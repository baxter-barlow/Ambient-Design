"""The Starlark-restricted-Python baseline — §4's budgeted line item.

§4 names one fallback and one only: "Starlark-restricted Python, never full
Python", and makes the flip criterion a comparison against it under the AC5
protocol. A comparison needs something to compare against, so here it is: a
builder API, and an evaluator that enforces the restriction.

THE RESTRICTION IS ENFORCED BY AN AST ALLOWLIST AND A TREE-WALKING
EVALUATOR. There is no `exec`, no `eval`, and no sandboxed-globals trick,
because none of those actually restricts Python — and "arbitrary code
execution from an untrusted model" is the specific thing §6 rejects the
embedded path for. A baseline that ran the model's Python would be
demonstrating the objection rather than answering it.

What is forbidden, and what each rejection is for:

    import / from            hermeticity (I3): a design cannot reach the host
    while                    termination (L1)
    recursion                termination (L1), checked statically on the call
                             graph the way Starlark does, not by blowing a
                             stack at runtime
    class                    no user-defined types; nothing to reflect over
    lambda, comprehension    keeps the evaluable subset small and total
    global / nonlocal        no free-function mutation of module state — one
                             of JITX's four banned patterns
    try / with / raise       no control flow that can swallow a failure
    attributes off the API   an attribute access is only legal on a builder
                             or a handle, and only for a method that builder
                             declares. An earlier version allowed any
                             non-underscore attribute on any value, which was
                             not a restriction at all: `"".format` walks
                             `.attr` and `[key]` for free, so five lines of
                             design could read os.environ and sys.modules and
                             put the host's state into the netlist. Blocking
                             `_`-prefixed names is a spelling rule, not a
                             capability rule.
    f-strings, walrus        no expression forms that hide a computation

A step budget bounds node visits, and `range()` and `+` are bounded
separately — the budget alone does not bound WORK, because fourteen node
visits can allocate a gigabyte. Call depth is counted at runtime as well as
statically, because the static call graph only sees cycles routed through a
bare function name, and a function passed as an argument is invisible to it.

WHAT THIS BASELINE COSTS, VISIBLY. Every dimensioned value is a STRING,
because `100kohm` is not a Python expression. That is §6's "SKiDL's stringly
values" criticism reproduced rather than asserted, and it has teeth here: a
symbolic value that happens to look like a quantity is silently read as one,
and no amount of API design fixes it while the host language owns the literal
syntax. The measurement records the cost; the failure mode is the argument.
"""

import ast
from dataclasses import dataclass

from .. import library
from ..diagnostics import Diag, ParseFailure, Span
from ..model import (
    Assertion,
    DesignModel,
    HARDWARE_KINDS,
    Instance,
    MEASUREMENT_KINDS,
    PIN_ROLES,
    Port,
    Value,
)
from ..quantities import QuantityError, parse_quantity
from .base import variant_flags
from .shared import build_model, module_order

KEY = "starlark"
TITLE = "S - Starlark baseline"
CODE_PREFIX = "RHOS"

# Only `explicit` and `inferred`: L6's columnar sub-syntax is a proposal for
# Rhoform's surface, and Python has no columnar form to compare it against. Saying
# so is better than inventing one and reporting a number for it.
VARIANTS = ("explicit", "inferred")

STEP_BUDGET = 200_000

# Bounds on WORK, not on syntax. The step budget counts node visits and a
# handful of them can allocate arbitrarily much, so collection size and call
# depth are charged separately.
MAX_COLLECTION = 100_000
MAX_CALL_DEPTH = 64

_FORBIDDEN = {
    ast.Import: ("import", "a design may not reach outside itself (I3 hermeticity)"),
    ast.ImportFrom: ("import", "a design may not reach outside itself (I3 hermeticity)"),
    ast.While: ("while", "elaboration must terminate (L1); use a bounded `for`"),
    ast.ClassDef: ("class", "no user-defined types; there is nothing to reflect over"),
    ast.Lambda: ("lambda", "the evaluable subset is deliberately small"),
    ast.ListComp: ("comprehension", "the evaluable subset is deliberately small"),
    ast.SetComp: ("comprehension", "the evaluable subset is deliberately small"),
    ast.DictComp: ("comprehension", "the evaluable subset is deliberately small"),
    ast.GeneratorExp: ("generator", "the evaluable subset is deliberately small"),
    ast.Global: ("global", "no free-function mutation of module state"),
    ast.Nonlocal: ("nonlocal", "no free-function mutation of module state"),
    ast.Try: ("try", "no control flow that can swallow a failure"),
    ast.With: ("with", "no context managers; there are no resources to manage"),
    ast.Raise: ("raise", "no user-raised exceptions"),
    ast.Delete: ("del", "no name deletion"),
    ast.Yield: ("yield", "no generators"),
    ast.YieldFrom: ("yield from", "no generators"),
    ast.Await: ("await", "elaboration is effect-free (L1)"),
    ast.AsyncFunctionDef: ("async def", "elaboration is effect-free (L1)"),
    ast.JoinedStr: ("f-string", "no computation hidden inside a literal"),
    ast.NamedExpr: (":=", "no assignment inside an expression"),
    ast.Starred: ("*args unpacking", "call shapes stay statically readable"),
    ast.Assert: ("assert", "design assertions are `m.check(...)`, not Python asserts"),
}


class StarlarkError(Exception):
    def __init__(self, diagnostics):
        self.diagnostics = list(diagnostics)
        super().__init__(self.diagnostics[0].message if self.diagnostics else "rejected")


def _span(node) -> Span:
    return Span(
        line=getattr(node, "lineno", 1),
        column=getattr(node, "col_offset", 0) + 1,
        offset=0,
        length=1,
    )


def _reject(node, code: str, message: str, fixit: str | None = None):
    raise StarlarkError(
        [
            Diag(
                code=f"{CODE_PREFIX}{code}",
                message=message,
                span=_span(node),
                params={"node": type(node).__name__},
                fixit=fixit,
            )
        ]
    )


# --------------------------------------------------------------------------
# Static restriction pass
# --------------------------------------------------------------------------


def _check_restrictions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    """Reject forbidden constructs and recursion before anything runs.

    Recursion is caught on the call graph rather than at runtime, which is
    what Starlark does and what makes the termination claim static rather than
    a promise about how deep the stack happens to get.
    """
    functions: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        for forbidden, (name, why) in _FORBIDDEN.items():
            if isinstance(node, forbidden):
                _reject(node, "0101", f"`{name}` is not available: {why}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            _reject(
                node,
                "0102",
                f"attribute {node.attr!r} is private",
                fixit="the builder's public methods are the whole API",
            )
        if isinstance(node, ast.FunctionDef):
            if node.name in functions:
                _reject(node, "0103", f"function {node.name!r} is defined twice")
            if node.decorator_list:
                _reject(
                    node,
                    "0106",
                    f"function {node.name!r} carries a decorator",
                    fixit="decorators are neither applied nor allowed here",
                )
            if getattr(node, "type_params", ()):
                _reject(
                    node,
                    "0107",
                    f"function {node.name!r} carries type parameters",
                    fixit="there is no type system in this subset to carry them",
                )
            if node.args.defaults or node.args.kw_defaults:
                _reject(
                    node,
                    "0108",
                    f"function {node.name!r} has default arguments",
                    fixit="every call states every argument",
                )
            if node.args.vararg or node.args.kwarg or node.args.kwonlyargs:
                _reject(
                    node,
                    "0104",
                    f"function {node.name!r} uses a variadic signature",
                    fixit="parameters are positional or keyword, and named",
                )
            functions[node.name] = node

    calls: dict[str, set[str]] = {name: set() for name in functions}
    for name, node in functions.items():
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                if inner.func.id in functions:
                    calls[name].add(inner.func.id)
            # A bare reference also counts: `m.sub("x", LedIndicator)` hands a
            # function to the builder, which calls it. Ignoring that would let
            # mutual recursion through the API slip past the check.
            if isinstance(inner, ast.Name) and inner.id in functions and inner.id != name:
                calls[name].add(inner.id)

    colour: dict[str, int] = {}

    def visit(name: str, stack: tuple[str, ...]):
        if colour.get(name) == 2:
            return
        if colour.get(name) == 1:
            _reject(
                functions[name],
                "0105",
                "recursive definition: " + " -> ".join(stack + (name,)),
                fixit="elaboration must terminate (L1); Starlark forbids recursion",
            )
        colour[name] = 1
        for callee in sorted(calls[name]):
            visit(callee, stack + (name,))
        colour[name] = 2

    for name in sorted(functions):
        visit(name, ())
    return functions


# --------------------------------------------------------------------------
# Builder API
# --------------------------------------------------------------------------


def _as_value(raw, node) -> Value:
    """Coerce a Python value from the baseline source into a model Value.

    THE STRINGLY-VALUE HAZARD LIVES HERE and is not hidden: a string is a
    quantity if it parses as one, and a symbolic value that happens to look
    dimensioned is silently reclassified. `"0R"` reads as a string because `R`
    is not a unit; `"16V"` reads as a quantity even if it was meant as a
    package code. The host language owns literal syntax, so the API cannot fix
    this — which is exactly what §6 says about embedding.
    """
    if isinstance(raw, bool):
        return Value(tag="b", flag=raw)
    if isinstance(raw, int):
        return Value(tag="i", number=raw)
    if isinstance(raw, str):
        try:
            return Value(tag="q", quantity=parse_quantity(raw))
        except QuantityError:
            if not raw:
                _reject(node, "0201", "an empty string is not a value")
            return Value(tag="s", text=raw)
    _reject(node, "0202", f"{type(raw).__name__} is not a value")


class _Handle:
    """What `m.part(...)` hands back: the instance being described."""

    def __init__(self, record: dict):
        self.record = record

    def pins(self, *specs, node=None):
        for spec in specs:
            if not isinstance(spec, (list, tuple)) or not 2 <= len(spec) <= 3:
                _reject(node, "0203", "a pin is (name, role) or (name, role, designators)")
            name, role = spec[0], spec[1]
            if role not in PIN_ROLES:
                _reject(node, "0204", f"{role!r} is not a pin role")
            designators = spec[2] if len(spec) == 3 else []
            if isinstance(designators, str):
                designators = [designators]
            self.record["ports"].append(
                Port(
                    name=name,
                    role=role,
                    pin_numbers=tuple(sorted(str(d) for d in designators)),
                )
            )
        return self

    def part(self, key=None, node=None, **constraints):
        if key is not None:
            self.record["lockfile_key"] = key
        else:
            self.record["abstract"] = True
        for name, raw in constraints.items():
            self.record["constraints"][name] = _as_value(raw, node)
        return self

    def hardware(self, kind, node=None, exclude_from_bom=False, board_only=False):
        if kind not in HARDWARE_KINDS:
            _reject(node, "0205", f"{kind!r} is not an L9 hardware kind")
        self.record["hardware_kind"] = kind
        self.record["exclude_from_bom"] = bool(exclude_from_bom)
        self.record["board_only"] = bool(board_only)
        self.record["hardware_stated"] = True
        return self

    def fab(self, node=None, exclude_from_bom=False, board_only=False):
        """L9 flags on a component that has no hardware kind.

        Without this the arm could not express `exclude_from_bom` on an
        ordinary component at all — `.hardware()` was the only setter and it
        demands a kind — so the flags were silently dropped on the round trip.
        The agreement gate passed only because neither corpus design used that
        combination, which is what the coverage fixture now exists to stop.
        """
        self.record["exclude_from_bom"] = bool(exclude_from_bom)
        self.record["board_only"] = bool(board_only)
        self.record["hardware_stated"] = True
        return self

    def dnp(self, node=None):
        self.record["dnp"] = True
        return self


class _ModuleBuilder:
    def __init__(self, name: str):
        self.name = name
        self.ports: list[Port] = []
        self.instances: dict[str, dict] = {}
        self.signals: dict[str, dict] = {}
        self.links: list[tuple[str, str]] = []
        self.assertions: list[Assertion] = []
        # Line of the call that introduced each endpoint, so a semantic
        # failure found after evaluation still points somewhere.
        self.spans: dict = {}

    def _record(self, name: str, definition: str, params: dict, node) -> dict:
        if name in self.instances or name in self.signals:
            _reject(node, "0206", f"{name!r} is already declared in {self.name!r}")
        record = {
            "name": name,
            "definition": definition,
            "parameters": {k: _as_value(v, node) for k, v in params.items()},
            "ports": [],
            "constraints": {},
            "lockfile_key": None,
            "abstract": False,
            "hardware_kind": None,
            "hardware_stated": False,
            "dnp": False,
            "exclude_from_bom": False,
            "board_only": False,
        }
        self.instances[name] = record
        return record

    # -- API ------------------------------------------------------------
    def port(self, name, role, node=None):
        if role not in PIN_ROLES:
            _reject(node, "0204", f"{role!r} is not a pin role")
        self.ports.append(Port(name=name, role=role))

    def part(self, name, definition, node=None, **params):
        return _Handle(self._record(name, definition, params, node))

    def sub(self, name, definition, node=None, **params):
        target = definition if isinstance(definition, str) else getattr(definition, "name", None)
        if target is None:
            _reject(node, "0207", "a submodule is named by its function or its name")
        return _Handle(self._record(name, target, params, node))

    def net(self, name, *members, node=None, **attributes):
        if name in self.signals or name in self.instances:
            _reject(node, "0206", f"{name!r} is already declared in {self.name!r}")
        for key in attributes:
            if key not in ("ground_domain", "voltage_domain"):
                _reject(node, "0208", f"{key!r} is not a net attribute")
        if not members:
            _reject(node, "0209", f"net {name!r} has no members")
        self.signals[name] = {
            "ground_domain": attributes.get("ground_domain"),
            "voltage_domain": attributes.get("voltage_domain"),
        }
        for member in members:
            self.links.append((name, member))
            self.spans.setdefault(member, _span(node) if node is not None else None)

    def isolated(self, endpoint, node=None):
        """A net with exactly one endpoint (L9b intentional single-pin net)."""
        self.links.append((endpoint, endpoint))
        self.spans.setdefault(endpoint, _span(node) if node is not None else None)

    def link(self, *endpoints, node=None):
        if len(endpoints) == 1:
            _reject(
                node,
                "0210",
                "a link joins at least two endpoints",
                fixit="for a deliberate single-pin net use m.isolated(...)",
            )
        if len(endpoints) < 2:
            _reject(node, "0210", "a link joins at least two endpoints")
        for left, right in zip(endpoints, endpoints[1:]):
            self.links.append((left, right))
        for endpoint in endpoints:
            self.spans.setdefault(endpoint, _span(node) if node is not None else None)

    def check(self, name, tier, measurement, subject, node=None, unit="1", min=None, max=None):
        if tier not in ("static", "dynamic"):
            _reject(node, "0211", f"{tier!r} is not an assertion tier")
        if measurement not in MEASUREMENT_KINDS:
            _reject(node, "0212", f"{measurement!r} is not in the V2 vocabulary")
        if min is None and max is None:
            _reject(node, "0213", f"assertion {name!r} declares no bound")
        self.assertions.append(
            Assertion(
                name=name,
                tier=tier,
                measurement=measurement,
                subject=subject,
                unit=unit,
                minimum=None if min is None else str(min),
                maximum=None if max is None else str(max),
            )
        )


class _BoundMethod:
    """An API method bound to its receiver, opaque to the design.

    A bare `(method, node)` tuple used to travel here, which the evaluator's
    Subscript branch happily indexed - so a design could pull the raw callable
    out and invoke it with arguments the call protocol never saw. This carries
    no non-underscore attribute and is not a sequence, so there is nothing to
    take apart.
    """

    __slots__ = ("_fn", "_node")

    def __init__(self, fn, node):
        self._fn = fn
        self._node = node


# The whole attribute surface. An attribute access is legal only on one of
# these types and only for a method it declares here. Anything else - a
# string's `.format`, a list's `.append`, a function's `.__globals__` - is a
# capability the design does not get, and the reason the check is a table
# rather than a `getattr` is that `getattr` is not a restriction.
_API_METHODS = {
    "_ModuleBuilder": frozenset(
        {"port", "part", "sub", "net", "link", "isolated", "check"}
    ),
    "_Handle": frozenset({"pins", "part", "hardware", "fab", "dnp"}),
}


class _FunctionValue:
    def __init__(self, node: ast.FunctionDef):
        self.node = node
        self.name = node.name


class _DesignMarker:
    def __init__(self, modules):
        self.modules = modules


# --------------------------------------------------------------------------
# Evaluator
# --------------------------------------------------------------------------


class _Evaluator:
    """A total tree-walking evaluator over the allowed subset.

    Total in the sense L1 asks for: the allowlist removes `while` and the
    static pass removes recursion, so the only remaining way to run forever is
    a `for` over something enormous, which the step budget covers.
    """

    def __init__(self, functions):
        self.functions = functions
        self.steps = 0
        self.depth = 0
        # Identity set of the builtins a design may call. `callable(target)`
        # used to stand here, which let anything callable that reached the
        # value space be invoked.
        self.builtins = set()

    def step(self, node):
        self.steps += 1
        if self.steps > STEP_BUDGET:
            _reject(
                node,
                "0301",
                f"evaluation exceeded {STEP_BUDGET} steps",
                fixit="elaboration is bounded; a design this large is a bug",
            )

    # -- statements -----------------------------------------------------
    def exec_body(self, body, env):
        for statement in body:
            result = self.exec_statement(statement, env)
            if result is not None:
                return result
        return None

    def exec_statement(self, node, env):
        self.step(node)
        if isinstance(node, ast.FunctionDef):
            env[node.name] = _FunctionValue(node)
            return None
        if isinstance(node, ast.Assign):
            value = self.evaluate(node.value, env)
            for target in node.targets:
                self.bind(target, value, env)
            return None
        if isinstance(node, ast.Expr):
            self.evaluate(node.value, env)
            return None
        if isinstance(node, ast.If):
            branch = node.body if self.truth(self.evaluate(node.test, env), node) else node.orelse
            return self.exec_body(branch, env)
        if isinstance(node, ast.For):
            iterable = self.evaluate(node.iter, env)
            if not isinstance(iterable, (list, tuple)):
                _reject(node, "0302", "a `for` iterates a list or tuple")
            for item in iterable:
                self.bind(node.target, item, env)
                result = self.exec_body(node.body, env)
                if result is not None:
                    return result
            return None
        if isinstance(node, ast.Return):
            return ("return", None if node.value is None else self.evaluate(node.value, env))
        if isinstance(node, ast.Pass):
            return None
        _reject(node, "0303", f"`{type(node).__name__}` is not an allowed statement")

    def bind(self, target, value, env):
        if isinstance(target, ast.Name):
            env[target.id] = value
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            if not isinstance(value, (list, tuple)) or len(value) != len(target.elts):
                _reject(target, "0304", "unpacking needs a sequence of matching length")
            for element, item in zip(target.elts, value):
                self.bind(element, item, env)
            return
        _reject(target, "0305", "assignment targets are names and tuples of names")

    def truth(self, value, node) -> bool:
        if isinstance(value, (bool, int, str, list, tuple, dict)) or value is None:
            return bool(value)
        _reject(node, "0306", "only plain values are truth-tested")

    # -- expressions ----------------------------------------------------
    def evaluate(self, node, env):
        self.step(node)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (str, int, bool)) or node.value is None:
                return node.value
            _reject(node, "0307", f"{type(node.value).__name__} literals are not allowed")
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            _reject(node, "0308", f"{node.id!r} is not defined")
        if isinstance(node, ast.List):
            return [self.evaluate(e, env) for e in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self.evaluate(e, env) for e in node.elts)
        if isinstance(node, ast.Dict):
            return {
                self.evaluate(k, env): self.evaluate(v, env)
                for k, v in zip(node.keys, node.values)
            }
        if isinstance(node, ast.Attribute):
            owner = self.evaluate(node.value, env)
            allowed = _API_METHODS.get(type(owner).__name__)
            if allowed is None:
                _reject(
                    node,
                    "0309",
                    f"attribute access is not available on "
                    f"{type(owner).__name__}; only the builder and the handles "
                    "it returns have methods",
                    fixit="the builder API is the whole surface a design has",
                )
            if node.attr not in allowed:
                _reject(
                    node,
                    "0310",
                    f"no method {node.attr!r} here; this object offers "
                    + ", ".join(sorted(allowed)),
                )
            return _BoundMethod(getattr(owner, node.attr), node)
        if isinstance(node, ast.Call):
            return self.call(node, env)
        if isinstance(node, ast.UnaryOp):
            operand = self.evaluate(node.operand, env)
            if isinstance(node.op, ast.Not):
                return not self.truth(operand, node)
            if isinstance(node.op, ast.USub) and isinstance(operand, int):
                return -operand
            _reject(node, "0310", "unsupported unary operator")
        if isinstance(node, ast.BinOp):
            left, right = self.evaluate(node.left, env), self.evaluate(node.right, env)
            return self.binop(node, left, right)
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1:
                _reject(node, "0311", "chained comparisons are not allowed")
            left, right = self.evaluate(node.left, env), self.evaluate(node.comparators[0], env)
            return self.compare(node.ops[0], left, right, node)
        if isinstance(node, ast.BoolOp):
            values = [self.evaluate(v, env) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(self.truth(v, node) for v in values)
            return any(self.truth(v, node) for v in values)
        if isinstance(node, ast.IfExp):
            chosen = node.body if self.truth(self.evaluate(node.test, env), node) else node.orelse
            return self.evaluate(chosen, env)
        if isinstance(node, ast.Subscript):
            owner = self.evaluate(node.value, env)
            index = self.evaluate(node.slice, env)
            if not isinstance(owner, (list, tuple, dict)):
                _reject(node, "0312", "only lists, tuples and dicts are indexable")
            try:
                return owner[index]
            except (KeyError, IndexError, TypeError):
                _reject(node, "0313", "index is out of range or of the wrong type")
        _reject(node, "0314", f"`{type(node).__name__}` is not an allowed expression")

    def bounded(self, node, value):
        """Reject a value the step budget would not have noticed building.

        STEP_BUDGET counts node visits, and fourteen visits can allocate a
        gigabyte: `big = range(5000000)` materialises a list. Size is charged
        here so "elaboration is bounded" is about work and not only about
        syntax.
        """
        if len(value) > MAX_COLLECTION:
            _reject(
                node,
                "0321",
                f"value would hold {len(value)} elements, over the "
                f"{MAX_COLLECTION} limit",
                fixit="elaboration is bounded in size as well as in steps",
            )
        return value

    def binop(self, node, left, right):
        operator = node.op
        if isinstance(operator, ast.Add):
            if isinstance(left, str) and isinstance(right, str):
                return self.bounded(node, left + right)
            if isinstance(left, list) and isinstance(right, list):
                return self.bounded(node, left + right)
            if isinstance(left, int) and isinstance(right, int):
                return left + right
        if isinstance(left, int) and isinstance(right, int):
            if isinstance(operator, ast.Sub):
                return left - right
            if isinstance(operator, ast.Mult):
                return left * right
            if isinstance(operator, ast.FloorDiv) and right != 0:
                return left // right
            if isinstance(operator, ast.Mod) and right != 0:
                return left % right
        if isinstance(operator, ast.Mult) and isinstance(right, int):
            if isinstance(left, (str, list)):
                if right > MAX_COLLECTION:
                    _reject(node, "0321", f"result would exceed {MAX_COLLECTION} elements")
                return self.bounded(node, left * right)
        _reject(node, "0315", "unsupported operand types for this operator")

    def compare(self, operator, left, right, node):
        if isinstance(operator, ast.Eq):
            return left == right
        if isinstance(operator, ast.NotEq):
            return left != right
        if isinstance(operator, ast.In):
            return left in right if isinstance(right, (list, tuple, dict, str)) else False
        if isinstance(operator, ast.NotIn):
            return left not in right if isinstance(right, (list, tuple, dict, str)) else True
        if isinstance(left, int) and isinstance(right, int):
            for op_type, fn in (
                (ast.Lt, lambda a, b: a < b),
                (ast.LtE, lambda a, b: a <= b),
                (ast.Gt, lambda a, b: a > b),
                (ast.GtE, lambda a, b: a >= b),
            ):
                if isinstance(operator, op_type):
                    return fn(left, right)
        _reject(node, "0316", "unsupported comparison")

    def call(self, node, env):
        arguments = [self.evaluate(a, env) for a in node.args]
        keywords = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                _reject(node, "0317", "`**kwargs` unpacking is not allowed")
            keywords[keyword.arg] = self.evaluate(keyword.value, env)

        target = self.evaluate(node.func, env)

        if isinstance(target, _BoundMethod):
            return target._fn(*arguments, node=node, **keywords)

        if isinstance(target, _FunctionValue):
            names = [a.arg for a in target.node.args.args]
            if len(arguments) != len(names) or keywords:
                _reject(node, "0318", f"{target.name}() takes {len(names)} positional argument(s)")
            # Counted at runtime as well as statically. The static call graph
            # only sees a cycle routed through a bare function name; a
            # function passed as an argument and called through the parameter
            # is invisible to it, and used to recurse until the interpreter's
            # own stack gave out - which the docstring said could not happen.
            self.depth += 1
            if self.depth > MAX_CALL_DEPTH:
                _reject(
                    node,
                    "0320",
                    f"call depth exceeded {MAX_CALL_DEPTH}",
                    fixit="elaboration must terminate (L1); this is a recursion "
                    "the static call-graph check could not see",
                )
            local = dict(env)
            local.update(dict(zip(names, arguments)))
            try:
                result = self.exec_body(target.node.body, local)
            finally:
                self.depth -= 1
            return result[1] if isinstance(result, tuple) else None

        if target in self.builtins:
            return target(*arguments, **keywords)

        _reject(node, "0319", "this expression is not callable")


def _builtins():
    """The whole builtin surface. Anything absent is simply not defined."""
    def _range(*bounds):
        values = range(*bounds)
        if len(values) > MAX_COLLECTION:
            raise StarlarkError(
                [
                    Diag(
                        code=f"{CODE_PREFIX}0321",
                        message=(
                            f"range() of {len(values)} exceeds the "
                            f"{MAX_COLLECTION} element limit"
                        ),
                        params={"length": len(values)},
                    )
                ]
            )
        return list(values)

    return {
        "design": lambda *modules: _DesignMarker(list(modules)),
        "len": lambda value: len(value),
        "range": _range,
        "str": lambda value: str(value),
        "True": True,
        "False": False,
        "None": None,
    }


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------


def _literal(value: Value) -> str:
    if value.tag == "q":
        return '"' + value.quantity.text + '"'
    if value.tag == "s":
        return '"' + value.text + '"'
    if value.tag == "i":
        return str(value.number)
    return "True" if value.flag else "False"


def _keywords(values: dict) -> str:
    return ", ".join(f"{name}={_literal(values[name])}" for name in sorted(values))


def _instance_lines(inst: Instance, infer: bool) -> list[str]:
    call = "sub" if inst.kind == "module" else "part"
    definition = inst.definition if inst.kind == "module" else f'"{inst.definition}"'
    arguments = _keywords(inst.parameters)
    head = f'{inst.name} = m.{call}("{inst.name}", {definition}'
    head += (", " + arguments if arguments else "") + ")"
    lines = [head]

    if inst.kind == "component" and not (infer and library.inferable_ports(inst)):
        supplied = library.LIBRARY.get(inst.definition)
        if infer and not inst.ports and supplied is not None and supplied.ports:
            raise ValueError(
                f"{inst.name}: is portless but the library gives "
                f"{inst.definition} pins, so `inferred` cannot say 'no pins here'."
            )
        if inst.ports:
            specs = ", ".join(
                "(" + ", ".join(
                    ['"' + port.name + '"', '"' + port.role + '"']
                    + (
                        ["[" + ", ".join('"' + d + '"' for d in port.pin_numbers) + "]"]
                        if port.pin_numbers
                        else []
                    )
                ) + ")"
                for port in inst.ports
            )
            lines.append(f"{inst.name}.pins({specs})")

    if inst.part is not None:
        skip = library.inferable_constraints(inst) if infer else set()
        names = sorted(set(inst.part.constraints) - skip)
        arguments = []
        if inst.part.lockfile_key:
            arguments.append('"' + inst.part.lockfile_key + '"')
        arguments.extend(
            f"{name}={_literal(inst.part.constraints[name])}" for name in names
        )
        lines.append(f"{inst.name}.part({', '.join(arguments)})")

    if not (infer and library.inferable_hardware(inst)):
        definition = library.LIBRARY.get(inst.definition)
        flags = "".join(
            f", {flag}={'True' if getattr(inst, flag) else 'False'}"
            for flag in ("exclude_from_bom", "board_only")
            if getattr(inst, flag)
            or (definition is not None and getattr(definition, flag))
        )
        if inst.hardware_kind:
            lines.append(f'{inst.name}.hardware("{inst.hardware_kind}"{flags})')
        elif flags:
            lines.append(f"{inst.name}.fab({flags.lstrip(', ')})")
    if inst.dnp:
        lines.append(f"{inst.name}.dnp()")
    return lines


def render(model: DesignModel, variant: str = "explicit") -> str:
    if variant not in VARIANTS:
        raise ValueError(
            f"the Starlark baseline has no {variant!r} variant; it offers "
            + ", ".join(VARIANTS)
            + ". Python has no columnar sub-syntax to compare L6 against, and "
            "inventing one to report a number for would be measuring a "
            "construct nobody proposed."
        )
    infer, _ = variant_flags(variant)
    out: list[str] = []

    for module in module_order(model):
        out.append(f"def {module.name}(m):")
        body: list[str] = []
        for port in module.ports:
            body.append(f'm.port("{port.name}", "{port.role}")')
        for inst in module.instances:
            body.extend(_instance_lines(inst, infer))
        for net in module.nets:
            members = ", ".join('"' + member + '"' for member in net.members)
            if net.name:
                attributes = "".join(
                    f', {name}="{getattr(net, name)}"'
                    for name in ("ground_domain", "voltage_domain")
                    if getattr(net, name)
                )
                body.append(f'm.net("{net.name}", {members}{attributes})')
            elif len(net.members) == 1:
                body.append(f"m.isolated({members})")
            else:
                body.append(f"m.link({members})")
        if module.name == model.root_module:
            for assertion in model.assertions:
                bounds = "".join(
                    f', {key}="{value}"'
                    for key, value in (
                        ("min", assertion.minimum),
                        ("max", assertion.maximum),
                    )
                    if value is not None
                )
                body.append(
                    f'm.check("{assertion.name}", "{assertion.tier}", '
                    f'"{assertion.measurement}", "{assertion.subject}", '
                    f'unit="{assertion.unit}"{bounds})'
                )
        out.extend("    " + line for line in body)
        out.append("")

    names = ", ".join(module.name for module in module_order(model))
    out.append(f"DESIGN = design({names})")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# Parse
# --------------------------------------------------------------------------


def parse(source: str, variant: str = "explicit") -> DesignModel:
    if variant not in VARIANTS:
        raise ValueError(f"the Starlark baseline has no {variant!r} variant")
    infer, _ = variant_flags(variant)

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ParseFailure(
            [
                Diag(
                    code=f"{CODE_PREFIX}0001",
                    message=f"Python syntax error: {exc.msg}",
                    span=Span(exc.lineno or 1, exc.offset or 1, 0),
                    params={"detail": exc.msg},
                )
            ]
        ) from None

    try:
        functions = _check_restrictions(tree)
        evaluator = _Evaluator(functions)
        env = _builtins()
        evaluator.builtins = {v for v in env.values() if callable(v)}
        evaluator.exec_body(tree.body, env)

        marker = env.get("DESIGN")
        if not isinstance(marker, _DesignMarker):
            _reject(
                tree.body[-1] if tree.body else tree,
                "0401",
                "the file must end with `DESIGN = design(<module>, ...)`",
                fixit="design() names every module function in the file",
            )

        builders = []
        assertions: list[Assertion] = []
        per_module: dict[str, list[Assertion]] = {}
        for function in marker.modules:
            if not isinstance(function, _FunctionValue):
                _reject(tree, "0402", "design() takes module functions")
            builder = _ModuleBuilder(function.name)
            evaluator.call_module(function, builder)
            builders.append(builder)
            per_module[function.name] = builder.assertions
            assertions.extend(builder.assertions)
    except StarlarkError as exc:
        raise ParseFailure(exc.diagnostics) from None
    except ParseFailure:
        raise
    except RecursionError:
        raise ParseFailure(
            [
                Diag(
                    code=f"{CODE_PREFIX}0322",
                    message="evaluation exhausted the interpreter stack",
                    params={},
                )
            ]
        ) from None
    except Exception as exc:  # noqa: BLE001
        # A LAST RESORT, and it exists because of a real failure: the
        # evaluator injected `node=` into every attribute-resolved callable,
        # so an ordinary Python method call raised a bare TypeError out of
        # `parse`. eval/rhoform_eval/protocol.py calls the gate with no handler
        # around it, so that exception did not become a scored failure - it
        # aborted the whole AC5 run and discarded every trial in it. Whatever
        # else goes wrong in here must come out as a diagnostic.
        raise ParseFailure(
            [
                Diag(
                    code=f"{CODE_PREFIX}0999",
                    message=(
                        f"the prototype evaluator failed unexpectedly: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    params={"exception": type(exc).__name__},
                )
            ]
        ) from None

    from .base import Cursor
    from ..layout import Token

    cursor = Cursor([Token("EOF", "", 1, 1, 0)], CODE_PREFIX)
    return build_model(
        cursor=cursor,
        builders=builders,
        assertions=assertions,
        root_assertions=per_module,
        infer=infer,
        code_prefix=CODE_PREFIX,
    )


def _call_module(self, function: _FunctionValue, builder: _ModuleBuilder) -> None:
    names = [a.arg for a in function.node.args.args]
    if len(names) != 1:
        _reject(function.node, "0403", "a module function takes exactly one argument")
    local = dict(_builtins())
    self.builtins |= {v for v in local.values() if callable(v)}
    for name, node in self.functions.items():
        local[name] = _FunctionValue(node)
    local[names[0]] = builder
    self.exec_body(function.node.body, local)


_Evaluator.call_module = _call_module


def language_card() -> str:
    return _LANGUAGE_CARD


_LANGUAGE_CARD = '''\
# Rhoform Starlark baseline - language card

Designs are written in a restricted Python subset (Starlark-shaped) against a
builder API. Each module is a function taking the builder `m`. The file ends
by naming its modules.

## Restrictions

No import, while, class, lambda, comprehension, global/nonlocal, try/with/
raise, f-string, walrus, `*args` unpacking, decorators, type parameters, or
default arguments. Attribute access works ONLY on the builder `m` and the
handles it returns, and only for the methods listed here - strings, lists and
dicts have no methods.
Recursion is rejected statically. Evaluation is bounded by a step budget.
Allowed: def, if, bounded for over a list, assignment, calls, arithmetic on
whole numbers, string and list concatenation, comparisons, indexing.

## Modules

    def Blinker555(m):
        m.port("ctl", "input")
        ...

    DESIGN = design(LedIndicator, Blinker555)

## Instances

    r_a = m.part("r_a", "rhoform.lib.passive.Resistor", resistance="100kohm +/- 1%")
    r_a.pins(("a", "passive"), ("b", "passive"))
    r_a.part(package="axial_0207", power_rating="0.25W")

    timer = m.part("timer", "rhoform.lib.timer.Ne555")
    timer.part("timer.555/ti-NE555P@2", function="timer_555")

    indicator = m.sub("indicator", LedIndicator, color="red")

    mh1.hardware("mounting_hole", exclude_from_bom=True, board_only=True)
    tp.fab(exclude_from_bom=True)
    j4.dnp()

`m.part(name, definition, **parameters)` instantiates a component;
`m.sub(name, function, **parameters)` instantiates a module. `.pins()` takes
(name, role) or (name, role, [designators]). `.part()` takes an optional
lockfile key followed by constraints.

## Values

Every dimensioned value is a STRING, because Python has no unit literals:

    resistance="100kohm +/- 1%"    dimensioned
    package="0402"                 symbolic
    count=8                        whole number
    dnp=True                       flag

A string is read as a quantity when it parses as one. `"16V"` is therefore a
voltage even where a package code was meant.

Units: ohm kohm Mohm mohm, F mF uF nF pF, H mH uH nH, V kV mV uV,
A mA uA nA, W mW uW, Hz kHz MHz, s ms us ns, m mm um, degC.

## Connections

    m.net("VCC", "j_bat.pos", "r_a.a", voltage_domain="vbat_9v")
    m.link("ctl", "r_lim.a")

    m.isolated("tp1.p")

`m.net` names a net and lists its members; `m.link` chains endpoints into an
unnamed net; `m.isolated` declares a net with a single endpoint (L9b). An
endpoint is "instance.pin" or one of this module's ports.

## Assertions

    m.check("assert_freq", "dynamic", "frequency", "OUT",
            unit="Hz", min="0.932", max="1.051")

Pin roles: power_in, power_out, passive, bidirectional, open_drain,
open_collector, tri_state, input, output, nc. Hardware kinds: mounting_hole,
fiducial, artwork, test_point, grounded_mounting_hole.

## Reserved words

Python's own keywords, plus `design` and `DESIGN`. Names bound in a module
function are ordinary Python locals and may be anything else.
'''
