"""T10 current and power budgets (L4, AMB-55): passes 6 and 7.

Not implemented yet. L4 sums each domain's worst-case draw against its
capability (spec 05/07) and sets `analysis.budget`. Pass 7, `Refine`
below, lives here too (amendment 12): it decides the T5 sites that depend
on current, from this pass's edge currents, behind DomainAnalysis's API,
and reports in the domains codeset.
"""

NAME = "budget"
OWNER = "budget"
IMPLEMENTED = False


def run(model, analysis, report):
    """Pass 6: nothing yet (L4)."""


class Refine:
    """Pass 7, domains.refine: nothing yet (L4)."""

    NAME = "domains_refine"
    OWNER = "domains"
    IMPLEMENTED = False

    @staticmethod
    def run(model, analysis, report):
        """Nothing yet (L4)."""
