#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
list_verify_jobs — deterministic s6 work-list producer for /mgh-sast.

Reads the s5 product `s5_filtered.json` (prefilter wrapper {kept[], dropped[], stats})
and the s6 per-finding checkpoint dir, then prints the authoritative pending work-list
as JSON on stdout. Closes the s6 fan-out asymmetry (harden-mgh-sast-orchestration-
discipline FD2): s4 has list_chunks.py, s6 now has this. Replaces hand-rolled
`py -c "import json..."` introspection of s5_filtered.json and the
`_aggregate_verify.py` micro-script reflex in the orchestrator (R5.2).

Unit key: the canonical Finding carries `id` (e.g. "F-001", see core/contracts/README.md);
this script prefers it and, when absent (raw vvah s4 output omits id), DERIVES a stable
filename-safe `finding_id` from {file, line_start, vuln_class} with positional collision
disambiguation (-2, -3, ...). Checkpoint convention (DEFINED here, see
core/contracts/sast/fanout-enumeration.md): orchestrator writes
`checkpoints/s6/<finding_id>.json` + `<finding_id>.json.done` per completed verify.
finding_id values are filename-safe, so done-id = the `.done` marker's stem.

Per-unit input materialization (`--materialize`, request-context-budget): each finding's
COMPLETE record (the full Finding dict — `source_ref`/`sink_ref`/`file`/`line`/`vuln_class`/
etc.) is written to `<dir>/<finding_id>.input.json`; `pending[]` becomes a SLIM envelope
carrying `input_path`/`bytes`/`oversize` and NO variable-length payload (`source_ref`/
`sink_ref` sink into the input file). The orchestrator passes `input_path` verbatim; the
sast-verify subagent reads its own bounded file (NEVER the whole `s5_filtered.json`). An s6
finding is the atomic verify unit — an oversize finding (> `--max-unit-bytes`) is FLAGGED
`oversize` + recipe (NOT sliced, NOT sharded).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/re/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_verify_jobs.py --findings <s5_filtered.json> [--checkpoints <s6-dir>]
       [--materialize <inputs-dir>] [--offset N] [--limit N]
       [--max-unit-bytes B] [--orch-budget-bytes B]

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"repo": ..., "total": N, "done": M, "pending": [<FindingLite>, ...],
   "truncated": false, "offset": 0, "limit": K, "effective_limit": k, "shrunk": false}
  - total       = len(kept[])               (the REAL kept-finding count)
  - done        = #findings whose <finding_id>.json.done marker exists
  - pending[]   = findings not yet done, in file order; each item (WITH --materialize):
      {finding_id, file, line, vuln_class, input_path, checkpoint_path, done_marker,
       bytes, oversize}
    (WITHOUT --materialize: backward-compat lite shell retains `source_ref`/`sink_ref`)
  - input_path     = ABSOLUTE per-finding input file (subagent reads this; ≤ --max-unit-bytes).
  - checkpoint_path = ABSOLUTE path the sast-verify subagent's verdict is associated with
                      (<resolved --checkpoints>/<finding_id>.json); passed verbatim.
  - done_marker     = ABSOLUTE `.done` marker path (<checkpoint_path>.done) to touch.
  - bytes/oversize = input file size / whether it exceeded --max-unit-bytes (flagged, not sliced).
  - line        = finding.line_start   (vvah field; re-projected as `line` in the lite)
  - repo/truncated = passthrough (null/false when absent — s5 wrapper lacks them)
  - offset/limit/effective_limit/shrunk = paging (R5.3b); orchestrator advances offset
    by effective_limit. shrunk=true iff a page was auto-tightened to ≤ --orch-budget-bytes.

Exit codes (R5.3b): 0 ok (incl. empty kept) · 1 s5_filtered.json missing/malformed ·
2 misuse (argparse / bad budget). Idempotent, no TTY.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). list_verify_jobs currently has no sibling
# import, but the guard keeps it in the self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_MAX_UNIT_BYTES = 192 * 1024    # 192KB
DEFAULT_ORCH_BUDGET_BYTES = 64 * 1024  # 64KB — orchestrator single-request page cap

_DONE_SUFFIX = ".json.done"
_BAD_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _parse_bytes(label: str, raw) -> int:
    """Non-negative integer byte budget; exit 2 on misuse (R5.3b)."""
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


def _sanitize(s) -> str:
    """Filename-safe projection of an id fragment (checkpoint names must be safe on
    bash/git/CI). Path separators, colons, spaces -> '-'."""
    return _BAD_CHARS.sub("-", str(s)).strip("-") or "finding"


def _base_id(finding: dict) -> str:
    """Prefer the canonical `id`; else derive a stable base from file/line/vuln_class."""
    fid = finding.get("id")
    if fid:
        return _sanitize(fid)
    file = finding.get("file") or "nofile"
    line = finding.get("line_start", finding.get("line")) or 0
    vc = finding.get("vuln_class") or "other"
    return _sanitize(f"{file}-{line}-{vc}")


def _done_ids(checkpoints_dir: Path):
    """Return the set of completed finding_ids by scanning `<finding_id>.json.done`
    markers. finding_id is filename-safe, so the marker stem IS the finding_id."""
    done = set()
    if not checkpoints_dir.is_dir():
        return done
    for marker in sorted(checkpoints_dir.glob("*" + _DONE_SUFFIX)):
        name = marker.name
        if name.endswith(_DONE_SUFFIX):
            done.add(name[: -len(_DONE_SUFFIX)])  # strip ".json.done" -> <finding_id>
    return done


def _assign_ids(findings):
    """Assign a unique filename-safe finding_id to each finding in file order.
    Collisions (same base id) get a positional suffix -2, -3, ... Positional
    disambiguation is resume-stable because prefilter.py is deterministic, so the
    kept[] order is stable across re-runs of the same s5_filtered.json."""
    assigned = []
    seen = {}
    for f in findings:
        base = _base_id(f)
        fid = base
        if base in seen:
            seen[base] += 1
            fid = f"{base}-{seen[base]}"
        else:
            seen[base] = 1
        assigned.append((fid, f))
    return assigned


def _write_finding_input(inputs_dir: Path, finding_id: str, finding: dict):
    """Write `<dir>/<finding_id>.input.json` (the COMPLETE finding record + finding_id);
    idempotent overwrite. Returns (abs input_path, file bytes)."""
    inputs_dir.mkdir(parents=True, exist_ok=True)
    inp = dict(finding)
    inp["finding_id"] = finding_id
    path = (inputs_dir / f"{_sanitize(finding_id)}.input.json").resolve()
    path.write_text(json.dumps(inp, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path), path.stat().st_size


def _paths(checkpoints_dir: Path, finding_id: str):
    base = checkpoints_dir / f"{finding_id}.json"
    return str(base), str(base.with_name(base.name + ".done"))


def _lite(finding_id: str, finding: dict) -> dict:
    """Backward-compat lite shell (no --materialize): retains source_ref/sink_ref."""
    return {
        "finding_id": finding_id,
        "file": finding.get("file"),
        "line": finding.get("line_start", finding.get("line")),
        "vuln_class": finding.get("vuln_class"),
        "source_ref": finding.get("source_ref"),
        "sink_ref": finding.get("sink_ref"),
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
        description="list pending s6 verify jobs from s5_filtered.json (deterministic work-list)")
    ap.add_argument("--findings", required=True,
                    help="path to s5_filtered.json ({kept[], dropped[], stats}) or a bare findings list")
    ap.add_argument("--checkpoints",
                    help="s6 per-finding checkpoint dir (default: <findings-dir>/s6)")
    ap.add_argument("--materialize", metavar="<inputs-dir>",
                    help="write each finding's complete record to <dir>/<finding_id>.input.json "
                         "(slim envelope + input_path/bytes/oversize; backward-compat lite "
                         "shell if omitted)")
    ap.add_argument("--offset", type=int, default=0, help="page offset (default 0)")
    ap.add_argument("--limit", type=int, default=None,
                    help="max items per page (default: all pending)")
    ap.add_argument("--max-unit-bytes", type=int, default=DEFAULT_MAX_UNIT_BYTES,
                    help=f"per-finding input byte cap (default {DEFAULT_MAX_UNIT_BYTES}; "
                         f"oversize findings flagged + recipe, NOT sliced)")
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

    findings_path = Path(args.findings)
    if not findings_path.is_file():
        print(f"error: s5_filtered.json not found: {findings_path}", file=sys.stderr)
        return 1
    try:
        wrapper = json.loads(findings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed s5_filtered.json: {e}", file=sys.stderr)
        return 1
    # s5_filtered.json is prefilter.py output {kept[], ...}; also accept a findings[]
    # wrapper or a bare list (robustness — do NOT assume a single key name).
    if isinstance(wrapper, list):
        findings = wrapper
        repo, truncated = None, False
    elif isinstance(wrapper, dict):
        if isinstance(wrapper.get("kept"), list):
            findings = wrapper["kept"]
        elif isinstance(wrapper.get("findings"), list):
            findings = wrapper["findings"]
        else:
            print("error: s5_filtered.json must have kept[] (prefilter output) or "
                  "findings[] (do NOT len() the wrapper)", file=sys.stderr)
            return 1
        repo, truncated = wrapper.get("repo"), bool(wrapper.get("truncated", False))
    else:
        print("error: s5_filtered.json must be {kept[], ...} or a bare findings list",
              file=sys.stderr)
        return 1

    checkpoints_dir = (Path(args.checkpoints).resolve() if args.checkpoints
                       else (findings_path.parent / "s6").resolve())
    done = _done_ids(checkpoints_dir)
    materialize = bool(args.materialize)
    inputs_dir = Path(args.materialize).resolve() if materialize else None

    assigned = _assign_ids([f for f in findings if isinstance(f, dict)])
    all_units = []
    for fid, f in assigned:
        if fid in done:
            continue
        if materialize:
            ipath, nbytes = _write_finding_input(inputs_dir, fid, f)
            oversize = nbytes > args.max_unit_bytes
            if oversize:
                print(f"warn: finding {fid} oversize ({nbytes}B > {args.max_unit_bytes}B); "
                      f"s6 finding is atomic — NOT sliced; advise --scope to narrow the diff",
                      file=sys.stderr)
            cp, dm = _paths(checkpoints_dir, fid)
            all_units.append({
                "finding_id": fid,
                "file": f.get("file"),
                "line": f.get("line_start", f.get("line")),
                "vuln_class": f.get("vuln_class"),
                "input_path": ipath,
                "checkpoint_path": cp,
                "done_marker": dm,
                "bytes": nbytes,
                "oversize": oversize,
            })
        else:
            all_units.append(_lite(fid, f))

    total = len(assigned)
    done_count = total - len(all_units)
    req_limit = args.limit if args.limit is not None else len(all_units)
    page = all_units[args.offset: args.offset + max(0, req_limit)]
    page, eff, shrunk = _shrink_page(page, args.orch_budget_bytes)
    result = {
        "repo": repo,
        "total": total,
        "done": done_count,
        "pending": page,
        "truncated": truncated,
        "offset": args.offset,
        "limit": req_limit,
        "effective_limit": eff,
        "shrunk": shrunk,
    }
    print(f"s5_filtered.json: {total} kept finding(s), {done_count} done, "
          f"{len(all_units)} pending; page offset={args.offset} eff={eff} shrunk={shrunk} "
          f"(checkpoints: {checkpoints_dir})", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
