## Context

R5.4(AGENTS.md:145-160)让压缩**可存活**——进度(`step`/`tiers`/`next_action`)从磁盘重派生。但盘上**没有**
「当前步的执行纪律 HOW」:三条 NEVER、fan-out 刚性三元组、`.failed` ack 配方、绝对路径逐字透传、
T1→T2 shape-gate、scout-incomplete-gate 全在 prompt fragment 里,压缩 head 摘要(`core/compaction.ts:18-40`)
只保留「做了什么」不保留「规则是什么」。压缩后 same-session 编排器**知道在哪步、不知道该步怎么执行** →
跑偏(`2026-08-10-fix-mgh-init-t1-record-schema-drift` 类 bug 温床)。

`docs/mgh-init-budget-analysis.md` §A.2/§A.3 结论:真 gap = 「执行纪律 HOW 不在盘上」;头号准确度杠杆 =
option A(**补全 R5.4**):`resume_state.py` / `list_steps --step` 带 per-step `discipline_reminders[]`。
§A.5 排序 #1,状态「待 propose(最高优先)」。§B.5:与预算层 change(`split-mgh-init-stage-flow-per-step`)
**正交、可并行、可后合并**——本设计只做准确度层。

利益相关方:① 维护者(要防压缩后跑偏治本);② mgh-init 既有使用者(零感知,stdout 增字段不破坏消费方);
③ 未来合并路径(§B.5:静态表 → fragment 派生单一真相)。

## Goals / Non-Goals

**Goals:**
- `resume_state.py` stdout 增 `discipline_reminders[]`(当前步纪律子集),disk-backed 衍生量。
- `list_steps.py --step` 增同 step 纪律子集,与 resume_state 逐字一致(单一真相)。
- 双壳 resume/compaction 恢复路径消费 `discipline_reminders[]`(先读纪律再执行)。
- 纪律表覆盖全部承重防御(scout-incomplete-gate / T1→T2 shape-gate / fan-out 路径 / `.failed` ack / NEVER)。
- 既有回归测 + 契约 lint + 分发纯净 lint 全绿;纯标准库(R2)。

**Non-Goals:**
- **不**改 mgh-init 流水线可观测行为(产物/退出码/路径/fan-out 边界/`--check` 行为逐字不变)。
- **不**拆 fragment、**不**改 `init-stage-flow.md` 结构(那是 `split-mgh-init-stage-flow-per-step` 的事)。
- **不**扩 `--check`(R5.9)到纪律字段(纪律是 resume 衍生量,非磁盘状态)。
- **不**新增 pip 依赖、不新增 CLI flag(`discipline_reminders[]` 是 stdout 字段,非 flag;R5.1 契约面不动)。

## Decisions

### D1 — 纪律表单一真相 = 新共享模块 `core/scripts/discipline_core.py`

- **选择**:per-step 纪律表定义在**一个**共享模块 `discipline_core.py`(`_DISCIPLINE: dict[step, dict]`),
  `resume_state.py` 与 `list_steps.py` 均 `from discipline_core import ...`;两脚本只做「当前 step 查表」。
- **理由**:① 两脚本需同一纪律(§B.5「单一真相」),嵌入任一方则另一方要 import 对方脚本(耦合
  resume_state↔list_steps);独立模块 = 纯数据 + 零副作用,两方只消费;② 未来合并(§B.5)把表内容
  改成「从 `init-stage/<step>.md` 纪律段派生」时,只改 `discipline_core` 一处,两消费方零改动——
  这是合并路径的结构性准备;③ sibling-import 有先例(`merge_scout → discover_controls`,
  `resume_state` 已 `sys.path.insert` 自定位,R5.3a),零依赖 AST 扫描放行 sibling(`tests/test_zero_deps.py`)。
- **备选(否决)**:
  - 表嵌入 `list_steps.py`,`resume_state` import list_steps——否决:两脚本职责耦合,list_steps 的
    step-manifest 契约(承 `2026-08-01-improve-mgh-init-deterministic-step-manifest`)会被纪律改动扰动。
  - 表复制两份(各自内联)——否决:制造第二真相源,drift 温床,正是本变更要消除的问题。

### D2 — `discipline_reminders[]` 结构化 shape(gate/path_recipe/never 三组)

- **选择**:stdout 字段为**结构化对象**而非字符串数组:
  ```
  "discipline_reminders": {
    "gates": [{"id":"t1-shape-gate","desc":"T1→T2 边界形状校验","command":"validate_t1_records --strip-bom + --check","fail_exit":2}],
    "path_recipes": [{"id":"t1-fanout-path","desc":"T1 单元输出路径 = list_clusters stdout pending[].checkpoint_path,绝对逐字透传","source":"list_clusters --step 契约"}],
    "nevers": ["NEVER 整份 Read clusters.json","NEVER 拼 <target>/<cluster>"]
  }
  ```
- **理由**:§A.3 明确纪律三要素(gate 闸门形状 + 路径配方 + 适用 NEVER);结构化组让消费方(编排器/弱模型)
  按类别读取,也让未来 fragment 派生(`discipline_core` 解析 fragment 纪律段)有稳定映射点。单对象 JSON
  保持 R5.3b stdout 契约。
- **备选(否决)**:扁平字符串数组——否决:无法表达「这是 gate、那是路径配方」,弱模型逐条硬读,
  未来 fragment 派生无结构锚点。

### D3 — 纪律内容与既有 fragment/stage prompt 措辞对齐(防漂移)

- **选择**:`_DISCIPLINE` 表内容**镜像** `init-stage-flow.md` 各步承重反例的措辞(实现时逐条对表,
  参考 `init-stage-flow.md:93` scout 闸门、`:97-101` T1→T2 gate、`:88-96` fan-out 路径)。
- **理由**:纪律表是「resume 时的精简提醒」,fragment 是「完整参考」;两者措辞漂移会让压缩后恢复的
  编排器按表执行却与 fragment 冲突。对表保证一致。
- **备选(否决)**:表只给指针(「纪律见 init-stage-flow step N」)——否决:压缩后 fragment 可能已不被加载,
  指针是死链;表必须**自含**纪律内容。

### D4 — 双壳 resume recipe 措辞(承 R5.5①:recipe 优先,硬边界用 NEVER)

- **选择**:两壳 Resume/cache 段改为:「`--resume`/压缩后第一步 = `py resume_state.py --target <target>` →
  读 stdout `step` + `discipline_reminders[]`,**先按该步纪律执行**(gate `--check` 闸门 / 路径配方 /
  适用 NEVER),再 `list_steps.py --step <step>` 取调用行」。措辞用「该做什么」recipe,
  仅在真正的硬边界用 `NEVER`(不靠对话记忆判步骤、不跳过 gate)。
- **理由**:压缩后第一步读盘 = 同时恢复「在哪步 + 怎么执行」,与 §A.3 目标一致;recipe 措辞是
  R5.5① 正引导(shaping 用 recipe,防 prohibition 负引导)。

### D5 — 回归测 + 契约面防护

- **选择**:扩 `tests/test_resume_state.py`(或 `test_list_steps.py`):断言① `resume_state.py` 对处于某步的
  run 输出非空 `discipline_reminders[]` 且覆盖该步承重 gate;② `list_steps.py --step <id>` 的 `discipline`
  与 `resume_state.py` 同 step 的 `discipline_reminders[]` 逐字一致(单一真相);③ `done`/`not-started` 步
  输出空纪律;④ stdout 仍是单对象 JSON(R5.3b)、字段增量不破坏既有 7 字段。
- **理由**:纪律表是静态数据,最怕「表与 fragment 措辞漂移」与「两脚本查表不一致」;显式断言
  一致性 + 覆盖性把 drift 风险变结构兜底。

## Risks / Trade-offs

- **[纪律表与 fragment/stage prompt 措辞漂移]** → D3 对表 + D5 一致性测试(抽查 t1 纪律含
  `validate_t1_records`);未来合并(§B.5)后表改从 fragment 派生,漂移面归零。
- **[stdout 增字段破坏下游消费方]** → 字段是**增量**(既有 7 字段形状/语义不变);消费方(壳 recipe /
  测试 / 脚本)读旧字段不受影响;`--help`/flag 面不动(R5.1)。
- **[纪律内容过长增 stdout 体积]** → 每步纪律 ~数百 token,有界(固定表);stdout 单对象 JSON 契约不变;
  编排器只读当前步(非全表)。
- **[与 split-mgh-init-stage-flow-per-step 并行改 resume_state.py,合并且冲突]** → 两 change 各加不同字段
  (`discipline_reminders[]` vs `stage_flow_files[]`)、不互改同一字段;apply 顺序无关,git 合并不冲突;
  §B.5 已预判合并路径。
- **[新增 `discipline_core.py` 需过零依赖 AST 扫描与纯净 lint]** → 纯标准库 + 纯数据(无 argparse/无
  IO);不随分发纯净 lint 面(脚本非分发 md);`test_zero_deps.py` 放行 sibling import。

## Migration Plan

1. 建 `core/scripts/discipline_core.py`:`_DISCIPLINE` 静态表(step → `{gates, path_recipes, nevers}`,
   内容镜像 `init-stage-flow.md` 承重反例)+ `get_discipline(step) -> dict` 纯函数(未知 step → 空结构)。
2. `core/scripts/resume_state.py`:stdout 构建处(`resume_state.py:370-376`)增 `discipline_reminders` =
   `discipline_core.get_discipline(step)`(当前步;`done`/`not-started` → 空结构);docstring stdout 段更新。
3. `core/scripts/list_steps.py`:`_build_step`(`:196-204`)增 `discipline` = `discipline_core.get_discipline(step_id)`;
   docstring 更新;`--help` 不动(不增 flag)。
4. 双壳 `mgh-init.md`(claude + opencode)Resume/cache 段更新 recipe(消费 `discipline_reminders[]`)。
5. 扩测(`test_resume_state.py`/`test_list_steps.py`)D5 断言;跑全套回归 + 三项 lint;bump 版本号。
6. **回滚**:`discipline_reminders[]`/`discipline` 是 stdout 增量字段,无脚本/壳行为依赖回滚;
   git revert 单变更即可,产物 schema 无变化。

## Open Questions

- `discipline_reminders[]` 的 `nevers` 是否逐字复制 `orchestrator-discipline.md` 三条 NEVER(全集)
  还是只给该步适用的子集——倾向**子集**(该步适用),全集在 orchestrator-discipline fragment,避免重复。
- `discipline_core` 是否要暴露 `--check` 自验(纪律表 vs fragment 措辞对表)——倾向在回归测里做
  (确定性),不增脚本 CLI。
- 未来合并(§B.5)时 `discipline_core` 是保留静态表、还是改为运行时读 fragment——倾向保留静态表 +
  提供「从 fragment 重新生成表」的迁移工具(生成物进 CI 对账),避免运行时读 md 的脆弱性。
