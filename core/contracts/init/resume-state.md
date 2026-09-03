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
  survey/resolve(单上下文可选)与 assemble(确定性)不在 tiers。`done`/`failed` = **正向 marker
  路径判定**计数(canonical 单元 id 经与物化同源编码算出 marker 路径、`is_file()` 即终态;与
  `list_clusters`/`list_scout_batches` 的 `pending[]` 语义同源,NEVER 记录体字段/stem 反推):
  fan-out tier(scout/t1/t3)的**确认失败**单元(终态、resume 不重试);discover/t2/t4 恒 `failed:0`
  (不适用)。任一 tier `failed>0` 进 `notes[]` 披露(tier名 + failed/total);`failed > total/2` 升级为
  醒目 `WARNING` advisory(**非 gate**,run 仍继续)。孤儿 marker 不进任何计数(`--check` notes[] 披露)。
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
3. 全部 reader batch 终态(`done+failed>=total`)但 `scout_candidates.json` 缺 → **subagent init-scout-merge**
   (真实失败形状:上下文吃紧的 session 扇出了 readers 却没跑 scout-merge,resume 时编排器
   丢了步骤序,跳到 `merge_scout.py`/T1 并手搓畸形聚合——本状态防之)。按 merge/fold-in 子状态给精确
   note(三支 next_action 恒为 spawn `init-scout-merge`,诚实重生成、唯一恢复路径):
   - merge marker 缺(`checkpoints/scout/merge.json.done` 不在)→ 合并未跑:note「regen 凭证后 fold-in 仍待跑」;
   - merge marker 在 + fold-in 已跑(`controls_candidates.json::provenance.scout_merged` 在)→ note
     「fold-in 已跑(scout_merged=N)、regen 仅作完成凭证(无下游消费、LLM 漂移无害)、NEVER 重跑
     `merge_scout.py` fold-in、regen 后重派生 step=t1」;
   - merge marker 在 + fold-in 未跑(`scout_merged` 不在)→ note「凭证与 fold-in 均欠,regen 后 fold-in 待跑」。
   merge 仅吞**成功**批记录,`.failed` 批跳过(scout 覆盖本就 partial)。
4. `scout_candidates.json` + merge 完但 fold-in 未跑(`controls_candidates.json` 无
   `provenance.scout_merged`)→ bash `merge_scout.py` fold-in。

fold-in 检测:`merge_scout.py` 设 `provenance.scout_merged`(即便 0 scout 候选也设);
`scout_merged` 在 ⟺ fold-in 已跑。**重跑非幂等**——同文件重跑把 `scout_merged` 覆盖为 0(触发虚假召回
缺口披露),漂移重生成文件重跑重复追加候选/簇;resume_state 在 `scout_merged` 存在时 MUST NOT 建议或
指引重跑 `merge_scout.py` fold-in;凭证缺 → 经 `init-scout-merge` 诚实重生成(唯一恢复路径,内容仅作
完成凭证、无下游消费、漂移无害)。

## run_config.json 缺失/破损 → 退出码 2(fail-loud,NEVER 静默猜步骤图)

`run_config.json` 缺失或不可解析 → stdout `{"step":null,"resumable":false,"error":"run_config missing or unparseable"}`
+ stderr recipe「重跑 `/mgh-init --<flags>` 重建」+ **退出码 2**。猜错步骤图 = 执行路径偏离
(用户痛点),故 NEVER 静默猜。`run_config.json` 由 `write_runconfig.py` 在 step 0 原子写出
(见 [`unit-inputs.md`](unit-inputs.md) 的 run_config 行)。

## `--check`(自洽校验)

校验磁盘状态自洽,不自洽 → 退出码 2 + `violations[]`;自洽 → 退出码 0。stdout 另含 `notes[]`
(advisory 披露,非 gate)。
检查项(机械化、低误报):t2 `.done` 在但 `controls_inventory.json` 缺;inventory 在但 t2 标记缺;
t3 `.done` 在但 inventory 缺;`scout_candidates.json` 在但 merge 标记缺;
**同 id 既有 `.done` 又有 `.failed`**(ambiguous terminal,scout/t1/t3 三 checkpoint 目录);
**判定不一致**(canonical 单元按正向 marker 路径判 pending 但其 marker 名已在 checkpoint 目录 →
violation,列 id + 磁盘路径 + recipe「NEVER 重派该单元,先核对 marker 形态再修复枚举身份」);discover 产物不一致
(`controls_candidates.json` 与 `clusters.json` 须同在或同缺)。`.done`/`.failed` 无 sibling 记录体**不**报违例
(touch-only 是合法终态形态——marker 即凭证、记录体仅诊断);**孤儿 marker**(编码文件名不对应任何 canonical
单元 id 的磁盘 marker,scout 排除 tier 级 merge/audit)→ `notes[]` advisory、不计入任何 tier 计数、fail-soft。

> **计数口径(与枚举脚本同源)**:`tiers.t1.done`/`tiers.scout.done` = canonical 单元 id 的**正向 marker
> 路径判定** done 数(谓词共享自 `init_tier.forward_done_ids`/`forward_failed_ids`,`list_clusters`/
> `list_scout_batches` 的 `pending[]` 语义同源,`pending ≡ total - done - failed` 恒可推导)。与
> `ls checkpoints/<tier>/` 目录条目数可不等(条目含 `.failed` marker、记录体、分片 sibling、孤儿)——
> 差异**非数据丢失**。

scout 启用(`no_scout` falsy)时的三条确定性违例(tier 数据依赖不变量):
- **过期凭证**:scout 未完成 但 t2/t3/t4 任一 `.done` 存在(基于 regex-only 输入产出)→ 退出码 2,
  recipe 指向 `--invalidate-stale`(先 `--dry-run`)。
- **scout 搁浅**:`scout_plan.batches>0` + readers 全终态 + `provenance.scout_merged` 缺失 → 退出码 2
  (跑了却从未并入);`scout_merged` 存在但为 `0` → **非 gate**,进 `notes[]` 醒目披露「审阅 N 批并入 0,可能召回缺口」。
- **凭证丢失(镜像违例)**:`checkpoints/scout/merge.json.done` 在 **且** `provenance.scout_merged` 在 **且**
  `scout_candidates.json` 缺 → 退出码 2(fold-in 已跑但完成凭证丢失);recipe = 经 `init-scout-merge` 诚实
  重生成凭证(唯一恢复路径)+ NEVER 重跑 `merge_scout.py` fold-in;与「`scout_candidates.json` 在但 merge
  marker 缺」互为镜像。恢复(凭证重新在盘)后 `--check` 通过。

## `--invalidate-stale [--dry-run]`

确定性清除「scout 启用 + scout 未完成 + 下游 t2/t3/t4 `.done`」的过期凭证,使 scout 补完后 plain
`--resume` 重跑 T1–T4 免手工删 marker。失效范围 = t2 `{synthesis.json.done,.done}`、t3 `*.json.done`、
t4 `{consistency.json.done,.done}`;**保留** t1 各簇 `.done`(scout 簇在 fold-in 后自然成新 pending)。
`--dry-run` 只列不删(stdout `markers[]`),实删 stdout `removed[]`;dry-run 与实删共用同一
`init_tier.stale_marker_paths`(两者一致)。幂等(已删则无害)。该范围与 `merge_scout.py` fold-in 的
级联失效完全一致(上游输入变更点自动触发,本命令是 resume 前的显式兜底)。
