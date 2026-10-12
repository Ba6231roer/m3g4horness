# Delta — request-context-budget

## MODIFIED Requirements

### Requirement: Configurable request-context byte budgets

每条 `mgh-*` 命令(`/mgh-init`、`/mgh-sast`、`/mgh-sra`、`/mgh-srr`)SHALL 接受三个可配置字节预算 flag:
`--max-unit-bytes`(单 fan-out 单元物化输入上限,默认 192KB)、`--orch-budget-bytes`(编排器单次请求可见的
待办壳页上限,默认 64KB)、`--max-aggregate-bytes`(跨单元聚合 stage 输入上限,默认 **96KB**)。三者 SHALL
在**花 token 之前**的参数解析阶段被接受并落入各命令 `--help` 参数表(承 R5.1,`--help` 即契约面)。无效值
(负数/非整数)MUST 在解析期 fail-loud(退出码 2),不进入后续阶段。预算语义对四命令的扇出与聚合节点
**统一**适用;同名 flag 在各声明脚本(`plan_aggregate.py` 的 `DEFAULT_BUDGET`、`write_runconfig.py` /
`write_ut_runconfig.py` / `render_report.py` 的 `DEFAULT_MAX_AGGREGATE_BYTES`)的默认值 MUST 同值。

`--max-aggregate-bytes` 默认值 96KB 的定值依据 SHALL 记录于契约:按本仓 token 启发式最坏口径
(CJK 密集内容 ≈ 2 字节/token),单聚合请求输入 ≤ ~48K token,叠加 stage 提示词与有界回传后仍
远低于 ~150K token 上下文窗口模型的 120K 输入红线;显式传 flag 可覆盖该默认(大窗口模型用户
可自行放大)。

#### Scenario: Budget flags are accepted across all four commands
- **WHEN** 任一 `mgh-*` 命令以 `--max-unit-bytes 131072 --orch-budget-bytes 32768` 运行
- **THEN** 三个 flag 被该命令 argparse 接受、出现在其 `--help`,流水线按给定预算运行

#### Scenario: Invalid budget fails before any LLM call
- **WHEN** 任一 `mgh-*` 命令传 `--max-unit-bytes -1`
- **THEN** 系统在参数解析期 fail-loud(退出码 2),不扫描、不调 LLM

#### Scenario: Defaults apply when flags omitted
- **WHEN** 任一 `mgh-*` 命令未给任一预算 flag
- **THEN** `--max-unit-bytes=192KB`/`--orch-budget-bytes=64KB`/`--max-aggregate-bytes=96KB` 默认生效

#### Scenario: Aggregate default is uniform across declaring scripts
- **WHEN** 分别运行 `plan_aggregate.py --help`、`write_runconfig.py --help`、`write_ut_runconfig.py --help`、`render_report.py --help` 且不传预算 flag
- **THEN** 各 help 文案声明的聚合预算默认值均为 98304 字节(96KB),实际生效默认与文案一致

## ADDED Requirements

### Requirement: Init aggregate node dispatched shards are hard-bounded

`/mgh-init` 两个聚合节点(T2 `plan_aggregate.py --node t2`、scout-merge
`plan_aggregate.py --node scout-merge`)在 map-reduce 路径下,每个**被派发** shard 的物化输入
`bytes` MUST ≤ `--max-aggregate-bytes`——「oversize shard 告警后整份照发」的旧形态 SHALL 移除,
scout-merge 与 t2 收敛到同一硬界不变式。单条记录(scout-merge = 单个 scout 批 checkpoint 记录)
自身超预算时,SHALL 按**候选(candidate)粒度**确定性再切分为多个 ≤ 预算 shard(切分顺序稳定、
幂等重列结果一致);切分后单条候选仍超预算(scout-merge 的 `evidence_snippet`/描述类字段构成
病态大候选)时,SHALL 先做确定性散文瘦身投影(只截散文/证据 snippet 字段,`file`/`line`/`anchor`/
`category`/`kind`/`source` 等锚点与结构字段永不截,原始记录文件不回写),瘦身后仍超预算 →
退出码 2 fail-loud、**零物化零派发**,stderr 给出可操作 recipe(缩小 `--budget` 无意义,指认
病态记录路径)。

#### Scenario: Oversize scout batch record is split by candidate, never dispatched whole

- **WHEN** 某 scout 批 checkpoint 记录序列化后 > `--max-aggregate-bytes`,运行
  `plan_aggregate.py --node scout-merge --init-dir <init-dir> --budget <B> --materialize <dir>`
- **THEN** 该记录的候选按稳定顺序被切进多个 ≤ `<B>` 的 shard;`pending[]` 中不存在
  `oversize:true` 且整份超预算的待派发项;stderr/boundaries 披露该批的切分

#### Scenario: Atomic oversize candidate fails loud before any dispatch

- **WHEN** 候选粒度切分后某**单条候选**经散文瘦身投影仍 > 预算
- **THEN** `plan_aggregate.py --node scout-merge` 退出码 2,不物化任何 shard 输入、stdout 无
  pending;stderr 指认该候选来源记录路径

#### Scenario: Rollup eats only bounded shard summaries

- **WHEN** scout-merge map 各 shard 完成、编排器进入 rollup
- **THEN** rollup 请求仅吞各 shard 的结构化摘要 checkpoint(经绝对 `summary_paths` 逐字透传),
  NEVER 吞任何 shard 的原始输入记录;各 shard 摘要本身为有界结构(候选摘要,非记录体回显)
