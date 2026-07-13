## ADDED Requirements

### Requirement: opencode rule fragments carry no front matter or inventory-schema fields

`--format opencode` 的每个暂存 fragment(`<target>/.mgh-init/rules-parts/<category>.md`)SHALL 是
一个**裸 category 小节**——以 `### <Category>` 标题起头,**NEVER** 携带 YAML `---` 围栏(front matter),
**NEVER** 出现 `controls_inventory.json` 的结构字段名(`found_controls` / `evidence_count` / `category:` /
`source:` / `evidence:` 作为 front matter 键或正文元数据)。opencode 不支持 path-scoping,fragment 对它
无任何 front matter 语义;front matter 纯耗根上下文。claude 格式不受此约束(claude 合法使用 `paths:` 作
唯一 front matter,见既有「Claude Code rules use path-scoped .claude/rules/」要求)。该约束 SHALL 写入
`core/prompts/fragments/rules-format-opencode.md`(recipe + `NEVER` 硬边界,承 R5.5①②③),并由确定性
lint 兜底(见「Purity lint detects inventory-schema fields, YAML fences, and discovery prose」)。

#### Scenario: opencode fragment has no YAML front matter

- **WHEN** T3 `init-rulewriter` 为 category `authentication` 产出 fragment(`--format opencode`)
- **THEN** fragment 以 `### 认证`(或对应 category 标题)起头,**不**以 `---` 围栏开头,**不**含 `category:` /
  `found_controls` / `evidence_count` 等 inventory schema 字段

#### Scenario: opencode fragment carries concrete implementation, not metadata header

- **WHEN** 一条认证规则描述目标项目的 `AuthConfig` + `TokenAuthenticationService`
- **THEN** fragment 形如 `### 认证\n- 项目使用自定义 \`AuthConfig\` + \`TokenAuthenticationService\` 实现 Bearer Token 认证。锚点: \`src/.../AuthConfig.java::TokenAuthenticationService\``,**不**形如
  `---\ncategory: authentication\nfound_controls:\n  - C-AUTHN-001\nevidence_count: 1\n---\n### 认证`

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
- **THEN** 不产出 `<target>/.mgh-init/rules-parts/access-control.md`(opencode)/ 不产出
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
