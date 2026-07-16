## MODIFIED Requirements

### Requirement: Inventory human-readable fields exclude tool-internal content

`controls_inventory.json` 的面向人读字段 SHALL 只描述目标项目的安全控制本身,且 MUST NOT
携带任何本工具内部信息。受约束的人读字段为 `description`、`usage`、`gaps`、`notes`、
`competing_clusters[].note`。被禁止的工具内部信息包括:本工具名、发现/归纳脚本名
(`discover_controls.py`、`chunk_sources.py`、`plan_scout.py`、`merge_scout.py`、
`list_clusters.py`、`assemble_rules.py` 等)、作为过程描述的流水线层级标签
(`T1`、`T2`、`T3`、`scout`)、内部路径(`.mgh-init/`、`checkpoints/`、`rules-parts/`),以及
任何「如何被本工具发现或归纳」的过程描述。结构/标识字段(`name`、`kind`、`category`、`role`、
`cluster_id`、`evidence`、`protects`、`entry_points`、`confidence`)与目标项目的 evidence 锚点、
文件路径 SHALL 保持原样。该约束 SHALL 同时写入 T1 `init-induct`、S3 `init-scout`、
T2 `init-synthesis` 的提示词,作为 shipped rules 纯净性的源头防线。结构字段 `source`
(取值 `regex`、`scout` 或 `codegraph`)SHALL 保留为结构标识,供 manifest 与审计使用,不视为人读正文泄漏。

`source: "codegraph"` 标记的候选来自「codegraph 解析器」(`init-resolve` stage,见「Resolve
unresolved controls via codegraph when an index is present」)对 `unresolved[]` 的解析,与
`regex`/`scout` 同为结构标识,适用相同纯净性规则;该值的出现 MUST NOT 使目标项目人读字段引入 codegraph
工具名或「经 codegraph 解析」之类过程描述。

#### Scenario: usage field describes target-project invocation only
- **WHEN** T1 归纳出 Spring 方法级安全控制,写入其 `usage` 字段
- **THEN** `usage` 以「开发者如何调用/注解」陈述目标项目用法,不含 `discover_controls.py` 或「经 regex 发现」等过程描述

#### Scenario: gaps field states effectiveness caveats only
- **WHEN** T1 发现参数化类型上 `@PreAuthorize` 的绕过形态,写入 `gaps`
- **THEN** `gaps` 描述该控制的有效性缺口(目标项目语义),不含 `chunk_sources.py`、`.mgh-init/checkpoints/` 等工具内部引用

#### Scenario: source field retained as structural tag
- **WHEN** 一条控制由 scout 子阶段发现
- **THEN** 其结构字段 `source: "scout"` 保留(供 manifest/审计);该值不是人读正文,不构成泄漏

#### Scenario: codegraph source tag carries no tool-internal prose
- **WHEN** 一条控制由 `init-resolve` 经 codegraph 解析 `unresolved[]` 得到,标 `source: "codegraph"`
- **THEN** 其结构字段 `source: "codegraph"` 保留(供 manifest/审计);其人读字段(`usage`/`gaps`)仅描述目标项目
  控制语义,**不**出现 `codegraph`、`init-resolve`、「经索引解析」等工具内部 / 过程描述

#### Scenario: T2 strips residual tool-internal references
- **WHEN** 某 T1 记录的人读字段不慎带入工具内部引用,T2 `init-synthesis` 综合该记录
- **THEN** T2 在写入 `controls_inventory.json` 前剥离这些引用,使最终 inventory 人读字段干净

## ADDED Requirements

### Requirement: Detect optional codegraph index and gate enrichment (fail-soft)

`/mgh-init` 编排器 SHALL 在起步段(步骤 0)以 Bash 检测目标项目是否具备 codegraph:`test -d
<target>/.codegraph` **且** `command -v codegraph`(二者皆真才视为可用)。检测结果 SHALL 作为
`codegraph=on|off` 信号逐字透传进后续 subagent task 输入。codegraph 富化 SHALL 默认 `auto`(可用即启用);
SHALL 提供 `--no-codegraph` opt-out(语义对齐既有 `--no-scout`),传该 flag 或检测为不可用时 MUST 完整
回退到引入 codegraph 前的行为(零 codegraph 调用)。检测 MUST 在「花 token 之前」完成,且 MUST NOT 引入
任何 `pip` 依赖或对 codegraph 的 Python `import`(codegraph 是宿主 MCP 工具 / 外部 CLI,非运行时依赖,
承 R2)。`--help` / 无 actionable 参数的零 token 早停行为保持不变。

#### Scenario: Index present enables enrichment
- **WHEN** 目标项目根存在 `.codegraph/` 且 PATH 上有 `codegraph`,未传 `--no-codegraph`
- **THEN** 编排器置 `codegraph=on` 并把该信号透传给 scout/induct/survey/resolve subagent

#### Scenario: Index absent falls back to legacy behavior
- **WHEN** 目标项目无 `.codegraph/`(或 PATH 无 `codegraph`)
- **THEN** 编排器置 `codegraph=off`,全流程不发起任何 codegraph 调用,行为等价于引入 codegraph 前

#### Scenario: Opt-out flag forces legacy behavior
- **WHEN** 运行 `mgh-init --no-codegraph`(即使 `.codegraph/` 存在)
- **THEN** codegraph 富化与 `init-resolve` stage 均不执行,行为等价于引入 codegraph 前

#### Scenario: Detection introduces no runtime dependency
- **WHEN** 对本变更新增/改动的任何 `.md` 或既有 `.py` 做 AST/文本扫描
- **THEN** 不存在 `import codegraph` 或对 codegraph 的 Python 运行时依赖;codegraph 仅经 MCP/Bash 消费

### Requirement: Optional codegraph context backend for scout/induct/survey subagents

当编排器信号 `codegraph=on` 时,`init-scout` / `init-induct` / `init-survey` subagent **SHALL 优先**用
MCP `codegraph_explore`(主)/ CLI `codegraph explore`(Bash,回退)取得目标符号的**逐字源码 + 调用路径 +
blast radius**,**仅**对 codegraph 未覆盖项(非索引语言、超 `--big-file-bytes` 的文件、索引未含项、或
codegraph `⚠️ pending sync` banner 点名的文件)回退 `Read`/`Glob`/`Grep`。该指引 SHALL 以**主谓**措辞
(「SHALL 优先 …,仅 … 回退 Read」)写入共享片段 `core/prompts/fragments/codegraph-hint.md`,由上述三份
stage 提示词在 `codegraph=on` 时引用;**MUST NOT** 用「you may」式可选措辞(规避 subagent 仍自行 Read、
使 codegraph 沦为纯开销的已知陷阱)。`codegraph=off` 时三份 stage 行为与引入 codegraph 前逐字一致。本要求
MUST NOT 改动任一确定性 `.py` 的契约(R5.3);codegraph 调用 SHALL 由 subagent(经 MCP)或编排器(经 Bash)
发起,NEVER 由 `.py` `import`/`subprocess` 发起。

#### Scenario: Scout uses codegraph for surgical context when on
- **WHEN** `codegraph=on` 且 scout subagent 处理一个含候选符号 `PermGuard` 的 batch 目标
- **THEN** subagent 先 `codegraph_explore "PermGuard"` 取其源码+调用方+blast radius,而非整文件 Read;仅对
  codegraph 未覆盖的文件回退 Read

#### Scenario: Read fallback for codegraph-uncovered files
- **WHEN** `codegraph=on` 但某目标文件是非索引语言(或超 `--big-file-bytes`,或被 codegraph `⚠️ pending` 点名)
- **THEN** subagent 对该文件回退 `Read`/`Glob`/`Grep`,不因 codegraph 未覆盖而丢覆盖

#### Scenario: Off behaves identically to pre-codegraph
- **WHEN** `codegraph=off` 运行 scout/induct/survey
- **THEN** 三份 stage 的工具使用与产出与引入 codegraph 前逐字一致(无 codegraph 调用)

#### Scenario: Hint steering is prescriptive not permissive
- **WHEN** 审阅 `core/prompts/fragments/codegraph-hint.md`
- **THEN** 其措辞为「codegraph 在场 SHALL 优先 codegraph_explore,仅 … 回退 Read」,而非「you may use codegraph」

#### Scenario: No deterministic-script contract change
- **WHEN** 本变更生效后审阅 `discover_controls.py` / `plan_scout.py` / `merge_scout.py` 的 CLI 与 I/O 契约
- **THEN** 与变更前逐字一致;codegraph 从不被 `.py` import 或 subprocess 调用

### Requirement: Resolve unresolved controls via codegraph when an index is present

`/mgh-init` SHALL 在 scout-merge 与 T1 之间插入一个**可选** `init-resolve` stage(仅当 `codegraph=on` 且
`unresolved[]` 非空时执行)。其输入为 `unresolved[]` 文件/控制清单——编排器 SHALL 经**合法结构出口**
`describe_artifact.py --field`(或该量产出者的 stdout 字段)取得该清单,**MUST NOT** `py -c`/`python -c` 内省
或 `Read` 整份大 JSON(承「Sanctioned artifact-inspection primitive」)。`init-resolve` subagent 用 codegraph
`callers`/`explore` + 框架路由解析,对每条原 `unresolved` 控制产出 Candidate-schema 子集锚点
(`file/line/category/kind/anchor/shape/evidence_snippet/confidence`),每条带 `source: "codegraph"` + 解析出的
调用路径,写入 `<target>/.mgh-init/resolved.json` + `checkpoints/resolve/.done`。该产物 SHALL **additive** 并入
候选集后走既有 `form_clusters`(簇形成逻辑不变;不 mutate regex/scout 候选)。每条 resolved 候选 MUST ground
在 codegraph 返回的真实符号 `file:line`;无解析结果的控制 SHALL 留在 `unresolved[]`(缩小不归零)。

该 stage SHALL **fail-soft**:codegraph off / `unresolved[]` 为空 / 清单过大超单 subagent 上下文预算 →
跳过整 stage + 在摘要披露(对标 `init-survey` 的 optional/advisory/non-fatal 语义),流水线不阻断、不报致命错。
命令壳两份(claude/opencode)MUST 在 flow 显式标注本 stage 的 optional/codegraph-gated/non-fatal 语义。
codegraph 自身静态分析上限(反射/DI 容器/运行时分派)产生的残留 MUST 计入 `unresolved_residual`(见
「Disclose codegraph enrichment coverage and residual blind spot」)。

#### Scenario: Framework-routed control resolved off the unresolved list
- **WHEN** 某鉴权控制仅经 Spring AOP pointcut 织入(文本图判 `unresolved`),且 `codegraph=on`
- **THEN** `init-resolve` 经 codegraph 解析出其 caller/route,产一条 `source: "codegraph"` 候选(含真实 `file:line`
  + 调用路径),从 `unresolved[]` 移出并入候选集

#### Scenario: Resolved candidate grounded in codegraph evidence
- **WHEN** `init-resolve` 产出一条 `source: "codegraph"` 候选
- **THEN** 其 `evidence_snippet`/`file:line` 来自 codegraph 返回的真实符号,且经 `init-resolve` 实际核验

#### Scenario: Unresolvable control stays unresolved
- **WHEN** codegraph 亦无法解析某控制(如纯运行时反射分派)
- **THEN** 该控制留在 `unresolved[]`,计入 `unresolved_residual`,不被伪造成 resolved

#### Scenario: Stage is skipped without breaking the run
- **WHEN** `codegraph=off`,或 `unresolved[]` 为空,或清单超上下文预算
- **THEN** 编排器跳过 `init-resolve`,不报致命错,T1 继续从 `clusters.json` 正常扇出,摘要披露该跳过

#### Scenario: Unresolved list obtained via sanctioned primitive
- **WHEN** 编排器进入 `init-resolve`,需要 `unresolved[]` 清单
- **THEN** 它经 `describe_artifact.py --field`(或产出者 stdout 字段)取得清单,**不** `py -c` 内省、**不** `Read`
  整份 `controls_candidates.json`

#### Scenario: Shell declares the optional/codegraph-gated semantics
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md` 的 flow
- **THEN** 两壳均在 scout-merge 与 T1 之间显式标注 `init-resolve` 为 optional + codegraph-gated + non-fatal +
  bounded(大 unresolved 跳过)

### Requirement: Disclose codegraph enrichment coverage and residual blind spot

`init_manifest.json` SHALL 增 `codegraph` 段,记录:`available`(检测到 `.codegraph/`+CLI 否)、`used`(本次
是否启用富化)、`resolved_count`(`init-resolve` 实际解析并入的候选数)、`unresolved_residual`(经 codegraph
解析后仍残留的 `unresolved[]` 条数)。`report.md` 与 `init_manifest.json` 的 `boundaries[]` SHALL 新增披露:
(1) codegraph 是否辅助、解析了多少、残留多少(**不声称全解析**);(2) codegraph 自身静态分析上限——反射/DI
容器/运行时分派,缩小但不归零 `unresolved[]`,解析结果为 LLM+codegraph 候选,需人工复核。既有三条诚实边界
(存在≠有效 / 文本调用图盲点 / 需人工复核)**保持不变**(文本图盲点仍真;codegraph 是其上的可选 resolver)。

#### Scenario: Manifest reports real codegraph coverage numbers
- **WHEN** 一次 `codegraph=on` 的运行完成
- **THEN** `init_manifest.json` 的 `codegraph` 段含 `available/used/resolved_count/unresolved_residual` 真实计数,
  且不出现「全解析」之类断言

#### Scenario: Off run reports not-used
- **WHEN** `codegraph=off` 运行完成
- **THEN** `init_manifest.json` 的 `codegraph.used` 为假,且不出现 codegraph 解析计数(resolved_count 为 0 或缺省)

#### Scenario: Residual blind spot is disclosed
- **WHEN** 审阅 `report.md` / `init_manifest.json` 的 `boundaries[]`
- **THEN** 其中明示「codegraph 静态分析上限致 `unresolved[]` 缩小不归零,残留需人工复核」,且既有三条诚实边界仍在
