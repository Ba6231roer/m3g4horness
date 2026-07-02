## ADDED Requirements

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

写入既有目标文件时 SHALL 以哨兵标记的**受管块**追加或原地替换
(`<!-- mgh-init:begin --> … <!-- mgh-init:end -->` / opencode 等价标记),MUST NOT 覆盖
用户手写内容。重复运行同一 `--format` MUST 幂等:仅替换受管块,其余内容不变。

#### Scenario: Existing user content preserved
- **WHEN** 目标已有用户手写的 `AGENTS.md` / `.claude/rules/*.md`
- **THEN** 用户内容原样保留,init 仅追加/替换自己的受管块

#### Scenario: Re-run is idempotent
- **WHEN** 对同一目标连续两次运行 `mgh-init --format opencode`
- **THEN** `AGENTS.md` 受管块只出现一次,内容为最新 inventory,非受管部分无变化

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
