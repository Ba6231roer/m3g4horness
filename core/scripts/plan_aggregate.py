#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
plan_aggregate — hard-budget sharding decision + materialization for /mgh-init aggregate nodes.

Promotes `--max-aggregate-bytes` from a disclosed soft boundary to a HARD gate at the two
aggregate nodes (T2 init-synthesis / scout-merge init-scout-merge). Reads the previous tier's
records, and:
  - total input ≤ budget  → needs_reduce=false (single-context existing path, byte-identical
    behavior for small repos — zero regression);
  - total input > budget  → needs_reduce=true: cuts the records into ≤-budget shards (T2 by
    `category`; scout-merge by batch cluster), --materialize writes each shard's bounded input,
    and emits per-shard checkpoint paths. The orchestrator fans out one partial-synthesis
    subagent per shard (bounded input, bounded ack) then a single rollup subagent that consumes
    ONLY the shard summaries — every model request ≤ budget.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py plan_aggregate.py --node t2|scout-merge --init-dir <dir>
       [--budget B] [--materialize <shards-dir>] [--offset N] [--limit N] [--orch-budget-bytes B]

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"node":"t2|scout-merge","total_bytes":N,"budget":B,"needs_reduce":bool,"shards":K,
   "pending":[<Shard>,...],"truncated":false,"offset":0,"limit":K,"effective_limit":k,"shrunk":false,
   "rollup":{"summary_paths":["<abs>",...],"output":"<abs>","done_marker":"<abs>"}}
  - needs_reduce=false → pending=[] + rollup omitted; orchestrator uses single-context init-synthesis
    / init-scout-merge directly (existing path).
  - Shard item: {shard_id, node, categories (t2) | batches (scout-merge), input_path, bytes,
    oversize, checkpoint_path, done_marker}  (all ABSOLUTE; passed verbatim by the orchestrator).
Exit codes (R5.3b): 0 ok · 1 init-dir/records unreadable · 2 misuse (argparse / bad budget).
Idempotent (overwrite), no TTY.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). plan_aggregate currently has no sibling import,
# but the guard keeps it in the self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_BUDGET = 256 * 1024          # 256KB — --max-aggregate-bytes default
DEFAULT_ORCH_BUDGET_BYTES = 64 * 1024  # 64KB


def _parse_bytes(label: str, raw) -> int:
    try:
        v = int(raw)
    except (TypeError, ValueError):
        print(f"error: {label} must be a non-negative integer (got {raw!r})", file=sys.stderr)
        return -1
    if v < 0:
        print(f"error: {label} must be >= 0 (got {v})", file=sys.stderr)
        return -1
    return v


def _byte_len(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _safe_name(unit_id: str) -> str:
    """Filesystem-safe shard filename (category names / batch ids may contain `::`)."""
    return unit_id.replace("/", "_").replace("\\", "_").replace(":", "_")


def _shrink_page(page: list, orch_budget: int):
    if orch_budget <= 0 or not page:
        return page, len(page), False
    eff = len(page)
    while eff > 1 and _byte_len(page[:eff]) > orch_budget:
        eff -= 1
    return page[:eff], eff, eff < len(page)


def _read_records(records_dir: Path, exclude_names=()) -> list:
    """Read every `<id>.json` (NOT `.done`) under records_dir; skip names in exclude_names."""
    out = []
    if not records_dir.is_dir():
        return out
    for p in sorted(records_dir.glob("*.json")):
        if p.name in exclude_names:
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"warn: skipping unreadable record {p}: {e}", file=sys.stderr)
            continue
        if isinstance(rec, dict):
            rec.setdefault("__source_file", p.name)
            out.append(rec)
    return out


def _shard_by_category(records: list, budget: int):
    """T2 sharding: one shard per category. Returns [(shard_id, categories, records, bytes, oversize)]."""
    by_cat = {}
    for r in records:
        cat = r.get("category") or "_uncategorized"
        by_cat.setdefault(cat, []).append(r)
    shards = []
    for cat in sorted(by_cat):
        recs = by_cat[cat]
        nbytes = _byte_len(recs)
        sid = f"t2-{_safe_name(cat)}"
        shards.append((sid, [cat], recs, nbytes, nbytes > budget))
    return shards


def _shard_by_batch_cluster(records: list, budget: int):
    """scout-merge sharding: greedily pack batch records into ≤-budget shards (batch clusters)."""
    shards = []
    cur, cur_b, n = [], 0, 0
    for r in records:
        rb = _byte_len([r])
        if cur and cur_b + rb > budget:
            shards.append((f"scout-merge-{n}", None, cur, cur_b, cur_b > budget))
            n += 1
            cur, cur_b = [], 0
        cur.append(r)
        cur_b += rb
    if cur:
        shards.append((f"scout-merge-{n}", None, cur, cur_b, cur_b > budget))
    return shards


def _write_shard_input(shards_dir: Path, shard_id: str, node: str, categories, records: list):
    """Write `<shards-dir>/<shard_id>.input.json`; idempotent. Returns (abs path, bytes)."""
    shards_dir.mkdir(parents=True, exist_ok=True)
    body = {"node": node, "shard_id": shard_id, "records": records}
    if categories is not None:
        body["categories"] = categories
    path = (shards_dir / f"{_safe_name(shard_id)}.input.json").resolve()
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path), path.stat().st_size


def main():
    ap = argparse.ArgumentParser(
        description="hard-budget aggregate sharding for T2 / scout-merge (map-reduce gate)")
    ap.add_argument("--node", required=True, choices=["t2", "scout-merge"],
                    help="aggregate node (t2 = init-synthesis; scout-merge = init-scout-merge)")
    ap.add_argument("--init-dir", required=True,
                    help=".mgh-init dir (records read from checkpoints/<t1|scout>)")
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET,
                    help=f"per-request aggregate byte cap (default {DEFAULT_BUDGET} = "
                         f"--max-aggregate-bytes); over it → map-reduce")
    ap.add_argument("--materialize", metavar="<shards-dir>",
                    help="write each shard's bounded records to <dir>/<shard_id>.input.json "
                         "(+ input_path/bytes/oversize; slim envelope if omitted)")
    ap.add_argument("--offset", type=int, default=0, help="page offset (default 0)")
    ap.add_argument("--limit", type=int, default=None, help="max shards per page (default all)")
    ap.add_argument("--orch-budget-bytes", type=int, default=DEFAULT_ORCH_BUDGET_BYTES,
                    help=f"orchestrator single-request page byte cap (default "
                         f"{DEFAULT_ORCH_BUDGET_BYTES}; page auto-tightened + shrunk:true)")
    # Emit JSON / glyphs cleanly regardless of host console codepage (e.g. cp936/gbk).
    # Before parse_args so --help is utf-8 too. No-op on StringIO (in-process tests).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = ap.parse_args()

    if args.offset < 0:
        print("error: --offset must be >= 0", file=sys.stderr)
        return 2
    for label, raw in (("--budget", args.budget), ("--orch-budget-bytes", args.orch_budget_bytes)):
        if _parse_bytes(label, raw) < 0:
            return 2

    init_dir = Path(args.init_dir).resolve()
    if not init_dir.is_dir():
        print(f"error: init-dir not found: {init_dir}", file=sys.stderr)
        return 1

    if args.node == "t2":
        records = _read_records(init_dir / "checkpoints" / "t1")
        shard_fn = _shard_by_category
        output = (init_dir / "controls_inventory.json")
        done_marker = init_dir / "checkpoints" / "t2" / "synthesis.json.done"
        shard_cp_dir = init_dir / "checkpoints" / "t2" / "shards"
    else:
        records = _read_records(init_dir / "checkpoints" / "scout",
                                exclude_names=("merge.json", "audit.json"))
        shard_fn = _shard_by_batch_cluster
        output = init_dir / "scout_candidates.json"
        done_marker = init_dir / "checkpoints" / "scout" / "merge.json.done"
        shard_cp_dir = init_dir / "checkpoints" / "scout" / "shards"

    total_bytes = _byte_len(records)
    needs_reduce = total_bytes > args.budget

    if not needs_reduce:
        # single-context existing path — byte-identical for small repos (zero regression)
        result = {
            "node": args.node, "total_bytes": total_bytes, "budget": args.budget,
            "needs_reduce": False, "shards": 0, "pending": [],
            "truncated": False, "offset": args.offset, "limit": 0,
            "effective_limit": 0, "shrunk": False,
            "note": (f"aggregate input {total_bytes}B <= budget {args.budget}B — use "
                     f"single-context {'init-synthesis' if args.node == 't2' else 'init-scout-merge'}"),
        }
        print(f"[plan_aggregate] node={args.node} total={total_bytes}B budget={args.budget}B "
              f"-> single-context (no shards)", file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    raw_shards = shard_fn(records, args.budget)
    shards_dir = Path(args.materialize).resolve() if args.materialize else None
    pending = []
    summary_paths = []
    for sid, categories, recs, nbytes, oversize in raw_shards:
        cp = (shard_cp_dir / f"{sid}.json")
        cp_abs, dm_abs = str(cp), str(cp.with_name(cp.name + ".done"))
        item = {
            "shard_id": sid, "node": args.node,
            "checkpoint_path": cp_abs, "done_marker": dm_abs,
            "bytes": nbytes, "oversize": bool(oversize),
        }
        if categories is not None:
            item["categories"] = categories
        else:
            item["batches"] = len(recs)
        if shards_dir:
            ipath, _ = _write_shard_input(shards_dir, sid, args.node, categories, recs)
            item["input_path"] = ipath
            if oversize:
                print(f"warn: shard {sid} alone > budget ({nbytes}B > {args.budget}B) — cannot "
                      f"split further without losing whole-{'category' if args.node=='t2' else 'batch'} "
                      f"view; disclose in boundaries[]", file=sys.stderr)
        pending.append(item)
        summary_paths.append(cp_abs)

    req_limit = args.limit if args.limit is not None else len(pending)
    page = pending[args.offset: args.offset + max(0, req_limit)]
    page, eff, shrunk = _shrink_page(page, args.orch_budget_bytes)
    result = {
        "node": args.node, "total_bytes": total_bytes, "budget": args.budget,
        "needs_reduce": True, "shards": len(raw_shards), "pending": page,
        "truncated": False, "offset": args.offset, "limit": req_limit,
        "effective_limit": eff, "shrunk": shrunk,
        "rollup": {"summary_paths": summary_paths,
                   "output": str(output), "done_marker": str(done_marker)},
        "note": (f"aggregate input {total_bytes}B > budget {args.budget}B — {len(raw_shards)} "
                 f"shard(s); per-shard partial then single rollup over summaries"),
    }
    print(f"[plan_aggregate] node={args.node} total={total_bytes}B budget={args.budget}B "
          f"-> map-reduce: {len(raw_shards)} shard(s); page offset={args.offset} eff={eff} "
          f"shrunk={shrunk}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
