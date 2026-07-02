#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
chunk_sources — deterministic AST/text skeleton + candidate slicing for large files.

Zero runtime deps (Python >=3.10 stdlib). Tree-sitter is NOT bundled (R2); we
build a textual skeleton via the same per-language DEF_CALL patterns used by
expand_scope, plus class/struct patterns. Purpose: never feed a >200KB file
whole to an LLM — locate the enclosing class/function of a candidate and emit
only that slice (+ a small context window).

Two modes (CLI):
  skeleton:  py chunk_sources.py --in <file> [--big-file-bytes N] --out shards.json
  slice:     py chunk_sources.py --in <file> --line <L> [--window 40] --out slice.json

Importable:
  from chunk_sources import parse_skeleton, slice_for_line, file_lang, is_big
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

# FD2: self-locate this script's directory so the sibling `expand_scope` import
# resolves under ANY cwd / host-agent invocation (direct `py`/`python`), removing
# the "No module named 'expand_scope'" failure and the python -c exec workaround.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from expand_scope import SOURCE_EXT, DEF_CALL  # reuse, no rewrite (D2)

# Stronger Java method pattern than expand_scope's DEF_CALL (which misses methods
# with a return type, e.g. "public static String mask(...)" — name before '(' ).
JAVA_DEF = re.compile(
    r"\b(?:public|private|protected|static|final|synchronized|abstract|native|default|\s)*"
    r"(?:[A-Za-z_]\w*(?:\s*<[^>]*>)?(?:\s*\[\s*\])*\s+)*"
    r"([A-Za-z_]\w*)\s*\([^;{]*\)\s*(?:throws[^{]*)?\{")


def _def_rx(lang: str):
    return JAVA_DEF if lang == "java" else DEF_CALL.get(lang, DEF_CALL["c"])[0]

# class/struct/interface patterns per language family (textual)
CLASS_RX = {
    "java":   re.compile(r"\b(?:public|private|protected|static|final|abstract|sealed|non-sealed|\s)*\s*(?:class|interface|enum|record|@interface)\s+([A-Za-z_]\w*)"),
    "python": re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.M),
    "js":     re.compile(r"\bclass\s+([A-Za-z_]\w*)"),
    "ts":     re.compile(r"\bclass\s+([A-Za-z_$]\w*)"),
    "go":     re.compile(r"\btype\s+([A-Za-z_]\w*)\s+(?:struct|interface)"),
    "c":      re.compile(r"\b(?:struct|union|enum)\s+([A-Za-z_]\w*)"),
    "ruby":   re.compile(r"^\s*(?:class|module)\s+([A-Za-z_]\w*)", re.M),
    "php":    re.compile(r"\b(?:class|interface|trait)\s+([A-Za-z_]\w*)"),
}


def file_lang(path: Path):
    return SOURCE_EXT.get(path.suffix.lower())


def is_big(path: Path, threshold: int) -> bool:
    try:
        return path.stat().st_size > threshold
    except OSError:
        return False


def _node_end(start_idx: int, starts: list[int], n_lines: int) -> int:
    """End line = line before the next sibling node (≥ own start), else EOF."""
    if start_idx + 1 < len(starts):
        return max(starts[start_idx], starts[start_idx + 1] - 1)
    return n_lines


def parse_skeleton(path: Path, lang: str | None = None):
    """Return list of structural nodes: {name, kind, line_start, line_end}.

    kind ∈ class | function. Boundaries are textual (next sibling - 1 / EOF).
    """
    lang = lang or file_lang(path)
    if not lang:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    n_lines = len(lines) or 1
    nodes: list[dict] = []
    cls_rx = CLASS_RX.get(lang)
    if cls_rx:
        for m in cls_rx.finditer(text):
            ln = text.count("\n", 0, m.start()) + 1
            nodes.append({"name": m.group(1), "kind": "class",
                          "line_start": ln, "line_end": 0})
    dp = _def_rx(lang)
    for m in dp.finditer(text):
        name = m.group(1)
        if not name or len(name) <= 2:
            continue
        ln = text.count("\n", 0, m.start()) + 1
        nodes.append({"name": name, "kind": "function",
                      "line_start": ln, "line_end": 0})
    # dedupe same (name, kind, line_start)
    seen = set()
    uniq = []
    for nd in nodes:
        k = (nd["kind"], nd["name"], nd["line_start"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(nd)
    uniq.sort(key=lambda d: d["line_start"])
    starts = [d["line_start"] for d in uniq]
    for i, nd in enumerate(uniq):
        nd["line_end"] = _node_end(i, starts, n_lines)
    return uniq


def slice_for_line(path: Path, line: int, window: int = 40, lang: str | None = None):
    """Return the innermost structural node containing `line`, plus a context window.

    Output: {file, line, enclosing: {name,kind,line_start,line_end},
             context_start, context_end, sharded: bool}
    The LLM slice = lines [context_start, context_end] of the file (bounded).
    """
    lang = lang or file_lang(path)
    nodes = parse_skeleton(path, lang)
    # innermost node containing the line (functions inside classes → deepest)
    enclosing = None
    for nd in nodes:
        if nd["line_start"] <= line <= nd["line_end"]:
            if enclosing is None or nd["line_end"] <= enclosing["line_end"]:
                enclosing = nd
    try:
        n_lines = max(1, sum(1 for _ in path.open(encoding="utf-8", errors="replace")))
    except OSError:
        n_lines = line
    if enclosing:
        cs = max(1, enclosing["line_start"] - window // 4)
        ce = min(n_lines, enclosing["line_end"] + window // 4)
    else:
        cs = max(1, line - window // 2)
        ce = min(n_lines, line + window // 2)
    return {"file": str(path), "line": line,
            "enclosing": enclosing,
            "context_start": cs, "context_end": ce,
            "sharded": bool(enclosing)}


def main():
    ap = argparse.ArgumentParser(description="large-file skeleton + candidate slicing")
    ap.add_argument("--in", dest="inp", required=True, help="source file")
    ap.add_argument("--big-file-bytes", type=int, default=204800)
    ap.add_argument("--line", type=int, help="candidate line → emit slice")
    ap.add_argument("--window", type=int, default=40)
    ap.add_argument("--out", default="shards.json")
    args = ap.parse_args()
    p = Path(args.inp)
    lang = file_lang(p)
    big = is_big(p, args.big_file_bytes)
    if args.line:
        result = {"file": str(p), "lang": lang, "big_file": big,
                  "slice": slice_for_line(p, args.line, args.window, lang)}
    else:
        result = {"file": str(p), "lang": lang, "big_file": big,
                  "byte_size": (p.stat().st_size if p.exists() else 0),
                  "sharded": big,
                  "skeleton": parse_skeleton(p, lang)}
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print(json.dumps({"big_file": big, "nodes": len(result.get("skeleton", [])),
                      "sharded": result.get("sharded", big)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
