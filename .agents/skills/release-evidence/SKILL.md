---
name: release-evidence
description: Evaluate an immutable Rhoform milestone or release candidate, assemble reproducibility and acceptance-gate evidence, obtain independent review, and publish the decision through Notion, Linear, and the Ambient Labs Slack channel. Use for milestone gates, freezes, release candidates, readiness claims, or blocked release decisions.
---

# Release Evidence

Produce a traceable release decision, not a celebratory summary. Keep the evidence attached to an immutable candidate and distinguish verified facts from blocked gates.

## Freeze the candidate

1. Resolve the Linear milestone or release issue and its acceptance criteria.
2. Use a clean, isolated clone at an exact commit.
3. Record the commit, branch or tag, dependency locks, toolchain versions, platform, and relevant configuration hashes.
4. Confirm the scoped tree is clean before and after verification.

If the candidate is mutable, the repository is absent, ownership is unclear, or required dependencies are unpinned, return `BLOCKED`.

## Run the gate set

Use `verify-rhoform-change` to execute every change-class gate plus the milestone acceptance script. Regenerate evidence from the frozen candidate after any fix; never splice pre-fix and post-fix results together.

Capture:

- exact commands and exit codes;
- durations and tool versions;
- test, type, lint, format, determinism, and domain-gate results;
- artifact names, sizes, and SHA-256 hashes;
- unavailable gates and environmental limitations;
- waivers, degraded coverage, and residual risks.

Do not promote a static review into runtime evidence. Do not call a partially runnable gate green.

## Obtain independent review

Give a reviewer the candidate identity, acceptance criteria, raw logs or artifacts, and evidence table. Do not lead with the desired conclusion. Resolve findings by creating or updating Linear issues and regenerating the candidate evidence.

Require the reviewer to state `APPROVE`, `REJECT`, or `BLOCKED` with reasons. A missing independent review blocks a release claim when the milestone requires one.

## Publish

Required publication connectors are part of the gate. If Notion is unavailable, do not substitute a local report: return `BLOCKED` and record the pending destination and exact blocker in Linear when possible. If Linear is unavailable, retain the immutable evidence without claiming completion and return `BLOCKED`. If Slack is unavailable for a required milestone update, record the pending channel and blocker in Linear, return `BLOCKED`, and do not claim publication complete.

Create or update a Notion release-evidence page with:

1. candidate identity and scope;
2. acceptance criteria and result;
3. evidence table;
4. artifact hashes;
5. independent review;
6. waivers, blocked gates, and residual risk;
7. release or rollback decision.

Link that page from the Linear milestone or release issue, add the concise outcome, and update status only after the recorded evidence supports it. Do not create a local Markdown report.

For a meaningful milestone, post one concise update in the Ambient Labs Slack channel containing the outcome, candidate, important evidence, remaining risk, and Linear/Notion links. Do not post routine verification runs or duplicate updates.

## Decision

- `PASS`: all required gates passed on the frozen candidate, required review approved, and required publication completed.
- `FAIL`: a required gate failed or review rejected the candidate.
- `BLOCKED`: a required gate, review, or publication could not be completed.

Return the decision, candidate identity, Notion evidence URL, Linear issue, Slack message link when posted, and the smallest safe next action.
