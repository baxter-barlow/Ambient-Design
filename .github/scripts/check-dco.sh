#!/bin/sh
set -eu

usage() {
  printf 'usage: %s <base-commit> [head-commit]\n' "$0" >&2
  exit 2
}

# Every failure path below, proven to fire against throwaway repositories.
# This gate ran for fourteen rounds with no self-test at all, which the
# coverage gate published honestly and nothing acted on; each case asserts
# the exit code AND a message fragment, so blanking a report line cannot
# pass as long as the exit path still fires.
self_test() {
  script=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)/$(basename -- "$0")
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  failures=0

  expect() {
    # expect <name> <expected-exit> <stderr+stdout fragment> <repo> [args...]
    name=$1; want=$2; fragment=$3; repo=$4; shift 4
    got=0
    out=$( (cd "$repo" && "$script" "$@") 2>&1 ) || got=$?
    if [ "$got" -eq "$want" ] && printf '%s' "$out" | grep -Fq -- "$fragment"; then
      printf 'self-test ok:   %s\n' "$name"
    else
      printf 'self-test FAIL: %s (exit %s, wanted %s; output: %s)\n' \
        "$name" "$got" "$want" "$out"
      failures=$((failures + 1))
    fi
  }

  commit() {
    # commit <repo> <subject> [signoff-line]
    msg=$2
    [ -z "${3:-}" ] || msg=$(printf '%s\n\n%s' "$2" "$3")
    git -C "$1" -c user.name='T Author' -c user.email='t@example.invalid' \
      commit -q --allow-empty -m "$msg"
  }

  signed="$tmp/signed"
  git init -q "$signed"
  commit "$signed" root 'Signed-off-by: T Author <t@example.invalid>'
  commit "$signed" second 'Signed-off-by: T Author <t@example.invalid>'
  root_commit=$(git -C "$signed" rev-list --max-parents=0 HEAD)

  unsigned="$tmp/unsigned"
  git init -q "$unsigned"
  commit "$unsigned" root 'Signed-off-by: T Author <t@example.invalid>'
  commit "$unsigned" 'no trailer here'
  unsigned_root=$(git -C "$unsigned" rev-list --max-parents=0 HEAD)

  bare_root="$tmp/bare-root"
  git init -q "$bare_root"
  commit "$bare_root" 'root without signoff'
  commit "$bare_root" second 'Signed-off-by: T Author <t@example.invalid>'
  bare_root_commit=$(git -C "$bare_root" rev-list --max-parents=0 HEAD)

  expect "no arguments is usage, not a pass" 2 "usage:" "$signed"
  expect "an unavailable base commit is an environment failure" \
    2 "base commit" "$signed" 0000000000000000000000000000000000000000
  expect "an unavailable head commit is an environment failure" \
    2 "head commit" "$signed" "$root_commit" 0000000000000000000000000000000000000000
  expect "a fully signed range passes" \
    0 "DCO check passed" "$signed" "$root_commit" HEAD
  expect "a commit without the trailer fails" \
    1 "DCO failed" "$unsigned" "$unsigned_root" HEAD
  expect "the root commit is checked when it is the base" \
    1 "DCO failed" "$bare_root" "$bare_root_commit" HEAD

  DCO_EXEMPT_EXTRA="$bare_root_commit" export DCO_EXEMPT_EXTRA
  expect "a ledgered exemption passes with notice, not silently" \
    0 "DCO exempt:" "$bare_root" "$bare_root_commit" HEAD
  unset DCO_EXEMPT_EXTRA

  if [ "$failures" -ne 0 ]; then
    printf 'dco: SELF-TEST FAILED: %s case(s)\n' "$failures" >&2
    return 1
  fi
  printf 'dco: self-test PASS: 7 cases.\n'
  return 0
}

[ "${1:-}" != "--self-test" ] || { self_test; exit $?; }

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
# Self-test hook: a commit hash cannot be forged into a throwaway repo, so the
# exemption BRANCH is exercisable only by injecting a hash. The override is
# additive-only input to a pass-with-notice path, it announces itself on
# stdout, and the CI workflows that run this script are SHA-pinned and
# parity-checked, so it cannot be smuggled into CI silently.
if [ -n "${DCO_EXEMPT_EXTRA:-}" ]; then
  printf 'DCO exemption list extended via DCO_EXEMPT_EXTRA (self-test hook)\n'
  DCO_EXEMPT="$DCO_EXEMPT $DCO_EXEMPT_EXTRA"
fi

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
