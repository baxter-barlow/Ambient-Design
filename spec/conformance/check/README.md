# Check cases

*Part of the Rhoform Language Specification · CC-BY-4.0 (see
[spec/README.md](../../README.md))*

One directory per **area**, each pinning one pass of the check stage
([05 — Static types](../../language/05-static-types.md)). An area holds
`pass.json`, `{"last_pass": NAME}`, naming the last pass its cases run,
and `accept/` and `reject/`, one directory per case, each its own
compile root with its entry `main.rhoform` and its pinned stream
`expected.ndjson`. The format and the rules are
[conformance/README.md](../README.md#check--the-check-stage-by-area)'s.

The area a landing owns is its own to add to; `model` is the checked
design itself (the stage's foundation), and its cases run no pass.
`assertions` is the static assertion tier's
([05 section 8](../../language/05-static-types/08-waivers-and-static-assertions.md));
until that pass lands it holds the `RHO3553` the driver reports in its
place.
