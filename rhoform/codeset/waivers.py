"""T6 waivers and the V1 static assertion tier (L5a, AMB-56): the waiver
reporting layer (RHO0002 waived-diagnostic, RHO0003 unused-waiver), the
validation of waiver statements, and the static assertion results with
tier `static`.

Its ranges: RHO0002-RHO0009, RHO3501-RHO3549 and RHO3551-RHO3599
(rhoform.codes.RANGES). A new code takes the next free number in its
range, and CODES stays in code order.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = (
    # Reserved for L5a's results and emitted already, by the check driver on
    # behalf of the unimplemented assertions pass (amendment OD1): a
    # declared static-tier assertion that nothing evaluates gates, as V1
    # says an unmeasurable one must. L5a's evaluator takes it over for the
    # assertions it cannot decide.
    CodeDef(
        code="RHO3553", slug="static-assertion-incomplete", severity="error",
        message=(
            "static assertion `{assertion}` ({measurement}) could not be "
            "evaluated: {reason}; a declared assertion that cannot be "
            "measured gates unless waived (V1)."
        ),
        params=("assertion", "measurement", "reason"),
        rule="V1",
    ),
)
