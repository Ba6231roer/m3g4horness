#!/usr/bin/env bash
# m3g4h⊿rness installer — copies a platform shell + core/ into a project.
# Usage: ./install.sh [--claude|--opencode] [target_project_dir]
#   default platform: claude ; default target: current dir
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM="claude"
TARGET="${TARGET:-.}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --claude)  PLATFORM="claude"; shift;;
    --opencode) PLATFORM="opencode"; shift;;
    -h|--help)
      echo "Usage: $0 [--claude|--opencode] [target_project_dir]"; exit 0;;
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

echo "✓ installed $PLATFORM shell into $DEST"
echo "  commands: /mgh-sast, /mgh-init ($PLATFORM)"
echo "Run /mgh-sast --help or /mgh-init --help to verify."
