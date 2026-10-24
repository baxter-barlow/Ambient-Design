"""Lockfile v0 (rhoform.lockfile, R55 / AMB-59): the canonical bytes and
their JavaScript equivalence, the strict reader and each refusal, the
invariants, the packages section's staleness, the constraints digest, the
writer's half of the contract, and determinism across hash seeds.

spec/language/08-packages.md ("The lockfile") is the normative text. The
conformance suite pins one case per lockfile code (packages/reject
r23-r32); this file holds the module to the contracts behind them,
clause by clause. The schema tests skip without jsonschema, as
test_ir.py's do; the compile tests skip without lark too.
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
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

from rhoform import lockfile

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "rhoform" / "examples"
CONFORMANCE = ROOT / "spec" / "conformance"
SKIP = "jsonschema (pinned in toolchain/versions.yaml) is required"
H = "sha256:" + "ab" * 32


def committed() -> list[Path]:
    """Every canonical lockfile the repository commits: the examples and
    each rhoform.lock an accept case holds."""
    found = sorted(EXAMPLES.glob("*.lock.json"))
    found += sorted(CONFORMANCE.glob("packages/accept/*/rhoform.lock"))
    found += sorted(CONFORMANCE.glob("check/*/accept/*/rhoform.lock"))
    return found


def parsed(data: bytes):
    """(Lockfile or None, the diagnostics as dicts)."""
    from rhoform.diagnostics import Diagnostics

    sink = Diagnostics()
    lock = lockfile.parse(data, sink)
    return lock, [json.loads(line) for line in sink.render().splitlines()]


def spanned(data: bytes, diagnostic: dict) -> bytes:
    span = diagnostic["spans"][0]
    return data[span["byte_start"]:span["byte_end"]]


def _at(document, pointer):
    node = document
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        node = node[int(token)] if isinstance(node, list) else node[token]
    return node


def full() -> dict:
    """A lockfile using every section and both kinds of pick."""
    return json.loads((EXAMPLES / "l01_packages_and_parts.lock.json")
                      .read_bytes())


# The canonical layout, as a JavaScript engine writes it: ECMA-262's
# JSON.stringify(value, null, 2) transcribed (SerializeJSONProperty,
# SerializeJSONObject/Array with gap "  ", QuoteJSONString), so the claim
# is checked without a JavaScript engine too.
_JS_ESCAPES = {0x08: "\\b", 0x09: "\\t", 0x0A: "\\n", 0x0C: "\\f",
               0x0D: "\\r", 0x22: '\\"', 0x5C: "\\\\"}


def _js_quote(text: str) -> str:
    out = []
    for unit in text.encode("utf-16-le").decode("utf-16-le"):
        code = ord(unit)
        if code in _JS_ESCAPES:
            out.append(_JS_ESCAPES[code])
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            out.append(unit)
    return '"' + "".join(out) + '"'


def _js_stringify(value, indent="") -> str:
    step = indent + "  "
    if value is None:
        return "null"
    if value is True or value is False:
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _js_quote(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[\n" + ",\n".join(step + _js_stringify(item, step)
                                  for item in value) + "\n" + indent + "]"
    if not value:
        return "{}"
    # The "sorted" object: keys in UTF-16 code-unit order, as Array.sort.
    keys = sorted(value, key=lambda key: key.encode("utf-16-be"))
    return "{\n" + ",\n".join(
        step + _js_quote(key) + ": " + _js_stringify(value[key], step)
        for key in keys) + "\n" + indent + "}"


# A document exercising every escape the layout writes, empty containers,
# nesting, and characters JSON leaves raw (U+2028, an astral one, DEL).
TRICKY = {"a": [1, -2, 0, {"b": "é \x7f\U0001f600"}, [], {}],
          "c": "\"\\\b\f\n\r\t\x00\x1f/", "d": None, "e": True,
          "f": False, "z": {"y": [[]]}}

_NODE = r'''
const fs = require("fs");
const sort = v => Array.isArray(v) ? v.map(sort)
  : (v && typeof v === "object")
    ? Object.fromEntries(Object.keys(v).sort().map(k => [k, sort(v[k])]))
    : v;
for (const path of process.argv.slice(1)) {
  const text = JSON.stringify(sort(JSON.parse(fs.readFileSync(path, "utf8"))),
                              null, 2) + "\n";
  process.stdout.write(Buffer.from(text, "utf8").toString("hex") + "\n");
}
'''


class CanonicalTest(unittest.TestCase):
    def test_the_layout_is_json_dumps_sorted_with_indent_two(self):
        for document in [TRICKY, {"lockfile_version": 0}, full()] + [
                json.loads(path.read_bytes()) for path in committed()]:
            with self.subTest(document=str(document)[:60]):
                self.assertEqual(lockfile.canonical_bytes(document), (
                    json.dumps(document, ensure_ascii=False, sort_keys=True,
                               indent=2) + "\n").encode("utf-8"))

    def test_every_committed_lockfile_round_trips(self):
        paths = committed()
        self.assertGreaterEqual(len(paths), 9)
        for path in paths:
            with self.subTest(lockfile=path.relative_to(ROOT).as_posix()):
                data = path.read_bytes()
                self.assertEqual(
                    lockfile.canonical_bytes(json.loads(data)), data)

    def test_javascript_writes_the_same_bytes_by_its_own_algorithm(self):
        for document in [TRICKY, full()] + [
                json.loads(path.read_bytes()) for path in committed()]:
            with self.subTest(document=str(document)[:60]):
                self.assertEqual(
                    (_js_stringify(document) + "\n").encode("utf-8"),
                    lockfile.canonical_bytes(document))

    def test_a_javascript_engine_writes_the_same_bytes(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("no JavaScript engine (node) on PATH; the "
                          "transcribed algorithm above still runs")
        with tempfile.TemporaryDirectory() as tmp:
            tricky = Path(tmp) / "tricky.json"
            tricky.write_bytes(lockfile.canonical_bytes(TRICKY))
            paths = [tricky] + committed()
            done = subprocess.run([node, "-e", _NODE, *map(str, paths)],
                                  capture_output=True, text=True,
                                  timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        written = [bytes.fromhex(line) for line in done.stdout.split()]
        self.assertEqual(written, [lockfile.canonical_bytes(TRICKY)] + [
            path.read_bytes() for path in committed()])

    def test_spans_cover_each_value_exactly(self):
        data = lockfile.canonical_bytes(full())
        layout = lockfile._Layout(full())
        for pointer, (start, end) in layout.values.items():
            self.assertEqual(json.loads(data[start:end]),
                             _at(full(), pointer), pointer)
        for pointer, (start, end) in layout.keys.items():
            self.assertEqual(json.loads(data[start:end]),
                             pointer.rsplit("/", 1)[1])


@unittest.skipUnless(HAVE_JSONSCHEMA, SKIP)
class ParseTest(unittest.TestCase):
    def only(self, data: bytes, code: str) -> dict:
        lock, found = parsed(data)
        self.assertIsNone(lock)
        self.assertEqual([d["code"] for d in found], [code],
                         json.dumps(found, indent=1))
        self.assertEqual(found[0]["spans"][0]["file"], "rhoform.lock")
        return found[0]

    def test_committed_lockfiles_parse_and_l03_is_refused(self):
        for path in committed():
            if path.name.startswith("l03_"):
                continue
            with self.subTest(lockfile=path.name):
                lock, found = parsed(path.read_bytes())
                self.assertEqual(found, [])
                self.assertIsNotNone(lock)
        found = self.only((EXAMPLES / "l03_rename_ledger_shape.lock.json")
                          .read_bytes(), "RHO2075")
        self.assertEqual(found["params"]["pointer"], "/renames/entries/0")

    def test_rho2070_each_way_bytes_are_not_a_lockfiles_json(self):
        cases = {
            b'{\n  "lockfile_version": 0,\n}\n': (b"", "an object key"),
            b'{"a": 1, "a": 2}': (b'"a"', 'the key "a" appears twice'),
            b'{"a": {"b": 1, "b": 1}}': (b'"b"', "appears twice"),
            b'{"a": NaN}': (b"NaN", "`NaN` is not a JSON number"),
            b'{"a": -Infinity, "b": "NaN"}': (b"-Infinity", "-Infinity"),
            b'{"a": "\\ud800"}': (b"\\ud800", "lone surrogate"),
            b'{"a": "\\udc00\\ud800"}': (b"\\udc00", "lone surrogate"),
            b'\xff{}': (b"", "not UTF-8"),
            b"[" * 40 + b"]" * 40: (b"", "nests more than 32"),
            b'{"a": "x': (b"", "not closed"),
            b'{"a": "\\x"}': (b"\\x", "escape that JSON does not have"),
            b'{"a": "\\u12"}': (b"\\u", "four hex digits"),
            b'{"a": "\t"}': (b"", "control character"),
            b'{"a": 01}': (b"", "`,` or `}`"),
            b'{"a": [1 2]}': (b"", "`,` or `]`"),
            b'{"a" 1}': (b"", "`:` is expected"),
            b'{} {}': (b"", "more after the document"),
            b'': (b"", "a value is missing"),
            b'{"a": tru}': (b"", "a value is expected"),
        }
        for data, (covered, words) in cases.items():
            with self.subTest(data=data[:24]):
                found = self.only(data, "RHO2070")
                self.assertEqual(spanned(data, found), covered)
                self.assertIn(words, found["params"]["reason"])

    def test_the_reader_reads_what_strict_json_reads(self):
        # Independent of the interpreter's decoder, which words and places
        # its errors differently from one Python to the next, and equal to
        # it on everything it accepts.
        from rhoform.lockfile import _decode

        documents = [path.read_bytes() for path in committed()] + [
            lockfile.canonical_bytes(TRICKY),
            b'{"a": [1.5, -0, 2e3, 12345678901234567890, "\\ud83d\\ude00",'
            b' "\\u00e9\\/\\b\\f\\n\\r\\t\\"\\\\"], "b": {}}']
        for data in documents:
            with self.subTest(data=data[:24]):
                self.assertEqual(lockfile._plain(_decode(data)),
                                 json.loads(data, parse_float=Decimal))

    def test_rho2071_is_alone_and_its_fixit_rewrites_to_canonical(self):
        document = full()
        good = lockfile.canonical_bytes(document)
        for bad in (json.dumps(document).encode(),
                    json.dumps(document, indent=4).encode() + b"\n",
                    good + b"\n", good[:-1], good.replace(b"  ", b"\t", 1),
                    good.replace(b"\n", b"\r\n"),
                    b"\xef\xbb\xbf" + good):
            with self.subTest(bad=bad[:20]):
                lock, found = parsed(bad)
                self.assertIsNone(lock)
                if bad.startswith(b"\xef\xbb\xbf"):
                    # A byte-order mark is no JSON value at all.
                    self.assertEqual([d["code"] for d in found], ["RHO2070"])
                    continue
                self.assertEqual([d["code"] for d in found], ["RHO2071"])
                fixit = found[0]["fixits"][0]
                self.assertEqual(fixit["applicability"],
                                 "machine-applicable")
                edit = fixit["edits"][0]
                self.assertEqual((edit["byte_start"], edit["byte_end"]),
                                 (0, len(bad)))
                self.assertEqual(edit["replacement"].encode(), good)
                self.assertEqual(parsed(good)[1], [])
        # The span is the line holding the first byte that differs.
        bad = good.replace(b'"lockfile_version": 0',
                           b'"lockfile_version" : 0')
        found = self.only(bad, "RHO2071")
        self.assertEqual(spanned(bad, found), b'  "lockfile_version" : 0,')
        self.assertEqual(found["params"]["line"], 2)

    def test_rho2072_a_version_this_toolchain_does_not_read(self):
        for version, shown in ((1, "1"), ("0", '"0"'), (True, "true"),
                               (None, "null"), ([0], "an array")):
            data = lockfile.canonical_bytes({"lockfile_version": version})
            with self.subTest(version=version):
                found = self.only(data, "RHO2072")
                self.assertEqual(found["params"],
                                 {"version": shown, "supported": "0"})
        self.assertEqual(self.only(b'{\n  "lockfile_version": 0.0\n}\n',
                                   "RHO2072")["params"]["version"], "0.0")
        found = self.only(lockfile.canonical_bytes({}), "RHO2072")
        self.assertEqual(found["params"]["version"], "missing")
        self.assertEqual(self.only(b"[]\n", "RHO2072")["params"]["version"],
                         "missing")

    def test_rho2073_the_schema_spans_the_value_it_refuses(self):
        document = full()
        document["parts"]["entries"][0]["vendor"] = "acme"
        data = lockfile.canonical_bytes(document)
        found = self.only(data, "RHO2073")
        self.assertEqual(found["params"]["pointer"],
                         "/parts/entries/0/vendor")
        self.assertEqual(spanned(data, found), b'"acme"')
        document = full()
        document["parts"]["inputs"][0]["sha256"] = "md5:0"
        data = lockfile.canonical_bytes(document)
        self.assertEqual(spanned(data, self.only(data, "RHO2073")),
                         b'"md5:0"')

    def invariant(self, change, pointer, words):
        """The planted defect is reported at `pointer`; a reference it also
        breaks (an entry naming the input moved) may be reported too."""
        document = full()
        change(document)
        data = lockfile.canonical_bytes(document)
        self.assertEqual(lockfile.schema_problems(document), [])
        lock, found = parsed(data)
        self.assertIsNone(lock)
        self.assertEqual({d["code"] for d in found}, {"RHO2073"})
        reasons = {d["params"]["pointer"]: d["params"]["reason"]
                   for d in found}
        self.assertIn(pointer, reasons)
        self.assertIn(words, reasons[pointer])
        at = next(d for d in found if d["params"]["pointer"] == pointer)
        self.assertEqual(json.loads(spanned(data, at)), _at(document,
                                                            pointer))

    def test_rho2073_each_invariant_the_schema_cannot_state(self):
        def swap(items):
            items[0], items[1] = items[1], items[0]

        cases = [
            (lambda d: swap(d["packages"]["inputs"]),
             "/packages/inputs/1/path", "out of order"),
            (lambda d: d["packages"]["inputs"].__setitem__(
                1, dict(d["packages"]["inputs"][0])),
             "/packages/inputs/1/path", "repeats"),
            (lambda d: swap(d["packages"]["entries"]),
             "/packages/entries/1/name", "sorted by name"),
            (lambda d: swap(d["parts"]["entries"]),
             "/parts/entries/1", "keyed picks come first"),
            (lambda d: d["parts"]["entries"][0].update(
                record="parts/acme/other.part.json"),
             "/parts/entries/0/record", "not among the section's inputs"),
            (lambda d: d["packages"]["entries"][0].update(
                manifest="parts/rhoform.toml"),
             "/packages/entries/0/manifest", "not the manifest of"),
            (lambda d: d["packages"]["entries"][0].update(
                requires_rhoform="^0.2.0-rc.1"),
             "/packages/entries/0/requires_rhoform", "pre-release"),
            (lambda d: d["packages"]["entries"][0].update(
                name="acme/" + "x" * 64),
             "/packages/entries/0/name", "longer than 63 bytes"),
            (lambda d: d["parts"]["inputs"][0].update(
                path="parts/acme/widget.json"),
             "/parts/inputs/0/path", "is not a part record"),
            (lambda d: d["parts"]["inputs"][1].update(
                path="rhoform/lib/ne555p.part.json"),
             "/parts/inputs/1/path", "outside its part store"),
            (lambda d: d["packages"]["inputs"][0].update(
                path="app/package.toml"),
             "/packages/inputs/0/path", "is not a manifest"),
            (lambda d: d["packages"]["inputs"][1].update(
                path="rhoform/rhoform.toml"),
             "/packages/inputs/1/path", "bundles no package manifest"),
            (lambda d: d.update(x_note="hand-edited"),
             "/x_note", "a lockfile holds none"),
        ]
        for change, pointer, words in cases:
            with self.subTest(pointer=pointer, words=words):
                self.invariant(change, pointer, words)

    def test_rho2073_instance_picks_and_renames(self):
        def second_pick(d):
            pick = dict(d["parts"]["entries"][1])
            d["parts"]["entries"].append(pick)

        self.invariant(second_pick, "/parts/entries/2/instance", "repeats")
        renames = lambda entries: {  # noqa: E731
            "lockfile_version": 0,
            "renames": {"entries": entries, "inputs": []}}
        same = renames([{"design": "a.B", "origin": "/u", "path": "/u"}])
        found = self.only(lockfile.canonical_bytes(same), "RHO2073")
        self.assertEqual(found["params"]["pointer"],
                         "/renames/entries/0/origin")
        twice = renames([{"design": "a.B", "origin": "/o", "path": "/u1"},
                         {"design": "a.B", "origin": "/o", "path": "/u2"}])
        found = self.only(lockfile.canonical_bytes(twice), "RHO2073")
        self.assertIn("one identity has one current path",
                      found["params"]["reason"])

    def test_rho2075_what_version_0_refuses_rather_than_ignores(self):
        document = full()
        document["packages"]["entries"][0]["content_hash"] = H
        del document["packages"]["entries"][0]["unavailable_reason"]
        found = self.only(lockfile.canonical_bytes(document), "RHO2075")
        self.assertEqual(found["params"]["pointer"],
                         "/packages/entries/0/content_hash")
        self.assertIn("G8-G10", found["params"]["owner"])

    def test_an_entry_unsupported_waits_for_a_valid_file(self):
        document = json.loads((EXAMPLES / "l03_rename_ledger_shape.lock.json")
                              .read_bytes())
        document["renames"]["entries"][0]["extra"] = 1
        found = self.only(lockfile.canonical_bytes(document), "RHO2073")
        self.assertEqual(found["params"]["pointer"],
                         "/renames/entries/0/extra")


@unittest.skipUnless(HAVE_JSONSCHEMA, SKIP)
class PickTest(unittest.TestCase):
    def test_picks_unlocked_and_their_reasons(self):
        lock, _found = parsed(lockfile.canonical_bytes(full()))
        keyed = lock.pick_key("acme/widget")
        self.assertEqual((keyed.part_id, keyed.record, keyed.revision,
                          keyed.pointer),
                         ("acme/widget", "parts/acme/widget.part.json",
                          "sha256:" + "ef" * 32, "/parts/entries/0"))
        self.assertEqual(lock.pick_key("acme/other"),
                         lockfile.Unlocked("no-pick"))
        picked = lock.pick_instance("acme.app.main.Panel", "/timer")
        self.assertEqual((picked.constraints, picked.revision),
                         (H, "sha256:" + "cd" * 32))
        self.assertEqual(lock.instance_picks("acme.app.main.Panel"),
                         (picked,))
        self.assertEqual(lock.instance_picks("other.Design"), ())
        self.assertEqual(lockfile.pick_key(None, "x"),
                         lockfile.Unlocked("no-lockfile"))
        self.assertEqual(lockfile.pick_instance(None, "a.B", "/x"),
                         lockfile.Unlocked("no-lockfile"))
        bare, _found = parsed(lockfile.canonical_bytes(
            {"lockfile_version": 0}))
        self.assertEqual(bare.pick_key("x"),
                         lockfile.Unlocked("no-parts-section"))
        self.assertEqual(bare.pick_instance("a.B", "/x"),
                         lockfile.Unlocked("no-parts-section"))
        self.assertEqual(sorted({u for u in lockfile.UNLOCKED}),
                         sorted(lockfile.UNLOCKED))


class DigestTest(unittest.TestCase):
    def quantity(self, value, unit, low=None, high=None):
        from rhoform.elaborate import Quantity

        tolerance = None if low is None else (Decimal(low), Decimal(high))
        return Quantity(Decimal(value), unit, tolerance)

    def test_the_digest_is_over_exact_values_whatever_their_spelling(self):
        digest = lockfile.constraints_digest
        a = digest({"capacitance": self.quantity("1.50", "uF", "1.4", "1.6")})
        b = digest({"capacitance": self.quantity("1.5", "uF", "1.40",
                                                 "1.600")})
        self.assertEqual(a, b)
        self.assertEqual(digest({"x": self.quantity("-0.0", "V")}),
                         digest({"x": self.quantity("0", "V")}))
        self.assertEqual(digest({"x": self.quantity("1E+3", "ohm")}),
                         digest({"x": self.quantity("1000", "ohm")}))
        self.assertRegex(a, r"^sha256:[0-9a-f]{64}$")

    def test_values_doubles_cannot_tell_apart_have_two_digests(self):
        # As IR doubles these are one number; the digest never reads one.
        digest = lockfile.constraints_digest
        self.assertEqual(float("0.1000000000000000000001"), float("0.1"))
        self.assertNotEqual(
            digest({"r": self.quantity("0.1000000000000000000001", "ohm")}),
            digest({"r": self.quantity("0.1", "ohm")}))

    def test_every_value_kind_is_its_own(self):
        digest = lockfile.constraints_digest
        kinds = [{"k": "1"}, {"k": 1}, {"k": True}, {"k": "true"},
                 {"k": self.quantity("1", "V")},
                 {"k": self.quantity("1", "V", "1", "1")}, {}]
        digests = [digest(item) for item in kinds]
        self.assertEqual(len(set(digests)), len(digests))

    def test_the_encoding_is_the_one_spec_08_states(self):
        from rhoform import ir

        constraints = {"mpn": "R-10K", "count": 2, "fitted": False,
                       "resistance": self.quantity("10000", "ohm", "9900",
                                                   "10100.0")}
        self.assertEqual(lockfile.constraints_digest(constraints),
                         lockfile.digest(ir.canonical_bytes({
                             "count": {"integer": "2"}, "fitted": False,
                             "mpn": "R-10K",
                             "resistance": {"max": "10100", "min": "9900",
                                            "unit": "ohm",
                                            "value": "10000"}})))


@unittest.skipUnless(HAVE_JSONSCHEMA, SKIP)
class WriterTest(unittest.TestCase):
    def test_a_writer_replaces_its_own_section_and_nothing_else(self):
        before = lockfile.canonical_bytes(full())
        parts = {"entries": [], "inputs": []}
        after = lockfile.replace_section(before, "parts", parts)
        document = json.loads(after)
        self.assertEqual(document["parts"], parts)
        self.assertEqual(document["packages"], full()["packages"])
        self.assertEqual(lockfile.canonical_bytes(document), after)
        self.assertEqual(parsed(after)[1], [])
        self.assertNotIn("parts", json.loads(
            lockfile.replace_section(after, "parts", None)))
        created = lockfile.replace_section(None, "parts", parts)
        self.assertEqual(json.loads(created),
                         {"lockfile_version": 0, "parts": parts})

    def test_a_writer_refuses_what_it_cannot_round_trip(self):
        with self.assertRaises(ValueError):
            lockfile.replace_section(b'{"lockfile_version": 0}', "parts",
                                     None)
        with self.assertRaises(ValueError):
            lockfile.replace_section(lockfile.canonical_bytes(
                {"lockfile_version": 1}), "parts", None)
        with self.assertRaises(ValueError):
            lockfile.replace_section(None, "picks", {})
        self.assertEqual(lockfile.input_entry("a.part.json", b"x"), {
            "path": "a.part.json", "sha256": "sha256:2d711642b726b04401627"
            "ca9fbac32f5c8530fb1903cc4db02258717921a4881"})


class LocateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rhoform-lock-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "root" / "parts").mkdir(parents=True)
        (self.tmp / "root" / "parts" / "r.part.json").write_text("{}")

    def test_a_record_path_resolves_exactly_or_says_why_not(self):
        root = self.tmp / "root"
        where, why = lockfile.locate(root, "parts/r.part.json")
        self.assertEqual((where, why), (root / "parts" / "r.part.json", None))
        self.assertEqual(lockfile.locate(root, "parts/x.part.json"),
                         (None, "does not exist"))
        where, why = lockfile.locate(root, "Parts/r.part.json")
        self.assertIsNone(where)
        self.assertIn("spells `Parts` as `parts`", why)
        self.assertEqual(lockfile.locate(root, "parts"),
                         (None, "is not a file"))

    def test_a_link_out_of_the_compile_root_names_nothing(self):
        root = self.tmp / "root"
        (self.tmp / "outside.part.json").write_text("{}")
        try:
            os.symlink(self.tmp / "outside.part.json",
                       root / "parts" / "l.part.json")
        except OSError:  # pragma: no cover - no symlink support
            self.skipTest("no symbolic links here")
        where, why = lockfile.locate(root, "parts/l.part.json")
        self.assertIsNone(where)
        self.assertIn("outside the compile root", why)

    def test_a_toolchain_path_is_the_bundled_store(self):
        where, why = lockfile.locate(self.tmp / "root",
                                     "rhoform/parts/ti/ne555p.part.json")
        self.assertEqual((where, why), (
            lockfile.TOOLCHAIN / "rhoform" / "parts" / "ti" /
            "ne555p.part.json", None))


@unittest.skipUnless(HAVE_LARK and HAVE_JSONSCHEMA, SKIP)
class PackagesTest(unittest.TestCase):
    """The packages section against the compilation, through the package
    layer: one case per way it can be stale."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rhoform-lock-pkg-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        case = CONFORMANCE / "packages" / "accept" / "a07_lockfile_packages"
        self.root = self.tmp / "ws"
        shutil.copytree(case, self.root)
        self.lock = json.loads((self.root / "rhoform.lock").read_bytes())

    def stale(self, change=None, manifest=None):
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics

        document = copy.deepcopy(self.lock)
        if change is not None:
            change(document)
        (self.root / "rhoform.lock").write_bytes(
            lockfile.canonical_bytes(document))
        if manifest is not None:
            path = self.root / "parts" / "rhoform.toml"
            path.write_text(manifest(path.read_text()))
        sink = Diagnostics()
        compiled = pipeline.compile("app/main.rhoform", self.root,
                                    stage="load", sink=sink)
        found = [json.loads(line) for line in sink.render().splitlines()]
        return compiled.loaded, [(d["code"], d["params"].get("subject"))
                                 for d in found], found

    def test_a_fresh_section_is_clean_and_reaches_the_compilation(self):
        loaded, codes, _found = self.stale()
        self.assertEqual(codes, [])
        self.assertTrue(loaded.ok)
        self.assertIsNotNone(loaded.lockfile)

    def test_each_way_a_section_goes_stale(self):
        entries = lambda d: d["packages"]["entries"]  # noqa: E731
        cases = [
            (lambda d: d["packages"]["inputs"].pop(0), None,
             [("RHO2073", None)]),
            (lambda d: d["packages"].update(inputs=d["packages"]["inputs"][1:],
                                            entries=entries(d)[1:]), None,
             [("RHO2074", "app/rhoform.toml"), ("RHO2074", "acme/app")]),
            (lambda d: entries(d)[1].update(version="1.2.0"), None,
             [("RHO2074", "acme/parts")]),
            (lambda d: entries(d)[1].update(source={"path": "vendor"},
                                            manifest="vendor/rhoform.toml"),
             None, [("RHO2073", None)]),
            (lambda d: entries(d)[1].update(requires_rhoform="^0.1.0"),
             None, [("RHO2074", "acme/parts")]),
            (lambda d: entries(d)[1].update(requires_rhoform="=0.2.1"),
             None, [("RHO2074", "acme/parts")]),
            (None, lambda text: text.replace("MIT OR ", ""),
             [("RHO2074", "parts/rhoform.toml")]),
        ]
        for change, manifest, want in cases:
            with self.subTest(want=want):
                loaded, codes, _found = self.stale(change, manifest)
                self.assertEqual(sorted(codes, key=str), sorted(want, key=str))
                self.assertFalse(loaded.ok)
                self.setUp()

    def test_a_moved_source_and_a_range_admitting_nothing_say_so(self):
        def moved(d):
            d["packages"]["entries"][1].update(source={"path": "app"},
                                               manifest="app/rhoform.toml")

        _loaded, _codes, found = self.stale(moved)
        self.assertIn("this compilation reads it from `parts`",
                      found[0]["params"]["problem"])
        self.setUp()
        _loaded, _codes, found = self.stale(lambda d: d["packages"][
            "entries"][1].update(requires_rhoform="=0.2.1"))
        self.assertIn("admits none of the language versions",
                      found[0]["params"]["problem"])

    def test_entries_of_other_packages_are_not_this_compilations(self):
        def other(d):
            d["packages"]["entries"].append({
                "content_hash": None, "manifest": "zz/rhoform.toml",
                "name": "acme/zz", "requires_rhoform": "^9.0.0",
                "source": {"path": "zz"},
                "unavailable_reason": "canonical-archive-unavailable",
                "version": "9.0.0"})
            d["packages"]["inputs"].append({"path": "zz/rhoform.toml",
                                            "sha256": H})

        _loaded, codes, _found = self.stale(other)
        self.assertEqual(codes, [])

    def test_a_manifest_in_error_is_not_reported_again_as_stale(self):
        _loaded, codes, _found = self.stale(
            manifest=lambda text: text.replace('"1.3.0"', '"1.3"'))
        self.assertEqual([code for code, _subject in codes], ["RHO2053"])

    def test_containment_of_ranges(self):
        within = lockfile._within
        for inner, outer, holds in (
                ("^0.2.0", "^0.2.0", True), ("^0.2.3", "^0.2.0", True),
                ("^0.2.0", "^0.2.3", False), ("^0.3.0", "^0.2.0", False),
                ("=0.2.5", "^0.2.0", True), ("=0.3.0", "^0.2.0", False),
                ("^1.2.0", "^1.0.0", True), ("^2.0.0", "^1.0.0", False),
                ("^1.0.0", "=1.0.0", False), ("=1.0.0", "=1.0.0", True),
                ("^0.0.3", "^0.0.1", True)):
            with self.subTest(inner=inner, outer=outer):
                self.assertEqual(within(inner, outer), holds)


_SEED_PROBE = r'''
import hashlib, json, sys
from pathlib import Path
from rhoform import compile as pipeline, ir
from rhoform.diagnostics import Diagnostics
out = {}
for case in map(Path, sys.argv[1:]):
    sink = Diagnostics()
    entry = next(p for p in sorted(case.rglob("main.rhoform")))
    c = pipeline.compile(entry.relative_to(case).as_posix(), case, sink=sink)
    report = None if c.report is None else hashlib.sha256(ir.canonical_bytes(
        c.report.document("sha256:" + "0" * 64))).hexdigest()
    out[case.name] = [hashlib.sha256(sink.render().encode()).hexdigest(),
                      report]
print(json.dumps(out, sort_keys=True))
'''


@unittest.skipUnless(HAVE_LARK and HAVE_JSONSCHEMA, SKIP)
class DeterminismTest(unittest.TestCase):
    def test_lockfile_compilations_agree_across_hash_seeds(self):
        cases = sorted(CONFORMANCE.glob("packages/*/*lockfile*")) + sorted(
            CONFORMANCE.glob("check/parts/*/*"))
        self.assertGreater(len(cases), 20)
        runs = []
        for seed in ("0", "1", "4242"):
            done = subprocess.run(
                [sys.executable, "-c", _SEED_PROBE, *map(str, cases)],
                env=dict(os.environ, PYTHONHASHSEED=seed,
                         PYTHONPATH=str(ROOT)),
                capture_output=True, text=True, timeout=300)
            self.assertEqual(done.returncode, 0, done.stderr)
            runs.append(json.loads(done.stdout))
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(runs[0], runs[2])
        self.assertEqual(len(runs[0]), len(cases))


class SchemaFileTest(unittest.TestCase):
    @unittest.skipUnless(HAVE_JSONSCHEMA, SKIP)
    def test_missing_jsonschema_is_an_import_error_never_a_pass(self):
        with mock.patch.dict(sys.modules, {"jsonschema": None}), \
                mock.patch.object(lockfile, "_VALIDATOR", None):
            with self.assertRaises(ImportError):
                lockfile.parse(lockfile.canonical_bytes(
                    {"lockfile_version": 0}), _Sink())

    def test_the_key_table_is_the_schemas(self):
        schema = json.loads(lockfile.SCHEMA_PATH.read_text())
        defs = schema["$defs"]
        objects = {
            "the lockfile": schema,
            "a section": defs["PartsSection"],
            "an input": defs["Input"],
            "a package entry": defs["PackageEntry"],
            "a keyed pick": defs["KeyedPick"],
            "an instance pick": defs["InstancePick"],
            "a rename": defs["Rename"],
        }
        for what, keys in lockfile.KEYS:
            with self.subTest(object=what):
                body = objects[what]
                self.assertEqual(sorted(key for key, _r in keys),
                                 sorted(body["properties"]))
                self.assertEqual(sorted(key for key, required in keys
                                        if required),
                                 sorted(body.get("required", ())))
        for section in ("PackagesSection", "RenamesSection"):
            self.assertEqual(sorted(defs[section]["properties"]),
                             ["entries", "inputs"])
        self.assertEqual(tuple(schema["properties"]["lockfile_version"]
                               ["const"] for _ in (0,)), lockfile.SUPPORTED)
        self.assertEqual(defs["PackageEntry"]["properties"][
            "unavailable_reason"]["enum"],
            list(lockfile.UNAVAILABLE_REASONS))


class _Sink:
    def add(self, *args, **kwargs):  # pragma: no cover - never reached
        raise AssertionError("nothing should be reported")

    def counts(self):  # pragma: no cover - never reached
        return {"error": 0, "warning": 0, "note": 0}


if __name__ == "__main__":
    unittest.main()
