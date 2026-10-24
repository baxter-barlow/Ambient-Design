"""The V1 static assertion tier (L5a, AMB-56): pass 8.

Not implemented yet. L5a evaluates each static-tier assertion over the
envelopes and budgets and reports RHO3551-3553 with tier `static`
(spec 05/08); until then the driver reports every declared static-tier
assertion as RHO3553, because a declared assertion that cannot be
measured gates. Dynamic-tier assertions are the dynamic tier's (M5):
`check` never evaluates them, and they are no incompletes here.
"""

NAME = "assertions"
OWNER = "waivers"
IMPLEMENTED = False


def run(model, analysis, report):
    """Pass 8: nothing yet (L5a)."""
