#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
r"""
list_clusters — deterministic T1 work-list producer for /mgh-init.

Reads the wrapper dict `clusters.json` ({repo, clusters[], truncated}) and the T1
checkpoint dir, then prints the authoritative pending work-list as JSON on stdout.
Replaces hand-rolled `py -c "import json..."` introspection in the orchestrator
(R5.2: orchestrator invokes leaf scripts via Bash; MUST NOT hand-roll JSON mining,
MUST NOT `len()` the wrapper — that yields 3, the top-level key count, not the
cluster count).

Scout-tier gate (deterministic tier ordering): when `<clusters.json 同目录>/run_config.json`
exists with `no_scout` falsy (scout enabled) and the scout tier is NOT complete
(`init_tier.scout_complete`), list_clusters refuses to emit a T1 work-list — exit 2 +
stdout `{"error":"scout-incomplete-gate",...}` + stderr recipe — so the orchestrator
CANNOT fan out T1 on a regex-only cluster set (the stranded-scout failure). run_config
absent (bare clusters.json / test fixture) or `no_scout` true → gate skipped (can't judge
scout intent / explicit regex-only is legal).

Per-unit input materialization (`--materialize`, request-context-budget): each cluster's
COMPLETE input record (cluster fields + candidate hits looked up from controls_candidates.json)
is written to `<dir>/<unit>.input.json`; `pending[]` becomes a SLIM envelope carrying
`input_path`/`bytes`/`oversize` and NO variable-length payload (`evidence_files[]`/
`usage_sites[]`/hits sink into the input file). The orchestrator passes `input_path`
verbatim; the T1 subagent reads its own bounded file (NEVER the whole `clusters.json`).
Oversize clusters (> `--max-unit-bytes`) are sharded into `<cluster_id>::shard-<n>` units.
The input filename stem is length-capped (`_safe_name`, ≤ 200 chars keeping a ~60-char
discriminant tail) so ANY cluster_id — including legacy overlong ids from pre-bound discover
runs — yields a writable file. A single cluster whose materialization write fails is ISOLATED:
its `.failed` terminal marker is written + `failed` count +1 + the batch continues (exit 0);
a `.failed` marker that also cannot be written → exit 2 fail-loud (systemic run-dir damage).

Deterministic small-cluster packing (`--pack-bytes`, opt-in quota amortization): with
`--pack-bytes B > 0` (+ `--pack-max N` member cap, default 8) the enumeration unit shifts
from the cluster to the PACK — same-category clusters whose whole-cluster input fits
`--max-unit-bytes` are sorted by `(bytes asc, cluster_id)` and greedily packed up to the
byte cap; oversize/`::shard-<n>` units and terminal-failed clusters NEVER enter a pack.
Pack id = `pack::<category[:64]>::<sha8(sorted member ids)>` — partition and id are PURE
functions of `clusters.json` + the flag values (same input, same packs, stable across
runs; marker state never influences identity). Each pending pack carries ONE merged input
file (`members[]` = full cluster records, `checkpoints[]` = per-member checkpoint/done
paths) so one subagent context amortizes its fixed call overhead over several clusters;
member-level `.done` markers stay the ONLY truth source and the recovery granularity
(a re-dispatched pack skips already-done members via the task template; the pack is
pending iff ≥1 member marker is missing). `total` = dispatch units (packs + independent
oversize/shard clusters); stdout adds `cluster_total`/`cluster_done` cluster-level
disclosure. A pack whose merged input cannot be written is excluded from `pending[]`
with a stderr warning (batch continues, exit code unchanged). Off (`--pack-bytes 0`,
the default) the legacy per-cluster path runs byte-identical — no new fields, zero pack
code executed.

Zero runtime deps (Python >=3.10 stdlib: argparse/hashlib/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_clusters.py --clusters <clusters.json> [--checkpoints <t1-dir>]
       [--candidates <controls_candidates.json>] [--materialize <inputs-dir>]
       [--offset N] [--limit N] [--max-unit-bytes B] [--orch-budget-bytes B]
       [--pack-bytes B] [--pack-max N]

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"repo": "...", "total": N, "done": M, "failed": F, "pending": [<ClusterLite>, ...],
   "truncated": false, "offset": 0, "limit": K, "effective_limit": k, "shrunk": false}
  packing mode adds: "cluster_total": C, "cluster_done": D  (cluster-level counts; never
  present on the off path)
  - total       = len(clusters[])             (the REAL count, not len(wrapper))
  - done        = #canonical units whose `.done` marker exists (FORWARD marker-path
                  computation: encode `<safe(unit_id)>.json.done` with the same
                  `_safe_name` the write side uses, `is_file()` = terminal. NEVER a
                  record-body field read / filename-stem reverse lookup — an overlong
                  id's truncated stem ≠ its canonical id, and the old glob+stem
                  fallback permanently misjudged such finished units as pending →
                  infinite re-dispatch. Record-body identity fields are diagnostic
                  only, never load-bearing.)
  - failed      = #canonical units confirmed-failed (`.failed` marker exists; terminal,
                  excluded from pending, NOT retried on --resume; same forward
                  computation). Covers both orchestrator-acked failures AND a
                  per-cluster materialize write failure (`--materialize` isolates it:
                  `.failed` marker + count +1 + batch continues, never aborts).
                  Crash with no `failed` ack leaves no marker → unit stays pending
                  (crash ≠ confirmed failure). Orphan markers on disk (encoded
                  filename maps to no canonical unit id) are stderr-warned and enter
                  NO count.
  - pending[]   = slim work items on the current page; each item (WITH --materialize):
      {cluster_id, category, kind, shape, candidate_count,
       input_path, checkpoint_path, done_marker, failed_marker, bytes, oversize, slice_dir}
    (WITHOUT --materialize: backward-compat lite shell retains `evidence_files[]`)
  - input_path     = ABSOLUTE per-unit input file (subagent reads this; ≤ --max-unit-bytes).
  - checkpoint_path = ABSOLUTE path the T1 subagent MUST write its checkpoint to
                      (<resolved --checkpoints>/<safe(unit)>.json; `safe` = `_safe_name`,
                      `/` `\` `:` → `_` AND stem length-capped ≤ 200); passed verbatim by
                      the orchestrator so the subagent NEVER assembles/interpolates a path.
  - done_marker     = ABSOLUTE `.done` marker path (<checkpoint_path>.done) to touch on success.
  - failed_marker   = ABSOLUTE `.failed` marker path (<checkpoint_path>.failed); the
                      orchestrator writes it (body {unit,reason,tier}) on a `failed` ack —
                      passed verbatim, NEVER self-assembled.
  - slice_dir      = ABSOLUTE in-tree dir for this unit's big-file slice outputs
                     (<init-dir>/slices/t1/<safe(unit_id)>/). Orchestrator passes it verbatim;
                     the T1 induct subagent writes `chunk_sources.py --out
                     <slice_dir>/<safe-stem>.slice.json` for runtime-discovered big evidence
                     files and re-reads that exact path (NEVER a cwd/Temp-derived or
                     out-of-tree --out). `_safe_name` sanitizes `::` in cluster_id.
  - bytes/oversize  = input file size / whether it exceeded --max-unit-bytes (sharded).
  - truncated   = passthrough of the wrapper's `truncated` flag (no silent loss)
  - offset/limit/effective_limit/shrunk = paging (R5.3b); orchestrator advances offset
    by effective_limit. shrunk=true iff a page was auto-tightened to ≤ --orch-budget-bytes.
  Packing mode: a pending[] PACK item carries `cluster_id` = the pack id (the dispatcher
  and ack state machine consume the same field slot, zero changes), `input_path` = the
  merged pack input, pack-level checkpoint/done/failed marker paths + `slice_dir`, and
  adds `members[]` = [{cluster_id, input_path, checkpoint_path, done_marker, bytes}]
  (per-member, all `Path.resolve()` absolute — pass through verbatim).

Exit codes (R5.3b): 0 ok (incl. empty clusters) · 1 clusters.json missing/malformed ·
2 misuse (argparse / bad budget / scout-incomplete-gate). Idempotent, no TTY.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

# Self-locate this script's dir so the sibling `init_tier` import resolves under any
# cwd / host-agent invocation (direct `py`/`python`) — R5.3a.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from init_tier import (scout_complete, safe_unit_filename, forward_marker_paths,
                       forward_done_ids, forward_failed_ids, orphan_markers,
                       MAX_UNIT_FILENAME_STEM)  # noqa: E402

DEFAULT_MAX_UNIT_BYTES = 192 * 1024    # 192KB — aligns with --big-file-bytes 200KB
DEFAULT_ORCH_BUDGET_BYTES = 64 * 1024  # 64KB — orchestrator single-request page cap
MAX_UNIT_FILENAME_STEM = 200           # alias of init_tier.MAX_UNIT_FILENAME_STEM (single source)
DEFAULT_PACK_BYTES = 0                 # packing off (opt-in; off path stays byte-identical)
DEFAULT_PACK_MAX = 8                   # per-pack member cap when packing is on


def _abs_file(raw, repo_path):
    """Materialize a file path ABSOLUTE against the repo root (read-side path-confinement
    parity with list_scout_batches). discover_controls emits `evidence_files[]` /
    `usage_sites[]` / candidate `file` repo-relative, so a T1 subagent whose cwd drifted
    (opencode system-temp cwd, or a parent-repo submodule cwd) could resolve a relative
    path to the wrong tree. Returns the ABSOLUTE path string (original kept by the caller
    under `repo_relative`); passes `raw` through unchanged when it is non-str / empty /
    already absolute / repo unavailable / unresolvable."""
    if not isinstance(raw, str) or not raw or repo_path is None:
        return raw
    if Path(raw).is_absolute():
        return raw
    try:
        return str((repo_path / raw).resolve())
    except (OSError, ValueError):
        return raw


def _absolutize_paths(obj, repo_path, with_repo=True):
    """Walk a materialized input record (cluster header + candidate hits) and make every
    file path ABSOLUTE (resolved against the repo root), preserving the original value as
    `repo_relative`. By default ALSO sinks the absolute `repo` root into the record as a
    TOP-LEVEL field (fan-out input anchor: the reader subagent anchors its tool paths on
    it without re-deriving, and rejects input path fields resolving outside the anchored
    tree as poisoned — shared contract with list_scout_batches / list_test_groups).
    `with_repo=False` (pack members): absolutize paths only — the merged pack envelope
    carries `repo` once at top level, never duplicated per member. Operates on a shallow
    copy; returns the copy."""
    if not isinstance(obj, dict) or repo_path is None:
        return obj
    out = dict(obj)
    if with_repo:
        out["repo"] = str(repo_path)
    for key in ("evidence_files", "usage_sites"):
        if isinstance(out.get(key), list):
            out[key] = [_abs_file(p, repo_path) for p in out[key]]
    # candidate hits carry a `file` field (repo-relative like discover_controls candidates).
    if isinstance(out.get("candidates"), list):
        new_cands = []
        for c in out["candidates"]:
            if isinstance(c, dict) and isinstance(c.get("file"), str):
                nc = dict(c)
                af = _abs_file(c.get("file"), repo_path)
                if af is not None:
                    nc["file"] = af
                    nc["repo_relative"] = c.get("file")
                new_cands.append(nc)
            else:
                new_cands.append(c)
        out["candidates"] = new_cands
    return out


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


def _done_ids(checkpoints_dir: Path, canonical_ids):
    """Set of completed canonical unit ids — FORWARD marker-path computation
    (identity-immune): for each canonical id, encode the exact marker filename with
    the SAME `_safe_name` the materialization write side uses, `is_file()` = done.
    NEVER re-derives identity from a record-body field or a filename stem (an
    overlong id's truncated stem ≠ canonical id — the old glob+stem fallback
    misjudged such units as forever-pending and re-dispatched finished work
    forever; record-body fields may drift/be absent and are not load-bearing).

    Covers whole-cluster ids and `<cid>::shard-<n>` shard ids alike (both are
    members of `canonical_ids`)."""
    return forward_done_ids(checkpoints_dir, canonical_ids)


def _failed_ids(checkpoints_dir: Path, canonical_ids):
    """Set of TERMINAL-FAILED canonical unit ids (confirmed failure; excluded from
    `pending` and NOT retried on `--resume`) — same forward computation as
    `_done_ids`: marker 存在即终态, identity NEVER from record body or stem.
    A crash with no `failed` ack leaves no marker → the unit stays `pending` and
    IS retried (crash ≠ confirmed terminal failure)."""
    return forward_failed_ids(checkpoints_dir, canonical_ids)


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
    identity + checkpoint `unit` field; only the input FILENAME is encoded.

    ALSO caps the filename stem length (MAX_UNIT_FILENAME_STEM): beyond it the stem is
    truncated keeping the head + a ~60-char discriminant tail (contains the full-key sha8)
    so ANY cluster_id — including legacy overlong ids from pre-bound discover runs — yields
    a writable filename, and two distinct ids do not collide on disk (distinct sha8 tails
    differ). Short ids are returned unchanged.

    Alias of `init_tier.safe_unit_filename` (single encoding source shared with the
    forward done/failed predicates — judgment and materialization never diverge)."""
    return safe_unit_filename(unit_id)


def _cluster_header(cluster: dict) -> dict:
    return {
        "cluster_id": cluster.get("cluster_id"),
        "category": cluster.get("category"),
        "kind": cluster.get("kind"),
        "shape": cluster.get("shape"),
        "evidence_files": cluster.get("evidence_files", []),
        "usage_sites": cluster.get("usage_sites", []),
    }


def collect_canonical_ids(clusters, cands, max_unit_bytes: int, repo_root):
    """The canonical unit-id set for the T1 tier — the identity truth source the
    forward done/failed judgment walks: every whole-cluster id + every oversize
    `<cid>::shard-<n>` derivation (shard plan shared with `_resolve_units`, so the
    id set judgment uses is by construction the id set materialization can write).
    Single shared entry point: resume_state imports THIS (count caliber and
    enumeration pending[] semantics agree by construction — NEVER a second copy)."""
    ids = []
    for cluster in clusters or []:
        if not isinstance(cluster, dict) or not cluster.get("cluster_id"):
            continue
        cid = cluster["cluster_id"]
        ids.append(cid)
        hits = [cands[i] for i in cluster.get("candidate_ids", []) if i in cands]
        ids.extend(uid for uid, _ in
                   _shard_plan(cid, cluster, hits, max_unit_bytes, repo_root))
    return ids


def _shard_plan(cid: str, cluster: dict, hits: list, max_unit_bytes: int,
                repo_path=None):
    """Single source of the sharding decision: greedy candidate-hit grouping under
    the byte budget. Returns the list of (unit_id, absolutized input body) for the
    shards — [] when the cluster fits whole (the caller then uses `cid` itself).
    Both the canonical-id collector and `_resolve_units` consume THIS plan, so the
    id set the forward done/failed judgment walks is by construction the id set
    materialization can write."""
    header = _cluster_header(cluster)
    header_bytes = _byte_len(header)
    shards, cur, cur_b, n = [], [], header_bytes, 0
    for h in hits:
        hb = _byte_len(h)
        if cur and cur_b + hb > max_unit_bytes:
            shards.append((n, _absolutize_paths(dict(header, candidates=cur), repo_path)))
            n += 1
            cur, cur_b = [], header_bytes
        cur.append(h)
        cur_b += hb
    if cur:
        shards.append((n, _absolutize_paths(dict(header, candidates=cur), repo_path)))
    return [(f"{cid}::shard-{sn}", inp) for sn, inp in shards]


def _resolve_units(cid: str, cluster: dict, hits: list, max_unit_bytes: int,
                   inputs_dir: Path, repo_path=None):
    """Materialize one cluster into ≥1 bounded units. Returns list of
    (unit_id, input_path, bytes, oversize). Whole cluster if ≤ budget; else sharded by
    candidate-hit groups into `<cid>::shard-<n>` (each ≤ budget). Idempotent overwrite.

    Every file path in the materialized input (evidence_files[] / usage_sites[] / candidate
    `file`) is made ABSOLUTE against `repo_path` (read-side confinement: a T1 subagent
    resolves the same file under any cwd and stays inside the MGH_TARGET tree)."""
    full = _absolutize_paths(dict(_cluster_header(cluster), candidates=hits), repo_path)
    if _byte_len(full) <= max_unit_bytes or not hits:
        return [_write_unit(inputs_dir, cid, full)]
    # oversize: shard candidate hits greedily (plan shared with the canonical-id
    # collector — judgment and materialization cannot drift).
    shards = _shard_plan(cid, cluster, hits, max_unit_bytes, repo_path)
    units = [_write_unit(inputs_dir, uid, inp) for uid, inp in shards]
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
    # errno 22 on Windows) and overlong ids are stem-capped. Alias of the shared
    # `init_tier.forward_marker_paths` — the paths stdout advertises are byte-identical
    # to what the forward done/failed judgment recomputes (single source, never drift).
    return forward_marker_paths(checkpoints_dir, unit_id)


def _slice_dir(checkpoints_dir: Path, unit_id: str) -> str:
    """ABSOLUTE in-tree slice-output dir for a unit: <init-dir>/slices/t1/<safe(unit_id)>/.
    <init-dir> = grandparent of the checkpoint dir (<target>/.mgh-init, same root as
    checkpoint_path). `_safe_name` sanitizes `::` in cluster_id (NTFS ADS separator).
    Pinned in-tree so a subagent process whose cwd is a system temp dir (opencode) cannot
    drift big-file slice outputs out-of-tree."""
    init_dir = checkpoints_dir.parent.parent
    return str((init_dir / "slices" / "t1" / _safe_name(unit_id)).resolve())


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
        "slice_dir": _slice_dir(checkpoints_dir, unit_id),
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
        "slice_dir": _slice_dir(checkpoints_dir, cid),
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


# ---------------------------------------------------------------------------
# Deterministic small-cluster packing (--pack-bytes > 0, opt-in): the T1
# enumeration unit shifts from the cluster to the PACK so one subagent context
# amortizes its fixed LLM call overhead over several same-category small
# clusters (quota-constrained gateways bill per call, not per byte).
# ---------------------------------------------------------------------------

def _pack_id(category: str, member_ids) -> str:
    """Deterministic pack id: `pack::<category[:64]>::<sha8>`. sha8 = sha1 hex[:8] over
    the NEWLINE-joined SORTED member cluster ids (a separator keeps distinct member sets
    from concatenating to the same bytes). Pure function of (category, member id set):
    same members → same id across runs (re-dispatch identity stable); any member-id
    change → a new id. The category display slot is truncated at 64 so the whole id
    stays well under the cluster-id 160 bound."""
    cat = (category or "")[:64]
    tail = hashlib.sha1("\n".join(sorted(member_ids)).encode("utf-8")).hexdigest()[:8]
    return f"pack::{cat}::{tail}"


def _pack_partition(items, pack_bytes: int, pack_max: int):
    """Greedy deterministic packing over ONE category's eligible clusters, pre-sorted by
    (bytes asc, cluster_id): keep appending while the pack stays within --pack-bytes AND
    --pack-max; otherwise seal the pack and start a new one. A single cluster larger
    than --pack-bytes still gets its own pack (packing never splits a cluster — that is
    the oversize shard path's job)."""
    packs, cur, cur_b = [], [], 0
    for it in items:
        if cur and (cur_b + it["bytes"] > pack_bytes or len(cur) >= pack_max):
            packs.append(cur)
            cur, cur_b = [], 0
        cur.append(it)
        cur_b += it["bytes"]
    if cur:
        packs.append(cur)
    return packs


def _pack_member_entry(cluster: dict, hits: list, repo_path):
    """One member record inside a merged pack input: cluster header + its candidate hits
    with file paths absolutized (same read-side confinement as single-unit inputs), NO
    per-member `repo` injection (the merged envelope carries `repo` once, top level)."""
    return _absolutize_paths(dict(_cluster_header(cluster), candidates=hits),
                             repo_path, with_repo=False)


def _write_pack_input(inputs_dir: Path, pack_id: str, merged: dict) -> Path:
    """Write the merged pack input `<inputs_dir>/<safe(pack_id)>.input.json` (idempotent
    overwrite; same `_safe_name` stem cap/sanitization as unit inputs). Returns the
    absolute path."""
    inputs_dir.mkdir(parents=True, exist_ok=True)
    path = (inputs_dir / f"{_safe_name(pack_id)}.input.json").resolve()
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _slim_pack(pack_id: str, category, kind, hit_count: int, merged_path: str,
               merged_bytes: int, checkpoints_dir: Path, members: list) -> dict:
    """Pack-level slim envelope: `cluster_id` carries the PACK id (the dispatcher's id
    field slot and ack state machine consume it unchanged); path fields are PACK-level
    (the ack `.failed` marker the dispatcher writes on a failed pack is exactly this
    path); `members[]` carries the per-member absolute paths the task template walks."""
    cp, dm, fm = _paths(checkpoints_dir, pack_id)
    return {
        "cluster_id": pack_id,
        "category": category,
        "kind": kind,
        "shape": "packed",
        "candidate_count": hit_count,
        "input_path": merged_path,
        "checkpoint_path": cp,
        "done_marker": dm,
        "failed_marker": fm,
        "bytes": merged_bytes,
        "oversize": False,
        "slice_dir": _slice_dir(checkpoints_dir, pack_id),
        "members": members,
    }


def _enumerate_packed(args, wrapper, clusters, checkpoints_dir, cands, inputs_dir,
                      repo_root, done, failed) -> int:
    """The `--pack-bytes > 0` enumeration path. Classification is pure and marker-blind
    for identity: terminal-failed clusters (pre-existing `.failed`) are never packable;
    oversize clusters stay on the existing shard path; everything else is packable
    within its category, DONE members included (pack identity must depend only on
    `clusters.json` + flags, so a crash-interrupted pack keeps its id and its done
    members are skipped by the task template on re-dispatch)."""
    pack_max = args.pack_max if args.pack_max is not None else DEFAULT_PACK_MAX
    packable = {}          # category -> [{bytes, cid, cluster, hits}]
    independent = []       # (cluster, hits) — oversize, existing shard path
    clusters_failed = 0
    whole_ids = []
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        cid = cluster.get("cluster_id")
        if not cid:
            continue
        whole_ids.append(cid)
        if cid in failed:  # terminal → excluded from any pack, counted failed
            clusters_failed += 1
            if not args.include_failed:
                continue
            # --include-failed: the failed cluster re-enters on the independent
            # (unpacked) path — same canonical identity the unpacked path would
            # derive; pack identity must stay independent of failure markers.
            independent.append((cluster,
                                [cands[i] for i in cluster.get("candidate_ids", [])
                                 if i in cands]))
            continue
        hits = [cands[i] for i in cluster.get("candidate_ids", []) if i in cands]
        nbytes = _byte_len(_absolutize_paths(
            dict(_cluster_header(cluster), candidates=hits), repo_root))
        if hits and nbytes > args.max_unit_bytes:
            independent.append((cluster, hits))
            continue
        packable.setdefault(cluster.get("category") or "", []).append(
            {"bytes": nbytes, "cid": cid, "cluster": cluster, "hits": hits})

    all_units = []
    packs_all = packs_done = packs_failed = 0
    pack_member_total = 0
    for category in sorted(packable):
        items = sorted(packable[category], key=lambda it: (it["bytes"], it["cid"]))
        for members in _pack_partition(items, args.pack_bytes, pack_max):
            packs_all += 1
            pack_member_total += len(members)
            member_ids = [m["cid"] for m in members]
            if all(cid in done for cid in member_ids):
                packs_done += 1  # every member marker present → nothing to dispatch
                continue
            pack_id = _pack_id(category, member_ids)
            if Path(_paths(checkpoints_dir, pack_id)[2]).is_file():
                packs_failed += 1  # pack-level terminal failure (failed ack); NOT retried
                if not args.include_failed:
                    continue
                # --include-failed: the failed pack re-emits as the pack unit
                # (canonical pack id; its failed_marker path is the pack-level
                # marker the dispatcher's --retry-failed deletes at claim)
            merged_members = []
            checkpoints_index = []
            for m in members:
                merged_members.append(
                    _pack_member_entry(m["cluster"], m["hits"], repo_root))
                mcp, mdm, _ = _paths(checkpoints_dir, m["cid"])
                checkpoints_index.append({"cluster_id": m["cid"],
                                          "checkpoint_path": mcp,
                                          "done_marker": mdm})
            merged = {
                "repo": str(repo_root) if repo_root is not None else wrapper.get("repo"),
                "pack_id": pack_id,
                "category": category,
                "members": merged_members,
                "checkpoints": checkpoints_index,
            }
            try:
                merged_path = _write_pack_input(inputs_dir, pack_id, merged)
            except OSError as e:
                # Pack-materialize isolation: this pack is excluded from pending
                # entirely (stderr warning, batch continues, exit code unchanged);
                # member markers are untouched — members stay pending for the next
                # successful enumeration. NEVER abort the batch on one bad pack.
                print(f"warn: pack {pack_id} materialize failed ({e}); pack excluded "
                      f"from pending (exit code unchanged)", file=sys.stderr)
                continue
            members_meta = []
            for m in members:
                mcp, mdm, _ = _paths(checkpoints_dir, m["cid"])
                members_meta.append({"cluster_id": m["cid"],
                                     "input_path": str(merged_path),
                                     "checkpoint_path": mcp,
                                     "done_marker": mdm,
                                     "bytes": m["bytes"]})
            all_units.append(_slim_pack(
                pack_id, category, members[0]["cluster"].get("kind"),
                sum(len(m["hits"]) for m in members), str(merged_path),
                merged_path.stat().st_size, checkpoints_dir, members_meta))

    # independent oversize clusters: the existing per-cluster shard path, verbatim
    # (same `_resolve_units` + OSError isolation semantics as the unpacked path).
    independent_all = independent_done = 0
    for cluster, hits in independent:
        cid = cluster["cluster_id"]
        independent_all += 1
        try:
            units = list(_resolve_units(cid, cluster, hits,
                                        args.max_unit_bytes, inputs_dir, repo_root))
        except OSError as e:
            # Same single-cluster isolation as the unpacked path: `.failed` terminal
            # marker + batch continues; unwritable `.failed` → systemic → exit 2.
            print(f"error: cluster {cid} materialize failed: {e}", file=sys.stderr)
            failed_path = _paths(checkpoints_dir, cid)[2]
            try:
                Path(failed_path).parent.mkdir(parents=True, exist_ok=True)
                Path(failed_path).write_text(json.dumps(
                    {"unit": cid, "reason": f"materialize failed: {e}", "tier": "t1"},
                    ensure_ascii=False), encoding="utf-8")
            except OSError:
                print(f"error: cannot write failed marker for {cid} — systemic "
                      f"run-dir failure", file=sys.stderr)
                return 2
            clusters_failed += 1
            continue
        emitted = False
        for uid, ipath, nbytes in units:
            if uid in done or (uid in failed and not args.include_failed):
                continue
            shard = uid != cid
            all_units.append(_slim_materialized(
                cluster, uid, len(hits) if not shard else _shard_hit_count(inputs_dir, uid),
                ipath, nbytes, shard, checkpoints_dir))
            emitted = True
        if not emitted:
            independent_done += 1

    total = packs_all + independent_all
    done_count = packs_done + independent_done
    failed_count = packs_failed + clusters_failed
    cluster_done = sum(1 for cid in whole_ids if cid in done)
    avg = (pack_member_total / packs_all) if packs_all else 0.0
    print(f"packing: {packs_all} pack(s) over {pack_member_total} packable cluster(s), "
          f"avg {avg:.1f} member(s)/pack; {independent_all} independent oversize/shard "
          f"cluster(s) outside packs; {packs_failed} failed pack(s); "
          f"cluster_total={len(clusters)} cluster_done={cluster_done}", file=sys.stderr)
    req_limit = args.limit if args.limit is not None else len(all_units)
    page = all_units[args.offset: args.offset + max(0, req_limit)]
    page, eff, shrunk = _shrink_page(page, args.orch_budget_bytes)
    result = {
        "repo": wrapper.get("repo"),
        "total": total,
        "done": done_count,
        "failed": failed_count,
        "pending": page,
        "truncated": bool(wrapper.get("truncated", False)),
        "offset": args.offset,
        "limit": req_limit,
        "effective_limit": eff,
        "shrunk": shrunk,
        "cluster_total": len(clusters),
        "cluster_done": cluster_done,
    }
    print(f"clusters.json: {total} total, {done_count} done, {failed_count} failed, "
          f"{len(all_units)} pending unit(s); page offset={args.offset} eff={eff} "
          f"shrunk={shrunk} (checkpoints: {checkpoints_dir})", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="list pending T1 clusters from clusters.json (deterministic work-list)")
    ap.add_argument("--clusters", required=True,
                    help="path to clusters.json (wrapper dict {repo,clusters,truncated}); "
                         "T1 scout gate: if <dir>/run_config.json enables scout and the scout "
                         "tier is incomplete, exits 2 with {\"error\":\"scout-incomplete-gate\"} "
                         "and emits no pending[] (no_scout or absent run_config skips the gate)")
    ap.add_argument("--checkpoints",
                    help="T1 checkpoint dir (default: <clusters>/../checkpoints/t1)")
    ap.add_argument("--candidates",
                    help="controls_candidates.json (for --materialize hit lookup)")
    ap.add_argument("--materialize", metavar="<inputs-dir>",
                    help="write each cluster's complete input to <dir>/<unit>.input.json "
                         "(slim envelope + input_path/bytes/oversize; backward-compat lite "
                         "shell if omitted). Filename stem length-capped (<=200, overlong "
                         "ids writable); a per-cluster write failure -> .failed terminal "
                         "marker + batch continues (never aborts)")
    ap.add_argument("--offset", type=int, default=0, help="page offset (default 0)")
    ap.add_argument("--limit", type=int, default=None,
                    help="max items per page (default: all pending)")
    ap.add_argument("--max-unit-bytes", type=int, default=DEFAULT_MAX_UNIT_BYTES,
                    help=f"per-unit input byte cap (default {DEFAULT_MAX_UNIT_BYTES}; "
                         f"oversize clusters sharded into ::shard-<n>)")
    ap.add_argument("--orch-budget-bytes", type=int, default=DEFAULT_ORCH_BUDGET_BYTES,
                    help=f"orchestrator single-request page byte cap (default "
                         f"{DEFAULT_ORCH_BUDGET_BYTES}; page auto-tightened + shrunk:true)")
    ap.add_argument("--pack-bytes", type=int, default=DEFAULT_PACK_BYTES,
                    help=f"opt-in deterministic small-cluster packing (default "
                         f"{DEFAULT_PACK_BYTES} = OFF: legacy per-cluster path, byte-identical). "
                         f">0 shifts the enumeration unit from the cluster to the PACK: "
                         f"same-category clusters whose whole-cluster input fits "
                         f"--max-unit-bytes are sorted by (bytes asc, cluster_id) and "
                         f"greedily packed up to this byte cap (unit=pack; oversize and "
                         f"::shard-<n> units never pack). Pack id = "
                         f"pack::<category>::<sha8(member ids)> — a pure function of "
                         f"clusters.json + these flag values (same input, same packs). "
                         f"Member-level .done markers stay the ONLY truth source and the "
                         f"recovery granularity: a pack is pending iff >=1 member marker "
                         f"is missing; a re-dispatched pack skips done members via the "
                         f"task template. Requires --materialize. Quota-constrained "
                         f"suggested value: 16384")
    ap.add_argument("--pack-max", type=int, default=None,
                    help=f"per-pack member cap when --pack-bytes > 0 (default "
                         f"{DEFAULT_PACK_MAX}; guardrail against template-iteration "
                         f"bloat). Passing it while --pack-bytes is 0/absent is an "
                         f"invalid combination -> exit 2")
    ap.add_argument("--include-failed", action="store_true",
                    help="re-list confirmed-failed units into pending[] under their "
                         "canonical ids with their existing .failed marker paths "
                         "(whole-cluster failures re-enter on the independent path, "
                         "failed packs re-emit as the pack unit, failed shards "
                         "re-emit; identity from this enumerator's forward "
                         "derivation, never filename stems; opt-in for the "
                         "dispatcher's --retry-failed flow). Default off keeps "
                         "stdout byte-identical")
    args = ap.parse_args()

    if args.offset < 0:
        print("error: --offset must be >= 0", file=sys.stderr)
        return 2
    for label, raw in (("--max-unit-bytes", args.max_unit_bytes),
                       ("--orch-budget-bytes", args.orch_budget_bytes),
                       ("--pack-bytes", args.pack_bytes)):
        v = _parse_bytes(label, raw)
        if v < 0:
            return 2
    pack_max = args.pack_max if args.pack_max is not None else DEFAULT_PACK_MAX
    if args.pack_max is not None and args.pack_bytes == 0:
        print("error: --pack-max requires --pack-bytes > 0 (invalid combination: "
              "packing is off). recipe: enable packing with e.g. `--pack-bytes 16384 "
              "--pack-max 8`, or drop --pack-max", file=sys.stderr)
        return 2
    if args.pack_bytes > 0:
        if not args.materialize:
            print("error: --pack-bytes requires --materialize (each pack materializes "
                  "ONE merged input file). recipe: add --materialize <inputs/t1>",
                  file=sys.stderr)
            return 2
        if pack_max < 1:
            print("error: --pack-max must be >= 1", file=sys.stderr)
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

    # --- scout-tier gate (deterministic tier ordering; see module docstring) ---
    # <clusters.json 同目录>/run_config.json decides scout intent. run_config absent
    # (bare clusters.json / test fixture) or no_scout=true → gate skipped (conservative
    # pass-through / explicit regex-only). scout enabled + incomplete → fail-loud so the
    # orchestrator CANNOT fan out T1 on a regex-only cluster set.
    init_dir = clusters_path.resolve().parent
    rc_path = init_dir / "run_config.json"
    if rc_path.is_file():
        try:
            rc = json.loads(rc_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rc = None
        if isinstance(rc, dict) and not rc.get("no_scout"):
            if not scout_complete(init_dir):
                print(f"error: scout tier incomplete but run_config enables scout "
                      f"(no_scout=false) — T1 must NOT proceed on regex-only clusters. "
                      f"Read `py resume_state.py --target <target>` stdout step/next_action "
                      f"to finish the scout tier first; pass --no-scout to explicitly run "
                      f"regex-only.", file=sys.stderr)
                print(json.dumps({"error": "scout-incomplete-gate",
                                  "init_dir": str(init_dir),
                                  "clusters": str(clusters_path),
                                  "hint": "finish the scout tier (resume_state.py) or "
                                          "re-run /mgh-init with --no-scout"},
                                 ensure_ascii=False))
                return 2

    # canonical unit-id set (identity truth source): whole clusters + oversize
    # `<cid>::shard-<n>` derivations (same `_shard_plan` the materializer splits
    # with — the two sides cannot drift). Done/failed judgment = forward
    # marker-path computation over THIS set (init_tier.forward_*); never a
    # glob+stem reverse lookup (an overlong id's truncated stem ≠ canonical id →
    # the old fallback misjudged finished units as forever-pending → infinite
    # re-dispatch).
    materialize = bool(args.materialize)
    cands = _load_candidates(args.candidates) if materialize else {}
    inputs_dir = Path(args.materialize).resolve() if materialize else None
    try:
        repo_root = Path(wrapper["repo"]).resolve() \
            if isinstance(wrapper.get("repo"), str) and wrapper["repo"] else None
    except (OSError, ValueError):
        repo_root = None
    canonical_ids = collect_canonical_ids(clusters, cands, args.max_unit_bytes,
                                          repo_root) if materialize else \
        [c.get("cluster_id") for c in clusters
         if isinstance(c, dict) and c.get("cluster_id")]

    done = _done_ids(checkpoints_dir, canonical_ids)
    failed = _failed_ids(checkpoints_dir, canonical_ids)
    # orphan audit (fail-soft): markers whose encoded filename maps to no
    # canonical unit id (renamed/legacy run products) — stderr warn only, they
    # NEVER enter done/failed/pending.
    for name in orphan_markers(checkpoints_dir, canonical_ids):
        print(f"warn: orphan marker (no canonical unit id matches; audit only, "
              f"not counted): {name}", file=sys.stderr)

    # Opt-in packing: units shift from clusters to deterministic packs (see
    # _enumerate_packed). Off path below stays byte-identical — zero pack code runs.
    if materialize and args.pack_bytes > 0:
        return _enumerate_packed(args, wrapper, clusters, checkpoints_dir, cands,
                                 inputs_dir, repo_root, done, failed)

    all_units = []          # full slim work-list (pre-page)
    clusters_with_pending = 0
    clusters_failed = 0
    clusters_reincluded = 0
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        cid = cluster.get("cluster_id")
        if cid in done:  # whole-cluster complete (terminal)
            continue
        if cid in failed:  # whole-cluster confirmed-failed (terminal; NOT retried)
            clusters_failed += 1
            if not args.include_failed:
                continue
            # --include-failed: the failed cluster falls through to the normal
            # materialize + emit below (canonical cluster id / shard ids; the
            # forward-derived failed_marker path rides the emitted unit)
            clusters_reincluded += 1
        emitted = False
        if materialize:
            hits = [cands[i] for i in cluster.get("candidate_ids", []) if i in cands]
            try:
                units = list(_resolve_units(cid, cluster, hits,
                                            args.max_unit_bytes, inputs_dir, repo_root))
            except OSError as e:
                # Single-cluster materialize-failure isolation: write the `.failed` terminal
                # marker (filename stem-capped → writable even for overlong ids), count the
                # failure, keep materializing the rest — NEVER abort the whole batch on one
                # bad cluster. If the `.failed` marker itself cannot be written → systemic
                # run-dir damage → exit 2 fail-loud (R5.3b / R5.9).
                print(f"error: cluster {cid} materialize failed: {e}", file=sys.stderr)
                failed_path = _paths(checkpoints_dir, cid)[2]
                try:
                    # checkpoints dir may not exist yet (first cluster failing before any
                    # checkpoint write) — a missing dir is NOT systemic damage, so create it.
                    Path(failed_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(failed_path).write_text(json.dumps(
                        {"unit": cid, "reason": f"materialize failed: {e}", "tier": "t1"},
                        ensure_ascii=False), encoding="utf-8")
                except OSError:
                    print(f"error: cannot write failed marker for {cid} — systemic "
                          f"run-dir failure", file=sys.stderr)
                    return 2
                clusters_failed += 1
                continue
            for uid, ipath, nbytes in units:
                if uid in done:
                    continue
                if uid in failed and not args.include_failed:
                    # shard-level terminal failure (skip, not retried;
                    # --include-failed re-emits it under its canonical shard id)
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
    # re-included failed clusters sit in BOTH clusters_with_pending and
    # clusters_failed — add them back so done stays the marker-truth count
    # under --include-failed
    done_count = (total - clusters_with_pending - clusters_failed
                  + clusters_reincluded)
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
