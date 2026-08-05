# request-context-budget Specification

## Purpose

保证**每条 `mgh-*` 命令**(`/mgh-init`、`/mgh-sast`、`/mgh-sra`、`/mgh-srr`)流水线**每次大模型请求**
(编排器 + 各 stage subagent)的输入上下文 **≤ 可配置字节阈值**,在**确定性边界**强制——per-unit 输入
物化到文件由 subagent 自读、编排器待办壳 slim + 分页、超阈值单元确定性切分/标注、聚合节点分层归约或
回退。源于 `harden-mgh-init-context-budget`(根治 mgh-init 426KB 编排器上下文过大),泛化为四命令共用的
横切能力。预算单位 = **字节**(标准库可测、零依赖,承 R2;字节为 token 的保守上界)。

> **实现进度(分阶段交付)**:`/mgh-init` = 本 change(`harden-mgh-init-context-budget`,地基,端到端落地 +
> 修 bug);`/mgh-sast` / `/mgh-sra` / `/mgh-srr` = 后续 `harden-mgh-{sast,sra,srr}-context-budget` 各自采纳
> (照本 spec 机制 + init 参考实现,MODIFY 各命令 spec)。本 spec 是四命令统一的目标契约,实现跨 change 落地。

## Command fan-out surface(本能力绑定的脚本与节点)

四命令的扇出**同构**:确定性枚举脚本产出 lite `pending[]`(每项含绝对输出路径),subagent 需**完整
per-unit 记录**;若无 per-unit 物化,编排器被推向整份读多单元聚合(= 上下文爆炸的统一根因)。各命令的
枚举脚本与聚合节点(「见全部记录」的 stage)如下,本能力的机制对每行统一适用:

| 命令 | 扇出枚举脚本(产 `pending[]`) | 多单元聚合(编排器禁整份读) | 聚合 stage(跨单元,需有界/披露) |
|---|---|---|---|
| `/mgh-init` | `list_clusters.py`(T1)/`list_scout_batches.py`(scout)/`list_rule_jobs.py`(T3) | `clusters.json`/`controls_candidates.json`/`scout_plan.json`/`controls_inventory.json` | T2 `init-synthesis`/`init-scout-merge`/T4 `init-rules-consistency` |
| `/mgh-sast` | `list_chunks.py`(s4)/`list_verify_jobs.py`(s6) | `s3_chunks.json`/`s5_filtered.json`/`scope_manifest.json` | s1 scope / s2-s3 hypothesis 单上下文 stage |
| `/mgh-sra` | `prepare_augment.py`(a3 per-capability `pending[]`) | `change_context.json`(全 cap requirements + candidate_controls + memory) | a2 `sra-clarify`(单上下文扫全变更)/ a4 `sra-consistency`(全部 drafts) |
| `/mgh-srr` | `ingest_requirements.py`(产 sra-shape `pending[]`,复用 sra 引擎) | sra-shape `change_context.json` | 复用 sra a2/a4 + `render_report.py`(读全部定稿) |

per-unit 物化路径约定:`<命令输出目录>/inputs/<tier>/<unit>.input.json`(init:`.mgh-init/inputs/`、
sast:`security-scan/inputs/`、sra:`<change-root>/.mgh-sra/inputs/`、srr:`<out-dir>/inputs/`)。

## Requirements

### Requirement: Configurable request-context byte budgets

每条 `mgh-*` 命令(`/mgh-init`、`/mgh-sast`、`/mgh-sra`、`/mgh-srr`)SHALL 接受三个可配置字节预算 flag:
`--max-unit-bytes`(单 fan-out 单元物化输入上限,默认 192KB)、`--orch-budget-bytes`(编排器单次请求可见的
待办壳页上限,默认 64KB)、`--max-aggregate-bytes`(跨单元聚合 stage 输入上限,默认 256KB)。三者 SHALL
在**花 token 之前**的参数解析阶段被接受并落入各命令 `--help` 参数表(承 R5.1,`--help` 即契约面)。无效值
(负数/非整数)MUST 在解析期 fail-loud(退出码 2),不进入后续阶段。预算语义对四命令的扇出与聚合节点
**统一**适用。

#### Scenario: Budget flags are accepted across all four commands
- **WHEN** 任一 `mgh-*` 命令以 `--max-unit-bytes 131072 --orch-budget-bytes 32768` 运行
- **THEN** 三个 flag 被该命令 argparse 接受、出现在其 `--help`,流水线按给定预算运行

#### Scenario: Invalid budget fails before any LLM call
- **WHEN** 任一 `mgh-*` 命令传 `--max-unit-bytes -1`
- **THEN** 系统在参数解析期 fail-loud(退出码 2),不扫描、不调 LLM

#### Scenario: Defaults apply when flags omitted
- **WHEN** 任一 `mgh-*` 命令未给任一预算 flag
- **THEN** `--max-unit-bytes=192KB`/`--orch-budget-bytes=64KB`/`--max-aggregate-bytes=256KB` 默认生效

### Requirement: Per-unit inputs are materialized and bounded

每条 `mgh-*` 命令的每个扇出单元 SHALL 由其确定性枚举脚本物化完整输入记录到
`<命令输出目录>/inputs/<tier>/<unit>.input.json`(init:T1 cluster/scout batch/T3 category;sast:s4 chunk/s6
verify-job;sra/srr:per-capability;绝对路径、落运行域树内、幂等、`--resume` 复用),其字节数 SHALL ≤
`--max-unit-bytes`。枚举脚本 `pending[]` 每项 SHALL 携带该单元的 `input_path`(绝对)+ `bytes` + `oversize`。
subagent SHALL **读自己的 `input_path`**(一个有界单元);编排器 SHALL 向 subagent **透传 `input_path`**
而非内联传完整记录。超 `--max-unit-bytes` 的单元 SHALL 被确定性切分(init T1:按 evidence/usage-site 组切分
子单元;sast:超 `--big-file-bytes` 文件经 `chunk_sources` 切片;sra/srr:capability 不切分)或标
`oversize:true` + recipe。

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

### Requirement: Orchestrator context is bounded by a slim paged work-list

每条 `mgh-*` 命令的编排器 SHALL **NEVER** 整份读多单元聚合产物(见上方「Command fan-out surface」表第 3 列,
或任何 `inputs/` 外的整份扇出相关 JSON)进其请求上下文;SHALL 只装载枚举脚本产出的 **slim 待办壳**。枚举
脚本 SHALL 支持 `--offset`/`--limit` 分页;编排器 SHALL 按页迭代待办壳而非一次性装载。当某页序列化字节数 >
`--orch-budget-bytes` 时,枚举脚本 SHALL 自动收紧 `--limit`、在 stdout 报 `effective_limit` + `shrunk:true`
(stderr 告警),保证**编排器单次请求 ≤ `--orch-budget-bytes`**。待办壳 SHALL 不携带可变长记录负载(完整
记录下沉进 `input_path` 文件)。

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

### Requirement: Aggregate-stage inputs are bounded or disclosed

每条 `mgh-*` 命令的聚合 stage(init T2/merge/T4、sast scope、sra a2/a4、srr render)SHALL 上报其聚合
输入字节数(产出者 stdout 字段
或 `describe_artifact --count --field`),且 MUST 在聚合输入超过 `--max-aggregate-bytes` 时被处置(切分 /
标注 / 披露之一,**NEVER** 静默整份喂入)。**P0**:编排器 SHALL 建议 `--scope`/`--merge`(init/sast)或
分变更/分文档(sra/srr)并经命令 manifest `boundaries[]` + 人读报告披露该聚合未硬界(对标各命令既有
optional/advisory/non-fatal 语义)。**P1 目标**(后续 change)SHALL 经分层归约(per-unit summary 分组 →
逐组归约 → 归约再归约)使聚合请求亦 ≤ `--max-aggregate-bytes`。本 requirement 不声称 P0 已对聚合节点
提供硬阈值——P0 为「披露 + 回退」软边界。

#### Scenario: Aggregate input size is reported (generic)
- **WHEN** 任一聚合 stage 即将运行,编排器需知其输入大小
- **THEN** 该量可由产出者 stdout 字段或 `describe_artifact.py` 上报,编排器不 `py -c` 自算

#### Scenario: Oversize aggregate advises fallback and is disclosed
- **WHEN** 任一聚合 stage 输入 > `--max-aggregate-bytes`
- **THEN** 编排器建议对应的收窄/切分杠杆(`--scope`+`--merge` / 分变更 / `--split`),并在该命令 manifest
  `boundaries[]` 与人读报告披露「聚合超预算、未硬界、建议收窄」(P0 软边界)

### Requirement: No silent context overflow

任何 fan-out 单元、待办壳页、聚合 stage 输入**超其预算阈值**时,系统 SHALL 以**确定性切分 / 标注 / 披露**
之一处置,**NEVER** 把超阈值内容**整份静默**喂进任一 LLM 请求。所有阈值命中(`oversize`/`shrunk`/聚合超限)
SHALL 在 stderr(进度)与产物(各命令 manifest `boundaries[]`/人读报告)留痕,无静默截断(承 R5.4 无静默
截断精神)。

#### Scenario: Oversize unit is never passed whole (generic)
- **WHEN** 一个超 `--max-unit-bytes` 的 fan-out 单元经枚举
- **THEN** 它被切分或标 `oversize`,**不**以其原始整份形态进入任何 subagent 请求

#### Scenario: Budget hits are surfaced in artifacts (generic)
- **WHEN** 运行中发生任一 `oversize`/`shrunk`/聚合超限
- **THEN** 该命令 manifest `boundaries[]` 与人读报告记录之;用户可从产物复盘阈值命中,无静默

### Requirement: All orchestrator-to-subagent fan-out paths are absolute, in-tree, and verbatim

每条 `mgh-*` 命令的 fan-out 路径纪律(R5.3b)SHALL 覆盖编排器交给 subagent 的**所有**路径,不止 `input_path`/`checkpoint_path`/`rule_path`/`done_marker`/`failed_marker`。大文件**切片输出**路径(`chunk_sources.py --out`,init scout/T1、sast s4/deepdive 用)SHALL 同纪律:由确定性枚举脚本产出绝对 `slice_dir`/`slice_path`(落命令运行域受信子树,如 `<target>/.mgh-init/slices/<tier>/<unit>/`、`<target>/security-scan/slices/s4/<chunk>/`)、编排器逐字透传、subagent 恰好写该绝对路径。subagent NEVER 自拼路径(`<target>/<id>` 占位符)、NEVER 写相对路径、NEVER 写 cwd/系统临时目录(如 `…\AppData\Local\Temp\opencode\`、`/tmp/`)派生路径、NEVER 写运行域受信子树之外(含盘符根)。无切片的命令(sra/srr)空真满足。理由〔防 opencode 下 subagent 进程 cwd = 系统临时目录致切片落树外 → 回读触发越权 `Read` 提示 + 落 hook 受信子树自动放行〕。

#### Scenario: Slice output path follows the same discipline as checkpoint paths
- **WHEN** 一个 fan-out subunit 含需切片的大文件,编排器向 subagent 透传该 unit 的路径集合
- **THEN** 集合包含切片输出路径(绝对、落运行域受信子树),与 `checkpoint_path`/`input_path` 同形(均绝对、均树内、均逐字透传);subagent 写切片到该确切绝对路径并回读之

#### Scenario: No subagent writes a slice to a cwd/temp-derived or out-of-tree path
- **WHEN** subagent 进程 cwd 为系统临时目录(如 opencode 的 `…\AppData\Local\Temp\opencode\`),且需切片一个大文件
- **THEN** subagent 写切片到编排器透传的绝对 `slice_dir`/`slice_path`(运行域受信子树内),NEVER 写 `shards.json`(相对 cwd 默认)、NEVER 写 `…\Temp\…` 派生路径、NEVER 触发对临时目录的越权 `Read`

#### Scenario: Commands without slicing vacuously satisfy
- **WHEN** 一条命令的 fan-out subagent 不产生大文件切片(如 `/mgh-sra`、`/mgh-srr` 的 augment subagent)
- **THEN** 本要求空真满足(无切片路径需钉);该命令的既有 `input_path`/`checkpoint_path` 纪律不变
