#!/usr/bin/env bash
set -euo pipefail

# Enforces Rhoform monorepo layout invariants:
#   - top-level directories are limited to a declared allowlist;
#   - root-level Markdown is limited to operational files (product specs
#     and research live in Notion per LICENSES.md);
#   - required governance and toolchain files exist;
#   - every JSON file under ir/ parses (schema well-formedness beyond
#     parsing is the schemas gate, tests/schemas/validate-schemas.py);
#   - toolchain/versions.yaml parses as YAML when PyYAML is available.
#
# Runnable locally with bash and python3; jq is used only as a fallback
# JSON parser when python3 is absent. Exit 0 on pass, 1 on violation,
# 2 when no JSON parser is available (an unavailable gate is not a pass).

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd -P)

# Declared allowlists. Extend these through a dedicated Linear issue, not
# ad hoc: an undeclared top-level directory is a layout violation.
ALLOWED_DIRS=".agents .claude .git .github benchmarks corpus eval ir lang parts tests toolchain"
ALLOWED_ROOT_MD="AGENTS.md CLAUDE.md CONTRIBUTING.md LICENSES.md README.md"
REQUIRED_FILES="AGENTS.md CLAUDE.md CONTRIBUTING.md LICENSE LICENSES.md NOTICE README.md toolchain/versions.yaml"

# Directories whose JSON must parse. Keep in step with SCHEMA_ROOTS in
# tests/schemas/validate-schemas.py: this gate proves the bytes are JSON,
# that one proves the JSON means something.
JSON_ROOTS="ir parts eval lang"

# Every failure path, proven against a sandbox repository with stub gates.
# ROOT is this script's grandparent, so the RUNNING script (mutations
# included) is copied into the sandbox; the transcript engine talks to stub
# gates that print fixture summaries, and the environment legs run under
# restricted PATH directories. Each case asserts the exit code AND one
# message fragment per report line, so blanking any line goes red.
self_test() {
  local st_script st_tmp st_root st_bin st_path st_failures=0
  st_script=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/$(basename -- "${BASH_SOURCE[0]}")
  st_tmp=$(mktemp -d)
  # shellcheck disable=SC2064
  trap "rm -rf '$st_tmp'" EXIT
  st_root="$st_tmp/tree"

  st_bin="$st_tmp/bin"
  mkdir -p "$st_bin"
  local tool tpath
  for tool in bash sh python3 git find sort sed grep awk dirname basename \
              cat mktemp rm mkdir ln cp wc env; do
    tpath=$(command -v "$tool") && ln -s "$tpath" "$st_bin/$tool"
  done
  # Variant PATHs, one per environment leg.
  cp -R "$st_bin" "$st_tmp/bin-noparser"; rm -f "$st_tmp/bin-noparser/python3"
  cp -R "$st_bin" "$st_tmp/bin-nogit";    rm -f "$st_tmp/bin-nogit/git"
  cp -R "$st_bin" "$st_tmp/bin-noyaml";   rm -f "$st_tmp/bin-noyaml/python3"
  printf '#!/bin/bash\nfor a in "$@"; do case "$a" in *"import yaml"*) exit 1;; esac; done\nexec %s "$@"\n' \
    "$(command -v python3)" > "$st_tmp/bin-noyaml/python3"
  chmod +x "$st_tmp/bin-noyaml/python3"
  cp -R "$st_bin" "$st_tmp/bin-nomd";     rm -f "$st_tmp/bin-nomd/find"
  printf '#!/bin/bash\nfor a in "$@"; do case "$a" in "*.md") exit 0;; esac; done\nexec %s "$@"\n' \
    "$(command -v find)" > "$st_tmp/bin-nomd/find"
  chmod +x "$st_tmp/bin-nomd/find"
  cp -R "$st_bin" "$st_tmp/bin-nojson";   rm -f "$st_tmp/bin-nojson/find"
  printf '#!/bin/bash\nfor a in "$@"; do case "$a" in "*.json") exit 0;; esac; done\nexec %s "$@"\n' \
    "$(command -v find)" > "$st_tmp/bin-nojson/find"
  chmod +x "$st_tmp/bin-nojson/find"

  st_write_retired() {
    # st_write_retired <self-test-exit> <run-exit>
    printf 'import sys\nis_self = "--self-test" in sys.argv\nif not is_self and %s:\n    print("planted retired name", file=sys.stderr)\nsys.exit(%s if is_self else %s)\n' \
      "$2" "$1" "$2" > "$st_root/tests/structure/check-retired-names.py"
  }
  st_write_transcript_stubs() {
    printf 'import sys\nprint("stub-corpus: self-test PASS: 1 cases." if "--self-test" in sys.argv else "stub-corpus: PASS: fixture summary.")\n' \
      > "$st_root/tests/corpus/check-classification.py"
    printf 'import sys\nprint("stub-ir: self-test PASS: 1 cases." if "--self-test" in sys.argv else "stub-ir: PASS: fixture summary.")\n' \
      > "$st_root/tests/ir/check-hashes.py"
    printf '#!/usr/bin/env bash\necho "sim-assert: PASS: blinker-555: fixture ok"\necho "sim-assert: PASS: buck-3v3: fixture ok"\n' \
      > "$st_root/tests/benchmarks/run-sim.sh"
    printf 'import sys\nprint("hand-assert: PASS: esp32s3-devboard: fixture " + sys.argv[1].split("/")[-1])\n' \
      > "$st_root/tests/benchmarks/check-hand-assertions.py"
  }
  st_write_logs() {
    printf 'stub-corpus: self-test PASS: 1 cases.\nstub-corpus: PASS: fixture summary.\n' \
      > "$st_root/corpus/validation.log"
    printf 'stub-ir: self-test PASS: 1 cases.\nstub-ir: PASS: fixture summary.\n' \
      > "$st_root/ir/validation.log"
    printf 'sim-assert: PASS: blinker-555: fixture ok\n' \
      > "$st_root/benchmarks/blinker-555/validation.log"
    printf 'sim-assert: PASS: buck-3v3: fixture ok\n' \
      > "$st_root/benchmarks/buck-3v3/validation.log"
    printf 'hand-assert: PASS: esp32s3-devboard: fixture esp32s3-devboard\n' \
      > "$st_root/benchmarks/esp32s3-devboard/validation.log"
  }

  rm -rf "$st_root"
  mkdir -p "$st_root/tests/structure" "$st_root/tests/corpus" \
           "$st_root/tests/ir" "$st_root/tests/benchmarks" \
           "$st_root/toolchain" "$st_root/corpus" "$st_root/ir" \
           "$st_root/benchmarks/blinker-555" "$st_root/benchmarks/buck-3v3" \
           "$st_root/benchmarks/esp32s3-devboard"
  local f i
  for f in AGENTS.md CLAUDE.md CONTRIBUTING.md LICENSE LICENSES.md NOTICE README.md; do
    printf 'fixture\n' > "$st_root/$f"
  done
  printf 'pin: 1\n' > "$st_root/toolchain/versions.yaml"
  i=0
  while [ "$i" -lt 50 ]; do
    printf '{}' > "$st_root/ir/f$i.json"
    i=$((i + 1))
  done
  cp "$st_script" "$st_root/tests/structure/check-layout.sh"
  st_write_retired 0 0
  st_write_transcript_stubs
  st_write_logs
  git init -q "$st_root"
  git -C "$st_root" add .

  st_path="$st_bin"
  st_expect() {
    # st_expect <name> <expected-exit> <fragment>... -- one fragment per
    # report line the fixture should produce, so each line is its own pin.
    local name=$1 want=$2 got=0 out ok=yes frag
    shift 2
    out=$(env PATH="$st_path" bash "$st_root/tests/structure/check-layout.sh" 2>&1) || got=$?
    [ "$got" -eq "$want" ] || ok=no
    for frag in "$@"; do
      printf '%s' "$out" | grep -Fq -- "$frag" || ok=no
    done
    if [ "$ok" = yes ]; then
      printf 'self-test ok:   %s\n' "$name"
    else
      printf 'self-test FAIL: %s (exit %s, wanted %s; output: %s)\n' \
        "$name" "$got" "$want" "$out"
      st_failures=$((st_failures + 1))
    fi
  }

  st_expect "a well-formed sandbox repository passes" 0 "PASS: Rhoform layout"

  st_path="$st_tmp/bin-noparser"
  st_expect "no JSON parser is an environment failure" 2 "neither python3 nor jq"
  st_path="$st_tmp/bin-nogit"
  st_expect "a missing git fails the retired-name scan closed" 2 "retired-name scan needs python3 and git"
  st_path="$st_tmp/bin-noyaml"
  st_expect "missing PyYAML is an environment failure" 2 "PyYAML is required"
  st_path="$st_tmp/bin-nomd"
  st_expect "a silent Markdown enumeration trips the floor" 1 "so the enumeration did not run"
  st_path="$st_tmp/bin-nojson"
  st_expect "a silent JSON enumeration trips the floor" 1 "expected at least 50"
  st_path="$st_bin"

  mkdir "$st_root/rogue"
  st_expect "an undeclared top-level directory fails" 1 "unexpected top-level directory: rogue"
  rmdir "$st_root/rogue"

  printf 'rogue\n' > "$st_root/.gitignore"
  mkdir "$st_root/rogue"
  git -C "$st_root" add .gitignore
  st_expect "a git-ignored transient directory is tolerated" 0 "PASS: Rhoform layout"
  rmdir "$st_root/rogue"; git -C "$st_root" rm -q --cached .gitignore; rm "$st_root/.gitignore"

  printf 'notes\n' > "$st_root/HANDOFF.md"
  st_expect "an undeclared root Markdown file fails" 1 "unexpected root Markdown file: HANDOFF.md"
  rm "$st_root/HANDOFF.md"

  mv "$st_root/LICENSE" "$st_root/LICENSE.away"
  st_expect "a missing required file fails" 1 "required file is missing: LICENSE"
  mv "$st_root/LICENSE.away" "$st_root/LICENSE"

  printf '{broken' > "$st_root/ir/f0.json"
  st_expect "a JSON file that does not parse fails" 1 "does not parse as JSON: ir/f0.json"
  printf '{}' > "$st_root/ir/f0.json"

  st_write_retired 1 0
  st_expect "a failing retired-name self-test fails" 1 "retired-name scan's own self-test failed"
  st_write_retired 0 1
  st_expect "a retired-name hit fails and its report passes through" 1 "planted retired name"
  st_write_retired 0 0

  printf 'a: [unclosed\n' > "$st_root/toolchain/versions.yaml"
  st_expect "an unparseable toolchain manifest fails" 1 "does not parse as YAML"
  printf 'pin: 1\n' > "$st_root/toolchain/versions.yaml"

  printf 'untracked\n' > "$st_root/benchmarks/blinker-555/validation-extra.log"
  st_expect "an untracked evidence file fails" 1 "not tracked" \
    "deliberately authored deliverables"
  git -C "$st_root" add benchmarks/blinker-555/validation-extra.log
  st_expect "a tracked evidence file outside both lists fails" 1 \
    "in neither TRANSCRIPT_PAIRS nor NO_SUMMARY_EVIDENCE"
  git -C "$st_root" rm -q --cached benchmarks/blinker-555/validation-extra.log
  rm "$st_root/benchmarks/blinker-555/validation-extra.log"

  printf 'import sys\n' > "$st_root/tests/corpus/check-classification.py"
  st_expect "a gate that prints no summary fails its pair" 1 "prints no PASS summary"
  st_write_transcript_stubs

  printf 'stub-corpus: self-test PASS: 1 cases.\nstub-corpus: PASS: fixture summary.\nstub-corpus: PASS: stale copy.\n' \
    > "$st_root/corpus/validation.log"
  st_expect "a duplicated quoted summary fails" 1 "Only the first is read" \
    "stale copy appended below a fresh one"
  st_write_logs

  printf 'stub-corpus: self-test PASS: 1 cases.\n' > "$st_root/corpus/validation.log"
  st_expect "a deleted quoted summary fails" 1 "carries no \"stub-corpus: PASS\" line" \
    "Deleting the quoted summary"
  st_write_logs

  printf 'stub-corpus: self-test PASS: 1 cases.\nstub-corpus: self-test PASS: 1 cases.\nstub-corpus: PASS: fixture summary.\n' \
    > "$st_root/corpus/validation.log"
  st_expect "a duplicated self-test summary fails" 1 "self-test PASS\" lines; only the first is read"
  st_write_logs

  printf 'stub-corpus: self-test PASS: 99 cases.\nstub-corpus: PASS: fixture summary.\n' \
    > "$st_root/corpus/validation.log"
  st_expect "a stale self-test summary fails" 1 \
    "quotes a self-test summary the gate no longer prints" "99 cases"
  st_write_logs

  printf 'stub-corpus: PASS: fixture summary.\n' > "$st_root/corpus/validation.log"
  st_expect "a deleted self-test summary fails" 1 "self-test PASS\" line to compare"
  st_write_logs

  printf 'stub-corpus: self-test PASS: 1 cases.\nstub-corpus: PASS: stale summary.\n' \
    > "$st_root/corpus/validation.log"
  st_expect "a stale quoted summary fails" 1 \
    "quotes a summary the gate no longer prints" \
    "stale summary" "is not evidence"
  st_write_logs

  mv "$st_root/ir/validation.log" "$st_tmp/ir-log.away"
  st_expect "a skipped pair trips the transcript floor" 1 \
    "reconciled 5 evidence summary line(s)" "quietly checks nothing"

  printf 'hand-assert: PASS: esp32s3-devboard: stale tally\n' \
    > "$st_root/benchmarks/esp32s3-devboard/validation.log"
  st_expect "a stale summary in an ARGUMENT-carrying pair fails" 1 \
    "quotes a summary the gate no longer prints" "stale tally"
  st_write_logs
  mv "$st_tmp/ir-log.away" "$st_root/ir/validation.log"

  if [ "$st_failures" -ne 0 ]; then
    printf 'layout: SELF-TEST FAILED: %s case(s)\n' "$st_failures" >&2
    return 1
  fi
  printf 'layout: self-test PASS: 25 cases.\n'
  return 0
}

[ "${1:-}" != "--self-test" ] || { self_test; exit $?; }

json_parser=""
if command -v python3 >/dev/null 2>&1; then
  json_parser="python3"
elif command -v jq >/dev/null 2>&1; then
  json_parser="jq"
else
  printf 'FAIL: neither python3 nor jq is available; the JSON parse gate cannot run.\n' >&2
  exit 2
fi

parse_json_batch() {
  # One parser process for the whole file list on stdin, printing the first
  # file that fails. One python3 per FILE made this gate's dominant cost a
  # spawn loop -- 67 interpreter startups to parse 67 small files -- and made
  # the self-test too slow to mutation-test.
  if [ "$json_parser" = "python3" ]; then
    python3 -c '
import json, sys
for path in sys.stdin.read().splitlines():
    if not path:
        continue
    try:
        json.load(open(path, encoding="utf-8"))
    except Exception:
        print(path)
        sys.exit(1)
' 2>/dev/null
  else
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      jq empty "$f" >/dev/null 2>&1 || { printf '%s\n' "$f"; return 1; }
    done
  fi
}

# Top-level directories must come from the allowlist. Missing directories
# are fine (the tree grows over time); unexpected ones are not.
#
# Git-ignored directories are skipped. The layout invariant is about what
# the REPOSITORY contains, and a contributor's transient tool cache
# (.pytest_cache, .ruff_cache, .venv) is not part of it — failing their
# `make check` because they ran a test runner would be a false positive
# that teaches people to distrust the gate. An untracked directory that is
# NOT ignored is still a violation: that is one somebody is about to
# commit, which is exactly the case this check exists for.
#
# When git is unavailable (a tarball export, say) every directory is
# checked, which is the conservative direction.
ignored() {
  command -v git >/dev/null 2>&1 || return 1
  git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || return 1
  git -C "$ROOT" check-ignore -q -- "$1" 2>/dev/null
}

while IFS= read -r dir; do
  name=$(basename "$dir")
  case " $ALLOWED_DIRS " in
    *" $name "*) continue ;;
  esac
  ignored "$dir" && continue
  fail "unexpected top-level directory: $name"
done < <(find "$ROOT" -mindepth 1 -maxdepth 1 -type d | LC_ALL=C sort)

# Root-level Markdown is operational configuration only. Product specs
# and research documents belong in Notion (see LICENSES.md).
md_count=0
while IFS= read -r file; do
  name=$(basename "$file")
  md_count=$((md_count + 1))
  case " $ALLOWED_ROOT_MD " in
    *" $name "*) ;;
    *)
      # On its own line so the coverage mutation can blank it without
      # eating the arm's `;;` -- a site that can only be blanked into a
      # syntax error is scored as unpinned.
      fail "unexpected root Markdown file: $name (specs live in Notion per LICENSES.md)"
      ;;
  esac
done < <(find "$ROOT" -mindepth 1 -maxdepth 1 -type f -name '*.md' | LC_ALL=C sort)

# Required governance and toolchain files.
for rel in $REQUIRED_FILES; do
  [ -f "$ROOT/$rel" ] || fail "required file is missing: $rel"
done

# Every JSON file under a declared JSON root must parse. Schema semantics
# are checked by the schemas gate; a file that does not even parse fails
# here first. Roots that do not exist yet are skipped.
json_files=""
json_count=0
for json_root in $JSON_ROOTS; do
  [ -d "$ROOT/$json_root" ] || continue
  while IFS= read -r file; do
    json_count=$((json_count + 1))
    json_files="$json_files$file
"
  done < <(find "$ROOT/$json_root" -type f -name '*.json' | LC_ALL=C sort)
done
bad_json=$(printf '%s' "$json_files" | parse_json_batch) \
  || fail "does not parse as JSON: ${bad_json#"$ROOT"/}"

# Retired names must not come back. That check grew two matchers and a set
# of exclusions, so it lives in its own script with its own self-test rather
# than as embedded Python here - the same shape as the part linter and the IR
# hash gate, and for the same reason: a check that silently stopped firing
# must fail loudly instead of reporting a clean sweep.
# It used to print WARN and exit 0 when git or python3 was missing, which is
# the same defect the sibling gates were written to avoid: an unavailable gate
# reported as a pass. AGENTS.md is explicit, and so is this script's own
# header. It exits 2 now.
if ! command -v git >/dev/null 2>&1 || [ "$json_parser" != "python3" ]; then
  printf 'FAIL: the retired-name scan needs python3 and git, and neither is optional; an unavailable gate is not a pass.\n' >&2
  exit 2
fi
python3 "$SCRIPT_DIR/check-retired-names.py" --self-test >/dev/null \
  || fail "the retired-name scan's own self-test failed"
python3 "$SCRIPT_DIR/check-retired-names.py" >/dev/null || exit 1

# The toolchain manifest must parse as YAML. This used to be "deferred to CI,
# where it always runs" — nothing enforced "always runs", and with PyYAML
# absent the gate printed PASS having parsed nothing. Deleting the pip step in
# checks.yml would have switched it off silently.
if ! python3 -c 'import yaml' 2>/dev/null; then
  printf 'FAIL: PyYAML is required to parse toolchain/versions.yaml; install the pin (python3 -m pip install pyyaml==6.0.2). An unavailable gate is not a pass.\n' >&2
  exit 2
fi
python3 -c 'import sys, yaml; yaml.safe_load(open(sys.argv[1], encoding="utf-8"))' \
  "$ROOT/toolchain/versions.yaml" 2>/dev/null \
  || fail "toolchain/versions.yaml does not parse as YAML"

# Evidence files must be IN the repository. `.gitignore`'s `*.log` was written
# for ngspice scratch output and silently swallowed five `validation.log` files
# that nine tracked documents cite as committed evidence — including the one
# carrying a retraction of fabricated evidence — plus the golden harness's
# tamper-evidence ledger. `git add` on an ignored path does nothing unless
# forced, so nothing warned at commit time. This is the recurrence guard.
untracked_evidence=""
while IFS= read -r evidence; do
  [ -n "$evidence" ] || continue
  rel=${evidence#"$ROOT"/}
  git -C "$ROOT" ls-files --error-unmatch "$rel" >/dev/null 2>&1 \
    || untracked_evidence="$untracked_evidence  $rel
"
done < <(find "$ROOT" -type f \( -name 'validation*.log' -o -name 'UPDATES.log' \) \
           -not -path "$ROOT/.git/*" -not -path "$ROOT/.claude/*" | LC_ALL=C sort)
if [ -n "$untracked_evidence" ]; then
  printf 'FAIL: evidence file(s) exist on disk but are not tracked:\n%s' "$untracked_evidence" >&2
  printf 'These are deliberately authored deliverables, not scratch output. Track them, or the claims that cite them are unverifiable by anyone but their author.\n' >&2
  exit 1
fi

# Floor assertions on the counts. Every enumeration above uses `done < <(find
# ...)`, and a failing process substitution does not propagate under `set -e`:
# with `find` off PATH the gate printed "0 root Markdown files, 0 JSON files"
# and exited 0. A self-reported statistic is not an assertion.
[ "$md_count" -ge 5 ] || fail "counted $md_count root Markdown files; expected at least 5, so the enumeration did not run"
[ "$json_count" -ge 50 ] || fail "counted $json_count JSON files under [$JSON_ROOTS]; expected at least 50, so the enumeration did not run"

# Evidence transcripts that quote a gate's own summary line must quote the line
# that gate prints TODAY. corpus/validation.log certified "22 in scope" while
# the gate printed 21 -- the denominator moved 100 minutes after the file was
# written, in a commit titled "loudly", and nothing read the file, so it
# outlived the fix. Each pair is (evidence file, command whose summary it quotes).
transcripts_checked=0
# Every evidence file that transcribes a gate summary. The list used to hold
# two of the four, and the floor was the size of the LIST rather than of the
# population -- so the two benchmark transcripts quoted a sim-assert line the
# gate had stopped printing, and nothing could notice.
TRANSCRIPT_PAIRS="corpus/validation.log:tests/corpus/check-classification.py
ir/validation.log:tests/ir/check-hashes.py
benchmarks/blinker-555/validation.log:tests/benchmarks/run-sim.sh:sim-assert: PASS: blinker-555:
benchmarks/buck-3v3/validation.log:tests/benchmarks/run-sim.sh:sim-assert: PASS: buck-3v3:
benchmarks/esp32s3-devboard/validation.log:tests/benchmarks/check-hand-assertions.py benchmarks/esp32s3-devboard:hand-assert: PASS: esp32s3-devboard:"

# Evidence files that genuinely quote no live gate summary, with the reason
# held here so an entry is a decision rather than an escape:
#   - buck-3v3/validation-corners.log is re-derived block by block by
#     tests/benchmarks/check-corners.py, which re-runs each modified deck; it
#     quotes no summary line, so there is nothing for THIS engine to compare.
# The esp32s3 log sat in this list for one round with a reason that was
# FALSE -- it quotes the live hand-assert summary at its line 169 -- which is
# exactly the drift the pair engine exists to catch. It is a pair now.
NO_SUMMARY_EVIDENCE="benchmarks/buck-3v3/validation-corners.log"

# THE PAIR LIST IS A POPULATION CLAIM, and until now it was hand-maintained:
# a new evidence file quoting a gate summary joined no list and was checked by
# nothing, which is exactly how the first version sat at two of four. Every
# evidence file found on disk must now be in one list or the other.
while IFS= read -r evidence_path; do
  [ -n "$evidence_path" ] || continue
  rel=${evidence_path#"$ROOT"/}
  accounted=""
  while IFS= read -r pair; do
    [ "${pair%%:*}" = "$rel" ] && accounted=paired
  done <<<"$TRANSCRIPT_PAIRS"
  while IFS= read -r ledgered; do
    [ "$ledgered" = "$rel" ] && accounted=ledgered
  done <<<"$NO_SUMMARY_EVIDENCE"
  [ -n "$accounted" ] || fail "$rel is an evidence file in neither TRANSCRIPT_PAIRS nor NO_SUMMARY_EVIDENCE; if it quotes a gate summary, pair it, and if it quotes none, ledger it with the reason -- an unlisted transcript is how two of four went unchecked"
done < <(find "$ROOT" -type f \( -name 'validation*.log' -o -name 'UPDATES.log' \) \
           -not -path "$ROOT/.git/*" -not -path "$ROOT/.claude/*" | LC_ALL=C sort)

while IFS= read -r pair; do
  evidence="$ROOT/${pair%%:*}"
  rest="${pair#*:}"
  # An optional third field pins WHICH summary line to compare, for a command
  # that prints one per benchmark; the command field may carry ONE
  # repo-relative argument after a space (check-hand-assertions needs its
  # benchmark directory).
  case "$rest" in
    *:*) command_spec="${rest%%:*}"; pattern="${rest#*:}" ;;
    *) command_spec="$rest"; pattern="" ;;
  esac
  command_path=${command_spec%% *}
  command_arg=""
  [ "$command_spec" = "$command_path" ] || command_arg="$ROOT/${command_spec#* }"
  command="$ROOT/$command_path"
  [ -f "$evidence" ] && [ -f "$command" ] || continue
  # BOTH summary lines. The first version grepped for "$prefix: PASS", which
  # does not match "$prefix: self-test PASS", so the self-test line above it
  # was free -- and both files were stale on exactly that line, by 4 and 27
  # checks. The round-9 fix reconciled the line the round-9 defect was on.
  if [ -n "$pattern" ]; then
    case "$command" in
      *.sh) fresh=$(bash "$command" ${command_arg:+"$command_arg"} 2>/dev/null | grep -m1 -- "$pattern" || true) ;;
      *)    fresh=$(python3 "$command" ${command_arg:+"$command_arg"} 2>/dev/null | grep -m1 -- "$pattern" || true) ;;
    esac
  else
    fresh=$(python3 "$command" 2>/dev/null | grep -m1 ": PASS" || true)
  fi
  # Only the pattern-less pairs compare a self-test line; running the
  # command's --self-test for pattern pairs burned a full self-test run
  # whose output the branch below then discarded (round 16).
  fresh_self=""
  [ -n "$pattern" ] || fresh_self=$(python3 "$command" --self-test 2>/dev/null | grep -m1 ": self-test PASS" || true)
  if [ -z "$fresh" ]; then
    # $command_path, not ${pair##*:}: for a pattern-carrying pair the
    # latter is the tail of the grep pattern, so the report named no
    # command at all (round 18).
    printf 'FAIL: %s prints no PASS summary, so %s is compared to nothing.\n' "$command_path" "${pair%%:*}" >&2
    exit 1
  fi
  if [ -n "$pattern" ]; then prefix="$pattern"; else prefix="${fresh%%:*}"; fi
  # Anchor-free and whitespace-tolerant. `^prefix: PASS` let a transcript
  # escape by indenting the line by one space or deleting it outright, and the
  # `[ -n "$quoted" ]` guard then failed OPEN -- in a script whose own comment
  # says a self-reported statistic is not an assertion.
  if [ -n "$pattern" ]; then
    matches=$(grep -c -- "$prefix" "$evidence" || true)
  else
    matches=$(grep -c "$prefix: PASS" "$evidence" || true)
  fi
  if [ "$matches" -gt 1 ]; then
    printf 'FAIL: %s carries %s "%s: PASS" lines. Only the first is read, so a\n' "${pair%%:*}" "$matches" "$prefix" >&2
    printf 'stale copy appended below a fresh one would be unread.\n' >&2
    exit 1
  fi
  if [ -n "$pattern" ]; then
    quoted=$(grep -m1 -- "$prefix" "$evidence" | sed 's/^[[:space:]]*//' || true)
  else
    quoted=$(grep -m1 "$prefix: PASS" "$evidence" | sed 's/^[[:space:]]*//' || true)
  fi
  if [ -z "$quoted" ]; then
    printf 'FAIL: %s carries no "%s: PASS" line to compare.\n' "${pair%%:*}" "$prefix" >&2
    printf 'Deleting the quoted summary is not a way to stop disagreeing with the gate.\n' >&2
    exit 1
  fi
  transcripts_checked=$((transcripts_checked + 1))
  if [ -z "$pattern" ] && [ -n "$fresh_self" ]; then
    self_matches=$(grep -c "$prefix: self-test PASS" "$evidence" || true)
    if [ "$self_matches" -gt 1 ]; then
      printf 'FAIL: %s carries %s "%s: self-test PASS" lines; only the first is read.\n' "${pair%%:*}" "$self_matches" "$prefix" >&2
      exit 1
    fi
    quoted_self=$(grep -m1 "$prefix: self-test PASS" "$evidence" \
                  | sed 's/^[[:space:]]*//' || true)
    if [ -n "$quoted_self" ] && [ "$quoted_self" != "$fresh_self" ]; then
      printf 'FAIL: %s quotes a self-test summary the gate no longer prints:\n' "${pair%%:*}" >&2
      printf '  file: %s\n  now:  %s\n' "$quoted_self" "$fresh_self" >&2
      exit 1
    fi
    if [ -z "$quoted_self" ]; then
      printf 'FAIL: %s carries no "%s: self-test PASS" line to compare.\n' "${pair%%:*}" "$prefix" >&2
      exit 1
    fi
    transcripts_checked=$((transcripts_checked + 1))
  fi
  if [ "$quoted" != "$fresh" ]; then
    printf 'FAIL: %s quotes a summary the gate no longer prints:\n' "${pair%%:*}" >&2
    printf '  file: %s\n  now:  %s\n' "$quoted" "$fresh" >&2
    printf 'An evidence transcript that disagrees with the gate it transcribes is not evidence.\n' >&2
    exit 1
  fi
done <<<"$TRANSCRIPT_PAIRS"
if [ "$transcripts_checked" -lt 7 ]; then
  printf 'FAIL: reconciled %s evidence summary line(s), expected 7. A leg that\n' \
    "$transcripts_checked" >&2
  printf 'quietly checks nothing is indistinguishable from one that passes.\n' >&2
  exit 1
fi

printf 'PASS: Rhoform layout is structurally valid (%s root Markdown files, %s JSON files under [%s], versions.yaml parsed, retired-name scan scanned, evidence files tracked).\n' \
  "$md_count" "$json_count" "$JSON_ROOTS"
