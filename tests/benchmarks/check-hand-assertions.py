#!/usr/bin/env python3
"""Re-evaluate the hand-computed assertions of a deck-less benchmark.

Benchmark (c) has no ngspice deck by design — its gate is a hand-computed T10
power budget plus assertions A1..A10 — and `run-sim.sh` therefore skips it
entirely, so `check-assertions.py` never sees it. That left ten assertions the
file calls "the gating checks" read by no code at all: an auditor rewrote A3's
inputs to `{ldo_rating_a: 0.001, worst_rail_a: 99.0}`, leaving the expression
and `status: PASS` intact, and `make sim` stayed green. It is the same
"assertions.yaml was read by no code in the repository" condition that
check-assertions.py was written to close, still live for one of the three
benchmarks.

WHAT THIS CHECKS. Each assertion records `inputs`, a relation, and a `status`.
This recomputes the relation FROM the inputs and compares the verdict to the
recorded one. It cannot re-derive the inputs — those come from datasheets and
from power-tree.yaml, and checking them is a human job — but it does mean the
recorded PASS has to follow from the recorded numbers, so an input edited to an
absurd value stops agreeing with its own verdict.

Relations are matched on the `check:` key each assertion declares, not parsed
out of prose: a checker that guessed at English would fail open the first time
someone rephrased a line.

Exit codes: 0 pass, 1 an assertion whose verdict does not follow, 2 environment
failure.

    python3 tests/benchmarks/check-hand-assertions.py --self-test
    python3 tests/benchmarks/check-hand-assertions.py <benchmark-dir>
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class GateUnavailable(Exception):
    """The check could not be performed. Never reported as a pass."""


def _interval(value):
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return float(value[0]), float(value[1])
    raise ValueError(f"{value!r} is not a two-element interval")


def _leaf_numbers(mapping, prefix=""):
    """Every numeric leaf in `inputs`, keyed by dotted path."""
    out = {}
    if isinstance(mapping, dict):
        for k, v in mapping.items():
            out.update(_leaf_numbers(v, f"{prefix}{k}." if prefix == "" else f"{prefix}{k}."))
        return {k.rstrip("."): v for k, v in out.items()} if prefix else out
    return out


def _flatten(value, path, out):
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(v, f"{path}.{k}" if path else k, out)
    elif isinstance(value, (list, tuple)):
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
            out[path] = list(value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out[path] = value


def _resolve(inputs, name):
    flat = {}
    _flatten(inputs, "", flat)
    if name not in flat:
        raise KeyError(f"`inputs` has no numeric key {name!r} (has: {sorted(flat)})")
    return flat[name]


_ALLOWED = None


def evaluate_formula(expr, inputs):
    """Arithmetic over `inputs` keys only. No calls, no attributes, no names
    beyond the input keys themselves."""
    import ast
    flat = {}
    _flatten(inputs, "", flat)
    tree = ast.parse(expr, mode="eval")
    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            a, b = walk(node.left), walk(node.right)
            # Branch, do not build a dict: a dict literal evaluates ALL FOUR
            # operations, so `a ** b` overflowed on a plain multiply and the
            # gate crashed instead of reporting the finding it had found.
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                return a / b
            return a ** b
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = walk(node.operand)
            return v if isinstance(node.op, ast.UAdd) else -v
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in flat:
                raise ValueError(f"formula names {node.id!r}, which is not an input key")
            return float(flat[node.id])
        if isinstance(node, ast.Attribute):
            parts = []
            cur = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if not isinstance(cur, ast.Name):
                raise ValueError("unsupported expression")
            parts.append(cur.id)
            key = ".".join(reversed(parts))
            if key not in flat:
                raise ValueError(f"formula names {key!r}, which is not an input key")
            return float(flat[key])
        raise ValueError(f"unsupported expression element {type(node).__name__}")
    return walk(tree)


def evaluate(check, inputs):
    """Return (holds, explanation) for one declared relation."""
    if check == "interval-within":
        inner, outer = _interval(inputs["inner"]), _interval(inputs["outer"])
        holds = outer[0] <= inner[0] and inner[1] <= outer[1]
        return holds, f"[{inner[0]}, {inner[1]}] within [{outer[0]}, {outer[1]}]"
    if check == "at-least":
        have, need = float(inputs["have"]), float(inputs["need"])
        return have >= need, f"{have} >= {need}"
    if check == "at-most":
        have, limit = float(inputs["have"]), float(inputs["limit"])
        return have <= limit, f"{have} <= {limit}"
    if check == "sum-at-most":
        parts = [float(v) for v in inputs["parts"]]
        limit = float(inputs["limit"])
        return sum(parts) <= limit, f"sum({parts}) = {sum(parts):.6g} <= {limit}"
    if check == "at-least-all":
        have = float(inputs["have"])
        needs = [float(v) for v in inputs["needs"]]
        return all(have >= n for n in needs), f"{have} >= max({needs})"
    raise ValueError(
        f"unknown check {check!r}; declare one of interval-within, at-least, at-least-all, "
        "at-most, sum-at-most, or add it here with its arithmetic"
    )


# At least this many assertions must actually be evaluated. Without a floor,
# relabelling every `check:` as `not_mechanisable` reported "0 assertion(s)
# follow from their inputs" and exited 0 — the set that "cannot grow quietly"
# growing to everything.
MINIMUM_MECHANISED = 8


def check_spec(spec, label, problems, minimum=None):
    assertions = spec.get("assertions") or []
    if not assertions:
        problems.append(f"{label}: declares no assertions")
        return 0
    checked = 0
    unmechanised = 0
    for assertion in assertions:
        name = assertion.get("id") or assertion.get("name") or "<unnamed>"
        check = assertion.get("check")
        if check is None and assertion.get("not_mechanisable"):
            # Declared unmechanisable, with a stated reason. Counted and printed
            # so the set cannot grow quietly.
            print(f"hand-assert: not mechanisable: {label}/{name}: "
                  f"{assertion['not_mechanisable'].strip()}")
            unmechanised += 1
            continue
        if check is None:
            # Not yet machine-checkable. Reported, never skipped: an assertion
            # nothing evaluates is the condition this file exists to end.
            problems.append(
                f"{label}/{name}: declares no `check:` key, so its recorded "
                "verdict is re-derived by nothing. Add one of the declared "
                "relations, or state in the file why this assertion cannot be "
                "mechanised."
            )
            continue
        try:
            holds, shown = evaluate(check, assertion.get("check_inputs") or {})
        except (ValueError, KeyError, TypeError) as exc:
            problems.append(f"{label}/{name}: {exc}")
            continue
        checked += 1
        status = assertion.get("status")
        if status is None:
            # Absent status read as "not PASS", so a relation that does NOT hold
            # and records no verdict was silently accepted.
            problems.append(
                f"{label}/{name}: records no `status:`, so there is no verdict "
                "for the recomputed relation to agree or disagree with.")
            continue
        recorded = str(status).upper().startswith("PASS")
        if holds != recorded:
            problems.append(
                f"{label}/{name}: recorded status {assertion.get('status')!r} but "
                f"the inputs give {shown} -> {'PASS' if holds else 'FAIL'}. The "
                "verdict does not follow from the numbers beside it."
            )
    floor = MINIMUM_MECHANISED if minimum is None else minimum
    if checked < floor:
        problems.append(
            f"{label}: only {checked} of {len(assertions)} assertion(s) were "
            f"evaluated ({unmechanised} declared unmechanisable), below the "
            f"floor of {floor}. Lowering the floor is a deliberate "
            "decision; drifting under it is not."
        )
    # THE RECONCILIATION, rebuilt. It used to compare SETS OF NUMBERS between
    # `check_inputs` and `inputs`, which means (i) swapping the operands was
    # invisible -- one auditor asserted a 0.001 A LDO supplies a 99 A rail with
    # the gate green -- and (ii) it only required check_inputs SUBSET inputs, so
    # every input the operands did not happen to use could be set to physical
    # nonsense. Now each operand names the input key it comes from, and every
    # numeric input must be either used or declared ungated with a reason.
    for assertion in assertions:
        name = assertion.get("id") or assertion.get("name") or "<unnamed>"
        declared = assertion.get("check_inputs")
        if not declared:
            continue
        recorded = assertion.get("inputs")
        if not isinstance(recorded, dict):
            problems.append(
                f"{label}/{name}: has `check_inputs` but no `inputs` mapping to "
                "reconcile them against.")
            continue
        origin = assertion.get("check_inputs_from")
        formulas = assertion.get("check_inputs_derived") or {}
        if not isinstance(origin, dict):
            problems.append(
                f"{label}/{name}: declares no `check_inputs_from`, so its "
                "operands are a copy of the inputs that nothing reconciles. "
                "Name the `inputs` key each operand comes from.")
            continue
        used = set()
        for operand, value in declared.items():
            if operand in formulas:
                try:
                    got = evaluate_formula(formulas[operand], recorded)
                except (ValueError, KeyError, SyntaxError, ArithmeticError) as exc:
                    problems.append(f"{label}/{name}: {operand}: {exc}")
                    continue
                import ast as _ast
                for node in _ast.walk(_ast.parse(formulas[operand], mode="eval")):
                    if isinstance(node, _ast.Name):
                        used.add(node.id)
                    elif isinstance(node, _ast.Attribute):
                        parts, cur = [], node
                        while isinstance(cur, _ast.Attribute):
                            parts.append(cur.attr); cur = cur.value
                        if isinstance(cur, _ast.Name):
                            parts.append(cur.id); used.add(".".join(reversed(parts)))
                if abs(got - float(value)) > abs(float(value)) * 1e-3 + 1e-12:
                    problems.append(
                        f"{label}/{name}: operand {operand}={value} but its own "
                        f"formula over `inputs` gives {got:.6g}. The gated number "
                        "is not the number the inputs produce.")
                continue
            if operand not in origin:
                problems.append(
                    f"{label}/{name}: operand {operand!r} is not in "
                    "`check_inputs_from`, so nothing ties it to an input.")
                continue
            keys = origin[operand]
            keys = keys if isinstance(keys, list) else [keys]
            used.update(keys)
            try:
                resolved = [_resolve(recorded, k) for k in keys]
            except KeyError as exc:
                problems.append(f"{label}/{name}: {operand}: {exc}")
                continue
            got = resolved[0] if len(resolved) == 1 else resolved
            if isinstance(value, list):
                flatv = [float(v) for v in value]
                flatg = [float(v) for v in (got if isinstance(got, list) else [got])]
                if len(flatg) == 1 and isinstance(resolved[0], list):
                    flatg = [float(v) for v in resolved[0]]
                ok = len(flatv) == len(flatg) and all(
                    abs(a - b) <= abs(b) * 1e-9 + 1e-15 for a, b in zip(flatv, flatg))
            else:
                ok = (not isinstance(got, list)
                      and abs(float(value) - float(got)) <= abs(float(got)) * 1e-9 + 1e-15)
            if not ok:
                problems.append(
                    f"{label}/{name}: operand {operand}={value!r} does not equal "
                    f"`inputs.{'+'.join(map(str, keys))}`={got!r}. The gate is "
                    "re-deriving the verdict from a copy nobody maintains.")
        flat = {}
        _flatten(recorded, "", flat)
        ungated = assertion.get("inputs_not_gated") or {}
        orphans = sorted(set(flat) - used - set(ungated))
        if orphans:
            problems.append(
                f"{label}/{name}: numeric input(s) {orphans} feed no operand and "
                "are not listed in `inputs_not_gated`. An input nothing reads can "
                "be set to anything, which is how a 500 C ambient passed.")
        for key, reason in ungated.items():
            if key not in flat:
                problems.append(
                    f"{label}/{name}: `inputs_not_gated` names {key!r}, which is "
                    "not a numeric input.")
            elif not str(reason).strip():
                problems.append(
                    f"{label}/{name}: `inputs_not_gated[{key}]` states no reason.")
    return checked


def load_yaml(path):
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise GateUnavailable(
            "PyYAML is required; install the pin (python3 -m pip install pyyaml==6.0.2)."
        ) from exc
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GateUnavailable(f"{path} is not readable as YAML: {exc}") from exc


def self_test():
    cases = []

    def probe(assertion):
        # The arithmetic probes predate `check_inputs_from`; they exist to test
        # the RELATIONS, so the reconciliation wiring is synthesised for them
        # and tested separately by the three cases at the end of this list.
        if "check_inputs" in assertion and "inputs" not in assertion:
            ci = assertion["check_inputs"]
            assertion = dict(assertion,
                             inputs={f"in_{k}": v for k, v in ci.items()},
                             check_inputs_from={k: f"in_{k}" for k in ci})
        problems = []
        check_spec({"assertions": [assertion]}, "probe", problems, minimum=0)
        return problems

    cases.append(("a true interval containment passes", not probe(
        {"id": "a", "check": "interval-within",
         "check_inputs": {"inner": [3.234, 3.366], "outer": [3.0, 3.6]}, "status": "PASS"})))
    cases.append(("a false containment recorded PASS is caught", any(
        "does not follow" in p for p in probe(
            {"id": "a", "check": "interval-within",
             "check_inputs": {"inner": [2.0, 4.0], "outer": [3.0, 3.6]}, "status": "PASS"}))))
    cases.append(("the auditor's A3 mutation is caught", any(
        "does not follow" in p for p in probe(
            {"id": "a3", "check": "at-least",
             "check_inputs": {"have": 0.001, "need": 99.0}, "status": "PASS"}))))
    cases.append(("a true at-most passes", not probe(
        {"id": "a", "check": "at-most",
         "check_inputs": {"have": 0.3916, "limit": 0.5}, "status": "PASS"})))
    cases.append(("a false at-most recorded PASS is caught", any(
        "does not follow" in p for p in probe(
            {"id": "a", "check": "at-most",
             "check_inputs": {"have": 9.0, "limit": 0.5}, "status": "PASS"}))))
    cases.append(("sum-at-most adds its parts", any(
        "does not follow" in p for p in probe(
            {"id": "a", "check": "sum-at-most",
             "check_inputs": {"parts": [4.7, 4.7, 0.1], "limit": 9.0}, "status": "PASS"}))))
    cases.append(("an assertion with no check key is reported", any(
        "declares no `check:`" in p for p in probe(
            {"id": "a", "check_inputs": {}, "status": "PASS"}))))
    cases.append(("an unknown relation is rejected, not assumed true", any(
        "unknown check" in p for p in probe(
            {"id": "a", "check": "vibes", "check_inputs": {}, "status": "PASS"}))))
    cases.append(("a recorded FAIL that really fails is consistent", not probe(
        {"id": "a", "check": "at-least",
         "check_inputs": {"have": 1.0, "need": 2.0}, "status": "FAIL"})))

    # THE RECONCILIATION CONTRACT itself, which the arithmetic probes above
    # synthesise past. These are the two attacks both round-5 auditors landed.
    cases.append(("an operand tied to no input key is caught", any(
        "check_inputs_from" in p for p in probe(
            {"id": "a", "check": "at-least", "check_inputs": {"have": 1.0, "need": 0.5},
             "inputs": {"rating_a": 1.0, "need_a": 0.5}, "status": "PASS"}))))
    cases.append(("swapped operands are caught even though the numbers all appear", any(
        "does not equal" in p for p in probe(
            {"id": "a", "check": "at-least", "check_inputs": {"have": 99.0, "need": 0.001},
             "check_inputs_from": {"have": "rating_a", "need": "need_a"},
             "inputs": {"rating_a": 0.001, "need_a": 99.0}, "status": "PASS"}))))
    cases.append(("an input feeding no operand is caught", any(
        "feed no operand" in p for p in probe(
            {"id": "a", "check": "at-least", "check_inputs": {"have": 1.0, "need": 0.5},
             "check_inputs_from": {"have": "rating_a", "need": "need_a"},
             "inputs": {"rating_a": 1.0, "need_a": 0.5, "ta_c": 500}, "status": "PASS"}))))
    cases.append(("a derived operand that the inputs do not produce is caught", any(
        "not the number the inputs produce" in p for p in probe(
            {"id": "a", "check": "at-least", "check_inputs": {"have": 3.8, "need": 3.5618},
             "check_inputs_from": {"have": "v_in"},
             "check_inputs_derived": {"need": "v_out + k * i"},
             "inputs": {"v_in": 3.8, "v_out": 99.0, "k": 0.5, "i": 0.3916},
             "status": "PASS"}))))
    cases.append(("an ungated input with no stated reason is caught", any(
        "states no reason" in p for p in probe(
            {"id": "a", "check": "at-least", "check_inputs": {"have": 1.0, "need": 0.5},
             "check_inputs_from": {"have": "rating_a", "need": "need_a"},
             "inputs": {"rating_a": 1.0, "need_a": 0.5, "spare": 1.0},
             "inputs_not_gated": {"spare": ""}, "status": "PASS"}))))

    # WIRING, over the real entry point. Eight assertions because main() applies
    # MINIMUM_MECHANISED, and a wiring case that dodged the floor would not be
    # driving the shipped path.
    import contextlib, io, tempfile

    def drive(have, need):
        body = "assertions:\n" + "".join(
            f"  - id: a{i}\n    check: at-least\n"
            f"    check_inputs: {{have: {have}, need: {need}}}\n"
            f"    check_inputs_from: {{have: h, need: n}}\n"
            f"    inputs: {{h: {have}, n: {need}}}\n    status: PASS\n"
            for i in range(8))
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp)
            (case / "assertions.yaml").write_text(body, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return main([str(case)])

    planted, clean = drive(0.001, 99.0), drive(99.0, 0.001)
    cases.append(("main() exits 1 when a verdict does not follow", planted == 1))
    cases.append(("main() exits 0 when every verdict follows", clean == 0))

    failures = 0
    for name, ok in cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        print(f"hand-assert: SELF-TEST FAILED: {failures} case(s)", file=sys.stderr)
        return 1
    print(f"hand-assert: self-test PASS: {len(cases)} cases.")
    return 0


def main(argv):
    if argv and argv[0] == "--self-test":
        return self_test()
    if len(argv) != 1:
        print("usage: check-hand-assertions.py <benchmark-dir>", file=sys.stderr)
        return 2
    case_dir = Path(argv[0])
    spec_path = case_dir / "assertions.yaml"
    if not spec_path.is_file():
        print(f"hand-assert: FAIL: {case_dir.name} has no assertions.yaml", file=sys.stderr)
        return 1
    problems = []
    try:
        checked = check_spec(load_yaml(spec_path), case_dir.name, problems)
    except GateUnavailable as exc:
        print(f"hand-assert: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    if problems:
        print(f"hand-assert: FAIL: {case_dir.name}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"hand-assert: PASS: {case_dir.name}: {checked} assertion(s) follow from their inputs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
