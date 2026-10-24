# 02 — Grammar, names, and vocabularies

*Rhoform Language Specification · normative, v0.2 and the unfrozen 0.3 · CC-BY-4.0 (see
[spec/README.md](../README.md))*

## The grammar, by reference

The productions of Rhoform syntax 0.1, 0.2 and 0.3 are defined by
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

One grammar serves every syntax version. [Syntax 0.2
additions](#syntax-02-additions) and [Syntax 0.3
additions](#syntax-03-additions-unfrozen) below describe what each
adds, and [01 — Lexical structure](01-lexical-structure.md#syntax-versions)
how a file is held to the version it declares.

## Names

Two identifier roles exist, and the distinction is frozen (the second
recorded asymmetry of v0.1, carried into 0.2 unchanged):

- A name being **bound** — a module, port, net, table row, or instance
  name, since 0.2 a component, an imported name, a declared parameter,
  or a loop variable, and since 0.3 a component's side — MUST NOT be a
  keyword or a reserved word. In a file declaring 0.3, it MUST NOT be a
  word [reserved from 0.3](#reserved-from-03) either (`RHO1019`); nor
  may a reference, or the first name of a 0.3 statement's target.
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
  0.2 `pin in passive` and `r1.in`. A pin a 0.3 component rule or side
  names MAY be any keyword but `from` and `to`, the two words a rule
  spells itself, so `regulate out from in` names a pin `in`.

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

Seven word sets are checked by list AFTER parsing, never as keywords —
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

`ground_domain` `ground_kind` `voltage_domain`

The third is syntax 0.3's: in a file declaring an older version it is
RHO1016, and its value is a string holding a word of the next list.

### ground_kind (GA-2)

The kind a net's ground_kind attribute states (syntax 0.3), checked as
the string's content, as in ground_kind = "power". A string outside the
list is RHO1009 with this vocabulary named and, when one word is
clearly closest, a fix-it that writes it in quotes. What a kind means, and how
the kinds of joined nets meet, is the check stage's (GA-2).

`chassis` `earth` `power` `signal` `unspecified`

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
construct keeps its shape and its parse tree. Its meaning is kept too,
with one deliberate exception that is no construct: a dotted name under
the standard library's reserved prefix `rhoform.lib.` names a library
component in a 0.1 file as well, which [04 — Elaboration](04-elaboration.md)
records as a departure from decision S-1's strict-superset wording. This section describes
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
import Divider from "./lib/divider"
import Led, Resistor from "acme/parts/leds"
```

An import line names one or more definitions, comma-separated, and the
file they come from as a string. Import lines follow the pragma and
precede the first definition; none may appear later. Each imported name
is bound, so it follows the binding rule in [Names](#names). What the
path is relative to and what it may name are the package layer's
([08 — Packages and imports](08-packages.md)).

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
has in an instance body. A component with no pins — a mounting hole, a
fiducial, artwork — has no block either: its definition is the header
alone, with no colon (`component Fiducial`), as a `part "key"` binding
with no constraints is.

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

## Syntax 0.3 additions (unfrozen)

Syntax 0.3 is unfrozen ([01 — Lexical
structure](01-lexical-structure.md#syntax-versions)): the constructs
below may still change until M2 exits. It adds them and nothing else; a
file declaring 0.1 or 0.2 keeps its parse tree, its diagnostics and its
meaning. They state source facts: the electrical structure of a
component, a supply, a load, a waiver, a severity, a ground's kind. What
each fact MEANS to a check is the check stage's (spec 05); elaboration
resolves what a statement names and keeps it ([04 —
Elaboration](04-elaboration.md#syntax-03-source-facts-unfrozen)).

### Soft keywords (0.3)

The words that open 0.3's statements. None was reserved in 0.2, so none
can be a keyword without breaking a 0.2 file that binds it (E1): each is
recognized as its word only where its statement may start, a 0.2 file
binding one parses to the tree it always had, and from 0.3 on the words
of [Reserved from 0.3](#reserved-from-03) are refused as names. This
list is reconciled against the grammar source of truth by the
conformance gate.

`draw` `rule` `side` `supply` `waive` `warning`

### Rule words (0.3)

The words a component rule opens with, recognized only where a component
body statement starts. A misspelled one is an unexpected token whose
expected list names "a rule word", not a did-you-mean: a component body
held only pin statements through 0.2, and a name-shaped rule would turn
a misspelled pin keyword in a 0.2 file into a rule. This list is reconciled
against the grammar source of truth by the conformance gate; only the
check stage's owner adds to it.

`bias` `bridge` `conduct` `connector` `diode` `feedback` `ground` `hiz`
`open` `pass` `rail` `ref` `regulate` `source` `switch` `tie`

### Reserved from 0.3

The words a file declaring 0.3 or later may not use as a name
(RHO1019): the four module-statement soft keywords, and variant,
reserved for assembly variants (E4) before any construct uses it, so
that adding one later breaks nothing. A file declaring 0.2 binds them
freely. This list is reconciled against the grammar source of truth by
the conformance gate.

`draw` `rule` `supply` `variant` `waive`

### Component rules and sides

```text
component Ldo(vout: voltage = 3.3V):
    pin gnd passive 3
    pin in power_in 1
    pin out power_out 2
    ground gnd
    regulate out from in = vout

component Opto:
    pin a passive 1
    pin c passive 3
    pin e passive 4
    pin k passive 2
    side detector: c e
    side emitter: a k
```

A component body may hold, beside its `pin` statements, rules and
sides. A rule is a rule word, the pins it covers, optionally `from` or
`to` and one more pin, and optionally `=` and a value, which may be a
parameter reference. A side is `side`, its name, a colon and the pins on
it. The grammar takes them in any order; the canonical form puts the
pins first ([07 — Formatting](07-formatting.md)).

### Quoted designators

```text
pin gnd passive "03"
```

A pin's designator may be a quoted string of printable characters with
no space, for the designators a number or a name cannot spell (a
leading zero). From 0.3 on, designators that run together with no
separator, `01`, are the error `RHO1018`, whose two needs-review fix-its
separate them (`0 1`) or quote them (`"01"`); 0.1 and 0.2 keep reading
`01` as `0` and `1` (AMB-139).

### Rule statements

```text
rule isos[1] open a k
```

`rule`, a target naming a component instance of the module, and a rule
body as a component's: the instance takes the module's rules in place of
its definition's, and keeps its definition's sides. It is for a part
used as something its definition does not say — a diode as a power
path, a FET as a load switch.

### Supply and draw

```text
supply VIN within 4.5V to 5.5V
supply ldo.out at most 300mA
draw ldo.in at most 5mA
```

`supply` or `draw`, a target, and a bound, the bound of an assertion. A
target is a name, optionally indexed, and optionally a pin after a dot:
here a net label or an instance pin. A supply's bound is a voltage window
or a current capability, a draw's a current into its target; which
dimension a target may take is the check stage's. There is no `expect`
statement: a containment expectation is a static assertion.

### Waivers

```text
waive RHO3001 isos[0] "a spare footprint; nothing drives it yet"
```

`waive`, the code it waives, a target — an instance, an array member, a
net label or an assertion of the module — and a justification string,
which is mandatory. Which codes are waivable, and what a waiver does, is
the check stage's (T6).

### Assertion severity

```text
assert ripple_ok dynamic ripple(VOUT) at most 50mV warning
```

An assertion may end with `warning`: a failing assertion then warns
rather than gates. Without it, an assertion is an error, as it always
was. An assertion that cannot be measured gates either way (V1).

### Under an older pragma

Every construct in this section is refused in a file whose pragma
declares 0.1 or 0.2, with one `RHO1016` per file whose fix-it rewrites
the pragma to 0.3, and the `ground_kind` attribute with them.

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
- **What a 0.3 statement names, and what its rule means.** Whether a
  target names something its module has, whether a fact is stated twice,
  and whether a rule's pins are its component's are elaboration's; how
  many pins a rule word takes, which targets and dimensions a statement
  accepts, and which codes may be waived are the check stage's.
