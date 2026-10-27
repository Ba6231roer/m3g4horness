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

Coverage reconciliation gate (inventory <-> rules, both formats): every control in
controls_inventory.json that carries evidence MUST have at least one evidence token
whose PATH (full normalized form or basename, via the shared anchor module's
normalization) appear in its category's rule-file text — opencode
<rules-dir>/<cat>.md; claude .claude/rules/security-<cat>.md. Any unrepresented
control -> opencode writes NOTHING, exit 2, stderr per-category counts + first N
control names (default 5; --coverage-top) — the orchestrator re-dispatches the
affected categories to T3 (same shape as a lint violation). `--accept-coverage-gaps`
is the ONLY relaxation switch: reconciliation still runs, the disclosure line is
still written, and the gap counts/categories land in stdout `coverage` for the run
report / manifest boundaries (`coverage_gaps_accepted`) — NEVER a silent pass. On
pass (or accepted) the opencode managed block carries an idempotent coverage
disclosure line (whole block regenerated each run, so the line never duplicates).
Inventory lookup: `--inventory` flag > <target>/.mgh-init/controls_inventory.json;
absent -> reconciliation skipped with disclosure (out-of-pipeline standalone use;
the in-pipeline step ordering guarantees the inventory before assembly).

claude format has NO index (T3 writes .claude/rules/security-<cat>.md directly, already
lazy via `paths:` scoping); for claude this script is lint + coverage gate (scans those
files; no AGENTS.md write involved).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/re/sys/pathlib).

CLI contract (`--help` is the contract surface, R5.1):
  py assemble_rules.py --target <dir> --format opencode|claude
       [--rules-dir <dir>] [--out <path>] [--check] [--dry-run]
       [--inventory <controls_inventory.json>] [--accept-coverage-gaps]
       [--coverage-top N]

  --target     target project root (default .)
  --format     opencode | claude (required)
  --rules-dir  opencode detail-file dir (default <target>/docs/security-controls;
               relative paths resolve against --target)
  --out        opencode: AGENTS.md path (default <target>/AGENTS.md);
               claude: rules dir to lint (default <target>/.claude/rules)
  --check      lint only — do not write (opencode); lint existing rule files (claude)
  --dry-run    compute but do not write (opencode normal mode)
  --inventory  controls_inventory.json for the coverage gate (default
               <target>/.mgh-init/controls_inventory.json; absent -> gate skipped
               with disclosure)
  --accept-coverage-gaps
               the ONLY relaxation of the coverage gate: still reconcile + still
               disclose; gaps land in stdout coverage (recorded as
               coverage_gaps_accepted in the run report / manifest boundaries)
  --coverage-top N
               max unrepresented control names per category on stderr (default 5)

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"format":"...","block":"security-controls"|null,"rules_dir":"...",
   "categories":[...],"migrated_legacy_blocks":N,
   "lint":{"ok":bool,"violations":[{"file,line,token}]},"written":bool,
   "coverage":{"skipped":bool[,"reason":...],"evaluated":N,"covered":M,
               "missing":K,"accepted":bool,"ok":bool,
               "by_category":{cat:{"covered":n,"missing":m}},
               "disclosure":"- 覆盖:M/N 控制已入规则..."|null}}
  coverage.evaluated counts controls carrying >=1 parseable evidence token (the
  gate denominator); covered+missing = evaluated.

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
2 misuse (argparse) or purity-lint violation or coverage-gate violation
(unrepresented controls without --accept-coverage-gaps) — fail-loud.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

# FD2 family convention: self-locate so any sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). The coverage gate imports the shared
# anchor normalization (anchor_resolve) — the T2 boundary existence gate reuses the
# SAME single source, never a private copy (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from anchor_resolve import (parse_anchor_token, normalize_for_match,  # noqa: E402
                            evidence_path_keys)

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


def _compose_index_block(entries, coverage_line=None):
    """Managed-block body (sentinels excluded): header + lazy directive + one line per
    detail file + footer directive + optional coverage disclosure line. `entries` =
    [(display_name, rel_ref), ...]. The whole block is regenerated per run, so the
    coverage line is idempotent by construction (never duplicated, dropped when the
    gate is skipped)."""
    lines = [BLOCK_HEADER, "", _LAZY_INTRO, ""]
    for display, rel in entries:
        lines.append(f"- {display} → @{rel}")
    lines += ["", _LAZY_FOOTER]
    # trailing "" keeps the no-coverage output byte-identical to the pre-gate form;
    # the coverage line slots in as its own paragraph before it
    lines += (["", coverage_line, ""] if coverage_line else [""])
    return "\n".join(lines)


def _coverage_disclosure_line(covered: int, evaluated: int) -> str:
    """The managed-block coverage line (opencode face; claude has no managed block —
    its disclosure is stdout-only + the run report)."""
    if covered == evaluated:
        return f"- 覆盖:{covered}/{evaluated} 控制已入规则(全部覆盖)"
    return f"- 覆盖:{covered}/{evaluated} 控制已入规则,缺口清单见运行报告"


def _reconcile_coverage(inventory_path: Path, category_texts: dict):
    """Inventory <-> rules coverage reconciliation (single source of matching keys:
    the shared anchor module). `category_texts` maps category -> NORMALIZED rule-file
    text ("" when the category's file is absent — every evidence miss then lands on
    `missing`, which is exactly the T3-missing case).

    Returns (coverage_dict, missing_by_category) where coverage_dict is the stdout
    `coverage` section (skipped shape when the inventory is absent — out-of-pipeline
    standalone use; the in-pipeline step ordering guarantees the inventory before
    assembly) and missing_by_category feeds the stderr gate listing."""
    if not inventory_path.is_file():
        return {"skipped": True,
                "reason": f"controls_inventory.json absent: {inventory_path}"}, {}
    try:
        inv = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"skipped": True,
                "reason": f"controls_inventory.json unreadable: {e}"}, {}
    controls = inv.get("controls") if isinstance(inv, dict) else None
    if not isinstance(controls, list):
        return {"skipped": True,
                "reason": "controls_inventory.json has no controls[] list"}, {}

    evaluated = covered = 0
    by_category: dict = {}
    missing_by_category: dict = {}
    for c in controls:
        if not isinstance(c, dict):
            continue
        ev = c.get("evidence")
        items = ev if isinstance(ev, list) else ([ev] if ev else [])
        tokens = [parse_anchor_token(a)[0] for a in items if isinstance(a, str)]
        tokens = [t for t in tokens if t]
        if not tokens:
            continue  # controls without parseable evidence are the T2 shape gate's
        evaluated += 1
        cat = str(c.get("category") or "")
        body = category_texts.get(cat, "")
        hit = any(k in body for tok in tokens for k in evidence_path_keys(tok))
        if hit:
            covered += 1
            by_category.setdefault(cat, {"covered": 0, "missing": 0})["covered"] += 1
        else:
            by_category.setdefault(cat, {"covered": 0, "missing": 0})["missing"] += 1
            missing_by_category.setdefault(cat, []).append(
                {"name": str(c.get("name") or "<unnamed>"), "category": cat})
    return {"skipped": False, "evaluated": evaluated, "covered": covered,
            "missing": evaluated - covered,
            "by_category": by_category}, missing_by_category


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


def _coverage_gate_stderr(coverage, missing_by_category, top):
    """stderr gate listing: per-category missing counts + first N control names."""
    for cat in sorted(missing_by_category):
        names = [m["name"] for m in missing_by_category[cat]]
        head = ", ".join(names[:top])
        more = f" (+{len(names) - top} more)" if len(names) > top else ""
        print(f"  [{cat}] missing={len(names)}: {head}{more}", file=sys.stderr)


def _finalize_coverage(coverage, missing_by_category, accepted):
    """Fill the derived gate fields (accepted/ok + opencode disclosure line)."""
    coverage["accepted"] = bool(accepted and not coverage.get("skipped"))
    coverage["ok"] = bool(coverage.get("skipped")
                         or coverage.get("missing", 0) == 0 or accepted)
    coverage["disclosure"] = (None if coverage.get("skipped") else
                              _coverage_disclosure_line(coverage["covered"],
                                                        coverage["evaluated"]))
    return coverage


def _opencode(args, rules_dir, out_path, target):
    # Snapshot the detail dir: [(path, text)] sorted by filename for determinism.
    files = sorted(rules_dir.glob("*.md")) if rules_dir.is_dir() else []
    texts = [(p, p.read_text(encoding="utf-8")) for p in files]
    entries = [(_display_name(text, p.stem), _index_ref(p, target)) for p, text in texts]
    categories = [p.stem for p in files]

    # Coverage reconciliation (inventory <-> rules): category text normalized once;
    # matching keys come from the shared anchor module (same normalization the T2
    # boundary existence gate uses — never a private copy).
    category_texts = {p.stem: normalize_for_match(text) for p, text in texts}
    coverage, missing_by_category = _reconcile_coverage(
        Path(args.inventory), category_texts)
    _finalize_coverage(coverage, missing_by_category, args.accept_coverage_gaps)
    coverage_line = coverage["disclosure"] if coverage["ok"] else None
    full_block = f"{BLOCK_BEGIN}\n{_compose_index_block(entries, coverage_line)}{BLOCK_END}"

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
        if not coverage["ok"]:
            print(f"[assemble_rules] coverage gate: {coverage['missing']}/"
                  f"{coverage['evaluated']} control(s) not represented in their "
                  f"category rule file", file=sys.stderr)
            _coverage_gate_stderr(coverage, missing_by_category, args.coverage_top)
    elif not files:
        print(f"warn: no detail files in {rules_dir}; {out_path} left unchanged",
              file=sys.stderr)
    elif violations:
        # fail-loud: do NOT persist a polluted index / detail snapshot
        print(f"[assemble_rules] {len(violations)} lint violation(s); "
              f"{out_path} NOT written", file=sys.stderr)
    elif not coverage["ok"]:
        # fail-loud coverage gate: do NOT persist an index that silently covers a
        # fraction of the inventory (same-shape path back to T3 as a lint violation)
        print(f"[assemble_rules] coverage gate: {coverage['missing']}/"
              f"{coverage['evaluated']} control(s) not represented in their category "
              f"rule file; {out_path} NOT written (re-dispatch affected categories "
              f"to T3; pass --accept-coverage-gaps to accept WITH disclosure)",
              file=sys.stderr)
        _coverage_gate_stderr(coverage, missing_by_category, args.coverage_top)
    else:
        cleaned, migrated = _strip_legacy_blocks(existing)
        new_content = _merge_into(cleaned, full_block)
        if not args.dry_run:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(new_content, encoding="utf-8")
            written = True
        print(f"[assemble_rules] opencode -> {out_path}: {len(files)} detail file(s), "
              f"{migrated} legacy block(s) migrated, written={written}", file=sys.stderr)
        if not coverage["skipped"]:
            print(f"[assemble_rules] coverage: {coverage['covered']}/"
                  f"{coverage['evaluated']} control(s) represented"
                  + (" (gaps ACCEPTED with disclosure)" if coverage["accepted"] else ""),
                  file=sys.stderr)

    return {
        "format": "opencode",
        "block": "security-controls",
        "rules_dir": str(rules_dir),
        "categories": categories,
        "migrated_legacy_blocks": migrated,
        "lint": {"ok": len(violations) == 0, "violations": violations},
        "written": written,
        "coverage": coverage,
    }


def _claude(args, rules_dir):
    files = sorted(rules_dir.glob("security-*.md")) if rules_dir.is_dir() else []
    if not files:
        print(f"warn: no security-*.md in {rules_dir}", file=sys.stderr)
    violations = []
    for f in files:
        violations.extend(_lint(f.read_text(encoding="utf-8"), str(f)))
    # coverage gate, claude face: stem security-<cat> -> category key; same shared
    # matching keys; no managed block here — the disclosure lives in stdout + the
    # run report (claude rules are already lazy via paths: scoping)
    category_texts = {f.stem[len("security-"):]: normalize_for_match(
        f.read_text(encoding="utf-8")) for f in files}
    coverage, missing_by_category = _reconcile_coverage(
        Path(args.inventory), category_texts)
    _finalize_coverage(coverage, missing_by_category, args.accept_coverage_gaps)
    print(f"[assemble_rules] claude: linted {len(files)} rule file(s), "
          f"{len(violations)} violation(s)", file=sys.stderr)
    if not coverage["ok"]:
        print(f"[assemble_rules] coverage gate: {coverage['missing']}/"
              f"{coverage['evaluated']} control(s) not represented", file=sys.stderr)
        _coverage_gate_stderr(coverage, missing_by_category, args.coverage_top)
    elif not coverage["skipped"]:
        print(f"[assemble_rules] coverage: {coverage['covered']}/"
              f"{coverage['evaluated']} control(s) represented"
              + (" (gaps ACCEPTED)" if coverage["accepted"] else ""), file=sys.stderr)
    return {
        "format": "claude",
        "block": None,
        "rules_dir": str(rules_dir),
        "categories": [f.stem for f in files],
        "migrated_legacy_blocks": 0,
        "lint": {"ok": len(violations) == 0, "violations": violations},
        "written": False,
        "coverage": coverage,
    }


def main():
    ap = argparse.ArgumentParser(
        description="build the opencode lazy-load rules index in AGENTS.md from "
                    "<rules-dir>/*.md detail files + purity lint + inventory<->rules "
                    "coverage gate (R5.3 leaf script)")
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
    ap.add_argument("--inventory", metavar="<controls_inventory.json>",
                    help="controls_inventory.json for the coverage gate (default "
                    "<target>/.mgh-init/controls_inventory.json; absent -> gate "
                    "skipped with disclosure)")
    ap.add_argument("--accept-coverage-gaps", action="store_true",
                    help="the ONLY relaxation of the coverage gate: still reconcile "
                    "+ still disclose; gaps land in stdout coverage for the run "
                    "report / manifest boundaries (coverage_gaps_accepted)")
    ap.add_argument("--coverage-top", type=int, default=5, metavar="N",
                    help="max unrepresented control names per category on stderr "
                    "(default 5)")
    args = ap.parse_args()

    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"error: target not a directory: {target}", file=sys.stderr)
        return 1

    if args.inventory:
        inventory_path = Path(args.inventory)
        if not inventory_path.is_absolute():
            inventory_path = (target / inventory_path).resolve()
    else:
        inventory_path = target / ".mgh-init" / "controls_inventory.json"
    args.inventory = str(inventory_path)

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
        summary = _claude(args, rules_dir)

    print(json.dumps(summary, ensure_ascii=False))
    return 2 if not (summary["lint"]["ok"] and summary["coverage"]["ok"]) else 0


if __name__ == "__main__":
    sys.exit(main())
