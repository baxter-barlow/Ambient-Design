"""Tests for the AC5 measurement harness.

stdlib unittest, deliberately: the harness must be runnable in CI with no
dependency beyond the pinned interpreter, and adding a test-runner pin to
toolchain/versions.yaml to test a measurement tool would be a poor trade.

    python3 -m unittest discover -s eval/tests -t eval
"""

import json
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rhoform_eval import stats  # noqa: E402
from rhoform_eval.gates import (  # noqa: E402
    CallableGate,
    CommandGate,
    CompositeGate,
    Diagnostic,
    GateResult,
    ReplayGate,
)
from rhoform_eval.models import (  # noqa: E402
    HarnessIntegrityError,
    ModelResponse,
    ReplayClient,
    ReplayDivergenceError,
    ReplayExhaustedError,
    SamplingParams,
    Usage,
    request_digest,
)
from rhoform_eval.protocol import (  # noqa: E402
    TrialConfig,
    build_repair_message,
    extract_source,
    unterminated_fence,
    pair_discordance,
    run_arm,
    run_trial,
)
from rhoform_eval.results import build_run_record  # noqa: E402
from rhoform_eval.tokenizer import (  # noqa: E402
    PinnedTokenizerError,
    StubTokenizer,
    a4_context_budget,
    assert_gating_tokenizer,
)


class TestStatsAgainstKnownValues(unittest.TestCase):
    """Closed-form references. These numbers are not the harness's opinion."""

    def test_binomial_closed_form(self):
        self.assertAlmostEqual(float(stats.binom_cdf(0, 10, Fraction(1, 2))), 1 / 1024)
        self.assertAlmostEqual(float(stats.binom_sf(7, 10, Fraction(1, 2))), 176 / 1024)

    def test_fisher_matches_tea_tasting(self):
        # Fisher's tea-tasting table, lower tail.
        self.assertAlmostEqual(stats.fisher_exact_one_sided(1, 3, 3, 1), 17 / 70)

    def test_fisher_symmetric_table_is_not_significant(self):
        self.assertGreater(stats.fisher_exact_one_sided(5, 5, 5, 5), 0.5)

    def test_mcnemar_matches_binomial(self):
        self.assertAlmostEqual(stats.mcnemar_exact(0, 5), 1 / 32)
        self.assertEqual(stats.mcnemar_exact(0, 0), 1.0)

    def test_wilson_interval_at_seven_of_ten(self):
        w = stats.wilson_interval(7, 10)
        self.assertAlmostEqual(w["low"], 0.3967781474611, places=9)
        self.assertAlmostEqual(w["high"], 0.8922087325937, places=9)


class TestAc5Gate(unittest.TestCase):
    def test_threshold_at_ten_trials(self):
        self.assertTrue(stats.ac5_gate(7, 10)["passed"])
        self.assertFalse(stats.ac5_gate(6, 10)["passed"])

    def test_rule_is_a_rate_not_a_raw_count(self):
        """A longer run must clear the same bar, not an easier one."""
        self.assertTrue(stats.ac5_gate(14, 20)["passed"])
        self.assertFalse(stats.ac5_gate(13, 20)["passed"])
        self.assertEqual(stats.ac5_gate(13, 20)["required_successes"], 14)

    def test_rejects_impossible_inputs(self):
        with self.assertRaises(ValueError):
            stats.ac5_gate(11, 10)
        with self.assertRaises(ValueError):
            stats.ac5_gate(1, 0)


class TestPowerHonesty(unittest.TestCase):
    def test_ten_trials_per_arm_is_badly_underpowered(self):
        """The finding that motivates reporting power at all.

        Even against an enormous 0.60-vs-0.90 difference, ten trials per arm
        cannot reliably detect it. A bake-off that read a non-significant
        result here as 'no difference' would be wrong."""
        self.assertLess(stats.power_unpaired(10, 10, 0.6, 0.9), 0.4)

    def test_power_increases_with_n(self):
        small = stats.power_unpaired(10, 10, 0.6, 0.9)
        large = stats.power_unpaired(40, 40, 0.6, 0.9)
        self.assertGreater(large, small)

    def test_required_n_is_reported(self):
        result = stats.required_n_unpaired(0.6, 0.9, target_power=0.8)
        self.assertIsNotNone(result["n_per_arm"])
        self.assertGreaterEqual(result["power"], 0.8)

    def test_underpowered_null_result_is_inconclusive_not_equivalent(self):
        verdict = stats.flip_verdict(6, 10, 7, 10)
        self.assertEqual(verdict["verdict"], "inconclusive")
        self.assertIn("NOT evidence of equivalence", verdict["interpretation"])

    def test_not_met_requires_a_pre_declared_effect_size(self):
        """Without a declared effect there is no basis for claiming adequacy.

        The dangerous failure mode: a large-n non-significant run reporting
        'no difference' when it was never powered for the difference that
        actually occurred."""
        v = stats.flip_verdict(24, 30, 27, 30)
        self.assertEqual(v["verdict"], "inconclusive")
        self.assertIsNone(v["power_against_declared_effect"])

    def test_not_met_is_reachable_with_an_adequately_powered_declared_effect(self):
        v = stats.flip_verdict(24, 30, 27, 30, minimum_effect_of_interest=(0.6, 0.9))
        self.assertEqual(v["verdict"], "flip_criterion_not_met")
        self.assertGreaterEqual(v["power_against_declared_effect"], 0.8)

    def test_declared_but_underpowered_effect_stays_inconclusive(self):
        v = stats.flip_verdict(24, 30, 27, 30, minimum_effect_of_interest=(0.8, 0.9))
        self.assertEqual(v["verdict"], "inconclusive")
        self.assertLess(v["power_against_declared_effect"], 0.8)

    def test_significant_result_stands_without_a_declared_effect(self):
        v = stats.flip_verdict(0, 20, 20, 20)
        self.assertEqual(v["verdict"], "flip_criterion_met")


class TestInputValidation(unittest.TestCase):
    """Out-of-range inputs must raise, not return a plausible number.

    The binomial formula is a polynomial: p = 1.5 yields a finite negative
    'probability', which the power functions sum into values like 40.9 and
    required_n_unpaired turns into a sample-size budget. Reachable from the
    shipped `plan` command, whose entire job is telling you what to spend."""

    def test_binom_pmf_rejects_impossible_probability(self):
        with self.assertRaises(ValueError):
            stats.binom_pmf(3, 10, Fraction(3, 2))

    def test_power_unpaired_rejects_out_of_range_rates(self):
        for bad in ((1.5, 0.9), (-0.2, 0.9), (0.6, 1.4)):
            with self.assertRaises(ValueError):
                stats.power_unpaired(10, 10, *bad)

    def test_power_functions_reject_bad_alpha(self):
        with self.assertRaises(ValueError):
            stats.power_unpaired(10, 10, 0.6, 0.9, alpha=2.0)
        with self.assertRaises(ValueError):
            stats.power_paired(10, 0.4, 0.25, alpha=0.0)

    def test_power_paired_rejects_out_of_range_probabilities(self):
        with self.assertRaises(ValueError):
            stats.power_paired(10, 2.0, 0.25)

    def test_flip_verdict_rejects_impossible_counts(self):
        with self.assertRaises(ValueError):
            stats.flip_verdict(11, 10, 5, 10)
        with self.assertRaises(ValueError):
            stats.flip_verdict(5, 0, 5, 10)

    def test_flip_verdict_rejects_more_discordant_pairs_than_trials(self):
        with self.assertRaises(ValueError):
            stats.flip_verdict(
                5, 10, 5, 10, discordant_rhoform_only=8, discordant_baseline_only=7
            )

    def test_wilson_rejects_out_of_range_successes(self):
        with self.assertRaises(ValueError):
            stats.wilson_interval(11, 10)

    def test_required_n_is_exact_across_several_effects(self):
        """Power saw-tooths in n for exact tests, so only a full scan is right."""
        for pa, pb in ((0.4, 0.9), (0.5, 0.9), (0.6, 0.9), (0.3, 0.8)):
            n = stats.required_n_unpaired(pa, pb, target_power=0.8)["n_per_arm"]
            self.assertIsNotNone(n)
            brute = next(
                m for m in range(1, 201)
                if stats.power_unpaired(m, m, pa, pb) >= 0.8
            )
            self.assertEqual(n, brute, f"{pa} vs {pb}: got {n}, true smallest {brute}")

    def test_required_n_finds_the_exact_smallest_n(self):
        """The docstring promises the smallest n, so a grid of 5 will not do.

        At roughly 150K tokens a trial, over-budgeting by four trials per
        arm is real money in the one function whose job is budgeting."""
        result = stats.required_n_unpaired(0.4, 0.9, target_power=0.8)
        n = result["n_per_arm"]
        self.assertIsNotNone(n)
        self.assertGreaterEqual(stats.power_unpaired(n, n, 0.4, 0.9), 0.8)
        # n-1 must fall short, or n was not the smallest.
        self.assertLess(stats.power_unpaired(n - 1, n - 1, 0.4, 0.9), 0.8)


class TestSourceExtraction(unittest.TestCase):
    def test_takes_the_last_fenced_block(self):
        """Models quote the broken snippet before giving the fix."""
        text = "The error was here:\n```rhoform\nBROKEN\n```\nCorrected:\n```rhoform\nFIXED\n```"
        self.assertEqual(extract_source(text), "FIXED")

    def test_no_fence_is_a_failure_not_a_fallback(self):
        self.assertIsNone(extract_source("Here is the design, described in prose."))

    def test_untagged_fence_is_accepted(self):
        self.assertEqual(extract_source("```\nmodule X:\n```"), "module X:")


class TestRepairMessage(unittest.TestCase):
    def test_carries_codes_and_spans(self):
        gate = GateResult(
            passed=False,
            diagnostics=[
                Diagnostic("RHO0201", "bad arg", {"line": 3, "column": 22}, {"severity": "error"})
            ],
        )
        msg = build_repair_message(gate)
        self.assertIn("RHO0201", msg)
        self.assertIn("line 3", msg)

    def test_params_render_deterministically(self):
        """Key order must not change the prompt.

        Renders as sorted JSON rather than a Python dict repr: a diagnostic
        round-tripped through JSON has a different insertion order, and a
        repr would silently change the prompt and therefore the run."""
        a = GateResult(False, [Diagnostic("C", "m", None, {"b": 2, "a": 1})])
        b = GateResult(False, [Diagnostic("C", "m", None, {"a": 1, "b": 2})])
        self.assertEqual(build_repair_message(a), build_repair_message(b))

    def test_truncation_is_stated(self):
        gate = GateResult(False, [Diagnostic(f"C{i}", "m") for i in range(30)])
        msg = build_repair_message(gate, max_diagnostics=5)
        self.assertIn("omitted", msg)


class _ScriptedModel:
    def __init__(self, texts, tokens_per_turn=1000):
        self.texts = list(texts)
        self.i = 0
        self.tokens = tokens_per_turn

    def complete(self, system, messages):
        text = self.texts[min(self.i, len(self.texts) - 1)]
        self.i += 1
        return ModelResponse(text, Usage(self.tokens, 0), "end_turn", "scripted")

    def identity(self):
        return {"kind": "scripted", "model": "scripted", "sampling": {}}


def _gate(sequence):
    it = iter(sequence)
    return CallableGate(lambda src: GateResult(passed=next(it)), "scripted")


class TestTrialProtocol(unittest.TestCase):
    def _config(self, **kw):
        base = dict(
            benchmark_id="b",
            task_prompt="emit",
            system_context="ctx",
        )
        base.update(kw)
        return TrialConfig(**base)

    def test_passes_on_first_cycle(self):
        r = run_trial(self._config(), _ScriptedModel(["```\nOK\n```"]), _gate([True]), 1)
        self.assertTrue(r.passed)
        self.assertEqual(r.cycles_used, 1)

    def test_recovers_within_the_repair_budget(self):
        model = _ScriptedModel(["```\nBAD\n```", "```\nOK\n```"])
        r = run_trial(self._config(), model, _gate([False, True]), 1)
        self.assertTrue(r.passed)
        self.assertEqual(r.cycles_used, 2)

    def test_strict_semantics_allow_three_cycles(self):
        model = _ScriptedModel(["```\nBAD\n```"] * 5)
        r = run_trial(self._config(), model, _gate([False] * 5), 1)
        self.assertFalse(r.passed)
        self.assertEqual(r.outcome, "iteration_budget_exhausted")
        self.assertEqual(r.cycles_used, 3)

    def test_lenient_semantics_allow_one_more_cycle(self):
        """The two readings of AC5 must differ, and by exactly one cycle."""
        cfg = self._config(iteration_semantics="initial_plus_repairs")
        model = _ScriptedModel(["```\nBAD\n```"] * 6)
        r = run_trial(cfg, model, _gate([False] * 6), 1)
        self.assertEqual(r.cycles_used, 4)

    def test_token_budget_is_conjunctive_with_the_gate(self):
        """Passing the gate over budget is a failure, not a pass with a note."""
        cfg = self._config(token_budget=500)
        model = _ScriptedModel(["```\nOK\n```"], tokens_per_turn=900)
        r = run_trial(cfg, model, _gate([True]), 1)
        self.assertFalse(r.passed)
        self.assertEqual(r.outcome, "token_budget_exceeded")

    def test_missing_fence_consumes_a_cycle_and_is_recorded(self):
        model = _ScriptedModel(["no code here", "```\nOK\n```"])
        r = run_trial(self._config(), model, _gate([True]), 1)
        self.assertTrue(r.passed)
        self.assertEqual(r.cycles_used, 2)
        self.assertFalse(r.iterations[0].source_extracted)

    def test_model_error_fails_the_trial_and_is_never_retried(self):
        class Boom:
            def complete(self, system, messages):
                raise RuntimeError("api down")

            def identity(self):
                return {}

        r = run_trial(self._config(), Boom(), _gate([True]), 1)
        self.assertFalse(r.passed)
        self.assertEqual(r.outcome, "model_error")
        self.assertIn("api down", r.error)


class TestBrokenInstrumentPropagates(unittest.TestCase):
    """A broken recording must fail the run, not fail a trial.

    Swallowing replay divergence into `model_error` made the CI replay job
    incapable of failing: every drifted transcript looked like ten failed
    trials and exited 0."""

    def test_replay_divergence_escapes_the_trial_loop(self):
        cfg = TrialConfig(benchmark_id="b", task_prompt="p", system_context="c")
        turns = [{"text": "x", "request_digest": request_digest("OTHER", []), "usage": {}}]
        client = ReplayClient(turns, "m", SamplingParams(0.0, 10))
        with self.assertRaises(ReplayDivergenceError):
            run_trial(cfg, client, _gate([True]), 1)

    def test_ordinary_model_failure_is_still_recorded_not_raised(self):
        class Boom:
            def complete(self, system, messages):
                raise RuntimeError("api down")

            def identity(self):
                return {}

        cfg = TrialConfig(benchmark_id="b", task_prompt="p", system_context="c")
        result = run_trial(cfg, Boom(), _gate([True]), 1)
        self.assertEqual(result.outcome, "model_error")


class TestTruncatedEmission(unittest.TestCase):
    def test_unterminated_fence_is_detected(self):
        """A truncated reply usually still quotes the broken snippet."""
        text = "The bug was:\n```rhoform\nBROKEN\n```\nFixed:\n```rhoform\nGOOD but cut off"
        self.assertTrue(unterminated_fence(text))
        # extract_source itself does NOT judge truncation: it would have
        # discarded legitimate designs containing a fence marker.
        self.assertEqual(extract_source(text), "BROKEN")

    def test_max_tokens_stop_is_a_failed_emission_even_with_balanced_fences(self):
        """The case `extract_source` alone cannot see.

        Truncation can land AFTER a complete block, leaving the fences
        balanced. The last complete block is then the model quoting the
        broken file back, and grading it scores a truncation as a PASS.
        Review found this path had no coverage: mutating the stop_reason
        check away left every test green."""

        class Truncated:
            def complete(self, system, messages):
                return ModelResponse(
                    text="Here is the file I am fixing:\n```rhoform\nBROKEN\n```\nNow the corrected",
                    usage=Usage(100, 50),
                    stop_reason="max_tokens",
                    model="scripted",
                )

            def identity(self):
                return {}

        cfg = TrialConfig(benchmark_id="b", task_prompt="p", system_context="c")
        # The gate would PASS anything it is handed; the trial must still
        # fail, because nothing should reach the gate at all.
        result = run_trial(cfg, Truncated(), _gate([True, True, True]), 1)
        self.assertFalse(result.passed)
        self.assertFalse(any(i.source_extracted for i in result.iterations))


class TestTruncationDoesNotEatGoodEmissions(unittest.TestCase):
    """The fix for truncation must not become a bug of its own.

    An odd triple-backtick count also occurs when a design legitimately
    contains a fence marker. Discarding those would score complete,
    gate-passing emissions as failures - biasing the measured rate in the
    opposite direction from the bug the guard was added to fix."""

    def test_clean_stop_is_trusted_over_the_fence_heuristic(self):
        class Weird:
            def complete(self, system, messages):
                return ModelResponse(
                    text="```rhoform\nmodule M:\n    note = \"```\"\n```",
                    usage=Usage(10, 10),
                    stop_reason="end_turn",
                    model="scripted",
                )

            def identity(self):
                return {}

        cfg = TrialConfig(benchmark_id="b", task_prompt="p", system_context="c")
        result = run_trial(cfg, Weird(), _gate([True]), 1)
        self.assertTrue(result.passed)

    def test_fence_heuristic_still_applies_when_no_stop_reason_is_given(self):
        class NoStop:
            def complete(self, system, messages):
                return ModelResponse(
                    text="Fixing:\n```rhoform\nBROKEN\n```\nNow:\n```rhoform\ncut off",
                    usage=Usage(10, 10), stop_reason=None, model="scripted",
                )

            def identity(self):
                return {}

        cfg = TrialConfig(benchmark_id="b", task_prompt="p", system_context="c")
        result = run_trial(cfg, NoStop(), _gate([True, True, True]), 1)
        self.assertFalse(result.passed)

    def test_a_wholly_truncated_trial_is_labelled_as_such(self):
        """A budget failure and a comprehension failure are different."""

        class Truncated:
            def complete(self, system, messages):
                return ModelResponse(text="```rhoform\nX\n```", usage=Usage(10, 10),
                                     stop_reason="max_tokens", model="s")

            def identity(self):
                return {}

        cfg = TrialConfig(benchmark_id="b", task_prompt="p", system_context="c")
        result = run_trial(cfg, Truncated(), _gate([True] * 3), 1)
        self.assertEqual(result.outcome, "truncated")


class TestPairedPowerMatchesPairedTest(unittest.TestCase):
    def test_paired_verdict_does_not_borrow_unpaired_power(self):
        """Certifying a McNemar result with Fisher's power is incoherent."""
        paired = stats.flip_verdict(
            6, 20, 12, 20, discordant_rhoform_only=2, discordant_baseline_only=8,
            minimum_effect_of_interest=(0.6, 0.9),
        )
        unpaired = stats.flip_verdict(6, 20, 12, 20, minimum_effect_of_interest=(0.6, 0.9))
        self.assertEqual(paired["test"], "mcnemar_exact_one_sided")
        self.assertEqual(unpaired["test"], "fisher_exact_one_sided")
        self.assertNotEqual(
            paired["power_against_declared_effect"],
            unpaired["power_against_declared_effect"],
        )


class TestPairing(unittest.TestCase):
    def _arm(self, seeds, passes):
        return {"trials": [{"seed": s, "passed": p} for s, p in zip(seeds, passes)]}

    def test_discordance_counts(self):
        a = self._arm([1, 2, 3, 4], [True, True, False, False])
        b = self._arm([1, 2, 3, 4], [True, False, True, False])
        self.assertEqual(pair_discordance(a, b), (1, 1))

    def test_mismatched_seed_sets_are_rejected(self):
        a = self._arm([1, 2], [True, True])
        b = self._arm([3, 4], [True, True])
        with self.assertRaises(ValueError):
            pair_discordance(a, b)


class TestGates(unittest.TestCase):
    def test_command_gate_never_trusts_exit_zero_alone(self):
        """A tool exiting 0 while emitting errors must not pass the trial."""
        diag = json.dumps({"code": "E1", "message": "bad", "params": {"severity": "error"}})
        gate = CommandGate(["python3", "-c", f"print({diag!r})"], "fake")
        with tempfile.TemporaryDirectory() as tmp:
            result = gate.check("source", Path(tmp))
        self.assertEqual(result.exit_code, 0)
        self.assertFalse(result.passed)

    def test_command_gate_passes_on_clean_zero_exit(self):
        gate = CommandGate(["python3", "-c", "pass"], "fake")
        with tempfile.TemporaryDirectory() as tmp:
            result = gate.check("source", Path(tmp))
        self.assertTrue(result.passed)

    def test_missing_executable_is_reported_not_silently_passed(self):
        gate = CommandGate(["definitely-not-a-real-binary-xyz"], "missing", stage="export")
        with tempfile.TemporaryDirectory() as tmp:
            result = gate.check("source", Path(tmp))
        self.assertFalse(result.passed)
        # The stage is carried through, so "the export tool is missing" is
        # distinguishable from "the compiler is missing" in a run record.
        self.assertEqual(result.stage, "export:gate-unavailable")

    def test_command_gate_reports_its_own_stage(self):
        """A parse failure and an export failure must be distinguishable."""
        gate = CommandGate(["python3", "-c", "pass"], "fake", stage="export")
        with tempfile.TemporaryDirectory() as tmp:
            result = gate.check("source", Path(tmp))
        self.assertEqual(result.stage, "export")

    def test_composite_gate_expresses_the_ac5a_pipeline(self):
        """AC5a's bar is compile/type-check/EXPORT - plural stages."""
        ok = ["python3", "-c", "pass"]
        gate = CompositeGate(
            [
                CommandGate(ok, "c", stage="compile"),
                CommandGate(ok, "t", stage="type-check"),
                CommandGate(ok, "e", stage="export"),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = gate.check("source", Path(tmp))
        self.assertTrue(result.passed)
        self.assertEqual(result.stage, "compile -> type-check -> export")

    def test_composite_gate_short_circuits_and_names_the_failing_stage(self):
        fail = ["python3", "-c", "import sys; sys.exit(1)"]
        ok = ["python3", "-c", "pass"]
        gate = CompositeGate(
            [
                CommandGate(ok, "c", stage="compile"),
                CommandGate(fail, "t", stage="type-check"),
                CommandGate(fail, "e", stage="export"),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = gate.check("source", Path(tmp))
        self.assertFalse(result.passed)
        self.assertIn("type-check", result.stage)
        # export must NOT have run: cascade noise from an upstream failure
        # makes the repair loop worse, not better.
        self.assertNotIn("export", result.stage)

    def test_composite_gate_rejects_an_empty_pipeline(self):
        with self.assertRaises(ValueError):
            CompositeGate([])

    def test_replay_gate_refuses_to_invent_results(self):
        gate = ReplayGate([{"passed": True}])
        gate.check("x")
        with self.assertRaises(ReplayExhaustedError):
            gate.check("x")


class TestReplayDivergence(unittest.TestCase):
    def test_changed_request_is_detected(self):
        """A stale transcript must fail loudly, never replay quietly."""
        turns = [{"text": "hi", "request_digest": request_digest("OLD", []), "usage": {}}]
        client = ReplayClient(turns, "m", SamplingParams(0.0, 10))
        with self.assertRaises(ReplayDivergenceError) as ctx:
            client.complete("NEW SYSTEM PROMPT", [])
        self.assertIn("replay divergence", str(ctx.exception))
        # Must be a harness-integrity error, so the trial loop re-raises it
        # instead of recording it as an ordinary failed trial.
        self.assertIsInstance(ctx.exception, HarnessIntegrityError)

    def test_matching_request_replays(self):
        system, messages = "S", [{"role": "user", "content": "u"}]
        turns = [
            {
                "text": "ok",
                "request_digest": request_digest(system, messages),
                "usage": {"input_tokens": 5, "output_tokens": 2},
            }
        ]
        client = ReplayClient(turns, "m", SamplingParams(0.0, 10))
        response = client.complete(system, messages)
        self.assertEqual(response.text, "ok")
        self.assertEqual(response.usage.total, 7)


class TestTokenizerGating(unittest.TestCase):
    def test_stub_is_marked_non_gating(self):
        self.assertFalse(StubTokenizer().identity().gating)

    def test_gating_assertion_rejects_the_stub(self):
        with self.assertRaises(PinnedTokenizerError):
            assert_gating_tokenizer(StubTokenizer().identity())

    def test_a4_budget_refuses_a_non_gating_tokenizer_by_default(self):
        with self.assertRaises(PinnedTokenizerError):
            a4_context_budget(StubTokenizer(), {"card": "a b c"})

    def test_a4_budget_reports_the_breakdown_not_just_the_total(self):
        report = a4_context_budget(
            StubTokenizer(),
            {"card": "a b c", "skill": "d e"},
            limit=10,
            enforce_gating=False,
        )
        self.assertEqual(report["total"], 5)
        self.assertEqual(report["breakdown"], {"card": 3, "skill": 2})
        self.assertTrue(report["passed"])

    def test_a4_budget_fails_when_over_limit(self):
        report = a4_context_budget(
            StubTokenizer(), {"card": "a b c d e f"}, limit=3, enforce_gating=False
        )
        self.assertFalse(report["passed"])
        self.assertEqual(report["headroom"], -3)


class TestAuthoritativeComputation(unittest.TestCase):
    def _arm(self):
        cfg = TrialConfig(benchmark_id="b", task_prompt="p", system_context="c")
        model = _ScriptedModel(["```\nOK\n```"])
        return run_arm(cfg, model, lambda: _gate([True]), [1])

    def test_stub_tokenizer_makes_a_record_non_authoritative(self):
        record = build_run_record(
            run_id="r",
            purpose="test",
            arms={"a": self._arm()},
            tokenizer_identity=StubTokenizer().identity().as_dict(),
            model_identity={"kind": "anthropic", "model": "m", "sampling": {}},
            gate_identity={"kind": "callable"},
        )
        self.assertFalse(record["authoritative"])
        self.assertTrue(record["non_authoritative_reasons"])

    def test_replayed_model_makes_a_record_non_authoritative(self):
        gating = {"name": "pinned", "kind": "tiktoken", "fingerprint": "sha256:" + "0" * 64,
                  "n_vocab": 1, "gating": True}
        record = build_run_record(
            run_id="r",
            purpose="test",
            arms={"a": self._arm()},
            tokenizer_identity=gating,
            model_identity={"kind": "replay", "model": "m", "sampling": {}},
            gate_identity={"kind": "replay"},
        )
        self.assertFalse(record["authoritative"])
        self.assertIn("replay", record["non_authoritative_reasons"][0])

    def test_live_run_with_pinned_tokenizer_is_authoritative(self):
        gating = {"name": "pinned", "kind": "tiktoken", "fingerprint": "sha256:" + "0" * 64,
                  "n_vocab": 1, "gating": True}
        record = build_run_record(
            run_id="r",
            purpose="test",
            arms={"a": self._arm()},
            tokenizer_identity=gating,
            model_identity={"kind": "anthropic", "model": "m", "sampling": {}},
            gate_identity={"kind": "command"},
        )
        self.assertTrue(record["authoritative"])
        self.assertEqual(record["non_authoritative_reasons"], [])

    def test_gate_verdict_ships_with_its_interval(self):
        record = build_run_record(
            run_id="r",
            purpose="test",
            arms={"a": self._arm()},
            tokenizer_identity=StubTokenizer().identity().as_dict(),
            model_identity={"kind": "anthropic", "model": "m", "sampling": {}},
            gate_identity={"kind": "callable"},
            primary_arm="a",
        )
        self.assertIn("wilson_95", record["ac5_gate"])
        self.assertIn("caveat", record["ac5_gate"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
