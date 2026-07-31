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

Per-unit input materialization (`--materialize`, request-context-budget): each cluster's
COMPLETE input record (cluster fields + candidate hits looked up from controls_candidates.json)
is written to `<dir>/<unit>.input.json`; `pending[]` becomes a SLIM envelope carrying
`input_path`/`bytes`/`oversize` and NO variable-length payload (`evidence_files[]`/
`usage_sites[]`/hits sink into the input file). The orchestrator passes `input_path`
verbatim; the T1 subagent reads its own bounded file (NEVER the whole `clusters.json`).
Oversize clusters (> `--max-unit-bytes`) are sharded into `<cluster_id>::shard-<n>` units.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_clusters.py --clusters <clusters.json> [--checkpoints <t1-dir>]
       [--candidates <controls_candidates.json>] [--materialize <inputs-dir>]
       [--offset N] [--limit N] [--max-unit-bytes B] [--orch-budget-bytes B]

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"repo": "...", "total": N, "done": M, "failed": F, "pending": [<ClusterLite>, ...],
   "truncated": false, "offset": 0, "limit": K, "effective_limit": k, "shrunk": false}
  - total       = len(clusters[])             (the REAL count, not len(wrapper))
  - done        = #clusters fully complete (whole-cluster .done, or all shards .done)
  - failed      = #whole-cluster confirmed-failed units (`.failed` marker; terminal,
                  excluded from pending, NOT retried on --resume; done+failed+pending
                  = total for the non-sharded case). Crash with no `failed` ack leaves
                  no marker → unit stays pending (crash ≠ confirmed failure).
  - pending[]   = slim work items on the current page; each item (WITH --materialize):
      {cluster_id, category, kind, shape, candidate_count,
       input_path, checkpoint_path, done_marker, failed_marker, bytes, oversize}
    (WITHOUT --materialize: backward-compat lite shell retains `evidence_files[]`)
  - input_path     = ABSOLUTE per-unit input file (subagent reads this; ≤ --max-unit-bytes).
  - checkpoint_path = ABSOLUTE path the T1 subagent MUST write its checkpoint to
                      (<resolved --checkpoints>/<safe(unit)>.json; `safe` = `_safe_name`,
                      `/` `\` `:` → `_`); passed verbatim by the orchestrator so the
                      subagent NEVER assembles/interpolates a path.
  - done_marker     = ABSOLUTE `.done` marker path (<checkpoint_path>.done) to touch on success.
  - failed_marker   = ABSOLUTE `.failed` marker path (<checkpoint_path>.failed); the
                      orchestrator writes it (body {unit,reason,tier}) on a `failed` ack —
                      passed verbatim, NEVER self-assembled.
  - bytes/oversize  = input file size / whether it exceeded --max-unit-bytes (sharded).
  - truncated   = passthrough of the wrapper's `truncated` flag (no silent loss)
  - offset/limit/effective_limit/shrunk = paging (R5.3b); orchestrator advances offset
    by effective_limit. shrunk=true iff a page was auto-tightened to ≤ --orch-budget-bytes.

Exit codes (R5.3b): 0 ok (incl. empty clusters) · 1 clusters.json missing/malformed ·
2 misuse (argparse / bad budget). Idempotent, no TTY.
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

DEFAULT_MAX_UNIT_BYTES = 192 * 1024    # 192KB — aligns with --big-file-bytes 200KB
DEFAULT_ORCH_BUDGET_BYTES = 64 * 1024  # 64KB — orchestrator single-request page cap


def _parse_bytes(label: str, raw) -> int:
    """Non-negative integer byte budget; exit 2 on misuse (R5.3b)."""
    try:
        v = int(raw)
    except (TypeError, ValueError):
        print(f"error: {label} must be a non-negative integer (got {raw!r})", file=sys.stderr)
        return -1  # sentinel; caller re-checks >= 0
    if v < 0:
        print(f"error: {label} must be >= 0 (got {v})", file=sys.stderr)
        return -1
    return v


def _byte_len(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _done_ids(checkpoints_dir: Path):
    """Return the set of completed unit ids by reading each checkpoint record's
    `unit` field (robust to filename sanitization of cluster_id, which may contain
    `::` and `/`). Marker = `<id>.json.done`; record = `<id>.json` (sibling).
    Covers both whole-cluster ids and `<cid>::shard-<n>` shard ids."""
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


def _failed_ids(checkpoints_dir: Path):
    """Return the set of TERMINAL-FAILED unit ids (confirmed failure; excluded from
    `pending` and NOT retried on `--resume`). Marker = `<id>.json.failed` (sibling of
    `.done`); the orchestrator writes its body `{unit,reason,tier}` on a `failed` ack —
    `unit` is the canonical id, read here in-body so a failure that produced NO sibling
    record body is still matched (unlike `.done`, which is an empty touched marker that
    forces `_done_ids` to read the sibling record; `.failed` carries its unit in-body).
    Resolution: body `unit` → sibling record `unit` → filename-stem fallback. A crash
    with no `failed` ack leaves no marker → the unit stays `pending` and IS retried
    (crash ≠ confirmed terminal failure)."""
    failed = set()
    if not checkpoints_dir.is_dir():
        return failed
    for marker in sorted(checkpoints_dir.glob("*.json.failed")):
        record = marker.with_suffix("")  # strip ".failed" → <id>.json (sibling)
        unit = None
        try:
            body = json.loads(marker.read_text(encoding="utf-8"))
            if isinstance(body, dict):
                unit = body.get("unit") or None
        except (OSError, ValueError):
            unit = None
        if not unit and record.is_file():  # fall back to the sibling record's `unit`
            try:
                unit = json.loads(record.read_text(encoding="utf-8")).get("unit") or None
            except (OSError, ValueError):
                unit = None
        if not unit:
            unit = record.stem  # sanitized filename; best-effort (no body + no record)
        failed.add(unit)
    return failed


def _load_candidates(path):
    """{candidate_id: candidate} from controls_candidates.json; {} if absent/unreadable
    (materialization degrades to cluster-fields-only input with a stderr note)."""
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        print(f"warn: --candidates not found: {p}; input files carry cluster fields only",
              file=sys.stderr)
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"warn: malformed --candidates, ignoring: {e}", file=sys.stderr)
        return {}
    cands = data.get("candidates") if isinstance(data, dict) else data
    if not isinstance(cands, list):
        return {}
    return {c["id"]: c for c in cands if isinstance(c, dict) and c.get("id")}


def _safe_name(unit_id: str) -> str:
    """Filesystem-safe encoding of a unit_id for an INPUT filename. cluster_ids (and
    `<cid>::shard-<n>` ids) contain `::`, which is NTFS's Alternate-Data-Stream separator
    (write fails with errno 22 on Windows). The canonical unit_id stays as the envelope
    identity + checkpoint `unit` field; only the input FILENAME is encoded."""
    return unit_id.replace("/", "_").replace("\\", "_").replace(":", "_")


def _cluster_header(cluster: dict) -> dict:
    return {
        "cluster_id": cluster.get("cluster_id"),
        "category": cluster.get("category"),
        "kind": cluster.get("kind"),
        "shape": cluster.get("shape"),
        "evidence_files": cluster.get("evidence_files", []),
        "usage_sites": cluster.get("usage_sites", []),
    }


def _resolve_units(cid: str, cluster: dict, hits: list, max_unit_bytes: int,
                   inputs_dir: Path):
    """Materialize one cluster into ≥1 bounded units. Returns list of
    (unit_id, input_path, bytes, oversize). Whole cluster if ≤ budget; else sharded by
    candidate-hit groups into `<cid>::shard-<n>` (each ≤ budget). Idempotent overwrite."""
    full = dict(_cluster_header(cluster), candidates=hits)
    if _byte_len(full) <= max_unit_bytes or not hits:
        return [_write_unit(inputs_dir, cid, full)]
    # oversize: shard candidate hits greedily; header repeats per shard (small).
    header = _cluster_header(cluster)
    header_bytes = _byte_len(header)
    shards, cur, cur_b, n = [], [], header_bytes, 0
    for h in hits:
        hb = _byte_len(h)
        if cur and cur_b + hb > max_unit_bytes:
            shards.append((n, dict(header, candidates=cur)))
            n += 1
            cur, cur_b = [], header_bytes
        cur.append(h)
        cur_b += hb
    if cur:
        shards.append((n, dict(header, candidates=cur)))
    units = []
    for sn, inp in shards:
        uid = f"{cid}::shard-{sn}"
        units.append(_write_unit(inputs_dir, uid, inp))
    print(f"warn: cluster {cid} oversize ({_byte_len(full)}B > {max_unit_bytes}B) → "
          f"{len(units)} shard(s)", file=sys.stderr)
    return units


def _write_unit(inputs_dir: Path, unit_id: str, inp: dict):
    """Write `<inputs_dir>/<unit_id>.input.json` (idempotent overwrite); return
    (unit_id, abs input_path, file bytes, oversize_flag=False — caller sets oversize
    via shard decision)."""
    inputs_dir.mkdir(parents=True, exist_ok=True)
    path = (inputs_dir / f"{_safe_name(unit_id)}.input.json").resolve()
    body = json.dumps(inp, ensure_ascii=False, indent=2)
    path.write_text(body, encoding="utf-8")
    return unit_id, str(path), path.stat().st_size


def _paths(checkpoints_dir: Path, unit_id: str):
    # Filename component is `_safe_name`-encoded (same as input filenames): cluster_ids /
    # shard ids carry `::` (NTFS Alternate-Data-Stream separator → write fails with
    # errno 22 on Windows). The canonical unit_id stays as envelope `cluster_id` + the
    # checkpoint record's `unit` field; only the FILENAME is encoded (done detection reads
    # the record's `unit` field, not the filename → resume matching unaffected).
    base = (checkpoints_dir / f"{_safe_name(unit_id)}.json")
    return (str(base),
            str(base.with_name(base.name + ".done")),
            str(base.with_name(base.name + ".failed")))


def _slim_materialized(cluster: dict, unit_id: str, hit_count: int,
                       input_path: str, nbytes: int, oversize: bool,
                       checkpoints_dir: Path) -> dict:
    cp, dm, fm = _paths(checkpoints_dir, unit_id)
    return {
        "cluster_id": unit_id,
        "category": cluster.get("category"),
        "kind": cluster.get("kind"),
        "shape": cluster.get("shape"),
        "candidate_count": hit_count,
        "input_path": input_path,
        "checkpoint_path": cp,
        "done_marker": dm,
        "failed_marker": fm,
        "bytes": nbytes,
        "oversize": oversize,
    }


def _lite(cluster: dict, checkpoints_dir: Path) -> dict:
    """Backward-compat lite shell (no --materialize): retains evidence_files[]."""
    cid = cluster.get("cluster_id")
    cp, dm, fm = _paths(checkpoints_dir, cid)
    return {
        "cluster_id": cid,
        "category": cluster.get("category"),
        "kind": cluster.get("kind"),
        "shape": cluster.get("shape"),
        "evidence_files": cluster.get("evidence_files", []),
        "candidate_count": len(cluster.get("candidate_ids", [])),
        "checkpoint_path": cp,
        "done_marker": dm,
        "failed_marker": fm,
    }


def _shrink_page(page: list, orch_budget: int):
    """Tighten a page so its serialized bytes ≤ orch_budget (keep ≥1 item). Returns
    (page, effective_limit, shrunk)."""
    if orch_budget <= 0 or not page:
        return page, len(page), False
    eff = len(page)
    while eff > 1 and _byte_len(page[:eff]) > orch_budget:
        eff -= 1
    return page[:eff], eff, eff < len(page)


def main():
    ap = argparse.ArgumentParser(
        description="list pending T1 clusters from clusters.json (deterministic work-list)")
    ap.add_argument("--clusters", required=True,
                    help="path to clusters.json (wrapper dict {repo,clusters,truncated})")
    ap.add_argument("--checkpoints",
                    help="T1 checkpoint dir (default: <clusters>/../checkpoints/t1)")
    ap.add_argument("--candidates",
                    help="controls_candidates.json (for --materialize hit lookup)")
    ap.add_argument("--materialize", metavar="<inputs-dir>",
                    help="write each cluster's complete input to <dir>/<unit>.input.json "
                         "(slim envelope + input_path/bytes/oversize; backward-compat lite shell if omitted)")
    ap.add_argument("--offset", type=int, default=0, help="page offset (default 0)")
    ap.add_argument("--limit", type=int, default=None,
                    help="max items per page (default: all pending)")
    ap.add_argument("--max-unit-bytes", type=int, default=DEFAULT_MAX_UNIT_BYTES,
                    help=f"per-unit input byte cap (default {DEFAULT_MAX_UNIT_BYTES}; "
                         f"oversize clusters sharded into ::shard-<n>)")
    ap.add_argument("--orch-budget-bytes", type=int, default=DEFAULT_ORCH_BUDGET_BYTES,
                    help=f"orchestrator single-request page byte cap (default "
                         f"{DEFAULT_ORCH_BUDGET_BYTES}; page auto-tightened + shrunk:true)")
    args = ap.parse_args()

    if args.offset < 0:
        print("error: --offset must be >= 0", file=sys.stderr)
        return 2
    for label, raw in (("--max-unit-bytes", args.max_unit_bytes),
                       ("--orch-budget-bytes", args.orch_budget_bytes)):
        v = _parse_bytes(label, raw)
        if v < 0:
            return 2

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
    failed = _failed_ids(checkpoints_dir)
    materialize = bool(args.materialize)
    cands = _load_candidates(args.candidates) if materialize else {}
    inputs_dir = Path(args.materialize).resolve() if materialize else None

    all_units = []          # full slim work-list (pre-page)
    clusters_with_pending = 0
    clusters_failed = 0
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        cid = cluster.get("cluster_id")
        if cid in done:  # whole-cluster complete (terminal)
            continue
        if cid in failed:  # whole-cluster confirmed-failed (terminal; NOT retried)
            clusters_failed += 1
            continue
        emitted = False
        if materialize:
            hits = [cands[i] for i in cluster.get("candidate_ids", []) if i in cands]
            for uid, ipath, nbytes in _resolve_units(cid, cluster, hits,
                                                     args.max_unit_bytes, inputs_dir):
                if uid in done:
                    continue
                if uid in failed:  # shard-level terminal failure (skip, not retried)
                    continue
                shard = uid != cid
                all_units.append(_slim_materialized(
                    cluster, uid, len(hits) if not shard else _shard_hit_count(inputs_dir, uid),
                    ipath, nbytes, shard, checkpoints_dir))
                emitted = True
        else:
            all_units.append(_lite(cluster, checkpoints_dir))
            emitted = True
        if emitted:
            clusters_with_pending += 1

    total = len(clusters)
    done_count = total - clusters_with_pending - clusters_failed
    req_limit = args.limit if args.limit is not None else len(all_units)
    page = all_units[args.offset: args.offset + max(0, req_limit)]
    page, eff, shrunk = _shrink_page(page, args.orch_budget_bytes)
    result = {
        "repo": wrapper.get("repo"),
        "total": total,
        "done": done_count,
        "failed": clusters_failed,
        "pending": page,
        "truncated": bool(wrapper.get("truncated", False)),
        "offset": args.offset,
        "limit": req_limit,
        "effective_limit": eff,
        "shrunk": shrunk,
    }
    print(f"clusters.json: {total} total, {done_count} done, {clusters_failed} failed, "
          f"{len(all_units)} pending unit(s); page offset={args.offset} eff={eff} "
          f"shrunk={shrunk} (checkpoints: {checkpoints_dir})", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _shard_hit_count(inputs_dir: Path, uid: str) -> int:
    """Count candidates in a written shard input (best-effort; falls back to 0)."""
    p = inputs_dir / f"{_safe_name(uid)}.input.json"
    try:
        return len(json.loads(p.read_text(encoding="utf-8")).get("candidates", []))
    except (OSError, ValueError):
        return 0


if __name__ == "__main__":
    sys.exit(main())
