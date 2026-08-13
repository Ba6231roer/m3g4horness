# Tasks — complete-r5-4-per-step-discipline

> 实现顺序按依赖;每个任务可验证。**准确度目标**:压缩后 same-session 恢复执行纪律(防跑偏)。`discipline_reminders[]`
> / `discipline` 是 stdout **增量字段**(既有 7 字段形状/语义不变);不增 CLI flag(R5.1);纯 Python ≥3.10 标准库(R2);
> 流水线可观测行为逐字不变。任一 `.md`/脚本改动 bump 版本号。

## 1. discipline_core(静态 per-step 纪律表单一真相)

- [x] 1.1 建 `core/scripts/discipline_core.py`:`_DISCIPLINE: dict[step, {gates[], path_recipes[], nevers[]}]`
  (step key = `resume_state.py:46` 枚举 `not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`);
  内容**镜像** `core/prompts/fragments/init-stage-flow.md` 各步承重反例(scout-incomplete-gate 退出码 2、
  T1→T2 `validate_t1_records --strip-bom`+`--check` gate、fan-out 路径 = 枚举脚本 `checkpoint_path`/`rule_path`
  绝对逐字、`.failed` ack、适用 NEVER 子集);`get_discipline(step) -> dict`(未知/无纪律 step → 空结构)。
- [x] 1.2 纯标准库 + 纯数据(无 argparse/无 IO);`sys.path.insert(0, dir-of-__file__)` 自定位(承 R5.3a);
  零依赖 AST 扫描通过。

## 2. resume_state.py stdout 增 discipline_reminders[]

- [x] 2.1 `core/scripts/resume_state.py` stdout 构建处(`:370-376`)增 `discipline_reminders` =
  `discipline_core.get_discipline(step)`;`done`/`not-started` → 空结构;既有 7 字段形状/语义不变。
- [x] 2.2 docstring stdout 段(`:33-41`)更新(增 `discipline_reminders[]` 说明 + 衍生量非持久态声明);
  `--help` 不动(不增 flag)。

## 3. list_steps.py --step 增 discipline 子集

- [x] 3.1 `core/scripts/list_steps.py` `_build_step`(`:196-204`)增 `discipline` =
  `discipline_core.get_discipline(step_id)`;`--step` 闭集/退出码 2 行为不变。
- [x] 3.2 docstring 更新;`--help` 不动。

## 4. 双壳 resume recipe 消费 discipline_reminders[]

- [x] 4.1 `releases/claude-code/commands/mgh-init.md` Resume/cache 段改:「`--resume`/压缩后第一步 =
  `py resume_state.py --target <target>` → 读 stdout `step` + `discipline_reminders[]`,**先按该步纪律执行**
  (gate `--check` 闸门 / 路径配方 / 适用 NEVER),再 `list_steps.py --step <step>` 取调用行」。措辞承 R5.5①
  (recipe 优先,硬边界才用 NEVER)。
- [x] 4.2 `releases/opencode/command/mgh-init.md` 镜像同改。

## 5. 回归测 + 契约面防护

- [x] 5.1 扩 `tests/test_resume_state.py`:断言① 处于某步的 run 输出非空 `discipline_reminders[]` 且覆盖该步
  承重 gate(如 t1 含 `validate_t1_records`);② `done`/`not-started` 输出空纪律;③ stdout 仍是单对象 JSON、
  既有 7 字段逐字不变(增量)。
- [x] 5.2 扩 `tests/test_list_steps.py`:断言 `list_steps.py --step <id>` 的 `discipline` 与
  `resume_state.py` 同 step 的 `discipline_reminders[]` 逐字一致(单一真相)。
- [x] 5.3 跑全套回归(`test_init_runtime.py` 等)+ 三项 lint(契约 `check_contracts.py` / 分发纯净
  `check_distributed_purity.py` / 零依赖 `test_zero_deps.py` 放行新 sibling import);bump 版本号;
  `install.sh` 自检 fail-soft。

## 6. 分发纯净 + 收尾

- [x] 6.1 核对分发纯净 lint(`test_distributed_md_purity.py`)——双壳 resume 段措辞无 `R5.x`/`FDn`/`Dn`/
  变更夹名/dev-meta(操作性语义如 `--check`/退出码 2/`NEVER`/`resume_state.py` 保留)。
- [x] 6.2 冒烟:对既有 mgh-init 产物目录跑 `resume_state.py` 与 `list_steps.py --step t1`,确认 stdout
  增量字段出现且既有字段逐字不变。
