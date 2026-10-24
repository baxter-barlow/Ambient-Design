"""T2 pin-role ERC and the L9b single-pin-net rule (L1b, AMB-52).

Its range: RHO3101-RHO3199 (rhoform.codes.RANGES). A new code takes the next
free number in the range, and CODES stays in code order. Empty until the
landing adds its first code.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = ()
