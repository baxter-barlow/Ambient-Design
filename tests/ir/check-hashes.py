#!/usr/bin/env python3
"""Recompute the IR examples' content hashes and fail on mismatch.

`ir/examples/blinker.ir.json` carries `header.design_hash`, which `ir/README.md`
defines as a hash over the document's own canonical bytes, and the paired
source map mirrors it. Until this gate existed NOTHING recomputed either one:
the schemas gate and `ir/validate.sh` check shape, and the schema pins the
`^sha256:[0-9a-f]{64}$` pattern — that the value LOOKS like a hash, not that it
is the right one. So the worked example of the determinism contract was free to
carry a hash that did not describe its own bytes, with every gate green.

That is not a theoretical gap. Editing any string inside the IR changes its
bytes, so a perfectly executed rename — following a complete inventory, missing
nothing — silently produces a fixture whose hash is wrong. I2 and I5 make
byte-stable identity the thing AC4 gates on and `design_hash` is how the IR
expresses it, so an example allowed to drift from its own hash teaches the
wrong thing and is the artifact newcomers copy.

WHAT THIS CAN AND CANNOT CHECK, stated rather than blurred:

  design_hash          verifiable today, and verified here.
  source-map pairing   verifiable today: consumers must reject a pair whose
                       `design_hash` values disagree, so the two must match.
  source_hash          NOT verifiable yet. It hashes the `.rhoform` sources,
                       and none exist — the compiler is what will make it
                       honest. Reported as unverified, never as a pass.
  files[].sha256       same: each entry is checked the moment its file exists
                       on disk, and reported unverified until then.

Exit codes follow tests/structure/check-layout.sh: 0 pass, 1 mismatch, 2 when
the gate could not run.

    python3 tests/ir/check-hashes.py --self-test   # prove the check can fail
    python3 tests/ir/check-hashes.py
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IR_EXAMPLES = ROOT / "ir" / "examples"

# The blanking rule, verbatim from ir/README.md: the hash is taken over the
# document's bytes with the `design_hash` VALUE replaced by an empty string.
# Done textually rather than by re-serializing the parsed JSON, because the
# hash is over the committed bytes — re-serializing would silently normalize
# whitespace and key order and compute a hash of something else.
_DESIGN_HASH_RE = re.compile(r'("design_hash": )"[^"]*"')


def design_hash_of(text: str) -> str:
    blanked, count = _DESIGN_HASH_RE.subn(lambda m: m.group(1) + '""', text, count=1)
    if count != 1:
        raise ValueError("document has no single `design_hash` field to blank")
    return "sha256:" + hashlib.sha256(blanked.encode()).hexdigest()


def check_document(ir_path: Path, problems: list[str], notes: list[str]) -> None:
    text = ir_path.read_text(encoding="utf-8")
    rel = ir_path.relative_to(ROOT)
    document = json.loads(text)
    header = document.get("header", {})

    committed = header.get("design_hash")
    try:
        expected = design_hash_of(text)
    except ValueError as exc:
        problems.append(f"{rel}: {exc}")
        return
    if committed != expected:
        problems.append(
            f"{rel}: design_hash is {committed}, but the document's bytes hash "
            f"to {expected}. Recompute it; the content changed."
        )

    source_map_path = ir_path.with_name(ir_path.name.replace(".ir.json", ".sourcemap.json"))
    if not source_map_path.exists():
        notes.append(f"{rel}: no paired source map")
        return

    source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
    sm_rel = source_map_path.relative_to(ROOT)
    if source_map.get("design_hash") != committed:
        problems.append(
            f"{sm_rel}: design_hash {source_map.get('design_hash')} does not "
            f"match the IR's {committed}. A consumer must reject this pair, so "
            "the repository must not ship it."
        )

    # Source-side hashes. Every one is checked the moment its file exists.
    for entry in source_map.get("files", []):
        source_path = (ROOT / "ir" / entry["path"]).resolve()
        if not source_path.exists():
            notes.append(f"{sm_rel}: {entry['path']} does not exist yet")
            continue
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if digest != entry.get("sha256"):
            problems.append(
                f"{sm_rel}: {entry['path']} hashes to {digest}, not "
                f"{entry.get('sha256')}"
            )
    if header.get("source_hash"):
        notes.append(f"{rel}: source_hash covers sources that do not exist yet")


def self_test() -> int:
    """Prove the check fails on a document whose content moved.

    A gate nobody has watched fail is a gate nobody knows works — the same
    reason `parts/lint-part-data.py` runs its self-test first. The mutation is
    the one a rename performs: change a string, leave the hash alone.
    """
    ir_path = IR_EXAMPLES / "blinker.ir.json"
    text = ir_path.read_text(encoding="utf-8")

    checks = []

    genuine = design_hash_of(text)
    committed = json.loads(text)["header"]["design_hash"]
    checks.append(("the committed example verifies", genuine == committed))

    mutated = text.replace("aed.lib.", "rhoform.lib.", 1)
    checks.append(
        ("a renamed definition moves the hash", design_hash_of(mutated) != genuine)
    )

    # And the blanking rule itself: two documents differing ONLY in the
    # design_hash value must hash identically, or the rule is not idempotent
    # and every recomputation would chase its own tail.
    rehashed = _DESIGN_HASH_RE.sub(lambda m: m.group(1) + '"sha256:' + "0" * 64 + '"', text, count=1)
    checks.append(("blanking ignores the old hash", design_hash_of(rehashed) == genuine))

    try:
        design_hash_of('{"header": {}}')
        checks.append(("a document with no design_hash is rejected", False))
    except ValueError:
        checks.append(("a document with no design_hash is rejected", True))

    failed = 0
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
        failed += 0 if ok else 1
    if failed:
        print(f"ir-hashes: SELF-TEST FAILED: {failed} check(s)", file=sys.stderr)
        return 1
    print(f"ir-hashes: self-test PASS: {len(checks)} checks.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="prove the check can fail, then exit",
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()

    if not IR_EXAMPLES.is_dir():
        print(f"ir-hashes: FAIL: {IR_EXAMPLES} is missing", file=sys.stderr)
        return 2

    # `negative/` is deliberately malformed for the SCHEMA gate; its documents
    # are not required to be hash-consistent and checking them would make two
    # gates fight over the same fixtures.
    documents = sorted(p for p in IR_EXAMPLES.glob("*.ir.json"))
    if not documents:
        print("ir-hashes: FAIL: no IR examples found to check", file=sys.stderr)
        return 2

    problems: list[str] = []
    notes: list[str] = []
    for path in documents:
        check_document(path, problems, notes)

    for note in notes:
        print(f"ir-hashes: unverified: {note}")
    for problem in problems:
        print(f"ir-hashes: FAIL: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(
        f"ir-hashes: PASS: {len(documents)} document(s) hash to their committed "
        f"design_hash, and every paired source map agrees."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
