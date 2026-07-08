#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
list_clusters — deterministic T1 work-list producer for /mgh-init.

Reads the wrapper dict `clusters.json` ({repo, clusters[], truncated}) and the T1
checkpoint dir, then prints the authoritative pending work-list as JSON on stdout.
Replaces hand-rolled `py -c "import json..."` introspection in the orchestrator
(R5.2: orchestrator invokes leaf scripts via Bash; MUST NOT hand-roll JSON mining,
MUST NOT `len()` the wrapper — that yields 3, the top-level key count, not the
cluster count).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_clusters.py --clusters <clusters.json> [--checkpoints <t1-dir>]

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"repo": "...", "total": N, "done": M, "pending": [<ClusterLite>, ...],
   "truncated": false}
  - total       = len(clusters[])             (the REAL count, not len(wrapper))
  - done        = #clusters whose checkpoint unit is complete
  - pending[]   = clusters not yet done, in file order; each item:
      {cluster_id, category, kind, shape, evidence_files[], candidate_count,
       checkpoint_path, done_marker}
  - checkpoint_path = ABSOLUTE path the T1 subagent MUST write its checkpoint to
                      (<resolved --checkpoints>/<cluster_id>.json); passed verbatim by the
                      orchestrator so the subagent NEVER assembles/interpolates a path.
  - done_marker     = ABSOLUTE `.done` marker path (<checkpoint_path>.done) to touch.
  - truncated   = passthrough of the wrapper's `truncated` flag (no silent loss)

Exit codes (R5.3b): 0 ok (incl. empty clusters) · 1 clusters.json missing/malformed ·
2 misuse (argparse). Idempotent, read-only, no TTY.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# FD2 family convention: self-locate this script's dir so any future sibling import
# resolves under any cwd / host-agent invocation (direct `py`/`python`). list_clusters
# currently has no sibling import, but the guard keeps it in the self-contained family.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _done_ids(checkpoints_dir: Path):
    """Return the set of completed cluster_ids by reading each checkpoint record's
    `unit` field (robust to filename sanitization of cluster_id, which may contain
    `::` and `/`). Marker = `<id>.json.done`; record = `<id>.json` (sibling)."""
    done = set()
    if not checkpoints_dir.is_dir():
        return done
    for marker in sorted(checkpoints_dir.glob("*.json.done")):
        record = marker.with_suffix("")  # strip trailing ".done" → <id>.json
        unit = None
        if record.is_file():
            try:
                unit = json.loads(record.read_text(encoding="utf-8")).get("unit")
            except (OSError, ValueError):
                unit = None
        if not unit:
            # fallback: derive from filename stem (best-effort); warn on stderr
            unit = record.stem  # <id>
            print(f"warn: could not read unit from {record.name}; using stem {unit!r}",
                  file=sys.stderr)
        done.add(unit)
    return done


def _lite(cluster: dict, checkpoints_dir: Path) -> dict:
    cid = cluster.get("cluster_id")
    base = checkpoints_dir / f"{cid}.json"
    return {
        "cluster_id": cid,
        "category": cluster.get("category"),
        "kind": cluster.get("kind"),
        "shape": cluster.get("shape"),
        "evidence_files": cluster.get("evidence_files", []),
        "candidate_count": len(cluster.get("candidate_ids", [])),
        # Absolute output paths (checkpoints_dir is already .resolve()'d in main): the
        # single authoritative value the orchestrator passes VERBATIM to the T1 subagent
        # and the subagent writes VERBATIM — no relative path / no placeholder assembly
        # (safe under any subagent cwd, incl. Windows drive root).
        "checkpoint_path": str(base),
        "done_marker": str(base.with_name(base.name + ".done")),
    }


def main():
    ap = argparse.ArgumentParser(
        description="list pending T1 clusters from clusters.json (deterministic work-list)")
    ap.add_argument("--clusters", required=True,
                    help="path to clusters.json (wrapper dict {repo,clusters,truncated})")
    ap.add_argument("--checkpoints",
                    help="T1 checkpoint dir (default: <clusters>/../checkpoints/t1)")
    args = ap.parse_args()

    clusters_path = Path(args.clusters)
    if not clusters_path.is_file():
        print(f"error: clusters.json not found: {clusters_path}", file=sys.stderr)
        return 1
    try:
        wrapper = json.loads(clusters_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed clusters.json: {e}", file=sys.stderr)
        return 1
    if not isinstance(wrapper, dict) or not isinstance(wrapper.get("clusters"), list):
        print("error: clusters.json must be a wrapper {repo, clusters[], truncated}; "
              "clusters must be a list (do NOT len() the wrapper)", file=sys.stderr)
        return 1

    clusters = wrapper["clusters"]
    checkpoints_dir = (Path(args.checkpoints).resolve() if args.checkpoints
                       else (clusters_path.parent / "checkpoints" / "t1").resolve())
    done = _done_ids(checkpoints_dir)

    pending = [_lite(c, checkpoints_dir) for c in clusters
               if isinstance(c, dict) and c.get("cluster_id") not in done]
    result = {
        "repo": wrapper.get("repo"),
        "total": len(clusters),
        "done": len(clusters) - len(pending),
        "pending": pending,
        "truncated": bool(wrapper.get("truncated", False)),
    }
    print(f"clusters.json: {len(clusters)} total, {result['done']} done, "
          f"{len(pending)} pending (checkpoints: {checkpoints_dir})", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
