#!/usr/bin/env bash
set -euo pipefail

# Runs every benchmark deck (benchmarks/*/netlist.cir) through ngspice in
# batch mode and enforces the Rhoform dynamic-check contract:
#   - the installed ngspice major version matches toolchain/versions.yaml;
#   - each deck declares at least one .meas assertion (a benchmark that
#     measures nothing cannot gate anything);
#   - ngspice exits 0 (quit-code protocol);
#   - the log contains no measurement failure or error lines;
#   - every declared .meas name produced a value in the log;
#   - each deck finishes inside the 60 s budget.
#
# Decks run in sorted order for deterministic output. Logs go to a temp
# directory, never into the repository. Written for bash 3.2+ so it runs
# on stock macOS as well as in CI.
#
# Exit codes: 0 all decks pass (or no decks yet), 1 any deck fails,
# 2 environment failure (ngspice or the toolchain manifest unavailable).

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd -P)
BENCH_DIR="$ROOT/benchmarks"
MANIFEST="$ROOT/toolchain/versions.yaml"
BUDGET_SECONDS=60

fail_env() {
  printf 'sim: FAIL: %s\n' "$1" >&2
  exit 2
}

command -v ngspice >/dev/null 2>&1 \
  || fail_env "ngspice is not installed; an unavailable gate is not a pass."
[ -f "$MANIFEST" ] || fail_env "toolchain/versions.yaml is missing."

# Expected major version, read from the manifest's ngspice block so this
# script has no second copy of the pin.
expected_version=$(sed -n '/^ngspice:/,/^[a-z]/p' "$MANIFEST" \
  | grep -m1 -E '^[[:space:]]+version:' \
  | sed -E 's/^[[:space:]]*version:[[:space:]]*"([0-9]+)".*/\1/')
case "$expected_version" in
  '' | *[!0-9]*)
    fail_env "could not read ngspice.version from toolchain/versions.yaml." ;;
esac

actual_banner=$(ngspice --version 2>/dev/null | grep -m1 -o 'ngspice-[0-9]*' || true)
if [ "$actual_banner" != "ngspice-$expected_version" ]; then
  fail_env "ngspice version mismatch: manifest pins ngspice-$expected_version, found ${actual_banner:-unknown}."
fi

deck_list=""
if [ -d "$BENCH_DIR" ]; then
  deck_list=$(find "$BENCH_DIR" -mindepth 2 -maxdepth 2 -type f -name 'netlist.cir' | LC_ALL=C sort)
fi

if [ -z "$deck_list" ]; then
  printf 'sim: no benchmark decks under benchmarks/*/netlist.cir; nothing to run.\n'
  exit 0
fi

# Prefer a timeout binary so a runaway deck is killed; the elapsed-time
# check below enforces the budget even where timeout is unavailable
# (a hung deck then hangs locally, but CI always has timeout).
TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_BIN=timeout
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_BIN=gtimeout
fi

run_ngspice() {
  # $1 = deck directory, $2 = log path. Batch mode with output captured
  # to the log; the deck's cwd is its own directory so relative includes
  # resolve deterministically.
  if [ -n "$TIMEOUT_BIN" ]; then
    (cd "$1" && "$TIMEOUT_BIN" "$BUDGET_SECONDS" ngspice -b netlist.cir -o "$2") >/dev/null 2>&1
  else
    (cd "$1" && ngspice -b netlist.cir -o "$2") >/dev/null 2>&1
  fi
}

log_dir=$(mktemp -d)
trap 'rm -rf "$log_dir"' EXIT

deck_count=0
failed=0
while IFS= read -r deck; do
  [ -n "$deck" ] || continue
  deck_count=$((deck_count + 1))
  deck_dir=$(dirname "$deck")
  case_name=$(basename "$deck_dir")
  log="$log_dir/$case_name.log"

  # The subshell keeps a matchless grep (exit 1) from tripping set -e.
  meas_names=$( (grep -iE '^[[:space:]]*\.meas' "$deck" || true) | awk '{print tolower($3)}' | LC_ALL=C sort -u)
  meas_count=$(printf '%s' "$meas_names" | grep -c . || true)
  if [ "$meas_count" -eq 0 ]; then
    printf 'sim: FAIL: %s declares no .meas assertions; benchmarks must measure something.\n' "$case_name" >&2
    failed=1
    continue
  fi

  start=$SECONDS
  status=0
  run_ngspice "$deck_dir" "$log" || status=$?
  elapsed=$((SECONDS - start))

  if [ "$status" -eq 124 ]; then
    printf 'sim: FAIL: %s exceeded the %ss budget (killed).\n' "$case_name" "$BUDGET_SECONDS" >&2
    failed=1
    continue
  fi
  if [ "$status" -ne 0 ]; then
    printf 'sim: FAIL: %s: ngspice exited %s (quit-code protocol).\n' "$case_name" "$status" >&2
    failed=1
    continue
  fi
  if [ "$elapsed" -gt "$BUDGET_SECONDS" ]; then
    printf 'sim: FAIL: %s took %ss, over the %ss budget.\n' "$case_name" "$elapsed" "$BUDGET_SECONDS" >&2
    failed=1
    continue
  fi
  if grep -iqE 'meas(ure)?[^=]*(fail|error)' "$log"; then
    printf 'sim: FAIL: %s reported measurement failures:\n' "$case_name" >&2
    grep -iE 'meas(ure)?[^=]*(fail|error)' "$log" >&2
    failed=1
    continue
  fi

  missing=0
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    if ! grep -iqE "^[[:space:]]*${name}[[:space:]]*=" "$log"; then
      printf 'sim: FAIL: %s: .meas %s produced no value.\n' "$case_name" "$name" >&2
      missing=1
    fi
  done <<<"$meas_names"
  if [ "$missing" -ne 0 ]; then
    failed=1
    continue
  fi

  printf 'sim: PASS: %s (%s measurement(s), %ss).\n' "$case_name" "$meas_count" "$elapsed"
done <<<"$deck_list"

if [ "$failed" -ne 0 ]; then
  printf 'sim: FAIL: one or more benchmark decks failed.\n' >&2
  exit 1
fi
printf 'sim: PASS: %s deck(s) completed within budget.\n' "$deck_count"
