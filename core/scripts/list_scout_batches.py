#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
list_scout_batches — deterministic scout work-list producer for /mgh-init.

Reads the wrapper dict `scout_plan.json` ({repo, targets_total, truncated, batches[]})
and the scout checkpoint dir, then prints the authoritative pending work-list as JSON
on stdout. Closes the fan-out asymmetry: T1 has `list_clusters.py`, scout now has this.
Replaces hand-rolled `py -c "import json..."` introspection (R5.2).

Per-unit input materialization (`--materialize`, request-context-budget): each batch's
COMPLETE `targets[]` is written to `<dir>/<batch_id>.input.json`; `pending[]` carries
`input_path`/`oversize`. The orchestrator passes `input_path` verbatim; the scout
subagent reads its own bounded file (NEVER the whole `scout_plan.json`). Batches are the
plan unit (not sharded); oversize batches are flagged and their big files stay in
`needs_slice[]` (sliced by `init-scout` via `chunk_sources`).

`targets[].file` (and `needs_slice[]`) are materialized ABSOLUTE (resolved against the
plan's `repo`), with the original repo-relative value kept as `targets[].repo_relative` —
so a subagent resolves the same file under any cwd and stays inside the MGH_TARGET tree.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_scout_batches.py --scout-plan <scout_plan.json> [--checkpoints <scout-dir>]
       [--materialize <inputs-dir>] [--offset N] [--limit N]
       [--max-unit-bytes B] [--orch-budget-bytes B]

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"repo": "...", "total": N, "done": M, "failed": F, "pending": [<BatchLite>, ...],
   "truncated": false, "offset": 0, "limit": K, "effective_limit": k, "shrunk": false}
  - pending[] item: {batch_id, targets_count, bytes, needs_slice[], input_path,
                     checkpoint_path, done_marker, failed_marker, oversize, slice_dir}
  - each materialized <batch_id>.input.json ALSO carries the absolute `repo` root as a
    TOP-LEVEL field (fan-out input anchor: the reader anchors its tool paths on it and
    rejects path fields resolving outside the anchored tree as poisoned).
  - failed         = #confirmed-failed reader batches (`.failed` marker; terminal,
                     excluded from pending, NOT retried on --resume; done+failed+pending
                     = total). Crash with no `failed` ack → no marker → batch stays pending.
  - input_path     = ABSOLUTE per-batch input file (subagent reads this).
  - checkpoint_path / done_marker / failed_marker = ABSOLUTE (verbatim, passed to
                     subagent; failed_marker body {unit,reason,tier} written by the
                     orchestrator on a `failed` ack).
  - slice_dir      = ABSOLUTE in-tree dir for this batch's big-file slice outputs
                     (<init-dir>/slices/scout/<safe(batch_id)>/). Orchestrator passes it
                     verbatim; the scout subagent writes `chunk_sources.py --out
                     <slice_dir>/<safe-stem>.slice.json` and re-reads that exact path
                     (NEVER a cwd/Temp-derived or out-of-tree --out).
  - oversize       = batch bytes > --max-unit-bytes (flagged, not sharded).

Exit codes (R5.3b): 0 ok (incl. empty batches) · 1 scout_plan.json missing/malformed ·
2 misuse (argparse / bad budget). Idempotent, read-only (sans --materialize writes), no TTY.
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

DEFAULT_MAX_UNIT_BYTES = 192 * 1024    # 192KB
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
    """Filesystem-safe input filename (batch_id is clean `scout-NNN`, but guard anyway)."""
    return unit_id.replace("/", "_").replace("\\", "_").replace(":", "_")


def _done_ids(checkpoints_dir: Path):
    """Completed batch_ids by reading each checkpoint record's `batch_id` field (robust);
    marker = `<id>.json.done`, record = `<id>.json` (sibling)."""
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


def _failed_ids(checkpoints_dir: Path):
    """TERMINAL-FAILED batch_ids (confirmed failure; excluded from `pending`, NOT retried
    on `--resume`). Marker = `<id>.json.failed` (sibling of `.done`); the orchestrator
    writes its body `{unit,reason,tier}` on a `failed` ack — `unit` is the batch_id, read
    in-body so a failure that produced no sibling record body is still matched (the
    `.done` marker is empty so `_done_ids` reads the sibling record; `.failed` carries
    its unit in-body). Body `unit` → sibling record `batch_id` → filename-stem fallback.
    Excludes `merge.json.failed`/`audit.json.failed` (tier-level markers, not reader
    batches). A crash with no `failed` ack leaves no marker → batch stays pending and IS
    retried (crash ≠ confirmed terminal failure)."""
    failed = set()
    if not checkpoints_dir.is_dir():
        return failed
    for marker in sorted(checkpoints_dir.glob("*.json.failed")):
        record = marker.with_suffix("")  # strip ".failed" → <id>.json (sibling)
        if record.stem in ("merge", "audit"):  # tier-level markers, not reader batches
            continue
        bid = None
        try:
            body = json.loads(marker.read_text(encoding="utf-8"))
            if isinstance(body, dict):
                bid = body.get("unit") or None
        except (OSError, ValueError):
            bid = None
        if not bid and record.is_file():  # fall back to the sibling record's `batch_id`
            try:
                bid = json.loads(record.read_text(encoding="utf-8")).get("batch_id") or None
            except (OSError, ValueError):
                bid = None
        if not bid:
            bid = record.stem  # sanitized filename; best-effort (no body + no record)
        failed.add(bid)
    return failed


def _write_batch_input(inputs_dir: Path, batch_id: str, batch: dict, repo):
    """Write `<dir>/<batch_id>.input.json` (full targets[] + needs_slice[]); idempotent.
    Returns (abs input_path, file bytes).

    Each `targets[].file` is materialized as an ABSOLUTE path (resolved against `repo`),
    with the original repo-relative value preserved as `repo_relative`. discover_controls
    emits `file` repo-relative, so a subagent process whose cwd drifted (e.g. opencode
    system-temp cwd, or a parent-repo submodule cwd) could resolve a relative `file` to the
    wrong tree. An absolute `file` resolves identically under any cwd AND stays inside the
    MGH_TARGET tree (so the read-side hook passes it) — closing the non-subjective out-of-
    tree read path (R5.3(b) fan-out path absolutization, extended to the read side).
    `needs_slice[]` entries (repo-relative file paths) are absolutized the same way.

    The input ALSO carries the absolute `repo` root as a TOP-LEVEL field (same source as
    the stdout `repo`): every reader subagent's input then carries a deterministic anchor
    without re-deriving it — the reader anchors all its tool paths on this field (verbatim
    producer-materialized paths, or paths built relative to the anchor) and rejects input
    path fields that resolve outside the anchored tree as poisoned (fan-out input anchor
    contract, shared with list_clusters / list_test_groups)."""
    inputs_dir.mkdir(parents=True, exist_ok=True)
    repo_path = Path(repo) if repo else None

    def _abs_file(raw):
        if not isinstance(raw, str) or not raw:
            return raw, raw
        # already absolute -> keep as-is; repo_relative = the original string (best effort).
        if Path(raw).is_absolute():
            return raw, raw
        if repo_path is None:
            return raw, raw
        try:
            return str((repo_path / raw).resolve()), raw
        except (OSError, ValueError):
            return raw, raw

    abs_targets = []
    for t in batch.get("targets", []):
        if not isinstance(t, dict):
            abs_targets.append(t)
            continue
        nt = dict(t)
        af, rr = _abs_file(t.get("file"))
        if af is not None:
            nt["file"] = af
            if rr is not None:
                nt["repo_relative"] = rr
        abs_targets.append(nt)
    abs_needs_slice = []
    for nf in batch.get("needs_slice", []):
        if not isinstance(nf, str):
            abs_needs_slice.append(nf)
            continue
        af, _ = _abs_file(nf)
        abs_needs_slice.append(af if af is not None else nf)
    inp = {
        "batch_id": batch_id,
        "repo": str(repo_path.resolve()) if repo_path else "",
        "targets": abs_targets,
        "needs_slice": abs_needs_slice,
        "bytes": batch.get("bytes", 0),
    }
    path = (inputs_dir / f"{_safe_name(batch_id)}.input.json").resolve()
    path.write_text(json.dumps(inp, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path), path.stat().st_size


def _shrink_page(page: list, orch_budget: int):
    if orch_budget <= 0 or not page:
        return page, len(page), False
    eff = len(page)
    while eff > 1 and _byte_len(page[:eff]) > orch_budget:
        eff -= 1
    return page[:eff], eff, eff < len(page)


def main():
    ap = argparse.ArgumentParser(
        description="list pending scout batches from scout_plan.json (deterministic work-list)")
    ap.add_argument("--scout-plan", required=True,
                    help="path to scout_plan.json (wrapper {repo,batches,truncated})")
    ap.add_argument("--checkpoints",
                    help="scout checkpoint dir (default: <scout-plan>/../checkpoints/scout)")
    ap.add_argument("--materialize", metavar="<inputs-dir>",
                    help="write each batch's complete targets[] to <dir>/<batch_id>.input.json "
                         "(+ input_path/oversize; backward-compat lite shell if omitted)")
    ap.add_argument("--offset", type=int, default=0, help="page offset (default 0)")
    ap.add_argument("--limit", type=int, default=None, help="max items per page (default: all)")
    ap.add_argument("--max-unit-bytes", type=int, default=DEFAULT_MAX_UNIT_BYTES,
                    help=f"per-batch input byte cap (default {DEFAULT_MAX_UNIT_BYTES}; "
                         f"oversize batches flagged, not sharded)")
    ap.add_argument("--orch-budget-bytes", type=int, default=DEFAULT_ORCH_BUDGET_BYTES,
                    help=f"orchestrator single-request page byte cap (default "
                         f"{DEFAULT_ORCH_BUDGET_BYTES}; page auto-tightened + shrunk:true)")
    args = ap.parse_args()

    if args.offset < 0:
        print("error: --offset must be >= 0", file=sys.stderr)
        return 2
    for label, raw in (("--max-unit-bytes", args.max_unit_bytes),
                       ("--orch-budget-bytes", args.orch_budget_bytes)):
        if _parse_bytes(label, raw) < 0:
            return 2

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
    # <init-dir> = grandparent of the checkpoint dir (same root as checkpoint_path),
    # i.e. <target>/.mgh-init. Anchors slice outputs in-tree so a subagent process whose
    # cwd is a system temp dir (opencode) cannot drift slices out-of-tree.
    init_dir = checkpoints_dir.parent.parent
    done = _done_ids(checkpoints_dir)
    failed = _failed_ids(checkpoints_dir)
    materialize = bool(args.materialize)
    inputs_dir = Path(args.materialize).resolve() if materialize else None

    all_units = []
    failed_count = 0
    for batch in batches:
        if not isinstance(batch, dict):
            continue
        bid = batch.get("batch_id")
        if bid in done:
            continue
        if bid in failed:  # confirmed failure (terminal; NOT retried on --resume)
            failed_count += 1
            continue
        base = checkpoints_dir / f"{bid}.json"
        cp = str(base)
        dm = str(base.with_name(base.name + ".done"))
        fm = str(base.with_name(base.name + ".failed"))
        slice_dir = str((init_dir / "slices" / "scout" / _safe_name(bid)).resolve())
        if materialize:
            ipath, _ = _write_batch_input(inputs_dir, bid, batch, wrapper.get("repo"))
            nbytes = int(batch.get("bytes", 0))
            oversize = nbytes > args.max_unit_bytes
            if oversize:
                print(f"warn: batch {bid} oversize ({nbytes}B > {args.max_unit_bytes}B); "
                      f"big files in needs_slice[] sliced by init-scout", file=sys.stderr)
            all_units.append({
                "batch_id": bid,
                "targets_count": len(batch.get("targets", [])),
                "bytes": nbytes,
                "needs_slice": batch.get("needs_slice", []),
                "input_path": ipath,
                "checkpoint_path": cp,
                "done_marker": dm,
                "failed_marker": fm,
                "oversize": oversize,
                "slice_dir": slice_dir,
            })
        else:
            all_units.append({
                "batch_id": bid,
                "targets_count": len(batch.get("targets", [])),
                "bytes": batch.get("bytes", 0),
                "needs_slice": batch.get("needs_slice", []),
                "checkpoint_path": cp,
                "done_marker": dm,
                "failed_marker": fm,
                "slice_dir": slice_dir,
            })

    total = len(batches)
    done_count = total - len(all_units) - failed_count
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
    }
    print(f"scout_plan.json: {total} total, {done_count} done, {failed_count} failed, "
          f"{len(all_units)} pending batch(es); page offset={args.offset} eff={eff} "
          f"shrunk={shrunk} (checkpoints: {checkpoints_dir})", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
