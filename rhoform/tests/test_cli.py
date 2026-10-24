"""The command line (R18 / AMB-49; decision record C-1..C-6).

Most cases run `rhoform.cli.main` in-process with stdout and stderr
captured; a few run `python3 -m rhoform` as a real subprocess, where only a
process boundary can show the property (concurrent writers, and an audit
hook watching every file the run opens). The command line is held to the
reference implementation through the committed artifacts: `check --emit-ir`
must reproduce every elaboration accept case's expected IR and every
benchmark golden byte for byte, and its stream must be exactly what
rhoform.compile reports. What the elaboration cases pin is the elaborator's,
so the tests that compare streams and IR with them compile in-process at
stage=elaborate; `check` runs the static stage too, whose coverage note
every check-stage run carries until M2's passes land (amendment OD1), and
whose benchmark output is pinned in test_benchmarks.py alone.

Every compilation here has its compile root inside the test's temporary
directory: the root is passed with --compile-root, or found by a walk
bounded to that directory, so a rhoform.toml or rhoform.lock above the
checkout cannot move it (AMB-142 #12). A benchmark is copied into a
compile root of its own, as its directory is.

Every test skips without lark, as test_parser.py does; the cases that
compile need jsonschema too, which the CI job running rhoform/tests pins.
"""

import io
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
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

SKIP = "lark and jsonschema (pinned in toolchain/versions.yaml) are required"
ROOT = Path(__file__).resolve().parents[2]
ELABORATE = ROOT / "spec" / "conformance" / "elaborate"

COVERAGE_NOTE = "RHO3901"

P = "#pragma rhoform-syntax 0.1\n"
CLEAN = P + "\nmodule M:\n    port p passive\n"
NONCANONICAL = P + "module M:\n  port p passive\n"
BROKEN = P + "\nmodule M:\n    port p passiv\n"
TWO_ROOTS = (P + "\nmodule A:\n    port p passive\n"
             "\nmodule B:\n    port q passive\n")
MANIFEST = ('[package]\nname = "acme/app"\nversion = "0.1.0"\n'
            'requires-rhoform = "^0.1.0"\nlicense = "Apache-2.0"\n')
P2 = "#pragma rhoform-syntax 0.2\n"
LIBRARY = P2 + "\ncomponent Led:\n    pin a passive\n    pin k passive\n"
IMPORTER = (P2 + '\nimport Led from "./lib"\n\nmodule {name}:\n'
            "    d = new Led\n    d.a ~ d.k\n")
STATIC_ASSERTION = (P + "\nmodule M:\n    port vin power_in\n"
                    "    net VIN:\n        vin\n"
                    "    assert vin_ok static operating_point(VIN) "
                    "within 4.5V to 5.5V\n")


def run(*argv, stdin: bytes | None = None):
    """(exit code, stdout, stderr) of one in-process invocation."""
    from rhoform import cli

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        if stdin is None:
            code = cli.main([str(arg) for arg in argv])
        else:
            wrapper = io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")
            with mock.patch.object(sys, "stdin", wrapper):
                code = cli.main([str(arg) for arg in argv])
    return code, out.getvalue(), err.getvalue()


def lines(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines()]


def checked(stdout: str) -> list[dict]:
    """The stream less the static stage's coverage note, which every
    check-stage run carries while passes are unimplemented."""
    return [d for d in lines(stdout) if d["code"] != COVERAGE_NOTE]


def exit_of(stdout: str) -> int:
    """The exit code a stream implies: 1 with an error in it, else 0."""
    return int(any(d["severity"] == "error" for d in lines(stdout)))


def copy_benchmarks(directory: Path) -> list[tuple[Path, Path]]:
    """Each benchmark copied into a compile root of its own under
    `directory`, as it compiles in place: (root, entry) pairs. The
    benchmark's rhoform.lock comes along when it has one."""
    from rhoform.tests.test_benchmarks import sources

    copied = []
    for source in sources():
        root = directory / source.parent.name
        root.mkdir(parents=True)
        shutil.copy(source, root / source.name)
        if (source.parent / "rhoform.lock").is_file():
            shutil.copy(source.parent / "rhoform.lock", root)
        copied.append((root, root / source.name))
    return copied


def snapshot(directory: Path) -> dict:
    """Every file under `directory` with its bytes, mode and mtime."""
    found = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            info = path.stat()
            found[path.relative_to(directory).as_posix()] = (
                path.read_bytes(), stat.S_IMODE(info.st_mode),
                info.st_mtime_ns, info.st_ino)
    return found


class _Tmp(unittest.TestCase):
    def setUp(self):
        from rhoform import cli

        self.tmp = Path(tempfile.mkdtemp(prefix="rhoform-cli-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # The compile-root walk stops at this directory: a manifest or
        # lockfile above it belongs to the host, not to the test.
        real, top = cli._holds, os.path.realpath(self.tmp)

        def bounded(directory, name):
            here = os.path.realpath(directory)
            return (here == top or here.startswith(top + os.sep)) \
                and real(directory, name)

        patcher = mock.patch.object(cli, "_holds", bounded)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, rel: str, text: str) -> Path:
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path


def compiled(case: Path, stage: str):
    """(stream, Compilation) of one elaboration case compiled in-process,
    its directory the compile root, as the conformance suite compiles it."""
    from rhoform import compile as pipeline
    from rhoform.diagnostics import Diagnostics

    sink = Diagnostics()
    compilation = pipeline.compile(case.name, case.parent, stage=stage,
                                   sink=sink)
    return sink.render(), compilation


@unittest.skipUnless(HAVE_LARK and HAVE_JSONSCHEMA, SKIP)
class CheckTest(_Tmp):
    def test_clean_file_exits_zero_with_only_the_coverage_note(self):
        # Every pass a stub, whichever have landed: the note is all.
        from rhoform.tests.test_check import planted

        with planted():
            code, out, err = run("check", "--compile-root", self.tmp,
                                 self.write("m.rhoform", CLEAN))
        self.assertEqual((code, err, checked(out)), (0, "", []))
        self.assertEqual([(d["code"], d["severity"]) for d in lines(out)],
                         [(COVERAGE_NOTE, "note")])

    def test_a_clean_file_elaborates_with_an_empty_stream(self):
        # The M1-era form of the test above: through elaboration the
        # stream of a clean file is empty, and the design is there.
        stream, compilation = compiled(self.write("m.rhoform", CLEAN),
                                       "elaborate")
        self.assertEqual(stream, "")
        self.assertIsNotNone(compilation.design)
        self.assertIsNone(compilation.report)

    def test_errors_exit_one_as_ndjson_with_root_relative_files(self):
        code, out, err = run("check", "--compile-root", self.tmp / "sub",
                             self.write("sub/m.rhoform", BROKEN))
        self.assertEqual((code, err), (1, ""))
        self.assertEqual([d["code"] for d in lines(out)], ["RHO1009"])
        self.assertEqual(lines(out)[0]["spans"][0]["file"], "m.rhoform")

    def test_reject_cases_reproduce_their_expected_streams(self):
        cases = sorted((ELABORATE / "reject").glob("*.rhoform"))
        self.assertTrue(cases)
        for case in cases:
            with self.subTest(case=case.name):
                stream, _compilation = compiled(case, "elaborate")
                expected = case.with_name(
                    case.name[:-len(".rhoform")] + ".expected.ndjson")
                self.assertEqual(stream, expected.read_text(encoding="utf-8"))

    def test_check_reports_exactly_what_the_pipeline_does(self):
        # The command line is a shell over rhoform.compile: its stream for
        # each reject case is the pipeline's at stage=check (a warnings-only
        # case elaborates, so its check stage runs too), and its exit code
        # is what that stream implies.
        for case in sorted((ELABORATE / "reject").glob("*.rhoform")):
            with self.subTest(case=case.name):
                code, out, _err = run("check", "--compile-root", case.parent,
                                      case)
                stream, _compilation = compiled(case, "check")
                self.assertEqual(out, stream)
                self.assertEqual(code, exit_of(out))

    def test_accept_cases_elaborate_to_their_expected_ir(self):
        from rhoform import ir

        cases = sorted((ELABORATE / "accept").glob("*.rhoform"))
        self.assertTrue(cases)
        for case in cases:
            stem = case.name[:-len(".rhoform")]
            with self.subTest(case=stem):
                stream, compilation = compiled(case, "elaborate")
                self.assertEqual(stream, "")
                self.assertEqual(
                    ir.emit(compilation.design)[0],
                    case.with_name(f"{stem}.expected.ir.json").read_bytes())

    def test_emit_ir_writes_the_ir_whatever_the_check_stage_finds(self):
        # A declared static-tier assertion is an RHO3553 error while the
        # assertions pass is unimplemented (pinned as such here, with
        # stand-in passes, whatever the real passes' state): the run exits
        # 1, and the IR of the design, which elaborated, is still written.
        from rhoform import compile as pipeline
        from rhoform.diagnostics import Diagnostics
        from rhoform.tests.test_check import planted

        entry = self.write("m.rhoform", STATIC_ASSERTION)
        with planted():
            code, out, err = run("check", "--compile-root", self.tmp,
                                 "--emit-ir", self.tmp / "out", entry)
            compilation = pipeline.compile("m.rhoform", self.tmp,
                                           sink=Diagnostics())
        self.assertEqual((code, err), (1, ""))
        self.assertIn(("RHO3553", "/vin_ok", "static"),
                      [(d["code"], d["entity"], d["tier"])
                       for d in lines(out)])
        from rhoform import ir

        self.assertEqual((self.tmp / "out" / "m.ir.json").read_bytes(),
                         ir.emit(compilation.design)[0])

    def test_emit_ir_reproduces_every_benchmark_golden(self):
        from rhoform.tests.test_benchmarks import goldens, sources

        self.assertTrue(sources())
        for (root, entry), source in zip(copy_benchmarks(self.tmp / "src"),
                                         sources()):
            out = self.tmp / "ir" / source.parent.name
            with self.subTest(benchmark=source.parent.name):
                code, stdout, err = run("check", "--compile-root", root,
                                        "--emit-ir", out, entry)
                self.assertEqual((code, err), (exit_of(stdout), ""))
                written = sorted(p.name for p in out.iterdir())
                self.assertEqual(written, sorted(g.name for g in
                                                 goldens(source)))
                for golden in goldens(source):
                    self.assertTrue((out / golden.name).read_bytes()
                                    == golden.read_bytes(),
                                    f"{golden.name} differs")

    def test_check_never_writes_without_emit_ir(self):
        copy_benchmarks(self.tmp)
        self.write("bad.rhoform", BROKEN)
        before = snapshot(self.tmp)
        code, _out, _err = run("check", self.tmp)
        self.assertEqual(code, 1)
        self.assertEqual(snapshot(self.tmp), before)

    def test_emit_report_writes_each_check_report(self):
        from rhoform import ir
        from rhoform.check import report as check_report

        entry = self.write("m.rhoform", CLEAN)
        bad = self.write("bad.rhoform", BROKEN)
        code, out, err = run("check", "--compile-root", self.tmp,
                             "--emit-report", self.tmp / "reports",
                             "--emit-ir", self.tmp / "ir", entry, bad)
        self.assertEqual((code, err), (1, ""))
        # Only the entry the check stage ran on has a report.
        self.assertEqual(sorted(p.name for p in
                                (self.tmp / "reports").iterdir()),
                         ["m.check.json"])
        data = (self.tmp / "reports" / "m.check.json").read_bytes()
        document = json.loads(data)
        self.assertEqual(data, ir.canonical_bytes(document))
        self.assertIsNone(check_report.schema_problem(document))
        self.assertEqual(
            document["design_hash"],
            json.loads((self.tmp / "ir" / "m.ir.json").read_bytes())
            ["header"]["design_hash"])

    def test_a_check_report_the_schema_rejects_is_internal_never_written(self):
        entry = self.write("m.rhoform", CLEAN)
        with mock.patch("rhoform.check.report.schema_problem",
                        return_value="planted"):
            code, _out, err = run("check", "--compile-root", self.tmp,
                                  "--emit-report", self.tmp / "out", entry)
        self.assertEqual(code, 2)
        self.assertIn("INTERNAL: the check report", err)
        self.assertFalse((self.tmp / "out").exists())

    def test_a_report_without_jsonschema_is_unavailable(self):
        entry = self.write("m.rhoform", CLEAN)
        with mock.patch("rhoform.check.report.schema_problem",
                        side_effect=ImportError("planted")):
            code, _out, err = run("check", "--compile-root", self.tmp,
                                  "--emit-report", self.tmp / "out", entry)
        self.assertEqual(code, 2)
        self.assertIn("UNAVAILABLE", err)
        self.assertFalse((self.tmp / "out").exists())

    def test_a_directory_expands_to_its_sources_in_sorted_order(self):
        self.write("d/b/z.rhoform", BROKEN)
        self.write("d/a.rhoform", BROKEN)
        self.write("d/notes.txt", BROKEN)
        code, out, _err = run("check", self.tmp / "d")
        self.assertEqual(code, 1)
        self.assertEqual([d["spans"][0]["file"] for d in lines(out)],
                         ["a.rhoform", "z.rhoform"])

    def test_a_directory_with_no_sources_is_a_usage_error(self):
        (self.tmp / "empty").mkdir()
        code, out, err = run("check", self.tmp / "empty")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no *.rhoform file", err)

    def test_compile_root_is_the_nearest_manifest_ancestor(self):
        self.write("pkg/rhoform.toml", MANIFEST)
        entry = self.write("pkg/boards/main.rhoform", CLEAN)
        code, _out, _err = run("check", "--emit-ir", self.tmp / "out", entry)
        self.assertEqual(code, 0)
        document = json.loads((self.tmp / "out" / "main.ir.json").read_text())
        source_map = json.loads(
            (self.tmp / "out" / "main.sourcemap.json").read_text())
        self.assertEqual([f["path"] for f in source_map["files"]],
                         ["boards/main.rhoform"])
        # A file a manifest governs is named by its package's identity
        # first (AMB-144 item 1).
        self.assertEqual(document["instances"][0]["definition"],
                         "acme.app.boards.main.M")
        code, out, _err = run("check", self.write("pkg/boards/bad.rhoform",
                                                  BROKEN))
        self.assertEqual(lines(out)[0]["spans"][0]["file"],
                         "boards/bad.rhoform")

    def test_only_a_file_named_rhoform_toml_exactly_is_a_manifest(self):
        # A case-insensitive file system also answers for RHOFORM.TOML;
        # Linux does not, and the compile root may not depend on the host.
        from rhoform import cli

        self.write("pkg/RHOFORM.TOML", MANIFEST)
        entry = self.write("pkg/boards/main.rhoform", CLEAN)
        self.assertEqual(cli.compile_root(entry), cli._absolute(entry.parent))

    def test_a_lockfile_ancestor_is_the_compile_root_ahead_of_a_manifest(self):
        # The workspace root (AMB-144 item 2): the nearest rhoform.lock wins
        # over a nearer rhoform.toml, so sibling path dependencies compile
        # without --compile-root. Only its presence counts: it is not read.
        from rhoform import cli

        self.write("ws/rhoform.lock", "not read\n")
        self.write("ws/app/rhoform.toml", MANIFEST)
        entry = self.write("ws/app/boards/main.rhoform", CLEAN)
        self.assertEqual(cli.compile_root(entry), cli._absolute(self.tmp / "ws"))
        code, out, _err = run("check", self.write("ws/app/boards/bad.rhoform",
                                                  BROKEN))
        self.assertEqual(code, 1)
        self.assertEqual(lines(out)[0]["spans"][0]["file"],
                         "app/boards/bad.rhoform")
        # Without the lockfile, the manifest's directory is the root again,
        # and without either, the entry's own directory.
        (self.tmp / "ws" / "rhoform.lock").unlink()
        self.assertEqual(cli.compile_root(entry),
                         cli._absolute(self.tmp / "ws" / "app"))
        (self.tmp / "ws" / "app" / "rhoform.toml").unlink()
        self.assertEqual(cli.compile_root(entry), cli._absolute(entry.parent))

    def test_only_a_file_named_rhoform_lock_exactly_marks_the_workspace(self):
        from rhoform import cli

        self.write("ws/RHOFORM.LOCK", "not read\n")
        entry = self.write("ws/app/main.rhoform", CLEAN)
        self.assertEqual(cli.compile_root(entry), cli._absolute(entry.parent))
        # A directory named rhoform.lock is no lockfile either.
        (self.tmp / "ws" / "app" / "rhoform.lock").mkdir()
        self.assertEqual(cli.compile_root(entry), cli._absolute(entry.parent))

    def test_explicit_compile_root_wins_and_must_contain_the_entry(self):
        self.write("pkg/rhoform.toml", MANIFEST)
        entry = self.write("pkg/boards/bad.rhoform", BROKEN)
        code, out, _err = run("check", "--compile-root", self.tmp, entry)
        self.assertEqual(code, 1)
        self.assertEqual(lines(out)[0]["spans"][0]["file"],
                         "pkg/boards/bad.rhoform")
        code, out, err = run("check", "--compile-root", self.tmp / "pkg" /
                             "boards", self.write("elsewhere.rhoform", CLEAN))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("not under the compile root", err)

    def test_a_root_named_through_a_symlink_still_contains_its_files(self):
        # macOS's /tmp is a symlink to /private/tmp, and os.getcwd()
        # returns the resolved spelling, so a relative entry and a root
        # spelled through the link disagree lexically while naming one
        # directory.
        entry = self.write("real/sub/bad.rhoform", BROKEN)
        (self.tmp / "link").symlink_to(self.tmp / "real")
        code, out, err = run("check", "--compile-root", self.tmp / "link",
                             entry)
        self.assertEqual((code, err), (1, ""))
        self.assertEqual(lines(out)[0]["spans"][0]["file"],
                         "sub/bad.rhoform")

    def test_root_module_selects_the_root_and_names_an_unknown_one(self):
        entry = self.write("two.rhoform", TWO_ROOTS)
        code, out, _err = run("check", entry)
        self.assertEqual([d["code"] for d in lines(out)], ["RHO2002"])
        code, out, _err = run("check", "--root-module", "B", "--emit-ir",
                              self.tmp / "out", entry)
        self.assertEqual((code, checked(out)), (0, []))
        document = json.loads((self.tmp / "out" / "two.ir.json").read_text())
        self.assertEqual(document["header"]["design_name"], "B")
        code, out, _err = run("check", "--root-module", "C", entry)
        self.assertEqual(code, 1)
        self.assertEqual([d["code"] for d in lines(out)], ["RHO2003"])

    def test_unreadable_file_exits_two_and_still_reports_the_rest(self):
        code, out, err = run("check", self.tmp / "missing.rhoform",
                             self.write("bad.rhoform", BROKEN))
        self.assertEqual(code, 2)
        self.assertEqual([d["code"] for d in lines(out)], ["RHO1009"])
        self.assertIn("cannot read", err)

    def test_missing_jsonschema_is_unavailable_not_a_pass(self):
        entry = self.write("m.rhoform", CLEAN)
        with mock.patch.dict(sys.modules, {"jsonschema": None}):
            code, out, err = run("check", "--emit-ir", self.tmp / "out",
                                 entry)
            self.assertEqual((code, checked(out)), (2, []))
            self.assertIn("UNAVAILABLE", err)
            self.assertFalse((self.tmp / "out").exists())
            # No IR, nothing to validate: the errors are the whole answer.
            code, _out, _err = run("check", self.write("b.rhoform", BROKEN))
            self.assertEqual(code, 1)

    def test_ir_the_schema_rejects_is_an_internal_error_never_written(self):
        entry = self.write("m.rhoform", CLEAN)
        with mock.patch("rhoform.ir.emit", return_value=(b"{}\n", b"{}\n")):
            code, out, err = run("check", "--emit-ir", self.tmp / "out",
                                 entry)
        self.assertEqual((code, checked(out)), (2, []))
        self.assertIn("does not validate", err)
        self.assertFalse((self.tmp / "out").exists())

    def test_missing_lark_is_unavailable(self):
        from rhoform.parser import LarkUnavailable

        with mock.patch("rhoform.parser._load",
                        side_effect=LarkUnavailable("no lark")):
            code, out, err = run("check", self.write("m.rhoform", CLEAN))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("UNAVAILABLE", err)

    def test_emit_ir_refuses_two_entries_with_one_stem(self):
        code, out, err = run("check", "--emit-ir", self.tmp / "out",
                             self.write("a/m.rhoform", CLEAN),
                             self.write("b/m.rhoform", CLEAN))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("m.ir.json", err)
        self.assertFalse((self.tmp / "out").exists())

    def test_stems_that_differ_only_in_case_are_one_stem(self):
        # On a case-insensitive file system M.ir.json and m.ir.json are one
        # file (AMB-142 item 11), and so are two check reports.
        for flag, suffix in (("--emit-ir", ".ir.json"),
                             ("--emit-report", ".check.json")):
            with self.subTest(flag=flag):
                code, out, err = run("check", flag, self.tmp / "out",
                                     self.write("a/m.rhoform", CLEAN),
                                     self.write("b/M.rhoform", CLEAN))
                self.assertEqual((code, out), (2, ""))
                self.assertIn(f"M{suffix} for both", err)
                self.assertFalse((self.tmp / "out").exists())

    def test_an_unreadable_subdirectory_stops_the_run_naming_it(self):
        # A sweep that skipped it would pass over files it never read
        # (AMB-142 item 10): `check DIR` and `fmt --check DIR` exit 2.
        self.write("d/a.rhoform", CLEAN)
        self.write("d/locked/b.rhoform", BROKEN)
        locked = self.tmp / "d" / "locked"
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        if os.access(locked, os.R_OK):
            self.skipTest("this user can read a mode-0 directory (root)")
        for argv in (("check", self.tmp / "d"),
                     ("fmt", "--check", self.tmp / "d")):
            with self.subTest(command=argv[0]):
                code, out, err = run(*argv)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(f"cannot list {locked}", err)

    def test_an_entry_compiles_with_the_files_it_imports(self):
        self.write("pkg/rhoform.toml", MANIFEST.replace("^0.1.0", "^0.2.0"))
        self.write("pkg/lib.rhoform", LIBRARY)
        entry = self.write("pkg/main.rhoform", IMPORTER.format(name="Main"))
        code, out, _err = run("check", "--emit-ir", self.tmp / "out", entry)
        self.assertEqual((code, checked(out)), (0, []))
        source_map = json.loads(
            (self.tmp / "out" / "main.sourcemap.json").read_text())
        self.assertEqual([f["path"] for f in source_map["files"]],
                         ["lib.rhoform", "main.rhoform"])
        # The manifest is real now: one that is not TOML stops the check.
        self.write("pkg/rhoform.toml", "[package\n")
        code, out, _err = run("check", entry)
        self.assertEqual([(d["code"], d["spans"][0]["file"])
                          for d in lines(out)],
                         [("RHO2048", "rhoform.toml")])

    def test_a_directory_checks_its_entries_not_their_libraries(self):
        self.write("d/lib.rhoform", LIBRARY.replace("pin k", "pin k pasive"))
        self.write("d/a.rhoform", IMPORTER.format(name="A"))
        self.write("d/b.rhoform", IMPORTER.format(name="B"))
        code, out, _err = run("check", self.tmp / "d")
        # lib.rhoform is no entry (it defines no module, which would be
        # RHO2047), and its defect is reported once, not per importer.
        self.assertEqual(code, 1)
        self.assertEqual([(d["code"], d["spans"][0]["file"])
                          for d in lines(out)],
                         [("RHO1009", "lib.rhoform")])
        # Named on the command line, a library is an entry like any file.
        code, out, _err = run("check", self.tmp / "d",
                              self.tmp / "d" / "lib.rhoform")
        self.assertEqual(sorted(d["code"] for d in lines(out)),
                         ["RHO1009"])
        self.write("d/lib.rhoform", LIBRARY)
        code, out, _err = run("check", "--emit-ir", self.tmp / "out",
                              self.tmp / "d")
        self.assertEqual((code, checked(out)), (0, []))
        self.assertEqual(sorted(p.name for p in (self.tmp / "out").iterdir()),
                         ["a.ir.json", "a.sourcemap.json", "b.ir.json",
                          "b.sourcemap.json"])

    def test_files_that_import_each_other_are_still_checked(self):
        self.write("c/x.rhoform", P2 + '\nimport Y from "./y"\n\n'
                   "component X:\n    pin p passive\n")
        self.write("c/y.rhoform", P2 + '\nimport X from "./x"\n\n'
                   "component Y:\n    pin p passive\n")
        code, out, _err = run("check", self.tmp / "c")
        self.assertEqual(code, 1)
        # Both are entries, and both compilations meet the one cycle: it
        # is reported once, whichever file each started from.
        self.assertEqual([d["code"] for d in lines(out)], ["RHO2064"])

    def test_an_unreadable_import_exits_two(self):
        self.write("lib.rhoform", LIBRARY)
        entry = self.write("main.rhoform", IMPORTER.format(name="Main"))
        from rhoform import package

        real = package._Loader.read

        def read(loader, key):
            if key == "lib.rhoform":
                raise package.ReadFailure(loader.root / key,
                                          OSError("planted"))
            return real(loader, key)

        with mock.patch.object(package._Loader, "read", read):
            code, out, err = run("check", entry)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("cannot read", err)

    def test_usage_errors_exit_two(self):
        for argv in ([], ["check"], ["frobnicate", "x"],
                     ["fmt", "--dry-run", "x.rhoform"]):
            with self.subTest(argv=argv):
                code, out, _err = run(*argv)
                self.assertEqual((code, out), (2, ""))


@unittest.skipUnless(HAVE_LARK and HAVE_JSONSCHEMA, SKIP)
class FmtTest(_Tmp):
    def test_rewrites_in_place_keeping_the_mode(self):
        path = self.write("m.rhoform", NONCANONICAL)
        path.chmod(0o640)
        self.assertEqual(run("fmt", path), (0, "", ""))
        self.assertEqual(path.read_text(), CLEAN)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                         ["m.rhoform"])

    def test_a_canonical_file_is_not_rewritten(self):
        path = self.write("m.rhoform", CLEAN)
        before = snapshot(self.tmp)
        self.assertEqual(run("fmt", path), (0, "", ""))
        self.assertEqual(snapshot(self.tmp), before)

    def test_a_file_that_does_not_parse_is_refused_untouched(self):
        bad = self.write("bad.rhoform", BROKEN)
        good = self.write("good.rhoform", NONCANONICAL)
        before = snapshot(self.tmp)["bad.rhoform"]
        code, out, _err = run("fmt", bad, good)
        self.assertEqual(code, 1)
        self.assertEqual([d["code"] for d in lines(out)], ["RHO1009"])
        self.assertEqual(snapshot(self.tmp)["bad.rhoform"], before)
        self.assertEqual(good.read_text(), CLEAN)

    def test_check_writes_nothing_and_names_the_first_differing_line(self):
        self.write("a.rhoform", NONCANONICAL)
        self.write("b.rhoform", CLEAN)
        self.write("c.rhoform", CLEAN + "\n\n")
        before = snapshot(self.tmp)
        code, out, _err = run("fmt", "--check", self.tmp)
        self.assertEqual(code, 1)
        self.assertEqual(snapshot(self.tmp), before)
        found = [(d["code"], d["severity"], d["category"],
                  d["spans"][0]["file"], d["spans"][0]["line_start"],
                  d["spans"][0]["byte_start"], d["spans"][0]["byte_end"])
                 for d in lines(out)]
        cut = len(CLEAN)
        self.assertEqual(found, [
            # The pragma is followed by `module M:` where a blank line
            # belongs: line 2 is the first that differs.
            ("RHO1017", "error", "syntax", "a.rhoform", 2, len(P),
             len(P) + len("module M:")),
            # Surplus blank lines at the end: the first one is spanned by
            # its own line feed.
            ("RHO1017", "error", "syntax", "c.rhoform", 5, cut, cut + 1),
        ])

    def test_check_passes_on_canonical_files(self):
        self.write("b.rhoform", CLEAN)
        self.assertEqual(run("fmt", "--check", self.tmp), (0, "", ""))

    def test_check_reports_a_missing_final_newline_at_the_last_line(self):
        self.write("a.rhoform", CLEAN[:-1])
        code, out, _err = run("fmt", "--check", self.tmp)
        self.assertEqual(code, 1)
        span = lines(out)[0]["spans"][0]
        self.assertEqual((span["line_start"], span["byte_start"],
                          span["byte_end"]),
                         (4, CLEAN.rindex("    port"), len(CLEAN) - 1))

    def test_a_formatter_self_check_failure_is_exit_two_and_unwritten(self):
        from rhoform.fmt import FormatterError

        path = self.write("m.rhoform", NONCANONICAL)
        before = snapshot(self.tmp)
        with mock.patch("rhoform.fmt.format_source",
                        side_effect=FormatterError("planted")):
            code, out, err = run("fmt", path)
            self.assertEqual((code, out), (2, ""))
            self.assertIn("self-check", err)
            code, out, _err = run("fmt", "--stdin", path,
                                  stdin=NONCANONICAL.encode())
            self.assertEqual((code, out), (2, ""))
        self.assertEqual(snapshot(self.tmp), before)


@unittest.skipUnless(HAVE_LARK and HAVE_JSONSCHEMA, SKIP)
class WriteGateTest(_Tmp):
    """`fmt --stdin TARGET`, the A2 write gate (C-4)."""

    def test_accept_replaces_target_and_echoes_the_canonical_bytes(self):
        target = self.write("m.rhoform", BROKEN)
        target.chmod(0o600)
        code, out, err = run("fmt", "--stdin", target,
                             stdin=NONCANONICAL.encode())
        self.assertEqual((code, out, err), (0, CLEAN, ""))
        self.assertEqual(target.read_bytes(), out.encode())
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                         ["m.rhoform"])

    def test_accept_creates_a_new_target(self):
        target = self.tmp / "new.rhoform"
        code, out, _err = run("fmt", "--stdin", target,
                              stdin=CLEAN.encode())
        self.assertEqual((code, out), (0, CLEAN))
        self.assertEqual(target.read_text(), CLEAN)

    def test_an_unchanged_target_is_not_rewritten(self):
        target = self.write("m.rhoform", CLEAN)
        before = snapshot(self.tmp)
        self.assertEqual(run("fmt", "--stdin", target,
                             stdin=NONCANONICAL.encode())[:2], (0, CLEAN))
        self.assertEqual(snapshot(self.tmp), before)

    def test_reject_leaves_target_untouched_and_prints_ndjson(self):
        target = self.write("sub/m.rhoform", CLEAN)
        before = snapshot(self.tmp)
        code, out, _err = run("fmt", "--stdin", target, stdin=BROKEN.encode())
        self.assertEqual(code, 1)
        diagnostics = lines(out)
        self.assertEqual([d["code"] for d in diagnostics], ["RHO1009"])
        self.assertEqual(diagnostics[0]["spans"][0]["file"], "m.rhoform")
        self.assertEqual(snapshot(self.tmp), before)

    def test_invalid_utf8_is_diagnosed_not_crashed_on(self):
        target = self.write("m.rhoform", CLEAN)
        code, out, _err = run("fmt", "--stdin", target,
                              stdin=CLEAN.encode() + b"# \xff\n")
        self.assertEqual(code, 1)
        self.assertEqual([d["code"] for d in lines(out)], ["RHO1002"])
        self.assertEqual(target.read_text(), CLEAN)

    def test_dry_run_never_touches_target(self):
        target = self.write("m.rhoform", BROKEN)
        before = snapshot(self.tmp)
        self.assertEqual(run("fmt", "--stdin", "--dry-run", target,
                             stdin=NONCANONICAL.encode()), (0, CLEAN, ""))
        code, out, _err = run("fmt", "--stdin", "--dry-run", target,
                              stdin=BROKEN.encode())
        self.assertEqual(code, 1)
        self.assertEqual([d["code"] for d in lines(out)], ["RHO1009"])
        self.assertEqual(snapshot(self.tmp), before)

    def test_filter_mode_usage_errors(self):
        target = self.write("m.rhoform", CLEAN)
        for argv in (["--stdin", target, target],
                     ["--stdin", "--check", target],
                     ["--stdin", self.tmp]):
            with self.subTest(argv=argv):
                code, out, _err = run("fmt", *argv, stdin=CLEAN.encode())
                self.assertEqual((code, out), (2, ""))
        self.assertEqual(target.read_text(), CLEAN)


def _child(argv, prelude=""):
    """The command line of `python3 -m rhoform ARGV` in a child, run after
    `prelude`, with the repository importable from any working directory."""
    runner = (
        "import runpy, sys\n" + prelude +
        "sys.argv = ['rhoform'] + sys.argv[1:]\n"
        "runpy.run_module('rhoform', run_name='__main__', alter_sys=True)\n")
    return [sys.executable, "-c", runner, *map(str, argv)]


def _env():
    return dict(os.environ, PYTHONPATH=str(ROOT))


def _subprocess(argv, cwd, stdin=None, prelude=""):
    return subprocess.run(_child(argv, prelude), cwd=cwd, env=_env(),
                          input=stdin, capture_output=True, timeout=120)


# Run in the child before the CLI: every file it opens is recorded, every
# network attempt aborts the process, and at exit the record goes to stderr
# beside the interpreter's own install locations, which are allowed reads.
_AUDIT = r'''
import atexit, json, site, sysconfig
# Computed BEFORE the hook: on macOS sysconfig reads the OS version plist.
_python = sorted(set(sysconfig.get_paths().values())
                 | set(site.getsitepackages())
                 | {site.getusersitepackages(), sys.prefix, sys.base_prefix,
                    sys.exec_prefix, sys.base_exec_prefix})
_opened = []
def _hook(event, args):
    if event == "open" and isinstance(args[0], str):
        _opened.append(args[0])
    elif event.split(".")[0] in ("socket", "http", "urllib", "ftplib",
                                 "smtplib", "ssl"):
        raise SystemExit("network use: " + event)
sys.addaudithook(_hook)
atexit.register(lambda: sys.stderr.write(
    "AUDIT " + json.dumps({"opened": _opened, "python": _python}) + "\n"))
'''


@unittest.skipUnless(HAVE_LARK and HAVE_JSONSCHEMA, SKIP)
class HermeticTest(_Tmp):
    """C-6: no network, no reads beyond the input closure (the sources and
    the standard library modules they name) plus the grammar, the IR
    schema, the check report's schema and the interpreter's own files, no
    writes except targets, --emit-ir and --emit-report."""

    def test_no_network_and_no_stray_files(self):
        def refuse(*_args, **_kwargs):
            raise AssertionError("the CLI attempted network use")

        copied = copy_benchmarks(self.tmp / "src")
        self.write("draft.rhoform", NONCANONICAL)
        with mock.patch.object(socket, "socket", refuse), \
                mock.patch.object(socket, "create_connection", refuse):
            for root, entry in copied:
                code, out, _err = run("check", "--compile-root", root,
                                      "--emit-ir", self.tmp / "ir",
                                      "--emit-report", self.tmp / "reports",
                                      entry)
                self.assertEqual(code, exit_of(out))
            self.assertEqual(run("fmt", self.tmp / "draft.rhoform")[0], 0)
            self.assertEqual(run("fmt", "--stdin", self.tmp / "gate.rhoform",
                                 stdin=NONCANONICAL.encode())[0], 0)
        stems = [entry.name[:-len(".rhoform")] for _root, entry in copied]
        self.assertEqual(sorted(snapshot(self.tmp)), sorted(
            ["draft.rhoform", "gate.rhoform"]
            + [entry.relative_to(self.tmp).as_posix()
               for _root, entry in copied]
            + [f"ir/{stem}.{kind}" for stem in stems
               for kind in ("ir.json", "sourcemap.json")]
            + [f"reports/{stem}.check.json" for stem in stems]))

    def _audited_check(self, names, root=".", cwd=None):
        """(opened paths, the interpreter's own locations) of one audited
        `check --compile-root ROOT --emit-ir ir --emit-report reports
        NAMES...` run in `cwd` (self.tmp by default)."""
        cwd = self.tmp if cwd is None else cwd
        done = _subprocess(["check", "--compile-root", root, "--emit-ir",
                            "ir", "--emit-report", "reports", *names], cwd,
                           prelude=_AUDIT)
        self.assertEqual(done.returncode, 0, done.stderr.decode())
        report = json.loads(next(
            line[len("AUDIT "):] for line in done.stderr.decode().splitlines()
            if line.startswith("AUDIT ")))
        real = os.path.realpath
        return ([real(os.path.join(cwd, path))
                 for path in report["opened"]],
                [real(p) for p in report["python"]])

    @staticmethod
    def _within(path, root):
        return path == root or path.startswith(root + os.sep)

    def test_a_check_opens_only_its_closure(self):
        # The package's code, the grammar, the IR schema, the check report's
        # schema, the source, the --emit-ir and --emit-report directories,
        # and of the standard library exactly the modules the source names
        # (E-8): nothing else under rhoform/lib/. Each benchmark is its own
        # compile root, as in place.
        real = os.path.realpath
        library = real(ROOT / "rhoform" / "lib")
        for root, entry in copy_benchmarks(self.tmp):
            with self.subTest(benchmark=root.name):
                opened, python = self._audited_check([entry.name], cwd=root)
                named = set(re.findall(r"rhoform\.lib\.(\w+)\.",
                                       entry.read_text(encoding="utf-8")))
                self.assertTrue(named)
                self.assertEqual(
                    sorted({path for path in opened
                            if self._within(path, library)}),
                    sorted(real(ROOT / "rhoform" / "lib" / f"{module}"
                                ".rhoform") for module in named))
                allowed = [real(ROOT / "rhoform"),
                           real(ROOT / "lang" / "grammar"),
                           real(ROOT / "ir" / "netlist-ir.v1.schema.json"),
                           real(root / "ir"), real(root / "reports"),
                           real(entry)]
                allowed += python
                stray = [path for path in opened if not any(
                    self._within(path, place) for place in allowed)]
                self.assertEqual(stray, [])

    def test_a_lockfile_decides_the_root_and_is_not_read(self):
        # Until the lockfile lands (AMB-59), rhoform.lock is a marker: its
        # directory is the compile root, and the check stage opens nothing,
        # it included.
        real = os.path.realpath
        self.write("rhoform.lock", "{not even json\n")
        self.write("boards/main.rhoform", CLEAN)
        done = _subprocess(["check", "--emit-ir", "ir", "boards/main.rhoform"],
                           self.tmp, prelude=_AUDIT)
        self.assertEqual(done.returncode, 0, done.stderr.decode())
        report = json.loads(next(
            line[len("AUDIT "):] for line in done.stderr.decode().splitlines()
            if line.startswith("AUDIT ")))
        opened = [real(os.path.join(self.tmp, path))
                  for path in report["opened"]]
        self.assertNotIn(real(self.tmp / "rhoform.lock"), opened)
        source_map = json.loads(
            (self.tmp / "ir" / "main.sourcemap.json").read_text())
        self.assertEqual([entry["path"] for entry in source_map["files"]],
                         ["boards/main.rhoform"])

    def test_a_check_reads_only_the_library_modules_it_names(self):
        # One module named, one module read: adding or editing any other
        # library module cannot touch this design's source_hash.
        real = os.path.realpath
        self.write("divider.rhoform", P + "\nmodule Divider:\n"
                   "    port top passive\n"
                   "    r1 = new rhoform.lib.passive.Resistor\n"
                   "    top ~ r1.a\n")
        opened, _python = self._audited_check(["divider.rhoform"])
        library = real(ROOT / "rhoform" / "lib")
        self.assertEqual(
            [path for path in opened if self._within(path, library)],
            [real(ROOT / "rhoform" / "lib" / "passive.rhoform")])
        source_map = json.loads(
            (self.tmp / "ir" / "divider.sourcemap.json").read_text())
        self.assertEqual([entry["path"] for entry in source_map["files"]],
                         ["divider.rhoform", "rhoform/lib/passive.rhoform"])

    def test_a_package_check_reads_the_library_modules_its_closure_names(self):
        # The library name sits in an imported file, under a package whose
        # rhoform.toml is the compile root: that module and no other is
        # read, and it is listed by its fixed library path (E-8).
        real = os.path.realpath
        self.write("rhoform.toml", MANIFEST.replace("^0.1.0", "^0.2.0"))
        self.write("src/main.rhoform", P2 + '\nimport Divider from '
                   '"./divider"\n\nmodule Main:\n    d = new Divider\n'
                   "    d.top ~ d.mid\n")
        self.write("src/divider.rhoform", P2 + "\nmodule Divider:\n"
                   "    port top passive\n    port mid passive\n"
                   "    r1 = new rhoform.lib.passive.Resistor\n"
                   "    top ~ r1.a\n    mid ~ r1.b\n")
        opened, _python = self._audited_check(["src/main.rhoform"])
        library = real(ROOT / "rhoform" / "lib")
        self.assertEqual(
            sorted({path for path in opened if self._within(path, library)}),
            [real(ROOT / "rhoform" / "lib" / "passive.rhoform")])
        source_map = json.loads(
            (self.tmp / "ir" / "main.sourcemap.json").read_text())
        self.assertEqual([entry["path"] for entry in source_map["files"]],
                         ["rhoform/lib/passive.rhoform",
                          "src/divider.rhoform", "src/main.rhoform"])

    def test_a_package_check_opens_its_closure_and_manifests_only(self):
        # The read closure grows by exactly the import closure and the
        # manifests that govern it (C-6, spec 08): a sibling source, a
        # file the dependency does not import from, and a manifest outside
        # the dependency graph are never opened.
        manifest = MANIFEST.replace("^0.1.0", "^0.2.0")
        self.write("ws/app/rhoform.toml", manifest + '[deps]\n"acme/parts" '
                   '= { version = "^1.0.0", path = "../parts" }\n')
        self.write("ws/app/main.rhoform", P2 + '\nimport Led from '
                   '"acme/parts/leds"\nimport Spare from "./spare"\n\n'
                   "module Main:\n    d = new Led\n    s = new Spare\n"
                   "    d.a ~ d.k\n    isolated s.p\n")
        self.write("ws/app/spare.rhoform", P2 + "\ncomponent Spare:\n"
                   "    pin p passive\n")
        self.write("ws/app/sibling.rhoform", "not read")
        self.write("ws/parts/rhoform.toml", manifest.replace(
            "acme/app", "acme/parts").replace('"0.1.0"', '"1.0.0"'))
        self.write("ws/parts/leds.rhoform", LIBRARY)
        self.write("ws/parts/other.rhoform", "not read")
        self.write("ws/elsewhere/rhoform.toml", "not read")
        done = _subprocess(["check", "--compile-root", "ws",
                            "ws/app/main.rhoform"], self.tmp, prelude=_AUDIT)
        self.assertEqual(done.returncode, 0, done.stderr.decode())
        report = json.loads(next(
            line[len("AUDIT "):] for line in done.stderr.decode().splitlines()
            if line.startswith("AUDIT ")))
        real = os.path.realpath
        inputs = sorted(
            os.path.relpath(real(os.path.join(self.tmp, path)),
                            real(self.tmp / "ws"))
            for path in report["opened"]
            if real(os.path.join(self.tmp, path)).startswith(
                real(self.tmp / "ws") + os.sep))
        self.assertEqual(inputs, [
            "app/main.rhoform", "app/rhoform.toml", "app/spare.rhoform",
            "parts/leds.rhoform", "parts/rhoform.toml"])


@unittest.skipUnless(HAVE_LARK and HAVE_JSONSCHEMA, SKIP)
class ProcessTest(_Tmp):
    def test_python_m_rhoform_runs(self):
        done = _subprocess(["fmt", "--stdin", "--dry-run", "m.rhoform"],
                           self.tmp, stdin=NONCANONICAL.encode())
        self.assertEqual((done.returncode, done.stdout),
                         (0, CLEAN.encode()))

    def test_concurrent_writers_leave_one_canonical_file(self):
        target = self.write("m.rhoform", NONCANONICAL)
        others = [self.write(f"o{i}.rhoform", NONCANONICAL) for i in range(3)]
        children = [subprocess.Popen(
            _child(["fmt", target, other]), cwd=self.tmp, env=_env(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for other in others * 2]
        for child in children:
            out, err = child.communicate(timeout=120)
            self.assertEqual((child.returncode, out), (0, b""), err)
        for path in [target, *others]:
            self.assertEqual(path.read_text(), CLEAN)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                         sorted(["m.rhoform"] + [o.name for o in others]))


if __name__ == "__main__":
    unittest.main()
