"""rhoform.compile: the one load / elaborate / check composition.

Each stage runs only on what the stage before it accepted, every
diagnostic lands in the caller's sink, and the check stage changes no IR
byte. The elaboration conformance cases are the reference for what the
stages before `check` report, so they are replayed here at every stage.
"""

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
ELABORATE = ROOT / "spec" / "conformance" / "elaborate"

P = "#pragma rhoform-syntax 0.1\n"
CLEAN = P + "\nmodule M:\n    port p passive\n"
BROKEN = P + "\nmodule M:\n    port p passiv\n"
UNKNOWN = P + "\nmodule M:\n    x = new Missing\n"
MANIFEST = ('[package]\nname = "acme/app"\nversion = "0.1.0"\n'
            'requires-rhoform = "^0.2.0"\nlicense = "Apache-2.0"\n')


@unittest.skipUnless(HAVE_LARK, "lark (pinned in toolchain/versions.yaml) "
                     "is required")
class CompileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rhoform-compile-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def compile(self, text, stage, name="m.rhoform", **kwargs):
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics

        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        sink = Diagnostics()
        compilation = pipeline.compile(name, self.tmp, stage=stage,
                                       sink=sink, **kwargs)
        return sink, compilation

    def test_each_stage_stops_where_it_says(self):
        sink, loaded = self.compile(CLEAN, "load")
        self.assertEqual((len(sink), loaded.design, loaded.report),
                         (0, None, None))
        self.assertTrue(loaded.loaded.ok)
        self.assertEqual([r.file for r in loaded.loaded.results],
                         ["m.rhoform"])
        sink, elaborated = self.compile(CLEAN, "elaborate")
        self.assertEqual(len(sink), 0)
        self.assertIsNotNone(elaborated.design)
        self.assertEqual((elaborated.analysis, elaborated.report),
                         (None, None))
        sink, checked = self.compile(CLEAN, "check")
        self.assertIsNotNone(checked.design)
        self.assertIsNotNone(checked.analysis)
        self.assertIsNotNone(checked.report)
        self.assertEqual([d.code for d in sink], ["RHO3901"])

    def test_check_is_the_default_stage(self):
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics

        (self.tmp / "m.rhoform").write_text(CLEAN, encoding="utf-8")
        compilation = pipeline.compile("m.rhoform", self.tmp,
                                       sink=Diagnostics())
        self.assertIsNotNone(compilation.report)

    def test_an_unknown_stage_is_refused(self):
        with self.assertRaises(ValueError):
            self.compile(CLEAN, "emit")

    def test_a_parse_error_stops_before_elaboration(self):
        for stage in ("elaborate", "check"):
            with self.subTest(stage=stage):
                sink, compilation = self.compile(BROKEN, stage)
                self.assertEqual([d.code for d in sink], ["RHO1009"])
                self.assertFalse(compilation.loaded.ok)
                self.assertIsNone(compilation.design)
                self.assertIsNone(compilation.report)

    def test_an_elaboration_error_stops_before_the_check_stage(self):
        sink, compilation = self.compile(UNKNOWN, "check")
        self.assertEqual([d.code for d in sink], ["RHO2005"])
        self.assertIsNone(compilation.design)
        self.assertIsNone(compilation.report)

    def test_the_check_stage_changes_no_ir_byte(self):
        from rhoform import ir

        name = "a03_unlabelled_and_isolated_nets.rhoform"
        source = (ELABORATE / "accept" / name).read_text(encoding="utf-8")
        _sink, elaborated = self.compile(source, "elaborate", name=name)
        before = ir.emit(elaborated.design)
        _sink, checked = self.compile(source, "check", name=name)
        self.assertEqual(ir.emit(checked.design), before)
        self.assertEqual(before[0], (ELABORATE / "accept" /
                                     "a03_unlabelled_and_isolated_nets"
                                     ".expected.ir.json").read_bytes())

    def test_elaboration_reject_streams_are_the_same_at_every_stage(self):
        # The check stage never runs after an elaboration error, so an
        # elaboration case that fails pins the same stream at stage=check;
        # a warnings-only case elaborates, and its check stage adds only
        # check-stage codes after the elaborator's.
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics

        cases = sorted((ELABORATE / "reject").glob("*.rhoform"))
        self.assertTrue(cases)
        for case in cases:
            expected = case.with_name(case.name[:-len(".rhoform")]
                                      + ".expected.ndjson").read_text(
                                          encoding="utf-8")
            with self.subTest(case=case.name):
                streams = {}
                for stage in ("elaborate", "check"):
                    sink = Diagnostics()
                    compilation = pipeline.compile(
                        case.name, case.parent, stage=stage, sink=sink)
                    streams[stage] = sink
                self.assertEqual(streams["elaborate"].render(), expected)
                if compilation.design is None:
                    self.assertEqual(streams["check"].render(), expected)
                else:
                    added = [d.code for d in streams["check"]
                             if d.code[3] not in "12"]
                    self.assertEqual(
                        len(streams["check"]),
                        len(streams["elaborate"]) + len(added))

    def test_root_module_reaches_the_elaborator(self):
        two = P + "\nmodule A:\n    port p passive\n\nmodule B:\n" \
            "    port q passive\n"
        sink, compilation = self.compile(two, "elaborate")
        self.assertEqual([d.code for d in sink], ["RHO2002"])
        sink, compilation = self.compile(two, "elaborate", root_module="B")
        self.assertEqual(len(sink), 0)
        self.assertEqual(compilation.design.design_name, "B")

    def test_through_reaches_the_check_stage(self):
        _sink, compilation = self.compile(CLEAN, "check", through="model")
        self.assertEqual(list(compilation.report.sections), ["model"])
        with self.assertRaises(ValueError):
            self.compile(CLEAN, "check", through="nonesuch")

    def test_a_manifest_governed_file_is_named_by_its_package(self):
        # AMB-144 item 1: the package layer names the file, the elaborator
        # names its definitions after it.
        (self.tmp / "rhoform.toml").write_text(MANIFEST, encoding="utf-8")
        text = "#pragma rhoform-syntax 0.2\n\nmodule Board:\n" \
            "    port p passive\n"
        _sink, compilation = self.compile(text, "elaborate",
                                          name="boards/main.rhoform")
        self.assertEqual(compilation.loaded.modules,
                         {"boards/main.rhoform": "acme.app.boards.main"})
        self.assertEqual(compilation.design.instances[0].definition,
                         "acme.app.boards.main.Board")
