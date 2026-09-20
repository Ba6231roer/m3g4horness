#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
sdr_tier — /mgh-sdr shared predicates: unit marker paths + the codegraph probe.

Pure functions, no argparse, no side effects beyond marker `is_file()` probes.

**Marker predicates** — imported by BOTH sides of the same rule:

  * the WRITER  — `diff_group.py` (materializes `slices/` + emits `pending[]`),
  * the READER  — `resume_sdr_state.py` (derives `step` / `tiers` after a resume).

Sharing one function is the structural close on the "enumerator says pending while
disk already holds a marker → the same unit is re-dispatched forever" defect class.
A second copy of the concatenation looks cheap and protects nothing.

NO sanitization and NO truncation: `unit_id` is already filesystem-safe by
construction (`diff_group._safe_name` maps `/ \\ :` -> `_` when the unit is built),
and a marker's filename is the bare concatenation `{unit_id}.done`. This module
therefore reproduces that concatenation VERBATIM — marker paths stay byte-identical
to what is already on disk. It deliberately does NOT reuse
`init_tier.safe_unit_filename`: init truncates over-long stems, sdr does not, and
adopting init's encoding here would rename every existing sdr marker.

**Codegraph probe** — ONE predicate, because two sides must agree on one fact:
the grouping stage (`diff_group.py`, which decides whether to merge units along the
call chain) and the signal the orchestrator writes into the run dir (`sdr_context.py`,
which the dispatcher then reads back into each unit's task message). If the writer
probed differently from the grouper, a slice could be reported as "carries the whole
chain" while the chain was never materialized — a false instruction to the reviewer,
not a cosmetic mismatch.

Zero runtime deps (Python >=3.10 stdlib: os/pathlib/shutil).
"""
from __future__ import annotations
import os
import shutil
from pathlib import Path

CODEGRAPH_DIR = ".codegraph"
CODEGRAPH_BIN_ENV = "MGH_CODEGRAPH_BIN"


def codegraph_bin() -> str | None:
    """Path to the codegraph binary (env override wins; else PATH). None = unavailable."""
    env = os.environ.get(CODEGRAPH_BIN_ENV)
    if env:
        p = Path(env)
        return str(p) if p.is_file() else None
    return shutil.which("codegraph")


def codegraph_available(repo: Path) -> bool:
    """codegraph is a grouping input ONLY when the repo is indexed (`.codegraph/` dir)
    AND a binary resolves. Absent either → fallback grouping (never a hard dep)."""
    return (Path(repo) / CODEGRAPH_DIR).is_dir() and codegraph_bin() is not None


def codegraph_probe_reason(repo: Path) -> str | None:
    """Why call-chain grouping is off (None = available). Diagnostic only."""
    if not (Path(repo) / CODEGRAPH_DIR).is_dir():
        return "no .codegraph dir"
    if codegraph_bin() is None:
        return "no binary"
    return None


def forward_marker_paths(checkpoints_dir: Path, unit_id: str) -> tuple:
    """(draft_path, done_marker, failed_marker) for one canonical sdr unit id,
    FORWARD-computed with the same layout `diff_group.py` writes.

    `drafts/` is the deterministic sibling of the markers dir in the standard
    `<run-dir>/{markers,drafts}` layout. The three paths are the identity of one
    work unit for both the enumerator and the resume reader: 单元是否终态只看
    marker 文件存在性,NEVER 反查文件名 stem、NEVER 采信 grouping.json 的 status
    字段(那是枚举时点快照,fan-out 之后即陈旧)。"""
    base = checkpoints_dir / unit_id
    return (str((checkpoints_dir.parent / "drafts" / f"{unit_id}.json").resolve()),
            str(base.with_name(base.name + ".done").resolve()),
            str(base.with_name(base.name + ".failed").resolve()))


def forward_done_ids(checkpoints_dir: Path, canonical_ids) -> set:
    """Canonical unit ids whose `.done` marker exists (forward marker-path
    computation — identity-immune to filename-stem drift and to a stale
    `grouping.json::units[].status`)."""
    done = set()
    if not checkpoints_dir.is_dir():
        return done
    for uid in canonical_ids:
        if Path(forward_marker_paths(checkpoints_dir, uid)[1]).is_file():
            done.add(uid)
    return done


def forward_failed_ids(checkpoints_dir: Path, canonical_ids) -> set:
    """Canonical unit ids whose `.failed` marker exists (terminal, NOT retried on
    --resume unless --retry-failed; forward computation, same source as
    forward_done_ids)."""
    failed = set()
    if not checkpoints_dir.is_dir():
        return failed
    for uid in canonical_ids:
        if Path(forward_marker_paths(checkpoints_dir, uid)[2]).is_file():
            failed.add(uid)
    return failed


def orphan_markers(checkpoints_dir: Path, canonical_ids) -> list:
    """Marker files on disk whose name corresponds to NO canonical unit id
    (renamed/legacy run products from an earlier grouping). Fail-soft audit
    input: the caller lists them in advisory notes — orphans NEVER enter any
    done/failed/pending set."""
    if not checkpoints_dir.is_dir():
        return []
    expected = set()
    for uid in canonical_ids:
        for p in forward_marker_paths(checkpoints_dir, uid)[1:]:
            expected.add(Path(p).name)
    out = []
    for m in sorted(checkpoints_dir.iterdir()):
        if not m.is_file():
            continue
        if not (m.name.endswith(".done") or m.name.endswith(".failed")):
            continue
        if m.name in expected:
            continue
        out.append(m.name)
    return out
