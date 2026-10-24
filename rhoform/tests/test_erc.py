"""The erc pass (rhoform.check.erc): the T2 pair table and its fold, the
rules RHO3101-RHO3110, DNP and ground handling, and reporting once per
definition.

The conformance area spec/conformance/check/erc pins each rule's stream
byte for byte; what is pinned here is what a stream cannot show -- the
table's totality, the fold's order-independence, the report rows, the
fix-it applied, the per-definition spelling across instances, and the
benchmarks' nets the acceptance names one by one.
"""

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from itertools import combinations_with_replacement, permutations
from pathlib import Path

try:
    import lark  # noqa: F401 - availability probe only
    HAVE_LARK = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_LARK = False

ROOT = Path(__file__).resolve().parents[2]
AREA = ROOT / "spec" / "conformance" / "check" / "erc"
SKIP = "lark (pinned in toolchain/versions.yaml) is required"

P = "#pragma rhoform-syntax 0.2\n\n"
BAT = "rhoform.lib.connector.BatteryConnector9V"
CAP = "rhoform.lib.passive.Capacitor"
RES = "rhoform.lib.passive.Resistor"
LDO = ("rhoform.lib.regulator.LinearRegulator(output_current = 1A, "
       "output_voltage = 3.3V)")
CHIP = """\
component Chip:
    pin gnd power_in
    pin vdd power_in
    pin a input
    pin y output
    pin od open_drain

"""
# A supplied, decoupled board around two Chips, `x` and `z`; each test adds
# the nets that put their signal pins somewhere.
BOARD = P + CHIP + f"""\
module Board:
    c = new {CAP}
    j = new {BAT}
    x = new Chip
    z = new Chip
    net GND(ground_domain = "gnd"):
        c.b
        j.neg
        x.gnd
        z.gnd
    net VCC:
        c.a
        j.pos
        x.vdd
        z.vdd
"""


class TableTest(unittest.TestCase):
    def test_the_pair_table_is_total_over_45_cells_and_symmetric(self):
        from rhoform.check import erc
        from rhoform.check.model import PinRole

        self.assertEqual(erc.CONNECTABLE,
                         tuple(r for r in PinRole if r != "nc"))
        cells = {frozenset(pair) for pair in
                 combinations_with_replacement(erc.CONNECTABLE, 2)}
        self.assertEqual(len(cells), 45)
        self.assertEqual(set(erc.PAIR), cells)
        self.assertLessEqual(set(erc.PAIR.values()), set(erc.VERDICTS))
        matrix = erc.pair_matrix()
        self.assertEqual([row[0] for row in matrix], list(erc.CONNECTABLE))
        for i, row in enumerate(matrix):
            for j, verdict in enumerate(row[1:]):
                self.assertEqual(verdict, matrix[j][i + 1])
                self.assertEqual(verdict, erc.PAIR[frozenset(
                    (erc.CONNECTABLE[i], erc.CONNECTABLE[j]))])

    def test_the_table_is_the_kicad_baseline_restricted(self):
        # Every cell not listed here is ok, open drain and open collector
        # alike (KiCad's one open-collector type).
        from rhoform.check import erc

        errors = {frozenset(p) for p in (
            ("output", "output"), ("output", "power_out"),
            ("output", "open_drain"), ("output", "open_collector"),
            ("power_out", "power_out"), ("power_out", "open_drain"),
            ("power_out", "open_collector"), ("power_out", "tri_state"))}
        warnings = {frozenset(p) for p in (
            ("output", "tri_state"), ("bidirectional", "power_out"),
            ("tri_state", "power_in"), ("tri_state", "open_drain"),
            ("tri_state", "open_collector"))}
        for cell, verdict in erc.PAIR.items():
            with self.subTest(cell=sorted(cell)):
                self.assertEqual(verdict, "error" if cell in errors else
                                 "warning" if cell in warnings else "ok")
                swapped = {frozenset(("open_drain" if r == "open_collector"
                                      else "open_collector"
                                      if r == "open_drain" else r)
                                     for r in cell)}
                self.assertEqual(erc.PAIR[swapped.pop()], verdict)

    def test_the_ground_reference_is_total_and_exempts_only_errors(self):
        from rhoform.check import erc

        self.assertEqual(list(erc.REFERENCE), list(erc.CONNECTABLE))
        self.assertEqual([r for r, _v in erc.reference_rows()],
                         list(erc.CONNECTABLE))
        for cell in erc.GROUND_OK:
            self.assertEqual(erc.PAIR[cell], "error")

    def test_the_fold_depends_on_role_counts_only(self):
        from rhoform.check import erc

        rng = random.Random(4242)
        for _ in range(300):
            roles = [rng.choice(erc.CONNECTABLE)
                     for _ in range(rng.randint(0, 6))]
            for ground in (False, True):
                found = erc.fold(roles, ground)
                for order in list(permutations(roles))[:24]:
                    self.assertEqual(erc.fold(list(order), ground), found)
        # A role meets itself only through two pins.
        self.assertEqual(erc.fold(["output"]),
                         {"error": set(), "warning": set()})
        self.assertEqual(erc.fold(["output", "output"])["error"],
                         {"output"})
        # On ground, returns share the reference; an output never does.
        self.assertEqual(erc.fold(["power_out", "power_out"], True),
                         {"error": set(), "warning": set()})
        self.assertEqual(erc.fold(["output"], True)["error"], {"output"})
        self.assertEqual(erc.fold(["bidirectional"], True)["warning"],
                         {"bidirectional"})

    def test_code_rows_are_the_erc_codeset(self):
        from rhoform import codes
        from rhoform.check import erc

        self.assertEqual([row[0] for row in erc.code_rows()],
                         [f"RHO31{n:02d}" for n in range(1, 11)])
        for code, slug, severity in erc.code_rows():
            entry = codes.lookup(code)
            self.assertEqual((entry.slug, entry.severity, entry.reserved),
                             (slug, severity, False))
            self.assertEqual(codes.owner_of(code), "erc")


class _Check(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rhoform-erc-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_erc(self, text, name="board.rhoform"):
        """(findings as dicts, erc rows as dicts, analysis, report), the
        check stage stopped after erc."""
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics

        (self.tmp / name).write_text(text, encoding="utf-8")
        sink = Diagnostics()
        compiled = pipeline.compile(name, self.tmp, sink=sink, through="erc")
        self.assertIsNotNone(compiled.report, sink.render())
        found = [json.loads(line) for line in sink.render().splitlines()]
        rows = [r.as_dict() for r in compiled.report.sections["erc"]["rows"]]
        return found, rows, compiled.analysis, compiled.report

    def codes(self, text):
        found, _rows, _a, _r = self.run_erc(text)
        return sorted((d["code"], d["entity"]) for d in found)


@unittest.skipUnless(HAVE_LARK, SKIP)
class BenchmarkTest(_Check):
    """Acceptance: (a), (b) and (c) produce no RHO31xx and no erc row,
    and the nets the plan names are clean for the reason it gives."""

    def views(self, benchmark):
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics
        from rhoform.tests.test_benchmarks import isolated_copy

        source = ROOT / "benchmarks" / benchmark / f"{benchmark}.rhoform"
        entry = isolated_copy(source, self.tmp)
        sink = Diagnostics()
        compiled = pipeline.compile(entry.name, entry.parent, sink=sink)
        lines = [json.loads(line) for line in sink.render().splitlines()]
        self.assertEqual([d["code"] for d in lines
                          if d["code"].startswith("RHO31")], [])
        self.assertEqual(compiled.report.sections["erc"],
                         {"implemented": True, "rows": []})
        return compiled.analysis.erc.views

    def test_blinker_timing_node_is_driven_by_its_rc(self):
        views = self.views("blinker-555")
        counts = views["N_TH"].counts()
        self.assertEqual((counts["input"], counts["passive"]), (2, 2))
        self.assertTrue(views["GND"].ground)

    def test_buck_strap_inputs_syncout_and_ground(self):
        views = self.views("buck-3v3")
        for net in ("EN", "FB", "ILIM", "RT", "SS"):
            with self.subTest(net=net):
                counts = views[net].counts()
                self.assertGreaterEqual(counts.get("input", 0), 1)
                self.assertGreaterEqual(counts.get("passive", 0), 1)
                self.assertNotIn("output", counts)
        self.assertTrue(views["N_u1.SYNCOUT"].isolated)
        # AGND, PGND and the exposed pad share one ground-typed net.
        self.assertTrue(views["GND"].ground)
        self.assertEqual(views["GND"].counts()["power_in"], 2)

    def test_esp32_rails_are_decoupled_and_dnp_changes_no_verdict(self):
        views = self.views("esp32s3-devboard")
        for net in ("P5V0", "P3V3_LOAD", "VBUS_IN"):
            self.assertFalse(views[net].ground)
        self.assertEqual(views["P5V0"].counts()["power_in"], 1)
        self.assertEqual(views["P3V3_LOAD"].counts()["power_in"], 1)
        self.assertTrue(views["GND"].ground)
        self.assertEqual(views["GND"].counts()["power_out"], 1)
        # IO3's pull-down is DNP: still two pins for L9b, one fitted.
        self.assertEqual((len(views["IO3"].physical),
                          len(views["IO3"].fitted)), (2, 1))


@unittest.skipUnless(HAVE_LARK, SKIP)
class RuleTest(_Check):
    def test_members_go_in_one_finding_per_net(self):
        text = BOARD + "    w = new Chip\n" + """\
    net Y:
        w.y
        x.y
        z.y
    w.gnd ~ x.gnd
    w.vdd ~ x.vdd
    net A:
        w.a
        x.a
        z.a
        w.od
        x.od
        z.od
"""
        found, _rows, _a, _r = self.run_erc(text)
        # Three outputs on Y are one finding, all three in it; three open
        # drains with three inputs on A and nothing to pull them up are
        # one RHO3104, and no RHO3103 (the open drains are its case).
        self.assertEqual(
            sorted((d["code"], d["entity"], d["params"]) for d in found),
            [("RHO3101", "Y", {"net": "Y", "members": ["w.y", "x.y", "z.y"],
                               "roles": ["output"] * 3}),
             ("RHO3104", "A", {"net": "A",
                               "pins": ["w.od", "x.od", "z.od"]})])

    def test_passive_drives_an_input_and_single_pin_hardware_does_not(self):
        driven = BOARD + f"""\
    r = new {RES}
    tp = new rhoform.lib.mech.TestPoint:
        hardware test_point
    net A:
        r.b
        x.a
    net A2:
        tp.p
        z.a
    r.a ~ x.y
    isolated z.y
    isolated x.od
    isolated z.od
"""
        self.assertEqual(self.codes(driven), [("RHO3103", "A2")])

    def test_root_ports_are_terminals_and_module_ports_never_count(self):
        module = P + CHIP + f"""\
module Stage:
    port vdd power_out
    port gnd power_in
    port sig input
    c = new {CAP}
    x = new Chip
    net VDD:
        vdd
        c.a
        x.vdd
    net GND(ground_domain = "gnd"):
        gnd
        c.b
        x.gnd
    sig ~ x.a
    isolated x.y
    isolated x.od
"""
        # Checked alone: every port is the root's, so x.a is driven from
        # outside and no net is a single pin.
        self.assertEqual(self.codes(module), [])
        board = module.replace("module Stage", "module Inner") + f"""
module Outer:
    j = new {BAT}
    s1 = new Inner
    s2 = new Inner
    net VCC:
        j.pos
        s1.vdd
        s2.vdd
    net GND(ground_domain = "gnd"):
        j.neg
        s1.gnd
        s2.gnd
"""
        # Inside a parent the ports are hierarchical: two power_out ports
        # on VCC are no contention (j.pos is its one source), and each
        # Inner's sig is left open by the parent.
        found, _rows, _a, _r = self.run_erc(board)
        self.assertEqual(sorted(((d["code"], d["entity"]) for d in found),
                                key=str),
                         [("RHO3103", None), ("RHO3106", "N_s1.sig"),
                          ("RHO3106", "N_s2.sig")])
        # The undriven input is the definition's: its two copies agree and
        # are one finding about no single net. The open port is each
        # copy's own site in the parent, so those stay apart, each
        # pointing at the instance left open.
        single = [d for d in found if d["code"] == "RHO3106"]
        self.assertEqual([d["params"] for d in single],
                         [{"net": "N_sig", "member": "x.a"}] * 2)
        lines = board.splitlines()
        self.assertEqual(sorted(s["line_start"] for d in single
                                for s in d["spans"] if not s["primary"]),
                         [lines.index("    s1 = new Inner") + 1,
                          lines.index("    s2 = new Inner") + 1])

    def test_an_unconnected_pin_is_one_finding_with_an_isolated_fixit(self):
        text = BOARD.replace("    x = new Chip\n",
                             "    x = new Chip\n    w = new Chip[2]\n") + """\
    net A:
        x.y
        x.a
        z.a
        z.y
    w[0].vdd ~ x.vdd
    w[0].gnd ~ x.gnd
    w[1].vdd ~ x.vdd
    w[1].gnd ~ x.gnd
    isolated w[1].a
    isolated w[1].y
    isolated w[1].od
    table rhoform.lib.passive.Resistor (resistance):
        r1  10ohm
    r1.a ~ x.vdd
"""
        found, _rows, _a, _r = self.run_erc(text)
        unconnected = {d["entity"]: d for d in found
                       if d["code"] == "RHO3105"}
        self.assertEqual(sorted(unconnected),
                         ["/r1", "/w[0]", "/x", "/z"])
        self.assertEqual(unconnected["/w[0]"]["params"],
                         {"instance": "w[0]", "ports": ["a", "od", "y"],
                          "roles": ["input", "open_drain", "output"]})
        self.assertEqual(unconnected["/r1"]["fixits"], [])
        fix = unconnected["/x"]["fixits"][0]
        self.assertEqual((fix["applicability"], len(fix["edits"])),
                         ("needs-review", 1))
        self.assertEqual(fix["edits"][0]["replacement"],
                         "\n    isolated x.od")
        self.assertEqual(unconnected["/w[0]"]["fixits"][0]["edits"][0][
            "replacement"], "\n    isolated w[0].a\n    isolated w[0].od"
            "\n    isolated w[0].y")
        # Applying every fix-it clears RHO3105 except the table row's.
        data = (self.tmp / "board.rhoform").read_bytes()
        edits = sorted((f["edits"][0] for d in unconnected.values()
                        for f in d["fixits"]),
                       key=lambda e: e["byte_start"], reverse=True)
        for edit in edits:
            data = (data[:edit["byte_start"]] + edit["replacement"].encode()
                    + data[edit["byte_end"]:])
        self.assertEqual([(c, e) for c, e in self.codes(data.decode())
                          if c == "RHO3105"], [("RHO3105", "/r1")])

    def test_a_reused_modules_defect_is_one_finding(self):
        text = P + CHIP + f"""\
module Pair:
    port vdd passive
    port gnd passive
    a = new Chip
    b = new Chip
    net Y:
        a.y
        b.y
    vdd ~ a.vdd ~ b.vdd
    gnd ~ a.gnd ~ b.gnd
    a.a ~ b.a ~ a.od ~ b.od

module Board:
    c = new {CAP}
    j = new {BAT}
    p1 = new Pair
    p2 = new Pair
    pa = new Pair[2]
    net GND(ground_domain = "gnd"):
        c.b
        j.neg
        p1.gnd
        p2.gnd
        pa[0].gnd
        pa[1].gnd
    net VCC:
        c.a
        j.pos
        p1.vdd
        p2.vdd
        pa[0].vdd
        pa[1].vdd
"""
        found, _rows, _a, _r = self.run_erc(text)
        self.assertEqual(sorted((d["code"], d["entity"]) for d in found),
                         [("RHO3101", None), ("RHO3104", None)])
        params = {d["code"]: d["params"] for d in found}
        self.assertEqual(params["RHO3101"], {
            "net": "Y", "members": ["a.y", "b.y"],
            "roles": ["output", "output"]})
        self.assertEqual(params["RHO3104"]["net"], "N_a.a")
        # One copy alone keeps its entity.
        single = text.replace("    p2 = new Pair\n", "").replace(
            "    pa = new Pair[2]\n", "").replace(
            "        p2.gnd\n", "").replace("        p2.vdd\n", "").replace(
            "        pa[0].gnd\n        pa[1].gnd\n", "").replace(
            "        pa[0].vdd\n        pa[1].vdd\n", "")
        self.assertEqual(self.codes(single), [("RHO3101", "p1/Y"),
                                              ("RHO3104", "N_p1/a.a")])

    def test_a_labelled_net_its_parent_extends_is_spelled_by_the_parent(self):
        # Stage labels OUT; Channel extends it to a second buffer. The net
        # is sited at Stage's label, but Channel's body holds it, so the
        # copies spell it as Channel does and are one finding.
        text = P + f"""\
component Buffer:
    pin gnd power_in
    pin vdd power_in
    pin y output

module Stage:
    port gnd passive
    port out passive
    port vdd passive
    a = new Buffer
    net OUT:
        a.y
        out
    vdd ~ a.vdd
    gnd ~ a.gnd

module Channel:
    port gnd passive
    port vdd passive
    d = new Buffer
    s = new Stage
    s.out ~ d.y
    vdd ~ d.vdd ~ s.vdd
    gnd ~ d.gnd ~ s.gnd

module Board:
    c = new {CAP}
    j = new {BAT}
    ch1 = new Channel
    ch2 = new Channel
    net GND(ground_domain = "gnd"):
        c.b
        ch1.gnd
        ch2.gnd
        j.neg
    net VCC:
        c.a
        ch1.vdd
        ch2.vdd
        j.pos
"""
        spelled = {"net": "s/OUT", "members": ["d.y", "s/a.y"],
                   "roles": ["output", "output"]}
        found, _rows, _a, _r = self.run_erc(text)
        self.assertEqual([(d["code"], d["entity"], d["params"])
                          for d in found], [("RHO3101", None, spelled)])
        single = text.replace("    ch2 = new Channel\n", "").replace(
            "        ch2.gnd\n", "").replace("        ch2.vdd\n", "")
        found, _rows, _a, _r = self.run_erc(single)
        self.assertEqual([(d["code"], d["entity"], d["params"])
                          for d in found],
                         [("RHO3101", "ch1/s/OUT", spelled)])

    def test_a_part_returning_to_ground_pulls_no_open_drain_up(self):
        text = BOARD + f"""\
    r = new {RES}
    c_od = new {CAP}
    c_ss = new {CAP}
    net A:
        r.a
        x.od
    r.b ~ c.b
    net B:
        c_od.a
        z.od
    c_od.b ~ c.b
    net SS:
        c_ss.a
        x.a
    c_ss.b ~ c.b
    x.y ~ z.a
    isolated z.y
"""
        # A pull-down and a capacitor to ground hold a line low and never
        # lift it. An input with only a capacitor to ground is still
        # driven (a soft-start pin's current source charges it).
        self.assertEqual(self.codes(text), [("RHO3104", "A"),
                                            ("RHO3104", "B")])
        # The same resistor to the rail is the pull-up.
        self.assertEqual(self.codes(text.replace("    r.b ~ c.b\n",
                                                 "    r.b ~ c.a\n")),
                         [("RHO3104", "B")])

    def test_ground_typed_nets_take_returns_but_not_outputs(self):
        text = BOARD + f"""\
    j2 = new {BAT}
    c2 = new {CAP}
    j2.neg ~ c.b
    net V2:
        c2.a
        j2.pos
    c2.b ~ c.b
    net GND2(ground_domain = "gnd"):
        x.a
        x.od
    isolated z.a
    isolated z.od
    net Y:
        x.y
        z.y
"""
        found, _rows, _a, _r = self.run_erc(text)
        # Two power outputs on GND, an input and an open drain on a ground
        # net: fine. Two outputs on Y: contention. The isolated input
        # floats.
        self.assertEqual(sorted((d["code"], d["entity"]) for d in found),
                         [("RHO3101", "Y"), ("RHO3107", "N_z.a")])
        output_on_ground = BOARD + """\
    net GND2(ground_domain = "gnd"):
        x.y
    isolated x.a
    isolated x.od
    isolated z.a
    isolated z.y
    isolated z.od
"""
        self.assertEqual(self.codes(output_on_ground),
                         [("RHO3101", "GND2"), ("RHO3106", "GND2"),
                          ("RHO3107", "N_x.a"), ("RHO3107", "N_z.a")])

    def test_decoupling_needs_a_capacitor_to_a_ground_typed_net(self):
        bare = P + CHIP.replace("    pin a input\n    pin y output\n"
                                "    pin od open_drain\n", "") + """\
component Cap:
    pin p passive
    pin n passive

module Board:
    j = new {BAT}
    x = new Chip
    k = new Cap{ARGS}
    net GND(ground_domain = "gnd"):
        j.neg
        x.gnd
        {RETURN}
    net VCC:
        j.pos
        k.p
        x.vdd
{REST}"""
        bare = bare.replace("{BAT}", BAT)

        def board(args="", ret="k.n", rest=""):
            return bare.replace("{ARGS}", args).replace(
                "{RETURN}", ret).replace("{REST}", rest)

        # An ad-hoc two-pin part is a capacitor only when it says so.
        self.assertEqual(self.codes(board()), [("RHO3110", "VCC")])
        self.assertEqual(self.codes(board("(capacitance = 100nF)")), [])
        stated = board(":\n        part abstract:\n"
                       "            capacitance = 100nF")
        self.assertEqual(self.codes(stated), [])
        # A capacitor to a net that is not ground-typed does not count
        # (and leaves REF a net of one pin). The power input on GND is a
        # return, exempt though no capacitor touches GND at all.
        floating = board("(capacitance = 100nF)", ret="",
                         rest="    net REF:\n        k.n\n")
        self.assertEqual(self.codes(floating), [("RHO3106", "REF"),
                                                ("RHO3110", "VCC")])
        # A DNP capacitor does not decouple, and the report says fitting
        # it would.
        dnp = board("(capacitance = 100nF):\n        dnp")
        found, rows, _a, _r = self.run_erc(dnp)
        self.assertEqual([(d["code"], d["entity"]) for d in found],
                         [("RHO3110", "VCC")])
        self.assertEqual(rows, [{
            "entity": "VCC", "status": "fail", "reason": "depends-on-dnp",
            "actionable": False,
            "detail": {"dnp": ["/k"], "codes": ["RHO3110"],
                       "codes_if_fitted": []}}])

    def test_no_ground_typed_net_is_an_actionable_row_not_warnings(self):
        text = BOARD.replace('(ground_domain = "gnd")', "") + """\
    isolated x.a
    isolated x.y
    isolated x.od
    isolated z.a
    isolated z.y
    isolated z.od
"""
        found, rows, _a, report = self.run_erc(text)
        self.assertEqual(
            [(d["code"], d["entity"]) for d in found if d["code"] !=
             "RHO3107"], [("RHO3901", "/")])
        self.assertEqual(rows, [{
            "entity": "/", "status": "no-data",
            "reason": "no-ground-typed-net", "actionable": True,
            "detail": {"nets": ["GND", "VCC"]}}])
        note = next(d for d in found if d["code"] == "RHO3901")
        self.assertEqual(note["params"]["classes"],
                         ["no-ground-typed-net: 1"])

    def test_dnp_parts_add_no_driver_or_pull_and_rows_record_it(self):
        text = BOARD + f"""\
    u = new {LDO}:
        dnp
    rp = new {RES}:
        dnp
    rs = new {RES}:
        dnp
    w = new Chip:
        dnp
    u.gnd ~ c.b
    u.vin ~ c.a
    u.vout ~ c.a
    net OD:
        rp.b
        x.od
        z.a
    rp.a ~ c.a
    net S:
        rs.a
        rs.b
        x.a
        x.y
    isolated z.y
    isolated z.od
    w.vdd ~ c.a
    w.gnd ~ c.b
    isolated w.a
    isolated w.y
"""
        found, rows, _a, _r = self.run_erc(text)
        # As fitted: VCC has one rail source, OD only an open drain and an
        # input, S is driven by x.y and its shorted resistor is not
        # fitted. w's unconnected pin is reported, DNP or not; its
        # isolated input floats only once it is fitted.
        self.assertEqual(sorted((d["code"], d["entity"]) for d in found),
                         [("RHO3104", "OD"), ("RHO3105", "/w")])
        self.assertEqual(sorted((r["entity"], r["status"],
                                 r["detail"]["dnp"], r["detail"]["codes"],
                                 r["detail"]["codes_if_fitted"])
                                for r in rows), [
            ("/rs", "pass", ["/rs"], [], ["RHO3109"]),
            ("N_w.a", "pass", ["/w"], [], ["RHO3107"]),
            ("OD", "fail", ["/rp"], ["RHO3104"], []),
            ("VCC", "pass", ["/rp", "/u", "/w"], [], ["RHO3101"]),
        ])
        self.assertTrue(all(r["reason"] == "depends-on-dnp"
                            and not r["actionable"] for r in rows))

    def test_a_two_terminal_part_on_one_net_is_shorted_and_only_it(self):
        text = BOARD + f"""\
    r = new {RES}
    q = new rhoform.lib.semiconductor.Nmos(vds_max = 40V)
    net S:
        q.d
        q.s
        r.a
        r.b
        x.y
    q.g ~ x.y
    isolated x.a
    isolated x.od
    isolated z.a
    isolated z.y
    isolated z.od
"""
        found, _rows, _a, _r = self.run_erc(text)
        shorted = [d for d in found if d["code"] == "RHO3109"]
        self.assertEqual([(d["entity"], d["params"]) for d in shorted],
                         [("/r", {"instance": "r", "net": "S"})])
        self.assertEqual(len([s for s in shorted[0]["spans"]
                              if not s["primary"]]), 2)

    def test_the_analysis_has_a_view_of_every_net(self):
        text = BOARD + """\
    isolated x.a
    isolated x.y
    isolated x.od
    isolated z.a
    isolated z.y
    isolated z.od
"""
        _found, _rows, analysis, _r = self.run_erc(text)
        views = analysis.erc.views
        self.assertEqual(list(views), sorted(views))
        self.assertEqual(views["VCC"].counts(),
                         {"passive": 1, "power_out": 1, "power_in": 2})
        self.assertTrue(views["GND"].ground)
        self.assertTrue(views["N_x.y"].isolated)
        self.assertEqual(views["N_x.y"].root_ports, ())

    def test_every_code_has_a_reject_case_in_the_area(self):
        from rhoform.codeset.erc import CODES

        emitted = set()
        for expected in sorted((AREA / "reject").glob("*/expected.ndjson")):
            emitted |= {json.loads(line)["code"] for line in
                        expected.read_text(encoding="utf-8").splitlines()}
        self.assertLessEqual({entry.code for entry in CODES}, emitted)
        self.assertEqual(json.loads((AREA / "pass.json").read_text()),
                         {"last_pass": "erc"})
        for expected in sorted((AREA / "accept").glob("*/expected.ndjson")):
            with self.subTest(case=expected.parent.name):
                self.assertEqual(expected.read_text(encoding="utf-8"), "")

    def test_findings_and_rows_are_identical_under_hash_seeds(self):
        cases = sorted(str(case) for case in (AREA / "reject").iterdir())
        probe = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "from rhoform import compile as pipeline\n"
            "from rhoform.diagnostics import Diagnostics\n"
            "out = []\n"
            "for case in sys.argv[1:]:\n"
            "    sink = Diagnostics()\n"
            "    c = pipeline.compile('main.rhoform', Path(case), sink=sink,"
            " through='erc')\n"
            "    out.append([sink.render(), [r.as_dict() for r in "
            "c.report.sections['erc']['rows']], "
            "[(v.name, v.counts()) for v in c.analysis.erc.views.values()]"
            "])\n"
            "sys.stdout.write(json.dumps(out))\n")
        outputs = set()
        for seed in ("0", "1", "4242"):
            done = subprocess.run(
                [sys.executable, "-c", probe, *cases],
                env=dict(os.environ, PYTHONHASHSEED=seed,
                         PYTHONPATH=str(ROOT)),
                capture_output=True, timeout=300)
            self.assertEqual(done.returncode, 0, done.stderr.decode())
            outputs.add(done.stdout)
        self.assertEqual(len(outputs), 1)


if __name__ == "__main__":
    unittest.main()
