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
    `category`, splitting an over-budget category whole-record into multiple ≤-budget parts
    `t2-<category>-part<N>`; scout-merge by batch cluster), --materialize writes each shard's
    bounded input, and emits per-shard checkpoint paths. The orchestrator fans out one
    partial-synthesis subagent per shard (bounded input, bounded ack) then a single rollup
    subagent that consumes ONLY the shard summaries — every model request ≤ budget.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py plan_aggregate.py --node t2|scout-merge --init-dir <dir>
       [--budget B] [--materialize <shards-dir>] [--offset N] [--limit N] [--orch-budget-bytes B]

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"node":"t2|scout-merge","repo":"<abs target>","total_bytes":N,"budget":B,
   "needs_reduce":bool,"shards":K,
   "pending":[<Shard>,...],"truncated":false,"offset":0,"limit":K,"effective_limit":k,"shrunk":false,
   "rollup":{"summary_paths":["<abs>",...],"output":"<abs>","done_marker":"<abs>"}}
  - needs_reduce=false → pending=[] + rollup omitted; orchestrator uses single-context init-synthesis
    / init-scout-merge directly (existing path). This path is BYTE-IDENTICAL to the pre-map-reduce
    release (no repo / failed_marker added) — single-context callers read the same fields.
  - Shard item: {shard_id, node, categories (t2) | batches (scout-merge), input_path, bytes,
    oversize, checkpoint_path, done_marker, failed_marker}  (all ABSOLUTE; passed verbatim by the
    orchestrator). t2 map-reduce items additionally carry part_index/part_count (part-split
    disclosure; 0/1 when the category was not split) and slimmed ({} or the atomic-oversize
    slim-projection trace {record: {original_bytes, truncated: {field: original_bytes}}}).
    A dispatched t2 shard is ALWAYS ≤ budget: an over-budget category is split into parts and
    an atomic-oversize record (a single record whose own bytes exceed budget) is deterministically
    slim-projected at materialization (prose fields only; `evidence` anchors and other structural
    fields never truncated; checkpoints/t1 originals NEVER rewritten) or the run exits 2 —
    so t2 `oversize` is always false (field kept for stdout compat; the old
    "warn + dispatch oversize anyway" path is removed). scout-merge keeps its envelope/stdout
    byte-identical (hand-paged non-goal; its `oversize:true` + warn + send behavior is unchanged).
    repo (needs_reduce=true only) = `--init-dir` resolve parent — `.mgh-init` always
    lives under <target>/.mgh-init, so repo == <target> absolute root (anchor for the dispatcher's
    `_anchor_check`). failed_marker = same directory as done_marker, file `.<shard_id>.json.failed`
    (written by the dispatcher when a unit fails / drifts out of the repo anchor tree).
  - --node t2 only (dispatcher adoption; scout-merge stays hand-paged): the enumerator is
    marker-aware — pending[] EXCLUDES shards whose `.done`/`.failed` marker exists, and the stdout
    adds list_*-style {total, done, failed} (marker-derived; total = done + failed + pending).
    summary_paths/shards remain the FULL shard set (rollup + boundaries disclosure).
Exit codes (R5.3b): 0 ok · 1 init-dir/records unreadable · 2 misuse (argparse / bad budget) /
atomic-oversize record still > budget after slim projection (fail-loud, zero dispatch).
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


def _greedy_pack(records: list, budget: int):
    """Greedy whole-record packing in the given (glob) order: flush the current
    part before any record that would push it over budget. Deterministic.
    Returns [(records, bytes), ...]. A part that still exceeds budget holds
    exactly one record (atomic oversize — the caller slim-projects or fails
    loud; a multi-record part is ≤ budget by construction)."""
    parts = []
    cur, cur_b = [], 0
    for r in records:
        rb = _byte_len([r])
        if cur and cur_b + rb > budget:
            parts.append((cur, cur_b))
            cur, cur_b = [], 0
        cur.append(r)
        cur_b += rb
    if cur:
        parts.append((cur, cur_b))
    return parts


def _shard_by_category(records: list, budget: int):
    """T2 sharding: one shard per category; a category whose own serialized
    size exceeds budget is further split whole-record (greedy, existing glob
    order — deterministic) into ≤-budget parts (`t2-<category>-part<N>`, N
    zero-padded from 0). Returns [(shard_id, categories, records, bytes,
    oversize, part_index, part_count)]; `oversize` is always False — every
    dispatched shard is ≤ budget by construction (atomic-oversize records are
    slim-projected / fail-loud in main(), design D3)."""
    by_cat = {}
    for r in records:
        cat = r.get("category") or "_uncategorized"
        by_cat.setdefault(cat, []).append(r)
    shards = []
    for cat in sorted(by_cat):
        recs = by_cat[cat]
        nbytes = _byte_len(recs)
        if nbytes <= budget:
            shards.append((f"t2-{_safe_name(cat)}", [cat], recs, nbytes, False, 0, 1))
            continue
        parts = _greedy_pack(recs, budget)
        n = len(parts)
        for i, (prec, pb) in enumerate(parts):
            shards.append((f"t2-{_safe_name(cat)}-part{i:02d}", [cat], prec, pb, False, i, n))
    return shards


def _shard_by_batch_cluster(records: list, budget: int):
    """scout-merge sharding: greedily pack batch records into ≤-budget shards
    (batch clusters). Part splitting is a t2-only feature — scout-merge's
    shard ids, envelope, and stdout stay byte-identical."""
    shards = []
    for n, (brecs, bb) in enumerate(_greedy_pack(records, budget)):
        shards.append((f"scout-merge-{n}", None, brecs, bb, bb > budget, 0, 1))
    return shards


# Deterministic slim-projection caps (serialized-value bytes) for an ATOMIC-
# oversize T1 record — a single record whose own bytes exceed the budget, which
# greedy packing cannot split. Prose fields only; `evidence` anchors and every
# other structural field are NEVER truncated (dedup anchors + validate_inventory
# contract). Deliberately not flags: the real lever is `--budget`, and the CLI
# contract surface must not grow (design D3).
_SLIM_FIELD_CAPS = {"description": 4096, "usage": 2048, "protects": 2048, "gaps": 1024}
_SLIM_ENTRY_POINTS_MAX = 16  # keep the first N entry_points


def _cap_str(s: str, cap: int) -> str:
    """Char-boundary truncation of a str so its JSON-serialized size stays
    ≤ cap bytes (2 quote bytes + the 3-byte ellipsis marker reserved),
    ending with an explicit ellipsis (visible truncation, deterministic)."""
    out, used = [], 0
    for ch in s:
        w = len(ch.encode("utf-8"))
        if used + w > cap - 5:
            break
        out.append(ch)
        used += w
    return "".join(out) + "…"


def _slim_record(rec: dict) -> dict:
    """Deterministic prose-slim projection for one atomic-oversize T1 record:
    truncate description/usage/protects/gaps (str and list forms) to
    _SLIM_FIELD_CAPS and entry_points to _SLIM_ENTRY_POINTS_MAX items; NEVER
    touches `evidence` or any other structural field. Mutates `rec` in place
    (the in-memory record feeding the materialized shard input only — the
    checkpoints/t1 original file is NEVER rewritten). Returns the truncation
    trace {field: original_serialized_bytes}; empty dict when nothing was cut."""
    touched = {}
    for field, cap in _SLIM_FIELD_CAPS.items():
        val = rec.get(field)
        if isinstance(val, str):
            orig = _byte_len(val)
            if orig <= cap:
                continue
            rec[field] = _cap_str(val, cap)
            touched[field] = orig
        elif isinstance(val, list):
            orig = _byte_len(val)
            if orig <= cap:
                continue
            kept = []
            for item in val:
                if _byte_len(kept + [item]) > cap:
                    break
                kept.append(item)
            rec[field] = kept
            touched[field] = orig
    ep = rec.get("entry_points")
    if isinstance(ep, list) and len(ep) > _SLIM_ENTRY_POINTS_MAX:
        touched["entry_points"] = _byte_len(ep)
        rec["entry_points"] = ep[:_SLIM_ENTRY_POINTS_MAX]
    return touched


def _write_shard_input(shards_dir: Path, shard_id: str, node: str, categories, records: list,
                       part_index=None, part_count=None):
    """Write `<shards-dir>/<shard_id>.input.json`; idempotent. Returns (abs path, bytes).
    part_index/part_count ride the t2 map-reduce envelope only (None = omit —
    scout-merge envelope unchanged, design D5)."""
    shards_dir.mkdir(parents=True, exist_ok=True)
    body = {"node": node, "shard_id": shard_id, "records": records}
    if part_index is not None:
        body["part_index"] = part_index
    if part_count is not None:
        body["part_count"] = part_count
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
                         "(+ input_path/bytes/oversize/part_index/part_count/slimmed; "
                         "slim envelope if omitted)")
    ap.add_argument("--offset", type=int, default=0, help="page offset (default 0)")
    ap.add_argument("--limit", type=int, default=None, help="max shards per page (default all)")
    ap.add_argument("--orch-budget-bytes", type=int, default=DEFAULT_ORCH_BUDGET_BYTES,
                    help=f"orchestrator single-request page byte cap (default "
                         f"{DEFAULT_ORCH_BUDGET_BYTES}; page auto-tightened + shrunk:true)")
    ap.add_argument("--include-failed", action="store_true",
                    help="re-list failed shards into pending[] under their canonical "
                         "shard_id with their existing .failed marker path (t2 node "
                         "only; identity from this enumerator's forward derivation, "
                         "never filename stems; opt-in for the dispatcher's "
                         "--retry-failed flow). Default off keeps stdout byte-identical")
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
    # `.mgh-init` always lives under `<target>/.mgh-init` → parent IS the repo anchor root.
    # Emitted (needs_reduce=true path only) so the dispatcher can run its spawn-time `_anchor_check`
    # against the same absolute root the fanout units write under (R5.3b path-drift guard).
    repo = init_dir.parent

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

    # Atomic-oversize guard (t2, design D3): an over-budget part holds exactly
    # one record whose own bytes greedy packing cannot split. Deterministic
    # slim projection runs on the in-memory record feeding the materialized
    # shard input (prose fields only; `evidence`/structural fields never
    # truncated; checkpoints/t1 originals NEVER rewritten). A record still over
    # budget beyond slimming is pathological (structural fields over the cap)
    # → fail-loud exit 2 BEFORE any materialization or listing (zero side
    # effects, zero dispatch of a doomed unit).
    slim_by_sid: dict = {}
    bytes_by_sid: dict = {}
    oversize_fatal = []
    if args.node == "t2":
        for sid, _cats, recs, nbytes, _ov, _pi, _pc in raw_shards:
            slim: dict = {}
            post = nbytes
            if nbytes > args.budget:
                for r in recs:
                    orig_b = _byte_len(r)
                    touched = _slim_record(r)
                    if touched:
                        r["_slimmed"] = touched
                        src = str(r.get("__source_file") or r.get("name") or "record")
                        slim[src] = {"original_bytes": orig_b, "truncated": touched}
                post = _byte_len(recs)
                if post > args.budget:
                    src = recs[0].get("__source_file") if recs else None
                    rpath = str(init_dir / "checkpoints" / "t1" / src) if src else sid
                    oversize_fatal.append((sid, rpath, post))
            slim_by_sid[sid] = slim
            bytes_by_sid[sid] = post
    if oversize_fatal:
        for sid, rpath, post in oversize_fatal:
            print(f"error: atomic-oversize record cannot fit budget even after slim "
                  f"projection: shard {sid} record {rpath} ({post}B > {args.budget}B) — "
                  f"structural fields beyond slim caps (pathological record); "
                  f"no units dispatched", file=sys.stderr)
        return 2

    # D2a (marker-aware enumeration for the t2 dispatcher only): `--node t2` is consumed by
    # fanout_runner --tier t2, whose wave loop converges by re-listing (pending shrinks) and whose
    # zero-progress circuit breaker needs marker-derived counts. So for t2: exclude terminal
    # (`.done`/`.failed`) shards from pending[] and emit total/done/failed. `summary_paths`/`shards`
    # stay FULL — rollup eats every shard summary and boundaries disclose the whole reduction. A
    # `.failed` shard is terminal and NOT retried; the orchestrator surfaces it (map not all-done →
    # report, do not rollup). scout-merge stays hand-paged → all shards listed (non-goal, unchanged).
    marker_aware = args.node == "t2"
    done_count = failed_count = 0
    pending = []
    summary_paths = []
    for sid, categories, recs, nbytes, oversize, part_index, part_count in raw_shards:
        cp = (shard_cp_dir / f"{sid}.json")
        cp_abs = str(cp)
        dm_abs = str(cp.with_name(cp.name + ".done"))
        # failed_marker: same dir as done_marker, file `.<shard_id>.json.failed` (dot-prefixed,
        # mirrors list_rule_jobs' `.<cat>.<fmt>.json.failed` shape). Dispatcher writes it on a
        # failed ack / pre-spawn path-drift; orchestrator/resume treat it as the unit's terminal
        # `.failed` state. ABSOLUTE — resolved above via shard_cp_dir (already absolute).
        fm_abs = str(cp.with_name("." + cp.name + ".failed"))
        terminal = False
        if marker_aware:
            if Path(dm_abs).is_file():
                done_count += 1
                terminal = True
            elif Path(fm_abs).is_file():
                failed_count += 1
                # --include-failed: the failed shard re-enters pending under
                # its canonical shard_id (fm_abs below is the same
                # forward-derived marker path; the dispatcher's --retry-failed
                # deletes it at claim). Default (flag off) keeps it terminal.
                terminal = not args.include_failed
        item = {
            "shard_id": sid, "node": args.node,
            "checkpoint_path": cp_abs, "done_marker": dm_abs, "failed_marker": fm_abs,
            "bytes": bytes_by_sid.get(sid, nbytes) if marker_aware else nbytes,
            "oversize": bool(oversize),
        }
        if marker_aware:
            item["part_index"] = part_index
            item["part_count"] = part_count
            item["slimmed"] = slim_by_sid.get(sid, {})
        if categories is not None:
            item["categories"] = categories
        else:
            item["batches"] = len(recs)
        if not terminal:
            if shards_dir:
                ipath, _ = _write_shard_input(
                    shards_dir, sid, args.node, categories, recs,
                    part_index if marker_aware else None,
                    part_count if marker_aware else None)
                item["input_path"] = ipath
                # t2 shards are ≤ budget by construction (split + slim + exit-2
                # gate above); an oversize shard can only be a scout-merge
                # batch cluster — its warn+send disclosure stays (hand-paged).
                if oversize:
                    print(f"warn: shard {sid} alone > budget ({nbytes}B > {args.budget}B) — cannot "
                          f"split further without losing whole-batch "
                          f"view; disclose in boundaries[]", file=sys.stderr)
            pending.append(item)
        summary_paths.append(cp_abs)

    req_limit = args.limit if args.limit is not None else len(pending)
    page = pending[args.offset: args.offset + max(0, req_limit)]
    page, eff, shrunk = _shrink_page(page, args.orch_budget_bytes)
    result = {
        "node": args.node, "repo": str(repo), "total_bytes": total_bytes, "budget": args.budget,
        "needs_reduce": True, "shards": len(raw_shards), "pending": page,
        "truncated": False, "offset": args.offset, "limit": req_limit,
        "effective_limit": eff, "shrunk": shrunk,
        "rollup": {"summary_paths": summary_paths,
                   "output": str(output), "done_marker": str(done_marker)},
        "note": (f"aggregate input {total_bytes}B > budget {args.budget}B — {len(raw_shards)} "
                 f"shard(s); per-shard partial then single rollup over summaries"),
    }
    if marker_aware:
        # Dispatcher expects list_*-style marker counts (total = done + failed + pending).
        result["total"] = len(raw_shards)
        result["done"] = done_count
        result["failed"] = failed_count
    print(f"[plan_aggregate] node={args.node} total={total_bytes}B budget={args.budget}B "
          f"-> map-reduce: {len(raw_shards)} shard(s); page offset={args.offset} eff={eff} "
          f"shrunk={shrunk}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
