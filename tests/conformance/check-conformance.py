#!/usr/bin/env python3
"""Gate: the conformance suite holds the implementation to the spec.

Seven legs:

  1. PARSE ACCEPT: every spec/conformance/parse/accept case parses with
     zero diagnostics.
  2. PARSE REJECT: every reject case's diagnostic stream equals its
     committed .expected.ndjson BYTE FOR BYTE — codes, spans, params,
     fix-its, and canonical order all pinned — and every expected line
     validates against the wire schema, so the suite cannot commit an
     expectation the format forbids.
  3. LITERAL VECTORS: every normal-form vector row reproduces, and the
     three T3 properties (value-exact, idempotent, re-lexable) plus form
     preservation hold ON each row — a vector contradicting the
     properties cannot sit in the table quietly. Error rows pin the
     stable rejection reasons.
  4. DOC RECONCILIATION: every closed list the spec restates (keywords,
     the keywords syntax 0.2 added, reserved words, every closed
     vocabulary, the punctuation tokens, the pragma versions, the unit
     ladders, the diagnostic block table, the output cap, the formatter's
     statement ranks and instance-body order) equals the source of truth
     it restates, and 07's collation sample is in natural order. The spec
     promised "a list in this spec is either machine-reconciled or
     absent"; this is the reconciliation.
  5. FORMATTER: every spec/conformance/fmt input formats to its committed
     .expected.rhoform BYTE FOR BYTE, every expected file formats to
     itself (canonical output is a fixed point), and the formatter
     refuses every parse reject case, returning no bytes.
  6. ELABORATION CASES (spec/language/04-elaboration.md): every
     elaborate/accept case elaborates with zero diagnostics to IR equal to
     its .expected.ir.json BYTE FOR BYTE, and that IR validates against
     ir/netlist-ir.schema.json; every elaborate/reject case parses clean
     and its elaboration diagnostic stream equals its .expected.ndjson
     byte for byte, each line valid on the wire schema. Every block-2 code
     a source can trigger must be emitted by some reject case (of this leg
     or the next), and the closed lists 04 restates are reconciled against
     the elaborator.
  7. PACKAGE CASES (spec/language/08-packages.md): each case is a
     directory, compiled with itself as the compile root from its one
     `main.rhoform` through the package layer (manifests, imports, the
     import closure). packages/accept cases elaborate with zero
     diagnostics to IR equal to their expected.ir.json byte for byte, valid
     against the IR schema; packages/reject cases' streams equal their
     expected.ndjson byte for byte, each line valid on the wire schema.

Population floors on cases and vectors keep the suite from shrinking by
accident, the same posture as the schema gate's negative-control floor.

Exit 0 pass, 1 violation, 2 when the pinned lark or jsonschema is
missing (an unavailable gate is not a pass). `--write` regenerates the
reject and formatter cases' expected files, and the elaboration and
package cases' expected IR and streams, from the reference
implementation; the git diff is the review artifact.

Usage: check-conformance.py [--self-test | --write]
"""

import itertools
import json
import re
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

CONFORMANCE = ROOT / "spec" / "conformance"
SPEC_LANG = ROOT / "spec" / "language"
SCHEMA_PATH = ROOT / "rhoform" / "diagnostic.schema.json"

# Today's populations. Cases may be added freely; a DROP below the floor
# is the suite shrinking out from under the spec, and must be a decision
# recorded here. Syntax 0.2 added a09-a16 and r17-r23, and its canonical
# form f17-f24; bodyless component definitions added a17 and f25.
MINIMUM_ACCEPT_CASES = 17
MINIMUM_REJECT_CASES = 23
MINIMUM_VECTORS = 30
MINIMUM_ERROR_VECTORS = 11
MINIMUM_FMT_CASES = 25

# Elaboration cases (leg 5). The reject floor is one case per block-2 code
# a source can trigger; the coverage check below is what keeps that true
# as codes are added, the floor is what keeps cases from vanishing. Syntax
# 0.2's semantics added a09-a14 and r35-r48; a08 came with AMB-132.
ELABORATE = CONFORMANCE / "elaborate"
IR_SCHEMA_PATH = ROOT / "ir" / "netlist-ir.schema.json"
# r33 went with RHO2033, the interim refusal of imports, when the package
# layer gave imports their semantics: 46 -> 45. The standard library added
# a15-a16 and r49-r51.
MINIMUM_ELABORATE_ACCEPT_CASES = 16
MINIMUM_ELABORATE_REJECT_CASES = 48

# Package cases (leg 7): one directory per case, added with R14b; a05
# came with the standard library.
PACKAGES = CONFORMANCE / "packages"
MINIMUM_PACKAGE_ACCEPT_CASES = 5
MINIMUM_PACKAGE_REJECT_CASES = 20
PACKAGE_ENTRY = "main.rhoform"

# Block-2 codes no source text can trigger, each with its reason. Every
# other active block-2 code must be emitted by at least one reject case,
# so an elaboration code cannot land without the case the spec README
# requires in the same change.
NOT_SOURCE_TRIGGERED = {
    "RHO2003": "it fires only for a root module requested by name, which "
               "the caller supplies and no source text can spell",
}

_WORD = re.compile(r"`([A-Za-z_][A-Za-z0-9_./-]*)`")
# A backticked run of punctuation, for the token list 01 restates.
_PUNCTUATION = re.compile(r"`([^`\sA-Za-z0-9_]+)`")


def _section(text: str, heading: str) -> str | None:
    """The text under `heading`, up to the next heading of its level or
    above; None when the heading is absent."""
    lines = text.split("\n")
    start = None
    level = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index + 1
            level = line.split(" ")[0]
            break
    if start is None:
        return None
    body = []
    for line in lines[start:]:
        if line.startswith("#") and line.split(" ")[0] <= level:
            break
        body.append(line)
    return "\n".join(body)


def _spec_words(text: str, heading: str, pattern=_WORD) -> list[str]:
    """Backticked words under `heading`, up to the next heading."""
    return pattern.findall(_section(text, heading) or "")


def _rank_rows(text: str, heading: str) -> list[tuple[int, str]]:
    """`| <rank> | `<word>` | ...` table rows under `heading`."""
    return [(int(rank), word) for rank, word in re.findall(
        r"^\| (\d+) \| `([a-z_]+)` \|", _section(text, heading) or "",
        re.MULTILINE)]


def _read_case(case: Path) -> str:
    """A case's source text. surrogateescape, exactly like the parser
    CLI: a case with an invalid byte is a legitimate reject fixture, and a
    strict read here made that class of case structurally unpinnable
    (review round 2). But the repository REFUSES tracked bytes that are
    not valid UTF-8 (the retired-names scanner fails closed on binary, by
    policy — round 3 caught a committed 0xFF turning `make all` red), so
    such fixtures — and formatter inputs that need bytes the whitespace
    policy refuses — are committed as `.rhoform.escaped`: ASCII with
    Python-style byte escapes, decoded here to the raw bytes a
    third-party implementation should feed its reader."""
    if case.name.endswith(".escaped"):
        escaped = case.read_text(encoding="ascii")
        raw = (escaped.encode("ascii").decode("unicode_escape")
               .encode("latin-1"))
        return raw.decode("utf-8", errors="surrogateescape")
    return case.read_bytes().decode("utf-8", errors="surrogateescape")


def _case_stem(case: Path) -> str:
    name = case.name
    if name.endswith(".rhoform.escaped"):
        return name[:-len(".rhoform.escaped")]
    return name[:-len(".rhoform")]


def _case_sources(directory: Path) -> list[Path]:
    """Every case source in `directory`, escaped or not, sorted."""
    return sorted(list(directory.glob("*.rhoform"))
                  + list(directory.glob("*.rhoform.escaped")))


def _grammar_punctuation(sot) -> set[str]:
    """Every punctuation token the grammar can lex, read off the source of
    truth rather than listed here: the non-word literals its rules spell,
    plus every short run of punctuation a named terminal matches whole.
    The second half is what catches an operator terminal (COMPARE,
    INDEX_OP) — and any future one — without this gate naming it; no
    other terminal matches a run with no letter, digit, underscore, quote
    or `#`."""
    found = set()

    def walk(node):
        if isinstance(node, sot.Lit) and not node.text.isidentifier():
            found.add(node.text)
        for child in (getattr(node, "items", ()) or getattr(node, "options", ())
                      or ()):
            walk(child)
        inner = getattr(node, "item", None)
        if inner is not None:
            walk(inner)

    for _, _, node in sot.RULES:
        walk(node)
    marks = [mark for mark in string.punctuation if mark not in '"#_']
    runs = ["".join(run) for length in (1, 2, 3)
            for run in itertools.product(marks, repeat=length)]
    for pattern in sot.TERMINALS.values():
        terminal = re.compile(pattern)
        found.update(run for run in runs if terminal.fullmatch(run))
    return found


def _load_sot():
    """The grammar source of truth, imported by path (never copied)."""
    import importlib.util

    sot_path = ROOT / "lang" / "grammar" / "rhoform_syntax.py"
    spec = importlib.util.spec_from_file_location("_sot_doc", sot_path)
    sot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sot)
    return sot


def parse_case_problems(accept_dir, reject_dir, write=False):
    """Legs 1 and 2. Returns (problems, accept_count, reject_count)."""
    from rhoform.parser import parse

    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.validators.validator_for(schema)(schema)

    problems = []
    accept_cases = sorted(accept_dir.glob("*.rhoform"))
    for case in accept_cases:
        result = parse(_read_case(case), file=case.name)
        if not result.ok:
            emitted = result.diagnostics.render().splitlines()
            codes = [json.loads(line)["code"] for line in emitted]
            problems.append(
                f"accept/{case.name}: expected a clean parse, got "
                f"{codes or 'no tree'}"
            )

    reject_cases = _case_sources(reject_dir)
    expected_files = set(reject_dir.glob("*.expected.ndjson"))
    for case in reject_cases:
        stem = _case_stem(case)
        expected_path = case.with_name(stem + ".expected.ndjson")
        expected_files.discard(expected_path)
        # The logical case name, escaped or not: the wire `file` field
        # must not leak the encoding an implementation happens to store
        # the fixture in.
        result = parse(_read_case(case), file=stem + ".rhoform")
        stream = result.diagnostics.render()
        if not stream:
            problems.append(
                f"reject/{case.name}: produced no diagnostics; a reject "
                "case that stopped rejecting is an accepted defect"
            )
            continue
        for number, line in enumerate(stream.splitlines(), 1):
            for error in validator.iter_errors(json.loads(line)):
                problems.append(
                    f"reject/{case.name}: line {number} violates the "
                    f"wire schema at /{'/'.join(map(str, error.absolute_path))}: "
                    f"{error.message}"
                )
        if write:
            expected_path.write_text(stream, encoding="utf-8")
            shown = (expected_path.relative_to(ROOT)
                     if expected_path.is_relative_to(ROOT) else expected_path)
            print(f"conformance: wrote {shown}")
            continue
        if not expected_path.is_file():
            problems.append(
                f"reject/{case.name}: no {expected_path.name}; run "
                "--write and review the diff"
            )
            continue
        expected = expected_path.read_text(encoding="utf-8")
        if expected != stream:
            got_codes = [json.loads(l)["code"] for l in stream.splitlines()]
            want_codes = [json.loads(l)["code"]
                          for l in expected.splitlines() if l.strip()]
            problems.append(
                f"reject/{case.name}: diagnostic stream diverges from "
                f"{expected_path.name} (emitted {got_codes}, expected "
                f"{want_codes}; if the change is deliberate, --write and "
                "review the byte diff)"
            )
    for orphan in sorted(expected_files):
        problems.append(
            f"reject/{orphan.name}: expected file with no .rhoform case; "
            "delete it or restore its case"
        )
    return problems, len(accept_cases), len(reject_cases)


def vector_problems(vector_path):
    """Leg 3. Returns (problems, vector_count, error_count)."""
    from rhoform.quantities import (
        QuantityError, normal_form, parse_quantity,
    )
    import importlib.util

    sot_path = ROOT / "lang" / "grammar" / "rhoform_syntax.py"
    spec = importlib.util.spec_from_file_location("_sot_conf", sot_path)
    sot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sot)
    lexer_quantity = re.compile(sot.LEXER_QUANTITY)

    problems = []
    table = json.loads(vector_path.read_text(encoding="utf-8"))
    for row in table["vectors"]:
        text, want = row["input"], row["canonical"]
        try:
            got = normal_form(text)
        except QuantityError as exc:
            problems.append(f"vector {text!r}: does not parse: {exc.reason}")
            continue
        if got != want:
            problems.append(
                f"vector {text!r}: normal form is {got!r}, table says "
                f"{want!r}"
            )
            continue
        if normal_form(got) != got:
            problems.append(f"vector {text!r}: normal form not idempotent")
        # Compare the DECIMALS the parse semantics expose, not key(), which
        # renders through `_plain()`: this leg is about the FIELDS a
        # downstream check consumes. Be exact about what it can see. Both
        # sides pass through the same parse_quantity(), so a rounding
        # applied to BOTH is invisible here by construction, and round 8
        # measured that the committed table (20 significant digits at
        # most) could not trip any precision floor this module has had.
        # This leg pins that normalization PRESERVES the parse semantics;
        # exactness against exact arithmetic is pinned by
        # rhoform/tests/test_quantities.py, and the deep vectors in the
        # table give the rendering leg a population past every old floor
        # (28, then 60) so a returning one is caught on real data.
        before, after = parse_quantity(text), parse_quantity(got)
        if ((before.nominal, before.lower, before.upper)
                != (after.nominal, after.lower, after.upper)):
            problems.append(
                f"vector {text!r}: normalization changed the VALUE — the "
                "one thing T3 forbids"
            )
        if parse_quantity(got).form != parse_quantity(text).form:
            problems.append(f"vector {text!r}: normalization changed form")
        match = lexer_quantity.match(want)
        if match is None or match.group(0) != want:
            problems.append(
                f"vector {text!r}: canonical {want!r} does not re-lex as "
                "one quantity token; the formatter would write a file the "
                "parser rejects"
            )
    for row in table["errors"]:
        text, fragment = row["input"], row["reason_fragment"]
        try:
            parse_quantity(text)
            problems.append(
                f"error vector {text!r}: parsed, but the table says it "
                "must be rejected"
            )
        except QuantityError as exc:
            if fragment not in exc.reason:
                problems.append(
                    f"error vector {text!r}: reason {exc.reason!r} does "
                    f"not carry the pinned fragment {fragment!r}"
                )
    return problems, len(table["vectors"]), len(table["errors"])


def _format_case(source: str, name: str):
    """("ok", canonical text), ("refused", [codes]) or ("broken", why).

    "broken" is the formatter failing its own self-check (F-11): it
    raises rather than return bytes, and an uncaught raise here would
    turn a formatter defect into a traceback instead of a report."""
    from rhoform.fmt import FormatterError, format_source

    try:
        result = format_source(source, file=name)
    except FormatterError as exc:
        return "broken", str(exc).splitlines()[0]
    if result.text is None:
        return "refused", [json.loads(line)["code"] for line
                           in result.diagnostics.render().splitlines()]
    return "ok", result.text


def fmt_case_problems(fmt_dir, reject_dir, write=False):
    """Leg 5. Returns (problems, case_count)."""
    from rhoform.fmt import first_difference

    problems = []
    inputs = [case for case in _case_sources(fmt_dir)
              if not case.name.endswith(".expected.rhoform")]
    expected_files = set(fmt_dir.glob("*.expected.rhoform"))
    for case in inputs:
        stem = _case_stem(case)
        expected_path = case.with_name(stem + ".expected.rhoform")
        expected_files.discard(expected_path)
        state, output = _format_case(_read_case(case), stem + ".rhoform")
        if state != "ok":
            problems.append(
                f"fmt/{case.name}: the input does not format ({state}: "
                f"{output}); a formatter case must be a clean source the "
                "formatter accepts"
            )
            continue
        if write:
            expected_path.write_text(output, encoding="utf-8")
            shown = (expected_path.relative_to(ROOT)
                     if expected_path.is_relative_to(ROOT) else expected_path)
            print(f"conformance: wrote {shown}")
            continue
        if not expected_path.is_file():
            problems.append(
                f"fmt/{case.name}: no {expected_path.name}; run --write "
                "and review the diff"
            )
            continue
        expected = _read_case(expected_path)
        if output != expected:
            problems.append(
                f"fmt/{case.name}: formats to bytes that diverge from "
                f"{expected_path.name} at character "
                f"{first_difference(output, expected)} (if the change is "
                "deliberate, --write and review the diff)"
            )
        state, again = _format_case(expected, stem + ".rhoform")
        if state != "ok" or again != expected:
            detail = (f"{state}: {again}" if state != "ok" else
                      f"formatting it changes character "
                      f"{first_difference(expected, again)}")
            problems.append(
                f"fmt/{expected_path.name}: not a fixed point ({detail}); "
                "canonical output must format to itself"
            )
    for orphan in sorted(expected_files):
        problems.append(
            f"fmt/{orphan.name}: expected file with no input case; delete "
            "it or restore its case"
        )
    # Refusal (F-11) is pinned on the reject corpus rather than on cases
    # of its own: a source that does not parse clean gets no bytes.
    for case in _case_sources(reject_dir):
        state, _ = _format_case(_read_case(case), _case_stem(case) + ".rhoform")
        if state != "refused":
            problems.append(
                f"reject/{case.name}: the formatter did not refuse it "
                f"({state}); a source that does not parse clean must get "
                "its diagnostics and no bytes"
            )
    return problems, len(inputs)


def doc_sync_problems(spec_dir=SPEC_LANG, sot=None, units=None,
                      blocks=None, cap=None, severities=None,
                      applicability=None):
    """Leg 4: every restated list equals its source of truth."""
    if sot is None:
        sot = _load_sot()
    if units is None:
        from rhoform.quantities import UNITS as units
    if blocks is None:
        from rhoform.codes import BLOCKS as blocks
    if cap is None:
        from rhoform.diagnostics import OUTPUT_CAP as cap
    if severities is None:
        from rhoform.codes import SEVERITIES as severities
    if applicability is None:
        from rhoform.diagnostics import APPLICABILITY as applicability

    problems = []
    lexical_md = (spec_dir / "01-lexical-structure.md").read_text(
        encoding="utf-8")
    grammar_md = (spec_dir / "02-grammar.md").read_text(encoding="utf-8")
    literals_md = (spec_dir / "03-literals.md").read_text(encoding="utf-8")
    diag_md = (spec_dir / "06-diagnostics.md").read_text(encoding="utf-8")

    def reconcile(name, spec_list, truth_list):
        if list(spec_list) != list(truth_list):
            missing = sorted(set(truth_list) - set(spec_list))
            extra = sorted(set(spec_list) - set(truth_list))
            detail = []
            if missing:
                detail.append(f"missing {missing}")
            if extra:
                detail.append(f"extra {extra}")
            if not detail:
                detail.append("order differs")
            problems.append(
                f"{name}: the spec's restatement disagrees with the "
                f"source of truth ({'; '.join(detail)})"
            )

    # The keyword heading lost its "(v0.1)" when syntax 0.2 added seven
    # words: the list is every keyword of the one grammar, whichever
    # version introduced it, and the 0.2 subset is reconciled on its own.
    reconcile("02-grammar.md keywords",
              _spec_words(grammar_md, "### Keywords"),
              sorted(sot.KEYWORDS))
    reconcile("02-grammar.md keywords added in 0.2",
              _spec_words(grammar_md, "### Keywords added in 0.2"),
              sorted(sot.PROMOTED_IN_0_2))
    reconcile("02-grammar.md reserved words",
              _spec_words(grammar_md, "### Reserved for v1"),
              sorted(sot.RESERVED_FUTURE))
    heading_of = {
        "pin_role": "### pin_role (T2)",
        "hardware_kind": "### hardware_kind (L9)",
        "net_attribute": "### net_attribute (T5)",
        "measurement_kind": "### measurement_kind (V2)",
        "param_type": "### param_type (L3)",
        "loop_iterator": "### loop_iterator (L3)",
    }
    for vocabulary, words in sorted(sot.CLOSED_VOCABULARIES.items()):
        # A vocabulary this table does not know yet is looked for under a
        # bare heading and, absent, reported as unrestated. Indexing the
        # table crashed the whole gate with a KeyError the day syntax 0.2
        # added two vocabularies — a traceback where a report belonged.
        heading = heading_of.get(vocabulary, f"### {vocabulary}")
        reconcile(f"02-grammar.md {vocabulary}",
                  _spec_words(grammar_md, heading),
                  sorted(words))
    reconcile("01-lexical-structure.md punctuation tokens",
              sorted(_spec_words(lexical_md, "### Punctuation tokens",
                                 _PUNCTUATION)),
              sorted(_grammar_punctuation(sot)))

    ladders = {}
    for symbol, (dimension, multiplier) in units.items():
        ladders.setdefault(dimension, []).append((multiplier, symbol))
    spec_rows = re.findall(
        r"^\| (\w[\w ]*?) \| ((?:`[^`]+` ?)+) \| `([^`]+)` \|$",
        literals_md, re.MULTILINE)
    spec_table = {row[0]: (tuple(_WORD.findall(row[1])), row[2])
                  for row in spec_rows}
    truth_table = {
        dimension: (
            tuple(symbol for _, symbol in sorted(ladder)),
            next(symbol for mult, symbol in ladder if mult == 1),
        )
        for dimension, ladder in ladders.items()
    }
    if spec_table != truth_table:
        for dimension in sorted(set(spec_table) | set(truth_table)):
            if spec_table.get(dimension) != truth_table.get(dimension):
                problems.append(
                    f"03-literals.md unit table, {dimension}: spec says "
                    f"{spec_table.get(dimension)}, implementation says "
                    f"{truth_table.get(dimension)}"
                )

    block_rows = re.findall(r"^\| RHO(\d)xxx \| ([a-z-]+) \|", diag_md,
                            re.MULTILINE)
    spec_blocks = {int(digit): category for digit, category in block_rows}
    truth_blocks = {digit: name for digit, (name, _) in blocks.items()}
    if spec_blocks != truth_blocks:
        problems.append(
            f"06-diagnostics.md block table {spec_blocks} != registry "
            f"BLOCKS {truth_blocks}"
        )

    cap_match = re.search(r"capped at \*\*(\d+) diagnostics\*\*", diag_md)
    if cap_match is None:
        problems.append(
            "06-diagnostics.md no longer states the output cap in the "
            "expected form ('capped at **N diagnostics**')"
        )
    elif int(cap_match.group(1)) != cap:
        problems.append(
            f"06-diagnostics.md states a {cap_match.group(1)}-diagnostic "
            f"cap; the framework's OUTPUT_CAP is {cap}"
        )

    # Vocabularies 06 restates as definition bullets ('- `word` — ...').
    # The first review round found the applicability and severity lists
    # restated but reconciled by nothing — exactly the drift channel the
    # spec's own "machine-reconciled or absent" rule forbids.
    def bullet_words(text, heading):
        lines = text.split("\n")
        try:
            start = lines.index(heading) + 1
        except ValueError:
            return None
        words = []
        for line in lines[start:]:
            if line.startswith("#"):
                break
            match = re.match(r"- `([a-z-]+)` —", line)
            if match:
                words.append(match.group(1))
        return words

    for heading, truth, name in (
        ("## Severity and tier", list(severities), "severity"),
        ("## Fix-its", list(applicability), "applicability"),
    ):
        stated = bullet_words(diag_md, heading)
        if stated is None:
            problems.append(
                f"06-diagnostics.md lost the '{heading}' section this "
                "reconciliation reads"
            )
        elif stated != truth:
            problems.append(
                f"06-diagnostics.md {name} bullets {stated} != the "
                f"framework's vocabulary {truth}"
            )

    # The facts 02 and 01 state in prose — two counts, the version set an
    # implementation implements, and which version is current — and the
    # pragmas 01 restates in its fence: all pinned, same review finding.
    # Compared as whitespace-normalized text, since prose wraps.
    for doc, text, pattern, want, where in (
        ("02-grammar.md", grammar_md,
         r"The (\d+) words the grammar spells as literals",
         str(len(sot.KEYWORDS)), "keyword count"),
        ("02-grammar.md", grammar_md,
         r"The (\d+) words? reserved and not yet used",
         str(len(sot.RESERVED_FUTURE)), "reserved-word count"),
        ("01-lexical-structure.md", lexical_md,
         r"implements the version set\s+\{([^}]*)\}",
         ", ".join(sot.SYNTAX_VERSIONS), "implemented version set"),
        ("01-lexical-structure.md", lexical_md,
         r"Syntax (\d+\.\d+) is the\s+current\s+version",
         sot.SYNTAX_VERSION, "current version"),
    ):
        match = re.search(pattern, text)
        if match is None:
            problems.append(
                f"{doc} no longer states the {where} in the expected form"
            )
        elif " ".join(match.group(1).split()) != want:
            problems.append(
                f"{doc} states {match.group(1)!r} for the {where}; the "
                f"grammar source of truth has {want!r}"
            )

    # One line per implemented version since syntax 0.2: the fence is the
    # set of headers a reader MUST accept, not only the current one.
    fence = re.search(r"```text\n((?:#pragma[^\n]*\n)+)```", lexical_md)
    if fence is None:
        problems.append(
            "01-lexical-structure.md no longer shows the pragma in its "
            "fenced block"
        )
    elif fence.group(1).splitlines() != list(sot.PRAGMA_TEXTS):
        problems.append(
            f"01-lexical-structure.md shows the pragma as "
            f"{fence.group(1).splitlines()!r}; the source of truth says "
            f"{list(sot.PRAGMA_TEXTS)!r}"
        )

    # 07 restates the formatter's two rank tables. Rows are compared as
    # sets of (rank, word): a deleted table reconciles as every row
    # missing, so it needs no report of its own.
    from rhoform import fmt

    formatting_md = (spec_dir / "07-formatting.md").read_text(
        encoding="utf-8")
    reconcile("07-formatting.md statement ranks",
              sorted(_rank_rows(formatting_md, "### Statement ranks (F-1)")),
              sorted((rank, production) for production, rank
                     in fmt.STATEMENT_RANKS.items()))
    reconcile("07-formatting.md instance body order",
              sorted(_rank_rows(formatting_md,
                                "### Instance body order (F-5)")),
              sorted((rank, word) for word, rank in fmt.BODY_RANKS.items()))
    # The collation is an algorithm, not a list, so 07 pins it with a
    # sample the implementation's own key must leave in place.
    sample = re.search(r"```text\n([^\n]*)\n```",
                       _section(formatting_md, "### Collation (F-2)") or "")
    sample_words = sample.group(1).split() if sample else []
    if len(sample_words) < 2:
        problems.append(
            "07-formatting.md no longer shows the collation sample (a "
            "```text fence under '### Collation (F-2)')"
        )
    else:
        reconcile("07-formatting.md collation sample", sample_words,
                  sorted(sample_words, key=fmt.natural_key))
    return problems


# ---- leg 5: elaboration cases (spec/language/04-elaboration.md) ----------
#
# Kept apart from the parse legs on purpose: each function below takes its
# directories and truths as arguments, so the self-test drives it over
# planted trees exactly as it drives the parse legs.

def _shown(path):
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def elaborate_case_problems(accept_dir, reject_dir, write=False):
    """Returns (problems, accept_count, reject_count, emitted_codes).

    Each case is compiled alone with its own directory as the compile
    root, so its one source file is `<case>.rhoform` and its definitions
    are `<case>.<Module>`. An elaboration case must PARSE clean: a case
    that stops at the parser is a parse case, and filing it here would
    let the parse layer satisfy a leg written to pin the elaborator.
    """
    import jsonschema

    from rhoform.elaborate import elaborate
    from rhoform.ir import emit
    from rhoform.parser import parse

    def validator(path):
        schema = json.loads(path.read_text(encoding="utf-8"))
        return jsonschema.validators.validator_for(schema)(schema)

    wire = validator(SCHEMA_PATH)
    ir_schema = validator(IR_SCHEMA_PATH)

    def run(case):
        text = case.read_bytes().decode("utf-8", errors="surrogateescape")
        result = parse(text, file=case.name)
        return result, (elaborate([result]) if result.ok else None)

    def stem(case):
        return case.name[:-len(".rhoform")]

    problems = []
    accept_cases = sorted(accept_dir.glob("*.rhoform"))
    expected_irs = set(accept_dir.glob("*.expected.ir.json"))
    for case in accept_cases:
        expected_path = case.with_name(stem(case) + ".expected.ir.json")
        expected_irs.discard(expected_path)
        result, elaboration = run(case)
        stream = (elaboration or result).diagnostics.render()
        if elaboration is None or elaboration.design is None or stream:
            codes = [json.loads(line)["code"] for line in stream.splitlines()]
            problems.append(
                f"elaborate/accept/{case.name}: expected a clean "
                f"elaboration, got {codes or 'no design'}"
            )
            continue
        ir_bytes = emit(elaboration.design)[0]
        # The emitted document is the one compared byte for byte below, so
        # whenever the case passes this is the EXPECTED IR being validated;
        # checking before the comparison also keeps --write from committing
        # IR the schema refuses.
        for error in ir_schema.iter_errors(json.loads(ir_bytes)):
            problems.append(
                f"elaborate/accept/{case.name}: the IR violates "
                f"ir/netlist-ir.schema.json at "
                f"/{'/'.join(map(str, error.absolute_path))}: {error.message}"
            )
        if write:
            expected_path.write_bytes(ir_bytes)
            print(f"conformance: wrote {_shown(expected_path)}")
            continue
        if not expected_path.is_file():
            problems.append(
                f"elaborate/accept/{case.name}: no {expected_path.name}; run "
                "--write and review the diff"
            )
            continue
        if expected_path.read_bytes() != ir_bytes:
            problems.append(
                f"elaborate/accept/{case.name}: the IR diverges from "
                f"{expected_path.name} (if the change is deliberate, --write "
                "and review the byte diff)"
            )
    for orphan in sorted(expected_irs):
        problems.append(
            f"elaborate/accept/{orphan.name}: expected IR with no .rhoform "
            "case; delete it or restore its case"
        )

    emitted_codes = set()
    reject_cases = sorted(reject_dir.glob("*.rhoform"))
    expected_streams = set(reject_dir.glob("*.expected.ndjson"))
    for case in reject_cases:
        expected_path = case.with_name(stem(case) + ".expected.ndjson")
        expected_streams.discard(expected_path)
        result, elaboration = run(case)
        if elaboration is None:
            codes = [json.loads(line)["code"]
                     for line in result.diagnostics.render().splitlines()]
            problems.append(
                f"elaborate/reject/{case.name}: does not parse clean "
                f"({codes or 'no tree'}); an elaboration case must reach the "
                "elaborator, or it is a parse case"
            )
            continue
        stream = elaboration.diagnostics.render()
        if not stream:
            problems.append(
                f"elaborate/reject/{case.name}: produced no diagnostics; a "
                "reject case that stopped rejecting is an accepted defect"
            )
            continue
        lines = [json.loads(line) for line in stream.splitlines()]
        emitted_codes.update(line["code"] for line in lines)
        for number, line in enumerate(lines, 1):
            for error in wire.iter_errors(line):
                problems.append(
                    f"elaborate/reject/{case.name}: line {number} violates "
                    "the wire schema at "
                    f"/{'/'.join(map(str, error.absolute_path))}: "
                    f"{error.message}"
                )
        if write:
            expected_path.write_text(stream, encoding="utf-8")
            print(f"conformance: wrote {_shown(expected_path)}")
            continue
        if not expected_path.is_file():
            problems.append(
                f"elaborate/reject/{case.name}: no {expected_path.name}; run "
                "--write and review the diff"
            )
            continue
        expected = expected_path.read_text(encoding="utf-8")
        if expected != stream:
            want = [json.loads(line)["code"]
                    for line in expected.splitlines() if line.strip()]
            problems.append(
                f"elaborate/reject/{case.name}: diagnostic stream diverges "
                f"from {expected_path.name} (emitted "
                f"{[line['code'] for line in lines]}, expected {want}; if the "
                "change is deliberate, --write and review the byte diff)"
            )
    for orphan in sorted(expected_streams):
        problems.append(
            f"elaborate/reject/{orphan.name}: expected file with no .rhoform "
            "case; delete it or restore its case"
        )
    return problems, len(accept_cases), len(reject_cases), emitted_codes


def elaborate_coverage_problems(emitted_codes, registry=None,
                                exempt=None):
    """Every active block-2 code is emitted by a reject case or exempt."""
    if registry is None:
        from rhoform.codes import REGISTRY as registry
    if exempt is None:
        exempt = NOT_SOURCE_TRIGGERED
    block = {entry.code for entry in registry
             if entry.code.startswith("RHO2") and not entry.reserved}
    problems = []
    for code in sorted(block - set(exempt) - set(emitted_codes)):
        problems.append(
            f"{code}: no elaborate/reject or packages/reject case emits it; "
            "every block-2 code a source can trigger needs one (or a reason "
            "in NOT_SOURCE_TRIGGERED)"
        )
    for code in sorted(set(exempt) - block):
        problems.append(
            f"NOT_SOURCE_TRIGGERED exempts {code}, which is not an active "
            "block-2 code; drop the stale exemption"
        )
    return problems


def _list_sentence_problems(spec_dir, doc, truths, owner):
    """Each closed list `doc` restates as one sentence 'LEAD `a`, `b` and
    `c`.' equals its constant in `owner`, sorted."""
    text = " ".join((spec_dir / doc).read_text(encoding="utf-8").split())
    problems = []
    for lead, truth in truths.items():
        match = re.search(re.escape(lead) + r"([^.]*)\.", text)
        if match is None:
            problems.append(
                f"{doc} no longer states '{lead} ...', the restatement "
                "this reconciliation reads"
            )
            continue
        stated = _WORD.findall(match.group(1))
        if stated != sorted(truth):
            problems.append(
                f"{doc}: '{lead}' lists {stated}; the {owner}'s list is "
                f"{sorted(truth)}"
            )
    return problems


def elaboration_doc_problems(spec_dir=SPEC_LANG, truths=None):
    """The closed lists 04 restates equal the elaborator's constants."""
    if truths is None:
        from rhoform import elaborate as elaborator

        truths = {
            "The fabrication flags are": elaborator.FLAGS,
            "The pinless hardware kinds are": elaborator.PINLESS_HARDWARE,
            "The single-pin hardware kinds are":
                elaborator.SINGLE_PIN_HARDWARE,
            "The static measurement kinds are":
                elaborator.STATIC_MEASUREMENTS,
        }
    return _list_sentence_problems(spec_dir, "04-elaboration.md", truths,
                                   "elaborator")


def package_doc_problems(spec_dir=SPEC_LANG, truths=None):
    """The closed lists 08 restates equal the package layer's constants."""
    if truths is None:
        from rhoform import package

        truths = {
            "The [package] keys are": package.PACKAGE_KEYS,
            "The required [package] keys are":
                package.REQUIRED_PACKAGE_KEYS,
            "The dependency keys are": package.DEPENDENCY_KEYS,
            "The reserved namespaces are": package.RESERVED_NAMESPACES,
        }
    return _list_sentence_problems(spec_dir, "08-packages.md", truths,
                                   "package layer")


def elaborate_leg_problems(write=False, package_codes=()):
    """Leg 5 as main() runs it: (problems, accept_count, reject_count).
    Block-2 coverage counts the package cases' codes too."""
    problems, accepts, rejects, codes = elaborate_case_problems(
        ELABORATE / "accept", ELABORATE / "reject", write=write)
    problems += elaborate_coverage_problems(set(codes) | set(package_codes))
    problems += elaboration_doc_problems()
    if accepts < MINIMUM_ELABORATE_ACCEPT_CASES:
        problems.append(
            f"{accepts} elaborate accept case(s), below the floor of "
            f"{MINIMUM_ELABORATE_ACCEPT_CASES}"
        )
    if rejects < MINIMUM_ELABORATE_REJECT_CASES:
        problems.append(
            f"{rejects} elaborate reject case(s), below the floor of "
            f"{MINIMUM_ELABORATE_REJECT_CASES}"
        )
    return problems, accepts, rejects


def elaborate_self_test_cases(tmp):
    """Leg 5's self-test cases, over planted trees under `tmp`.

    Every report site in leg 5 has a case here that fails when the site is
    blanked; the coverage meta-gate measures exactly that, with no
    survivors allowed for this gate.
    """
    import contextlib
    import io
    import shutil

    global SCHEMA_PATH, IR_SCHEMA_PATH

    cases = []
    accept = Path(tmp) / "elaborate" / "accept"
    reject = Path(tmp) / "elaborate" / "reject"
    accept.mkdir(parents=True)
    reject.mkdir(parents=True)
    pragma = "#pragma rhoform-syntax 0.1\n"

    def run(write=False):
        with contextlib.redirect_stdout(io.StringIO()):
            return elaborate_case_problems(accept, reject, write=write)

    def strict(name, code_const):
        path = Path(tmp) / name
        path.write_text(json.dumps({
            "type": "object",
            "properties": {code_const[0]: {"const": code_const[1]}},
        }))
        return path

    # -- accept
    (accept / "a01_ok.rhoform").write_text(
        pragma + "module M:\n    port p passive\n")
    problems, n_accept, _, _ = run()
    cases.append(("an elaborate accept case without expected IR is caught",
                  any("no a01_ok.expected.ir.json" in p for p in problems)
                  and n_accept == 1))
    problems, _, _, _ = run(write=True)
    expected_ir = accept / "a01_ok.expected.ir.json"
    cases.append(("--write creates an accept case's expected IR and passes",
                  problems == [] and expected_ir.is_file()))
    problems, _, _, _ = run()
    cases.append(("a written expected IR round-trips byte-exact",
                  problems == []))

    good = expected_ir.read_bytes()
    drifted = good.replace(b'"design_name":"M"', b'"design_name":"N"')
    expected_ir.write_bytes(drifted)
    problems, _, _, _ = run()
    cases.append(("a one-byte drift in expected IR is caught",
                  drifted != good
                  and any("the IR diverges" in p for p in problems)))
    expected_ir.write_bytes(good)

    (accept / "a02_orphan.expected.ir.json").write_bytes(good)
    problems, _, _, _ = run()
    cases.append(("an orphaned expected IR is caught",
                  any("expected IR with no .rhoform case" in p
                      for p in problems)))
    (accept / "a02_orphan.expected.ir.json").unlink()

    dirty = accept / "a03_dirty.rhoform"
    dirty.write_text(pragma + "module M:\n    x = new Missing\n")
    problems, _, _, _ = run()
    cases.append(("an accept case the elaborator rejects is caught",
                  any("expected a clean elaboration" in p and "RHO2005" in p
                      for p in problems)))
    dirty.write_text(pragma + "module M:\n    port p pasive\n")
    problems, _, _, _ = run()
    cases.append(("an accept case that does not parse is caught",
                  any("expected a clean elaboration" in p and "RHO1009" in p
                      for p in problems)))
    dirty.unlink()

    real_ir_schema = IR_SCHEMA_PATH
    IR_SCHEMA_PATH = strict("strict-ir.schema.json", ("header", "never"))
    try:
        problems, _, _, _ = run()
    finally:
        IR_SCHEMA_PATH = real_ir_schema
    cases.append(("IR violating ir/netlist-ir.schema.json is reported",
                  any("violates ir/netlist-ir.schema.json" in p
                      for p in problems)))

    # -- reject
    (reject / "r01_x.rhoform").write_text(
        pragma + "module M:\n    x = new lib.U:\n        part abstract\n")
    problems, _, n_reject, _ = run()
    cases.append(("an elaborate reject case without expected output is "
                  "caught", any("no r01_x.expected.ndjson" in p
                                for p in problems) and n_reject == 1))
    problems, _, _, codes = run(write=True)
    expected = reject / "r01_x.expected.ndjson"
    cases.append(("--write creates a reject case's expected stream",
                  problems == [] and expected.is_file()
                  and codes == {"RHO2014"}))
    problems, _, _, _ = run()
    cases.append(("a written expected stream round-trips byte-exact",
                  problems == []))

    stream = expected.read_text()
    obj = json.loads(stream)
    obj["spans"][0]["byte_start"] += 1
    expected.write_text(
        json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")
    problems, _, _, _ = run()
    cases.append(("a one-byte span drift in an elaboration stream is caught",
                  any("elaborate/reject/r01_x.rhoform: diagnostic stream "
                      "diverges" in p for p in problems)))
    expected.write_text(stream)

    (reject / "r02_orphan.expected.ndjson").write_text(stream)
    problems, _, _, _ = run()
    cases.append(("an orphaned expected elaboration stream is caught",
                  any("elaborate/reject/r02_orphan.expected.ndjson" in p
                      for p in problems)))
    (reject / "r02_orphan.expected.ndjson").unlink()

    (reject / "r03_clean.rhoform").write_text(
        pragma + "module M:\n    port p passive\n")
    problems, _, _, _ = run()
    cases.append(("an elaborate reject case that stopped rejecting is caught",
                  any("r03_clean.rhoform: produced no diagnostics" in p
                      for p in problems)))
    (reject / "r03_clean.rhoform").unlink()

    (reject / "r04_parse.rhoform").write_text(
        pragma + "module M:\n    port p pasive\n")
    problems, _, _, _ = run()
    cases.append(("an elaborate reject case that fails to parse is caught",
                  any("r04_parse.rhoform: does not parse clean" in p
                      and "RHO1009" in p for p in problems)))
    (reject / "r04_parse.rhoform").unlink()

    real_schema = SCHEMA_PATH
    SCHEMA_PATH = strict("strict-wire.schema.json", ("code", "RHONONE"))
    try:
        problems, _, _, _ = run()
    finally:
        SCHEMA_PATH = real_schema
    cases.append(("an elaboration stream violating the wire schema is "
                  "reported", any("elaborate/reject/r01_x.rhoform: line 1 "
                                  "violates the wire schema" in p
                                  for p in problems)))

    # -- coverage of the block-2 codes
    from rhoform.codes import REGISTRY

    block = {entry.code for entry in REGISTRY
             if entry.code.startswith("RHO2") and not entry.reserved}
    triggerable = block - set(NOT_SOURCE_TRIGGERED)
    cases.append(("full block-2 coverage passes",
                  elaborate_coverage_problems(triggerable) == []))
    problems = elaborate_coverage_problems(triggerable - {"RHO2001"})
    cases.append(("a block-2 code no reject case emits is caught",
                  any(p.startswith("RHO2001: no elaborate/reject or "
                                   "packages/reject case")
                      for p in problems)))
    problems = elaborate_coverage_problems(block, exempt={"RHO2999": "x"})
    cases.append(("a stale NOT_SOURCE_TRIGGERED entry is caught",
                  any("stale exemption" in p for p in problems)))

    # -- the lists 04 restates
    cases.append(("the real 04 restatements reconcile",
                  elaboration_doc_problems() == []))
    spec_copy = Path(tmp) / "language-04"
    shutil.copytree(SPEC_LANG, spec_copy)
    elaboration_md = spec_copy / "04-elaboration.md"
    text = elaboration_md.read_text()
    drifted = text.replace("`grounded_mounting_hole` and",
                           "`grounded_mounting_hole`, `fiducial` and")
    elaboration_md.write_text(drifted)
    problems = elaboration_doc_problems(spec_dir=spec_copy)
    cases.append(("a drifted hardware list in 04 is caught",
                  drifted != text
                  and any("single-pin hardware kinds are' lists" in p
                          for p in problems)))
    dropped = text.replace("The static measurement kinds are",
                           "The static kinds include")
    elaboration_md.write_text(dropped)
    problems = elaboration_doc_problems(spec_dir=spec_copy)
    cases.append(("a dropped list statement in 04 is caught",
                  dropped != text
                  and any("no longer states 'The static measurement kinds "
                          "are" in p for p in problems)))

    # -- both floors feed main()
    for floor_name in ("MINIMUM_ELABORATE_ACCEPT_CASES",
                       "MINIMUM_ELABORATE_REJECT_CASES"):
        real_floor = globals()[floor_name]
        globals()[floor_name] = 10_000
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                wired = main()
        finally:
            globals()[floor_name] = real_floor
        cases.append((f"the {floor_name} floor is WIRED into main()",
                      wired == 1 and "below the floor" in err.getvalue()))
    return cases


# ---- leg 7: package cases (spec/language/08-packages.md) ---------------

def package_case_problems(accept_dir, reject_dir, write=False):
    """Returns (problems, accept_count, reject_count, emitted_codes).

    A case is a directory and its own compile root. Its entry is its one
    `main.rhoform`, wherever it sits (a case with a path dependency keeps
    each package in a directory of its own); its expectation is
    `expected.ir.json` (accept) or `expected.ndjson` (reject) at the case
    root, and nothing else there may be an expectation of the other kind.
    """
    import jsonschema

    from rhoform import package
    from rhoform.diagnostics import Diagnostics
    from rhoform.elaborate import elaborate
    from rhoform.ir import emit

    def validator(path):
        schema = json.loads(path.read_text(encoding="utf-8"))
        return jsonschema.validators.validator_for(schema)(schema)

    wire = validator(SCHEMA_PATH)
    ir_schema = validator(IR_SCHEMA_PATH)
    problems = []

    def compile_case(case, where):
        """(stream, design) of a case, or None when it cannot be run."""
        entries = sorted(case.rglob(PACKAGE_ENTRY))
        if len(entries) != 1:
            problems.append(
                f"{where}: holds {len(entries)} {PACKAGE_ENTRY} files; a "
                "package case has exactly one entry")
            return None
        sink = Diagnostics()
        try:
            compilation = package.load(
                entries[0].relative_to(case).as_posix(), case, sink)
        except package.ReadFailure as exc:
            problems.append(f"{where}: could not be read: {exc}")
            return None
        design = None
        if compilation.ok:
            design = elaborate(compilation.results, sink=sink,
                               imports=compilation.imports).design
        return sink.render(), design

    def cases_in(directory, kind):
        found = sorted(directory.iterdir()) if directory.is_dir() else []
        for stray in (p for p in found if not p.is_dir()):
            problems.append(
                f"packages/{kind}/{stray.name}: not a case directory; each "
                "package case is a directory of its own")
        return [p for p in found if p.is_dir()]

    accept_cases = cases_in(accept_dir, "accept")
    for case in accept_cases:
        where = f"packages/accept/{case.name}"
        expected = case / "expected.ir.json"
        if (case / "expected.ndjson").exists():
            problems.append(
                f"{where}: holds expected.ndjson, a reject case's "
                "expectation; an accept case's is expected.ir.json")
        compiled = compile_case(case, where)
        if compiled is None:
            continue
        stream, design = compiled
        if design is None or stream:
            codes = [json.loads(line)["code"] for line in stream.splitlines()]
            problems.append(
                f"{where}: expected a clean compilation, got "
                f"{codes or 'no design'}")
            continue
        ir_bytes = emit(design)[0]
        for error in ir_schema.iter_errors(json.loads(ir_bytes)):
            problems.append(
                f"{where}: the IR violates ir/netlist-ir.schema.json at "
                f"/{'/'.join(map(str, error.absolute_path))}: "
                f"{error.message}")
        if write:
            expected.write_bytes(ir_bytes)
            print(f"conformance: wrote {_shown(expected)}")
            continue
        if not expected.is_file():
            problems.append(
                f"{where}: no expected.ir.json; run --write and review the "
                "diff")
            continue
        if expected.read_bytes() != ir_bytes:
            problems.append(
                f"{where}: the IR diverges from expected.ir.json (if the "
                "change is deliberate, --write and review the byte diff)")

    emitted_codes = set()
    reject_cases = cases_in(reject_dir, "reject")
    for case in reject_cases:
        where = f"packages/reject/{case.name}"
        expected = case / "expected.ndjson"
        if (case / "expected.ir.json").exists():
            problems.append(
                f"{where}: holds expected.ir.json, an accept case's "
                "expectation; a reject case's is expected.ndjson")
        compiled = compile_case(case, where)
        if compiled is None:
            continue
        stream, _design = compiled
        if not stream:
            problems.append(
                f"{where}: produced no diagnostics; a reject case that "
                "stopped rejecting is an accepted defect")
            continue
        lines = [json.loads(line) for line in stream.splitlines()]
        emitted_codes.update(line["code"] for line in lines)
        for number, line in enumerate(lines, 1):
            for error in wire.iter_errors(line):
                problems.append(
                    f"{where}: line {number} violates the wire schema at "
                    f"/{'/'.join(map(str, error.absolute_path))}: "
                    f"{error.message}")
        if write:
            expected.write_text(stream, encoding="utf-8")
            print(f"conformance: wrote {_shown(expected)}")
            continue
        if not expected.is_file():
            problems.append(
                f"{where}: no expected.ndjson; run --write and review the "
                "diff")
            continue
        if expected.read_text(encoding="utf-8") != stream:
            want = [json.loads(line)["code"] for line in
                    expected.read_text(encoding="utf-8").splitlines()
                    if line.strip()]
            problems.append(
                f"{where}: diagnostic stream diverges from expected.ndjson "
                f"(emitted {[line['code'] for line in lines]}, expected "
                f"{want}; if the change is deliberate, --write and review "
                "the byte diff)")
    return problems, len(accept_cases), len(reject_cases), emitted_codes


def package_leg_problems(write=False):
    """Leg 7 as main() runs it: (problems, accept_count, reject_count,
    emitted codes)."""
    problems, accepts, rejects, codes = package_case_problems(
        PACKAGES / "accept", PACKAGES / "reject", write=write)
    problems += package_doc_problems()
    if accepts < MINIMUM_PACKAGE_ACCEPT_CASES:
        problems.append(
            f"{accepts} package accept case(s), below the floor of "
            f"{MINIMUM_PACKAGE_ACCEPT_CASES}")
    if rejects < MINIMUM_PACKAGE_REJECT_CASES:
        problems.append(
            f"{rejects} package reject case(s), below the floor of "
            f"{MINIMUM_PACKAGE_REJECT_CASES}")
    return problems, accepts, rejects, codes


def package_self_test_cases(tmp):
    """Leg 7's self-test cases, over planted case directories under
    `tmp`. Every report site in package_case_problems has a case that
    fails when the site is blanked."""
    import contextlib
    import io
    import shutil
    from unittest import mock

    global SCHEMA_PATH, IR_SCHEMA_PATH

    cases = []
    accept = Path(tmp) / "packages" / "accept"
    reject = Path(tmp) / "packages" / "reject"
    accept.mkdir(parents=True)
    reject.mkdir(parents=True)
    pragma = "#pragma rhoform-syntax 0.2\n"
    led = pragma + "\ncomponent Led:\n    pin a passive\n    pin k passive\n"
    top = (pragma + 'import Led from "./leds"\n\nmodule Top:\n'
           "    d = new Led\n    d.a ~ d.k\n")

    def plant(case, files):
        for name, text in files.items():
            path = case / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def run(write=False):
        with contextlib.redirect_stdout(io.StringIO()):
            return package_case_problems(accept, reject, write=write)

    def strict(name, code_const):
        path = Path(tmp) / name
        path.write_text(json.dumps({
            "type": "object",
            "properties": {code_const[0]: {"const": code_const[1]}},
        }))
        return path

    # -- accept
    good = accept / "a01_import"
    plant(good, {"main.rhoform": top, "leds.rhoform": led})
    problems, n_accept, _, _ = run()
    cases.append(("a package accept case without expected IR is caught",
                  any("a01_import: no expected.ir.json" in p
                      for p in problems) and n_accept == 1))
    problems, _, _, _ = run(write=True)
    cases.append(("--write creates a package case's expected IR and passes",
                  problems == [] and (good / "expected.ir.json").is_file()))
    expected_ir = good / "expected.ir.json"
    ir_bytes = expected_ir.read_bytes()
    expected_ir.write_bytes(ir_bytes.replace(b'"Top"', b'"Tap"'))
    problems, _, _, _ = run()
    cases.append(("a drifted package expected IR is caught",
                  any("a01_import: the IR diverges" in p for p in problems)))
    expected_ir.write_bytes(ir_bytes)

    (good / "expected.ndjson").write_text("")
    problems, _, _, _ = run()
    cases.append(("a reject expectation in an accept case is caught",
                  any("a01_import: holds expected.ndjson" in p
                      for p in problems)))
    (good / "expected.ndjson").unlink()

    (accept / "notes.txt").write_text("x")
    problems, _, _, _ = run()
    cases.append(("a stray file among the package cases is caught",
                  any("packages/accept/notes.txt: not a case directory" in p
                      for p in problems)))
    (accept / "notes.txt").unlink()

    dirty = accept / "a02_dirty"
    plant(dirty, {"main.rhoform": top})
    problems, _, _, _ = run()
    cases.append(("a package accept case that does not compile is caught",
                  any("a02_dirty: expected a clean compilation" in p
                      and "RHO2060" in p for p in problems)))
    plant(dirty, {"sub/main.rhoform": top})
    problems, _, _, _ = run()
    cases.append(("a package case with two entries is caught",
                  any("a02_dirty: holds 2 main.rhoform files" in p
                      for p in problems)))
    shutil.rmtree(dirty)

    real_ir_schema = IR_SCHEMA_PATH
    IR_SCHEMA_PATH = strict("strict-package-ir.schema.json",
                            ("header", "never"))
    try:
        problems, _, _, _ = run()
    finally:
        IR_SCHEMA_PATH = real_ir_schema
    cases.append(("package IR violating the IR schema is reported",
                  any("a01_import: the IR violates" in p for p in problems)))

    from rhoform import package

    def unreadable(self, key):
        raise package.ReadFailure(self.root / key, OSError("planted"))

    with mock.patch.object(package._Loader, "read", unreadable):
        problems, _, _, _ = run()
    cases.append(("an unreadable package case is reported, not a crash",
                  any("a01_import: could not be read" in p
                      for p in problems)))

    # -- reject
    bad = reject / "r01_missing"
    plant(bad, {"main.rhoform": top})
    problems, _, n_reject, _ = run()
    cases.append(("a package reject case without expected output is caught",
                  any("r01_missing: no expected.ndjson" in p
                      for p in problems) and n_reject == 1))
    problems, _, _, codes = run(write=True)
    expected = bad / "expected.ndjson"
    cases.append(("--write creates a package case's expected stream",
                  problems == [] and expected.is_file()
                  and codes == {"RHO2060"}))
    stream = expected.read_text()
    obj = json.loads(stream)
    obj["spans"][0]["byte_start"] += 1
    expected.write_text(
        json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")
    problems, _, _, _ = run()
    cases.append(("a one-byte span drift in a package stream is caught",
                  any("r01_missing: diagnostic stream diverges" in p
                      for p in problems)))
    expected.write_text(stream)

    (bad / "expected.ir.json").write_text("{}")
    problems, _, _, _ = run()
    cases.append(("an accept expectation in a reject case is caught",
                  any("r01_missing: holds expected.ir.json" in p
                      for p in problems)))
    (bad / "expected.ir.json").unlink()

    clean = reject / "r02_clean"
    plant(clean, {"main.rhoform": top, "leds.rhoform": led})
    problems, _, _, _ = run()
    cases.append(("a package reject case that stopped rejecting is caught",
                  any("r02_clean: produced no diagnostics" in p
                      for p in problems)))
    shutil.rmtree(clean)

    real_schema = SCHEMA_PATH
    SCHEMA_PATH = strict("strict-package-wire.schema.json",
                         ("code", "RHONONE"))
    try:
        problems, _, _, _ = run()
    finally:
        SCHEMA_PATH = real_schema
    cases.append(("a package stream violating the wire schema is reported",
                  any("r01_missing: line 1 violates the wire schema" in p
                      for p in problems)))

    # -- both floors feed main()
    for floor_name in ("MINIMUM_PACKAGE_ACCEPT_CASES",
                       "MINIMUM_PACKAGE_REJECT_CASES"):
        real_floor = globals()[floor_name]
        globals()[floor_name] = 10_000
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                wired = main()
        finally:
            globals()[floor_name] = real_floor
        cases.append((f"the {floor_name} floor is WIRED into main()",
                      wired == 1 and "below the floor" in err.getvalue()))

    # -- the lists 08 restates
    cases.append(("the real 08 restatements reconcile",
                  package_doc_problems() == []))
    spec_copy = Path(tmp) / "language-08"
    shutil.copytree(SPEC_LANG, spec_copy)
    packages_md = spec_copy / "08-packages.md"
    text = packages_md.read_text()
    drifted = text.replace("`rev` and `version`", "`rev`, `vendor` and "
                           "`version`")
    packages_md.write_text(drifted)
    problems = package_doc_problems(spec_dir=spec_copy)
    cases.append(("a drifted dependency-key list in 08 is caught",
                  drifted != text
                  and any("08-packages.md: 'The dependency keys are' lists"
                          in p for p in problems)))
    dropped = text.replace("The reserved namespaces are",
                           "Reserved namespaces include")
    packages_md.write_text(dropped)
    problems = package_doc_problems(spec_dir=spec_copy)
    cases.append(("a dropped list statement in 08 is caught",
                  dropped != text
                  and any("no longer states 'The reserved namespaces are"
                          in p for p in problems)))

    # -- a code only a package case emits still counts for coverage
    from rhoform.codes import REGISTRY

    block = {entry.code for entry in REGISTRY
             if entry.code.startswith("RHO2") and not entry.reserved}
    triggerable = block - set(NOT_SOURCE_TRIGGERED)
    elaborate_only = triggerable - {"RHO2064"}
    cases.append(("a block-2 code emitted only by a package case covers it",
                  elaborate_coverage_problems(elaborate_only) != []
                  and elaborate_coverage_problems(
                      elaborate_only | {"RHO2064"}) == []))
    return cases


def unavailable_reason():
    """Why the gate cannot run, or None when both pins are present.

    Two dependencies, two failure SHAPES. A missing jsonschema raises
    ImportError at import time. A missing lark does not: rhoform.parser
    imports fine (it does not import lark at module scope), and the
    absence surfaces only when `_load()` raises LarkUnavailable, which
    subclasses RuntimeError because the parser reports it as a runtime
    condition. A guard catching ImportError alone let the lark case
    through as an uncaught traceback and exit 1 — reporting an
    environment problem as a conformance violation, the opposite of the
    "an unavailable gate is not a pass" rule this file states four times
    (review round 6).

    The obvious test misses it: with no pins installed at all, jsonschema
    raises first and the gate exits 2, so the lark branch is never
    reached. The self-test therefore plants the failure directly.
    """
    try:
        import jsonschema  # noqa: F401
        from rhoform import parser as _parser
        from rhoform.parser import LarkUnavailable
    except ImportError as exc:
        return str(exc)
    try:
        _parser._load()
    except (ImportError, LarkUnavailable) as exc:
        return str(exc)
    return None


def main(write=False) -> int:
    reason = unavailable_reason()
    if reason is not None:
        print(
            f"conformance: UNAVAILABLE: {reason}. Install the pins from "
            "toolchain/versions.yaml (lark==1.3.0, jsonschema==4.26.0); "
            "an unavailable gate is not a pass.",
            file=sys.stderr,
        )
        return 2

    problems = []
    parse_problems, accepts, rejects = parse_case_problems(
        CONFORMANCE / "parse" / "accept",
        CONFORMANCE / "parse" / "reject",
        write=write,
    )
    problems += parse_problems
    literal_problems, vectors, errors = vector_problems(
        CONFORMANCE / "literals" / "normal-form.json")
    problems += literal_problems
    problems += doc_sync_problems()
    formatter_problems, formats = fmt_case_problems(
        CONFORMANCE / "fmt",
        CONFORMANCE / "parse" / "reject",
        write=write,
    )
    problems += formatter_problems
    package_problems, p_accepts, p_rejects, package_codes = \
        package_leg_problems(write=write)
    problems += package_problems
    elaborate_problems, e_accepts, e_rejects = elaborate_leg_problems(
        write=write, package_codes=package_codes)
    problems += elaborate_problems

    if accepts < MINIMUM_ACCEPT_CASES:
        problems.append(
            f"{accepts} accept case(s), below the floor of "
            f"{MINIMUM_ACCEPT_CASES}; the suite may not shrink by accident"
        )
    if rejects < MINIMUM_REJECT_CASES:
        problems.append(
            f"{rejects} reject case(s), below the floor of "
            f"{MINIMUM_REJECT_CASES}"
        )
    if vectors < MINIMUM_VECTORS:
        problems.append(
            f"{vectors} normal-form vector(s), below the floor of "
            f"{MINIMUM_VECTORS}"
        )
    if errors < MINIMUM_ERROR_VECTORS:
        problems.append(
            f"{errors} error vector(s), below the floor of "
            f"{MINIMUM_ERROR_VECTORS}"
        )
    if formats < MINIMUM_FMT_CASES:
        problems.append(
            f"{formats} formatter case(s), below the floor of "
            f"{MINIMUM_FMT_CASES}"
        )

    if problems:
        for problem in problems:
            print(f"conformance: FAIL: {problem}", file=sys.stderr)
        print(f"conformance: {len(problems)} failure(s).", file=sys.stderr)
        return 1
    print(
        f"conformance: PASS: {accepts} accept + {rejects} reject parse "
        f"case(s) byte-exact, {e_accepts} accept + {e_rejects} reject "
        f"elaboration case(s) byte-exact, {p_accepts} accept + {p_rejects} "
        f"reject package case(s) byte-exact, {formats} formatter case(s) "
        "byte-exact and fixed points with every reject case refused, "
        f"{vectors} normal-form vector(s) with all three T3 properties, "
        f"{errors} pinned rejection(s), spec restatements reconciled."
    )
    return 0


def self_test() -> int:
    """Prove each leg can fail, over throwaway trees and planted inputs."""
    import contextlib
    import io
    import shutil
    import tempfile

    reason = unavailable_reason()
    if reason is not None:
        print(f"conformance: UNAVAILABLE: {reason}", file=sys.stderr)
        return 2

    cases = []

    with tempfile.TemporaryDirectory() as tmp:
        accept = Path(tmp) / "accept"
        reject = Path(tmp) / "reject"
        accept.mkdir()
        reject.mkdir()
        pragma = "#pragma rhoform-syntax 0.1\n"

        (accept / "a01_ok.rhoform").write_text(
            pragma + "module M:\n    port p passive\n")
        problems, n_accept, _ = parse_case_problems(accept, reject)
        cases.append(("a clean accept case passes",
                      problems == [] and n_accept == 1))

        (accept / "a02_bad.rhoform").write_text(
            pragma + "module M:\n    port p pasive\n")
        problems, _, _ = parse_case_problems(accept, reject)
        cases.append(("an accept case that emits is caught",
                      any("expected a clean parse" in p and "RHO1009" in p
                          for p in problems)))
        (accept / "a02_bad.rhoform").unlink()

        bad = pragma + "module M:\n    port p pasive\n"
        (reject / "r01_x.rhoform").write_text(bad)
        problems, _, n_reject = parse_case_problems(accept, reject)
        cases.append(("a reject case without expected output is caught",
                      any("no r01_x.expected.ndjson" in p
                          for p in problems) and n_reject == 1))

        with contextlib.redirect_stdout(io.StringIO()):
            problems, _, _ = parse_case_problems(accept, reject, write=True)
        cases.append(("--write creates the expected file and passes",
                      problems == []
                      and (reject / "r01_x.expected.ndjson").is_file()))

        problems, _, _ = parse_case_problems(accept, reject)
        cases.append(("a written expected file round-trips byte-exact",
                      problems == []))

        stream = (reject / "r01_x.expected.ndjson").read_text()
        # The subtlest divergence worth pinning: one span byte shifts.
        obj = json.loads(stream)
        obj["spans"][0]["byte_start"] += 1
        (reject / "r01_x.expected.ndjson").write_text(
            json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")
        problems, _, _ = parse_case_problems(accept, reject)
        cases.append(("a one-byte span drift is caught",
                      any("diverges" in p for p in problems)))
        (reject / "r01_x.expected.ndjson").write_text(stream)

        (reject / "r02_orphan.expected.ndjson").write_text(stream)
        problems, _, _ = parse_case_problems(accept, reject)
        cases.append(("an orphaned expected file is caught",
                      any("no .rhoform case" in p for p in problems)))
        (reject / "r02_orphan.expected.ndjson").unlink()

        (reject / "r03_clean.rhoform").write_text(
            pragma + "module M:\n    port p passive\n")
        problems, _, _ = parse_case_problems(accept, reject)
        cases.append(("a reject case that stopped rejecting is caught",
                      any("no diagnostics" in p for p in problems)))
        (reject / "r03_clean.rhoform").unlink()

        # The escaped-fixture mechanism: an invalid-byte case committed
        # as ASCII escapes must decode, emit against the LOGICAL file
        # name, and round-trip byte-exactly like any other case.
        (reject / "r04_escaped.rhoform.escaped").write_text(
            "#pragma rhoform-syntax 0.1\\nmodule M:\\n"
            "    r = new lib.R(c = 5\\xffF)\\n")
        with contextlib.redirect_stdout(io.StringIO()):
            problems, _, n_reject = parse_case_problems(
                accept, reject, write=True)
        escaped_expected = reject / "r04_escaped.expected.ndjson"
        first = (json.loads(escaped_expected.read_text().splitlines()[0])
                 if escaped_expected.is_file() else {})
        cases.append(("an escaped invalid-byte case decodes and pins",
                      problems == [] and n_reject == 2
                      and first.get("code") == "RHO1002"
                      and "not valid UTF-8" in str(
                          first.get("params", {}).get("codepoint"))
                      and first.get("spans", [{}])[0].get("file")
                      == "r04_escaped.rhoform"))
        problems, _, _ = parse_case_problems(accept, reject)
        cases.append(("an escaped case round-trips byte-exact",
                      problems == []))
        (reject / "r04_escaped.rhoform.escaped").unlink()
        escaped_expected.unlink()

        # Leg 5, over its own throwaway directory. `reject` still holds
        # r01_x, a source with an error, which the formatter must refuse.
        formatter = Path(tmp) / "fmt"
        formatter.mkdir()
        canonical = pragma + "\nmodule M:\n    port p passive\n"
        (formatter / "f01_ok.rhoform").write_text(
            pragma + "module M:\n  port   p passive")
        (formatter / "f01_ok.expected.rhoform").write_text(canonical)
        problems, n_fmt = fmt_case_problems(formatter, reject)
        cases.append(("a formatter case formatting to its expected bytes "
                      "passes", problems == [] and n_fmt == 1))

        (formatter / "f01_ok.expected.rhoform").write_text(
            canonical.replace("port p", "port q"))
        problems, _ = fmt_case_problems(formatter, reject)
        cases.append(("a formatter case whose output diverges is caught",
                      any("diverge from f01_ok.expected.rhoform at "
                          "character 47" in p for p in problems)))

        (formatter / "f01_ok.expected.rhoform").write_text(
            pragma + "module M:\n  port p passive\n")
        problems, _ = fmt_case_problems(formatter, reject)
        cases.append(("an expected file that is not canonical is caught",
                      any("f01_ok.expected.rhoform: not a fixed point" in p
                          for p in problems)))
        (formatter / "f01_ok.expected.rhoform").write_text(canonical)

        (formatter / "f02_x.rhoform").write_text(canonical)
        problems, n_fmt = fmt_case_problems(formatter, reject)
        cases.append(("a formatter case without expected output is caught",
                      any("no f02_x.expected.rhoform" in p
                          for p in problems) and n_fmt == 2))

        # Trailing spaces and blank lines at end of file: the bytes the
        # escaped form exists for.
        (formatter / "f03_esc.rhoform.escaped").write_text(
            "#pragma rhoform-syntax 0.1\\nmodule M:  \\n"
            "  port p passive  # t   \\n\\n\\n")
        with contextlib.redirect_stdout(io.StringIO()):
            problems, n_fmt = fmt_case_problems(formatter, reject,
                                                write=True)
        written = formatter / "f03_esc.expected.rhoform"
        cases.append(("--write creates formatter expected files, escaped "
                      "inputs decoded",
                      problems == [] and n_fmt == 3
                      and (formatter / "f02_x.expected.rhoform").is_file()
                      and written.is_file() and written.read_text()
                      == canonical.replace("passive\n", "passive  # t\n")))
        problems, _ = fmt_case_problems(formatter, reject)
        cases.append(("written formatter cases round-trip byte-exact",
                      problems == []))

        (formatter / "f09_orphan.expected.rhoform").write_text(canonical)
        problems, _ = fmt_case_problems(formatter, reject)
        cases.append(("an orphaned formatter expected file is caught",
                      any("f09_orphan.expected.rhoform: expected file with "
                          "no input case" in p for p in problems)))
        (formatter / "f09_orphan.expected.rhoform").unlink()

        (formatter / "f04_bad.rhoform").write_text(
            pragma + "module M:\n    port p pasive\n")
        problems, _ = fmt_case_problems(formatter, reject)
        cases.append(("a formatter input that does not parse is caught",
                      any("f04_bad.rhoform: the input does not format "
                          "(refused: ['RHO1009'])" in p for p in problems)))
        (formatter / "f04_bad.rhoform").unlink()

        # A formatter that fails its own self-check raises; the leg must
        # report that, not die on the traceback.
        from unittest import mock

        from rhoform import fmt as fmt_module

        with mock.patch.dict(fmt_module._HEADS,
                             {"port_decl": lambda node: "port"}):
            problems, _ = fmt_case_problems(formatter, reject)
        cases.append(("a formatter failing its self-check is reported",
                      any("the input does not format (broken:" in p
                          for p in problems)))

        clean = Path(tmp) / "clean_reject"
        clean.mkdir()
        (clean / "r01_clean.rhoform").write_text(canonical)
        problems, _ = fmt_case_problems(formatter, clean)
        cases.append(("a formatter that does not refuse a reject case is "
                      "caught", any("r01_clean.rhoform: the formatter did "
                                    "not refuse it (ok)" in p
                                    for p in problems)))

        vec = Path(tmp) / "vectors.json"

        def write_vectors(vectors, errors):
            vec.write_text(json.dumps(
                {"vectors": vectors, "errors": errors}))

        write_vectors([{"input": "1000mV", "canonical": "1V"}],
                      [{"input": "10kOhm",
                        "reason_fragment": "unknown unit"}])
        problems, n_vec, n_err = vector_problems(vec)
        cases.append(("a correct vector table passes",
                      problems == [] and (n_vec, n_err) == (1, 1)))

        write_vectors([{"input": "1000mV", "canonical": "1000mV"}], [])
        problems, _, _ = vector_problems(vec)
        cases.append(("a wrong canonical spelling is caught",
                      any("normal form is" in p for p in problems)))

        write_vectors([], [{"input": "1V", "reason_fragment": "x"}])
        problems, _, _ = vector_problems(vec)
        cases.append(("an error vector that parses is caught",
                      any("must be rejected" in p for p in problems)))

        write_vectors([], [{"input": "10kOhm",
                            "reason_fragment": "wrong text"}])
        problems, _, _ = vector_problems(vec)
        cases.append(("a drifted rejection reason is caught",
                      any("pinned fragment" in p for p in problems)))

        write_vectors([{"input": "zzz", "canonical": "zzz"}], [])
        problems, _, _ = vector_problems(vec)
        cases.append(("an unparseable vector input is caught",
                      any("does not parse" in p for p in problems)))

        # The property checks fire only when the ENGINE breaks, so a
        # broken engine is planted: normal_form maps i -> c -> c2 and the
        # parse stub disagrees with itself about value and form. All four
        # property sites must report — without this they are deletable,
        # and the properties the spec advertises would be prose.
        from decimal import Decimal

        import rhoform.quantities as quantities_module

        class _StubQuantity:
            def __init__(self, text):
                self._text = text

            def key(self):
                # CONSTANT on purpose: the value leg must read the fields
                # below, and with a key() that never changes, a leg that
                # quietly went back to comparing key() to key() cannot
                # make the self-test case fire (round 8 found the
                # previous per-text key let exactly that revert pass).
                return ("stub",)

            # The value leg reads the DECIMALS, not key(), so the stub
            # carries them: a stub missing a field the gate reads makes
            # that leg unreachable in the self-test, which is the same
            # measuring-the-wrong-population defect the gate exists to
            # prevent. Distinct per text, so the leg sees a real change.
            @property
            def nominal(self):
                return Decimal(sum(ord(char) for char in self._text))

            @property
            def lower(self):
                return Decimal(sum(ord(char) for char in self._text))

            @property
            def upper(self):
                return Decimal(sum(ord(char) for char in self._text))

            @property
            def form(self):
                return "exact" if self._text == "i" else "interval-bare"

        real_nf = quantities_module.normal_form
        real_pq = quantities_module.parse_quantity
        quantities_module.normal_form = lambda t: {"i": "c", "c": "c2"}[t]
        quantities_module.parse_quantity = _StubQuantity
        try:
            write_vectors([{"input": "i", "canonical": "c"}], [])
            problems, _, _ = vector_problems(vec)
        finally:
            quantities_module.normal_form = real_nf
            quantities_module.parse_quantity = real_pq
        for fragment, label in (
            ("not idempotent", "a non-idempotent normal form is reported"),
            ("changed the VALUE", "a value-changing normal form is reported"),
            ("changed form", "a form-changing normal form is reported"),
            ("does not re-lex", "an unlexable canonical is reported"),
        ):
            cases.append((label, any(fragment in p for p in problems)))

        # The wire-schema leg on expected streams: point SCHEMA_PATH at a
        # schema the real emission cannot satisfy and the leg must report,
        # or it is a validator whose report line is deletable.
        global SCHEMA_PATH
        strict = Path(tmp) / "strict.schema.json"
        strict.write_text(json.dumps({
            "type": "object",
            "properties": {"code": {"const": "RHONONE"}},
        }))
        real_schema_path = SCHEMA_PATH
        SCHEMA_PATH = strict
        try:
            problems, _, _ = parse_case_problems(accept, reject)
        finally:
            SCHEMA_PATH = real_schema_path
        cases.append(("an expected stream violating the wire schema is "
                      "reported", any("violates the wire schema" in p
                                      for p in problems)))

        spec_copy = Path(tmp) / "language"
        shutil.copytree(SPEC_LANG, spec_copy)
        cases.append(("the real spec restatements reconcile",
                      doc_sync_problems() == []))

        grammar_md = spec_copy / "02-grammar.md"
        # `module` `most` is adjacent only in the keyword LIST; the word
        # `module` alone also appears in prose, which the extractor
        # rightly ignores — mutating prose would test nothing.
        grammar_md.write_text(grammar_md.read_text().replace(
            "`module` `most`", "`most`"))
        problems = doc_sync_problems(spec_dir=spec_copy)
        cases.append(("a drifted keyword list is caught",
                      any("keywords" in p for p in problems)))
        shutil.rmtree(spec_copy)
        shutil.copytree(SPEC_LANG, spec_copy)

        literals_md = spec_copy / "03-literals.md"
        literals_md.write_text(literals_md.read_text().replace(
            "`mohm` `ohm` `kohm` `Mohm`", "`ohm` `kohm` `Mohm`"))
        problems = doc_sync_problems(spec_dir=spec_copy)
        cases.append(("a shrunken unit ladder is caught",
                      any("unit table, resistance" in p for p in problems)))
        shutil.rmtree(spec_copy)
        shutil.copytree(SPEC_LANG, spec_copy)

        diag_md = spec_copy / "06-diagnostics.md"
        diag_md.write_text(diag_md.read_text().replace(
            "capped at **100 diagnostics**", "capped at **500 diagnostics**"))
        problems = doc_sync_problems(spec_dir=spec_copy)
        cases.append(("a drifted output cap is caught",
                      any("OUTPUT_CAP" in p for p in problems)))

        diag_md.write_text(diag_md.read_text().replace(
            "capped at **500 diagnostics**", "capped at very many"))
        problems = doc_sync_problems(spec_dir=spec_copy)
        cases.append(("a cap statement dropped from the prose is caught",
                      any("no longer states the output cap" in p
                          for p in problems)))
        shutil.rmtree(spec_copy)
        shutil.copytree(SPEC_LANG, spec_copy)

        diag_md = spec_copy / "06-diagnostics.md"
        diag_md.write_text(diag_md.read_text().replace(
            "| RHO0xxx | framework |", "| RHO0xxx | meta |"))
        problems = doc_sync_problems(spec_dir=spec_copy)
        cases.append(("a drifted block table is caught",
                      any("block table" in p for p in problems)))
        shutil.rmtree(spec_copy)
        shutil.copytree(SPEC_LANG, spec_copy)

        diag_md = spec_copy / "06-diagnostics.md"
        diag_md.write_text(diag_md.read_text().replace(
            "- `warning` — annotates.\n", ""))
        problems = doc_sync_problems(spec_dir=spec_copy)
        cases.append(("a dropped severity bullet is caught",
                      any("severity bullets" in p for p in problems)))

        diag_md.write_text(
            (spec_copy / "06-diagnostics.md").read_text().replace(
                "- `needs-review` —", "- `needs-a-look` —"))
        problems = doc_sync_problems(spec_dir=spec_copy)
        cases.append(("a renamed applicability bullet is caught",
                      any("applicability bullets" in p for p in problems)))
        shutil.rmtree(spec_copy)
        shutil.copytree(SPEC_LANG, spec_copy)

        grammar_md = spec_copy / "02-grammar.md"
        grammar_md.write_text(grammar_md.read_text().replace(
            "The 31 words the grammar spells", "The 30 words the grammar spells"))
        problems = doc_sync_problems(spec_dir=spec_copy)
        cases.append(("a drifted keyword count is caught",
                      any("keyword count" in p for p in problems)))
        shutil.rmtree(spec_copy)
        shutil.copytree(SPEC_LANG, spec_copy)

        lexical_md = spec_copy / "01-lexical-structure.md"
        # Since 0.2 the fence lists every implemented version: dropping
        # one is the drift, since a reader MUST still accept it.
        lexical_md.write_text(lexical_md.read_text().replace(
            "```text\n#pragma rhoform-syntax 0.1\n", "```text\n"))
        problems = doc_sync_problems(spec_dir=spec_copy)
        cases.append(("a drifted pragma restatement is caught",
                      any("shows the pragma as" in p for p in problems)))
        shutil.rmtree(spec_copy)
        shutil.copytree(SPEC_LANG, spec_copy)

        # Deleting a restatement outright must be as loud as drifting it:
        # these three branches survived the first coverage measurement.
        diag_md = spec_copy / "06-diagnostics.md"
        diag_md.write_text(diag_md.read_text().replace(
            "## Severity and tier", "## Severities"))
        problems = doc_sync_problems(spec_dir=spec_copy)
        cases.append(("a deleted severity section is caught",
                      any("lost the '## Severity and tier'" in p
                          for p in problems)))

        grammar_md = spec_copy / "02-grammar.md"
        grammar_md.write_text(grammar_md.read_text().replace(
            "The 31 words the grammar spells as literals",
            "the grammar's literal words"))
        problems = doc_sync_problems(spec_dir=spec_copy)
        cases.append(("a deleted keyword-count sentence is caught",
                      any("no longer states the keyword count" in p
                          for p in problems)))

        lexical_md = spec_copy / "01-lexical-structure.md"
        lexical_md.write_text(lexical_md.read_text().replace(
            "```text\n#pragma", "```\npragma"))
        problems = doc_sync_problems(spec_dir=spec_copy)
        cases.append(("a deleted pragma fence is caught",
                      any("no longer shows the pragma" in p
                          for p in problems)))
        shutil.rmtree(spec_copy)
        shutil.copytree(SPEC_LANG, spec_copy)

        formatting_md = spec_copy / "07-formatting.md"
        real_formatting = formatting_md.read_text()
        for old, new, fragment, label in (
            ("| 3 | `net_decl` |", "| 2 | `net_decl` |",
             "07-formatting.md statement ranks",
             "a drifted statement rank is caught"),
            ("### Statement ranks (F-1)", "### Statement order",
             "07-formatting.md statement ranks",
             "a deleted statement-rank table is caught"),
            ("| 5 | `dnp` |", "| 0 | `dnp` |",
             "07-formatting.md instance body order",
             "a drifted instance-body rank is caught"),
            ("c2 c10", "c10 c2", "07-formatting.md collation sample",
             "a collation sample out of natural order is caught"),
            ("```text\nR2", "```\nR2",
             "no longer shows the collation sample",
             "a deleted collation sample is caught"),
        ):
            formatting_md.write_text(real_formatting.replace(old, new))
            problems = doc_sync_problems(spec_dir=spec_copy)
            cases.append((label, real_formatting.count(old) == 1
                          and any(fragment in p for p in problems)))
        formatting_md.write_text(real_formatting)

        # Syntax 0.2's restatements. Each mutation runs on a fresh copy and
        # must actually apply: a replacement that matched nothing would
        # leave the spec intact and report nothing, failing the case for
        # the wrong reason, so a miss is reported as its own failure.
        import types

        def drifted(doc, old, new, sot=None):
            shutil.rmtree(spec_copy)
            shutil.copytree(SPEC_LANG, spec_copy)
            target = spec_copy / doc
            text = target.read_text()
            if old not in text:
                return [f"self-test mutation {old!r} matched nothing"]
            target.write_text(text.replace(old, new))
            return doc_sync_problems(spec_dir=spec_copy, sot=sot)

        for doc, old, new, fragment, label in (
            ("02-grammar.md", "`from` `if` `import` `in`\n",
             "`from` `if` `import`\n",
             "keywords added in 0.2", "a drifted 0.2 keyword list"),
            ("02-grammar.md", "`inductance` `int`", "`inductance`",
             "02-grammar.md param_type", "a drifted param_type list"),
            ("02-grammar.md", "\n`range`\n", "\n`rnage`\n",
             "02-grammar.md loop_iterator", "a drifted loop_iterator list"),
            ("02-grammar.md", "The 1 word reserved", "The 8 words reserved",
             "reserved-word count", "a drifted reserved-word count"),
            ("01-lexical-structure.md", "`~` `[` `]` ", "`~` ",
             "punctuation tokens", "a drifted punctuation list"),
            ("01-lexical-structure.md", "{0.1, 0.2}", "{0.2}",
             "implemented version set", "a drifted version set"),
            ("01-lexical-structure.md", "Syntax 0.2 is the",
             "Syntax 0.1 is the", "'0.1' for the current version",
             "a drifted current version"),
            ("01-lexical-structure.md", "is the\ncurrent version",
             "was the\nlatest version",
             "no longer states the current version",
             "a deleted current-version sentence"),
        ):
            problems = drifted(doc, old, new)
            cases.append((f"{label} is caught",
                          any(fragment in p for p in problems)))

        # Two kinds of growth in the source of truth the spec has not
        # caught up with. A new vocabulary must be REPORTED as unrestated,
        # where it used to crash the gate with a KeyError; a new operator
        # terminal must reach the punctuation reconciliation, which reads
        # the terminals rather than naming COMPARE and INDEX_OP.
        real_sot = _load_sot()
        grown = types.SimpleNamespace(**vars(real_sot))
        grown.CLOSED_VOCABULARIES = {**real_sot.CLOSED_VOCABULARIES,
                                     "widget_kind": ("knob",)}
        problems = drifted("02-grammar.md", "", "", sot=grown)
        cases.append(("a vocabulary the spec does not restate is reported, "
                      "not a crash",
                      any("widget_kind" in p and "missing ['knob']" in p
                          for p in problems)))
        grown = types.SimpleNamespace(**vars(real_sot))
        grown.TERMINALS = {**real_sot.TERMINALS, "ARROW": r"->"}
        problems = drifted("02-grammar.md", "", "", sot=grown)
        cases.append(("an operator terminal the spec does not list is "
                      "caught", any("punctuation tokens" in p
                                    and "missing ['->']" in p
                                    for p in problems)))

        cases += elaborate_self_test_cases(tmp)
        cases += package_self_test_cases(tmp)

    # WIRING: all five floors feed main(). Raise each over the real
    # population in turn — three of the first four were deletable when
    # only the accept floor had a case.
    for floor_name in ("MINIMUM_ACCEPT_CASES", "MINIMUM_REJECT_CASES",
                       "MINIMUM_VECTORS", "MINIMUM_ERROR_VECTORS",
                       "MINIMUM_FMT_CASES"):
        real_floor = globals()[floor_name]
        globals()[floor_name] = 10_000
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                wired = main()
        finally:
            globals()[floor_name] = real_floor
        cases.append((f"the {floor_name} floor is WIRED into main()",
                      wired == 1 and "below the floor" in err.getvalue()))

    # A missing lark must exit 2, not 1. Planted rather than discovered:
    # uninstalling both pins hits the jsonschema branch first, so the
    # only way to measure THIS branch is to make _load() fail on its own.
    from rhoform import parser as _parser
    from rhoform.parser import LarkUnavailable

    def _no_lark():
        raise LarkUnavailable("lark is not installed (planted)")

    real_load, _parser._load = _parser._load, _no_lark
    try:
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            absent = main()
    finally:
        _parser._load = real_load
    cases.append(("a missing lark exits 2 (UNAVAILABLE), never 1",
                  absent == 2 and "UNAVAILABLE" in err.getvalue()))

    failures = 0
    for name, ok in cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        print(f"conformance: SELF-TEST FAILED: {failures} case(s)",
              file=sys.stderr)
        return 1
    print(f"conformance: self-test PASS: {len(cases)} cases.")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(self_test())
    sys.exit(main(write="--write" in sys.argv[1:]))
