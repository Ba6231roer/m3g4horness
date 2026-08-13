# Tasks — split-mgh-init-stage-flow-per-step

> 实现顺序按依赖;每个任务可验证。**预算层目标**:非同时驻留(resume 只加载当前步 fragment)。**只迁移、不删**
> (保真度优先):scout-incomplete-gate / T1→T2 shape-gate / 级联失效 / `.failed` 终态 / 绝对路径逐字透传 /
> NTFS `::` sanitize / BOM 剥离等承重反例 MUST 随对应 step 进 fragment,NEVER 丢。流水线可观测行为逐字不变;
> 纯 Python ≥3.10 标准库(R2)。任一 `.md`/脚本改动 bump 版本号。

## 1. 拆 init-stage-flow 为 12 个 per-step fragment

- [x] 1.1 建 `core/prompts/fragments/init-stage/` 目录,逐行迁移 `init-stage-flow.md` 正文到 12 个 fragment
  (文件名 = 运行时 step 枚举:`bootstrap,discover,survey,scout,resolve,t1,t2,t3,assemble,t4,merge,done`):
  `bootstrap.md`(step 0:run_config 原子写 + 哨兵生命周期 + MGH_TARGET + codegraph 检测,壳自持首步加载)、
  `merge.md`(step 1)、`discover.md`(step 2:MGH_TARGET 重设 + `--check` 闸门 + `--resume` 跳过语义)、
  `survey.md`(step 3 opt)、`scout.md`(step 3b:批数涌现 + `needs_slice` + `needs_reduce` 分支 + 级联失效 +
  `.failed` ack)、`resolve.md`(step 3c codegraph-gated)、`t1.md`(step 4 + **step 4b T1→T2 shape-gate 并入**:
  `validate_t1_records --strip-bom`+`--check` + scout-incomplete-gate + 分页 `shrunk` + oversize `::shard-<n>`)、
  `t2.md`(step 5 + 聚合硬阈值)、`t3.md`(step 6 + `assemble_rules --check` lint 形状 + `failed` ack)、
  `assemble.md`(step 6b 独立)、`t4.md`(step 7)、`done.md`(step 8:manifest/report 落账 + 失败/scout_merged
  披露 + 收尾 rm 哨兵)。
- [x] 1.2 删除原 `core/prompts/fragments/init-stage-flow.md`(正文已全部分迁,无残留引用);每 fragment 头部
  2–3 行溯源/install 说明注释(承 R1);跨步引用改为相对描述(「step 4b」→「t1.md 的 T1→T2 gate」)。

## 2. resume_state.py stdout 增 stage_flow_files[]

- [x] 2.1 `core/scripts/resume_state.py` stdout 构建处(`:370-376`)增 `stage_flow_files`:
  `step ∈ {discover,survey,scout,resolve,t1,t2,t3,assemble,t4,merge}` → `[Path.resolve() 的
  <mgh-core>/prompts/fragments/init-stage/<step>.md]`(经 `Path(__file__).resolve().parent.parent`,host-agnostic);
  `not-started`/`done` → `[]`。既有 7 字段形状/语义不变。
- [x] 2.2 docstring stdout 段(`:33-41`)更新(增 `stage_flow_files[]` 说明 + 衍生量非持久态 + `not-started`/`done`
  空数组规则);`--help` 不动(不增 flag)。

## 3. 双壳 SUB-SKILL 指令改按步加载 recipe

- [x] 3.1 `releases/claude-code/commands/mgh-init.md` SUB-SKILL 段(`:41-49`)改:「stage 流按需加载:
  `py resume_state.py --target <target>` 拿 `step` + `stage_flow_files[]` → `py list_steps.py --step <step>`
  拿调用行 → Read `stage_flow_files[]`(当前步 fragment)」。NEVER 整份加载全部 step fragment、NEVER 靠
  对话记忆判当前步。
- [x] 3.2 `releases/opencode/command/mgh-init.md` 镜像同改。

## 4. token 预算 + 分发纯净重派生

- [x] 4.1 跑 `py tools/measure_prompts.py releases/claude-code/commands/mgh-init.md releases/opencode/command/mgh-init.md`
  重测:两壳 `mid_tokens` 各 ≤ 5,000(claude 3,048 / opencode 2,986);12 个 fragment 逐个报告单文件尺寸
  (无硬求和上限);磁盘 `mid_tokens` 合计 5,245 ≤ ~10,000(防漂移 lint)。若 lint 报超,逐文件查迁移是否意外
  膨胀(应为纯迁移)。
- [x] 4.2 跑 `py tools/check_distributed_purity.py`:`init-stage/*.md` 逐文件无 `R5.x`/`FDn`/`Dn`/变更夹名/
  dev-meta(操作语义如 `--check`/退出码 2/`NEVER`/确切脚本名保留);`tests/test_distributed_md_purity.py` 覆盖
  `init-stage/` 目录。

## 5. 回归测 + 收尾

- [x] 5.1 扩 `tests/test_resume_state.py`:断言① 处于某步的 run 输出 `stage_flow_files[]` = 该步单个绝对路径;
  ② `not-started`/`done` → `[]`;③ 只含当前步(非 all-remaining);④ 同磁盘状态两次调用逐字一致(衍生量)。
- [x] 5.2 跑全套回归(`test_init_runtime.py` 等)+ 三项 lint(契约 / 分发纯净 / 零依赖);冒烟:既有 mgh-init
  产物目录 `resume_state.py` + `list_steps.py --step t1` 输出既有字段逐字不变;bump 版本号(0.1.24→0.1.25);
  `install.sh` 自检 fail-soft(临时目标安装:12 fragment 全落,旧单文件不镜像)。
- [x] 5.3 同步 `docs/mgh-init-budget-analysis.md` §B.3.2 尺寸表 + `openspec/specs/orchestration-substrate/spec.md`
  场景里的「init-stage-flow 4.8K/130 行」数字为拆分后基线(机制文档 `docs/opencode-context-mechanics.md`
  另会话处理)。
