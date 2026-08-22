# Licensing boundary

Rhoform uses a deliberate license split:

- Source code, executable configuration, agent instructions, skills, CI, and repository-governance files are licensed under the Apache License 2.0 in [LICENSE](LICENSE).
- Product specifications and research documents published in the [Ambient Design Notion project](https://app.notion.com/p/3ba627dbcc428097b5c7ce1b2fc7bd70) are licensed under [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/legalcode.en), unless a document states otherwise.
- **`spec/`** — the in-repo normative language specification (requirement E2) — is CC-BY-4.0, declared in [spec/README.md](spec/README.md) and in each document's header. It lives in the repository rather than in Notion because it is a versioned release artifact grown in lockstep with the implementation, and its conformance suite's *case files and expected outputs* are part of the specification. The gate that runs them (`tests/conformance/check-conformance.py`) is code, Apache-2.0.

Unless a file states otherwise, new source and operational configuration use Apache-2.0. New product specifications and research documents must declare CC-BY-4.0 explicitly before publication in Notion — or, for the language specification only, under `spec/`.

## Copyright holder

Copyright 2026 Baxter Barlow. Stated here because the repository asserted a
licence without ever naming a licensor: a reader asking "who is granting me
this patent licence?" had no answer, and CC-BY-4.0's BY term was unsatisfiable
because there was nobody to attribute. Apache-2.0's appendix is instructions
for applying the licence, not a claim, so filling it in would not have fixed
this.

Attribute as: `Rhoform, copyright 2026 Baxter Barlow, https://github.com/baxter-barlow/Ambient-Design`.

## What the split does NOT cover

The sentence "everything in this tree is Apache-2.0 source and operational
configuration" was not true of two directories, and both are material:

- **`corpus/`** carries 93 verbatim excerpts from third-party forum posts,
  issue trackers and blog postmortems. The project cannot license a forum
  poster's words under Apache-2.0. They are quoted for identification,
  criticism and research; copyright in each stays with its author, and each is
  attributed to a specific URL in the entry that quotes it.
- **`parts/`** records carry their own `license_class` vocabulary
  (`vendor-public`, `vendor-agreement`, `open-cc`) describing the terms of the
  datasheet a value was read from. That vocabulary is deliberately separate
  from this file's split and is defined in `parts/part-data.schema.json`.

See [NOTICE](NOTICE) for the per-directory statement.

## Attribution

Rhoform's surface syntax adopts constructs from
[atopile](https://github.com/atopile/atopile), which is MIT-licensed —
principally the `module` and `new` keywords and the `~` connection operator.
Requirement L2 makes that attribution a first-class obligation rather than a
courtesy: "Adopt atopile's MIT-licensed surface with public attribution."

The frozen grammar is generated from an original rule table
(`lang/grammar/rhoform_syntax.py`), and the bake-off's atopile-faithful
candidate is the one that LOST, so no grammar text is copied. The attribution
above is owed regardless, and is stated here rather than deferred, because the
repository has been public since the artifacts were first pushed.

Shipping atopile's full MIT licence text in a `THIRD_PARTY_NOTICES` file is
tracked separately as AMB-117, gated on a public release.
