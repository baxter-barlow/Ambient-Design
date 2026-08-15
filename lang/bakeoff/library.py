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
        `hardware_kind` and the L9 flags it implies come from the library. A
        mounting hole is board-only and out of the BOM because it is a
        mounting hole, not because the design said so twice.

There are deliberately NO value defaults ("a resistor is 0402", "a resistor is
0.25 W"). They looked like the biggest saving available and they are a trap:
the right default for benchmark (a)'s through-hole build is wrong for
benchmark (c)'s SMD build, so a library carrying one would hand the tax
measurement a number that depends on which design happens to be in the corpus.
A rule that only pays off when the corpus agrees with it is not an inference
rule, it is a coincidence.

THE TAX IS THEREFORE A LOWER BOUND on what a real type checker could recover,
and the report says so. Under-claiming here is the safe direction: R59 at M2
re-measures against the actual checker, and a preliminary number that came in
low is a pleasant surprise, whereas one that came in high would have already
been used to justify a decision.

This library is a bake-off fixture standing in for D3 part data. It is not the
D5 seed library and nothing outside lang/ may read it.
"""

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
    if inst.kind != "component":
        return False
    try:
        return lookup(inst.definition).ports == inst.ports
    except LibraryError:
        return False


def inferable_hardware(inst: Instance) -> bool:
    """True when T9-3 recovers this instance's L9 facts exactly."""
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


def apply_inference(inst: Instance) -> Instance:
    """Fill in everything the rules recover, for a parser reading `inferred`.

    The parser calls this on an instance it read without ports, hardware facts
    or duplicated constraints; the result must equal the instance the renderer
    started from, which is what the round-trip test asserts. If a rule were
    lossy the round trip would fail rather than the tax being overstated.
    """
    if inst.kind != "component":
        return inst
    definition = lookup(inst.definition)
    ports = inst.ports or definition.ports
    hardware_kind = inst.hardware_kind or definition.hardware_kind
    exclude = inst.exclude_from_bom or definition.exclude_from_bom
    board_only = inst.board_only or definition.board_only

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
