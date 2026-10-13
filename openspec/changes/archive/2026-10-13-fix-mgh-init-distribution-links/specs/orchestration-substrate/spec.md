# fix-mgh-init-distribution-links — orchestration-substrate delta

## MODIFIED Requirements

### Requirement: 单一共享 orchestrator-discipline fragment 持有宿主无关纪律正文

SHALL 存在唯一 fragment `core/prompts/fragments/orchestrator-discipline.md`,持有当前在各壳内联的
**宿主无关**编排纪律正文,至少覆盖:① 编排器 = 宿主 agent(非物化脚本);② 三条 `NEVER`
硬边界(`Write` 任何脚本扩展名编排器/微脚本、经 `Bash` 向解释器**内联喂代码**——含 `-c`、解释器后跟
独占 `-`(heredoc 经 stdin)与 here-string **全部形态**——去内省/重派生产物、`Read`
叶子 `.py` 源码进上下文);③ implementation-intention recipe(需工作清单/瞄结构/派生量/单单元输出路径/
当前步骤 → 各自合法出口,`NEVER` 内联代码);④ fan-out 刚性三元组(`[输入产物::字段] → script/subagent →
[输出产物::字段]`,输出路径 = 枚举脚本 stdout 的 `checkpoint_path`/`rule_path`,绝对、逐字透传);⑤
`.failed` = 终态(resume 不重派;crash 无 ack → 仍 pending → 重派);⑥ 长跑确定性 Bash per-call
`timeout` 纪律 + opencode env-var 可靠性边界;⑦ **编排器自身禁止向系统临时目录(`$env:TEMP` / `%TEMP%` /
`/tmp` / `TMPDIR`)写中间文件,stdout MUST 从 Bash 工具返回值直接消费**。fragment 正文 SHALL **泛化**
(用「该命令的 `list_*` 枚举脚本」/「resume-state 脚本」等抽象名词),**不**绑定 init 专属脚本名/产物名
(那些留在各壳 stage 流)。fragment 是分发产物,SHALL 通过分发纯净性 lint:无研发铁律编号、失败/设计 ID、
openspec 变更夹名、dev-meta 措辞。**头注的命令覆盖状态 SHALL 随发布事实维护**:头注中「今日已发布 /
后续待发布」类列举(`… today; … to come`)SHALL 与命令族的实发布状态一致——已发布命令 NEVER 留在
`to come` 清单里(失实的发布状态与死链同性质:目标读者会据其判断命令可用性);每发布一个新命令,
该头注随发布 change 一并更新。

#### Scenario: fragment 文件存在且被分发镜像

- **WHEN** 审阅 `core/prompts/fragments/` 目录与 `install.sh` 镜像规则
- **THEN** `orchestrator-discipline.md` 存在;`install.sh` 镜像 `core/` → `.claude/mgh-core/` 时该
  fragment 一并落入 `.claude/mgh-core/prompts/fragments/orchestrator-discipline.md`

#### Scenario: fragment 持有三条 NEVER 硬边界、fan-out 三元组与 temp-file 禁令

- **WHEN** 审阅 `orchestrator-discipline.md` 正文
- **THEN** 其显式包含三条 `NEVER` 边界(其中内联代码边界**逐字覆盖 `-c` / 独占 `-` heredoc /
  here-string 三形态**)+ fan-out 刚性三元组 + `.failed` 终态声明 + per-call `timeout`
  纪律 + **stdout 直消费 recipe(含 `NEVER` 向 `$env:TEMP`/`%TEMP%`/`/tmp`/`TMPDIR` 写中间文件)**,
  且用抽象名词指代脚本(不出现 `list_clusters.py`/`resume_state.py` 等 init 专属名)

#### Scenario: fragment 通过分发纯净性 lint

- **WHEN** 运行 `tools/check_distributed_purity.py`
- **THEN** `orchestration-discipline.md` 不含 `R5.x`/`FDn`/`Dn`/变更夹名/`承 R5`/`范式锚点` 等 dev-meta
  (操作性语义如 `--check`/退出码 2/`NEVER` 保留)

#### Scenario: header release-state list matches reality

- **WHEN** 审阅 fragment 头注的命令覆盖列举(mgh-init 已发布;mgh-ut-init 已随其 install 面发布)
- **THEN** 头注不再把已发布命令列入「to come」;列举只保留确实未发布的条目(或移除整个
  「to come」段),目标读者据头注判断的命令可用性与实况一致
