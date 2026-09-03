# Proposal: harden-mgh-init-scout-merge-lost-artifact-recovery

> **人话序**
> **现象**:真实大仓跑 `/mgh-init` 到 scout 层,scout 其实**已经跑完并并入**
> (`checkpoints/scout/merge.json.done` 在、`controls_candidates.json::provenance.scout_merged=760`、
> `clusters.json` 830 簇已含 scout 簇),但中间凭证文件 `scout_candidates.json` 丢了。
> 此时 `resume_state.py` 报 `step=scout`,note 却写「scout_candidates.json / merge marker absent」
> (merge marker 明明在),`resume_state.py --check` 还判定 OK——编排器 / 维护者拿到的是一份
> **误导性状态**。
> **根因**:`_scout_step` 把「凭证缺」与「merge marker 缺」并成一个含糊 note,不区分 fold-in
> 是否已跑;`--check` 缺「fold-in 已跑但凭证缺」这一镜像违例;契约文档还错误宣称 fold-in
> 「再跑幂等、安全」——实际重跑**非幂等**(同文件重跑把 `scout_merged` 归零,漂移文件重跑
> 重复追加候选/簇)。
> **改什么**:① `_scout_step` note 按 merge/fold-in 子状态给精确恢复配方(凭证缺→regen;fold-in
> 已跑→NEVER 重跑 `merge_scout.py`);② `--check` 增「fold-in 已跑 + 凭证缺」违例(退出码 2);
> ③ 修正契约文档的错误主张 + scout 步纪律 nevers 补反例。
> **怎么验证**:构造「merge marker + fold-in 在 + 凭证缺」态 → `--check` 退出码 2 且 recipe 精确;
> `_scout_step` note 对三子状态分别给出正确指引;经 `init-scout-merge` regen 凭证后 `--check` 过、
> `resume_state` 重派生 `step=t1`;单测覆盖。

## Why

磁盘真值恢复(R5.4)是 `/mgh-init` 在压缩 / crash / 新会话后唯一的恢复机制,而它的第一步就是
读 `resume_state.py` 的输出。但当 scout 合并的**完成凭证** `scout_candidates.json` 在 fold-in **已经
跑完之后**丢失时,当前代码会:报一条误导 note(「merge marker absent」但 marker 在)、`--check`
静默通过(无镜像违例)、且契约文档 `core/contracts/init/resume-state.md` 宣称 fold-in「再跑幂等、
安全」——直接诱使一个 resume 的编排器重跑 fold-in,而重跑非幂等:同文件重跑把
`provenance.scout_merged` 从 760 覆盖为 0(抹掉并入证据 + 触发虚假召回缺口披露),漂移文件重跑则
重复追加候选与簇。这个状态在真实测试环境实际发生过(scout 1068 批终态、fold-in 并入 760、830
簇、仅中间凭证丢失)。恢复路径必须精确检测该状态并导向安全、确定性的修复。

## What Changes

- **resume_state `_scout_step` note 精确化**:「reader 批全终态但 `scout_candidates.json` 缺」按
  merge marker + fold-in 子状态分三支,给精确恢复配方:
  - merge marker 缺 → 合并未跑:regen 凭证后 fold-in 待跑;
  - merge marker 在 + `provenance.scout_merged` 在(**本次失败形态**)→ fold-in 已跑:note MUST 载明
    「`scout_merged=N` 已并入、regen 内容仅作完成凭证(无下游消费,漂移无害)、NEVER 重跑
    `merge_scout.py` fold-in、regen 后 `resume_state` 重派生 `step=t1`」;
  - merge marker 在 + `scout_merged` 缺 → 凭证与 fold-in 均欠:regen 后 fold-in 待跑。
- **resume_state `--check` 增镜像违例**:「`merge.json.done` 在 + `scout_merged` 在 + `scout_candidates.json`
  缺」(scout 启用)报违例退出码 2,recipe 指向 `init-scout-merge` 诚实 regen + NEVER 重跑 fold-in。
  与既有「凭证在但 merge marker 缺」违例互为镜像。
- **discipline_core scout 步 nevers 增反例**:「NEVER 重跑 `merge_scout.py` fold-in(`provenance.scout_merged`
  已设时;重跑非幂等)」进 `discipline_reminders[]`。
- **契约文档纠正**:`core/contracts/init/resume-state.md` 删除「该键存在 ⟺ fold-in 已跑(再跑幂等、
  安全)」的错误主张,改为「`scout_merged` 在 ⟺ fold-in 已跑;resume_state 在 `scout_merged` 存在时
  NEVER 建议重跑 fold-in;重跑非幂等」。
- **回归测试**:`tests/test_resume_state.py` 覆盖三子状态 note、`--check` 镜像违例、regen
  (`init-scout-merge`)后 `step=t1` 的恢复路径。

无 shell(命令壳)改动:恢复配方经 note / `--check` violation 交给编排器与维护者,不进壳。无
install 分发面变化(改的都是已分发脚本与契约文档)。

## Capabilities

### New Capabilities
<!-- 无:恢复行为落进既有 resume/闸门能力,不新建 capability。 -->

### Modified Capabilities
- `resume-step-discipline`: resume_state 对「scout 合并凭证丢失」子状态给出精确 note + 恢复配方
  (三子状态区分、NEVER 重跑 fold-in 反例),以及契约文档对「fold-in 重跑安全」错误主张的纠正。
- `scout-tier-gate`: `--check` 增「fold-in 已跑但 `scout_candidates.json` 缺」镜像违例(recipe 指向
  `init-scout-merge` regen + NEVER 重跑 fold-in)。

## Impact

- **代码**:`core/scripts/resume_state.py`(`_scout_step` note 三分支 + `--check` 镜像违例);
  `core/scripts/discipline_core.py`(scout 步 nevers 增反例)。
- **契约文档**:`core/contracts/init/resume-state.md`(纠正 fold-in 重跑安全主张 + 补子状态 / 违例
  契约说明)。
- **测试**:`tests/test_resume_state.py` 增三子状态 note / `--check` 镜像违例 / regen 后 `step=t1`
  恢复路径用例。
- **行为兼容**:`--check` 新增违例只在「fold-in 已跑 + 凭证缺」这一此前静默通过的状态上 fail-loud;
  既有 note / stdout 字段形状不变;无新增 CLI flag。
- **风险**:低。所有改动是恢复路径的检测 + 指引增强;不触碰 discover/scout reader/fold-in/T1–T4
  的正常执行路径。恢复成本 = 一次 `init-scout-merge` LLM 重跑(刻意选择:诚实重生成,宁花 token 不做
  占位凭证)。
