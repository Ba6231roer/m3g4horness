# Tasks: harden-mgh-init-scout-merge-lost-artifact-recovery

> 规格:两份 delta spec(`resume-step-discipline` / `scout-tier-gate`)。设计:design.md(D1–D5)。
> 恢复路径**唯一** = `init-scout-merge` 诚实重生成(拒绝占位凭证,用户已决)。所有改动以
> `core/scripts/` 源码 / 契约文档为基准;行为要求见 spec,实现见 design。

## 1. `_scout_step` note 三子状态分支(D1)

- [x] 1.1 在 `core/scripts/resume_state.py` `_scout_step`(现 line ~512「scout_candidates.json / merge marker absent」分支)中,把「all reader batches done 但 `scout_candidates.json` 缺」按
  `_scout_merge_done(init_dir)` 与 `_scout_merged_value(candidates)` 三分支写 note,next_action 三支恒为
  spawn `init-scout-merge`:
  - merge marker 缺 → note「合并未跑,regen 凭证后 fold-in 待跑」;
  - merge marker 在 + `scout_merged` 在 → note「fold-in 已跑(scout_merged=N)、regen 仅作完成凭证(无下游消费、LLM 漂移无害)、NEVER 重跑 `merge_scout.py` fold-in、regen 后 `resume_state` 重派生 `step=t1`」;
  - merge marker 在 + `scout_merged` 缺 → note「凭证与 fold-in 均欠,regen 后 fold-in 待跑」。
- [x] 1.2 确认 note 不再于 merge marker 实际在盘时打印「merge marker absent」字样(逐字对齐磁盘事实)。

## 2. `--check` 镜像违例(D2)

- [x] 2.1 在 `core/scripts/resume_state.py` `check()` scout 启用块(现 line ~584–611)增违例:merge marker 在
  **且** `_foldin_done` 在 **且** `scout_candidates.json` 缺 → `{"issue": "checkpoints/scout/merge.json.done + fold-in done but scout_candidates.json missing — regen via init-scout-merge; NEVER re-run merge_scout.py fold-in"}`。
- [x] 2.2 确认该违例走既有退出码 2 路径(与「凭证在但 merge marker 缺」对称);恢复(凭证重新在盘)后 `--check` 通过。

## 3. scout 步纪律 nevers(D4)

- [x] 3.1 `core/scripts/discipline_core.py` scout 步 `nevers` 增「NEVER 重跑 `merge_scout.py` fold-in
  (`controls_candidates.json::provenance.scout_merged` 已设时;重跑非幂等——同文件重跑把 `scout_merged` 归零,漂移文件重跑重复追加候选/簇)」。
- [x] 3.2 确认 `resume_state.py` stdout `discipline_reminders[]` 与 `list_steps.py --step scout` stdout
  `discipline` 对该反例逐字一致(共享纪律表单一真相,D5 既有断言覆盖)。

## 4. 契约文档纠正

- [x] 4.1 `core/contracts/init/resume-state.md` scout 子状态段(现 line ~85–90)增三子状态 note 分支说明;
  fold-in 检测段(现 line ~92–93)**删除/纠正**「该键存在 ⟺ fold-in 已跑(再跑幂等、安全)」→「`scout_merged`
  在 ⟺ fold-in 已跑;重跑非幂等(同文件归零、漂移文件重复追加);resume_state 在 `scout_merged` 存在时
  MUST NOT 建议重跑 `merge_scout.py` fold-in;凭证缺 → 经 `init-scout-merge` 重生成(唯一恢复路径)」。
- [x] 4.2 `core/contracts/init/resume-state.md` `--check` 段(现 line ~102–116)补镜像违例(2.1)说明。

## 5. 回归测试

- [x] 5.1 `tests/test_resume_state.py` 增三子状态 note 用例:`_scout_step` 在 merge marker 缺 / fold-in 已跑 /
  fold-in 未跑三种磁盘状态下 note 文本分别匹配预期(含「merge marker absent」不再误报)。
- [x] 5.2 `tests/test_resume_state.py` 增 `--check` 镜像违例用例:构造「merge marker + fold-in 在 + 凭证缺」
  → 退出码 2 + violation 含 regen 配方;凭证恢复后 `--check` 退出码 0。
- [x] 5.3 `tests/test_resume_state.py` 增恢复路径用例:构造「merge marker + fold-in 在 + 凭证缺」夹具 →
  模拟 `init-scout-merge` regen(写回一个 `scout_candidates.json`)→ `scout_complete()` 通过 +
  `resume_state` 重派生 `step=t1`、**不进入** `_scout_step` fold-in 分支(不重派 fold-in)。

## 6. 版本、自检与 lint(承 R5.8)

- [x] 6.1 `VERSION` bump(0.1.32 → 0.1.33,承 R5.8「任何 `.md`/脚本改动 bump 版本号」)+ `CHANGELOG.md`
  `[Unreleased]` 增条目「harden: scout 合并凭证丢失的恢复路径(精确 note + `--check` 镜像违例 +
  fold-in 重跑反例 + 契约纠正)」。
- [x] 6.2 `py tests/test_resume_state.py` 全绿(51 tests,含既有用例不回归)。
- [x] 6.3 `py tools/check_contracts.py` 通过(254 flags,既有契约不破坏)。
- [x] 6.4 `py tools/check_distributed_purity.py` 通过——本 change 的契约文档改动(含
  `core/contracts/init/resume-state.md`)不引入任何 dev-id / R5.x 引用;lint 当前唯一 violation 是
  另一 in-flight change `add-mgh-init-stage-outputs-doc` 的未跟踪产物 `docs/man/mgh-init-artifacts.md:3`,
  与本 change 无关(见会话总结)。
- [x] 6.5 手工夹具验证:构造「merge marker + fold-in 在 + 凭证缺」的 `.mgh-init/` 夹具 →
  `resume_state.py --check` 退出码 2(镜像违例含 regen 配方)→ 写回 `scout_candidates.json`(模拟
  `init-scout-merge` regen)→ `--check` 退出码 0 → `resume_state.py` stdout `step=t1`(tiers.scout.merged=760);
  逐条对照 `scout-tier-gate` / `resume-step-discipline` spec 场景通过。
