# resume-step-discipline Specification

## Purpose

压缩后 same-session **从磁盘恢复「在哪步 + 怎么执行」**的确定性机制——补全 R5.4 disk-truth 的真实 gap
(盘上有进度、**无执行纪律 HOW**)。`resume_state.py` / `list_steps.py --step` 携带 per-step
`discipline_reminders[]`(当前步的 gate 闸门形状 + 路径配方 + 适用 NEVER 反例),双壳 resume/compaction
恢复路径消费之。使压缩 head 摘要丢失的纪律配方从**磁盘重派生**,抗任意压缩强度、model-independent。

## Requirements

### Requirement: resume_state.py stdout 携带当前步 discipline_reminders[]

`core/scripts/resume_state.py` 的 stdout(既有 7 字段基座 `{target, format, step, resumable, tiers,
next_action, notes}`)SHALL 增 `discipline_reminders[]` 字段——值 = **当前 step**(stdout `step` 值)的纪律子集,
为**增量字段**(不改变既有字段形状/语义;stdout 仍是单对象 JSON,R5.3b)。`discipline_reminders[]` 每项 SHALL
携带该步的:gate 闸门形状(`--check` 命令 + 退出码 2 fail-loud 语义)、路径配方(fan-out 单元输出路径 =
枚举脚本 stdout 的 `checkpoint_path`/`rule_path`,绝对、逐字透传)、适用 NEVER 反例(该步的硬边界,如
`NEVER 拼 <target>/<id>`、`NEVER py -c` 内省)。该字段是 **resume 衍生量、非持久态**:值纯从
`<target>/.mgh-init/` 产物 + `.done`/`.failed` + `run_config.json` 派生,不写入任何磁盘文件;
`--check`(R5.9)不涉及该字段。

#### Scenario: resume 输出携带当前步纪律子集

- **WHEN** 编排器对处于 t1 步的 run 调用 `resume_state.py --target <t>`
- **THEN** stdout 含 `step: "t1"` 且 `discipline_reminders[]` 非空,覆盖 t1 步的:fan-out 路径配方
  (T1 单元输出路径 = `list_clusters.py` stdout `pending[].checkpoint_path`,绝对、逐字透传)、
  T1→T2 shape-gate(`validate_t1_records --strip-bom`+`--check`,退出码 2 → 外科式重派)、适用 NEVER
  (`NEVER 整份 Read clusters.json`、`NEVER 拼 <target>/<cluster>`)

#### Scenario: discipline_reminders 是衍生量,不写盘

- **WHEN** 审阅 `.mgh-init/` 目录产物清单与 `resume_state.py` 写路径
- **THEN** `discipline_reminders[]` 未持久化到任何磁盘文件;两次 `--resume` 调用的值仍逐字一致
  (同一磁盘状态 → 同一纪律子集)

#### Scenario: 无纪律子集的 step 返回空数组而非缺字段

- **WHEN** 当前步是 `done`(流水线已收尾,无下一步纪律)
- **THEN** stdout 仍含 `discipline_reminders[]`,值为空数组 `[]`(字段恒存在,shape 稳定)

### Requirement: list_steps.py --step 携带同 step 纪律子集

`core/scripts/list_steps.py --step <id>`(现输出 `{step, kind, script_abs, invocation, input, output}`,
§B.1)SHALL 增 `discipline` 子集——与 `resume_state.py` 同一 step 枚举 key、同一纪律单一真相
(两脚本共享静态 per-step 纪律表,不允许各自实现)。`--step` 输出的 `discipline` 与
`resume_state.py` 当前步的 `discipline_reminders[]` SHALL 逐字一致(同一 step)。未知 id 仍退出码 2(闭集,
R5.3b 不变);不增 CLI flag(纪律是 stdout 字段,非 flag;R5.1 契约面不受扰动)。

#### Scenario: list_steps --step 与 resume_state 纪律逐字一致

- **WHEN** 对同一 run 分别调用 `list_steps.py --step t1` 与 `resume_state.py --target <t>`(当前步 t1)
- **THEN** `list_steps.py` stdout 的 `discipline` 与 `resume_state.py` stdout 的 `discipline_reminders[]`
  内容逐字一致(单一真相)

#### Scenario: --step 闭集语义不变

- **WHEN** 调用 `list_steps.py --step bogus`
- **THEN** 退出码 2(stderr recipe),stdout 不产 JSON(既有闭集行为不变)

### Requirement: 双壳 resume/compaction 恢复路径消费 discipline_reminders[]

`releases/claude-code/commands/mgh-init.md` 与 `releases/opencode/command/mgh-init.md` 的
Resume/cache 段 SHALL 更新:`--resume`/压缩后**第一步** SHALL 调 `resume_state.py --target <target>`,
从 stdout 读 `step` + `discipline_reminders[]`,**先按该步纪律执行**(gate/路径配方/NEVER),
再 `list_steps.py --step <step>` 取确切调用行。NEVER 靠对话记忆判步骤、NEVER 跳过 gate、NEVER 在
`discipline_reminders[]` 空时静默继续(空数组仅对 `done` 步合法)。该段措辞是**指令性 recipe**
(承 R5.5①:shaping 用 recipe,硬边界才用 NEVER)。

#### Scenario: 压缩后恢复路径从磁盘拿纪律

- **WHEN** 编排器经历压缩/compact 后 resume,当前步 t1,该步纪律曾被压缩摘要丢弃
- **THEN** 编排器首调 `resume_state.py` 读 `step: "t1"` + `discipline_reminders[]`(T1→T2 gate 配方 +
  fan-out 路径配方),按纪律跑 `validate_t1_records --check` + `list_steps --step t1` 取调用行
  再执行;不依赖任何压缩残留的对话记忆

#### Scenario: done 步后不再加载纪律

- **WHEN** 当前步 `done`(流水线已收尾),编排器 resume
- **THEN** `discipline_reminders[]` 为空,编排器进收尾/停止,不空转

### Requirement: 纪律内容单一真相 + 未来合并路径

per-step 纪律表 SHALL 定义**一次**(两脚本共享),内容与既有 `core/prompts/fragments/init-stage-flow.md`
各 step 的纪律措辞对齐(scout-incomplete-gate、T1→T2 shape-gate、fan-out 路径透传、`.failed` ack、
NEVER 反例——全部覆盖,不删减)。未来与 `split-mgh-init-stage-flow-per-step` 合并时(§B.5),
`discipline_reminders[]` SHALL 改从按步 fragment 的纪律段派生(单一真相),本变更的静态表成为
fragment 拆分前的过渡来源;合并前两 change 互不阻塞。

#### Scenario: 纪律表覆盖全部承重防御

- **WHEN** 审阅静态 per-step 纪律表
- **THEN** 它覆盖 scout-incomplete-gate(退出码 2)、T1→T2 shape-gate(`--strip-bom`+`--check`)、
  fan-out 输出路径 = 枚举脚本 `checkpoint_path`/`rule_path`(绝对逐字)、`.failed` 终态 ack、
  每步适用 NEVER 反例——任一承重防御不随压缩丢失

#### Scenario: 合并路径以 fragment 为单一真相

- **WHEN** `split-mgh-init-stage-flow-per-step` 落地后两 change 合并
- **THEN** 静态表被移除,`discipline_reminders[]` 从 `init-stage/<step>.md` 纪律段派生;
  两 change 各自独立 apply 阶段互不阻塞
