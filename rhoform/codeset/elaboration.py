"""Elaborator residuals: the block-2 codes the elaborator needs after M1, owned
in each wave by whichever landing owns rhoform/elaborate.py.

Its range: RHO2120-RHO2149 (rhoform.codes.RANGES). A new code takes the next
free number in the range, and CODES stays in code order. Empty until the
landing adds its first code.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = ()
