# 03 — Literals and the SI normal form

*Rhoform Language Specification · normative, v0.1 · CC-BY-4.0 (see
[spec/README.md](../README.md))*

This section is the T3 deliverable the roadmap orders authored FIRST: the
single source of truth for quantity-literal meaning and canonical
spelling. The canonical formatter (R16) and the quantity type system
(R21) consume this section — concretely, its reference implementation
`rhoform/quantities.py` — rather than deciding any of it again. The
vector table
[`spec/conformance/literals/normal-form.json`](../conformance/literals/normal-form.json)
is the machine-checked half of this section; a conforming implementation
MUST reproduce every row.

## The five forms (T4)

A quantity literal is one token, in one of five forms:

| Form | Example | Meaning |
|---|---|---|
| exact | `100kohm` | the exact value |
| tolerance, absolute | `2V +/- 0.2V` | nominal with a symmetric absolute band |
| tolerance, percent | `100kohm +/- 1%` | nominal with a symmetric relative band |
| interval, bracketed | `9.5mA (8mA to 10.5mA)` | nominal with an explicit asymmetric window |
| interval, bare | `3V to 3.6V` | a range with no centre — `nominal` does not exist |

Spelling rules, all of them errors when violated: ASCII only; no
exponent notation; exactly one space either side of `+/-` and `to`; a
`+/-` magnitude is non-negative (the sign is in the operator); a
bracketed interval MUST contain its nominal; a lower bound MUST NOT
exceed its upper bound; every unit in one literal MUST share one
dimension.

## Value-exactness

Literals are **value-exact** (T3). The value of a literal is a decimal
number, exactly as written; an implementation MUST NOT round it through
a binary floating-point representation at parse, comparison, or
normalization time. `0.1uF` means exactly one tenth of a microfarad —
not the nearest IEEE double — and `560ohm +/- 1%` means exactly
[554.4, 565.6] ohm. Two literals are the same quantity iff they have the
same dimension and exactly equal nominal, lower, and upper values in the
dimension's base unit, whatever units they were written in.

## The unit table

The unit table is CLOSED: an unknown unit is an error, never a
pass-through, so a typo cannot become its own dimension. The table below
is reconciled against the reference implementation's `UNITS` by the
conformance gate. Within each dimension the multipliers step by exactly
10³, which is what makes the normal form's unit choice unique; extending
a ladder is a change to this section, made here first.

| Dimension | Units, ascending | Base |
|---|---|---|
| resistance | `mohm` `ohm` `kohm` `Mohm` | `ohm` |
| capacitance | `pF` `nF` `uF` `mF` `F` | `F` |
| inductance | `nH` `uH` `mH` `H` | `H` |
| voltage | `uV` `mV` `V` `kV` | `V` |
| current | `nA` `uA` `mA` `A` | `A` |
| power | `uW` `mW` `W` | `W` |
| frequency | `Hz` `kHz` `MHz` | `Hz` |
| time | `ns` `us` `ms` `s` | `s` |
| length | `um` `mm` `m` | `m` |
| temperature | `degC` | `degC` |

Temperature is an offset scale: `degC` has no prefixed siblings and is
never rescaled — scaling a Celsius reading by a power of ten is
meaningless, and the way to make that mistake unrepresentable is to give
the table nowhere to scale it to. Dimensionless values are NUMBER and
INTEGER tokens of the grammar, not quantities; there is no dimensionless
unit.

## The normal form (T3)

Canonical text wins over authored spelling: the formatter rewrites every
quantity literal to the normal form defined here, and the normal form of
a literal is computed as follows.

**Rule 1 — every number–unit pair is rewritten independently.** A
literal's components are its number–unit pairs (the nominal, an absolute
tolerance, each interval bound). Each is rewritten by Rules 2–3 on its
own; components of one literal MAY therefore end in different units
(`1500mV +/- 20mV` normalizes to `1.5V +/- 20mV`). A percent tolerance's
number is rewritten by Rule 2 and keeps `%`.

**Rule 2 — minimal number spelling.** No leading `+`; no padding zeros
(a single `0` precedes the point in `0.5`; no trailing zeros follow a
fraction; no bare trailing point); negative zero is `0`.

**Rule 3 — unit choice.** For a non-zero value, the canonical unit is
the entry of the dimension's ladder that puts the magnitude in
[1, 1000). Because ladders step by exactly 10³, at most one entry
qualifies. When none does — the value falls off the ladder's end — the
nearest end is used and the magnitude is allowed outside the window
(`5000Mohm`, `0.05mohm`): inventing units the table does not carry is
not this rule's job. Zero is spelled in the dimension's base unit
(`0V`, `0A`). `degC` is never rescaled (see above).

**Rule 4 — form preservation.** The five forms are distinct value
shapes, and normalization never converts between them: a percent
tolerance stays percent (it carries the author's relative-intent), an
absolute tolerance stays absolute, and intervals keep their bracketing.
`1000mV +/- 10%` normalizes to `1V +/- 10%`, never to `1V +/- 100mV`.

Three properties follow, and the conformance gate checks all three over
the vector table rather than trusting the derivation:

- **Value-exact:** normalization never changes a literal's quantity —
  every rewrite is a power-of-ten shift on exact decimals, which cannot
  round.
- **Idempotent:** the normal form of a normal form is itself.
- **Re-lexable:** the canonical text is a legal quantity token of the
  frozen grammar — the formatter must never write a file the parser
  rejects.

## Errors

An ill-formed literal is the parse-level diagnostic `RHO1010`
(`invalid-quantity-literal`), carrying the literal and a stable reason
in structured params — see [06 — Diagnostics](06-diagnostics.md). The
vector table's `errors` half pins the reasons.
