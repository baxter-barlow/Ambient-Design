#!/usr/bin/env bash
set -euo pipefail

# Golden-file harness. See tests/golden/README.md for the full contract.
#
#   bash tests/golden/run.sh [case]
#   UPDATE=1 UPDATE_REASON="..." bash tests/golden/run.sh [case]
#
# Cases run in LC_ALL=C sorted order; comparison is byte-exact (diff -rq).
# Written for bash 3.2+ so it runs on stock macOS as well as in CI.
# Exit codes: 0 all pass (or no cases), 1 any case failed, 2 usage or
# environment error.

usage_fail() {
  printf 'golden: FAIL: %s\n' "$1" >&2
  exit 2
}

# Every failure path, proven against sandbox case directories. The RUNNING
# script (mutations included) is copied into the sandbox, because case
# discovery is SCRIPT_DIR-relative; each case asserts exit code AND a message
# fragment so a blanked report line cannot hide behind a surviving exit.
self_test() {
  local script sandbox failures=0
  script=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/$(basename -- "${BASH_SOURCE[0]}")
  sandbox=$(mktemp -d)
  # Expanded NOW: the trap runs after this function's locals are gone, and an
  # unbound $sandbox under set -u turned a passing self-test into exit 1.
  # shellcheck disable=SC2064
  trap "rm -rf '$sandbox'" EXIT

  expect() {
    # expect <name> <expected-exit> <fragment> [args...]; env via EXPECT_ENV
    local name=$1 want=$2 fragment=$3 got=0 out
    shift 3
    out=$(env $EXPECT_ENV bash "$sandbox/run.sh" "$@" 2>&1) || got=$?
    if [ "$got" -eq "$want" ] && printf '%s' "$out" | grep -Fq -- "$fragment"; then
      printf 'self-test ok:   %s\n' "$name"
    else
      printf 'self-test FAIL: %s (exit %s, wanted %s; output: %s)\n' \
        "$name" "$got" "$want" "$out"
      failures=$((failures + 1))
    fi
  }
  EXPECT_ENV=""

  rebuild() {
    rm -rf "$sandbox"
    mkdir "$sandbox"
    cp "$script" "$sandbox/run.sh"
  }
  plant() {
    # plant <case-name> [expected-content] -- driver writes "payload" to out.txt
    mkdir -p "$sandbox/$1"
    printf 'printf %%s payload > "$1/out.txt"\n' > "$sandbox/$1/driver.sh"
    if [ "$#" -gt 1 ]; then
      mkdir -p "$sandbox/$1/expected"
      printf '%s' "$2" > "$sandbox/$1/expected/out.txt"
    fi
  }

  rebuild
  expect "two arguments are usage, not a pass" 2 "usage:" a b
  EXPECT_ENV="UPDATE=1"
  expect "UPDATE=1 without a reason is refused" 2 "UPDATE_REASON"
  EXPECT_ENV=""
  expect "a nonexistent case name is refused" 2 "no such case" ghost
  expect "an empty tree reports no cases and passes" 0 "no cases"

  rebuild; mkdir "$sandbox/case1"
  expect "a case without a driver fails" 1 "has no driver.sh"

  rebuild; mkdir "$sandbox/case1"
  printf 'exit 7\n' > "$sandbox/case1/driver.sh"
  expect "a failing driver fails the case" 1 "driver exited 7"

  rebuild; plant case1
  expect "a case without expected output fails" 1 "has no expected/"

  rebuild; plant case1 payload
  expect "matching output passes" 0 "golden: PASS: case1"

  rebuild; plant case1 "different bytes"
  expect "diverging output fails" 1 "diverges"
  expect "the divergence detail names the differing file" 1 "differ"

  rebuild; plant case1
  EXPECT_ENV="UPDATE=1 UPDATE_REASON=self-test"
  expect "UPDATE regenerates and records the reason" 0 "UPDATED: case1"
  EXPECT_ENV=""
  if [ -f "$sandbox/UPDATES.log" ] && grep -q "self-test" "$sandbox/UPDATES.log" \
      && [ "$(cat "$sandbox/case1/expected/out.txt")" = "payload" ]; then
    printf 'self-test ok:   the ledger and expected/ were written\n'
  else
    printf 'self-test FAIL: the ledger and expected/ were written\n'
    failures=$((failures + 1))
  fi

  if [ "$failures" -ne 0 ]; then
    printf 'golden: SELF-TEST FAILED: %s case(s)\n' "$failures" >&2
    return 1
  fi
  printf 'golden: self-test PASS: 12 cases.\n'
  return 0
}

[ "${1:-}" != "--self-test" ] || { self_test; exit $?; }

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
LEDGER="$SCRIPT_DIR/UPDATES.log"
UPDATE=${UPDATE:-0}
UPDATE_REASON=${UPDATE_REASON:-}

# Deterministic environment for every driver.
export LC_ALL=C
export TZ=UTC
export SOURCE_DATE_EPOCH=0

[ "$#" -le 1 ] || usage_fail "usage: run.sh [case]"

if [ "$UPDATE" = "1" ] && [ -z "$UPDATE_REASON" ]; then
  usage_fail "UPDATE=1 requires a non-empty UPDATE_REASON justification."
fi

if [ "$#" -eq 1 ]; then
  [ -d "$SCRIPT_DIR/$1" ] || usage_fail "no such case: $1"
  case_list="$SCRIPT_DIR/$1"
else
  case_list=$(find "$SCRIPT_DIR" -mindepth 1 -maxdepth 1 -type d | LC_ALL=C sort)
fi

if [ -z "$case_list" ]; then
  printf 'golden: no cases\n'
  exit 0
fi

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

passed=0
failed=0
while IFS= read -r case_dir; do
  [ -n "$case_dir" ] || continue
  case_name=$(basename "$case_dir")
  out_dir="$scratch/$case_name"
  mkdir "$out_dir"

  if [ ! -f "$case_dir/driver.sh" ]; then
    printf 'golden: FAIL: %s has no driver.sh\n' "$case_name" >&2
    failed=$((failed + 1))
    continue
  fi

  status=0
  (cd "$case_dir" && bash driver.sh "$out_dir") || status=$?
  if [ "$status" -ne 0 ]; then
    printf 'golden: FAIL: %s driver exited %s\n' "$case_name" "$status" >&2
    failed=$((failed + 1))
    continue
  fi

  if [ "$UPDATE" = "1" ]; then
    # Regenerate expected/ from the fresh output and record the
    # justification in the ledger; golden bytes never change silently.
    rm -rf "$case_dir/expected"
    mkdir "$case_dir/expected"
    if [ -n "$(ls -A "$out_dir")" ]; then
      cp -R "$out_dir"/. "$case_dir/expected/"
    fi
    printf '%s %s: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$case_name" "$UPDATE_REASON" >>"$LEDGER"
    printf 'golden: UPDATED: %s (reason recorded in UPDATES.log)\n' "$case_name"
    passed=$((passed + 1))
    continue
  fi

  if [ ! -d "$case_dir/expected" ]; then
    printf 'golden: FAIL: %s has no expected/ directory (run with UPDATE=1 to create it)\n' "$case_name" >&2
    failed=$((failed + 1))
    continue
  fi

  if diff -rq "$case_dir/expected" "$out_dir" >"$scratch/$case_name.diff" 2>&1; then
    printf 'golden: PASS: %s\n' "$case_name"
    passed=$((passed + 1))
  else
    printf 'golden: FAIL: %s output diverges from expected/:\n' "$case_name" >&2
    cat "$scratch/$case_name.diff" >&2
    failed=$((failed + 1))
  fi
done <<<"$case_list"

printf 'golden: %s passed, %s failed.\n' "$passed" "$failed"
[ "$failed" -eq 0 ] || exit 1
