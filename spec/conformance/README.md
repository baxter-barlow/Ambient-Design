# The Rhoform conformance suite

*Part of the Rhoform Language Specification · CC-BY-4.0 (see
[spec/README.md](../README.md))*

These cases define, executably, what a conforming Rhoform implementation
does. In this repository `tests/conformance/check-conformance.py` (the
gate; Apache-2.0 code) runs them against the reference implementation on
every `make all`; a third-party implementation conforms to the parse and
literal layers exactly when it reproduces them. The suite is standing —
each milestone that changes the language adds its cases in the same
change (parser disambiguation with R12, formatter cases with R16, type
cases with M2, and so on).

## `parse/accept/` — sources that parse clean

Each `<case>.rhoform` MUST parse with **zero diagnostics**. These pin
the accepted surface, including the decisions a reader might "fix":
keywords usable in non-binding name positions, the chain-endpoint
asymmetry's accepted half, comments before the pragma, a file without a
final newline.

## `parse/reject/` — sources with defects, and the exact report

Each `<case>.rhoform` is paired with `<case>.expected.ndjson`: the
byte-exact A1 diagnostic stream the reference implementation emits for
it (each line conforms to `rhoform/diagnostic.schema.json`). The gate
compares bytes, so codes, spans, params, fix-its, AND canonical order
are all pinned — a span that drifts by one byte is a red gate, which is
the point: diagnostics are the repair loop's substrate (P2), and their
stability is part of the language's contract.

Third-party note: byte-exactness of `message` strings is a REFERENCE
property (messages render from the registry's templates); an independent
implementation conforms at the parse layer when it reproduces the
codes, spans, structured params, and order.

Regenerating an expected file after a deliberate change:

```sh
python3 tests/conformance/check-conformance.py --write
```

The diff is the review artifact; an expected file never changes without
one.

## `literals/normal-form.json` — the T3 vector table

The machine-checked half of
[03 — Literals](../language/03-literals.md). `vectors` rows map an input
literal to its canonical spelling; the gate checks each row plus the
three properties (value-exact, idempotent, re-lexable) ON the row, so a
vector that contradicts the properties cannot be committed. `errors`
rows pin the stable rejection reasons ill-formed literals carry
(RHO1010's `reason` param).

## Case naming

`aNN_...` accept cases, `rNN_...` reject cases, numbered in the order
they were added, never renumbered — a conformance case is cited by name
in commit messages and issues, and a renamed case orphans every
citation.
