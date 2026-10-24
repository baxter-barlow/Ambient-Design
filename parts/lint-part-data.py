#!/usr/bin/env python3
"""Lint Rhoform part-data (D3) records for invariants JSON Schema cannot express.

The schemas (part-data.schema.json for version 0, part-data.v1.schema.json
for version 1) check SHAPE. A meaningful part record also has to be
internally consistent, and several of those consistency rules are
cross-references between distant parts of the document, which JSON Schema
has no vocabulary for. Every place a schema says "the part-data linter does"
refers to a check run here.

THE CHECKS LIVE IN rhoform/partdata.py (`lint_problems`, which lists L1-L22),
because the compiler runs the same rules on every record it loads and two
copies of a rule are two rules. This gate runs them over the repository's
records and adds what only the repository can check:

  - every record under parts/examples/ and in the bundled store
    rhoform/parts/ lints clean, and a record a benchmark picks (see
    BENCHMARK_PICKED) is held to the R29a field families;
  - every store record is in canonical layout (L22) -- its revision is the
    hash of its bytes -- sits at the path its part_id names, and implements
    at least one definition, since the store exists to be joined to one;
  - every LINT control under parts/examples/negative/ (one whose
    `x_negative_control` starts `LINT-REJECTED by <check> at <pointer>:`)
    fails with that check at those pointers and nothing else, the way
    tests/schemas/validate-schemas.py holds the schema controls;
  - NOTICE's provenance-coverage numbers are the records';
  - the named records are present, and the unperformable-check ceiling
    holds.

Usage:
    lint-part-data.py [path ...]      lint records (default: parts/examples
                                      and rhoform/parts)
    lint-part-data.py --self-test     verify every check above actually fires

Exit codes: 0 pass, 1 lint failure, 2 usage/environment error.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rhoform import partdata  # noqa: E402

EXAMPLES = ROOT / "parts" / "examples"
STORE = partdata.STORE
DEFAULT_TARGETS = (EXAMPLES, STORE)

# The lint core, re-exported under the names this gate has always used: the
# self-test plants `lint` to prove main() is wired to it.
lint = partdata.lint
walk_measures = partdata.walk_measures

# Records a benchmark picks, on which `not-transcribed` is refused for pin
# roles, abs-max and supply-current-per-mode (R29a). Today these are the
# three benchmark records the store holds. The landing that commits the
# benchmarks' lockfiles should derive this set from their picks rather than
# keep a list.
BENCHMARK_PICKED = (
    "diodes/ap7361c-33e-13",
    "espressif/esp32-s3-wroom-1-n8r2",
    "ti/ne555p",
)

# Controls cite sources at the reserved .example domain, which no vendor
# list may contain; the lint controls are linted against the real lists plus
# that one fixture vendor.
FIXTURE_DOMAINS = {**partdata.VENDOR_DOMAINS, "acme": ("acme.example",)}
LINT_CONTROL = re.compile(
    r"^LINT-REJECTED by (?P<check>L\d+) at (?P<locs>[^:]+):")
# EQUAL to the population, as the floors elsewhere are: a lint control that
# vanished, or stopped being recognised as one, must not leave this gate
# green with less evidence behind it.
MINIMUM_LINT_CONTROLS = 5


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


def valid_v1_record():
    """A v1 record using every member v1 adds; it lints clean, and the
    self-test mutates it once per v1 check clause."""
    gpio = {"vih": {"unit": "V", "min": {"reference": "VDD", "factor": 0.75}}}
    return {
        "schema_version": 1,
        "stability": "unstable",
        "part_id": "acme/mcu",
        "manufacturer": "Acme",
        "mpn": "MCU-1",
        "package": {"name": "QFN-6", "pin_count": 6},
        "pins": [
            {"name": "BOOT", "numbers": ["1"], "role": "bidirectional",
             "class": "gpio",
             "strap": {"function": "boot select", "default": "pull_up"}},
            {"name": "GND", "numbers": ["2"], "role": "power_in"},
            {"name": "MODE", "numbers": ["3"], "role": "bidirectional",
             "class": "gpio",
             "strap": {"function": "mode select", "default": "floating"}},
            {"name": "NC", "numbers": ["4"], "role": "nc"},
            {"name": "VDD", "numbers": ["5"], "role": "power_in",
             "abs_max": {"voltage": {"unit": "V", "max": 4}}},
            {"name": "VOUT", "numbers": ["6"], "role": "power_out",
             "output": {"voltage": [
                 {"unit": "V", "min": 1.7, "max": 1.9,
                  "conditions": {"iout": {"unit": "mA", "typ": 1}}},
                 {"unit": "V", "min": 1.6, "max": 1.9,
                  "conditions": {"iout": {"unit": "mA", "typ": 10}}}]}},
        ],
        "pin_classes": [
            {"id": "gpio", "role": "bidirectional", "characteristics": gpio},
        ],
        "implements": [
            {"definition": "acme.lib.Mcu",
             "pins": {"boot": "BOOT", "gnd": "GND", "mode": "MODE",
                      "vdd": "VDD"},
             "unbound": ["VOUT"]},
        ],
        "straps": [
            {"id": "flash", "kind": "valid", "when": {"BOOT": "1", "MODE": "x"}},
            {"id": "rom", "kind": "valid", "when": {"BOOT": "0", "MODE": "0"}},
        ],
        "absent": [
            {"pointer": "/parameters", "reason": "not-transcribed"},
            {"pointer": "/pin_classes/0/abs_max", "reason": "vendor-unpublished",
             "target": "gpio"},
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


def record_files():
    """Every record NOTICE's paragraph describes: the teaching set and the
    store, never the controls."""
    return sorted(EXAMPLES.glob("*.part.json")) + \
        sorted(STORE.glob("*/*.part.json"))


def _rel(path):
    path = Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) \
        else str(path)


def store_problems(path, data, doc, problems):
    """A bundled store record is pinned by its revision -- the hash of its
    bytes -- and found by its part_id, so both must be exact."""
    for problem in partdata.layout_problems(data):
        problems.append(f"{path}: {problem.check}: {problem.message}")
    part_id = doc.get("part_id")
    expected = partdata.store_path(part_id) if isinstance(part_id, str) \
        and part_id.count("/") == 1 else None
    if expected is None or Path(path).resolve() != expected.resolve():
        problems.append(
            f"{path}: store: part_id {part_id!r} belongs at "
            f"{_rel(expected) if expected else '<no valid path>'}; the store "
            "has no index, so a record anywhere else is one no lookup finds")
    if not doc.get("implements"):
        problems.append(
            f"{path}: store: implements no definition, so no design port can "
            "join it; the store holds records for definitions to bind to")
    return problems


def lint_control_problems(path, doc, problems, domains=None):
    """True if `doc` is a lint control; its failures go to `problems`.

    A control must fail with the check it names, at the pointers it names,
    and nowhere else. One that fails somewhere it does not declare would
    stay red with its own guarantee deleted, which is the gap the schema
    gate's location rule closed for the schema controls."""
    declaration = doc.get("x_negative_control") if isinstance(doc, dict) else None
    # A declaration that merely MENTIONS the prefix is held to the form too:
    # tests/schemas/validate-schemas.py exempts a control from the schema
    # only when the prefix comes first, nothing stripped, and a variant this
    # gate skipped silently would leave the two gates counting different
    # populations.
    if not isinstance(declaration, str) or "LINT-REJECTED" not in declaration:
        return False
    match = LINT_CONTROL.match(declaration)
    if match is None:
        problems.append(
            f"{path}: lint control does not declare where it fails; its "
            "x_negative_control must start, with nothing before it, "
            "`LINT-REJECTED by <check> at <pointer>[ + <pointer>...]: `")
        return True
    declared = {(match.group("check"), loc.strip())
                for loc in match.group("locs").split("+") if loc.strip()}
    found = {(p.check, p.pointer) for p in partdata.lint_problems(
        doc, [], domains=FIXTURE_DOMAINS if domains is None else domains)}
    if not found:
        problems.append(
            f"{path}: lint control declares {sorted(declared)} and lints "
            "clean, so the check it exists to prove no longer fires")
    elif found != declared:
        problems.append(
            f"{path}: lint control declares it fails at {sorted(declared)} "
            f"but actually fails at {sorted(found)}")
    return True


def lint_control_floor_problems(count, problems, minimum=None):
    """The lint-control population may not shrink by accident."""
    minimum = MINIMUM_LINT_CONTROLS if minimum is None else minimum
    if count < minimum:
        problems.append(
            f"{count} lint control(s), below the floor of {minimum}. They are "
            "the fixtures showing the cross-reference checks reject a whole "
            "record, not only a mutated dict in this file.")
    return problems


def self_test():
    """Every check must fire on a document that violates it, and the clean
    record must produce no findings. A linter whose checks are never shown
    to fire is indistinguishable from a linter that does nothing."""
    import copy
    import tempfile

    hosts = FIXTURE_DOMAINS
    for name, clean in (("v0", valid_multi_unit_record()),
                        ("v1", valid_v1_record())):
        findings = lint(clean, "clean", domains=hosts)
        if findings:
            print(f"self-test FAIL: the {name} reference record should lint "
                  "clean but did not:")
            for f in findings:
                print(f"  {f}")
            return 1

    def mutate(fn, base=valid_multi_unit_record):
        doc = copy.deepcopy(base())
        fn(doc)
        return doc

    def v1(fn):
        return mutate(fn, valid_v1_record)

    def set_provenance_key(doc, key):
        doc["provenance"][key] = {
            "source_id": "acme-ds",
            "confidence": "datasheet-stated",
            "method": "manual",
        }

    def put(doc, pointer, value):
        *head, last = pointer.split("/")[1:]
        node = doc
        for token in head:
            node = node[int(token)] if isinstance(node, list) else node[token]
        node[last] = value

    # EQUAL to the case count, not one below it: a floor with slack in it
    # permits exactly the silent drift it exists to name.
    MINIMUM_CASES = 56  # raise deliberately; drifting below is not a decision
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
        ("L5", "a unit pin claimed by two units", mutate(lambda d: d["units"][1]["pins"].append("1A")), "claimed by both unit"),
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
        ("L8", "draw[] out of sort order", mutate(lambda d: d["modes"][0]["draw"].append({"pin": "GND", "current": {"unit": "mA", "typ": 1}})), "draw[].pin"),
        ("L12", "recommended voltage below the absolute minimum", mutate(lambda d: d["pins"][5].update({"abs_max": {"voltage": {"unit": "V", "min": 0, "max": 7}}, "recommended": {"voltage": {"unit": "V", "min": -3, "max": 5}}}))),
        ("L13", "physical designators out of ascending order", mutate(lambda d: d["pins"][0].__setitem__("numbers", ["9", "3"]))),
        # v1. One case per clause of each check v1 adds (L14-L21).
        ("L14", "implements[] with a definition twice", v1(lambda d: d["implements"].append(copy.deepcopy(d["implements"][0]))), "sorted bytewise-ascending by definition"),
        ("L14", "a definition pin mapped to no record pin", v1(lambda d: d["implements"][0]["pins"].__setitem__("vdd", "VCC")), "which is not a pin of this record"),
        ("L14", "two definition pins on one record pin", v1(lambda d: d["implements"][0]["pins"].__setitem__("vdd2", "VDD")), "must be injective"),
        ("L14", "unbound[] out of sort order", v1(lambda d: d["implements"][0].__setitem__("unbound", ["VOUT", "NC"])), "unbound[] is not sorted"),
        ("L14", "unbound names no record pin", v1(lambda d: d["implements"][0]["unbound"].append("ZZZ")), "unbound names 'ZZZ'"),
        ("L14", "a pin both mapped and unbound", v1(lambda d: d["implements"][0]["unbound"].insert(0, "BOOT")), "both mapped and listed as unbound"),
        ("L14", "a record pin the map does not account for", v1(lambda d: d["implements"][0]["unbound"].clear() or d["implements"][0].pop("unbound")), "neither mapped, listed as unbound, nor of role nc"),
        ("L15", "pin_classes[] with an id twice", v1(lambda d: d["pin_classes"].append(dict(d["pin_classes"][0]))), "pin_classes[] must be sorted"),
        ("L15", "a pin naming an undeclared class", v1(lambda d: d["pins"][2].__setitem__("class", "adc")), "which pin_classes[] does not declare"),
        ("L15", "a member re-typed by its class", v1(lambda d: d["pin_classes"][0].__setitem__("role", "input")), "never re-types a pin"),
        ("L15", "a class with no member", v1(lambda d: d["pin_classes"].append({"id": "spare", "role": "input"})), "has no member pin"),
        ("L16", "straps[] out of sort order", v1(lambda d: d["straps"].reverse()), "straps[] must be sorted"),
        ("L16", "a combination needing a pin with no strap", v1(lambda d: d["straps"][0]["when"].__setitem__("GND", "0")), "carries no strap block"),
        ("L16", "a combination needing a pin that does not exist", v1(lambda d: d["straps"][0]["when"].__setitem__("GHOST", "0")), "does not exist"),
        ("L16", "two combinations requiring the same levels", v1(lambda d: d["straps"][1].__setitem__("when", dict(d["straps"][0]["when"]))), "require the same levels"),
        ("L17", "a power_out pin restating accuracy as recommended", v1(lambda d: d["pins"][5].__setitem__("recommended", {"voltage": {"unit": "V", "min": 1.7, "max": 1.9}})), "carries a recommended voltage"),
        ("L18", "absent[] out of sort order", v1(lambda d: d["absent"].reverse()), "absent[] must be sorted"),
        ("L18", "an absence alongside a value", v1(lambda d: d["absent"].append({"pointer": "/pins/4/abs_max", "reason": "vendor-unpublished", "target": "VDD"})), "also carries a value"),
        ("L18", "an absence whose parent does not resolve", v1(lambda d: d["absent"].append({"pointer": "/pins/9/abs_max", "reason": "vendor-unpublished"})), "does not resolve, so the absence names no field"),
        ("L18", "an indexed absence with no target echo", v1(lambda d: d["absent"][1].pop("target")), "declares no target"),
        ("L18", "an indexed absence whose target no longer matches", v1(lambda d: d["absent"][1].__setitem__("target", "adc")), "but resolves to 'gpio'"),
        ("L19", "a condition array stating one operating point twice", v1(lambda d: put(d, "/pins/5/output/voltage/1/conditions", {"iout": {"unit": "mA", "typ": 1}})), "state the same conditions"),
        ("L21", "a source vendor with no host allowlist", v1(lambda d: d["sources"][0].__setitem__("vendor", "unlisted")), "has no host allowlist"),
        ("L21", "a source URL off its vendor's hosts", v1(lambda d: d["sources"][0].__setitem__("url", "https://parts-distributor.example/ds.pdf")), "is not one of acme's hosts"),
        # The allowlist matches the vendor's own domain and its subdomains,
        # not any host that merely ENDS in its letters.
        ("L21", "a lookalike domain that ends in the vendor's", v1(lambda d: d["sources"][0].__setitem__("url", "https://evilacme.example/ds.pdf")), "is not one of acme's hosts"),
        ("L12", "a class window outside the pin's abs_max", v1(lambda d: d["pin_classes"][0].__setitem__("recommended", {"voltage": {"unit": "V", "min": 0, "max": 9}}) or d["pins"][0].__setitem__("abs_max", {"voltage": {"unit": "V", "min": 0, "max": 4}})), "exceeds abs_max max=4"),
        ("L17", "a class window making a power_out pin restate accuracy", v1(lambda d: d["pins"][5].__setitem__("class", "pwr") or d["pin_classes"].append({"id": "pwr", "role": "power_out", "recommended": {"voltage": {"unit": "V", "max": 2}}})), "carries a recommended voltage"),
    ]

    failures = 0
    for entry in cases:
        check, description, doc = entry[0], entry[1], entry[2]
        fragment = entry[3] if len(entry) > 3 else None
        found = lint(doc, "case", domains=hosts)
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

    # PICKED records. The same not-transcribed absence is legal on a record no
    # benchmark picks and refused on one that is, only for R29a's families.
    picked = v1(lambda d: d["absent"].insert(0, {"pointer": "/modes", "reason": "not-transcribed"}))
    # An absence COVERING an R29a field is refused as well: "/ratings" hides
    # "/ratings/abs_max" exactly as well as naming it would.
    covering = v1(lambda d: d["absent"].append({"pointer": "/ratings", "reason": "not-transcribed"}))
    for name, ok in (
            ("not-transcribed on an R29a family is refused on a picked record",
             any(": L18: " in f and "required data there (R29a)" in f
                 for f in lint(picked, "case", domains=hosts, picked=True))),
            ("an absence covering an R29a family is refused on a picked record",
             any(": L18: " in f and "required data there (R29a)" in f
                 for f in lint(covering, "case", domains=hosts, picked=True))),
            ("the same absence is legal on a record nobody picks",
             lint(picked, "case", domains=hosts) == []),
            ("not-transcribed outside the R29a families stays legal when picked",
             lint(valid_v1_record(), "case", domains=hosts, picked=True) == [])):
        print(f"self-test {'ok:  ' if ok else 'FAIL:'} {name}")
        failures += 0 if ok else 1

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
        lint(mutate(mutation), "probe", notes, domains=hosts)
        if any(fragment in note for note in notes):
            print(f"self-test ok:   L12 reports {description} as unchecked")
        else:
            print(f"self-test FAIL: L12 did NOT report {description} as unchecked")
            failures += 1

    # CANONICAL LAYOUT (L22), on bytes. Numbers are kept as written, so `4.0`
    # and `1e3` are canonical; whitespace, key order, CR and the trailing LF
    # are not negotiable.
    layout_doc = {"b": [1, {"x": "y"}], "a": 4.0, "c": {}, "d": []}
    canonical = (json.dumps(layout_doc, indent=2, sort_keys=True,
                            ensure_ascii=False) + "\n").encode("utf-8")
    exotic = canonical.replace(b'"a": 4.0', b'"a": 4.00e0')
    for name, data, want in (
            ("canonical bytes pass", canonical, False),
            ("a number spelled differently but laid out canonically passes",
             exotic, False),
            ("unsorted keys are caught",
             (json.dumps(layout_doc, indent=2) + "\n").encode(), True),
            ("a four-space indent is caught",
             (json.dumps(layout_doc, indent=4, sort_keys=True) + "\n").encode(),
             True),
            ("CRLF line ends are caught", canonical.replace(b"\n", b"\r\n"), True),
            ("a missing trailing LF is caught", canonical[:-1], True),
            ("an escaped non-ASCII character is caught",
             canonical.replace(b'"y"', b'"\\u00b5"'), True)):
        found = partdata.layout_problems(data)
        ok = bool(found) == want and (not want or found[0].check == "L22")
        print(f"self-test {'ok:  ' if ok else 'FAIL:'} L22: {name}")
        failures += 0 if ok else 1

    # STORE, and the lint controls: the checks this gate makes itself.
    good = valid_v1_record()
    good["part_id"] = "acme/mcu"
    for name, probe, fragment in (
            ("a store record off its part_id's path is caught",
             lambda: store_problems(STORE / "acme" / "elsewhere.part.json",
                                    canonical, good, []), "belongs at rhoform/parts/acme/mcu.part.json"),
            ("a non-canonical store record is caught",
             lambda: store_problems(STORE / "acme" / "mcu.part.json",
                                    canonical.replace(b"\n", b"\r\n"), good,
                                    []), ": L22: "),
            ("a store record implementing nothing is caught",
             lambda: store_problems(STORE / "acme" / "mcu.part.json", canonical,
                                    dict(good, implements=[]), []),
             "implements no definition"),
            ("a lint control with no location is caught",
             lambda: _control_probe("LINT-REJECTED: nowhere"),
             "does not declare where it fails"),
            ("a lint declaration with leading space is caught, not skipped",
             lambda: _control_probe(
                 " LINT-REJECTED by L14 at /implements/0/pins/vdd2: twice",
                 lambda d: d["implements"][0]["pins"].__setitem__("vdd2",
                                                                 "VDD")),
             "with nothing before it"),
            ("a lint control that lints clean is caught",
             lambda: _control_probe("LINT-REJECTED by L14 at /implements/0/pins/vdd: clean"),
             "lints clean"),
            ("a lint control failing somewhere it does not declare is caught",
             lambda: _control_probe("LINT-REJECTED by L19 at /x: wrong place",
                                    lambda d: d["implements"][0]["pins"].__setitem__("vdd", "BOOT")),
             "but actually fails at"),
            ("a lint control population under its floor is caught",
             lambda: lint_control_floor_problems(4, [], minimum=5),
             "below the floor of 5")):
        found = probe()
        ok = any(fragment in x for x in found)
        print(f"self-test {'ok:  ' if ok else 'FAIL:'} {name}")
        failures += 0 if ok else 1
    # NOTICE, and a record that does not parse: the paths the real tree never
    # takes, each driven once so blanking its report goes red.
    records, total, gaps, ratings = provenance_coverage()
    stated = (f"{gaps} of the {total} measured values across the {records} "
              f"records, of which {ratings} are ratings")
    with tempfile.TemporaryDirectory() as tmp:
        notice = Path(tmp) / "NOTICE"
        outcomes = {"missing": []}
        notice_problems(outcomes["missing"], notice)
        for name, text in (("silent", "nothing about records\n"),
                           ("stale", stated.replace(f"{total} measured",
                                                    f"{total + 1} measured")),
                           ("current", "...\n    " + stated.replace(
                               " records,", "\n    records,") + ".\n")):
            notice.write_text(text, encoding="utf-8")
            found = []
            notice_problems(found, notice)
            outcomes[name] = found
        broken = Path(tmp) / "broken.part.json"
        broken.write_bytes(b'{"schema_version": 1,')
        argv = sys.argv
        sys.argv = ["lint-part-data.py", str(broken)]
        try:
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                unparsed = main()
        finally:
            sys.argv = argv
    for name, ok in (
            ("a missing NOTICE is caught",
             outcomes["missing"] == ["NOTICE is missing"]),
            ("a NOTICE that no longer states the numbers is caught",
             any("no longer states its provenance-coverage" in x
                 for x in outcomes["silent"])),
            ("a NOTICE publishing stale numbers is caught",
             any("NOTICE publishes" in x for x in outcomes["stale"])),
            ("a NOTICE stating the records' numbers, wrapped, passes",
             outcomes["current"] == []),
            ("a record that does not parse fails the run",
             unparsed == 1 and "does not parse as JSON" in err.getvalue())):
        print(f"self-test {'ok:  ' if ok else 'FAIL:'} {name}")
        failures += 0 if ok else 1

    exact = []
    _control_probe("LINT-REJECTED by L14 at /implements/0/pins/vdd2: twice",
                   lambda d: d["implements"][0]["pins"].__setitem__("vdd2", "VDD"),
                   exact)
    clean_store = store_problems(STORE / "acme" / "mcu.part.json", canonical,
                                 good, [])
    for name, ok in (("a lint control failing exactly where it declares passes",
                      exact == []),
                     ("a canonical store record at its path passes",
                      clean_store == []),
                     ("a population at its floor passes",
                      lint_control_floor_problems(5, [], minimum=5) == [])):
        print(f"self-test {'ok:  ' if ok else 'FAIL:'} {name}")
        failures += 0 if ok else 1

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
    # THE UNPERFORMABLE-CHECK CEILING, and its wiring. It reported through a
    # bare print and no case reached it, so the guard that stops L12 opting
    # out of itself was deletable with everything green (round 21).
    _over = unchecked_ceiling_problems(["a", "b", "c"], maximum=2)
    _at = unchecked_ceiling_problems(["a", "b"], maximum=2)
    wired = {}
    for planted_name in ("unchecked_ceiling_problems", "store_problems",
                         "lint_control_problems", "lint_control_floor_problems"):
        _real_fn = globals()[planted_name]

        def _plant(*args, _fn=_real_fn, **kwargs):
            result = _fn(*args, **kwargs)
            for value in args + tuple(kwargs.values()):
                if isinstance(value, list) and value is not args[0]:
                    value.append("planted")
                    break
            return result

        globals()[planted_name] = _plant
        try:
            sys.argv = ["lint-part-data.py"]
            with _c.redirect_stdout(_i.StringIO()), _c.redirect_stderr(_i.StringIO()):
                wired[planted_name] = main()
        finally:
            globals()[planted_name] = _real_fn
            sys.argv = _argv
    for _name, _ok in (("main() exits non-zero when lint reports a problem", _planted == 1),
                       ("main() exits zero when it does not", _clean == 0),
                       ("more unperformable checks than the ceiling is caught",
                        any("above the ceiling of 2" in x for x in _over)),
                       ("a record set at the ceiling passes", _at == []),
                       ("the unperformable-check ceiling is WIRED into main()",
                        wired["unchecked_ceiling_problems"] == 1),
                       ("the store checks are WIRED into main()",
                        wired["store_problems"] == 1),
                       ("the lint-control checks are WIRED into main()",
                        wired["lint_control_problems"] == 1),
                       ("the lint-control floor is WIRED into main()",
                        wired["lint_control_floor_problems"] == 1),
                       ("a required record that vanished is caught",
                        any("named as required" in x for x in
                            required_records_problems(
                                [], required=("parts/examples/gone.part.json",)))),
                       ("a present required record is not reported",
                        required_records_problems(
                            [ROOT / "parts" / "examples" / "here.part.json"],
                            required=("parts/examples/here.part.json",)) == [])):
        print(f"self-test {'ok:  ' if _ok else 'FAIL:'} {_name}")
        failures += 0 if _ok else 1

    if len(cases) < MINIMUM_CASES:
        print(f"self-test FAIL: only {len(cases)} defect cases, below the floor "
              f"of {MINIMUM_CASES}")
        failures += 1

    if failures:
        print(f"\nself-test: {failures} check(s) did not fire.")
        return 1
    # THE MEASURE PREDICATE used by provenance_coverage(), whose numbers
    # NOTICE publishes. It had its own weaker copy -- `"unit" in node` -- ten
    # lines from walk_measures, which correctly also requires one of
    # min/typ/max/peak. That counted the SN74HC00D's twelve PIN objects (whose
    # `unit` is the L5 gate id) and returned before the 24 real measures inside
    # them, so the published total was wrong by exactly 24 - 12.
    _hc = partdata.parse((EXAMPLES / "ti-sn74hc00d.part.json").read_bytes())
    _pin_paths = {f"/pins/{i}" for i in range(len(_hc.get("pins") or []))}
    _measured = {path for path, _ in walk_measures(_hc)}
    if _pin_paths & _measured:
        print(f"FAIL pin objects counted as measured values: "
              f"{sorted(_pin_paths & _measured)}", file=sys.stderr)
        return 1
    # THE COUNT, pinned on a fixture whose answer is worked out by hand rather
    # than on the real records, whose numbers move every time one is added:
    # six measures, two of them inside `conditions` (excluded); of the four
    # counted, the two elements of a condition array sit under a provenance
    # entry with a locator, and the other two fall to the locator-less
    # default, one of them a rating. So (4, 2, 1).
    _fixture = {
        "pins": [{"name": "P", "characteristics": {
            "a": {"unit": "V", "typ": 1},
            "b": [{"unit": "V", "typ": 1, "conditions": {
                      "t": {"unit": "degC", "typ": 25}}},
                  {"unit": "V", "typ": 2, "conditions": {
                      "t": {"unit": "degC", "typ": 85}}}]}}],
        "ratings": {"abs_max": {"t": {"unit": "degC", "max": 150}}},
        "provenance": {"": {"source_id": "s"},
                       "/pins/0/characteristics/b": {"source_id": "s",
                                                     "locator": "Table 1"}},
    }
    if document_locator_gaps(_fixture) != (4, 2, 1):
        print(f"FAIL document_locator_gaps() gives "
              f"{document_locator_gaps(_fixture)} on the hand-counted fixture, "
              "expected (4, 2, 1).", file=sys.stderr)
        return 1
    print("ok   provenance coverage counts real Measures, each once (4, 2, 1)")
    # THE POPULATION NOTICE speaks for is the teaching set plus the store, and
    # never the controls; a record that left either directory must leave it.
    _named = {_rel(path) for path in record_files()}
    if not (set(REQUIRED_RECORDS) <= _named) or any(
            "/negative/" in name for name in _named):
        print(f"FAIL record_files() gives {sorted(_named)}; it must include "
              f"every required record and no control", file=sys.stderr)
        return 1
    print(f"ok   NOTICE's population is {len(_named)} record(s) across "
          "parts/examples and rhoform/parts")

    # THE GAP PREDICATE reads the locator field, not the provenance key. The
    # previous predicate counted default-fallthrough, which agrees with "names
    # no table" on today's records only because every specific entry happens to
    # carry a locator and no default does. Both drift directions were silent:
    # a locator-less specific entry hid every value under it from the count,
    # and a default gaining a locator kept counting values that now have one.
    _ne = partdata.parse((STORE / "ti" / "ne555p.part.json").read_bytes())
    _t0, _g0, _r0 = document_locator_gaps(_hc)
    _hc_mut = copy.deepcopy(_hc)
    del _hc_mut["provenance"]["/ratings/abs_max"]["locator"]
    _t1, _g1, _r1 = document_locator_gaps(_hc_mut)
    if not (_g1 > _g0 and _t1 == _t0):
        print(f"FAIL a specific provenance entry that names no table must add "
              f"its values to the gap count: {(_t0, _g0)} -> {(_t1, _g1)}",
              file=sys.stderr)
        return 1
    print("ok   a locator-less specific entry counts as a table gap")
    _ne_mut = copy.deepcopy(_ne)
    _ne_mut["provenance"][""]["locator"] = "planted table, page 1"
    _tn, _gn, _rn = document_locator_gaps(_ne)
    _tm, _gm, _rm = document_locator_gaps(_ne_mut)
    if not (_gn > 0 and _gm == 0 and _tm == _tn):
        print(f"FAIL a record default that names a table must close its gaps: "
              f"{(_tn, _gn)} -> {(_tm, _gm)}", file=sys.stderr)
        return 1
    print("ok   a default that names a table stops counting as a gap")

    print(f"\nself-test PASS: reference records lint clean; {len(cases)} defect cases all detected.")
    return 0


def _control_probe(declaration, mutation=None, problems=None):
    """lint_control_problems() over the v1 reference record, mutated."""
    import copy
    doc = copy.deepcopy(valid_v1_record())
    if mutation is not None:
        mutation(doc)
    doc["x_negative_control"] = declaration
    problems = [] if problems is None else problems
    lint_control_problems("probe", doc, problems)
    return problems


# How many checks may legitimately be unperformable across the whole record set.
# Today: one, on diodes/ap7361c-33e-13 pin OUT -- a recommended current with no
# abs_max current sibling (the vendor rates OUT's voltage, relative to IN, and
# no OUT current). v0 had a second on the same pin, the relative abs_max
# voltage bound checked against OUT's recommended voltage; v1 moved that
# figure to output.voltage (L17), so nothing is left to contain it. Raise it
# deliberately and name the record; drifting up is how a rule opts out of
# itself.
MAXIMUM_UNCHECKED = 1


def required_records_problems(files, required=None, problems=None):
    """Every named record must be among the files being linted."""
    problems = [] if problems is None else problems
    present = {_rel(path) for path in files}
    gone = [name for name in (REQUIRED_RECORDS if required is None
                              else required) if name not in present]
    if gone:
        problems.append(
            f"record(s) {gone} are named as required and are not present. "
            "Deleting one took the reported record count down by one and "
            "exited 0.")
    return problems


def unchecked_ceiling_problems(unchecked, maximum=None, problems=None):
    """More unperformable checks than the recorded ceiling is a failure.

    Appends to the caller's accumulator rather than returning a fresh list,
    so the report site lands in the coverage meta-gate's counted population
    -- being outside it is half of why this guard was deletable green."""
    problems = [] if problems is None else problems
    maximum = MAXIMUM_UNCHECKED if maximum is None else maximum
    if len(unchecked) > maximum:
        problems.append(
            f"{len(unchecked)} check(s) could not be performed, above the "
            f"ceiling of {maximum}. A rule that opts out of itself by "
            "changing the shape of the data it reads is not a rule; raise "
            "this deliberately and say which record needs it: "
            + "; ".join(unchecked))
    return problems

# Records that must exist, by repository path. Deleting one took the record
# count down by one and exited 0: a linter with fewer things to lint is
# indistinguishable from a clean tree. The teaching set's two exemplars, and
# the store's three benchmark records.
REQUIRED_RECORDS = (
    "parts/examples/ti-sn74hc00d.part.json",
    "parts/examples/vishay-crcw040210k0fked.part.json",
    "rhoform/parts/diodes/ap7361c-33e-13.part.json",
    "rhoform/parts/espressif/esp32-s3-wroom-1-n8r2.part.json",
    "rhoform/parts/ti/ne555p.part.json",
)


def document_locator_gaps(document):
    """(measured values, values whose effective provenance names no table, of
    which ratings) for one parsed record.

    THE PREDICATE IS "names no locator", NOT "falls to the record default".
    Those coincided across the first five records -- every specific entry
    carried a locator and no default did -- but the coincidence is
    load-bearing in both directions. Counting default-fallthrough meant a
    locator-less SPECIFIC entry would have hidden every value under it from the
    count, and a default that gained a locator would have kept counting values
    that now have a table. NOTICE's claim is about tables, so the gate reads
    the locator field.
    """
    entries = document.get("provenance", {})
    total = gaps = ratings = 0
    # USE THE MODULE'S OWN MEASURE PREDICATE. A second one here -- `"unit" in
    # node` -- counted the SN74HC00D's twelve PIN objects (whose `unit` is the
    # L5 gate id) as measured values AND returned before reaching the 24 real
    # measures inside them: 130 - 24 + 12 = 118, exactly the number NOTICE
    # published. The paragraph's whole defence is that the numbers are
    # computed rather than hand-maintained, and nobody hand-checks a computed
    # number.
    for pointer, _measure in walk_measures(document):
        if "/conditions/" in pointer:
            continue
        total += 1
        key = partdata.covering(entries, pointer)
        entry = entries.get(key, {}) if key is not None else {}
        if not entry.get("locator"):
            gaps += 1
            if pointer.startswith("/ratings"):
                ratings += 1
    return total, gaps, ratings


def provenance_coverage(files=None):
    """(records, measured values, values whose provenance names no table, of
    which ratings).

    NOTICE publishes these numbers. They were wrong in three successive
    revisions -- a table-per-field claim, a generalisation of one record's
    shape to all of them, and a count that was internally unsatisfiable. The
    paragraph even carried a recount procedure, and following it did not
    reproduce the number it guarded. So the gate computes them and holds NOTICE
    to the result, the record count included. The per-record predicate lives
    in document_locator_gaps().

    `conditions` sub-objects are EXCLUDED: they state the operating point at
    which a value was measured, not a transcribed rating, and counting them
    made "measured values" mean something no reader would guess.
    """
    files = record_files() if files is None else files
    total = gaps = ratings = 0
    for path in files:
        t, g, r = document_locator_gaps(partdata.parse(path.read_bytes()))
        total, gaps, ratings = total + t, gaps + g, ratings + r
    return len(files), total, gaps, ratings


def notice_problems(problems, notice=None):
    """Hold NOTICE's provenance-coverage numbers to the records."""
    notice = ROOT / "NOTICE" if notice is None else notice
    if not notice.is_file():
        problems.append("NOTICE is missing")
        return 0
    records, total, gaps, ratings = provenance_coverage()
    text = notice.read_text(encoding="utf-8")
    # Whitespace-tolerant: the sentence wraps, and the first version of this
    # regex missed its own text because of a line break.
    collapsed = re.sub(r"\s+", " ", text)
    found = re.search(
        r"(\d+) of the (\d+) measured values across the (\d+) records, "
        r"of which (\d+) are ratings", collapsed)
    if found is None:
        problems.append(
            "NOTICE no longer states its provenance-coverage numbers in the form "
            "this gate reads. That paragraph has been wrong three times; it is "
            "gated on purpose. Publish: "
            f"{gaps} of the {total} measured values across the {records} "
            f"records, of which {ratings} are ratings.")
        return 0
    published = tuple(int(g) for g in found.groups())
    if published != (gaps, total, records, ratings):
        problems.append(
            f"NOTICE publishes {published[0]} of {published[1]} measured values "
            f"across {published[2]} records whose provenance names no table, "
            f"{published[3]} of them ratings. The records give {gaps} of "
            f"{total} across {records}, {ratings} ratings.")
        return 0
    return 4


def main() -> int:
    args = sys.argv[1:]
    if "--self-test" in args:
        return self_test()

    targets = [Path(a) for a in args] or list(DEFAULT_TARGETS)
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

    if not args:
        notice_found = []
        notice_problems(notice_found)
        if notice_found:
            print("lint: FAIL:", file=sys.stderr)
            for problem in notice_found:
                print(f"  {problem}", file=sys.stderr)
            return 1

    problems, unchecked = [], []
    controls = stored = 0
    # Each named record must be among the files being linted. A count that can
    # shrink silently is the same defect as a floor with slack in it. Reported
    # through `problems`, like the unperformable-check ceiling beside it and
    # for the same reason (round 21).
    if not args:
        required_records_problems(files, problems=problems)
    for path in files:
        data = path.read_bytes()
        try:
            doc = partdata.parse(data)
        except partdata.PartDataError as exc:
            problems.append(f"{path}: does not parse as JSON: "
                            f"{exc.problems[0].message}")
            continue
        # Schema controls are not lint subjects: they are deliberately
        # malformed, and linting them would report noise. Lint controls are
        # schema-valid records with one cross-reference defect, held to it.
        if "negative" in path.parts:
            if lint_control_problems(path, doc, problems):
                controls += 1
            continue
        if path.resolve().is_relative_to(STORE.resolve()):
            stored += 1
            store_problems(path, data, doc, problems)
        found = lint(doc, str(path), unchecked,
                     picked=doc.get("part_id") in BENCHMARK_PICKED)
        problems.extend(found)
        if not found:
            print(f"lint: {path}: clean.")
    if not args:
        lint_control_floor_problems(controls, problems)

    # Printed on every run, and counted in the pass line, so a growing set of
    # unresolvable bounds is visible rather than silently shrinking coverage.
    # A CEILING on unperformable checks. L12's containment rule becomes a
    # printed note whenever an abs_max is relative ({"reference": "VCC"}), and
    # nothing bounded how many checks could become notes -- so rewriting a
    # numeric abs_max as a relative one turned a firing L12 into silence.
    #
    # Reported through `problems` like every other check here. A bare
    # `print(...); return 1` is outside the coverage meta-gate's counted
    # population by its own docstring, and no self-test case reached this
    # one, so the guard that stops L12 opting out of itself could itself be
    # deleted with the gate, its self-test and the measurement all green
    # (round 21) -- the shape already closed for MINIMUM_AGREEMENTS,
    # MINIMUM_NEGATIVE_CONTROLS and MINIMUM_ENTRIES.
    unchecked_ceiling_problems(unchecked, problems=problems)
    for note in unchecked:
        print(f"lint: unchecked: {note}")

    if problems:
        for problem in problems:
            print(f"lint: FAIL: {problem}", file=sys.stderr)
        print(f"lint: {len(problems)} problem(s).", file=sys.stderr)
        return 1

    print(
        f"lint: PASS: {len([f for f in files if 'negative' not in f.parts])} "
        f"record(s) consistent ({stored} in the store, canonical and at their "
        f"part_id's path), {controls} lint control(s) failing exactly where "
        "they declare, NOTICE's provenance-coverage numbers verified, "
        f"{len(unchecked)} check(s) not performable on the data as modelled."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
