# fanout-dispatch Specification — delta

## ADDED Requirements

### Requirement: t2 tier dispatches T2 partial-synthesis through the shared wave machine

`fanout_runner.py` 的 `--tier` 闭集 SHALL 扩为 `scout|t1|t2|t3|sdr`,新增 `t2` 条目挂入既有 TIERS
单点映射表:枚举脚本 = `plan_aggregate.py`(`--node t2` + `--init-dir`/`--budget`/`--materialize`
转发)、任务模板 = `core/prompts/fragments/fanout/t2-task.md`、fanout agent = `init-synthesis-fanout`、
占位符/路径字段集 = `input_path`/`checkpoint_path`/`done_marker`/`failed_marker` +
`shard_id`/`categories`/`repo`(与 t3 同形:无 `slice_dir`/`chunk_sources`/`codegraph`,partial-synthesis
只读结构化 shard 记录、写摘要 checkpoint、不切大文件)。波次循环、ack 状态机、三级超时不变式、liveness
登记、`--kill-stale`、零推进熔断、进度 sidecar(`<init-dir>/fanout_progress.t2.json`)SHALL 对 t2 tier
零改动复用(tier 无关代码路径不变;TIERS 表增行不触既有 scout/t1/t3/sdr 行)。

**枚举字段前置**:`plan_aggregate.py --node t2 --materialize` 的 stdout SHALL 成为 dispatcher 可消费的
合法枚举——顶层补 `repo`(=`--init-dir` resolve 的父目录,`.mgh-init` 恒在 `<target>/.mgh-init` 下)、
marker 派生 `total`/`done`/`failed`,每 `pending[]` shard 项补 `failed_marker`(与 `done_marker` 同目录
`.<shard_id>.json.failed`),且 `pending[]` 排除已有 `.done`/`.failed` marker 的 shard(dispatcher 波次重列 →
pending 收缩;`summary_paths`/`shards` 仍为全集)。dispatcher 据此锚树校验(`_anchor_check`)与 `.failed`
终态写入;任一 shard 路径解析落在 `repo` 锚树外 → spawn 前记 `failed`(reason=path-drift),不进入重派循环。
`needs_reduce=false`(pending 空)时 dispatcher SHALL 幂等空转(0 单元、`partial:false`,不误报 `stalled`),
该路径由编排器在调用 dispatcher 前判定并改走 single-context `init-synthesis`(行为不变)。

`install.sh` 自检清单与 fanout agent 自检 SHALL 覆盖 `plan_aggregate.py` 脚本、`t2-task.md` 模板与
`init-synthesis-fanout` agent 克隆;`tools/check_contracts.py` 覆盖 `--tier t2` 与 `plan_aggregate.py`
新增 flag。既有 scout/t1/t3/sdr 四 tier 的调用面、模板、agent、行为 SHALL 逐字不变。

#### Scenario: t2 tier 经共享状态机波次消化 map 阶段

- **WHEN** 大仓 T1 记录 > `--max-aggregate-bytes`,`plan_aggregate.py --node t2 --materialize` 产出 K 个
  category shard,编排器一次调用 `fanout_runner.py --tier t2 --init-dir <init-dir> --budget 262144
  --checkpoints <t2-dir> --inputs-dir <inputs/t2>`
- **THEN** dispatcher 以 `--wave` 并发度内部消化全部波次,每 shard 一个 `init-synthesis-fanout`
  subagent(任务消息 = `t2-task.md` 模板逐字填充),stdout 摘要含 `tier:"t2"`;软时限早退 / resume / 熔断
  行为与既有 tier 一致

#### Scenario: plan_aggregate t2 stdout 携带 repo 与 failed_marker

- **WHEN** `plan_aggregate.py --node t2 --init-dir <target>/.mgh-init --materialize <inputs/t2>` 产出一页
  shard pending
- **THEN** stdout JSON 顶层含 `repo`(=`<target>` resolve 绝对值),每 shard 项含 `failed_marker`(绝对,
  `.<shard_id>.json.failed`);dispatcher 据此锚定锚树校验与 `.failed` 终态写入

#### Scenario: t2 shard 越树路径 spawn 前拦截

- **WHEN** 某 shard 项的 `checkpoint_path`(或 `failed_marker`)解析后落在 `repo` 锚树外
- **THEN** dispatcher 不 spawn 该 shard,直接写 `.failed` marker(reason=path-drift),后续波次不受影响
  (与既有 tier 同一 `_anchor_check` 代码路径)

#### Scenario: needs_reduce=false 时 dispatcher 幂等空转

- **WHEN** 编排器误以 `--tier t2` 调用 dispatcher,但 `plan_aggregate.py --node t2` 判定
  `needs_reduce=false`(pending 空)
- **THEN** dispatcher 以 0 单元、`partial:false` 干净完成(不误报 `stalled:true`);编排器走 single-context
  `init-synthesis` 路径行为不变

#### Scenario: 既有 tier 行为零漂移

- **WHEN** 对 scout/t1/t3/sdr 各自的枚举产物运行既有调用面并比对本次变更前后的 stdout 摘要与模板填充结果
- **THEN** 四 tier 的枚举脚本、模板、agent、占位符集、波次行为逐字一致(TIERS 表增行不触既有行)
