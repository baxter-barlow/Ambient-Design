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
