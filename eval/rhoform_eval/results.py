"""Run-record assembly and canonical serialization.

A run record is the evidence a gate decision rests on. It has to answer,
years later and without the author present: what was measured, with which
model at which sampling parameters, against which gate, under which
tokenizer, under which reading of the iteration budget, and what the
statistics actually support.

Records are written as canonical JSON (sorted keys, LF, UTF-8) so two runs
diff cleanly and a record can be hashed. The record deliberately DOES carry
a wall-clock timestamp: it is an observation of an external system, not a
compiled artifact, so the determinism contract that bans timestamps from
the IR does not apply and provenance requires one.
"""

import json
import platform
import sys
from datetime import datetime, timezone

from . import stats
from .protocol import pair_discordance

HARNESS_VERSION = "0.1.0"
RECORD_SCHEMA_VERSION = 0


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Kinds that mean a real model / real gate produced this. Kept as allowlists so
# that an unrecognised value fails closed. tests/eval/check-run-records.py holds
# the same two sets; they are duplicated deliberately, because a gate importing
# the thing it checks cannot catch that thing changing.
LIVE_MODEL_KINDS = ("anthropic", "openai", "live")
LIVE_GATE_KINDS = ("command", "compiler")


def build_run_record(
    *,
    run_id: str,
    purpose: str,
    arms: dict,
    tokenizer_identity: dict,
    model_identity: dict,
    gate_identity: dict,
    context_budget: dict | None = None,
    primary_arm: str | None = None,
    baseline_arm: str | None = None,
    alpha: float = 0.05,
    minimum_effect_of_interest: tuple[float, float] | None = None,
    paired_by: str | None = None,
    notes: str | None = None,
) -> dict:
    """Assemble a complete run record, including the statistical verdicts.

    `arms` maps an arm name to the dict returned by protocol.run_arm.

    The AC5a gate is evaluated for the primary arm, and the §4 flip
    criterion only when a baseline arm is present. Both verdicts carry the
    evidence behind them — the Wilson interval for the gate, the power for
    the comparison — because a bare PASS or a bare p-value invites exactly
    the overreading this record exists to prevent.
    """
    # Whether this record may be cited as gate evidence. COMPUTED, never
    # passed in: a replayed or scripted model is not a measurement of any
    # model, and a non-gating tokenizer's counts cannot satisfy a budget.
    # Deriving it here means a synthetic fixture cannot be mistaken for
    # evidence even if someone quotes its numbers out of context.
    non_authoritative_reasons = []
    if not tokenizer_identity.get("gating", False):
        non_authoritative_reasons.append(
            f"tokenizer {tokenizer_identity.get('name')!r} is non-gating"
        )
    # ALLOWLIST, not a denylist. `in ("replay", "scripted", "stub")` meant an
    # unrecognised kind — `mock`, `testdouble`, a typo — minted an authoritative
    # record, and the schema used the same denylist so it agreed.
    if model_identity.get("kind") not in LIVE_MODEL_KINDS:
        non_authoritative_reasons.append(
            f"model source is {model_identity.get('kind')!r}, not a live pinned model"
        )
    # And the GATE identity, which README says this is computed from and which
    # was stored and never read: a run whose verdicts came from a ReplayGate
    # could call itself authoritative, producing a record the repository's own
    # run-record checker then rejects.
    if gate_identity.get("kind") not in LIVE_GATE_KINDS:
        non_authoritative_reasons.append(
            f"gate is {gate_identity.get('kind')!r}, not a live compile/check gate"
        )

    record = {
        "record_schema_version": RECORD_SCHEMA_VERSION,
        "run_id": run_id,
        "purpose": purpose,
        "recorded_at": utc_now(),
        "authoritative": not non_authoritative_reasons,
        "non_authoritative_reasons": non_authoritative_reasons,
        "harness": {
            "version": HARNESS_VERSION,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "tokenizer": tokenizer_identity,
        "model": model_identity,
        "gate": gate_identity,
        "arms": arms,
    }

    if context_budget is not None:
        record["a4_context_budget"] = context_budget

    if primary_arm and primary_arm in arms:
        arm = arms[primary_arm]
        gate_result = stats.ac5_gate(arm["successes"], arm["trial_count"])
        interval = stats.wilson_interval(arm["successes"], arm["trial_count"])
        record["ac5_gate"] = {
            "arm": primary_arm,
            **gate_result,
            "wilson_95": interval,
            "caveat": (
                "The Wilson interval is the honest width of this estimate. A "
                "pass at 7/10 is consistent with a true rate anywhere from "
                f"{interval['low']:.2f} to {interval['high']:.2f}; the gate is a "
                "threshold rule, not a demonstration that the true rate exceeds "
                "the threshold."
            ),
        }

        if baseline_arm and baseline_arm in arms:
            base = arms[baseline_arm]
            # Pair ONLY when a blocking factor was named. Matching seed
            # numbers are not one: in the AC5 protocol every trial runs the
            # same prompt on the same benchmark, so trial i of two arms
            # shares nothing but an index and a paired test would claim
            # precision the design does not earn. Inferring pairing from
            # seed lists lining up is exactly that mistake, and it was in
            # here until review found it.
            paired = (None, None)
            if paired_by:
                a_only, b_only = pair_discordance(arm, base)
                paired = (a_only, b_only)
            record["flip_criterion"] = stats.flip_verdict(
                rhoform_successes=arm["successes"],
                rhoform_trials=arm["trial_count"],
                baseline_successes=base["successes"],
                baseline_trials=base["trial_count"],
                discordant_rhoform_only=paired[0],
                discordant_baseline_only=paired[1],
                alpha=alpha,
                minimum_effect_of_interest=minimum_effect_of_interest,
            )
            record["flip_criterion"]["primary_arm"] = primary_arm
            record["flip_criterion"]["baseline_arm"] = baseline_arm
            record["flip_criterion"]["paired_by"] = paired_by

    if notes:
        record["notes"] = notes

    return record


def write_run(path, record: dict) -> None:
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(record), encoding="utf-8")


def summarize(record: dict) -> str:
    """Short human summary. Always states the caveat with the verdict."""
    lines = [f"run {record['run_id']}  ({record['purpose']})"]
    if not record.get("authoritative", False):
        lines.append(
            "  NOT AUTHORITATIVE - "
            + "; ".join(record.get("non_authoritative_reasons", []))
        )
    lines.append(
        f"  tokenizer {record['tokenizer']['name']} "
        f"({'gating' if record['tokenizer'].get('gating') else 'NON-GATING'})"
    )
    lines.append(f"  model     {record['model'].get('model')}")
    for name, arm in sorted(record["arms"].items()):
        lines.append(
            f"  arm {name}: {arm['successes']}/{arm['trial_count']} passed, "
            f"{arm['total_tokens']:,} tokens, outcomes {arm['outcomes']}"
        )
    if "a4_context_budget" in record:
        b = record["a4_context_budget"]
        lines.append(
            f"  A4 context: {b['total']:,}/{b['limit']:,} tokens "
            f"({'PASS' if b['passed'] else 'OVER BUDGET'})"
        )
    if "ac5_gate" in record:
        g = record["ac5_gate"]
        w = g["wilson_95"]
        lines.append(
            f"  AC5a gate: {'PASS' if g['passed'] else 'FAIL'} "
            f"({g['successes']}/{g['trials']}, 95% CI {w['low']:.2f}-{w['high']:.2f})"
        )
    if "flip_criterion" in record:
        f = record["flip_criterion"]
        declared = f.get("power_against_declared_effect")
        power_note = (
            f"power(declared)={declared:.2f}"
            if declared is not None
            else "no declared effect"
        )
        lines.append(
            f"  §4 flip:   {f['verdict']} (p={f['p_value']:.4f}, "
            f"{power_note}, {f['test']})"
        )
        lines.append(f"             {f['interpretation']}")
    return "\n".join(lines)
