## Why

`task.260805.md` 的第二纵向第二命令:diff 驱动的**测试质量门**。定位在 openspec apply 之后、archive
之前(也适用于其它 SDD 工具流程与无 SDD 的普通 diff)。`mgh-ut-init`(P1)已产出测试约定 rules +
pitest 派生默认 mutator 清单;`/mgh-ut` 是它们的消费方,把「diff 中新增/改方法行为」的单元**无条件**
审计既有测试质量 + 补缺/增强 + 变异硬化(mutator 透镜喂 LLM 写「足以杀死变异」的测试,**不实跑
pitest**),产出**暂存供人/apply 评审**的增强提案。本命令建于共享基座(编排纪律 fragment +
`runconfig_core`/`resume_core`,后者由 `extract-ut-shared-helpers` 提供)。

## What Changes

- 新命令 `/mgh-ut`(claude + opencode 薄壳,`REQUIRED SUB-SKILL` 引用 orchestrator-discipline)。
- `extract_diff_units.py`(确定性):`git diff <base>..<head>` → 行为变更方法单元(排除 cosmetic/rename/
  move/delete;方法级优先,codegraph 增强;启发式阈值判「行为变更」)。
- 逐单元流水线(subagent `ut-audit`/`ut-generate`/`ut-consistency`):
  ① 定位覆盖该方法的既有测试(codegraph 符号引用/命名约定);② 审计(弱测试信号 + mutator 透镜打分 →
  findings);③ 补缺(新测试/强化断言以杀死已配 mutator + 覆盖分支,**MUST 按发现的 mock 约定 mock
  协作者**);④ (可选)富化(读未归档 SDD spec 取需求意图,openspec 优先)。
- **补缺产出暂存 `.mgh-ut/proposals/`**(不直写 `src/test`;承「LLM 候选需人评」纪律)。
- mutator 透镜复用 pitest 分类法(决策 A/Q1);清单默认取 `default_mutators.json`(ut-init 派生),
  `--mutators` 覆盖。
- 第 6 个 hook 运行域 `MGH_UT_ACTIVE` + `.mgh-ut/.active` 哨兵,双端对等 + parity 测。
- 无 ut-init rules 时优雅降级:从 diff 邻近测试惰性发现约定。

## Capabilities

### New Capabilities

- `diff-test-quality-gate`: `/mgh-ut` 命令的规约——diff → 行为变更单元 → 逐单元审计 + 补缺 + 变异硬化,
  产出暂存提案;mutator 透镜 / SDD 富化 / mock-约定强制 / 优雅降级 / 诚实边界。

### Modified Capabilities

- `runtime-hook-enforcement`: 新增第 6 域 `mgh-ut`(`MGH_UT_ACTIVE`/`.mgh-ut/.active`),域表 env 名单、
  run-root 表、受信子树表从 5 域扩到 6 域。

## Impact

- **Affected code**: 新壳 `releases/claude-code/commands/mgh-ut.md` + `releases/opencode/command/mgh-ut.md`;
  新确定性脚本 `extract_diff_units.py` + mgh-ut 的 run-config/resume 挂 `runconfig_core`/`resume_core`;
  新 subagent 提示词 `core/prompts/stages/ut-{audit,generate,consistency}.md` + agent 定义;
  `core/contracts/ut/` 契约;`block_adhoc_scripts.py` 域表加 1 行 + 受信子树;parity/回归测。
- **影响面**:
  - `mgh-init`/`mgh-ut-init`/sast/sra/srr 调用方:零感知(hook 域表加行是新增,不改既有域)。
  - 目标项目:`.mgh-ut/` 运行目录 + `.claude/mgh-core/` 镜像新增组件。
  - `tests/test_opencode_hook_parity.py`/`test_block_adhoc_scripts.py` 扩到第 6 域。
- **无**第三方依赖(R2,`extract_diff_units.py` 经 `git` 子进程驱动目标仓工具链,非 mgh 自身 pip 依赖);
  **无**数据迁移(新命令新产物目录);`src/test` **不**被直写(提案暂存 `.mgh-ut/proposals/`)。
