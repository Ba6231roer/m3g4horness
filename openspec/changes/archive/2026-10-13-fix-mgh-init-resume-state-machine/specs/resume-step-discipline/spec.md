## MODIFIED Requirements

### Requirement: 计数口径披露与自洽校验

`resume_state.py` 的 done 口径 SHALL 为「canonical 单元 id 的正向 marker 存在性」——与
`list_clusters.py`/`list_scout_batches.py` 的判定同源(同一编码函数正向计算 marker 路径),
而非裸 glob 文件计数。**canonical id 集本身 SHALL 与枚举器口径合一**(单一真相,禁止第二份
退化实现):

1. **t1 的 id 集 SHALL 经 `list_clusters.py` 生产者侧共享函数复算**:读 `clusters.json` +
   `controls_candidates.json` 真实候选,按**共享默认单元预算**(与枚举器 `--max-unit-bytes`
   缺省值同一常量、共享导入,NEVER 各持一份)派生整簇 id + 真超预算簇的 `::shard-<n>` 分片
   id。SHALL NOT 以空候选集/零预算的退化入参调收集器——该入参下分片簇永判未完,step 永卡
   t1(2026-10-13 评审唯一 Critical 的根因);
2. **t3 的 id 集 SHALL 由「`controls_inventory.json` 的 categories × run format」派生**
   `<category>.<fmt>` 单元 id(id 公式与 `list_rule_jobs.py` 单一来源共享导入),done/failed
   按正向 marker 判定;SHALL NOT 裸 glob 计数(孤儿 marker 不得抬高 done 静默跳过 pending
   category);
3. scout 的 id 集维持 `scout_plan.json::batches[].batch_id`(既有口径不变)。

`--help`/docstring SHALL 注明各消费方口径:
1. `resume_state.py` 的 tier done = canonical id 集上正向判定 done 的单元数(与枚举脚本
   `pending[]` 语义一致:pending 恒可推导为 `total - done - failed`);
2. `ls checkpoints/<tier>/` 目录条目数 = done marker + `.failed` marker + 记录体 `.json`
   + tier 级 merge/audit marker,含孤儿产物 → 与口径 1 可不等;
3. 两数差非数据丢失(口径不同);**孤儿 marker** (不对应任何 canonical id 的磁盘 marker)
   由枚举脚本 stderr 审计告警、由 `resume_state.py --check` 列出(不计入任何 tier 计数,
   fail-soft 提示,不阻断)。

`--check` 自洽校验 SHALL 覆盖:某 canonical 单元同时携带 `.done` 与 `.failed`(歧义终态,
violation);canonical 单元判 pending 但其 marker 文件已存在(判定不一致 = 枚举脚本与磁盘
真相漂移的确定性信号,violation);孤儿 marker(advisory note,非 violation)。**孤儿审计与
判定一致性审计 SHALL 覆盖 scout/t1/t3 三个 checkpoint 目录**(此前 t3 不在审计面内)。
理由〔口径披露是给「人比对文件数与 stdout 数字」的场景;判定不一致从「静默口径差」升级为
「--check 可检 violation」后,身份漂移类缺陷(mgh-init 实测:超长 id 簇 done 判定漂移致
无限重派)在边界即 fail-loud,不再依赖 fan-out 运行时暴露;id 集合一是同一教训的收口——
「枚举说完成、状态机说未完」的分片簇死锁与「状态机说完成、磁盘说有失败」的吞失同属口径
分裂缺陷类〕。

#### Scenario: 用户比对 stdout 与目录条目数

- **WHEN** 用户比对 stdout `tiers.t1.done` 与 `checkpoints/t1/` 下文件数
- **THEN** `resume_state.py` docstring/--help 注明口径差异:done = canonical id 正向判定,
  目录条目数含孤儿与记录体;两数差非数据丢失

#### Scenario: 判定不一致是 --check violation

- **WHEN** 某 canonical 单元无 `.done`/`.failed` marker(按正向路径计算判 pending),但其
  checkpoint 目录存在编码后与该单元 marker 路径相同的文件(判定与磁盘真相矛盾)
- **THEN** `resume_state.py --check` 退出码 2,violations 列出该单元 id + 磁盘 marker 路径
  + 修复 recipe;stdout `pending` 语义不变

#### Scenario: 孤儿 marker 是 advisory note

- **WHEN** checkpoint 目录存在不对应任何 canonical id 的 `.done`/`.failed` marker
  (遗留 run 产物)
- **THEN** `resume_state.py --check` 将其列入 notes[](advisory),不 violation、不阻断;
  tier 计数不含孤儿

#### Scenario: 合法分片 marker 不再误报孤儿

- **WHEN** 某超预算簇已物化为 2 个 `::shard-<n>` 单元且 marker 在盘,运行 `--check`
- **THEN** 该分片 marker 对应复算 id 集中的 canonical id,不出现在孤儿 advisory(修复前
  退化 id 集把全部合法分片 marker 误报为孤儿)

#### Scenario: t3 孤儿 marker 不抬高 done

- **WHEN** `checkpoints/t3/` 存在一个文件名不对应任何 inventory category × format 单元 id 的
  `.json.done` marker,`resume_state.py` 查询该 run
- **THEN** `tiers.t3.done` 不计该 marker;`--check` notes[] 以孤儿披露(t3 审计面与 scout/t1
  对齐)

### Requirement: resume_state stdout 携带 stale-fanout 检出(stale_fanout)

`resume_state.py` 的 stdout SHALL 增 `stale_fanout` 字段(增量字段,基座 shape 不变):扫
`<init-dir>/fanout_runner.*.pid` liveness 文件,每份残留文件报
`{tier, pid_file, pid_alive, note}`;`pid_alive` = 该 PID 当前存活(OS 进程表查询)。
任一 `pid_alive:true` → `note` SHALL 附 `--kill-stale --dry-run` recipe(编排器 resume
第一步先杀孤儿再继续,防双跑烧 token + checkpoint 竞态)。无 liveness 文件 → `stale_fanout:
[]`(字段恒存在,shape 稳定,承 resume_state 既有空结构约定)。**字段恒存在承诺 SHALL 覆盖
全部 step 分支,含 `run_config.mode=merge` 的短路分支**(修复前 merge 分支缺该字段,违背
「field always present」承诺,消费方下标访问即 KeyError)。该字段是 resume 衍生量、非
持久态;`--check` 对 stale-fanout SHALL 仅 advisory 披露(notes[]),NEVER 作为 gate(孤儿
单元留 pending 本就是合法可重派态,杀死旧 runner 是优化而非正确性前提)。

#### Scenario: 孤儿 fanout 在 resume 时被点名

- **WHEN** 上次 t1 fanout 被硬杀、宿主子进程树仍在跑,编排器执行 `/mgh-init --resume` 第一步
  `resume_state.py --target <t>`
- **THEN** stdout `stale_fanout` 含该 tier 条目(`pid_alive:true` + kill-stale recipe),
  `notes[]` 含 advisory 披露;step/next_action 派生逻辑不受影响(仍按磁盘 marker 重派 pending)

#### Scenario: 无孤儿时字段空但不缺

- **WHEN** 运行目录无任何 `fanout_runner.*.pid` 残留
- **THEN** stdout 含 `stale_fanout: []`(字段恒存在),无 note,`--check` 无 stale 相关披露

#### Scenario: merge 模式分支同样携带字段

- **WHEN** `run_config.mode=merge` 的 run 被查询(merge 短路分支)
- **THEN** stdout 含 `stale_fanout`(无残留时为 `[]`),字段集与常规分支一致

## ADDED Requirements

### Requirement: T1 终态闸门按单元口径收敛(分片簇不死锁)

step 派生的 t1 闸门 SHALL 以「全部 canonical 单元(整簇 + 真超预算簇的 `::shard-<n>` 分片)
终态」为完成判据:`tiers.t1` SHALL 为单元口径 `{done, failed, total = canonical 单元数(含
分片)}`,`step` 停留 t1 当且仅当 `done + failed < total`。分片簇的收敛 = 其全部分片单元终态
(整簇 marker 存在 OR 簇被切分时全部分片 marker 终态,均计入)。pack 模式(`--pack-bytes > 0`)
下成员级 marker 仍是唯一真相源,单元口径复算对 pack run 同样成立(pack 级 `.failed` marker 经
孤儿审计豁免披露、不进计数)。

`init_manifest.json` 存在(整条 run 的终态凭证)时,step 派生 SHALL **短路为 done,先于任何
tier 闸门探针**——完成态 run 不因下游计数的历史漂移被拉回执行态重派;tier 计数照实披露,但
不再驱动 step。

#### Scenario: 分片簇全 done → step 越过 t1(回归锚)

- **WHEN** 单簇被物化为 3 个 shard 单元、3 个 `.done` marker 全部在盘、t2 产物尚未生成,
  编排器查询 `resume_state.py`
- **THEN** stdout `step` 推进到 t2,`tiers.t1 = {done:3, failed:0, total:3}`;修复前同一磁盘
  状态实测输出 `{done:0, total:1}` + `step:"t1"`(枚举器报 pending=0 与状态机死锁并存)

#### Scenario: 分片部分完成仍留 t1

- **WHEN** 3 个 shard 仅 2 个终态(2 `.done` + 0 `.failed`)
- **THEN** `step` 停留 t1;重派清单只含未终态分片(经枚举器 `pending[]`,不重派已完分片)

#### Scenario: 分片含失败计入收敛但不吞失

- **WHEN** 3 个 shard 中 2 `.done` + 1 `.failed`
- **THEN** `tiers.t1 = {done:2, failed:1, total:3}`,step 越过 t1(`.failed` 终态承既有语义),
  `notes[]` 披露失败计数(终局需人评)

#### Scenario: manifest 在则 done 短路

- **WHEN** `init_manifest.json` 存在,但某 tier 的磁盘计数呈现「未完」形态(如历史口径漂移
  遗留的分片 marker)
- **THEN** stdout `step = "done"`、`resumable = false`;tier 计数字段照实输出但不驱动 step

### Requirement: done 步收尾纪律可达与完成态哨兵残留违例

step=done 时 `stage_flow_files[]` SHALL 返回 `init-stage/done.md` 的绝对路径——manifest 收尾、
fan-out 失败落账、**收尾移除哨兵 `<init-dir>/.active`** 的纪律经既有「Read stage_flow_files[0]」
壳配方恢复可达(长跑压缩后恢复到收尾态不再失联;not-started 维持空数组,bootstrap 仍由壳
fresh-run recipe fixed-path Read)。survey/resolve 等 step 派生**从不路由**的可选步,其 fragment
头注 SHALL 如实陈述可达性(编排器决定执行该 optional 阶段时按固定路径 Read 本文件),NEVER
声称「经 resume_state per-step 加载」;`assemble.md` 尾部 SHALL 携带「进入 T4 前 Read
`init-stage/t4.md`」的固定路径配方(T4 纪律不依赖 step 派生路由)。

`--check` SHALL 新增完成态哨兵残留违例:`init_manifest.json` 存在(run 已完成)但
`<init-dir>/.active` 仍存在 → 退出码 2 + violations 载移除 recipe(残留哨兵在守卫激活语义下
会把目标项目日常开发会话整体写锁定);进行中 run 缺哨兵的既有违例语义不变。

#### Scenario: 压缩后恢复到收尾态加载 done.md

- **WHEN** 长跑压缩后 resume,全部 stage 完成但 manifest 尚未写(finalize 分支,step=done)
- **THEN** `stage_flow_files[]` 含 done.md 绝对路径;编排器按其完成 manifest 收尾并执行
  `rm <init-dir>/.active`

#### Scenario: 完成态哨兵残留是 --check 违例

- **WHEN** `init_manifest.json` 与 `<init-dir>/.active` 同时存在,运行 `resume_state.py --check`
- **THEN** 退出码 2,violations 含「run 完成但哨兵残留」+ 移除 recipe

#### Scenario: 可选步 fragment 头注不虚假声明

- **WHEN** 审阅 `init-stage/survey.md`/`resolve.md`/`t4.md` 的头注
- **THEN** 头注如实陈述可达性(编排器选择执行时固定路径 Read / 经 assemble.md 尾部配方),
  不出现「Loaded per-step via resume_state.py」类与机制不符的声明

### Requirement: --invalidate-stale 前置判定、删除失败与组合互斥

`--invalidate-stale` SHALL 复用「scout 启用(`run_config.no_scout` falsy)**且** scout 未完成」
作为前置判定(与 `--check` 的 stale-credential 违例同判据):

- 前置不满足(no_scout / scout 已完成)→ SHALL 输出诚实空结果(stdout `removed:[]` /
  `markers:[]`)+ stderr 提示「前置不满足,无过期凭证可清」,删除零文件,退出码 0——
  NEVER 对有效下游凭证执行删除(迫使 T2-T4 全量重跑);
- 真实删除路径中任一 marker unlink 失败 → 退出码 2 fail-loud(stderr 列失败路径 + 可操作
  recipe),SHALL NOT 以 exit 0 静默吞删除失败;
- `--invalidate-stale` 与 `--check`/`--rearm-sentinel` SHALL 互斥:同时传入 → argparse 误用
  退出码 2 + 可操作提示(消除「组合时后到 flag 被静默短路」的歧义语义)。

#### Scenario: no_scout run 上空转不删

- **WHEN** 对 `no_scout=true` 的 run 执行 `--invalidate-stale`(不带 --dry-run)
- **THEN** stdout `removed: []`、退出码 0、下游 t2/t3/t4 marker 零删除,stderr 提示前置不满足

#### Scenario: unlink 失败 fail-loud

- **WHEN** 前置满足且某 stale marker 因文件系统错误 unlink 失败
- **THEN** 退出码 2,stderr 列失败路径;stdout 如实区分已删/未删

#### Scenario: 与 --check 组合是误用

- **WHEN** 同时传 `--invalidate-stale --check`
- **THEN** 退出码 2 + stderr 可操作提示(二者互斥,分开调用),不执行任何删除或校验
