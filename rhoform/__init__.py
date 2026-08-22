"""Rhoform: the production compiler package.

This package is the tool the roadmap calls `rhoform` — the diagnostics
framework (R17/A1), the lexer/parser generated from the frozen grammar
(R12/L5), and the quantity-literal reference implementation that anchors the
spec's T3 normal form (R54/T3). Later milestones add the elaborator (R13),
the formatter (R16), and the CLI (R18) here.

It deliberately imports nothing from `lang.bakeoff` (the throwaway
prototypes) and nothing from `lang.grammar` at import time; the parser loads
the generated Lark ARTIFACT `lang/grammar/rhoform.lark` as data, which is the
direction AMB-43 fixes: the grammar source of truth stays in one place and
this package consumes what it renders.
"""
