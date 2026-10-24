"""T2 pin-role ERC and the L9b single-pin-net rule (L1b, AMB-52): pass 4.

Not implemented yet. L1b folds each net's physical members through the
pin-role pair table (spec 05/04), with the ground exemptions taken from
`analysis.ground`, and sets `analysis.erc`.
"""

NAME = "erc"
OWNER = "erc"
IMPLEMENTED = False


def run(model, analysis, report):
    """Pass 4: nothing yet (L1b)."""
