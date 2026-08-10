#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
assemble_test_rules — build the opencode lazy-load test-conventions index in AGENTS.md
from <rules-dir>/*.md detail files + purity lint (R5.3 leaf script, /mgh-ut-init).

  opencode — scans `<rules-dir>/*.md` (default <target>/docs/test-conventions) and builds
    a concise lazy index block in `<target>/AGENTS.md` under a NEUTRAL managed sentinel
    (`<!-- test-conventions:begin --> … :end -->`); idempotent (regex replace count=1),
    preserves all user content, migrates legacy `<!-- mgh-ut-init:… -->` blocks.
  claude   — no index (the rulewriter tier writes `.claude/rules/test-*.md` directly);
    lints those files only.

Purity lint (both formats, fail-loud exit 2 on violation): a rule/detail body MUST NOT leak
ut-internal tokens (tool name / distinctive script basenames / internal paths), inventory
schema fields (`assert_density`/`uniformity`/`weak_dominated`/`group_id`), or process prose
(`归类器子分`/`抽样提炼`/`断言密度`). opencode additionally flags any `---` YAML fence
(opencode detail files carry NO front matter, so a fence = leaked header); claude's `paths:`
frontmatter is exempt (check_yaml_fence=False).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/re/sys + pathlib).
CLI contract (`--help` is the contract surface, R5.1):
  py assemble_test_rules.py --target <dir> --format opencode|claude
       [--rules-dir <dir>] [--out <path>] [--check] [--dry-run]
stdout (structured JSON; stderr = diagnostics only, R5.3b):
  {"format":"...","block":"test-conventions"|null,"rules_dir":"...",
   "categories":[...],"migrated_legacy_blocks":N,
   "lint":{"ok":bool,"violations":[{file,line,token}]},"written":bool}
Exit codes (R5.3b): 0 ok · 1 general (target not a dir) · 2 misuse (argparse) or
purity-lint violation (fail-loud). Idempotent, no TTY.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

# Self-locate this script's dir (self-contained family, R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

BLOCK_BEGIN = "<!-- test-conventions:begin -->"
BLOCK_END = "<!-- test-conventions:end -->"
BLOCK_HEADER = "## 测试约定 — 复用,勿重造"
_LEGACY_BEGIN = re.compile(r"^\s*<!--\s*mgh-ut-init:begin", re.IGNORECASE)
_LEGACY_END = re.compile(r"^\s*<!--\s*mgh-ut-init:end", re.IGNORECASE)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_YAML_FENCE = re.compile(r"^---+\s*$")

_LAZY_INTRO = ("本项目已梳理出以下**既有测试约定**(团队真正在用的家法,勿重新发明)。**按需加载**:"
               "仅当要写的测试涉及某约定时,用 Read 工具读对应文件;**勿预先全加载**(省上下文)。"
               "读后内容即强制指令。")
_LAZY_FOOTER = ("> 涉及以上领域的新测试 MUST 先 Read 对应文件、遵循既有家法;"
                "无对应文件 = 该领域无梳理出的测试约定。")

# ut-internal tokens (a) + inventory-schema field names (b) + process prose (c).
FORBIDDEN_TOKENS = [
    # (a) tool-internal identifiers — tool name + distinctive script basenames + paths
    "mgh-ut-init", "mgh_ut_init", "mgh-ut-init", "megahorn", "megahorness",
    "classify_tests.py", "list_test_groups.py", "assemble_test_rules.py",
    "derive_mutators.py", "resume_ut_init_state.py", "write_ut_runconfig.py",
    ".mgh-ut-init/",
    # (b) inventory-schema field names — classify/extract headers leaked into rules
    "assert_density", "uniformity", "weak_dominated", "group_id",
    # (c) process prose — classifier/pipeline internals leaked into the body
    "归类器子分", "抽样提炼", "断言密度",
]


def _lint(text: str, file_label: str, check_yaml_fence: bool = False) -> list:
    """Return [{file,line,token}] for forbidden tokens in text (1-based lines)."""
    violations = []
    for i, line in enumerate(text.splitlines(), start=1):
        for tok in FORBIDDEN_TOKENS:
            if tok in line:
                violations.append({"file": file_label, "line": i, "token": tok})
        if check_yaml_fence and _YAML_FENCE.match(line):
            violations.append({"file": file_label, "line": i, "token": "--- YAML fence"})
    return violations


def _display_name(text: str, stem: str) -> str:
    """Index display name for a detail file = first `#` heading text, with the template
    suffix ` 测试约定` stripped; falls back to the filename stem."""
    for line in text.splitlines():
        m = _HEADING.match(line.strip())
        if m:
            name = m.group(2).strip()
            if name.endswith(" 测试约定"):
                name = name[: -len(" 测试约定")].strip()
            return name or stem
    return stem


def _index_ref(path: Path, target: Path) -> str:
    """Detail-file path relative to the target (AGENTS.md dir), forward-slashed for `@`."""
    try:
        return str(path.resolve().relative_to(target.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def _compose_index_block(entries) -> str:
    """Managed-block body (sentinels excluded): header + lazy directive + one line per
    detail file + footer directive. `entries` = [(display_name, rel_ref), ...]."""
    lines = [BLOCK_HEADER, "", _LAZY_INTRO, ""]
    for display, rel in entries:
        lines.append(f"- {display} → @{rel}")
    lines += ["", _LAZY_FOOTER, ""]
    return "\n".join(lines)


def _merge_into(content: str, full_block: str) -> str:
    """Replace existing test-conventions block (if any) else append; preserve rest."""
    if BLOCK_BEGIN in content and BLOCK_END in content:
        pattern = re.compile(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END),
                             re.DOTALL)
        return pattern.sub(lambda m: full_block, content, count=1)
    prefix = content
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix:
        prefix += "\n"
    return prefix + full_block + "\n"


def _strip_legacy_blocks(text: str):
    """Remove legacy branded managed blocks (`<!-- mgh-ut-init:begin… -->` …
    `<!-- mgh-ut-init:end… -->`). Line-based; returns (cleaned_text, count)."""
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
        print("warn: legacy `mgh-ut-init:begin` block had no matching `mgh-ut-init:end`; "
              "trailing lines dropped", file=sys.stderr)
    return "\n".join(out), count


def _opencode(args, rules_dir: Path, out_path: Path, target: Path) -> dict:
    files = sorted(rules_dir.glob("*.md")) if rules_dir.is_dir() else []
    texts = [(p, p.read_text(encoding="utf-8")) for p in files]
    entries = [(_display_name(text, p.stem), _index_ref(p, target)) for p, text in texts]
    categories = [p.stem for p in files]
    full_block = f"{BLOCK_BEGIN}\n{_compose_index_block(entries)}{BLOCK_END}"

    violations = []
    for p, text in texts:
        violations.extend(_lint(text, str(p), check_yaml_fence=True))

    existing = out_path.read_text(encoding="utf-8") if out_path.is_file() else ""
    _, legacy_on_disk = _strip_legacy_blocks(existing)

    written, migrated = False, 0
    if args.check:
        print(f"[assemble_test_rules] opencode --check: {len(files)} detail file(s), "
              f"{len(violations)} violation(s), {legacy_on_disk} legacy block(s) on disk",
              file=sys.stderr)
    elif not files:
        print(f"warn: no detail files in {rules_dir}; {out_path} left unchanged",
              file=sys.stderr)
    elif violations:
        print(f"[assemble_test_rules] {len(violations)} lint violation(s); "
              f"{out_path} NOT written", file=sys.stderr)
    else:
        cleaned, migrated = _strip_legacy_blocks(existing)
        new_content = _merge_into(cleaned, full_block)
        if not args.dry_run:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(new_content, encoding="utf-8")
            written = True
        print(f"[assemble_test_rules] opencode -> {out_path}: {len(files)} detail file(s), "
              f"{migrated} legacy block(s) migrated, written={written}", file=sys.stderr)

    return {
        "format": "opencode",
        "block": "test-conventions",
        "rules_dir": str(rules_dir),
        "categories": categories,
        "migrated_legacy_blocks": migrated,
        "lint": {"ok": len(violations) == 0, "violations": violations},
        "written": written,
    }


def _claude(args, rules_dir: Path) -> dict:
    files = sorted(rules_dir.glob("test-*.md")) if rules_dir.is_dir() else []
    violations = []
    for p in files:
        violations.extend(_lint(p.read_text(encoding="utf-8"), str(p),
                                check_yaml_fence=False))
    print(f"[assemble_test_rules] claude lint: {len(files)} rule file(s), "
          f"{len(violations)} violation(s)", file=sys.stderr)
    return {
        "format": "claude",
        "block": None,
        "rules_dir": str(rules_dir),
        "categories": [p.stem for p in files],
        "migrated_legacy_blocks": 0,
        "lint": {"ok": len(violations) == 0, "violations": violations},
        "written": False,
    }


def main():
    ap = argparse.ArgumentParser(
        description="build the opencode lazy-load test-conventions index in AGENTS.md from "
                    "<rules-dir>/*.md detail files + purity lint (R5.3 leaf script)")
    ap.add_argument("--target", default=".", help="target project root (default .)")
    ap.add_argument("--format", required=True, choices=["opencode", "claude"],
                    help="opencode | claude (required)")
    ap.add_argument("--rules-dir", help="opencode detail-file dir (default "
                    "<target>/docs/test-conventions; relative resolves against --target)")
    ap.add_argument("--out", help="opencode: AGENTS.md path (default <target>/AGENTS.md); "
                    "claude: rules dir to lint (default <target>/.claude/rules)")
    ap.add_argument("--check", action="store_true",
                    help="lint only, do not write (opencode); lint existing rule files (claude)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute but do not write (opencode normal mode)")
    # Emit JSON / glyphs cleanly regardless of host console codepage (e.g. cp936/gbk).
    # Before parse_args so --help is utf-8 too. No-op on StringIO (in-process tests).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = ap.parse_args()
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"error: target not a directory: {target}", file=sys.stderr)
        return 1

    if args.format == "opencode":
        rules_rel = args.rules_dir or "docs/test-conventions"
        rules_dir_path = Path(rules_rel)
        if not rules_dir_path.is_absolute():
            rules_dir_path = target / rules_rel
        rules_dir = rules_dir_path.resolve()
        out_path = (Path(args.out).resolve() if args.out else (target / "AGENTS.md"))
        summary = _opencode(args, rules_dir, out_path, target)
    else:
        rules_dir = (Path(args.out).resolve() if args.out else (target / ".claude" / "rules"))
        summary = _claude(args, rules_dir)
    print(json.dumps(summary, ensure_ascii=False))
    return 2 if not summary["lint"]["ok"] else 0


if __name__ == "__main__":
    sys.exit(main())
