## ADDED Requirements

### Requirement: `--check` 对「fold-in 已跑但凭证缺失」报镜像违例

当 scout 启用且磁盘状态为「`checkpoints/scout/merge.json.done` 在 **且**
`controls_candidates.json::provenance.scout_merged` 在 **且** `scout_candidates.json` **缺失」时,
`resume_state.py --check` SHALL 报违例并退出码 2(R5.9 fail-loud),violation 文本 SHALL 载明恢复
配方:经 `init-scout-merge` 诚实重生成 `scout_candidates.json`(唯一恢复路径),且 NEVER 重跑
`merge_scout.py` fold-in(fold-in 已跑,`scout_merged` 是权威证据)。该违例与既有
「`scout_candidates.json` 在但 merge marker 缺」违例互为镜像;恢复(凭证重新在盘)后 `--check`
SHALL 通过(退出码 0)。

#### Scenario: fold-in 已跑但凭证缺失 → --check 退出码 2

- **WHEN** scout 启用、`merge.json.done` 在、`scout_merged` 在、`scout_candidates.json` 缺,调用
  `resume_state.py --check`
- **THEN** 退出码 2,stdout `violations[]` 含「merge.json.done + fold-in 已跑但 scout_candidates.json
  缺失」违例,文本含 regen 两径 + NEVER 重跑 fold-in 配方

#### Scenario: 凭证恢复后 --check 通过

- **WHEN** 上述状态经 `init-scout-merge` regen 使 `scout_candidates.json` 重新在盘,再次调用
  `resume_state.py --check`
- **THEN** 退出码 0,该镜像违例不再出现在 `violations[]`
