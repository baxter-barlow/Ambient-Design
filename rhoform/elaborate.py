"""The elaborator (R13, R15): parsed sources to a design.

LAYERING. This module turns `ok` parse trees into an in-memory
`ElaboratedDesign` that keeps every value as an exact `Decimal` and every
entity's source span. It knows nothing about JSON: `rhoform/ir.py` turns
the design into IR v1 and its source map, owns the canonical encoder, and
computes both hashes. Elaboration runs only on `ok` trees — a recovered
tree is the file with its broken lines removed, and elaborating it would
report the consequences of text the author never wrote.

THE PASSES, in order, each total over its input:

  A. definitions: every `module` and (0.2) `component` per file, named
     `<module path>.<Name>` where the module path is the file's path
     relative to the compile root with `/` turned into `.` and each
     segment made an identifier — or, for a file a manifest governs, the
     package layer's name for it, its package's identity before its
     package-relative path (`modules`); then each definition's parameter
     list;
  B. each module's own ports, each component's pins;
  C. imports bind names (each imported name must be a definition of the
     file it comes from, and binds once per file); then the instantiation
     graph: a single-word definition must be a module or component of the
     file or imported into it; a dotted one under the reserved prefix
     `rhoform.lib.` must be a component of the bundled standard library
     (see THE STANDARD LIBRARY), and any other dotted one is an ad-hoc
     component whose ports are exactly its inline `pin` statements;
  D. cycles (an error: elaboration terminates because no module may
     contain itself, whatever its parameters), then the root — the unique
     module of the entry file that nothing instantiates;
  E. the checks that need no parameter VALUE, once per definition: names a
     value refers to, the types of arguments, defaults, conditions,
     bounds and indexes, and where a statement may stand;
  F. the walk: from the root, each module instance's body is evaluated
     under its parameter environment — `if` picks a branch, `for`
     unrolls, arrays replicate — once per distinct (definition,
     environment), and the instance tree is built from the results;
  G. reporting: a body defect found identically under every environment
     the design gives its definition is reported once per definition, as
     in v0.1; one found under some environments only depends on the
     values and is reported per instance, carrying that entity;
  H. flattening: nets are a union-find over (instance path, port) nodes,
     so a module port — named by the parent as `inst.port` and by the
     module as `port` — is one node and nets merge across the hierarchy
     with no special case. A defect of a flattened net that every copy of
     a module repeats alike is reported once, as pass G does for bodies.

NET NAMES. The shallowest label wins; two different labels at that depth
are an error. A label declared inside a module instance is qualified by
the instance path (`indicator/LED`, `cells[2]/LED`) always, so a name never
depends on unrelated parts of the design. An unlabelled net is `N_` plus
its lexicographically least member, spelled `<instance path without the
leading slash>.<port>` — so a root port `vin` is `.vin` and its net
`N_.vin`. That rule is interim (R27/M3 owns naming) and is recorded in the
spec so a later change is a ledgered one. Every net a statement creates is
emitted, including the single-member net `isolated` makes.

FLAGS on a module instance are inherited by every descendant (logical
OR). Quantities keep their exact value; `rhoform/ir.py` performs the one
Decimal-to-double conversion at emission, and this module refuses, with a
diagnostic, any number that conversion could not carry.

THE STANDARD LIBRARY is `rhoform/lib/<module>.rhoform`, files of
`component` definitions only, listed in the source map as exactly that path
so a definition's name, `rhoform.lib.<module>.<Name>`, follows the one
naming rule. A compilation reads the library modules its qualified names
mention and no other, so adding a module changes no existing design's
`source_hash`. A library definition is used like one of the file's own:
its pins are the instance's ports, inline pins must restate them, and its
parameter list, when it has one, checks the arguments.

REPLICATION is budgeted: loop iterations and array members together are
capped at EXPANSION_LIMIT per design, counted over every instance, so a
source that parses cannot make elaboration slow.

FILES. A compilation is the entry file plus the files it imports, which
the package layer (`rhoform/package.py`) finds, reads and resolves; this
module binds the imported names. Called with files and no resolution, it
resolves their imports among exactly those files.

SYNTAX 0.3 (unfrozen) adds source facts no check reads yet: a component
definition's electrical rules and sides, and the `rule` statements that
give one instance others (Instance.rules); the `supply`, `draw` and
`waive` statements, each resolved to the IR entity it names and kept once
per module instance that states it (ElaboratedDesign.annotations); an
assertion's severity; and a net's authored `ground_kind`. Elaborating them
checks only what needs no electrical meaning: that a target names
something, that a fact is stated once, that a rule names pins its
component has. What they MEAN is the check stage's (spec 05).

FOR THE CHECKER, IN MEMORY ONLY. The static stage (`rhoform.check`) reads
this design, never the IR, so the design carries source facts the IR does
not: every site of a net attribute (Net.attribute_sites) and of an
endpoint (Net.endpoint_spans), each port's declaration (Port.declaration),
how each part constraint was written (Part.sites), each assertion's bound
(Assertion.bound_span), and where each rule and annotation was written and
whether a rule is its definition's or an override. `rhoform/ir.py`
serializes none of them, so they change no IR byte and no hash. IR
version 2 does serialize what an `isolated` statement made (Net.isolated)
and the 0.3 facts above.
"""

from dataclasses import dataclass, field, replace
from decimal import Decimal
from difflib import get_close_matches
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re

from . import quantities
from .diagnostics import Diagnostics, Edit, FixIt, Span, span_from_bytes

STATIC_MEASUREMENTS = frozenset(
    {"operating_point", "power_avg", "power_rms", "efficiency"})
PINLESS_HARDWARE = frozenset({"mounting_hole", "fiducial", "artwork"})
SINGLE_PIN_HARDWARE = frozenset({"test_point", "grounded_mounting_hole"})
FLAGS = ("dnp", "exclude_from_bom", "board_only")
MAX_IR_INTEGER = 2 ** 53
# Loop iterations plus array members, per design (decision S-4).
EXPANSION_LIMIT = 4096

# The bundled standard library (E-4, E-5, E-8): the reserved prefix of a
# qualified name, where its modules live, and how the source map lists them.
LIBRARY_PREFIX = ("rhoform", "lib")
LIBRARY_DIR = Path(__file__).resolve().parent / "lib"
LIBRARY_SUFFIX = ".rhoform"

_PAIR_RE = re.compile(r"\A(-?[0-9]+(?:\.[0-9]+)?)(.+)\Z")
_IDENTIFIER_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")
_EQUALITY = ("==", "!=")


class _Unknown:
    """A value elaboration could not determine because an error was
    already reported for it. Anything computed from it is skipped
    quietly, so one defect is one diagnostic."""

    def __repr__(self):
        return "<unknown>"


UNKNOWN = _Unknown()


# ---- the elaborated design ------------------------------------------------

@dataclass(frozen=True)
class Quantity:
    """A quantity in its T3 normal-form unit: `value` is the nominal's
    mantissa there, `tolerance` the absolute (min, max) in the same unit,
    or None when the literal was exact."""

    value: Decimal
    unit: str
    tolerance: tuple[Decimal, Decimal] | None = None


@dataclass(frozen=True)
class Port:
    name: str
    role: str
    pin_numbers: tuple[str, ...] = ()
    # The `port` or `pin` statement declaring it: the definition's for a
    # library or file component, the instance's own for an ad-hoc one.
    # Not compared, so restating a pin elsewhere is still the same pin.
    declaration: Span | None = field(default=None, compare=False)


@dataclass(frozen=True)
class ConstraintSite:
    """How one part constraint was written. `form` is the authored shape of
    a quantity — `exact`, `toleranced` (a `+/-` band) or `interval` (a
    bracketed window) — or None for a string, an integer or a boolean. A
    `reference` to a parameter has the form of the value it evaluates to,
    `toleranced` when that value's band is symmetric about its nominal.
    `span` is the value's."""

    form: str | None
    origin: str  # "literal" | "reference"
    span: Span


@dataclass(frozen=True)
class Part:
    binding: str  # "abstract" | "resolved"
    lockfile_key: str | None
    constraints: dict
    sites: dict = field(default_factory=dict, compare=False)  # name -> site


@dataclass(frozen=True)
class Rule:
    """One electrical rule of a component instance (syntax 0.3): its word,
    the pins it covers in the order written, the pin after `from` or `to`
    (`relation` says which), and its value, evaluated in the environment of
    the instance (a definition's rule) or of the module stating it (an
    override). A side is a rule whose word is `side` and whose `side` is its
    name. `origin` is `definition` or `override`: an instance a `rule`
    statement names takes those rules in place of its definition's, and
    keeps its definition's sides. Inert until the check stage reads it."""

    word: str
    pins: tuple[str, ...]
    relation: str | None = None  # "from" | "to"
    other: str | None = None
    value: object = None
    side: str | None = None
    origin: str = field(default="definition", compare=False)
    span: Span | None = field(default=None, compare=False)


@dataclass
class Instance:
    path: str
    kind: str  # "module" | "component"
    definition: str
    parameters: dict
    ports: tuple[Port, ...]
    dnp: bool
    exclude_from_bom: bool
    board_only: bool
    hardware_kind: str | None
    part: Part | None
    declaration: Span
    trace: tuple[Span, ...]
    rules: tuple[Rule, ...] = ()  # components only (syntax 0.3)


@dataclass
class Net:
    name: str
    ground_domain: str | None
    voltage_domain: str | None
    members: tuple[tuple[str, str], ...]  # sorted (instance path, port)
    declaration: Span
    trace: tuple[Span, ...]
    # Made by an `isolated` statement: an intentional single-member net.
    isolated: bool = False
    # attribute -> [(value, span of the attribute)], one per site that sets
    # it, shallowest label first: both sides of a conflict, for a checker
    # that compares what elaboration only merges.
    attribute_sites: dict = field(default_factory=dict)
    # member -> the spans of every connecting statement naming it, in the
    # order of the sites that hold them (depth, path, file, offset).
    endpoint_spans: dict = field(default_factory=dict)
    # Syntax 0.3: the `ground_kind` every site that sets one agrees on, or
    # None (no site, or sites that disagree, which is the check stage's
    # GA-2 question over attribute_sites, never an elaboration error).
    ground_kind: str | None = None


@dataclass(frozen=True)
class Bounds:
    unit: str
    min: Decimal | None
    max: Decimal | None


@dataclass
class Assertion:
    path: str
    tier: str
    measurement: str
    subject: str  # the flattened net's final name
    bounds: Bounds
    declaration: Span
    trace: tuple[Span, ...]
    bound_span: Span | None = None  # its `within` / `at least` / `at most`
    severity: str = "error"  # "warning" with a trailing `warning` (0.3)


@dataclass(frozen=True)
class Annotation:
    """A design annotation (syntax 0.3): `supply` or `draw` with its
    bounds, or `waive` with its code and justification. `target` is the IR
    entity it names: ("net", name), ("port", instance path, port),
    ("instance", path) or ("assertion", path). `scope` is the path of the
    module instance whose body states it, so a statement in a module used
    twice is two annotations, as its assertions are two."""

    kind: str  # "supply" | "draw" | "waive"
    scope: str
    target: tuple
    bounds: Bounds | None = None
    code: str | None = None
    justification: str | None = None
    declaration: Span | None = field(default=None, compare=False)
    trace: tuple = field(default=(), compare=False)


@dataclass(frozen=True)
class SourceFile:
    path: str  # POSIX, relative to the compile root
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass
class ElaboratedDesign:
    design_name: str
    language_version: str
    instances: list[Instance]  # sorted by path
    nets: list[Net]  # sorted by name
    assertions: list[Assertion]  # sorted by path
    files: list[SourceFile]  # sorted by path; every source file read
    # Syntax 0.3, sorted by scope, kind, then target.
    annotations: list[Annotation] = field(default_factory=list)

    def connections(self) -> list[tuple[str, str, str]]:
        """(net, instance path, port), in the IR's sort order."""
        return sorted((net.name, path, port)
                      for net in self.nets for path, port in net.members)


@dataclass
class Elaboration:
    design: ElaboratedDesign | None
    diagnostics: Diagnostics

    @property
    def ok(self) -> bool:
        return self.design is not None and not self.diagnostics.has_errors


# ---- the standard library ---------------------------------------------------

def library_file(module: str) -> str:
    """The path a library module has in the source map and in spans."""
    return f"rhoform/lib/{module}{LIBRARY_SUFFIX}"


class Library:
    """The bundled standard library: `<directory>/<module>.rhoform`, one file
    per module. Module names are matched exactly as spelled on disk, so a
    case-insensitive filesystem cannot make `rhoform.lib.Passive` resolve
    where a case-sensitive one would not. Parses are cached per file
    content; the bytes are read on every load, so what a compilation lists
    is always what it read. A test may point one at another directory."""

    def __init__(self, directory=LIBRARY_DIR):
        self.directory = Path(directory)
        self._modules = None
        self._parsed = {}

    def modules(self) -> tuple:
        if self._modules is None:
            try:
                names = os.listdir(self.directory)
            except OSError:
                names = []
            stems = (name[:-len(LIBRARY_SUFFIX)] for name in names
                     if name.endswith(LIBRARY_SUFFIX))
            self._modules = tuple(sorted(
                stem for stem in stems if _IDENTIFIER_RE.match(stem)))
        return self._modules

    def load(self, module: str):
        """The ParseResult of `module`, or None when there is none."""
        if module not in self.modules():
            return None
        data = (self.directory / f"{module}{LIBRARY_SUFFIX}").read_bytes()
        key = (module, data)
        if key not in self._parsed:
            from .parser import parse

            self._parsed[key] = parse(
                data.decode("utf-8", "surrogateescape"),
                file=library_file(module))
        return self._parsed[key]


BUNDLED = Library()


def library_modules(results) -> list:
    """The library modules the qualified names of `results` mention, sorted:
    the third word of every name under the reserved prefix."""
    found = set()
    for result in results:
        work = [result.tree]
        while work:
            node = work.pop()
            if not _is_tree(node):
                continue
            if node.data == "qualified_name":
                words = _words(node)
                if tuple(words[:2]) == LIBRARY_PREFIX and len(words) > 2:
                    found.add(words[2])
                continue
            work.extend(node.children)
    return sorted(found)


def _component_names(result) -> list:
    return [str(node.children[1]) for node in result.tree.children
            if _is_tree(node) and node.data == "component_def"]


# ---- names ------------------------------------------------------------------

def _identifier(segment: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", segment)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned


def module_path(path: str) -> str:
    """A file's dotted module path: its compile-root-relative path without
    `.rhoform`, `/` turned into `.`, each segment made an identifier."""
    text = path[:-len(".rhoform")] if path.endswith(".rhoform") else path
    parts = [part for part in PurePosixPath(text).parts
             if part not in ("/", ".")]
    return ".".join(_identifier(part) for part in parts) or "_"


def child_path(parent: str, name: str) -> str:
    return "/" + name if parent == "/" else f"{parent}/{name}"


def member_spelling(path: str, port: str) -> str:
    """How an unlabelled net's members are spelled for its derived name."""
    return f"{path[1:]}.{port}"


def _qualified_label(path: str, label: str) -> str:
    return label if path == "/" else f"{path[1:]}/{label}"


# ---- tree access (lark trees, duck-typed: no lark import here) --------------

def _is_tree(node) -> bool:
    return hasattr(node, "children")


def _unwrap(node):
    while _is_tree(node) and node.data in ("statement", "instance_stmt"):
        node = node.children[0]
    return node


def _trees(node, data: str) -> list:
    return [c for c in node.children if _is_tree(c) and c.data == data]


def _tree(node, data: str):
    found = _trees(node, data)
    return found[0] if found else None


def _tokens(node, kind: str) -> list:
    return [c for c in node.children if not _is_tree(c) and c.type == kind]


def _words(node) -> list[str]:
    return [str(c) for c in node.children if not _is_tree(c)]


def _designator(node) -> str:
    """A `designator` node's pad: a quoted one (0.3) is its text without
    the quotes, so `"01"` is the designator `01` and `"3"` is `3`."""
    token = node.children[0]
    text = str(token)
    return text[1:-1] if token.type == "QUOTED_DESIGNATOR" else text


def _rule_parts(body):
    """A `rule_body` as (word token, pin tokens, relation, other pin
    token, value tree): `regulate OUT from IN = v`."""
    word, *rest = body.children
    pins, relation, other, value = [], None, None, None
    for child in rest:
        if _is_tree(child):
            value = child
        elif str(child) in ("from", "to"):  # never a pin's name here
            relation = str(child)
        elif relation is None:
            pins.append(child)
        else:
            other = child
    return word, pins, relation, other, value


def _block_statements(block) -> list:
    return [_unwrap(c) for c in block.children
            if _is_tree(c) and c.data == "statement"]


def _one_close(word: str, choices):
    """The one choice close to `word`, or None when none or several are."""
    matches = get_close_matches(word, sorted(choices), n=2, cutoff=0.6)
    return matches[0] if len(matches) == 1 else None


def _did_you_mean(word: str, choices, span: Span) -> tuple:
    match = _one_close(word, choices)
    if match is None:
        return ()
    return (FixIt(f"did you mean `{match}`?", "needs-review",
                  (Edit(span, match),)),)


def _span_through(result, start: int, after: int, char: bytes) -> Span:
    """A header span: from `start` to just past the next `char` at or
    after `after`, skipping spaces, line breaks and comments (author
    bytes). Used where the grammar filters the closing token out."""
    data = result.data
    position = after
    while position < len(data):
        byte = data[position:position + 1]
        if byte == char:
            position += 1
            break
        if byte == b"#":
            newline = data.find(b"\n", position)
            position = len(data) if newline < 0 else newline
        elif byte in (b" ", b"\n"):
            position += 1
        else:
            position = after
            break
    return span_from_bytes(result.file, data, start, max(start, position))


def _text_of(result, node) -> str:
    span = result.span_of(node)
    return result.data[span.byte_start:span.byte_end].decode(
        "utf-8", "surrogateescape")


# ---- values -----------------------------------------------------------------

def _base_unit(dimension: str) -> str:
    return next(symbol for symbol, (dim, mult) in quantities.UNITS.items()
                if dim == dimension and mult == 1)


def _in_unit(base: Decimal, multiplier: Decimal) -> Decimal:
    """`base / multiplier` for a power-of-ten multiplier, exactly: the
    division is an exponent shift, so no context can round it."""
    sign, digits, exponent = base.as_tuple()
    return Decimal((sign, digits, exponent - multiplier.adjusted()))


def _unit_for(base: Decimal, dimension: str) -> tuple[str, Decimal]:
    """The T3 normal-form unit for a base-unit value, taken from
    rhoform.quantities.normal_form itself so the IR cannot disagree with
    the formatter about which unit a value belongs in."""
    spelled = quantities.normal_form(
        format(base, "f") + _base_unit(dimension))
    symbol = _PAIR_RE.match(spelled).group(2)
    return symbol, quantities.UNITS[symbol][1]


def _representable(*values: Decimal) -> bool:
    return all(abs(float(value)) != float("inf") for value in values)


# A quantity literal's form, as ConstraintSite records it.
_AUTHORED_FORM = {"exact": "exact", "tolerance-absolute": "toleranced",
                  "tolerance-percent": "toleranced",
                  "interval-bracketed": "interval",
                  "interval-bare": "interval"}


def _literal_form(token) -> str | None:
    """The authored form of a value literal: None unless it is a quantity."""
    if token.type in ("STRING", "INTEGER") or str(token) in ("true",
                                                             "false"):
        return None
    return _AUTHORED_FORM[quantities.parse_quantity(str(token)).form]


def _value_form(value) -> str | None:
    """The form of an evaluated value, for a reference whose literal lies
    elsewhere: a band symmetric about the nominal is `toleranced`."""
    if not isinstance(value, Quantity):
        return None
    if value.tolerance is None:
        return "exact"
    low, high = value.tolerance
    return "toleranced" if value.value - low == high - value.value \
        else "interval"


# Value types. A parameter's declared type is one of the param_type words:
# `string`, `int`, `bool`, or a quantity dimension. A bare-interval literal
# has the type ("interval", dimension): it is never a parameter value.

def _beyond_ir(integer: str) -> bool:
    """Whether an INTEGER token's magnitude exceeds 2^53 (RHO2017). Its
    digits have no leading zero, and 2^53 has 16, so a longer one is past
    it without int(), which CPython refuses for a long enough digit string
    (sys.get_int_max_str_digits)."""
    digits = integer.lstrip("-")
    return len(digits) > 16 or int(digits) > MAX_IR_INTEGER


def _literal_type(token):
    kind = token.type
    if kind == "STRING":
        return "string"
    if kind == "INTEGER":
        return "int"
    if str(token) in ("true", "false"):
        return "bool"
    parsed = quantities.parse_quantity(str(token))
    if parsed.nominal is None:
        return ("interval", parsed.dimension)
    return parsed.dimension


def _article(word: str) -> str:
    return ("an " if word[0] in "aeiou" else "a ") + word


def _describe(kind) -> str:
    if isinstance(kind, tuple):
        return _article(f"{kind[1]} interval")
    return _article(kind)


def _assignable(found, expected) -> bool:
    """Whether a value of type `found` may stand where `expected` is
    declared. A bare interval of the right dimension is not a type error:
    RHO2016 (no nominal) is the precise report for it."""
    if found == expected:
        return True
    return isinstance(found, tuple) and found[1] == expected


def _comparable(value):
    """A value as (kind, payload) for an exact comparison, or None."""
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, Quantity):
        dimension = quantities.UNITS[value.unit][0]
        return (dimension, quantities.to_base(value.value, value.unit))
    return None


def _compare(op: str, left, right):
    a, b = _comparable(left), _comparable(right)
    if a is None or b is None or a[0] != b[0]:
        return None
    x, y = a[1], b[1]
    if op == "==":
        return x == y
    if op == "!=":
        return x != y
    if a[0] in ("bool", "string"):
        return None
    return {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]


def _env_key(values: dict) -> tuple:
    return tuple((name, type(value).__name__, value)
                 for name, value in sorted(values.items()))


@dataclass(frozen=True)
class _Env:
    """A definition's parameter environment: every declared parameter's
    resolved value (UNKNOWN when an error was reported for it)."""

    values: tuple  # ((name, value), ...) in declaration order

    @property
    def key(self) -> tuple:
        return _env_key(dict(self.values))

    def get(self, name, default=None):
        for key, value in self.values:
            if key == name:
                return value
        return default


EMPTY_ENV = _Env(())


# ---- per-definition working state ------------------------------------------

@dataclass
class _Param:
    name: str
    type: str
    span: Span
    has_default: bool = False
    default_ref: str | None = None  # a default naming an earlier parameter
    default_value: object = UNKNOWN  # a literal default, evaluated once


@dataclass
class _Definition:
    name: str
    result: object  # the ParseResult of its file
    tree: object
    header: Span
    definition: str
    order: int
    kind: str = "module"  # "module" | "component"
    params: list | None = None  # _Param, source order; None: no list
    ports: list = field(default_factory=list)  # Port, source order
    roles: dict = field(default_factory=dict)  # port name -> role
    edges: list = field(default_factory=list)  # (member, target, span)
    paths: list = field(default_factory=list)  # its instance paths
    pin_spans: dict = field(default_factory=dict)  # component pin -> span
    quiet_ports: set = field(default_factory=set)  # misplaced port names
    quiet_members: set = field(default_factory=set)  # misplaced members
    library: bool = False  # a standard library definition
    # A component's rules and sides (0.3), in source order: Rule templates
    # whose `value` is the evaluated literal, or ("reference", name) for a
    # parameter the instance's environment supplies.
    rules: list = field(default_factory=list)

    @property
    def spelled(self) -> str:
        """The definition as a source names it: a library one by its
        dotted name, which is how every source spells it."""
        return self.definition if self.library else self.name


@dataclass
class _Member:
    name: str
    kind: str
    definition: str
    target: _Definition | None
    parameters: dict
    roles: dict  # port name -> role, for endpoint resolution
    ports: tuple = ()
    flags: dict = field(default_factory=dict)
    hardware_kind: str | None = None
    part: Part | None = None
    span: Span | None = None
    broken: bool = False  # failed to resolve; endpoints on it stay quiet
    env: _Env = EMPTY_ENV  # a module member's parameter environment


@dataclass
class _Endpoint:
    member: str | None  # None: one of the module's own ports
    port: str
    text: str  # as evaluated: `leds[2].a`
    span: Span
    written: str = ""  # as written: `leds[i].a`


@dataclass
class _Connect:
    kind: str  # "net" | "chain" | "isolated"
    endpoints: list
    span: Span
    label: str | None = None
    attributes: dict = field(default_factory=dict)
    node: object = None  # the statement, so a loop's label is one label
    attribute_spans: dict = field(default_factory=dict)  # attribute -> span


@dataclass
class _Check:
    name: str
    tier: str
    measurement: str
    subject: str
    bounds: Bounds | None
    span: Span
    bound_span: Span | None = None
    severity: str = "error"


@dataclass
class _Note:
    """A 0.3 annotation statement of one module body, its target resolved
    within the body: ("label", label), ("pin", member or None, port),
    ("member", member) or ("assertion", name). Flattening turns it into
    an Annotation on the IR entity."""

    kind: str
    target: tuple
    bounds: Bounds | None
    code: str | None
    justification: str | None
    span: Span


@dataclass
class _Findings:
    """Diagnostics held back until the design's instance paths are known,
    deduplicated: the same defect reached twice (two loop iterations, two
    passes) is one finding. `about` is the member name the IR entity is
    built from, or None."""

    order: list = field(default_factory=list)  # keys, first-seen order
    items: dict = field(default_factory=dict)  # key -> [code, params, kw, about]

    def add(self, code, params, kwargs, about):
        key = (code, json.dumps(params, sort_keys=True),
               kwargs.get("primary"), tuple(kwargs.get("secondary", ())),
               tuple(kwargs.get("fixits", ())))
        if key in self.items:
            if self.items[key][3] != about:
                self.items[key][3] = None
            return
        self.order.append(key)
        self.items[key] = [code, params, kwargs, about]


@dataclass
class _Model:
    """One module body evaluated under one parameter environment."""

    env: _Env
    members: dict = field(default_factory=dict)  # IR segment -> _Member
    arrays: dict = field(default_factory=dict)  # name -> size or None
    quiet: set = field(default_factory=set)  # names skipped after an error
    connects: list = field(default_factory=list)
    labels: dict = field(default_factory=dict)  # label -> _Connect
    checks: list = field(default_factory=list)
    findings: _Findings = field(default_factory=_Findings)
    units: int = 0  # loop iterations + array members expanded here
    sites: list = field(default_factory=list)  # (span, units, construct)
    paths: list = field(default_factory=list)  # instance paths using it
    overrides: dict = field(default_factory=dict)  # member -> [Rule] (0.3)
    notes: list = field(default_factory=list)  # _Note (0.3)


def _annotation_key(annotation) -> tuple:
    """Annotations in a stable order: by scope, kind and target, then code
    and bounds, which tell apart the facts one target may carry."""
    bounds = annotation.bounds
    return (annotation.scope, annotation.kind, annotation.target,
            annotation.code or "",
            () if bounds is None else (bounds.unit, str(bounds.min),
                                       str(bounds.max)))


class _UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, node):
        self.parent.setdefault(node, node)
        root = node
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[node] != root:
            self.parent[node], node = root, self.parent[node]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


# ---- the elaborator ---------------------------------------------------------

def elaborate(results, *, root: str | None = None,
              sink: Diagnostics | None = None,
              imports: dict | None = None,
              library: Library | None = None,
              modules: dict | None = None) -> Elaboration:
    """Elaborate a compilation: `results[0]` is the entry file's
    ParseResult, any others are the files it imports. `root` names the
    root module explicitly; otherwise it is the unique module of the entry
    file that nothing instantiates. `imports` is the package layer's
    resolution of every file's import statements (`package.load`); when
    it is None they are resolved among `results` alone (`package.link`),
    and any problem doing so stops elaboration as it would at load.
    `library` is the standard library names under `rhoform.lib.` resolve
    against: the bundled one unless a test supplies another. `modules` is
    the package layer's name for each file (`package.load`), which a file
    a manifest governs takes from its package's identity; a file it does
    not name is named by its compile-root-relative path."""
    results = list(results)
    sink = sink if sink is not None else Diagnostics()
    if not results:
        raise ValueError("elaborate() needs at least the entry file")
    if not all(result.ok for result in results):
        for result in results:
            if result.diagnostics is not sink:
                sink.extend(result.diagnostics)
        return Elaboration(None, sink)
    if imports is None:
        from .package import link

        errors = sink.counts()["error"]
        imports = link(results, sink)
        if sink.counts()["error"] > errors:
            return Elaboration(None, sink)
    design = _Elaborator(results, sink, imports,
                         BUNDLED if library is None else library,
                         modules or {}).run(root)
    if sink.has_errors:
        design = None
    return Elaboration(design, sink)


def elaborate_source(source: str, path: str = "design.rhoform", *,
                     root: str | None = None,
                     library: Library | None = None) -> Elaboration:
    """Parse and elaborate one file whose compile-root-relative path is
    `path`. The convenience entry point for tests and single files."""
    from .parser import parse

    result = parse(source, file=path)
    return elaborate([result], root=root, library=library)


class _Elaborator:
    def __init__(self, results, sink: Diagnostics, imports: dict,
                 library: Library, modules: dict):
        self.results = results
        self.sink = sink
        self.imports = imports
        self.library = library
        self.modules = modules  # file -> module name, from the package layer
        self.defs: list[_Definition] = []
        self.visible: dict[str, dict[str, _Definition]] = {}
        self.unbound: dict[str, set] = {}  # file -> names an import failed
        self.library_files: set[str] = set()  # paths of library modules read
        self.models: dict = {}  # (id(defn), env key) -> _Model
        self.model_order: dict = {}  # id(defn) -> [_Model], first-use order
        self.static: dict = {}  # id(defn) -> _Findings
        self.mentioned: set[int] = set()
        self.bucket: _Findings | None = None
        self.bad: set[int] = set()  # node ids an error was reported for
        self.misplaced: set[int] = set()  # statements refused by placement
        self.current_env = EMPTY_ENV  # the body being evaluated
        self.limit_reported = False
        self.elaborated: set[str] = set()  # instance paths the walk built
        self.spare_roots: list = []  # root candidates, when several
        self.unresolved_news: list = []  # (defn, qualified), taken or not

    # -- reporting

    def report(self, code, params, primary, *, about=None, entity=None,
               **kwargs):
        """Report now (design-level diagnostics), or hold the finding in
        the current definition's bucket until its paths are known."""
        if self.bucket is not None:
            self.bucket.add(code, params, dict(kwargs, primary=primary),
                            about)
            return
        self.sink.add(code, params, primary=primary, entity=entity,
                      **kwargs)

    def publish(self) -> None:
        """Emit every held finding, now that instance paths are known.

        A static finding, or a body finding present under every
        environment the design gives its definition, is reported once and
        carries an entity only when the definition has exactly one
        instance path (a static finding only when the member it is about
        was elaborated: it may stand in a branch not taken). A body
        finding present under some environments only is reported once
        per instance path whose environment shows it, in path order,
        carrying that instance's entity (the member it is about, or the
        module instance itself)."""
        for defn in self.defs:
            once = []
            findings = self.static.get(id(defn))
            if findings is not None:
                once += [(findings.items[key], True)
                         for key in findings.order]
            models = self.model_order.get(id(defn), [])
            everywhere = None
            for model in models:
                keys = set(model.findings.items)
                everywhere = keys if everywhere is None else everywhere & keys
            per_instance = []
            seen = set()
            for model in models:
                for key in model.findings.order:
                    item = model.findings.items[key]
                    if key in everywhere:
                        if key in seen:
                            continue
                        seen.add(key)
                        abouts = {m.findings.items[key][3] for m in models}
                        merged = list(item)
                        merged[3] = item[3] if len(abouts) == 1 else None
                        once.append((merged, False))
                    else:
                        per_instance += [(item, path)
                                         for path in model.paths]
            for (code, params, kwargs, about), static in once:
                entity = None
                if about is not None and len(defn.paths) == 1:
                    entity = child_path(defn.paths[0], about)
                    if static and entity not in self.elaborated:
                        entity = None
                self.sink.add(code, params, entity=entity, **kwargs)
            # Stable: copies of one diagnostic tie in the sink's canonical
            # order, so inserting them by path is what orders them.
            per_instance.sort(key=lambda entry: entry[1])
            for (code, params, kwargs, about), path in per_instance:
                entity = child_path(path, about) if about else path
                self.sink.add(code, params, entity=entity, **kwargs)

    # -- driver

    def run(self, root: str | None) -> ElaboratedDesign | None:
        for result in list(self.results):
            self.collect_definitions(result)
        self.load_library()
        self.bind_imports()
        for defn in self.defs:
            self.within(defn, self.collect_params, defn)
        for defn in self.defs:
            self.within(defn, self.collect_ports, defn)
        for defn in self.defs:
            if defn.kind == "module":
                self.collect_edges(defn)
        for defn in self.defs:
            if defn.kind == "module":
                self.within(defn, self.check_static, defn)
        cyclic = self.report_cycles()
        root_def = None
        if not cyclic:
            root_def = self.select_root(root)
        walked = None
        if root_def is not None:
            walked = self.walk(root_def)
        for defn in self.defs:
            if defn.kind == "module" and id(defn) not in self.model_order:
                # Not reached by the walk: still checked, once, under its
                # defaults, so its defects are not hidden by another one.
                self.model(defn, self.bind_defaults(defn))
        self.report_spare_roots()
        self.publish()
        if walked is None:
            return None
        return self.flatten(root_def, *walked)

    def within(self, defn, method, *args):
        """Run a per-definition pass with its findings held back."""
        saved = self.bucket
        self.bucket = self.static.setdefault(id(defn), _Findings())
        try:
            return method(*args)
        finally:
            self.bucket = saved

    # -- pass A: definitions and their parameter lists

    def load_library(self) -> None:
        """Read the library modules the sources mention, and only those
        (E-8): each joins the compilation as a source file, listed in the
        source map, its definitions named `rhoform.lib.<module>.<Name>`. A
        module that does not parse is a defect of the toolchain, reported
        as its parse diagnostics; its names then resolve to nothing. So do
        the names of a module whose library path an author's own source
        already occupies, which the package layer refuses (RHO2068) before
        elaboration: this only keeps a caller that brings its own imports
        from making one path name two files."""
        for module in library_modules(self.results):
            if library_file(module) in self.visible:
                continue
            result = self.library.load(module)
            if result is None:
                continue
            if not result.ok:
                self.sink.extend(result.diagnostics)
                continue
            self.results.append(result)
            self.library_files.add(result.file)
            self.collect_definitions(result, library=True)

    def collect_definitions(self, result, library: bool = False) -> None:
        mpath = self.modules.get(result.file) or module_path(result.file)
        table = self.visible.setdefault(result.file, {})
        for node in result.tree.children:
            if not (_is_tree(node)
                    and node.data in ("module_def", "component_def")):
                continue
            kind = "module" if node.data == "module_def" else "component"
            keyword, name_token = node.children[0], node.children[1]
            name = str(name_token)
            params = _tree(node, "params")
            after = result.span_of(params or name_token).byte_end
            header = _span_through(
                result, result.span_of(keyword).byte_start, after, b":")
            if name in table:
                first = table[name]
                if first.kind == "module" and kind == "module":
                    self.report(
                        "RHO2001", {"name": name}, header,
                        secondary=((first.header, "first defined here"),))
                else:
                    self.report(
                        "RHO2034",
                        {"name": name, "first": first.kind, "second": kind},
                        header,
                        secondary=((first.header, "first defined here"),))
                continue
            defn = _Definition(name=name, result=result, tree=node,
                               header=header,
                               definition=f"{mpath}.{name}",
                               order=len(self.defs), kind=kind,
                               library=library)
            table[name] = defn
            self.defs.append(defn)

    def bind_imports(self) -> None:
        """Make each imported name visible in its importing file as the
        definition of that name in the file it comes from. Only a file's
        own definitions can be imported (nothing is re-exported). A name
        whose import failed is remembered, so the uses of it stay quiet:
        the import is the one defect."""
        own = {file: dict(table) for file, table in self.visible.items()}
        for result in self.results:
            table = self.visible.setdefault(result.file, {})
            unbound = self.unbound.setdefault(result.file, set())
            bound = {}
            for record in self.imports.get(result.file, ()):
                defined = own.get(record.target) if record.target else None
                for name, span in record.names:
                    if name in own.get(result.file, {}):
                        self.report(
                            "RHO2066",
                            {"name": name, "first": "by its own definition"},
                            span, secondary=((table[name].header,
                                              "defined here"),))
                        continue
                    if name in bound:
                        self.report(
                            "RHO2066",
                            {"name": name, "first": "by an earlier import"},
                            span, secondary=((bound[name],
                                              "first imported here"),))
                        continue
                    bound[name] = span
                    if defined is None:
                        unbound.add(name)
                    elif name not in defined:
                        unbound.add(name)
                        self.report(
                            "RHO2065", {"name": name, "file": record.target},
                            span, fixits=_did_you_mean(name, defined, span))
                    else:
                        table[name] = defined[name]

    def collect_params(self, defn: _Definition) -> None:
        node = _tree(defn.tree, "params")
        # An empty `()` is no list: the formatter drops it (F-7), so it
        # must not check arguments against nothing.
        if node is None or not _trees(node, "param"):
            return
        result = defn.result
        defn.params = []
        declared: dict[str, _Param] = {}
        for param in _trees(node, "param"):
            name = str(_tokens(param, "FREE_NAME")[0])
            kind = str(_tokens(param, "NAME")[0])
            span = result.span_of(param)
            if name in declared:
                self.report(
                    "RHO2007",
                    {"kind": "parameter", "name": name,
                     "scope": f"{defn.kind} `{defn.name}`"},
                    span, secondary=((declared[name].span,
                                      "first declared here"),))
                continue
            entry = _Param(name, kind, span)
            value = _tree(param, "value")
            if value is not None:
                entry.has_default = True
                token = value.children[0]
                context = f"the default of `{name}`"
                if token.type == "FREE_NAME":
                    ref = str(token)
                    if ref not in declared:
                        tspan = result.span_of(token)
                        self.report(
                            "RHO2039",
                            {"name": ref, "definition": defn.name},
                            tspan, fixits=_did_you_mean(ref, declared,
                                                        tspan))
                    elif declared[ref].type != kind:
                        self.mismatch(defn, value, declared[ref].type,
                                      context, kind)
                    else:
                        entry.default_ref = ref
                elif not _assignable(_literal_type(token), kind):
                    self.mismatch(defn, value, _literal_type(token),
                                  context, kind)
                else:
                    evaluated = self.value(defn, value, name, EMPTY_ENV)
                    entry.default_value = evaluated
            declared[name] = entry
            defn.params.append(entry)

    def mismatch(self, defn, node, found, context, expected) -> None:
        self.bad.add(id(node))
        self.report(
            "RHO2038",
            {"value": _text_of(defn.result, node),
             "found": _describe(found), "context": context,
             "expected": _describe(expected)},
            defn.result.span_of(node))

    def statements(self, defn: _Definition):
        return [_unwrap(c) for c in defn.tree.children
                if _is_tree(c) and c.data == "statement"]

    # -- pass B: own ports, component pins

    def collect_ports(self, defn: _Definition) -> None:
        if defn.kind == "component":
            self.collect_pins(defn)
            return
        spans = {}
        for stmt in self.statements(defn):
            if stmt.data != "port_decl":
                continue
            name_token = _tokens(stmt, "FREE_NAME")[0]
            name, role = str(name_token), str(_tokens(stmt, "NAME")[0])
            span = defn.result.span_of(stmt)
            if name in spans:
                self.report(
                    "RHO2007",
                    {"kind": "port", "name": name,
                     "scope": f"module `{defn.name}`"},
                    span, secondary=((spans[name], "first declared here"),))
                continue
            spans[name] = span
            defn.ports.append(Port(name, role, declaration=span))
            defn.roles[name] = role

    def collect_pins(self, defn: _Definition) -> None:
        result = defn.result
        for pin_node in _trees(defn.tree, "pin_decl"):
            pin, role = (str(t) for t in _tokens(pin_node, "NAME")[:2])
            span = result.span_of(pin_node)
            if pin in defn.pin_spans:
                self.report(
                    "RHO2007",
                    {"kind": "pin", "name": pin,
                     "scope": f"component `{defn.name}`"},
                    span, secondary=((defn.pin_spans[pin],
                                      "first declared here"),))
                continue
            defn.pin_spans[pin] = span
            designators = []
            for designator in _trees(pin_node, "designator"):
                text = _designator(designator)
                if text in designators:
                    self.report(
                        "RHO2007",
                        {"kind": "designator", "name": text,
                         "scope": f"pin `{pin}` of component "
                                  f"`{defn.name}`"},
                        result.span_of(designator))
                    continue
                designators.append(text)
            defn.ports.append(Port(pin, role, tuple(sorted(designators)),
                                   declaration=span))
            defn.roles[pin] = role
        self.collect_rules(defn)

    def collect_rules(self, defn: _Definition) -> None:
        """A component definition's rules and sides (syntax 0.3), each
        checked once: its pins are the component's (RHO2082), a side's
        name is declared once (RHO2007), a reference in a value names one
        of its parameters (RHO2039). A literal value is evaluated here,
        once; a reference is evaluated per instance, in its environment."""
        result = defn.result
        scope = {p.name: p.type for p in defn.params or ()}
        sides = {}
        for node in defn.tree.children:
            if not _is_tree(node) or node.data not in ("rule_decl",
                                                       "side_decl"):
                continue
            span = result.span_of(node)
            if node.data == "side_decl":
                _word, name_token, *pins = [c for c in node.children
                                            if not _is_tree(c)]
                name = str(name_token)
                if name in sides:
                    self.report(
                        "RHO2007",
                        {"kind": "side", "name": name,
                         "scope": f"component `{defn.name}`"},
                        span, secondary=((sides[name], "first declared "
                                          "here"),))
                    continue
                sides[name] = span
                if self.rule_pins(defn, "side", pins, defn.roles,
                                  defn.spelled):
                    defn.rules.append(Rule(
                        "side", tuple(map(str, pins)), side=name,
                        span=span))
                continue
            word, pins, relation, other, value = _rule_parts(
                node.children[0])
            named = pins + ([other] if other is not None else [])
            known = self.rule_pins(defn, str(word), named, defn.roles,
                                   defn.spelled)
            evaluated = None
            if value is not None:
                token = value.children[0]
                if token.type == "FREE_NAME":
                    if self.reference(defn, token, scope) is None:
                        continue
                    evaluated = ("reference", str(token))
                else:
                    evaluated = self.value(defn, value, str(word), EMPTY_ENV)
                    if evaluated is UNKNOWN:
                        continue
            if known:
                defn.rules.append(Rule(
                    str(word), tuple(map(str, pins)), relation,
                    None if other is None else str(other), evaluated,
                    span=span))

    def rule_pins(self, defn, word, tokens, roles, component) -> bool:
        """Every pin a rule names is one of the component's (RHO2082);
        False when one is not."""
        known = True
        for token in tokens:
            if str(token) not in roles:
                known = False
                span = defn.result.span_of(token)
                self.report("RHO2082", {"pin": str(token), "word": word,
                                        "component": component},
                            span, fixits=_did_you_mean(str(token), roles,
                                                       span))
        return known

    # -- pass C: the instantiation graph

    def resolve(self, defn: _Definition, qualified):
        """(kind, target, definition) for a qualified_name tree, or None
        when a single-word name is not visible or a name under the
        reserved prefix `rhoform.lib.` is not a library definition. The one
        place definitions resolve, so imports land here too. `target` is
        the module or component definition, or None for an ad-hoc
        component (any other dotted name)."""
        words = _words(qualified)
        if len(words) == 1:
            target = self.visible[defn.result.file].get(words[0])
        elif tuple(words[:2]) == LIBRARY_PREFIX:
            target = None
            if len(words) == 4:
                table = self.visible.get(library_file(words[2]), {})
                target = table.get(words[3])
                if target is not None and not target.library:
                    target = None
        else:
            return "component", None, ".".join(words)
        if target is None:
            return None
        return target.kind, target, target.definition

    def unresolved(self, defn, qualified) -> None:
        """Report a qualified name `resolve` found nothing for: RHO2005
        for a single word, RHO2067 under the library's reserved prefix,
        each with the one close match as a fix-it when there is one. A
        single word whose import failed is not reported again: the import
        is the one defect."""
        words = _words(qualified)
        name = ".".join(words)
        span = defn.result.span_of(qualified)
        if len(words) == 1:
            if name in self.unbound.get(defn.result.file, ()):
                return
            self.report("RHO2005", {"name": name}, span,
                        fixits=_did_you_mean(
                            name, self.visible[defn.result.file], span))
            return
        self.report("RHO2067", {"name": name}, span,
                    fixits=self.library_fixits(words, span))

    def library_fixits(self, words, span) -> tuple:
        """The one library name a misspelled one is close to, as a fix-it.
        Words are compared one at a time: whole dotted names share their
        prefix, so every name of a module would look close. A misspelled
        module is corrected only when the component name then exists in
        it. Reads at most the one module named or meant, and only on this
        path, where the compilation produces nothing."""
        if len(words) != 4:
            return ()
        module, name = words[2], words[3]
        modules = self.library.modules()
        if module not in modules:
            module = _one_close(module, modules)
            if module is None:
                return ()
        result = self.library.load(module)
        names = _component_names(result) if result is not None \
            and result.ok else []
        if name not in names:
            name = _one_close(name, names)
            if name is None or module != words[2]:
                return ()
        full = ".".join((*LIBRARY_PREFIX, module, name))
        return (FixIt(f"did you mean `{full}`?", "needs-review",
                      (Edit(span, full),)),)

    def collect_edges(self, defn: _Definition) -> None:
        """Every instantiation of a module anywhere in the body, taken or
        not: whether a module may contain itself, and which module is the
        root, do not depend on parameter values."""
        seen = set()
        work = [(stmt, True) for stmt in reversed(self.statements(defn))]
        while work:
            stmt, top = work.pop()
            if stmt.data in ("if_stmt", "for_stmt"):
                for block in reversed(_trees(stmt, "block")):
                    work += [(s, False)
                             for s in reversed(_block_statements(block))]
            elif stmt.data == "instance_decl":
                name = str(stmt.children[0])
                if top:
                    if name in seen:
                        continue
                    seen.add(name)
                qualified = _tree(stmt, "qualified_name")
                resolved = self.resolve(defn, qualified)
                if resolved is None and len(_words(qualified)) == 1:
                    self.unresolved_news.append((defn, qualified))
                elif resolved is not None and resolved[0] == "module":
                    defn.edges.append(
                        (name, resolved[1], defn.result.span_of(stmt)))
            elif stmt.data == "table_decl":
                if top:
                    for row in _trees(stmt, "table_row"):
                        seen.add(str(row.children[0]))
                # A table over a module is an error of its own (RHO2006);
                # counting the module as used keeps that one defect from
                # also making the module a second root candidate.
                resolved = self.resolve(defn, _tree(stmt, "qualified_name"))
                if resolved is not None and resolved[0] == "module":
                    self.mentioned.add(id(resolved[1]))

    # -- pass D: cycles, root

    def report_cycles(self) -> bool:
        """Report every instantiation cycle once per strongly connected
        component; True when any exists. Iterative Tarjan, so a long
        chain of modules cannot exhaust the interpreter's stack."""
        index, low, on_stack, stack = {}, {}, set(), []
        components = []
        counter = 0
        for start in self.defs:
            if id(start) in index:
                continue
            work = [(start, 0)]
            while work:
                node, position = work.pop()
                key = id(node)
                if position == 0:
                    index[key] = low[key] = counter
                    counter += 1
                    stack.append(node)
                    on_stack.add(key)
                if position < len(node.edges):
                    work.append((node, position + 1))
                    target = node.edges[position][1]
                    if id(target) not in index:
                        work.append((target, 0))
                    elif id(target) in on_stack:
                        low[key] = min(low[key], index[id(target)])
                    continue
                for _name, target, _span in node.edges:
                    if id(target) in on_stack:
                        low[key] = min(low[key], low[id(target)])
                if low[key] == index[key]:
                    component = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(id(member))
                        component.append(member)
                        if member is node:
                            break
                    components.append(component)
        cyclic = False
        for component in components:
            members = {id(d) for d in component}
            closing = [(defn.order, span.byte_start, span)
                       for defn in component
                       for _name, target, span in defn.edges
                       if id(target) in members]
            if not closing:
                continue
            cyclic = True
            closing.sort(key=lambda item: (item[0], item[1]))
            names = [d.name for d in sorted(component, key=lambda d: d.order)]
            self.report(
                "RHO2004", {"cycle": names}, closing[0][2],
                secondary=tuple((span, "also part of the cycle")
                                for _o, _b, span in closing[1:]))
        return cyclic

    def select_root(self, root: str | None) -> _Definition | None:
        entry = self.results[0]
        local = [d for d in self.defs
                 if d.result is entry and d.kind == "module"]
        names = [d.name for d in local]
        if root is not None:
            chosen = self.visible[entry.file].get(root)
            if chosen is None or chosen.kind != "module" \
                    or chosen.result is not entry:
                self.report("RHO2003", {"name": root, "candidates": names},
                            span_from_bytes(entry.file, entry.data, 0, 0))
                return None
            return chosen
        if not local:
            # A module dropped as a duplicate (RHO2001/RHO2034) is still
            # written; reporting "no module" for it would echo that error.
            if not any(_is_tree(node) and node.data == "module_def"
                       for node in entry.tree.children):
                self.report("RHO2047", {"file": entry.file},
                            span_from_bytes(entry.file, entry.data, 0, 0))
            return None
        targets = {id(target) for d in self.defs
                   for _n, target, _s in d.edges} | self.mentioned
        candidates = [d for d in local if id(d) not in targets]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            self.spare_roots = candidates  # judged by report_spare_roots
        return None

    def report_spare_roots(self) -> None:
        """RHO2002, once the bodies are checked. An unresolved single-word
        definition (RHO2005) is the likelier cause of a spare candidate:
        `new Divder` leaves Divider instantiated by nothing, and naming it
        as a possible root would send the author to the wrong line, so that
        defect is reported alone. Only a REPORTED one counts: a typo in a
        branch no instance takes draws no RHO2005, and suppressing RHO2002
        for it would leave the file failing with nothing said. Except that
        candidates are found in the text, taken branches or not, so a
        `new` whose one close match is a candidate is why that candidate
        is spare wherever it stands: it is reported here, and alone."""
        candidates = self.spare_roots
        if not candidates:
            return
        held = [self.static.values(),
                (model.findings for model in self.models.values())]
        if any(d.code == "RHO2005" for d in self.sink) or any(
                item[0] == "RHO2005" for buckets in held
                for bucket in buckets for item in bucket.items.values()):
            return
        spare = {id(d) for d in candidates}
        typos = []
        for defn, qualified in self.unresolved_news:
            file = defn.result.file
            name = _words(qualified)[0]
            match = _one_close(name, self.visible[file])
            if match is not None and name not in self.unbound.get(file, ()) \
                    and id(self.visible[file][match]) in spare:
                typos.append((defn, qualified))
        if typos:
            for defn, qualified in typos:
                self.unresolved(defn, qualified)
            return
        self.report(
            "RHO2002", {"candidates": [d.name for d in candidates]},
            candidates[1].header,
            secondary=tuple((d.header, "also instantiated by nothing")
                            for d in candidates[:1] + candidates[2:]))

    # -- pass E: what needs no parameter value, once per definition

    def check_static(self, defn: _Definition) -> None:
        """Names, types and placement over the WHOLE body, taken branches
        or not: none of it depends on a parameter's value, so it is
        checked once per definition. Each statement is visited with the
        loop variables in scope, the innermost enclosing `if`/`for`, and
        the nearest enclosing `for`."""
        params = {p.name: p.type for p in defn.params or ()}
        work = [(stmt, {}, None, None)
                for stmt in reversed(self.statements(defn))]
        while work:
            stmt, loops, inner, loop = work.pop()
            scope = dict(params, **loops)
            data = stmt.data
            if data == "port_decl" and inner is not None:
                defn.quiet_ports.add(str(_tokens(stmt, "FREE_NAME")[0]))
                self.misplace(defn, stmt, "a `port` declaration", inner,
                              "a definition's ports do not depend on its "
                              "parameters")
            elif data in ("instance_decl", "table_decl") and loop is not None:
                if data == "instance_decl":
                    defn.quiet_members.add(str(stmt.children[0]))
                else:
                    defn.quiet_members.update(
                        str(row.children[0])
                        for row in _trees(stmt, "table_row"))
                self.misplace(
                    defn, stmt,
                    "an instance declaration" if data == "instance_decl"
                    else "a table", loop,
                    "arrays, not loops, replicate instances")
            elif data == "assertion" and loop is not None:
                self.misplace(defn, stmt, "an assertion", loop,
                              "every iteration would declare the same "
                              "assertion path")
            elif data == "instance_decl":
                self.check_instance(defn, stmt, params)
            elif data == "table_decl":
                self.check_table(defn, stmt, params)
            elif data in ("net_decl", "chain", "isolated_decl"):
                for node in _trees(stmt, "endpoint") + _trees(
                        stmt, "chain_head"):
                    index = _tree(node, "index")
                    if index is not None:
                        # The base, then the offset of `i + 1`.
                        for token in index.children[::2]:
                            self.check_int(defn, index, token, scope,
                                           "an index")
            elif data in ("annotation", "waiver", "rule_override"):
                index = _tree(_tree(stmt, "target"), "index")
                if index is not None:
                    for token in index.children[::2]:
                        self.check_int(defn, index, token, scope,
                                       "an index")
                if data == "rule_override":
                    value = _rule_parts(_tree(stmt, "rule_body"))[4]
                    if value is not None:
                        self.check_value(defn, value, scope, None, None)
            elif data == "if_stmt":
                self.check_condition(defn, _tree(stmt, "condition"), scope)
                for block in reversed(_trees(stmt, "block")):
                    work += [(s, loops, "an `if` statement", loop)
                             for s in reversed(_block_statements(block))]
            elif data == "for_stmt":
                variable = _tokens(stmt, "FREE_NAME")[0]
                name = str(variable)
                shadowed = None
                if name in loops:
                    shadowed = "an enclosing loop variable"
                elif name in params:
                    shadowed = f"a parameter of `{defn.name}`"
                if shadowed is not None:
                    self.bad.add(id(stmt))
                    self.report("RHO2041", {"name": name,
                                            "shadowed": shadowed},
                                defn.result.span_of(variable))
                for bound in _trees(stmt, "bound_arg"):
                    self.check_int(defn, bound, bound.children[0], scope,
                                   "a `range` bound")
                inner_loops = dict(loops, **{name: "int"})
                for block in reversed(_trees(stmt, "block")):
                    work += [(s, inner_loops, "a `for` loop", "a `for` loop")
                             for s in reversed(_block_statements(block))]

    def misplace(self, defn, stmt, statement, construct, reason) -> None:
        self.misplaced.add(id(stmt))
        self.report("RHO2040", {"statement": statement,
                                "construct": construct, "reason": reason},
                    defn.result.span_of(stmt))

    def reference(self, defn, token, scope):
        """The declared type a FREE_NAME refers to, or None (reported)."""
        name = str(token)
        if name in scope:
            return scope[name]
        span = defn.result.span_of(token)
        self.report("RHO2039", {"name": name, "definition": defn.name},
                    span, fixits=_did_you_mean(name, scope, span))
        return None

    def check_int(self, defn, node, token, scope, context) -> None:
        """An index, `range` bound or array size: an INTEGER no larger than
        a value may be, or a name in scope whose type is int."""
        if token.type != "FREE_NAME":
            self.check_integer(defn, node, token)
            return
        found = self.reference(defn, token, scope)
        if found is None:
            self.bad.add(id(node))
        elif found != "int":
            self.mismatch(defn, token, found, context, "int")
            self.bad.add(id(node))

    def check_integer(self, defn, node, token) -> None:
        """E-7 bounds every integer literal, not only values: past 2^53 is
        RHO2017 wherever it is written, and `node` is not evaluated."""
        if token.type == "INTEGER" and _beyond_ir(str(token)):
            self.report("RHO2017", {"literal": str(token)},
                        defn.result.span_of(token))
            self.bad.add(id(node))

    def check_value(self, defn, node, scope, expected, context) -> None:
        """A `value`: a reference must name a parameter in scope, and with
        a declared `expected` type its type must match."""
        token = node.children[0]
        if token.type == "FREE_NAME":
            found = self.reference(defn, token, scope)
            if found is None:
                self.bad.add(id(node))
                return
        else:
            found = _literal_type(token)
        if expected is not None and not _assignable(found, expected):
            self.mismatch(defn, node, found, context, expected)

    def check_arguments(self, defn, target, pairs, instance, anchor,
                        params) -> None:
        """Arguments (or table columns) against a definition with a
        parameter list: `pairs` is [(name token, value node or None)]."""
        declared = {p.name: p for p in target.params}
        given = set()
        for token, value in pairs:
            name = str(token)
            if name not in declared:
                span = defn.result.span_of(token)
                self.bad.add(id(token))
                self.report(
                    "RHO2036",
                    {"name": name, "definition": target.spelled,
                     "parameters": [p.name for p in target.params]},
                    span, about=instance,
                    fixits=_did_you_mean(name, declared, span))
                continue
            given.add(name)
            if value is not None:
                self.check_value(
                    defn, value, params, declared[name].type,
                    f"parameter `{name}` of `{target.spelled}`")
        for param in target.params:
            if param.name not in given and not param.has_default:
                self.report(
                    "RHO2037",
                    {"instance": instance or anchor[1],
                     "parameter": param.name, "definition": target.spelled},
                    anchor[0], about=instance,
                    secondary=((param.span, "declared here"),))

    def check_instance(self, defn, stmt, params) -> None:
        result = defn.result
        name = str(stmt.children[0])
        size = _tree(stmt, "array_size")
        if size is not None:
            self.check_int(defn, size, size.children[0], params,
                           "an array size")
        qualified = _tree(stmt, "qualified_name")
        resolved = self.resolve(defn, qualified)
        target = resolved[1] if resolved is not None else None
        arguments = _tree(stmt, "arguments")
        nodes = _trees(arguments, "argument") if arguments else []
        if target is not None and target.params is not None:
            about = name if size is None else None
            self.check_arguments(
                defn, target,
                [(_tokens(a, "NAME")[0], _tree(a, "value")) for a in nodes],
                about, (result.span_of(qualified), name), params)
        else:
            for argument in nodes:
                self.check_value(defn, _tree(argument, "value"), params,
                                 None, None)
        body = _tree(stmt, "instance_body")
        for fact in (_unwrap(c) for c in body.children) if body else ():
            if fact.data == "part_decl":
                for constraint in _trees(fact, "constraint"):
                    self.check_value(defn, _tree(constraint, "value"),
                                     params, None, None)

    def check_table(self, defn, stmt, params) -> None:
        result = defn.result
        qualified = _tree(stmt, "qualified_name")
        resolved = self.resolve(defn, qualified)
        target = resolved[1] if resolved is not None else None
        column_list = _tree(stmt, "column_list")
        columns = _trees(column_list, "column") if column_list else []
        typed = target is not None and target.kind == "component" \
            and target.params is not None
        types = [None] * len(columns)
        if typed:
            plain = [(i, c) for i, c in enumerate(columns)
                     if len(c.children) == 1]
            self.check_arguments(
                defn, target, [(c.children[0], None) for _i, c in plain],
                None, (result.span_of(qualified), target.spelled), params)
            declared = {p.name: p.type for p in target.params}
            for i, column in plain:
                types[i] = declared.get(str(column.children[0]))
        for row in _trees(stmt, "table_row"):
            values = _trees(row, "value")
            for i, value in enumerate(values):
                expected = types[i] if len(values) == len(columns) else None
                context = None
                if expected is not None:
                    context = (f"parameter `{columns[i].children[0]}` of "
                               f"`{target.spelled}`")
                self.check_value(defn, value, params, expected, context)

    def check_condition(self, defn, cond, scope) -> None:
        name_token = cond.children[0]
        name = str(name_token)
        left = self.reference(defn, name_token, scope)
        if left is None:
            self.bad.add(id(cond))
            return
        compare = _tokens(cond, "COMPARE")
        if not compare:
            if left != "bool":
                self.mismatch(defn, name_token, left, "an `if` condition",
                              "bool")
                self.bad.add(id(cond))
            return
        op = str(compare[0])
        value = _tree(cond, "value")
        token = value.children[0]
        if left in ("string", "bool") and op not in _EQUALITY:
            self.report(
                "RHO2038",
                {"value": name, "found": _describe(left),
                 "context": f"`{op}`", "expected": "an int or a quantity"},
                defn.result.span_of(name_token))
            self.bad.add(id(cond))
            return
        if token.type == "FREE_NAME":
            right = self.reference(defn, token, scope)
            if right is None:
                self.bad.add(id(cond))
                return
        else:
            self.check_integer(defn, cond, token)
            if id(cond) in self.bad:
                return
            right = _literal_type(token)
            if token.type in ("QUANTITY", "QUANTITY_INTERVAL") \
                    and right == left \
                    and quantities.parse_quantity(str(token)).form != "exact":
                self.report(
                    "RHO2038",
                    {"value": str(token),
                     "found": _article(f"toleranced {left}"),
                     "context": f"a comparison with `{name}`",
                     "expected": _article(f"exact {left}")},
                    defn.result.span_of(token))
                self.bad.add(id(cond))
                return
        if right != left:
            self.mismatch(defn, value, right, f"a comparison with `{name}`",
                          left)
            self.bad.add(id(cond))

    # -- pass F: the walk, and each body under its environment

    def bind_values(self, target: _Definition, given: dict) -> _Env:
        """A definition's environment: each declared parameter's argument,
        else its default (a reference resolving to the earlier parameter's
        value), else UNKNOWN (reported where the argument is missing)."""
        values = {}
        for param in target.params:
            if param.name in given:
                value = given[param.name]
            elif param.default_ref is not None:
                value = values.get(param.default_ref, UNKNOWN)
            elif param.has_default:
                value = param.default_value
            else:
                value = UNKNOWN
            values[param.name] = value
        return _Env(tuple(values.items()))

    def bind_defaults(self, defn: _Definition) -> _Env:
        if defn.params is None:
            return EMPTY_ENV
        return self.bind_values(defn, {})

    def root_env(self, root_def: _Definition) -> _Env:
        for param in root_def.params or ():
            if not param.has_default:
                self.report(
                    "RHO2037",
                    {"instance": "/", "parameter": param.name,
                     "definition": root_def.name},
                    param.span, entity="/")
        return self.bind_defaults(root_def)

    def walk(self, root_def: _Definition):
        """Build the instance tree from the root, evaluating each module
        body once per distinct (definition, environment). Returns
        (instances, visits), or None when the design's replication budget
        is exhausted (reported)."""
        env = self.root_env(root_def)
        parameters = dict(env.values) if root_def.params is not None else {}
        instances = [Instance(
            path="/", kind="module", definition=root_def.definition,
            parameters=parameters, ports=tuple(root_def.ports), dnp=False,
            exclude_from_bom=False, board_only=False, hardware_kind=None,
            part=None, declaration=root_def.header, trace=())]
        visits = []
        total = 0
        work = [(root_def, env, "/", 0, (), dict.fromkeys(FLAGS, False))]
        while work:
            defn, env, path, depth, trace, inherited = work.pop()
            model = self.model(defn, env)
            model.paths.append(path)
            defn.paths.append(path)
            if total + model.units > EXPANSION_LIMIT:
                self.over_limit(model, total)
                return None
            total += model.units
            for member in model.members.values():
                if member.broken:
                    continue
                ipath = child_path(path, member.name)
                flags = {flag: member.flags.get(flag, False)
                         or inherited[flag] for flag in FLAGS}
                itrace = (member.span,) + trace
                self.elaborated.add(ipath)
                instances.append(Instance(
                    path=ipath, kind=member.kind,
                    definition=member.definition,
                    parameters=dict(member.parameters),
                    ports=tuple(member.ports),
                    hardware_kind=member.hardware_kind, part=member.part,
                    declaration=member.span, trace=itrace,
                    rules=self.member_rules(member, model), **flags))
                if member.kind == "module":
                    work.append((member.target, member.env, ipath,
                                 depth + 1, itrace, flags))
            visits.append((model, path, depth, trace))
        return instances, visits

    @staticmethod
    def member_rules(member: _Member, model: _Model) -> tuple:
        """A component member's rules (syntax 0.3): its definition's, each
        reference evaluated in the member's own environment; or, when the
        module's `rule` statements name it, those instead, with the
        definition's sides kept (a side is what the part is, not how it is
        used)."""
        if member.kind != "component":
            return ()
        definition = member.target.rules if member.target is not None \
            else []
        overrides = model.overrides.get(member.name)
        rules = []
        for rule in definition:
            if overrides is not None and rule.word != "side":
                continue
            value = rule.value
            if isinstance(value, tuple):  # ("reference", name)
                value = member.parameters.get(value[1], UNKNOWN)
            rules.append(replace(rule, value=value))
        return tuple(rules + list(overrides or ()))

    def over_limit(self, model: _Model, total: int) -> None:
        """The design crossed its replication budget inside `model`'s
        expansion: report once, at the statement that crossed it."""
        if self.limit_reported:
            return
        self.limit_reported = True
        running = total
        for span, units, construct in model.sites:
            running += units
            if running > EXPANSION_LIMIT:
                self.report("RHO2046", {"construct": construct,
                                        "limit": EXPANSION_LIMIT}, span)
                return

    def spend(self, model: _Model, span: Span, count: int,
              construct: str) -> bool:
        """Charge `count` replicated units to the body being evaluated;
        False when that alone passes the design's budget. Reported once
        per design, like over_limit: after the first crossing every later
        charge also fails, and blaming it would name statements (an array
        charged after the loops that spent the budget) that are not why.
        Straight to the sink, not into the body's findings: those are
        published once per instance path when other environments of the
        module do not show them, and the design draws one RHO2046 however
        many instances share the body that crossed."""
        if count <= 0:
            return True
        if model.units + count > EXPANSION_LIMIT:
            if not self.limit_reported:
                self.limit_reported = True
                self.sink.add("RHO2046", {"construct": construct,
                                          "limit": EXPANSION_LIMIT},
                              primary=span, entity=None)
            return False
        model.units += count
        model.sites.append((span, count, construct))
        return True

    def model(self, defn: _Definition, env: _Env) -> _Model:
        key = (id(defn), env.key)
        model = self.models.get(key)
        if model is None:
            model = _Model(env)
            self.models[key] = model
            self.model_order.setdefault(id(defn), []).append(model)
            saved = self.bucket, self.current_env
            self.bucket, self.current_env = model.findings, env
            try:
                self.check_body(defn, model)
            finally:
                self.bucket, self.current_env = saved
        return model

    def lookup(self, model: _Model, name: str, loops: dict):
        if name in loops:
            return loops[name]
        return model.env.get(name, UNKNOWN)

    def integer(self, model, node, loops):
        """An index base, bound or size as an int, or None (an error was
        reported for it already)."""
        if id(node) in self.bad:
            return None
        token = node.children[0]
        if token.type == "INTEGER":
            return int(str(token))
        value = self.lookup(model, str(token), loops)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    def literal(self, token):
        """A condition's literal operand, silently (pass E checked it)."""
        text = str(token)
        if token.type == "STRING":
            return text[1:-1]
        if text in ("true", "false"):
            return text == "true"
        if token.type == "INTEGER":
            return int(text)
        parsed = quantities.parse_quantity(text)
        if parsed.nominal is None:
            return UNKNOWN
        unit, multiplier = _unit_for(parsed.nominal, parsed.dimension)
        return Quantity(_in_unit(parsed.nominal, multiplier), unit)

    def decide(self, model, stmt, loops):
        """Which branch an `if` takes: True, False, or None when its
        condition cannot be evaluated (already reported)."""
        cond = _tree(stmt, "condition")
        if id(cond) in self.bad:
            return None
        left = self.lookup(model, str(cond.children[0]), loops)
        compare = _tokens(cond, "COMPARE")
        if not compare:
            return left if isinstance(left, bool) else None
        token = _tree(cond, "value").children[0]
        right = self.lookup(model, str(token), loops) \
            if token.type == "FREE_NAME" else self.literal(token)
        return _compare(str(compare[0]), left, right)

    def loop_range(self, defn, model, stmt, loops):
        if id(stmt) in self.bad:
            return None
        bounds = [self.integer(model, b, loops)
                  for b in _trees(stmt, "bound_arg")]
        if any(b is None for b in bounds):
            return None
        low, high = (0, bounds[0]) if len(bounds) == 1 else bounds
        result = defn.result
        last = _trees(stmt, "bound_arg")[-1]
        span = _span_through(
            result, result.span_of(stmt.children[0]).byte_start,
            result.span_of(last).byte_end, b")")
        if not self.spend(model, span, high - low, "a `for` loop"):
            return None
        return low, high

    def quieten(self, model, blocks) -> None:
        """Names declared in a region not evaluated because of an error:
        endpoints naming them stay quiet rather than echo that error."""
        work = list(blocks)
        while work:
            node = work.pop()
            if not _is_tree(node):
                continue
            if node.data == "instance_decl":
                model.quiet.add(str(node.children[0]))
            elif node.data == "table_row":
                model.quiet.add(str(node.children[0]))
            else:
                work += node.children

    def expand(self, defn: _Definition, model: _Model) -> list:
        """The live statements of the body, in source order, each with its
        loop variables: `if` takes one branch, `for` unrolls. Iterative,
        so nesting depth costs no interpreter stack."""
        def each(statements, loops):
            for stmt in statements:
                yield stmt, loops

        def unroll(statements, name, low, high, loops):
            for value in range(low, high):
                inner = dict(loops)
                inner[name] = value
                for stmt in statements:
                    yield stmt, inner

        live = []
        stack = [each(self.statements(defn), {})]
        while stack:
            pair = next(stack[-1], None)
            if pair is None:
                stack.pop()
                continue
            stmt, loops = pair
            if id(stmt) in self.misplaced:
                continue
            if stmt.data == "if_stmt":
                blocks = _trees(stmt, "block")
                choice = self.decide(model, stmt, loops)
                if choice is None:
                    self.quieten(model, blocks)
                elif choice:
                    stack.append(each(_block_statements(blocks[0]), loops))
                elif len(blocks) > 1:
                    stack.append(each(_block_statements(blocks[1]), loops))
            elif stmt.data == "for_stmt":
                block = _tree(stmt, "block")
                bounds = self.loop_range(defn, model, stmt, loops)
                if bounds is None:
                    self.quieten(model, [block])
                    continue
                name = str(_tokens(stmt, "FREE_NAME")[0])
                stack.append(unroll(_block_statements(block), name,
                                    bounds[0], bounds[1], loops))
            else:
                live.append((stmt, loops))
        return live

    def check_body(self, defn: _Definition, model: _Model) -> None:
        live = self.expand(defn, model)
        first_seen: dict[str, Span] = {}
        for stmt, _loops in live:
            if stmt.data == "instance_decl":
                self.instance(defn, model, stmt, first_seen)
            elif stmt.data == "table_decl":
                self.table(defn, model, stmt, first_seen)
        for stmt, loops in live:
            if stmt.data in ("net_decl", "chain", "isolated_decl"):
                self.connect(defn, model, stmt, loops)
        names: dict[str, Span] = {}
        for stmt, _loops in live:
            if stmt.data == "assertion":
                self.assertion(defn, model, stmt, names)
        stated: dict = {}
        for stmt, loops in live:
            if stmt.data == "rule_override":
                self.rule_override(defn, model, stmt, loops)
            elif stmt.data in ("annotation", "waiver"):
                self.annotation(defn, model, stmt, loops, stated, names)

    def declare(self, defn, model, name, span, first_seen) -> bool:
        """Claim a member name in the module; False (reported) if taken."""
        if name in first_seen:
            self.report(
                "RHO2007",
                {"kind": "instance", "name": name,
                 "scope": f"module `{defn.name}`"},
                span, about=None if name in model.arrays else name,
                secondary=((first_seen[name], "first declared here"),))
            return False
        first_seen[name] = span
        return True

    def array_size(self, defn, model, node, name, qualified):
        result = defn.result
        size = self.integer(model, node, {})
        if size is None:
            return None
        span = span_from_bytes(result.file, result.data,
                               result.span_of(qualified).byte_start,
                               result.span_of(node).byte_end)
        if size < 1:
            self.report("RHO2042", {"array": name, "size": size}, span)
            return None
        if not self.spend(model, span, size, "an array"):
            return None
        return size

    def instance(self, defn, model, stmt, first_seen) -> None:
        result = defn.result
        name = str(stmt.children[0])
        span = result.span_of(stmt)
        if not self.declare(defn, model, name, span, first_seen):
            return
        qualified = _tree(stmt, "qualified_name")
        size_node = _tree(stmt, "array_size")
        size = None
        if size_node is not None:
            size = self.array_size(defn, model, size_node, name, qualified)
            if size is None:
                model.arrays[name] = None
                return
        about = name if size is None else None
        resolved = self.resolve(defn, qualified)
        if resolved is None:
            self.unresolved(defn, qualified)
            if size is None:
                model.members[name] = _Member(
                    name, "component", ".".join(_words(qualified)), None,
                    {}, {}, span=span, broken=True)
            else:
                model.arrays[name] = None
            return
        kind, target, definition = resolved
        parameters, env = self.bind(defn, model, target,
                                    _tree(stmt, "arguments"), name)
        body = _tree(stmt, "instance_body")
        facts = [_unwrap(c) for c in body.children] if body is not None \
            else []
        if kind == "module":
            member = _Member(name, kind, definition, target, parameters,
                             dict(target.roles), tuple(target.ports),
                             span=span, env=env)
            self.module_facts(defn, member, facts, about)
        else:
            member = _Member(name, kind, definition, target, parameters,
                             {}, span=span)
            self.component_facts(defn, member, facts, about, qualified)
        if size is None:
            model.members[name] = member
            return
        model.arrays[name] = size
        for index in range(size):
            segment = f"{name}[{index}]"
            model.members[segment] = replace(member, name=segment)

    def bind(self, defn, model, target, node, instance):
        """(IR parameters, environment) for an instantiation. With a
        parameter list the parameters are the definition's whole
        environment; without one, the arguments as given (v0.1)."""
        given = self.arguments(defn, model, node, instance)
        if target is None or target.params is None:
            return given, EMPTY_ENV
        declared = {param.name for param in target.params}
        env = self.bind_values(
            target, {k: v for k, v in given.items() if k in declared})
        return dict(env.values), env

    def flags(self, defn, member, facts, about) -> dict:
        """The flags an instance body states, warning on repeats; returns
        {flag: span} and {flag: span} for the `no` forms."""
        stated, denied = {}, {}
        for fact in facts:
            if fact.data == "flag":
                word, table, shown = str(fact.children[0]), stated, None
            elif fact.data == "negated_flag":
                word, table = str(fact.children[1]), denied
                shown = f"no {word}"
            else:
                continue
            span = defn.result.span_of(fact)
            if word in table:
                self.report("RHO2011",
                            {"flag": shown or word, "instance": member.name},
                            span, about=about)
                continue
            table[word] = span
        return stated, denied

    def module_facts(self, defn, member, facts, about) -> None:
        stated, denied = self.flags(defn, member, facts, about)
        for fact in facts:
            if fact.data in ("pin_decl", "part_decl", "hardware_decl"):
                word = fact.data.split("_")[0]
            elif fact.data == "negated_flag":
                word = f"no {fact.children[1]}"
            else:
                continue
            self.report(
                "RHO2009",
                {"fact": word, "instance": member.name,
                 "module": member.target.name},
                defn.result.span_of(fact), about=about)
        member.flags = {flag: True for flag in stated}

    def component_facts(self, defn, member, facts, about, qualified) -> None:
        result = defn.result
        ports, pin_spans = [], {}
        hardware = hardware_span = None
        part_seen = False
        for fact in facts:
            span = result.span_of(fact)
            if fact.data == "pin_decl":
                pin, role = (str(t) for t in _tokens(fact, "NAME")[:2])
                if pin in pin_spans:
                    self.report(
                        "RHO2007",
                        {"kind": "pin", "name": pin,
                         "scope": f"instance `{member.name}`"},
                        span, about=about,
                        secondary=((pin_spans[pin], "first declared here"),))
                    continue
                pin_spans[pin] = span
                designators = []
                for designator in _trees(fact, "designator"):
                    text = _designator(designator)
                    if text in designators:
                        self.report(
                            "RHO2007",
                            {"kind": "designator", "name": text,
                             "scope": f"pin `{pin}` of instance "
                                      f"`{member.name}`"},
                            result.span_of(designator), about=about)
                        continue
                    designators.append(text)
                ports.append(Port(pin, role, tuple(sorted(designators)),
                                  declaration=span))
            elif fact.data == "part_decl":
                if part_seen:
                    self.report("RHO2010",
                                {"fact": "part", "instance": member.name},
                                span, about=about)
                    continue
                part_seen = True
                member.part = self.part(defn, member.name, fact, span, about)
            elif fact.data == "hardware_decl":
                if hardware is not None:
                    self.report("RHO2010",
                                {"fact": "hardware", "instance": member.name},
                                span, about=about)
                    continue
                hardware = str(_tokens(fact, "NAME")[0])
                hardware_span = span
        stated, denied = self.flags(defn, member, facts, about)
        for flag in sorted(set(stated) & set(denied)):
            later = max(stated[flag], denied[flag],
                        key=lambda s: s.byte_start)
            self.report("RHO2012", {"flag": flag, "instance": member.name},
                        later, about=about)
        if member.target is not None:
            # A component definition: its pins are the ports. Pins the
            # instance states anyway must restate them exactly.
            if ports:
                self.agree(defn, member, ports, pin_spans, qualified, about)
            ports = list(member.target.ports)
        member.flags = {flag: True for flag in stated}
        member.ports = tuple(ports)
        member.roles = {port.name: port.role for port in ports}
        member.hardware_kind = hardware
        if hardware is not None:
            self.hardware_arity(member, hardware, hardware_span, about)

    def agree(self, defn, member, ports, pin_spans, qualified, about) -> None:
        target = member.target

        def spell(port):
            words = ["pin", port.name, port.role, *port.pin_numbers]
            return "`" + " ".join(words) + "`"

        defined = {port.name: port for port in target.ports}
        stated = {port.name for port in ports}
        for port in ports:
            want = defined.get(port.name)
            if want == port:
                continue
            secondary = ()
            if want is not None:
                secondary = ((target.pin_spans[port.name], "defined here"),)
            self.report(
                "RHO2035",
                {"instance": member.name, "pin": port.name,
                 "component": target.spelled, "found": spell(port),
                 "expected": spell(want) if want else "no such pin"},
                pin_spans[port.name], about=about, secondary=secondary)
        for port in target.ports:
            if port.name in stated:
                continue
            self.report(
                "RHO2035",
                {"instance": member.name, "pin": port.name,
                 "component": target.spelled, "found": "no such pin",
                 "expected": spell(port)},
                defn.result.span_of(qualified), about=about,
                secondary=((target.pin_spans[port.name], "defined here"),))

    def hardware_arity(self, member, hardware, span, about) -> None:
        ports = member.ports
        if hardware in PINLESS_HARDWARE and ports:
            requirement, found = "no pins", f"{len(ports)} pin(s)"
        elif hardware in SINGLE_PIN_HARDWARE and not (
                len(ports) == 1 and ports[0].role == "passive"):
            requirement = "exactly one passive pin"
            if not ports:
                found = "no pins"
            elif len(ports) > 1:
                found = f"{len(ports)} pins"
            else:
                found = f"one `{ports[0].role}` pin"
        else:
            return
        self.report(
            "RHO2013",
            {"instance": member.name, "kind": hardware,
             "requirement": requirement, "found": found},
            span, about=about)

    def part(self, defn, instance, fact, span, about) -> Part:
        binding = fact.children[1]
        statements = _trees(fact, "constraint")
        constraints = self.pairs(defn, statements, "constraint",
                                 f"instance `{instance}`",
                                 self.current_env)
        sites = self.constraint_sites(
            defn, [(str(_tokens(s, "NAME")[0]), _tree(s, "value"))
                   for s in statements], constraints)
        if getattr(binding, "type", None) == "STRING":
            key = str(binding)[1:-1]
            if not key:
                self.report("RHO2015", {"instance": instance}, span,
                            about=about)
            return Part("resolved", key, constraints, sites)
        if not statements:
            self.report("RHO2014", {"instance": instance}, span,
                        about=about)
        return Part("abstract", None, constraints, sites)

    @staticmethod
    def constraint_sites(defn, pairs, values) -> dict:
        """How each constraint of `values` was written, from its (name,
        value node) pairs; the first pair naming it wins, as it does for
        the value."""
        sites = {}
        for name, node in pairs:
            if name in sites or name not in values:
                continue
            token = node.children[0]
            if token.type == "FREE_NAME":
                origin, form = "reference", _value_form(values[name])
            else:
                origin, form = "literal", _literal_form(token)
            sites[name] = ConstraintSite(form, origin,
                                         defn.result.span_of(node))
        return sites

    # -- values

    def arguments(self, defn, model, node, instance) -> dict:
        if node is None:
            return {}
        return self.pairs(defn, _trees(node, "argument"), "argument",
                          f"instance `{instance}`", model.env)

    def pairs(self, defn, statements, kind, scope, env) -> dict:
        """`name = value` statements to a dict, refusing repeats."""
        out, spans = {}, {}
        for stmt in statements:
            name = str(_tokens(stmt, "NAME")[0])
            span = defn.result.span_of(stmt)
            if name in spans:
                self.report(
                    "RHO2007", {"kind": kind, "name": name, "scope": scope},
                    span, secondary=((spans[name], "first given here"),))
                continue
            spans[name] = span
            out[name] = self.value(defn, _tree(stmt, "value"), name, env)
        return out

    def value(self, defn, node, name, env):
        """One `value` tree to its elaborated value, or UNKNOWN (reported).
        The single evaluation point: a parameter reference resolves in
        `env`, the instantiating definition's environment."""
        if id(node) in self.bad:
            return UNKNOWN
        token = node.children[0]
        text = str(token)
        span = defn.result.span_of(token)
        if token.type == "FREE_NAME":
            return env.get(text, UNKNOWN)
        if token.type == "STRING":
            return text[1:-1]
        if text in ("true", "false"):
            return text == "true"
        if token.type == "INTEGER":
            if _beyond_ir(text):
                self.report("RHO2017", {"literal": text}, span)
                return UNKNOWN
            return int(text)
        parsed = quantities.parse_quantity(text)
        if parsed.nominal is None:
            self.report("RHO2016", {"literal": text, "name": name}, span)
            return UNKNOWN
        unit, multiplier = _unit_for(parsed.nominal, parsed.dimension)
        tolerance = None
        if parsed.form != "exact":
            tolerance = (_in_unit(parsed.lower, multiplier),
                         _in_unit(parsed.upper, multiplier))
        quantity = Quantity(_in_unit(parsed.nominal, multiplier), unit,
                            tolerance)
        if not _representable(quantity.value, *(tolerance or ())):
            self.report("RHO2017", {"literal": text}, span)
            return UNKNOWN
        return quantity

    # -- tables

    def table(self, defn, model, stmt, first_seen) -> None:
        result = defn.result
        qualified = _tree(stmt, "qualified_name")
        qname = ".".join(_words(qualified))
        resolved = self.resolve(defn, qualified)
        broken = False
        target = None
        definition = qname
        if resolved is None:
            self.unresolved(defn, qualified)
            broken = True
        elif resolved[0] == "module":
            self.report("RHO2006", {"name": qname},
                        result.span_of(qualified))
            broken = True
        else:
            target, definition = resolved[1], resolved[2]
        typed = target is not None and target.params is not None
        binding = _tree(stmt, "table_binding")
        column_list = _tree(stmt, "column_list")
        columns = _trees(column_list, "column") if column_list else []
        last = column_list or binding or qualified
        header = _span_through(result, result.span_of(stmt.children[0])
                               .byte_start, result.span_of(last).byte_end,
                               b")")
        plan, seen = [], {}
        for column in columns:
            words = _words(column)
            text = ".".join(words)
            cspan = result.span_of(column)
            if len(words) == 1:
                slot = ("parameter", words[0])
            elif words[0] == "part":
                slot = ("constraint", words[1])
                if binding is None:
                    self.report("RHO2020", {"column": text}, cspan)
            else:
                self.report("RHO2019", {"column": text}, cspan)
                plan.append(None)
                continue
            if slot in seen:
                self.report(
                    "RHO2007",
                    {"kind": "column", "name": text,
                     "scope": f"table `{qname}`"},
                    cspan, secondary=((seen[slot], "first given here"),))
                plan.append(None)
                continue
            seen[slot] = cspan
            if slot[0] == "parameter" and id(column.children[0]) in self.bad:
                plan.append(None)  # not a parameter of the definition
                continue
            plan.append(slot)
        key = None
        if binding is not None:
            bspan = result.span_of(binding)
            if getattr(binding.children[1], "type", None) == "STRING":
                key = str(binding.children[1])[1:-1]
                if not key:
                    self.report("RHO2015", {"instance": qname}, bspan)
            elif not any(s and s[0] == "constraint" for s in plan):
                self.report("RHO2014", {"instance": qname}, bspan)
        ports = tuple(target.ports) if target is not None else ()
        for row in _trees(stmt, "table_row"):
            name = str(row.children[0])
            span = result.span_of(row)
            if not self.declare(defn, model, name, span, first_seen):
                continue
            values = _trees(row, "value")
            member = _Member(name, "component", definition, target, {},
                             {port.name: port.role for port in ports},
                             ports, span=span, broken=broken)
            model.members[name] = member
            if len(values) != len(columns):
                self.report(
                    "RHO2018",
                    {"row": name, "values": len(values),
                     "columns": len(columns)},
                    header, about=name,
                    secondary=((span, "this row"),))
                member.broken = True
                continue
            given, constraints, written = {}, {}, []
            for slot, node in zip(plan, values):
                if slot is None:
                    continue
                value = self.value(defn, node, slot[1], model.env)
                if value is UNKNOWN and not typed:
                    continue
                target_dict = given if slot[0] == "parameter" \
                    else constraints
                target_dict[slot[1]] = value
                if slot[0] == "constraint":
                    written.append((slot[1], node))
            member.parameters = dict(self.bind_values(target, given).values) \
                if typed else given
            if binding is not None:
                member.part = Part(
                    "resolved" if key is not None else "abstract", key,
                    constraints,
                    self.constraint_sites(defn, written, constraints))

    # -- connections

    def endpoint(self, defn, model, node, loops):
        """Resolve one endpoint, or None (reported, or quiet when it names
        something that already failed to resolve)."""
        result = defn.result
        tokens = [c for c in node.children if not _is_tree(c)]
        index = _tree(node, "index")
        span = result.span_of(node)
        head = str(tokens[0])
        written_head = head
        if index is not None:
            written_head = head + _text_of(result, index)
        if len(tokens) == 1:
            if index is not None:
                self.report("RHO2023", {"name": written_head,
                                        "module": defn.name}, span)
                return None
            role = defn.roles.get(head)
            if role is None:
                if head in defn.quiet_ports:
                    return None
                self.report("RHO2023", {"name": head, "module": defn.name},
                            span, fixits=_did_you_mean(head, defn.roles,
                                                       span))
                return None
            if role == "nc":
                self.report("RHO2024", {"endpoint": head}, span)
                return None
            return _Endpoint(None, head, head, span, head)
        port = str(tokens[1])
        written = f"{written_head}.{port}"
        hspan = result.span_of(tokens[0])
        quiet = head in model.quiet or head in defn.quiet_members
        if index is None:
            if head in model.arrays:
                size = model.arrays[head]
                if size is not None:
                    self.report("RHO2044", {"array": head, "size": size},
                                hspan)
                return None
            owner = head
        else:
            if head in model.members:
                if model.members[head].broken:
                    return None
                self.report("RHO2045", {"instance": head},
                            span_from_bytes(result.file, result.data,
                                            hspan.byte_start,
                                            result.span_of(index).byte_end),
                            about=head)
                return None
            if head not in model.arrays:
                if not quiet:
                    self.report("RHO2021",
                                {"instance": head, "module": defn.name},
                                hspan, fixits=_did_you_mean(
                                    head, self.member_names(model), hspan))
                return None
            size = model.arrays[head]
            position = self.position(model, index, loops)
            if size is None or position is None:
                return None
            if not 0 <= position < size:
                self.report(
                    "RHO2043",
                    {"endpoint": f"{head}[{position}].{port}",
                     "index": position, "array": head, "last": size - 1},
                    span)
                return None
            owner = f"{head}[{position}]"
        member = model.members.get(owner)
        if member is None:
            if not quiet:
                self.report("RHO2021", {"instance": owner,
                                        "module": defn.name},
                            hspan, fixits=_did_you_mean(
                                owner, self.member_names(model), hspan))
            return None
        if member.broken:
            return None
        text = f"{owner}.{port}"
        role = member.roles.get(port)
        if role is None:
            pspan = result.span_of(tokens[1])
            self.report(
                "RHO2022",
                {"instance": written_head, "definition": member.definition,
                 "port": port},
                pspan, about=owner,
                fixits=_did_you_mean(port, member.roles, pspan))
            return None
        if role == "nc":
            self.report("RHO2024", {"endpoint": written}, span, about=owner)
            return None
        return _Endpoint(owner, port, text, span, written)

    @staticmethod
    def member_names(model) -> list:
        return [name for name in model.members if "[" not in name] \
            + list(model.arrays)

    def position(self, model, index, loops):
        """An index expression's value: NAME, INTEGER, or either plus or
        minus an INTEGER. None when it cannot be evaluated (reported)."""
        base = self.integer(model, index, loops)
        if base is None:
            return None
        tokens = [c for c in index.children if not _is_tree(c)]
        if len(tokens) == 3:
            offset = int(str(tokens[2]))
            base = base + offset if str(tokens[1]) == "+" else base - offset
        return base

    def connect(self, defn, model, stmt, loops) -> None:
        result = defn.result
        span = result.span_of(stmt)
        label, attributes, attribute_spans = None, {}, {}
        if stmt.data == "net_decl":
            kind, nodes = "net", _trees(stmt, "endpoint")
            label = str(_tokens(stmt, "FREE_NAME")[0])
            if label in model.labels and model.labels[label].node \
                    is not stmt:
                self.report(
                    "RHO2007",
                    {"kind": "net", "name": label,
                     "scope": f"module `{defn.name}`"},
                    span, secondary=((model.labels[label].span,
                                      "first labelled here"),))
                label = None
            attributes, attribute_spans = self.net_attributes(
                defn, stmt, label)
        elif stmt.data == "chain":
            kind = "chain"
            nodes = _trees(stmt, "chain_head") + _trees(stmt, "endpoint")
        else:
            kind, nodes = "isolated", _trees(stmt, "endpoint")
        endpoints, seen = [], set()
        for node in nodes:
            endpoint = self.endpoint(defn, model, node, loops)
            if endpoint is None:
                continue
            key = (endpoint.member, endpoint.port)
            if key in seen:
                self.report("RHO2025", {"endpoint": endpoint.written},
                            endpoint.span)
                continue
            seen.add(key)
            endpoints.append(endpoint)
        connect = _Connect(kind, endpoints, span, label, attributes, stmt,
                           attribute_spans)
        model.connects.append(connect)
        if label is not None and label not in model.labels:
            model.labels[label] = connect

    def net_attributes(self, defn, stmt, label) -> tuple[dict, dict]:
        """({attribute: value}, {attribute: its span}) of a net block."""
        node = _tree(stmt, "net_attributes")
        if node is None:
            return {}, {}
        out, spans = {}, {}
        shown = label or str(_tokens(stmt, "FREE_NAME")[0])
        for attribute in _trees(node, "net_attribute"):
            key = str(_tokens(attribute, "NAME")[0])
            text = str(_tokens(attribute, "STRING")[0])[1:-1]
            span = defn.result.span_of(attribute)
            if key in spans:
                self.report(
                    "RHO2007",
                    {"kind": "net attribute", "name": key,
                     "scope": f"net `{shown}`"},
                    span, secondary=((spans[key], "first given here"),))
                continue
            spans[key] = span
            if not text:
                self.report("RHO2032", {"net": shown, "attribute": key},
                            span)
                continue
            out[key] = text
        return out, {key: spans[key] for key in out}

    # -- assertions

    def assertion(self, defn, model, stmt, names) -> None:
        result = defn.result
        words = [c for c in stmt.children if not _is_tree(c)]
        name, tier = str(words[1]), str(words[2])
        measurement, subject = str(words[3]), str(words[4])
        span = result.span_of(stmt)
        if name in names:
            self.report(
                "RHO2007",
                {"kind": "assertion", "name": name,
                 "scope": f"module `{defn.name}`"},
                span, about=name,
                secondary=((names[name], "first declared here"),))
            return
        names[name] = span
        if name in model.members:
            self.report("RHO2008", {"name": name, "module": defn.name},
                        span, secondary=((model.members[name].span,
                                          "the instance"),))
        if tier == "static" and measurement not in STATIC_MEASUREMENTS:
            self.report("RHO2030", {"name": name, "measurement": measurement},
                        result.span_of(words[3]), about=name)
        if subject not in model.labels:
            sspan = result.span_of(words[4])
            self.report("RHO2029", {"subject": subject, "module": defn.name},
                        sspan, about=name,
                        fixits=_did_you_mean(subject, model.labels, sspan))
        bound = _tree(stmt, "bound")
        bounds = self.bounds(defn, bound)
        severity = "warning" if _tokens(stmt, "WARNING") else "error"
        model.checks.append(
            _Check(name, tier, measurement, subject, bounds, span,
                   result.span_of(bound), severity))

    def bounds(self, defn, node) -> Bounds | None:
        result = defn.result
        parts = node.children
        keyword = str(parts[0])
        if keyword == "within" and len(parts) == 2:
            parsed = quantities.parse_quantity(str(parts[1]))
            widest = max(parsed.lower, parsed.upper,
                         key=lambda v: (abs(v), v))
            unit, multiplier = _unit_for(widest, parsed.dimension)
            low = _in_unit(parsed.lower, multiplier)
            high = _in_unit(parsed.upper, multiplier)
            literal = parts[1]
        elif keyword == "within":
            unit = "1"
            low, high = Decimal(str(parts[1])), Decimal(str(parts[3]))
            literal = parts[1]
            if low > high:
                self.report("RHO2031",
                            {"low": str(parts[1]), "high": str(parts[3])},
                            result.span_of(node))
        else:
            token = parts[2]
            if token.type == "QUANTITY_PLAIN":
                parsed = quantities.parse_quantity(str(token))
                unit, multiplier = _unit_for(parsed.nominal,
                                             parsed.dimension)
                number = _in_unit(parsed.nominal, multiplier)
            else:
                unit, number = "1", Decimal(str(token))
            low, high = (number, None) if str(parts[1]) == "least" \
                else (None, number)
            literal = token
        present = [v for v in (low, high) if v is not None]
        if not _representable(*present):
            self.report("RHO2017", {"literal": str(literal)},
                        result.span_of(literal))
            return None
        return Bounds(unit, low, high)

    # -- syntax 0.3: annotations, waivers and rule overrides

    def target(self, defn, model, statement, node, loops, accepts,
               assertions=()):
        """What a 0.3 statement's target names in this body, as one of
        `accepts`: ("label", label), ("pin", member, port), ("member",
        member), or ("assertion", name). "component" accepts a member that
        is a component instance. None when it names nothing that kind of
        statement takes (RHO2080), or names something whose own defect was
        already reported (quiet, so one defect is one diagnostic)."""
        result = defn.result
        tokens = [c for c in node.children if not _is_tree(c)]
        head = str(tokens[0])
        index = _tree(node, "index")
        port = str(tokens[1]) if len(tokens) > 1 else None
        written = head + ("" if index is None else _text_of(result, index))
        span = result.span_of(node)

        def refuse(reason, shown=None):
            shown = written if shown is None else shown
            if port is not None:
                shown += f".{port}"
            self.report("RHO2080", {"statement": statement, "target": shown,
                                    "module": defn.name, "reason": reason},
                        span)
            return None

        quiet = head in model.quiet or head in defn.quiet_members
        owner = head
        if index is not None:
            if id(index) in self.bad:
                return None
            if head not in model.arrays:
                if quiet or (head in model.members
                             and model.members[head].broken):
                    return None
                return refuse(f"`{head}` is not an array")
            size = model.arrays[head]
            position = self.position(model, index, loops)
            if size is None or position is None:
                return None
            owner = f"{head}[{position}]"
            if not 0 <= position < size:
                return refuse(f"`{head}` has members 0 to {size - 1}", owner)
        elif head in model.arrays and (port is not None
                                       or "label" not in accepts
                                       or head not in model.labels):
            if model.arrays[head] is None:
                return None
            return refuse(f"`{head}` is an array; name one member, "
                          f"`{head}[0]`")
        member = model.members.get(owner)
        if port is not None:
            if "pin" not in accepts:
                return refuse("a pin is not a target this statement takes")
            if member is None:
                return None if quiet else refuse(
                    f"module `{defn.name}` has no instance `{owner}`")
            if member.broken:
                return None
            if port not in member.roles:
                return refuse(f"`{owner}` has no port `{port}`")
            return ("pin", owner, port)
        found = []
        if member is not None and accepts != ("label", "pin"):
            found.append(("member", "an instance"))
        if index is None and head in model.labels and "label" in accepts:
            found.append(("label", "a net label"))
        if index is None and head in assertions \
                and "assertion" in accepts:
            found.append(("assertion", "an assertion"))
        if len(found) > 1:
            return refuse(f"it names both {found[0][1]} and {found[1][1]}")
        if not found:
            if quiet:
                return None
            if accepts == ("label", "pin"):
                return refuse("no net of the module carries that label, and "
                              "a pin is written `instance.pin`")
            if accepts == ("component",):
                return refuse(f"module `{defn.name}` has no instance "
                              f"`{owner}`")
            return refuse("it names no instance, net label or assertion")
        kind = found[0][0]
        if kind == "member":
            if member.broken:
                return None
            if "component" in accepts and member.kind != "component":
                return refuse("it is a module instance, and only a "
                              "component has rules")
        return (kind, owner)

    @staticmethod
    def _shown(target) -> str:
        if target[0] == "pin":
            return f"{target[1]}.{target[2]}"
        return target[1]

    def annotation(self, defn, model, stmt, loops, stated, assertions):
        """A `supply`, `draw` or `waive` statement: its target resolved
        (RHO2080), its bounds or code and justification read, and a second
        statement of one fact about one target refused (RHO2081). A
        `supply` of a voltage and one of a current are two facts."""
        result = defn.result
        kind = str(stmt.children[0])
        node = _tree(stmt, "target")
        bounds = code = justification = None
        if kind == "waive":
            target = self.target(defn, model, kind, node, loops,
                                 ("member", "label", "assertion"),
                                 assertions)
            code = str(stmt.children[1])
            justification = str(stmt.children[3])[1:-1]
            fact = code
        else:
            target = self.target(defn, model, kind, node, loops,
                                 ("label", "pin"))
            bounds = self.bounds(defn, _tree(stmt, "bound"))
            if bounds is None:
                return
            fact = quantities.UNITS[bounds.unit][0] \
                if bounds.unit in quantities.UNITS else bounds.unit
        if target is None:
            return
        span = result.span_of(stmt)
        key = (kind, target, fact)
        if key in stated:
            self.report(
                "RHO2081",
                {"statement": kind, "target": self._shown(target),
                 "module": defn.name},
                span, secondary=((stated[key], "first stated here"),))
            return
        stated[key] = span
        model.notes.append(_Note(kind, target, bounds, code, justification,
                                 span))

    def rule_override(self, defn, model, stmt, loops) -> None:
        """A `rule` statement: its target a component member (RHO2080), its
        pins that member's ports (RHO2082), and its value evaluated in the
        module's environment and loop variables. The member then takes the
        module's rules in place of its definition's."""
        result = defn.result
        target = self.target(defn, model, "rule", _tree(stmt, "target"),
                             loops, ("component",))
        if target is None:
            return
        member = model.members[target[1]]
        word, pins, relation, other, value = _rule_parts(
            _tree(stmt, "rule_body"))
        named = pins + ([other] if other is not None else [])
        # The component as a source names it, as RHO2035 does: a library
        # one by its dotted name. An ad-hoc component has no definition.
        component = (member.target.spelled if member.target is not None
                     else member.definition)
        if not self.rule_pins(defn, str(word), named, member.roles,
                              component):
            return
        evaluated = None
        if value is not None:
            env = _Env(tuple(model.env.values) + tuple(loops.items()))
            evaluated = self.value(defn, value, str(word), env)
            if evaluated is UNKNOWN:
                return
        model.overrides.setdefault(target[1], []).append(Rule(
            str(word), tuple(map(str, pins)), relation,
            None if other is None else str(other), evaluated,
            origin="override", span=result.span_of(stmt)))

    # -- pass H: flattening

    def report_net_defects(self, defects, visits) -> None:
        """Spec 04's reporting rule, applied to flattened-net defects as
        publish() applies it to body findings: a defect that instances
        under every environment of its module show is reported once, with
        the least params and an entity only when every copy names the same
        one; a defect only some environments show depends on the values
        and is reported per instance that shows it, in path order, with
        its net as the entity, else the instance. Copies that come out
        the same diagnostic are said once."""
        model_at = {path: model for model, path, _depth, _trace in visits}
        owner = {id(model): id(defn) for defn in self.defs
                 for model in self.model_order.get(id(defn), ())}
        environments = {}  # id(defn) -> ids of its models the walk used
        for model, _path, _depth, _trace in visits:
            environments.setdefault(owner[id(model)], set()).add(id(model))

        def one(copies):
            params = min(params for _path, params, _entity in copies)
            entities = {entity for _path, _params, entity in copies}
            return dict(params), (entities.pop() if len(entities) == 1
                                  else None)

        for (code, primary, secondary, _detail), copies in defects.items():
            shown = {id(model_at[path]) for path, _params, _e in copies}
            everywhere = shown == environments[owner[next(iter(shown))]]
            if everywhere:
                groups = [copies]
            else:
                by_path = {}
                for copy in copies:
                    by_path.setdefault(copy[0], []).append(copy)
                groups = [by_path[path] for path in sorted(by_path)]
            said = set()
            for group in groups:
                params, entity = one(group)
                if not everywhere and entity is None:
                    entity = group[0][0]  # the instance, as publish() does
                key = (json.dumps(params, sort_keys=True), entity)
                if key in said:
                    continue
                said.add(key)
                self.report(code, params, primary, entity=entity,
                            secondary=secondary)

    def flatten(self, root_def, instances, visits) -> ElaboratedDesign:
        # The design's language version is the newest any of its authored
        # files declares. Only a 0.2 file can import, so today that is
        # always the entry file's. The standard library is the
        # toolchain's, written in whatever syntax it implements, so its
        # files do not raise the version of a design that uses it.
        version = max((str(c).split()[-1] for r in self.results
                       if r.file not in self.library_files
                       for c in r.tree.children
                       if not _is_tree(c) and c.type == "PRAGMA"),
                      key=lambda v: tuple(int(p) for p in v.split(".")))
        found = _UnionFind()
        labels, statements, isolated, checks = [], [], [], []
        notes = []  # (scope path, _Note, the IR target or a label's node)
        endpoint_sites = {}  # node -> [(site key, span)], for the checker
        for model, path, depth, trace in visits:
            labelled = {}  # label -> a node of its net, in this instance
            for connect in model.connects:
                nodes = [(path if ep.member is None
                          else child_path(path, ep.member), ep.port)
                         for ep in connect.endpoints]
                if not nodes:
                    continue
                found.find(nodes[0])
                for node in nodes[1:]:
                    found.union(nodes[0], node)
                for node, endpoint in zip(nodes, connect.endpoints):
                    endpoint_sites.setdefault(node, []).append(
                        ((depth, path, endpoint.span.file,
                          endpoint.span.byte_start, endpoint.span.byte_end),
                         endpoint.span))
                if connect.label is not None:
                    # A net block a loop runs more than once declares one
                    # label: every iteration joins the one net.
                    found.union(labelled.setdefault(connect.label,
                                                    nodes[0]), nodes[0])
                site = (depth, path, connect.span,
                        (connect.span,) + trace)
                statements.append((nodes[0], site))
                if connect.label is not None:
                    labels.append((nodes[0], site,
                                   _qualified_label(path, connect.label),
                                   connect.attributes,
                                   connect.attribute_spans))
                if connect.kind == "isolated":
                    isolated.append((nodes[0], connect.endpoints[0],
                                     connect.span, path))
            for check in model.checks:
                connect = model.labels.get(check.subject)
                if connect is None or not connect.endpoints \
                        or check.bounds is None:
                    continue
                anchor = connect.endpoints[0]
                node = (path if anchor.member is None
                        else child_path(path, anchor.member), anchor.port)
                checks.append((child_path(path, check.name), check, node,
                               (check.span,) + trace))
            for note in model.notes:
                kind, *what = note.target
                if kind == "label":
                    connect = model.labels.get(what[0])
                    if connect is None or not connect.endpoints:
                        continue
                    anchor = connect.endpoints[0]
                    target = ("net", (path if anchor.member is None
                                      else child_path(path, anchor.member),
                                      anchor.port))
                elif kind == "pin":
                    target = ("port", child_path(path, what[0]), what[1])
                elif kind == "member":
                    target = ("instance", child_path(path, what[0]))
                else:
                    target = ("assertion", child_path(path, what[0]))
                notes.append((path, note, target, (note.span,) + trace))

        def site_key(site):
            depth, path, span, _trace = site
            return (depth, path, span.file, span.byte_start)

        groups, group_labels, group_sites = {}, {}, {}
        for node in list(found.parent):
            groups.setdefault(found.find(node), []).append(node)
        for node, site, name, attributes, spans in labels:
            group_labels.setdefault(found.find(node), []).append(
                (site, name, attributes, spans))
        for node, site in statements:
            group_sites.setdefault(found.find(node), []).append(site)

        # A net defect is found once per flattened net, so a module used
        # several times would repeat it once per copy. Copies share their
        # code and spans (and a detail: RHO2028's attribute, RHO2026's
        # evaluated endpoint, which differs per loop iteration); `path` is
        # the instance whose body holds the statement they point at.
        defects = {}

        def defect(code, params, primary, path, detail=None, *,
                   entity=None, secondary=()):
            defects.setdefault((code, primary, secondary, detail), []).append(
                (path, tuple(sorted(params.items())), entity))

        isolated_nets = {found.find(node) for node, *_ in isolated}

        def spans_of(node):
            """A node's endpoint spans in site order, each once."""
            out = []
            for _key, span in sorted(endpoint_sites.get(node, ()),
                                     key=lambda item: item[0]):
                if span not in out:
                    out.append(span)
            return tuple(out)

        nets, names = [], {}
        for key, members in groups.items():
            members = tuple(sorted(set(members)))
            candidates = sorted(group_labels.get(key, []),
                                key=lambda c: site_key(c[0]))
            domains = {"ground_domain": None, "voltage_domain": None}
            attribute_sites = {}
            if candidates:
                shallowest = candidates[0][0][0]
                top = [c for c in candidates if c[0][0] == shallowest]
                distinct = sorted({c[1] for c in top})
                name = distinct[0]
                if len(distinct) > 1:
                    clash = next(c for c in top if c[1] != top[0][1])
                    defect(
                        "RHO2027", {"labels": distinct}, clash[0][2],
                        clash[0][1],
                        secondary=((top[0][0][2], "the other label"),))
                site = next(c[0] for c in top if c[1] == name)
                setters = {}
                for csite, _cname, attributes, spans in candidates:
                    for attribute, value in sorted(attributes.items()):
                        sites = attribute_sites.setdefault(attribute, [])
                        if (value, spans[attribute]) not in sites:
                            sites.append((value, spans[attribute]))
                        if attribute not in domains:
                            # `ground_kind` (0.3) is no domain label: sites
                            # that disagree are GA-2's question, which the
                            # check stage asks of attribute_sites.
                            continue
                        if domains[attribute] is None:
                            domains[attribute] = value
                            setters[attribute] = csite[2]
                        elif domains[attribute] != value:
                            defect(
                                "RHO2028",
                                {"net": name, "attribute": attribute,
                                 "first": domains[attribute],
                                 "second": value},
                                csite[2], csite[1], attribute, entity=name,
                                secondary=((setters[attribute],
                                            "first set here"),))
            else:
                spelled = sorted(member_spelling(p, port)
                                 for p, port in members)
                name = "N_" + spelled[0]
                site = min(group_sites[key], key=site_key)
            names[key] = name
            kinds = {value for value, _span
                     in attribute_sites.get("ground_kind", ())}
            nets.append(Net(name, domains["ground_domain"],
                            domains["voltage_domain"], members, site[2],
                            site[3], isolated=key in isolated_nets,
                            attribute_sites=attribute_sites,
                            endpoint_spans={member: spans_of(member)
                                            for member in members},
                            ground_kind=kinds.pop() if len(kinds) == 1
                            else None))

        for node, endpoint, span, path in isolated:
            key = found.find(node)
            others = sorted(member_spelling(p, port)
                            for p, port in set(groups[key]) if
                            (p, port) != node)
            if others:
                defect(
                    "RHO2026",
                    {"endpoint": endpoint.text, "other": others[0]},
                    span, path, endpoint.text, entity=names[key])

        self.report_net_defects(defects, visits)

        assertions = [
            Assertion(apath, check.tier, check.measurement,
                      names[found.find(node)], check.bounds, check.span,
                      atrace, check.bound_span, check.severity)
            for apath, check, node, atrace in checks]
        annotations = sorted(
            (Annotation(note.kind, scope,
                        ("net", names[found.find(target[1])])
                        if target[0] == "net" else target,
                        note.bounds, note.code, note.justification,
                        note.span, atrace)
             for scope, note, target, atrace in notes),
            key=_annotation_key)

        if len({net.name for net in nets}) != len(nets):
            raise AssertionError(  # pragma: no cover - naming invariant
                "two distinct nets derived one name; the naming rules in "
                "this module's docstring are supposed to make that "
                "impossible")
        return ElaboratedDesign(
            design_name=root_def.name,
            language_version=version + ".0",
            instances=sorted(instances, key=lambda i: i.path),
            nets=sorted(nets, key=lambda n: n.name),
            assertions=sorted(assertions, key=lambda a: a.path),
            files=sorted((SourceFile(r.file, r.data) for r in self.results),
                         key=lambda f: f.path),
            annotations=annotations,
        )
