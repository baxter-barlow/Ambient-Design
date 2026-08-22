# 02 — Grammar, names, and vocabularies

*Rhoform Language Specification · normative, v0.1 · CC-BY-4.0 (see
[spec/README.md](../README.md))*

## The grammar, by reference

The productions of Rhoform v0.1 are defined by
[`lang/grammar/rhoform.ebnf`](../../lang/grammar/rhoform.ebnf), generated
from the single source of truth and held to it by `make grammar`. That
artifact is normative; this section states only what the grammar cannot
state about itself. The grammar is context-free over the layout-tokenized
stream of [01 — Lexical structure](01-lexical-structure.md) and is
LALR(1): an implementation whose parse of any file differs from the
reference implementation's is nonconformant, and the parser MUST reject
ambiguity rather than resolve it silently (E2) — the conformance suite's
`parse/reject` cases include the disambiguation decisions with the
reading each MUST get.

## Names

Two identifier roles exist, and the distinction is frozen (the second
recorded asymmetry of v0.1):

- A name being **bound** — a module, port, net, table row, or instance
  name — MUST NOT be a keyword or a reserved word.
- Every **other** name position — pin names, constraint names, parameter
  names, column names, and the component after a dot — MAY be a keyword.
  `pin net passive` is legal; so is `r1.net` as an endpoint.

One consequence, stated so it stays a decision: a chain statement's HEAD
is a binding-checked position while endpoints after `~` are not, so
`net.a ~ x` is rejected while `x ~ net.a` is accepted.

Every keyword carries a word boundary: `moduleM:` is a use of the name
`moduleM`, never of the keyword `module`.

### Keywords (v0.1)

The 24 words the grammar spells as literals. This list is reconciled
against the grammar source of truth by the conformance gate.

`abstract` `assert` `at` `board_only` `dnp` `dynamic` `exclude_from_bom`
`false` `hardware` `isolated` `least` `module` `most` `net` `new` `no`
`part` `pin` `port` `static` `table` `to` `true` `within`

### Reserved for v1

Eight words no v0.1 rule uses, excluded from binding positions now
because reserving a word later is a breaking change (E1). Each is
required by an approved requirement a later milestone implements.

`component` `else` `for` `from` `if` `import` `in` `interface`

## Closed vocabularies

Four word sets are checked by list AFTER parsing, never as keywords —
`input` and `output` are pin roles, and a grammar that reserved them
would reject `input = new ...`, a legal design. A conforming
implementation MUST accept these words as ordinary names in name
positions and MUST reject, at parse level, a word outside the list in a
vocabulary position. The lists are reconciled against
`CLOSED_VOCABULARIES` in the grammar source of truth by the conformance
gate.

### pin_role (T2)

`bidirectional` `input` `nc` `open_collector` `open_drain` `output`
`passive` `power_in` `power_out` `tri_state`

### hardware_kind (L9)

`artwork` `fiducial` `grounded_mounting_hole` `mounting_hole`
`test_point`

### net_attribute (T5)

`ground_domain` `voltage_domain`

### measurement_kind (V2)

`bandwidth` `duty_cycle` `efficiency` `fall_time` `frequency` `gain`
`operating_point` `overshoot` `period` `power_avg` `power_rms`
`prop_delay` `ripple` `rise_time` `settling_time`

## What the grammar deliberately does not check

The parse level accepts some sentences the language rejects later, and
an implementation MUST NOT tighten these at parse level:

- **Table-row arity.** A row carries one value per column of its header,
  but no context-free rule can count a preceding declaration; the arity
  check belongs to the checker, reported against the header.
- **Names resolving.** An undeclared instance in an endpoint is an
  elaboration error, not a parse error.
- **Dimensional agreement.** A quantity literal's internal consistency
  is checked at parse level ([03 — Literals](03-literals.md)); whether
  its dimension suits its context is the type system's question (M2).
