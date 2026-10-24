#!/usr/bin/env python3
"""Review tooling for part records: a figure table, a blind-extraction diff,
and MPN-code decoders. Test-only; nothing here is a gate or reads a PDF.

  crosscheck.py dump RECORD
      Every figure of one record as a tab-separated table, one row per
      published statistic: pointer, statistic, value, unit, conditions,
      confidence, source document and revision, and the locator a reviewer
      opens the document at. Pin roles and absences are rows too, so the
      whole R29a surface of a record reads off one table.

  crosscheck.py diff RECORD_A RECORD_B
      The blind cross-check (L2d): two independent extractions of one part,
      compared field by field. Pins are matched by NAME, condition-array
      elements by their conditions' VALUE (rhoform.partdata.condition_key),
      and numbers exactly after unit scaling, so `0.5 V` and `500 mV` agree
      and an index shuffle is not a difference. Exit 1 on any disagreement;
      each one is adjudicated against the document and the verdict logged on
      the issue, never in the repository.

  crosscheck.py decode RECORD...
      For the jellybean passives, the vendor's part-number code is a second
      reading of the same facts: size, value, tolerance and rated voltage.
      Each decoder below encodes one vendor's ordering-code legend and says
      which document section it is; a record whose parameters disagree with
      its own MPN is reported, and so is a code the decoder cannot read.
      A decoder is a cross-check, not a source: when it and the record
      disagree, the datasheet decides, and a decoder table found wrong is
      corrected against that legend.

Exit codes: 0 agreement, 1 a disagreement, 2 usage.
"""

import json
import re
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from rhoform import partdata  # noqa: E402
from rhoform.check import values  # noqa: E402


def _load(path):
    return partdata.parse(Path(path).read_bytes())


def _source(doc, pointer):
    entries = doc.get("provenance", {})
    key = partdata.covering(entries, pointer)
    entry = entries.get(key, {}) if key is not None else {}
    sources = {s["source_id"]: s for s in doc.get("sources", [])}
    source = sources.get(entry.get("source_id"), {})
    return (entry.get("confidence", "unsourced"),
            source.get("document_version", source.get("source_id", "-")),
            entry.get("locator", "-"))


def _conditions(measure):
    def one(value):
        if isinstance(value, dict):
            stats = ",".join(f"{s}={_plain(value[s])}"
                             for s in partdata.STATISTICS if s in value)
            return f"{stats} {value.get('unit', '')}".strip()
        return str(value)
    conditions = measure.get("conditions") or {}
    return "; ".join(f"{name}: {one(v)}" for name, v in sorted(
        conditions.items())) or "-"


def _plain(value):
    if isinstance(value, dict):
        return partdata._show(value)
    return str(value)


def figure_rows(doc):
    """(pointer, statistic, value, unit, conditions, confidence, document,
    locator) for every figure, role and absence of one record, sorted."""
    rows = []
    for i, pin in enumerate(doc.get("pins", [])):
        pointer = f"/pins/{i}/role"
        rows.append((pointer, "role", f"{pin['name']}={pin['role']}", "-",
                     "-", *_source(doc, pointer)))
    for pointer, measure in partdata.walk_measures(doc):
        if "/conditions/" in pointer:
            continue
        for stat in partdata.STATISTICS:
            if stat in measure:
                rows.append((pointer, stat, _plain(measure[stat]),
                             measure.get("unit", "-"), _conditions(measure),
                             *_source(doc, pointer)))
    for entry in doc.get("absent", []):
        rows.append((entry["pointer"], "absent", entry["reason"], "-", "-",
                     "-", "-", entry.get("note", "-")))
    return sorted(rows)


def dump(path):
    doc = _load(path)
    print("\t".join(("pointer", "statistic", "value", "unit", "conditions",
                     "confidence", "document", "locator")))
    for row in figure_rows(doc):
        print("\t".join(str(cell).replace("\t", " ").replace("\n", " ")
                        for cell in row))
    return 0


# ---- the blind diff ----------------------------------------------------------

def _semantic(doc):
    """{semantic key: value} for one record: pins by name, condition arrays
    by condition value, numbers in base units."""
    names = [pin.get("name") for pin in doc.get("pins", [])]
    classes = [c.get("id") for c in doc.get("pin_classes", [])]
    modes = [m.get("id") for m in doc.get("modes", [])]
    out = {}
    for i, pin in enumerate(doc.get("pins", [])):
        out[("pin", pin["name"], "role")] = pin.get("role")
        out[("pin", pin["name"], "numbers")] = tuple(pin.get("numbers", ()))
        out[("pin", pin["name"], "class")] = pin.get("class")
    for pointer, measure in partdata.walk_measures(doc):
        if "/conditions/" in pointer:
            continue
        tokens = pointer.split("/")[1:]
        if tokens[0] == "pins":
            tokens[1] = names[int(tokens[1])]
        elif tokens[0] == "pin_classes":
            tokens[1] = classes[int(tokens[1])]
        elif tokens[0] == "modes":
            tokens[1] = modes[int(tokens[1])]
        if tokens[-1].isdigit():
            tokens[-1] = partdata.condition_key(measure.get("conditions"))
        else:
            tokens.append(partdata.condition_key(measure.get("conditions")))
        try:
            unit = values.parse_part_unit(measure["unit"])
            scale, dimension = unit.scale, unit.dimension
        except values.UnitError:
            scale, dimension = None, measure["unit"]
        for stat in partdata.STATISTICS:
            if stat not in measure:
                continue
            bound = measure[stat]
            if isinstance(bound, dict) or scale is None:
                value = (json.dumps(bound, sort_keys=True, default=str),
                         measure["unit"])
            else:
                value = (Fraction(bound) * scale, dimension)
            out[(*tokens, stat)] = value
    for entry in doc.get("absent", []):
        out[("absent", entry["pointer"])] = entry["reason"]
    return out


def _label(key):
    return "/".join(k if isinstance(k, str) else "<conditions>"
                    for k in key if k is not None)


def diff(path_a, path_b):
    a, b = _semantic(_load(path_a)), _semantic(_load(path_b))
    differences = []
    for key in sorted(set(a) | set(b), key=repr):
        if a.get(key) != b.get(key):
            differences.append((_label(key), a.get(key, "<absent>"),
                                b.get(key, "<absent>")))
    for label, left, right in differences:
        print(f"differ\t{label}\t{left}\t{right}")
    print(f"crosscheck: {len(differences)} disagreement(s) between "
          f"{path_a} and {path_b}")
    return 1 if differences else 0


# ---- MPN decoders --------------------------------------------------------------

def _value(code, unit_letters):
    """A resistance-style value code: `10K`, `1K13`, `634R`, `31K2`,
    `R0200`, `1M`, `0R`. `unit_letters` maps the letter standing in for the
    decimal point to its multiplier."""
    match = re.fullmatch(r"(\d*)([A-Z])(\d*)", code)
    if match is None or match.group(2) not in unit_letters:
        return None
    whole, letter, fraction = match.groups()
    digits = (whole or "0") + "." + (fraction or "0")
    return Fraction(digits) * unit_letters[letter]


OHMS = {"R": Fraction(1), "K": Fraction(1000), "M": Fraction(10 ** 6)}
TOLERANCE = {"B": Fraction(1, 1000), "D": Fraction(5, 1000),
             "F": Fraction(1, 100), "G": Fraction(2, 100),
             "J": Fraction(5, 100), "K": Fraction(10, 100),
             "M": Fraction(20, 100)}


def _pf(code):
    """A three-character capacitance code in pF: two digits and a power of
    ten (`104` is 100 nF), or an `R` decimal (`1R5`)."""
    if "R" in code:
        return Fraction(code.replace("R", "."))
    return Fraction(int(code[:2]) * 10 ** int(code[2]))


def yageo_rc(mpn):
    # Yageo RC_L chip resistor datasheet, "ORDERING INFORMATION - GLOBAL
    # PART NUMBER": RC <size> <tolerance> <packaging> - <reel> <value> L.
    m = re.fullmatch(r"RC(\d{4})([A-Z])R-\d{2}(\w+?)L", mpn)
    if m is None:
        return None
    size, tol, value = m.groups()
    ohms = _value(value, OHMS)
    if ohms == 0:
        # A jumper: no nominal and no tolerance, a maximum resistance.
        return {"size": size, "jumper": True}
    return {"size": size, "resistance": ohms,
            "resistance_tolerance": TOLERANCE.get(tol)}


def yageo_mfr(mpn):
    # Yageo MFR datasheet, "ORDERING INFORMATION": MFR-<power class>
    # <tolerance> <packaging> <taping> - <value>. Only the tolerance letter
    # and the value are decoded; the packaging fields are not facts a check
    # reads.
    m = re.fullmatch(r"MFR-\d+([A-Z])[A-Z]+\d+-(\w+)", mpn)
    if m is None:
        return None
    return {"resistance": _value(m.group(2), OHMS),
            "resistance_tolerance": TOLERANCE.get(m.group(1))}


def vishay_resistor(mpn):
    # Vishay TNPW e3 and WSLP datasheets, "PART NUMBER AND PRODUCT
    # DESCRIPTION": <model><size> <value> <tolerance> <TCR or packaging>.
    m = re.fullmatch(r"(TNPW|WSLP)(\d{4})(\w+?)([BDF])(\w{2,3})", mpn)
    if m is None:
        return None
    _model, size, value, tol, _rest = m.groups()
    return {"size": size, "resistance": _value(value, OHMS),
            "resistance_tolerance": TOLERANCE.get(tol)}


MURATA_SIZE = {"03": "0201", "15": "0402", "18": "0603", "21": "0805",
               "31": "1206", "32": "1210"}
MURATA_VOLTS = {"0J": Fraction(63, 10), "1A": Fraction(10), "1C": Fraction(16),
                "1E": Fraction(25), "1H": Fraction(50), "2A": Fraction(100)}
# Only the codes the benchmark parts use; an unlisted code is reported as
# unreadable, never guessed.
MURATA_CHAR = {"5C": "C0G", "R6": "X5R", "R7": "X7R"}


def murata_mlcc(mpn):
    # Murata "Part Numbering" for ceramic capacitors (SMD): GRM/GCM <size>
    # <thickness> <temperature characteristic> <rated voltage>
    # <capacitance> <tolerance> <individual specification> <packaging>.
    m = re.fullmatch(r"(GRM|GCM)(\d{2})\w([0-9A-Z]{2})([0-9][A-Z])"
                     r"(\d{2}\d|\dR\d|R\d\d)([A-Z])\w{3}[A-Z]?", mpn)
    if m is None:
        return None
    _series, size, char, volts, cap, tol = m.groups()
    return {"size": MURATA_SIZE.get(size), "dielectric": MURATA_CHAR.get(char),
            "voltage_rating": MURATA_VOLTS.get(volts),
            "capacitance": _pf(cap) * Fraction(1, 10 ** 12),
            "capacitance_tolerance": TOLERANCE.get(tol)}


TDK_VOLTS = MURATA_VOLTS
TDK_SIZE = {"1005": "0402", "1608": "0603", "2012": "0805", "3216": "1206"}


def tdk_mlcc(mpn):
    # TDK "Commercial grade, general" C series catalogue, "Part number
    # system": C <size> <temperature characteristic> <rated voltage>
    # <capacitance> <tolerance> <thickness> <packaging> <special>.
    m = re.fullmatch(r"C(\d{4})(X5R|X7R|C0G|X7S|X6S)(\d[A-Z])(\d{3})([A-Z])"
                     r"\d{3}[A-Z]{1,2}", mpn)
    if m is None:
        return None
    size, char, volts, cap, tol = m.groups()
    return {"size": TDK_SIZE.get(size), "dielectric": char,
            "voltage_rating": TDK_VOLTS.get(volts),
            "capacitance": _pf(cap) * Fraction(1, 10 ** 12),
            "capacitance_tolerance": TOLERANCE.get(tol)}


KEMET_VOLTS = {"9": Fraction(63, 10), "8": Fraction(10), "4": Fraction(16),
               "3": Fraction(25), "6": Fraction(35), "5": Fraction(50),
               "1": Fraction(100), "2": Fraction(200)}
KEMET_CHAR = {"R": "X7R"}


def kemet_mlcc(mpn):
    # KEMET "Surface Mount Multilayer Ceramic Chip Capacitors (SMD MLCCs),
    # X7R Dielectric", "Ordering Information": C <case> C <capacitance>
    # <tolerance> <rated voltage> <dielectric> A <termination> <packaging>.
    m = re.fullmatch(r"C(\d{4})C(\d{3})([A-Z])(\d)([A-Z])A[A-Z]\w*", mpn)
    if m is None:
        return None
    size, cap, tol, volts, char = m.groups()
    return {"size": size, "dielectric": KEMET_CHAR.get(char),
            "voltage_rating": KEMET_VOLTS.get(volts),
            "capacitance": _pf(cap) * Fraction(1, 10 ** 12),
            "capacitance_tolerance": TOLERANCE.get(tol)}


DECODERS = (("yageo", "RC", yageo_rc), ("yageo", "MFR", yageo_mfr),
            ("vishay", "TNPW", vishay_resistor),
            ("vishay", "WSLP", vishay_resistor),
            ("murata", "GRM", murata_mlcc), ("murata", "GCM", murata_mlcc),
            ("tdk", "C", tdk_mlcc), ("kemet", "C", kemet_mlcc))


def _record_value(doc, section, key, stat):
    node = (doc.get(section) or {}).get(key) if "/" not in section else \
        ((doc.get("ratings") or {}).get(section.split("/")[1]) or {}).get(key)
    measures = node if isinstance(node, list) else [node]
    found = []
    for measure in measures:
        if not isinstance(measure, dict) or stat not in measure:
            continue
        try:
            unit = values.parse_part_unit(measure["unit"])
        except values.UnitError:
            continue
        if not isinstance(measure[stat], dict):
            found.append(Fraction(measure[stat]) * unit.scale)
    return found


def decode_problems(doc):
    """(checked, problems) for one record against its own MPN."""
    vendor = doc["part_id"].split("/")[0]
    decoder = next((fn for slug, prefix, fn in DECODERS
                    if slug == vendor and doc["mpn"].startswith(prefix)
                    and fn(doc["mpn"]) is not None), None)
    if decoder is None:
        print(f"crosscheck: note: no decoder reads {doc['mpn']!r} "
              f"({doc['part_id']}); it needs the blind extraction instead")
        return 0, []
    facts = decoder(doc["mpn"])
    checked, problems = 0, []
    for name, want in sorted(facts.items()):
        if want is None:
            problems.append(f"{doc['part_id']}: the decoder cannot read the "
                            f"{name} field of {doc['mpn']!r}")
            continue
        checked += 1
        if name == "size":
            got = doc.get("package", {}).get("name", "")
            ok = want in got
        elif name == "dielectric":
            got = doc.get("description", "")
            ok = want in got
        elif name == "jumper":
            got = _record_value(doc, "parameters", "resistance", "max")
            ok = bool(got) and not _record_value(
                doc, "parameters", "resistance_tolerance", "max")
        elif name in ("resistance", "capacitance"):
            got = _record_value(doc, "parameters", name, "typ") or \
                _record_value(doc, "parameters", name, "max")
            ok = want in got
        elif name.endswith("_tolerance"):
            got = _record_value(doc, "parameters", name, "max")
            ok = want in got
        else:
            got = _record_value(doc, "ratings/recommended", name, "max")
            ok = want in got
        if not ok:
            problems.append(f"{doc['part_id']}: {doc['mpn']} encodes {name} "
                            f"{want}, the record says {got!r}")
    return checked, problems


def decode(paths):
    total, problems = 0, []
    for path in paths:
        checked, found = decode_problems(_load(path))
        total += checked
        problems += found
    for problem in problems:
        print(f"crosscheck: DISAGREE: {problem}")
    print(f"crosscheck: {total} field(s) decoded from {len(paths)} MPN(s), "
          f"{len(problems)} disagreement(s)")
    return 1 if problems else 0


def main(argv):
    if len(argv) == 2 and argv[0] == "dump":
        return dump(argv[1])
    if len(argv) == 3 and argv[0] == "diff":
        return diff(argv[1], argv[2])
    if len(argv) >= 2 and argv[0] == "decode":
        return decode(argv[1:])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
