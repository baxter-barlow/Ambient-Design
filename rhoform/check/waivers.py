"""T6 waivers (L5a, AMB-56): applied by the driver after the passes.

Not implemented yet. L5a matches each buffered finding, before dedup, to
the design's waivers on (code, entity) and turns a waived error into an
RHO0002 note carrying the original code (spec 05/08); until then nothing
is waived.
"""


def apply(model, findings):
    """The findings once waived: all of them, unchanged, until L5a."""
    return findings
