# Rhoform

Rhoform is an open-source, bring-your-own-model agentic electronics-design harness: a small declarative DSL, deterministic electrical checks, reproducible simulation, reviewable schematics, part resolution, and KiCad handoff.

The model makes engineering decisions. Deterministic tooling owns parsing, netlist bookkeeping, type checking, simulation, rendering, and file-format emission.

## Names

The language, the compiler and the CLI are **Rhoform**; sources are `.rhoform`.
The company is Ambient Labs.

Where the work is *tracked* still carries older names, and they are not all the
same name — renaming what ships was one piece of work, and renaming each
tracker is another, each needing its own review:

| Surface | Name today |
|---|---|
| GitHub repository | `baxter-barlow/Ambient-Design` |
| Notion project | Ambient Design |
| Linear project | Agentic Electronic Design |
| `AGENTS.md` title | Agentic Electronic Design: Agent Policy |

Everything the project *ships* — the language, the CLI, diagnostics, schema
`$id`s, the stdlib root, cache directories — says Rhoform.

## Status

Rhoform is in its foundation phase. The requirements and v1 roadmap are approved; the compiler and runtime are not implemented yet.

Start with:

- [DSL design requirements](https://app.notion.com/p/3ba627dbcc42812388cedd16078a691c)
- [v1 roadmap](https://app.notion.com/p/3ba627dbcc428146a8dcd5f52eb2a2c9)
- [Ground-architecture semantics](https://app.notion.com/p/3bd627dbcc42818b88d6da7052b999ca)
- [Package identity and registry rules](https://app.notion.com/p/3bd627dbcc4281ac98f6c28e944991cb)
- [Flux community feedback analysis](https://app.notion.com/p/3ba627dbcc4281118402e1eedd8064a9)
- [Flux product case study](https://app.notion.com/p/3ba627dbcc4280cc9d4bfa82c65cf16b)
- [agent development policy](AGENTS.md)

## Project systems

- GitHub contains implementation and executable configuration.
- [Linear](https://linear.app/ambient-labs/project/agentic-electronic-design-cc8a03247964) tracks planned work, ownership, dependencies, and acceptance criteria.
- [Notion](https://app.notion.com/p/3ba627dbcc428097b5c7ce1b2fc7bd70) holds durable specifications, architecture, decisions, and research.
- Slack is reserved for meaningful milestones and ecosystem-level blockers.

Public contributors can start with a GitHub issue. Before implementation begins, a maintainer creates or links the corresponding Linear issue and assigns a non-overlapping path claim.

## Repository layout

- `benchmarks/` — the three v1 reference designs. Each carries a design rationale, a part list, and its assertion set; the two analog benchmarks also carry an ngspice deck (`benchmarks/<name>/netlist.cir`) whose `.meas` assertions gate simulation behavior in CI.
- `corpus/` — the seeded-bug corpus: externally documented, diagnosed electronics design failures that the static checks are measured against.
- `ir/` — JSON Schemas for the typed netlist IR (`*.schema.json`) with validated examples and expected-invalid controls under `ir/examples/`.
- `parts/` — the D3 part-data schema: the typed, provenance-carrying contract describing a physical component, with real example records and a linter for the cross-reference invariants JSON Schema cannot express.
- `lang/` — the §8-Q1 syntax bake-off: two candidate grammars, the Starlark-restricted-Python baseline, and the corpus each expresses identically. Throwaway prototypes, checked against the IR example and the benchmark BOM so their reference designs are not self-certified.
- `eval/` — the measurement harness: pinned token counting, the AC5 repair-loop trial protocol, exact small-sample statistics, and result capture. Built against gate and model adapters so the syntax bake-off and the later AC5a gate run share one rig.
- `toolchain/` — `versions.yaml`, the single pinned-toolchain manifest every local run and CI job resolves versions from.
- `tests/` — repository gates: layout invariants (`structure/`), schema validation (`schemas/`), the simulation runner (`benchmarks/`), and the golden-file harness (`golden/`).

Run the gates locally with `make check` (layout, schemas, part-data lint), `make sim` (benchmark decks), or `make all`.

Everything in this tree is Apache-2.0 source and operational configuration. Product specifications and research documents are CC-BY-4.0 and live in Notion rather than in the repository; see [LICENSES.md](LICENSES.md) for the exact boundary.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and the repository [agent policy](AGENTS.md). Contributions use the Developer Certificate of Origin and must include a `Signed-off-by` trailer.

## Licensing

Source code and operational configuration are Apache-2.0. Project specifications and research documents use CC-BY-4.0. See [LICENSES.md](LICENSES.md) for the exact boundary.
