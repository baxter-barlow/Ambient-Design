# The Rhoform Language Specification

**Status: skeleton, v0.1 syntax.** This is the normative specification of
the Rhoform language (requirement E2), grown at every milestone alongside
the reference implementation. It is a release artifact: the docs site
(R56) renders it, `llms-full.txt` (R36) derives from it, and the
conformance suite under [conformance/](conformance/) holds the reference
implementation to it.

## Licensing

Every document under `spec/` is licensed
[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/legalcode.en),
per the E2/E3 licensing boundary: specifications are CC-BY-4.0, code is
Apache-2.0. Attribute as: *Rhoform Language Specification, copyright 2026
Baxter Barlow, https://github.com/baxter-barlow/Ambient-Design*. The
conformance suite's **case files and expected outputs** are part of the
specification (CC-BY-4.0); the **gate that runs them**
(`tests/conformance/check-conformance.py`) is code (Apache-2.0).

## What "normative" means here

MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are used as in RFC 2119.
Where this specification is silent, the reference implementation in this
repository defines the semantics (E2: "reference implementation defines
semantics"); where the two disagree, that is a defect in one of them and
the conformance suite exists to make the disagreement loud rather than
philosophical.

Two artifacts elsewhere in this repository are normative by reference,
and this specification deliberately does not restate their content:

- `lang/grammar/rhoform.ebnf` — the grammar, generated from the single
  source of truth (`lang/grammar/rhoform_syntax.py`) and held to it by
  `make grammar`. Restating productions here would create the second
  hand-maintained copy L5 forbids.
- `rhoform/diagnostic.schema.json` — the diagnostic wire format's
  structural half.

Where a section below **does** restate a closed list from the
implementation (keywords, vocabularies, the unit table), the conformance
gate reconciles the restatement against the source of truth, so the spec
cannot drift from the language it describes. A list in this spec is
either machine-reconciled or absent.

## Sections

| Section | Status |
|---|---|
| [01 — Lexical structure](language/01-lexical-structure.md) | normative, v0.1 |
| [02 — Grammar, names, and vocabularies](language/02-grammar.md) | normative, v0.1 |
| [03 — Literals and the SI normal form](language/03-literals.md) | normative, v0.1 (T3; the single source R16 and R21 consume) |
| [04 — Elaboration](language/04-elaboration.md) | reserved (lands with the elaborator, AMB-44) |
| [05 — Static types and domains](language/05-static-types.md) | reserved (lands with M2; T5 transfer semantics land with R22) |
| [06 — Diagnostics](language/06-diagnostics.md) | normative, v0.1 (A1) |

The milestone plan for growth is the roadmap's: each milestone that
changes the language lands its spec section and its conformance cases in
the same change. A behavior shipped without its section is a defect of
that change, not a note for later.

## The conformance suite

[conformance/README.md](conformance/README.md) documents the case
format. The suite is runnable against any implementation that can parse
Rhoform sources and emit the diagnostic wire format; in this repository,
`tests/conformance/check-conformance.py` runs it against the reference
implementation on every `make all`.
