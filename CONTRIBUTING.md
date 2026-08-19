# Contributing

Thank you for helping build Rhoform. Rhoform treats reproducibility, verification, and multi-agent collision safety as product requirements.

## Before changing files

1. Read [AGENTS.md](AGENTS.md).
2. Link the work to a Linear issue and reserve exact file or directory paths. If you do not have Linear access, open a GitHub issue so a maintainer can create the internal work item.
3. Use an independent clone and a task branch. Do not share a writable checkout, build directory, cache, database, or development port with another contributor or agent.
4. Keep the change within the issue acceptance criteria and claimed paths.

## Commits and pull requests

- Branch from `main` and open a focused pull request.
- Preserve unrelated work; do not reformat or regenerate files outside the claim.
- Explain what changed, why it changed, and how it was verified.
- Record unavailable checks as blocked or not run; never report them as passing.
- Do not include secrets, proprietary models, restricted datasheets, customer data, or local session artifacts.

## Developer Certificate of Origin

Every non-merge commit must certify the [Developer Certificate of Origin 1.1](https://developercertificate.org/) with a trailer matching the commit author:

```text
Signed-off-by: Your Name <your-email@example.com>
```

The easiest method is:

```sh
git commit -s
```

The DCO workflow checks every pull-request commit.

## Verification

`make all` runs every local gate the repository has (the one stated
exception: checks.yml's pinned-KiCad digest resolution needs network and is
CI-only, as the Makefile's own header records) -- layout and policy, toolchain
pins, schema validation, part-data lint, IR hashing, corpus and classification,
the bake-off and grammar suites, the eval-harness tests, benchmark simulation,
the golden-file harness, and the gate-coverage measurement. Run it before every
handoff; a change scoped to one area can also run its named target first
(`make structure`, `make sim`, `make grammar`, ... -- see the Makefile).
Repository-policy changes must additionally pass:

```sh
sh .agents/skills/verify-rhoform-change/scripts/validate-layout.sh
sh .github/scripts/check-dco.sh --self-test
```

(An earlier revision of this section predated the gate suite and named only
the two policy scripts; the suite is frozen now and `make all` is the bar.)
