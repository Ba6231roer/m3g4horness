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

#### Scenario: 两壳引用同一 fragment 而非内联

- **WHEN** 审阅 `releases/claude-code/commands/mgh-init.md` 与 `releases/opencode/command/mgh-init.md`
- **THEN** 两壳均含 `REQUIRED SUB-SKILL: Use orchestrator-discipline`(或等价标记);且均**不**再内联
  implementation-intention recipe 详述块与三条 `NEVER` 边界详述块(该正文只在 fragment 里)

#### Scenario: init 专属 stage 流与调用行留在壳内

- **WHEN** 审阅两壳的 stage 流 / Deterministic invocation 段
- **THEN** 确切脚本名(`discover_controls.py`/`list_clusters.py`/`list_scout_batches.py`/`list_rule_jobs.py`/
  `resume_state.py` 等)、确切 flag、产物路径、`MGH_INIT_ACTIVE`/`.mgh-init/.active` 哨兵步骤仍在壳内
  (未随纪律正文一并移出)

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
