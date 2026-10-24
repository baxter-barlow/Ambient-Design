"""The ground pass (rhoform.check.ground): conduction groups from rules,
the isolation partition, ground typing and the GA-2 meet, the two
union-finds, the scans, and the GroundAnalysis API.

The conformance area spec/conformance/check/ground pins each code's
stream byte for byte; what is pinned here is what a stream cannot show --
the API, the report rows, the zero-annotation result on the three
benchmarks (GA-16/17), that ERC reads the same ground typing as before on
every design it has a verdict for, and determinism.
"""

import importlib.util
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

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "spec" / "conformance" / "check"
AREA = CHECK / "ground"
SKIP = "lark (pinned in toolchain/versions.yaml) is required"

P = "#pragma rhoform-syntax 0.3\n\n"
TIE = ("component NetTie:\n    pin a passive\n    pin b passive\n"
       "    tie a b\n\n")
LOAD = ("component Load:\n    pin gnd power_in\n    pin vdd power_in\n"
        "    ground gnd\n\n")


def grammar_kinds() -> tuple:
    spec = importlib.util.spec_from_file_location(
        "_sot_kinds", ROOT / "lang" / "grammar" / "rhoform_syntax.py")
    sot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sot)
    return tuple(sot.CLOSED_VOCABULARIES["ground_kind"])


class _Interim:
    """The foundation's interim ground typing, rebuilt here as it was: a
    net is ground exactly when an author labelled it `ground_domain`. It
    typed no ties, so it handed ERC no net-ties."""

    net_ties = ()

    def __init__(self, model):
        self._ground = frozenset(name for name, net in model.nets.items()
                                 if net.ground_domain is not None)

    def is_ground(self, net):
        return net in self._ground


def interim_run(model, analysis, report):
    analysis.ground = _Interim(model)


class _Ground(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rhoform-ground-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def compile(self, root: Path, entry="main.rhoform", through="ground"):
        """(findings as dicts, Compilation) of one compile root."""
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics

        sink = Diagnostics()
        compiled = pipeline.compile(entry, root, sink=sink, through=through)
        self.assertIsNotNone(compiled.report, sink.render())
        return ([json.loads(line) for line in sink.render().splitlines()],
                compiled)

    def run_text(self, text, through="ground"):
        root = self.tmp / f"case{len(list(self.tmp.iterdir()))}"
        root.mkdir()
        (root / "main.rhoform").write_text(text, encoding="utf-8")
        return self.compile(root, through=through)

    def case(self, name):
        (root,) = AREA.glob(f"*/{name}")
        return self.compile(root)

    @staticmethod
    def rows(compiled, section="ground"):
        """The section's rows as the check report writes them: sorted."""
        return compiled.report.document("sha256:" + "0" * 64)["sections"][
            section]["rows"]


class ConductionTest(unittest.TestCase):
    """Groups from rules, on stand-in instances: what each word does."""

    @staticmethod
    def instance(pins, rules=(), roles=None):
        from rhoform.elaborate import Port, Rule

        made = []
        for rule in rules:
            word, *rest = rule
            if word == "side":
                made.append(Rule("side", tuple(rest[1]), side=rest[0]))
            else:
                made.append(Rule(word, tuple(rest[0]),
                                 other=rest[1] if len(rest) > 1 else None))
        ports = tuple(Port(p, (roles or {}).get(p, "passive")) for p in pins)
        return mock.Mock(ports=ports, rules=tuple(made))

    def groups(self, pins, rules=(), roles=None):
        from rhoform.check.ground import conduction

        return conduction(self.instance(pins, rules, roles))

    def test_the_kinds_are_the_grammars(self):
        from rhoform.check import ground

        self.assertEqual(ground.KINDS, grammar_kinds())
        self.assertEqual(ground.KINDS[0], ground.UNSPECIFIED)

    def test_a_component_with_no_rule_is_one_group(self):
        model = self.groups(("a", "b", "c"), roles={"a": "power_in"})
        self.assertEqual(model.groups, (("a", "b", "c"),))
        self.assertFalse(model.barrier)
        self.assertEqual(model.galvanic, ())

    def test_a_two_terminal_passive_with_no_rule_is_galvanic(self):
        self.assertEqual(self.groups(("a", "b")).galvanic, (("a", "b"),))
        # Not passive both sides: an ordinary part, not a galvanic passive.
        self.assertEqual(self.groups(("a", "b"),
                                     roles={"a": "power_out"}).galvanic, ())

    def test_a_passive_with_no_rule_is_galvanic_whatever_its_pin_count(self):
        # A common-mode choke or a Kelvin shunt is one group, all passive.
        pins = ("in1", "in2", "out1", "out2")
        self.assertEqual(self.groups(pins).galvanic, (pins,))
        self.assertEqual(self.groups(("a",)).galvanic, ())
        self.assertEqual(self.groups(("a", "b", "c"),
                                     roles={"c": "power_in"}).galvanic, ())

    def test_open_and_bridge_pins_are_groups_of_their_own(self):
        model = self.groups(("a", "b", "c"), [("open", ("a", "b"))])
        self.assertEqual(model.groups, (("a",), ("b",), ("c",)))
        self.assertEqual(model.opens, (("a", "b"),))
        model = self.groups(("a", "b"), [("bridge", ("a", "b"))])
        self.assertEqual(model.groups, (("a",), ("b",)))
        self.assertEqual(model.bridges, (("a", "b"),))
        self.assertEqual(model.galvanic, ())

    def test_a_bare_connector_makes_every_other_pin_a_contact(self):
        model = self.groups(("gnd", "p1", "p2", "vbus"),
                            [("ground", ("gnd",)), ("source", ("vbus",)),
                             ("connector", ())])
        self.assertEqual(model.groups, (("gnd", "vbus"), ("p1",), ("p2",)))
        model = self.groups(("p1", "p2", "p3"), [("connector", ("p1",))])
        self.assertEqual(model.groups, (("p1",), ("p2", "p3")))

    def test_coupling_words_join_what_splitting_words_separate(self):
        model = self.groups(("a", "b", "c"),
                            [("connector", ()), ("pass", ("a",), "b")])
        self.assertEqual(model.groups, (("a", "b"), ("c",)))
        self.assertEqual(model.galvanic, (("a", "b"),))

    def test_sides_make_a_barrier_and_leave_the_rest_alone(self):
        model = self.groups(("a", "c", "e", "k", "nc"),
                            [("side", "emitter", ("a", "k")),
                             ("side", "detector", ("c", "e"))])
        self.assertTrue(model.barrier)
        self.assertEqual(model.sides, (("detector", ("c", "e")),
                                       ("emitter", ("a", "k"))))
        self.assertEqual(model.groups, (("a", "k"), ("c", "e"), ("nc",)))

    def test_a_net_tie_is_two_pins_and_one_tie(self):
        self.assertEqual(self.groups(("a", "b"), [("tie", ("a", "b"))]).tie,
                         ("a", "b"))
        for pins, rules in ((("a", "b", "c"), [("tie", ("a", "b"))]),
                            (("a", "b"), [("tie", ("a",))]),
                            (("a", "b"), [("tie", ("a", "b")),
                                          ("tie", ("b", "a"))])):
            with self.subTest(pins=pins, rules=rules):
                model = self.groups(pins, rules)
                self.assertIsNone(model.tie)
                self.assertEqual([reason for reason, _ in model.malformed],
                                 ["malformed-tie"])

    def test_the_classes_root_at_their_least_member_in_any_order(self):
        from itertools import permutations

        from rhoform.check.ground import _Classes

        pairs = [("d", "b"), ("c", "a"), ("b", "c")]
        for order in permutations(pairs):
            classes = _Classes("abcde")
            for x, y in order:
                classes.union(x, y)
            self.assertEqual(classes.classes(), [["a", "b", "c", "d"],
                                                 ["e"]])
            self.assertEqual({classes.find(x) for x in "abcd"}, {"a"})


@unittest.skipUnless(HAVE_LARK, SKIP)
class AnalysisTest(_Ground):
    def test_the_default_ground_comes_from_ground_rules(self):
        found, compiled = self.case("c01_single_default_ground")
        self.assertEqual(found, [])
        ground = compiled.analysis.ground
        self.assertEqual(ground.ground_nets, ("GND",))
        self.assertEqual(ground.ground_kind("GND"), "unspecified")
        self.assertEqual(list(ground.ground_domains), ["GND"])
        self.assertEqual(len(ground.isolation_domains), 1)
        self.assertIsNone(ground.ground_domain("VOUT"))
        self.assertIsNone(ground.ground_kind("VOUT"))
        self.assertEqual(ground.conduction_groups("/u"),
                         (("gnd", "vin", "vout"),))

    def test_a_tie_and_a_ferrite_make_one_domain_and_one_edge(self):
        found, compiled = self.case("c02_tie_plus_ferrite")
        self.assertEqual(found, [])
        ground = compiled.analysis.ground
        self.assertEqual(ground.ground_domains, {"AGND": ("AGND", "PGND")})
        self.assertEqual(ground.tie_graph, (("/nt", "AGND", "PGND"),))
        self.assertEqual((ground.ground_kind("AGND"),
                          ground.ground_kind("PGND")), ("signal", "power"))
        self.assertIn({"entity": "/fb", "status": "pass",
                       "reason": "passive-joins-distinct-kinds",
                       "actionable": False,
                       "detail": {"kinds": ["signal", "power"],
                                  "nets": ["AGND", "PGND"]}},
                      self.rows(compiled))

    def test_sides_seed_two_isolation_domains_the_barriers_relate(self):
        found, compiled = self.case("c04_isolated_dcdc_opto_feedback")
        self.assertEqual(found, [])
        ground = compiled.analysis.ground
        self.assertEqual(ground.isolation_domains, {
            "FB": ("FB", "GND_PRI", "VIN"),
            "GND_SEC": ("GND_SEC", "LED", "VOUT")})
        self.assertEqual(sorted(ground.ground_domains),
                         ["GND_PRI", "GND_SEC"])
        self.assertEqual(ground.isolation_domain("LED"), "GND_SEC")
        self.assertEqual(sorted(ground.barriers()), ["/dcdc", "/opto"])
        rows = {(r["entity"], r["reason"]): r["detail"]
                for r in self.rows(compiled)}
        self.assertEqual(rows[("FB", "isolation-domain")], {
            "nets": ["FB", "GND_PRI", "VIN"],
            "ground_domains": ["GND_PRI"], "barriers": ["/dcdc", "/opto"]})
        self.assertEqual(rows[("GND_SEC", "ground-domain")], {
            "nets": ["GND_SEC"], "kinds": ["unspecified"],
            "isolation_domain": "GND_SEC"})

    def test_computed_ids_go_to_the_report_and_never_to_the_ir(self):
        from rhoform import ir

        _found, compiled = self.case("c04_isolated_dcdc_opto_feedback")
        document = json.loads(ir.emit(compiled.design)[0])
        labels = {net["name"]: net.get("ground_domain")
                  for net in document["nets"]}
        # The authored labels, as written; the computed ids are net names.
        self.assertEqual((labels["GND_PRI"], labels["GND_SEC"],
                          labels["LED"]), ("pri", "sec", None))
        self.assertTrue(any(r["reason"] == "ground-domain"
                            and r["entity"] == "GND_PRI"
                            for r in self.rows(compiled)))

    def test_a_dnp_part_adds_no_conduction_and_is_listed(self):
        found, compiled = self.case("c07_dnp_resistor_across_barrier")
        self.assertEqual(found, [])
        self.assertIn({"entity": "/r_fit", "status": "pass",
                       "reason": "depends-on-dnp", "actionable": False,
                       "detail": {"dnp": ["/r_fit"],
                                  "ground_domains": ["GND_SEC"],
                                  "isolation_domains": ["FB", "GND_SEC"]}},
                      self.rows(compiled))
        # Fitted, it spans the barrier: c12's finding.
        fitted = (AREA / "accept" / "c07_dnp_resistor_across_barrier" /
                  "main.rhoform").read_text(encoding="utf-8").replace(
            "    r_fit = new rhoform.lib.passive.Resistor:\n        dnp\n",
            "    r_fit = new rhoform.lib.passive.Resistor\n")
        found, _compiled = self.run_text(fitted)
        self.assertEqual([(d["code"], d["entity"]) for d in found],
                         [("RHO4005", "/r_fit")])

    def test_a_dnp_part_types_no_net_and_ties_nothing(self):
        text = P + LOAD + TIE + """\
module Board:
    a = new Load
    b = new Load:
        dnp
    nt1 = new NetTie
    nt2 = new NetTie:
        dnp
    net G1(ground_kind = "signal"):
        a.gnd
        nt1.a
        nt2.a
    net G2(ground_kind = "power"):
        nt1.b
        nt2.b
    net X:
        a.vdd
        b.gnd
"""
        found, compiled = self.run_text(text)
        self.assertEqual(found, [])  # the DNP tie closes no loop
        ground = compiled.analysis.ground
        self.assertFalse(ground.is_ground("X"))
        self.assertEqual(ground.tie_graph, (("/nt1", "G1", "G2"),))

    def test_a_rule_statement_replaces_the_conduction_model(self):
        # The library resistor is a galvanic passive; a `rule` statement
        # making it DC-open makes it a plain capacitor's position.
        base = P + LOAD + TIE + """\
module Board:
    bond = new NetTie
    load = new Load
    r = new rhoform.lib.passive.Resistor
    net CHASSIS(ground_kind = "chassis"):
        bond.a
        r.a
    net GND:
        bond.b
        load.gnd
        r.b
"""
        found, _compiled = self.run_text(base)
        # Rule-less, its galvanic reading is the default: a row says so.
        self.assertEqual(sorted((d["code"], d["entity"]) for d in found),
                         [("RHO3901", "/"), ("RHO4011", "/bond"),
                          ("RHO4011", "/r")])
        found, compiled = self.run_text(base.replace(
            "    r = new rhoform.lib.passive.Resistor\n",
            "    r = new rhoform.lib.passive.Resistor\n    rule r open a b\n"))
        self.assertEqual(sorted((d["code"], d["entity"]) for d in found),
                         [("RHO4004", "/r"), ("RHO4011", "/bond")])
        self.assertEqual(compiled.analysis.ground.conduction_groups("/r"),
                         (("a",), ("b",)))

    def test_a_malformed_tie_is_an_actionable_row_not_a_tie(self):
        text = P + """\
component Tie3:
    pin a passive
    pin b passive
    pin c passive
    tie a b

""" + LOAD + """\
module Board:
    load = new Load
    t = new Tie3
    net GND:
        load.gnd
        t.a
        t.b
"""
        found, compiled = self.run_text(text)
        self.assertEqual([d["code"] for d in found], ["RHO3901"])
        self.assertEqual(compiled.analysis.ground.tie_graph, ())
        self.assertIn({"entity": "/t", "status": "no-data",
                       "reason": "malformed-tie", "actionable": True,
                       "detail": {"pins": ["a", "b", "c"],
                                  "tie_pins": ["a", "b"], "ties": 1}},
                      self.rows(compiled))

    def test_no_ground_at_all_is_an_actionable_row(self):
        text = P + """\
component Part:
    pin a passive
    pin b passive

module Board:
    p = new Part
    q = new Part
    net X:
        p.a
        q.a
    net Y:
        p.b
        q.b
"""
        found, compiled = self.run_text(text)
        self.assertEqual([d["code"] for d in found], ["RHO3901"])
        self.assertIn({"entity": "/", "status": "no-data",
                       "reason": "no-ground-domain", "actionable": True,
                       "detail": {"nets": ["X", "Y"]}}, self.rows(compiled))

    def test_a_passive_across_a_barrier_unifies_no_grounds(self):
        # GA section 4.2's `oops`: a resistor, or a library capacitor read
        # as one, from the secondary ground to the primary's. It spans the
        # barrier, and the grounds stay two ground domains, each within
        # its own isolation domain (GA section 1.1, GA-13).
        text = P + """\
component IsoDcDc:
    pin gnd_in power_in
    pin gnd_out power_out
    pin vin power_in
    pin vout power_out
    ground gnd_in gnd_out
    side pri: gnd_in vin
    side sec: gnd_out vout

""" + LOAD + """\
module Board:
    port vin power_in
    dcdc = new IsoDcDc
    load = new Load
    oops = new rhoform.lib.passive.PART
    net GND_PRI:
        dcdc.gnd_in
        oops.b
    net GND_SEC:
        dcdc.gnd_out
        load.gnd
        oops.a
    net VIN:
        dcdc.vin
        vin
    net VOUT:
        dcdc.vout
        load.vdd
"""
        for part in ("Resistor", "Capacitor"):
            with self.subTest(part=part):
                found, compiled = self.run_text(text.replace("PART", part))
                self.assertEqual([(d["code"], d["entity"]) for d in found],
                                 [("RHO4005", "/oops")])
                ground = compiled.analysis.ground
                self.assertEqual(ground.ground_domains,
                                 {"GND_PRI": ("GND_PRI",),
                                  "GND_SEC": ("GND_SEC",)})
                self.assertEqual(ground.isolation_domain("GND_SEC"),
                                 "GND_SEC")
                rows = {(r["entity"], r["reason"]): r["detail"]
                        for r in self.rows(compiled)}
                self.assertEqual(rows[("GND_SEC", "ground-domain")], {
                    "nets": ["GND_SEC"], "kinds": ["unspecified"],
                    "isolation_domain": "GND_SEC"})
                self.assertNotIn(("/oops", "assumed-galvanic-passive"), rows)

    def test_a_rule_less_passive_joining_grounds_is_an_assumed_row(self):
        # The library capacitor has no rules yet, so from the chassis to
        # GND it reads as a galvanic passive: one domain and a bond, where
        # GA-12 makes a plain capacitor RHO4004. The default decided that,
        # so the report says it was assumed and the coverage note counts it.
        text = P + LOAD + TIE + """\
module Board:
    bond = new NetTie
    cy = new rhoform.lib.passive.Capacitor
    load = new Load
    net CHASSIS(ground_kind = "chassis"):
        bond.a
        cy.a
    net GND:
        bond.b
        cy.b
        load.gnd
    net V:
        load.vdd
"""
        found, compiled = self.run_text(text)
        self.assertEqual(sorted((d["code"], d["entity"]) for d in found),
                         [("RHO3901", "/"), ("RHO4011", "/bond"),
                          ("RHO4011", "/cy")])
        self.assertEqual(found[0]["params"]["classes"],
                         ["assumed-galvanic-passive: 1"])
        self.assertIn({"entity": "/cy", "status": "no-data",
                       "reason": "assumed-galvanic-passive",
                       "actionable": True,
                       "detail": {"nets": ["CHASSIS", "GND"]}},
                      self.rows(compiled))
        # Decoupling the supply to the one ground, it decides nothing.
        found, compiled = self.run_text(text.replace(
            "        cy.a\n", "").replace("        load.vdd\n",
                                         "        cy.a\n        load.vdd\n"))
        self.assertEqual([(d["code"], d["entity"]) for d in found],
                         [("RHO4011", "/bond")])
        # Declared DC-open, it is no assumption, and GA-12's position.
        found, compiled = self.run_text(text.replace(
            "    cy = new rhoform.lib.passive.Capacitor\n",
            "    cy = new rhoform.lib.passive.Capacitor\n"
            "    rule cy open a b\n"))
        self.assertEqual(sorted((d["code"], d["entity"]) for d in found),
                         [("RHO4004", "/cy"), ("RHO4011", "/bond")])

    def test_a_multi_terminal_passive_with_no_rules_joins_its_grounds(self):
        # GA section 1.4's galvanic passives with more than two pins, and
        # no annotation: one ground domain, nothing straddled (GA-16).
        for name, part, nets in (
                ("c21_choke_on_ground_return", "/l1", ["GND_IN", "GND"]),
                ("c22_kelvin_shunt_low_side", "/rs", ["GND_LOAD", "GND"])):
            with self.subTest(case=name):
                found, compiled = self.case(name)
                self.assertEqual(
                    [(d["code"], d["params"]["classes"]) for d in found],
                    [("RHO3901", ["assumed-galvanic-passive: 1"])])
                ground = compiled.analysis.ground
                self.assertEqual(list(ground.ground_domains), ["GND"])
                self.assertEqual(len(ground.isolation_domains), 1)
                self.assertIn({"entity": part, "status": "no-data",
                               "reason": "assumed-galvanic-passive",
                               "actionable": True,
                               "detail": {"nets": nets}},
                              self.rows(compiled))

    def test_unrelated_grounds_no_part_straddles_are_an_actionable_row(self):
        # GA-14c's own example: two subcircuits that share a signal net
        # and no ground relation. No part straddles both grounds, and what
        # each signal pin is referenced to is T5's (L3): a row, not a pass.
        text = P + """\
component Mcu:
    pin gnd power_in
    pin tx output
    pin vdd power_in
    ground gnd

component Sensor:
    pin gnd power_in
    pin rx input
    pin vdd power_in
    ground gnd

""" + TIE + """\
module Board:
    port v1 power_in
    port v2 power_in
    m = new Mcu
    s = new Sensor
    net GND_A:
        m.gnd
    net GND_B:
        s.gnd
    net SIG:
        m.tx
        s.rx
    net V1:
        m.vdd
        v1
    net V2:
        s.vdd
        v2
"""
        found, compiled = self.run_text(text)
        self.assertEqual(
            [(d["code"], d["params"]["classes"]) for d in found],
            [("RHO3901", ["unrelated-ground-domains: 1"])])
        rows = self.rows(compiled)
        self.assertIn({"entity": "GND_A", "status": "no-data",
                       "reason": "unrelated-ground-domains",
                       "actionable": True,
                       "detail": {"ground_domains": ["GND_A", "GND_B"]}},
                      rows)
        # The command line's run counts it among every section's gaps.
        found, _compiled = self.run_text(text, through=None)
        (note,) = [d for d in found if d["code"] == "RHO3901"]
        self.assertIn("unrelated-ground-domains: 1", note["params"]["classes"])
        # Tied, the grounds are one domain and there is nothing to decide.
        found, _compiled = self.run_text(text.replace(
            "    s = new Sensor\n", "    s = new Sensor\n    nt = new NetTie\n"
        ).replace("        m.gnd\n", "        m.gnd\n        nt.a\n").replace(
            "        s.gnd\n", "        s.gnd\n        nt.b\n"))
        self.assertEqual(found, [])
        # A part straddling them is RHO4010, which names them: no row.
        _found, compiled = self.case(
            "c16_component_straddles_unrelated_grounds")
        self.assertNotIn("unrelated-ground-domains",
                         [r["reason"] for r in self.rows(compiled)])


@unittest.skipUnless(HAVE_LARK, SKIP)
class ScanTest(_Ground):
    def test_the_kind_meet_reports_the_least_pair_with_both_spans(self):
        # Three specific kinds on one net: one finding, the two least.
        text = P + LOAD + """\
module Inner:
    port g passive
    a = new Load
    net SG(ground_kind = "signal"):
        a.gnd
        g

module Mid:
    port g passive
    i = new Inner
    net CG(ground_kind = "chassis"):
        g
        i.g

module Board:
    m = new Mid
    net PG(ground_kind = "power"):
        m.g
"""
        found, compiled = self.run_text(text)
        (conflict,) = found
        self.assertEqual((conflict["code"], conflict["entity"],
                          conflict["params"]),
                         ("RHO4001", "PG", {"net_a": "SG",
                                            "kind_a": "signal",
                                            "net_b": "PG",
                                            "kind_b": "power"}))
        self.assertEqual([s["primary"] for s in conflict["spans"]],
                         [True, False])
        self.assertIsNone(compiled.analysis.ground.ground_kind("PG"))
        self.assertTrue(compiled.analysis.ground.is_ground("PG"))

    def test_the_meet_does_not_depend_on_which_site_is_shallower(self):
        text = P + LOAD + """\
module Front:
    port gnd passive
    a = new Load
    net AG(ground_kind = "{inner}"):
        a.gnd
        gnd

module Board:
    f = new Front
    net PG(ground_kind = "{outer}"):
        f.gnd
"""
        seen = []
        for inner, outer in (("signal", "power"), ("power", "signal")):
            found, _compiled = self.run_text(
                text.format(inner=inner, outer=outer))
            (conflict,) = found
            seen.append((conflict["params"]["kind_a"],
                         conflict["params"]["kind_b"]))
        self.assertEqual(seen, [("signal", "power")] * 2)
        # `unspecified` meets anything.
        found, compiled = self.run_text(
            text.format(inner="unspecified", outer="chassis"))
        self.assertEqual(found, [])
        self.assertEqual(compiled.analysis.ground.ground_kind("PG"),
                         "chassis")

    def test_a_label_is_read_past_a_string_that_looks_like_one(self):
        text = P + LOAD + """\
module Front:
    port gnd passive
    a = new Load
    net AG(voltage_domain = "net X(", ground_kind = "signal"):
        a.gnd
        gnd

module Board:
    f = new Front
    net PG(ground_kind = "power"):
        f.gnd
"""
        found, _compiled = self.run_text(text)
        self.assertEqual(found[0]["params"]["net_a"], "AG")

    def test_the_tie_graph_loop_names_its_whole_cycle_in_order(self):
        found, _compiled = self.case("c18_third_tie_closes_triangle")
        (loop,) = found
        self.assertEqual(loop["params"]["cycle"],
                         ["AGND", "/t1", "DGND", "/t2", "PGND", "/t3",
                          "AGND"])
        self.assertEqual([s["label"] for s in loop["spans"]],
                         [None, "in the cycle", "in the cycle"])

    def test_a_tie_to_a_non_ground_net_is_transparent(self):
        text = P + LOAD + TIE + """\
module Board:
    load = new Load
    nt1 = new NetTie
    nt2 = new NetTie
    net GND:
        load.gnd
        nt1.a
        nt2.a
    net SENSE:
        nt1.b
        nt2.b
"""
        found, compiled = self.run_text(text)
        self.assertEqual(found, [])
        self.assertEqual(compiled.analysis.ground.tie_graph, ())
        self.assertFalse(compiled.analysis.ground.is_ground("SENSE"))

    def test_earth_joins_no_domain_and_is_no_crossing(self):
        text = P + """\
component Bridge2:
    pin a passive
    pin b passive
    pin c passive
    ground c

""" + TIE + """\
module Board:
    bond = new NetTie
    x = new Bridge2
    net CH(ground_kind = "chassis"):
        bond.a
        x.a
    net GND:
        x.b
    net PE(ground_kind = "earth"):
        bond.b
"""
        found, compiled = self.run_text(text)
        # The earth bond is safety-relevant; earth stays its own domain.
        self.assertEqual([(d["code"], d["params"]["boundary"])
                          for d in found], [("RHO4011", "earth")])
        ground = compiled.analysis.ground
        self.assertEqual(ground.ground_domain("PE"), "PE")
        self.assertEqual(ground.ground_domain("CH"), "CH")
        self.assertEqual(ground.tie_graph, (("/bond", "CH", "PE"),))
        # x straddles chassis and GND, two unrelated domains: RHO4010.
        text = text.replace("        x.b\n", "        x.b\n        x.c\n")
        found, _compiled = self.run_text(text)
        self.assertEqual(sorted((d["code"], d["entity"]) for d in found),
                         [("RHO4010", "/x"), ("RHO4011", "/bond")])

    def test_a_safety_capacitor_alone_relates_nothing_and_is_no_crossing(self):
        text = P + LOAD + """\
component YCap:
    pin a passive
    pin b passive
    bridge a b

module Board:
    load = new Load
    y = new YCap
    net CHASSIS(ground_kind = "chassis"):
        y.a
    net GND:
        load.gnd
        y.b
"""
        found, compiled = self.run_text(text)
        self.assertEqual([(d["code"], d["entity"]) for d in found],
                         [("RHO4011", "/y")])
        ground = compiled.analysis.ground
        self.assertNotEqual(ground.ground_domain("CHASSIS"),
                            ground.ground_domain("GND"))

    def test_contacts_carry_grounds_without_straddling_them(self):
        # A connector's contacts are transparent: two unrelated grounds
        # on one header are no crossing of the header's. The chip whose
        # grounds they are is.
        text = P + """\
component Chip:
    pin g1 power_in
    pin g2 power_in
    ground g1 g2

component Header:
    pin p1 passive
    pin p2 passive
    connector

module Board:
    chip = new Chip
    j = new Header
    net G1(ground_kind = "signal"):
        chip.g1
        j.p1
    net G2(ground_kind = "signal"):
        chip.g2
        j.p2
"""
        found, compiled = self.run_text(text)
        self.assertEqual([(d["code"], d["entity"]) for d in found],
                         [("RHO4010", "/chip")])
        self.assertEqual(compiled.analysis.ground.conduction_groups("/j"),
                         (("p1",), ("p2",)))

    def test_net_ties_are_the_well_formed_ties(self):
        _found, compiled = self.case("c03_star_ground")
        self.assertEqual(compiled.analysis.ground.net_ties, ("/t1", "/t2"))
        self.assertEqual(compiled.analysis.ground.tie_graph,
                         (("/t1", "AGND", "PGND"), ("/t2", "DGND", "PGND")))

    def test_a_net_on_two_sides_of_two_barriers_is_reported_once(self):
        text = P + """\
component Opto:
    pin a passive
    pin c passive
    pin e passive
    pin k passive
    side detector: c e
    side emitter: a k

""" + LOAD + """\
module Board:
    load = new Load
    o1 = new Opto
    o2 = new Opto
    net GND:
        load.gnd
        o1.e
        o1.k
        o2.e
        o2.k
"""
        found, _compiled = self.run_text(text)
        self.assertEqual([(d["code"], d["entity"],
                           d["params"]["barrier_component"])
                          for d in found], [("RHO4005", "GND", "/o1")])

    def test_a_chassis_reference_is_a_row(self):
        text = P + LOAD + """\
module Board:
    load = new Load
    net CH(ground_kind = "chassis"):
        load.gnd
"""
        found, compiled = self.run_text(text)
        self.assertEqual(found, [])
        self.assertIn({"entity": "/load", "status": "pass",
                       "reason": "chassis-as-reference",
                       "actionable": False, "detail": {"net": "CH"}},
                      self.rows(compiled))

    def test_each_component_reports_one_finding_per_code(self):
        # A part spanning the barrier with two of its groups reports once.
        text = (AREA / "reject" / "c12_resistor_across_barrier" /
                "main.rhoform").read_text(encoding="utf-8")
        text = text.replace("component IsoDcDc:", """\
component Bridge4:
    pin a passive
    pin b passive
    pin c passive
    pin d passive
    connector
    pass a b
    pass c d

component IsoDcDc:""").replace(
            "    fbr = new rhoform.lib.passive.Resistor\n",
            "    fbr = new rhoform.lib.passive.Resistor\n"
            "    two = new Bridge4\n").replace(
            "        fbr.b\n", "        fbr.b\n        two.a\n").replace(
            "        fbr.a\n", "        fbr.a\n        two.b\n").replace(
            "        r_pu.a\n", "        r_pu.a\n        two.c\n").replace(
            "        load.vdd\n", "        load.vdd\n        two.d\n")
        found, _compiled = self.run_text(text)
        self.assertEqual(sorted((d["code"], d["entity"]) for d in found),
                         [("RHO4005", "/fbr"), ("RHO4005", "/two")])


@unittest.skipUnless(HAVE_LARK, SKIP)
class BenchmarkTest(_Ground):
    """GA-16/17: each benchmark, as authored, has one ground domain, GND,
    of kind unspecified, in one isolation domain, and no RHO40xx."""

    def test_one_ground_domain_one_isolation_domain_no_finding(self):
        from rhoform.tests.test_benchmarks import isolated_copy, sources

        for source in sources():
            with self.subTest(benchmark=source.parent.name):
                entry = isolated_copy(source, self.tmp)
                found, compiled = self.compile(entry.parent, entry.name,
                                               through=None)
                self.assertEqual([d["code"] for d in found
                                  if d["code"].startswith("RHO40")], [])
                ground = compiled.analysis.ground
                self.assertEqual(ground.ground_domains, {"GND": ("GND",)})
                self.assertEqual(ground.ground_kind("GND"), "unspecified")
                self.assertEqual(len(ground.isolation_domains), 1)
                (domain,) = ground.isolation_domains
                self.assertEqual(
                    sorted(ground.isolation_domains[domain]),
                    sorted(compiled.design.nets[i].name
                           for i in range(len(compiled.design.nets))))
                self.assertEqual(ground.tie_graph, ())
                self.assertEqual(
                    [(r["entity"], r["reason"], r["actionable"])
                     for r in self.rows(compiled)],
                    [(domain, "isolation-domain", False),
                     ("GND", "ground-domain", False)]
                    if domain < "GND" else
                    [("GND", "ground-domain", False),
                     ("GND", "isolation-domain", False)])

    def test_the_ledger_holds_nothing_for_the_ground_pass(self):
        from rhoform.tests.test_benchmarks import known_findings

        self.assertEqual(known_findings()["L2c"], [])


@unittest.skipUnless(HAVE_LARK, SKIP)
class ErcUnchangedTest(_Ground):
    """ERC reads the real ground typing; on the benchmarks and every
    check/erc case it reaches exactly what it reached under the
    foundation's interim, label-only rule."""

    def erc(self, root, entry, interim):
        from rhoform.check import ground

        if interim:
            with mock.patch.object(ground, "run", interim_run):
                found, compiled = self.compile(root, entry, through="erc")
        else:
            found, compiled = self.compile(root, entry, through="erc")
        return ([d for d in found if d["code"].startswith("RHO31")],
                self.rows(compiled, "erc"), compiled)

    def roots(self):
        from rhoform.tests.test_benchmarks import isolated_copy, sources

        for source in sources():
            entry = isolated_copy(source, self.tmp)
            yield source.parent.name, entry.parent, entry.name
        for case in sorted((CHECK / "erc").glob("*/*/main.rhoform")):
            yield (f"erc/{case.parent.parent.name}/{case.parent.name}",
                   case.parent, case.name)

    def test_erc_findings_and_rows_match_the_interim_rule(self):
        count = 0
        for name, root, entry in self.roots():
            with self.subTest(design=name):
                real = self.erc(root, entry, interim=False)
                interim = self.erc(root, entry, interim=True)
                self.assertEqual(real[:2], interim[:2])
                # And for the same reason: the same nets are ground.
                model_nets = real[2].design.nets
                self.assertEqual(
                    [net.name for net in model_nets
                     if real[2].analysis.ground.is_ground(net.name)],
                    [net.name for net in model_nets
                     if net.ground_domain is not None])
                count += 1
        self.assertGreaterEqual(count, 3 + 34)


@unittest.skipUnless(HAVE_LARK, SKIP)
class NetTieHandOffTest(_Ground):
    """A net-tie with both pins on one net is GA-9's RHO4009 (spec 04
    section 4.8). The ground pass sees it first, so it is reported once,
    there: ERC's RHO3109 skips the pass's net_ties with an upstream-defect
    row (spec 05 section 1). Run as the command line runs it, every pass."""

    SHORTED = ("RHO3109", "RHO4009")

    def test_a_redundant_tie_is_reported_once_on_the_full_run(self):
        (root,) = AREA.glob("reject/c14_redundant_tie")
        found, compiled = self.compile(root, through=None)
        # Filtered to the codes about a part shorted onto one net: the full
        # run also reaches c14's undecoupled supplies (RHO3110) and the
        # coverage note, which are other rules' and not this test's.
        self.assertEqual([(d["code"], d["entity"]) for d in found
                          if d["code"] in self.SHORTED
                          or d["entity"] == "/nt"],
                         [("RHO4009", "/nt")])
        self.assertIn({"entity": "/nt", "status": "no-data",
                       "reason": "upstream-defect", "actionable": False,
                       "detail": {"codes": ["RHO4009"]}},
                      self.rows(compiled, "erc"))
        (note,) = [d for d in found if d["code"] == "RHO3901"]
        self.assertFalse([c for c in note["params"]["classes"]
                          if c.startswith("upstream-defect")])

    def test_only_a_net_tie_is_handed_on(self):
        found, compiled = self.run_text(P + LOAD + TIE + """\
component Strap:
    pin a passive
    pin b passive

module Board:
    port v power_in
    load = new Load
    nt = new NetTie:
        dnp
    s = new Strap
    net GND:
        load.gnd
        nt.a
        nt.b
        s.a
        s.b
    net V:
        load.vdd
        v
""", through=None)
        # A plain two-terminal part on one net is still ERC's; a DNP tie is
        # nothing's until fitted, and then the ground pass's.
        self.assertEqual([(d["code"], d["entity"]) for d in found
                          if d["code"] in self.SHORTED],
                         [("RHO3109", "/s")])
        self.assertEqual([r for r in self.rows(compiled, "erc")
                          if r["entity"] == "/nt"],
                         [{"entity": "/nt", "status": "pass",
                           "reason": "depends-on-dnp", "actionable": False,
                           "detail": {"codes": [], "codes_if_fitted":
                                      ["RHO4009"], "dnp": ["/nt"]}}])
        self.assertEqual(compiled.analysis.ground.net_ties, ("/nt",))


_PROBE = r'''
import hashlib, json, sys
from pathlib import Path
from rhoform import compile as pipeline, ir
from rhoform.diagnostics import Diagnostics
out = {}
for entry in map(Path, sys.argv[1:]):
    sink = Diagnostics()
    c = pipeline.compile(entry.name, entry.parent, sink=sink, through="ground")
    g = c.analysis.ground
    out[str(entry)] = {
        "stream": sink.render(),
        "rows": [r.as_dict() for r in c.report.sections["ground"]["rows"]],
        "ground": [list(g.ground_domains.items()),
                   list(g.isolation_domains.items()), list(g.tie_graph)]}
print(json.dumps(out, sort_keys=True))
'''


@unittest.skipUnless(HAVE_LARK, SKIP)
class DeterminismTest(unittest.TestCase):
    def test_streams_rows_and_domains_are_seed_independent(self):
        entries = [str(path) for path in sorted(AREA.glob("*/*/main.rhoform"))]
        self.assertGreaterEqual(len(entries), 20)
        runs = []
        for seed in ("0", "1", "4242"):
            done = subprocess.run(
                [sys.executable, "-c", _PROBE, *entries],
                env=dict(os.environ, PYTHONHASHSEED=seed,
                         PYTHONPATH=str(ROOT)),
                capture_output=True, text=True, timeout=300)
            self.assertEqual(done.returncode, 0, done.stderr)
            runs.append(json.loads(done.stdout))
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(runs[0], runs[2])


if __name__ == "__main__":
    unittest.main()
