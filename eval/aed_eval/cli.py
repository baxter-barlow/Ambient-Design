"""Command-line entry points for the measurement harness.

    python3 -m aed_eval tokens --part card=card.md --part skill=skill.md
    python3 -m aed_eval replay --transcript fixtures/demo-replay.json
    python3 -m aed_eval plan --rate-a 0.6 --rate-b 0.9
    python3 -m aed_eval selftest

`plan` is deliberately prominent. It answers "how many trials would this
comparison actually need?" BEFORE any tokens are spent, which at roughly
150K tokens per trial is the difference between a designed experiment and
an expensive one that cannot answer its question.
"""

import argparse
import json
import sys
from pathlib import Path

from . import stats
from .gates import ReplayGate
from .models import HarnessIntegrityError, ReplayClient, SamplingParams
from .protocol import TrialConfig, run_arm
from .results import build_run_record, summarize, write_run
from .tokenizer import (
    PinnedTokenizerError,
    StubTokenizer,
    TiktokenTokenizer,
    a4_context_budget,
)


def load_tokenizer(name: str | None, fingerprint: str | None, allow_stub: bool):
    if name in (None, "stub"):
        if not allow_stub:
            raise PinnedTokenizerError(
                "no pinned tokenizer selected. Pass --tokenizer <encoding>, or "
                "--allow-stub to use the non-gating test double (whose results "
                "can never satisfy a gate)."
            )
        return StubTokenizer()
    return TiktokenTokenizer(name, fingerprint)


def cmd_tokens(args) -> int:
    parts = {}
    for spec in args.part:
        if "=" not in spec:
            print(f"--part expects name=path, got {spec!r}", file=sys.stderr)
            return 2
        name, path = spec.split("=", 1)
        parts[name] = Path(path).read_text(encoding="utf-8")

    tokenizer = load_tokenizer(args.tokenizer, args.fingerprint, args.allow_stub)
    report = a4_context_budget(
        tokenizer, parts, limit=args.limit, enforce_gating=not args.allow_stub
    )
    print(json.dumps(report, indent=2, sort_keys=True))

    if not report["tokenizer"].get("gating", False):
        # Exit 3, never 0 or 1. A stub measurement is neither a pass nor a
        # failure — it is not a measurement of the A4 budget at all. Exiting
        # 0 would let a CI job treat it as green; exiting 1 would let
        # someone "fix" it by nudging the content. A distinct code means no
        # pipeline can mistake it for either verdict.
        print(
            "\nNON-GATING TOKENIZER: this number cannot satisfy the A4 budget. "
            "Exit code 3 is neither pass nor fail. Re-run with the pinned "
            "tokenizer from toolchain/versions.yaml for a verdict.",
            file=sys.stderr,
        )
        return 3

    if not report["passed"]:
        print(
            f"\nA4 budget exceeded by {-report['headroom']:,} tokens.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_replay(args) -> int:
    transcript = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
    tokenizer = load_tokenizer(args.tokenizer, args.fingerprint, args.allow_stub)

    sampling = SamplingParams(**transcript["sampling"])
    seeds = transcript["seeds"]
    arms = {}

    for arm_name, arm_spec in transcript["arms"].items():
        model = ReplayClient(
            arm_spec["turns"], transcript["model"], sampling, strict=not args.lenient
        )
        gate_entries = list(arm_spec["gate_results"])
        # One shared cursor across the arm's trials: the recording is a flat
        # sequence, and each trial consumes the next verdicts in order.
        shared = ReplayGate(gate_entries)
        config = TrialConfig(
            benchmark_id=transcript["benchmark_id"],
            task_prompt=transcript["task_prompt"],
            system_context=transcript["system_context"],
            max_iterations=transcript.get("max_iterations", 3),
            iteration_semantics=transcript.get(
                "iteration_semantics", "total_write_check_cycles"
            ),
            token_budget=transcript.get("token_budget", 150_000),
        )
        arms[arm_name] = run_arm(config, model, lambda: shared, seeds)
        arms[arm_name]["model_identity"] = model.identity()

    # Measure the A4 model-facing context that the run actually used, so
    # the "<=12K tokens" clause AC5a is gated on is checkable from the
    # record rather than merely asserted. Non-gating tokenizers still
    # produce a number; the record's `authoritative` flag is what says
    # whether it counts.
    context_budget = a4_context_budget(
        tokenizer,
        {
            "system_context": transcript["system_context"],
            "task_prompt": transcript["task_prompt"],
        },
        enforce_gating=False,
    )

    record = build_run_record(
        run_id=transcript.get("run_id", Path(args.transcript).stem),
        purpose=transcript.get("purpose", "replay"),
        arms=arms,
        tokenizer_identity=tokenizer.identity().as_dict(),
        model_identity={"kind": "replay", "model": transcript["model"],
                        "sampling": sampling.as_dict()},
        gate_identity={"kind": "replay"},
        context_budget=context_budget,
        primary_arm=transcript.get("primary_arm"),
        baseline_arm=transcript.get("baseline_arm"),
        paired_by=transcript.get("paired_by"),
        # Carried from the transcript, which is where a PRE-REGISTERED
        # effect size belongs: recorded with the run design, before any
        # result exists. Dropping it here made flip_criterion_not_met
        # unreachable through the only shipped entry point.
        minimum_effect_of_interest=(
            tuple(transcript["minimum_effect_of_interest"])
            if transcript.get("minimum_effect_of_interest")
            else None
        ),
        alpha=transcript.get("alpha", 0.05),
        notes=transcript.get("notes"),
    )

    if args.out:
        write_run(args.out, record)
        print(f"wrote {args.out}")
    print(summarize(record))
    return 0


def cmd_plan(args) -> int:
    report = {
        "question": (
            f"how many trials per arm to detect a true {args.rate_a} vs "
            f"{args.rate_b} difference at alpha={args.alpha}, one-sided?"
        ),
        "unpaired_power_by_n": {
            n: stats.power_unpaired(n, n, args.rate_a, args.rate_b, args.alpha)
            for n in (10, 20, 30, 40, 50)
        },
        "required_n_unpaired": stats.required_n_unpaired(
            args.rate_a, args.rate_b, args.power, args.alpha
        ),
        "note": (
            "AC5a's 10 trials are sized to gate a threshold, not to compare two "
            "arms. Read required_n_unpaired before budgeting a bake-off arm: at "
            "roughly 150K tokens per trial, the sample size IS the cost."
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def cmd_selftest(args) -> int:
    """Verify the statistics against closed-form values.

    A harness whose statistics silently changed would still produce
    confident-looking verdicts, so the reference values are checked rather
    than trusted."""
    from fractions import Fraction

    checks = [
        ("binom_cdf(0,10,1/2)", float(stats.binom_cdf(0, 10, Fraction(1, 2))), 1 / 1024),
        ("binom_sf(7,10,1/2)", float(stats.binom_sf(7, 10, Fraction(1, 2))), 176 / 1024),
        ("fisher[[1,3],[3,1]]", stats.fisher_exact_one_sided(1, 3, 3, 1), 17 / 70),
        ("mcnemar(0,5)", stats.mcnemar_exact(0, 5), 1 / 32),
        ("mcnemar(0,0)", stats.mcnemar_exact(0, 0), 1.0),
        ("wilson(7,10).low", stats.wilson_interval(7, 10)["low"], 0.3967781474611),
        ("wilson(7,10).high", stats.wilson_interval(7, 10)["high"], 0.8922087325937),
    ]
    failures = 0
    for label, got, want in checks:
        ok = abs(got - want) < 1e-9
        print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r} (expected {want!r})")
        failures += 0 if ok else 1

    gate_cases = [((7, 10), True), ((6, 10), False), ((14, 20), True), ((13, 20), False)]
    for (successes, trials), expected in gate_cases:
        got = stats.ac5_gate(successes, trials)["passed"]
        ok = got is expected
        print(f"{'ok  ' if ok else 'FAIL'} ac5_gate({successes}/{trials}) -> {got}")
        failures += 0 if ok else 1

    if failures:
        print(f"\nselftest: {failures} check(s) failed.", file=sys.stderr)
        return 1
    print(f"\nselftest PASS: {len(checks) + len(gate_cases)} checks against known values.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aed_eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_tokenizer_flags(p):
        p.add_argument("--tokenizer", default=None, help="pinned tiktoken encoding name")
        p.add_argument("--fingerprint", default=None, help="expected behavioural fingerprint")
        p.add_argument("--allow-stub", action="store_true",
                       help="permit the non-gating test tokenizer")

    p = sub.add_parser("tokens", help="measure the A4 model-facing context budget")
    p.add_argument("--part", action="append", default=[], metavar="NAME=PATH")
    p.add_argument("--limit", type=int, default=12000)
    add_tokenizer_flags(p)
    p.set_defaults(func=cmd_tokens)

    p = sub.add_parser("replay", help="re-run a recorded transcript offline")
    p.add_argument("--transcript", required=True)
    p.add_argument("--out", default=None, help="write the run record here")
    p.add_argument("--lenient", action="store_true",
                   help="do not verify request digests (diagnostic use only)")
    add_tokenizer_flags(p)
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("plan", help="sample size and power for a comparison")
    p.add_argument("--rate-a", type=float, default=0.6)
    p.add_argument("--rate-b", type=float, default=0.9)
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--power", type=float, default=0.8)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("selftest", help="verify statistics against known values")
    p.set_defaults(func=cmd_selftest)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except HarnessIntegrityError as exc:
        # A broken instrument, not a failed measurement. Diagnosed rather
        # than dumped as a traceback, because the person hitting this needs
        # to know the recording is stale, not read a stack.
        print(
            f"\nHARNESS INTEGRITY FAILURE: {exc}\n\n"
            "This is not a failed run - it means the recording no longer "
            "describes the protocol, so any numbers produced would be for a "
            "run that never happened. Re-record the transcript.",
            file=sys.stderr,
        )
        return 1
    except PinnedTokenizerError as exc:
        print(f"tokenizer error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
