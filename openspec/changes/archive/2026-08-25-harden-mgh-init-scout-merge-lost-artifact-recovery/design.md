# Design: harden-mgh-init-scout-merge-lost-artifact-recovery

## Context

磁盘真值恢复(R5.4)是 `/mgh-init` 压缩 / crash / 新会话后的唯一恢复机制,`resume_state.py` 是编排器
「我在哪 / 下一步」的单一出口。真实测试环境暴露的失败形态:scout 层**已跑完并入**
(`checkpoints/scout/merge.json.done` 在、`controls_candidates.json::provenance.scout_merged=760`、
`clusters.json` 830 簇已含 scout 簇),但中间凭证 `scout_candidates.json` 丢失。此时 step 机本身
**能**正确恢复(`_scout_step` 返回 step=scout + spawn init-scout-merge),但三个伴随缺陷让恢复不安全:
① `_scout_step` 的 note 把「凭证缺」与「merge marker 缺」并成一句(实际 merge marker 在),弱模型可能据此
误判「scout 没真正合并」;② `resume_state.py --check` 对该状态**静默通过**(缺镜像违例);③ 契约文档
`core/contracts/init/resume-state.md` 宣称 fold-in「再跑幂等、安全」——实际重跑非幂等(同文件重跑把
`scout_merged` 覆盖为 0 并触发虚假召回缺口披露,漂移重生成文件重跑重复追加候选/簇)。动机详见
`proposal.md`;行为要求见两份 delta spec(`resume-step-discipline` / `scout-tier-gate`)。

关键事实依据(均已核实源码):
- `_foldin_done` 判定 = `controls_candidates.json::provenance` dict 含 `scout_merged` 键;该键存在 ⟺
  fold-in 已跑(即便并入 0 也设)。
- `scout_complete()` 谓词要求 `scout_candidates.json` 存在(else False)→ 凭证缺 → `resume_state`
  走 `_scout_step`、`list_clusters` 触发 scout-incomplete-gate 退出码 2 拦 T1。
- **fold-in 后无任何下游消费 `scout_candidates.json` 的内容**(grep 全仓:消费方为 `scout_complete`/
  `--check` 的存在性判定、fold-in 时 `merge_scout` 的读取、`merge_scout --check` 校验)——凭证缺时该文件
  的**存在性**是完成谓词的唯一所需,内容不参与后续任何计算;故 `init-scout-merge` 重生成的内容
  漂移无害。

## Goals / Non-Goals

**Goals:**
- `_scout_step` 对「reader 全终态但凭证缺」按 merge/fold-in 三子状态给精确 note + 恢复配方。
- `--check` 增「fold-in 已跑 + 凭证缺」镜像违例(退出码 2),与既有「凭证在但 merge marker 缺」对称。
- 恢复路径收敛为 `init-scout-merge` 唯一路径(诚实重生成;拒绝占位凭证)。
- scout 步纪律 nevers 增「NEVER 重跑 fold-in」反例;契约文档纠正「重跑幂等安全」错误主张。

**Non-Goals:**
- 不把 fold-in 改成幂等(正确不变量是「已跑则不重跑」,不是「重跑无害」;改幂等会改动 provenance
  语义且超出本 change)。
- 不自动执行恢复(编排器 MUST 按 `resume_state` next_action 走,不替它做决定)。
- **不提供确定性占位凭证重生**(`candidates:[]` 占位与已并入实体不符 = 伪造;宁花 LLM token 走
  `init-scout-merge` 诚实重生成)。
- 不改命令壳(`mgh-init.md`)——恢复配方经 note / `--check` violation 下发,壳受 R5.6 token 预算
  约束,不为此扩容。
- 不改 discover / scout reader / fold-in / T1–T4 正常执行路径。

## Decisions

### D1 — `_scout_step` note 按三子状态分支

`_scout_step` 在「all reader batches terminal 且 `scout_candidates.json` 缺」时,按
`_scout_merge_done()` 与 `_scout_merged_value()` 三分支写 note:
- merge marker 缺 → 「合并未跑,regen 后 fold-in 待跑」;
- merge marker 在 + `scout_merged` 在 → 「fold-in 已跑(scout_merged=N)、regen 仅作完成凭证(无下游
  消费、漂移无害)、NEVER 重跑 merge_scout.py fold-in、regen 后 step=t1」;
- merge marker 在 + `scout_merged` 缺 → 「凭证与 fold-in 均欠,regen 后 fold-in 待跑」。
next_action 三支恒为 spawn `init-scout-merge`(诚实重生成)。
**理由**:现 single note 的「scout_candidates.json / merge marker absent」在 merge marker 实际在时
是**误导**——弱模型读到会以为「scout 未真正合并」,进而(配合契约文档的错误主张)线性重跑 fold-in。
分支后 note 与磁盘事实逐字对齐,fold-in 已跑的情况明示「重跑有害」。
**备选**:保持 single note 但补一句「若 merge marker 在则 fold-in 已跑」——仍把两态混在一句,弱模型
区分成本高;弃。

### D2 — `--check` 增镜像违例(退出码 2)

`check()` 在 scout 启用时增一条:merge marker 在 **且** `_foldin_done` 在 **且** `scout_candidates.json`
缺 → violation(退出码 2),文本含 `init-scout-merge` regen 配方 + NEVER 重跑 fold-in。
**理由**:R5.9 哲学 = 不带着破损产物继续。正常流里 merge marker 与凭证由 init-scout-merge **同时**落地,
「marker + fold-in 在而凭证缺」是真实异常;既有「凭证在但 marker 缺」已是违例,镜像方向也应 fail-loud。
恢复后(凭证重新在盘)该违例自然清除,非死路。
**备选**:仅 advisory note——正是当前「静默通过」的缺陷本身;弃。

### D3 — 恢复路径收敛为 `init-scout-merge` 唯一路径(拒绝占位凭证)

凭证缺失时的恢复 = 重跑 `init-scout-merge`(LLM 诚实重生成),`_scout_step` next_action 已天然指向
它;note / `--check` violation 只负责把「为何需要 regen、跑完 resume_state 会报什么、NEVER 做什么」
讲清。**不做**确定性占位凭证(`candidates:[]` 占位)。
**理由**:「fold-in 后凭证内容无下游消费」虽已核实(存在性即完成谓词全部所需),但**存在性 ≠ 内容
诚实**——一个 `candidates:[]` 的占位文件与 `controls_candidates.json` 里真实并入的 760 相悖,若被
未来任何下游误读为空,会静默丢召回信号。维护者明确选择**宁花 token 重跑 LLM**(全量 fan-in,真实
场景 1068 批、可能触发 plan_aggregate map-reduce),换取产物溯源诚实;恢复是低频事件,单次成本可
接受。仓内「不伪造产物、verify-before-trust」纪律优先于零 token 的便利。
**备选**:(a) `--regen-scout-credential` 占位重生——零 token 但伪造产物;用户明确否决;弃。
(b) 操作者手工写空文件——R5.2 禁 ad-hoc 写,且无门控;弃。(c) 把 fold-in 改幂等——改 provenance
语义、非本 change 目标;弃。

### D4 — 纪律表 nevers + 契约文档纠正(双防线持久化)

`discipline_core.py` scout 步 `nevers` 增「NEVER 重跑 `merge_scout.py` fold-in(`scout_merged` 已设时;
重跑非幂等——同文件归零、漂移文件重复追加)」,随 `discipline_reminders[]` 在压缩后从磁盘重派生。
`core/contracts/init/resume-state.md` 纠正「该键存在 ⟺ fold-in 已跑(再跑幂等、安全)」为「scout_merged
在 ⟺ fold-in 已跑;重跑非幂等;resume_state 在 scout_merged 存在时 NEVER 建议重跑 fold-in」。
**理由**:动态 note(D1)只覆盖「凭证缺」这一瞬态;纪律 nevers 是**静态**常驻防线(压缩后仍随
`discipline_reminders[]` 恢复),覆盖「凭证在但编排器想重跑 fold-in」的其它诱因。契约文档的
「幂等安全」是**主动招致重跑**的错误主张,纠正属行为级变更而非润色。
**备选**:只改动态 note 不动契约——弱模型读契约仍以为重跑安全;弃。

### D5 — 不改命令壳

`releases/claude-code/commands/mgh-init.md` 与 `releases/opencode/command/mgh-init.md` 的
Resume 段已指向 `resume_state.py`(第一步),恢复配方由 note / `--check` violation 承载。新 flag 不进
壳、不进 `discipline_reminders` 的 path_recipes(它是操作者修复动作,不是编排器步骤纪律)。
**理由**:R5.1 只断言壳内出现过的 `*.py --flag` 存在(反方向不强制);壳受 R5.6 token 硬预算,不加
非承重行。若后续需要操作者直接可见,可单独立 doc 任务。

## Risks / Trade-offs

- [恢复成本 = 一次 `init-scout-merge` LLM 重跑(真实场景 1068 批,可能触发 plan_aggregate
  map-reduce)] → 低频事件 + 诚实重生成的价值优先(D3 用户明确选择);note 明示重生成内容漂移无害
  (无下游消费),编排器不因「与 760 对不上」二次折返。
- [弱模型无视 note 仍线性重跑 fold-in] → 三层防线:① 动态 note(D1);② 静态纪律 nevers(D4);
  ③ `--check` fail-loud(D2)。且 step 机本身在 `scout_merged` 在时经 `scout_complete()` 直接跳过
  `_scout_step` 的 fold-in 分支(永不重派),契约不再鼓励重跑。
- [`--check` 新违例误伤合法 in-flight run] → 该状态(merge marker + fold-in 在但凭证缺)在正常流
  不可能出现(两者同时落地);出现即异常,正是 fail-loud 的用途;recipe 给出 `init-scout-merge`
  regen 恢复径,非死路。

## Migration Plan

纯增量、无数据迁移。部署:apply 后 `core/scripts/resume_state.py` / `discipline_core.py` 就地生效,
目标项目重跑 `install.sh` 刷新镜像。回滚:还原 `.py` + 契约文档改动;改动均为增量、无持久 schema
依赖,回滚无残留。存量「凭证缺 + fold-in 已跑」的 run(如测试环境):apply 后 `--check` 首次
即暴露镜像违例 → 按 recipe 经 `init-scout-merge` 恢复即可。

## Open Questions

无。
