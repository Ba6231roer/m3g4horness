#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
merge_scout — fold scout_candidates.json (+ audit_found) into controls_candidates.json
and append scout clusters to clusters.json. Part of improve-mgh-init-llm-discovery.

Reuses discover_controls.form_clusters (D2: import, no rewrite) with an empty reverse
graph: scout clusters carry no graph-derived usage_sites, but T1 reads evidence_files
regardless, so nothing material is lost. Regex clusters (already in clusters.json with
full usage_sites from the i1 pass) are PRESERVED — scout clusters are APPENDED only.

Zero runtime deps (Python >=3.10 stdlib). stdout = summary JSON; stderr = diagnostics.

CLI:
  py merge_scout.py --candidates <controls_candidates.json> --scout <scout_candidates.json>
       [--audit <checkpoints/scout/audit.json>] --clusters <clusters.json> [--sample 8]
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover_controls import form_clusters  # reuse grouping logic, no drift


def _normalize(c, i):
    """Bring a scout Candidate-subset up to the full Candidate shape form_clusters expects."""
    a = c.get("anchor") or {}
    return {
        "id": c.get("id") or f"S-{i:04d}",
        "file": c["file"],
        "line": c.get("line"),
        "category": c["category"],
        "kind": c.get("kind"),
        "pattern": c.get("pattern") or a.get("class") or a.get("method") or "",
        "anchor": a,
        "snippet": c.get("evidence_snippet", c.get("snippet", "")),
        "shape": c.get("shape", "centralized"),
        "cluster_id": None,
        "entry_points": c.get("entry_points", []),
        "big_file": c.get("big_file", False),
        "source": "scout",
        "confidence": c.get("confidence"),
    }


def _key(c):
    a = c.get("anchor") or {}
    return (c.get("file"), a.get("class"), a.get("method"), c.get("category"))


def _run_check(scout_path: Path):
    """R5.9 boundary check: validate scout_candidates.json — every candidate MUST carry
    `source:"scout"` and a concrete `file:line` anchor. Returns exit 0 ok / 2 violation."""
    violations = []
    try:
        sc = json.loads(scout_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed scout_candidates.json: {e}", file=sys.stderr)
        return 1
    cands = sc.get("candidates") if isinstance(sc, dict) else None
    if not isinstance(cands, list):
        print("error: scout_candidates.json must be a wrapper {repo, candidates[], unresolved}",
              file=sys.stderr)
        return 1
    for i, c in enumerate(cands):
        if not isinstance(c, dict):
            violations.append({"index": i, "issue": "candidate not an object"})
            continue
        if c.get("source") != "scout":
            violations.append({"index": i, "issue": f"source must be 'scout', got {c.get('source')!r}"})
        if not c.get("file"):
            violations.append({"index": i, "issue": "missing file"})
        if not c.get("line"):
            violations.append({"index": i, "issue": "missing line"})
    ok = not violations
    print(f"[merge_scout --check] {scout_path}: {'OK' if ok else f'{len(violations)} violation(s)'}",
          file=sys.stderr)
    print(json.dumps({"check": "merge_scout", "ok": ok, "candidates": len(cands),
                      "violations": violations}, ensure_ascii=False))
    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(
        description="fold scout candidates into controls_candidates.json + clusters.json")
    ap.add_argument("--candidates", required=False, help="controls_candidates.json (regex; rewritten)")
    ap.add_argument("--scout", required=False, help="scout_candidates.json")
    ap.add_argument("--audit", help="checkpoints/scout/audit.json (optional, best-effort)")
    ap.add_argument("--clusters", required=False, help="clusters.json (scout clusters appended)")
    ap.add_argument("--check", help="validate scout_candidates.json (R5.9 boundary check)")
    ap.add_argument("--sample", type=int, default=8)
    args = ap.parse_args()

    if args.check:
        return _run_check(Path(args.check).resolve())
    if not (args.candidates and args.scout and args.clusters):
        print("error: --candidates, --scout, --clusters are required "
              "(or use --check <scout_candidates.json>)", file=sys.stderr)
        return 2

    cd = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    regex_cands = cd.get("candidates", [])
    sc = json.loads(Path(args.scout).read_text(encoding="utf-8"))
    scout_cands = list(sc.get("candidates", []))
    if args.audit and Path(args.audit).is_file():
        try:
            au = json.loads(Path(args.audit).read_text(encoding="utf-8"))
            scout_cands += au.get("audit_found", [])
        except (OSError, ValueError):
            pass  # audit is optional/best-effort

    # de-dup scout vs regex (and within scout) by (file, anchor.class/method, category)
    seen = {_key(c) for c in regex_cands}
    fresh_raw = []
    for c in scout_cands:
        k = _key(c)
        if k in seen:
            continue
        seen.add(k)
        fresh_raw.append(c)
    fresh = [_normalize(c, i) for i, c in enumerate(fresh_raw)]

    # reuse discover's grouping logic (empty reverse -> no graph-derived usage_sites)
    scout_clusters = form_clusters(list(fresh), {}, set(), None, args.sample)

    cd["candidates"] = regex_cands + fresh
    cd.setdefault("provenance", {})["scout_merged"] = len(fresh)
    Path(args.candidates).write_text(
        json.dumps(cd, indent=2, ensure_ascii=False), encoding="utf-8")

    cl = json.loads(Path(args.clusters).read_text(encoding="utf-8"))
    if not isinstance(cl.get("clusters"), list):
        cl["clusters"] = []
    cl["clusters"] = cl["clusters"] + scout_clusters
    Path(args.clusters).write_text(
        json.dumps(cl, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[merge_scout] +{len(fresh)} scout candidates, +{len(scout_clusters)} scout clusters",
          file=sys.stderr)
    print(json.dumps({"scout_candidates_added": len(fresh),
                      "scout_clusters_added": len(scout_clusters)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
