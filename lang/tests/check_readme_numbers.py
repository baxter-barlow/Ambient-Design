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
# The decision table's columns, in order. The two @-prefixed entries are the
# defect columns, whose cells are `16/16` and `94%` rather than bare counts;
# they were zipped against token keys, matched nothing, and so were the only
# two columns of this table outside the gate.
DECISION_KEYS = (
    "blinker-555|{arm}|inferred",
    "esp32s3-devboard|{arm}|inferred",
    "esp32s3-devboard|{arm}|inferred+columnar",
    "card|{arm}",
    "@detected",
    "@localised",
)
CELL_NUMBER = re.compile(r"-?\d+")
DETECTED_CELL = re.compile(r"(\d+)/(\d+)")
PERCENT_CELL = re.compile(r"(\d+)%")

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
    "lines": 7,  # 3 blinker AC1a + 4 esp32
    "defect-table": 3,       # one row per arm
    "cheaper": 2,            # the headline percentage, one per design
    "anchor": 1,             # the IR anchor sentence
}

# 6 rows x (3 rules + the `all` column), counted as DISTINCT (design, arm,
# rule) identities: six copies of one correct row met a cell count of 18 while
# five real rows left the document, which is the third recurrence of this exact
# defect here.
#
# The comment used to derive it as "6 rows x 3 rules", which is 18 against a
# constant of 24 -- the `all` column was added and the arithmetic behind the
# number was not. A maintainer trusting the comment and "correcting" 24 to 18
# would have un-pinned six cells, including the whole `all` column the README
# quotes its headline range from, with make all green.
MINIMUM_T9_CELLS = 24
# The exact population the shipped README publishes: 16 token + 11 decision
# token/card cells + 9 decision defect cells (three arms x detected numerator,
# denominator, localised %) + 12 defect-table cells (three arms x those three
# plus diagnostics/defect) + 3 card + 24 T9 + 20 L6 sweep + 3 AC1a line counts
# + 2 cheaper-than-A percentages + 4 IR anchor counts. A total, not a floor:
# any leg detaching drops it.
MINIMUM_TOTAL_COUNTS = 108  # 16 token + 11+9 decision + 12 defect + 3 card + 24 T9 + 20 L6 + 3 AC1a + 4 esp32 lines + 2 cheaper + 4 anchor
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
    # THE DEFECT OUTCOMES over the two reference designs. The decision table's
    # last two columns and the whole standalone defect table published these
    # nine cells and nothing read any of them: an auditor rewrote 16/16 into
    # arbitrary figures with make all green. Scored over DESIGNS only -- the
    # README's table excludes the coverage probe by its own stated rule, and
    # the probe's row is prose that the same paragraph covers. Stored as
    # integers like every other key: localisation as a whole percent,
    # diagnostics-per-defect in tenths.
    from bakeoff.arms import ARMS as scored_arms
    from bakeoff.defects import score
    for name in arms:
        rows = [row for design in DESIGNS
                for row in score(scored_arms[name], "inferred",
                                 load_model(ROOT / "lang" / "examples" /
                                            f"{design}.design.json"), design)]
        applicable = [row for row in rows if row["status"] != "not_applicable"]
        detected = [row for row in applicable if row["status"] == "detected"]
        localised = sum(1 for row in detected if row.get("localised"))
        diagnostics = sum(row.get("diagnostics", 0) for row in applicable)
        tokens[f"defects|{name}|detected"] = len(detected)
        tokens[f"defects|{name}|applicable"] = len(applicable)
        tokens[f"defects|{name}|localised_pct"] = round(
            100 * localised / len(detected)) if detected else 0
        tokens[f"defects|{name}|diag_tenths"] = round(
            10 * diagnostics / len(detected)) if detected else 0
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
    # AND THE DEFINITION OF THE MEASUREMENT ITSELF. `measure_now()` decides
    # what each key MEANS: the line-count rule behind the sixteen `lines|`
    # keys, the `round(value * 1000)` T9 scaling, the `t9all` tax formula, the
    # L6 sweep keys. The arms and the manifest were hashed and this was not, so
    # redefining a measured quantity -- counting non-blank lines instead of all
    # lines, which shifts every `lines|` key by one or two -- left the
    # fingerprint byte-identical, the artifact and the README agreeing with
    # each other and both stale, every gate green. That is the same "measured
    # once, published forever" failure the docstring above says this ends, one
    # function up from where it was last chased, and `--verify` runs in no
    # target and no CI job so nothing else could notice.
    #
    # The FUNCTION's source, not the whole file: editing a comment down here
    # would otherwise invalidate a measurement it cannot affect, and a gate
    # that cries wolf on every edit is a gate someone eventually widens.
    import inspect
    digest.update(inspect.getsource(measure_now).encode("utf-8"))
    digest.update(repr((DESIGNS, VARIANTS)).encode("utf-8"))
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


def _ir_counts():
    """(instances, nets, connections, assertions) of the committed blinker IR,
    or None if it cannot be read. Plain JSON: offline, no optional packages."""
    import json
    try:
        document = json.loads(
            (ROOT / "ir" / "examples" / "blinker.ir.json").read_text(
                encoding="utf-8"))
        return tuple(len(document[key]) for key in
                     ("instances", "nets", "connections", "assertions"))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def token_problems(text, counts, problems, minimum=None, ir=None):
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
            cell = cell.replace(",", "").replace("*", "")
            if template == "@detected":
                fraction = DETECTED_CELL.search(cell)
                want = (counts.get(f"defects|{arm}|detected"),
                        counts.get(f"defects|{arm}|applicable"))
                if None in want:
                    continue
                if fraction is None or tuple(
                        int(g) for g in fraction.groups()) != want:
                    problems.append(
                        f"lang/README.md: the decision table publishes "
                        f"{cell!r} defects for {arm}, but the artifact records "
                        f"{want[0]}/{want[1]}. This column was outside the "
                        "gate by construction and rewrote cleanly.")
                    continue
                rows_seen.add(("decision", arm))
                checked += 2
                continue
            if template == "@localised":
                percent = PERCENT_CELL.search(cell)
                want = counts.get(f"defects|{arm}|localised_pct")
                if want is None:
                    continue
                if percent is None or int(percent.group(1)) != want:
                    problems.append(
                        f"lang/README.md: the decision table publishes "
                        f"{cell!r} localised for {arm}, but the artifact "
                        f"records {want}%.")
                    continue
                rows_seen.add(("decision", arm))
                checked += 1
                continue
            number = CELL_NUMBER.search(cell)
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

    # THE ESP32 LINE-COUNT SENTENCE, the AC1a sentence's sibling one
    # paragraph up. Its four numbers matched the artifact and were read by
    # nothing (round 15) -- the same sentence shape, outside the locator.
    esp32_lines = re.search(
        r"Measured: (\d+) \(A, inferred\), (\d+) \(B,\s+inferred\), "
        r"(\d+)/(\d+) with columnar", text)
    if esp32_lines:
        for key, published in zip(
                ("lines|esp32s3-devboard|candidate_a|inferred",
                 "lines|esp32s3-devboard|candidate_b|inferred",
                 "lines|esp32s3-devboard|candidate_a|inferred+columnar",
                 "lines|esp32s3-devboard|candidate_b|inferred+columnar"),
                esp32_lines.groups()):
            want = counts.get(key)
            if want is None:
                continue
            if int(published) != want:
                problems.append(
                    f"lang/README.md: the esp32 line-count sentence publishes "
                    f"{published} for {key}, but the artifact records {want}.")
                continue
            rows_seen.add(("lines", "esp32", key.rsplit("|", 2)[-2],
                           key.rsplit("|", 1)[-1]))
            checked += 1
    elif minimum is None:
        problems.append(
            "lang/README.md: the esp32 line-count sentence is gone or "
            "reshaped, so its four numbers are checked by nothing.")

    # THE STANDALONE DEFECT TABLE, located by its own header and held to the
    # same defects| keys as the decision table's last two columns. Its nine
    # cells repeat the decision table's story with the diagnostics/defect
    # column added, and none of them were read by anything.
    defect_headers = [i for i, line in enumerate(all_lines)
                      if _norm(line).startswith("|arm|detected|")]
    if len(defect_headers) > 1:
        problems.append(
            f"lang/README.md: publishes the defect table {len(defect_headers)} "
            "times; only the first is read.")
    if not defect_headers and minimum is None:
        problems.append(
            "lang/README.md: the defect table's header row is gone, so its "
            "nine cells are checked by nothing.")
    for line in all_lines[defect_headers[0]:] if defect_headers else ():
        if not line.strip().startswith("|"):
            break
        found = DECISION_ROW.match(line.strip())
        if not found:
            continue
        arm = found.group("arm")
        cells = [c.strip().replace("*", "")
                 for c in found.group("rest").split("|")]
        want = tuple(counts.get(f"defects|{arm}|{field}") for field in
                     ("detected", "applicable", "localised_pct", "diag_tenths"))
        if None in want or len(cells) < 3:
            continue
        fraction = DETECTED_CELL.search(cells[0])
        percent = PERCENT_CELL.search(cells[1])
        diag = re.search(r"(\d+)\.(\d)", cells[2])
        published = (
            (int(fraction.group(1)), int(fraction.group(2))) if fraction else (None, None),
            int(percent.group(1)) if percent else None,
            int(diag.group(1)) * 10 + int(diag.group(2)) if diag else None,
        )
        if published != ((want[0], want[1]), want[2], want[3]):
            problems.append(
                f"lang/README.md: the defect table's {arm} row publishes "
                f"{cells[0]} detected, {cells[1]} localised, {cells[2]} "
                f"diagnostics/defect, but the artifact records "
                f"{want[0]}/{want[1]}, {want[2]}%, {want[3] / 10:.1f}.")
            continue
        rows_seen.add(("defect-table", arm))
        checked += 4

    # THE HEADLINE PERCENTAGES. "B is 18.0% cheaper than A on (a) and 20.8%
    # on (c)" is derived from four cells this gate already reconciles, and an
    # auditor rewrote it to 91.0%/99.8% with make all green. Recomputed from
    # the artifact at the one decimal the README prints.
    cheaper = re.search(
        r"B is (-?\d+\.\d)% cheaper than A on \(a\) and (-?\d+\.\d)% on \(c\)",
        text)
    if cheaper:
        for design, published in zip(DESIGNS, cheaper.groups()):
            a = counts.get(f"{design}|candidate_a|inferred")
            b = counts.get(f"{design}|candidate_b|inferred")
            if not a or b is None:
                continue
            want_tenths = round(1000 * (a - b) / a)
            if round(float(published) * 10) != want_tenths:
                problems.append(
                    f"lang/README.md: says B is {published}% cheaper than A "
                    f"on {design}, but the reconciled counts give "
                    f"{want_tenths / 10:.1f}%.")
                continue
            rows_seen.add(("cheaper", design))
            checked += 1
    elif minimum is None:
        problems.append(
            "lang/README.md: the cheaper-than-A sentence is gone or reshaped, "
            "so its two percentages are checked by nothing.")

    # THE IR ANCHOR SENTENCE. "13 instances, 7 nets, 27 connections, 2
    # assertions" describes ir/examples/blinker.ir.json, which is offline
    # JSON, so it is compared LIVE rather than through the artifact. An
    # auditor rewrote all four numbers to 99/1/3/0 with make all green.
    anchor = re.search(
        r"(\d+) instances, (\d+)\s+nets, (\d+) connections, (\d+) assertions",
        text)
    if anchor is None:
        if minimum is None:
            problems.append(
                "lang/README.md: the IR anchor sentence (instances/nets/"
                "connections/assertions) is gone or reshaped, so its four "
                "numbers are checked by nothing.")
    else:
        if ir is None:
            ir = _ir_counts()
        if ir is None:
            problems.append(
                "ir/examples/blinker.ir.json is missing or unreadable, so the "
                "README's IR anchor sentence is compared to nothing.")
        else:
            published = tuple(int(g) for g in anchor.groups())
            if published != ir:
                problems.append(
                    "lang/README.md: the IR anchor sentence publishes "
                    f"{published[0]} instances, {published[1]} nets, "
                    f"{published[2]} connections, {published[3]} assertions; "
                    f"ir/examples/blinker.ir.json holds "
                    f"{'/'.join(str(n) for n in ir)}.")
            else:
                rows_seen.add(("anchor", "blinker-555"))
                checked += 4

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
             "| | (a) blinker | (c) esp32 | (c) +columnar | card | defects | localised |\n"
             "|---|---:|---:|---:|---:|---:|---:|\n"
             "| candidate_a | 20 | 21 | 31 | 90 | 15/15 | 100% |\n"
             "\nLanguage cards: candidate_a 90, candidate_b 91, starlark 92 tokens\n"
             "\n| Design | Arm | T9-1 library pins | T9-2 inference | T9-3 L9 flags | all |\n"
             "|---|---|---:|---:|---:|---:|\n"
             "| blinker-555 | candidate_a | 1.5% | 2.5% | 3.5% | 7.5% |\n"
             "\n| Arm | detected | localised | diagnostics/defect |\n"
             "|---|---|---|---|\n"
             "| candidate_a | 15/15 | 100% | 1.0 |\n"
             # The FAKE counts put candidate_b ABOVE candidate_a, so the
             # fixture's true percentages are negative; the regex accepts the
             # sign so this fixture can exercise the arithmetic at all.
             "\nMeasured: 91 (A, inferred), 92 (B, inferred), 93/94 with columnar.\n"
             "\nB is -150.0% cheaper than A on (a) and -142.9% on (c).\n"
             "\nreproduces 5 instances, 6 nets, 7 connections, 8 assertions.\n")
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
        "lines|esp32s3-devboard|candidate_a|inferred": 91,
        "lines|esp32s3-devboard|candidate_b|inferred": 92,
        "lines|esp32s3-devboard|candidate_a|inferred+columnar": 93,
        "lines|esp32s3-devboard|candidate_b|inferred+columnar": 94,
        "defects|candidate_a|detected": 15,
        "defects|candidate_a|applicable": 15,
        "defects|candidate_a|localised_pct": 100,
        "defects|candidate_a|diag_tenths": 10,
    }

    def probe(table, counts=FAKE, ir=(5, 6, 7, 8)):
        problems = []
        token_problems(table, counts, problems, minimum=0, ir=ir)
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
                TABLE.replace("| | (a) blinker | (c) esp32 | (c) +columnar | card | defects | localised |\n", "")))),
        # THE DEFECT COLUMNS, decision table and standalone table both. All
        # eleven of these README cells were outside the gate; an auditor
        # rewrote 16/16 and 94% arbitrarily with make all green.
        ("a stale decision-table defect fraction is caught", any(
            "defects for candidate_a" in p for p in probe(
                TABLE.replace("| 90 | 15/15 | 100% |", "| 90 | 14/15 | 100% |")))),
        ("a stale decision-table localised percent is caught", any(
            "localised for candidate_a" in p for p in probe(
                TABLE.replace("| 15/15 | 100% |", "| 15/15 | 90% |")))),
        ("a stale defect-table row is caught", any(
            "defect table's candidate_a row" in p for p in probe(
                TABLE.replace("| candidate_a | 15/15 | 100% | 1.0 |",
                              "| candidate_a | 15/15 | 100% | 9.9 |")))),
        ("a missing defect-table header is caught", any(
            "defect table's header row is gone" in p for p in _floor_probe(
                TABLE.replace("| Arm | detected | localised | diagnostics/defect |\n", ""),
                FAKE))),
        ("a second defect table is reported, not silently unread", any(
            "publishes the defect table 2 times" in p for p in probe(
                TABLE + "\n| Arm | detected | localised | diagnostics/defect |\n"
                        "|---|---|---|---|\n"
                        "| candidate_a | 12/15 | 80% | 3.0 |\n"))),
        ("a stale esp32 line count is caught", any(
            "esp32 line-count sentence publishes" in p for p in probe(
                TABLE.replace("Measured: 91 (A", "Measured: 990 (A")))),
        ("a missing esp32 line-count sentence is caught", any(
            "esp32 line-count sentence is gone" in p for p in _floor_probe(
                TABLE.replace(
                    "Measured: 91 (A, inferred), 92 (B, inferred), 93/94 with columnar.",
                    ""), FAKE))),
        ("a stale cheaper-than-A percentage is caught", any(
            "cheaper than A on" in p for p in probe(
                TABLE.replace("-150.0", "91.0")))),
        ("a missing cheaper-than-A sentence is caught", any(
            "cheaper-than-A sentence is gone" in p for p in _floor_probe(
                TABLE.replace(
                    "B is -150.0% cheaper than A on (a) and -142.9% on (c).", ""),
                FAKE))),
        ("a stale IR anchor number is caught", any(
            "blinker.ir.json holds" in p for p in probe(
                TABLE.replace("5 instances", "99 instances")))),
        ("a missing IR anchor sentence is caught", any(
            "IR anchor sentence" in p and "gone" in p for p in _floor_probe(
                TABLE.replace(
                    "reproduces 5 instances, 6 nets, 7 connections, 8 assertions.",
                    ""), FAKE))),
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

    # The unreadable-IR leg: _ir_counts() returning None must be reported,
    # not skipped -- a missing anchor file silently unpinning four numbers is
    # the exact shape this file exists to end.
    _real_ir_counts = _ir_counts
    try:
        globals()["_ir_counts"] = lambda: None
        cases.append(("an unreadable blinker IR is reported, not skipped", any(
            "compared to nothing" in p for p in probe(TABLE, ir=None))))
    finally:
        globals()["_ir_counts"] = _real_ir_counts

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
