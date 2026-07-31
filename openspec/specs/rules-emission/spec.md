# rules-emission Specification

## Purpose
TBD - created by archiving change add-mgh-init. Update Purpose after archive.
## Requirements
### Requirement: Format-strict rules emission selected by --format

`init-rulewriter` SHALL 按 `--format`(**必选**)渲染且仅渲染对应 Agent 的 rules 结构。
Claude Code(`--format claude`)与 opencode(`--format opencode`)的 rules 结构**根本
不同**,MUST NOT 混用或互相套用;错误结构 Agent 不会加载 = 功能失效。

#### Scenario: Claude format emits .claude/rules only
- **WHEN** 用户运行 `mgh-init --format claude`
- **THEN** 产出 `<target>/.claude/rules/security-*.md`,且不产出 `AGENTS.md`

#### Scenario: opencode format emits root AGENTS.md only
- **WHEN** 用户运行 `mgh-init --format opencode`
- **THEN** 产出 `<target>/AGENTS.md`(根目录),且不产出 `.claude/rules/`

### Requirement: Claude Code rules use path-scoped .claude/rules/

每个 `category` SHALL 产出一个 `.claude/rules/security-<category>.md`,文件头含 YAML
frontmatter `paths:`(由该类控制的 `protects` glob 派生),使 rule 仅在编辑相关路径时
自动加载。规则正文 SHALL 指向**具体 `file`/`class`/`method`** 锚点(可索引,非泛泛而谈),
并给出「复用此封装、勿重新发明」的明确 usage。

#### Scenario: Rule file carries valid paths frontmatter
- **WHEN** 产出 `security-authorization.md`
- **THEN** 文件头 frontmatter 含非空 `paths:` 列表,字段格式可被 Claude Code 解析

#### Scenario: Rule references concrete anchors
- **WHEN** 一条 rule 描述某鉴权封装
- **THEN** 正文含 `file:class:method` 或 `file:line` 锚点,不粘贴超过 3–5 行代码(R3)

### Requirement: opencode rules use single root AGENTS.md

`--format opencode` SHALL 产出一个项目根 `AGENTS.md`,其安全规则块为**简洁索引**(category 清单 +
`@<rules-dir>/<cat>.md` 引用 + 「按需 lazy 加载」强制指令),规则正文 SHALL 拆入**每 category 一个独立
详述文件** `<target>/docs/security-controls/<category>.md`(默认;`--rules-dir` 可覆盖)。opencode 启动整份
`AGENTS.md` 进根上下文,故索引块 SHALL 保持简洁(每 category 一行级);详述文件 SHALL **仅在 agent 任务
涉及对应领域时经 Read 按需加载**(逐字对齐 opencode 文档 "Manual Instructions in AGENTS.md" lazy 范式)。
MUST NOT 写 `.opencode/AGENTS.md`(opencode 不加载该位置,issue #11454);MUST NOT 把详述文件列入
`opencode.json` `instructions`(该字段 eager 全量并入,不省上下文,违本变更目标)。opencode 不支持
path-scoping,lazy 由索引块的语义 directive 驱动(非路径自动触发)。

#### Scenario: Concise index block plus per-category detail files

- **WHEN** `--format opencode` 运行完成
- **THEN** 存在 `<target>/AGENTS.md`,其 `<!-- security-controls:begin --> … :end -->` 受管块为**索引**
  (各 category 一行 + `@docs/security-controls/<cat>.md` 引用 + lazy 指令),且存在
  `<target>/docs/security-controls/<cat>.md` 详述文件(每实现 category 一个);不存在 `.opencode/AGENTS.md`,
  详述文件未列入 `opencode.json` `instructions`

#### Scenario: Index references only categories with emitted detail files

- **WHEN** category `rate-limiting` 在目标项目无任何源码锚点(T3 不写其详述文件)
- **THEN** 索引块**不**含 `rate-limiting` 行(无孤儿引用);`docs/security-controls/rate-limiting.md` 不存在

#### Scenario: Index entries derive display name from detail-file heading

- **WHEN** `docs/security-controls/authentication.md` 首行为 `# 认证 安全控制`
- **THEN** 索引块对应行展示名为「认证」(取首条 `#` 标题);该文件无 `#` 标题时回退 filename stem `authentication`

### Requirement: Non-destructive, idempotent emission

写入既有目标文件时 SHALL 以**中性哨兵**标记的**受管块**追加或原地替换,MUST NOT 覆盖用户手写内容。
opencode(`--format opencode`)SHALL 使用**单个**受管块 `<!-- security-controls:begin --> …
<!-- security-controls:end -->`,该块现在承载**索引**(非全量规则正文;正文在详述文件),由确定性脚本
`assemble_rules.py` 从 `<rules-dir>/*.md` 现实快照生成(见「Deterministic assembly and purity lint」)。
哨兵标记 MUST 是中性的,`MUST NOT` 携带本工具名(`mgh-init`/`megahorness` 等)。详述文件
`docs/security-controls/<category>.md` 每 category 一个独立文件,幂等=整文件覆写(对齐 claude)。
重复运行同一 `--format` MUST 幂等:仅替换受管块(opencode,内容为最新索引)/ 对应详述文件,其余内容不变。
`assemble_rules.py` 首次运行 SHALL 一次性清扫并迁移旧版 `<!-- mgh-init:begin` 开头的受管块,避免孤儿重复;
**复用同哨兵**使旧版「全量内联块」幂等替换为新「索引块」(零额外迁移逻辑)。

#### Scenario: Existing user content preserved

- **WHEN** 目标已有用户手写的 `AGENTS.md` / `docs/` 内容
- **THEN** 用户内容原样保留,init 仅替换自己的受管块(opencode,现为索引)/ 对应 category 详述文件,其余不动

#### Scenario: Re-run is idempotent

- **WHEN** 对同一目标连续两次运行 `mgh-init --format opencode`
- **THEN** `AGENTS.md` 的 `<!-- security-controls:begin --> … :end -->` 受管块只出现一次且为最新索引
  (反映当前 `docs/security-controls/` 快照),非受管部分无变化;详述文件被最新内容覆写

#### Scenario: Neutral sentinel carries no tool name

- **WHEN** `--format opencode` 产出 `AGENTS.md` 受管块
- **THEN** 哨兵标记为 `<!-- security-controls:begin -->` / `<!-- security-controls:end -->`,不含 `mgh-init`、
  `megahorness` 或任何本工具标识

#### Scenario: Legacy branded blocks migrated on first run

- **WHEN** 目标 `AGENTS.md` 含旧版 `<!-- mgh-init:begin:audit-logging --> … <!-- mgh-init:end:audit-logging -->` 块,以新版重跑
- **THEN** `assemble_rules.py` 清除旧品牌块、写入新中性索引块,用户其余内容不动,stdout 摘要 `migrated_legacy_blocks` 记被迁移块数

#### Scenario: Old inline block migrated to index block via reused sentinel

- **WHEN** 目标 `AGENTS.md` 含旧版「全量规则内联」的 `<!-- security-controls:begin --> … :end -->` 块(本变更前产物),以新版重跑
- **THEN** `assemble_rules.py` 把该同哨兵块替换为索引块(规则正文已由 T3 重生为 `docs/security-controls/<cat>.md`),用户其余内容不动

### Requirement: Emission validation and manifest

落盘前 SHALL 校验产物符合所选格式(claude:`paths:` frontmatter 合法、文件位于
`.claude/rules/`;opencode:单文件位于根)。校验失败 MUST 报错并拒绝产出「看似成功」的
rules。运行末尾 SHALL 写 `init_manifest.json`,记录 `format`、控制数、provenance、
`unresolved[]` 与三条诚实边界声明。

#### Scenario: Invalid claude frontmatter rejected
- **WHEN** 生成的某 `.claude/rules/*.md` 的 `paths:` frontmatter 非法
- **THEN** 系统报错指明文件,不产出「成功」rules

#### Scenario: Manifest records format and provenance
- **WHEN** 一次运行完成
- **THEN** `init_manifest.json` 含 `format`、控制计数、provenance 与边界声明字段

### Requirement: 面向人读的非代码内容用简体中文

工具所有面向人读的非代码输出 SHALL 用简体中文撰写:rules 正文、T1/T2 的
`description`/`usage`/`gaps`、`report.md`、`init_manifest.json` 的 `boundaries[]`/文案、
`competing_clusters[].note`。代码、文件路径、`file:class:method` 锚点、标识符、`name`/枚举值、
YAML `paths:` frontmatter 字段 MUST 保持原样(英文/符号不变)。

#### Scenario: Rules body in Chinese, anchors untouched
- **WHEN** T3 产出 claude `.claude/rules/security-authorization.md`
- **THEN** 规则正文(描述/用法/注意)为简体中文,而 `paths:` frontmatter、文件路径、`WebSecurityConfig.java::filterChain` 锚点保持原样

#### Scenario: Manifest boundaries in Chinese
- **WHEN** 写入 `init_manifest.json` 的 `boundaries[]`
- **THEN** 三条边界声明为简体中文;键名、路径、计数保持原样

### Requirement: Shipped rules exclude tool-internal content

shipped rules(opencode 受管块正文 / claude `.claude/rules/security-*.md` 正文)SHALL 只描述
**目标项目**的安全控制。规则正文(描述 / 用法 / 注意 / 缺口)MUST NOT 出现本工具内部信息,
包括:本工具名(`mgh-init` / `megahorness` / `mgh-core`)、脚本名(`discover_controls.py` /
`chunk_sources.py` / `plan_scout.py` / `merge_scout.py` / `list_clusters.py` / `assemble_rules.py` /
`emit_sarif.py` / `prefilter.py` / `expand_scope.py` / `dedup.py`)、流水线层级标签
(`T1` / `T2` / `T3` / `scout` 作为生成过程描述)、内部路径(`.mgh-init/` / `checkpoints/`)、以及任何「如何被本工具发现/归纳」的过程描述。目标项目自身的代码、文件路径、
`file:class:method` 锚点、标识符 SHALL 保持原样(此非工具内部信息)。该约束 SHALL 同时写入
T1 `init-induct` / S3 `init-scout` / T2 `init-synthesis` / T3 `init-rulewriter` 的提示词
(recipe 式:该写什么 + `NEVER` 硬边界,无豁免子句,承 R5.5①②③),并由确定性 lint 兜底
(见「Deterministic assembly and purity lint」)。

#### Scenario: Rule body free of script names

- **WHEN** T3 产出某 category 的规则正文
- **THEN** 正文不含 `discover_controls.py`、`chunk_sources.py` 等本工具脚本 basename

#### Scenario: Rule body free of pipeline tier descriptions

- **WHEN** 一条规则描述某鉴权封装
- **THEN** 正文以目标项目语言陈述(是什么 / 怎么复用 / 锚点 / 缺口),不含「由 T2 归纳」「经 scout 发现」「mgh-init 流水线」等过程描述

#### Scenario: Target-project anchors preserved

- **WHEN** 规则引用某控制
- **THEN** `src/.../WebSecurityConfig.java::filterChain` 等目标项目锚点原样保留(锚点是目标项目信息,非工具内部信息)

### Requirement: Deterministic assembly and purity lint

opencode 规则 SHALL 经确定性叶脚本 `core/scripts/assemble_rules.py` 装配:T3 每 category 直写独立详述文件
`<target>/docs/security-controls/<category>.md`(默认;`--rules-dir` 可覆盖,中性、独立 H1 文档、无外层哨兵);
脚本 `glob` 该目录 → 每文件取首条 `#` 标题为展示名(回退 filename stem)+ `@<相对 target 路径>` 引用 → 拼简洁
索引块 → 幂等替换 `<target>/AGENTS.md` 的 `<!-- security-controls:begin --> … :end -->` 块(复用 `_merge_into`
既有逻辑)。脚本 SHALL 同时提供 `--check` 模式作**确定性纯净性 lint**:对 opencode 详述文件
`<rules-dir>/*.md` 与 claude `.claude/rules/security-*.md` 扫描高精度禁用 token(工具名 / 脚本 basename /
内部路径 / inventory schema 字段 / 特征过程散文)+ opencode `---` YAML 围栏结构检查,命中 SHALL fail-loud
(退出码 2)并报具体文件与位置;裸层级词(`T1`/`T2`/`T3`/`scout`)MUST NOT 纳入 lint。脚本 SHALL 遵守 R5.3
稳定性契约:`--help` 即 CLI 唯一契约(`--rules-dir` 取代旧 `--parts`)、`stdout`=JSON 摘要 / `stderr`=诊断
严格分流、退出码 `0/1/2`、任意 cwd 可直接 `py`、`sys.path` 自定位兄弟导入、`encoding="utf-8"`、零运行时依赖(承 R2)。

#### Scenario: T3 writes detail files directly, not the index or staging fragment

- **WHEN** T3 `init-rulewriter` 为 category `authorization` 完成草拟(`--format opencode`)
- **THEN** 它写出 `<target>/docs/security-controls/authorization.md`(独立 H1 文档),`AGENTS.md` 与
  `.mgh-init/rules-parts/` 均不被 T3 写

#### Scenario: Assembler builds index block from detail-file glob

- **WHEN** `assemble_rules.py --target . --format opencode` 运行
- **THEN** `<target>/AGENTS.md` 的受管块为索引(每详述文件一行 `@docs/security-controls/<cat>.md` + lazy 指令),
  反映 `<rules-dir>/*.md` 现实快照;stdout 输出 JSON 摘要含 `categories[]` 与 `rules_dir`

#### Scenario: Lint fails loud on leaked script name in detail file

- **WHEN** `<rules-dir>/authentication.md` 正文出现 `discover_controls.py`,执行 `assemble_rules.py --check`
- **THEN** 脚本以退出码 2 失败,stderr 报具体文件与命中 token,不产出「看似成功」的 rules

#### Scenario: Lint fails loud on YAML fence in opencode detail file

- **WHEN** `<rules-dir>/authentication.md` 正文含一行 `---`(YAML 围栏),执行 `assemble_rules.py --target . --format opencode --check`
- **THEN** 脚本以退出码 2 失败,报围栏泄漏位置(opencode 详述文件无 front matter)

#### Scenario: Lint does not flag bare tier tokens in target code

- **WHEN** 目标项目某控制锚点为 `src/.../T1LineParser.java::parse`,执行 `--check`
- **THEN** lint 不把它当作层级词泄漏误报(裸 `T1` 不在禁用 token 集合)

#### Scenario: Assembler is self-contained and offline

- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/assemble_rules.py --target . --format opencode --check` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8 读入、零第三方依赖),AST 扫描无非标准库 import

### Requirement: Deterministic rule-job enumeration for T3 fan-out

`/mgh-init` 的编排器进入 T3 fan-out(按 category 出 rules)时,MUST 经确定性叶脚本
`core/scripts/list_rule_jobs.py` 取得按-category 的 pending 工作清单(对标 T1 `list_clusters.py` 与 scout
`list_scout_batches.py`),MUST NOT 手挖 inventory 取 category、MUST NOT `py -c` 内省、MUST NOT **整份读**
`controls_inventory.json` 进编排器上下文(完整记录经 `--materialize` 下沉到 per-unit input 文件,见
`request-context-budget`)。`list_rule_jobs.py` SHALL 读 `<target>/.mgh-init/controls_inventory.json` 的
categories(+ 对应 `--format`)+ `--rules-dir`(默认 `<target>/docs/security-controls`)并扫
`<target>/.mgh-init/checkpoints/t3/*.done`,stdout 输出结构化 JSON
`{total,done,pending[],format,offset,limit,effective_limit,shrunk}`,`pending[]` 每项(slim 壳)含
`{category,format,rule_path,done_marker,input_path,bytes,oversize}`(`rule_path`/`done_marker`/`input_path`
绝对);stderr 仅诊断/进度;退出码 `0/1/2`;`--help` 即其 CLI 契约(承 R5.1)。opencode `rule_path` SHALL 为
`<abs target>/<rules-dir>/<cat>.md`。脚本 SHALL 支持 `--materialize <dir>`(把每 category 完整 controls 写到
`<dir>/<category>.input.json` + 报 `input_path`/`bytes`/`oversize`)、`--offset`/`--limit`(分页)。单 category
input `bytes` > `--max-unit-bytes` 时 SHALL 标 `oversize:true` + recipe 建议 `--scope`+`--merge`(**不**切分
category,rulewriter 需整 category 视图)。当某页字节 > `--orch-budget-bytes` 时 SHALL 自动收紧 `--limit`、报
`effective_limit`+`shrunk:true`。`init-rulewriter` SHALL 读自己的 `input_path`(一个 category 的 controls)而非
编排器内联传记录。脚本 MUST 自定位 `sys.path`、utf-8 读入、零第三方依赖、任意 cwd 可 `py`(承 R5.3a)。T3 产出
的详述文件 SHALL 经既有 `assemble_rules.py --check` 做边界校验,失败 fail-loud(退出码 2)回退重跑(承 R5.9)。

#### Scenario: Orchestrator enumerates rule jobs via the leaf script

- **WHEN** 编排器进入 T3 fan-out(步骤 6)
- **THEN** 它先调用 `list_rule_jobs.py --format <format> --materialize <inputs/t3> --rules-dir <dir>` 取
  `pending[]` 再逐 category 扇出 `init-rulewriter`,向 subagent **透传 `input_path`**;不出现手挖 inventory、
  `py -c` 或整份读 inventory

#### Scenario: list_rule_jobs reports total vs done for resume

- **WHEN** 部分 category 已 done(`checkpoints/t3/<category>.<format>.json.done` 存在)后再次运行
- **THEN** stdout 的 `done` 反映已完成 category 数,`pending[]` 仅含未完成 category,`total = done + len(pending)`

#### Scenario: list_rule_jobs is self-contained and offline

- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_rule_jobs.py --inventory <dir>/controls_inventory.json --checkpoints <dir>/checkpoints/t3 --format opencode --rules-dir <dir>/docs/security-controls --materialize <dir>/inputs/t3` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8 读入、零第三方依赖),stdout 为合法 JSON,per-category input 文件落 `<dir>/inputs/t3/`

#### Scenario: Empty inventory handled without silent truncation

- **WHEN** `controls_inventory.json` 含 0 个 category
- **THEN** `list_rule_jobs.py` 输出 `total:0`,退出码仍 `0`,不静默丢信息

#### Scenario: Oversize category is flagged not sharded

- **WHEN** 某 category input `bytes` > `--max-unit-bytes`
- **THEN** `list_rule_jobs.py` 标 `oversize:true` + stderr recipe 建议 `--scope`+`--merge`;**不**切分 category

#### Scenario: Work-list page shrinks to the orchestrator budget

- **WHEN** 一页 `pending[]` 序列化字节 > `--orch-budget-bytes`
- **THEN** `list_rule_jobs.py` 自动收紧 `--limit`,stdout 报 `effective_limit` + `shrunk:true`,编排器翻页

### Requirement: T3 rule-output paths are deterministic absolute values

T3 fan-out 的每个待跑 category 的**输出路径** SHALL 是由确定性枚举脚本产出的**单一权威绝对路径值**,
而非相对路径或占位符模板。`list_rule_jobs.py` 的 stdout `pending[]` 每项 SHALL 包含绝对 `rule_path`
(claude:`<abs target>/.claude/rules/security-<cat>.md`;opencode:`<abs target>/<rules-dir>/<cat>.md`,
`<rules-dir>` 默认 `docs/security-controls`,经 `Path.resolve()` 绝对化)与绝对 `done_marker`
(`<abs checkpoints>/<cat>.<format>.json.done`),二者均由该脚本从其 `--target`(经 `Path.resolve()`)、
`--rules-dir` 与 `--checkpoints`(已 `resolve()`)参数拼出。`rule_path` MUST NOT 在 `--target` 缺省为 `.` 时
仍是相对路径。

编排器 SHALL 把 `list_rule_jobs.py` stdout 的 `rule_path` / `done_marker` **逐字透传**进
`init-rulewriter` subagent 的 task 输入,MUST NOT 自行拼路径。`init-rulewriter` 的 stage 提示词 SHALL 把
`rule_path`(与 `done_marker`)列为**编排器逐字给定**的输入字段,其 Output 段 SHALL 要求「Write 恰好
`rule_path` 给定的绝对路径并 touch `done_marker`」;且 SHALL 以硬边界 `NEVER` 禁止:自行拼路径、
写相对路径、写到项目目录之外、直写 `AGENTS.md` 或受管块哨兵(既有约束,保留——T3 只产详述文件,
索引块归 `assemble_rules.py`)。

路径 SHALL 为绝对路径(经 `Path.resolve()`),使其对 subagent 的任意工作目录安全。运行时 hook(在
`MGH_INIT_ACTIVE` 运行域内)的子树外写入拦截对 T3 的 `.claude/rules/` 与 `<rules-dir>/` 写入同样生效——
二者均在 resolved `MGH_TARGET` 子树内,故合法写入被放行。

#### Scenario: list_rule_jobs emits absolute rule_path and done_marker

- **WHEN** `list_rule_jobs.py --inventory …/controls_inventory.json --format opencode --checkpoints …/checkpoints/t3 --target . --rules-dir docs/security-controls` 运行
- **THEN** stdout `pending[]` 每项的 `rule_path` 与 `done_marker` 均为**绝对路径**(即使 `--target` 取默认 `.`),
  分别等于 `<abs target>/docs/security-controls/<cat>.md` 与 `<abs checkpoints>/<cat>.opencode.json.done`

#### Scenario: Orchestrator passes rule_path verbatim

- **WHEN** 编排器取得 T3 `pending[]` 并起 `init-rulewriter` subagent
- **THEN** subagent task 输入里的输出路径**逐字等于** `list_rule_jobs.py` stdout 的 `rule_path`,
  编排器**不**自行拼 `<target>`/`<category>` 占位符

#### Scenario: Rulewriter writes exactly the given absolute path

- **WHEN** 一个 init-rulewriter subagent 在工作目录 ≠ 项目根的隔离上下文运行
- **THEN** 它把详述文件写到输入字段 `rule_path` 给定的绝对路径,**不**写到项目外目录,且 touch 输入字段
  `done_marker` 给定的绝对 `.done` 路径

#### Scenario: Legit rule write under target tree is not blocked

- **WHEN** 运行域内 `init-rulewriter` 向 `<abs target>/docs/security-controls/authentication.md` 写入
- **THEN** PreToolUse hook 放行(目标在 resolved `MGH_TARGET` 子树内),不被误判为越界

### Requirement: opencode rule detail files carry no front matter or inventory-schema fields

`--format opencode` 的每个详述文件(`<target>/docs/security-controls/<category>.md`)SHALL 是一个**独立
H1 文档**——以 `# <Category> 安全控制` 标题起头,**NEVER** 携带 YAML `---` 围栏(front matter),**NEVER**
出现 `controls_inventory.json` 的结构字段名(`found_controls` / `evidence_count` / `category:` / `source:` /
`evidence:` 作为 front matter 键或正文元数据)。opencode 不支持 path-scoping,详述文件对它无任何 front matter
语义;front matter 纯耗上下文(且详述文件按需加载,front matter 更无意义)。claude 格式不受此约束(claude
合法使用 `paths:` 作唯一 front matter)。该约束 SHALL 写入 `core/prompts/fragments/rules-format-opencode.md`
(recipe + `NEVER` 硬边界,承 R5.5①②③),并由确定性 lint 兜底(见「Deterministic assembly and purity lint」)。

#### Scenario: opencode detail file has no YAML front matter

- **WHEN** T3 `init-rulewriter` 为 category `authentication` 产出详述文件(`--format opencode`)
- **THEN** 文件以 `# 认证 安全控制`(或对应 category H1 标题)起头,**不**以 `---` 围栏开头,**不**含
  `category:` / `found_controls` / `evidence_count` 等 inventory schema 字段

#### Scenario: opencode detail file carries concrete implementation, not metadata header

- **WHEN** 一条认证规则描述目标项目的 `AuthConfig` + `TokenAuthenticationService`
- **THEN** 文件形如 `# 认证 安全控制\n\n- 项目使用自定义 \`AuthConfig\` + \`TokenAuthenticationService\` 实现 Bearer Token 认证。锚点: \`src/.../AuthConfig.java::TokenAuthenticationService\``,
  **不**形如 `---\ncategory: authentication\nfound_controls:\n  - C-AUTHN-001\nevidence_count: 1\n---\n# 认证`

### Requirement: Rules are emitted only for controls with a concrete target-project implementation

shipped rules(opencode 受管块正文 / claude `.claude/rules/security-*.md` 正文)SHALL **只**承载目标项目里
**有具体源码锚点**(`file:class:method` / `file:line`)的**存量可复用实现**——这是 mgh-init 的唯一职责
(梳理存量、引导复用、勿重造)。inventory 里**无源码锚点**的控制(扫描器/正则期望某模式但目标项目源码无
实现,如「声明式 ACL 未发现」「限流未发现实现」)SHALL **emit no rule**;若整 category 的全部控制均无
源码锚点,T3 SHALL **不产出该 category 的 fragment**(该 category 不进受管块 / 不产 claude 规则文件),
且 SHALL 仍 touch 其 `done_marker`(宣告已处理,防 `--resume` 重跑)。规则正文 MUST NOT 用「设计缺失」/
「未发现实现」散文占行填补无实现项——AGENTS.md 篇幅受限,缺失项不出现在面向 AI 编码的规则里。无实现项
仍由面向人的 `report.md` / `init_manifest.json` 全量披露(职责分离)。该约束 SHALL 写入
`core/prompts/stages/init-rulewriter.md`(两格式共享,recipe + `NEVER`,承 R5.5①②③)。

#### Scenario: Control with no source anchor produces no rule

- **WHEN** inventory 某 `rate-limiting` 控制无任何 `file:class:method` 锚点(扫描器期望 `@RateLimit` 但源码无实现)
- **THEN** T3 不为该控制产出任何规则行;整 category 无实现时,不产出 `rate-limiting` fragment

#### Scenario: Category with no implemented controls is omitted entirely

- **WHEN** category `access-control` 的全部控制均无源码锚点
- **THEN** 不产出 `<target>/docs/security-controls/access-control.md`(opencode)/ 不产出
  `<target>/.claude/rules/security-access-control.md`(claude),且 `checkpoints/t3/access-control.<format>.json.done`
  被 touch;受管块 / rules 目录中**不**出现 `### 访问控制\n- C-ABS-001（缺失）: 未发现……` 式散文

#### Scenario: Implemented controls are still emitted

- **WHEN** category `authentication` 含一条有 `src/.../AuthConfig.java::TokenAuthenticationService` 锚点的控制
- **THEN** T3 为该 category 产出 fragment / 规则文件,正文指向该锚点(无实现项被静默丢弃,有实现项保留)

### Requirement: Rule anchors point at target-project source, not discovery internals

shipped rules 的锚点字段(`锚点:` / Anchor)SHALL **只**指向**目标项目源码**位置(`file:class:method` /
`file:line`)。锚点字段 MUST NEVER 指向「扫描器内部正则定义」「扫描器模式定义」「如何被发现/归纳」等
本工具发现过程的内部。规则正文(描述/用法/缺口)MUST NOT 描述扫描器/正则「定义了什么模式」「期望什么」;
正文 SHALL 以目标项目**实际使用的类/方法/配置名**起头陈述(是什么 / 怎么复用 / 锚点指向源码 / 必要的
有效性 caveat)。控制 ID(`C-*-001`)可选;若出现,SHALL 无 `(缺失)` / `(扫描器…)` / `(扫描器模式定义)`
等过程性后缀。该约束 SHALL 写入 `core/prompts/stages/init-rulewriter.md` 与两个 rules-format fragment
(recipe + `NEVER`),并由确定性 lint 对特征短语兜底(见「Purity lint detects inventory-schema fields,
YAML fences, and discovery prose」)。

#### Scenario: Anchor field points at target source

- **WHEN** 一条认证规则引用目标项目的 `TokenAuthenticationService`
- **THEN** 锚点字段为 `` `src/.../AuthConfig.java::TokenAuthenticationService` ``,**不**为
  `锚点：扫描器内部正则定义` 或 `锚点: 扫描器模式定义`

#### Scenario: Rule body describes the project control, not the scanner

- **WHEN** 一条规则描述某鉴权封装
- **THEN** 正文以「项目使用自定义 `AuthConfig` + `TokenAuthenticationService` 实现 Bearer Token 认证」起头,
  **不**含「扫描器定义了 `@EnableWebSecurity`」「扫描器模式定义」「检测 Spring Security 标准认证模式」等
  扫描器/正则定义描述

### Requirement: Purity lint detects inventory-schema fields, YAML fences, and discovery prose

确定性叶脚本 `core/scripts/assemble_rules.py` 的纯净性 lint(`--check` / 常驻)SHALL 在既有高精度禁用
token(工具名 / 脚本 basename / 内部路径)之外,**额外**检测以下高精度、近零误报的泄漏形状,命中 SHALL
fail-loud(退出码 2)并报具体文件与位置:(a) inventory schema 字段名 `found_controls`、`evidence_count`;
(b) 特征发现过程散文短语 `扫描器模式定义`、`扫描器内部正则`、`扫描器定义`、`锚点:扫描器`(半角冒号)、
`锚点：扫描器`(全角冒号);(c) **opencode 结构检查**——opencode 受管块(`<!-- security-controls:begin --> …
<!-- security-controls:end -->` 内)正文出现任意 `---` YAML 围栏行 SHALL fail-loud(opencode fragment 模板
无围栏,出现即 front matter 泄漏)。`---` 围栏结构检查 SHALL **仅对 opencode 生效**;claude
`.claude/rules/security-*.md` 合法使用 `paths:` frontmatter,lint 对 claude 文件 MUST NOT 跑围栏检查
(仅跑 token 检查)。裸通用词(`category` / `缺失` / 泛指 `锚点` / 单独 `source:`·`evidence:` 键)MUST NOT
纳入 lint(目标项目正文误伤风险),其泄漏由提示词护栏覆盖、非确定性可测。脚本稳定性契约不变(`--help` 即
CLI 唯一契约、`stdout`=JSON 摘要 / `stderr`=诊断、退出码 `0/1/2`、零依赖、承 R5.3)。

#### Scenario: Lint fails loud on leaked inventory-schema field

- **WHEN** opencode 受管块正文出现 `found_controls:` 或 `evidence_count:`,执行 `assemble_rules.py --check`
- **THEN** 脚本以退出码 2 失败,stderr 报具体文件与命中 token,stdout `lint.ok=false` 含 violations

#### Scenario: Lint fails loud on YAML fence in opencode managed block

- **WHEN** opencode 受管块正文含一行 `---`(YAML 围栏),执行 `assemble_rules.py --target . --format opencode --check`
- **THEN** 脚本以退出码 2 失败,报围栏泄漏位置;不产出「看似成功」的 rules

#### Scenario: Lint fails loud on discovery-prose phrase

- **WHEN** 受管块正文出现 `扫描器模式定义` 或 `锚点：扫描器内部正则定义`,执行 `--check`
- **THEN** 脚本以退出码 2 失败,报命中短语

#### Scenario: Lint does not false-positive on claude paths frontmatter

- **WHEN** claude 规则文件 `security-authentication.md` 以合法 `---\npaths:\n  - "src/**"\n---` frontmatter
  开头,执行 `assemble_rules.py --target . --format claude --check`
- **THEN** lint **不**把 `---` 围栏当作泄漏误报(`paths:` 是 claude 合法 frontmatter);退出码 0

#### Scenario: Lint does not flag bare generic words

- **WHEN** 受管块正文含裸词 `category` 或 `缺失`(目标项目合法措辞),执行 `--check`
- **THEN** lint 不误报(裸通用词不在禁用集,其泄漏由提示词护栏覆盖)

### Requirement: init-rulewriter returns a bounded ack to the orchestrator

`init-rulewriter`(T3 per-category rulewriter)subagent 的**最终回传消息** SHALL 是**单条有界 ack**——取值之一
`ok <绝对 rule_path> <category>`、`oversize <绝对 rule_path> <category>`、`failed <简短原因>`——且 **MUST NOT** 回显规则
正文、inventory 记录体、或源码(承 control-discovery「Subagent return-to-orchestrator is a bounded ack」的横切纪律,
专治 T3 fan-out 完成时编排器上下文随 category 数单调膨胀)。该 ack 仅为存活/成功信号;编排器 SHALL 据 ack + `.done`
标记判断该 category 成败,MUST NOT 为继续 fan-out 而内联 `Read` 规则/详述文件回编排器上下文。该契约 SHALL 同时写入
`core/prompts/stages/init-rulewriter.md` 与双壳 `agents/init-rulewriter.md` 的 Hard-constraints 段(双重防线)。
`assemble_rules.py --check` 纯净性 lint、T3 fan-out 绝对 `rule_path` 契约(承 rules-emission 既有要求)**保持不变**。

#### Scenario: rulewriter prompt declares the bounded ack

- **WHEN** 审阅 `core/prompts/stages/init-rulewriter.md`
- **THEN** 该提示词含一个 Return-to-orchestrator 段,声明最终消息为单条有界 ack(`ok <abs rule_path> <category>` 等)、
  NEVER 回显规则正文/inventory 记录体

#### Scenario: Orchestrator does not inline-read rules to continue fan-out

- **WHEN** 一个 init-rulewriter subagent 完成并回传 `ok <abs rule_path> <category>`,编排器进入下一 category
- **THEN** 编排器仅记 ack 为成功信号 + 探 `.done`;它 **不** `Read` 该规则/详述文件内联回上下文

#### Scenario: Shell agent definition mirrors the ack contract

- **WHEN** 审阅 claude-code 与 opencode 两份 `agents/init-rulewriter.md` 的 Hard-constraints 段
- **THEN** 两壳均显式声明 subagent 回传为有界 ack、NEVER 回显正文(双壳与 prompt 双重防线)
