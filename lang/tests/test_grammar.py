"""Tests for the frozen Rhoform syntax v0.

Three groups, and the middle one is the point:

  ARTIFACTS   the two generated files still match their source of truth
  ANCHORING   the frozen grammar describes the language the winning bake-off
              prototype actually implements — checked by running it over the
              same corpus, not by reading it
  BOUNDARY    what a context-free grammar cannot decide, stated as tests so
              nobody later mistakes the grammar's silence for approval

The anchoring group is what stops this freeze from being prose. AMB-32 shipped
a gate that printed "agrees with its anchor" while comparing a refdes list and
nothing else; a grammar file that is never fed to a parser is the same mistake
in a different costume.
"""

import re
import sys
import unittest
from pathlib import Path

LANG = Path(__file__).resolve().parents[1]
if str(LANG) not in sys.path:
    sys.path.insert(0, str(LANG))

from bakeoff.arms import candidate_a, candidate_b  # noqa: E402
from bakeoff.arms.base import PRAGMA, RESERVED, VARIANTS  # noqa: E402
from bakeoff.defects import DEFECTS  # noqa: E402
from bakeoff.model import (  # noqa: E402
    HARDWARE_KINDS,
    MEASUREMENT_KINDS,
    PIN_ROLES,
    load_corpus,
)
from grammar import conformance, rhoform_syntax  # noqa: E402
from grammar.rhoform_syntax import (  # noqa: E402
    ARTIFACTS,
    CLOSED_VOCABULARIES,
    KEYWORDS,
    LEXER_QUANTITY,
    PRAGMA_TEXT,
    RULES,
    TERMINALS,
    Alt,
    Lit,
    Opt,
    Rep,
    Seq,
)

CORPUS = load_corpus()


def _literals(node) -> set[str]:
    """Every word-shaped literal in a production tree."""
    found: set[str] = set()
    if isinstance(node, Lit):
        if re.fullmatch(r"[a-z_]+", node.text):
            found.add(node.text)
    for child in getattr(node, "items", ()) or getattr(node, "options", ()) or ():
        found |= _literals(child)
    inner = getattr(node, "item", None)
    if inner is not None:
        found |= _literals(inner)
    return found


class Artifacts(unittest.TestCase):
    def test_the_committed_artifacts_match_the_source_of_truth(self):
        """`--check` is the gate; this is the same comparison in the suite."""
        directory = LANG / "grammar"
        for filename, emit in ARTIFACTS.items():
            with self.subTest(artifact=filename):
                committed = (directory / filename).read_text(encoding="utf-8")
                self.assertEqual(committed, emit(), f"{filename} is stale")

    def test_generation_is_deterministic(self):
        for filename, emit in ARTIFACTS.items():
            with self.subTest(artifact=filename):
                self.assertEqual(emit(), emit())

    def test_check_mode_fails_on_a_stale_artifact(self):
        """The generator's own check must bite, or it is decoration.

        Written because `make_esp32_model.py` shipped a `--check` that could
        not fail; a freshness gate nobody has seen fail is a freshness gate
        nobody knows works.
        """
        import contextlib
        import io
        import tempfile

        def run(*argv: str) -> int:
            # The failing call prints its diagnosis, which is correct
            # behaviour and pure noise in a passing suite.
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                return rhoform_syntax.main(list(argv))

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for filename in ARTIFACTS:
                (directory / filename).write_text("stale\n", encoding="utf-8")
            self.assertEqual(run("--check", "--dir", str(directory)), 1)
            self.assertEqual(run("--write", "--dir", str(directory)), 0)
            self.assertEqual(run("--check", "--dir", str(directory)), 0)

    def test_check_mode_fails_when_an_artifact_is_missing(self):
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                self.assertEqual(rhoform_syntax.main(["--check", "--dir", tmp]), 1)

    def test_both_artifacts_state_the_same_lexical_layer(self):
        """Rule NAMES matching is not the two artifacts agreeing.

        The lexical layer was rendered by two different code paths — one
        walking the data, one hardcoding a string in the Lark emitter — and
        they disagreed. The EBNF said `NEWLINE ::= /(?:\\n[ ]*|COMMENT)+/`,
        which as a regex matches the literal word COMMENT and does not match a
        comment; the Lark half said `( /\\n[ ]*/ | COMMENT )+`, a reference,
        which is right. Both artifacts were generated, both were checked, and
        nothing compared the one line where they differed. This compares the
        rendered text.
        """
        from grammar.rhoform_syntax import LEXICAL, _render_parts

        ebnf = (LANG / "grammar" / "rhoform.ebnf").read_text(encoding="utf-8")
        lark = (LANG / "grammar" / "rhoform.lark").read_text(encoding="utf-8")
        for name, parts, _ in LEXICAL:
            if parts is None:
                continue
            rendered = _render_parts(parts)
            with self.subTest(lexical=name):
                self.assertIn(rendered, ebnf, f"{name} missing from the EBNF")
                self.assertIn(rendered, lark, f"{name} missing from the Lark")

    def test_a_lexical_reference_is_not_rendered_as_a_regex(self):
        """The specific defect above, pinned at the mechanism.

        A `LexRef` must render as a bare name in both dialects. If it ever
        renders inside a `/.../` literal again, it silently becomes the
        eight characters of its own name.
        """
        from grammar.rhoform_syntax import LexRef, Pat, _render_parts

        rendered = _render_parts((Pat(r"\n"), LexRef("COMMENT")))
        self.assertEqual(rendered, r"( /\n/ | COMMENT )+")
        self.assertNotIn("/COMMENT", rendered)

    def test_both_artifacts_carry_the_same_rules(self):
        """The two dialects are two renderings of one tree, so the rule set
        they declare cannot differ. This is the property that makes "generated
        from one source of truth" checkable rather than asserted."""
        ebnf = (LANG / "grammar" / "rhoform.ebnf").read_text(encoding="utf-8")
        lark = (LANG / "grammar" / "rhoform.lark").read_text(encoding="utf-8")
        in_ebnf = set(re.findall(r"^([a-z_]+) ::=", ebnf, re.M))
        in_lark = set(re.findall(r"^([a-z_]+):", lark, re.M))
        declared = {name for name, _, _ in RULES}
        self.assertEqual(in_ebnf, declared)
        self.assertEqual(in_lark, declared)

    def test_every_referenced_rule_is_defined(self):
        from grammar.rhoform_syntax import Ref

        defined = {name for name, _, _ in RULES}

        def refs(node) -> set[str]:
            found = {node.name} if isinstance(node, Ref) else set()
            for child in (
                getattr(node, "items", ()) or getattr(node, "options", ()) or ()
            ):
                found |= refs(child)
            inner = getattr(node, "item", None)
            if inner is not None:
                found |= refs(inner)
            return found

        used: set[str] = set()
        for _, _, node in RULES:
            used |= refs(node)
        self.assertEqual(used - defined, set(), "a rule is referenced but not defined")
        self.assertEqual(
            defined - used - {"start"}, set(), "a rule is defined but unreachable"
        )


class Anchoring(unittest.TestCase):
    """The frozen grammar against the prototype it was frozen from."""

    def test_the_pragma_is_the_one_the_prototype_emits(self):
        self.assertEqual(PRAGMA_TEXT, PRAGMA)

    def test_terminal_patterns_match_the_layout_tokenizer(self):
        """The grammar restates the lexer's patterns; they must still agree.

        The grammar owns its terminals rather than importing them, because it
        outlives the prototype. That freedom is only safe if something checks
        the two while both exist.
        """
        from bakeoff import layout

        self.assertEqual(TERMINALS["NAME"], layout._NAME_RE.pattern)
        self.assertEqual(TERMINALS["NUMBER"], layout._NUMBER_RE.pattern)
        self.assertEqual(LEXER_QUANTITY, layout._QUANTITY_RE.pattern)

    def test_the_quantity_split_covers_exactly_what_the_lexer_lexes(self):
        """The grammar splits one lexer terminal in two; the halves must add up.

        `within` needs an interval and `at least` a scalar, which one terminal
        cannot express — but a split that dropped or duplicated a form would
        change which literals exist, quietly, in a freeze.
        """
        whole = re.compile(LEXER_QUANTITY)
        scalar = re.compile(TERMINALS["QUANTITY"])
        interval = re.compile(TERMINALS["QUANTITY_INTERVAL"])
        literals = [
            "100kohm",
            "3.3V",
            "-5V",
            "100kohm +/- 1%",
            "2.0V +/- 0.2V",
            "9.5mA (8.0mA to 10.5mA)",
            "3.0V to 3.6V",
            "0.932Hz to 1.051Hz",
        ]
        for literal in literals:
            with self.subTest(literal=literal):
                self.assertEqual(whole.fullmatch(literal).group(0), literal)
                halves = [
                    bool(scalar.fullmatch(literal)),
                    bool(interval.fullmatch(literal)),
                ]
                self.assertEqual(
                    sum(halves), 1, "each literal belongs to exactly one half"
                )

    def test_closed_vocabularies_match_the_model(self):
        self.assertEqual(CLOSED_VOCABULARIES["pin_role"], tuple(PIN_ROLES))
        self.assertEqual(CLOSED_VOCABULARIES["hardware_kind"], tuple(HARDWARE_KINDS))
        self.assertEqual(
            CLOSED_VOCABULARIES["measurement_kind"], tuple(MEASUREMENT_KINDS)
        )
        self.assertEqual(
            CLOSED_VOCABULARIES["net_attribute"], candidate_b.NET_ATTRIBUTES
        )

    def test_every_literal_in_the_tree_is_a_declared_keyword(self):
        found: set[str] = set()
        for _, _, node in RULES:
            found |= _literals(node)
        self.assertEqual(found, set(KEYWORDS))

    def test_keywords_are_a_subset_of_what_the_prototype_reserves(self):
        """A keyword the parser lets you use as a name is a hole in the freeze."""
        self.assertEqual(set(KEYWORDS) - RESERVED, set())

    def test_the_freeze_drops_signal_and_nothing_else(self):
        """`signal` is candidate A's net declaration and lost the bake-off.

        Pinned so the difference stays a decision rather than becoming an
        oversight: `RESERVED` is shared by both candidates, and carrying the
        loser's keyword into the frozen language would reserve a useful
        identifier for a syntax that no longer exists.
        """
        self.assertEqual(RESERVED - set(KEYWORDS), {"signal"})

    def test_no_closed_vocabulary_word_is_also_a_keyword(self):
        """Roles and kinds must stay nameable; that is why they are not
        keywords. `input` and `output` are pin roles AND plausible instance
        names."""
        for kind, words in CLOSED_VOCABULARIES.items():
            with self.subTest(vocabulary=kind):
                self.assertEqual(set(words) & set(KEYWORDS), set())


@unittest.skipIf(
    not conformance.GRAMMAR_PATH.exists(), "the grammar artifact is missing"
)
class Conformance(unittest.TestCase):
    """Run the grammar. Everything above this point only reads it."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.parser = conformance.load_parser()
        except conformance.LarkUnavailable as exc:
            raise unittest.SkipTest(str(exc))

    RESISTOR = "aed.lib.passive.Resistor"

    def _accepts(self, source: str) -> bool:
        try:
            self.parser.parse(conformance.normalize(source))
            return True
        except Exception:
            return False

    def _design(self, body: str) -> str:
        """A whole file around a module body, so cases stay one-liners."""
        return f"{PRAGMA_TEXT}\n\nmodule M:\n" + body

    def _both(self, source: str) -> tuple[bool, bool]:
        """(grammar accepts, prototype accepts) — the differential itself.

        The prototype is asked only about SYNTAX: a `ParseFailure` is a
        syntactic no, and any other exception is the checker objecting to a
        well-formed file, which the grammar is not responsible for.
        """
        from bakeoff.diagnostics import ParseFailure

        try:
            candidate_b.parse(source, "inferred")
            prototype = True
        except ParseFailure:
            prototype = False
        except Exception:
            prototype = True
        return self._accepts(source), prototype

    def test_the_grammar_accepts_every_rendering_of_the_whole_corpus(self):
        for design_id, model in sorted(CORPUS.items()):
            for variant in VARIANTS:
                with self.subTest(design=design_id, variant=variant):
                    self.assertTrue(
                        self._accepts(candidate_b.render(model, variant)),
                        "the frozen grammar rejects source its own prototype "
                        "renders and parses",
                    )

    def test_the_grammar_rejects_the_losing_candidates_surface(self):
        """A negative control. A grammar loose enough to accept candidate A as
        well would not be describing the language that was chosen — and every
        acceptance test above would still pass."""
        source = candidate_a.render(CORPUS["blinker-555"], "inferred")
        self.assertFalse(self._accepts(source))

    def test_a_file_without_the_pragma_is_rejected(self):
        source = candidate_b.render(CORPUS["blinker-555"], "inferred")
        self.assertFalse(self._accepts(source.split("\n", 1)[1]))

    def test_a_pin_role_word_is_still_usable_as_an_instance_name(self):
        """The contextual-keyword hazard, pinned.

        `input` is a pin role. Had the grammar spelled the role vocabulary as
        keywords — the obvious way to write it — this design would stop
        parsing, while the prototype goes on accepting it. The two would
        disagree about a real program and every corpus test would still pass,
        because no corpus design happens to name an instance `input`.
        """
        source = (
            f"{PRAGMA_TEXT}\n"
            "\n"
            "module M:\n"
            "    input = new aed.lib.passive.Resistor(resistance = 1kohm)\n"
            "    output = new aed.lib.passive.Resistor(resistance = 1kohm)\n"
            "    input.a ~ output.a\n"
        )
        self.assertTrue(self._accepts(source))
        # And the prototype agrees, which is the half that makes it a conflict
        # rather than a preference.
        candidate_b.parse(source, "inferred")

    def test_syntactic_defects_are_rejected(self):
        """The defects a context-free grammar is responsible for."""
        syntactic = {"remove_indent", "unterminated_string", "dropped_bracket"}
        source = candidate_b.render(CORPUS["esp32s3-devboard"], "inferred")
        seen = set()
        for defect in DEFECTS:
            if defect.key not in syntactic:
                continue
            mutated = defect.apply(source)
            if mutated is None:
                continue
            seen.add(defect.key)
            with self.subTest(defect=defect.key):
                self.assertFalse(
                    self._accepts(mutated[0]),
                    f"{defect.key} leaves the file syntactically valid",
                )
        self.assertEqual(seen, syntactic, "a syntactic defect did not apply")

    def test_a_comment_only_line_parses(self):
        """`%ignore COMMENT` alone leaves two adjacent newlines behind.

        No production accepts that, so before the comment alternative was
        folded into `_NEWLINE`, NO file containing a standalone comment
        parsed — in any position. The conformance corpus could never have
        found it: `candidate_b.render` is a canonical formatter and emits no
        comments at all, so the gate was structurally blind to the whole
        construct.
        """
        for body in (
            "    # leading\n    r1 = new {r}(resistance = 1kohm)\n",
            "    r1 = new {r}(resistance = 1kohm)\n    # trailing\n",
            "    r1 = new {r}(resistance = 1kohm):\n        # inside a block\n"
            "        pin a passive\n",
        ):
            source = self._design(body.format(r=self.RESISTOR))
            with self.subTest(body=body.strip()[:24]):
                self.assertEqual(self._both(source), (True, True))

    def test_a_trailing_comment_parses(self):
        source = self._design(
            f"    r1 = new {self.RESISTOR}(resistance = 1kohm)  # a note\n"
        )
        self.assertEqual(self._both(source), (True, True))

    def test_no_keyword_is_usable_where_a_name_is_bound(self):
        """The grammar must be keyword-based (L5), not merely keyword-shaped.

        Lark's contextual lexer will happily read `module` as an ordinary
        identifier wherever an identifier is acceptable, so before FREE_NAME
        existed every one of the 24 keywords parsed as a module name, a net
        name, an instance name and a table row name — while the prototype
        rejected all of them. The test that was supposed to cover this
        compared KEYWORDS against RESERVED, which is a statement about two
        lists and not about the parser.
        """
        for word in KEYWORDS:
            for body in (
                f"module {word}:\n    port p passive\n",
                f"    net {word}:\n        p\n",
                f"    {word} = new {self.RESISTOR}(resistance = 1kohm)\n",
            ):
                source = (
                    f"{PRAGMA_TEXT}\n\n{body}"
                    if body.startswith("module")
                    else self._design(body)
                )
                with self.subTest(word=word, site=body.split()[0]):
                    self.assertFalse(
                        self._accepts(source),
                        f"{word!r} is a keyword but binds as a name here",
                    )

    def test_a_name_merely_starting_with_a_keyword_is_fine(self):
        """The negative lookahead must end at a word boundary, or `module_a`
        and `network` become unusable identifiers."""
        for word in ("module_a", "network", "porting", "newton", "tolerance"):
            with self.subTest(name=word):
                source = self._design(
                    f"    {word} = new {self.RESISTOR}(resistance = 1kohm)\n"
                )
                self.assertEqual(self._both(source), (True, True))

    def test_a_bound_takes_the_shape_its_keyword_requires(self):
        """`within` needs an interval and `at least` needs a scalar.

        One QUANTITY terminal covering both let `within 5V` and
        `at least 3.0V to 3.6V` through, and the prototype rejects each —
        `within` splits on ` to ` and the bound regex refuses an interval.
        """
        cases = {
            "within 1.0Hz to 2.0Hz": True,
            "within 0.5 to 0.6": True,
            "within 5V": False,
            "within 100kohm +/- 1%": False,
            "at least 3.0V": True,
            "at most 100kohm": True,
            "at least 3.0V to 3.6V": False,
            # The `at` half of the same rule. The first split separated the
            # interval form only, so a tolerance or an asymmetric interval
            # still passed where the prototype reports "is not a bound".
            "at most 100kohm +/- 1%": False,
            "at least 9.5mA (8.0mA to 10.5mA)": False,
            "at most 0.75": True,
        }
        for bound, expected in cases.items():
            source = self._design(
                f"    port p passive\n    assert a1 dynamic frequency(p) {bound}\n"
            )
            with self.subTest(bound=bound):
                self.assertEqual(self._accepts(source), expected)

    def test_an_alphanumeric_designator_parses(self):
        """Every designator in the corpus is numeric, so the NAME branch of
        `designator` is unreachable from the conformance gate alone — deleting
        it survives the whole suite otherwise. Connector pins are `A1`."""
        source = self._design(
            f"    j1 = new {self.RESISTOR}(resistance = 1kohm):\n"
            "        pin a passive A1\n"
            "        pin b passive B2\n"
        )
        self.assertEqual(self._both(source), (True, True))

    def test_the_pragma_terminal_is_not_merely_a_comment(self):
        """Loosening PRAGMA to `#[^\\n]*` survives every corpus test, because
        the corpus always opens with a real pragma. A plain comment in the
        pragma's position must not stand in for it."""
        source = "# not a pragma\n\nmodule M:\n    port p passive\n"
        self.assertFalse(self._accepts(source))

    def test_tabs_and_carriage_returns_are_rejected(self):
        """L5 says ASCII with indentation blocks; the tokenizer makes a tab a
        lexical error. A grammar that ignored `[ \\t]+` would accept two files
        that differ by a tab as the same program."""
        self.assertFalse(self._accepts(f"{PRAGMA_TEXT}\n\nmodule M:\n\tport p passive\n"))
        self.assertFalse(
            self._accepts(f"{PRAGMA_TEXT}\r\n\r\nmodule M:\r\n    port p passive\r\n")
        )

    def test_an_empty_net_attribute_list_parses(self):
        """`net N():` — the prototype's argument parser allows it, so the
        grammar must too, or the two disagree about a file that exists."""
        source = self._design("    port p passive\n    net N():\n        p\n")
        self.assertEqual(self._both(source), (True, True))

    def test_a_file_without_a_trailing_newline_parses(self):
        """The layout pass owes the grammar a final newline token.

        The tokenizer synthesizes one; Lark reads raw text. `normalize`
        supplies it so the difference stays a property of the reader rather
        than becoming a rule about a file's last byte.
        """
        source = self._design(
            f"    r1 = new {self.RESISTOR}(resistance = 1kohm)"
        ).rstrip("\n")
        self.assertTrue(self._accepts(source))

    def test_a_word_beginning_with_pragma_is_still_a_comment(self):
        """`#pragmatic` is a comment; only a `#pragma` WORD is the header.

        Excluding the bare prefix made `# pragmatic` notes a parse error,
        which the prototype accepts — the exclusion has to end at a word
        boundary for the same reason FREE_NAME's does.
        """
        source = self._design(f"    port p passive  #pragmatic\n")
        self.assertEqual(self._both(source), (True, True))

    def test_the_pragma_and_comment_boundary_is_a_decision(self):
        """Two divergences from the prototype, kept knowingly.

        The prototype decides `#pragma` POSITIONALLY — a `#` line whose
        stripped text starts with `#pragma` is the header, anything mid-line
        is a comment (layout.py) — and no terminal regex can express "at the
        start of a line, after optional spaces". Three formulations were
        measured against the prototype:

          exclusion on COMMENT (this one)   2 divergences
          no exclusion at all               2 divergences, and the SPDX case
                                            breaks: `_NEWLINE` swallows the
                                            pragma as a comment
          line-start lookbehind on PRAGMA   3 divergences, same SPDX break

        So this formulation is kept, and what it costs is written down rather
        than discovered later:

          `port p passive  #pragma x`  the grammar rejects, the prototype
                                       accepts it as a trailing comment
          `#pragmatic` on its own line the grammar reads a comment, the
                                       prototype reads a malformed pragma

        The second is arguably the prototype being wrong. Both are recorded
        in the freeze-basis memo's known-asymmetries list.
        """
        mid_line = self._design("    port p passive  #pragma x\n")
        self.assertEqual(self._both(mid_line), (False, True))

        standalone = self._design("    #pragmatic\n    port p passive\n")
        self.assertEqual(self._both(standalone), (True, False))

    def test_a_comment_or_blank_line_may_precede_the_pragma(self):
        """SPDX headers are the obvious case, and the prototype allows it:
        comments are stripped before the pragma is looked for."""
        for prefix in ("# SPDX-License-Identifier: Apache-2.0\n", "\n"):
            with self.subTest(prefix=prefix.strip() or "blank"):
                source = prefix + self._design("    port p passive\n")
                self.assertEqual(self._both(source), (True, True))

    def test_non_ascii_and_tabs_are_rejected_inside_lexemes_too(self):
        """L5's ASCII rule is about the file, not about the gaps between
        tokens. The tokenizer scans every character of every line, so a
        micro sign in a package string is a lexical error there; a grammar
        that only policed inter-token space would disagree about real files.
        """
        cases = {
            "string": self._design(
                f"    r1 = new {self.RESISTOR}(resistance = 1kohm):\n"
                '        part abstract:\n            package = "\u00b5F"\n'
                "        pin a passive\n        pin b passive\n    r1.a ~ r1.b\n"
            ),
            "comment": self._design("    port p passive  # 100k\u03a9\n"),
            "tab between tokens": self._design("    port\tp passive\n"),
            # The pragma line was the last lexeme still admitting a tab or a
            # non-ASCII character, which left L5's ASCII rule holding
            # everywhere except the one line every file must carry.
            "pragma, tab": f"{PRAGMA_TEXT}\t\n\nmodule M:\n    port p passive\n",
            "pragma, non-ascii": (
                f"{PRAGMA_TEXT} \u03a9\n\nmodule M:\n    port p passive\n"
            ),
            "pragma, DEL": (
                f"{PRAGMA_TEXT}\x7f\n\nmodule M:\n    port p passive\n"
            ),
        }
        for label, source in cases.items():
            with self.subTest(where=label):
                self.assertEqual(self._both(source), (False, False))

    def test_a_string_may_not_span_a_line(self):
        source = self._design(
            f"    r1 = new {self.RESISTOR}(resistance = 1kohm):\n"
            '        part abstract:\n            package = "un\nterminated"\n'
        )
        self.assertFalse(self._accepts(source))

    def test_empty_lists_parse_where_the_prototype_allows_them(self):
        """Three list forms, all of which the prototype accepts empty. The
        grammar required at least one member in each until a differential
        run said otherwise."""
        cases = {
            "argument list": self._design(
                f"    r1 = new {self.RESISTOR}():\n"
                "        pin a passive\n        pin b passive\n    r1.a ~ r1.b\n"
            ),
            "net attributes": self._design(
                "    port p passive\n    net N():\n        p\n"
            ),
            # A table declaring no columns gives rows that are a bare name.
            # `value+` made those rows unparseable while the header they
            # belong to stayed legal.
            "table column list": self._design(
                f"    table {self.RESISTOR} ():\n"
                "        r1\n        r2\n        r3\n"
                "    r1.a ~ r2.a\n    r1.b ~ r3.b\n"
            ),
        }
        for label, source in cases.items():
            with self.subTest(list=label):
                self.assertEqual(self._both(source), (True, True))

    def test_a_block_that_must_have_members_may_not_be_empty(self):
        """The counterpart: `module M:` and `net N:` both need a body, and
        `statement*` or `member*` would be a loosening no corpus design can
        catch."""
        self.assertFalse(self._accepts(f"{PRAGMA_TEXT}\n\nmodule M:\n"))
        self.assertFalse(
            self._accepts(self._design("    port p passive\n    net N:\n"))
        )

    def test_semantic_defects_are_not_the_grammars_job(self):
        """Stated as a test so the boundary is explicit.

        A misspelled unit, an undeclared instance, a role outside the T2
        lattice: all of these are well-formed sentences of this grammar and
        are caught by the checker, not the parser. Writing the grammar tight
        enough to reject them would mean baking four closed vocabularies into
        the keyword set, which breaks `input = new ...` (see above). If a
        later change makes one of these fail here, the grammar has grown a
        vocabulary it should not own.
        """
        source = candidate_b.render(CORPUS["esp32s3-devboard"], "inferred")
        for name in ("unknown_instance", "unknown_port", "corrupt_unit"):
            defect = next(d for d in DEFECTS if d.key == name)
            mutated = defect.apply(source)
            if mutated is None:
                continue
            with self.subTest(defect=name):
                self.assertTrue(self._accepts(mutated[0]))


if __name__ == "__main__":
    unittest.main()
