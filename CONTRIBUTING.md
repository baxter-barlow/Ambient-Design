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

Run the narrow checks first, then every affected integration and domain gate. At minimum, repository-policy changes must pass:

```sh
sh .agents/skills/verify-rhoform-change/scripts/validate-layout.sh
sh -n .github/scripts/check-dco.sh
```

Implementation-specific commands will be added after the language and toolchain are frozen.
