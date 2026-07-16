#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
render_report — deterministic r2 (output adapter) for /mgh-srr: read the finalized sra
drafts (the reused middle engine's output) + intake metadata, and render a plain,
human-readable `security_review_report.md` (简体中文, brief, by dimension/anchor) plus
`srr_manifest.json` (counts + boundaries). NEVER writes anywhere under openspec/.

This is the port-adapter's output seam: the middle engine is reused verbatim; only the
output shape changes (a plain report instead of a managed-block merge into specs/tasks).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/re/sys/pathlib).

CLI contract (`--help` is the contract surface, R5.1):
  py render_report.py --drafts-dir <abs> [--out <dir>] [--memory <path>]
  py render_report.py --check <out-dir>

  --drafts-dir <abs>   drafts directory (absolute) holding <cap>.md JSON drafts from the
                       reused sra-augment/sra-consistency stages (default: <out>/drafts)
  --out <dir>          output dir = the intake working dir holding change_context.json +
                       drafts/ (default: <project>/.mgh-srr). The report + manifest land here.
  --memory <path>      optional business_context.json (counts answered clarifications;
                       default: change_context.memory_source, else none)
  --check <out-dir>    post-render validation: security_review_report.md + srr_manifest.json
                       exist with complete shape (counts fields + >=6 boundaries incl. the
                       SRR-specific one) + no openspec/ path touched; exit 2 on violation.

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"report":"<abs>","manifest":"<abs>","counts":{...},"boundaries":N,"checked":false}
In --check mode: {"check":"srr-report","ok":bool,"out":"<abs>","violations":[...]}.

Exit codes (R5.3b): 0 ok · 1 file missing / JSON malformed ·
2 misuse (argparse), out-dir under openspec/, or report-shape violation (--check).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_DIMENSION_LABEL = {
    "horizontal-authz": "横向越权(IDOR)",
    "vertical-authz": "纵向越权",
    "authentication": "认证",
    "injection": "注入",
    "sensitive-data": "敏感数据",
    "integrity": "完整性",
    "secrets": "密钥配置",
    "rate-limiting": "限流",
    "audit": "审计",
}

# The 6 honesty boundaries: SRR-specific (input completeness/extraction degradation) +
# the 5 reused sra boundaries (LLM candidates / coverage / controls-assert-existence /
# memory-user-asserted / codegraph-optional-advisory).
_BOUNDARIES = [
    "输入抽取对 .docx/.xlsx 是尽力而为(日期/格式/列表降级);评审覆盖受输入完整度上界约束——含糊的需求文档只能产锚点稀疏的泛化缺口。",
    "缺口/增补为 LLM 候选,需人工复核。",
    "覆盖取决于需求文档声明 + 已记业务事实(未声明/未记的看不到)。",
    "引用控制断言存在不断言有效(存在 ≠ 有效)。",
    "业务记忆为用户断言,非代码真相(显式代码/proposal 声明 > 用户记忆 > 默认猜测;冲突时代码为准)。",
    "codegraph 结构确认是可选 advisory(仅目标已建 .codegraph/ 时);call_path 确认 N / 残留 M,不声称全确认;未建索引时确认/残留均为 0。",
]


def _find_project_root(start: Path):
    p = start.resolve()
    for cand in [p, *p.parents]:
        if (cand / "openspec").is_dir():
            return cand
    return p


def _load_json(path: Path, what: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"error: {what} not found: {path}", file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError) as e:
        print(f"error: {what} malformed: {path}: {e}", file=sys.stderr)
        sys.exit(1)


def _load_drafts(drafts_dir: Path):
    if not drafts_dir.is_dir():
        print(f"error: drafts dir not found: {drafts_dir}", file=sys.stderr)
        sys.exit(1)
    drafts = []
    for dp in sorted(drafts_dir.glob("*.md")):
        d = _load_json(dp, f"draft {dp.name}")
        if not isinstance(d, dict):
            print(f"error: draft {dp.name} is not a JSON object", file=sys.stderr)
            sys.exit(2)
        drafts.append(d)
    return drafts


def _aggregate(drafts):
    gaps, sec_reqs = [], []
    ref_controls, dims = set(), set()
    cp_confirmed = cp_residual = 0
    for d in drafts:
        for g in d.get("gaps", []) or []:
            if not isinstance(g, dict):
                continue
            gaps.append(g)
            dim = g.get("dimension")
            if dim:
                dims.add(dim)
            rc = g.get("recommended_control")
            if isinstance(rc, dict) and rc.get("name"):
                ref_controls.add(rc["name"])
                cp = rc.get("call_path")
                if isinstance(cp, dict):
                    if cp.get("confirmed") is True:
                        cp_confirmed += 1
                    elif cp.get("confirmed") in (False, None):
                        cp_residual += 1
        for sr in d.get("security_requirements", []) or []:
            if isinstance(sr, dict):
                sec_reqs.append(sr)
    return {
        "gaps": gaps, "sec_reqs": sec_reqs, "ref_controls": ref_controls,
        "dims": dims, "cp_confirmed": cp_confirmed, "cp_residual": cp_residual,
    }


def _anchor_str(anchor):
    if not isinstance(anchor, dict) or not anchor:
        return "(无具体锚点·泛化缺口)"
    parts = []
    for k in ("requirement", "endpoint", "field"):
        v = anchor.get(k)
        if v:
            parts.append(f"{k}={v}")
    return " / ".join(parts) if parts else "(无具体锚点·泛化缺口)"


def _render_report(doc, agg, degraded, rules_source, memory_source, clarifications):
    """Render security_review_report.md (简体中文, brief, human-readable)."""
    L = []
    L.append(f"# 安全需求评审报告:{doc}")
    L.append("")
    if degraded:
        intro = (f"> 输入抽取:{'/'.join(degraded)}(尽力而为,有保真度损失,见末尾边界)。"
                 f" 控制来源:{rules_source}。项目记忆:{memory_source}。")
    else:
        intro = (f"> 输入抽取:文本原生(无降级)。控制来源:{rules_source}。"
                 f"项目记忆:{memory_source}。")
    L.append(intro)
    L.append("")

    gaps = agg["gaps"]
    if not gaps:
        L.append("## 缺口")
        L.append("")
        L.append("未发现可锚定的安全缺口。覆盖取决于输入完整度(见末尾边界)——含糊的需求文档可能漏掉泛化缺口。")
        L.append("")
    else:
        L.append("## 缺口(按维度)")
        L.append("")
        # group by dimension, preserve first-seen order, "other"/None last
        order = []
        buckets = {}
        for g in gaps:
            dim = g.get("dimension") or "other"
            if dim not in buckets:
                buckets[dim] = []
                order.append(dim)
            buckets[dim].append(g)
        order_sorted = sorted([d for d in order if d != "other"], key=lambda x: x)
        if "other" in buckets:
            order_sorted.append("other")
        for dim in order_sorted:
            label = _DIMENSION_LABEL.get(dim, dim)
            L.append(f"### {label}")
            L.append("")
            for g in buckets[dim]:
                L.append(f"- **锚点**:{_anchor_str(g.get('anchor'))}")
                risk = (g.get("risk") or "").strip()
                if risk:
                    L.append(f"- **风险**:{risk}")
                rc = g.get("recommended_control")
                if isinstance(rc, dict) and rc.get("name"):
                    reason = (rc.get("reason") or "").strip()
                    cp = rc.get("call_path")
                    cp_note = ""
                    if isinstance(cp, dict) and cp.get("confirmed") is True:
                        cp_note = "(codegraph 已确认接入请求路径)"
                    elif isinstance(cp, dict) and cp.get("confirmed") is False:
                        cp_note = "(codegraph:存在但未确认接入)"
                    L.append(f"- **建议复用**:{rc['name']}{(' — ' + reason) if reason else ''}{cp_note}")
                else:
                    L.append("- **建议复用**:无存量控制可复用(若给了 --rules 仍未命中三信号)")
                L.append("")

    sec_reqs = agg["sec_reqs"]
    if sec_reqs:
        L.append("## 安全需求建议")
        L.append("")
        for sr in sec_reqs:
            heading = (sr.get("heading") or "安全要求").strip()
            body = (sr.get("body") or "").strip()
            L.append(f"- **{heading}**")
            if body:
                for ln in body.splitlines():
                    L.append(f"  {ln}" if ln.strip() else "")
        L.append("")

    if clarifications:
        L.append("## 澄清过的问题")
        L.append("")
        for c in clarifications:
            q = c.get("question", "").strip()
            ans = c.get("answer") or c.get("value") or "(默认猜测·未确认)"
            if q:
                L.append(f"- {q} → {ans}")
        L.append("")

    L.append("## 诚实边界")
    L.append("")
    for i, b in enumerate(_BOUNDARIES, 1):
        L.append(f"{i}. {b}")
    L.append("")
    return "\n".join(L)


def _read_clarifications(path):
    if not path or not Path(path).is_file():
        return []
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cl = data.get("clarifications") if isinstance(data, dict) else None
    return cl if isinstance(cl, list) else []


def _count_unconfirmed(clarifications, memory):
    """Clarifications asked but whose fact_key is absent from memory (= never persisted /
    skipped / went to default). Asked - answered-by-memory."""
    if not clarifications:
        return 0
    mem_keys = set()
    if isinstance(memory, dict):
        for c in memory.get("clarifications", []) or []:
            if isinstance(c, dict) and c.get("fact_key"):
                mem_keys.add(c["fact_key"])
    return sum(1 for c in clarifications
               if isinstance(c, dict) and c.get("fact_key") not in mem_keys)


def _run_render(args):
    out_dir = Path(args.out).resolve() if args.out else (_find_project_root(Path.cwd()) / ".mgh-srr")
    # NEVER touch openspec/
    if "openspec" in out_dir.parts:
        print(f"error: out-dir is under openspec/ (srr MUST NOT write openspec/): {out_dir}",
              file=sys.stderr)
        return 2
    drafts_dir = Path(args.drafts_dir).resolve() if args.drafts_dir else (out_dir / "drafts")

    # intake metadata from change_context.json if present
    ctx_path = out_dir / "change_context.json"
    ctx = _load_json(ctx_path, "change_context.json") if ctx_path.is_file() else {}
    doc = ctx.get("change") if isinstance(ctx, dict) else None
    doc = doc or "freeform-review"
    degraded = ctx.get("degraded", []) if isinstance(ctx, dict) else []
    rules_source = ctx.get("rules_source", "none") if isinstance(ctx, dict) else "none"
    clarify_path = ctx.get("clarify_path") if isinstance(ctx, dict) else None

    # memory (explicit override > change_context.memory_source > none)
    memory = None
    memory_source = "none"
    if args.memory:
        mp = Path(args.memory)
        if mp.is_file():
            memory = _load_json(mp, "memory")
            memory_source = str(mp)
    elif isinstance(ctx, dict) and ctx.get("memory_source") not in (None, "none"):
        mp = Path(ctx["memory_source"])
        if mp.is_file():
            memory = _load_json(mp, "memory")
            memory_source = str(mp)

    drafts = _load_drafts(drafts_dir)
    if not drafts:
        print(f"warn: no drafts in {drafts_dir}; rendering an empty review", file=sys.stderr)
    agg = _aggregate(drafts)

    clarifications = _read_clarifications(clarify_path)
    unconfirmed = _count_unconfirmed(clarifications, memory)

    report_md = _render_report(doc, agg, degraded, rules_source, memory_source, clarifications)

    counts = {
        "gaps": len(agg["gaps"]),
        "augmented_requirements": len(agg["sec_reqs"]),
        "referenced_controls": len(agg["ref_controls"]),
        "clarifications_asked": len(clarifications),
        "unconfirmed_defaults": unconfirmed,
        "call_path_confirmed": agg["cp_confirmed"],
        "call_path_residual": agg["cp_residual"],
    }
    manifest = {
        "doc": doc,
        "rules_source": rules_source,
        "memory_source": memory_source,
        "counts": counts,
        "boundaries": list(_BOUNDARIES),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "security_review_report.md"
    manifest_path = out_dir / "srr_manifest.json"
    report_path.write_text(report_md, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {"report": str(report_path), "manifest": str(manifest_path),
               "counts": counts, "boundaries": len(_BOUNDARIES), "checked": False}
    print(f"[render_report] doc={doc} gaps={counts['gaps']} reqs={counts['augmented_requirements']} "
          f"ref_controls={counts['referenced_controls']} clarifications={counts['clarifications_asked']} "
          f"call_path={counts['call_path_confirmed']}/{counts['call_path_residual']} -> {report_path}",
          file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _run_check(out_arg):
    out = Path(out_arg).resolve()
    report = out / "security_review_report.md"
    manifest_p = out / "srr_manifest.json"
    violations = []
    if not report.is_file():
        violations.append("missing security_review_report.md")
    if not manifest_p.is_file():
        violations.append("missing srr_manifest.json")
    if "openspec" in out.parts:
        violations.append("out-dir is under openspec/ (srr MUST NOT write openspec/)")
    if manifest_p.is_file():
        try:
            m = json.loads(manifest_p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            violations.append(f"manifest malformed: {e}")
            m = {}
        if isinstance(m, dict):
            for f in ("doc", "rules_source", "memory_source", "counts", "boundaries"):
                if f not in m:
                    violations.append(f"manifest missing field: {f}")
            counts = m.get("counts") if isinstance(m.get("counts"), dict) else {}
            for f in ("gaps", "augmented_requirements", "referenced_controls",
                      "clarifications_asked", "unconfirmed_defaults",
                      "call_path_confirmed", "call_path_residual"):
                if f not in counts:
                    violations.append(f"manifest counts missing: {f}")
            b = m.get("boundaries")
            if not isinstance(b, list) or len(b) < 6:
                violations.append("manifest boundaries[] missing or < 6")
            elif not any(("输入完整度" in x or "尽力而为" in x) for x in b if isinstance(x, str)):
                violations.append("manifest missing the SRR-specific input-completeness boundary")
    if report.is_file():
        rt = report.read_text(encoding="utf-8")
        if "openspec/" in rt:
            violations.append("report references an openspec/ path")
    ok = not violations
    summary = {"check": "srr-report", "ok": ok, "out": str(out), "violations": violations}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[render_report] --check {out}: ok={ok} violations={len(violations)}", file=sys.stderr)
    return 0 if ok else 2


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="r2 output adapter for /mgh-srr: finalized sra drafts -> plain "
                    "security_review_report.md + srr_manifest.json (never touches openspec/)")
    ap.add_argument("--drafts-dir", metavar="ABS",
                    help="drafts dir holding <cap>.md JSON drafts (default: <out>/drafts)")
    ap.add_argument("--out", help="output / intake working dir (default: <project>/.mgh-srr)")
    ap.add_argument("--memory", help="optional business_context.json path")
    ap.add_argument("--check", metavar="OUT-DIR", default=None,
                    help="post-render validation: report + manifest shape + no openspec/ touched")
    args = ap.parse_args()

    if args.check is not None:
        if not args.check.strip():
            print("error: --check needs an out-dir path", file=sys.stderr)
            return 2
        return _run_check(args.check.strip())
    return _run_render(args)


if __name__ == "__main__":
    sys.exit(main())
