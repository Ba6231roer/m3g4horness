#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
render_sdr_report — deterministic summary renderer for /mgh-sdr: collect the fan-out
units' draft JSONs (.done + parseable), dedup-merge findings by {dimension, route, file},
and render the human-facing Simplified-Chinese md report at the project root plus
`sdr_manifest.json` in the run dir. The report is the ONE artifact a human consumes
(daily / pre-merge trigger); all machine artifacts stay in the run dir.

Findings merge: same {dimension, route, file} triple => ONE entry (line_hint union;
risk/suggestion/control_ref from the first occurrence — duplicates across units carry no
new information). `.failed` units do NOT block rendering: they are counted in
`counts.failed_units` + listed in `failed_units[]` (unit id + reason), and the report's
honesty-boundary section discloses "N review units failed; their coverage is unreviewed".
An unparsable draft of a .done unit takes the same path (failed_units, not a crash).

Report name: `mgh-sdr-<branch-safe>-<YYYYMMDD_HHMMSS>.md` at --repo root (tool name
fixed `mgh-sdr`; branch name filesystem-safe; second-resolution local timestamp). A same-
name report (re-run within the same second) is ATOMICALLY overwritten (idempotent);
across seconds both reports coexist (history is the user's to manage).

NEVER writes into `openspec/`, NEVER writes anything in the target repo except the
report file itself, NEVER writes outside --out-dir + the report.

Honesty boundary (>= 6 entries, always):
  1. findings are LLM candidates needing human review, not confirmed vulnerabilities;
  2. interface grouping is an annotation heuristic — an unrecognized interface/chain
     falls into a directory-clustered unit (coarser granularity, coverage not lost);
  3. cited existing controls assert EXISTENCE, not effectiveness;
  4. external-repo conclusions are a retrieval-moment snapshot (frontend branch sync not
     guaranteed);
  5. the baseline is a byte-budgeted projection — low-priority design details may be
     missing;
  6. the sensitive-catalog source and coverage (fields outside the catalog are only
     recognized by the fallback rule) + failed units (their coverage is unreviewed);
  7. exclusion-set disclosure — N files excluded by the closed set (test trees/build
     outputs/static assets/lockfiles/build scripts, counted per reason), NOT reviewed;
     --include-excluded is the fallback.
plus a failed-units entry when failed_units[] is non-empty, a dimensions-narrowed
entry when the run used fewer than the default 6, and an external-repo-UNAPPROVED
entry when declared repos were skipped for lack of project-config authorization
(`unapproved:` skips — kept distinct from `not-found` unreachable degradations).

Grouping overview (report head): interface/standalone unit counts, codegraph on/off +
capture stats (route anchors / upstream anchors / chain merges / edges), exclusion
counts — grouping quality is observable without opening grouping.json. The stats ride
grouping.json in the run dir (older layouts: the section is simply absent).

Exit codes (R5.3b): 0 ok · 1 input error (run dir/drafts missing) · 2 misuse (argparse)
or --check violation (manifest/draft/counts inconsistency; R5.9).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/re/sys/pathlib).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

TOOL_NAME = "mgh-sdr"

# Default closed-set dimension keys (the report groups by whatever the drafts actually
# carry; free-text extension dimensions render under their own name).
DEFAULT_DIMENSIONS = ["vertical-authz", "horizontal-authz", "other-authz",
                      "sql-injection", "sensitive-data", "input-validation"]
_DIMENSION_LABEL = {
    "vertical-authz": "垂直越权",
    "horizontal-authz": "横向越权",
    "other-authz": "其他权限问题",
    "sql-injection": "SQL 注入",
    "sensitive-data": "敏感信息屏蔽",
    "input-validation": "输入校验",
}
_SEVERITY_LABEL = {"high": "高", "medium": "中", "low": "低", "info": "提示"}
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}

_DIMENSION_COL = {
    "vertical-authz": "垂直越权",
    "horizontal-authz": "横向越权",
    "other-authz": "其他权限",
    "sql-injection": "SQL注入",
    "sensitive-data": "敏感屏蔽",
    "input-validation": "输入校验",
}


def _dim_col(d: str) -> str:
    return _DIMENSION_COL.get(d, d)


def _eprint(*a):
    print(*a, file=sys.stderr)


def _safe_name(s: str) -> str:
    return re.sub(r"[/\\:*?\"<>|]", "_", s).strip("_") or "branch"


def _load_drafts(run_dir: Path):
    """(drafts, failed_units). A unit counts as done iff its .done marker exists in
    markers/; a failed unit = .failed marker present (reason read from the marker body
    when parsable) OR a .done unit whose draft is missing/unparsable."""
    markers = run_dir / "markers"
    drafts_dir = run_dir / "drafts"
    drafts, failed = [], []
    done_ids, failed_ids = set(), {}
    if markers.is_dir():
        for p in sorted(markers.glob("*.done")):
            done_ids.add(p.name[:-len(".done")])
        for p in sorted(markers.glob("*.failed")):
            uid = p.name[:-len(".failed")]
            try:
                body = json.loads(p.read_text(encoding="utf-8"))
                reason = body.get("reason") or "unknown"
            except (OSError, ValueError, AttributeError):
                reason = "unknown"
            failed_ids[uid] = reason
    for uid in sorted(done_ids):
        dp = drafts_dir / f"{uid}.json"
        try:
            draft = json.loads(dp.read_text(encoding="utf-8"))
            if not isinstance(draft, dict):
                raise ValueError("draft not an object")
        except (OSError, ValueError) as e:
            failed.append({"unit": uid, "reason": f"draft unparsable: {e}"})
            continue
        findings = draft.get("findings", [])
        if not isinstance(findings, list):
            failed.append({"unit": uid, "reason": "findings field not a list"})
            continue
        drafts.append({"unit": uid, "findings": findings})
    for uid, reason in sorted(failed_ids.items()):
        failed.append({"unit": uid, "reason": reason})
    return drafts, failed


def _merge_findings(drafts: list) -> dict:
    """Dedup-merge by {dimension, route, file}; line_hint union; first-writer-wins for
    the text fields. Returns {dimension: [finding...]} severity-sorted."""
    merged: dict[tuple, dict] = {}
    for d in drafts:
        for f in d["findings"]:
            if not isinstance(f, dict):
                continue
            key = (str(f.get("dimension", "")), str(f.get("route", "")),
                   str(f.get("file", "")))
            hint = str(f.get("line_hint", "") or "")
            if key in merged:
                prev = merged[key]
                if hint and hint not in prev["line_hint"]:
                    prev["line_hint"] = ", ".join(x for x in (prev["line_hint"], hint) if x)
                continue
            merged[key] = {
                "dimension": key[0], "route": key[1], "file": key[2],
                "severity": f.get("severity") if f.get("severity") in _SEVERITY_ORDER else "medium",
                "line_hint": hint,
                # anchor line (int, optional; old drafts lack it — degrade to file only)
                "line": f.get("line") if isinstance(f.get("line"), int)
                        and not isinstance(f.get("line"), bool) else None,
                "risk": str(f.get("risk", "") or ""),
                "suggestion": str(f.get("suggestion", "") or ""),
                "control_ref": f.get("control_ref"),
            }
    by_dim: dict[str, list] = {}
    for (dim, _r, _f), rec in merged.items():
        by_dim.setdefault(dim, []).append(rec)
    for lst in by_dim.values():
        lst.sort(key=lambda r: (_SEVERITY_ORDER.get(r["severity"], 9), r["route"], r["file"]))
    return by_dim


def _render_chain(chain: list) -> str:
    """chain[] -> abbreviated one-cell chain text (Plan C): `·` same-class continuation,
    `⤷` branch (branch_of host), `⇢` mapper XML terminal, `†` unchanged node. A linear
    chain reads as A → B → C → ⇢terminal; branch nodes are appended flat after the main
    line. Returns "" for an empty/absent chain (the row falls back to the entry form)."""
    if not chain:
        return ""
    # main line = nodes without branch_of, in array order; branch subtrees = nodes with
    # branch_of, rendered right after the main line in array order (fan-out never nests:
    # branch_of always points at a main-line index — asserted by diff_group --check)
    main = [(i, n) for i, n in enumerate(chain) if n.get("branch_of") is None]
    branches = [(i, n) for i, n in enumerate(chain) if n.get("branch_of") is not None]
    parts: list[str] = []
    prev_class = None
    for pos, (i, n) in enumerate(main):
        if pos == 0:
            parts.append(_node_text(n))
        elif n.get("change") == "external":
            parts.append(" ⇢" + _node_text(n))   # mapper XML terminal (XML not a graph node)
        elif n.get("file") and n.get("file") == prev_class:
            parts.append(" ·" + _node_text(n))   # same-class continuation
        else:
            parts.append(" → " + _node_text(n))
        prev_class = n.get("file")
    for _i, n in branches:
        sep = " ⇢" if n.get("change") == "external" else " ⤷"
        parts.append(sep + _node_text(n))
    return "".join(parts)


def _node_text(n: dict) -> str:
    txt = str(n.get("fqn_short", ""))
    if n.get("change") == "unchanged":
        txt = "†" + txt
    return txt


def _mermaid_chain(unit_id: str, route: str, chain: list) -> str:
    """One mermaid flowchart LR per BRANCHED unit (章节三): entry → nodes → dashed
    mapper-terminal edges. branch_of = the edge's source host; mapper terminals (change
    == "external") get dashed edges. Linear chains never reach here (caller filters)."""
    ids: list[str] = []
    for i, n in enumerate(chain):
        base = re.sub(r"[^A-Za-z0-9]", "", str(n.get("fqn_short", ""))) or f"n{i}"
        ids.append(f"n{i}{base[:24]}")
    lines = ["```mermaid", "flowchart LR"]
    for i, n in enumerate(chain):
        label = str(n.get("label") or n.get("fqn_short", "")).replace('"', "'")
        if n.get("change") == "external":
            # mapper XML terminal: declared + dashed edge FROM its host node
            host = n.get("branch_of") if isinstance(n.get("branch_of"), int) else i - 1
            if isinstance(host, int) and 0 <= host < len(chain):
                lines.append(f'  {ids[host]} -.-> {ids[i]}["{label}"]')
            else:
                lines.append(f'  {ids[i]}["{label}"]')
            continue
        if i == 0:
            prefix = str(n.get("route") or route or "")
            head = f'{prefix} ' if prefix else ""
            lines.append(f'  {ids[i]}["{head}{label}"]')
            continue
        bo = n.get("branch_of")
        src = ids[bo] if isinstance(bo, int) and 0 <= bo < len(chain) else ids[i - 1]
        lines.append(f'  {src} --> {ids[i]}["{label}"]')
    lines.append("```")
    return "\n".join(lines)


def _sorted_units(units: list) -> list:
    """简报表 row order: interface by route asc (first route for merged units),
    standalone after by unit_id."""
    def key(u):
        routes = [r for r in str(u.get("route", "")).split(";") if r]
        return (0 if u.get("kind") == "interface" else 1,
                routes[0] if routes else "￿",
                str(u.get("unit_id", "")))
    return sorted(units, key=key)


def _frontend_pair(route: str, exts: list) -> tuple[str, str]:
    """(是否前端接口, 前端使用) three-state by route join over route_hits[]:
    declared ∧ count>0 = 是/N 处; declared ∧ 0 = 否/—; route not in any route_hits[]
    (or no declared repo) = 未知/—. Multi-route units join on the MAIN route only
    (first ';'-segment, per spec; the entry column shows the others as `(+N)`)."""
    main = str(route).split(";")[0]
    if not main or not exts:
        return "未知", "—"
    found = False
    best = 0
    for e in exts:
        for rh in e.get("route_hits") or []:
            if not isinstance(rh, dict):
                continue
            rt = rh.get("route", "")
            if rt and rt in main:
                found = True
                best = max(best, rh.get("count", 0) or 0)
    if not found:
        return "未知", "—"
    if best > 0:
        return "是", f"{best} 处"
    return "否", "—"


def _row_dimensions(dims, rows) -> list:
    """Column set for the 简报表: default closed-set order first, then any free-text
    extension dimension found in the run face (each extension gets one column)."""
    seen = {d for r in rows for d in r["dim_refs"]}
    return [d for d in DEFAULT_DIMENSIONS if d in dims or d in seen] + \
        sorted(d for d in seen if d not in DEFAULT_DIMENSIONS and d in dims) + \
        sorted(d for d in seen if d not in DEFAULT_DIMENSIONS and d not in dims)


def _build_rows(g_units: list, by_dim: dict, pnums: dict, unit_refs: dict,
                external: list) -> list[dict]:
    """简报表 data rows from grouping.json units[] (the renderer's row truth). Failed
    units NEVER become rows (their coverage is unreviewed — the honesty boundary
    discloses them instead)."""
    rows = []
    for u in _sorted_units(g_units):
        if u.get("status") == "failed":
            continue
        routes = [r for r in str(u.get("route", "")).split(";") if r]
        chain = u.get("chain") or []
        chain_txt = _render_chain(chain)
        if routes:
            entry = routes[0] if len(routes) == 1 else routes[0] + f"(+{len(routes) - 1})"
            if not chain_txt:
                chain_txt = entry
        else:
            entry = _standalone_entry(u)
            if not chain_txt:
                chain_txt = entry
        refs = unit_refs.get(u.get("unit_id", ""), set())
        dim_refs: dict[str, set] = {}
        for ref in refs:
            for dim, lst in by_dim.items():
                if any(f["pnum"] == ref for f in lst):
                    dim_refs.setdefault(dim, set()).add(ref)
        rows.append({
            "unit_id": u.get("unit_id", ""),
            "kind": u.get("kind", ""),
            "entry": entry,
            "chain": chain_txt,
            "frontend_is": "—",
            "frontend_count": "—",
            "dim_refs": dim_refs,
            "all_refs": refs,
        })
    # frontend two columns need the row route: fill after rows exist
    for r, u in zip(rows, _sorted_units(g_units)):
        fis, fcnt = _frontend_pair(str(u.get("route", "")), external)
        r["frontend_is"], r["frontend_count"] = fis, fcnt
    return rows


def _standalone_entry(u: dict) -> str:
    """Entry cell for a no-route unit: the unit's own method-def short form (first chain
    node, else the unit_id stem)."""
    chain = u.get("chain") or []
    if chain:
        return _node_text(chain[0])
    return str(u.get("unit_id", ""))


def _boundaries(by_dim, failed, catalog_source, external, dims, baseline_truncated,
                excluded=None, skipped=None):
    sk = [s for s in (skipped or []) if isinstance(s, str)]
    unapproved = [s[len("unapproved: "):].strip() for s in sk
                  if s.startswith("unapproved: ")]
    b = [
        "发现是 LLM 生成的待复核候选,不是已确认漏洞;每次运行非确定性,需人工复核后再处置。",
        "接口分组是注解启发式(Spring/JAX-RS/Servlet 常用注解):未识别的接口或调用链退入"
        "目录聚簇单元(分析粒度粗但覆盖不丢);非 java web 项目整体退化为目录聚簇模式。",
        "引用存量安全控制仅断言其「存在」,不断言其「有效」;控制有效性须另行验证。",
        "外部仓结论是检索时点快照,不保证前端分支已同步;同名分支缺失时回退其默认分支检索。",
        "检查基线经字节预算投影(优先级:接口授权 > SQL > 输入校验 > 敏感数据),低优先级维度的"
        "存量设计细节可能未全量投影。",
        f"敏感目录来源:{catalog_source}("
        + ("项目目录复用" if catalog_source == "project"
           else "默认模板回退:与 sra/srr 的显式行为分歧,复核域回退 37 项模板,不收窄到 6 facet")
        + ");目录外字段仅按回退规则识别,非穷尽所有敏感字段。",
    ]
    if excluded and excluded.get("count"):
        by_reason = excluded.get("by_reason") or {}
        detail = "、".join(f"{k} {v}" for k, v in sorted(by_reason.items())) or "-"
        b.append(f"排除集披露:本次运行按闭集排除了 {excluded['count']} 个文件(测试树/构建产物/"
                 f"静态资源/锁文件/构建脚本;{detail}),它们未进入评审;如需全量评审可用 "
                 f"--include-excluded 兜底重跑。")
    if dims and sorted(dims) != sorted(DEFAULT_DIMENSIONS):
        b.append(f"本次检查面经参数化收窄为 {len(dims)} 个维度({', '.join(dims)}),"
                 f"范围外维度未覆盖。")
    if failed:
        b.append(f"{len(failed)} 个评审单元失败({'、'.join(u['unit'] for u in failed[:5])}"
                 f"{'…' if len(failed) > 5 else ''}),其覆盖范围本次未复核;建议重跑补齐。")
    if baseline_truncated:
        b.append("基线投影发生截断(超字节预算),部分存量设计段落未进入检查基线。")
    if external:
        b.append(f"外部仓检索覆盖 {len(external)} 个声明仓;未声明/不可达的外部仓不在本次检查面内。")
    if unapproved:
        shown = "、".join(unapproved[:3]) + ("…" if len(unapproved) > 3 else "")
        b.append(f"外部仓未授权:存量设计声明了 {len(unapproved)} 个外部目录({shown}),"
                 f"未经用户确认写入项目配置,本次未检索;前端相关检查面未覆盖,经用户确认后"
                 f"重跑可覆盖。")
    return b


def _load_grouping(run_dir: Path) -> dict:
    """grouping.json (diff_group run record) when present — carries the grouping
    stats the report's overview section discloses. Missing/old layout -> {}."""
    gp = run_dir / "grouping.json"
    try:
        g = json.loads(gp.read_text(encoding="utf-8"))
        return g if isinstance(g, dict) else {}
    except (OSError, ValueError):
        return {}


def _render(repo: Path, run_dir: Path, ctx: dict, by_dim: dict, drafts, failed,
            out_dir: Path | None):
    branch = ctx.get("branch", "")
    base = ctx.get("base", "")
    dims = ctx.get("dimensions") or DEFAULT_DIMENSIONS
    catalog_source = ctx.get("sensitive_catalog_source", "default-template")
    external = ctx.get("external_repos", [])
    skipped = [s for s in ctx.get("external_skipped", []) if isinstance(s, str)]
    unapproved = [s[len("unapproved: "):].strip() for s in skipped
                  if s.startswith("unapproved: ")]
    now = datetime.now().astimezone()
    ts = now.strftime("%Y%m%d_%H%M%S")
    report_path = repo / f"{TOOL_NAME}-{_safe_name(branch)}-{ts}.md"

    total = sum(len(v) for v in by_dim.values())
    by_sev = {"high": 0, "medium": 0, "low": 0, "info": 0}
    for lst in by_dim.values():
        for f in lst:
            by_sev[f["severity"]] += 1
    ok_units = [d["unit"] for d in drafts if not d["findings"]]
    grouping = _load_grouping(run_dir)
    excluded = grouping.get("excluded") or ctx.get("excluded") or {}
    cg_stats = grouping.get("codegraph_stats") or ctx.get("codegraph_stats") or {}

    # P-NN global numbering: severity asc (high→info), then (route, file) for a
    # deterministic order that is stable across runs.
    flat: list[dict] = []
    for dim_list in by_dim.values():
        flat.extend(dim_list)
    flat.sort(key=lambda f: (_SEVERITY_ORDER.get(f["severity"], 9), f["route"], f["file"]))
    pnums: dict[tuple, str] = {}
    for i, f in enumerate(flat, 1):
        pnums[(f["dimension"], f["route"], f["file"])] = f"P-{i:02d}"
        f["pnum"] = f"P-{i:02d}"
    # unit -> its finding refs (a unit "owns" a finding when a draft with that unit id
    # carried the same triple; shared triples = shared P-NN across rows, by design)
    unit_refs: dict[str, set] = {}
    for d in drafts:
        for f in d["findings"]:
            if not isinstance(f, dict):
                continue
            key = (str(f.get("dimension", "")), str(f.get("route", "")),
                   str(f.get("file", "")))
            if key in pnums:
                unit_refs.setdefault(d["unit"], set()).add(pnums[key])

    # ---- report body ----------------------------------------------------------
    L: list[str] = []
    L.append(f"# {TOOL_NAME} 安全设计符合性复核报告")
    L.append("")
    L.append(f"- 分支:`{branch}`(base:`{base}`)")
    L.append(f"- 时间:{now.strftime('%Y-%m-%d %H:%M:%S %z')}")
    L.append(f"- 检查面:{', '.join(dims)}")
    L.append(f"- 敏感目录来源:{catalog_source}"
             + ("(项目目录复用)" if catalog_source == "project"
                else "(默认模板回退:PIPL/GB-T 35273 37 项;与 sra/srr 的显式行为分歧)"))
    if external:
        L.append(f"- 外部仓结论:{', '.join(e.get('slug', '?') for e in external)}"
                 f"({len(external)} 仓,检索时点快照)")
    elif unapproved:
        L.append(f"- 外部仓结论:无(外部仓未授权,前端相关检查面未覆盖)")
    else:
        L.append("- 外部仓结论:无(未声明 / 不可达降级,前端相关检查面未覆盖)")
    L.append(f"- 单元:{len(drafts) + len(failed)} 个(done {len(drafts)} / failed "
             f"{len(failed)});findings 去重后 {total} 条"
             f"(高 {by_sev['high']} / 中 {by_sev['medium']} / 低 {by_sev['low']} / "
             f"提示 {by_sev['info']})")

    # 分组概览:unit counts + anchoring/merge summary + exclusion counts (grouping
    # quality at a glance — was previously unobservable from the report alone).
    g_counts = grouping.get("counts") or {}
    if g_counts or excluded or cg_stats:
        L.append("")
        L.append("## 分组概览")
        L.append("")
        if g_counts:
            L.append(f"- 单元数:interface {g_counts.get('interface', 0)} / "
                     f"standalone {g_counts.get('standalone', 0)}"
                     f"(total {grouping.get('total', '?')})")
        if cg_stats:
            L.append(f"- codegraph:{'on' if grouping.get('codegraph') else 'off'}"
                     f"(路由锚 {cg_stats.get('anchors_changed', 0)}、向上锚定 "
                     f"{cg_stats.get('anchors_upstream', 0)}、链合并 "
                     f"{cg_stats.get('chain_merged', 0)}、捕获调用边 "
                     f"{cg_stats.get('edges_captured', 0)}、变更集内边 "
                     f"{cg_stats.get('edges_in_changed_set', 0)})")
        if excluded.get("count"):
            detail = "、".join(f"{k} {v}" for k, v in sorted((excluded.get("by_reason")
                                                              or {}).items()))
            L.append(f"- 排除文件:{excluded['count']} 个"
                     + (f"({detail})" if detail else "")
                     + "(未进入评审,详见诚实边界)")
    L.append("")
    L.append("> **发现是 LLM 生成的待复核候选,不是已确认漏洞。** 合并/处置前须人工复核。")
    L.append("")

    # ---- 章节一 简报表 ---------------------------------------------------------
    g_units = grouping.get("units")
    rows: list[dict] = []
    if g_units:
        rows = _build_rows(g_units, by_dim, pnums, unit_refs, external)
    L.append("## 章节一 简报表")
    L.append("")
    if rows:
        cols = ["接口/方法入口", "调用链", "是否前端接口", "前端使用"] + \
               [_dim_col(d) for d in _row_dimensions(dims, rows)]
        L.append("| " + " | ".join(cols) + " |")
        L.append("| " + " | ".join(["---"] * len(cols)) + " |")
        for r in rows:
            cells = [r["entry"].replace("|", "\\|"), r["chain"].replace("|", "\\|"),
                     r["frontend_is"].replace("|", "\\|"),
                     r["frontend_count"].replace("|", "\\|")]
            for d in _row_dimensions(dims, rows):
                refs = r["dim_refs"].get(d)
                cells.append(("是 [" + ", ".join(sorted(refs)) + "]") if refs else "否")
            L.append("| " + " | ".join(cells) + " |")
        L.append("")
        L.append("> 阅读方式:维度列只标 是/否 + `P-NN` 编号(纯文本,无内部锚点);"
                 "编号详情统一看「章节二 问题详述」。`†` 未变更节点 · `⤷` 分支 · "
                 "`⇢` mapper XML 终端 · `·` 同类延续。")
        L.append("")
    else:
        L.append("(无 grouping.json 单元数据:旧 run 布局,仅问题详述可用)")
        L.append("")

    # ---- 章节二 问题详述 -------------------------------------------------------
    L.append("## 章节二 问题详述")
    L.append("")
    if not flat:
        L.append("本次检查面内未产出任何问题记录;不代表「无风险」,仅代表本次检查面 + 基线"
                 "投影下未命中。")
        L.append("")
    else:
        for f in flat:   # flat is already severity-asc then route/file = P-NN order
            label = _DIMENSION_LABEL.get(f["dimension"], f["dimension"])
            L.append(f"### {f['pnum']} · {label} · "
                     f"{f['route'] or '(独立变更单元)'} · "
                     f"{_SEVERITY_LABEL.get(f['severity'], f['severity'])}")
            loc = f"`{f['file']}`"
            if f.get("line"):
                loc += f":{f['line']}"
            elif f.get("line_hint"):
                loc += f"({f['line_hint']})"
            L.append(f"- 位置:{loc}")
            if f["risk"]:
                L.append(f"- 风险:{f['risk']}")
            if f["suggestion"]:
                L.append(f"- 建议:{f['suggestion']}")
            if f["control_ref"]:
                L.append(f"- 命中存量控制:{f['control_ref']}")
            L.append("")

    # ---- 章节三 分支调用链图 ----------------------------------------------------
    # 真实分支 = a non-external node carries branch_of (a java fan-out). branch_of on
    # an `external` mapper-terminal node is D3 encoding, NOT a branch — a linear chain
    # whose only branch_of is its ⇢ terminal stays in 章节一 and draws NO diagram.
    branch_units = [u for u in g_units or []
                    if any(n.get("branch_of") is not None
                           and n.get("change") != "external"
                           for n in (u.get("chain") or []))]
    L.append("## 章节三 分支调用链图")
    L.append("")
    if not branch_units:
        L.append("(无带分支的单元:线性链不画图)")
        L.append("")
    else:
        for u in branch_units:
            routes = str(u.get("route", "")).split(";")
            L.append(f"#### {u.get('unit_id')} · {routes[0]}")
            L.append("")
            L.append(_mermaid_chain(u.get("unit_id"), routes[0], u.get("chain") or []))
            L.append("")

    L.append("## 无问题单元")
    L.append("")
    if ok_units:
        for u in ok_units:
            L.append(f"- `{u}`(复核通过,merge 前放行参考)")
    else:
        L.append("- (无:全部单元均产出问题记录或失败)")
    L.append("")

    L.append("## 诚实边界")
    L.append("")
    for b in _boundaries(by_dim, failed, catalog_source, external, dims,
                         ctx.get("baseline_truncated", False), excluded, skipped):
        L.append(f"- {b}")
    L.append("")

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / (report_path.name + ".tmp")
    tmp.write_text("\n".join(L) + "\n", encoding="utf-8")

    manifest_rows = [{
        "unit_id": r["unit_id"], "entry": r["entry"], "chain": r["chain"],
        "frontend_is": r["frontend_is"], "frontend_count": r["frontend_count"],
        "issue_refs": sorted(r["all_refs"]),
    } for r in rows]

    manifest = {
        "tool": TOOL_NAME,
        "branch": branch,
        "base": base,
        "dimensions": dims,
        "sensitive_catalog_source": catalog_source,
        "external_repos": [{"slug": e.get("slug"), "path": e.get("path"),
                            "branch_sync_note": e.get("branch_sync_note")}
                           for e in external],
        "rows": manifest_rows,
        "counts": {
            "units": len(drafts) + len(failed),
            "interfaces": ctx.get("counts_interface", None),
            "standalone": ctx.get("counts_standalone", None),
            "findings": total,
            "findings_by_severity": by_sev,
            "failed_units": len(failed),
            "excluded_files": excluded.get("count", 0) if isinstance(excluded, dict) else 0,
        },
        "boundaries": _boundaries(by_dim, failed, catalog_source, external, dims,
                                  ctx.get("baseline_truncated", False), excluded,
                                  skipped),
        "failed_units": failed,
        "report": str(report_path),
        "ts": ts,
    }
    mtmp = out_dir / "sdr_manifest.json.tmp"
    mtmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    # atomic placement (same-volume os.replace): a same-second re-run overwrites cleanly
    import os
    os.replace(tmp, report_path)
    os.replace(mtmp, out_dir / "sdr_manifest.json")
    return report_path, manifest


def _run(args) -> dict:
    run_dir = Path(args.run_dir).resolve()
    repo = Path(args.repo).resolve()
    if not run_dir.is_dir():
        _eprint(f"error: run dir not found: {run_dir}\n"
                f"recipe: run diff_group.py --materialize first (creates the run dir "
                f"layout); a zero-diff run renders a 'no changes' report without drafts.")
        sys.exit(1)
    if not repo.is_dir():
        _eprint(f"error: --repo not a directory: {repo}")
        sys.exit(1)
    ctx_path = run_dir / "context.json"
    if not ctx_path.is_file():
        _eprint(f"error: context.json not found in {run_dir}\n"
                f"recipe: run `sdr_context.py --repo <abs> --run-dir <abs>` before "
                f"render (it produces context.json).")
        sys.exit(1)
    try:
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _eprint(f"error: malformed context.json: {e}")
        sys.exit(1)

    drafts, failed = _load_drafts(run_dir)
    by_dim = _merge_findings(drafts)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else run_dir
    report_path, manifest = _render(repo, run_dir, ctx, by_dim, drafts, failed, out_dir)
    _eprint(f"[render_sdr_report] report={report_path}")
    _eprint(f"[render_sdr_report] findings={manifest['counts']['findings']} "
            f"failed_units={manifest['counts']['failed_units']} "
            f"boundaries={len(manifest['boundaries'])}")
    result = {"report": str(report_path), "manifest": str(out_dir / "sdr_manifest.json"),
              "counts": manifest["counts"], "boundaries": len(manifest["boundaries"]),
              "checked": False}
    return result


def _check(run_dir: Path) -> int:
    violations = []
    mp = run_dir / "sdr_manifest.json"
    if not mp.is_file():
        _eprint(f"error: sdr_manifest.json not found in {run_dir}\n"
                f"recipe: run `render_sdr_report.py --run-dir <abs> --repo <abs>` first.")
        return 2
    try:
        m = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _eprint(f"error: malformed sdr_manifest.json: {e}")
        return 2
    # draft truth vs manifest counts
    drafts, failed = _load_drafts(run_dir)
    by_dim = _merge_findings(drafts)
    actual = sum(len(v) for v in by_dim.values())
    if m.get("counts", {}).get("findings") != actual:
        violations.append(f"counts.findings mismatch (manifest "
                          f"{m.get('counts', {}).get('findings')}, drafts {actual})")
    if m.get("counts", {}).get("failed_units") != len(failed):
        violations.append(f"counts.failed_units mismatch (manifest "
                          f"{m.get('counts', {}).get('failed_units')}, disk {len(failed)})")
    if len(m.get("boundaries", [])) < 6:
        violations.append(f"boundaries must have >=6 entries (got "
                          f"{len(m.get('boundaries', []))})")
    report = m.get("report", "")
    if not report or not Path(report).is_file():
        violations.append(f"report file missing: {report!r}")
    else:
        text = Path(report).read_text(encoding="utf-8")
        if "诚实边界" not in text:
            violations.append("report missing honesty-boundary section")
        if report.replace("\\", "/").find("/openspec/") >= 0:
            violations.append("report path under openspec/ (NEVER allowed)")
        # 纯文本 P-NN 引用(目标编辑器不支持 md 内部锚点):any anchor form = violation
        for pat, what in ((r"<a id=", "html anchor <a id="), (r"\{#", "pandoc anchor {#"),
                          (r"\]\(#", "md link anchor ](#")):
            if re.search(pat, text):
                violations.append(f"report contains {what} (NEVER: anchors are not "
                                  f"supported by target editors)")
        # rows[] projection must match the rendered table body row count
        if "## 章节一" in text:
            in_table = False
            header_seen = False
            table_rows = 0
            for ln in text.splitlines():
                if ln.startswith("## "):
                    in_table = ln.startswith("## 章节一")
                    header_seen = False
                    continue
                if in_table and ln.startswith("|"):
                    if "---" in ln:
                        header_seen = True   # separator under the header row
                        continue
                    if not header_seen:
                        header_seen = True   # the header row itself
                        continue
                    table_rows += 1
            if m.get("rows") is not None and len(m["rows"]) != table_rows:
                violations.append(f"manifest rows length {len(m['rows'])} != report "
                                  f"table rows {table_rows}")
        else:
            # old-layout runs without grouping.json render no 简报表; rows must be absent
            if m.get("rows"):
                violations.append("manifest has rows[] but report has no 简报表 section")
    # the renderer NEVER writes beyond the report + run dir: the report must live at the
    # repo root and the manifest in the run dir
    if "sdr_manifest.json" not in str(mp):
        violations.append(f"manifest not in run dir: {mp}")
    if violations:
        _eprint(f"error: render_sdr_report --check: {len(violations)} violation(s):")
        for v in violations:
            _eprint(f"  - {v}")
        _eprint("recipe: re-run `render_sdr_report.py --run-dir <abs> --repo <abs>` "
                "(deterministic; same-second overwrite is atomic).")
        return 2
    _eprint(f"[render_sdr_report] --check ok ({run_dir})")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="deterministic summary renderer for /mgh-sdr: dedup-merge fan-out "
                    "draft findings and render the human-facing report at the project root")
    ap.add_argument("--run-dir", help="absolute run dir (<repo>/.mgh-sdr/runs/<ts>)")
    ap.add_argument("--repo", help="absolute target repo root (report lands here)")
    ap.add_argument("--out-dir", help="manifest output dir (default: the run dir)")
    ap.add_argument("--check", metavar="<run-dir>",
                    help="validate a run dir's manifest + report (fail-loud exit 2)")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.check:
        if args.run_dir or args.repo:
            _eprint("error: --check takes only <run-dir>")
            return 2
        return _check(Path(args.check).resolve())
    if not args.run_dir or not args.repo:
        _eprint("error: --run-dir and --repo are required (or use --check <run-dir>)")
        return 2

    result = _run(args)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
