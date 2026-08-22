#!/usr/bin/env python3
"""Gate: the conformance suite holds the implementation to the spec.

Four legs:

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
     reserved words, the four vocabularies, the unit ladders, the
     diagnostic block table, the output cap) equals the source of truth
     it restates. The spec promised "a list in this spec is either
     machine-reconciled or absent"; this is the reconciliation.

Population floors on cases and vectors keep the suite from shrinking by
accident, the same posture as the schema gate's negative-control floor.

Exit 0 pass, 1 violation, 2 when the pinned lark or jsonschema is
missing (an unavailable gate is not a pass). `--write` regenerates the
reject cases' expected files from the reference implementation; the git
diff is the review artifact.

Usage: check-conformance.py [--self-test | --write]
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

CONFORMANCE = ROOT / "spec" / "conformance"
SPEC_LANG = ROOT / "spec" / "language"
SCHEMA_PATH = ROOT / "rhoform" / "diagnostic.schema.json"

# Today's populations. Cases may be added freely; a DROP below the floor
# is the suite shrinking out from under the spec, and must be a decision
# recorded here.
MINIMUM_ACCEPT_CASES = 8
MINIMUM_REJECT_CASES = 14
MINIMUM_VECTORS = 30
MINIMUM_ERROR_VECTORS = 11

_WORD = re.compile(r"`([A-Za-z_][A-Za-z0-9_./-]*)`")


def _spec_words(text: str, heading: str) -> list[str]:
    """Backticked words under `heading`, up to the next heading."""
    lines = text.split("\n")
    start = None
    level = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index + 1
            level = line.split(" ")[0]
            break
    if start is None:
        return []
    body = []
    for line in lines[start:]:
        if line.startswith("#") and line.split(" ")[0] <= level:
            break
        body.append(line)
    return _WORD.findall("\n".join(body))


def parse_case_problems(accept_dir, reject_dir, write=False):
    """Legs 1 and 2. Returns (problems, accept_count, reject_count)."""
    from rhoform.parser import parse

    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.validators.validator_for(schema)(schema)

    problems = []
    accept_cases = sorted(accept_dir.glob("*.rhoform"))
    for case in accept_cases:
        result = parse(case.read_text(encoding="utf-8"), file=case.name)
        if not result.ok:
            emitted = result.diagnostics.render().splitlines()
            codes = [json.loads(line)["code"] for line in emitted]
            problems.append(
                f"accept/{case.name}: expected a clean parse, got "
                f"{codes or 'no tree'}"
            )

    reject_cases = sorted(reject_dir.glob("*.rhoform"))
    expected_files = set(reject_dir.glob("*.expected.ndjson"))
    for case in reject_cases:
        expected_path = case.with_name(
            case.name[:-len(".rhoform")] + ".expected.ndjson")
        expected_files.discard(expected_path)
        result = parse(case.read_text(encoding="utf-8"), file=case.name)
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
        if parse_quantity(got).key() != parse_quantity(text).key():
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


def doc_sync_problems(spec_dir=SPEC_LANG, sot=None, units=None,
                      blocks=None, cap=None, severities=None,
                      applicability=None):
    """Leg 4: every restated list equals its source of truth."""
    if sot is None:
        import importlib.util

        sot_path = ROOT / "lang" / "grammar" / "rhoform_syntax.py"
        spec = importlib.util.spec_from_file_location("_sot_doc", sot_path)
        sot = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sot)
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

    reconcile("02-grammar.md keywords",
              _spec_words(grammar_md, "### Keywords (v0.1)"),
              sorted(sot.KEYWORDS))
    reconcile("02-grammar.md reserved words",
              _spec_words(grammar_md, "### Reserved for v1"),
              sorted(sot.RESERVED_FUTURE))
    heading_of = {
        "pin_role": "### pin_role (T2)",
        "hardware_kind": "### hardware_kind (L9)",
        "net_attribute": "### net_attribute (T5)",
        "measurement_kind": "### measurement_kind (V2)",
    }
    for vocabulary, words in sorted(sot.CLOSED_VOCABULARIES.items()):
        reconcile(f"02-grammar.md {vocabulary}",
                  _spec_words(grammar_md, heading_of[vocabulary]),
                  sorted(words))

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

    # The counts 02 states in prose, and the pragma 01 restates in its
    # fence: both pinned, same review finding.
    for pattern, want, where in (
        (r"The (\d+) words the grammar spells as literals",
         len(sot.KEYWORDS), "keyword count"),
        (r"The (\d+) words no v0\.1 rule uses",
         len(sot.RESERVED_FUTURE), "reserved-word count"),
    ):
        match = re.search(pattern, grammar_md)
        if match is None:
            problems.append(
                f"02-grammar.md no longer states the {where} in the "
                "expected form"
            )
        elif int(match.group(1)) != want:
            problems.append(
                f"02-grammar.md states {match.group(1)} for the {where}; "
                f"the grammar source of truth has {want}"
            )

    fence = re.search(r"```text\n(#pragma[^\n]*)\n```", lexical_md)
    if fence is None:
        problems.append(
            "01-lexical-structure.md no longer shows the pragma in its "
            "fenced block"
        )
    elif fence.group(1) != sot.PRAGMA_TEXT:
        problems.append(
            f"01-lexical-structure.md shows the pragma as "
            f"{fence.group(1)!r}; the source of truth says "
            f"{sot.PRAGMA_TEXT!r}"
        )
    return problems


def main(write=False) -> int:
    try:
        import jsonschema  # noqa: F401
        from rhoform import parser as _parser  # noqa: F401
        _parser._load()
    except ImportError as exc:
        print(
            f"conformance: UNAVAILABLE: {exc}. Install the pins from "
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

    if problems:
        for problem in problems:
            print(f"conformance: FAIL: {problem}", file=sys.stderr)
        print(f"conformance: {len(problems)} failure(s).", file=sys.stderr)
        return 1
    print(
        f"conformance: PASS: {accepts} accept + {rejects} reject parse "
        f"case(s) byte-exact, {vectors} normal-form vector(s) with all "
        f"three T3 properties, {errors} pinned rejection(s), spec "
        "restatements reconciled."
    )
    return 0


def self_test() -> int:
    """Prove each leg can fail, over throwaway trees and planted inputs."""
    import contextlib
    import io
    import shutil
    import tempfile

    try:
        import jsonschema  # noqa: F401
        from rhoform import parser as _parser
        _parser._load()
    except ImportError as exc:
        print(f"conformance: UNAVAILABLE: {exc}", file=sys.stderr)
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
        import rhoform.quantities as quantities_module

        class _StubQuantity:
            def __init__(self, text):
                self._text = text

            def key(self):
                return ("stub", self._text)

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
            "The 24 words the grammar spells", "The 23 words the grammar spells"))
        problems = doc_sync_problems(spec_dir=spec_copy)
        cases.append(("a drifted keyword count is caught",
                      any("keyword count" in p for p in problems)))
        shutil.rmtree(spec_copy)
        shutil.copytree(SPEC_LANG, spec_copy)

        lexical_md = spec_copy / "01-lexical-structure.md"
        lexical_md.write_text(lexical_md.read_text().replace(
            "#pragma rhoform-syntax 0.1", "#pragma rhoform-syntax 0.2"))
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
            "The 24 words the grammar spells as literals",
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

    # WIRING: all four floors feed main(). Raise each over the real
    # population in turn — three of the four were deletable when only the
    # accept floor had a case.
    for floor_name in ("MINIMUM_ACCEPT_CASES", "MINIMUM_REJECT_CASES",
                       "MINIMUM_VECTORS", "MINIMUM_ERROR_VECTORS"):
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
