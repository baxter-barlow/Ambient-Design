#!/usr/bin/env python3
"""Hold each benchmark's design.md to the numbers its assertions.yaml records.

WHY THIS EXISTS. Lowering buck-3v3's feedback divider from 31.6k to 31.2k moved
every measured value in the deck. The five gated ones in `assertions.yaml` were
re-recorded; thirteen numbers in `design.md` were not, because NO CODE IN THIS
REPOSITORY READ design.md. The repository shipped a correct transcript and a
contradicting narrative side by side for as long as that was true, and the
document that justifies the 2 ns timestep described a deck that no longer
existed. blinker-555's doc had the same defect from the same cause: it published
the pre-fix oscillator windows in three places.

Fixing the numbers by hand does not fix that. This does.

WHAT IT CHECKS. Each design.md carries a results table whose header ends in a
verdict column:

    | Assertion | Predicted window | Measured | Verdict |
    | Mean Vout (2 A) | 3.3 V +/-3% | 3.2960 V (-0.12%) | pass |

Every row's measured figure must agree with the `measured:` its assertion
records, to the precision the table itself states. Rows are matched to
assertions by `meas_id` or `name` appearing in the row's first cell, so
renaming a row breaks the link loudly rather than quietly.

WHAT IT DELIBERATELY DOES NOT CHECK. Prose. A gate that tried to parse every
number out of English would either fail open on rephrasing or fight the author
on every edit. The results table is the part a reader treats as authoritative,
so that is the part held to the data. Numbers in prose are still the author's
job -- but a stale table is what made the prose worth doubting.

Exit codes: 0 pass, 1 a table disagrees with its assertions, 2 environment.

    python3 tests/benchmarks/check-design-docs.py --self-test
    python3 tests/benchmarks/check-design-docs.py <benchmark-dir>...
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Benchmarks that MUST carry a checkable table. Enumerating from the filesystem
# would let a benchmark leave the gate by deleting its own doc, which is the
# failure mode run-sim.sh already learned twice.
# name -> how many results rows that benchmark MUST publish. Deriving the floor
# from the document (`floor = len(rows)`) meant a row escaping the parser also
# lowered the bar: de-verdicting four of buck's five rows reported "6 rows agree"
# and exited 0. These counts are the answer to "how many rows should be here",
# which the document cannot be trusted to supply.
REQUIRED = {"blinker-555": 5, "buck-3v3": 5}

# A row is `| cell | cell | ... |`. The verdict column is the last cell.
ROW = re.compile(r"^\|(?P<cells>.+)\|\s*$")
# A verdict cell, however it is dressed. `^(pass|fail|PASS|FAIL)$` meant a row
# opted out of the gate by writing `Pass`, `pass (see note)` or `pass /checkmark/`
# -- one character in a cell no reader treats as data, and four of buck's five
# rows left the gate that way with `make all` green.
VERDICT = re.compile(r"^(pass|fail)\b", re.IGNORECASE)
# The first number in a cell, with an optional unit and an optional sign.
NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


class GateUnavailable(Exception):
    """The check could not be performed. Never reported as a pass."""


def _cells(line):
    found = ROW.match(line.rstrip())
    if not found:
        return None
    return [c.strip() for c in found.group("cells").split("|")]


def _first_number(cell):
    found = NUMBER.search(cell.replace(",", ""))
    return None if found is None else float(found.group(0))


# SI prefixes a doc may state a measurement in. The buck writes ripple as
# "3.587 mVpp" and records it as 0.00359 V; those are one measurement.
SI = {"n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6}
PREFIXED = re.compile(r"\d\s*(?P<prefix>[numkM])(?P<unit>[A-Za-z])")


def _scale_of(cell):
    """The multiplier the CELL's unit implies, relative to the base unit."""
    found = PREFIXED.search(cell)
    return SI[found.group("prefix")] if found else 1.0


# Significant digits: leading zeros are not significant, TRAILING ONES ARE.
SIGNIFICANT = re.compile(r"\d[\d.]*")


def _sig_figs(cell):
    """Significant figures the cell states.

    Comparison happens at the COARSER of the two, so a doc rounded to four
    figures is not failed by a record carrying three.

    This used to `rstrip("0")`, which made "3.000" ONE significant figure --
    so a design.md publishing 3.000 V against a recorded 3.296 V reconciled at
    a single figure, printed `pass`, and sat next to a +/-3 % window the value
    is outside. "20 us" against 16.86 did the same. It is now the identical
    function check-assertions.py uses on `measured:`; the two gates disagreeing
    about what a figure is was the defect.
    """
    text = str(cell).replace(",", "").strip()
    found = SIGNIFICANT.search(text.lstrip("+-").split("e")[0].split("E")[0])
    if not found:
        return 0
    return max(1, len(found.group(0).replace(".", "").lstrip("0")))


def _round_sig(value, figures):
    if value == 0 or figures <= 0:
        return 0.0
    from math import floor, log10
    return round(value, -int(floor(log10(abs(value)))) + (figures - 1))


def result_rows(text):
    """Every row of every table whose last column holds a verdict."""
    rows = []
    for line in text.splitlines():
        cells = _cells(line)
        if not cells or len(cells) < 3:
            continue
        if VERDICT.match(cells[-1]):
            rows.append(cells)
    return rows


def check_case(case_dir, problems, minimum=None):
    """Returns the number of rows reconciled."""
    doc = case_dir / "design.md"
    spec = case_dir / "assertions.yaml"
    if not doc.is_file():
        problems.append(f"{case_dir.name}: has no design.md")
        return 0
    if not spec.is_file():
        problems.append(f"{case_dir.name}: has no assertions.yaml")
        return 0

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise GateUnavailable(
            "PyYAML is required; install the pin (python3 -m pip install pyyaml==6.0.2)."
        ) from exc
    parsed = yaml.safe_load(spec.read_text(encoding="utf-8")) or {}
    assertions = parsed.get("assertions") or []

    rows = result_rows(doc.read_text(encoding="utf-8"))
    if not rows:
        problems.append(
            f"{case_dir.name}/design.md: has no results table (no row whose last "
            "column is a verdict), so nothing in it is held to the recorded "
            "measurements. That is the state both benchmark docs were in when "
            "thirteen numbers went stale.")
        return 0

    reconciled = 0
    for cells in rows:
        label = cells[0]
        match = None
        for assertion in assertions:
            for key in ("meas_id", "name", "id"):
                value = assertion.get(key)
                if value and str(value) in label:
                    match = assertion
                    break
            if match:
                break
        if match is None:
            problems.append(
                f"{case_dir.name}/design.md: results row {label!r} matches no "
                "assertion by meas_id, name or id. Either the row is stale or an "
                "assertion was renamed; both are the drift this gate exists for.")
            continue
        recorded = match.get("measured")
        if recorded is None:
            continue
        want = _first_number(str(recorded))
        # The MEASURED column: second from the right, before the verdict.
        got = _first_number(cells[-2])
        if want is None or got is None:
            problems.append(
                f"{case_dir.name}/design.md: row {label!r} states "
                f"{cells[-2]!r} against a recorded {recorded!r}; one of them "
                "carries no number to compare.")
            continue
        # PERCENT vs FRACTION. The buck states efficiency as 92.864 % and
        # records it as 0.92864; those are the same measurement in two
        # notations, and failing on it would be fighting the author over units
        # instead of catching drift. Rescaled only when the table says `%` and
        # the recorded value is a fraction, so a genuinely wrong number in
        # either notation still fails.
        if "%" in cells[-2] and abs(want) <= 1.0 and abs(got) > 1.0:
            want = want * 100.0
        # Into the DOC's unit: "3.587 mVpp" against a recorded 0.00359 V.
        # The RECORDED value's unit comes from the assertion, not from guessing:
        # `measured: 16.86` under `expected.unit: us` is microseconds, and
        # reading it as seconds turned a matching row into a 1e7 discrepancy.
        declared_unit = (match.get("reported_unit")
                         or (match.get("expected") or {}).get("unit")
                         if isinstance(match.get("expected"), dict)
                         else match.get("reported_unit"))
        recorded_text = f"{recorded} {declared_unit or ''}".strip()
        recorded_scale, doc_scale = _scale_of(recorded_text), _scale_of(cells[-2])
        want = want * recorded_scale / doc_scale
        figures = min(_sig_figs(cells[-2]), _sig_figs(str(recorded)))
        if _round_sig(got, figures) != _round_sig(want, figures):
            problems.append(
                f"{case_dir.name}/design.md: row {label!r} publishes {got} but "
                f"assertions.yaml records {recorded!r} (= {want:.6g} in the "
                "table's own unit). The document a reader trusts disagrees "
                "with the run that gates.")
            continue
        reconciled += 1

    expected = REQUIRED.get(case_dir.name) if minimum is None else minimum
    if expected is not None and len(rows) < expected:
        problems.append(
            f"{case_dir.name}/design.md: publishes {len(rows)} results row(s), "
            f"but this benchmark must publish {expected}. A row leaves this gate "
            "by losing its verdict cell, so the count is pinned here rather than "
            "read from the document.")
    floor = len(rows) if minimum is None else minimum
    if reconciled < floor:
        problems.append(
            f"{case_dir.name}/design.md: only {reconciled} of {len(rows)} "
            f"results row(s) reconciled against assertions.yaml.")
    return reconciled


def self_test():
    import tempfile

    SPEC = (
        "assertions:\n"
        "  - name: osc_period\n    meas_id: t_period\n    measured: 1.01191 s\n"
        "  - name: duty_cycle_high\n    meas_id: duty_pct\n    measured: 53.45 %\n"
    )

    def probe(doc_body, spec=SPEC):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp) / "case"
            case.mkdir()
            (case / "design.md").write_text(doc_body, encoding="utf-8")
            (case / "assertions.yaml").write_text(spec, encoding="utf-8")
            problems = []
            check_case(case, problems)
            return problems

    agreeing = (
        "| Assertion | Window | Measured | Verdict |\n"
        "|---|---|---|---|\n"
        "| t_period | 0.951 - 1.083 s | 1.01191 s | PASS |\n"
        "| duty_pct | 53.3 - 55.8 % | 53.45 % | PASS |\n")

    cases = [
        ("a table agreeing with its assertions passes", not probe(agreeing)),
        ("a stale measured value is caught", any(
            "disagrees with the run" in p for p in probe(
                agreeing.replace("1.01191 s", "1.07300 s")))),
        # THE ACTUAL DEFECT: buck's doc kept the pre-divider figures.
        ("the buck's real drift shape is caught", any(
            "disagrees with the run" in p for p in probe(
                agreeing.replace("53.45 %", "0.11 %")))),
        ("a row matching no assertion is caught", any(
            "matches no assertion" in p for p in probe(
                agreeing.replace("| duty_pct |", "| ghost_meas |")))),
        ("a document with no results table is caught", any(
            "no results table" in p for p in probe("# Design\n\nProse only.\n"))),
        # A doc rounded to three figures must not be failed by a run that
        # agrees to three figures -- the same rule check-assertions.py applies.
        ("a rounded table is not failed by a longer recorded value", not probe(
            agreeing.replace("1.01191 s", "1.012 s"))),
        ("a missing design.md is caught", any(
            "has no design.md" in p for p in [
                *(lambda: (lambda ps: ps)([]))(),
                *_missing_doc_probe()])),
    ]

    # WIRING, over the real entry point: everything above drives check_case.
    import contextlib, io
    with tempfile.TemporaryDirectory() as tmp:
        case = Path(tmp) / "case"
        case.mkdir()
        (case / "assertions.yaml").write_text(SPEC, encoding="utf-8")
        (case / "design.md").write_text(
            agreeing.replace("1.01191 s", "9.99999 s"), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            planted = main([str(case)])
        (case / "design.md").write_text(agreeing, encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            clean = main([str(case)])
    cases.append(("main() exits 1 when a table disagrees", planted == 1))
    cases.append(("main() exits 0 when it agrees", clean == 0))

    failures = 0
    for name, ok in cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        print(f"design-docs: SELF-TEST FAILED: {failures} case(s)", file=sys.stderr)
        return 1
    print(f"design-docs: self-test PASS: {len(cases)} cases.")
    return 0


def _missing_doc_probe():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        case = Path(tmp) / "case"
        case.mkdir()
        (case / "assertions.yaml").write_text("assertions: []\n", encoding="utf-8")
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
                print(f"design-docs: FAIL: {case.name} is missing; a benchmark "
                      "cannot leave this gate by deleting its directory.",
                      file=sys.stderr)
                return 1

    problems = []
    total = 0
    try:
        for case in cases:
            total += check_case(case, problems)
    except GateUnavailable as exc:
        print(f"design-docs: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2

    if problems:
        print("design-docs: FAIL:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"design-docs: PASS: {total} results row(s) agree with the "
          "measurements their benchmarks record.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
