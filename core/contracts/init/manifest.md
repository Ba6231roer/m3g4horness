# Contract: `init_manifest.json` + checkpoint units

Producer: command orchestrator (i4). Consumer: humans, `/mgh-sra`, `/mgh-blst`, resume.

`init_manifest.json`:

```json
{
  "version": 7,
  "format": "opencode|claude",
  "repo": "<abs repo root>",
  "scope": {"seed": "...", "scope-mode": "defined|applicable"},
  "counts": {"candidates": 0, "controls": 0, "clusters": 0, "unresolved": 0, "out_of_scope": 0, "truncated": false},
  "failures": {"scout": {"done": 0, "failed": 0, "total": 0}, "t1": {"done": 0, "failed": 0, "total": 0}, "t3": {"done": 0, "failed": 0, "total": 0}},
  "scout": {"enabled": true, "skeleton_total": 0, "scout_targets": 0, "batches": 0, "deep_read_files": 0, "audit_sampled": 0, "audit_found": 0, "scout_merged": 0,
            "dispatch": {"form": "native", "source": "host-default|profile", "profile_exists": false, "host_face": "opencode", "consumer": "init", "plan_path": "<abs init-dir>/native_plan.json", "plan_present": true, "native_agent": "init-scout-native"}},
  "codegraph": {"available": false, "used": false, "resolved_count": 0, "unresolved_residual": 0},
  "rules": {"block": "security-controls", "rules_dir": "docs/security-controls (opencode; absent for claude)", "rules_layout": "lazy-index (opencode) | path-scoped (claude)", "categories": 0, "migrated_legacy_blocks": 0, "lint": {"ok": true, "violations": []}},
  "provenance": {"discover": "discover_controls.py", "induct": "init-induct(T1)", "synthesis": "init-synthesis(T2)", "rules": "init-rulewriter(T3)+assemble_rules.py", "scout": "init-scout/merge/audit", "resolve": "init-resolve(codegraph)"},
  "unresolved": ["<file>", ...],
  "out_of_scope": ["<file>", ...],
  "boundaries": [
    "existence-not-effectiveness: CVE-2025-41248 shows @PreAuthorize bypass on parameterized types",
    "call-graph is textual/AST-level; misses AOP/reflection/DI/framework-routing — see unresolved[]",
    "request-context-budget: every model request ≤ a configurable byte threshold (--max-unit-bytes per fan-out unit / --orch-budget-bytes per work-list page / --max-aggregate-bytes per aggregate stage); oversize/shrunk/aggregate-overrun are deterministically sharded/flagged/disclosed (NEVER silently whole-fed); T2/scout-merge aggregate stages are HARD-thresholded via plan_aggregate.py (> --max-aggregate-bytes → two-pass map-reduce: per-shard ≤ budget → single rollup over shard summaries; ≤ budget → single-context, byte-identical); T4 rules-consistency remains soft-bounded (disclose + --scope/--merge fallback) — see inputs/<tier>/*.input.json",
    "dot-prefixed paths are not scanned by default (tooling/VCS/IDE/build/config/index, e.g. .opencode/.claude/.codegraph/.github/.env) — a control whose definition site lives under a .xxx dir will not be discovered unless --include-dotfiles is passed (see discover_controls.py --help); discover stdout `dotfiles_skipped` counts the pruned sources",
    "test source trees are not scanned by default (src/test/src/tests prefix; tests/__tests__/__mocks__/spec/specs dir segment; bare singular test/ is NOT matched — collision risk) — a control whose definition site lives under a test dir will not be discovered unless --include-tests is passed (see discover_controls.py --help); discover stdout `tests_skipped` counts the pruned sources",
    "codegraph enrichment is optional + assistive only: resolves some framework-routed/AOP/DI/interface→impl controls off unresolved[] but shrinks-not-zeros it (reflection/DI-container/runtime-dispatch residual); resolved candidates are LLM+codegraph candidates needing human review — see codegraph.* counts",
    "LLM-induced candidates — human review required",
    "re-entrant resume: pipeline progress is re-derived from disk (<target>/.mgh-init/ products + per-tier .done + run_config.json) by resume_state.py — NOT from conversation memory; compact / crash / new-session all recover via /mgh-init --resume, and run_config.json makes resume stateless of re-typed flags",
    "partial fan-out tolerance: a confirmed unit failure (subagent failed ack → orchestrator writes <checkpoint_path>.failed sibling to .done) is terminal — counted toward tier completion (done+failed>=total), excluded from resume pending (NOT retried), and disclosed in failures.{scout,t1,t3} (per-tier {done,failed,total}) + this boundaries[] line; counts are read from resume_state.py / list_* stdout (disk truth), NEVER agent memory; crash without an ack leaves no marker → unit stays pending → retried (crash is not a confirmed failure); a human may delete a .failed marker then --resume to retry that unit",
    "scout coverage is partial, not whole-repo — see scout.* counts; generic-name + low-fan-in controls may be missed (--no-scout falls back to regex-only)",
    "scout is non-deterministic — cluster count may vary run-to-run (regex-source clusters stay deterministic)",
    "opencode rules are a lazy index in AGENTS.md + per-category detail files: opencode has no path-scoping, so on-demand loading is semantic (directive-driven), not deterministic — an agent that skips the Read may miss a reusable control; claude is path-scoped via paths: (deterministic trigger)",
    "rules purity lint covers high-precision shapes: tool-internal tokens (tool name + distinctive script names + internal paths) + inventory-schema fields (found_controls/evidence_count) + opencode YAML fences (---) + discovery-prose phrases (扫描器模式定义 etc.); bare generic words (category/缺失/锚点), bare tier words (T1/T2/scout), and generic script names remain prompt-guardrail-only, not the deterministic lint"
  ],
  "artifacts": {"candidates":".mgh-init/controls_candidates.json","resolved":".mgh-init/resolved.json (only when codegraph=on & unresolved non-empty)","inventory":".mgh-init/controls_inventory.json","run_config":".mgh-init/run_config.json (start-state intent; stateless-resume source, written step 0)","rules-detail(opencode)":"docs/security-controls/*.md (shipped, per-category H1 docs)","rules":"<target>/.claude/rules|<target>/AGENTS.md (security-controls lazy index) + docs/security-controls/*.md (opencode)","report":".mgh-init/report.md"}
}
```

`scout.scout_merged` = fold-in 实际并入 `controls_candidates.json` 的 scout 候选数
(取值于 `merge_scout.py` 写入的 `provenance.scout_merged`;`resume_state.py` stdout
`tiers.scout.merged` 同源)。`--no-scout` 或 fold-in 未跑时该字段缺省/为空,不声称 scout 并入量。

`scout.dispatch` = **可选字段,仅原生形态在场**(scout 读者批经原生子代理波次派发,
opencode 面 `consumer=init` 缺省解析 native,或画像显式 `dispatch_mode:"native"`):八键
`{form:"native", source:"host-default|profile", profile_exists, host_face:"opencode",
consumer:"init", plan_path, plan_present, native_agent:"init-scout-native"}`,值取自
`list_steps.py` / `resume_state.py` stdout 的 `dispatch` 字段(**NEVER** 靠模型记忆重写;
`plan_present` = `<init-dir>/native_plan.json` 在场证据)。**子进程形态(显式
`dispatch_mode:"runner"`、`consumer=generic`、claude/dsh 面)不出现该字段**——读者以
「字段缺席 = 子进程派发」解释,既有 manifest 形状不变。写 manifest 时同步在
`boundaries[]` 披露实际派发形态与计划工件在场证据(原生形态的诚实边界:止损为波次
粒度〔挂死由看门狗中止兜底〕、编排父会话是单点、任务文件路径转述的残余错抄面〔令牌
展开落地后只剩短号错抄,防线 = 越树守卫 + 重枚举回待派 + 至多一轮重派〕、一次物化只
覆盖当前 pending 页)。

`aggregate_dispatch` = **可选字段,仅原生形态在场**(t1/t2/t3/scout-merge 四个聚合层
map 段的派发披露;与 `scout.dispatch` 同源同缺席语义):

```json
"aggregate_dispatch": {
  "form": "native", "source": "host-default|profile", "host_face": "opencode",
  "consumer": "init",
  "channel": "tool|waves",
  "layers": {
    "t1":  {"plan": "native_plan_t1.json", "plan_present": true, "agent": "init-induct-native"},
    "t2":  {"plan": "native_plan_t2.json", "plan_present": true, "agent": "init-synthesis-native"}
            | {"zero_dispatch": true, "note": "needs_reduce=false → single-context"},
    "scout-merge": {"plan": "native_plan_scout-merge.json", "plan_present": true, "agent": "init-scout-merge-native"}
            | {"single_context": true}
            | {"skipped": true, "note": "--no-scout"},
    "t3":  {"plan": "native_plan_t3.json", "plan_present": true, "agent": "init-rulewriter-native"}
  },
  "fallback_events": ["<通道 A 回退 / 零派发 / 缺口等事实,如实记录>"]
}
```

- `channel` = 实际执行的通道(`"tool"` = 通道 B 派发工具一次调用跑完本页波次 /
  `"waves"` = 通道 A 编排器波次纪律;工具缺席回退通道 A 时如实记 `"waves"` 并把回退
  事实写进 `fallback_events[]`,**NEVER** 声称未发生的通道)。
- 每层 `plan_present` = 该层 `native_plan_<tier>.json` 在场证据;`t2`/`scout-merge` 的
  `needs_reduce=false` 支路记 `zero_dispatch`/`single_context`(零派发不变量的落账)。
- 值取自 `resume_state.py` stdout `dispatch`(聚合扩展键)+ 本 run 过程记录;
  **NEVER** 靠模型记忆重写。子进程形态(显式 runner / claude/dsh 面)整字段缺席。
- 失败缺口披露沿用既有面:`failures.{t1,t3}` 计数 + `boundaries[]` 行;t2/scout-merge
  缺片不 rollup 的事实进 `fallback_events[]` + `report.md`。

### Checkpoint units (`<target>/.mgh-init/checkpoints/<unit>.json`)

Work-unit granularity = isolation unit = resume unit:

| stage | unit key | file |
|---|---|---|
| i1 discover | per file (big file per shard) | `i1/<sha(file)>.json` + `.done` |
| scout reader | per batch | `scout/<batch_id>.json` + `.done` |
| T1 induct | per cluster | `t1/<safe(cluster_id)>.json` + `.done` |
| resolve (opt, codegraph-gated) | whole-repo (1) | `resolved.json` (top-level) + `checkpoints/resolve/.done` (subagent 写、optional/codegraph-gated——非确定性产出者,缺产 = stage 跳过 + 披露) |
| T2 synthesis | whole-repo (1) | `t2/synthesis.json` + `.done` |
| T3 rulewriter | per category | `t3/<category>.<format>.json` + `.done` |
| T4 consistency | whole-repo (1) | `t4/consistency.json` + `.done` |

`--resume` skips any unit whose `.done` exists; `--rebuild-cache` ignores
`cache/callgraph.json` (rebuilt from source mtimes otherwise).

> **输出语言**:`boundaries[]`、`provenance` 文案、`report.md` 等面向人读内容用**简体中文**;
> 键名、路径、枚举、计数保持原样。
