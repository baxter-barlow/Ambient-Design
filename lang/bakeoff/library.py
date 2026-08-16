"""The component library the T9 inference rules draw on.

T9 asks what "inference beyond cheap local defaulting" would buy, and says the
annotation tax is to be measured in the bake-off before anyone decides. A
number for that tax only means something if the inference rules are WRITTEN
DOWN and EXECUTABLE, so here they are, in full:

  T9-1  library_ports
        A component's port names, T2 roles and footprint pin numbers come
        from its library definition, not from the design source. A design
        that instantiates an NE555 does not restate its eight pins.

  T9-2  constraint_from_parameter
        For the attributes a component declares RESOLVER-VISIBLE, a part
        constraint whose name and value equal a same-named instance parameter
        is recovered from that parameter. `r_a.resistance = 100kohm +/- 1%`
        already says what the resolver needs; writing it again under
        `part.constraints` is pure duplication.

        The resolver-visible set is per component and declared, not "every
        parameter". `forward_voltage` is a parameter of an LED and is not one
        of its part constraints, so a blanket rule would invent a constraint
        on the way back and the round trip would fail — which is exactly how
        this was caught.

  T9-3  hardware_flags
        `hardware_kind` and the L9 flags it implies come from the library —
        but ONLY when the source said nothing about them at all. An earlier
        version OR-ed the instance's flags with the library's, so a design
        that deliberately kept a test point IN the BOM had that override
        silently reverted on the way back in: a BOM flag flipping with no way
        to say otherwise in source. Presence is now tracked separately from
        value, so "the source was silent" and "the source said false" are
        different states.

There are deliberately NO value defaults ("a resistor is 0402", "a resistor is
0.25 W"). They looked like the biggest saving available and they are a trap:
the right default for benchmark (a)'s through-hole build is wrong for
benchmark (c)'s SMD build, so a library carrying one would hand the tax
measurement a number that depends on which design happens to be in the corpus.
A rule that only pays off when the corpus agrees with it is not an inference
rule, it is a coincidence.

THE AGGREGATE IS NOT A LOWER BOUND, and an earlier version of this docstring
said it was. Decomposing it settles the question: T9-1 alone is 59-77% of the
total, and T9-1 is not inference — it is a component library supplying a pin
list, which L2, D3 and D5 give unconditionally and which no candidate grammar
would ever have charged an author for. The `explicit` denominator that
includes it describes a language nobody proposed.

Three biases, all of them now stated rather than one:

  UP    counting T9-1 as inference at all
  UP    benchmark (c) is built so every instance is port-recoverable (see
        examples/make_esp32_model.py), which maximises T9-1 specifically
  DOWN  no value defaults, so a real checker recovers more than T9-2 does

The T9-2 delta — 4.3-7.0% — is the reading that answers T9's actual question,
and `bakeoff measure` reports the three separately for that reason. R59 at M2
re-measures against the real checker.

This library is a bake-off fixture standing in for D3 part data. It is not the
D5 seed library and nothing outside lang/ may read it.
"""

from contextlib import contextmanager
from dataclasses import dataclass

from .model import Instance, Port


@dataclass(frozen=True)
class ComponentDef:
    """A library component: its interface and the L9 facts its kind implies."""

    ports: tuple[Port, ...]
    hardware_kind: str | None = None
    exclude_from_bom: bool = False
    board_only: bool = False
    # Attributes this component exposes to the part resolver. T9-2 recovers a
    # constraint only for a name in here, which is what makes the rule
    # invertible: the parser knows exactly which constraints to put back.
    constraint_attributes: frozenset[str] = frozenset()


def _p(name: str, role: str, *pins: str) -> Port:
    return Port(name=name, role=role, pin_numbers=tuple(sorted(pins)))


# Keyed by the fully qualified definition name that appears in the model and
# in the IR. Closed: instantiating a definition that is not here is an error
# in every arm, which is how a typo in a component name becomes a diagnostic
# instead of a silently empty component.
LIBRARY: dict[str, ComponentDef] = {
    "aed.lib.passive.Resistor": ComponentDef(
        ports=(_p("a", "passive"), _p("b", "passive")),
        constraint_attributes=frozenset({"resistance"}),
    ),
    "aed.lib.passive.Capacitor": ComponentDef(
        ports=(_p("a", "passive"), _p("b", "passive")),
        constraint_attributes=frozenset({"capacitance"}),
    ),
    "aed.lib.passive.Inductor": ComponentDef(
        ports=(_p("a", "passive"), _p("b", "passive")),
        constraint_attributes=frozenset({"inductance"}),
    ),
    "aed.lib.passive.FerriteBead": ComponentDef(
        ports=(_p("a", "passive"), _p("b", "passive"))
    ),
    "aed.lib.passive.PtcFuse": ComponentDef(
        ports=(_p("a", "passive"), _p("b", "passive"))
    ),
    "aed.lib.semiconductor.Led": ComponentDef(
        ports=(_p("a", "passive"), _p("k", "passive")),
        constraint_attributes=frozenset({"color"}),
    ),
    "aed.lib.semiconductor.SchottkyDiode": ComponentDef(
        ports=(_p("a", "passive"), _p("k", "passive"))
    ),
    "aed.lib.semiconductor.TvsDiode": ComponentDef(
        ports=(_p("a", "passive"), _p("k", "passive"))
    ),
    "aed.lib.connector.BatteryConnector9V": ComponentDef(
        ports=(_p("neg", "power_out", "2"), _p("pos", "power_out", "1"))
    ),
    "aed.lib.timer.Ne555": ComponentDef(
        ports=(
            _p("ctl", "passive", "5"),
            _p("dis", "open_collector", "7"),
            _p("gnd", "power_in", "1"),
            _p("out", "output", "3"),
            _p("rst", "input", "4"),
            _p("thr", "input", "6"),
            _p("trig", "input", "2"),
            _p("vcc", "power_in", "8"),
        )
    ),
    "aed.lib.connector.UsbCReceptacle16": ComponentDef(
        # One logical port per signal; the multi-pin members are the paired
        # A/B-side contacts a USB-C receptacle commons internally.
        ports=(
            _p("cc1", "bidirectional"),
            _p("cc2", "bidirectional"),
            _p("dm", "bidirectional"),
            _p("dp", "bidirectional"),
            _p("gnd", "power_out"),
            _p("shield", "passive"),
            _p("vbus", "power_out"),
        )
    ),
    "aed.lib.connector.PinHeader1x2": ComponentDef(
        ports=(_p("p1", "passive"), _p("p2", "passive"))
    ),
    "aed.lib.connector.PinHeader1x6": ComponentDef(
        ports=tuple(_p(f"p{i}", "passive") for i in range(1, 7))
    ),
    "aed.lib.connector.PinHeader1x20": ComponentDef(
        ports=tuple(sorted((_p(f"p{i}", "passive") for i in range(1, 21)), key=lambda p: p.name))
    ),
    "aed.lib.connector.Shunt2": ComponentDef(
        ports=(_p("a", "passive"), _p("b", "passive"))
    ),
    "aed.lib.switch.TactileSwitch": ComponentDef(
        ports=(_p("a", "passive"), _p("b", "passive"))
    ),
    "aed.lib.semiconductor.UsbEsdArray": ComponentDef(
        ports=(
            _p("dm", "bidirectional"),
            _p("dp", "bidirectional"),
            _p("gnd", "power_in"),
            _p("vbus", "passive"),
        )
    ),
    "aed.lib.regulator.LinearRegulator": ComponentDef(
        # No enable port. The AP7361C's EN treatment is not stated in
        # benchmarks/esp32s3-devboard/, and inventing a connection for it
        # would put a design decision this issue has no business making into
        # a fixture. AMB-58 authors the real D3 record from the datasheet.
        ports=(
            _p("gnd", "power_in"),
            _p("vin", "power_in"),
            _p("vout", "power_out"),
        )
    ),
    "aed.lib.module.Esp32S3Wroom1": ComponentDef(
        # Ports carry NO pin designators. The WROOM-1 pinout is a datasheet
        # fact this issue has no datasheet in front of it for, and a plausible
        # guess written into a fixture is worse than an absence: the schema
        # makes pin_numbers optional precisely so an unresolved mapping can be
        # left unresolved. AMB-58 / AMB-65 own the real pin map.
        ports=tuple(
            sorted(
                (
                    _p("en", "input"),
                    _p("gnd", "power_in"),
                    _p("p3v3", "power_in"),
                )
                + tuple(
                    _p(f"io{n}", "bidirectional")
                    for n in list(range(0, 22)) + list(range(35, 49))
                ),
                key=lambda p: p.name,
            )
        )
    ),
    "aed.lib.mech.MountingHole": ComponentDef(
        ports=(),
        hardware_kind="mounting_hole",
        exclude_from_bom=True,
        board_only=True,
    ),
    "aed.lib.mech.GroundedMountingHole": ComponentDef(
        ports=(_p("p", "passive"),),
        hardware_kind="grounded_mounting_hole",
        exclude_from_bom=True,
    ),
    "aed.lib.mech.TestPoint": ComponentDef(
        ports=(_p("p", "passive"),),
        hardware_kind="test_point",
        exclude_from_bom=True,
    ),
}


class LibraryError(KeyError):
    """A definition the library does not know."""


# Which T9 rules are active. MEASUREMENT KNOB ONLY: the bake-off has to be
# able to say how much each rule is worth on its own, because reporting one
# aggregate "annotation tax" hid that two thirds of it was T9-1 — a component
# library supplying a pin list, which is not inference and which no candidate
# grammar was ever going to charge for. Nothing outside measure.py changes it,
# and it is restored on the way out.
ALL_RULES = frozenset({"T9-1", "T9-2", "T9-3"})
ACTIVE_RULES = ALL_RULES


@contextmanager
def rule_set(rules):
    """Run a block with only `rules` active. Single-threaded, restores on exit."""
    global ACTIVE_RULES
    previous = ACTIVE_RULES
    ACTIVE_RULES = frozenset(rules)
    try:
        yield
    finally:
        ACTIVE_RULES = previous


def lookup(definition: str) -> ComponentDef:
    try:
        return LIBRARY[definition]
    except KeyError:
        raise LibraryError(
            f"component {definition!r} is not in the bake-off library "
            "(lang/bakeoff/library.py). Add it there deliberately: a component "
            "with no interface would instantiate with no pins and connect to "
            "nothing, and every arm would agree on the wrong answer."
        ) from None


def inferable_ports(inst: Instance) -> bool:
    """True when T9-1 recovers this instance's ports exactly."""
    if "T9-1" not in ACTIVE_RULES:
        return False
    if inst.kind != "component":
        return False
    try:
        return lookup(inst.definition).ports == inst.ports
    except LibraryError:
        return False


def inferable_hardware(inst: Instance) -> bool:
    """True when T9-3 recovers this instance's L9 facts exactly.

    All three fields must match. A partial match is not inferable: the source
    has to state the whole set or none of it, because there is no spelling for
    "this one flag differs from the library".
    """
    if "T9-3" not in ACTIVE_RULES:
        return False
    if inst.kind != "component":
        return False
    try:
        definition = lookup(inst.definition)
    except LibraryError:
        return False
    return (
        definition.hardware_kind == inst.hardware_kind
        and definition.exclude_from_bom == inst.exclude_from_bom
        and definition.board_only == inst.board_only
    )


def inferable_constraints(inst: Instance) -> set[str]:
    """Constraint names T9-2 recovers from same-named instance parameters."""
    if "T9-2" not in ACTIVE_RULES:
        return set()
    if inst.part is None or inst.kind != "component":
        return set()
    try:
        resolver_visible = lookup(inst.definition).constraint_attributes
    except LibraryError:
        return set()
    return {
        name
        for name, value in inst.part.constraints.items()
        if name in resolver_visible
        and name in inst.parameters
        and inst.parameters[name].key() == value.key()
    }


def apply_inference(inst: Instance, *, hardware_stated: bool = False) -> Instance:
    """Fill in everything the rules recover, for a parser reading `inferred`.

    The parser calls this on an instance it read without ports, hardware facts
    or duplicated constraints; the result must equal the instance the renderer
    started from, which is what the round-trip test asserts.

    THE KEYWORD ARGUMENT IS WHAT MAKES T9-3 INVERTIBLE, and it was added
    because the round trip was silently lossy without it:

      hardware_stated     the source declared at least one L9 fact, so T9-3
                          must not touch any of them. Without this an
                          instance-level `false` could not override a library
                          `true`, because the renderers only spell a flag when
                          it is set — so the flag flipped on the way back in.

    T9-2 needs no such flag, and the reason is worth writing down because the
    obvious fix does not work: "the renderer skipped it" and "the source never
    had it" produce IDENTICAL text, so no amount of parser bookkeeping can
    tell them apart. What closes the hole is a coherence rule on the MODEL
    (`model.validate`): an instance with a part binding and a resolver-visible
    parameter must carry the matching constraint. With that rule the second
    case cannot exist, and restoring unconditionally is exact.
    """
    if inst.kind != "component":
        return inst
    definition = lookup(inst.definition)
    ports = inst.ports or definition.ports
    if hardware_stated:
        hardware_kind = inst.hardware_kind
        exclude = inst.exclude_from_bom
        board_only = inst.board_only
    else:
        hardware_kind = definition.hardware_kind
        exclude = definition.exclude_from_bom
        board_only = definition.board_only

    part = inst.part
    if part is not None:
        restored = dict(part.constraints)
        for name in sorted(definition.constraint_attributes):
            if name in inst.parameters:
                restored.setdefault(name, inst.parameters[name])
        part = type(part)(
            binding=part.binding,
            constraints=restored,
            lockfile_key=part.lockfile_key,
        )

    return type(inst)(
        name=inst.name,
        kind=inst.kind,
        definition=inst.definition,
        parameters=inst.parameters,
        ports=ports,
        part=part,
        hardware_kind=hardware_kind,
        dnp=inst.dnp,
        exclude_from_bom=exclude,
        board_only=board_only,
    )
