## Context

四条 `mgh-*` 命令的扇出**同构**:确定性枚举脚本产出 *lite* `pending[]`,stage subagent 需**完整 per-unit
记录**;sanctioned 出口无「按单元取完整记录」原语 → 编排器整份读多单元聚合 = 上下文爆炸的**统一根因**,叠加
全流水线无阈值。命令映射(横切 spec `request-context-budget` 详载):

| 命令 | 枚举脚本 | 多单元聚合(禁整份读) | 聚合 stage |
|---|---|---|---|
| `/mgh-init` **← 本 change 实现** | `list_clusters`(T1)/`list_scout_batches`(scout)/`list_rule_jobs`(T3) | `clusters.json`/`controls_candidates.json`/`scout_plan.json`/`controls_inventory.json` | T2/`init-scout-merge`/T4 |
| `/mgh-sast`(后续) | `list_chunks`(s4)/`list_verify_jobs`(s6) | `s3_chunks.json`/`s5_filtered.json` | s1 scope / s2-s3 |
| `/mgh-sra`(后续) | `prepare_augment`(a3) | `change_context.json` | a2/a4 |
| `/mgh-srr`(后续) | `ingest_requirements`(复用 sra 引擎) | sra-shape `change_context.json` | render + sra a2/a4 |

本 change = **地基**:立横切 `request-context-budget` spec + 物化契约 + hook recipe + **init 端到端参考实现**
(同时修本次 bug)。sast/sra/srr 是**结构相同的独立叶子**,由后续 `harden-mgh-{sast,sra,srr}-context-budget`
照本 change 的 init 模式采纳(各为精简 change,只读引用本 spec,无跨命令代码依赖)。

observed 失败:opencode DeepSeek-V4-Flash `[ReadAllBytes(".mgh-init/t1_pending.json")]` → 426KB 进编排器上下文。

约束(承 AGENTS.md):R2 零依赖;R5.2 编排器 = 宿主 agent、物化器是叶脚本;R5.3a/b;R5.5;R5.9;R5.10。

## Goals / Non-Goals

**Goals:**
- **init 端到端根治编排器上下文过大**(修 bug):编排器 NEVER 整份读多单元聚合;只装 slim 分页待办壳
  (≤ `--orch-budget-bytes`)。
- **init 每个扇出 subagent 收到有界输入**:读自己的 `input_path`(≤ `--max-unit-bytes`),编排器只透传路径。
- **立横切地基**: `request-context-budget` spec + 物化契约 + hook recipe + 可复用的 init 参考实现,
  供 sast/sra/srr 后续照搬。
- **可配置阈值,确定性强制**:`--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes`;超阈值切分/标注/披露。

**Non-Goals:**
- **不实现 sast/sra/srr**(后续 adoption change;本 change 只立地基 + init)。
- 不改既有产物**产出** schema(只新增 `input_path`/`bytes`/`oversize` + `inputs/` 目录)。
- P0 不重写 init 聚合 stage 为 map-reduce(分层归约 = P1)。
- 不引入第三方 token 计数器(预算单位 = 字节,承 R2)。

## Decisions

### D1 — per-unit **输入物化**闭合契约缺口(输出 `checkpoint_path` 的镜像)

每个 init 扇出单元(T1 cluster / scout batch / T3 category)的**完整输入记录**由确定性枚举脚本物化到
`<target>/.mgh-init/inputs/<tier>/<unit>.input.json`(绝对、落运行域树、幂等、`--resume` 复用)。`pending[]`
每项增 `input_path` + `bytes` + `oversize`;subagent **读自己的 `input_path`**,编排器**只透传路径**。**为何唯一
根治**:要同时满足「记录不进编排器上下文」+「subagent 输入有界」,记录必须落到按单元、有界、由 subagent 自读的
文件。内联传 → 编排器持全部记录(当前 bug);让 subagent 回查聚合 → bloat 移到 subagent 且弱模型仍整份读。
此模式即 sast/sra/srr 后续照搬的**参考实现**。

### D2 — 物化**折进各 `list_*`**(`--materialize <dir>`),单一枚举原语

`list_clusters`/`list_scout_batches`/`list_rule_jobs` 各增 `--materialize <dir>`:读源产物时顺便把每单元完整输入
写到 `<dir>/<unit>.input.json` + 报 `input_path`。无 `--materialize` 时行为不变(向后兼容)。**为何不单开
`materialize_units.py`**:违反 R5.3b「扇出即脚本枚举」;各 `list_*` 已读源产物,折进最自然。sast/sra/srr 后续
各折进自己的枚举脚本(同模式)。

### D3 — slim 待办壳 + `--offset/--limit` 分页

`pending[]` 壳剔除可变长负载(`list_clusters` 去 `evidence_files[]`,下沉进 input 文件),保留单元标识 + 计数 +
路径 + `bytes`/`oversize`。三脚本增 `--offset/--limit`;编排器按页迭代,NEVER 一次性装载。

### D4 — per-unit 字节预算 `--max-unit-bytes`(默认 192KB),按 tier 差异处置 oversize

- **T1 簇**:按 `evidence_files`/`usage_sites` 组切 `<cid>::shard-<n>` 子单元。
- **scout 批**:超 `--big-file-bytes` 文件强制 `needs_slice` 走 `chunk_sources`(`--max-unit-bytes` 与 `--batch-bytes` 取 min)。
- **T3 category**:标 `oversize:true` + recipe(`--scope`+`--merge`),**不**切分(rulewriter 需整 category 视图)。

NEVER 静默把超阈值单元整份喂进请求。

### D5 — 编排器预算 `--orch-budget-bytes`(默认 64KB)自动收紧分页

三脚本在 `--limit` 给定下,若该页序列化字节 > `--orch-budget-bytes`,SHALL 自动缩 `--limit`、stdout 报
`effective_limit` + `shrunk:true`(stderr 告警)。

### D6 — init 聚合 stage 分阶段有界

P0:T2 `init-synthesis`/`init-scout-merge`/T4 聚合输入上报 `bytes`(产出者 stdout 或 `describe_artifact --count
--field`);超 `--max-aggregate-bytes`(256KB)→ 编排器建议 `--scope`+`--merge`,并在 `init_manifest.json::boundaries[]`
+ `report.md` 披露(对标 init-survey optional/advisory/non-fatal 语义)。P1(后续 change):分层归约。

### D7 — hook + recipe 为纵深防御,结构性修复为主

`block_adhoc_scripts` recipe(双端、四运行域 `MGH_{INIT,SAST,SAST,SRA,SRR}_ACTIVE`)增「整份读多单元聚合 → 指向
`input_path`/`describe_artifact`」。**本 change 一次改 recipe 覆盖四运行域**,sast/sra/srr 后续直接复用(无需再改
hook)。承既有可靠性边界:opencode env 仅启动时已就绪才激活守卫;未激活时由命令壳纪律明线 + 各 producer `--check`
兜底。结构性修复(D1–D5)是主 lever。

### D8 — 契约变更与迁移(向后兼容)

additive:`input_path`/`bytes`/`oversize`/`effective_limit`/`shrunk` 新字段;新 flag additive。**envelope 形态变更**:
`list_clusters` 壳移除 `evidence_files[]`(下沉进 input 文件)。仓内无外部消费者(仅编排器 + subagent,随本 change
同步改)。各 `list_*`/命令壳/提示词 bump 版本号(承 R5.8)。`--resume` 复用 `inputs/`(按 unit 幂等覆盖)。**spec
纠正**:T3 枚举归 `rules-emission`(此前 control-discovery 误置 ADDED,本 change 改 rules-emission MODIFIED)。

## Risks / Trade-offs

- **[物化写 N 个 input 文件(磁盘)]** → 落 `<target>/.mgh-init/inputs/`(随 `.mgh-init/` gitignore);按 unit 幂等,
  `--resume` 复用;总量 ≤ 源产物大小(无放大)。
- **[oversize 簇切分改变 cluster_id 粒度]** → 子单元 id 确定性派生(`<cid>::shard-<n>`);T2 仍见全部子单元
  (additive);dedup 在 candidate 层不受影响。
- **[弱模型仍可能 cat 单个 input 文件]** → input 文件本身 ≤ `--max-unit-bytes`(已 bound),即便整读也 ≤ 预算。
- **[init 聚合 stage P0 仍无硬界]** → 披露 + `--scope`/`--merge` 回退;P1 闭合。不声称 P0 已全有界。
- **[地基先行 → sast/sra/srr 阻塞]** → 本 change 必须先落地;但本 change 本就是最高优先级(修 bug),串行无损失。
- **[字节 ≠ token]** → 字节为保守上界;不引入 tokenizer(承 R2)。

## Migration Plan

1. 三 `list_*` 脚本加 `--materialize`/`--offset`/`--limit`/`--max-unit-bytes`/`--orch-budget-bytes` + 新字段
   (保留无 `--materialize` 旧路径,向后兼容)。
2. 三 stage 提示词(`init-induct`/`init-scout`/`init-rulewriter`)输入改「读 `input_path`」;聚合 stage 提示词加
   `bytes` 披露护栏。
3. 两份命令壳:纪律段 + flow(物化 → 分页迭代 → 透传 input_path)+ flag 表 + disclose。
4. `block_adhoc_scripts.{py,ts}` recipe + `tools/check_contracts.py` init flag 覆盖。
5. 契约:`core/contracts/init/unit-inputs.md`(新);`request-context-budget` spec 含命令映射表(标 sast/sra/srr 后续)。
6. 单测:`list_*` 物化/分页/`bytes`/`oversize`/切分;回归:整份读多单元聚合应被 hook 拦。
7. 版本 bump;`install.sh` 共定位自检(无新脚本名)。
8. **回滚**:纯 additive(除 `evidence_files[]` 下沉);回滚 = 还原三脚本/提示词/命令壳,`inputs/` 可删,既有产物
   路径与 schema 不变。

## Open Questions

- `--max-unit-bytes` 默认 192KB(对齐 `--big-file-bytes` 200KB)是否合适?(倾向:独立 flag;实测后微调。)
- T3 category oversize 真不需切分?大 inventory 单 category 能多大?(倾向:P0 只 flag + recipe。)
- `--orch-budget-bytes` 默认 64KB 对弱模型窗口是否过紧?(可配置;默认取保守值。)
- sast/sra/srr adoption 是否各独立默认 `--max-unit-bytes`?(地基定统一默认,adoption 可实测后各自调。)
