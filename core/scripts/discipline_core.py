#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
discipline_core — shared static per-step discipline table, PER RUN DOMAIN.

Single source of truth for the "how to execute THIS step" reminders that the
orchestrator re-derives from disk after --resume / compaction: gate shapes
(--check commands + fail-loud exit 2), fan-out path recipes (enumerator stdout
`checkpoint_path`/`rule_path`, absolute, verbatim), and applicable NEVER hard
boundaries. Consumed by `resume_state.py` (stdout `discipline_reminders[]`,
current step) and `list_steps.py --step` (stdout `discipline`, same key) — the
two scripts MUST stay byte-identical for the same step (D5 test asserts it).
The sdr domain uses the same contract via `resume_sdr_state.py` /
`list_sdr_steps.py`.

One table per domain, selected by `get_discipline(step, domain=...)`:

  * `init` — the /mgh-init step graph (default; existing callers unchanged).
  * `sdr`  — the /mgh-sdr step graph (`not-started|group|fanout|render|done`).

Tables live in ONE module (not one file per domain) so "is sdr's defense line
still adjacent to init's?" stays answerable at a glance, and so a rename on
either side cannot silently collide across a shared namespace. Unknown/
missing domain → EMPTY, so a newer caller against an older module degrades to
"no reminders" instead of crashing.

Content mirrors the load-bearing defenses in the per-step fragments
(`core/prompts/fragments/init-stage/*.md`) and, for sdr, the dual command
shells' Orchestration flow (same step → same wording) — the table is a
self-contained resume reminder; fragment/shell is the full reference. Steps
with no discipline (`done`, `not-started`) and unknown steps yield the EMPTY
structure (field恒存在, shape stable).

Pure data + one pure function: NO argparse, NO IO, no side effects. Sibling
imported by resume_state/list_steps/resume_sdr_state/list_sdr_steps (R5.3a
self-locate retained for uniform install copies; zero runtime deps, R2).
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


# Shared fan-out resilience recipes (fast-fail storm layer, design D1/D3/D6):
# appended to every fan-out dispatcher step (scout/t1/t3) so a post-resume /
# post-compaction orchestrator re-derives both branches from disk.
_STALLED_PROVIDER_RECIPE = (
    "stalled:true 且 `resume_state.py --check` 无磁盘异常(marker 与 stalled_pending 互洽)"
    "→ provider 拥塞形态:直接重派同一命令(fanout_runner 已内建快败冷却与熔断前一次退避自愈);"
    "NEVER 据此改写单元输入/删 marker/写微脚本")
_RETRY_FAILED_RECIPE = (
    "tier 收尾 failed>0 且单元 run.log(<checkpoints>/<tier>/<unit>.run.log)呈 provider 瞬断形态"
    "(429/rate limit/quota 特征)→ 至多一次 fanout_runner --retry-failed 重派(runner 自动携枚举器 "
    "--include-failed,单元身份永远来自枚举器,认领时先删 .failed marker);再失败接受缺口并在报告披露")


_EMPTY = {"gates": [], "path_recipes": [], "nevers": []}

# =====================================================================
# init domain — step key ∈ resume_state.py enum:
# not-started|discover|survey|scout|resolve|
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
            _pr("scout-fanout-dispatcher",
                "主路径 = 一次 Bash 跑 fanout_runner.py(带 --time-budget-ms < 宿主 per-call timeout × 0.8,且 MUST 显式传 --call-timeout-s < budget×0.8、--stall-timeout-s < --call-timeout-s,四级不变式违反 spawn 前退出码 2;合规 720000/540/300 或 480000/360/300);partial:true 重派同一命令,重派传 per-call timeout > --time-budget-ms(软时限先于宿主硬杀,重派 NEVER 退化为硬杀循环);单元输出静默 ≥ --stall-timeout-s → 树杀重派(不增磁盘终态计数);退出码 2(宿主 CLI 不可用)→ 回退手派路径;NEVER 手动翻页、NEVER 逐次撰写 subagent 任务消息",
                "fanout_runner --step 契约"),
            _pr("scout-fanout-path",
                "scout 批输出路径 = list_scout_batches stdout pending[].checkpoint_path,绝对逐字透传;成功恰好写 checkpoint_path + touch done_marker;失败 ack → 编排器写 failed_marker(终态,不重试不阻断)",
                "list_scout_batches --step 契约"),
            _pr("scout-fanout-stalled-provider", _STALLED_PROVIDER_RECIPE,
                "fanout_runner 快败冷却契约"),
            _pr("scout-fanout-retry-failed", _RETRY_FAILED_RECIPE,
                "fanout_runner --retry-failed 契约"),
        ],
        "nevers": [
            "NEVER 手挖 scout_plan.json",
            "NEVER 写 wrapper .py 循环",
            "NEVER 二次聚合 / 重切批(终态)",
            "NEVER 重跑 `merge_scout.py` fold-in(`controls_candidates.json::provenance.scout_merged` 已设时;重跑非幂等——同文件重跑把 `scout_merged` 归零,漂移文件重跑重复追加候选/簇)",
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
            _pr("t1-fanout-dispatcher",
                "主路径 = 一次 Bash 跑 fanout_runner.py --tier t1(带 --time-budget-ms < 宿主 per-call timeout × 0.8,且 MUST 显式传 --call-timeout-s < budget×0.8、--stall-timeout-s < --call-timeout-s,四级不变式违反 spawn 前退出码 2;合规 720000/540/300 或 480000/360/300);partial:true 重派同一命令,重派传 per-call timeout > --time-budget-ms(软时限先于宿主硬杀,重派 NEVER 退化为硬杀循环);单元输出静默 ≥ --stall-timeout-s → 树杀重派(不增磁盘终态计数);退出码 2 → 看 stderr——宿主 CLI 不可用 → 回退手派路径,scout 闸门(scout-incomplete-gate)→ 先完成 scout 层;NEVER 手动翻页、NEVER 逐次撰写 subagent 任务消息",
                "fanout_runner --step 契约"),
            _pr("t1-fanout-path",
                "T1 单元输出路径 = list_clusters stdout pending[].checkpoint_path,绝对逐字透传;成功恰好写 checkpoint_path + touch done_marker;失败 ack → 编排器写 failed_marker(终态)",
                "list_clusters --step 契约"),
            _pr("t1-pack",
                "配额受限(网关按调用数限流)时 list_clusters 枚举行加 --pack-bytes 16384(--pack-max 8)启用小簇打包:枚举单元 = 包(cluster_id 载包 id、members[] 载成员绝对路径清单,逐字透传;成员级 .done marker 仍是唯一真相源,重派跳过已完成成员);包级 .failed 恢复 recipe:删除该包的 .failed marker(<checkpoints>/t1/<safe(pack id)>.json.failed)→ 重跑枚举 → 包回 pending → 已 done 成员被任务模板跳过,仅缺失成员重归纳",
                "list_clusters --pack-bytes 契约"),
            _pr("t1-fanout-stalled-provider", _STALLED_PROVIDER_RECIPE,
                "fanout_runner 快败冷却契约"),
            _pr("t1-fanout-retry-failed", _RETRY_FAILED_RECIPE,
                "fanout_runner --retry-failed 契约"),
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
                "先判聚合预算:plan_aggregate.py --node t2;needs_reduce=false → single-context init-synthesis(逐字不变);needs_reduce=true(> 预算)→ map-reduce,每个请求 ≤ 预算",
                "plan_aggregate.py --node t2"),
            _pr("t2-fanout-dispatcher",
                "map 主路径(needs_reduce=true 且 pending 非空)= 一次 Bash 跑 fanout_runner.py --tier t2 --init-dir <init-dir> --budget <max-aggregate-bytes>(budget 与 gate 同值;带 --time-budget-ms < 宿主 per-call timeout × 0.8,且 MUST 显式传 --call-timeout-s < budget×0.8、--stall-timeout-s < --call-timeout-s,四级不变式违反 spawn 前退出码 2;合规 720000/540/300 或 480000/360/300);partial:true 重派同一命令,重派传 per-call timeout > --time-budget-ms(软时限先于宿主硬杀,重派 NEVER 退化为硬杀循环);单元输出静默 ≥ --stall-timeout-s → 树杀重派(不增磁盘终态计数);退出码 2(宿主 CLI 不可用)→ 回退手派路径;map 全 .done 后单一 rollup init-synthesis-rollup 吞 rollup.summary_paths;NEVER 手动翻页、NEVER 逐次撰写 subagent 任务消息",
                "fanout_runner --step 契约"),
            _pr("t2-fanout-path",
                "t2 shard 输出路径 = plan_aggregate --node t2 stdout pending[].checkpoint_path,绝对逐字透传;成功恰好写 checkpoint_path(结构化 shard 摘要)+ touch done_marker;失败 ack → 编排器写 failed_marker(终态);任一 shard .failed → 不得 rollup(缺摘要),披露后修复再 --resume",
                "plan_aggregate --node t2 --step 契约"),
        ],
        "nevers": [],
    },
    # step 6 — T3 FAN-OUT (per-category subagents; enumerator path + never).
    "t3": {
        "gates": [],
        "path_recipes": [
            _pr("t3-fanout-dispatcher",
                "主路径 = 一次 Bash 跑 fanout_runner.py --tier t3(带 --time-budget-ms < 宿主 per-call timeout × 0.8,且 MUST 显式传 --call-timeout-s < budget×0.8、--stall-timeout-s < --call-timeout-s,四级不变式违反 spawn 前退出码 2;合规 720000/540/300 或 480000/360/300);partial:true 重派同一命令,重派传 per-call timeout > --time-budget-ms(软时限先于宿主硬杀,重派 NEVER 退化为硬杀循环);单元输出静默 ≥ --stall-timeout-s → 树杀重派(不增磁盘终态计数);退出码 2(宿主 CLI 不可用)→ 回退手派路径;NEVER 手动翻页、NEVER 逐次撰写 subagent 任务消息",
                "fanout_runner --step 契约"),
            _pr("t3-fanout-path",
                "T3 category 输出路径 = list_rule_jobs stdout pending[].rule_path,绝对逐字透传;成功恰好写 rule_path + touch done_marker;失败 ack → 编排器写 failed_marker(终态)",
                "list_rule_jobs --step 契约"),
            _pr("t3-fanout-stalled-provider", _STALLED_PROVIDER_RECIPE,
                "fanout_runner 快败冷却契约"),
            _pr("t3-fanout-retry-failed", _RETRY_FAILED_RECIPE,
                "fanout_runner --retry-failed 契约"),
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


# ---------------------------------------------------------------------
# sdr domain — step key ∈ resume_sdr_state.py enum:
# not-started|group|fanout|render|done (step name = the CURRENT TODO step).
#
# Wording deliberately mirrors the dual command shells' Orchestration flow
# (`releases/{claude-code/commands,opencode/command}/mgh-sdr.md`): the two
# MUST describe the same step the same way, so a post-compaction orchestrator
# gets the same defense line whether it re-reads the shell or the disk state.
# ---------------------------------------------------------------------

# sdr-domain resilience recipes. NOTE the integrity check is the sdr-domain
# executable one (`diff_group.py --check <run-dir>`); the init-domain
# `resume_state.py --check` resolves its run dir under `.mgh-init` and therefore
# CANNOT address an sdr run dir (it exits 1 there — that dead pointer is exactly
# what this domain's table exists to replace).
_SDR_STALLED_PROVIDER_RECIPE = (
    "stalled:true 且 `diff_group.py --check <run-dir>` 退出码 0(分组产物完好:grouping.json + "
    "slices + markers;该检查校验**产物完整性**、**非**运行进度自洽性)→ provider 拥塞形态:直接"
    "同参重派(runner 已内建快败冷却与熔断前一次退避);NEVER 据此改写单元输入/删 marker/写微脚本")
_SDR_RETRY_FAILED_RECIPE = (
    "收尾 failed>0 且该单元 run.log(<checkpoints>/sdr/<unit>.run.log)呈 provider 瞬断形态"
    "(429/rate limit/quota 特征)→ **至多一次** `fanout_runner.py --tier sdr --retry-failed` 重派"
    "(runner 自动携枚举器 --include-failed,认领时先删 .failed marker);再失败接受缺口并在报告 "
    "degraded 披露")
_SDR_FANOUT_DISPATCHER_RECIPE = (
    "主路径 = 一次 Bash 跑 fanout_runner.py --tier sdr(带 --time-budget-ms < 宿主 per-call "
    "timeout × 0.8,且 MUST 显式传 --call-timeout-s < budget×0.8、--stall-timeout-s < "
    "--call-timeout-s,四级不变式违反 spawn 前退出码 2;合规 480000/360/300(claude)或 "
    "720000/540/300(opencode));partial:true 重派同一命令,重派传 per-call timeout > "
    "--time-budget-ms(软时限先于宿主硬杀,重派 NEVER 退化为硬杀循环);单元输出静默 ≥ "
    "--stall-timeout-s → 树杀重派(不增磁盘终态计数);退出码 2(宿主 CLI 不可用)→ 回退手派路径;"
    "NEVER 手动翻页、NEVER 逐次撰写 subagent 任务消息")
_SDR_FANOUT_PATH_RECIPE = (
    "单元输入切片 / 草稿 / 完成标记 / 失败标记 = `diff_group.py` stdout "
    "`pending[].input_path|draft_path|done_marker|failed_marker`(**绝对**、逐字透传给 dispatcher,"
    "dispatcher 逐字填进 subagent task);`baseline_path` / `external_dir` 同源;成功恰好写 "
    "draft_path + touch done_marker,失败 ack → 编排器写 failed_marker(终态,不重试不阻断);"
    "NEVER 自拼 <run-dir>/<unit_id>、NEVER `py -c` 算路径、NEVER 相对路径")
_SDR_RUN_LOG_RECIPE = (
    "非 ok 单元的诊断证据 = <checkpoints>/sdr/<unit>.run.log(绝对路径由 runner 在 stderr 报出);"
    "判断 provider 瞬断形态读它,**NEVER** 靠重跑整 tier 复现")
_SDR_RENDER_MANIFEST_RECIPE = (
    "终态凭证 = <run-dir>/sdr_manifest.json(renderer 先写报告再写 manifest ⟹ manifest 存在即"
    "报告已产出);收尾 counts 读 manifest stdout 字段,**NEVER** `py -c` 挖 JSON")

# step keys are exactly resume_sdr_state.py's closed set.
_DISCIPLINE_SDR = {
    # step `group` — deterministic diff collection + interface grouping. Reached
    # once context.json exists (so the context step's own product is validated
    # here, before the enumeration it feeds is trusted).
    "group": {
        "gates": [
            _g("sdr-context-check",
               "上一步产物校验:baseline.md 在预算内 + 外部仓结论齐备 + 敏感目录形状"
               "(退出码 2 → 回退重跑 sdr_context)",
               "sdr_context.py --check <run-dir>"),
            _g("sdr-diff-group-check",
               "本步产物校验:grouping.json + 切片 + marker 一致(退出码 2 → 回退重跑 diff_group,"
               "NEVER 带破损 work-list 进 fan-out)",
               "diff_group.py --check <run-dir>"),
        ],
        "path_recipes": [
            _pr("sdr-fanout-path", _SDR_FANOUT_PATH_RECIPE, "diff_group --step 契约"),
        ],
        "nevers": [
            "NEVER 自拼 <run-dir>/<unit_id> 路径",
            "NEVER 用 `py -c` 内省 grouping.json",
            "NEVER Read 叶子脚本源码(报错看 stderr)",
        ],
    },
    # step `fanout` — per-unit design-compliance review (the run's only fan-out).
    "fanout": {
        "gates": [
            _g("sdr-diff-group-check",
               "派发前产物完整性(grouping.json + slices + markers;退出码 2 → 先修产物)"
               "兼「stalled 是拥塞还是本地损坏」的判据(退出码 0 = 本地没坏)",
               "diff_group.py --check <run-dir>"),
        ],
        "path_recipes": [
            _pr("sdr-fanout-dispatcher", _SDR_FANOUT_DISPATCHER_RECIPE, "fanout_runner --step 契约"),
            _pr("sdr-fanout-path", _SDR_FANOUT_PATH_RECIPE, "diff_group --step 契约"),
            _pr("sdr-fanout-stalled-provider", _SDR_STALLED_PROVIDER_RECIPE,
                "fanout_runner 快败冷却契约"),
            _pr("sdr-fanout-retry-failed", _SDR_RETRY_FAILED_RECIPE,
                "fanout_runner --retry-failed 契约"),
            _pr("sdr-fanout-run-log", _SDR_RUN_LOG_RECIPE, "fanout_runner run.log 契约"),
        ],
        "nevers": [
            "NEVER 自拼 <run-dir>/<unit_id> 路径",
            "NEVER 用 `py -c` 内省 grouping.json",
            "NEVER 写 wrapper .py 循环",
            "NEVER 手动翻页 / 逐次撰写 subagent 任务消息",
            "NEVER Read 叶子脚本源码(报错看 stderr)",
        ],
    },
    # step `render` — deterministic report + terminal manifest.
    "render": {
        "gates": [
            _g("sdr-render-check",
               "报告与 manifest 校验(draft 齐备 + 报告已写出;退出码 2 → 回退重跑 renderer)",
               "render_sdr_report.py --check <run-dir>"),
        ],
        "path_recipes": [
            _pr("sdr-render-manifest", _SDR_RENDER_MANIFEST_RECIPE,
                "render_sdr_report --step 契约"),
        ],
        "nevers": [
            "NEVER 把报告 / manifest 写进 openspec/",
            "NEVER 用 `py -c` 挖 JSON",
        ],
    },
    # done / not-started → empty structure (field恒存在, shape stable).
    "done": dict(_EMPTY),
    "not-started": dict(_EMPTY),
}

_DOMAINS = {
    "init": _DISCIPLINE,
    "sdr": _DISCIPLINE_SDR,
}


def get_discipline(step: str, domain: str = "init") -> dict:
    """Return the discipline subset for `step` as {gates, path_recipes, nevers}.

    `domain` selects the run domain's table (default `init` — the pre-existing
    callers are unchanged by this parameter's arrival). Unknown domain, unknown
    step, and no-discipline steps (`done`, `not-started`) all → EMPTY structure
    (all three keys present, empty lists) so the stdout field shape is stable
    everywhere.
    """
    table = _DOMAINS.get(domain)
    if table is None:
        return dict(_EMPTY)
    return table.get(step, dict(_EMPTY))
