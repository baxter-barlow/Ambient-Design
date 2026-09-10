"""The A1 contract, held as tests: registry discipline, span math, fix-it
applicability, canonical order, the stated cap, and NDJSON determinism."""

import json
import unittest

from rhoform import codes
from rhoform.diagnostics import (
    Diagnostic, Diagnostics, Edit, FixIt, OUTPUT_CAP, Span, entity_spans,
    span_from_bytes,
)

DATA = b"#pragma rhoform-syntax 0.1\nmodule M:\n    port p passive\n"


def _span(start, end):
    return span_from_bytes("design.rhoform", DATA, start, end)


class RegistryTest(unittest.TestCase):
    def test_the_shipped_registry_is_structurally_clean(self):
        self.assertEqual(codes.registry_problems(), [])

    def test_every_declared_block_digit_is_assigned(self):
        for entry in codes.REGISTRY:
            self.assertIn(int(entry.code[3]), codes.BLOCKS, entry.code)

    def test_lookup_refuses_an_undeclared_code(self):
        with self.assertRaises(KeyError):
            codes.lookup("RHO9999")

    def test_the_ga_block_carries_the_ten_spec_codes_plus_the_safety_note(self):
        ga = [e for e in codes.REGISTRY if e.code.startswith("RHO40")]
        self.assertEqual(
            [e.code for e in ga],
            [f"RHO40{n:02d}" for n in range(1, 12)],
        )
        # Slugs verbatim from the GA spec section 6 table; the registry
        # gate pins the full (slug, severity, params) transcription — this
        # test pins that they are all RESERVED until a checker emits them.
        self.assertTrue(all(e.reserved for e in ga))

    def test_render_is_deterministic_for_structured_values(self):
        entry = codes.lookup("RHO4002")
        first = entry.render({"cycle": ["agnd", "nt1", "pgnd", "nt2"]})
        second = entry.render({"cycle": ["agnd", "nt1", "pgnd", "nt2"]})
        self.assertEqual(first, second)
        self.assertIn('["agnd","nt1","pgnd","nt2"]', first)

    def test_registry_problems_reports_each_defect_shape(self):
        # Drive the checker over planted registries, one defect per case,
        # so a deleted rule in registry_problems cannot hide.
        good = codes.CodeDef("RHO1099", "planted", "error", "m {p}.", ("p",))
        cases = [
            ("bad code shape", codes.CodeDef("RHOX1", "s", "error", "m"),
             "does not match"),
            ("unassigned block", codes.CodeDef("RHO9001", "s", "error", "m"),
             "not assigned in BLOCKS"),
            ("bad slug", codes.CodeDef("RHO1099", "Bad_Slug", "error", "m"),
             "not kebab-case"),
            ("bad severity", codes.CodeDef("RHO1099", "s", "fatal", "m"),
             "unknown"),
            ("undeclared placeholder",
             codes.CodeDef("RHO1099", "s", "error", "m {ghost}."),
             "does not declare it"),
            ("unrendered param",
             codes.CodeDef("RHO1099", "s", "error", "m.", ("ghost",)),
             "never renders"),
        ]
        original = codes.REGISTRY
        try:
            for name, planted, fragment in cases:
                codes.REGISTRY = original + (planted,)
                problems = codes.registry_problems()
                self.assertTrue(
                    any(fragment in p for p in problems),
                    f"{name}: {problems}",
                )
            codes.REGISTRY = original + (good, good)
            problems = codes.registry_problems()
            self.assertTrue(any("already used" in p for p in problems))
            # Retirement holds a code forever: reusing a retired code or
            # slug is caught the same way.
            original_retired = codes.RETIRED
            try:
                codes.RETIRED = (("RHO1099", "planted", "test"),)
                codes.REGISTRY = original + (good,)
                problems = codes.registry_problems()
                self.assertTrue(
                    any("retired code" in p for p in problems), problems
                )
            finally:
                codes.RETIRED = original_retired
            # Out-of-order registries are refused: sortedness is what makes
            # the next free number visible.
            codes.REGISTRY = (original[1], original[0]) + original[2:]
            self.assertTrue(
                any("not in code order" in p for p in codes.registry_problems())
            )
        finally:
            codes.REGISTRY = original


class SpanTest(unittest.TestCase):
    def test_byte_offsets_are_authoritative_and_line_col_denormalized(self):
        span = _span(27, 33)  # "module"
        self.assertEqual((span.line_start, span.col_start), (2, 1))
        self.assertEqual((span.line_end, span.col_end), (2, 7))

    def test_a_zero_length_span_is_an_insertion_point(self):
        span = _span(27, 27)
        self.assertEqual((span.line_start, span.col_start), (2, 1))
        self.assertEqual((span.line_end, span.col_end), (2, 1))

    def test_columns_count_unicode_scalars_not_bytes(self):
        data = "x = 5µF\n".encode()  # µ occupies bytes 5-6
        span = span_from_bytes("f", data, 5, 7)
        self.assertEqual((span.byte_start, span.byte_end), (5, 7))
        self.assertEqual((span.col_start, span.col_end), (6, 7))

    def test_offsets_outside_the_file_are_refused(self):
        with self.assertRaises(ValueError):
            span_from_bytes("f", DATA, 5, len(DATA) + 1)
        with self.assertRaises(ValueError):
            span_from_bytes("f", DATA, 9, 5)

    def test_disordered_span_fields_are_refused(self):
        with self.assertRaises(ValueError):
            Span("f", 5, 3, 1, 1, 1, 1)
        with self.assertRaises(ValueError):
            Span("f", 0, 1, 0, 1, 1, 1)


class FixItTest(unittest.TestCase):
    def test_applicability_vocabulary_is_closed(self):
        with self.assertRaises(ValueError):
            FixIt("m", "definitely-safe", (Edit(_span(0, 1), "x"),))

    def test_a_fixit_with_no_edits_is_refused(self):
        with self.assertRaises(ValueError):
            FixIt("m", "needs-review", ())

    def test_placeholders_and_applicability_must_agree(self):
        edit = Edit(_span(0, 0), "<name> = new NetTie\n")
        FixIt("m", "has-placeholders", (edit,), placeholders=("name",))
        with self.assertRaises(ValueError):
            FixIt("m", "needs-review", (edit,), placeholders=("name",))
        with self.assertRaises(ValueError):
            FixIt("m", "has-placeholders", (edit,))
        with self.assertRaises(ValueError):
            FixIt("m", "has-placeholders", (Edit(_span(0, 0), "plain"),),
                  placeholders=("name",))

    def test_insertion_is_an_edit_capability(self):
        # The GA notes flagged instance insertion as an A1 requirement:
        # a zero-length span plus placeholder replacement expresses it.
        edit = Edit(_span(27, 27), "<tie> = new NetTie\n")
        fixit = FixIt("insert a NetTie", "has-placeholders", (edit,),
                      placeholders=("tie",))
        self.assertEqual(fixit.edits[0].span.byte_start,
                         fixit.edits[0].span.byte_end)


class DiagnosticTest(unittest.TestCase):
    def test_params_must_match_the_declaration_exactly(self):
        with self.assertRaises(ValueError):
            Diagnostic.new("RHO1010", {"literal": "x"}, primary=_span(0, 1))
        with self.assertRaises(ValueError):
            Diagnostic.new(
                "RHO1010",
                {"literal": "x", "reason": "r", "extra": 1},
                primary=_span(0, 1),
            )

    def test_severity_and_category_come_from_the_registry(self):
        diag = Diagnostic.new(
            "RHO1010", {"literal": "x", "reason": "r"}, primary=_span(0, 1)
        )
        self.assertEqual(diag.severity, "error")
        self.assertEqual(diag.category, "syntax")
        self.assertEqual(diag.slug, "invalid-quantity-literal")

    def test_the_message_is_rendered_from_template_and_params(self):
        diag = Diagnostic.new(
            "RHO1010", {"literal": "5kOhm", "reason": "unknown unit"},
            primary=_span(0, 1),
        )
        self.assertEqual(
            diag.message, "`5kOhm` is not a valid quantity: unknown unit"
        )

    def test_tier_vocabulary_is_closed(self):
        with self.assertRaises(ValueError):
            Diagnostic.new("RHO1001", {}, primary=_span(0, 1), tier="soon")

    def test_the_wire_object_carries_every_a1_field(self):
        diag = Diagnostic.new(
            "RHO1009", {"vocabulary": "pin_role", "word": "pasive"},
            primary=_span(43, 49), primary_label="declared here",
            secondary=((_span(27, 33), "in this module"),),
            entity="/m/p", tier="static",
        )
        obj = diag.as_dict()
        self.assertEqual(obj["schema"], "rhoform-diagnostic/0")
        self.assertEqual(obj["entity"], "/m/p")
        self.assertEqual(obj["tier"], "static")
        self.assertEqual(obj["params"],
                         {"vocabulary": "pin_role", "word": "pasive"})
        self.assertEqual([s["primary"] for s in obj["spans"]], [True, False])
        self.assertEqual(obj["spans"][1]["label"], "in this module")


class CollectorTest(unittest.TestCase):
    def _flood(self, sink, count, code="RHO1001"):
        for index in range(count):
            sink.add(code, {}, primary=_span(index % 20, index % 20 + 1))

    def test_emission_is_in_source_order_with_code_tiebreak(self):
        sink = Diagnostics()
        sink.add("RHO1010", {"literal": "x", "reason": "r"},
                 primary=_span(40, 43))
        sink.add("RHO1001", {}, primary=_span(27, 28))
        sink.add("RHO1004", {}, primary=_span(27, 28))
        self.assertEqual(
            [d.code for d in sink.capped()],
            ["RHO1001", "RHO1004", "RHO1010"],
        )

    def test_rendering_is_byte_deterministic(self):
        def build():
            sink = Diagnostics()
            sink.add("RHO1009", {"vocabulary": "pin_role", "word": "z"},
                     primary=_span(43, 49))
            sink.add("RHO1001", {}, primary=_span(27, 28))
            return sink.render()

        self.assertEqual(build(), build())

    def test_every_rendered_line_is_one_json_object(self):
        sink = Diagnostics()
        sink.add("RHO1001", {}, primary=_span(0, 1))
        sink.add("RHO1004", {}, primary=_span(2, 3))
        lines = sink.render().splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertEqual(json.loads(line)["schema"],
                             "rhoform-diagnostic/0")

    def test_the_cap_is_stated_never_silent(self):
        sink = Diagnostics(cap=3)
        self._flood(sink, 5)
        emitted = sink.capped()
        self.assertEqual(len(emitted), 4)  # cap + the truncation note
        note = emitted[-1]
        self.assertEqual(note.code, "RHO0001")
        params = dict(note.params)
        self.assertEqual(params["shown"], 3)
        self.assertEqual(params["total"], 5)
        self.assertEqual(params["suppressed"], 2)
        self.assertEqual(params["suppressed_errors"], 2)

    def test_the_column_index_agrees_with_decoding_at_every_offset(self):
        # Review round 7: the per-line column table is built with an
        # incremental decoder, which is NOT trivially the same thing as
        # decoding each prefix. This pins the equivalence exhaustively —
        # every offset of every case, against the exact expression the
        # fallback path uses — because a column is byte-exactly pinned by
        # the conformance suite and a silent drift would move every span
        # after it.
        from rhoform.diagnostics import span_from_bytes

        cases = [
            b"plain ascii line\n",
            "résistance = 100kΩ\n".encode("utf-8"),      # valid multi-byte
            b"a\xc3\n",                                   # truncated 2-byte
            b"a\xe2\x82\n",                               # truncated 3-byte
            b"a\xff\xfe b\n",                             # invalid bytes
            b"\xf0\x9f\x92\xa9 four-byte\n",              # 4-byte codepoint
            b"mixed \xc3\xa9 \xff \xe2\x82\xac end\n",
            b"no trailing newline \xc3\xa9",
            b"\n\n\xc3\xa9\n",                            # empty lines
            # Round 8: an encoded surrogate — what CESU-8, WTF-8 and Java's
            # modified UTF-8 emit for every astral character. CPython's
            # incremental decoder BUFFERS `ED A0..BF` at a chunk boundary
            # (so `surrogatepass` can work incrementally) where a bulk
            # decode emits two U+FFFD, so "one for the pending bytes" was
            # one short at exactly that offset; the line total healed a
            # byte later and the total-only check never fired. Round 7's
            # nine cases held no such pair.
            b"port \xed\xa0\x80 p passive\n",
            b"ab\xed\xa7M\n",
            b"\xed\xbf\xbf\xed\xa0\x80=\xc1(\n",
            b"ends mid-surrogate \xed\xa0",               # pending at EOF
        ]
        for data in cases:
            starts = [0] + [i + 1 for i, b in enumerate(data) if b == 0x0A]
            for offset in range(len(data) + 1):
                if offset == len(data) and offset in starts:
                    continue
                span = span_from_bytes("f.rhoform", data, offset, offset)
                line_index = max(i for i, s in enumerate(starts)
                                 if s <= offset)
                exact = len(
                    data[starts[line_index]:offset].decode("utf-8", "replace")
                ) + 1
                self.assertEqual(
                    span.col_start, exact,
                    f"{data!r} offset {offset}: {span.col_start} != {exact}")

    def test_the_column_table_matches_a_bulk_decode_for_every_byte_pair(self):
        # Round 8: the property is "table[i] == len(line[:i].decode(
        # 'utf-8', 'replace'))" at EVERY i, and a hand-picked case list is
        # the wrong population for a decoder whose buffering policy is not
        # documented as part of its contract. Every two-byte sequence with
        # a non-ASCII lead, and every three-byte sequence with a lead in
        # E0..F4 and a continuation second byte, each embedded mid-line;
        # the table must be exact AND the fast path must have held (a None
        # here means the total-only check fired, and round 8 measured the
        # per-call fallback it selects as quadratic again).
        from rhoform.diagnostics import _index_of, _line_columns

        def check(line: bytes):
            # The table spans the line INCLUDING its newline byte, so it
            # has len(data) + 1 entries: one per byte offset, 0..len.
            data = line + b"\n"
            starts, columns = _index_of(data)
            table = _line_columns(data, starts, columns, 0)
            self.assertIsNotNone(table, line)
            exact = [len(data[:i].decode("utf-8", "replace"))
                     for i in range(len(data) + 1)]
            self.assertEqual(table, exact, line)

        for lead in range(0x80, 0x100):
            for second in range(0x100):
                if second == 0x0A:
                    continue
                check(b"a" + bytes((lead, second)) + b"z")
        thirds = (0x00, 0x41, 0x80, 0xA0, 0xBF, 0xC0, 0xED, 0xFF)
        for lead in range(0xE0, 0xF5):
            for second in range(0x80, 0xC0):
                for third in thirds:
                    check(b"a" + bytes((lead, second, third)) + b"z")

    def test_col_end_is_exact_for_spans_that_cross_or_end_at_a_newline(self):
        # Round 8's pass: every col_end assertion in this file sat
        # mid-line, so an off-by-one for a span ending exactly at a line
        # start — its last byte the newline above — was pinned only by the
        # conformance case r12 on the wire. Every (start, end) pair of a
        # few multi-line strings, against the per-call slice round 6 used.
        from rhoform.diagnostics import span_from_bytes

        for data in (b"ab\ncd\n", b"\xc3\xa9\xff\ncd\n\n\xe2\x82",
                     b"one\n\ntwo \xed\xa0\x80\nthree"):
            starts = [0] + [i + 1 for i, b in enumerate(data) if b == 0x0A]
            for start in range(len(data) + 1):
                for end in range(start, len(data) + 1):
                    if end == start:
                        continue
                    span = span_from_bytes("f.rhoform", data, start, end)
                    last = end - 1
                    line_end = max(i for i, s in enumerate(starts)
                                   if s <= last)
                    exact = len(data[starts[line_end]:end]
                                .decode("utf-8", "replace")) + 1
                    self.assertEqual(
                        (span.line_end, span.col_end), (line_end + 1, exact),
                        f"{data!r} [{start}, {end})")

    def test_the_cap_holds_when_extend_aliases_a_diagnostic(self):
        # Review round 6: capped() partitioned kept from suppressed by
        # id(), but extend() splices the other collector's items BY
        # REFERENCE, so one object can hold two slots. When the retention
        # cut fell between two aliased occurrences both survived — the
        # cap was exceeded and the note's own shown+suppressed no longer
        # summed to total. Every existing cap test builds through add(),
        # which allocates a fresh object per call, so this branch was
        # never measured.
        sink = Diagnostics(cap=5)
        for offset in range(4):
            sink.add("RHO1004", {}, primary=_span(offset, offset + 1))
        aliased = Diagnostics()
        aliased.add("RHO1004", {}, primary=_span(20, 21))
        sink.extend(aliased)
        sink.extend(aliased)
        for offset in (40, 41, 42):
            sink.add("RHO1004", {}, primary=_span(offset, offset + 1))

        emitted = sink.capped()
        note = emitted[-1]
        self.assertEqual(note.code, "RHO0001")
        self.assertEqual(len(emitted), 6)  # cap + the truncation note
        params = dict(note.params)
        self.assertEqual(params["shown"], len(emitted) - 1)
        self.assertEqual(params["shown"] + params["suppressed"],
                         params["total"])

    def test_the_cap_retains_errors_over_warnings_and_notes(self):
        sink = Diagnostics(cap=2)
        sink.add("RHO4007", {"domain_ids": ["a", "b"]},
                 primary=_span(0, 1))          # warning
        sink.add("RHO1001", {}, primary=_span(5, 6))   # error
        sink.add("RHO1004", {}, primary=_span(9, 10))  # error
        kept = sink.capped()
        self.assertEqual([d.code for d in kept[:-1]],
                         ["RHO1001", "RHO1004"])
        self.assertEqual(dict(kept[-1].params)["suppressed_warnings"], 1)

    def test_under_the_cap_no_note_is_appended(self):
        sink = Diagnostics(cap=5)
        self._flood(sink, 5)
        self.assertEqual(len(sink.capped()), 5)
        self.assertTrue(all(d.code != "RHO0001" for d in sink.capped()))

    def test_the_default_cap_is_the_documented_decision(self):
        self.assertEqual(OUTPUT_CAP, 100)
        sink = Diagnostics()
        self._flood(sink, OUTPUT_CAP + 1)
        emitted = sink.capped()
        self.assertEqual(len(emitted), OUTPUT_CAP + 1)
        self.assertEqual(emitted[-1].code, "RHO0001")

    def test_has_errors_and_counts(self):
        sink = Diagnostics()
        self.assertFalse(sink.has_errors)
        sink.add("RHO4007", {"domain_ids": []}, primary=_span(0, 1))
        self.assertFalse(sink.has_errors)
        sink.add("RHO1001", {}, primary=_span(0, 1))
        self.assertTrue(sink.has_errors)
        self.assertEqual(sink.counts(),
                         {"error": 1, "warning": 1, "note": 0})


class EntitySpanTest(unittest.TestCase):
    SOURCEMAP = {
        "files": [{"path": "designs/blinker.rhoform", "sha256": "0" * 64}],
        "nodes": {
            "/indicator/r_lim": {
                "declaration": {
                    "file": 0, "byte_start": 100, "byte_end": 130,
                    "line_start": 7, "col_start": 5, "line_end": 7,
                    "col_end": 35,
                },
                "instantiation_trace": [
                    {"file": 0, "byte_start": 100, "byte_end": 130,
                     "line_start": 7, "col_start": 5, "line_end": 7,
                     "col_end": 35},
                    {"file": 0, "byte_start": 300, "byte_end": 340,
                     "line_start": 20, "col_start": 5, "line_end": 20,
                     "col_end": 45},
                ],
            }
        },
    }

    def test_resolution_returns_declaration_then_trace(self):
        spans = entity_spans(self.SOURCEMAP, "/indicator/r_lim")
        self.assertEqual(len(spans), 3)
        self.assertEqual(spans[0].byte_start, 100)
        self.assertEqual(spans[0].file, "designs/blinker.rhoform")
        self.assertEqual(spans[2].byte_start, 300)

    def test_an_unmapped_entity_raises(self):
        with self.assertRaises(KeyError):
            entity_spans(self.SOURCEMAP, "/ghost")

    def test_an_anchored_diagnostic_carries_entity_and_resolved_span(self):
        spans = entity_spans(self.SOURCEMAP, "/indicator/r_lim")
        diag = Diagnostic.new(
            "RHO4009", {"tie": "/indicator/r_lim", "net": "GND"},
            primary=spans[0],
            secondary=tuple((s, "instantiated from") for s in spans[1:]),
            entity="/indicator/r_lim",
        )
        obj = diag.as_dict()
        self.assertEqual(obj["entity"], "/indicator/r_lim")
        self.assertEqual(obj["spans"][0]["byte_start"], 100)


if __name__ == "__main__":
    unittest.main()
