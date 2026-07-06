## MODIFIED Requirements

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

## ADDED Requirements

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
