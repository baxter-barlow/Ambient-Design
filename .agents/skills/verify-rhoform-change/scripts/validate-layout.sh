#!/bin/sh
set -eu

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../../../.." && pwd -P)
CANONICAL_SKILLS="$PROJECT_ROOT/.agents/skills"
CLAUDE_SKILLS="$PROJECT_ROOT/.claude/skills"
SKILLS="claim-linear-work isolated-agent-checkout verify-rhoform-change release-evidence"

[ -f "$PROJECT_ROOT/AGENTS.md" ] || fail "AGENTS.md is missing"
[ -f "$PROJECT_ROOT/CLAUDE.md" ] || fail "CLAUDE.md is missing"
[ "$(cat "$PROJECT_ROOT/CLAUDE.md")" = '@AGENTS.md' ] || fail "CLAUDE.md must contain only @AGENTS.md"

agents_lines=$(wc -l < "$PROJECT_ROOT/AGENTS.md" | tr -d ' ')
[ "$agents_lines" -le 200 ] || fail "AGENTS.md exceeds 200 lines"

for skill in $SKILLS; do
  skill_dir="$CANONICAL_SKILLS/$skill"
  skill_file="$skill_dir/SKILL.md"
  metadata_file="$skill_dir/agents/openai.yaml"
  claude_link="$CLAUDE_SKILLS/$skill"

  [ -f "$skill_file" ] || fail "$skill/SKILL.md is missing"
  [ "$(sed -n '1p' "$skill_file")" = '---' ] || fail "$skill frontmatter does not start on line 1"
  [ "$(sed -n '2p' "$skill_file")" = "name: $skill" ] || fail "$skill name does not match its directory"
  sed -n '3p' "$skill_file" | grep -Eq '^description: .+' || fail "$skill description is missing"
  sed -n '4p' "$skill_file" | grep -Fxq -- '---' || fail "$skill frontmatter contains unsupported fields"
  ! grep -n 'TODO' "$skill_file" >/dev/null || fail "$skill contains a TODO placeholder"

  skill_lines=$(wc -l < "$skill_file" | tr -d ' ')
  [ "$skill_lines" -le 500 ] || fail "$skill/SKILL.md exceeds 500 lines"

  [ -f "$metadata_file" ] || fail "$skill UI metadata is missing"
  grep -Fq "\$$skill" "$metadata_file" || fail "$skill default prompt does not name the skill"

  [ -L "$claude_link" ] || fail ".claude/skills/$skill is not a symlink"
  [ -e "$claude_link/SKILL.md" ] || fail ".claude/skills/$skill is broken"
  canonical_target=$(CDPATH= cd -- "$skill_dir" && pwd -P)
  claude_target=$(CDPATH= cd -- "$claude_link" && pwd -P)
  [ "$claude_target" = "$canonical_target" ] || fail ".claude/skills/$skill does not resolve to the canonical skill"
done

for skill_dir in "$CANONICAL_SKILLS"/*; do
  [ -d "$skill_dir" ] || continue
  skill=$(basename "$skill_dir")
  case " $SKILLS " in
    *" $skill "*) ;;
    *) fail "unexpected canonical skill directory: $skill" ;;
  esac
done

for claude_entry in "$CLAUDE_SKILLS"/*; do
  [ -e "$claude_entry" ] || [ -L "$claude_entry" ] || continue
  skill=$(basename "$claude_entry")
  case " $SKILLS " in
    *" $skill "*) ;;
    *) fail "unexpected Claude skill entry: $skill" ;;
  esac
done

printf 'PASS: Rhoform agent layout is structurally valid (%s AGENTS.md lines, %s skills).\n' "$agents_lines" "$(printf '%s\n' $SKILLS | wc -l | tr -d ' ')"
