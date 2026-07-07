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

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/re/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_verify_jobs.py --findings <s5_filtered.json> [--checkpoints <s6-dir>]

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"repo": ..., "total": N, "done": M, "pending": [<FindingLite>, ...],
   "truncated": false}
  - total       = len(kept[])               (the REAL kept-finding count)
  - done        = #findings whose <finding_id>.json.done marker exists
  - pending[]   = findings not yet done, in file order; each item:
      {finding_id, file, line, vuln_class, source_ref, sink_ref}
  - line        = finding.line_start   (vvah field; re-projected as `line` in the lite)
  - repo/truncated = passthrough (null/false when absent — s5 wrapper lacks them)

Exit codes (R5.3b): 0 ok (incl. empty kept) · 1 s5_filtered.json missing/malformed ·
2 misuse (argparse). Idempotent, read-only, no TTY.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). list_verify_jobs currently has no
# sibling import, but the guard keeps it in the self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

_DONE_SUFFIX = ".json.done"
_BAD_CHARS = re.compile(r"[^A-Za-z0-9._-]")


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


def _lite(finding_id: str, finding: dict) -> dict:
    return {
        "finding_id": finding_id,
        "file": finding.get("file"),
        "line": finding.get("line_start", finding.get("line")),
        "vuln_class": finding.get("vuln_class"),
        "source_ref": finding.get("source_ref"),
        "sink_ref": finding.get("sink_ref"),
    }


def main():
    ap = argparse.ArgumentParser(
        description="list pending s6 verify jobs from s5_filtered.json (deterministic work-list)")
    ap.add_argument("--findings", required=True,
                    help="path to s5_filtered.json ({kept[], dropped[], stats}) or a bare findings list")
    ap.add_argument("--checkpoints",
                    help="s6 per-finding checkpoint dir (default: <findings-dir>/s6)")
    args = ap.parse_args()

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

    assigned = _assign_ids([f for f in findings if isinstance(f, dict)])
    pending = [_lite(fid, f) for fid, f in assigned if fid not in done]
    result = {
        "repo": repo,
        "total": len(assigned),
        "done": len(assigned) - len(pending),
        "pending": pending,
        "truncated": truncated,
    }
    print(f"s5_filtered.json: {len(assigned)} kept finding(s), {result['done']} done, "
          f"{len(pending)} pending (checkpoints: {checkpoints_dir})", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
