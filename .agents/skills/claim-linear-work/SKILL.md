---
name: claim-linear-work
description: Reserve, confirm, hand off, or release exclusive file and directory ownership in the Agentic Electronic Design Linear project. Use before any AED shared-workspace write, when scope expands, when another agent may touch related paths, or when stopping work so concurrent agents do not collide.
---

# Claim Linear Work

Establish a visible, bounded work lease before changing shared AED state. Treat Linear as the ownership ledger; a chat message or local note is not a claim.

## Gather inputs

Obtain:

- the Linear issue identifier, or enough scope to create one;
- the intended owner or agent identity;
- exact repository-relative files and directory prefixes;
- the checkout path and branch, if Git exists;
- acceptance criteria, dependencies, and expected handoff.

Use the Ambient Labs team and the Agentic Electronic Design project. Confirm the connected Linear identity before mutating Linear. If Linear is unavailable, stop before writing.

## Inspect before claiming

1. Fetch the target issue and project.
2. Search active issues and recent comments for every intended path, its ancestors, and its descendants.
3. Inspect the filesystem and Git status without changing either.
4. Identify active agent processes or open files when the workspace is shared.
5. Treat exact, ancestor, descendant, generated-output, and shared-schema overlap as collisions.

Do not claim over another active owner. Ask for a handoff or split the scope into disjoint paths. If ownership is ambiguous, leave the workspace unchanged and record the blocker in Linear.

## Create the claim

Create or update one Linear issue and set it to `In Progress`. Record:

- owner and agent/runtime;
- UTC claim time;
- exact exclusive paths;
- checkout and branch, or `no Git repository`;
- acceptance criteria;
- dependencies and known blockers;
- explicit non-scope paths that must remain untouched.

Use repository-relative paths. A directory claim ends with `/**`. Avoid broad claims such as the repository root unless the task truly owns repository bootstrap and the user approved it.

Re-read the saved issue to confirm the claim is visible before the first filesystem write.

## Maintain the claim

- Update the issue before adding paths or broadening acceptance criteria.
- When work continues across a handoff, session restart, or material pause, re-check overlaps and add the current owner's confirmation with a UTC timestamp before resuming writes.
- Add a concise progress comment when ownership or blockers materially change.
- Keep routine implementation chatter out of Slack.
- Do not assume a stale-looking claim has expired; obtain an explicit handoff.

## Hand off or release

Before stopping, add a Linear comment containing:

- completed and remaining work;
- changed paths and commit or artifact identifiers;
- verification evidence and unavailable gates;
- unresolved risks;
- the next owner, if handed off.

Move the issue to the appropriate state. State that the path claim is released, narrowed, or transferred. Never release a claim while unrecorded shared changes remain.

## Required output

Return the issue identifier and URL, claimed paths, detected collisions, checkout/branch, claim status, and the next safe action.
