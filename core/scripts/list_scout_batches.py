#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
list_scout_batches — deterministic scout work-list producer for /mgh-init.

Reads the wrapper dict `scout_plan.json` ({repo, targets_total, truncated, batches[]})
and the scout checkpoint dir, then prints the authoritative pending work-list as JSON
on stdout. Closes the fan-out asymmetry: T1 has `list_clusters.py`, scout now has this
(harden-mgh-init-orchestration-discipline FD3). Replaces hand-rolled
`py -c "import json..."` introspection / `_prep_scout_batches.py` in the orchestrator
(R5.2: orchestrator invokes leaf scripts via Bash; MUST NOT hand-roll JSON mining).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_scout_batches.py --scout-plan <scout_plan.json> [--checkpoints <scout-dir>]

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"repo": "...", "total": N, "done": M, "pending": [<BatchLite>, ...],
   "truncated": false}
  - total       = len(batches[])
  - done        = #batches whose checkpoint unit is complete
  - pending[]   = batches not yet done, in file order; each item:
      {batch_id, targets_count, bytes, needs_slice[],
       checkpoint_path, done_marker}
  - checkpoint_path = ABSOLUTE path the scout subagent MUST write its checkpoint to
                      (<resolved --checkpoints>/<batch_id>.json); passed verbatim by the
                      orchestrator so the subagent NEVER assembles/interpolates a path.
  - done_marker     = ABSOLUTE `.done` marker path (<checkpoint_path>.done) to touch.
  - truncated   = passthrough of the wrapper's `truncated` flag (no silent loss)

Exit codes (R5.3b): 0 ok (incl. empty batches) · 1 scout_plan.json missing/malformed ·
2 misuse (argparse). Idempotent, read-only, no TTY.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). list_scout_batches currently has no
# sibling import, but the guard keeps it in the self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _done_ids(checkpoints_dir: Path):
    """Return the set of completed batch_ids by reading each checkpoint record's
    `batch_id` field (robust); marker = `<id>.json.done`, record = `<id>.json`
    (sibling). batch_id is clean (`scout-NNN`), so filename-stem fallback is safe."""
    done = set()
    if not checkpoints_dir.is_dir():
        return done
    for marker in sorted(checkpoints_dir.glob("*.json.done")):
        record = marker.with_suffix("")  # strip trailing ".done" -> <id>.json
        bid = None
        if record.is_file():
            try:
                bid = json.loads(record.read_text(encoding="utf-8")).get("batch_id")
            except (OSError, ValueError):
                bid = None
        if not bid:
            bid = record.stem  # <id>; fallback for missing/empty record
            print(f"warn: could not read batch_id from {record.name}; using stem {bid!r}",
                  file=sys.stderr)
        done.add(bid)
    return done


def _lite(batch: dict, checkpoints_dir: Path) -> dict:
    bid = batch.get("batch_id")
    base = checkpoints_dir / f"{bid}.json"
    return {
        "batch_id": bid,
        "targets_count": len(batch.get("targets", [])),
        "bytes": batch.get("bytes", 0),
        "needs_slice": batch.get("needs_slice", []),
        # Absolute output paths (checkpoints_dir is already .resolve()'d in main): the
        # single authoritative value the orchestrator passes VERBATIM to the scout
        # subagent and the subagent writes VERBATIM — no <target>/<batch_id> placeholder
        # assembly, no relative path (safe under any subagent cwd, incl. Windows drive root).
        "checkpoint_path": str(base),
        "done_marker": str(base.with_name(base.name + ".done")),
    }


def main():
    ap = argparse.ArgumentParser(
        description="list pending scout batches from scout_plan.json (deterministic work-list)")
    ap.add_argument("--scout-plan", required=True,
                    help="path to scout_plan.json (wrapper {repo,batches,truncated})")
    ap.add_argument("--checkpoints",
                    help="scout checkpoint dir (default: <scout-plan>/../checkpoints/scout)")
    args = ap.parse_args()

    plan_path = Path(args.scout_plan)
    if not plan_path.is_file():
        print(f"error: scout_plan.json not found: {plan_path}", file=sys.stderr)
        return 1
    try:
        wrapper = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed scout_plan.json: {e}", file=sys.stderr)
        return 1
    if not isinstance(wrapper, dict) or not isinstance(wrapper.get("batches"), list):
        print("error: scout_plan.json must be a wrapper {repo, batches[], truncated}",
              file=sys.stderr)
        return 1

    batches = wrapper["batches"]
    checkpoints_dir = (Path(args.checkpoints).resolve() if args.checkpoints
                       else (plan_path.parent / "checkpoints" / "scout").resolve())
    done = _done_ids(checkpoints_dir)

    pending = [_lite(b, checkpoints_dir) for b in batches
               if isinstance(b, dict) and b.get("batch_id") not in done]
    result = {
        "repo": wrapper.get("repo"),
        "total": len(batches),
        "done": len(batches) - len(pending),
        "pending": pending,
        "truncated": bool(wrapper.get("truncated", False)),
    }
    print(f"scout_plan.json: {len(batches)} total, {result['done']} done, "
          f"{len(pending)} pending (checkpoints: {checkpoints_dir})", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
