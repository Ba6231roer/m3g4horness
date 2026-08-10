# Contract: `resume_state.py` stdout — re-entrant orchestrator resume state

Producer: `core/scripts/resume_state.py` (read-only leaf). Consumer: the `/mgh-init`
orchestrator — the **single sanctioned outlet** for "which step am I on / what do I do next".
Called as the FIRST action on `--resume` and after any host context compaction
(claude `/compact` / opencode auto-compact).

> 进度真相源 = 磁盘(`<target>/.mgh-init/` 产物 + `.done` + `run_config.json`),**不是对话记忆**。
> compact / crash / 新 session 三态坍缩为同一恢复路径:「读磁盘状态 → 继续」。`step` / `next_action`
> 纯由磁盘重派生,使「compaction 是否丢编排纪律提示词」无关紧要(新 session 重灌命令壳 = 完整提示词)。

## CLI

```
py resume_state.py --target <dir> [--init-dir <dir>] [--check]
py resume_state.py --target <dir> [--init-dir <dir>] --invalidate-stale [--dry-run]
```

`--init-dir` 覆盖默认 `<target>/.mgh-init`。`--check` = 自洽校验(见末尾)。
`--invalidate-stale` = 清除「scout 未完 + 下游 t2/t3/t4 `.done`」过期凭证(见末尾);`--dry-run` 只列不删。

## stdout shape

```json
{
  "target": "<abs target, from run_config>",
  "format": "opencode|claude",
  "step": "<enum>",
  "resumable": true,
  "tiers": {
    "discover": {"done": 1, "failed": 0, "total": 1},
    "scout":    {"done": 0, "failed": 0, "total": 0, "merged": 3},
    "t1":       {"done": 2, "failed": 1, "total": 5},
    "t2":       {"done": 0, "failed": 0, "total": 1},
    "t3":       {"done": 0, "failed": 0, "total": 0},
    "t4":       {"done": 0, "failed": 0, "total": 1}
  },
  "next_action": {
    "kind": "bash|subagent|done",
    "desc": "fan out init-induct per pending cluster via list_clusters.py --materialize",
    "absolute_paths": ["<abs clusters.json>", "<abs controls_candidates.json>", "<abs checkpoints/t1>"]
  },
  "notes": ["survey: optional/advisory ...", "resolve: codegraph=on, unresolved=N ..."]
}
```

- `step` ∈ `not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`。
  **阻塞序列** = `discover→scout→t1→t2→t3→assemble→t4→done`;`survey`/`resolve` 为可选/non-fatal,
  仅进 `notes[]`、**从不阻塞**(对标二者 advisory/fail-soft 语义)。
- `tiers` 只覆盖 6 个 fan-out/聚合 tier(discover/scout/t1/t2/t3/t4),各 `{done,failed,total}`;
  survey/resolve(单上下文可选)与 assemble(确定性)不在 tiers。`failed` = `.failed` marker 计数:
  fan-out tier(scout/t1/t3)的**确认失败**单元(终态、resume 不重试);discover/t2/t4 恒 `failed:0`
  (不适用)。任一 tier `failed>0` 进 `notes[]` 披露(tier名 + failed/total);`failed > total/2` 升级为
  醒目 `WARNING` advisory(**非 gate**,run 仍继续)。
- `next_action.absolute_paths` = `Path.resolve()` 绝对值,**复用** `list_*`/`describe_artifact`
  既有的同款解析(产物文件 + checkpoint 目录),NEVER 自拼 / NEVER 模板 `<target>`。
- `resumable` = 还有未完工作;仅当 `step=done` **且** `init_manifest.json` 存在(全完)才 false。

## step 判定真值表(阻塞序列;由产物 + `.done` + `run_config` 解析)

顺序探针,首个未完成即当前 step(`run_config.mode=merge` 直接 → `merge`):

| step | 完成标志(该 step done ⟺) | 未完时 next_action.kind |
|---|---|---|
| `not-started` | `.mgh-init/` 不存在 | — |
| `discover` | `controls_candidates.json` **且** `clusters.json` 均在 | bash(discover_controls[ --resume]) |
| `scout` | `no_scout` **或**(`scout_plan.json` 在 **且** (0 batch **或** (reader 批 `done+failed>=total` **且** `scout_candidates.json` + `checkpoints/scout/merge.json.done` + fold-in 均完))) | bash/subagent(见下) |
| `t1` | `tiers.t1.done + failed == total`(全部簇 `.done` **或** `.failed` = 终态) | bash(list_clusters 扇出 init-induct) |
| `t2` | `controls_inventory.json` 在 **且** `checkpoints/t2/synthesis.json.done`(或 `t2/.done`) | subagent(init-synthesis) |
| `t3` | `tiers.t3.done + failed == total`(全部 category `.done` **或** `.failed` = 终态) | bash(list_rule_jobs 扇出 init-rulewriter) |
| `assemble` | T3 完后:`checkpoints/t4/...done` 在(或 skip_consistency → 跳到 done) | bash(assemble_rules 然后 T4) |
| `t4` | `checkpoints/t4/consistency.json.done`(或 `t4/.done`) | subagent(init-rules-consistency) |
| `done` | `init_manifest.json` 在 | done(全完) / done(只剩写 manifest,resumable=true) |
| `merge` | `run_config.mode=merge` | bash(--merge 流) |

> **终态门(`done+failed>=total`,非 `done>=total`)**:fan-out 单元的**确认失败**(subagent 回 `failed`
> ack、编排器写 `.failed` marker)是**终态** —— 计入 tier 完成、resume 不重派、不阻塞。crash 无 ack → 无
> marker → 仍 `pending` → resume 重派(crash ≠ 确认失败,安全重试非静默丢失)。

### scout 子状态(关键:防「跳过 scout-merge 直奔 T1」)

`scout` 启用且未完时,按序判定 next_action:
1. `scout_plan.json` 缺 → bash `plan_scout.py`。
2. 有 batch 未终态(`.done` 与 `.failed` 均无)→ bash `list_scout_batches.py` 扇出 init-scout readers。
3. 全部 reader batch 终态(`done+failed>=total`)但 `scout_candidates.json` / `merge.json.done` 缺 → **subagent init-scout-merge**
   (真实失败形状:上下文吃紧的 session 扇出了 readers 却没跑 scout-merge,resume 时编排器
   丢了步骤序,跳到 `merge_scout.py`/T1 并手搓畸形聚合——本状态防之)。merge 仅吞**成功**批记录,
   `.failed` 批跳过(scout 覆盖本就 partial)。
4. `scout_candidates.json` + merge 完但 fold-in 未跑(`controls_candidates.json` 无
   `provenance.scout_merged`)→ bash `merge_scout.py` fold-in。

fold-in 检测:`merge_scout.py` 设 `provenance.scout_merged`(即便 0 scout 候选也设);
该键存在 ⟺ fold-in 已跑(再跑幂等、安全)。

## run_config.json 缺失/破损 → 退出码 2(fail-loud,NEVER 静默猜步骤图)

`run_config.json` 缺失或不可解析 → stdout `{"step":null,"resumable":false,"error":"run_config missing or unparseable"}`
+ stderr recipe「重跑 `/mgh-init --<flags>` 重建」+ **退出码 2**。猜错步骤图 = 执行路径偏离
(用户痛点),故 NEVER 静默猜。`run_config.json` 由 `write_runconfig.py` 在 step 0 原子写出
(见 [`unit-inputs.md`](unit-inputs.md) 的 run_config 行)。

## `--check`(自洽校验)

校验磁盘状态自洽,不自洽 → 退出码 2 + `violations[]`;自洽 → 退出码 0。stdout 另含 `notes[]`
(advisory 披露,非 gate)。
检查项(机械化、低误报):t2 `.done` 在但 `controls_inventory.json` 缺;inventory 在但 t2 标记缺;
t3 `.done` 在但 inventory 缺;`scout_candidates.json` 在但 merge 标记缺;t1 `.done` 孤儿(无兄弟记录);
**同 id 既有 `.done` 又有 `.failed`**(ambiguous terminal,scout/t1/t3 三 checkpoint 目录);discover 产物不一致
(`controls_candidates.json` 与 `clusters.json` 须同在或同缺)。`.failed` 无 sibling 记录**不**报违例
(失败可不产记录体);`.done` 无记录仍按既有孤儿规则报。

scout 启用(`no_scout` falsy)时的两条确定性违例(tier 数据依赖不变量):
- **过期凭证**:scout 未完成 但 t2/t3/t4 任一 `.done` 存在(基于 regex-only 输入产出)→ 退出码 2,
  recipe 指向 `--invalidate-stale`(先 `--dry-run`)。
- **scout 搁浅**:`scout_plan.batches>0` + readers 全终态 + `provenance.scout_merged` 缺失 → 退出码 2
  (跑了却从未并入);`scout_merged` 存在但为 `0` → **非 gate**,进 `notes[]` 醒目披露「审阅 N 批并入 0,可能召回缺口」。

## `--invalidate-stale [--dry-run]`

确定性清除「scout 启用 + scout 未完成 + 下游 t2/t3/t4 `.done`」的过期凭证,使 scout 补完后 plain
`--resume` 重跑 T1–T4 免手工删 marker。失效范围 = t2 `{synthesis.json.done,.done}`、t3 `*.json.done`、
t4 `{consistency.json.done,.done}`;**保留** t1 各簇 `.done`(scout 簇在 fold-in 后自然成新 pending)。
`--dry-run` 只列不删(stdout `markers[]`),实删 stdout `removed[]`;dry-run 与实删共用同一
`init_tier.stale_marker_paths`(两者一致)。幂等(已删则无害)。该范围与 `merge_scout.py` fold-in 的
级联失效完全一致(上游输入变更点自动触发,本命令是 resume 前的显式兜底)。
