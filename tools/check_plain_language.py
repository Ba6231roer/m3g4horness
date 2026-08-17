#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""check_plain_language — plain-language-doctrine proxy lint.

Deterministic, machine-checkable subset of the plain-language doctrine
(AGENTS.md R3 受众声明制). True readability cannot be machine-tested; the
human gate (maintainer restates the change from preamble + tasks.md) covers
the rest. This lint enforces / warns on:

  1. preamble existence   every openspec/changes/*/proposal.md MUST open
                          with a `> **人话序**` blockquote. Missing =
                          structural defect -> exit 2 (fail-loud).
                          Legacy pre-doctrine changes are exempt via
                          --allowlist `<change-name>` lines (mirrors
                          check_distributed_purity.py's escape hatch).
  2. jargon blacklist     banned coined/compressed terms (物化 / 拒识 /
                          接线 / 治类 / 锚 / 哨兵 / 运行域 ...) hit in a
                          human-facing file -> WARN, exit 0. Whole-term
                          matching only ("哨兵" is legit once defined, so
                          blacklist is advisory; glossary is the authority).
  3. english-atom density prose lines in human-facing files whose
                          non-identifier ASCII words exceed a fraction
                          threshold -> WARN, exit 0. Skips fenced code,
                          inline `code`, `> ` quote lines, pure-path lines
                          (legit flags/paths in man pages must not trip).

Human-facing scan set (audience-declared, per R3): openspec/changes/*/
proposal.md, docs/man/**, docs/glossary.md. Glossary table rows (lines
starting with `|`) are exempt from the jargon check — the glossary is where
blacklisted terms are DEFINED. Agent-facing files (stage prompts, contracts,
JSON schemas, command shells) are NEVER scanned here.

Contract (R5.3): `--help` IS the CLI surface; stdout=JSON {scanned,
missing_preambles[], warnings[], allowlisted}; stderr=human diagnostics;
exit 0 clean-or-warn-only / 2 missing preamble / 1 operational error.
Self-locating, any-cwd, `encoding="utf-8"`, zero runtime deps
(Python >=3.10 stdlib only).

Run:  py tools/check_plain_language.py
      py tools/check_plain_language.py --allowlist plain_language_allowlist.txt
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

PREAMBLE_MARKER = "> **人话序**"

# Human-facing files (audience: human, R3). Agent-facing md is never listed.
MAN_DIR = ROOT / "docs" / "man"
GLOSSARY = ROOT / "docs" / "glossary.md"
CHANGES_DIR = ROOT / "openspec" / "changes"

# Coined/compressed jargon banned from human-facing prose. Whole-term
# (word-boundary-ish) matches; no rule-id dev-meta here (that class is already
# enforced by check_distributed_purity.py).
BLACKLIST = [
    "物化",
    "拒识",
    "接线",
    "治类",
    "锚",
    "哨兵",
    "运行域",
    "扇出",
    "承重",
    "兜底",
    "范式锚点",
]

# English-atom density: prose lines whose non-identifier ASCII words
# (excludes --flags, paths, identifiers with _/./-) exceed this fraction of
# the line's word count -> WARN. Generous on purpose (WARN, not fail).
# English-atom density: prose lines whose bare english atoms (excludes
# --flags, paths, identifiers, known tool names) exceed this fraction of all
# tokens (CJK + ascii words) -> WARN. Calibrated so a line with 1-2 legit
# english tokens in a full chinese sentence stays far below.
DENSITY_THRESHOLD = 0.1

_ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-']*")
# Identifier-like tokens: contain _ . / \ or start with -- (flags, paths,
# code identifiers). These are legitimate in man pages and never counted as
# bare english atoms.
_IDENT = re.compile(r"[_/\\]|^--")
_CJK = re.compile(r"[一-鿿]")
# Common legit english tokens in human-facing prose (tool names, platform
# names, well-known abbreviations). Kept english on purpose; not "atoms".
_SHORT_LABEL = re.compile(r"^[A-Za-z]\d$|^[st]\d{1,2}$", re.IGNORECASE)
_KNOWN = {"AI", "claude", "opencode", "openspec", "SAST", "SARIF", "CVSS",
          "CWE", "JSON", "Word", "Excel", "md", "txt", "git", "gitignore",
          "Spring", "Feign", "JPA", "AOP", "pitest", "py", "python",
          "JUnit", "pytest", "mock", "fixture", "word", "excel"}


def _strip_inline_code(line: str) -> str:
    return re.sub(r"`[^`]*`", " ", line)


def _english_atom_fraction(line: str) -> float | None:
    """Fraction of english non-identifier atoms among ALL word-like tokens
    (CJK chars included) in a prose line. Bare english spliced into chinese
    prose ("来源层 = producer 物化 repo 锚") scores high; a line with two
    legit tokens ("AI 知道…") scores near zero.

    Returns None when the line is not checkable prose (heading/quote line,
    table row, no CJK, no atoms, or only known/identifier/label tokens).
    """
    s = line.strip()
    if not s or s.startswith(">") or s.startswith("#"):
        return None  # quote lines and headings are structural
    if s.startswith("|"):
        return None  # table rows carry term columns by design
    stripped = _strip_inline_code(line)
    if not _CJK.search(stripped):
        return None  # no chinese — not mixed prose we can judge
    words = _ASCII_WORD.findall(stripped)
    atoms = [w for w in words
             if not _IDENT.search(w) and len(w) > 1 and w not in _KNOWN
             and not _SHORT_LABEL.match(w)]
    if not atoms:
        return None
    # denominator: CJK chars + ascii words (both count as tokens)
    denom = len(_CJK.findall(stripped)) + len(words)
    return len(atoms) / denom


def _iter_fenced(lines):
    """Yield (lineno, line, in_fence) skipping fenced code block interiors
    for prose checks (fence lines themselves are inert)."""
    in_fence = False
    fence = re.compile(r"^\s*(```|~~~)")
    for i, line in enumerate(lines, 1):
        if fence.match(line):
            in_fence = not in_fence
            continue
        yield i, line, in_fence


def load_allowlist(path: str | None) -> set[str]:
    """Each non-empty, non-`#` line: a change-name exempted from the
    preamble existence check (legacy pre-doctrine changes)."""
    allow = set()
    if not path:
        return allow
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        allow.add(line)
    return allow


def check_file_jargon_and_density(path: Path, rel: str, warnings: list,
                                  is_glossary: bool = False) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for i, line, in_fence in _iter_fenced(lines):
        if in_fence:
            continue
        for term in BLACKLIST:
            if term in line and not (is_glossary and line.lstrip().startswith("|")):
                warnings.append({
                    "file": rel, "line": i, "kind": "jargon",
                    "term": term, "excerpt": line.strip()[:80],
                })
        frac = _english_atom_fraction(line)
        if frac is not None and frac > DENSITY_THRESHOLD:
            warnings.append({
                "file": rel, "line": i, "kind": "english_density",
                "fraction": round(frac, 2), "excerpt": line.strip()[:80],
            })


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="plain-language-doctrine proxy lint: proposal preamble "
                    "existence (fail-loud) + jargon/english-density WARNs on "
                    "human-facing files only")
    ap.add_argument("--allowlist", default=None, metavar="FILE",
                    help="file of change-name lines exempted from the "
                         "preamble existence check (legacy pre-doctrine "
                         "changes; default empty)")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    allow = load_allowlist(args.allowlist)
    missing, warnings, errors, allowlisted = [], [], [], 0

    # 1) preamble existence over every openspec/changes/*/proposal.md
    #    (archive/ excluded: doctrine applies to living change folders).
    proposals = []
    if CHANGES_DIR.is_dir():
        for d in sorted(CHANGES_DIR.iterdir()):
            if not d.is_dir() or d.name == "archive":
                continue
            p = d / "proposal.md"
            if p.is_file():
                proposals.append((d.name, p))

    # 2-3) jargon + density over human-facing files. The glossary is the
    # definition source — blacklisted terms appear there BY DESIGN (each
    # entry defines one), so jargon hits inside the glossary's term column
    # are informational only; still reported for visibility.
    human_files: list[tuple[Path, str]] = []
    if MAN_DIR.is_dir():
        human_files += [(p, str(p.relative_to(ROOT)).replace("\\", "/"))
                        for p in sorted(MAN_DIR.rglob("*.md"))]
    if GLOSSARY.is_file():
        human_files.append((GLOSSARY, "docs/glossary.md"))

    scanned = len(proposals) + len(human_files)
    for name, p in proposals:
        try:
            first_lines = p.read_text(encoding="utf-8").splitlines()[:10]
        except OSError as e:
            errors.append(f"{p}: read failed: {e}")
            continue
        if any(PREAMBLE_MARKER in ln for ln in first_lines):
            continue
        if name in allow:
            allowlisted += 1
            continue
        missing.append(name)

    for p, rel in human_files:
        try:
            check_file_jargon_and_density(p, rel, warnings,
                                          is_glossary=(p == GLOSSARY))
        except OSError as e:
            errors.append(f"{p}: read failed: {e}")

    summary = {"scanned": scanned, "missing_preambles": missing,
               "warnings": warnings, "allowlisted": allowlisted}
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    for e in errors:
        print(f"✗ {e}", file=sys.stderr)
    if missing:
        print(f"✗ {len(missing)} proposal(s) missing plain-language preamble "
              f"(`{PREAMBLE_MARKER}`):", file=sys.stderr)
        for name in missing:
            print(f"  openspec/changes/{name}/proposal.md", file=sys.stderr)
    if warnings:
        print(f"⚠ {len(warnings)} plain-language warning(s) "
              f"(advisory, exit 0):", file=sys.stderr)
        for w in warnings:
            if w["kind"] == "jargon":
                print(f"  {w['file']}:{w['line']}: jargon \"{w['term']}\" "
                      f"— glossary.md must define it or rephrase", file=sys.stderr)
            else:
                print(f"  {w['file']}:{w['line']}: english-atom density "
                      f"{w['fraction']} > {DENSITY_THRESHOLD}", file=sys.stderr)
    if not missing and not warnings and not errors:
        print(f"✓ {scanned} human-facing file(s) clean "
              f"(preambles present, no blacklisted jargon)", file=sys.stderr)

    if errors:
        return 1
    return 2 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
