#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
install_opencode_plugin — idempotently place the block-adhoc-scripts opencode plugin into a
target project's .opencode/plugins/ (the opencode analog of install_hook.py; R5.7 deliverable).

opencode auto-loads .opencode/plugins/*.{js,ts} at startup (NO config registration), so "wiring"
= placing the .ts file. Idempotent + merge-aware: a second run refreshes our own file to the
canonical source and NEVER touches the user's other plugins (we manage exactly one filename).

Mirrors install_hook.py's CLI contract:
  py install_opencode_plugin.py --plugins-dir <path> --source <ts-file>
       [--plugin-name block_adhoc_scripts] [--remove]

stdout (R5.3b): {"plugins_dir":"...","plugin":"...","action":"written|present|removed","path":"..."}
stderr = diagnostics. Exit codes (R5.3b): 0 ok · 1 IO error · 2 misuse.

Build/install-time tool (like tools/install_hook.py / gen_*.py); NOT the /mgh-* orchestrator,
so it is outside the R5.2 "no .py" bright-line. Zero runtime deps (Python >=3.10 stdlib).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_DEFAULT_PLUGIN_NAME = "block_adhoc_scripts"


def main():
    ap = argparse.ArgumentParser(
        description="idempotently place block-adhoc-scripts opencode plugin into .opencode/plugins/")
    ap.add_argument("--plugins-dir", required=True,
                    help="path to target .opencode/plugins/ (created if missing)")
    ap.add_argument("--source", required=True,
                    help="canonical .ts plugin file to copy from (e.g. releases/opencode/plugins/block_adhoc_scripts.ts)")
    ap.add_argument("--plugin-name", default=_DEFAULT_PLUGIN_NAME,
                    help=f"plugin filename stem (default: {_DEFAULT_PLUGIN_NAME})")
    ap.add_argument("--remove", action="store_true",
                    help="remove our plugin file instead of placing it")
    args = ap.parse_args()

    plugins_dir = Path(args.plugins_dir)
    source = Path(args.source)
    dest = plugins_dir / f"{args.plugin_name}.ts"

    if args.remove:
        if dest.is_file():
            dest.unlink()
            action = "removed"
        else:
            action = "absent"  # nothing to remove (still a success / idempotent no-op)
        print(f"[install_opencode_plugin] {dest}: {action}", file=sys.stderr)
        print(json.dumps({"plugins_dir": str(plugins_dir), "plugin": args.plugin_name,
                          "action": action, "path": str(dest)}, ensure_ascii=False))
        return 0

    if not source.is_file():
        print(f"error: source plugin not found: {source}", file=sys.stderr)
        return 1

    new_text = source.read_text(encoding="utf-8")
    # Idempotent: if our file already matches the canonical source, leave it (present); else refresh (written).
    if dest.is_file() and dest.read_text(encoding="utf-8") == new_text:
        action = "present"
    else:
        plugins_dir.mkdir(parents=True, exist_ok=True)
        dest.write_text(new_text, encoding="utf-8")
        action = "written"

    print(f"[install_opencode_plugin] {dest}: {action}", file=sys.stderr)
    print(json.dumps({"plugins_dir": str(plugins_dir), "plugin": args.plugin_name,
                      "action": action, "path": str(dest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
