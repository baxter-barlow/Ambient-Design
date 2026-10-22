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

from dataclasses import dataclass
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
        # L3 since syntax 0.2: param_type and loop_iterator.
        rule="T2/L9/V2/T5/L3",
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
    CodeDef(
        code="RHO1012",
        slug="toleranced-quantity-in-plain-position",
        severity="error",
        message=(
            "`{literal}` carries a tolerance or interval, but this "
            "position takes a plain quantity."
        ),
        params=("literal",),
        rule="T3/T4",
    ),
    CodeDef(
        code="RHO1013",
        slug="midline-pragma",
        severity="error",
        message=(
            "`#pragma` may only begin a line; mid-line pragma text is "
            "neither a comment nor a header (a frozen v0.1 decision)."
        ),
        rule="L8",
    ),
    CodeDef(
        code="RHO1014",
        slug="control-character",
        severity="error",
        message=(
            "control character {codepoint}; sources are printable ASCII "
            "plus LF."
        ),
        params=("codepoint",),
        rule="L5",
    ),
    CodeDef(
        code="RHO1015",
        slug="unclosed-bracket",
        severity="error",
        message=(
            "`{bracket}` opened here is never closed; everything after "
            "it joins one logical line until it is."
        ),
        params=("bracket",),
        rule="L5",
    ),
    # One per file, however many constructs: the defect is the header, and
    # so is the repair (decision S-2). `count` keeps the first construct
    # from reading as the only one.
    CodeDef(
        code="RHO1016",
        slug="syntax-needs-newer-pragma",
        severity="error",
        message=(
            "{construct} needs syntax {required}, but the pragma declares "
            "{declared} ({count} construct(s) in this file need "
            "{required})."
        ),
        params=("construct", "required", "declared", "count"),
        rule="L8",
    ),
    CodeDef(
        code="RHO1017",
        slug="not-canonical",
        severity="error",
        message=(
            "not in canonical form from this line on; `rhoform fmt` "
            "rewrites the file to its one canonical spelling (I1)."
        ),
        rule="I1",
    ),
    # ---- block 2: elaboration (rhoform/elaborate.py, AMB-44/R13) --------
    # Every error the elaborator can raise on a parse-clean v0.1 file. The
    # ones guarding IR shape (RHO2013-2017, RHO2030, RHO2032) exist because
    # emitting the IR anyway would hand a backend a schema-invalid document.
    CodeDef(
        code="RHO2001", slug="duplicate-module", severity="error",
        message=(
            "module `{name}` is defined twice in this file; a definition "
            "name must identify one module."
        ),
        params=("name",),
        rule="L7",
    ),
    CodeDef(
        code="RHO2002", slug="ambiguous-root-module", severity="error",
        message=(
            "modules {candidates} are each instantiated by nothing, so the "
            "root is ambiguous; instantiate all but one, or name the root "
            "explicitly."
        ),
        params=("candidates",),
        rule="L1",
    ),
    CodeDef(
        code="RHO2003", slug="unknown-root-module", severity="error",
        message=(
            "the requested root `{name}` is not a module of this file; its "
            "modules are {candidates}."
        ),
        params=("name", "candidates"),
        rule="L1",
    ),
    CodeDef(
        code="RHO2004", slug="instantiation-cycle", severity="error",
        message=(
            "modules {cycle} instantiate one another in a cycle; elaboration "
            "must terminate, so no module may contain itself."
        ),
        params=("cycle",),
        rule="L1/L3",
    ),
    CodeDef(
        code="RHO2005", slug="unknown-definition", severity="error",
        message=(
            "`{name}` names no definition visible in this file; a "
            "single-word definition must be a module or component defined "
            "here (a dotted name is a library component)."
        ),
        params=("name",),
        rule="L2",
    ),
    CodeDef(
        code="RHO2006", slug="table-of-modules", severity="error",
        message=(
            "`{name}` is a module, and table rows elaborate to components; "
            "instantiate the module with `new` once per instance instead."
        ),
        params=("name",),
        rule="L6",
    ),
    CodeDef(
        code="RHO2007", slug="duplicate-declaration", severity="error",
        message="{kind} `{name}` appears twice in {scope}.",
        params=("kind", "name", "scope"),
        rule="L7",
    ),
    CodeDef(
        code="RHO2008", slug="assertion-path-collision", severity="error",
        message=(
            "assertion `{name}` and an instance of the same name in module "
            "`{module}` would share one path identity."
        ),
        params=("name", "module"),
        rule="L7",
    ),
    CodeDef(
        code="RHO2009", slug="fact-on-module-instance", severity="error",
        message=(
            "`{fact}` cannot appear on `{instance}`, an instance of module "
            "`{module}`: a module's ports and parts come from its "
            "definition, and it carries no defaults to deny."
        ),
        params=("fact", "instance", "module"),
        rule="L2/L9",
    ),
    CodeDef(
        code="RHO2010", slug="repeated-instance-fact", severity="error",
        message=(
            "`{instance}` states `{fact}` more than once; an instance has "
            "one {fact}."
        ),
        params=("fact", "instance"),
        rule="L9/D1",
    ),
    CodeDef(
        code="RHO2011", slug="repeated-flag", severity="warning",
        message="`{instance}` states the flag `{flag}` more than once.",
        params=("flag", "instance"),
        rule="L9",
    ),
    CodeDef(
        code="RHO2012", slug="contradictory-flag", severity="error",
        message="`{instance}` states both `{flag}` and `no {flag}`.",
        params=("flag", "instance"),
        rule="L9",
    ),
    CodeDef(
        code="RHO2013", slug="hardware-port-arity", severity="error",
        message=(
            "`{instance}` is hardware `{kind}`, which takes {requirement}; "
            "it declares {found}."
        ),
        params=("instance", "kind", "requirement", "found"),
        rule="L9",
    ),
    CodeDef(
        code="RHO2014", slug="abstract-part-without-constraints",
        severity="error",
        message=(
            "`{instance}` has `part abstract` with no constraints; an "
            "abstract part is the constraint set it must satisfy."
        ),
        params=("instance",),
        rule="D1",
    ),
    CodeDef(
        code="RHO2015", slug="empty-part-key", severity="error",
        message=(
            "`{instance}` pins its part to the empty key; a resolved part "
            "names a lockfile entry."
        ),
        params=("instance",),
        rule="D1",
    ),
    CodeDef(
        code="RHO2016", slug="interval-without-nominal", severity="error",
        message=(
            "`{literal}` for `{name}` is a bare interval with no nominal; a "
            "parameter or constraint needs a value, e.g. `3.3V (3V to "
            "3.6V)`."
        ),
        params=("literal", "name"),
        rule="T4/I4",
    ),
    CodeDef(
        code="RHO2017", slug="number-not-representable", severity="error",
        message=(
            "`{literal}` cannot be carried by the IR, whose numbers are "
            "IEEE doubles: an integer must not exceed 2^53 in magnitude and "
            "a quantity must be finite."
        ),
        params=("literal",),
        rule="I4",
    ),
    CodeDef(
        code="RHO2018", slug="table-row-arity", severity="error",
        message=(
            "row `{row}` carries {values} value(s), but the table header "
            "declares {columns} column(s)."
        ),
        params=("row", "values", "columns"),
        rule="L6",
    ),
    CodeDef(
        code="RHO2019", slug="invalid-table-column", severity="error",
        message=(
            "column `{column}` is neither a parameter name nor "
            "`part.<constraint>`."
        ),
        params=("column",),
        rule="L6",
    ),
    CodeDef(
        code="RHO2020", slug="part-column-without-binding", severity="error",
        message=(
            "column `{column}` sets a part constraint, but the table header "
            "declares no `part` binding to carry it."
        ),
        params=("column",),
        rule="L6/D1",
    ),
    CodeDef(
        code="RHO2021", slug="unknown-instance", severity="error",
        message="`{instance}` is not an instance of module `{module}`.",
        params=("instance", "module"),
        rule="L7",
    ),
    CodeDef(
        code="RHO2022", slug="unknown-port", severity="error",
        message=(
            "instance `{instance}` of `{definition}` has no port `{port}`; "
            "a component's ports are its `pin` statements and a module's "
            "are its `port` declarations."
        ),
        params=("instance", "definition", "port"),
        rule="T2",
    ),
    CodeDef(
        code="RHO2023", slug="unknown-own-port", severity="error",
        message=(
            "`{name}` is not a port of module `{module}`; a bare endpoint "
            "names one of the module's own ports."
        ),
        params=("name", "module"),
        rule="T2",
    ),
    CodeDef(
        code="RHO2024", slug="nc-port-connected", severity="error",
        message=(
            "`{endpoint}` has role `nc`; a declared no-connect cannot join "
            "a net."
        ),
        params=("endpoint",),
        rule="T2",
    ),
    CodeDef(
        code="RHO2025", slug="repeated-endpoint", severity="warning",
        message="`{endpoint}` is listed more than once in one statement.",
        params=("endpoint",),
        rule="T2",
    ),
    CodeDef(
        code="RHO2026", slug="isolated-endpoint-connected", severity="error",
        message=(
            "`{endpoint}` is declared isolated but its net also reaches "
            "`{other}`; an isolated port is alone on its net."
        ),
        params=("endpoint", "other"),
        rule="L9",
    ),
    CodeDef(
        code="RHO2027", slug="conflicting-net-labels", severity="error",
        message=(
            "one net carries labels {labels} at the same depth; a net has "
            "one name, so connect differently or keep one label."
        ),
        params=("labels",),
        rule="I2",
    ),
    CodeDef(
        code="RHO2028", slug="conflicting-net-domain", severity="error",
        message=(
            "net `{net}` is given two {attribute} values, `{first}` and "
            "`{second}`."
        ),
        params=("net", "attribute", "first", "second"),
        rule="T5",
    ),
    CodeDef(
        code="RHO2029", slug="unknown-assertion-subject", severity="error",
        message=(
            "`{subject}` is not a net labelled in module `{module}`; an "
            "assertion's subject is a net label of its own module."
        ),
        params=("subject", "module"),
        rule="V1",
    ),
    CodeDef(
        code="RHO2030", slug="static-assertion-dynamic-measurement",
        severity="error",
        message=(
            "static assertion `{name}` measures `{measurement}`, which has "
            "no static evaluation rule; only operating_point, power_avg, "
            "power_rms and efficiency are static."
        ),
        params=("name", "measurement"),
        rule="V1/V2",
    ),
    CodeDef(
        code="RHO2031", slug="inverted-assertion-bounds", severity="error",
        message="`within {low} to {high}`: the lower bound exceeds the upper.",
        params=("low", "high"),
        rule="V1",
    ),
    CodeDef(
        code="RHO2032", slug="empty-net-domain", severity="error",
        message="net `{net}` sets `{attribute}` to the empty string.",
        params=("net", "attribute"),
        rule="T5",
    ),
    # INTERIM. Syntax 0.2 parses (RHO1016 guards it under a 0.1 pragma).
    # The elaborator gives every 0.2 construct but `import` its meaning; it
    # refuses imports with this code until the package layer resolves them
    # (wave 2b). The formatter formats every 0.2 construct, imports
    # included, and never emits it. `tool` names the stage that refused.
    CodeDef(
        code="RHO2033", slug="syntax-0-2-not-yet-supported",
        severity="error",
        message=(
            "{construct} is syntax 0.2: it parses, but the {tool} does not "
            "support it yet."
        ),
        params=("construct", "tool"),
    ),
    # ---- syntax 0.2 elaboration: components, parameters, if/for, arrays --
    # RHO2001 keeps its meaning (two modules); a clash involving a
    # component is this code, so neither message lies about the kinds.
    CodeDef(
        code="RHO2034", slug="duplicate-definition", severity="error",
        message=(
            "`{name}` is defined twice in this file, first as a {first} and "
            "then as a {second}; a definition name must identify one "
            "definition."
        ),
        params=("name", "first", "second"),
        rule="L7",
    ),
    CodeDef(
        code="RHO2035", slug="component-pin-mismatch", severity="error",
        message=(
            "pin `{pin}` of `{instance}` disagrees with component "
            "`{component}`: the instance has {found}, the definition has "
            "{expected}; pins stated on an instance must restate the "
            "definition exactly."
        ),
        params=("pin", "instance", "component", "found", "expected"),
        rule="L2/T2",
    ),
    CodeDef(
        code="RHO2036", slug="unknown-parameter", severity="error",
        message=(
            "`{name}` is not a parameter of `{definition}`, whose "
            "parameters are {parameters}."
        ),
        params=("name", "definition", "parameters"),
        rule="L3",
    ),
    CodeDef(
        code="RHO2037", slug="missing-argument", severity="error",
        message=(
            "`{instance}` gives no value for `{parameter}`, a parameter of "
            "`{definition}` with no default."
        ),
        params=("instance", "parameter", "definition"),
        rule="L3",
    ),
    CodeDef(
        code="RHO2038", slug="value-type-mismatch", severity="error",
        message="`{value}` is {found}, but {context} takes {expected}.",
        params=("value", "found", "context", "expected"),
        rule="L3/T3",
    ),
    CodeDef(
        code="RHO2039", slug="unknown-parameter-reference", severity="error",
        message=(
            "`{name}` is not a parameter of `{definition}` or a loop "
            "variable in scope here."
        ),
        params=("name", "definition"),
        rule="L3",
    ),
    CodeDef(
        code="RHO2040", slug="misplaced-statement", severity="error",
        message="{statement} cannot appear inside {construct}: {reason}.",
        params=("statement", "construct", "reason"),
        rule="L3",
    ),
    CodeDef(
        code="RHO2041", slug="shadowed-loop-variable", severity="error",
        message=(
            "loop variable `{name}` shadows {shadowed} of the same name; "
            "give the loop variable a name of its own."
        ),
        params=("name", "shadowed"),
        rule="L3",
    ),
    CodeDef(
        code="RHO2042", slug="invalid-array-size", severity="error",
        message=(
            "array `{array}` would have {size} member(s); an array has at "
            "least one."
        ),
        params=("array", "size"),
        rule="L3",
    ),
    CodeDef(
        code="RHO2043", slug="index-out-of-range", severity="error",
        message=(
            "`{endpoint}` selects member {index} of `{array}`, whose "
            "members are numbered 0 to {last}."
        ),
        params=("endpoint", "index", "array", "last"),
        rule="L3/L7",
    ),
    CodeDef(
        code="RHO2044", slug="array-needs-index", severity="error",
        message=(
            "`{array}` is an array of {size} instances; select one member, "
            "e.g. `{array}[0]`."
        ),
        params=("array", "size"),
        rule="L3/L7",
    ),
    CodeDef(
        code="RHO2045", slug="index-on-non-array", severity="error",
        message="`{instance}` is a single instance, not an array; it takes "
                "no index.",
        params=("instance",),
        rule="L3/L7",
    ),
    CodeDef(
        code="RHO2046", slug="expansion-limit", severity="error",
        message=(
            "{construct} takes the design past {limit} array members and "
            "loop iterations, counted over every instance; elaboration is "
            "capped so that it stays fast."
        ),
        params=("construct", "limit"),
        rule="L3",
    ),
    # Under 0.1 every file has a module, and a file whose every module is
    # instantiated has a cycle (RHO2004). A file of `component`s only has
    # neither, and elaboration must still say why there is no design.
    CodeDef(
        code="RHO2047", slug="no-root-module", severity="error",
        message=(
            "`{file}` defines no module, so it has no design to elaborate; "
            "the root of a design is a module."
        ),
        params=("file",),
        rule="L1",
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
