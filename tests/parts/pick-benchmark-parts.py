#!/usr/bin/env python3
"""Map every benchmark instance to the store record it picks, by exact MPN.

Test-only tooling, never part of a compile: rhoform resolves a part only
through a lockfile pick, and this is what writes the picks down. It reads
the three benchmarks' sources (through the elaborator, so an instance and
its `mpn` constraint are what the compiler sees) and, for benchmark (a),
whose source names no MPN, its parts.yaml through the refdes table below.
Each MPN is split into a manufacturer and the vendor's part number, and the
part number must equal a store record's `mpn` exactly. Two completions are
allowed, each a rule the vendor itself prints, and each is reported by name
so the source can be normalised (L5b):

  murata-packaging-code  Murata writes a part as `GRM155R71C104KA88#`, the
                         `#` standing for a one-letter packaging code; a
                         source that leaves the code off names that family,
                         and the record is the orderable member.
  ck-lfs-suffix          C&K's ordering table spells its lead-free parts
                         with a trailing ` LFS`.

Nothing else is guessed: an MPN with no record is UNRESOLVED, and one the
vendor does not list is BLOCKED with the reason (a BOM decision for L5b).
The output is sorted and carries no timestamps, so two runs over one tree
are byte-identical.

Usage:
    pick-benchmark-parts.py            print the mapping, one row per instance
    pick-benchmark-parts.py --json     the same as JSON, for test lockfiles
    pick-benchmark-parts.py --check    also exit 1 unless every non-hardware
                                       instance resolves or is BLOCKED, every
                                       pick implements its instance's
                                       definition, and every pick is in
                                       parts/lint-part-data.py's
                                       BENCHMARK_PICKED

Exit codes: 0 ok, 1 a --check failure, 2 environment (lark or PyYAML missing).
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from rhoform import partdata  # noqa: E402

BENCHMARKS = ("blinker-555", "buck-3v3", "esp32s3-devboard")

# Manufacturer spellings the benchmarks use, longest first so `TDK EPCOS`
# wins over `TDK`, each to the vendor slug that starts its part_ids.
MANUFACTURERS = (
    ("Keystone Electronics", "keystone"),
    ("STMicroelectronics", "st"),
    ("Texas Instruments", "ti"),
    ("TDK EPCOS", "tdk"),
    ("Coilcraft", "coilcraft"),
    ("Kingbright", "kingbright"),
    ("Littelfuse", "littelfuse"),
    ("Infineon", "infineon"),
    ("Keystone", "keystone"),
    ("STMicro", "st"),
    ("Sullins", "sullins"),
    ("Murata", "murata"),
    ("Vishay", "vishay"),
    ("KEMET", "kemet"),
    ("Yageo", "yageo"),
    ("C&K", "ck"),
    ("GCT", "gct"),
    ("TDK", "tdk"),
    ("TI", "ti"),
)

# Benchmark (a): its source binds abstract parts with no `mpn`, and its
# parts.yaml names refdes, not instances. This is the join, by the role and
# value each parts.yaml line states. Two instances already carry resolved
# keys (`timer.555/ti-NE555P@2`, `conn.battery_9v/keystone-232@1`) that
# resolve to nothing; the lockfile pick supersedes them.
BLINKER_REFDES = {
    "/c_byp": "CBYP",
    "/c_ctl": "CB",
    "/c_t": "CT",
    "/indicator/d1": "D1",
    "/indicator/r_lim": "RL",
    "/j_bat": "BT1",
    "/r_a": "RA",
    "/r_b": "RB",
    "/timer": "U1",
}

# MPNs the vendor does not list as orderable parts: no record is authored,
# and the line is a BOM decision for L5b (AMB-149).
BLOCKED = {
    "1206L075YR": "Littelfuse lists no 1206L075YR orderable; the 1206L075 "
                  "variants are /13.2WR, /16WR and THYR (AMB-126)",
    "GRM188R61A106KE69": "murata.com serves no product page or specification "
                         "for GRM188R61A106KE69# (checked 2026-10-24)",
}


def split_mpn(text):
    """(vendor slug or None, the vendor's part number) for one MPN as a
    benchmark spells it."""
    text = " ".join(str(text).split())
    for name, slug in MANUFACTURERS:
        if text.startswith(name + " "):
            return slug, text[len(name) + 1:]
    return None, text


def store_index():
    """[(vendor slug, mpn, part_id, implemented definitions)] for every
    store record, sorted."""
    rows = []
    for path in sorted(partdata.STORE.glob("*/*.part.json")):
        doc = partdata.parse(path.read_bytes())
        rows.append((doc["part_id"].split("/")[0], doc["mpn"], doc["part_id"],
                     tuple(e["definition"] for e in doc.get("implements", ()))))
    return rows


def match(vendor, mpn, index):
    """(part_id, rule, definitions) for one split MPN, or None."""
    for rule in ("exact", "murata-packaging-code", "ck-lfs-suffix"):
        found = [(part_id, defs) for slug, record_mpn, part_id, defs in index
                 if vendor in (None, slug) and _matches(rule, slug, mpn,
                                                        record_mpn)]
        if len(found) == 1:
            return found[0][0], rule, found[0][1]
        if len(found) > 1:
            raise SystemExit(f"pick: {mpn!r} matches {len(found)} records "
                             f"by rule {rule}: {sorted(f[0] for f in found)}")
    return None


def _matches(rule, slug, mpn, record_mpn):
    if rule == "exact":
        return record_mpn == mpn
    if rule == "murata-packaging-code":
        return slug == "murata" and len(record_mpn) == len(mpn) + 1 \
            and record_mpn.startswith(mpn) and record_mpn[-1].isalpha()
    return slug == "ck" and record_mpn == mpn + " LFS"


def instances(benchmark):
    """[(path, definition, hardware_kind, dnp, spelt MPN or None, source)]
    for every component instance of one benchmark."""
    from rhoform import compile as pipeline
    from rhoform.diagnostics import Diagnostics

    directory = ROOT / "benchmarks" / benchmark
    source = directory / f"{benchmark}.rhoform"
    sink = Diagnostics()
    design = pipeline.compile(source.name, directory, stage="elaborate",
                              sink=sink).design
    if design is None or sink.has_errors:
        raise SystemExit(f"pick: {benchmark} does not elaborate:\n"
                         f"{sink.render()}")
    refdes = {}
    if benchmark == "blinker-555":
        import yaml
        lines = yaml.safe_load((directory / "parts.yaml").read_text(
            encoding="utf-8"))["parts"]
        refdes = {line["ref"]: line["mpn"] for line in lines}
        missing = sorted(set(BLINKER_REFDES.values()) - set(refdes))
        if missing:
            raise SystemExit(f"pick: blinker-555/parts.yaml has no line "
                             f"{missing}")
    rows = []
    for instance in design.instances:
        if instance.kind != "component":
            continue
        constraints = instance.part.constraints if instance.part else {}
        if "mpn" in constraints:
            spelt, where = constraints["mpn"], "source"
        elif instance.path in BLINKER_REFDES and benchmark == "blinker-555":
            spelt = refdes[BLINKER_REFDES[instance.path]]
            where = f"parts.yaml {BLINKER_REFDES[instance.path]}"
        else:
            spelt, where = None, None
        rows.append((instance.path, instance.definition,
                     instance.hardware_kind, instance.dnp, spelt, where))
    unjoined = sorted(set(BLINKER_REFDES) - {r[0] for r in rows}) \
        if benchmark == "blinker-555" else []
    if unjoined:
        raise SystemExit(f"pick: blinker-555 has no instance {unjoined}")
    return rows


def mapping():
    """One dict per component instance of every benchmark, sorted."""
    index = store_index()
    out = []
    for benchmark in BENCHMARKS:
        for path, definition, hardware, dnp, spelt, where in \
                instances(benchmark):
            row = {"benchmark": benchmark, "instance": path,
                   "definition": definition, "hardware": hardware,
                   "dnp": dnp, "mpn": spelt, "from": where}
            if spelt is None:
                row["status"] = "hardware" if hardware else "no-mpn"
                out.append(row)
                continue
            vendor, mpn = split_mpn(spelt)
            row["vendor"], row["vendor_mpn"] = vendor, mpn
            if mpn in BLOCKED:
                row["status"], row["reason"] = "blocked", BLOCKED[mpn]
            else:
                found = match(vendor, mpn, index)
                if found is None:
                    row["status"] = "unresolved"
                else:
                    row["part_id"], row["rule"], defs = found
                    row["status"] = "picked" if definition in defs \
                        else "definition-not-implemented"
            out.append(row)
    return out


def check_problems(rows, picked):
    problems = []
    for row in rows:
        where = f"{row['benchmark']}{row['instance']}"
        if row["status"] == "no-mpn":
            problems.append(f"{where}: no MPN in the source or parts.yaml")
        elif row["status"] == "unresolved":
            problems.append(f"{where}: {row['mpn']!r} has no store record")
        elif row["status"] == "definition-not-implemented":
            problems.append(f"{where}: {row['part_id']} does not implement "
                            f"{row['definition']}")
        if row.get("part_id") and row["part_id"] not in picked:
            problems.append(f"{where}: {row['part_id']} is not in "
                            "BENCHMARK_PICKED, so R29a is not held on it")
    return problems


def benchmark_picked():
    spec = importlib.util.spec_from_file_location(
        "lint_part_data", ROOT / "parts" / "lint-part-data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return set(module.BENCHMARK_PICKED)


def main(argv):
    try:
        import lark  # noqa: F401 - the elaborator needs it
        import yaml  # noqa: F401 - benchmark (a)'s parts.yaml
    except ImportError as exc:
        print(f"pick: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    rows = mapping()
    if "--json" in argv:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        for row in rows:
            target = row.get("part_id") or row.get("reason") or ""
            rule = f" [{row['rule']}]" if row.get("rule") else ""
            print(f"{row['benchmark']:17} {row['instance']:18} "
                  f"{row['status']:10} {row['mpn'] or '-':34} "
                  f"{target}{rule}")
    if "--check" not in argv:
        return 0
    picked = benchmark_picked()
    problems = check_problems(rows, picked)
    resolved = {row["part_id"] for row in rows if row.get("part_id")}
    for part_id in sorted(picked - resolved):
        print(f"pick: note: BENCHMARK_PICKED names {part_id}, which no "
              "instance picks yet (its record has not landed)",
              file=sys.stderr)
    for problem in problems:
        print(f"pick: FAIL: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"pick: PASS: {len(resolved)} record(s) picked by "
          f"{sum(1 for r in rows if r.get('part_id'))} instance(s), "
          f"{sum(1 for r in rows if r['status'] == 'blocked')} blocked, "
          f"{sum(1 for r in rows if r['status'] == 'hardware')} hardware.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
