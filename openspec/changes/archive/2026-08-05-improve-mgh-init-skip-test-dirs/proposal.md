## Why

`/mgh-init` 的发现阶段(`discover_controls.py`,经共享 `expand_scope.walk_sources`/
`collect_dir`)把所有一方源码当作生产代码扫描以发现**存量安全控制**。当前文件枚举层
只剪枝 `EXCLUDE_DIR`(`node_modules`/`target`/`build`/`vendor` 等)+ 点前缀路径
(`--include-dotfiles` 默认关),**不区分测试源码树**——`src/test/`(Maven/Gradle)、
`tests/`(Python)、`__tests__/`(JS/TS)、`spec/`(Ruby/JS)下的文件被当作生产控制来源扫描。

测试代码对「发现生产安全控制」这一目标是**净噪声**,且以**反信号**为主:

- **mock/stub** 把安全组件(`mock(SecurityChecker)`、`@MockBean SecurityConfig`)物化成
  调用图里的伪「控制」——假实现被当成真控制进 inventory;
- **故意写脆弱的测试夹具**(渗透训练 `VulnerableApp`、负路径样本、禁用 TLS / 放宽 CORS /
  占位密钥 / dummy JWT issuer 的 test 配置)被当成真实控制特征命中,产出**错误规则**;
- 测试代码**不上线**——`mgh-init` 产出的 rules 治理生产代码,test-only「控制」域外。

代价:inventory 被污染、生成的 rules 出错、scout/induct 在测试文件上白烧 LLM 预算
(大型 Java/Gradle 仓 `src/test` 常占 30–50% 源文件)。

**为什么现在**:与最近的 `fix-mgh-init-skip-dotfiles` 同构——后者把点前缀路径(tooling/
VCS/IDE)默认排除出发现域,理由完全一致(非一方生产代码会诱导伪控制)。本变更把同款
「默认排除 + opt-in + 计数披露」纪律延伸到测试源码树,闭合同一类污染面。

## What Changes

- **默认排除测试源码树**:文件枚举层(`expand_scope.walk_sources` / `collect_dir`)在既有
  `EXCLUDE_DIR` + 点前缀剪枝之外,**额外跳过**测试源码根。匹配规则(单一 chokepoint,见
  design):
  - 路径前缀:`src/test/`、`src/tests/`(Maven/Gradle/Kotlin 约定,命中用户原文「src/test」);
  - 目录段集合:`tests`、`__tests__`、`__mocks__`、`spec`、`specs`(Python/JS/Ruby 等生态)。
  - **刻意不含裸 `test`**(单数)作目录段——碰撞风险最高(生产 `com/acme/test/` 工具包、
    Go `test` 包);裸 `test/` 由 `src/test` 前缀与生态段覆盖,单数裸段保持现状(纳入,无回归)。
- **opt-in 回退**:`discover_controls.py` 新增 `--include-tests` flag(默认关 = 排除);传该 flag
  回退到引入本变更前的行为(纳入测试源码)。镜像既有 `--include-dotfiles` 的极性与措辞。
- **计数披露**:discover stdout 摘要新增 `tests_skipped`(本次跳过的测试源文件数,镜像
  `dotfiles_skipped`);`report.md` / `init_manifest.json::boundaries[]` 新增一条诚实边界:
  「测试源码树默认不扫描,控制定义点在测试目录内须传 `--include-tests`」。
- **resume 一致**:`write_runconfig.py` 记录 `include_tests` 进 `run_config.json`(start-state
  intent),使 `--resume` 无状态重派(镜像 `include_dotfiles`)。
- **非跨命令行为变更**:`walk_sources`/`collect_dir` 的新参数 `include_tests` **默认 True**
  (保持现状);只有 `discover_controls`(mgh-init)显式传 `False`(新默认 = 排除)。`mgh-sast`
  (`expand_scope.build_call_graph`)不经该参数 → 行为逐字不变(测试排除作为 mgh-sast 默认是
  另一处行为变更,留给后续独立变更,见 `26080401_issues.md` TODO)。

## Capabilities

### New Capabilities
<!-- 无新能力;测试源码树排除是 control-discovery 既有发现域的一个新默认剪枝 + opt-in。 -->

### Modified Capabilities
- `control-discovery`:发现阶段的文件枚举默认排除测试源码树(新增 requirement「Skip test
  source directories during discovery」);`--include-tests` 成为受识别 flag(修订「Parse
  arguments and guard zero-token no-op」);`tests_skipped` + 测试目录边界入诚实边界披露
  (修订「Disclose honesty boundaries in artifacts」)。

## Impact

- **确定性脚本**(Python ≥3.10 标准库,承 R2 零依赖):
  - `core/scripts/expand_scope.py`:`walk_sources` / `collect_dir` 新增 `include_tests` 参数
    + `TEST_*` 匹配常量 + `tests_skipped` 计数(单一 chokepoint,下游 skeleton/调用图/scout
    目标集一致不见测试源码)。
  - `core/scripts/discover_controls.py`:`collect_sources`/`run_discover`/`scan`/`resolve_seed`/
    `main` 串入 `include_tests`(默认 False=排除)+ `--include-tests` argparse + stdout `tests_skipped`
    (partial + full 两路)+ `--check` 校验该字段。
  - `core/scripts/write_runconfig.py`:`--include-tests` flag + `run_config["include_tests"]`。
- **命令壳**(双端对等,镜像 `--include-dotfiles` 的所有出现点):
  - `releases/claude-code/commands/mgh-init.md` + `releases/opencode/command/mgh-init.md`:flag 表、
    `write_runconfig` / `discover_controls` 调用示例、boundaries 披露段三处。
- **契约 / 提示词**:`core/contracts/init/*` 若声明 discover stdout schema 则补 `tests_skipped`;
  无 stage 提示词改动(剪枝发生在确定性枚举层,LLM 阶段无感)。
- **测试**:`tests/test_init_discover.py` 增「src/test 默认排除 + tests_skipped>0 + --include-tests
  回退」用例;`tests/` AST 零依赖扫描保持绿(无新 import)。
- **契约 lint / 纯净性**(R5.1 / R5.10):`tools/check_contracts.py` 自动断言 `--include-tests` ∈
  `discover_controls.py --help`;`tools/check_distributed_purity.py` 确保双壳不携 R5.x/FDn。
- **版本号**:触动到的 `.md` 壳与脚本 bump(R5.8)。
- **不引入运行时依赖**;不改动既有 `EXCLUDE_DIR` 集合(测试剪枝是并行的独立规则,不吸收既有成员)。
