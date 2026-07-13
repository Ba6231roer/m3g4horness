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
    """Bring a scout Candidate-subset up to the full Candidate shape form_clusters expects.
    Returns None when `category` is missing/empty so the caller skips + warns (a category is
    required downstream — never fabricate one)."""
    if not c.get("category"):
        return None
    a = c.get("anchor") or {}
    return {
        "id": c.get("id") or f"S-{i:04d}",
        "file": c["file"],
        "line": c.get("line"),
        "category": c.get("category"),
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


def _json_err_detail(e, path):
    """Structured JSON-parse error detail (R5.3b): lineno/colno/msg + a nearby byte window
    (±40 chars around the error position). Uniform across _run_check (exit 2) and main()
    (exit 1) so diagnostics stay consistent at both boundaries."""
    detail = {"error": "malformed JSON", "file": str(path)}
    if isinstance(e, json.JSONDecodeError):
        doc = e.doc or ""
        lo, hi = max(0, e.pos - 40), min(len(doc), e.pos + 40)
        nearby = doc[lo:hi].replace("\r", "\\r").replace("\n", "\\n")
        detail.update({"lineno": e.lineno, "colno": e.colno, "msg": e.msg, "nearby": nearby})
    else:
        detail["msg"] = str(e)
    return detail


def _load_json(path_str):
    """Read + parse JSON for main() fold-in. Returns (data, None) on success or
    (None, detail) on a read/parse failure, where detail = {error, file, msg, lineno?,
    colno?, nearby?}. Lets main() emit a structured stdout error + stderr diagnostic and
    return exit 1 with NO uncaught traceback on malformed input."""
    p = Path(path_str)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        return None, {"error": "unreadable file", "file": str(p), "msg": str(e)}
    try:
        return json.loads(raw), None
    except ValueError as e:
        return None, _json_err_detail(e, p)


def _emit_load_error(detail):
    """Structured stdout error JSON + actionable stderr (R5.3b). Caller returns exit 1."""
    where = (f"line {detail['lineno']} col {detail['colno']}: {detail['msg']} "
             f"near: {detail.get('nearby')!r}" if "lineno" in detail else detail.get("msg", ""))
    print(f"error: cannot load {detail.get('file')}: {where}", file=sys.stderr)
    print(json.dumps({"status": "error", **detail}, ensure_ascii=False))


def _run_check(scout_path: Path):
    """R5.9 boundary check: validate scout_candidates.json. Every candidate MUST carry
    `source:"scout"`, a concrete `file:line` anchor, and a non-empty `category`; the file
    MUST parse as JSON. Any boundary failure (malformed JSON / unreadable / bad wrapper /
    field violation) returns exit 2 so the orchestrator gate reruns S4; success exit 0."""
    violations = []
    try:
        raw = scout_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"error: cannot read scout_candidates.json ({scout_path}): {e}", file=sys.stderr)
        print(json.dumps({"check": "merge_scout", "ok": False, "error": "unreadable",
                          "file": str(scout_path), "msg": str(e)}, ensure_ascii=False))
        return 2
    try:
        sc = json.loads(raw)
    except ValueError as e:
        detail = _json_err_detail(e, scout_path)
        where = (f"line {detail['lineno']} col {detail['colno']}: {detail['msg']} "
                 f"near: {detail.get('nearby')!r}" if "lineno" in detail else detail.get("msg", ""))
        print(f"error: malformed scout_candidates.json ({scout_path}): {where}", file=sys.stderr)
        print(json.dumps({"check": "merge_scout", "ok": False, **detail}, ensure_ascii=False))
        return 2
    cands = sc.get("candidates") if isinstance(sc, dict) else None
    if not isinstance(cands, list):
        print("error: scout_candidates.json must be a wrapper {repo, candidates[], unresolved}",
              file=sys.stderr)
        print(json.dumps({"check": "merge_scout", "ok": False, "error": "not a wrapper",
                          "file": str(scout_path)}, ensure_ascii=False))
        return 2
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
        if not c.get("category"):
            violations.append({"index": i, "issue": "missing category"})
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

    cd, err = _load_json(args.candidates)
    if err:
        _emit_load_error(err)
        return 1
    regex_cands = cd.get("candidates", [])

    sc, err = _load_json(args.scout)
    if err:
        _emit_load_error(err)
        return 1
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
    # normalize; skip + warn on any candidate missing category (belt-and-suspenders for the
    # audit path, which does not pass through --check)
    fresh = []
    skipped = 0
    for i, c in enumerate(fresh_raw):
        n = _normalize(c, i)
        if n is None:
            print(f"[merge_scout] warn: scout candidate #{i} "
                  f"({c.get('file', '?')}:{c.get('line', '?')}) missing category - skipped",
                  file=sys.stderr)
            skipped += 1
            continue
        fresh.append(n)

    # reuse discover's grouping logic (empty reverse -> no graph-derived usage_sites)
    scout_clusters = form_clusters(list(fresh), {}, set(), None, args.sample)

    cd["candidates"] = regex_cands + fresh
    cd.setdefault("provenance", {})["scout_merged"] = len(fresh)
    Path(args.candidates).write_text(
        json.dumps(cd, indent=2, ensure_ascii=False), encoding="utf-8")

    cl, err = _load_json(args.clusters)
    if err:
        _emit_load_error(err)
        return 1
    if not isinstance(cl.get("clusters"), list):
        cl["clusters"] = []
    cl["clusters"] = cl["clusters"] + scout_clusters
    Path(args.clusters).write_text(
        json.dumps(cl, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[merge_scout] +{len(fresh)} scout candidates, +{len(scout_clusters)} scout clusters"
          + (f", {skipped} skipped (missing category)" if skipped else ""),
          file=sys.stderr)
    print(json.dumps({"scout_candidates_added": len(fresh),
                      "scout_clusters_added": len(scout_clusters),
                      "skipped": skipped}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
