"""Candidate A — `statement`: one fact per statement, atopile-faithful.

    r_a = new aed.lib.passive.Resistor
    r_a.resistance = 100kohm +/- 1%
    r_a.part.package = "axial_0207"
    signal VCC
    VCC ~ r_a.a
    VCC ~ timer.vcc

This is the conservative candidate and it is meant to be. L2 adopts atopile's
MIT surface with attribution, and this is that surface: `new`, `~`, dotted
attribute assignment, `signal`. Every fact has its own line, which means every
fact has its own span, which means every diagnostic points at one thing. Under
P2 — repair-loop convergence, not first-shot success — that locality is the
argument for A, and the token count is the argument against it.

A's weakness is visible in its own output: an instance's identifier is
repeated once per fact, and a net's label once per member. A twenty-member
ground net costs twenty lines that each say `GND`.
"""

from .. import library
from ..diagnostics import Diag
from ..model import (
    Assertion,
    DesignModel,
    Instance,
    Module,
    Net,
    PartBinding,
    Port,
    Value,
)
from .base import (
    COLUMNAR_MIN_ROWS,
    PRAGMA,
    VARIANTS,
    Cursor,
    open_source,
    parse_assertion,
    parse_port_decl,
    parse_role,
    render_assertion,
    variant_flags,
)
from .shared import (
    columnar_groups,
    module_order,
    parse_table_header,
    parse_table_rows,
    render_table,
)

KEY = "candidate_a"
TITLE = "A - statement"
CODE_PREFIX = "AEDA"
FLAGS = ("dnp", "exclude_from_bom", "board_only")
NET_ATTRIBUTES = ("ground_domain", "voltage_domain")


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------


def _instance_lines(inst: Instance, infer: bool) -> list[str]:
    lines = [f"{inst.name} = new {inst.definition}"]
    for name in sorted(inst.parameters):
        lines.append(f"{inst.name}.{name} = {inst.parameters[name].render()}")

    if inst.kind == "component" and not (infer and library.inferable_ports(inst)):
        # In `explicit` no pin lines means no pins, because the parser does no
        # inference there. In `inferred` it would mean "ask the library", so a
        # genuinely portless component the library disagrees with has no
        # spelling at all — that is a fixture bug, and silence would turn it
        # into a wrong netlist both arms agreed on.
        if infer and not inst.ports:
            raise ValueError(
                f"{inst.name}: is portless but the library gives "
                f"{inst.definition} pins, so `inferred` has no way to say "
                "'no pins here'. Fix the library or the fixture."
            )
        for port in inst.ports:
            designators = " " + " ".join(port.pin_numbers) if port.pin_numbers else ""
            lines.append(f"pin {inst.name}.{port.name} {port.role}{designators}")

    if inst.part is not None:
        skip = library.inferable_constraints(inst) if infer else set()
        names = sorted(set(inst.part.constraints) - skip)
        if inst.part.lockfile_key:
            lines.append(f'{inst.name}.part = "{inst.part.lockfile_key}"')
        elif not names:
            lines.append(f"{inst.name}.part = abstract")
        for name in names:
            lines.append(
                f"{inst.name}.part.{name} = {inst.part.constraints[name].render()}"
            )

    if not (infer and library.inferable_hardware(inst)):
        if inst.hardware_kind:
            lines.append(f"{inst.name}.hardware = {inst.hardware_kind}")
        for flag in ("exclude_from_bom", "board_only"):
            if getattr(inst, flag):
                lines.append(f"{inst.name}.{flag} = true")
    if inst.dnp:
        lines.append(f"{inst.name}.dnp = true")
    return lines


def _net_lines(net: Net) -> list[str]:
    if net.name:
        lines = [f"signal {net.name}"]
        for attribute in NET_ATTRIBUTES:
            value = getattr(net, attribute)
            if value:
                lines.append(f'{net.name}.{attribute} = "{value}"')
        lines.extend(f"{net.name} ~ {member}" for member in net.members)
        return lines
    # Unlabelled: a chain of binary connections, which is what a pin-to-pin
    # grammar actually costs. Chaining rather than star-connecting keeps every
    # statement two endpoints wide, which is A's whole idea.
    return [
        f"{net.members[i]} ~ {net.members[i + 1]}"
        for i in range(len(net.members) - 1)
    ]


def render(model: DesignModel, variant: str = "explicit") -> str:
    infer, columnar = variant_flags(variant)
    out = [PRAGMA, ""]

    for module in module_order(model):
        body: list[str] = []
        for port in module.ports:
            body.append(f"port {port.name} {port.role}")

        grouped, singles = (
            columnar_groups(module.instances)
            if columnar
            else ({}, list(module.instances))
        )
        for table in grouped.values():
            body.extend(render_table(table, ""))
        for inst in singles:
            body.extend(_instance_lines(inst, infer))

        for net in module.nets:
            body.extend(_net_lines(net))

        if module.name == model.root_module:
            body.extend(render_assertion(a) for a in model.assertions)

        out.append(f"module {module.name}:")
        out.extend("    " + line for line in body)
        out.append("")

    return "\n".join(out).rstrip("\n") + "\n"


# --------------------------------------------------------------------------
# Parse
# --------------------------------------------------------------------------


class _ModuleBuilder:
    def __init__(self, name: str):
        self.name = name
        self.ports: list[Port] = []
        self.instances: dict[str, dict] = {}
        self.signals: dict[str, dict] = {}
        self.links: list[tuple[str, str]] = []
        # Where each endpoint was written. Semantic failures are found after
        # parsing, by which point the token stream is gone; without this the
        # diagnostic for "no such port" would have no line, and the
        # localisation column of the defect table would be uniformly blank —
        # measuring nothing, for every candidate equally.
        self.spans: dict = {}


def _new_instance(name: str, definition: str) -> dict:
    return {
        "name": name,
        "definition": definition,
        "parameters": {},
        "ports": [],
        "constraints": {},
        "lockfile_key": None,
        "abstract": False,
        "hardware_kind": None,
        "dnp": False,
        "exclude_from_bom": False,
        "board_only": False,
    }


def _require_instance(cursor: Cursor, builder: _ModuleBuilder, name: str) -> dict:
    inst = builder.instances.get(name)
    if inst is None:
        cursor.error(
            "0201",
            f"{name!r} is not an instance of module {builder.name!r}",
            fixit=f"declare it first with `{name} = new <Definition>`",
            instance=name,
        )
        cursor.fail()
    return inst


def _parse_statement(cursor: Cursor, builder: _ModuleBuilder, assertions: list) -> None:
    if cursor.at_keyword("port"):
        builder.ports.append(parse_port_decl(cursor))
        return

    if cursor.at_keyword("pin"):
        cursor.advance()
        owner = cursor.expect_name("the instance a pin belongs to")
        cursor.expect("OP", ".", what="between instance and pin name")
        pin_name = cursor.expect_name("a pin name")
        role = parse_role(cursor, f"pin {owner}.{pin_name}")
        designators = []
        while cursor.current.kind in ("NUMBER", "NAME"):
            designators.append(cursor.advance().text)
        cursor.expect_newline()
        _require_instance(cursor, builder, owner)["ports"].append(
            Port(name=pin_name, role=role, pin_numbers=tuple(sorted(designators)))
        )
        return

    if cursor.at_keyword("signal"):
        cursor.advance()
        name = cursor.expect_name("a signal name")
        cursor.expect_newline()
        if name in builder.signals:
            cursor.error("0202", f"signal {name!r} is declared twice", signal=name)
            cursor.fail()
        builder.signals[name] = {"ground_domain": None, "voltage_domain": None}
        return

    if cursor.at_keyword("assert"):
        assertions.append(parse_assertion(cursor))
        return

    if cursor.at_keyword("table"):
        _parse_table(cursor, builder)
        return

    # Everything else starts with a dotted path, and the operator that follows
    # decides what kind of statement it is.
    start = cursor.current
    path = [cursor.expect_name("an instance, signal or port name")]
    while cursor.at("OP", "."):
        cursor.advance()
        path.append(cursor.expect_name("a member name"))

    if cursor.at("OP", "~"):
        cursor.advance()
        right_token = cursor.current
        right = cursor.dotted_ref("a connection endpoint")
        cursor.expect_newline()
        left = ".".join(path)
        builder.links.append((left, right))
        builder.spans.setdefault(left, start.span(len(left)))
        builder.spans.setdefault(right, right_token.span(len(right)))
        return

    if not cursor.at("OP", "="):
        cursor.error(
            "0203",
            f"expected `=` or `~` after {'.'.join(path)!r}, found "
            f"{cursor.current.text!r}",
            fixit="a statement either assigns a value or makes a connection",
            found=cursor.current.text or cursor.current.kind,
        )
        cursor.fail()
    cursor.advance()

    if cursor.at_keyword("new"):
        cursor.advance()
        definition = cursor.qualified_name("a definition name")
        cursor.expect_newline()
        if len(path) != 1:
            cursor.diagnostics.append(
                Diag(
                    code=f"{CODE_PREFIX}0204",
                    message=f"cannot instantiate into {'.'.join(path)!r}; "
                    "an instance name is a single identifier",
                    span=start.span(),
                    params={"target": ".".join(path)},
                )
            )
            cursor.fail()
        if path[0] in builder.instances or path[0] in builder.signals:
            # Reported at the NAME, not at `cursor.current`: by this point the
            # cursor has walked past the statement's newline, so the default
            # span would blame the following line for this line's mistake.
            cursor.diagnostics.append(
                Diag(
                    code=f"{CODE_PREFIX}0205",
                    message=f"{path[0]!r} is already declared",
                    span=start.span(len(path[0])),
                    params={"name": path[0]},
                    fixit="rename one of them, or delete the repeat",
                )
            )
            cursor.fail()
        builder.instances[path[0]] = _new_instance(path[0], definition)
        return

    _parse_assignment(cursor, builder, path, start)


def _parse_assignment(cursor: Cursor, builder, path: list[str], start) -> None:
    if len(path) == 3 and path[1] == "part":
        inst = _require_instance(cursor, builder, path[0])
        inst["constraints"][path[2]] = cursor.value(f"{path[0]}.part.{path[2]}")
        cursor.expect_newline()
        return

    if len(path) == 2 and path[1] == "part":
        inst = _require_instance(cursor, builder, path[0])
        if cursor.at_keyword("abstract"):
            cursor.advance()
            cursor.expect_newline()
            inst["abstract"] = True
            return
        value = cursor.value(f"{path[0]}.part")
        cursor.expect_newline()
        if value.tag != "s":
            cursor.error("0206", "a resolved part binding is a lockfile key string")
            cursor.fail()
        inst["lockfile_key"] = value.text
        return

    if len(path) == 2 and path[1] == "hardware":
        inst = _require_instance(cursor, builder, path[0])
        kind = cursor.current
        from ..model import HARDWARE_KINDS

        if kind.kind != "NAME" or kind.text not in HARDWARE_KINDS:
            cursor.error(
                "0207",
                f"{kind.text!r} is not an L9 hardware kind",
                fixit="kinds are: " + ", ".join(HARDWARE_KINDS),
                found=kind.text or kind.kind,
            )
            cursor.fail()
        cursor.advance()
        cursor.expect_newline()
        inst["hardware_kind"] = kind.text
        return

    if len(path) == 2 and path[1] in FLAGS:
        inst = _require_instance(cursor, builder, path[0])
        value = cursor.value(f"{path[0]}.{path[1]}")
        cursor.expect_newline()
        if value.tag != "b":
            cursor.error("0208", f"{path[1]} is a flag: write `true` or `false`")
            cursor.fail()
        inst[path[1]] = value.flag
        return

    if len(path) == 2 and path[0] in builder.signals and path[1] in NET_ATTRIBUTES:
        value = cursor.value(f"{path[0]}.{path[1]}")
        cursor.expect_newline()
        if value.tag != "s":
            cursor.error("0209", f"{path[1]} is a domain label string")
            cursor.fail()
        builder.signals[path[0]][path[1]] = value.text
        return

    if len(path) == 2:
        inst = _require_instance(cursor, builder, path[0])
        inst["parameters"][path[1]] = cursor.value(f"{path[0]}.{path[1]}")
        cursor.expect_newline()
        return

    cursor.diagnostics.append(
        Diag(
            code=f"{CODE_PREFIX}0210",
            message=f"{'.'.join(path)!r} is not an assignable target",
            span=start.span(),
            params={"target": ".".join(path)},
            fixit="targets are `x.param`, `x.part`, `x.part.name`, `x.dnp`, "
            "`x.hardware`, or a signal's domain attribute",
        )
    )
    cursor.fail()


def _parse_table(cursor: Cursor, builder: _ModuleBuilder) -> None:
    header = parse_table_header(cursor)
    for name, values in parse_table_rows(cursor, header):
        if name in builder.instances or name in builder.signals:
            cursor.error("0205", f"{name!r} is already declared", name=name)
            cursor.fail()
        inst = _new_instance(name, header.definition)
        inst["lockfile_key"] = header.lockfile_key
        inst["abstract"] = header.binding == "abstract"
        for column, value in zip(header.columns, values):
            if column.startswith("part."):
                inst["constraints"][column[5:]] = value
            else:
                inst["parameters"][column] = value
        builder.instances[name] = inst


def parse(source: str, variant: str = "explicit") -> DesignModel:
    """Parse candidate-A source into a design model.

    `variant` selects whether the T9 rules are applied on the way back in. The
    parser is otherwise variant-blind: a file that writes out what inference
    could have supplied still parses, because a model that only accepts its own
    formatter's output is not a language.
    """
    infer, _ = variant_flags(variant)
    cursor = open_source(source, CODE_PREFIX)

    builders: list[_ModuleBuilder] = []
    assertions: list[Assertion] = []
    root_assertions: dict[str, list[Assertion]] = {}

    while not cursor.at("EOF"):
        cursor.skip_newlines()
        if cursor.at("EOF"):
            break
        if not cursor.at_keyword("module"):
            cursor.error(
                "0300",
                f"expected `module`, found {cursor.current.text!r}",
                fixit="every declaration at file scope is a module",
                found=cursor.current.text or cursor.current.kind,
            )
            cursor.fail()
        cursor.advance()
        name = cursor.expect_name("a module name")
        cursor.expect_block(f"module {name}")

        builder = _ModuleBuilder(name)
        mine: list[Assertion] = []
        while not cursor.at("DEDENT") and not cursor.at("EOF"):
            cursor.skip_newlines()
            if cursor.at("DEDENT") or cursor.at("EOF"):
                break
            _parse_statement(cursor, builder, mine)
        cursor.end_block()
        builders.append(builder)
        root_assertions[name] = mine
        assertions.extend(mine)

    cursor.finish()
    return assemble(cursor, builders, assertions, root_assertions, infer)


def assemble(cursor, builders, assertions, root_assertions, infer) -> DesignModel:
    """Turn parsed builders into a validated model. Shared shape with arm B."""
    from .shared import build_model

    return build_model(
        cursor=cursor,
        builders=builders,
        assertions=assertions,
        root_assertions=root_assertions,
        infer=infer,
        code_prefix=CODE_PREFIX,
    )


def language_card() -> str:
    """The A4 language card for this candidate.

    §4's flip criterion is stated in tokens of this artifact ("the language
    card exceeds ~3K tokens and still can't express real designs"), so each
    candidate ships one and the bake-off measures it. A candidate that is
    cheaper per design but needs a bigger card to teach has not obviously won.
    """
    return _LANGUAGE_CARD


_LANGUAGE_CARD = '''\
# AED candidate A - language card

Declarative electronics design. One fact per statement. ASCII only.
Blocks are opened by `:` and delimited by 4-space indentation.
Every file starts with:

    #pragma language "0.1.0"

## Modules

    module Blinker555:
        <statements>

A module groups instances and nets. `port <name> <role>` declares an
interface port that the enclosing design connects to.

## Instances

    r_a = new aed.lib.passive.Resistor
    r_a.resistance = 100kohm +/- 1%
    r_a.part.package = "axial_0207"

`new <Definition>` instantiates a library component or another module in
this file. `<instance>.<name> = <value>` sets a parameter;
`<instance>.part.<name> = <value>` sets a part-resolution constraint;
`<instance>.part = "<key>"` pins an already-resolved part.

Fabrication attributes: `<instance>.dnp = true`,
`.exclude_from_bom = true`, `.board_only = true`,
`.hardware = test_point`.

## Pins

    pin timer.out output 3

Names a component pin, its role, and its footprint designators. Pin roles:
power_in, power_out, passive, bidirectional, open_drain, open_collector,
tri_state, input, output, nc. Omit `pin` lines when the component library
supplies them.

## Connections

    signal VCC
    VCC.voltage_domain = "vbat_9v"
    VCC ~ j_bat.pos
    VCC ~ timer.vcc
    ctl ~ r_lim.a

`signal` declares a named net; `~` attaches one endpoint. Two endpoints
joined directly form an unnamed net. An endpoint is `<instance>.<pin>` or
one of this module's own ports.

## Values

    100kohm          exact
    100kohm +/- 1%   symmetric relative tolerance
    2.0V +/- 0.2V    symmetric absolute tolerance
    9.5mA (8.0mA to 10.5mA)   nominal with an asymmetric interval
    3.0V to 3.6V     interval, no nominal
    "0402"           symbolic
    8                whole number
    true / false     flag

Units: ohm kohm Mohm mohm, F mF uF nF pF, H mH uH nH, V kV mV uV,
A mA uA nA, W mW uW, Hz kHz MHz, s ms us ns, m mm um, degC.

## Assertions

    assert assert_freq dynamic frequency(OUT) within 0.932Hz to 1.051Hz
    assert assert_duty dynamic duty_cycle(OUT) within 0.524 to 0.544

`<name> <tier> <measurement>(<net>)` then `within <lo> to <hi>`,
`at least <bound>` or `at most <bound>`. Tier is `static` or `dynamic`.

## Tables

    table aed.lib.passive.Capacitor part abstract (capacitance, part.package):
        c12  100nF +/- 10%  "0402"
        c13  100nF +/- 10%  "0402"
        c14  100nF +/- 10%  "0402"

A columnar shorthand for three or more instances that differ only in their
values. The header names the definition, the part binding and the columns;
each row is an instance name followed by one value per column.
'''
