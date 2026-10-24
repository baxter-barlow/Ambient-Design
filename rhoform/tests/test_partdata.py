"""Part data (rhoform.partdata): exact reading, byte identity, version
routing, the shared lint core, binding through `implements`, honest
statistic tags, and hermeticity.

The binding tests read the bundled standard library's definitions through
the elaborator, so they skip without the lark pin, as test_library.py does;
the schema tests skip without jsonschema, as test_ir.py does.
parts/lint-part-data.py's self-test drives every lint clause one case at a
time; this file holds the module to its contracts.
"""

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

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

from rhoform import partdata

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "rhoform" / "parts"
EXAMPLES = ROOT / "parts" / "examples"
NE555 = STORE / "ti" / "ne555p.part.json"
AP7361C = STORE / "diodes" / "ap7361c-33e-13.part.json"
ESP32 = STORE / "espressif" / "esp32-s3-wroom-1-n8r2.part.json"
# parts/part-data.schema.json as frozen (D3 Freeze Record). v0 is immutable:
# version 1 is a second file, never an edit to this one.
V0_SCHEMA_SHA256 = \
    "6d9e35aa436c3821f1e7d2af1f2ae576deef27c2fa3753d7155800aff7995882"


def _doc(path):
    return partdata.parse(path.read_bytes())


def _numbers(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _numbers(value)
    elif isinstance(node, list):
        for value in node:
            yield from _numbers(value)
    elif not isinstance(node, (str, bool)) and node is not None:
        yield node


def _definition_pins(qualified):
    """(name, role, designators) for each pin of one bundled definition,
    read from the library's parse tree as test_library.py reads it."""
    from rhoform import elaborate as E

    _rhoform, _lib, module, name = qualified.split(".")
    result = E.BUNDLED.load(module)
    for node in result.tree.children:
        if E._is_tree(node) and node.data == "component_def" \
                and str(node.children[1]) == name:
            return [(str(E._tokens(pin, "NAME")[0]),
                     str(E._tokens(pin, "NAME")[1]),
                     tuple(str(d.children[0])
                           for d in E._trees(pin, "designator")))
                    for pin in E._trees(node, "pin_decl")]
    raise LookupError(f"the bundled library defines no {qualified}")


class ReadingTest(unittest.TestCase):
    def test_a_fraction_is_an_exact_decimal(self):
        value = partdata.parse(b'{"x": 0.3}')["x"]
        self.assertIsInstance(value, Decimal)
        self.assertEqual(value, Decimal("0.3"))
        self.assertEqual(Fraction(value), Fraction(3, 10))

    def test_an_integer_is_an_int(self):
        value = partdata.parse(b'{"x": 140}')["x"]
        self.assertIs(type(value), int)

    def test_no_store_value_is_a_float(self):
        for path in sorted(STORE.glob("*/*.part.json")):
            with self.subTest(record=path.name):
                kinds = {type(n) for n in _numbers(_doc(path))}
                self.assertLessEqual(kinds, {int, Decimal})

    def test_duplicate_keys_nan_and_bad_utf8_are_refused(self):
        for data in (b'{"a": 1, "a": 2}', b'{"a": NaN}', b'{"a": Infinity}',
                     b'{"a": "\xff"}', b'{"a": '):
            with self.subTest(data=data):
                with self.assertRaises(partdata.PartDataError) as caught:
                    partdata.parse(data)
                self.assertEqual(caught.exception.problems[0].check, "json")

    def test_text_is_refused_so_bytes_are_what_get_hashed(self):
        with self.assertRaises(TypeError):
            partdata.parse('{"a": 1}')

    def test_lone_surrogates_and_deep_nesting_are_json_problems(self):
        # Each of these escaped every reader as a bare exception: a lone
        # surrogate decodes and then cannot be encoded back, and nesting
        # the decoder accepts overflowed the layout's recursion.
        limit = partdata.MAX_NESTING
        for data in (b'{"a": "\\ud800"}\n', b'{"a": ["\\udfff"]}\n',
                     b'{"\\ud800": 1}\n', b'"\\ud800"\n',
                     b"[" * 100000 + b"]" * 100000,
                     b'{"a": ' * 100000 + b"1" + b"}" * 100000,
                     b"[" * (limit + 1) + b"]" * (limit + 1)):
            for reader in (partdata.parse, partdata.canonical_layout):
                with self.subTest(data=data[:24], reader=reader.__name__):
                    with self.assertRaises(partdata.PartDataError) as caught:
                        reader(data)
                    self.assertEqual(
                        [p.check for p in caught.exception.problems], ["json"])
            with self.subTest(data=data[:24], reader="check"):
                doc, problems, _ = partdata.check(data)
                self.assertIsNone(doc)
                self.assertEqual([p.check for p in problems], ["json"])
            with self.subTest(data=data[:24], reader="load"), \
                    tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "x.part.json"
                path.write_bytes(data)
                with self.assertRaises(partdata.PartDataError):
                    partdata.load(path)

    def test_the_nesting_limit_admits_its_own_depth_and_a_surrogate_pair(self):
        want = []
        for _level in range(partdata.MAX_NESTING - 1):
            want = [want]
        data = b"[" * partdata.MAX_NESTING + b"]" * partdata.MAX_NESTING
        self.assertEqual(partdata.parse(data), want)
        self.assertEqual(partdata.canonical_layout(data).count(b"["),
                         partdata.MAX_NESTING)
        self.assertEqual(partdata.parse(b'{"a": "\\ud83d\\ude00"}')["a"],
                         "\U0001f600")
        # Room to spare: no record of any version nests near the limit.
        for path in sorted(STORE.glob("*/*.part.json")) + \
                sorted(EXAMPLES.glob("**/*.part.json")):
            with self.subTest(record=path.name):
                partdata.parse(path.read_bytes())


class IdentityTest(unittest.TestCase):
    def test_revision_is_the_sha256_of_the_exact_bytes(self):
        data = NE555.read_bytes()
        self.assertEqual(partdata.revision(data),
                         "sha256:" + hashlib.sha256(data).hexdigest())

    def test_store_records_are_in_canonical_layout(self):
        for path in sorted(STORE.glob("*/*.part.json")):
            with self.subTest(record=path.name):
                data = path.read_bytes()
                self.assertEqual(partdata.canonical_layout(data), data)
                self.assertEqual(partdata.layout_problems(data), [])

    def test_numbers_keep_their_spelling(self):
        # 4.0 is not respelt 4, and 1e3 is not respelt 1000: the round trip
        # keeps each token, so the layout rule can never rewrite a value.
        data = b'{\n  "a": 4.0,\n  "b": 1e3,\n  "c": -0\n}\n'
        self.assertEqual(partdata.canonical_layout(data), data)

    def test_a_layout_only_change_is_caught_and_moves_the_revision(self):
        data = NE555.read_bytes()
        reindented = (json.dumps(json.loads(data), indent=4, sort_keys=True)
                      + "\n").encode()
        problems = partdata.layout_problems(reindented)
        self.assertEqual([p.check for p in problems], ["L22"])
        self.assertNotEqual(partdata.revision(reindented),
                            partdata.revision(data))

    def test_canonical_layout_is_idempotent(self):
        messy = b'{"b":[1,{"y":2,"x":1}],"a":"\\u00b5"}'
        once = partdata.canonical_layout(messy)
        self.assertEqual(partdata.canonical_layout(once), once)
        self.assertIn("µ".encode(), once)

    def test_the_store_path_is_the_part_id(self):
        for path in sorted(STORE.glob("*/*.part.json")):
            with self.subTest(record=path.name):
                self.assertEqual(
                    partdata.store_path(_doc(path)["part_id"]), path)


@unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema required")
class VersionTest(unittest.TestCase):
    def test_versions_zero_and_one_route_to_their_own_schemas(self):
        self.assertEqual(sorted(partdata.SCHEMAS), [0, 1])
        self.assertEqual(partdata.validate(_doc(NE555)), [])
        self.assertEqual(
            partdata.validate(_doc(EXAMPLES / "ti-sn74hc00d.part.json")), [])

    def test_an_unknown_version_is_refused_not_read_as_a_neighbour(self):
        for version in (2, -1, None, True, "1"):
            with self.subTest(version=version):
                doc = dict(_doc(NE555), schema_version=version)
                problems = partdata.validate(doc)
                self.assertEqual([p.check for p in problems], ["version"])

    def test_v1_is_additive_over_v0(self):
        # Every v0 example, relabelled version 1, is a valid v1 record.
        for path in sorted(EXAMPLES.glob("*.part.json")):
            with self.subTest(record=path.name):
                doc = dict(_doc(path), schema_version=1)
                self.assertEqual(partdata.validate(doc), [])

    def test_v0_refuses_what_v1_adds(self):
        doc = dict(_doc(NE555), schema_version=0)
        self.assertTrue(any(p.check == "schema"
                            for p in partdata.validate(doc)))

    def test_v0_schema_is_byte_identical_to_its_freeze(self):
        self.assertEqual(hashlib.sha256(
            (ROOT / "parts" / "part-data.schema.json").read_bytes()
        ).hexdigest(), V0_SCHEMA_SHA256)


@unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema required")
class LoadTest(unittest.TestCase):
    def test_store_records_load_with_their_revision(self):
        for path in sorted(STORE.glob("*/*.part.json")):
            with self.subTest(record=path.name):
                record = partdata.load(path)
                self.assertEqual(record.revision,
                                 partdata.revision(path.read_bytes()))
                self.assertEqual(record.schema_version, 1)

    def test_the_unperformable_check_is_kept_not_dropped(self):
        record = partdata.load(AP7361C)
        self.assertEqual([(p.check, p.pointer) for p in record.unchecked],
                         [("L12", "/pins/2/recommended/current")])

    def test_a_canonical_v0_record_loads(self):
        data = partdata.canonical_layout(
            (EXAMPLES / "ti-sn74hc00d.part.json").read_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.part.json"
            path.write_bytes(data)
            self.assertEqual(partdata.load(path).schema_version, 0)

    def test_each_kind_of_defect_refuses_the_record(self):
        canonical = NE555.read_bytes()
        doc = _doc(NE555)
        lint_defect = copy.deepcopy(doc)
        lint_defect["implements"][0]["pins"]["vcc"] = "GND"
        schema_defect = dict(doc, lifecycle="immortal")
        version_defect = dict(doc, schema_version=9)

        def canonical_bytes(document):
            return partdata.canonical_layout(json.dumps(
                document, default=float).encode())

        cases = (("json", b"{"), ("layout", None),
                 ("L14", canonical_bytes(lint_defect)),
                 ("schema", canonical_bytes(schema_defect)),
                 ("version", canonical_bytes(version_defect)))
        for check, data in cases:
            with self.subTest(check=check), \
                    tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "x.part.json"
                path.write_bytes(canonical.replace(b"\n", b"\r\n")
                                 if data is None else data)
                with self.assertRaises(partdata.PartDataError) as caught:
                    partdata.load(path)
                got = {p.check for p in caught.exception.problems}
                self.assertIn("L22" if check == "layout" else check, got)

    def test_a_picked_record_refuses_not_transcribed_r29a_data(self):
        doc = _doc(NE555)
        doc["absent"].insert(0, {"pointer": "/modes/0/draw/0/current/min",
                                 "reason": "not-transcribed",
                                 "target": doc["modes"][0]["id"]})
        data = partdata.canonical_layout(json.dumps(doc, default=float).encode())
        _doc_, problems, _ = partdata.check(data)
        self.assertEqual(problems, [])
        _doc_, problems, _ = partdata.check(data, picked=True)
        self.assertEqual([p.check for p in problems], ["L18"])


class LintTest(unittest.TestCase):
    def test_every_record_lints_clean(self):
        for path in sorted(STORE.glob("*/*.part.json")) + \
                sorted(EXAMPLES.glob("*.part.json")):
            with self.subTest(record=path.name):
                self.assertEqual(partdata.lint_problems(_doc(path), []), [])

    def test_the_r29a_families_cover_and_are_covered(self):
        for pointer, want in (("/modes", True), ("/modes/3/draw", True),
                              ("/pins/2/abs_max/voltage", True),
                              ("/pins/2", True), ("/pins", True),
                              ("/ratings", True), ("/ratings/abs_max", True),
                              ("/pin_classes/0/abs_max", True),
                              ("/ratings/thermal", False),
                              ("/pins/2/characteristics", False),
                              ("/parameters", False)):
            with self.subTest(pointer=pointer):
                self.assertEqual(partdata.touches_r29a(pointer), want)

    def test_problems_carry_the_pointer_they_are_about(self):
        doc = _doc(ESP32)
        doc["pins"][3]["class"] = "adc"
        problems = partdata.lint_problems(doc, [])
        self.assertIn(("L15", "/pins/3/class"),
                      [(p.check, p.pointer) for p in problems])


class CompatibilityTest(unittest.TestCase):
    def test_roles_are_the_schemas_pin_roles(self):
        for name in ("part-data.schema.json", "part-data.v1.schema.json"):
            with self.subTest(schema=name):
                schema = json.loads((ROOT / "parts" / name).read_text(
                    encoding="utf-8"))
                self.assertEqual(sorted(partdata.ROLES),
                                 sorted(schema["$defs"]["PinRole"]["enum"]))

    def test_the_relation(self):
        for record, definition, want in (
                ("input", "input", True),
                ("passive", "power_out", True),
                ("passive", "nc", True),
                ("bidirectional", "input", True),
                ("bidirectional", "open_collector", True),
                ("bidirectional", "passive", False),
                ("bidirectional", "power_in", False),
                ("output", "input", False),
                ("open_drain", "output", False),
                ("power_in", "passive", False)):
            with self.subTest(record=record, definition=definition):
                self.assertEqual(partdata.compatible(record, definition), want)


@unittest.skipUnless(HAVE_LARK, "lark required")
class BindTest(unittest.TestCase):
    """The three benchmark records joined to the definitions they implement,
    through `implements` and nothing else."""

    def bind(self, path, definition):
        return partdata.bind(_doc(path), definition,
                             _definition_pins(definition))

    def test_every_store_record_names_real_definitions_and_all_their_pins(self):
        # Totality over the DEFINITION, which the lint core cannot see.
        for path in sorted(STORE.glob("*/*.part.json")):
            for entry in _doc(path)["implements"]:
                with self.subTest(record=path.name,
                                  definition=entry["definition"]):
                    pins = {n for n, _r, _d in
                            _definition_pins(entry["definition"])}
                    self.assertEqual(set(entry["pins"]), pins)

    def test_ne555_joins_every_pin_and_reports_the_ctl_conflict(self):
        binding = self.bind(NE555, "rhoform.lib.timer.Ne555")
        self.assertEqual(
            {name: facts.pin for name, facts in binding.ports.items()},
            {"ctl": "CONT", "dis": "DISCH", "gnd": "GND", "out": "OUT",
             "rst": "RESET", "thr": "THRES", "trig": "TRIG", "vcc": "VCC"})
        # The library declares ctl passive and TI's pin table says CONT is
        # input/output (bidirectional), which cannot carry a passive port.
        # That disagreement is real and is the library's to fix (landing
        # L3); the binder reports it rather than overriding either side.
        self.assertEqual([(p.check, p.pointer) for p in binding.problems],
                         [("role-conflict", "/pins/0/role")])

    def test_the_regulator_joins_cleanly(self):
        binding = self.bind(AP7361C, "rhoform.lib.regulator.LinearRegulator")
        self.assertEqual(binding.problems, ())
        self.assertEqual({n: f.pin for n, f in binding.ports.items()},
                         {"gnd": "GND", "vin": "IN", "vout": "OUT"})

    def test_the_module_joins_cleanly_without_guessing_names(self):
        binding = self.bind(ESP32, "rhoform.lib.module.Esp32S3Wroom1")
        self.assertEqual(binding.problems, ())
        self.assertEqual(len(binding.ports), 39)
        # The three joins name guessing gets wrong.
        self.assertEqual(binding.ports["io43"].pin, "TXD0")
        self.assertEqual(binding.ports["io44"].pin, "RXD0")
        self.assertEqual(binding.ports["p3v3"].pin, "3V3")
        # Supply draw arrives keyed by the DEFINITION's pin.
        self.assertTrue(all(set(draw) == {"p3v3"}
                            for _id, _kind, _cond, draw in binding.modes))

    def test_no_implements_entry_means_no_join(self):
        doc = _doc(AP7361C)
        doc["implements"] = [dict(doc["implements"][0],
                                  definition="acme.lib.Other")]
        # Same pin names would match by name; they must not.
        binding = partdata.bind(doc, "rhoform.lib.regulator.LinearRegulator",
                                [("GND", "power_in", ()), ("IN", "power_in", ()),
                                 ("OUT", "power_out", ())])
        self.assertEqual(binding.ports, {})
        self.assertEqual([p.check for p in binding.problems],
                         ["no-implements"])

    def test_unmapped_unknown_and_designator_problems(self):
        doc = _doc(NE555)
        del doc["implements"][0]["pins"]["vcc"]
        doc["implements"][0]["pins"]["extra"] = "VCC"
        pins = _definition_pins("rhoform.lib.timer.Ne555")
        pins = [(n, r, ("9",) if n == "out" else d) for n, r, d in pins]
        binding = partdata.bind(doc, "rhoform.lib.timer.Ne555", pins)
        self.assertEqual(sorted(p.check for p in binding.problems),
                         ["designator-mismatch", "pin-unknown",
                          "pin-unmapped", "role-conflict"])
        self.assertNotIn("vcc", binding.ports)


class ViewTest(unittest.TestCase):
    """Statistic tags, relative bounds, condition arrays, classes, absences,
    outputs and straps, as a checker reads them."""

    def ports(self, path, definition, pins):
        return partdata.bind(_doc(path), definition, pins).ports

    def test_min_and_max_are_guarantees_typ_and_peak_never(self):
        regulator = self.ports(AP7361C, "rhoform.lib.regulator.LinearRegulator",
                               [("vout", "power_out", ())])["vout"]
        floor, = regulator.capability["source_current"]
        self.assertEqual([(v.statistic, v.bound, v.guaranteed)
                          for v in floor.values], [("min", Decimal("1.0"), True)])
        dropout = regulator.output["dropout"]
        self.assertEqual(len(dropout), 2)
        self.assertEqual([[(v.statistic, v.guaranteed) for v in m.values]
                          for m in dropout],
                         [[("typ", False), ("max", True)], [("typ", False)]])
        binding = partdata.bind(_doc(ESP32), "rhoform.lib.module.Esp32S3Wroom1",
                                [("io19", "bidirectional", ())])
        drive, = binding.ports["io19"].capability["source_current"]
        self.assertEqual(drive.guaranteed, ())
        peaks = [m for _i, _k, _c, draw in binding.modes for m in draw.values()
                 if m.get("peak")]
        self.assertTrue(peaks)
        self.assertTrue(all(m.guaranteed == () for m in peaks))

    def test_an_estimated_limit_is_not_a_guarantee(self):
        doc = _doc(AP7361C)
        doc["provenance"]["/pins/2/capability/source_current"]["confidence"] = \
            "estimated"
        facts = partdata.bind(doc, "rhoform.lib.regulator.LinearRegulator",
                              [("vout", "power_out", ())]).ports["vout"]
        floor, = facts.capability["source_current"]
        self.assertEqual(floor.confidence, "estimated")
        self.assertEqual(floor.guaranteed, ())

    def test_a_relative_bound_stays_symbolic(self):
        rst = self.ports(NE555, "rhoform.lib.timer.Ne555",
                         [("rst", "input", ())])["rst"]
        limit, = rst.abs_max["voltage"]
        self.assertEqual(limit.get("max").bound,
                         partdata.Relative("VCC", Decimal(1), Decimal(0)))
        self.assertTrue(limit.get("max").guaranteed)

    def test_both_ne555_columns_arrive_with_their_conditions(self):
        thr = self.ports(NE555, "rhoform.lib.timer.Ne555",
                         [("thr", "input", ())])["thr"]
        levels = thr.characteristics["threshold_voltage_level"]
        self.assertEqual(
            sorted((m.conditions["vcc"]["typ"], m.get("min").bound,
                    m.get("max").bound) for m in levels),
            [(5, Decimal("2.4"), Decimal("4.2")),
             (15, Decimal("8.8"), Decimal("11.2"))])

    def test_class_data_and_class_absences_reach_every_member(self):
        ports = self.ports(ESP32, "rhoform.lib.module.Esp32S3Wroom1",
                           [("io35", "bidirectional", ()),
                            ("en", "input", ())])
        io35 = ports["io35"]
        self.assertEqual(io35.pin_class, "gpio")
        self.assertIn("vih", io35.characteristics)
        self.assertEqual(io35.characteristics["vih"][0].pointer,
                         "/pin_classes/0/characteristics/vih")
        self.assertEqual(io35.abs_max, {})
        self.assertEqual(io35.absent, {"abs_max": "vendor-unpublished"})
        self.assertEqual(ports["en"].absent, {"abs_max": "vendor-unpublished"})

    def test_an_output_states_what_it_delivers_not_a_window(self):
        vout = self.ports(AP7361C, "rhoform.lib.regulator.LinearRegulator",
                          [("vout", "power_out", ())])["vout"]
        accuracy, = vout.output["voltage"]
        self.assertEqual(accuracy.conditions["iout"]["typ"], 100)
        self.assertNotIn("voltage", vout.recommended)

    def test_straps(self):
        binding = partdata.bind(_doc(ESP32), "rhoform.lib.module.Esp32S3Wroom1",
                                [("io0", "bidirectional", ()),
                                 ("io3", "bidirectional", ())])
        self.assertEqual(binding.ports["io0"].strap["default"], "pull_up")
        self.assertEqual(binding.ports["io3"].strap["default"], "floating")
        self.assertEqual([s["id"] for s in binding.straps],
                         ["joint_download_boot", "spi_boot"])


# Runs in a child before anything is called: every path opened and every
# network attempt is recorded, and the interpreter's own install locations
# are reported so they can be set aside (imports read them).
_AUDIT = r'''
import json, os, site, sys, sysconfig
sys.path.insert(0, sys.argv[1])
from rhoform import partdata
import jsonschema
_python = sorted(set(sysconfig.get_paths().values())
                 | set(site.getsitepackages())
                 | {site.getusersitepackages(), sys.prefix, sys.base_prefix,
                    sys.exec_prefix, sys.base_exec_prefix})
events = []
def _hook(event, args):
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        events.append(["open", os.fsdecode(os.fspath(args[0]))])
    elif event.split(".")[0] in ("socket", "http", "urllib", "ftplib",
                                 "smtplib", "ssl"):
        events.append(["network", event])
sys.addaudithook(_hook)
record = sys.argv[2]
marks = {}
marks["first"] = len(events); partdata.load(record)
marks["second"] = len(events); doc = partdata.load(record).document
marks["pure"] = len(events)
data = open(record, "rb").read()
marks["after_read"] = len(events)
partdata.parse(data); partdata.layout_problems(data); partdata.revision(data)
partdata.lint_problems(doc, []); partdata.validate(doc)
partdata.bind(doc, "rhoform.lib.timer.Ne555", [("vcc", "power_in", ("8",))])
marks["end"] = len(events)
print(json.dumps({"events": events, "marks": marks, "python": _python}))
'''


@unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema required")
class HermeticTest(unittest.TestCase):
    def test_load_opens_its_path_and_its_schema_and_nothing_else(self):
        done = subprocess.run(
            [sys.executable, "-c", _AUDIT, str(ROOT), str(NE555)],
            capture_output=True, text=True, timeout=120,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        real = os.path.realpath
        python = [real(p) for p in report["python"]]

        def ours(events):
            return [real(path) if kind == "open" else kind + ":" + path
                    for kind, path in events
                    if kind != "open" or not any(
                        real(path) == p or real(path).startswith(p + os.sep)
                        for p in python)]

        events, marks = report["events"], report["marks"]
        schema = real(ROOT / "parts" / "part-data.v1.schema.json")
        record = real(NE555)
        self.assertFalse([e for e in events if e[0] == "network"])
        self.assertEqual(ours(events[marks["first"]:marks["second"]]),
                         [record, schema])
        self.assertEqual(ours(events[marks["second"]:marks["pure"]]),
                         [record])
        self.assertEqual(ours(events[marks["after_read"]:marks["end"]]), [])


if __name__ == "__main__":
    unittest.main()
