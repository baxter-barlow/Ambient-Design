"""The command line (R18): `python3 -m rhoform check|fmt`.

`check PATH...` compiles each PATH as the entry file of its own
compilation: the package layer (rhoform/package.py) reads the entry, the
files it imports and the rhoform.toml files that govern them, then the
compilation is parsed, checked, elaborated, and its IR validated against
ir/netlist-ir.schema.json. A directory stands for its ENTRY files, in
sorted order: every `*.rhoform` under it except a file that another file
named on the command line reaches through imports without being reached
back (a library is checked through the files that import it; a file
imported only within a cycle is still an entry, so the cycle is
reported). It never writes, except that `--emit-ir DIR` writes
`<stem>.ir.json` and `<stem>.sourcemap.json` for every entry that
elaborates, the names the benchmark goldens use.

`fmt PATH...` rewrites each file to its canonical form, in place and only
when the bytes change; a file that does not parse is refused and left
alone. `fmt --check` writes nothing and reports every file that would
change as RHO1017, spanning the first line that differs. `fmt --stdin
TARGET` is the A2 write gate: the proposed bytes arrive on stdin; a
rejected proposal leaves TARGET untouched and prints its diagnostics
(exit 1), an accepted one replaces TARGET with the canonical bytes and
echoes them (exit 0). `--dry-run` never touches TARGET.

THE STREAM (spec 06). stdout carries NDJSON only, from one Diagnostics
aggregate rendered once, so canonical order and the cap hold across every
file of the invocation; each compilation reports into a sink of its own
that is then merged into the aggregate (C-5), a defect two compilations
share (one imported file) once. Filter mode is the stated
carve-out: on exit 0 its stdout is the canonical source. Exit 0 is clean,
1 is at least one error, 2 is a tool that could not do its job: a usage
error, an unreadable or unwritable file, a missing pinned dependency
(lark always; jsonschema whenever there is IR to validate), or an
internal error such as a formatter self-check failure or IR the schema
rejects. Operational complaints go to stderr, never stdout.

PATHS (spec 04, E-8). Each compilation's compile root is `--compile-root`,
else the nearest ancestor of the entry file holding `rhoform.toml`, else
the entry file's directory. Span files, the source map's `files[].path`
and definition names are POSIX paths relative to it, so a span names the
same file the source map does. The standard library modules a compilation
reads are the exception: they are the toolchain's own files, listed as
`rhoform/lib/<module>.rhoform` whatever the compile root.

HERMETIC (I3, C-6). No network module is imported and nothing reads the
environment or the clock. Reads: the input files and their import
closures, the rhoform.toml files governing them, the standard library
modules their qualified names mention (rhoform/lib/, no others), the
grammar artifacts the parser loads, and the IR schema. Nothing outside a
compile root is read as an author's source. Writes: fmt's targets and
--emit-ir's files, each through a temporary file in the target's own
directory and `os.replace`, so a reader never sees a torn file and two
concurrent runs cannot interleave their bytes.
"""

import argparse
import contextlib
import json
import os
import stat
import sys
import tempfile
import traceback
from pathlib import Path

from . import elaborate as elaborator
from . import fmt as formatter
from . import ir
from . import package
from . import parser as rhoparser
from .diagnostics import Diagnostics, span_from_bytes

MANIFEST = "rhoform.toml"
SUFFIX = ".rhoform"
IR_SCHEMA = (Path(__file__).resolve().parents[1] / "ir"
             / "netlist-ir.schema.json")

EXIT_CLEAN = 0
EXIT_ERRORS = 1
EXIT_UNAVAILABLE = 2


class UsageError(Exception):
    """A command line the tool cannot act on. Exit 2, before any write."""


class _Run:
    """One command's shared state: the aggregate sink and the exit floor."""

    def __init__(self, command: str):
        self.command = command
        self.report = Diagnostics()
        self.failed = False

    def complain(self, text: str) -> None:
        print(f"rhoform {self.command}: {text}", file=sys.stderr)
        self.failed = True

    def finish(self) -> int:
        sys.stdout.write(self.report.render())
        if self.failed:
            return EXIT_UNAVAILABLE
        return EXIT_ERRORS if self.report.has_errors else EXIT_CLEAN


# ---- paths ------------------------------------------------------------------

def _absolute(path) -> Path:
    """Lexically absolute and normalized; symlinks are not resolved, so a
    path is relative to the root the user named, not to where it points."""
    return Path(os.path.normpath(os.path.abspath(path)))


def compile_root(entry, explicit=None) -> Path:
    """The compile root of a compilation whose entry file is `entry`."""
    if explicit is not None:
        return _absolute(explicit)
    directory = _absolute(entry).parent
    for candidate in (directory, *directory.parents):
        if (candidate / MANIFEST).is_file():
            return candidate
    return directory


def root_relative(entry, root: Path) -> str:
    """`entry` relative to `root`, lexically when the two spellings agree,
    else through resolved links (a root named via a symlinked directory,
    such as macOS's /tmp, still contains the files under its target)."""
    for spell in (_absolute, os.path.realpath):
        try:
            return Path(spell(entry)).relative_to(spell(root)).as_posix()
        except ValueError:
            continue
    raise UsageError(f"{entry} is not under the compile root {root}")


def expand(given, swept=None) -> list[Path]:
    """Files in argument order, each directory replaced by its *.rhoform
    files sorted by path; a file named twice is compiled once. The keys of
    files found only by sweeping a directory, never named themselves, are
    added to `swept`."""
    files, seen, named, found_in_directories = [], set(), set(), set()
    for text in given:
        path = Path(text)
        if path.is_dir():
            found = sorted(
                (p for p in path.rglob("*" + SUFFIX) if p.is_file()),
                key=lambda p: p.as_posix())
            if not found:
                raise UsageError(
                    f"{text}: no *{SUFFIX} file under this directory; a "
                    "check over nothing is not a pass")
            found_in_directories.update(_absolute(p) for p in found)
        else:
            found = [path]
            named.add(_absolute(path))
        for path in found:
            key = _absolute(path)
            if key not in seen:
                seen.add(key)
                files.append(path)
    if swept is not None:
        swept.update(found_in_directories - named)
    return files


def _plan(given, explicit_root, swept=None) -> list[tuple[Path, Path, str]]:
    """(path, compile root, compile-root-relative file name) for every
    input, computed before anything is read so a usage error leaves
    everything untouched."""
    if explicit_root is not None and not Path(explicit_root).is_dir():
        raise UsageError(f"--compile-root {explicit_root} is not a directory")
    plan = []
    for path in expand(given, swept):
        root = compile_root(path, explicit_root)
        plan.append((path, root, root_relative(path, root)))
    return plan


def stem(path: Path) -> str:
    return path.name.removesuffix(SUFFIX)


# ---- writing ----------------------------------------------------------------

def _default_mode() -> int:
    mask = os.umask(0o022)
    os.umask(mask)
    return 0o666 & ~mask


def write_atomically(target: Path, data: bytes) -> None:
    """Replace `target` with `data` via a temporary file in its directory and
    os.replace, keeping the target's permission bits (a new file gets the
    umask's). On any failure the temporary file is removed and the target
    is as it was."""
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = _default_mode()
    handle, temporary = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


# ---- check ------------------------------------------------------------------

_SCHEMA_VALIDATOR = None


def schema_problem(document: dict) -> str | None:
    """Why `document` is not valid IR, or None. Raises ImportError when the
    pinned jsonschema is missing: an unavailable gate, never a pass."""
    global _SCHEMA_VALIDATOR
    import jsonschema

    if _SCHEMA_VALIDATOR is None:
        schema = json.loads(IR_SCHEMA.read_text(encoding="utf-8"))
        _SCHEMA_VALIDATOR = jsonschema.validators.validator_for(schema)(schema)
    error = jsonschema.exceptions.best_match(
        _SCHEMA_VALIDATOR.iter_errors(document))
    if error is None:
        return None
    where = "/".join(str(part) for part in error.absolute_path)
    return f"{error.message} (at /{where})"


def _closure(root: Path, file: str) -> set:
    """Every file the compilation entered at `file` reads, by real path;
    what it reports is discarded (the real compilation reports it)."""
    try:
        compilation = package.load(file, root, Diagnostics())
    except package.ReadFailure:
        return set()
    return {os.path.realpath(root / result.file)
            for result in compilation.results}


def entries(plan, swept) -> list:
    """The plan without the swept files some other planned file reaches
    through imports without being reached back: those are compiled as
    part of their importers. A file named on the command line is always
    an entry."""
    if not swept:
        return plan
    real = {os.path.realpath(key) for key in swept}
    reach = {os.path.realpath(path): _closure(root, file)
             for path, root, file in plan}
    kept = []
    for item in plan:
        key = os.path.realpath(item[0])
        if key in real and any(
                other != key and key in reached and other not in reach[key]
                for other, reached in reach.items()):
            continue
        kept.append(item)
    return kept


def run_check(args) -> int:
    run = _Run("check")
    swept = set()
    plan = entries(_plan(args.paths, args.compile_root, swept), swept)
    out = None
    if args.emit_ir is not None:
        out = Path(args.emit_ir)
        if out.exists() and not out.is_dir():
            raise UsageError(f"--emit-ir {out} is not a directory")
        claimed = {}
        for path, _root, _file in plan:
            other = claimed.setdefault(stem(path), path)
            if other is not path:
                raise UsageError(
                    f"--emit-ir would write {stem(path)}.ir.json for both "
                    f"{other} and {path}")
    for path, root, file in plan:
        sink = Diagnostics()
        try:
            compilation = package.load(file, root, sink)
        except package.ReadFailure as exc:
            run.report.merge(sink)
            run.complain(f"FAIL: {exc}")
            continue
        if not compilation.ok:
            run.report.merge(sink)
            continue
        elaboration = elaborator.elaborate(
            compilation.results, root=args.root_module, sink=sink,
            imports=compilation.imports)
        run.report.merge(sink)
        if not elaboration.ok:
            continue
        ir_bytes, map_bytes = ir.emit(elaboration.design)
        try:
            problem = schema_problem(json.loads(ir_bytes))
        except ImportError:
            run.complain(
                f"UNAVAILABLE: jsonschema is not installed, so the IR of "
                f"{path} could not be validated against "
                "ir/netlist-ir.schema.json. Install the pin from "
                "toolchain/versions.yaml: python3 -m pip install "
                "jsonschema==4.26.0")
            continue
        if problem is not None:
            run.complain(f"INTERNAL: the IR elaborated from {path} does not "
                         f"validate against ir/netlist-ir.schema.json: "
                         f"{problem}")
            continue
        if out is not None:
            try:
                out.mkdir(parents=True, exist_ok=True)
                write_atomically(out / f"{stem(path)}.ir.json", ir_bytes)
                write_atomically(out / f"{stem(path)}.sourcemap.json",
                                 map_bytes)
            except OSError as exc:
                run.complain(f"FAIL: cannot write the IR of {path} to "
                             f"{out}: {exc}")
    return run.finish()


# ---- fmt --------------------------------------------------------------------

def first_differing_line(file: str, data: bytes, old: str, new: str):
    """The span of the physical line of `data` holding the first character
    where `old` (its decoding) and `new` differ. A line with no text is
    spanned by its line feed, so the span is never empty while a byte
    remains; at end of file it is the insertion point there."""
    position = formatter.first_difference(old, new)
    start = data.rfind(b"\n", 0, position) + 1
    end = data.find(b"\n", position)
    if end < 0:
        end = len(data)
    if start == end and end < len(data):
        end += 1
    return span_from_bytes(file, data, start, end)


def _format(run: _Run, path, file: str, source: str):
    """The formatter's result, or None when its self-check failed (an
    internal error, reported; nothing is written)."""
    try:
        return formatter.format_source(source, file=file)
    except formatter.FormatterError as exc:
        run.complain(f"INTERNAL: formatting {path} failed its self-check; "
                     f"nothing was written. {exc}")
        return None


def run_fmt(args) -> int:
    if args.dry_run and not args.stdin:
        raise UsageError("--dry-run applies only to --stdin")
    if args.stdin:
        if args.check:
            raise UsageError("--check and --stdin are separate modes")
        if len(args.paths) != 1:
            raise UsageError("--stdin takes exactly one TARGET")
        return run_filter(Path(args.paths[0]), args.compile_root,
                          args.dry_run)
    run = _Run("fmt")
    for path, _root, file in _plan(args.paths, args.compile_root):
        try:
            data = path.read_bytes()
        except OSError as exc:
            run.complain(f"FAIL: cannot read {path}: {exc}")
            continue
        source = data.decode("utf-8", "surrogateescape")
        result = _format(run, path, file, source)
        if result is None:
            continue
        run.report.extend(result.diagnostics)
        if result.text is None or result.text == source:
            continue
        if args.check:
            run.report.add("RHO1017", primary=first_differing_line(
                file, data, source, result.text))
            continue
        try:
            write_atomically(path, result.text.encode("utf-8"))
        except OSError as exc:
            run.complain(f"FAIL: cannot write {path}: {exc}")
    return run.finish()


def _stdin_bytes() -> bytes:
    stream = getattr(sys.stdin, "buffer", None)
    if stream is not None:
        return stream.read()
    return sys.stdin.read().encode("utf-8", "surrogateescape")


def run_filter(target: Path, explicit_root, dry_run: bool) -> int:
    """The A2 write gate. stdout is the canonical source on exit 0 and the
    diagnostic stream on exit 1 (spec 06's filter-mode carve-out); exit 2
    leaves stdout empty and TARGET untouched."""
    run = _Run("fmt")
    if target.is_dir():
        raise UsageError(f"--stdin TARGET {target} is a directory")
    if explicit_root is not None and not Path(explicit_root).is_dir():
        raise UsageError(f"--compile-root {explicit_root} is not a directory")
    file = root_relative(target, compile_root(target, explicit_root))
    proposed = _stdin_bytes()
    result = _format(run, target, file, proposed.decode("utf-8",
                                                        "surrogateescape"))
    if result is None:
        return EXIT_UNAVAILABLE
    if result.text is None:
        sys.stdout.write(result.diagnostics.render())
        return EXIT_ERRORS
    canonical = result.text.encode("utf-8")
    if not dry_run:
        try:
            current = target.read_bytes()
        except FileNotFoundError:
            current = None
        except OSError as exc:
            run.complain(f"FAIL: cannot read {target}: {exc}")
            return EXIT_UNAVAILABLE
        if current != canonical:
            try:
                write_atomically(target, canonical)
            except OSError as exc:
                run.complain(f"FAIL: cannot write {target}: {exc}")
                return EXIT_UNAVAILABLE
    sys.stdout.write(result.text)
    return EXIT_CLEAN


# ---- the command line -------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="rhoform",
        description="Rhoform compiler front end. stdout is NDJSON "
                    "diagnostics (spec 06); exit 0 clean, 1 errors, 2 could "
                    "not run.")
    commands = root.add_subparsers(dest="command", required=True,
                                   metavar="{check,fmt}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--compile-root", metavar="DIR",
        help="the compile root every path is relative to (default: the "
             "nearest ancestor holding rhoform.toml, else the file's "
             "directory)")

    check = commands.add_parser(
        "check", parents=[common],
        help="parse, check, elaborate and validate; writes nothing",
        description="Compile each PATH as its own entry file, with the "
                    "files it imports (a directory stands for its *.rhoform "
                    "files, less those another named file imports).")
    check.add_argument("paths", nargs="+", metavar="PATH")
    check.add_argument("--root-module", metavar="NAME",
                       help="the root module, when the entry file has "
                            "several candidates")
    check.add_argument("--emit-ir", metavar="DIR",
                       help="write <stem>.ir.json and <stem>.sourcemap.json "
                            "here for every entry that elaborates")
    check.set_defaults(run=run_check)

    fmt = commands.add_parser(
        "fmt", parents=[common],
        help="rewrite files in canonical form",
        description="Rewrite each PATH in canonical form, in place.")
    fmt.add_argument("paths", nargs="+", metavar="PATH")
    fmt.add_argument("--check", action="store_true",
                     help="write nothing; report each file that would change")
    fmt.add_argument("--stdin", action="store_true",
                     help="the write gate: read proposed source on stdin and "
                          "write its canonical form to the one PATH (TARGET)")
    fmt.add_argument("--dry-run", action="store_true",
                     help="with --stdin: check and echo, but leave TARGET "
                          "alone")
    fmt.set_defaults(run=run_fmt)
    return root


def main(argv=None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse: --help (0) or a usage error (2)
        return exc.code if isinstance(exc.code, int) else EXIT_UNAVAILABLE
    try:
        return args.run(args)
    except UsageError as exc:
        print(f"rhoform {args.command}: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except rhoparser.LarkUnavailable as exc:
        print(f"rhoform {args.command}: UNAVAILABLE: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except Exception:  # an internal error must not exit 1, which means
        traceback.print_exc()  # "ran, found errors" (spec 06)
        print(f"rhoform {args.command}: INTERNAL: unexpected error",
              file=sys.stderr)
        return EXIT_UNAVAILABLE
