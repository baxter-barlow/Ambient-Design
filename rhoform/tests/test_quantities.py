"""The T3 normal form's three properties — value-exact, idempotent,
form-preserving — plus the parse semantics the spec section states.
The conformance vectors in spec/conformance/ re-check the same properties
over the published vector table; these tests pin the engine itself."""

import decimal
import unittest
from decimal import Decimal

from rhoform.quantities import (
    FORMS, QuantityError, UNITS, normal_form, parse_quantity,
)


class AmbientContextTest(unittest.TestCase):
    """Review round 6: _plain() called Decimal.normalize() outside the
    module's 60-digit local context, so the normal form rounded at the
    AMBIENT context's precision — process-global mutable state no caller
    of normal_form() controls. Both checks that claimed to pin
    value-exactness measured the wrong population: the precision test
    used 20 significant digits, safely under the default 28, and the
    idempotence checks compare key() to key(), so both sides round
    identically and the comparison is blind to the loss."""

    def test_a_literal_past_the_default_precision_is_not_rounded(self):
        literal = "1.0000000000000000000000000001ohm"
        self.assertEqual(normal_form(literal), literal)

    def test_the_normal_form_ignores_the_ambient_decimal_context(self):
        literal = "1.0000000000000000000000000001ohm"
        with decimal.localcontext() as ctx:
            ctx.prec = 5
            self.assertEqual(normal_form(literal), literal)

    def test_every_ambient_context_setting_is_ignored_not_just_precision(self):
        # Round 8: `localcontext()` copies the WHOLE ambient context, so
        # round 6's fix for precision left the exponent range and the
        # rounding mode inherited — an ambient Emax of 5 made `5000000MHz`
        # overflow and be refused. Hermetic means the same literal parses
        # to the same value in every process state, so every field is set.
        literal = "1234.5678901234567891ohm +/- 0.25%"
        expected = parse_quantity(literal)
        with decimal.localcontext() as ctx:
            ctx.prec, ctx.Emax, ctx.Emin = 5, 5, -5
            ctx.rounding = decimal.ROUND_DOWN
            ctx.traps[decimal.Inexact] = True
            got = parse_quantity(literal)
            self.assertEqual((got.nominal, got.lower, got.upper),
                             (expected.nominal, expected.lower,
                              expected.upper))
            self.assertEqual(normal_form("5000000MHz"), "5000000MHz")
            self.assertEqual(normal_form("0.05mohm"), "0.05mohm")

    def test_no_precision_boundary_survives_anywhere_in_the_module(self):
        # Review round 7: making `_plain()` adaptive MOVED the 28-digit
        # boundary to 60 rather than removing it, because to_base(),
        # parse_quantity() and _canonical_pair() still pinned the floor
        # flat. A 70-digit literal collapsed to `1ohm` exactly as a
        # 30-digit one used to. The assertion compares against the
        # LITERAL, not against another key() — the conformance gate's
        # value-exactness leg compares key() to key(), so both sides
        # round identically and it is structurally blind to this.
        for digits in (28, 40, 60, 61, 70, 120, 300):
            literal = "1." + "0" * (digits - 2) + "1ohm"
            self.assertEqual(normal_form(literal), literal, f"{digits} digits")

    def test_deep_precision_survives_a_unit_shift_and_a_tolerance(self):
        # The paths beyond _plain(): a power-of-ten shift through
        # to_base()/_canonical_pair(), and the one place two
        # author-supplied numbers are multiplied together.
        deep = "1." + "0" * 68 + "1"
        self.assertEqual(normal_form(deep + "kohm"), deep + "kohm")
        toleranced = f"{deep}ohm +/- {deep}%"
        self.assertEqual(normal_form(toleranced), toleranced)
        self.assertEqual(normal_form(normal_form(toleranced)),
                         normal_form(toleranced))

    @staticmethod
    def _exact(reference):
        # A reference computed where rounding is impossible. Every operand
        # here is a finite decimal and every divisor a power of ten, so the
        # exact result exists and five thousand digits is far past it.
        with decimal.localcontext() as ctx:
            ctx.prec = 5000
            return reference()

    def test_the_bounds_are_exact_when_the_operands_exponents_differ(self):
        # Round 8 (the focused pass over the round-7 fix): summing the
        # operands' digit counts bounds a PRODUCT, and every operation in
        # the module is a product or a power-of-ten shift except one —
        # `value -/+ spread` is a SUM, and a sum of operands at different
        # exponents needs the whole span between them. A 40-digit value
        # with a tolerance 24 orders of magnitude down needed 65 digits and
        # got 60. The rendered text never showed it: the percent and
        # absolute forms print the value and the tolerance, never the
        # bounds, so normal_form() stayed idempotent while the Decimal
        # fields a tolerance check consumes were rounded. Hence the
        # population here is the FIELDS, against exact arithmetic — not
        # text against text, and not key() against key().
        value, pct = "1." + "0" * 38 + "1", "0." + "0" * 23 + "5"
        v, t = Decimal(value), Decimal(pct)
        quantity = parse_quantity(f"{value}ohm +/- {pct}%")
        self.assertEqual(quantity.lower, self._exact(lambda: v - v * t / 100))
        self.assertEqual(quantity.upper, self._exact(lambda: v + v * t / 100))

        farads, picofarads = "1." + "0" * 45 + "1", "3." + "0" * 20 + "7"
        f, p = Decimal(farads), Decimal(picofarads)
        quantity = parse_quantity(f"{farads}F +/- {picofarads}pF")
        self.assertEqual(quantity.lower,
                         self._exact(lambda: f - p * Decimal("1e-12")))
        self.assertEqual(quantity.upper,
                         self._exact(lambda: f + p * Decimal("1e-12")))

    def test_every_form_keeps_every_field_exact_under_wide_operands(self):
        # All five forms, all three fields, in base units, against the
        # reference. The literal text is built from the STRINGS: Decimal's
        # str() switches to exponent notation below 1e-6, which no
        # quantity literal may carry.
        wide, tiny = "7." + "0" * 50 + "3", "0." + "0" * 40 + "9"
        w, y = Decimal(wide), Decimal(tiny)
        k, m, u, n, p = (Decimal(s) for s in
                         ("1e3", "1e-3", "1e-6", "1e-9", "1e-12"))
        cases = [
            (f"{wide}kohm", lambda: (w * k, w * k, w * k)),
            (f"{wide}V +/- {tiny}V", lambda: (w, w - y, w + y)),
            (f"{wide}mA +/- {tiny}%",
             lambda: (w * m, (w - w * y / 100) * m, (w + w * y / 100) * m)),
            (f"{wide}uF ({tiny}pF to {wide}mF)",
             lambda: (w * u, y * p, w * m)),
            (f"{tiny}nH to {wide}H", lambda: (None, y * n, w)),
        ]
        for text, reference in cases:
            quantity = parse_quantity(text)
            nominal, lower, upper = self._exact(reference)
            self.assertEqual(quantity.nominal, nominal, text)
            self.assertEqual(quantity.lower, lower, text)
            self.assertEqual(quantity.upper, upper, text)

    def test_a_rounding_the_bound_missed_is_loud_not_silent(self):
        # The bound is the ESTIMATE; the Inexact trap is the CHECK. If a
        # future edit brings back a boundary, the literal is refused with
        # a stable reason rather than compiled with a changed value. Proved
        # live by shrinking the bound, since a correct bound never trips it.
        from rhoform import quantities
        original = quantities._wide_enough
        quantities._wide_enough = lambda *values: 5
        try:
            with self.assertRaises(QuantityError) as caught:
                parse_quantity("123456789ohm +/- 1%")
            self.assertIn("working precision", caught.exception.reason)
            with self.assertRaises(QuantityError):
                normal_form("1234567890123ohm")
        finally:
            quantities._wide_enough = original

    def test_a_literal_past_the_exponent_range_is_refused_not_a_crash(self):
        # Round 8: a numeral of a million digits overflowed Decimal's
        # default Emax inside to_base() and escaped as decimal.Overflow, a
        # traceback from parse() for a literal the lexer admits — which
        # compilation-is-total forbids however unrealistic the input. Its
        # mirror, a million zeros after the point, rounded to ZERO and
        # normalized to `0mohm`, whose own normal form is `0ohm`: text
        # idempotence and value-exactness both gone, silently. Both are
        # refused now, with the same reason.
        with self.assertRaises(QuantityError) as caught:
            parse_quantity("1" + "0" * 1_000_000 + "kohm")
        self.assertIn("refused rather than rounded", caught.exception.reason)
        with self.assertRaises(QuantityError):
            normal_form("0." + "0" * 1_000_060 + "1mohm")


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
