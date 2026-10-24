"""The static stage's foundation (rhoform.check): the checked-design view,
the reporter's rules, the driver's pass order and mask, the coverage
summary, and the check report.

Every pass is still a stub, so what is pinned here is the machinery each
M2 checker plugs into, not any checker's verdicts: the benchmarks' check
output is pinned in test_benchmarks.py alone.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import lark  # noqa: F401 - availability probe only
    HAVE_LARK = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_LARK = False

try:
    import jsonschema  # noqa: F401 - availability probe only
    HAVE_JSONSCHEMA = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_JSONSCHEMA = False

ROOT = Path(__file__).resolve().parents[2]
SKIP = "lark (pinned in toolchain/versions.yaml) is required"

# One design touching every fact the view indexes: a module port joining
# nets across the hierarchy, an isolated net, labelled nets with domain
# attributes on two levels, a pinless component, pinless hardware, a part
# whose constraints are written every way, an nc pin and an unconnected
# pin, root ports, and an assertion of each tier.
DESIGN = """\
#pragma rhoform-syntax 0.2

component Logo

module Divider(r: resistance = 10kohm):
    port top passive
    port mid passive
    r1 = new rhoform.lib.passive.Resistor:
        part abstract:
            resistance = r
    net TOP(voltage_domain = "vin_5v"):
        top
        r1.a
    mid ~ r1.b

module Board:
    port vin power_in
    port spare passive
    d = new Divider
    logo = new Logo
    mh = new acme.hw.Hole:
        hardware mounting_hole
    u = new acme.ic.Sensor:
        pin vdd power_in 1
        pin out output 2
        pin unused bidirectional 3
        pin nc1 nc 4
        part abstract:
            mpn = "ACME-1"
            supply = 3.3V +/- 5%
            voltage_rating = 6V
            window = 9.5mA (8mA to 10.5mA)
    net VIN(voltage_domain = "vin_5v"):
        vin
        d.top
        u.vdd
    net MID(ground_domain = "gnd"):
        d.mid
        u.out
    isolated spare
    assert vin_ok static operating_point(VIN) within 4.5V to 5.5V
    assert vin_ripple dynamic ripple(VIN) at most 50mV
"""


def compile_text(directory: Path, text: str, name="board.rhoform", **kw):
    """(sink, Compilation) of `text` as `name` under `directory`."""
    from rhoform import compile as pipeline
    from rhoform.diagnostics import Diagnostics

    (directory / name).write_text(text, encoding="utf-8")
    sink = Diagnostics()
    return sink, pipeline.compile(name, directory, sink=sink, **kw)


class _Design(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rhoform-check-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def design(self, text=DESIGN):
        sink, compilation = compile_text(self.tmp, text, stage="elaborate")
        self.assertIsNotNone(compilation.design, sink.render())
        return compilation.design


@unittest.skipUnless(HAVE_LARK, SKIP)
class ModelTest(_Design):
    def setUp(self):
        super().setUp()
        from rhoform.check.model import CheckedDesign

        self.model = CheckedDesign(self.design())

    def test_members_split_into_physical_and_hierarchical(self):
        from rhoform.check.model import Member

        model = self.model
        self.assertEqual(model.physical_members["VIN"],
                         (Member("/d/r1", "a", "passive", True),
                          Member("/u", "vdd", "power_in", True)))
        self.assertEqual(model.hierarchical_members["VIN"],
                         (Member("/", "vin", "power_in", False),
                          Member("/d", "top", "passive", False)))
        self.assertEqual(model.net_of[("/d/r1", "b")], "MID")
        self.assertEqual(model.net_of[("/d", "mid")], "MID")

    def test_unconnected_ports_root_ports_and_isolated_nets(self):
        from rhoform.check.model import Member

        model = self.model
        # nc1 is nc, so it is never unconnected; the isolated root port is
        # connected (to a net of its own).
        self.assertEqual(model.unconnected,
                         (Member("/u", "unused", "bidirectional", True),))
        self.assertEqual(model.root_ports,
                         (Member("/", "spare", "passive", False),
                          Member("/", "vin", "power_in", False)))
        self.assertEqual(model.isolated, frozenset({"N_.spare"}))
        self.assertEqual(model.pinless_components(), ("/logo",))
        self.assertEqual(model.components,
                         ("/d/r1", "/logo", "/mh", "/u"))

    def test_attribute_and_endpoint_sites_keep_every_site(self):
        model = self.model
        data = (self.tmp / "board.rhoform").read_bytes()

        def text(span):
            return data[span.byte_start:span.byte_end].decode()

        sites = model.attribute_sites["VIN"]["voltage_domain"]
        self.assertEqual([(value, text(span)) for value, span in sites],
                         [("vin_5v", 'voltage_domain = "vin_5v"')] * 2)
        # Shallowest label first: Board's VIN, then Divider's TOP.
        lines = DESIGN.splitlines()
        self.assertEqual(
            [span.line_start for _value, span in sites],
            [lines.index('    net VIN(voltage_domain = "vin_5v"):') + 1,
             lines.index('    net TOP(voltage_domain = "vin_5v"):') + 1])
        # The module port is named by the parent (`d.top`) and by the
        # module itself (`top`): both sites are kept, the parent's first.
        self.assertEqual([text(span) for span in
                          model.endpoint_spans[("/d", "top")]],
                         ["d.top", "top"])
        self.assertEqual([text(span) for span in
                          model.endpoint_spans[("/", "spare")]], ["spare"])

    def test_values_constraints_ports_and_bounds_with_their_spans(self):
        from decimal import Decimal

        from rhoform.elaborate import Quantity

        model = self.model
        data = (self.tmp / "board.rhoform").read_bytes()

        def text(span):
            return data[span.byte_start:span.byte_end].decode()

        self.assertEqual(model.value("/d", "r"), Quantity(Decimal("10"),
                                                          "kohm"))
        self.assertEqual(model.value("/u", "mpn"), "ACME-1")
        with self.assertRaises(KeyError):
            model.value("/u", "nonesuch")
        shapes = {name: (c.form, c.origin, text(c.span)) for name, c in (
            (name, model.constraint("/u", name))
            for name in ("mpn", "supply", "voltage_rating", "window"))}
        self.assertEqual(shapes, {
            "mpn": (None, "literal", '"ACME-1"'),
            "supply": ("toleranced", "literal", "3.3V +/- 5%"),
            "voltage_rating": ("exact", "literal", "6V"),
            "window": ("interval", "literal", "9.5mA (8mA to 10.5mA)")})
        reference = model.constraint("/d/r1", "resistance")
        self.assertEqual((reference.form, reference.origin,
                          text(reference.span)), ("exact", "reference", "r"))
        self.assertIsNone(model.constraint("/u", "nonesuch"))
        self.assertIsNone(model.constraint("/logo", "mpn"))
        self.assertEqual(text(model.port_decl_span("/u", "vdd")),
                         "pin vdd power_in 1")
        self.assertEqual(text(model.port_decl_span("/", "vin")),
                         "port vin power_in")
        self.assertTrue(model.port_decl_span("/d/r1", "a").file.startswith(
            "rhoform/lib/"))
        self.assertEqual(text(model.bound_span("/vin_ok")),
                         "within 4.5V to 5.5V")
        self.assertEqual([a.path for a in model.static_assertions()],
                         ["/vin_ok"])

    def test_entities_are_exactly_the_source_map_nodes(self):
        from rhoform import ir

        design = self.model.design
        nodes = ir.to_source_map(design, "")["nodes"]
        self.assertEqual(sorted(self.model.entities), sorted(nodes))
        for entity in nodes:
            spans = self.model.entity_spans(entity)
            self.assertEqual(spans[0], self.model.declaration(entity))
            self.assertEqual(len(spans),
                             1 + len(nodes[entity]["instantiation_trace"]))

    def test_the_in_memory_facts_never_reach_the_ir(self):
        from rhoform import ir

        text = ir.emit(self.model.design)[0].decode()
        for word in ("isolated", "attribute_sites", "endpoint_spans",
                     "bound_span", "sites", "declaration"):
            self.assertNotIn(f'"{word}"', text)


@unittest.skipUnless(HAVE_LARK, SKIP)
class ReporterTest(_Design):
    def setUp(self):
        super().setUp()
        from rhoform.check.model import CheckedDesign
        from rhoform.check.report import Report

        self.model = CheckedDesign(self.design())
        self.report = Report(self.model)
        self.report.open("assertions", "waivers", False)

    def finding(self, entity="/vin_ok", **kw):
        return self.report.finding(
            "RHO3553", {"assertion": entity, "measurement": "m",
                        "reason": "r"}, entity=entity, **kw)

    def test_a_pass_reports_only_its_owners_codes(self):
        self.report.owner = "erc"
        with self.assertRaisesRegex(AssertionError,
                                    "waivers's to report, not erc's"):
            self.finding()
        self.report.owner = "waivers"
        with self.assertRaisesRegex(AssertionError, "in no range"):
            self.report.finding("RHO3600", {}, entity="/")

    def test_a_finding_is_about_an_entity_with_a_source_map_node(self):
        with self.assertRaisesRegex(AssertionError, "no source-map node"):
            self.finding(entity="/u.vdd")
        found = self.finding()
        self.assertEqual(found.primary, self.model.declaration("/vin_ok"))
        self.assertEqual(found.entity, "/vin_ok")

    def test_copies_dedup_and_keep_an_entity_only_when_all_agree(self):
        from rhoform.diagnostics import Diagnostics

        span = self.model.declaration("/vin_ok")
        self.finding()
        self.finding()
        sink = Diagnostics()
        self.report.flush(sink)
        self.assertEqual([(d.code, d.entity) for d in sink],
                         [("RHO3553", "/vin_ok")])
        self.report.findings.clear()
        # Same params and spans, different entities: one finding, about
        # no single entity.
        params = {"assertion": "/vin_ok", "measurement": "m", "reason": "r"}
        self.report.finding("RHO3553", params, entity="/vin_ok")
        self.report.finding("RHO3553", params, entity="/vin_ripple",
                            primary=span)
        sink = Diagnostics()
        self.report.flush(sink)
        self.assertEqual([(d.code, d.entity) for d in sink],
                         [("RHO3553", None)])

    def test_one_finding_per_code_and_entity(self):
        from rhoform.diagnostics import Diagnostics

        self.finding()
        self.report.finding("RHO3553", {"assertion": "/vin_ok",
                                        "measurement": "other",
                                        "reason": "r"}, entity="/vin_ok")
        with self.assertRaisesRegex(AssertionError, "aggregate"):
            self.report.flush(Diagnostics())

    def test_rows_are_checked_and_frozen(self):
        with self.assertRaises(ValueError):
            self.report.row("/", "maybe", "x")
        with self.assertRaises(ValueError):
            self.report.row("/", "pass", "Not Kebab")
        with self.assertRaises(ValueError):
            self.report.row("/", "pass", "x", detail={"nested": {"a": 1}})
        with self.assertRaises(ValueError):
            self.report.row("/", "pass", "x", detail={"n": float("nan")})
        with self.assertRaisesRegex(AssertionError, "no source-map node"):
            self.report.row("/nowhere", "pass", "x")
        nets = ["MID"]
        row = self.report.row("/", "pass", "x", detail={"nets": nets})
        nets.append("VIN")
        self.assertEqual(row.as_dict()["detail"], {"nets": ["MID"]})

    def test_the_coverage_note_counts_actionable_rows_by_class(self):
        from rhoform.diagnostics import Diagnostics

        self.assertIsNone(self.report.summarize("check"))
        self.report.row("/", "not-run", "dynamic-tier")  # inherent
        self.assertIsNone(self.report.summarize("check"))
        self.report.open("model", "check", True)
        self.report.row("/logo", "no-data", "component-without-pins",
                        actionable=True)
        self.report.row("/u", "no-data", "component-without-pins",
                        actionable=True)
        self.report.open("parts", "parts", False)
        self.report.row("/", "not-implemented", "pass-not-implemented",
                        actionable=True)
        note = self.report.summarize("check")
        self.assertEqual(dict(note.params), {
            "actionable": 3,
            "classes": ("component-without-pins: 2",
                        "pass-not-implemented: 1"),
            "sections": ("model", "parts")})
        self.assertEqual((note.entity, note.severity), ("/", "note"))
        sink = Diagnostics()
        self.report.flush(sink)
        self.assertEqual([d.code for d in sink], ["RHO3901"])


@unittest.skipUnless(HAVE_LARK, SKIP)
class DriverTest(_Design):
    def check(self, text=DESIGN, through=None):
        from rhoform.check import check
        from rhoform.diagnostics import Diagnostics

        sink = Diagnostics()
        analysis, report = check(self.design(text), sink=sink,
                                 through=through)
        return sink, analysis, report

    def test_the_passes_run_in_the_fixed_order(self):
        from rhoform import check as checker

        self.assertEqual(checker.pass_names(), (
            "model", "parts", "dimensions", "ground", "erc", "domains",
            "budget", "domains_refine", "assertions"))
        for step in checker.PASSES:
            with self.subTest(step=step.NAME):
                self.assertIn(step.OWNER, ("budget", "domains", "erc",
                                           "ground", "parts", "quantities",
                                           "waivers"))
                self.assertIsInstance(step.IMPLEMENTED, bool)
                self.assertTrue(callable(step.run))
        _sink, _analysis, report = self.check()
        self.assertEqual(list(report.sections), list(checker.pass_names()))

    def test_every_stub_is_an_actionable_row_and_one_coverage_note(self):
        sink, _analysis, report = self.check()
        for name, section in report.sections.items():
            if name == "model":
                continue
            with self.subTest(section=name):
                self.assertFalse(section["implemented"])
                self.assertIn(("/", "not-implemented",
                               "pass-not-implemented", True),
                              [(r.entity, r.status, r.reason, r.actionable)
                               for r in section["rows"]])
        notes = [d for d in sink if d.code == "RHO3901"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(dict(notes[0].params)["classes"], (
            "component-without-pins: 1", "pass-not-implemented: 8"))

    def test_the_mask_runs_the_passes_up_to_the_named_one(self):
        _sink, _analysis, report = self.check(through="model")
        self.assertEqual(list(report.sections), ["model"])
        _sink, analysis, report = self.check(through="ground")
        self.assertEqual(list(report.sections),
                         ["model", "parts", "dimensions", "ground"])
        self.assertIsNotNone(analysis.ground)
        with self.assertRaisesRegex(ValueError, "no pass is named"):
            self.check(through="interfaces")

    def test_the_interim_ground_stub_types_labelled_nets(self):
        _sink, analysis, report = self.check(through="ground")
        self.assertEqual(analysis.ground.status, "interim")
        self.assertTrue(analysis.ground.is_ground("MID"))
        self.assertFalse(analysis.ground.is_ground("VIN"))
        rows = [r.as_dict() for r in report.sections["ground"]["rows"]]
        self.assertIn({"entity": "/", "status": "interim",
                       "reason": "ground-typing-from-labels",
                       "actionable": False,
                       "detail": {"ground_nets": ["MID"]}}, rows)

    def test_a_declared_static_assertion_gates_while_nothing_evaluates_it(
            self):
        with mock.patch("rhoform.check.assertions.IMPLEMENTED", False):
            for through in ("model", "assertions"):
                with self.subTest(through=through):
                    sink, _analysis, _report = self.check(through=through)
                    incomplete = [d for d in sink if d.code == "RHO3553"]
                    self.assertEqual(
                        [(d.entity, d.tier, d.severity) for d in incomplete],
                        [("/vin_ok", "static", "error")])
                    # The dynamic assertion is the dynamic tier's: nothing.
                    self.assertNotIn("/vin_ripple",
                                     [d.entity for d in sink])

    def test_a_module_only_an_untaken_branch_uses_draws_no_finding(self):
        # AMB-144 item 10: a module whose only `new` stands in a branch no
        # instance takes is elaborated once under its defaults, and nothing
        # from that run reaches the check stage. Its pinless component and
        # its static assertion would each draw a finding if it did.
        spare = """\
#pragma rhoform-syntax 0.2

component Logo

module Spare:
    port p passive
    logo = new Logo
    net P:
        p
    assert p_ok static operating_point(P) within 1V to 2V

module Board(debug: bool = false):
    port q passive
    if debug:
        s = new Spare
"""
        with mock.patch("rhoform.check.assertions.IMPLEMENTED", False):
            sink, _analysis, report = self.check(spare, through="model")
            self.assertEqual(len(sink), 0, sink.render())
            self.assertEqual(report.sections["model"]["rows"], [])
            taken = spare.replace("debug: bool = false",
                                  "debug: bool = true")
            sink, _analysis, report = self.check(taken, through="model")
            self.assertEqual(sorted((d.code, d.entity) for d in sink),
                             [("RHO3553", "/s/p_ok"), ("RHO3901", "/")])

    def test_the_check_report_is_canonical_and_schema_valid(self):
        from rhoform import ir
        from rhoform.check import report as check_report

        if not HAVE_JSONSCHEMA:
            self.skipTest("jsonschema (pinned in toolchain/versions.yaml) "
                          "is required")
        _sink, _analysis, report = self.check()
        design_hash = "sha256:" + "0" * 64
        document = report.document(design_hash)
        self.assertIsNone(check_report.schema_problem(document))
        data = report.canonical(design_hash)
        self.assertEqual(data, ir.canonical_bytes(json.loads(data)))
        self.assertEqual(json.loads(data), document)
        self.assertEqual(document["report_version"],
                         check_report.REPORT_VERSION)
        broken = dict(document, sections={})
        self.assertIn("model", check_report.schema_problem(broken))

    def test_the_schema_restates_the_pass_names_and_statuses(self):
        from rhoform import check as checker
        from rhoform.check import report as check_report

        schema = json.loads(check_report.SCHEMA_PATH.read_text(
            encoding="utf-8"))
        self.assertEqual(
            schema["properties"]["sections"]["propertyNames"]["enum"],
            list(checker.pass_names()))
        self.assertEqual(
            schema["$defs"]["Row"]["properties"]["status"]["enum"],
            list(check_report.STATUSES))

    def test_findings_and_report_are_identical_under_hash_seeds(self):
        (self.tmp / "board.rhoform").write_text(DESIGN, encoding="utf-8")
        probe = (
            "import sys\n"
            "from pathlib import Path\n"
            "from rhoform import compile as pipeline\n"
            "from rhoform.diagnostics import Diagnostics\n"
            "sink = Diagnostics()\n"
            "c = pipeline.compile('board.rhoform', Path(sys.argv[1]), "
            "sink=sink)\n"
            "sys.stdout.write(sink.render())\n"
            "sys.stdout.buffer.write(c.report.canonical('sha256:' + '0' * "
            "64))\n")
        outputs = set()
        for seed in ("0", "1", "4242"):
            done = subprocess.run(
                [sys.executable, "-c", probe, str(self.tmp)],
                env=dict(os.environ, PYTHONHASHSEED=seed,
                         PYTHONPATH=str(ROOT)),
                capture_output=True, timeout=300)
            self.assertEqual(done.returncode, 0, done.stderr.decode())
            outputs.add(done.stdout)
        self.assertEqual(len(outputs), 1)
