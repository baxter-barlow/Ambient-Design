"""The production parser's contract: SoT-derived construction, error
tolerance with one diagnostic per defect, byte-true spans under every
recovery path, and the disambiguation decisions the frozen grammar makes.

The ambiguity-rejection cases here are the unit-level half of what
spec/conformance/ publishes as corpus cases; both exist because a corpus
case pins the wire format while a unit test pins the tree, and the two can
drift independently.
"""

import json
import unittest

try:
    import lark  # noqa: F401 - availability probe only
    HAVE_LARK = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_LARK = False

PRAGMA = "#pragma rhoform-syntax 0.1"


def _parse(source, **kwargs):
    from rhoform.parser import parse

    return parse(source, **kwargs)


def _codes(result):
    return [json.loads(line)["code"]
            for line in result.diagnostics.render().splitlines()]


@unittest.skipUnless(HAVE_LARK, "lark (pinned in toolchain/versions.yaml) "
                     "is required; the grammar gate exits 2 without it")
class CleanParseTest(unittest.TestCase):
    GOOD = PRAGMA + """
module Blinker:
    port vin power_in
    r1 = new rhoform.lib.passive.Resistor(resistance = 100kohm +/- 1%):
        pin a passive 1
        part abstract:
            package = "axial_0207"
        hardware test_point
        dnp
    net VCC (voltage_domain = "5V"):
        r1.a
    isolated r1.a
    vin ~ r1.a
    assert f static frequency (OUT) within 0.9 to 1.1
"""

    def test_a_valid_file_parses_with_zero_diagnostics(self):
        result = _parse(self.GOOD)
        self.assertTrue(result.ok)
        self.assertEqual(_codes(result), [])

    def test_output_is_byte_deterministic(self):
        bad = PRAGMA + "\nmodule M:\n    prt p passive\n    port q pasive\n"
        self.assertEqual(
            _parse(bad).diagnostics.render(),
            _parse(bad).diagnostics.render(),
        )

    def test_a_comment_before_the_pragma_is_legal(self):
        result = _parse("# banner\n" + PRAGMA + "\nmodule M:\n"
                        "    port p passive\n")
        self.assertTrue(result.ok)

    def test_no_final_newline_is_normalized_not_rejected(self):
        result = _parse(PRAGMA + "\nmodule M:\n    port p passive")
        self.assertTrue(result.ok)

    def test_the_parser_carries_no_grammar_of_its_own(self):
        # The load path is the generated artifact plus the SoT module;
        # this pins that the pragma text was recovered from the artifact,
        # not typed here.
        from rhoform import parser as production

        loaded = production._load()
        self.assertEqual(loaded.pragma_text, PRAGMA)
        self.assertIn("module", loaded.keyword_of.values())
        self.assertEqual(
            sorted(loaded.vocabularies),
            ["hardware_kind", "measurement_kind", "net_attribute",
             "pin_role"],
        )


@unittest.skipUnless(HAVE_LARK, "lark required")
class ByteLevelTest(unittest.TestCase):
    def test_a_tab_is_reported_with_its_exact_byte(self):
        result = _parse(PRAGMA + "\nmodule M:\n\tport p passive\n")
        self.assertEqual(_codes(result), ["RHO1001"])
        span = json.loads(result.diagnostics.render())["spans"][0]
        self.assertEqual(span["byte_start"], len(PRAGMA) + 1 + 10)
        self.assertIsNone(result.tree)

    def test_non_ascii_reports_the_codepoint_and_a_fixit(self):
        result = _parse(PRAGMA + "\nmodule M:\n    r = new lib.R(x = 5µF)\n")
        self.assertEqual(_codes(result), ["RHO1002"])
        diag = json.loads(result.diagnostics.render())
        self.assertEqual(diag["params"]["codepoint"], "U+00B5")
        self.assertEqual(diag["fixits"][0]["applicability"],
                         "machine-applicable")
        self.assertEqual(diag["fixits"][0]["edits"][0]["replacement"], "u")

    def test_a_carriage_return_is_its_own_diagnostic(self):
        result = _parse(PRAGMA + "\r\nmodule M:\n    port p passive\n")
        self.assertEqual(_codes(result), ["RHO1003"])

    def test_spans_stay_byte_true_after_an_invalid_utf8_byte(self):
        # Review round 1: a replace-mode decode turned one invalid byte
        # into a three-byte U+FFFD and every later span drifted by two.
        raw = (PRAGMA + "\nmodule M:\n    port p passive\n").encode()
        mutated = raw[:35] + b"\xff" + raw[35:40] + b"\t" + raw[40:]
        result = _parse(mutated.decode("utf-8", errors="surrogateescape"))
        diags = [json.loads(line)
                 for line in result.diagnostics.render().splitlines()]
        self.assertEqual([d["code"] for d in diags],
                         ["RHO1002", "RHO1001"])
        self.assertEqual(diags[0]["spans"][0]["byte_start"], 35)
        self.assertEqual(diags[0]["params"]["codepoint"],
                         "0xFF (not valid UTF-8)")
        tab_at = diags[1]["spans"][0]["byte_start"]
        self.assertEqual(mutated[tab_at], 0x09)

    def test_ascii_control_characters_have_their_own_code(self):
        # DEL is ASCII; reporting it as "non-ASCII character U+007F" was
        # factually wrong (review round 1).
        result = _parse(PRAGMA + "\nmodule M:\n    port p\x7f passive\n")
        diag = json.loads(result.diagnostics.render())
        self.assertEqual(diag["code"], "RHO1014")
        self.assertEqual(diag["slug"], "control-character")
        self.assertEqual(diag["params"], {"codepoint": "U+007F"})

    def test_byte_defects_suppress_the_grammar_parse(self):
        # One tab must not ALSO produce a parse error about the text
        # around it: pre-syntactic defects gate the syntactic read.
        result = _parse(PRAGMA + "\nmodule M\n\tport p passive\n")
        self.assertEqual(_codes(result), ["RHO1001"])


@unittest.skipUnless(HAVE_LARK, "lark required")
class PragmaTest(unittest.TestCase):
    def test_missing_pragma_is_one_diagnostic_and_the_body_is_checked(self):
        result = _parse("module M:\n    port p pasive\n")
        self.assertEqual(_codes(result), ["RHO1005", "RHO1009"])
        self.assertIsNotNone(result.tree)
        first = json.loads(result.diagnostics.render().splitlines()[0])
        self.assertEqual(first["params"]["expected"], PRAGMA)
        fixit = first["fixits"][0]
        self.assertEqual(fixit["applicability"], "machine-applicable")
        self.assertEqual(fixit["edits"][0]["byte_start"], 0)
        self.assertEqual(fixit["edits"][0]["replacement"], PRAGMA + "\n")

    def test_wrong_version_is_one_diagnostic_with_a_replacement_fixit(self):
        result = _parse("#pragma rhoform-syntax 9.9\nmodule M:\n"
                        "    port p passive\n")
        self.assertEqual(_codes(result), ["RHO1005"])
        self.assertIsNotNone(result.tree)
        diag = json.loads(result.diagnostics.render())
        self.assertIn("9.9", diag["params"]["found"])
        self.assertEqual(diag["fixits"][0]["edits"][0]["replacement"],
                         PRAGMA)

    def test_body_spans_are_untranslated_by_the_synthetic_header(self):
        # The parse runs over a shifted text; the report must not.
        result = _parse("module M:\n    port p pasive\n")
        vocab = json.loads(result.diagnostics.render().splitlines()[1])
        span = vocab["spans"][0]
        self.assertEqual(span["line_start"], 2)
        self.assertEqual(span["byte_start"],
                         len("module M:\n") + len("    port p "))

    def test_pragmatic_is_a_comment_not_a_failed_pragma(self):
        # One of the two recorded freeze divergences: the comment
        # exclusion ends at a word boundary.
        result = _parse("#pragmatic notes\n" + PRAGMA + "\nmodule M:\n"
                        "    port p passive\n")
        self.assertTrue(result.ok)

    def test_an_empty_file_reports_the_missing_header_and_module(self):
        result = _parse("")
        self.assertEqual(_codes(result), ["RHO1005", "RHO1007"])


@unittest.skipUnless(HAVE_LARK, "lark required")
class RecoveryTest(unittest.TestCase):
    def test_one_broken_statement_is_one_diagnostic(self):
        result = _parse(PRAGMA + "\nmodule M:\n    prt p passive\n"
                        "    port q pasive\n")
        self.assertEqual(_codes(result), ["RHO1006", "RHO1009"])
        self.assertIsNotNone(result.tree)

    def test_two_broken_statements_are_two_diagnostics(self):
        result = _parse(PRAGMA + "\nmodule M:\n    prt p passive\n"
                        "    x = neww lib.R\n    port q passive\n")
        self.assertEqual(_codes(result), ["RHO1006", "RHO1006"])

    def test_a_broken_header_orphans_its_block_silently(self):
        source = PRAGMA + """
module M
    port p passive
    port q passive
module N:
    port r passive
"""
        result = _parse(source)
        self.assertEqual(_codes(result), ["RHO1006"])
        self.assertIsNotNone(result.tree)
        # The surviving tree holds module N, proving the parse continued
        # past the orphaned block rather than stopping at it.
        modules = [
            str(next(child for child in node.children
                     if getattr(child, "type", None) == "FREE_NAME"))
            for node in result.tree.find_data("module_def")
        ]
        self.assertEqual(modules, ["N"])

    def test_an_unterminated_string_does_not_charge_per_word(self):
        result = _parse(PRAGMA + "\nmodule M:\n    r = new lib.R:\n"
                        '        part "axial 0207 through hole\n')
        self.assertEqual(_codes(result), ["RHO1004", "RHO1006"])

    def test_a_stray_character_heals_to_a_tree(self):
        result = _parse(PRAGMA + "\nmodule M:\n    port p passive @\n")
        self.assertEqual(_codes(result), ["RHO1011"])
        self.assertIsNotNone(result.tree)

    def test_eof_inside_a_block_names_what_was_expected(self):
        result = _parse(PRAGMA + "\nmodule M:")
        self.assertEqual(_codes(result), ["RHO1007"])

    def test_a_dedent_to_no_open_level_is_reported_not_swallowed(self):
        # Regression: lark's DedentError is not an UnexpectedInput, and
        # the first version returned NO tree and NO diagnostics for this
        # file — the one combination the framework must never produce.
        result = _parse(PRAGMA + "\nmodule M:\n    r = new lib.R:\n"
                        "        pin a passive\n      dnp\n")
        self.assertEqual(_codes(result), ["RHO1008"])
        diag = json.loads(result.diagnostics.render())
        # 1-based, agreeing with the span's col_start: the wire format
        # must not carry two column conventions in one line (review
        # round 1).
        self.assertEqual(diag["params"], {"column": 7})
        self.assertEqual(diag["spans"][0]["col_start"], 7)
        self.assertEqual(diag["spans"][0]["line_start"], 5)
        self.assertIsNotNone(result.tree)

    def test_a_broken_first_statement_orphans_its_block_silently(self):
        # Review round 1: the reactive orphan rule only worked when a
        # sibling statement preceded the broken header; with the broken
        # statement LEADING its block, the Indenter established the level
        # one deeper and charged the orphan one diagnostic per line (20
        # on a 40-line block, then no tree).
        body = "".join(f"        pin p{i} passive\n" for i in range(40))
        result = _parse(PRAGMA + "\nmodule M:\n    r = neww lib.R:\n"
                        + body + "module N:\n    port x passive\n")
        self.assertEqual(_codes(result), ["RHO1006"])
        self.assertIsNotNone(result.tree)
        modules = [
            str(next(child for child in node.children
                     if getattr(child, "type", None) == "FREE_NAME"))
            for node in result.tree.find_data("module_def")
        ]
        self.assertEqual(modules, ["N"])

    def test_an_authors_empty_block_still_reports(self):
        # The emptied-header silencing must apply ONLY to blocks recovery
        # itself emptied: a genuinely empty module is the author's
        # defect, reported once, and the file after it still parses.
        result = _parse(PRAGMA + "\nmodule Empty:\nmodule M:\n"
                        "    prt p passive\n    port q passive\n")
        self.assertEqual(_codes(result), ["RHO1006", "RHO1006"])
        self.assertIsNotNone(result.tree)

    def test_a_toleranced_quantity_in_a_plain_position_is_one_diagnostic(self):
        # Review round 1: ` +/- 1%` after a plain quantity lexes as
        # nothing, and the generic path charged one unexpected-character
        # per operator character. The defect is the literal's FORM.
        result = _parse(PRAGMA + "\nmodule M:\n"
                        "    assert v static operating_point (OUT) "
                        "at most 100kohm +/- 1%\n")
        self.assertEqual(_codes(result), ["RHO1012"])
        diag = json.loads(result.diagnostics.render())
        self.assertEqual(diag["params"], {"literal": "100kohm +/- 1%"})
        source = (PRAGMA + "\nmodule M:\n"
                  "    assert v static operating_point (OUT) "
                  "at most 100kohm +/- 1%\n")
        span = diag["spans"][0]
        self.assertEqual(source[span["byte_start"]:span["byte_end"]],
                         "100kohm +/- 1%")

    def test_a_midline_pragma_is_one_diagnostic(self):
        result = _parse(PRAGMA + "\nmodule M:\n"
                        "    port p passive  #pragma x\n")
        self.assertEqual(_codes(result), ["RHO1013"])

    def test_bad_dedents_inside_brackets_are_not_layout(self):
        # The re-derivation walker must mirror the Indenter: a wrapped
        # parameter list's continuation lines carry no layout.
        result = _parse(PRAGMA + "\nmodule M:\n    r = new lib.R(\n"
                        "  a = 1,\n        b = 2)\n")
        self.assertTrue(result.ok, _codes(result))

    def test_recovery_is_bounded_and_the_bound_is_stated(self):
        from rhoform.parser import _RECOVERY_LIMIT

        junk = PRAGMA + "\nmodule M:\n" + "".join(
            f"    ~{index} junk~\n" for index in range(60)
        )
        result = _parse(junk)
        self.assertLessEqual(len(result.diagnostics), _RECOVERY_LIMIT + 2)
        self.assertIsNone(result.tree)


@unittest.skipUnless(HAVE_LARK, "lark required")
class FileLocalCheckTest(unittest.TestCase):
    def test_each_vocabulary_site_is_checked(self):
        cases = {
            "port p pasive": ("pin_role", "pasive"),
            "h = new lib.H:\n        hardware mountinghole":
                ("hardware_kind", "mountinghole"),
            "assert f static frequencyy (OUT) at least 1":
                ("measurement_kind", "frequencyy"),
        }
        for body, (vocabulary, word) in cases.items():
            result = _parse(PRAGMA + "\nmodule M:\n    " + body + "\n")
            self.assertEqual(_codes(result), ["RHO1009"], body)
            diag = json.loads(result.diagnostics.render())
            self.assertEqual(diag["params"]["vocabulary"], vocabulary)
            self.assertEqual(diag["params"]["word"], word)

    def test_net_attribute_vocabulary_is_checked(self):
        result = _parse(PRAGMA + "\nmodule M:\n"
                        '    net VCC (voltage_domainn = "5V"):\n'
                        "        p\n")
        self.assertEqual(_codes(result), ["RHO1009"])

    def test_a_close_misspelling_gets_a_did_you_mean_fixit(self):
        result = _parse(PRAGMA + "\nmodule M:\n    port p pasive\n")
        diag = json.loads(result.diagnostics.render())
        self.assertEqual(diag["fixits"][0]["applicability"], "needs-review")
        self.assertEqual(diag["fixits"][0]["edits"][0]["replacement"],
                         "passive")

    def test_quantity_semantics_are_checked_with_spans(self):
        result = _parse(PRAGMA + "\nmodule M:\n"
                        "    r = new lib.R(x = 5kOhm)\n")
        self.assertEqual(_codes(result), ["RHO1010"])
        diag = json.loads(result.diagnostics.render())
        self.assertEqual(diag["params"]["literal"], "5kOhm")
        self.assertIn("unknown unit", diag["params"]["reason"])
        start = diag["spans"][0]["byte_start"]
        source = PRAGMA + "\nmodule M:\n    r = new lib.R(x = 5kOhm)\n"
        self.assertEqual(source[start:start + 5], "5kOhm")

    def test_vocabulary_words_stay_usable_as_names(self):
        # `input` is a pin role; it must still bind as an instance name —
        # the reason the vocabularies are not keywords.
        result = _parse(PRAGMA + "\nmodule M:\n"
                        "    input = new lib.Button\n")
        self.assertTrue(result.ok)


@unittest.skipUnless(HAVE_LARK, "lark required")
class AmbiguityRejectionTest(unittest.TestCase):
    """The disambiguation decisions, pinned at tree level (R12's feed into
    the R54 suite; the corpus half lives in spec/conformance/)."""

    def _tree(self, source):
        result = _parse(source)
        self.assertTrue(result.ok, _codes(result))
        return result.tree

    def test_a_to_b_lexes_as_one_interval_token(self):
        tree = self._tree(PRAGMA + "\nmodule M:\n"
                          "    r = new lib.R(x = 3V to 3.6V)\n")
        tokens = [t.type for t in tree.scan_values(
            lambda v: hasattr(v, "type") and v.type.startswith("QUANTITY")
        )]
        self.assertEqual(tokens, ["QUANTITY_INTERVAL"])

    def test_a_value_takes_integer_not_number(self):
        tree = self._tree(PRAGMA + "\nmodule M:\n"
                          "    r = new lib.R(count = 8)\n")
        tokens = [t.type for t in tree.scan_values(
            lambda v: getattr(v, "type", None) in ("INTEGER", "NUMBER")
        )]
        self.assertEqual(tokens, ["INTEGER"])

    def test_a_bare_decimal_value_is_rejected(self):
        result = _parse(PRAGMA + "\nmodule M:\n"
                        "    r = new lib.R(x = 1.5)\n")
        self.assertEqual(_codes(result), ["RHO1006"])

    def test_a_dimensionless_bound_admits_decimals(self):
        result = _parse(PRAGMA + "\nmodule M:\n"
                        "    assert d static duty_cycle (OUT) "
                        "within 0.5 to 0.6\n")
        self.assertTrue(result.ok)

    def test_keywords_carry_their_word_boundary(self):
        # `moduleM:` must not parse as `module M:`.
        result = _parse(PRAGMA + "\nmoduleM:\n    port p passive\n")
        self.assertFalse(result.ok)

    def test_the_chain_head_asymmetry_is_frozen(self):
        # `net.a ~ x` is rejected (the statement head is reserved-checked)
        # while `x ~ net.a` is accepted — recorded in the freeze basis,
        # reproduced here so regularising it is a decision, not drift.
        accepted = _parse(PRAGMA + "\nmodule M:\n    x ~ net.a\n")
        self.assertTrue(accepted.ok)
        rejected = _parse(PRAGMA + "\nmodule M:\n    net.a ~ x\n")
        self.assertFalse(rejected.ok)

    def test_a_bound_rejects_a_toleranced_quantity(self):
        result = _parse(PRAGMA + "\nmodule M:\n"
                        "    assert v static operating_point (OUT) "
                        "at most 100kohm +/- 1%\n")
        self.assertFalse(result.ok)

    def test_trailing_pragma_text_is_rejected_mid_line(self):
        # The other recorded freeze divergence: a mid-line `#pragma x` is
        # not a trailing comment.
        result = _parse(PRAGMA + "\nmodule M:\n"
                        "    port p passive  #pragma x\n")
        self.assertFalse(result.ok)


@unittest.skipUnless(HAVE_LARK, "lark required")
class TreeShapeTest(unittest.TestCase):
    """_VOCAB_SITES depends on the generated tree keeping NAME tokens where
    they are today; if the grammar regenerates differently, fail HERE with
    a message about the table rather than silently checking nothing."""

    def test_vocab_site_positions_match_the_generated_tree(self):
        from rhoform.parser import _VOCAB_SITES

        source = PRAGMA + """
module M:
    port p passive
    h = new lib.H:
        pin a passive 1
        hardware test_point
    net VCC (voltage_domain = "x"):
        h.a
    assert f static frequency (OUT) at least 1
"""
        result = _parse(source)
        self.assertTrue(result.ok, _codes(result))
        seen = set()
        for node in result.tree.iter_subtrees():
            site = _VOCAB_SITES.get(node.data)
            if site is None:
                continue
            vocabulary, index = site
            names = [c for c in node.children
                     if getattr(c, "type", None) == "NAME"]
            self.assertGreater(len(names), index, node.data)
            seen.add(node.data)
        self.assertEqual(seen, set(_VOCAB_SITES))


@unittest.skipUnless(HAVE_LARK, "lark required")
class MainTest(unittest.TestCase):
    def test_main_exits_like_a_gate(self):
        import contextlib
        import io
        import tempfile
        from pathlib import Path

        from rhoform.parser import main

        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.rhoform"
            good.write_text(PRAGMA + "\nmodule M:\n    port p passive\n")
            bad = Path(tmp) / "bad.rhoform"
            bad.write_text(PRAGMA + "\nmodule M:\n    port p pasive\n")

            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main([str(good)]), 0)
            self.assertEqual(out.getvalue(), "")

            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main([str(bad)]), 1)
            lines = out.getvalue().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["code"], "RHO1009")

            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(Path(tmp) / "ghost")]), 2)
                self.assertEqual(main([]), 2)


if __name__ == "__main__":
    unittest.main()
