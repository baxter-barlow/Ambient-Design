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

from aed_eval import stats  # noqa: E402
from aed_eval.gates import CallableGate, CommandGate, Diagnostic, GateResult, ReplayGate  # noqa: E402
from aed_eval.models import ReplayClient, SamplingParams, Usage, ModelResponse, request_digest  # noqa: E402
from aed_eval.protocol import (  # noqa: E402
    TrialConfig,
    build_repair_message,
    extract_source,
    pair_discordance,
    run_arm,
    run_trial,
)
from aed_eval.results import build_run_record  # noqa: E402
from aed_eval.tokenizer import (  # noqa: E402
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


class TestSourceExtraction(unittest.TestCase):
    def test_takes_the_last_fenced_block(self):
        """Models quote the broken snippet before giving the fix."""
        text = "The error was here:\n```aed\nBROKEN\n```\nCorrected:\n```aed\nFIXED\n```"
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
                Diagnostic("AED0201", "bad arg", {"line": 3, "column": 22}, {"severity": "error"})
            ],
        )
        msg = build_repair_message(gate)
        self.assertIn("AED0201", msg)
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
        gate = CommandGate(["definitely-not-a-real-binary-xyz"], "missing")
        with tempfile.TemporaryDirectory() as tmp:
            result = gate.check("source", Path(tmp))
        self.assertFalse(result.passed)
        self.assertEqual(result.stage, "gate-unavailable")

    def test_replay_gate_refuses_to_invent_results(self):
        gate = ReplayGate([{"passed": True}])
        gate.check("x")
        with self.assertRaises(IndexError):
            gate.check("x")


class TestReplayDivergence(unittest.TestCase):
    def test_changed_request_is_detected(self):
        """A stale transcript must fail loudly, never replay quietly."""
        turns = [{"text": "hi", "request_digest": request_digest("OLD", []), "usage": {}}]
        client = ReplayClient(turns, "m", SamplingParams(0.0, 10))
        with self.assertRaises(ValueError) as ctx:
            client.complete("NEW SYSTEM PROMPT", [])
        self.assertIn("replay divergence", str(ctx.exception))

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
