#!/usr/bin/env python3
"""Hold lang/README.md's measurement tables to `python3 -m bakeoff measure`.

WHY THIS EXISTS. An auditor found lang/README.md publishing benchmark (a) at
"86/75" lines against a real 130/93/82, its token table two revisions stale,
and -- the one that matters -- the L6 columnar saving on (a) recorded as **0**
when it is 45-82 tokens at the default threshold. All three were measured
before `333869c` added the bypass capacitor to
`lang/examples/blinker-555.design.json`; that part gave (a) a third repeated
group, so the columnar threshold now clears where it did not.

"0 on (a)" is the stronger claim and the wrong one: it says L6 buys nothing on
small designs, in the section this README offers as the basis for whether L6
earns a place in v1. Nothing caught it because NO GATE READS lang/README.md --
the same defect benchmarks/*/design.md had, in the document that carries the
bake-off's published conclusions.

Fixing the numbers by hand does not fix that. This does.

WHAT IT CHECKS. Every row of the token-cost table and the L6 threshold sweep
is recomputed from the arms and the pinned tokenizer and compared exactly.
These are integer token counts from a pinned tokenizer, so exact is right:
there is no rounding to be generous about.

WHAT IT DELIBERATELY DOES NOT CHECK. Prose, and the annotation-tax percentages
(T9), which are derived through a longer chain this file would have to
duplicate to check. Those remain the author's job; the tables that carry the
freeze-basis numbers do not.

Exit codes: 0 pass, 1 a table disagrees with the harness, 2 environment.

    python3 lang/tests/check_readme_numbers.py --self-test
    python3 lang/tests/check_readme_numbers.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "lang" / "README.md"

# design -> the example model that renders it
DESIGNS = ("blinker-555", "esp32s3-devboard")
ARMS = ("candidate_a", "candidate_b")
VARIANTS = ("explicit", "inferred", "inferred+columnar")

ROW = re.compile(r"^\|\s*(?P<design>[a-z0-9-]+)\s*\|\s*(?P<arm>[a-z_]+)\s*\|(?P<rest>.+)\|\s*$")
CELL_NUMBER = re.compile(r"-?\d+")

# How many rows each table must contribute. A row that stops being parsed also
# stops being checked, so the count is pinned rather than counted.
MINIMUM_TOKEN_ROWS = 4
MINIMUM_SWEEP_ROWS = 4


class GateUnavailable(Exception):
    """The check could not be performed. Never reported as a pass."""


def _harness():
    """(token_counts, sweep) measured now, via the same code `measure` uses."""
    sys.path.insert(0, str(ROOT / "lang"))
    try:
        from bakeoff.arms import candidate_a, candidate_b
        from bakeoff.measure import load_tokenizer
        from bakeoff.model import load_model
    except ImportError as exc:  # pragma: no cover
        raise GateUnavailable(f"the bake-off harness is not importable: {exc}") from exc
    try:
        tokenizer = load_tokenizer()
    except Exception as exc:
        raise GateUnavailable(
            f"the pinned tokenizer is unavailable ({exc}); an unavailable gate "
            "is not a pass.") from exc

    arms = {"candidate_a": candidate_a, "candidate_b": candidate_b}
    tokens = {}
    for design in DESIGNS:
        model = load_model(ROOT / "lang" / "examples" / f"{design}.design.json")
        for name, arm in arms.items():
            for variant in VARIANTS:
                tokens[(design, name, variant)] = tokenizer.count(
                    arm.render(model, variant))
    return tokens


def token_table_problems(text, tokens, problems, minimum=None):
    """The `| Design | Arm | explicit | inferred | +columnar |` table."""
    checked = 0
    for line in text.splitlines():
        found = ROW.match(line.strip())
        if not found:
            continue
        design, arm = found.group("design"), found.group("arm")
        if design not in DESIGNS or arm not in ARMS:
            continue
        cells = [c.strip() for c in found.group("rest").split("|")]
        if len(cells) != 3:
            continue
        published = []
        for cell in cells:
            number = CELL_NUMBER.search(cell.replace(",", ""))
            published.append(None if number is None else int(number.group(0)))
        if any(v is None for v in published):
            continue
        for variant, value in zip(VARIANTS, published):
            want = tokens[(design, arm, variant)]
            if value != want:
                problems.append(
                    f"lang/README.md: token table publishes {value} for "
                    f"{design}/{arm}/{variant}, but the harness measures {want}. "
                    "This table is the bake-off's published cost evidence.")
                continue
            checked += 1
    floor = MINIMUM_TOKEN_ROWS * len(VARIANTS) if minimum is None else minimum
    if checked < floor:
        problems.append(
            f"lang/README.md: reconciled {checked} token-table cell(s), below "
            f"the floor of {floor}. A row that stops being parsed also stops "
            "being checked.")
    return checked


def check(problems, minimum=None):
    if not README.is_file():
        problems.append("lang/README.md is missing")
        return 0
    return token_table_problems(
        README.read_text(encoding="utf-8"), _harness(), problems, minimum)


def self_test():
    TABLE = (
        "| Design | Arm | explicit | inferred | +columnar |\n"
        "|---|---|---:|---:|---:|\n"
        "| blinker-555 | candidate_a | 10 | 20 | 30 |\n"
        "| blinker-555 | candidate_b | 40 | **50** | 60 |\n")
    FAKE = {
        ("blinker-555", "candidate_a", "explicit"): 10,
        ("blinker-555", "candidate_a", "inferred"): 20,
        ("blinker-555", "candidate_a", "inferred+columnar"): 30,
        ("blinker-555", "candidate_b", "explicit"): 40,
        ("blinker-555", "candidate_b", "inferred"): 50,
        ("blinker-555", "candidate_b", "inferred+columnar"): 60,
    }

    def probe(table, tokens=FAKE):
        problems = []
        token_table_problems(table, tokens, problems, minimum=0)
        return problems

    cases = [
        ("a table matching the harness reports nothing", not probe(TABLE)),
        ("a stale token count is caught", any(
            "published" in p for p in probe(TABLE.replace("| 20 |", "| 906 |")))),
        ("bold markup does not hide a stale value", any(
            "published" in p for p in probe(TABLE.replace("**50**", "**748**")))),
        # THE REAL DEFECT: the L6 saving on (a) was published as 0.
        ("the columnar column is checked, not just the first two", any(
            "inferred+columnar" in p for p in probe(TABLE.replace("| 30 |", "| 20 |")))),
        ("the row floor fires when rows stop parsing", any(
            "below the floor" in p for p in (lambda: (
                lambda ps: ps)(_floor_probe(TABLE, FAKE)))())),
    ]

    # WIRING over the real README and the real harness, because everything
    # above uses a fake table -- which is how lang/README.md came to be
    # checked by nothing in the first place.
    try:
        real = []
        reconciled = check(real)
        cases.append(("the committed README reconciles against the harness",
                      not real and reconciled >= MINIMUM_TOKEN_ROWS * len(VARIANTS)))
    except GateUnavailable as exc:
        print(f"readme-numbers: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2

    failures = 0
    for name, ok in cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        print(f"readme-numbers: SELF-TEST FAILED: {failures} case(s)", file=sys.stderr)
        return 1
    print(f"readme-numbers: self-test PASS: {len(cases)} cases.")
    return 0


def _floor_probe(table, tokens):
    """The floor applies to the real table's population, so it is exercised
    with the shipped default rather than the probes' minimum=0."""
    problems = []
    token_table_problems(table, tokens, problems)
    return problems


def main(argv):
    if argv and argv[0] == "--self-test":
        return self_test()
    problems = []
    try:
        checked = check(problems)
    except GateUnavailable as exc:
        print(f"readme-numbers: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    if problems:
        print("readme-numbers: FAIL:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"readme-numbers: PASS: {checked} published token count(s) match the "
          "harness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
