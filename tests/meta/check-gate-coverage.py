#!/usr/bin/env python3
"""Measure how much of each gate is actually pinned by its own `--self-test`.

WHY THIS EXISTS. Across twelve audit rounds the single most common finding was
a check that could be deleted with everything green -- a leg with no self-test
case. It was found in every round from 6 onwards, twice in legs written to
close the previous round's finding, and once in a case whose NAME asserted the
property while its body compared a constant to itself. An auditor finally
measured it: of 21 report sites in check-design-docs.py, 15 survived being
blanked; of 24 in check_readme_numbers.py, 16 did. The two files flagged as
newest were the two least covered, by a wide margin.

Individual missing cases are worth fixing one at a time. The RECURRENCE is not
fixable that way, because nothing made the number visible: a gate with no
coverage and a gate with full coverage print the same PASS.

WHAT IT DOES. For each gate below, blank one report site at a time (the
`problems.append(...)` / `bad(...)` call and its continuation lines), then run
that gate's `--self-test`. A site that survives is a check whose removal no
case notices. The count is compared to a declared ceiling.

CEILINGS ONLY GO DOWN. Each number is today's measured value, and a gate that
regresses fails. Lowering one is a deliberate commit; drifting up is not
possible without this gate going red. Ceilings above zero are honest: they
record uncovered legs rather than pretending they do not exist.

WHAT THIS DOES NOT MEASURE, demonstrated rather than supposed:

  1. PER SITE, NOT PER BRANCH. A new condition added inside an
     already-covered report site is invisible here. Round 13 found the
     mode-table decomposition rule -- five lines, three escape routes, no case
     -- and this gate scored the file unchanged before and after those cases
     were added. If a fix adds a branch rather than a site, expect no movement
     and do not read that as coverage.
  2. A site can be reached by a case for the wrong reason, and a case can
     assert something weaker than the check does.
  3. Report paths that are not `problems.append`/`bad`/`out.append` -- a helper
     that appends, a returned value, a raised exception -- are not counted at
     all, so a gate could score well while most of its reporting is unseen.

Surviving-site count is a floor on what is unpinned. It is not a coverage
percentage and must not be quoted as one.

Exit codes: 0 every gate at or under its ceiling, 1 a regression, 2 environment.

    python3 tests/meta/check-gate-coverage.py --self-test
    python3 tests/meta/check-gate-coverage.py
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# gate -> how many report sites may survive being blanked. Measured, not
# chosen. Lower these; do not raise them.
CEILINGS = {
    "lang/tests/check_readme_numbers.py": 16,
    "tests/benchmarks/check-corners.py": 9,
    "tests/benchmarks/check-design-docs.py": 5,
    "tests/benchmarks/check-hand-assertions.py": 10,
    "tests/corpus/check-classification.py": 18,
    "tests/corpus/check-corpus.py": 3,
    "tests/eval/check-run-records.py": 8,
    "tests/ir/check-hashes.py": 2,
}

REPORT_SITE = re.compile(
    r"^[ \t]*(?:problems\.append\(|bad\(|out\.append\(|problems_out\.append\()",
    re.MULTILINE)

# A gate must have at least this many report sites for the measurement to mean
# anything; a gate that reports nothing would otherwise score a perfect zero.
MINIMUM_SITES = 5


class GateUnavailable(Exception):
    """The measurement could not be performed. Never reported as a pass."""


def report_sites(source: str) -> list[int]:
    """Line numbers of report sites outside the gate's own self_test()."""
    limit = source.find("def self_test(")
    if limit == -1:
        limit = len(source)
    return [source[:m.start()].count("\n")
            for m in REPORT_SITE.finditer(source) if m.start() < limit]


def blank_site(source: str, line_no: int) -> str:
    """Replace the call starting at `line_no` with `pass`, spanning its parens."""
    lines = source.splitlines(keepends=True)
    indent = len(lines[line_no]) - len(lines[line_no].lstrip())
    depth = 0
    index = line_no
    while index < len(lines):
        depth += lines[index].count("(") - lines[index].count(")")
        lines[index] = " " * indent + ("pass\n" if index == line_no else "pass\n")
        if depth <= 0:
            break
        index += 1
    return "".join(lines)


def surviving_sites(gate: Path) -> tuple[int, int, list[int]]:
    """(sites, survivors, survivor line numbers) for one gate."""
    source = gate.read_text(encoding="utf-8")
    sites = report_sites(source)
    survivors = []
    backup = gate.with_suffix(gate.suffix + ".coverage-backup")
    shutil.copy(gate, backup)
    try:
        for line_no in sites:
            gate.write_text(blank_site(source, line_no), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(gate), "--self-test"],
                capture_output=True, text=True, cwd=ROOT, timeout=300)
            if result.returncode == 0:
                survivors.append(line_no + 1)
            gate.write_text(source, encoding="utf-8")
    finally:
        # Restore from the backup, not from `source`: if this process dies
        # mid-loop the gate is left mutated, which is the shared-writable-state
        # hazard AGENTS.md forbids and which a sibling probe already caused.
        shutil.copy(backup, gate)
        backup.unlink()
    return len(sites), len(survivors), survivors


def check(problems: list[str], ceilings=None) -> int:
    measured = 0
    for name, ceiling in sorted((ceilings or CEILINGS).items()):
        gate = ROOT / name
        if not gate.is_file():
            problems.append(f"{name}: named as a gate and is not present")
            continue
        try:
            sites, survivors, where = surviving_sites(gate)
        except subprocess.TimeoutExpired:
            raise GateUnavailable(f"{name}: --self-test did not terminate")
        if sites < MINIMUM_SITES:
            problems.append(
                f"{name}: has {sites} report site(s), below the {MINIMUM_SITES} "
                "this measurement needs to mean anything. A gate that reports "
                "almost nothing scores a perfect coverage number.")
            continue
        if survivors > ceiling:
            problems.append(
                f"{name}: {survivors} of {sites} report site(s) survive being "
                f"blanked, above the ceiling of {ceiling}. Lines {where}. Each "
                "is a check that can be deleted with --self-test green.")
            continue
        if survivors < ceiling:
            print(f"gate-coverage: {name}: {survivors} of {sites} survive, under "
                  f"its ceiling of {ceiling}. Lower the ceiling to {survivors} "
                  "in the same commit so it cannot drift back.")
        measured += 1
    return measured


def self_test() -> int:
    cases = []

    SAMPLE = (
        "import sys\n"
        "def check(problems):\n"
        "    if 1 > 2:\n"
        "        problems.append('never')\n"
        "    if 2 > 1:\n"
        "        problems.append(\n"
        "            'always')\n"
        "def self_test():\n"
        "    problems = []\n"
        "    check(problems)\n"
        "    return 0 if problems else 1\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(self_test() if '--self-test' in sys.argv else 0)\n"
    )

    cases.append(("report sites are found outside self_test()",
                  report_sites(SAMPLE) == [3, 5]))
    cases.append(("a site inside self_test() is not counted",
                  all(n < SAMPLE.count("\n", 0, SAMPLE.index("def self_test("))
                      for n in report_sites(SAMPLE))))

    blanked = blank_site(SAMPLE, 5)
    cases.append(("blanking spans a multi-line call",
                  "'always'" not in blanked and blanked.count("pass") == 2))
    cases.append(("blanking leaves the rest of the file intact",
                  "'never'" in blanked))

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.py"
        probe.write_text(SAMPLE, encoding="utf-8")
        sites, survivors, where = surviving_sites(probe)
        # The unreachable site (1 > 2) survives; the reachable one does not.
        cases.append(("an unreachable check is reported as surviving",
                      sites == 2 and survivors == 1 and where == [4]))
        cases.append(("the gate is restored after measurement",
                      probe.read_text(encoding="utf-8") == SAMPLE))

        problems = []
        check(problems, ceilings={str(probe.relative_to(ROOT))
                                  if probe.is_relative_to(ROOT) else "probe.py": 0})
        cases.append(("a gate above its ceiling is reported",
                      any("survive being blanked" in p or "not present" in p
                          for p in problems)))

    # WIRING over the real gates: the shipped ceilings must hold.
    real = []
    measured = check(real)
    cases.append(("every shipped gate is at or under its ceiling", not real))
    cases.append(("every named gate was measured", measured == len(CEILINGS)))

    failures = 0
    for name, ok in cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        print(f"gate-coverage: SELF-TEST FAILED: {failures} case(s)", file=sys.stderr)
        return 1
    print(f"gate-coverage: self-test PASS: {len(cases)} cases.")
    return 0


def main(argv):
    if argv and argv[0] == "--self-test":
        return self_test()
    problems = []
    try:
        measured = check(problems)
    except GateUnavailable as exc:
        print(f"gate-coverage: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    if problems:
        print("gate-coverage: FAIL:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"gate-coverage: PASS: {measured} gate(s) at or under their "
          "self-test coverage ceiling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
