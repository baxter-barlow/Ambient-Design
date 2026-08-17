#!/usr/bin/env python3
"""Gate the AC2 in/out-of-scope classification, and freeze its denominator.

AC2 asks for the corpus to be "classified at freeze time — before checker
tuning — as in-scope (static-tier domain, expressible in the v1 DSL) or
out-of-scope, both populations published", and then gates the static tier at
"≥90% of in-scope" bugs.

The word doing the work is BEFORE. A ratio whose denominator can be edited
after the numerator is known is not a measurement. Nothing stops a later
issue — AMB-61 is the one that has the motive — from moving three awkward
bugs out of scope and reporting a pass. Not from malice: reclassifying feels
like a correction when a check turns out to be hard, and the corpus README is
prose that no gate has ever read.

So this gate exists to make the denominator tamper-EVIDENT rather than to make
it tamper-proof. Reclassifying stays possible and is sometimes right; what it
cannot be is quiet. Every verdict change moves `decision_hash`, and the commit
that moves it says so in the diff.

WHAT IS CHECKED, AND AGAINST WHAT:

  coverage        every corpus id classified exactly once, no strays. A bug
                  appended to bugs.yaml without a verdict is a silent
                  denominator change, so it fails here.
  vocabularies    verdict, check family and reason code come from closed
                  lists. A typo cannot invent a scope category.
  citations       each verdict cites the frozen artifact that decided it, and
                  the citation is RESOLVED, not just pattern-matched:
                    d3:     walked against parts/part-data.schema.json
                    syntax: resolved against the frozen grammar's own rules
                    vocab:  resolved against the frozen closed vocabularies
                  Those three are live. The rest (ga:, req:, v2:, nongoal:)
                  name clauses in Notion specifications this gate cannot fetch
                  offline, so they resolve against lists transcribed here and
                  are reported as transcribed rather than passed off as
                  verified. See TRANSCRIBED below.
  sufficiency     a reason code must cite the KIND of clause that justifies
                  it — `v1-non-goal` must name a non-goal, `dynamic-deferred`
                  must name something actually on V2's deferred list. This is
                  what stops a verdict being justified by gesture.
  gap falsified   `d3-gap` is the largest out-of-scope population, so it is the
                  code that does the most to shrink the AC2 denominator. Each
                  one names the field path a checker would need, and the gate
                  proves that path does NOT resolve — anchor included, so the
                  claim is about a real place in the schema. Entries whose
                  fact IS in D3, behind a conventional key in an open map,
                  name that map in `carried_at`, which the gate resolves and
                  requires to end in an open map — so "absent" and "present
                  but not enumerated" are different, checkable states.
  freeze          `decision_hash` recomputed from the verdicts themselves.
  published       the summary block in corpus/README.md regenerated and
                  compared, so the published populations cannot drift from
                  the data the way hand-maintained counts do.

`decision_hash` covers the decision fields and the falsifiable claims behind
them, and NOT the rationale prose: hashing that would make a typo fix
indistinguishable from a reclassification, and the predictable result is
people updating the hash without reading the diff. A freeze everybody learns
to bypass is worse than none.

The exact field list is `decision_hash` below, and is deliberately not
restated in prose — not here and not in corpus/README.md, which delegates to
it. Both copies of that list went stale three revisions running, which is the
argument for having one.

Exit codes follow tests/structure/check-layout.sh: 0 pass, 1 violation, 2 when
the gate could not run.

    python3 tests/corpus/check-classification.py --self-test  # prove it fails
    python3 tests/corpus/check-classification.py
    python3 tests/corpus/check-classification.py --write      # refreeze
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUGS = ROOT / "corpus" / "bugs.yaml"
CLASSIFICATION = ROOT / "corpus" / "classification.yaml"
README = ROOT / "corpus" / "README.md"
PART_SCHEMA = ROOT / "parts" / "part-data.schema.json"
GRAMMAR_DIR = ROOT / "lang"

VERDICTS = ("in-scope", "out-of-scope")

# The static check families. Every one is a capability the frozen artifacts
# already support: a family that needs a fact D3 v0 does not carry is not a
# family, it is a wish.
FAMILIES = {
    "erc-pin-role": "T2 pin-role lattice: conflicts, undriven inputs, open-drain nets with no pull-up, undeclared single-pin nets",
    "abs-max-containment": "T5: declared domain interval against pins[].abs_max",
    "voltage-domain-crossing": "T5: undeclared crossing between voltage_domain nets",
    "ground-architecture": "GA-1..GA-17 / RHO4001..RHO4010",
    "current-budget": "T10: pins[].capability against summed modes[].draw per domain",
    "dimension-interval": "T3/T4: dimensional and interval containment on declared values",
    "net-topology": "decidable from the netlist alone, with no part data at all",
    "part-binding": "D1: constraint conflicts and unresolved abstract parts",
}

# The out-of-scope reason codes. Each names a pre-existing declared exclusion,
# never a judgement invented at classification time — which is the only thing
# keeping the out-of-scope population honest.
REASONS = {
    "not-expressible": "the defective design cannot be written in frozen syntax v0.1",
    "v1-non-goal": "root cause is a declared section-3 non-goal",
    "ground-arch-excluded": "root cause is a ground-architecture section-7 exclusion",
    "dynamic-vocabulary": "needs time/frequency-domain behaviour; v1 catches it in the ngspice tier",
    "dynamic-deferred": "needs a measurement on V2's deferred list; v1 has no tier for it",
    "d3-gap": "static and expressible, but no checker-reliable D3 v0 field carries the fact",
}

# Reason and family codes each demand a citation from a particular space. A
# verdict citing nothing relevant is the failure mode this table exists for:
# `v1-non-goal` that names no non-goal is an assertion, not a classification.
REQUIRED_SPACE = {
    "not-expressible": ("syntax", "vocab"),
    "v1-non-goal": ("nongoal",),
    "ground-arch-excluded": ("ga-excluded",),
    "dynamic-vocabulary": ("v2",),
    "dynamic-deferred": ("v2-deferred",),
    "d3-gap": (),  # carries `missing_path` instead; see check_entry
}

# `req:` and `ga:` are deliberately NOT here. Both are transcribed spaces, and
# an in-scope verdict justified only by "cites T5" names an aspiration rather
# than a capability. To be in scope a verdict must point at something the
# frozen artifacts actually hold.
IN_SCOPE_SPACES = ("d3", "syntax", "vocab")

# The D3 v0 surface a checker may depend on. `parts/README.md` puts
# `characteristics`, `parameters`, `ratings.*` and `conditions` in open maps
# whose KEY SPELLINGS are conventional rather than enum-enforced — a checker
# keyed on one is keyed on an unfrozen name. Those maps are real data and are
# unit-carrying; what they are not is a name a check may rely on at v0. This
# allowlist is the operative distinction, and it is enforced rather than
# described: without it the resolver happily accepted `d3:parameters`, which
# is precisely the citation the rubric forbids.
CHECKER_UNRELIABLE_D3 = ("conditions", "characteristics", "parameters", "ratings")

CHECKER_RELIABLE_D3 = (
    "pins[].role",
    "pins[].numbers",
    "pins[].unit",
    "pins[].abs_max",
    "pins[].recommended",
    "pins[].capability",
    "modes[].draw",
    "modes[].id",
    "package",
    "lifecycle",
    "units[]",
    "shared_pins",
)

# The `d3-gap` classes, closed. Every gap entry names one, so the published
# "which missing fact blocks how many bugs" table is DERIVED from the verdicts
# rather than counted by hand in prose — and so the counterfactual population
# ("close this gap and N entries move in scope") is computable and auditable.
# The one gap class whose fix is a promotion rather than an addition: the data
# is already in D3 v0, in an open map. Entries in it must say WHERE, and the
# gate checks that the open map really is there — otherwise "missing" and
# "documented but not enumerated" are indistinguishable, which is exactly the
# error this classification's own finding made in its first draft.
GAP_CLASSES = {
    "companion-requirement": "a requirement a part places on an external companion component",
    "strap-semantics": "which pins latch at reset as configuration straps, and to what level",
    "functional-class": "what a part IS — regulator, protection diode, undervoltage cutoff",
    "bus-address": "the bus address a part presents, fixed or strap-selected",
    "internal-pull": "a pin's internal pull-up or pull-down presence and strength",
    "part-own-value": "a part's own defining value that no closed field enumerates",
    "pin-semantics": "what a pin MEANS beyond its electrical role — which outputs it gates, its polarity",
}

# N.B. this is a citation-shape check, not a semantic one: it proves an
# `abs-max-containment` verdict at least names an abs-max field. It caught a
# real mislabel — an entry filed under abs-max whose rule was a `recommended`
# comparison — which is why it is here rather than dismissed as ceremony.
FAMILY_REQUIRES = {
    "erc-pin-role": ("d3:pins[].role",),
    "abs-max-containment": ("d3:pins[].abs_max",),
    "voltage-domain-crossing": ("vocab:net_attribute.voltage_domain",),
    "ground-architecture": ("ga:",),
    "current-budget": ("d3:pins[].capability", "d3:modes[].draw"),
    "dimension-interval": ("syntax:value", "syntax:constraint", "syntax:argument"),
    "net-topology": ("syntax:net_decl", "syntax:endpoint"),
    "part-binding": ("syntax:part_decl", "syntax:constraint"),
}

# The kinds of thing that survive a D3 change. Closed, because the kind has
# consequences the prose cannot carry: `fact-undocumented` says the fact is in
# no source, which contradicts `carried_at` saying where it lives — so that
# pairing is a gate failure rather than something a reviewer has to notice.
RESIDUAL_KINDS = {
    "v1-non-goal": "blocked by a declared section-3 non-goal, so no schema version reaches it",
    "designs-identical": "the buggy and corrected designs are the same netlist",
    "not-design-time": "the failure is not a property of the design as authored",
    "fact-undocumented": "the fact is in no source, so no field could carry it",
    "counterfactual-inverted": "adding the fact would make the generic rule flag the CORRECTED design",
    "not-a-postmortem": "the entry states a requirement rather than reporting an observed failure, so there is no buggy board for any check to catch",
}

# Each of these says nothing a SCHEMA CHANGE reaches, so none can sit on an
# entry that also claims the fix is a promotion. Keyed on `carried_at`, which
# is what carries that claim.
#
# `not-a-postmortem` is deliberately NOT in this list. It is a claim about the
# SOURCE -- the entry states a requirement rather than reporting an observed
# failure -- and says nothing about where the fact lives in D3. Treating the
# two as the same forced BUG-0054 to assert "absent" when its own
# `missing_fact` says the qualification is "expressible only as an open
# `conditions` key", and `conditions` resolves. The gate's own docstring says
# `carried_at` exists to make "absent" and "present but not enumerated"
# different, checkable states; conflating them picked the false one.
RESIDUAL_KIND_EMPTIES_PROMOTION = (
    "fact-undocumented",
    "designs-identical",
    "not-design-time",
)

# `at_risk` entries group into the decisions that would lose them together.
# Reporting 17 conditional verdicts as 17 independent risks both
# overstates the exposure and buries the useful fact: two of these decisions
# fail AC2 on their own, which is something to go and settle rather than a
# number to worry about.
AT_RISK_GROUPS = {
    "l9b-leg": "the L9b undeclared-single-pin-net leg is implemented, not only the T2 no-driver leg",
    "decoupling-rule": "the generic decoupling rule survives the zero-spurious-errors precision pass",
    "domain-attributes": "the designs under test declare `voltage_domain`, which the grammar makes optional",
    "gpio-roles": "MCU general-purpose pins are transcribed with directional or open-drain roles",
    "part-record": "one individual part-record authoring call; unlike the others, these are independent of each other",
}

# Members of these are independent calls, so the group fails on a SUBSET. The
# block figure in the table is the pessimistic end; the subset figure is the
# one that bites first, and it is emitted alongside.
INDEPENDENT_GROUPS = ("part-record",)

ID_PATTERN = re.compile(r"^BUG-\d{4}$")

# ---------------------------------------------------------------------------
# TRANSCRIBED constants.
#
# These name clauses in Notion documents (the requirements and the
# ground-architecture semantics) and in the requirements' own section 3. A gate
# that must run offline in CI cannot fetch them, so they are transcribed. That
# makes them weaker than the live resolvers above and the report says so
# explicitly rather than letting all citations look equally checked. The
# failure they still catch is the common one: a citation to a rule id that
# never existed, or a measurement moved between the v1 and deferred lists.
# ---------------------------------------------------------------------------

GA_RULES = tuple(f"GA-{n}" for n in range(1, 18)) + ("GA-14b", "GA-14c")
GA_DIAGNOSTICS = tuple(f"RHO{4000 + n}" for n in range(1, 11))

# Ground-architecture section 7, "Out of scope for v1 (declared honestly)".
GA_EXCLUSIONS = (
    "return-path",
    "current-density",
    "split-plane",
    "emi",
    "creepage",
    "multi-point-bonding",
    "surge",
)

# Requirements section 3, "Non-goals (v1)".
NON_GOALS = (
    "placement-routing",
    "xy-coordinates",
    "fab-outputs",
    "thermal-analysis",
    "emi-analysis",
    "mechanical-analysis",
    "digital-simulation",
    "interchange-format",
    "turing-complete",
    "gui-editor",
    "kicad-import",
)

# V2's DEFERRED list. Its v1 counterpart is not here: that one is the frozen
# grammar's `measurement_kind` and is resolved live in `build_resolvers`. The
# split is the whole point of having two dynamic reason codes: one says "v1
# catches this, in the other tier", the other says "v1 catches this nowhere".
#
# This half stays transcribed because a deferred kind is by definition absent
# from every frozen artifact — there is nothing in the repository to resolve it
# against, which is exactly why it is reported as transcribed on every run.
V2_DEFERRED = ("phase-margin", "gain-margin", "soa", "thd-fft", "monte-carlo", "corners")

# Requirement ids that may be cited. Deliberately the ids only: this gate
# checks that a citation names a requirement that exists, not that the
# requirement says what the rationale claims. A reviewer does the second part.
REQUIREMENTS = tuple(
    f"{letter}{n}"
    for letter, count in (("L", 9), ("T", 10), ("V", 8), ("D", 5), ("I", 10), ("A", 7), ("E", 4), ("P", 7))
    for n in range(1, count + 1)
) + ("L9b", "L9c", "AC1", "AC2", "AC3", "AC4", "AC5a", "AC5b", "AC6", "AC7")

SUMMARY_OPEN = "<!-- generated: classification-summary -->"
SUMMARY_CLOSE = "<!-- /generated -->"


class GateUnavailable(Exception):
    """The gate could not run. Exit 2, never 0 — a missing gate is not a pass."""


def load_yaml(path: Path):
    try:
        import yaml
    except ImportError:
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # malformed YAML is "could not run", not "violation"
        raise GateUnavailable(f"{path} is not readable as YAML: {exc}") from exc


# ---------------------------------------------------------------------------
# Live citation resolvers.
# ---------------------------------------------------------------------------


def resolve_d3(pointer: str, schema: dict) -> bool:
    """Walk a dotted D3 field path against the real schema.

    `pins[].abs_max.voltage` means: property `pins`, its array items, then
    `abs_max`, then `voltage`. $refs are followed, because every interesting
    field in that schema sits behind one.
    """
    defs = schema.get("$defs", {})

    def deref(node):
        seen = 0
        while isinstance(node, dict) and "$ref" in node and seen < 20:
            ref = node["$ref"]
            if not ref.startswith("#/$defs/"):
                return None
            node = defs.get(ref[len("#/$defs/"):])
            seen += 1
        return node

    node = deref(schema)
    for segment in pointer.split("."):
        array = segment.endswith("[]")
        name = segment[:-2] if array else segment
        if not isinstance(node, dict):
            return False
        properties = node.get("properties") or {}
        if name not in properties:
            return False
        node = deref(properties[name])
        if array:
            if not isinstance(node, dict) or "items" not in node:
                return False
            node = deref(node["items"])
    return node is not None


def checker_reliable(pointer: str) -> bool:
    """Is this D3 path one a check may depend on at v0?

    Prefix match, so `pins[].abs_max.voltage` is covered by `pins[].abs_max`.
    """
    # Deny-list first. `pins[].abs_max.voltage` is reliable, but
    # `pins[].abs_max.voltage.conditions` reaches an open map THROUGH it, and a
    # prefix match alone happily allowed that.
    if any(segment in CHECKER_UNRELIABLE_D3 for segment in pointer.split(".")):
        return False
    return any(
        pointer == allowed or pointer.startswith(allowed + ".")
        for allowed in CHECKER_RELIABLE_D3
    )


def load_frozen_grammar():
    """Import the frozen grammar module, or None when it cannot be loaded."""
    if str(GRAMMAR_DIR) not in sys.path:
        sys.path.insert(0, str(GRAMMAR_DIR))
    try:
        from grammar import rhoform_syntax
    except Exception as exc:
        # Report the cause. `lang/` is outside this issue's path claim, so when
        # it moves under someone else's change this gate goes red and the
        # message needs to say why rather than shrugging.
        raise GateUnavailable(
            f"the frozen grammar module could not be imported ({exc!r}), so "
            "`syntax:` and `vocab:` citations cannot be resolved"
        ) from exc
    return rhoform_syntax


def build_resolvers(schema, grammar):
    """Map citation prefix to a predicate. Live spaces first, transcribed after."""
    rule_names = {name for name, _doc, _node in grammar.RULES} if grammar else set()
    terminals = set(grammar.TERMINALS) if grammar else set()
    keywords = set(grammar.KEYWORDS) if grammar else set()
    vocabularies = grammar.CLOSED_VOCABULARIES if grammar else {}

    # V2's v1 vocabulary is NOT transcribed: it is the frozen grammar's
    # `measurement_kind`, in the module already imported two lines up, spelled
    # with hyphens here because that is how the citations read.
    #
    # It used to be a hand-copied tuple justified by "the memo is in Notion and
    # this gate cannot fetch it offline" — true of the memo, false of the
    # vocabulary, which is in this repository and frozen. The copy had drifted:
    # it carried `oscillation-frequency`/`oscillation-period` where the grammar
    # says `frequency`/`period`, so the gate ACCEPTED two names no artifact
    # contains and would have REJECTED the two it does. Both spellings were
    # cited by real verdicts.
    v2_vocabulary = tuple(
        kind.replace("_", "-") for kind in vocabularies.get("measurement_kind", ())
    )

    def vocab(token: str) -> bool:
        name, _, member = token.partition(".")
        members = vocabularies.get(name)
        if members is None:
            return False
        # A bare vocabulary name is not a citation: naming `pin_role` says
        # nothing a reader can check. The member is the claim.
        return bool(member) and member in members

    return {
        "d3": (lambda t: resolve_d3(t, schema) and checker_reliable(t), "live"),
        "syntax": (lambda t: t in rule_names or t in terminals or t in keywords, "live"),
        "vocab": (vocab, "live"),
        "ga": (lambda t: t in GA_RULES or t in GA_DIAGNOSTICS, "transcribed"),
        "ga-excluded": (lambda t: t in GA_EXCLUSIONS, "transcribed"),
        "req": (lambda t: t in REQUIREMENTS, "transcribed"),
        "v2": (lambda t: t in v2_vocabulary, "live"),
        "v2-deferred": (lambda t: t in V2_DEFERRED, "transcribed"),
        "nongoal": (lambda t: t in NON_GOALS, "transcribed"),
    }


# ---------------------------------------------------------------------------
# Checks.
# ---------------------------------------------------------------------------


def decision_hash(entries) -> str:
    """Hash the decisions, and only the decisions.

    Covers the verdict, its key, and — because `d3-gap` is 29 of the 39
    out-of-scope entries — the falsifiable `gap_class` and `missing_path` that
    justify it. The rationale prose stays out: hashing it would make a typo fix
    indistinguishable from a reclassification, and people would learn to update
    the hash without reading the diff.

    Sorted so file ordering is not load-bearing, and JSON-encoded so no field
    VALUE can forge a record boundary.

    The encoding is the security property, and the previous one did not have
    it. Records were tab-joined and newline-joined, defended by this docstring
    on the grounds that "`check_entry` pins ids to ID_PATTERN" — which is true
    and irrelevant. The delimiters were reachable from every OTHER field, and
    on an in-scope entry `compound`, `gap_class`, `missing_path`, `carried_at`,
    `residual_blocker`, `residual_kind` and `gap_class_also` were unvalidated
    free text that still fed the tuple. So: delete an in-scope entry from both
    files, drop `corpus_entry_count`, and append the deleted record's line to
    the surviving entry's `compound` after a newline. The digest is unchanged,
    the gate exits 0, and the AC2 denominator has quietly gone from 22 to 21 —
    which is exactly the move this hash exists to prevent, by the issue that
    has the motive.
    `json.dumps` escapes `\\n` and `\\t`, so a value cannot contain a
    delimiter; the list encoding makes field count structural rather than
    positional. `check_entry` now also refuses out-of-scope-only fields on an
    in-scope entry, so the forged text has nowhere to live either.
    """
    lines = sorted(
        json.dumps(
            [
                e["id"],
                e["verdict"],
                e.get("family") or e.get("reason") or "",
                e.get("gap_class") or "",
                e.get("missing_path") or "",
                e.get("at_risk") or "",
                e.get("at_risk_group") or "",
                "survives" if e.get("at_risk_survives_group") else "",
                e.get("carried_at") or "",
                e.get("residual_blocker") or "",
                e.get("residual_kind") or "",
                sorted(e.get("gap_class_also") or ()),
                e.get("compound") or "",
                # The CITATION. The gate calls this "the falsifiable claim" and
                # the README says each verdict carries "the citation that
                # decided it" — and it was outside the freeze, so a
                # current-budget verdict could be repointed at a mounting-hole
                # vocabulary member at an unchanged digest.
                sorted(e.get("cites") or ()),
                # The falsifiable gap claim, for the same reason.
                e.get("missing_fact") or "",
            ],
            ensure_ascii=True,
            sort_keys=True,
        )
        for e in entries
    )
    return "sha256:" + hashlib.sha256("\n".join(lines).encode()).hexdigest()


def corpus_hash(bugs) -> str:
    """Hash the CORPUS TEXT, not just the verdicts about it.

    `decision_hash` covers classification.yaml alone, so an entry's title,
    source, symptom, root cause and evidence could all be rewritten into an
    unrelated bug while its frozen in-scope verdict stayed put and the digest
    did not move. tests/corpus/check-corpus.py closed the gutted-record half of
    that (required fields); this closes the rewritten-record half.

    Same JSON-list encoding as `decision_hash`, for the same reason: no field
    value can forge a record boundary.
    """
    lines = sorted(
        json.dumps(
            [b.get("id", ""), b.get("title", ""),
             (b.get("source") or {}).get("url", ""),
             # PROVENANCE, which was outside both hashes: 3 KB of it could be
             # deleted with every gate green. `kind` is the sole input to
             # AMB-35's "majority externally sourced" criterion and could be
             # walked from 100% to 51%; `additional_urls` is the surviving
             # provenance of all 15 dedup merges, and carries the re-check
             # evidence for three of the five corrected entries; `review` is
             # read by this gate itself to REQUIRE a residual_blocker, so
             # deleting the flag switched off the gate's own obligation; and
             # `correction_note` is the record that an entry was re-fetched,
             # which corpus/README.md calls part of the evidence.
             (b.get("source") or {}).get("kind", ""),
             sorted((b.get("source") or {}).get("additional_urls") or ()),
             b.get("symptom", ""), b.get("root_cause", ""), b.get("category", ""),
             b.get("class", ""), b.get("evidence", ""),
             b.get("collected", ""), b.get("review", ""),
             b.get("corrected", ""), b.get("correction_note", "")],
            ensure_ascii=True, sort_keys=True,
        )
        for b in bugs
    )
    return "sha256:" + hashlib.sha256("\n".join(lines).encode()).hexdigest()


def check_entry(entry, resolvers, schema, problems):
    entry_id = entry.get("id", "<no id>")
    if not ID_PATTERN.match(str(entry_id)):
        problems.append(f"{entry_id!r}: not a well-formed corpus id (expected BUG-NNNN)")
        return
    verdict = entry.get("verdict")
    if verdict not in VERDICTS:
        problems.append(f"{entry_id}: verdict {verdict!r} is not one of {VERDICTS}")
        return

    family, reason = entry.get("family"), entry.get("reason")
    if verdict == "in-scope":
        if reason is not None:
            problems.append(f"{entry_id}: in-scope entries carry `family`, not `reason`")
        if family not in FAMILIES:
            problems.append(f"{entry_id}: family {family!r} is not a declared check family")
            return
    else:
        if family is not None:
            problems.append(f"{entry_id}: out-of-scope entries carry `reason`, not `family`")
        if reason not in REASONS:
            problems.append(f"{entry_id}: reason {reason!r} is not a declared reason code")
            return

    if not (entry.get("rationale") or "").strip():
        problems.append(f"{entry_id}: no rationale")

    # Citations resolve.
    spaces_used = set()
    for citation in entry.get("cites") or []:
        prefix, sep, token = citation.partition(":")
        if not sep:
            problems.append(f"{entry_id}: citation {citation!r} has no `space:token` form")
            continue
        resolver = resolvers.get(prefix)
        if resolver is None:
            problems.append(f"{entry_id}: citation space {prefix!r} is not one of {sorted(resolvers)}")
            continue
        if not resolver[0](token):
            problems.append(
                f"{entry_id}: citation {citation!r} does not resolve — "
                f"no such {prefix} entry"
            )
            continue
        spaces_used.add(prefix)

    # Sufficiency: the citation must be of the kind the verdict needs.
    if verdict == "out-of-scope":
        if reason == "d3-gap":
            if not (entry.get("missing_fact") or "").strip():
                problems.append(
                    f"{entry_id}: reason `d3-gap` must name the missing fact in "
                    "`missing_fact` — the gap IS the finding"
                )
            # The claim `d3-gap` makes is falsifiable, so falsify it. Without
            # this the largest out-of-scope population — the one that removes
            # entries from the AC2 denominator — rested on unread prose, while
            # in-scope `d3:` citations were being walked against the schema.
            # That asymmetry pointed the wrong way.
            missing_path = (entry.get("missing_path") or "").strip()
            if not missing_path:
                problems.append(
                    f"{entry_id}: reason `{reason}` must give `missing_path` — the "
                    "field path a checker would need, so the gate can prove it is "
                    "absent rather than take the claim on trust"
                )
            elif resolve_d3(missing_path, schema):
                problems.append(
                    f"{entry_id}: `missing_path` {missing_path!r} RESOLVES against "
                    "parts/part-data.schema.json, so the fact is not missing and "
                    "`d3-gap` is the wrong reason"
                )
            elif (
                "." in missing_path
                and not resolve_d3(missing_path.rsplit(".", 1)[0], schema)
            ):
                problems.append(
                    f"{entry_id}: `missing_path` {missing_path!r} names no real place — "
                    "its anchor does not resolve either, so this asserts a gap in a "
                    "part of the schema that does not exist"
                )
            elif "." in missing_path and any(
                seg in CHECKER_UNRELIABLE_D3
                for seg in missing_path.rsplit(".", 1)[0].split(".")
            ):
                problems.append(
                    f"{entry_id}: `missing_path` {missing_path!r} anchors inside an open "
                    "map, so the fix would be a promotion — say so with `carried_at` "
                    "rather than claiming the field is absent"
                )
            elif checker_reliable(missing_path):
                problems.append(
                    f"{entry_id}: `missing_path` {missing_path!r} is inside the "
                    "checker-reliable surface, so claiming it absent contradicts "
                    "CHECKER_RELIABLE_D3"
                )
            carried_at = (entry.get("carried_at") or "").strip()
            gap_class = entry.get("gap_class") or ""
            if carried_at:
                if not resolve_d3(carried_at, schema):
                    problems.append(
                        f"{entry_id}: `carried_at` {carried_at!r} does not resolve, so "
                        "the value is not carried there and the class is wrong"
                    )
                elif checker_reliable(carried_at):
                    problems.append(
                        f"{entry_id}: `carried_at` {carried_at!r} IS checker-reliable, "
                        "so there is no gap at all"
                    )
                elif carried_at.split(".")[-1].rstrip("[]") not in CHECKER_UNRELIABLE_D3:
                    # R4: resolving and not-allowlisted is not the same as being an
                    # open map. `carried_at: notes` satisfied both and means nothing.
                    problems.append(
                        f"{entry_id}: `carried_at` {carried_at!r} does not end in an "
                        f"open map ({', '.join(CHECKER_UNRELIABLE_D3)}), so it does not "
                        "show the fact is carried anywhere"
                    )
                missing_path = (entry.get("missing_path") or "").strip()
                if (
                    carried_at
                    and missing_path.startswith("pins[].")
                    and not carried_at.startswith("pins[].")
                ):
                    problems.append(
                        f"{entry_id}: `missing_path` is per-pin but `carried_at` "
                        f"{carried_at!r} is not, so it does not carry that fact"
                    )

            # A residual is OPTIONAL on a plain `d3-gap` and mandatory on a
            # promotion. Forbidding it on gaps was what left the gap table
            # asserting one counterfactual over rows it is false for — and, for
            # BUG-0049, over a row where adding the field flags the CORRECTED
            # design instead.
            residual_kind = entry.get("residual_kind") or ""
            has_residual = bool((entry.get("residual_blocker") or "").strip())
            if has_residual and not residual_kind:
                problems.append(
                    f"{entry_id}: a `residual_blocker` must carry a `residual_kind` "
                    f"from {sorted(RESIDUAL_KINDS)} — the prose says why, the kind says "
                    "what sort of thing, and only the kind is checkable"
                )
            if residual_kind:
                if residual_kind not in RESIDUAL_KINDS:
                    problems.append(
                        f"{entry_id}: residual_kind {residual_kind!r} is not one of "
                        f"{sorted(RESIDUAL_KINDS)}"
                    )
                elif (
                    residual_kind in RESIDUAL_KIND_EMPTIES_PROMOTION
                    and entry.get("carried_at")
                ):
                    problems.append(
                        f"{entry_id}: residual_kind `{residual_kind}` says no schema "
                        "change reaches this, but `carried_at` claims the fix is a "
                        "promotion. Both cannot hold — drop `carried_at`."
                    )
                elif not has_residual:
                    problems.append(
                        f"{entry_id}: `residual_kind` without `residual_blocker` states a "
                        "category and no claim"
                    )
                if residual_kind == "v1-non-goal" and not any(
                    c.startswith(("nongoal:", "ga-excluded:"))
                    for c in (entry.get("cites") or [])
                ):
                    problems.append(
                        f"{entry_id}: residual_kind `v1-non-goal` must cite the non-goal "
                        "or ground-architecture exclusion it rests on"
                    )
            # `gap_class` is single-valued, so an entry whose missing fact is
            # a conjunction is counted under one row and understates what it
            # needs. Rather than rely on a reviewer noticing, force the call on
            # every candidate: name the second class, or say there isn't one.
            fact = entry.get("missing_fact") or ""
            if (" and " in fact or ", and " in fact) and not (
                entry.get("gap_class_also") or entry.get("compound") == "single-class"
            ):
                problems.append(
                    f"{entry_id}: `missing_fact` names more than one fact, so one "
                    "`gap_class` understates it. Give `gap_class_also`, or "
                    "`compound: single-class` if the conjunction is not a second class."
                )
            if entry.get("compound") not in (None, "single-class"):
                # Deliberately not the word `no`: YAML reads that as a boolean,
                # which silently turned every adjudication into False.
                problems.append(
                    f"{entry_id}: `compound` takes only the value `single-class`"
                )
            for extra in entry.get("gap_class_also") or []:
                if extra not in GAP_CLASSES:
                    problems.append(
                        f"{entry_id}: gap_class_also {extra!r} is not a declared class"
                    )
                elif extra == gap_class:
                    problems.append(
                        f"{entry_id}: gap_class_also repeats `gap_class`"
                    )
            if gap_class not in GAP_CLASSES:
                problems.append(
                    f"{entry_id}: gap_class {entry.get('gap_class')!r} is not one of "
                    f"{sorted(GAP_CLASSES)} — the published gap table is generated "
                    "from this field, so it cannot be free text"
                )
        else:
            for stray in ("at_risk", "at_risk_group"):
                if entry.get(stray):
                    problems.append(
                        f"{entry_id}: `{stray}` annotates in-scope entries only"
                    )
            for stray in ("gap_class", "gap_class_also", "missing_path", "carried_at",
                          "residual_blocker", "residual_kind"):
                if entry.get(stray):
                    problems.append(
                        f"{entry_id}: `{stray}` belongs only on a `d3-gap` entry"
                    )
            required = REQUIRED_SPACE[reason]
            if required and not spaces_used & set(required):
                problems.append(
                    f"{entry_id}: reason {reason!r} must cite one of "
                    f"{sorted(required)}; cites {sorted(spaces_used) or 'nothing'}"
                )
        if entry.get("missing_fact") and reason != "d3-gap":
            problems.append(f"{entry_id}: `missing_fact` only belongs on a D3 entry")
    else:
        # Out-of-scope-only fields on an in-scope entry. Symmetrical with the
        # in-scope-only sweep above, and missing until the audit that found
        # `decision_hash` forgeable: these seven fed the digest while nothing
        # constrained them, so they were the free text the forged record
        # boundary was written into. The encoding fix makes the injection
        # inert; this makes the fields unwritable in the first place.
        for stray in ("gap_class", "gap_class_also", "missing_path", "carried_at",
                      "residual_blocker", "residual_kind", "compound", "reason"):
            if entry.get(stray):
                problems.append(
                    f"{entry_id}: `{stray}` belongs only on an out-of-scope entry"
                )
        at_risk = entry.get("at_risk")
        if at_risk is not None and not str(at_risk).strip():
            problems.append(f"{entry_id}: `at_risk` is present but empty")
        # An entry can be conditional on a group's decision and still be caught
        # if it goes the wrong way, when a SECOND independent leg reaches it.
        # BUG-0025 ("the abs-max leg is independent, but the domain leg reads
        # the optional voltage_domain attribute") and BUG-0055 ("the abs-max leg
        # is independent of it, which makes this the least exposed") both say so
        # in prose, and the generated margin table counted them as lost anyway —
        # publishing "l9b-leg is a single point of failure" against the
        # classification's own annotations.
        if entry.get("at_risk_survives_group") and not at_risk:
            problems.append(f"{entry_id}: `at_risk_survives_group` without `at_risk`")
        group = entry.get("at_risk_group")
        if at_risk and group not in AT_RISK_GROUPS:
            problems.append(
                f"{entry_id}: at_risk_group {group!r} is not one of "
                f"{sorted(AT_RISK_GROUPS)} — the published single-point-of-failure list "
                "is generated from it, so it cannot be free text"
            )
        if group and not at_risk:
            problems.append(f"{entry_id}: `at_risk_group` without `at_risk`")
        required = FAMILY_REQUIRES.get(family, ())
        citations = entry.get("cites") or []
        if required and not any(c.startswith(r) for c in citations for r in required):
            problems.append(
                f"{entry_id}: family {family!r} reads {FAMILIES[family]}, but the "
                f"entry cites none of {list(required)} — a family label the "
                "citations do not support is a mislabel"
            )
        if not spaces_used & set(IN_SCOPE_SPACES):
            problems.append(
                f"{entry_id}: an in-scope verdict must cite the frozen capability the "
                f"check reads (one of {sorted(IN_SCOPE_SPACES)}); cites "
                f"{sorted(spaces_used) or 'nothing'}"
            )
        if entry.get("missing_fact"):
            problems.append(f"{entry_id}: `missing_fact` only belongs on a `d3-gap` entry")


def summary_block(entries) -> str:
    """The published populations, generated from the data.

    Hand-maintained counts drift; AMB-35's own close-out had to diff three
    histograms against the YAML by hand to prove they did not. This is the
    same generated-artifact contract `grammar.rhoform_syntax --check` uses.
    """
    in_scope = [e for e in entries if e["verdict"] == "in-scope"]
    out_scope = [e for e in entries if e["verdict"] == "out-of-scope"]
    total = len(entries)
    # The gate rounds UP: catching 89.9% of 39 is not catching 90%.
    must_catch = -(-len(in_scope) * 9 // 10)

    lines = [
        "| population | count | share |",
        "|---|---|---|",
        f"| **in-scope** (static-tier domain, expressible in the v1 DSL) | {len(in_scope)} | {len(in_scope) / total:.0%} |",
        f"| **out-of-scope** | {len(out_scope)} | {len(out_scope) / total:.0%} |",
        f"| total | {total} | |",
        "",
        f"AC2 gate: the static tier must catch **{must_catch} of {len(in_scope)}** in-scope bugs (≥90%).",
        "",
        "| in-scope check family | count |",
        "|---|---|",
    ]
    for family in sorted(FAMILIES):
        count = sum(1 for e in in_scope if e.get("family") == family)
        if count:
            lines.append(f"| `{family}` | {count} |")
    lines += ["", "| out-of-scope reason | count |", "|---|---|"]
    for reason in sorted(REASONS):
        count = sum(1 for e in out_scope if e.get("reason") == reason)
        if count:
            lines.append(f"| `{reason}` | {count} |")

    # Emitted unconditionally. An honest disclosure that vanishes when nobody
    # fills it in is worse than none: removal shows up in a diff, but an empty
    # section that was never populated shows up nowhere. Printing "0 flagged"
    # makes under-population visible as a number.
    at_risk = [e for e in in_scope if e.get("at_risk")]
    surviving = len(in_scope) - len(at_risk)
    lines += [
        "",
        f"**Margin.** {len(at_risk)} of {len(in_scope)} in-scope entries are flagged "
        "`at_risk` — verdicts whose catch is conditioned on one of four things: an "
        "implementation choice; a **defensible alternative** part-record transcription; an "
        "open-map fact; or an attribute the frozen grammar makes optional, which the design "
        "under test is therefore not required to declare. The defensibility test is what keeps "
        "the second category from covering everything — a dedicated I2C peripheral pin roled "
        "`open_drain` has no defensible alternative, while a general-purpose GPIO roled "
        "`bidirectional`, an AREF pin roled `passive`, a reserved pin roled `nc` and a record "
        "with no transmit mode all do. The fourth category is a grammar fact: `net_decl ::= "
        "'net' FREE_NAME net_attributes? ...` — a design that declares no `voltage_domain` "
        "silences every rule that reads one.",
        "",
    ]
    for entry in sorted(at_risk, key=lambda e: e["id"]):
        lines.append(f"- `{entry['id']}` — {entry['at_risk']}")
    if not at_risk:
        lines.append("- none flagged")
    if surviving >= must_catch:
        tail = (
            f"Lose all {len(at_risk)} and the tier still catches {surviving} of "
            f"{len(in_scope)} against a bar of {must_catch}, so the margin survives the "
            "whole risk register."
        )
    else:
        tail = (
            f"{len(at_risk)} of {len(in_scope)} verdicts are conditional and only "
            f"{surviving} are unconditional, which is fewer than the bar of {must_catch}. "
            "So **the AC2 outcome is decided by part-record authoring and "
            "rule-implementation choices, not by this classification**. The flags are not "
            f"independent, though: counting them as {len(at_risk)} separate risks would "
            "overstate the exposure and bury the actionable part. They are a handful of "
            "decisions."
        )
    emptied = sorted(
        {
            e["family"]
            for e in at_risk
            if not any(
                o.get("family") == e["family"] and not o.get("at_risk") for o in in_scope
            )
        }
    )
    if emptied:
        tail += (
            " Losing them also empties "
            + (f"`{emptied[0]}`" if len(emptied) == 1
               else ", ".join(f"`{f}`" for f in emptied[:-1]) + f" and `{emptied[-1]}`")
            + " entirely, so the gate would stop testing "
            + ("that family" if len(emptied) == 1 else "those families")
            + " at all — which no count above shows."
        )
    lines += ["", tail]
    if at_risk:
        groups = {}
        for entry in at_risk:
            groups.setdefault(entry.get("at_risk_group"), []).append(
                (entry["id"], bool(entry.get("at_risk_survives_group"))))
        lines += ["", "| decision | entries | caught if it goes the wrong way | verdict |",
                  "|---|---|---|---|"]
        alone_fails = []
        for key in sorted(groups, key=lambda k: (-len(groups[k]), k)):
            members = sorted(groups[key])
            # Only entries the decision actually LOSES count against the margin.
            lost = [m for m in members if not m[1]]
            left = len(in_scope) - len(lost)
            if left < must_catch:
                alone_fails.append(key)
                outcome = "**fails**"
            elif left == must_catch:
                outcome = "passes, with nothing to spare"
            else:
                outcome = f"passes, {left - must_catch} to spare"
            if key in INDEPENDENT_GROUPS:
                tolerable = len(in_scope) - must_catch
                outcome += f" (but any {tolerable + 1} of them fails)"
            lines.append(
                f"| **`{key}`** — {AT_RISK_GROUPS.get(key, '?')} | "
                + ", ".join(
                    f"`{i}`" + (" (survives; a second leg is independent)" if s else "")
                    for i, s in members)
                + f" | {left} of {len(in_scope)} | {outcome} |"
            )
        if alone_fails:
            named = ", ".join(f"`{k}`" for k in alone_fails)
            lines += [
                "",
                f"{named} "
                + ("is a single point of failure for AC2 on its own"
                   if len(alone_fails) == 1
                   else "are each a single point of failure for AC2 on their own")
                + ", and the groups that pass alone do not survive being combined. Settling "
                + ("it" if len(alone_fails) == 1 else "those")
                + " is worth more to AMB-61 than any amount of checker tuning.",
            ]

    gaps = [e for e in out_scope if e.get("reason") == "d3-gap"]
    if gaps:
        lines += [
            "",
            f"The {len(gaps)} `d3-gap` entries by missing fact. Each row is also the "
            "counterfactual: add that field and those entries become candidates for "
            "in-scope at the next `schema_version`.",
            "",
            "| missing D3 fact | entries | with a residual blocker |",
            "|---|---|---|",
        ]
        for gap_class, description in sorted(
            GAP_CLASSES.items(),
            key=lambda kv: (-sum(1 for e in gaps if e.get("gap_class") == kv[0]), kv[0]),
        ):
            members = [e["id"] for e in gaps if e.get("gap_class") == gap_class]
            if members:
                qualified = [
                    e["id"] for e in gaps
                    if e.get("gap_class") == gap_class and e.get("residual_blocker")
                ]
                note = ", ".join(f"`{i}`" for i in qualified) if qualified else "—"
                lines.append(
                    f"| `{gap_class}` — {description} | {len(members)} | {note} |"
                )
        compound = sorted(e["id"] for e in gaps if e.get("gap_class_also"))
        if compound:
            lines += [
                "",
                "Counted once but blocked by more than one missing fact, so the single row "
                "understates what each needs: "
                + ", ".join(f"`{i}`" for i in compound)
                + ".",
            ]
        lines += [
            "",
            "Entries in the third column carry a blocker that survives adding the field, "
            "named in `classification.yaml`. For one of them the counterfactual is not "
            "merely weaker but inverted: adding the fact would make the generic rule flag "
            "the *corrected* design.",
        ]

    promotions = [e for e in out_scope if e.get("carried_at")]
    if promotions:
        lines += [
            "",
            (
                f"{len(promotions)} entry makes" if len(promotions) == 1
                else f"{len(promotions)} of those entries make"
            )
            + " a weaker claim: the fact is already in D3 v0, in an open map, so the fix is "
            "to **promote** a key rather than add a field. Marked here rather than given a "
            "reason code: the population is small enough that a code would cost more than "
            "it buys, and both entries carry a further blocker anyway. "
            "(This sentence read \"a code with one member\" while the table had two, "
            "because the count above it was generated and the clause after it was not.)",
            "",
            "| entry | carried at | further blocker, if any |",
            "|---|---|---|",
        ]
        for entry in sorted(promotions, key=lambda e: e["id"]):
            lines.append(
                f"| `{entry['id']}` | `{entry.get('carried_at')}` | "
                f"{entry.get('residual_blocker') or '—'} |"
            )
    return "\n".join(lines)


def replace_summary(text: str, block: str) -> str:
    pattern = re.compile(
        re.escape(SUMMARY_OPEN) + r".*?" + re.escape(SUMMARY_CLOSE), re.DOTALL
    )
    return pattern.sub(f"{SUMMARY_OPEN}\n\n{block}\n\n{SUMMARY_CLOSE}", text, count=1)


def extract_summary(text: str):
    match = re.search(
        re.escape(SUMMARY_OPEN) + r"(.*?)" + re.escape(SUMMARY_CLOSE), text, re.DOTALL
    )
    return match.group(1).strip() if match else None


def run(write: bool, bugs=None, classification=None, readme=None) -> int:
    """Paths are injectable so the self-test can drive THIS function.

    The alternative — a self-test that exercises `check_entry` and reimplements
    the wiring — is how a kill switch quietly moves down a layer: every
    individual matcher proven, and the loop that calls them proven by nobody.
    """
    bugs = bugs or BUGS
    classification = classification or CLASSIFICATION
    readme = readme or README

    for path in (bugs, classification, readme, PART_SCHEMA):
        if not path.exists():
            print(f"corpus-classification: FAIL: {path} is missing", file=sys.stderr)
            return 2

    corpus = load_yaml(bugs)
    document = load_yaml(classification)
    if corpus is None or document is None:
        print(
            "corpus-classification: FAIL: PyYAML is unavailable, so the "
            "classification cannot be read. An unavailable gate is not a pass.",
            file=sys.stderr,
        )
        return 2

    schema = json.loads(PART_SCHEMA.read_text(encoding="utf-8"))
    resolvers = build_resolvers(schema, load_frozen_grammar())

    entries = document.get("entries") or []
    problems: list[str] = []

    # Coverage: exact bijection with the corpus.
    corpus_bugs = corpus.get("bugs") or []
    if any("id" not in b for b in corpus_bugs):
        raise GateUnavailable(f"{bugs} has an entry with no `id`")
    corpus_ids = [b["id"] for b in corpus_bugs]

    # AC2's other two numbers. The freeze protects the denominator's
    # composition; nothing protected its floor, and the README already
    # nominates one entry for retirement.
    if len(corpus_ids) < 50:
        problems.append(
            f"the corpus holds {len(corpus_ids)} entries; AC2 requires at least 50"
        )
    declared = document.get("classification", {}).get("corpus_entry_count")
    if declared != len(corpus_ids):
        problems.append(
            f"classification declares corpus_entry_count {declared}, but the corpus "
            f"holds {len(corpus_ids)} — a decorative count inside a frozen artifact "
            "is worse than none"
        )
    classified = [e.get("id") for e in entries]
    duplicates = sorted({i for i in classified if classified.count(i) > 1})
    if duplicates:
        problems.append(f"classified more than once: {', '.join(duplicates)}")
    missing = sorted(set(corpus_ids) - set(classified))
    if missing:
        problems.append(
            f"in the corpus but not classified: {', '.join(missing)} — an "
            "unclassified bug silently changes the AC2 denominator"
        )
    strays = sorted(set(classified) - set(corpus_ids))
    if strays:
        problems.append(f"classified but not in the corpus: {', '.join(strays)}")

    flagged = {b["id"]: b["review"] for b in corpus_bugs if b.get("review")}
    for entry in entries:
        check_entry(entry, resolvers, schema, problems)
        # A `review:` flag on the corpus record is a residual by another name,
        # in another file. Unjoined, an entry could be counted among the ones a
        # schema change rescues while its own record says it may not survive
        # review at all.
        if (
            entry.get("verdict") == "out-of-scope"
            and entry["id"] in flagged
            and not (entry.get("residual_blocker") or "").strip()
        ):
            problems.append(
                f"{entry['id']}: corpus record carries `review: {flagged[entry['id']]}`, "
                "so the published counterfactual may not hold for it. State a "
                "`residual_blocker`, or move the flag if it does not bear on scope."
            )

    # Freeze.
    committed = document.get("classification", {}).get("decision_hash")
    computed = decision_hash(entries) if not problems else None
    if computed and committed != computed:
        if write:
            text = classification.read_text(encoding="utf-8")
            rewritten, count = re.subn(
                r"^(\s*decision_hash:\s*).*$",
                lambda m: m.group(1) + computed,
                text,
                count=1,
                flags=re.MULTILINE,
            )
            if count != 1:
                problems.append(
                    "cannot refreeze: classification.yaml has no single "
                    "`decision_hash:` line to rewrite"
                )
            else:
                classification.write_text(rewritten, encoding="utf-8")
                print(f"corpus-classification: refroze decision_hash to {computed}")
                committed = computed
        else:
            problems.append(
                f"decision_hash is {committed}, but the verdicts hash to {computed}. "
                "A verdict changed. That is allowed and sometimes right — but it "
                "moves the AC2 denominator, so it must be a deliberate, reviewed "
                "commit: rerun with --write and say why in the message."
            )

    # And the CORPUS TEXT. `decision_hash` covers classification.yaml alone, so
    # a bug's title, source, symptom, root cause and evidence could all be
    # rewritten into an unrelated defect while its frozen verdict stayed put and
    # the digest did not move. A verdict sitting on a different bug is exactly
    # the thing "frozen" is supposed to rule out.
    committed_corpus = document.get("classification", {}).get("corpus_hash")
    computed_corpus = corpus_hash(corpus_bugs) if not problems else None
    if computed_corpus and committed_corpus != computed_corpus:
        if write:
            text = classification.read_text(encoding="utf-8")
            if "corpus_hash:" in text:
                rewritten, count = re.subn(
                    r"^(\s*corpus_hash:\s*).*$",
                    lambda m: m.group(1) + computed_corpus,
                    text, count=1, flags=re.MULTILINE)
            else:
                rewritten, count = re.subn(
                    r"^(\s*decision_hash:\s*.*)$",
                    lambda m: m.group(1) + "\n  corpus_hash: " + computed_corpus,
                    text, count=1, flags=re.MULTILINE)
            if count != 1:
                problems.append("cannot refreeze: no place to write `corpus_hash:`")
            else:
                classification.write_text(rewritten, encoding="utf-8")
                print(f"corpus-classification: refroze corpus_hash to {computed_corpus}")
        else:
            problems.append(
                f"corpus_hash is {committed_corpus}, but corpus/bugs.yaml hashes "
                f"to {computed_corpus}. A bug's TEXT changed under a frozen "
                "verdict. Correcting an entry is allowed — AMB-36 corrected five "
                "— but it must be deliberate: rerun with --write and say what "
                "changed and why."
            )

    # Published populations.
    if not problems:
        block = summary_block(entries)
        text = readme.read_text(encoding="utf-8")
        if extract_summary(text) is None:
            problems.append(
                f"corpus/README.md has no {SUMMARY_OPEN} block, so the populations "
                "AC2 requires published are not published"
            )
        elif extract_summary(text) != block:
            if write:
                readme.write_text(replace_summary(text, block), encoding="utf-8")
                print("corpus-classification: regenerated the README summary block")
            else:
                problems.append(
                    "corpus/README.md's published summary does not match the "
                    "classification. Regenerate it with --write."
                )

    for problem in problems:
        print(f"corpus-classification: FAIL: {problem}", file=sys.stderr)
    if problems:
        return 1

    in_scope = sum(1 for e in entries if e["verdict"] == "in-scope")
    transcribed = sorted(p for p, (_fn, kind) in resolvers.items() if kind == "transcribed")
    print(
        f"corpus-classification: unverified: citation spaces {', '.join(transcribed)} "
        "resolve against lists transcribed from Notion specifications, not against "
        "the documents themselves — this gate runs offline."
    )
    print(
        f"corpus-classification: PASS: {len(entries)} entries classified exactly once, "
        f"{in_scope} in scope, every citation resolves, decision_hash matches, "
        "populations published."
    )
    return 0


# ---------------------------------------------------------------------------
# Self-test.
# ---------------------------------------------------------------------------


def self_test() -> int:
    """Prove each check fails on the mutation it exists to catch.

    Every check below has a matching mutation. A gate whose failure nobody has
    watched is a gate nobody knows works — the same argument that put a
    self-test on the part linter and the IR hash check.
    """
    schema = json.loads(PART_SCHEMA.read_text(encoding="utf-8"))
    grammar = load_frozen_grammar()
    if grammar is None:
        print("corpus-classification: FAIL: cannot import the frozen grammar", file=sys.stderr)
        return 2
    resolvers = build_resolvers(schema, grammar)

    def problems_for(entry):
        found: list[str] = []
        check_entry(entry, resolvers, schema, found)
        return found

    good_in = {
        "id": "BUG-0001", "verdict": "in-scope", "family": "erc-pin-role",
        "cites": ["req:T2", "d3:pins[].role"], "rationale": "ok",
    }
    good_out = {
        "id": "BUG-0002", "verdict": "out-of-scope", "reason": "v1-non-goal",
        "cites": ["nongoal:thermal-analysis"], "rationale": "ok",
    }
    good_gap = {
        "id": "BUG-0003", "verdict": "out-of-scope", "reason": "d3-gap",
        "cites": ["d3:pins[].role"], "rationale": "ok",
        "missing_fact": "reset-time strap semantics",
        "missing_path": "pins[].strap", "gap_class": "strap-semantics",
    }

    good_promo = {
        "id": "BUG-0004", "verdict": "out-of-scope", "reason": "d3-gap",
        "cites": [], "rationale": "ok",
        "gap_class": "internal-pull",
        "missing_fact": "the value behind a conventional key",
        "missing_path": "pins[].internal_pull",
        "carried_at": "pins[].characteristics",
    }

    checks = [
        ("a well-formed in-scope entry passes", not problems_for(good_in)),
        ("a well-formed out-of-scope entry passes", not problems_for(good_out)),
        ("a well-formed d3-gap entry passes", not problems_for(good_gap)),
        ("a malformed id is rejected", problems_for({**good_in, "id": "BUG-1"})),
        ("an unknown verdict is rejected", problems_for({**good_in, "verdict": "maybe"})),
        ("an unknown family is rejected", problems_for({**good_in, "family": "vibes"})),
        ("an unknown reason is rejected", problems_for({**good_out, "reason": "too-hard"})),
        ("an in-scope entry carrying a reason is rejected",
         problems_for({**good_in, "reason": "d3-gap"})),
        ("an out-of-scope entry carrying a family is rejected",
         problems_for({**good_out, "family": "net-topology"})),
        ("a missing rationale is rejected", problems_for({**good_in, "rationale": "  "})),
        ("a citation with no space is rejected", problems_for({**good_in, "cites": ["T2"]})),
        ("an unknown citation space is rejected",
         problems_for({**good_in, "cites": ["vibes:T2"]})),
        # The live resolvers, each against a plausible-looking miss.
        ("a D3 field that does not exist is rejected",
         problems_for({**good_in, "cites": ["d3:pins[].strap_level"]})),
        ("a D3 field reached without the array step is rejected",
         problems_for({**good_in, "cites": ["d3:pins.role"]})),
        ("a real D3 field resolves", not problems_for({**good_in, "cites": ["d3:pins[].role", "d3:modes[].draw"]})),
        ("a nested D3 field resolves",
         not problems_for({**good_in, "cites": ["d3:pins[].role", "d3:pins[].abs_max.voltage"]})),
        ("a grammar production that does not exist is rejected",
         problems_for({**good_in, "cites": ["syntax:strap_decl"]})),
        ("a real grammar production resolves",
         not problems_for({**good_in, "cites": ["d3:pins[].role", "syntax:isolated_decl"]})),
        ("a vocabulary member that does not exist is rejected",
         problems_for({**good_in, "cites": ["vocab:pin_role.strap"]})),
        ("a real vocabulary member resolves",
         not problems_for({**good_in, "cites": ["d3:pins[].role", "vocab:pin_role.open_drain"]})),
        # Sufficiency: the citation must be of the right KIND.
        ("a non-goal verdict citing no non-goal is rejected",
         problems_for({**good_out, "cites": ["req:T5"]})),
        ("a deferred verdict citing a v1 measurement is rejected",
         problems_for({**good_out, "reason": "dynamic-deferred", "cites": ["v2:ripple"]})),
        ("a deferred verdict citing a deferred measurement passes",
         not problems_for({**good_out, "reason": "dynamic-deferred", "cites": ["v2-deferred:phase-margin"]})),
        ("a d3-gap with no missing_fact is rejected",
         problems_for({**good_gap, "missing_fact": ""})),
        ("a d3-gap with no missing_path is rejected",
         problems_for({**good_gap, "missing_path": ""})),
        ("a d3-gap whose missing_path RESOLVES is rejected",
         problems_for({**good_gap, "missing_path": "pins[].role"})),
        ("a d3-gap with an unknown gap_class is rejected",
         problems_for({**good_gap, "gap_class": "vibes"})),
        ("a well-formed promotion entry passes", not problems_for(good_promo)),
        ("a promotion whose carried_at does not resolve is rejected",
         problems_for({**good_promo, "carried_at": "pins[].nope"})),
        ("a promotion whose carried_at is checker-reliable is rejected",
         problems_for({**good_promo, "carried_at": "pins[].role"})),
        ("a promotion whose carried_at is not an open map is rejected",
         problems_for({**good_promo, "carried_at": "notes"})),
        ("a residual kind that empties the promotion contradicts carried_at",
         problems_for({**good_promo, "residual_blocker": "x",
                       "residual_kind": "designs-identical"})),
        ("a missing_path whose anchor does not resolve is rejected",
         problems_for({**good_gap, "missing_path": "nowhere.zz"})),
        ("a missing_path anchored inside an open map is rejected",
         problems_for({**good_gap, "missing_path": "pins[].characteristics.zz"})),
        ("an unknown gap_class_also is rejected",
         problems_for({**good_gap, "gap_class_also": ["vibes"]})),
        ("a gap_class_also repeating gap_class is rejected",
         problems_for({**good_gap, "gap_class_also": ["strap-semantics"]})),
        ("a valid gap_class_also passes",
         not problems_for({**good_gap, "gap_class_also": ["bus-address"]})),
        ("a residual_blocker on a plain d3-gap is allowed with a kind",
         not problems_for({**good_gap, "residual_blocker": "still blocked",
                           "residual_kind": "counterfactual-inverted"})),
        ("a residual_blocker with no residual_kind is rejected",
         problems_for({**good_gap, "residual_blocker": "still blocked"})),
        ("an unknown residual_kind is rejected",
         problems_for({**good_gap, "residual_blocker": "x", "residual_kind": "vibes"})),
        ("a residual_kind with no residual_blocker is rejected",
         problems_for({**good_gap, "residual_kind": "counterfactual-inverted"})),
        ("residual_kind v1-non-goal without a non-goal citation is rejected",
         problems_for({**good_gap, "residual_blocker": "x", "residual_kind": "v1-non-goal"})),
        ("residual_kind v1-non-goal citing a non-goal passes",
         not problems_for({**good_gap, "residual_blocker": "x",
                           "residual_kind": "v1-non-goal",
                           "cites": ["nongoal:xy-coordinates"]})),
        ("fact-undocumented alongside carried_at is rejected",
         problems_for({**good_promo, "residual_blocker": "x",
                       "residual_kind": "fact-undocumented"})),
        ("a per-pin missing_path with a part-level carried_at is rejected",
         problems_for({**good_promo, "carried_at": "parameters"})),
        ("a d3 path reaching an open map through a reliable prefix is rejected",
         problems_for({**good_in, "cites": ["d3:pins[].abs_max.voltage.conditions"]})),
        ("a family whose citations do not support it is rejected",
         problems_for({**good_in, "family": "abs-max-containment",
                       "cites": ["d3:pins[].role"]})),
        ("an unexercised family row still rejects a bad citation",
         problems_for({**good_in, "family": "part-binding", "cites": ["d3:pins[].role"]})),
        ("an unexercised family row accepts a good citation",
         not problems_for({**good_in, "family": "part-binding",
                           "cites": ["d3:pins[].role", "syntax:part_decl"]})),
        ("a family whose citations do support it passes",
         not problems_for({**good_in, "family": "abs-max-containment",
                           "cites": ["d3:pins[].abs_max.voltage"]})),
        ("at_risk on an out-of-scope entry is rejected",
         problems_for({**good_out, "at_risk": "something"})),
        ("at_risk with no group is rejected",
         problems_for({**good_in, "at_risk": "conditional"})),
        ("at_risk with an unknown group is rejected",
         problems_for({**good_in, "at_risk": "conditional", "at_risk_group": "vibes"})),
        ("at_risk with a known group passes",
         not problems_for({**good_in, "at_risk": "conditional",
                           "at_risk_group": "part-record"})),
        ("at_risk_group with no at_risk is rejected",
         problems_for({**good_in, "at_risk_group": "part-record"})),
        ("a compound missing_fact with no adjudication is rejected",
         problems_for({**good_gap, "missing_fact": "one thing and another thing"})),
        ("a compound missing_fact adjudicated single-class passes",
         not problems_for({**good_gap, "missing_fact": "one thing and its own detail",
                           "compound": "single-class"})),
        ("a compound missing_fact with a second class passes",
         not problems_for({**good_gap, "missing_fact": "one thing and another",
                           "gap_class_also": ["bus-address"]})),
        ("compound with any other value is rejected",
         problems_for({**good_gap, "missing_fact": "a and b", "compound": "yes"})),
        ("an open-map d3 citation is rejected as not checker-reliable",
         problems_for({**good_in, "cites": ["d3:parameters"]})),
        ("a d3 citation into an open map is rejected",
         problems_for({**good_in, "cites": ["d3:pins[].characteristics"]})),
        ("a bare vocabulary name is not a citation",
         problems_for({**good_in, "cites": ["vocab:pin_role"]})),
        ("an in-scope entry citing only a transcribed requirement is rejected",
         problems_for({**good_in, "cites": ["req:T2"]})),
        ("missing_fact on a non-gap entry is rejected",
         problems_for({**good_out, "missing_fact": "something"})),
        ("an in-scope entry citing nothing capability-bearing is rejected",
         problems_for({**good_in, "cites": ["nongoal:thermal-analysis"]})),
    ]

    # The freeze itself: a changed verdict must move the hash, and reordering
    # must not.
    a = [{"id": "A", "verdict": "in-scope", "family": "net-topology"},
         {"id": "B", "verdict": "out-of-scope", "reason": "d3-gap"}]
    b = [dict(a[1]), dict(a[0])]
    c = [dict(a[0]), {**a[1], "reason": "v1-non-goal"}]
    checks.append(("reordering entries does not move decision_hash", decision_hash(a) == decision_hash(b)))
    checks.append(("changing one verdict moves decision_hash", decision_hash(a) != decision_hash(c)))
    for field, value in (("gap_class", "bus-address"), ("missing_path", "pins[].other"),
                         ("at_risk", "narrowed"), ("carried_at", "parameters"),
                         ("residual_blocker", "still blocked"),
                         ("residual_kind", "designs-identical")):
        moved = [dict(a[0]), {**a[1], field: value}]
        checks.append((f"changing {field} moves decision_hash",
                       decision_hash(a) != decision_hash(moved)))

    # The ENCODING, not just the field set. A delimiter reachable from a field
    # value lets one record forge another's boundary: with tab/newline joining,
    # appending "\n" + a deleted record's line to a surviving entry's free text
    # reproduced the deleted record at an unchanged digest, dropping the AC2
    # denominator from 22 to 21 with the gate green. JSON escapes both
    # delimiters, so the forged text can only ever be part of one field.
    victim = {"id": "BUG-0019", "verdict": "in-scope", "family": "erc-pin-role"}
    survivor = {"id": "BUG-0018", "verdict": "in-scope", "family": "erc-pin-role"}
    forged = [{**survivor, "compound": "\n" + json.dumps(
        [victim["id"], victim["verdict"], victim["family"],
         "", "", "", "", "", "", "", [], ""])}]
    checks.append((
        "changing a citation moves decision_hash",
        decision_hash([{"id": "BUG-0001", "verdict": "in-scope", "family": "erc-pin-role",
                        "cites": ["d3:pins[].role"]}])
        != decision_hash([{"id": "BUG-0001", "verdict": "in-scope", "family": "erc-pin-role",
                           "cites": ["d3:pins[].abs_max"]}]),
    ))
    checks.append((
        "rewriting a bug's text moves corpus_hash",
        corpus_hash([{"id": "BUG-0001", "title": "a real bug"}])
        != corpus_hash([{"id": "BUG-0001", "title": "a ceiling fan wobble"}]),
    ))
    checks.append((
        "a field value cannot forge a record boundary in corpus_hash",
        corpus_hash([{"id": "BUG-0001", "title": "x"}, {"id": "BUG-0002", "title": "y"}])
        != corpus_hash([{"id": "BUG-0001",
                         "title": "x\n" + json.dumps(["BUG-0002", "y", "", "", "", "", "", ""])}]),
    ))
    checks.append((
        "a field value cannot forge a record boundary in decision_hash",
        decision_hash([victim, survivor]) != decision_hash(forged),
    ))

    # And the field is unwritable in the first place, which is the other half.
    stray_problems: list[str] = []
    check_entry({**survivor, "cites": ["d3:pins[].role"], "compound": "x"},
                {"d3": (lambda _t: True, "live")}, None, stray_problems)
    checks.append((
        "an out-of-scope-only field on an in-scope entry is rejected",
        any("belongs only on an out-of-scope entry" in p for p in stray_problems),
    ))

    # And the published-summary contract: the block must be derived, so a
    # count that no longer matches the data must not survive a round trip.
    text = f"before\n{SUMMARY_OPEN}\nstale counts\n{SUMMARY_CLOSE}\nafter"
    rewritten = replace_summary(text, "fresh counts")
    checks.append(("the summary block is replaceable in place",
                   extract_summary(rewritten) == "fresh counts" and "before" in rewritten and "after" in rewritten))

    # WIRING. Everything above proves a matcher fires; none of it proves the
    # shipped entry point CALLS the matchers. That gap is how a kill switch
    # moves down a layer — each check verified, the loop that runs them
    # verified by nobody — so these cases drive `run()` itself over a
    # throwaway tree and assert the exit code.
    checks.extend(_wiring_checks())

    return _report(checks)


def _wiring_checks():
    """Drive the shipped `run()` over a temp tree, once clean and once mutated."""
    import contextlib
    import io
    import tempfile

    ids = [f"BUG-{n:04d}" for n in range(1, 51)]
    good_bugs = {"entry_count": len(ids), "bugs": [{"id": i} for i in ids]}
    good_entries = [
        {"id": i, "verdict": "in-scope", "family": "net-topology",
         "cites": ["syntax:net_decl"], "rationale": "ok"}
        for i in ids[:25]
    ] + [
        {"id": i, "verdict": "out-of-scope", "reason": "v1-non-goal",
         "cites": ["nongoal:thermal-analysis"], "rationale": "ok"}
        for i in ids[25:]
    ]

    def render(bugs, entries, digest):
        bug_text = "entry_count: {}\nbugs:\n".format(bugs["entry_count"]) + "".join(
            f"- id: {b['id']}\n" for b in bugs["bugs"]
        )
        lines = [
            "classification:",
            "  corpus_entry_count: {}".format(bugs["entry_count"]),
            f"  decision_hash: {digest}",
            f"  corpus_hash: {corpus_hash(bugs['bugs'])}",
            "entries:",
        ]
        for e in entries:
            lines.append(f"- id: {e['id']}")
            lines.append(f"  verdict: {e['verdict']}")
            key = "family" if "family" in e else "reason"
            lines.append(f"  {key}: {e[key]}")
            lines.append("  cites: [{}]".format(", ".join(f'"{c}"' for c in e["cites"])))
            for extra in ("gap_class", "missing_path", "missing_fact"):
                if e.get(extra):
                    lines.append(f"  {extra}: {e[extra]}")
            lines.append(f"  rationale: {e['rationale']}")
        return bug_text, "\n".join(lines) + "\n"

    results = []
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)

        def attempt(bugs, entries, digest, readme_block=None, stale_corpus_hash=None):
            bug_text, cls_text = render(bugs, entries, digest)
            if stale_corpus_hash:
                cls_text = re.sub(r"^(\s*corpus_hash:\s*).*$",
                                  lambda m: m.group(1) + stale_corpus_hash,
                                  cls_text, count=1, flags=re.MULTILINE)
            (tmp / "bugs.yaml").write_text(bug_text, encoding="utf-8")
            (tmp / "classification.yaml").write_text(cls_text, encoding="utf-8")
            block = summary_block(entries) if readme_block is None else readme_block
            (tmp / "README.md").write_text(
                f"{SUMMARY_OPEN}\n\n{block}\n\n{SUMMARY_CLOSE}\n", encoding="utf-8"
            )
            # Swallow the gate's own diagnostics. A self-test that prints
            # "FAIL:" lines while passing trains people to skim past the
            # word, which is the one word this file needs them to read.
            sink = io.StringIO()
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                return run(
                    write=False,
                    bugs=tmp / "bugs.yaml",
                    classification=tmp / "classification.yaml",
                    readme=tmp / "README.md",
                )

        digest = decision_hash(good_entries)
        results.append(("run() passes a well-formed tree", attempt(good_bugs, good_entries, digest) == 0))

        # The single check standing between AMB-61 and a moved denominator.
        extra = {"entry_count": len(ids) + 1,
                 "bugs": good_bugs["bugs"] + [{"id": "BUG-0099"}]}
        results.append(("run() rejects a corpus bug with no verdict",
                        attempt(extra, good_entries, digest) == 1))

        flipped = [dict(e) for e in good_entries]
        flipped[-1] = {"id": flipped[-1]["id"], "verdict": "in-scope",
                       "family": "net-topology", "cites": ["syntax:net_decl"],
                       "rationale": "ok"}
        results.append(("run() rejects a verdict change against the committed hash",
                        attempt(good_bugs, flipped, digest) == 1))

        # A stale corpus_hash must fail run(), whatever moved it. Driven by
        # planting the wrong digest rather than by rewriting a bug, because this
        # fixture's bugs carry only an `id` — the real rewritten-bug case is
        # covered by the three corpus_hash cases above and was demonstrated
        # end-to-end against the committed corpus.
        results.append(("run() rejects a stale corpus_hash",
                        attempt(good_bugs, good_entries, digest,
                                stale_corpus_hash="sha256:" + "0" * 64) == 1))

        results.append(("run() rejects a README summary that drifted",
                        attempt(good_bugs, good_entries, digest, readme_block="| stale |") == 1))

        short_ids = ids[:40]
        short_bugs = {"entry_count": len(short_ids), "bugs": [{"id": i} for i in short_ids]}
        short_entries = [e for e in good_entries if e["id"] in set(short_ids)]
        results.append(("run() rejects a corpus below AC2's floor of 50",
                        attempt(short_bugs, short_entries, decision_hash(short_entries)) == 1))
        results.append(("run() rejects a mis-declared corpus_entry_count",
                        attempt({**good_bugs, "entry_count": 999}, good_entries, digest) == 1))
    return results


def _report(checks) -> int:
    failed = 0
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
        failed += 0 if ok else 1
    if failed:
        print(f"corpus-classification: SELF-TEST FAILED: {failed} check(s)", file=sys.stderr)
        return 1
    print(f"corpus-classification: self-test PASS: {len(checks)} checks.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-test", action="store_true", help="prove the checks can fail, then exit")
    parser.add_argument(
        "--write",
        action="store_true",
        help="refreeze decision_hash and regenerate the README summary",
    )
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            return self_test()
        return run(write=args.write)
    except GateUnavailable as exc:
        print(f"corpus-classification: FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
