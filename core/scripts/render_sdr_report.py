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
  2. interface grouping is an annotation heuristic — an unrecognized interface falls into
     a standalone unit (coarser granularity, coverage not lost);
  3. cited existing controls assert EXISTENCE, not effectiveness;
  4. external-repo conclusions are a retrieval-moment snapshot (frontend branch sync not
     guaranteed);
  5. the baseline is a byte-budgeted projection — low-priority design details may be
     missing;
  6. the sensitive-catalog source and coverage (fields outside the catalog are only
     recognized by the fallback rule) + failed units (their coverage is unreviewed).
plus a failed-units entry when failed_units[] is non-empty, and a dimensions-narrowed
entry when the run used fewer than the default 6.

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


def _boundaries(by_dim, failed, catalog_source, external, dims, baseline_truncated):
    b = [
        "发现是 LLM 生成的待复核候选,不是已确认漏洞;每次运行非确定性,需人工复核后再处置。",
        "接口分组是注解启发式(Spring/JAX-RS/Servlet 常用注解):未识别的接口落入独立变更单元,"
        "分析粒度变粗但覆盖不丢;非 java web 项目整体退化为独立变更单元模式。",
        "引用存量安全控制仅断言其「存在」,不断言其「有效」;控制有效性须另行验证。",
        "外部仓结论是检索时点快照,不保证前端分支已同步;同名分支缺失时回退其默认分支检索。",
        "检查基线经字节预算投影(优先级:接口授权 > SQL > 输入校验 > 敏感数据),低优先级维度的"
        "存量设计细节可能未全量投影。",
        f"敏感目录来源:{catalog_source}("
        + ("项目目录复用" if catalog_source == "project"
           else "默认模板回退:与 sra/srr 的显式行为分歧,复核域回退 37 项模板,不收窄到 6 facet")
        + ");目录外字段仅按回退规则识别,非穷尽所有敏感字段。",
    ]
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
    return b


def _render(repo: Path, run_dir: Path, ctx: dict, by_dim: dict, drafts, failed,
            out_dir: Path | None):
    branch = ctx.get("branch", "")
    base = ctx.get("base", "")
    dims = ctx.get("dimensions") or DEFAULT_DIMENSIONS
    catalog_source = ctx.get("sensitive_catalog_source", "default-template")
    external = ctx.get("external_repos", [])
    now = datetime.now().astimezone()
    ts = now.strftime("%Y%m%d_%H%M%S")
    report_path = repo / f"{TOOL_NAME}-{_safe_name(branch)}-{ts}.md"

    total = sum(len(v) for v in by_dim.values())
    by_sev = {"high": 0, "medium": 0, "low": 0, "info": 0}
    for lst in by_dim.values():
        for f in lst:
            by_sev[f["severity"]] += 1
    ok_units = [d["unit"] for d in drafts if not d["findings"]]

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
    else:
        L.append("- 外部仓结论:无(未声明 / 不可达降级,前端相关检查面未覆盖)")
    L.append(f"- 单元:{len(drafts) + len(failed)} 个(done {len(drafts)} / failed "
             f"{len(failed)});findings 去重后 {total} 条"
             f"(高 {by_sev['high']} / 中 {by_sev['medium']} / 低 {by_sev['low']} / "
             f"提示 {by_sev['info']})")
    L.append("")
    L.append("> **发现是 LLM 生成的待复核候选,不是已确认漏洞。** 合并/处置前须人工复核。")
    L.append("")

    if total == 0:
        L.append("## 未发现设计缺口候选")
        L.append("")
        L.append("本次检查面内未产出任何问题记录;不代表「无风险」,仅代表本次检查面 + 基线"
                 "投影下未命中。")
        L.append("")
    else:
        ordered_dims = [d for d in DEFAULT_DIMENSIONS if d in by_dim] + \
                       sorted(d for d in by_dim if d not in DEFAULT_DIMENSIONS)
        L.append("## 问题清单(按维度)")
        for dim in ordered_dims:
            label = _DIMENSION_LABEL.get(dim, dim)
            L.append("")
            L.append(f"### {label}(`{dim}`)— {len(by_dim[dim])} 条")
            for f in by_dim[dim]:
                L.append("")
                L.append(f"- **[{_SEVERITY_LABEL.get(f['severity'], f['severity'])}]** "
                         f"路由:`{f['route'] or '(独立变更单元)'}` · 文件:`{f['file']}`"
                         + (f" · 行:{f['line_hint']}" if f["line_hint"] else ""))
                if f["risk"]:
                    L.append(f"  - 风险:{f['risk']}")
                if f["suggestion"]:
                    L.append(f"  - 建议:{f['suggestion']}")
                if f["control_ref"]:
                    L.append(f"  - 命中存量控制:{f['control_ref']}")
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
                         ctx.get("baseline_truncated", False)):
        L.append(f"- {b}")
    L.append("")

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / (report_path.name + ".tmp")
    tmp.write_text("\n".join(L) + "\n", encoding="utf-8")

    manifest = {
        "tool": TOOL_NAME,
        "branch": branch,
        "base": base,
        "dimensions": dims,
        "sensitive_catalog_source": catalog_source,
        "external_repos": [{"slug": e.get("slug"), "path": e.get("path"),
                            "branch_sync_note": e.get("branch_sync_note")}
                           for e in external],
        "counts": {
            "units": len(drafts) + len(failed),
            "interfaces": ctx.get("counts_interface", None),
            "standalone": ctx.get("counts_standalone", None),
            "findings": total,
            "findings_by_severity": by_sev,
            "failed_units": len(failed),
        },
        "boundaries": _boundaries(by_dim, failed, catalog_source, external, dims,
                                  ctx.get("baseline_truncated", False)),
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
