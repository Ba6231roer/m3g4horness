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
py resume_state.py --target <dir> [--init-dir <dir>] [--run-root <name>] [--check]
py resume_state.py --target <dir> [--init-dir <dir>] [--run-root <name>] --invalidate-stale [--dry-run]
py resume_state.py --target <dir> [--init-dir <dir>] [--run-root <name>] --rearm-sentinel
```

`--init-dir` 覆盖默认 `<target>/.mgh-init`;`--run-root` 指定 `<target>` 下的 run 目录**名**
(默认 `.mgh-init`,仅在 `--init-dir` 缺席时生效;默认值与旧硬编码行为字节等价)。
`--check` = 自洽校验(见末尾)。`--invalidate-stale` = 清除「scout 未完 + 下游 t2/t3/t4
`.done`」过期凭证(见末尾);`--dry-run` 只列不删。`--rearm-sentinel` = 据持久化 run_config
确定性重写 `<init-dir>/.active` 哨兵(幂等;compact / clean-stop 后 `--resume` 第一步可调用)。

**动作 flag 互斥**:`--check` / `--invalidate-stale` / `--rearm-sentinel` 三者两两互斥
(argparse 互斥组;组合传入 = 误用,退出码 2 + stderr 指明冲突)。`--dry-run` 仅在
`--invalidate-stale` 存在时有效(单独传入 = 误用,退出码 2)。

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
  "notes": ["survey: optional/advisory ...", "resolve: codegraph=on, unresolved=N ..."],
  "stale_fanout": [],
  "discipline_reminders": {"gates": [], "path_recipes": [], "nevers": []},
  "stage_flow_files": ["<abs>/prompts/fragments/init-stage/t1.md"]
}
```

- `step` ∈ `not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|done`。
  **阻塞序列** = `discover→scout→t1→t2→t3→assemble→t4→done`;`survey`/`resolve` 为可选/non-fatal,
  仅进 `notes[]`、**从不阻塞**(对标二者 advisory/fail-soft 语义)。
- `tiers` 只覆盖 6 个 fan-out/聚合 tier(discover/scout/t1/t2/t3/t4),各 `{done,failed,total}`;
  survey/resolve(单上下文可选)与 assemble(确定性)不在 tiers。`done`/`failed` = **正向 marker
  路径判定**计数(canonical 单元 id 经与物化同源编码算出 marker 路径、`is_file()` 即终态;与
  `list_clusters`/`list_scout_batches` 的 `pending[]` 语义同源,NEVER 记录体字段/stem 反推):
  fan-out tier(scout/t1/t3)的**确认失败**单元(终态、resume 不重试);discover/t2/t4 恒 `failed:0`
  (不适用)。任一 tier `failed>0` 进 `notes[]` 披露(tier名 + failed/total);`failed > total/2` 升级为
  醒目 `WARNING` advisory(**非 gate**,run 仍继续)。孤儿 marker 不进任何计数(`--check` notes[] 披露)。
  **canonical id 集与枚举器同源复算**(单一真相,NEVER 退化副本):t1 = 经 `list_clusters.py`
  生产者侧共享函数按**真实候选 + 共享默认单元预算**复算——恰为可物化单元集(整装簇 → 整簇 id;
  真超预算簇 → **仅** `::shard-<n>` 分片 id),故 `tiers.t1.total` 是**单元数**(含分片),闸门按
  「全部单元终态」收敛(无分片 run 数值与旧簇口径一致);t3 = 经 `list_rule_jobs.py` 的公式按
  inventory categories × run format 派生(`<category>.<fmt>`,与磁盘 marker 命名吻合);scout =
  `scout_plan.json` batch ids(不变)。
- `next_action.absolute_paths` = `Path.resolve()` 绝对值,**复用** `list_*`/`describe_artifact`
  既有的同款解析(产物文件 + checkpoint 目录),NEVER 自拼 / NEVER 模板 `<target>`。
- `resumable` = 还有未完工作;仅当 `step=done` **且** `init_manifest.json` 存在(全完)才 false。
- `stale_fanout[]` = `<init-dir>/fanout_runner.*.pid` liveness 残留扫描(每条
  `{tier,pid_file,pid,pid_alive,note}`;`pid_alive` = OS 进程表探测;任一 alive → note 附
  `--kill-stale --dry-run` recipe)。**字段恒存在**(无残留 = `[]`),**含历史遗留 `run_config.mode=merge` 旧 run(该模式已被 step 0 拒绝,不再有新产出)
  的短路分支在内的一切 step 分支**(消费方下标访问永不 KeyError)。
- `discipline_reminders` = 当前 step 的纪律子集 `{gates[],path_recipes[],nevers[]}`(共享静态表;
  `done`/`not-started`/未知 step → 空结构,字段恒存在)。
- `stage_flow_files[]` = **当前 step 单个** `init-stage/<step>.md` 绝对路径(`Path.resolve()`,
  非 all-remaining);`not-started` → `[]`(bootstrap 由壳 fresh-run recipe fixed-path Read);
  **`done` → `init-stage/done.md`**(收尾纪律——manifest 收尾 + 失败落账 + 移除哨兵——经既有
  「Read stage_flow_files[0]」壳配方可达,长跑压缩后恢复到收尾态不再失联)。resume 衍生量,
  不持久化。

## step 判定真值表(阻塞序列;由产物 + `.done` + `run_config` 解析)

顺序探针,首个未完成即当前 step(`run_config.mode=merge` 为历史遗留,按磁盘产物正常派生——词表已无 `merge` 步)。
**manifest 短路**:`init_manifest.json` 存在 → **先于任何 tier 闸门探针**直接 `step=done`
(manifest 是整条 run 的终态凭证;tier 计数照实输出但不再驱动 step,完成态 run 不因下游
计数口径的历史漂移被拉回执行态重派)。

| step | 完成标志(该 step done ⟺) | 未完时 next_action.kind |
|---|---|---|
| `not-started` | `.mgh-init/` 不存在 | — |
| `discover` | `controls_candidates.json` **且** `clusters.json` 均在 | bash(discover_controls[ --resume]) |
| `scout` | `no_scout` **或**(`scout_plan.json` 在 **且** (0 batch **或** (reader 批 `done+failed>=total` **且** `scout_candidates.json` + `checkpoints/scout/merge.json.done` + fold-in 均完))) | bash/subagent(见下) |
| `t1` | `tiers.t1.done + failed == total`(全部 canonical **单元**(整簇 + 真超预算簇的 `::shard-<n>` 分片)`.done` 或 `.failed` = 终态;`total` = 单元数,经真实候选 + 共享默认预算复算) | bash(list_clusters 扇出 init-induct) |
| `t2` | `controls_inventory.json` 在 **且** `checkpoints/t2/synthesis.json.done`(或 `t2/.done`) | subagent(init-synthesis) |
| `t3` | `tiers.t3.done + failed == total`(全部 category 单元(`<category>.<fmt>`)`.done` 或 `.failed` = 终态) | bash(list_rule_jobs 扇出 init-rulewriter) |
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
violation,列 id + 磁盘路径 + recipe「NEVER 重派该单元,先核对 marker 形态再修复枚举身份」;
**孤儿审计与判定一致性审计覆盖 scout/t1/t3 三个 checkpoint 目录**,t3 的 canonical id 集 =
inventory categories × run format);discover 产物不一致
(`controls_candidates.json` 与 `clusters.json` 须同在或同缺)。`.done`/`.failed` 无 sibling 记录体**不**报违例
(touch-only 是合法终态形态——marker 即凭证、记录体仅诊断);**孤儿 marker**(编码文件名不对应任何 canonical
单元 id 的磁盘 marker,scout 排除 tier 级 merge/audit)→ `notes[]` advisory、不计入任何 tier 计数、fail-soft。

**哨兵生命周期双向违例**(guard 激活语义闭环):
- **进行中缺哨兵**:run 进行中(run_config 在、step≠done)但 `<init-dir>/.active` 缺 → 退出码 2 +
  re-arm recipe(`resume_state.py --rearm-sentinel`;宿主不继承 mid-session env 时守卫整 run 休眠)。
- **完成态哨兵残留**:`init_manifest.json` 在(run 已完成)但 `<init-dir>/.active` 仍在 → 退出码 2 +
  移除 recipe(`rm <init-dir>/.active`;残留哨兵把目标项目日常开发会话整体写锁定)。

> **计数口径(与枚举脚本同源)**:`tiers.t1.done`/`tiers.scout.done`/`tiers.t3.done` = canonical 单元
> id 的**正向 marker 路径判定** done 数(谓词共享自 `init_tier.forward_done_ids`/`forward_failed_ids`,
> `list_clusters`/`list_scout_batches` 的 `pending[]` 语义同源,`pending ≡ total - done - failed` 恒可
> 推导)。id 集**与枚举器同源复算、NEVER 退化副本**:t1 经 `list_clusters` 生产者侧共享函数按真实候选 +
> 共享默认单元预算复算(恰为可物化单元集:整装簇 → 整簇 id;真超预算簇 → 仅分片 id;`tiers.t1.total`
> 为单元数——此前以空候选/零预算退化调用,分片 marker 永不被计数,分片 run 永卡 t1);t3 经
> `list_rule_jobs` 公式按 inventory categories × format 派生(孤儿 marker 不抬高 done)。与
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
`--dry-run` 只列不删(stdout `markers[]`);实删 stdout `removed[]` + `failed[]`(成功时 `failed` 为
空列表,形状恒定)。dry-run 与实删共用同一 `init_tier.stale_marker_paths`(两者一致)。幂等(已删则无害)。
该范围与 `merge_scout.py` fold-in 的级联失效完全一致(上游输入变更点自动触发,本命令是 resume 前的显式兜底)。

**前置判定(与 `--check` 的过期凭证违例同判据)**:scout 启用(`no_scout` falsy)**且** scout 未完成。
前置不满足(no_scout run / scout 已完成)→ **诚实空转**:stdout `removed:[]` + stderr 提示前置不满足、
**删除零文件**、退出码 0——NEVER 对有效下游凭证执行删除(那会迫使 T2-T4 全量重跑)。
**删除失败 fail-loud**:真实删除路径中任一 marker unlink 失败 → 退出码 2,stderr 列失败路径,
stdout `removed[]`/`failed[]` 如实区分已删/未删。
**组合互斥**:与 `--check`/`--rearm-sentinel` 同传 = argparse 误用退出码 2(消除「组合时后到 flag 被
静默短路」的歧义);`--dry-run` 单独传入(无 `--invalidate-stale`)= 误用退出码 2。
