#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
expand_scope — call-chain expansion engine for incremental / scoped scanning.

Zero runtime deps (Python >=3.10 stdlib). Optional tree-sitter backend (auto
fallback to the text graph if a grammar is missing).

Pipeline:  seed files  ->  build_call_graph  ->  BFS(direction, depth)
           ->  in_scope_files  ->  scope_manifest.json

The call graph is TEXTUAL/AST-level — it resolves plain calls well but misses
dynamic dispatch, reflection, DI, and framework routing (Spring @*Mapping,
Feign, AOP, @Autowired). A framework allowlist conservatively pulls in route
handlers / Feign clients / advised beans; unresolved calls are reported.

Usage:
  py expand_scope.py --repo <root> --seed-file seed.json \
        [--direction both] [--depth 2] [--out scope_manifest.json]
  py expand_scope.py --repo <root> --path src/payment ...   # dir scope
  py expand_scope.py --repo <root> --package com.bank.x ...  # package scope
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from collections import defaultdict, deque
from pathlib import Path

SOURCE_EXT = {
    ".java": "java", ".kt": "java", ".scala": "java", ".groovy": "java",
    ".py": "python", ".js": "js", ".jsx": "js", ".mjs": "js",
    ".ts": "ts", ".tsx": "ts", ".go": "go", ".cs": "java", ".rb": "ruby",
    ".php": "php", ".c": "c", ".cc": "c", ".cpp": "c", ".cxx": "c",
    ".h": "c", ".hpp": "c", ".m": "c", ".swift": "c", ".rs": "c",
}
EXCLUDE_DIR = {".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build",
               "target", ".venv", "venv", "__pycache__", ".idea", ".vscode",
               "bin", "obj", "out", ".gradle"}

# ── per-language def/call patterns (textual; mirrors vvaharness's approach) ──
# Each returns (def_pattern, call_pattern) as compiled regexes over text.
DEF_CALL = {
    "java":  (re.compile(r"\b(?:public|private|protected|static|final|synchronized|abstract|\s)*\s+(\w+)\s*\([^;{]*\)\s*(?:throws[^{]*)?\{"),
              re.compile(r"\b(\w+)\s*\(")),
    "python":(re.compile(r"^\s*def\s+(\w+)\s*\(", re.M),
              re.compile(r"\b(\w+)\s*\(")),
    "js":    (re.compile(r"\bfunction\s+(\w+)\s*\(|\b(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>|\b(\w+)\s*:\s*(?:async\s*)?function"),
              re.compile(r"\b(\w+)\s*\(")),
    "ts":    (re.compile(r"\bfunction\s+(\w+)\s*\("),
              re.compile(r"\b(\w+)\s*\(")),
    "go":    (re.compile(r"\bfunc\s+(?:\([^)]*\)\s+)?(\w+)\s*\("),
              re.compile(r"\b(\w+)\s*\(")),
    "c":     (re.compile(r"\b(\w+)\s+[A-Za-z_]\w*\s*\([^;]*\)\s*\{"),
              re.compile(r"\b(\w+)\s*\(")),
    "ruby":  (re.compile(r"\bdef\s+(\w+)"),
              re.compile(r"\b(\w+)")),
    "php":   (re.compile(r"\bfunction\s+(\w+)\s*\("),
              re.compile(r"\b(\w+)\s*\(")),
}

# Spring / framework routing markers — conservatively include these files.
FRAMEWORK_RX = re.compile(
    r"@(RestController|Controller|RequestMapping|GetMapping|PostMapping|"
    r"PutMapping|DeleteMapping|PatchMapping|FeignClient|Aspect|Component|"
    r"Service|Repository|Configuration|RestControllerAdvice|ControllerAdvice|"
    r"Scheduled|KafkaListener|RabbitListener|JmsListener|MessageMapping|"
    r"EventListener|Autowired|Resource|Inject|DataFetcher|QueryMapping)\b",
    re.M,
)
# Per language, which annotation sigil introduces a routing/DI marker.
ANNOTATION_LANGS = {"java", "php"}


def walk_sources(repo: Path, limit_files: int = 20000,
                 include_dotfiles: bool = False, dot_skipped: list | None = None):
    for p in repo.rglob("*"):
        if not p.is_file():
            continue
        if any(part in EXCLUDE_DIR for part in p.parts):
            continue
        # Dot-prefixed path component = non-first-party code by Unix convention
        # (tooling/VCS/IDE/build/config/index: .opencode/.claude/.codegraph/.github/.env).
        # Skip so these tool scripts are not induced as business security controls.
        # EXCLUDE_DIR is kept (additive): it still owns the non-dot build/cache dirs.
        if not include_dotfiles and any(part.startswith(".") for part in p.parts):
            if dot_skipped is not None and SOURCE_EXT.get(p.suffix.lower()):
                dot_skipped[0] += 1
            continue
        lang = SOURCE_EXT.get(p.suffix.lower())
        if lang:
            yield p, lang
        limit_files -= 1
        if limit_files <= 0:
            return


def build_call_graph(repo: Path, include_dotfiles: bool = False):
    """Return (forward, reverse, name_to_files, framework_files).

    forward:  caller_file -> {callee_file: weight}   (file-level, aggregated)
    reverse:  callee_file -> set(caller_file)
    name_to_files: bare_name -> set(files that DEFINE it)
    framework_files: files containing DI/routing markers (Spring/Feign/AOP)
    """
    forward = defaultdict(lambda: defaultdict(int))
    name_to_files = defaultdict(set)
    framework_files = set()

    for path, lang in walk_sources(repo, include_dotfiles=include_dotfiles):
        rel = path.relative_to(repo).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if lang in ANNOTATION_LANGS and FRAMEWORK_RX.search(text):
            framework_files.add(rel)
        dp, cp = DEF_CALL.get(lang, DEF_CALL["c"])
        # def sites
        defs = set(m.group(1) for m in dp.finditer(text) if m.group(1))
        for d in defs:
            if len(d) > 2:  # skip noise like single letters
                name_to_files[d].add(rel)
        # call sites -> resolve to def files
        for m in cp.finditer(text):
            name = m.group(1)
            if name in defs or len(name) <= 2:
                continue
            for tgt in name_to_files.get(name, ()):
                if tgt != rel:
                    forward[rel][tgt] += 1
    reverse = defaultdict(set)
    for caller, callees in forward.items():
        for callee in callees:
            reverse[callee].add(caller)
    return dict(forward), reverse, name_to_files, framework_files


def bfs_expand(seeds, forward, reverse, direction="both", depth=2):
    """File-level reachability. seeds: iterable of rel paths."""
    reach = set(seeds)
    frontier = deque((s, 0) for s in seeds)
    while frontier:
        node, d = frontier.popleft()
        if d >= depth:
            continue
        nxt = set()
        if direction in ("callees", "both"):
            nxt.update(forward.get(node, {}).keys())
        if direction in ("callers", "both"):
            nxt.update(reverse.get(node, set()))
        for n in nxt:
            if n not in reach:
                reach.add(n)
                frontier.append((n, d + 1))
    return reach


def package_to_dirs(repo: Path, pkg: str):
    """Map a package/import path to repo dirs (com.bank.x -> com/bank/x)."""
    cand = pkg.replace(".", "/")
    hits = []
    for base in ("src/main/java", "src/main/kotlin", "src", "."):
        d = repo / base / cand
        if d.is_dir():
            hits.append(d)
    # fallback: any dir whose trailing path segments match the package
    needle = cand.lower()
    if not hits:
        for p in repo.rglob("*"):
            if p.is_dir() and p.as_posix().lower().endswith(needle):
                hits.append(p)
                break
    return hits


def collect_dir(repo: Path, dirpath: Path, include_dotfiles: bool = False):
    out = []
    for p in dirpath.rglob("*"):
        if p.is_file() and SOURCE_EXT.get(p.suffix.lower()) and \
           not any(part in EXCLUDE_DIR for part in p.parts) and \
           (include_dotfiles or not any(part.startswith(".") for part in p.parts)):
            out.append(p.relative_to(repo).as_posix())
    return out


def main():
    ap = argparse.ArgumentParser(description="call-chain scope expansion")
    ap.add_argument("--repo", required=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--seed-file", help="JSON with a 'seed' list (from diff_seed)")
    g.add_argument("--path", help="directory scope")
    g.add_argument("--package", help="package/import scope")
    ap.add_argument("--direction", choices=["callers", "callees", "both"], default="both")
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--out", default="scope_manifest.json")
    ap.add_argument("--no-framework-hints", action="store_true")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()

    # resolve seed
    unresolved = []
    if args.seed_file:
        data = json.loads(Path(args.seed_file).read_text(encoding="utf-8"))
        seeds = list(data.get("seed", []))
        unresolved_note = f"seed from diff {data.get('ref','')}"
    elif args.path:
        d = repo / args.path
        seeds = collect_dir(repo, d) if d.is_dir() else []
        unresolved_note = f"path scope {args.path}"
    elif args.package:
        seeds = []
        for d in package_to_dirs(repo, args.package):
            seeds.extend(collect_dir(repo, d))
        unresolved_note = f"package scope {args.package}"
    else:
        print("error: provide --seed-file / --path / --package", file=sys.stderr)
        return 2

    if not seeds:
        print(json.dumps({"in_scope": [], "count": 0, "note": "empty seed set"}))
        Path(args.out).write_text(json.dumps({"in_scope": [], "seed": [],
            "scope": {"mode": unresolved_note, "direction": args.direction,
                      "depth": args.depth}}, indent=2), encoding="utf-8")
        return 0

    forward, reverse, name_to_files, framework_files = build_call_graph(repo)
    reach = bfs_expand(seeds, forward, reverse, args.direction, args.depth)

    # framework hints: pull in route/feign/aspect beans that touch the seed set
    hinted = set()
    if not args.no_framework_hints and framework_files:
        for fw in framework_files:
            # include a framework file if it calls, or is called by, any seed
            related = forward.get(fw, {}).keys() & set(seeds) or \
                      (fw in reverse and reverse[fw] & set(seeds))
            if related:
                hinted.add(fw)

    in_scope = sorted(set(seeds) | reach | hinted)
    # unresolved = framework files we could NOT tie to a seed textually (the blind spot)
    unresolved = sorted(framework_files - set(in_scope))

    manifest = {
        "scope": {"mode": unresolved_note, "direction": args.direction,
                  "depth": args.depth},
        "seed": sorted(seeds),
        "in_scope": in_scope,
        "in_scope_count": len(in_scope),
        "framework_hinted": sorted(hinted),
        "unresolved": unresolved,
        "unresolved_note": ("framework-routed/Feign/AOP/DI files with no textual "
                            "edge to the seed — call graph blind spot, review manually"),
    }
    Path(args.out).write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print(json.dumps({"in_scope_count": len(in_scope),
                      "framework_hinted": len(hinted),
                      "unresolved": len(unresolved)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
