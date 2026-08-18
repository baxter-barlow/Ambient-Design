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

WHAT IT CHECKS. Every published token count in lang/README.md -- the token
table, the decision table, and the language-card line -- against
`lang/token-counts.json`, exactly. These are integers from a pinned tokenizer,
so exact is right: there is no rounding to be generous about.

WHY AN ARTIFACT AND NOT A LIVE MEASUREMENT. The first version of this file
called the pinned tiktoken encoding directly. That made `make sim` depend on an
OPTIONAL package that no CI job installs, so the benchmarks-sim job could not
have passed as written -- and on a cold cache it fetched the vocabulary over
the network from inside a target whose contract is that it runs offline. That
is the identical defect tests/toolchain/check-pins.py had gone to explicit
trouble to fix for itself, reintroduced one file over.

So the counts are a committed artifact, regenerated deliberately with `--write`
by someone who has the tokenizer, exactly as corpus/classification.yaml pins
decision_hash. The offline gate reads the artifact; `--verify` re-measures and
is run only where tiktoken is present. An artifact that drifts from the arms is
caught by `--verify`; a README that drifts from the artifact is caught here,
offline, always.

WHAT IT DELIBERATELY DOES NOT CHECK. Prose. The T9 annotation-tax table USED to
be excluded on the grounds that it was "the author's job" -- and it then stayed
stale through two separate corrections, because an exclusion is an invitation.
It is gated now.

Exit codes: 0 pass, 1 a table disagrees with the harness, 2 environment.

    python3 lang/tests/check_readme_numbers.py --self-test
    python3 lang/tests/check_readme_numbers.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "lang" / "README.md"
ARTIFACT = ROOT / "lang" / "token-counts.json"

# design -> the example model that renders it
DESIGNS = ("blinker-555", "esp32s3-devboard")
# starlark included. The first version listed only the candidates, so 14 of the
# README's 26 published counts were outside the gate -- and 8 of those 14 were
# stale, including every blinker cell of the table headed "The decision", whose
# numbers the headline percentage is computed from. The docstring said "every
# row".
ARMS = ("candidate_a", "candidate_b", "starlark")
VARIANTS = ("explicit", "inferred", "inferred+columnar")

# Backticks and bold are ordinary Markdown. Requiring BARE names made a row
# unparseable -- and unparseable was SILENT, so backticking the decision table
# dropped the gate from 27 cells to 16 with no diagnostic at all.
ROW = re.compile(
    r"^\|\s*[`*]*(?P<design>[a-z0-9-]+)[`*]*\s*\|\s*[`*]*(?P<arm>[a-z_]+)[`*]*\s*\|(?P<rest>.+)\|\s*$")
# `| **candidate_b** | 748 | 5003 | 4160 | 886 | ... |` -- the decision table,
# whose first cell is the ARM. ROW's design pattern is `[a-z0-9-]+`, which
# cannot match `candidate_a`, so all seven of this table's token cells were
# outside the gate by construction and four of them were stale.
DECISION_ROW = re.compile(
    r"^\|\s*[`*]*(?P<arm>candidate_a|candidate_b|starlark)[`*]*\s*\|(?P<rest>.+)\|\s*$")
# The decision table's token columns, in order.
DECISION_KEYS = (
    "blinker-555|{arm}|inferred",
    "esp32s3-devboard|{arm}|inferred",
    "esp32s3-devboard|{arm}|inferred+columnar",
    "card|{arm}",
)
CELL_NUMBER = re.compile(r"-?\d+")

# How many rows each table must contribute. A row that stops being parsed also
# stops being checked, so the count is pinned rather than counted.
# DISTINCT (design, arm) rows, not cells: the floor counted cells, so
# duplicating a correct row paid for one that had stopped parsing.
# PER CATEGORY. One total let the token table detach from its locator on a
# blank line -- taking six rows with it -- and be paid for by the T9 rows the
# comment never counted. Every locator stops at the first non-table line, so
# detaching a table silently removes it; the only thing that can notice is a
# floor scoped to that table.
MINIMUM_ROWS_BY_KIND = {
    "blinker-555": 3,        # token-table rows for this design
    "esp32s3-devboard": 3,   # ditto
    "decision": 3,
    "card": 3,
    "t9": 6,
    "lines": 3,
}

# 6 rows x 3 rules, counted as DISTINCT (design, arm, rule) identities: six
# copies of one correct row met a cell count of 18 while five real rows left
# the document, which is the third recurrence of this exact defect here.
MINIMUM_T9_CELLS = 24
# The exact population the shipped README publishes: 16 token + 11 decision
# + 3 card + 24 T9 + 20 L6 sweep + 3 AC1a line counts. A total, not a floor:
# any leg detaching drops it.
MINIMUM_TOTAL_COUNTS = 77  # 6 rows x (3 rules + the `all` column)
# 4 rows x 5 thresholds.
MINIMUM_SWEEP_CELLS = 20


class GateUnavailable(Exception):
    """The check could not be performed. Never reported as a pass."""


def measure_now():
    """Measure every (design, arm, variant) with the pinned tokenizer.

    Only reachable via --write/--verify. The offline gate never calls this.
    """
    sys.path.insert(0, str(ROOT / "lang"))
    try:
        from bakeoff.arms import candidate_a, candidate_b, starlark
        from bakeoff.measure import load_tokenizer
        from bakeoff.model import load_model
    except ImportError as exc:  # pragma: no cover
        raise GateUnavailable(f"the bake-off harness is not importable: {exc}") from exc
    try:
        tokenizer = load_tokenizer()
    except Exception as exc:
        raise GateUnavailable(
            f"the pinned tokenizer is unavailable ({exc})") from exc

    arms = {"candidate_a": candidate_a, "candidate_b": candidate_b,
            "starlark": starlark}
    tokens = {}
    for design in DESIGNS:
        model = load_model(ROOT / "lang" / "examples" / f"{design}.design.json")
        for name, arm in arms.items():
            for variant in VARIANTS:
                try:
                    rendered = arm.render(model, variant)
                except Exception:
                    # starlark has no columnar variant; the README prints an
                    # em dash there and nothing should be invented for it.
                    continue
                tokens[f"{design}|{name}|{variant}"] = tokenizer.count(rendered)
    for name, arm in arms.items():
        tokens[f"card|{name}"] = tokenizer.count(arm.language_card())
    # THE T9 TABLE. It was a stated exclusion -- "Those remain the author's
    # job" -- and it stayed stale through TWO corrections because of that: a
    # round found 11 of 24 cells wrong, the prose ranges were recomputed from a
    # live run, the table was not, and the next round found 13 of 24. A number
    # this document calls "the reading that answers T9's question" cannot be
    # the one thing nothing checks. Stored to one decimal, which is how the
    # README publishes it.
    from bakeoff.measure import measure
    readings = measure()["readings"]
    # THE L6 SWEEP, stored per (design, arm, threshold).
    for design, arms_seen in readings["l6_threshold_curve"].items():
        for arm, reading in arms_seen.items():
            for threshold, saving in reading["saving_by_threshold"].items():
                tokens[f"l6|{design}|{arm}|{threshold}"] = saving
    # LINE COUNTS, which the harness does not publish, measured here from the
    # same renderers the token counts come from.
    from bakeoff.arms import candidate_a, candidate_b, starlark
    from bakeoff.model import load_model
    for design in DESIGNS:
        model = load_model(ROOT / "lang" / "examples" / f"{design}.design.json")
        for name, arm in {"candidate_a": candidate_a, "candidate_b": candidate_b,
                          "starlark": starlark}.items():
            for variant in VARIANTS:
                try:
                    rendered = arm.render(model, variant)
                except Exception:
                    continue
                tokens[f"lines|{design}|{name}|{variant}"] = len(
                    rendered.splitlines())
    t9 = readings["t9_by_rule"]
    for design, arms_seen in t9.items():
        for arm, reading in arms_seen.items():
            fractions = reading["by_rule_fraction"]
            for rule, value in fractions.items():
                tokens[f"t9|{design}|{arm}|{rule}"] = round(value * 1000)
    # THE `all` COLUMN, from the harness's own aggregate rather than a sum of
    # the rounded rule columns. It was read by nothing, and one of its six
    # cells was a tenth low.
    for design, arms_seen in readings["t9_annotation_tax"].items():
        for arm, reading in arms_seen.items():
            tokens[f"t9all|{design}|{arm}"] = round(
                1000 * reading["tax_tokens"] / reading["explicit_tokens"])
    return tokens


def inputs_fingerprint():
    """sha256 over everything that determines the counts.

    The artifact was pinned "exactly as corpus/classification.yaml pins
    decision_hash" -- but that analogy was false in the load-bearing way:
    decision_hash is RECOMPUTED OFFLINE, so drift breaks the build. This
    artifact was verified only by `--verify`, which no target and no CI job
    runs, and which needs a tokenizer no CI job installs. So changing an arm's
    renderer left README and artifact agreeing with each other, both stale,
    every gate green -- the "measured once, published forever" condition this
    file exists to end, moved one file over.

    Hashing the arm sources and the example models is offline and needs no
    tokenizer, so the artifact now goes stale LOUDLY.
    """
    import hashlib
    digest = hashlib.sha256()
    sources = sorted((ROOT / "lang" / "bakeoff").rglob("*.py"))
    sources += sorted((ROOT / "lang" / "examples").glob("*.design.json"))
    # THE RULER, which the first version left out. `measure.py` reads
    # `evaluation.tokenizer.encoding` from the manifest at runtime, so
    # re-pinning the tokenizer moves ALL NINETEEN counts -- and `check-pins`
    # cannot help, because that pin is read-by-key and its value is explicitly
    # not compared. Without this the artifact and the README stayed consistent
    # with each other, both measured with a tokenizer the manifest no longer
    # declares. This is the round-8 finding one input over.
    sources.append(ROOT / "toolchain" / "versions.yaml")
    for path in sources:
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def load_counts():
    """The committed artifact. Offline, no optional packages."""
    import json
    if not ARTIFACT.is_file():
        raise GateUnavailable(
            f"{ARTIFACT.name} is missing. Regenerate it on a machine with the "
            "pinned tokenizer: python3 lang/tests/check_readme_numbers.py --write")
    try:
        document = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        committed = document.get("inputs_fingerprint")
        actual = inputs_fingerprint()
        if committed != actual:
            raise GateUnavailable(
                f"{ARTIFACT.name} was measured against arms/examples that have "
                f"since changed (records {committed}, inputs now hash to "
                f"{actual}). Re-measure on a machine with the pinned tokenizer: "
                "python3 lang/tests/check_readme_numbers.py --write")
        return document["counts"]
    except (ValueError, KeyError) as exc:
        raise GateUnavailable(f"{ARTIFACT.name} is not readable: {exc}") from exc


def token_problems(text, counts, problems, minimum=None):
    """Every `| design | arm | ... |` row, against the committed counts."""
    checked = 0
    rows_seen = set()
    # THE TOKEN TABLE, located by its own header. Matching any `| design | arm |`
    # row also matched the L6 THRESHOLD SWEEP, whose rows have the same shape
    # but whose columns are thresholds rather than variants -- so the gate
    # compared a sweep saving against a token count and reported nonsense.
    all_lines = text.splitlines()
    def _norm(line):
        """Collapse whitespace and emphasis so a reflowed header still matches."""
        return re.sub(r"[\s*`]+", "", line).lower()

    token_headers = [i for i, line in enumerate(all_lines)
                     if _norm(line).startswith("|design|arm|") and "explicit" in _norm(line)]
    if len(token_headers) > 1:
        problems.append(
            f"lang/README.md: publishes the token table {len(token_headers)} "
            "times; only the first is read.")
    try:
        token_start = token_headers[0]
    except IndexError:
        problems.append(
            "lang/README.md: the token table's header row is gone, so its "
            "cells are checked by nothing.")
        token_start = len(all_lines)
    token_lines = []
    for line in all_lines[token_start:]:
        if not line.strip().startswith("|"):
            break
        token_lines.append(line)
    for line in token_lines:
        found = ROW.match(line.strip())
        if not found:
            continue
        design, arm = found.group("design"), found.group("arm")
        if design not in DESIGNS or arm not in ARMS:
            continue
        cells = [c.strip() for c in found.group("rest").split("|")]
        published = []
        for cell in cells:
            number = CELL_NUMBER.search(cell.replace(",", ""))
            published.append(None if number is None else int(number.group(0)))
        # Match cells to variants positionally, skipping em-dash / empty cells
        # rather than dropping the whole row: requiring exactly three cells
        # meant a row could leave the gate by growing a fourth column.
        for variant, value in zip(VARIANTS, published):
            if value is None:
                continue
            key = f"{design}|{arm}|{variant}"
            want = counts.get(key)
            if want is None:
                continue
            if value != want:
                problems.append(
                    f"lang/README.md: publishes {value} for {key}, but "
                    f"lang/token-counts.json records {want}. This is the "
                    "bake-off's published cost evidence.")
                continue
            rows_seen.add((design, arm))
            checked += 1
    # THE DECISION TABLE, which publishes the same `inferred` measurement as
    # the token table and disagreed with it in-file: 906 against 993, 748
    # against 814, 822 against 901.
    # LOCATED BY ITS OWN HEADER. Matching any row that starts with an arm name
    # also matched the DEFECT table, whose rows start the same way -- so the
    # gate compared 15/15 and 100% against token counts and reported nonsense.
    lines = all_lines
    decision_headers = [i for i, line in enumerate(lines)
                        if line.startswith("| ") and "(a)blinker" in _norm(line)
                        and "card" in _norm(line)]
    if len(decision_headers) > 1:
        problems.append(
            f"lang/README.md: publishes the decision table "
            f"{len(decision_headers)} times; only the first is read.")
    try:
        start = decision_headers[0]
    except IndexError:
        problems.append(
            "lang/README.md: the decision table's header row is gone, so its "
            "cells are checked by nothing. That table publishes the same "
            "`inferred` measurement as the token table and once disagreed "
            "with it in-file.")
        start = len(lines)
    for line in lines[start:]:
        if not line.strip().startswith("|"):
            break
        found = DECISION_ROW.match(line.strip())
        if not found:
            continue
        arm = found.group("arm")
        cells = [c.strip() for c in found.group("rest").split("|")]
        for template, cell in zip(DECISION_KEYS, cells):
            number = CELL_NUMBER.search(cell.replace(",", "").replace("*", ""))
            if number is None:
                continue
            key = template.format(arm=arm)
            want = counts.get(key)
            if want is None:
                continue
            if int(number.group(0)) != want:
                problems.append(
                    f"lang/README.md: the decision table publishes "
                    f"{number.group(0)} for {key}, but lang/token-counts.json "
                    f"records {want}. Two tables in this file were publishing "
                    "different numbers for the same measurement.")
                continue
            rows_seen.add(("decision", arm))
            checked += 1

    # THE CARD LINE, which is prose rather than a table. The docstring named it
    # as covered and `token_problems` parses table rows only, so all three of
    # its numbers were free.
    # Tolerant of "and" and of bold, so a reworded second copy is still seen
    # as a second copy rather than slipping past as prose.
    card_lines = list(re.finditer(
        r"Language cards:\s*\**candidate_a\**\s+(\d+),\s*\**candidate_b\**\s+(\d+),"
        r"\s*(?:and\s+)?\**starlark\**\s+(\d+)", text))
    if len(card_lines) > 1:
        problems.append(
            f"lang/README.md: publishes the language-card line {len(card_lines)} "
            "times. Every locator here reads the FIRST match, so a second copy "
            "is outside this gate -- which is how a corrected block inserted "
            "above a stale one left the stale numbers shipping and unread.")
    card_line = card_lines[0] if card_lines else None
    if card_line:
        for arm, published in zip(("candidate_a", "candidate_b", "starlark"),
                                  card_line.groups()):
            want = counts.get(f"card|{arm}")
            if want is None:
                problems.append(
                    f"lang/token-counts.json records no card count for {arm}, "
                    "so the published one is compared to nothing.")
                continue
            if int(published) != want:
                problems.append(
                    f"lang/README.md: the language-card line publishes "
                    f"{published} for {arm}, but lang/token-counts.json records "
                    f"{want}.")
                continue
            rows_seen.add(("card", arm))
            checked += 1
    else:
        problems.append(
            "lang/README.md: the language-card line is gone or reshaped, so its "
            "three counts are checked by nothing.")

    # THE T9 TABLE, held to the same artifact. Percentages, so compared at the
    # one decimal the README prints.
    t9_seen = set()
    t9_order = ["T9-1", "T9-2", "T9-3"]
    in_t9 = False
    t9_headers = [l for l in all_lines if _norm(l).startswith("|design|arm|t9-1")]
    if len(t9_headers) > 1:
        problems.append(
            f"lang/README.md: publishes the T9 table {len(t9_headers)} times; "
            "only the first is read, so the others are gated by nothing.")
    for line in all_lines:
        if _norm(line).startswith("|design|arm|t9-1"):
            in_t9 = True
            # BY NAME. The rules were zipped to cells 2-4 positionally, so
            # swapping the T9-2 and T9-3 header labels re-attributed every
            # value and left the gate green -- publishing T9-2 = 3.4% against
            # the document's own conclusion that T9-2 spans 4.2-7.7%.
            header_cells = [c.strip() for c in line.strip().strip("|").split("|")]
            t9_order = []
            for cell in header_cells[2:5]:
                found_rule = re.match(r"(T9-\d)", cell)
                t9_order.append(found_rule.group(1) if found_rule else None)
            if t9_order != ["T9-1", "T9-2", "T9-3"]:
                problems.append(
                    f"lang/README.md: the T9 table's rule columns are "
                    f"{t9_order}, not T9-1/T9-2/T9-3 in order. Values are read "
                    "by position, so a reordered header silently re-attributes "
                    "every number.")
            continue
        if in_t9:
            if not line.strip().startswith("|"):
                break
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 6 or cells[0] in ("---", ""):
                continue
            design, arm = cells[0], cells[1]
            want_all = counts.get(f"t9all|{design}|{arm}")
            if want_all is not None and len(cells) > 5:
                found_all = re.search(r"[\d.]+", cells[5])
                if found_all and abs(float(found_all.group(0)) - want_all / 10.0) > 0.05:
                    problems.append(
                        f"lang/README.md: the T9 table publishes {cells[5]} in "
                        f"the `all` column for {design}/{arm}, but the harness "
                        f"measures {want_all / 10.0:.1f}%. The headline range is "
                        "quoted from this column.")
                elif found_all:
                    t9_seen.add((design, arm, "all"))
                    checked += 1
            for rule, cell in zip(t9_order, cells[2:5]):
                if rule is None:
                    continue
                want = counts.get(f"t9|{design}|{arm}|{rule}")
                if want is None:
                    continue
                found = re.search(r"[\d.]+", cell)
                if found is None:
                    continue
                if abs(float(found.group(0)) - want / 10.0) > 0.05:
                    problems.append(
                        f"lang/README.md: the T9 table publishes {cell} for "
                        f"{design}/{arm}/{rule}, but the harness measures "
                        f"{want / 10.0:.1f}%. This is the table the same "
                        "document calls the reading that answers T9.")
                    continue
                rows_seen.add(("t9", design, arm))
                t9_seen.add((design, arm, rule))
                checked += 1
    if minimum is None and len(t9_seen) < MINIMUM_T9_CELLS:
        problems.append(
            f"lang/README.md: reconciled {len(t9_seen)} distinct T9 cell(s), below "
            f"the floor "
            f"of {MINIMUM_T9_CELLS}. This table was a stated exclusion and went "
            "stale through two corrections while nothing looked at it.")

    # THE L6 SWEEP TABLE, located by its own header. An auditor changed a row
    # from 65/45 to 6500/4500 with zero problems reported: this table was
    # deliberately excluded from the token-table locator (its columns are
    # thresholds) and then checked by nothing at all.
    sweep_seen = set()
    in_sweep = False
    thresholds = []
    for line in all_lines:
        if line.startswith("| Design | Arm |") and ("≥2" in line or ">=2" in line):
            in_sweep = True
            header_cells = [c.strip() for c in line.strip().strip("|").split("|")]
            thresholds = [re.sub(r"[^\d]", "", c) for c in header_cells[2:]]
            continue
        if in_sweep:
            if not line.strip().startswith("|"):
                break
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 3 or cells[0].startswith("---"):
                continue
            design, arm = cells[0], cells[1]
            for threshold, cell in zip(thresholds, cells[2:]):
                want = counts.get(f"l6|{design}|{arm}|{threshold}")
                if want is None:
                    continue
                found = re.search(r"-?\d+", cell.replace(",", ""))
                if found is None:
                    continue
                if int(found.group(0)) != want:
                    problems.append(
                        f"lang/README.md: the L6 sweep publishes {cell} for "
                        f"{design}/{arm} at threshold {threshold}, but the "
                        f"harness measures {want}.")
                    continue
                sweep_seen.add((design, arm, threshold))
                checked += 1
    if minimum is None and len(sweep_seen) < MINIMUM_SWEEP_CELLS:
        problems.append(
            f"lang/README.md: reconciled {len(sweep_seen)} distinct L6 sweep "
            f"cell(s), below the sweep floor of {MINIMUM_SWEEP_CELLS}.")

    # LINE COUNTS IN PROSE, in both documents that publish them. An auditor
    # rewrote "119 explicit / 82 inferred / 71 inferred+columnar" to
    # "999/888/777" with zero problems, and that sentence is AC1a's headline
    # evidence -- the one already found published against the LOSING arm once.
    prose = re.search(
        r"comes in at (\d+) explicit / (\d+) inferred / (\d+) inferred\+columnar "
        r"on (candidate_a|candidate_b|starlark)", text)
    if prose:
        arm = prose.group(4)
        for variant, published in zip(VARIANTS, prose.groups()[:3]):
            want = counts.get(f"lines|blinker-555|{arm}|{variant}")
            if want is None:
                continue
            if int(published) != want:
                problems.append(
                    f"lang/README.md: publishes {published} lines for "
                    f"blinker-555/{arm}/{variant}, but the renderer produces "
                    f"{want}. This sentence is AC1a's headline evidence and has "
                    "already been published against the wrong arm once.")
                continue
            rows_seen.add(("lines", arm, variant))
            checked += 1
    elif minimum is None:
        problems.append(
            "lang/README.md: the AC1a line-count sentence is gone or reshaped, "
            "so its three numbers are checked by nothing.")

    if minimum is None:
        by_kind = {}
        for row in rows_seen:
            by_kind[row[0]] = by_kind.get(row[0], 0) + 1
        for kind, want in sorted(MINIMUM_ROWS_BY_KIND.items()):
            found = by_kind.get(kind, 0)
            if found < want:
                problems.append(
                    f"lang/README.md: reconciled {found} {kind!r} row(s), below "
                    f"the row floor of {want} for that table. Every locator here "
                    "stops at the first non-table line, so a table detached by a "
                    "stray blank line vanishes silently -- and one combined "
                    "floor let the other tables pay for it.")
    elif len(rows_seen) < minimum:
        problems.append(
            f"lang/README.md: reconciled {len(rows_seen)} distinct row(s), "
            f"below the row floor of {minimum}.")
    return checked


def check(problems, minimum=None):
    if not README.is_file():
        problems.append("lang/README.md is missing")
        return 0
    return token_problems(
        README.read_text(encoding="utf-8"), load_counts(), problems, minimum)


def write_artifact():
    import json
    counts = measure_now()
    ARTIFACT.write_text(json.dumps({
        "_comment": ("Generated. Regenerate deliberately with: python3 "
                     "lang/tests/check_readme_numbers.py --write, on a machine "
                     "with the optional tiktoken pin installed and its cache "
                     "warm. lang/README.md is held to this file OFFLINE."),
        "inputs_fingerprint": inputs_fingerprint(),
        "counts": dict(sorted(counts.items())),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"readme-numbers: wrote {ARTIFACT.name} ({len(counts)} counts).")
    return 0


def verify_artifact():
    """Re-measure and compare to the artifact. Needs the tokenizer."""
    counts = load_counts()
    fresh = measure_now()
    problems = []
    for key, value in sorted(fresh.items()):
        if counts.get(key) != value:
            problems.append(
                f"{ARTIFACT.name}: records {counts.get(key)} for {key}, but "
                f"measuring now gives {value}.")
    for key in sorted(set(counts) - set(fresh)):
        problems.append(f"{ARTIFACT.name}: records {key}, which no arm renders.")
    if problems:
        print("readme-numbers: FAIL:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"readme-numbers: PASS: {len(fresh)} committed count(s) reproduce.")
    return 0


def _full_run():
    """(problems, reconciled) over the real README and artifact."""
    problems = []
    return problems, check(problems)


def self_test():
    HEADER = ("| Design | Arm | explicit | inferred | +columnar |\n"
              "|---|---|---:|---:|---:|\n")
    TABLE = (HEADER +
             "| blinker-555 | candidate_a | 10 | 20 | 30 |\n"
             "| blinker-555 | candidate_b | 40 | **50** | 60 |\n"
             "| blinker-555 | starlark | 70 | 80 | — |\n"
             "| esp32s3-devboard | candidate_a | 11 | 21 | 31 |\n"
             "| esp32s3-devboard | candidate_b | 41 | 51 | 61 |\n"
             "\n"
             "| | (a) blinker | (c) esp32 | (c) +columnar | card | defects |\n"
             "|---|---:|---:|---:|---:|---:|\n"
             "| candidate_a | 20 | 21 | 31 | 90 | 15/15 |\n"
             "\nLanguage cards: candidate_a 90, candidate_b 91, starlark 92 tokens\n"
             "\n| Design | Arm | T9-1 library pins | T9-2 inference | T9-3 L9 flags | all |\n"
             "|---|---|---:|---:|---:|---:|\n"
             "| blinker-555 | candidate_a | 1.5% | 2.5% | 3.5% | 7.5% |\n")
    FAKE = {
        "blinker-555|candidate_a|explicit": 10,
        "blinker-555|candidate_a|inferred": 20,
        "blinker-555|candidate_a|inferred+columnar": 30,
        "blinker-555|candidate_b|explicit": 40,
        "blinker-555|candidate_b|inferred": 50,
        "blinker-555|candidate_b|inferred+columnar": 60,
        "blinker-555|starlark|explicit": 70,
        "blinker-555|starlark|inferred": 80,
        "esp32s3-devboard|candidate_a|explicit": 11,
        "esp32s3-devboard|candidate_a|inferred": 21,
        "esp32s3-devboard|candidate_a|inferred+columnar": 31,
        "esp32s3-devboard|candidate_b|explicit": 41,
        "esp32s3-devboard|candidate_b|inferred": 51,
        "esp32s3-devboard|candidate_b|inferred+columnar": 61,
        "card|candidate_a": 90,
        "card|candidate_b": 91,
        "card|starlark": 92,
        "t9|blinker-555|candidate_a|T9-1": 15,
        "t9|blinker-555|candidate_a|T9-2": 25,
        "t9|blinker-555|candidate_a|T9-3": 35,
    }

    def probe(table, counts=FAKE):
        problems = []
        token_problems(table, counts, problems, minimum=0)
        return problems

    cases = [
        ("a table matching the artifact reports nothing", not probe(TABLE)),
        ("a stale token count is caught", any(
            "publishes" in p for p in probe(TABLE.replace("| 20 |", "| 906 |", 1)))),
        ("bold markup does not hide a stale value", any(
            "publishes" in p for p in probe(TABLE.replace("**50**", "**748**")))),
        # THE ROWS THE FIRST VERSION SKIPPED. starlark was outside ARMS, and the
        # decision table's first cell is the arm, which the design pattern
        # cannot match -- 8 of the 14 skipped cells were stale.
        ("a stale starlark row is caught", any(
            "starlark" in p for p in probe(TABLE.replace("| 70 | 80 |", "| 1144 | 822 |")))),
        ("a stale decision-table cell is caught", any(
            "decision table" in p for p in probe(
                TABLE.replace("| candidate_a | 20 | 21 |", "| candidate_a | 906 | 21 |")))),
        ("a stale language-card cell is caught", any(
            "card|candidate_a" in p for p in probe(
                TABLE.replace("| 31 | 90 | 15/15 |", "| 31 | 863 | 15/15 |")))),
        ("a missing decision-table header is caught", any(
            "header row is gone" in p for p in probe(
                TABLE.replace("| | (a) blinker | (c) esp32 | (c) +columnar | card | defects |\n", "")))),
        ("a missing token-table header is caught", any(
            "header row is gone" in p for p in probe(TABLE.replace(HEADER, "")))),
        ("a stale language-card number is caught", any(
            "language-card line publishes" in p for p in probe(
                TABLE.replace("candidate_a 90,", "candidate_a 863,")))),
        ("a missing language-card line is caught", any(
            "checked by nothing" in p for p in probe(
                TABLE[:TABLE.index("\nLanguage cards:")]))),
        # THREE LEGS THAT DELETED CLEANLY. The only wiring assertion was
        # `reconciled >= 30` against a real population of 77, so 47 cells of
        # slack absorbed the removal of the L6 sweep, the AC1a prose line
        # counts, or the T9 `all` column -- each of which the docstring names
        # as something this file exists to hold.
        ("main() reconciles every published count", (lambda: (
            lambda ps, n: not ps and n == MINIMUM_TOTAL_COUNTS)(
                *_full_run()))()),
        ("a stale T9 cell is caught", any(
            "the T9 table publishes" in p for p in probe(
                TABLE.replace("| 1.5% | 2.5%", "| 9.9% | 2.5%")))),
        ("a backticked row is still read", any(
            "publishes" in p for p in probe(
                TABLE.replace("| blinker-555 | candidate_a | 10 |",
                              "| `blinker-555` | `candidate_a` | 999 |")))),
        # The L6 sweep has the same row shape and different columns; reading it
        # as the token table compared a threshold saving to a token count.
        ("the L6 sweep table is not read as the token table", not probe(
            TABLE + "\n| blinker-555 | candidate_a | 112 | 82 | 0 | 0 | 0 |\n")),
        ("a row that grows a column is still read", any(
            "publishes" in p for p in probe(
                TABLE.replace("| blinker-555 | candidate_a | 10 | 20 | 30 |",
                              "| blinker-555 | candidate_a | 999 | 20 | 30 | note |")))),
        ("the distinct-row floor fires when rows stop parsing", any(
            "below the row floor" in p for p in _floor_probe(
                HEADER + "| blinker-555 | candidate_a | 10 | 20 | 30 |\n", FAKE))),
        ("a duplicated row cannot pay for a missing one", any(
            "below the row floor" in p for p in _floor_probe(
                HEADER + "| blinker-555 | candidate_a | 10 | 20 | 30 |\n" * 6, FAKE))),
    ]

    # WIRING over the real README and the committed artifact.
    try:
        real = []
        reconciled = check(real)
        cases.append(("the committed README reconciles against the artifact",
                      not real and reconciled >= 30))
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


def _floor_probe(table, counts):
    """The floor applies to the real table's population, so it is exercised
    with the shipped default rather than the probes' minimum=0."""
    problems = []
    token_problems(table, counts, problems)
    return problems


def main(argv):
    if argv and argv[0] == "--self-test":
        return self_test()
    try:
        if argv and argv[0] == "--write":
            return write_artifact()
        if argv and argv[0] == "--verify":
            return verify_artifact()
    except GateUnavailable as exc:
        print(f"readme-numbers: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
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
    print(f"readme-numbers: PASS: {checked} published token count(s) match "
          "lang/token-counts.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
