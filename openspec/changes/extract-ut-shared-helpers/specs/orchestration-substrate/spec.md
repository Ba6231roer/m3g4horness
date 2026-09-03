## ADDED Requirements

### Requirement: Script-level shared helper cores complement the --run-root parameterization

The orchestration substrate SHALL extend beyond the `--run-root` run-dir parameterization to include
**script-level shared helper cores** in `core/scripts/` (`runconfig_core.py` / `resume_core.py` /
`assemble_core.py`) that the `write_runconfig.py` / `write_ut_runconfig.py`, `resume_state.py` /
`resume_ut_init_state.py`, and `assemble_rules.py` / `assemble_test_rules.py` leaf scripts import for
pure-function logic (atomic write, byte-budget validation, run-dir resolution, marker/terminal-state
determination, lazy-index-block composition, purity-lint skeleton). The existing `--run-root`
Requirement's behavior SHALL be preserved unchanged (flag surface intact, default `.mgh-init` still
byte-identical for mgh-init). The shared cores SHALL accept their run dir / checkpoints dir / BLOCK /
FORBIDDEN_TOKENS / lazy-copy as parameters (not hard-coded to `.mgh-init` / `.mgh-ut-init`), so a future
command with a different run dir (e.g. `/mgh-ut` → `.mgh-ut`) reuses the same cores.

#### Scenario: --run-root requirement invariant holds after extraction

- **WHEN** 以既有 `--run-root` 用例调用 `resume_state.py` / `write_runconfig.py`(默认 `.mgh-init`、
  `--init-dir` 优先、命名目录)
- **THEN** 行为与变更前逐字一致(运行目录解析、stdout、退出码不变;`test_resume_state.py` /
  `test_write_runconfig.py` 全绿)

#### Scenario: leaf scripts delegate pure logic to cores instead of inlining

- **WHEN** 审阅六个叶脚本的 import 与 `core/scripts/` 目录
- **THEN** `write_runconfig.py`/`write_ut_runconfig.py` 从 `runconfig_core` import 原子写/run-dir 解析;
  `resume_state.py`/`resume_ut_init_state.py` 从 `resume_core` import marker/终态判定;
  `assemble_rules.py`/`assemble_test_rules.py` 从 `assemble_core` import 索引块组装/lint 骨架
