"""The T3 normal form's three properties — value-exact, idempotent,
form-preserving — plus the parse semantics the spec section states.
The conformance vectors in spec/conformance/ re-check the same properties
over the published vector table; these tests pin the engine itself."""

import unittest
from decimal import Decimal

from rhoform.quantities import (
    FORMS, QuantityError, UNITS, normal_form, parse_quantity,
)


class ParseTest(unittest.TestCase):
    def test_the_five_forms_parse_to_their_form_names(self):
        cases = {
            "100kohm": "exact",
            "2V +/- 0.2V": "tolerance-absolute",
            "100kohm +/- 1%": "tolerance-percent",
            "9.5mA (8mA to 10.5mA)": "interval-bracketed",
            "3V to 3.6V": "interval-bare",
        }
        for text, form in cases.items():
            self.assertEqual(parse_quantity(text).form, form, text)
        self.assertEqual(sorted(cases.values()), sorted(FORMS))

    def test_arithmetic_is_exact_decimal_never_float(self):
        quantity = parse_quantity("560ohm +/- 1%")
        self.assertEqual(quantity.lower, Decimal("554.4"))
        self.assertEqual(quantity.upper, Decimal("565.6"))

    def test_semantics_are_in_base_units(self):
        quantity = parse_quantity("100kohm")
        self.assertEqual(quantity.nominal, Decimal("100000"))

    def test_dimensional_equality_across_spellings(self):
        self.assertEqual(
            parse_quantity("100kohm").key(),
            parse_quantity("100000ohm").key(),
        )
        self.assertNotEqual(
            parse_quantity("100kohm").key(),
            parse_quantity("100kHz").key(),
        )

    def test_a_bare_interval_has_no_nominal(self):
        self.assertIsNone(parse_quantity("3V to 3.6V").nominal)

    def test_mixed_unit_tolerance_converts_before_adding(self):
        quantity = parse_quantity("1V +/- 50mV")
        self.assertEqual(quantity.lower, Decimal("0.95"))
        self.assertEqual(quantity.upper, Decimal("1.05"))

    def test_rejections_carry_stable_reasons(self):
        cases = [
            ("10kOhm", "unknown unit"),
            ("1.5", "not one of the five"),
            ("2V +/- -1%", "cannot be negative"),
            ("9.5mA (10mA to 11mA)", "outside its own interval"),
            ("5V to 3V", "lower bound exceeds"),
            ("2V +/- 10ms", "is time but the value is voltage"),
            ("9.5mA (8s to 10s)", "is time but the value is current"),
        ]
        for text, fragment in cases:
            with self.assertRaises(QuantityError) as caught:
                parse_quantity(text)
            self.assertIn(fragment, caught.exception.reason, text)

    def test_the_unit_table_ladders_step_by_exactly_a_thousand(self):
        # The uniqueness of the normal form's unit choice rests on this;
        # a 10^1-stepped unit added carelessly would make two candidates
        # satisfy the mantissa window and the choice ambiguous.
        by_dimension = {}
        for symbol, (dimension, multiplier) in UNITS.items():
            by_dimension.setdefault(dimension, []).append(multiplier)
        for dimension, multipliers in by_dimension.items():
            if dimension == "temperature":
                continue
            ordered = sorted(multipliers)
            for below, above in zip(ordered, ordered[1:]):
                self.assertEqual(above / below, 1000, dimension)
            self.assertIn(Decimal(1), ordered, dimension)


class NormalFormTest(unittest.TestCase):
    VECTORS = [
        ("100kohm", "100kohm"),
        ("100000ohm", "100kohm"),
        ("0.1uF", "100nF"),
        ("1000mV", "1V"),
        ("1234.5ohm", "1.2345kohm"),
        ("-0.5V", "-500mV"),
        ("-0V", "0V"),
        ("0mA", "0A"),
        ("2.0V +/- 200mV", "2V +/- 200mV"),
        ("1500mV +/- 0.02V", "1.5V +/- 20mV"),
        ("100kohm +/- 1.50%", "100kohm +/- 1.5%"),
        ("9.5mA (8.0mA to 10.5mA)", "9.5mA (8mA to 10.5mA)"),
        ("3.0V to 3.6V", "3V to 3.6V"),
        ("0.5Hz", "0.5Hz"),
        ("5000000MHz", "5000000MHz"),
        ("25degC", "25degC"),
        ("560ohm +/- 1%", "560ohm +/- 1%"),
    ]

    def test_the_vectors(self):
        for text, want in self.VECTORS:
            self.assertEqual(normal_form(text), want, text)

    def test_idempotent(self):
        for text, _ in self.VECTORS:
            once = normal_form(text)
            self.assertEqual(normal_form(once), once, text)

    def test_value_exact(self):
        for text, _ in self.VECTORS:
            self.assertEqual(
                parse_quantity(normal_form(text)).key(),
                parse_quantity(text).key(),
                text,
            )

    def test_form_preserving(self):
        for text, _ in self.VECTORS:
            self.assertEqual(
                parse_quantity(normal_form(text)).form,
                parse_quantity(text).form,
                text,
            )

    def test_the_mantissa_window_is_one_to_a_thousand(self):
        self.assertEqual(normal_form("999.999ohm"), "999.999ohm")
        self.assertEqual(normal_form("1000ohm"), "1kohm")
        self.assertEqual(normal_form("1ohm"), "1ohm")
        self.assertEqual(normal_form("0.999ohm"), "999mohm")

    def test_off_ladder_values_take_the_nearest_end(self):
        # Resistance has no prefix above Mohm or below mohm; power stops
        # at W. The rule: nearest ladder end, mantissa allowed outside
        # the window rather than an invented unit.
        self.assertEqual(normal_form("5000Mohm"), "5000Mohm")
        self.assertEqual(normal_form("0.05mohm"), "0.05mohm")
        self.assertEqual(normal_form("5000W"), "5000W")

    def test_temperature_is_never_rescaled(self):
        self.assertEqual(normal_form("0.001degC"), "0.001degC")
        self.assertEqual(normal_form("2500degC"), "2500degC")

    def test_percent_never_converts_to_absolute(self):
        self.assertEqual(normal_form("1000mV +/- 10%"), "1V +/- 10%")

    def test_high_precision_survives(self):
        # 20 significant digits through a prefix shift, exactly.
        text = "1234.5678901234567891ohm"
        self.assertEqual(normal_form(text), "1.2345678901234567891kohm")
        self.assertEqual(
            parse_quantity(normal_form(text)).key(),
            parse_quantity(text).key(),
        )

    def test_the_output_relexes_as_one_quantity_token(self):
        # The canonical text must be a legal literal of the frozen
        # grammar, or the formatter would write files the parser rejects.
        import importlib.util
        from pathlib import Path
        import re

        sot_path = (Path(__file__).resolve().parents[2]
                    / "lang" / "grammar" / "rhoform_syntax.py")
        spec = importlib.util.spec_from_file_location("_sot_nf", sot_path)
        sot = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sot)
        lexer_quantity = re.compile(sot.LEXER_QUANTITY)
        for text, want in self.VECTORS:
            match = lexer_quantity.match(want)
            self.assertIsNotNone(match, want)
            self.assertEqual(match.group(0), want)


if __name__ == "__main__":
    unittest.main()
