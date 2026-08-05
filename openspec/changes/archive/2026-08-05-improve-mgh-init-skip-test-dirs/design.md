## Context

`/mgh-init` 发现阶段经共享 `expand_scope.walk_sources` / `collect_dir` 枚举一方源码,在其上
发现**存量安全控制**。当前枚举层剪枝:
- `EXCLUDE_DIR`(精确分量匹配:`node_modules`/`target`/`build`/`vendor`/`__pycache__`…);
- 点前缀路径(任何相对 repo 的 `.` 开头分量,`--include-dotfiles` 默认关;见既有 requirement
  「Skip dot-prefixed paths during discovery」,`fix-mgh-init-skip-dotfiles`)。

二者**都不识别测试源码树**——`src/test/`、`tests/`、`__tests__/`、`spec/` 下的文件被当生产
代码扫描。本变更把同款「默认排除 + opt-in + 计数披露」纪律延伸到测试源码树。

关键现有锚点(逐字镜像而非新发明):
- 参数/计数模板:`expand_scope.walk_sources(..., include_dotfiles=False, dot_skipped=None)` →
  `discover_controls.collect_sources`/`run_discover`/`scan`/`resolve_seed`/`main` → argparse
  `--include-dotfiles` + `dot_skipped=[0]` → stdout `dotfiles_skipped`(partial + full 两路)。
- 共享 chokepoint 语义:文件枚举层剪枝统一作用于 regex 候选 / `skeleton.json` / 调用图 / scout 目标集
  (单一剪枝点,非仅 regex 一路)——见「Dot-prefix skip is consistent across all downstream stages」场景。

本设计**复刻**该模板到 `include_tests` / `tests_skipped`,不发明新机制。

## Goals / Non-Goals

**Goals:**
- 文件枚举层默认排除测试源码树(单一 chokepoint),使 regex 候选 / skeleton / 调用图 / scout 目标集
  一致不见测试源码——而非仅 regex 一路。
- 命中用户原文「src/test 目录下所有文件」(Maven/Gradle),并合理覆盖主流生态测试根
  (`tests`/`__tests__`/`__mocks__`/`spec`/`specs`)。
- opt-in 回退(`--include-tests`)+ 计数披露(`tests_skipped`)+ 诚实边界入 `report.md`/`init_manifest`,
  使「控制定义点在测试目录内」可被发现、可追溯、不静默。
- `--resume` 无状态:`run_config.json` 记 `include_tests`(镜像 `include_dotfiles`)。
- **零行为变更外溢到 mgh-sast**:共享函数默认保持现状,仅 mgh-init 发现层 opt-in 排除。

**Non-Goals:**
- **不改 mgh-sast 默认**:`expand_scope.build_call_graph`(mgh-sast 调用链扩展)默认仍纳入测试源码。
  将 mgh-sast(以及 mgh-sra/srr 若其触及目标仓源码树)的测试排除作为**独立后续变更**(见
  `26080401_issues.md` TODO),避免本变更成为跨命令行为变更(承「split cross-cutting changes」纪律)。
- 不改 `EXCLUDE_DIR` 集合(测试剪枝是并行独立规则)。
- 不引入运行时依赖(承 R2)。
- 不改任何 LLM stage 提示词(剪枝发生在确定性枚举层,LLM 阶段无感)。

## Decisions

### D1 — 匹配器:路径前缀 + 受限目录段集合;刻意不含裸 `test`

匹配规则(单一函数 `_is_test_path(rel, parts)`):

```
TEST_PREFIXES  = ("src/test/", "src/tests/")          # Maven/Gradle/Kotlin
TEST_SEGMENTS  = {"tests", "__tests__", "__mocks__", "spec", "specs"}  # 目录分量(非文件名)
命中 = rel.startswith(prefix) OR (any(seg in TEST_SEGMENTS for seg in parent_dir_parts))
```

- **前缀 `src/test`/`src/tests`** 精确命中用户原文与 Java/Kotlin/Gradle 约定,零生产代码附带损害。
- **段集合用复数 `tests` + 生态专用 `__tests__`/`__mocks__`/`spec`/`specs`**,覆盖 Python(`tests/`)、
  JS/TS(`__tests__/`、`tests/`)、Ruby/JS(`spec/`、`specs/`)。
- **刻意排除裸 `test`(单数)作目录段**:碰撞风险最高——生产 `com/acme/test/` 工具包、Go `test` 包、
  `src/main/.../test/` 辅助包会被误删。单数裸 `test/` 由 `src/test` 前缀覆盖(Java 已命中);其余生态的
  单数 `test/` 保持现状(纳入,无回归),用户可 `--include-tests` 不影响。

**Alternatives considered**:
- *仅 `src/test` 前缀*:精度最高但漏 Python `tests/`、JS `__tests__`、Ruby `spec/`——半措施,用户
  生态无关的「排除测试」目标会被迫后续再改。
- *加裸 `test` 入段集合*:覆盖最广但附带损害(生产 `test` 命名包) unacceptable for a default-ON 剪枝。
- *加 `mocks`/`stubs`/`fixtures` 入段集合*:这些常作测试**子目录**(已在测试根下,被剪),但作顶层
  生产目录名也常见(如 `src/main/resources/fixtures`)——碰撞,故不入。

### D2 — 极性不对称:共享函数默认 True(保持),发现层默认 False(排除)

- `expand_scope.walk_sources(..., include_tests: bool = True)` / `collect_dir(..., include_tests=True)`:
  **默认 True = 纳入 = 现状**。mgh-sast 的 `build_call_graph` 不传该参数 → 逐字不变。
- `discover_controls.collect_sources(..., include_tests: bool = False)` 及其下游:`main` 绑定
  `--include-tests`(store_true,默认 False = 排除)→ 显式传 `include_tests=False` 给共享函数。

**Rationale**:避开跨命令行为变更。若共享函数默认 False(排除),则 mgh-sast 默认也排除测试源码——
那是另一处需独立评估的行为变更(SAST 扫测试码的取舍不同),本变更不夹带。镜像既有 `include_dotfiles`
的**形状**(bool 参数 + 计数 + opt-in),但**翻转默认所在层**(dotfiles 在共享层默认 False;tests 在
共享层默认 True、发现层默认 False),正是为了 non-cross-cutting。代码注释显式标注该不对称意图。

### D3 — 单一 chokepoint(镜像 dotfiles)

剪枝只发生在 `walk_sources` / `collect_dir` 两个函数内(现有唯一枚举入口)。`discover_controls` 全部
下游(`index_files`/`build_call_graph`/`scan_candidates`/`build_skeleton`/`plan_scout`)消费同一份物化
文件清单,故测试源码对 regex 候选、`skeleton.json`、调用图、scout 目标集**一致不可见**,而非仅 regex
一路。这与既有「Dot-prefix skip is consistent across all downstream stages」场景同构,无新机制。

### D4 — 计数披露 + 诚实边界(镜像 dotfiles)

- discover stdout 摘要(partial + full 两路 JSON)增 `tests_skipped: <int>`,逐字并列于既有
  `dotfiles_skipped`。
- `report.md` / `init_manifest.json::boundaries[]` 增一条:「测试源码树(`src/test`/`tests`/`__tests__`/
  `spec`/`specs`)默认不扫描——控制定义点落在测试目录内须传 `--include-tests`」,与既有 dotfiles 边界并列。
- `--check`(R5.9)校验 `tests_skipped` 字段存在且为非负整数(fail-loud 退出码 2 若产物破损)。

### D5 — resume 一致(镜像 dotfiles)

`write_runconfig.py` 增 `--include-tests` → `run_config["include_tests"]`(bool)。`--resume` 时编排器
从 `run_config` 读该字段决定是否给 discover 加 `--include-tests`(与 `include_dotfiles` 同路径)。本变更
不要求改 `resume_state.py`(其当前不按 `include_dotfiles` 分支;discover 调用点直接读 run_config)——
若 apply 阶段发现 resume_state 暴露 per-step 意图 flag,则按 `include_dotfiles` 同样方式补 `include_tests`。

## Risks / Trade-offs

- **[生产代码落在测试命名目录被漏报]** 如 `com/acme/tests/` 实为生产包 → 默认排除会漏发现其控制。
  → **Mitigation**:计数披露(`tests_skipped`)+ 诚实边界明示 + `--include-tests` opt-in 回退;匹配器刻意
  排除裸单数 `test`(最高碰撞形态)。属已知精度边界,与 dotfiles-skip 同性质(披露 + opt-in,非静默)。
- **[极性不对称致未来维护者困惑]** 共享层默认 True、发现层默认 False 不直观。
  → **Mitigation**:`expand_scope.walk_sources` 参数注释 + `discover_controls.collect_sources` 签名注释
  显式标注「默认 True 保持 mgh-sast 不变;mgh-init 显式 opt-in 排除」;design.md D2 承载 rationale。
- **[裸单数 `test/` 不被排除(JS/Go 约定)]** → **Mitigation**:by design(碰撞);`src/test` 前缀覆盖 Java;
  其余生态用户可 `--include-tests`(当前纳入 = 无回归,只是不排除)。记入 `26080401_issues.md` 待评估是否
  扩展。
- **[mgh-sast 仍扫测试码]** → **Non-goal**(D2);独立后续变更。本变更不夹带跨命令行为变更。
- **[契约 lint / 纯净性回归]** 新 flag 必须进 `--help`(R5.1)、双壳不得携 R5.x/FDn(R5.10)。
  → **Mitigation**:`tools/check_contracts.py` + `tools/check_distributed_purity.py` + CI(R5.8)兜底;tasks
  含「跑全套校验」步骤。

## Migration Plan

- **默认行为变更**:本变更生效后,测试源码树默认不进发现域。`tests_skipped` 计数让用户感知跳过量。
- **受影响用户**:安全控制定义点**仅**存在于测试代码的项目(罕见;典型为安全集成测试即控制契约)→
  传 `--include-tests` 回退到旧行为。
- **Rollback**:`--include-tests`(per-run);卸载本变更则恢复全局旧默认。
- **无磁盘 schema 变更**:discover 产物(`controls_candidates.json`/`clusters.json`/`skeleton.json`)schema
  不变,仅候选集合可能变小(测试码不再贡献);新增的是 stdout `tests_skipped` 摘要字段(附加,非破坏)。

## Open Questions

- 是否需要把「测试目录排除」上报进 `init_manifest.json` 的一个可机读字段(而非仅 `boundaries[]` 散文)?
  倾向:复用 `boundaries[]` 一条(与 dotfiles 同形态);若下游 `/mgh-blst` 需判「是否排除了测试」,再加
  专用字段——留待 `/mgh-blst` 设计时定。
