"""Part picks and records (L2b, AMB-59): pass 1, and the check context.

Not implemented yet. L2b reads the compile root's rhoform.lock, verifies
each record a pick the design uses names (sha256 against the lock, schema,
lint), binds it through its `implements` map, and sets
`analysis.parts` (PartsAnalysis); no MPN is searched and nothing is
fetched. Until then no instance has part data, which the driver records
as this pass's actionable row.
"""

NAME = "parts"
OWNER = "parts"
IMPLEMENTED = False


def load_context(root, compilation):
    """The CheckContext of one compilation (`compilation` is the package
    layer's). Until L2b reads a lockfile, it holds the compile root and
    nothing else, so the check stage reads no file at all."""
    from . import CheckContext

    return CheckContext(root=root)


def run(model, analysis, report):
    """Pass 1: nothing yet (L2b)."""
