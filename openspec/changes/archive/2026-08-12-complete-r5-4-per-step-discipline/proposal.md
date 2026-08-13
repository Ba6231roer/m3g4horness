# Proposal — complete-r5-4-per-step-discipline

## Why

R5.4 的 disk-truth 让压缩**可存活**(进度 `step`/`tiers`/`next_action` 从磁盘重派生),但盘上**没有**
「当前步的执行纪律 HOW」——三条 NEVER、fan-out 刚性三元组、`.failed` ack 配方、绝对路径逐字透传、
T1→T2 shape-gate、scout-incomplete-gate 全不在盘上。压缩 head 摘要只保留「做了什么」、不保留「规则是什么」
(`core/compaction.ts:18-40`),于是压缩后 same-session 编排器**知道在哪步、不知道该步怎么执行** → 跑偏。
这正是 `2026-08-10-fix-mgh-init-t1-record-schema-drift` 类 bug 的温床:T1→T2 gate 被压缩摘要丢掉 → 编排器
忘了跑 → schema 漂移静默进 T2。

归档 drift-fix spec 审计(2026-08-12,`docs/mgh-init-budget-analysis.md` §A.1)确认:**压缩不是跑偏主因**
(14 个 drift spec 里仅 2 个压缩相关、且均为多层根因中的一层);真实机制是「执行纪律 HOW 不在盘上 →
压缩后 same-session 仍可能跑偏」(§A.2)。`resume_state.py` stdout 实为 7 字段(§A.2 已核
`resume_state.py:33-41`):`{target, format, step, resumable, tiers, next_action, notes}`——**含进度、不含纪律配方**。
`list_steps.py --step` 输出 `{step, kind, script, script_abs, invocation, input, output}`(§B.1 已核)——**缺纪律子集**。

按 `docs/mgh-init-budget-analysis.md` §A.5 排序,补全 R5.4 = **准确度目标下的头号杠杆**(唯一治「压缩后
same-session 丢执行纪律」真 gap;确定性、model-independent、覆盖全部 stage、抗任意压缩强度),状态 = 待 propose
(最高优先)。

## What Changes

- **`core/scripts/resume_state.py` stdout 增 `discipline_reminders[]`**:值 = **当前 step** 的纪律子集
  (该步 gate 闸门形状 + 路径配方 + 适用 NEVER 反例)。disk-backed 衍生量、**非持久态**(磁盘真相源不变:
  `.mgh-init/` 产物 + `.done`/`.failed`)。当前 7 字段 stdout 为基座,增量字段。
- **`core/scripts/list_steps.py --step <id>` 增同 step 纪律子集**(与 resume_state 同一枚举 key,单一真相)。
- **双壳 resume 恢复路径更新**(`releases/claude-code/commands/mgh-init.md` + `releases/opencode/command/mgh-init.md`
  的 Resume/compaction 段):`--resume`/压缩后**第一步**调 `resume_state.py`,从 stdout 读 `step` + `discipline_reminders[]`,
  按该步纪律执行(再 `list_steps --step` 拿调用行)——NEVER 靠对话记忆判步骤、NEVER 跳过 gate。
- **纪律内容单一真相**:per-step 纪律表定义一次(脚本内静态表),与既有 `init-stage-flow.md` / 各 stage
  prompt 的纪律措辞对齐;未来与 `split-mgh-init-stage-flow-per-step` 合并时,`discipline_reminders[]`
  直接改从按步 fragment 的纪律段派生(§B.5 合并路径)。

## Capabilities

### New Capabilities

- `resume-step-discipline`:压缩后 same-session 从磁盘恢复「在哪步 + 怎么执行」的确定性机制——
  `resume_state.py` / `list_steps.py --step` 携带 per-step `discipline_reminders[]`(gate 闸门形状 +
  路径配方 + 适用 NEVER),双壳 resume/compaction 恢复路径消费之。

### Modified Capabilities

<!-- 无:本变更新增 resume 时纪律恢复这一独立 concern;orchestration-substrate 既有 requirement
(碎片引用 / token 预算 / --run-root)行为不变。 -->

## Impact

- `core/scripts/resume_state.py`(stdout 增字段;`--check` 不涉及)
- `core/scripts/list_steps.py`(`--step` 输出增纪律子集)
- `releases/claude-code/commands/mgh-init.md` + `releases/opencode/command/mgh-init.md`(Resume/compaction 段)
- `tests/`:`test_resume_state.py` / `test_list_steps.py`(或 `test_deterministic.py`)扩断言;`tools/check_contracts.py`
  (R5.1 契约 lint 覆盖新 stdout 字段不涉 flag,若增 flag 才需扩)
- `docs/mgh-init-budget-analysis.md` §A.3 落地;R5.4(AGENTS.md)不新增条文(机制已在 R5.4 语义内)
- 无新增依赖;纯标准库(R2);无分发纯净性风险(stdout 字段是操作性语义)
