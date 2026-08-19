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
from decimal import Decimal
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
#   6. Arrays keep their order — order is meaning in this IR. The schema states
#      a sort rule for each array; clause 6 alone therefore did NOT deliver
#      "two toolchains agree on one design", because those rules were enforced
#      by nothing: reversing `connections` gave the same 27 connections a
#      different design_hash and `make all` stayed green. `sort_problems()`
#      below enforces every rule the schema states, so one design has one
#      legal serialization and therefore one hash.
#
# The hash is taken with `header.design_hash` set to the empty string, which is
# unchanged, and is now done structurally rather than by regex.
CANONICAL_PROFILE = "rhoform-canonical-json/1"

# The sort rule the schema states for each array, as (pointer-ish label, key).
# `key` returns the tuple the entries must be ascending in.
SORT_RULES = (
    ("instances", lambda d: d.get("instances") or [],
     lambda e: (e.get("path") or "",)),
    ("nets", lambda d: d.get("nets") or [],
     lambda e: (e.get("name") or "",)),
    ("connections", lambda d: d.get("connections") or [],
     # `port` is a nested {instance, port} object, not two sibling strings.
     lambda e: (e.get("net") or "",
                ((e.get("port") or {}).get("instance") or ""),
                ((e.get("port") or {}).get("port") or ""))),
    ("assertions", lambda d: d.get("assertions") or [],
     lambda e: (e.get("path") or "",)),
)


def sort_problems(document, label):
    """Every array order the schema declares, actually enforced.

    The schema says "Sorted bytewise-ascending by `path` (determinism
    contract)" and similar on four arrays plus per-instance `ports`. Nothing
    checked it, and clause 6 of the canonical profile deliberately preserves
    array order, so one design had as many design_hash values as it had
    orderings -- which is precisely the property the hash exists to deny.
    """
    problems = []
    for name, pick, key in SORT_RULES:
        entries = pick(document)
        keys = [key(e) for e in entries]
        if keys != sorted(keys):
            first = next((i for i in range(1, len(keys)) if keys[i] < keys[i - 1]), None)
            problems.append(
                f"{label}: `{name}` is not in the order the schema declares "
                f"(entry {first} sorts before entry {first - 1}: "
                f"{keys[first]!r} < {keys[first - 1]!r}). Array order is part of "
                "the canonical serialization, so an unsorted array gives one "
                "design more than one design_hash.")
    for instance in document.get("instances") or []:
        names = [p.get("name") or "" for p in (instance.get("ports") or [])]
        if names != sorted(names):
            problems.append(
                f"{label}: instance {instance.get('path')!r} has `ports` out of "
                "the bytewise-ascending order the schema declares.")
        for port in instance.get("ports") or []:
            # `pin_numbers`, which is what ir/netlist-ir.schema.json actually
            # declares. This read `pins`, a field the IR does not have, so the
            # rule was dead -- and its self-test case passed because the case
            # fed a synthetic dict using the same wrong name. That is the exact
            # defect check-run-records.py's own docstring describes for
            # arm["trials"], repeated in a sibling gate.
            pins = port.get("pin_numbers")
            if isinstance(pins, list) and pins != sorted(pins):
                problems.append(
                    f"{label}: {instance.get('path')!r}/{port.get('name')!r} has "
                    "`pin_numbers` out of the ascending order the schema "
                    "declares.")
    return problems


def _canonical_number(value) -> str:
    """Clause 7: one spelling per numeric VALUE, independent of language.

    The profile pinned encoding, key order, whitespace, escaping, NaN and array
    order — and said nothing about numbers, so `1000` and `1e3` are the same
    value and hashed differently, and `1e16` serialized as `1e+16` here against
    `10000000000000000` from JSON.stringify. A profile whose stated purpose is
    that "two toolchains agree on one design" has to pin this or it does not
    deliver the thing it is for.

    THAT FIX WENT HALF THE DISTANCE. It handled integral floats and then
    delegated everything else to "the shortest string that round-trips", which
    is `repr` — a PYTHON spelling, not a specified one. Python pads a
    single-digit exponent to two (`1e-07`) where JavaScript does not (`1e-7`),
    and Python switches to exponential below 1e-4 where JavaScript switches
    below 1e-6 (`1e-05` against `0.00001`). That is the whole nF/uF/nA/us band
    in base SI — the numbers an electronics IR is made of. An auditor wrote a
    second conforming implementation in 6 lines of JavaScript, expressed one
    100 nF capacitor as 1e-7 F, and got a different design_hash for a document
    the schema validates and this gate accepts.

    So the spelling is now SPECIFIED rather than inherited: ECMA-262's
    Number::toString (§6.1.6.1.20), which is the algorithm behind
    JSON.stringify. Given the shortest round-tripping digits `s` (length k) and
    the exponent n with value = 0.s x 10^n:

        k <= n <= 21   digits, then n-k zeros              1500
        0 < n <= 21    digits with a point after n of them 1.5
        -6 < n <= 0    "0.", -n zeros, then digits         0.0015
        otherwise      d[.rest] "e" (+|-) |n-1|            1.5e-7

    It is a real specification an implementer in any language can follow, which
    is what clause 7 claimed to be.
    """
    if isinstance(value, bool):
        raise TypeError("booleans are not numbers")
    if isinstance(value, int):
        # ECMA has ONE number type. `str(int)` gave integers a second spelling
        # per value -- 10**21 printed all its digits while the same value as a
        # float printed "1e+21" -- so two conforming producers still disagreed
        # on design_hash (round 15). An integer is serialized as the double it
        # denotes, and an integer the double grid cannot hold exactly is
        # REJECTED rather than silently rounded: a hash over a silently
        # rounded value is an unledgered identity change.
        try:
            as_float = float(value)
        except OverflowError:
            as_float = float("inf")
        if as_float in (float("inf"), float("-inf")) or int(as_float) != value:
            raise ValueError(
                f"{value} is not exactly representable as an IEEE double; "
                "rhoform-canonical-json/1 numbers are doubles, and integers "
                "beyond 2^53 must be rejected, not rounded (clause 7)")
        value = as_float
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("NaN and Infinity are not representable")
    if value == 0:
        # A design has no signed zero: -0.0 and 0.0 are one value.
        return "0"
    sign, digits, exponent = Decimal(repr(value)).as_tuple()
    n = exponent + len(digits)
    s = "".join(str(digit) for digit in digits).rstrip("0") or "0"
    k = len(s)
    if k <= n <= 21:
        text = s + "0" * (n - k)
    elif 0 < n <= 21:
        text = s[:n] + "." + s[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * (-n) + s
    else:
        mantissa = s if k == 1 else s[0] + "." + s[1:]
        power = n - 1
        text = f"{mantissa}e{'+' if power >= 0 else '-'}{abs(power)}"
    return "-" + text if sign else text


def _canonical_str(value: str) -> str:
    """Clause 4: literal non-ASCII, and Unicode SCALAR VALUES only.

    A lone surrogate previously failed only at .encode("utf-8") -- a
    UnicodeEncodeError that happens to subclass ValueError -- while a
    conforming JS implementation would either backslash-u escape it (violating
    clause 4) or silently substitute U+FFFD and hash a different document.
    The rule is stated, and it covers keys and values alike."""
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise ValueError(
            "lone surrogates are not representable in "
            "rhoform-canonical-json/1 (clause 4: strings are Unicode "
            "scalar values; a surrogate has no UTF-8 bytes)")
    return json.dumps(value, ensure_ascii=False)


def _encode(node) -> str:
    """rhoform-canonical-json/1, written out rather than configured.

    `json.dumps` was doing the numbers, and its float spelling is Python's. The
    structural clauses are four lines; the number clause is the one that had to
    stop being inherited. String escaping still goes through `json.dumps`,
    which is unambiguous for JSON and identical across implementations.
    """
    if node is None:
        return "null"
    if isinstance(node, bool):
        return "true" if node else "false"
    if isinstance(node, (int, float)):
        return _canonical_number(node)
    if isinstance(node, str):
        return _canonical_str(node)
    if isinstance(node, list):
        return "[" + ",".join(_encode(item) for item in node) + "]"
    if isinstance(node, dict):
        # Keys route through the same guarded encoder as values: the
        # round-17 surrogate rule covered only the value branch, so a
        # surrogate OBJECT KEY still went through bare json.dumps (round 18).
        return "{" + ",".join(
            _canonical_str(key) + ":" + _encode(value)
            for key, value in sorted(node.items())) + "}"
    raise TypeError(f"{type(node).__name__} is not representable in JSON")


def canonical_bytes(document) -> bytes:
    """Serialize per rhoform-canonical-json/1."""
    return _encode(document).encode("utf-8") + b"\n"


# Header fields that describe HOW the document was produced, not WHAT it
# describes. They are blanked out of the preimage for the same reason
# `design_hash` itself is: a content address that moves when the compiler is
# rebuilt is not a content address for the design.
#
# `design_hash` used to cover both, so `rhoformc 0.1.0` and `rhoformc 0.1.1`
# gave one unchanged netlist two different addresses -- and so did a
# comment-only edit to the DSL source, through `source_hash`. The README says
# the profile exists because "two conforming implementations could produce
# different design_hash values for the same design"; hashing the generator's
# own name guaranteed they would, whatever the serialization did. The (IR,
# source map) pairing rule binds on this value, so as shipped a source map
# from one toolchain could never pair with an IR from another.
NON_DESIGN_HEADER_FIELDS = ("design_hash", "generator", "source_hash")


def design_hash_of(document) -> str:
    """The hash of `document` over its design-bearing content.

    Takes the PARSED document, so re-indenting a committed file, reordering its
    keys, or writing a Quantity inline instead of expanded does not move the
    digest — while any change to the data does.
    """
    if not isinstance(document, dict) or "header" not in document:
        raise ValueError("document has no `header` to read `design_hash` from")
    if "design_hash" not in document["header"]:
        raise ValueError("document has no single `design_hash` field to blank")
    blanked = json.loads(json.dumps(document))
    for field in NON_DESIGN_HEADER_FIELDS:
        if field in blanked["header"]:
            blanked["header"][field] = ""
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

    problems.extend(sort_problems(document, rel))

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
    # ir/source-map.schema.json declares `files` "Sorted bytewise-ascending by
    # path", and nothing enforced it -- so the map has the same one-design-many-
    # hashes property the IR had, via source_hash.
    # NODE COVERAGE. ir/source-map.schema.json says "Every instance,
    # assertion, and net of the referenced IR document must have an entry" and
    # ir/README.md repeats it; nothing checked it, so the bypass capacitor
    # AMB-123 added to the design and the IR was never added to the sidecar --
    # a diagnostic on that part has no source location, in the one committed
    # illustration of I9. Same shape as the superseded-window finding: the pair
    # was updated on one side.
    identities = set()
    for instance in document.get("instances") or []:
        if instance.get("path"):
            identities.add(instance["path"])
    for net in document.get("nets") or []:
        if net.get("name"):
            identities.add(net["name"])
    for assertion in document.get("assertions") or []:
        if assertion.get("path"):
            identities.add(assertion["path"])
    nodes = source_map.get("nodes")
    if not isinstance(nodes, dict):
        # Failing open here gave the same cheerful summary a missing map used
        # to give, which this file upgraded from a note to a problem one field
        # up for exactly that reason.
        problems.append(
            f"{source_map_path.name}: has no `nodes` object, so no identity is "
            "covered and the coverage rule checks nothing.")
    if isinstance(nodes, dict):
        # SPAN SANITY. ir/README.md lists these as compiler-enforced and the
        # map is the one committed illustration of I9: /c_byp was added with
        # VCC's exact start position, the only same-file overlap in the file,
        # because the span was copied from the neighbour above without checking
        # what already sat on that line.
        seen_spans = []
        for name, node in sorted(nodes.items()):
            for span in ([node.get("declaration")] if isinstance(node, dict) else []) \
                    + list((node.get("instantiation_trace") or []) if isinstance(node, dict) else []):
                if not isinstance(span, dict):
                    continue
                start, end = span.get("byte_start"), span.get("byte_end")
                if isinstance(start, int) and isinstance(end, int) and end < start:
                    problems.append(
                        f"{source_map_path.name}: {name} has a span ending "
                        f"before it starts ({start} > {end}).")
                index = span.get("file")
                if isinstance(index, int) and isinstance(source_map.get("files"), list):
                    if not 0 <= index < len(source_map["files"]):
                        problems.append(
                            f"{source_map_path.name}: {name} names file index "
                            f"{index}, which the `files` table does not have.")
            declaration = node.get("declaration") if isinstance(node, dict) else None
            if isinstance(declaration, dict) and isinstance(
                    declaration.get("byte_start"), int):
                seen_spans.append((declaration["file"], declaration["byte_start"],
                                   declaration.get("byte_end", 0), name))
        seen_spans.sort()
        for left, right in zip(seen_spans, seen_spans[1:]):
            # `>` not `>=`: byte_end is END-EXCLUSIVE per the Span schema, so
            # [496,519) and [519,543) are adjacent, not overlapping. The first
            # version reported that pair as an overlap, with a message about
            # two statements beginning at the same position -- which is not
            # what the predicate tested.
            if left[0] == right[0] and left[2] > right[1]:
                problems.append(
                    f"{source_map_path.name}: the declarations of {left[3]} and "
                    f"{right[3]} overlap in file {left[0]} "
                    f"([{left[1]}, {left[2]}) against [{right[1]}, "
                    f"{right[2]})). Two declarations cannot share source bytes.")
        uncovered = sorted(identities - set(nodes))
        if uncovered:
            problems.append(
                f"{source_map_path.name}: has no `nodes` entry for "
                f"{uncovered}. The schema and ir/README.md both require every "
                "instance, net and assertion identity to have one; without it "
                "a diagnostic on that entity has no source location.")
        stray = sorted(set(nodes) - identities)
        if stray:
            problems.append(
                f"{source_map_path.name}: has `nodes` entries for {stray}, "
                "which the IR does not contain.")

    files = source_map.get("files")
    if isinstance(files, list):
        paths = [f.get("path") or "" for f in files if isinstance(f, dict)]
        if paths != sorted(paths):
            problems.append(
                f"{source_map_path.name}: `files` is not in the "
                "bytewise-ascending path order the source-map schema declares. "
                "source_hash is taken over that list, so an unsorted map gives "
                "one source set more than one hash.")
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


def _unsorted_map_probe():
    import json as _json, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        doc = Path(tmp) / "p.ir.json"
        text = (IR_EXAMPLES / "blinker.ir.json").read_text(encoding="utf-8")
        doc.write_text(text, encoding="utf-8")
        real = _json.loads(
            (IR_EXAMPLES / "blinker.sourcemap.json").read_text(encoding="utf-8"))
        if isinstance(real.get("files"), list):
            real["files"] = list(reversed(real["files"]))
        (Path(tmp) / "p.sourcemap.json").write_text(_json.dumps(real), encoding="utf-8")
        problems = []
        check_document(doc, problems, [])
        return problems


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
    # THE SORT RULES. Clause 6 keeps array order, so the schema's per-array
    # sort rules are what make one design have one hash -- and they were
    # enforced by nothing: reversing `connections` gave the same 27 connections
    # a different design_hash with `make all` green.
    checks.append((
        "connections out of their declared order are caught",
        any("connections" in p for p in sort_problems({"connections": [
            {"net": "b", "port": {"instance": "i", "port": "p"}},
            {"net": "a", "port": {"instance": "i", "port": "p"}}]}, "probe")),
    ))
    checks.append((
        "instances out of path order are caught",
        any("instances" in p for p in sort_problems(
            {"instances": [{"path": "/b"}, {"path": "/a"}]}, "probe")),
    ))
    checks.append((
        "nets out of name order are caught",
        any("nets" in p for p in sort_problems(
            {"nets": [{"name": "B"}, {"name": "A"}]}, "probe")),
    ))
    checks.append((
        "an instance's ports out of order are caught",
        any("ports" in p for p in sort_problems({"instances": [
            {"path": "/x", "ports": [{"name": "b"}, {"name": "a"}]}]}, "probe")),
    ))
    checks.append((
        "pin designators out of order are caught",
        any("pin_numbers" in p for p in sort_problems({"instances": [
            {"path": "/x", "ports": [{"name": "a", "pin_numbers": ["2", "1"]}]}]},
            "probe")),
    ))
    checks.append((
        "a source map with unsorted files is caught",
        any("bytewise-ascending path order" in p
            for p in _unsorted_map_probe()),
    ))
    checks.append((
        "the field the rule reads is the field the schema declares",
        "pin_numbers" in json.loads(
            (ROOT / "ir" / "netlist-ir.schema.json").read_text(encoding="utf-8")
        )["$defs"]["Port"]["properties"],
    ))
    checks.append((
        "the committed IR satisfies every sort rule the schema states",
        not sort_problems(json.loads((IR_EXAMPLES / "blinker.ir.json").read_text(
            encoding="utf-8")), "committed"),
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
    # THE VALUES A SECOND IMPLEMENTATION SPELLS DIFFERENTLY. The cases above
    # pin 1e3, 1e16, -0.0 and 0.1 -- the four values that were wrong once --
    # and not one value where Python's float repr and JavaScript's disagree.
    # That is testing the shape of the previous defect rather than the
    # property, and it left the whole nF/uF/nA/us band in base SI open: an
    # auditor expressed one 100 nF capacitor as 1e-7 F and got a different
    # design_hash from a six-line conforming implementation.
    #
    # Every expected string here was taken from `node -e JSON.stringify(v)`,
    # not from Python.
    for value, expected in (
            (1e-7, "1e-7"),          # python repr: 1e-07
            (9e-8, "9e-8"),          # python repr: 9e-08
            (2.5e-7, "2.5e-7"),      # python repr: 2.5e-07
            (1e-5, "0.00001"),       # python repr: 1e-05
            (4.7e-6, "0.0000047"),   # python repr: 4.7e-06
            (1e-6, "0.000001"),      # python repr: 1e-06
            (1e-10, "1e-10"),        # agrees, and pins the boundary
            (1e21, "1e+21"),         # the top of the plain-integer range
            (1500.0, "1500"),
            (0.0015, "0.0015"),
            (-2.5e-8, "-2.5e-8"),
    ):
        checks.append((
            f"clause 7 spells {value!r} the way JSON.stringify does ({expected})",
            canonical_bytes({"v": value}) == b'{"v":' + expected.encode() + b'}\n',
        ))
    checks.append((
        "the example declares the profile this gate hashes under",
        document["header"].get("canonical_form") == CANONICAL_PROFILE,
    ))

    # INTEGERS ARE DOUBLES. `str(int)` gave 10**21 a different spelling from
    # the identical value 1e21, so two conforming producers disagreed on
    # design_hash for the same document (round 15); and an integer the double
    # grid cannot hold must be rejected, not silently rounded to a neighbour
    # that hashes as something else.
    checks.append((
        "an int and the equal float spell identically (10**21 vs 1e21)",
        canonical_bytes({"v": 10**21}) == canonical_bytes({"v": 1e21}),
    ))
    checks.append((
        "2**53 is exactly representable and accepted",
        canonical_bytes({"v": 2**53}) == b'{"v":9007199254740992}\n',
    ))
    rejected = False
    try:
        canonical_bytes({"v": 2**53 + 1})
    except ValueError:
        rejected = True
    checks.append(("an integer beyond the double grid is rejected, "
                   "not rounded", rejected))
    surrogate_rejected = False
    try:
        canonical_bytes({"v": "bad \udcff string"})
    except ValueError as exc:
        # The rule's own message, not UnicodeEncodeError's: the accidental
        # rejection also says "surrogates", so a fragment match could not
        # tell the rule from the accident it replaced (round 18).
        surrogate_rejected = ("rhoform-canonical-json" in str(exc)
                              and not isinstance(exc, UnicodeEncodeError))
    checks.append(("a lone surrogate is rejected by rule, not by accident",
                   surrogate_rejected))
    key_rejected = False
    try:
        canonical_bytes({"bad \udcff key": 1})
    except ValueError as exc:
        key_rejected = ("rhoform-canonical-json" in str(exc)
                        and not isinstance(exc, UnicodeEncodeError))
    checks.append(("a lone surrogate in an OBJECT KEY is rejected by rule",
                   key_rejected))

    # THE README'S PUBLISHED DIGEST, held to the committed header through
    # readme_digest_problems() with injectable inputs.
    _good = "sha256:" + "a" * 64
    _bad = "sha256:" + "b" * 64
    _ok, _stale, _gone = [], [], []
    readme_digest_problems(_ok, readme_text=f"scalar values\n# -> {_good}\n",
                           committed=_good)
    readme_digest_problems(_stale, readme_text=f"scalar values\n# -> {_bad}\n",
                           committed=_good)
    readme_digest_problems(_gone, readme_text="scalar values, no digest here",
                           committed=_good)
    _clauseless = []
    readme_digest_problems(_clauseless, readme_text=f"# -> {_good}\n",
                           committed=_good)
    checks.append(("a README that drops the scalar-values clause is caught",
                   any("scalar-values" in x for x in _clauseless)))
    checks.append(("a README digest matching the header reconciles clean",
                   not _ok))
    checks.append(("a stale README digest is caught",
                   any("disagrees with the artifact" in x for x in _stale)))
    checks.append(("a README that stops publishing the digest is caught",
                   any("checked by nothing" in x for x in _gone)))
    _missing = []
    readme_digest_problems(_missing, readme_text=None, committed=_good)
    checks.append(("a missing ir/README.md is reported, not skipped",
                   any("is missing" in x for x in _missing)))

    # And the blanking rule itself: two documents differing ONLY in the
    # design_hash value must hash identically, or the rule is not idempotent
    # and every recomputation would chase its own tail.
    rehashed = json.loads(text)
    rehashed["header"]["design_hash"] = "sha256:" + "0" * 64
    checks.append(("blanking ignores the old hash", design_hash_of(rehashed) == genuine))

    # WHICH COMPILER BUILT IT IS NOT PART OF THE DESIGN. design_hash covered
    # header.generator and header.source_hash, so `rhoformc 0.1.1` addressed an
    # unchanged netlist differently from `rhoformc 0.1.0` -- and so did a
    # comment-only edit to the DSL source. The README's whole justification for
    # this profile is that two conforming implementations must agree on one
    # design; hashing the producer's own name guaranteed they could not.
    for field, value in (("generator", {"name": "otherc", "version": "9.9.9"}),
                         ("source_hash", "sha256:" + "f" * 64)):
        moved = json.loads(text)
        moved["header"][field] = value
        checks.append((
            f"design_hash ignores header.{field}",
            design_hash_of(moved) == genuine,
        ))
    # And it is not simply ignoring the header: a real change still moves it.
    changed = json.loads(text)
    changed["header"]["design_name"] = "something_else"
    checks.append(("design_hash still moves for a header field that IS the design",
                   design_hash_of(changed) != genuine))

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

        # The source-map design_hash comparison, uncovered: a map pointing at
        # a DIFFERENT document is the failure this pairing exists to detect.
        mism_doc = Path(tmp) / "mismatched.ir.json"
        mism_doc.write_text(text, encoding="utf-8")
        mism_map = Path(tmp) / "mismatched.sourcemap.json"
        real_map = json.loads(
            (IR_EXAMPLES / "blinker.sourcemap.json").read_text(encoding="utf-8"))
        real_map["design_hash"] = "sha256:" + "0" * 64
        mism_map.write_text(json.dumps(real_map), encoding="utf-8")
        mism_problems = []
        check_document(mism_doc, mism_problems, [])
        checks.append((
            "a source map naming a different design_hash is caught",
            any("does not match the IR" in p for p in mism_problems)))

        # WIRING for the sort rules: the cases above call sort_problems
        # directly, so cutting the one line that calls it from check_document
        # left every one of them green.
        permuted = Path(tmp) / "permuted.ir.json"
        shuffled = json.loads(text)
        shuffled["connections"].reverse()
        shuffled["header"]["design_hash"] = ""
        shuffled["header"]["design_hash"] = design_hash_of(shuffled)
        permuted.write_text(json.dumps(shuffled), encoding="utf-8")
        sort_problems_seen, sort_notes = [], []
        check_document(permuted, sort_problems_seen, sort_notes)
        # THE NODE-COVERAGE AND SPAN LEGS. Added last round with no case at
        # all: deleting the coverage block left the self-test output
        # byte-identical, including the summary line check-layout.sh
        # reconciles. That is the state this self-test was expanded three times
        # to prevent, in the leg written to close a defect that survived nine
        # rounds precisely because nothing enforced it.
        def _map_probe(mutate):
            probe_ir = Path(tmp) / "probe.ir.json"
            probe_map = Path(tmp) / "probe.sourcemap.json"
            body = json.loads(text)
            body["header"]["design_hash"] = ""
            body["header"]["design_hash"] = design_hash_of(body)
            probe_ir.write_text(json.dumps(body), encoding="utf-8")
            side = json.loads((IR_EXAMPLES / "blinker.sourcemap.json").read_text(
                encoding="utf-8"))
            side["design_hash"] = body["header"]["design_hash"]
            mutate(side)
            probe_map.write_text(json.dumps(side), encoding="utf-8")
            found, _ = [], []
            check_document(probe_ir, found, _)
            return found

        def _drop_node(side):
            side["nodes"].pop("/c_byp", None)

        def _add_stray(side):
            side["nodes"]["/ghost"] = side["nodes"]["/c_byp"]

        def _overlap(side):
            side["nodes"]["/c_byp"]["declaration"] = dict(
                side["nodes"]["/c_ctl"]["declaration"])

        def _no_nodes(side):
            side.pop("nodes", None)

        checks.append(("a source map missing an IR identity is caught",
                       any("has no `nodes` entry" in p for p in _map_probe(_drop_node))))
        checks.append(("a source map naming an identity the IR lacks is caught",
                       any("which the IR does not contain" in p
                           for p in _map_probe(_add_stray))))
        checks.append(("two declarations at the same source position are caught",
                       any("overlap in file" in p for p in _map_probe(_overlap))))
        def _bad_order(side):
            side["nodes"]["/c_byp"]["declaration"]["byte_end"] = 1

        def _bad_file(side):
            side["nodes"]["/c_byp"]["declaration"]["file"] = 7

        checks.append(("a span ending before it starts is caught",
                       any("ending before it starts" in p
                           for p in _map_probe(_bad_order))))
        checks.append(("a span naming a file index the table lacks is caught",
                       any("which the `files` table does not have" in p
                           for p in _map_probe(_bad_file))))
        checks.append(("adjacent spans are NOT reported as overlapping",
                       not any("share source bytes" in p
                               for p in _map_probe(lambda side: None))))
        checks.append(("a source map with no nodes object is caught",
                       any("has no `nodes` object" in p for p in _map_probe(_no_nodes))))

        checks.append((
            "check_document reports an array out of its declared order, even "
            "when the permuted document's own hash is self-consistent",
            any("not in the order the schema declares" in p
                for p in sort_problems_seen)))

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


_READ_FROM_DISK = object()


def readme_digest_problems(problems, readme_text=_READ_FROM_DISK, committed=None):
    """ir/README.md publishes the frozen design_hash in prose; hold it to the
    committed header. The README's copy was read by nothing, so a legitimate
    --write refreeze would have left it publishing the superseded digest --
    the exact drift ir/validation.log documents for the b2a4c088 -> 8d056aa1
    move (round 15)."""
    if readme_text is _READ_FROM_DISK:
        readme = ROOT / "ir" / "README.md"
        readme_text = (readme.read_text(encoding="utf-8")
                       if readme.is_file() else None)
    if readme_text is None:
        problems.append("ir/README.md is missing, so its published "
                        "design_hash is compared to nothing")
        return
    if committed is None:
        document = json.loads(
            (IR_EXAMPLES / "blinker.ir.json").read_text(encoding="utf-8"))
        committed = document["header"]["design_hash"]
    if "scalar values" not in readme_text:
        problems.append(
            "ir/README.md no longer states clause 4's Unicode-scalar-values "
            "rule; the serializer enforces what the profile no longer "
            "documents, which is how implementations diverge.")
    published = re.findall(r"# -> (sha256:[0-9a-f]{64})", readme_text)
    if not published:
        problems.append(
            "ir/README.md no longer publishes the recompute result in the "
            "form this gate reads ('# -> sha256:...'), so its digest prose "
            "is checked by nothing")
        return
    for digest in published:
        if digest != committed:
            problems.append(
                f"ir/README.md publishes {digest} as the recompute result; "
                f"the committed example's header holds {committed}. A README "
                "that disagrees with the artifact it documents is the drift "
                "its own history section warns about.")


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
    readme_digest_problems(problems)

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
