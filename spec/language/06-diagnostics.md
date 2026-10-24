# 06 — Diagnostics

*Rhoform Language Specification · normative, v0.1 · CC-BY-4.0 (see
[spec/README.md](../README.md))*

Every Rhoform tool reports through one diagnostic format (A1). The
structural half is
[`rhoform/diagnostic.schema.json`](../../rhoform/diagnostic.schema.json)
(normative by reference); this section states the semantics the schema
cannot.

## The stream

Diagnostics are emitted as newline-delimited JSON on stdout: zero or
more lines, each one object conforming to the schema, nothing else on
stdout. Consumers read line-wise and MUST ignore lines that are not JSON
objects (stderr is for the tool's own operational complaints, never for
diagnostics).

Exit-code contract for checking tools: `0` — ran, no error-severity
diagnostics; `1` — ran, at least one error; `2` — could not run (a
missing dependency is an unavailable gate, never a pass).

**Filter mode** is the one stated carve-out from "nothing else on
stdout". A tool that reads a proposed source on stdin and answers with
its accepted form (the A2 write gate, `rhoform fmt --stdin`) puts the
canonical source on stdout when it exits `0` and the diagnostic stream
when it exits `1`; on exit `2` stdout is empty. A consumer branches on
the exit code before reading stdout.

## The command line

`python3 -m rhoform` is the reference command line (R18). It speaks the
stream and the exit codes above, and its paths are those of
[04 — Elaboration](04-elaboration.md#the-compile-root): every span's
`file` is a POSIX path relative to its compilation's compile root (a
standard library module's, its library path).

`rhoform check PATH...` compiles each PATH as the entry file of its own
compilation, with the files it imports
([08 — Packages and imports](08-packages.md#the-command-line); a
directory stands for its `*.rhoform` files, in sorted order, less those
another named file imports, and a directory that cannot be listed exits
`2` naming it rather than be skipped): the package layer's checks, parse,
file-local checks, elaboration, validation of the IR against the IR
schema of the version it writes ([04](04-elaboration.md)), and the check
stage ([05 — Static types](05-static-types.md#1-the-checking-model)). IR
that cannot be validated because the validator is missing exits `2`, and
so does IR the schema rejects (an internal error). It writes nothing,
except that `--emit-ir DIR` writes `<stem>.ir.json` and
`<stem>.sourcemap.json` for each entry that elaborates, whatever the
check stage finds, and `--emit-report DIR` writes `<stem>.check.json`,
the check report, for each entry the check stage ran on, after
validating it against its schema (a missing validator or a report the
schema rejects exits `2`). Two entries whose stems differ only in letter
case are refused, as one stem, before anything is written.
`--compile-root DIR` and `--root-module NAME` name the compile root and
the root module.

`rhoform fmt PATH...` rewrites each file in its canonical form
([07 — Formatting](07-formatting.md)), atomically and only when its
bytes change. A file that does not parse is refused: its diagnostics are
reported and its bytes are left alone. `rhoform fmt --check PATH...`
writes nothing and reports each file that would change as one
`RHO1017` (`not-canonical`) error spanning the first line that differs.

`rhoform fmt --stdin TARGET` is the write gate, in filter mode. A
proposal that does not parse is rejected: its diagnostics on stdout,
TARGET untouched, exit `1`. An accepted proposal's canonical bytes
atomically replace TARGET and are echoed on stdout, exit `0`, so the
writer always holds the bytes that were written (I1). `--dry-run` leaves
TARGET alone and answers the same way.

## Codes are forever

A diagnostic code is `RHO` plus four digits. The registry
(`rhoform/codes.py`, with the per-owner files it assembles under
`rhoform/codeset/`) is the only place a code may be declared; a code,
once published, keeps its meaning forever, and a retired code keeps its
number and slug and is never reassigned. Each code lies in a range one
owner holds ([05](05-static-types.md#code-ranges)). The leading digit is
the code's block. This table is reconciled against the registry's block
table by the conformance gate:

| Block | Category | Owner |
|---|---|---|
| RHO0xxx | framework | the diagnostics framework itself |
| RHO1xxx | syntax | lexer/parser and file-local checks |
| RHO2xxx | elaboration | the elaborator |
| RHO3xxx | types | the static type system |
| RHO4xxx | ground-architecture | the T5 ground rules GA-1..GA-17 |
| RHO5xxx | verification | the dynamic assertion tier |
| RHO6xxx | parts | part resolution and binding |
| RHO7xxx | interop | exports and the KiCad boundary |

The RHO40xx entries were published ahead of their checker by the
ground-architecture spec; the registry carries them as *reserved* —
shape frozen, emitter pending — and the registry gate holds the
transcription to the spec's catalog.

## Severity and tier

The severity vocabulary is closed (reconciled against the registry's
constants by the conformance gate):

- `error` — gates (V1).
- `warning` — annotates.
- `note` — non-gating context: safety notes, the truncation marker.

Severity is fixed per code in the registry. Per-site waivers (T6), when
they land, downgrade at the reporting layer and are surfaced in reports;
they do not touch the registry, and only an error of blocks 3–5 may be
waived. The `tier` field carries the V1 assertion tier on assertion
results and is null otherwise — V1 makes the tier visible in every
diagnostic. The assertion tiers are `static` and `dynamic`.

## Structured params, rendered messages

The params object is the machine-readable contract: exactly the fields
the registry declares for the code, no more, no fewer. The message
string is RENDERED from the registry's template and the params — a
conforming emitter cannot say something in prose that the params do not
carry, which is what "structured parameter fields separate from message
strings" is for.

A param's value is a JSON scalar — a string, a finite number, a boolean
or null — or an array of scalars, never an object: structure a value
carried would be structure the rendered message never shows. A quantity
is carried as its normal-form string (`"3.6V"`,
[03 — Literals](03-literals.md)), never as a JSON number, which would be
a double; an interval as two such params, `<name>_min` and `<name>_max`.
A value is fixed when the diagnostic is built, so the line on the wire
and the message rendered from it always agree.

## Spans and the entity anchor

Spans use the source-map schema's vocabulary: byte offsets are
authoritative, line/col are denormalized, exactly one span per
diagnostic is primary. Post-elaboration diagnostics additionally carry
the IR entity identity they are ABOUT (`entity`), per the source-map
schema's diagnostic-anchor rule; their spans are that identity's
resolution through the map, so a reformat moves the diagnostic with the
declaration. Pre-elaboration stages (the lexer and parser) have no IR to
anchor to; their `entity` is null and their spans are raw.

## Fix-its

A fix-it is a message, an applicability level, and one or more edits
(span plus replacement; a zero-length span inserts, an empty replacement
deletes). Applicability is the closed three-level vocabulary (reconciled
against the framework's constants by the conformance gate):

- `machine-applicable` — applying the edits verbatim is believed
  correct; the agent re-runs the check rather than trusting it blindly.
- `needs-review` — the edits are concrete but require judgment.
- `has-placeholders` — the edits contain `<name>` markers the author
  must fill, every one declared in `placeholders`. This is how a fix-it
  inserts an entity with a synthesized name.

## Canonical order and the cap

Emission order is canonical: primary span's file, then byte start, then
byte end, then code, then message, then params — source order first,
because a repair loop reads a file top to bottom (P2). *(Decision
recorded: the ground-architecture implementation notes sketched
"code, then primary span" before this framework existed; the framework
owns the order, and source-position-first supersedes that sketch.)*

Output is capped at **100 diagnostics**. The cap is deterministic:
errors are retained before warnings before notes, canonical order
deciding within a severity, and the emitted lines are re-sorted
canonically. When anything is suppressed, the stream's last line is the
`RHO0001` (`diagnostics-truncated`) note carrying exact counts — a
truncation the reader cannot see would change a repair run's difficulty
invisibly, so the cap is stated, never silent.
