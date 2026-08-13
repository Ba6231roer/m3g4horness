# Design: fix-mgh-init-numeric-step-id

## Context

`split-mgh-init-stage-flow-per-step` 把单文件 `init-stage-flow.md`(数字 step 0–8)拆成
per-step 命名 fragment(`init-stage/{bootstrap,discover,…,done}.md`),并把运行时 step id
固化为命名枚举(`not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`),
`list_steps.py`/`resume_state.py` 同 key 零重映射。但**编排器可读文本**(双壳 + bootstrap/done
fragment)仍残留数字 step 散文:`releases/{opencode,claude-code}/*/mgh-init.md` 的
「(step 0–8)」「(step 0)」「(2)…(8)」「step 0 首调 list_steps.py」「--resume 走同一命令壳 step 0」,
`bootstrap.md` 头「bootstrap (step 0)」、`done.md` 头「done (step 8)」。

`docs/mgh-init-budget-analysis.md §B.3.1` 已自我澄清「0–8 编号只是文档结构,不是运行时枚举」,
但壳散文没做等价消歧。**真实失败形状**(真机复现,`list_steps.py:247-251`):

- 编排器(弱模型)读壳 stage-flow recipe(壳 line 45「当前步执行前 … `list_steps.py --step <step>`」),
  对 fresh-run bootstrap 步,壳说「bootstrap(step 0)由本壳自持」——但壳**不含** bootstrap 正文
  (run_config/哨兵/MGH_TARGET/codegraph 在不可达的 `bootstrap.md`,resume_state 对 not-started
  返回 `stage_flow_files=[]`、run_config 前 exit 1),模型无「bootstrap 该怎么跑」的确切来源,
  遂拿壳文本的「step 0」执行 `list_steps.py --step 0`。
- `list_steps --step 0` → closed-set misuse,`error: unknown step id: '0'`(exit 2),流水线卡死。
  报错只列 known id,不说明「id 是命名枚举」→ 模型无法自纠(R5.3b「可操作报错」缺口)。

## Goals / Non-Goals

**Goals:**
- `list_steps.py --step` 永不收到数字索引(`--step 0` 从此机械化可断言为 misuse + 可操作 hint)。
- fresh-run bootstrap 步有确定可达的指令来源(壳 fixed-path Read `init-stage/bootstrap.md`)。
- 双壳、fragment、契约、测试的 step 散文统一为命名 id,零「step 0–8」残留(编排器可读面)。
- 行为零变化:退出码、闭集、`stage_flow_files`(not-started → `[]`)不变。

**Non-Goals:**
- 不改 `list_steps.py` 闭集语义(数字 id **不**变成合法别名——R5.3b「闭集参数拒歧义输入」,承错误调用方而非放宽被调方)。
- 不动 `resume_state.py` 行为(`not-started → stage_flow_files=[]` 保持,spec 既有要求不变)。
- **不扩到 mgh-ut-init**(同模式但另一命令 → follow-up)。
- 不重写 sra/srr/sast 壳(其「step 0」指哨兵写时序,不接 `list_steps --step`,无此失败形状)。
- 不改 dev 面向的契约散文(runtime-enforcement.md 等)的「step 0」措辞——非编排器失败向量,只在顺手处消歧。

## Decisions

### D1. 双壳去数字 step + 显式命名闭集(claude/opencode 逐字对等)

- 壳 line 49「完整 stage 流…(step 0–8)…(step 0)→ discover(2)→ … (8)」→ 命名序列:
  `not-started`(bootstrap)→ `discover` → `survey`(opt)→ `scout` → `resolve`(opt)→ `t1`
  → T1→T2 闸门 → `t2` → `t3` → `assemble` → `t4` → `merge`(--merge 模式)→ `done`。
  顺带消掉 claude「ASSEMBLE/LINT」vs opencode「BUILD INDEX+LINT」措辞 drift(统一「BUILD INDEX+LINT」)。
- 壳 line 45「stage 流按需加载」recipe 补两硬句:
  - 「`--step <id>` 只吃 resume_state stdout `step` 的**命名 id**;NEVER 数字索引」。
  - fresh-run(首 run,`<target>/.mgh-init/` 不存在 / resume_state exit 1):「**不走该循环**;
    改 Read `<mgh-core>/prompts/fragments/init-stage/bootstrap.md`(固定路径)按之执行
    bootstrap(run_config 原子写/哨兵/MGH_TARGET/codegraph),然后 resume_state → `discover`
    进统一循环;NEVER 对 bootstrap 调 `list_steps --step <数字>`」。
- 壳 line 63「--resume 走同一命令壳 step 0」→「…bootstrap(not-started)步」。
- 壳 line 64「step 0 首调 list_steps.py 用相对路径」→「**首次** `list_steps.py` 调用
  (discover 步)用相对路径」——launch-cwd 前置只约束第一次 list_steps 调用,与 bootstrap 无关。
- 壳 line 61 resume recipe 补「`--step <id>` 取命名 id;NEVER 数字索引」。
- 替代方案(否决):在壳内**内联** bootstrap 正文(R5.6 薄壳、正文下沉 fragment,否决);
  让 `list_steps --step` **接受数字别名**(closed-set 拒歧义被破坏、掩盖调用方 bug,否决)。

### D2. 闭合 fresh-run bootstrap 盲区(fixed-path,非 resume_state)

`bootstrap.md` 由壳 fresh-run recipe **固定路径 Read**(`.opencode/mgh-core` /
`.claude/mgh-core` 前缀 + `prompts/fragments/init-stage/bootstrap.md`)加载。理由:
- resume_state 对 not-started 返回 `stage_flow_files=[]`(spec 既有要求「not-started 与 done 返回空数组」),
  且 run_config 前 exit 1 → 它**结构性不可能**是 bootstrap 的来源;fresh-run 唯一加载面是壳。
- 保持 spec「not-started → `[]`」不变,resume_state 零行为改动(比改 `_stage_flow_files`
  返回 bootstrap 路径更诚实——后者在运行时永不触发、纯死码)。
- 替代方案(否决):resume_state `not-started` 返回 `[bootstrap.md]`(运行时永不 emit,死码 +
  改 spec 既有要求 + 改测试,ROI 为负)。

### D3. `list_steps.py --step` 数字 id 可操作报错(leaf 硬化)

`list_steps.py:247-251` 非闭集命中时:若 `args.step` 全数字(`.isdigit()`),stderr 在
known 列表后附 hint:
`step ids are NAMED enums (from resume_state.py stdout step, or run list_steps.py without --step to list all); numeric indices are NOT accepted`。
退出码保持 2。`--help` 的 `--step` 描述补「named ids only;NOT numeric indices」。
效果:真实失败形状从「静默死卡」变「exit 2 + 自纠指引」,且可被 `tests/test_list_steps.py`
机械化断言(`--step 0` → exit 2 + stderr 含 hint + known 列表)。

### D4. fragment/注释标签消歧(低风险)

- `bootstrap.md` 头「bootstrap (step 0)」→「bootstrap(not-started 首 run)」;「step 0 即就绪」
  →「首 run 即就绪」;补一行可达性注(本 fragment 由壳 fresh-run recipe fixed-path Read,
  不走 resume_state 循环)。
- `done.md` 头「done (step 8)」→「done」。
- `resume_state.py` docstring(行 51-52/212-213)「bootstrap shell self-hosts step 0」→
  「bootstrap 由壳 fresh-run recipe fixed-path Read `init-stage/bootstrap.md` 加载」。

### D5. 契约 + 测试

- `core/contracts/init/step-manifest.md` CLI 节补:`--step <id>` 只接受命名枚举 id(与
  resume_state 枚举一致);数字索引 → exit 2(closed-set);补 bootstrap 可达性注。
- `tests/test_list_steps.py` 新增 `test_step_numeric_exit_2_with_hint`。
- `tests/test_resume_state.py`:`test_not_started_empty_direct` 保持(设计不变),docstring 注释同步。
- R5.8:VERSION bump;`tests/test_mgh_init_codegraph_parity.py` 等回归全绿。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 壳字数增长(加 recipe 句) | 净增 ~100–150 tok,远低于 R5.6 5,000 上限(实测 claude 3,048/opencode 2,986);lint 见回归 |
| 命名序列丢失 3b/4b/6b 等子步信息 | 保留为命名步**行内注解**(scout fan-out / T1→T2 闸门 / BUILD INDEX+LINT 仍在对应命名步后),零信息丢失 |
| 弱模型仍传数字 id | D3 可操作报错 = 自纠兜底 + 测试锁定 |
| 双壳对等 drift | 同一次 edit 同步两文件,spec 两壳零 drift 场景 + 现有对等回归 |
| mgh-ut-init 同模式未修 | 显式记 follow-up(另变更),不在本变更 apply 面内 |

## Migration Plan

- 纯文档/注释/测试改动 + 单脚本报错分支;无数据迁移、无 schema 变更、无回滚需求。
- 交付后跑 `py tests/test_list_steps.py` + `py tests/test_resume_state.py` + `py tools/check_contracts.py`
  + `py tools/measure_prompts.py releases/*/…/mgh-init.md`(壳 ≤ 5,000 确认)。
- 真机验收:对安装副本跑 `py <target>/.mgh-init/…/list_steps.py --step 0` → exit 2 + hint;
  fresh run `/mgh-init` → bootstrap 经 fixed-path Read 正常推进(不再卡 `--step 0`)。

## Open Questions

- 无阻塞项。ut-init follow-up 单独提变更。
