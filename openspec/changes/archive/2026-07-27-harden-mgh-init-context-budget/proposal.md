## Why

`/mgh-init` 在大仓扇出时,opencode 宿主 agent(实测 DeepSeek-V4-Flash)把 `.mgh-init/t1_pending.json`
(426KB)**整份读进编排器上下文**,导致其后每次大模型请求过大、被截断。根因是**契约缺口 + 全流水线无阈值**:

1. **契约缺口**:三个扇出枚举脚本(`list_clusters`/`list_scout_batches`/`list_rule_jobs`)只回 *lite* 待办壳
   (单元 id + 绝对输出路径),但 `init-induct`/`init-scout`/`init-rulewriter` 提示词要求**完整 per-unit 记录**
   (簇记录 + 候选命中 + `usage_sites` / batch `targets` / 该 category 的 controls)。sanctioned 出口里**没有
   「按单元取完整记录」的原语** → 编排器被结构性推向**整份读** `clusters.json`/`controls_inventory.json`/
   `scout_plan.json`,弱模型直接 `py -c`/`ReadAllBytes` 兜底 = 426KB(正是 R5.2(b) 要拦的形状)。
2. **无阈值**:work-list、per-unit 记录、T2/merge/T4 聚合输入**皆无可配置上界**。`--scout-batch-bytes` 只 bound
   scout 批输入。

> 用户诉求双重:(a) 解决这次 426KB;(b) 从根源保证**每次请求上下文 ≤ 可配置阈值**。
> 排查发现该契约缺口**四条 `mgh-*` 命令同构**(init/sast/sra/srr 的枚举脚本同型)。故本 change 作**地基**:
> 引入横切能力 `request-context-budget`(四命令统一机制 + 命令映射表)+ 物化契约 + hook recipe + **在 init 端到端落地参考实现并修复本次 bug**;sast/sra/srr 的采纳由后续 `harden-mgh-{sast,sra,srr}-context-budget`
> 承接(各为精简独立 change,本 change 不实现)。

## What Changes

- **新增横切能力 `request-context-budget`**:每条 `mgh-*` 命令每次大模型请求 ≤ 可配置字节阈值,确定性边界强制。
  机制(per-unit 输入物化到文件由 subagent 自读 + 编排器 slim 分页待办壳 + 超阈值切分/标注 + 聚合有界/披露 +
  无静默溢出)+ 「命令→枚举脚本→多单元聚合→聚合 stage」映射表。**本 change 实现 init;sast/sra/srr 标「后续」**。
- **init 端到端落地(参考实现 + 修 bug)**:`list_clusters`/`list_scout_batches`/`list_rule_jobs` 增
  `--materialize <dir>`,把每单元完整输入写到 `<target>/.mgh-init/inputs/<tier>/<unit>.input.json`(绝对、幂等、
  `--resume` 复用),`pending[]` 每项回 `input_path` + `bytes` + `oversize`;subagent **读自己的 `input_path`**;
  编排器**只透传路径**,NEVER 整份读多单元聚合。
- **slim 待办壳 + 分页**:`pending[]` 剔除 `evidence_files[]` 等可变长负载;三脚本增 `--offset/--limit`;单页 >
  `--orch-budget-bytes` → 自动收紧 `--limit` + `effective_limit`/`shrunk:true`。
- **可配置阈值**:`--max-unit-bytes`(192KB;T1 簇切 `::shard-<n>`、scout 超大文件走 `chunk_sources`、T3 category
  标 `oversize` 不切)、`--orch-budget-bytes`(64KB)、`--max-aggregate-bytes`(256KB)。
- **聚合 stage 分阶段(P0)**:T2 `init-synthesis`/`init-scout-merge`/T4 聚合输入上报 `bytes`;超
  `--max-aggregate-bytes` → 披露 + `--scope`/`--merge` 回退(P0 软边界;P1 分层归约留后续)。
- **命令壳 + 提示词 + hook + 契约 lint(双端)**:两份 `mgh-init.md` 纪律段/flow/flag 表/discard;三 stage 提示词
  输入改「读 `input_path`」;`block_adhoc_scripts` recipe 增「整份读多单元聚合 → 指向 `input_path`」(双端、四运行域,
  一次覆盖,后续 sast/sra/srr 直接复用);`tools/check_contracts.py` 扩 init flag 覆盖(后续各 adoption 各加各的)。
- **修正一处 spec 错放**:T3 枚举(`list_rule_jobs`)归 `rules-emission`(此前误置 control-discovery)。

**fan-out 契约变更(内部,非用户 breaking)**:subagent 输入从「编排器内联传记录」改为「读 `input_path`」;新 flag
皆 additive。**非目标**:不改既有产物产出 schema(只新增 `input_path`/`bytes`/`oversize` + `inputs/` 目录);不引入
第三方依赖(承 R2);P0 不重写聚合 stage 为 map-reduce;**本 change 不实现 sast/sra/srr**(后续 adoption change);
预算单位用字节。

## Capabilities

### New Capabilities
- `request-context-budget`: **横切能力**(地基)——四条 `mgh-*` 命令每次大模型请求 ≤ 可配置字节阈值,确定性边界
  强制。覆盖:预算 CLI 语义、per-unit 物化契约、slim 分页待办壳、oversize 处置、聚合 stage 有界/披露、无静默溢出;
  附「命令→脚本→聚合」映射表。**实现进度**:init = 本 change;sast/sra/srr = 后续 `harden-mgh-{sast,sra,srr}-context-budget`。

### Modified Capabilities
- `control-discovery`: init T1 `list_clusters` + scout `list_scout_batches` 采纳物化/分页/预算;编排器纪律增
  「NEVER 整份读多单元聚合」。
- `rules-emission`: init T3 `list_rule_jobs` 采纳物化/分页/预算(从 control-discovery 纠正归位)。

> sast/sra/srr 各自命令 spec 的采纳 MODIFIED 见对应 adoption change,不在本 change。

## Impact

- **代码(init 脚本)**:`list_clusters.py`/`list_scout_batches.py`/`list_rule_jobs.py`——各增 `--materialize`/
  `--offset`/`--limit`/`--max-unit-bytes`/`--orch-budget-bytes` + `input_path`/`bytes`/`oversize` + 自动收紧页宽。
- **代码(init 提示词)**:`init-induct.md`/`init-scout.md`/`init-rulewriter.md` 输入改「读 `input_path`」;
  `init-synthesis`/`init-scout-merge`/`init-rules-consistency` 增聚合 `bytes` 披露护栏。
- **代码(命令壳,双端)**:`mgh-init.md`(claude+opencode)纪律段 + flow + flag 表 + disclose。
- **代码(hook/契约,四命令共用)**:`block_adhoc_scripts.{py,ts}` recipe(一次覆盖四运行域,后续 adoption 复用);
  `tools/check_contracts.py` 扩 init flag。
- **契约**:`core/contracts/init/unit-inputs.md`(新,per-unit 物化契约,四命令路径约定);`request-context-budget`
  spec 含命令映射表。
- **测试**:init `list_*` 物化/分页/`bytes`/`oversize`/切分单测 + 纪律回归(整份读多单元聚合应被 hook 拦)。
- **研发铁律对齐**:R2(零依赖);R5.2(物化器是叶脚本);R5.3a/b(自定位/分页/退出码/幂等);R5.5(recipe + `NEVER`);
  R5.8(版本 bump + 回归);R5.9(物化 `--check`);R5.10(命令壳新增内容为操作性)。
- **诚实边界**:init per-unit 扇出 + 编排器请求**确定性有界**;init 聚合 stage P0 为软边界、P1 升硬阈值;不声称零
  上下文增长,只保证**单次请求 ≤ 配置阈值**(超阈值确定性切分/分层,NEVER 静默)。sast/sra/srr 未实现(后续 change)。
