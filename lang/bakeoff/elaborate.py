"""Flatten a design model and check it against an external anchor.

This is the only part of the bake-off that produces something IR-shaped, and
it exists for one reason: to prove the reference design is not the author's
opinion. `lang/examples/blinker-555.design.json` claims to be benchmark (a).
`ir/examples/blinker.ir.json` was authored under AMB-38, before this issue
existed, by a process that knew nothing about these parsers. Elaborating the
model and requiring it to reproduce that document is what makes the claim
checkable.

It is NOT an elaborator. There is no parameter evaluation, no `for`, no `if`,
no identity derivation, no hashing — R13 owns all of that. It resolves
hierarchy into paths and unions nets across module boundaries, which is the
minimum needed to compare a source-level model with an elaborated document.

NET FLATTENING is the whole of the interesting work. A module port is one node
that two scopes both name — the parent as `indicator.gnd`, the module itself
as `gnd` — so unioning on (instance path, port name) makes the two scopes'
nets merge without any special case. When a merged net carries labels from
several scopes, the outermost wins, which is the rule the IR states.
"""

import json
from decimal import Decimal

from .model import REPO_ROOT, DesignModel
from .quantities import base_bounds, quantity_from_ir, to_base


class AnchorError(AssertionError):
    """The model and the artifact it claims to transcribe disagree."""


def flatten(model: DesignModel) -> dict:
    """Resolve hierarchy into paths, and nets across module boundaries."""
    instances: list[dict] = []
    # (path, port) -> union-find parent; labels maps a root to (depth, name).
    parent: dict[tuple[str, str], tuple[str, str]] = {}
    labels: dict[tuple[str, str], list[tuple[int, str, dict]]] = {}

    def find(node):
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    def walk(module, prefix: str, depth: int) -> None:
        for inst in module.instances:
            path = f"{prefix}/{inst.name}"
            record = {
                "path": path,
                "kind": inst.kind,
                "parameters": inst.parameters,
                "dnp": inst.dnp,
                "exclude_from_bom": inst.exclude_from_bom,
                "board_only": inst.board_only,
                "hardware_kind": inst.hardware_kind,
                "part": inst.part,
            }
            if inst.kind == "module":
                child = model.module(inst.definition)
                record["definition"] = child.qualified_name
                record["ports"] = child.ports
                instances.append(record)
                walk(child, path, depth + 1)
            else:
                record["definition"] = inst.definition
                record["ports"] = inst.ports
                instances.append(record)

        for net in module.nets:
            nodes = []
            for member in net.members:
                if "." in member:
                    owner, port = member.split(".", 1)
                    nodes.append((f"{prefix}/{owner}", port))
                else:
                    # One of this module's own ports. Its node is (this
                    # module's own path, port), which is the SAME node the
                    # parent named as `<instance>.<port>` — so the two scopes'
                    # nets merge with no special case.
                    nodes.append((prefix or "/", member))
            for node in nodes[1:]:
                union(nodes[0], node)
            if net.name:
                labels.setdefault(find(nodes[0]), []).append(
                    (
                        depth,
                        net.name,
                        {
                            "ground_domain": net.ground_domain,
                            "voltage_domain": net.voltage_domain,
                        },
                    )
                )

    root = model.root()
    instances.append(
        {
            "path": "/",
            "kind": "module",
            "definition": root.qualified_name,
            "parameters": {},
            "ports": root.ports,
            "dnp": False,
            "exclude_from_bom": False,
            "board_only": False,
            "hardware_kind": None,
            "part": None,
        }
    )
    walk(root, "", 0)

    groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for node in list(parent):
        groups.setdefault(find(node), []).append(node)

    nets: list[dict] = []
    connections: list[dict] = []
    for representative, members in groups.items():
        candidates = labels.get(representative, [])
        if not candidates:
            raise AnchorError(
                "a flattened net carries no label: "
                + ", ".join(f"{path}.{port}" for path, port in sorted(members))
                + ". Deriving a name for it is I2's rule, which the bake-off "
                "deliberately does not implement — label the net in the model."
            )
        shallowest = min(depth for depth, _, _ in candidates)
        outermost = sorted(name for depth, name, _ in candidates if depth == shallowest)
        if len(outermost) > 1:
            raise AnchorError(
                f"one flattened net carries two outermost labels: {', '.join(outermost)}"
            )
        name = outermost[0]
        attributes = {"ground_domain": None, "voltage_domain": None}
        for _, _, values in candidates:
            for key, value in values.items():
                if value is None:
                    continue
                if attributes[key] not in (None, value):
                    raise AnchorError(
                        f"net {name!r} is given two different {key} values: "
                        f"{attributes[key]!r} and {value!r}"
                    )
                attributes[key] = value
        net = {"name": name}
        net.update({k: v for k, v in attributes.items() if v})
        nets.append(net)
        for path, port in members:
            connections.append({"net": name, "instance": path, "port": port})

    assertions = [
        {
            "path": f"/{a.name}",
            "tier": a.tier,
            "measurement": a.measurement,
            "subject": a.subject,
            "unit": a.unit,
            "min": a.minimum,
            "max": a.maximum,
        }
        for a in model.assertions
    ]

    # Two DISTINCT nets that flatten to the same name is the silent-wrong-answer
    # case this whole design treats as the cardinal sin: a module instantiated
    # twice gives each copy its own internal net, both carrying the label the
    # module wrote, and any backend keying on name would fuse them into one.
    # Deriving a unique name for them is I2's identity rule, which the bake-off
    # deliberately does not implement - so this refuses rather than guesses.
    seen: dict[str, int] = {}
    for net in nets:
        seen[net["name"]] = seen.get(net["name"], 0) + 1
    collisions = sorted(name for name, count in seen.items() if count > 1)
    if collisions:
        raise AnchorError(
            "flattening produced two distinct nets with the same name: "
            + ", ".join(collisions)
            + ". A module instantiated more than once gives each copy its own "
            "internal nets, and disambiguating their labels is I2's derived-"
            "identity rule (AMB-62/R27), which this prototype does not "
            "implement. Label the nets uniquely, or keep the module to one "
            "instantiation in a bake-off fixture."
        )

    return {
        "instances": sorted(instances, key=lambda i: i["path"]),
        "nets": sorted(nets, key=lambda n: n["name"]),
        "connections": sorted(
            connections, key=lambda c: (c["net"], c["instance"], c["port"])
        ),
        "assertions": sorted(assertions, key=lambda a: a["path"]),
    }


# --------------------------------------------------------------------------
# IR anchor
# --------------------------------------------------------------------------


def _ir_value_key(raw) -> tuple:
    """Canonical key for an IR ParameterValue, comparable with a model Value."""
    if isinstance(raw, bool):
        return ("b", raw)
    if isinstance(raw, int):
        return ("i", raw)
    if isinstance(raw, str):
        return ("s", raw)
    quantity = quantity_from_ir(raw["value"], raw["unit"], raw.get("tolerance"))
    return ("q",) + quantity.key()


def _model_value_key(value) -> tuple:
    return value.key()


def _fail(problems: list[str]) -> None:
    if problems:
        raise AnchorError(
            f"{len(problems)} disagreement(s) with the anchor:\n  "
            + "\n  ".join(problems[:20])
            + ("" if len(problems) <= 20 else f"\n  ... and {len(problems) - 20} more")
        )


def check_netlist_ir(model: DesignModel, path: str) -> dict:
    """Require the flattened model to reproduce an IR document.

    Compares instances, nets, connections and assertions. Deliberately does
    NOT compare the header: `design_hash`, `source_hash` and `generator` are
    outputs of an elaborator that does not exist yet, and asserting on them
    would be asserting on nothing.
    """
    with open(REPO_ROOT / path, encoding="utf-8") as handle:
        ir = json.load(handle)

    flat = flatten(model)
    problems: list[str] = []

    ir_instances = {i["path"]: i for i in ir["instances"]}
    my_instances = {i["path"]: i for i in flat["instances"]}
    for missing in sorted(set(ir_instances) - set(my_instances)):
        problems.append(f"instance {missing}: in the IR, absent from the model")
    for extra in sorted(set(my_instances) - set(ir_instances)):
        problems.append(f"instance {extra}: in the model, absent from the IR")

    for path_id in sorted(set(ir_instances) & set(my_instances)):
        want, got = ir_instances[path_id], my_instances[path_id]
        if want["kind"] != got["kind"]:
            problems.append(
                f"instance {path_id}: kind {got['kind']!r} vs IR {want['kind']!r}"
            )
        if want["definition"] != got["definition"]:
            problems.append(
                f"instance {path_id}: definition {got['definition']!r} vs IR "
                f"{want['definition']!r}"
            )
        for flag in ("dnp", "exclude_from_bom", "board_only"):
            if bool(want[flag]) != bool(got[flag]):
                problems.append(f"instance {path_id}: {flag} {got[flag]} vs IR {want[flag]}")
        if want.get("hardware_kind") != got.get("hardware_kind"):
            problems.append(
                f"instance {path_id}: hardware_kind {got.get('hardware_kind')!r} vs IR "
                f"{want.get('hardware_kind')!r}"
            )

        want_params = {k: _ir_value_key(v) for k, v in want.get("parameters", {}).items()}
        got_params = {k: _model_value_key(v) for k, v in got["parameters"].items()}
        if want_params != got_params:
            problems.append(
                f"instance {path_id}: parameters differ\n"
                f"      model {sorted(got_params.items())}\n"
                f"      IR    {sorted(want_params.items())}"
            )

        want_ports = [
            (p["name"], p["role"], tuple(p.get("pin_numbers", ())))
            for p in want.get("ports", [])
        ]
        got_ports = [(p.name, p.role, p.pin_numbers) for p in got["ports"]]
        if sorted(want_ports) != sorted(got_ports):
            problems.append(
                f"instance {path_id}: ports differ\n"
                f"      model {sorted(got_ports)}\n"
                f"      IR    {sorted(want_ports)}"
            )

        want_part, got_part = want.get("part"), got["part"]
        if (want_part is None) != (got_part is None):
            problems.append(f"instance {path_id}: part binding present in only one")
        elif want_part is not None:
            if want_part["binding"] != got_part.binding:
                problems.append(
                    f"instance {path_id}: binding {got_part.binding!r} vs IR "
                    f"{want_part['binding']!r}"
                )
            if want_part.get("lockfile_key") != got_part.lockfile_key:
                problems.append(
                    f"instance {path_id}: lockfile key {got_part.lockfile_key!r} vs IR "
                    f"{want_part.get('lockfile_key')!r}"
                )
            want_c = {
                k: _ir_value_key(v) for k, v in want_part.get("constraints", {}).items()
            }
            got_c = {k: _model_value_key(v) for k, v in got_part.constraints.items()}
            if want_c != got_c:
                problems.append(
                    f"instance {path_id}: part constraints differ\n"
                    f"      model {sorted(got_c.items())}\n"
                    f"      IR    {sorted(want_c.items())}"
                )

    ir_nets = {n["name"]: n for n in ir["nets"]}
    my_nets = {n["name"]: n for n in flat["nets"]}
    for missing in sorted(set(ir_nets) - set(my_nets)):
        problems.append(f"net {missing}: in the IR, absent from the model")
    for extra in sorted(set(my_nets) - set(ir_nets)):
        problems.append(f"net {extra}: in the model, absent from the IR")
    for name in sorted(set(ir_nets) & set(my_nets)):
        for attribute in ("ground_domain", "voltage_domain"):
            if ir_nets[name].get(attribute) != my_nets[name].get(attribute):
                problems.append(
                    f"net {name}: {attribute} {my_nets[name].get(attribute)!r} vs IR "
                    f"{ir_nets[name].get(attribute)!r}"
                )

    ir_connections = {
        (c["net"], c["port"]["instance"], c["port"]["port"]) for c in ir["connections"]
    }
    my_connections = {(c["net"], c["instance"], c["port"]) for c in flat["connections"]}
    for missing in sorted(ir_connections - my_connections):
        problems.append(f"connection {missing[1]}.{missing[2]} on {missing[0]}: IR only")
    for extra in sorted(my_connections - ir_connections):
        problems.append(f"connection {extra[1]}.{extra[2]} on {extra[0]}: model only")

    ir_assertions = {a["path"]: a for a in ir["assertions"]}
    my_assertions = {a["path"]: a for a in flat["assertions"]}
    for missing in sorted(set(ir_assertions) ^ set(my_assertions)):
        problems.append(f"assertion {missing}: present in only one of the two")
    for path_id in sorted(set(ir_assertions) & set(my_assertions)):
        want, got = ir_assertions[path_id], my_assertions[path_id]
        if want["tier"] != got["tier"] or want["measurement"] != got["measurement"]:
            problems.append(f"assertion {path_id}: tier or measurement differs")
        subject = want["subject"]
        if "net" not in subject or subject["net"] != got["subject"]:
            problems.append(f"assertion {path_id}: probes a different subject")
        bounds = want["bounds"]
        if bounds["unit"] != got["unit"]:
            problems.append(
                f"assertion {path_id}: unit {got['unit']!r} vs IR {bounds['unit']!r}"
            )
        for key in ("min", "max"):
            mine = None if got[key] is None else Decimal(got[key])
            theirs = None if bounds.get(key) is None else Decimal(str(bounds[key]))
            if mine != theirs:
                problems.append(
                    f"assertion {path_id}: {key} {mine} vs IR {theirs}"
                )

    _fail(problems)
    return {
        "anchor": path,
        "instances": len(flat["instances"]),
        "nets": len(flat["nets"]),
        "connections": len(flat["connections"]),
        "assertions": len(flat["assertions"]),
    }


def check_parts_yaml(model: DesignModel, path: str, refdes_map: dict) -> dict:
    """Require the model's component set to match a committed BOM exactly.

    Benchmark (c) has no IR document, so its anchor is the parts list AMB-39
    authored: sixty placements, three of them DNP. The map from refdes to
    instance path is written out rather than derived by lowercasing, so a BOM
    line no instance covers fails loudly instead of matching something close.

    Parsed with a deliberately small line reader rather than PyYAML: the BOM
    is only needed for `ref:` and `dnp:` and the gate must run wherever the
    rest of `make check` runs, PyYAML installed or not.
    """
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    bom: dict[str, bool] = {}
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ref:"):
            current = stripped.split(":", 1)[1].strip()
            bom[current] = False
        elif stripped.startswith("dnp:") and current:
            bom[current] = stripped.split(":", 1)[1].strip().lower() == "true"

    flat = flatten(model)
    components = {i["path"] for i in flat["instances"] if i["kind"] == "component"}
    by_path = {i["path"]: i for i in flat["instances"]}

    problems: list[str] = []
    for refdes in sorted(set(bom) - set(refdes_map)):
        problems.append(f"BOM {refdes}: no entry in the model's refdes_map")
    for refdes in sorted(set(refdes_map) - set(bom)):
        problems.append(f"refdes_map {refdes}: not in the BOM")

    mapped: set[str] = set()
    for refdes in sorted(set(bom) & set(refdes_map)):
        target = refdes_map[refdes]
        mapped.add(target)
        if target not in components:
            problems.append(f"BOM {refdes}: maps to {target}, which is not a component")
            continue
        if by_path[target]["dnp"] != bom[refdes]:
            problems.append(
                f"BOM {refdes}: dnp {by_path[target]['dnp']} vs BOM {bom[refdes]}"
            )
    for orphan in sorted(components - mapped):
        problems.append(f"component {orphan}: no BOM line maps to it")

    _fail(problems)
    return {
        "anchor": path,
        "placements": len(bom),
        "dnp": sum(1 for value in bom.values() if value),
        "instances": len(flat["instances"]),
        "nets": len(flat["nets"]),
        "connections": len(flat["connections"]),
    }


def check_anchor(model: DesignModel) -> dict | None:
    """Run whichever anchor the model declares, or report that it has none."""
    anchor = model.anchor
    if not anchor:
        return None
    if anchor["kind"] == "netlist-ir":
        return check_netlist_ir(model, anchor["path"])
    return check_parts_yaml(model, anchor["path"], anchor.get("refdes_map", {}))
