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


def _elaborate(body, path="design.rhoform", root=None):
    from rhoform.elaborate import elaborate_source

    return elaborate_source(PRAGMA + "\n" + body, path, root=root)


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
        source = ("module Leaf:\n    port p passive\n"
                  "module Top:\n    m = new Leaf\n"
                  "    c = new rhoform.lib.passive.Resistor:\n"
                  "        pin a passive 1\n        pin b passive 2\n")
        design = _elaborate(source).design
        instances = _by_path(design)
        self.assertEqual(instances["/m"].kind, "module")
        self.assertEqual(instances["/c"].kind, "component")
        self.assertEqual(instances["/c"].definition,
                         "rhoform.lib.passive.Resistor")
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
class CodeTest(unittest.TestCase):
    """One planted defect per code: the code, its params, its span."""

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

    def test_every_block_two_code_has_a_test_here(self):
        from rhoform import codes

        block = {c.code for c in codes.REGISTRY if c.code.startswith("RHO2")}
        tested = {name.split("_")[1].upper() for name in dir(self)
                  if name.startswith("test_rho2")}
        self.assertEqual(block, tested)

    def test_a_defect_in_a_reused_module_is_reported_once(self):
        source = ("module Inner:\n    x = new lib.H:\n"
                  "        hardware fiducial\n        pin p passive\n"
                  "module Top:\n    a = new Inner\n    b = new Inner\n")
        result = _elaborate(source)
        diagnostics = _diagnostics(result)
        self.assertEqual([d["code"] for d in diagnostics], ["RHO2013"])
        # Two instances share the definition: no single entity exists.
        self.assertIsNone(diagnostics[0]["entity"])
