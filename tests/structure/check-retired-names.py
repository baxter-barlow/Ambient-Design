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

# The library nickname, in each shape it actually takes. A footprint-shaped
# tail on the colon form is what lets `AEL: Application Extension Language`
# through while still catching `"ael:DIP-8_W7.62mm"`.
NICKNAME_IN_TEXT = re.compile(r"\bael:[A-Za-z0-9_.\-]|\"ael\"", re.I)
NICKNAME_IN_PATH = re.compile(r"(?<![A-Za-z0-9])ael(?![A-Za-z0-9])", re.I)

# Files that must be able to name what they forbid.
EXEMPT_FILES = {
    "tests/structure/check-retired-names.py",
    "tests/ir/check-hashes.py",
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
    text = HEX.sub("", text)
    hits = []
    for line_no, line in enumerate(text.split("\n"), 1):
        if PROJECT.search(line) or NICKNAME_IN_TEXT.search(line):
            hits.append(f"{rel}:{line_no}")
    return hits


def scan_repository() -> list[str]:
    hits: list[str] = []
    for rel in tracked_files():
        if rel in EXEMPT_FILES:
            continue
        path_hit = scan_path(rel)
        if path_hit:
            hits.append(path_hit)
        full = ROOT / rel
        try:
            text = full.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except IsADirectoryError:
            continue
        except UnicodeDecodeError:
            # A binary carrying the name is still the name; reporting beats
            # silence, which is the same bug as not looking at paths.
            hits.append(f"{rel}  (binary, not scanned)")
            continue
        except OSError as exc:
            # Reported as a finding so the scan COMPLETES and still lists the
            # real hits elsewhere; raising aborted it and turned a diagnosable
            # failure into a bare non-zero exit.
            hits.append(f"{rel}  (unreadable: {exc.strerror}, not scanned)")
            continue
        hits.extend(scan_text(rel, text))
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
        ("python3 -m aed_eval replay", True),
        ("the .aed-cache directory", True),
        # Prose about Keysight's language must survive: this repository has to
        # be able to explain why the prefix moved.
        ("AEL: Application Extension Language, by Keysight.", False),
        ("## AEL: why the prefix moved", False),
        ("Keysight's AEL is a different thing entirely.", False),
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

    failures = 0
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
        f"{len(text_cases) + len(path_cases)} cases."
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
