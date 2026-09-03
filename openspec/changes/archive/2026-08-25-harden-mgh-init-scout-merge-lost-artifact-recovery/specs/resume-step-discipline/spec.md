## ADDED Requirements

### Requirement: scout 合并凭证丢失子状态的精确恢复指引

当 scout 启用、`scout_plan.json::batches[]` 非空、scout readers 全终态(`.done` + `.failed` ≥ total)但
`scout_candidates.json` **缺失**时,`resume_state.py` SHALL 按 merge marker 与 fold-in 子状态区分输出
note 与恢复配方,不得把「凭证缺」与「merge marker 缺」并成一个含糊状态:
- **merge marker 缺**(`checkpoints/scout/merge.json.done` 不在)→ 合并未跑:note SHALL 载明
  「regen `scout_candidates.json` 后 fold-in 仍待跑」,next_action = spawn `init-scout-merge`。
- **merge marker 在 + fold-in 已跑**(`controls_candidates.json::provenance.scout_merged` 存在)→
  note SHALL 载明:`scout_merged` 的并入证据(值)、`scout_candidates.json` 仅作完成凭证(内容无
  下游消费、LLM 重生成漂移无害)、NEVER 重跑 `merge_scout.py` fold-in、regen 后 `resume_state`
  重派生 `step=t1`。next_action = spawn `init-scout-merge`(诚实重生成)。
- **merge marker 在 + fold-in 未跑**(`scout_merged` 不存在)→ 凭证与 fold-in 均欠:note SHALL 载明
  「regen 凭证后 fold-in 待跑」,next_action = spawn `init-scout-merge`。

所有子状态 next_action 恒为 spawn `init-scout-merge`——**唯一恢复路径**(诚实重生成,宁花 LLM
token 不做占位凭证);重生成内容仅作完成凭证、漂移无害。

#### Scenario: fold-in 已跑但凭证丢失(真实失败形态)

- **WHEN** scout readers 全终态、`merge.json.done` 在、`controls_candidates.json::provenance.scout_merged=760`
  在、但 `scout_candidates.json` 缺失,编排器调用 `resume_state.py`
- **THEN** stdout `step="scout"`、next_action = spawn `init-scout-merge`,note 精确载明「fold-in 已跑
  (scout_merged=760)、regen 仅作完成凭证、NEVER 重跑 merge_scout.py fold-in、regen 后 step=t1」;
  note 不出现「merge marker absent」字样

#### Scenario: merge marker 缺失(合并确未跑)

- **WHEN** scout readers 全终态但 `merge.json.done` 与 `scout_candidates.json` 均缺
- **THEN** note 载明「合并未跑,regen 凭证后 fold-in 待跑」,next_action = spawn `init-scout-merge`

#### Scenario: merge marker 在但 fold-in 未跑

- **WHEN** `merge.json.done` 在但 `controls_candidates.json` 无 `provenance.scout_merged`,且
  `scout_candidates.json` 缺
- **THEN** note 载明「凭证与 fold-in 均欠,regen 后 fold-in 待跑」,next_action = spawn `init-scout-merge`

### Requirement: scout 步纪律表包含「NEVER 重跑 fold-in」反例

`core/scripts/discipline_core.py` scout 步的 `discipline_reminders[].nevers` SHALL 增反例:
「NEVER 重跑 `merge_scout.py` fold-in(`controls_candidates.json::provenance.scout_merged` 已设时;
重跑非幂等——同文件重跑把 `scout_merged` 归零,漂移文件重跑重复追加候选/簇)」。该反例随
`resume_state.py` stdout `discipline_reminders[]` 与 `list_steps.py --step scout` stdout `discipline`
逐字下发(两脚本共享同一纪律表,单一真相)。

#### Scenario: scout 步 resume 收到 fold-in 反例

- **WHEN** 编排器对处于 scout 步的 run 调用 `resume_state.py --target <t>` 或
  `list_steps.py --step scout`
- **THEN** stdout `discipline_reminders[].nevers` / `discipline.nevers` 含「NEVER 重跑 merge_scout.py
  fold-in(scout_merged 已设时)」反例,且两脚本逐字一致

### Requirement: resume-state 契约纠正「fold-in 重跑幂等安全」主张

`core/contracts/init/resume-state.md` SHALL 纠正既有「该键存在 ⟺ fold-in 已跑(再跑幂等、安全)」
的错误主张,改为:`provenance.scout_merged` 存在 ⟺ fold-in 已跑;fold-in **重跑非幂等**(同文件
重跑把 `scout_merged` 覆盖为 0 并触发虚假召回缺口披露,漂移重生成文件重跑重复追加候选/簇);
resume_state 在 `scout_merged` 存在时 MUST NOT 建议或指引重跑 `merge_scout.py` fold-in。契约 SHALL
补记「fold-in 已跑 + 凭证缺」子状态的恢复配方与 `--check` 违例(配方见 `scout-tier-gate`)。

#### Scenario: 契约不再宣称重跑安全

- **WHEN** 维护者读 `core/contracts/init/resume-state.md` 的 fold-in 检测段
- **THEN** 该段明确「scout_merged 在 ⟺ fold-in 已跑;重跑非幂等;resume_state 不得在 scout_merged
  存在时建议重跑 fold-in」,不再出现「再跑幂等、安全」之类主张
