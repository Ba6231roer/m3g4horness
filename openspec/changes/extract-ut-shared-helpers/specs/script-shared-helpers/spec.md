# script-shared-helpers Specification

## ADDED Requirements

### Requirement: Shared pure-function helper modules exist for the deterministic script family

`core/scripts/` SHALL contain shared helper modules — `runconfig_core.py`, `resume_core.py`,
`assemble_core.py` — holding **pure functions** reusable across the mgh-* deterministic leaf scripts
(`write_runconfig.py`/`write_ut_runconfig.py`, `resume_state.py`/`resume_ut_init_state.py`,
`assemble_rules.py`/`assemble_test_rules.py`). Each core module SHALL be consumed by **at least two**
leaf scripts (no orphan cores). Helper modules SHALL use only Python ≥3.10 stdlib (R2, zero runtime deps),
be self-contained (importable via the leaf scripts' existing `sys.path.insert(0, dir-of-__file__)`
sibling-import pattern), and be mirrored by `install.sh` along with the rest of `core/scripts/`.

`runconfig_core.py` SHALL provide: byte-budget parsing/validation, atomic JSON write (`.tmp` +
`os.replace`), UTF-8 stream reconfigure, and run-dir resolution (accepting a `run_root` parameter — not
hard-coded to `.mgh-init`). `resume_core.py` SHALL provide: marker counting / terminal-state (`.done`/
`.failed`) determination, `_both_marker_violations`, `_next` action construction, `_empty_tiers`, JSON
loading, and run_config loading (accepting a run dir / checkpoints dir parameter). `assemble_core.py`
SHALL provide: lazy-index-block composition, legacy-block stripping, and purity-lint skeleton (accepting
BLOCK markers / FORBIDDEN_TOKENS / lazy copy text as parameters).

#### Scenario: each core is imported by at least two leaf scripts

- **WHEN** 审阅 `core/scripts/` 中六个叶脚本(`write_runconfig.py`/`write_ut_runconfig.py`/
  `resume_state.py`/`resume_ut_init_state.py`/`assemble_rules.py`/`assemble_test_rules.py`)的 import
- **THEN** `runconfig_core` 被两个 write_* 脚本 import;`resume_core` 被两个 resume 脚本 import;
  `assemble_core` 被两个 assemble 脚本 import

#### Scenario: cores are zero-runtime-dependency and sibling-importable

- **WHEN** 运行 `tests/test_zero_deps.py`(AST 扫描 `core/scripts/*.py`)+ 从非 `core/scripts` 目录以
  `py core/scripts/runconfig_core.py` 等直接执行
- **THEN** 无第三方 import;sibling import(`from runconfig_core import ...`)在任意 cwd 可解析

### Requirement: Leaf scripts keep their CLI contract surface unchanged

After extracting shared helpers, each of the six leaf scripts SHALL keep its `--help` output
(argparse definitions), stdout JSON schema, exit codes, and product paths **byte-for-byte identical**
to their pre-change behavior. The core modules are internal implementation detail — callers observe only
`--help`/stdout/exit codes (R5.1 contract surface). `tools/check_contracts.py` SHALL still pass (every
flag advertised in the command shells exists in the corresponding script's `--help`).

#### Scenario: leaf --help flag sets unchanged

- **WHEN** 运行 `py core/scripts/write_runconfig.py --help` 等六个叶脚本的 `--help` + `tools/check_contracts.py`
- **THEN** 每个叶脚本的 flag 集与其变更前逐字一致;`check_contracts` 全绿(双壳广告 flag 均在 `--help`)

#### Scenario: stdout schema and exit codes unchanged

- **WHEN** 以既有回归测的用例调用六个叶脚本(如 `write_runconfig.py --target <t> --format claude`)
- **THEN** stdout JSON 字段与退出码与变更前逐字一致(`test_write_runconfig.py`/`test_resume_state.py`/
  `test_resume_ut_init_state.py`/`test_ut_init_runtime.py`/`test_assemble_rules.py`/`test_test_rules_purity.py`
  全绿)

### Requirement: Core signatures are neutral to a third consumer (.mgh-ut)

The `runconfig_core` / `resume_core` signatures SHALL accept the run dir / run-root / checkpoints dir as
parameters rather than binding to `.mgh-init` / `.mgh-ut-init` names, and `assemble_core` SHALL accept
BLOCK markers / FORBIDDEN_TOKENS / lazy copy text as parameters — so that a future command using a
different run dir (e.g. `/mgh-ut` with `.mgh-ut`) can reuse the same cores without copy or rewrite.

#### Scenario: run-root parameterization is name-neutral

- **WHEN** 审阅 `runconfig_core` 的 run-dir 解析与 `resume_core` 的 marker/终态判定签名
- **THEN** 二者接收 `run_root` / 运行目录 / checkpoints 目录参数,不硬编码 `.mgh-init` 或 `.mgh-ut-init`

#### Scenario: assemble params are configurable, not hard-coded

- **WHEN** 审阅 `assemble_core` 的索引块组装与 lint 骨架签名
- **THEN** 其接收 BLOCK 标记 / FORBIDDEN_TOKENS / 惰性文案参数,不硬编码 `security-controls` 或
  `test-conventions` 文案

### Requirement: Behavior preservation — regression suite and lints stay green

This change SHALL NOT alter the observable behavior of the `mgh-init` or `mgh-ut-init` pipelines. All
existing regression tests SHALL pass; contract lint, distributed-purity lint, and zero-dependency AST scan
SHALL pass. Any changed `.md`/script SHALL bump the corresponding version. A shared-ownership regression
test SHALL assert that the shared functions are imported from the cores (not re-inlined in the leaf
scripts), preventing drift back to copy-paste.

#### Scenario: shared-ownership test guards against re-inline

- **WHEN** 运行共享归属回归测(如 `tests/test_shared_helpers.py`)
- **THEN** 断言六个叶脚本对 atomic-write / marker 判定 / 索引块组装等函数 `from <core> import ...` 而非
  本地重新定义;既有回归测 + 三项 lint 全绿

#### Scenario: install self-check stays fail-soft and passes

- **WHEN** 运行 `install.sh` 的脚本族同目录共存自检
- **THEN** 新增的 3 个 core 模块与既有脚本同目录共存校验通过;自检失败仅 warn、不阻断 install(CI 必 fail)
