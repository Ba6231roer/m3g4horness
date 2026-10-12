## ADDED Requirements

### Requirement: 守卫推荐的合法出口 MUST 在命令壳步骤级配方中先验可见

运行时守卫被触发时 recipe 里推荐的**每个** sanctioned primitive(工作清单枚举脚本、产物内省脚本、
产出者 stdout 字段等),SHALL 在对应 `mgh-*` 命令壳(双端同构)的**步骤级配方**中至少出现一次
**可照抄的确切调用形态**(脚本名 + flag 逐字镜像其 `--help` 契约)——编排器对合法出口的知情
SHALL NOT 依赖「先违例被拦、再从报错里学习」。正例基线:sra/srr 壳各引用产物内省脚本 5 次;
反例基线(本 change 修复对象):某壳 0 次引用该脚本,而守卫 recipe 恰指向它。

强制面:该对应关系 SHALL 以 `/mgh-sdr` 双壳为首个落地面(step 1/2 补产物内省配方,见
`security-design-review`),并 SHALL 由一条确定性检查兜底(在既有契约 lint 的壳-脚本提取面上追加:
守卫 recipe 文本中出现的脚本名集合 ⊆ 该域命令壳出现的脚本名集合 ∪ 共享 fragment 出现的脚本名
集合;缺项 fail-loud 退出码 2)。

#### Scenario: 守卫 recipe 推荐即壳内已教

- **WHEN** 从守卫的 per-domain recipe 文本提取被推荐脚本名(如产物内省脚本、各域 `list_*`),与该域
  双端命令壳 + 共享 fragment 中出现的脚本名比对
- **THEN** 前者为后者子集,退出码 0;若守卫新推荐一个壳内没有的脚本,检查退出码 2 并列出(壳, 缺失
  脚本)对

#### Scenario: 被拦前已知情(sdr step 1 内省)

- **WHEN** 编排器在 `/mgh-sdr` step 1 后需要查看 `context.json` 的某嵌套字段,按壳配方执行
  `describe_artifact.py --in <abs> --field external_repos.0.summary_path`
- **THEN** 该调用一次成功(配方形态与脚本 `--help` 契约逐字一致),编排器全程未产生内联代码形态

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
openspec 变更夹名、dev-meta 措辞。

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
