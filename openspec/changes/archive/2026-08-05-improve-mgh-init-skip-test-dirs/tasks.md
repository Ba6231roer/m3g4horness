# Implementation Tasks

> 实现纪律:本变更是 `mgh-*` 命令壳 + `core/scripts/*.py` 改动,承 R5 全族(R5.1 契约 lint / R5.3 脚本
> 稳定性 / R5.6 薄壳 / R5.8 自检+回归 / R5.9 边界校验 / R5.10 分发纯净)。镜像既有 `--include-dotfiles`
> 的全部出现点,不发明新机制。确定性脚本经 Bash 执行,NEVER 由编排器 `Read` 叶脚本源码、NEVER 写微脚本。

## 1. 共享枚举层(expand_scope.py)— 单一 chokepoint

- [x] 1.1 在 `core/scripts/expand_scope.py` 紧邻 `EXCLUDE_DIR` 后新增匹配常量:`TEST_PREFIXES =
  ("src/test/", "src/tests/")`(repo 相对 posix 前缀)与 `TEST_SEGMENTS = {"tests", "__tests__",
  "__mocks__", "spec", "specs"}`(目录段集合);加模块注释说明「不含裸 `test`(碰撞)、并行于
  `EXCLUDE_DIR` 不吸收其成员」。
- [x] 1.2 新增内部函数 `_is_test_path(rel_posix: str, parent_parts) -> bool`:`rel.startswith(TEST_PREFIXES)`
  或 `any(seg in TEST_SEGMENTS for seg in parent_parts)`;仅 Python 标准库。
- [x] 1.3 `walk_sources` 增参 `include_tests: bool = True`(默认 True = 保持现状,mgh-sast 不变)与
  `tests_skipped: list | None = None`;`include_tests=False` 时对每个候选文件计算 rel,命中 `_is_test_path`
  则跳过 + `tests_skipped[0] += 1`(仅对 `SOURCE_EXT` 命中的源文件计数,镜像 `dot_skipped` 语义)。注释
  显式标注极性不对称(design D2)。
- [x] 1.4 `collect_dir` 增参 `include_tests: bool = True`;`include_tests=False` 时以同一 `_is_test_path`
  剪枝(`--path`/`--package` scope 解析一致)。

## 2. 发现层(discover_controls.py)— 串入 + argparse + stdout + --check

- [x] 2.1 `collect_sources` 增参 `include_tests: bool = False`(默认 False = 排除)+ `tests_skipped:
  list | None = None`,透传给 `walk_sources`。
- [x] 2.2 `run_discover` / `scan` / `resolve_seed` 各增 `include_tests`/`tests_skipped` 形参并逐层透传
  (镜像既有 `include_dotfiles`/`dot_skipped` 的传参路径);`resolve_seed` 的 `path:`/`package:`/`file:`
  三分支均把 `include_tests` 传给 `collect_dir`/`walk_sources`。
- [x] 2.3 `main` 增 argparse `--include-tests`(action="store_true",help 文案镜像 `--include-dotfiles`,
  指明默认排除测试源码树、传则回退);`tests_skipped = [0]`;`run_discover(...)` 调用传
  `include_tests=args.include_tests, tests_skipped=tests_skipped`。
- [x] 2.4 stdout 摘要 JSON 在 partial 与 full 两路均新增 `"tests_skipped": tests_skipped[0]`,逐字并列于
  既有 `"dotfiles_skipped"`。
- [x] 2.5 `--check`(`_run_check`)校验 discover 产物/摘要:`tests_skipped` 字段存在且为非负整数,否则
  fail-loud 退出码 2(承 R5.9);不破坏既有 wrapper/`source`/cluster_id 唯一性校验。

## 3. 起始态记录(write_runconfig.py)— resume 无状态

- [x] 3.1 `core/scripts/write_runconfig.py` 增 argparse `--include-tests`(action="store_true"),紧随
  `--include-dotfiles`;CLI 契约 docstring 与 `--help` 镜像更新。
- [x] 3.2 `run_config` dict 增 `"include_tests": bool(args.include_tests)`,紧随 `include_dotfiles`。

## 4. resume / 编排器透传校验

- [x] 4.1 确认 `core/scripts/resume_state.py` 是否暴露 per-step 意图 flag:若其当前分支处理
  `include_dotfiles`,则按同方式补 `include_tests`;若不处理(当前 grep 无 `include_dotfiles`),则验证
  discover 调用点从 `run_config.json` 读 `include_tests` 决定是否加 `--include-tests`(镜像 dotfiles 的
  resume 路径)。变更后 `mgh-init --resume` 行为与首跑一致(不丢 `--include-tests`/默认排除)。

## 5. 命令壳(双端对等)— 镜像 --include-dotfiles 全部出现点

- [x] 5.1 `releases/claude-code/commands/mgh-init.md` 与 `releases/opencode/command/mgh-init.md` 的 flag
  表:在 `--include-dotfiles` 行后新增 `--include-tests` 行(默认关;排除测试源码树 `src/test`/`tests`/
  `__tests__`/`__mocks__`/`spec`/`specs`;控制定义点在测试目录内时传此 flag 纳入)。
- [x] 5.2 两壳的 `write_runconfig.py` 调用示例(步骤 0)增 `[--include-tests]`(镜像 `[--include-dotfiles]`)。
- [x] 5.3 两壳的 `discover_controls.py` 调用示例增 `[--include-tests]` 一行(镜像 `--include-dotfiles`
  示例行),保持「不带 `--format`」纪律不变。
- [x] 5.4 两壳的 `boundaries` 披露段:在点前缀边界行后新增测试目录边界行(默认不扫描 + 指向 `--include-tests`
  + `tests_skipped` 计数)。
- [x] 5.5 双壳文案逐字对等(仅路径前缀 `.claude/` vs `.opencode/` 差异);无 R5.x/FDn/`(add|fix|harden)-mgh-*`
  变更夹名等 dev-only 溯源(承 R5.10,`tools/check_distributed_purity.py` 兜底)。

## 6. 契约(若声明 discover stdout schema)

- [x] 6.1 检查 `core/contracts/init/*.md` 是否枚举 discover stdout 摘要字段;若是,补 `tests_skipped`
  并列于 `dotfiles_skipped`;若契约仅描述产物 JSON(`controls_candidates.json`/`clusters.json`/
  `skeleton.json`)schema,则无需改(schema 不变,仅候选集合可能变小 + stdout 新增摘要字段)。

## 7. 测试

- [x] 7.1 `tests/test_init_discover.py`(或 `tests/test_init_runtime.py`)增用例:构造含 `src/test/...`、
  `tests/...`、`__tests__/...`、`spec/...` 与一个单数 `src/main/.../test/...` 生产文件的临时仓 → 默认运行
  断言测试文件不在 candidates/skeleton、`tests_skipped` ≥4、单数 `test` 生产文件仍在;`--include-tests` 后
  测试文件回归。
- [x] 7.2 增 `walk_sources`/`collect_dir` 直测(经 `tests/test_chunk_sources.py` 同款 `_load` 模式或新
  `test_scope_engine.py`):默认 `include_tests=True` 纳入;`include_tests=False` 排除前缀+段集合、保留单数
  `test`、`tests_skipped` 计数正确。
- [x] 7.3 增 `write_runconfig` 用例:`--include-tests` 写入 `run_config["include_tests"]==true`;默认 `false`。
- [x] 7.4 回归:既有 `tests/test_init_discover.py` 的 dotfiles-skip 用例仍绿(测试剪枝不弱化点前缀剪枝)。

## 8. 契约 lint / 纯净性 / 版本 / 全套校验

- [x] 8.1 `py tools/check_contracts.py`:断言双壳每个 `discover_controls.py --include-tests` / 
  `write_runconfig.py --include-tests` flag 在对应脚本 `--help` 中存在(承 R5.1)。
- [x] 8.2 `py tools/check_distributed_purity.py`:双壳无 R5.x/FDn/Dn/变更夹名/`task.*.md`/dev-meta 措辞
  (承 R5.10)。
- [x] 8.3 零依赖 AST 扫描(`tests/test_zero_deps.py`):新增/改动 `.py` 无第三方 import、无 `import
  vvaharness`。
- [x] 8.4 bump 触动到的 `.md` 壳与脚本版本号(承 R5.8)。
- [x] 8.5 `openspec validate improve-mgh-init-skip-test-dirs --strict` 绿;`install.sh` 自检 fail-soft 通过。
- [x] 8.6 全套确定性单测 `py tests/test_deterministic.py`(或逐 `tests/test_init_*.py`)绿。
