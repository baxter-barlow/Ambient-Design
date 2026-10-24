# The Rhoform conformance suite

*Part of the Rhoform Language Specification · CC-BY-4.0 (see
[spec/README.md](../README.md))*

These cases define, executably, what a conforming Rhoform implementation
does. In this repository `tests/conformance/check-conformance.py` (the
gate; Apache-2.0 code) runs them against the reference implementation on
every `make all`; a third-party implementation conforms to the parse,
literal, elaboration, package, check and formatter layers exactly when it
reproduces them. The suite is standing —
each milestone that changes the language adds its cases in the same
change (parser disambiguation with R12, formatter cases with R16, type
cases with M2, and so on).

## `parse/accept/` — sources that parse clean

Each `<case>.rhoform` MUST parse with **zero diagnostics**. These pin
the accepted surface, including the decisions a reader might "fix":
keywords usable in non-binding name positions, the chain-endpoint
asymmetry's accepted half, comments before the pragma, a file without a
final newline.

Cases `a01`–`a08` declare syntax 0.1 and stay that way: 0.2 only adds,
so they must keep parsing clean under an implementation of both
versions (the reference implementation's tests also pin their parse
trees as unchanged). Cases from `a09` on declare 0.2, one per family of
constructs 0.2 added.

## `parse/reject/` — sources with defects, and the exact report

Each `<case>.rhoform` is paired with `<case>.expected.ndjson`: the
byte-exact A1 diagnostic stream the reference implementation emits for
it (each line conforms to `rhoform/diagnostic.schema.json`). Cases
`r24`–`r27` pin the four lexical codes no case pinned before them
(carriage return, end of file, an unexpected character, a control
character).

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
rows pin the stable rejection reasons the quantity reader gives an
ill-formed literal (RHO1010's `reason` param). RHO1010 has a second
source the table does not read: the parser's two reasons for a
misspaced `+/-`, given before the literal is one token, are pinned by
the reference implementation's parser tests.

## `elaborate/accept/` — sources that elaborate clean, and the exact IR

The machine-checked half of
[04 — Elaboration](../language/04-elaboration.md). Each
`<case>.rhoform` MUST parse and elaborate with **zero diagnostics**, and
the IR it elaborates to MUST equal `<case>.expected.ir.json` byte for
byte: the IR version 1 document in `rhoform-canonical-json/1`, hashes
included. The gate also validates that IR against
`ir/netlist-ir.v1.schema.json`, as does the schema gate
(`tests/schemas/validate-schemas.py`) for every committed expectation,
so the suite cannot commit an expectation the IR schema forbids. Each case is compiled alone with its own
directory as the compile root, so its one source file is
`<case>.rhoform`, its definitions are `<case>.<Module>`, and its
`source_hash` covers that file and the standard library modules it
names (`rhoform/lib/<module>.rhoform`): a case's expected IR moves when
one of those modules' bytes do.

Third-party note: `header.generator` names the implementation that
produced the document and is outside `design_hash`; an independent
implementation conforms at this layer when its IR equals the expected
document with `header.generator` set aside.

## `elaborate/reject/` — sources the elaborator reports, and the exact report

Each `<case>.rhoform` MUST parse clean — a case that stops at the
parser belongs under `parse/` — and its elaboration diagnostic stream
MUST equal `<case>.expected.ndjson` byte for byte, exactly as for
`parse/reject/`. The stream is the elaborator's: the case is compiled
through the pipeline the command line runs, stopped after elaboration,
so the check stage's notes are not part of it. A case pinning a warning
(a repeated flag, a repeated endpoint) still elaborates to a design; the
stream is what it pins.

**Coverage.** Across the reject cases of every layer — `parse/`,
`elaborate/`, `packages/` and `check/` — every active code of blocks 1–4
and 6 a source can trigger MUST be emitted by some case, and the gate
fails when one is emitted by none. A code no source text can reach says
so, and why, in its own registry entry (`source_triggered`,
`trigger_reason`: `RHO1017`, which only `fmt --check` reports, and
`RHO2003`, which only a caller's `--root-module` reaches); the gate
fails on an exemption a case contradicts, too.

`r33` pinned the interim refusal of `import` statements and was retired
with its code, `RHO2033`, when imports gained their semantics; its
number is not reused. Cases from `a09` and `r35` on declare syntax 0.2
and pin its semantics: component definitions, parameters, `if`, `for`
and arrays.

`--write` regenerates the elaboration cases' expected IR and streams
along with the parse reject cases'; the diff is the review artifact.

## `packages/accept/` and `packages/reject/` — compilations of several files

The machine-checked half of
[08 — Packages and imports](../language/08-packages.md). Each case is a
directory, and the directory is its compile root: it holds the case's
sources, any `rhoform.toml` manifests, and its expectation at its top
level. The entry file is the case's one `main.rhoform`, wherever it sits
(a case with a path dependency keeps each package in a directory of its
own, such as `app/` and `parts/`), and the compilation is that file plus
its import closure, read through the package layer exactly as the
reference command line reads it, plus the standard library modules its
files name. Those are listed in `source_hash` by their fixed path
`rhoform/lib/<module>.rhoform` whatever the case's layout
(`packages/accept/a05_standard_library`), so a package case's expected
IR moves when one of those modules' bytes do.

- `packages/accept/<case>/expected.ir.json`: the case MUST compile with
  **zero diagnostics** to IR equal to this file byte for byte, valid
  against `ir/netlist-ir.v1.schema.json` (the schema gate validates every
  committed expectation too).
- `packages/reject/<case>/expected.ndjson`: the case's diagnostic stream
  MUST equal this file byte for byte, each line valid on the wire
  schema. A manifest diagnostic's span `file` is the manifest's
  compile-root-relative path (`rhoform.toml`, `app/rhoform.toml`).

There is a reject case for every code of the package layer, and the
block-2 coverage rule above counts them. Every `.rhoform` file of a
package case is held to the canonical form, like the elaboration cases.
`--write` regenerates the expectations; the diff is the review artifact.

## `check/` — the check stage, by area

The machine-checked half of
[05 — Static types](../language/05-static-types.md). Cases are grouped
in **areas**, `check/<area>/`, one per checker. An area holds a
`pass.json`, `{"last_pass": NAME}`, and its `accept/` and `reject/`
directories, nothing else. NAME is the last pass the area's cases run
(or `model`, the checked design alone): the check stage runs the passes
up to and including it, so what an area pins is that pass's behaviour,
whatever later passes do, and a later landing never moves another
area's streams. One `integration` area, added with the last checker,
runs every pass.

Each case is a directory and its own compile root, like a package case,
its entry its one `main.rhoform`. It MUST reach the check stage — a case
that stops at the parser or the elaborator belongs to their layers — and
its stream MUST equal its `expected.ndjson` byte for byte, each line
valid on the wire schema. An `accept/` case reports no error or warning;
its notes, such as the coverage note every check-stage run carries while
passes are unimplemented, are pinned like the rest. A `reject/` case
reports something. Every source of a check case is in canonical form,
which the gate checks itself. `--write` regenerates the streams; the
diff is the review artifact.

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
messages and issues, and a renamed case orphans every citation. Check
cases are `cNN_...`, numbered across their area's `accept/` and
`reject/` together. A case retired with the behavior it pinned keeps its
number unused. Cite an elaboration, package or check case with its
directory (`elaborate/r04_unknown_definition`, `packages/r18_import_cycle`,
`check/model/c01_component_without_pins`), since the parse cases use the
same prefixes.
