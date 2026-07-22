#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
assemble_rules — deterministic opencode rules index builder + purity lint for /mgh-init.

T3 (init-rulewriter) writes ONE shipped detail file per category directly to
<target>/<rules-dir>/<category>.md (default <target>/docs/security-controls/<cat>.md;
neutral, independent H1 document, no outer sentinels). This script builds a CONCISE
lazy-load INDEX block in <target>/AGENTS.md that references them — the rule BODIES stay
in the per-category detail files, so opencode's root context (which loads ALL of AGENTS.md
eagerly) is not bloated. opencode has no path-scoping, so lazy loading is driven by a
semantic directive in the index ("Read the detail file only when the task touches that
domain"), verbatim-aligned with opencode docs ("Manual Instructions in AGENTS.md").

The index block (owned by this script — T3 NEVER writes AGENTS.md):

    <!-- security-controls:begin -->
    ## 安全设计 — 复用,勿重造
    本项目已梳理出以下**既有可复用安全控制**...**按需加载**...读后内容即强制指令。
    - 认证 → @docs/security-controls/authentication.md
    - 授权 → @docs/security-controls/authorization.md
    > 涉及以上领域的新代码 MUST 先 Read 对应文件、复用既有实现;无对应文件 = 该领域无梳理出的存量控制。
    <!-- security-controls:end -->

Index = a real snapshot of <rules-dir>/*.md: each line's display name is the detail
file's first `#` heading (template strips the ` 安全控制` suffix), falling back to the
filename stem; the `@` ref is the detail path relative to the target. A category T3 wrote
no file for is simply absent (no orphan ref). Idempotent (R5.3b): replaces only the managed
block (or appends if absent) and preserves user content. On first run it sweeps legacy
branded blocks (<!-- mgh-init:begin(:cat)? --> ... <!-- mgh-init:end(:cat)? -->) so no
orphaned duplicate remains. Reusing the SAME neutral sentinel means an old "full inline"
block (this change's predecessor) is idempotently replaced by the index block on re-run —
zero extra migration logic.

Also runs a deterministic purity lint (`--check` / always) that fails loud (exit 2) if
tool-internal tokens leak into shipped detail files (R5.7 closed loop). The neutral
sentinel carries NO tool name, by contract.

claude format has NO index (T3 writes .claude/rules/security-<cat>.md directly, already
lazy via `paths:` scoping); for claude this script is lint-only (scans those files).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/re/sys/pathlib).

CLI contract (`--help` is the contract surface, R5.1):
  py assemble_rules.py --target <dir> --format opencode|claude
       [--rules-dir <dir>] [--out <path>] [--check] [--dry-run]

  --target     target project root (default .)
  --format     opencode | claude (required)
  --rules-dir  opencode detail-file dir (default <target>/docs/security-controls;
               relative paths resolve against --target)
  --out        opencode: AGENTS.md path (default <target>/AGENTS.md);
               claude: rules dir to lint (default <target>/.claude/rules)
  --check      lint only — do not write (opencode); lint existing rule files (claude)
  --dry-run    compute but do not write (opencode normal mode)

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"format":"...","block":"security-controls"|null,"rules_dir":"...",
   "categories":[...],"migrated_legacy_blocks":N,
   "lint":{"ok":bool,"violations":[{"file,line,token}]},"written":bool}

Purity lint — high-precision forbidden shapes (near-zero false positives on target
projects; scope = mgh-init's own shipped detail/rule files, never target source). Three
token families + one opencode-only structural check:
  (a) tool-internal identifiers — tool name + distinctive script basenames + internal
      paths (e.g. mgh-init / discover_controls.py / .mgh-init/);
  (b) inventory-schema field names — `found_controls` / `evidence_count`
      (controls_inventory.json headers leaked as front matter / metadata);
  (c) discovery-prose phrases — `扫描器模式定义` / `扫描器内部正则` / `扫描器定义` /
      `锚点:扫描器` (half-width) / `锚点：扫描器` (full-width) — scanner/regex internals
      leaked into the rule body or the anchor field.
  (d) opencode-only structural check — any `---` YAML-fence line inside an opencode
      detail file = front-matter leak (opencode detail files carry NO front matter).
      claude legitimately uses `paths:` front matter, so this fence check runs
      opencode-only (claude gets the token check, never the fence check).
Bare generic words (`category` / `缺失` / bare `锚点` / standalone `source:`·`evidence:`
keys) and generic script names (dedup.py / prefilter.py / emit_sarif.py /
expand_scope.py) and bare tier words (T1/T2/T3/scout) are intentionally EXCLUDED
(false-positive risk on target projects) — those are covered by the prompt guardrail
(init-rulewriter / rules-format fragments), which is non-deterministic. Edit in
lock-step with the honesty boundary in AGENTS.md.

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

# Lazy-load directive text (opencode has no path-scoping; loading is semantic). Verbatim
# aligned with opencode docs "Manual Instructions in AGENTS.md".
_LAZY_INTRO = ("本项目已梳理出以下**既有可复用安全控制**(存量实现,勿重新发明)。**按需加载**:"
               "仅当要改动的代码涉及某领域时,用 Read 工具读对应文件;**勿预先全加载**"
               "(省上下文)。读后内容即强制指令。")
_LAZY_FOOTER = ("> 涉及以上领域的新代码 MUST 先 Read 对应文件、复用既有实现;"
                "无对应文件 = 该领域无梳理出的存量控制。")

_LEGACY_BEGIN = re.compile(r"^\s*<!--\s*mgh-init:begin", re.IGNORECASE)
_LEGACY_END = re.compile(r"^\s*<!--\s*mgh-init:end", re.IGNORECASE)

# First ATX heading of a detail file -> index display name (any level 1-6, space after #).
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

# High-precision forbidden tokens — three families, near-zero false positives on
# target projects (scope = mgh-init's own shipped rules). Bare generic words
# (`category` / `缺失` / `锚点`) and generic script names are EXCLUDED (false-positive
# risk) — the prompt guardrail (init-rulewriter / rules-format fragments) covers
# those. Edit in lock-step with the honesty boundary in AGENTS.md.
FORBIDDEN_TOKENS = [
    # (a) tool-internal identifiers — tool name + distinctive script basenames + paths
    "mgh-init", "mgh_core", "mgh-core", "megahorn", "megahorness",
    "discover_controls.py", "chunk_sources.py", "plan_scout.py",
    "merge_scout.py", "list_clusters.py", "assemble_rules.py",
    ".mgh-init/",
    # (b) inventory-schema field names — controls_inventory.json headers leaked as
    #     front matter / metadata into shipped rules
    "found_controls", "evidence_count",
    # (c) discovery-prose phrases — scanner/regex internals leaked into the body / anchor
    "扫描器模式定义", "扫描器内部正则", "扫描器定义",
    "锚点:扫描器", "锚点：扫描器",
]

# opencode-only structural check: a `---` YAML-fence line inside a detail file =
# leaked front matter (opencode detail files carry NO front matter). claude legitimately
# uses `paths:` front matter, so this is enforced opencode-only via _lint's flag.
_YAML_FENCE = re.compile(r"^---+\s*$")


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


def _display_name(text, stem):
    """Index display name for a detail file = first `#` heading text, with the template
    suffix ` 安全控制` stripped for conciseness; falls back to the filename stem."""
    for line in text.splitlines():
        m = _HEADING.match(line.strip())
        if m:
            name = m.group(2).strip()
            if name.endswith(" 安全控制"):
                name = name[:-len(" 安全控制")].strip()
            return name or stem
    return stem


def _index_ref(path, target):
    """Detail-file path relative to the target (AGENTS.md dir), forward-slashed for the
    `@` reference. Falls back to the basename if the file is outside the target tree."""
    try:
        return str(path.resolve().relative_to(target.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def _compose_index_block(entries):
    """Managed-block body (sentinels excluded): header + lazy directive + one line per
    detail file + footer directive. `entries` = [(display_name, rel_ref), ...]."""
    lines = [BLOCK_HEADER, "", _LAZY_INTRO, ""]
    for display, rel in entries:
        lines.append(f"- {display} → @{rel}")
    lines += ["", _LAZY_FOOTER, ""]
    return "\n".join(lines)


def _lint(text, file_label, check_yaml_fence=False):
    """Return [{file,line,token}] for forbidden tokens in text (1-based lines).

    The `---` YAML-fence check is opencode-only: opencode detail files carry NO front
    matter, so a fence line inside a detail file = a leaked inventory header.
    claude legitimately uses `paths:` front matter, so claude MUST call with
    check_yaml_fence=False (token check only, never the fence check).
    """
    violations = []
    for i, line in enumerate(text.splitlines(), start=1):
        for tok in FORBIDDEN_TOKENS:
            if tok in line:
                violations.append({"file": file_label, "line": i, "token": tok})
        if check_yaml_fence and _YAML_FENCE.match(line):
            violations.append({"file": file_label, "line": i, "token": "--- YAML fence"})
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


def _opencode(args, rules_dir, out_path, target):
    # Snapshot the detail dir: [(path, text)] sorted by filename for determinism.
    files = sorted(rules_dir.glob("*.md")) if rules_dir.is_dir() else []
    texts = [(p, p.read_text(encoding="utf-8")) for p in files]
    entries = [(_display_name(text, p.stem), _index_ref(p, target)) for p, text in texts]
    categories = [p.stem for p in files]
    full_block = f"{BLOCK_BEGIN}\n{_compose_index_block(entries)}{BLOCK_END}"

    # Purity lint: scan each detail file (tokens + opencode YAML fence).
    violations = []
    for p, text in texts:
        violations.extend(_lint(text, str(p), check_yaml_fence=True))

    existing = out_path.read_text(encoding="utf-8") if out_path.is_file() else ""
    _, legacy_on_disk = _strip_legacy_blocks(existing)  # count only (no write here)

    written, migrated = False, 0

    if args.check:
        print(f"[assemble_rules] opencode --check: {len(files)} detail file(s), "
              f"{len(violations)} violation(s), {legacy_on_disk} legacy block(s) on disk",
              file=sys.stderr)
    elif not files:
        print(f"warn: no detail files in {rules_dir}; {out_path} left unchanged",
              file=sys.stderr)
    elif violations:
        # fail-loud: do NOT persist a polluted index / detail snapshot
        print(f"[assemble_rules] {len(violations)} lint violation(s); "
              f"{out_path} NOT written", file=sys.stderr)
    else:
        cleaned, migrated = _strip_legacy_blocks(existing)
        new_content = _merge_into(cleaned, full_block)
        if not args.dry_run:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(new_content, encoding="utf-8")
            written = True
        print(f"[assemble_rules] opencode -> {out_path}: {len(files)} detail file(s), "
              f"{migrated} legacy block(s) migrated, written={written}", file=sys.stderr)

    return {
        "format": "opencode",
        "block": "security-controls",
        "rules_dir": str(rules_dir),
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
        "rules_dir": str(rules_dir),
        "categories": [f.stem for f in files],
        "migrated_legacy_blocks": 0,
        "lint": {"ok": len(violations) == 0, "violations": violations},
        "written": False,
    }


def main():
    ap = argparse.ArgumentParser(
        description="build the opencode lazy-load rules index in AGENTS.md from "
                    "<rules-dir>/*.md detail files + purity lint (R5.3 leaf script)")
    ap.add_argument("--target", default=".", help="target project root (default .)")
    ap.add_argument("--format", required=True, choices=["opencode", "claude"],
                    help="opencode | claude (required)")
    ap.add_argument("--rules-dir", help="opencode detail-file dir (default "
                    "<target>/docs/security-controls; relative resolves against --target)")
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
        if args.rules_dir:
            rd = Path(args.rules_dir)
            rules_dir = (rd if rd.is_absolute() else target / rd).resolve()
        else:
            rules_dir = (target / "docs" / "security-controls").resolve()
        out_path = Path(args.out).resolve() if args.out else target / "AGENTS.md"
        summary = _opencode(args, rules_dir, out_path, target)
    else:
        rules_dir = (Path(args.out).resolve() if args.out
                     else target / ".claude" / "rules")
        summary = _claude(rules_dir)

    print(json.dumps(summary, ensure_ascii=False))
    return 2 if not summary["lint"]["ok"] else 0


if __name__ == "__main__":
    sys.exit(main())
