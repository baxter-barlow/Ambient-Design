"""T1 interfaces (L2a, AMB-51; spec 05/03): what elaboration makes of them.

The conformance cases pin each code's stream and each accept case's IR
byte for byte; what is pinned here is what a stream cannot show. A shape's
leaves and nested bundles, counted before they are spelled out; a bundle
port's leaves as ports of every instance; a view that adds no node; a
member-wise union that flattens to exactly the nets the same design
written leaf by leaf has; the in-memory bundle connects the ground
architecture reads; nominal typing across files; the paths the reject
cases do not take; and the acceptance's two halves about the check stage:
bundle-connected designs draw no RHO31xx, and the pin-role pass never
counts a bundle port's leaves as pins.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    import lark  # noqa: F401 - availability probe only
    HAVE_LARK = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_LARK = False

ROOT = Path(__file__).resolve().parents[2]
ACCEPT = ROOT / "spec" / "conformance" / "elaborate" / "accept"
PACKAGES = ROOT / "spec" / "conformance" / "packages" / "accept"
SKIP = "lark (pinned in toolchain/versions.yaml) is required"

P = "#pragma rhoform-syntax 0.3\n\n"
RES = "rhoform.lib.passive.Resistor"
POWER = "rhoform.lib.iface.Power"
LOGIC = "rhoform.lib.iface.Logic"


def _elaborate(source, path="t.rhoform"):
    from rhoform.elaborate import elaborate_source

    return elaborate_source(source, path)


def _codes(result):
    return [json.loads(line)["code"]
            for line in result.diagnostics.render().splitlines()]


def _nets(design):
    return {net.name: net.members for net in design.nets}


@unittest.skipUnless(HAVE_LARK, SKIP)
class ShapeTest(unittest.TestCase):
    def test_leaves_and_nested_bundles_are_member_paths(self):
        result = _elaborate(P + f"""\
interface Bus:
    port d[2]
    port en
    port rails = new {POWER}[2]

module Top:
    port bus = new Bus
""")
        self.assertEqual(result.diagnostics.render(), "")
        bundles = {b.port: b for b in result.design.bundles}
        self.assertEqual(sorted(bundles), ["bus", "bus.rails[0]",
                                           "bus.rails[1]"])
        self.assertEqual(
            [leaf for leaf, _node in bundles["bus"].members],
            ["d[0]", "d[1]", "en", "rails[0].gnd", "rails[0].hv",
             "rails[1].gnd", "rails[1].hv"])
        self.assertEqual(bundles["bus.rails[1]"].members,
                         (("gnd", ("/", "bus.rails[1].gnd")),
                          ("hv", ("/", "bus.rails[1].hv"))))
        (root,) = [i for i in result.design.instances if i.path == "/"]
        self.assertEqual([(p.name, p.role) for p in root.ports],
                         [(leaf, "passive") for leaf in (
                             "bus.d[0]", "bus.d[1]", "bus.en",
                             "bus.rails[0].gnd", "bus.rails[0].hv",
                             "bus.rails[1].gnd", "bus.rails[1].hv")])

    def test_a_shape_is_counted_before_it_is_spelled_out(self):
        # 65 * 64 * 64 leaves would take a long time to list; the count
        # alone refuses it, as soon as a bundle port is typed by it, and an
        # interface no port uses costs nothing. B's 4160 already pass the
        # budget, so only A is spelled out.
        from rhoform import elaborate as E

        nested = P + """\
interface A:
    port d[65]

interface B:
    port a = new A[64]

interface C:
    port b = new B[64]

module Top:
"""
        enumerated = []
        shape = E._Elaborator.shape

        def spy(defn):
            shape(defn)
            enumerated.append((defn.name, defn.leaves is not None))

        E._Elaborator.shape = staticmethod(spy)
        self.addCleanup(setattr, E._Elaborator, "shape",
                        staticmethod(shape))
        result = _elaborate(nested + "    port c = new C\n")
        self.assertEqual(_codes(result), ["RHO2046"])
        self.assertEqual(dict(enumerated),
                         {"A": True, "B": False, "C": False})
        enumerated.clear()
        result = _elaborate(nested + "    port p passive\n")
        self.assertEqual(result.diagnostics.render(), "")

    def test_a_bundle_ports_leaves_count_against_the_budget(self):
        # 1000 leaves per instance, five instances: past 4096 together,
        # though each bundle port alone is within it.
        result = _elaborate(P + """\
interface Wide:
    port d[1000]

module Cell:
    port bus = new Wide

module Top:
    cells = new Cell[5]
""")
        self.assertEqual(_codes(result), ["RHO2046"])
        within = _elaborate(P + """\
interface Wide:
    port d[1000]

module Cell:
    port bus = new Wide

module Top:
    cells = new Cell[4]
""")
        self.assertEqual(within.diagnostics.render(), "")

    def test_a_cyclic_interface_is_reported_once_and_quiets_its_users(self):
        result = _elaborate(P + """\
interface A:
    port b = new B

interface B:
    port a = new A

module Top:
    port x = new A
    r = new rhoform.lib.passive.Resistor
    x.b.a ~ r.a
    x ~ r.b
""")
        self.assertEqual(_codes(result), ["RHO3002"])


@unittest.skipUnless(HAVE_LARK, SKIP)
class BundlePortTest(unittest.TestCase):
    def test_parameters_are_evaluated_per_instance_and_unset_is_absent(self):
        result = _elaborate(P + f"""\
module Rail(v: voltage):
    port out = new {POWER}(v = v)
    port spare = new {POWER}

module Top:
    a = new Rail(v = 3.3V)
    b = new Rail(v = 5V)
""")
        self.assertEqual(result.diagnostics.render(), "")
        bundles = {(b.instance, b.port): b.parameters
                   for b in result.design.bundles}
        self.assertEqual(str(bundles[("/a", "out")]["v"].value), "3.3")
        self.assertEqual(str(bundles[("/b", "out")]["v"].value), "5")
        self.assertEqual(bundles[("/a", "spare")], {})

    def test_an_argument_is_checked_against_the_interface(self):
        result = _elaborate(P + f"""\
module Top:
    port a = new {POWER}(volts = 3V)
    port b = new {POWER}(v = 1kohm)
    port c = new {LOGIC}(v = 3V)
""")
        self.assertEqual(sorted(_codes(result)),
                         ["RHO2036", "RHO2036", "RHO2038"])

    def test_the_parent_and_the_module_name_one_node(self):
        # `ind.power.hv` in the parent is the node `power.hv` of the
        # module: one net, as any module port's two names are.
        result = _elaborate(P + f"""\
module Indicator:
    port power = new {POWER}
    r = new {RES}
    power.gnd ~ r.b
    power.hv ~ r.a

module Top:
    port vin passive
    ind = new Indicator
    ind.power.hv ~ vin
""")
        self.assertEqual(result.diagnostics.render(), "")
        self.assertIn((("/", "vin"), ("/ind", "power.hv"), ("/ind/r", "a")),
                      _nets(result.design).values())


@unittest.skipUnless(HAVE_LARK, SKIP)
class ViewTest(unittest.TestCase):
    COMPONENT = f"""\
component Ldo(vout: voltage):
    pin gnd passive 1
    pin vin power_in 2
    pin vout power_out 3
    port input = new {POWER}:
        gnd = gnd
        hv = vin
    port output = new {POWER}(v = vout):
        gnd = gnd
        hv = vout

"""

    def test_a_view_adds_no_port_and_its_leaves_are_its_pins(self):
        result = _elaborate(P + self.COMPONENT + """\
module Top:
    port a passive
    port b passive
    reg = new Ldo(vout = 1.8V)
    reg.output.hv ~ a
    reg.input.gnd ~ b
""")
        self.assertEqual(result.diagnostics.render(), "")
        design = result.design
        (reg,) = [i for i in design.instances if i.path == "/reg"]
        self.assertEqual([p.name for p in reg.ports], ["gnd", "vin", "vout"])
        self.assertEqual(sorted(_nets(design).values()),
                         [(("/", "a"), ("/reg", "vout")),
                          (("/", "b"), ("/reg", "gnd"))])
        output = next(b for b in design.bundles if b.port == "output")
        self.assertEqual(output.members, (("gnd", ("/reg", "gnd")),
                                          ("hv", ("/reg", "vout"))))
        self.assertEqual(str(output.parameters["v"].value), "1.8")

    def test_two_views_may_share_a_pin(self):
        result = _elaborate(P + self.COMPONENT + "module Top:\n"
                            "    reg = new Ldo(vout = 1.8V)\n")
        self.assertEqual(result.diagnostics.render(), "")
        shared = {b.port: dict(b.members)["gnd"]
                  for b in result.design.bundles}
        self.assertEqual(shared, {"input": ("/reg", "gnd"),
                                  "output": ("/reg", "gnd")})

    def test_a_binding_path_ends_at_a_leaf(self):
        for binding, code in (("bus = sck", "RHO3006"),
                              ("bus.sck[0] = sck", "RHO3013"),
                              ("bus.clk = sck", "RHO3003")):
            with self.subTest(binding=binding):
                result = _elaborate(P + f"""\
component Flash:
    pin cs input 1
    pin sck input 2
    port spi = new rhoform.lib.iface.Spi:
        {binding}
        cs = cs

module Top:
    f = new Flash
""")
                self.assertEqual(_codes(result), [code])

    def test_a_view_over_a_leaf_array_takes_literal_indexes(self):
        result = _elaborate(P + """\
interface Bus:
    port d[2]

component Latch:
    pin d0 input 1
    pin d1 input 2
    port bus = new Bus:
        d[0] = d0
        d[1] = d1

module Top:
    port a passive
    x = new Latch
    x.bus.d[1] ~ a
""")
        self.assertEqual(result.diagnostics.render(), "")
        self.assertIn((("/", "a"), ("/x", "d1")),
                      _nets(result.design).values())
        for index, code in (("2", "RHO3014"), ("-1", "RHO3014")):
            with self.subTest(index=index):
                broken = _elaborate(P + f"""\
interface Bus:
    port d[2]

component Latch:
    pin d0 input 1
    pin d1 input 2
    port bus = new Bus:
        d[0] = d0
        d[{index}] = d1

module Top:
    x = new Latch
""")
                # The leaf it meant is not then also unbound: one defect.
                self.assertEqual(_codes(broken), [code])


@unittest.skipUnless(HAVE_LARK, SKIP)
class ConnectTest(unittest.TestCase):
    def test_a_bundle_connect_is_the_same_nets_as_its_leaves(self):
        # Sugar, proven: the chain of whole bundles flattens to exactly the
        # nets the leaf-by-leaf chains make, member for member.
        body = P + f"""\
module Load:
    port power = new {POWER}
    r = new {RES}
    power.gnd ~ r.b
    power.hv ~ r.a

module Top:
    port power = new {POWER}
    a = new Load
    b = new Load
"""
        whole = _elaborate(body + "    power ~ a.power ~ b.power\n")
        leaves = _elaborate(
            body + "    power.gnd ~ a.power.gnd ~ b.power.gnd\n"
            "    power.hv ~ a.power.hv ~ b.power.hv\n")
        self.assertEqual(whole.diagnostics.render(), "")
        self.assertEqual(leaves.diagnostics.render(), "")
        self.assertEqual(_nets(whole.design), _nets(leaves.design))
        self.assertEqual(whole.design.connections(),
                         leaves.design.connections())
        # The provenance is what tells them apart, and only in memory.
        (connect,) = whole.design.bundle_connects
        self.assertEqual(connect.definition, POWER)
        self.assertEqual(connect.endpoints,
                         (("/", "power"), ("/a", "power"), ("/b", "power")))
        self.assertEqual(connect.scope, "/")
        self.assertEqual(connect.leaf_unions, (
            ("gnd", (("/", "power.gnd"), ("/a", "power.gnd"),
                     ("/b", "power.gnd"))),
            ("hv", (("/", "power.hv"), ("/a", "power.hv"),
                    ("/b", "power.hv")))))
        self.assertEqual(leaves.design.bundle_connects, [])

    def test_an_array_connect_is_one_record_per_element(self):
        result = _elaborate(P + f"""\
module Top:
    port a = new {LOGIC}[2]
    port b = new {LOGIC}[2]
    a ~ b
""")
        self.assertEqual(result.diagnostics.render(), "")
        self.assertEqual([c.endpoints for c in result.design.bundle_connects],
                         [(("/", "a[0]"), ("/", "b[0]")),
                          (("/", "a[1]"), ("/", "b[1]"))])
        self.assertEqual(
            sorted(_nets(result.design).values()),
            [(("/", "a[0].line"), ("/", "b[0].line")),
             (("/", "a[0].ref"), ("/", "b[0].ref")),
             (("/", "a[1].line"), ("/", "b[1].line")),
             (("/", "a[1].ref"), ("/", "b[1].ref"))])

    def test_a_leaf_array_connects_element_by_element_with_no_record(self):
        result = _elaborate(P + """\
interface Bus:
    port d[2]

module Top:
    port a = new Bus
    port b = new Bus
    a.d ~ b.d
""")
        self.assertEqual(result.diagnostics.render(), "")
        self.assertEqual(result.design.bundle_connects, [])
        self.assertEqual(sorted(_nets(result.design).values()),
                         [(("/", "a.d[0]"), ("/", "b.d[0]")),
                          (("/", "a.d[1]"), ("/", "b.d[1]"))])

    def test_a_module_used_twice_records_each_instances_connect(self):
        result = _elaborate(P + f"""\
module Pair:
    port x = new {POWER}
    port y = new {POWER}
    x ~ y

module Top:
    p = new Pair
    q = new Pair
""")
        self.assertEqual(result.diagnostics.render(), "")
        self.assertEqual([(c.scope, c.endpoints)
                          for c in result.design.bundle_connects],
                         [("/p", (("/p", "x"), ("/p", "y"))),
                          ("/q", (("/q", "x"), ("/q", "y")))])

    def test_a_whole_bundle_is_refused_where_single_nodes_are_joined(self):
        for statement in ("isolated power", "power ~ r.a",
                          "net N:\n        power\n        r.a"):
            with self.subTest(statement=statement):
                result = _elaborate(P + f"""\
module Top:
    port power = new {POWER}
    r = new {RES}
    {statement}
""")
                self.assertIn("RHO3006", _codes(result))

    def test_a_0_2_file_may_name_a_whole_bundle_another_file_declares(self):
        # 0.1-shaped syntax, 0.3 meaning: the departure spec 04 records.
        tmp = Path(tempfile.mkdtemp(prefix="rhoform-iface-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "parts.rhoform").write_text(P + f"""\
module Load:
    port power = new {POWER}
    r = new {RES}
    power.gnd ~ r.b
    power.hv ~ r.a
""", encoding="utf-8")
        (tmp / "main.rhoform").write_text(
            "#pragma rhoform-syntax 0.2\n\nimport Load from \"./parts\"\n\n"
            "module Top:\n    a = new Load\n    b = new Load\n"
            "    a.power ~ b.power\n", encoding="utf-8")
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics

        sink = Diagnostics()
        compiled = pipeline.compile("main.rhoform", tmp, sink=sink,
                                    stage="elaborate")
        self.assertEqual(sink.render(), "")
        self.assertEqual(len(compiled.design.bundle_connects), 1)
        self.assertEqual(compiled.design.language_version, "0.3.0")


@unittest.skipUnless(HAVE_LARK, SKIP)
class NominalTest(unittest.TestCase):
    def test_the_same_members_are_not_the_same_interface(self):
        result = _elaborate(P + f"""\
interface Rail:
    port gnd
    port hv

module Top:
    port a = new Rail
    port b = new {POWER}
    a ~ b
""")
        self.assertEqual(_codes(result), ["RHO3004"])
        (diagnostic,) = [json.loads(line) for line
                         in result.diagnostics.render().splitlines()]
        self.assertEqual(diagnostic["params"]["interface_a"], "t.Rail")
        self.assertEqual(diagnostic["params"]["interface_b"], POWER)

    def test_parameters_take_no_part(self):
        result = _elaborate(P + f"""\
module Top:
    port a = new {POWER}(v = 3.3V)
    port b = new {POWER}(v = 5V)
    a ~ b
""")
        self.assertEqual(result.diagnostics.render(), "")

    def test_an_imported_interface_is_its_files_definition(self):
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics

        root = PACKAGES / "a06_interface_import"
        sink = Diagnostics()
        compiled = pipeline.compile("main.rhoform", root, sink=sink,
                                    stage="elaborate")
        self.assertEqual(sink.render(), "")
        self.assertEqual({b.definition for b in compiled.design.bundles},
                         {"probes.Probe"})


@unittest.skipUnless(HAVE_LARK, SKIP)
class QuietTest(unittest.TestCase):
    """One defect, one diagnostic: what names a refused bundle port, view
    or interface draws nothing more."""

    def test_users_of_a_refused_bundle_port_stay_quiet(self):
        for port in (f"port p = new {RES}", "port p = new Nope",
                     f"port p = new {LOGIC}[n]"):
            with self.subTest(port=port):
                result = _elaborate(P + f"""\
module Top(n: int = 2):
    {port}
    r = new {RES}
    p.hv ~ r.a
    p ~ r.b
""")
                self.assertEqual(len(_codes(result)), 1, _codes(result))

    def test_a_pin_or_a_port_takes_no_member_and_no_index(self):
        result = _elaborate(P + f"""\
module Top:
    port vin passive
    r = new {RES}
    s = new {RES}
    r.a.b ~ vin
    s.a[0] ~ vin
    vin.x ~ s.b
""")
        self.assertEqual(sorted(_codes(result)),
                         ["RHO2021", "RHO3003", "RHO3013"])


@unittest.skipUnless(HAVE_LARK, SKIP)
class CheckStageTest(unittest.TestCase):
    """The acceptance's check-stage half (design record Part A): bundle
    connected Power, SPI and I2C designs draw no RHO31xx, and the erc
    pass never counts a bundle port's leaves as pins."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rhoform-iface-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def check(self, root, entry):
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics

        sink = Diagnostics()
        compiled = pipeline.compile(entry, root, sink=sink, through="erc")
        self.assertIsNotNone(compiled.report, sink.render())
        return [json.loads(line) for line in sink.render().splitlines()]

    def test_the_bundle_accept_cases_draw_no_pin_role_finding(self):
        cases = [(ACCEPT, f"{name}.rhoform") for name in (
            "a18_power_bundle_chain", "a19_component_view",
            "a20_nested_and_array_bundles", "a21_unset_parameters")]
        cases.append((PACKAGES / "a06_interface_import", "main.rhoform"))
        for root, entry in cases:
            with self.subTest(case=entry):
                # Each case alone in a compile root, as the suite runs it.
                copy = self.tmp / entry.split(".")[0]
                if entry == "main.rhoform":
                    shutil.copytree(root, copy)
                else:
                    copy.mkdir()
                    shutil.copy(root / entry, copy / entry)
                found = self.check(copy, entry)
                self.assertEqual([d["code"] for d in found
                                  if d["code"].startswith("RHO31")], [])

    def test_a_bundle_ports_leaves_are_never_counted_as_pins(self):
        # One resistor pin and two modules' bundle leaves: one pin, which
        # the single-pin rule reports. Were the leaves counted, the net
        # would have three.
        (self.tmp / "t.rhoform").write_text(P + f"""\
module Stub:
    port power = new {POWER}

module Top:
    a = new Stub
    b = new Stub
    r = new {RES}
    a.power.hv ~ b.power.hv ~ r.a
    a.power.gnd ~ b.power.gnd ~ r.b
""", encoding="utf-8")
        found = self.check(self.tmp, "t.rhoform")
        self.assertEqual(sorted((d["code"], d["entity"]) for d in found
                                if d["code"].startswith("RHO31")),
                         [("RHO3106", "N_a.power.gnd"),
                          ("RHO3106", "N_a.power.hv")])


@unittest.skipUnless(HAVE_LARK, SKIP)
class PreservationTest(unittest.TestCase):
    def test_a_design_without_interfaces_is_untouched_by_them(self):
        # The benchmarks name no interface: their IR is byte for byte what
        # a library without the interfaces' module gives, which is the IR
        # of the landing before interfaces, and holds no bundle.
        from rhoform import ir
        from rhoform.elaborate import Library, elaborate
        from rhoform.parser import parse

        tmp = Path(tempfile.mkdtemp(prefix="rhoform-iface-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        shutil.copytree(ROOT / "rhoform" / "lib", tmp / "lib")
        (tmp / "lib" / "iface.rhoform").unlink()
        without = Library(tmp / "lib")
        for source in sorted((ROOT / "benchmarks").glob("*/*.rhoform")):
            if source.name != source.parent.name + ".rhoform":
                continue
            with self.subTest(benchmark=source.parent.name):
                result = parse(source.read_text(encoding="utf-8"),
                               file=source.name)
                design = elaborate([result]).design
                self.assertEqual(design.bundles, [])
                self.assertEqual(ir.emit(design),
                                 ir.emit(elaborate([result],
                                                   library=without).design))
                golden = source.with_name(source.name[:-len(".rhoform")]
                                          + ".ir.json")
                self.assertEqual(ir.emit(design)[0], golden.read_bytes())


if __name__ == "__main__":
    unittest.main()
