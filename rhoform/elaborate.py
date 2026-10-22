"""The elaborator (R13 slice 1, R15): parsed v0.1 sources to a design.

LAYERING. This module turns `ok` parse trees into an in-memory
`ElaboratedDesign` that keeps every value as an exact `Decimal` and every
entity's source span. It knows nothing about JSON: `rhoform/ir.py` turns
the design into IR v0 and its source map, owns the canonical encoder, and
computes both hashes. Elaboration runs only on `ok` trees — a recovered
tree is the file with its broken lines removed, and elaborating it would
report the consequences of text the author never wrote.

THE PASSES, in order, each total over its input:

  A. definitions: every `module` per file, named `<module path>.<Name>`
     where the module path is the file's path relative to the compile
     root with `/` turned into `.` and each segment made an identifier;
  B. each module's own ports;
  C. the instantiation graph: a single-word definition must be a module
     visible in the file, a dotted one is a library component (there is
     no bundled library yet, so it is an ad-hoc component whose ports
     are exactly its inline `pin` statements);
  D. cycles (an error: elaboration terminates because no module may
     contain itself), then the root — the unique module of the entry
     file that nothing instantiates — and every module's instance paths;
  E. each module body, checked once per DEFINITION, so a module used
     twice reports a defect in its body once; a diagnostic carries the
     IR entity it is about whenever that entity is unique;
  F. flattening: instances become paths, nets are a union-find over
     (instance path, port) nodes, so a module port — named by the parent
     as `inst.port` and by the module as `port` — is one node and nets
     merge across the hierarchy with no special case. A defect of a
     flattened net that each copy of a module repeats is reported once,
     as pass E does for bodies.

NET NAMES. The shallowest label wins; two different labels at that depth
are an error. A label declared inside a module instance is qualified by
the instance path (`indicator/LED`) always, so a name never depends on
unrelated parts of the design. An unlabelled net is `N_` plus its
lexicographically least member, spelled `<instance path without the
leading slash>.<port>` — so a root port `vin` is `.vin` and its net
`N_.vin`. That rule is interim (R27/M3 owns naming) and is recorded in
the spec so a later change is a ledgered one. Every net a statement
creates is emitted, including the single-member net `isolated` makes.

FLAGS on a module instance are inherited by every descendant (logical
OR). Quantities keep their exact value; `rhoform/ir.py` performs the one
Decimal-to-double conversion at emission, and this module refuses, with a
diagnostic, any number that conversion could not carry.

Structured for the 0.2 surface (imports, `component`, parameter lists,
`if`/`for`, arrays): definitions resolve through one function, statements
dispatch on `tree.data`, and values evaluate through one function, so each
construct lands as a new branch rather than a new pass.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from difflib import get_close_matches
from pathlib import PurePosixPath
import hashlib
import re

from . import quantities
from .diagnostics import Diagnostics, Edit, FixIt, Span, span_from_bytes

STATIC_MEASUREMENTS = frozenset(
    {"operating_point", "power_avg", "power_rms", "efficiency"})
PINLESS_HARDWARE = frozenset({"mounting_hole", "fiducial", "artwork"})
SINGLE_PIN_HARDWARE = frozenset({"test_point", "grounded_mounting_hole"})
FLAGS = ("dnp", "exclude_from_bom", "board_only")
MAX_IR_INTEGER = 2 ** 53

_PAIR_RE = re.compile(r"\A(-?[0-9]+(?:\.[0-9]+)?)(.+)\Z")


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


@dataclass(frozen=True)
class Part:
    binding: str  # "abstract" | "resolved"
    lockfile_key: str | None
    constraints: dict


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


@dataclass
class Net:
    name: str
    ground_domain: str | None
    voltage_domain: str | None
    members: tuple[tuple[str, str], ...]  # sorted (instance path, port)
    declaration: Span
    trace: tuple[Span, ...]


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


def _did_you_mean(word: str, choices, span: Span) -> tuple:
    matches = get_close_matches(word, sorted(choices), n=2, cutoff=0.6)
    if len(matches) != 1:
        return ()
    return (FixIt(f"did you mean `{matches[0]}`?", "needs-review",
                  (Edit(span, matches[0]),)),)


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


# ---- per-definition working state ------------------------------------------

@dataclass
class _ModuleDef:
    name: str
    result: object  # the ParseResult of its file
    tree: object
    header: Span
    definition: str
    order: int
    ports: list = field(default_factory=list)  # Port, source order
    roles: dict = field(default_factory=dict)  # port name -> role
    edges: list = field(default_factory=list)  # (member, target, span)
    paths: list = field(default_factory=list)  # its instance paths


@dataclass
class _Member:
    name: str
    kind: str
    definition: str
    target: _ModuleDef | None
    parameters: dict
    roles: dict  # port name -> role, for endpoint resolution
    ports: tuple = ()
    flags: dict = field(default_factory=dict)
    hardware_kind: str | None = None
    part: Part | None = None
    span: Span | None = None
    broken: bool = False  # failed to resolve; endpoints on it stay quiet


@dataclass
class _Endpoint:
    member: str | None  # None: one of the module's own ports
    port: str
    text: str
    span: Span


@dataclass
class _Connect:
    kind: str  # "net" | "chain" | "isolated"
    endpoints: list
    span: Span
    label: str | None = None
    attributes: dict = field(default_factory=dict)


@dataclass
class _Check:
    name: str
    tier: str
    measurement: str
    subject: str
    bounds: Bounds | None
    span: Span


@dataclass
class _Model:
    members: dict = field(default_factory=dict)
    connects: list = field(default_factory=list)
    labels: dict = field(default_factory=dict)  # label -> _Connect
    checks: list = field(default_factory=list)


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
              sink: Diagnostics | None = None) -> Elaboration:
    """Elaborate a compilation: `results[0]` is the entry file's
    ParseResult, any others are further sources it may read. `root`
    names the root module explicitly; otherwise it is the unique module
    of the entry file that nothing instantiates."""
    results = list(results)
    sink = sink if sink is not None else Diagnostics()
    if not results:
        raise ValueError("elaborate() needs at least the entry file")
    if not all(result.ok for result in results):
        for result in results:
            if result.diagnostics is not sink:
                sink.extend(result.diagnostics)
        return Elaboration(None, sink)
    design = _Elaborator(results, sink).run(root)
    if sink.has_errors:
        design = None
    return Elaboration(design, sink)


def elaborate_source(source: str, path: str = "design.rhoform", *,
                     root: str | None = None) -> Elaboration:
    """Parse and elaborate one file whose compile-root-relative path is
    `path`. The convenience entry point for tests and single files."""
    from .parser import parse

    result = parse(source, file=path)
    return elaborate([result], root=root)


class _Elaborator:
    def __init__(self, results, sink: Diagnostics):
        self.results = results
        self.sink = sink
        self.defs: list[_ModuleDef] = []
        self.visible: dict[str, dict[str, _ModuleDef]] = {}
        self.models: dict[int, _Model] = {}
        self.mentioned: set[int] = set()
        self.unresolved = False

    # -- reporting

    def report(self, code, params, primary, *, entity=None, **kwargs):
        self.sink.add(code, params, primary=primary, entity=entity,
                      **kwargs)

    @staticmethod
    def entity(defn: _ModuleDef, suffix: str | None) -> str | None:
        """The IR identity a body diagnostic is about, when it is unique:
        a module elaborated at exactly one path."""
        if suffix is None or len(defn.paths) != 1:
            return None
        return child_path(defn.paths[0], suffix)

    # -- driver

    def run(self, root: str | None) -> ElaboratedDesign | None:
        for result in self.results:
            self.collect_definitions(result)
        for defn in self.defs:
            self.collect_ports(defn)
        for defn in self.defs:
            self.collect_edges(defn)
        cyclic = self.report_cycles()
        root_def = None
        if not cyclic:
            root_def = self.select_root(root)
            if root_def is not None:
                self.assign_paths(root_def)
        for defn in self.defs:
            self.models[id(defn)] = self.check_body(defn)
        if root_def is None:
            return None
        return self.flatten(root_def)

    # -- pass A: definitions

    def collect_definitions(self, result) -> None:
        mpath = module_path(result.file)
        table = self.visible.setdefault(result.file, {})
        for node in result.tree.children:
            if not (_is_tree(node) and node.data == "module_def"):
                continue
            keyword, name_token = node.children[0], node.children[1]
            name = str(name_token)
            header = _span_through(
                result, result.span_of(keyword).byte_start,
                result.span_of(name_token).byte_end, b":")
            if name in table:
                self.report(
                    "RHO2001", {"name": name}, header,
                    secondary=((table[name].header, "first defined here"),))
                continue
            defn = _ModuleDef(name=name, result=result, tree=node,
                              header=header,
                              definition=f"{mpath}.{name}",
                              order=len(self.defs))
            table[name] = defn
            self.defs.append(defn)

    def statements(self, defn: _ModuleDef):
        return [_unwrap(c) for c in defn.tree.children
                if _is_tree(c) and c.data == "statement"]

    # -- pass B: own ports

    def collect_ports(self, defn: _ModuleDef) -> None:
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
            defn.ports.append(Port(name, role))
            defn.roles[name] = role

    # -- pass C: the instantiation graph

    def resolve(self, defn: _ModuleDef, qualified):
        """(kind, target, definition) for a qualified_name tree, or None
        when a single-word name is not visible. The one place definitions
        resolve, so imports and a bundled library land here."""
        words = _words(qualified)
        if len(words) == 1:
            target = self.visible[defn.result.file].get(words[0])
            if target is None:
                return None
            return "module", target, target.definition
        return "component", None, ".".join(words)

    def collect_edges(self, defn: _ModuleDef) -> None:
        seen = set()
        for stmt in self.statements(defn):
            if stmt.data == "instance_decl":
                name = str(stmt.children[0])
                if name in seen:
                    continue
                seen.add(name)
                resolved = self.resolve(defn, _tree(stmt, "qualified_name"))
                if resolved is None:
                    self.unresolved = True
                elif resolved[0] == "module":
                    defn.edges.append(
                        (name, resolved[1], defn.result.span_of(stmt)))
            elif stmt.data == "table_decl":
                for row in _trees(stmt, "table_row"):
                    seen.add(str(row.children[0]))
                # A table over a module is an error of its own (RHO2006);
                # counting the module as used keeps that one defect from
                # also making the module a second root candidate.
                resolved = self.resolve(defn, _tree(stmt, "qualified_name"))
                if resolved is None:
                    self.unresolved = True
                elif resolved[0] == "module":
                    self.mentioned.add(id(resolved[1]))

    # -- pass D: cycles, root, paths

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

    def select_root(self, root: str | None) -> _ModuleDef | None:
        entry = self.results[0]
        local = [d for d in self.defs if d.result is entry]
        names = [d.name for d in local]
        if root is not None:
            chosen = self.visible[entry.file].get(root)
            if chosen is None:
                self.report("RHO2003", {"name": root, "candidates": names},
                            span_from_bytes(entry.file, entry.data, 0, 0))
            return chosen
        targets = {id(target) for d in self.defs
                   for _n, target, _s in d.edges} | self.mentioned
        candidates = [d for d in local if id(d) not in targets]
        if len(candidates) == 1:
            return candidates[0]
        # An unresolved single-word definition (RHO2005, reported with the
        # body) is the likelier cause of a spare candidate: `new Divder`
        # leaves Divider instantiated by nothing. Naming it as a possible
        # root would send the author to the wrong line, so that defect is
        # reported alone.
        if len(candidates) > 1 and not self.unresolved:
            self.report(
                "RHO2002", {"candidates": [d.name for d in candidates]},
                candidates[1].header,
                secondary=tuple((d.header, "also instantiated by nothing")
                                for d in candidates[:1] + candidates[2:]))
        return None

    def assign_paths(self, root_def: _ModuleDef) -> None:
        work = [(root_def, "/")]
        while work:
            defn, path = work.pop()
            defn.paths.append(path)
            for name, target, _span in reversed(defn.edges):
                work.append((target, child_path(path, name)))

    # -- pass E: module bodies, once per definition

    def check_body(self, defn: _ModuleDef) -> _Model:
        model = _Model()
        first_seen: dict[str, Span] = {}
        statements = self.statements(defn)
        for stmt in statements:
            if stmt.data == "instance_decl":
                self.instance(defn, model, stmt, first_seen)
            elif stmt.data == "table_decl":
                self.table(defn, model, stmt, first_seen)
        for stmt in statements:
            if stmt.data in ("net_decl", "chain", "isolated_decl"):
                self.connect(defn, model, stmt)
        names: dict[str, Span] = {}
        for stmt in statements:
            if stmt.data == "assertion":
                self.assertion(defn, model, stmt, names)
        return model

    def declare(self, defn, model, name, span, first_seen) -> bool:
        """Claim a member name in the module; False (reported) if taken."""
        if name in first_seen:
            self.report(
                "RHO2007",
                {"kind": "instance", "name": name,
                 "scope": f"module `{defn.name}`"},
                span, entity=self.entity(defn, name),
                secondary=((first_seen[name], "first declared here"),))
            return False
        first_seen[name] = span
        return True

    def instance(self, defn, model, stmt, first_seen) -> None:
        result = defn.result
        name = str(stmt.children[0])
        span = result.span_of(stmt)
        if not self.declare(defn, model, name, span, first_seen):
            return
        entity = self.entity(defn, name)
        qualified = _tree(stmt, "qualified_name")
        resolved = self.resolve(defn, qualified)
        if resolved is None:
            word = _words(qualified)[0]
            qspan = result.span_of(qualified)
            self.report("RHO2005", {"name": word}, qspan,
                        fixits=_did_you_mean(
                            word, self.visible[result.file], qspan))
            model.members[name] = _Member(
                name, "component", word, None, {}, {}, span=span,
                broken=True)
            return
        kind, target, definition = resolved
        parameters = self.arguments(defn, _tree(stmt, "arguments"), name)
        body = _tree(stmt, "instance_body")
        facts = [_unwrap(c) for c in body.children] if body is not None \
            else []
        if kind == "module":
            member = _Member(name, kind, definition, target, parameters,
                             dict(target.roles), tuple(target.ports),
                             span=span)
            self.module_facts(defn, member, facts, entity)
        else:
            member = _Member(name, kind, definition, None, parameters, {},
                             span=span)
            self.component_facts(defn, member, facts, entity)
        model.members[name] = member

    def flags(self, defn, member, facts, entity) -> dict:
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
                            span, entity=entity)
                continue
            table[word] = span
        return stated, denied

    def module_facts(self, defn, member, facts, entity) -> None:
        stated, denied = self.flags(defn, member, facts, entity)
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
                defn.result.span_of(fact), entity=entity)
        member.flags = {flag: True for flag in stated}

    def component_facts(self, defn, member, facts, entity) -> None:
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
                        span, entity=entity,
                        secondary=((pin_spans[pin], "first declared here"),))
                    continue
                pin_spans[pin] = span
                designators = []
                for designator in _trees(fact, "designator"):
                    text = str(designator.children[0])
                    if text in designators:
                        self.report(
                            "RHO2007",
                            {"kind": "designator", "name": text,
                             "scope": f"pin `{pin}` of instance "
                                      f"`{member.name}`"},
                            result.span_of(designator), entity=entity)
                        continue
                    designators.append(text)
                ports.append(Port(pin, role, tuple(sorted(designators))))
            elif fact.data == "part_decl":
                if part_seen:
                    self.report("RHO2010",
                                {"fact": "part", "instance": member.name},
                                span, entity=entity)
                    continue
                part_seen = True
                member.part = self.part(defn, member.name, fact, span, entity)
            elif fact.data == "hardware_decl":
                if hardware is not None:
                    self.report("RHO2010",
                                {"fact": "hardware", "instance": member.name},
                                span, entity=entity)
                    continue
                hardware = str(_tokens(fact, "NAME")[0])
                hardware_span = span
        stated, denied = self.flags(defn, member, facts, entity)
        for flag in sorted(set(stated) & set(denied)):
            later = max(stated[flag], denied[flag],
                        key=lambda s: s.byte_start)
            self.report("RHO2012", {"flag": flag, "instance": member.name},
                        later, entity=entity)
        member.flags = {flag: True for flag in stated}
        member.ports = tuple(ports)
        member.roles = {port.name: port.role for port in ports}
        member.hardware_kind = hardware
        if hardware is not None:
            self.hardware_arity(member, hardware, hardware_span, entity)

    def hardware_arity(self, member, hardware, span, entity) -> None:
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
            span, entity=entity)

    def part(self, defn, instance, fact, span, entity) -> Part:
        binding = fact.children[1]
        statements = _trees(fact, "constraint")
        constraints = self.pairs(defn, statements, "constraint",
                                 f"instance `{instance}`")
        if getattr(binding, "type", None) == "STRING":
            key = str(binding)[1:-1]
            if not key:
                self.report("RHO2015", {"instance": instance}, span,
                            entity=entity)
            return Part("resolved", key, constraints)
        if not statements:
            self.report("RHO2014", {"instance": instance}, span,
                        entity=entity)
        return Part("abstract", None, constraints)

    # -- values

    def arguments(self, defn, node, instance) -> dict:
        if node is None:
            return {}
        return self.pairs(defn, _trees(node, "argument"), "argument",
                          f"instance `{instance}`")

    def pairs(self, defn, statements, kind, scope) -> dict:
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
            value = self.value(defn, _tree(stmt, "value"), name)
            if value is not None:
                out[name] = value
        return out

    def value(self, defn, node, name):
        """One `value` tree to its elaborated value, or None (reported).
        The single evaluation point: a parameter reference lands here."""
        token = node.children[0]
        text = str(token)
        span = defn.result.span_of(token)
        if token.type == "STRING":
            return text[1:-1]
        if text in ("true", "false"):
            return text == "true"
        if token.type == "INTEGER":
            number = int(text)
            if abs(number) > MAX_IR_INTEGER:
                self.report("RHO2017", {"literal": text}, span)
                return None
            return number
        parsed = quantities.parse_quantity(text)
        if parsed.nominal is None:
            self.report("RHO2016", {"literal": text, "name": name}, span)
            return None
        unit, multiplier = _unit_for(parsed.nominal, parsed.dimension)
        tolerance = None
        if parsed.form != "exact":
            tolerance = (_in_unit(parsed.lower, multiplier),
                         _in_unit(parsed.upper, multiplier))
        quantity = Quantity(_in_unit(parsed.nominal, multiplier), unit,
                            tolerance)
        if not _representable(quantity.value, *(tolerance or ())):
            self.report("RHO2017", {"literal": text}, span)
            return None
        return quantity

    # -- tables

    def table(self, defn, model, stmt, first_seen) -> None:
        result = defn.result
        qualified = _tree(stmt, "qualified_name")
        qname = ".".join(_words(qualified))
        resolved = self.resolve(defn, qualified)
        broken = False
        if resolved is None:
            qspan = result.span_of(qualified)
            self.report("RHO2005", {"name": qname}, qspan,
                        fixits=_did_you_mean(
                            qname, self.visible[result.file], qspan))
            broken = True
        elif resolved[0] == "module":
            self.report("RHO2006", {"name": qname},
                        result.span_of(qualified))
            broken = True
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
        for row in _trees(stmt, "table_row"):
            name = str(row.children[0])
            span = result.span_of(row)
            if not self.declare(defn, model, name, span, first_seen):
                continue
            values = _trees(row, "value")
            member = _Member(name, "component", qname, None, {}, {},
                             span=span, broken=broken)
            model.members[name] = member
            if len(values) != len(columns):
                self.report(
                    "RHO2018",
                    {"row": name, "values": len(values),
                     "columns": len(columns)},
                    header, entity=self.entity(defn, name),
                    secondary=((span, "this row"),))
                member.broken = True
                continue
            constraints = {}
            for slot, node in zip(plan, values):
                if slot is None:
                    continue
                value = self.value(defn, node, slot[1])
                if value is None:
                    continue
                target = member.parameters if slot[0] == "parameter" \
                    else constraints
                target[slot[1]] = value
            if binding is not None:
                member.part = Part("resolved" if key is not None
                                   else "abstract", key, constraints)

    # -- connections

    def endpoint(self, defn, model, node):
        """Resolve one endpoint, or None (reported, or quiet when it names
        an instance that already failed to resolve)."""
        result = defn.result
        tokens = [c for c in node.children if not _is_tree(c)]
        text = ".".join(str(t) for t in tokens)
        span = result.span_of(node)
        if len(tokens) == 1:
            name = str(tokens[0])
            role = defn.roles.get(name)
            if role is None:
                self.report("RHO2023", {"name": name, "module": defn.name},
                            span, fixits=_did_you_mean(name, defn.roles,
                                                       span))
                return None
            if role == "nc":
                self.report("RHO2024", {"endpoint": text}, span)
                return None
            return _Endpoint(None, name, text, span)
        owner, port = str(tokens[0]), str(tokens[1])
        member = model.members.get(owner)
        if member is None:
            ospan = result.span_of(tokens[0])
            self.report("RHO2021", {"instance": owner, "module": defn.name},
                        ospan, fixits=_did_you_mean(owner, model.members,
                                                    ospan))
            return None
        if member.broken:
            return None
        role = member.roles.get(port)
        if role is None:
            pspan = result.span_of(tokens[1])
            self.report(
                "RHO2022",
                {"instance": owner, "definition": member.definition,
                 "port": port},
                pspan, entity=self.entity(defn, owner),
                fixits=_did_you_mean(port, member.roles, pspan))
            return None
        if role == "nc":
            self.report("RHO2024", {"endpoint": text}, span,
                        entity=self.entity(defn, owner))
            return None
        return _Endpoint(owner, port, text, span)

    def connect(self, defn, model, stmt) -> None:
        result = defn.result
        span = result.span_of(stmt)
        label, attributes = None, {}
        if stmt.data == "net_decl":
            kind, nodes = "net", _trees(stmt, "endpoint")
            label = str(_tokens(stmt, "FREE_NAME")[0])
            if label in model.labels:
                self.report(
                    "RHO2007",
                    {"kind": "net", "name": label,
                     "scope": f"module `{defn.name}`"},
                    span, secondary=((model.labels[label].span,
                                      "first labelled here"),))
                label = None
            attributes = self.net_attributes(defn, stmt, label)
        elif stmt.data == "chain":
            kind = "chain"
            nodes = _trees(stmt, "chain_head") + _trees(stmt, "endpoint")
        else:
            kind, nodes = "isolated", _trees(stmt, "endpoint")
        endpoints, seen = [], set()
        for node in nodes:
            endpoint = self.endpoint(defn, model, node)
            if endpoint is None:
                continue
            key = (endpoint.member, endpoint.port)
            if key in seen:
                self.report("RHO2025", {"endpoint": endpoint.text},
                            endpoint.span)
                continue
            seen.add(key)
            endpoints.append(endpoint)
        connect = _Connect(kind, endpoints, span, label, attributes)
        model.connects.append(connect)
        if label is not None:
            model.labels[label] = connect

    def net_attributes(self, defn, stmt, label) -> dict:
        node = _tree(stmt, "net_attributes")
        if node is None:
            return {}
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
        return out

    # -- assertions

    def assertion(self, defn, model, stmt, names) -> None:
        result = defn.result
        words = [c for c in stmt.children if not _is_tree(c)]
        name, tier = str(words[1]), str(words[2])
        measurement, subject = str(words[3]), str(words[4])
        span = result.span_of(stmt)
        entity = self.entity(defn, name)
        if name in names:
            self.report(
                "RHO2007",
                {"kind": "assertion", "name": name,
                 "scope": f"module `{defn.name}`"},
                span, entity=entity,
                secondary=((names[name], "first declared here"),))
            return
        names[name] = span
        if name in model.members:
            self.report("RHO2008", {"name": name, "module": defn.name},
                        span, secondary=((model.members[name].span,
                                          "the instance"),))
        if tier == "static" and measurement not in STATIC_MEASUREMENTS:
            self.report("RHO2030", {"name": name, "measurement": measurement},
                        result.span_of(words[3]), entity=entity)
        if subject not in model.labels:
            sspan = result.span_of(words[4])
            self.report("RHO2029", {"subject": subject, "module": defn.name},
                        sspan, entity=entity,
                        fixits=_did_you_mean(subject, model.labels, sspan))
        bounds = self.bounds(defn, _tree(stmt, "bound"))
        model.checks.append(
            _Check(name, tier, measurement, subject, bounds, span))

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

    # -- pass F: flattening

    def flatten(self, root_def: _ModuleDef) -> ElaboratedDesign:
        entry = self.results[0]
        pragma = next(c for c in entry.tree.children
                      if not _is_tree(c) and c.type == "PRAGMA")
        instances = [Instance(
            path="/", kind="module", definition=root_def.definition,
            parameters={}, ports=tuple(root_def.ports), dnp=False,
            exclude_from_bom=False, board_only=False, hardware_kind=None,
            part=None, declaration=root_def.header, trace=())]
        found = _UnionFind()
        labels, statements, isolated, checks = [], [], [], []
        work = [(root_def, "/", 0, (), dict.fromkeys(FLAGS, False))]
        while work:
            defn, path, depth, trace, inherited = work.pop()
            model = self.models[id(defn)]
            for member in model.members.values():
                if member.broken:
                    continue
                ipath = child_path(path, member.name)
                flags = {flag: member.flags.get(flag, False)
                         or inherited[flag] for flag in FLAGS}
                itrace = (member.span,) + trace
                instances.append(Instance(
                    path=ipath, kind=member.kind,
                    definition=member.definition,
                    parameters=dict(member.parameters),
                    ports=tuple(member.ports),
                    hardware_kind=member.hardware_kind, part=member.part,
                    declaration=member.span, trace=itrace, **flags))
                if member.kind == "module":
                    work.append((member.target, ipath, depth + 1, itrace,
                                 flags))
            for connect in model.connects:
                nodes = [(path if ep.member is None
                          else child_path(path, ep.member), ep.port)
                         for ep in connect.endpoints]
                if not nodes:
                    continue
                found.find(nodes[0])
                for node in nodes[1:]:
                    found.union(nodes[0], node)
                site = (depth, path, connect.span,
                        (connect.span,) + trace)
                statements.append((nodes[0], site))
                if connect.label is not None:
                    labels.append((nodes[0], site,
                                   _qualified_label(path, connect.label),
                                   connect.attributes))
                if connect.kind == "isolated":
                    isolated.append((nodes[0], connect.endpoints[0],
                                     connect.span))
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

        def site_key(site):
            depth, path, span, _trace = site
            return (depth, path, span.file, span.byte_start)

        groups, group_labels, group_sites = {}, {}, {}
        for node in list(found.parent):
            groups.setdefault(found.find(node), []).append(node)
        for node, site, name, attributes in labels:
            group_labels.setdefault(found.find(node), []).append(
                (site, name, attributes))
        for node, site in statements:
            group_sites.setdefault(found.find(node), []).append(site)

        # A net defect is found once per flattened net, so a module used
        # several times would repeat it once per copy. Copies share their
        # code and spans (and, for RHO2028, the attribute); spec 04 reports
        # them once, with the least params and an entity only when every
        # copy names the same one.
        defects = {}

        def defect(code, params, primary, detail=None, *, entity=None,
                   secondary=()):
            defects.setdefault((code, primary, secondary, detail), []).append(
                (tuple(sorted(params.items())), entity))

        nets, names = [], {}
        for key, members in groups.items():
            members = tuple(sorted(set(members)))
            candidates = sorted(group_labels.get(key, []),
                                key=lambda c: site_key(c[0]))
            domains = {"ground_domain": None, "voltage_domain": None}
            if candidates:
                shallowest = candidates[0][0][0]
                top = [c for c in candidates if c[0][0] == shallowest]
                distinct = sorted({c[1] for c in top})
                name = distinct[0]
                if len(distinct) > 1:
                    clash = next(c for c in top if c[1] != top[0][1])
                    defect(
                        "RHO2027", {"labels": distinct}, clash[0][2],
                        secondary=((top[0][0][2], "the other label"),))
                site = next(c[0] for c in top if c[1] == name)
                setters = {}
                for csite, _cname, attributes in candidates:
                    for attribute, value in sorted(attributes.items()):
                        if domains[attribute] is None:
                            domains[attribute] = value
                            setters[attribute] = csite[2]
                        elif domains[attribute] != value:
                            defect(
                                "RHO2028",
                                {"net": name, "attribute": attribute,
                                 "first": domains[attribute],
                                 "second": value},
                                csite[2], attribute, entity=name,
                                secondary=((setters[attribute],
                                            "first set here"),))
            else:
                spelled = sorted(member_spelling(p, port)
                                 for p, port in members)
                name = "N_" + spelled[0]
                site = min(group_sites[key], key=site_key)
            names[key] = name
            nets.append(Net(name, domains["ground_domain"],
                            domains["voltage_domain"], members, site[2],
                            site[3]))

        for node, endpoint, span in isolated:
            key = found.find(node)
            others = sorted(member_spelling(p, port)
                            for p, port in set(groups[key]) if
                            (p, port) != node)
            if others:
                defect(
                    "RHO2026",
                    {"endpoint": endpoint.text, "other": others[0]},
                    span, entity=names[key])

        for (code, primary, secondary, _detail), copies in defects.items():
            params = min(params for params, _entity in copies)
            entities = {entity for _params, entity in copies}
            self.report(code, dict(params), primary,
                        entity=entities.pop() if len(entities) == 1
                        else None,
                        secondary=secondary)

        assertions = [
            Assertion(apath, check.tier, check.measurement,
                      names[found.find(node)], check.bounds, check.span,
                      atrace)
            for apath, check, node, atrace in checks]

        if len({net.name for net in nets}) != len(nets):
            raise AssertionError(  # pragma: no cover - naming invariant
                "two distinct nets derived one name; the naming rules in "
                "this module's docstring are supposed to make that "
                "impossible")
        return ElaboratedDesign(
            design_name=root_def.name,
            language_version=str(pragma).split()[-1] + ".0",
            instances=sorted(instances, key=lambda i: i.path),
            nets=sorted(nets, key=lambda n: n.name),
            assertions=sorted(assertions, key=lambda a: a.path),
            files=sorted((SourceFile(r.file, r.data) for r in self.results),
                         key=lambda f: f.path),
        )
