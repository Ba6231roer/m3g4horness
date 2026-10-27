#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
validate_inventory — boundary validator for controls_inventory.json (R5.9).

The cross-product inventory (vvah `design_controls`-compatible) gets its own validator:
single-product `--check` lives on each producer; the inventory is consumed downstream
by /mgh-sra / /mgh-blst / mgh-sast, so a
corrupt one must fail loud at the T2 boundary, not silently propagate.

Asserts (shape):
  - wrapper is {repo, format, controls[], ...} with controls a list;
  - each control carries vvah-compat fields: name, kind (vvah 6-enum), category (init 8);
  - each control has >=1 evidence anchor (non-empty file:class:method | file:line);
  - category->kind matches the deterministic normalization map (drift detector).

Asserts (evidence anchor existence gate):
  - every evidence token of every control MUST resolve to a real repo file via
    the deterministic ladder (repo-root exact -> same-dir case -> UNIQUE
    whole-repo basename; a unique-basename hit PASSES, counted `by_basename`),
    and its claim verified: line anchors in 1..len(lines), symbol anchors with
    every `.`-segment present in the file text. Violations (file_missing /
    line_out_of_range / symbol_absent) fail loud — NEVER lenient pass, NEVER
    rewriting the token. Parsing/resolution logic is the shared single source
    (anchor_resolve.py; the assembly-boundary coverage gate reuses it).
  - repo root = `--repo` flag > inventory top-level `repo` field. Neither
    present/valid → exit 2 with recipe (anchor checks cannot run half-way).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/sys/pathlib).

CLI contract (`--help` is the contract surface, R5.1):
  py validate_inventory.py --inventory <controls_inventory.json>
       [--repo <repo-root>] [--anchor-top N]

stdout (R5.3b): {"check":"inventory","ok":bool,"controls":N,"categories":M,
                 "violations":[...],
                 "anchors":{"anchors_total":T,"ok":a,"by_basename":b,
                            "file_missing":c,"line_out_of_range":d,
                            "symbol_absent":e}}
  anchors_total = ok + by_basename + the three violation counts (every token
  lands in exactly one bucket; by_basename is a PASSING path-format signal).
stderr = diagnostics + per-class first-N violation examples with control names.
Exit codes (R5.3b): 0 ok · 1 missing/malformed · 2 violation (shape or anchors).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`).
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Canonical 8 categories + category->kind map (single source of truth: init_tier).
# Drift here or in the inventory is a real bug; importing keeps every consumer aligned.
from init_tier import KIND, INIT_CATEGORIES  # noqa: E402
# Shared anchor parsing/resolution (single source; the assembly boundary
# coverage gate reuses the SAME implementation — never a private copy).
from anchor_resolve import (RepoResolver, check_anchor,  # noqa: E402
                            VIOLATION_STATUSES)

VVAH_KINDS = {"auth", "sandbox", "input-validation", "aslr", "cfi", "other"}

# stdout counter key order (closed set; by_basename is passing, not a violation).
_ANCHOR_KEYS = ("ok", "by_basename") + VIOLATION_STATUSES


def _evidence_token(item):
    """One evidence entry -> a checkable token string. Non-string items return
    "" (the shape gate above already fails them loud as contract violations —
    evidence items are anchor strings; NEVER silently coerced)."""
    return item.strip() if isinstance(item, str) else ""


def main():
    ap = argparse.ArgumentParser(
        description="validate controls_inventory.json at the T2 boundary (R5.9): "
                    "shape + evidence-anchor existence (file/line/symbol)")
    ap.add_argument("--inventory", required=True, help="path to controls_inventory.json")
    ap.add_argument("--repo", help="repo root for anchor resolution (default: the "
                    "inventory's top-level `repo` field)")
    ap.add_argument("--anchor-top", type=int, default=5, metavar="N",
                    help="max violation examples per class on stderr (default 5)")
    args = ap.parse_args()

    inv_path = Path(args.inventory)
    if not inv_path.is_file():
        print(f"error: controls_inventory.json not found: {inv_path}", file=sys.stderr)
        return 1
    try:
        inv = json.loads(inv_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed controls_inventory.json: {e}", file=sys.stderr)
        return 1
    if not isinstance(inv, dict) or not isinstance(inv.get("controls"), list):
        print("error: controls_inventory.json must be a wrapper {format, controls[]}",
              file=sys.stderr)
        return 1

    controls = inv["controls"]
    violations = []
    cats = set()
    for i, c in enumerate(controls):
        if not isinstance(c, dict):
            violations.append({"index": i, "issue": "control not an object"})
            continue
        name = c.get("name")
        kind = c.get("kind")
        cat = c.get("category")
        ev = c.get("evidence")
        where = {"index": i, "name": name}
        if not name:
            violations.append({**where, "issue": "missing name"})
        if kind not in VVAH_KINDS:
            violations.append({**where, "issue": f"kind {kind!r} not in vvah 6-enum"})
        if cat not in INIT_CATEGORIES:
            violations.append({**where, "issue": f"category {cat!r} not in init 8"})
        elif kind and kind != KIND[cat]:
            violations.append({**where, "issue":
                               f"category {cat!r} maps to kind {KIND[cat]!r}, got {kind!r}"})
        else:
            cats.add(cat)
        if not isinstance(ev, list) or not ev:
            violations.append({**where, "issue": "evidence must be a non-empty list"})
        else:
            for j, a in enumerate(ev):
                if not isinstance(a, str) or not a.strip():
                    violations.append({**where, "evidence": j,
                                       "issue": "evidence anchor must be a non-empty string"})

    # --- evidence anchor existence gate (T2 boundary; fail-loud, zero LLM) ---
    repo_raw = args.repo or (inv.get("repo") if isinstance(inv.get("repo"), str) else None)
    anchors = {k: 0 for k in _ANCHOR_KEYS}
    anchors["anchors_total"] = 0
    examples = {k: [] for k in VIOLATION_STATUSES}
    anchor_violations = 0
    if not repo_raw:
        print("error: no repo root for anchor checks — pass --repo <repo-root> or "
              "ensure the inventory carries a top-level `repo` field (NEVER skip the "
              "existence gate silently)", file=sys.stderr)
        return 2
    repo = Path(repo_raw)
    if not repo.is_dir():
        print(f"error: repo root not a directory: {repo} (anchor checks cannot run; "
              f"fix --repo / the inventory `repo` field)", file=sys.stderr)
        return 2
    resolver = RepoResolver(repo)
    for i, c in enumerate(controls):
        if not isinstance(c, dict):
            continue
        cname = c.get("name") or f"<control #{i}>"
        ev = c.get("evidence")
        items = ev if isinstance(ev, list) else ([ev] if ev else [])
        for item in items:
            tok = _evidence_token(item)
            if not tok:
                continue  # shape violation already recorded above for str items
            r = check_anchor(tok, resolver)
            anchors["anchors_total"] += 1
            status = r["status"]
            anchors[status] = anchors.get(status, 0) + 1
            if status in VIOLATION_STATUSES:
                anchor_violations += 1
                if len(examples[status]) < args.anchor_top:
                    examples[status].append({"control": str(cname),
                                             "token": tok[:160]})
    for cls in VIOLATION_STATUSES:
        for ex in examples[cls]:
            print(f"anchor[{cls}] {ex['control']}: {ex['token']}", file=sys.stderr)

    ok = not violations and anchor_violations == 0
    print(f"[validate_inventory] {inv_path}: controls={len(controls)}, "
          f"categories={len(cats)}, anchors={anchors['anchors_total']} "
          f"(ok={anchors['ok']} by_basename={anchors['by_basename']} "
          f"violations={anchor_violations}), "
          f"{'OK' if ok else f'{len(violations)} shape + {anchor_violations} anchor violation(s)'}",
          file=sys.stderr)
    print(json.dumps({"check": "inventory", "ok": ok, "controls": len(controls),
                      "categories": sorted(cats),
                      "violations": violations,
                      "anchors": {k: anchors[k] for k in
                                  ("anchors_total",) + _ANCHOR_KEYS}},
                     ensure_ascii=False))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
