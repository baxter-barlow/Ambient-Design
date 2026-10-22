"""IR emission: the canonical encoder held byte-equal to the gate that
defines it, both hashes, schema validity, sort rules, source-map coverage,
and the determinism properties the hashes exist to prove.

tests/ir/check-hashes.py is loaded BY PATH here, never imported from
rhoform/: the package carries its own encoder, and this file is where the
two are shown to agree.
"""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

try:
    import lark  # noqa: F401 - availability probe only
    HAVE_LARK = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_LARK = False

try:
    import jsonschema
    HAVE_JSONSCHEMA = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_JSONSCHEMA = False

from rhoform import ir

ROOT = Path(__file__).resolve().parents[2]
PRAGMA = "#pragma rhoform-syntax 0.1"


def _gate():
    spec = importlib.util.spec_from_file_location(
        "_rhoform_check_hashes", ROOT / "tests" / "ir" / "check-hashes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = _gate()

DESIGN = PRAGMA + """

module Indicator:
    port ctl input
    port gnd power_in
    d1 = new rhoform.lib.semiconductor.Led(color = "red"):
        pin a passive
        pin k passive
    r_lim = new rhoform.lib.passive.Resistor(resistance = 560ohm +/- 1%):
        pin a passive
        pin b passive
        part abstract:
            resistance = 560ohm +/- 1%
            package = "axial_0207"
    net LED:
        d1.a
        r_lim.b
    ctl ~ r_lim.a
    d1.k ~ gnd

module Blinker:
    port vin power_in
    timer = new rhoform.lib.timer.Ne555:
        part "timer.555/ti-NE555P@2"
    c_t = new rhoform.lib.passive.Capacitor(capacitance = 1uF +/- 5%):
        pin a passive
        pin b passive
    indicator = new Indicator(current = 9.5mA (8mA to 10.5mA))
    mh1 = new rhoform.lib.mech.MountingHole(diameter = 3.2mm):
        hardware mounting_hole
        exclude_from_bom
        board_only
    tp_out = new rhoform.lib.mech.TestPoint:
        pin p passive
        hardware test_point
        exclude_from_bom
    net VCC(voltage_domain = "vbat_9v"):
        vin
        timer.vcc
    net GND(ground_domain = "gnd"):
        timer.gnd
        indicator.gnd
        c_t.b
    net OUT:
        timer.out
        indicator.ctl
        tp_out.p
    isolated c_t.a
    assert freq dynamic frequency(OUT) within 0.923Hz to 1.052Hz
    assert duty dynamic duty_cycle(OUT) within 0.533 to 0.558
"""

# The same design, respelled under T3 and reformatted: other units for the
# same values, other comments and blank lines, a wrapped argument list.
RESPELLED = PRAGMA + """
# a header comment the first spelling does not have
module Indicator:
    port ctl input
    port gnd power_in
    d1 = new rhoform.lib.semiconductor.Led(color = "red"):  # a trailer
        pin a passive
        pin k passive

    r_lim = new rhoform.lib.passive.Resistor(
        resistance = 0.56kohm +/- 5.6ohm):
        pin a passive
        pin b passive
        part abstract:
            resistance = 560ohm (554.4ohm to 565.6ohm)
            package = "axial_0207"
    net LED:
        d1.a
        r_lim.b
    ctl ~ r_lim.a
    d1.k ~ gnd
module Blinker:
    port vin power_in
    timer = new rhoform.lib.timer.Ne555:
        part "timer.555/ti-NE555P@2"
    c_t = new rhoform.lib.passive.Capacitor(capacitance = 1000nF +/- 5%):
        pin a passive
        pin b passive
    indicator = new Indicator(current = 0.0095A (8mA to 10500uA))
    mh1 = new rhoform.lib.mech.MountingHole(diameter = 3200um):
        hardware mounting_hole
        exclude_from_bom
        board_only
    tp_out = new rhoform.lib.mech.TestPoint:
        pin p passive
        hardware test_point
        exclude_from_bom
    net VCC(voltage_domain = "vbat_9v"):
        vin
        timer.vcc
    net GND(ground_domain = "gnd"):
        timer.gnd
        indicator.gnd
        c_t.b
    net OUT:
        timer.out
        indicator.ctl
        tp_out.p
    isolated c_t.a
    assert freq dynamic frequency(OUT) within 0.9230Hz to 1.0520Hz
    assert duty dynamic duty_cycle(OUT) within 0.5330 to 0.558
"""


def _design(source=DESIGN, path="blinker.rhoform"):
    from rhoform.elaborate import elaborate_source

    result = elaborate_source(source, path)
    assert result.ok, result.diagnostics.render()
    return result.design


class EncoderTest(unittest.TestCase):
    NUMBERS = (0, -0.0, 1, -1, 0.1, 1.5, 1500, 0.0015, 1e-7, 1.5e-7, 1e-5,
               0.000001, 1e21, 1e16, 1.2345678901234568e20, 1e-6, 1e20,
               5e-324, 1.7976931348623157e308, 2 ** 53, -(2 ** 53), 554.4,
               0.95, 100000, 9.5, 1.052, 3.3e-9)

    def test_number_spelling_matches_the_gate(self):
        for value in self.NUMBERS:
            with self.subTest(value=value):
                self.assertEqual(ir.canonical_number(value),
                                 GATE._canonical_number(value))
        self.assertEqual(ir.canonical_number(1e-7), "1e-7")
        self.assertEqual(ir.canonical_number(1e-5), "0.00001")
        self.assertEqual(ir.canonical_number(1e21), "1e+21")
        self.assertEqual(ir.canonical_number(-0.0), "0")

    def test_refusals_match_the_gate(self):
        for value in (2 ** 53 + 1, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ir.canonical_number(value)
                with self.assertRaises(ValueError):
                    GATE._canonical_number(value)
        with self.assertRaises(ValueError):
            ir.canonical_bytes({"x": "\ud800"})
        with self.assertRaises(TypeError):
            ir.canonical_bytes({"x": Decimal("1")})

    def test_committed_examples_encode_and_hash_identically(self):
        examples = sorted((ROOT / "ir" / "examples").glob("*.json"))
        self.assertTrue(examples)
        for path in examples:
            with self.subTest(path=path.name):
                document = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(ir.canonical_bytes(document),
                                 GATE.canonical_bytes(document))
                if path.name.endswith(".ir.json"):
                    self.assertEqual(ir.design_hash_of(document),
                                     GATE.design_hash_of(document))
                    self.assertEqual(ir.design_hash_of(document),
                                     document["header"]["design_hash"])

    def test_the_decimal_to_double_rule(self):
        self.assertEqual(ir.number(Decimal("0.1")), 0.1)
        # Round half to even at the 2^53 boundary.
        self.assertEqual(ir.number(Decimal(2 ** 53 + 1)), float(2 ** 53))


@unittest.skipUnless(HAVE_LARK, "lark (pinned in toolchain/versions.yaml) "
                     "is required")
class EmissionTest(unittest.TestCase):
    def setUp(self):
        self.design = _design()
        self.document = ir.to_ir(self.design)
        self.source_map = ir.to_source_map(
            self.design, self.document["header"]["design_hash"])

    def test_header(self):
        header = self.document["header"]
        self.assertEqual(header["ir_version"], 0)
        self.assertEqual(header["language_version"], "0.1.0")
        self.assertEqual(header["design_name"], "Blinker")
        self.assertEqual(header["canonical_form"], "rhoform-canonical-json/1")
        self.assertEqual(header["generator"]["name"], "rhoformc")
        self.assertEqual(header["design_hash"],
                         GATE.design_hash_of(self.document))

    def test_source_hash_is_the_pinned_serialization(self):
        # The entry file, then exactly the library modules it names (E-8):
        # connector, module, regulator and the rest are not read, so they
        # are not listed.
        data = DESIGN.encode()
        pairs = [["blinker.rhoform", hashlib.sha256(data).hexdigest()]]
        for module in ("mech", "passive", "semiconductor", "timer"):
            library = ROOT / "rhoform" / "lib" / f"{module}.rhoform"
            pairs.append([f"rhoform/lib/{module}.rhoform",
                          hashlib.sha256(library.read_bytes()).hexdigest()])
        expected = "sha256:" + hashlib.sha256(
            json.dumps(pairs, separators=(",", ":")).encode()
            + b"\n").hexdigest()
        self.assertEqual(self.document["header"]["source_hash"], expected)
        self.assertEqual(self.source_map["files"],
                         [{"path": path, "sha256": digest}
                          for path, digest in pairs])

    @unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema required")
    def test_documents_validate_against_their_schemas(self):
        for name, document in (("netlist-ir.schema.json", self.document),
                               ("source-map.schema.json", self.source_map)):
            with self.subTest(schema=name):
                schema = json.loads((ROOT / "ir" / name).read_text())
                jsonschema.Draft202012Validator(schema).validate(document)

    def test_the_gate_accepts_the_pair(self):
        self.assertEqual(GATE.sort_problems(self.document, "emitted"), [])
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "emitted.ir.json"
            ir_bytes, map_bytes = ir.emit(self.design)
            target.write_bytes(ir_bytes)
            (Path(scratch) / "emitted.sourcemap.json").write_bytes(map_bytes)
            problems, notes = [], []
            GATE.check_document(target, problems, notes)
        self.assertEqual(problems, [])

    def test_quantities_are_in_normal_form_units(self):
        instances = {i["path"]: i for i in self.document["instances"]}
        self.assertEqual(
            instances["/indicator/r_lim"]["parameters"]["resistance"],
            {"value": 560, "unit": "ohm",
             "tolerance": {"min": 554.4, "max": 565.6}})
        self.assertEqual(instances["/c_t"]["parameters"]["capacitance"],
                         {"value": 1, "unit": "uF",
                          "tolerance": {"min": 0.95, "max": 1.05}})
        self.assertEqual(instances["/mh1"]["ports"], [])
        self.assertNotIn("part", instances["/mh1"])
        self.assertEqual(instances["/timer"]["part"],
                         {"binding": "resolved",
                          "lockfile_key": "timer.555/ti-NE555P@2"})

    def test_nets_connections_and_assertions(self):
        nets = {n["name"]: n for n in self.document["nets"]}
        self.assertEqual(sorted(nets), ["GND", "N_c_t.a", "OUT", "VCC",
                                        "indicator/LED"])
        self.assertEqual(nets["GND"], {"name": "GND",
                                       "ground_domain": "gnd"})
        members = [(c["port"]["instance"], c["port"]["port"])
                   for c in self.document["connections"]
                   if c["net"] == "OUT"]
        self.assertEqual(members, [("/indicator", "ctl"),
                                   ("/indicator/r_lim", "a"),
                                   ("/timer", "out"), ("/tp_out", "p")])
        self.assertEqual(self.document["assertions"][0]["bounds"],
                         {"unit": "1", "min": 0.533, "max": 0.558})

    def test_source_map_covers_exactly_the_identities(self):
        identities = ({i["path"] for i in self.document["instances"]}
                      | {n["name"] for n in self.document["nets"]}
                      | {a["path"] for a in self.document["assertions"]})
        self.assertEqual(set(self.source_map["nodes"]), identities)
        root = self.source_map["nodes"]["/"]
        self.assertEqual(root["instantiation_trace"], [])
        start, end = root["declaration"]["byte_start"], \
            root["declaration"]["byte_end"]
        self.assertEqual(DESIGN.encode()[start:end], b"module Blinker:")
        nested = self.source_map["nodes"]["/indicator/d1"]
        self.assertEqual(nested["instantiation_trace"][0],
                         nested["declaration"])
        self.assertEqual(len(nested["instantiation_trace"]), 2)

    def test_the_gate_accepts_a_module_instantiated_twice(self):
        # Both copies of a reused module's members are declared by one
        # statement, so their declaration spans are identical. The gate
        # rejected that as an overlap until it learned the difference
        # between a shared span and an overlapping one.
        twice = PRAGMA + """

module Leg:
    port a passive
    r = new lib.R:
        pin a passive
        pin b passive
    net MID:
        r.b
    a ~ r.a
    assert m dynamic frequency(MID) within 1Hz to 2Hz

module Top:
    l1 = new Leg
    l2 = new Leg
    l1.a ~ l2.a
"""
        design = _design(twice, "twice.rhoform")
        source_map = ir.to_source_map(design, "")
        nodes = source_map["nodes"]
        for left, right in (("/l1/r", "/l2/r"), ("l1/MID", "l2/MID"),
                            ("/l1/m", "/l2/m")):
            with self.subTest(pair=(left, right)):
                self.assertEqual(nodes[left]["declaration"],
                                 nodes[right]["declaration"])
                self.assertNotEqual(nodes[left]["instantiation_trace"],
                                    nodes[right]["instantiation_trace"])
        with tempfile.TemporaryDirectory() as scratch:
            ir_bytes, map_bytes = ir.emit(design)
            (Path(scratch) / "twice.ir.json").write_bytes(ir_bytes)
            (Path(scratch) / "twice.sourcemap.json").write_bytes(map_bytes)
            (Path(scratch) / "twice.rhoform").write_bytes(twice.encode())
            problems, notes = [], []
            GATE.check_document(Path(scratch) / "twice.ir.json", problems,
                                notes, compile_root=Path(scratch))
        self.assertEqual(problems, [])
        self.assertEqual(notes, [])

    def test_source_hash_matches_the_gate(self):
        files = [(f.path, f.sha256) for f in self.design.files]
        self.assertEqual(
            ir.source_hash_of(files),
            GATE.source_hash_of([{"path": p, "sha256": h} for p, h in files]))

    def test_repeated_builds_are_byte_identical(self):
        self.assertEqual(ir.emit(_design()), ir.emit(_design()))

    def test_t3_respelling_and_reformatting_keep_the_design_hash(self):
        respelled = ir.to_ir(_design(RESPELLED))
        self.assertEqual(respelled["header"]["design_hash"],
                         self.document["header"]["design_hash"])
        self.assertNotEqual(respelled["header"]["source_hash"],
                            self.document["header"]["source_hash"])
        self.assertEqual(
            {k: v for k, v in respelled.items() if k != "header"},
            {k: v for k, v in self.document.items() if k != "header"})

    def test_a_design_change_moves_the_design_hash(self):
        changed = ir.to_ir(_design(DESIGN.replace("560ohm +/- 1%",
                                                  "562ohm +/- 1%")))
        self.assertNotEqual(changed["header"]["design_hash"],
                            self.document["header"]["design_hash"])
