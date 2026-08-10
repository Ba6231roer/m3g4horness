#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
list_ut_steps — deterministic step invocation manifest for /mgh-ut-init.

Emits the canonical per-step invocation manifest as JSON on stdout. Each step
carries {step, kind, script_abs, invocation, input{}, output{}} where
`script_abs` is an absolute path derived from this script's location
(`Path(__file__).resolve().parent / <script_name>`) — the host prefix
(`.claude/mgh-core/` vs `.opencode/mgh-core/`) is inferred from where the
script is installed, NEVER hardcoded or passed via prompt. Copied from init's
`list_steps.py` and adapted to the ut step graph (classify prelude, no
codegraph-resolve step, ut product names); init's `list_steps.py` is untouched.

Zero disk preconditions: does NOT read run_config.json, does NOT scan
.mgh-ut-init/, does NOT depend on any run-state artifacts. Queryable pre-run,
during compaction recovery, or for pure documentation review.

Complements `resume_ut_init_state.py` (disk-derived "where am I / what's next"):
resume_ut_init_state gives current step; list_ut_steps gives the exact
invocation line for any step. Use together after --resume/compaction.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_ut_steps.py [--target <dir>] [--step <id>]

  --target   target project root (default: .); accepted for future extension,
             not used in manifest content (static contract).
  --step     emit only the single step with this id (e.g., "classify",
             "extract"); exits 2 if id not recognized (closed set, R5.3b).
             Default: emit all steps.

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"steps": [{step, kind, script_abs, invocation, input{}, output{}}]}
  - step        = step id (enum matching resume_ut_init_state.py)
  - kind        = "bash" | "subagent"
  - script_abs  = absolute path to the script (<mgh-core>/scripts/<name>.py,
                 derived from __file__; host-agnostic)
  - invocation  = copy-pasteable Bash invocation line: "py <script_abs> <args>"
  - input{}     = {artifact: "<name>", shape: "<shape>"}
  - output{}    = {artifact: "<name>", shape: "<shape>", path_pattern: "<pattern>"}

Exit codes (R5.3b): 0 ok · 1 target not a dir · 2 misuse (--step not found).
Idempotent, no TTY, read-only.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate so sibling imports resolve under any cwd / host-agent invocation.
sys.path.insert(0, str(Path(__file__).resolve().parent))


# Static step→IO table (data-driven, defined once). Step id set matches
# resume_ut_init_state.py step enumeration (cross-script consistency guard).
# Each entry: {step, kind, script_name, cli_args, input, output}.
# `script_abs` is derived at runtime from __file__.
_STEPS = [
    {
        "step": "classify",
        "kind": "bash",
        "script_name": "classify_tests.py",
        "cli_args": "--repo <target> --out <init-dir>",
        "input": {"artifact": None, "shape": None},
        "output": {"artifact": "test_groups.json", "shape": "{repo,groups[]}",
                   "path_pattern": "<init-dir>/test_groups.json"},
    },
    {
        "step": "extract",
        "kind": "bash",
        "script_name": "list_test_groups.py",
        "cli_args": "--tier extract --groups <init-dir>/test_groups.json --checkpoints <init-dir>/checkpoints/extract --materialize <init-dir>/inputs/extract",
        "input": {"artifact": "test_groups.json", "shape": "{repo,groups[]}"},
        "output": {"artifact": "checkpoints/extract/*.json", "shape": "[checkpoint per group]",
                   "path_pattern": "<init-dir>/checkpoints/extract/<group>.json"},
    },
    {
        "step": "synthesize",
        "kind": "subagent",
        "script_name": None,  # Subagent: no leaf script
        "cli_args": None,
        "input": {"artifact": "checkpoints/extract/*.json", "shape": "[per-group observations]"},
        "output": {"artifact": "test_rules_inventory.json", "shape": "{rules[],category}",
                   "path_pattern": "<init-dir>/test_rules_inventory.json"},
    },
    {
        "step": "rules",
        "kind": "bash",
        "script_name": "list_test_groups.py",
        "cli_args": "--tier rules --inventory <init-dir>/test_rules_inventory.json --format <fmt> --checkpoints <init-dir>/checkpoints/rules --target <target> --rules-dir <rules-dir> --materialize <init-dir>/inputs/rules",
        "input": {"artifact": "test_rules_inventory.json", "shape": "{rules[]}"},
        "output": {"artifact": "checkpoints/rules/*.json", "shape": "[checkpoint per category]",
                   "path_pattern": "<init-dir>/checkpoints/rules/<category>.json"},
    },
    {
        "step": "assemble",
        "kind": "bash",
        "script_name": "assemble_test_rules.py",
        "cli_args": "--target <target> --format <fmt>",
        "input": {"artifact": "checkpoints/rules/*.json", "shape": "[rules records]"},
        "output": {"artifact": "rules", "shape": "<fmt>-specific files",
                   "path_pattern": "<claude: target>/.claude/rules/test-*.md | <opencode: target>/docs/test-conventions/*.md"},
    },
    {
        "step": "consistency",
        "kind": "subagent",
        "script_name": None,  # Subagent: no leaf script
        "cli_args": None,
        "input": {"artifact": "rules", "shape": "rule files"},
        "output": {"artifact": "checkpoints/consistency/.done", "shape": "marker",
                   "path_pattern": "<init-dir>/checkpoints/consistency/.done"},
    },
    {
        "step": "mutators",
        "kind": "bash",
        "script_name": "derive_mutators.py",
        "cli_args": "--repo <target> --out <init-dir>",
        "input": {"artifact": None, "shape": None},
        "output": {"artifact": "default_mutators.json", "shape": "{source,mutators[],parser_notes[]}",
                   "path_pattern": "<init-dir>/default_mutators.json"},
    },
    {
        "step": "done",
        "kind": "bash",
        "script_name": None,  # Terminal state: no script
        "cli_args": None,
        "input": {"artifact": None, "shape": None},
        "output": {"artifact": "ut_manifest.json", "shape": "{version,counts,boundaries[]}",
                   "path_pattern": "<init-dir>/ut_manifest.json"},
    },
]


def _script_abs(script_name: str | None) -> str | None:
    """Derive absolute script path from __file__. Returns None for subagent steps
    (no leaf script) or for steps with script_name=None."""
    if script_name is None:
        return None
    # This script resides in <mgh-core>/scripts/; sibling scripts are in the same dir.
    scripts_dir = Path(__file__).resolve().parent
    sibling = scripts_dir / script_name
    return str(sibling) if sibling.exists() else None


def _invocation(script_abs: str | None, cli_args: str | None) -> str | None:
    """Build copy-pasteable Bash invocation line. Returns None for subagent steps."""
    if script_abs is None or cli_args is None:
        return None
    return f"py {script_abs} {cli_args}"


def _build_step(entry: dict) -> dict:
    """Build output step entry from static definition, resolving runtime fields."""
    step_id = entry["step"]
    script_name = entry["script_name"]
    script_abs = _script_abs(script_name)
    cli_args = entry["cli_args"]
    return {
        "step": step_id,
        "kind": entry["kind"],
        "script": script_name,
        "script_abs": script_abs,
        "invocation": _invocation(script_abs, cli_args),
        "input": entry["input"],
        "output": entry["output"],
    }


def main():
    ap = argparse.ArgumentParser(
        description="emit /mgh-ut-init per-step invocation manifest (deterministic, zero disk pre-req)")
    ap.add_argument("--target", default=".",
                    help="target project root (default .); accepted for future extension")
    ap.add_argument("--step", metavar="<id>",
                    help="emit only the single step with this id (e.g. classify, extract); "
                         "exits 2 if not recognized (closed set)")
    # Emit JSON cleanly regardless of host console codepage (e.g. cp936/gbk on Chinese
    # Windows) so stdout parses everywhere. No-op on StringIO (in-process tests).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = ap.parse_args()

    # Validate --target is a dir (even though unused; keeps contract honest for future)
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"error: target not a directory: {target}", file=sys.stderr)
        return 1

    # Build all steps
    steps = [_build_step(e) for e in _STEPS]
    step_ids = {s["step"] for s in steps}

    # Filter by --step if requested
    if args.step:
        if args.step not in step_ids:
            print(f"error: unknown step id: {args.step!r} (known: {sorted(step_ids)})",
                  file=sys.stderr)
            return 2
        steps = [s for s in steps if s["step"] == args.step]
        print(f"[list_ut_steps] emitting single step: {args.step}", file=sys.stderr)
    else:
        print(f"[list_ut_steps] emitting {len(steps)} steps (use --step <id> for single step)",
              file=sys.stderr)

    result = {"steps": steps}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
