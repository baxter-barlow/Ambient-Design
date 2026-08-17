#!/bin/sh
set -eu

usage() {
  printf 'usage: %s <base-commit> [head-commit]\n' "$0" >&2
  exit 2
}

[ "$#" -ge 1 ] && [ "$#" -le 2 ] || usage

base=$1
head=${2:-HEAD}

git cat-file -e "$base^{commit}" 2>/dev/null || {
  printf 'DCO check failed: base commit %s is unavailable.\n' "$base" >&2
  exit 2
}
git cat-file -e "$head^{commit}" 2>/dev/null || {
  printf 'DCO check failed: head commit %s is unavailable.\n' "$head" >&2
  exit 2
}

# `base..head` EXCLUDES base. When the caller passes the root commit as base —
# which `make policy` does, and which is the only way to check a repository with
# no merge commits — the root itself is never examined. In this repository the
# root is the one commit with no Signed-off-by, so the gate was structurally
# blind to its only failure. Including base when it IS the root closes that.
if [ "$base" = "$(git rev-list --max-parents=0 "$head" | head -n1)" ]; then
  commits=$(git rev-list --reverse --no-merges "$head")
else
  commits=$(git rev-list --reverse --no-merges "$base..$head")
fi

# Commits that predate the DCO requirement, each recorded with why. A ledger,
# not a wildcard: an exemption nobody can enumerate is not an exemption, it is
# an unenforced rule. GitHub creates the root commit of a repository initialised
# through its UI, with no trailer and no way to add one without rewriting the
# history every later commit is chained to.
DCO_EXEMPT="199bdcffee2b65b34975b01b7ce47091a141746c"

if [ -z "$commits" ]; then
  printf 'DCO check passed: no non-merge commits in range.\n'
  exit 0
fi

failed=0
for commit in $commits; do
  case " $DCO_EXEMPT " in
    *" $commit "*)
      printf 'DCO exempt:  %s %s (predates the requirement; see check-dco.sh)\n' \
        "$(git rev-parse --short "$commit")" "$(git show -s --format=%s "$commit")"
      continue ;;
  esac
  author_name=$(git show -s --format=%an "$commit")
  author_email=$(git show -s --format=%ae "$commit")
  expected="Signed-off-by: $author_name <$author_email>"
  trailers=$(git show -s --format=%B "$commit" | git interpret-trailers --parse)

  if printf '%s\n' "$trailers" | grep -Fxi -- "$expected" >/dev/null; then
    printf 'DCO passed: %.12s %s\n' "$commit" "$author_name"
  else
    printf 'DCO failed: %.12s requires exactly: %s\n' "$commit" "$expected" >&2
    failed=1
  fi
done

[ "$failed" -eq 0 ] || exit 1
printf 'DCO check passed for all non-merge commits.\n'
