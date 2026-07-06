#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
validate_inventory — boundary validator for controls_inventory.json (R5.9).

The cross-product inventory (vvah `design_controls`-compatible) gets its own validator
(harden-mgh-init-orchestration-discipline FD7): single-product `--check` lives on each
producer; the inventory is consumed downstream by /mgh-sra / /mgh-blst / mgh-sast, so a
corrupt one must fail loud at the T2 boundary, not silently propagate.

Asserts:
  - wrapper is {repo, format, controls[], ...} with controls a list;
  - each control carries vvah-compat fields: name, kind (vvah 6-enum), category (init 8);
  - each control has >=1 evidence anchor (non-empty file:class:method | file:line);
  - category->kind matches the deterministic normalization map (drift detector).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/sys/pathlib).

CLI contract (`--help` is the contract surface, R5.1):
  py validate_inventory.py --inventory <controls_inventory.json>

stdout (R5.3b): {"check":"inventory","ok":bool,"controls":N,"categories":M,"violations":[...]}
stderr = diagnostics. Exit codes (R5.3b): 0 ok · 1 missing/malformed · 2 violation.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). validate_inventory currently has no
# sibling import, but the guard keeps it in the self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Deterministic category->kind normalization (single source of truth: must match
# discover_controls.KIND). Drift here or in the inventory is a real bug.
KIND = {
    "input-validation": "input-validation",
    "authentication": "auth", "authorization": "auth",
    "data-masking": "other", "crypto": "other", "csrf": "other",
    "rate-limiting": "other", "audit-logging": "other",
}
VVAH_KINDS = {"auth", "sandbox", "input-validation", "aslr", "cfi", "other"}
INIT_CATEGORIES = set(KIND.keys())


def main():
    ap = argparse.ArgumentParser(
        description="validate controls_inventory.json at the T2 boundary (R5.9)")
    ap.add_argument("--inventory", required=True, help="path to controls_inventory.json")
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

    ok = not violations
    print(f"[validate_inventory] {inv_path}: controls={len(controls)}, "
          f"categories={len(cats)}, {'OK' if ok else f'{len(violations)} violation(s)'}",
          file=sys.stderr)
    print(json.dumps({"check": "inventory", "ok": ok, "controls": len(controls),
                      "categories": sorted(cats),
                      "violations": violations}, ensure_ascii=False))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
