"""T5 voltage domains and abs-max (L3, AMB-54): origins, rails, envelopes,
abs-max and recommended windows, crossings and declared-voltage containment.
The current-dependent sites, which domains.refine decides in
rhoform/check/budget.py, report here too.

Its range: RHO3301-RHO3399 (rhoform.codes.RANGES). A new code takes the next
free number in the range, and CODES stays in code order. Empty until the
landing adds its first code.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = ()
