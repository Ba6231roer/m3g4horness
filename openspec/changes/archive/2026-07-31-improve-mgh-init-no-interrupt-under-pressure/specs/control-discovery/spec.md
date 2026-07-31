## ADDED Requirements

### Requirement: Fan-out waves run to completion without scale-driven user interruption

`/mgh-init` 的编排器(宿主 agent)SHALL 把每个 fan-out 波次跑到完成,且 MUST NOT 因规模大而中途停下征求用户拆分 / 跳过 / 终止。具体到 scout reader batches / T1 per-cluster induction / T3 per-category rule writing 任一波次:编排器迭代 `list_*` 的 `pending` 工作清单、以 `max_concurrent` 并发起 subagent、跑完一波起下一波,直至无 pending 单元剩余;规模大(数百至 ~1000 单元)本身 NEVER 构成停下征求的理由。规模与边界事实 SHALL 流入既有披露渠道——`init_manifest.json::boundaries[]`、`report.md`、`resume_state.py` `notes[]`——NEVER 作为运行中的阻塞式提问;披露所用计数 SHALL 自磁盘读取(`resume_state.py` / `list_*` stdout),NEVER 据对话记忆编造。

本要求**不改动**既有 **pre-run** 建议:i0 阶段统计源文件数命中 `--large-repo-threshold` 时、
**在花 token 之前**主动建议 `--scope` 分模块 + `--merge` 的行为(承「Bounded single-pass scan
performance on large repos」)保持不变。本要求的禁止范围仅限**运行已提交之后**(波次进行中)的
打断行为。

该指令 SHALL 以规范性措辞(RFC-2119 `MUST NOT`/`SHALL`)写入 claude-code 与 opencode 两份
`mgh-init.md`(逐字镜像),落在 fan-out / Re-entrancy & compaction 区。这是编排器对话行为约束
(非工具调用约束),runtime hook 管不到「agent 是否停下来问用户」;确定性可测部分 = 披露侧
(规模/边界进 `init_manifest.json`/`report.md`/`resume_state.py`,计数来自磁盘)。

#### Scenario: A large fan-out wave runs to completion without a blocking question

- **WHEN** 编排器进入一个 fan-out 波次,且该波次 `pending` 单元数很大(如 ~1000 个 scout batch),
  用户期望全面、稳定执行到底
- **THEN** 编排器迭代 `list_*` stdout `pending[]`、以 `max_concurrent` 并行跑完所有单元,**不**
  中途停下征求用户「是否拆分 / 跳过 / 终止」;波次跑到 `pending` 为空

#### Scenario: Scale and boundaries are disclosed, not asked

- **WHEN** 一个 fan-out 波次规模大或覆盖部分(含 `.failed`/跳过单元 / 残留盲区)
- **THEN** 规模与边界事实出现在 `init_manifest.json::boundaries[]` 和/或 `report.md` 和/或
  `resume_state.py` `notes[]`(计数自磁盘 `resume_state.py`/`list_*` stdout),且编排器**不**就
  规模提出运行中的阻塞式提问

#### Scenario: The pre-run scope advisory is preserved

- **WHEN** i0 阶段统计的源文件数超过 `--large-repo-threshold`,且尚未花 token 进入全量扫描
- **THEN** 系统在开始全量扫描前建议 `--scope` 分模块 + `--merge`(行为等价于本要求引入前);
  该 pre-token 建议不受「运行中不打断」指令影响

#### Scenario: Both shells declare the run-to-completion directive

- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md` 的 fan-out / Re-entrancy & compaction 区
- **THEN** 两壳均含一条规范性措辞,声明编排器 MUST NOT 因规模在波次进行中停下征求拆分/跳过/终止、
  SHALL 把规模与边界流入既有披露渠道(双壳逐字镜像)

#### Scenario: Disclosed counts come from disk, not conversation memory

- **WHEN** 编排器在摘要/披露中陈述 fan-out 规模、失败数、跳过数或覆盖率
- **THEN** 这些计数取自 `resume_state.py` / `list_*` stdout 的结构化字段(磁盘真相),NEVER 据对话
  记忆编造
