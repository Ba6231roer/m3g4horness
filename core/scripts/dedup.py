#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
dedup — s7 deterministic + semantic-flavored deduplication.

Stdlib only. Clusters findings by (file, cwe, line proximity) then by normalized
title overlap, keeping the highest-confidence representative and folding the
rest into `duplicates`. Deterministic: same input -> same output.

Usage:
  py dedup.py --in s6_verdicts.json --out s7_findings.json [--line-window 5]
  py dedup.py --check <s7_findings.json>   # boundary check (R5.9)

--check validates an EXISTING s7 product by re-running the SAME clustering
(deterministic thresholds, NOT recomputing the canonical set) and asserting no
further merges would occur (idempotent = no residual near-duplicate cluster), plus
each canonical finding carries `file`. stdout =
{"ok":bool,"findings":N,"would_merge":M,"violations":[...]}; stderr = diagnostics.
Exit codes: 0 ok · 1 missing/malformed · 2 violation or misuse.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

STOP = set("a an the of to in on for and or is are be with via from into by "
           "as at it this that can could may might will not no".split())
TOKEN_RX = re.compile(r"[A-Za-z][A-Za-z0-9_]+")


def tokens(title):
    return {t.lower() for t in TOKEN_RX.findall(title or "") if t.lower() not in STOP}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_key(f, window):
    fpath = (f.get("file") or "").replace("\\", "/").lower()
    cwe = (f.get("cwe") or "").upper().strip()
    line = int(f.get("line_start") or 0)
    bucket = (line // max(1, window)) if line else 0
    return (fpath, cwe, bucket)


def run(findings, window=5, title_thresh=0.6):
    # pass 1: deterministic (file, cwe, line-bucket)
    groups = {}
    for f in findings:
        groups.setdefault(cluster_key(f, window), []).append(f)
    # pass 2: within near-miss buckets, merge by title similarity
    canonical, duplicates = [], []
    for _, members in groups.items():
        reps = []  # each rep: {rep, toks, dups}
        for f in sorted(members, key=lambda x: -float(x.get("confidence") or 0)):
            ft = tokens(f.get("title"))
            merged = False
            for r in reps:
                if jaccard(ft, r["toks"]) >= title_thresh or \
                   cluster_key(f, window) == cluster_key(r["rep"], window):
                    r["dups"].append(f)
                    merged = True
                    break
            if not merged:
                reps.append({"rep": f, "toks": ft, "dups": []})
        for r in reps:
            rep = dict(r["rep"])
            if r["dups"]:
                rep["duplicates"] = [
                    {"id": d.get("id"), "title": d.get("title"),
                     "file": d.get("file"), "line_start": d.get("line_start")}
                    for d in r["dups"]]
            canonical.append(rep)
            duplicates.extend(r["dups"])
    # stable order: severity-ish by confidence desc
    canonical.sort(key=lambda x: -float(x.get("confidence") or 0))
    return canonical, duplicates


def _check(path: str, window: int, title_thresh: float) -> int:
    """R5.9 boundary check: re-cluster the canonical findings with the SAME
    deterministic thresholds and assert idempotency (no further merges). A product
    that still merges had a residual near-duplicate cluster = broken artifact."""
    p = Path(path)
    if not p.is_file():
        print(f"error: artifact not found: {p}", file=sys.stderr)
        return 1
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed JSON: {e}", file=sys.stderr)
        return 1
    findings = data.get("findings", data if isinstance(data, list) else [])
    violations = []
    for i, f in enumerate(findings):
        if not isinstance(f, dict) or not (f.get("file") or "").strip():
            violations.append({"index": i, "missing": ["file"]})
    canon, _ = run(findings, window, title_thresh)
    would_merge = len(findings) - len(canon)  # >0 => residual near-dups that re-cluster
    if would_merge > 0:
        violations.append({"residual_near_duplicates": would_merge})
    ok = not violations
    print(f"[dedup --check] {len(findings)} finding(s), would_merge={would_merge}, "
          f"{len(violations)} violation(s)", file=sys.stderr)
    print(json.dumps({"ok": ok, "findings": len(findings), "would_merge": would_merge,
                      "violations": violations}, ensure_ascii=False))
    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(description="s7 dedup")
    ap.add_argument("--in", dest="inp", help="s6_verdicts.json (produce mode)")
    ap.add_argument("--out", help="s7_findings.json output (produce mode)")
    ap.add_argument("--line-window", type=int, default=5)
    ap.add_argument("--title-thresh", type=float, default=0.6)
    ap.add_argument("--check", metavar="<s7_findings.json>",
                    help="boundary check (R5.9): validate an existing s7 product, exit 0/2")
    args = ap.parse_args()
    if args.check:
        return _check(args.check, args.line_window, args.title_thresh)
    if not args.inp or not args.out:
        print("error: produce mode needs --in and --out (or use --check <path>)",
              file=sys.stderr)
        return 2
    data = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    findings = data.get("findings", data if isinstance(data, list) else [])
    canon, dups = run(findings, args.line_window, args.title_thresh)
    out = {"findings": canon,
           "stats": {"in": len(findings), "canonical": len(canon),
                     "duplicates": len(dups)}}
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print(json.dumps(out["stats"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
