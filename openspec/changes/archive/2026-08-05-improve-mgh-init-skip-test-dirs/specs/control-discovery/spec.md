## ADDED Requirements

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

## MODIFIED Requirements

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
