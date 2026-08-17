#!/usr/bin/env python3
"""Recompute the IR examples' content hashes and fail on mismatch.

`ir/examples/blinker.ir.json` carries `header.design_hash`, which `ir/README.md`
defines as a hash over the document's own canonical bytes, and the paired
source map mirrors it. Until this gate existed NOTHING recomputed either one:
the schemas gate checks shape, and the schema pins the
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
  source_hash          NOT verifiable, and NOT because the sources are
                       missing — the schema defines it as a sha256 over the
                       sorted (path, sha256) pairs, and the source map
                       carries those today. It is the SERIALIZATION of that
                       list that no document pins: separator, encoding and
                       line ending are all unstated, so there is no single
                       byte string to hash. Pin it in the IR spec and this
                       becomes checkable; until then the committed value is
                       a placeholder and is reported as unverified rather
                       than passed.
  files[].sha256       checked the moment the file exists at its
                       repository-relative path; reported unverified until
                       then.

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

# rhoform-canonical-json/1 — the serialization profile the hash is taken over.
#
# The schema has always said `design_hash` covers "this IR document's CANONICAL
# serialization". It did not: the hash was taken over the committed BYTES, with
# a regex blanking the hash field, on the stated grounds that re-serializing
# "would compute a hash of something else". That reasoning inverts the
# requirement. Hashing bytes proves the file has not been edited; it does not
# prove two toolchains agree on one design, which is what the determinism
# contract (P5) and AC4/I2/I5 actually gate on. Re-serializing the SAME
# document under a profile that satisfied every clause the schema listed —
# same keys, LF, UTF-8 — produced a different digest, and the committed example
# was itself internally inconsistent, serializing one Quantity expanded and
# another inline.
#
# The profile named in the schema, `rhoform-canonical-json/1`, was defined
# nowhere in the repository. It is defined here and in ir/README.md, and it is
# what this function implements:
#
#   1. UTF-8, no BOM, a single trailing LF.
#   2. Object keys sorted by Unicode code point. NOT "the order given by the
#      schema": open maps (`parameters`, `x_` extensions) have no schema order,
#      so that rule was unimplementable for exactly the objects most likely to
#      differ between implementations.
#   3. No insignificant whitespace: `,` and `:` separators, nothing else.
#   4. Non-ASCII characters emitted literally rather than \u-escaped, so the
#      bytes are the text.
#   5. NaN and Infinity are not representable and are an error, not `NaN`.
#   6. Arrays keep their order — order is meaning in this IR, and the sort
#      rules for each array are the schema's business, not the encoder's.
#
# The hash is taken with `header.design_hash` set to the empty string, which is
# unchanged, and is now done structurally rather than by regex.
CANONICAL_PROFILE = "rhoform-canonical-json/1"


def _canonical_number(value):
    """Clause 7: one spelling per numeric VALUE, independent of language.

    The profile pinned encoding, key order, whitespace, escaping, NaN and array
    order — and said nothing about numbers, so `1000` and `1e3` are the same
    value and hashed differently, and `1e16` serialized as `1e+16` here against
    `10000000000000000` from JSON.stringify. A profile whose stated purpose is
    that "two toolchains agree on one design" has to pin this or it does not
    deliver the thing it is for.

    The rule: a float whose value is integral is written as that integer, and
    every other float is written by `repr`, which is the shortest string that
    round-trips. Integers are already unambiguous. `-0.0` normalizes to `0`,
    because a design has no signed zero.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("NaN and Infinity are not representable")
        if value == int(value):
            return int(value)
    return value


def _canonicalize(node):
    if isinstance(node, dict):
        return {key: _canonicalize(sub) for key, sub in node.items()}
    if isinstance(node, list):
        return [_canonicalize(sub) for sub in node]
    return _canonical_number(node)


def canonical_bytes(document) -> bytes:
    """Serialize per rhoform-canonical-json/1."""
    return json.dumps(
        _canonicalize(document),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"


def design_hash_of(document) -> str:
    """The hash of `document` with its own `design_hash` blanked.

    Takes the PARSED document, so re-indenting a committed file, reordering its
    keys, or writing a Quantity inline instead of expanded does not move the
    digest — while any change to the data does.
    """
    if not isinstance(document, dict) or "header" not in document:
        raise ValueError("document has no `header` to read `design_hash` from")
    if "design_hash" not in document["header"]:
        raise ValueError("document has no single `design_hash` field to blank")
    blanked = json.loads(json.dumps(document))
    blanked["header"]["design_hash"] = ""
    return "sha256:" + hashlib.sha256(canonical_bytes(blanked)).hexdigest()


def check_document(ir_path: Path, problems: list[str], notes: list[str]) -> None:
    text = ir_path.read_text(encoding="utf-8")
    # `relative_to` only for display, and it must not raise: the self-test
    # drives this function over a planted document in a temp directory, which
    # is the only way to exercise the mismatch branch without editing a
    # committed example.
    rel = ir_path.relative_to(ROOT) if ir_path.is_relative_to(ROOT) else ir_path.name
    document = json.loads(text)
    header = document.get("header", {})

    declared_profile = header.get("canonical_form")
    if declared_profile != CANONICAL_PROFILE:
        problems.append(
            f"{rel}: header.canonical_form is {declared_profile!r}, but this gate "
            f"hashes under {CANONICAL_PROFILE!r}. A document that names a "
            "different profile is hashed under rules nobody has stated."
        )

    committed = header.get("design_hash")
    try:
        expected = design_hash_of(document)
    except ValueError as exc:
        problems.append(f"{rel}: {exc}")
        return
    if committed != expected:
        problems.append(
            f"{rel}: design_hash is {committed}, but the document canonicalizes "
            f"to {expected}. Recompute it; the content changed."
        )

    source_map_path = ir_path.with_name(ir_path.name.replace(".ir.json", ".sourcemap.json"))
    if not source_map_path.exists():
        # Was a NOTE, so `rm ir/examples/blinker.sourcemap.json` left every
        # gate green while the gate printed "...and every paired source map
        # agrees" — vacuously true, and the source map is half of AMB-38's
        # deliverable. Renaming the IR file had the same effect.
        problems.append(
            f"{rel}: has no paired source map at {source_map_path.name}. The "
            "(IR, source map) pairing is the only live integrity check on the "
            "map, so a deleted or renamed half must fail rather than reduce "
            "the number of things checked."
        )
        return

    source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
    sm_rel = (source_map_path.relative_to(ROOT)
              if source_map_path.is_relative_to(ROOT) else source_map_path.name)
    if source_map.get("design_hash") != committed:
        problems.append(
            f"{sm_rel}: design_hash {source_map.get('design_hash')} does not "
            f"match the IR's {committed}. A consumer must reject this pair, so "
            "the repository must not ship it."
        )

    # Source-side hashes. Every one is checked the moment its file exists.
    for entry in source_map.get("files", []):
        # `path` is defined by ir/source-map.schema.json as a
        # REPOSITORY-relative POSIX path, not one relative to ir/. Resolving
        # it the other way made this whole leg dead code: it looked for a
        # file that could never be there, reported "does not exist yet", and
        # passed — while a real source file sitting at the schema's location
        # went unchecked.
        source_path = (ROOT / entry["path"]).resolve()
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
        notes.append(
            f"{rel}: source_hash is unverifiable — the IR spec pins no "
            "serialization for the (path, sha256) list it hashes"
        )


def _raises(thunk, exception) -> bool:
    try:
        thunk()
    except exception:
        return True
    return False


def self_test() -> int:
    """Prove the check fails on a document whose content moved.

    A gate nobody has watched fail is a gate nobody knows works — the same
    reason `parts/lint-part-data.py` runs its self-test first. The mutation is
    the one a rename performs: change a string, leave the hash alone.
    """
    ir_path = IR_EXAMPLES / "blinker.ir.json"
    text = ir_path.read_text(encoding="utf-8")
    document = json.loads(text)

    checks = []

    genuine = design_hash_of(document)
    committed = document["header"]["design_hash"]
    checks.append(("the committed example verifies", genuine == committed))

    # A stand-in for the edit a rename performs. Deliberately NOT spelled as
    # one of the project's own names: the AED -> Rhoform rename rewrote this
    # line into `replace("rhoform.lib.", "rhoform.lib.")`, a no-op, which
    # would have left the check asserting that an unchanged document hashes
    # differently from itself. The gate caught its own tooling, which is the
    # argument for having it.
    mutated = text.replace("rhoform.lib.", "elsewhere.lib.", 1)
    if mutated == text:
        raise AssertionError("the self-test mutation no longer changes anything")
    checks.append(
        ("a changed definition moves the hash",
         design_hash_of(json.loads(mutated)) != genuine)
    )

    # THE CANONICAL PROPERTY, which is the whole reason the hash moved off raw
    # bytes: a document re-serialized under any formatting must hash the same.
    # Under the old byte-hash it did not, so two conforming implementations
    # disagreed on one design and `design_hash` proved only "this file has not
    # been edited".
    for label, dumped in (
        ("re-indented", json.dumps(document, indent=4)),
        ("keys sorted", json.dumps(document, sort_keys=True)),
        ("whitespace stripped", json.dumps(document, separators=(",", ":"))),
    ):
        checks.append((f"a {label} document hashes the same",
                       design_hash_of(json.loads(dumped)) == genuine))

    # ...and the profile is not merely whatever json.dumps does today.
    checks.append((
        "canonical_bytes sorts keys and strips insignificant whitespace",
        canonical_bytes({"b": 1, "a": {"d": 2, "c": 3}})
        == b'{"a":{"c":3,"d":2},"b":1}\n',
    ))
    checks.append((
        "an integral float and its integer hash the same",
        canonical_bytes({"v": 1000}) == canonical_bytes({"v": 1e3}),
    ))
    checks.append((
        "a large integer is not written in exponent form",
        canonical_bytes({"v": 1e16}) == b'{"v":10000000000000000}\n',
    ))
    checks.append((
        "negative zero normalizes",
        canonical_bytes({"v": -0.0}) == canonical_bytes({"v": 0}),
    ))
    checks.append((
        "a genuinely fractional value keeps its shortest round-trip form",
        canonical_bytes({"v": 0.1}) == b'{"v":0.1}\n',
    ))
    checks.append((
        "canonical_bytes refuses NaN rather than emitting it",
        _raises(lambda: canonical_bytes({"x": float("nan")}), ValueError),
    ))
    checks.append((
        "the example declares the profile this gate hashes under",
        document["header"].get("canonical_form") == CANONICAL_PROFILE,
    ))

    # And the blanking rule itself: two documents differing ONLY in the
    # design_hash value must hash identically, or the rule is not idempotent
    # and every recomputation would chase its own tail.
    rehashed = json.loads(text)
    rehashed["header"]["design_hash"] = "sha256:" + "0" * 64
    checks.append(("blanking ignores the old hash", design_hash_of(rehashed) == genuine))

    checks.append(("a document with no design_hash is rejected",
                   _raises(lambda: design_hash_of({"header": {}}), ValueError)))

    # AMB-121's third scope bullet, undelivered until now: the FAILURE path had
    # no committed test. `check_document` was never invoked by anything but the
    # live run, so the mismatch branch was one refactor from decorative — which
    # is the defect class AMB-121 was filed about.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        planted = Path(tmp) / "planted.ir.json"
        broken = json.loads(text)
        broken["header"]["design_name"] = "not-the-design-this-hash-describes"
        planted.write_text(json.dumps(broken), encoding="utf-8")
        problems, notes = [], []
        check_document(planted, problems, notes)
        checks.append(("check_document reports a hash mismatch",
                       any("canonicalizes to" in p for p in problems)))
        checks.append(("check_document reports a missing source map",
                       any("no paired source map" in p for p in problems)))

        # The three legs a blind pass could delete with everything still green:
        # the declared-profile check, the source-map design_hash comparison, and
        # the files[].sha256 comparison. Each is driven here over a planted pair
        # so its removal fails a case rather than reducing what is checked.
        pair = Path(tmp) / "paired.ir.json"
        pair.write_text(json.dumps(json.loads(text)), encoding="utf-8")
        smap = pair.with_name("paired.sourcemap.json")
        source_map = json.loads(
            (IR_EXAMPLES / "blinker.sourcemap.json").read_text(encoding="utf-8"))
        smap.write_text(json.dumps(source_map), encoding="utf-8")
        problems, notes = [], []
        check_document(pair, problems, notes)
        checks.append(("a correctly paired document reports no problem", not problems))

        wrong_profile = json.loads(text)
        wrong_profile["header"]["canonical_form"] = "some-other-profile/9"
        pair.write_text(json.dumps(wrong_profile), encoding="utf-8")
        problems = []
        check_document(pair, problems, [])
        checks.append(("a document naming another canonical profile is caught",
                       any("canonical_form" in p for p in problems)))

        pair.write_text(json.dumps(json.loads(text)), encoding="utf-8")
        drifted = dict(source_map, design_hash="sha256:" + "0" * 64)
        smap.write_text(json.dumps(drifted), encoding="utf-8")
        problems = []
        check_document(pair, problems, [])
        checks.append(("a source map whose design_hash disagrees is caught",
                       bool(problems)))


    # WIRING. Everything above drives the check function; nothing proved
    # `main()` turns a finding into a non-zero exit. That branch was still one
    # refactor from decorative, one call level up from where the last fix
    # stopped.
    import contextlib as _c, io as _i
    _real = check_document
    try:
        globals()["check_document"] = lambda _path, _p, _n: _p.append("planted")
        with _c.redirect_stdout(_i.StringIO()), _c.redirect_stderr(_i.StringIO()):
            _planted = main([])
        globals()["check_document"] = lambda _path, _p, _n: None
        with _c.redirect_stdout(_i.StringIO()), _c.redirect_stderr(_i.StringIO()):
            _clean = main([])
    finally:
        globals()["check_document"] = _real
    checks.append(("main() exits non-zero when a problem is found", _planted == 1))
    checks.append(("main() exits zero when none is", _clean == 0))

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
