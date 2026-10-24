"""T10 current and power budgets (L4, AMB-55): budget-exceeded,
declared-draw-below-part-data, declared-supply-above-part-data and
budget-fact-role.

Its range: RHO3401-RHO3499 (rhoform.codes.RANGES). A new code takes the next
free number in the range, and CODES stays in code order. Empty until the
landing adds its first code.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = ()
