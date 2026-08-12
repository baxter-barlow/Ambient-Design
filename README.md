# Ambient Design (AED)

Ambient Design is an open-source, bring-your-own-model agentic electronics-design harness: a small declarative DSL, deterministic electrical checks, reproducible simulation, reviewable schematics, part resolution, and KiCad handoff.

The model makes engineering decisions. Deterministic tooling owns parsing, netlist bookkeeping, type checking, simulation, rendering, and file-format emission.

## Status

AED is in its foundation phase. The requirements and v1 roadmap are approved; the compiler and runtime are not implemented yet.

Start with:

- [DSL design requirements](dsl-design-requirements.md)
- [v1 roadmap](v1-roadmap.md)
- [agent development policy](AGENTS.md)

## Project systems

- GitHub contains implementation and executable configuration.
- [Linear](https://linear.app/ambient-labs/project/agentic-electronic-design-cc8a03247964) tracks planned work, ownership, dependencies, and acceptance criteria.
- Notion holds durable architecture, decisions, and research.
- Slack is reserved for meaningful milestones and ecosystem-level blockers.

Public contributors can start with a GitHub issue. Before implementation begins, a maintainer creates or links the corresponding Linear issue and assigns a non-overlapping path claim.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and the repository [agent policy](AGENTS.md). Contributions use the Developer Certificate of Origin and must include a `Signed-off-by` trailer.

## Licensing

Source code and operational configuration are Apache-2.0. Project specifications and research documents use CC-BY-4.0. See [LICENSES.md](LICENSES.md) for the exact boundary.
