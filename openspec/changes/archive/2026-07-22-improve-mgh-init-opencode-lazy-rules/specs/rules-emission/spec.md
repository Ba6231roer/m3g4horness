## MODIFIED Requirements

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
`list_scout_batches.py`)。`list_rule_jobs.py` SHALL 读 `<target>/.mgh-init/controls_inventory.json` 的
categories(+ 对应 `--format`)+ `--rules-dir`(默认 `<target>/docs/security-controls`)并扫
`<target>/.mgh-init/checkpoints/t3/*.done`,stdout 输出结构化 JSON `{total,done,pending[],format}`;
`pending[]` 每项含 `{category,format,rule_path,done_marker}`;stderr 仅诊断/进度;退出码 `0/1/2`;`--help`
即其 CLI 契约(承 R5.1)。opencode `rule_path` SHALL 为 `<abs target>/<rules-dir>/<cat>.md`。编排器 MUST NOT
手挖 inventory 取 category、MUST NOT `py -c` 内省。脚本 MUST 自定位 `sys.path`、utf-8 读入、零第三方依赖、
任意 cwd 可 `py`(承 R5.3a)。T3 产出的详述文件 SHALL 经既有 `assemble_rules.py --check` 做边界校验,失败
fail-loud(退出码 2)回退重跑(承 R5.9)。

#### Scenario: Orchestrator enumerates rule jobs via the leaf script

- **WHEN** 编排器进入 T3 fan-out(步骤 6)
- **THEN** 它先调用 `list_rule_jobs.py --rules-dir <dir>` 取 `pending[]` 再逐 category 扇出 `init-rulewriter`;
  不出现手挖 inventory 或 `py -c`

#### Scenario: list_rule_jobs reports total vs done for resume

- **WHEN** 部分 category 已 done(`checkpoints/t3/<category>.<format>.json.done` 存在)后再次运行
- **THEN** stdout 的 `done` 反映已完成 category 数,`pending[]` 仅含未完成 category,`total = done + len(pending)`

#### Scenario: list_rule_jobs is self-contained and offline

- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_rule_jobs.py --inventory <dir>/controls_inventory.json --checkpoints <dir>/checkpoints/t3 --format opencode --rules-dir <dir>/docs/security-controls` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8 读入、零第三方依赖),stdout 为合法 JSON

#### Scenario: Empty inventory handled without silent truncation

- **WHEN** `controls_inventory.json` 含 0 个 category
- **THEN** `list_rule_jobs.py` 输出 `total:0`,退出码仍 `0`,不静默丢信息

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
