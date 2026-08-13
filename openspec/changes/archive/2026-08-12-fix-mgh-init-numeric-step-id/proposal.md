# Proposal: fix-mgh-init-numeric-step-id

## Why

`/mgh-init` 编排器在 fresh run / resume 时按壳文本的 `step 0` 调用
`list_steps.py --step 0`,命中 closed-set misuse(exit 2,
`unknown step id: '0'`),流水线无法前进。根因:per-step fragment 化后,运行时
step id 已改为**命名枚举**(`not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`),
但壳/碎片散文仍残留 split 前的**数字 step 编号**(`step 0–8` / `step 0` / `(2)…(8)`),
`bootstrap.md` 又是 fresh-run 循环的盲区(壳说「壳自持」、壳却不含正文),模型拿
「step 0」撞 `--step 0`。`list_steps --step` 的报错不可操作,撞错后无法自纠。

## What Changes

- **壳去数字 step**(claude + opencode 双壳对等):`(step 0–8)`/`(step 0)`/`(2)…(8)` 叙述
  改为**命名 step id 序列**;stage-flow recipe 显式「`list_steps --step <id>` 只吃命名 id
  (来自 `resume_state.py` stdout `step`),NEVER 数字索引」;「step 0 首调 list_steps.py」等
  措辞改为「首次 list_steps 调用(discover 步)」。
- **闭合 fresh-run bootstrap 盲区**:壳给首 run 固定路径 recipe —— `Read
  <mgh-core>/prompts/fragments/init-stage/bootstrap.md`(resume_state 在 run_config
  前 exit 1、`stage_flow_files` 对 not-started 返回 `[]`,故 bootstrap 由壳 fixed-path
  加载,不走 resume_state 循环)。
- **`list_steps.py --step` 数字 id 可操作报错**(R5.3b):非闭集命中且参数全数字时,
  stderr 附 hint(step ids 是命名枚举、读 `resume_state.py` stdout `step` / 无 `--step`
  列全表、数字索引不接受);退出码保持 2(closed-set 拒歧义)。真实失败形状从此机械化可断言。
- **`bootstrap.md`/`done.md` 去「step 0/8」标签** + 声明可达性;`resume_state.py` docstring
  注释同步(bootstrap 由壳 fixed-path 加载,非「壳自持」歧义)。
- **契约与测试**:`core/contracts/init/step-manifest.md` 补命名闭集 + bootstrap 可达性注;
  `tests/test_list_steps.py` 加 `--step 0` → exit 2 + hint 断言。
- **R5.8**:VERSION bump;现有回归全绿。

## Capabilities

### New Capabilities

无新能力;这是对既有 stage-flow 加载契约的漂移修正。

### Modified Capabilities

- `orchestration-substrate`:该 spec 的 stage-flow 散文仍以数字 `step 0–8` 标注流程节点
  (且以「bootstrap 壳自持」描述首步加载),与本变更的目标直接冲突。delta 改变其要求:
  (a) 两壳 stage-flow recipe SHALL 只使用命名 step id 且显式禁止数字索引传给 `list_steps --step`;
  (b) fresh-run bootstrap SHALL 经壳 fixed-path Read `init-stage/bootstrap.md` 加载(非 resume_state
  循环),`not-started → stage_flow_files=[]` 要求不变;
  (c) 新增 `list_steps.py --step` 数字 id 可操作报错要求。
- `resume-step-discipline`:已核其散文用命名 `<step>`,无数字引用 → **无需 delta**。

## Impact

- `releases/claude-code/commands/mgh-init.md` + `releases/opencode/command/mgh-init.md`(双壳对等改)。
- `core/scripts/list_steps.py`(可操作报错;退出码/闭集不变)。
- `core/prompts/fragments/init-stage/{bootstrap,done}.md`(标签去数字 + 可达性注)。
- `core/scripts/resume_state.py`(docstring 注释同步;行为零变化)。
- `core/contracts/init/step-manifest.md`、`openspec/specs/orchestration-substrate/spec.md`。
- `tests/test_list_steps.py`(新增断言)、`tests/test_resume_state.py`(注释同步)。
- **范围外**:mgh-ut-init 有同一潜在模式(`list_ut_steps.py --step 0` 会被其壳 line 172
  「step 0 首调」诱发),但属另一命令 → follow-up,不在本变更(保持 apply 上下文有界)。
  mgh-sra/srr 壳的「step 0」指哨兵写时序、不接 `list_steps --step`,无此失败形状。
