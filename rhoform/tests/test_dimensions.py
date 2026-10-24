"""The dimensions pass (rhoform/check/dimensions.py, spec 05 section 2):
constraint dimensions (RHO3202), assertion-bound dimensions (RHO3203), the
T4 exact-value lint (RHO3201), the rows it writes and the enclosures it
leaves in `analysis.values` -- and, on the benchmarks, none of its codes.

Every run here stops after the pass (`through`), so its stream is the
pass's own and moves with no other pass's landing.
"""

import importlib.util
import json
import shutil
import tempfile
import unittest
from collections import Counter
from fractions import Fraction
from pathlib import Path

try:
    import lark  # noqa: F401 - availability probe only
    HAVE_LARK = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_LARK = False

ROOT = Path(__file__).resolve().parents[2]
SKIP = "lark (pinned in toolchain/versions.yaml) is required"


def compile_text(directory: Path, text: str):
    """(diagnostic lines, Compilation) of `text`, its own compile root,
    checked through the dimensions pass."""
    from rhoform import compile as pipeline
    from rhoform.diagnostics import Diagnostics

    (directory / "main.rhoform").write_text(text, encoding="utf-8")
    sink = Diagnostics()
    compiled = pipeline.compile("main.rhoform", directory, sink=sink,
                                through="dimensions")
    return [json.loads(line) for line in sink.render().splitlines()], \
        compiled


def grammar_vocabulary(name: str) -> tuple:
    spec = importlib.util.spec_from_file_location(
        "_sot_dimensions", ROOT / "lang" / "grammar" / "rhoform_syntax.py")
    sot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sot)
    return tuple(sot.CLOSED_VOCABULARIES[name])


class TableTest(unittest.TestCase):
    def test_every_measurement_kind_has_its_dimensions_in_order(self):
        from rhoform.check.dimensions import MEASUREMENT_DIMENSIONS

        self.assertEqual(tuple(MEASUREMENT_DIMENSIONS),
                         grammar_vocabulary("measurement_kind"))

    def test_the_tables_name_only_real_dimensions_and_kinds(self):
        from rhoform import quantities
        from rhoform.check.dimensions import (
            CONSTRAINT_KINDS, CONSTRAINT_VOCABULARY, MEASUREMENT_DIMENSIONS,
        )

        words = set(quantities.DIMENSIONS) | {"dimensionless"}
        for allowed in MEASUREMENT_DIMENSIONS.values():
            self.assertTrue(set(allowed) <= words, allowed)
            self.assertEqual(len(set(allowed)), len(allowed))
        for name, (dimension, kind) in CONSTRAINT_VOCABULARY.items():
            self.assertIn(dimension, quantities.DIMENSIONS, name)
            self.assertIn(kind, CONSTRAINT_KINDS, name)
        # D22: what the static tier's current rule needs.
        self.assertEqual(MEASUREMENT_DIMENSIONS["operating_point"],
                         ("voltage", "current"))
        self.assertEqual(MEASUREMENT_DIMENSIONS["overshoot"],
                         ("dimensionless", "voltage"))

    def test_the_rows_the_pass_writes_are_its_row_table(self):
        import re

        from rhoform.check import dimensions
        from rhoform.check.report import STATUSES

        source = Path(dimensions.__file__).read_text(encoding="utf-8")
        written = set(re.findall(
            r'report\.row\(\s*path,\s*"([a-z-]+)",\s*"([a-z-]+)"', source))
        self.assertEqual(written, set(dimensions.ROWS))
        for status, _reason in dimensions.ROWS:
            self.assertIn(status, STATUSES)

    def test_the_codes_are_the_owners_and_say_what_they_take(self):
        from rhoform import codes

        for code, severity, waivable in (("RHO3201", "warning", False),
                                         ("RHO3202", "error", False),
                                         ("RHO3203", "error", False)):
            entry = codes.lookup(code)
            self.assertEqual(codes.owner_of(code), "quantities")
            self.assertEqual((entry.severity, entry.waivable),
                             (severity, waivable))
        self.assertEqual(codes.lookup("RHO3203").params,
                         codes.lookup("RHO2038").params)


@unittest.skipUnless(HAVE_LARK, SKIP)
class BenchmarkTest(unittest.TestCase):
    """AC2 precision: the benchmarks as authored draw nothing from this
    pass -- 53 exact rating constraints and the `0ohm +/- 5%` jumpers are
    not flagged, and every assertion bound fits its measurement."""

    @classmethod
    def setUpClass(cls):
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics

        cls.runs = {}
        for root in sorted((ROOT / "benchmarks").iterdir()):
            sink = Diagnostics()
            compiled = pipeline.compile(root.name + ".rhoform", root,
                                        sink=sink, through="dimensions")
            cls.runs[root.name] = (sink, compiled)

    def test_no_quantities_code_and_no_row(self):
        for name, (sink, compiled) in self.runs.items():
            with self.subTest(benchmark=name):
                self.assertEqual([d.code for d in sink
                                  if d.code.startswith("RHO32")], [])
                self.assertEqual(
                    compiled.report.sections["dimensions"]["rows"], [])

    def test_the_exact_ratings_and_the_jumpers_are_read_not_flagged(self):
        from rhoform.check.dimensions import CONSTRAINT_VOCABULARY

        exact = Counter()
        jumpers = []
        for name, (_sink, compiled) in self.runs.items():
            design = compiled.design
            found = compiled.analysis.values
            for instance in design.instances:
                part = instance.part
                if part is None:
                    continue
                for constraint, site in part.sites.items():
                    if site.form is None:
                        continue
                    q = found.constraint(instance.path, constraint)
                    self.assertIsNotNone(q, (instance.path, constraint))
                    self.assertIn(constraint, CONSTRAINT_VOCABULARY)
                    if site.form == "exact":
                        exact[name] += 1
                        self.assertNotEqual(
                            CONSTRAINT_VOCABULARY[constraint][1], "nominal")
                    if q.iv.is_point and site.form != "exact":
                        jumpers.append((name, instance.path, constraint))
        self.assertEqual(dict(exact), {"blinker-555": 7, "buck-3v3": 27,
                                       "esp32s3-devboard": 19})
        self.assertEqual(jumpers, [
            ("esp32s3-devboard", "/r11", "resistance"),
            ("esp32s3-devboard", "/r12", "resistance")])

    def test_all_seven_bounds_fit_their_measurements(self):
        windows = {}
        for name, (_sink, compiled) in self.runs.items():
            for assertion in compiled.design.assertions:
                window = compiled.analysis.values.window(assertion.path)
                self.assertIsNotNone(window, assertion.path)
                windows[(name, assertion.measurement)] = window.dim.name
        self.assertEqual(windows, {
            ("blinker-555", "duty_cycle"): "dimensionless",
            ("blinker-555", "frequency"): "frequency",
            ("buck-3v3", "efficiency"): "dimensionless",
            ("buck-3v3", "overshoot"): "dimensionless",
            ("buck-3v3", "operating_point"): "voltage",
            ("buck-3v3", "ripple"): "voltage",
            ("buck-3v3", "settling_time"): "time",
        })


@unittest.skipUnless(HAVE_LARK, SKIP)
class PassTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rhoform-dimensions-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_pass(self, body: str, header: str = ""):
        text = "#pragma rhoform-syntax 0.2\n\n" + header + \
            "module Board:\n    port vin power_in\n" + body + \
            "    net VIN:\n        vin\n"
        lines, compiled = compile_text(self.tmp, text)
        self.assertIsNotNone(compiled.report, lines)
        return lines, compiled

    def test_a_clean_design_draws_nothing_and_leaves_its_enclosures(self):
        lines, compiled = self.run_pass(
            "    r1 = new rhoform.lib.passive.Resistor:\n"
            "        part abstract:\n"
            "            resistance = 10kohm +/- 1%\n"
            "            power_rating = 100mW\n"
            "    r2 = new rhoform.lib.passive.Resistor:\n"
            "        part abstract:\n"
            "            resistance = 0ohm +/- 5%\n"
            "    assert vin_ok static operating_point(VIN) within 1A to 2A\n"
            "    assert vin_os dynamic overshoot(VIN) at most 50mV\n"
            "    assert vin_ri dynamic ripple(VIN) at most 5mA\n")
        self.assertEqual(lines, [])
        found = compiled.analysis.values
        r1 = found.constraint("/r1", "resistance")
        self.assertEqual((r1.iv.lo, r1.iv.hi), (Fraction(9900),
                                                Fraction(10100)))
        self.assertEqual(r1.vars, (("/r1", "resistance"),))
        self.assertTrue(r1.tight)
        self.assertEqual(found.constraint("/r1", "power_rating").iv.lo,
                         Fraction(1, 10))
        self.assertEqual(found.window("/vin_ok").iv.hi, Fraction(2))
        self.assertIsNone(found.constraint("/r1", "mpn"))

    def test_an_exact_nominal_on_an_abstract_part_is_the_lint(self):
        lines, compiled = self.run_pass(
            "    r1 = new rhoform.lib.passive.Resistor:\n"
            "        part abstract:\n"
            "            resistance = 10kohm\n"
            "            voltage_rating = 50V\n")
        self.assertEqual([(d["code"], d["severity"], d["entity"])
                          for d in lines],
                         [("RHO3201", "warning", "/r1")])
        found = lines[0]
        self.assertEqual(found["params"], {"constraints": ["resistance"],
                                           "values": ["10kohm"]})
        span = found["spans"][0]
        fixit = found["fixits"][0]
        self.assertEqual(fixit["applicability"], "has-placeholders")
        self.assertEqual(fixit["placeholders"], ["tolerance"])
        self.assertEqual(
            [(e["byte_start"], e["byte_end"], e["replacement"])
             for e in fixit["edits"]],
            [(span["byte_end"], span["byte_end"], " +/- <tolerance>")])
        # Applied with a tolerance, the fix leaves nothing to report.
        text = (self.tmp / "main.rhoform").read_bytes()
        fixed = text[:span["byte_end"]] + b" +/- 1%" + text[span["byte_end"]:]
        lines, _compiled = compile_text(self.tmp, fixed.decode())
        self.assertEqual(lines, [])
        rows = _compiled.report.sections["dimensions"]["rows"]
        self.assertEqual(rows, [])

    def test_the_lint_reports_a_value_in_normal_form(self):
        lines, _compiled = self.run_pass(
            "    r1 = new rhoform.lib.passive.Resistor:\n"
            "        part abstract:\n"
            "            resistance = 10000ohm\n")
        self.assertEqual([(d["code"], d["entity"], d["params"]["values"])
                          for d in lines], [("RHO3201", "/r1", ["10kohm"])])

    def test_the_lint_reads_the_authored_form_and_the_binding(self):
        header = ("module Divider(r: resistance = 10kohm):\n"
                  "    port top passive\n"
                  "    r1 = new rhoform.lib.passive.Resistor:\n"
                  "        part abstract:\n"
                  "            resistance = r\n"
                  "    top ~ r1.a\n\n")
        lines, compiled = self.run_pass(
            "    d = new Divider\n"
            "    vin ~ d.top\n"
            "    c1 = new rhoform.lib.passive.Capacitor:\n"
            "        part \"c-100n\":\n"
            "            capacitance = 100nF\n"
            "    c2 = new rhoform.lib.passive.Capacitor:\n"
            "        part abstract:\n"
            "            capacitance = 100nF\n"
            "            voltage_rating = 16V\n"
            "    l1 = new acme.passive.Inductor:\n"
            "        pin a passive 1\n"
            "        pin b passive 2\n"
            "        part abstract:\n"
            "            inductance = 4.7uH\n"
            "            reference_voltage = 800mV\n"
            "            dcr_max = 50mohm\n",
            header)
        # The resolved part's missing pick is the parts pass's (RHO6001).
        by_entity = {d["entity"]: d for d in lines
                     if d["code"].startswith("RHO32")}
        self.assertEqual(sorted(by_entity), ["/c2", "/d/r1", "/l1"])
        # A reference has the form of its value, and the finding names the
        # value, not the parameter; there is no literal here to fix.
        self.assertEqual(by_entity["/d/r1"]["params"]["values"], ["10kohm"])
        self.assertEqual(by_entity["/d/r1"]["fixits"], [])
        # Two on one instance are one finding, in name order.
        l1 = by_entity["/l1"]
        self.assertEqual(l1["params"], {
            "constraints": ["inductance", "reference_voltage"],
            "values": ["4.7uH", "800mV"]})
        self.assertEqual(len(l1["fixits"][0]["edits"]), 2)
        self.assertEqual([s["label"] for s in l1["spans"]],
                         [None, "`reference_voltage` too"])
        # A resolved part is not linted.
        self.assertNotIn("/c1", by_entity)
        rows = compiled.report.sections["dimensions"]["rows"]
        self.assertEqual(sorted({(r.entity, r.status, r.reason, r.actionable)
                                 for r in rows}),
                         [("/c2", "fail", "exact-part-constraint", False),
                          ("/d/r1", "fail", "exact-part-constraint", False),
                          ("/l1", "fail", "exact-part-constraint", False)])

    def test_a_reused_literal_is_one_finding_about_no_single_instance(self):
        header = ("module Cell:\n"
                  "    port top passive\n"
                  "    r1 = new rhoform.lib.passive.Resistor:\n"
                  "        part abstract:\n"
                  "            resistance = 1kohm\n"
                  "    top ~ r1.a\n\n")
        lines, _compiled = self.run_pass(
            "    a = new Cell\n    b = new Cell\n"
            "    vin ~ a.top\n    vin ~ b.top\n", header)
        self.assertEqual([(d["code"], d["entity"]) for d in lines],
                         [("RHO3201", None)])

    def test_a_vocabulary_name_of_another_dimension_is_an_error(self):
        lines, compiled = self.run_pass(
            "    r1 = new rhoform.lib.passive.Resistor:\n"
            "        part abstract:\n"
            "            resistance = 10uF +/- 10%\n"
            "            voltage_rating = \"50V\"\n"
            "            power_rating = 100mW\n")
        self.assertEqual([(d["code"], d["entity"]) for d in lines],
                         [("RHO3202", "/r1")])
        self.assertEqual(lines[0]["params"], {
            "constraints": ["resistance", "voltage_rating"],
            "values": ["10uF +/- 10%", "\"50V\""],
            "found": ["a capacitance", "a string"],
            "expected": ["a resistance", "a voltage"]})
        found = compiled.analysis.values
        # The earliest pass that sees a defect reports it; no later pass
        # reads the value it reported.
        self.assertIsNone(found.constraint("/r1", "resistance"))
        self.assertIsNotNone(found.constraint("/r1", "power_rating"))
        rows = compiled.report.sections["dimensions"]["rows"]
        self.assertEqual([(r.status, r.reason, dict(r.detail)) for r in rows],
                         [("fail", "constraint-dimension-mismatch",
                           {"constraints": ("resistance",
                                            "voltage_rating")})])

    def test_a_bound_its_measurement_does_not_admit_is_an_error(self):
        lines, compiled = self.run_pass(
            "    assert a_power dynamic operating_point(VIN) within 1W to 2W\n"
            "    assert b_eff dynamic efficiency(VIN) at least 85W\n"
            "    assert c_ripple dynamic ripple(VIN) at most 0.05\n"
            "    assert d_ok dynamic overshoot(VIN) at most 0.05\n")
        self.assertEqual(
            [(d["code"], d["entity"], d["params"]) for d in lines],
            [("RHO3203", "/a_power",
              {"value": "within 1W to 2W", "found": "a power",
               "context": "the bound of an `operating_point` assertion",
               "expected": "a voltage or a current"}),
             ("RHO3203", "/b_eff",
              {"value": "at least 85W", "found": "a power",
               "context": "the bound of an `efficiency` assertion",
               "expected": "a dimensionless number"}),
             ("RHO3203", "/c_ripple",
              {"value": "at most 0.05", "found": "a dimensionless number",
               "context": "the bound of a `ripple` assertion",
               "expected": "a voltage or a current"})])
        found = compiled.analysis.values
        self.assertIsNone(found.window("/a_power"))
        self.assertIsNotNone(found.window("/d_ok"))

    def test_a_name_outside_the_vocabulary_is_an_inherent_row(self):
        lines, compiled = self.run_pass(
            "    u1 = new acme.ic.Sensor:\n"
            "        pin vdd power_in 1\n"
            "        part abstract:\n"
            "            mpn = \"ACME-1\"\n"
            "            supply = 3.3V +/- 5%\n"
            "            window = 9.5mA (8mA to 10.5mA)\n"
            "    vin ~ u1.vdd\n")
        self.assertEqual(lines, [])
        rows = compiled.report.sections["dimensions"]["rows"]
        self.assertEqual(
            [(r.entity, r.status, r.reason, r.actionable, dict(r.detail))
             for r in rows],
            [("/u1", "not-run", "constraint-outside-vocabulary", False,
              {"constraints": ("supply", "window")})])
        # Unchecked, but still a value a later pass can read.
        self.assertIsNotNone(compiled.analysis.values.constraint("/u1",
                                                                 "supply"))


if __name__ == "__main__":
    unittest.main()
