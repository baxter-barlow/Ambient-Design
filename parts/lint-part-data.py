#!/usr/bin/env python3
"""Lint Rhoform part-data (D3) records for invariants JSON Schema cannot express.

The schema in part-data.schema.json checks SHAPE. A meaningful part record
also has to be internally consistent, and several of those consistency
rules are cross-references between distant parts of the document, which
JSON Schema has no vocabulary for. Every place the schema says "the
part-library linter does" refers to a check implemented here.

Checks (each is a real defect that shape validation would let through):

  L1  provenance keys resolve to a location that exists in the document.
      An unresolvable pointer means the field it was meant to cover is
      silently unsourced, which is the exact failure per-field provenance
      exists to prevent.
  L2  every provenance source_id names a declared source.
  L3  source_id values are unique within the record.
  L4  modes[].draw[].pin names a declared pin whose role is power_in.
      Attributing supply draw to a signal pin would corrupt the T10 budget.
  L5  multi-unit consistency: unit pin membership exists, is disjoint from
      shared_pins, is disjoint between units, every pin's `unit` matches a
      declared unit, and on a multi-unit part every pin is accounted for.
  L6  shared_pins names declared pins.
  L7  pin names are unique, and no physical designator is claimed twice.
  L8  determinism: pins, modes, sources and draw entries are sorted as the
      schema requires, so records diff cleanly and hash reproducibly.
  L9  Measure bounds are ordered: min <= typ <= max where all are numeric.
  L10 the record's license_class is at least as restrictive as every
      source it cites, so republishing the record cannot leak a fact out
      of the licence it arrived under.
  L11 a provenance pointer addressing an element of a SORTED array echoes
      that element's identity. Without it, renaming one mode re-sorts the
      array and silently re-points every index-based citation at a
      different element - the pointer still resolves, so L1 cannot see it.
  L12 a pin's recommended window sits inside its absolute-maximum window.
      This containment is what makes abs_max mean anything; JSON Schema
      cannot compare two sibling objects.
  L13 physical designators are in ascending order, matching the ordering
      the schema documents. Documented and unchecked is how an ordering
      rule quietly stops being true.

Usage:
    lint-part-data.py [path ...]      lint records (default: parts/examples)
    lint-part-data.py --self-test     verify every check above actually fires

Exit codes: 0 pass, 1 lint failure, 2 usage/environment error.
"""

import json
import sys
from pathlib import Path

DEFAULT_TARGET = Path(__file__).resolve().parent / "examples"

# Restrictiveness ordering for L10. Higher means more restrictive.
LICENSE_RANK = {"open-cc": 0, "vendor-public": 1, "vendor-agreement": 2}


def unescape_token(token):
    """RFC 6901: ~1 is '/', ~0 is '~', and ~1 must be decoded first."""
    return token.replace("~1", "/").replace("~0", "~")


def pointer_resolves(doc, pointer):
    """True if an RFC 6901 pointer names an existing location in doc."""
    if pointer == "":
        return True
    if not pointer.startswith("/"):
        return False
    node = doc
    for raw in pointer.split("/")[1:]:
        token = unescape_token(raw)
        if isinstance(node, dict):
            if token not in node:
                return False
            node = node[token]
        elif isinstance(node, list):
            if not token.isdigit():
                return False
            index = int(token)
            if index >= len(node):
                return False
            node = node[index]
        else:
            return False
    return True


def pointer_target(doc, pointer):
    """Resolve a pointer and return the node, or None if it does not resolve."""
    if pointer == "":
        return doc
    if not pointer.startswith("/"):
        return None
    node = doc
    for raw in pointer.split("/")[1:]:
        token = unescape_token(raw)
        if isinstance(node, dict):
            if token not in node:
                return None
            node = node[token]
        elif isinstance(node, list):
            if not token.isdigit() or int(token) >= len(node):
                return None
            node = node[int(token)]
        else:
            return None
    return node


def identity_of(node):
    """The identity field of an addressable array element, if it has one."""
    if isinstance(node, dict):
        for key in ("id", "name", "source_id"):
            if key in node and isinstance(node[key], str):
                return node[key]
    return None


def walk_measures(node, path=""):
    """Yield (path, measure) for every object that looks like a Measure."""
    if isinstance(node, dict):
        if "unit" in node and any(k in node for k in ("min", "typ", "max", "peak")):
            yield path, node
        for key, value in node.items():
            yield from walk_measures(value, f"{path}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk_measures(value, f"{path}/{i}")


def lint(doc, label, unchecked=None):
    """Return a list of human-readable defects.

    `unchecked` collects checks that could not be PERFORMED on this record, as
    distinct from checks that failed. The two must not be conflated in either
    direction: reporting an unresolvable bound as a defect blames the record
    for a limitation of the data model, and skipping it silently — which is
    what happened until AMB-123 — leaves a containment gate covering some pins
    and not others with no way to tell which.
    """
    problems = []
    unchecked = problems if unchecked is None else unchecked

    def bad(check, message):
        problems.append(f"{label}: {check}: {message}")

    def cannot_check(check, message):
        unchecked.append(f"{label}: {check}: {message}")

    pins = doc.get("pins", [])
    pin_names = [p.get("name") for p in pins]
    pin_by_name = {p.get("name"): p for p in pins}
    sources = doc.get("sources", [])
    source_ids = [s.get("source_id") for s in sources]

    # L3 first: later checks reference source ids.
    if len(set(source_ids)) != len(source_ids):
        bad("L3", "duplicate source_id values in sources[]")

    # L1, L2, L11
    indexed_arrays = ("pins", "modes", "sources")
    for pointer, entry in sorted(doc.get("provenance", {}).items()):
        if not pointer_resolves(doc, pointer):
            bad("L1", f"provenance pointer {pointer!r} does not resolve to any location")
        sid = entry.get("source_id")
        if sid not in source_ids:
            bad("L2", f"provenance {pointer!r} cites unknown source_id {sid!r}")

        # L11: an index-addressed element of a sorted array must echo its
        # identity, or a re-sort silently re-points the citation.
        parts_ = pointer.split("/")
        if len(parts_) >= 3 and parts_[1] in indexed_arrays and parts_[2].isdigit():
            element = pointer_target(doc, "/".join(parts_[:3]))
            actual = identity_of(element)
            declared = entry.get("target")
            if actual is None:
                continue
            if declared is None:
                bad(
                    "L11",
                    f"provenance {pointer!r} addresses {parts_[1]}[{parts_[2]}] by index "
                    f"but declares no target; add \"target\": {actual!r} so a re-sort of "
                    "the array cannot silently re-point this citation",
                )
            elif declared != actual:
                bad(
                    "L11",
                    f"provenance {pointer!r} declares target {declared!r} but resolves to "
                    f"{actual!r}; the array was reordered without updating the citation",
                )

    # L4
    for i, mode in enumerate(doc.get("modes", [])):
        for j, draw in enumerate(mode.get("draw", [])):
            pin_name = draw.get("pin")
            pin = pin_by_name.get(pin_name)
            if pin is None:
                bad("L4", f"modes[{i}].draw[{j}] names unknown pin {pin_name!r}")
            elif pin.get("role") != "power_in":
                bad(
                    "L4",
                    f"modes[{i}].draw[{j}] attributes supply current to pin "
                    f"{pin_name!r} whose role is {pin.get('role')!r}, not power_in",
                )

    # L5, L6
    units = doc.get("units", [])
    shared = doc.get("shared_pins", [])
    for name in shared:
        if name not in pin_by_name:
            bad("L6", f"shared_pins names unknown pin {name!r}")

    if units:
        unit_ids = {u.get("id") for u in units}
        claimed = {}
        for unit in units:
            for name in unit.get("pins", []):
                if name not in pin_by_name:
                    bad("L5", f"unit {unit.get('id')!r} names unknown pin {name!r}")
                if name in shared:
                    bad(
                        "L5",
                        f"pin {name!r} is claimed by unit {unit.get('id')!r} and also "
                        "listed in shared_pins; a pin belongs to one or the other",
                    )
                if name in claimed:
                    bad(
                        "L5",
                        f"pin {name!r} is claimed by both unit {claimed[name]!r} "
                        f"and unit {unit.get('id')!r}",
                    )
                claimed[name] = unit.get("id")
        for pin in pins:
            name, declared = pin.get("name"), pin.get("unit")
            if declared is not None and declared not in unit_ids:
                bad("L5", f"pin {name!r} declares unit {declared!r}, which is not in units[]")
            if declared is None and name not in shared:
                bad(
                    "L5",
                    f"pin {name!r} on a multi-unit part belongs to no unit and is not "
                    "in shared_pins; every pin must be accounted for",
                )
            if declared is not None and claimed.get(name) != declared:
                bad(
                    "L5",
                    f"pin {name!r} declares unit {declared!r} but that unit does not "
                    "list it as a member",
                )
    else:
        for pin in pins:
            if pin.get("unit") is not None:
                bad("L5", f"pin {pin.get('name')!r} declares a unit but units[] is absent")

    # L7
    if len(set(pin_names)) != len(pin_names):
        bad("L7", "duplicate pin names")
    seen_designators = {}
    for pin in pins:
        for number in pin.get("numbers", []):
            if number in seen_designators:
                bad(
                    "L7",
                    f"physical designator {number!r} is claimed by both pin "
                    f"{seen_designators[number]!r} and pin {pin.get('name')!r}",
                )
            seen_designators[number] = pin.get("name")

    # L8
    def check_sorted(values, what):
        if values != sorted(values):
            bad("L8", f"{what} are not sorted bytewise-ascending (determinism contract)")

    check_sorted(pin_names, "pins[].name")
    check_sorted([m.get("id") for m in doc.get("modes", [])], "modes[].id")
    check_sorted(source_ids, "sources[].source_id")
    for i, mode in enumerate(doc.get("modes", [])):
        check_sorted([d.get("pin") for d in mode.get("draw", [])], f"modes[{i}].draw[].pin")

    # L9
    for path, measure in walk_measures(doc):
        ordered = [
            (key, measure[key])
            for key in ("min", "typ", "max")
            if isinstance(measure.get(key), (int, float))
        ]
        for (ka, va), (kb, vb) in zip(ordered, ordered[1:]):
            if va > vb:
                bad("L9", f"{path}: {ka}={va} exceeds {kb}={vb}")
        # `peak` sits outside the min/typ/max ordering because it is not a
        # guaranteed bound, but it still cannot fall below a guaranteed
        # minimum: an observed peak under the floor the vendor promises is
        # a transcription error, not a fact about the part.
        peak, lo = measure.get("peak"), measure.get("min")
        if isinstance(peak, (int, float)) and isinstance(lo, (int, float)) and peak < lo:
            bad("L9", f"{path}: peak={peak} is below the guaranteed min={lo}")

    # L12: a recommended window must sit inside its absolute-maximum window.
    # This is the containment that makes abs_max meaningful at all - a part
    # recommended to operate outside its own damage threshold is a defect in
    # the record, and no schema keyword can compare two sibling objects.
    for pin in pins:
        limits_abs, limits_rec = pin.get("abs_max") or {}, pin.get("recommended") or {}
        for quantity in ("voltage", "current"):
            a, r = limits_abs.get(quantity), limits_rec.get(quantity)
            if isinstance(r, dict) and not isinstance(a, dict):
                # A recommended window with NO absolute maximum to contain it.
                # This was `continue`d silently, so the shipped AP7361C accepted
                # a recommended current of -1000 A on a 1 A part. Same rule as
                # the relative-bound case: reported, never skipped.
                cannot_check("L12", f"pin {pin.get('name')!r}: recommended "
                                    f"{quantity} has no abs_max {quantity} to be "
                                    "contained by, so nothing bounds it")
                continue
            if not (isinstance(a, dict) and isinstance(r, dict)):
                continue
            # Never compare across units. Millivolts against volts would
            # both false-positive on a legitimate record and, worse, miss
            # real over-stress by a factor of a thousand.
            if a.get("unit") != r.get("unit"):
                bad("L12", f"pin {pin.get('name')!r}: recommended {quantity} is in "
                           f"{r.get('unit')!r} but abs_max is in {a.get('unit')!r}; "
                           "containment cannot be checked across units")
                continue
            a_lo, a_hi = a.get("min"), a.get("max")
            # A RelativeBound (`{reference, offset}`) is not a number, and this
            # loop's `isinstance(..., (int, float))` guards silently skipped
            # every one of them — including the case parts/README.md presents
            # as the interesting one. On the shipped AP7361C, whose
            # OUT.abs_max.voltage.max is `IN + 0.3 V`, a recommended maximum of
            # 100 V passed cleanly while the numeric sibling pin correctly
            # rejected 60 V against 6.5 V.
            #
            # Resolving the reference needs a supply value the record does not
            # carry, so this cannot be checked here. It is REPORTED as
            # unchecked rather than skipped: a containment gate that quietly
            # covers some pins and not others, with no way to tell which, is
            # the shape of gap this file exists to close.
            for endpoint, side in ((a_lo, "min"), (a_hi, "max")):
                if isinstance(endpoint, dict) and "reference" in endpoint:
                    cannot_check("L12", f"pin {pin.get('name')!r}: abs_max {quantity} "
                               f"{side} is a relative bound "
                               f"({endpoint.get('reference')}"
                               f"{endpoint.get('offset', 0):+g}), so containment "
                               "cannot be checked without a value for that "
                               "reference. Either state the bound numerically or "
                               "record the reference's value in the same record; "
                               "an unresolvable limit checks nothing.")
            for key in ("min", "typ", "max"):
                value = r.get(key)
                if not isinstance(value, (int, float)):
                    continue
                if isinstance(a_lo, (int, float)) and value < a_lo:
                    bad("L12", f"pin {pin.get('name')!r}: recommended {quantity} "
                               f"{key}={value} is below abs_max min={a_lo}")
                if isinstance(a_hi, (int, float)) and value > a_hi:
                    bad("L12", f"pin {pin.get('name')!r}: recommended {quantity} "
                               f"{key}={value} exceeds abs_max max={a_hi}")

    # L13: physical designators are documented as sorted ascending, for the
    # same determinism reason as every other ordering here. Documented and
    # unchecked is how an ordering rule quietly stops being true.
    for pin in pins:
        numbers = pin.get("numbers", [])
        if numbers != sorted(numbers, key=lambda n: (len(str(n)), str(n))):
            bad(
                "L13",
                f"pin {pin.get('name')!r}: numbers {numbers} are not in ascending "
                "order (natural sort: shorter designators first, then bytewise)",
            )

    # L10
    record_rank = LICENSE_RANK.get(doc.get("license_class"))
    if record_rank is not None:
        for source in sources:
            source_rank = LICENSE_RANK.get(source.get("license_class"))
            if source_rank is not None and source_rank > record_rank:
                bad(
                    "L10",
                    f"source {source.get('source_id')!r} is licensed "
                    f"{source.get('license_class')!r}, which is more restrictive than "
                    f"the record's {doc.get('license_class')!r}",
                )

    return problems


def valid_multi_unit_record():
    """A small record that passes every check; the self-test mutates it."""
    return {
        "schema_version": 0,
        "stability": "unstable",
        "part_id": "acme/dual",
        "manufacturer": "Acme",
        "mpn": "DUAL-1",
        "package": {"name": "SOIC-8", "pin_count": 8},
        "pins": [
            {"name": "1A", "numbers": ["1"], "role": "input", "unit": "1"},
            {"name": "1Y", "numbers": ["2"], "role": "output", "unit": "1"},
            {"name": "2A", "numbers": ["3"], "role": "input", "unit": "2"},
            {"name": "2Y", "numbers": ["4"], "role": "output", "unit": "2"},
            {"name": "GND", "numbers": ["5"], "role": "power_in"},
            {"name": "VCC", "numbers": ["8"], "role": "power_in"},
        ],
        "units": [
            {"id": "1", "pins": ["1A", "1Y"], "swappability_class": "g"},
            {"id": "2", "pins": ["2A", "2Y"], "swappability_class": "g"},
        ],
        "shared_pins": ["GND", "VCC"],
        "modes": [
            {
                "id": "active",
                "kind": "active",
                "draw": [{"pin": "VCC", "current": {"unit": "mA", "min": 1, "typ": 2, "max": 3}}],
            }
        ],
        "sources": [
            {
                "source_id": "acme-ds",
                "vendor": "acme",
                "url": "https://acme.example/ds.pdf",
                "state": "source-unreachable",
                "origin": "vendor-direct",
                "license_class": "vendor-public",
            }
        ],
        "provenance": {
            "": {"source_id": "acme-ds", "confidence": "datasheet-stated", "method": "manual"}
        },
        "license_class": "vendor-public",
    }


def self_test():
    """Every check must fire on a document that violates it, and the clean
    record must produce no findings. A linter whose checks are never shown
    to fire is indistinguishable from a linter that does nothing."""
    import copy

    clean = valid_multi_unit_record()
    findings = lint(clean, "clean")
    if findings:
        print("self-test FAIL: the reference record should lint clean but did not:")
        for f in findings:
            print(f"  {f}")
        return 1

    def mutate(fn):
        doc = copy.deepcopy(clean)
        fn(doc)
        return doc

    def set_provenance_key(doc, key):
        doc["provenance"][key] = {
            "source_id": "acme-ds",
            "confidence": "datasheet-stated",
            "method": "manual",
        }

    # EQUAL to the case count, not one below it: a floor with slack in it
    # permits exactly the silent drift it exists to name.
    MINIMUM_CASES = 27  # raise deliberately; drifting below is not a decision
    cases = [
        ("L1", "unresolvable provenance pointer", mutate(lambda d: set_provenance_key(d, "/pins/99/role"))),
        ("L2", "provenance cites unknown source", mutate(lambda d: d["provenance"].__setitem__("", {"source_id": "nope", "confidence": "unverified", "method": "manual"}))),
        ("L3", "duplicate source_id", mutate(lambda d: d["sources"].append(dict(d["sources"][0])))),
        ("L4", "supply draw on a signal pin", mutate(lambda d: d["modes"][0]["draw"][0].__setitem__("pin", "1A"))),
        ("L4", "supply draw on an unknown pin", mutate(lambda d: d["modes"][0]["draw"][0].__setitem__("pin", "NOPE"))),
        ("L5", "unit claims an unknown pin", mutate(lambda d: d["units"][0]["pins"].append("GHOST")), "names unknown pin"),
        ("L5", "pin in both a unit and shared_pins", mutate(lambda d: d["units"][0]["pins"].append("VCC")), "shared"),
        ("L5", "pin belongs to no unit and is not shared", mutate(lambda d: d["shared_pins"].remove("GND"))),
        ("L5", "pin declares an undeclared unit", mutate(lambda d: d["pins"][0].__setitem__("unit", "7")), "which is not in units[]"),
        # The third L5 clause. It had no case at all, so deleting it made a
        # genuine multi-unit inconsistency vanish entirely rather than merely
        # being mislabelled.
        ("L5", "pin declares a unit that does not list it",
         mutate(lambda d: d["pins"][0].__setitem__("unit", d["units"][1]["id"])),
         "does not list it as a member"),
        ("L6", "shared_pins names an unknown pin", mutate(lambda d: d["shared_pins"].append("GHOST"))),
        ("L7", "duplicate physical designator", mutate(lambda d: d["pins"][1]["numbers"].__setitem__(0, "1"))),
        ("L8", "pins out of sort order", mutate(lambda d: d["pins"].reverse())),
        ("L9", "min exceeds max", mutate(lambda d: d["modes"][0]["draw"][0]["current"].__setitem__("min", 99))),
        ("L10", "source stricter than record", mutate(lambda d: d["sources"][0].__setitem__("license_class", "vendor-agreement"))),
        ("L11", "indexed citation with no target echo", mutate(lambda d: set_provenance_key(d, "/modes/0"))),
        ("L11", "indexed citation whose target no longer matches", mutate(lambda d: d["provenance"].__setitem__("/modes/0", {"source_id": "acme-ds", "confidence": "datasheet-stated", "method": "manual", "target": "some_other_mode"}))),
        ("L11", "nested citation into a pin subtree with no target", mutate(lambda d: set_provenance_key(d, "/pins/0/role"))),
        ("L9", "peak below the guaranteed minimum", mutate(lambda d: d["modes"][0]["draw"][0]["current"].update({"peak": 0.5}))),
        ("L12", "recommended voltage above the absolute maximum", mutate(lambda d: d["pins"][5].update({"abs_max": {"voltage": {"unit": "V", "min": -0.5, "max": 7}}, "recommended": {"voltage": {"unit": "V", "min": 2, "typ": 5, "max": 9}}}))),
        # BRANCH-level cases. Disabling a whole check ID was caught; deleting an
        # individual clause inside one was not, for 8 of 10 clauses tried. Each
        # of these targets a clause that survived deletion.
        ("L7", "duplicate pin NAMES", mutate(lambda d: d["pins"][1].__setitem__("name", d["pins"][0]["name"]))),
        ("L12", "containment across different units", mutate(lambda d: d["pins"][5].update({"abs_max": {"voltage": {"unit": "mV", "min": -500, "max": 7000}}, "recommended": {"voltage": {"unit": "V", "min": 2, "typ": 5, "max": 6}}}))),
        ("L5", "pin declares a unit while units[] is absent", mutate(lambda d: (d.pop("units"), d.pop("shared_pins", None)))),
        ("L8", "modes[] out of sort order", mutate(lambda d: d["modes"].insert(0, dict(d["modes"][0], id="zzz_last_by_id")))),
        ("L8", "sources[] out of sort order", mutate(lambda d: d["sources"].append(dict(d["sources"][0], source_id="aaa-first")))),
        ("L12", "recommended voltage below the absolute minimum", mutate(lambda d: d["pins"][5].update({"abs_max": {"voltage": {"unit": "V", "min": 0, "max": 7}}, "recommended": {"voltage": {"unit": "V", "min": -3, "max": 5}}}))),
        ("L13", "physical designators out of ascending order", mutate(lambda d: d["pins"][0].__setitem__("numbers", ["9", "3"]))),
    ]

    failures = 0
    for entry in cases:
        check, description, doc = entry[0], entry[1], entry[2]
        fragment = entry[3] if len(entry) > 3 else None
        found = lint(doc, "case")
        # Match on the MESSAGE, not just the check ID. Matching on the ID meant
        # any L5 branch satisfied any L5 case, so three L5 clauses could be
        # deleted with the suite green — and for one of them the defect then
        # went entirely unreported.
        if any(f": {check}: " in f and (fragment is None or fragment in f)
               for f in found):
            print(f"self-test ok:   {check} fires on {description}")
        else:
            print(f"self-test FAIL: {check} did NOT fire on {description}")
            failures += 1

    # The UNCHECKED channel, which the `cases` loop above cannot see because it
    # only asks whether a PROBLEM was produced. Its two branches were deletable
    # with the self-test green — and they are the ones that keep L12's coverage
    # honest, so losing them silently would restore the exact gap the channel
    # was added to close.
    for description, mutation, fragment in (
        ("a relative abs_max bound",
         lambda d: d["pins"][5].update({
             "abs_max": {"voltage": {"unit": "V", "min": -0.5,
                                     "max": {"reference": "VCC", "offset": 0.3}}},
             "recommended": {"voltage": {"unit": "V", "min": 2, "typ": 5, "max": 6}}}),
         "relative bound"),
        ("a recommended window with no abs_max sibling",
         lambda d: d["pins"][5].update({
             "recommended": {"current": {"unit": "A", "min": -1000, "max": 0}}}),
         "no abs_max"),
    ):
        notes = []
        lint(mutate(mutation), "probe", notes)
        if any(fragment in note for note in notes):
            print(f"self-test ok:   L12 reports {description} as unchecked")
        else:
            print(f"self-test FAIL: L12 did NOT report {description} as unchecked")
            failures += 1

    # WIRING. self_test() called lint() and nothing else, so main()'s exit
    # branch was untested — and with it dead, every committed part record went
    # unchecked while both the Makefile and CI advertise the self-test as the
    # thing that stops a silent clean sweep.
    import contextlib as _c, io as _i
    _real, _argv = lint, sys.argv
    try:
        # main() re-reads sys.argv, which still says --self-test; without this
        # the probe re-enters self_test() and recurses.
        sys.argv = ["lint-part-data.py"]
        globals()["lint"] = lambda *_a, **_k: ["planted"]
        with _c.redirect_stdout(_i.StringIO()), _c.redirect_stderr(_i.StringIO()):
            _planted = main()
        globals()["lint"] = lambda *_a, **_k: []
        with _c.redirect_stdout(_i.StringIO()), _c.redirect_stderr(_i.StringIO()):
            _clean = main()
    finally:
        globals()["lint"], sys.argv = _real, _argv
    for _name, _ok in (("main() exits non-zero when lint reports a problem", _planted == 1),
                       ("main() exits zero when it does not", _clean == 0)):
        print(f"self-test {'ok:  ' if _ok else 'FAIL:'} {_name}")
        failures += 0 if _ok else 1

    if len(cases) < MINIMUM_CASES:
        print(f"self-test FAIL: only {len(cases)} defect cases, below the floor "
              f"of {MINIMUM_CASES}")
        failures += 1

    if failures:
        print(f"\nself-test: {failures} check(s) did not fire.")
        return 1
    print(f"\nself-test PASS: reference record lints clean; {len(cases)} defect cases all detected.")
    return 0


# How many checks may legitimately be unperformable across the whole record set.
# Today: two, both L12 containment on pins whose abs_max is relative. Raise it
# deliberately and name the record; drifting up is how a rule opts out of
# itself.
MAXIMUM_UNCHECKED = 2


def main() -> int:
    args = sys.argv[1:]
    if "--self-test" in args:
        return self_test()

    targets = [Path(a) for a in args] or [DEFAULT_TARGET]
    files = []
    for target in targets:
        if target.is_dir():
            files.extend(sorted(target.rglob("*.part.json")))
        elif target.is_file():
            files.append(target)
        else:
            print(f"lint: FAIL: no such path: {target}", file=sys.stderr)
            return 2

    if not files:
        # NOT a pass. `lint: PASS: 0 record(s) consistent` on an empty tree is
        # indistinguishable from a linter that does nothing, which is the
        # reasoning check-run-records.py already applies to itself.
        print("lint: FAIL: no *.part.json records found. A checker with "
              "nothing to check is indistinguishable from no checker; if the "
              "records legitimately moved, point this gate at them.",
              file=sys.stderr)
        return 1

    problems, unchecked = [], []
    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.append(f"{path}: does not parse as JSON: {exc}")
            continue
        # Expected-invalid schema fixtures are not lint subjects: they are
        # deliberately malformed, and linting them would report noise.
        if "negative" in path.parts:
            continue
        found = lint(doc, str(path), unchecked)
        problems.extend(found)
        if not found:
            print(f"lint: {path}: clean.")

    # Printed on every run, and counted in the pass line, so a growing set of
    # unresolvable bounds is visible rather than silently shrinking coverage.
    # A CEILING on unperformable checks. L12's containment rule becomes a
    # printed note whenever an abs_max is relative ({"reference": "VCC"}), and
    # nothing bounded how many checks could become notes -- so rewriting a
    # numeric abs_max as a relative one turned a firing L12 into silence, and
    # a +/-999 V recommended range on a pin whose abs_max is already relative
    # is indistinguishable from correct data. Four NE555 pins carry relative
    # bounds legitimately; that is the number this ceiling encodes.
    if len(unchecked) > MAXIMUM_UNCHECKED:
        print(f"lint: FAIL: {len(unchecked)} check(s) could not be performed, "
              f"above the ceiling of {MAXIMUM_UNCHECKED}. A rule that opts out "
              "of itself by changing the shape of the data it reads is not a "
              "rule; raise this deliberately and say which record needs it.",
              file=sys.stderr)
        for note in unchecked:
            print(f"  unchecked: {note}", file=sys.stderr)
        return 1
    for note in unchecked:
        print(f"lint: unchecked: {note}")

    if problems:
        for problem in problems:
            print(f"lint: FAIL: {problem}", file=sys.stderr)
        print(f"lint: {len(problems)} problem(s).", file=sys.stderr)
        return 1

    print(
        f"lint: PASS: {len([f for f in files if 'negative' not in f.parts])} "
        f"record(s) consistent, {len(unchecked)} check(s) not performable on the "
        "data as modelled."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
