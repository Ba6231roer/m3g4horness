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


def _run_check(plan_path: Path, batch_bytes: int):
    """R5.9 boundary check: validate an existing scout_plan.json. Asserts batches[] is
    non-empty when there are targets, every batch is within byte budget (an over-budget
    batch MUST be a sliced single-file batch), and needs_slice lists only oversize files.
    Returns exit 0 ok / 2 violation."""
    violations = []
    try:
        wrapper = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed scout_plan.json: {e}", file=sys.stderr)
        return 1
    if not isinstance(wrapper, dict) or not isinstance(wrapper.get("batches"), list):
        print("error: scout_plan.json must be a wrapper {repo, batches[], ...}", file=sys.stderr)
        return 1
    batches = wrapper["batches"]
    targets_total = wrapper.get("targets_total", 0)
    if targets_total and not batches:
        violations.append({"issue": f"0 batches but targets_total={targets_total}"})

    for bat in batches:
        if not isinstance(bat, dict):
            violations.append({"issue": "batch not an object"})
            continue
        bid = bat.get("batch_id", "<no-id>")
        if not bat.get("batch_id"):
            violations.append({"batch_id": bid, "issue": "missing batch_id"})
        if not isinstance(bat.get("targets"), list):
            violations.append({"batch_id": bid, "issue": "missing targets[]"})
            continue
        b = int(bat.get("bytes", 0))
        needs_slice = bat.get("needs_slice", []) or []
        # over-budget is allowed ONLY for a sliced batch (single oversize file)
        if b > batch_bytes and not needs_slice:
            violations.append({"batch_id": bid,
                               "issue": f"bytes {b} > budget {batch_bytes} but needs_slice empty"})
        # needs_slice must list only oversize files
        size_of = {t.get("file"): int(t.get("bytes", 0))
                   for t in bat["targets"] if isinstance(t, dict)}
        for f in needs_slice:
            if f in size_of and size_of[f] <= batch_bytes:
                violations.append({"batch_id": bid, "file": f,
                                   "issue": f"in needs_slice but bytes {size_of[f]} <= budget {batch_bytes}"})

    ok = not violations
    print(f"[plan_scout --check] {plan_path}: {'OK' if ok else f'{len(violations)} violation(s)'}",
          file=sys.stderr)
    print(json.dumps({"check": "plan_scout", "ok": ok, "batches": len(batches),
                      "targets_total": targets_total,
                      "violations": violations}, ensure_ascii=False))
    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(
        description="plan byte-bounded, package-co-located scout batches from skeleton.json (D4)")
    ap.add_argument("--skeleton", required=False, help="path to skeleton.json")
    ap.add_argument("--candidates", required=False,
                    help="path to controls_candidates.json (regex hits to exclude)")
    ap.add_argument("--out", required=False, help="output scout_plan.json path")
    ap.add_argument("--check", help="validate an existing scout_plan.json (R5.9 boundary check)")
    ap.add_argument("--batch-bytes", type=int, default=98304,
                    help="max cumulative bytes per scout batch (default 96KB)")
    ap.add_argument("--batch-cap", type=int, default=40,
                    help="max files per scout batch (coverage-expectation guard)")
    ap.add_argument("--budget", type=int, default=0,
                    help="cap total scout targets (0 = no cap; >0 -> truncated if exceeded)")
    args = ap.parse_args()

    if args.check:
        return _run_check(Path(args.check).resolve(), args.batch_bytes)
    if not (args.skeleton and args.candidates and args.out):
        print("error: --skeleton, --candidates, --out are required (or use --check <plan.json>)",
              file=sys.stderr)
        return 2

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
    regex_known_count = len(regex_files)  # exposed (FD6): downstream reads this, never re-derives
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
        "regex_known_count": regex_known_count,
        "truncated": truncated,
        "batches": batches,
    }
    Path(args.out).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[plan_scout] {len(targets)} targets -> {len(batches)} batches "
          f"(regex_known: {regex_known_count}, oversize->slice: {oversize}, "
          f"truncated: {truncated})", file=sys.stderr)
    print(json.dumps({"targets_total": len(targets), "batches": len(batches),
                      "regex_known_count": regex_known_count,
                      "truncated": truncated, "oversize": oversize}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
