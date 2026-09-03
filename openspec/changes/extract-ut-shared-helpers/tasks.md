# Tasks — extract-ut-shared-helpers

> 实现顺序按依赖;每个任务可验证。**行为保持是硬约束**:六个叶脚本的 `--help` 契约面、stdout JSON、
> 退出码、产物路径逐字不变。core 模块全部 Python ≥3.10 标准库、零依赖、自包含。任一 `.md`/脚本改动
> bump 版本号。

## 1. runconfig_core(共享运行目录 + 原子写 + 预算校验)

- [ ] 1.1 建 `core/scripts/runconfig_core.py`:移入 `_parse_bytes`(byte 预算解析)、`_atomic_write_json`
  (`.tmp` + `os.replace`)、UTF-8 stream reconfigure、run-dir 解析(`--init-dir` > `<target>/<--run-root>` >
  默认 `.mgh-init`)。签名接收 `run_root` 参数,**不硬编码** `.mgh-init`/`.mgh-ut-init`。
- [ ] 1.2 `core/scripts/write_runconfig.py` 改 `from runconfig_core import ...`,删除本地重复定义;argparse
  flag 集、run_config schema、ack stdout **逐字不变**。
- [ ] 1.3 `core/scripts/write_ut_runconfig.py` 同上(保留其抽样 flag/schema 专属部分)。

## 2. resume_core(共享 marker/终态判定)

- [ ] 2.1 建 `core/scripts/resume_core.py`:移入 `_load_json`、`_run_config`、`_count_markers`、
  `_marker_exists`、`_both_marker_violations`、`_next`、`_empty_tiers`(签名接收运行目录 / checkpoints 目录
  参数,不绑 init/ut-init 名)。
- [ ] 2.2 `core/scripts/resume_state.py` 改 `from resume_core import ...`,删除本地重复定义;`resolve()`
  step-graph(discover/scout/t1–t4/merge)留本脚本。
- [ ] 2.3 `core/scripts/resume_ut_init_state.py` 同上(其 step-graph classify→extract→…→mutators 留本脚本)。

## 3. assemble_core(共享索引块 + 纯净 lint)

- [ ] 3.1 建 `core/scripts/assemble_core.py`:移入索引块组装(`_compose_index_block`/`_merge_into`/
  `_strip_legacy_blocks`)、纯净 lint 骨架(`_lint`/`_display_name`/`_index_ref`),接收 BLOCK 标记 +
  FORBIDDEN_TOKENS + 惰性文案参数。
- [ ] 3.2 `core/scripts/assemble_rules.py` 改 `from assemble_core import ...`,删除本地重复定义;BLOCK 标记
  (`security-controls`)、FORBIDDEN_TOKENS、惰性文案留本脚本。
- [ ] 3.3 `core/scripts/assemble_test_rules.py` 同上(BLOCK 标记 `test-conventions` 留本脚本)。

## 4. 归属回归测 + 契约 lint 兜底

- [ ] 4.1 建 `tests/test_shared_helpers.py`:断言六个叶脚本对原子写 / marker 判定 / 索引块组装等函数
  `from <core> import ...` 而非本地重新定义;断言 core 签名接收 `run_root`/checkpoints 参数(名中立)。
- [ ] 4.2 扩 `tools/check_contracts.py`(如需):六个叶脚本 `--help` flag 集未漂(双壳广告 flag 仍在)。
- [ ] 4.3 跑全套回归(`test_write_runconfig.py`/`test_resume_state.py`/`test_resume_ut_init_state.py`/
  `test_ut_init_runtime.py`/`test_assemble_rules.py`/`test_test_rules_purity.py`/`test_init_runtime.py`)+
  三项 lint(契约/纯净/零依赖 `test_zero_deps.py` 放行新 sibling import);bump 版本号;
  `install.sh` 自检 fail-soft。

## 5. 分发纯净 + 收尾

- [ ] 5.1 核对分发纯净 lint(`test_distributed_md_purity.py`)——core 模块不进分发面,无新悬空引用;壳/README
  若提及脚本内部路径则核对(一般不动)。
- [ ] 5.2 冒烟:在既有 mgh-init 产物目录跑 `resume_state.py --check` + `write_runconfig.py --help`,确认
  输出与变更前逐字一致;`mgh-ut-init` 同验。
