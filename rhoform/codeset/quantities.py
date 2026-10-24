"""T3/T4 quantities and intervals (L1c, AMB-53): the exact-value lint and the
constraint and assertion-bound dimension checks.

Its range: RHO3201-RHO3299 (rhoform.codes.RANGES). A new code takes the next
free number in the range, and CODES stays in code order.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = (
    # The T4 lint, narrowly (decision D23): an exact FORM on a nominal-valued
    # name of a `part abstract`. Ratings and limits are exact by nature, and
    # a degenerate band such as `0ohm +/- 5%` was written with a tolerance,
    # so neither is flagged. One per instance; its constraints are arrays.
    CodeDef(
        code="RHO3201", slug="exact-part-constraint", severity="warning",
        message=(
            "part constraint(s) {constraints} of this `part abstract` hold "
            "the exact value(s) {values}; no physical part has an exact "
            "nominal value, so resolution would match nothing or invent a "
            "tolerance. State the tolerance the design accepts (T4)."
        ),
        params=("constraints", "values"),
        rule="T4",
    ),
    # RHO2038's repair pattern from the check stage's own range (D8). One
    # per instance, so its params are RHO2038's, pluralized into arrays in
    # name order: an instance with two mismatched constraints has one
    # finding. A wrong dimension is a defect of the source, not a judgment
    # a design can overrule, so neither code is waivable.
    CodeDef(
        code="RHO3202", slug="constraint-dimension-mismatch", severity="error",
        message=(
            "the constraint vocabulary types part constraint(s) "
            "{constraints} as {expected}, but this instance gives {values}, "
            "which is {found} (T3)."
        ),
        params=("constraints", "values", "found", "expected"),
        rule="T3",
        waivable=False,
    ),
    CodeDef(
        code="RHO3203", slug="bound-dimension-mismatch", severity="error",
        message="`{value}` is {found}, but {context} takes {expected}.",
        params=("value", "found", "context", "expected"),
        rule="T3",
        waivable=False,
    ),
)
