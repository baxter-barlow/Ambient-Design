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
     against. Round 14 closed four of the five shell gates this way -- each
     now measured under CEILINGS like everything else -- leaving only the
     validate-layout skill script, whose self-test is blocked on skill-change
     policy (see the NO_SELF_TEST comment) rather than on nobody writing it.

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
    ".github/scripts/check-dco.sh": (4, 0),
    "lang/tests/check_readme_numbers.py": (36, 16),
    "parts/lint-part-data.py": (30, 5),
    "tests/benchmarks/check-assertions.py": (18, 3),
    "tests/benchmarks/check-corners.py": (22, 9),
    "tests/benchmarks/check-design-docs.py": (31, 21),
    "tests/benchmarks/check-hand-assertions.py": (28, 15),
    "tests/benchmarks/run-sim.sh": (11, 0),
    "tests/benchmarks/derive-555-windows.py": (5, 0),
    "tests/corpus/check-classification.py": (54, 18),
    "tests/corpus/check-corpus.py": (27, 3),
    "tests/eval/check-run-records.py": (62, 9),
    "tests/ir/check-hashes.py": (19, 2),
    # Measured under INNER, so 6 is an upper bound: sites the skipped wiring
    # block would have caught score as surviving. The gate now measures itself,
    # which the version that excused itself as "too few sites" did not.
    "tests/meta/check-gate-coverage.py": (12, 6),
    "tests/schemas/validate-schemas.py": (11, 2),
    "tests/golden/run.sh": (6, 0),
    "tests/structure/check-layout.sh": (29, 0),
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
    # Shell gates report through `fail`/printf lines counted by SHELL_SITE,
    # not through accumulators; the empty classification keeps them in the
    # same census as everything else.
    ".github/scripts/check-dco.sh": (set(), set()),
    "tests/benchmarks/run-sim.sh": (set(), set()),
    "tests/golden/run.sh": (set(), set()),
    "tests/structure/check-layout.sh": (set(), set()),
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
        {"problems"}, {"cases", "numbers", "spans"}),
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
                       "gates", "notes", "unaccounted", "missed",
                       "_TREE_DIGEST_MEMO"}),
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
    # The one remaining member. It is a PROJECT SKILL script, and AGENTS.md
    # allows skill changes only through a dedicated Linear issue with
    # independent review -- so its self-test is recorded work, not a silent
    # gap: its 19 report sites stay in the published unpinned total until
    # that issue lands.
    ".agents/skills/verify-rhoform-change/scripts/validate-layout.sh",
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


def makefile_gates(text=None) -> list[str]:
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
    if text is None:
        text = (ROOT / "Makefile").read_text(encoding="utf-8")
    found = []
    for line in text.splitlines():
        # Comments are not invocations. The regex used to run over the whole
        # file, so `#`-ing a recipe line out DISABLED the gate while the
        # census still listed it as covered -- the exact silent unhooking the
        # census exists to catch, hidden by its own parser.
        if line.lstrip().startswith("#"):
            continue
        for match in re.finditer(r"(?:python3|bash|sh)\s+(\S+\.(?:py|sh))", line):
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
    #
    # A self_test() body is excluded, exactly as report_sites() excludes the
    # Python one: its FAIL lines report on the self-test, not on the tree, and
    # counting them handed every migrated shell gate one permanent survivor.
    # The extent is the function opener to the first column-0 `}` -- these
    # scripts are written to that shape, and a self_test whose closer is
    # indented would put its lines back IN the population, which fails safe.
    sites, in_self_test = [], False
    for i, line in enumerate(source.splitlines()):
        if re.match(r"self_test\s*\(\)", line):
            # A one-line `self_test() { ...; }` closes itself; entering
            # exclusion mode for it would swallow every later site in the
            # file, which is how the syntax-fragility probe briefly scored
            # zero sites.
            in_self_test = not line.rstrip().endswith("}")
        elif in_self_test and line.rstrip() == "}":
            in_self_test = False
        elif not in_self_test and SHELL_SITE.search(line):
            sites.append(i)
    return sites


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


def blank_shell_site(source: str, line_no: int) -> str:
    """Replace one shell report line with a no-op colon command.

    Line-scoped where the Python side is statement-scoped, because that is
    what SHELL_SITE counts. A line that cannot be blanked without breaking
    the script's syntax (a continuation, a one-line case arm carrying its own
    `;;`) is handled by the caller: the mutant fails `bash -n` and the site
    scores as SURVIVING, because a self-test that only fails on a syntax
    error has not pinned the check."""
    lines = source.splitlines(keepends=True)
    indent = len(lines[line_no]) - len(lines[line_no].lstrip())
    lines[line_no] = " " * indent + ":\n"
    return "".join(lines)


def _last_line(result) -> str:
    """The most informative line of a failed run, or a stand-in if it printed
    nothing. Indexing [-1] of an empty split is how this crashed once."""
    text = (result.stderr or result.stdout or "").strip()
    return text.splitlines()[-1][:120] if text else "(no output)"


def _machinery_salt() -> str:
    """Hash of the mutation machinery itself, so editing how sites are
    counted, blanked or JUDGED invalidates every cached measurement. Round 15
    showed the first version's docstring claimed "judged" while the salt
    covered only counting and blanking -- surviving_sites (the runner, the
    exit-code judgement, the bash -n rule) is hashed now, and so is the tree
    digest function whose output joins the key."""
    import hashlib
    import inspect
    digest = hashlib.sha256()
    digest.update(SHELL_SITE.pattern.encode("utf-8"))
    for fn in (report_sites, shell_report_sites, blank_site, blank_shell_site,
               surviving_sites, _tree_digest, _cache_key):
        digest.update(inspect.getsource(fn).encode("utf-8"))
    return digest.hexdigest()


def _tree_digest():
    """Content hash of every git-tracked file, or None when git is absent.

    A mutation outcome depends on everything a gate's self-test reads --
    part fixtures, the frozen IR example, the Makefile -- not only on the
    gate's own bytes, and round 15 reproduced stale cache hits through
    exactly those inputs. Keying on the whole tracked tree is coarse: any
    edit anywhere re-measures every gate. That is the correct direction;
    a cheaper key that misses an input serves a wrong number. When the
    digest cannot be computed the cache is DISABLED, not trusted.
    """
    import hashlib
    try:
        listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                                 capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if listing.returncode != 0:
        return None
    digest = hashlib.sha256()
    for rel in listing.stdout.decode("utf-8", "replace").split("\0"):
        if not rel:
            continue
        try:
            data = (ROOT / rel).read_bytes()
        except OSError:
            data = b"<unreadable>"
        digest.update(rel.encode("utf-8"))
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


# Computed once per process, BEFORE any mutation is written: the loop below
# swaps mutants into tracked files, and a digest taken mid-measurement would
# key on a tree state that never exists at rest.
_TREE_DIGEST_MEMO = []


def _tree_digest_cached():
    if not _TREE_DIGEST_MEMO:
        _TREE_DIGEST_MEMO.append(_tree_digest())
    return _TREE_DIGEST_MEMO[0]


def _cache_key(source: str, report_owners: set[str], tree) -> str:
    import hashlib
    return hashlib.sha256(
        (source + repr(sorted(report_owners)) + str(tree) + _machinery_salt())
        .encode("utf-8")).hexdigest()


def _mutation_cache_path() -> Path:
    """A per-machine, per-checkout cache file in the system temp directory.

    Not committed: the measurement is a pure function of the gate's bytes and
    this file's machinery, so a cold cache costs one full measurement and a
    warm one costs nothing -- but a committed file would assert results for
    machines that never ran them."""
    import hashlib
    import tempfile
    tag = hashlib.sha256(str(ROOT).encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"rhoform-gate-coverage-{tag}.json"


def _load_mutation_cache() -> dict:
    import json
    try:
        return json.loads(_mutation_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _store_mutation_cache(cache: dict) -> None:
    import json
    try:
        _mutation_cache_path().write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass  # a cache that cannot be written is only a slower measurement


def surviving_sites(gate: Path, report_owners: set[str],
                    cache: dict | None = None) -> tuple[int, int, list[int]]:
    """(sites, survivors, survivor line numbers) for one gate.

    THE BASELINE SELF-TEST ALWAYS RUNS -- the environment can rot under an
    unchanged gate (PyYAML uninstalled, ngspice gone), and the baseline is
    what catches that. Only the mutation LOOP is cached, keyed on the gate's
    bytes, the owner classification and the machinery hash: with a working
    environment its outcome is a pure function of those, and re-running
    27 mutants of a six-second self-test on every make invocation priced the
    measurement out of the default gate run.
    """
    import hashlib
    source = gate.read_text(encoding="utf-8")
    shell = gate.suffix == ".sh"
    sites = (shell_report_sites(source) if shell
             else report_sites(source, report_owners))
    # THE BASELINE MUST PASS FIRST. Nothing checked that the UNMUTATED gate's
    # self-test exits 0, so a self-test that cannot run at all -- PyYAML absent,
    # which is true of four of these gates in CI's schemas job -- made every
    # blanked site score as "caught" and the gate report perfect coverage. It
    # then told the maintainer to pin those fabricated zeros. An unavailable
    # measurement is not a measurement.
    inner_env = {**os.environ, "RHOFORM_GATE_COVERAGE_INNER": "1"}
    runner = (["bash", str(gate), "--self-test"] if shell
              else [sys.executable, str(gate), "--self-test"])
    baseline = subprocess.run(runner,
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
    tree = _tree_digest_cached()
    if tree is None:
        cache = None  # no digest, no cache: an unverifiable key is not a key
    cache_key = _cache_key(source, report_owners, tree)
    if cache is not None and cache_key in cache:
        cached_sites, cached_survivors = cache[cache_key]
        return cached_sites, len(cached_survivors), list(cached_survivors)
    survivors = []
    backup = gate.with_suffix(gate.suffix + ".coverage-backup")
    shutil.copy(gate, backup)

    def swap_in(text: str) -> None:
        # Write-to-temp then atomic rename. `gate.write_text` opened the REAL
        # gate with truncation, so an ENOSPC between the truncate and the
        # write left a ZERO-BYTE gate on disk -- and the finally's restore
        # copy failed on the same full disk, so the tree stayed corrupted.
        # A rename needs no new blocks; a failed temp write leaves the gate
        # untouched.
        scratch = gate.with_suffix(gate.suffix + ".coverage-mutant")
        scratch.write_text(text, encoding="utf-8")
        os.replace(scratch, gate)

    try:
        for line_no in sites:
            swap_in((blank_shell_site if shell else blank_site)
                    (source, line_no))
            if shell:
                syntax = subprocess.run(["bash", "-n", str(gate)],
                                        capture_output=True, timeout=60)
                if syntax.returncode != 0:
                    # A blank that breaks the script is not a deleted check;
                    # a self-test that goes red on the syntax error proves
                    # nothing about the CHECK, so score it as unpinned.
                    survivors.append(line_no + 1)
                    swap_in(source)
                    continue
            result = subprocess.run(
                runner,
                capture_output=True, text=True, cwd=ROOT,
                env=inner_env, timeout=300)
            if result.returncode == 0:
                survivors.append(line_no + 1)
            swap_in(source)
    except OSError as exc:
        raise GateUnavailable(
            f"mutating {gate.name} failed mid-loop ({exc}); the gate itself "
            "is intact and its .coverage-backup still exists") from exc
    finally:
        # Restore from the backup, not from `source`: if this process dies
        # mid-loop the gate is left mutated, which is the shared-writable-state
        # hazard AGENTS.md forbids and which a sibling probe already caused.
        try:
            os.replace(backup, gate)
        except OSError:
            shutil.copy(backup, gate)
            backup.unlink()
    if cache is not None:
        cache[cache_key] = [len(sites), survivors]
    return len(sites), len(survivors), survivors


def has_self_test(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    return "--self-test" in text and ("def self_test" in text or "self_test()" in text)


def census(problems: list[str], gates=None, ceilings=None,
           no_self_test=None) -> list[str]:
    """Every Makefile gate lands in exactly one bucket, or this fails.

    The buckets are CEILINGS (measured) and NO_SELF_TEST (verified to have
    none). There is deliberately no third bucket: the one this replaced said
    its entries were too small to measure, nothing checked that, and the two it
    named had 11 and 4 real report sites. A gate in neither bucket is the case
    this function exists for: a new gate shipping with zero coverage and
    nothing saying so.
    """
    unaccounted = []
    ceilings = CEILINGS if ceilings is None else ceilings
    no_self_test = NO_SELF_TEST if no_self_test is None else no_self_test
    population = gates if gates is not None else makefile_gates()
    for rel in population:
        buckets = [name for name, holder in
                   (("CEILINGS", ceilings), ("NO_SELF_TEST", no_self_test))
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
    # THE REVERSE DIRECTION, which round 15 demonstrated was open end to end:
    # deleting a gate's invocations from the Makefile and CI left the gate
    # running NOWHERE while this census (population = the Makefile's), the
    # measurement loop (population = CEILINGS, measured off disk whether or
    # not anything invokes them) and check-pins' Makefile-subset-of-CI parity
    # all stayed green. A bucket entry the Makefile no longer runs is a gate
    # that has been unhooked, not retired -- retiring one means removing it
    # from the bucket in the same commit, which is a visible decision.
    for name, holder in (("CEILINGS", ceilings), ("NO_SELF_TEST", no_self_test)):
        for rel in sorted(holder):
            if rel not in population:
                problems.append(
                    f"{rel}: listed in {name} and the Makefile no longer runs "
                    "it, so its checks execute nowhere while its coverage is "
                    "still reported as measured. Rewire the Makefile, or "
                    "remove the entry in the same commit as a deliberate "
                    "retirement.")
    return unaccounted


def check(problems: list[str], ceilings=None, owners=None, gates=None) -> tuple[int, int]:
    """(gates measured, report sites counted but unpinned in NO_SELF_TEST)."""
    census(problems, gates=gates, ceilings=ceilings,
           no_self_test=NO_SELF_TEST if gates is None else ())
    if gates is None:
        for missed in uncollected_tests():
            problems.append(
                f"{missed} is collected by no `unittest discover -p` pattern "
                "the Makefile uses, so it runs nowhere. A failing test in it "
                "leaves `make all` green.")
    owners = owners if owners is not None else OWNERS
    measured = 0
    mutation_cache = _load_mutation_cache()
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
        # A shell gate has no accumulators to classify -- its sites are
        # SHELL_SITE lines -- and ast.parse on bash is a crash, not a census.
        unclassified = (set() if name.endswith(".sh")
                        else appended_owners(source) - report_owners - bookkeeping)
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
            sites, survivors, where = surviving_sites(gate, report_owners,
                                                      cache=mutation_cache)
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
    _store_mutation_cache(mutation_cache)

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
    cases.append(("a report line inside a shell self_test is not counted",
                  shell_report_sites(
                      'self_test() {\n  fail "mine"\n}\nfail "real"\n') == [3]))
    cases.append(("a one-line self_test does not swallow later sites",
                  shell_report_sites(
                      'self_test() { :; }\nfail "real"\n') == [1]))

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

        # THE SHELL SIDE of the same machinery. A shell gate is mutated per
        # LINE (that is what SHELL_SITE counts), run with bash, and a blank
        # that breaks the script's syntax scores as SURVIVING: a self-test
        # that only goes red on a syntax error has not pinned the check.
        SHELL_SAMPLE = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "fail() { printf 'FAIL: %s\\n' \"$1\" >&2; exit 1; }\n"
            "self_test() {\n"
            "  if out=$(bash \"$0\" broken 2>&1); then return 1; fi\n"
            "  case \"$out\" in *pinned*) : ;; *) return 1 ;; esac\n"
            "  return 0\n"
            "}\n"
            "[ \"${1:-}\" != \"--self-test\" ] || { self_test; exit $?; }\n"
            "[ \"${1:-}\" != broken ] || fail \"pinned check\"\n"
            "[ \"${1:-}\" != quiet ] || fail \"unpinned check\"\n"
            "echo PASS\n"
        )
        shell_probe = Path(tmp) / "probe.sh"
        shell_probe.write_text(SHELL_SAMPLE, encoding="utf-8")
        sh_sites, sh_survivors, sh_where = surviving_sites(shell_probe, set())
        cases.append(("a pinned shell site is caught and an unpinned one "
                      "survives",
                      sh_sites == 2 and sh_survivors == 1 and sh_where == [11]))
        cases.append(("the shell gate is restored after measurement",
                      shell_probe.read_text(encoding="utf-8") == SHELL_SAMPLE))
        FRAGILE = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "fail() { printf 'FAIL: %s\\n' \"$1\" >&2; exit 1; }\n"
            "self_test() { bash -n \"$0\"; }\n"
            "[ \"${1:-}\" != \"--self-test\" ] || { self_test; exit $?; }\n"
            "case \"${1:-}\" in\n"
            "  broken) fail \"inside a case arm\" ;;\n"
            "esac\n"
            "echo PASS\n"
        )
        fragile = Path(tmp) / "fragile.sh"
        fragile.write_text(FRAGILE, encoding="utf-8")
        fr_sites, fr_survivors, _ = surviving_sites(fragile, set())
        cases.append(("a syntax-breaking shell blank scores as surviving, "
                      "not caught",
                      fr_sites == 1 and fr_survivors == 1))

        # THE MUTATION CACHE. The loop's outcome is a pure function of the
        # gate's bytes, the owner set and the machinery, so check() caches
        # it -- the BASELINE still runs uncached every time, which is what
        # keeps a rotted environment loud. A poisoned entry proves the read
        # path is real; an edited gate must miss it.
        probe_cache = {}
        cases.append(("a mutation result lands in the cache",
                      surviving_sites(shell_probe, set(), cache=probe_cache)
                      == (2, 1, [11]) and len(probe_cache) == 1))
        poisoned = {key: [99, [1, 2, 3]] for key in probe_cache}
        cases.append(("a cached measurement is returned without re-running",
                      surviving_sites(shell_probe, set(), cache=poisoned)
                      == (99, 3, [1, 2, 3])))
        edited_probe = Path(tmp) / "edited.sh"
        edited_probe.write_text(SHELL_SAMPLE + "# edited\n", encoding="utf-8")
        cases.append(("an edited gate misses the cache",
                      surviving_sites(edited_probe, set(), cache=poisoned)
                      == (2, 1, [11])))
        # The key covers the WHOLE tracked tree, not just the gate: a
        # self-test's fixtures live outside the gate file, and round 15
        # served a stale measurement through exactly that gap.
        cases.append(("a changed tree digest misses the cache",
                      _cache_key("x", set(), "tree-a")
                      != _cache_key("x", set(), "tree-b")))
        cases.append(("the tree digest is computable in this checkout",
                      isinstance(_tree_digest_cached(), str)))

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
            check(over, ceilings={rel: (6, 0)}, owners=probe_owners, gates=[rel])
            cases.append(("a gate above its ceiling is reported", any(
                "survive being blanked" in p and "above the ceiling of 0" in p
                for p in over)))
            under = []
            check(under, ceilings={rel: (6, 9)}, owners=probe_owners, gates=[rel])
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
                "check-layout.sh" in p and "does not account" in p
                for p in unaccounted)))
            # THE REVERSE DIRECTION. The probe population above omits every
            # real bucket entry except check-layout, so each omission must be
            # reported as an unhooked gate -- and check-layout must not be.
            cases.append(("a bucket entry the Makefile no longer runs is "
                          "reported", any(
                "check-dco.sh" in p and "no longer runs it" in p
                for p in unaccounted)))
            cases.append(("a bucket entry the Makefile still runs is not "
                          "reported as unhooked", not any(
                "check-layout.sh" in p and "no longer runs it" in p
                for p in unaccounted)))
        finally:
            inside.unlink()

    # A commented-out recipe line is not an invocation; the census parser
    # matched them, so #-ing a gate out kept it "covered" while disabling it.
    cases.append(("a commented-out recipe line is not counted as a gate",
                  makefile_gates("\tbash tests/structure/check-layout.sh\n"
                                 "#\tbash tests/golden/run.sh\n")
                  == ["tests/structure/check-layout.sh"]))

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
