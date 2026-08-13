#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
discipline_core — shared static per-step discipline table for /mgh-init.

Single source of truth for the "how to execute THIS step" reminders that the
orchestrator re-derives from disk after --resume / compaction: gate shapes
(--check commands + fail-loud exit 2), fan-out path recipes (enumerator stdout
`checkpoint_path`/`rule_path`, absolute, verbatim), and applicable NEVER hard
boundaries. Consumed by `resume_state.py` (stdout `discipline_reminders[]`,
current step) and `list_steps.py --step` (stdout `discipline`, same key) — the
two scripts MUST stay byte-identical for the same step (D5 test asserts it).

Content mirrors the load-bearing defenses in the per-step fragments
`core/prompts/fragments/init-stage/*.md` (scout-incomplete-gate / T1→T2
shape-gate / fan-out path verbatim-pass / `.failed` terminal ack / NEVER
subset) — the table is a self-contained resume reminder; the fragment is the
full reference. Steps with
no discipline (`done`, `not-started`) and unknown steps yield the EMPTY
structure (field恒存在, shape stable).

Pure data + one pure function: NO argparse, NO IO, no side effects. Sibling
imported by resume_state/list_steps (R5.3a self-locate retained for uniform
install copies; zero runtime deps, R2).
"""
from __future__ import annotations
import sys
from pathlib import Path

# Self-locate this script's dir so sibling resolution behaves identically under
# any cwd / host-agent invocation (uniform with resume_state/list_steps) — R5.3a.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _g(id, desc, command, fail_exit=2):
    """Build one gate entry: {id, desc, command, fail_exit}."""
    return {"id": id, "desc": desc, "command": command, "fail_exit": fail_exit}


def _pr(id, desc, source):
    """Build one path-recipe entry: {id, desc, source}."""
    return {"id": id, "desc": desc, "source": source}


_EMPTY = {"gates": [], "path_recipes": [], "nevers": []}

# step key ∈ resume_state.py enum: not-started|discover|survey|scout|resolve|
# t1|t2|t3|assemble|t4|merge|done. Each entry carries ONLY the subset needed to
# execute that step after a resume — the fragment remains the full reference.
_DISCIPLINE = {
    # step 2 — i1 discover (deterministic bash; derived counts via stdout).
    "discover": {
        "gates": [
            _g("discover-check",
               "discover 产物校验(wrapper + 每条 source + cluster_id 唯一)",
               "discover_controls.py --check <init-dir>"),
        ],
        "path_recipes": [
            _pr("discover-derived",
                "派生量(candidates/clusters/unresolved_count/big_files)直读 discover stdout,NEVER py -c 内省产物",
                "discover_controls.py stdout"),
        ],
        "nevers": [
            "NEVER 用 py -c 内省 discover 产物",
            "NEVER Read discover_controls.py 源码(报错看 stderr)",
        ],
    },
    # step 3 — init-survey (optional subagent; advisory + non-fatal).
    "survey": {
        "gates": [],
        "path_recipes": [
            _pr("survey-nonfatal",
                "advisory + non-fatal:i1_enriched.json 缺失不阻断;total 过大(单 subagent 装不下)跳过并在摘要披露",
                "init-stage/survey.md"),
        ],
        "nevers": [],
    },
    # step 3b — SCOUT FAN-OUT (per-batch isolated subagents; gate + path + never).
    "scout": {
        "gates": [
            _g("scout-plan-check",
               "scout_plan.json 批规划校验(batches 非空除非 0 target、每批 bytes≤预算、needs_slice 仅含超批文件)",
               "plan_scout.py --check <init-dir>/scout_plan.json"),
            _g("scout-merge-check",
               "scout_candidates.json 校验(每条 source:scout + file:line)",
               "merge_scout.py --check <init-dir>/scout_candidates.json"),
        ],
        "path_recipes": [
            _pr("scout-fanout-path",
                "scout 批输出路径 = list_scout_batches stdout pending[].checkpoint_path,绝对逐字透传;成功恰好写 checkpoint_path + touch done_marker;失败 ack → 编排器写 failed_marker(终态,不重试不阻断)",
                "list_scout_batches --step 契约"),
        ],
        "nevers": [
            "NEVER 手挖 scout_plan.json",
            "NEVER 写 wrapper .py 循环",
            "NEVER 二次聚合 / 重切批(终态)",
        ],
    },
    # step 3c — init-resolve (optional, codegraph-gated; non-fatal + bounded).
    "resolve": {
        "gates": [],
        "path_recipes": [
            _pr("resolve-checkpoint",
                "init-resolve 恰好写 checkpoint_path(绝对)+ touch done_marker;codegraph=off / unresolved 空 / 清单超预算 → 跳过整 stage + 披露,不阻断",
                "init-stage/resolve.md"),
        ],
        "nevers": [
            "NEVER 拼 <target>/<id>、NEVER 占位符、NEVER 相对路径",
        ],
    },
    # step 4 — T1 FAN-OUT (per-cluster isolated subagents; scout gate + shape gate).
    "t1": {
        "gates": [
            _g("scout-incomplete-gate",
               "scout 启用而 scout 层未完成时 list_clusters 退出码 2(先完成 scout 层,NEVER 以纯 regex 簇继续 T1;--no-scout 显式绕行则跳过)",
               "list_clusters.py (scout-incomplete-gate)"),
            _g("t1-shape-gate",
               "T1→T2 边界形状校验(BOM 剥离 + 根级 cluster_id/name/category/kind/evidence 等形状;退出码 2 → 对 stdout violations[] 外科式重派,NEVER 带破损 T1 记录进 T2)",
               "validate_t1_records.py --strip-bom + --check --checkpoints <init-dir>/checkpoints/t1"),
        ],
        "path_recipes": [
            _pr("t1-fanout-path",
                "T1 单元输出路径 = list_clusters stdout pending[].checkpoint_path,绝对逐字透传;成功恰好写 checkpoint_path + touch done_marker;失败 ack → 编排器写 failed_marker(终态)",
                "list_clusters --step 契约"),
        ],
        "nevers": [
            "NEVER 整份 Read clusters.json",
            "NEVER 拼 <target>/<cluster>",
            "NEVER 用 py -c 内省集群",
            "NEVER 写 wrapper .py 循环",
        ],
    },
    # step 5 — T2 synthesis (aggregate; budget check + inventory validator).
    "t2": {
        "gates": [
            _g("t2-inventory-check",
               "controls_inventory.json 校验(design_controls 兼容字段 + 每条 evidence 锚点 + category→kind 归一;退出码 2 → 回退重跑)",
               "validate_inventory.py --inventory <init-dir>/controls_inventory.json"),
        ],
        "path_recipes": [
            _pr("t2-aggregate-budget",
                "先判聚合预算:plan_aggregate.py --node t2;needs_reduce=true(> 预算)→ map-reduce 每 shard 扇出 + 单一 rollup,每个请求 ≤ 预算",
                "plan_aggregate.py --node t2"),
        ],
        "nevers": [],
    },
    # step 6 — T3 FAN-OUT (per-category subagents; enumerator path + never).
    "t3": {
        "gates": [],
        "path_recipes": [
            _pr("t3-fanout-path",
                "T3 category 输出路径 = list_rule_jobs stdout pending[].rule_path,绝对逐字透传;成功恰好写 rule_path + touch done_marker;失败 ack → 编排器写 failed_marker(终态)",
                "list_rule_jobs --step 契约"),
        ],
        "nevers": [
            "NEVER 整份 Read controls_inventory.json",
            "NEVER 手挖 controls_inventory.json",
            "NEVER 拼 <target>/<category>",
            "NEVER 写 wrapper .py 循环",
        ],
    },
    # step 6b — ASSEMBLE / LINT (deterministic; purity lint fail-loud).
    "assemble": {
        "gates": [
            _g("assemble-lint",
               "规则纯净性 lint(禁 front matter / inventory schema 字段 / 过程散文泄漏;退出码 2 → 回 T3 修正后重跑)",
               "assemble_rules.py --check --target <target> --format <fmt>"),
        ],
        "path_recipes": [],
        "nevers": [],
    },
    # step 7 — T4 consistency (unless --skip-consistency; subagent, no leaf script).
    "t4": {
        "gates": [],
        "path_recipes": [
            _pr("t4-inplace",
                "init-rules-consistency in-place 编辑 rule/detail 文件 + 写 checkpoints/t4/.done;T4 跳过(--skip-consistency)则无此步",
                "init-stage/t4.md"),
        ],
        "nevers": [],
    },
    # --merge mode short-circuit (merge partial inventories by evidence anchor → STOP).
    "merge": {
        "gates": [],
        "path_recipes": [
            _pr("merge-partials",
                "merge partial inventories by evidence anchor 后 STOP(不进入常规 pipeline)",
                "resume_state.py merge mode"),
        ],
        "nevers": [],
    },
    # done / not-started → empty structure (field恒存在, shape stable).
    "done": dict(_EMPTY),
    "not-started": dict(_EMPTY),
}


def get_discipline(step: str) -> dict:
    """Return the discipline subset for `step` as {gates, path_recipes, nevers}.

    Unknown / no-discipline steps → EMPTY structure (all three keys present,
    empty lists) so the stdout field shape is stable across every step.
    """
    return _DISCIPLINE.get(step, dict(_EMPTY))
