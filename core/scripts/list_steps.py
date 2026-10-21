#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
list_steps — deterministic step invocation manifest for /mgh-init.

Emits the canonical per-step invocation manifest as JSON on stdout. Each step
carries {step, kind, script_abs, invocation, input{}, output{}} where
`script_abs` is an absolute path derived from this script's location
(`Path(__file__).resolve().parent / <script_name>`) — the host prefix
(`.claude/mgh-core/` vs `.opencode/mgh-core/`) is inferred from where the
script is installed, NEVER hardcoded or passed via prompt.

Zero disk preconditions (D3): does NOT read run_config.json, does NOT scan
.mgh-init/ (beyond the two probes below), does NOT depend on any run-state
artifacts. Queryable pre-run, during compaction recovery, or for pure
documentation review. The allowed disk probes (dispatch-form awareness, mirroring
the sdr sister script `list_sdr_steps.py`): the project env profile read
(`<target>/.mgh/env-profile.json`, resolved via the shared `env_profile` module
with `consumer="init"`) and — only when the resolved form is native — a
`<target>/.mgh-init/native_plan.json` presence check reported as corroboration
in the top-level `dispatch` field.

Dispatch-form awareness (scout reader batches; zero-change by construction):
the project env profile decides the scout step's shape. Resolution is the
SINGLE source: explicit `dispatch_mode` wins; otherwise `consumer=init` on the
opencode install face resolves `native` (the opencode-face default — no
profile file means native too), and every other consumer/face keeps the
ESTABLISHED subprocess manifest, byte-identical output (no new stdout fields).
Resolved `native` → the scout step entry switches to the native plan
materializer (`emit_native_plan.py --tier scout`) and gains a `native_arc`
field (materialize → same-message wave dispatch → the unchanged scout-merge
segment), the t1/t2/t3 step entries switch to their aggregate native faces
(materializer entry + native_arc: gate/materialize/dispatch[/rollup/gate]),
and the top-level `dispatch` field appears with
`source`/`profile_exists`/`host_face`/`consumer=init` (+ the aggregate
fragment/agents/plan-presence keys). A malformed profile is
fail-closed: exit 2 + recipe (NEVER silently treated as defaults). A resolved
native on a non-opencode face is fail-closed too: exit 2 + recipe (native
dispatch exists only on the opencode face — NEVER silently run as subprocess).
On the opencode face the init native assets (the five `init-*-native` twins +
the scout and aggregate wave-discipline fragments) are checked before
emitting the manifest; absent → exit 2 + reinstall/runner recipe (NEVER a
silent fallback). The scout step AND the aggregate steps (t1/t2/t3) switch to
their native faces (plan materializer entry + `native_arc` + the native
discipline variant; each aggregate layer's plan file is tier-suffixed
`native_plan_<tier>.json`); the runner form keeps every step byte-identical.

Complements `resume_state.py` (disk-derived "where am I / what's next"):
resume_state gives current step; list_steps gives the exact invocation line
for any step. Use together after --resume/compaction: resume_state yields
`step` → list_steps --step <id> yields the exact invocation.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_steps.py [--target <dir>] [--step <id>]

  --target   target project root (default: .); the env-profile read and the
             plan-artifact probe resolve against it — pass the ABSOLUTE root
             so no probe depends on cwd.
  --step     emit only the single step with this id (e.g., "t1", "discover");
             named ids only; NOT numeric indices (e.g. --step 0 → exit 2 +
             actionable hint). Exits 2 if id not recognized (closed set, R5.3b).
             Default: emit all steps.

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"steps": [{step, kind, script_abs, invocation, input{}, output{}}]
   [, "dispatch": {form, source, profile_exists, host_face, consumer,
                   profile_path, plan_present, native_agent, discipline_fragment}]}
  - dispatch    = present ONLY in the native form (resolved form native on the
                  opencode face): {form:"native", source:"profile"|"host-default",
                  profile_exists, host_face:"opencode", consumer:"init",
                  profile_path, plan_present (corroboration only, the resolved
                  form is the binding decision), native_agent, discipline_fragment}.
                  Absent otherwise.
  - step        = step id (enum matching resume_state.py)
  - kind        = "bash" | "subagent"
  - script_abs  = absolute path to the script (<mgh-core>/scripts/<name>.py,
                 derived from __file__; host-agnostic)
  - invocation  = copy-pasteable Bash invocation line: "py <script_abs> <args>"
  - input{}     = {artifact: "<name>", shape: "<shape>"}
  - output{}    = {artifact: "<name>", shape: "<shape>", path_pattern: "<pattern>"}
  - discipline  = per-step discipline subset {gates[], path_recipes[], nevers[]}
                (gate shapes / fan-out path recipes / applicable NEVER) — identical
                to resume_state.py stdout `discipline_reminders[]` for the same step
                (shared static table in discipline_core.py; `done`/`not-started` and
                unknown steps → EMPTY structure)

Exit codes (R5.3b): 0 ok · 1 target not a dir · 2 misuse (--step not found) or
malformed env profile / native form on a non-opencode face / missing native
assets (fail-closed, with recipe).
Idempotent, no TTY, read-only.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate so sibling imports resolve under any cwd / host-agent invocation.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Shared static per-step discipline table (single source of truth, D1): identical
# to resume_state.py stdout `discipline_reminders[]` for the same step (D5 asserts
# byte-verbatim equality). discipline_core is pure data — no IO, no side effects.
from discipline_core import get_discipline  # noqa: E402
import env_profile  # noqa: E402 — sibling; profile read + fail-closed semantics


# The native scout plan lands next to the plan artifact it materializes from
# (`emit_native_plan.py` anchors the plan beside `scout_plan.json` = the init
# dir). Corroboration probe only — the resolved form is the binding decision.
# The four AGGREGATE tiers carry per-tier suffixed plan names
# (`native_plan_<tier>.json`) so the layers sharing one init dir never
# overwrite each other's plan evidence (scout keeps the un-suffixed name).
_INIT_RUN_ROOT = ".mgh-init"
NATIVE_PLAN_NAME = "native_plan.json"
AGGREGATE_PLAN_NAMES = {
    "t1": "native_plan_t1.json",
    "t2": "native_plan_t2.json",
    "t3": "native_plan_t3.json",
    "scout-merge": "native_plan_scout-merge.json",
}


# Static step→IO table (D2: data-driven, defined once). Step id set matches
# resume_state.py step enumeration (D4 cross-script consistency guard).
# Each entry: {step, kind, script_name, cli_args, input, output}.
# `script_abs` is derived at runtime from __file__.
_STEPS = [
    {
        "step": "not-started",
        "kind": "bash",
        "script_name": "discover_controls.py",
        "cli_args": "--repo <target> --out <init-dir>",
        "input": {"artifact": None, "shape": None},
        "output": {"artifact": "controls_candidates.json", "shape": "{candidates[],source}",
                   "path_pattern": "<init-dir>/controls_candidates.json"},
    },
    {
        "step": "discover",
        "kind": "bash",
        "script_name": "discover_controls.py",
        "cli_args": "--repo <target> --out <init-dir> [--resume]",
        "input": {"artifact": None, "shape": None},
        "output": {"artifact": "controls_candidates.json", "shape": "{candidates[],source}",
                   "path_pattern": "<init-dir>/controls_candidates.json"},
    },
    {
        "step": "survey",
        "kind": "subagent",
        "script_name": None,  # Subagent: no leaf script
        "cli_args": None,
        "input": {"artifact": "controls_candidates.json", "shape": "{candidates[]}"},
        "output": {"artifact": "i1_enriched.json", "shape": "{summary[]}",
                   "path_pattern": "<init-dir>/i1_enriched.json"},
    },
    {
        "step": "scout",
        "kind": "bash",
        "script_name": "fanout_runner.py",
        "cli_args": "--scout-plan <init-dir>/scout_plan.json --checkpoints <init-dir>/checkpoints/scout --inputs-dir <init-dir>/inputs/scout",
        # map-stage drive for the scout-merge aggregate (over-budget path; gate
        # plan_aggregate --node scout-merge decides — needs_reduce=false → this
        # dispatcher line is a clean no-op, see scout fragment).
        "extra_invocations": [
            {"script_name": "fanout_runner.py",
             "cli_args": "--tier scout-merge --init-dir <init-dir> --budget <max-aggregate-bytes> --checkpoints <init-dir>/checkpoints/scout --inputs-dir <init-dir>/inputs/scout-merge"},
        ],
        "input": {"artifact": "scout_plan.json", "shape": "{batches[]"},
                  "output": {"artifact": "scout_candidates.json", "shape": "{candidates[],source}",
                             "path_pattern": "<init-dir>/scout_candidates.json"},
    },
    {
        "step": "resolve",
        "kind": "subagent",
        "script_name": None,  # Subagent: no leaf script
        "cli_args": None,
        "input": {"artifact": "controls_candidates.json::unresolved", "shape": "[unresolved[]]"},
        "output": {"artifact": "resolved.json", "shape": "{resolved[],unresolved_residual[]}",
                   "path_pattern": "<init-dir>/resolved.json"},
    },
    {
        "step": "t1",
        "kind": "bash",
        "script_name": "fanout_runner.py",
        "cli_args": "--tier t1 --clusters <init-dir>/clusters.json --candidates <init-dir>/controls_candidates.json --checkpoints <init-dir>/checkpoints/t1 --inputs-dir <init-dir>/inputs/t1",
        "input": {"artifact": "clusters.json", "shape": "{repo,clusters[]}"},
        "output": {"artifact": "checkpoints/t1/*.json", "shape": "[checkpoint per cluster]",
                   "path_pattern": "<init-dir>/checkpoints/t1/<cluster_id>.json"},
    },
    {
        "step": "t2",
        # Dispatcher-first over the MAP stage (over-budget map-reduce): the
        # deterministic drive = fanout_runner --tier t2. Small-repo (needs_reduce
        # false) single-context init-synthesis is a subagent branch per the t2
        # fragment; fanout with empty pending is a clean no-op (benign, partial:false).
        "kind": "bash",
        "script_name": "fanout_runner.py",
        "cli_args": "--tier t2 --init-dir <init-dir> --budget <max-aggregate-bytes> --checkpoints <init-dir>/checkpoints/t2 --inputs-dir <init-dir>/inputs/t2",
        "input": {"artifact": "checkpoints/t1/*.json", "shape": "[T1 records]"},
        "output": {"artifact": "controls_inventory.json", "shape": "{controls[],category}",
                   "path_pattern": "<init-dir>/controls_inventory.json"},
    },
    {
        "step": "t3",
        "kind": "bash",
        "script_name": "fanout_runner.py",
        "cli_args": "--tier t3 --inventory <init-dir>/controls_inventory.json --format <fmt> --rules-dir <rules-dir> --target <target> --checkpoints <init-dir>/checkpoints/t3 --inputs-dir <init-dir>/inputs/t3",
        "input": {"artifact": "controls_inventory.json", "shape": "{controls[]}"},
        "output": {"artifact": "checkpoints/t3/*.<fmt>.json", "shape": "[checkpoint per category]",
                   "path_pattern": "<init-dir>/checkpoints/t3/<category>.<fmt>.json"},
    },
    {
        "step": "assemble",
        "kind": "bash",
        "script_name": "assemble_rules.py",
        "cli_args": "--target <target> --format <fmt>",
        "input": {"artifact": "checkpoints/t3/*.<fmt>.json", "shape": "[T3 records]"},
        "output": {"artifact": "rules", "shape": "<fmt>-specific files",
                   "path_pattern": "<claude: target>/.claude/rules/security-*.md | <opencode: target>/docs/security-controls/*.md"},
    },
    {
        "step": "t4",
        "kind": "subagent",
        "script_name": None,  # Subagent: no leaf script
        "cli_args": None,
        "input": {"artifact": "rules", "shape": "rule files"},
        "output": {"artifact": "checkpoints/t4/consistency.json.done", "shape": "marker",
                   "path_pattern": "<init-dir>/checkpoints/t4/consistency.json.done"},
    },    {
        "step": "done",
        "kind": "bash",
        "script_name": None,  # Terminal state: no script
        "cli_args": None,
        "input": {"artifact": None, "shape": None},
        "output": {"artifact": "init_manifest.json", "shape": "{version,counts,boundaries[]}",
                   "path_pattern": "<init-dir>/init_manifest.json"},
    },
]


def _script_abs(script_name: str | None) -> str | None:
    """Derive absolute script path from __file__. Returns None for subagent steps
    (no leaf script) or for steps with script_name=None."""
    if script_name is None:
        return None
    # This script resides in <mgh-core>/scripts/; sibling scripts are in the same dir.
    scripts_dir = Path(__file__).resolve().parent
    sibling = scripts_dir / script_name
    return str(sibling) if sibling.exists() else None


def _invocation(script_abs: str | None, cli_args: str | None) -> str | None:
    """Build copy-pasteable Bash invocation line. Returns None for subagent steps."""
    if script_abs is None or cli_args is None:
        return None
    return f"py {script_abs} {cli_args}"


def _mgh_core_root() -> Path:
    """This script's installed <mgh-core> root (its `scripts/` parent)."""
    return Path(__file__).resolve().parent.parent


def _dispatch_form(target: Path):
    """Native-form detection for the scout step via the ONE shared resolver
    (`consumer=init`). An explicit `dispatch_mode` wins; otherwise the init
    consumer on the opencode install face resolves native (the default — no
    profile file means native too), and every other consumer/face keeps the
    established subprocess form. The `native_plan.json` presence probe is
    corroboration only, reported so the orchestrator can see whether a prior
    wave round already materialized. Fail-closed faces:
      * malformed profile → exit 2 + recipe (NEVER silently treated as
        defaults — a "configured native but actually ran runner" mismatch must
        blow up here);
      * resolved native on a non-opencode face → exit 2 + recipe (native
        dispatch exists only on the opencode face; NEVER silently run as
        subprocess);
      * missing scout native assets on the opencode face → exit 2 +
        reinstall/runner recipe (NEVER a silent fallback).
    Returns None unless the native form is active — the caller then omits the
    `dispatch` field entirely and keeps every step byte-identical, so every
    subprocess-form invocation keeps byte-identical stdout."""
    try:
        res = env_profile.resolve(target, consumer="init")
    except env_profile.EnvProfileError as e:
        print(f"error: env profile rejected: {e}\n"
              f"recipe: fix or delete the config — a malformed profile is NEVER "
              f"silently treated as defaults (a 'configured native but actually "
              f"ran runner' mismatch must fail at startup).", file=sys.stderr)
        sys.exit(2)
    if res.form != "native":
        return None
    if res.host_face != "opencode":
        print("error: native dispatch resolved for consumer=init but the host "
              "install face is not opencode — native dispatch exists only on "
              "the opencode face.\n"
              "recipe: set {\"dispatch_mode\":\"runner\"} in "
              "<target>/.mgh/env-profile.json to keep the subprocess form "
              "explicitly, or run /mgh-init from the opencode face. NEVER "
              "silently runs as subprocess.", file=sys.stderr)
        sys.exit(2)
    recipe = env_profile.require_native_assets(_mgh_core_root(), surface="init")
    if recipe:
        print(recipe, file=sys.stderr)
        sys.exit(2)
    plan_present = (target / _INIT_RUN_ROOT / NATIVE_PLAN_NAME).is_file()
    aggregate_plans = {
        tier: (target / _INIT_RUN_ROOT / name).is_file()
        for tier, name in AGGREGATE_PLAN_NAMES.items()
    }
    return {
        "form": "native",
        "source": res.source,
        "profile_exists": res.profile_exists,
        "host_face": res.host_face,
        "consumer": res.consumer,
        "profile_path": str(Path(target) / env_profile.CONFIG_REL),
        "plan_present": plan_present,
        "native_agent": env_profile.INIT_NATIVE_AGENT,
        "discipline_fragment": str(_mgh_core_root() / "prompts" / "fragments"
                                   / "init-scout-native-dispatch.md"),
        "aggregate_fragment": str(_mgh_core_root() / "prompts" / "fragments"
                                  / "init-aggregate-native-dispatch.md"),
        "aggregate_agents": {
            "t1": "init-induct-native",
            "t2": "init-synthesis-native",
            "t3": "init-rulewriter-native",
            "scout-merge": "init-scout-merge-native",
        },
        "aggregate_plan_present": aggregate_plans,
    }


def _native_scout_step(base: dict, dispatch: dict) -> dict:
    """The scout step's NATIVE face: the deterministic entry point is the plan
    materializer (re-materialize = re-enumerate; one materialization covers only
    the enumerator's CURRENT pending page — the wave loop re-materializes until
    `units_total == 0`); the wave dispatch itself is orchestrator discipline,
    carried by the `native_arc` phases + the native discipline variant (same
    table resume_state reports). The scout-merge segment stays subprocess
    (extra_invocations preserved verbatim)."""
    emit_abs = _script_abs("emit_native_plan.py")
    cli_args = ("--tier scout --scout-plan <init-dir>/scout_plan.json "
                "--checkpoints <init-dir>/checkpoints/scout "
                "--inputs-dir <init-dir>/inputs/scout --profile <target>")
    step = dict(base)
    step.update({
        "script": "emit_native_plan.py",
        "script_abs": emit_abs,
        "invocation": _invocation(emit_abs, cli_args),
        "output": {"artifact": "native_plan.json + <batch>.task.md + checkpoints/markers",
                   "shape": "[page-bounded wave split + per-batch task file; terminal "
                            "markers written by the subagents themselves]",
                   "path_pattern": "<init-dir>/native_plan.json "
                                   "(+ <init-dir>/inputs/scout/<batch_id>.task.md)"},
        "native_arc": [
            {"phase": "materialize", "kind": "bash", "script": "emit_native_plan.py",
             "invocation": _invocation(emit_abs, cli_args),
             "note": ("每轮重跑 = 重枚举(pending 由磁盘标记重派生;一次物化只覆盖枚举器当前 "
                      "pending 页,units_total 是本页单元数);物化后同参跑 --check;任一单元"
                      "完成后计划按设计变 stale,波次收尾以重物化修复")},
            {"phase": "waves", "kind": "subagent", "agent": dispatch["native_agent"],
             "discipline_fragment": dispatch["discipline_fragment"],
             "note": ("同一条 assistant 消息并发派当前波全部单元(description=计划短号,"
                      "任务体=单行令牌 mgh-dispatch: plan=<plan_path> unit=<短号>,派发插件"
                      " mgh_dispatch.ts 的令牌展开钩子展开为任务全文;展开钩子缺席的旧版"
                      "安装回退=固定句+task_file 绝对路径逐字透传);看门狗先行(启动与收尾"
                      "参数见 fragment 第 0 节);派完当前页回 materialize,units_total==0 "
                      "才进 merge")},
            {"phase": "merge", "kind": "bash", "step_ref": "scout-merge",
             "note": ("units_total==0(失败缺口已按至多一轮重派纪律接受或为零)→ 回本步既有 "
                      "scout-merge 段:聚合预算闸门(plan_aggregate --node scout-merge)不变;"
                      "needs_reduce=false 单上下文不变;needs_reduce=true 的 map 分片段按"
                      "聚合层原生纪律执行(emit_native_plan --tier scout-merge + 通道 B "
                      "默认/通道 A 回退,计划文件 native_plan_scout-merge.json),"
                      "rollup / audit / fold-in 不变(见 extra_invocations 与聚合 fragment)")},
        ],
        "discipline": get_discipline("scout", domain="init", form="native"),
    })
    # the scout-merge map drive companion switches to the plan materializer in
    # the native face (channel B/A per the aggregate fragment); the subprocess
    # drive stays the extra for the runner form untouched.
    emit_merge_abs = _script_abs("emit_native_plan.py")
    step["extra_invocations"] = [{
        "script": "emit_native_plan.py", "script_abs": emit_merge_abs,
        "invocation": _invocation(
            emit_merge_abs,
            "--tier scout-merge --init-dir <init-dir> --budget "
            "<max-aggregate-bytes> --checkpoints <init-dir>/checkpoints/scout "
            "--inputs-dir <init-dir>/inputs/scout-merge --profile <target>"),
    }]
    return step


def _native_aggregate_step(base: dict, dispatch: dict, tier: str) -> dict:
    """A t1/t2/t3 step's NATIVE face (aggregate layers):
    the deterministic entry point is the plan materializer (re-materialize =
    re-enumerate; page loop until units_total == 0); the dispatch itself is
    channel B (the mgh_dispatch tool, one call per materialized page — the
    DEFAULT) with channel A (orchestrator same-message waves) as the fallback,
    carried by the `native_arc` phases + the native discipline variant (same
    table resume_state reports). Each layer's own invariants (t1 pack/gates,
    t2 zero-dispatch + rollup manifest, t3 positive marker judgment) live in
    the aggregate fragment + the discipline table — the subprocess entries'
    semantics, unchanged."""
    emit_abs = _script_abs("emit_native_plan.py")
    cli = {
        "t1": ("--tier t1 --clusters <init-dir>/clusters.json --candidates "
               "<init-dir>/controls_candidates.json --checkpoints "
               "<init-dir>/checkpoints/t1 --inputs-dir <init-dir>/inputs/t1 "
               "--profile <target> [--pack-bytes 16384 --pack-max 8]"),
        "t2": ("--tier t2 --init-dir <init-dir> --budget <max-aggregate-bytes> "
               "--checkpoints <init-dir>/checkpoints/t2 --inputs-dir "
               "<init-dir>/inputs/t2 --profile <target>"),
        "t3": ("--tier t3 --inventory <init-dir>/controls_inventory.json "
               "--format <fmt> --rules-dir <rules-dir> --target <target> "
               "--checkpoints <init-dir>/checkpoints/t3 --inputs-dir "
               "<init-dir>/inputs/t3 --profile <target>"),
    }[tier]
    agent = dispatch["aggregate_agents"][tier]
    plan_name = AGGREGATE_PLAN_NAMES[tier]
    arc = [
        {"phase": "materialize", "kind": "bash", "script": "emit_native_plan.py",
         "invocation": _invocation(emit_abs, cli),
         "note": ("每轮重跑 = 重枚举(pending 由磁盘标记重派生;一次物化只覆盖枚举器当前 "
                  "pending 页);物化后同参跑 --check;任一单元完成后计划按设计变 stale,"
                  "波次收尾以重物化修复")},
        {"phase": "dispatch", "kind": "tool", "agent": agent,
         "tool": "mgh_dispatch",
         "discipline_fragment": dispatch["aggregate_fragment"],
         "note": ("默认通道 B:工具 mgh_dispatch 输入只带计划引用 {\"plan\": <物化 "
                  "stdout plan_path 逐字>}(整份计划 = 本页全部波次,零 LLM 波次回合);"
                  "工具缺席回退通道 A:同一条 assistant 消息并发派当前波全部单元"
                  "(description=计划短号,任务体=单行令牌 mgh-dispatch: plan=<plan_path> "
                  "unit=<短号>);看门狗先行(与 scout 读者层同一实例);至多一轮重派 + "
                  "限流等窗见 fragment")},
    ]
    if tier == "t2":
        arc.insert(0, {
            "phase": "gate", "kind": "bash", "script": "plan_aggregate.py",
            "invocation": _invocation(
                _script_abs("plan_aggregate.py"),
                "--node t2 --init-dir <init-dir> --budget <max-aggregate-bytes>"),
            "note": ("聚合预算闸门先行且不变:needs_reduce=false → 零派发(物化器不产计划、"
                     "不建会话,stdout note 即此信号;single-context init-synthesis 照既有"
                     "段执行);needs_reduce=true 才进 materialize 相位(--budget 与闸门"
                     "同值)")})
        arc.append({
            "phase": "rollup", "kind": "subagent", "agent": "init-synthesis-rollup",
            "note": ("map 全终态(units_total==0)后单一 rollup 仅吞 rollup.summary_paths "
                     "清单路径(manifest 文件先行,不变);任一分片 .failed → 不 rollup,"
                     "缺口披露")})
    elif tier == "t1":
        arc.append({
            "phase": "gate", "kind": "bash", "script": "validate_t1_records.py",
            "invocation": _invocation(
                _script_abs("validate_t1_records.py"),
                "--strip-bom --checkpoints <init-dir>/checkpoints/t1 "
                "(then --check, same args)"),
            "note": ("T1→T2 形状闸门两形态共用,波次收敛后照常必跑:先 --strip-bom 再 "
                     "--check;退出码 2 → 对 stdout violations[] 外科式重派(删该簇 "
                     ".done → 重物化重派该簇),NEVER 带破损 T1 记录进 T2(t1 层不变量)")})
    else:
        arc.append({
            "phase": "gate", "kind": "bash", "script": "assemble_rules.py",
            "invocation": _invocation(
                _script_abs("assemble_rules.py"),
                "--check --target <target> --format <fmt>"),
            "note": ("规则纯净 lint 对原生形态产出同样把关(t3 层不变量,收口在 assemble "
                     "步);done/failed 判定 = 正向 marker 路径计算,孤儿 marker 清单告警"
                     "照常;agent = init-rulewriter-native,原生评审孪生中唯一带写权限者"
                     "(写面只开规则产物,越树写被守卫拦)"),
        })
    step = dict(base)
    step.update({
        "script": "emit_native_plan.py",
        "script_abs": emit_abs,
        "invocation": _invocation(emit_abs, cli),
        "output": {"artifact": f"{plan_name} + <unit>.task.md + checkpoints/markers",
                   "shape": "[page-bounded wave split + per-unit task file; terminal "
                            "markers written by the subagents themselves]",
                   "path_pattern": f"<init-dir>/{plan_name} "
                                   f"(+ <init-dir>/inputs/{tier}/<unit>.task.md)"},
        "native_arc": arc,
        "discipline": get_discipline(tier, domain="init", form="native"),
    })
    return step


def _build_step(entry: dict) -> dict:
    """Build output step entry from static definition, resolving runtime fields."""
    step_id = entry["step"]
    script_name = entry["script_name"]
    script_abs = _script_abs(script_name)
    cli_args = entry["cli_args"]
    built = {
        "step": step_id,
        "kind": entry["kind"],
        "script": script_name,
        "script_abs": script_abs,
        "invocation": _invocation(script_abs, cli_args),
        "input": entry["input"],
        "output": entry["output"],
        "discipline": get_discipline(step_id),
    }
    # Optional same-step companion commands (e.g. scout step's scout-merge map
    # drive); resolved the same way as the primary invocation.
    extras = []
    for ex in entry.get("extra_invocations", []):
        ex_abs = _script_abs(ex["script_name"])
        extras.append({"script": ex["script_name"], "script_abs": ex_abs,
                       "invocation": _invocation(ex_abs, ex["cli_args"])})
    if extras:
        built["extra_invocations"] = extras
    return built


def main():
    ap = argparse.ArgumentParser(
        description="emit /mgh-init per-step invocation manifest (deterministic, zero disk pre-req)")
    ap.add_argument("--target", default=".",
                    help="target project root (default .); the env-profile read "
                         "and the plan-artifact probe resolve against it — pass "
                         "the ABSOLUTE project root so no probe depends on cwd")
    ap.add_argument("--step", metavar="<id>",
                    help="emit only the single step with this id (e.g. t1, discover); "
                         "named ids only; NOT numeric indices; exits 2 if not "
                         "recognized (closed set)")
    # Emit JSON cleanly regardless of host console codepage (e.g. cp936/gbk on Chinese
    # Windows) so stdout parses everywhere. No-op on StringIO (in-process tests).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = ap.parse_args()

    # Validate --target is a dir (even though unused; keeps contract honest for future)
    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"error: target not a directory: {target}", file=sys.stderr)
        return 1

    # Build all steps
    steps = [_build_step(e) for e in _STEPS]
    dispatch = _dispatch_form(target)
    if dispatch is not None:
        steps = [_native_scout_step(s, dispatch) if s["step"] == "scout"
                 else _native_aggregate_step(s, dispatch, s["step"])
                 if s["step"] in ("t1", "t2", "t3") else s
                 for s in steps]
    step_ids = {s["step"] for s in steps}

    # Filter by --step if requested
    if args.step:
        if args.step not in step_ids:
            msg = f"error: unknown step id: {args.step!r} (known: {sorted(step_ids)})"
            if args.step.isdigit():
                msg += ("; step ids are NAMED enums (from resume_state.py stdout step, "
                        "or run list_steps.py without --step to list all); "
                        "numeric indices are NOT accepted")
            print(msg, file=sys.stderr)
            return 2
        steps = [s for s in steps if s["step"] == args.step]
        print(f"[list_steps] emitting single step: {args.step}", file=sys.stderr)
    else:
        print(f"[list_steps] emitting {len(steps)} steps (use --step <id> for single step)",
              file=sys.stderr)

    result = {"steps": steps}
    if dispatch is not None:
        result["dispatch"] = dispatch
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
