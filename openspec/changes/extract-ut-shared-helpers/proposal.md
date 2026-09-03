## Why

`task.260805.md` 的 P1(`add-mgh-ut-init`)归档时把 F10 暂缓入 risk:F10 认定 `write_ut_runconfig.py` /
`resume_ut_init_state.py` / `assemble_test_rules.py` 三组 ut-init 脚本是 `write_runconfig.py` /
`resume_state.py` / `assemble_rules.py` 的拷贝,并明示「待 `/mgh-ut` 出现第 2 个 ut 消费者时,再评估
抽共享 helper」(P1 决策 5 演进路径)。本变更即兑现该承诺:P2(`add-mgh-ut`)需要的 `.mgh-ut` run-config /
resume-state 脚本是**同一批 core 的第 3 个消费者**——先抽 core、行为保持,再让 P2 挂同 core,避免出现
第 3、4、5 份漂移拷贝。现量:三对脚本 diff 各有 40–70% 重复(`assemble_test_rules` 经 review 称 72%
重复 `assemble_rules`),拷贝间 drift 已由各自单测兜底,但维护面重复、新命令再复制只会更糟。

## What Changes

- 在 `core/scripts/` 建 **3 个共享 helper 模块**(sibling-import 复用,承 R5.3a 自包含模式,如
  `merge_scout → discover_controls` 前例):
  - `runconfig_core.py` — 运行目录解析(`--init-dir` > `--run-root` > 默认)、byte-budget 校验、
    原子写 `.tmp`+`os.replace`、UTF-8 流 reconfigure。
  - `resume_core.py` — marker 计数 / 终态(`.done`/`.failed`)判定、`_both_marker_violations`、
    `_next` action 构造、`_empty_tiers`、`--check` 自洽骨架。
  - `assemble_core.py` — opencode 惰性索引块组装(`_compose_index_block`/`_merge_into`/
    `_strip_legacy_blocks`)、双格式纯净 lint(`_lint`/`_display_name`/`_index_ref`),由各命令以
    BLOCK 标记 + FORBIDDEN_TOKENS + 惰性文案参数化。
- 六个叶脚本改为**导入上述 core**:`write_runconfig.py`/`write_ut_runconfig.py`/`resume_state.py`/
  `resume_ut_init_state.py`/`assemble_rules.py`/`assemble_test_rules.py`。**每个脚本的 `--help`(R5.1
  契约面)、argparse 定义、stdout JSON schema、退出码、产物路径全部保持逐字不变**——只把可复用纯函数
  移到 core,命令专属 flag/schema/step-graph 留各脚本。
- **行为保持是硬约束**:`mgh-init` 与 `mgh-ut-init` 的既有回归测(`test_write_runconfig.py` /
  `test_resume_state.py` / `test_resume_ut_init_state.py` / `test_assemble_rules.py` /
  `test_ut_init_runtime.py` / `test_test_rules_purity.py`)全绿;两项 lint(`check_contracts` /
  `check_distributed_purity`)与零依赖 AST 扫描不破。
- 为 P2 铺路:`runconfig_core` / `resume_core` 的调用签名对「第 3 个消费者(`.mgh-ut`)」中立(不绑定
  init/ut-init 专属 flag 名),P2 挂同 core 零重写。

## Capabilities

### New Capabilities

- `script-shared-helpers`: 确定性叶脚本族共享纯函数 helper 模块(runconfig_core / resume_core /
  assemble_core)的规约——sibling-import 复用、零运行时依赖、各命令 `--help`/stdout/退出码/产物路径
  行为保持、命令专属 schema 与 step-graph 留各脚本。

### Modified Capabilities

- `orchestration-substrate`: 现有 `--run-root` Requirement 不变量保留(flag 面不变);本变更**只新增**
  共享脚本 helper 模块这一独立 concern,不改变既有 requirement 行为 → 以 ADDED delta 承载。

## Impact

- **Affected code**: `core/scripts/` 新增 3 个共享模块 + 6 个叶脚本改导入(纯函数删除、逻辑不进
  入/移出行为面);`tests/` 增补共享-归属回归测(断言核心函数确实在 core 而非各脚本重复定义)。
- **影响面**:
  - `mgh-init` 调用方:零感知(行为字节级一致,`--help` 面不变)。
  - `mgh-ut-init` 调用方:零感知(同上)。
  - 后续 P2 `add-mgh-ut`:直接挂 `runconfig_core`/`resume_core`,本变更是最短前置。
  - `install.sh` 镜像:core/scripts 全目录镜像,新模块随镜像,无分发改动。
- **无**第三方依赖(R2);**无** data/schema 迁移(产物 JSON schema 不变);**无** BREAKING。
