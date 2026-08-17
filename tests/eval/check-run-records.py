#!/usr/bin/env python3
"""Cross-field consistency for recorded AC5 runs.

`run-result.schema.json` proves a run record has the right SHAPE. It cannot
prove the record is internally consistent, because JSON Schema has no
arithmetic — and an audit built eleven dishonest records from the committed
`demo.run.json` and validated every one of them with zero errors:

  - `total: 64000` against `limit: 12000` with `passed: true` — the schema's own
    `$comment` claims this is closed, and the rule it added only requires
    `headroom >= 0`, so `headroom: 0` walks straight through;
  - `ac5_gate.passed: true` at 2/10, with a correct Wilson interval;
  - an `ac5_gate` reporting 8/10 while the arm it names records 1 success;
  - 99 successes in 10 trials;
  - `flip_criterion_not_met` declared with power 0.02, which is the exact
    failure eval/README.md says "was a real defect caught in review";
  - an `authoritative` AC5a PASS whose own `a4_context_budget.passed` is false.

Two of those reopen defects that negative controls e07 and e09 exist to prove
are closed. This file is where the arithmetic lives, on the same
schema-proves-shape / script-proves-meaning split the part linter and the IR
hash gate already use.

Every `*.run.json` under eval/examples/ is checked, EXCEPT the negative
controls: those are deliberately invalid and the schema gate owns them.

Exit codes: 0 pass, 1 an inconsistent record, 2 environment failure.

    python3 tests/eval/check-run-records.py --self-test
    python3 tests/eval/check-run-records.py
"""

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "eval" / "examples"

# AC5a's bar, as a Fraction so the boundary is exact. Duplicated from the
# harness deliberately: a gate that imports the thing it checks cannot catch
# that thing changing.
AC5A_THRESHOLD = Fraction(7, 10)

# `kind` values that mean "a real model / gate / tokenizer produced this".
# An ALLOWLIST, not a denylist: the harness and the schema both used
# ("replay", "scripted", "stub") as a denylist, so an unrecognised kind
# defeated both at once.
LIVE_MODEL_KINDS = {"anthropic", "openai", "live"}
LIVE_GATE_KINDS = {"command", "compiler"}


def problems_for(record, label):
    out = []

    def bad(message):
        out.append(f"{label}: {message}")

    budget = record.get("a4_context_budget")
    if isinstance(budget, dict):
        total, limit = budget.get("total"), budget.get("limit")
        headroom, passed = budget.get("headroom"), budget.get("passed")
        if isinstance(total, int) and isinstance(limit, int):
            if isinstance(headroom, int) and headroom != limit - total:
                bad(f"a4_context_budget.headroom is {headroom}, but limit - total "
                    f"is {limit - total}. The recorded headroom does not describe "
                    "the recorded numbers.")
            if passed is not None and passed != (total <= limit):
                bad(f"a4_context_budget says passed={passed} at total={total} "
                    f"against limit={limit}. A budget cannot pass while over it.")

    arms = record.get("arms") if isinstance(record.get("arms"), dict) else {}
    for name, arm in arms.items():
        successes, trials = arm.get("successes"), arm.get("trials")
        if isinstance(successes, int) and isinstance(trials, int):
            if trials < 0 or successes < 0:
                bad(f"arm {name!r} records negative counts")
            elif successes > trials:
                bad(f"arm {name!r} records {successes} successes in {trials} "
                    "trials, which is impossible")

    gate = record.get("ac5_gate")
    if isinstance(gate, dict):
        successes, trials = gate.get("successes"), gate.get("trials")
        passed, arm_name = gate.get("passed"), gate.get("arm")
        if isinstance(successes, int) and isinstance(trials, int) and trials > 0:
            if successes > trials:
                bad(f"ac5_gate records {successes} successes in {trials} trials")
            else:
                expected = Fraction(successes, trials) >= AC5A_THRESHOLD
                if passed is not None and passed != expected:
                    bad(f"ac5_gate says passed={passed} at {successes}/{trials}; "
                        f"AC5a's bar is {AC5A_THRESHOLD} so it should be {expected}. "
                        "A threshold recorded as a verdict must agree with the "
                        "counts recorded beside it.")
            arm = arms.get(arm_name)
            if isinstance(arm, dict):
                for field in ("successes", "trials"):
                    if isinstance(arm.get(field), int) and arm[field] != gate.get(field):
                        bad(f"ac5_gate.{field} is {gate.get(field)} but arm "
                            f"{arm_name!r} records {arm[field]}. The gate and the "
                            "data it claims to summarise disagree.")
            elif arm_name is not None and arms:
                bad(f"ac5_gate names arm {arm_name!r}, which this record has no data for")
        if gate.get("passed") and "wilson_95" not in gate:
            bad("ac5_gate passed without recording its Wilson interval")

    flip = record.get("flip_criterion")
    if isinstance(flip, dict):
        verdict = flip.get("verdict")
        declared = flip.get("minimum_effect_of_interest")
        power = flip.get("power_against_declared_effect")
        threshold = flip.get("adequate_power_threshold")
        if verdict == "flip_criterion_not_met":
            if declared is None:
                bad("verdict is flip_criterion_not_met with no declared minimum "
                    "effect of interest; 'not met' is a claim about power, and "
                    "without a declared effect there is none to report")
            elif (isinstance(power, (int, float)) and isinstance(threshold, (int, float))
                  and power < threshold):
                bad(f"verdict is flip_criterion_not_met with power "
                    f"{power} against a declared effect, below the "
                    f"{threshold} adequacy threshold. That is an underpowered "
                    "run reported as evidence of no effect.")
        if flip.get("paired"):
            b, c = flip.get("discordant_b"), flip.get("discordant_c")
            primary, baseline = arms.get(flip.get("primary_arm")), arms.get(flip.get("baseline_arm"))
            if (isinstance(b, int) and isinstance(c, int)
                    and isinstance(primary, dict) and isinstance(baseline, dict)
                    and isinstance(primary.get("successes"), int)
                    and isinstance(baseline.get("successes"), int)):
                # In a paired design every trial is one item under both arms, so
                # the success difference IS the discordant difference. Nothing
                # checked this, and the harness would certify "flip criterion
                # MET" from 10/10 vs 0/10 with b=0, c=10 — the arm that won
                # every trial reported as statistically below the baseline.
                if primary["successes"] - baseline["successes"] != b - c:
                    bad(f"paired run: {primary['successes']} - "
                        f"{baseline['successes']} != b - c ({b} - {c}). In a "
                        "paired design those are the same number, so these "
                        "counts cannot have come from one run.")

    if record.get("authoritative"):
        reasons = record.get("non_authoritative_reasons") or []
        if reasons:
            bad(f"authoritative is true but {len(reasons)} non-authoritative "
                f"reason(s) are recorded: {reasons}")
        model_kind = (record.get("model") or {}).get("kind")
        if model_kind not in LIVE_MODEL_KINDS:
            bad(f"authoritative is true but model kind is {model_kind!r}, which is "
                f"not one of {sorted(LIVE_MODEL_KINDS)}")
        gate_kind = (record.get("gate") or {}).get("kind")
        if gate_kind not in LIVE_GATE_KINDS:
            bad(f"authoritative is true but gate kind is {gate_kind!r}, which is not "
                f"one of {sorted(LIVE_GATE_KINDS)}. README says authoritative is "
                "computed from the tokenizer, model AND gate identities; the gate "
                "identity was stored and never read.")
        tokenizer = ((record.get("a4_context_budget") or {}).get("tokenizer")
                     or record.get("tokenizer") or {})
        if tokenizer.get("gating") is False:
            bad(f"authoritative is true on a non-gating tokenizer "
                f"({tokenizer.get('name')!r})")
        if isinstance(budget, dict) and budget.get("passed") is False:
            bad("authoritative is true while its own A4 context budget failed")

    # Arms compared against each other must have been run under the same rules.
    semantics = {
        name: (arm.get("config") or {}).get("iteration_semantics")
        for name, arm in arms.items()
        if isinstance(arm, dict)
    }
    distinct = {value for value in semantics.values() if value is not None}
    if len(distinct) > 1:
        bad(f"arms were run under different iteration semantics ({sorted(distinct)}) "
            "and are still compared. Recording the reading is necessary and not "
            "sufficient: AMB-119 is unsettled, and the two readings differ by a "
            "third of the repair budget.")
    budgets = {
        (arm.get("config") or {}).get("token_budget")
        for arm in arms.values() if isinstance(arm, dict)
    } - {None}
    if len(budgets) > 1:
        bad(f"arms were run under different token budgets ({sorted(budgets)}) and "
            "are still compared")
    benches = {
        (arm.get("config") or {}).get("benchmark")
        for arm in arms.values() if isinstance(arm, dict)
    } - {None}
    if len(benches) > 1:
        bad(f"arms were run against different benchmarks ({sorted(benches)}) and "
            "are still compared")
    return out


def self_test():
    base = {
        "a4_context_budget": {"total": 58, "limit": 12000, "headroom": 11942, "passed": True},
        "arms": {"a": {"successes": 8, "trials": 10}, "b": {"successes": 6, "trials": 10}},
        "ac5_gate": {"arm": "a", "successes": 8, "trials": 10, "passed": True,
                     "wilson_95": [0.49, 0.94]},
        "flip_criterion": {"verdict": "inconclusive", "paired": False},
        "authoritative": False,
    }

    def with_(**over):
        record = json.loads(json.dumps(base))
        for path, value in over.items():
            node, *rest = path.split("__")
            if rest:
                record.setdefault(node, {})
                target = record[node]
                for key in rest[:-1]:
                    target = target.setdefault(key, {})
                target[rest[-1]] = value
            else:
                record[node] = value
        return record

    cases = [
        ("a consistent record reports no problem", not problems_for(base, "x")),
        ("a budget that passed while over its limit is caught", any(
            "cannot pass while over" in p for p in problems_for(
                with_(a4_context_budget__total=64000, a4_context_budget__headroom=0), "x"))),
        ("headroom that does not describe the numbers is caught", any(
            "does not describe" in p for p in problems_for(
                with_(a4_context_budget__headroom=999), "x"))),
        ("a gate passing below the bar is caught", any(
            "should be False" in p for p in problems_for(
                with_(ac5_gate__successes=2), "x"))),
        ("a gate failing at the bar is caught", any(
            "should be True" in p for p in problems_for(
                with_(ac5_gate__successes=7, ac5_gate__passed=False), "x"))),
        ("the 7/10 boundary is exact", not any(
            "ac5_gate says" in p for p in problems_for(with_(ac5_gate__successes=7), "x"))),
        ("more successes than trials is caught", any(
            "impossible" in p for p in problems_for(
                with_(arms={"a": {"successes": 99, "trials": 10}}), "x"))),
        ("a gate disagreeing with the arm it names is caught", any(
            "disagree" in p for p in problems_for(
                with_(arms={"a": {"successes": 1, "trials": 10},
                            "b": {"successes": 6, "trials": 10}}), "x"))),
        ("a passing gate with no Wilson interval is caught", any(
            "Wilson" in p for p in problems_for(
                with_(ac5_gate={"arm": "a", "successes": 8, "trials": 10,
                                "passed": True}), "x"))),
        ("'not met' with no declared effect is caught", any(
            "no declared minimum" in p for p in problems_for(
                with_(flip_criterion={"verdict": "flip_criterion_not_met",
                                      "minimum_effect_of_interest": None}), "x"))),
        ("'not met' on an underpowered run is caught", any(
            "underpowered" in p for p in problems_for(
                with_(flip_criterion={"verdict": "flip_criterion_not_met",
                                      "minimum_effect_of_interest": 0.2,
                                      "power_against_declared_effect": 0.02,
                                      "adequate_power_threshold": 0.8}), "x"))),
        ("an impossible paired table is caught", any(
            "same number" in p for p in problems_for(
                with_(arms={"a": {"successes": 10, "trials": 10},
                            "b": {"successes": 0, "trials": 10}},
                      flip_criterion={"verdict": "flip_criterion_met", "paired": True,
                                      "primary_arm": "a", "baseline_arm": "b",
                                      "discordant_b": 0, "discordant_c": 10}), "x"))),
        ("authoritative on a replay gate is caught", any(
            "gate kind" in p for p in problems_for(
                with_(authoritative=True, model={"kind": "anthropic"},
                      gate={"kind": "replay"}), "x"))),
        ("authoritative on a mock model is caught", any(
            "model kind" in p for p in problems_for(
                with_(authoritative=True, model={"kind": "mock"},
                      gate={"kind": "command"}), "x"))),
        ("authoritative on a non-gating tokenizer is caught", any(
            "non-gating tokenizer" in p for p in problems_for(
                with_(authoritative=True, model={"kind": "anthropic"},
                      gate={"kind": "command"},
                      a4_context_budget__tokenizer={"gating": False, "name": "stub"}), "x"))),
        ("authoritative with a failed budget is caught", any(
            "own A4 context budget failed" in p for p in problems_for(
                with_(authoritative=True, model={"kind": "anthropic"},
                      gate={"kind": "command"}, a4_context_budget__passed=False), "x"))),
        ("authoritative with recorded reasons is caught", any(
            "non-authoritative reason" in p for p in problems_for(
                with_(authoritative=True, model={"kind": "anthropic"},
                      gate={"kind": "command"},
                      non_authoritative_reasons=["stub tokenizer"]), "x"))),
        ("arms under different iteration semantics are caught", any(
            "different iteration semantics" in p for p in problems_for(
                with_(arms={"a": {"successes": 8, "trials": 10,
                                  "config": {"iteration_semantics": "initial_plus_repairs"}},
                            "b": {"successes": 6, "trials": 10,
                                  "config": {"iteration_semantics": "total_write_check_cycles"}}}), "x"))),
        ("arms under different token budgets are caught", any(
            "different token budgets" in p for p in problems_for(
                with_(arms={"a": {"successes": 8, "trials": 10, "config": {"token_budget": 1000000}},
                            "b": {"successes": 6, "trials": 10, "config": {"token_budget": 150000}}}), "x"))),
        ("arms against different benchmarks are caught", any(
            "different benchmarks" in p for p in problems_for(
                with_(arms={"a": {"successes": 8, "trials": 10, "config": {"benchmark": "easy"}},
                            "b": {"successes": 6, "trials": 10, "config": {"benchmark": "hard"}}}), "x"))),
    ]

    failures = 0
    for name, ok in cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        print(f"run-records: SELF-TEST FAILED: {failures} case(s)", file=sys.stderr)
        return 1
    print(f"run-records: self-test PASS: {len(cases)} cases.")
    return 0


def main(argv):
    if argv and argv[0] == "--self-test":
        return self_test()
    if not EXAMPLES.is_dir():
        print("run-records: UNAVAILABLE: eval/examples/ does not exist", file=sys.stderr)
        return 2

    problems, checked = [], 0
    for path in sorted(EXAMPLES.rglob("*.run.json")):
        if "negative" in path.relative_to(EXAMPLES).parts[:-1]:
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.append(f"{path.relative_to(ROOT)}: does not parse: {exc}")
            continue
        checked += 1
        problems.extend(problems_for(record, str(path.relative_to(ROOT))))

    if not checked:
        print("run-records: FAIL: no run records found; a checker with nothing to "
              "check is indistinguishable from no checker.", file=sys.stderr)
        return 1
    if problems:
        print("run-records: FAIL:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"run-records: PASS: {checked} record(s) internally consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
