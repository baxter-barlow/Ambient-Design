"""Rhoform syntax v0 — the frozen grammar, and the tools that keep it honest.

`rhoform_syntax` is the source of truth; `rhoform.ebnf` and `rhoform.lark` are
generated from it and are never edited by hand. `conformance` turns the Lark
artifact into a real parser, which is what makes the freeze checkable.

Unlike its neighbour `bakeoff`, this package is NOT throwaway: the prototypes
exist to have decided the grammar, and this is what they decided. AMB-43
generates the production parser from `rhoform.lark`.
"""
