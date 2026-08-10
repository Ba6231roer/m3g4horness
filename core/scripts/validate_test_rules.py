#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
validate_test_rules — boundary check for /mgh-ut-init's test_rules_inventory.json.

Validates the synthesize-tier product at the boundary (R5.9): wrapper shape, and per-rule —
category/name/anchor/layer non-empty + known, evidence non-empty anchors, provenance carries
a groups list, confidence ∈ [0,1], weak_dominated boolean. Fail-loud exit 2 on violation
(the orchestrator re-runs ut-synthesize rather than proceeding with a broken inventory).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/sys + pathlib).
CLI contract (`--help` is the contract surface, R5.1):
  py validate_test_rules.py --inventory <test_rules_inventory.json>
stdout (structured JSON; stderr = diagnostics only, R5.3b):
  {"check":"test_rules","ok":bool,"rules":N,"categories":[...],"violations":[...]}
Exit codes (R5.3b): 0 ok · 1 missing/malformed · 2 violation. No TTY, read-only.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate this script's dir (self-contained family, R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Mirrors classify_tests._LAYERS (cross-script consistency guard; drift is a real bug).
_LAYERS = ("controller", "service", "repository", "config", "integration", "util", "other")


def main():
    ap = argparse.ArgumentParser(
        description="validate test_rules_inventory.json at the synthesize boundary (R5.9)")
    ap.add_argument("--inventory", required=True, help="path to test_rules_inventory.json")
    # Emit JSON / glyphs cleanly regardless of host console codepage (e.g. cp936/gbk).
    # Before parse_args so --help is utf-8 too. No-op on StringIO (in-process tests).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = ap.parse_args()
    inv_path = Path(args.inventory)
    if not inv_path.is_file():
        print(f"error: test_rules_inventory.json not found: {inv_path}", file=sys.stderr)
        return 1
    try:
        inv = json.loads(inv_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed test_rules_inventory.json: {e}", file=sys.stderr)
        return 1
    if not isinstance(inv, dict) or not isinstance(inv.get("rules"), list):
        print("error: test_rules_inventory.json must be a wrapper {repo,rules[]}",
              file=sys.stderr)
        return 1

    rules = inv["rules"]
    violations, cats = [], set()
    for i, r in enumerate(rules):
        if not isinstance(r, dict):
            violations.append({"index": i, "issue": "rule not an object"})
            continue
        where = {"index": i, "name": r.get("name")}
        if not r.get("name"):
            violations.append({**where, "issue": "missing name"})
        cat = r.get("category")
        if not cat:
            violations.append({**where, "issue": "missing category"})
        else:
            cats.add(cat)
        layer = r.get("layer")
        if layer not in _LAYERS:
            violations.append({**where, "issue": f"layer {layer!r} not in bucket set"})
        anchor = r.get("anchor")
        if not isinstance(anchor, str) or not anchor.strip():
            violations.append({**where, "issue": "anchor must be a non-empty string "
                                                 "(file:class:method / file:line)"})
        ev = r.get("evidence")
        if not isinstance(ev, list) or not ev:
            violations.append({**where, "issue": "evidence must be a non-empty list"})
        else:
            for j, a in enumerate(ev):
                if not isinstance(a, str) or not a.strip():
                    violations.append({**where, "evidence": j,
                                       "issue": "evidence anchor must be a non-empty string"})
        prov = r.get("provenance")
        if not isinstance(prov, dict) or not isinstance(prov.get("groups"), list):
            violations.append({**where, "issue": "provenance must carry groups[]"})
        conf = r.get("confidence")
        if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not (0.0 <= conf <= 1.0):
            violations.append({**where, "issue": f"confidence must be a float in [0,1] "
                                                 f"(got {conf!r})"})
        if "weak_dominated" in r and not isinstance(r["weak_dominated"], bool):
            violations.append({**where, "issue": "weak_dominated must be a boolean"})

    ok = not violations
    print(f"[validate_test_rules] {inv_path}: rules={len(rules)}, "
          f"categories={len(cats)}, {'OK' if ok else f'{len(violations)} violation(s)'}",
          file=sys.stderr)
    print(json.dumps({"check": "test_rules", "ok": ok, "rules": len(rules),
                      "categories": sorted(cats),
                      "violations": violations}, ensure_ascii=False))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
