"""Rhoform: the production compiler package.

This package is the tool the roadmap calls `rhoform` — the diagnostics
framework (R17/A1), the lexer/parser generated from the grammar (R12/L5),
which reads syntax 0.1 and its strict superset 0.2, the quantity-literal
reference implementation that anchors the spec's T3 normal form (R54/T3),
the elaborator (R13, with R15's fabrication facts) that flattens a parsed
design into IR v0 and its source map, serialized and hashed by
`rhoform.ir` (all of syntax 0.2 except `import`, which waits on the package
layer), the canonical formatter (R16) for both syntax versions, and the
command line (R18, `python3 -m rhoform check|fmt`, in `rhoform.cli`).

It deliberately imports nothing from `lang.bakeoff` (the throwaway
prototypes) and nothing from `lang.grammar` at import time; the parser loads
the generated Lark ARTIFACT `lang/grammar/rhoform.lark` as data, which is the
direction AMB-43 fixes: the grammar source of truth stays in one place and
this package consumes what it renders.
"""
