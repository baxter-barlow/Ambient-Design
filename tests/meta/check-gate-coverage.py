#!/usr/bin/env python3
"""Measure how much of each gate is actually pinned by its own `--self-test`.

WHY THIS EXISTS. Across thirteen audit rounds the single most common finding was
a check that could be deleted with everything green -- a leg with no self-test
case. It was found in every round from 6 onwards, twice in legs written to close
the previous round's finding, and once in a case whose NAME asserted the
property while its body compared a constant to itself.

Individual missing cases are worth fixing one at a time. The RECURRENCE is not
fixable that way, because nothing made the number visible: a gate with no
coverage and a gate with full coverage print the same PASS.

WHAT IT DOES. For each gate the Makefile runs, blank one report site at a time
(the `problems.append(...)` / `bad(...)` call and its continuation lines), then
run that gate's `--self-test`. A site that survives is a check whose removal no
case notices. The count is compared to a declared ceiling.

ROUND 14 FOUND FOUR WAYS THIS GATE LIED ABOUT ITS OWN POPULATION, and every one
of them is now a failure rather than an omission:

  1. THE POPULATION IS THE MAKEFILE'S, NOT A GLOB'S. `self_testing_gates()`
     rglobbed `*.py` for files containing `def self_test`, so a gate with NO
     self-test was invisible to the census whose stated purpose was catching a
     wrongly-scoped population. Five shell gates and derive-555-windows.py --
     36 report sites -- were neither measured nor recorded. GATES is now read
     out of the Makefile, and a gate that lands in no bucket is a failure.

  2. THE EXCUSE LIST WAS CIRCULAR, so it is gone. TOO_FEW_SITES said its
     entries had "fewer than MINIMUM_SITES report sites"; that was measured
     with a global owner whitelist that did not contain their accumulator
     names (`failures`, `hits`), so the gate could not see their sites and
     therefore excused them for having none. validate-schemas.py has 11 and
     check-retired-names.py has 4; `hits.append(path_hit)` -- the path leg of
     the AMB-122 rename guard -- was deletable with `make all` green.
     Both are measured now, and no gate can be excused for being small: only a
     population of ZERO invalidates a coverage number.

  3. OWNERSHIP IS PER FILE. `out` is the report accumulator in
     check-run-records.py and a list of parsed table rows in check-corners.py.
     One global whitelist cannot be right for both, and `notes` -- printed,
     never failing -- was counted as a report site, so 2 of check-hashes.py's 4
     published survivors were print statements that cannot be pinned by
     anything. OWNERS classifies every accumulator per file, and a name it does
     not classify is a failure, not a silent exclusion.

  4. THE DENOMINATOR WAS FREE. Only `survivors` was compared to anything, so
     `REPORT_NAMES = ("append",)` cut 82 of 292 sites -- 28% of the population
     every ceiling is measured over -- with every ceiling still met and every
     gate still green. SITES pins the denominator: it may grow, never shrink.

CEILINGS ONLY GO DOWN. Each number is today's measured value, and a gate that
regresses fails. Lowering one is a deliberate commit; drifting up is not
possible without this gate going red. Ceilings above zero are honest: they
record uncovered legs rather than pretending they do not exist.

WHAT THIS DOES NOT MEASURE, demonstrated rather than supposed:

  1. PER SITE, NOT PER BRANCH. A new condition added inside an already-covered
     report site is invisible here. Round 13 found the mode-table decomposition
     rule -- five lines, three escape routes, no case -- and this gate scored
     the file unchanged before and after those cases were added. If a fix adds
     a branch rather than a site, expect no movement and do not read that as
     coverage.
  2. A site can be reached by a case for the wrong reason, and a case can
     assert something weaker than the check does.
  3. Report paths that are not a classified accumulator's `.append` or a `bad()`
     call -- a raised exception, a returned value, a bare `print` to stderr
     before `return 1` -- are not counted. OWNERS makes an unclassified
     ACCUMULATOR loud; it cannot make an unusual reporting STYLE loud.
  4. NO_SELF_TEST gates are counted, not measured. Their report sites are
     published as an unpinned total because there is no self-test to run them
     against; that number is a floor on what is unpinned in the shell half of
     the suite, and closing it means writing those self-tests.

Surviving-site count is a floor on what is unpinned. It is not a coverage
percentage and must not be quoted as one.

Exit codes: 0 every gate at or under its ceiling, 1 a regression, 2 environment.

    python3 tests/meta/check-gate-coverage.py --self-test
    python3 tests/meta/check-gate-coverage.py
"""

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Set by surviving_sites() in the subprocesses it mutates. This gate measures
# itself, and its self-test's last block measures every other gate -- so a
# naive self-measurement is quadratic: nine mutants times a two-minute run. The
# flag skips only that final wiring block, leaving every probe-driven case (the
# ones that actually exercise check(), census() and the classification legs)
# in force. It makes the self-measurement CONSERVATIVE -- a site the wiring
# block would have caught scores as surviving -- which is the safe direction
# for a number whose whole purpose is to be an honest floor.
INNER = os.environ.get("RHOFORM_GATE_COVERAGE_INNER") == "1"

# gate -> (report sites, how many may survive being blanked). Both measured, not
# chosen. Sites may grow (a new check); a DROP is the population being cut out
# from under the ceiling, which is how 28% of it disappeared unnoticed. Lower
# the survivor number; do not raise it.
CEILINGS = {
    "lang/tests/check_readme_numbers.py": (24, 16),
    "parts/lint-part-data.py": (30, 5),
    "tests/benchmarks/check-assertions.py": (18, 3),
    "tests/benchmarks/check-corners.py": (22, 9),
    "tests/benchmarks/check-design-docs.py": (31, 21),
    "tests/benchmarks/check-hand-assertions.py": (28, 15),
    "tests/benchmarks/derive-555-windows.py": (5, 0),
    "tests/corpus/check-classification.py": (54, 18),
    "tests/corpus/check-corpus.py": (15, 3),
    "tests/eval/check-run-records.py": (62, 9),
    "tests/ir/check-hashes.py": (16, 2),
    # Measured under INNER, so 6 is an upper bound: sites the skipped wiring
    # block would have caught score as surviving. The gate now measures itself,
    # which the version that excused itself as "too few sites" did not.
    "tests/meta/check-gate-coverage.py": (11, 6),
    "tests/schemas/validate-schemas.py": (11, 2),
    "tests/structure/check-retired-names.py": (4, 0),
    "tests/toolchain/check-pins.py": (18, 12),
}

# Which `<name>.append(...)` calls report a problem, per file. Both halves are
# required: a name in neither is a failure, so a new accumulator cannot join a
# gate unnoticed on either side of the line.
#
# This is per file because it has to be. `out` is the report accumulator behind
# check-run-records.py's `bad()` closure and a list of parsed transcript rows in
# check-corners.py; one global whitelist scored the second as a check and the
# first not at all.
OWNERS = {
    "lang/tests/check_readme_numbers.py": (
        {"problems"},
        {"token_lines", "t9_order", "sources", "published", "cases"}),
    "parts/lint-part-data.py": (
        {"problems"}, {"unchecked", "files"}),
    "tests/benchmarks/check-assertions.py": (
        {"problems"}, {"cases"}),
    "tests/benchmarks/check-corners.py": (
        {"problems"}, {"cases", "out"}),
    "tests/benchmarks/check-design-docs.py": (
        {"problems"}, {"cases", "unmapped", "rows"}),
    "tests/benchmarks/check-hand-assertions.py": (
        {"problems"}, {"cases", "parts", "shape"}),
    "tests/benchmarks/derive-555-windows.py": (
        {"problems"}, set()),
    "tests/corpus/check-classification.py": (
        {"problems"}, {"lines", "checks", "results", "alone_fails"}),
    "tests/corpus/check-corpus.py": (
        {"problems"}, {"cases", "numbers"}),
    "tests/eval/check-run-records.py": (
        {"problems", "problems_out", "out"}, {"cases"}),
    "tests/ir/check-hashes.py": (
        # `notes` is printed and never fails the gate. Counting it made two
        # print statements 2 of this gate's 4 published survivors -- unpinnable
        # by construction, and a route to lowering a ceiling by converting a
        # real check into a note.
        {"problems"}, {"checks", "notes", "seen_spans", "_p"}),
    "tests/meta/check-gate-coverage.py": (
        {"problems"}, {"cases", "survivors", "sites", "found", "unclassified",
                       "gates", "notes", "unaccounted", "missed"}),
    "tests/schemas/validate-schemas.py": (
        {"failures"}, {"cases"}),
    "tests/structure/check-retired-names.py": (
        {"hits"}, {"wiring_cases"}),
    "tests/toolchain/check-pins.py": (
        # READ_BY_KEY is printed, never fails -- the same shape as `notes`
        # above. That it is only a note is itself a finding (a pin recorded as
        # unverified reads like a pin that passed), tracked against the
        # tiktoken offline guard rather than papered over by counting it here.
        {"problems", "missing_jobs"},
        {"cases", "pins", "parsed_refs", "READ_BY_KEY", "joined",
         "required", "computed"}),
}

# Calls that report by name rather than through an accumulator.
REPORT_CALLS = ("bad",)

# Below this, a gate's number is annotated as resting on a small population.
# It is NOT a reason to skip the gate. The old rule refused to measure anything
# under five sites, which took check-retired-names.py -- 4 sites, 3 of them
# unpinned, including the path leg of the AMB-122 rename guard -- out of the
# measurement for being too small to have a bad number, and made TOO_FEW_SITES
# an unverified escape hatch that any gate could be moved into. There is no
# such list now. What a population of ZERO cannot support is a zero; that is
# the only case that fails.
SMALL_POPULATION = 5

# Gates the Makefile runs that have no `--self-test` at all. VERIFIED: an entry
# that does have one fails, and so does a Makefile gate missing from every
# bucket. Their report sites are counted and published as an unpinned total,
# because a gap that is measured is a gap somebody can close.
NO_SELF_TEST = (
    ".agents/skills/verify-rhoform-change/scripts/validate-layout.sh",
    ".github/scripts/check-dco.sh",
    "tests/benchmarks/run-sim.sh",
    "tests/golden/run.sh",
    "tests/structure/check-layout.sh",
)

# Shell gates are counted by pattern; there is no AST for them. Every one of
# these scripts reports a failure by writing to stderr or by calling its own
# `fail` helper, so that is the rule.
#
# This pattern was wrong twice while being written, both times in the same
# direction -- reporting ZERO for a file full of failure paths, which is the
# defect this gate exists to catch, one level up. First it required FAIL
# immediately after the opening quote, which does not match
# `printf 'sim: FAIL: ...'`: run-sim.sh, golden/run.sh and check-dco.sh all
# scored 0. Then it anchored `fail` to the start of the line, which does not
# match `[ -f X ] || fail "..."`: validate-layout.sh scored 1 against 19.
#
# A multi-line shell report writes several times to stderr, so this counts one
# site per LINE where the Python side counts one per CALL. The shell number is
# therefore an over-count of distinct checks -- the conservative direction for
# a figure whose claim is "pinned by nothing".
SHELL_SITE = re.compile(r"""(\bfail\s+["'$]|>&2\s*\\?\s*$)""")


class GateUnavailable(Exception):
    """The measurement could not be performed. Never reported as a pass."""


def makefile_gates() -> list[str]:
    """Every script path the Makefile invokes, read out of the Makefile.

    The population used to be `ROOT.rglob("*.py")` filtered to files containing
    `def self_test`, which is the set of gates that already pass this gate's
    entrance exam -- a census that cannot see what it exists to find. A gate is
    something `make all` runs, so that is what is enumerated.

    Module invocations (`cd lang && python3 -m bakeoff check`) are excluded:
    they are packages with their own unittest suites, not single-file gates
    with a `--self-test`. That exclusion is by construction -- no path appears
    -- rather than by a list somebody has to maintain.
    """
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    found = []
    for match in re.finditer(r"(?:python3|bash|sh)\s+(\S+\.(?:py|sh))", text):
        rel = match.group(1)
        if (ROOT / rel).is_file() and rel not in found:
            found.append(rel)
    return sorted(found)


def uncollected_tests() -> list[str]:
    """Test files under a discovered directory that no `-p` pattern collects.

    `make bakeoff` and `make grammar` each run `unittest discover` with an
    EXACT filename -- `-p 'test_bakeoff.py'`, `-p 'test_grammar.py'` -- because
    one needs lark and the other must stay stdlib-only. The collected
    population is therefore two hand-named files rather than the directory, so
    a contributor adding the obviously-named lang/tests/test_foo.py gets it
    silently ignored by `make all` and by CI. An auditor planted a failing test
    there and both stayed green.

    The inverse direction already fails correctly: renaming test_grammar.py
    away makes `unittest discover` exit non-zero with NO TESTS RAN. Only the
    additive direction was open.
    """
    import fnmatch
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    patterns: dict[str, list[str]] = {}
    for match in re.finditer(
            r"unittest discover -s (?P<dir>\S+)(?P<rest>[^\n]*)", text):
        found = re.search(r"-p ['\"]?(?P<pattern>[^'\"\s]+)",
                          match.group("rest"))
        # unittest's own default when no -p is given.
        patterns.setdefault(match.group("dir"), []).append(
            found.group("pattern") if found else "test*.py")
    missed = []
    for directory, globs in sorted(patterns.items()):
        path = ROOT / directory
        if not path.is_dir():
            continue
        for test in sorted(path.glob("test_*.py")):
            name = test.name
            if not any(fnmatch.fnmatch(name, glob) for glob in globs):
                missed.append(f"{directory}/{name}")
    return missed


def appended_owners(source: str) -> set[str]:
    """Every `<name>.append(` owner in the file, for the classification check."""
    owners = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if getattr(func, "attr", None) != "append":
            continue
        owner = getattr(getattr(func, "value", None), "id", None)
        if owner:
            owners.add(owner)
    return owners


def report_sites(source: str, report_owners: set[str]) -> list[int]:
    """Line numbers of report calls outside the gate's own self_test().

    Parsed, not searched. The first version took `source.find("def self_test(")`
    as the limit, which is a TEXTUAL position: every check function defined
    BELOW self_test in the file was invisible. check-design-docs.py defines
    model_problems, line_count_problems and mode_table_problems after it, so 14
    of its 23 sites were never measured and its published ceiling was 5 against
    a real 17.
    """
    tree = ast.parse(source)
    excluded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "self_test":
            excluded.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name == "append":
            owner = getattr(getattr(func, "value", None), "id", None)
            if owner not in report_owners:
                continue
        elif name not in REPORT_CALLS:
            continue
        if node.lineno in excluded:
            continue
        sites.append(node.lineno - 1)
    return sorted(set(sites))


def shell_report_sites(source: str) -> list[int]:
    """Failure-reporting lines in a shell gate, counted rather than measured."""
    # search, not match: the pattern is no longer anchored to the start of the
    # line, because `[ -f X ] || fail "..."` reports from the middle of one.
    return [i for i, line in enumerate(source.splitlines())
            if SHELL_SITE.search(line)]


def blank_site(source: str, line_no: int) -> str:
    """Replace the call at `line_no` with `pass`, using its PARSED extent.

    Counting parentheses per line is lexical: a paren inside a string literal
    over-blanks and eats the next independent check, and a `#` comment
    containing `)` ends the span early and leaves an orphan continuation. Both
    make the mutant MORE damaged, so the self-test fails and the site scores as
    covered -- the number improves without the gate improving.
    """
    tree = ast.parse(source)
    extent = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.lineno - 1 == line_no:
            end = node.end_lineno or node.lineno
            if extent is None or end > extent:
                extent = end
    lines = source.splitlines(keepends=True)
    indent = len(lines[line_no]) - len(lines[line_no].lstrip())
    last = (extent or (line_no + 1)) - 1
    for index in range(line_no, last + 1):
        lines[index] = " " * indent + "pass\n"
    return "".join(lines)


def _last_line(result) -> str:
    """The most informative line of a failed run, or a stand-in if it printed
    nothing. Indexing [-1] of an empty split is how this crashed once."""
    text = (result.stderr or result.stdout or "").strip()
    return text.splitlines()[-1][:120] if text else "(no output)"


def surviving_sites(gate: Path, report_owners: set[str]) -> tuple[int, int, list[int]]:
    """(sites, survivors, survivor line numbers) for one gate."""
    source = gate.read_text(encoding="utf-8")
    sites = report_sites(source, report_owners)
    # THE BASELINE MUST PASS FIRST. Nothing checked that the UNMUTATED gate's
    # self-test exits 0, so a self-test that cannot run at all -- PyYAML absent,
    # which is true of four of these gates in CI's schemas job -- made every
    # blanked site score as "caught" and the gate report perfect coverage. It
    # then told the maintainer to pin those fabricated zeros. An unavailable
    # measurement is not a measurement.
    inner_env = {**os.environ, "RHOFORM_GATE_COVERAGE_INNER": "1"}
    baseline = subprocess.run([sys.executable, str(gate), "--self-test"],
                              capture_output=True, text=True, cwd=ROOT,
                              env=inner_env, timeout=300)
    if baseline.returncode != 0:
        # `gate.relative_to(ROOT)` raises for a probe in a TemporaryDirectory,
        # so the unavailability report died on its own error path.
        shown = gate.relative_to(ROOT) if gate.is_relative_to(ROOT) else gate
        raise GateUnavailable(
            f"{shown}: its own --self-test exits "
            f"{baseline.returncode} before any mutation, so every site would "
            "score as caught. Install the pinned dependencies and re-run: "
            f"{_last_line(baseline)}")
    survivors = []
    backup = gate.with_suffix(gate.suffix + ".coverage-backup")
    shutil.copy(gate, backup)
    try:
        for line_no in sites:
            gate.write_text(blank_site(source, line_no), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(gate), "--self-test"],
                capture_output=True, text=True, cwd=ROOT,
                env=inner_env, timeout=300)
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


def has_self_test(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    return "--self-test" in text and ("def self_test" in text or "self_test()" in text)


def census(problems: list[str], gates=None) -> list[str]:
    """Every Makefile gate lands in exactly one bucket, or this fails.

    The buckets are CEILINGS (measured) and NO_SELF_TEST (verified to have
    none). There is deliberately no third bucket: the one this replaced said
    its entries were too small to measure, nothing checked that, and the two it
    named had 11 and 4 real report sites. A gate in neither bucket is the case
    this function exists for: a new gate shipping with zero coverage and
    nothing saying so.
    """
    unaccounted = []
    for rel in (gates if gates is not None else makefile_gates()):
        buckets = [name for name, holder in
                   (("CEILINGS", CEILINGS), ("NO_SELF_TEST", NO_SELF_TEST))
                   if rel in holder]
        if len(buckets) > 1:
            problems.append(f"{rel}: listed in {' and '.join(buckets)}; a gate "
                            "belongs to exactly one bucket")
        elif not buckets:
            unaccounted.append(rel)
            problems.append(
                f"{rel}: the Makefile runs it and this census does not account "
                "for it. Add it to CEILINGS with a measured (sites, ceiling), "
                "or to NO_SELF_TEST if it has none. A gate that is in no bucket "
                "is a gate whose coverage nobody has looked at.")
    return unaccounted


def check(problems: list[str], ceilings=None, owners=None, gates=None) -> tuple[int, int]:
    """(gates measured, report sites counted but unpinned in NO_SELF_TEST)."""
    census(problems, gates=gates)
    if gates is None:
        for missed in uncollected_tests():
            problems.append(
                f"{missed} is collected by no `unittest discover -p` pattern "
                "the Makefile uses, so it runs nowhere. A failing test in it "
                "leaves `make all` green.")
    owners = owners if owners is not None else OWNERS
    measured = 0
    for name, pinned in sorted((ceilings or CEILINGS).items()):
        recorded_sites, ceiling = pinned
        gate = ROOT / name
        if not gate.is_file():
            problems.append(f"{name}: named as a gate and is not present")
            continue
        source = gate.read_text(encoding="utf-8")
        if name not in owners:
            problems.append(f"{name}: no accumulator classification in OWNERS")
            continue
        report_owners, bookkeeping = owners[name]
        unclassified = appended_owners(source) - report_owners - bookkeeping
        if unclassified:
            problems.append(
                f"{name}: appends to {sorted(unclassified)}, which OWNERS "
                "classifies as neither a report accumulator nor bookkeeping. "
                "Classify it: an unclassified accumulator is a check this "
                "measurement cannot see, which is how `failures` and `hits` "
                "went uncounted while their gates were excused for having no "
                "sites.")
            continue
        try:
            sites, survivors, where = surviving_sites(gate, report_owners)
        except subprocess.TimeoutExpired:
            raise GateUnavailable(f"{name}: --self-test did not terminate")
        # A gate with NO report sites scores a perfect zero for free. That is
        # the only size that invalidates the number.
        if sites == 0:
            problems.append(
                f"{name}: has no report site this measurement can see, so its "
                "coverage number is a free zero. Either it reports through a "
                "path OWNERS does not classify, or it checks nothing.")
            continue
        if sites < SMALL_POPULATION:
            print(f"gate-coverage: {name}: {survivors} of {sites} survive; a "
                  "small population, so read the number with that in mind.")
        if sites < recorded_sites:
            problems.append(
                f"{name}: {sites} report site(s), down from the recorded "
                f"{recorded_sites}. The ceiling of {ceiling} is measured over "
                "this population; shrinking it silently is how 28% of the "
                "sites left the measurement with every ceiling still met.")
            continue
        if sites > recorded_sites:
            print(f"gate-coverage: {name}: {sites} report site(s), up from the "
                  f"recorded {recorded_sites}. Record the new count in the same "
                  "commit.")
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

    unpinned = 0
    for rel in NO_SELF_TEST:
        gate = ROOT / rel
        if not gate.is_file():
            problems.append(f"{rel}: listed as having no self-test and is not present")
            continue
        if has_self_test(gate):
            problems.append(
                f"{rel}: listed in NO_SELF_TEST and has a --self-test. Measure "
                "it: move it to CEILINGS with its real numbers.")
            continue
        text = gate.read_text(encoding="utf-8")
        unpinned += (len(shell_report_sites(text)) if rel.endswith(".sh")
                     else len(report_sites(text, owners.get(rel, (set(), set()))[0])))
    return measured, unpinned


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
                  report_sites(SAMPLE, {"problems"}) == [3, 5]))
    cases.append(("a site inside self_test() is not counted",
                  all(n < SAMPLE.count("\n", 0, SAMPLE.index("def self_test("))
                      for n in report_sites(SAMPLE, {"problems"}))))
    cases.append(("an unclassified owner is not counted as a report site",
                  report_sites(SAMPLE, set()) == []))
    cases.append(("appended_owners finds the accumulator",
                  appended_owners(SAMPLE) == {"problems"}))

    blanked = blank_site(SAMPLE, 5)
    cases.append(("blanking spans a multi-line call",
                  "'always'" not in blanked and blanked.count("pass") == 2))
    cases.append(("blanking leaves the rest of the file intact",
                  "'never'" in blanked))

    # THE DISCOVERED POPULATION. The case that consumed the old discovery
    # asserted `not unlisted`, which a discovery returning NOTHING satisfies
    # perfectly -- the fix for a wrongly-scoped population was itself unpinned,
    # and replacing the glob with `[]` left all twelve cases green. Pin the set.
    discovered = makefile_gates()
    cases.append((f"the Makefile's gates are discovered ({len(discovered)})",
                  len(discovered) >= 15
                  and "tests/structure/check-layout.sh" in discovered
                  and "tests/meta/check-gate-coverage.py" in discovered))
    cases.append(("shell gates are in the discovered population",
                  sum(1 for g in discovered if g.endswith(".sh")) >= 4))
    cases.append(("shell report sites are counted",
                  len(shell_report_sites(
                      (ROOT / "tests/structure/check-layout.sh")
                      .read_text(encoding="utf-8"))) >= 20))
    # NO SHELL GATE SCORES ZERO. The pattern was wrong twice while being
    # written and both times the symptom was a zero, which reads exactly like
    # a gate with no failure paths. Every one of these scripts exits non-zero
    # somewhere, so a zero here is the counter being broken, not the gate being
    # clean.
    zeros = [rel for rel in NO_SELF_TEST if rel.endswith(".sh")
             and (ROOT / rel).is_file()
             and not shell_report_sites((ROOT / rel).read_text(encoding="utf-8"))]
    cases.append((f"no shell gate is counted at zero sites ({zeros})", not zeros))
    # THE COLLECTED TEST POPULATION. `-p 'test_bakeoff.py'` is an exact
    # filename, so a new lang/tests/test_*.py is collected by neither pattern
    # and runs nowhere; an auditor planted a failing test there and `make all`
    # stayed green. Pinned over a fixture directory so the case does not simply
    # assert that today's tree happens to be clean.
    import fnmatch as _fnmatch
    cases.append(("an exact -p pattern does not collect a sibling",
                  not _fnmatch.fnmatch("test_planted.py", "test_bakeoff.py")
                  and _fnmatch.fnmatch("test_planted.py", "test*.py")))
    cases.append(("both shell reporting styles are recognised",
                  len(shell_report_sites('  [ -f X ] || fail "gone"\n')) == 1
                  and len(shell_report_sites("  printf 'x: FAIL\\n' >&2\n")) == 1))

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.py"
        probe.write_text(SAMPLE, encoding="utf-8")
        sites, survivors, where = surviving_sites(probe, {"problems"})
        # The unreachable site (1 > 2) survives; the reachable one does not.
        cases.append(("an unreachable check is reported as surviving",
                      sites == 2 and survivors == 1 and where == [4]))
        cases.append(("the gate is restored after measurement",
                      probe.read_text(encoding="utf-8") == SAMPLE))

        # THE BASELINE GUARD. Round 13 added it as the fix for a blocker and
        # pinned it with nothing: `if baseline.returncode != 0:` -> `if False:`
        # left all twelve cases green. Without it, a self-test that cannot run
        # scores every site as caught and the gate reports perfect coverage.
        broken = Path(tmp) / "broken.py"
        broken.write_text(
            "import sys\n"
            "def check(problems):\n"
            "    problems.append('x')\n"
            "def self_test():\n"
            "    return 1\n"
            "if __name__ == '__main__':\n"
            "    raise SystemExit(self_test() if '--self-test' in sys.argv else 0)\n",
            encoding="utf-8")
        try:
            surviving_sites(broken, {"problems"})
            cases.append(("a gate whose baseline self-test fails is UNAVAILABLE", False))
        except GateUnavailable:
            cases.append(("a gate whose baseline self-test fails is UNAVAILABLE", True))

        # THE ENFORCEMENT BRANCH ITSELF. The first version keyed the probe on
        # `probe.relative_to(ROOT) if probe.is_relative_to(ROOT) else "probe.py"`
        # -- and probe lives in a TemporaryDirectory, so that is ALWAYS
        # "probe.py", a path under ROOT that never exists. The case named "a
        # gate above its ceiling is reported" passed on the `not present`
        # branch while the ceiling comparison was never reached.
        #
        # Measured inside ROOT so the branch is genuinely exercised, and big
        # enough that its numbers are not a small-population footnote.
        BIGGER = ("import sys\n"
                  "def check(problems):\n"
                  + "".join(f"    if {i} > 99:\n"
                            f"        problems.append('dead {i}')\n"
                            for i in range(5))
                  + "    if 2 > 1:\n"
                    "        problems.append('always')\n"
                    "def self_test():\n"
                    "    problems = []\n"
                    "    check(problems)\n"
                    "    return 0 if problems else 1\n"
                    "if __name__ == '__main__':\n"
                    "    raise SystemExit(self_test() if '--self-test' in sys.argv else 0)\n")
        inside = ROOT / "tests" / "meta" / ".coverage-probe.py"
        inside.write_text(BIGGER, encoding="utf-8")
        rel = inside.relative_to(ROOT).as_posix()
        probe_owners = {rel: ({"problems"}, set())}
        try:
            over = []
            check(over, ceilings={rel: (6, 0)}, owners=probe_owners, gates=[])
            cases.append(("a gate above its ceiling is reported", any(
                "survive being blanked" in p and "above the ceiling of 0" in p
                for p in over)))
            under = []
            check(under, ceilings={rel: (6, 9)}, owners=probe_owners, gates=[])
            cases.append(("a gate under its ceiling is not reported", not under))

            # THE DENOMINATOR. `REPORT_NAMES = ("append",)` removed 82 of 292
            # sites and every ceiling was still met, because only `survivors`
            # was ever compared to anything.
            shrunk = []
            check(shrunk, ceilings={rel: (99, 9)}, owners=probe_owners, gates=[])
            cases.append(("a shrunken report-site population is reported", any(
                "down from the recorded 99" in p for p in shrunk)))

            # THE OWNER CLASSIFICATION. An accumulator in neither half must
            # fail rather than be silently invisible, which is what let
            # `failures` and `hits` go uncounted.
            unclassified = []
            check(unclassified, ceilings={rel: (6, 9)},
                  owners={rel: (set(), set())}, gates=[])
            cases.append(("an unclassified accumulator is reported", any(
                "classifies as neither" in p for p in unclassified)))

            # A GATE WITH NOTHING TO MEASURE. A free zero is the one size that
            # invalidates the number; everything above zero is measured, small
            # or not, because "too small to measure" was the excuse that took
            # two gates with 11 and 4 real sites out of the census.
            nothing = ROOT / "tests" / "meta" / ".coverage-probe-empty.py"
            nothing.write_text(
                "import sys\n"
                "def check(problems):\n"
                "    return 0\n"
                "def self_test():\n"
                "    return 0\n"
                "if __name__ == '__main__':\n"
                "    raise SystemExit(self_test() if '--self-test' in sys.argv else 0)\n",
                encoding="utf-8")
            empty_rel = nothing.relative_to(ROOT).as_posix()
            try:
                free = []
                check(free, ceilings={empty_rel: (0, 0)},
                      owners={empty_rel: ({"problems"}, set())}, gates=[])
                cases.append(("a gate with no report sites is reported", any(
                    "free zero" in p for p in free)))
            finally:
                nothing.unlink()

            # THE CENSUS. A Makefile gate in no bucket must fail; that is the
            # whole population defect, and the old code could not express it.
            unaccounted = []
            census(unaccounted, gates=["tests/structure/check-layout.sh",
                                       "tests/meta/nonexistent-gate.py"])
            cases.append(("a Makefile gate in no bucket is reported", any(
                "does not account for it" in p for p in unaccounted)))
            cases.append(("a gate that IS in a bucket is not reported", not any(
                "check-layout.sh" in p for p in unaccounted)))
        finally:
            inside.unlink()

    # NO_SELF_TEST must be true of every entry.
    cases.append(("no NO_SELF_TEST entry has a self-test", not [
        rel for rel in NO_SELF_TEST if (ROOT / rel).is_file()
        and has_self_test(ROOT / rel)]))
    cases.append(("every CEILINGS entry does have a self-test", all(
        has_self_test(ROOT / rel) for rel in CEILINGS if (ROOT / rel).is_file())))

    # WIRING over the real gates: the shipped ceilings must hold. Skipped when
    # this gate is measuring ITSELF -- see INNER. Everything above runs either
    # way, so a mutant is still judged by fourteen probe-driven cases.
    if not INNER:
        # Kept out of the INNER set with the wiring below: a REAL-TREE
        # condition failing inside the self-test turns self-measurement into
        # GateUnavailable, so an uncollected test file reported itself as an
        # environment problem (exit 2) instead of the failure it is (exit 1).
        cases.append((f"today's test files are all collected "
                      f"({uncollected_tests()})", not uncollected_tests()))
        real = []
        measured, unpinned = check(real)
        cases.append((f"every shipped gate is at or under its ceiling ({real})", not real))
        cases.append(("every named gate was measured", measured == len(CEILINGS)))
        cases.append(("the unpinned shell total is published", unpinned > 0))

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
        measured, unpinned = check(problems)
    except GateUnavailable as exc:
        print(f"gate-coverage: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    if problems:
        print("gate-coverage: FAIL:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"gate-coverage: PASS: {measured} gate(s) at or under their "
          f"self-test coverage ceiling; {len(NO_SELF_TEST)} gate(s) have no "
          f"self-test at all and their {unpinned} report site(s) are pinned by "
          "nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
