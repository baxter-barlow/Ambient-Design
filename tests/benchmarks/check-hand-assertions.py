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
    raise ValueError(
        f"unknown check {check!r}; declare one of interval-within, at-least, "
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
        recorded = str(assertion.get("status", "")).upper().startswith("PASS")
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
    # `inputs` is the field a reader edits. If it disagrees with `check_inputs`
    # on a value they share, the gate is re-deriving from a copy the reader
    # never sees — which is how the docstring's own attack kept passing.
    for assertion in assertions:
        declared = assertion.get("check_inputs") or {}
        recorded = assertion.get("inputs")
        if not isinstance(recorded, dict):
            recorded = {}
        shared = {v for v in declared.values() if isinstance(v, (int, float))}
        listed = {v for v in recorded.values() if isinstance(v, (int, float))}
        missing = shared - listed
        if declared and recorded and missing:
            problems.append(
                f"{label}/{assertion.get('id', '?')}: check_inputs uses "
                f"{sorted(missing)}, which appear nowhere in the `inputs` block "
                "a reader edits. The two must agree, or the gate re-derives the "
                "verdict from a copy nobody maintains."
            )
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

    # WIRING, over the real entry point. Eight assertions because main() applies
    # MINIMUM_MECHANISED, and a wiring case that dodged the floor would not be
    # driving the shipped path.
    import contextlib, io, tempfile

    def drive(have, need):
        body = "assertions:\n" + "".join(
            f"  - id: a{i}\n    check: at-least\n"
            f"    check_inputs: {{have: {have}, need: {need}}}\n    status: PASS\n"
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
