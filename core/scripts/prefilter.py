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
  py prefilter.py --check <s5_filtered.json>   # boundary check (R5.9)

--check validates an EXISTING s5 product: every kept finding MUST carry
file / line_start / vuln_class / source_ref / sink_ref (s6 verify needs them all).
stdout = {"ok":bool,"checked":N,"violations":[{"index","missing"}...]}; stderr =
diagnostics. Exit codes: 0 ok · 1 missing/malformed · 2 violation or misuse.
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


# R5.9 boundary check: s6 verify consumes every kept finding and needs these fields.
_CHECK_FIELDS = ("file", "line_start", "vuln_class", "source_ref", "sink_ref")


def _present(v):
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    return True  # ints (line_start) are present when not None


def _check(path: str) -> int:
    p = Path(path)
    if not p.is_file():
        print(f"error: artifact not found: {p}", file=sys.stderr)
        return 1
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed JSON: {e}", file=sys.stderr)
        return 1
    findings = data.get("kept", data.get("findings", data if isinstance(data, list) else []))
    violations = []
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            violations.append({"index": i, "missing": ["(not an object)"]})
            continue
        missing = [k for k in _CHECK_FIELDS if not _present(f.get(k))]
        if missing:
            violations.append({"index": i, "missing": missing})
    ok = not violations
    print(f"[prefilter --check] {len(findings)} finding(s), {len(violations)} violation(s)",
          file=sys.stderr)
    print(json.dumps({"ok": ok, "checked": len(findings), "violations": violations},
                     ensure_ascii=False))
    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(description="s5 deterministic pre-filter")
    ap.add_argument("--in", dest="inp", help="s4_candidates.json (produce mode)")
    ap.add_argument("--out", help="s5_filtered.json output (produce mode)")
    ap.add_argument("--min-confidence", type=float, default=MIN_CONF_DEFAULT)
    ap.add_argument("--scope-file", default=None,
                    help="scope_manifest.json with in_scope[] to enforce")
    ap.add_argument("--check", metavar="<s5_filtered.json>",
                    help="boundary check (R5.9): validate an existing s5 product, exit 0/2")
    args = ap.parse_args()
    if args.check:
        return _check(args.check)
    if not args.inp or not args.out:
        print("error: produce mode needs --in and --out (or use --check <path>)",
              file=sys.stderr)
        return 2
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
