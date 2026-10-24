"""T5 voltage domains and abs-max (L3, AMB-54): pass 5.

Not implemented yet. L3 finds each domain's origins and rails, computes
the envelopes, checks abs-max and recommended windows and domain
crossings (spec 05/06), and sets `analysis.domains`.
"""

NAME = "domains"
OWNER = "domains"
IMPLEMENTED = False


def run(model, analysis, report):
    """Pass 5: nothing yet (L3)."""
