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
# Overridable ONLY so the self-test can exercise the elapsed-over-budget leg
# without a 61-second sleep. Production callers never set this.
BUDGET_SECONDS=${RHOFORM_SIM_BUDGET_SECONDS:-60}

fail_env() {
  printf 'sim: FAIL: %s\n' "$1" >&2
  exit 2
}

# Every failure path, proven against a sandbox tree with a scripted ngspice.
# ROOT is derived from this script's location, so the RUNNING script
# (mutations included) is copied into the sandbox beside stub checkers; the
# fake ngspice replays whatever the deck's *SIMLOG lines say and exits with
# *SIMEXIT, so each leg of the contract can be forced deterministically.
self_test() {
  local script sandbox bin failures=0
  script=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/$(basename -- "${BASH_SOURCE[0]}")
  sandbox=$(mktemp -d)
  # shellcheck disable=SC2064
  trap "rm -rf '$sandbox'" EXIT

  bin="$sandbox/bin"
  mkdir -p "$bin"
  for tool in bash sh sed grep tr sort awk dirname basename mktemp find \
              cat wc env sleep python3 rm mkdir; do
    path=$(command -v "$tool") && ln -s "$path" "$bin/$tool"
  done
  write_fake_ngspice() {
    # Scripted ngspice: replays the deck's *SIMLOG lines, exits per *SIMEXIT,
    # sleeps per *SIMSLEEP, and reports version 99.
    cat > "$bin/ngspice" <<'FAKE'
#!/bin/bash
if [ "${1:-}" = "--version" ]; then echo "ngspice-99"; exit 0; fi
deck="" ; out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out=$2; shift 2 ;;
    -b) shift ;;
    *) deck=$1; shift ;;
  esac
done
grep '^\*SIMSLEEP' "$deck" >/dev/null && sleep "$(grep -m1 '^\*SIMSLEEP' "$deck" | awk '{print $2}')"
grep '^\*SIMLOG ' "$deck" | sed 's/^\*SIMLOG //' > "$out"
code=$(grep -m1 '^\*SIMEXIT' "$deck" | awk '{print $2}')
exit "${code:-0}"
FAKE
    chmod +x "$bin/ngspice"
  }
  write_fake_ngspice
  # A timeout that never kills: lets the elapsed-time leg fire instead of the
  # kill leg when a deck deliberately overruns a 1-second budget.
  printf '#!/bin/bash\nshift\nexec "$@"\n' > "$bin/timeout"
  chmod +x "$bin/timeout"

  rebuild() {
    # rebuild <pin> -- a sandbox tree whose manifest pins ngspice-<pin>
    rm -rf "$sandbox/tree"
    mkdir -p "$sandbox/tree/tests/benchmarks" "$sandbox/tree/toolchain" \
             "$sandbox/tree/benchmarks/blinker-555" \
             "$sandbox/tree/benchmarks/buck-3v3" \
             "$sandbox/tree/benchmarks/esp32s3-devboard"
    cp "$script" "$sandbox/tree/tests/benchmarks/run-sim.sh"
    printf 'import sys, pathlib\nsys.exit(1 if (pathlib.Path(sys.argv[1]) / "ASSERT_FAIL").exists() else 0)\n' \
      > "$sandbox/tree/tests/benchmarks/check-assertions.py"
    printf 'import sys, pathlib\nsys.exit(1 if (pathlib.Path(sys.argv[1]) / "HAND_FAIL").exists() else 0)\n' \
      > "$sandbox/tree/tests/benchmarks/check-hand-assertions.py"
    printf 'ngspice:\n  version: "%s"\n' "$1" > "$sandbox/tree/toolchain/versions.yaml"
    printf 'deck: netlist.cir\n' > "$sandbox/tree/benchmarks/blinker-555/assertions.yaml"
    printf 'deck: null\n' > "$sandbox/tree/benchmarks/buck-3v3/assertions.yaml"
    printf 'deck: null\n' > "$sandbox/tree/benchmarks/esp32s3-devboard/assertions.yaml"
    printf '* deck\n.meas tran f_hz trig\n*SIMLOG f_hz = 1.0\n.end\n' \
      > "$sandbox/tree/benchmarks/blinker-555/netlist.cir"
  }

  st_cases=0
  expect() {
    # expect <name> <expected-exit> <fragment>; env via EXPECT_ENV
    local name=$1 want=$2 fragment=$3 got=0 out
    st_cases=$((st_cases + 1))
    out=$(env PATH="$bin" $EXPECT_ENV bash "$sandbox/tree/tests/benchmarks/run-sim.sh" 2>&1) || got=$?
    if [ "$got" -eq "$want" ] && printf '%s' "$out" | grep -Fq -- "$fragment"; then
      printf 'self-test ok:   %s\n' "$name"
    else
      printf 'self-test FAIL: %s (exit %s, wanted %s; output: %s)\n' \
        "$name" "$got" "$want" "$out"
      failures=$((failures + 1))
    fi
  }
  EXPECT_ENV=""

  rebuild 99
  expect "a sandbox tree with a scripted ngspice passes" 0 "deck(s) completed"

  rebuild 99; rm "$bin/ngspice"
  expect "a missing ngspice is an environment failure" 2 "ngspice is not installed"
  write_fake_ngspice

  rebuild 99; rm "$sandbox/tree/toolchain/versions.yaml"
  expect "a missing manifest is an environment failure" 2 "versions.yaml is missing"

  rebuild 99; printf 'nonsense: {}\n' > "$sandbox/tree/toolchain/versions.yaml"
  expect "an unreadable version pin is an environment failure" 2 "could not read ngspice.version"

  rebuild 98
  expect "a version mismatch is an environment failure" 2 "version mismatch"

  rebuild 99; rm "$sandbox/tree/benchmarks/buck-3v3/assertions.yaml"
  expect "a required benchmark losing its spec fails" 2 "cannot leave the gate by losing its spec"

  rebuild 99; mkdir "$sandbox/tree/benchmarks/rogue-bench"
  printf '* deck\n.end\n' > "$sandbox/tree/benchmarks/rogue-bench/netlist.cir"
  expect "a benchmark joining without a spec fails" 2 "cannot join the tree ungated"

  rebuild 99; printf 'title: no deck key\n' > "$sandbox/tree/benchmarks/buck-3v3/assertions.yaml"
  expect "a spec that does not say whether it has a deck fails" 2 "declares no \`deck:\`"

  rebuild 99; touch "$sandbox/tree/benchmarks/buck-3v3/HAND_FAIL"
  expect "failing hand-computed assertions fail the gate" 1 "hand-computed assertions do not follow"

  rebuild 99; rm "$sandbox/tree/benchmarks/blinker-555/netlist.cir"
  expect "a declared deck that does not exist fails" 1 "declare a deck that does not exist"

  rebuild 99; printf '* deck with no meas\n*SIMLOG x = 1\n.end\n' \
    > "$sandbox/tree/benchmarks/blinker-555/netlist.cir"
  expect "a deck with no .meas assertions fails" 1 "declares no .meas assertions"

  rebuild 99; printf '*SIMEXIT 124\n.meas tran f_hz trig\n.end\n' \
    > "$sandbox/tree/benchmarks/blinker-555/netlist.cir"
  expect "a killed deck reports the budget" 1 "exceeded the"

  rebuild 99; printf '*SIMEXIT 3\n.meas tran f_hz trig\n.end\n' \
    > "$sandbox/tree/benchmarks/blinker-555/netlist.cir"
  expect "a nonzero ngspice exit fails the quit-code protocol" 1 "ngspice exited 3"

  rebuild 99; printf '*SIMSLEEP 2\n.meas tran f_hz trig\n*SIMLOG f_hz = 1.0\n.end\n' \
    > "$sandbox/tree/benchmarks/blinker-555/netlist.cir"
  EXPECT_ENV="RHOFORM_SIM_BUDGET_SECONDS=1"
  expect "a deck over the elapsed budget fails" 1 "over the"
  EXPECT_ENV=""

  rebuild 99; printf '.meas tran f_hz trig\n*SIMLOG meas f_hz failed badly\n.end\n' \
    > "$sandbox/tree/benchmarks/blinker-555/netlist.cir"
  expect "measurement failures in the log fail" 1 "reported measurement failures"
  rebuild 99; printf '.meas tran f_hz trig\n*SIMLOG meas f_hz failed badly\n.end\n' \
    > "$sandbox/tree/benchmarks/blinker-555/netlist.cir"
  expect "the failing measurement line itself is shown" 1 "failed badly"

  rebuild 99; printf '.meas tran f_hz trig\n*SIMLOG other = 2\n.end\n' \
    > "$sandbox/tree/benchmarks/blinker-555/netlist.cir"
  expect "a .meas that produced no value fails" 1 "produced no value"

  rebuild 99; touch "$sandbox/tree/benchmarks/blinker-555/ASSERT_FAIL"
  expect "failing value assertions fail the gate" 1 "one or more benchmark decks failed"

  if [ "$failures" -ne 0 ]; then
    printf 'sim: SELF-TEST FAILED: %s case(s)\n' "$failures" >&2
    return 1
  fi
  printf 'sim: self-test PASS: %s cases.\n' "$st_cases"
  return 0
}

[ "${1:-}" != "--self-test" ] || { self_test; exit $?; }

command -v ngspice >/dev/null 2>&1 \
  || fail_env "ngspice is not installed; an unavailable gate is not a pass."
[ -f "$MANIFEST" ] || fail_env "toolchain/versions.yaml is missing."

# Expected major version, read from the manifest's ngspice block so this
# script has no second copy of the pin.
# The `|| true` is load-bearing: under pipefail, a manifest with NO ngspice
# block made grep fail the whole pipeline and set -e killed the gate at exit 1
# with no message at all -- the "could not read" report below was unreachable
# for exactly the input it describes. The self-test found this.
expected_version=$(sed -n '/^ngspice:/,/^[a-z]/p' "$MANIFEST" \
  | { grep -m1 -E '^[[:space:]]+version:' || true; } \
  | sed -E 's/^[[:space:]]*version:[[:space:]]*"([0-9]+)".*/\1/')
case "$expected_version" in
  '' | *[!0-9]*)
    fail_env "could not read ngspice.version from toolchain/versions.yaml." ;;
esac

actual_banner=$(ngspice --version 2>/dev/null | grep -m1 -o 'ngspice-[0-9]*' || true)
if [ "$actual_banner" != "ngspice-$expected_version" ]; then
  fail_env "ngspice version mismatch: manifest pins ngspice-$expected_version, found ${actual_banner:-unknown}."
fi

# Which benchmarks MUST have a deck, taken from each benchmark's own
# `assertions.yaml: deck:` key rather than from a list kept here. Without this
# the gate had no idea what it was supposed to run: deleting every deck printed
# "nothing to run" and exited 0, and renaming one just made the run shorter.
# `deck: null` is how benchmark (c) says it deliberately has none.
# Benchmarks that must exist. Enumerating work from assertions.yaml moved the
# source of truth from decks to specs and reproduced the identical defect one
# file to the left: `rm benchmarks/blinker-555/assertions.yaml` printed
# "1 deck(s) completed" and exited 0, and removing all of them printed
# "nothing to run".
REQUIRED_BENCHMARKS="blinker-555 buck-3v3 esp32s3-devboard"
for required in $REQUIRED_BENCHMARKS; do
  [ -f "$BENCH_DIR/$required/assertions.yaml" ] \
    || fail_env "benchmarks/$required/assertions.yaml is missing; a benchmark cannot leave the gate by losing its spec."
done

# The JOINING direction, which the list above cannot see: a benchmark
# directory added with a deck and no spec was skipped by the glob below and
# gated by nothing -- the same additive hole uncollected_tests() closed for
# lang/tests, one directory over.
for joined in "$BENCH_DIR"/*/; do
  [ -d "$joined" ] || continue
  [ -f "$joined/assertions.yaml" ] \
    || fail_env "benchmarks/$(basename "$joined") has no assertions.yaml; a benchmark cannot join the tree ungated."
done

expected_decks=""
missing_decks=""
for spec in "$BENCH_DIR"/*/assertions.yaml; do
  [ -f "$spec" ] || continue
  case_dir=$(dirname "$spec")
  # Same pipefail hazard as the version pin above: without `|| true`, a spec
  # with no `deck:` key at all killed the gate silently instead of reaching
  # the report that names that exact defect.
  declared=$({ grep -m1 -E '^deck:' "$spec" || true; } | sed -E 's/^deck:[[:space:]]*//' | tr -d '"')
  case "$declared" in
    '' )
      fail_env "$(basename "$case_dir")/assertions.yaml declares no \`deck:\`; a benchmark must say whether it has one, so a deleted deck cannot look like a deliberate absence." ;;
    null | ~ )
      # Deck-less, but its hand-computed assertions still have to follow from
      # their own inputs. Until AMB-123 nothing read them at all: rewriting A3
      # to "0.001 >= 99.0" with status PASS left `make sim` green.
      if ! python3 "$SCRIPT_DIR/check-hand-assertions.py" "$case_dir"; then
        printf 'sim: FAIL: %s hand-computed assertions do not follow from their inputs.\n' "$(basename "$case_dir")" >&2
        exit 1
      fi
      continue ;;
  esac
  expected_decks="$expected_decks$case_dir/$declared
"
  [ -f "$case_dir/$declared" ] || missing_decks="$missing_decks  $(basename "$case_dir")/$declared
"
done

if [ -n "$missing_decks" ]; then
  printf 'sim: FAIL: benchmark(s) declare a deck that does not exist:\n%s' "$missing_decks" >&2
  exit 1
fi

deck_list=$(printf '%s' "$expected_decks" | LC_ALL=C sort)

if [ -z "$deck_list" ]; then
  printf 'sim: no benchmark declares a deck; nothing to run.\n'
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

  # THE VALUES, which is the part that was missing. Everything above proves
  # the deck ran; `assertions.yaml` was read by no code in this repository, so
  # a deck could be electrically destroyed — 6.1 Hz against a 0.932-1.051 Hz
  # window — and still print PASS here.
  if ! python3 "$SCRIPT_DIR/check-assertions.py" "$deck_dir" "$log"; then
    failed=1
    continue
  fi

  # No wall-clock in the transcript: the elapsed check above still
  # enforces the budget, but two identical runs must print identical bytes.
  printf 'sim: PASS: %s (%s measurement(s), within budget).\n' "$case_name" "$meas_count"
done <<<"$deck_list"

if [ "$failed" -ne 0 ]; then
  printf 'sim: FAIL: one or more benchmark decks failed.\n' >&2
  exit 1
fi
printf 'sim: PASS: %s deck(s) completed within budget.\n' "$deck_count"
