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
[atopile](https://github.com/atopile/atopile), which is MIT-licensed. What was
adopted is the shape of the surface, not text:

- the definition nouns `module`, `component` and `interface` (syntax 0.2
  defines `component`; `interface` remains a reserved word whose definition
  arrives in a later syntax version);
- the `new` keyword;
- the `~` connection operator.

Requirement L2 makes that attribution a first-class obligation rather than a
courtesy: "Adopt atopile's MIT-licensed surface with public attribution."
References to atopile and to its `.ato` file format anywhere in this
repository are nominative only. They identify atopile's work and imply no
affiliation with or endorsement by its authors.

The frozen grammar is generated from an original rule table
(`lang/grammar/rhoform_syntax.py`), and the bake-off's atopile-faithful
candidate is the one that LOST, so no grammar text is copied. The attribution
above is owed regardless, and is stated here rather than deferred, because the
repository has been public since the artifacts were first pushed.

atopile's MIT licence text is reproduced verbatim in
[THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES), taken from a pinned atopile commit
and recorded with its source URL, git blob id and SHA-256 so the copy can be
checked against upstream.

## License-stability covenant

Requirement E2 defends Rhoform against incompatible third-party forks with the
trademark and the conformance suite, and against the project itself closing up
with structure. Contributions come in under the DCO with no CLA, so the
project never holds the copyright in other people's work and cannot relicense
it on its own. This covenant extends the same protection to the project's own
work, in writing and in advance.

**Who makes it.** Baxter Barlow, the copyright holder of record named above.
Every later holder of Rhoform copyrights or of the RHOFORM mark takes them
subject to this covenant, and any transfer will be made on that condition.

**When it binds.** It takes effect on the date of the first tagged release of
this repository. Until then it is a published statement of intent: the text
may still be revised, including after legal review, and every revision is
visible in this file's history. From that release on, commitment 7 governs
how it can change.

**What it covers.** The components requirement E3 keeps open forever: the
specification, compiler, formatter, renderer, exporters, documentation, agent
skills, seed component library and core macromodels. By function this
includes the command-line tool, the conformance suite, and the schemas these
components read and write (netlist IR, source map, part data, diagnostics).

**Commitments.**

1. **The licences stay.** Code stays Apache-2.0. The specification and
   documentation stay CC-BY-4.0. The seed library and core macromodels stay
   Apache-2.0 or CC0. Every future release of a covered component ships under
   these licences or more permissive ones, never under source-available,
   delayed-open, field-of-use, non-compete or non-commercial terms. Releases
   already made are irrevocably licensed by the licences they shipped under;
   this commitment is about future ones.
2. **DCO only.** Contributions are accepted under the Developer Certificate of
   Origin, and contributors keep their copyright. The project will not
   introduce a contributor licence agreement, a copyright assignment, or any
   licence-back clause that would let it relicense contributions.
3. **No hollowing out.** A feature of a covered component is never removed so
   that it can be offered again under a proprietary licence or only through a
   hosted service. Features are removed for technical reasons, and each
   removal is announced publicly with its reason.
4. **The toolchain stands alone.** Compiling, checking, formatting and
   exporting never require a hosted service, an account, or a network
   connection. The part-data contract stays public, and any third party can
   implement it.
5. **The trademark is not a licence back door.** The project will not enforce
   the RHOFORM mark against anyone before it has published a trademark
   policy. That policy will permit nominative use and the redistribution of
   unmodified releases. It will decide what may call itself Rhoform by
   conformance (requirement E2), not by copyright licensing.
6. **A neutral home.** Before the first release that makes a stability
   promise for the netlist IR or the part-data schema, the project will
   publish a concrete plan for moving stewardship of the RHOFORM mark,
   editorial control of the specification, and the conformance suite to an
   independent non-profit home. The plan will name the home and the timeline.
7. **The covenant only widens.** Once in effect, it may be amended only to
   extend the freedoms it grants. An amendment is published in this file and
   in the release notes at least 90 days before it takes effect. Each release
   is governed by the covenant text in force when that release ships.

**What it does not cover.**

- the hosted part-data service: its scaled corpus, freshness tiers, and bulk
  and export products (commitment 4 still governs how the open toolchain
  relates to it);
- team services;
- the RHOFORM mark itself, beyond commitments 5 and 6;
- third-party material in this repository, which keeps its own terms (see
  [NOTICE](NOTICE) and [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES)).
