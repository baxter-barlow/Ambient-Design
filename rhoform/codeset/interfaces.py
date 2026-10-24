"""T1 nominal interfaces (L2a, AMB-51): the block-3 interface checks, and any
syntax or elaboration code interfaces need.

Its range: RHO1030-RHO1039, RHO2100-RHO2119 and RHO3001-RHO3099
(rhoform.codes.RANGES). A new code takes the next free number in the range,
and CODES stays in code order. Spec 05/03 says what fires each one. The
elaborator reports them all: interfaces are checked while the design is
built, since a bundle that does not resolve has no design to check.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = (
    CodeDef(
        code="RHO3001", slug="definition-kind-mismatch", severity="error",
        message=(
            "`{name}` is {found}, and {expected} is required here; an "
            "interface types a port or a member of another interface "
            "(`port p = new I`), and `new` instantiates a module or a "
            "component."
        ),
        params=("name", "found", "expected"),
        rule="T1",
    ),
    CodeDef(
        code="RHO3002", slug="interface-nesting-cycle", severity="error",
        message=(
            "interfaces {cycle} contain one another through their members; "
            "an interface's shape must be finite, so none may contain "
            "itself."
        ),
        params=("cycle",),
        rule="T1",
    ),
    CodeDef(
        code="RHO3003", slug="unknown-member", severity="error",
        message=(
            "`{path}` has no member `{member}`; its members are {members} "
            "(a pin, a port and a leaf member have none)."
        ),
        params=("path", "member", "members"),
        rule="T1",
    ),
    CodeDef(
        code="RHO3004", slug="interface-mismatch", severity="error",
        message=(
            "`{endpoint_b}` is a bundle of `{interface_b}` and `{endpoint_a}` "
            "one of `{interface_a}`; a bundle connects only to bundles of "
            "its own interface, whatever members two interfaces declare "
            "(interfaces are nominal)."
        ),
        params=("endpoint_a", "interface_a", "endpoint_b", "interface_b"),
        rule="T1",
    ),
    CodeDef(
        code="RHO3005", slug="bundle-shape-mismatch", severity="error",
        message=(
            "`{endpoint_b}` is {shape_b} and `{endpoint_a}` {shape_a}; "
            "bundles join member by member, so the bundles a chain joins "
            "have one shape."
        ),
        params=("endpoint_a", "shape_a", "endpoint_b", "shape_b"),
        rule="T1",
    ),
    CodeDef(
        code="RHO3006", slug="bundle-where-node-required", severity="error",
        message=(
            "`{endpoint}` is a whole bundle, but {statement} takes single "
            "nodes only; name one of its members, {members}, or join it in a "
            "chain of bundles alone."
        ),
        params=("endpoint", "statement", "members"),
        rule="T1",
    ),
    CodeDef(
        code="RHO3007", slug="unbound-view-member", severity="error",
        message=(
            "view `{view}` of `{component}` binds no pin to {members}; a "
            "view is an interface over pins the component has, so every "
            "leaf member is bound."
        ),
        params=("view", "component", "members"),
        rule="T1",
    ),
    CodeDef(
        code="RHO3008", slug="view-binds-unknown-pin", severity="error",
        message=(
            "view `{view}` binds `{member}` to `{pin}`, which is not a pin "
            "of `{component}`."
        ),
        params=("view", "member", "pin", "component"),
        rule="T1",
    ),
    CodeDef(
        code="RHO3009", slug="view-binds-nc-pin", severity="error",
        message=(
            "view `{view}` binds `{member}` to `{pin}`, whose role is `nc`; "
            "a declared no-connect joins nothing, so it is no member of a "
            "bundle."
        ),
        params=("view", "member", "pin"),
        rule="T1",
    ),
    CodeDef(
        code="RHO3010", slug="view-members-share-pin", severity="error",
        message=(
            "view `{view}` binds {members} to one pin, `{pin}`, which would "
            "join them; bind each member of a view to a pin of its own (two "
            "views may share a pin)."
        ),
        params=("view", "pin", "members"),
        rule="T1",
    ),
    CodeDef(
        code="RHO3011", slug="port-name-clash", severity="error",
        message=(
            "`{name}` names both a bundle port or view and {other}, so "
            "`{name}.x` would be ambiguous; give one of them another name."
        ),
        params=("name", "other"),
        rule="T1",
    ),
    CodeDef(
        code="RHO3012", slug="interface-array-size-not-literal",
        severity="error",
        message=(
            "`{name}` is sized by `{size}`, a parameter reference; the size "
            "of a bundle port or of an interface member is a literal, since "
            "a port set and an interface's shape do not depend on parameter "
            "values."
        ),
        params=("name", "size"),
        rule="T1",
    ),
    CodeDef(
        code="RHO3013", slug="index-on-scalar-port", severity="error",
        message="`{path}` is not an array, so it takes no index.",
        params=("path",),
        rule="T1",
    ),
    CodeDef(
        code="RHO3014", slug="port-index-out-of-range", severity="error",
        message=(
            "`{endpoint}` selects member {index} of `{array}`, whose "
            "members are numbered 0 to {last}."
        ),
        params=("endpoint", "index", "array", "last"),
        rule="T1",
    ),
    CodeDef(
        code="RHO3015", slug="reference-member-not-leaf", severity="error",
        message=(
            "member `ref` of interface `{interface}` is a nested interface "
            "or an array; a reference member is a single node, so that it "
            "can be bound to a ground-typed net (GA-1)."
        ),
        params=("interface",),
        rule="GA-1",
    ),
    CodeDef(
        code="RHO3016", slug="port-array-needs-index", severity="error",
        message=(
            "`{path}` is an array of {size}; select one of them, as in "
            "`{path}[0]`, before naming its member `{member}`."
        ),
        params=("path", "size", "member"),
        rule="T1",
    ),
)


def code_rows() -> tuple:
    """(code, slug, severity) of every interface code, as spec 05/03
    restates them (reconciled by the conformance gate)."""
    return tuple((entry.code, entry.slug, entry.severity) for entry in CODES)
