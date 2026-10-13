# fix-mgh-init-enumeration-caliber — resume-step-discipline delta

## MODIFIED Requirements

### Requirement: T1 终态闸门按单元口径收敛(分片簇不死锁)

step 派生的 t1 闸门 SHALL 以「全部 canonical 单元(整簇 + 真超预算簇的 `::shard-<n>` 分片)
终态」为完成判据:`tiers.t1` SHALL 为单元口径 `{done, failed, total = canonical 单元数(含
分片)}`,`step` 停留 t1 当且仅当 `done + failed < total`。分片簇的收敛 = 其全部分片单元终态
(整簇 marker 存在 OR 簇被切分时全部分片 marker 终态,均计入)。pack 模式(`--pack-bytes > 0`)
下成员级 marker 仍是唯一真相源,单元口径复算对 pack run 同样成立(pack 级 `.failed` marker 经
孤儿审计豁免披露、不进计数)。

**t1 复算预算与派发侧恒同源(run_config 锁步)**:t1 canonical 单元集复算
(`canonical_unit_ids_for_run`)的单元预算 SHALL 与派发侧同值——`run_config.json` 的
`budgets.max_unit_bytes` 存在且为正整数时,复算 MUST 用该值(经收集器的显式预算参数传入);
缺 run_config 或字段缺失时回退共享默认常量(与枚举器缺省一致)。理由〔派发侧透传 run_config
预算后,若复算仍锚共享默认,自定义预算的 run 会出现「物化按 64KB 切片、复算按 192KB 只见整簇
id」的口径分叉——已终态分片 marker 对复算不可见,step 永卡 t1,即 CR-1 死锁形态复活;两侧
同值是同一 change 内的强制锁步(`list_clusters.py::canonical_unit_ids_for_run` 的 COUPLING
LOCKSTEP 注释所锚契约)〕。

`init_manifest.json` 存在(整条 run 的终态凭证)时,step 派生 SHALL **短路为 done,先于任何
tier 闸门探针**——完成态 run 不因下游计数的历史漂移被拉回执行态重派;tier 计数照实披露,但
不再驱动 step。

#### Scenario: 分片簇全 done → step 越过 t1(回归锚)

- **WHEN** 单簇被物化为 3 个 shard 单元、3 个 `.done` marker 全部在盘、t2 产物尚未生成,
  编排器查询 `resume_state.py`
- **THEN** stdout `step` 推进到 t2,`tiers.t1 = {done:3, failed:0, total:3}`;修复前同一磁盘
  状态实测输出 `{done:0, total:1}` + `step:"t1"`(枚举器报 pending=0 与状态机死锁并存)

#### Scenario: 自定义预算 run 的复算与物化同口径

- **WHEN** `run_config.json` 记录 `budgets.max_unit_bytes: 65536`,某簇按 64KB 预算被物化为
  2 个 shard 单元且两 marker 均终态,查询 `resume_state.py`
- **THEN** t1 复算用 65536 复算分片计划,`tiers.t1 = {total:2(该簇), …}` 且两分片计入终态,
  step 越过 t1;修复前复算锚共享默认 192KB → 该簇只见整簇 id、无 marker → step 永卡 t1
  (锁步缺失的 CR-1 复活形态);缺 run_config 的 run 回退共享默认,行为不变

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
