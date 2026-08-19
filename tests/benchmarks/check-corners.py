#!/usr/bin/env python3
"""Re-derive the corner-survey evidence of each REQUIRED benchmark.

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
# DISTINCT (corner, measurement) identities in each benchmark's design.md
# corner table that must reconcile. Counting CELLS let a duplicated column pay
# for a deleted one -- the settling column, carrying the 45.39 us worst case,
# could leave the reader's table entirely. Its sibling gate had already learned
# this; this one repeated it the same day. 9 = three rows (9, 12 and 14 V) x
# three measurement columns. The comment used to derive it as 6 = two
# surveyed corners x three columns, on the grounds that the 12 V row is the
# nominal deck and held by check-assertions.py's transcript leg instead --
# but NOMINAL_VOLTS is checked here too, so the derivation described a gate
# this is not and a maintainer correcting 9 to 6 would have unpinned a row.
MINIMUM_DOC_CELLS = {"buck-3v3": 9}
# The deck's own supply voltage, whose design.md row has no corner block and
# is therefore held to validation.log instead.
NOMINAL_VOLTS = {"buck-3v3": 12.0}
# How far at least one measurement must move for a substitution to be a corner
# rather than a nudge. 1% is far below any real input-corner survey (the buck's
# 9 V and 14 V rows move ripple current by 13% and 6%) and far above numerical
# noise.
MINIMUM_CORNER_SHIFT = 0.01

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
    """[(old, new, {name: value}, header)] in file order.

    The HEADER (`--- V3 = 9 V ---`) is what design.md's corner table names in
    its first column. Deriving the corner's voltage from the substitution text
    instead worked only for the buck's PWL shape, so any other corner form
    silently skipped the design.md comparison entirely.
    """
    out, current = [], None
    for line in text.splitlines():
        found = RERUN.match(line)
        if found:
            current = [found.group("old"), found.group("new"), {}, ""]
            out.append(current)
            continue
        if current is None:
            continue
        header = re.match(r"^---\s*(?P<label>.+?)\s*---\s*$", line.strip())
        if header and not current[3]:
            current[3] = header.group("label")
            continue
        meas = MEAS.match(line.strip())
        if meas and meas.group("name").lower() not in NOT_A_MEASUREMENT:
            current[2].setdefault(meas.group("name").lower(), meas.group("value"))
    return [tuple(b) for b in out]


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

    # A CORNER MUST BE A DIFFERENT CIRCUIT. The gate checked that the
    # substitution's `old` text existed and that the run reproduced -- so two
    # blocks whose edits touched only ngspice COMMENT lines, carrying the
    # nominal 12 V measurements under 9 V and 14 V headers, passed and
    # satisfied the floor. il_pp at a real 14 V is 0.5119 A, not 0.4844.
    # A CORNER MUST BE A DIFFERENT CIRCUIT, tested by RUNNING both decks rather
    # than by inspecting the substitution's shape. The first version rejected
    # edits starting with `*` or `;`, which is a test for the literal previous
    # defect: a whitespace-only edit, or `.param LVAL=10u -> .param LVAL=10.0u`,
    # passed all of it and carried the nominal measurements under corner
    # headers. Whether a substitution changes the circuit is a question the
    # simulator answers.
    seen_edits = set()
    # Run the nominal deck ONCE, not once per block: it was 2 of the 4 ngspice
    # runs in this gate and scaled linearly with corner count for no
    # information.
    nominal_output = None
    reconciled = 0
    for old, new, recorded, header in found_blocks:
        if old == new:
            problems.append(
                f"{case_dir.name}/validation-corners.log: a `# rerun:` line "
                "substitutes a line for itself, so the 'corner' is the nominal "
                "deck.")
            continue
        if (old, new) in seen_edits:
            problems.append(
                f"{case_dir.name}/validation-corners.log: two corner blocks "
                "declare the same substitution, so one benchmark's floor is met "
                "by running the same corner twice.")
            continue
        # THE HEADER MUST DESCRIBE THE SUBSTITUTION. It was free text, so the
        # 9 V and 14 V labels could be swapped -- publishing ripple current
        # FALLING with input voltage and moving the worst case onto the wrong
        # rail -- with every gate green. Deriving the voltage from the
        # substitution alone was abandoned earlier because it only matched the
        # buck's PWL shape; the answer is to keep the header AND require the
        # two to agree.
        claimed = re.search(r"(\d+(?:\.\d+)?)\s*V", header)
        if claimed is None:
            problems.append(
                f"{case_dir.name}/validation-corners.log: block header "
                f"{header!r} names no voltage, so nothing binds this evidence "
                "to the corner it claims to survey.")
            continue
        # NOT followed by a SPICE unit suffix. `PWL(0 0 20u 0 220u 9 1 9)`
        # contains `20u`, so a header claiming 20 V bound to the 9 V edit and
        # republished 9 V ripple as 20 V ripple -- falling with input voltage,
        # and outside the design's own 9-14 V window. The reproduce check
        # cannot catch this: it re-runs the same substitution, so it binds the
        # numbers to the edit and never the edit to the claimed voltage.
        if not re.search(
                r"(?<![\d.])" + re.escape(claimed.group(1))
                + r"(?![\d])(?![munpkKMG]\w*)", new):
            problems.append(
                f"{case_dir.name}/validation-corners.log: header claims "
                f"{claimed.group(1)} V but the substitution it labels is "
                f"{new.strip()[:52]!r}, which does not contain that value. A "
                "label nothing binds to the edit lets the nominal deck publish "
                "as any corner at all. NOTE this is a cheap first check: a "
                "stray digit anywhere in the substitution satisfies it. What "
                "actually binds a block to its corner is the reproduce check "
                "below, which re-runs the edit and compares every recorded "
                "value; this one exists to give a clear message for the "
                "common case rather than a wall of mismatches.")
            continue
        seen_edits.add((old, new))
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
        if nominal_output is None:
            with tempfile.TemporaryDirectory() as tmp:
                nominal_output = run_deck(base, Path(tmp))
        nominal = nominal_output
        def _values(text):
            out = {}
            for line in text.splitlines():
                found = MEAS.match(line.strip())
                if found and found.group("name").lower() not in NOT_A_MEASUREMENT:
                    out.setdefault(found.group("name").lower(),
                                   float(found.group("value")))
            return out
        moved = _values(fresh)
        still = _values(nominal)
        shared = set(moved) & set(still)
        # MATERIALLY different, not merely different. At 1e-9 relative, a
        # substitution of `12` -> `12.0001` cleared the rule while producing
        # the nominal deck's numbers to four significant figures: the "9 V
        # corner" understated settling by 63%. A corner that moves nothing a
        # reader would notice is the nominal deck under another name.
        if shared and all(
                abs(moved[k] - still[k]) <= abs(still[k]) * MINIMUM_CORNER_SHIFT
                for k in shared):
            problems.append(
                f"{case_dir.name}/validation-corners.log: the substitution "
                f"{old.strip()[:32]!r} -> {new.strip()[:32]!r} produces "
                "measurements identical to the nominal deck, so this 'corner' "
                "is the nominal deck under another name. A corner has to be a "
                "different circuit, which is a question the simulator answers.")
            continue
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

    # THE TABLE A READER SEES. check-corners re-derives the LOG; the corner
    # figures a reader acts on are in design.md, whose corner table has no
    # verdict column and is therefore invisible to check-design-docs.py. So
    # 99.8 mVpp against a 50 mV spec sat in that table with both gates green --
    # the original finding, fully reachable, one file from the fix for it.
    doc = case_dir / "design.md"
    if doc.is_file():
        # BOUND BY COLUMN NAME. The first version matched a published cell
        # against ANY recorded value in the block, so a settling time satisfied
        # a ripple-current cell: 45.392 A of inductor ripple on a 2 A converter
        # -- 89x the physical value -- passed. The table's header names the
        # measurement each column carries, so that is what each cell is held to.
        header, rows, headerless = None, {}, 0
        for line in doc.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            if header is None and cells[0].lower() in ("vin", "v_in", "supply"):
                header = [c.lower() for c in cells[1:]]
                continue
            volt = re.match(r"^(\d+(?:\.\d+)?)\s*V$", cells[0])
            if volt:
                headerless += 1
                if header is not None:
                    rows[float(volt.group(1))] = cells[1:]
        if header is None and headerless:
            problems.append(
                f"{case_dir.name}/design.md: the corner table has no header row "
                "naming its measurements, so no cell can be bound to the "
                "measurement it claims to publish.")
        checked_cells = set()
        for old, new_line, recorded, block_header in found_blocks:
            volts = re.search(r"(\d+(?:\.\d+)?)\s*V", block_header)
            if volts is None:
                problems.append(
                    f"{case_dir.name}/validation-corners.log: block header "
                    f"{block_header!r} names no voltage, so its design.md row is "
                    "compared to nothing. Renaming a header silently switched "
                    "this whole leg off.")
                continue
            volt_value = float(volts.group(1))
            if volt_value not in rows:
                problems.append(
                    f"{case_dir.name}/design.md: publishes no corner row for "
                    f"{volt_value} V, which validation-corners.log surveys.")
                continue
            for name, cell in zip(header or [], rows[volt_value]):
                written = recorded.get(name)
                if written is None:
                    problems.append(
                        f"{case_dir.name}/design.md: the corner table has a "
                        f"{name!r} column, but the {volt_value} V block records "
                        "no such measurement.")
                    continue
                number = re.search(r"[-+]?\d+(?:\.\d+)?", cell)
                if number is None:
                    continue
                shown = float(number.group(0))
                if re.search(r"m(V|A)", cell):
                    shown *= 1e-3
                figures = min(significant_figures(number.group(0)),
                              significant_figures(written))
                if round_to_significant(shown, figures) != round_to_significant(
                        float(written), figures):
                    problems.append(
                        f"{case_dir.name}/design.md: publishes {cell!r} for "
                        f"{name} at {volt_value} V, but that corner produces "
                        f"{written}. The table a reader acts on is not the "
                        "evidence.")
                    continue
                checked_cells.add((volt_value, name))
        # A FLOOR on the design.md leg. Without one, the leg silently going to
        # zero coverage -- which renaming one block header did -- was
        # indistinguishable from passing.
        # THE NOMINAL ROW, held to validation.log rather than to a corner
        # block. Its voltage is the deck's own supply, so it has no `# rerun:`
        # entry and fell between the two gates.
        nominal_volts = NOMINAL_VOLTS.get(case_dir.name)
        if nominal_volts is not None and header is not None:
            transcript = case_dir / "validation.log"
            recorded_nominal = {}
            if transcript.is_file():
                for line in transcript.read_text(encoding="utf-8",
                                                 errors="replace").splitlines():
                    found = MEAS.match(line.strip())
                    if found and found.group("name").lower() not in NOT_A_MEASUREMENT:
                        recorded_nominal.setdefault(found.group("name").lower(),
                                                    found.group("value"))
            if nominal_volts not in rows:
                problems.append(
                    f"{case_dir.name}/design.md: publishes no corner row for the "
                    f"nominal {nominal_volts} V, so the deck's own operating "
                    "point is absent from the table a reader acts on.")
            elif not recorded_nominal:
                problems.append(
                    f"{case_dir.name}: validation.log records no measurements, "
                    "so the nominal corner row is compared to nothing.")
            else:
                for name, cell in zip(header, rows[nominal_volts]):
                    written = recorded_nominal.get(name)
                    if written is None:
                        problems.append(
                            f"{case_dir.name}/design.md: the corner table has a "
                            f"{name!r} column, but validation.log records no "
                            "such measurement for the nominal run.")
                        continue
                    number = re.search(r"[-+]?\d+(?:\.\d+)?", cell)
                    if number is None:
                        continue
                    shown = float(number.group(0))
                    if re.search(r"m(V|A)", cell):
                        shown *= 1e-3
                    figures = min(significant_figures(number.group(0)),
                                  significant_figures(written))
                    if round_to_significant(shown, figures) != round_to_significant(
                            float(written), figures):
                        problems.append(
                            f"{case_dir.name}/design.md: publishes {cell!r} for "
                            f"{name} at the nominal {nominal_volts} V, but the "
                            f"shipped deck produces {written}.")
                        continue
                    checked_cells.add((nominal_volts, name))

        expected_cells = MINIMUM_DOC_CELLS.get(case_dir.name)
        if expected_cells is not None and len(checked_cells) < expected_cells:
            problems.append(
                f"{case_dir.name}/design.md: reconciled {len(checked_cells)} corner "
                f"cell(s) against the evidence, below the floor of "
                f"{expected_cells}.")
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

    cases.append(("a corner that substitutes a line for itself is caught", any(
        "for itself" in p for p in probe(
            "# rerun: V1 in 0 DC 5 -> V1 in 0 DC 5\n--- x ---\nvout = 2.5\n"))))
    # A no-op substitution is now caught by RUNNING both decks, not by the
    # shape of the edited line -- so a whitespace-only edit is caught too,
    # which the shape rule missed.
    cases.append(("a substitution that changes nothing is caught by running it", any(
        "identical to the nominal deck" in p for p in probe(
            "# rerun: V1 in 0 DC 9 -> V1 in 0 DC 9.0\n--- 9 V ---\nvout = 4.5\n",
            deck=DECK.replace("V1 in 0 DC 5", "V1 in 0 DC 9")))))
    cases.append(("two blocks declaring the same substitution are caught", any(
        "same substitution" in p for p in probe(good + good))))
    # THE TABLE A READER SEES, which is where the original finding lived.
    cases.append(("a corner that moves the deck by less than the threshold is caught", any(
        "identical to the nominal deck" in p for p in probe(
            "# rerun: V1 in 0 DC 9 -> V1 in 0 DC 9.00001\n--- 9 V ---\n"
            "vout                =  4.50000e+00\n",
            deck=DECK.replace("V1 in 0 DC 5", "V1 in 0 DC 9")))))
    cases.append(("a header claiming a corner its substitution does not make is caught", any(
        "does not contain that value" in p for p in probe(
            "# rerun: V1 in 0 DC 5 -> V1 in 0 DC 9\n--- 14 V ---\nvout = 4.5\n"))))

    # THE DESIGN.MD TABLE, bound by column name.
    cases.append(("a design.md corner cell that disagrees is caught", any(
        "is not the evidence" in p for p in _doc_probe(
            "| Vin | vout |\n|---|---|\n| 9 V | 9.9 |", DECK, good))))
    cases.append(("a design.md corner cell that agrees is accepted", not
        _doc_probe("| Vin | vout |\n|---|---|\n| 9 V | 4.5 |", DECK, good)))
    cases.append(("a corner table with no header row is caught", any(
        "no header row" in p for p in _doc_probe("| 9 V | 4.5 |", DECK, good))))
    cases.append(("a column naming a measurement the block lacks is caught", any(
        "records no such measurement" in p for p in _doc_probe(
            "| Vin | ghost |\n|---|---|\n| 9 V | 4.5 |", DECK, good))))

    # THE DOC-CELL FLOOR, which was pinned by nothing: emptying it let the
    # design.md leg verify zero cells and still print PASS.
    cases.append(("the doc-cell floor fires when the table stops reconciling", any(
        "below the floor" in p for p in _doc_floor_probe())))

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


def _doc_floor_probe():
    """Drive the design.md leg with a REAL benchmark name, so the shipped
    floor applies rather than the probes' minimum=0."""
    import tempfile as _tf
    with _tf.TemporaryDirectory() as tmp:
        case = Path(tmp) / "buck-3v3"
        case.mkdir()
        (case / "netlist.cir").write_text(
            ".title p\nV1 in 0 DC 5\nR1 in out 1k\nR2 out 0 1k\n"
            ".tran 1u 100u\n.meas tran vout AVG v(out) FROM=50u TO=100u\n.end\n",
            encoding="utf-8")
        (case / "validation-corners.log").write_text(
            "# rerun: V1 in 0 DC 5 -> V1 in 0 DC 9\n--- 9 V ---\n"
            "vout                =  4.50000e+00\n", encoding="utf-8")
        (case / "design.md").write_text(
            "| Vin | vout |\n|---|---|\n| 9 V | see log |\n", encoding="utf-8")
        problems = []
        check_case(case, problems, minimum=0)
        return problems


def _doc_probe(doc_row, deck, evidence):
    """Drive the design.md corner-table leg over a throwaway case."""
    with tempfile.TemporaryDirectory() as tmp:
        case = Path(tmp) / "case"
        case.mkdir()
        (case / "netlist.cir").write_text(deck, encoding="utf-8")
        (case / "validation-corners.log").write_text(evidence, encoding="utf-8")
        (case / "design.md").write_text(doc_row + "\n", encoding="utf-8")
        problems = []
        check_case(case, problems, minimum=0)
        return problems


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
