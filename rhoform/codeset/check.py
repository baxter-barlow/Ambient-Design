"""The check driver and its coverage summary (L0, the M2 foundation).

Its range: RHO3901-RHO3999 (rhoform.codes.RANGES). A new code takes the
next free number in the range, and CODES stays in code order.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = (
    # One per compilation, never one per gap (amendment OD1): every pass
    # writes coverage rows to the check report, and only the actionable
    # ones -- a gap the author or the toolchain can close -- raise this.
    # Inherent limits stay in the report. Until every pass is implemented,
    # every check-stage run carries it.
    CodeDef(
        code="RHO3901", slug="static-coverage-degraded", severity="note",
        message=(
            "static checking did not cover this design fully: {actionable} "
            "actionable coverage gap(s), by class {classes}, in {sections}; "
            "`rhoform check --emit-report DIR` writes the check report that "
            "lists each one."
        ),
        params=("actionable", "classes", "sections"),
        rule="D2",
    ),
)
