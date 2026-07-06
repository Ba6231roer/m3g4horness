#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
block_adhoc_scripts — PreToolUse hook enforcing /mgh-init orchestrator discipline.

Active ONLY inside the /mgh-init run-domain (env MGH_INIT_ACTIVE=1, set by the
orchestrator at step 0). Outside it: exit 0 silently (zero day-to-day noise).
hardens R5.2 at runtime (R5.7 deliverable): blocks the two real-world failure shapes
from new_issue.txt —
  (a) Bash `py -c|python -c` introspection of artifacts (import json / open( / load( /
      .json), and
  (b) Write/Edit of an ad-hoc `*.py` not on the sanctioned whitelist.
On a hit: exit 2 (Claude Code blocks the call) + stderr recipe pointing at the
sanctioned primitives (list_* / describe_artifact / producer stdout fields).

Claude Code feeds the tool call as JSON on stdin:
  {"tool_name":"Bash|Write|Edit", "tool_input":{"command"|"file_path": ...}, ...}

Zero runtime deps (Python >=3.10 stdlib: json/os/re/sys). Idempotent, stateless, no TTY.
"""
from __future__ import annotations
import json
import os
import re
import sys

# A `py -c` / `python -c` / `python3 -c` invocation (preceded by start or a shell
# delimiter, so it does not match a substring of another token).
_PYC_RX = re.compile(r'(?:^|[\s;&|(])py(?:thon)?[0-9]*\s+-c\b')
# Introspection / re-derivation signals (FD1 real failure shape).
_INTRO_TOKENS = ("import json", "open(", "load(", ".json")

# Write/Edit whitelist: sanctioned locations where a .py is legitimate (the installed
# leaf scripts, repo dev dirs, the hooks dir itself). Fragment/segment match covers both
# the repo layout (core/scripts) and the installed layout (.claude/mgh-core/scripts).
_WL_SEGMENTS = {"tests", "tools", "hooks"}

_RECIPE = (
    "mgh-init orchestrator discipline (R5.2): use a sanctioned primitive —\n"
    "  - work-list   -> list_clusters.py / list_scout_batches.py / list_rule_jobs.py\n"
    "  - structure   -> describe_artifact.py --keys/--sample/--shape/--field\n"
    "  - derived qty -> the producer's stdout field (regex_known_count / big_files / ...)\n"
    "  NEVER py -c / python -c introspection, NEVER Write ad-hoc .py in /mgh-init."
)


def _is_introspect_py_c(cmd: str) -> bool:
    if not _PYC_RX.search(cmd):
        return False
    low = cmd.lower()
    return any(tok in low for tok in _INTRO_TOKENS)


def _is_blocked_py_write(path: str) -> bool:
    if not path.lower().endswith(".py"):
        return False
    norm = path.replace("\\", "/").lower()
    if "core/scripts" in norm:  # matches core/scripts AND mgh-core/scripts
        return False
    segs = [s for s in norm.split("/") if s]
    if any(s in _WL_SEGMENTS for s in segs):
        return False
    return True


def main():
    if os.environ.get("MGH_INIT_ACTIVE", "") != "1":
        return 0  # outside run-domain: pass silently
    try:
        payload = json.load(sys.stdin)
    except (OSError, ValueError):
        return 0  # cannot inspect -> never block
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}

    if tool == "Bash":
        cmd = (ti.get("command") or "")
        if _is_introspect_py_c(cmd):
            sys.stderr.write(
                f"blocked: ad-hoc `py -c` introspection in /mgh-init run-domain.\n  {_RECIPE}\n")
            return 2
    elif tool in ("Write", "Edit"):
        path = (ti.get("file_path") or ti.get("path") or "")
        if _is_blocked_py_write(path):
            sys.stderr.write(
                f"blocked: Write/Edit of ad-hoc .py in /mgh-init run-domain: {path}\n  {_RECIPE}\n")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
