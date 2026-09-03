#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
sdr_context — deterministic baseline projection + external-repo controlled retrieval for
/mgh-sdr. Runs in the ORCHESTRATOR's main flow (launcher process / host shell step 1),
NEVER in a subagent: this is the single place a cross-tree read happens, so subagent
sessions get materialized conclusion files only (zero cross-tree reads on the normal path).

(a) Baseline projection — extracts the 6-dimension-relevant sections from the target
repo's existing security design (AGENTS.md security-ish sections + docs/security-controls/
*.md + .mgh-sra/business_context.json if present) into <run-dir>/baseline.md, capped at
--baseline-budget-bytes (default 32KB); over-cap truncation follows the dimension priority
interface-authz > sql-injection > input-validation > sensitive-data and is disclosed as
baseline_truncated:true + truncated bytes on stdout.

(b) External-repo controlled retrieval — parses existing-design EXTERNAL-REPO DECLARATIONS
(a local absolute path of a frontend/external project + a same-branch convention, e.g.
"本地前端项目地址 D:/xxx/front,前端分支名与本项目一致"), and for each reachable one runs
controlled retrieval IN THIS PROCESS: the external repo's same-name-branch `git diff
--name-status` file list (vs the same base), permission-config hit lines (a config file
named in the declaration, e.g. buttonAuth.properties, scanned for the branch's new routes),
and occurrence counts of the new routes across the external repo's text files. Conclusions
materialize as small files under <run-dir>/external/<repo-slug>/ (per-repo byte budget,
default 64KB, over-cap truncation disclosed). stdout carries external_repos[] = the ACTUAL
searched roots (for the sentinel read_roots[] declaration) — NEVER any user-supplied
catch-all path. Declaration missing / path unreachable / not a git dir => graceful
degrade: external_repos: [] + external_skipped:<reason>, the flow continues.

(c) Sensitive-catalog resolution — project catalog <repo>/.mgh-sra/sensitive_catalog.json
exists => sibling-import sensitive_catalog and reuse (parse + closed-set validate; invalid
=> exit 2 BEFORE any LLM token); missing => fall back to the DEFAULT TEMPLATE shipped by
install (.mgh-sra/sensitive_catalog.json.example = PIPL/GB-T 35273 37 items). This fallback
is the DELIBERATE sdr-vs-sra/srr divergence (code-diff review falls back to the wider
default template instead of narrowing to 6 facets); the resolved object + source
(project|default-template) ride stdout verbatim into subagent task messages.

Exit codes (R5.3b): 0 ok · 1 input error (--repo/--run-dir missing) · 2 misuse (argparse)
or closed-set violation (project catalog invalid / --check violations).
--check <run-dir>: baseline.md exists within budget, external conclusion files complete,
sensitive_catalog object shape valid (R5.9).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/re/sys/pathlib).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_BASELINE_BUDGET = 32 * 1024   # 32KB
DEFAULT_EXTERNAL_BUDGET = 64 * 1024   # 64KB per external repo

# Baseline dimension priority (truncation order; interface-authz first — it is the
# highest-yield check face for interface units).
DIMENSION_PRIORITY = [
    ("vertical-authz", ("垂直越权", "vertical", "鉴权", "权限", "authz", "buttonAuth",
                        "角色", "拦截器", "注解")),
    ("horizontal-authz", ("横向越权", "越权", "brch", "机构", "数据权限", "IDOR")),
    ("sql-injection", ("SQL", "注入", "注入攻击", "mybatis", "#\\$", "预编译")),
    ("input-validation", ("输入校验", "参数校验", "校验", "validation", "@Valid")),
    ("sensitive-data", ("敏感信息", "脱敏", "敏感数据", "个人信息", "掩码", "屏蔽")),
    ("other-authz", ("其他权限", "登录", "会话", "session", "token", "白名单")),
]

# External-repo declaration patterns: a local absolute path (drive-letter / UNC / POSIX
# abs) inside a sentence that ALSO mentions an external/frontend project + a branch or
# consistency convention. Regex-over-observed-shape (declaration prose varies); the path
# token itself is validated by existence checks downstream.
_EXT_PATH_RX = re.compile(
    r'([A-Za-z]:[\\/][^\s,，。;；"\'()（）]+|\\\\[^\s,，。;；"\'()（）]+|/[a-zA-Z][^\s,，。;；"\'()（）]+)')
_EXT_CTX_RX = re.compile(r'(前端|外部|front|frontend|另一个项目|另一仓|姊妹仓)', re.IGNORECASE)
_BRANCH_CONV_RX = re.compile(r'(同名分支|分支.{0,8}一致|branch.{0,12}(same|一致)|同版本分支)')
_CONFIG_FILE_RX = re.compile(r'([\w.-]+\.properties|[\w.-]+\.json|[\w.-]+\.yml|[\w.-]+\.yaml)')
_SLUG_RX = re.compile(r'[^a-zA-Z0-9_-]+')

# Source files scanned for declarations + baseline sections (closed set, deterministic
# order). A target repo WITHOUT any of these yields an empty baseline + no declarations.
_DECLARATION_SOURCES = ("AGENTS.md", "CLAUDE.md", "README.md")
_CONTROLS_DIR = "docs/security-controls"
_BASELINE_SECTIONS_RX = re.compile(
    r'^#{1,4}\s+.*(安全|权限|鉴权|认证|注入|脱敏|敏感|校验|安全设计|security).*$', re.IGNORECASE)


def _eprint(*a):
    print(*a, file=sys.stderr)


def _safe_slug(name: str) -> str:
    return _SLUG_RX.sub("_", name).strip("_") or "external"


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        try:
            return p.read_text(encoding="gbk", errors="replace")
        except OSError:
            return ""


# --- (a) baseline projection -------------------------------------------------

def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (header_line, section_body) chunks (header belongs to body)."""
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    cur_head, cur_body = "", []
    for ln in lines:
        if _BASELINE_SECTIONS_RX.match(ln):
            if cur_head or cur_body:
                sections.append((cur_head, "\n".join(cur_body)))
            cur_head, cur_body = ln, [ln]
        elif cur_head:
            cur_body.append(ln)
        else:
            cur_body.append(ln)
    if cur_head or cur_body:
        sections.append((cur_head, "\n".join(cur_body)))
    return sections


def _section_scores(body: str) -> list[str]:
    """Dimensions this section plausibly serves (matched against the priority keyword
    sets). A section matching nothing is still kept at the lowest priority (never
    silently dropped before budget)."""
    low = body.lower()
    hits = []
    for dim, kws in DIMENSION_PRIORITY:
        if any(kw.lower() in low for kw in kws):
            hits.append(dim)
    return hits or ["other-authz"]


def _project_baseline(repo: Path, budget: int) -> tuple[str, bool, int]:
    """Return (baseline_text, truncated, truncated_bytes). Sections sorted by their
    highest-priority dimension, then source order; kept whole until the budget runs out
    (whole-section granularity — a mid-section cut would corrupt the design statements)."""
    chunks: list[tuple[int, int, str, str]] = []  # (prio_rank, source_rank, source, section)
    sources: list[str] = []
    for name in _DECLARATION_SOURCES:
        p = repo / name
        if p.is_file():
            sources.append(_read_text(p))
    controls = repo / _CONTROLS_DIR
    if controls.is_dir():
        for p in sorted(controls.glob("*.md")):
            sources.append(_read_text(p))
    bc = repo / ".mgh-sra" / "business_context.json"
    if bc.is_file():
        sources.append("```json\n" + _read_text(bc) + "\n```")
    prio_names = [d for d, _ in DIMENSION_PRIORITY]
    for srank, text in enumerate(sources):
        for head, body in _split_sections(text):
            dims = _section_scores(body)
            rank = min(prio_names.index(d) if d in prio_names else len(prio_names)
                       for d in dims)
            chunks.append((rank, srank, head or "(preamble)", body))
    chunks.sort(key=lambda c: (c[0], c[1]))
    kept: list[str] = []
    used = 0
    truncated_bytes = 0
    truncated = False
    seen_sources: set[str] = set()
    for rank, _srank, head, body in chunks:
        entry = f"### 来源: {head}\n{body.strip()}\n"
        size = len(entry.encode("utf-8"))
        if used + size > budget:
            truncated = True
            truncated_bytes += size
            continue
        kept.append(entry)
        used += size
        seen_sources.add(head)
    header = ("# SDR 检查基线(存量安全设计投影)\n\n"
              "由 sdr_context.py 从项目存量安全设计确定性投影;按维度优先级截断披露于 stdout。"
              "\n\n")
    return header + "\n".join(kept), truncated, truncated_bytes


# --- (b) external-repo controlled retrieval ----------------------------------

def _git(repo: Path, *args: str):
    import subprocess
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def _parse_declarations(texts: list[str]) -> tuple[list[dict], list[str]]:
    """(declarations, skips). Extract external-repo declarations (path + branch
    convention + named config file) from the design texts. A declared path that does not
    exist becomes a skip reason (\"not-found: <path>\") so the degradation is disclosed,
    never silent."""
    decls: dict[str, dict] = {}
    skips: list[str] = []
    for text in texts:
        if not text:
            continue
        for para in re.split(r"\n\s*\n", text):
            if not _EXT_CTX_RX.search(para):
                continue
            for m in _EXT_PATH_RX.finditer(para):
                path = m.group(1).rstrip(".,;、)")
                cand = Path(path)
                if not cand.is_absolute():
                    continue
                if not cand.is_dir():
                    if path not in skips:
                        skips.append(f"not-found: {path}")
                    continue
                entry = decls.setdefault(str(cand), {
                    "path": str(cand), "branch_sync": bool(_BRANCH_CONV_RX.search(para)),
                    "config_files": [], "source_snippet": para.strip()[:300],
                })
                entry["branch_sync"] = entry["branch_sync"] or bool(_BRANCH_CONV_RX.search(para))
                for cf in _CONFIG_FILE_RX.finditer(para):
                    if cf.group(1) not in entry["config_files"]:
                        entry["config_files"].append(cf.group(1))
    return list(decls.values()), skips


def _external_slug(decl: dict) -> str:
    return _safe_slug(Path(decl["path"]).name)


def _new_routes(repo: Path, base: str, branch: str) -> list[str]:
    """Branch-new interface route strings (java mapping annotations in the diff's added
    lines, joined with class-level base routes where trivially visible). Best-effort by
    design: the occurrence count in the external repo is the signal, not a route registry."""
    r = _git(repo, "diff", "--no-color", "-U0", f"{base}..{branch}", "--", "*.java")
    if r.returncode != 0:
        return []
    routes: set[str] = set()
    for m in re.finditer(r'^\+.*@(?:Get|Post|Put|Delete|Patch)Mapping\s*\(\s*(?:value\s*=\s*)?"([^"]*)"',
                         r.stdout, re.MULTILINE):
        if m.group(1):
            routes.add(m.group(1))
    return sorted(routes)


def _external_retrieve(decl: dict, repo: Path, base: str, branch: str,
                       budget: int, run_dir: Path) -> dict | None:
    """Controlled retrieval in ONE external repo; returns the conclusion record or None
    when the repo is unreachable/not-git/degraded-unusable (caller discloses the skip)."""
    ext = Path(decl["path"])
    if not ext.is_dir():
        return None
    if _git(ext, "rev-parse", "--git-dir").returncode != 0:
        return None
    slug = _external_slug(decl)
    out_dir = run_dir / "external" / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    # branch resolution: same-name branch preferred, default-branch fallback disclosed
    target_branch = branch
    branch_fallback = False
    if _git(ext, "rev-parse", "--verify", "--quiet", branch).returncode != 0:
        default = _git(ext, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"
        target_branch = default
        branch_fallback = True

    # 1) external diff file list (same base, its branch)
    lines: list[str] = [f"# 外部仓检索结论: {slug}", f"external_path: {decl['path']}",
                        f"branch: {target_branch}" +
                        ("(同名分支缺失,回退默认分支)" if branch_fallback else ""),
                        f"base: {base}", ""]
    d = _git(ext, "diff", "--no-color", "--name-status", f"{base}..{target_branch}")
    file_list: list[str] = []
    if d.returncode == 0 and d.stdout.strip():
        file_list = [l for l in d.stdout.splitlines() if l.strip()]
        lines += ["## 外部 diff 文件清单(变更类型)", *[f"- {l}" for l in file_list], ""]

    # 2) permission-config hit lines (config files named in the declaration)
    routes = _new_routes(repo, base, branch)
    hits: list[str] = []
    if routes:
        lines += ["## 本分支新增接口路由", *[f"- {rt}" for rt in routes], ""]
        for root_name in decl["config_files"][:5]:
            for cfg in ext.rglob(root_name):
                if not cfg.is_file():
                    continue
                try:
                    cfg_text = _read_text(cfg)
                except OSError:
                    continue
                rel = str(cfg.relative_to(ext))
                for i, ln in enumerate(cfg_text.splitlines(), 1):
                    for rt in routes:
                        if rt and rt in ln:
                            hits.append(f"{rel}:{i}: {ln.strip()[:200]}")
        lines += ["## 权限配置命中(buttonAuth.properties 类)"]
        lines += ([f"- {h}" for h in hits[:200]] or ["- (无命中)"])
        lines.append("")

    # 3) route occurrence counts across the external repo's text files
    counts: list[str] = []
    if routes:
        text_exts = (".js", ".vue", ".ts", ".jsx", ".tsx", ".html", ".json")
        skip_dirs = {".git", "node_modules", "dist", "build"}
        occurrence: dict[str, list[str]] = {rt: [] for rt in routes}
        for p in ext.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in text_exts:
                continue
            if any(part in skip_dirs for part in p.parts):
                continue
            try:
                txt = _read_text(p)
            except OSError:
                continue
            rel = str(p.relative_to(ext))
            for rt in routes:
                if rt and rt in txt:
                    occurrence[rt].append(rel)
        for rt, locs in occurrence.items():
            counts.append(f"- {rt}: {len(locs)} 处" +
                          (f" ({', '.join(locs[:10])})" if locs else ""))
        lines += ["## 新增路由在前端的出现计数", *counts, ""]

    lines += ["", "检索时点快照:结论反映本次检索时刻的外部仓状态,不保证前端分支已同步。"]
    body = "\n".join(lines)
    raw = body.encode("utf-8")
    truncated = False
    if len(raw) > budget:
        body = body.encode("utf-8")[:budget].decode("utf-8", "ignore") + \
            "\n\n[截断: 超出逐仓字节预算]\n"
        truncated = True
    (out_dir / "hits.md").write_text(body, encoding="utf-8")

    record = {
        "path": str(ext),
        "slug": slug,
        "branch_sync_note": ("同名分支" if not branch_fallback
                             else f"同名分支缺失,回退默认分支 {target_branch}"),
        "branch_fallback": branch_fallback,
        "summary_path": str((out_dir / "hits.md").resolve()),
        "diff_files": len(file_list),
        "route_hits": len(hits),
        "bytes": min(len(raw), budget),
        "truncated": truncated,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return record


# --- (c) sensitive catalog ----------------------------------------------------

def _resolve_sensitive_catalog(repo: Path):
    """(resolved_catalog_or_None, source, violations). Reuses the sibling sensitive_catalog
    module for parsing/validation in BOTH branches (closed-set single source)."""
    import sensitive_catalog
    project = repo / ".mgh-sra" / "sensitive_catalog.json"
    if project.is_file():
        try:
            catalog = sensitive_catalog.resolve(f"@{project}")
            return catalog, "project", []
        except sensitive_catalog.CatalogInputError as e:
            return None, "project", [f"project catalog unreadable: {e}"]
        except sensitive_catalog.CatalogViolation as v:
            return None, "project", list(v.messages)
    example = Path(__file__).resolve().parent / "sensitive_catalog.json.example"
    if not example.is_file():
        return None, "default-template", [f"default template missing: {example}"]
    try:
        catalog = sensitive_catalog.resolve(f"@{example}")
        return catalog, "default-template", []
    except (sensitive_catalog.CatalogInputError, sensitive_catalog.CatalogViolation) as e:
        msgs = list(e.messages) if isinstance(e, sensitive_catalog.CatalogViolation) else [str(e)]
        return None, "default-template", msgs


# --- main ---------------------------------------------------------------------

def _run(args) -> dict:
    repo = Path(args.repo)
    if not repo.is_dir():
        _eprint(f"error: --repo not a directory: {repo}")
        sys.exit(1)
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    repo = repo.resolve()
    run_dir = run_dir.resolve()
    base = args.base
    branch = args.branch or _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    # design sources: declarations + baseline share the same deterministic read set
    texts: list[str] = []
    for name in _DECLARATION_SOURCES:
        p = repo / name
        if p.is_file():
            texts.append(_read_text(p))
    controls = repo / _CONTROLS_DIR
    if controls.is_dir():
        for p in sorted(controls.glob("*.md")):
            texts.append(_read_text(p))

    # (a) baseline
    baseline, truncated, trunc_bytes = _project_baseline(repo, args.baseline_budget_bytes)
    baseline_path = run_dir / "baseline.md"
    baseline_path.write_text(baseline, encoding="utf-8")

    # (b) external repos
    external: list[dict] = []
    skipped: list[str] = []
    if not args.no_external:
        decls, not_found = _parse_declarations(texts)
        skipped.extend(not_found)
        for decl in decls:
            rec = _external_retrieve(decl, repo, base, branch,
                                     args.external_budget_bytes, run_dir)
            if rec is None:
                skipped.append(f"unreachable-or-not-git: {decl['path']}")
                continue
            external.append(rec)
        # explicit --read-root additions are the operator's confirmation (sdr minimalism:
        # only roots that went through retrieval OR explicit operator confirmation land
        # in read_roots)
        for rr in args.read_root or []:
            rp = Path(rr).resolve()
            if rp.is_dir() and not any(e["path"] == str(rp) for e in external):
                external.append({"path": str(rp), "slug": _safe_slug(rp.name),
                                 "branch_sync_note": "operator-declared (no retrieval)",
                                 "branch_fallback": False, "summary_path": "",
                                 "diff_files": 0, "route_hits": 0, "bytes": 0,
                                 "truncated": False})
    else:
        skipped.append("disabled: --no-external")

    # (c) sensitive catalog
    catalog, source, violations = _resolve_sensitive_catalog(repo)
    if violations:
        _eprint("error: sensitive catalog resolution failed (closed-set/shape violation; "
                "fail-loud BEFORE any LLM token):")
        for v in violations:
            _eprint(f"  - {v}")
        _eprint("recipe: fix <repo>/.mgh-sra/sensitive_catalog.json (validate with "
                "`py sensitive_catalog.py --check @<file>`) — the sdr run MUST NOT "
                "proceed with a broken catalog.")
        sys.exit(2)

    result = {
        "repo": str(repo),
        "run_dir": str(run_dir),
        "base": base,
        "branch": branch,
        "baseline_path": str(baseline_path.resolve()),
        "baseline_bytes": baseline_path.stat().st_size,
        "baseline_truncated": truncated,
        "baseline_truncated_bytes": trunc_bytes,
        "sensitive_catalog": catalog,
        "sensitive_catalog_source": source,
        "external_repos": external,
        "external_skipped": skipped,
    }
    (run_dir / "context.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    _eprint(f"[sdr_context] baseline={result['baseline_bytes']}B truncated={truncated}; "
            f"external={len(external)} repo(s) skipped={skipped or 'none'}; "
            f"sensitive_catalog_source={source}")
    return result


def _check(run_dir: Path) -> int:
    violations = []
    ctx_path = run_dir / "context.json"
    if not ctx_path.is_file():
        _eprint(f"error: context.json not found in run dir: {run_dir}\n"
                f"recipe: run `sdr_context.py --repo <abs> --run-dir <abs>` first.")
        return 2
    try:
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _eprint(f"error: malformed context.json: {e}")
        return 2
    bp = ctx.get("baseline_path", "")
    if not bp or not Path(bp).is_file():
        violations.append(f"baseline missing: {bp!r}")
    elif ctx.get("baseline_bytes", 0) > DEFAULT_BASELINE_BUDGET * 4:
        violations.append(f"baseline unexpectedly huge: {ctx.get('baseline_bytes')}B")
    for e in ctx.get("external_repos", []):
        sp = e.get("summary_path", "")
        if sp and not Path(sp).is_file():
            violations.append(f"external summary missing for {e.get('slug')}: {sp}")
        if not Path(e.get("path", "")).is_dir():
            violations.append(f"external root missing: {e.get('path')}")
    cat = ctx.get("sensitive_catalog")
    if cat is not None:
        try:
            import sensitive_catalog
            v = sensitive_catalog.validate_resolved(cat)
            violations.extend(v)
        except Exception as ex:  # noqa: BLE001 — any import/shape failure is a violation
            violations.append(f"sensitive_catalog shape invalid: {ex}")
    if ctx.get("sensitive_catalog_source") not in ("project", "default-template"):
        violations.append(f"sensitive_catalog_source invalid: "
                          f"{ctx.get('sensitive_catalog_source')!r}")
    if violations:
        _eprint(f"error: sdr_context --check: {len(violations)} violation(s):")
        for v in violations:
            _eprint(f"  - {v}")
        _eprint("recipe: re-run `sdr_context.py --repo <abs> --run-dir <abs>` "
                "(idempotent, deterministic).")
        return 2
    _eprint(f"[sdr_context] --check ok ({run_dir})")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="deterministic baseline projection + external-repo controlled "
                    "retrieval for /mgh-sdr (runs in the orchestrator main flow, never "
                    "in a subagent)")
    ap.add_argument("--repo", help="absolute target git repo root")
    ap.add_argument("--run-dir", help="absolute run dir (<repo>/.mgh-sdr/runs/<ts>)")
    ap.add_argument("--base", default="master", help="base ref (default master)")
    ap.add_argument("--branch", default="", help="branch ref (default: current branch)")
    ap.add_argument("--dimensions", metavar="<inline-json|@path>",
                    help="dimension set (closed-set keys + free-text extensions); "
                         "narrowing discloses in manifest; default = all 6")
    ap.add_argument("--baseline-budget-bytes", type=int, default=DEFAULT_BASELINE_BUDGET,
                    help=f"baseline projection byte cap (default {DEFAULT_BASELINE_BUDGET})")
    ap.add_argument("--external-budget-bytes", type=int, default=DEFAULT_EXTERNAL_BUDGET,
                    help=f"per-external-repo conclusion byte cap (default "
                         f"{DEFAULT_EXTERNAL_BUDGET})")
    ap.add_argument("--read-root", action="append", metavar="<abs>",
                    help="extra confirmed read-only root for the sentinel read_roots[] "
                         "(repeatable; only explicitly confirmed roots)")
    ap.add_argument("--no-external", action="store_true",
                    help="skip external-repo retrieval entirely")
    ap.add_argument("--check", metavar="<run-dir>",
                    help="validate a run dir's context artifacts (fail-loud exit 2)")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.check:
        if args.repo or args.run_dir:
            _eprint("error: --check takes only <run-dir>")
            return 2
        return _check(Path(args.check).resolve())
    if not args.repo or not args.run_dir:
        _eprint("error: --repo and --run-dir are required (or use --check <run-dir>)")
        return 2
    if args.baseline_budget_bytes <= 0 or args.external_budget_bytes <= 0:
        _eprint("error: budgets must be > 0")
        return 2
    if args.dimensions:
        spec = args.dimensions
        raw = None
        try:
            if spec.startswith("{"):
                raw = json.loads(spec)
            elif spec == "-":
                import json as _j
                raw = _j.loads(sys.stdin.read())
            else:
                p = Path(spec[1:] if spec.startswith("@") else spec)
                raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            _eprint(f"error: --dimensions unparsable: {e}")
            return 2
        dims = (raw or {}).get("dimensions") if isinstance(raw, dict) else None
        if not isinstance(dims, list) or not dims:
            _eprint("error: --dimensions must be {\"dimensions\": [\"...\", ...]} "
                    "(non-empty)")
            return 2
        closed = {"vertical-authz", "horizontal-authz", "other-authz", "sql-injection",
                  "sensitive-data", "input-validation"}
        unknown = [d for d in dims
                   if not isinstance(d, str) or not re.match(r"^[a-z0-9-]+$", d)]
        if unknown:
            _eprint(f"error: --dimensions illegal keys: {unknown}; closed set: "
                    f"{sorted(closed)}; other keys are free-text check items (kebab-case)")
            return 2

    result = _run(args)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
