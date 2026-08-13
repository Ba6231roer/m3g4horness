## MODIFIED Requirements

### Requirement: 壳经 REQUIRED SUB-SKILL 引用 fragment,不内联重复纪律正文

`mgh-init.md`(claude + opencode 两壳)SHALL 经 `REQUIRED SUB-SKILL` 标记引用编排纪律与 stage 流细节,并
从壳正文**移除**被 fragment 覆盖的纪律正文块。编排纪律 = 单一宿主无关 fragment
`orchestrator-discipline.md`(三条 `NEVER` 边界 / implementation-intention recipe / fan-out 刚性三元组 /
temp-file 禁令,抽象名词,不绑 init 专属名);壳 SHALL 保留一句指引(「编排器 = 宿主 agent;完整纪律见
orchestrator-discipline fragment」)。stage 流细节 = **per-step fragment 集** `init-stage/{<step>}.md`
(init 专属正文,step 枚举 key 与 `resume_state.py`/`list_steps.py` 运行时枚举一致),壳经「`resume_state`
拿当前步 → `list_steps --step` 拿调用行 → Read `stage_flow_files[]`(当前步 fragment)」的 recipe 按需加载
**当前步单文件**,NEVER 整份加载 stage 流。两壳引用**同一 per-step fragment 集**(单一真相源目录,零正文 drift);
`install.sh` 镜像 `core/` → `mgh-core/` 时 `init-stage/` 目录整体落入。壳 token 预算:两壳实测 `mid_tokens`
各 SHALL ≤ 5,000 tok;碎片逐个评估单次 Read 轮尺寸(平均 ~0.4K/步,重步 ~0.6–0.8K),磁盘 `mid_tokens`
合计 SHALL ≤ ~10,000 作防漂移 lint(标注根据 = 磁盘大小防漂移,非运行时叠加占用)。

#### Scenario: 两壳引用 orchestrator-discipline + per-step fragment 集而非内联

- **WHEN** 审阅 `releases/claude-code/commands/mgh-init.md` 与 `releases/opencode/command/mgh-init.md`
- **THEN** 两壳均含 `REQUIRED SUB-SKILL: Use orchestrator-discipline`;stage 流按需加载 recipe 为
  「`resume_state` 拿当前步 → `list_steps --step` 拿调用行 → Read `stage_flow_files[]`(当前步 fragment)」;
  均**不**内联 implementation-intention recipe 详述块、三条 `NEVER` 边界详述块与 stage 流逐步细节正文

#### Scenario: 两壳 stage 流正文逐字一致(零 drift)

- **WHEN** 审阅两壳引用的 `init-stage/` fragment 集
- **THEN** 两壳引用**同一目录**(`core/prompts/fragments/init-stage/` 单一真相源);无 claude/opencode 各自
  内联的 stage 流正文副本;fragment 文件名 key 与 `resume_state.py`/`list_steps.py` step 枚举一致
  (`bootstrap` ↔ `not-started`,`discover`/`survey`/`scout`/`resolve`/`t1`/`t2`/`t3`/`assemble`/`t4`/`merge`/`done`
  逐一对应),无重映射

#### Scenario: 壳 token 实测 ≤ 5,000 tok 且碎片磁盘合计 ≤ ~10,000

- **WHEN** 运行 `py tools/measure_prompts.py releases/claude-code/commands/mgh-init.md releases/opencode/command/mgh-init.md`
- **THEN** 两壳 `mid_tokens` 各 ≤ 5,000;`init-stage/*.md` 12 个碎片逐个报告单文件尺寸(无硬求和上限),
  磁盘 `mid_tokens` 合计 ≤ ~10,000(防漂移 lint)

#### Scenario: per-step fragment 集通过分发纯净性 lint

- **WHEN** 运行 `tools/check_distributed_purity.py`
- **THEN** `init-stage/*.md` 每个碎片不含 `R5.x`/`FDn`/`Dn`/变更夹名/`承 R5`/`范式锚点`/「本仓」dev-meta
  (操作性语义如 `--check`/退出码 2/`NEVER`/确切脚本名保留)

### Requirement: mgh-init stage 流细节拆 per-step fragment,行为零变化

SHALL 存在 per-step fragment 集 `core/prompts/fragments/init-stage/`,承载 mgh-init 编排流 step 0–8 的
逐步细节正文,按运行时 step 枚举拆成 `{bootstrap,discover,survey,scout,resolve,t1,t2,t3,assemble,t4,merge,done}.md`
12 个文件(**bootstrap** 对应 step 0 = run_config 原子写 + 哨兵生命周期 + MGH_TARGET + codegraph 检测,壳自持、
首步加载一次;`t1` 对应 step 4 **+ step 4b T1→T2 shape-gate 同文件**;`assemble` 对应 step 6b,独立碎片)。
该 fragment 集是 **init 专属**(非宿主无关),但**两壳共用同一份**(stage 流正文 host-agnostic)。拆分 SHALL
**只迁移、不删**——任何承重内容(scout-incomplete-gate 退出码 2、T1→T2 `validate_t1_records --strip-bom`+`--check`
shape-gate、级联失效、`.failed` 终态、fan-out 路径 = 枚举脚本 `checkpoint_path`/`rule_path` 绝对逐字、NTFS
`::` sanitize、UTF-8 BOM 剥离)MUST 随对应 step 进 fragment,NEVER 丢。壳内 Stage→组件表折叠为紧凑
「script inventory | subagent inventory」(仅名;绝对路径由 `list_steps.py` 运行时给);「Deterministic
invocation (Bash)」整块删除,仅大文件切片 `chunk_sources.py` 形式与 `resume_state.py --invalidate-stale`
配方迁回原生步骤。

#### Scenario: per-step fragment 集承载完整 stage 流(零内容丢失)

- **WHEN** 审阅 `init-stage/` 12 个 fragment
- **THEN** 它们共同覆盖 step 0(parse+self-check+run_config+哨兵+MGH_TARGET+codegraph)、step 1(--merge)、
  step 2(discover+校验)、step 3(survey opt)、step 3b(scout 全流程)、step 3c(resolve codegraph-gated)、
  step 4(T1 fan-out+scout 闸门)、step 4b(T1→T2 gate,并入 `t1.md`)、step 5(T2+聚合+validate_inventory)、
  step 6(T3 fan-out)、step 6b(assemble/lint,独立 `assemble.md`)、step 7(T4)、step 8(manifest+report+
  失败/scout_merged 落账+收尾 rm 哨兵);每步保留确切脚本调用、确切 flag、`--check` 闸门、fan-out 三元组、
  `checkpoint_path`/`rule_path` 绝对路径语义

#### Scenario: 承重反例随 step 进 fragment 不删减

- **WHEN** 审阅 `t1.md` 与 `scout.md`
- **THEN** `t1.md` 含 T1→T2 shape-gate(`validate_t1_records --strip-bom`+`--check`、退出码 2 → 外科式
  重派、NEVER 带破损 T1 记录进 T2)与 scout-incomplete-gate 反例;`scout.md` 含批数涌现公式、`needs_slice`/
  切片、scout-merge `needs_reduce` 分支、级联失效——与拆分前逐字等价(只迁移、不删)

#### Scenario: mgh-init 流水线可观测行为零变化

- **WHEN** 默认运行 `/mgh-init` 与 `/mgh-init --resume`
- **THEN** 产物路径、产物 schema、stdout schema、退出码、fan-out 单元边界、`--check` 闸门行为与拆分前
  逐字一致(无回归);`init_manifest.json::version` 不变

## ADDED Requirements

### Requirement: resume_state.py stdout 携带当前步 stage_flow_files[]

`core/scripts/resume_state.py` 的 stdout(既有 7 字段基座 `{target, format, step, resumable, tiers,
next_action, notes}`)SHALL 增 `stage_flow_files[]` 字段——值 = **当前 step 的单个**
`init-stage/<step>.md` 绝对路径(`Path.resolve()`,Windows 原生),为**增量字段**(不改变既有字段形状/语义)。
当前 step 为 `not-started`(bootstrap 壳自持、首步加载、非 resume 循环)时 SHALL 为空数组 `[]`;
`done` 步无后续加载动作 SHALL 为空数组。**非 all-remaining**(只给当前步,不给 step 0、不给全部剩余步)。
该字段是 **resume 衍生量、非持久态**:值纯从 `<target>/.mgh-init/` 产物 + `run_config.json` 派生的 step
推断,不写入任何磁盘文件;`--check`(R5.9)不涉及该字段。路径 `Path.resolve()` 绝对、逐字透传给编排器
(承 R5.3(b) fan-out 路径契约;对 subagent 任意 cwd 安全,含 Windows 盘符相对)。

#### Scenario: resume 输出当前步单文件绝对路径

- **WHEN** 编排器对处于 t1 步的 run 调用 `resume_state.py --target <t>`
- **THEN** stdout 含 `step: "t1"` 且 `stage_flow_files[]` = `["<abs>/.mgh-init/../prompts/fragments/init-stage/t1.md"]`
  (单个绝对路径,`Path.resolve()` 归一);编排器逐字透传给后续 `Read`

#### Scenario: not-started 与 done 步返回空数组

- **WHEN** run 未开始(`not-started`,无 `.done` marker)或已收尾(`done`)
- **THEN** `stage_flow_files[]` 为空数组 `[]`(bootstrap 壳自持 / 无后续加载);stdout 仍含该字段(shape 稳定)

#### Scenario: 只含当前步,非 all-remaining

- **WHEN** 当前步 `t1`,审阅 `stage_flow_files[]`
- **THEN** 数组只含 `t1.md` 一个条目,不含 `t2`/`t3`/`assemble`/`t4` 等后续步 fragment(非 all-remaining,
  非 step 0)

#### Scenario: 值派生自磁盘 step 推断,不持久化

- **WHEN** 对同一磁盘状态的 run 连续两次调用 `resume_state.py`
- **THEN** `stage_flow_files[]` 两次逐字一致(同一步 → 同一文件路径);`stage_flow_files[]` 未写入
  `.mgh-init/` 任何文件
