## Context

`core/prompts/fragments/init-stage-flow.md` 是 mgh-init 编排流 step 0–8 的逐步细节载体,**4,769 mid / 130 行**,
两壳(claude + opencode)经 `REQUIRED SUB-SKILL: Use init-stage-flow` **整份加载**。prune 默认关
(`docs/mgh-init-budget-analysis.md` §1.2 纠错 2)下,默认用户真省 token 头号杠杆 = **缩壳 + 拆 fragment
(非同时驻留)**;`list_steps.py --step` 已能确定性给出当前步**调用行 + I/O 契约**(§B.1,零新代码)。

§B 是维护者拍板的**预算层方案 2B**(2026-08-12):**`list_steps --step`(现成)+ 按步拆 fragment(给纪律)+
resume 只加载当前步**。收益 = **非同时驻留**(只加载当前步单个 fragment,平均 ~0.4K/步,非整份 4.8K)。
与准确度头号 change(`complete-r5-4-per-step-discipline`)**正交、可并行、可后合并**(§B.5);本设计**只管预算层**,
不承担准确度目标。

利益相关方:① 维护者(要非同时驻留 + 调 shell 指令);② mgh-init 既有使用者(零感知——流水线行为逐字不变,
只有 fragment 加载方式变化);③ `complete-r5-4-per-step-discipline`(未来合并时以 fragment 纪律段为单一真相)。

## Goals / Non-Goals

**Goals:**
- `init-stage-flow.md` 单文件 → `init-stage/{bootstrap,discover,survey,scout,resolve,t1,t2,t3,assemble,t4,merge,done}.md`
  12 个 per-step fragment(平均 ~0.4K,重步 ~0.6–0.8K)。**只迁移、不删**。
- `resume_state.py` stdout 增 `stage_flow_files[]`(当前步单文件绝对路径,`Path.resolve()`);`not-started`/`done` → `[]`。
- 双壳 SUB-SKILL 指令改:「`resume_state` 拿当前步 → `list_steps --step` 拿调用行 → Read `stage_flow_files[]`」。
- 既有回归测 + 契约 lint + 分发纯净 lint 全绿;两壳 token 实测 ≤ 5,000;碎片磁盘合计 ≤ ~10,000(防漂移)。

**Non-Goals:**
- **不**改 mgh-init 流水线可观测行为(产物/退出码/路径/`--check` 闸门逐字不变)。
- **不**让脚本携带纪律正文(`list_steps --step` 仍只给调用行+I/O,纪律留 fragment;承 §B.2 避 R5.1 张力)。
- **不**实现 `discipline_reminders[]`(那是 `complete-r5-4-per-step-discipline` 的事)。
- **不**改 `install.sh` 镜像规则(`cp -r core/` 自动含新目录)。
- **不**新增 pip 依赖、不新增 CLI flag。

## Decisions

### D1 — 采用 §B.3.1 的 step 枚举映射(决策已定,直接采用)

- **选择**:fragment 文件名 + `stage_flow_files[]` **统一 key 在 `resume_state.py`/`list_steps.py` 的 step
  枚举**(`not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`);init-stage-flow 的
  0–8 编号只是文档结构,非运行时枚举。映射:`bootstrap`↔`not-started`(壳自持、首步加载一次)、
  `t1` 含 step 4b gate、`assemble` 独立。12 个 fragment 文件名 = `bootstrap,discover,survey,scout,resolve,
  t1,t2,t3,assemble,t4,merge,done`。
- **理由**:resume_state 就 emit 该枚举、`list_steps --step` 也吃该枚举,三者同 key 零重映射(§B.3.1 决策,
  评审 agent 标记的关键缺口已消歧);`resume_state.py:46` 枚举 = 单一锚点。
- **备选(否决)**:fragment 用 init-stage-flow 的 0–8 编号命名——否决:编号是文档结构,与运行时枚举
  无机械对应,resume 路径要重映射,漂移风险。

### D2 — `resume_state.py` 增 `stage_flow_files[]`,按当前步查 fragment 路径

- **选择**:stdout 构建处(`resume_state.py:370-376`)增 `stage_flow_files`:
  - `step ∈ {discover,survey,scout,resolve,t1,t2,t3,assemble,t4,merge,done}` → `[Path(__file__).resolve().parent.parent / "prompts" / "fragments" / "init-stage" / f"{step}.md"]`
    (经 `Path.resolve()`;`__file__` 自定位 `<mgh-core>/scripts/`,`parent.parent` = `<mgh-core>/`)。
  - `step == "not-started"`(bootstrap 壳自持)→ `[]`;`step == "done"` → `[]`。
  - 文件不存在(异常安装)时 SHALL 仍输出路径(绝对、逐字透传),由编排器 Read 时自然报错,不静默跳过;
    stderr 可给 advisory。
- **理由**:`__file__` 自定位(承 R5.3a)使 fragment 路径随安装镜像自动正确(claude `.claude/mgh-core/` /
  opencode `.opencode/mgh-core/` 自适应,两壳零分发改动);`Path.resolve()` 绝对对 subagent 任意 cwd 安全
  (含 Windows 盘符相对);「非 all-remaining」= 只当前步,符合 §B.4#2。
- **备选(否决)**:硬编码 `.claude/mgh-core/prompts/...`——否决:opencode 是 `.opencode/mgh-core/`,
  硬编码破坏 host-agnostic;`__file__` 派生天然自适应。

### D3 — 拆分只迁移不删,承重反例随 step 进 fragment

- **选择**:逐行迁移 `init-stage-flow.md` 正文到 12 个 fragment,按 step 边界切分。**每步承重反例原地带走**:
  - `discover.md`:MGH_TARGET 重设、`--check` 闸门、`--resume` 跳过语义、派生量直读 stdout。
  - `scout.md`:批数涌现公式、`needs_slice`/切片、scout-merge `needs_reduce` 分支、级联失效、`.failed` ack。
  - `t1.md`:scout-incomplete-gate(退出码 2)、分页 `shrunk`、`failed` ack、oversize `::shard-<n>` 切片、
    **step 4b T1→T2 shape-gate**(`validate_t1_records --strip-bom`+`--check`)并入同文件。
  - `t3.md`:`assemble_rules --check` lint 形状、`failed` ack;`assemble.md`(step 6b)独立。
  - `bootstrap.md`:run_config 原子写 + 哨兵生命周期 + MGH_TARGET + codegraph 检测(step 0,壳自持首步加载)。
  - `done.md`:manifest/report 落账 + 失败/scout_merged 披露 + 收尾 rm 哨兵。
  头部溯源注释(`Source: ...` / install 说明)保留在 bootstrap 或每个 fragment(承 R1)。
- **理由**:「只迁移、不删」= 保真度优先(报告「⚠ 裁剪前提」);承重反例是历史 bug 防线,拆分不得丢;
  `t1` 并入 4b gate(§B.3.1 决策)保证「T1 步的完整纪律」单文件自含。
- **备选(否决)**:迁移时顺手删冗余——否决:预算 change 不承担「裁剪内容」职责,删内容会丢承重防线,
  且与本 change 目标(结构拆分,非内容删减)冲突。

### D4 — 双壳 SUB-SKILL 指令改为按步加载 recipe

- **选择**:两壳 `mgh-init.md` 的 SUB-SKILL 段(`releases/claude-code/commands/mgh-init.md:41-49` + opencode
  镜像)改为:「stage 流细节按需加载:`py resume_state.py --target <target>` 拿 stdout `step` +
  `stage_flow_files[]` → `py list_steps.py --step <step>` 拿调用行 → Read `stage_flow_files[]`(当前步
  fragment)。NEVER 整份加载全部 step fragment、NEVER 从对话记忆判当前步」。
- **理由**:step 0(bootstrap)壳自持、首步加载一次(不走 resume 循环);其余步走「resume_state → list_steps →
  Read 当前步」recipe,非同时驻留。措辞承 R5.5①(recipe 优先,硬边界才用 NEVER)。
- **备选(否决)**:壳仍整份加载(保持现状)——否决:那是本 change 要消除的 4.8K 同时驻留。

### D5 — token 预算 + 分发纯净 lint 重派生

- **选择**:拆分后用 `tools/measure_prompts.py` 重测:两壳 `mid_tokens` 各 ≤ 5,000(拆分后壳更瘦);
  12 个 fragment 逐个报告单文件尺寸(无硬求和上限);磁盘 `mid_tokens` 合计 ≤ ~10,000(防漂移 lint)。
  `tools/check_distributed_purity.py` / `tests/test_distributed_md_purity.py` 对 `init-stage/*.md` 逐文件
  覆盖(无 R5.x/FDn/Dn/变更夹名/dev-meta;操作语义保留)。
- **理由**:R5.6 壳 ≤5,000 硬上限是 lint fail-loud;碎片防漂移 lint 已从「单文件求和」改为「逐个评估 +
  磁盘合计 ≤ ~10K」(R5.6 现行条文);拆分后测量值会变化,需重派生基线。
- **备选(否决)**:沿用拆分前单文件 4.8K 基线——否决:12 文件求和会虚高,且逐文件 lint 更贴合
  R5.6「逐个评估」语义。

### D6 — 与 complete-r5-4-per-step-discipline 的合并路径(不阻塞)

- **选择**:本 change 的 fragment 纪律段(`t1.md` 的 gate、`scout.md` 的闸门等)是未来
  `discipline_reminders[]` 的**数据源**(§B.5):`complete-r5-4-per-step-discipline` 落地后,静态
  `discipline_core` 表可改从 fragment 纪律段派生。两 change 各改 resume_state 不同字段
  (`stage_flow_files[]` vs `discipline_reminders[]`),apply 顺序无关、git 合并不冲突。
- **理由**:§B.5 明示两路径正交、可并行;合并是未来选项,当前分离推进互不阻塞。

## Risks / Trade-offs

- **[拆分引入 fragment 间引用断裂(某步正文引用别的 step 编号)]** → 迁移时检查跨步引用,改为
  相对描述(「见 step 4b gate」→「见 t1.md 的 T1→T2 gate」);无跨步正文依赖则天然安全。
- **[`stage_flow_files[]` 路径在异常安装下指向不存在文件]** → 脚本仍输出绝对路径,由编排器 Read
  自然报错(不静默跳过);stderr advisory 提示 install 镜像问题;正常安装(`install.sh` 镜像 `core/` →
  `mgh-core/`)必然存在。
- **[12 个 fragment 的磁盘合计超过 ~10K 防漂移线]** → 拆分 = 同一正文重排 + 头部注释,总和 ~原 4.8K +
  12 个头部注释(~2K)= ~7K < 10K;若 lint 报超,逐文件查「迁移是否意外膨胀」(应为纯迁移)。
- **[壳 token 在 SUB-SKILL 改写后超 5K]** → 改写是「整文件加载 → 按步 recipe」,壳只增 ~2–3 行 recipe
  措辞(净减,因去掉整文件加载语义);实测后若超,回退到极简 recipe 措辞。
- **[与 complete-r5-4-per-step-discipline 并发改 resume_state.py 的 stdout 构建函数]** → 各加各字段
  (增量、不同 key),diff 不冲突;回归测各自扩,合并后全绿。

## Migration Plan

1. 建 `core/prompts/fragments/init-stage/` 目录,按 D3 迁移 `init-stage-flow.md` 正文到 12 个 fragment
   (逐行搬移、保真优先);删原 `init-stage-flow.md`。
2. `core/scripts/resume_state.py`:stdout 构建处增 `stage_flow_files`(D2 规则);docstring stdout 段更新。
3. 双壳 `mgh-init.md`(claude + opencode)SUB-SKILL 指令改(D4 recipe)。
4. 跑 `tools/measure_prompts.py` 重测壳 + 12 fragment 尺寸,记新基线;`tools/check_distributed_purity.py`
   逐文件 lint。
5. 扩测:`test_resume_state.py` 增 `stage_flow_files[]` 断言(D2 四条);`test_distributed_md_purity.py`
   覆盖 `init-stage/`;跑全套回归 + 三项 lint;bump 版本号。
6. **回滚**:fragment 拆分是文件迁移(可 git revert 恢复单文件);`stage_flow_files[]` 是 stdout 增量
   字段无行为依赖;壳 SUB-SKILL 措辞 revert 回「Use init-stage-flow」。产物 schema 无变化。

## Open Questions

- 12 个 fragment 的**头部溯源注释**策略:每文件一份 install 说明 vs 只在 bootstrap 一份——倾向每文件
  头部 2–3 行(便于独立 Read),合计 ~2K 在预算内。
- `not-started` 步是否要在 `stage_flow_files[]` 给 `bootstrap.md`(而非 `[]`)——§B.4#2 说「非 step 0」,
  倾向 `[]`(bootstrap 壳自持、首步加载);若实测发现 resume 首步需要 bootstrap recipe,再改为给
  `bootstrap.md`。
- 拆分后 `docs/opencode-context-mechanics.md` / `docs/mgh-init-budget-analysis.md` / `orchestration-substrate`
  spec 里「init-stage-flow 4.8K/130 行」数字的同步——倾向本 change 内同步关键引用(budget-analysis §B.3.2
  尺寸表 + orchestration-substrate spec 场景),机制文档(`opencode-context-mechanics.md`)另会话处理。
