# The Rhoform conformance suite

*Part of the Rhoform Language Specification · CC-BY-4.0 (see
[spec/README.md](../README.md))*

These cases define, executably, what a conforming Rhoform implementation
does. In this repository `tests/conformance/check-conformance.py` (the
gate; Apache-2.0 code) runs them against the reference implementation on
every `make all`; a third-party implementation conforms to the parse,
literal, elaboration and formatter layers exactly when it reproduces them. The suite is standing —
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
it (each line conforms to `rhoform/diagnostic.schema.json`).

One encoding exception: a case whose bytes are DELIBERATELY not valid
UTF-8 (the invalid-byte diagnostic class) is committed as
`<case>.rhoform.escaped` — ASCII text with Python-style byte escapes
(`\xff`, `\n`) — because this repository refuses tracked files that are
not valid UTF-8 (its retired-name scanner fails closed on binary, by
policy). The gate decodes the escapes to raw bytes before parsing; a
third-party runner must do the same. The expected stream's `file` field
carries the logical `<case>.rhoform` name either way. The gate
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
one. The same command rewrites the formatter cases' expected files
(below).

## `literals/normal-form.json` — the T3 vector table

The machine-checked half of
[03 — Literals](../language/03-literals.md). `vectors` rows map an input
literal to its canonical spelling; the gate checks each row plus the
three properties (value-exact, idempotent, re-lexable) ON the row, so a
vector that contradicts the properties cannot be committed. `errors`
rows pin the stable rejection reasons ill-formed literals carry
(RHO1010's `reason` param).

## `elaborate/accept/` — sources that elaborate clean, and the exact IR

The machine-checked half of
[04 — Elaboration](../language/04-elaboration.md). Each
`<case>.rhoform` MUST parse and elaborate with **zero diagnostics**, and
the IR it elaborates to MUST equal `<case>.expected.ir.json` byte for
byte: the IR v0 document in `rhoform-canonical-json/1`, hashes
included. The gate also validates that IR against
`ir/netlist-ir.schema.json`, so the suite cannot commit an expectation
the IR schema forbids. Each case is compiled alone with its own
directory as the compile root, so its one source file is
`<case>.rhoform`, its definitions are `<case>.<Module>`, and its
`source_hash` covers that file alone.

Third-party note: `header.generator` names the implementation that
produced the document and is outside `design_hash`; an independent
implementation conforms at this layer when its IR equals the expected
document with `header.generator` set aside.

## `elaborate/reject/` — sources the elaborator reports, and the exact report

Each `<case>.rhoform` MUST parse clean — a case that stops at the
parser belongs under `parse/` — and its elaboration diagnostic stream
MUST equal `<case>.expected.ndjson` byte for byte, exactly as for
`parse/reject/`. There is one case per block-2 code a source can
trigger, and the gate fails when an active block-2 code is emitted by
no case, unless it exempts the code with a stated reason it cannot be
reached from source text. A case pinning a warning (a repeated flag, a
repeated endpoint) still elaborates to a design; the stream is what it
pins.

`--write` regenerates the elaboration cases' expected IR and streams
along with the parse reject cases'; the diff is the review artifact.

## `fmt/` — formatter cases

The machine-checked half of
[07 — Formatting](../language/07-formatting.md). Each input
`<case>.rhoform` is paired with `<case>.expected.rhoform`, the canonical
bytes a conforming formatter writes for it. Two checks run per case,
both byte-exact: the input MUST format to the expected file, and the
expected file MUST format to itself (canonical output is a fixed
point). Every input MUST parse clean. Refusal needs no cases of its
own: the gate also requires the formatter to refuse every
`parse/reject/` case, returning no bytes.

An input that needs bytes this repository's whitespace policy refuses
in a tracked file — trailing spaces, blank lines at the end of the
file — is committed as `<case>.rhoform.escaped` under the same escape
convention as the reject cases above, and decoded before formatting.
Its expected file is never escaped: canonical output carries neither.

## Case naming

`aNN_...` accept cases, `rNN_...` reject cases, `fNN_...` formatter
cases, numbered within their directory in the order they were added,
never renumbered — a conformance case is cited by name in commit
messages and issues, and a renamed case orphans every citation. Cite an
elaboration case with its directory (`elaborate/r04_unknown_definition`),
since the parse cases use the same prefixes.
