# Agentic Electronic Design: Agent Policy

## Scope and mission

This policy applies to every agent working in this workspace. AED is an open-source, bring-your-own-model electronics-design harness centered on a small declarative DSL. The agent makes engineering decisions; deterministic tooling owns parsing, electrical checks, simulation, rendering, part resolution, and export.

At session start, run `git rev-parse --show-toplevel` read-only. If it fails, treat the directory as a planning surface: do not initialize Git, install dependencies, or invent build commands unless a dedicated Linear issue and the user explicitly authorize repository bootstrap.

## Sources of truth

- **Git:** implementation and executable configuration after a canonical repository exists.
- **Linear:** work scope, owner, status, dependencies, acceptance criteria, and exclusive path claims. Use the Ambient Labs team and the Agentic Electronic Design project: https://linear.app/ambient-labs/project/agentic-electronic-design-cc8a03247964
- **Notion:** durable product specifications, architecture, decisions, research, and reports. Start at the Ambient Design project: https://app.notion.com/p/3ba627dbcc428097b5c7ce1b2fc7bd70
- **Slack:** meaningful milestones and ecosystem-level blockers in the Ambient Labs channel. Do not post routine path claims, intermediate notes, or noisy status updates.
- **Local Markdown:** `AGENTS.md`, `CLAUDE.md`, and skill packages are operational configuration. Do not create local reports, handoffs, meeting notes, roadmaps, or duplicate product documentation; put them in Notion.

If sources conflict, stop and surface the conflict in Linear. Do not silently choose the more convenient source.

## Required workflow

1. Read the applicable instruction chain and the relevant Linear issue before acting.
2. Read only the Notion specifications needed for the task; do not rely on stale local summaries for current decisions. If a required specification or connector is unavailable, stop before writing and record the blocker in Linear when possible.
3. Before any write, use `claim-linear-work` to record exact files or directory prefixes in Linear and check for overlaps.
4. Use an independent writable clone for code work whenever another agent may be active. A shared non-Git planning directory is read-only except for explicitly claimed coordination/bootstrap paths.
5. Keep changes inside the claimed paths and acceptance criteria. Stop if the required scope expands.
6. Use `verify-aed-change` to select and run proportionate checks. A missing or unavailable gate is not a pass.
7. Record verification evidence and remaining risk in Linear. Put durable analysis in Notion. Use `release-evidence` for milestone or release decisions.
8. Release or hand off the path claim when work stops.

## Multi-agent safety

- Assume Claude Code, Codex, and other agents may be active concurrently.
- Never write to a path claimed by another active issue. Parent/child path overlap counts as a collision.
- Never share a writable checkout, branch, worktree, build directory, dependency environment, cache, database, generated-output directory, or development port between agents.
- Prefer independent clones. Git worktrees share repository metadata and are not the default isolation boundary.
- Assign one integration owner for each landing branch. Task agents may rebase only their own private task branches when project policy permits. Only the integration owner may rebase or merge a landing/integration branch or resolve cross-agent conflicts.
- Do not modify, delete, stage, revert, format, or commit another agent's work.
- On an unexpected file change, overlapping claim, lock, open editor, or uncertain ownership: stop writes, preserve evidence, and coordinate in Linear.
- Do not use destructive Git or filesystem commands. Never force-push without explicit user authorization.

## Product invariants

- The AED DSL is the circuit-design source of truth. Generated netlists, reports, schematics, and project files are reproducible artifacts.
- Compilation is total, terminating, hermetic, effect-free, deterministic, and offline.
- The DSL contains no placement or routing coordinates in v1.
- AED-owned schematic-side artifacts may be regenerated with divergence protection. A user-owned `.kicad_pcb` is scaffolded once and must never be overwritten.
- Static and dynamic checks produce structured, source-mapped diagnostics. A declared assertion that cannot be measured is gating unless explicitly waived.
- Never silently retry simulation to green, silently re-resolve parts, or hide degraded coverage.
- Keep GPL tools such as KiCad CLI and ngspice at subprocess boundaries; do not link their code into AED.
- Preserve deterministic identities and rename continuity; unledgered identity changes are errors.

## Change boundaries

- Inspect before editing and preserve unrelated work.
- Match established project style once code exists; do not introduce speculative frameworks or abstractions.
- Do not edit generated outputs by hand unless the issue explicitly targets the generator or golden fixture.
- Keep credentials, proprietary models, licensed datasheets, customer data, and local session artifacts out of source, skills, Linear, Notion, and Slack.
- Do not fetch or redistribute vendor artifacts without a recorded source, checksum, and license basis.
- External writes must be necessary for the requested workflow. Draft first when an external message has material organizational impact.

## Definition of done

Work is complete only when:

- the Linear acceptance criteria are satisfied;
- the scoped diff contains no unrelated changes;
- relevant tests, type checks, linters, formatters, determinism checks, and domain gates pass;
- new failure behavior has regression coverage where practical;
- tool versions, commands, results, and unavailable gates are recorded in Linear;
- durable decisions or reports are stored in Notion, not in new local documentation;
- the integration owner has a clear handoff and the path claim is released;
- a meaningful milestone, if reached, is shared once in the Ambient Labs Slack channel.

Do not declare success based only on code inspection. Do not weaken checks to make a failure disappear.

## Skill routing

- **`claim-linear-work`:** required before shared-workspace writes, scope expansion, handoff, or claim release.
- **`isolated-agent-checkout`:** required when preparing a writable checkout for concurrent implementation or review.
- **`verify-aed-change`:** required after a change and before handoff, review, merge, or completion.
- **`release-evidence`:** required for milestone gates, release candidates, freeze decisions, or public readiness claims.

Canonical project skills live in `.agents/skills/`. `.claude/skills/` exposes reviewed links to the same directories; never maintain copied skill bodies. Keep each skill focused and portable, with only `name` and `description` in `SKILL.md` frontmatter.

## Policy maintenance

Change this file or a project skill only through a dedicated Linear issue with independent review. Keep this file concise and universal; move conditional procedures, examples, and detailed references into focused skills. Use technical controls such as CI, hooks, permissions, and branch protection for rules that require enforcement.
