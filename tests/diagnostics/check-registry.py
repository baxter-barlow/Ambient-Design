#!/usr/bin/env python3
"""Gate: the diagnostic code registry keeps the promises A1 makes.

Three legs, each of which failed somewhere before it was checked here:

  1. STRUCTURE. rhoform/codes.py's own rules (unique codes and slugs,
     assigned blocks, kebab slugs, params matching templates both ways,
     retirement permanence, sorted order) — registry_problems() is the
     shared engine, this gate is what makes violating it red rather than
     a comment.
  2. THE GA TRANSCRIPTION. The ground-architecture spec published ten
     codes with slugs and structured-parameter shapes "stable from this
     document forward", and the AC2 corpus already cites them
     (tests/corpus/check-classification.py transcribes RHO4001..RHO4010).
     The registry must carry exactly that block; the table below is an
     INDEPENDENT transcription of the spec's section 6, so the registry
     agreeing with it is two documents agreeing, not one document quoted
     twice.
  3. SCHEMA SYNC. rhoform/diagnostic.schema.json restates the severity,
     category, and applicability vocabularies and the format
     discriminator as enums. Restatements drift; this leg holds each enum
     to the Python constant it restates, in both directions.

Exit 0 pass, 1 violation, 2 only when the gate cannot run at all.
Usage: check-registry.py [--self-test]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from rhoform import codes as codes_module          # noqa: E402
from rhoform import diagnostics as diag_module     # noqa: E402

SCHEMA_PATH = ROOT / "rhoform" / "diagnostic.schema.json"

# The GA spec section 6 catalog, transcribed here from the spec (Notion:
# "Rhoform Ground-Architecture Semantics", CC-BY-4.0), NOT imported from
# the registry. Columns: code, slug, severity, params, rule. RHO4011 is
# the GA-11 safety note, which the spec left to "the A1 registry" to
# number — recorded here so this transcription states the whole block.
GA_CATALOG = (
    ("RHO4001", "ground-kind-conflict", "error",
     ("net_a", "kind_a", "net_b", "kind_b"), "GA-2"),
    ("RHO4002", "ground-loop", "error", ("cycle",), "GA-6"),
    ("RHO4003", "earth-as-reference", "error",
     ("net", "referencing_entity"), "GA-10"),
    ("RHO4004", "undeclared-chassis-bridge", "error",
     ("component", "net_a", "net_b", "boundary"), "GA-12"),
    ("RHO4005", "isolation-spanning-component", "error",
     ("component", "domain_a", "domain_b", "barrier_component"), "GA-14"),
    ("RHO4006", "isolation-spanning-interface", "error",
     ("interface_type", "endpoint_a", "endpoint_b", "domain_a", "domain_b"),
     "GA-14"),
    ("RHO4007", "disjoint-ground-domains", "warning",
     ("domain_ids",), "GA-15"),
    ("RHO4008", "isolation-defeating-bond", "error",
     ("tie", "barrier_component"), "GA-14b"),
    ("RHO4009", "redundant-net-tie", "warning", ("tie", "net"), "GA-9"),
    ("RHO4010", "undeclared-ground-domain-crossing", "error",
     ("entity", "domain_a", "domain_b"), "GA-14c"),
    ("RHO4011", "safety-relevant-bond", "note",
     ("bond", "boundary"), "GA-11"),
)


def transcription_problems(registry, catalog=GA_CATALOG):
    """The registry's GA block equals the spec's catalog, exactly.

    Set equality on codes first (a missing or extra code is its own
    finding), then field equality per code — slug, severity, params IN
    ORDER (the spec's table states them in order), and the GA rule id."""
    problems = []
    in_registry = {e.code: e for e in registry if e.code.startswith("RHO4")}
    expected = {row[0]: row for row in catalog}
    for code in sorted(set(expected) - set(in_registry)):
        problems.append(
            f"{code}: in the GA spec catalog but not in the registry; the "
            "reserved block must land whole or the spec's 'final numbers "
            "are assigned when the A1 registry lands' clause never closes"
        )
    for code in sorted(set(in_registry) - set(expected)):
        problems.append(
            f"{code}: in the registry's GA block but not in the spec "
            "catalog; block 4 is the GA spec's to define"
        )
    for code in sorted(set(expected) & set(in_registry)):
        _, slug, severity, params, rule = expected[code]
        entry = in_registry[code]
        for field, want, got in (
            ("slug", slug, entry.slug),
            ("severity", severity, entry.severity),
            ("params", params, entry.params),
            ("rule", rule, entry.rule),
        ):
            if want != got:
                problems.append(
                    f"{code}: {field} is {got!r} but the GA spec's "
                    f"catalog says {want!r}; the spec's slugs and "
                    "structured-parameter shapes are stable from that "
                    "document forward"
                )
        if not entry.reserved:
            problems.append(
                f"{code}: not marked reserved, but no checker emits GA "
                "diagnostics yet; unreserving a code is the checker "
                "issue's move, made when the emitter lands"
            )
    return problems


def schema_sync_problems(schema, blocks=None, severities=None,
                         applicability=None, discriminator=None):
    """Every vocabulary the wire schema restates equals its constant."""
    blocks = codes_module.BLOCKS if blocks is None else blocks
    severities = codes_module.SEVERITIES if severities is None else severities
    applicability = (diag_module.APPLICABILITY if applicability is None
                     else applicability)
    discriminator = (diag_module.SCHEMA if discriminator is None
                     else discriminator)
    problems = []
    props = schema.get("properties", {})

    got = props.get("severity", {}).get("enum")
    if got != list(severities):
        problems.append(
            f"schema severity enum {got} != SEVERITIES {list(severities)}"
        )
    want_categories = [blocks[digit][0] for digit in sorted(blocks)]
    got = props.get("category", {}).get("enum")
    if got != want_categories:
        problems.append(
            f"schema category enum {got} != BLOCKS categories "
            f"{want_categories}"
        )
    got = (schema.get("$defs", {}).get("FixIt", {}).get("properties", {})
           .get("applicability", {}).get("enum"))
    if got != list(applicability):
        problems.append(
            f"schema applicability enum {got} != APPLICABILITY "
            f"{list(applicability)}"
        )
    got = props.get("schema", {}).get("const")
    if got != discriminator:
        problems.append(
            f"schema discriminator const {got!r} != diagnostics.SCHEMA "
            f"{discriminator!r}"
        )
    described = schema.get("properties", {}).get("code", {}).get(
        "description", "")
    for digit in sorted(blocks):
        label = f"{digit} {blocks[digit][0]}"
        if label not in described:
            problems.append(
                f"schema code description does not state block "
                f"'{label}'; the block table is restated there and "
                "restatements drift"
            )
    return problems


def emission_probe_problems():
    """The framework still refuses what the registry forbids.

    Three one-line probes, because a gate that only reads tables would
    pass with the enforcement deleted: an undeclared code, a param-set
    mismatch, and a wrong-applicability fix-it must all still raise."""
    problems = []
    span = diag_module.Span("probe.rhoform", 0, 1, 1, 1, 1, 2)
    try:
        diag_module.Diagnostic.new("RHO9998", {}, primary=span)
        problems.append(
            "an undeclared code was accepted at emission; the registry "
            "is decoration if construction does not consult it"
        )
    except KeyError:
        pass
    try:
        diag_module.Diagnostic.new("RHO1010", {"literal": "x"}, primary=span)
        problems.append(
            "a params set missing a declared member was accepted; "
            "structured params are the contract"
        )
    except ValueError:
        pass
    try:
        diag_module.FixIt("m", "has-placeholders",
                          (diag_module.Edit(span, "no markers"),))
        problems.append(
            "has-placeholders with no declared placeholder was accepted"
        )
    except ValueError:
        pass
    return problems


def main() -> int:
    if not SCHEMA_PATH.is_file():
        print(
            "registry: FAIL: rhoform/diagnostic.schema.json is missing; "
            "the wire schema is part of the A1 contract.",
            file=sys.stderr,
        )
        return 1
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    problems = []
    problems += codes_module.registry_problems()
    problems += transcription_problems(codes_module.REGISTRY)
    problems += schema_sync_problems(schema)
    problems += emission_probe_problems()

    if problems:
        for problem in problems:
            print(f"registry: FAIL: {problem}", file=sys.stderr)
        print(f"registry: {len(problems)} failure(s).", file=sys.stderr)
        return 1

    active = sum(1 for e in codes_module.REGISTRY if not e.reserved)
    reserved = sum(1 for e in codes_module.REGISTRY if e.reserved)
    print(
        f"registry: PASS: {active + reserved} stable code(s) "
        f"({active} active, {reserved} reserved), "
        f"{len(codes_module.RETIRED)} retired, GA catalog transcription "
        "matched, wire schema vocabularies in sync, emission refusals "
        "probed."
    )
    return 0


def self_test() -> int:
    """Prove every leg can fail, by planting the defect it exists for."""
    import contextlib
    import copy
    import io

    cases = []
    registry = codes_module.REGISTRY
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def entry(code):
        return next(e for e in registry if e.code == code)

    def replaced(code, **changes):
        out = []
        for item in registry:
            if item.code == code:
                fields = {f: getattr(item, f) for f in
                          ("code", "slug", "severity", "message",
                           "params", "rule", "reserved")}
                fields.update(changes)
                item = codes_module.CodeDef(**fields)
            out.append(item)
        return tuple(out)

    problems = transcription_problems(registry)
    cases.append(("the shipped registry matches the GA transcription",
                  problems == []))

    without = tuple(e for e in registry if e.code != "RHO4002")
    cases.append(("a missing GA code is caught", any(
        "RHO4002" in p and "not in the registry" in p
        for p in transcription_problems(without))))

    extra = registry + (codes_module.CodeDef(
        "RHO4099", "invented", "error", "m"),)
    cases.append(("an invented GA-block code is caught", any(
        "RHO4099" in p and "not in the spec catalog" in p
        for p in transcription_problems(extra))))

    renamed = replaced("RHO4001", slug="ground-conflict")
    cases.append(("a drifted GA slug is caught", any(
        "slug" in p and "stable from that document" in p
        for p in transcription_problems(renamed))))

    reordered = replaced(
        "RHO4001", params=("kind_a", "net_a", "net_b", "kind_b"))
    cases.append(("a reordered GA param shape is caught", any(
        "params" in p for p in transcription_problems(reordered))))

    unreserved = replaced("RHO4001", reserved=False)
    cases.append(("an unreserved GA code with no emitter is caught", any(
        "not marked reserved" in p
        for p in transcription_problems(unreserved))))

    cases.append(("the shipped schema is in sync",
                  schema_sync_problems(schema) == []))

    broken = copy.deepcopy(schema)
    broken["properties"]["severity"]["enum"] = ["error", "warning"]
    cases.append(("a shrunken severity enum is caught", any(
        "severity enum" in p for p in schema_sync_problems(broken))))

    broken = copy.deepcopy(schema)
    broken["properties"]["category"]["enum"][0] = "meta"
    cases.append(("a renamed category is caught", any(
        "category enum" in p for p in schema_sync_problems(broken))))

    broken = copy.deepcopy(schema)
    broken["$defs"]["FixIt"]["properties"]["applicability"]["enum"] = [
        "machine-applicable"]
    cases.append(("a shrunken applicability enum is caught", any(
        "applicability enum" in p for p in schema_sync_problems(broken))))

    broken = copy.deepcopy(schema)
    broken["properties"]["schema"]["const"] = "rhoform-diagnostic/9"
    cases.append(("a drifted discriminator is caught", any(
        "discriminator" in p for p in schema_sync_problems(broken))))

    broken = copy.deepcopy(schema)
    broken["properties"]["code"]["description"] = "a code"
    cases.append(("a block table dropped from the prose is caught", any(
        "does not state block" in p for p in schema_sync_problems(broken))))

    cases.append(("the emission probes pass on the real framework",
                  emission_probe_problems() == []))

    # The probes' own report sites: each fires only when the framework
    # STOPS refusing, so a stub framework is planted to prove the reports
    # are wired — otherwise all three appends are deletable and the probe
    # leg degrades to three try-blocks that check nothing.
    class _AcceptsAnything:
        @staticmethod
        def new(*args, **kwargs):
            return None

    def _lenient_fixit(*args, **kwargs):
        return None

    real_diag, real_fixit = diag_module.Diagnostic, diag_module.FixIt
    diag_module.Diagnostic = _AcceptsAnything
    diag_module.FixIt = _lenient_fixit
    try:
        stubbed = emission_probe_problems()
    finally:
        diag_module.Diagnostic, diag_module.FixIt = real_diag, real_fixit
    cases.append(("a framework that stops refusing undeclared codes is "
                  "reported", any("undeclared code was accepted" in p
                                  for p in stubbed)))
    cases.append(("a framework that stops refusing param mismatches is "
                  "reported", any("missing a declared member" in p
                                  for p in stubbed)))
    cases.append(("a framework that stops refusing placeholder abuse is "
                  "reported", any("no declared placeholder" in p
                                  for p in stubbed)))

    # WIRING: registry_problems feeds main(). Plant a duplicate through
    # the module global and main() must go red — the same shape as
    # validate-schemas' floor-wiring case.
    codes_module.REGISTRY = registry + (entry("RHO1001"),)
    try:
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            wired = main()
    finally:
        codes_module.REGISTRY = registry
    cases.append(("registry problems are WIRED into main()",
                  wired == 1 and "already used" in err.getvalue()))

    with contextlib.redirect_stdout(io.StringIO()) as out:
        clean = main()
    cases.append(("the real tree passes end to end",
                  clean == 0 and "registry: PASS:" in out.getvalue()))

    failures = 0
    for name, ok in cases:
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if failures:
        print(f"registry: SELF-TEST FAILED: {failures} case(s)",
              file=sys.stderr)
        return 1
    print(f"registry: self-test PASS: {len(cases)} cases.")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        sys.exit(self_test())
    sys.exit(main())
