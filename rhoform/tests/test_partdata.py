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

    def test_the_part_id_rule_is_the_schemas(self):
        for name in ("part-data.schema.json", "part-data.v1.schema.json"):
            with self.subTest(schema=name):
                schema = json.loads((ROOT / "parts" / name).read_text(
                    encoding="utf-8"))
                self.assertEqual(partdata.PART_ID.pattern,
                                 schema["properties"]["part_id"]["pattern"])

    def test_an_id_that_is_not_a_part_id_is_refused_not_resolved(self):
        # `../x` resolved to a file beside the store, and `a/../../b` died
        # in the split with a bare ValueError.
        for part_id in ("../x", "a/../../b", "ti/../../etc/passwd",
                        "/etc/passwd", "/ti/ne555p", "ti/ne555p/",
                        "ti\\ne555p", "ti/..\\..\\x", "..", "ti/..", "ti/.",
                        "./ne555p", "", "ti", "ti/ne555p/x", "TI/NE555P",
                        "ti/ne555p\n", None, 42, b"ti/ne555p"):
            with self.subTest(part_id=part_id):
                with self.assertRaises(partdata.PartDataError) as caught:
                    partdata.store_path(part_id)
                self.assertEqual(
                    [p.check for p in caught.exception.problems], ["part_id"])

    def test_every_id_it_admits_names_a_file_one_level_under_the_store(self):
        for part_id in ("ti/ne555p", "a/b..c", "x-1/y.z_2"):
            with self.subTest(part_id=part_id):
                path = partdata.store_path(part_id)
                self.assertEqual(path.parent.parent, partdata.STORE)
                self.assertEqual(os.path.normpath(path), str(path))
                self.assertTrue(path.name.endswith(partdata.RECORD_SUFFIX))


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


class NumberAgreementTest(unittest.TestCase):
    """partdata and the schema gate read one record's numbers differently --
    exact Decimals here, floats there -- and must reach one verdict on its
    shape (AMB-151 item 16)."""

    def check_both(self, data, want_valid):
        import jsonschema
        exact = partdata.parse(data)
        problems = partdata.validate(exact)
        # The schema gate's reading: json.loads, floats, the same schema.
        loose = json.loads(data)
        schema = json.loads((ROOT / "parts" / partdata.SCHEMAS[1]).read_text(
            encoding="utf-8"))
        gate = list(jsonschema.validators.validator_for(schema)(schema)
                    .iter_errors(loose))
        self.assertEqual(problems == [], want_valid, problems)
        self.assertEqual(gate == [], want_valid, gate)

    def respelt(self, old, new):
        data = NE555.read_bytes()
        self.assertEqual(data.count(old), 1)
        return data.replace(old, new)

    @unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema required")
    def test_an_integral_fraction_is_an_integer_to_both_readers(self):
        self.check_both(self.respelt(b'"pin_count": 8', b'"pin_count": 8.0'),
                        True)
        self.check_both(self.respelt(b'"pin_count": 8', b'"pin_count": 8.5'),
                        False)

    @unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema required")
    def test_schema_version_1_0_is_version_1_to_both_readers(self):
        data = self.respelt(b'"schema_version": 1', b'"schema_version": 1.0')
        self.check_both(data, True)
        self.assertEqual(partdata.schema_version(partdata.parse(data)), 1)
        self.assertIsNone(partdata.schema_version(
            partdata.parse(b'{"schema_version": 1.5}')))


class VocabularyTest(unittest.TestCase):
    """L20: the keys a check may read, each with one dimension."""

    def test_every_dimension_spec_names_a_dimension(self):
        from rhoform.check import values
        specs = [spec for section in partdata.VOCABULARY.values()
                 for spec in section.values()]
        specs += list(partdata.CLOSED_DIMENSIONS.values())
        specs += list(partdata.CONDITION_DIMENSIONS.values())
        for spec in sorted(set(specs)):
            with self.subTest(spec=spec):
                dimension, kind = partdata._dimension(spec)
                self.assertIsInstance(dimension, values.Dimension)
                self.assertIn(kind, values.UNIT_KINDS)

    def test_keys_the_dsl_also_names_have_the_dsls_dimension(self):
        # A record value RHO6007 compares with a `part abstract` constraint
        # of the same name must be in the same dimension, or the comparison
        # is between two different quantities.
        from rhoform.check import dimensions, values
        for name, (dimension, _kind) in sorted(
                dimensions.CONSTRAINT_VOCABULARY.items()):
            for section, keys in sorted(partdata.VOCABULARY.items()):
                if name in keys:
                    with self.subTest(key=name, section=section):
                        self.assertEqual(
                            partdata._dimension(keys[name])[0],
                            values.named(dimension))

    def test_the_slot_a_pointer_names(self):
        for pointer, want in (
                ("/pins/2/abs_max/voltage", ("closed", "voltage", "voltage")),
                ("/pins/2/output/dropout/1", ("closed", "dropout", "voltage")),
                ("/pin_classes/0/capability/source_current",
                 ("closed", "source_current", "current")),
                ("/series/resistance/0", ("closed", "resistance",
                                          "resistance")),
                ("/modes/3/draw/0/current", ("closed", "current", "current")),
                ("/parameters/capacitance", ("parameters", "capacitance",
                                             "capacitance")),
                ("/ratings/recommended/voltage_rating/1",
                 ("ratings/recommended", "voltage_rating", "voltage")),
                ("/ratings/thermal/theta_ja",
                 ("ratings/thermal", "theta_ja", "temperature/power")),
                ("/pins/0/characteristics/required_supply_current",
                 ("characteristics", "required_supply_current", "current")),
                ("/pins/2/output/voltage/0/conditions/ta",
                 ("conditions", "ta", "temperature")),
                ("/parameters/flux_capacity", None),
                ("/pins/2/characteristics/start_up_time", None),
                ("/pins/2/output/voltage/0/conditions/vout_range", None)):
            with self.subTest(pointer=pointer):
                self.assertEqual(partdata.vocabulary_slot(pointer), want)

    def test_the_readme_defines_every_key(self):
        # The key's MEANING is the contract; its dimension alone is not.
        text = (ROOT / "parts" / "README.md").read_text(encoding="utf-8")
        start = text.index("## Checker-reliable keys")
        section = text[start:text.index("\n## ", start + 1)]
        for where, keys in sorted(partdata.VOCABULARY.items()):
            for key in sorted(keys):
                with self.subTest(section=where, key=key):
                    self.assertIn(f"`{key}`", section)
        for name in sorted(partdata.CONDITION_DIMENSIONS):
            with self.subTest(condition=name):
                self.assertIn(f"`{name}`", section)

    def test_the_store_records_read_as_their_slots(self):
        # Every Measure a check may read parses and has its dimension: the
        # lint's verdict, restated against the checker's own reader.
        from rhoform.check import values
        for path in sorted(STORE.glob("*/*.part.json")):
            for pointer, measure in partdata.walk_measures(_doc(path)):
                slot = partdata.vocabulary_slot(pointer)
                if slot is None:
                    continue
                with self.subTest(record=path.name, pointer=pointer):
                    unit = values.parse_part_unit(measure["unit"])
                    want = partdata._dimension(slot[2])
                    self.assertEqual((unit.dimension, unit.kind), want)


class ConditionValueTest(unittest.TestCase):
    """Conditions compare by value (AMB-151 item 15)."""

    def key(self, conditions):
        return partdata.condition_key(conditions)

    def test_spellings_of_one_value_are_one_condition(self):
        five = {"vcc": {"unit": "V", "typ": 5}}
        for same in ({"vcc": {"unit": "V", "typ": Decimal("5.0")}},
                     {"vcc": {"unit": "mV", "typ": 5000}},
                     {"vcc": {"typ": Decimal("5.00"), "unit": "V"}}):
            with self.subTest(same=same):
                self.assertEqual(self.key(five), self.key(same))

    def test_different_values_kinds_and_statistics_stay_apart(self):
        base = {"ta": {"unit": "degC", "typ": 25}}
        for other in ({"ta": {"unit": "degC", "typ": 85}},
                      {"ta": {"unit": "K", "typ": 25}},
                      {"ta": {"unit": "degC", "max": 25}},
                      {"ta": "25 degC"},
                      {"tj": {"unit": "degC", "typ": 25}}):
            with self.subTest(other=other):
                self.assertNotEqual(self.key(base), self.key(other))

    def test_strings_and_unreadable_units_compare_as_written(self):
        self.assertEqual(self.key({"vin": "VOUT + 1 V"}),
                         self.key({"vin": "VOUT + 1 V"}))
        self.assertNotEqual(self.key({"vin": "VOUT + 1 V"}),
                            self.key({"vin": "VOUT+1V"}))
        self.assertNotEqual(self.key({"x": {"unit": "furlong", "typ": 1}}),
                            self.key({"x": {"unit": "furlong", "typ": 2}}))

    def test_a_strap_level_x_is_a_pin_left_out(self):
        self.assertEqual(partdata._strap_key({"IO0": "1", "IO46": "x"}),
                         partdata._strap_key({"IO0": "1"}))
        self.assertNotEqual(partdata._strap_key({"IO0": "1", "IO46": "0"}),
                            partdata._strap_key({"IO0": "1"}))


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

    def test_every_relative_bound_names_a_record_pin(self):
        # L23 over the store, and the reason it exists: a reference is a
        # record pin name, and nothing else resolves.
        for path in sorted(STORE.glob("*/*.part.json")):
            doc = _doc(path)
            names = {pin["name"] for pin in doc["pins"]}
            for pointer, measure in partdata.walk_measures(doc):
                for stat in partdata.STATISTICS:
                    bound = measure.get(stat)
                    if isinstance(bound, dict):
                        with self.subTest(record=path.name, pointer=pointer):
                            self.assertIn(bound["reference"], names)
        doc = _doc(NE555)
        doc["pins"][4]["abs_max"]["voltage"]["max"]["reference"] = "V+"
        self.assertEqual(
            [(p.check, p.pointer) for p in partdata.lint_problems(doc, [])],
            [("L23", "/pins/4/abs_max/voltage/max/reference")])

    def test_an_absence_cannot_contradict_the_class(self):
        doc = _doc(ESP32)
        io0 = [p["name"] for p in doc["pins"]].index("IO0")
        doc["absent"].append({"pointer": f"/pins/{io0}/characteristics/vih",
                              "reason": "vendor-unpublished",
                              "target": "IO0"})
        doc["absent"].sort(key=lambda a: a["pointer"])
        # Its parent does not resolve on the raw pin; that is not what is
        # wrong. The class supplies vih to IO0.
        doc["pins"][io0]["characteristics"] = {"capacitance": {
            "unit": "pF", "typ": 2}}
        self.assertIn(("L18", f"/pins/{io0}/characteristics/vih"),
                      [(p.check, p.pointer)
                       for p in partdata.lint_problems(doc, [])])

    def test_a_unit_outside_the_grammar_is_a_problem_not_a_crash(self):
        doc = _doc(AP7361C)
        doc["pins"][0]["abs_max"]["voltage"]["unit"] = "%"
        self.assertEqual(
            [(p.check, p.pointer) for p in partdata.lint_problems(doc, [])],
            [("L20", "/pins/0/abs_max/voltage/unit")])

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

    def test_a_part_specific_definition_admits_only_the_same_role(self):
        for record, definition, want in (
                ("input", "input", True),
                ("bidirectional", "bidirectional", True),
                ("bidirectional", "input", False),
                ("passive", "power_out", False),
                ("passive", "nc", False)):
            with self.subTest(record=record, definition=definition):
                self.assertEqual(partdata.compatible(record, definition,
                                                     exact=True), want)


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

    # The one disagreement the store and the library are known to have. The
    # library declares Ne555.ctl passive, and TI's Table 4-1 says CONT is an
    # input/output; landing L3 changes the library. Tolerated rather than
    # required, so that fix needs nothing from this test, and named, so no
    # other drift can hide behind it.
    KNOWN_ROLE_DRIFT = {("ti/ne555p", "rhoform.lib.timer.Ne555", "ctl")}

    def test_part_specific_definitions_match_their_records_role_for_role(self):
        # The lint half of the exact rule: the bundled store against the
        # bundled library, pin by pin, without going through bind().
        for path in sorted(STORE.glob("*/*.part.json")):
            doc = _doc(path)
            roles = {pin["name"]: pin["role"] for pin in doc["pins"]}
            for entry in doc["implements"]:
                if entry["definition"] not in partdata.PART_SPECIFIC:
                    continue
                for name, role, _d in _definition_pins(entry["definition"]):
                    key = (doc["part_id"], entry["definition"], name)
                    if key in self.KNOWN_ROLE_DRIFT:
                        continue
                    with self.subTest(pin=key):
                        self.assertEqual(roles[entry["pins"][name]], role)

    def test_every_store_record_binds_its_definitions_cleanly(self):
        for path in sorted(STORE.glob("*/*.part.json")):
            doc = _doc(path)
            index = {pin["name"]: i for i, pin in enumerate(doc["pins"])}
            for entry in doc["implements"]:
                known = {("role-conflict",
                          f"/pins/{index[entry['pins'][name]]}/role")
                         for part_id, definition, name in self.KNOWN_ROLE_DRIFT
                         if (part_id, definition)
                         == (doc["part_id"], entry["definition"])}
                with self.subTest(record=path.name,
                                  definition=entry["definition"]):
                    binding = self.bind(path, entry["definition"])
                    self.assertLessEqual(
                        {(p.check, p.pointer) for p in binding.problems},
                        known)

    def test_the_part_specific_names_are_bundled_definitions(self):
        for qualified in sorted(partdata.PART_SPECIFIC):
            with self.subTest(definition=qualified):
                self.assertTrue(_definition_pins(qualified))

    def test_a_part_specific_definition_may_not_narrow_a_role(self):
        # Bidirectional admits input on a generic definition. On the module,
        # which models this one part, a library edit narrowing io0 to input
        # is drift, and it would have bound silently.
        doc = _doc(ESP32)
        pins = [(n, "input" if n == "io0" else r, d)
                for n, r, d in _definition_pins(
                    "rhoform.lib.module.Esp32S3Wroom1")]
        binding = partdata.bind(doc, "rhoform.lib.module.Esp32S3Wroom1", pins)
        io0 = [p["name"] for p in doc["pins"]].index("IO0")
        self.assertEqual([(p.check, p.pointer) for p in binding.problems],
                         [("role-conflict", f"/pins/{io0}/role")])
        self.assertIn("models one part", binding.problems[0].message)
        generic = copy.deepcopy(doc)
        generic["implements"][0]["definition"] = "acme.lib.GenericModule"
        self.assertEqual(
            partdata.bind(generic, "acme.lib.GenericModule", pins).problems, ())

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

    def test_a_reference_resolves_through_the_binding_to_a_port(self):
        # AMB-151 item 13: references stay record pin names; port_of maps
        # each to the definition pin whose net evaluates it.
        for path, definition in (
                (NE555, "rhoform.lib.timer.Ne555"),
                (AP7361C, "rhoform.lib.regulator.LinearRegulator"),
                (ESP32, "rhoform.lib.module.Esp32S3Wroom1")):
            binding = self.bind(path, definition)
            seen = set()
            for facts in binding.ports.values():
                for block in (facts.abs_max, facts.recommended,
                              facts.capability, facts.characteristics,
                              facts.output):
                    for measures in block.values():
                        for measure in measures:
                            for value in measure.values:
                                if isinstance(value.bound, partdata.Relative):
                                    seen.add(value.bound.reference)
            with self.subTest(record=path.name):
                self.assertTrue(seen)
                for reference in sorted(seen):
                    self.assertIsNotNone(binding.port_of(reference))
        esp = self.bind(ESP32, "rhoform.lib.module.Esp32S3Wroom1")
        self.assertEqual((esp.port_of("3V3"), esp.port_of("TXD0"),
                          esp.port_of("NOPE")), ("p3v3", "io43", None))
        ne = self.bind(NE555, "rhoform.lib.timer.Ne555")
        self.assertEqual(ne.ports["rst"].abs_max["voltage"][0].get("max")
                         .bound.reference, "VCC")
        self.assertEqual(ne.port_of("VCC"), "vcc")

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

    def test_ne555_supply_current_is_stated_per_output_state_per_column(self):
        # SLFS022K page 6 publishes both output states at both columns; the
        # record carried output low only.
        binding = partdata.bind(_doc(NE555), "rhoform.lib.timer.Ne555",
                                [("vcc", "power_in", ())])
        got = {(cond["output_state"], cond["vcc"]["typ"]):
               (draw["vcc"].get("typ").bound, draw["vcc"].get("max").bound,
                draw["vcc"].get("max").guaranteed)
               for _id, _kind, cond, draw in binding.modes}
        self.assertEqual(got, {("high", 15): (9, 13, True),
                               ("high", 5): (2, 5, True),
                               ("low", 15): (10, 15, True),
                               ("low", 5): (3, 6, True)})

    def test_the_regulators_floor_carries_its_tables_header_conditions(self):
        vout = self.ports(AP7361C, "rhoform.lib.regulator.LinearRegulator",
                          [("vout", "power_out", ())])["vout"]
        floor, = vout.capability["source_current"]
        self.assertEqual(floor.conditions, {
            "cin": {"typ": Decimal("4.7"), "unit": "uF"},
            "cout": {"typ": Decimal("4.7"), "unit": "uF"},
            "ta": {"typ": 25, "unit": "degC"},
            "ven": "VIN", "vin": "VOUT + 1 V"})

    def test_table_6_3_figures_carry_its_title_conditions(self):
        ports = self.ports(ESP32, "rhoform.lib.module.Esp32S3Wroom1",
                           [("io35", "bidirectional", ()),
                            ("io3", "bidirectional", ()),
                            ("en", "input", ())])
        for name, block in (("en", "characteristics"),
                            ("io35", "capability"),
                            ("io35", "characteristics"),
                            ("io3", "capability"),
                            ("io3", "characteristics")):
            for symbol, measures in getattr(ports[name], block).items():
                with self.subTest(pin=name, symbol=symbol):
                    stated = {(m.conditions["ta"]["typ"],
                               m.conditions["vdd"]["typ"]) for m in measures}
                    self.assertEqual(stated, {(25, Decimal("3.3"))})

    def test_io3_inherits_no_internal_pull_and_keeps_the_rest(self):
        # Section 4.4: GPIO3 "does not have any internal pull resistors".
        ports = self.ports(ESP32, "rhoform.lib.module.Esp32S3Wroom1",
                           [("io0", "bidirectional", ()),
                            ("io3", "bidirectional", ())])
        io0, io3 = ports["io0"], ports["io3"]
        pulls = {"pull_up_resistance", "pull_down_resistance"}
        self.assertLessEqual(pulls, set(io0.characteristics))
        self.assertFalse(pulls & set(io3.characteristics))

        def plain(block):
            return {name: [(m.unit, m.values, json.dumps(
                               m.conditions, sort_keys=True, default=str))
                           for m in measures]
                    for name, measures in block.items() if name not in pulls}
        self.assertEqual(plain(io3.capability), plain(io0.capability))
        self.assertEqual(plain(io3.characteristics),
                         plain(io0.characteristics))
        self.assertEqual(io3.absent, {"abs_max": "vendor-unpublished"})
        self.assertEqual(io3.strap["default"], "floating")

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

    def test_the_module_states_what_its_supply_must_deliver(self):
        # AMB-151 item 19: Table 6-2's IVDD minimum, under a key a budget
        # check reads, as a guarantee with no free-text condition.
        p3v3 = self.ports(ESP32, "rhoform.lib.module.Esp32S3Wroom1",
                          [("p3v3", "power_in", ())])["p3v3"]
        need, = p3v3.characteristics["required_supply_current"]
        self.assertEqual((need.unit, need.conditions), ("A", {}))
        self.assertEqual([(v.statistic, v.bound, v.guaranteed)
                          for v in need.values],
                         [("min", Decimal("0.5"), True)])

    def test_table_header_conditions_reach_the_figures_under_them(self):
        # AMB-151 item 23: the NE555 Section 5.5 header and the AP7361C
        # Electrical Characteristics header.
        ne = self.ports(NE555, "rhoform.lib.timer.Ne555",
                        [("thr", "input", ()), ("trig", "input", ()),
                         ("rst", "input", ())])
        for port, symbol in (("thr", "input_current"),
                             ("trig", "input_current"),
                             ("rst", "reset_voltage_level")):
            with self.subTest(part="NE555", port=port):
                measure, = ne[port].characteristics[symbol]
                self.assertEqual(measure.conditions["ta"],
                                 {"typ": 25, "unit": "degC"})
                self.assertEqual(measure.conditions["vcc"],
                                 {"max": 15, "min": 5, "unit": "V"})
        vout = self.ports(AP7361C, "rhoform.lib.regulator.LinearRegulator",
                          [("vout", "power_out", ())])["vout"]
        for symbol in ("psrr", "output_discharge_resistance",
                       "short_circuit_current", "start_up_time"):
            with self.subTest(part="AP7361C", symbol=symbol):
                measure, = vout.characteristics[symbol]
                self.assertEqual(measure.conditions["ta"],
                                 {"typ": 25, "unit": "degC"})

    def test_straps(self):
        binding = partdata.bind(_doc(ESP32), "rhoform.lib.module.Esp32S3Wroom1",
                                [("io0", "bidirectional", ()),
                                 ("io3", "bidirectional", ())])
        self.assertEqual(binding.ports["io0"].strap["default"], "pull_up")
        self.assertEqual(binding.ports["io3"].strap["default"], "floating")
        self.assertEqual([s["id"] for s in binding.straps],
                         ["joint_download_boot", "spi_boot"])


# Runs in a child before anything is called: every path opened or listed,
# every network attempt and every process started is recorded, and the
# interpreter's own install locations are reported so they can be set aside
# (imports read and list them). Listing is recorded because it is how a
# reader would SEARCH the store, which has no index precisely so that
# nothing does; an open-only hook let a load() that listed rhoform/parts
# pass unchanged.
_AUDIT = r'''
import json, os, site, sys, sysconfig
sys.path.insert(0, sys.argv[1])
from rhoform import partdata
import jsonschema
_python = sorted(set(sysconfig.get_paths().values())
                 | set(site.getsitepackages())
                 | {site.getusersitepackages(), sys.prefix, sys.base_prefix,
                    sys.exec_prefix, sys.base_exec_prefix})
_LIST = ("os.listdir", "os.scandir", "os.walk", "os.fwalk", "glob.glob",
         "glob.glob/2", "pathlib.Path.glob", "pathlib.Path.rglob",
         "pathlib.Path.walk")
_SPAWN = ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn",
          "os.spawn", "os.fork", "os.forkpty", "os.startfile", "pty.spawn")
events = []
def _path(arg):
    if isinstance(arg, (str, bytes, os.PathLike)):
        return os.fsdecode(os.fspath(arg))
    # os.scandir() with no argument lists the working directory, and an
    # integer is a directory descriptor: both are listings all the same.
    return os.getcwd() if arg is None else repr(arg)
def _hook(event, args):
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        events.append(["open", os.fsdecode(os.fspath(args[0]))])
    elif event in _LIST:
        events.append(["list", _path(args[0] if args else None)])
    elif event in _SPAWN:
        events.append(["spawn", event])
    elif event.split(".")[0] in ("socket", "http", "urllib", "ftplib",
                                 "smtplib", "ssl"):
        events.append(["network", event])
sys.addaudithook(_hook)
record, legacy = sys.argv[2], sys.argv[3]
marks = {}
marks["v1_first"] = len(events); partdata.load(record)
marks["v1_second"] = len(events); doc = partdata.load(record).document
marks["v0_first"] = len(events); partdata.load(legacy)
marks["v0_second"] = len(events); old = partdata.load(legacy).document
marks["pure"] = len(events)
data = open(record, "rb").read()
marks["after_read"] = len(events)
partdata.parse(data); partdata.layout_problems(data); partdata.revision(data)
partdata.lint_problems(doc, []); partdata.validate(doc); partdata.validate(old)
partdata.store_path(doc["part_id"])
partdata.bind(doc, "rhoform.lib.timer.Ne555", [("vcc", "power_in", ("8",))])
marks["end"] = len(events)
print(json.dumps({"events": events, "marks": marks, "python": _python}))
'''


class ImportOrderTest(unittest.TestCase):
    """partdata reads units with rhoform.check.values, which imports
    partdata's Relative: either may be imported first."""

    def test_either_module_may_be_imported_first(self):
        for first in ("rhoform.partdata", "rhoform.check.values",
                      "rhoform.check"):
            with self.subTest(first=first):
                done = subprocess.run(
                    [sys.executable, "-c",
                     f"import sys; sys.path.insert(0, sys.argv[1]); "
                     f"import {first}; from rhoform import partdata; "
                     "print(partdata._values.parse_part_unit('mV').kind)",
                     str(ROOT)],
                    capture_output=True, text=True, timeout=120)
                self.assertEqual((done.returncode, done.stdout.strip()),
                                 (0, "linear"), done.stderr)


@unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema required")
class HermeticTest(unittest.TestCase):
    """partdata opens the path it is given and, once per process per
    schema_version, the toolchain's own schema file for that version
    (parts/part-data[.vN].schema.json); it lists nothing, starts no process,
    and opens no network connection."""

    def test_the_module_states_this_rule_word_for_word(self):
        def words(text):
            return " ".join(text.split())
        self.assertIn("HERMETIC. " + words(HermeticTest.__doc__),
                      words(partdata.__doc__))

    def test_load_opens_its_path_and_its_versions_schema_once_only(self):
        # A version 0 record too, so "once per schema_version" is held for
        # each version and not only for the first one validated.
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "v0.part.json"
            legacy.write_bytes(partdata.canonical_layout(
                (EXAMPLES / "ti-sn74hc00d.part.json").read_bytes()))
            done = subprocess.run(
                [sys.executable, "-c", _AUDIT, str(ROOT), str(NE555),
                 str(legacy)],
                capture_output=True, text=True, timeout=120,
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            legacy = os.path.realpath(legacy)
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        real = os.path.realpath
        python = [real(p) for p in report["python"]]

        def ours(events):
            # An open is shown as its path and a listing as `list:` and its
            # path, both unless the interpreter's own files are the subject.
            return [(real(path) if kind == "open"
                     else kind + ":" + (real(path) if kind == "list"
                                        else path))
                    for kind, path in events
                    if kind not in ("open", "list") or not any(
                        real(path) == p or real(path).startswith(p + os.sep)
                        for p in python)]

        events, marks = report["events"], report["marks"]
        v1_schema = real(ROOT / "parts" / "part-data.v1.schema.json")
        v0_schema = real(ROOT / "parts" / "part-data.schema.json")
        record = real(NE555)
        self.assertFalse([e for e in events if e[0] in ("network", "spawn")])
        for start, end, want in (
                ("v1_first", "v1_second", [record, v1_schema]),
                ("v1_second", "v0_first", [record]),
                ("v0_first", "v0_second", [legacy, v0_schema]),
                ("v0_second", "pure", [legacy]),
                ("after_read", "end", [])):
            with self.subTest(window=start):
                self.assertEqual(ours(events[marks[start]:marks[end]]), want)


if __name__ == "__main__":
    unittest.main()
