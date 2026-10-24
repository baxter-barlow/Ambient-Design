"""The living benchmark sources (R53) and the goldens committed beside them.

Each benchmarks/<id>/<id>.rhoform is compiled with its own directory as the
compile root, and must reproduce the <id>.ir.json and <id>.sourcemap.json
next to it byte for byte. A change to the elaborator, the encoder or the
source that moves either file fails here until the golden is regenerated on
purpose, so a moved design_hash is always a reviewed diff rather than a
silent one. tests/schemas/validate-schemas.py and tests/ir/check-hashes.py
check the same goldens' shape and hashes; this file checks that they are
still what the compiler makes.

The sources are the library-pins form (E-17, wave 3): a standard library
component's pins come from its definition under rhoform/lib/, so the sources
state only what the library cannot know (parts, hardware, flags). Writing
those pins back inline -- the explicit form the sources had before the
library existed -- must elaborate to the same design_hash; a test below
holds every benchmark to that.

THE CHECK STAGE'S OUTPUT ON THE BENCHMARKS IS PINNED HERE AND NOWHERE ELSE.
From the M2 foundation to the landing that empties it (L5b), each
benchmark's check stage must match the KNOWN_FINDINGS ledger: the union
of rhoform/tests/benchmark_findings/<landing>.json, one file per landing
so parallel landings never edit one file. An entry is one of two kinds,
each saying why it is there and which landing resolves it:

  - a FINDING: the benchmark, the code and the entity of one diagnostic.
    The stream's findings must be exactly these (code, entity) pairs;
    their params and spans are not pinned here.
  - an ACTIONABLE ROW count: the benchmark, a check-report section, a
    row class (the row's reason) and how many such rows that section
    holds. It lives in the file of the landing that implements that
    section's pass (SECTION_LEDGERS). The report's actionable rows must
    be exactly these counts, and the stream's coverage note (RHO3901)
    must count exactly them, so its actionable total, classes and
    sections are pinned too: a coverage gap opened or closed on a
    benchmark fails here as a finding does.

A finding or a row the ledger does not list fails, and so does an entry
nothing matches, so neither a new false positive, nor a new coverage
gap, nor a resolved one can sit unnoticed. Inherent rows are not
pinned here (amendment OD1: the committed check-report goldens hold
them, from L5b). Every benchmark compiles from a copy in a compile root
of its own, as it does in place.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import lark  # noqa: F401 - availability probe only
    HAVE_LARK = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_LARK = False

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / "benchmarks"
FINDINGS = Path(__file__).resolve().parent / "benchmark_findings"
FINDING_KEYS = ("benchmark", "code", "entity", "reason", "resolving_landing")
ROW_KEYS = ("benchmark", "class", "count", "reason", "resolving_landing",
            "section")

# The ledger file a check section's actionable rows are counted in: the
# landing that implements that section's pass, whose file it alone edits.
SECTION_LEDGERS = {
    "model": "L0",
    "parts": "L2b",
    "dimensions": "L1c",
    "ground": "L2c",
    "erc": "L1b",
    "domains": "L3",
    "budget": "L4",
    "domains_refine": "L4",
    "assertions": "L5a",
}

# The benchmarks that must have a living source. Discovery below finds
# whatever is on disk; this list makes a deleted source a failure rather
# than one fewer thing checked.
REQUIRED = ("blinker-555", "buck-3v3", "esp32s3-devboard")

REGENERATE = ("python3 -c 'from rhoform.tests.test_benchmarks import "
              "regenerate; regenerate()'")


def sources():
    """Every benchmarks/<id>/<id>.rhoform, sorted."""
    return sorted(path for path in BENCHMARKS.glob("*/*.rhoform")
                  if path.name == path.parent.name + ".rhoform")


def build(source: Path, stage: str = "elaborate"):
    """(stream, Compilation) for one source through rhoform.compile, its
    directory the compile root. The package layer reads the bytes, so the
    hashed bytes are the file's, with no newline translation between."""
    from rhoform import compile as pipeline
    from rhoform.diagnostics import Diagnostics

    sink = Diagnostics()
    compilation = pipeline.compile(source.name, source.parent, stage=stage,
                                   sink=sink)
    return sink.render(), compilation


def isolated_copy(source: Path, directory: Path) -> Path:
    """The benchmark copied into a compile root of its own under
    `directory` (its rhoform.lock with it, once it has one): the entry."""
    root = directory / source.parent.name
    root.mkdir(parents=True)
    shutil.copy(source, root / source.name)
    if (source.parent / "rhoform.lock").is_file():
        shutil.copy(source.parent / "rhoform.lock", root)
    return root / source.name


def known_findings() -> dict:
    """{landing: [entries]} from every ledger file, in file-name order."""
    return {path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(FINDINGS.glob("*.json"))}


def ledger_rows(benchmark: str) -> dict:
    """{(section, class): count} of one benchmark's actionable rows, from
    every ledger file."""
    return {(entry["section"], entry["class"]): entry["count"]
            for entries in known_findings().values() for entry in entries
            if "section" in entry and entry["benchmark"] == benchmark}


def goldens(source: Path) -> tuple[Path, Path]:
    stem = source.name[:-len(".rhoform")]
    return (source.with_name(stem + ".ir.json"),
            source.with_name(stem + ".sourcemap.json"))


def emit_argv(source: Path, out: Path) -> list[str]:
    """The `rhoform check --emit-ir` command line that writes one
    benchmark's IR and source map into `out`, with the benchmark's own
    directory as the compile root (E-17). regenerate() runs it into the
    benchmark directory; test_cli.py runs it into a temporary one and
    compares, so the goldens and the command line cannot drift apart."""
    return ["check", "--compile-root", str(source.parent),
            "--emit-ir", str(out), str(source)]


def regenerate() -> None:
    """Rewrite every committed golden from its source, through the CLI.
    Run it from the repository root, then review the diff: it is the change
    the compiler made to each design's IR."""
    from rhoform import cli

    for source in sources():
        stream, compilation = build(source)
        if compilation.design is None:
            raise SystemExit(f"{source.relative_to(ROOT)} does not "
                             f"elaborate; its diagnostics:\n{stream}")
        # Exit 1 may be the check stage's: the IR of a design that
        # elaborates is written whatever the checks find.
        status = cli.main(emit_argv(source, source.parent))
        if status == 2:
            raise SystemExit(f"{source.relative_to(ROOT)} could not be "
                             "compiled (exit 2); the reason is above")
        ir_path, map_path = goldens(source)
        print(f"wrote {ir_path.relative_to(ROOT)} and "
              f"{map_path.relative_to(ROOT)}")


@unittest.skipUnless(HAVE_LARK, "lark (pinned in toolchain/versions.yaml) "
                     "is required")
class BenchmarkGoldenTest(unittest.TestCase):
    def test_every_required_benchmark_has_a_living_source(self):
        found = {source.parent.name for source in sources()}
        self.assertEqual(sorted(set(REQUIRED) - found), [])

    def test_no_golden_outlives_its_source(self):
        stems = {source.parent.name for source in sources()}
        for kind in ("ir.json", "sourcemap.json"):
            for path in sorted(BENCHMARKS.glob(f"*/*.{kind}")):
                if path.name == f"{path.parent.name}.{kind}":
                    with self.subTest(golden=path.name):
                        self.assertIn(path.parent.name, stems)

    def test_sources_parse_and_elaborate_with_no_diagnostics(self):
        for source in sources():
            with self.subTest(benchmark=source.parent.name):
                stream, compilation = build(source)
                self.assertEqual(stream, "")
                self.assertIsNotNone(compilation.design)

    def test_elaborating_each_source_reproduces_its_goldens(self):
        from rhoform import ir

        for source in sources():
            with self.subTest(benchmark=source.parent.name):
                stream, compilation = build(source)
                self.assertIsNotNone(compilation.design, stream)
                emitted = ir.emit(compilation.design)
                for golden, produced in zip(goldens(source), emitted):
                    self.assertTrue(
                        golden.is_file(),
                        f"{golden.relative_to(ROOT)} is missing; create it "
                        f"from the repository root with: {REGENERATE}")
                    committed = golden.read_bytes()
                    # Not assertEqual: a byte diff of a one-line canonical
                    # document is unreadable. The offset is enough to look.
                    first = next((i for i, (a, b) in
                                  enumerate(zip(committed, produced))
                                  if a != b),
                                 min(len(committed), len(produced)))
                    self.assertTrue(
                        committed == produced,
                        f"{golden.relative_to(ROOT)} is not what "
                        f"{source.relative_to(ROOT)} elaborates to (first "
                        f"difference at byte {first}). If the change is "
                        "intended, regenerate from the repository root "
                        f"with: {REGENERATE}")

    def test_the_compile_root_is_the_benchmark_directory(self):
        # The source is named relative to its own directory; the library
        # modules it uses are listed as rhoform/lib/<module>.rhoform (E-8),
        # each one the toolchain's own file, byte for byte.
        import hashlib

        from rhoform import elaborate as elaborator
        from rhoform import ir

        for source in sources():
            with self.subTest(benchmark=source.parent.name):
                _stream, compilation = build(source)
                document = ir.to_ir(compilation.design)
                source_map = ir.to_source_map(
                    compilation.design, document["header"]["design_hash"])
                modules = elaborator.library_modules(
                    compilation.loaded.results)
                self.assertTrue(modules)
                self.assertEqual(
                    [entry["path"] for entry in source_map["files"]],
                    [source.name] + [f"rhoform/lib/{module}.rhoform"
                                     for module in modules])
                for entry in source_map["files"][1:]:
                    self.assertEqual(entry["sha256"], hashlib.sha256(
                        (ROOT / entry["path"]).read_bytes()).hexdigest())
                stem = source.parent.name.replace("-", "_")
                root = next(i for i in document["instances"]
                            if i["path"] == "/")
                self.assertEqual(root["definition"].split(".")[0], stem)


def explicit_form(source: Path) -> str:
    """The source with every standard library instance's pins written back
    inline, copied from its definition: what the benchmark sources were
    before the library existed (E-17)."""
    from rhoform import elaborate as E
    from rhoform.parser import parse

    data = source.read_bytes()
    text = data.decode("utf-8")
    result = parse(text, file=source.name)
    pins = {}
    for module in E.library_modules([result]):
        library = E.BUNDLED.load(module)
        for node in library.tree.children:
            if E._is_tree(node) and node.data == "component_def":
                pins[f"rhoform.lib.{module}.{node.children[1]}"] = [
                    library.data[library.span_of(pin).byte_start:
                                 library.span_of(pin).byte_end].decode()
                    for pin in E._trees(node, "pin_decl")]
    lines = text.split("\n")
    inserts = {}
    work = [result.tree]
    while work:
        node = work.pop()
        if not E._is_tree(node):
            continue
        work.extend(node.children)
        if node.data != "instance_decl":
            continue
        name = ".".join(E._words(E._tree(node, "qualified_name")))
        if name not in pins:
            continue
        body = E._tree(node, "instance_body")
        assert body is None or not E._trees(body, "pin_decl"), name
        start = result.span_of(node).byte_start
        line = data.count(b"\n", 0, start)
        indent = " " * (len(lines[line]) - len(lines[line].lstrip()) + 4)
        inserts[line] = (body is None, [indent + pin for pin in pins[name]])
    out = []
    for number, line in enumerate(lines):
        if number in inserts:
            bare, extra = inserts[number]
            out.append(line + ":" if bare else line)
            out.extend(extra)
        else:
            out.append(line)
    return "\n".join(out)


@unittest.skipUnless(HAVE_LARK, "lark (pinned in toolchain/versions.yaml) "
                     "is required")
class LibraryFormTest(unittest.TestCase):
    """E-5/E-17: a standard library instance's ports are its definition's
    pins, so restating them inline is the same design. Re-rendering (a)
    and (c) to the library form therefore left their design_hash where it
    was; this holds every benchmark, and every later edit, to that."""

    def test_restating_library_pins_inline_keeps_the_design_hash(self):
        from rhoform import ir

        for source in sources():
            with self.subTest(benchmark=source.parent.name), \
                    tempfile.TemporaryDirectory() as tmp:
                explicit = explicit_form(source)
                self.assertGreater(explicit.count("\n"),
                                   source.read_text().count("\n"))
                restated = Path(tmp) / source.name
                restated.write_text(explicit, encoding="utf-8")
                stream, compilation = build(restated)
                self.assertEqual(stream, "")
                design_hash = ir.to_ir(compilation.design)["header"][
                    "design_hash"]
                golden = goldens(source)[0].read_text(encoding="utf-8")
                self.assertIn(f'"design_hash":"{design_hash}"', golden)


# Each benchmark's check-stage stream and check report, by digest, from a
# process of its own: run under several PYTHONHASHSEED values, they must
# agree byte for byte (the M1 evidence standard for the IR, extended to the
# check stage).
_SEED_PROBE = r'''
import hashlib, json, sys
from pathlib import Path
from rhoform import compile as pipeline, ir
from rhoform.check import report as check_report
from rhoform.diagnostics import Diagnostics
out = {}
for entry in map(Path, sys.argv[1:]):
    sink = Diagnostics()
    c = pipeline.compile(entry.name, entry.parent, sink=sink)
    ir_bytes = ir.emit(c.design)[0]
    document = c.report.document(json.loads(ir_bytes)["header"]["design_hash"])
    out[entry.name] = {
        "stream": hashlib.sha256(sink.render().encode()).hexdigest(),
        "ir": hashlib.sha256(ir_bytes).hexdigest(),
        "report": hashlib.sha256(ir.canonical_bytes(document)).hexdigest(),
        "valid": check_report.schema_problem(document) is None}
print(json.dumps(out, sort_keys=True))
'''


@unittest.skipUnless(HAVE_LARK, "lark (pinned in toolchain/versions.yaml) "
                     "is required")
class BenchmarkCheckTest(unittest.TestCase):
    """The check stage on the benchmarks, against the KNOWN_FINDINGS
    ledger. The foundation's entries: every pass is a stub, so each
    benchmark has one actionable pass-not-implemented row per pass, each
    counted in its pass's landing's file, and so exactly one RHO3901
    (amendment OD1)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rhoform-benchmarks-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_the_ledger_is_well_formed_and_each_entry_has_one_owner(self):
        from rhoform import check as checker
        from rhoform import codes

        self.assertEqual(list(SECTION_LEDGERS), list(checker.pass_names()))
        names = {source.parent.name for source in sources()}
        owners = {}
        notes = set()
        gapped = set()
        ledger = known_findings()
        self.assertTrue(ledger)
        for landing, entries in ledger.items():
            with self.subTest(ledger=landing):
                self.assertIsInstance(entries, list)
                for entry in entries:
                    self.assertIn(sorted(entry), (sorted(FINDING_KEYS),
                                                  sorted(ROW_KEYS)))
                    self.assertIn(entry["benchmark"], names)
                    self.assertTrue(entry["reason"].strip())
                    self.assertTrue(entry["resolving_landing"].strip())
                    if "section" in entry:
                        self.assertEqual(
                            SECTION_LEDGERS.get(entry["section"]), landing,
                            f"{entry['section']} rows are counted in "
                            f"{SECTION_LEDGERS.get(entry['section'])}.json")
                        self.assertRegex(entry["class"],
                                         r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                        self.assertIs(type(entry["count"]), int)
                        self.assertGreater(entry["count"], 0)
                        key = (entry["benchmark"], entry["section"],
                               entry["class"])
                        gapped.add(entry["benchmark"])
                    else:
                        codes.lookup(entry["code"])
                        key = (entry["benchmark"], entry["code"],
                               entry["entity"])
                        if (entry["code"], entry["entity"]) == ("RHO3901",
                                                                "/"):
                            notes.add(entry["benchmark"])
                    self.assertNotIn(
                        key, owners, f"{key} is claimed by both "
                        f"{owners.get(key)} and {landing}; one finding or "
                        "row class has one ledger entry")
                    owners[key] = landing
            path = FINDINGS / f"{landing}.json"
            self.assertEqual(path.read_bytes(), (json.dumps(
                entries, indent=2, sort_keys=True) + "\n").encode(),
                f"{path.name} is not in canonical layout")
        # The coverage note fires exactly when some row is actionable.
        self.assertEqual(sorted(notes), sorted(gapped))

    def test_findings_and_actionable_rows_are_exactly_the_ledger(self):
        from collections import Counter

        from rhoform import check as checker

        expected = {}
        for entries in known_findings().values():
            for entry in entries:
                if "code" in entry:
                    expected.setdefault(entry["benchmark"], []).append(
                        (entry["code"], entry["entity"]))
        order = checker.pass_names()
        for source in sources():
            name = source.parent.name
            with self.subTest(benchmark=name):
                stream, compilation = build(
                    isolated_copy(source, self.tmp), stage="check")
                self.assertIsNotNone(compilation.report)
                lines = [json.loads(line) for line in stream.splitlines()]
                found = sorted((d["code"], d["entity"]) for d in lines)
                self.assertEqual(found, sorted(expected.get(name, [])),
                                 "the check stage's findings and the "
                                 "KNOWN_FINDINGS ledger disagree")
                rows = ledger_rows(name)
                self.assertEqual(
                    dict(Counter((section, row.reason) for section, row
                                 in compilation.report.actionable())),
                    rows, "the check report's actionable rows and the "
                    "KNOWN_FINDINGS ledger disagree")
                by_class = Counter()
                for (_section, kind), count in rows.items():
                    by_class[kind] += count
                notes = [d["params"] for d in lines
                         if (d["code"], d["entity"]) == ("RHO3901", "/")]
                self.assertEqual(notes, [{
                    "actionable": sum(rows.values()),
                    "classes": [f"{kind}: {count}" for kind, count
                                in sorted(by_class.items())],
                    "sections": sorted({section for section, _ in rows},
                                       key=order.index),
                }] if rows else [], "the coverage note does not count the "
                    "ledger's rows")

    def test_check_reports_are_canonical_schema_valid_and_seed_independent(
            self):
        entries = [str(isolated_copy(source, self.tmp))
                   for source in sources()]
        runs = []
        for seed in ("0", "1", "4242"):
            done = subprocess.run(
                [sys.executable, "-c", _SEED_PROBE, *entries],
                env=dict(os.environ, PYTHONHASHSEED=seed,
                         PYTHONPATH=str(ROOT)),
                capture_output=True, text=True, timeout=300)
            self.assertEqual(done.returncode, 0, done.stderr)
            runs.append(json.loads(done.stdout))
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(runs[0], runs[2])
        self.assertEqual(sorted(runs[0]), sorted(
            Path(entry).name for entry in entries))
        for name, digests in runs[0].items():
            with self.subTest(benchmark=name):
                self.assertTrue(digests["valid"])
                golden = BENCHMARKS / name[:-len(".rhoform")] / (
                    name[:-len(".rhoform")] + ".ir.json")
                self.assertEqual(digests["ir"], hashlib.sha256(
                    golden.read_bytes()).hexdigest())


class BlinkerOracleTest(unittest.TestCase):
    """The committed (a) golden against ir/examples/blinker.ir.json, which
    was written by hand before any elaborator existed. Regenerating a golden
    makes the byte test above pass whatever the compiler now does; this
    holds the design itself to an independent oracle. The example is a
    structural oracle only: its file layout was never committed and its
    resistances are in base ohm, so each difference allowed here is a
    recorded decision, named where it is allowed."""

    # Definition names follow the file the module is in (E-4); the
    # example's came from a two-file layout with a library module.
    DEFINITIONS = {"/": ("blinker.Blinker555", "blinker_555.Blinker555"),
                   "/indicator": ("rhoform.lib.display.LedIndicator",
                                  "blinker_555.LedIndicator")}
    # A label inside a module instance is qualified by its path (E-9).
    NETS = {"N_IND_LED": "indicator/N_IND_LED"}

    @classmethod
    def setUpClass(cls):
        import json

        cls.oracle = json.loads((ROOT / "ir" / "examples" / "blinker.ir.json")
                                .read_text(encoding="utf-8"))
        cls.golden = json.loads((BENCHMARKS / "blinker-555" /
                                 "blinker-555.ir.json")
                                .read_text(encoding="utf-8"))

    @staticmethod
    def exact(value):
        """A parameter value with its unit folded in, exactly: the IR may
        spell one quantity in any unit (E-6 picks the normal-form one)."""
        from decimal import Decimal

        from rhoform.quantities import UNITS

        if not isinstance(value, dict):
            return value
        dimension, scale = ("1", Decimal(1)) if value["unit"] == "1" \
            else UNITS[value["unit"]]
        tolerance = value.get("tolerance", {})
        return (dimension,) + tuple(
            (Decimal(repr(number)) * scale).normalize()
            for number in (value["value"], tolerance.get("min"),
                           tolerance.get("max")) if number is not None)

    def test_header_differs_only_by_decision(self):
        # design_name is the root module's name (E-3); the example's
        # `blinker_555` is spelled by nothing in any source.
        self.assertEqual(self.oracle["header"]["design_name"], "blinker_555")
        self.assertEqual(self.golden["header"]["design_name"], "Blinker555")
        for key in ("language_version", "canonical_form"):
            self.assertEqual(self.golden["header"][key],
                             self.oracle["header"][key])
        # The example is a hand-written IR v0 document, which v0's schema
        # still validates; the compiler writes v2 (ir/README.md,
        # "Versioning policy").
        self.assertEqual(self.oracle["header"]["ir_version"], 0)
        self.assertEqual(self.golden["header"]["ir_version"], 2)

    def test_same_instances_ports_flags_and_values(self):
        oracle = {i["path"]: i for i in self.oracle["instances"]}
        golden = {i["path"]: i for i in self.golden["instances"]}
        self.assertEqual(sorted(golden), sorted(oracle))
        for path, expected in oracle.items():
            got = golden[path]
            with self.subTest(path=path):
                want, have = self.DEFINITIONS.get(
                    path, (expected["definition"], expected["definition"]))
                self.assertEqual((expected["definition"], got["definition"]),
                                 (want, have))
                for key in ("kind", "ports", "dnp", "exclude_from_bom",
                            "board_only", "hardware_kind"):
                    self.assertEqual(got.get(key), expected.get(key), key)
                for key in ("parameters",):
                    self.assertEqual(
                        {k: self.exact(v) for k, v in got[key].items()},
                        {k: self.exact(v) for k, v in expected[key].items()})
                part, oracle_part = got.get("part"), expected.get("part")
                self.assertEqual(part is None, oracle_part is None)
                if part is not None:
                    self.assertEqual(
                        {k: v for k, v in part.items() if k != "constraints"},
                        {k: v for k, v in oracle_part.items()
                         if k != "constraints"})
                    self.assertEqual(
                        {k: self.exact(v) for k, v in
                         part.get("constraints", {}).items()},
                        {k: self.exact(v) for k, v in
                         oracle_part.get("constraints", {}).items()})

    def test_same_connectivity_domains_and_assertions(self):
        def nets(document, rename=lambda name: name):
            members = {}
            for connection in document["connections"]:
                port = connection["port"]
                members.setdefault(rename(connection["net"]), set()).add(
                    (port["instance"], port["port"]))
            domains = {rename(net["name"]): net for net in document["nets"]}
            return members, {name: {k: v for k, v in net.items()
                                    if k != "name"}
                             for name, net in domains.items()}

        rename = lambda name: self.NETS.get(name, name)  # noqa: E731
        self.assertEqual(nets(self.golden), nets(self.oracle, rename))
        self.assertEqual(self.golden["assertions"], self.oracle["assertions"])


if __name__ == "__main__":
    unittest.main()
