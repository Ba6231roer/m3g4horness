#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
install_hook — idempotently merge the block-adhoc-scripts PreToolUse hook into a
target project's .claude/settings.json (called by install.sh, R5.7 deliverable).

Build/install-time tool (like tools/gen_*.py); NOT the /mgh-init orchestrator, so it is
outside the R5.2 "no .py" bright-line. Idempotent: a second run does not duplicate the
matcher and never clobbers the user's existing hooks — it only appends one entry whose
command references `block_adhoc_scripts`.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/sys/pathlib).

CLI (`--help` is the contract surface):
  py install_hook.py --settings <path> --hook-command <cmd>
       [--matcher Bash|Write|Edit] [--remove]

stdout (R5.3b): {"settings":"...","action":"added|present|removed","matcher":"..."}
stderr = diagnostics. Exit codes (R5.3b): 0 ok · 1 IO error · 2 misuse.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_DEFAULT_MATCHER = "Bash|Write|Edit"
# idempotency anchor: a PreToolUse entry is "ours" if any of its hook commands references
# this substring (stable across reinstalls even if the matcher text is edited).
_OUR_MARKER = "block_adhoc_scripts"


def _load(path: Path):
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed settings.json: {e}", file=sys.stderr)
        sys.exit(1)
    return data if isinstance(data, dict) else {}


def _find_ours(preuse: list) -> int:
    """Index of the first PreToolUse entry whose command references our marker, else -1."""
    for i, entry in enumerate(preuse):
        if not isinstance(entry, dict):
            continue
        for h in entry.get("hooks", []) or []:
            if isinstance(h, dict) and _OUR_MARKER in (h.get("command") or ""):
                return i
    return -1


def main():
    ap = argparse.ArgumentParser(
        description="idempotently merge block-adhoc-scripts PreToolUse hook into settings.json")
    ap.add_argument("--settings", required=True, help="path to .claude/settings.json")
    ap.add_argument("--hook-command", required=True,
                    help='command string for the hook (e.g. "py .claude/hooks/block_adhoc_scripts.py")')
    ap.add_argument("--matcher", default=_DEFAULT_MATCHER,
                    help=f"PreToolUse tool matcher regex (default: {_DEFAULT_MATCHER})")
    ap.add_argument("--remove", action="store_true",
                    help="remove our matcher entry instead of adding it")
    args = ap.parse_args()

    settings_path = Path(args.settings)
    data = _load(settings_path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        data["hooks"] = hooks
    preuse = hooks.get("PreToolUse")
    if not isinstance(preuse, list):
        preuse = []
        hooks["PreToolUse"] = preuse

    idx = _find_ours(preuse)
    action = "present"

    if args.remove:
        if idx >= 0:
            preuse.pop(idx)
            action = "removed"
            if not preuse:
                del hooks["PreToolUse"]
            if not hooks:
                del data["hooks"]
    else:
        if idx < 0:
            preuse.append({
                "matcher": args.matcher,
                "hooks": [{"type": "command", "command": args.hook_command}],
            })
            action = "added"
        # if present: leave the user's possibly-customized entry untouched (idempotent)

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    print(f"[install_hook] {settings_path}: {action} (matcher={args.matcher})",
          file=sys.stderr)
    print(json.dumps({"settings": str(settings_path), "action": action,
                      "matcher": args.matcher}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
