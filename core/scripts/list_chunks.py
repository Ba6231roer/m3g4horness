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

Per-unit input materialization (`--materialize`, request-context-budget): each chunk's
COMPLETE input record (`files[]` + `threat_id` + `hypothesis`) is written to
`<dir>/<chunk_id>.input.json`; `pending[]` becomes a SLIM envelope carrying
`input_path`/`bytes`/`oversize`/`needs_slice` and NO variable-length payload (`files[]`/
`hypothesis` sink into the input file). The orchestrator passes `input_path` verbatim;
the sast-deepdive subagent reads its own bounded file (NEVER the whole `s3_chunks.json`).
Chunks are the plan unit (not sharded); a chunk whose input exceeds `--max-unit-bytes`,
or which contains a source file > `--big-file-bytes`, is flagged `oversize` and its big
files are listed in `needs_slice[]` (sliced by `sast-deepdive` via `chunk_sources`).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/os/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_chunks.py --chunks <s3_chunks.json> [--checkpoints <s4-dir>]
       [--materialize <inputs-dir>] [--offset N] [--limit N]
       [--max-unit-bytes B] [--orch-budget-bytes B]
       [--repo <repo-root>] [--big-file-bytes B]

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"repo": ..., "total": N, "done": M, "pending": [<ChunkLite>, ...],
   "truncated": false, "offset": 0, "limit": K, "effective_limit": k, "shrunk": false,
   "scripts_dir": "<abs <mgh-core>/scripts dir of THIS install>"}
  - total       = len(chunks[])             (the REAL count, not len(wrapper))
  - done        = #chunks whose <chunk_id>.json.done marker exists
  - pending[]   = chunks not yet done, in file order; each item (WITH --materialize):
      {chunk_id, files_count, threat_id, needs_slice, input_path, checkpoint_path,
       done_marker, slice_dir, bytes, oversize}
    (WITHOUT --materialize: backward-compat lite shell retains `files[]`/`hypothesis` and
     omits slice_dir — lite never fans out)
  - input_path     = ABSOLUTE per-chunk input file (subagent reads this; ≤ --max-unit-bytes).
  - checkpoint_path = ABSOLUTE path the sast-deepdive subagent MUST write its checkpoint to
                      (<resolved --checkpoints>/<chunk_id>.json); passed verbatim by the
                      orchestrator so the subagent NEVER assembles/interpolates a path.
  - done_marker     = ABSOLUTE `.done` marker path (<checkpoint_path>.done) to touch.
  - slice_dir       = ABSOLUTE in-tree dir for THIS chunk's big-file slices
                      (<命令输出目录>/slices/s4/<safe(chunk_id)>/; <命令输出目录> = grandparent of
                      --checkpoints = <target>/security-scan, same root as checkpoint_path).
                      Orchestrator passes it verbatim; sast-deepdive writes
                      `chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json` and re-reads
                      that exact path (NEVER relative/cwd/Temp --out). --materialize slim only.
  - needs_slice    = source files in this chunk > --big-file-bytes (sliced via chunk_sources;
                     empty when --repo omitted or no big files).
  - bytes/oversize = input file size / whether it exceeded --max-unit-bytes OR has big files.
  - repo        = passthrough of wrapper.repo (null when absent — s3 wrapper lacks it)
  - truncated   = passthrough of wrapper.truncated (false when absent)
  - offset/limit/effective_limit/shrunk = paging (R5.3b); orchestrator advances offset
    by effective_limit. shrunk=true iff a page was auto-tightened to ≤ --orch-budget-bytes.
  - scripts_dir = ABSOLUTE dir of THIS install's <mgh-core>/scripts/ (Path(__file__).resolve()
                  .parent; host-agnostic). Orchestrator reads it in s4 fan-out and passes
                  `<scripts_dir>/chunk_sources.py` verbatim to sast-deepdive as the ABSOLUTE
                  tool path (NEVER bare name / relative `.claude`|`.opencode/mgh-core/scripts/…`,
                  which under a multi-layer install can resolve to an older copy).

Exit codes (R5.3b): 0 ok (incl. empty chunks) · 1 s3_chunks.json missing/malformed ·
2 misuse (argparse / bad budget). Idempotent, no TTY.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). list_chunks currently has no sibling
# import, but the guard keeps it in the self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_MAX_UNIT_BYTES = 192 * 1024    # 192KB — aligns with --big-file-bytes 200KB
DEFAULT_ORCH_BUDGET_BYTES = 64 * 1024  # 64KB — orchestrator single-request page cap
DEFAULT_BIG_FILE_BYTES = 204800        # 200KB — matches chunk_sources.py default

_DONE_SUFFIX = ".json.done"  # marker = "<chunk_id>.json.done"; chunk_id is filename-safe


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


def _safe_name(unit_id: str) -> str:
    """Filesystem-safe encoding of a unit_id for an INPUT filename. chunk_ids are clean
    ("chunk-NN"), but guard against any path/ADS separators on bash/git/CI/NTFS."""
    return str(unit_id).replace("/", "_").replace("\\", "_").replace(":", "_")


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


def _needs_slice(files, repo_root, big_file_bytes):
    """Source files in this chunk whose on-disk size > big_file_bytes (sliced via
    chunk_sources by sast-deepdive). Resolves paths under --repo when given, else cwd
    (best-effort); files that cannot be stat'd are skipped. Returns [] when --repo is
    absent and no file resolves, so big-file slicing still works via the existing
    sast-deepdive behavior (R5.3a: any cwd, never hard-fails)."""
    if not files or big_file_bytes <= 0:
        return []
    base = Path(repo_root) if repo_root else Path.cwd()
    out = []
    for f in files:
        if not isinstance(f, str) or not f:
            continue
        candidate = (base / f) if not os.path.isabs(f) else Path(f)
        try:
            if candidate.is_file() and candidate.stat().st_size > big_file_bytes:
                out.append(f)
        except OSError:
            continue  # unreadable / missing — best-effort, skip
    return out


def _write_chunk_input(inputs_dir: Path, chunk_id, chunk: dict, needs_slice):
    """Write `<dir>/<chunk_id>.input.json` (full files[] + threat_id + hypothesis +
    needs_slice); idempotent overwrite. Returns (abs input_path, file bytes)."""
    inputs_dir.mkdir(parents=True, exist_ok=True)
    inp = {
        "chunk_id": chunk_id,
        "files": chunk.get("files", []),
        "threat_id": chunk.get("threat_id"),
        "hypothesis": chunk.get("hypothesis"),
        "needs_slice": needs_slice,
    }
    path = (inputs_dir / f"{_safe_name(chunk_id)}.input.json").resolve()
    path.write_text(json.dumps(inp, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path), path.stat().st_size


def _paths(checkpoints_dir: Path, chunk_id):
    base = checkpoints_dir / f"{chunk_id}.json"
    return str(base), str(base.with_name(base.name + ".done"))


def _slice_dir(checkpoints_dir: Path, chunk_id) -> str:
    """ABSOLUTE in-tree slice-output dir for a chunk: <out-root>/slices/s4/<safe(chunk_id)>/.
    <out-root> = grandparent of the checkpoint dir (<target>/security-scan, same root as
    checkpoint_path). `_safe_name` sanitizes any `/`/`\\`/`:` (chunk_ids are clean "chunk-NN"
    → no-op; defensive parity with init T1's NTFS-ADS guard). Pinned in-tree so an
    sast-deepdive subagent whose cwd is a system temp dir (opencode) cannot drift big-file
    slice outputs out-of-tree."""
    out_root = checkpoints_dir.parent.parent  # checkpoints/s4 -> checkpoints -> security-scan
    return str((out_root / "slices" / "s4" / _safe_name(chunk_id)).resolve())


def _lite(chunk: dict) -> dict:
    """Backward-compat lite shell (no --materialize): retains files[]/hypothesis.
    The --materialize slim shell is the blessed fan-out path (carries checkpoint_path/
    done_marker/input_path); this lite shape is preserved verbatim for backward compat."""
    return {
        "chunk_id": chunk.get("id"),          # vvah s3 key is `id` ("chunk-01")
        "files": chunk.get("files", []),
        "threat_id": chunk.get("threat_id"),
        "hypothesis": chunk.get("hypothesis"),
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
        description="list pending s4 chunks from s3_chunks.json (deterministic work-list)")
    ap.add_argument("--chunks", required=True,
                    help="path to s3_chunks.json (vvah wrapper {rationale, chunks[]})")
    ap.add_argument("--checkpoints",
                    help="s4 per-chunk checkpoint dir (default: <chunks-dir>/s4)")
    ap.add_argument("--materialize", metavar="<inputs-dir>",
                    help="write each chunk's complete input to <dir>/<chunk_id>.input.json "
                         "(slim envelope + input_path/bytes/oversize/needs_slice; "
                         "backward-compat lite shell if omitted)")
    ap.add_argument("--offset", type=int, default=0, help="page offset (default 0)")
    ap.add_argument("--limit", type=int, default=None,
                    help="max items per page (default: all pending)")
    ap.add_argument("--max-unit-bytes", type=int, default=DEFAULT_MAX_UNIT_BYTES,
                    help=f"per-chunk input byte cap (default {DEFAULT_MAX_UNIT_BYTES}; "
                         f"oversize chunks flagged + big files listed in needs_slice)")
    ap.add_argument("--orch-budget-bytes", type=int, default=DEFAULT_ORCH_BUDGET_BYTES,
                    help=f"orchestrator single-request page byte cap (default "
                         f"{DEFAULT_ORCH_BUDGET_BYTES}; page auto-tightened + shrunk:true)")
    ap.add_argument("--repo",
                    help="repo root for resolving chunk files[] to compute needs_slice "
                         "(big-file slicing); when omitted, needs_slice is best-effort/empty")
    ap.add_argument("--big-file-bytes", type=int, default=DEFAULT_BIG_FILE_BYTES,
                    help=f"per-source-file slice threshold (default {DEFAULT_BIG_FILE_BYTES}; "
                         f"files larger go to needs_slice[] for chunk_sources slicing)")
    args = ap.parse_args()

    if args.offset < 0:
        print("error: --offset must be >= 0", file=sys.stderr)
        return 2
    for label, raw in (("--max-unit-bytes", args.max_unit_bytes),
                       ("--orch-budget-bytes", args.orch_budget_bytes),
                       ("--big-file-bytes", args.big_file_bytes)):
        if _parse_bytes(label, raw) < 0:
            return 2

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
    materialize = bool(args.materialize)
    inputs_dir = Path(args.materialize).resolve() if materialize else None
    repo_root = args.repo if args.repo else None

    all_units = []          # full work-list (pre-page)
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        cid = chunk.get("id")
        if cid in done:
            continue
        cp, dm = _paths(checkpoints_dir, cid)
        if materialize:
            needs_slice = _needs_slice(chunk.get("files", []), repo_root, args.big_file_bytes)
            ipath, nbytes = _write_chunk_input(inputs_dir, cid, chunk, needs_slice)
            oversize = nbytes > args.max_unit_bytes or bool(needs_slice)
            if oversize:
                why = (f"{nbytes}B > {args.max_unit_bytes}B" if nbytes > args.max_unit_bytes
                       else f"{len(needs_slice)} big file(s) > {args.big_file_bytes}B")
                print(f"warn: chunk {cid} oversize ({why}); big files in needs_slice[] "
                      f"sliced by sast-deepdive via chunk_sources", file=sys.stderr)
            all_units.append({
                "chunk_id": cid,
                "files_count": len(chunk.get("files", [])),
                "threat_id": chunk.get("threat_id"),
                "needs_slice": needs_slice,
                "input_path": ipath,
                "checkpoint_path": cp,
                "done_marker": dm,
                "slice_dir": _slice_dir(checkpoints_dir, cid),
                "bytes": nbytes,
                "oversize": oversize,
            })
        else:
            all_units.append(_lite(chunk))

    total = len(chunks)
    done_count = total - len(all_units)
    req_limit = args.limit if args.limit is not None else len(all_units)
    page = all_units[args.offset: args.offset + max(0, req_limit)]
    page, eff, shrunk = _shrink_page(page, args.orch_budget_bytes)
    result = {
        "repo": wrapper.get("repo") if isinstance(wrapper, dict) else None,
        "total": total,
        "done": done_count,
        "pending": page,
        "truncated": bool(wrapper.get("truncated", False)) if isinstance(wrapper, dict) else False,
        "offset": args.offset,
        "limit": req_limit,
        "effective_limit": eff,
        "shrunk": shrunk,
        "scripts_dir": str(Path(__file__).resolve().parent),
    }
    print(f"s3_chunks.json: {total} total, {done_count} done, {len(all_units)} pending "
          f"chunk(s); page offset={args.offset} eff={eff} shrunk={shrunk} "
          f"(checkpoints: {checkpoints_dir})", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
