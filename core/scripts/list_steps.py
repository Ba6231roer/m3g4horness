#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
list_steps — deterministic step invocation manifest for /mgh-init.

Emits the canonical per-step invocation manifest as JSON on stdout. Each step
carries {step, kind, script_abs, invocation, input{}, output{}} where
`script_abs` is an absolute path derived from this script's location
(`Path(__file__).resolve().parent / <script_name>`) — the host prefix
(`.claude/mgh-core/` vs `.opencode/mgh-core/`) is inferred from where the
script is installed, NEVER hardcoded or passed via prompt.

Zero disk preconditions (D3): does NOT read run_config.json, does NOT scan
.mgh-init/, does NOT depend on any run-state artifacts. Queryable pre-run,
during compaction recovery, or for pure documentation review.

Complements `resume_state.py` (disk-derived "where am I / what's next"):
resume_state gives current step; list_steps gives the exact invocation line
for any step. Use together after --resume/compaction: resume_state yields
`step` → list_steps --step <id> yields the exact invocation.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_steps.py [--target <dir>] [--step <id>]

  --target   target project root (default: .); accepted for future extension,
             not used in manifest content (static contract).
  --step     emit only the single step with this id (e.g., "t1", "discover");
             named ids only; NOT numeric indices (e.g. --step 0 → exit 2 +
             actionable hint). Exits 2 if id not recognized (closed set, R5.3b).
             Default: emit all steps.

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"steps": [{step, kind, script_abs, invocation, input{}, output{}}]}
  - step        = step id (enum matching resume_state.py)
  - kind        = "bash" | "subagent"
  - script_abs  = absolute path to the script (<mgh-core>/scripts/<name>.py,
                 derived from __file__; host-agnostic)
  - invocation  = copy-pasteable Bash invocation line: "py <script_abs> <args>"
  - input{}     = {artifact: "<name>", shape: "<shape>"}
  - output{}    = {artifact: "<name>", shape: "<shape>", path_pattern: "<pattern>"}
  - discipline  = per-step discipline subset {gates[], path_recipes[], nevers[]}
                (gate shapes / fan-out path recipes / applicable NEVER) — identical
                to resume_state.py stdout `discipline_reminders[]` for the same step
                (shared static table in discipline_core.py; `done`/`not-started` and
                unknown steps → EMPTY structure)

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

# Shared static per-step discipline table (single source of truth, D1): identical
# to resume_state.py stdout `discipline_reminders[]` for the same step (D5 asserts
# byte-verbatim equality). discipline_core is pure data — no IO, no side effects.
from discipline_core import get_discipline  # noqa: E402


# Static step→IO table (D2: data-driven, defined once). Step id set matches
# resume_state.py step enumeration (D4 cross-script consistency guard).
# Each entry: {step, kind, script_name, cli_args, input, output}.
# `script_abs` is derived at runtime from __file__.
_STEPS = [
    {
        "step": "not-started",
        "kind": "bash",
        "script_name": "discover_controls.py",
        "cli_args": "--repo <target> --out <init-dir>",
        "input": {"artifact": None, "shape": None},
        "output": {"artifact": "controls_candidates.json", "shape": "{candidates[],source}",
                   "path_pattern": "<init-dir>/controls_candidates.json"},
    },
    {
        "step": "discover",
        "kind": "bash",
        "script_name": "discover_controls.py",
        "cli_args": "--repo <target> --out <init-dir> [--resume]",
        "input": {"artifact": None, "shape": None},
        "output": {"artifact": "controls_candidates.json", "shape": "{candidates[],source}",
                   "path_pattern": "<init-dir>/controls_candidates.json"},
    },
    {
        "step": "survey",
        "kind": "subagent",
        "script_name": None,  # Subagent: no leaf script
        "cli_args": None,
        "input": {"artifact": "controls_candidates.json", "shape": "{candidates[]}"},
        "output": {"artifact": "i1_enriched.json", "shape": "{summary[]}",
                   "path_pattern": "<init-dir>/i1_enriched.json"},
    },
    {
        "step": "scout",
        "kind": "bash",
        "script_name": "list_scout_batches.py",
        "cli_args": "--scout-plan <init-dir>/scout_plan.json --checkpoints <init-dir>/checkpoints/scout --materialize <init-dir>/inputs/scout",
        "input": {"artifact": "scout_plan.json", "shape": "{batches[]"},
                  "output": {"artifact": "scout_candidates.json", "shape": "{candidates[],source}",
                             "path_pattern": "<init-dir>/scout_candidates.json"},
    },
    {
        "step": "resolve",
        "kind": "subagent",
        "script_name": None,  # Subagent: no leaf script
        "cli_args": None,
        "input": {"artifact": "controls_candidates.json::unresolved", "shape": "[unresolved[]]"},
        "output": {"artifact": "resolved.json", "shape": "{resolved[],unresolved_residual[]}",
                   "path_pattern": "<init-dir>/resolved.json"},
    },
    {
        "step": "t1",
        "kind": "bash",
        "script_name": "list_clusters.py",
        "cli_args": "--clusters <init-dir>/clusters.json --checkpoints <init-dir>/checkpoints/t1 --candidates <init-dir>/controls_candidates.json --materialize <init-dir>/inputs/t1",
        "input": {"artifact": "clusters.json", "shape": "{repo,clusters[]}"},
        "output": {"artifact": "checkpoints/t1/*.json", "shape": "[checkpoint per cluster]",
                   "path_pattern": "<init-dir>/checkpoints/t1/<cluster_id>.json"},
    },
    {
        "step": "t2",
        "kind": "subagent",
        "script_name": None,  # Subagent: no leaf script
        "cli_args": None,
        "input": {"artifact": "checkpoints/t1/*.json", "shape": "[T1 records]"},
        "output": {"artifact": "controls_inventory.json", "shape": "{controls[],category}",
                   "path_pattern": "<init-dir>/controls_inventory.json"},
    },
    {
        "step": "t3",
        "kind": "bash",
        "script_name": "list_rule_jobs.py",
        "cli_args": "--inventory <init-dir>/controls_inventory.json --format <fmt> --checkpoints <init-dir>/checkpoints/t3 --target <target> --rules-dir <rules-dir> --materialize <init-dir>/inputs/t3",
        "input": {"artifact": "controls_inventory.json", "shape": "{controls[]}"},
        "output": {"artifact": "checkpoints/t3/*.<fmt>.json", "shape": "[checkpoint per category]",
                   "path_pattern": "<init-dir>/checkpoints/t3/<category>.<fmt>.json"},
    },
    {
        "step": "assemble",
        "kind": "bash",
        "script_name": "assemble_rules.py",
        "cli_args": "--target <target> --format <fmt>",
        "input": {"artifact": "checkpoints/t3/*.<fmt>.json", "shape": "[T3 records]"},
        "output": {"artifact": "rules", "shape": "<fmt>-specific files",
                   "path_pattern": "<claude: target>/.claude/rules/security-*.md | <opencode: target>/docs/security-controls/*.md"},
    },
    {
        "step": "t4",
        "kind": "subagent",
        "script_name": None,  # Subagent: no leaf script
        "cli_args": None,
        "input": {"artifact": "rules", "shape": "rule files"},
        "output": {"artifact": "checkpoints/t4/consistency.json.done", "shape": "marker",
                   "path_pattern": "<init-dir>/checkpoints/t4/consistency.json.done"},
    },
    {
        "step": "merge",
        "kind": "bash",
        "script_name": "merge_inventories.py",
        "cli_args": "--partials <partials-dir> --out <init-dir>/controls_inventory.json",
        "input": {"artifact": "<partials-dir>", "shape": "[partial inventory JSONs]"},
        "output": {"artifact": "controls_inventory.json", "shape": "{controls[],merged[]}",
                   "path_pattern": "<init-dir>/controls_inventory.json"},
    },
    {
        "step": "done",
        "kind": "bash",
        "script_name": None,  # Terminal state: no script
        "cli_args": None,
        "input": {"artifact": None, "shape": None},
        "output": {"artifact": "init_manifest.json", "shape": "{version,counts,boundaries[]}",
                   "path_pattern": "<init-dir>/init_manifest.json"},
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
        "discipline": get_discipline(step_id),
    }


def main():
    ap = argparse.ArgumentParser(
        description="emit /mgh-init per-step invocation manifest (deterministic, zero disk pre-req)")
    ap.add_argument("--target", default=".",
                    help="target project root (default .); accepted for future extension")
    ap.add_argument("--step", metavar="<id>",
                    help="emit only the single step with this id (e.g. t1, discover); "
                         "named ids only; NOT numeric indices; exits 2 if not "
                         "recognized (closed set)")
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
            msg = f"error: unknown step id: {args.step!r} (known: {sorted(step_ids)})"
            if args.step.isdigit():
                msg += ("; step ids are NAMED enums (from resume_state.py stdout step, "
                        "or run list_steps.py without --step to list all); "
                        "numeric indices are NOT accepted")
            print(msg, file=sys.stderr)
            return 2
        steps = [s for s in steps if s["step"] == args.step]
        print(f"[list_steps] emitting single step: {args.step}", file=sys.stderr)
    else:
        print(f"[list_steps] emitting {len(steps)} steps (use --step <id> for single step)",
              file=sys.stderr)

    result = {"steps": steps}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
