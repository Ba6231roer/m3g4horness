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

`--format opencode` SHALL 产出一个项目根 `AGENTS.md`,内含按 `category` 分节的安全规则块。
MUST NOT 写 `.opencode/AGENTS.md`(opencode 不加载该位置,issue #11454);因 opencode 不
支持 path-scoping,所有类别集中在单文件内分节。

#### Scenario: Single root AGENTS.md with category sections
- **WHEN** `--format opencode` 运行完成
- **THEN** 存在 `<target>/AGENTS.md`,包含 ≥1 个 category 小节,且不存在 `.opencode/AGENTS.md`

### Requirement: Non-destructive, idempotent emission

写入既有目标文件时 SHALL 以**中性哨兵**标记的**受管块**追加或原地替换,MUST NOT 覆盖用户手写内容。
opencode(`--format opencode`)SHALL 使用**单个**受管块
`<!-- security-controls:begin --> … <!-- security-controls:end -->`(包纳全部 category 小节),
由确定性脚本 `assemble_rules.py` 合并 T3 暂存 fragment 落盘(见「Deterministic assembly and
purity lint」)。哨兵标记 MUST 是中性的,`MUST NOT` 携带本工具名(`mgh-init`/`megahorness` 等)。
claude(`--format claude`)每 category 一个独立文件 `security-<category>.md`,幂等=整文件覆写。
重复运行同一 `--format` MUST 幂等:仅替换受管块(opencode)/ 对应文件(claude),其余内容不变。
`assemble_rules.py` 首次运行 SHALL 一次性清扫并迁移旧版 `<!-- mgh-init:begin` 开头的受管块,
避免孤儿重复内容,并将迁移计数记入 stdout 摘要。

#### Scenario: Existing user content preserved

- **WHEN** 目标已有用户手写的 `AGENTS.md` / `.claude/rules/*.md`
- **THEN** 用户内容原样保留,init 仅追加/替换自己的受管块(opencode)/ 对应 category 文件(claude)

#### Scenario: Re-run is idempotent

- **WHEN** 对同一目标连续两次运行 `mgh-init --format opencode`
- **THEN** `AGENTS.md` 的 `<!-- security-controls:begin --> … :end -->` 受管块只出现一次,内容为最新 inventory,非受管部分无变化

#### Scenario: Neutral sentinel carries no tool name

- **WHEN** `--format opencode` 产出 `AGENTS.md` 受管块
- **THEN** 哨兵标记为 `<!-- security-controls:begin -->` / `<!-- security-controls:end -->`,不含 `mgh-init`、`megahorness` 或任何本工具标识

#### Scenario: Legacy branded blocks migrated on first run

- **WHEN** 目标 `AGENTS.md` 含旧版 `<!-- mgh-init:begin:audit-logging --> … <!-- mgh-init:end:audit-logging -->` 块,以新版重跑
- **THEN** `assemble_rules.py` 清除旧品牌块、写入新中性单块,用户其余内容不动,stdout 摘要 `migrated_legacy_blocks` 记被迁移块数

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
(`T1` / `T2` / `T3` / `scout` 作为生成过程描述)、内部路径(`.mgh-init/` / `checkpoints/` /
`rules-parts/`)、以及任何「如何被本工具发现/归纳」的过程描述。目标项目自身的代码、文件路径、
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

opencode 规则 SHALL 经确定性叶脚本 `core/scripts/assemble_rules.py` 装配:T3 每 category 产出
暂存 fragment `<target>/.mgh-init/rules-parts/<category>.md`(中性、无外层哨兵),脚本将其合并
进 `<target>/AGENTS.md` 的单个 `<!-- security-controls:begin --> … :end -->` 受管块,幂等替换、
保留用户内容。脚本 SHALL 同时提供 `--check` 模式作**确定性纯净性 lint**:对 opencode 受管块与
claude `.claude/rules/security-*.md` 扫描高精度禁用 token(工具名 / 脚本 basename / 内部路径),
命中 SHALL fail-loud(退出码 2)并报具体文件与位置;裸层级词(`T1`/`T2`/`T3`/`scout`)MUST NOT
纳入 lint(避免目标项目类名误伤,其泄漏由提示词护栏覆盖)。脚本 SHALL 遵守 R5.3 稳定性契约:
`--help` 即 CLI 唯一契约、`stdout`=JSON 摘要 / `stderr`=诊断严格分流、退出码 `0/1/2`、任意 cwd
可直接 `py`、`sys.path` 自定位兄弟导入、`encoding="utf-8"`、零运行时依赖(承 R2)。

#### Scenario: T3 emits staged fragments, not the final file

- **WHEN** T3 `init-rulewriter` 为 category `authorization` 完成草拟(`--format opencode`)
- **THEN** 它写出 `<target>/.mgh-init/rules-parts/authorization.md`(无外层哨兵),`AGENTS.md` 不被 T3 直接写

#### Scenario: Assembler merges fragments into single neutral block

- **WHEN** `assemble_rules.py --target . --format opencode` 运行
- **THEN** `<target>/AGENTS.md` 出现单个 `<!-- security-controls:begin --> … <!-- security-controls:end -->` 块,内含各 category 小节;stdout 输出 JSON 摘要含 `categories[]`

#### Scenario: Lint fails loud on leaked script name

- **WHEN** 受管块正文出现 `discover_controls.py`,执行 `assemble_rules.py --check`
- **THEN** 脚本以退出码 2 失败,stderr 报具体文件与命中 token,不产出「看似成功」的 rules

#### Scenario: Lint does not flag bare tier tokens in target code

- **WHEN** 目标项目某控制锚点为 `src/.../T1LineParser.java::parse`,执行 `--check`
- **THEN** lint 不把它当作层级词泄漏误报(裸 `T1` 不在禁用 token 集合)

#### Scenario: Assembler is self-contained and offline

- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/assemble_rules.py --target . --format opencode --check` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8 读入、零第三方依赖),AST 扫描无非标准库 import

### Requirement: Deterministic rule-job enumeration for T3 fan-out

`/mgh-init` 的编排器进入 T3 fan-out(按 category 出 rules)时,MUST 经确定性叶脚本
`core/scripts/list_rule_jobs.py` 取得按-category 的 pending 工作清单(对标 T1 的 `list_clusters.py`
与 scout 的 `list_scout_batches.py`,闭合 FD3 的三处扇出不对称)。`list_rule_jobs.py` SHALL 读
`<target>/.mgh-init/controls_inventory.json` 中的 categories(+ 对应 `--format`)并扫
`<target>/.mgh-init/checkpoints/t3/*.done`,stdout 输出结构化 JSON
`{total,done,pending[],format}`,`pending[]` 每项含 `{category,format,rule_path}`;stderr 仅诊断/进度;
退出码 `0/1/2`;`--help` 即其 CLI 契约(承 R5.1)。编排器 MUST NOT 手挖 inventory 取 category、
MUST NOT `py -c` 内省。脚本 MUST 自定位 `sys.path`、utf-8 读入、零第三方依赖、任意 cwd 可 `py`(承
R5.3a)。T3 产出的 rules SHALL 经既有 `assemble_rules.py --check`(见「Deterministic assembly and
purity lint」)做边界校验,失败 fail-loud(退出码 2)回退重跑(承 R5.9 边界校验泛化,该 `--check` 为
范式源头)。

#### Scenario: Orchestrator enumerates rule jobs via the leaf script
- **WHEN** 编排器进入 T3 fan-out(步骤 6)
- **THEN** 它先调用 `list_rule_jobs.py` 取 `pending[]` 再逐 category 扇出 `init-rulewriter`;不出现手挖 inventory 或 `py -c`

#### Scenario: list_rule_jobs reports total vs done for resume
- **WHEN** 部分 category 已 done(`checkpoints/t3/<category>.<format>.json.done` 存在)后再次运行
- **THEN** stdout 的 `done` 反映已完成 category 数,`pending[]` 仅含未完成 category,`total = done + len(pending)`

#### Scenario: list_rule_jobs is self-contained and offline
- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_rule_jobs.py --inventory <dir>/controls_inventory.json --checkpoints <dir>/checkpoints/t3 --format opencode` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8 读入、零第三方依赖),stdout 为合法 JSON

#### Scenario: Empty inventory handled without silent truncation
- **WHEN** `controls_inventory.json` 含 0 个 category
- **THEN** `list_rule_jobs.py` 输出 `total:0`,退出码仍 `0`,不静默丢信息

### Requirement: T3 rule-output paths are deterministic absolute values

T3 fan-out 的每个待跑 category 的**输出路径** SHALL 是由确定性枚举脚本产出的**单一权威绝对路径值**,
而非相对路径或占位符模板。`list_rule_jobs.py` 的 stdout `pending[]` 每项 SHALL 包含绝对 `rule_path`
(claude:`<绝对 target>/.claude/rules/security-<cat>.md`;opencode:`<绝对 target>/.mgh-init/rules-parts/<cat>.md`)
与绝对 `done_marker`(`<绝对 checkpoints>/<cat>.<format>.json.done`),二者均由该脚本从其 `--target`
(经 `Path.resolve()`)与 `--checkpoints`(已 `resolve()`)参数拼出。`rule_path` MUST NOT 在 `--target`
缺省为 `.` 时仍是相对路径。

编排器 SHALL 把 `list_rule_jobs.py` stdout 的 `rule_path` / `done_marker` **逐字透传**进
`init-rulewriter` subagent 的 task 输入,MUST NOT 自行拼路径。`init-rulewriter` 的 stage 提示词 SHALL 把
`rule_path`(与 `done_marker`)列为**编排器逐字给定**的输入字段,其 Output 段 SHALL 要求「Write 恰好
`rule_path` 给定的绝对路径并 touch `done_marker`」;且 SHALL 以硬边界 `NEVER` 禁止:自行拼路径、
写相对路径、写到项目目录之外、直写 `AGENTS.md` 或受管块哨兵(既有约束,保留)。

路径 SHALL 为绝对路径(经 `Path.resolve()`),使其对 subagent 的任意工作目录安全。运行时 hook(在
`MGH_INIT_ACTIVE` 运行域内)的子树外写入拦截(见 `control-discovery` 同名要求)对 T3 的 `.claude/rules/`
与 `.mgh-init/rules-parts/` 写入同样生效——二者均在 resolved `MGH_TARGET` 子树内,故合法写入被放行。

#### Scenario: list_rule_jobs emits absolute rule_path and done_marker
- **WHEN** `list_rule_jobs.py --inventory …/controls_inventory.json --format claude --checkpoints …/checkpoints/t3 --target .` 运行
- **THEN** stdout `pending[]` 每项的 `rule_path` 与 `done_marker` 均为**绝对路径**(即使 `--target` 取默认 `.`),
  分别等于 `<绝对 target>/.claude/rules/security-<cat>.md` 与 `<绝对 checkpoints>/<cat>.claude.json.done`

#### Scenario: Orchestrator passes rule_path verbatim
- **WHEN** 编排器取得 T3 `pending[]` 并起 `init-rulewriter` subagent
- **THEN** subagent task 输入里的输出路径**逐字等于** `list_rule_jobs.py` stdout 的 `rule_path`,
  编排器**不**自行拼 `<target>`/`<category>` 占位符

#### Scenario: Rulewriter writes exactly the given absolute path
- **WHEN** 一个 init-rulewriter subagent 在工作目录 ≠ 项目根的隔离上下文运行
- **THEN** 它把规则文件(claude)或暂存 fragment(opencode)写到输入字段 `rule_path` 给定的绝对路径,
  **不**写到项目外目录,且 touch 输入字段 `done_marker` 给定的绝对 `.done` 路径

#### Scenario: Legit rule write under target tree is not blocked
- **WHEN** 运行域内 `init-rulewriter` 向 `<绝对 target>/.claude/rules/security-authentication.md` 写入
- **THEN** PreToolUse hook 放行(目标在 resolved `MGH_TARGET` 子树内),不被误判为越界

