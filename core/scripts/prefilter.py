#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
prefilter — s5 deterministic confidence/evidence gate.

Stdlib only. Drops candidate findings that fail the evidence gate
(missing source_ref/sink_ref) or fall below the confidence threshold, and
optionally drops findings whose file/path is clearly out-of-scope noise
(test/example/build dirs). Deterministic: same input -> same output.

Usage:
  py prefilter.py --in s4_candidates.json --out s5_filtered.json
                  [--min-confidence 0.4] [--scope-file scope_manifest.json]
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

MIN_CONF_DEFAULT = 0.40
NOISE_RX = re.compile(r"(^|/)(test|tests|__tests__|fixtures|examples?|samples?|"
                      r"mocks?|stubs?|node_modules|vendor|build|dist|target|"
                      r"\.venv|venv|conftest)(/|$)", re.I)


def _refs(f):
    s = f.get("source_ref") or ""
    k = f.get("sink_ref") or ""
    return s.strip(), k.strip()


def evaluate(finding, min_conf, scope_set):
    """Return (keep: bool, reason: str|None)."""
    # evidence gate: both refs must be real file:line locations
    s, k = _refs(finding)
    if not s or not k:
        return False, "missing source_ref/sink_ref (no proof of data flow)"
    if not re.search(r":\d+", s) or not re.search(r":\d+", k):
        return False, "source_ref/sink_ref lack line numbers"
    # confidence gate
    try:
        conf = float(finding.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    if conf < min_conf:
        return False, f"confidence {conf:.2f} < {min_conf:.2f}"
    # noise floor: test/example/build code (mirrors EXCLUSION_RULES group A/E)
    path = (finding.get("file") or "").replace("\\", "/")
    if NOISE_RX.search(path):
        return False, "test/example/build path (exclusion group A)"
    # scope gate: if a scope manifest is given, drop findings outside in_scope
    if scope_set is not None and path and path not in scope_set:
        return False, "outside scan scope"
    return True, None


def run(candidates, min_conf, scope_set):
    kept, dropped = [], []
    for f in candidates:
        keep, reason = evaluate(f, min_conf, scope_set)
        if keep:
            kept.append(f)
        else:
            ff = dict(f); ff["dropped_reason"] = reason
            dropped.append(ff)
    return kept, dropped


def main():
    ap = argparse.ArgumentParser(description="s5 deterministic pre-filter")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-confidence", type=float, default=MIN_CONF_DEFAULT)
    ap.add_argument("--scope-file", default=None,
                    help="scope_manifest.json with in_scope[] to enforce")
    args = ap.parse_args()
    data = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    candidates = data.get("findings", data if isinstance(data, list) else [])
    scope_set = None
    if args.scope_file and Path(args.scope_file).exists():
        sm = json.loads(Path(args.scope_file).read_text(encoding="utf-8"))
        scope_set = set(sm.get("in_scope", []))
    kept, dropped = run(candidates, args.min_confidence, scope_set)
    out = {"kept": kept, "dropped": dropped,
           "stats": {"in": len(candidates), "kept": len(kept),
                     "dropped": len(dropped)}}
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print(json.dumps(out["stats"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
