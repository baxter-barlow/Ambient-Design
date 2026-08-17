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

# AC5a reads "in >=7/10 independent trials". The rate rule generalises the
# threshold to other n, which is right — but it generalised DOWNWARD too, and
# `ac5_gate(1, 1)` recorded a PASS through both eval gates. One trial is not a
# measurement of a 70% success rate.
MINIMUM_AC5A_TRIALS = 10

# `kind` values that mean "a real model / gate / tokenizer produced this".
# An ALLOWLIST, not a denylist: the harness and the schema both used
# ("replay", "scripted", "stub") as a denylist, so an unrecognised kind
# defeated both at once.
LIVE_MODEL_KINDS = {"anthropic", "openai", "live"}
LIVE_GATE_KINDS = {"command", "compiler"}


def _arm_count(arm):
    """An arm's trial COUNT. `trials` is the list; `trial_count` is the number."""
    count = arm.get("trial_count")
    if isinstance(count, int):
        return count
    listed = arm.get("trials")
    return len(listed) if isinstance(listed, list) else None


def problems_for(record, label):
    out = []

    def bad(message):
        out.append(f"{label}: {message}")

    budget = record.get("a4_context_budget")
    if isinstance(budget, dict):
        total, limit = budget.get("total"), budget.get("limit")
        headroom, passed = budget.get("headroom"), budget.get("passed")
        # `breakdown` must account for `total`. The schema's own $comment says
        # the per-part breakdown is required "precisely because A4 exists to
        # stop the teaching payload migrating from the card into the skill and
        # out of sight" — and the migrating payload was the one thing unchecked,
        # so `{system_context: 27, task_prompt: 31, skill_payload: 243000}` under
        # `total: 58` passed.
        breakdown = budget.get("breakdown")
        if isinstance(breakdown, dict) and isinstance(total, int):
            parts = [v for v in breakdown.values() if isinstance(v, (int, float))]
            if not parts and total:
                bad(f"a4_context_budget.breakdown is empty while total is "
                    f"{total}. An empty breakdown accounts for nothing, and "
                    "the breakdown exists precisely to stop a payload hiding "
                    "outside the parts.")
            elif parts and abs(sum(parts) - total) > 0.5:
                bad(f"a4_context_budget.breakdown sums to {sum(parts):g} but "
                    f"total is {total}. The parts do not account for the whole, "
                    "which is exactly how a payload migrates out of sight.")
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
        # `trial_count` is the COUNT; `trials` is the list of trial records.
        # This file originally read `arm["trials"]` as an integer, which is
        # never true, so `isinstance(..., int)` was always False and this whole
        # block was dead — while its self-test, built from synthetic dicts
        # using the same wrong name, reported green. Eight forged records
        # passed. Hence `_arm_count`, and hence a self-test built from the
        # committed record instead of from my idea of its shape.
        successes, trials = arm.get("successes"), _arm_count(arm)
        if isinstance(successes, int) and isinstance(trials, int):
            if trials < 0 or successes < 0:
                bad(f"arm {name!r} records negative counts")
            elif successes > trials:
                bad(f"arm {name!r} records {successes} successes in {trials} "
                    "trials, which is impossible")
        # `successes` is a SUMMARY of `trials`, and nothing reconciled them, so
        # the AC5a verdict could be derived from a counter contradicting every
        # trial record beside it.
        listed_trials = arm.get("trials")
        if isinstance(listed_trials, list) and isinstance(successes, int):
            passed_count = sum(1 for x in listed_trials
                               if isinstance(x, dict) and x.get("passed") is True)
            if any(isinstance(x, dict) and "passed" in x for x in listed_trials) \
                    and passed_count != successes:
                bad(f"arm {name!r} records successes={successes} but "
                    f"{passed_count} of its {len(listed_trials)} trial record(s) "
                    "are marked passed")
        outcomes = arm.get("outcomes")
        if isinstance(outcomes, dict) and isinstance(successes, int):
            # ABSENT means zero, not "unchecked": `{"failed": 10}` beside
            # `successes: 8` is the contradiction, and reading a missing key as
            # None skipped exactly that case.
            recorded_pass = outcomes.get("passed", 0)
            total = sum(v for v in outcomes.values() if isinstance(v, int))
            count = _arm_count(arm)
            if isinstance(count, int) and total and total != count:
                bad(f"arm {name!r} outcomes sum to {total} but it records "
                    f"{count} trial(s)")
            if isinstance(recorded_pass, int) and recorded_pass != successes:
                bad(f"arm {name!r} records successes={successes} but its "
                    f"outcomes say passed={recorded_pass}")
        listed = arm.get("trials")
        if isinstance(listed, list) and isinstance(trials, int) and len(listed) != trials:
            bad(f"arm {name!r} declares trial_count={trials} but carries "
                f"{len(listed)} trial record(s)")

    gate = record.get("ac5_gate")
    if isinstance(gate, dict):
        successes, trials = gate.get("successes"), gate.get("trials")
        passed, arm_name = gate.get("passed"), gate.get("arm")
        if isinstance(trials, int) and trials < MINIMUM_AC5A_TRIALS and gate.get("passed"):
            bad(f"ac5_gate passed on {trials} trial(s), below AC5a's stated "
                f"{MINIMUM_AC5A_TRIALS}. The rate rule generalises the bar to "
                "larger n; it does not license a smaller sample.")
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
                # `ac5_gate.trials` IS an int; `arm.trials` is a list and the
                # count lives in `arm.trial_count`. Comparing the two by name
                # compared an int to a list and never fired.
                # NOT `label`: that is the enclosing parameter `bad()` closes
                # over, and shadowing it would relabel every later message.
                for field, gate_value, arm_value in (
                    ("successes", gate.get("successes"), arm.get("successes")),
                    ("trials", gate.get("trials"), _arm_count(arm)),
                ):
                    if isinstance(arm_value, int) and arm_value != gate_value:
                        bad(f"ac5_gate.{field} is {gate_value} but arm "
                            f"{arm_name!r} records {arm_value}. The gate and the "
                            "data it claims to summarise disagree.")
            elif arm_name is not None and arms:
                bad(f"ac5_gate names arm {arm_name!r}, which this record has no data for")
        interval = gate.get("wilson_95")
        if gate.get("passed") and interval is None:
            bad("ac5_gate passed without recording its Wilson interval")
        elif isinstance(interval, dict):
            low, high = interval.get("low"), interval.get("high")
            if isinstance(low, (int, float)) and isinstance(high, (int, float)):
                # Presence was all that was checked, so `{low: 0.995, high: 0.10}`
                # on a passing 8/10 gate validated — defeating the exact reading
                # the schema says the interval exists to prevent.
                if low > high:
                    bad(f"ac5_gate.wilson_95 low={low} exceeds high={high}")
                if not (0.0 <= low <= 1.0 and 0.0 <= high <= 1.0):
                    bad(f"ac5_gate.wilson_95 [{low}, {high}] leaves [0, 1]")
                rate = gate.get("observed_rate")
                if isinstance(rate, (int, float)) and not (low <= rate <= high):
                    bad(f"ac5_gate.observed_rate {rate} is outside its own "
                        f"Wilson interval [{low}, {high}]")

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
            elif power is None:
                bad("verdict is flip_criterion_not_met with no recorded power "
                    "against the declared effect. 'Not met' is a claim ABOUT "
                    "power; omitting the number does not make the claim safer, "
                    "it makes it unfalsifiable.")
            elif threshold is None:
                bad("verdict is flip_criterion_not_met with no recorded "
                    "`adequate_power_threshold`, so the power beside it is "
                    "compared against nothing. Both fields are optional in the "
                    "schema, so deleting either used to disable this check.")
            elif (isinstance(power, (int, float)) and isinstance(threshold, (int, float))
                  and power < threshold):
                bad(f"verdict is flip_criterion_not_met with power "
                    f"{power} against a declared effect, below the "
                    f"{threshold} adequacy threshold. That is an underpowered "
                    "run reported as evidence of no effect.")
        # `flip_criterion_met` is the verdict that reopens the standalone-DSL
        # decision, and nothing related it to its own p-value.
        alpha = flip.get("alpha")
        p_value = flip.get("p_value")
        if isinstance(p_value, (int, float)) and isinstance(alpha, (int, float)):
            significant = p_value <= alpha
            if verdict == "flip_criterion_met" and not significant:
                bad(f"verdict is flip_criterion_met at p={p_value} against "
                    f"alpha={alpha}. The verdict and the test disagree.")
            # The other direction was unchecked, so a significant flip could be
            # recorded as `inconclusive` — burying the result that reopens the
            # standalone-DSL decision.
            if verdict in ("inconclusive", "flip_criterion_not_met") and significant:
                bad(f"verdict is {verdict!r} at p={p_value} against "
                    f"alpha={alpha}, which IS significant. A significant result "
                    "recorded as inconclusive buries the finding.")
        # A one-sided test has no power against an effect declared in the other
        # direction, and the paired branch reports the same power either way.
        effect = flip.get("minimum_effect_of_interest")
        if (isinstance(effect, (list, tuple)) and len(effect) == 2
                and all(isinstance(v, (int, float)) for v in effect)
                and effect[0] >= effect[1]):
            bad(f"minimum_effect_of_interest {list(effect)} declares the "
                "primary arm at or above the baseline, which is the direction "
                "this one-sided test has no power against")
        # These four were gated on `paired`, so setting `paired: false` skipped
        # them — including the arms-vs-verdict identity this file's own comment
        # calls "the check that would have caught 'flip criterion MET' from
        # 10/10 against 0/10". They apply to every flip verdict now.
        for role in ("primary_arm", "baseline_arm"):
            named = flip.get(role)
            if named is not None and arms and named not in arms:
                bad(f"flip_criterion.{role} is {named!r}, which this record has "
                    "no arm data for")
        primary, baseline = arms.get(flip.get("primary_arm")), arms.get(flip.get("baseline_arm"))
        for role, arm, rate_key in (("primary", primary, "rhoform_rate"),
                                    ("baseline", baseline, "baseline_rate")):
            rate = flip.get(rate_key)
            if (isinstance(arm, dict) and isinstance(rate, (int, float))
                    and isinstance(arm.get("successes"), int)):
                count = _arm_count(arm)
                if isinstance(count, int) and count > 0:
                    actual = arm["successes"] / count
                    if abs(actual - rate) > 1e-6:
                        bad(f"flip_criterion.{rate_key} is {rate} but the "
                            f"{role} arm records {arm['successes']}/{count} = "
                            f"{actual:.6g}")
        if (verdict == "flip_criterion_met" and isinstance(primary, dict)
                and isinstance(baseline, dict)
                and isinstance(primary.get("successes"), int)
                and isinstance(baseline.get("successes"), int)):
            pc, bc = _arm_count(primary), _arm_count(baseline)
            if isinstance(pc, int) and isinstance(bc, int) and pc and bc:
                if primary["successes"] / pc >= baseline["successes"] / bc:
                    bad(f"verdict is flip_criterion_met — 'statistically below "
                        f"the baseline' — but the primary arm records "
                        f"{primary['successes']}/{pc} against the baseline's "
                        f"{baseline['successes']}/{bc}, which is not below it.")
        # A paired TEST on an unpaired design. protocol.py: "PAIRING IS ONLY
        # VALID WITH A REAL BLOCKING FACTOR, AND MATCHING SEED NUMBERS ARE NOT
        # ONE." Recording McNemar with paired false is that error made explicit.
        if str(flip.get("test", "")).startswith("mcnemar") and not flip.get("paired"):
            bad(f"test is {flip.get('test')!r}, a paired test, but `paired` is "
                f"{flip.get('paired')!r}")
        if flip.get("paired"):
            # `discordant_b`/`discordant_c` are read here and written NOWHERE in
            # the tree — a McNemar verdict is recorded without the 2x2 table it
            # was computed from, so the identity
            # successes_primary - successes_baseline == b - c cannot be checked.
            # Reported rather than skipped: this is the check that would have
            # caught "flip criterion MET" from 10/10 against 0/10, and silently
            # not performing it is how it stayed uncaught.
            if flip.get("discordant_b") is None or flip.get("discordant_c") is None:
                bad("flip_criterion is paired but records no discordant counts, "
                    "so the McNemar table behind its verdict cannot be checked "
                    "against the arms' own successes. Record `discordant_b` and "
                    "`discordant_c`, or the paired verdict is unfalsifiable.")
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
    for key, label in (("token_budget", "token budgets"),
                       ("max_write_check_cycles", "repair-cycle budgets"),
                       ("benchmark_id", "benchmarks")):
        values = {
            (arm.get("config") or {}).get(key)
            for arm in arms.values() if isinstance(arm, dict)
        } - {None}
        if len(values) > 1:
            bad(f"arms were run under different {label} ({sorted(values)}) and "
                "are still compared")
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
    """Every case is a mutation of the COMMITTED record, not of a synthetic dict.

    This matters more than the cases. The first version of this file built its
    fixtures by hand and read `arm["trials"]` as an integer — the harness writes
    a LIST there and puts the count in `trial_count` — so three checks were dead
    while the self-test, using the same wrong names, reported 20/20 green. Eight
    forged records passed both eval gates, including the 10/10-versus-0/10
    "flip criterion MET" this file's own comment says it exists to stop.

    Mutating the real record makes that unrepresentable: a check reading a field
    that does not exist now fails its own case, because the base document is the
    one the harness actually produces.
    """
    base_path = EXAMPLES / "demo.run.json"
    if not base_path.is_file():
        print("run-records: SELF-TEST UNAVAILABLE: eval/examples/demo.run.json "
              "is missing; the cases are mutations of it.", file=sys.stderr)
        return 2
    base = json.loads(base_path.read_text(encoding="utf-8"))
    arm_name = base["ac5_gate"]["arm"]
    other = next(k for k in base["arms"] if k != arm_name)

    def mutate(fn):
        record = json.loads(json.dumps(base))
        fn(record)
        return problems_for(record, "probe")

    def hit(fragment, fn):
        return any(fragment in problem for problem in mutate(fn))

    def set_authoritative(record):
        record["authoritative"] = True
        record["non_authoritative_reasons"] = []
        record["model"] = {"kind": "anthropic", "model": "m",
                           "sampling": {"temperature": 0.0}}
        record["gate"] = {"kind": "command"}
        record["a4_context_budget"]["tokenizer"] = {"gating": True, "name": "o200k_base"}

    cases = [
        ("the committed record is consistent", not problems_for(base, "probe")),

        # The three that were dead. Each names a field the harness really writes.
        ("more successes than trial_count is caught", hit("impossible", lambda r:
            r["arms"][arm_name].update(successes=99))),
        ("a trials list disagreeing with trial_count is caught",
         hit("trial record(s)", lambda r: r["arms"][arm_name]["trials"].pop())),
        ("arms on different benchmark_ids are caught", hit("different benchmarks",
            lambda r: r["arms"][other]["config"].update(benchmark_id="something-else"))),
        ("arms on different repair-cycle budgets are caught",
         hit("different repair-cycle budgets", lambda r:
             r["arms"][other]["config"].update(max_write_check_cycles=99))),
        ("arms on different token budgets are caught", hit("different token budgets",
            lambda r: r["arms"][other]["config"].update(token_budget=1))),
        ("arms under different iteration semantics are caught",
         hit("different iteration semantics", lambda r:
             r["arms"][other]["config"].update(iteration_semantics="initial_plus_repairs"))),

        # The gate against the data it summarises.
        ("a gate disagreeing with its arm's successes is caught", hit("disagree",
            lambda r: r["arms"][arm_name].update(successes=1))),
        ("a gate disagreeing with its arm's trial_count is caught", hit("disagree",
            lambda r: r["arms"][arm_name].update(trial_count=3))),
        ("a gate naming an arm with no data is caught", hit("no data for",
            lambda r: r["ac5_gate"].update(arm="ghost"))),

        # The AC5a threshold, at the boundary.
        ("a gate passing below the bar is caught", hit("should be False", lambda r:
            r["ac5_gate"].update(successes=2) or r["arms"][arm_name].update(successes=2))),
        ("the 7/10 boundary passes", not any("ac5_gate says" in p for p in mutate(
            lambda r: (r["ac5_gate"].update(successes=7),
                       r["arms"][arm_name].update(successes=7))))),

        # The Wilson interval, which was checked only for presence.
        ("an inverted Wilson interval is caught", hit("exceeds high", lambda r:
            r["ac5_gate"].update(wilson_95={"low": 0.995, "high": 0.10}))),
        ("a Wilson interval outside [0,1] is caught", hit("leaves [0, 1]", lambda r:
            r["ac5_gate"].update(wilson_95={"low": -0.2, "high": 0.5}))),
        ("an observed rate outside its own interval is caught",
         hit("outside its own", lambda r:
             r["ac5_gate"].update(wilson_95={"low": 0.10, "high": 0.20}))),

        # The flip criterion, against its own test.
        ("flip_criterion_met above alpha is caught", hit("verdict and the test", lambda r:
            r["flip_criterion"].update(verdict="flip_criterion_met", p_value=0.93, alpha=0.05))),
        ("an effect declared in the wrong direction is caught", hit("no power against",
            lambda r: r["flip_criterion"].update(minimum_effect_of_interest=[0.9, 0.6]))),
        ("'not met' with no declared effect is caught", hit("no declared minimum",
            lambda r: r["flip_criterion"].update(
                verdict="flip_criterion_not_met", minimum_effect_of_interest=None))),
        ("'not met' on an underpowered run is caught", hit("underpowered", lambda r:
            r["flip_criterion"].update(verdict="flip_criterion_not_met",
                                       minimum_effect_of_interest=[0.6, 0.9],
                                       power_against_declared_effect=0.02,
                                       adequate_power_threshold=0.8))),

        # The A4 budget.
        ("a budget passing while over its limit is caught", hit("cannot pass while over",
            lambda r: r["a4_context_budget"].update(total=64000, headroom=0))),
        ("headroom that does not describe the numbers is caught", hit("does not describe",
            lambda r: r["a4_context_budget"].update(headroom=999))),

        # authoritative, against all three identities.
        ("authoritative on a replay gate is caught", hit("gate kind", lambda r: (
            set_authoritative(r), r["gate"].update(kind="replay")))),
        ("authoritative on a mock model is caught", hit("model kind", lambda r: (
            set_authoritative(r), r["model"].update(kind="mock")))),
        ("authoritative on a non-gating tokenizer is caught", hit("non-gating tokenizer",
            lambda r: (set_authoritative(r),
                       r["a4_context_budget"]["tokenizer"].update(gating=False)))),
        ("authoritative with a failed budget is caught", hit("own A4 context budget",
            lambda r: (set_authoritative(r), r["a4_context_budget"].update(passed=False)))),
        ("authoritative with recorded reasons is caught", hit("non-authoritative reason",
            lambda r: (set_authoritative(r),
                       r.update(non_authoritative_reasons=["stub tokenizer"])))),
    ]

    # WIRING. Everything above drives `problems_for`; nothing proved `main()`
    # turns a finding into a non-zero exit. That branch was the one part of
    # every gate here that no self-test touched.
    import contextlib, io
    real = problems_for
    try:
        globals()["problems_for"] = lambda *_a, **_k: ["planted"]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            planted = main([])
        globals()["problems_for"] = lambda *_a, **_k: []
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            clean = main([])
    finally:
        globals()["problems_for"] = real
    cases.append(("main() exits non-zero when a problem is found", planted == 1))
    cases.append(("main() exits zero when none is", clean == 0))

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
