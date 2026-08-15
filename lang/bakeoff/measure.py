"""Run the measurement: token cost, agreement, and the L6/T9 readings.

Everything here is offline and deterministic. Nothing calls a model — that is
the AC5 protocol, which AMB-31 built and AMB-33 runs with these arms plugged
in as gates.

WHAT THE TOKEN NUMBERS ARE. Each cell is the pinned tokenizer's count over one
arm's CANONICAL rendering of one design. That makes it a property of the
grammar and a fixed formatter, not of any author's habits and not of any
model's output — which is the question §8-Q1 asks ("token cost") and all it
can honestly answer without spending a trial. Emission accuracy under a model
is a different question with a different instrument.

WHAT MAKES THE COMPARISON FAIR, and it is not politeness — it is checked:
every arm must round-trip its own rendering, and every arm's parse of its own
rendering must equal the same reference model. If those hold, the arms are
saying the same thing and the counts differ only by how they say it. If they
do not hold, the run FAILS rather than reporting numbers, because a token
count over an arm that said something else is not a measurement.

The pinned tokenizer comes from eval/, so the bake-off and the AC5a gate run
count with the same ruler. If it is unavailable the report is marked
non-gating and says so; it never substitutes an approximation, because a
number that looks like a pinned count and is not one is worse than no number.
"""

import sys
from pathlib import Path

from .arms import ARMS
from .defects import DEFECTS, score, summarise
from .diagnostics import ParseFailure
from .elaborate import AnchorError, check_anchor
from .model import REPO_ROOT, diff, load_corpus

sys.path.insert(0, str(REPO_ROOT / "eval"))


class MeasurementError(RuntimeError):
    """The run cannot produce comparable numbers."""


def load_tokenizer(allow_stub: bool = False):
    """The pinned budget tokenizer, or a clearly-marked stub.

    Reads the pin out of toolchain/versions.yaml rather than repeating it, so
    a re-pin cannot leave the bake-off counting with the old encoding while
    claiming the new one.
    """
    from aed_eval.tokenizer import PinnedTokenizerError, StubTokenizer, TiktokenTokenizer

    encoding, fingerprint = _read_pin()
    try:
        return TiktokenTokenizer(encoding, fingerprint)
    except PinnedTokenizerError as exc:
        if not allow_stub:
            raise MeasurementError(
                f"{exc}\n\nThe bake-off will not substitute an approximate "
                "tokenizer. Install the pin, or pass --allow-stub to run the "
                "structural checks with token counts explicitly marked "
                "non-gating."
            ) from None
        return StubTokenizer()


def _read_pin() -> tuple[str, str]:
    """(encoding, fingerprint) from toolchain/versions.yaml, without PyYAML.

    A four-line scan rather than a dependency: this must run in the same
    places `make check` runs, and the two keys it needs are unambiguous.
    """
    encoding = fingerprint = None
    inside = False
    for line in (REPO_ROOT / "toolchain" / "versions.yaml").read_text(
        encoding="utf-8"
    ).splitlines():
        stripped = line.strip()
        if stripped.startswith("tokenizer:"):
            inside = True
            continue
        if inside and stripped.startswith("encoding:"):
            encoding = stripped.split(":", 1)[1].strip().strip('"')
        if inside and stripped.startswith("fingerprint:"):
            fingerprint = stripped.split(":", 1)[1].strip().strip('"')
        if inside and stripped.startswith("probe_corpus:"):
            break
    if not encoding or not fingerprint:
        raise MeasurementError(
            "toolchain/versions.yaml does not declare evaluation.tokenizer."
            "{encoding,fingerprint}; the bake-off has no ruler to count with."
        )
    return encoding, fingerprint


def measure(allow_stub: bool = False, with_defects: bool = True) -> dict:
    tokenizer = load_tokenizer(allow_stub)
    identity = tokenizer.identity()
    designs = load_corpus()

    anchors = {}
    for design_id, model in sorted(designs.items()):
        try:
            anchors[design_id] = check_anchor(model)
        except AnchorError as exc:
            raise MeasurementError(
                f"{design_id}: the corpus disagrees with its own anchor, so no "
                f"measurement over it means anything.\n{exc}"
            ) from None

    cells = []
    failures = []
    for design_id, model in sorted(designs.items()):
        for arm in ARMS.values():
            for variant in arm.variants:
                source = arm.render(model, variant)
                cell = {
                    "design": design_id,
                    "arm": arm.key,
                    "variant": variant,
                    "tokens": tokenizer.count(source),
                    "lines": len(source.splitlines()),
                    "bytes": len(source.encode("utf-8")),
                }
                try:
                    parsed = arm.parse(source, variant)
                except ParseFailure as failure:
                    cell["agrees"] = False
                    failures.append(
                        f"{design_id}/{arm.key}/{variant}: the arm cannot parse its "
                        "own canonical rendering: "
                        + "; ".join(d.message for d in failure.diagnostics[:3])
                    )
                else:
                    differences = diff(model, parsed)
                    cell["agrees"] = not differences
                    if differences:
                        failures.append(
                            f"{design_id}/{arm.key}/{variant}: round trip changed the "
                            "design: " + "; ".join(differences[:3])
                        )
                cells.append(cell)

    if failures:
        raise MeasurementError(
            "the arms do not all express the same design, so their token counts "
            "are not comparable:\n  " + "\n  ".join(failures)
        )

    cards = {
        arm.key: {
            "tokens": tokenizer.count(arm.language_card()),
            "lines": len(arm.language_card().splitlines()),
            # §4's flip criterion is stated against the language card at ~3K
            # tokens, so the budget is checked here rather than left to be
            # eyeballed later.
            "within_3k": tokenizer.count(arm.language_card()) <= 3000,
        }
        for arm in ARMS.values()
    }

    report = {
        "tokenizer": identity.as_dict(),
        "gating": identity.gating,
        "designs": {
            design_id: {
                "anchor": anchors[design_id],
                "instances": sum(len(m.instances) for m in model.modules),
                "modules": len(model.modules),
                "nets": sum(len(m.nets) for m in model.modules),
            }
            for design_id, model in sorted(designs.items())
        },
        "cells": cells,
        "language_cards": cards,
        "readings": _readings(cells),
    }
    if with_defects:
        rows = [
            row
            for design_id, model in sorted(designs.items())
            for arm in ARMS.values()
            for row in score(arm, "inferred", model, design_id)
        ]
        report["defects"] = {"rows": rows, "summary": summarise(rows)}
    return report


def _cell(cells, design, arm, variant):
    for entry in cells:
        if (entry["design"], entry["arm"], entry["variant"]) == (design, arm, variant):
            return entry
    return None


def _readings(cells) -> dict:
    """The two S-item readings §8-Q1 asks this issue for.

    Both are DELTAS BETWEEN VARIANTS OF THE SAME ARM, never between arms, so
    neither reading depends on which candidate eventually wins.
    """
    designs = sorted({cell["design"] for cell in cells})
    t9, l6 = {}, {}
    for design in designs:
        for arm_key, arm in ARMS.items():
            explicit = _cell(cells, design, arm_key, "explicit")
            inferred = _cell(cells, design, arm_key, "inferred")
            if explicit and inferred:
                t9.setdefault(design, {})[arm_key] = {
                    "explicit_tokens": explicit["tokens"],
                    "inferred_tokens": inferred["tokens"],
                    "tax_tokens": explicit["tokens"] - inferred["tokens"],
                    "tax_fraction": round(
                        (explicit["tokens"] - inferred["tokens"]) / explicit["tokens"], 4
                    ),
                }
            columnar = _cell(cells, design, arm_key, "inferred+columnar")
            if inferred and columnar:
                l6.setdefault(design, {})[arm_key] = {
                    "inferred_tokens": inferred["tokens"],
                    "columnar_tokens": columnar["tokens"],
                    "saving_tokens": inferred["tokens"] - columnar["tokens"],
                    "saving_fraction": round(
                        (inferred["tokens"] - columnar["tokens"]) / inferred["tokens"], 4
                    ),
                }
    return {
        "t9_annotation_tax": t9,
        "l6_columnar_saving": l6,
        "note": (
            "T9 is a LOWER BOUND: the rules in lang/bakeoff/library.py carry no "
            "value defaults, so a real type checker recovers at least this much "
            "and probably more. L6 is measured on top of `inferred` only. Both "
            "are preliminary by construction — no type checker exists at M0 "
            "(roadmap Risk 8), and AMB-57/R59 re-measures against the real one."
        ),
    }
