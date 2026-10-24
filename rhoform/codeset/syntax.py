"""Syntax 0.3 (L1a): its parse codes, and the generic elaboration of 0.3
statements (annotation targets, duplicate facts, rule pins, placement).

Its range: RHO1018-RHO1029 and RHO2080-RHO2089 (rhoform.codes.RANGES). A new
code takes the next free number in the range, and CODES stays in code order.
Empty until the landing adds its first code.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = ()
