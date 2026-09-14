# Spec: orchestration-substrate

## Purpose

确立**宿主无关的共享编排纪律基座**:把 `mgh-init`(及未来 `mgh-ut-init` / `mgh-ut`)壳里重复内联的
通用编排纪律正文(orchestrator = 宿主 agent、三条 `NEVER` 硬边界、fan-out 刚性三元组、
implementation-intention recipe、resume-from-disk recipe、`.failed` 终态、长跑 Bash per-call `timeout`)
抽成单一 fragment,壳经 `REQUIRED SUB-SKILL` 间接引用;并把 `resume_state.py` /
`write_runconfig.py` 的运行目录名参数化为 `--run-root`。本能力由 change `extract-shared-substrate`
建立(P0),**行为保持**:mgh-init 是首个消费方,sast 不在本能力范围
(其纪律由 `sast-orchestration-discipline` 治理)。

## Requirements

### Requirement: 单一共享 orchestrator-discipline fragment 持有宿主无关纪律正文

SHALL 存在唯一 fragment `core/prompts/fragments/orchestrator-discipline.md`,持有当前在 `mgh-init`
两壳内联的**宿主无关**编排纪律正文,至少覆盖:① 编排器 = 宿主 agent(非物化脚本);② 三条 `NEVER`
硬边界(`Write` 任何脚本扩展名编排器/微脚本、经 `Bash` `py -c`/`python -c` 内省/重派生产物、`Read`
叶子 `.py` 源码进上下文);③ implementation-intention recipe(需工作清单/瞄结构/派生量/单单元输出路径/
当前步骤 → 各自合法出口,`NEVER py -c`);④ fan-out 刚性三元组(`[输入产物::字段] → script/subagent →
[输出产物::字段]`,输出路径 = 枚举脚本 stdout 的 `checkpoint_path`/`rule_path`,绝对、逐字透传);⑤
`.failed` = 终态(resume 不重派;crash 无 ack → 仍 pending → 重派);⑥ 长跑确定性 Bash per-call
`timeout` 纪律 + opencode env-var 可靠性边界;⑦ **编排器自身禁止向系统临时目录(`$env:TEMP` / `%TEMP%` /
`/tmp` / `TMPDIR`)写中间文件,stdout MUST 从 Bash 工具返回值直接消费**。fragment 正文 SHALL **泛化**
(用「该命令的 `list_*` 枚举脚本」/「resume-state 脚本」等抽象名词),**不**绑定 init 专属脚本名/产物名
(那些留在各壳 stage 流)。fragment 是分发产物,SHALL 通过分发纯净性 lint:无研发铁律编号、失败/设计 ID、
openspec 变更夹名、dev-meta 措辞。

#### Scenario: fragment 文件存在且被分发镜像

- **WHEN** 审阅 `core/prompts/fragments/` 目录与 `install.sh` 镜像规则
- **THEN** `orchestrator-discipline.md` 存在;`install.sh` 镜像 `core/` → `.claude/mgh-core/` 时该
  fragment 一并落入 `.claude/mgh-core/prompts/fragments/orchestrator-discipline.md`

#### Scenario: fragment 持有三条 NEVER 硬边界、fan-out 三元组与 temp-file 禁令

- **WHEN** 审阅 `orchestrator-discipline.md` 正文
- **THEN** 其显式包含三条 `NEVER` 边界 + fan-out 刚性三元组 + `.failed` 终态声明 + per-call `timeout`
  纪律 + **stdout 直消费 recipe(含 `NEVER` 向 `$env:TEMP`/`%TEMP%`/`/tmp`/`TMPDIR` 写中间文件)**,
  且用抽象名词指代脚本(不出现 `list_clusters.py`/`resume_state.py` 等 init 专属名)

#### Scenario: fragment 通过分发纯净性 lint

- **WHEN** 运行 `tools/check_distributed_purity.py`
- **THEN** `orchestration-discipline.md` 不含 `R5.x`/`FDn`/`Dn`/变更夹名/`承 R5`/`范式锚点` 等 dev-meta
  (操作性语义如 `--check`/退出码 2/`NEVER` 保留)

### Requirement: 编排器禁止向系统临时目录写中间文件

`orchestrator-discipline.md` SHALL 增显式 `NEVER`:编排器 MUST NOT 把确定性脚本 stdout 重定向到磁盘文件
(尤其系统临时目录 `$env:TEMP` / `%TEMP%` / `/tmp` / `TMPDIR`),再从文件回读解析。stdout SHALL 从 Bash
工具返回值直接消费。同一条 Bash 调用内「写 temp + 回读」的配对模式视为违纪。

正引导 recipe SHALL 以如下措辞出现:「取确定性脚本的 JSON 输出:经 Bash 跑该脚本、从工具返回值取 stdout
(最后一行是 JSON)、在你的推理里解析 `pending[]`。NEVER 把 stdout 重定向到磁盘文件、NEVER
`$env:TEMP`/`%TEMP%`/`/tmp`/`TMPDIR`」。

#### Scenario: 编排器经 Bash 工具返回值消费 stdout(正例)

- **WHEN** 编排器需要取 `list_scout_batches.py` 的 `pending[]`
- **THEN** 编排器经 `Bash: py <...>/list_scout_batches.py ...` 执行,从 Bash 工具返回值的 stdout 字段取 JSON
  (最后一行);NEVER 在命令字符串中使用 `>` 重定向到文件

#### Scenario: 编排器向 $env:TEMP 写中间文件触发纪律违例(反例)

- **WHEN** 编排器执行 `py <...>/list_scout_batches.py ... > $env:TEMP/scout_page0.json; Get-Content $env:TEMP/scout_page0.json | ConvertFrom-Json ...`
- **THEN** 该行为违反本 requirement;编排纪律 SHALL 显式禁止该模式

### Requirement: 壳经 REQUIRED SUB-SKILL 引用 fragment,不内联重复纪律正文

`mgh-init.md`(claude + opencode 两壳)SHALL 经 `REQUIRED SUB-SKILL: Use orchestrator-discipline`
标记引用上述 fragment,并从壳正文中**移除**被 fragment 覆盖的宿主无关纪律正文块(三条 `NEVER` 边界
详述、implementation-intention recipe 详述、fan-out 刚性三元组详述)。壳 SHALL 保留一句指引(「编排器
= 宿主 agent;完整纪律见 orchestrator-discipline fragment」)+ 壳内 init 专属内容(stage 流、确切
`list_*`/`resume_state.py` 调用行、产物清单、`MGH_INIT_ACTIVE`/哨兵、init 边界披露)。两壳引用同一个
fragment(零正文 drift)。

**stage 流细节的载体**(自本变更起):mgh-init stage 流的**逐步细节正文**(not-started bootstrap 的
run_config 写、哨兵生命周期、codegraph 检测、discover/scout/T1/T2/T3/T4 的 fan-out 刚性三元组与
`--check` 校验、聚合硬阈值、scout 级联失效落账、fan-out 失败落账等)SHALL 拆进 **per-step fragment 集**
`core/prompts/fragments/init-stage/{<step>}.md`(12 文件,step 枚举 key 与 `resume_state.py`/
`list_steps.py` 运行时枚举一致;`bootstrap` ↔ `not-started`、`t1` 含 T1→T2 gate、`assemble` 独立);
壳经「`resume_state` 拿当前步 → `list_steps --step` 拿调用行 → Read `stage_flow_files[]`(当前步
fragment)」recipe **按需加载当前步单文件**,NEVER 整份加载。壳内**仅保留** parse-args + SUB-SKILL
指令 + Stage→组件表(紧凑) + Resume/cache + Output + Always disclose(精简)。两壳引用**同一
per-step fragment 集**(零正文 drift;壳体 claude/opencode 差异留在壳,stage 流正文 host-agnostic
由壳侧的 `.claude/mgh-core` / `.opencode/mgh-core` 前缀覆盖)。

**命名 step id 契约**(自本变更起):壳的 stage-flow recipe SHALL 只使用**命名 step id**(与
`resume_state.py` stdout `step` 字段一致:not-started/discover/survey/scout/resolve/t1/t2/t3/
assemble/t4/merge/done);`list_steps.py --step <id>` 只接受命名 id。数字索引(0-based,如 `--step 0`)
NEVER 出现在壳/fragment 的调用面、NEVER 传给 `list_steps --step`(闭集拒歧义,退出码 2)。壳 SHALL
不再以「step 0–8」数字标注流程节点(旧 init-stage-flow 编号仅作文档结构,非运行时枚举)。

**fresh-run bootstrap 可达性**(自本变更起):fresh-run(首 run,`<target>/.mgh-init/` 不存在 /
`resume_state.py` exit 1)SHALL 经壳 **fixed-path Read** `<mgh-core>/prompts/fragments/init-stage/
bootstrap.md` 加载 bootstrap 正文(run_config 原子写 + 哨兵 + MGH_TARGET + codegraph 检测),再
`resume_state` → `discover` 进统一循环;NEVER 对 bootstrap 调 `list_steps --step <数字>`(bootstrap
在 `stage_flow_files[]` 中结构性不存在——not-started 返回 `[]`、run_config 前 exit 1,故由壳直达)。

**壳 token 预算**(自本变更起):mgh-init 两壳经 `tools/measure_prompts.py` 实测 `mid_tokens` 各
**SHALL ≤ 5,000 tok**(R5.6 硬上限;壳 = 触发轮 USER 首条消息、primacy 区,lost-in-the-middle + 防回归,
据 `docs/opencode-context-mechanics.md` §1/§6)。**编排器 fragments**(init-stage 12 个 per-step +
orchestrator-discipline)SHALL **逐个评估**单次 Read 轮尺寸是否结构良好(**不**强制求和 ≤ N;实测平均
~0.44K/步,重步 scout ~1.0K / t1 ~0.86K,轻步 merge 75 / t4 96);磁盘 `mid_tokens` 合计 SHALL ≤ ~10,000
作**防漂移** lint 上限(标注根据 = 磁盘大小防漂移,**非**运行时叠加占用——opencode 下壳与各 fragment
均为单次 lazy Read 的 USER 历史项、非每轮 system 税,见 `docs/opencode-context-mechanics.md` §1/§6)。

#### Scenario: 两壳引用 orchestrator-discipline + per-step fragment 集而非内联

- **WHEN** 审阅 `releases/claude-code/commands/mgh-init.md` 与 `releases/opencode/command/mgh-init.md`
- **THEN** 两壳均含 `REQUIRED SUB-SKILL: Use orchestrator-discipline`;stage 流按需加载 recipe 为
  「`resume_state` 拿当前步 → `list_steps --step` 拿调用行 → Read `stage_flow_files[]`(当前步 fragment)」;
  且均**不**再内联 implementation-intention recipe 详述块与三条 `NEVER` 边界详述块(在 orchestrator-discipline)
  及 stage 流逐步细节正文(在 per-step fragment 集)

#### Scenario: fresh-run bootstrap 经壳 fixed-path Read,NEVER --step 数字

- **WHEN** 首 run 执行 `/mgh-init`(`<target>/.mgh-init/` 不存在),审阅壳 stage-flow recipe
- **THEN** 壳指引「Read `<mgh-core>/prompts/fragments/init-stage/bootstrap.md` 按之执行 bootstrap,
  然后 resume_state → discover 进统一循环」;壳/碎片中无「`list_steps.py --step 0`」类数字调用面;
  bootstrap 步不进入 resume_state 循环

#### Scenario: 壳以命名 step id 标注流程节点,无数字残留

- **WHEN** 审阅两壳与 `init-stage/` fragment 的流程标注
- **THEN** 流程节点以命名 step id 标注(`not-started`→`discover`→`survey`→`scout`→`resolve`→`t1`→
  `t2`→`t3`→`assemble`→`t4`→`merge`→`done`);编排器可读面无「step 0–8」「(step 0)」「(2)…(8)」数字残留

#### Scenario: init 专属调用面与表留在壳内

- **WHEN** 审阅两壳的 parse-args / Stage→组件表 / Resume·cache / Output / Always disclose 段
- **THEN** 确切脚本名(`discover_controls.py`/`list_clusters.py`/`list_scout_batches.py`/`list_rule_jobs.py`/
  `resume_state.py`/`write_runconfig.py` 等)、确切 flag、产物路径、`MGH_INIT_ACTIVE`/`.mgh-init/.active` 哨兵
  指针、`list_steps.py` 调用面仍在壳内(未随 stage 流细节一并移出)

#### Scenario: 壳 token 实测 ≤ 5,000 tok 且碎片磁盘合计 ≤ ~10,000

- **WHEN** 运行 `py tools/measure_prompts.py releases/claude-code/commands/mgh-init.md releases/opencode/command/mgh-init.md`
- **THEN** 两文件 `mid_tokens` 各 ≤ 5,000;`init-stage/*.md` 12 碎片逐个报告单文件尺寸;磁盘 `mid_tokens`
  合计 ≤ ~10,000(防漂移 lint)

#### Scenario: per-step fragment 集通过分发纯净性 lint

- **WHEN** 运行 `tools/check_distributed_purity.py`
- **THEN** `init-stage/*.md` 每个碎片不含 `R5.x`/`FDn`/`Dn`/变更夹名/`承 R5`/`范式锚点`/「本仓」dev-meta
  (操作性语义如 `--check`/退出码 2/`NEVER`/确切脚本名保留)

#### Scenario: 两壳 stage 流正文逐字一致(零 drift)

- **WHEN** 审阅两壳引用的 `init-stage/` fragment 集
- **THEN** 两壳引用**同一目录**(`core/prompts/fragments/init-stage/` 单一真相源);无 claude/opencode 各自内联的
  stage 流正文副本;fragment 文件名 key 与 `resume_state.py`/`list_steps.py` step 枚举一致(零重映射)

### Requirement: mgh-init stage 流细节拆 per-step fragment,行为零变化

SHALL 存在 per-step fragment 集 `core/prompts/fragments/init-stage/`,承载 mgh-init 编排流
(not-started bootstrap → discover → survey → scout → resolve → t1 → t2 → t3 → assemble → t4 →
merge → done)的逐步细节正文,按运行时 step 枚举拆成 `{bootstrap,discover,survey,scout,resolve,t1,t2,t3,
assemble,t4,merge,done}.md` 12 个文件(**bootstrap** 对应 `not-started` = run_config 原子写 + 哨兵生命周期 +
MGH_TARGET + codegraph 检测,由壳 fresh-run recipe **fixed-path Read** 加载一次;`t1` 对应 T1 fan-out
**+ T1→T2 shape-gate 同文件**;`assemble` 对应 BUILD INDEX+LINT,独立碎片)。
该 fragment 集是 **init 专属**(非宿主无关——含 init 专属脚本名/产物名/fan-out 三元组),但**两壳共用同一份**
(claude 与 opencode 仅壳体措辞差异,stage 流正文 host-agnostic)。拆分 SHALL **只迁移、不删**——任何承重
内容(scout-incomplete-gate 退出码 2、T1→T2 `validate_t1_records --strip-bom`+`--check` shape-gate、级联失效、
`.failed` 终态、fan-out 路径 = 枚举脚本 `checkpoint_path`/`rule_path` 绝对逐字、NTFS `::` 文件名 sanitize、
盘符根漂移防护、UTF-8 BOM 剥离)MUST 随对应 step 进 fragment,NEVER 丢。壳内 Stage→组件表折叠为紧凑
「script inventory | subagent inventory」(仅名;绝对路径由 `list_steps.py` 运行时给);「Deterministic
invocation (Bash)」整块删除,仅大文件切片 `chunk_sources.py` form 与 `resume_state.py --invalidate-stale`
配方迁回原生步骤。「Always disclose」压为 5 条规范要点,细节落 `init_manifest.json::boundaries[]` / `report.md`。

#### Scenario: per-step fragment 集承载完整 stage 流(零内容丢失)

- **WHEN** 审阅 `init-stage/` 12 个 fragment
- **THEN** 它们共同覆盖 bootstrap(`not-started`:parse + self-check + run_config 原子写 + 哨兵生命周期 +
  MGH_TARGET + codegraph 检测,在 `bootstrap.md`)、`merge`(--merge 模式,`merge.md`)、`discover`(i1 discover +
  校验,`discover.md`)、`survey`(init-survey opt,`survey.md`)、`scout`(SCOUT FAN-OUT 含聚合硬阈值预判 +
  级联失效 + 终态,`scout.md`)、`resolve`(init-resolve codegraph-gated,`resolve.md`)、`t1`(T1 FAN-OUT +
  scout 闸门 + T1→T2 边界闸门 BOM+形状,`t1.md`)、`t2`(T2 + 聚合硬阈值 + validate_inventory,`t2.md`)、
  `t3`(T3 FAN-OUT,`t3.md`)、`assemble`(BUILD INDEX+LINT,`assemble.md`)、`t4`(T4,`t4.md`)、`done`
  (manifest + report + 失败/scout_merged 落账 + 收尾 rm 哨兵,`done.md`);
  每步保留确切脚本调用、确切 flag、`--check` 闸门、fan-out 三元组、`checkpoint_path`/`rule_path` 绝对路径语义

#### Scenario: 壳删 Bash 目录块但保留逃生口

- **WHEN** 审阅两壳
- **THEN** 两壳**无**「### Deterministic invocation (Bash)」整块目录;但大文件切片 `chunk_sources.py` 调用 form
  与 `resume_state.py --invalidate-stale` 配方仍在(迁入 stage 流对应步骤或 Resume/cache 段)

#### Scenario: mgh-init 流水线可观测行为零变化

- **WHEN** 默认运行 `/mgh-init` 与 `/mgh-init --resume`
- **THEN** 产物路径、产物 schema(`controls_candidates.json`/`clusters.json`/`controls_inventory.json`/
  `init_manifest.json`/`report.md`/rules)、stdout schema、退出码、fan-out 单元边界、`--check` 闸门行为
  与变更前逐字一致(无回归);`init_manifest.json::version` 保持 7(无 schema 变更)

### Requirement: resume_state.py stdout 携带当前步 stage_flow_files[]

`core/scripts/resume_state.py` 的 stdout(既有 7 字段基座 `{target, format, step, resumable, tiers,
next_action, notes}` + `discipline_reminders[]`)SHALL 增 `stage_flow_files[]` 字段——值 = **当前 step 的
单个** `init-stage/<step>.md` 绝对路径(`Path.resolve()`,Windows 原生),为**增量字段**(不改变既有字段
形状/语义)。当前 step 为 `not-started`(bootstrap 由壳 fresh-run recipe **fixed-path Read**
`<mgh-core>/prompts/fragments/init-stage/bootstrap.md` 加载、非 resume 循环)时 SHALL 为空数组 `[]`;
`done` 步无后续加载动作 SHALL 为空数组。**非 all-remaining**(只给当前步,不给 step 0、不给全部剩余步)。
该字段是 **resume 衍生量、非持久态**:值纯从 `<target>/.mgh-init/` 产物 + `run_config.json` 派生的 step
推断,不写入任何磁盘文件;`--check`(R5.9)不涉及该字段。路径 `Path.resolve()` 绝对、逐字透传给编排器
(承 R5.3(b) fan-out 路径契约;对 subagent 任意 cwd 安全,含 Windows 盘符相对)。

#### Scenario: resume 输出当前步单文件绝对路径

- **WHEN** 编排器对处于 t1 步的 run 调用 `resume_state.py --target <t>`
- **THEN** stdout 含 `step: "t1"` 且 `stage_flow_files[]` = `["<abs>/prompts/fragments/init-stage/t1.md"]`
  (单个绝对路径,`Path.resolve()` 归一);编排器逐字透传给后续 `Read`

#### Scenario: not-started 与 done 步返回空数组

- **WHEN** run 未开始(`not-started`)或已收尾(`done`)
- **THEN** `stage_flow_files[]` 为空数组 `[]`(bootstrap 由壳 fresh-run recipe fixed-path Read 加载 /
  无后续加载);stdout 仍含该字段(shape 稳定)

#### Scenario: 只含当前步,非 all-remaining

- **WHEN** 当前步 `t1`,审阅 `stage_flow_files[]`
- **THEN** 数组只含 `t1.md` 一个条目,不含 `t2`/`t3`/`assemble`/`t4` 等后续步 fragment(非 all-remaining,
  非 step 0)

#### Scenario: 值派生自磁盘 step 推断,不持久化

- **WHEN** 对同一磁盘状态的 run 连续两次调用 `resume_state.py`
- **THEN** `stage_flow_files[]` 两次逐字一致(同一步 → 同一文件路径);`stage_flow_files[]` 未写入
  `.mgh-init/` 任何文件

### Requirement: list_steps.py --step 数字 id 报错可操作化

`core/scripts/list_steps.py --step <id>` 的闭集验证(R5.3b 拒歧义)SHALL 保持退出码 2 不变,但当传入的
id **非命名枚举**(如数字索引 `0`)时,stderr SHALL 附带**可操作 hint**:step id 是命名枚举(读
`resume_state.py` stdout `step` 字段,或 `list_steps.py` 不带 `--step` 列全表),数字索引不接受。
`--help` 的 `--step` 描述 SHALL 注明「named ids only;NOT numeric indices」。该报错分支 SHALL 被
`tests/test_list_steps.py` 机械化断言(`list_steps.py --step 0` → exit 2 + stderr 含 hint + known 列表)。

#### Scenario: 数字 id 触发 exit 2 + 可操作 hint

- **WHEN** 调用 `py core/scripts/list_steps.py --step 0`
- **THEN** 退出码 2;stderr 含 `unknown step id` + `known:` 命名列表 + hint(指明 id 为命名枚举、
  「numeric indices are NOT accepted」);stdout 无部分 manifest(不混入)

#### Scenario: 命名 id 行为不变

- **WHEN** 调用 `py core/scripts/list_steps.py --step t1`
- **THEN** 退出码 0;stdout 仅含 t1 单步完整 manifest;stderr 无 hint(命名 id 不受影响)

### Requirement: 「本仓」dev-meta 修正为「目标项目」

两壳顶部编排器声明中的「本仓」措辞(指 m3g4horness 研发仓)SHALL 改为「目标项目」——该措辞出现在
**分发给目标 agent** 的提示词中,目标 agent 可能误读为「m3g4horness 研发仓」而非其所在的目标项目,
造成歧义。R5.10 第 7 类 dev-meta(指本研发仓时的「本仓」)由 `tools/check_distributed_purity.py` 守护;
本变更 SHALL 使该措辞在两壳顶部消失。

#### Scenario: 两壳顶部无「本仓」措辞

- **WHEN** 审阅 `releases/claude-code/commands/mgh-init.md` 与 `releases/opencode/command/mgh-init.md` 顶部编排器声明
- **THEN** 「本仓」改为「目标项目」(或等价无歧义措辞);`tools/check_distributed_purity.py` 对该 dev-meta 通过

### Requirement: resume_state.py 与 write_runconfig.py 暴露 --run-root 参数

`core/scripts/resume_state.py` 与 `core/scripts/write_runconfig.py` 各 SHALL 接受 `--run-root <name>`
(运行目录名,默认 `.mgh-init`)。运行目录解析优先级:`--init-dir`(显式全路径)> `--run-root` →
`<target>/<name>` > 默认 `<target>/.mgh-init`。`--help` 即 CLI 契约面;`tools/check_contracts.py`
断言双壳调用的每个新 flag 在脚本 `--help` 中存在。默认值 `.mgh-init` SHALL 使既有 mgh-init 行为
**字节级一致**(产物路径、stdout、退出码不变)。

#### Scenario: 默认 --run-root 等价旧行为

- **WHEN** 分别以 `--target <t>`(不传 `--run-root`)与 `--target <t> --run-root .mgh-init` 调用
  `resume_state.py`(及 `write_runconfig.py`)
- **THEN** 两者读写的运行目录均为 `<t>/.mgh-init`,stdout 与退出码逐字一致

#### Scenario: --run-root 命名目录被使用

- **WHEN** 以 `--target <t> --run-root .mgh-ut-init` 调用 `write_runconfig.py`
- **THEN** `run_config.json` 写入 `<t>/.mgh-ut-init/run_config.json`;`resume_state.py --target <t>
  --run-root .mgh-ut-init` 读同一目录

#### Scenario: --init-dir 仍优先于 --run-root

- **WHEN** 同时传 `--init-dir <abs>` 与 `--run-root <name>` 调用任一脚本
- **THEN** 运行目录解析为 `--init-dir` 的全路径,`--run-root` 被忽略(无歧义)

#### Scenario: --help 与契约 lint 覆盖新 flag

- **WHEN** 运行 `py resume_state.py --help` / `py write_runconfig.py --help` 与 `tools/check_contracts.py`
- **THEN** `--run-root` 列于两者 `--help`;双壳中出现的 `resume_state.py`/`write_runconfig.py` 调用 flag
  均在对应 `--help` 中存在

### Requirement: 行为保持——既有回归测全绿 + mgh-init 字节级一致

本变更 SHALL 不改变 mgh-init 流水线的可观测行为。既有回归测全绿;契约 lint、分发纯净性 lint、零依赖 AST
扫描 SHALL 通过。新增/改动脚本 MUST 仅用 Python ≥3.10 标准库。任一 `.md`/脚本改动 SHALL bump 对应版本号。

#### Scenario: 既有回归测与 lint 全绿

- **WHEN** 运行既有 `tests/` 套件 + 三项 lint(契约 / 分发纯净 / 零依赖)
- **THEN** 全部通过,无新增失败

#### Scenario: mgh-init 流水线产物路径未漂移

- **WHEN** 默认调用 `resume_state.py`/`write_runconfig.py`(不传 `--run-root`)
- **THEN** 运行目录、`run_config.json` 路径、stdout schema 与变更前逐字一致(无回归)

### Requirement: core/scripts 叶脚本编译零告警(stderr 纯净)

`core/scripts/` 全部叶脚本 SHALL 在 `py_compile` 编译(即任何 import/直接执行的第一步)下
**零 SyntaxWarning**:模块 docstring 与一切字符串字面量 SHALL NOT 含无效转义序列(如
反斜杠+反引号)——docstring 中的正则/路径示例含反斜杠时 SHALL 用 raw string 或双反斜杠
表达。理由:叶脚本被编排器/re-export 脚本 import 链加载(如 `resume_state.py` →
`list_clusters.collect_canonical_ids`),一处 `SyntaxWarning` 即经 stderr 污染每次调用的
诊断面,弱模型易把告警误读为脚本故障;stderr 与 stdout 的严格分流契约(R5.3b)隐含
「stderr 只含预期诊断,不含编译期噪声」。回归单测 SHALL 全量编译 `core/scripts/*.py` 并
断言捕获不到任何 Warning(fail-loud,退出码非 0)。

#### Scenario: list_clusters docstring 不再触发 SyntaxWarning
- **WHEN** `py_compile.compile("core/scripts/list_clusters.py")` 且 warnings 置为 always
- **THEN** 不捕获任何 SyntaxWarning(现行 `` `\` `` 非法转义已消除)

#### Scenario: import 链的 stderr 纯净
- **WHEN** 子进程执行 `resume_state.py --target <运行目录>`(其 import 链加载
  `list_clusters`)
- **THEN** stderr 不含 `SyntaxWarning: invalid escape sequence`(进度输出正常,不受影响)

#### Scenario: 全量零告警回归测防回归
- **WHEN** 运行零告警回归单测(全量编译 `core/scripts/*.py`)
- **THEN** 任一脚本产生 Warning → 测试 fail-loud 列出脚本名与告警消息
