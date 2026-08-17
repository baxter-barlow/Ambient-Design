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
REQUIRED_FILES="AGENTS.md CLAUDE.md CONTRIBUTING.md LICENSE LICENSES.md README.md toolchain/versions.yaml"

# Directories whose JSON must parse. Keep in step with SCHEMA_ROOTS in
# tests/schemas/validate-schemas.py: this gate proves the bytes are JSON,
# that one proves the JSON means something.
JSON_ROOTS="ir parts eval lang"

json_parser=""
if command -v python3 >/dev/null 2>&1; then
  json_parser="python3"
elif command -v jq >/dev/null 2>&1; then
  json_parser="jq"
else
  printf 'FAIL: neither python3 nor jq is available; the JSON parse gate cannot run.\n' >&2
  exit 2
fi

parse_json() {
  if [ "$json_parser" = "python3" ]; then
    python3 -c 'import json, sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$1" 2>/dev/null
  else
    jq empty "$1" >/dev/null 2>&1
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
    *) fail "unexpected root Markdown file: $name (specs live in Notion per LICENSES.md)" ;;
  esac
done < <(find "$ROOT" -mindepth 1 -maxdepth 1 -type f -name '*.md' | LC_ALL=C sort)

# Required governance and toolchain files.
for rel in $REQUIRED_FILES; do
  [ -f "$ROOT/$rel" ] || fail "required file is missing: $rel"
done

# Every JSON file under a declared JSON root must parse. Schema semantics
# are checked by the schemas gate; a file that does not even parse fails
# here first. Roots that do not exist yet are skipped.
json_count=0
for json_root in $JSON_ROOTS; do
  [ -d "$ROOT/$json_root" ] || continue
  while IFS= read -r file; do
    json_count=$((json_count + 1))
    parse_json "$file" || fail "does not parse as JSON: ${file#"$ROOT"/}"
  done < <(find "$ROOT/$json_root" -type f -name '*.json' | LC_ALL=C sort)
done

# Retired names must not come back. AMB-122 renamed AED to Rhoform across
# everything that ships, and AMB-118 moved the KiCad library prefix off
# `ael:` because AEL is Keysight ADS's Application Extension Language - a
# same-industry collision. Without a gate, one copied snippet or one reverted
# file reintroduces either and nothing notices until it is inconsistent again.
#
# The library prefix is matched as `ael:` and not as a bare word, because
# unlike the project name it is retired only in that one position: three
# letters that occur inside ordinary English would fail on the next document
# that happens to contain them.
#
# PATHS ARE CHECKED AS WELL AS CONTENTS. The first version of this scanned
# file bodies only, so re-creating `eval/aed_eval/` and tracking a file in it
# passed cleanly - which is precisely the miss AMB-122 was written to prevent,
# since the thing its inventory nearly lost was a DIRECTORY NAME.
#
# Four exclusions are deliberate, listed explicitly rather than matched
# loosely:
#
#   aed-part-data / aed_part_data   a SEPARATE project's repository
#   sha256 digests                  two of them spell the letters mid-hash
#   the note in tests/ir/           records that the rename happened
#   this file                       a check cannot forbid a word without
#                                   naming it, so it does not scan itself
#
# Only tracked files are scanned: an untracked scratch tree is not the
# repository. Needs python3 and git; without either it reports itself
# unavailable rather than passing silently.
brand_check="scanned"
if ! command -v git >/dev/null 2>&1 || [ "$json_parser" != "python3" ]; then
  brand_check="DEFERRED (needs python3 and git)"
  printf 'WARN: retired-name scan %s; it did not run.\n' "$brand_check" >&2
else
  brand_hits=$(cd "$ROOT" && git ls-files -z | python3 -c '
import re, sys
ALLOWED = ("aed-part-data", "aed_part_data")
HEX = re.compile(r"\b[0-9a-f]{64}\b")
NOTE = "tests/ir/check-hashes.py"
SELF = "tests/structure/check-layout.sh"
BRAND = re.compile("aed", re.I)
PREFIX = re.compile(r"\bael:", re.I)
hits = []
for raw in sys.stdin.buffer.read().split(b"\0"):
    rel = raw.decode()
    if not rel or rel == SELF:
        continue
    # The path itself, which is how a renamed package or skill directory
    # comes back. Stripped THEN searched, exactly as the body is below: an
    # earlier version exempted the whole path if any allowed token appeared
    # anywhere in it, so a single `aed-part-data` segment switched the gate
    # off for everything beneath it - the moment that pipeline is vendored or
    # mirrored under its own name, the subtree stops being checked.
    probe = rel
    for token in ALLOWED:
        probe = probe.replace(token, "")
    if BRAND.search(probe):
        hits.append(f"{rel}  (path)")
    try:
        text = open(rel, encoding="utf-8").read()
    except FileNotFoundError:
        continue
    except IsADirectoryError:
        continue
    except UnicodeDecodeError:
        # Not text. Report rather than skip: a binary carrying the old name
        # is still the old name, and silence here would be the same bug as
        # not looking at paths.
        hits.append(f"{rel}  (binary, not scanned)")
        continue
    except OSError as exc:
        # Unreadable. Reported as a finding so the scan still COMPLETES and
        # the real residue elsewhere is still listed; letting this raise
        # aborted the whole scan and turned a diagnosable failure into a
        # bare non-zero exit.
        hits.append(f"{rel}  (unreadable: {exc.strerror}, not scanned)")
        continue
    for token in ALLOWED:
        text = text.replace(token, "")
    text = HEX.sub("", text)
    if rel == NOTE:
        text = text.replace("the AED -> Rhoform rename", "")
    for line_no, line in enumerate(text.split("\n"), 1):
        if BRAND.search(line) or PREFIX.search(line):
            hits.append(f"{rel}:{line_no}")
if hits:
    print("\n".join(hits))
')
  if [ -n "$brand_hits" ]; then
    printf 'FAIL: a retired name (AED, or the ael: library prefix) reappears in tracked files:\n%s\n' "$brand_hits" >&2
    exit 1
  fi
fi

# The toolchain manifest must parse as YAML when PyYAML is available.
# Without PyYAML the deep parse is deferred to CI, where it always runs.
yaml_check="deferred (PyYAML unavailable)"
if [ "$json_parser" = "python3" ] && python3 -c 'import yaml' 2>/dev/null; then
  python3 -c 'import sys, yaml; yaml.safe_load(open(sys.argv[1], encoding="utf-8"))' \
    "$ROOT/toolchain/versions.yaml" 2>/dev/null \
    || fail "toolchain/versions.yaml does not parse as YAML"
  yaml_check="parsed"
fi

printf 'PASS: Rhoform layout is structurally valid (%s root Markdown files, %s JSON files under [%s], versions.yaml %s, retired-name scan %s).\n' \
  "$md_count" "$json_count" "$JSON_ROOTS" "$yaml_check" "$brand_check"
