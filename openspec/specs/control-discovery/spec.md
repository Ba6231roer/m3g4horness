# control-discovery Specification

## Purpose
TBD - created by archiving change add-mgh-init. Update Purpose after archive.
## Requirements
### Requirement: Parse arguments and guard zero-token no-op

`/mgh-init` SHALL accept `--target <dir>`(默认 `.`)、`--format opencode|claude`
(**必选**)、`--out <path>`、`--scope <dir|package>`、`--language <lang>`、
`--config <profile>`、`--include-dotfiles`(默认关;传则回退到扫描点前缀路径,见「Skip
dot-prefixed paths during discovery」)、`--include-tests`(默认关;传则回退到扫描测试源码树,见「Skip
test source directories during discovery」)。当无 actionable 参数或传 `--help` 时,系统 MUST 仅打印参数表
与指向 `task.260630.md` 的说明后**停止,不消耗 token、不做任何分析**。

#### Scenario: Missing required --format
- **WHEN** 用户运行 `mgh-init --target ./svc` 未提供 `--format`
- **THEN** 系统打印「`--format` 必选」错误 + 参数表并停止,不扫描代码

#### Scenario: Help / no actionable args
- **WHEN** 用户运行 `mgh-init --help` 或不带任何参数
- **THEN** 系统打印参数表后停止,零 LLM 调用、零代码扫描

#### Scenario: --include-dotfiles is a recognized flag
- **WHEN** 用户运行 `mgh-init --target . --format claude --include-dotfiles`
- **THEN** `--include-dotfiles` 被 `discover_controls.py` 接受(argparse 不报 unrecognized),
  发现阶段纳入点前缀路径;该 flag 出现在 `--help` 参数表(承 R5.1,`--help` 即契约面)

#### Scenario: --include-tests is a recognized flag

- **WHEN** 用户运行 `mgh-init --target . --format claude --include-tests`
- **THEN** `--include-tests` 被 `discover_controls.py` 接受(argparse 不报 unrecognized),发现阶段纳入测试
  源码树(回退到引入测试目录排除前的行为);该 flag 出现在 `--help` 参数表(承 R5.1)

### Requirement: Discover security control candidates deterministically

`discover_controls.py` SHALL 用 Python ≥3.10 标准库,按文件名/扩展 + 内容模式 + 注解
特征扫描候选控制,覆盖类别:`input-validation`、`data-masking`、`authentication`、
`authorization`、`crypto`、`rate-limiting`、`csrf`、`audit-logging`。扫描 MUST 复用
`expand_scope.py` 的 `SOURCE_EXT` / `EXCLUDE_DIR`(排除 `node_modules`/`target`/
`build`/`vendor` 等)。每条候选 SHALL 记录 `file`、`line`、`category`、匹配模式、片段。

本确定性扫描是发现候选的 **fast-path 来源之一**(双源并集的另一源是 LLM scout 层,
见「LLM scout discovers controls beyond the token allowlist」)。每条 regex 候选 SHALL
带 `source: "regex"`。`_QUICK_RX` 预过滤不命中的文件 MUST NOT 被丢弃出发现流程——
它们 SHALL 仍进入 `skeleton.json`(见「Extract lossless source skeleton」),保持对
scout 层可见。「不命中规范 token」本身 MUST NOT 成为排除一个文件被 LLM 审视的理由。

#### Scenario: Detect Spring authorization annotation
- **WHEN** 扫描到 `@PreAuthorize` / `@PostAuthorize` / `@Secured` / `@RolesAllowed`
- **THEN** 产出一条 `category: authorization`、`source: "regex"` 候选,含文件与行号

#### Scenario: Detect sensitive-data masking utility
- **WHEN** 扫描到含 `mask` / `redact` / `脱敏` / `@JsonSerialize` 脱敏器 / Luhn 校验等方法特征
- **THEN** 产出一条 `category: data-masking`、`source: "regex"` 候选

#### Scenario: Exclude non-source / build directories
- **WHEN** 候选落在 `target/`、`node_modules/`、`build`/`vendor/` 等 `EXCLUDE_DIR`
- **THEN** 该候选被跳过,不计入 `controls_candidates.json`

#### Scenario: Custom control missing canonical tokens stays discoverable
- **WHEN** 一个自研鉴权类 `PermGuard`(命名不撞任何规范 token)落在非 `EXCLUDE_DIR`
- **THEN** 它不产出 regex 候选,但仍出现在 `skeleton.json` 中、对 scout 层可见(即:
  「不命中 token」不会把它排除出发现流程,只是不由 regex 这一路发现)

### Requirement: Skip dot-prefixed paths during discovery

确定性文件遍历(`expand_scope.walk_sources` / `collect_dir` / `build_call_graph`)SHALL 在既有
`EXCLUDE_DIR` 精确匹配之外,**额外跳过**任何「相对 repo 的路径中存在以 `.` 开头的分量」的文件
(即点前缀目录与点前缀文件,如 `.opencode/`、`.claude/`、`.codegraph/`、`.github/`、`.husky/`、
`.env`)。该跳过 SHALL 作为文件枚举层的属性,统一作用于 regex 候选、`skeleton.json`、调用图与
scout 目标集(单一 chokepoint,承「Bounded single-pass scan」与「Extract lossless source skeleton」
的单遍复用语义),使全部下游阶段一致地不见点前缀路径,而非仅 regex 一路。

`discover_controls.py` SHALL 提供 `--include-dotfiles` flag(默认关);传该 flag 时 SHALL 回退到
引入本要求前的行为(纳入点前缀路径)。理由:点前缀条目按 Unix 惯例为非一方业务代码(tooling /
VCS / IDE / build / config / 索引);默认扫描它们会把工具自身脚本(如运行时纪律守卫
`block_adhoc_scripts.py`)诱导成伪业务控制,污染 inventory 与生成的 rules 并浪费 LLM 预算。
既有 `EXCLUDE_DIR` 集合**保持不变**(通用点规则吸收其点成员,非点构建/缓存目录如 `node_modules`/
`target`/`build`/`vendor` 仍由其精确匹配负责)。本要求仅用 Python 标准库(`pathlib.Parts` /
`str.startswith`),承 R2 零运行时依赖。

#### Scenario: Installed tooling under a dot-prefixed dir is not discovered by default
- **WHEN** 目标项目根下 `.opencode/plugins/` 与 `.claude/hooks/` 各含一个匹配控制特征(如鉴权/校验
  关键字)的 `.py`/`.ts` 源文件,且未传 `--include-dotfiles`
- **THEN** 这些文件不出现在 `controls_candidates.json`、`skeleton.json`、调用图、scout 目标集中;
  它们诱导出的工具脚本(如 `block_adhoc_scripts.py`)**不**作为安全控制进入 inventory / 生成的 rules

#### Scenario: --include-dotfiles re-includes dot-prefixed paths
- **WHEN** 运行 `discover_controls.py --repo . --out .mgh-init --include-dotfiles`,且 `.opencode/` 下
  含一个匹配控制特征的源文件
- **THEN** 该文件被纳入候选/skeleton/调用图(行为等价于引入本要求前),不被点前缀规则跳过

#### Scenario: Dot-prefix skip is consistent across all downstream stages
- **WHEN** 默认运行 `discover_controls.py`,且 `.codegraph/` 与 `.claude/` 下各有一个源文件
- **THEN** `skeleton.json`、调用图(`build_call_graph` 产出)、`plan_scout.py` 的 scout 目标集三者
  **均不含**这些点前缀路径(单一 chokepoint,非仅 regex 候选一路排除)

#### Scenario: Non-dot build/cache dirs remain excluded (regression guard)
- **WHEN** 默认运行发现,且 `node_modules/`、`target/`、`build/` 下各有一个源文件
- **THEN** 这些文件仍被既有 `EXCLUDE_DIR` 精确匹配跳过(通用点规则不弱化既有构建目录剪枝)

#### Scenario: Windows drive root is not mis-excluded
- **WHEN** 在 Windows 上对 `C:\DEV\<repo>` 运行发现
- **THEN** 盘符根分量(`C:\`)不以 `.` 开头,不触发点前缀跳过;repo 下正常源文件照常被发现

### Requirement: Skip test source directories during discovery

确定性文件遍历(`expand_scope.walk_sources` / `collect_dir`)SHALL 在既有 `EXCLUDE_DIR` 精确匹配
与「Skip dot-prefixed paths during discovery」点前缀剪枝之外,**额外跳过**测试源码树下的源文件,使测试
源码对 regex 候选、`skeleton.json`、调用图与 scout 目标集**一致不可见**(单一 chokepoint,与点前缀
剪枝同构,非仅 regex 一路)。测试源码树按以下匹配规则判定(机械、确定性、仅用 Python 标准库
`str.startswith` / 集合 membership):

- **路径前缀**(repo 相对 posix):`src/test/`、`src/tests/`(Maven/Gradle/Kotlin 约定);
- **目录分量集合**(仅目录段、**非**文件名):`tests`、`__tests__`、`__mocks__`、`spec`、`specs`。

匹配器 SHALL **不含**裸单数 `test` 作目录段(碰撞风险最高:生产 `com/acme/test/` 工具包、Go `test` 包);
单数 `test/` 仅由 `src/test` 前缀覆盖。该跳过 SHALL 作为文件枚举层的属性,统一作用于全部下游阶段。

`discover_controls.py` SHALL 提供 `--include-tests` flag(默认关 = 排除);传该 flag 时 SHALL 回退到
引入本要求前的行为(纳入测试源码树)。理由:测试代码**不上线**且为**派生物**;对「发现生产安全控制」
这一目标以**反信号**为主——`mock`/`stub`/`@MockBean` 把安全组件物化成调用图里的伪控制、故意写脆弱的
测试夹具(渗透训练 `VulnerableApp`、负路径样本、禁用 TLS / 放宽 CORS / 占位密钥 / dummy JWT issuer 的
test 配置)被当成真实控制特征命中产出错误规则、并在大型仓白烧 scout/induct 的 LLM 预算(Java/Gradle 仓
`src/test` 常占 30–50% 源文件)。既有 `EXCLUDE_DIR` 集合**保持不变**(测试剪枝是并行独立规则,不吸收其
构建/缓存成员)。本要求仅用 Python 标准库(`pathlib.Parts` / `str.startswith` / 集合),承 R2 零运行时依赖。

`expand_scope.walk_sources` / `collect_dir` 的新参数 `include_tests` SHALL **默认 True**(保持现状,
使不经该参数的调用方——含 mgh-sast 的 `build_call_graph`——行为逐字不变);**仅** `discover_controls`
(mgh-init)的 `collect_sources`/`run_discover`/`scan`/`resolve_seed` 链以默认 `include_tests=False`
(排除)调用,并由 `main` 经 `--include-tests` store_true 绑定。该极性不对称是有意的非跨命令设计
(mgh-sast 的测试排除是独立后续变更,见 design.md D2)。

discover stdout 摘要(partial 与 full 两路 JSON)SHALL 新增 `tests_skipped`(本次跳过的测试源文件数,
非负整数),逐字并列于既有 `dotfiles_skipped`。`--check`(R5.9)SHALL 校验该字段存在且为非负整数,否则
fail-loud(退出码 2)。

#### Scenario: Maven src/test sources are skipped by default

- **WHEN** 目标项目含 `src/test/java/com/acme/SecurityTest.java`(匹配控制特征如鉴权关键字),且未传
  `--include-tests`
- **THEN** 该文件不出现在 `controls_candidates.json`、`skeleton.json`、调用图、scout 目标集中;
  discover stdout `tests_skipped` ≥1

#### Scenario: Ecosystem test roots are skipped (tests / __tests__ / spec)

- **WHEN** 目标项目分别含 `tests/test_auth.py`、`src/__tests__/auth.test.ts`、`spec/auth_spec.rb`
  (各匹配控制特征),且未传 `--include-tests`
- **THEN** 这些文件均被跳过(目录段命中 `tests`/`__tests__`/`spec`),不出现在候选/skeleton/调用图/scout
  目标集;`tests_skipped` 反映三者

#### Scenario: --include-tests re-includes test source trees

- **WHEN** 运行 `discover_controls.py --repo . --out .mgh-init --include-tests`,且 `src/test/` 下含一个
  匹配控制特征的源文件
- **THEN** 该文件被纳入候选/skeleton/调用图(行为等价于引入本要求前),不被测试目录规则跳过

#### Scenario: Test-dir skip is consistent across all downstream stages

- **WHEN** 默认运行 `discover_controls.py`,且 `src/test/` 与 `tests/` 下各有一个源文件
- **THEN** `skeleton.json`、调用图(`build_call_graph` 产出)、`plan_scout.py` 的 scout 目标集三者
  **均不含**这些测试路径(单一 chokepoint,非仅 regex 候选一路排除)

#### Scenario: Bare singular test dir is NOT excluded (regression guard)

- **WHEN** 目标项目含 `src/main/java/com/acme/test/Helper.java`(生产代码落在单数 `test` 目录段下),
  且未传 `--include-tests`
- **THEN** 该文件仍被纳入发现(单数裸 `test` 不在匹配段集合内);仅 `src/test/` 前缀与复数/生态专用段
  (`tests`/`__tests__`/`__mocks__`/`spec`/`specs`)触发跳过

#### Scenario: Non-test build/cache dirs remain excluded (regression guard)

- **WHEN** 默认运行发现,且 `node_modules/`、`target/`、`build/` 下各有一个源文件
- **THEN** 这些文件仍被既有 `EXCLUDE_DIR` 精确匹配跳过(测试目录规则不弱化既有构建目录剪枝)

#### Scenario: mgh-sast call-graph behavior is unchanged

- **WHEN** 审阅 `expand_scope.build_call_graph`(不经 `include_tests` 参数)对含 `src/test/` 的仓运行
- **THEN** 测试源码仍被纳入调用图(共享函数默认 `include_tests=True`;本要求仅 `discover_controls` opt-in
  排除,mgh-sast 行为逐字不变)

#### Scenario: --include-tests is a recognized contract flag

- **WHEN** 以 `discover_controls.py --repo . --out ./.mgh-init --include-tests` 执行
- **THEN** argparse 不报「unrecognized argument」;该 flag 出现在 `--help` 参数表(承 R5.1,`--help` 即契约面)

### Requirement: Zero runtime dependencies

`discover_controls.py` 及所有新增脚本 MUST 仅用 Python 标准库(`argparse/ast/collections/
datetime/json/math/pathlib/re/subprocess/sys` 同类)。MUST NOT `import` 任何 `vvaharness`
模块;MUST NOT 要求 Semgrep / CodeQL / tree-sitter 或任何 `pip install`。

#### Scenario: AST scan finds no third-party imports
- **WHEN** 对新增 `.py` 做 AST 扫描
- **THEN** 不存在非标准库 import,且无 `import vvaharness` / `from vvaharness import`

#### Scenario: Runs fully offline
- **WHEN** 在无网络内网环境对样例仓运行
- **THEN** i1 确定性发现阶段正常产出 `controls_candidates.json`

### Requirement: Reuse call-graph engine for control wiring

`discover_controls.py` SHALL 导入并复用 `expand_scope.build_call_graph`(D2:导入不改写),
为每个候选控制计算:`reverse`(谁调用了该控制)、`framework_files`(Spring Security 配置
等框架标记文件)、`name_to_files`(注解/方法名 → 定义文件)。经调用图关联到的入口写入
候选 `entry_points`;无法文本解析的框架路由控制(AOP pointcut / 反射 / DI)写入
`unresolved[]`。

#### Scenario: Control entry_points populated from reverse graph
- **WHEN** 一个 sanitizer 工具方法被多个 controller 调用
- **THEN** 该候选的 `entry_points` 包含这些调用方文件

#### Scenario: AOP-advised control reported unresolved
- **WHEN** 某鉴权逻辑仅通过 AOP pointcut 织入,无文本调用边
- **THEN** 该控制出现在 `unresolved[]` 而非 `entry_points`,并在 report 披露

### Requirement: Emit design_controls-compatible inventory

`controls_inventory.json` SHALL 为每条归纳后的控制携带:`name`(slug)、`kind`(vvah
6 枚举之一:`auth`/`sandbox`/`input-validation`/`aslr`/`cfi`/`other`)、`category`(细分类)、
`description`、`usage`、
`evidence`(至少一个 `file:class:method` 锚点)、`entry_points`、`protects`(fnmatch
globs,vvah 兼容)、`gaps`、`confidence`。`category → kind` 归一 MUST 确定且可测
(如 `authorization`/`authentication`→`auth`,`data-masking`/`crypto`/`csrf`/`audit`/
`rate-limiting`→`other`,`input-validation`→`input-validation`)。

#### Scenario: kind normalized from aliases
- **WHEN** 归纳出 `authorization` 类控制
- **THEN** 其 `kind` 为 `auth`,与 vvah `design_controls` 别名归一一致

#### Scenario: Every control cites concrete evidence
- **WHEN** inventory 写入一条控制
- **THEN** `evidence` 至少含一个 `file:class:method`(或 `file:line`)锚点,可被索引

### Requirement: LLM induction grounded in evidence

`init-induct` subagent SHALL 仅基于 i1 候选 + 相关文件摘录归纳控制语义(这是什么、怎么用、
入口、缺口)。MUST NOT 凭空生成无证据支撑的控制;低证据候选 MUST 降 `confidence` 或丢弃。
归纳提示词 SHALL 带溯源注释(若移植 vvah 片段标注 `Source:`;纯自创标注
`rewrite-original`)。

#### Scenario: Hallucinated control without evidence is dropped
- **WHEN** LLM 试图归纳一条 i1 候选中无任何文件证据的控制
- **THEN** 该控制被丢弃或标 `confidence: low`,不进入高置信 inventory

### Requirement: Isolated per-cluster induction with cross-cluster synthesis

归纳 SHALL 按 **T1/T2 两层**执行(D12):T1 为**每个控制簇**扇出一个**独立 subagent 上下文**,
仅读该簇文件集(大文件先分片)+ 候选元数据,产出结构化控制记录且**不得做 canonical 判定**
(隔离单元看不到别簇);T2 为单一综合上下文,仅读全部 T1 的**结构化记录**(无原始码),
完成跨模块聚类、canonical/role 选定(D8)、去重与命名归一。出 rules SHALL 按 **T3/T4 两层**:
T3 每 category 一个独立上下文出草稿,T4 可选一致性 pass。**隔离单元边界 = checkpoint 单元
边界**(同一边界同时服务质量与可恢复)。

#### Scenario: Each cluster induced in its own isolated context
- **WHEN** 一个项目有 3 个独立控制簇(鉴权 filter、脱敏工具、加密工具)
- **THEN** 产出 ≥3 个独立 T1 subagent 上下文,各自只读本簇文件,互不串扰

#### Scenario: Canonical decided in synthesis, not in isolated units
- **WHEN** 两个模块各自被独立 T1 归纳出鉴权控制
- **THEN** canonical/competing 判定发生在 T2 综合(可见两者);T1 记录中不含 canonical 判定

#### Scenario: Synthesis operates on structured records only
- **WHEN** T2 综合运行
- **THEN** 其输入为 T1 结构化 JSON 记录(无原始源码),上下文规模远小于任一 T1

### Requirement: Disclose honesty boundaries in artifacts

`report.md` 与 `init_manifest.json` MUST 明示五条边界:(1) 控制为「**存在**」非「**有效**」
(引用 CVE-2025-41248:参数化类型上 `@PreAuthorize` 可绕过);(2) 调用图为文本/AST 级,
漏 AOP/反射/DI/框架路由,未解析项见 `unresolved[]`;(3) 归纳结果为 LLM 候选,**需人工复核**;
(4) **点前缀路径(tooling/VCS/IDE/build/config/索引,如 `.opencode`/`.claude`/`.codegraph`/
`.github`)默认不扫描**——若目标项目的安全控制定义点落在 `.xxx` 内,默认不会被发现,须传
`--include-dotfiles` 才纳入;(5) **测试源码树(`src/test`/`src/tests` 前缀与 `tests`/`__tests__`/
`__mocks__`/`spec`/`specs` 目录段)默认不扫描**——若目标项目的安全控制定义点落在测试目录内,默认不会
被发现,须传 `--include-tests` 才纳入;discover stdout `tests_skipped` 计本次跳过的测试源文件数。

#### Scenario: Manifest carries all five disclaimers
- **WHEN** 一次运行完成
- **THEN** `init_manifest.json` 含上述五条边界声明的可识别字段

#### Scenario: Dot-prefix skip boundary is disclosed
- **WHEN** 审阅默认运行产出的 `report.md` / `init_manifest.json::boundaries[]`
- **THEN** 其中明示「点前缀路径默认不扫描,控制定义点在 `.xxx` 内须传 `--include-dotfiles`」,
  并指向该 flag

#### Scenario: Test-dir skip boundary is disclosed

- **WHEN** 审阅默认运行产出的 `report.md` / `init_manifest.json::boundaries[]`
- **THEN** 其中明示「测试源码树(`src/test`/`tests`/`__tests__`/`spec`/`specs`)默认不扫描,控制定义点
  在测试目录内须传 `--include-tests`」,并指向该 flag;discover stdout `tests_skipped` 计本次跳过数

### Requirement: Shard large files for stable LLM analysis

单文件超过 `--big-file-bytes`(默认 200KB)时,系统 SHALL 先用 `chunk_sources.py`
做**确定性 AST 骨架**(imports/顶层 class/method 签名/注解,零 LLM),再只把「控制候选
函数体 ± 上下文窗口」作为切片喂给 induct,**不得整文件塞入 LLM 上下文**。非 AST 语言
SHALL 回退到带重叠的行窗口。对大文件 shard 的归纳结果,系统 MAY 再跑一道 verify
pass 交叉核验,不一致时降 `confidence`。

#### Scenario: Big file is sharded, not fed whole
- **WHEN** 一个 250KB 的 `LegacyAuthFilter.java` 含控制候选
- **THEN** induct 收到的是候选函数切片(含上下文窗口),而非整文件;切片来自 AST 骨架定位

#### Scenario: Shard disagreement lowers confidence
- **WHEN** 大文件某 shard 的归纳与 verify pass 核验不一致
- **THEN** 该控制 `confidence` 被下调,并在 report 标注

### Requirement: Cluster competing controls and designate canonical

当同 `category`(如 authorization、data-masking)存在 2+ 候选时,i2 归纳 SHALL 将其
聚类,按 canonicality 加权(框架背书 / 调用图入度 / `security`·`common`·`config` 包位置 /
注解化)选定主实现。每条控制 inventory 项 SHALL 带 `cluster_id` 与
`role∈{canonical,competing,duplicate,possibly-dead}`。非 canonical 控制 **MUST 保留**
(只标 role、不删)。report SHALL 含「竞争控制」专节。

#### Scenario: Two auth implementations clustered with canonical picked
- **WHEN** 项目同时存在 Spring `SecurityConfig` 过滤器链与一套散落的 `if(user.isAdmin())`
- **THEN** 两者归入同一 `cluster_id`,前者 `role: canonical`(框架背书 + 高入度),后者
  `role: competing`,两者均保留进 inventory

#### Scenario: Canonical selection surfaces bypass candidates
- **WHEN** 存在标为 canonical 的鉴权控制
- **THEN** report「竞争控制」专节列出非 canonical / possibly-dead 实现,供 `/mgh-blst`
  据此找未走 canonical 的接口

### Requirement: Resumable, checkpointed execution

系统 SHALL 按工作单元 checkpoint:`i1` 按文件(大文件按 shard)、`i2` 按 cluster、
`i3` 按 category,每单元落 `<target>/.mgh-init/checkpoints/<unit>.json` + done 标记。
`--resume` SHALL 跳过已完成单元并合并 parts。调用图 SHALL 缓存到
`<target>/.mgh-init/cache/callgraph.json`(全仓建一次;`--rebuild-cache` 或源文件 mtime
变化时失效重建)。

#### Scenario: Resume skips completed units
- **WHEN** 一次运行中途断开,随后 `mgh-init --resume`
- **THEN** 已 done 的文件/cluster/category 单元被跳过,仅继续未完成单元,产物最终完整

#### Scenario: Call graph cached across runs
- **WHEN** 源文件未变更,第二次运行
- **THEN** 复用 `cache/callgraph.json`,不重建全图

### Requirement: Scoped and partial-merge analysis

`--scope path:<dir>|package:<pkg>|file:<glob>` SHALL 限定分析种子。`--scope-mode`
SHALL 区分:`defined`(默认,控制定义点在 scope 内)与 `applicable`(控制调用方/入口
触及 scope)。跨模块但定义点在 scope 外的控制 SHALL 记入 `out_of_scope[]`(披露不丢)。
`mgh-init --merge <partials-dir>` SHALL 按 `evidence`(`file:class:method`)去重合并
多次局部产物,并跨模块重算 cluster role。

#### Scenario: Scoped run bounds to a module
- **WHEN** `mgh-init --scope path:src/payment --scope-mode defined`
- **THEN** 仅分析定义点在 `src/payment` 内的控制;跨模块控制入 `out_of_scope[]`

#### Scenario: Partial runs merge by evidence anchor
- **WHEN** 对模块 A、B 各跑一次局部 init,再 `mgh-init --merge partials/`
- **THEN** 合并后 inventory 按 `file:class:method` 去重,同一控制不重复,cluster role 跨模块重算

### Requirement: Standalone script invocation robustness

`discover_controls.py` 与 `chunk_sources.py` SHALL 在 `from expand_scope import …` 之前,把
**本脚本所在目录**显式插入 `sys.path`(`sys.path.insert(0, str(Path(__file__).resolve().parent))`),
使其在**任意工作目录**、经**宿主 agent 的任意调用方式**(直接 `py`/`python` 执行)下都能定位同目录
的 `expand_scope.py`。两脚本 MUST NOT 仅依赖「运行时自动把脚本目录加入 `sys.path[0]`」这一隐式行为
来保障兄弟导入,MUST NOT 要求用户以 `python -c "exec(…)"` 方式绕行(该方式在 Windows 中文 locale
下会触发 gbk 解码错误)。

#### Scenario: Runs from a different working directory
- **WHEN** 宿主 agent 从目标仓根目录(非脚本所在目录)执行 `py <path>/discover_controls.py --repo . --out ./.mgh-init`
- **THEN** 脚本成功 import `expand_scope`,不报 `No module named 'expand_scope'`,正常产出 candidates/clusters

#### Scenario: Direct execution needs no python -c workaround
- **WHEN** 用户按文档以 `py`/`python` 直接执行 `chunk_sources.py` / `discover_controls.py`
- **THEN** 无需借助 `python -c "exec(open(...).read())"` 即可运行,从而不触发 Windows gbk 编码错误

### Requirement: Bounded single-pass scan performance on large repos

`discover_controls.py` SHALL 对每个源文件**至多读一次磁盘**(读入后缓存文本,供调用图两遍与候选
扫描共用);`walk_sources(repo)` 在单次运行中**只遍历一次**仓库并物化文件清单,供调用图构建与候选
扫描复用;每文件**仅调用一次 `splitlines()`**;候选的 enclosing 锚点 SHALL 通过**每文件预排序的
结构节点列表 + 按行二分**求解,而非「每候选对全文反复 `finditer`」。系统 SHALL 在扫描期间向
**stderr** 周期输出进度(每 N 个文件),stdout 仅在末尾输出既有 JSON 摘要(契约不变)。在 i0 阶段
SHALL 以低成本统计源文件数,命中大仓阈值时**在开始全量扫描前**主动建议 `--scope` 分模块 + `--merge`。

本要求**不再假设 discover 在单次宿主调用内必然完成**:当目标仓大到单次调用超过宿主 shell 超时
(claude Bash / opencode shell 工具默认 120s,可被强杀于更早),discover SHALL 经 callgraph 缓存 +
scan 续点 + 软时限干净早退(见「Discover call-graph cache survives re-runs」「Discover scan resumes
from a checkpoint」「Discover soft time-budget clean exit」「Discover writes are atomic」)**跨多次
编排器调用推进且零全损**,而非依赖「5 分钟内一发跑完」。

#### Scenario: Large repo completes across re-invocations without total loss
- **WHEN** 对一个单次调用即超过宿主 shell 超时的大目标仓运行 `/mgh-init`,且某次 discover 调用被宿主
  在超时处强杀
- **THEN** 已建成的 callgraph 缓存与 scan 续点**留存可用**,编排器 Bash 重派 `discover ... --resume`
  复用缓存、从续点继续,**不**从零重跑;经有限次重派后产物完整,期间**无**「`(no output)` 全损」形态

#### Scenario: Each source file read at most once
- **WHEN** 对任意目标仓运行发现脚本(单次调用内)
- **THEN** 每个源文件的磁盘读取次数为 1(调用图两遍与候选扫描共用同一缓存文本)

#### Scenario: Progress emitted to stderr only
- **WHEN** 扫描持续进行且尚未完成
- **THEN** stderr 周期性打印已扫描文件数;stdout 不在中途打印非 JSON 内容,末尾 JSON 摘要契约不变

#### Scenario: Large repo advised to scope before scanning
- **WHEN** i0 阶段统计的源文件数超过阈值
- **THEN** 系统在开始全量扫描前提示建议 `--scope` 分模块 + `--merge`,而非静默跑到超时

### Requirement: Deterministic scripts are orchestrator black boxes

`/mgh-init` 的编排器是宿主 agent 本身(按 `mgh-init.md` 用自身工具跑流水线,非写代码)。命令壳 SHALL 在正文最前列声明,且把编排纪律明线**扩展到一次性微脚本**(承
`harden-mgh-init-orchestration-discipline` FD1:真机失败形状是微脚本内省,非大编排器)。agent
**MUST NOT**(硬边界,`NEVER`):

- (a) `Write` 任何 `.py`——含大编排器(`mgh_init.py`)与**一次性微脚本**(`py -c` 产物、`_prep_scout_batches.py`、
  `_aggregate_scout.py`、`<run>_helper.py` 等);
- (b) 经 `Bash` 运行 `py -c` / `python -c` 去**内省或重派生**产物(`import json` / `open(` / `load(` 读
  `.mgh-init/**` 之类);
- (c) `Read` 叶子脚本 `.py` 源码进编排上下文(报错看 stderr)。

`Write`/`Edit` 仅用于产物。调用示例 SHALL 只传脚本声明的 flag——`--format` 由 T3 `init-rulewriter`
消费,`discover_controls.py` 不接受 `--format`。当 agent 需要「工作清单 / 瞄一眼结构 / 派生量」时,
SHALL 走 implementation-intention 句式声明的合法出口:工作清单 → `list_clusters.py` /
`list_scout_batches.py` / `list_rule_jobs.py`;瞄结构 → `describe_artifact.py`;派生量 → 该量产出者
的 stdout 字段(见「Derived counts exposed as script output」)。命令壳 SHALL 在编排流以刚性三元组
`[输入产物::字段] → script/subagent → [输出产物::字段]` 表述每个 fan-out 步骤,并在 doubt 时刻内联
1 行 shape。

#### Scenario: No orchestrator or helper script is created
- **WHEN** 宿主 agent 执行 `/mgh-init`,需要取得 scout 待跑批清单
- **THEN** agent 调用 `list_scout_batches.py`,**不** `Write` `_prep_scout_batches.py` 之类一次性 `.py`,
  也**不** `py -c "import json…"` 挖 `scout_plan.json`

#### Scenario: Discover script not passed --format
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md` 中 `discover_controls.py` 的调用示例
- **THEN** 这些示例不含 `--format`;`--format` 仅出现在 T3 `init-rulewriter` 阶段的描述中

#### Scenario: Scripts invoked, not read, by the orchestrator
- **WHEN** 编排器执行 i1 发现阶段
- **THEN** `discover_controls.py` / `chunk_sources.py` / `expand_scope.py` 经 Bash 执行,其源码不被 `Read` 进编排上下文

#### Scenario: Discover accepts its documented flags
- **WHEN** 以 `discover_controls.py --repo . --out ./.mgh-init`(不带 `--format`)执行
- **THEN** argparse 不报「unrecognized argument」,脚本正常进入扫描

#### Scenario: Structure-understanding reflex routes to sanctioned primitive
- **WHEN** 编排器想确认 `controls_candidates.json` / `scout_plan.json` 的结构再动手
- **THEN** 它调用 `describe_artifact.py --keys/--sample/--shape`,**不** `py -c` 读 `[0]` 或 list keys

### Requirement: Cluster inventory file contract

`clusters.json`(由 `discover_controls.py` 产出)MUST 是一个**包装字典**`{repo, clusters[], truncated}`,
其中 `clusters[]` 为 T1 隔离单元列表,**不是**顶层数组。每条 Cluster 记录 SHALL 携带
`cluster_id`、`category`、`kind`、`shape∈{centralized,distributed}`、`evidence_files[]`、
`usage_sites[]`、`candidate_ids[]`(源 `discover_controls.py:409` 的 `form_clusters`)。簇级
MUST NOT 携带 `entry_points`(`entry_points` 在 candidate 上,仅 distributed shape 被 set)。
该结构 SHALL 在 `core/contracts/init/clusters.md` 落定为唯一 I/O 契约。

#### Scenario: clusters.json is a wrapper dict, not a bare list
- **WHEN** `discover_controls.py` 写出 `clusters.json`
- **THEN** 顶层为对象 `{repo, clusters, truncated}`;簇列表在 `clusters` 键下,对顶层 `len()` 得 3 而非簇数

#### Scenario: Cluster record shape is documented and stable
- **WHEN** 消费者(init-induct / init-survey / list_clusters)读取一条簇
- **THEN** 该记录含 `cluster_id/category/kind/shape/evidence_files[]/usage_sites[]/candidate_ids[]`,且无簇级 `entry_points`

#### Scenario: Contract file exists as single source of truth
- **WHEN** 检查 `core/contracts/`
- **THEN** 存在 `init/clusters.md`,逐字段描述包装结构与 Cluster 记录,与 `candidates.md`/`inventory.md` 并列

### Requirement: Deterministic cluster enumeration for T1 fan-out

`/mgh-init` 的编排器 MUST 经确定性叶脚本 `core/scripts/list_clusters.py` 取得 T1 工作清单,
MUST NOT 手搓 `py -c "import json…"` 式内省、MUST NOT 对 `clusters.json` 顶层做 `len()`
(那是包装字典的 key 数,非簇数)、MUST NOT **整份读** `clusters.json` 进编排器上下文(完整记录经
`--materialize` 下沉到 per-unit input 文件,见 `request-context-budget`)。`list_clusters.py` SHALL 读
`<target>/.mgh-init/clusters.json` 并扫 `<target>/.mgh-init/checkpoints/t1/*.done`,stdout 输出结构化
JSON `{repo,total,done,pending[],truncated,offset,limit,effective_limit,shrunk}`,`pending[]` 每项为
**slim 壳**`{cluster_id,category,kind,shape,candidate_count,input_path,checkpoint_path,done_marker,bytes,oversize}`
(**不含** `evidence_files[]`/`usage_sites[]`/候选命中——已下沉进 `input_path` 文件);stderr 仅走诊断/进度;
退出码 `0/1/2`。脚本 SHALL 支持 `--materialize <dir>`(把每簇完整输入写到
`<dir>/<cluster_id>.input.json` + 报 `input_path`/`bytes`/`oversize`,无该 flag 时回退 read-only lite 壳
向后兼容)、`--offset`/`--limit`(分页)、`--max-unit-bytes`(超阈值簇切分为 `<cluster_id>::shard-<n>`
子单元或标 `oversize`)。当某页序列化字节 > `--orch-budget-bytes` 时 SHALL 自动收紧 `--limit`、报
`effective_limit`+`shrunk:true`。脚本的 `--help` 即其 CLI 契约(承 R5.1)。簇数权威真相源 =
`discover_controls.py` stdout `clusters` 字段 或 `list_clusters.py` stdout `total`。

#### Scenario: Orchestrator enumerates clusters via the leaf script
- **WHEN** 编排器进入 T1 fan-out(步骤 4)
- **THEN** 它调用 `list_clusters.py --materialize <inputs/t1>` 取 `pending[]`,据此逐簇扇出 `init-induct`,
  向 subagent **透传 `input_path`**;不出现手搓 JSON 内省,不整份读 `clusters.json`

#### Scenario: list_clusters reports total vs done for resume
- **WHEN** 部分簇已 done(`checkpoints/t1/<cluster_id>.json.done` 存在)后再次运行
- **THEN** `list_clusters.py` stdout 的 `done` 反映已完成数,`pending[]` 仅含未完成簇,`total = done + len(pending)`

#### Scenario: list_clusters is self-contained and offline
- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_clusters.py --clusters <dir>/clusters.json --checkpoints <dir>/checkpoints/t1 --materialize <dir>/inputs/t1` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8 读入、零第三方依赖),stdout 为合法 JSON,per-unit input 文件落 `<dir>/inputs/t1/`

#### Scenario: Empty or truncated clusters handled without silent truncation
- **WHEN** `clusters.json` 的 `clusters[]` 为空,或 `truncated: true`
- **THEN** `list_clusters.py` 输出 `total:0`(空)或保留 `truncated: true`(截断显式告警),退出码仍 `0`,不静默丢信息

#### Scenario: Slim envelope excludes variable-length payload
- **WHEN** 审阅 `list_clusters.py` stdout 的 `pending[]` 元素
- **THEN** 壳含 `{cluster_id,category,kind,shape,candidate_count,input_path,checkpoint_path,done_marker,bytes,oversize}`,
  **不含** `evidence_files[]`/`usage_sites[]`(已下沉进 `input_path` 文件)

#### Scenario: Oversize cluster is sharded within the unit budget
- **WHEN** 某 cluster 物化输入 `bytes` > `--max-unit-bytes`
- **THEN** `list_clusters.py` 按 `evidence_files`/`usage_sites` 组切分为 `<cluster_id>::shard-<n>` 子单元,
  每子单元 `bytes` ≤ `--max-unit-bytes` 且有独立 `input_path`/`checkpoint_path`;`pending[]` 不出现超阈值整簇

#### Scenario: Work-list page shrinks to the orchestrator budget
- **WHEN** 一页 `pending[]` 序列化字节 > `--orch-budget-bytes`
- **THEN** `list_clusters.py` 自动收紧 `--limit`,stdout 报 `effective_limit` + `shrunk:true`(stderr 告警),
  编排器据 `offset`/`effective_limit` 翻页

### Requirement: init-survey is optional, advisory, and non-fatal

init-survey 子阶段 SHALL 是**可选**的;其产出 `i1_enriched.json` 当前仅作**审计/T2 参考**,
**不是** T1(`init-induct`)的输入(T1 直接读 `clusters.json`)。`i1_enriched.json` 缺失 MUST NOT
阻断流水线、MUST NOT 触发致命错误处理。当簇数过大(单 subagent 上下文装不下整仓簇)时,编排器
SHALL 跳过 init-survey。命令壳 MUST 在步骤 3 显式声明上述 optional/advisory/non-fatal/bounded 语义。

#### Scenario: Missing i1_enriched does not break the run
- **WHEN** init-survey 未产出 `i1_enriched.json`(被跳过或返回空)
- **THEN** 编排器不报致命错误,T1 继续从 `clusters.json` 正常扇出

#### Scenario: init-survey skipped on large cluster count
- **WHEN** `list_clusters.total` 超过壳声明的上界
- **THEN** 编排器跳过 init-survey 步骤,直接进入 T1,并在摘要披露该跳过

#### Scenario: Shell declares the advisory semantics
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md` 步骤 3
- **THEN** 两壳均显式标注 init-survey 为 optional + advisory(非 T1 输入)+ non-fatal + 大簇跳过

### Requirement: Inventory human-readable fields exclude tool-internal content

`controls_inventory.json` 的面向人读字段 SHALL 只描述目标项目的安全控制本身,且 MUST NOT
携带任何本工具内部信息。受约束的人读字段为 `description`、`usage`、`gaps`、`notes`、
`competing_clusters[].note`。被禁止的工具内部信息包括:本工具名、发现/归纳脚本名
(`discover_controls.py`、`chunk_sources.py`、`plan_scout.py`、`merge_scout.py`、
`list_clusters.py`、`assemble_rules.py` 等)、作为过程描述的流水线层级标签
(`T1`、`T2`、`T3`、`scout`)、内部路径(`.mgh-init/`、`checkpoints/`),以及
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

### Requirement: Extract lossless source skeleton for LLM selection

`discover_controls.py` SHALL 在其既有单遍文件遍历中,为**每个**源文件机械抽取一份
**无损骨架**并 emit 到 `skeleton.json`,字段:`file`、`lang`、`pkg`(由相对路径推)、
`classes[]`(复用既有 `CLASS_RX`)、`method_sigs[]`(复用 `JAVA_DEF`/`DEF_CALL`)、
`imports[]`(新增按 `lang` 分派的 `import`/`#include`/`require`/`from…import` 正则)、
`fan_in`(来自既有 reverse graph)、`bytes`。抽取 MUST NOT 判定「该文件是否为安全控制」
——骨架仅是供 LLM 选择「读谁」的廉价元数据,所有语义判断留给 scout 层。抽取 MUST 复用
既有单遍 I/O(每文件至多读一次),MUST NOT 引入对仓库的第二次遍历。

#### Scenario: Skeleton carries mechanical metadata only
- **WHEN** `discover_controls.py` 运行
- **THEN** `skeleton.json` 每条含 `pkg/classes/imports/method_sigs/fan_in/bytes`,且不含
  「是否控制」之类的语义判定字段

#### Scenario: Skeleton covers files the regex skipped
- **WHEN** 某文件不含任何规范 token(被 `_QUICK_RX` 预过滤跳过)
- **THEN** 该文件仍出现在 `skeleton.json` 中(预过滤只跳过 regex 候选生成,不跳过骨架抽取)

#### Scenario: Single-pass extraction without a second walk
- **WHEN** 对任意目标仓运行发现脚本
- **THEN** 仓库源文件遍历次数为 1(骨架抽取搭 regex 扫描与调用图构建的同一次遍历)

### Requirement: LLM scout discovers controls beyond the token allowlist

`/mgh-init` SHALL 在 i1 与 T1 之间插入一个 **LLM scout 发现层**:scout subagent 读取
`skeleton.json` 中的目标行 + repo root,**自适应地**(无固定词表)用自身工具(Glob/Grep/
Read)寻找 regex 漏掉的自研安全控制,对确认者按 Candidate schema 子集产出锚点候选
(`file/line/category/kind/anchor/shape/evidence_snippet/confidence`),每条带
`source: "scout"`。scout 输出 SHALL 经 `scout_candidates.json` 与 regex 候选**并集**
后,走既有 `form_clusters`(簇形成逻辑不变)。每条 scout 候选 MUST ground 在该 subagent
实际 Read 过的真实 `file:line`;无证据的候选 MUST 降 `confidence` 或丢弃。scout 发现
DI/AOP/反射等文本调用图无法解析的控制时,SHALL 并入既有 `unresolved[]` 并标 `source`。

#### Scenario: Custom control found by scout, missed by regex
- **WHEN** 项目含一个零规范 token 的自研鉴权 `PermGuard`,且未传 `--no-scout`
- **THEN** scout 层产出一条 `source: "scout"` 的 authorization 候选,其 evidence 指向真实
  Read 过的 `PermGuard` 锚点;该控制进入候选并集并形成簇

#### Scenario: Scout proposal without evidence is dropped
- **WHEN** scout subagent 试图产出一个未实际 Read 过文件证据的候选
- **THEN** 该候选被丢弃或标 `confidence: low`,不进入高置信候选集

#### Scenario: No-scout flag preserves legacy regex-only behavior
- **WHEN** 运行 `mgh-init --no-scout`
- **THEN** scout 层不执行,候选集仅含 `source: "regex"`(等价于引入 scout 前的行为)

### Requirement: Fan out scout across parallel isolated byte-bounded batches

scout 深读 SHALL 按**隔离 fan-out**执行(对标 D12 T1→T2 同构):确定性脚本
`plan_scout.py` 对 `skeleton.json` 做噪声剪枝(复用 `EXCLUDE_DIR`)+ 去除 regex 已命中
文件后,把剩余 scout 目标按**字节预算**切批——每批累计 `bytes ≤ --scout-batch-bytes`
(默认 96KB),且分批前先按 `pkg` 排序以**包内聚**(同目录相关文件落同批),每批文件数
MUST NOT 超过 `--scout-batch-cap`(默认 40)。单个 `bytes > --scout-batch-bytes` 的文件
MUST 经既有 `chunk_sources.py` 切片入批,MUST NOT 整文件塞入单个 LLM 上下文。每批在一个
**独立 scout-reader subagent 上下文**深读,产出 `checkpoints/scout/<batch_id>.json`;全部
批次完成后由**单一 scout-merge subagent** 在**仅结构化记录、无原始码**上做去重、归一、
provisional `source` 标记 → `scout_candidates.json`。编排器 SHALL 以 `max_concurrent`
(默认 8)并行起 subagent、跑完一波起下一波,直至无 pending 批次。批数(= subagent 数)
SHALL 由 `ceil(Σtarget_bytes / batch_bytes)` **涌现而出**,而非固定常量。每批 SHALL 落
`checkpoints/scout/<batch_id>.json.done`;`--resume` MUST 跳过已 done 批次。

编排器取得「待跑批清单」MUST 经确定性叶脚本 `list_scout_batches.py`(见「Deterministic
scout-batch enumeration for fan-out」),MUST NOT 手挖 `scout_plan.json`、MUST NOT `py -c`
内省。`merge_scout.py` 折叠后,`scout_candidates.json` 与改写后的 `controls_candidates.json`
为**终态**,编排器 MUST NOT 对其二次聚合或重切批。

#### Scenario: Batches sized by bytes, co-located by package
- **WHEN** scout 目标含同一 `com/acme/security/` 包下的多个相关文件
- **THEN** `scout_plan.json` 的某批同时包含这些文件,且该批累计 bytes ≤ `--scout-batch-bytes`

#### Scenario: Oversize single file is sliced, not fed whole
- **WHEN** scout 目标含一个 250KB 的 `LegacyGuard.java`,而 `--scout-batch-bytes` 为 96KB
- **THEN** 该文件经 `chunk_sources.py` 切成函数切片入批,而非整文件塞入一个 scout-reader

#### Scenario: Batch count emerges from data, parallel waves bounded
- **WHEN** scout 目标共 ~9.6MB、`--scout-batch-bytes` 96KB、`max_concurrent` 8
- **THEN** `scout_plan.json` 产出约 100 批,编排器以每波 8 并行跑完所有批

#### Scenario: Merge operates on structured records only
- **WHEN** scout-merge 运行
- **THEN** 其输入为各 batch 的结构化候选 JSON(无原始源码),上下文规模远小于任一
  scout-reader;跨批重复报告的同一控制被去重归一

#### Scenario: Resume skips completed batches
- **WHEN** scout fan-out 中途断开,随后 `mgh-init --resume`
- **THEN** 已 done 的批次被跳过,仅继续 pending 批次,`scout_candidates.json` 最终完整

#### Scenario: Pending work-list obtained via leaf script, not hand-mining
- **WHEN** 编排器进入 scout fan-out
- **THEN** 它先调用 `list_scout_batches.py` 取 `pending[]` 再逐批扇出;不出现 `py -c` 挖 `scout_plan.json` 或 `Write _prep_scout_batches.py`

#### Scenario: Merged artifacts are terminal
- **WHEN** `merge_scout.py` 完成,`scout_candidates.json` 落盘
- **THEN** 编排器不再对其二次聚合或重切批(不出现 `_aggregate_scout.py` 之类重实现)

### Requirement: Self-audit scout rejections to bound false negatives

scout 批次完成后,系统 SHALL 随机抽取 `--scout-audit-pct`(默认 15%)个被 scout 判定
「无控制」的目标,交一个**怀疑论偏置**的 `init-scout-audit` subagent 复核(对标 s6
「assume WRONG until confirmed」):尝试证明该目标**实为**被漏报的控制。若审计发现漏报,
SHALL 将该目标回灌(重跑其所属批次或直接补候选),并在 `init_manifest.json` 记录
`audit_found`。抽样 MUST 确定性(脚本选样,可复现)。审计 MUST NOT 对全部拒绝项 100%
复核(成本不可接受)。

#### Scenario: Audit catches a scout false negative
- **WHEN** scout 漏判一个自研脱敏工具为「无控制」,且它落入 audit 抽样
- **THEN** audit subagent 复核发现它实为 data-masking 控制,该候选被补回候选集,manifest
  的 `audit_found` 计数 +1

#### Scenario: Audit sample is deterministic and bounded
- **WHEN** 对同一 skeleton 两次运行(同 seed)
- **THEN** audit 抽到的目标集相同;且抽样数 = `ceil(rejected × audit_pct)`,非全量复核

### Requirement: Disclose scout coverage and residual blind spot

`init_manifest.json` SHALL 增 `scout` 段,记录:`skeleton_total`、`scout_targets`、
`batches`、`deep_read_files`、`audit_sampled`、`audit_found`、`scout_merged`(fold-in 实际并入
`controls_candidates.json` 的 scout 候选数,取值于 `merge_scout.py` 写入的
`provenance.scout_merged`;scout 未启用时该字段 SHALL 缺省/为空)、`truncated`(目标超预算时为真
并建议 `--scope`+`--merge`)。`report.md` 与 `init_manifest.json` 的 `boundaries[]` SHALL
新增披露:(1) scout 实际审视了 `skeleton_total` 中的多少、深度 Read 了多少、自检了多少
(**不声称全仓覆盖**);(2) scout 非确定,簇数 run-to-run 可能变化(regex 来源簇仍确定);
(3) 残留盲区——泛型包 + 泛型类名 + 泛型签名 + 无安全导入 + 低扇因的控制,规则与骨架均
无法识别,可能漏报。既有三条诚实边界(存在≠有效 / 调用图盲点 / 需人工复核)保持不变。

#### Scenario: Manifest reports real scout coverage numbers
- **WHEN** 一次含 scout 的运行完成
- **THEN** `init_manifest.json` 的 `scout` 段含可识别的真实计数字段(含 `scout_merged`),且不出现
  「全仓覆盖」之类断言

#### Scenario: Manifest omits scout_merged when scout disabled
- **WHEN** `--no-scout` 运行完成
- **THEN** `init_manifest.json` 的 `scout` 段不含 `scout_merged`(或为空),不声称 scout 并入量

#### Scenario: Residual blind spot is disclosed
- **WHEN** 审阅 `report.md` / `init_manifest.json` 的 `boundaries[]`
- **THEN** 其中明示「泛型命名 + 低扇因控制可能漏报」这一残留盲区,以及 scout 的非确定性

### Requirement: Deterministic scout-batch enumeration for fan-out

`/mgh-init` 的编排器 MUST 经确定性叶脚本 `core/scripts/list_scout_batches.py` 取得 scout 工作清单
(对标 T1 的 `list_clusters.py`,闭合 FD3 的扇出不对称),MUST NOT **整份读** `scout_plan.json` 进编排器
上下文。`list_scout_batches.py` SHALL 读 `<target>/.mgh-init/scout_plan.json::batches[]` 并扫
`<target>/.mgh-init/checkpoints/scout/*.json.done`,stdout 输出结构化 JSON
`{repo,total,done,pending[],truncated,offset,limit,effective_limit,shrunk}`,`pending[]` 每项含
`{batch_id,targets_count,bytes,needs_slice[],input_path,checkpoint_path,done_marker,oversize}`;stderr 仅
诊断/进度;退出码 `0/1/2`;`--help` 即其 CLI 契约(承 R5.1)。`total = len(batches[])`,
`done = #已 .done`,`pending = total − done`。脚本 SHALL 支持 `--materialize <dir>`(把每批完整 `targets[]`
输入写到 `<dir>/<batch_id>.input.json` + 报 `input_path`)、`--offset`/`--limit`(分页)、
`--max-unit-bytes`(与 `plan_scout --batch-bytes` 取 `min` 作硬上限;超 `--big-file-bytes` 文件强制
`needs_slice` 走 `chunk_sources`)。当某页字节 > `--orch-budget-bytes` 时 SHALL 自动收紧 `--limit`、报
`effective_limit`+`shrunk:true`。脚本 MUST 自定位 `sys.path`、utf-8 读入、零第三方依赖、任意 cwd 可 `py`
(承 R5.3a)。

#### Scenario: Orchestrator enumerates scout batches via the leaf script
- **WHEN** 编排器进入 scout fan-out(步骤 3b)
- **THEN** 它调用 `list_scout_batches.py --materialize <inputs/scout>` 取 `pending[]`,据此逐批扇出
  `init-scout`,向 subagent **透传 `input_path`**;不出现手搓 JSON 内省,不整份读 `scout_plan.json`

#### Scenario: list_scout_batches reports total vs done for resume
- **WHEN** 部分批已 done(`checkpoints/scout/<batch_id>.json.done` 存在)后再次运行
- **THEN** stdout 的 `done` 反映已完成批数,`pending[]` 仅含未完成批,`total = done + len(pending)`

#### Scenario: list_scout_batches is self-contained and offline
- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_scout_batches.py --scout-plan <dir>/scout_plan.json --checkpoints <dir>/checkpoints/scout --materialize <dir>/inputs/scout` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8 读入、零第三方依赖),stdout 为合法 JSON,per-unit input 文件落 `<dir>/inputs/scout/`

#### Scenario: Empty or truncated scout plan handled without silent truncation
- **WHEN** `scout_plan.json::batches[]` 为空,或 `truncated: true`
- **THEN** `list_scout_batches.py` 输出 `total:0`(空)或保留 `truncated: true`(显式告警),退出码仍 `0`,不静默丢信息

#### Scenario: Oversize batch respects the unit budget via slicing
- **WHEN** 某批 input `bytes` > `--max-unit-bytes`(或含 > `--big-file-bytes` 文件)
- **THEN** 该文件入 `needs_slice[]`,`init-scout` 经 `chunk_sources.py` 切片后读 slice,NEVER 整文件喂 LLM

#### Scenario: Work-list page shrinks to the orchestrator budget
- **WHEN** 一页 `pending[]` 序列化字节 > `--orch-budget-bytes`
- **THEN** `list_scout_batches.py` 自动收紧 `--limit`,stdout 报 `effective_limit` + `shrunk:true`,编排器翻页

### Requirement: Sanctioned artifact-inspection primitive (no ad-hoc introspection)

`/mgh-init` SHALL 提供确定性叶脚本 `core/scripts/describe_artifact.py`,作为编排器/subagent
「瞄一眼产物结构」反射的**唯一合法出口**(专治「先理解结构再动手」的 `py -c` 反射,FD5)。其 SHALL
支持 `--in <json>` + 至少下列模式之一:`--keys`(顶层键)、`--count`(数组长度,对 wrapper dict 额外
warn 顶层键数 vs 目标数组长度,防 `len(wrapper)=3` 误判)、`--sample N`(数组首 N 项)、`--shape`(轻量
schema:键 + 类型 + 数组元素 shape)、`--field a.b.c`(取嵌套字段)。stdout = JSON 摘要;stderr = 诊断;
退出码 `0/1/2`;零依赖、自定位、utf-8、任意 cwd。编排器与 subagent MUST NOT 用 `py -c`/`python -c`
或 `Read` 整份大 JSON 去内省产物结构,SHALL 改用本脚本。

#### Scenario: Count mode warns on wrapper-dict miscount
- **WHEN** 对 `clusters.json`(wrapper `{repo,clusters,truncated}`)运行 `describe_artifact.py --count`
- **THEN** stdout 报 `clusters[]` 真实长度,并对顶层 3 键给出 warn(防把 3 当簇数)

#### Scenario: Sample mode replaces reading the first element by hand
- **WHEN** 编排器想理解 `scout_plan.json::batches[]` 元素结构
- **THEN** 它运行 `describe_artifact.py --sample 1`,而非 `py -c "import json; print(json.load(open(...))['batches'][0])"`

#### Scenario: describe_artifact is self-contained and offline
- **WHEN** 从任意 cwd 以 `py <path>/describe_artifact.py --in <dir>/controls_candidates.json --keys` 执行
- **THEN** 脚本成功,stdout 为合法 JSON 摘要

### Requirement: Derived counts exposed as script output fields

下游(编排器/subagent)可能需要 list keys / len / sample 才能得到的**派生量**,MUST 由该量的**产出者**
作为 stdout 字段 emit,而非留给下游现算(消除「自己写脚本算」的动机,FD6)。具体:`plan_scout.py`
stdout 与 `scout_plan.json` 顶层 SHALL 含 `regex_known_count`(= 已被 regex 命中、排除出 scout 的文件数,
内部 `regex_files` 已算);`discover_controls.py` stdout 摘要 SHALL 含 `big_files`、`unresolved_count`
等下游常查量(不删既有字段)。派生量字段 SHALL 在对应 `core/contracts/init/*.md` 落定。

#### Scenario: regex_known count available without re-derivation
- **WHEN** 编排器需要「多少文件已被 regex 命中、不需 scout」
- **THEN** 它读 `plan_scout.py` stdout 的 `regex_known_count`,而非 `py -c` 集合运算 `controls_candidates.json`

#### Scenario: discover summary carries downstream-queried counts
- **WHEN** `discover_controls.py` 完成
- **THEN** 其 stdout 摘要含 `big_files` 与 `unresolved_count` 等字段,供编排器直接消费

### Requirement: Runtime enforcement hook for orchestrator script discipline

`install.sh` SHALL 在镜像 `core/` 后,**双端对等**注入运行时纪律守卫 `block_adhoc_scripts`(单一
Python 标准库脚本、零运行时依赖,承 R2),使 Claude Code 与 opencode 用户获得对等的运行时强制:

- **claude**:`install_hook.py` 向目标 `.claude/settings.json` 的 `PreToolUse` **幂等追加**一条命令
  hook(matcher `Bash|Write|Edit` → `py .claude/hooks/block_adhoc_scripts.py`)。
- **opencode**:`install_opencode_plugin.py` 向目标 `.opencode/plugins/` **幂等落**一个订阅
  `tool.execute.before` 的 `.ts` 插件(`block_adhoc_scripts.ts`)。opencode 的 hook 形态即 JS/TS
  插件(非 Claude 的 settings.json 命令式 hook),等价事件为 `tool.execute.before`(pre-tool,可阻断)/
  `tool.execute.after`(post-tool)。该插件是 opencode 原生胶水(非 Python `pip` 依赖),把 opencode
  工具事件**归一化**为 Claude PreToolUse 的 stdin 形态(`{tool_name, tool_input}`),管道喂给**同一**
  `block_adhoc_scripts.py`,据其退出码 2 阻断该工具调用、否则放行。

守卫的**激活模型 + 运行域写入纪律**由共享契约 [`runtime-hook-enforcement`](../runtime-hook-enforcement/spec.md)
单一规定(取代此前散在本要求内的 env-only 激活 + `core/scripts` 白名单措辞):激活 = `MGH_INIT_ACTIVE=1`
env **或** `<cwd>/.mgh-init/.active` 哨兵(编排器 step 0 经 `Bash` 写、run 完成/干净停止移除);运行域内
一切脚本扩展名(`.py`/`.ps1`/`.sh`/`.ts`/…)写入均 fail-loud——**取消**既有 `core/scripts`/`tests`/
`tools`/`hooks` 白名单豁免(叶脚本对 agent 为 read-only);init 域 `Write`/`Edit` 须落入受信子树(见
「Init write confinement to sanctioned subtrees」)。既有 `py -c`/`python -c` 内省拦截 + 多单元聚合整读
拦截 + recipe(指向 `list_clusters`/`list_scout_batches`/`list_rule_jobs`/`describe_artifact`/脚本 stdout
字段)**不变**。非运行域会话 SHALL 直接放行(零日常噪声)。`install.sh` SHALL 提供 `--no-enforce-hook`
opt-out;仅当某端的 hook 注入或核验失败时(claude:settings.json 写入失败;opencode:`tool.execute.before`
在目标 opencode 版本不可用/不触发)SHALL stderr warn 并跳过**该端**注入(fail-soft,承 R5.8),此时纪律
由命令壳明线 + R5.9 边界校验兜底。本条兑现 R5.7「能 hook 就别靠自觉」——双端均有等价 hook 路径,且哨兵
关闭了 opencode「mid-session env 不继承 → 守卫休眠」的既有可靠性边界。

#### Scenario: Hook blocks introspection py -c during a run (claude)
- **WHEN** `MGH_INIT_ACTIVE=1` 下编排器运行 `py -c "import json; json.load(open('.mgh-init/scout_plan.json'))"`
- **THEN** hook 以退出码 2 拦截,stderr 给出「用 list_scout_batches.py / describe_artifact.py」recipe

#### Scenario: Hook passes legitimate leaf-script invocation (claude)
- **WHEN** `MGH_INIT_ACTIVE=1` 下运行 `py .claude/mgh-core/scripts/discover_controls.py --repo . --out .mgh-init`
- **THEN** hook 放行,不误伤合法叶子调用

#### Scenario: Hook blocks editing a leaf script during a run
- **WHEN** `mgh-init` 运行域内编排器 `Edit`/`Write` `.claude/mgh-core/scripts/list_clusters.py`(或 `merge_scout.py`)
- **THEN** hook 以退出码 2 拦截(叶脚本 read-only;此前 `core/scripts` 白名单放行——即「agent 改叶脚本」失守形状)

#### Scenario: opencode activates the guard via the disk sentinel
- **WHEN** opencode 下 `MGH_INIT_ACTIVE` env 未设(opencode 插件进程不继承 mid-session export),但 step 0 已写 `<cwd>/.mgh-init/.active` 哨兵
- **THEN** 守卫经哨兵激活,等效 env 已设;`py -c` 内省/越权脚本写/越树写均 fail-loud(opencode 不再整 run 休眠)

#### Scenario: Hook is idempotent across reinstalls (claude)
- **WHEN** 对同一目标项目连续两次 `install.sh --claude`
- **THEN** `PreToolUse` 中本工具的 matcher 只出现一次,不覆盖用户既有 hook

#### Scenario: opencode plugin blocks the same introspection via the shared gate
- **WHEN** `MGH_INIT_ACTIVE=1` 下 opencode 触发 `tool.execute.before`,且该 Bash 为 `py -c "import json; json.load(open('.mgh-init/scout_plan.json'))"`
- **THEN** `.ts` 插件把事件归一化为 `{tool_name:"Bash", tool_input:{command:...}}` 管道喂给 `block_adhoc_scripts.py`,据退出码 2 阻断该调用,stderr 出同一 recipe;守卫判定逻辑与 claude 端零差异(单一来源)

#### Scenario: opencode plugin is idempotent across reinstalls
- **WHEN** 对同一目标项目连续两次 `install.sh --opencode`
- **THEN** `.opencode/plugins/` 中本工具插件只落一份(幂等替换同名文件、不覆盖用户既有其它插件)

#### Scenario: Opt-out and per-platform fail-soft
- **WHEN** `install.sh --no-enforce-hook`,或某端 hook 注入/核验失败(含 opencode `tool.execute.before` 在目标版本不可用)
- **THEN** 该端 hook 不注入(warn 跳过),install 仍成功(fail-soft);命令壳明线 + R5.9 校验仍生效

### Requirement: Init write confinement to sanctioned subtrees

In the `mgh-init` run-domain, every `Write`/`Edit` SHALL resolve to a target inside one of the sanctioned
subtrees (positive allowlist); writes inside `MGH_TARGET` but outside these subtrees (e.g. project-root
`temp_clusters*.json`, `process_*.ps1`) SHALL be blocked fail-loud by the guard (exit 2) per
`runtime-hook-enforcement`. The sanctioned subtrees are:

| Subtree | Purpose |
|---|---|
| `<target>/.mgh-init/**` | artifacts / checkpoints / inputs / manifest / report / sentinel |
| `<target>/.claude/rules/**` | claude rules output |
| `<target>/docs/security-controls/**` | opencode per-category detail files |
| `<target>/AGENTS.md` | opencode lazy index |
| `out_roots[]` (sentinel-carried) | customized `--out` / `--rules-dir` absolute roots |

The orchestrator SHALL record any non-default `--out` / `--rules-dir` resolved absolute root into the sentinel's
`out_roots[]` at step 0 so the guard honors custom output locations without over-blocking.

#### Scenario: Root-level aggregate dump is blocked
- **WHEN** `mgh-init` 运行域内编排器 `Write` `<target>/temp_clusters1.json`(聚合 dump 到项目根)
- **THEN** 守卫以退出码 2 拦截;recipe 指向 `list_*` stdout 的受信 `checkpoint_path`/`rule_path`

#### Scenario: Sanctioned fan-out paths pass
- **WHEN** `mgh-init` 运行域内写 `<target>/.mgh-init/inputs/t1/<unit>.input.json` 或 `<target>/docs/security-controls/authn.md`
- **THEN** 守卫放行(落入受信子树)

#### Scenario: Custom output root is honored via the sentinel
- **WHEN** 编排器以 `--rules-dir <custom abs>` 启动、写入哨兵 `out_roots[]`,运行域内 `Write` `<custom>/x.md`
- **THEN** 守卫放行(自定义产物根被受信,不 over-block)

### Requirement: Stage-boundary contract checks

每个 stage 产物的产出者 SHALL 暴露 `--check`(或独立 validator),编排器跑完一步、进下一步前 MUST
运行之;失败 MUST fail-loud(退出码 2)并回退重跑(泛化既有 `assemble_rules.py --check` 范式,承
openspec validate-at-boundary,FD7)。覆盖:`discover_controls.py --check`(candidates/clusters wrapper
+ 每条 `source` + cluster_id 唯一)、`plan_scout.py --check`(batches 非空除非 0 target、每批 bytes≤
budget、needs_slice 仅含超批文件)、`merge_scout.py --check`(每条 `source:"scout"` + `file:line` +
**每条 `category` 非空** + **破损 JSON(无法 parse)亦属边界失败、退出码 2** + 给 `JSONDecodeError` 的
`lineno/colno/msg` 与错位附近字节窗诊断)、`validate_inventory.py`(vvah design_controls 兼容 + evidence
锚点 + category→kind 归一)、既有 `assemble_rules.py --check`(rules 纯净性)。

`merge_scout.py --check` 对破损 JSON SHALL 返回退出码 `2`(非 `1`),使编排器闸门(仅在退出码 2 回退)
正确触发重跑 S4;诊断 SHALL 含 `lineno`/`colno`/`msg` 字段供定位。`category` 校验 SHALL 断言非空(不断言
枚举归属,枚举归一交给 `validate_inventory.py`)。

#### Scenario: Check passes on a well-formed artifact
- **WHEN** 编排器对刚产出的 `scout_plan.json` 运行 `plan_scout.py --check`
- **THEN** 退出码 0,编排器进入下一步

#### Scenario: Check fails loud on a corrupted artifact
- **WHEN** 某 batch 的 `bytes` 超过 `--scout-batch-bytes`(或 wrapper 损坏)
- **THEN** `--check` 退出码 2,编排器回退重跑该步,不带着破损产物继续

#### Scenario: merge_scout --check rejects a candidate missing category
- **WHEN** `scout_candidates.json` 的某条 candidate 缺 `category` 字段(或为空)
- **THEN** `merge_scout.py --check` 退出码 2,violations 报告该 candidate 的 index 与 issue,编排器回退重跑 S4

#### Scenario: merge_scout --check rejects malformed JSON with line:col diagnostics
- **WHEN** `scout_candidates.json` 不是合法 JSON(如字符串值内转义错位)
- **THEN** `merge_scout.py --check` 退出码 `2`(非 `1`),stderr/stdout 诊断含 `lineno`/`colno`/`msg` 与错位附近字节窗,编排器回退重跑 S4

#### Scenario: Inventory validated against design_controls schema
- **WHEN** T2 产出 `controls_inventory.json`
- **THEN** `validate_inventory.py`(或 T2 后 check)断言 vvah 兼容字段 + 每条 evidence 锚点 + category→kind 归一,失败退出码 2

### Requirement: Subagent sanctioned-tools allowlist

每个 `core/prompts/stages/init-*.md`(及双壳 `agents/init-*.md`)SHALL 声明一个 **Sanctioned tools**
白名单:读侧 `Read`(仅 input 给定文件/slice)/ `Glob` / `Grep` 自由;脚本侧**仅** `chunk_sources.py`
(若需切片);`Write`/`Edit` 仅限该 stage 的产物文件。subagent MUST NOT `Write` 任何 `.py`、MUST NOT
`py -c`/`python -c` 内省或重派生。stage 输入产物 SHALL 视为**终态**:MUST NOT 用代码变换或重派生;
需瞄结构时 SHALL 向编排器请求 `describe_artifact.py` 输出。`init-scout.md` 现有「Use your tools
freely」SHALL 改为「Use Read/Glob/Grep freely; scripts sanctioned-list only」(治 subagent 侧写脚本,
FD8)。

#### Scenario: scout-reader does not write helper scripts
- **WHEN** `init-scout` subagent 处理一个 batch
- **THEN** 它仅用 Read/Glob/Grep + `chunk_sources.py`(若 needs_slice),不 `Write .py`、不 `py -c`

#### Scenario: Stage prompt declares the allowlist
- **WHEN** 审阅 `core/prompts/stages/init-scout.md` / `init-induct.md` / `init-synthesis.md` / `init-rulewriter.md` 等
- **THEN** 每份含一个可识别的 Sanctioned-tools 段,显式列出允许的工具/脚本并 NEVER 越界

#### Scenario: Shell agent mirrors the allowlist
- **WHEN** 审阅 claude-code 与 opencode 两份 `agents/init-*.md` 的 Hard constraints 段
- **THEN** 两壳均显式声明 subagent NEVER `Write .py` / `py -c`(双壳与 prompt 双重防线)

### Requirement: Fan-out checkpoint paths are deterministic absolute values

scout 与 T1 fan-out 的每个待跑单元的**输出路径** SHALL 是由确定性枚举脚本产出的**单一权威绝对路径值**,
而非占位符模板或相对路径。`list_scout_batches.py` 与 `list_clusters.py` 的 stdout `pending[]` 每项
SHALL 额外包含 `checkpoint_path`(待写产物文件的**绝对路径**)与 `done_marker`(对应 `.done` 标记的
**绝对路径**),二者均由该脚本从其 `--checkpoints` 参数(已 `resolve()`)拼单元 id 得出。

`checkpoint_path` / `done_marker` 的**文件名分量** SHALL 经文件系统消毒(复用 `_safe_name`:`/`、`\`、`:`
→ `_`),使含 `::`(NTFS Alternate-Data-Stream 分隔符)或 `/` 的 `cluster_id` / shard id 派生的文件名在
Windows NTFS 上可写(否则 `write_text` 报 `OSError [Errno 22]`)。canonical 单元 id(含 `::`)SHALL 原样
保留为 slim envelope 的 `cluster_id` 字段与检查点记录内的 `unit` 字段——**只有文件名被编码,身份不变**;
done 检测读记录内 `unit` 字段、不依赖文件名,故消毒不影响 resume 匹配。

编排器 SHALL 把 `list_*` stdout 中的 `checkpoint_path` / `done_marker` **逐字透传**进对应 subagent 的 task 输入,
MUST NOT 自行用 `<target>` / `<batch_id>` / `<cluster_id>` 占位符拼路径,也 MUST NOT 用 `py -c` 算路径。

`init-scout` / `init-induct` subagent 的 stage 提示词 SHALL 把 `checkpoint_path`(与 `done_marker`)
列为**编排器逐字给定**的输入字段,其 Output 段 SHALL 要求「Write 恰好 `checkpoint_path` 给定的绝对路径
并 touch `done_marker`」;且 SHALL 以硬边界 `NEVER` 禁止:自行拼路径、发明文件名(如 `xxxraw.json`)、
写相对路径、写到项目目录之外(含盘符根)。

路径 SHALL 为绝对路径(经 `Path.resolve()`),使其对 subagent 的任意工作目录安全。运行时 hook(在
`MGH_INIT_ACTIVE` 运行域内)SHALL 拦截 `Write`/`Edit` 其 resolved 目标不以 resolved `MGH_TARGET`
为前缀的调用,失败 fail-loud(退出码 2)+ stderr 指向 `list_*` stdout 的 `checkpoint_path` 字段;
`MGH_TARGET` 缺失时该拦截条放行(降级)。`MGH_TARGET` SHALL 由编排器在起步段设置,且其取值 MUST
复用既有确定性脚本的绝对路径 stdout 字段(如 `discover_controls.py` 的 `repo`),MUST NOT 经 `py -c`
现算(守 `harden-mgh-init-orchestration-discipline` 的微脚本明线)。

#### Scenario: Enumeration script emits absolute checkpoint path per pending unit
- **WHEN** `list_scout_batches.py --scout-plan …/scout_plan.json --checkpoints …/checkpoints/scout` 运行
- **THEN** stdout `pending[]` 每项含 `checkpoint_path` 与 `done_marker`,二者均为绝对路径,且分别等于
  `<绝对 checkpoints dir>/<safe(batch_id)>.json` 与 `<绝对 checkpoints dir>/<safe(batch_id)>.json.done`
  (`safe` = `_safe_name`,`batch_id` 通常不含 `::`,消毒为幂等 no-op)

#### Scenario: Checkpoint filename is sanitized for NTFS-unsafe cluster_id
- **WHEN** `list_clusters.py` 对一条 `cluster_id` 含 `::`(如 `authorization::SecCfg::ab12cd34`)、或 shard id
  含 `::shard-<n>` 的待跑单元产出 `pending[]`,运行宿主为 Windows
- **THEN** 该项 `checkpoint_path` / `done_marker` 的**文件名分量**把 `::`(及 `/` `\`)替换为 `_`
  (可经 `write_text` 写下、不报 Errno 22);该项 envelope `cluster_id` 字段仍为**原始**含 `::` 的 canonical id;
  subagent 写入的检查点记录内 `unit` 字段为该 canonical id;`_done_ids` 据此 `unit` 字段正确判终态

#### Scenario: Orchestrator passes path verbatim, never interpolates
- **WHEN** 编排器取得 scout / T1 的 `pending[]` 并起 subagent
- **THEN** subagent task 输入里的输出路径**逐字等于** `list_*` stdout 的 `checkpoint_path`,
  编排器**不**出现 `<target>`/`<batch_id>`/`<cluster_id>` 占位符拼装,也**不** `py -c` 算路径

#### Scenario: Subagent writes exactly the given absolute path
- **WHEN** 一个 init-scout / init-induct subagent 在工作目录 ≠ 项目根(含 Windows 盘符相对 cwd)的隔离上下文运行
- **THEN** 它把产物写到输入字段 `checkpoint_path` 给定的绝对路径(落在 `<target>/.mgh-init/checkpoints/<tier>/` 下),
  **不**写到盘符根或任何项目外目录,**不**发明文件名

#### Scenario: Out-of-tree write is blocked at runtime
- **WHEN** 运行域(`MGH_INIT_ACTIVE=1`)内一个 `Write`/`Edit` 的 resolved 目标不以 resolved `MGH_TARGET` 为前缀
- **THEN** PreToolUse hook 以退出码 2 拒绝,并在 stderr 给出「路径须取自 `list_*` stdout 的 `checkpoint_path`」recipe

#### Scenario: Existing on-disk artifact schema unchanged
- **WHEN** 本变更生效后审阅 `checkpoints/scout/<safe(batch_id)>.json` 与 `checkpoints/t1/<safe(cluster_id)>.json`
- **THEN** 其磁盘**内容** schema 与变更前一致(记录内 `unit` = canonical id、`status`、`out`、`bytes` 等);
  文件名经 `_safe_name` 消毒;`checkpoint_path`/`done_marker` 仅存在于 `list_*` stdout,不写入产物文件内容

### Requirement: Scout candidate JSON robustness at the merge boundary

LLM subagent 产出的 scout 候选 JSON SHALL 是合法 JSON,每条 candidate SHALL 携带非空 `category`,
`evidence_snippet` SHALL 是单行安全子串(以 `'` 代 `"`、去 `\`)——结构上不可能破坏 JSON 字符串。
产出者:S3 `init-scout`(per-batch `checkpoints/scout/<batch_id>.json`)、S4 `init-scout-merge`
(`scout_candidates.json`)、`init-scout-audit`(`audit.json::audit_found[]`);S4 合并时 MUST NOT 丢弃
`category`。该约束 SHALL 写入 `core/prompts/stages/init-scout.md`、`init-scout-merge.md`、
`init-scout-audit.md` 三份提示词(双 shell 共享 `core/`,一次改双端)。

`merge_scout.py` 折入(`main()`)SHALL **NOT** 在畸形输入上抛未捕获异常(原始 traceback):
- 破损 JSON(`--scout`/`--candidates`/`--clusters` 任一 `json.loads` 失败)→ stderr 出 `lineno/colno/msg`
  诊断、stdout 出结构化错误 JSON(含 `error`/`file`/`lineno`/`colno`/`nearby`)、退出码 `1`;
- 缺 `category` 的 candidate(含 `audit_found[]` 路径,该路径不经 `--check`)→ `_normalize` **跳过**该
  candidate、stderr warn、退出码 `0`,stdout 成功摘要 SHALL 含 `skipped` 计数显式披露丢弃数。

`_normalize` 取 category SHALL 用 `c.get("category")`(非 `c["category"]` 直索引)。本要求**不**改
`discover_controls.form_clusters`(共享逻辑;`_normalize` 跳过即阻断缺 category 候选进入)。

#### Scenario: merge_scout fold-in does not crash on malformed JSON
- **WHEN** `merge_scout.py --candidates … --scout <malformed.json> --clusters …` 被调用,且 `<malformed.json>` 不是合法 JSON
- **THEN** 进程退出码 `1`、**不**抛未捕获 traceback;stdout 为含 `error`/`file`/`lineno`/`colno` 的结构化 JSON,stderr 出可操作诊断

#### Scenario: merge_scout fold-in skips missing-category audit candidates
- **WHEN** `audit.json::audit_found[]` 含一条缺 `category` 的 candidate(该路径不经 `--check`)
- **THEN** `merge_scout.py` 折入跳过该 candidate、stderr warn 指明丢弃、退出码 `0`,stdout 摘要的 `skipped` 计数 ≥1,合法 candidate 仍正常折入

#### Scenario: merge_scout fold-in reports skipped count on success
- **WHEN** 折入完成且有 candidate 因缺 `category` 被跳过
- **THEN** stdout 成功摘要 JSON 含 `skipped` 字段(非 0),`scout_candidates_added` 仅计合法折入数

#### Scenario: Scout prompts require category and a JSON-safe snippet
- **WHEN** 审阅 `core/prompts/stages/init-scout.md` / `init-scout-merge.md` / `init-scout-audit.md`
- **THEN** 每份显式声明:每条 candidate `category` 必带(S4 合并 NEVER 丢弃)、`evidence_snippet` 为单行且以 `'` 代 `"`、去 `\` 的安全子串

#### Scenario: form_clusters untouched by the robustness fix
- **WHEN** 本变更生效后审阅 `discover_controls.py::form_clusters`
- **THEN** 其 `category` 取值方式与变更前一致(未改为 `.get`);缺 `category` 的 scout 候选在 `merge_scout._normalize` 即被跳过,不进入 `form_clusters`

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

### Requirement: Discover call-graph cache survives re-runs

`discover_controls.py` SHALL 在两遍调用图建成后将结果(`forward`/`reverse`/`framework_files`/
`name_to_files` 等重建所需态)原子写到 `<out>/cache/callgraph.json`;重跑时 SHALL 按源文件 mtime
判定缓存新鲜度——源未变更且未传 `--rebuild-cache` 时 SHALL 加载缓存、跳过两遍 callgraph 重建。该缓存
是「跨调用零全损推进」与「重跑提速」的基础(兑现既有「Resumable, checkpointed execution」的
callgraph-cache 条款,关闭 `--rebuild-cache` 悬空契约)。`--rebuild-cache` flag SHALL 真实存在且经
`--help` 暴露(承 R5.1);默认行为(无缓存或缓存失效=每次重建)向后兼容。

#### Scenario: Cache hit skips callgraph rebuild
- **WHEN** discover 完成一次写入 `cache/callgraph.json` 后,源文件未变更即再次运行
- **THEN** discover 加载缓存、跳过两遍 callgraph 重建,stdout 摘要含缓存命中标志

#### Scenario: Stale cache rebuilt on source change
- **WHEN** 缓存存在但某源文件 mtime 新于缓存,或传 `--rebuild-cache`
- **THEN** discover 重建调用图并刷新缓存(不返回过期结果)

#### Scenario: rebuild-cache is a real documented flag
- **WHEN** 运行 `discover_controls.py --help`
- **THEN** `--rebuild-cache` 出现在参数表(argparse 认识,不报 unrecognized)

### Requirement: Discover scan resumes from a checkpoint

`discover_controls.py` SHALL 在 scan 阶段周期(每 `--progress-every` 文件)原子写续点
`<out>/cache/scan_progress.json`(至少含已扫文件索引 `scanned_index` 与累积候选)。`--resume` SHALL
复用 callgraph 缓存并从 `scanned_index` 续扫、追加候选(不重扫已续点文件);续点合并 SHALL 确定性、
幂等(同一续点重跑产等价候选集)。scan 完成后续点可保留(供再次 resume)或清理,均不破坏最终产物。

#### Scenario: Resume continues scan past a kill
- **WHEN** discover 在 scan 中途被强杀,留下 `scan_progress.json`(scanned_index=K),随后
  `discover ... --resume`
- **THEN** discover 跳过前 K 个已扫文件、从第 K+1 续扫,候选集等价于一次跑完的结果

#### Scenario: Resume is idempotent
- **WHEN** 对同一续点连续两次 `--resume`
- **THEN** 两次产出的候选集等价(不重复、不丢失)

### Requirement: Discover soft time-budget clean exit

`discover_controls.py` SHALL 提供 `--time-budget-ms <N>`(默认 0=关)。当置位且在安全边界(callgraph
建成后、scan 每 `--progress-every` 文件)已超预算时,discover SHALL 落全部-so-far 产物(callgraph
缓存 + scan 续点)并在 stdout 增 `partial: true` + `resume_hint`(可操作的重派提示)后**退出码 0**
(干净早退,而非被宿主 SIGKILL 全损)。未置位或未超预算时 SHALL 一次性跑完,stdout `partial: false`。
编排器 SHALL 据 stdout `partial: true` 经 Bash 重派 `--resume`(编排器循环,**NEVER** 写 wrapper `.py`;
承 R5.2 黑盒纪律)直至 `partial: false`。

#### Scenario: Budget exceeded triggers clean partial exit
- **WHEN** 运行 `discover_controls.py --repo . --out .mgh-init --time-budget-ms 30000`,且单次调用 30s
  内跑不完
- **THEN** discover 在安全边界落缓存/续点后退出码 0,stdout 含 `partial: true` + `resume_hint`,无产物截断

#### Scenario: Budget off finishes in one go
- **WHEN** 未传 `--time-budget-ms`(默认 0),且仓规模在单次超时内
- **THEN** discover 一次性跑完,stdout `partial: false`,行为等价于引入本要求前

#### Scenario: Orchestrator re-dispatches on partial, never via wrapper script
- **WHEN** discover stdout 为 `partial: true`
- **THEN** 编排器经 Bash 重派 `discover ... --resume`;**不** `Write` wrapper `.py` 去循环

### Requirement: Discover writes are atomic

`discover_controls.py` SHALL 原子写出所有产物 JSON(`controls_candidates.json`/`clusters.json`/`skeleton.json`/
`cache/*`):先写 `<path>.tmp` 再 `os.replace` 落盘,使进程在任意时刻被 SIGKILL 都**不**留下
截断/半写 JSON(`--check` 与下游 `json.loads` 不会读到破损文件)。原子写仅用 Python 标准库
(`os.replace`/`pathlib`),承 R2 零运行时依赖。

#### Scenario: Killed mid-write leaves no truncated artifact
- **WHEN** discover 在写 `controls_candidates.json` 的过程中被强杀
- **THEN** 目标仓里**不**存在截断的 `controls_candidates.json`(要么完整、要么不存在),`.tmp` 残留可被
  下次运行覆盖

#### Scenario: check passes after an interrupted run
- **WHEN** 对一次被强杀后留下完整产物的 out-dir 运行 `discover_controls.py --check`
- **THEN** `--check` 读到合法 JSON,退出码 0(无破损文件误判为边界失败)

### Requirement: Long-running deterministic Bash calls carry a per-call timeout

每份 `mgh-*.md` 命令壳的编排器 SHALL 给**长跑确定性 Bash 调用**传一个慷慨的 per-call `timeout`
(claude Bash 工具与 opencode shell 工具均接受毫秒级 `timeout` 参数)。对 init,长跑脚本含
`discover_controls.py`(尤其带 `--time-budget-ms`)/`plan_scout.py`/`merge_scout.py`;对带 `--time-budget-ms`
的 discover,`timeout` SHALL 略大于该 budget,编排器见 stdout `partial: true` 即 Bash 重派 `--resume`。
命令壳 SHALL 在边界/披露段说明:opencode 用户**可**经环境变量
`OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认 120000)提升全局默认,但该变量**须在 opencode
启动前就绪**(mid-session `export` 不被 opencode 插件进程继承,与 R5.7 `MGH_*_ACTIVE` 可靠性边界同根因);
per-call `timeout` 是跨宿主公共杠杆,可在会话中即时生效。该 recipe 是横切编排纪律(镜像
`sast-orchestration-discipline`/`security-augmentation`/`freeform-security-review`)。

#### Scenario: Shell recipe tells the orchestrator to pass a per-call timeout
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md`
- **THEN** 两壳均显式要求长跑确定性 Bash 调用携带 per-call `timeout`,并据 discover stdout `partial`
  决定是否 Bash 重派 `--resume`

#### Scenario: opencode env-var boundary disclosed
- **WHEN** 审阅 `mgh-init.md` 边界段与 README
- **THEN** 其中明示 `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` 须 opencode 启动前设置、mid-session
  `export` 不生效,并指 per-call `timeout` 为会话内即时生效的替代

### Requirement: Re-entrant orchestrator resume state (disk as single source of truth)

`/mgh-init` SHALL provide a deterministic leaf script `core/scripts/resume_state.py` that, given a
`<target>/.mgh-init/` directory, derives the pipeline's **current step** and **exact next action** **purely from
on-disk artifacts + `.done` markers** — independent of any conversation / session memory. It is the single
sanctioned outlet for the orchestrator reflex "which step am I on / what do I do next" (replaces relying on
remembering progress across the 8-step flow). stdout = slim structured JSON
`{target, format, step, tiers{discover, scout, t1, t2, t3, t4 each {done, total}}, next_action{kind∈bash|subagent|done,
desc, absolute_paths}, resumable, notes[]}`; stderr = diagnostics/progress only; exit codes `0/1/2`.
`step` SHALL be one of `not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`, resolved by
probing product artifacts (`controls_candidates.json`/`clusters.json`/`scout_candidates.json`/`controls_inventory.json`/
rule files/`init_manifest.json`) and per-tier `.done` markers, **conditional on the persisted run config**
(see "Persisted run configuration for stateless resume") so optional/codepath branches
(`--no-scout`/`--no-codegraph`/`--skip-consistency`/`--merge`/survey-skipped/resolve-skipped) are honored.
`next_action.absolute_paths` SHALL reuse the same `Path.resolve()` absolute values the `list_*`/`describe_artifact`
producers emit (承 "Fan-out checkpoint paths are deterministic absolute values"); the script MUST NOT invent paths or
template `<target>`. The script MUST be zero-runtime-dependency (承 R2), self-locate `sys.path`, read utf-8, run from
any cwd, and expose `--help` as its CLI contract (承 R5.1/R5.3). The orchestrator SHALL call `resume_state.py` as the
**first action** on `--resume` and **after any host context compaction** (claude `/compact` / opencode auto-compact),
and SHALL NOT determine "current step" from conversation memory.

#### Scenario: Fresh session resumes mid-T1 purely from disk

- **WHEN** a run halted with some `<target>/.mgh-init/checkpoints/t1/*.done` present but
  `controls_inventory.json` absent, and a **new session** runs
  `py <path>/resume_state.py --target <target>`
- **THEN** stdout `step` = `t1`, `tiers.t1` = `{total, done}` reflecting real `.done` count,
  `next_action.kind` = `subagent` with `desc` naming `init-induct` for the pending units and `absolute_paths`
  carrying the real `input_path`/`checkpoint_path` from `list_clusters.py`, `resumable` = true — and the orchestrator
  obtained this **without consulting any prior conversation memory**

#### Scenario: Run config makes resume stateless of re-typed flags

- **WHEN** the original invocation passed `--format opencode --no-scout` and then halted, and a fresh session runs
  `/mgh-init --resume` **without** re-passing `--format`/`--no-scout`
- **THEN** `resume_state.py` reads `<target>/.mgh-init/run_config.json`, reports `format` = `opencode` and the scout
  tier as skipped (not pending), and `next_action` respects `--no-scout` (it does NOT direct spawning scout readers)

#### Scenario: Completed run reports done

- **WHEN** all terminal artifacts exist (`controls_inventory.json` + rule/detail files + `init_manifest.json`) and the
  final tier `.done` markers are present
- **THEN** `resume_state.py` stdout `step` = `done`, `next_action.kind` = `done`, `resumable` = false

#### Scenario: --merge short-circuit reflected

- **WHEN** `run_config.json` records `mode` = `merge`
- **THEN** `resume_state.py` stdout `step` = `merge` and `next_action` directs the `--merge <partials-dir>` flow
  rather than discover/scout/t1

#### Scenario: Scout-merge sub-step is not skipped on resume

- **WHEN** all scout batch `.done` markers exist but `scout_candidates.json` (and
  `checkpoints/scout/merge.json.done`) are absent — i.e. a prior, context-pressured session fanned out the scout
  readers but never ran `init-scout-merge`
- **THEN** `resume_state.py` stdout `step` = `scout` (NOT `t1`/`resolve`), `next_action.kind` = `subagent` naming
  `init-scout-merge` to produce `scout_candidates.json` first — preventing the orchestrator from skipping straight
  to `merge_scout.py` / T1 and hand-rolling a malformed aggregate (real-machine failure shape: orchestrator lost the
  step sequence, read `merge_scout.py` source to reverse-engineer the expected wrapper format, then fabricated it)

#### Scenario: resume_state is self-contained, offline, and contract-complete

- **WHEN** `py <path>/resume_state.py --target <dir>` is executed from an arbitrary cwd in an offline environment, and
  `py <path>/resume_state.py --help` is run
- **THEN** it succeeds (self-located `sys.path`, utf-8 read, zero third-party imports) emitting valid JSON; and `--help`
  prints a flag table whose flags the dual `mgh-init.md` shells mirror verbatim (承 R5.1)

#### Scenario: Orchestrator routes "where am I" to the sanctioned primitive

- **WHEN** the orchestrator (on `--resume` or post-compaction) needs to know the current step / next action
- **THEN** it calls `resume_state.py`, MUST NOT `py -c`/`python -c` introspect `.mgh-init/**`, MUST NOT `Read` whole
  aggregate JSON to reconstruct progress, and MUST NOT rely on remembered step state from conversation

### Requirement: Persisted run configuration for stateless resume

`/mgh-init` 编排器 SHALL 在 step 0(参数解析后、花 token 前)原子写出
`<target>/.mgh-init/run_config.json`(`.tmp`+`os.replace`,承 "Discover writes are atomic"),记录**决定步骤图的本次
调用 flag**:`target`(绝对)、`format`、`scope`/`scope_mode`、`no_scout`、`no_codegraph`、`skip_consistency`、
`merge`(及 `merge_partials_dir`)、`include_dotfiles`、以及 `--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes`
预算与 `--scout-*` 参数。该文件是**起始态**意图记录,与既有**终态** `init_manifest.json`(版本/计数/出处)边界清晰、
互不替代。`resume_state.py` SHALL 消费 `run_config.json` 解析可选/codepath 分支。`run_config.json` 缺失或破损时,
`resume_state.py` SHALL fail-loud(退出码 2)+ stderr recipe(指向重跑 `/mgh-init --<flags>` 重建),MUST NOT 静默猜测
步骤图。该文件随 `.mgh-init/` gitignore(承既有 unit-inputs gitignore 约定)。

#### Scenario: Run config written atomically at start

- **WHEN** `/mgh-init --target <t> --format opencode --no-scout` runs and reaches step 0
- **THEN** `<t>/.mgh-init/run_config.json` is written atomically (no truncated half-write survives a mid-write kill) and
  records `format`/`no_scout`/absolute `target` verbatim from the invocation

#### Scenario: Resume consumes run config

- **WHEN** `resume_state.py` runs against a `.mgh-init/` whose `run_config.json` records `no_scout=true`
- **THEN** it reports the scout tier as skipped and never directs scout fan-out, matching the original invocation intent

#### Scenario: Missing run config fails loud, not silent

- **WHEN** `resume_state.py` runs and `run_config.json` is absent or unparseable
- **THEN** it exits code `2` with a stderr recipe telling the user to re-run `/mgh-init --<flags>` to rebuild it, rather
  than silently guessing a step graph that could diverge from the original intent

### Requirement: Subagent return-to-orchestrator is a bounded ack

每份 `core/prompts/stages/init-*.md` SHALL 声明一个 **Return-to-orchestrator** 契约:subagent 的**最终回传消息**
SHALL 是**单条有界 ack**——取值之一 `ok <绝对 checkpoint_path 或 rule_path> <count>`、`oversize <绝对 path>`、
`failed <简短原因>`(聚合 stage 的 ack 额外带 `total`/`merged` 计数)——且 **MUST NOT** 回显记录体、原始源码、或
检查点文件内容(治「subagent 回传随 fan-out 单调膨胀编排器上下文」,承审计发现:9 份提示词此前对回传消息集体沉默)。
该 ack 是**存活/成功信号**,非数据载体。编排器 SHALL 仅据 ack 判断该单元成败、并以 `.done` 标记 + `resume_state.py`
确认进度;MUST NOT 为「继续流水线」而内联 `Read` 检查点文件回编排器上下文。聚合节点(T2/scout-merge)的检查点文件
本身即全量聚合记录,编排器 SHALL 通过 `resume_state.py`/`describe_artifact.py` 的有界摘要接触之,NEVER 整份读回。
本要求同时写入双壳 `agents/init-*.md` 的 Hard-constraints 段(双重防线)。

#### Scenario: Each stage prompt declares the bounded ack contract

- **WHEN** 审阅 `core/prompts/stages/init-scout.md`/`init-induct.md`/`init-synthesis.md`/`init-scout-merge.md`/
  `init-survey.md`/`init-scout-audit.md`/`init-resolve.md`/`init-rules-consistency.md`
- **THEN** 每份含一个可识别的 Return-to-orchestrator 段,声明最终消息为单条有界 ack、NEVER 回显记录体/源码

#### Scenario: Orchestrator does not echo checkpoint content to continue

- **WHEN** 一个 init-induct subagent 完成并回传 `ok <abs path> <count>`,编排器进入下一单元
- **THEN** 编排器仅记 ack 为成功信号 + 探 `.done`;它 **不** `Read` 该 checkpoint 内联回上下文,也 **不** 把记录体
  透传给后续 subagent(后续 subagent 经自己的 `input_path` 自读)

#### Scenario: Aggregate checkpoint accessed via bounded summary, not inline read

- **WHEN** 编排器在 T2 完成后需要确认 inventory 落盘
- **THEN** 它经 `resume_state.py`(或 `describe_artifact.py --count/--keys`)取得有界摘要,**不** 整份 `Read`
  `controls_inventory.json` 进编排器上下文

### Requirement: Aggregate nodes enforce a hard request budget via map-reduce

T2(`init-synthesis`)与 scout-merge(`init-scout-merge`)SHALL 把 `--max-aggregate-bytes` 当作**硬闸门**(兑现
shell 既有「P0 软边界:T2/merge/T4 聚合节点目前为披露 + `--scope`/`--merge` 回退」的自认 TODO,把软边界升级为硬阈值)。
聚合输入(全部 T1 记录 / 全部 scout 批记录)≤ `--max-aggregate-bytes` 时,行为**逐字不变**(单一综合 subagent
上下文,承 "Isolated per-cluster induction with cross-cluster synthesis" / "Fan out scout across parallel isolated
byte-bounded batches" 的既有 single-context 综合语义)。聚合输入 **>** 预算时,SHALL 自动触发**两段 map-reduce**:
确定性叶脚本 `core/scripts/plan_aggregate.py` 把上一层记录(T2 按 `category` 分桶;scout-merge 按 batch 簇分桶)切成
**每桶 ≤ `--max-aggregate-bytes`** 的有界 shard 并物化 per-shard 输入;编排器为每 shard 扇出一个 **partial-synthesis
subagent**(有界输入、回传有界 ack),产出 per-shard 摘要 checkpoint;最后由**单一 rollup subagent** 仅吞**各 shard
摘要**(有界)产出终态产物(`controls_inventory.json` / `scout_candidates.json`)。**每个大模型请求 SHALL ≤ 预算**。
`plan_aggregate.py` SHALL 零依赖、自定位、utf-8、任意 cwd、stdout=JSON/stderr=诊断、退出码 `0/1/2`、`--help` 即契约
(承 R5.1/R5.3),并复用既有 `list_*` 的 `--materialize`/`--offset`/`--limit`/`--orch-budget-bytes` 翻页语义。降级触发
与 shard 数 SHALL 在 `init_manifest.json::boundaries[]` + `report.md` 披露(无静默溢出)。本要求在「超预算」时**取代**
既有 single-context 综合条款;≤ 预算(常见小仓)时既有条款逐字生效。

#### Scenario: Small repo keeps single-context synthesis unchanged

- **WHEN** 全部 T1 记录序列化字节 ≤ `--max-aggregate-bytes`
- **THEN** T2 仍为单一综合 subagent 上下文(无 shard、无 rollup),行为等价于引入本要求前

#### Scenario: Large repo triggers automatic map-reduce sharding

- **WHEN** 全部 T1 记录序列化字节 > `--max-aggregate-bytes`
- **THEN** `plan_aggregate.py` 按 `category` 切成多个每桶 ≤ 预算的 shard,编排器每 shard 一个 partial-synthesis
  subagent(有界输入),再一个 rollup subagent 仅吞各 shard 摘要;**每个大模型请求 ≤ 预算**

#### Scenario: scout-merge over budget uses batch-cluster shards

- **WHEN** 全部 scout 批记录 > `--max-aggregate-bytes`
- **THEN** `plan_aggregate.py` 按 batch 簇分桶,每桶一个 bounded partial-merge subagent,再 rollup;每请求有界

#### Scenario: Rollup operates on summaries only

- **WHEN** map-reduce 的 rollup subagent 运行
- **THEN** 其输入为各 shard 的**结构化摘要**(非原始 T1/scout 记录全集),上下文规模远小于任一 shard

#### Scenario: Reduction is disclosed, not silent

- **WHEN** 一次运行触发了聚合 map-reduce 降级
- **THEN** `init_manifest.json::boundaries[]` + `report.md` 记录触发节点、shard 数与每 shard 预算,不静默溢出

#### Scenario: plan_aggregate is self-contained, offline, and contract-complete

- **WHEN** `py <path>/plan_aggregate.py ...` 从任意 cwd、内网无网环境执行,且 `--help` 被运行
- **THEN** 脚本成功(零依赖、自定位、utf-8),stdout 为合法 JSON;`--help` flag 表被双壳 `mgh-init.md` 逐字镜像(承 R5.1)

### Requirement: Compaction-aware orchestration

两份 `mgh-init.md` 命令壳(claude + opencode)SHALL 新增一个 **Re-entrancy & compaction** 段,声明:(1) 所有可恢复
流水线状态(checkpoints / `.done` / 产物 JSON / `run_config.json`)都在磁盘 `<target>/.mgh-init/`,**对话记忆只是缓存、
不是进度真相源**;(2) claude `/compact` 与 opencode 自动压缩(~95% 触发)是**模型生成摘要**,**可能丢掉**命令壳灌入的
编排纪律系统提示词,故续跑 SHALL **NEVER** 依赖「记得自己在第几步」;(3) **`--resume` 与任何压缩事件后,编排器第一步
SHALL 调 `resume_state.py`** 从磁盘重派生 step + next_action;(4) 上下文吃紧时编排器 **MAY** **干净停止**(跑完当前
fan-out 波次、落 `.done`、不留下半截单元)→ **新 session `/mgh-init --resume` 续**,此路径**优于**人工 `/compact`(
后者摘要可能丢编排纪律导致执行路径偏离——直击用户痛点);(5) 既有 per-call `timeout` + discover `partial:true` +
`--resume` 纪律**保持不变**。该段 SHALL 用主谓措辞(SHALL/MAY)+ recipe 句式(承 R5.5①「该做什么」优先于禁令)。

#### Scenario: Shell declares disk-as-source-of-truth

- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md`
- **THEN** 两壳均含可识别的 Re-entrancy & compaction 段,声明可恢复状态在磁盘、对话记忆非真相源、压缩是模型摘要可能丢提示词

#### Scenario: Resume / post-compaction first action is resume_state

- **WHEN** 编排器在 `--resume` 或一次自动/手动压缩后继续
- **THEN** 其第一步是调用 `resume_state.py` 重派生 step + next_action,而非依赖对话记忆判步骤

#### Scenario: Stop-cleanly-and-resume preferred over manual compact

- **WHEN** 审阅 Re-entrancy & compaction 段关于上下文吃紧的 recipe
- **THEN** 该段声明编排器 MAY 干净停止 + 新 session `/mgh-init --resume` 续,并指明此路径优于人工 `/compact`(因其可能丢编排纪律)

#### Scenario: Existing timeout / partial-resume discipline preserved

- **WHEN** 审阅该段与既有「Long-running deterministic Bash calls carry a per-call timeout」段
- **THEN** per-call `timeout` + discover `partial:true` + `--resume` 纪律保持不变,本段为 additive

### Requirement: Merge path tolerates scout candidates missing required fields

`merge_scout.py::_normalize`(把 scout candidate 子集归一到完整 Candidate shape 的路径,非 `--check` 路径)SHALL 对缺任一必填字段(`category` 或 `file`)的 candidate 返回 `None`,由调用方 skip 并向 stderr 打印 warn(warn SHALL 如实指出缺哪个必填字段、candidate 的 `index`、以及可得的 `file:line` 定位),而非直索引抛 `KeyError` 中止整次 merge。`_normalize` 内所有字段取值 SHALL 统一用 `.get`,不得残留对必填字段的直索引。

此要求为 defense-in-depth:正常流程下 `merge_scout.py --check` 已挡缺字段候选(退出码 2 回退重跑);本要求覆盖 `--check` 被绕行(如编排器上下文压力下跳过 merge 闸门、或畸形 `scout_candidates.json`)时的脚本侧鲁棒性,使 merge 优雅丢弃个别畸形 candidate 并继续,而非整体崩溃。

#### Scenario: Candidate missing file is skipped with a warning, merge continues
- **WHEN** `merge_scout.py` 归一一条缺 `file` 字段的 scout candidate(且 `--check` 未先运行或被绕行)
- **THEN** `_normalize` 返回 `None`,该 candidate 被 skip;stderr 打印指出**缺 `file`** 的 warn(含
  candidate `index` 与可得 `file:line` 定位);merge 继续处理其余 candidate;进程**不**抛 `KeyError: "file"`,
  正常产出(退出码 0)

#### Scenario: Candidate missing category is still skipped (behavior unchanged)
- **WHEN** 某 scout candidate 缺 `category` 字段
- **THEN** 行为与现状一致:`_normalize` 返回 `None`,candidate 被 skip,stderr 打印指出缺 `category` 的 warn,
  merge 继续

#### Scenario: Candidate missing both required fields is skipped once
- **WHEN** 某 scout candidate 同时缺 `category` 与 `file`
- **THEN** candidate 被 skip 一次,stderr warn 如实列出所缺字段(含 `category` 与 `file`),不重复 skip、不抛异常

#### Scenario: Well-formed candidate is unaffected
- **WHEN** 某 scout candidate 含完整 `category` 与 `file`
- **THEN** `_normalize` 正常归一产出完整 Candidate dict,不打 warn,merge 正常进行

### Requirement: Fan-out waves run to completion without scale-driven user interruption

`/mgh-init` 的编排器(宿主 agent)SHALL 把每个 fan-out 波次跑到完成,且 MUST NOT 因规模大而中途停下征求用户拆分 / 跳过 / 终止。具体到 scout reader batches / T1 per-cluster induction / T3 per-category rule writing 任一波次:编排器迭代 `list_*` 的 `pending` 工作清单、以 `max_concurrent` 并发起 subagent、跑完一波起下一波,直至无 pending 单元剩余;规模大(数百至 ~1000 单元)本身 NEVER 构成停下征求的理由。规模与边界事实 SHALL 流入既有披露渠道——`init_manifest.json::boundaries[]`、`report.md`、`resume_state.py` `notes[]`——NEVER 作为运行中的阻塞式提问;披露所用计数 SHALL 自磁盘读取(`resume_state.py` / `list_*` stdout),NEVER 据对话记忆编造。

本要求**不改动**既有 **pre-run** 建议:i0 阶段统计源文件数命中 `--large-repo-threshold` 时、
**在花 token 之前**主动建议 `--scope` 分模块 + `--merge` 的行为(承「Bounded single-pass scan
performance on large repos」)保持不变。本要求的禁止范围仅限**运行已提交之后**(波次进行中)的
打断行为。

该指令 SHALL 以规范性措辞(RFC-2119 `MUST NOT`/`SHALL`)写入 claude-code 与 opencode 两份
`mgh-init.md`(逐字镜像),落在 fan-out / Re-entrancy & compaction 区。这是编排器对话行为约束
(非工具调用约束),runtime hook 管不到「agent 是否停下来问用户」;确定性可测部分 = 披露侧
(规模/边界进 `init_manifest.json`/`report.md`/`resume_state.py`,计数来自磁盘)。

#### Scenario: A large fan-out wave runs to completion without a blocking question

- **WHEN** 编排器进入一个 fan-out 波次,且该波次 `pending` 单元数很大(如 ~1000 个 scout batch),
  用户期望全面、稳定执行到底
- **THEN** 编排器迭代 `list_*` stdout `pending[]`、以 `max_concurrent` 并行跑完所有单元,**不**
  中途停下征求用户「是否拆分 / 跳过 / 终止」;波次跑到 `pending` 为空

#### Scenario: Scale and boundaries are disclosed, not asked

- **WHEN** 一个 fan-out 波次规模大或覆盖部分(含 `.failed`/跳过单元 / 残留盲区)
- **THEN** 规模与边界事实出现在 `init_manifest.json::boundaries[]` 和/或 `report.md` 和/或
  `resume_state.py` `notes[]`(计数自磁盘 `resume_state.py`/`list_*` stdout),且编排器**不**就
  规模提出运行中的阻塞式提问

#### Scenario: The pre-run scope advisory is preserved

- **WHEN** i0 阶段统计的源文件数超过 `--large-repo-threshold`,且尚未花 token 进入全量扫描
- **THEN** 系统在开始全量扫描前建议 `--scope` 分模块 + `--merge`(行为等价于本要求引入前);
  该 pre-token 建议不受「运行中不打断」指令影响

#### Scenario: Both shells declare the run-to-completion directive

- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md` 的 fan-out / Re-entrancy & compaction 区
- **THEN** 两壳均含一条规范性措辞,声明编排器 MUST NOT 因规模在波次进行中停下征求拆分/跳过/终止、
  SHALL 把规模与边界流入既有披露渠道(双壳逐字镜像)

#### Scenario: Disclosed counts come from disk, not conversation memory

- **WHEN** 编排器在摘要/披露中陈述 fan-out 规模、失败数、跳过数或覆盖率
- **THEN** 这些计数取自 `resume_state.py` / `list_*` stdout 的结构化字段(磁盘真相),NEVER 据对话
  记忆编造

### Requirement: Partial fan-out unit failure tolerance

A confirmed `/mgh-init` fan-out unit failure SHALL be treated as a terminal, non-blocking state distinct from completion. This covers the scout-reader batch, T1 per-cluster induction, and T3 per-category rule-writing tiers: when a unit's subagent returns the existing `failed <reason>` ack, the orchestrator SHALL record it with a `.failed` marker sibling to its `.done` marker (`<checkpoint_path>.failed`); the unit SHALL NOT be retried on `--resume` and SHALL NOT block tier completion. A tier SHALL be considered complete enough to proceed when `done + failed >= total` (not `done >= total`).

The orchestrator (host agent) SHALL write the `.failed` marker on receiving a `failed` ack — the
subagent touches nothing on failure (it only emits the ack). A unit whose subagent crashed
without producing any ack SHALL leave neither `.done` nor `.failed` and SHALL remain pending
(crash is not a confirmed terminal failure).

The `list_clusters.py`, `list_scout_batches.py`, and `list_rule_jobs.py` work-list producers
SHALL exclude `.failed` units from `pending[]`, SHALL emit a `failed` count in stdout, and SHALL
emit a `failed_marker` absolute path per pending item (parallel to `done_marker`). `resume_state.py`
SHALL derive each tier's `failed` count from `.failed` markers, gate tier completion on
`done + failed >= total`, surface non-zero failures in `notes[]`, and flag a unit carrying both
`.done` and `.failed` as a `--check` self-consistency violation (exit 2).

#### Scenario: A failed unit is marked terminal and excluded from pending

- **WHEN** a T1 cluster subagent returns `failed evidence parse error` for cluster `authZ::shard-0`
  and the orchestrator writes its `failed_marker` (`checkpoints/t1/<safe(authZ::shard-0)>.json.failed`)
- **THEN** the next `list_clusters.py --checkpoints <t1-dir>` run does NOT list that unit in
  `pending[]`, and its stdout `failed` count is incremented

#### Scenario: A tier proceeds when done plus failed reaches total

- **WHEN** a tier has `total=1000` units, of which 997 are `.done` and 3 are `.failed`
- **THEN** `resume_state.py` reports `step` past that tier (it does not gate on `done < total`),
  `tiers[<tier>].failed == 3`, and the pipeline proceeds to the next stage

#### Scenario: Resume does not retry a failed unit

- **WHEN** the pipeline is re-entered with `mgh-init --resume` after a unit was marked `.failed`
- **THEN** `resume_state.py` does not surface that unit in `next_action` / `pending`, and the
  orchestrator does not re-dispatch it

#### Scenario: A crash is not a confirmed failure and is retried

- **WHEN** a subagent crashes mid-unit leaving neither `.done` nor `.failed`
- **THEN** the unit remains `pending` and `resume_state.py` re-dispatches it on the next resume

#### Scenario: Both done and failed for one unit is a check violation

- **WHEN** a unit carries both `<checkpoint_path>.done` and `<checkpoint_path>.failed`
- **THEN** `resume_state.py --check` reports the ambiguous terminal state and exits 2

#### Scenario: A failed unit with no checkpoint record body is not a violation

- **WHEN** a `.failed` marker exists but its sibling checkpoint record `<id>.json` is absent
  (the subagent failed before writing the record)
- **THEN** `resume_state.py --check` does not flag it (absent record is expected for failures)

### Requirement: Fan-out failures are disclosed in artifacts

The orchestrator SHALL disclose fan-out unit failures in `init_manifest.json` and `report.md`.
The `failures` counts SHALL be read from disk via `resume_state.py` stdout `tiers` or `list_*`
stdout `failed` fields — NEVER from agent conversation memory. The `list_*` producers and
`resume_state.py` SHALL expose failure counts as structured output fields.

#### Scenario: Work-list producers expose failed count and failed_marker path

- **WHEN** the orchestrator runs `list_clusters.py` / `list_scout_batches.py` / `list_rule_jobs.py`
  over a checkpoint dir containing `.failed` markers
- **THEN** stdout carries a `failed` integer count, and each `pending[]` item carries an absolute
  `failed_marker` path parallel to its `done_marker`

#### Scenario: resume_state reports failed per tier

- **WHEN** a tier has any `.failed` units
- **THEN** `resume_state.py` stdout `tiers[<tier>]` includes a `failed` count, and `notes[]`
  contains a disclosure entry naming the tier, the failed count, and the total

#### Scenario: The manifest and report disclose the failure rate

- **WHEN** the orchestrator finalizes `init_manifest.json` and `report.md` after a tier with
  `failed > 0`
- **THEN** `init_manifest.json` carries a `failures` object (per-tier `{done,failed,total}` or
  equivalent) and a `boundaries[]` entry disclosing that fan-out units failed and were skipped,
  and `report.md` surfaces the same fact in its disclosure section

#### Scenario: High failure rate produces a loud advisory

- **WHEN** a tier's failed count exceeds half its total
- **THEN** `resume_state.py` `notes[]` elevates the disclosure to a prominent advisory (the run
  still proceeds; this is not a gate)

### Requirement: Canonical per-step invocation manifest (zero prompt-token, host-prefix derived from install location)

`/mgh-init` SHALL 提供确定性叶脚本 `core/scripts/list_steps.py`(对标 `list_clusters.py`/
`list_scout_batches.py`/`list_rule_jobs.py` 同族;R5.2 零运行时依赖、R5.3 自包含、`--help` 即 CLI 契约 R5.1),
作为编排器「每步确切脚本调用行 + 输入/产物 shape」反射的**规范化出口**——专治上下文压力下模型
**猜脚本路径**的失败形状(实测:opencode 下猜 `scripts/merge_scout.py`,实际为
`.opencode/mgh-core/scripts/merge_scout.py`)。其 stdout SHALL 输出结构化 JSON:一个 `steps[]` 数组,
每项 `{step, kind∈bash|subagent, script_abs, invocation, input{artifact, shape}, output{artifact, shape, path_pattern}}`;
退出码 `0/1/2`;stderr 仅诊断/进度(R5.3b)。脚本 SHALL 支持 `--step <id>`(打印单步确切调用行);
默认打印全量紧凑清单(不静默截断,承 R5.3b)。

每步的 `script_abs` / `invocation` 中的**脚本路径 SHALL 是经 `Path(__file__).resolve().parent` 派生的
绝对路径**(本脚本所在 `scripts/` 目录的同族文件),MUST NOT 硬编码宿主前缀、MUST NOT 经提示词传递、
MUST NOT 是相对路径。这使得脚本在 claude install(`<target>/.claude/mgh-core/scripts/`)与 opencode
install(`<target>/.opencode/mgh-core/scripts/`)下分别 emit **正确宿主的同族绝对路径**——**「宿主前缀」
不存在可猜空间**(哪个宿主装的就 emit 哪个宿主的路径,双壳 `.claude/` vs `.opencode/` 手镜像漂移失效)。
模型 SHALL 逐字直抄该绝对路径(任意 cwd 安全),NEVER 自拼 `scripts/` / `mgh-core/scripts/`、
NEVER 漏宿主前缀。

脚本 SHALL **零磁盘前置**:不读 `run_config.json`、不扫 `.mgh-init/`、不依赖任何 run 态产物(step→IO 表
是静态契约)。故其**任意时刻可查**——包括 run 起步前、`--resume`/压缩后、纯文档审阅。这与 `resume_state.py`
(磁盘派生、要求 `run_config.json`)形成互补分工:`resume_state` 答「我在哪 / 下一步干啥」(磁盘真相),
`list_steps` 答「这一步的确切调用行 / 全量 step→IO map」(静态契约);二者**配套**用——`--resume` 或
任何压缩事件后,编排器调 `resume_state.py` 得 `step`/`next_action`,据 `step` 调
`list_steps.py --step <id>` 得确切调用行。

两份命令壳(claude-code / opencode,**逐字镜像**)SHALL 在 Orchestrator discipline 段以**一行 recipe**
声明:需任一步确切脚本路径 / 调用行 / IO shape → `list_steps.py` stdout(宿主前缀自动派生,NEVER 猜);
MUST NOT 把全量 `steps[]` 表内联进提示词正文(护 R5.6 token 预算,正是 D6 列明的冲突点);既有
`Deterministic invocation` 示例块与 inline flow **保留**(示例可直抄,manifest 是「确认/兜底」互补层)。
该 manifest 是 `control-discovery` 编排纪律的一个 aspect,NEVER 替代 `resume_state.py` 的磁盘派生进度。

#### Scenario: list_steps emits host-correct absolute script paths per step

- **WHEN** 在一个 claude install 的目标项目(`<target>/.claude/mgh-core/scripts/list_steps.py`)运行
  `py <target>/.claude/mgh-core/scripts/list_steps.py`
- **THEN** stdout `steps[]` 每项的 `script_abs` 是 `<target>/.claude/mgh-core/scripts/<name>.py` 形态的
  **绝对路径**(经 `Path(__file__).resolve().parent` 派生,非硬编码、非相对),且每条 `invocation` 可
  逐字 `py <abs> <args>` 执行;不出现裸 `scripts/<name>.py` 或漏 `mgh-core/` 前缀

#### Scenario: opencode install emits the opencode prefix (no drift from claude)

- **WHEN** 在一个 opencode install 的目标项目(`<target>/.opencode/mgh-core/scripts/list_steps.py`)运行
  `list_steps.py`,与 claude install 下对比
- **THEN** opencode 下 `script_abs` 落 `<target>/.opencode/mgh-core/scripts/<name>.py`,与 claude 下各自
  指向**自身实际所在** scripts 目录的同族文件;两份 install 各自正确,**NEVER** 出现「claude 壳 emit
  opencode 路径」或反过来的手镜像漂移

#### Scenario: Manifest is queryable pre-run with no disk precondition

- **WHEN** 对一个**尚未跑过** `/mgh-init` 的目标项目(无 `<target>/.mgh-init/`、无 `run_config.json`)
  运行 `py <install>/list_steps.py`
- **THEN** 脚本成功退出(退出码 0)、emit 完整 `steps[]` manifest;**不**因缺 `run_config.json` 或
  `.mgh-init/` 报错或 exit 2(与 `resume_state.py` 要求 run_config 形成互补分工)

#### Scenario: Shell routes path confirmation through list_steps, never guesses prefix

- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md` 的 Orchestrator discipline 段
- **THEN** 两壳均含一行 recipe 指向 `list_steps.py` 作为「确切每步脚本路径/调用行/IO shape」的确认出口,
  且明示「宿主前缀自动派生,NEVER 猜 `scripts/` vs `mgh-core/scripts`、NEVER 漏宿主前缀」;
  全量 `steps[]` 表**不**内联进提示词正文

#### Scenario: Step-id set is consistent with resume_state (drift guard)

- **WHEN** 对比 `list_steps.py` stdout 的 `steps[].step` 集合 与 `resume_state.py` 的 step 枚举
  (`not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`)
- **THEN** 两者 step id 集合一致(或 `list_steps` 为 documented 超集);每 step 的 `script_abs` 指向的
  脚本名在 `core/scripts/` **实际存在**(回归测断言,防双真相源漂移 + 防指向幽灵脚本)

#### Scenario: list_steps is self-contained and offline

- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_steps.py` 或 `py <path>/list_steps.py --step t1` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8、零第三方依赖),stdout 为合法 JSON,退出码 0;`--help`
  暴露 `--step` 且 `--help` 即其 CLI 契约(承 R5.1)

### Requirement: Big-file slice outputs are confined to an absolute in-tree path

`chunk_sources.py` 的切片输出(`--out`)是 fan-out 邻接路径,SHALL 与 `checkpoint_path`/`input_path` 同纪律——绝对、落受信子树、由枚举脚本产出 + 编排器逐字透传。`list_scout_batches.py` 与 `list_clusters.py` 的 stdout `pending[]` 每项 SHALL **额外**携带 `slice_dir`(绝对、`Path.resolve()`、形如 `<init-dir>/slices/<tier>/<safe(unit_id)>/`,其中 `<init-dir>` = `<target>/.mgh-init`、`<tier>` ∈ `scout`/`t1`)。scout/induct subagent 处理大文件(`needs_slice[]` 或运行时发现 > `--big-file-bytes` 的证据文件)SHALL 调 `chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json` 并**回读该确切绝对路径**。subagent NEVER 写相对 `--out`、NEVER 写 cwd/Temp 派生路径、NEVER 写 `<target>/.mgh-init/` 子树之外。`chunk_sources.py` 本身保持 cwd 无关、不假设项目树(承 R5.3a);路径钉死在契约 + 提示词层,非脚本层。

#### Scenario: Slice output lands inside the project tree, not the opencode temp dir
- **WHEN** opencode 下 scout subagent 处理一个含 250KB `LegacyGuard.java`(`needs_slice[]`)的 batch,且 subagent 进程 cwd 为 `C:\Users\<u>\AppData\Local\Temp\opencode\`
- **THEN** subagent 调 `chunk_sources.py --out <slice_dir>/LegacyGuard.slice.json`,其中 `<slice_dir>` = 编排器透传的 `pending[].slice_dir`(绝对、落 `<target>/.mgh-init/slices/scout/<batch_id>/`);切片落该树内路径,subagent 回读该确切路径,**不**向 `…\Temp\opencode\*` 发起 `Read`、**不**触发越权读取提示

#### Scenario: Enumeration stdout carries an absolute slice_dir per pending unit
- **WHEN** 编排器运行 `list_scout_batches.py --materialize <init-dir>/inputs/scout`(或 `list_clusters.py --materialize <init-dir>/inputs/t1`)
- **THEN** stdout `pending[]` 每项含 `slice_dir` 字段,值为 `resolve()` 后的绝对路径且以 `<target>/.mgh-init/slices/<tier>/` 为前缀;编排器将其与 `input_path`/`checkpoint_path` 一同逐字透传给 subagent

#### Scenario: T1 induct slices a runtime-discovered big evidence file in-tree
- **WHEN** `init-induct` subagent 在读某 `evidence_file` 时发现其 > `--big-file-bytes`(该文件未预先列入任何 `needs_slice[]`,系运行时发现)
- **THEN** subagent 用编排器透传的 `slice_dir` + 确定性 stem 规则(`<safe-stem>.slice.json`,`_safe_name` 消毒 `/ \ :`)写切片,回读该确切路径;NEVER 自发明 cwd 相对路径或树外路径

#### Scenario: chunk_sources.py itself stays cwd-agnostic
- **WHEN** 人类或编排器按 `list_steps.py` 示例以 `py chunk_sources.py --in <f> --out <any>` 直接执行(ad-hoc,非 fan-out 切片)
- **THEN** 脚本仍按 `--out` 指定处写出,不强制树内、不假设项目树(cwd 无关性不破);fan-out 树内约束由枚举脚本的 `slice_dir` + subagent prompt 兜,非由 `chunk_sources.py` 兜

### Requirement: Fan-out subagents use absolute tool-script paths pinned to the current install

编排器 SHALL 在 step 0 经 `list_steps.py` stdout 的 `script_abs`(`__file__` 派生 = 当前运行 install 的 `<mgh-core>/scripts/` 目录)取绝对工具基,把绝对 `chunk_sources` 脚本路径逐字透传给 scout/induct subagent task 输入。subagent SHALL 用该绝对路径 verbatim 调用,**NEVER** 用裸名 `chunk_sources.py`、**NEVER** 用相对 `.opencode/mgh-core/scripts/…` / `.claude/mgh-core/scripts/…`(多层 install 下相对路径可经 `.opencode/`/`.claude/` 上溯解析到**别的** install 的副本,实测会命中父层旧版本)。此约束使整 run 只用当前项目(命令壳加载处)的工具副本,与 `<target>` 可独立(允许 install 在 A、分析 B)。

#### Scenario: Subagent uses the orchestrator-broadcast absolute tool path, not a bare name
- **WHEN** 父项目与叶项目均装过本工具(叶项目 `D:\repo\leaf\.opencode\mgh-core\scripts\chunk_sources.py` 为当前版,父项目 `D:\repo\parent\.opencode\mgh-core\scripts\chunk_sources.py` 为 7-20 前旧版),编排器从叶项目调 `/mgh-init`
- **THEN** 编排器经 `list_steps.py`(其 `__file__` 落叶项目 install)取 `script_abs` = `D:\repo\leaf\.opencode\mgh-core\scripts\chunk_sources.py`,逐字透传给 scout subagent;subagent 调该绝对路径,**不**命中父层旧版(不出现旧版 stdout `"node"` 这类版本错位)

#### Scenario: Tool base derived from list_steps script_abs, not from --target
- **WHEN** 编排器需要给 subagent `chunk_sources` 的绝对路径
- **THEN** 它读 `list_steps.py --step discover`(或任一 step)stdout 的 `script_abs`,取其目录作为工具基;NEVER 从 `--target` 拼 `<target>/.opencode/mgh-core/scripts`(install-dir 可与 target 不同)、NEVER 从 mid-session bash env 读工具基(opencode 插件进程不继承,承 R5.7)

### Requirement: Deterministic T1 record gate before T2 synthesis

The `/mgh-init` orchestrator SHALL, after the T1 fan-out wave completes and before advancing to T2
synthesis, run `validate_t1_records.py --strip-bom` and then `validate_t1_records.py --check` over
`<target>/.mgh-init/checkpoints/t1` (the `--strip-bom` pass is always run and is idempotent; the `--check`
pass is the fail-loud gate). On `--check` exit code 2, the orchestrator SHALL invalidate each violating
record's `.done` marker and re-spawn those clusters via `list_clusters` (fail-loud recovery), and MUST
NOT carry broken T1 records into T2 synthesis. This gate is the T1-boundary dual of the existing T2
`validate_inventory.py` gate, closing the path by which LLM-induced T1 record shape drift (e.g. a nested
`controls[]` instead of root-level `evidence`/`entry_points`/`confidence`) is silently dropped by T2.
See capability `t1-record-schema-gate` for the validator contract.

#### Scenario: all T1 records conform — T2 proceeds
- **WHEN** T1 fan-out is complete and `validate_t1_records.py --check` exits 0 over `checkpoints/t1`
- **THEN** the orchestrator advances to T2 synthesis with the validated records

#### Scenario: a T1 record drifts — gate fails loud, broken record never reaches T2
- **WHEN** one or more `checkpoints/t1/*.json` violate the contract shape (e.g. nested `controls[]`)
- **THEN** `--check` exits 2, the orchestrator invalidates the violating clusters' `.done` markers and
  re-spawns them, and does NOT advance to T2 carrying the broken records

#### Scenario: BOM is removed before the shape gate
- **WHEN** T1 records were written with a leading UTF-8 BOM
- **THEN** the orchestrator-run `--strip-bom` removes the BOM before `--check`, so the shape gate sees
  no-BOM records and BOM is never a fail-loud trigger

### Requirement: Merge scout fold-in normalizes non-canonical categories deterministically

`merge_scout.py` fold-in SHALL 用**确定性别名映射**把 scout 候选的非规范类名归一为规范 8 类之一
(`input-validation`/`authentication`/`authorization`/`data-masking`/`crypto`/`rate-limiting`/`csrf`/
`audit-logging`)再写入 `controls_candidates.json` 并参与 `form_clusters`。别名表 SHALL 与
`validate_inventory.py` 的规范 8 类共享**单一真相源**(如常量/helper 放在两脚本均可导入的公共位置,
承 R2 零依赖),至少覆盖既有漂移实例:`access-control→authorization`、`auth→authentication`。
归一 SHALL 发生在 fold-in 写入前(T2 之前),使 T2 `init-synthesis` 与 `validate_inventory.py`
只见到规范类名。`merge_scout.py --check` SHALL 对每条 scout candidate 断言其 `category` 归一后 ∈
规范 8 类;未映射的非规范类 SHALL 作为违例 fail-loud 退出码 2(而非静默丢弃或放行),使类名漂移在
**fold-in 边界**被拦截、而非等到 T2 边界(`validate_inventory.py`)或静默丢进综合。

#### Scenario: Non-canonical scout category is normalized at fold-in

- **WHEN** scout candidate 携带 `category: "access-control"`,fold-in 运行
- **THEN** 写入 `controls_candidates.json` 的该候选 `category` 为 `authorization`,并以其参与
  `form_clusters`;T2 只见规范类名

#### Scenario: merge_scout --check rejects an unmapped non-canonical category

- **WHEN** scout candidate 携带 `category: "runtime-guard"`(不在 8 类、不在别名表),运行
  `merge_scout.py --check`
- **THEN** 退出码 2,violations 报告该 candidate 的 index 与「category 非规范 8 类」issue;
  编排器据此回退重跑 scout-merge,而非带着漂移类名进入 T2

#### Scenario: Canonical categories pass the fold-in check unchanged

- **WHEN** scout candidate 携带规范类名(如 `authorization`),运行 `merge_scout.py --check` 与 fold-in
- **THEN** `--check` 退出码 0;fold-in 不改写该 `category` 原值

#### Scenario: Alias source stays shared between merge_scout and validate_inventory

- **WHEN** 审阅 `merge_scout.py` / `validate_inventory.py` 的类别常量来源
- **THEN** 两脚本引用同一规范 8 类 + 别名表(单一真相源),不允许各自硬编码一份
