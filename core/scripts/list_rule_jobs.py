#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
list_rule_jobs — deterministic T3 work-list producer for /mgh-init.

Reads `controls_inventory.json` (categories from controls[]) and the T3 checkpoint dir,
then prints the authoritative per-category pending work-list as JSON on stdout. Closes
the fan-out asymmetry: T1 has `list_clusters.py`, scout has `list_scout_batches.py`,
T3 now has this (harden-mgh-init-orchestration-discipline FD3). Replaces hand-rolled
`py -c "import json..."` introspection of the inventory in the orchestrator (R5.2).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_rule_jobs.py --inventory <controls_inventory.json>
       --format opencode|claude [--checkpoints <t3-dir>] [--target <dir>]

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"total": N, "done": M, "pending": [<RuleJobLite>, ...], "format": "..."}
  - total       = #distinct categories in the inventory
  - done        = #categories whose T3 checkpoint marker exists
  - pending[]   = categories not yet done; each item:
      {category, format, rule_path, done_marker}
  - rule_path   = ABSOLUTE (target resolved via Path.resolve(); absolute even when
                  --target defaults to "."):
                  claude  -> <abs target>/.claude/rules/security-<cat>.md
                  opencode-> <abs target>/.mgh-init/rules-parts/<cat>.md
                  Passed verbatim by the orchestrator; the rulewriter subagent NEVER
                  assembles/interpolates a path.
  - done_marker = ABSOLUTE `.done` marker path
                  (<abs checkpoints>/<cat>.<format>.json.done) to touch.

Exit codes (R5.3b): 0 ok (incl. empty inventory) · 1 inventory missing/malformed ·
2 misuse (argparse). Idempotent, read-only, no TTY.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). list_rule_jobs currently has no sibling
# import, but the guard keeps it in the self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _rule_path(target: str, category: str, fmt: str) -> str:
    base = target.rstrip("/")
    if fmt == "claude":
        return f"{base}/.claude/rules/security-{category}.md"
    return f"{base}/.mgh-init/rules-parts/{category}.md"


def _done_categories(checkpoints_dir: Path, fmt: str):
    """Return the set of completed categories by scanning
    `<category>.<format>.json.done` markers. Category names contain no dots
    (init 8-enum), so `<cat>.<format>` splits cleanly on the last dot."""
    done = set()
    if not checkpoints_dir.is_dir():
        return done
    suffix = f".{fmt}.json.done"
    for marker in sorted(checkpoints_dir.glob(f"*.{fmt}.json.done")):
        name = marker.name
        if not name.endswith(suffix):
            continue
        cat = name[: -len(suffix)]  # strip ".<fmt>.json.done" -> <category>
        done.add(cat)
    return done


def main():
    ap = argparse.ArgumentParser(
        description="list pending T3 rule jobs from controls_inventory.json (deterministic work-list)")
    ap.add_argument("--inventory", required=True,
                    help="path to controls_inventory.json ({format, controls[]})")
    ap.add_argument("--format", required=True, choices=["opencode", "claude"],
                    help="rule format (determines rule_path; also the run's --format)")
    ap.add_argument("--checkpoints",
                    help="T3 checkpoint dir (default: <inventory>/../checkpoints/t3)")
    ap.add_argument("--target", default=".",
                    help="target project root for rule_path (default .)")
    args = ap.parse_args()

    inv_path = Path(args.inventory)
    if not inv_path.is_file():
        print(f"error: controls_inventory.json not found: {inv_path}", file=sys.stderr)
        return 1
    try:
        inv = json.loads(inv_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed controls_inventory.json: {e}", file=sys.stderr)
        return 1
    if not isinstance(inv, dict) or not isinstance(inv.get("controls"), list):
        print("error: controls_inventory.json must be a wrapper {format, controls[]}",
              file=sys.stderr)
        return 1

    # distinct categories in file order (deterministic), then sorted for stability
    seen = []
    for c in inv["controls"]:
        if isinstance(c, dict) and c.get("category") and c["category"] not in seen:
            seen.append(c["category"])
    categories = sorted(seen)

    checkpoints_dir = (Path(args.checkpoints).resolve() if args.checkpoints
                       else (inv_path.parent / "checkpoints" / "t3").resolve())
    done = _done_categories(checkpoints_dir, args.format)

    # Resolve target ONCE to an absolute path (FD5): the rulewriter subagent's cwd is not
    # assumed, so a relative rule_path is unsafe (would resolve to the drive root on a
    # misplaced cwd). rule_path / done_marker are the single authoritative values the
    # orchestrator passes VERBATIM — no <target>/<category> assembly downstream.
    target_abs = str(Path(args.target).resolve())
    pending = [{"category": cat, "format": args.format,
                "rule_path": _rule_path(target_abs, cat, args.format),
                "done_marker": str(checkpoints_dir / f"{cat}.{args.format}.json.done")}
               for cat in categories if cat not in done]
    result = {
        "total": len(categories),
        "done": len(categories) - len(pending),
        "pending": pending,
        "format": args.format,
    }
    print(f"controls_inventory.json: {len(categories)} category(ies), {result['done']} done, "
          f"{len(pending)} pending (checkpoints: {checkpoints_dir})", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
