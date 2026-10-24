"""T1 nominal interfaces (L2a, AMB-51): the block-3 interface checks, and any
syntax or elaboration code interfaces need.

Its range: RHO1030-RHO1039, RHO2100-RHO2119 and RHO3001-RHO3099
(rhoform.codes.RANGES). A new code takes the next free number in the range,
and CODES stays in code order. Empty until the landing adds its first code.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = ()
