"""The arm-neutral design model: what every arm has to say the same way.

The bake-off compares grammars, which means the one thing that must NOT vary
between arms is the design being described. This module owns that design:
loading it, checking it is internally coherent, ordering it canonically, and
deciding when two of them are the same design.

Every arm is a pair of functions over this type — `render(model) -> source`
and `parse(source) -> model`. Three properties follow, and the measurement is
worthless without all three:

  ROUND TRIP     parse(render(m)) == m, per arm, per variant. An arm whose
                 printer and parser disagree is measuring a language nobody
                 can read back.
  AGREEMENT      parse_A(src_A) == parse_B(src_B) == parse_S(src_S) == m.
                 Without this, "arm B is 18% cheaper" might only mean arm B
                 was given less to say.
  ANCHORING      m, elaborated and flattened, reproduces an artifact authored
                 under a different issue. Without this, the reference is just
                 the author's opinion wearing a schema.

Equality is STRUCTURAL AND DIMENSIONAL, not textual: instance order, key
order and unit spelling do not matter, `100kohm` equals `100000ohm`, and
unlabelled nets are identified by their member sets. Anything coarser would
let a real difference hide; anything finer would fail arms for spelling.
"""

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from .quantities import Quantity, QuantityError, parse_quantity, unit_dimension

MODEL_VERSION = 0

# The T2 pin-role lattice and the L9 hardware kinds, as the parsers need them.
# lang/tests/test_bakeoff.py reads the enums out of BOTH JSON Schemas and fails
# if either tuple has drifted from them, so these cannot quietly diverge from
# the IR the way two hand-maintained lists otherwise do.
PIN_ROLES = (
    "power_in",
    "power_out",
    "passive",
    "bidirectional",
    "open_drain",
    "open_collector",
    "tri_state",
    "input",
    "output",
    "nc",
)

HARDWARE_KINDS = (
    "mounting_hole",
    "fiducial",
    "artwork",
    "test_point",
    "grounded_mounting_hole",
)

MEASUREMENT_KINDS = (
    "operating_point",
    "ripple",
    "frequency",
    "period",
    "duty_cycle",
    "gain",
    "bandwidth",
    "rise_time",
    "fall_time",
    "prop_delay",
    "settling_time",
    "overshoot",
    "power_avg",
    "power_rms",
    "efficiency",
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class ModelError(ValueError):
    """The model is not a coherent design.

    Distinct from a schema violation: the schema decides shape, this decides
    whether the shape describes something that could exist.
    """


# --------------------------------------------------------------------------
# Values
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Value:
    """A tagged parameter value: quantity, string, integer or flag.

    Tagged rather than inferred from the JSON type, because `"0805"` and
    `805` are one keystroke apart and mean entirely different things — a
    package code and a count. With the tag, that typo cannot be written.
    """

    tag: str
    quantity: Quantity | None = None
    text: str | None = None
    number: int | None = None
    flag: bool | None = None

    @staticmethod
    def from_json(raw: dict, where: str) -> "Value":
        if not isinstance(raw, dict) or len(raw) != 1:
            raise ModelError(
                f"{where}: a value is exactly one of {{'q','s','i','b'}}, got {raw!r}"
            )
        (tag, payload), = raw.items()
        if tag == "q":
            try:
                return Value(tag="q", quantity=parse_quantity(payload))
            except QuantityError as exc:
                raise ModelError(f"{where}: {exc}") from None
        if tag == "s":
            if not isinstance(payload, str) or not payload:
                raise ModelError(f"{where}: 's' takes a non-empty string")
            return Value(tag="s", text=payload)
        if tag == "i":
            if not isinstance(payload, int) or isinstance(payload, bool):
                raise ModelError(f"{where}: 'i' takes an integer")
            return Value(tag="i", number=payload)
        if tag == "b":
            if not isinstance(payload, bool):
                raise ModelError(f"{where}: 'b' takes a boolean")
            return Value(tag="b", flag=payload)
        raise ModelError(f"{where}: unknown value tag {tag!r}")

    def to_json(self) -> dict:
        if self.tag == "q":
            return {"q": self.quantity.text}
        if self.tag == "s":
            return {"s": self.text}
        if self.tag == "i":
            return {"i": self.number}
        return {"b": self.flag}

    def key(self) -> tuple:
        if self.tag == "q":
            return ("q",) + self.quantity.key()
        if self.tag == "s":
            return ("s", self.text)
        if self.tag == "i":
            return ("i", self.number)
        return ("b", self.flag)

    def render(self) -> str:
        """Surface spelling, shared by every arm (see quantities.py)."""
        if self.tag == "q":
            return self.quantity.text
        if self.tag == "s":
            return '"' + self.text + '"'
        if self.tag == "i":
            return str(self.number)
        return "true" if self.flag else "false"


def _values_from_json(raw: dict | None, where: str) -> dict[str, Value]:
    if raw is None:
        return {}
    return {name: Value.from_json(v, f"{where}.{name}") for name, v in raw.items()}


def _values_key(values: dict[str, Value]) -> tuple:
    return tuple((name, values[name].key()) for name in sorted(values))


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Port:
    name: str
    role: str
    pin_numbers: tuple[str, ...] = ()

    def key(self) -> tuple:
        return (self.name, self.role, self.pin_numbers)


@dataclass(frozen=True)
class PartBinding:
    binding: str
    constraints: dict[str, Value] = field(default_factory=dict)
    lockfile_key: str | None = None

    def key(self) -> tuple:
        return (self.binding, self.lockfile_key, _values_key(self.constraints))


@dataclass(frozen=True)
class Instance:
    name: str
    kind: str
    definition: str
    parameters: dict[str, Value] = field(default_factory=dict)
    ports: tuple[Port, ...] = ()
    part: PartBinding | None = None
    hardware_kind: str | None = None
    dnp: bool = False
    exclude_from_bom: bool = False
    board_only: bool = False

    def key(self) -> tuple:
        return (
            self.name,
            self.kind,
            self.definition,
            _values_key(self.parameters),
            tuple(p.key() for p in self.ports),
            self.part.key() if self.part else None,
            self.hardware_kind,
            self.dnp,
            self.exclude_from_bom,
            self.board_only,
        )


@dataclass(frozen=True)
class Net:
    members: tuple[str, ...]
    name: str | None = None
    ground_domain: str | None = None
    voltage_domain: str | None = None

    def key(self) -> tuple:
        # An unlabelled net has no identity beyond the ports it joins, which
        # is exactly what a net IS. Labelled nets keep their label in the key
        # so a renamed rail is a difference, not a coincidence.
        return (self.name, self.members, self.ground_domain, self.voltage_domain)

    def sort_key(self) -> tuple:
        # Labelled nets first, in name order, then unlabelled in member order:
        # a total order with no ties, so serialization is deterministic.
        return (0, self.name, ()) if self.name else (1, "", self.members)


@dataclass(frozen=True)
class Module:
    name: str
    qualified_name: str
    ports: tuple[Port, ...] = ()
    instances: tuple[Instance, ...] = ()
    nets: tuple[Net, ...] = ()

    def key(self) -> tuple:
        # `qualified_name` is deliberately absent. It is the name this module
        # elaborates to in the IR, and no arm can recover it from source: the
        # prototypes have no import syntax, because L4 owns imports and
        # inventing one for the bake-off would measure a construct neither
        # candidate is proposing. Keeping it in the key would fail every arm
        # for not knowing something the surface does not carry.
        return (
            self.name,
            tuple(p.key() for p in self.ports),
            tuple(i.key() for i in self.instances),
            tuple(n.key() for n in self.nets),
        )

    def instance(self, name: str) -> Instance | None:
        for inst in self.instances:
            if inst.name == name:
                return inst
        return None

    def port(self, name: str) -> Port | None:
        for port in self.ports:
            if port.name == name:
                return port
        return None


@dataclass(frozen=True)
class Assertion:
    name: str
    tier: str
    measurement: str
    subject: str
    unit: str
    minimum: str | None
    maximum: str | None

    def key(self) -> tuple:
        return (
            self.name,
            self.tier,
            self.measurement,
            self.subject,
            self.unit,
            self.minimum,
            self.maximum,
        )


@dataclass(frozen=True)
class DesignModel:
    design_id: str
    root_module: str
    modules: tuple[Module, ...]
    assertions: tuple[Assertion, ...] = ()
    source_benchmark: str | None = None
    anchor: dict | None = None
    notes: str = ""

    def key(self) -> tuple:
        """Everything that makes this the design it is.

        `design_id`, `notes`, `source_benchmark` and `anchor` are provenance
        about the fixture, not facts about the circuit, so they stay out: an
        arm that round-trips the design perfectly must not fail because the
        source carries no corpus key or comment about where it came from.

        `root_module` stays in, because which module is the top IS a design
        fact — and a recoverable one: it is the module nothing instantiates.
        """
        return (
            self.root_module,
            tuple(m.key() for m in self.modules),
            tuple(a.key() for a in self.assertions),
        )

    def __eq__(self, other) -> bool:
        return isinstance(other, DesignModel) and self.key() == other.key()

    def __hash__(self) -> int:
        return hash(self.key())

    def module(self, name: str) -> Module | None:
        for mod in self.modules:
            if mod.name == name:
                return mod
        return None

    def root(self) -> Module:
        mod = self.module(self.root_module)
        if mod is None:
            raise ModelError(f"root module {self.root_module!r} is not defined")
        return mod


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def _port_from_json(raw: dict, where: str) -> Port:
    pins = tuple(sorted(raw.get("pin_numbers", ())))
    return Port(name=raw["name"], role=raw["role"], pin_numbers=pins)


def _instance_from_json(raw: dict, where: str) -> Instance:
    part_raw = raw.get("part")
    part = None
    if part_raw is not None:
        part = PartBinding(
            binding=part_raw["binding"],
            constraints=_values_from_json(
                part_raw.get("constraints"), f"{where}.part.constraints"
            ),
            lockfile_key=part_raw.get("lockfile_key"),
        )
    return Instance(
        name=raw["name"],
        kind=raw["kind"],
        definition=raw["definition"],
        parameters=_values_from_json(raw.get("parameters"), f"{where}.parameters"),
        ports=tuple(
            sorted(
                (_port_from_json(p, where) for p in raw.get("ports", ())),
                key=lambda p: p.name,
            )
        ),
        part=part,
        hardware_kind=raw.get("hardware_kind"),
        dnp=bool(raw.get("dnp", False)),
        exclude_from_bom=bool(raw.get("exclude_from_bom", False)),
        board_only=bool(raw.get("board_only", False)),
    )


def _net_from_json(raw: dict) -> Net:
    return Net(
        name=raw.get("name"),
        members=tuple(sorted(raw["members"])),
        ground_domain=raw.get("ground_domain"),
        voltage_domain=raw.get("voltage_domain"),
    )


def model_from_json(raw: dict) -> DesignModel:
    """Build a model from parsed JSON, sorting everything canonically."""
    if raw.get("model_version") != MODEL_VERSION:
        raise ModelError(
            f"model_version must be {MODEL_VERSION}, got {raw.get('model_version')!r}"
        )
    if raw.get("stability") != "unstable":
        raise ModelError("stability must be the constant \"unstable\"")

    modules = []
    for mod_raw in raw["modules"]:
        where = f"modules.{mod_raw.get('name')}"
        modules.append(
            Module(
                name=mod_raw["name"],
                qualified_name=mod_raw["qualified_name"],
                ports=tuple(
                    sorted(
                        (_port_from_json(p, where) for p in mod_raw.get("ports", ())),
                        key=lambda p: p.name,
                    )
                ),
                instances=tuple(
                    sorted(
                        (
                            _instance_from_json(i, f"{where}.{i.get('name')}")
                            for i in mod_raw.get("instances", ())
                        ),
                        key=lambda i: i.name,
                    )
                ),
                nets=tuple(
                    sorted(
                        (_net_from_json(n) for n in mod_raw.get("nets", ())),
                        key=lambda n: n.sort_key(),
                    )
                ),
            )
        )

    assertions = tuple(
        sorted(
            (
                Assertion(
                    name=a["name"],
                    tier=a["tier"],
                    measurement=a["measurement"],
                    subject=a["subject"],
                    unit=a["bounds"]["unit"],
                    minimum=a["bounds"].get("min"),
                    maximum=a["bounds"].get("max"),
                )
                for a in raw.get("assertions", ())
            ),
            key=lambda a: a.name,
        )
    )

    model = DesignModel(
        design_id=raw["design_id"],
        root_module=raw["root_module"],
        modules=tuple(sorted(modules, key=lambda m: m.name)),
        assertions=assertions,
        source_benchmark=raw.get("source_benchmark"),
        anchor=raw.get("anchor"),
        notes=raw.get("notes", ""),
    )
    validate(model)
    return model


def load_model(path: Path) -> DesignModel:
    with open(path, encoding="utf-8") as handle:
        return model_from_json(json.load(handle))


def corpus_dir() -> Path:
    return REPO_ROOT / "lang" / "examples"


def load_corpus() -> dict[str, DesignModel]:
    """Every design model in the corpus, keyed by design_id.

    Negative controls under examples/negative/ are excluded: they exist to be
    rejected by the schema, and loading them here would fail the corpus.
    """
    designs = {}
    for path in sorted(corpus_dir().glob("*.design.json")):
        model = load_model(path)
        if model.design_id in designs:
            raise ModelError(f"duplicate design_id {model.design_id!r} in the corpus")
        designs[model.design_id] = model
    return designs


# --------------------------------------------------------------------------
# Coherence checks
# --------------------------------------------------------------------------

# Kept in step with ir/netlist-ir.schema.json's Assertion tier/measurement
# rule. A static-tier assertion naming a kind that needs a simulator is
# rejected rather than silently promoted to the dynamic tier: silent
# promotion is how an unmeasured assertion comes to look measured.
STATIC_MEASUREMENTS = frozenset(
    {"operating_point", "power_avg", "power_rms", "efficiency"}
)

PINLESS_HARDWARE = frozenset({"mounting_hole", "fiducial", "artwork"})


def _resolve_endpoint(model: DesignModel, module: Module, ref: str, where: str) -> tuple[str, str]:
    """Resolve `instance.port` or a bare own-port name, or raise.

    Returns (owner, port) where owner is "" for one of this module's own
    ports. Resolving through the DEFINITION for module instances rather than
    through a repeated copy of the interface is deliberate: an instance that
    listed its own ports could list them wrongly.
    """
    if "." in ref:
        inst_name, port_name = ref.split(".", 1)
        inst = module.instance(inst_name)
        if inst is None:
            raise ModelError(
                f"{where}: {ref!r} names instance {inst_name!r}, which "
                f"module {module.name!r} does not declare"
            )
        if inst.kind == "module":
            target = model.module(inst.definition)
            if target is None:
                raise ModelError(
                    f"{where}: instance {inst_name!r} elaborates module "
                    f"{inst.definition!r}, which is not defined"
                )
            port = target.port(port_name)
            owner_desc = f"module {inst.definition!r}"
        else:
            port = next((p for p in inst.ports if p.name == port_name), None)
            owner_desc = f"component {inst.definition!r}"
        if port is None:
            raise ModelError(
                f"{where}: {owner_desc} has no port {port_name!r} "
                f"(instance {inst_name!r})"
            )
        if port.role == "nc":
            raise ModelError(
                f"{where}: {ref!r} has role 'nc'. A declared no-connect that "
                "joins a net is a contradiction, not a warning."
            )
        return inst_name, port_name

    port = module.port(ref)
    if port is None:
        raise ModelError(
            f"{where}: {ref!r} is neither `instance.port` nor a port of "
            f"module {module.name!r}"
        )
    if port.role == "nc":
        raise ModelError(f"{where}: own port {ref!r} has role 'nc' and cannot join a net")
    return "", ref


def validate(model: DesignModel) -> None:
    """Reject a model that is well-shaped but does not describe a design."""
    names = [m.name for m in model.modules]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ModelError(f"duplicate module definitions: {', '.join(duplicates)}")
    if model.root_module not in names:
        raise ModelError(f"root_module {model.root_module!r} is not among {names}")

    for module in model.modules:
        port_names = [p.name for p in module.ports]
        if len(set(port_names)) != len(port_names):
            raise ModelError(f"module {module.name!r} declares a port twice")

        inst_names = [i.name for i in module.instances]
        if len(set(inst_names)) != len(inst_names):
            raise ModelError(f"module {module.name!r} declares an instance twice")

        for inst in module.instances:
            where = f"{module.name}.{inst.name}"
            if inst.kind == "module":
                if model.module(inst.definition) is None:
                    raise ModelError(
                        f"{where}: instantiates undefined module {inst.definition!r}"
                    )
            else:
                if model.module(inst.definition) is not None:
                    raise ModelError(
                        f"{where}: kind is 'component' but {inst.definition!r} is a "
                        "module definition; a module cannot be instantiated as a leaf"
                    )
                own_ports = [p.name for p in inst.ports]
                if len(set(own_ports)) != len(own_ports):
                    raise ModelError(f"{where}: declares a port twice")
                if inst.hardware_kind in PINLESS_HARDWARE and inst.ports:
                    raise ModelError(
                        f"{where}: hardware_kind {inst.hardware_kind!r} is pinless "
                        "and must declare no ports"
                    )
            if inst.part is not None:
                if inst.part.binding == "abstract" and not inst.part.constraints:
                    raise ModelError(f"{where}: an abstract part needs constraints")
                if inst.part.binding == "abstract" and inst.part.lockfile_key:
                    raise ModelError(f"{where}: an abstract part has no lockfile key")
                if inst.part.binding == "resolved" and not inst.part.lockfile_key:
                    raise ModelError(f"{where}: a resolved part needs a lockfile key")

        labels = [n.name for n in module.nets if n.name]
        if len(set(labels)) != len(labels):
            raise ModelError(f"module {module.name!r} labels two nets the same")

        seen_endpoints: dict[tuple[str, str], str] = {}
        for net in module.nets:
            label = net.name or f"<unlabelled {','.join(net.members)}>"
            where = f"{module.name} net {label}"
            if len(set(net.members)) != len(net.members):
                raise ModelError(f"{where}: lists an endpoint twice")
            for ref in net.members:
                endpoint = _resolve_endpoint(model, module, ref, where)
                previous = seen_endpoints.get(endpoint)
                if previous is not None:
                    raise ModelError(
                        f"{where}: {ref!r} is already on net {previous}. A port "
                        "belongs to exactly one net; two nets touching one port "
                        "are one net."
                    )
                seen_endpoints[endpoint] = label

    # Unreachable definitions are dead weight in a token-cost measurement:
    # they would be rendered, counted, and mean nothing.
    reachable = set()
    frontier = [model.root_module]
    while frontier:
        current = frontier.pop()
        if current in reachable:
            continue
        reachable.add(current)
        module = model.module(current)
        for inst in module.instances:
            if inst.kind == "module":
                frontier.append(inst.definition)
    unreachable = sorted(set(names) - reachable)
    if unreachable:
        raise ModelError(
            f"module(s) {', '.join(unreachable)} are never instantiated from "
            f"{model.root_module!r}. Unreachable definitions inflate every "
            "arm's token count with source no design uses."
        )

    root = model.root()
    root_labels = {n.name for n in root.nets if n.name}
    seen_assertions = set()
    for assertion in model.assertions:
        if assertion.name in seen_assertions:
            raise ModelError(f"assertion {assertion.name!r} is declared twice")
        seen_assertions.add(assertion.name)
        if assertion.subject not in root_labels:
            raise ModelError(
                f"assertion {assertion.name!r} probes {assertion.subject!r}, which "
                f"is not a labelled net of {model.root_module!r}"
            )
        if assertion.unit != "1":
            unit_dimension(assertion.unit)
        if assertion.tier == "static" and assertion.measurement not in STATIC_MEASUREMENTS:
            raise ModelError(
                f"assertion {assertion.name!r} is static-tier but "
                f"{assertion.measurement!r} has no interval-arithmetic rule; the IR "
                "rejects this rather than promoting it to the dynamic tier"
            )
        if assertion.minimum is not None and assertion.maximum is not None:
            from decimal import Decimal

            if Decimal(assertion.minimum) > Decimal(assertion.maximum):
                raise ModelError(
                    f"assertion {assertion.name!r}: min exceeds max"
                )


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------


def _port_to_json(port: Port) -> dict:
    out = {"name": port.name, "role": port.role}
    if port.pin_numbers:
        out["pin_numbers"] = list(port.pin_numbers)
    return out


def _instance_to_json(inst: Instance) -> dict:
    out = {"name": inst.name, "kind": inst.kind, "definition": inst.definition}
    if inst.parameters:
        out["parameters"] = {k: inst.parameters[k].to_json() for k in sorted(inst.parameters)}
    if inst.kind == "component":
        out["ports"] = [_port_to_json(p) for p in inst.ports]
    if inst.part is not None:
        part = {"binding": inst.part.binding}
        if inst.part.lockfile_key:
            part["lockfile_key"] = inst.part.lockfile_key
        if inst.part.constraints:
            part["constraints"] = {
                k: inst.part.constraints[k].to_json() for k in sorted(inst.part.constraints)
            }
        out["part"] = part
    if inst.hardware_kind:
        out["hardware_kind"] = inst.hardware_kind
    for flag in ("dnp", "exclude_from_bom", "board_only"):
        if getattr(inst, flag):
            out[flag] = True
    return out


def model_to_json(model: DesignModel) -> dict:
    """Canonical JSON form. Round-trips through model_from_json unchanged."""
    out = {
        "model_version": MODEL_VERSION,
        "stability": "unstable",
        "design_id": model.design_id,
        "root_module": model.root_module,
    }
    if model.source_benchmark:
        out["source_benchmark"] = model.source_benchmark
    if model.anchor:
        out["anchor"] = model.anchor
    if model.notes:
        out["notes"] = model.notes
    out["modules"] = [
        {
            "name": m.name,
            "qualified_name": m.qualified_name,
            "ports": [_port_to_json(p) for p in m.ports],
            "instances": [_instance_to_json(i) for i in m.instances],
            "nets": [
                {
                    **({"name": n.name} if n.name else {}),
                    **({"ground_domain": n.ground_domain} if n.ground_domain else {}),
                    **({"voltage_domain": n.voltage_domain} if n.voltage_domain else {}),
                    "members": list(n.members),
                }
                for n in m.nets
            ],
        }
        for m in model.modules
    ]
    if model.assertions:
        out["assertions"] = [
            {
                "name": a.name,
                "tier": a.tier,
                "measurement": a.measurement,
                "subject": a.subject,
                "bounds": {
                    "unit": a.unit,
                    **({"min": a.minimum} if a.minimum is not None else {}),
                    **({"max": a.maximum} if a.maximum is not None else {}),
                },
            }
            for a in model.assertions
        ]
    return out


def diff(expected: DesignModel, actual: DesignModel, limit: int = 12) -> list[str]:
    """Human-readable differences, for a gate's diagnostics.

    Compares the same canonical keys equality uses, so a reported difference
    is always a real one and an empty list always means equal.
    """
    if expected == actual:
        return []

    notes: list[str] = []
    if expected.design_id != actual.design_id:
        notes.append(f"design_id: expected {expected.design_id!r}, got {actual.design_id!r}")
    if expected.root_module != actual.root_module:
        notes.append(
            f"root_module: expected {expected.root_module!r}, got {actual.root_module!r}"
        )

    exp_mods = {m.name: m for m in expected.modules}
    act_mods = {m.name: m for m in actual.modules}
    for name in sorted(set(exp_mods) - set(act_mods)):
        notes.append(f"module {name!r}: missing")
    for name in sorted(set(act_mods) - set(exp_mods)):
        notes.append(f"module {name!r}: unexpected")

    for name in sorted(set(exp_mods) & set(act_mods)):
        exp, act = exp_mods[name], act_mods[name]
        exp_inst = {i.name: i for i in exp.instances}
        act_inst = {i.name: i for i in act.instances}
        for inst in sorted(set(exp_inst) - set(act_inst)):
            notes.append(f"{name}.{inst}: instance missing")
        for inst in sorted(set(act_inst) - set(exp_inst)):
            notes.append(f"{name}.{inst}: instance unexpected")
        for inst in sorted(set(exp_inst) & set(act_inst)):
            if exp_inst[inst].key() != act_inst[inst].key():
                notes.append(
                    f"{name}.{inst}: differs\n"
                    f"    expected {exp_inst[inst].key()}\n"
                    f"    actual   {act_inst[inst].key()}"
                )
        exp_nets = {n.sort_key(): n for n in exp.nets}
        act_nets = {n.sort_key(): n for n in act.nets}
        for k in sorted(set(exp_nets) - set(act_nets)):
            n = exp_nets[k]
            notes.append(f"{name} net {n.name or tuple(n.members)}: missing")
        for k in sorted(set(act_nets) - set(exp_nets)):
            n = act_nets[k]
            notes.append(f"{name} net {n.name or tuple(n.members)}: unexpected")
        for k in sorted(set(exp_nets) & set(act_nets)):
            if exp_nets[k].key() != act_nets[k].key():
                notes.append(
                    f"{name} net {exp_nets[k].name or tuple(exp_nets[k].members)}: "
                    f"expected {exp_nets[k].key()}, got {act_nets[k].key()}"
                )

    exp_a = {a.name: a for a in expected.assertions}
    act_a = {a.name: a for a in actual.assertions}
    for n in sorted(set(exp_a) - set(act_a)):
        notes.append(f"assertion {n!r}: missing")
    for n in sorted(set(act_a) - set(exp_a)):
        notes.append(f"assertion {n!r}: unexpected")
    for n in sorted(set(exp_a) & set(act_a)):
        if exp_a[n].key() != act_a[n].key():
            notes.append(
                f"assertion {n!r}: expected {exp_a[n].key()}, got {act_a[n].key()}"
            )

    if not notes:
        # Equality is defined by key(), so an inequality the structural walk
        # cannot name means the walk is incomplete. Saying so is better than
        # returning [] and letting a caller read that as "equal".
        notes.append(
            "models differ but the structural diff found no difference; "
            "DesignModel.key() and diff() have drifted apart"
        )
    if len(notes) > limit:
        notes = notes[:limit] + [f"... and {len(notes) - limit} more difference(s)"]
    return notes
