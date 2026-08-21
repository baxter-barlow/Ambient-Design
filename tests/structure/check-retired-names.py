#!/usr/bin/env python3
"""Fail if a retired name reappears in a tracked file's contents or its path.

Two names have been retired, for different reasons and with different shapes:

  AED    the project name, replaced by Rhoform (AMB-122). Retired everywhere.
  AEL    the KiCad library prefix, replaced by `rho:` (AMB-118). AEL is
         Keysight ADS's Application Extension Language, a same-industry
         collision. Retired only as a LIBRARY NICKNAME — the three letters are
         still the correct way to refer to Keysight's language, which this
         repository has to be able to do while explaining why the prefix moved.

That difference is the whole design of this check. `aed` is forbidden as a
word anywhere; `ael` is forbidden only in the shapes a KiCad library nickname
takes, so that prose can still say "AEL: Application Extension Language"
without tripping a gate.

WHERE THE NICKNAME APPEARS, which is more places than the obvious one:

    "rho:R_0402_1005Metric"          a footprint REFERENCE
    (lib (name "rho")(uri ...))      a lib-table DECLARATION
    parts/library/rho.pretty/        a library DIRECTORY

Only the first has a colon. An earlier version matched `ael:` alone, so a
revert of just the lib-table entry or the directory name came back silently —
and those are exactly what AMB-64 and AMB-65 will generate.

    python3 tests/structure/check-retired-names.py --self-test
    python3 tests/structure/check-retired-names.py
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Never flagged. `aed-part-data` and its package name a SEPARATE project's
# repository; the two sha256 digests below happen to spell `aed` mid-hash.
ALLOWED = ("aed-part-data", "aed_part_data")
HEX = re.compile(r"\b[0-9a-f]{64}\b")

# The project name: a word, anywhere.
PROJECT = re.compile(r"aed", re.I)

# The library nickname, in each shape it actually takes. Every alternative is
# keyed on POSITION - a reference, a declaration, a library artefact - never on
# the quote character. Keying on quotes was both too broad and too narrow at
# once: it flagged `Keysight's language is "AEL".` while missing the same
# declaration written with single quotes or none.
#
# The footprint-shaped tail on the colon form is what lets
# `AEL: Application Extension Language` through, which this repository has to
# be able to write in order to explain why the prefix moved at all.
NICKNAME_IN_TEXT = re.compile(
    r"\bael:[A-Za-z0-9_.\-]"                                    # a reference
    # No leading \b: the key is often a SUFFIX, as in `HOUSE_LIBRARY = "ael"`.
    # The cost is that any identifier ENDING in one of these words counts, so
    # `filename: ael` and `The vendor library: AEL is not ours.` both hit. That
    # is the accepted side of the trade: putting \b back reintroduces the
    # `HOUSE_LIBRARY` miss, and a false positive on prose is a sentence to
    # rephrase while a miss is a collision that ships. Pinned by self-test.
    # `s?` and the optional bracket carry the JSON array form
    # `"pinned_footprint_libs": ["ael"]` that KiCad writes into .kicad_pro.
    r"|(?:name|nickname|library|lib)s?[\"']?\s*[:=]\s*\[?\s*[\"']?ael[\"']?(?![A-Za-z0-9_])"
    # The s-expression form takes the SAME key set as the assignment form
    # above. Hard-coding `name` here left a seam: `(lib "ael")` uses a key the
    # other alternative knew about and a separator this one required, so
    # KiCad's own `libsource` and `libpart` netlist output fell between them.
    r"|\(\s*(?:name|nickname|library|lib)\s+[\"']?ael[\"']?\s*\)"
    r"|\bael\.(?:pretty|kicad_sym|kicad_mod)\b",                # a library artefact
    re.I,
)
NICKNAME_IN_PATH = re.compile(r"(?<![A-Za-z0-9])ael(?![A-Za-z0-9])", re.I)

# Only this file is exempt WHOLESALE, because a check cannot forbid a word
# without naming it repeatedly.
EXEMPT_FILES = {"tests/structure/check-retired-names.py"}

# Everything else that legitimately names a retired name gets the PHRASE
# blanked and the rest of the file scanned. An earlier version exempted
# `check-hashes.py` entirely to spare one historical note, which turned a live
# gate script into a blind spot: `.aed-cache` and `import aed_eval` planted in
# it became invisible. Breadth bought nothing - that file produces exactly one
# hit, and it is the note.
EXEMPT_PHRASES = {
    "tests/ir/check-hashes.py": ("the AED -> Rhoform rename",),
}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    return [rel.decode() for rel in out.split(b"\0") if rel]


def scan_path(rel: str) -> str | None:
    probe = rel
    for token in ALLOWED:
        probe = probe.replace(token, "")
    if PROJECT.search(probe) or NICKNAME_IN_PATH.search(probe):
        return f"{rel}  (path)"
    return None


def scan_text(rel: str, text: str) -> list[str]:
    for token in ALLOWED:
        text = text.replace(token, "")
    for phrase in EXEMPT_PHRASES.get(rel, ()):
        text = text.replace(phrase, "")
    text = HEX.sub("", text)
    hits = []
    for line_no, line in enumerate(text.split("\n"), 1):
        if PROJECT.search(line) or NICKNAME_IN_TEXT.search(line):
            hits.append(f"{rel}:{line_no}")
    return hits


def scan_files(files) -> list[str]:
    """Scan an iterable of (path, text). The layer the self-test can drive.

    Split out from `scan_repository` because the exemption logic lives here,
    and a self-test that only exercised the matchers could not see it: making
    `EXEMPT_FILES` match everything left the suite green and the gate dead.
    """
    hits: list[str] = []
    for rel, text in files:
        if rel in EXEMPT_FILES:
            continue
        path_hit = scan_path(rel)
        if path_hit:
            hits.append(path_hit)
        hits.extend(scan_text(rel, text))
    return hits


def scan_repository() -> list[str]:
    """Read the tracked tree and hand every file to `scan_files`.

    This deliberately owns NO matching or exemption logic of its own. It used
    to carry a second copy of the exemption loop, so gutting that copy left the
    self-test green at 34/34 while the real sweep reported nothing — the kill
    switch simply moved one layer down from the constant to the loop reading
    it. Reading is the only thing that happens here.
    """
    hits: list[str] = []
    for rel in tracked_files():
        full = ROOT / rel
        try:
            text = full.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError):
            # The PATH is still checked, exactly as for the two branches
            # below: this file's own rule is that an entry the scanner
            # cannot read must be reported, "which is the same failure as
            # not looking at paths". These two returned early instead, and
            # IsADirectoryError is reachable here today -- the repository
            # tracks symlinks to directories under .claude/skills/, so a
            # tracked path carrying the retired name was reported by
            # nothing (round 21).
            hits.extend(scan_files([(rel, "")]))
            continue
        except UnicodeDecodeError:
            # A binary carrying the name is still the name; reporting beats
            # silence, which is the same bug as not looking at paths. The
            # empty text still gets the PATH checked, which is how a binary at
            # `eval/aed_eval/x.bin` yields both findings.
            hits.extend(scan_files([(rel, "")]))
            if rel not in EXEMPT_FILES:
                hits.append(f"{rel}  (binary, not scanned)")
            continue
        except OSError as exc:
            # Reported as a finding so the scan COMPLETES and still lists the
            # real hits elsewhere; raising aborted it and turned a diagnosable
            # failure into a bare non-zero exit.
            hits.extend(scan_files([(rel, "")]))
            if rel not in EXEMPT_FILES:
                hits.append(f"{rel}  (unreadable: {exc.strerror}, not scanned)")
            continue
        hits.extend(scan_files([(rel, text)]))
    return hits


def self_test() -> int:
    """Prove both matchers fire, and that neither over-fires.

    The repo standard, stated twice in the Makefile: a linter whose checks
    silently stopped firing must fail loudly rather than report a clean sweep.
    This gate grew a second matcher and had no such test.
    """
    text_cases = [
        # (sample, should_hit)
        ('"footprint_ref": "ael:DIP-8_W7.62mm"', True),
        ('"footprint_ref": "AEL:R_0402_1005Metric"', True),
        ('(lib (name "ael")(uri "${KIPRJMOD}/ael.pretty"))', True),
        ('HOUSE_LIBRARY = "ael"', True),
        # Same declaration, other spellings. Keying on the quote character
        # caught only the first of these.
        ("HOUSE_LIBRARY = 'ael'", True),
        ("library: ael", True),
        ("(lib (name 'ael')(uri 'x'))", True),
        ('(uri "${KIPRJMOD}/ael.pretty")', True),
        ("nickname = 'AEL'", True),
        # KiCad's own netlist output. These fell in a seam between the
        # assignment form (which knew `lib` but demanded `:` or `=`) and the
        # s-expression form (which allowed whitespace but only knew `name`) —
        # and they are precisely what the golden-file corpus will contain.
        ('(libsource (lib "ael") (part "R") (description ""))', True),
        ('(libpart (lib "ael") (part "R_0402")', True),
        ('  "pinned_footprint_libs": ["ael"],', True),
        ('  "pinned_symbol_libs": ["ael"]', True),
        # The accepted cost of dropping \b from the key group: any identifier
        # ENDING in a key word counts. Pinned so the trade is on the record
        # rather than rediscovered — restoring \b would miss HOUSE_LIBRARY.
        ("filename: ael", True),
        ("The vendor library: AEL is not ours.", True),
        # And the current prefix must never fire, in any of these shapes.
        ('(libsource (lib "rho") (part "R"))', False),
        ('  "pinned_footprint_libs": ["rho"],', False),
        ("HOUSE_LIBRARY = 'rho'", False),
        ("python3 -m aed_eval replay", True),
        ("the .aed-cache directory", True),
        # Prose about Keysight's language must survive: this repository has to
        # be able to explain why the prefix moved.
        ("AEL: Application Extension Language, by Keysight.", False),
        ("## AEL: why the prefix moved", False),
        ("Keysight's AEL is a different thing entirely.", False),
        # Quoted prose and data about Keysight's language. Matching a bare
        # quoted "ael" flagged every one of these.
        ('Keysight\'s scripting language is "AEL".', False),
        ('Vendors ship "SKILL", "AEL", "Verilog-A".', False),
        ('{"scripting_languages": ["skill", "ael", "spectre"]}', False),
        ('| language | "AEL" | Keysight |', False),
        ("Michael: see also Israel: and parallel: notes", False),
        ('"footprint_ref": "rho:DIP-8_W7.62mm"', False),
        ("a paella recipe", False),
    ]
    path_cases = [
        ("eval/aed_eval/__init__.py", True),
        ("parts/library/ael.pretty/R_0402.kicad_mod", True),
        ("parts/library/ael.kicad_sym", True),
        (".agents/skills/verify-aed-change/SKILL.md", True),
        ("eval/aed-part-data/aed_eval.py", True),
        ("parts/aed-part-data/notes.md", False),
        ("parts/library/rho.pretty/R_0402.kicad_mod", False),
        ("docs/michael.md", False),
        ("eval/rhoform_eval/__init__.py", False),
    ]

    # The exemption layer, which the matcher cases cannot see. Widening
    # EXEMPT_FILES to match everything is a silent kill switch, and that is
    # exactly how a whole-file exemption over a live gate script slipped past
    # a 21-case suite.
    exemption_cases = [
        (
            "a planted hit in a phrase-exempt file is still reported",
            bool(scan_files([("tests/ir/check-hashes.py", "import aed_eval\n")])),
        ),
        (
            "the exempt phrase itself is not reported",
            not scan_files(
                [("tests/ir/check-hashes.py", "# the AED -> Rhoform rename\n")]
            ),
        ),
        (
            "an ordinary file is scanned",
            bool(scan_files([("parts/README.md", "import aed_eval\n")])),
        ),
        (
            "only this script is exempt wholesale",
            EXEMPT_FILES == {"tests/structure/check-retired-names.py"},
        ),
        # THE PATH HIT MUST BE REPORTED, not merely matched. `path_cases`
        # below call `scan_path` directly, so they prove the matcher works
        # while saying nothing about whether `scan_files` passes its answer
        # on. Round 14 measured that: `hits.append(path_hit)` could be
        # replaced with `pass` -- a tracked file at eval/aed_eval/x.json goes
        # unreported, the gate prints PASS, all 46 cases stay green and
        # `make all` exits 0. This is the AMB-122 rename guard's path half.
        (
            "a path-only hit is reported through scan_files",
            scan_files([("eval/aed_eval/x.json", "nothing to see\n")])
            == ["eval/aed_eval/x.json  (path)"],
        ),
        (
            "a clean path with clean text reports nothing",
            scan_files([("eval/rhoform_eval/x.json", "nothing to see\n")]) == [],
        ),
    ]

    # And the READING layer, over a real temporary tree. Everything above
    # drives `scan_files` directly, so gutting `scan_repository`'s one
    # delegating line left the suite green and the sweep dead — the kill
    # switch kept moving down a layer as each one above it got covered. This
    # is the bottom: it plants a hit on disk and asserts the shipped entry
    # point finds it.
    import tempfile

    global ROOT
    real_root, real_tracked = ROOT, tracked_files
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ROOT = Path(tmp)
            (ROOT / "clean.md").write_text("nothing here\n", encoding="utf-8")
            (ROOT / "dirty.md").write_text(
                '"footprint_ref": "ael:DIP-8_W7.62mm"\n', encoding="utf-8"
            )
            globals()["tracked_files"] = lambda: ["clean.md", "dirty.md"]
            found = scan_repository()
            wiring_cases = [
                ("scan_repository finds a planted hit", found == ["dirty.md:1"]),
            ]

            # THE TWO UNREADABLE LEGS. Both were unpinned: blanking either
            # `hits.append` left the suite green, and both exist so that a
            # file the scanner cannot read is REPORTED rather than skipped in
            # silence -- which is the same failure as not looking at paths.
            (ROOT / "blob.bin").write_bytes(b"\xff\xfe ael:DIP-8 \x00")
            globals()["tracked_files"] = lambda: ["blob.bin"]
            binary_found = scan_repository()
            wiring_cases.append(
                ("an undecodable file is reported, not skipped",
                 any("(binary, not scanned)" in h for h in binary_found)))

            # A TRACKED DIRECTORY, which is what a symlink to a directory
            # reads as: the path must still be checked. This branch used to
            # `continue` without scanning, and the repository tracks four
            # such symlinks under .claude/skills/ today (round 21).
            (ROOT / "ael-skills").mkdir()
            globals()["tracked_files"] = lambda: ["ael-skills"]
            dir_found = scan_repository()
            wiring_cases.append(
                ("a tracked directory still gets its PATH checked",
                 any(h.startswith("ael-skills") for h in dir_found)))

            missing = "aed/gone.md"
            globals()["tracked_files"] = lambda: [missing]
            gone_found = scan_repository()
            wiring_cases.append(
                ("a tracked path that is not on disk still gets checked",
                 any(h.startswith(missing) for h in gone_found)))

            locked = ROOT / "locked.md"
            # chmod 0o000 does not stop root: DAC checks are bypassed at
            # uid 0, which is exactly how GitHub Actions container jobs run,
            # so this case failed the whole self-test in the committed CI
            # (round 18). Under root the unreadable file is a Unix socket
            # node instead -- open() fails with ENXIO for every uid.
            import os as _os
            if _os.geteuid() == 0:
                import socket as _socket
                _sock = _socket.socket(_socket.AF_UNIX)
                _sock.bind(str(locked))
            else:
                _sock = None
                locked.write_text("clean\n", encoding="utf-8")
                locked.chmod(0o000)
            globals()["tracked_files"] = lambda: ["locked.md"]
            try:
                unreadable_found = scan_repository()
            finally:
                if _sock is not None:
                    _sock.close()
                else:
                    locked.chmod(0o644)
            wiring_cases.append(
                ("an unreadable file is reported, not skipped",
                 any("not scanned" in h for h in unreadable_found)))
    finally:
        ROOT = real_root
        globals()["tracked_files"] = real_tracked

    # And main() itself. Every sibling gate gained this case; this file did
    # not, so `return 1` -> `return 0` left the self-test AND `make structure`
    # green with a real retired name planted in a tracked file. That is the same
    # kill switch this file's own docstring describes moving down a layer — it
    # had moved UP one, to the entry point.
    import contextlib as _c, io as _i
    _real = scan_repository
    try:
        globals()["scan_repository"] = lambda: ["planted.md:1"]
        with _c.redirect_stdout(_i.StringIO()), _c.redirect_stderr(_i.StringIO()):
            _planted = main([])
        globals()["scan_repository"] = lambda: []
        with _c.redirect_stdout(_i.StringIO()), _c.redirect_stderr(_i.StringIO()):
            _clean = main([])
    finally:
        globals()["scan_repository"] = _real
    wiring_cases.append(("main() exits non-zero on a hit", _planted == 1))
    wiring_cases.append(("main() exits zero with none", _clean == 0))

    failures = 0
    for name, ok in wiring_cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} wiring      {name}")
    for name, ok in exemption_cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} exempt      {name}")
    for sample, want in text_cases:
        got = bool(scan_text("probe.txt", sample))
        ok = got == want
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} text  {'hit ' if want else 'pass'}  {sample[:52]}")
    for sample, want in path_cases:
        got = scan_path(sample) is not None
        ok = got == want
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} path  {'hit ' if want else 'pass'}  {sample[:52]}")

    if failures:
        print(f"retired-names: SELF-TEST FAILED: {failures} case(s)", file=sys.stderr)
        return 1
    print(
        f"retired-names: self-test PASS: "
        f"{len(text_cases) + len(path_cases) + len(exemption_cases) + len(wiring_cases)} cases."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()

    try:
        hits = scan_repository()
    except (FileNotFoundError, subprocess.CalledProcessError):
        print(
            "retired-names: UNAVAILABLE: git is required to list tracked files",
            file=sys.stderr,
        )
        return 2

    if hits:
        print(
            "retired-names: FAIL: a retired name (the project name AED, or the "
            "AEL library nickname) reappears in tracked files:",
            file=sys.stderr,
        )
        for hit in hits:
            print(f"  {hit}", file=sys.stderr)
        return 1
    print("retired-names: PASS: no retired name in any tracked path or file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
