## ADDED Requirements

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

## MODIFIED Requirements

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
