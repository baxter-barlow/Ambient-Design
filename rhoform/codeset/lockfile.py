"""Lockfile v0 (L2b, AMB-59): the file and its packages section (not-json,
not-canonical, version-unsupported, invalid, packages-stale,
entry-unsupported). Verifying a record a pick names is block 6, in parts.py.

Its range: RHO2070-RHO2079 (rhoform.codes.RANGES). A new code takes the next
free number in the range, and CODES stays in code order. Empty until the
landing adds its first code.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = ()
