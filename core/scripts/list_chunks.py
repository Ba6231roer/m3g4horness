#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
list_chunks — deterministic s4 work-list producer for /mgh-sast.

Reads the s3 product `s3_chunks.json` (vvah wrapper {rationale, chunks[]}) and the
s4 per-chunk checkpoint dir, then prints the authoritative pending work-list as JSON
on stdout. Closes the s4 fan-out asymmetry: mgh-init has list_clusters.py /
list_scout_batches.py / list_rule_jobs.py, sast s4 now has this
(harden-mgh-sast-orchestration-discipline FD2). Replaces hand-rolled
`py -c "import json..."` introspection of checkpoints/s4_candidates.json and the
`_prep_chunks.py` micro-script reflex in the orchestrator (R5.2: orchestrator invokes
leaf scripts via Bash; MUST NOT hand-roll JSON mining, MUST NOT `len()` the wrapper —
that yields the top-level key count, not the chunk count).

Unit key: vvah s3 emits each chunk with `id` (e.g. "chunk-01"); the lite re-projects
it as `chunk_id`. Checkpoint convention (DEFINED here, see
core/contracts/sast/fanout-enumeration.md): orchestrator writes
`checkpoints/s4/<chunk_id>.json` + `<chunk_id>.json.done` per completed deep-dive.
chunk_id values are filename-safe, so done-id = the `.done` marker's stem.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_chunks.py --chunks <s3_chunks.json> [--checkpoints <s4-dir>]

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"repo": ..., "total": N, "done": M, "pending": [<ChunkLite>, ...],
   "truncated": false}
  - total       = len(chunks[])             (the REAL count, not len(wrapper))
  - done        = #chunks whose <chunk_id>.json.done marker exists
  - pending[]   = chunks not yet done, in file order; each item:
      {chunk_id, files[], threat_id, hypothesis}
  - repo        = passthrough of wrapper.repo (null when absent — s3 wrapper lacks it)
  - truncated   = passthrough of wrapper.truncated (false when absent)

Exit codes (R5.3b): 0 ok (incl. empty chunks) · 1 s3_chunks.json missing/malformed ·
2 misuse (argparse). Idempotent, read-only, no TTY.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). list_chunks currently has no sibling
# import, but the guard keeps it in the self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

_DONE_SUFFIX = ".json.done"  # marker = "<chunk_id>.json.done"; chunk_id is filename-safe


def _done_ids(checkpoints_dir: Path):
    """Return the set of completed chunk_ids by scanning `<chunk_id>.json.done`
    markers. chunk_id is filename-safe (vvah emits "chunk-NN"), so the marker stem
    IS the chunk_id — no sibling-record field read needed (cf. list_rule_jobs)."""
    done = set()
    if not checkpoints_dir.is_dir():
        return done
    for marker in sorted(checkpoints_dir.glob("*" + _DONE_SUFFIX)):
        name = marker.name
        if name.endswith(_DONE_SUFFIX):
            done.add(name[: -len(_DONE_SUFFIX)])  # strip ".json.done" -> <chunk_id>
    return done


def _lite(chunk: dict) -> dict:
    return {
        "chunk_id": chunk.get("id"),          # vvah s3 key is `id` ("chunk-01")
        "files": chunk.get("files", []),
        "threat_id": chunk.get("threat_id"),
        "hypothesis": chunk.get("hypothesis"),
    }


def main():
    ap = argparse.ArgumentParser(
        description="list pending s4 chunks from s3_chunks.json (deterministic work-list)")
    ap.add_argument("--chunks", required=True,
                    help="path to s3_chunks.json (vvah wrapper {rationale, chunks[]})")
    ap.add_argument("--checkpoints",
                    help="s4 per-chunk checkpoint dir (default: <chunks-dir>/s4)")
    args = ap.parse_args()

    chunks_path = Path(args.chunks)
    if not chunks_path.is_file():
        print(f"error: s3_chunks.json not found: {chunks_path}", file=sys.stderr)
        return 1
    try:
        wrapper = json.loads(chunks_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed s3_chunks.json: {e}", file=sys.stderr)
        return 1
    # Accept the vvah wrapper {rationale, chunks[]} or a bare chunks list.
    if isinstance(wrapper, list):
        chunks = wrapper
    elif isinstance(wrapper, dict) and isinstance(wrapper.get("chunks"), list):
        chunks = wrapper["chunks"]
    else:
        print("error: s3_chunks.json must be {rationale, chunks[]} (or a bare chunks "
              "list); chunks must be a list (do NOT len() the wrapper)", file=sys.stderr)
        return 1

    checkpoints_dir = (Path(args.checkpoints).resolve() if args.checkpoints
                       else (chunks_path.parent / "s4").resolve())
    done = _done_ids(checkpoints_dir)

    pending = [_lite(c) for c in chunks
               if isinstance(c, dict) and c.get("id") not in done]
    result = {
        "repo": wrapper.get("repo") if isinstance(wrapper, dict) else None,
        "total": len(chunks),
        "done": len(chunks) - len(pending),
        "pending": pending,
        "truncated": bool(wrapper.get("truncated", False)) if isinstance(wrapper, dict) else False,
    }
    print(f"s3_chunks.json: {len(chunks)} total, {result['done']} done, "
          f"{len(pending)} pending (checkpoints: {checkpoints_dir})", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
