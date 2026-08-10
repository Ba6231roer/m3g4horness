# Spec: orchestration-substrate

## Purpose

确立**宿主无关的共享编排纪律基座**:把 `mgh-init`(及未来 `mgh-ut-init` / `mgh-ut`)壳里重复内联的
通用编排纪律正文(orchestrator = 宿主 agent、三条 `NEVER` 硬边界、fan-out 刚性三元组、
implementation-intention recipe、resume-from-disk recipe、`.failed` 终态、长跑 Bash per-call `timeout`)
抽成单一 fragment,壳经 R5.6 认可的 `REQUIRED SUB-SKILL` 间接引用;并把 `resume_state.py` /
`write_runconfig.py` 的运行目录名参数化为 `--run-root`。本能力由 change `extract-shared-substrate`
建立(P0,`task.260805.md` 第六节),**行为保持**:mgh-init 是首个消费方,sast 不在本能力范围
(其纪律由 `sast-orchestration-discipline` 治理)。

## ADDED Requirements

### Requirement: 单一共享 orchestrator-discipline fragment 持有宿主无关纪律正文

SHALL 存在唯一 fragment `core/prompts/fragments/orchestrator-discipline.md`,持有当前在 `mgh-init`
两壳内联的**宿主无关**编排纪律正文,至少覆盖:① 编排器 = 宿主 agent(非物化脚本);② 三条 `NEVER`
硬边界(`Write` 任何脚本扩展名编排器/微脚本、经 `Bash` `py -c`/`python -c` 内省/重派生产物、`Read`
叶子 `.py` 源码进上下文);③ implementation-intention recipe(需工作清单/瞄结构/派生量/单单元输出路径/
当前步骤 → 各自合法出口,`NEVER py -c`);④ fan-out 刚性三元组(`[输入产物::字段] → script/subagent →
[输出产物::字段]`,输出路径 = 枚举脚本 stdout 的 `checkpoint_path`/`rule_path`,绝对、逐字透传);⑤
`.failed` = 终态(resume 不重派;crash 无 ack → 仍 pending → 重派);⑥ 长跑确定性 Bash per-call
`timeout` 纪律 + opencode env-var 可靠性边界。fragment 正文 SHALL **泛化**(用「该命令的 `list_*` 枚举
脚本」/「resume-state 脚本」等抽象名词),**不**绑定 init 专属脚本名/产物名(那些留在各壳 stage 流)。
fragment 是分发产物,SHALL 通过 `tools/check_distributed_purity.py`(承 R5.10):无研发铁律编号
(`R5.x`/`R3`)、失败/设计 ID(`FDn`/`Dn`)、openspec 变更夹名、dev-meta 措辞(`承/兑现 R5.x`、`范式锚点`)。

#### Scenario: fragment 文件存在且被分发镜像

- **WHEN** 审阅 `core/prompts/fragments/` 目录与 `install.sh` 镜像规则
- **THEN** `orchestrator-discipline.md` 存在;`install.sh` 镜像 `core/` → `.claude/mgh-core/` 时该
  fragment 一并落入 `.claude/mgh-core/prompts/fragments/orchestrator-discipline.md`

#### Scenario: fragment 持有三条 NEVER 硬边界与 fan-out 三元组

- **WHEN** 审阅 `orchestrator-discipline.md` 正文
- **THEN** 其显式包含三条 `NEVER` 边界 + fan-out 刚性三元组 + `.failed` 终态声明 + per-call `timeout`
  纪律,且用抽象名词指代脚本(不出现 `list_clusters.py`/`resume_state.py` 等 init 专属名)

#### Scenario: fragment 通过分发纯净性 lint

- **WHEN** 运行 `tools/check_distributed_purity.py`
- **THEN** `orchestration-discipline.md` 不含 `R5.x`/`FDn`/`Dn`/`(add|fix|harden|improve)-mgh-*` 变更夹名/
  `承 R5`/`范式锚点` 等 dev-meta(操作性语义如 `--check`/退出码 2/`NEVER` 保留)

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
`<target>/<name>` > 默认 `<target>/.mgh-init`。`--help` 即 CLI 契约面(承 R5.1);`tools/check_contracts.py`
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

本变更 SHALL 不改变 mgh-init 流水线的可观测行为。既有回归测(`tests/test_resume_state.py`、
`test_write_runconfig.py`、`test_init_runtime.py`、`test_init_ack_contract.py`、`test_distributed_md_purity.py`、
`test_opencode_hook_parity.py`、`test_deterministic.py` 等)SHALL 全绿;`tools/check_contracts.py`、
`tools/check_distributed_purity.py`、零依赖 AST 扫描 SHALL 通过。新增/改动脚本 MUST 仅用 Python ≥3.10
标准库(承 R2)。任一 `.md`/脚本改动 SHALL bump 对应版本号(承 R5.8)。

#### Scenario: 既有回归测与 lint 全绿

- **WHEN** 运行既有 `tests/` 套件 + 三项 lint(契约 / 分发纯净 / 零依赖)
- **THEN** 全部通过,无新增失败

#### Scenario: mgh-init 流水线产物路径未漂移

- **WHEN** 默认调用 `resume_state.py`/`write_runconfig.py`(不传 `--run-root`)
- **THEN** 运行目录、`run_config.json` 路径、stdout schema 与变更前逐字一致(无回归)
