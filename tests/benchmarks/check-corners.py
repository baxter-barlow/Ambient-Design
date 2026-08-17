#!/usr/bin/env python3
"""Re-derive each benchmark's corner-survey evidence by running the corner.

WHY THIS EXISTS. benchmarks/buck-3v3/design.md published three input-corner
figures -- 0.515 App at 14 V, 39.4 us at 9 V, 3.14 mVpp at 9 V -- and cited
"supplementary runs in `validation.log`". An auditor found that none of the
three came from the shipped deck: two were the 31.6k divider at 2 ns and one
was the 31.6k divider at 40 ns. The cited runs were not in validation.log
either; the only occurrence of the word "corner" in that file was the line
recording that an earlier regeneration had destroyed them.

So the corner survey was never re-run when the divider changed, the document
asserted evidence its own evidence file said was deleted, and worst-case
settling was 15% larger than published. Nothing could have caught it, because
a corner run is a run of a MODIFIED deck and no gate reproduced those.

WHAT IT CHECKS. `validation-corners.log` declares, per block, the single deck
substitution that produced it:

    # rerun: V3 in 0 PWL(...12 1 12) -> V3 in 0 PWL(...9 1 9)
    --- V3 = 9 V ---
    vout_avg = ...

This applies that edit to the benchmark's netlist.cir, runs ngspice, and holds
every recorded measurement to the result at the precision the file states. A
corner figure is then evidence that can be re-derived rather than a number in
a file.

Exit codes: 0 pass, 1 a corner does not reproduce, 2 environment failure.

    python3 tests/benchmarks/check-corners.py --self-test
    python3 tests/benchmarks/check-corners.py [<benchmark-dir>...]
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Benchmarks that MUST carry a corner survey. Named, so a benchmark cannot
# leave this gate by deleting its own evidence -- the failure mode run-sim.sh
# learned twice and check-assertions.py learned once.
REQUIRED = {"buck-3v3": 2}

RERUN = re.compile(r"^#\s*rerun:\s*(?P<old>.+?)\s*->\s*(?P<new>.+?)\s*$")
MEAS = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?P<value>[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\b")
NOT_A_MEASUREMENT = {"exit"}
BUDGET_SECONDS = 120


class GateUnavailable(Exception):
    """The check could not be performed. Never reported as a pass."""


def significant_figures(text):
    digits = re.search(r"\d[\d.]*", str(text).strip().lstrip("+-").split("e")[0].split("E")[0])
    if not digits:
        return 1
    return max(1, len(digits.group(0).replace(".", "").lstrip("0")))


def round_to_significant(value, figures):
    if value == 0:
        return 0.0
    from math import floor, log10
    return round(value, -int(floor(log10(abs(value)))) + (figures - 1))


def blocks(text):
    """[(old_line, new_line, {name: written_value})] in file order."""
    out, current = [], None
    for line in text.splitlines():
        found = RERUN.match(line)
        if found:
            current = (found.group("old"), found.group("new"), {})
            out.append(current)
            continue
        if current is None:
            continue
        meas = MEAS.match(line.strip())
        if meas and meas.group("name").lower() not in NOT_A_MEASUREMENT:
            current[2].setdefault(meas.group("name").lower(), meas.group("value"))
    return out


def run_deck(deck_text, work_dir):
    deck = work_dir / "netlist.cir"
    deck.write_text(deck_text, encoding="utf-8")
    log = work_dir / "out.log"
    try:
        subprocess.run(["ngspice", "-b", "netlist.cir", "-o", "out.log"],
                       cwd=work_dir, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=BUDGET_SECONDS,
                       check=False)
    except FileNotFoundError as exc:
        raise GateUnavailable(
            "ngspice is not installed; an unavailable gate is not a pass.") from exc
    except subprocess.TimeoutExpired as exc:
        raise GateUnavailable(
            f"a corner deck exceeded {BUDGET_SECONDS}s.") from exc
    return log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""


def check_case(case_dir, problems, minimum=None):
    """Returns the number of corner measurements reconciled."""
    evidence = case_dir / "validation-corners.log"
    deck_path = case_dir / "netlist.cir"
    if not evidence.is_file():
        if case_dir.name in REQUIRED:
            problems.append(
                f"{case_dir.name}: has no validation-corners.log. design.md "
                "cites a corner survey; a missing one is how the last survey "
                "came to be two revisions stale with every gate green.")
        return 0
    if not deck_path.is_file():
        problems.append(f"{case_dir.name}: has no netlist.cir to re-run corners against")
        return 0

    base = deck_path.read_text(encoding="utf-8")
    found_blocks = blocks(evidence.read_text(encoding="utf-8"))
    expected = REQUIRED.get(case_dir.name) if minimum is None else minimum
    if expected is not None and len(found_blocks) < expected:
        problems.append(
            f"{case_dir.name}/validation-corners.log: declares "
            f"{len(found_blocks)} corner(s), but this benchmark must survey "
            f"{expected}. Deleting a corner block is not a way to pass.")

    reconciled = 0
    for old, new, recorded in found_blocks:
        if old not in base:
            problems.append(
                f"{case_dir.name}/validation-corners.log: the `# rerun:` line "
                f"names {old!r}, which is not in netlist.cir. The deck moved and "
                "this evidence describes a line that no longer exists.")
            continue
        if not recorded:
            problems.append(
                f"{case_dir.name}/validation-corners.log: the corner for "
                f"{new!r} records no measurements.")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            fresh = run_deck(base.replace(old, new, 1), Path(tmp))
        produced = {}
        for line in fresh.splitlines():
            meas = MEAS.match(line.strip())
            if meas:
                produced.setdefault(meas.group("name").lower(), meas.group("value"))
        for name, written in recorded.items():
            if name not in produced:
                problems.append(
                    f"{case_dir.name} corner {new!r}: records `{name}`, which "
                    "this deck no longer emits.")
                continue
            want, got = float(written), float(produced[name])
            figures = min(significant_figures(written),
                          significant_figures(produced[name]))
            if round_to_significant(want, figures) != round_to_significant(got, figures):
                problems.append(
                    f"{case_dir.name} corner {new!r}: records {name} = "
                    f"{want:.6g}, but re-running that corner gives {got:.6g}. "
                    "The published corner figure is not this deck's.")
                continue
            reconciled += 1
    return reconciled


def self_test():
    DECK = (".title probe\n"
            "V1 in 0 DC 5\n"
            "R1 in out 1k\n"
            "R2 out 0 1k\n"
            ".tran 1u 100u\n"
            ".meas tran vout AVG v(out) FROM=50u TO=100u\n"
            ".end\n")

    def probe(evidence_body, deck=DECK):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp) / "case"
            case.mkdir()
            (case / "netlist.cir").write_text(deck, encoding="utf-8")
            (case / "validation-corners.log").write_text(evidence_body, encoding="utf-8")
            problems = []
            check_case(case, problems, minimum=0)
            return problems

    # 5 V across two equal 1k resistors -> 2.5 V; at 9 V -> 4.5 V.
    good = ("# rerun: V1 in 0 DC 5 -> V1 in 0 DC 9\n"
            "--- 9 V ---\n"
            "vout                =  4.50000e+00\n")
    cases = [
        ("a corner that reproduces reports nothing", not probe(good)),
        ("a corner figure the deck does not produce is caught", any(
            "not this deck's" in p for p in probe(
                good.replace("4.50000e+00", "9.90000e+00")))),
        ("a rerun line naming a vanished deck line is caught", any(
            "no longer exists" in p for p in probe(
                good.replace("V1 in 0 DC 5 ->", "V9 in 0 DC 5 ->")))),
        ("a corner block with no measurements is caught", any(
            "records no measurements" in p for p in probe(
                "# rerun: V1 in 0 DC 5 -> V1 in 0 DC 9\n--- 9 V ---\n"))),
        ("a measurement the deck dropped is caught", any(
            "no longer emits" in p for p in probe(
                good.replace("vout  ", "vghost")))),
        # The rounding rule everywhere else here: coarser of the two.
        ("a corner rounded to fewer figures is not failed", not probe(
            good.replace("4.50000e+00", "4.5e+00"))),
        ("the corner floor fires when a block is deleted", any(
            "must survey" in p for p in (lambda: (lambda ps: ps)(_floor_probe()))())),
    ]

    # WIRING, over the real entry point.
    import contextlib, io
    with tempfile.TemporaryDirectory() as tmp:
        case = Path(tmp) / "case"
        case.mkdir()
        (case / "netlist.cir").write_text(DECK, encoding="utf-8")
        (case / "validation-corners.log").write_text(
            good.replace("4.50000e+00", "9.90000e+00"), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            planted = main([str(case)])
        (case / "validation-corners.log").write_text(good, encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            clean = main([str(case)])
    cases.append(("main() exits 1 when a corner does not reproduce", planted == 1))
    cases.append(("main() exits 0 when every corner does", clean == 0))

    failures = 0
    for name, ok in cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        print(f"corners: SELF-TEST FAILED: {failures} case(s)", file=sys.stderr)
        return 1
    print(f"corners: self-test PASS: {len(cases)} cases.")
    return 0


def _floor_probe():
    """The floor is a statement about a real benchmark, so it is exercised with
    a named one rather than with the probes' minimum=0."""
    with tempfile.TemporaryDirectory() as tmp:
        case = Path(tmp) / "buck-3v3"
        case.mkdir()
        (case / "netlist.cir").write_text(
            ".title p\nV1 in 0 DC 5\nR1 in out 1k\nR2 out 0 1k\n"
            ".tran 1u 100u\n.meas tran vout AVG v(out) FROM=50u TO=100u\n.end\n",
            encoding="utf-8")
        (case / "validation-corners.log").write_text(
            "# rerun: V1 in 0 DC 5 -> V1 in 0 DC 9\n--- 9 V ---\n"
            "vghost = 1.0\n", encoding="utf-8")
        problems = []
        check_case(case, problems)
        return problems


def main(argv):
    if argv and argv[0] == "--self-test":
        return self_test()
    if argv:
        cases = [Path(a) for a in argv]
    else:
        cases = [ROOT / "benchmarks" / name for name in sorted(REQUIRED)]
        for case in cases:
            if not case.is_dir():
                print(f"corners: FAIL: {case.name} is missing.", file=sys.stderr)
                return 1

    problems, total = [], 0
    try:
        for case in cases:
            total += check_case(case, problems)
    except GateUnavailable as exc:
        print(f"corners: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2

    if problems:
        print("corners: FAIL:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"corners: PASS: {total} corner measurement(s) re-derived by "
          "re-running the corner.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
