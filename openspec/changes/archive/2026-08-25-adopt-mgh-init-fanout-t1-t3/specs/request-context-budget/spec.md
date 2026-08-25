# request-context-budget Delta: adopt-mgh-init-fanout-t1-t3

dispatcher 路径从 scout 步扩展到 t1/t3 步——同一条「slim paged work-list」requirement 的
消费面增量。

## MODIFIED Requirements

### Requirement: Orchestrator context is bounded by a slim paged work-list

每条 `mgh-*` 命令的编排器 SHALL **NEVER** 整份读多单元聚合产物(见上方「Command fan-out surface」表第 3 列,
或任何 `inputs/` 外的整份扇出相关 JSON)进其请求上下文;SHALL 只装载枚举脚本产出的 **slim 待办壳**。枚举
脚本 SHALL 支持 `--offset`/`--limit` 分页;编排器 SHALL 按页迭代待办壳而非一次性装载。当某页序列化字节数 >
`--orch-budget-bytes` 时,枚举脚本 SHALL 自动收紧 `--limit`、在 stdout 报 `effective_limit` + `shrunk:true`
(stderr 告警),保证**编排器单次请求 ≤ `--orch-budget-bytes`**。待办壳 SHALL 不携带可变长记录负载(完整
记录下沉进 `input_path` 文件)。

**dispatcher 路径增量**(mgh-init scout 首采,t1/t3 续采):当某 tier 的 fan-out 由确定性 dispatcher 叶脚本
(`fanout_runner.py`,见 `fanout-dispatch` 能力)驱动时,编排器驱动该 tier 的方式 SHALL 为一次
`Bash` 调用 dispatcher + `partial:true` 时重派同一命令——dispatcher 内部对全量 `pending[]` 按
`--orch-budget-bytes` 同源预算分页消费,编排器 NEVER 手动翻页、NEVER 逐次撰写 subagent 任务消息
(由固定模板 + 逐字字段填充构造)、NEVER 在波次边界发起 LLM 决策回合。手派路径(编排器翻页 + 逐单元
spawn)保留为宿主 CLI 不可用时的回退,其本 requirement 既有纪律不变。

**dispatcher 长跑增量**:编排器每次调用/重派 dispatcher 时 SHALL 传 per-call `timeout` 且该值 >
dispatcher 的 `--time-budget-ms`(软时限先于宿主硬杀触发;否则重派退化为「杀→查盘→重派→又被杀」
硬杀循环,每次硬杀浪费在飞波次)。dispatcher 运行态进度的查询路径 = 人直接读进度 sidecar 文件
(`<init-dir>/fanout_progress.<tier>.json`,见 `fanout-dispatch` 能力);编排器 SHALL NEVER 为查进度
发起 LLM 回合、NEVER 读 sidecar 进上下文。

#### Scenario: Orchestrator pages the work-list (generic)

- **WHEN** 任一 `mgh-*` 命令的待办单元众多,单页待办壳超过 `--orch-budget-bytes`
- **THEN** 编排器以 `--offset`/`--limit` 分多次取 `pending[]`,每次请求只见一页;枚举脚本报
  `effective_limit`/`shrunk:true`,编排器据此翻页

#### Scenario: Whole multi-unit aggregate is never loaded by the orchestrator

- **WHEN** 编排器需要某单元的完整记录以 spawn subagent
- **THEN** 它读 `pending[].input_path` 指向的**单单元** input 文件(由 subagent 自读),NEVER `Read`/
  `cat`/`py -c` 整份多单元聚合(`clusters.json`/`controls_inventory.json`/`scout_plan.json`/
  `s3_chunks.json`/`s5_filtered.json`/`change_context.json` 等)

#### Scenario: Slim envelope carries no variable-length payload

- **WHEN** 审阅任一 `mgh-*` 枚举脚本的 `pending[]` 元素结构
- **THEN** 壳含单元标识 + 计数/路径 + `input_path`/`checkpoint_path` 或 `draft_path`/`done_marker`/`bytes`/
  `oversize`,**不含**完整记录体(候选命中/requirements body/targets 文件正文/finding 详情等已下沉进
  `input_path` 文件)

#### Scenario: Dispatcher-driven tier keeps the orchestrator out of paging

- **WHEN** mgh-init 任一 dispatcher 采纳 tier(scout / t1 / t3)由 `fanout_runner.py` 驱动,pending
  单元数超过单页预算(如 500 单元)
- **THEN** 编排器对整个 tier 只发起一次 `Bash` 调用(+`partial:true` 时重派同一命令),不出现
  手动 `--offset`/`--limit` 翻页、不逐次撰写 subagent 任务消息;分页消费发生在 dispatcher 内部
  (同源 `--orch-budget-bytes` 预算)

#### Scenario: Re-dispatch carries per-call timeout above the soft deadline

- **WHEN** 编排器调用/重派 `fanout_runner.py --tier t1 --time-budget-ms 720000`
- **THEN** 该 `Bash` 调用带 per-call `timeout` > 720000ms(如宿主 900000ms);软时限先触发、
  dispatcher 干净早退,宿主硬杀 NEVER 发生

#### Scenario: Progress queries never burn orchestrator turns

- **WHEN** dispatcher 长跑期间有人想看进度
- **THEN** 进度可从 sidecar 文件 `fanout_progress.<tier>.json` 直接读取(零 token);编排器不为查进度
  发起 LLM 回合、不把 sidecar 读进上下文
