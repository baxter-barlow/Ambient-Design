"""The exact quantity and interval algebra (rhoform/check/values.py, spec 05
section 2): the operation table as vectors, the conversions from elaborated
values and part data, the verdict, display, and seeded property tests of
soundness, nominal containment and the tightness claim.

ALGEBRA holds the vectors in the JSON shape plan L1c gave
spec/conformance/check/quantities/algebra.json; the conformance gate admits
nothing but pass.json, accept/ and reject/ in an area, so until it admits
that file the table lives here, where these tests read it.
"""

import json
import random
import unittest
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from rhoform.check import values as V

ROOT = Path(__file__).resolve().parents[2]
SEED = 53  # AMB-53; fixed, so a property failure reproduces exactly

# An operand is a quantity literal or {lo, hi, dim[, var, nominal, offset,
# verified]} in base units, the ends exact rationals or `-inf`/`+inf`. Its
# variable id is `var`, by default its position (`a`, `b`, `m`), and null
# for an anonymous leaf, which is never tight; a point is its own nominal.
# A result is {lo, hi, dim, tight[, nominal, offset, verified]},
# `UNDEFINED`, or {raises: DimensionError}.
ALGEBRA = json.loads(r"""
{
  "operations": [
    {"case": "sum, units converted exactly",
     "op": "add", "a": "1V +/- 50mV", "b": "500mV",
     "want": {"lo": "29/20", "hi": "31/20", "dim": "voltage", "tight": true,
              "nominal": "3/2"}},
    {"case": "difference: [a1-b2, a2-b1]",
     "op": "sub", "a": "5V +/- 1V", "b": "2V +/- 1V",
     "want": {"lo": "1", "hi": "5", "dim": "voltage", "tight": true,
              "nominal": "3"}},
    {"case": "x - x is wide and not tight",
     "op": "sub", "a": {"lo": "1", "hi": "2", "dim": "voltage", "var": "x"},
     "b": {"lo": "1", "hi": "2", "dim": "voltage", "var": "x"},
     "want": {"lo": "-1", "hi": "1", "dim": "voltage", "tight": false}},
    {"case": "negation",
     "op": "neg", "a": "9.5mA (8mA to 10.5mA)",
     "want": {"lo": "-21/2000", "hi": "-1/125", "dim": "current",
              "tight": true, "nominal": "-19/2000"}},
    {"case": "a sum of volts and amps",
     "op": "add", "a": "1V", "b": "1A", "want": {"raises": "DimensionError"}},
    {"case": "R * C is a time",
     "op": "mul", "a": "10kohm", "b": "1uF",
     "want": {"lo": "1/100", "hi": "1/100", "dim": "time", "tight": true,
              "nominal": "1/100"}},
    {"case": "V / ohm is a current",
     "op": "div", "a": "5V", "b": "1kohm",
     "want": {"lo": "1/200", "hi": "1/200", "dim": "current", "tight": true,
              "nominal": "1/200"}},
    {"case": "V * A is a power",
     "op": "mul", "a": "3.3V", "b": "100mA",
     "want": {"lo": "33/100", "hi": "33/100", "dim": "power", "tight": true,
              "nominal": "33/100"}},
    {"case": "a product takes the extreme of the four corners",
     "op": "mul", "a": {"lo": "-2", "hi": "3", "dim": "dimensionless"},
     "b": {"lo": "-5", "hi": "4", "dim": "dimensionless"},
     "want": {"lo": "-15", "hi": "12", "dim": "dimensionless",
              "tight": true}},
    {"case": "0 * inf = 0",
     "op": "mul", "a": {"lo": "0", "hi": "0", "dim": "dimensionless"},
     "b": {"lo": "-inf", "hi": "+inf", "dim": "voltage"},
     "want": {"lo": "0", "hi": "0", "dim": "voltage", "tight": true}},
    {"case": "[0, 1] * [1, +inf)",
     "op": "mul", "a": {"lo": "0", "hi": "1", "dim": "dimensionless"},
     "b": {"lo": "1", "hi": "+inf", "dim": "dimensionless"},
     "want": {"lo": "0", "hi": "+inf", "dim": "dimensionless",
              "tight": true}},
    {"case": "an infinite end survives a sum",
     "op": "add", "a": {"lo": "-inf", "hi": "-1", "dim": "current"},
     "b": {"lo": "2", "hi": "3", "dim": "current"},
     "want": {"lo": "-inf", "hi": "2", "dim": "current", "tight": true}},
    {"case": "and a difference",
     "op": "sub", "a": {"lo": "-inf", "hi": "1", "dim": "current"},
     "b": {"lo": "2", "hi": "+inf", "dim": "current"},
     "want": {"lo": "-inf", "hi": "-1", "dim": "current", "tight": true}},
    {"case": "division (i): 0 not in the divisor",
     "op": "div", "a": {"lo": "1", "hi": "2", "dim": "dimensionless"},
     "b": {"lo": "4", "hi": "8", "dim": "dimensionless"},
     "want": {"lo": "1/8", "hi": "1/2", "dim": "dimensionless",
              "tight": true}},
    {"case": "division (i): a negative divisor",
     "op": "div", "a": {"lo": "-2", "hi": "3", "dim": "dimensionless"},
     "b": {"lo": "-4", "hi": "-1", "dim": "dimensionless"},
     "want": {"lo": "-3", "hi": "2", "dim": "dimensionless", "tight": true}},
    {"case": "division (i): an unbounded divisor",
     "op": "div", "a": {"lo": "1", "hi": "2", "dim": "dimensionless"},
     "b": {"lo": "1", "hi": "+inf", "dim": "dimensionless"},
     "want": {"lo": "0", "hi": "2", "dim": "dimensionless", "tight": true}},
    {"case": "division (ii): by exactly zero",
     "op": "div", "a": {"lo": "1", "hi": "2", "dim": "dimensionless"},
     "b": {"lo": "0", "hi": "0", "dim": "dimensionless"},
     "want": "UNDEFINED"},
    {"case": "division (ii): even zero by zero",
     "op": "div", "a": {"lo": "0", "hi": "0", "dim": "dimensionless"},
     "b": {"lo": "0", "hi": "0", "dim": "dimensionless"},
     "want": "UNDEFINED"},
    {"case": "division (iii): zero over a divisor holding zero",
     "op": "div", "a": {"lo": "0", "hi": "0", "dim": "voltage"},
     "b": {"lo": "-1", "hi": "1", "dim": "current"},
     "want": {"lo": "0", "hi": "0", "dim": "resistance", "tight": true}},
    {"case": "division (iv): a numerator straddling zero",
     "op": "div", "a": {"lo": "-1", "hi": "2", "dim": "dimensionless"},
     "b": {"lo": "0", "hi": "1", "dim": "dimensionless"},
     "want": {"lo": "-inf", "hi": "+inf", "dim": "dimensionless",
              "tight": false}},
    {"case": "division (v): negative over [0, d]",
     "op": "div", "a": {"lo": "-3", "hi": "-1", "dim": "dimensionless"},
     "b": {"lo": "0", "hi": "2", "dim": "dimensionless"},
     "want": {"lo": "-inf", "hi": "-1/2", "dim": "dimensionless",
              "tight": false}},
    {"case": "division (v): negative over [c, 0]",
     "op": "div", "a": {"lo": "-3", "hi": "-1", "dim": "dimensionless"},
     "b": {"lo": "-2", "hi": "0", "dim": "dimensionless"},
     "want": {"lo": "1/2", "hi": "+inf", "dim": "dimensionless",
              "tight": false}},
    {"case": "division (v): negative over c < 0 < d",
     "op": "div", "a": {"lo": "-3", "hi": "-1", "dim": "dimensionless"},
     "b": {"lo": "-1", "hi": "1", "dim": "dimensionless"},
     "want": {"lo": "-inf", "hi": "+inf", "dim": "dimensionless",
              "tight": false}},
    {"case": "division (v): negative over [0, +inf)",
     "op": "div", "a": {"lo": "-3", "hi": "-1", "dim": "dimensionless"},
     "b": {"lo": "0", "hi": "+inf", "dim": "dimensionless"},
     "want": {"lo": "-inf", "hi": "0", "dim": "dimensionless",
              "tight": false}},
    {"case": "division (vi): positive over [0, d]",
     "op": "div", "a": {"lo": "1", "hi": "3", "dim": "dimensionless"},
     "b": {"lo": "0", "hi": "2", "dim": "dimensionless"},
     "want": {"lo": "1/2", "hi": "+inf", "dim": "dimensionless",
              "tight": false}},
    {"case": "division (vi): positive over [c, 0]",
     "op": "div", "a": {"lo": "1", "hi": "3", "dim": "dimensionless"},
     "b": {"lo": "-2", "hi": "0", "dim": "dimensionless"},
     "want": {"lo": "-inf", "hi": "-1/2", "dim": "dimensionless",
              "tight": false}},
    {"case": "division (vi): positive over c < 0 < d",
     "op": "div", "a": {"lo": "1", "hi": "3", "dim": "dimensionless"},
     "b": {"lo": "-1", "hi": "1", "dim": "dimensionless"},
     "want": {"lo": "-inf", "hi": "+inf", "dim": "dimensionless",
              "tight": false}},
    {"case": "square straddling zero is one use",
     "op": "square", "a": {"lo": "-1", "hi": "2", "dim": "voltage",
                           "var": "x"},
     "want": {"lo": "0", "hi": "4", "dim": "voltage^2", "tight": true}},
    {"case": "self-multiplication is two uses",
     "op": "mul", "a": {"lo": "-1", "hi": "2", "dim": "voltage", "var": "x"},
     "b": {"lo": "-1", "hi": "2", "dim": "voltage", "var": "x"},
     "want": {"lo": "-2", "hi": "4", "dim": "voltage^2", "tight": false}},
    {"case": "square of a negative interval",
     "op": "square", "a": {"lo": "-3", "hi": "-1", "dim": "dimensionless",
                           "var": "x"},
     "want": {"lo": "1", "hi": "9", "dim": "dimensionless", "tight": true}},
    {"case": "square of a positive interval",
     "op": "square", "a": {"lo": "2", "hi": "3", "dim": "dimensionless",
                           "var": "x"},
     "want": {"lo": "4", "hi": "9", "dim": "dimensionless", "tight": true}},
    {"case": "two readings give their difference",
     "op": "sub", "a": "25degC", "b": "20degC",
     "want": {"lo": "5", "hi": "5", "dim": "temperature", "tight": true,
              "nominal": "5", "offset": false}},
    {"case": "a reading plus a difference is a reading",
     "op": "add", "a": "25degC",
     "b": {"lo": "2", "hi": "2", "dim": "temperature"},
     "want": {"lo": "27", "hi": "27", "dim": "temperature", "tight": true,
              "offset": true}},
    {"case": "a reading minus a difference is a reading",
     "op": "sub", "a": "25degC +/- 1degC",
     "b": {"lo": "2", "hi": "2", "dim": "temperature"},
     "want": {"lo": "22", "hi": "24", "dim": "temperature", "tight": true,
              "nominal": "23", "offset": true}},
    {"case": "two readings have no sum",
     "op": "add", "a": "25degC", "b": "20degC",
     "want": {"raises": "DimensionError"}},
    {"case": "a difference minus a reading",
     "op": "sub", "a": {"lo": "2", "hi": "2", "dim": "temperature"},
     "b": "25degC", "want": {"raises": "DimensionError"}},
    {"case": "a reading inside a product",
     "op": "mul", "a": "25degC", "b": "2V",
     "want": {"raises": "DimensionError"}},
    {"case": "a reading inside a quotient",
     "op": "div", "a": "1V", "b": "25degC",
     "want": {"raises": "DimensionError"}},
    {"case": "a reading negated",
     "op": "neg", "a": "25degC", "want": {"raises": "DimensionError"}},
    {"case": "a level admits no arithmetic",
     "op": "add", "a": {"lo": "3", "hi": "3", "dim": "dB"},
     "b": {"lo": "3", "hi": "3", "dim": "dB"},
     "want": {"raises": "DimensionError"}},
    {"case": "nor a product",
     "op": "mul", "a": {"lo": "3", "hi": "3", "dim": "dBm"}, "b": "2V",
     "want": {"raises": "DimensionError"}},
    {"case": "hull of two states that meet",
     "op": "hull", "a": {"lo": "0", "hi": "2", "dim": "voltage", "var": "x"},
     "b": {"lo": "1", "hi": "5", "dim": "voltage", "var": "y"},
     "want": {"lo": "0", "hi": "5", "dim": "voltage", "tight": true}},
    {"case": "hull of two that do not is no range",
     "op": "hull", "a": {"lo": "0", "hi": "1", "dim": "voltage", "var": "x"},
     "b": {"lo": "4", "hi": "5", "dim": "voltage", "var": "y"},
     "want": {"lo": "0", "hi": "5", "dim": "voltage", "tight": false}},
    {"case": "intersection",
     "op": "intersect", "a": {"lo": "0", "hi": "3", "dim": "current",
                              "var": "x"},
     "b": {"lo": "1", "hi": "5", "dim": "current", "var": "y"},
     "want": {"lo": "1", "hi": "3", "dim": "current", "tight": false}},
    {"case": "intersection with a superset is the subset",
     "op": "intersect", "a": {"lo": "1", "hi": "2", "dim": "current",
                              "var": "x"},
     "b": {"lo": "0", "hi": "5", "dim": "current", "var": "y"},
     "want": {"lo": "1", "hi": "2", "dim": "current", "tight": true}},
    {"case": "scale by an exact constant",
     "op": "scale", "a": "10kohm +/- 1%", "factor": "3/2",
     "want": {"lo": "14850", "hi": "15150", "dim": "resistance",
              "tight": true, "nominal": "15000"}},
    {"case": "a sum keeps an unverified operand unverified",
     "op": "add", "a": {"lo": "1", "hi": "+inf", "dim": "current",
                        "verified": false},
     "b": {"lo": "2", "hi": "3", "dim": "current"},
     "want": {"lo": "3", "hi": "+inf", "dim": "current", "tight": true,
              "verified": false}},
    {"case": "a product keeps an unverified operand unverified",
     "op": "mul", "a": {"lo": "2", "hi": "3", "dim": "voltage"},
     "b": {"lo": "1", "hi": "+inf", "dim": "current", "verified": false},
     "want": {"lo": "2", "hi": "+inf", "dim": "power", "tight": true,
              "verified": false}},
    {"case": "a scale keeps an unverified operand unverified",
     "op": "scale", "a": {"lo": "1", "hi": "+inf", "dim": "current",
                          "verified": false}, "factor": "2",
     "want": {"lo": "2", "hi": "+inf", "dim": "current", "tight": true,
              "verified": false}}
  ],
  "relations": [
    {"m": "3.3V +/- 1%", "b": "3V to 3.6V", "want": "inside"},
    {"m": "3.3V +/- 1%", "b": "3.3V +/- 1%", "want": "inside"},
    {"m": "5V +/- 1%", "b": "3V to 3.6V", "want": "outside"},
    {"m": "3.6V +/- 1%", "b": "3V to 3.6V", "want": "overlaps"},
    {"m": {"lo": "3.6", "hi": "4", "dim": "voltage"}, "b": "3V to 3.6V",
     "want": "overlaps"},
    {"m": {"lo": "-inf", "hi": "1", "dim": "current"},
     "b": {"lo": "0", "hi": "+inf", "dim": "current"}, "want": "overlaps"},
    {"m": {"lo": "3", "hi": "3", "dim": "dB"},
     "b": {"lo": "0", "hi": "6", "dim": "dB"}, "want": "inside"},
    {"m": {"lo": "3", "hi": "3", "dim": "dB"},
     "b": {"lo": "0", "hi": "6", "dim": "dBm"},
     "want": {"raises": "DimensionError"}},
    {"m": "25degC", "b": {"lo": "0", "hi": "30", "dim": "temperature"},
     "want": {"raises": "DimensionError"}},
    {"m": "3.3V", "b": "3A to 4A", "want": {"raises": "DimensionError"}}
  ],
  "verdicts": [
    {"m": "3.3V +/- 1%", "b": "3V to 3.6V", "want": {"outcome": "pass"}},
    {"m": "5V +/- 1%", "b": "3V to 3.6V",
     "want": {"outcome": "fail", "certainty": "definite",
              "basis": "guaranteed"}},
    {"m": "3.6V +/- 1%", "b": "3V to 3.6V",
     "want": {"outcome": "fail", "certainty": "possible",
              "basis": "guaranteed"}},
    {"m": {"lo": "3.5", "hi": "3.7", "dim": "voltage", "var": null},
     "b": "3V to 3.6V",
     "want": {"outcome": "incomplete", "reason": "interval-overestimate"}},
    {"m": "UNDEFINED", "b": "3V to 3.6V",
     "want": {"outcome": "incomplete", "reason": "undefined-value"}},
    {"m": "UNVERIFIED", "b": "3V to 3.6V",
     "want": {"outcome": "incomplete", "reason": "unverified-input"}}
  ]
}
""")


def end(text):
    if text == "-inf":
        return V.NEG_INF
    if text == "+inf":
        return V.POS_INF
    return Fraction(text)


def dimension(name):
    if name in ("dB", "dBm"):
        return V.Dimension((0, 0, 0, 0, 0), name)
    if name.endswith("^2"):
        return V.named(name[:-2]) ** 2
    return V.named(name)


def operand(spec, position):
    if spec in ("UNDEFINED", "UNVERIFIED"):
        return getattr(V, spec)
    if isinstance(spec, str):
        return V.from_literal(spec, var=position)
    iv = V.Interval(end(spec["lo"]), end(spec["hi"]))
    nominal = spec.get("nominal", spec["lo"] if iv.is_point else None)
    var = spec.get("var", position)
    return V.Q(iv, dimension(spec["dim"]), spec.get("offset", False),
               None if nominal is None else Fraction(nominal),
               iv.is_point or var is not None,
               (var,) if var is not None and not iv.is_point else (),
               spec.get("verified", True))


OPERATIONS = {"add": V.add, "sub": V.sub, "mul": V.mul, "div": V.div,
              "hull": V.hull, "intersect": V.intersect}


class AlgebraVectorTest(unittest.TestCase):
    def test_every_operation_vector(self):
        for row in ALGEBRA["operations"]:
            with self.subTest(case=row["case"]):
                a = operand(row["a"], "a")
                if row["op"] in OPERATIONS:
                    run = lambda: OPERATIONS[row["op"]](  # noqa: E731
                        a, operand(row["b"], "b"))
                elif row["op"] == "scale":
                    run = lambda: V.scale(a, Fraction(row["factor"]))  # noqa
                else:
                    run = lambda: getattr(V, row["op"])(a)  # noqa: E731
                want = row["want"]
                if isinstance(want, dict) and "raises" in want:
                    with self.assertRaises(getattr(V, want["raises"])):
                        run()
                    continue
                got = run()
                if want == "UNDEFINED":
                    self.assertIs(got, V.UNDEFINED)
                    continue
                self.assertEqual((got.iv.lo, got.iv.hi),
                                 (end(want["lo"]), end(want["hi"])))
                self.assertEqual(got.dim, dimension(want["dim"]))
                self.assertIs(got.tight, want["tight"])
                if "nominal" in want:
                    self.assertEqual(got.nominal, Fraction(want["nominal"]))
                if "offset" in want:
                    self.assertIs(got.offset, want["offset"])
                self.assertIs(got.verified, want.get("verified", True))

    def test_every_relation_vector(self):
        for row in ALGEBRA["relations"]:
            with self.subTest(m=row["m"], b=row["b"]):
                m, b = operand(row["m"], "m"), operand(row["b"], "b")
                if isinstance(row["want"], dict):
                    with self.assertRaises(V.DimensionError):
                        V.relate(m, b)
                else:
                    self.assertEqual(V.relate(m, b), row["want"])

    def test_every_verdict_vector(self):
        for row in ALGEBRA["verdicts"]:
            with self.subTest(m=row["m"], b=row["b"]):
                got = V.verdict(operand(row["m"], "m"), V.Q(
                    operand(row["b"], "b").iv, V.named("voltage")))
                want = row["want"]
                self.assertEqual(
                    (got.outcome, got.certainty, got.reason, got.basis),
                    (want["outcome"], want.get("certainty"),
                     want.get("reason"), want.get("basis")))

    def test_the_vectors_reach_every_division_case_and_operation(self):
        cases = " ".join(row["case"] for row in ALGEBRA["operations"])
        for label in ("(i)", "(ii)", "(iii)", "(iv)", "(v)", "(vi)"):
            self.assertIn(f"division {label}", cases)
        self.assertEqual(
            {row["op"] for row in ALGEBRA["operations"]},
            set(OPERATIONS) | {"neg", "square", "scale"})


class RelationTest(unittest.TestCase):
    def test_certainly_and_possibly(self):
        a = V.from_literal("1V to 2V")
        b = V.from_literal("2V to 3V")
        c = V.from_literal("1.5V to 3V")
        self.assertTrue(V.certainly_le(a, b))
        self.assertFalse(V.certainly_lt(a, b))
        self.assertTrue(V.possibly_lt(a, b))
        self.assertFalse(V.certainly_le(a, c))
        self.assertTrue(V.possibly_le(c, a))
        self.assertFalse(V.possibly_le(b, V.from_literal("1V to 1.5V")))

    def test_the_verdict_never_passes_on_a_lower_bound(self):
        floor = V.Q(V.Interval(Fraction(1), V.POS_INF), V.named("current"),
                    tight=False, verified=False)
        at_most = V.Q(V.Interval(V.NEG_INF, Fraction(2)), V.named("current"))
        at_least = V.Q(V.Interval(Fraction(1, 2), V.POS_INF),
                       V.named("current"))
        self.assertEqual(V.verdict(floor, at_most),
                         V.Verdict("incomplete", reason="unverified-input"))
        # Inside, and still no pass: the floor rests on a typical figure.
        self.assertEqual(V.verdict(floor, at_least).outcome, "incomplete")
        exceeded = V.verdict(floor, V.Q(V.Interval(V.NEG_INF, Fraction(1, 2)),
                                        V.named("current")))
        self.assertEqual(exceeded, V.Verdict("fail", "definite",
                                             basis="lower-bound"))

    def test_a_window_that_depends_on_a_value_is_refused(self):
        moving = V.from_literal("3V to 3.6V", var="rail")
        with self.assertRaises(ValueError):
            V.verdict(V.from_literal("3.3V"), moving)

    def test_row_status_maps_incomplete_to_undecided(self):
        self.assertEqual(V.Verdict("pass").row_status, "pass")
        self.assertEqual(V.Verdict("fail", "possible").row_status, "fail")
        self.assertEqual(V.Verdict("incomplete",
                                   reason="interval-overestimate").row_status,
                         "undecided")


class BuckDividerTest(unittest.TestCase):
    """The worked case (plan L1c): the buck's feedback divider, R1 31.2kohm
    +/-1%, R2 10kohm +/-1% and Vref 800mV +/-1%, against vout_mean's
    3.201-3.399 V window, read from the benchmark itself."""

    @classmethod
    def setUpClass(cls):
        try:
            import lark  # noqa: F401
        except ImportError:  # pragma: no cover - exercised by absence
            raise unittest.SkipTest("lark (pinned in toolchain/versions.yaml) "
                                    "is required")
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics

        root = ROOT / "benchmarks" / "buck-3v3"
        compiled = pipeline.compile("buck-3v3.rhoform", root,
                                    sink=Diagnostics(), through="dimensions")
        cls.found = compiled.analysis.values

    def test_the_single_use_form_is_tight_and_passes(self):
        found = self.found
        vref = found.constraint("/u1", "reference_voltage")
        r1 = found.constraint("/r1", "resistance")
        r2 = found.constraint("/r2", "resistance")
        vout = vref * (V.constant(1) + r1 / r2)
        self.assertTrue(vout.tight)
        low = Fraction("0.792") * (1 + Fraction("30.888") / Fraction("10.1"))
        high = Fraction("0.808") * (1 + Fraction("31.512") / Fraction("9.9"))
        self.assertEqual((vout.iv.lo, vout.iv.hi), (low, high))
        # [3.2141, 3.3799] V at four places, rounded outward.
        self.assertTrue(Fraction("3.2141") <= low < Fraction("3.2142"))
        self.assertTrue(Fraction("3.3798") < high <= Fraction("3.3799"))
        self.assertEqual(V.display(vout), ("3.2141V", "3.37989V"))
        self.assertEqual(V.verdict(vout, found.window("/vout_mean")),
                         V.Verdict("pass"))

    def test_the_naive_form_overestimates_and_is_incomplete(self):
        found = self.found
        vref = found.constraint("/u1", "reference_voltage")
        r1 = found.constraint("/r1", "resistance")
        r2 = found.constraint("/r2", "resistance")
        vout = vref / (r2 / (r1 + r2))
        self.assertFalse(vout.tight)
        self.assertEqual(V.display(vout), ("3.19842V", "3.39622V"))
        self.assertEqual(V.verdict(vout, found.window("/vout_mean")),
                         V.Verdict("incomplete",
                                   reason="interval-overestimate"))


class ConversionTest(unittest.TestCase):
    def test_elaborated_decimals_convert_exactly(self):
        from rhoform.elaborate import Quantity

        q = V.from_quantity(Quantity(Decimal("31.2"), "kohm",
                                     (Decimal("30.888"), Decimal("31.512"))),
                            var="r1")
        self.assertEqual((q.iv.lo, q.iv.hi, q.nominal),
                         (Fraction(30888), Fraction(31512), Fraction(31200)))
        self.assertTrue(q.tight)
        point = V.from_quantity(Quantity(Decimal("0.1"), "uF"))
        self.assertEqual(point.iv, V.Interval.point(Fraction(1, 10 ** 7)))
        self.assertTrue(point.tight)
        self.assertEqual(point.vars, ())

    def test_an_uncertain_leaf_with_no_variable_is_never_tight(self):
        self.assertFalse(V.from_literal("10kohm +/- 1%").tight)
        self.assertTrue(V.from_literal("10kohm +/- 1%", var="r").tight)
        self.assertTrue(V.from_literal("0ohm +/- 5%").tight)

    def test_a_degree_reading_is_an_offset_point(self):
        q = V.from_literal("25degC +/- 2degC")
        self.assertTrue(q.offset)
        self.assertEqual((q.iv.lo, q.iv.hi), (Fraction(23), Fraction(27)))

    def test_bounds_take_unit_one_as_dimensionless_and_open_ends(self):
        from rhoform.elaborate import Bounds

        q = V.from_bounds(Bounds("1", Decimal("0.85"), None))
        self.assertEqual(q.dim, V.DIMENSIONLESS)
        self.assertEqual((q.iv.lo, q.iv.hi), (Fraction(17, 20), V.POS_INF))
        q = V.from_bounds(Bounds("mV", None, Decimal("50")))
        self.assertEqual((q.iv.lo, q.iv.hi), (V.NEG_INF, Fraction(1, 20)))

    def test_a_window_read_as_a_value_is_a_leaf_like_a_literal(self):
        from rhoform.elaborate import Bounds

        # `supply VIN within 9V to 14V` as an origin: with no variable id
        # nothing shows it is used once, so b - b, exactly 0, overlaps
        # [-1V, 1V] by overestimate and is incomplete, never fail(possible).
        b = V.from_bounds(Bounds("V", Decimal("9"), Decimal("14")))
        self.assertEqual((b.tight, b.vars), (False, ()))
        window = V.from_bounds(Bounds("V", Decimal("-1"), Decimal("1")))
        self.assertEqual(V.verdict(b - b, window),
                         V.Verdict("incomplete",
                                   reason="interval-overestimate"))
        named = V.from_bounds(Bounds("V", Decimal("9"), Decimal("14")),
                              var="vin")
        self.assertEqual((named.tight, named.vars), (True, ("vin",)))
        self.assertFalse((named - named).tight)
        point = V.from_bounds(Bounds("V", Decimal("5"), Decimal("5")))
        self.assertEqual((point.tight, point.vars), (True, ()))

    def test_a_float_is_refused_never_converted(self):
        with self.assertRaises(TypeError):
            V.exact(0.3)
        with self.assertRaises(TypeError):
            V.exact(True)
        with self.assertRaises(ValueError):
            V.exact(Decimal("NaN"))
        self.assertEqual(V.exact(Decimal("0.3")), Fraction(3, 10))


def record(path):
    from rhoform import partdata

    return partdata.parse((ROOT / path).read_bytes())


def measure_at(doc, pointer):
    """The rhoform.partdata.Measure at `pointer`, as a binding hands it
    out."""
    from rhoform import partdata

    return partdata._measures(doc, partdata.pointer_target(doc, pointer),
                              pointer)[0]


class PartDataTest(unittest.TestCase):
    """D3 honesty: only guaranteed statistics bound a quantity, a relative
    bound is factor * ref + offset exactly, and a record's 0.3 is 3/10."""

    def test_every_unit_the_records_use_parses(self):
        from rhoform import partdata

        seen = set()
        paths = sorted((ROOT / "parts" / "examples").glob("*.part.json")) \
            + sorted((ROOT / "rhoform" / "parts").rglob("*.part.json"))
        self.assertGreaterEqual(len(paths), 5)
        for path in paths:
            doc = partdata.parse(path.read_bytes())
            for _pointer, node in partdata.walk_measures(doc):
                with self.subTest(record=path.name, unit=node["unit"]):
                    V.parse_part_unit(node["unit"])
                    seen.add(node["unit"])
        # The compound and non-literal units the records really carry.
        self.assertTrue({"1", "dB", "dBm", "degC/W", "ppm/K", "min"} <= seen)

    def test_the_part_unit_grammar(self):
        cases = {
            "1": (V.DIMENSIONLESS, Fraction(1), "linear"),
            "mA": (V.named("current"), Fraction(1, 1000), "linear"),
            "degC": (V.named("temperature"), Fraction(1), "offset"),
            "K": (V.named("temperature"), Fraction(1), "linear"),
            "ppm": (V.DIMENSIONLESS, Fraction(1, 10 ** 6), "linear"),
            "min": (V.named("time"), Fraction(60), "linear"),
            "degC/W": (V.named("temperature") / V.named("power"),
                       Fraction(1), "linear"),
            "ppm/K": (V.DIMENSIONLESS / V.named("temperature"),
                      Fraction(1, 10 ** 6), "linear"),
            "dB": (V.Dimension((0, 0, 0, 0, 0), "dB"), Fraction(1),
                   "level"),
        }
        for unit, (dim, factor, kind) in cases.items():
            with self.subTest(unit=unit):
                self.assertEqual(V.parse_part_unit(unit),
                                 V.PartUnit(dim, factor, kind))
        for bad in ("Ohm", "%", "V/", "/V", "V/A/s", "dB/Hz", "1/K", ""):
            with self.subTest(unit=bad), self.assertRaises(V.UnitError):
                V.parse_part_unit(bad)

    def test_a_record_value_converts_exactly(self):
        doc = record("rhoform/parts/ti/ne555p.part.json")
        level = measure_at(doc, "/pins/4/characteristics/reset_voltage_level")
        q = V.from_measure(level, var="reset")
        self.assertEqual((q.iv.lo, q.iv.hi, q.nominal),
                         (Fraction(3, 10), Fraction(1), Fraction(7, 10)))
        self.assertTrue(q.tight)
        self.assertTrue(q.verified)

    def test_typ_and_peak_are_never_promoted(self):
        doc = record("rhoform/parts/espressif/esp32-s3-wroom-1-n8r2.part.json")
        peak = measure_at(doc, "/modes/7/draw/0/current")
        self.assertIs(V.from_measure(peak), V.UNVERIFIED)
        # As a lower bound on the worst case it can prove a limit
        # exceeded, and nothing else.
        floor = V.from_measure(peak, lower_bound_only=True)
        self.assertEqual((floor.iv.lo, floor.iv.hi),
                         (Fraction(355, 1000), V.POS_INF))
        self.assertFalse(floor.verified)
        self.assertFalse(floor.tight)
        limit = V.from_literal("300mA to 500mA")
        self.assertEqual(V.verdict(floor, V.Q(V.Interval(V.NEG_INF,
                                                         limit.iv.lo),
                                              limit.dim)),
                         V.Verdict("fail", "definite", basis="lower-bound"))
        self.assertEqual(V.verdict(floor, V.Q(V.Interval(V.NEG_INF,
                                                         limit.iv.hi),
                                              limit.dim)).outcome,
                         "incomplete")

    def test_a_typ_beside_a_guarantee_is_only_the_nominal(self):
        from rhoform import partdata

        typical = partdata.Measure("/x", "V", (
            partdata.Value("typ", Decimal("0.1"), False),
            partdata.Value("max", Decimal("0.35"), True)), {}, "datasheet")
        q = V.from_measure(typical, lower_bound_only=True)
        self.assertEqual((q.iv.lo, q.iv.hi, q.nominal),
                         (V.NEG_INF, Fraction(7, 20), Fraction(1, 10)))
        self.assertTrue(q.verified)
        self.assertFalse(q.tight)

    def test_an_unguaranteed_max_is_not_a_limit(self):
        from rhoform import partdata

        estimated = partdata.Measure("/x", "mA", (
            partdata.Value("max", Decimal("20"), False),), {}, "estimated")
        self.assertIs(V.from_measure(estimated), V.UNVERIFIED)
        self.assertIs(V.from_measure(estimated, lower_bound_only=True),
                      V.UNVERIFIED)

    def test_a_relative_bound_is_factor_times_reference_plus_offset(self):
        doc = record("rhoform/parts/espressif/esp32-s3-wroom-1-n8r2.part.json")
        vih = measure_at(doc, "/pin_classes/0/characteristics/vih")
        self.assertEqual(V.references(vih), ("3V3",))
        rail = V.from_literal("3.3V")
        q = V.from_measure(vih, {"3V3": rail})
        self.assertEqual((q.iv.lo, q.iv.hi),
                         (Fraction("0.75") * Fraction("3.3"),
                          Fraction("3.3") + Fraction("0.3")))
        self.assertFalse(q.tight)  # no variable id was given
        self.assertTrue(V.from_measure(vih, {"3V3": rail}, var="v").tight)
        # Over an uncertain rail the enclosure widens to the outer corners
        # and carries the rail's variable.
        uncertain = V.from_literal("3.3V +/- 10%", var="rail")
        q = V.from_measure(vih, {"3V3": uncertain}, var="v")
        self.assertEqual((q.iv.lo, q.iv.hi),
                         (Fraction("0.75") * Fraction("2.97"),
                          Fraction("3.63") + Fraction("0.3")))
        self.assertFalse(q.tight)
        self.assertIn("rail", q.vars)
        # One statistic alone, exactly, as a consumer comparing it at the
        # rail's own instant needs it.
        high = V.statistic(vih, "max", {"3V3": uncertain})
        self.assertEqual((high.iv.lo, high.iv.hi),
                         (Fraction("3.27"), Fraction("3.93")))
        with self.assertRaises(KeyError):
            V.from_measure(vih)
        # Over an exact rail the limit is a fixed window.
        fixed = V.from_measure(vih, {"3V3": rail})
        self.assertEqual(fixed.vars, ())
        self.assertEqual(V.verdict(V.from_literal("2.5V to 2.6V"), fixed),
                         V.Verdict("pass"))

    def test_a_limit_over_an_uncertain_reference_is_never_a_fixed_window(self):
        from rhoform.elaborate import Bounds

        doc = record("rhoform/parts/espressif/esp32-s3-wroom-1-n8r2.part.json")
        vih = measure_at(doc, "/pin_classes/0/characteristics/vih")
        signal = V.from_literal("2.5V to 2.6V")
        # A rail with no variable id: the outer enclosure [2.2275V, 3.93V]
        # holds the signal, but at 3.63V VIH's min is 2.7225V, above 2.6V.
        # It carries the rail's identity, so it is refused, never a pass.
        for rail in (V.from_literal("3.3V +/- 10%"),
                     V.from_literal("3.3V +/- 10%", var="rail")):
            window = V.from_measure(vih, {"3V3": rail})
            self.assertIn(("reference", "3V3"), window.vars)
            with self.assertRaises(ValueError):
                V.verdict(signal, window)
            with self.assertRaises(ValueError):
                V.verdict(signal, V.statistic(vih, "min", {"3V3": rail}))
        # And a 555 abs-max relative to VCC, over a `supply` window.
        doc = record("rhoform/parts/ti/ne555p.part.json")
        limit = measure_at(doc, "/pins/0/abs_max/voltage")
        supply = V.from_bounds(Bounds("V", Decimal("4.5"), Decimal("16")))
        window = V.from_measure(limit, {"VCC": supply})
        self.assertEqual((window.iv.lo, window.iv.hi), (V.NEG_INF,
                                                        Fraction(16)))
        with self.assertRaises(ValueError):
            V.verdict(V.from_bounds(Bounds("V", Decimal("0"),
                                           Decimal("12"))), window)

    def test_a_limit_over_an_unverified_reference_is_unverified(self):
        from rhoform import partdata

        doc = record("rhoform/parts/espressif/esp32-s3-wroom-1-n8r2.part.json")
        vih = measure_at(doc, "/pin_classes/0/characteristics/vih")
        rail = V.Q(V.Interval(Fraction(3), Fraction("3.6")),
                   V.named("voltage"), tight=False, verified=False)
        q = V.from_measure(vih, {"3V3": rail})
        self.assertFalse(q.verified)
        self.assertEqual(V.verdict(q, V.from_literal("0V to 5V")),
                         V.Verdict("incomplete", reason="unverified-input"))
        self.assertEqual(q.verified, V.statistic(vih, "min",
                                                 {"3V3": rail}).verified)
        # A reference resting on a typ read as a lower bound feeds a
        # relative max: the enclosure cannot pass either.
        typical = partdata.Measure("/ref", "V", (
            partdata.Value("typ", Decimal("3.3"), False),), {}, "datasheet")
        floor = V.from_measure(typical, lower_bound_only=True)
        relative = partdata.Measure("/m", "V", (
            partdata.Value("min", Decimal("0"), True),
            partdata.Value("max", partdata.Relative("REF", Decimal("1"),
                                                    Decimal("0.3")), True)),
            {}, "datasheet")
        q = V.from_measure(relative, {"REF": floor})
        self.assertEqual((q.iv.lo, q.iv.hi, q.verified),
                         (Fraction(0), V.POS_INF, False))
        self.assertEqual(
            V.verdict(q, V.Q(V.Interval(Fraction(0), V.POS_INF),
                             V.named("voltage"))),
            V.Verdict("incomplete", reason="unverified-input"))

    def test_a_relative_bound_with_no_factor_and_an_offset(self):
        doc = record("rhoform/parts/diodes/ap7361c-33e-13.part.json")
        out = measure_at(doc, "/pins/2/abs_max/voltage")
        q = V.from_measure(out, {"IN": V.from_literal("5V")})
        self.assertEqual((q.iv.lo, q.iv.hi), (V.NEG_INF, Fraction("5.3")))
        with self.assertRaises(V.DimensionError):
            V.from_measure(out, {"IN": V.from_literal("5A")})


class DisplayTest(unittest.TestCase):
    def test_a_terminating_end_is_exact_in_normal_form(self):
        self.assertEqual(V.display(V.from_literal("31.2kohm +/- 1%")),
                         ("30.888kohm", "31.512kohm"))
        self.assertEqual(V.display(V.constant(Fraction(17, 20))),
                         ("0.85", "0.85"))
        self.assertEqual(V.display(V.from_literal("25degC")),
                         ("25degC", "25degC"))
        difference = V.from_literal("25degC") - V.from_literal("20degC")
        self.assertEqual(V.display(difference), ("5K", "5K"))

    def test_a_non_terminating_end_rounds_outward(self):
        third = V.constant(Fraction(1, 3), V.named("voltage"))
        self.assertEqual(V.display(third), ("333.333mV", "333.334mV"))
        negative = V.constant(Fraction(-2, 3), V.named("current"))
        self.assertEqual(V.display(negative), ("-666.667mA", "-666.666mA"))

    def test_infinite_ends_and_params(self):
        q = V.Q(V.Interval(V.NEG_INF, Fraction(1, 20)), V.named("voltage"))
        self.assertEqual(V.params("measured", q),
                         {"measured_min": "-inf", "measured_max": "50mV"})
        derived = V.constant(2, V.named("voltage") / V.named("time"))
        self.assertEqual(V.display(derived)[0], "2 m^2*kg*s^-4*A^-1")
        with self.assertRaises(TypeError):
            V.display(V.UNDEFINED)


class DimensionTest(unittest.TestCase):
    def test_named_dimensions_compose(self):
        self.assertEqual(V.named("resistance") * V.named("capacitance"),
                         V.named("time"))
        self.assertEqual(V.named("voltage") * V.named("current"),
                         V.named("power"))
        self.assertEqual(V.named("voltage") / V.named("resistance"),
                         V.named("current"))
        self.assertEqual(V.named("inductance") / V.named("resistance"),
                         V.named("time"))
        self.assertEqual(V.named("frequency") * V.named("time"),
                         V.DIMENSIONLESS)

    def test_names_and_descriptions(self):
        self.assertEqual(V.named("inductance").describe(), "an inductance")
        self.assertEqual(V.DIMENSIONLESS.describe(),
                         "a dimensionless number")
        self.assertIsNone((V.named("voltage") ** 3).name)

    def test_the_restated_tables_are_the_modules(self):
        from rhoform import quantities

        self.assertEqual([row[0] for row in V.dimension_rows()],
                         list(quantities.DIMENSIONS))
        self.assertEqual([row[0] for row in V.atom_rows()],
                         list(V.PART_ATOMS))
        self.assertEqual(V.INCOMPLETE_REASONS,
                         ("interval-overestimate", "undefined-value",
                          "unverified-input"))


def _random_interval(rng, dim, var):
    lo = Fraction(rng.randint(-40, 40), rng.randint(1, 8))
    width = Fraction(rng.randint(0, 40), rng.randint(1, 8))
    iv = V.Interval(lo, lo + width)
    nominal = lo + width * Fraction(rng.randint(0, 4), 4)
    return V.Q(iv, dim, False, nominal, iv.is_point or var is not None,
               () if var is None or iv.is_point else (var,))


def _evaluate(tree, point):
    kind = tree[0]
    if kind == "leaf":
        return point[tree[1]]
    left = _evaluate(tree[1], point)
    if kind == "square":
        return left * left
    right = _evaluate(tree[2], point)
    if kind == "add":
        return left + right
    if kind == "sub":
        return left - right
    if kind == "mul":
        return left * right
    if right == 0:
        raise ZeroDivisionError
    return left / right


def _compute(tree, leaves):
    kind = tree[0]
    if kind == "leaf":
        return leaves[tree[1]]
    left = _compute(tree[1], leaves)
    if kind == "square":
        return V.square(left)
    return {"add": V.add, "sub": V.sub, "mul": V.mul,
            "div": V.div}[kind](left, _compute(tree[2], leaves))


def _tree(rng, names, depth, ops):
    if depth == 0 or rng.random() < 0.3:
        return ("leaf", rng.choice(names))
    op = rng.choice(ops)
    if op == "square":
        return ("square", _tree(rng, names, depth - 1, ops))
    return (op, _tree(rng, names, depth - 1, ops),
            _tree(rng, names, depth - 1, ops))


class PropertyTest(unittest.TestCase):
    """Seeded (SEED) random expressions over random intervals. Soundness:
    every point evaluation lies in the computed enclosure. Nominal
    containment: the nominal, computed by the same point operations, lies
    inside too (Q refuses one that does not). Tightness: a tight result's
    ends are attained, at corners of the box, exactly."""

    ROUNDS = 400

    def test_soundness_and_nominal_containment(self):
        rng = random.Random(SEED)
        names = ("x", "y", "z")
        for round_number in range(self.ROUNDS):
            leaves = {name: _random_interval(rng, V.DIMENSIONLESS, name)
                      for name in names}
            tree = _tree(rng, names, 3,
                         ("add", "sub", "mul", "div", "square"))
            result = _compute(tree, leaves)
            if result is V.UNDEFINED:
                continue
            nominals = {name: q.nominal for name, q in leaves.items()}
            if result.nominal is not None:
                self.assertTrue(result.iv.contains(result.nominal))
                try:
                    self.assertEqual(_evaluate(tree, nominals),
                                     result.nominal, (round_number, tree))
                except ZeroDivisionError:
                    pass
            for _sample in range(8):
                point = {name: q.iv.lo + (q.iv.hi - q.iv.lo)
                         * Fraction(rng.randint(0, 6), 6)
                         for name, q in leaves.items()}
                try:
                    value = _evaluate(tree, point)
                except ZeroDivisionError:
                    continue
                self.assertTrue(result.iv.contains(value),
                                (round_number, tree, point, value,
                                 result.iv))

    def test_a_tight_result_is_the_exact_range(self):
        rng = random.Random(SEED + 1)
        checked = 0
        for round_number in range(self.ROUNDS):
            names = [f"v{i}" for i in range(4)]
            leaves = {name: _random_interval(rng, V.DIMENSIONLESS, name)
                      for name in names}
            # Single use: each leaf at most once, so the result may be tight.
            used = rng.sample(names, rng.randint(1, len(names)))

            def single(part):
                if len(part) == 1:
                    return ("leaf", part[0])
                split = rng.randint(1, len(part) - 1)
                return (rng.choice(("add", "sub", "mul", "div")),
                        single(part[:split]), single(part[split:]))

            tree = single(used)
            result = _compute(tree, leaves)
            if result is V.UNDEFINED or not result.tight \
                    or not result.iv.bounded:
                continue
            corners = [{}]
            for name in used:
                q = leaves[name]
                corners = [dict(c, **{name: e}) for c in corners
                           for e in (q.iv.lo, q.iv.hi)]
            seen = [_evaluate(tree, corner) for corner in corners]
            self.assertEqual((min(seen), max(seen)),
                             (result.iv.lo, result.iv.hi),
                             (round_number, tree))
            checked += 1
        self.assertGreater(checked, self.ROUNDS // 4)

    def test_repeating_a_variable_drops_tightness(self):
        rng = random.Random(SEED + 2)
        for _ in range(100):
            x = _random_interval(rng, V.DIMENSIONLESS, "x")
            if x.iv.is_point:
                continue
            for op in (V.add, V.sub, V.mul):
                self.assertFalse(op(x, x).tight)
            self.assertTrue(V.square(x).tight)


if __name__ == "__main__":
    unittest.main()
