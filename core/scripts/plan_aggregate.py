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
    `t2-<category>-part<N>`; scout-merge by stable-order greedy packing at CANDIDATE
    granularity), --materialize writes each shard's bounded input, and emits per-shard
    checkpoint paths. The orchestrator fans out one partial-synthesis subagent per shard
    (bounded input, bounded ack) then a single rollup
    subagent that consumes ONLY the shard summaries — every model request ≤ budget.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py plan_aggregate.py --node t2|scout-merge --init-dir <dir>
       [--budget B] [--materialize <shards-dir>] [--offset N] [--limit N] [--orch-budget-bytes B]

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"node":"t2|scout-merge","repo":"<abs target>","total_bytes":N,"budget":B,
   "needs_reduce":bool,"shards":K,
   "pending":[<Shard>,...],"truncated":false,"offset":0,"limit":K,"effective_limit":k,"shrunk":false,
   "rollup":{"summary_paths_manifest":"<abs rollup_manifest.json>","output":"<abs>","done_marker":"<abs>"}}
  - needs_reduce=false → pending=[] + rollup omitted; orchestrator uses single-context init-synthesis
    / init-scout-merge directly (existing path). This path is BYTE-IDENTICAL to the pre-map-reduce
    release (no repo / failed_marker added) — single-context callers read the same fields.
  - needs_reduce=true → the FULL shard-summary path set rides the materialized
    `rollup_manifest.json` (atomic, idempotent; the rollup subagent Reads it) — stdout carries only
    the manifest ABSOLUTE PATH, never the array (1000 shards ≈ 100KB would punch through the
    `--orch-budget-bytes` single-reply promise; the orchestrator passes the manifest path verbatim
    and NEVER reads it — R5.2).
  - Shard item: {shard_id, node, categories (t2) | batches (scout-merge: deduped list of
    batch_ids the shard covers), input_path, bytes, oversize, checkpoint_path, done_marker,
    failed_marker}  (all ABSOLUTE; passed verbatim by the
    orchestrator). t2 map-reduce items additionally carry part_index/part_count (part-split
    disclosure; 0/1 when the category was not split); both nodes carry slimmed ({} or the
    atomic-oversize slim-projection trace {record: {original_bytes, truncated: {field:
    original_bytes}}}).
    A dispatched shard is ALWAYS ≤ budget at BOTH nodes: t2 splits an over-budget category
    into parts; scout-merge packs candidates greedily across batch boundaries; an atomic-
    oversize unit (a single record / candidate whose own bytes exceed budget) is
    deterministically slim-projected at materialization (prose fields only; `evidence`
    anchors and other structural fields never truncated; checkpoints/t1|scout originals
    NEVER rewritten) or the run exits 2 —
    so `oversize` is always false (field kept for stdout compat; the old
    "warn + dispatch oversize anyway" path is removed at both nodes).
    repo (needs_reduce=true only) = `--init-dir` resolve parent — `.mgh-init` always
    lives under <target>/.mgh-init, so repo == <target> absolute root (anchor for the dispatcher's
    `_anchor_check`). failed_marker = same directory as done_marker, file `.<shard_id>.json.failed`
    (written by the dispatcher when a unit fails / drifts out of the repo anchor tree).
  - Both aggregate nodes (dispatcher adoption): the enumerator is
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
import os
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). plan_aggregate currently has no sibling import,
# but the guard keeps it in the self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_BUDGET = 96 * 1024           # 96KB (= 98304) — --max-aggregate-bytes default. Sized for
# the worst-case ~150K-token intranet model windows: worst CJK-dense packing is ~2 bytes/token
# (repo token heuristic), so one dispatched aggregate shard ≤ ~48K input tokens — far below the
# 120K red line once stage prompt + bounded ack are added. Explicit --budget overrides (big
# -window models may raise it); see contracts/init/aggregate-sharding.md.
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


def _atomic_write_text(path: Path, text: str):
    """Same-directory tmp + os.replace — atomic on POSIX and Windows; a crash
    mid-write leaves the previous file intact, never a truncated manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


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


def _t2_body(sid: str, cat: str, recs: list, part_index: int, part_count: int) -> dict:
    """The EXACT envelope `_write_shard_input` serializes for one t2 shard (same
    key order: node, shard_id, records, part_index, part_count, categories), so
    budget decisions measure the same bytes that land on disk. `sid` is passed
    by the caller (the split branch ALWAYS uses the `t2-<cat>-part<N>` form,
    even for a single part) — deriving it from part_count here would measure a
    different id than the file carries."""
    return {"node": "t2", "shard_id": sid, "records": recs,
            "part_index": part_index, "part_count": part_count, "categories": [cat]}


def _t2_part_seal_bytes(cat: str, part_recs: list, n_records: int) -> int:
    """Materialized-caliber size of a SPLIT part's on-disk body, with the shard
    id / part_count digit widths pinned to the worst case this category can
    produce (conservative by a couple of bytes) so the greedy seal decision can
    never under-measure the final file. The budget caliber is MATERIALIZED
    (H8): the pre-fix compact measure let a ≤-budget-compact part materialize
    ~1.23× over budget (indent + envelope + CRLF), so every dispatched shard
    file broke the hard bound."""
    digits = max(2, len(str(max(0, n_records - 1))))
    sid = f"t2-{_safe_name(cat)}-part{'0' * digits}"
    return _materialized_bytes({"node": "t2", "shard_id": sid, "records": part_recs,
                                "part_index": 0, "part_count": n_records,
                                "categories": [cat]})


def _shard_by_category(records: list, budget: int):
    """T2 sharding: one shard per category; a category whose own MATERIALIZED
    size exceeds budget is further split whole-record (greedy, existing glob
    order — deterministic, sealed on the materialized caliber) into ≤-budget
    parts (`t2-<category>-part<N>`, N zero-padded from 0). Returns
    [(shard_id, categories, records, bytes, oversize, part_index, part_count)];
    `bytes` is the MATERIALIZED body size (what the file will weigh — compact
    serialization under-reported ~1.23×, H8) and `oversize` is always False —
    every dispatched shard is ≤ budget by construction (atomic-oversize records
    are slim-projected / fail-loud in main(), design D3)."""
    by_cat = {}
    for r in records:
        cat = r.get("category") or "_uncategorized"
        by_cat.setdefault(cat, []).append(r)
    shards = []
    for cat in sorted(by_cat):
        recs = by_cat[cat]
        whole_sid = f"t2-{_safe_name(cat)}"
        whole = _materialized_bytes(_t2_body(whole_sid, cat, recs, 0, 1))
        if whole <= budget:
            shards.append((whole_sid, [cat], recs, whole, False, 0, 1))
            continue
        parts, cur = [], []
        for r in recs:
            if cur and _t2_part_seal_bytes(cat, cur + [r], len(recs)) > budget:
                parts.append(cur)
                cur = []
            cur.append(r)
        if cur:
            parts.append(cur)
        n = len(parts)
        for i, prec in enumerate(parts):
            sid = f"t2-{_safe_name(cat)}-part{i:02d}"
            shards.append((sid, [cat], prec,
                           _materialized_bytes(_t2_body(sid, cat, prec, i, n)),
                           False, i, n))
    return shards


def _materialized_bytes(body: dict) -> int:
    """Exact on-disk size of what `_write_shard_input` writes (utf-8 text mode):
    the scout-merge packer measures with THIS so the hard invariant "every
    dispatched shard input file ≤ budget" holds for the FILE, not just the
    in-memory payload (Windows text mode translates each structural `\\n` to
    `\\r\\n`; JSON string values carry no raw newlines — only indent ones)."""
    s = json.dumps(body, ensure_ascii=False, indent=2)
    if "\r\n" != "\n":
        s = s.replace("\n", "\r\n")
    return len(s.encode("utf-8"))


# Scout-merge candidate slim caps (D2): prose/evidence fields only. Structural
# fields (file/line/anchor/category/kind/source/id) are NEVER touched — they are
# merge_scout._key's dedup anchors and `merge_scout.py --check`'s validated surface.
_SCOUT_SLIM_CAPS = {"evidence_snippet": 4096, "snippet": 4096}
_SCOUT_SLIM_ENTRY_POINTS_MAX = 16


def _slim_scout_candidate(c) -> dict:
    """Deterministic prose-slim projection for ONE atomic-oversize scout candidate
    (an individual candidate whose own bytes exceed the budget). Mutates the
    in-memory copy feeding the materialized shard input — the checkpoints/scout
    original is NEVER rewritten. Returns the truncation trace {field:
    original_serialized_bytes}; empty dict when nothing was cut."""
    if not isinstance(c, dict):
        return {}
    touched = {}
    for field, cap in _SCOUT_SLIM_CAPS.items():
        val = c.get(field)
        if isinstance(val, str):
            orig = _byte_len(val)
            if orig <= cap:
                continue
            c[field] = _cap_str(val, cap)
            touched[field] = orig
    ep = c.get("entry_points")
    if isinstance(ep, list) and len(ep) > _SCOUT_SLIM_ENTRY_POINTS_MAX:
        touched["entry_points"] = _byte_len(ep)
        c["entry_points"] = ep[:_SCOUT_SLIM_ENTRY_POINTS_MAX]
    if touched:
        c["_slimmed"] = touched
    return touched


def _scout_batch_id(rec: dict) -> str:
    src = str(rec.get("__source_file") or "")
    return str(rec.get("batch_id") or Path(src).stem or "record")


def _scout_record_payloads(cur_by_src: dict) -> list:
    """Shard records in first-seen order; each payload keeps the original record's
    non-list fields (incl. __source_file / batch_id) plus THIS shard's candidate
    subset and, on the shard where the batch's unresolved item landed, its
    unresolved list."""
    recs = []
    for src, slot in cur_by_src.items():
        payload = dict(slot["base"])
        if slot["has_cands"]:
            payload["candidates"] = slot["candidates"]
        if slot["unresolved"] is not None:
            payload["unresolved"] = slot["unresolved"]
        recs.append(payload)
    return recs


def _shard_by_candidate(records: list, budget: int, init_dir: Path):
    """scout-merge sharding (D2 hard bound): stable-order greedy packing at
    CANDIDATE granularity — items stream in (record glob order, in-record
    candidate order); a batch's `unresolved` rides one item right after its
    candidates (so an unsplit batch stays whole; a split batch's unresolved
    lands on the shard of its last candidate). Every shard's MATERIALIZED
    input is ≤ budget by construction (envelope included in the measure).
    An individual candidate over budget alone → deterministic slim projection
    (same three-level ladder as t2); still over → recorded as a fatal.
    Returns (shards, slim_by_sid, bytes_by_sid, oversize_fatal) with the same
    7-tuple shape as _shard_by_category — slot 2 carries the shard's deduped
    batch_id list (the `batches` envelope field), part_index/part_count are
    fixed 0/1 (candidate packing has no part concept)."""
    shards, slim_by_sid, bytes_by_sid, fatals = [], {}, {}, []
    cur_by_src: dict = {}      # src -> {"base","has_cands","candidates","unresolved"}
    cur_seen: list = []        # (src, batch_id) in shard order (for `batches`)
    slim_trace: dict = {}

    def _cur_size() -> int:
        sid = f"scout-merge-{len(shards)}"
        return _materialized_bytes({"node": "scout-merge", "shard_id": sid,
                                    "records": _scout_record_payloads(cur_by_src)})

    def _slot(rec: dict):
        src = str(rec.get("__source_file") or "")
        slot = cur_by_src.get(src)
        if slot is None:
            base = {k: v for k, v in rec.items() if k not in ("candidates", "unresolved")}
            slot = {"base": base, "has_cands": False, "candidates": [], "unresolved": None}
            cur_by_src[src] = slot
            cur_seen.append((src, _scout_batch_id(rec)))
        return slot

    def _snapshot():
        """Deep-enough copy of the mutable shard accumulator for rollback: slots
        are dicts holding lists, a shallow `dict(cur_by_src)` would share the
        candidates list and undo nothing."""
        return ({src: {"base": dict(s["base"]), "has_cands": s["has_cands"],
                       "candidates": list(s["candidates"]), "unresolved": s["unresolved"]}
                 for src, s in cur_by_src.items()},
                list(cur_seen), dict(slim_trace))

    def _restore(snap):
        cur_by_src.clear(); cur_by_src.update(snap[0])
        cur_seen.clear(); cur_seen.extend(snap[1])
        slim_trace.clear(); slim_trace.update(snap[2])

    def _close():
        if not cur_by_src:
            return
        sid = f"scout-merge-{len(shards)}"
        recs = _scout_record_payloads(cur_by_src)
        size = _materialized_bytes({"node": "scout-merge", "shard_id": sid, "records": recs})
        batches = list(dict.fromkeys(bid for _src, bid in cur_seen))
        shards.append((sid, batches, recs, size, False, 0, 1))
        slim_by_sid[sid] = dict(slim_trace)
        bytes_by_sid[sid] = size
        cur_by_src.clear()
        cur_seen.clear()
        slim_trace.clear()

    for rec in records:
        cands = rec.get("candidates")
        if not isinstance(cands, list):
            items = [("rec", rec, None, 0)]
        else:
            items = [("cand", rec, c, i) for i, c in enumerate(cands)]
            if "unresolved" in rec:
                items.append(("unres", rec, rec.get("unresolved"), 0))
        for kind, owner, payload, ordinal in items:
            def _add():
                slot = _slot(owner)
                if kind == "cand":
                    slot["has_cands"] = True
                    slot["candidates"].append(payload)
                elif kind == "unres":
                    slot["unresolved"] = payload
                else:  # "rec" — non-candidate-shaped record, indivisible
                    slot["base"].update({k: v for k, v in owner.items()
                                         if k not in ("candidates", "unresolved")})
                    if isinstance(owner.get("candidates"), list):
                        slot["has_cands"] = True
                        slot["candidates"] = list(owner["candidates"])
                    if "unresolved" in owner:
                        slot["unresolved"] = owner["unresolved"]

            def _fatal():
                src = str(owner.get("__source_file") or "")
                rpath = str(init_dir / "checkpoints" / "scout" / src) if src else "record"
                fatals.append((f"scout-merge-{len(shards)}", rpath, _cur_size()))

            snap = _snapshot()
            _add()
            if _cur_size() > budget:
                # The item may be what pushes the shard over: roll back, close the
                # current shard, retry the item alone in a fresh one.
                _restore(snap)
                if cur_by_src:
                    _close()
                _add()
                if _cur_size() > budget:
                    if kind == "cand":
                        orig = _byte_len(payload)
                        touched = _slim_scout_candidate(payload)
                        if touched:
                            isrc = str(owner.get("__source_file") or "record")
                            slim_trace[f"{isrc}#{ordinal}"] = {
                                "original_bytes": orig, "truncated": touched}
                    if _cur_size() > budget:
                        _fatal()
    _close()
    return shards, slim_by_sid, bytes_by_sid, fatals


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
    part_index/part_count/categories ride the t2 map-reduce envelope only (None =
    omit — scout-merge envelope stays {node, shard_id, records}, design D2)."""
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
                         f"96KB = --max-aggregate-bytes; worst-case ~2 bytes/token → "
                         f"≤ ~48K tokens per dispatched shard); over it → map-reduce")
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
                         "shard_id with their existing .failed marker path (aggregate "
                         "nodes t2/scout-merge; identity from this enumerator's forward "
                         "derivation, never filename stems; opt-in for the dispatcher's "
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
    if args.limit is not None and args.limit < 1:
        # an empty page with effective_limit=0 would report SUCCESS and spin an
        # offset-advancing orchestrator forever (validation symmetric with --offset)
        print(f"error: --limit must be >= 1 (got {args.limit}). recipe: omit --limit "
              f"for the full shard list, or pass >= 1", file=sys.stderr)
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
        shard_fn = _shard_by_candidate
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

    # Both aggregate nodes hard-bound their dispatched shards (t2: category
    # split + record-granularity parts + slim; scout-merge: candidate-
    # granularity packing + slim). The packers report slim traces and atomic-
    # oversize fatals differently, so scout-merge gets its own call; t2's post-
    # hoc slim pass stays below. Either way a fatal exits 2 BEFORE any
    # materialization or listing (zero side effects, zero dispatch of a doomed
    # unit) — the "warn + dispatch anyway" path is retired for both nodes.
    slim_by_sid: dict = {}
    bytes_by_sid: dict = {}
    oversize_fatal = []
    if args.node == "scout-merge":
        raw_shards, slim_by_sid, bytes_by_sid, oversize_fatal = \
            _shard_by_candidate(records, args.budget, init_dir)
    else:
        raw_shards = shard_fn(records, args.budget)
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
                # post-slim size on the SAME materialized caliber the shard
                # decision used (compact `_byte_len` under-reported the file);
                # sid rides the tuple — split parts keep their partNN id
                cat = _cats[0] if _cats else sid
                post = _materialized_bytes(_t2_body(sid, cat, recs, _pi, _pc))
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
    # zero-progress circuit breaker needs marker-derived counts. So for both aggregate
    # nodes (t2 and the now dispatcher-consumed scout-merge): exclude terminal
    # (`.done`/`.failed`) shards from pending[] and emit total/done/failed. The rollup
    # manifest keeps the FULL shard set (rollup eats every shard summary and boundaries
    # disclose the whole reduction). A `.failed` shard is terminal and NOT retried; the
    # orchestrator surfaces it (map not all-done → report, do not rollup).
    shards_dir = Path(args.materialize).resolve() if args.materialize else None
    marker_aware = args.node in ("t2", "scout-merge")
    is_t2 = args.node == "t2"
    done_count = failed_count = 0
    pending = []
    summary_paths = []
    for sid, groups, recs, nbytes, oversize, part_index, part_count in raw_shards:
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
            "bytes": bytes_by_sid.get(sid, nbytes),
            "oversize": bool(oversize),
        }
        if marker_aware:
            item["slimmed"] = slim_by_sid.get(sid, {})
        if is_t2:
            # part 身份是 t2 category-partition 专属;scout-merge 候选装箱无 part 概念。
            item["part_index"] = part_index
            item["part_count"] = part_count
            item["categories"] = groups
        else:
            # scout-merge: `batches` = 该 shard 覆盖的去重 batch_id 列表(旧 int 计数废除)。
            item["batches"] = groups
        if not terminal:
            if shards_dir:
                ipath, fbytes = _write_shard_input(
                    shards_dir, sid, args.node, groups if is_t2 else None, recs,
                    part_index if is_t2 else None,
                    part_count if is_t2 else None)
                item["input_path"] = ipath
                # `bytes` = the MATERIALIZED file's actual size (H8): the compact
                # measure under-reported what the dispatched subagent will read.
                item["bytes"] = fbytes
                # Every dispatched shard is ≤ budget by construction at BOTH
                # nodes (t2: split+slim+exit-2 on the materialized caliber;
                # scout-merge: candidate packing +slim+exit-2, measured on the
                # materialized file) — the warn+dispatch-anyway disclosure path
                # is retired.
            pending.append(item)
        summary_paths.append(cp_abs)

    req_limit = args.limit if args.limit is not None else len(pending)
    page = pending[args.offset: args.offset + max(0, req_limit)]
    page, eff, shrunk = _shrink_page(page, args.orch_budget_bytes)
    # rollup manifest (M5): the FULL summary-path set rides a materialized file,
    # never stdout — 1000 shards ≈ 100KB of paths would punch through the
    # `--orch-budget-bytes` single-reply promise. The rollup SUBAGENT reads the
    # manifest (an in-tree Read, tree-confinement-legal); the orchestrator only
    # passes its absolute path verbatim and NEVER opens it (R5.2 introspection
    # ban). Atomic + idempotent: same full set every run (summary_paths is
    # marker-independent), so a re-dispatch overwrites identical content.
    manifest_path = shard_cp_dir / "rollup_manifest.json"
    _atomic_write_text(manifest_path, json.dumps(
        {"summary_paths": summary_paths,
         "output": str(output), "done_marker": str(done_marker)},
        ensure_ascii=False, indent=2))
    result = {
        "node": args.node, "repo": str(repo), "total_bytes": total_bytes, "budget": args.budget,
        "needs_reduce": True, "shards": len(raw_shards), "pending": page,
        "truncated": False, "offset": args.offset, "limit": req_limit,
        "effective_limit": eff, "shrunk": shrunk,
        "rollup": {"summary_paths_manifest": str(manifest_path),
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
