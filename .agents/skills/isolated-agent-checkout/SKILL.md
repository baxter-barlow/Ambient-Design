---
name: isolated-agent-checkout
description: Prepare and audit a private Git clone, branch, caches, build outputs, databases, and ports for one AED agent. Use before concurrent implementation, risky verification, integration rehearsal, or review whenever another agent may be active or a shared checkout could cause filesystem or Git collisions.
---

# Isolated Agent Checkout

Create a writable environment whose repository metadata and runtime state are not shared with another agent.

## Preflight

1. Confirm a Linear issue contains an active, non-overlapping path claim.
2. Resolve the canonical repository with `git rev-parse --show-toplevel`.
3. Record the immutable base commit and remote URL.
4. Choose an explicit sibling destination containing the issue identifier and agent slug.
5. Confirm the destination does not exist and is not a broad or protected path.

If the source is not a Git repository, stop. Do not run `git init` or bootstrap a repository unless a dedicated Linear issue and the user explicitly authorize it.

## Create the clone

Prefer an independent clone from the canonical remote. If the remote is unavailable and a local clone is authorized, use a non-hardlinked clone. Do not use a Git worktree by default because worktrees share repository metadata.

Create a task branch from the recorded base commit. Use the Linear-provided branch name when available. Verify:

- `git rev-parse --show-toplevel` resolves to the new clone;
- `git rev-parse HEAD` equals the recorded base;
- `git status --short` is empty before work;
- the branch is unique to the issue and agent;
- `git rev-parse --git-common-dir` is inside the private clone.

Update the Linear claim with the absolute clone path, branch, base commit, and integration owner.

## Isolate runtime state

Give the agent private values for every writable runtime surface:

- dependency environment and package cache;
- compiler/build/test output;
- generated AED/KiCad/SPICE artifacts;
- temporary directory and test fixtures;
- database or state files;
- service ports and sockets;
- logs and coverage outputs.

Never point these at the canonical checkout or another agent's directories. Do not copy secrets into the clone; use the approved secret provider or environment mechanism.

## Work and integrate

- Keep changes inside the Linear path claim.
- Fetch in the private clone. Rebase only the agent's private task branch and only when project policy permits it.
- Run verification before handoff.
- Give the integration owner the branch, commits, base, scoped diff, and evidence.
- Let only the integration owner rebase or merge the landing/integration branch or resolve cross-agent conflicts.

Do not delete the clone automatically. Retain it until integration and evidence review are complete; then remove it only with explicit, validated scope.

## Required output

Return the canonical repository, private clone, branch, base commit, isolated runtime paths, integration owner, verification status, and any blocker that prevents safe writes.
