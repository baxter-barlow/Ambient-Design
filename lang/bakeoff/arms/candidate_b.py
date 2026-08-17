"""Candidate B — `block`: facts scoped under what they describe.

    r_a = new aed.lib.passive.Resistor(resistance = 100kohm +/- 1%):
        part abstract:
            package = "axial_0207"
    net VCC:
        j_bat.pos
        r_a.a
        timer.vcc

Same nouns, same literals, same layout rules as candidate A. One axis differs:
a fact is written inside the scope of the thing it is about, so the thing's
name is written once instead of once per fact. On a design with a
twenty-member ground net and sixty instances that is not a small difference,
and finding out how large it actually is on a real benchmark is the point of
§8-Q1.

What B gives up is span locality. A bad parameter in a constructor list is
inside a line that also carries three good ones, and a mis-indented `part`
block reports at the block rather than at the fact. P2 says the repair loop is
where a grammar is won or lost, so `lang/bakeoff/defects.py` measures that
cost rather than leaving it as a matter of taste.
"""

from .. import library
from ..diagnostics import Diag
from ..model import (
    Assertion,
    DesignModel,
    HARDWARE_KINDS,
    Instance,
    Net,
    Port,
    Value,
)
from .base import (
    PRAGMA,
    Cursor,
    open_source,
    parse_assertion,
    parse_port_decl,
    parse_role,
    render_assertion,
    reserved_words_block,
    variant_flags,
)
from .shared import (
    columnar_groups,
    module_order,
    parse_table_header,
    parse_table_rows,
    render_table,
)

KEY = "candidate_b"
TITLE = "B - block"
CODE_PREFIX = "AEDB"
FLAGS = ("dnp", "exclude_from_bom", "board_only")
# The L9 flags T9-3 infers. `dnp` is NOT one of them: it is never inferred
# from the library, so writing it must not count as "the source stated its
# hardware facts".
HARDWARE_FLAGS = ("exclude_from_bom", "board_only")
NET_ATTRIBUTES = ("ground_domain", "voltage_domain")


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------


def _arguments(values: dict) -> str:
    if not values:
        return ""
    inner = ", ".join(f"{name} = {values[name].render()}" for name in sorted(values))
    return f"({inner})"


def _instance_lines(inst: Instance, infer: bool) -> list[str]:
    head = f"{inst.name} = new {inst.definition}{_arguments(inst.parameters)}"
    body: list[str] = []

    if inst.kind == "component" and not (infer and library.inferable_ports(inst)):
        # Only a contradiction when the LIBRARY has pins and the instance does
        # not: then silence would mean "ask the library" and there is no way to
        # say "no pins here". A component the library also holds portless is
        # unambiguous, and raising on it broke the per-rule decomposition.
        supplied = library.LIBRARY.get(inst.definition)
        if infer and not inst.ports and supplied is not None and supplied.ports:
            raise ValueError(
                f"{inst.name}: is portless but the library gives "
                f"{inst.definition} pins, so `inferred` has no way to say "
                "'no pins here'. Fix the library or the fixture."
            )
        for port in inst.ports:
            designators = " " + " ".join(port.pin_numbers) if port.pin_numbers else ""
            body.append(f"pin {port.name} {port.role}{designators}")

    if inst.part is not None:
        skip = library.inferable_constraints(inst) if infer else set()
        names = sorted(set(inst.part.constraints) - skip)
        header = (
            f'part "{inst.part.lockfile_key}"'
            if inst.part.lockfile_key
            else "part abstract"
        )
        if names:
            body.append(header + ":")
            body.extend(
                f"    {name} = {inst.part.constraints[name].render()}" for name in names
            )
        else:
            body.append(header)

    if not (infer and library.inferable_hardware(inst)):
        if inst.hardware_kind:
            body.append(f"hardware {inst.hardware_kind}")
        definition = library.LIBRARY.get(inst.definition)
        for flag in HARDWARE_FLAGS:
            value = getattr(inst, flag)
            if value:
                body.append(flag)
            elif definition is not None and getattr(definition, flag):
                # An explicit false, because the library says true and the
                # bare keyword only means true.
                body.append(f"no {flag}")
    if inst.dnp:
        body.append("dnp")

    if not body:
        return [head]
    return [head + ":"] + ["    " + line for line in body]


def _net_lines(net: Net) -> list[str]:
    if net.name:
        attributes = {
            name: getattr(net, name)
            for name in NET_ATTRIBUTES
            if getattr(net, name)
        }
        suffix = (
            "("
            + ", ".join(f'{k} = "{v}"' for k, v in sorted(attributes.items()))
            + ")"
            if attributes
            else ""
        )
        return [f"net {net.name}{suffix}:"] + [
            f"    {member}" for member in net.members
        ]
    # A net with exactly ONE endpoint. L9b calls these out by name -
    # "intentional single-pin nets" - and benchmark (c)'s design.md says the
    # lint must accept them only when declared, so the language needs a way to
    # declare one. Neither benchmark design happened to contain one, so all
    # three arms shipped with no spelling for it at all: candidate A dropped
    # the net silently, candidate B emitted a bare endpoint its own parser
    # rejected, and the baseline's `m.link` demanded two. The coverage probe
    # found it in one run.
    if len(net.members) == 1:
        return [f"isolated {net.members[0]}"]
    # Unlabelled nets are an n-ary chain on one line. Same operator as A, one
    # statement instead of k-1 of them.
    return [" ~ ".join(net.members)]


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
        # Endpoints declared as single-member nets (L9b).
        self.isolated_endpoints: list[str] = []


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
        # Did the source state any L9 hardware fact at all? Distinct from the
        # values, because the renderers only spell a flag when it is set, so
        # "silent" and "false" are otherwise the same text — and T9-3 filling
        # a silent instance is right while overriding an explicit false is a
        # BOM flag flipping behind the author's back.
        "hardware_stated": False,
        "dnp": False,
        "exclude_from_bom": False,
        "board_only": False,
    }


def _parse_arguments(cursor: Cursor, what: str) -> dict[str, Value]:
    values: dict[str, Value] = {}
    cursor.advance()  # `(`
    if cursor.at("OP", ")"):
        cursor.advance()
        return values
    while True:
        name = cursor.expect_name(f"a {what} name")
        cursor.expect("OP", "=", what=f"after {what} {name!r}")
        if name in values:
            cursor.error("0221", f"{name!r} is given twice in one list", name=name)
            cursor.fail()
        values[name] = cursor.value(f"{what} {name}")
        if cursor.at("OP", ","):
            cursor.advance()
            continue
        break
    cursor.expect("OP", ")", what=f"to close the {what} list")
    return values


def _parse_part(cursor: Cursor, inst: dict) -> None:
    cursor.advance()  # `part`
    if cursor.at_keyword("abstract"):
        cursor.advance()
        inst["abstract"] = True
    elif cursor.at("STRING"):
        inst["lockfile_key"] = cursor.advance().text
    else:
        cursor.error(
            "0222",
            f"expected `abstract` or a lockfile key string, found "
            f"{cursor.current.text!r}",
            fixit="`part abstract` states constraints; `part \"key\"` pins a pick",
            found=cursor.current.text or cursor.current.kind,
        )
        cursor.fail()

    if not cursor.at("OP", ":"):
        cursor.expect_newline()
        return
    cursor.expect_block("part")
    while not cursor.at("DEDENT") and not cursor.at("EOF"):
        cursor.skip_newlines()
        if cursor.at("DEDENT") or cursor.at("EOF"):
            break
        name = cursor.expect_name("a constraint name")
        cursor.expect("OP", "=", what=f"after constraint {name!r}")
        inst["constraints"][name] = cursor.value(f"constraint {name}")
        cursor.expect_newline()
    cursor.end_block()


def _parse_instance_body(cursor: Cursor, inst: dict) -> None:
    cursor.expect_block(f"instance {inst['name']}")
    while not cursor.at("DEDENT") and not cursor.at("EOF"):
        cursor.skip_newlines()
        if cursor.at("DEDENT") or cursor.at("EOF"):
            break
        if cursor.at_keyword("pin"):
            cursor.advance()
            pin_name = cursor.expect_name("a pin name")
            role = parse_role(cursor, f"pin {pin_name}")
            designators = []
            while cursor.current.kind in ("NUMBER", "NAME"):
                designators.append(cursor.advance().text)
            cursor.expect_newline()
            inst["ports"].append(
                Port(name=pin_name, role=role, pin_numbers=tuple(sorted(designators)))
            )
            continue
        if cursor.at_keyword("part"):
            _parse_part(cursor, inst)
            continue
        if cursor.at_keyword("hardware"):
            cursor.advance()
            kind = cursor.current
            if kind.kind != "NAME" or kind.text not in HARDWARE_KINDS:
                cursor.error(
                    "0223",
                    f"{kind.text!r} is not an L9 hardware kind",
                    fixit="kinds are: " + ", ".join(HARDWARE_KINDS),
                    found=kind.text or kind.kind,
                )
                cursor.fail()
            cursor.advance()
            cursor.expect_newline()
            inst["hardware_kind"] = kind.text
            inst["hardware_stated"] = True
            continue
        if cursor.at_keyword("no"):
            cursor.advance()
            flag = cursor.current
            if flag.kind != "NAME" or flag.text not in HARDWARE_FLAGS:
                cursor.error(
                    "0232",
                    f"`no {flag.text!r}` is not a fabrication flag",
                    fixit="`no` negates " + " or ".join(HARDWARE_FLAGS),
                    found=flag.text or flag.kind,
                )
                cursor.fail()
            cursor.advance()
            cursor.expect_newline()
            inst[flag.text] = False
            inst["hardware_stated"] = True
            continue
        if cursor.at_keyword(*FLAGS):
            flag = cursor.advance().text
            cursor.expect_newline()
            inst[flag] = True
            if flag in HARDWARE_FLAGS:
                inst["hardware_stated"] = True
            continue
        cursor.error(
            "0224",
            f"{cursor.current.text!r} is not an instance-body statement",
            fixit="the body carries `pin`, `part`, `hardware`, or a fabrication flag",
            found=cursor.current.text or cursor.current.kind,
        )
        cursor.fail()
    cursor.end_block()


def _parse_net(cursor: Cursor, builder: _ModuleBuilder) -> None:
    cursor.advance()  # `net`
    name = cursor.expect_free_name("a net")
    if name in builder.signals:
        cursor.error("0225", f"net {name!r} is declared twice", net=name)
        cursor.fail()
    attributes = {"ground_domain": None, "voltage_domain": None}
    if cursor.at("OP", "("):
        for key, value in _parse_arguments(cursor, "net attribute").items():
            if key not in NET_ATTRIBUTES:
                cursor.error("0226", f"{key!r} is not a net attribute", attribute=key)
                cursor.fail()
            if value.tag != "s":
                cursor.error("0227", f"{key} is a domain label string")
                cursor.fail()
            attributes[key] = value.text
    builder.signals[name] = attributes
    cursor.expect_block(f"net {name}")
    members = 0
    while not cursor.at("DEDENT") and not cursor.at("EOF"):
        cursor.skip_newlines()
        if cursor.at("DEDENT") or cursor.at("EOF"):
            break
        member_token = cursor.current
        member = cursor.dotted_ref("a net member")
        builder.links.append((name, member))
        builder.spans.setdefault(member, member_token.span(len(member)))
        cursor.expect_newline()
        members += 1
    cursor.end_block()
    if members == 0:
        cursor.error("0228", f"net {name!r} has no members", net=name)
        cursor.fail()


def _parse_statement(cursor: Cursor, builder: _ModuleBuilder, assertions: list) -> None:
    cursor.reject_reserved_name()
    if cursor.at_keyword("port"):
        builder.ports.append(parse_port_decl(cursor))
        return
    if cursor.at_keyword("isolated"):
        cursor.advance()
        token = cursor.current
        endpoint = cursor.dotted_ref("an isolated endpoint")
        cursor.expect_newline()
        builder.isolated_endpoints.append(endpoint)
        builder.spans.setdefault(endpoint, token.span(len(endpoint)))
        return

    if cursor.at_keyword("net"):
        _parse_net(cursor, builder)
        return
    if cursor.at_keyword("assert"):
        assertions.append(parse_assertion(cursor))
        return
    if cursor.at_keyword("table"):
        _parse_table(cursor, builder)
        return

    start = cursor.current
    first = cursor.dotted_ref("an instance, net or port name")

    if cursor.at("OP", "~"):
        chain = [first]
        builder.spans.setdefault(first, start.span(len(first)))
        while cursor.at("OP", "~"):
            cursor.advance()
            endpoint_token = cursor.current
            endpoint = cursor.dotted_ref("a connection endpoint")
            chain.append(endpoint)
            builder.spans.setdefault(endpoint, endpoint_token.span(len(endpoint)))
        cursor.expect_newline()
        for left, right in zip(chain, chain[1:]):
            builder.links.append((left, right))
        return

    cursor.expect("OP", "=", what=f"after {first!r}")
    if not cursor.at_keyword("new"):
        cursor.error(
            "0229",
            f"expected `new` after `{first} =`, found {cursor.current.text!r}",
            fixit="an assignment instantiates; facts about an instance go in its body",
            found=cursor.current.text or cursor.current.kind,
        )
        cursor.fail()
    cursor.advance()
    definition = cursor.qualified_name("a definition name")
    if "." in first:
        cursor.diagnostics.append(
            Diag(
                code=f"{CODE_PREFIX}0230",
                message=f"cannot instantiate into {first!r}; an instance name is "
                "a single identifier",
                span=start.span(),
                params={"target": first},
            )
        )
        cursor.fail()
    if first in builder.instances or first in builder.signals:
        # Reported at the NAME for the same reason as arm A: the cursor has
        # moved on, and the default span would blame the next line.
        cursor.diagnostics.append(
            Diag(
                code=f"{CODE_PREFIX}0231",
                message=f"{first!r} is already declared",
                span=start.span(len(first)),
                params={"name": first},
                fixit="rename one of them, or delete the repeat",
            )
        )
        cursor.fail()

    inst = _new_instance(first, definition)
    if cursor.at("OP", "("):
        inst["parameters"] = _parse_arguments(cursor, "parameter")
    if cursor.at("OP", ":"):
        _parse_instance_body(cursor, inst)
    else:
        cursor.expect_newline()
    builder.instances[first] = inst


def _parse_table(cursor: Cursor, builder: _ModuleBuilder) -> None:
    header = parse_table_header(cursor)
    for name, values in parse_table_rows(cursor, header):
        if name in builder.instances or name in builder.signals:
            cursor.error("0231", f"{name!r} is already declared", name=name)
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
    infer, _ = variant_flags(variant)
    cursor = open_source(source, CODE_PREFIX)

    builders: list[_ModuleBuilder] = []
    assertions: list[Assertion] = []
    per_module: dict[str, list[Assertion]] = {}

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
        name = cursor.expect_free_name("a module")
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
        per_module[name] = mine
        assertions.extend(mine)

    cursor.finish()
    from .shared import build_model

    return build_model(
        cursor=cursor,
        builders=builders,
        assertions=assertions,
        root_assertions=per_module,
        infer=infer,
        code_prefix=CODE_PREFIX,
    )


def language_card() -> str:
    """The A4 language card. Reserved words come from `RESERVED`, not a copy."""
    return _LANGUAGE_CARD.replace("{reserved_words}", reserved_words_block())


_LANGUAGE_CARD = '''\
# AED candidate B - language card

Declarative electronics design. Facts live inside the scope of what they
describe. ASCII only. Blocks are opened by `:` and delimited by 4-space
indentation. Every file starts with:

    #pragma rhoform-syntax 0.1

## Modules

    module Blinker555:
        <statements>

A module groups instances and nets. `port <name> <role>` declares an
interface port that the enclosing design connects to.

## Instances

    r_a = new aed.lib.passive.Resistor(resistance = 100kohm +/- 1%)

    timer = new aed.lib.timer.Ne555:
        pin out output 3
        part "timer.555/ti-NE555P@2":
            function = "timer_555"

Parameters are keyword arguments on the instantiation. An optional indented
body carries everything else:

    pin <name> <role> [<designator> ...]   a component pin
    part abstract:                         resolution constraints follow
    part "<key>"                           an already-resolved pick
    hardware <kind>                        L9 classification
    dnp / exclude_from_bom / board_only    fabrication flags

Omit `pin` lines and `hardware`/flag lines when the component library
supplies them. Pin roles: power_in, power_out, passive, bidirectional,
open_drain, open_collector, tri_state, input, output, nc. Hardware kinds:
mounting_hole, fiducial, artwork, test_point, grounded_mounting_hole.

## Connections

    net VCC(voltage_domain = "vbat_9v"):
        j_bat.pos
        r_a.a
        timer.vcc

    ctl ~ r_lim.a

    isolated tp1.p

A `net` block names a net and lists its members, one per line. A `~` chain
joins endpoints into an unnamed net. `isolated` declares a net with a single
endpoint (L9b). An endpoint is `<instance>.<pin>` or one of this module's own
ports.

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

## Reserved words

{reserved_words}

None of these may be used as an instance, net or module name.

## Tables

    table aed.lib.passive.Capacitor part abstract (capacitance, part.package):
        c12  100nF +/- 10%  "0402"
        c13  100nF +/- 10%  "0402"
        c14  100nF +/- 10%  "0402"

A columnar shorthand for three or more instances that differ only in their
values. The header names the definition, the part binding and the columns;
each row is an instance name followed by one value per column.
'''
