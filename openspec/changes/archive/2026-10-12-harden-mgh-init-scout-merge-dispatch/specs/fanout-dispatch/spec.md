# Delta — fanout-dispatch

## ADDED Requirements

### Requirement: scout-merge tier dispatches scout-merge partial synthesis through the shared wave machine

`fanout_runner.py` 的 `--tier` 闭集 SHALL 扩为 `scout|t1|t2|t3|sdr|scout-merge`,新增
`scout-merge` 条目挂入既有 TIERS 单点映射表:枚举脚本 = `plan_aggregate.py`
(`--node scout-merge` + `--init-dir`/`--budget`/`--materialize` 转发)、任务模板 =
`core/prompts/fragments/fanout/scout-merge-task.md`、fanout agent =
`init-scout-merge-fanout`、占位符/路径字段集与 t2 同形(`input_path`/`checkpoint_path`/
`done_marker`/`failed_marker` + `shard_id`/`batches`/`repo`/`mgh_core`;无
`slice_dir`/`chunk_sources`/`codegraph`)。波次循环、ack 状态机、四级超时不变式、liveness
登记、`--kill-stale`、零推进熔断、快败冷却、进度 sidecar(`<init-dir>/fanout_progress.scout-merge.json`)
SHALL 零改动复用(tier 无关代码路径不变;TIERS 表增行不触既有 scout/t1/t2/t3/sdr 行)。

**枚举 marker-aware**:`plan_aggregate.py --node scout-merge` SHALL 获得与 `--node t2` 同形的
dispatcher 可消费枚举——`pending[]` 排除已 `.done`/`.failed` 的 shard、stdout 补 marker 派生
`total`/`done`/`failed`、每 shard 项含绝对 `checkpoint_path`/`done_marker`/`failed_marker`/
`input_path`、支持 `--include-failed` 重列失败 shard(身份正向派生,NEVER 文件名 stem 反推);
`summary_paths`/`shards` 仍为全集(rollup 与 boundaries 披露用)。此前「scout-merge envelope
逐字节不变(hand-paged non-goal)」的豁免随本 requirement 废止。

**派发面 = 模板逐字填充,模型零撰写**:每个 shard 的任务消息 SHALL 由 dispatcher 从
`scout-merge-task.md` 模板固定占位符逐字替换生成(路径 = 枚举 stdout 绝对值原样注入);
subagent 的 stage 提示词路径由模板钉死为**唯一位置**,读不到即回 `failed` ack,NEVER 自行
搜寻其他目录。编排器 SHALL NOT 再为该 tier 撰写任何逐单元派发消息(消除实跑观测到的
「模型手派时跨目录翻找 agent 定义 → 向人要权限 → 无人值守中断」故障类)。

**三宿主接线**:opencode = `releases/opencode/agent/init-scout-merge-fanout.md`
(`mode: primary` 克隆,headless `opencode run --agent` 可用);claude = 既有 inline
`--agents` 装载同名定义;dsh = `releases/dsh/agents/scout-merge.md` 经
`tools/gen_dsh_tiers.py` 编译为 `tiers/scout-merge.yml`(`REQUIRED_TIERS` 闭集同步,缺定义
= install --check fail-loud)。`install.sh` 自检清单 SHALL 覆盖新模板/agent/stage 提示词;
`tools/check_contracts.py` 覆盖 `--tier scout-merge` 调用面。

**rollup 仍为编排器单步**(与 t2 同形,不进波次机):map 全 `.done` 后,单一
`init-scout-merge-rollup` subagent 仅吞 `rollup.summary_paths`(逐字透传,编排器 NEVER 整读
summary)→ 跨 shard 去重/归一 → 写 `scout_candidates.json` + touch `merge.json.done`;
任一 shard `.failed` 终态 → 不得 rollup,报告缺口后 `--resume` 重入。**手派回退保留**:
dispatcher 退出码 2(宿主 CLI 不可用)→ 编排器按既有逐字透传纪律手派,行为等价。
`needs_reduce=false`(小仓)→ 编排器仍走 single-context `init-scout-merge`,该路径不变;
dispatcher 被误调时 SHALL 幂等空转(0 单元、`partial:false`、不误报 `stalled`)。

#### Scenario: scout-merge map 经共享状态机波次消化

- **WHEN** 全部 scout 批记录聚合 > `--max-aggregate-bytes`,`plan_aggregate.py --node
  scout-merge --materialize` 产出 K 个 ≤ 预算 shard,编排器一次调用
  `fanout_runner.py --tier scout-merge --init-dir <init-dir> --budget <B> --checkpoints
  <scout-dir> --inputs-dir <inputs/scout-merge>`(带 per-call `timeout` 与合规四级超时参数)
- **THEN** dispatcher 内部以 `--wave` 并发消化全部波次,每 shard 一个 `init-scout-merge-fanout`
  subagent(任务消息 = 模板逐字填充),stdout 摘要含 `tier:"scout-merge"`;软时限早退 →
  重派同一命令直至 `partial:false`

#### Scenario: marker-aware 重列收敛,终态 shard 不重派

- **WHEN** 部分 shard 已有 `.done`/`.failed` marker 时 dispatcher 重列枚举
- **THEN** `pending[]` 收缩(终态排除)、`total = done + failed + pending`;零推进熔断与
  `--retry-failed` 行为与 t2 tier 一致

#### Scenario: 派发消息不含模型自撰内容,agent 定义路径钉死

- **WHEN** 审阅 `fanout/scout-merge-task.md` 模板与 dispatcher 填充路径
- **THEN** 任务消息的 stage 提示词路径为模板常量(唯一位置 + 读不到即 `failed` ack 的
  NEVER 搜寻他处纪律);`input_path`/`checkpoint_path`/`done_marker`/`failed_marker` 全部
  来自枚举 stdout 的绝对路径逐字注入

#### Scenario: needs_reduce=false 时 dispatcher 幂等空转

- **WHEN** 编排器误以 `--tier scout-merge` 调用 dispatcher,但聚合输入 ≤ 预算
  (`needs_reduce=false`,pending 空)
- **THEN** dispatcher 以 0 单元、`partial:false` 干净完成,不误报 `stalled:true`;
  single-context `init-scout-merge` 路径行为不变

#### Scenario: 越树 shard 路径 spawn 前拦截

- **WHEN** 某 shard 项路径 resolve 后落在枚举 stdout `repo` 锚树之外
- **THEN** dispatcher 不 spawn 该 shard,直接写 `.failed` marker(reason=path-drift),
  其余单元不受影响(与既有 tier 同一 `_anchor_check` 代码路径)

#### Scenario: dsh tier 闭集同步,缺定义 fail-loud

- **WHEN** `REQUIRED_TIERS` 未含 `scout-merge` 或 `releases/dsh/agents/scout-merge.md` 缺失
  时运行 `gen_dsh_tiers.py --check` / install 自检
- **THEN** 退出码 2 并列出缺失 tier 定义(闭集与 `fanout_runner.TIERS` 键集的等价断言由既有
  回归测兜底)

#### Scenario: 既有 tier 行为零漂移

- **WHEN** 对 scout/t1/t2/t3/sdr 各自枚举产物运行既有调用面
- **THEN** 五 tier 的枚举脚本、模板、agent、占位符集、波次行为逐字一致(TIERS 表增行不触
  既有行)
