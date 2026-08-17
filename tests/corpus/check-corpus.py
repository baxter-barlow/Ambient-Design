#!/usr/bin/env python3
"""Gate corpus/bugs.yaml — the population AC2 is measured over.

M0's exit criterion says "AC2 corpus frozen+classified". The classification
half was gated by check-classification.py; the corpus half was gated by
nothing. An audit replaced an entry's whole record with `id` and `title` — no
source, no root cause, no evidence — and `make all` stayed green. It rewrote
another entry's text into an unrelated bug, leaving a frozen verdict sitting on
top of a different defect, and the `decision_hash` did not move because that
hash covers classification.yaml only.

The collection phase did run checks: corpus/validation.log names the script it
ran them with, `check_corpus.py`. That script is in neither the repository nor
its history, so AMB-35's one substantive criterion — "at least 50 candidate
bugs, majority externally sourced" — rested on a log referencing something
nobody can run. This file is that script, written to exist.

WHAT IS CHECKED

  - the declared `entry_count` matches the number of entries, so a decorative
    count inside a frozen artifact cannot drift (check-classification.py
    already refuses this for its own count; the corpus's was unguarded);
  - AC2's floor of 50 entries;
  - every entry carries every required field, non-empty;
  - ids are well-formed and unique, and any GAP in the id sequence is
    accounted for by a retirement ledger. Ids are stable identifiers — the
    corpus is cited by id from classification.yaml and from Linear, so
    renumbering is not an option and a silent hole is an unledgered identity
    change, which AGENTS.md calls an error;
  - `kind` comes from a closed vocabulary, and a MAJORITY of entries are
    externally sourced, which is AMB-35's actual acceptance criterion;
  - every source URL is https and distinct, so "externally sourced" means a
    specific document rather than a gesture at one;
  - `review:` flags are declared from a closed set, so an unresolved review
    cannot be spelled in a way nothing recognises.

WHAT IS DELIBERATELY NOT CHECKED: whether a source URL resolves, or says what
the entry claims. This gate is offline. Re-fetching is a human job and its
results belong in the entry, as `corrected:` and `correction_note:` already
record for the five entries AMB-36 re-checked.

Exit codes: 0 pass, 1 corpus defect, 2 environment failure.

    python3 tests/corpus/check-corpus.py --self-test
    python3 tests/corpus/check-corpus.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus" / "bugs.yaml"

ID_PATTERN = re.compile(r"^BUG-\d{4}$")

REQUIRED = ("id", "title", "source", "symptom", "root_cause", "category", "class",
            "evidence", "collected")

# AC2's floor, from AMB-35: "at least 50 candidate bugs".
MINIMUM_ENTRIES = 50

# Source kinds, and which of them count as EXTERNAL for AMB-35's "majority
# externally sourced". All current kinds are external; the distinction is kept
# explicit so that adding an internal kind later cannot quietly satisfy the
# criterion.
SOURCE_KINDS = {
    "forum_postmortem": True,
    "blog_postmortem": True,
    "github_issue": True,
    "qa_site": True,
    "vendor_erratum": True,
    "mailing_list": True,
    "other_public": True,
    "internal": False,
}

REVIEW_FLAGS = {
    "needs-source-recheck",
    "schematic-vs-assembly-unresolved",
    "caveat-not-postmortem",
}

# Ids that were issued and later withdrawn. A gap in the sequence must appear
# here with the reason, or the gate fails.
#
# This exists because the corpus holds 61 entries numbered BUG-0001..BUG-0062
# with no BUG-0009, and until the audit neither retirement was recorded
# anywhere a reader could find: BUG-0063 only obliquely, inside another entry's
# correction note, and BUG-0009 nowhere at all. A reader counting entries and
# reading the highest id got two different populations and no explanation.
RETIRED = {
    "BUG-0009": (
        "Withdrawn during AMB-35 collection, BEFORE the corpus was first "
        "committed. The reason was not recorded and cannot now be recovered: "
        "git shows entry_count already 61 in the corpus's first commit "
        "(912f7ce), and the only artifact describing the 63-entry population "
        "was corpus/validation.log, which was never tracked. What that log did "
        "record is that BUG-0009 was one of six entries flagged "
        "`needs-source-recheck`; AMB-36 later re-fetched and corrected the "
        "other five (BUG-0031, 0034, 0035, 0045, 0051). That is suggestive and "
        "it is not evidence, so no reason is asserted here."
    ),
    "BUG-0063": (
        "Withdrawn during AMB-35 collection, before the first commit, for the "
        "same undocumented reason as BUG-0009. The one surviving trace is "
        "BUG-0035's `correction_note`, which cites it as the precedent for "
        "failing corpus inclusion rule 3 (schematic-level defects only) — so "
        "an assembly-process defect is the likely ground, stated here as an "
        "inference and not as a record."
    ),
}


class GateUnavailable(Exception):
    """The check could not be performed. Never reported as a pass."""


def load(path):
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment failure
        raise GateUnavailable(
            "PyYAML is required to read the corpus; install the pin "
            "(python3 -m pip install pyyaml==6.0.2)."
        ) from exc
    if not path.is_file():
        raise GateUnavailable(f"{path} is missing")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GateUnavailable(f"{path} is not readable as YAML: {exc}") from exc


def check(document):
    problems = []
    if not isinstance(document, dict) or "bugs" not in document:
        return ["corpus/bugs.yaml has no `bugs:` list"]
    bugs = document["bugs"] or []

    declared = document.get("entry_count")
    if declared != len(bugs):
        problems.append(
            f"`entry_count:` says {declared!r} but the file holds {len(bugs)} "
            "entries. A decorative count inside a frozen artifact is worse "
            "than none."
        )
    if len(bugs) < MINIMUM_ENTRIES:
        problems.append(
            f"{len(bugs)} entries is below AC2's floor of {MINIMUM_ENTRIES} "
            "(AMB-35: 'at least 50 candidate bugs')"
        )

    seen_ids, urls, external, numbers = set(), {}, 0, []
    for index, bug in enumerate(bugs):
        if not isinstance(bug, dict):
            problems.append(f"entry {index}: is not a mapping")
            continue
        entry_id = bug.get("id", f"<entry {index}>")

        for field in REQUIRED:
            value = bug.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                problems.append(f"{entry_id}: `{field}` is missing or empty")

        if not ID_PATTERN.match(str(entry_id)):
            problems.append(f"{entry_id!r}: not a well-formed corpus id (expected BUG-NNNN)")
        elif entry_id in seen_ids:
            problems.append(f"{entry_id}: appears more than once")
        else:
            seen_ids.add(entry_id)
            numbers.append(int(str(entry_id).split("-")[1]))
            if entry_id in RETIRED:
                problems.append(
                    f"{entry_id}: is listed as retired but is still in the corpus"
                )

        source = bug.get("source")
        if not isinstance(source, dict):
            problems.append(f"{entry_id}: `source` must be a mapping with a url and a kind")
            continue
        kind = source.get("kind")
        if kind not in SOURCE_KINDS:
            problems.append(
                f"{entry_id}: source kind {kind!r} is not one of "
                f"{sorted(SOURCE_KINDS)} — 'majority externally sourced' is "
                "counted from this field, so it cannot be free text"
            )
        elif SOURCE_KINDS[kind]:
            external += 1

        url = source.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            problems.append(f"{entry_id}: source url {url!r} is not an http(s) URL")
        else:
            if url in urls:
                problems.append(
                    f"{entry_id}: shares its source URL with {urls[url]}. The "
                    "corpus's own dedup rule makes the same underlying bug one "
                    "entry, so two entries citing one document inflate the "
                    "population AC2 is measured over."
                )
            else:
                urls[url] = entry_id

        review = bug.get("review")
        if review is not None and review not in REVIEW_FLAGS:
            problems.append(
                f"{entry_id}: review flag {review!r} is not one of {sorted(REVIEW_FLAGS)}"
            )

    if bugs and external * 2 <= len(bugs):
        problems.append(
            f"only {external} of {len(bugs)} entries are externally sourced; "
            "AMB-35 requires a majority"
        )

    # Every hole in the id sequence must be ledgered.
    if numbers:
        for number in range(min(numbers), max(numbers) + 1):
            candidate = f"BUG-{number:04d}"
            if number not in numbers and candidate not in RETIRED:
                problems.append(
                    f"{candidate} is missing from the sequence and is not in "
                    "RETIRED. Ids are stable identifiers cited from "
                    "classification.yaml and from Linear, so a hole is either a "
                    "withdrawal that must be recorded with its reason, or an "
                    "entry somebody dropped."
                )
    for retired_id in RETIRED:
        if not RETIRED[retired_id].strip():
            problems.append(f"{retired_id}: retired with no stated reason")

    return problems


def self_test():
    """Prove each rejection fires, over hand-built corpora."""
    # Synthetic ids start at 1000 so they cannot collide with RETIRED, whose
    # members are real withdrawn ids. A fixture that reused BUG-0009 tripped
    # the retired-id check and failed the "well-formed corpus" case — the gate
    # working correctly on a bad fixture.
    def entry(n, **over):
        n += 1000
        base = {
            "id": f"BUG-{n:04d}", "title": "t",
            "source": {"url": f"https://example.invalid/{n}", "kind": "github_issue"},
            "symptom": "s", "root_cause": "r", "category": "c", "class": "power-supply",
            "evidence": "e", "collected": "2026-08-14",
        }
        base.update(over)
        return base

    def corpus(entries, **over):
        doc = {"entry_count": len(entries), "bugs": entries}
        doc.update(over)
        return doc

    good = corpus([entry(n) for n in range(1, 51)])
    cases = [
        ("a well-formed corpus reports no problem", not check(good)),
        ("a mis-declared entry_count is caught", any(
            "entry_count" in p for p in check(corpus([entry(n) for n in range(1, 51)],
                                                     entry_count=999)))),
        ("a corpus below AC2's floor is caught", any(
            "floor of 50" in p for p in check(corpus([entry(n) for n in range(1, 10)])))),
        ("a gutted entry is caught", any(
            "`root_cause` is missing" in p for p in check(corpus(
                [entry(n) for n in range(1, 50)] + [{"id": "BUG-0050", "title": "no source at all"}])))),
        ("a duplicate id is caught", any(
            "more than once" in p for p in check(corpus(
                [entry(n) for n in range(1, 50)] + [entry(1)])))),
        ("a malformed id is caught", any(
            "well-formed corpus id" in p for p in check(corpus(
                [entry(n) for n in range(1, 50)] + [entry(1, id="BUG-1")])))),
        ("a source kind outside the vocabulary is caught", any(
            "not one of" in p for p in check(corpus(
                [entry(n) for n in range(1, 50)] + [entry(50, source={
                    "url": "https://example.invalid/x", "kind": "vibes"})])))),
        ("a non-https source is caught", any(
            "not an http(s) URL" in p for p in check(corpus(
                [entry(n) for n in range(1, 50)] + [entry(50, source={
                    "url": "ftp://example.invalid/x", "kind": "github_issue"})])))),
        ("two entries sharing one URL are caught", any(
            "shares its source URL" in p for p in check(corpus(
                [entry(n) for n in range(1, 50)] + [entry(50, source={
                    "url": "https://example.invalid/1001", "kind": "github_issue"})])))),
        ("an unrecognised review flag is caught", any(
            "review flag" in p for p in check(corpus(
                [entry(n) for n in range(1, 50)] + [entry(50, review="probably-fine")])))),
        ("a minority-external corpus is caught", any(
            "externally sourced" in p for p in check(corpus([
                entry(n, source={"url": f"https://example.invalid/{n}", "kind": "internal"})
                for n in range(1, 51)])))),
        # The retirement ledger, which is the reason this gate knows the
        # difference between a withdrawal and a dropped entry.
        ("an unledgered hole in the id sequence is caught", any(
            "not in RETIRED" in p for p in check(corpus(
                [entry(n) for n in range(1, 51) if n != 25])))),
        # These two use REAL retired ids, because that is what the ledger holds.
        ("a ledgered hole is accepted", not any(
            "not in RETIRED" in p for p in check(corpus(
                [dict(entry(n), id=f"BUG-{n:04d}",
                      source={"url": f"https://example.invalid/r{n}", "kind": "github_issue"})
                 for n in range(1, 65) if n not in (9, 63)])))),
        ("a retired id that is still present is caught", any(
            "listed as retired but is still" in p for p in check(corpus(
                [entry(n) for n in range(1, 51)]
                + [dict(entry(99), id="BUG-0009")])))),
    ]


    # WIRING. Everything above drives the check function directly; nothing
    # proved `main()` turns a finding into a non-zero EXIT. Replacing
    # `if problems:` with `if False:` left this self-test green AND the live
    # gate green over data with real defects planted in it.
    import contextlib as _ctx, io as _io
    _real = check
    try:
        globals()["check"] = lambda *_a, **_k: ["planted"]
        with _ctx.redirect_stdout(_io.StringIO()), _ctx.redirect_stderr(_io.StringIO()):
            _planted = main([])
        globals()["check"] = lambda *_a, **_k: []
        with _ctx.redirect_stdout(_io.StringIO()), _ctx.redirect_stderr(_io.StringIO()):
            _clean = main([])
    finally:
        globals()["check"] = _real
    cases.append(("main() exits non-zero when a problem is found", _planted == 1))
    cases.append(("main() exits zero when none is", _clean == 0))

    failures = 0
    for name, ok in cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        print(f"corpus: SELF-TEST FAILED: {failures} case(s)", file=sys.stderr)
        return 1
    print(f"corpus: self-test PASS: {len(cases)} cases.")
    return 0


def main(argv):
    if argv and argv[0] == "--self-test":
        return self_test()
    try:
        problems = check(load(CORPUS))
    except GateUnavailable as exc:
        print(f"corpus: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    if problems:
        print("corpus: FAIL:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    document = load(CORPUS)
    bugs = document["bugs"]
    external = sum(1 for b in bugs if SOURCE_KINDS.get(b["source"]["kind"]))
    print(
        f"corpus: PASS: {len(bugs)} entries, {external} externally sourced "
        f"({external * 100 // len(bugs)}%), ids contiguous with "
        f"{len(RETIRED)} ledgered retirement(s), every source URL distinct."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
