"""The package layer (R14b / AMB-45): manifests, imports, compilations.

The rules are the package spec's (R14a); spec/language/08-packages.md is
the restatement these tests hold the implementation to. `CodesTest` has
one test per diagnostic the package layer adds (the elaborator's
test_every_block_two_code_has_a_test_here counts them), each planting one
defect in an otherwise valid tree and pinning the code, its params and
the bytes its primary span covers.
"""

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import lark  # noqa: F401 - availability probe only
    HAVE_LARK = True
except ImportError:  # pragma: no cover - exercised by absence
    HAVE_LARK = False

ROOT = Path(__file__).resolve().parents[2]
P2 = "#pragma rhoform-syntax 0.2\n"
MANIFEST = ('[package]\nname = "acme/app"\nversion = "0.1.0"\n'
            'requires-rhoform = "^0.2.0"\nlicense = "Apache-2.0"\n')
PARTS = ('[package]\nname = "acme/parts"\nversion = "1.2.0"\n'
         'requires-rhoform = "^0.2.0"\nlicense = "MIT"\n')
LED = P2 + "\ncomponent Led:\n    pin a passive 1\n    pin k passive 2\n"
TOP = (P2 + 'import Led from "./leds"\n\nmodule Top:\n    led = new Led\n'
       "    isolated led.a\n    isolated led.k\n")


class _Tree(unittest.TestCase):
    """Builds a file tree under a temporary compile root."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rhoform-pkg-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def plant(self, files: dict) -> Path:
        for rel, text in files.items():
            path = self.tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        return self.tmp

    def compile(self, files: dict, entry="main.rhoform"):
        """(diagnostics as dicts, the package layer's compilation, the
        pipeline's, whose `design` is None unless it elaborated), through
        rhoform.compile at stage=elaborate."""
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics

        root = self.plant(files)
        sink = Diagnostics()
        compiled = pipeline.compile(entry, root, stage="elaborate", sink=sink)
        found = [json.loads(line) for line in sink.render().splitlines()]
        return found, compiled.loaded, compiled

    def only(self, files, code, entry="main.rhoform"):
        """The one diagnostic `files` draws, which must be `code`, and the
        text its primary span covers."""
        found, _c, _e = self.compile(files, entry)
        self.assertEqual([d["code"] for d in found], [code],
                         json.dumps(found, indent=1))
        span = found[0]["spans"][0]
        data = files[span["file"]].encode()
        return found[0], data[span["byte_start"]:span["byte_end"]].decode()


class VersionsTest(unittest.TestCase):
    def test_versions_are_semver_without_build_metadata(self):
        from rhoform.package import version_problem

        for good in ("0.1.0", "1.4.2", "10.20.30", "1.0.0-alpha.1",
                     "1.0.0-0.3.7", "1.0.0-x-y-z.--"):
            self.assertIsNone(version_problem(good), good)
        for bad in ("1", "1.2", "01.0.0", "1.02.0", "v1.0.0", "1.0.0-",
                    "1.0.0-01", "1.0.0 ", " 1.0.0", "1.0.0\n", ""):
            self.assertIn("SemVer", version_problem(bad), bad)
        self.assertIn("build metadata", version_problem("1.0.0+b.1"))

    def test_ranges_are_caret_or_exact_and_nothing_else(self):
        from rhoform.package import range_problem

        for good in ("^0.2.0", "^1.0.0", "=1.0.0", "=1.0.0-rc.1"):
            self.assertIsNone(range_problem(good), good)
        for bad in (">=1.0.0", "~1.0.0", "*", "1.0.0", "1.0.0 - 2", ""):
            self.assertIn("no other operator", range_problem(bad), bad)
        for bad in ("^1.0", "^1.0.0 || ^2.0.0", "=1", "^ 1.0.0"):
            self.assertIn("SemVer", range_problem(bad), bad)
        self.assertIn("pre-release", range_problem("^1.0.0-rc.1"))
        self.assertIn("build metadata", range_problem("=1.0.0+x"))

    def test_caret_windows_follow_l9_and_prereleases_only_pin(self):
        from rhoform.package import range_admits

        table = [
            ("^1.2.3", "1.2.3", True), ("^1.2.3", "1.9.0", True),
            ("^1.2.3", "2.0.0", False), ("^1.2.3", "1.2.2", False),
            ("^0.2.0", "0.2.9", True), ("^0.2.0", "0.3.0", False),
            ("^0.0.3", "0.0.9", True), ("^0.0.3", "0.1.0", False),
            ("^1.0.0", "1.1.0-alpha", False), ("=1.1.0-alpha",
                                               "1.1.0-alpha", True),
            ("=1.0.0", "1.0.0", True), ("=1.0.0", "1.0.1", False),
        ]
        for range_, version, admitted in table:
            self.assertEqual(range_admits(range_, version), admitted,
                             (range_, version))

    def test_version_numbers_compare_however_long(self):
        """SemVer numbers have no length limit, and int() has one
        (sys.get_int_max_str_digits): a long one used to crash the range
        check instead of comparing."""
        from rhoform.package import range_admits, range_problem

        long = "1" * 5000
        self.assertIsNone(range_problem(f"^0.{long}.0"))
        table = [
            (f"^0.{long}.0", "0.2.0", False),
            (f"^0.{long}.0", f"0.{long}.7", True),
            (f"^{long}.0.0", f"{long}.9.0", True),
            (f"^{long}.0.0", f"2{long[1:]}.0.0", False),
            (f"^1.0.{long}", "1.0.2", False),
            (f"^0.0.{long}", f"0.0.{long}", True),
            (f"={long}.0.0", f"{long}.0.0", True),
        ]
        for range_, version, admitted in table:
            self.assertEqual(range_admits(range_, version), admitted,
                             (range_[:12], version[:12]))

    @unittest.skipUnless(HAVE_LARK, "lark required")
    def test_language_versions_come_from_the_grammar(self):
        import importlib.util

        from rhoform.package import language_versions

        spec = importlib.util.spec_from_file_location(
            "_sot", ROOT / "lang" / "grammar" / "rhoform_syntax.py")
        sot = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sot)
        # Only the frozen ones (decision OD8): an unfrozen version parses,
        # but no manifest's range may admit it while it can still change.
        self.assertEqual(language_versions(),
                         tuple(v + ".0" for v in sot.SYNTAX_VERSIONS
                               if v not in sot.UNFROZEN_SYNTAX_VERSIONS))
        self.assertEqual(language_versions(), ("0.1.0", "0.2.0"))
        self.assertEqual(sot.UNFROZEN_SYNTAX_VERSIONS, ("0.3",))


class NamesTest(unittest.TestCase):
    def test_package_names_follow_n1_n2_n4(self):
        from rhoform.package import name_problem

        for good in ("acme/parts", "rho/passives", "a/b", "a1-b2/c-3",
                     "x" * 63 + "/" + "y" * 36):
            self.assertIsNone(name_problem(good), good)
        for bad, fragment in (
            ("acme", "exactly two segments"),
            ("a/b/c", "exactly two segments"),
            ("Acme/parts", "lowercase"), ("acme/Parts", "lowercase"),
            ("1acme/parts", "lowercase"), ("acme-/parts", "lowercase"),
            ("ac--me/parts", "lowercase"), ("acme_x/parts", "lowercase"),
            ("acme/", "lowercase"), ("x" * 64 + "/y", "63 bytes"),
            ("x" * 63 + "/" + "y" * 37, "100 bytes"),
        ):
            self.assertIn(fragment, name_problem(bad), bad)

    def test_spdx_expressions_are_checked_for_syntax(self):
        from rhoform.package import spdx_problem

        for good in ("MIT", "Apache-2.0", "MIT OR Apache-2.0",
                     "(MIT AND BSD-3-Clause) OR GPL-2.0-or-later",
                     "GPL-2.0+ WITH Classpath-exception-2.0",
                     "LicenseRef-acme-1", "DocumentRef-x:LicenseRef-y",
                     "CC-BY-4.0"):
            self.assertIsNone(spdx_problem(good), good)
        for bad in ("", "MIT OR", "AND MIT", "(MIT", "MIT)", "MIT WITH",
                    "Apache 2.0", "MIT/X11", "MIT,BSD", "(" * 40 + "MIT"
                    + ")" * 40):
            self.assertIsNotNone(spdx_problem(bad), bad)

    def test_import_paths_classify_as_x1_or_x2(self):
        from rhoform.package import classify

        self.assertEqual(classify("./leds"), ("local", "./leds.rhoform"))
        self.assertEqual(classify("leds.rhoform"),
                         ("local", "leds.rhoform"))
        self.assertEqual(classify("../lib/x"), ("local", "../lib/x.rhoform"))
        self.assertEqual(classify("rho/passives/resistors"),
                         ("package", "rho/passives", "resistors.rhoform"))
        self.assertEqual(classify("acme/parts/sub/leds.rhoform"),
                         ("package", "acme/parts", "sub/leds.rhoform"))
        for bad, fragment in (("", "empty"), ("/abs", "absolute"),
                              ("./a//b", "empty segment"), ("./", "empty"),
                              ("./x/..", "directory"),
                              ("lib/parts.rhoform", "package name"),
                              ("acme/parts", "no module"),
                              ("acme/parts/../x", "`.` or `..`")):
            kind, reason = classify(bad)
            self.assertEqual(kind, "invalid", bad)
            self.assertIn(fragment, reason, bad)


class TomlSpansTest(unittest.TestCase):
    def test_keys_and_values_are_found_in_every_spelling(self):
        from rhoform.package import _TomlSpans

        text = ('# head\n[package]\nname = "acme/app"  # c\n'
                "'requires-rhoform' = '^0.2.0'\n"
                'description = """multi\nline"""\n'
                'exclude = [\n  "a", # c\n  "b",\n]\n'
                'package2.x = 1\n'
                '[deps]\n"acme/parts" = { version = "^1.0.0", path = "../p" }\n'
                '[deps."acme/more"]\npath = "x"\n')
        spans = _TomlSpans(text)

        def show(path, part="value"):
            start, end = spans.find(path, part)
            return text[start:end]

        self.assertEqual(show(("package", "name")), '"acme/app"')
        self.assertEqual(show(("package", "name"), "key"), "name")
        self.assertEqual(show(("package", "requires-rhoform"), "key"),
                         "'requires-rhoform'")
        self.assertEqual(show(("package", "description")),
                         '"""multi\nline"""')
        self.assertEqual(show(("package", "exclude")),
                         '[\n  "a", # c\n  "b",\n]')
        self.assertEqual(show(("package", "package2", "x"), "key"),
                         "package2.x")
        self.assertEqual(show(("deps", "acme/parts", "path")), '"../p"')
        self.assertEqual(show(("deps", "acme/parts"), "key"), '"acme/parts"')
        self.assertEqual(show(("deps", "acme/more", "path")), '"x"')
        self.assertEqual(show(("deps", "acme/more", "nope")),
                         '[deps."acme/more"]')
        self.assertEqual(spans.find(("nowhere",)), (0, 0))

    def test_the_scanner_is_total_over_mutated_manifests(self):
        import tomllib

        from rhoform.diagnostics import Diagnostics
        from rhoform.package import Package, read_manifest

        base = MANIFEST + ('description = "d"\nexclude = ["x"]\n[deps]\n'
                           '"acme/parts" = { version = "^1.0.0", '
                           'path = "../p" }\n')
        rng = random.Random(45)
        pieces = ['"', "'", "[", "]", "{", "}", "=", ",", "\n", "#", ".",
                  '"""', "'''", " ", "x", "1", "\\", "\t", "é"]
        for _ in range(400):
            chars = list(base)
            for _ in range(rng.randrange(1, 5)):
                at = rng.randrange(len(chars) + 1)
                if rng.random() < 0.5 and chars:
                    del chars[min(at, len(chars) - 1)]
                else:
                    chars.insert(at, rng.choice(pieces))
            text = "".join(chars)
            package = Package(root="", manifest="rhoform.toml",
                              data=text.encode())
            sink = Diagnostics()
            read_manifest(package, sink)  # must not raise
            try:
                tomllib.loads(text)
            except tomllib.TOMLDecodeError:
                self.assertIn("RHO2048", [d.code for d in sink])


@unittest.skipUnless(HAVE_LARK, "lark required")
class CompilationTest(_Tree):
    def test_an_x1_import_names_definitions_by_their_own_file(self):
        found, compilation, elaboration = self.compile({
            "rhoform.toml": MANIFEST, "main.rhoform": TOP,
            "lib/leds.rhoform": LED})
        self.assertEqual(found[0]["code"], "RHO2060")
        found, compilation, elaboration = self.compile({
            "main.rhoform": TOP.replace("./leds", "./lib/leds")})
        self.assertEqual(found, [])
        design = elaboration.design
        # The first call's rhoform.toml still governs the tree, so the
        # names carry its package's identity (AMB-144 item 1).
        self.assertEqual({i.path: i.definition for i in design.instances},
                         {"/": "acme.app.main.Top",
                          "/led": "acme.app.lib.leds.Led"})
        self.assertEqual([f.path for f in design.files],
                         ["lib/leds.rhoform", "main.rhoform"])
        self.assertEqual([r.file for r in compilation.results],
                         ["main.rhoform", "lib/leds.rhoform"])

    def test_source_hash_covers_every_file_read(self):
        from rhoform import ir

        files = {"main.rhoform": TOP, "leds.rhoform": LED}
        _f, _c, first = self.compile(files)
        before = json.loads(ir.emit(first.design)[0])["header"]
        self.plant({"leds.rhoform": LED + "\n# a comment\n"})
        _f, _c, second = self.compile({})
        after = json.loads(ir.emit(second.design)[0])["header"]
        self.assertNotEqual(before["source_hash"], after["source_hash"])
        self.assertEqual(before["design_hash"], after["design_hash"])
        source_map = json.loads(ir.emit(second.design)[1])
        self.assertEqual([f["path"] for f in source_map["files"]],
                         ["leds.rhoform", "main.rhoform"])

    def test_an_x2_import_reads_a_path_dependency_in_place(self):
        files = {
            "app/rhoform.toml": MANIFEST + '[deps]\n"acme/parts" = '
            '{ version = "^1.0.0", path = "../parts" }\n',
            "app/main.rhoform": TOP.replace("./leds", "acme/parts/leds"),
            "parts/rhoform.toml": PARTS, "parts/leds.rhoform": LED}
        found, compilation, elaboration = self.compile(
            files, entry="app/main.rhoform")
        self.assertEqual(found, [])
        self.assertEqual(
            {i.path: i.definition for i in elaboration.design.instances},
            {"/": "acme.app.main.Top", "/led": "acme.parts.leds.Led"})

    def test_a_package_keeps_its_names_wherever_it_sits(self):
        # AMB-144 item 1: definitions are named by package identity, so
        # moving or vendoring a dependency renames nothing and leaves the
        # consumer's design_hash where it was.
        from rhoform import ir

        hashes, names = [], []
        for where in ("parts", "vendor/acme-parts"):
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp.mkdir()
            found, _c, compiled = self.compile({
                "app/rhoform.toml": MANIFEST + '[deps]\n"acme/parts" = '
                f'{{ version = "^1.0.0", path = "../{where}" }}\n',
                "app/main.rhoform": TOP.replace("./leds", "acme/parts/leds"),
                f"{where}/rhoform.toml": PARTS, f"{where}/leds.rhoform": LED},
                entry="app/main.rhoform")
            self.assertEqual(found, [])
            names.append(sorted(i.definition
                                for i in compiled.design.instances))
            hashes.append(ir.to_ir(compiled.design)["header"]["design_hash"])
        self.assertEqual(names[0], names[1])
        self.assertEqual(names[0], ["acme.app.main.Top",
                                    "acme.parts.leds.Led"])
        self.assertEqual(hashes[0], hashes[1])

    def test_module_names_prefix_a_governed_file_with_its_identity(self):
        from rhoform.package import Package, module_name

        package = Package(root="pkgs/app", manifest="pkgs/app/rhoform.toml",
                          name="acme-co/app-core")
        self.assertEqual(module_name("pkgs/app/lib/x-y.rhoform", package),
                         "acme_co.app_core.lib.x_y")
        self.assertEqual(module_name("lib/x-y.rhoform", None), "lib.x_y")
        loose = Package(root="", manifest=None)
        self.assertEqual(module_name("a/b.rhoform", loose), "a.b")

    def test_roots_come_from_the_entry_file_only(self):
        library = (P2 + "\nmodule Spare:\n    port p passive\n"
                   "\ncomponent Led:\n    pin a passive\n    pin k passive\n")
        found, _c, elaboration = self.compile({
            "main.rhoform": TOP, "leds.rhoform": library})
        self.assertEqual(found, [])
        self.assertEqual(elaboration.design.design_name, "Top")
        # An imported module can be instantiated, and its own defects are
        # reported in its own file.
        broken = library.replace("port p passive", "port p pasive")
        found, _c, _e = self.compile({"leds.rhoform": broken})
        self.assertEqual([(d["code"], d["spans"][0]["file"]) for d in found],
                         [("RHO1009", "leds.rhoform")])

    def test_an_imported_name_is_not_re_exported(self):
        middle = P2 + 'import Led from "./leds"\n\ncomponent Other:\n' \
            "    pin p passive\n"
        found, _c, _e = self.compile({
            "main.rhoform": TOP.replace("./leds", "./middle"),
            "middle.rhoform": middle, "leds.rhoform": LED})
        self.assertEqual([(d["code"], d["params"]) for d in found],
                         [("RHO2065", {"name": "Led",
                                       "file": "middle.rhoform"})])

    def test_a_failed_import_is_the_one_defect(self):
        found, _c, _e = self.compile({
            "main.rhoform": TOP.replace("import Led",
                                        "import Led, Lamp") +
            "    lamp = new Lamp\n", "leds.rhoform": LED})
        self.assertEqual([d["code"] for d in found], ["RHO2065"])

    def test_an_import_never_enters_a_nested_package(self):
        found, _c, _e = self.compile({
            "rhoform.toml": MANIFEST,
            "main.rhoform": TOP.replace("./leds", "./vendor/leds"),
            "vendor/rhoform.toml": PARTS, "vendor/leds.rhoform": LED})
        self.assertEqual([(d["code"], d["params"]["boundary"])
                          for d in found],
                         [("RHO2061", "package `acme/app`")])

    def test_the_language_version_is_the_newest_file_pragma(self):
        led01 = LED.replace("0.2", "0.1").replace(
            "component Led:\n    pin a passive 1\n    pin k passive 2\n",
            "module Led:\n    port a passive\n    port k passive\n")
        _f, _c, elaboration = self.compile({"main.rhoform": TOP,
                                            "leds.rhoform": led01})
        self.assertEqual(elaboration.design.language_version, "0.2.0")

    def test_the_manifest_read_closure_is_the_dependency_graph(self):
        from rhoform import package
        from rhoform.diagnostics import Diagnostics

        files = {
            "app/rhoform.toml": MANIFEST + '[deps]\n"acme/parts" = '
            '{ version = "^1.0.0", path = "../parts" }\n',
            "app/main.rhoform": TOP,
            "app/leds.rhoform": LED,
            "app/unused.rhoform": "this is never read",
            "parts/rhoform.toml": PARTS + '[deps]\n"acme/app" = '
            '{ version = "^0.1.0", path = "../app" }\n',
            "parts/leds.rhoform": LED,
            "other/rhoform.toml": "never read either"}
        root = self.plant(files)
        opened = []
        real = Path.read_bytes

        def spy(self):
            opened.append(self.relative_to(root).as_posix())
            return real(self)

        sink = Diagnostics()
        with mock.patch.object(Path, "read_bytes", spy):
            compilation = package.load("app/main.rhoform", root, sink)
        self.assertTrue(compilation.ok, sink.render())
        self.assertEqual(sorted(opened), [
            "app/leds.rhoform", "app/main.rhoform", "app/rhoform.toml",
            "parts/rhoform.toml"])

    def test_one_package_has_one_source(self):
        files = {
            "app/rhoform.toml": MANIFEST + '[deps]\n"acme/parts" = '
            '{ version = "^1.0.0", path = "../parts" }\n'
            '"acme/more" = { version = "^1.0.0", path = "../more" }\n',
            "app/main.rhoform": TOP,
            "app/leds.rhoform": LED,
            "parts/rhoform.toml": PARTS,
            "more/rhoform.toml": PARTS.replace("acme/parts", "acme/more")
            + '[deps]\n"acme/parts" = { version = "^1.0.0", '
              'path = "../copy" }\n',
            "copy/rhoform.toml": PARTS}
        found, _c, _e = self.compile(files, entry="app/main.rhoform")
        self.assertEqual([(d["code"], d["spans"][0]["file"]) for d in found],
                         [("RHO2057", "more/rhoform.toml")])
        self.assertIn("second source", found[0]["params"]["problem"])

    def test_a_broken_dependency_is_reported_once_not_per_import(self):
        files = {
            "app/rhoform.toml": MANIFEST + '[deps]\n"acme/parts" = '
            '{ version = "^1.0.0", path = "../parts" }\n',
            "app/main.rhoform": TOP.replace("./leds", "acme/parts/leds"),
            "parts/rhoform.toml": PARTS.replace('"MIT"', '"MIT OR"'),
            "parts/leds.rhoform": LED}
        found, _c, _e = self.compile(files, entry="app/main.rhoform")
        self.assertEqual([(d["code"], d["spans"][0]["file"]) for d in found],
                         [("RHO2051", "parts/rhoform.toml")])

    def test_a_path_the_file_system_cannot_name_is_not_found(self):
        # Python 3.12's Path.is_file() raises on ENAMETOOLONG where 3.14's
        # returns False; either way it is an import of no file.
        long = "./" + "x" * 300
        found, _c, _e = self.compile({
            "main.rhoform": TOP.replace("./leds", long)})
        self.assertEqual([d["code"] for d in found], ["RHO2060"])
        found, _c, _e = self.compile({
            "main.rhoform": TOP.replace("./leds", "acme/parts/" + "y" * 300),
            "rhoform.toml": MANIFEST + '[deps]\n"acme/parts" = { version = '
            '"^1.0.0", path = "' + "z" * 300 + '" }\n'})
        self.assertEqual([d["code"] for d in found], ["RHO2057"])

    def test_elaborate_alone_resolves_among_the_files_it_is_given(self):
        from rhoform.elaborate import elaborate
        from rhoform.parser import parse

        main = parse(TOP, file="main.rhoform")
        leds = parse(LED, file="leds.rhoform")
        self.assertTrue(elaborate([main, leds]).ok)
        alone = elaborate([parse(TOP, file="main.rhoform")])
        self.assertEqual([d.code for d in alone.diagnostics], ["RHO2060"])
        self.assertIsNone(alone.design)

    def test_compilation_is_independent_of_the_hash_seed(self):
        files = {
            "app/rhoform.toml": MANIFEST + '[deps]\n"acme/parts" = '
            '{ version = "^1.0.0", path = "../parts" }\n',
            "app/main.rhoform": TOP.replace(
                'import Led from "./leds"',
                'import Led from "acme/parts/leds"\n'
                'import A, B from "./ab"'),
            "app/ab.rhoform": P2 + 'import Top from "./main"\n\n'
                              "component A:\n    pin p passive\n",
            "parts/rhoform.toml": PARTS, "parts/leds.rhoform": LED}
        root = self.plant(files)
        program = (
            "import sys\nfrom pathlib import Path\n"
            "from rhoform import package\n"
            "from rhoform.diagnostics import Diagnostics\n"
            "sink = Diagnostics()\n"
            "package.load('app/main.rhoform', Path(sys.argv[1]), sink)\n"
            "print(sink.render())\n")
        outputs = set()
        for seed in ("0", "1", "4242"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            done = subprocess.run([sys.executable, "-c", program, str(root)],
                                  cwd=ROOT, env=env, capture_output=True,
                                  text=True, check=True)
            outputs.add(done.stdout)
        self.assertEqual(len(outputs), 1)
        codes = [json.loads(line)["code"]
                 for line in outputs.pop().splitlines() if line]
        self.assertEqual(codes, ["RHO2064"])


DIVIDER = (P2 + "\nmodule Divider:\n    port top passive\n"
           "    port mid passive\n    r1 = new rhoform.lib.passive.Resistor\n"
           "    top ~ r1.a\n    mid ~ r1.b\n")
MAIN = (P2 + 'import Divider from "./divider"\n\nmodule Main:\n'
        "    d = new Divider\n    d.top ~ d.mid\n")


@unittest.skipUnless(HAVE_LARK, "lark required")
class LetterCaseTest(_Tree):
    """Names on a path match the file system's exactly, letter case
    included, on every host: a case-insensitive file system (macOS's
    default) must not resolve what Linux reports as missing, nor give one
    file two keys and so two identities."""

    def fixit(self, found):
        (edit,) = found["fixits"][0]["edits"]
        return edit["replacement"]

    def test_an_import_spelled_in_the_wrong_case_names_nothing(self):
        cases = {"./LEDS": '"./leds"', "LEDS.rhoform": '"leds.rhoform"',
                 "./Lib/leds": '"./lib/leds"'}
        for spelled, meant in cases.items():
            with self.subTest(spelled=spelled):
                where = "lib/" if "Lib" in spelled else ""
                d, text = self.only({
                    "main.rhoform": TOP.replace("./leds", spelled),
                    where + "leds.rhoform": LED}, "RHO2060")
                self.assertEqual(text, f'"{spelled}"')
                self.assertEqual(self.fixit(d), meant)
                shutil.rmtree(self.tmp)
                self.tmp.mkdir()

    def test_one_file_never_gets_a_second_key(self):
        sub = (P2 + 'import Led from "./Leds"\n\nmodule Sub:\n'
               "    port p passive\n    q = new Led\n    q.a ~ p\n"
               "    isolated q.k\n")
        main = (P2 + 'import Led from "./leds"\nimport Sub from "./sub"\n\n'
                "module Main:\n    port p passive\n    s = new Sub\n"
                "    d = new Led\n    d.a ~ p\n    s.p ~ p\n"
                "    isolated d.k\n")
        files = {"main.rhoform": main, "sub.rhoform": sub,
                 "leds.rhoform": LED}
        found, _c, _e = self.compile(files)
        self.assertEqual([(d["code"], d["spans"][0]["file"]) for d in found],
                         [("RHO2060", "sub.rhoform")])
        files["sub.rhoform"] = sub.replace("./Leds", "./leds")
        found, _c, elaboration = self.compile(files)
        self.assertEqual(found, [])
        self.assertEqual(
            sorted({i.definition for i in elaboration.design.instances}),
            ["leds.Led", "main.Main", "sub.Sub"])

    def test_a_manifest_is_named_rhoform_toml_exactly(self):
        found, compilation, _e = self.compile({
            "app/RHOFORM.TOML": "not toml at all = = =\n",
            "app/main.rhoform": TOP, "app/leds.rhoform": LED},
            entry="app/main.rhoform")
        self.assertEqual(found, [])
        self.assertTrue(compilation.ok)

    def test_a_dependency_path_in_the_wrong_case_is_refused(self):
        found, _c, _e = self.compile({
            "app/rhoform.toml": MANIFEST + '[deps]\n"acme/parts" = '
            '{ version = "^1.0.0", path = "../Parts" }\n',
            "app/main.rhoform": TOP.replace("./leds", "acme/parts/leds"),
            "parts/rhoform.toml": PARTS, "parts/leds.rhoform": LED},
            entry="app/main.rhoform")
        self.assertEqual([d["code"] for d in found], ["RHO2057"])
        self.assertIn("`parts`", found[0]["params"]["problem"])

    def test_an_entry_spelled_in_the_wrong_case_is_not_read(self):
        from rhoform import package

        with self.assertRaises(package.ReadFailure):
            self.compile({"main.rhoform": TOP, "leds.rhoform": LED},
                         entry="MAIN.rhoform")

    def test_a_package_import_spelled_in_the_wrong_case_names_nothing(self):
        d, text = self.only({
            "app/rhoform.toml": MANIFEST + '[deps]\n"acme/parts" = '
            '{ version = "^1.0.0", path = "../parts" }\n',
            "app/main.rhoform": TOP.replace("./leds", "acme/parts/Leds"),
            "parts/rhoform.toml": PARTS, "parts/leds.rhoform": LED},
            "RHO2060", entry="app/main.rhoform")
        self.assertEqual(self.fixit(d), '"acme/parts/leds"')


@unittest.skipUnless(HAVE_LARK and hasattr(os, "symlink"),
                     "lark and symbolic links required")
class SymlinkTest(_Tree):
    """Nothing outside the compile root is opened, and an import stays in
    its package, however the file system links its names: a lexical path
    under the root that leads out of it through a symbolic link is
    refused before anything there is read."""

    SECRET = "SECRET_TOKEN=abc123xyz\n"

    def setUp(self):
        super().setUp()
        self.root = self.tmp / "ws"
        self.outside = self.tmp / "outside"
        self.outside.mkdir()
        (self.outside / "notes.txt").write_text(self.SECRET)
        (self.outside / "secret.rhoform").write_text(LED)

    def link(self, name, target):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, path)

    def load(self, files, entry="app/main.rhoform"):
        from rhoform import package
        from rhoform.diagnostics import Diagnostics

        for rel, text in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        sink = Diagnostics()
        compilation = package.load(entry, self.root, sink)
        rendered = sink.render()
        self.assertNotIn("SECRET", rendered)
        return [json.loads(line) for line in rendered.splitlines()], \
            compilation

    def test_a_linked_module_file_out_of_the_root_is_not_read(self):
        self.link("app/leds.rhoform", "../../outside/notes.txt")
        found, compilation = self.load({"app/rhoform.toml": MANIFEST,
                                        "app/main.rhoform": TOP})
        self.assertEqual([(d["code"], d["params"]) for d in found],
                         [("RHO2061", {"path": "./leds",
                                       "boundary": "package `acme/app`"})])
        self.assertEqual([r.file for r in compilation.results],
                         ["app/main.rhoform"])

    def test_a_linked_directory_out_of_the_root_is_not_entered(self):
        self.link("app/shared", "../../outside")
        found, _c = self.load({"main.rhoform": TOP.replace(
            "./leds", "./app/shared/secret")}, entry="main.rhoform")
        self.assertEqual([(d["code"], d["params"]) for d in found],
                         [("RHO2061", {"path": "./app/shared/secret",
                                       "boundary": "the compile root"})])

    def test_a_link_into_another_package_leaves_this_one(self):
        self.link("app/leds.rhoform", "../parts/leds.rhoform")
        found, _c = self.load({"app/rhoform.toml": MANIFEST,
                               "app/main.rhoform": TOP,
                               "parts/rhoform.toml": PARTS,
                               "parts/leds.rhoform": LED})
        self.assertEqual([d["code"] for d in found], ["RHO2061"])

    def test_a_link_that_stays_in_the_package_is_followed(self):
        self.link("app/leds.rhoform", "real/leds.rhoform")
        found, compilation = self.load({"app/rhoform.toml": MANIFEST,
                                        "app/main.rhoform": TOP,
                                        "app/real/leds.rhoform": LED})
        self.assertEqual(found, [])
        self.assertTrue(compilation.ok)

    def test_a_linked_dependency_root_out_of_the_root_is_refused(self):
        (self.outside / "parts").mkdir()
        (self.outside / "parts" / "rhoform.toml").write_text(PARTS)
        (self.outside / "parts" / "leds.rhoform").write_text(LED)
        self.link("parts", "../outside/parts")
        found, _c = self.load({
            "app/rhoform.toml": MANIFEST + '[deps]\n"acme/parts" = '
            '{ version = "^1.0.0", path = "../parts" }\n',
            "app/main.rhoform": TOP.replace("./leds", "acme/parts/leds")})
        self.assertEqual([d["code"] for d in found], ["RHO2057"])
        self.assertIn("outside the compile root",
                      found[0]["params"]["problem"])

    def test_a_linked_manifest_or_entry_out_of_the_root_is_never_read(self):
        from rhoform import package

        (self.outside / "rhoform.toml").write_text(MANIFEST)
        self.link("app/rhoform.toml", "../../outside/rhoform.toml")
        with self.assertRaises(package.ReadFailure) as raised:
            self.load({"app/main.rhoform": TOP, "app/leds.rhoform": LED})
        self.assertIn("outside the compile root", str(raised.exception))
        self.link("main.rhoform", "../outside/secret.rhoform")
        with self.assertRaises(package.ReadFailure):
            self.load({}, entry="main.rhoform")


@unittest.skipUnless(HAVE_LARK, "lark required")
class LibraryTest(_Tree):
    """The bundled library (spec 04) seen from a compilation of several
    files: every file of the closure resolves `rhoform.lib.` names, the
    package layer never reads a library module, and a module read is
    listed by its fixed path whatever the compile root."""

    def files_of(self, elaboration):
        return [f.path for f in elaboration.design.files]

    def test_an_imported_file_resolves_library_names(self):
        found, compilation, elaboration = self.compile({
            "rhoform.toml": MANIFEST, "main.rhoform": MAIN,
            "divider.rhoform": DIVIDER})
        self.assertEqual(found, [])
        design = elaboration.design
        self.assertEqual({i.path: i.definition for i in design.instances},
                         {"/": "acme.app.main.Main",
                          "/d": "acme.app.divider.Divider",
                          "/d/r1": "rhoform.lib.passive.Resistor"})
        resistor = next(i for i in design.instances if i.path == "/d/r1")
        self.assertEqual([p.name for p in resistor.ports], ["a", "b"])
        self.assertEqual(self.files_of(elaboration),
                         ["divider.rhoform", "main.rhoform",
                          "rhoform/lib/passive.rhoform"])
        self.assertEqual([r.file for r in compilation.results],
                         ["main.rhoform", "divider.rhoform"])

    def test_library_paths_are_fixed_whatever_the_compile_root(self):
        # A package below the compile root and a path dependency: the
        # authored files move with the compile root, the library does not.
        _f, _c, nested = self.compile({
            "rhoform.toml": MANIFEST, "src/main.rhoform": MAIN,
            "src/divider.rhoform": DIVIDER}, entry="src/main.rhoform")
        self.assertEqual(self.files_of(nested),
                         ["rhoform/lib/passive.rhoform",
                          "src/divider.rhoform", "src/main.rhoform"])
        found, _c, dependency = self.compile({
            "app/rhoform.toml": MANIFEST + '[deps]\n"acme/parts" = '
            '{ version = "^1.0.0", path = "../parts" }\n',
            "app/main.rhoform": MAIN.replace("./divider",
                                             "acme/parts/divider"),
            "parts/rhoform.toml": PARTS, "parts/divider.rhoform": DIVIDER},
            entry="app/main.rhoform")
        self.assertEqual(found, [])
        self.assertEqual(self.files_of(dependency),
                         ["app/main.rhoform", "parts/divider.rhoform",
                          "rhoform/lib/passive.rhoform"])
        resistor = next(i for i in dependency.design.instances
                        if i.path == "/d/r1")
        self.assertEqual(resistor.definition, "rhoform.lib.passive.Resistor")

    def test_a_bad_library_name_in_an_imported_file_is_reported_there(self):
        files = {"main.rhoform": MAIN, "divider.rhoform": DIVIDER.replace(
            "passive.Resistor", "passive.Resistr")}
        d, text = self.only(files, "RHO2067")
        self.assertEqual(d["spans"][0]["file"], "divider.rhoform")
        self.assertEqual(text, "rhoform.lib.passive.Resistr")
        self.assertEqual(d["fixits"][0]["edits"][0]["replacement"],
                         "rhoform.lib.passive.Resistor")

    def test_the_library_does_not_raise_the_language_version(self):
        # The library's modules are 0.2 files; a 0.2 design that imports
        # a 0.1 file which uses them is still 0.2.0, and a 0.1 design
        # that uses them alone is still 0.1.0.
        divider01 = DIVIDER.replace("0.2", "0.1")
        _f, _c, mixed = self.compile({"main.rhoform": MAIN,
                                      "divider.rhoform": divider01})
        self.assertEqual(mixed.design.language_version, "0.2.0")
        alone = divider01.replace("module Divider", "module Main")
        _f, _c, old = self.compile({"main.rhoform": alone})
        self.assertEqual(old.design.language_version, "0.1.0")
        self.assertEqual(self.files_of(old),
                         ["main.rhoform", "rhoform/lib/passive.rhoform"])


@unittest.skipUnless(HAVE_LARK, "lark required")
class CodesTest(_Tree):
    """One test per package-layer code; the elaborator's code census
    counts these."""

    def test_rho2048_manifest_not_toml(self):
        d, text = self.only({"rhoform.toml": MANIFEST + "oops = \n",
                             "main.rhoform": TOP}, "RHO2048")
        self.assertEqual(d["params"], {"reason": "invalid value"})
        self.assertEqual(d["spans"][0]["line_start"], 6)
        self.assertEqual(text, "")
        self.plant({"main.rhoform": TOP})
        (self.tmp / "rhoform.toml").write_bytes(b"[package]\nname = \"\xff\"")
        found, _c, _e = self.compile({})
        self.assertEqual([(d["code"], d["params"]) for d in found],
                         [("RHO2048", {"reason": "it is not UTF-8"})])

    def test_rho2048_an_integer_too_long_to_read(self):
        """tomllib lets a bare ValueError out for an integer past
        sys.get_int_max_str_digits. TOML 1.0.0 integers are 64-bit, so
        that is invalid TOML, not an internal error."""
        d, _text = self.only({"rhoform.toml": MANIFEST + "description = "
                              + "1" * 5000 + "\n", "main.rhoform": TOP},
                             "RHO2048")
        self.assertEqual(d["params"], {
            "reason": "an integer in it is outside TOML's 64-bit range"})

    def test_rho2058_a_range_whose_numbers_are_too_long_to_convert(self):
        d, _text = self.only({"rhoform.toml": MANIFEST.replace(
            "^0.2.0", "^0." + "1" * 5000 + ".0"), "main.rhoform": TOP},
            "RHO2058")
        self.assertEqual(d["params"]["supported"], "0.1.0, 0.2.0")

    def test_rho2068_reserved_module_path(self):
        # An author's file whose module path is under `rhoform.lib.` would
        # take the library's identities: refused at the import, unread.
        resistor = (P2 + "\ncomponent Resistor:\n    pin x passive 7\n"
                    "    pin y passive 9\n")
        main = (P2 + 'import Resistor from "./rhoform/lib/passive"\n\n'
                "module Panel:\n    r1 = new Resistor\n"
                "    r2 = new rhoform.lib.passive.Resistor\n"
                "    isolated r1.x\n    isolated r1.y\n"
                "    isolated r2.a\n    isolated r2.b\n")
        files = {"main.rhoform": main,
                 "rhoform/lib/passive.rhoform": resistor}
        d, text = self.only(files, "RHO2068")
        self.assertEqual(d["params"], {"file": "rhoform/lib/passive.rhoform",
                                       "module": "rhoform.lib.passive"})
        self.assertEqual(text, '"./rhoform/lib/passive"')
        _f, compilation, _e = self.compile(files)
        self.assertEqual([r.file for r in compilation.results],
                         ["main.rhoform"])
        # As the entry it is refused before it is read.
        found, compilation, _e = self.compile(
            {}, entry="rhoform/lib/passive.rhoform")
        self.assertEqual([d["code"] for d in found], ["RHO2068"])
        self.assertEqual(compilation.results, [])

    DIVIDER = (P2 + "\nmodule Divider:\n    port top passive\n"
               "    r1 = new rhoform.lib.passive.Resistor\n"
               "    top ~ r1.a\n    isolated r1.b\n")

    def test_rho2069_module_path_collision(self):
        # a_b/x.rhoform and a-b/x.rhoform both have the module path a_b.x,
        # so two different Dividers would both be `a_b.x.Divider` in the
        # IR. The second file read is refused at the import that brings it
        # in, and is not read.
        other = self.DIVIDER.replace("isolated r1.b", "r1.b ~ top")
        probe = (P2 + 'import Divider from "./a-b/x"\n\nmodule Probe:\n'
                 "    port top passive\n    d = new Divider\n"
                 "    top ~ d.top\n")
        main = (P2 + 'import Divider from "./a_b/x"\n'
                'import Probe from "./probe"\n\nmodule Panel:\n'
                "    port top passive\n    d = new Divider\n"
                "    p = new Probe\n    top ~ d.top\n    top ~ p.top\n")
        files = {"main.rhoform": main, "probe.rhoform": probe,
                 "a_b/x.rhoform": self.DIVIDER, "a-b/x.rhoform": other}
        d, _text = self.only(files, "RHO2069")
        self.assertEqual(d["params"], {"file": "a-b/x.rhoform",
                                       "module": "a_b.x",
                                       "first": "a_b/x.rhoform"})
        self.assertEqual(d["spans"][0]["file"], "probe.rhoform")
        span = d["spans"][0]
        self.assertEqual(probe.encode()[span["byte_start"]:span["byte_end"]],
                         b'"./a-b/x"')
        _f, compilation, _e = self.compile(files)
        self.assertNotIn("a-b/x.rhoform",
                         [r.file for r in compilation.results])
        self.assertFalse(compilation.ok)

    def test_rho2068_a_package_named_into_the_reserved_prefix(self):
        # A file is named by its package's identity, so a package
        # `rhoform/lib` (its namespace acknowledged) would name its files
        # into the library's prefix: refused as the entry and at an import.
        manifest = MANIFEST.replace('"acme/app"', '"rhoform/lib"') \
            + "reserved-namespace-ack = true\n"
        found, compilation, _e = self.compile({
            "rhoform.toml": manifest, "main.rhoform": TOP,
            "leds.rhoform": LED})
        self.assertEqual([(d["code"], d["params"]) for d in found], [(
            "RHO2068", {"file": "main.rhoform",
                        "module": "rhoform.lib.main"})])
        self.assertEqual(compilation.results, [])
        shutil.rmtree(self.tmp)
        self.tmp.mkdir()
        found, compilation, _e = self.compile({
            "app/rhoform.toml": MANIFEST + '[deps]\n"rhoform/lib" = '
            '{ version = "^0.1.0", path = "../lib" }\n',
            "app/main.rhoform": TOP.replace("./leds", "rhoform/lib/leds"),
            "lib/rhoform.toml": manifest, "lib/leds.rhoform": LED},
            entry="app/main.rhoform")
        self.assertEqual([(d["code"], d["params"]) for d in found], [(
            "RHO2068", {"file": "lib/leds.rhoform",
                        "module": "rhoform.lib.leds"})])
        self.assertNotIn("lib/leds.rhoform",
                         [r.file for r in compilation.results])

    def test_two_packages_never_share_a_module_path(self):
        # Each package's module paths are its own (RHO2069 is a rule within
        # one package): app's leds and parts' leds are two names.
        found, _c, compiled = self.compile({
            "app/rhoform.toml": MANIFEST + '[deps]\n"acme/parts" = '
            '{ version = "^1.0.0", path = "../parts" }\n',
            "app/main.rhoform": (P2 + 'import Led from "acme/parts/leds"\n'
                                 'import Lamp from "./leds"\n\n'
                                 "module Top:\n    led = new Led\n"
                                 "    lamp = new Lamp\n"
                                 "    isolated led.a\n    isolated led.k\n"
                                 "    isolated lamp.a\n"
                                 "    isolated lamp.k\n"),
            "app/leds.rhoform": LED.replace("component Led", "component Lamp"),
            "parts/rhoform.toml": PARTS, "parts/leds.rhoform": LED},
            entry="app/main.rhoform")
        self.assertEqual(found, [])
        self.assertEqual(sorted(i.definition
                                for i in compiled.design.instances),
                         ["acme.app.leds.Lamp", "acme.app.main.Top",
                          "acme.parts.leds.Led"])

    def test_a_module_path_collision_among_files_in_hand(self):
        # elaborate() over parse results it is given resolves their imports
        # itself (package.link); the same files draw the same refusal.
        from rhoform.elaborate import elaborate
        from rhoform.parser import parse

        main = (P2 + 'import Divider from "./a_b/x"\n'
                'import Other from "./a-b/x"\n\nmodule Panel:\n'
                "    port top passive\n    d = new Divider\n"
                "    o = new Other\n    top ~ d.top\n    top ~ o.top\n")
        other = self.DIVIDER.replace("module Divider", "module Other")
        results = [parse(main, file="main.rhoform"),
                   parse(self.DIVIDER, file="a_b/x.rhoform"),
                   parse(other, file="a-b/x.rhoform")]
        elaboration = elaborate(results)
        found = [json.loads(line)
                 for line in elaboration.diagnostics.render().splitlines()]
        self.assertEqual([(d["code"], d["params"]["file"]) for d in found],
                         [("RHO2069", "a-b/x.rhoform")])
        self.assertIsNone(elaboration.design)

    def test_one_file_imported_twice_is_no_module_path_collision(self):
        # The rule is about two FILES: one file named by two spellings of
        # its import path has one module path, and is read once.
        probe = (P2 + 'import Divider from "./a_b/x.rhoform"\n\n'
                 "module Probe:\n    port top passive\n"
                 "    d = new Divider\n    top ~ d.top\n")
        main = (P2 + 'import Divider from "./a_b/x"\n'
                'import Probe from "./probe"\n\nmodule Panel:\n'
                "    port top passive\n    d = new Divider\n"
                "    p = new Probe\n    top ~ d.top\n    top ~ p.top\n")
        found, compilation, elaboration = self.compile(
            {"main.rhoform": main, "probe.rhoform": probe,
             "a_b/x.rhoform": self.DIVIDER})
        self.assertEqual(found, [])
        self.assertEqual(sorted(r.file for r in compilation.results),
                         ["a_b/x.rhoform", "main.rhoform", "probe.rhoform"])
        self.assertIsNotNone(elaboration.design)

    def test_rho2049_manifest_unknown_key(self):
        d, text = self.only({"rhoform.toml": MANIFEST + 'autor = "x"\n',
                             "main.rhoform": TOP}, "RHO2049")
        self.assertEqual(d["params"], {"key": "autor",
                                       "where": "in [package]"})
        self.assertEqual(text, "autor")

    def test_rho2050_manifest_missing_key(self):
        d, text = self.only({"rhoform.toml": MANIFEST.replace(
            'license = "Apache-2.0"\n', ""), "main.rhoform": TOP}, "RHO2050")
        self.assertEqual(d["params"], {"table": "[package]",
                                       "key": "license"})
        self.assertEqual(text, "[package]")

    def test_rho2051_manifest_invalid_value(self):
        d, text = self.only({"rhoform.toml": MANIFEST.replace(
            '"Apache-2.0"', "2"), "main.rhoform": TOP}, "RHO2051")
        self.assertEqual(d["params"], {"key": "package.license",
                                       "expected": "a string",
                                       "found": "an integer"})
        self.assertEqual(text, "2")

    def test_rho2052_invalid_package_name(self):
        d, text = self.only({"rhoform.toml": MANIFEST.replace(
            "acme/app", "acme/App"), "main.rhoform": TOP}, "RHO2052")
        self.assertEqual(d["params"]["name"], "acme/App")
        self.assertEqual(text, '"acme/App"')

    def test_rho2053_invalid_package_version(self):
        d, text = self.only({"rhoform.toml": MANIFEST.replace(
            '"0.1.0"', '"0.1"'), "main.rhoform": TOP}, "RHO2053")
        self.assertEqual(d["params"]["version"], "0.1")
        self.assertEqual(text, '"0.1"')

    def test_rho2054_invalid_version_range(self):
        d, text = self.only({"rhoform.toml": MANIFEST.replace(
            "^0.2.0", ">=0.2.0"), "main.rhoform": TOP}, "RHO2054")
        self.assertEqual(d["params"]["range"], ">=0.2.0")
        self.assertEqual(text, '">=0.2.0"')

    def test_rho2055_reserved_namespace(self):
        d, text = self.only({"rhoform.toml": MANIFEST.replace(
            "acme/app", "rhoform/app"), "main.rhoform": TOP}, "RHO2055")
        self.assertEqual(d["params"], {"name": "rhoform/app",
                                       "namespace": "rhoform"})
        acked = MANIFEST.replace("acme/app", "rho/app") \
            + "reserved-namespace-ack = true\n"
        found, _c, _e = self.compile({"rhoform.toml": acked,
                                      "leds.rhoform": LED})
        self.assertEqual(found, [])

    def test_rho2056_unsupported_dependency(self):
        d, text = self.only({"rhoform.toml": MANIFEST + '[deps]\n'
                             '"acme/parts" = "^1.0.0"\n',
                             "main.rhoform": TOP, "leds.rhoform": LED},
                            "RHO2056")
        self.assertIn("bare version string", d["params"]["problem"])
        self.assertEqual(text, '"^1.0.0"')
        d, text = self.only({"rhoform.toml": MANIFEST + '[deps]\n'
                             '"acme/parts" = { version = "^1.0.0", git = '
                             '"https://example.com/x", rev = '
                             '"0123456789abcdef0123456789abcdef01234567" }\n'},
                            "RHO2056")
        self.assertIn("`git`", d["params"]["problem"])
        self.assertEqual(text, "git")

    def test_rho2057_invalid_path_dependency(self):
        d, text = self.only({
            "app/rhoform.toml": MANIFEST + '[deps]\n"acme/parts" = '
            '{ version = "^2.0.0", path = "../parts" }\n',
            "app/main.rhoform": TOP, "app/leds.rhoform": LED,
            "parts/rhoform.toml": PARTS}, "RHO2057",
            entry="app/main.rhoform")
        self.assertEqual(d["params"]["problem"],
                         "is version 1.2.0, outside `^2.0.0`")
        self.assertEqual(text, '"^2.0.0"')
        d, text = self.only({
            "rhoform.toml": MANIFEST + '[deps]\n"acme/parts" = '
            '{ version = "^1.0.0", path = "../parts" }\n',
            "main.rhoform": TOP, "leds.rhoform": LED}, "RHO2057")
        self.assertIn("outside the compile root", d["params"]["problem"])
        self.assertEqual(text, '"../parts"')

    def test_rho2058_package_excludes_toolchain(self):
        d, text = self.only({"rhoform.toml": MANIFEST.replace(
            "^0.2.0", "^1.0.0"), "main.rhoform": TOP}, "RHO2058")
        self.assertEqual(d["params"], {"package": "acme/app",
                                       "range": "^1.0.0",
                                       "supported": "0.1.0, 0.2.0"})
        self.assertEqual(text, '"^1.0.0"')

    def test_rho2059_pragma_outside_package_range(self):
        d, text = self.only({"rhoform.toml": MANIFEST.replace(
            "^0.2.0", "^0.1.0"), "main.rhoform": TOP}, "RHO2059")
        self.assertEqual(d["params"], {
            "file": "main.rhoform", "version": "0.2.0", "range": "^0.1.0",
            "package": "acme/app", "supported": "0.1.0, 0.2.0"})
        self.assertEqual(text, "#pragma rhoform-syntax 0.2")
        self.assertEqual(d["spans"][1]["file"], "rhoform.toml")

    def test_rho2060_import_not_found(self):
        d, text = self.only({"main.rhoform": TOP}, "RHO2060")
        self.assertEqual(d["params"], {"path": "./leds",
                                       "file": "leds.rhoform"})
        self.assertEqual(text, '"./leds"')

    def test_rho2061_import_escapes_package(self):
        d, text = self.only({"app/main.rhoform": TOP.replace(
            "./leds", "../leds"), "app/rhoform.toml": MANIFEST,
            "leds.rhoform": LED}, "RHO2061", entry="app/main.rhoform")
        self.assertEqual(d["params"], {"path": "../leds",
                                       "boundary": "package `acme/app`"})
        self.assertEqual(text, '"../leds"')

    def test_rho2062_invalid_import_path(self):
        d, text = self.only({"main.rhoform": TOP.replace(
            "./leds", "acme/parts")}, "RHO2062")
        self.assertIn("no module", d["params"]["reason"])

    def test_rho2063_undeclared_package_import(self):
        d, text = self.only({"rhoform.toml": MANIFEST,
                             "main.rhoform": TOP.replace(
                                 "./leds", "acme/parts/leds")}, "RHO2063")
        self.assertEqual(d["params"], {
            "path": "acme/parts/leds", "package": "acme/parts",
            "reason": "package `acme/app` does not list it in [deps]"})

    def test_rho2064_import_cycle(self):
        d, text = self.only({"main.rhoform": TOP, "leds.rhoform": P2
                             + 'import Top from "./main"\n' + LED[len(P2):]},
                            "RHO2064")
        self.assertEqual(d["params"], {"cycle": ["leds.rhoform",
                                                 "main.rhoform"]})
        self.assertEqual(text, '"./main"')
        self.assertEqual(d["spans"][0]["file"], "leds.rhoform")
        self.assertEqual(d["spans"][1]["file"], "main.rhoform")
        d, _t = self.only({"main.rhoform": TOP.replace("./leds", "./main")},
                          "RHO2064")
        self.assertEqual(d["params"], {"cycle": ["main.rhoform"]})

    def test_rho2065_unknown_imported_name(self):
        d, text = self.only({"main.rhoform": TOP.replace("Led", "Lde"),
                             "leds.rhoform": LED}, "RHO2065")
        self.assertEqual(d["params"], {"name": "Lde",
                                       "file": "leds.rhoform"})
        self.assertEqual(text, "Lde")
        self.assertEqual(d["fixits"][0]["edits"][0]["replacement"], "Led")

    def test_rho2066_name_bound_twice(self):
        d, text = self.only({"main.rhoform": TOP + "\ncomponent Led:\n"
                             "    pin a passive\n    pin k passive\n",
                             "leds.rhoform": LED}, "RHO2066")
        self.assertEqual(d["params"], {"name": "Led",
                                       "first": "by its own definition"})
        self.assertEqual(text, "Led")
        d, _t = self.only({"main.rhoform": TOP.replace(
            'import Led from "./leds"',
            'import Led from "./leds"\nimport Led from "./leds.rhoform"'),
            "leds.rhoform": LED}, "RHO2066")
        self.assertEqual(d["params"]["first"], "by an earlier import")


    # ---- the lockfile (R55; spec 08, The lockfile) --------------------------

    @staticmethod
    def lock(document) -> str:
        from rhoform import lockfile

        return lockfile.canonical_bytes(document).decode()

    def tree(self, lock: str) -> dict:
        return {"main.rhoform": TOP, "leds.rhoform": LED,
                "rhoform.lock": lock}

    def test_rho2070_lockfile_not_json(self):
        d, text = self.only(self.tree('{"lockfile_version": 0,}\n'),
                            "RHO2070")
        self.assertEqual(d["params"], {
            "reason": "an object key, a string, is expected here"})
        self.assertEqual((d["spans"][0]["byte_start"], text), (23, ""))

    def test_rho2071_lockfile_not_canonical(self):
        d, text = self.only(self.tree('{"lockfile_version": 0}\n'),
                            "RHO2071")
        self.assertEqual(d["params"], {"line": 1})
        self.assertEqual(text, '{"lockfile_version": 0}')
        self.assertEqual(d["fixits"][0]["edits"][0]["replacement"],
                         '{\n  "lockfile_version": 0\n}\n')

    def test_rho2072_lockfile_version_unsupported(self):
        d, text = self.only(self.tree(self.lock({"lockfile_version": 2})),
                            "RHO2072")
        self.assertEqual(d["params"], {"version": "2", "supported": "0"})
        self.assertEqual(text, "2")

    def test_rho2073_lockfile_invalid(self):
        d, text = self.only(self.tree(self.lock({
            "lockfile_version": 0, "parts": {"inputs": [], "entries": [{
                "key": "k", "manufacturer": "Acme", "mpn": "X",
                "part_id": "acme/x", "record": "x.part.json"}]}})),
            "RHO2073")
        self.assertEqual(d["params"]["pointer"], "/parts/entries/0/record")
        self.assertEqual(text, '"x.part.json"')

    def test_rho2074_lockfile_packages_stale(self):
        from rhoform import lockfile

        recorded = lockfile.digest(b"another manifest")
        files = dict(self.tree(self.lock({
            "lockfile_version": 0, "packages": {
                "inputs": [{"path": "rhoform.toml", "sha256": recorded}],
                "entries": [{
                    "content_hash": None, "manifest": "rhoform.toml",
                    "name": "acme/app", "requires_rhoform": "^0.2.0",
                    "source": {"path": "."},
                    "unavailable_reason": "canonical-archive-unavailable",
                    "version": "0.1.0"}]}})), **{"rhoform.toml": MANIFEST})
        d, text = self.only(files, "RHO2074")
        self.assertEqual(d["params"]["subject"], "rhoform.toml")
        self.assertIn(lockfile.digest(MANIFEST.encode()),
                      d["params"]["problem"])
        self.assertEqual(text, f'"{recorded}"')

    def test_rho2075_lockfile_entry_unsupported(self):
        d, _text = self.only(self.tree(self.lock({
            "lockfile_version": 0, "renames": {"inputs": [], "entries": [{
                "design": "main.Top", "origin": "/old", "path": "/led"}]}})),
            "RHO2075")
        self.assertEqual(d["params"], {
            "pointer": "/renames/entries/0",
            "entry": "a rename-ledger entry",
            "owner": "the rename ledger, R27, AMB-62"})


class LockfileLoadTest(_Tree):
    """The package layer reads the compile root's rhoform.lock, spelled
    exactly so, once the closure is read, and hands it on."""

    def test_the_lockfile_reaches_the_compilation_when_there_is_one(self):
        found, loaded, _compiled = self.compile({"main.rhoform": TOP,
                                                 "leds.rhoform": LED})
        self.assertEqual((found, loaded.lockfile), ([], None))
        found, loaded, compiled = self.compile({
            "rhoform.lock": '{\n  "lockfile_version": 0\n}\n'})
        self.assertEqual(found, [])
        self.assertEqual(loaded.lockfile.document, {"lockfile_version": 0})
        self.assertIsNotNone(compiled.design)

    def test_a_refused_lockfile_stops_the_compilation_before_elaboration(self):
        found, loaded, compiled = self.compile({
            "main.rhoform": TOP, "leds.rhoform": LED,
            "rhoform.lock": "[]\n"})
        self.assertEqual([d["code"] for d in found], ["RHO2072"])
        self.assertFalse(loaded.ok)
        self.assertIsNone(loaded.lockfile)
        self.assertIsNone(compiled.design)

    def test_only_a_file_named_rhoform_lock_exactly_is_read(self):
        found, loaded, _compiled = self.compile({
            "main.rhoform": TOP, "leds.rhoform": LED,
            "RHOFORM.LOCK": "not json"})
        self.assertEqual((found, loaded.lockfile), ([], None))
        (self.tmp / "RHOFORM.LOCK").unlink()
        (self.tmp / "rhoform.lock").mkdir()
        found, loaded, _compiled = self.compile({})
        self.assertEqual((found, loaded.lockfile), ([], None))

    def test_the_lockfile_is_neither_source_nor_hashed(self):
        from rhoform import ir

        _found, _loaded, before = self.compile({"main.rhoform": TOP,
                                                "leds.rhoform": LED})
        _found, _loaded, after = self.compile({
            "rhoform.lock": '{\n  "lockfile_version": 0\n}\n'})
        self.assertEqual(ir.emit(before.design), ir.emit(after.design))


if __name__ == "__main__":
    unittest.main()
