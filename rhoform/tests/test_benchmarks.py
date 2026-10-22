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
"""

import unittest
from pathlib import Path

try:
    import lark  # noqa: F401 - availability probe only
    HAVE_LARK = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_LARK = False

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / "benchmarks"

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


def build(source: Path):
    """(ParseResult, Elaboration) for one source, its directory the
    compile root. Bytes are decoded here rather than read as text, so the
    hashed bytes are the file's, with no newline translation between."""
    from rhoform.elaborate import elaborate
    from rhoform.parser import parse

    data = source.read_bytes()
    result = parse(data.decode("utf-8", "surrogateescape"), file=source.name)
    return result, elaborate([result])


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
        status = cli.main(emit_argv(source, source.parent))
        if status != 0:
            raise SystemExit(f"{source.relative_to(ROOT)} did not compile "
                             f"(exit {status}); its diagnostics are above")
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
                result, elaboration = build(source)
                self.assertEqual(result.diagnostics.render(), "")
                self.assertTrue(elaboration.ok)
                self.assertEqual(elaboration.diagnostics.render(), "")

    def test_elaborating_each_source_reproduces_its_goldens(self):
        from rhoform import ir

        for source in sources():
            with self.subTest(benchmark=source.parent.name):
                _result, elaboration = build(source)
                self.assertTrue(elaboration.ok,
                                elaboration.diagnostics.render())
                emitted = ir.emit(elaboration.design)
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
                result, elaboration = build(source)
                document = ir.to_ir(elaboration.design)
                source_map = ir.to_source_map(
                    elaboration.design, document["header"]["design_hash"])
                modules = elaborator.library_modules([result])
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
        from rhoform.elaborate import elaborate
        from rhoform.parser import parse

        for source in sources():
            with self.subTest(benchmark=source.parent.name):
                explicit = explicit_form(source)
                self.assertGreater(explicit.count("\n"),
                                   source.read_text().count("\n"))
                result = parse(explicit, file=source.name)
                elaboration = elaborate([result])
                self.assertEqual(elaboration.diagnostics.render(), "")
                design_hash = ir.to_ir(elaboration.design)["header"][
                    "design_hash"]
                golden = goldens(source)[0].read_text(encoding="utf-8")
                self.assertIn(f'"design_hash":"{design_hash}"', golden)


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
        for key in ("ir_version", "language_version", "canonical_form"):
            self.assertEqual(self.golden["header"][key],
                             self.oracle["header"][key])

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
