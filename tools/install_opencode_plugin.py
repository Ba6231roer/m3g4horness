#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
install_opencode_plugin — idempotently place the mgh opencode plugin file set into a target
project's .opencode/plugins/ (the opencode analog of install_hook.py; R5.7 deliverable).

The set is FIXED (two files, both managed by this repo, never user-extensible):
  block_adhoc_scripts.ts   tool.execute.before guard + permission.evaluate gate (Python guard shim)
  mgh_dispatch.ts          mgh_dispatch native-dispatch tool + subagent token-expansion hook

opencode auto-loads .opencode/plugins/*.{js,ts} at startup (NO config registration), so
"wiring" = placing the .ts files. Idempotent + merge-aware: a second run refreshes OUR OWN two
files to the canonical sources and NEVER touches the user's other plugins (we manage exactly
this fixed name set, nothing else in the directory).

CLI contract:
  py install_opencode_plugin.py --plugins-dir <path> --source-dir <dir> [--remove]

  --plugins-dir  target .opencode/plugins/ (created if missing)
  --source-dir   directory holding the canonical two .ts files (releases/opencode/plugins);
                 required for placement, unused by --remove
  --remove       take OUR two files back out (user plugins untouched)

stdout (R5.3b): one JSON line
  {"plugins_dir":"...","files":[{"plugin":"<stem>","action":"written|present|removed|absent",
                                 "path":"..."}, ...]}
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

# The fixed file set: both filenames are repo-owned; adding a third plugin file means
# changing THIS constant (and the install self-check + shape anchors with it), never
# scanning the directory.
_FILES = ("block_adhoc_scripts.ts", "mgh_dispatch.ts")


def main():
    ap = argparse.ArgumentParser(
        description="idempotently place the mgh opencode plugin file set (guard + dispatch) "
                    "into .opencode/plugins/")
    ap.add_argument("--plugins-dir", required=True,
                    help="path to target .opencode/plugins/ (created if missing)")
    ap.add_argument("--source-dir",
                    help="directory holding the canonical two .ts files "
                         "(e.g. releases/opencode/plugins); required for placement, "
                         "unused by --remove")
    ap.add_argument("--remove", action="store_true",
                    help="remove our plugin files instead of placing them")
    args = ap.parse_args()

    plugins_dir = Path(args.plugins_dir)
    results = []

    if args.remove:
        for name in _FILES:
            dest = plugins_dir / name
            if dest.is_file():
                dest.unlink()
                action = "removed"
            else:
                action = "absent"  # nothing to remove (still a success / idempotent no-op)
            print(f"[install_opencode_plugin] {dest}: {action}", file=sys.stderr)
            results.append({"plugin": dest.stem, "action": action, "path": str(dest)})
        print(json.dumps({"plugins_dir": str(plugins_dir), "files": results},
                         ensure_ascii=False))
        return 0

    if not args.source_dir:
        print("error: --source-dir is required for placement (directory holding the "
              "canonical two .ts plugin files)", file=sys.stderr)
        return 2
    source_dir = Path(args.source_dir)

    # Check ALL sources before writing ANY target: a skewed source tree must not leave a
    # half-installed plugin set behind.
    sources = {}
    for name in _FILES:
        src = source_dir / name
        if not src.is_file():
            print(f"error: source plugin not found: {src}", file=sys.stderr)
            return 1
        sources[name] = src.read_text(encoding="utf-8")

    for name in _FILES:
        dest = plugins_dir / name
        # Idempotent: if our file already matches the canonical source, leave it (present);
        # else refresh (written).
        if dest.is_file() and dest.read_text(encoding="utf-8") == sources[name]:
            action = "present"
        else:
            plugins_dir.mkdir(parents=True, exist_ok=True)
            dest.write_text(sources[name], encoding="utf-8")
            action = "written"
        print(f"[install_opencode_plugin] {dest}: {action}", file=sys.stderr)
        results.append({"plugin": dest.stem, "action": action, "path": str(dest)})

    print(json.dumps({"plugins_dir": str(plugins_dir), "files": results},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
