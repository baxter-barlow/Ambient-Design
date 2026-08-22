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

## Codes are forever

A diagnostic code is `RHO` plus four digits. The registry
(`rhoform/codes.py`) is the only place a code may be declared; a code,
once published, keeps its meaning forever, and a retired code keeps its
number and slug and is never reassigned. The leading digit is the
code's block. This table is reconciled against the registry's block
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

`error` gates; `warning` annotates; `note` carries non-gating context.
Severity is fixed per code in the registry. Per-site waivers (T6), when
they land, downgrade at the reporting layer and are surfaced in reports;
they do not touch the registry. The `tier` field carries the V1
assertion tier (`static` or `dynamic`) on assertion results and is null
otherwise — V1 makes the tier visible in every diagnostic.

## Structured params, rendered messages

The params object is the machine-readable contract: exactly the fields
the registry declares for the code, no more, no fewer. The message
string is RENDERED from the registry's template and the params — a
conforming emitter cannot say something in prose that the params do not
carry, which is what "structured parameter fields separate from message
strings" is for.

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
deletes). Applicability is the closed three-level vocabulary:

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
