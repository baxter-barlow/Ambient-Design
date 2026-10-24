"""The parts pass (rhoform.check.parts, L2b / AMB-59): picks, record
verification, binding, the constraint-satisfaction subset, staleness, what
later passes read, and the check context's route to the pass.

spec/language/05-static-types/09-part-data.md is the normative text, and
the conformance suite's `parts` area pins one case per code; this file
holds the pass to what its streams cannot show -- the facts it hands on,
the rows it writes, that a fix-it it offers is right, and that one broken
pick shared by several instances is one finding. Every test compiles, so
each skips without lark and jsonschema.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import lark  # noqa: F401 - availability probe only
    import jsonschema  # noqa: F401 - availability probe only
    HAVE_PINS = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_PINS = False

from rhoform import lockfile

ROOT = Path(__file__).resolve().parents[2]
PARTS = ROOT / "spec" / "conformance" / "check" / "parts"
SKIP = "lark and jsonschema (pinned in toolchain/versions.yaml) are required"
P2 = "#pragma rhoform-syntax 0.2\n"

WIDGET = (P2 + "\ncomponent Widget:\n    pin gnd_vcc power_in 3\n"
          "    pin in input 1\n    pin out output 2\n\nmodule Board:\n"
          "    port vin power_in\n    port x input\n    port y output\n"
          "{members}    vin ~ w.gnd_vcc\n    x ~ w.in\n    w.out ~ y\n")
ONE_WIDGET = '    w = new Widget:\n        part "acme/widget"\n'


def apply(data: bytes, fixit: dict) -> bytes:
    """`data` with a fix-it's edits applied, last first."""
    for edit in sorted(fixit["edits"], key=lambda e: -e["byte_start"]):
        data = data[:edit["byte_start"]] + edit["replacement"].encode() \
            + data[edit["byte_end"]:]
    return data


@unittest.skipUnless(HAVE_PINS, SKIP)
class _Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rhoform-parts-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def case(self, name: str) -> Path:
        """A conformance case of the parts area, copied to a root of its
        own."""
        source = next(PARTS.glob(f"*/{name}"))
        root = Path(tempfile.mkdtemp(dir=self.tmp)) / name
        shutil.copytree(source, root)
        return root

    def check(self, root: Path, through="parts"):
        """(diagnostics as dicts, Compilation) through the check stage."""
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics

        sink = Diagnostics()
        compiled = pipeline.compile("main.rhoform", root, sink=sink,
                                    through=through)
        return [json.loads(line) for line in sink.render().splitlines()], \
            compiled

    def rows(self, compiled, section="parts") -> dict:
        """{(entity, reason): row} of one section of the check report."""
        return {(row.entity, row.reason): row for row in
                compiled.report.sections[section]["rows"]}


class FactsTest(_Case):
    def test_a_bound_pick_hands_on_its_record_joined_to_the_definition(self):
        found, compiled = self.check(self.case("c01_keyed_pick_bound"))
        self.assertEqual(found, [])
        facts = compiled.analysis.parts.facts("/w")
        self.assertEqual((facts.source, facts.part_id, facts.record),
                         ("d3", "acme/widget", "parts/acme/widget.part.json"))
        self.assertEqual(sorted(facts.binding.ports), ["gnd_vcc", "in", "out"])
        self.assertEqual(facts.binding.ports["out"].pin, "OUT")
        data = (PARTS / "accept" / "c01_keyed_pick_bound" /
                facts.record).read_bytes()
        self.assertEqual(facts.revision, lockfile.digest(data))
        row = self.rows(compiled)[("/w", "bound")]
        self.assertEqual((row.status, row.actionable), ("pass", False))
        self.assertEqual(dict(row.detail)["pick"], "keyed")

    def test_an_instance_pick_and_an_unlocked_part(self):
        _found, compiled = self.check(self.case("c02_instance_pick_satisfied"))
        facts = compiled.analysis.parts.facts("/r1")
        self.assertEqual((facts.source, facts.part_id), ("d3", "acme/r10k"))
        self.assertIn("resistance", facts.constraints)
        _found, compiled = self.check(self.case("c03_unlocked_parts"))
        facts = compiled.analysis.parts.facts("/r1")
        self.assertEqual((facts.source, facts.binding), ("constraints", None))
        rows = self.rows(compiled)
        self.assertEqual(dict(rows[("/r1", "no-pick")].detail),
                         {"lockfile": "no-lockfile"})
        self.assertEqual(rows[("/mh", "hardware")].status, "not-run")
        self.assertEqual(rows[("/probe", "no-part-statement")].status,
                         "no-data")
        self.assertFalse(any(row.actionable for row in rows.values()))
        self.assertIsNone(compiled.analysis.parts.facts("/probe"))

    def test_a_net_tie_is_d1_exempt(self):
        root = self.tmp / "tie"
        root.mkdir()
        (root / "main.rhoform").write_text(
            "#pragma rhoform-syntax 0.3\n\ncomponent Tie:\n"
            "    pin a passive 1\n    pin b passive 2\n    tie a b\n\n"
            "module Board:\n    port p passive\n    port q passive\n"
            "    t = new Tie\n    p ~ t.a\n    t.b ~ q\n")
        found, compiled = self.check(root)
        self.assertEqual(found, [])
        self.assertEqual(self.rows(compiled)[("/t", "net-tie")].status,
                         "not-run")

    def test_require_rows_and_their_section(self):
        _found, compiled = self.check(self.case("c03_unlocked_parts"))
        analysis, report = compiled.analysis.parts, compiled.report
        report.open("domains", "domains", False)
        facts = analysis.require("/r1", "abs_max", "domains")
        self.assertEqual(facts.source, "constraints")
        self.assertIsNone(analysis.require("/probe", "abs_max", "domains"))
        rows = self.rows(compiled, "domains")
        self.assertTrue(rows[("/r1", "part-data-unresolved")].actionable)
        self.assertEqual(dict(rows[("/r1", "part-data-unresolved")].detail),
                         {"field": "abs_max"})
        with self.assertRaises(AssertionError):
            analysis.require("/r1", "abs_max", "budget")
        _found, compiled = self.check(self.case("c15_record_hash_mismatch"))
        analysis, report = compiled.analysis.parts, compiled.report
        self.assertIsNone(analysis.facts("/w"))
        report.open("domains", "domains", False)
        self.assertIsNone(analysis.require("/w", "abs_max", "domains"))
        row = self.rows(compiled, "domains")[("/w", "upstream-defect")]
        self.assertFalse(row.actionable)
        _found, compiled = self.check(self.case("c01_keyed_pick_bound"))
        compiled.report.open("domains", "domains", False)
        self.assertEqual(compiled.analysis.parts.require(
            "/w", "abs_max", "domains").source, "d3")
        self.assertEqual(compiled.report.sections["domains"]["rows"], [])

    def test_the_tables_spec_09_restates_are_the_codes_and_rows(self):
        from rhoform.check import parts
        from rhoform.check.report import STATUSES
        from rhoform.codeset.parts import CODES

        self.assertEqual([row[0] for row in parts.code_rows()],
                         [entry.code for entry in CODES])
        for status, reason, kind in parts.ROWS + parts.REQUIRE_ROWS:
            self.assertIn(status, STATUSES)
            self.assertIn(kind, ("actionable", "inherent"))
        self.assertEqual(len({row[1] for row in parts.ROWS}),
                         len(parts.ROWS))
        self.assertTrue(all(not entry.waivable for entry in CODES))

    def test_each_subset_home_is_where_the_d3_vocabulary_puts_its_kind(self):
        # A nominal is a defining value and a rating an operating rating
        # (spec 05/09 9.5); the limit names each say what they limit.
        from rhoform.check import parts
        from rhoform.check.dimensions import CONSTRAINT_VOCABULARY

        self.assertLessEqual(set(parts.HOMES), set(CONSTRAINT_VOCABULARY))
        for name, home in parts.HOMES.items():
            kind = CONSTRAINT_VOCABULARY[name][1]
            with self.subTest(name=name):
                if kind == "at_least":
                    self.assertEqual(home, ("ratings", "recommended", name))
                elif kind == "nominal":
                    self.assertEqual(home, ("parameters", name))
                else:
                    self.assertEqual(home[0], "parameters")
        self.assertEqual(
            sorted(set(CONSTRAINT_VOCABULARY) - set(parts.HOMES)),
            ["dcr_max", "supply_max", "vds_max"])


class RecordTest(_Case):
    def test_the_hash_fixit_re_pins_and_then_the_pick_binds(self):
        root = self.case("c15_record_hash_mismatch")
        found, _compiled = self.check(root)
        self.assertEqual([d["code"] for d in found], ["RHO6004"])
        lock = root / "rhoform.lock"
        lock.write_bytes(apply(lock.read_bytes(), found[0]["fixits"][0]))
        found, compiled = self.check(root)
        self.assertEqual(found, [])
        self.assertEqual(compiled.analysis.parts.facts("/w").source, "d3")

    def test_the_stale_fixit_re_pins_and_then_the_pick_binds(self):
        root = self.case("c26_pick_stale")
        found, _compiled = self.check(root)
        self.assertEqual([d["code"] for d in found], ["RHO6011"])
        lock = root / "rhoform.lock"
        lock.write_bytes(apply(lock.read_bytes(), found[0]["fixits"][0]))
        found, compiled = self.check(root)
        self.assertEqual(found, [])

    def test_a_record_that_is_no_json_says_so_in_fixed_words(self):
        from rhoform.check.parts import NOT_JSON

        root = self.case("c01_keyed_pick_bound")
        record = root / "parts" / "acme" / "widget.part.json"
        record.write_bytes(b'{"part_id": "acme/widget",}\n')
        lock = json.loads((root / "rhoform.lock").read_bytes())
        lock["parts"]["inputs"][0]["sha256"] = lockfile.digest(
            record.read_bytes())
        (root / "rhoform.lock").write_bytes(lockfile.canonical_bytes(lock))
        found, _compiled = self.check(root)
        self.assertEqual([(d["code"], d["params"]["problems"])
                          for d in found],
                         [("RHO6006", [f"json at /: {NOT_JSON}"])])

    def test_a_version_no_integer_or_a_record_no_object_is_rho6005(self):
        # Neither crashes the pass: a record need not be an object, and a
        # version written with a fraction or an exponent is a Decimal.
        source = self.case("c01_keyed_pick_bound")
        record = source / "parts" / "acme" / "widget.part.json"
        data = record.read_bytes()
        for written, declared in (
                (b"null\n", "missing"), (b"5\n", "missing"),
                (b'"schema_version"\n', "missing"), (b"[]\n", "missing"),
                (data.replace(b'"schema_version": 1,',
                              b'"schema_version": 1.0,'),
                 "1.0 (written with a fraction or an exponent)"),
                (data.replace(b'"schema_version": 1,',
                              b'"schema_version": 1.5,'),
                 "1.5 (written with a fraction or an exponent)"),
                (data.replace(b'"schema_version": 1,',
                              b'"schema_version": 1e0,'),
                 "1 (written with a fraction or an exponent)")):
            with self.subTest(written=written[:40]):
                root = Path(tempfile.mkdtemp(dir=self.tmp)) / "case"
                shutil.copytree(source, root)
                (root / "parts" / "acme" / "widget.part.json").write_bytes(
                    written)
                lock = json.loads((root / "rhoform.lock").read_bytes())
                lock["parts"]["inputs"][0]["sha256"] = lockfile.digest(
                    written)
                (root / "rhoform.lock").write_bytes(
                    lockfile.canonical_bytes(lock))
                found, _compiled = self.check(root)
                self.assertEqual([(d["code"], d["params"]["version"])
                                  for d in found], [("RHO6005", declared)])

    def test_one_broken_pick_several_instances_use_is_one_finding(self):
        root = self.case("c15_record_hash_mismatch")
        (root / "main.rhoform").write_text(WIDGET.format(
            members=ONE_WIDGET + '    w2 = new Widget:\n'
            '        part "acme/widget"\n') + "    isolated w2.gnd_vcc\n"
            "    isolated w2.in\n    isolated w2.out\n")
        found, compiled = self.check(root)
        self.assertEqual([(d["code"], d["entity"]) for d in found],
                         [("RHO6004", None)])
        rows = self.rows(compiled)
        self.assertIn(("/w", "record-hash-mismatch"), rows)
        self.assertIn(("/w2", "record-hash-mismatch"), rows)

    def test_a_record_is_read_once_whatever_shares_it(self):
        root = self.case("c01_keyed_pick_bound")
        (root / "main.rhoform").write_text(WIDGET.format(
            members=ONE_WIDGET + '    w2 = new Widget:\n'
            '        part "acme/widget"\n') + "    isolated w2.gnd_vcc\n"
            "    isolated w2.in\n    isolated w2.out\n")
        from rhoform import partdata

        with mock.patch.object(partdata, "check",
                               wraps=partdata.check) as checked:
            found, _compiled = self.check(root)
        self.assertEqual(found, [])
        self.assertEqual(checked.call_count, 1)

    def test_l21_holds_the_bundled_store_and_not_a_compile_roots_record(self):
        # The same acme record, compile-root-relative, binds (c01); named
        # as a store record it is held to the vendor list, which has no
        # acme, so it is refused.
        root = self.case("c01_keyed_pick_bound")
        data = (root / "parts" / "acme" / "widget.part.json").read_bytes()
        store = self.tmp / "toolchain"
        record = store / "rhoform" / "parts" / "acme" / "widget.part.json"
        record.parent.mkdir(parents=True)
        record.write_bytes(data)
        path = "rhoform/parts/acme/widget.part.json"
        document = json.loads((root / "rhoform.lock").read_bytes())
        document["parts"]["inputs"][0]["path"] = path
        document["parts"]["entries"][0]["record"] = path
        (root / "rhoform.lock").write_bytes(
            lockfile.canonical_bytes(document))
        with mock.patch.object(lockfile, "TOOLCHAIN", store):
            found, _compiled = self.check(root)
        self.assertEqual([d["code"] for d in found], ["RHO6006"])
        self.assertTrue(all(problem.startswith("L21 ")
                            for problem in found[0]["params"]["problems"]))

    def test_a_bundled_store_record_is_read_from_the_toolchain(self):
        # The NE555 record, picked for the library's Ne555 by the path the
        # toolchain bundles it at. Only that it is located, hashed and read
        # is pinned here: whether it binds is the store's and the
        # library's (test_partdata.py), and moves when they do.
        record = ROOT / "rhoform" / "parts" / "ti" / "ne555p.part.json"
        data = record.read_bytes()
        document = json.loads(data)
        root = self.tmp / "ne555"
        root.mkdir()
        (root / "main.rhoform").write_text(
            P2 + "\nmodule Board:\n    port p passive\n"
            "    u = new rhoform.lib.timer.Ne555:\n"
            '        part "ti/ne555p"\n    p ~ u.vcc\n')
        path = "rhoform/parts/ti/ne555p.part.json"
        (root / "rhoform.lock").write_bytes(lockfile.canonical_bytes({
            "lockfile_version": 0, "parts": {
                "inputs": [lockfile.input_entry(path, data)],
                "entries": [{"key": "ti/ne555p", "manufacturer":
                             document["manufacturer"], "mpn": document["mpn"],
                             "part_id": document["part_id"],
                             "record": path}]}}))
        found, _compiled = self.check(root)
        self.assertFalse({"RHO6003", "RHO6004", "RHO6005", "RHO6006",
                          "RHO6007"} & {d["code"] for d in found})


class SubsetTest(_Case):
    """D29's subset over one instance pick, case by case."""

    PARAMETERS = {"resistance": {"max": 10.1, "min": 9.9, "typ": 10,
                                 "unit": "kohm"},
                  "rds_on": {"max": 50, "unit": "mohm"},
                  "capacitance": {"typ": 100, "unit": "nF"}}
    RATINGS = {"recommended": {"voltage_rating": {"max": 25, "unit": "V"}}}

    def picked(self, constraints, parameters=None, ratings=None):
        """(codes, rows) of a resistor instance-picking a record with
        `parameters` and `ratings`, made for exactly `constraints`."""
        root = self.case("c02_instance_pick_satisfied")
        record = root / "parts" / "acme" / "r10k.part.json"
        document = json.loads(record.read_bytes())
        document["parameters"] = parameters or self.PARAMETERS
        document["ratings"] = ratings or self.RATINGS
        data = (json.dumps(document, ensure_ascii=False, sort_keys=True,
                           indent=2) + "\n").encode()
        record.write_bytes(data)
        text = (P2 + "\nmodule Board:\n    port bottom passive\n"
                "    port top passive\n"
                "    r1 = new rhoform.lib.passive.Resistor:\n"
                "        part abstract:\n" + "".join(
                    f"            {line}\n" for line in sorted(constraints))
                + "    top ~ r1.a\n    r1.b ~ bottom\n")
        (root / "main.rhoform").write_text(text)
        _found, elaborated = self.check(root, through="model")
        part = next(i for i in elaborated.design.instances
                    if i.path == "/r1").part
        lock = json.loads((root / "rhoform.lock").read_bytes())
        lock["parts"]["inputs"][0]["sha256"] = lockfile.digest(data)
        lock["parts"]["entries"][0]["constraints"] = \
            lockfile.constraints_digest(part.constraints)
        (root / "rhoform.lock").write_bytes(lockfile.canonical_bytes(lock))
        found, compiled = self.check(root)
        return ([d["code"] for d in found if d["code"] != "RHO3901"],
                {reason: dict(row.detail).get("constraints")
                 for (_entity, reason), row in self.rows(compiled).items()})

    def test_each_kind_satisfied_and_not(self):
        cases = [
            (["resistance = 10kohm +/- 1%"], []),
            (["resistance = 10kohm +/- 2%"], []),
            (["resistance = 10kohm +/- 0.5%"], ["RHO6010"]),
            (["resistance = 10.1kohm +/- 1%"], ["RHO6010"]),
            (["resistance = 10kohm (9kohm to 11kohm)"], []),
            (["voltage_rating = 25V"], []),
            (["voltage_rating = 25.5V"], ["RHO6010"]),
            (["rds_on_max = 50mohm"], []),
            (["rds_on_max = 40mohm"], ["RHO6010"]),
            (['mpn = "R-10K"', 'manufacturer = "Acme"', 'package = "0402"'],
             []),
            (['manufacturer = "Acme Corp"'], ["RHO6010"]),
        ]
        for constraints, codes in cases:
            with self.subTest(constraints=constraints):
                found, _rows = self.picked(constraints)
                self.assertEqual(found, codes)

    def test_what_the_subset_cannot_decide_is_an_actionable_row(self):
        found, rows = self.picked([
            "capacitance = 100nF +/- 10%", 'dielectric = "X7R"',
            "power_rating = 63mW", "resistance = 10kohm +/- 1%",
            "rms_current = 3V"])
        self.assertEqual(found, [])
        # capacitance: a typ alone guarantees nothing; power_rating: the
        # record states none; rms_current: a voltage, the dimensions
        # pass's to report.
        self.assertEqual(rows["constraint-unverified"],
                         ("capacitance", "power_rating"))
        self.assertEqual(rows["constraint-outside-subset"], ("dielectric",))
        self.assertEqual(rows["constraint-ill-typed"], ("rms_current",))
        self.assertIn("bound", rows)

    def test_a_rating_is_read_from_its_home_and_nowhere_else(self):
        # D3 v1 keeps a rating in `ratings`, apart from the `parameters`
        # that define the part: a 25 V record fails a 50 V requirement
        # from ratings.recommended, and one stating its rating anywhere
        # else, abs-max included, decides nothing.
        rated = {"recommended": {
            "power_rating": {"max": 62.5, "unit": "mW"},
            "voltage_rating": {"max": 25, "unit": "V"}}}
        self.assertEqual(self.picked(["voltage_rating = 50V"], None, rated),
                         (["RHO6010"], {"constraint-unsatisfied":
                                        ("voltage_rating",)}))
        self.assertEqual(self.picked(["power_rating = 100mW"], None, rated)[0],
                         ["RHO6010"])
        self.assertEqual(self.picked(["power_rating = 62.5mW"], None,
                                     rated)[0], [])
        misplaced = dict(self.PARAMETERS,
                         voltage_rating={"max": 25, "unit": "V"})
        for parameters, ratings in (
                (misplaced, {"thermal": {"theta_ja": {
                    "max": 200, "unit": "degC/W"}}}),
                (None, {"abs_max": {"voltage_rating": {
                    "max": 25, "unit": "V"}}})):
            with self.subTest(ratings=sorted(ratings)):
                found, rows = self.picked(["voltage_rating = 50V"],
                                          parameters, ratings)
                self.assertEqual((found, rows["constraint-unverified"]),
                                 ([], ("voltage_rating",)))

    def test_a_vocabulary_name_with_no_home_is_outside_the_subset(self):
        parameters = dict(self.PARAMETERS,
                          dcr_max={"max": 50, "unit": "mohm"})
        found, rows = self.picked(["dcr_max = 40mohm", "supply_max = 5V",
                                   "vds_max = 30V"], parameters)
        self.assertEqual((found, rows["constraint-outside-subset"]),
                         ([], ("dcr_max", "supply_max", "vds_max")))

    def test_a_condition_array_or_an_unbounded_nominal_is_undecided(self):
        parameters = dict(self.PARAMETERS)
        parameters["resistance"] = [
            {"conditions": {"ta": {"typ": 25, "unit": "degC"}}, "max": 10.1,
             "min": 9.9, "unit": "kohm"},
            {"conditions": {"ta": {"typ": 85, "unit": "degC"}}, "max": 10.2,
             "min": 9.8, "unit": "kohm"}]
        found, rows = self.picked(["resistance = 10kohm +/- 5%"], parameters)
        self.assertEqual((found, rows["constraint-unverified"]),
                         ([], ("resistance",)))
        parameters = dict(self.PARAMETERS)
        parameters["resistance"] = {"min": 9.9, "unit": "kohm"}
        found, rows = self.picked(["resistance = 10kohm +/- 5%"], parameters)
        self.assertEqual((found, rows["constraint-unverified"]),
                         ([], ("resistance",)))


class ContextTest(_Case):
    def test_a_design_checked_without_its_context_is_unlocked(self):
        from rhoform import check as checker
        from rhoform import compile as pipeline
        from rhoform.check import parts
        from rhoform.diagnostics import Diagnostics

        root = self.case("c01_keyed_pick_bound")
        compiled = pipeline.compile("main.rhoform", root, stage="elaborate",
                                    sink=Diagnostics())
        _analysis, report = checker.check(compiled.design, through="parts")
        self.assertEqual([f.code for f in report.findings], ["RHO6001"])
        # A context built for other files is not this design's.
        other = self.case("c02_instance_pick_satisfied")
        loaded = pipeline.compile("main.rhoform", other, stage="load",
                                  sink=Diagnostics()).loaded
        parts.load_context(other, loaded)
        _analysis, report = checker.check(compiled.design, through="parts")
        self.assertEqual([f.code for f in report.findings], ["RHO6001"])
        # Its own is, once.
        loaded = pipeline.compile("main.rhoform", root, stage="load",
                                  sink=Diagnostics()).loaded
        context = parts.load_context(root, loaded)
        self.assertIs(context.lockfile, loaded.lockfile)
        _analysis, report = checker.check(compiled.design, context,
                                          through="parts")
        self.assertEqual(report.findings, [])
        _analysis, report = checker.check(compiled.design, through="parts")
        self.assertEqual([f.code for f in report.findings], ["RHO6001"])


if __name__ == "__main__":
    unittest.main()
