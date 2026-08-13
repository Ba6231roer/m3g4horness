# Proposal — split-mgh-init-stage-flow-per-step

## Why

`core/prompts/fragments/init-stage-flow.md` 单文件 **4,769 mid / 130 行**,是 mgh-init 编排流的逐步细节载体
(step 0–8)。当前 resume/压缩后编排器**整份加载**它(4.8K)才能拿到当前步纪律;而 `list_steps.py --step` 已能
确定性给出当前步的**调用行 + I/O 契约**(§B.1 已核,零新代码),纪律正文分散在各步。

`docs/mgh-init-budget-analysis.md` §B 是维护者拍板的**预算层方案 2B**(2026-08-12):**`list_steps --step`(现成,
给调用行+I/O)+ 按步拆 fragment(给纪律)+ resume 只加载当前步**。收益 = **非同时驻留**——编排器只加载当前
step 的单个 fragment(实测平均 ~0.4K/步,重步 ~0.6–0.8K),而非整份 4.8K。prune 默认关(§1.2 纠错 2)下默认
用户的头号真省 token 杠杆 = 缩壳 + 拆 fragment(区迁移到工具输出区 + 非同时驻留),方案 2B 正是该形态。
`resume_state.py` stdout 增 `stage_flow_files[]`(当前步单文件绝对路径)使恢复路径**只加载当前步**。

本变更**只管预算层**(§A.6 拍板:prompt/预算层走 2B;**准确度头号杠杆另立 proposal**
`complete-r5-4-per-step-discipline`,两路径正交、可并行、后可合并——§B.5)。

## What Changes

- **拆 `core/prompts/fragments/init-stage-flow.md` → `fragments/init-stage/{bootstrap,discover,survey,scout,resolve,t1,t2,t3,assemble,t4,merge,done}.md`**
  (12 文件,平均 ~0.4K/步)。**只迁移、不删**(保真度优先,承报告「⚠ 裁剪前提」):scout-incomplete-gate /
  T1→T2 shape-gate(`validate_t1_records --strip-bom`+`--check`)/ 级联失效 / `.failed` ack / 绝对路径透传 /
  NTFS `::` sanitize / BOM 剥离等承重反例**必须**随对应 step 进 fragment,NEVER 丢。保留头部溯源注释(承 R1)。
- **`resume_state.py` stdout 增 `stage_flow_files[]`**:值 = **当前 step 的单个** `init-stage/<step>.md`
  绝对路径(`Path.resolve()`,非 step 0、非 all-remaining)。`Path.resolve()` 绝对、逐字透传给编排器(承
  R5.3(b) fan-out 路径契约)。当前 7 字段 stdout 基座见 `resume_state.py:33-41`,为**增量**字段。
- **双壳 SUB-SKILL 指令改**(`releases/claude-code/commands/mgh-init.md:41-49` + opencode 镜像同处):
  「Use init-stage-flow(整文件)」→ 「`resume_state` 拿当前步 → `list_steps --step` 拿调用行 → Read
  `stage_flow_files[]`(当前步 fragment)」。壳进一步瘦身(去掉整文件加载语义)。
- **step 枚举统一 key**(消歧):fragment 文件名 + `stage_flow_files[]` **统一 key 在**
  `resume_state.py`/`list_steps.py` 的 step 枚举(`not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`);
  init-stage-flow 的 0–8 编号只是文档结构,非运行时枚举(§B.3.1)。

## Capabilities

### New Capabilities

<!-- 无:本变更不是新能力,是把既有 init-stage-flow fragment 机制重构成 per-step 形态 + resume 增量字段。 -->

### Modified Capabilities

- `orchestration-substrate`:现有 Requirement「mgh-init stage 流细节抽 init-stage-flow fragment,行为零变化」
  (要求存在单一 `core/prompts/fragments/init-stage-flow.md`)与「壳经 REQUIRED SUB-SKILL 引用 fragment」
  的碎片形态改变 —— 单文件 → per-step fragment 集、resume 只加载当前步、`resume_state.py` stdout 增
  `stage_flow_files[]`。token 预算 lint(壳 ≤5,000 tok、碎片逐个评估、磁盘合计 ≤~10,000 防漂移)重派生。

## Impact

- `core/prompts/fragments/init-stage-flow.md`(删除)→ `core/prompts/fragments/init-stage/*.md`(12 个新文件)
- `core/scripts/resume_state.py`(stdout 增 `stage_flow_files[]`)
- `releases/claude-code/commands/mgh-init.md` + `releases/opencode/command/mgh-init.md`(SUB-SKILL 指令 + Resume 段)
- `install.sh`:53,78 `cp -r core/ → mgh-core/` 自动镜像新目录,无需改
- `tests/`:`test_resume_state.py` 扩 `stage_flow_files[]` 断言;`test_distributed_md_purity.py`(fragment 拆分后
  纯净性逐文件覆盖)
- `tools/measure_prompts.py`(重测量碎片尺寸);`docs/opencode-context-mechanics.md` / `docs/mgh-init-budget-analysis.md`
  引用的「init-stage-flow 4.8K」数字更新
- 无新增依赖;纯标准库(R2);fragment 是分发产物,经纯净性 lint
