"""Anchors: the production package agrees with the M0 artifacts.

These tests exist for the window in which both generations are in the
tree — the bake-off prototypes (throwaway) and the production `rhoform`
package (permanent). Each pins an agreement that would otherwise rot
silently: the freeze-basis memo's pattern of anchoring the frozen grammar
against the prototype that measured it, applied one layer up. They live
in lang/tests because they import `bakeoff`, and nothing outside lang/
may do that; the production package itself imports none of this.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import lark  # noqa: F401
    HAVE_LARK = True
except ImportError:  # pragma: no cover
    HAVE_LARK = False


class IndenterAnchorTest(unittest.TestCase):
    def test_production_and_conformance_indenter_configs_agree(self):
        # Two Indenter configurations exist (the M0 gate's and the
        # production parser's) because neither package may import the
        # other's internals; this is the test that makes them one.
        from grammar import conformance
        from rhoform import parser as production

        self.assertEqual(production._INDENTER, conformance._INDENTER)


class QuantityAnchorTest(unittest.TestCase):
    def test_the_production_unit_table_is_the_prototypes_minus_one(self):
        # The one deliberate difference: the dimensionless pseudo-unit
        # "1", which no literal can lex and which the production module
        # therefore refuses to carry (its docstring says why). Everything
        # else — symbols, dimensions, multipliers — must agree exactly.
        from bakeoff import quantities as prototype
        from rhoform import quantities as production

        expected = {symbol: value
                    for symbol, value in prototype._UNITS.items()
                    if symbol != "1"}
        self.assertEqual(production.UNITS, expected)

    def test_parse_semantics_agree_over_the_shared_forms(self):
        from bakeoff import quantities as prototype
        from rhoform import quantities as production

        for text in ("100kohm", "560ohm +/- 1%", "2.0V +/- 200mV",
                     "9.5mA (8.0mA to 10.5mA)", "3.0V to 3.6V",
                     "1V +/- 50mV", "25degC"):
            ours = production.parse_quantity(text)
            theirs = prototype.parse_quantity(text)
            self.assertEqual(
                (ours.dimension,
                 None if ours.nominal is None else str(ours.nominal),
                 str(ours.lower), str(ours.upper)),
                (theirs.dimension,
                 None if theirs.nominal is None
                 else str(prototype.to_base(theirs.nominal, theirs.unit)),
                 str(prototype.to_base(theirs.lower, theirs.unit)),
                 str(prototype.to_base(theirs.upper, theirs.unit))),
                text,
            )

    def test_rejections_agree_over_the_shared_error_shapes(self):
        from bakeoff.quantities import (
            QuantityError as PrototypeError,
            parse_quantity as prototype_parse,
        )
        from rhoform.quantities import (
            QuantityError as ProductionError,
            parse_quantity as production_parse,
        )

        for text in ("10kOhm", "2V +/- -1%", "9.5mA (10mA to 11mA)",
                     "5V to 3V", "2V +/- 10ms"):
            with self.assertRaises(ProductionError):
                production_parse(text)
            with self.assertRaises(PrototypeError):
                prototype_parse(text)


@unittest.skipUnless(HAVE_LARK, "lark (pinned in toolchain/versions.yaml) "
                     "is required; the grammar gate exits 2 without it")
class ParserAnchorTest(unittest.TestCase):
    def test_the_production_parser_accepts_the_whole_corpus_clean(self):
        # The conformance gate proves the GRAMMAR parses the corpus; the
        # production parser adds pre-scans and post-parse checks on top,
        # any of which could quietly start rejecting legal designs. Zero
        # diagnostics over every rendering is the anchor.
        from bakeoff.arms import candidate_b
        from bakeoff.arms.base import VARIANTS
        from bakeoff.model import load_corpus
        from rhoform.parser import parse

        checked = 0
        for design_id, model in sorted(load_corpus().items()):
            for variant in VARIANTS:
                source = candidate_b.render(model, variant)
                result = parse(source, file=f"{design_id}.rhoform")
                self.assertTrue(
                    result.ok,
                    f"{design_id}/{variant}: "
                    f"{result.diagnostics.render()[:400]}",
                )
                checked += 1
        self.assertEqual(checked, 9)

    def test_the_production_parser_rejects_the_losing_surface(self):
        # Same negative control the conformance gate's tests apply to the
        # grammar: a parser loose enough to accept candidate A's surface
        # would not implement the language that was chosen.
        from bakeoff.arms import candidate_a
        from bakeoff.model import load_corpus
        from rhoform.parser import parse

        source = candidate_a.render(load_corpus()["blinker-555"], "explicit")
        self.assertFalse(parse(source, file="a.rhoform").ok)


if __name__ == "__main__":
    unittest.main()
