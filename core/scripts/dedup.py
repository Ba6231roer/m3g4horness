#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
dedup — s7 deterministic + semantic-flavored deduplication.

Stdlib only. Clusters findings by (file, cwe, line proximity) then by normalized
title overlap, keeping the highest-confidence representative and folding the
rest into `duplicates`. Deterministic: same input -> same output.

Usage:
  py dedup.py --in s6_verdicts.json --out s7_findings.json [--line-window 5]
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


def main():
    ap = argparse.ArgumentParser(description="s7 dedup")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--line-window", type=int, default=5)
    ap.add_argument("--title-thresh", type=float, default=0.6)
    args = ap.parse_args()
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
