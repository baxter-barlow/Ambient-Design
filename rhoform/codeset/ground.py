"""The ground-architecture block (GA-1..GA-17): L2c (AMB-54) activated
RHO4001-4005 and RHO4007-4011 with GA passes 1-4 (rhoform/check/ground.py
emits them), L3 activates RHO4006, which needs interfaces, and the GA
follow-ons (the uncoded section 1.4 passive-between-kinds warning) take
numbers after the catalog.

Its ranges: RHO4001-RHO4011, the catalog, and RHO4012-RHO4099, its
follow-ons (rhoform.codes.RANGES). The registry gate pins the catalog's
transcription; rhoform/tests/test_diagnostics.py reads which of it is
still reserved from here, so activating a code is an edit to this file
alone.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = (
    # The GA spec published these as "placeholders in a reserved block;
    # final numbers are assigned when the A1 registry lands". This is that
    # registry landing: the numbers below are now FINAL and equal to the
    # placeholders, so every existing citation (corpus classifications,
    # spec prose) stays true. Slugs and param shapes are verbatim from the
    # §6 table; the registry gate pins them.
    CodeDef(
        code="RHO4001", slug="ground-kind-conflict", severity="error",
        message=(
            "ground kinds conflict: `{net_a}` is {kind_a}, `{net_b}` is "
            "{kind_b}."
        ),
        params=("net_a", "kind_a", "net_b", "kind_b"),
        rule="GA-2",
    ),
    CodeDef(
        code="RHO4002", slug="ground-loop", severity="error",
        message="ground loop: the tie graph must be acyclic; cycle: {cycle}.",
        params=("cycle",),
        rule="GA-6",
    ),
    CodeDef(
        code="RHO4003", slug="earth-as-reference", severity="error",
        message=(
            "`{net}` has kind earth and cannot be a reference or return "
            "path; referenced by {referencing_entity}."
        ),
        params=("net", "referencing_entity"),
        rule="GA-10",
    ),
    CodeDef(
        code="RHO4004", slug="undeclared-chassis-bridge", severity="error",
        message=(
            "`{component}` bridges `{net_a}` and `{net_b}` across a "
            "{boundary} boundary and is not a declared SafetyCapacitor."
        ),
        params=("component", "net_a", "net_b", "boundary"),
        rule="GA-12",
    ),
    CodeDef(
        code="RHO4005", slug="isolation-spanning-component", severity="error",
        message=(
            "`{component}` spans the isolation barrier of "
            "`{barrier_component}` (isolation domains: {domain_a}, "
            "{domain_b})."
        ),
        params=("component", "domain_a", "domain_b", "barrier_component"),
        rule="GA-14",
    ),
    CodeDef(
        code="RHO4006", slug="isolation-spanning-interface", severity="error",
        message=(
            "connecting {interface_type} from {endpoint_a} to {endpoint_b} "
            "crosses isolation domains {domain_a} and {domain_b} without a "
            "declared isolator."
        ),
        params=("interface_type", "endpoint_a", "endpoint_b", "domain_a",
                "domain_b"),
        rule="GA-14", reserved=True,
    ),
    CodeDef(
        code="RHO4007", slug="disjoint-ground-domains", severity="warning",
        message=(
            "isolation domains {domain_ids} are related by no declared "
            "isolation component; usually a forgotten connection."
        ),
        params=("domain_ids",),
        rule="GA-15",
    ),
    CodeDef(
        code="RHO4008", slug="isolation-defeating-bond", severity="error",
        message=(
            "net-tie `{tie}` crosses the declared isolation barrier of "
            "`{barrier_component}`, defeating the isolation."
        ),
        params=("tie", "barrier_component"),
        rule="GA-14b",
    ),
    CodeDef(
        code="RHO4009", slug="redundant-net-tie", severity="warning",
        message="both ports of `{tie}` are on `{net}`; the tie is redundant.",
        params=("tie", "net"),
        rule="GA-9",
    ),
    CodeDef(
        code="RHO4010", slug="undeclared-ground-domain-crossing",
        severity="error",
        message=(
            "`{entity}` straddles unrelated ground domains {domain_a} and "
            "{domain_b}; no voltage comparison across it exists."
        ),
        params=("entity", "domain_a", "domain_b"),
        rule="GA-14c",
    ),
    # GA-11's safety note had a category and no number in the GA spec —
    # "the diagnostic stream MUST tag the bond with a `safety` category
    # note" — and assigning it is exactly the job §6 delegates to this
    # registry. It stays in the GA block because GA-11 owns it.
    CodeDef(
        code="RHO4011", slug="safety-relevant-bond", severity="note",
        message=(
            "`{bond}` bonds across a {boundary} boundary; safety-relevant, "
            "surfaced in the report's safety section (GA-11)."
        ),
        params=("bond", "boundary"),
        rule="GA-11",
    ),
)
