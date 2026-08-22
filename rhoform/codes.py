"""The diagnostic code registry: stable unique codes from the first commit.

A1 requires codes that are STABLE — a code, once published, means one thing
forever. This module is the single place a code may be declared, and the
registry gate (tests/diagnostics/check-registry.py) holds the declarations to
the rules below, so stability is enforced rather than promised:

  - a code is `RHO` + four digits; the first digit names its block in BLOCKS,
    and a code in an unassigned block is an error;
  - codes and slugs are unique across active AND retired entries — a retired
    code keeps its number and slug forever and can never be reassigned,
    because a reader of an old transcript must never find its meaning changed;
  - every `{param}` placeholder in a message template must name a declared
    parameter, and every declared parameter must appear in the template —
    params are the machine-readable contract (A1: "structured parameter
    fields separate from message strings"), and a parameter the message never
    renders is a parameter no human review ever sees drift;
  - the ground-architecture block RHO40xx is transcribed from the GA spec's
    §6 catalog, whose slugs and structured-parameter shapes are stable from
    that document forward; the registry gate pins the transcription.

WHY FOUR EXISTING NAMESPACES ARE NOT HERE. `RHOX*`/`RHOA*`/`RHOB*`/`RHOS*`
are the bake-off prototypes' per-arm codes (lang/bakeoff/diagnostics.py) and
retire with the prototypes; `RHO0201`/`RHO0410` appear only inside a
synthetic eval fixture (eval/examples/negative/e02...) that demonstrates a
harness defect, not a language diagnostic. Neither is a published contract.
This registry is where the product's codes start.

Severity is fixed per code: `error` gates, `warning` annotates, `note`
carries non-gating context (the GA spec's safety notes, the framework's own
truncation marker). T6 waivers, when they land (AMB-56), downgrade at the
reporting layer without touching the registry.
"""

from dataclasses import dataclass, field
import re

CODE_RE = re.compile(r"^RHO[0-9]{4}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")

SEVERITIES = ("error", "warning", "note")

# Block table: leading digit -> (category, owner). A code whose first digit
# is not a key here does not exist yet as a concept; assigning a new block is
# a registry change with review, not a formatting accident. Blocks 2 and 3
# are named now so the elaborator (AMB-44) and the static type system (M2)
# cannot end up scattered across whatever digits were free on the day.
BLOCKS = {
    0: ("framework", "the diagnostics framework itself (R17)"),
    1: ("syntax", "lexer/parser and file-local checks (R12, A2)"),
    2: ("elaboration", "elaborator: instantiation, names, parameters (R13)"),
    3: ("types", "static type system: interfaces, roles, quantities, "
        "domains, budgets (M2)"),
    4: ("ground-architecture", "T5 ground rules GA-1..GA-17 (AMB-37 spec)"),
    5: ("verification", "dynamic assertion tier and simulation (M5)"),
    6: ("parts", "part resolution and the D1 binding ladder (M3)"),
    7: ("interop", "exports, artifact guard, KiCad boundary (M3)"),
}


@dataclass(frozen=True)
class CodeDef:
    """One diagnostic code. `reserved=True` means the shape is published but
    no pass emits it yet — the GA catalog's state until its checker lands."""

    code: str
    slug: str
    severity: str
    message: str
    params: tuple[str, ...] = ()
    rule: str | None = None  # traceability: a GA-* / requirement id
    reserved: bool = False

    @property
    def category(self) -> str:
        return BLOCKS[int(self.code[3])][0]

    def render(self, values: dict) -> str:
        """The human message, from the template and structured params.

        Values render deterministically: strings verbatim, everything else
        as key-sorted compact JSON, so a list-valued param (RHO4002's cycle)
        cannot render differently between two runs over the same input.
        """
        import json

        def show(value):
            return value if isinstance(value, str) else json.dumps(
                value, sort_keys=True, separators=(",", ":"))

        return self.message.format(**{k: show(v) for k, v in values.items()})


REGISTRY: tuple[CodeDef, ...] = (
    # ---- block 0: the framework itself -----------------------------------
    CodeDef(
        code="RHO0001",
        slug="diagnostics-truncated",
        severity="note",
        message=(
            "diagnostic output capped: showing {shown} of {total}; "
            "{suppressed} suppressed ({suppressed_errors} error(s), "
            "{suppressed_warnings} warning(s), {suppressed_notes} note(s))."
        ),
        params=("shown", "total", "suppressed", "suppressed_errors",
                "suppressed_warnings", "suppressed_notes"),
        rule="A1",
    ),
    # ---- block 1: lexical and syntactic ----------------------------------
    CodeDef(
        code="RHO1001",
        slug="tab-in-source",
        severity="error",
        message="tab character; indentation and spacing are spaces only (L5).",
        rule="L5",
    ),
    CodeDef(
        code="RHO1002",
        slug="non-ascii-character",
        severity="error",
        message=(
            "non-ASCII character {codepoint}; the surface syntax is "
            "ASCII only (L5)."
        ),
        params=("codepoint",),
        rule="L5",
    ),
    CodeDef(
        code="RHO1003",
        slug="carriage-return",
        severity="error",
        message=(
            "carriage return; Rhoform sources use LF line endings only, so "
            "two files differing by CRLF cannot be the same program."
        ),
        rule="L5",
    ),
    CodeDef(
        code="RHO1004",
        slug="unterminated-string",
        severity="error",
        message="unterminated string literal; a string ends on its own line.",
        rule="L5",
    ),
    CodeDef(
        code="RHO1005",
        slug="missing-or-wrong-pragma",
        severity="error",
        message=(
            "expected the syntax-version pragma `{expected}` as the first "
            "statement; found {found}."
        ),
        params=("expected", "found"),
        rule="L8",
    ),
    CodeDef(
        code="RHO1006",
        slug="unexpected-token",
        severity="error",
        message="unexpected {found}; expected {expected}.",
        params=("found", "expected"),
        rule="L5",
    ),
    CodeDef(
        code="RHO1007",
        slug="unexpected-end-of-file",
        severity="error",
        message="unexpected end of file; expected {expected}.",
        params=("expected",),
        rule="L5",
    ),
    CodeDef(
        code="RHO1008",
        slug="inconsistent-indentation",
        severity="error",
        message=(
            "this line dedents to column {column}, which matches no "
            "enclosing block."
        ),
        params=("column",),
        rule="L5",
    ),
    CodeDef(
        code="RHO1009",
        slug="not-in-closed-vocabulary",
        severity="error",
        message=(
            "`{word}` is not a {vocabulary}; the closed vocabulary is "
            "checked after parsing (see CLOSED_VOCABULARIES)."
        ),
        params=("vocabulary", "word"),
        rule="T2/L9/V2/T5",
    ),
    CodeDef(
        code="RHO1010",
        slug="invalid-quantity-literal",
        severity="error",
        message="`{literal}` is not a valid quantity: {reason}",
        params=("literal", "reason"),
        rule="T3",
    ),
    CodeDef(
        code="RHO1011",
        slug="unexpected-character",
        severity="error",
        message="unexpected character {character}; no token can start here.",
        params=("character",),
        rule="L5",
    ),
    # ---- block 4: ground architecture, transcribed from the GA spec §6 ---
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
        rule="GA-2", reserved=True,
    ),
    CodeDef(
        code="RHO4002", slug="ground-loop", severity="error",
        message="ground loop: the tie graph must be acyclic; cycle: {cycle}.",
        params=("cycle",),
        rule="GA-6", reserved=True,
    ),
    CodeDef(
        code="RHO4003", slug="earth-as-reference", severity="error",
        message=(
            "`{net}` has kind earth and cannot be a reference or return "
            "path; referenced by {referencing_entity}."
        ),
        params=("net", "referencing_entity"),
        rule="GA-10", reserved=True,
    ),
    CodeDef(
        code="RHO4004", slug="undeclared-chassis-bridge", severity="error",
        message=(
            "`{component}` bridges `{net_a}` and `{net_b}` across a "
            "{boundary} boundary and is not a declared SafetyCapacitor."
        ),
        params=("component", "net_a", "net_b", "boundary"),
        rule="GA-12", reserved=True,
    ),
    CodeDef(
        code="RHO4005", slug="isolation-spanning-component", severity="error",
        message=(
            "`{component}` spans the isolation barrier of "
            "`{barrier_component}` (isolation domains: {domain_a}, "
            "{domain_b})."
        ),
        params=("component", "domain_a", "domain_b", "barrier_component"),
        rule="GA-14", reserved=True,
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
        rule="GA-15", reserved=True,
    ),
    CodeDef(
        code="RHO4008", slug="isolation-defeating-bond", severity="error",
        message=(
            "net-tie `{tie}` crosses the declared isolation barrier of "
            "`{barrier_component}`, defeating the isolation."
        ),
        params=("tie", "barrier_component"),
        rule="GA-14b", reserved=True,
    ),
    CodeDef(
        code="RHO4009", slug="redundant-net-tie", severity="warning",
        message="both ports of `{tie}` are on `{net}`; the tie is redundant.",
        params=("tie", "net"),
        rule="GA-9", reserved=True,
    ),
    CodeDef(
        code="RHO4010", slug="undeclared-ground-domain-crossing",
        severity="error",
        message=(
            "`{entity}` straddles unrelated ground domains {domain_a} and "
            "{domain_b}; no voltage comparison across it exists."
        ),
        params=("entity", "domain_a", "domain_b"),
        rule="GA-14c", reserved=True,
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
        rule="GA-11", reserved=True,
    ),
)

# A code, once retired, keeps its number and slug here forever. Empty today,
# and the structure exists from the first commit so the first retirement is
# an append rather than an invention. Entries: (code, slug, reason).
RETIRED: tuple[tuple[str, str, str], ...] = ()

_BY_CODE = {entry.code: entry for entry in REGISTRY}


def lookup(code: str) -> CodeDef:
    try:
        return _BY_CODE[code]
    except KeyError:
        raise KeyError(
            f"{code!r} is not a registered diagnostic code; every code must "
            "be declared in rhoform/codes.py before anything emits it."
        ) from None


def registry_problems() -> list[str]:
    """Every structural violation of the registry's own rules.

    Lives here rather than in the gate so `import rhoform.codes` in any tool
    can assert a sane registry cheaply; the gate adds the self-test and the
    GA transcription pin on top.
    """
    problems: list[str] = []
    seen_codes: dict[str, str] = {}
    seen_slugs: dict[str, str] = {}

    for code, slug, _reason in RETIRED:
        seen_codes[code] = f"retired code {code}"
        seen_slugs[slug] = f"retired slug {slug!r}"

    for entry in REGISTRY:
        where = f"{entry.code} ({entry.slug})"
        if not CODE_RE.match(entry.code):
            problems.append(f"{where}: code does not match RHO + four digits")
            continue
        if int(entry.code[3]) not in BLOCKS:
            problems.append(
                f"{where}: block {entry.code[3]}xxx is not assigned in BLOCKS"
            )
        if not SLUG_RE.match(entry.slug):
            problems.append(f"{where}: slug is not kebab-case")
        if entry.severity not in SEVERITIES:
            problems.append(f"{where}: severity {entry.severity!r} unknown")
        if entry.code in seen_codes:
            problems.append(
                f"{where}: code already used by {seen_codes[entry.code]}"
            )
        if entry.slug in seen_slugs:
            problems.append(
                f"{where}: slug already used by {seen_slugs[entry.slug]}"
            )
        seen_codes[entry.code] = where
        seen_slugs[entry.slug] = where

        placeholders = set(PLACEHOLDER_RE.findall(entry.message))
        declared = set(entry.params)
        if len(entry.params) != len(declared):
            problems.append(f"{where}: duplicate declared parameter")
        # Both directions. A placeholder with no declared param renders a
        # KeyError at emission; a declared param no template renders is a
        # field that can drift without any human ever reading it.
        for name in sorted(placeholders - declared):
            problems.append(
                f"{where}: message names {{{name}}} but does not declare it"
            )
        for name in sorted(declared - placeholders):
            problems.append(
                f"{where}: declares param {name!r} the message never renders"
            )

    ordered = [entry.code for entry in REGISTRY]
    if ordered != sorted(ordered):
        problems.append(
            "REGISTRY is not in code order; a sorted registry is what makes "
            "'the next free number in the block' a fact a reader can see"
        )
    return problems
