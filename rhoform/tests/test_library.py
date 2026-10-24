"""The bundled standard library (rhoform/lib/) and E-5 name resolution.

Two halves. The library's own files: each module is a canonical syntax 0.2
file of `component` definitions only, but for `iface`, a syntax 0.3 file of
the standard interfaces only (spec 05/03), and every definition can be
instantiated, every interface given a bundle port. And what elaboration
does with them: a name under the reserved prefix `rhoform.lib.` resolves to
a definition or is RHO2067, only the modules a compilation names are read
and listed (E-8), and a module the toolchain ships broken is reported rather
than raised.
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
LIBRARY = ROOT / "rhoform" / "lib"
P = "#pragma rhoform-syntax 0.1\n\n"
P_0_3 = "#pragma rhoform-syntax 0.3\n\n"

# The one library module of interfaces, and what spec 05/03's table says
# each standard interface is: (parameters, members) as written there.
INTERFACES = "iface"
STANDARD = {
    "Power": ((("v", "voltage"),), ("gnd", "hv")),
    "Logic": ((), ("line", "ref")),
    "DiffPair": ((("impedance", "resistance"),), ("n", "p")),
    "I2C": ((("addr", "int"), ("freq", "frequency")),
            ("ref", "scl", "sda")),
    "SpiBus": ((), ("miso", "mosi", "ref", "sck")),
    "Spi": ((), ("bus", "cs")),
}

# One value per param_type, to instantiate a definition with a list.
SAMPLE = {"string": '"x"', "int": "1", "bool": "true",
          "capacitance": "1nF", "current": "1A", "frequency": "1kHz",
          "inductance": "1uH", "length": "1mm", "power": "1W",
          "resistance": "1ohm", "temperature": "25degC", "time": "1s",
          "voltage": "1V"}


def _diagnostics(result):
    return [json.loads(line)
            for line in result.diagnostics.render().splitlines()]


def _definitions(module):
    """(name, [(pin, role, designators)], [(param, type)] or None) for each
    component of one bundled module, read from its tree."""
    from rhoform import elaborate as E

    result = E.BUNDLED.load(module)
    found = []
    for node in result.tree.children:
        if not (E._is_tree(node) and node.data == "component_def"):
            continue
        pins = [(str(E._tokens(pin, "NAME")[0]), str(E._tokens(pin, "NAME")[1]),
                 tuple(sorted(str(d.children[0])
                              for d in E._trees(pin, "designator"))))
                for pin in E._trees(node, "pin_decl")]
        params = E._tree(node, "params")
        declared = None if params is None else [
            (str(E._tokens(p, "FREE_NAME")[0]), str(E._tokens(p, "NAME")[0]))
            for p in E._trees(params, "param")]
        found.append((str(node.children[1]), pins, declared))
    return found


@unittest.skipUnless(HAVE_LARK, "lark required")
class LibraryFilesTest(unittest.TestCase):
    def test_the_modules_are_the_files_on_disk(self):
        from rhoform.elaborate import BUNDLED

        self.assertEqual(
            list(BUNDLED.modules()),
            sorted(p.name[:-len(".rhoform")]
                   for p in LIBRARY.glob("*.rhoform")))
        self.assertIn("passive", BUNDLED.modules())

    def test_each_module_is_canonical_0_2_component_definitions(self):
        # Or, for the interfaces' module alone, canonical 0.3 interface
        # definitions: what a module holds is one kind of definition.
        from rhoform import elaborate as E
        from rhoform.fmt import format_source

        for module in E.BUNDLED.modules():
            with self.subTest(module=module):
                result = E.BUNDLED.load(module)
                self.assertTrue(result.ok, result.diagnostics.render())
                self.assertEqual(result.file, f"rhoform/lib/{module}.rhoform")
                pragma = next(c for c in result.tree.children
                              if not E._is_tree(c) and c.type == "PRAGMA")
                interfaces = module == INTERFACES
                self.assertEqual(str(pragma).split()[-1],
                                 "0.3" if interfaces else "0.2")
                self.assertEqual(
                    {c.data for c in result.tree.children if E._is_tree(c)},
                    {"interface_def" if interfaces else "component_def"})
                text = result.data.decode("utf-8")
                self.assertEqual(format_source(text, file=result.file).text,
                                 text)

    def test_every_definition_instantiates_to_its_pins(self):
        # One instance of every library component, with a sample argument
        # of the declared type for each parameter: the whole library
        # elaborates clean, and each instance's ports are its definition's
        # pins, in the definition's order.
        from rhoform.elaborate import BUNDLED, elaborate_source

        lines, expected = ["module Probe:"], {}
        for module in BUNDLED.modules():
            for name, pins, params in _definitions(module):
                member = f"{module}_{name.lower()}"
                arguments = ", ".join(f"{p} = {SAMPLE[t]}"
                                      for p, t in params or ())
                lines.append(f"    {member} = new rhoform.lib.{module}.{name}"
                             + (f"({arguments})" if arguments else ""))
                expected[f"/{member}"] = (f"rhoform.lib.{module}.{name}",
                                          pins)
        result = elaborate_source(P + "\n".join(lines) + "\n", "probe.rhoform")
        self.assertEqual(result.diagnostics.render(), "")
        instances = {i.path: i for i in result.design.instances}
        for path, (definition, pins) in expected.items():
            with self.subTest(instance=path):
                self.assertEqual(instances[path].definition, definition)
                self.assertEqual(
                    [(p.name, p.role, p.pin_numbers)
                     for p in instances[path].ports], pins)
        self.assertEqual(
            [f.path for f in result.design.files],
            ["probe.rhoform"] + [f"rhoform/lib/{m}.rhoform"
                                 for m in BUNDLED.modules()
                                 if m != INTERFACES])

    def test_every_interface_types_a_bundle_port(self):
        # iface.rhoform elaborates under its own pragma, 0.3: a bundle port
        # of each standard interface, a sample argument for each of its
        # parameters, and the bundles in the IR are the interfaces spec
        # 05/03 tabulates, member for member.
        from rhoform.elaborate import elaborate_source

        lines = ["module Probe:"]
        for name, (params, _members) in sorted(STANDARD.items()):
            arguments = ", ".join(f"{p} = {SAMPLE[t]}" for p, t in params)
            lines.append(f"    port {name.lower()} = new "
                         f"rhoform.lib.iface.{name}"
                         + (f"({arguments})" if arguments else ""))
        result = elaborate_source(P_0_3 + "\n".join(lines) + "\n",
                                  "probe.rhoform")
        self.assertEqual(result.diagnostics.render(), "")
        bundles = {b.port: b for b in result.design.bundles}
        for name, (params, members) in STANDARD.items():
            with self.subTest(interface=name):
                bundle = bundles[name.lower()]
                self.assertEqual(bundle.definition,
                                 f"rhoform.lib.iface.{name}")
                self.assertEqual(sorted(bundle.parameters),
                                 sorted(p for p, _t in params))
                self.assertEqual(
                    sorted({leaf.split(".")[0]
                            for leaf, _node in bundle.members}),
                    sorted(members))
        # Spi nests SpiBus: its `bus` is a bundle of its own.
        self.assertEqual(bundles["spi.bus"].definition,
                         "rhoform.lib.iface.SpiBus")
        self.assertEqual([f.path for f in result.design.files],
                         ["probe.rhoform", "rhoform/lib/iface.rhoform"])

    def test_the_standard_interfaces_are_spec_05_03s(self):
        # The library's definitions, read from its tree: exactly the six,
        # with the parameters and members the spec states, and `ref` a
        # leaf wherever it is a member (GA-1).
        from rhoform import elaborate as E

        result = E.BUNDLED.load(INTERFACES)
        found = {}
        for node in result.tree.children:
            if not (E._is_tree(node) and node.data == "interface_def"):
                continue
            params = E._tree(node, "params")
            declared = () if params is None else tuple(
                (str(E._tokens(p, "FREE_NAME")[0]),
                 str(E._tokens(p, "NAME")[0]))
                for p in E._trees(params, "param"))
            members = tuple(str(E._tokens(m, "FREE_NAME")[0])
                            for m in E._trees(node, "member_decl"))
            found[str(node.children[1])] = (declared, members)
            for member in E._trees(node, "member_decl"):
                if str(E._tokens(member, "FREE_NAME")[0]) == "ref":
                    self.assertIsNone(E._tree(member, "qualified_name"))
        self.assertEqual(found, STANDARD)
        # No library component has a view in M2 (decision D15).
        for module in E.BUNDLED.modules():
            tree = E.BUNDLED.load(module).tree
            self.assertEqual(list(tree.find_data("view_decl")), [], module)

    def test_the_hardware_kinds_have_the_arity_spec_04_requires(self):
        # E-11 against the library itself: the pinless kinds' definitions
        # have no pins, the single-pin kinds' exactly one passive pin.
        definitions = {name: pins for name, pins, _ in _definitions("mech")}
        for name in ("Fiducial", "Logo", "MountingHole"):
            self.assertEqual(definitions[name], [], name)
        for name in ("GroundedMountingHole", "TestPoint"):
            self.assertEqual(definitions[name], [("p", "passive", ())], name)


@unittest.skipUnless(HAVE_LARK, "lark required")
class ResolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def elaborate(self, body, library=None):
        from rhoform.elaborate import elaborate_source

        return elaborate_source(P + body, "top.rhoform", library=library)

    def copy_library(self):
        from rhoform.elaborate import Library

        directory = self.tmp / "lib"
        shutil.copytree(LIBRARY, directory)
        return directory, Library(directory)

    def test_a_library_instance_gets_its_definitions_ports(self):
        result = self.elaborate("module Top:\n    port vcc power_in\n"
                                "    u1 = new rhoform.lib.timer.Ne555\n"
                                "    vcc ~ u1.vcc\n")
        self.assertEqual(result.diagnostics.render(), "")
        timer = next(i for i in result.design.instances if i.path == "/u1")
        self.assertEqual(timer.definition, "rhoform.lib.timer.Ne555")
        self.assertEqual(
            [(p.name, p.pin_numbers) for p in timer.ports][:2],
            [("ctl", ("5",)), ("dis", ("7",))])

    def test_a_name_under_the_reserved_prefix_must_be_in_the_library(self):
        for name in ("rhoform.lib.passive.Nope", "rhoform.lib.nope.Resistor",
                     "rhoform.lib.passive", "rhoform.lib",
                     "rhoform.lib.passive.Resistor.a"):
            with self.subTest(name=name):
                result = self.elaborate(f"module Top:\n    r = new {name}\n")
                self.assertEqual([d["code"] for d in _diagnostics(result)],
                                 ["RHO2067"])
                self.assertIsNone(result.design)

    def test_other_dotted_names_stay_ad_hoc(self):
        # Only `rhoform.lib.` is reserved: `rhoform.library.X`, `lib.X` and
        # a vendor prefix keep v0.1's meaning, their ports their pins.
        for name in ("rhoform.library.passive.Resistor", "lib.R", "acme.R"):
            with self.subTest(name=name):
                result = self.elaborate(
                    f"module Top:\n    r = new {name}:\n"
                    "        pin x passive 7\n    isolated r.x\n")
                self.assertEqual(result.diagnostics.render(), "")
                r = next(i for i in result.design.instances
                         if i.path == "/r")
                self.assertEqual((r.definition, r.ports[0].pin_numbers),
                                 (name, ("7",)))

    def test_a_close_misspelling_gets_one_fix_it(self):
        cases = {
            "rhoform.lib.passive.Resistr": "rhoform.lib.passive.Resistor",
            "rhoform.lib.pasive.Resistor": "rhoform.lib.passive.Resistor",
            "rhoform.lib.timr.Ne555": "rhoform.lib.timer.Ne555",
            # both words wrong, or no close module: no guess
            "rhoform.lib.pasive.Resistr": None,
            "rhoform.lib.ic.Mcu": None,
        }
        for written, meant in cases.items():
            with self.subTest(name=written):
                result = self.elaborate(f"module Top:\n    r = new {written}\n")
                (diagnostic,) = _diagnostics(result)
                fixes = [e["replacement"] for f in diagnostic["fixits"]
                         for e in f["edits"]]
                self.assertEqual(fixes, [meant] if meant else [])

    def test_module_names_match_exactly_as_spelled_on_disk(self):
        # A case-insensitive filesystem would open Passive.rhoform for
        # passive.rhoform; the library refuses it everywhere alike.
        result = self.elaborate(
            "module Top:\n    r = new rhoform.lib.Passive.Resistor\n")
        self.assertEqual([d["code"] for d in _diagnostics(result)],
                         ["RHO2067"])

    def test_inline_pins_must_restate_the_definition(self):
        result = self.elaborate(
            "module Top:\n    r = new rhoform.lib.passive.Resistor:\n"
            "        pin a passive 1\n        pin b passive\n"
            "    isolated r.a\n")
        (diagnostic,) = _diagnostics(result)
        self.assertEqual(diagnostic["code"], "RHO2035")
        self.assertEqual(diagnostic["params"]["component"],
                         "rhoform.lib.passive.Resistor")
        self.assertEqual(diagnostic["spans"][1]["file"],
                         "rhoform/lib/passive.rhoform")

    def test_a_typed_definition_checks_its_arguments(self):
        result = self.elaborate(
            "module Top:\n    l = new rhoform.lib.passive.Inductor\n")
        (diagnostic,) = _diagnostics(result)
        self.assertEqual((diagnostic["code"], diagnostic["params"]),
                         ("RHO2037", {"definition":
                                      "rhoform.lib.passive.Inductor",
                                      "instance": "l",
                                      "parameter": "inductance"}))

    def test_a_table_row_of_a_library_component_has_its_ports(self):
        result = self.elaborate(
            "module Top:\n    port p passive\n"
            "    table rhoform.lib.passive.Resistor (resistance):\n"
            "        r1  1kohm\n    p ~ r1.a\n")
        self.assertEqual(result.diagnostics.render(), "")
        (net,) = result.design.nets
        self.assertEqual(net.members, (("/", "p"), ("/r1", "a")))

    def test_only_the_modules_named_are_read_and_listed(self):
        _directory, library = self.copy_library()
        loaded = []
        load = library.load
        library.load = lambda module: loaded.append(module) or load(module)
        result = self.elaborate(
            "module Top:\n    r = new rhoform.lib.passive.Resistor\n"
            "    t = new rhoform.lib.timer.Ne555\n", library=library)
        self.assertEqual(loaded, ["passive", "timer"])
        self.assertEqual([f.path for f in result.design.files],
                         ["rhoform/lib/passive.rhoform",
                          "rhoform/lib/timer.rhoform", "top.rhoform"])

    def test_an_unrelated_library_module_changes_no_hash(self):
        from rhoform import ir
        from rhoform.elaborate import elaborate
        from rhoform.parser import parse

        source = ROOT / "benchmarks" / "blinker-555" / "blinker-555.rhoform"
        result = parse(source.read_text(encoding="utf-8"), file=source.name)
        before = ir.emit(elaborate([result]).design)
        directory, library = self.copy_library()
        (directory / "zzz.rhoform").write_text(
            "#pragma rhoform-syntax 0.2\n\ncomponent Extra:\n"
            "    pin a passive\n", encoding="utf-8")
        (directory / "README.txt").write_text("not a module\n")
        self.assertIn("zzz", library.modules())
        after = ir.emit(elaborate([result], library=library).design)
        self.assertEqual(before, after)

    def test_a_broken_library_module_is_reported_not_raised(self):
        directory, library = self.copy_library()
        (directory / "passive.rhoform").write_text(
            "#pragma rhoform-syntax 0.2\n\ncomponent Resistor:\n"
            "    pin a passiv\n", encoding="utf-8")
        result = self.elaborate(
            "module Top:\n    r = new rhoform.lib.passive.Resistor\n",
            library=library)
        codes = [d["code"] for d in _diagnostics(result)]
        self.assertIn("RHO2067", codes)
        self.assertTrue(any(d["spans"][0]["file"]
                            == "rhoform/lib/passive.rhoform"
                            for d in _diagnostics(result)))
        self.assertIsNone(result.design)

    def test_an_authors_file_at_a_library_path_is_refused(self):
        # Its definitions would be named under the reserved prefix, and
        # one path cannot name two files: the file is refused, so the
        # library path always means the bundled module.
        from rhoform.elaborate import elaborate_source

        for path in ("rhoform/lib/passive.rhoform", "rhoform/lib.rhoform",
                     "rhoform/lib/sub/x.rhoform"):
            with self.subTest(path=path):
                result = elaborate_source(
                    P + "module Top:\n"
                    "    r = new rhoform.lib.passive.Resistor\n", path)
                found = _diagnostics(result)
                self.assertEqual([d["code"] for d in found], ["RHO2068"])
                self.assertEqual(found[0]["params"]["file"], path)
                self.assertIsNone(result.design)

    def test_a_missing_library_directory_resolves_nothing(self):
        from rhoform.elaborate import Library

        result = self.elaborate(
            "module Top:\n    r = new rhoform.lib.passive.Resistor\n",
            library=Library(self.tmp / "absent"))
        self.assertEqual([d["code"] for d in _diagnostics(result)],
                         ["RHO2067"])


if __name__ == "__main__":
    unittest.main()
