"""The command line (R18 / AMB-49; decision record C-1..C-6).

Most cases run `rhoform.cli.main` in-process with stdout and stderr
captured; a few run `python3 -m rhoform` as a real subprocess, where only a
process boundary can show the property (concurrent writers, and an audit
hook watching every file the run opens). The command line is held to the
reference implementation through the committed artifacts: `check` must
reproduce every elaboration reject case's expected stream and every accept
case's expected IR, and `check --emit-ir` every benchmark golden, byte for
byte.

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

P = "#pragma rhoform-syntax 0.1\n"
CLEAN = P + "\nmodule M:\n    port p passive\n"
NONCANONICAL = P + "module M:\n  port p passive\n"
BROKEN = P + "\nmodule M:\n    port p passiv\n"
TWO_ROOTS = (P + "\nmodule A:\n    port p passive\n"
             "\nmodule B:\n    port q passive\n")


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
        self.tmp = Path(tempfile.mkdtemp(prefix="rhoform-cli-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, rel: str, text: str) -> Path:
        path = self.tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path


@unittest.skipUnless(HAVE_LARK and HAVE_JSONSCHEMA, SKIP)
class CheckTest(_Tmp):
    def test_clean_file_exits_zero_with_an_empty_stream(self):
        self.assertEqual(run("check", self.write("m.rhoform", CLEAN)),
                         (0, "", ""))

    def test_errors_exit_one_as_ndjson_with_root_relative_files(self):
        code, out, err = run("check", self.write("sub/m.rhoform", BROKEN))
        self.assertEqual((code, err), (1, ""))
        self.assertEqual([d["code"] for d in lines(out)], ["RHO1009"])
        self.assertEqual(lines(out)[0]["spans"][0]["file"], "m.rhoform")

    def test_reject_cases_reproduce_their_expected_streams(self):
        cases = sorted((ELABORATE / "reject").glob("*.rhoform"))
        self.assertTrue(cases)
        for case in cases:
            with self.subTest(case=case.name):
                code, out, _err = run("check", case)
                expected = case.with_name(
                    case.name[:-len(".rhoform")] + ".expected.ndjson")
                self.assertEqual(out, expected.read_text(encoding="utf-8"))
                # Exit 1 needs an error; a warnings-only case exits 0.
                self.assertEqual(code, int(any(
                    d["severity"] == "error" for d in lines(out))))

    def test_accept_cases_emit_their_expected_ir(self):
        cases = sorted((ELABORATE / "accept").glob("*.rhoform"))
        self.assertTrue(cases)
        code, out, err = run("check", "--emit-ir", self.tmp, *cases)
        self.assertEqual((code, out, err), (0, "", ""))
        for case in cases:
            stem = case.name[:-len(".rhoform")]
            with self.subTest(case=stem):
                self.assertEqual(
                    (self.tmp / f"{stem}.ir.json").read_bytes(),
                    case.with_name(f"{stem}.expected.ir.json").read_bytes())

    def test_emit_ir_reproduces_every_benchmark_golden(self):
        from rhoform.tests.test_benchmarks import (emit_argv, goldens,
                                                   sources)

        self.assertTrue(sources())
        for source in sources():
            out = self.tmp / source.parent.name
            with self.subTest(benchmark=source.parent.name):
                self.assertEqual(run(*emit_argv(source, out)), (0, "", ""))
                written = sorted(p.name for p in out.iterdir())
                self.assertEqual(written, sorted(g.name for g in
                                                 goldens(source)))
                for golden in goldens(source):
                    self.assertTrue((out / golden.name).read_bytes()
                                    == golden.read_bytes(),
                                    f"{golden.name} differs")

    def test_check_never_writes_without_emit_ir(self):
        for source in sorted((ROOT / "benchmarks").glob("*/*.rhoform")):
            shutil.copy(source, self.tmp / source.name)
        self.write("bad.rhoform", BROKEN)
        before = snapshot(self.tmp)
        code, _out, _err = run("check", self.tmp)
        self.assertEqual(code, 1)
        self.assertEqual(snapshot(self.tmp), before)

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
        self.write("pkg/rhoform.toml", "")
        entry = self.write("pkg/boards/main.rhoform", CLEAN)
        code, _out, _err = run("check", "--emit-ir", self.tmp / "out", entry)
        self.assertEqual(code, 0)
        document = json.loads((self.tmp / "out" / "main.ir.json").read_text())
        source_map = json.loads(
            (self.tmp / "out" / "main.sourcemap.json").read_text())
        self.assertEqual([f["path"] for f in source_map["files"]],
                         ["boards/main.rhoform"])
        self.assertEqual(document["instances"][0]["definition"],
                         "boards.main.M")
        code, out, _err = run("check", self.write("pkg/boards/bad.rhoform",
                                                  BROKEN))
        self.assertEqual(lines(out)[0]["spans"][0]["file"],
                         "boards/bad.rhoform")

    def test_explicit_compile_root_wins_and_must_contain_the_entry(self):
        self.write("pkg/rhoform.toml", "")
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
        self.assertEqual((code, out), (0, ""))
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
            self.assertEqual((code, out), (2, ""))
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
        self.assertEqual((code, out), (2, ""))
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
    the standard library modules they name) plus the grammar, the IR schema
    and the interpreter's own files, no writes except targets and
    --emit-ir."""

    def test_no_network_and_no_stray_files(self):
        def refuse(*_args, **_kwargs):
            raise AssertionError("the CLI attempted network use")

        sources = sorted((ROOT / "benchmarks").glob("*/*.rhoform"))
        for source in sources:
            shutil.copy(source, self.tmp / source.name)
        self.write("draft.rhoform", NONCANONICAL)
        with mock.patch.object(socket, "socket", refuse), \
                mock.patch.object(socket, "create_connection", refuse):
            code, _out, _err = run("check", "--emit-ir", self.tmp / "ir",
                                   *(self.tmp / s.name for s in sources))
            self.assertEqual(code, 0)
            self.assertEqual(run("fmt", self.tmp / "draft.rhoform")[0], 0)
            self.assertEqual(run("fmt", "--stdin", self.tmp / "gate.rhoform",
                                 stdin=NONCANONICAL.encode())[0], 0)
        stems = [s.name[:-len(".rhoform")] for s in sources]
        self.assertEqual(sorted(snapshot(self.tmp)), sorted(
            ["draft.rhoform", "gate.rhoform"]
            + [s.name for s in sources]
            + [f"ir/{stem}.{kind}" for stem in stems
               for kind in ("ir.json", "sourcemap.json")]))

    def _audited_check(self, names):
        """(opened paths, the interpreter's own locations) of one audited
        `check --emit-ir ir NAMES...` run in self.tmp."""
        done = _subprocess(["check", "--emit-ir", "ir", *names], self.tmp,
                           prelude=_AUDIT)
        self.assertEqual(done.returncode, 0, done.stderr.decode())
        report = json.loads(next(
            line[len("AUDIT "):] for line in done.stderr.decode().splitlines()
            if line.startswith("AUDIT ")))
        real = os.path.realpath
        return ([real(os.path.join(self.tmp, path))
                 for path in report["opened"]],
                [real(p) for p in report["python"]])

    @staticmethod
    def _within(path, root):
        return path == root or path.startswith(root + os.sep)

    def test_a_check_opens_only_its_closure(self):
        # The package's code, the grammar, the IR schema, the sources, the
        # --emit-ir directory, and of the standard library exactly the
        # modules the sources name (E-8): nothing else under rhoform/lib/.
        real = os.path.realpath
        sources = sorted((ROOT / "benchmarks").glob("*/*.rhoform"))
        for source in sources:
            shutil.copy(source, self.tmp / source.name)
        opened, python = self._audited_check([s.name for s in sources])
        library = real(ROOT / "rhoform" / "lib")
        named = set()
        for source in sources:
            named.update(re.findall(r"rhoform\.lib\.(\w+)\.",
                                    source.read_text(encoding="utf-8")))
        self.assertTrue(named)
        self.assertEqual(
            sorted({path for path in opened if self._within(path, library)}),
            sorted(real(ROOT / "rhoform" / "lib" / f"{module}.rhoform")
                   for module in named))
        allowed = [real(ROOT / "rhoform"), real(ROOT / "lang" / "grammar"),
                   real(ROOT / "ir" / "netlist-ir.schema.json"),
                   real(self.tmp / "ir")]
        allowed += [real(self.tmp / s.name) for s in sources]
        allowed += python
        stray = [path for path in opened
                 if not any(self._within(path, root) for root in allowed)]
        self.assertEqual(stray, [])

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
