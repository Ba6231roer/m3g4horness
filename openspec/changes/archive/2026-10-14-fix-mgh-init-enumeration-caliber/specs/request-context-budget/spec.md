# fix-mgh-init-enumeration-caliber — request-context-budget delta

## MODIFIED Requirements

### Requirement: Per-unit inputs are materialized and bounded

每条 `mgh-*` 命令的每个扇出单元 SHALL 由其确定性枚举脚本物化完整输入记录到
`<命令输出目录>/inputs/<tier>/<unit>.input.json`(init:T1 cluster/scout batch/T3 category;sast:s4 chunk/s6
verify-job;sra/srr:per-capability;绝对路径、落运行域树内、幂等、`--resume` 复用),其字节数 SHALL ≤
`--max-unit-bytes`。枚举脚本 `pending[]` 每项 SHALL 携带该单元的 `input_path`(绝对)+ `bytes` + `oversize`。
subagent SHALL **读自己的 `input_path`**(一个有界单元);编排器 SHALL 向 subagent **透传 `input_path`**
而非内联传完整记录。超 `--max-unit-bytes` 的单元 SHALL 被确定性切分(init T1:按 evidence/usage-site 组切分
子单元;sast:超 `--big-file-bytes` 文件经 `chunk_sources` 切片;sra/srr:capability 不切分)或标
`oversize:true` + recipe。

**done/failed 判定 = 正向 marker 路径计算(身份免疫)**:枚举脚本判定某单元是否已完成/终态失败
SHALL 为**正向计算**——遍历计划产物(`clusters.json`/`scout_plan.json` 等)中的 canonical 单元 id,
对每个 id 用与输入/检查点物化**同一编码函数**(文件名 sanitize + 长度截断)算出确切的
`.done`/`.failed` marker 路径,`is_file()` 即终态。done/failed 判定 SHALL **NEVER** 依赖
(i) checkpoint 记录体字段名与 canonical id 的一致性(记录体可能没有该字段、或字段名漂移),
(ii) 文件名 stem 反推(被截断的文件名 stem ≠ canonical id)。glob 反查磁盘 marker 保留 SHALL 但
降级为**孤儿审计**:磁盘存在 `.done`/`.failed` marker 而其派生路径不对应任何 canonical 单元 id
(或 canonical 单元判 pending 而其 marker 已存在——即判定不一致)→ stderr 告警列出,不改变
pending 语义。理由〔正向计算与物化同源,天然免疫文件名截断/记录体字段漂移;glob+stem 反查在
超长 id 截断场景把已完成单元永久判 pending → fan-out 无限重派(实测:32 个超长 id 簇已有
`.json`+`.json.done` 仍被反复派发,wave5 起每波 5 并发×30min 全部重烧,done=476/failed=5/
pending=32 恒定不收敛)〕。

**pending[] 广告路径与判定同源**:枚举脚本 `pending[]` 每项广告的 `checkpoint_path`/`done_marker`/
`failed_marker` 路径 SHALL 由**同一 forward 编码函数**产出(与 done/failed 判定、与输入物化三方同源),
NEVER 裸单元 id 拼接。理由〔广告路径(裸拼)与判定路径(编码)分叉时,派发器把 marker 写到广告
路径、枚举器按判定路径看——单元永远 pending,无限重派;这正是正向计算要消灭的缺陷类〕。

#### Scenario: Subagent reads its own bounded input file (generic)

- **WHEN** 任一 `mgh-*` 命令扇出一个单元,编排器 spawn 对应 stage subagent
- **THEN** 该 subagent 输入含一个绝对 `input_path`,指向该命令 `inputs/<tier>/<unit>.input.json`,其
  `bytes` ≤ `--max-unit-bytes`;subagent Read 该文件而非编排器内联传记录

#### Scenario: Oversize unit is sharded or flagged, never passed whole

- **WHEN** 某 fan-out 单元完整记录 `bytes` > `--max-unit-bytes`
- **THEN** 枚举脚本将其切分子单元(init T1 `::shard-<n>`、sast 走切片)或标 `oversize:true`(sra/srr
  capability、init T3 category)+ recipe;`pending[]` 不出现超阈值整单元

#### Scenario: Materialized inputs are resumable and idempotent

- **WHEN** 同一单元在 `--resume` 下再次枚举
- **THEN** 已物化的 `<unit>.input.json` 被幂等复用(按 unit 覆盖,不重复膨胀),`pending[]` 据各自
  `done_marker` 跳过已完成单元

#### Scenario: Overlong-id unit with existing done marker is terminal

- **WHEN** 某 T1 簇的 canonical `cluster_id` 超出文件名 stem 长度上限(其 `_safe_name` 编码产生
  截断形态文件名),且磁盘已有该单元的 `<encoded>.json` 记录 + `<encoded>.json.done` marker
- **THEN** `list_clusters.py` 将其判为 done(从 `pending[]` 消失),NEVER 依赖记录体字段值或
  截断 stem 反推;`--resume` 不再重派该单元

#### Scenario: 广告 marker 路径与判定路径同源(含特殊 id)

- **WHEN** 某 scout 批的 `batch_id` 含 `::` 或其编码文件名因超长被截断,该批被枚举进 `pending[]`
  并被派发器写 marker
- **THEN** `pending[]` 广告的 `checkpoint_path`/`done_marker`/`failed_marker` 与枚举器判定所用的
  forward 编码路径逐字符相同(派发器写的 = 判定看的);修复前广告侧裸 id 拼接、判定侧编码,
  该批 marker 永远「写得到、看不见」→ 无限重派

#### Scenario: Orphan markers are audited but never silently ignored

- **WHEN** 磁盘 checkpoint 目录存在 `.done`/`.failed` marker,其编码文件名不对应任何 canonical
  单元 id(改名后的遗留 run、手工产物)
- **THEN** 枚举脚本 stderr 告警列出孤儿 marker 文件名;stdout `pending[]` 语义不受影响;
  枚举不失败、不中断

#### Scenario: Record-body unit field is consistent but never load-bearing

- **WHEN** 某 checkpoint 记录体的身份字段(`cluster_id`/`batch_id`/新增 `unit`)与 canonical id
  一致或缺失
- **THEN** done/failed 判定结果不变(判定只由正向 marker 路径决定);记录体身份字段仅作诊断
  信息与孤儿审计对照

### Requirement: Orchestrator context is bounded by a slim paged work-list

每条 `mgh-*` 命令的编排器 SHALL **NEVER** 整份读多单元聚合产物(见上方「Command fan-out surface」表第 3 列,
或任何 `inputs/` 外的整份扇出相关 JSON)进其请求上下文;SHALL 只装载枚举脚本产出的 **slim 待办壳**。枚举
脚本 SHALL 支持 `--offset`/`--limit` 分页;编排器 SHALL 按页迭代待办壳而非一次性装载。当某页序列化字节数 >
`--orch-budget-bytes` 时,枚举脚本 SHALL 自动收紧 `--limit`、在 stdout 报 `effective_limit` + `shrunk:true`
(stderr 告警),保证**编排器单次请求 ≤ `--orch-budget-bytes`**。待办壳 SHALL 不携带可变长记录负载(完整
记录下沉进 `input_path` 文件)。**`--limit` 取值域 SHALL 为 `≥ 1` 或缺省(全部)**:`--limit < 1` SHALL
退出码 2 + recipe(空页 + `effective_limit=0` 会让按 `offset` 推进的编排器原地自旋;与 `--offset` 的
校验对称);本校验对本能力绑定的全部枚举脚本(list_clusters / list_scout_batches / list_rule_jobs /
plan_aggregate 两 node)统一适用。

**dispatcher 路径增量**(mgh-init scout 首采,t1/t2/t3 续采):当某 tier 的 fan-out 由确定性 dispatcher 叶脚本
(`fanout_runner.py`,见 `fanout-dispatch` 能力)驱动时,编排器驱动该 tier 的方式 SHALL 为一次
`Bash` 调用 dispatcher + `partial:true` 时重派同一命令——dispatcher 内部对全量 `pending[]` 按
`--orch-budget-bytes` 同源预算分页消费,编排器 NEVER 手动翻页、NEVER 逐次撰写 subagent 任务消息
(由固定模板 + 逐字字段填充构造)、NEVER 在波次边界发起 LLM 决策回合。T2 map 阶段同样适用:编排器先
`plan_aggregate.py --node t2` 判 `needs_reduce`,仅当 `needs_reduce=true` 时一次 `Bash` 调
`fanout_runner.py --tier t2`,map 全 `.done` 后单一 rollup subagent 按 rollup manifest(见「Init
aggregate node dispatched shards are hard-bounded」——stdout 不再携带全量 `summary_paths` 数组)吞各
shard 摘要。手派路径(编排器翻页 + 逐单元 spawn)保留为宿主 CLI 不可用时的回退,其本 requirement
既有纪律不变。

**dispatcher 长跑增量**:编排器每次调用/重派 dispatcher 时 SHALL 传 per-call `timeout` 且该值 >
dispatcher 的 `--time-budget-ms`(软时限先于宿主硬杀触发;否则重派退化为「杀→查盘→重派→又被杀」
硬杀循环,每次硬杀浪费在飞波次)。dispatcher 运行态进度的查询路径 = 人直接读进度 sidecar 文件
(`<init-dir>/fanout_progress.<tier>.json`,见 `fanout-dispatch` 能力);编排器 SHALL NEVER 为查进度
发起 LLM 回合、NEVER 读 sidecar 进上下文。

#### Scenario: Orchestrator pages the work-list (generic)

- **WHEN** 任一 `mgh-*` 命令的待办单元众多,单页待办壳超过 `--orch-budget-bytes`
- **THEN** 编排器以 `--offset`/`--limit` 分多次取 `pending[]`,每次请求只见一页;枚举脚本报
  `effective_limit`/`shrunk:true`,编排器据此翻页

#### Scenario: `--limit < 1` 被统一拒识

- **WHEN** 对 `list_clusters.py` / `list_scout_batches.py` / `list_rule_jobs.py` /
  `plan_aggregate.py --node <t2|scout-merge>` 任一传 `--limit 0`(或负数)
- **THEN** 该脚本退出码 2 + stderr recipe(合法值 ≥ 1 或缺省);NEVER 产出空页 + `effective_limit=0`
  的「成功」输出把按 `offset` 推进的编排器留成原地自旋

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

- **WHEN** mgh-init 任一 dispatcher 采纳 tier(scout / t1 / t2 / t3)由 `fanout_runner.py` 驱动,pending
  单元数超过单页预算(如 500 单元)
- **THEN** 编排器对整个 tier 只发起一次 `Bash` 调用(+`partial:true` 时重派同一命令),不出现
  手动 `--offset`/`--limit` 翻页、不逐次撰写 subagent 任务消息;分页消费发生在 dispatcher 内部
  (同源 `--orch-budget-bytes` 预算)

#### Scenario: T2 map phase keeps the orchestrator out of manual paging

- **WHEN** T2 map 阶段 `needs_reduce=true`(K 个 category shard 超单页预算)
- **THEN** 编排器对 map 阶段只发起一次 `Bash` 调 `fanout_runner.py --tier t2`(+`partial:true` 重派),
  不手动 `--offset`/`--limit` 翻页、不逐 shard 撰写 partial-synthesis 任务消息;map 全 `.done` 后
  rollup subagent 经 rollup manifest(绝对路径逐字透传)取得全量 `summary_paths`,NEVER 由
  stdout 直接携带全量数组

#### Scenario: Re-dispatch carries per-call timeout above the soft deadline

- **WHEN** 编排器调用/重派 `fanout_runner.py --tier t1 --time-budget-ms 720000`
- **THEN** 该 `Bash` 调用带 per-call `timeout` > 720000ms(如宿主 900000ms);软时限先触发、
  dispatcher 干净早退,宿主硬杀 NEVER 发生

#### Scenario: Progress queries never burn orchestrator turns

- **WHEN** dispatcher 长跑期间有人想看进度
- **THEN** 进度可从 sidecar 文件 `fanout_progress.<tier>.json` 直接读取(零 token);编排器不为查进度
  发起 LLM 回合、不把 sidecar 读进上下文

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

**预算按物化口径计量(两节点统一)**:shard 的预算判定(分桶、瘦身触发、瘦身收敛)SHALL 以
**物化口径**字节为准——与落盘文件同一序列化形态(信封 + 缩进 + CRLF)的 `_materialized_bytes`
度量;scout-merge 已然,t2 SHALL 收敛到同一度量(修复前 t2 按紧凑序列化计量,实测 96KB 预算
物化 121KB ≈ 1.23×,凡触发 part 切分必超)。`pending[].bytes` SHALL 回填物化文件的
`st_size`(修复前按紧凑值低报)。「已派发 shard 落盘文件 ≤ 预算」SHALL 有回归断言。

**rollup manifest(全量摘要路径不进 stdout)**:`needs_reduce` 时脚本 SHALL 物化
`<shard_cp_dir>/rollup_manifest.json`(原子写、幂等——body 含全量 shard 摘要路径
`summary_paths[]`、`output`、`done_marker`);stdout `rollup` 段 SHALL 携带
`summary_paths_manifest`(manifest 绝对路径)与 `shards` 计数,**NEVER 携带 `summary_paths`
数组**(1000 shard ≈ 100KB 会击穿 `--orch-budget-bytes` 的单次回复承诺;单上下文路径
`needs_reduce:false` 不物化 manifest、stdout 形态不变)。rollup subagent SHALL 先 Read manifest
取得全量路径再逐份吞摘要(编排器逐字透传 manifest 路径,NEVER 自读 manifest 内容)。

#### Scenario: Oversize scout batch record is split by candidate, never dispatched whole

- **WHEN** 某 scout 批 checkpoint 记录序列化后 > `--max-aggregate-bytes`,运行
  `plan_aggregate.py --node scout-merge --init-dir <init-dir> --budget <B> --materialize <dir>`
- **THEN** 该记录的候选按稳定顺序被切进多个 ≤ `<B>` 的 shard;`pending[]` 中不存在
  `oversize:true` 且整份超预算的待派发项;stderr/boundaries 披露该批的切分

#### Scenario: Atomic oversize candidate fails loud before any dispatch

- **WHEN** 候选粒度切分后某**单条候选**经散文瘦身投影仍 > 预算
- **THEN** `plan_aggregate.py --node scout-merge` 退出码 2,不物化任何 shard 输入、stdout 无
  pending;stderr 指认该候选来源记录路径

#### Scenario: t2 shard 落盘文件 ≤ 预算(物化口径)

- **WHEN** `plan_aggregate.py --node t2 --budget 98304 --materialize <dir>` 对超预算输入运行,
  产出若干被派发 shard
- **THEN** 每个被派发 shard 的**落盘 input 文件** `st_size` ≤ 98304(修复前按紧凑口径分桶,
  实测可物化 ~121KB);`pending[].bytes` = 该文件 `st_size`(修复前按紧凑值低报)

#### Scenario: rollup manifest 承载全量摘要路径

- **WHEN** `plan_aggregate.py --node t2`(或 scout-merge)`needs_reduce` 运行,产出 1000 个 shard
- **THEN** stdout `rollup` 段为 `{summary_paths_manifest: <abs>, output: <abs>, done_marker: <abs>}`
  (无 `summary_paths` 数组),整份 stdout ≤ `--orch-budget-bytes`;`rollup_manifest.json` 含全量
  1000 条摘要路径;rollup subagent 先 Read manifest 再逐份吞摘要(NEVER 由 stdout/任务消息直载
  1000 条路径);`needs_reduce:false` 的单上下文路径 stdout 形态与既有逐字节一致

#### Scenario: Rollup eats only bounded shard summaries

- **WHEN** scout-merge map 各 shard 完成、编排器进入 rollup
- **THEN** rollup 请求仅吞各 shard 的结构化摘要 checkpoint(经 manifest 内绝对 `summary_paths`
  逐字定位),NEVER 吞任何 shard 的原始输入记录;各 shard 摘要本身为有界结构(候选摘要,非记录体回显)
