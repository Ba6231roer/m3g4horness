#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""check_distributed_purity — R5.10 distribution-purity lint.

Shipped md artifacts (command shells, agent defs, stage prompts, I/O contracts,
skills) MUST NOT carry dev-only provenance / dangling references that only make
sense in THIS repo's研发 context. install.sh mirrors them into target projects
where they are dangling pointers — waste tokens, and the target often has its own
AGENTS.md / unrelated ids that mislead the host agent. This lint enforces 8
high-precision禁止模式 (zero/low false-positive; operational paths and stage
labels are NOT flagged):

  1. rule id          \\bR\\d+(\\.\\d+)?\\b            e.g. R5.2, R3, R1–R4
  2. failure id       \\bFD\\d+\\b                     e.g. FD8, FD3
  3. decision id      \\bD\\d+\\b                      e.g. D12, D9 = D12
  4. dev-manual xref  AGENTS\\.md\\s+R\\d              e.g. AGENTS.md R1–R4
  5. change-folder    (add|fix|harden|improve|purify)-mgh-(init|sast|sra|blst)-…
  6. upstream doc     glasswing_docs/
  7. dev-file ptr     \\btask\\.\\d+\\.md\\b           e.g. task.260630.md
  8. dev-meta         范式锚点 / 承\\s*R\\d+ / 兑现\\s*R\\d+

Scan set mirrors install.sh source globs (design D1): releases/<platform>/
{commands,agents,skills} (claude) / {command,agent} (opencode) + core/prompts/**
+ core/contracts/**. Exempt by construction: *.py, AGENTS.md, openspec/**,
tools/, tests/, docs/, README, task.*, core/docs/ (R1 attribution records).

Upstream jargon (vvah / vvaharness / design_controls as谱系归因) is NOT a hard
boundary — same shape as protected `Source:` headers / Apache attribution /
operational `design_controls`, so a machine cannot tell them apart; it is handled
manually (design D4) + prompt guardrails. `--allowlist <file>` suppresses per-line
false positives (default empty).

Contract (R5.3): `--help` IS the CLI surface; stdout=JSON {scanned, violations[],
allowlisted}; stderr=human diagnostics; exit 0 clean / 2 violations / 1 operational
error. Self-locating, any-cwd, `encoding="utf-8"`, zero runtime deps
(Python >=3.10 stdlib only).

Run:  py tools/check_distributed_purity.py
      py tools/check_distributed_purity.py --files path/to/x.md [more...]
      py tools/check_distributed_purity.py --allowlist fp.txt
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Scan roots mirror install.sh source set (design D1). *.md only; .py / docs /
# openspec / AGENTS.md are out of scope by not being listed here.
SCAN_DIRS = [
    ROOT / "releases" / "claude-code" / "commands",
    ROOT / "releases" / "claude-code" / "agents",
    ROOT / "releases" / "claude-code" / "skills",
    ROOT / "releases" / "opencode" / "command",
    ROOT / "releases" / "opencode" / "agent",
    ROOT / "core" / "prompts",
    ROOT / "core" / "contracts",
]

# (name, compiled, example) — the 8 high-precision prohibited patterns.
PATTERNS = [
    ("rule_id",
     re.compile(r"\bR\d+(\.\d+)?\b"), "R5.2"),
    ("failure_id",
     re.compile(r"\bFD\d+\b"), "FD8"),
    ("decision_id",
     re.compile(r"\bD\d+\b"), "D12"),
    ("dev_manual_xref",
     re.compile(r"AGENTS\.md\s+R\d"), "AGENTS.md R1–R4"),
    ("change_folder",
     re.compile(r"\b(add|fix|harden|improve|purify)-mgh-(init|sast|sra|blst)-[a-z0-9-]+"),
     "improve-mgh-init-llm-discovery"),
    ("upstream_doc",
     re.compile(r"glasswing_docs/"), "glasswing_docs/09"),
    ("dev_file_ptr",
     re.compile(r"\btask\.\d+\.md\b"), "task.260630.md"),
    ("dev_meta",
     re.compile(r"范式锚点|承\s*R\d+|兑现\s*R\d+"), "承 R5.7 / 范式锚点"),
]


def gather_files(explicit):
    """Collect *.md files: explicit override list, else install-mirrored globs."""
    if explicit:
        return [Path(f) for f in explicit]
    out, seen = [], set()
    for d in SCAN_DIRS:
        if d.is_dir():
            for p in sorted(d.rglob("*.md")):
                key = str(p.resolve())
                if key not in seen:
                    seen.add(key)
                    out.append(p)
    return out


def load_allowlist(path):
    """Each non-empty, non-`#` line: `<rel/path.md>:<lineno>` (forward slashes)."""
    allow = set()
    if not path:
        return allow
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        allow.add(line.replace("\\", "/"))
    return allow


def relpath(p, root):
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="R5.10 distribution-purity lint: shipped md MUST be free of "
                    "dev-only provenance / dangling references")
    ap.add_argument("--files", nargs="*", default=None,
                    help="scan these md files explicitly "
                         "(default: install-mirrored globs under repo root)")
    ap.add_argument("--allowlist", default=None, metavar="FILE",
                    help="file of `rel/path.md:lineno` lines to suppress "
                         "(false-positive escape hatch; default empty)")
    ap.add_argument("--root", default=None, metavar="DIR",
                    help="repo root for relative-path computation "
                         "(default: parent of this script's dir)")
    args = ap.parse_args(argv)

    # emit glyphs/JSON cleanly regardless of host console codepage (e.g. cp936)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    root = Path(args.root).resolve() if args.root else ROOT
    files = gather_files(args.files)
    allow = load_allowlist(args.allowlist)

    violations, errors, allowlisted = [], [], 0
    for p in files:
        if not p.is_file():
            errors.append(f"not a file: {p}")
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as e:
            errors.append(f"{p}: read failed: {e}")
            continue
        rel = relpath(p, root)
        for i, line in enumerate(text.splitlines(), 1):
            hits = [{"pattern": name, "token": m.group(0)}
                    for name, rx, _ex in PATTERNS for m in rx.finditer(line)]
            if not hits:
                continue
            if f"{rel}:{i}" in allow:
                allowlisted += 1
                continue
            violations.append({"file": rel, "line": i, "hits": hits})

    summary = {"scanned": len(files), "violations": violations,
               "allowlisted": allowlisted}
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    for e in errors:
        print(f"✗ {e}", file=sys.stderr)
    if violations:
        print(f"✗ {len(violations)} offending line(s) across shipped md (R5.10):",
              file=sys.stderr)
        for v in violations:
            toks = ", ".join(f"{h['token']} ({h['pattern']})" for h in v["hits"])
            print(f"  {v['file']}:{v['line']}: {toks}", file=sys.stderr)
    elif not errors:
        print(f"✓ {len(files)} shipped md file(s) clean "
              f"(no dev-only provenance / dangling refs)", file=sys.stderr)

    if errors:
        return 1
    return 2 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
