#!/usr/bin/env bash
# m3g4h⊿rness installer — copies a platform shell + core/ into a project.
# Usage: ./install.sh [--claude|--opencode] [target_project_dir]
#   default platform: claude ; default target: current dir
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM="claude"
TARGET="${TARGET:-.}"
ENFORCE_HOOK="1"   # inject PreToolUse hook (R5.7); --no-enforce-hook opts out

while [[ $# -gt 0 ]]; do
  case "$1" in
    --claude)  PLATFORM="claude"; shift;;
    --opencode) PLATFORM="opencode"; shift;;
    --no-enforce-hook) ENFORCE_HOOK="0"; shift;;
    -h|--help)
      echo "Usage: $0 [--claude|--opencode] [--no-enforce-hook] [target_project_dir]"; exit 0;;
    *) TARGET="$1"; shift;;
  esac
done

TARGET="$(cd "$TARGET" && pwd)"
case "$PLATFORM" in
  claude)   SHELL_SRC="$HERE/releases/claude-code"; DEST_REL=".claude";;
  opencode) SHELL_SRC="$HERE/releases/opencode";    DEST_REL=".opencode";;
esac
CORE_SRC="$HERE/core"

[[ -d "$SHELL_SRC" ]] || { echo "✗ unknown platform shell: $SHELL_SRC" >&2; exit 1; }
[[ -d "$CORE_SRC" ]]  || { echo "✗ missing core/: $CORE_SRC" >&2; exit 1; }

# 1) Zero RUNTIME-dependency check: no real Python import of vvaharness.
#    (Prose attribution like "ported from vvaharness" in .md is allowed.)
if grep -rnE "^[[:space:]]*(import[[:space:]]+vvaharness|from[[:space:]]+vvaharness[[:space:]]+import)" "$HERE" --include=*.py >/dev/null 2>&1; then
  echo "✗ zero-dependency check FAILED: found runtime import of vvaharness:" >&2
  grep -rnE "^[[:space:]]*(import[[:space:]]+vvaharness|from[[:space:]]+vvaharness[[:space:]]+import)" "$HERE" --include=*.py >&2 || true
  exit 1
fi
echo "✓ zero-dependency check passed (no runtime import of vvaharness)"

# 2) Decide destination by platform.
case "$PLATFORM" in
  claude)  DEST="$TARGET/.claude";;
  opencode) DEST="$TARGET/.opencode";;
esac

# 3) Copy the shell-specific files + shared core.
copy_tree() {
  local src="$1" rel="$2"
  local dst="$DEST/$rel"
  mkdir -p "$dst"
  cp -r "$src/." "$dst/"
}

# Shell payload mirrors into the platform-native layout.
case "$PLATFORM" in
  claude)
    [[ -d "$SHELL_SRC/commands" ]] && { mkdir -p "$DEST/commands"; cp -r "$SHELL_SRC/commands/." "$DEST/commands/"; }
    [[ -d "$SHELL_SRC/agents" ]]   && { mkdir -p "$DEST/agents";   cp -r "$SHELL_SRC/agents/."   "$DEST/agents/"; }
    [[ -d "$SHELL_SRC/skills" ]]   && { mkdir -p "$DEST/skills";   cp -r "$SHELL_SRC/skills/."   "$DEST/skills/"; }
    [[ -d "$SHELL_SRC/hooks" ]]    && { mkdir -p "$DEST/hooks";    cp -r "$SHELL_SRC/hooks/."    "$DEST/hooks/"; }
    ;;
  opencode)
    [[ -d "$SHELL_SRC/command" ]]  && { mkdir -p "$DEST/command";  cp -r "$SHELL_SRC/command/."  "$DEST/command/"; }
    [[ -d "$SHELL_SRC/agent" ]]    && { mkdir -p "$DEST/agent";    cp -r "$SHELL_SRC/agent/."    "$DEST/agent/"; }
    ;;
esac
# Shared core always lands at <dest>/mgh-core so both shells reference one copy.
# This single copy includes every command/agent/prompt/script/contract/profile
# under core/ and releases/<platform>/ — so /mgh-sast AND /mgh-init (and their
# agents, prompts, discover_controls.py, chunk_sources.py, contracts/init/) ship
# together without per-command enumerate.
mkdir -p "$DEST/mgh-core"
cp -r "$CORE_SRC/." "$DEST/mgh-core/"

# 4) Self-check (fail-soft per R5.8): the /mgh-init discover/scout/assemble pipeline
#    needs these scripts co-located — discover_controls.py / chunk_sources.py do
#    `from expand_scope import ...`, merge_scout.py does `from discover_controls import
#    form_clusters`, and assemble_rules.py is invoked by the orchestrator after T3
#    (opencode assembly + purity lint). A missing sibling breaks i1 / scout fold-in /
#    opencode assembly at runtime. Warn only (don't block a partial install); CI / tests
#    enforce co-location (R5.8: CI 必 fail).
_missing=()
for s in expand_scope discover_controls chunk_sources plan_scout merge_scout assemble_rules \
         list_clusters list_scout_batches list_rule_jobs describe_artifact validate_inventory; do
  [[ -f "$DEST/mgh-core/scripts/$s.py" ]] || _missing+=("$s.py")
done
if (( ${#_missing[@]} )); then
  echo "⚠ self-check (non-blocking): missing co-located scripts in $DEST/mgh-core/scripts/: ${_missing[*]}" >&2
  echo "  (partial install? /mgh-init may fail at runtime; CI enforces co-location)" >&2
else
  echo "✓ mgh-init scripts co-located: expand_scope/discover_controls/chunk_sources/plan_scout/merge_scout/assemble_rules + list_clusters/list_scout_batches/list_rule_jobs/describe_artifact/validate_inventory"
fi

# 4b) Distribution-purity self-check (R5.10; fail-soft per R5.8): shipped md MUST be
#     free of dev-only provenance / dangling references (rule/decision ids, change-
#     folder names, glasswing_docs/, task.*.md, dev-meta). Warn only on violation —
#     don't block a partial install; CI / tests enforce purity.
if py "$HERE/tools/check_distributed_purity.py" >/dev/null 2>&1; then
  echo "✓ distribution-purity check passed (shipped md clean, R5.10)"
else
  echo "⚠ distribution-purity check FAILED (non-blocking, R5.8 fail-soft): shipped md carries dev-only provenance" >&2
  echo "  run 'py tools/check_distributed_purity.py' for details; CI enforces purity" >&2
fi

# 5) PreToolUse hook injection (R5.7 deliverable; FD4). claude only — opencode has no
#    equivalent PreToolUse capability, so warn + skip (fail-soft, R5.8). --no-enforce-hook
#    opts out entirely; discipline then rests on the shell bright-lines + R5.9 checks.
if [[ "$ENFORCE_HOOK" == "1" ]]; then
  if [[ "$PLATFORM" == "claude" ]]; then
    SETTINGS="$DEST/settings.json"
    HOOK_CMD="py .claude/hooks/block_adhoc_scripts.py"
    if py "$HERE/tools/install_hook.py" --settings "$SETTINGS" --hook-command "$HOOK_CMD" >/dev/null; then
      echo "✓ injected PreToolUse hook (block-adhoc-scripts) into $SETTINGS (idempotent; --no-enforce-hook to skip)"
    else
      echo "⚠ hook injection failed (non-blocking, R5.8 fail-soft); discipline via shell bright-lines + R5.9" >&2
    fi
  else
    echo "⚠ opencode: no PreToolUse hook injected (capability unsupported); discipline via shell bright-lines + R5.9" >&2
  fi
else
  echo "• --no-enforce-hook: PreToolUse hook not injected; discipline via shell bright-lines + R5.9"
fi

echo "✓ installed $PLATFORM shell into $DEST"
echo "  commands: /mgh-sast, /mgh-init ($PLATFORM)"
echo "Run /mgh-sast --help or /mgh-init --help to verify."
