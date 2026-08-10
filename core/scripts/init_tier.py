#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
init_tier — shared deterministic constants + tier predicates for /mgh-init leaf scripts.

Single source of truth for two cross-cutting facts previously duplicated per-script
(duplication drifted → non-canonical scout categories reached T2 and the scout tier
could be silently skipped):
  - the canonical 8-category inventory set + category→kind map + deterministic alias
    map (`INIT_CATEGORIES` / `KIND` / `CATEGORY_ALIASES` / `normalize_category`),
    imported by validate_inventory / discover_controls / merge_scout so no script
    hard-codes a private copy;
  - the deterministic scout-tier completion predicate (`scout_complete`) + the stale
    downstream aggregate `.done` paths (`stale_marker_paths`), imported by
    resume_state (step derivation / `--check` / `--invalidate-stale`) and
    list_clusters (T1 gate).

Zero runtime deps (Python >=3.10 stdlib: json/pathlib). Sibling scripts self-locate
this dir (R5.3a) before `import init_tier`.
"""
from __future__ import annotations
import json
from pathlib import Path

# Canonical 8 categories + category→kind map (single source of truth; was duplicated
# in validate_inventory.KIND / discover_controls.KIND — drift there was a real bug).
KIND = {
    "input-validation": "input-validation",
    "authentication": "auth", "authorization": "auth",
    "data-masking": "other", "crypto": "other", "csrf": "other",
    "rate-limiting": "other", "audit-logging": "other",
}
INIT_CATEGORIES = set(KIND.keys())

# Deterministic alias map for KNOWN non-canonical scout category names (extensible).
# An unmapped category is a hard fold-in / `--check` violation, never silently passed
# downstream (a drift name that survives to T2 is silently dropped by the LLM).
CATEGORY_ALIASES = {
    "access-control": "authorization",
    "auth": "authentication",
}


def normalize_category(c) -> str | None:
    """Map a category to its canonical 8-category form (lower-cased); None when empty.

    Alias hits map to the canonical member; already-canonical categories pass through
    unchanged; unknown values are returned lower-cased so the caller can skip + warn
    (never pass a drifted name downstream)."""
    if not c or not isinstance(c, str):
        return None
    cat = c.strip().lower()
    if cat in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[cat]
    return cat


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError):
        return None, "unreadable or malformed"


def _count_markers(checkpoints_dir: Path, glob: str, exclude=()) -> int:
    """Count marker files under checkpoints_dir matching glob, excluding any whose stem
    or name is in `exclude` (tier-level merge/audit markers are not reader batches)."""
    if not checkpoints_dir.is_dir():
        return 0
    n = 0
    for m in checkpoints_dir.glob(glob):
        if m.stem in exclude or m.name in exclude:
            continue
        n += 1
    return n


def _foldin_done(candidates_path: Path) -> bool:
    """merge_scout.py fold-in sets controls_candidates.json::provenance.scout_merged."""
    cd, err = _load_json(candidates_path)
    if err or not isinstance(cd, dict):
        return False
    return isinstance(cd.get("provenance"), dict) and "scout_merged" in cd["provenance"]


def scout_complete(init_dir: Path) -> bool:
    """Scout tier fully done = scout_plan exists AND (0 batches OR (all reader batches
    terminal AND scout_candidates + checkpoints/scout/merge.json.done + fold-in
    `provenance.scout_merged` all present)). A terminal `.failed` batch counts toward
    completion; completion is still gated on the merge/fold-in artifacts so a tier with
    finished readers but no merge output is NOT complete."""
    scout_plan = init_dir / "scout_plan.json"
    if not scout_plan.is_file():
        return False
    sp, err = _load_json(scout_plan)
    batches = 0
    if not err and isinstance(sp, dict) and isinstance(sp.get("batches"), list):
        batches = len(sp["batches"])
    if batches == 0:
        return True  # nothing to scout
    scout_cp = init_dir / "checkpoints" / "scout"
    done = _count_markers(scout_cp, "*.json.done", exclude=("merge.json", "audit.json"))
    failed = _count_markers(scout_cp, "*.json.failed", exclude=("merge.json", "audit.json"))
    if done + failed < batches:
        return False  # reader batches still pending
    if not ((init_dir / "scout_candidates.json").is_file()
            and (init_dir / "checkpoints" / "scout" / "merge.json.done").is_file()):
        return False
    return _foldin_done(init_dir / "controls_candidates.json")


def stale_marker_paths(init_dir: Path) -> list:
    """Downstream aggregate-tier `.done` markers (t2/t3/t4) that become STALE when
    scout fold-in adds candidates (they were produced from regex-only input). Shared by
    merge_scout fold-in (cascade-delete when merged > 0) and resume_state
    `--invalidate-stale` (dry-run and real-delete use the SAME list so they agree).
    t1 per-cluster markers are NOT stale — scout clusters re-enumerate naturally as new
    pending units after fold-in."""
    out = []
    t2 = init_dir / "checkpoints" / "t2"
    for name in ("synthesis.json.done", ".done"):
        p = t2 / name
        if p.is_file():
            out.append(p)
    t3 = init_dir / "checkpoints" / "t3"
    if t3.is_dir():
        out.extend(sorted(t3.glob("*.json.done")))
    t4 = init_dir / "checkpoints" / "t4"
    for name in ("consistency.json.done", ".done"):
        p = t4 / name
        if p.is_file():
            out.append(p)
    return out
