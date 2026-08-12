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

commits=$(git rev-list --reverse --no-merges "$base..$head")

if [ -z "$commits" ]; then
  printf 'DCO check passed: no non-merge commits in range.\n'
  exit 0
fi

failed=0
for commit in $commits; do
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
