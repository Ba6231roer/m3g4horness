#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
assemble_rules — deterministic opencode rules assembler + purity lint for /mgh-init.

T3 (init-rulewriter) writes ONE staged fragment per category to
<target>/.mgh-init/rules-parts/<category>.md (neutral, no outer sentinels). This
script merges them into a SINGLE neutral managed block in <target>/AGENTS.md:

    <!-- security-controls:begin -->
    ## 安全设计 — 复用,勿重造

    ### <Category>
    - **<Control>**: ... 锚点: src/.../X.java::Class.method
    <!-- security-controls:end -->

Idempotent (R5.3b): replaces only the managed block (or appends if absent) and
preserves user content. On first run it sweeps legacy branded blocks
(<!-- mgh-init:begin(:cat)? --> ... <!-- mgh-init:end(:cat)? -->) so no orphaned
duplicate remains. Also runs a deterministic purity lint (`--check` / always) that
fails loud (exit 2) if tool-internal tokens leak into shipped rules (R5.7 closed
loop). The neutral sentinel carries NO tool name, by contract.

claude format has NO assembly (T3 writes .claude/rules/security-<cat>.md directly);
for claude this script is lint-only (scans those files).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/re/sys/pathlib).

CLI contract (`--help` is the contract surface, R5.1):
  py assemble_rules.py --target <dir> --format opencode|claude
       [--parts <dir>] [--out <path>] [--check] [--dry-run]

  --target    target project root (default .)
  --format    opencode | claude (required)
  --parts     staged-fragment dir (opencode only; default <target>/.mgh-init/rules-parts)
  --out       opencode: AGENTS.md path (default <target>/AGENTS.md);
              claude: rules dir to lint (default <target>/.claude/rules)
  --check     lint only — do not write (opencode); lint existing rule files (claude)
  --dry-run   compute but do not write (opencode normal mode)

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"format":"...","block":"security-controls"|null,"categories":[...],
   "migrated_legacy_blocks":N,"lint":{"ok":bool,"violations":[{"file,line,token}]},"written":bool}

Purity lint — high-precision forbidden tokens (design D4): near-zero false positives
on target projects. Generic script names (dedup.py / prefilter.py / emit_sarif.py /
expand_scope.py) and bare tier words (T1/T2/T3/scout) are intentionally EXCLUDED
(target projects may legitimately contain them) — those are covered by the prompt
guardrail (init-induct/scout/synthesis/rulewriter), which is non-deterministic.

Exit codes (R5.3b): 0 ok · 1 general error (target not a dir) ·
2 misuse (argparse) or purity-lint violation (fail-loud).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

# FD2 family convention: self-locate so any sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). assemble_rules has no sibling import
# today, but the guard keeps it in the self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

BLOCK_BEGIN = "<!-- security-controls:begin -->"
BLOCK_END = "<!-- security-controls:end -->"
BLOCK_HEADER = "## 安全设计 — 复用,勿重造"

_LEGACY_BEGIN = re.compile(r"^\s*<!--\s*mgh-init:begin", re.IGNORECASE)
_LEGACY_END = re.compile(r"^\s*<!--\s*mgh-init:end", re.IGNORECASE)

# High-precision forbidden tokens (design D4). Generic script names + bare tier
# words are excluded (false-positive risk on target projects); the prompt
# guardrail covers those. Edit in lock-step with the honesty boundary in AGENTS.md.
FORBIDDEN_TOKENS = [
    "mgh-init", "mgh_core", "mgh-core", "megahorn", "megahorness",
    "discover_controls.py", "chunk_sources.py", "plan_scout.py",
    "merge_scout.py", "list_clusters.py", "assemble_rules.py",
    ".mgh-init/",
]


def _strip_legacy_blocks(text):
    """Remove legacy branded managed blocks (`<!-- mgh-init:begin(:cat)? -->` ...
    `<!-- mgh-init:end(:cat)? -->`). Line-based; returns (cleaned_text, count)."""
    out, count, skipping = [], 0, False
    for line in text.splitlines():
        if not skipping and _LEGACY_BEGIN.match(line):
            skipping, count = True, count + 1
            continue
        if skipping:
            if _LEGACY_END.match(line):
                skipping = False
            continue
        out.append(line)
    if skipping:
        print("warn: legacy `mgh-init:begin` block had no matching `mgh-init:end`; "
              "trailing lines dropped", file=sys.stderr)
    return "\n".join(out), count


def _read_fragments(parts_dir):
    """Sorted [(category, stripped_text)] for every <category>.md in parts_dir."""
    frags = []
    if parts_dir.is_dir():
        for p in sorted(parts_dir.glob("*.md")):
            frags.append((p.stem, p.read_text(encoding="utf-8").strip()))
    return frags


def _compose_block(frags):
    """Managed-block body (sentinels excluded): header + blank + each fragment."""
    body = [BLOCK_HEADER, ""]
    for _, text in frags:
        body.append(text)
        body.append("")
    return "\n".join(body).rstrip() + "\n"


def _lint(text, file_label):
    """Return [{file,line,token}] for forbidden tokens found in text (1-based lines)."""
    violations = []
    for i, line in enumerate(text.splitlines(), start=1):
        for tok in FORBIDDEN_TOKENS:
            if tok in line:
                violations.append({"file": file_label, "line": i, "token": tok})
    return violations


def _merge_into(content, full_block):
    """Replace existing security-controls block (if any) else append; preserve rest."""
    if BLOCK_BEGIN in content and BLOCK_END in content:
        pattern = re.compile(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END),
                             re.DOTALL)
        return pattern.sub(lambda m: full_block, content, count=1)
    prefix = content
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix:
        prefix += "\n"  # blank line between user content and the managed block
    return prefix + full_block + "\n"


def _opencode(args, parts_dir, out_path):
    frags = _read_fragments(parts_dir)
    categories = sorted(c for c, _ in frags)
    full_block = f"{BLOCK_BEGIN}\n{_compose_block(frags)}{BLOCK_END}"
    violations = _lint(full_block, str(out_path))

    existing = out_path.read_text(encoding="utf-8") if out_path.is_file() else ""
    _, legacy_on_disk = _strip_legacy_blocks(existing)  # count only (no write here)

    written, migrated = False, 0

    if args.check:
        print(f"[assemble_rules] opencode --check: {len(frags)} category(ies), "
              f"{len(violations)} violation(s), {legacy_on_disk} legacy block(s) on disk",
              file=sys.stderr)
    elif not frags:
        print(f"warn: no staged fragments in {parts_dir}; {out_path} left unchanged",
              file=sys.stderr)
    elif violations:
        # fail-loud: do NOT persist a polluted block
        print(f"[assemble_rules] {len(violations)} lint violation(s); "
              f"{out_path} NOT written", file=sys.stderr)
    else:
        cleaned, migrated = _strip_legacy_blocks(existing)
        new_content = _merge_into(cleaned, full_block)
        if not args.dry_run:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(new_content, encoding="utf-8")
            written = True
        print(f"[assemble_rules] opencode -> {out_path}: {len(frags)} category(ies), "
              f"{migrated} legacy block(s) migrated, written={written}", file=sys.stderr)

    return {
        "format": "opencode",
        "block": "security-controls",
        "categories": categories,
        "migrated_legacy_blocks": migrated,
        "lint": {"ok": len(violations) == 0, "violations": violations},
        "written": written,
    }


def _claude(rules_dir):
    files = sorted(rules_dir.glob("security-*.md")) if rules_dir.is_dir() else []
    if not files:
        print(f"warn: no security-*.md in {rules_dir}", file=sys.stderr)
    violations = []
    for f in files:
        violations.extend(_lint(f.read_text(encoding="utf-8"), str(f)))
    print(f"[assemble_rules] claude: linted {len(files)} rule file(s), "
          f"{len(violations)} violation(s)", file=sys.stderr)
    return {
        "format": "claude",
        "block": None,
        "categories": [f.stem for f in files],
        "migrated_legacy_blocks": 0,
        "lint": {"ok": len(violations) == 0, "violations": violations},
        "written": False,
    }


def main():
    ap = argparse.ArgumentParser(
        description="assemble opencode staged fragments into a single neutral "
                    "managed block in AGENTS.md + purity lint (R5.3 leaf script)")
    ap.add_argument("--target", default=".", help="target project root (default .)")
    ap.add_argument("--format", required=True, choices=["opencode", "claude"],
                    help="opencode | claude (required)")
    ap.add_argument("--parts", help="staged-fragment dir (opencode only; default "
                    "<target>/.mgh-init/rules-parts)")
    ap.add_argument("--out", help="opencode: AGENTS.md path (default <target>/AGENTS.md); "
                    "claude: rules dir to lint (default <target>/.claude/rules)")
    ap.add_argument("--check", action="store_true",
                    help="lint only, do not write (opencode); lint existing rule files (claude)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute but do not write (opencode normal mode)")
    args = ap.parse_args()

    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"error: target not a directory: {target}", file=sys.stderr)
        return 1

    if args.format == "opencode":
        parts_dir = (Path(args.parts).resolve() if args.parts
                     else target / ".mgh-init" / "rules-parts")
        out_path = Path(args.out).resolve() if args.out else target / "AGENTS.md"
        summary = _opencode(args, parts_dir, out_path)
    else:
        rules_dir = (Path(args.out).resolve() if args.out
                     else target / ".claude" / "rules")
        summary = _claude(rules_dir)

    print(json.dumps(summary, ensure_ascii=False))
    return 2 if not summary["lint"]["ok"] else 0


if __name__ == "__main__":
    sys.exit(main())
