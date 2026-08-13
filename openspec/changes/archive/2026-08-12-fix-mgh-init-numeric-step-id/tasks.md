# Tasks: fix-mgh-init-numeric-step-id

## 1. leaf 硬化:`list_steps.py` 数字 id 可操作报错

- [x] 1.1 `core/scripts/list_steps.py`:`--step <id>` 非闭集命中且 `id` 全数字(`.isdigit()`)时,stderr 在
  `unknown step id` + `known:` 列表后附 hint(step id 为命名枚举,读 `resume_state.py` stdout `step` /
  不带 `--step` 列全表;「numeric indices are NOT accepted」);退出码保持 2(闭集拒歧义不变)。
- [x] 1.2 `core/scripts/list_steps.py` `--help` 的 `--step` 描述补「named ids only;NOT numeric indices」。
- [x] 1.3 `tests/test_list_steps.py` 新增 `test_step_numeric_exit_2_with_hint`:`--step 0` → exit 2 +
  stderr 含 `unknown step id` + `known:` + hint;stdout 无部分 manifest(不混入)。

## 2. 双壳去数字 step(命名 id;claude/opencode 逐字对等)

- [x] 2.1 两壳「完整 stage 流」段(壳 line 49)`(step 0–8)`/`(step 0)`/`(2)…(8)` → 命名序列:
  `not-started`(bootstrap)→ `discover` → `survey`(opt)→ `scout` → `resolve`(opt)→ `t1` →
  T1→T2 闸门 → `t2` → `t3` → `assemble`(BUILD INDEX+LINT)→ `t4` → `merge`(--merge 模式)→ `done`;
  统一 claude「ASSEMBLE/LINT」/opencode「BUILD INDEX+LINT」措辞。
- [x] 2.2 两壳「stage 流按需加载」recipe(壳 line 45)补两硬句:`--step <id>` 只吃 resume_state stdout
  `step` 的**命名 id**,NEVER 数字索引;fresh-run(首 run,`.mgh-init/` 不存在 / resume_state exit 1)
  改 Read `<mgh-core>/prompts/fragments/init-stage/bootstrap.md`(固定路径)按之执行 bootstrap,再
  resume_state → `discover` 进统一循环,NEVER 对 bootstrap 调 `list_steps --step <数字>`。
- [x] 2.3 两壳 Resume recipe(壳 line 61)补「`--step <id>` 取命名 id;NEVER 数字索引」。
- [x] 2.4 两壳「--resume 走同一命令壳 step 0」(壳 line 63)→「…bootstrap(not-started)步」。
- [x] 2.5 两壳「step 0 首调 list_steps.py」(壳 line 64)→「**首次** `list_steps.py` 调用(discover 步)」。
- [x] 2.6 核对两壳 2.1–2.5 逐字对等(除 `.claude/`/`.opencode/` 前缀差异外零 drift)。

## 3. fragment/注释消歧

- [x] 3.1 `core/prompts/fragments/init-stage/bootstrap.md` 头「bootstrap (step 0)」→「bootstrap
  (not-started 首 run)」;「opencode step 0 即就绪」→「首 run 即就绪」;补一行可达性注(本 fragment 由壳
  fresh-run recipe fixed-path Read 加载,不走 resume_state 循环)。
- [x] 3.2 `core/prompts/fragments/init-stage/done.md` 头「done (step 8)」→「done」。
- [x] 3.3 `core/scripts/resume_state.py` docstring(行 51-52/212-213)「bootstrap shell self-hosts step 0」
  →「bootstrap 由壳 fresh-run recipe fixed-path Read `init-stage/bootstrap.md` 加载」;行为零变化。

## 4. 契约

- [x] 4.1 `core/contracts/init/step-manifest.md` CLI 节补:`--step <id>` 只接受命名枚举 id(与 resume_state
  枚举一致),数字索引 → exit 2(闭集);补 bootstrap 可达性注(not-started 由壳 fixed-path Read 加载)。

## 5. 回归 + 版本 + 验收

- [x] 5.1 `VERSION` bump(任一 .md/脚本改动)。
- [x] 5.2 回归全绿:`py tests/test_list_steps.py`、`py tests/test_resume_state.py`、
  `py tests/test_mgh_init_codegraph_parity.py`、`py tools/check_contracts.py`、
  `py tools/check_distributed_purity.py`、`py tools/measure_prompts.py releases/claude-code/commands/mgh-init.md releases/opencode/command/mgh-init.md`(两壳 `mid_tokens` 各 ≤ 5,000)。
- [x] 5.3 真机验收:安装副本 `py <target>/<host>/mgh-core/scripts/list_steps.py --step 0` → exit 2 + hint;
  fresh run `/mgh-init` 经 bootstrap fixed-path Read 正常推进(不再卡 `--step 0`)。
- [x] 5.4 摘要披露:LLM 诱发候选 / 存在≠有效 / call-graph 文本 AST 边界照旧;本变更不改 mgh-init 产物 schema。
