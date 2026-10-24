"""The elaborator's contract: every naming, flattening and fabrication rule
of R13 slice 1 and R15, byte-true spans, and one test per RHO2xxx code.

Each code test plants exactly one defect in an otherwise valid file and
pins the code, its structured params and the bytes its primary span
covers, so a regression in any of the three shows up here.
"""

from decimal import Decimal
import json
import unittest

try:
    import lark  # noqa: F401 - availability probe only
    HAVE_LARK = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_LARK = False

PRAGMA = "#pragma rhoform-syntax 0.1"
P2 = "#pragma rhoform-syntax 0.2\n"


def _elaborate(body, path="design.rhoform", root=None):
    from rhoform.elaborate import elaborate_source

    return elaborate_source(PRAGMA + "\n" + body, path, root=root)


def _elaborate2(body, path="design.rhoform"):
    from rhoform.elaborate import elaborate_source

    return elaborate_source(P2 + body, path)


def _diagnostics(result):
    return [json.loads(line)
            for line in result.diagnostics.render().splitlines()]


def _codes(result):
    return [d["code"] for d in _diagnostics(result)]


def _text(source, span):
    data = (PRAGMA + "\n" + source).encode()
    return data[span["byte_start"]:span["byte_end"]].decode()


def _by_path(design):
    return {i.path: i for i in design.instances}


def _by_name(design):
    return {n.name: n for n in design.nets}


RESISTOR = """    {name} = new lib.R:
        pin a passive
        pin b passive
"""


@unittest.skipUnless(HAVE_LARK, "lark (pinned in toolchain/versions.yaml) "
                     "is required")
class NamingTest(unittest.TestCase):
    def test_module_path_sanitizes_each_segment(self):
        from rhoform.elaborate import module_path

        self.assertEqual(module_path("blinker-555.rhoform"), "blinker_555")
        self.assertEqual(module_path("lib/9v.rhoform"), "lib._9v")
        self.assertEqual(module_path("a/b.c.rhoform"), "a.b_c")
        self.assertEqual(module_path("./top.rhoform"), "top")

    def test_definition_is_module_path_plus_name(self):
        result = _elaborate("module Top:\n    port p passive\n",
                            path="benchmarks/blinker-555.rhoform")
        self.assertTrue(result.ok, result.diagnostics.render())
        root = _by_path(result.design)["/"]
        self.assertEqual(root.definition, "benchmarks.blinker_555.Top")
        self.assertEqual(root.kind, "module")
        self.assertEqual(result.design.design_name, "Top")
        self.assertEqual(result.design.language_version, "0.1.0")

    def test_root_is_the_module_nothing_instantiates(self):
        source = ("module Leaf:\n    port p passive\n"
                  "module Top:\n    x = new Leaf\n")
        result = _elaborate(source)
        self.assertTrue(result.ok)
        self.assertEqual(result.design.design_name, "Top")
        self.assertEqual(_by_path(result.design)["/x"].definition,
                         "design.Leaf")

    def test_an_explicit_root_selects_among_candidates(self):
        source = ("module A:\n    port p passive\n"
                  "module B:\n    port q passive\n")
        result = _elaborate(source, root="B")
        self.assertTrue(result.ok)
        self.assertEqual(result.design.design_name, "B")

    def test_single_word_is_a_module_dotted_is_a_component(self):
        # A dotted name outside the reserved prefix `rhoform.lib.` is an
        # ad-hoc component: its ports are its inline pins, verbatim.
        source = ("module Leaf:\n    port p passive\n"
                  "module Top:\n    m = new Leaf\n"
                  "    c = new acme.passive.Resistor:\n"
                  "        pin a passive 1\n        pin b passive 2\n")
        design = _elaborate(source).design
        instances = _by_path(design)
        self.assertEqual(instances["/m"].kind, "module")
        self.assertEqual(instances["/c"].kind, "component")
        self.assertEqual(instances["/c"].definition,
                         "acme.passive.Resistor")
        self.assertEqual(
            [(p.name, p.role, p.pin_numbers) for p in instances["/c"].ports],
            [("a", "passive", ("1",)), ("b", "passive", ("2",))])
        self.assertEqual([p.name for p in instances["/m"].ports], ["p"])


@unittest.skipUnless(HAVE_LARK, "lark required")
class FlatteningTest(unittest.TestCase):
    NESTED = """module Inner:
    port p passive
    port q passive
    d1 = new lib.D:
        pin a passive
        pin k passive
    net LED:
        p
        d1.a
    d1.k ~ q
module Mid:
    port p passive
    inner = new Inner
    inner.p ~ p
module Top:
    port vin power_in
    mid = new Mid
""" + RESISTOR.format(name="r1") + """    net VCC:
        vin
        mid.p
    r1.a ~ vin
    isolated r1.b
"""

    def setUp(self):
        self.result = _elaborate(self.NESTED)
        self.assertTrue(self.result.ok, self.result.diagnostics.render())
        self.design = self.result.design

    def test_hierarchy_becomes_paths(self):
        self.assertEqual(
            [i.path for i in self.design.instances],
            ["/", "/mid", "/mid/inner", "/mid/inner/d1", "/r1"])

    def test_module_ports_merge_nets_across_scopes(self):
        # vin, mid.p, inner.p and d1.a are one net; the root label wins.
        vcc = _by_name(self.design)["VCC"]
        self.assertEqual(vcc.members, (
            ("/", "vin"), ("/mid", "p"), ("/mid/inner", "p"),
            ("/mid/inner/d1", "a"), ("/r1", "a")))

    def test_an_endpoint_in_two_statements_merges_rather_than_errs(self):
        # r1.a is in a chain and (through vin) in VCC: one net, no error.
        self.assertEqual(self.result.diagnostics.counts()["error"], 0)
        self.assertNotIn("N_r1.a", _by_name(self.design))

    def test_unlabelled_net_is_named_by_least_member(self):
        names = _by_name(self.design)
        self.assertIn("N_mid/inner.q", names)
        self.assertEqual(names["N_mid/inner.q"].members,
                         (("/mid/inner", "q"), ("/mid/inner/d1", "k")))

    def test_isolated_yields_a_single_member_net(self):
        self.assertEqual(_by_name(self.design)["N_r1.b"].members,
                         (("/r1", "b"),))

    def test_a_root_port_spells_with_a_leading_dot(self):
        result = _elaborate("module Top:\n    port vin power_in\n"
                            + RESISTOR.format(name="r1")
                            + "    vin ~ r1.a\n")
        self.assertEqual([n.name for n in result.design.nets], ["N_.vin"])

    def test_an_inner_label_is_qualified_by_its_instance_path(self):
        source = """module Inner:
    port p passive
    d1 = new lib.D:
        pin a passive
        pin k passive
    net LED:
        d1.a
module Top:
    inner = new Inner
"""
        names = _by_name(_elaborate(source).design)
        self.assertIn("inner/LED", names)

    def test_labels_and_domains_merge_across_depths(self):
        source = """module Inner:
    port g passive
    net GND_IN(ground_domain = "gnd"):
        g
module Top:
    inner = new Inner
""" + RESISTOR.format(name="r1") + """    net GND(voltage_domain = "v0"):
        inner.g
        r1.a
"""
        net = _by_name(_elaborate(source).design)["GND"]
        self.assertEqual((net.ground_domain, net.voltage_domain),
                         ("gnd", "v0"))

    def test_a_module_used_twice_gives_each_copy_its_own_nets(self):
        source = """module Inner:
    port p passive
    d1 = new lib.D:
        pin a passive
    net LED:
        p
        d1.a
module Top:
    a = new Inner
    b = new Inner
"""
        result = _elaborate(source)
        self.assertTrue(result.ok)
        self.assertEqual([n.name for n in result.design.nets],
                         ["a/LED", "b/LED"])


@unittest.skipUnless(HAVE_LARK, "lark required")
class FabricationTest(unittest.TestCase):
    def test_module_instance_flags_are_inherited(self):
        source = """module Inner:
""" + RESISTOR.format(name="r1") + """module Top:
    inner = new Inner:
        dnp
        board_only
"""
        instances = _by_path(_elaborate(source).design)
        self.assertTrue(instances["/inner"].dnp)
        self.assertTrue(instances["/inner/r1"].dnp)
        self.assertTrue(instances["/inner/r1"].board_only)
        self.assertFalse(instances["/inner/r1"].exclude_from_bom)

    def test_component_flags_and_hardware_kinds(self):
        source = """module Top:
    mh = new lib.MountingHole:
        hardware mounting_hole
        exclude_from_bom
        board_only
    tp = new lib.TestPoint:
        pin p passive
        hardware test_point
        exclude_from_bom
        no board_only
    isolated tp.p
"""
        result = _elaborate(source)
        self.assertTrue(result.ok, result.diagnostics.render())
        instances = _by_path(result.design)
        self.assertEqual(instances["/mh"].hardware_kind, "mounting_hole")
        self.assertEqual(instances["/mh"].ports, ())
        self.assertTrue(instances["/mh"].board_only)
        self.assertEqual(instances["/tp"].hardware_kind, "test_point")
        self.assertFalse(instances["/tp"].board_only)

    def test_parts_bind_abstract_and_resolved(self):
        source = """module Top:
    a = new lib.R:
        part abstract:
            package = "0402"
    b = new lib.U:
        part "timer.555/ti-NE555P@2"
"""
        instances = _by_path(_elaborate(source).design)
        self.assertEqual(instances["/a"].part.binding, "abstract")
        self.assertEqual(instances["/a"].part.constraints,
                         {"package": "0402"})
        self.assertEqual(instances["/b"].part.binding, "resolved")
        self.assertEqual(instances["/b"].part.lockfile_key,
                         "timer.555/ti-NE555P@2")


@unittest.skipUnless(HAVE_LARK, "lark required")
class ValueTest(unittest.TestCase):
    def _parameter(self, literal):
        result = _elaborate(f"module Top:\n    x = new lib.R(v = {literal})\n")
        self.assertTrue(result.ok, result.diagnostics.render())
        return _by_path(result.design)["/x"].parameters["v"]

    def test_a_quantity_takes_its_normal_form_unit(self):
        from rhoform.elaborate import Quantity

        self.assertEqual(self._parameter("100000ohm +/- 1%"),
                         Quantity(Decimal("100"), "kohm",
                                  (Decimal("99"), Decimal("101"))))
        self.assertEqual(self._parameter("0.00000001F"),
                         Quantity(Decimal("10"), "nF"))
        self.assertEqual(self._parameter("9.5mA (8mA to 10.5mA)"),
                         Quantity(Decimal("9.5"), "mA",
                                  (Decimal("8"), Decimal("10.5"))))
        self.assertEqual(self._parameter("25degC"),
                         Quantity(Decimal("25"), "degC"))

    def test_every_t3_respelling_is_one_value(self):
        spellings = ("100kohm +/- 1%", "100000ohm +/- 1%",
                     "0.1Mohm +/- 1%", "100kohm +/- 1kohm",
                     "100kohm (99kohm to 101kohm)")
        values = {self._parameter(s) for s in spellings}
        self.assertEqual(len(values), 1)

    def test_strings_integers_and_booleans(self):
        self.assertEqual(self._parameter('"red"'), "red")
        self.assertEqual(self._parameter("42"), 42)
        self.assertIs(self._parameter("true"), True)
        self.assertEqual(self._parameter(str(2 ** 53)), 2 ** 53)

    def test_module_arguments_are_recorded_verbatim(self):
        source = ("module Leaf:\n    port p passive\n"
                  'module Top:\n    x = new Leaf(color = "red", n = 3)\n')
        instance = _by_path(_elaborate(source).design)["/x"]
        self.assertEqual(instance.parameters, {"color": "red", "n": 3})


@unittest.skipUnless(HAVE_LARK, "lark required")
class AssertionTest(unittest.TestCase):
    SOURCE = """module Inner:
    port p passive
    d1 = new lib.D:
        pin a passive
    net LED:
        p
        d1.a
    assert v dynamic operating_point(LED) within 900mV to 1.1V
module Top:
    inner = new Inner
    net OUT:
        inner.p
    assert duty dynamic duty_cycle(OUT) within 0.533 to 0.558
    assert hi static operating_point(OUT) at most 5V
    assert lo dynamic frequency(OUT) at least 2
"""

    def setUp(self):
        result = _elaborate(self.SOURCE)
        self.assertTrue(result.ok, result.diagnostics.render())
        self.by_path = {a.path: a for a in result.design.assertions}

    def test_paths_and_final_subject_names(self):
        self.assertEqual(sorted(self.by_path),
                         ["/duty", "/hi", "/inner/v", "/lo"])
        # LED lost to the shallower OUT, and the subject follows it.
        self.assertEqual(self.by_path["/inner/v"].subject, "OUT")

    def test_bounds_units(self):
        from rhoform.elaborate import Bounds

        self.assertEqual(self.by_path["/inner/v"].bounds,
                         Bounds("V", Decimal("0.9"), Decimal("1.1")))
        self.assertEqual(self.by_path["/duty"].bounds,
                         Bounds("1", Decimal("0.533"), Decimal("0.558")))
        self.assertEqual(self.by_path["/hi"].bounds,
                         Bounds("V", None, Decimal("5")))
        self.assertEqual(self.by_path["/lo"].bounds,
                         Bounds("1", Decimal("2"), None))


@unittest.skipUnless(HAVE_LARK, "lark required")
class TableTest(unittest.TestCase):
    def test_rows_become_components(self):
        source = """module Top:
    table lib.R part abstract (resistance, part.package):
        ra 1kohm "0402"
        rb 2.2kohm "0603"
    table lib.C part "cap-key" (capacitance):
        c1 100nF
"""
        result = _elaborate(source)
        self.assertTrue(result.ok, result.diagnostics.render())
        instances = _by_path(result.design)
        self.assertEqual(instances["/rb"].kind, "component")
        self.assertEqual(instances["/rb"].definition, "lib.R")
        self.assertEqual(instances["/rb"].parameters["resistance"].unit,
                         "kohm")
        self.assertEqual(instances["/rb"].part.constraints,
                         {"package": "0603"})
        self.assertEqual(instances["/rb"].ports, ())
        self.assertEqual(instances["/c1"].part.lockfile_key, "cap-key")


@unittest.skipUnless(HAVE_LARK, "lark required")
class SpanTest(unittest.TestCase):
    SOURCE = """module Top:  # header comment
    r1 = new lib.R(v = 1kohm)  # trailing comment
    # standalone comment
    r2 = new lib.R:
        pin a passive
        pin b passive

    net N:
        r2.a
    assert a dynamic frequency(N) within 1Hz to 2Hz
"""

    def setUp(self):
        self.result = _elaborate(self.SOURCE)
        self.assertTrue(self.result.ok, self.result.diagnostics.render())
        self.data = (PRAGMA + "\n" + self.SOURCE).encode()

    def text(self, span):
        return self.data[span.byte_start:span.byte_end].decode()

    def test_declarations_run_first_token_to_last_token(self):
        instances = _by_path(self.result.design)
        self.assertEqual(self.text(instances["/"].declaration),
                         "module Top:")
        self.assertEqual(self.text(instances["/r1"].declaration),
                         "r1 = new lib.R(v = 1kohm)")
        self.assertEqual(
            self.text(instances["/r2"].declaration),
            "r2 = new lib.R:\n        pin a passive\n        pin b passive")
        self.assertEqual(self.text(self.result.design.nets[0].declaration),
                         "net N:\n        r2.a")
        self.assertEqual(
            self.text(self.result.design.assertions[0].declaration),
            "assert a dynamic frequency(N) within 1Hz to 2Hz")

    def test_traces_run_innermost_first(self):
        source = """module Inner:
    d1 = new lib.D
module Top:
    inner = new Inner
"""
        result = _elaborate(source)
        data = (PRAGMA + "\n" + source).encode()
        trace = _by_path(result.design)["/inner/d1"].trace
        self.assertEqual(
            [data[s.byte_start:s.byte_end].decode() for s in trace],
            ["d1 = new lib.D", "inner = new Inner"])
        self.assertEqual(_by_path(result.design)["/"].trace, ())


@unittest.skipUnless(HAVE_LARK, "lark required")
class TotalityTest(unittest.TestCase):
    def test_a_failed_parse_is_not_elaborated(self):
        result = _elaborate("module Top:\n    port p pasive\n")
        self.assertIsNone(result.design)
        self.assertEqual(_codes(result), ["RHO1009"])

    def test_output_is_deterministic(self):
        source = FlatteningTest.NESTED
        first, second = _elaborate(source), _elaborate(source)
        self.assertEqual(first.design, second.design)

    def test_deep_hierarchies_do_not_recurse(self):
        depth = 1200
        lines = ["module M0:", "    port p passive"]
        for level in range(1, depth):
            lines += [f"module M{level}:", f"    x = new M{level - 1}"]
        result = _elaborate("\n".join(lines) + "\n")
        self.assertTrue(result.ok, result.diagnostics.render())
        self.assertEqual(len(result.design.instances), depth)

    def test_a_long_cycle_is_reported_without_recursing(self):
        depth = 1200
        lines = []
        for level in range(depth):
            lines += [f"module M{level}:",
                      f"    x = new M{(level + 1) % depth}"]
        result = _elaborate("\n".join(lines) + "\n")
        self.assertEqual(_codes(result), ["RHO2004"])


@unittest.skipUnless(HAVE_LARK, "lark required")
class Syntax02Test(unittest.TestCase):
    """Every 0.2 parse accept case elaborates without a traceback. Before
    0.2's semantics a15 crashed the elaborator with a QuantityError and
    a12/a13 elaborated "clean" with their bodies dropped. Imports have
    their semantics too: a09's, elaborated alone, name files it was not
    given (rhoform/tests/test_package.py covers resolution)."""

    def test_every_0_2_accept_case_elaborates_without_a_traceback(self):
        from pathlib import Path

        from rhoform.elaborate import elaborate_source

        accept = (Path(__file__).resolve().parents[2] / "spec"
                  / "conformance" / "parse" / "accept")
        seen = 0
        for path in sorted(accept.glob("*.rhoform")):
            source = path.read_text(encoding="utf-8")
            if not source.startswith("#pragma rhoform-syntax 0.2"):
                continue
            seen += 1
            with self.subTest(path.name):
                result = elaborate_source(source, path.name)
                codes = {d["code"] for d in _diagnostics(result)}
                if path.name == "a09_imports.rhoform":
                    self.assertEqual(codes, {"RHO2060"})
                    self.assertEqual(len(_diagnostics(result)), 2)
                    self.assertIsNone(result.design)
        self.assertEqual(seen, 9)

    def test_an_imported_component_elaborates_under_its_own_name(self):
        from rhoform.elaborate import elaborate
        from rhoform.parser import parse

        main = parse(P2 + 'import Led from "./parts/led"\n\n'
                     "module Top:\n    d = new Led\n    d.a ~ d.k\n",
                     file="top.rhoform")
        led = parse(P2 + "\ncomponent Led:\n    pin a passive 1\n"
                    "    pin k passive 2\n", file="parts/led.rhoform")
        result = elaborate([main, led])
        self.assertTrue(result.ok, result.diagnostics.render())
        self.assertEqual(_by_path(result.design)["/d"].definition,
                         "parts.led.Led")
        self.assertEqual([f.path for f in result.design.files],
                         ["parts/led.rhoform", "top.rhoform"])

    def test_a_0_2_file_of_0_1_constructs_still_elaborates(self):
        from rhoform.elaborate import elaborate_source

        result = elaborate_source(P2 + "module Top:\n"
                                  + RESISTOR.format(name="r1")
                                  + "    r1.a ~ r1.b\n")
        self.assertTrue(result.ok, result.diagnostics.render())
        self.assertEqual(result.design.language_version, "0.2.0")


@unittest.skipUnless(HAVE_LARK, "lark required")
class CodeTest(unittest.TestCase):
    """One planted defect per code: the code, its params, its span."""

    def only2(self, source, code):
        """`only` for a 0.2 source: the code, its params, the bytes its
        primary span covers."""
        from rhoform.elaborate import elaborate_source

        result = elaborate_source(P2 + source)
        diagnostics = _diagnostics(result)
        self.assertEqual([d["code"] for d in diagnostics], [code],
                         result.diagnostics.render())
        span = diagnostics[0]["spans"][0]
        text = (P2 + source).encode()[span["byte_start"]:span["byte_end"]]
        return diagnostics[0], text.decode(), result

    def only(self, source, code, root=None):
        result = _elaborate(source, root=root)
        diagnostics = _diagnostics(result)
        self.assertEqual([d["code"] for d in diagnostics], [code],
                         result.diagnostics.render())
        diagnostic = diagnostics[0]
        primary = diagnostic["spans"][0]
        return diagnostic, _text(source, primary), result

    def test_rho2001_duplicate_module(self):
        d, text, _ = self.only("module A:\n    port p passive\n"
                               "module A:\n    port q passive\n", "RHO2001")
        self.assertEqual(d["params"], {"name": "A"})
        self.assertEqual(text, "module A:")

    def test_rho2002_ambiguous_root(self):
        d, text, result = self.only("module A:\n    port p passive\n"
                                    "module B:\n    port q passive\n",
                                    "RHO2002")
        self.assertEqual(d["params"], {"candidates": ["A", "B"]})
        self.assertIsNone(result.design)

    def test_rho2003_unknown_root(self):
        d, _text_, _ = self.only("module A:\n    port p passive\n",
                                 "RHO2003", root="Z")
        self.assertEqual(d["params"], {"name": "Z", "candidates": ["A"]})

    def test_rho2004_instantiation_cycle(self):
        d, text, _ = self.only("module A:\n    x = new A\n", "RHO2004")
        self.assertEqual(d["params"], {"cycle": ["A"]})
        self.assertEqual(text, "x = new A")
        d, _t, _ = self.only("module Top:\n    a = new A\n"
                             "module A:\n    b = new B\n"
                             "module B:\n    a = new A\n", "RHO2004")
        self.assertEqual(d["params"], {"cycle": ["A", "B"]})

    def test_rho2005_unknown_definition(self):
        d, text, _ = self.only("module Leaf:\n    port p passive\n"
                               "module Top:\n    x = new Lef\n"
                               "    y = new Leaf\n", "RHO2005")
        self.assertEqual(d["params"], {"name": "Lef"})
        self.assertEqual(text, "Lef")
        self.assertEqual(d["fixits"][0]["edits"][0]["replacement"], "Leaf")

    def test_rho2005_typo_on_a_modules_only_use_is_not_also_rho2002(self):
        # The typo leaves Divider instantiated by nothing, so it looks like
        # a second root candidate beside Top. The unresolved name is the
        # defect; naming Divider as a possible root sends the author to the
        # wrong line.
        for body in ("    d = new Divder\n",
                     "    table Divder (v):\n        d 1V\n"):
            with self.subTest(body=body):
                d, text, result = self.only(
                    "module Divider:\n    port mid passive\n"
                    "module Top:\n" + body, "RHO2005")
                self.assertEqual(d["params"], {"name": "Divder"})
                self.assertEqual(text, "Divder")
                self.assertIsNone(result.design)

    def test_rho2006_table_of_modules(self):
        d, text, _ = self.only("module Leaf:\n    port p passive\n"
                               "module Top:\n    table Leaf ():\n"
                               "        a\n", "RHO2006")
        self.assertEqual(text, "Leaf")

    def test_rho2007_duplicate_declarations(self):
        cases = {
            "instance": RESISTOR.format(name="r") + RESISTOR.format(name="r"),
            "port": "    port p passive\n    port p input\n",
            "pin": "    r = new lib.R:\n        pin a passive\n"
                   "        pin a passive\n",
            "designator": "    r = new lib.R:\n        pin a passive 1 1\n",
            "argument": "    r = new lib.R(v = 1V, v = 2V)\n",
            "constraint": "    r = new lib.R:\n        part abstract:\n"
                          '            m = "a"\n            m = "b"\n',
            "net": RESISTOR.format(name="r")
                   + "    net N:\n        r.a\n    net N:\n        r.b\n",
            "net attribute": RESISTOR.format(name="r")
                             + '    net N(ground_domain = "g", '
                               'ground_domain = "g"):\n        r.a\n',
            "column": "    table lib.R (v, v):\n        a 1V 2V\n",
            "assertion": RESISTOR.format(name="r")
                         + "    net N:\n        r.a\n"
                           "    assert x dynamic frequency(N) at least 1Hz\n"
                           "    assert x dynamic frequency(N) at most 2Hz\n",
        }
        for kind, body in cases.items():
            with self.subTest(kind=kind):
                d, _t, _ = self.only("module Top:\n" + body, "RHO2007")
                self.assertEqual(d["params"]["kind"], kind)

    def test_rho2008_assertion_path_collision(self):
        d, _t, _ = self.only(
            "module Top:\n" + RESISTOR.format(name="x")
            + "    net N:\n        x.a\n"
              "    assert x dynamic frequency(N) at least 1Hz\n", "RHO2008")
        self.assertEqual(d["params"], {"name": "x", "module": "Top"})

    def test_rho2009_fact_on_module_instance(self):
        for fact, line in (("pin", "pin a passive"), ("part", "part \"k\""),
                           ("hardware", "hardware test_point"),
                           ("no board_only", "no board_only")):
            with self.subTest(fact=fact):
                d, text, _ = self.only(
                    "module Leaf:\n    port p passive\n"
                    f"module Top:\n    x = new Leaf:\n        {line}\n",
                    "RHO2009")
                self.assertEqual(d["params"], {"fact": fact, "instance": "x",
                                               "module": "Leaf"})
                self.assertEqual(text, line)
                self.assertEqual(d["entity"], "/x")

    def test_rho2010_repeated_instance_fact(self):
        d, _t, _ = self.only("module Top:\n    x = new lib.H:\n"
                             "        hardware fiducial\n"
                             "        hardware artwork\n", "RHO2010")
        self.assertEqual(d["params"], {"fact": "hardware", "instance": "x"})
        d, _t, _ = self.only('module Top:\n    x = new lib.U:\n'
                             '        part "a"\n        part "b"\n',
                             "RHO2010")
        self.assertEqual(d["params"]["fact"], "part")

    def test_rho2011_repeated_flag_is_a_warning(self):
        d, _t, result = self.only("module Top:\n    x = new lib.U:\n"
                                  "        dnp\n        dnp\n", "RHO2011")
        self.assertEqual(d["severity"], "warning")
        self.assertTrue(result.ok)

    def test_rho2012_contradictory_flag(self):
        d, text, _ = self.only("module Top:\n    x = new lib.U:\n"
                               "        board_only\n        no board_only\n",
                               "RHO2012")
        self.assertEqual(d["params"], {"flag": "board_only", "instance": "x"})
        self.assertEqual(text, "no board_only")

    def test_rho2013_hardware_port_arity(self):
        cases = (
            ("mounting_hole", "        pin p passive\n", "1 pin(s)"),
            ("test_point", "", "no pins"),
            ("test_point", "        pin p input\n", "one `input` pin"),
            ("grounded_mounting_hole",
             "        pin p passive\n        pin q passive\n", "2 pins"),
        )
        for kind, pins, found in cases:
            with self.subTest(kind=kind, found=found):
                d, text, _ = self.only(
                    f"module Top:\n    x = new lib.H:\n{pins}"
                    f"        hardware {kind}\n", "RHO2013")
                self.assertEqual(d["params"]["found"], found)
                self.assertEqual(text, f"hardware {kind}")
                self.assertEqual(d["entity"], "/x")

    def test_rho2014_abstract_part_without_constraints(self):
        d, _t, _ = self.only("module Top:\n    x = new lib.U:\n"
                             "        part abstract\n", "RHO2014")
        self.assertEqual(d["params"], {"instance": "x"})
        d, _t, _ = self.only("module Top:\n    table lib.R part abstract "
                             "(v):\n        a 1V\n", "RHO2014")
        self.assertEqual(d["params"], {"instance": "lib.R"})

    def test_rho2015_empty_part_key(self):
        d, _t, _ = self.only('module Top:\n    x = new lib.U:\n'
                             '        part ""\n', "RHO2015")
        self.assertEqual(d["params"], {"instance": "x"})

    def test_rho2016_interval_without_nominal(self):
        d, text, _ = self.only("module Top:\n    x = new lib.U(v = 3V to "
                               "3.6V)\n", "RHO2016")
        self.assertEqual(d["params"], {"literal": "3V to 3.6V", "name": "v"})
        self.assertEqual(text, "3V to 3.6V")

    def test_rho2017_number_not_representable(self):
        big = str(2 ** 53 + 1)
        d, text, _ = self.only(f"module Top:\n    x = new lib.U(n = {big})\n",
                               "RHO2017")
        self.assertEqual(text, big)
        huge = "1" + "0" * 400 + "V"
        d, _t, _ = self.only(f"module Top:\n    x = new lib.U(v = {huge})\n",
                             "RHO2017")
        self.assertEqual(d["params"], {"literal": huge})

    def test_rho2017_bounds_every_integer_literal_however_long(self):
        """2^53 bounds every integer literal, not only values, and is
        decided without int(): CPython refuses to convert a digit string
        past sys.get_int_max_str_digits (4300 by default), which used to
        crash the elaborator at each of these sites."""
        long = "1" * 5000
        leaf = "component L:\n    pin a passive\n\n"
        sites = {
            "argument": "module Top:\n    x = new X.R(n = {n})\n",
            "table cell": leaf + "module Top:\n    table L (n):\n"
                          "        t1  {n}\n",
            "default": "module Sub(n: int = {n}):\n    port a passive\n\n"
                       "module Top:\n    s = new Sub\n",
            "condition": "module Top(n: int = 1):\n    if n > {n}:\n"
                         "        x = new X.R\n",
            "array size": leaf + "module Top:\n    ls = new L[{n}]\n",
            "range bound": "module Top:\n    port a passive\n"
                           "    port b passive\n    for i in range({n}):\n"
                           "        a ~ b\n",
            "upper range bound": "module Top:\n    port a passive\n"
                                 "    port b passive\n"
                                 "    for i in range(1, {n}):\n"
                                 "        a ~ b\n",
            "index": leaf + "module Top:\n    port a passive\n"
                     "    ls = new L[2]\n    a ~ ls[{n}].a\n",
            "index offset": leaf + "module Top:\n    port a passive\n"
                            "    ls = new L[2]\n"
                            "    for i in range(1):\n"
                            "        a ~ ls[i + {n}].a\n",
        }
        for site, template in sites.items():
            for literal in (long, "-" + long, str(2 ** 53 + 1)):
                with self.subTest(site=site, literal=literal[:20]):
                    d, text, _ = self.only2(template.format(n=literal),
                                            "RHO2017")
                    self.assertEqual(text, literal)
                    self.assertEqual(d["params"], {"literal": literal})
        # The bound is inclusive, as for values: 2^53 itself is a size
        # past the budget, not an unrepresentable number.
        self.only2(leaf + f"module Top:\n    ls = new L[{2 ** 53}]\n",
                   "RHO2046")

    def test_rho2018_table_row_arity_is_reported_against_the_header(self):
        d, text, _ = self.only("module Top:\n    table lib.R (a, b):\n"
                               "        r1 1V\n", "RHO2018")
        self.assertEqual(d["params"], {"row": "r1", "values": 1,
                                       "columns": 2})
        self.assertEqual(text, "table lib.R (a, b)")
        self.assertEqual(_text("module Top:\n    table lib.R (a, b):\n"
                               "        r1 1V\n", d["spans"][1]), "r1 1V")

    def test_rho2019_invalid_table_column(self):
        d, text, _ = self.only("module Top:\n    table lib.R (x.y):\n"
                               "        r1 1V\n", "RHO2019")
        self.assertEqual(d["params"], {"column": "x.y"})

    def test_rho2020_part_column_without_binding(self):
        d, _t, _ = self.only('module Top:\n    table lib.R (part.m):\n'
                             '        r1 "a"\n', "RHO2020")
        self.assertEqual(d["params"], {"column": "part.m"})

    def test_rho2021_unknown_instance(self):
        d, text, _ = self.only("module Top:\n" + RESISTOR.format(name="r1")
                               + "    rr1.a ~ r1.b\n", "RHO2021")
        self.assertEqual(d["params"], {"instance": "rr1", "module": "Top"})
        self.assertEqual(text, "rr1")
        self.assertEqual(d["fixits"][0]["edits"][0]["replacement"], "r1")

    def test_rho2022_unknown_port(self):
        d, text, _ = self.only("module Top:\n" + RESISTOR.format(name="r1")
                               + "    r1.c ~ r1.b\n", "RHO2022")
        self.assertEqual(d["params"], {"instance": "r1",
                                       "definition": "lib.R", "port": "c"})
        self.assertEqual(text, "c")
        self.assertEqual(d["entity"], "/r1")

    def test_rho2023_unknown_own_port(self):
        d, text, _ = self.only("module Top:\n    port vin power_in\n"
                               + RESISTOR.format(name="r1")
                               + "    vni ~ r1.b\n", "RHO2023")
        self.assertEqual(d["params"], {"name": "vni", "module": "Top"})
        self.assertEqual(d["fixits"][0]["edits"][0]["replacement"], "vin")

    def test_rho2024_nc_port_connected(self):
        d, text, _ = self.only("module Top:\n    x = new lib.U:\n"
                               "        pin n nc\n    isolated x.n\n",
                               "RHO2024")
        self.assertEqual(d["params"], {"endpoint": "x.n"})

    def test_rho2025_repeated_endpoint_is_a_warning(self):
        d, text, result = self.only("module Top:\n"
                                    + RESISTOR.format(name="r1")
                                    + "    net N:\n        r1.a\n"
                                      "        r1.a\n", "RHO2025")
        self.assertEqual(d["severity"], "warning")
        self.assertTrue(result.ok)
        self.assertEqual(result.design.nets[0].members, (("/r1", "a"),))

    def test_rho2026_isolated_endpoint_connected(self):
        d, text, _ = self.only("module Top:\n" + RESISTOR.format(name="r1")
                               + "    isolated r1.a\n    r1.a ~ r1.b\n",
                               "RHO2026")
        self.assertEqual(d["params"], {"endpoint": "r1.a", "other": "r1.b"})
        self.assertEqual(text, "isolated r1.a")
        self.assertEqual(d["entity"], "N_r1.a")

    def test_rho2027_conflicting_net_labels(self):
        d, _t, _ = self.only("module Top:\n" + RESISTOR.format(name="r1")
                             + "    net A:\n        r1.a\n"
                               "    net B:\n        r1.a\n", "RHO2027")
        self.assertEqual(d["params"], {"labels": ["A", "B"]})

    def test_rho2028_conflicting_net_domain(self):
        source = ("module Inner:\n    port g passive\n"
                  '    net L(ground_domain = "agnd"):\n        g\n'
                  "module Top:\n    inner = new Inner\n"
                  '    net GND(ground_domain = "gnd"):\n        inner.g\n')
        d, text, _ = self.only(source, "RHO2028")
        self.assertEqual(d["params"], {"net": "GND",
                                       "attribute": "ground_domain",
                                       "first": "gnd", "second": "agnd"})
        self.assertEqual(d["entity"], "GND")

    def test_rho2029_unknown_assertion_subject(self):
        d, text, _ = self.only("module Top:\n" + RESISTOR.format(name="r1")
                               + "    net OUT:\n        r1.a\n"
                                 "    assert f dynamic frequency(OTU) at "
                                 "least 1Hz\n", "RHO2029")
        self.assertEqual(d["params"], {"subject": "OTU", "module": "Top"})
        self.assertEqual(text, "OTU")

    def test_rho2030_static_assertion_with_dynamic_measurement(self):
        d, text, _ = self.only("module Top:\n" + RESISTOR.format(name="r1")
                               + "    net OUT:\n        r1.a\n"
                                 "    assert f static frequency(OUT) at "
                                 "least 1Hz\n", "RHO2030")
        self.assertEqual(d["params"], {"name": "f",
                                       "measurement": "frequency"})
        self.assertEqual(text, "frequency")
        self.assertEqual(d["entity"], "/f")

    def test_rho2031_inverted_assertion_bounds(self):
        d, _t, _ = self.only("module Top:\n" + RESISTOR.format(name="r1")
                             + "    net OUT:\n        r1.a\n"
                               "    assert d dynamic duty_cycle(OUT) within "
                               "0.6 to 0.5\n", "RHO2031")
        self.assertEqual(d["params"], {"low": "0.6", "high": "0.5"})

    def test_rho2032_empty_net_domain(self):
        d, _t, _ = self.only("module Top:\n" + RESISTOR.format(name="r1")
                             + '    net N(voltage_domain = ""):\n'
                               "        r1.a\n", "RHO2032")
        self.assertEqual(d["params"], {"net": "N",
                                       "attribute": "voltage_domain"})

    LED = "component Led:\n    pin a passive 1\n    pin k passive 2\n\n"
    RES = ("component Res(resistance: resistance, package: string = "
           '"0402"):\n    pin a passive 1\n    pin b passive 2\n\n')

    def test_rho2034_duplicate_definition(self):
        d, text, _ = self.only2(
            self.LED + "component Led:\n    pin x passive\n\n"
            "module Top:\n    d = new Led\n    isolated d.a\n", "RHO2034")
        self.assertEqual(d["params"], {"name": "Led", "first": "component",
                                       "second": "component"})
        self.assertEqual(text, "component Led:")
        self.assertEqual(d["spans"][1]["label"], "first defined here")

    def test_rho2035_component_pin_mismatch(self):
        d, text, _ = self.only2(
            self.LED + "module Top:\n    d = new Led:\n"
            "        pin a passive 1\n        pin k passive 3\n"
            "    isolated d.a\n", "RHO2035")
        self.assertEqual(d["params"], {
            "instance": "d", "pin": "k", "component": "Led",
            "found": "`pin k passive 3`", "expected": "`pin k passive 2`"})
        self.assertEqual(text, "pin k passive 3")
        self.assertEqual(d["entity"], "/d")
        # A pin the instance leaves out is reported against the definition
        # name it instantiates; one the definition lacks, against its line.
        result = _elaborate2(self.LED + "module Top:\n    d = new Led:\n"
                             "        pin a passive 1\n"
                             "        pin z passive 9\n    isolated d.a\n")
        found = {(x["params"]["pin"], x["params"]["found"],
                  x["params"]["expected"]) for x in _diagnostics(result)}
        self.assertEqual(found, {
            ("k", "no such pin", "`pin k passive 2`"),
            ("z", "`pin z passive 9`", "no such pin")})

    def test_rho2036_unknown_parameter(self):
        d, text, _ = self.only2(
            self.RES + "module Top:\n    r = new Res(pakage = \"0603\", "
            "resistance = 1kohm)\n    isolated r.a\n", "RHO2036")
        self.assertEqual(d["params"], {"name": "pakage", "definition": "Res",
                                       "parameters": ["resistance",
                                                      "package"]})
        self.assertEqual(text, "pakage")
        self.assertEqual(d["fixits"][0]["edits"][0]["replacement"],
                         "package")
        self.assertEqual(d["entity"], "/r")

    def test_rho2037_missing_argument(self):
        d, text, _ = self.only2(
            self.RES + "module Top:\n    r = new Res\n    isolated r.a\n",
            "RHO2037")
        self.assertEqual(d["params"], {"instance": "r",
                                       "parameter": "resistance",
                                       "definition": "Res"})
        self.assertEqual(text, "Res")
        # The root has no instantiation to give a value: its parameters
        # need defaults.
        d, text, _ = self.only2("module Top(n: int):\n    port p passive\n",
                                "RHO2037")
        self.assertEqual(d["params"]["instance"], "/")
        self.assertEqual(text, "n: int")
        self.assertEqual(d["entity"], "/")

    def test_rho2038_value_type_mismatch(self):
        cases = (
            (self.RES + "module Top:\n    r = new Res(resistance = 5)\n"
             "    isolated r.a\n", "5", "an int", "a resistance"),
            ("module Top(n: int = 1V):\n    port p passive\n",
             "1V", "a voltage", "an int"),
            ("module Top(s: string = \"a\"):\n    port p passive\n"
             "    if s:\n        isolated p\n", "s", "a string", "a bool"),
            ("module Top(v: voltage = 1V):\n    port p passive\n"
             "    if v < 2A:\n        isolated p\n", "2A", "a current",
             "a voltage"),
            ("module Top(s: string = \"a\"):\n    port p passive\n"
             "    if s < \"b\":\n        isolated p\n", "s", "a string",
             "an int or a quantity"),
            ("module Top(v: voltage = 1V):\n    port p passive\n"
             "    if v == 1V +/- 1%:\n        isolated p\n", "1V +/- 1%",
             "a toleranced voltage", "an exact voltage"),
            ("module Top(s: string = \"a\"):\n    port p passive\n"
             "    for i in range(s):\n        isolated p\n", "s",
             "a string", "an int"),
        )
        for source, value, found, expected in cases:
            with self.subTest(value=value, expected=expected):
                d, text, _ = self.only2(source, "RHO2038")
                self.assertEqual(text, value)
                self.assertEqual((d["params"]["found"],
                                  d["params"]["expected"]),
                                 (found, expected))

    def test_rho2039_unknown_parameter_reference(self):
        d, text, _ = self.only2(
            "module Top(limit: int = 2):\n    port p passive\n"
            "    if limt > 1:\n        isolated p\n", "RHO2039")
        self.assertEqual(d["params"], {"name": "limt", "definition": "Top"})
        self.assertEqual(d["fixits"][0]["edits"][0]["replacement"], "limit")
        # A default may name only an EARLIER parameter.
        d, text, _ = self.only2(
            "module Top(a: int = b, b: int = 1):\n    port p passive\n",
            "RHO2039")
        self.assertEqual(text, "b")

    def test_rho2040_misplaced_statement(self):
        cases = (
            ("    for i in range(2):\n        port q passive\n",
             "a `port` declaration", "a `for` loop"),
            ("    if b:\n        port q passive\n",
             "a `port` declaration", "an `if` statement"),
            ("    for i in range(2):\n        if b:\n"
             "            x = new lib.R\n",
             "an instance declaration", "a `for` loop"),
            ("    for i in range(2):\n        table lib.R ():\n"
             "            r1\n", "a table", "a `for` loop"),
            ("    for i in range(2):\n        assert v dynamic "
             "frequency(N) at least 1Hz\n", "an assertion", "a `for` loop"),
        )
        for body, statement, construct in cases:
            with self.subTest(statement=statement, construct=construct):
                d, _t, _ = self.only2(
                    "module Top(b: bool = true):\n    port p passive\n"
                    + body, "RHO2040")
                self.assertEqual((d["params"]["statement"],
                                  d["params"]["construct"]),
                                 (statement, construct))

    def test_rho2041_shadowed_loop_variable(self):
        d, text, _ = self.only2(
            "module Top:\n    port p passive\n    for i in range(2):\n"
            "        for i in range(2):\n            isolated p\n",
            "RHO2041")
        self.assertEqual(d["params"], {"name": "i", "shadowed":
                                       "an enclosing loop variable"})
        self.assertEqual(text, "i")

    def test_rho2042_invalid_array_size(self):
        d, text, _ = self.only2(
            "module Top:\n    x = new lib.R[0]\n", "RHO2042")
        self.assertEqual(d["params"], {"array": "x", "size": 0})
        self.assertEqual(text, "lib.R[0]")

    def test_rho2043_index_out_of_range(self):
        d, text, _ = self.only2(
            self.LED + "module Top:\n    leds = new Led[2]\n"
            "    for i in range(2):\n        leds[i].k ~ leds[i + 1].a\n",
            "RHO2043")
        self.assertEqual(d["params"], {"endpoint": "leds[2].a", "index": 2,
                                       "array": "leds", "last": 1})
        self.assertEqual(text, "leds[i + 1].a")

    def test_rho2044_array_needs_index(self):
        d, text, _ = self.only2(
            self.LED + "module Top:\n    leds = new Led[2]\n"
            "    isolated leds.a\n", "RHO2044")
        self.assertEqual(d["params"], {"array": "leds", "size": 2})
        self.assertEqual(text, "leds")

    def test_rho2045_index_on_non_array(self):
        d, text, _ = self.only2(
            self.LED + "module Top:\n    d = new Led\n    isolated d[0].a\n",
            "RHO2045")
        self.assertEqual(d["params"], {"instance": "d"})
        self.assertEqual(text, "d[0]")

    def test_rho2046_expansion_limit(self):
        import time

        start = time.perf_counter()
        d, text, result = self.only2(
            "module Top:\n    port p passive\n"
            "    for i in range(1000000000000):\n        isolated p\n",
            "RHO2046")
        self.assertEqual(d["params"], {"construct": "a `for` loop",
                                       "limit": 4096})
        self.assertEqual(text, "for i in range(1000000000000)")
        d, text, _ = self.only2("module Top:\n    x = new lib.R[5000]\n",
                                "RHO2046")
        self.assertEqual(d["params"]["construct"], "an array")
        # Counted over every instance: 3 x 2000 iterations.
        d, text, _ = self.only2(
            "module Leaf:\n    port p passive\n    for i in range(2000):\n"
            "        isolated p\n\nmodule Top:\n    x = new Leaf[3]\n",
            "RHO2046")
        self.assertEqual(text, "for i in range(2000)")
        # Nested hierarchies of arrays stop at the budget, quickly.
        source = "module M0:\n    port p passive\n"
        for level in range(1, 8):
            source += f"\nmodule M{level}:\n    x = new M{level - 1}[64]\n"
        d, _t, _ = self.only2(source, "RHO2046")
        self.assertLess(time.perf_counter() - start, 10)

    def test_rho2046_is_reported_once_and_never_blames_a_bystander(self):
        # Loops are charged before arrays, so once the loops had spent the
        # budget the 100-member array was blamed as well, and every later
        # loop that could not fit drew its own report.
        d, text, _ = self.only2(
            "module Top:\n    port p passive\n    x = new lib.R[100]\n\n"
            "    for i in range(50):\n        for j in range(100):\n"
            "            isolated p\n", "RHO2046")
        self.assertEqual(text, "for j in range(100)")
        d, text, _ = self.only2(
            "module Top:\n    port p passive\n\n"
            "    for i in range(20):\n        for j in range(20):\n"
            "            for k in range(20):\n                isolated p\n",
            "RHO2046")
        self.assertEqual(text, "for k in range(20)")

    def test_rho2046_is_one_diagnostic_when_instances_share_the_body(self):
        # big1 and big2 give Bank one environment, so the body that passes
        # the budget is evaluated once; its RHO2046 was held with that
        # environment's findings and, since small's environment does not
        # show it, published once per instance path. The design draws one.
        d, text, result = self.only2(
            "module Bank(n: int = 8):\n    port p passive\n"
            "    rs = new rhoform.lib.passive.Resistor[n]\n"
            "    for i in range(n):\n        rs[i].a ~ p\n\n"
            "module Top:\n    big1 = new Bank(n = 5000)\n"
            "    big2 = new Bank(n = 5000)\n    small = new Bank\n",
            "RHO2046")
        self.assertEqual(text, "for i in range(n)")
        self.assertIsNone(d["entity"])
        self.assertIsNone(result.design)

    def test_rho2047_no_root_module(self):
        d, text, result = self.only2(self.LED, "RHO2047")
        self.assertEqual(d["params"], {"file": "design.rhoform"})
        self.assertIsNone(result.design)

    def test_rho2067_unknown_library_definition(self):
        d, text, result = self.only(
            "module Top:\n    r1 = new rhoform.lib.passive.Resistr\n",
            "RHO2067")
        self.assertEqual(d["params"], {"name": "rhoform.lib.passive.Resistr"})
        self.assertEqual(text, "rhoform.lib.passive.Resistr")
        self.assertEqual(d["fixits"][0]["edits"][0]["replacement"],
                         "rhoform.lib.passive.Resistor")
        self.assertEqual(d["fixits"][0]["applicability"], "needs-review")
        self.assertIsNone(result.design)

    def test_every_block_two_code_has_a_test_here(self):
        # Here, or for the package layer's codes in test_package.CodesTest.
        from rhoform import codes
        from rhoform.tests.test_package import CodesTest

        block = {c.code for c in codes.REGISTRY if c.code.startswith("RHO2")}
        tested = {name.split("_")[1].upper()
                  for name in dir(self) + dir(CodesTest)
                  if name.startswith("test_rho2")}
        self.assertEqual(block, tested)
        self.assertFalse({code for code, _s, _r in codes.RETIRED} & tested)

    def test_a_defect_in_a_reused_module_is_reported_once(self):
        source = ("module Inner:\n    x = new lib.H:\n"
                  "        hardware fiducial\n        pin p passive\n"
                  "module Top:\n    a = new Inner\n    b = new Inner\n")
        result = _elaborate(source)
        diagnostics = _diagnostics(result)
        self.assertEqual([d["code"] for d in diagnostics], ["RHO2013"])
        # Two instances share the definition: no single entity exists.
        self.assertIsNone(diagnostics[0]["entity"])

    def test_a_net_defect_in_a_reused_module_is_reported_once(self):
        # The flatten-phase checks see one net per copy; spec 04 still
        # counts the defect once per module, with no single entity.
        cases = {
            "RHO2027": ("module Channel:\n    port vin power_in\n"
                        + RESISTOR.format(name="r1")
                        + "    net VIN:\n        vin\n        r1.a\n"
                          "    net VDD:\n        r1.a\n"
                          "module Top:\n    a = new Channel\n"
                          "    b = new Channel\n    c = new Channel\n",
                        ["RHO2027"], {"labels": ["a/VDD", "a/VIN"]}),
            "RHO2026": ("module Probe:\n" + RESISTOR.format(name="r1")
                        + "    isolated r1.a\n    r1.a ~ r1.b\n"
                          "module Top:\n    p1 = new Probe\n"
                          "    p2 = new Probe\n",
                        ["RHO2026"], {"endpoint": "r1.a",
                                      "other": "p1/r1.b"}),
            "RHO2028": ("module Sensor:\n" + RESISTOR.format(name="r1")
                        + '    net AGND(ground_domain = "agnd"):\n'
                          "        r1.a\n"
                          '    net DGND(ground_domain = "dgnd"):\n'
                          "        r1.a\n"
                          "module Top:\n    s1 = new Sensor\n"
                          "    s2 = new Sensor\n",
                        ["RHO2027", "RHO2028"],
                        {"net": "s1/AGND", "attribute": "ground_domain",
                         "first": "agnd", "second": "dgnd"}),
        }
        for code, (source, expected, params) in cases.items():
            with self.subTest(code=code):
                diagnostics = _diagnostics(_elaborate(source))
                self.assertEqual(sorted(d["code"] for d in diagnostics),
                                 expected)
                for d in diagnostics:
                    self.assertIsNone(d["entity"])
                d = next(d for d in diagnostics if d["code"] == code)
                self.assertEqual(d["params"], params)

    def test_copies_of_one_net_defect_keep_a_shared_entity(self):
        # Both copies land on the root's GND: one defect, one entity.
        source = ("module Inner:\n    port g passive\n"
                  '    net L(ground_domain = "agnd"):\n        g\n'
                  "module Top:\n    a = new Inner\n    b = new Inner\n"
                  '    net GND(ground_domain = "gnd"):\n'
                  "        a.g\n        b.g\n")
        diagnostics = _diagnostics(_elaborate(source))
        self.assertEqual([(d["code"], d["entity"]) for d in diagnostics],
                         [("RHO2028", "GND")])

    def test_two_net_defects_on_one_span_stay_two(self):
        # One label clashes on both attributes: two defects, not copies.
        source = ("module Inner:\n    port g passive\n"
                  '    net L(ground_domain = "agnd", '
                  'voltage_domain = "3v3"):\n        g\n'
                  "module Top:\n    inner = new Inner\n"
                  '    net GND(ground_domain = "gnd", '
                  'voltage_domain = "5v"):\n        inner.g\n')
        diagnostics = _diagnostics(_elaborate(source))
        self.assertEqual(sorted(d["params"]["attribute"]
                                for d in diagnostics),
                         ["ground_domain", "voltage_domain"])


# --------------------------------------------------------------------------
# Syntax 0.2 semantics: components, parameters, if/else, arrays, for
# --------------------------------------------------------------------------

LED = "component Led:\n    pin a passive 1\n    pin k passive 2\n\n"


@unittest.skipUnless(HAVE_LARK, "lark required")
class ComponentTest(unittest.TestCase):
    def test_an_instance_takes_its_ports_from_the_definition(self):
        result = _elaborate2(LED + "module Top:\n    d = new Led\n"
                             "    d2 = new Led:\n        pin a passive 1\n"
                             "        pin k passive 2\n        dnp\n"
                             "    d.a ~ d2.k\n")
        self.assertTrue(result.ok, result.diagnostics.render())
        instances = _by_path(result.design)
        for path in ("/d", "/d2"):
            self.assertEqual(instances[path].kind, "component")
            self.assertEqual(instances[path].definition, "design.Led")
            self.assertEqual(
                [(p.name, p.role, p.pin_numbers)
                 for p in instances[path].ports],
                [("a", "passive", ("1",)), ("k", "passive", ("2",))])
        self.assertTrue(instances["/d2"].dnp)

    def test_hardware_arity_is_checked_against_the_definition(self):
        result = _elaborate2(LED + "module Top:\n    d = new Led:\n"
                             "        hardware test_point\n")
        self.assertEqual(_codes(result), ["RHO2013"])

    def test_a_table_row_of_a_component_has_its_ports(self):
        result = _elaborate2(LED + "module Top:\n    table Led (color):\n"
                             '        d1  "red"\n    isolated d1.k\n')
        self.assertTrue(result.ok, result.diagnostics.render())
        row = _by_path(result.design)["/d1"]
        self.assertEqual([p.name for p in row.ports], ["a", "k"])
        self.assertEqual(row.parameters, {"color": "red"})

    def test_a_dotted_name_is_still_an_ad_hoc_component(self):
        result = _elaborate2("module Top:\n    r = new lib.R:\n"
                             "        pin a passive\n    isolated r.a\n")
        self.assertTrue(result.ok, result.diagnostics.render())
        self.assertEqual(_by_path(result.design)["/r"].definition, "lib.R")


@unittest.skipUnless(HAVE_LARK, "lark required")
class ParameterTest(unittest.TestCase):
    SOURCE = (
        "component Res(resistance: resistance, package: string = \"0402\"):"
        "\n    pin a passive 1\n    pin b passive 2\n\n"
        "module Div(top: resistance = 10kohm, bottom: resistance = top,"
        " pkg: string = \"0603\"):\n    port p passive\n"
        "    r1 = new Res(package = pkg, resistance = top)\n"
        "    r2 = new Res(resistance = bottom)\n"
        "    p ~ r1.a ~ r2.a\n\n"
        "module Top(n: int = 2):\n    a = new Div\n"
        "    b = new Div(bottom = 4.7kohm)\n")

    def setUp(self):
        self.result = _elaborate2(self.SOURCE)
        self.assertTrue(self.result.ok, self.result.diagnostics.render())
        self.instances = _by_path(self.result.design)

    def test_the_ir_parameters_are_the_whole_environment(self):
        from rhoform.elaborate import Quantity

        ten = Quantity(Decimal("10"), "kohm")
        self.assertEqual(self.instances["/a"].parameters,
                         {"top": ten, "bottom": ten, "pkg": "0603"})
        self.assertEqual(self.instances["/a/r2"].parameters,
                         {"resistance": ten, "package": "0402"})

    def test_a_default_naming_an_earlier_parameter_follows_it(self):
        from rhoform.elaborate import Quantity

        self.assertEqual(self.instances["/b"].parameters["bottom"],
                         Quantity(Decimal("4.7"), "kohm"))
        self.assertEqual(self.instances["/b/r1"].parameters["package"],
                         "0603")

    def test_the_root_records_its_defaults(self):
        self.assertEqual(self.instances["/"].parameters, {"n": 2})

    def test_a_module_without_a_list_records_arguments_verbatim(self):
        result = _elaborate2("module Leaf:\n    port p passive\n\n"
                             "module Top(v: voltage = 5V):\n"
                             "    x = new Leaf(rail = v, note = \"x\")\n")
        self.assertTrue(result.ok, result.diagnostics.render())
        self.assertEqual(
            set(_by_path(result.design)["/x"].parameters), {"rail", "note"})

    def test_a_bare_interval_parameter_is_still_rho2016(self):
        result = _elaborate2("module Top(rail: voltage = 3V to 3.6V):\n"
                             "    port p passive\n")
        self.assertEqual(_codes(result), ["RHO2016"])


@unittest.skipUnless(HAVE_LARK, "lark required")
class ConditionalTest(unittest.TestCase):
    SOURCE = LED + """module Opt(fast: bool = false, v: voltage = 3.3V, grade: string = "a"):
    port p passive
    if fast:
        d = new Led
    else:
        d = new Led:
            dnp
    p ~ d.a
    if v >= 5000mV:
        net HIGH:
            d.k
    if grade != "a":
        isolated d.k

module Top:
    one = new Opt(fast = true, v = 5V)
    two = new Opt(grade = "b")
"""

    def test_a_spare_modules_child_still_has_its_body_checked(self):
        """Fixture is reached only through Jig, which the chosen root never
        instantiates. Fixture's own defect must still be reported: an
        attempt to skip defaults runs for modules only untaken code names
        hid exactly this, and a valid 0.1 file passed with a pinned
        mounting hole in it (AMB-144)."""
        from rhoform.elaborate import elaborate_source

        source = PRAGMA + """
module Fixture:
    h1 = new hw.Hole:
        hardware mounting_hole
        pin x passive

module Jig:
    f = new Fixture

module Board:
    port p passive
"""
        self.assertIn("RHO2013", _codes(elaborate_source(source,
                                                         root="Board")))
        self.assertIn("RHO2013", _codes(elaborate_source(source)))

    def test_each_instance_elaborates_its_own_branch(self):
        result = _elaborate2(self.SOURCE)
        self.assertTrue(result.ok, result.diagnostics.render())
        instances = _by_path(result.design)
        self.assertFalse(instances["/one/d"].dnp)
        self.assertTrue(instances["/two/d"].dnp)
        names = _by_name(result.design)
        # 5V >= 5000mV compares exact values across units.
        self.assertIn("one/HIGH", names)
        self.assertIn("N_two/d.k", names)
        self.assertNotIn("two/HIGH", names)

    def test_a_branch_not_taken_is_still_checked_for_names_and_types(self):
        result = _elaborate2("module Top(fast: bool = false):\n"
                             "    port p passive\n    if fast:\n"
                             "        x = new lib.R(v = speed)\n")
        self.assertEqual(_codes(result), ["RHO2039"])

    def test_a_branch_not_taken_is_not_elaborated(self):
        result = _elaborate2("module Top(fast: bool = false):\n"
                             "    port p passive\n    if fast:\n"
                             "        nothing.a ~ p\n")
        self.assertTrue(result.ok, result.diagnostics.render())

    def test_a_typo_in_a_branch_not_taken_still_draws_rho2002(self):
        # Merging Landing A's RHO2002 suppression: it counted every
        # unresolved `new`, but one in a branch not taken draws no RHO2005,
        # so this file failed with no diagnostic at all. Here the typo is
        # close to no candidate, so it is not why the root is ambiguous.
        source = ("module Spare:\n    port p passive\n\n"
                  "module Top(fast: bool = {}):\n"
                  "    if fast:\n        d = new Divder\n")
        result = _elaborate2(source.format("false"))
        self.assertIsNone(result.design)
        self.assertEqual(_codes(result), ["RHO2002"])
        # Taken, the typo is reported, and any reported one stands alone.
        self.assertEqual(_codes(_elaborate2(source.format("true"))),
                         ["RHO2005"])

    def test_a_typo_that_leaves_a_root_candidate_is_reported_alone(self):
        # Root candidates are a fact of the text, so the typo that makes
        # one is too: `new TvsClmap` leaves TvsClamp instantiated by
        # nothing whether or not its branch is taken, and RHO2002 would
        # send the author to the wrong line. Here the only instance that
        # takes the branch is one the ambiguous root never walks.
        tvs = ("module TvsClamp:\n    port line passive\n\n"
               "module InputStage(with_tvs: bool = false):\n"
               "    port vin passive\n    if with_tvs:\n"
               "        tvs = new TvsClmap\n        vin ~ tvs.line\n\n"
               "module Board:\n    port vin passive\n"
               "    inp = new InputStage(with_tvs = {})\n"
               "    vin ~ inp.vin\n")
        divider = ("module Divider:\n    port p passive\n\n"
                   "module Top(fast: bool = {}):\n"
                   "    if fast:\n        d = new Divder\n")
        for source, typo, meant in ((tvs, "TvsClmap", "TvsClamp"),
                                    (divider, "Divder", "Divider")):
            for taken in ("true", "false"):
                with self.subTest(typo=typo, taken=taken):
                    result = _elaborate2(source.format(taken))
                    found = _diagnostics(result)
                    self.assertEqual([d["code"] for d in found],
                                     ["RHO2005"], result.diagnostics.render())
                    self.assertEqual(found[0]["params"], {"name": typo})
                    edit = found[0]["fixits"][0]["edits"][0]
                    self.assertEqual(edit["replacement"], meant)


@unittest.skipUnless(HAVE_LARK, "lark required")
class ArrayAndLoopTest(unittest.TestCase):
    SOURCE = LED + """module Cell:
    port inp passive
    port out passive
    d = new Led
    net OUT:
        d.k
        out
    inp ~ d.a

module Top(n: int = 3):
    port gnd passive
    cells = new Cell[2]
    leds = new Led[n]
    cells[1].out ~ gnd

    for i in range(1, n):
        leds[i - 1].k ~ leds[i].a
    for i in range(n):
        net GND:
            gnd
            leds[i].a
"""

    def setUp(self):
        self.result = _elaborate2(self.SOURCE)
        self.assertTrue(self.result.ok, self.result.diagnostics.render())

    def test_members_get_indexed_paths(self):
        paths = [i.path for i in self.result.design.instances]
        for path in ("/cells[0]", "/cells[0]/d", "/cells[1]/d", "/leds[0]",
                     "/leds[2]"):
            self.assertIn(path, paths)
        self.assertNotIn("/leds[3]", paths)

    def test_labels_and_derived_names_keep_the_index(self):
        names = _by_name(self.result.design)
        self.assertIn("cells[0]/OUT", names)
        self.assertIn("N_cells[0].inp", names)

    def test_a_net_block_in_a_loop_is_one_labelled_net(self):
        gnd = _by_name(self.result.design)["GND"]
        self.assertIn(("/leds[0]", "a"), gnd.members)
        self.assertIn(("/leds[2]", "a"), gnd.members)
        self.assertIn(("/cells[1]", "out"), gnd.members)

    def test_the_ir_validates_against_the_schema(self):
        import jsonschema
        from pathlib import Path

        from rhoform.ir import emit

        schema = json.loads(
            (Path(__file__).resolve().parents[2] / "ir"
             / "netlist-ir.v1.schema.json").read_text(encoding="utf-8"))
        document = json.loads(emit(self.result.design)[0])
        jsonschema.validate(document, schema)

    def test_loop_iterations_sharing_no_endpoint_still_share_the_label(self):
        # Found by the mutation test: three iterations, each net block
        # holding one member, derived three nets all named GND.
        result = _elaborate2(LED + "module Top:\n    leds = new Led[3]\n"
                             "    for i in range(3):\n"
                             "        net GND:\n            leds[i].k\n")
        self.assertTrue(result.ok, result.diagnostics.render())
        self.assertEqual([n.name for n in result.design.nets], ["GND"])
        self.assertEqual(len(result.design.nets[0].members), 3)

    def test_array_members_share_their_declaration(self):
        instances = _by_path(self.result.design)
        self.assertEqual(instances["/leds[0]"].declaration,
                         instances["/leds[2]"].declaration)

    def test_spans_include_the_closing_bracket(self):
        # The grammar filters `[` `]` out of the tree, so a span taken from
        # tokens alone ended inside the brackets: `leds = new Led[2`.
        source = (LED + "module Top(n: int = 2):\n"
                  "    leds = new Led[n]\n    isolated leds[1].a\n")
        result = _elaborate2(source)
        self.assertTrue(result.ok, result.diagnostics.render())
        data = (P2 + source).encode()
        span = _by_path(result.design)["/leds[0]"].declaration
        self.assertEqual(data[span.byte_start:span.byte_end].decode(),
                         "leds = new Led[n]")
        source = LED + "module Top:\n    port p passive\n" \
            "    d = new Led[2]\n    d[1] ~ p\n"
        diagnostic = _diagnostics(_elaborate2(source))[0]
        self.assertEqual(diagnostic["code"], "RHO2023")
        span = diagnostic["spans"][0]
        self.assertEqual((P2 + source).encode()[
            span["byte_start"]:span["byte_end"]].decode(), "d[1]")

    def test_a_defect_in_every_iteration_is_reported_once(self):
        result = _elaborate2(LED + "module Top:\n    leds = new Led[3]\n"
                             "    for i in range(3):\n"
                             "        isolated leds[i].x\n")
        diagnostics = _diagnostics(result)
        self.assertEqual([d["code"] for d in diagnostics], ["RHO2022"])
        self.assertEqual(diagnostics[0]["params"]["instance"], "leds[i]")


@unittest.skipUnless(HAVE_LARK, "lark required")
class ReportingTest(unittest.TestCase):
    """A defect under every environment of its module: once per module.
    A defect under some environments only: once per instance, with that
    instance as the entity."""

    BANK = LED + """module Bank(n: int = 2):
    port p passive
    leds = new Led[n]
    isolated leds[2].k
    leds[0].x ~ p

module Top:
{members}
"""

    def test_value_dependent_and_independent_defects(self):
        result = _elaborate2(self.BANK.format(members=(
            "    a = new Bank(n = 3)\n    b = new Bank\n"
            "    c = new Bank")))
        found = [(d["code"], d["entity"]) for d in _diagnostics(result)]
        self.assertEqual(found, [("RHO2043", "/b"), ("RHO2043", "/c"),
                                 ("RHO2022", None)])

    def test_copies_are_ordered_by_path(self):
        # Two environments show the defect: insertion must not follow the
        # order environments were first met (the walk meets `b` first).
        source = self.BANK.replace("Bank(n: int = 2)",
                                   'Bank(n: int = 2, tag: string = "x")')
        result = _elaborate2(source.format(members=(
            '    a = new Bank\n    b = new Bank(tag = "y")\n'
            "    c = new Bank(n = 3)")))
        found = [d["entity"] for d in _diagnostics(result)
                 if d["code"] == "RHO2043"]
        self.assertEqual(found, ["/a", "/b"])

    def test_a_static_finding_names_no_entity_that_was_not_built(self):
        result = _elaborate2(
            "module Leaf(n: int = 1):\n    port p passive\n\n"
            "module Top(fast: bool = false):\n    if fast:\n"
            "        x = new Leaf(m = 2)\n")
        diagnostics = _diagnostics(result)
        self.assertEqual([d["code"] for d in diagnostics], ["RHO2036"])
        self.assertIsNone(diagnostics[0]["entity"])

    def test_one_instance_carries_the_entity(self):
        result = _elaborate2(self.BANK.format(members="    a = new Bank"))
        found = [(d["code"], d["entity"]) for d in _diagnostics(result)]
        self.assertEqual(found, [("RHO2043", None),
                                 ("RHO2022", "/a/leds[0]")])

    # Net defects (RHO2026-RHO2028) are found while flattening, once per
    # copy of the module; they follow the same rule as body findings.
    RES = "component Res:\n    pin a passive 1\n    pin b passive 2\n\n"

    def test_a_net_defect_under_every_environment_is_reported_once(self):
        cases = {
            "labels": (self.RES + """module Sensor(tie: bool = false):
    port g passive
    r1 = new Res
    net AGND(ground_domain = "agnd"):
        r1.a
    net DGND(ground_domain = "dgnd"):
        r1.a
    if tie:
        g ~ r1.b

module Top:
    a = new Sensor(tie = true)
    b = new Sensor
    c = new Sensor(tie = true)
""", [("RHO2027", None, {"labels": ["a/AGND", "a/DGND"]}),
      ("RHO2028", None, {"net": "a/AGND", "attribute": "ground_domain",
                         "first": "agnd", "second": "dgnd"})]),
            "isolated": (self.RES + """module Probe(n: int = 1):
    r1 = new Res
    isolated r1.a
    r1.a ~ r1.b

module Top:
    p1 = new Probe(n = 2)
    p2 = new Probe
""", [("RHO2026", None, {"endpoint": "r1.a", "other": "p1/r1.b"})]),
        }
        for name, (source, expected) in cases.items():
            with self.subTest(name):
                found = [(d["code"], d["entity"], d["params"])
                         for d in _diagnostics(_elaborate2(source))]
                self.assertEqual(found, expected)

    def test_a_net_defect_that_depends_on_a_parameter_is_per_instance(self):
        sensor = self.RES + """module Sensor(tie: bool = false):
    port g passive
    r1 = new Res
    net L(ground_domain = "agnd"):
        r1.a
    if tie:
        g ~ r1.a

module Top:
    a = new Sensor(tie = true)
    b = new Sensor
    c = new Sensor(tie = true)
"""
        cases = {
            "domains": (sensor + '    net GA(ground_domain = "gnd"):\n'
                        "        a.g\n"
                        '    net GB(ground_domain = "gnd"):\n'
                        "        b.g\n"
                        '    net GC(ground_domain = "gnd"):\n'
                        "        c.g\n",
                        [("RHO2028", "GA", "GA"), ("RHO2028", "GC", "GC")]),
            # Both affected copies land on one net: the per-instance
            # reports are the same diagnostic, so it is said once.
            "one net": (sensor + '    net GND(ground_domain = "gnd"):\n'
                        "        a.g\n        b.g\n        c.g\n",
                        [("RHO2028", "GND", "GND")]),
            "isolated": (self.RES + """module Probe(short: bool = false):
    r1 = new Res
    isolated r1.a
    if short:
        r1.a ~ r1.b

module Top:
    p1 = new Probe(short = true)
    p2 = new Probe
    p3 = new Probe(short = true)
""", [("RHO2026", "N_p1/r1.a", "p1/r1.b"),
      ("RHO2026", "N_p3/r1.a", "p3/r1.b")]),
            # RHO2027 names no net, so each copy carries its instance.
            "labels": (self.RES + """module Sensor(split: bool = false):
    r1 = new Res
    net AGND:
        r1.a
    if split:
        net DGND:
            r1.a

module Top:
    a = new Sensor(split = true)
    b = new Sensor
    c = new Sensor(split = true)
""", [("RHO2027", "/a", None), ("RHO2027", "/c", None)]),
        }
        for name, (source, expected) in cases.items():
            with self.subTest(name):
                found = [(d["code"], d["entity"],
                          d["params"].get("net", d["params"].get("other")))
                         for d in _diagnostics(_elaborate2(source))]
                self.assertEqual(found, expected)

    def test_each_iteration_of_a_loop_keeps_its_own_isolated_defect(self):
        # RHO2026 spells the evaluated endpoint, so two iterations are two
        # defects, not two copies of one.
        source = self.RES + """module Top:
    rs = new Res[2]
    for i in range(2):
        isolated rs[i].a
        rs[i].a ~ rs[i].b
"""
        found = [d["params"]["endpoint"]
                 for d in _diagnostics(_elaborate2(source))]
        self.assertEqual(found, ["rs[0].a", "rs[1].a"])


@unittest.skipUnless(HAVE_LARK, "lark required")
class Totality02Test(unittest.TestCase):
    """No source that parses may crash the elaborator: mutate the 0.2
    sources the suite holds, token by token, and elaborate every mutant
    that still parses."""

    MUTANTS = 600

    def seeds(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "spec" / "conformance"
        sources = []
        for folder in ("parse/accept", "elaborate/accept",
                       "elaborate/reject"):
            for path in sorted((root / folder).glob("*.rhoform")):
                text = path.read_text(encoding="utf-8")
                if "#pragma rhoform-syntax 0.2" in text:
                    sources.append(text)
        self.assertGreaterEqual(len(sources), 25)
        return sources

    @staticmethod
    def mutate(rng, source):
        import re

        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|-?[0-9]+|\s+|.", source)
        words = sorted({t for t in tokens if t[:1].isalpha() or t == "_"})
        for _ in range(rng.randint(1, 3)):
            index = rng.randrange(len(tokens))
            token = tokens[index]
            choice = rng.random()
            if token.lstrip("-").isdigit():
                tokens[index] = str(rng.choice(
                    (-1, 0, 1, 2, 3, 7, 4096, 4097, 10 ** 20)))
            elif token[:1].isalpha() and choice < 0.6:
                tokens[index] = rng.choice(words)
            elif token in ("==", "<", ">", "!", "=") and choice < 0.8:
                tokens[index] = rng.choice(("==", "<", ">=", "!="))
            elif token == "\n":
                lines = "".join(tokens).split("\n")
                at = rng.randrange(len(lines))
                if choice < 0.5:
                    del lines[at]
                else:
                    lines.insert(at, lines[rng.randrange(len(lines))])
                return "\n".join(lines)
        return "".join(tokens)

    def test_mutated_sources_never_raise(self):
        import random

        from rhoform.elaborate import elaborate
        from rhoform.ir import emit
        from rhoform.parser import parse

        rng = random.Random(20261022)
        seeds = self.seeds()
        parsed = designs = 0
        for number in range(self.MUTANTS):
            source = self.mutate(rng, rng.choice(seeds))
            result = parse(source)
            if not result.ok:
                continue
            parsed += 1
            with self.subTest(number=number, source=source):
                elaboration = elaborate([result])
                if elaboration.design is not None:
                    designs += 1
                    emit(elaboration.design)
                else:
                    self.assertTrue(elaboration.diagnostics.has_errors)
        # Not vacuous: most mutants still parse, and some still elaborate.
        self.assertGreater(parsed, self.MUTANTS // 3)
        self.assertGreater(designs, 10)


@unittest.skipUnless(HAVE_LARK, "lark required")
class Determinism02Test(unittest.TestCase):
    def test_output_does_not_depend_on_the_hash_seed(self):
        import os
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        cases = sorted((root / "spec" / "conformance" / "elaborate")
                       .glob("*/*.rhoform"))
        program = (
            "import sys, hashlib\n"
            "from rhoform.parser import parse\n"
            "from rhoform.elaborate import elaborate\n"
            "from rhoform.ir import emit\n"
            "digest = hashlib.sha256()\n"
            "for path in sys.argv[1:]:\n"
            "    text = open(path, encoding='utf-8').read()\n"
            "    result = elaborate([parse(text, file=path)])\n"
            "    digest.update(result.diagnostics.render().encode())\n"
            "    if result.design is not None:\n"
            "        digest.update(b''.join(emit(result.design)))\n"
            "print(digest.hexdigest())\n")
        outputs = set()
        for seed in ("0", "1", "4242"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            completed = subprocess.run(
                [sys.executable, "-c", program, *map(str, cases)],
                cwd=root, env=env, capture_output=True, text=True,
                check=True)
            outputs.add(completed.stdout)
        self.assertEqual(len(outputs), 1)


@unittest.skipUnless(HAVE_LARK, "lark required")
class CheckerFactsTest(unittest.TestCase):
    """The source facts the design keeps for the static stage, in memory
    only (L0): none of them reaches the IR, whose bytes stay what they
    were, which test_benchmarks.py and the conformance cases pin."""

    SOURCE = (
        "module Probe:\n"
        "    port sig passive\n"
        "    t = new lib.T:\n"
        "        pin a passive\n"
        "    net SIG(ground_domain = \"gnd\"):\n"
        "        sig\n"
        "        t.a\n"
        "\n"
        "module Top:\n"
        "    port spare passive\n"
        "    port gnd passive\n"
        "    p = new Probe\n"
        "    r = new lib.R(resistance = 1kohm):\n"
        "        pin a passive 1\n"
        "        pin b passive 2\n"
        "        part abstract:\n"
        "            resistance = 1kohm +/- 1%\n"
        "            power_rating = 100mW\n"
        "    net GND(ground_domain = \"gnd\"):\n"
        "        gnd\n"
        "        p.sig\n"
        "        r.a\n"
        "    r.b ~ p.sig\n"
        "    isolated spare\n"
        "    assert sig_ok dynamic operating_point(GND) at most 1V\n")

    def setUp(self):
        result = _elaborate(self.SOURCE)
        self.assertTrue(result.ok, result.diagnostics.render())
        self.design = result.design
        self.nets = _by_name(self.design)
        self.instances = _by_path(self.design)

    def text(self, span):
        return _text(self.SOURCE, span.as_dict())

    def test_isolated_marks_only_the_net_an_isolated_statement_made(self):
        self.assertEqual({n.name for n in self.design.nets if n.isolated},
                         {"N_.spare"})

    def test_every_site_of_an_attribute_is_kept(self):
        sites = self.nets["GND"].attribute_sites["ground_domain"]
        self.assertEqual([(value, self.text(span)) for value, span in sites],
                         [("gnd", 'ground_domain = "gnd"')] * 2)
        # Shallowest label first: Top's GND, then Probe's SIG above it.
        self.assertGreater(sites[0][1].byte_start, sites[1][1].byte_start)

    def test_every_connecting_statement_naming_a_node_is_kept(self):
        spans = self.nets["GND"].endpoint_spans
        self.assertEqual([self.text(span) for span in spans[("/p", "sig")]],
                         ["p.sig", "p.sig", "sig"])
        self.assertEqual(sorted(spans), sorted(self.nets["GND"].members))

    def test_ports_constraints_and_bounds_keep_their_spans(self):
        resistor = self.instances["/r"]
        ports = {port.name: port for port in resistor.ports}
        self.assertEqual(self.text(ports["a"].declaration),
                         "pin a passive 1")
        root = {port.name: port for port in self.instances["/"].ports}
        self.assertEqual(self.text(root["spare"].declaration),
                         "port spare passive")
        sites = resistor.part.sites
        self.assertEqual(
            {name: (site.form, site.origin, self.text(site.span))
             for name, site in sites.items()},
            {"resistance": ("toleranced", "literal", "1kohm +/- 1%"),
             "power_rating": ("exact", "literal", "100mW")})
        assertion = self.design.assertions[0]
        self.assertEqual(self.text(assertion.bound_span), "at most 1V")

    def test_the_declaration_span_does_not_make_two_pins_differ(self):
        from rhoform.elaborate import Port

        self.assertEqual(Port("a", "passive"),
                         Port("a", "passive", declaration=_span_of(1)))

    def test_the_package_layers_names_name_the_definitions(self):
        from rhoform.elaborate import elaborate
        from rhoform.parser import parse

        result = parse(PRAGMA + "\nmodule M:\n    port p passive\n",
                       file="boards/m.rhoform")
        design = elaborate([result], modules={
            "boards/m.rhoform": "acme.app.boards.m"}).design
        self.assertEqual(design.instances[0].definition,
                         "acme.app.boards.m.M")
        design = elaborate([result]).design
        self.assertEqual(design.instances[0].definition, "boards.m.M")


def _span_of(offset):
    from rhoform.diagnostics import Span

    return Span("x.rhoform", offset, offset, 1, 1, 1, 1)
