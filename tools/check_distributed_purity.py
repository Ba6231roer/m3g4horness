#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""check_distributed_purity — R5.10 distribution-purity lint.

Shipped artifacts (command shells, agent defs, stage prompts, I/O contracts,
skills, runtime scripts) MUST NOT carry dev-only provenance / dangling references
that only make sense in THIS repo's研发 context. install.sh mirrors them into
target projects where they are dangling pointers — waste tokens, and the target
often has its own AGENTS.md / unrelated ids that mislead the host agent. This
lint enforces 9 high-precision禁止模式 (zero/low false-positive; operational
paths and stage labels are NOT flagged):

  1. rule id          \\bR\\d+(\\.\\d+)?\\b            e.g. R5.2, R3, R1–R4
  2. failure id       \\bFD\\d+\\b                     e.g. FD8, FD3
  3. decision id      \\bD\\d+\\b                      e.g. D12, D9 = D12
  4. dev-manual xref  AGENTS\\.md\\s+R\\d              e.g. AGENTS.md R1–R4
  5. change-folder    (add|fix|harden|improve|purify)-mgh-(init|sast|sra|blst|srr|ut-init)-…
  6. upstream doc     glasswing_docs/
  7. dev-file ptr     \\btask\\.\\d+\\.md\\b           e.g. task.260630.md
  8. dev-meta         范式锚点 / 承\\s*R\\d+ / 兑现\\s*R\\d+
  9. repo-root docs   this repo's developer-private docs/ tree (man pages, glossary,
                      upstream index, analysis notes) — see repo_docs_hits()

Items 1–4 and 8 are dev-manual VOCABULARY and items 5–7 and 9 are dangling
POINTERS. Both families apply to shipped md (the host agent reads it); only the
POINTER family applies to shipped runtime scripts (the host agent is required not
to read their source), where rule/decision ids in comments are legitimate
maintenance shorthand.

Three scan surfaces, each with its own rule family:

  1. Shipped md          — pointer + vocabulary families
  2. Shipped scripts     — pointer family only
  3. SDD artifacts (openspec/specs/** + openspec/changes/**, R5.11) — pattern 9
     only, since specs cite rule ids on nearly every line. Archived changes
     (frozen history) and the docs-writing change (the carve-out) are skipped.

Scan set mirrors install.sh source set (design D1): the md trees
releases/<platform>/{commands,agents,skills,command,agent} + core/prompts/**
+ core/contracts/**, PLUS the shipped runtime scripts (core/scripts/**,
releases/<platform>/hooks/**, releases/opencode/plugins/**). The repo-root
docs/ tree is the developer's private workspace: install.sh does NOT copy it
into a target project, so it is deliberately NOT a scan root — and pointing at
it from shipped content is exactly what pattern 9 catches. Exempt by
construction: AGENTS.md, openspec/**, tools/, tests/, docs/** (incl. docs/man),
README, task.*, core/docs/ (R1 attribution records).

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

# Scan roots mirror install.sh source set (design D1) — md trees only. The
# repo-root docs/ tree is NOT listed on purpose: it is the developer's private
# workspace and install.sh never copies it into a target project (docs/man/
# used to ship and no longer does — see the CHANGELOG entry for this change).
SCAN_DIRS = [
    ROOT / "releases" / "claude-code" / "commands",
    ROOT / "releases" / "claude-code" / "agents",
    ROOT / "releases" / "claude-code" / "skills",
    ROOT / "releases" / "opencode" / "command",
    ROOT / "releases" / "opencode" / "agent",
    ROOT / "core" / "prompts",
    ROOT / "core" / "contracts",
]

# Shipped runtime scripts. install.sh copies core/ wholesale plus the platform
# hooks/ + opencode plugins/, so these land in a target project and a comment
# citing an upstream doc path is exactly as dead there as a shell line would be.
# The md-only scan historically missed this (discover_controls.py cited the
# upstream design-doc path); extending the scan is what closed that gap.
SCAN_SCRIPT_DIRS = [
    ROOT / "core" / "scripts",
    ROOT / "releases" / "claude-code" / "hooks",
    ROOT / "releases" / "opencode" / "hooks",
    ROOT / "releases" / "opencode" / "plugins",
]
SCAN_SCRIPT_GLOBS = ("*.py", "*.ts", "*.json", "*.json.example")

# Two families, split by who can actually hit them.
#
# POINTER patterns name a path / folder that resolves to nothing in a target
# project: a reader who follows one hits a dead end. Applied to EVERY shipped
# file — md and runtime scripts alike.
POINTER_PATTERNS = [
    ("change_folder",
     re.compile(r"\b(add|fix|harden|improve|purify)-mgh-(init|sast|sra|blst|srr|ut-init)-[a-z0-9-]+"),
     "improve-mgh-init-llm-discovery"),
    ("upstream_doc",
     re.compile(r"glasswing_docs/"), "glasswing_docs/09"),
    ("dev_file_ptr",
     re.compile(r"\btask\.\d+\.md\b"), "task.260630.md"),
]

# VOCAB patterns name dev-manual VOCABULARY (rule / failure / decision ids,
# dev-meta phrasing). Applied to shipped md ONLY: the host agent is required to
# run these scripts without reading their source (errors go to stderr), so the
# target never encounters a `R5.9` in a script comment — while the scripts'
# comments legitimately carry that shorthand for the repo's own maintenance.
VOCAB_PATTERNS = [
    ("rule_id",
     re.compile(r"\bR\d+(\.\d+)?\b"), "R5.2"),
    ("failure_id",
     re.compile(r"\bFD\d+\b"), "FD8"),
    ("decision_id",
     re.compile(r"\bD\d+\b"), "D12"),
    ("dev_manual_xref",
     re.compile(r"AGENTS\.md\s+R\d"), "AGENTS.md R1–R4"),
    ("dev_meta",
     re.compile(r"范式锚点|承\s*R\d+|兑现\s*R\d+"), "承 R5.7 / 范式锚点"),
]

# --- pattern 9: repo-root docs/ (developer-private; never shipped) -----------
# Three families share the `docs/` prefix and MUST be told apart, or the rule
# either misses the real thing or drowns in false positives:
#   • repo-root docs/  — man pages, glossary, upstream index, analysis notes.
#     The developer's private workspace; install.sh never copies it, so a
#     pointer to it is a dead link in every target project. FLAG.
#   • docs/security-controls/ , docs/test-conventions/ — directories the tooling
#     CREATES inside the target project at runtime (mgh-init / mgh-ut-init
#     outputs). A different repo entirely. EXEMPT.
#   • core/docs/NOTICE , core/docs/prompt-provenance.md — Apache-2.0 attribution
#     records; `core/` ships as `<dest>/mgh-core/`, so this namespace merely
#     contains the substring. EXEMPT.
# `+` not `*`: a bare `docs/` names the directory in prose (the rule's own name,
# `<target>/docs/`), it does not point AT anything under it. Only `docs/<entry>`
# is a pointer.
REPO_DOCS_RX = re.compile(r"docs/[A-Za-z0-9_./一-鿿-]+")
TARGET_DOCS_DIRS = frozenset({"security-controls", "test-conventions"})
# `code.claude.com/docs/en/memory.md` / `opencode.ai/docs/rules` are upstream
# URLs cited as provenance, not repo paths.
UPSTREAM_URL_RX = re.compile(r"[A-Za-z0-9-]+\.[A-Za-z]{2,}/$")

# core/prompts/** is a verbatim port (R1-frozen): its body prose is the upstream
# authors' words and mentions the UPSTREAM project's own doc layout
# ("docs/manifests/tree", "docs/config/non-code files"). Pattern 9 is skipped
# there — the text cannot be edited, so flagging it would be an unfixable
# failure. Repo-authored prose lives in the shells / agents / skills / contracts
# / scripts, which stay in scope.
VERBATIM_PROSE_ROOT = ROOT / "core" / "prompts"

# --- R5.11: SDD artifacts (openspec) ----------------------------------------
# Proposals / designs / tasks / specs are TRACKED and get read by later agents,
# so a pointer to the maintainer's private docs/ area sends a future reader to a
# file that may not exist on their machine — the directory is private, and
# whether it is even committed is the maintainer's call. Only pattern 9 applies
# here: these artifacts legitimately cite rule / decision / change ids on nearly
# every line, so the vocabulary family would be pure noise.
SDD_SCAN_DIRS = [
    ROOT / "openspec" / "specs",
    ROOT / "openspec" / "changes",
]
# Frozen history: archived changes record what was thought AT THE TIME and guide
# no new work; retro-editing them would be busywork that also falsifies the
# record. `openspec/changes/archive/<date>-<name>/` is skipped whole.
SDD_SKIP_PARTS = frozenset({"archive"})
# R5.11 carve-out: when a change's REQUIREMENT is to write files under the
# private docs/ area, the path IS the deliverable rather than a pointer to
# somewhere else. Keyed by change-folder name.
SDD_EXEMPT_CHANGES = frozenset({"add-skill-dev-experience-doc"})


def repo_docs_hits(line):
    """Pattern-9 hits: repo-root docs/ refs that are not one of the two exempt
    families above."""
    out = []
    for m in REPO_DOCS_RX.finditer(line):
        prefix = line[:m.start()]
        # `glasswing_docs/09` — `docs` is the tail of a longer word, not a path
        # segment. A real reference is preceded by a boundary (start of line,
        # space, quote, backtick, paren, or a `/`).
        if prefix and (prefix[-1].isalnum() or prefix[-1] in "_-"):
            continue
        if prefix.endswith("core/"):          # core/docs/ attribution namespace
            continue
        if m.group(0)[len("docs/"):].split("/", 1)[0] in TARGET_DOCS_DIRS:
            continue
        if UPSTREAM_URL_RX.search(prefix):    # upstream doc URL
            continue
        out.append({"pattern": "repo_docs", "token": m.group(0)})
    return out


def _sdd_kept(p):
    """False for openspec artifacts that R5.11 leaves alone: archived changes
    (frozen history) and the docs-writing change (the carve-out)."""
    try:
        parts = p.resolve().relative_to((ROOT / "openspec").resolve()).parts
    except ValueError:
        return True
    if len(parts) >= 2 and parts[0] == "changes":
        return parts[1] not in SDD_SKIP_PARTS and parts[1] not in SDD_EXEMPT_CHANGES
    return True


def scan_mode(p):
    """Which rule family `p` gets.

    sdd    — openspec artifact: pattern 9 only (rule ids are legitimate there).
    md     — shipped markdown: pointer + vocabulary families.
    script — shipped runtime script: pointer family only (the host agent is
             required not to read their source, so id shorthand in comments is
             legitimate maintenance shorthand).
    """
    if p.resolve().is_relative_to(ROOT / "openspec"):
        return "sdd"
    return "md" if p.suffix.lower() == ".md" else "script"


def gather_files(explicit):
    """Collect scanned files: explicit override list, else the install-mirrored
    globs (md trees + runtime scripts) plus the SDD artifacts."""
    if explicit:
        return [Path(f) for f in explicit]
    out, seen = [], set()

    def add(p):
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            out.append(p)

    for d in SCAN_DIRS:
        if d.is_dir():
            for p in sorted(d.rglob("*.md")):
                add(p)
    for d in SCAN_SCRIPT_DIRS:
        if d.is_dir():
            for g in SCAN_SCRIPT_GLOBS:
                for p in sorted(d.rglob(g)):
                    add(p)
    for d in SDD_SCAN_DIRS:
        if d.is_dir():
            for p in sorted(d.rglob("*.md")):
                if _sdd_kept(p):
                    add(p)
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
        description="R5.10 distribution-purity lint: shipped md + shipped runtime "
                    "scripts MUST be free of dev-only provenance / dangling "
                    "references (incl. this repo's developer-private docs/ tree)")
    ap.add_argument("--files", nargs="*", default=None,
                    help="scan these files explicitly "
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
        verbatim_prose = p.resolve().is_relative_to(VERBATIM_PROSE_ROOT)
        mode = scan_mode(p)
        for i, line in enumerate(text.splitlines(), 1):
            if mode == "sdd":
                hits = repo_docs_hits(line)
            else:
                active = (POINTER_PATTERNS + VOCAB_PATTERNS
                          if mode == "md" else POINTER_PATTERNS)
                hits = [{"pattern": name, "token": m.group(0)}
                        for name, rx, _ex in active for m in rx.finditer(line)]
                if not verbatim_prose:
                    hits += repo_docs_hits(line)
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
        print(f"✗ {len(violations)} offending line(s) across shipped files (R5.10):",
              file=sys.stderr)
        for v in violations:
            toks = ", ".join(f"{h['token']} ({h['pattern']})" for h in v["hits"])
            print(f"  {v['file']}:{v['line']}: {toks}", file=sys.stderr)
    elif not errors:
        print(f"✓ {len(files)} shipped file(s) clean "
              f"(no dev-only provenance / dangling refs)", file=sys.stderr)

    if errors:
        return 1
    return 2 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
