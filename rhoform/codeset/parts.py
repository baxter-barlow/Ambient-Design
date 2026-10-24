"""Part picks, record verification, binding and constraint satisfaction (L2b,
AMB-59), then the D3 follow-ons inside M2 (L2d, L5b). A `part "key"` with no
keyed pick is RHO6001.

Its range: RHO6001-RHO6049 and RHO6050-RHO6099 (rhoform.codes.RANGES). A new
code takes the next free number in the range, and CODES stays in code order.
Empty until the landing adds its first code.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = ()
