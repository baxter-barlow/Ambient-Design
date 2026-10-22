# 02 — Grammar, names, and vocabularies

*Rhoform Language Specification · normative, v0.2 · CC-BY-4.0 (see
[spec/README.md](../README.md))*

## The grammar, by reference

The productions of Rhoform syntax 0.1 and 0.2 are defined by
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

One grammar serves both syntax versions. [Syntax 0.2
additions](#syntax-02-additions) below describes what 0.2 adds, and
[01 — Lexical structure](01-lexical-structure.md#syntax-versions) how a
file declaring 0.1 is held to 0.1.

## Names

Two identifier roles exist, and the distinction is frozen (the second
recorded asymmetry of v0.1, carried into 0.2 unchanged):

- A name being **bound** — a module, port, net, table row, or instance
  name, and since 0.2 a component, an imported name, a declared
  parameter, or a loop variable — MUST NOT be a keyword or a reserved
  word.
- A **parameter reference** (0.2) — a bare name used as a value, in an
  `if` condition, as a `range` bound, as an array size, or as the base
  of an index — MUST NOT be one either. A reference can only name a
  parameter or a loop variable, which are bound names, so a keyword
  there could never resolve; and as a value, `true` and `false` stay
  boolean literals.
- Every **other** name position — pin names, constraint names, argument
  names (the name in `name = value` inside an argument list), column
  names, and the component after a dot — MAY be a keyword.
  `pin net passive` is legal; so is `r1.net` as an endpoint, and since
  0.2 `pin in passive` and `r1.in`.

One consequence, stated so it stays a decision: a chain statement's HEAD
is a binding-checked position while endpoints after `~` are not, so
`net.a ~ x` is rejected while `x ~ net.a` is accepted.

Every keyword carries a word boundary: `moduleM:` is a use of the name
`moduleM`, never of the keyword `module`.

### Keywords

The 31 words the grammar spells as literals. This list is reconciled
against the grammar source of truth by the conformance gate. Syntax 0.2
added seven of them, each reserved in 0.1 so that adding it could break
no design; they are named under Syntax 0.2 additions below.

`abstract` `assert` `at` `board_only` `component` `dnp` `dynamic` `else`
`exclude_from_bom` `false` `for` `from` `hardware` `if` `import` `in`
`isolated` `least` `module` `most` `net` `new` `no` `part` `pin` `port`
`static` `table` `to` `true` `within`

### Reserved for v1

The 1 word reserved and not yet used by any rule, excluded from binding
positions now because reserving a word later is a breaking change (E1).
It is required by an approved requirement a later milestone implements:
T1 interface definitions. v0.1 reserved eight words; syntax 0.2 gave
seven of them productions, and they are keywords now.

`interface`

## Closed vocabularies

Six word sets are checked by list AFTER parsing, never as keywords —
`input` and `output` are pin roles, and a grammar that reserved them
would reject `input = new ...`, a legal design. A conforming
implementation MUST accept these words as ordinary names in name
positions and MUST reject, at parse level, a word outside the list in a
vocabulary position (`RHO1009`, with a did-you-mean fix-it when one
entry is clearly closest). The lists are reconciled against
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

### param_type (L3)

A declared parameter's type (syntax 0.2): string, int and bool, then
one word per quantity dimension of the unit table in
[03 — Literals](03-literals.md#the-unit-table).

`bool` `capacitance` `current` `frequency` `inductance` `int` `length`
`power` `resistance` `string` `temperature` `time` `voltage`

### loop_iterator (L3)

The one callable a for header may name (syntax 0.2). It is a vocabulary
word rather than a keyword because 0.1 never reserved it: making it a
keyword would stop a 0.1 design that binds it as a name from parsing,
which is the breaking change E1 forbids.

`range`

## Syntax 0.2 additions

Syntax 0.2 adds the constructs below and nothing else; every 0.1
construct keeps its shape and its parse tree. This section describes
their shape. The productions themselves are the EBNF's, and what the
constructs MEAN — which names are in scope, how parameters, defaults
and arguments bind, how conditions evaluate, how loops and arrays
expand and what the expanded members are called — is
[04 — Elaboration](04-elaboration.md)'s, not this section's or the
parser's.

### Keywords added in 0.2

The words syntax 0.2 promoted from the reserved list to keywords, all of
them in the keyword list above. This list is reconciled against the
grammar source of truth by the conformance gate.

`component` `else` `for` `from` `if` `import` `in`

### Imports

```text
import Divider from "lib/divider.rhoform"
import Led, Resistor from "lib/parts.rhoform"
```

An import line names one or more definitions, comma-separated, and the
file they come from as a string. Import lines follow the pragma and
precede the first definition; none may appear later. Each imported name
is bound, so it follows the binding rule in [Names](#names). What the
path is relative to and what it may name are elaboration's.

### Component definitions

```text
component Led:
    pin a passive 1
    pin k passive 2
```

A file's definitions are modules and, since 0.2, components, in any
order. A component definition is `component`, its name, an optional
parameter list, a colon, and a block of `pin` statements and nothing
else: no `part`, `hardware` or flag statements, because a definition
carries no defaults for those in 0.2. A `pin` statement has the shape it
has in an instance body.

### Parameter lists

```text
module Divider(r_top: resistance = 10kohm, r_bottom: resistance,
               stages: int = 1, trimmed: bool = false):
```

A `module` or `component` header may carry a parameter list between its
name and the colon. The list may be empty, and like an argument list it
may wrap, because `(` suspends layout. Each parameter is a bound name, a
colon, a type, and optionally `=` and a default, which is any value. The
type is a param_type word, checked after parsing like every closed
vocabulary.

### Parameter references

Wherever a value may appear — an argument, a constraint, a table cell, a
parameter's default, the right-hand side of a comparison — 0.2 also
accepts a bare name: a parameter reference. It follows the reference
rule in [Names](#names). Under a 0.1 pragma a bare-name value such as
`color = red` is therefore `RHO1016`, not an unexpected token.

### Conditionals

```text
if fast:
    r1.a ~ out
else:
    if n >= 2:
        isolated r1.a
```

`if`, a condition, a colon and a block, then optionally `else`, a colon
and a block at the `if`'s own indentation. A block holds one or more
statements of the kinds a module body holds, nested `if` and `for`
included. A condition is a parameter name alone, or a parameter name, a
comparison operator ([01 — Lexical
structure](01-lexical-structure.md#punctuation-tokens)) and a value.
There is no `and`, `or` or `not`: they were never reserved, and making
them keywords now would be a breaking change, so conjunction is spelled
by nesting. There is no `elif`; an `if` nested in the `else` block
serves. An `if` is a statement and appears only where a statement may.

### Loops

```text
for i in range(4):
    caps[i].a ~ vin
for i in range(1, n):
    caps[i - 1].b ~ caps[i].a
```

`for`, a bound loop variable, `in`, the callable, one or two bounds in
parentheses, a colon and a block. The callable is a loop_iterator word,
checked after parsing, so it stays an ordinary name everywhere else. A
bound is an integer or a parameter reference: there is no third (step)
argument and no arithmetic in a bound.

### Arrays and indexed endpoints

```text
caps = new rhoform.lib.passive.Capacitor[n](capacitance = 100nF)
caps[0].a ~ vin
net GND:
    caps[1].b
isolated caps[last].b
```

An instance declaration may carry an array size in square brackets
after the definition's name and before its arguments: an integer or a
parameter reference. An endpoint — a chain head, an endpoint after `~`,
a net member, the endpoint of `isolated` — may index its first name:
`c[i]` or `c[i].pin`. An index is a name or an integer, optionally
followed by an offset operator and an integer: `c[2]`, `c[i]`,
`c[i + 1]`, `c[i - 1]`. Square brackets do not suspend layout
([01 — Lexical structure](01-lexical-structure.md#layout)), so an index
never wraps.

### Under a 0.1 pragma

Every construct in this section is refused in a file whose pragma
declares 0.1, with one `RHO1016` per file and a machine-applicable
fix-it that rewrites the pragma, as
[01 — Lexical structure](01-lexical-structure.md#syntax-versions)
states. The grammar itself accepts them under either pragma.

## What the grammar deliberately does not check

The parse level accepts some sentences the language rejects later, and
an implementation MUST NOT tighten these at parse level:

- **Table-row arity.** A row carries one value per column of its header,
  but no context-free rule can count a preceding declaration; the arity
  check belongs to the checker, reported against the header.
- **Names resolving.** An undeclared instance in an endpoint is an
  elaboration error, not a parse error. So, since 0.2, are a parameter
  reference naming no parameter or loop variable in scope, an imported
  name its file does not define, and a definition name with no
  definition.
- **Dimensional agreement.** A quantity literal's internal consistency
  is checked at parse level ([03 — Literals](03-literals.md)); whether
  its dimension suits its context is the type system's question (M2).
- **What a 0.2 block or bound may hold.** A `for` body takes the same
  statements as any block, instance declarations included, and the
  grammar accepts any integer as a size, an index or a bound. Which
  statements a loop body may hold, which conditions, sizes, indexes and
  ranges are legal, and how far a design may expand are elaboration's
  ([04 — Elaboration](04-elaboration.md)).
