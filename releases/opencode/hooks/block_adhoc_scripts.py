#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
block_adhoc_scripts — PreToolUse hook enforcing /mgh-init + /mgh-sast + /mgh-sra + /mgh-srr
orchestrator discipline (R5.2 at runtime, R5.7 deliverable).

Active ONLY inside a mgh run-domain: env MGH_INIT_ACTIVE=1 (/mgh-init) OR
MGH_SAST_ACTIVE=1 (/mgh-sast) OR MGH_SRA_ACTIVE=1 (/mgh-sra) OR MGH_SRR_ACTIVE=1 (/mgh-srr),
set by the orchestrator at step 0. Outside all four: exit 0 silently (zero day-to-day
noise). Blocks the real-world failure shapes —
  (a) Bash `py -c|python -c` introspection of artifacts (import json / open( / load( /
      .json), and
  (b) Write/Edit of an ad-hoc `*.py` not on the sanctioned whitelist.
  (c) [init + sra + srr domains] Write/Edit whose resolved target falls OUTSIDE the resolved
      MGH_TARGET tree — the fan-out draft/checkpoint/memory/report path drifted to a non-project
      dir (observed: a Windows drive root). For sra/srr, MGH_TARGET is the project root, which
      covers BOTH the working subtree (<project>/openspec/changes/<change>/ for sra;
      <project>/.mgh-srr/ for srr) AND the shared project memory (<project>/.mgh-sra/).
      MGH_TARGET missing -> degrade (pass, no block).
On a hit: exit 2 (Claude Code blocks the call) + stderr recipe pointing at the
sanctioned primitives (list_* / prepare_augment / describe_artifact / producer stdout).

Claude Code feeds the tool call as JSON on stdin:
  {"tool_name":"Bash|Write|Edit", "tool_input":{"command"|"file_path": ...}, ...}

Zero runtime deps (Python >=3.10 stdlib: json/os/pathlib/re/sys). Idempotent, stateless,
no TTY.
"""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

# A `py -c` / `python -c` / `python3 -c` invocation (preceded by start or a shell
# delimiter, so it does not match a substring of another token).
_PYC_RX = re.compile(r'(?:^|[\s;&|(])py(?:thon)?[0-9]*\s+-c\b')
# Introspection / re-derivation signals (FD1 real failure shape).
_INTRO_TOKENS = ("import json", "open(", "load(", ".json")

# Write/Edit whitelist: sanctioned locations where a .py is legitimate (the installed
# leaf scripts, repo dev dirs, the hooks dir itself). Fragment/segment match covers both
# the repo layout (core/scripts) and the installed layout (.claude/mgh-core/scripts).
_WL_SEGMENTS = {"tests", "tools", "hooks"}

# Per-domain sanctioned work-list primitives (the recipe points the agent at the right
# one). describe_artifact.py + producer stdout are shared across domains.
_WORKLIST = {
    "mgh-init": "list_clusters.py / list_scout_batches.py / list_rule_jobs.py",
    "mgh-sast": "list_chunks.py / list_verify_jobs.py",
    "mgh-sra": "prepare_augment.py / merge_augment.py / merge_memory.py",
    "mgh-srr": "ingest_requirements.py / render_report.py / merge_memory.py",
}


def _recipe(domain: str) -> str:
    return (
        f"{domain} orchestrator discipline (R5.2): use a sanctioned primitive —\n"
        f"  - work-list   -> {_WORKLIST[domain]}\n"
        "  - structure   -> describe_artifact.py --keys/--sample/--shape/--field\n"
        "  - derived qty -> the producer's stdout field\n"
        f"  NEVER py -c / python -c introspection, NEVER Write ad-hoc .py in {domain}."
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


def _is_out_of_tree(path: str) -> bool:
    """True iff a Write/Edit target resolves OUTSIDE the MGH_TARGET tree (init domain;
    defense-in-depth for the fan-out output-path contract — turns a silent drift to a
    non-project dir into a fail-loud). Returns False (pass, never block) when MGH_TARGET
    is unset/blank (degrade), the path is empty, or either side will not resolve."""
    target = os.environ.get("MGH_TARGET", "").strip()
    if not target or not path:
        return False
    try:
        return not Path(path).resolve().is_relative_to(Path(target).resolve())
    except (OSError, ValueError):
        return False


def main():
    init = os.environ.get("MGH_INIT_ACTIVE", "") == "1"
    sast = os.environ.get("MGH_SAST_ACTIVE", "") == "1"
    sra = os.environ.get("MGH_SRA_ACTIVE", "") == "1"
    srr = os.environ.get("MGH_SRR_ACTIVE", "") == "1"
    if not (init or sast or sra or srr):
        return 0  # outside any run-domain: pass silently
    # precedence (rare to have two): sast > sra > srr > init
    domain = ("mgh-sast" if sast else
              "mgh-sra" if sra else
              "mgh-srr" if srr else "mgh-init")
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
                f"blocked: ad-hoc `py -c` introspection in {domain} run-domain.\n  {_recipe(domain)}\n")
            return 2
    elif tool in ("Write", "Edit"):
        path = (ti.get("file_path") or ti.get("path") or "")
        if _is_blocked_py_write(path):
            sys.stderr.write(
                f"blocked: Write/Edit of ad-hoc .py in {domain} run-domain: {path}\n  {_recipe(domain)}\n")
            return 2
        # subtree guard: init (checkpoint/rule paths) + sra (draft/memory/merge paths) +
        # srr (draft/report/memory paths). MGH_TARGET is the project root for sra/srr,
        # covering working subtree + shared project memory.
        if (init or sra or srr) and _is_out_of_tree(path):
            sys.stderr.write(
                f"blocked: Write/Edit outside the MGH_TARGET tree in {domain} run-domain: "
                f"{path}\n  target tree = {os.environ.get('MGH_TARGET', '?')}\n  {_recipe(domain)}\n"
                f"  the output path MUST be the verbatim `checkpoint_path`/`rule_path`/"
                f"`draft_path` from the producer stdout (already absolute, under the target tree).\n")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
