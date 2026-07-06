#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
plan_scout — deterministic scout batch planner for /mgh-init (D4 of
improve-mgh-init-llm-discovery).

Reads skeleton.json (lossless per-file metadata from discover_controls.py) and
controls_candidates.json (regex hits), then produces byte-bounded, package-co-located
batches for the LLM scout layer. Scout targets = files NOT already covered by regex
(regex hits already produced candidates). Batches are sized by cumulative bytes
(<= --batch-bytes) with a per-batch file cap, sorted by package so related files share
a scout-reader context (co-location). Single files exceeding the batch budget get their
own batch and are flagged needs_slice (scout-reader runs them through chunk_sources.py,
never whole). --budget caps total targets (large repos -> truncated, advise
--scope + --merge).

Zero runtime deps (Python >=3.10 stdlib). stdout = structured JSON; stderr = progress.

CLI contract (--help is the contract surface, R5.1):
  py plan_scout.py --skeleton <skeleton.json> --candidates <controls_candidates.json>
       --out <scout_plan.json> [--batch-bytes 98304] [--batch-cap 40] [--budget 0]

stdout (R5.3b): {"targets_total": N, "batches": M, "truncated": bool, "oversize": K}
Exit codes (R5.3b): 0 ok · 1 input missing/malformed · 2 misuse.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate so any future sibling import resolves under any cwd (Standalone script
# invocation robustness). plan_scout currently has no sibling import.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _seal(targets, bytes_):
    return {"batch_id": "", "targets": targets, "bytes": bytes_, "needs_slice": []}


def plan_batches(targets, batch_bytes: int, batch_cap: int):
    """Greedy bin-pack: sort by pkg then file (co-location); flush a batch when the next
    target would exceed batch_bytes or batch_cap. Oversize targets get their own batch
    and are flagged needs_slice. Returns (batches, oversize_count)."""
    ordered = sorted(targets, key=lambda t: (t.get("pkg", ""), t["file"]))
    batches = []
    cur, cur_bytes = [], 0
    oversize = 0
    for t in ordered:
        b = int(t.get("bytes", 0))
        if b > batch_bytes:
            if cur:
                batches.append(_seal(cur, cur_bytes))
                cur, cur_bytes = [], 0
            batches.append({"batch_id": "", "targets": [t], "bytes": b,
                            "needs_slice": [t["file"]]})
            oversize += 1
            continue
        if cur and (cur_bytes + b > batch_bytes or len(cur) >= batch_cap):
            batches.append(_seal(cur, cur_bytes))
            cur, cur_bytes = [], 0
        cur.append(t)
        cur_bytes += b
    if cur:
        batches.append(_seal(cur, cur_bytes))
    for i, bat in enumerate(batches, 1):
        bat["batch_id"] = f"scout-{i:03d}"
    return batches, oversize


def main():
    ap = argparse.ArgumentParser(
        description="plan byte-bounded, package-co-located scout batches from skeleton.json (D4)")
    ap.add_argument("--skeleton", required=True, help="path to skeleton.json")
    ap.add_argument("--candidates", required=True,
                    help="path to controls_candidates.json (regex hits to exclude)")
    ap.add_argument("--out", required=True, help="output scout_plan.json path")
    ap.add_argument("--batch-bytes", type=int, default=98304,
                    help="max cumulative bytes per scout batch (default 96KB)")
    ap.add_argument("--batch-cap", type=int, default=40,
                    help="max files per scout batch (coverage-expectation guard)")
    ap.add_argument("--budget", type=int, default=0,
                    help="cap total scout targets (0 = no cap; >0 -> truncated if exceeded)")
    args = ap.parse_args()

    sk_path = Path(args.skeleton)
    if not sk_path.is_file():
        print(f"error: skeleton.json not found: {sk_path}", file=sys.stderr)
        return 1
    cand_path = Path(args.candidates)
    if not cand_path.is_file():
        print(f"error: candidates not found: {cand_path}", file=sys.stderr)
        return 1
    try:
        sk = json.loads(sk_path.read_text(encoding="utf-8"))
        files = sk.get("files") if isinstance(sk, dict) else None
        if not isinstance(files, list):
            print("error: skeleton.json must be a wrapper {repo, generated_by, files[]}",
                  file=sys.stderr)
            return 1
        cd = json.loads(cand_path.read_text(encoding="utf-8"))
        cands = cd.get("candidates", []) if isinstance(cd, dict) else []
    except (OSError, ValueError) as e:
        print(f"error: malformed input: {e}", file=sys.stderr)
        return 1

    # regex-covered files (exclude from scout): either flagged in skeleton or listed in
    # candidates. scout targets = the regex-blind complement (D4-f).
    regex_files = {c.get("file") for c in cands
                   if isinstance(c, dict) and c.get("source", "regex") == "regex"}
    targets = [f for f in files
               if isinstance(f, dict) and not f.get("regex_hit")
               and f.get("file") not in regex_files]

    truncated = False
    if args.budget and len(targets) > args.budget:
        targets = sorted(targets, key=lambda t: (t.get("pkg", ""), t.get("file", "")))[:args.budget]
        truncated = True
        print(f"[plan_scout] targets exceeded --budget {args.budget}; truncated — "
              f"consider --scope path:<module> + --merge", file=sys.stderr)

    batches, oversize = plan_batches(targets, args.batch_bytes, args.batch_cap)
    payload = {
        "repo": sk.get("repo"),
        "generated_by": "plan_scout.py",
        "targets_total": len(targets),
        "truncated": truncated,
        "batches": batches,
    }
    Path(args.out).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[plan_scout] {len(targets)} targets -> {len(batches)} batches "
          f"(oversize->slice: {oversize}, truncated: {truncated})", file=sys.stderr)
    print(json.dumps({"targets_total": len(targets), "batches": len(batches),
                      "truncated": truncated, "oversize": oversize}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
