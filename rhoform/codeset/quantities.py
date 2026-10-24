"""T3/T4 quantities and intervals (L1c, AMB-53): the exact-value lint and the
constraint and assertion-bound dimension checks.

Its range: RHO3201-RHO3299 (rhoform.codes.RANGES). A new code takes the next
free number in the range, and CODES stays in code order. Empty until the
landing adds its first code.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = ()
