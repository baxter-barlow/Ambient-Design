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

import pathlib
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
# 2 assertions x 2 artifacts, counted as DISTINCT (file, measurement)
# identities: counting matches let a duplicated assertion pay for a renamed one.
MINIMUM_MODEL_WINDOWS = 4

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


# THE PREDICTED-WINDOW COLUMN. This gate's docstring says the results table is
# "the part a reader treats as authoritative, so that is the part held to the
# data" -- and it read only the Measured cell. The window IS the assertion, and
# ten window cells across the two gated design.md files were read by nothing:
# an auditor changed f_osc's published window to 88.923 - 99.052 Hz, ninety
# times outside the measurement in the very next cell, and `make all` exited 0
# with the row still marked PASS. model_problems() below does exactly this
# comparison for the two JSON artifacts; the population was scoped to those and
# left out the Markdown table this gate exists for.
RANGE = re.compile(
    r"(?P<lo>[-+]?\d[\d.]*(?:[eE][-+]?\d+)?)\s*[–—-]\s*"
    r"(?P<hi>[-+]?\d[\d.]*(?:[eE][-+]?\d+)?)")
AT_MOST = re.compile(r"<=\s*(?P<value>[-+]?\d[\d.]*(?:[eE][-+]?\d+)?)")
AT_LEAST = re.compile(r">=\s*(?P<value>[-+]?\d[\d.]*(?:[eE][-+]?\d+)?)")
TOLERANCE = re.compile(
    r"(?P<centre>[-+]?\d[\d.]*)\s*(?P<unit>[A-Za-z]*)\s*"
    r"(?:\+/-|±)\s*(?P<span>\d[\d.]*)\s*%")


def _percent_scale(cell):
    """Percent cells carry their own factor; `%` and `percent` both mean 1/100.

    The buck states efficiency as ">= 85%" and declares it as 0.85 `ratio`, and
    states overshoot as "<= 5%" against 5.0 `percent`. Both are the same number
    once percent is a scale rather than a spelling.
    """
    return 0.01 if "%" in cell or "percent" in cell.lower() else 1.0


def published_window(cell):
    """(low, high) in base units from a design.md window cell.

    `None` on either side means the document states no bound there. `(None,
    None)` means the cell carries no window this can read, which the caller
    reports rather than skipping.
    """
    text = cell.strip()
    if not text:
        return (None, None)
    tolerance = TOLERANCE.search(text)
    if tolerance:
        centre = float(tolerance.group("centre")) * _scale_of(
            tolerance.group("centre") + tolerance.group("unit"))
        span = float(tolerance.group("span")) / 100.0
        return (centre * (1 - span), centre * (1 + span))
    scale = _scale_of(text) * _percent_scale(text)
    spread = RANGE.search(text)
    if spread:
        return (float(spread.group("lo")) * scale,
                float(spread.group("hi")) * scale)
    most = AT_MOST.search(text)
    if most:
        return (None, float(most.group("value")) * scale)
    least = AT_LEAST.search(text)
    if least:
        return (float(least.group("value")) * scale, None)
    return (None, None)


def declared_window(assertion):
    """(low, high) in base units from an assertions.yaml entry."""
    window = assertion.get("window")
    if isinstance(window, list) and len(window) == 2:
        return tuple(
            float(str(bound).split()[0]) * _scale_of(str(bound))
            * _percent_scale(str(bound)) for bound in window)
    expected = assertion.get("expected")
    if isinstance(expected, dict):
        unit = str(expected.get("unit") or "")
        scale = _scale_of("0" + unit) * _percent_scale(unit)
        low = expected.get("min")
        high = expected.get("max")
        return (None if low is None else float(low) * scale,
                None if high is None else float(high) * scale)
    return (None, None)


def _agree(a, b):
    """Two bounds agree when both are absent, or equal to the digits published.

    The document rounds: the buck publishes `3.3 V +/-3%` where the spec says
    3.201/3.399, and `<= 50 mVpp` where it says 0.05 V. A relative tolerance
    absorbs the rounding without absorbing a wrong number -- the smallest real
    error found in this table was 100x.
    """
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))


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
    windows_reconciled = set()
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

        # THE PREDICTED-WINDOW COLUMN, third from the right. See the comment on
        # published_window: this is the number a reader acts on and it was held
        # to nothing.
        if len(cells) >= 4:
            stated = published_window(cells[-3])
            spec_window = declared_window(match)
            if stated == (None, None) and spec_window != (None, None):
                problems.append(
                    f"{case_dir.name}/design.md: row {label!r} publishes "
                    f"{cells[-3]!r} in the window column, which states no bound "
                    "this gate can read, while assertions.yaml declares "
                    f"{spec_window}. A window a reader cannot check against the "
                    "spec is the column being decorative.")
            elif not (_agree(stated[0], spec_window[0])
                      and _agree(stated[1], spec_window[1])):
                problems.append(
                    f"{case_dir.name}/design.md: row {label!r} publishes window "
                    f"{cells[-3]!r} = {stated} but assertions.yaml declares "
                    f"{spec_window} (base units). The published window IS the "
                    "assertion; a document and a gate stating different ones is "
                    "the drift this table exists to prevent.")
            else:
                windows_reconciled.add((case_dir.name, label))

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
        # Rescale ONLY when the assertion declares a unit that says the
        # recorded value is a fraction. Testing "is a fraction" as `<= 1.0` is
        # true of any sub-1% percentage, so `overshoot_pct` -- recorded 0.0466
        # with unit `percent` -- reconciled against a published 4.66%, a clean
        # 100x error absorbed by the gate whose whole job is stale numbers.
        declared_unit = str(
            (match.get("expected") or {}).get("unit")
            if isinstance(match.get("expected"), dict)
            else match.get("reported_unit") or "").strip().lower()
        recorded_is_fraction = declared_unit in ("", "1", "fraction", "ratio")
        if "%" in cells[-2] and recorded_is_fraction and abs(want) <= 1.0:
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

    # DISTINCT LABELS, not row count. Deleting the buck's efficiency row and
    # duplicating its ripple row left "10 results row(s) agree" -- the sibling
    # gate has a case named "a duplicated row cannot pay for a missing one" and
    # MINIMUM_MODEL_WINDOWS in this same file counts distinct identities for
    # exactly this reason; check_case was left counting rows.
    labels = [r[0] for r in rows]
    duplicates = sorted({l for l in labels if labels.count(l) > 1})
    if duplicates:
        problems.append(
            f"{case_dir.name}/design.md: the results table publishes "
            f"{duplicates} more than once. A duplicate row can pay for a "
            "deleted one while the reported count stays honest-looking.")
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
    # The window column gets its own floor, over DISTINCT labels, for the same
    # reason the measured column does. Sharing one counter would let a
    # reconciled measurement pay for an unread window.
    if len(windows_reconciled) < floor:
        problems.append(
            f"{case_dir.name}/design.md: only {len(windows_reconciled)} of "
            f"{len(rows)} published window(s) reconciled against "
            "assertions.yaml. A window column nothing reads is the column a "
            "reader trusts most.")
    return reconciled


def self_test():
    import tempfile

    SPEC = (
        "assertions:\n"
        "  - name: osc_period\n    meas_id: t_period\n"
        "    window: ['0.951 s', '1.083 s']\n    measured: 1.01191 s\n"
        "  - name: duty_cycle_high\n    meas_id: duty_pct\n"
        "    window: ['53.3 %', '55.8 %']\n    measured: 53.45 %\n"
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

    def _card_probe(card_text):
        problems = []
        card_problems(problems, cards={"probe": card_text})
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
        # THE WINDOW COLUMN. An auditor widened f_osc's published window to
        # ninety times outside its own measurement in the next cell and every
        # gate stayed green: only the Measured cell was ever read.
        ("a published window the spec does not declare is caught", any(
            "publishes window" in p for p in probe(
                agreeing.replace("0.951 - 1.083 s", "0.710 - 1.638 s")))),
        ("a widened window is caught in the other direction too", any(
            "publishes window" in p for p in probe(
                agreeing.replace("53.3 - 55.8 %", "1.0 - 99.0 %")))),
        ("a window cell with no readable bound is caught", any(
            "states no bound" in p for p in probe(
                agreeing.replace("0.951 - 1.083 s", "see below")))),
        ("the window floor fires when a row loses its window column", any(
            "published window(s) reconciled" in p for p in probe(
                "| Assertion | Measured | Verdict |\n"
                "|---|---|---|\n"
                "| t_period | 1.01191 s | PASS |\n"
                "| duty_pct | 53.45 % | PASS |\n"))),
        # THE LANGUAGE CARDS, both directions over a fixture. The shipped three
        # agree today, so a wiring case over them alone cannot tell "the cards
        # are right" from "nothing looked".
        ("a card teaching an undeclared window is caught", any(
            "which is not a bound" in p and "9.923" in p
            for p in _card_probe(
                "## Assertions\n\n"
                "    assert f dynamic frequency(OUT) within 9.923Hz to 91.052Hz\n"
                "    assert d dynamic duty_cycle(OUT) within 0.533 to 0.558\n"))),
        ("a card teaching the declared windows passes", not _card_probe(
            "## Assertions\n\n"
            "    assert f dynamic frequency(OUT) within 0.923Hz to 1.052Hz\n"
            "    assert d dynamic duty_cycle(OUT) within 0.533 to 0.558\n"
            "    m.check(min=\"0.951\", max=\"1.083\")\n")),
        ("a card whose Assertions section lost its numbers is caught", any(
            "states no window at all" in p or "below the floor" in p
            for p in _card_probe("## Assertions\n\nnothing numeric here\n"))),
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

    # WIRING OVER THE REAL TREE. Both wiring cases above pass explicit
    # directories, so emptying REQUIRED, zeroing the floor or narrowing the
    # verdict regex left the self-test green while the gate checked nothing.
    import contextlib as _c, io as _io
    with _c.redirect_stdout(_io.StringIO()) as _out, _c.redirect_stderr(_io.StringIO()):
        default_code = main([])
    default_text = _out.getvalue()
    cases.append(("main() with no arguments checks the real benchmarks",
                  default_code == 0 and "PASS: 10 results row(s)" in default_text))
    # EVERY COUNT IN THE SUMMARY, not just the first. Each of the other three
    # legs could be unwired -- `x = leg(problems) if not argv else 0` rewritten
    # to `x = 0` -- with all 18 cases green, because the case above reads one
    # clause of a sentence that reports four numbers.
    for _count, _noun in ((MINIMUM_MODE_ROWS, "mode-current row(s)"),
                          (MINIMUM_MODEL_WINDOWS, "model/IR assertion window(s)"),
                          (3, "AC1a line count(s)")):
        cases.append((f"main() reports {_count} {_noun}",
                      f"{_count} {_noun}" in default_text))
    # Narrowing VERDICT back to ^(pass|PASS)$ breaks no real row, because no
    # real row uses `Pass` -- which is exactly why a row could escape by
    # adopting one. Pinned directly.
    cases.append(("a dressed verdict cell is still a verdict", all(
        len(result_rows(agreeing.replace("| PASS |", f"| {form} |"))) == 2
        for form in ("Pass", "pass (see note)", "PASS - ok", "fail"))))
    cases.append(("a cell that is not a verdict is not read as one", not
        result_rows(agreeing.replace("| PASS |", "| passenger count |"))))
    # THE MODEL/IR LEG, which had no case at all -- emptying MODEL_LINKS left
    # the self-test green and the gate reporting 0 windows.
    cases.append(("the model/IR window leg reconciles the real artifacts",
                  model_problems([]) >= MINIMUM_MODEL_WINDOWS))
    cases.append(("MODEL_LINKS names the blinker model AND its IR",
                  {(m.name, i.name) for _, m, i in MODEL_LINKS} ==
                  {("blinker-555.design.json", "blinker.ir.json")}))
    # THE MODE TABLE, planted wrong. Adding a leg without a case is the defect
    # this audit has found in four consecutive rounds, including twice in legs
    # written to close a previous round's finding.
    cases.append(("a mode-current row disagreeing with the part record is caught",
                  any("records" in p and "for mode" in p
                      for p in _planted_mode_problems())))
    cases.append(("MODE_TABLE names every mode row the document publishes",
                  not _unmapped_mode_rows()))

    # THE DECOMPOSITION RULE, in all three forms that previously got through.
    # gate-coverage cannot see this: its measurement is per REPORT SITE, and a
    # new branch inside an already-covered site is invisible to it.
    for _form in ("**35 mA** typical, 320 mA transient",
                  "**35 mA** (320 mA is transient)",
                  "**35 mA** (+320 mA transient, not budgeted)"):
        cases.append((f"a decomposed headline is caught: {_form[:34]}",
                      any("records" in p and "for mode" in p
                          for p in _decomposed_mode_problems(_form))))
    cases.append(("a genuinely additive row still reconciles",
                  not any("Light-sleep" in p for p in _decomposed_mode_problems(None))))

    # A PLANTED WRONG WINDOW. The leg was pinned only by a count, and the count
    # survives the reporting branch being deleted -- so both directions of the
    # comparison could be cut with `--self-test` green.
    cases.append(("a model window disagreeing with its benchmark is caught",
                  any("must be the same numbers" in p
                      for p in _planted_window_problems())))
    cases.append(("every REQUIRED benchmark is actually reached",
                  set(REQUIRED) == {"blinker-555", "buck-3v3"}))

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


# design.json / IR assertion windows that must agree with the benchmark's
# assertions.yaml. Nothing compared them, so `lang/examples/` and
# `ir/examples/` shipped the SUPERSEDED blinker windows -- 0.524/0.544 duty and
# 0.932/1.051 Hz -- while assertions.yaml carried the corrected ones. That
# model is what lang/README.md calls "the design AC5a runs its trials on", and
# it encoded a duty window this repository's own derivation proves excludes the
# part's guaranteed THRES corner.
MODEL_LINKS = (
    ("blinker-555", ROOT / "lang" / "examples" / "blinker-555.design.json",
     ROOT / "ir" / "examples" / "blinker.ir.json"),
)
# assertions.yaml name -> (measurement, scale from the yaml unit to the model's)
LINKED_ASSERTIONS = {
    "duty_cycle_high": ("duty_cycle", 0.01),
    "osc_frequency": ("frequency", 1.0),
}


def model_problems(problems):
    """Hold the DSL model and the IR to the benchmark's declared windows."""
    import json
    checked = set()
    for name, model_path, ir_path in MODEL_LINKS:
        spec_path = ROOT / "benchmarks" / name / "assertions.yaml"
        if not spec_path.is_file():
            problems.append(f"{name}: no assertions.yaml to hold the model to")
            continue
        try:
            import yaml
        except ImportError as exc:
            raise GateUnavailable(f"PyYAML is required: {exc}") from exc
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
        want = {}
        for assertion in spec.get("assertions") or []:
            link = LINKED_ASSERTIONS.get(assertion.get("name"))
            if link is None:
                continue
            window = assertion.get("window")
            if not isinstance(window, list) or len(window) != 2:
                continue
            measurement, scale = link
            want[measurement] = tuple(
                float(str(v).split()[0]) * scale for v in window)
        for path in (model_path, ir_path):
            if not path.is_file():
                problems.append(f"{path.name} is missing")
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
            for assertion in document.get("assertions") or []:
                measurement = assertion.get("measurement")
                if measurement not in want:
                    continue
                bounds = assertion.get("bounds") or {}
                low, high = float(bounds.get("min")), float(bounds.get("max"))
                want_low, want_high = want[measurement]
                if (abs(low - want_low) > 1e-9 or abs(high - want_high) > 1e-9):
                    problems.append(
                        f"{path.name}: {measurement} window is [{low}, {high}] "
                        f"but benchmarks/{name}/assertions.yaml declares "
                        f"[{want_low}, {want_high}]. The model AC5a runs on and "
                        "the window the benchmark gates on must be the same "
                        "numbers.")
                    continue
                checked.add((path.name, measurement))
    if len(checked) < MINIMUM_MODEL_WINDOWS:
        problems.append(
            f"reconciled {len(checked)} distinct model window(s), below the floor of "
            f"{MINIMUM_MODEL_WINDOWS}.")
    return len(checked)


# THE LANGUAGE CARDS. `bakeoff card` is the A4 language card, and
# test_bakeoff.py makes it the AC5 trial's system_context -- the teaching
# payload a model is given before it writes a design. All three arms state the
# blinker's frequency and duty windows as literal text in their card, and
# nothing held them to benchmarks/blinker-555/assertions.yaml. A prior round
# found three cards teaching superseded windows; that fix corrected the
# literals and pinned nothing, so an auditor taught the model a 9.923-91.052 Hz
# oscillator for a ~1 Hz blinker, ran the file's own documented `--write`
# remedy, and every gate stayed green.
#
# The rule is deliberately not a per-arm parser: EVERY number in a card's
# Assertions section must be a bound the benchmark declares. Three arms spell
# the same window three ways (`within 0.923Hz to 1.052Hz`, `min="0.923"`), and
# a parser per spelling is three more things to keep in step. A number that is
# not a declared bound has no business being taught as one.
CARD_WINDOW_SOURCE = "blinker-555"
MINIMUM_CARD_NUMBERS = 6


def card_problems(problems, cards=None):
    """Hold every number in each arm's card Assertions section to the spec.

    `cards` is injectable so the self-test can drive both directions over a
    fixture rather than only over the three shipped arms, which agree today.
    """
    import sys as _sys
    if str(ROOT / "lang") not in _sys.path:
        _sys.path.insert(0, str(ROOT / "lang"))
    try:
        from bakeoff.arms import ARMS
    except ImportError as exc:
        raise GateUnavailable(f"the bake-off arms are not importable: {exc}") from exc
    try:
        import yaml
    except ImportError as exc:
        raise GateUnavailable(f"PyYAML is required: {exc}") from exc

    spec_path = ROOT / "benchmarks" / CARD_WINDOW_SOURCE / "assertions.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    allowed = set()
    for assertion in spec.get("assertions") or []:
        for bound in declared_window(assertion):
            if bound is not None:
                allowed.add(round(bound, 12))
    if len(allowed) < 4:
        problems.append(
            f"{CARD_WINDOW_SOURCE}/assertions.yaml yielded {len(allowed)} "
            "declared bound(s); the cards would be compared against almost "
            "nothing.")
        return 0

    checked = 0
    texts = (cards if cards is not None
             else {name: arm.language_card() for name, arm in ARMS.items()})
    for name, card in sorted(texts.items()):
        start = card.find("## Assertions")
        if start < 0:
            problems.append(
                f"the {name} language card has no `## Assertions` section, so "
                "the windows it teaches are read by nothing.")
            continue
        end = card.find("\n## ", start + 1)
        section = card[start:end if end > 0 else len(card)]
        numbers = [float(n) for n in NUMBER.findall(section)]
        if not numbers:
            problems.append(
                f"the {name} language card's Assertions section states no "
                "window at all; a card that teaches no bound cannot be checked "
                "against one.")
            continue
        for value in numbers:
            # Percent-free: the cards state duty as a fraction, as the spec's
            # base units do.
            if not any(abs(value - bound) <= 1e-9 * max(1.0, abs(bound))
                       for bound in allowed):
                problems.append(
                    f"the {name} language card teaches {value!r} in its "
                    f"Assertions section, which is not a bound "
                    f"benchmarks/{CARD_WINDOW_SOURCE}/assertions.yaml declares "
                    f"({sorted(allowed)}). The card is the AC5 trial's system "
                    "context: this is the window a model is taught to write.")
                continue
            checked += 1
    if checked < MINIMUM_CARD_NUMBERS:
        problems.append(
            f"reconciled {checked} card window number(s), below the floor of "
            f"{MINIMUM_CARD_NUMBERS}. A card whose Assertions section lost its "
            "numbers would otherwise reconcile perfectly.")
    return checked


# design.md's AC1a line-count table publishes the same measurement
# lang/README.md does, in a second document, and check-design-docs only reads
# tables whose last cell is a verdict -- so this one was outside every gate.
# It has already been published against the losing arm once.
LINE_TABLES = {"blinker-555": ("candidate_b", ROOT / "lang" / "examples"
                               / "blinker-555.design.json")}


def line_count_problems(problems):
    """Hold design.md's AC1a line table to the renderer it names."""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "lang"))
    try:
        from bakeoff import arms as _arms
        from bakeoff.model import load_model
    except ImportError as exc:
        raise GateUnavailable(f"the bake-off harness is not importable: {exc}")
    checked = 0
    for name, (arm_name, model_path) in LINE_TABLES.items():
        doc = ROOT / "benchmarks" / name / "design.md"
        if not doc.is_file():
            problems.append(f"{name}/design.md is missing")
            continue
        arm = getattr(_arms, arm_name)
        model = load_model(model_path)
        want = {v: len(arm.render(model, v).splitlines())
                for v in ("explicit", "inferred", "inferred+columnar")}
        seen = set()
        for line in doc.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != 2:
                continue
            variant = cells[0].replace(" + ", "+").replace(" ", "")
            variant = {"explicit": "explicit", "inferred": "inferred",
                       "inferred+columnar": "inferred+columnar"}.get(variant)
            if variant is None:
                continue
            found = re.search(r"\d+", cells[1])
            if found is None:
                continue
            if int(found.group(0)) != want[variant]:
                problems.append(
                    f"{name}/design.md: the AC1a table publishes "
                    f"{found.group(0)} lines for {variant}, but {arm_name} "
                    f"renders {want[variant]}. This table has already been "
                    "published against the losing arm once.")
                continue
            seen.add(variant)
            checked += 1
        if len(seen) < 3:
            problems.append(
                f"{name}/design.md: reconciled {len(seen)} of 3 AC1a line "
                "counts; a row that stops parsing also stops being checked.")
    return checked


# benchmark (c)'s design.md was measured at 167 published numbers with NOTHING
# reading any of them: an auditor changed every number in the file at once with
# `make all` green, and at one point it published `4.7 + 4.7 = 9.5`. The mode
# table is the part of it that is mechanically checkable -- every current in it
# is a `modes[].draw[].current` in the part record -- so that is what this
# holds. The rest of the file is prose and hand-derivation that
# check-hand-assertions.py gates through assertions.yaml.
MODE_TABLE = {
    "benchmark": "esp32s3-devboard",
    "record": "espressif-esp32-s3-wroom-1-n8r2.part.json",
    # design.md row label fragment -> mode id in the part record
    "rows": (
        ("802.11b 1 Mbps", "wifi_tx_802_11b_1mbps"),
        ("802.11b/g/n HT20", "wifi_rx_802_11bgn_ht20"),
        ("WAITI, peripheral clocks enabled", "modem_sleep_240mhz_waiti"),
        ("dual-core 128-bit", "modem_sleep_240mhz_dualcore_128bit"),
        ("Light-sleep", "light_sleep"),
        ("Deep-sleep", "deep_sleep_rtc_mem_and_periph"),
        ("802.11g 54 Mbps", "wifi_tx_802_11g_54mbps"),
        ("802.11n HT20 MCS7", "wifi_tx_802_11n_ht20_mcs7"),
        ("Power off (EN low)", "power_off_en_low"),
    ),
}
MINIMUM_MODE_ROWS = 9
# Rows whose cell legitimately publishes a decomposition rather than one value.
# Named per row, not detected by pattern: a rule that recognises decompositions
# is a rule any wrong number can dress up as one.
ADDITIVE_ROWS = ("Light-sleep",)


def mode_table_problems(problems):
    """Hold benchmark (c)'s mode-current table to the part record."""
    import json
    doc = ROOT / "benchmarks" / MODE_TABLE["benchmark"] / "design.md"
    record = ROOT / "parts" / "examples" / MODE_TABLE["record"]
    if not doc.is_file() or not record.is_file():
        problems.append(f"{MODE_TABLE['benchmark']}: design.md or its part record is missing")
        return 0
    modes = {}
    for mode in json.loads(record.read_text(encoding="utf-8")).get("modes") or []:
        for draw in mode.get("draw") or []:
            current = draw.get("current") or {}
            value = current.get("typ", current.get("peak", current.get("max")))
            if value is not None:
                scale = {"uA": 1e-6, "mA": 1e-3, "A": 1.0}.get(current.get("unit"), 1.0)
                modes[mode["id"]] = float(value) * scale
    text = doc.read_text(encoding="utf-8")
    checked = 0
    for fragment, mode_id in MODE_TABLE["rows"]:
        row = next((l for l in text.splitlines()
                    if l.startswith("|") and fragment in l), None)
        if row is None:
            problems.append(
                f"{doc.parent.name}/design.md: no mode-current row mentioning "
                f"{fragment!r}. The row that carries {mode_id} left the table.")
            continue
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        # SUM the cell's currents. The light-sleep row publishes a
        # decomposition -- "240 uA (+40 uA for 2 MB quad PSRAM)" -- where the
        # part record holds the 280 uA total, and both are correct. Reading
        # only the first number made the gate report a disagreement that was
        # its own.
        # THE HEADLINE TERM IS THE FIRST ONE, FULL STOP. Two previous versions
        # tested the SHAPE of the last defect instead of the property. Summing
        # everything let `**35 mA** (320 mA is transient)` reconcile against a
        # recorded 355 mA; stripping non-`+` parentheses let the same 10x error
        # through written with a comma -- `**35 mA** typical, 320 mA transient`
        # -- and left `(+320 mA ...)` open as well.
        #
        # The property is: the number a reader takes away must be the recorded
        # value. So the FIRST current in the cell is compared alone. A row that
        # genuinely decomposes says so with an explicit `+` on the continuation
        # and declares its terms in ADDITIVE_ROWS, which is a per-row decision
        # rather than a pattern any cell can adopt.
        terms = re.findall(r"([\d.]+)\s*(uA|mA|A)\b", cells[1])
        if fragment in ADDITIVE_ROWS:
            if len(terms) < 2:
                problems.append(
                    f"{doc.parent.name}/design.md: the {fragment!r} row is "
                    "declared additive but publishes one term.")
                continue
        else:
            terms = terms[:1]
        published = sum(float(v) * {"uA": 1e-6, "mA": 1e-3, "A": 1.0}[u]
                        for v, u in terms)
        want = modes.get(mode_id)
        if want is None:
            problems.append(
                f"{MODE_TABLE['record']} records no current for mode {mode_id!r}.")
            continue
        if abs(published - want) > abs(want) * 1e-9:
            problems.append(
                f"{doc.parent.name}/design.md: publishes "
                f"{' + '.join(v + ' ' + u for v, u in terms)} for "
                f"{fragment!r}, but {MODE_TABLE['record']} records "
                f"{want:.6g} A for mode {mode_id!r}.")
            continue
        checked += 1
    for label in _unmapped_mode_rows():
        problems.append(
            f"{doc.parent.name}/design.md: the mode row {label!r} publishes a "
            "current that MODE_TABLE does not map to the part record, so it is "
            "read by nothing.")
    if checked < MINIMUM_MODE_ROWS:
        problems.append(
            f"{doc.parent.name}/design.md: reconciled {checked} mode-current "
            f"row(s), below the floor of {MINIMUM_MODE_ROWS}.")
    return checked


def _unmapped_mode_rows():
    """Rows of the document's mode table that MODE_TABLE does not name.

    The case here used to assert `len(MODE_TABLE["rows"]) == MINIMUM_MODE_ROWS`
    -- a constant against a constant three lines below it in the same file,
    which is true no matter what the document publishes. The document has NINE
    rows; six were mapped, and the three that were not (802.11g 297 mA,
    802.11n 286 mA, power-off 1 uA) were read by nothing.
    """
    doc = ROOT / "benchmarks" / MODE_TABLE["benchmark"] / "design.md"
    if not doc.is_file():
        return ["design.md is missing"]
    inside, unmapped = False, []
    for line in doc.read_text(encoding="utf-8").splitlines():
        if line.startswith("| Mode |"):
            inside = True
            continue
        if inside:
            if not line.startswith("|"):
                break
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2 or set(cells[0]) <= set("-: "):
                continue
            if not re.search(r"[\d.]+\s*(uA|mA|A)\b", cells[1]):
                continue
            if not any(fragment in line for fragment, _ in MODE_TABLE["rows"]):
                unmapped.append(cells[0])
    return unmapped


def _decomposed_mode_problems(form):
    """Drive mode_table_problems over a design.md with one row rewritten."""
    import tempfile
    doc = ROOT / "benchmarks" / MODE_TABLE["benchmark"] / "design.md"
    text = doc.read_text(encoding="utf-8")
    if form is not None:
        text = text.replace("**355 mA**", form, 1)
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "parts" / "examples").mkdir(parents=True)
        (root / "parts" / "examples" / MODE_TABLE["record"]).write_text(
            (ROOT / "parts" / "examples" / MODE_TABLE["record"]).read_text(
                encoding="utf-8"), encoding="utf-8")
        case = root / "benchmarks" / MODE_TABLE["benchmark"]
        case.mkdir(parents=True)
        (case / "design.md").write_text(text, encoding="utf-8")
        saved = globals()["ROOT"]
        globals()["ROOT"] = root
        try:
            problems = []
            mode_table_problems(problems)
            return problems
        finally:
            globals()["ROOT"] = saved


def _planted_mode_problems():
    """Drive mode_table_problems against a record with one current changed.

    In a TEMPORARY tree. The first version wrote to the real tracked part
    record and restored it in `finally`, which makes `make sim` non-re-entrant
    and leaves `"typ": 999` committed if the process dies in between -- the
    shared-writable-state hazard AGENTS.md forbids, introduced by the probe for
    a leg written to close an ungated-document finding.
    """
    import json, tempfile
    record = ROOT / "parts" / "examples" / MODE_TABLE["record"]
    document = json.loads(record.read_text(encoding="utf-8"))
    for mode in document.get("modes") or []:
        if mode.get("id") == "deep_sleep_rtc_mem_and_periph":
            for draw in mode.get("draw") or []:
                draw["current"]["typ"] = 999
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "parts" / "examples").mkdir(parents=True)
        (root / "parts" / "examples" / MODE_TABLE["record"]).write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8")
        case = root / "benchmarks" / MODE_TABLE["benchmark"]
        case.mkdir(parents=True)
        (case / "design.md").write_text(
            (ROOT / "benchmarks" / MODE_TABLE["benchmark"] / "design.md").read_text(
                encoding="utf-8"), encoding="utf-8")
        saved = globals()["ROOT"]
        globals()["ROOT"] = root
        try:
            problems = []
            mode_table_problems(problems)
            return problems
        finally:
            globals()["ROOT"] = saved


def _planted_window_problems():
    """Drive model_problems over a copy of the IR with a superseded window."""
    import json, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        ir = json.loads((ROOT / "ir" / "examples" / "blinker.ir.json").read_text(
            encoding="utf-8"))
        for assertion in ir.get("assertions") or []:
            if assertion.get("measurement") == "duty_cycle":
                assertion["bounds"]["min"] = 0.524
                assertion["bounds"]["max"] = 0.544
        planted = pathlib.Path(tmp) / "planted.ir.json"
        planted.write_text(json.dumps(ir), encoding="utf-8")
        saved = MODEL_LINKS[0]
        globals()["MODEL_LINKS"] = ((saved[0], saved[1], planted),)
        try:
            problems = []
            model_problems(problems)
            return problems
        finally:
            globals()["MODEL_LINKS"] = (saved,)


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
        windows = model_problems(problems) if not argv else 0
        modes = mode_table_problems(problems) if not argv else 0
        lines_ok = line_count_problems(problems) if not argv else 0
        cards = card_problems(problems) if not argv else 0
    except GateUnavailable as exc:
        print(f"design-docs: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2

    if problems:
        print("design-docs: FAIL:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"design-docs: PASS: {total} results row(s) agree with the "
          f"measurements their benchmarks record, {modes} mode-current "
          f"row(s) agree with the part record, and {windows} model/IR "
          f"assertion window(s), {cards} language-card window number(s) and "
          f"{lines_ok} AC1a line count(s) agree with the artifacts that "
          "produce them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
