---
name: verify-rhoform-change
description: Select, run, and report proportionate verification for Rhoform instruction, compiler, DSL, electrical typing, part-data, ngspice, KiCad export, determinism, documentation, and release changes. Use after modifying Rhoform artifacts and before handoff, review, merge, issue completion, or any correctness claim.
---

# Verify Rhoform Change

Build an evidence chain from acceptance criteria to executable checks. Never report an unavailable, skipped, or manually inspected gate as passing.

## Classify the change

1. Read the Linear acceptance criteria and inspect the scoped diff.
2. Identify every affected change class and downstream consumer.
3. Read [references/verification-matrix.md](references/verification-matrix.md) for the required evidence.
4. Inspect project manifests, CI, and existing tests to obtain authoritative commands. Do not invent commands from conventions.
5. Add a regression test first for a bug fix when practical.

## Run checks

Run the narrowest fast checks first, followed by every affected integration and project gate. Use a private checkout and private outputs when another agent may be active.

For instruction or skill architecture changes, run:

```sh
sh .agents/skills/verify-rhoform-change/scripts/validate-layout.sh
```

Run the open Agent Skills validator against each changed skill:

```sh
skills-ref validate .agents/skills/<skill-name>
```

If `skills-ref` is unavailable, use a repository-pinned open-spec validator. Host-specific validators such as Codex skill-creator `quick_validate.py` are useful additional checks but are not the portable gate. Mark an unavailable required validator `NOT RUN` or `BLOCKED`. Test scripts with syntax checks and real representative execution.

For product code, preserve the project-defined formatter, linter, type checker, test, determinism, and domain-gate order. Record exact tool versions. Keep network access out of hermetic compile tests.

## Handle failures

- Capture the exact command, exit code, relevant output, environment, and smallest reproducer.
- Fix the cause; do not weaken an assertion, delete a test, hide output, or silently retry with looser simulation settings.
- After two unsuccessful correction attempts on the same cause, stop repeating the approach and record the blocker and alternatives in Linear.
- Mark environment-dependent or unavailable gates as `BLOCKED` or `NOT RUN`, never `PASS`.

## Review the result

Inspect the final scoped diff and confirm:

- no unclaimed paths changed;
- generated and user-owned artifacts remain correctly separated;
- deterministic outputs are stable across clean repeated runs where applicable;
- diagnostics and failure paths are covered;
- no credential, proprietary model, licensed document, or session artifact leaked.

## Publish evidence

Add a concise Linear comment containing:

- commit or filesystem snapshot identity;
- checks run, tool versions, result, and duration;
- regression coverage added;
- skipped or unavailable gates and why;
- residual risk and required reviewer.

Put durable analysis in Notion. Do not create a local verification report.

## Required output

Return one overall result: `PASS`, `FAIL`, or `BLOCKED`, followed by the evidence matrix and the smallest safe next action.
