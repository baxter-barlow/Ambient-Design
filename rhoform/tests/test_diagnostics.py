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
