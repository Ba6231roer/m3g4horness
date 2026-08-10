# scout-tier-gate Specification

## ADDED Requirements

### Requirement: Scout-tier completion gates T1 enumeration

`list_clusters.py`(T1 工作清单产出者)SHALL 在派发 T1 工作清单前,基于 `<target>/.mgh-init/run_config.json`
与磁盘产物判定 scout 层是否完成。当 `run_config.json::no_scout` 为 falsy(scout 启用)且 scout 层**未完成**
(scout_plan 缺失 / scout readers 未全 `.done` / `scout_candidates.json` 缺失 / `checkpoints/scout/merge.json.done`
缺失 / fold-in 未写 `controls_candidates.json::provenance.scout_merged` 任一成立)时,`list_clusters.py` MUST
**fail-loud 退出码 2** 并拒绝产出 `pending[]`,stderr 给出 recipe(读 `resume_state.py` 的 `step`/`next_action`
先完成 scout 层),编排器 MUST NOT 以纯 regex 簇清单继续 T1。scout 完成判定 SHALL 复用与
`resume_state._scout_complete` 相同的确定性谓词(单一真相源,不允许各自实现、允许折叠到共享 helper)。
`--no-scout` 路径 MUST 跳过该闸门(regex-only 为显式意图,合法)。

#### Scenario: Orchestrator attempts T1 while scout is incomplete

- **WHEN** scout 启用、scout 层未完成(如 scout readers 已全 `.done` 但 `scout_candidates.json` 缺失),
  编排器调用 `list_clusters.py` 取 T1 清单
- **THEN** `list_clusters.py` 退出码 2、stdout 不含 `pending[]`,stderr 指向 `resume_state.py` 的
  `step`/`next_action` 以先完成 scout 层;编排器不据此扇出 `init-induct`

#### Scenario: Scout enabled with zero batches passes the gate

- **WHEN** scout 启用但 `scout_plan.json::batches[]` 为空(0 目标)
- **THEN** scout 层视为完成(无物可 scout),`list_clusters.py` 正常退出码 0 产出 T1 清单

#### Scenario: --no-scout bypasses the gate

- **WHEN** `run_config.json::no_scout` 为真,编排器调用 `list_clusters.py`
- **THEN** 闸门跳过(即使磁盘上无任何 scout 产物),`list_clusters.py` 正常产出 T1 清单,行为与引入闸门前一致

#### Scenario: Complete scout tier passes the gate

- **WHEN** scout 已完整(scout_candidates + merge marker + fold-in `scout_merged` 俱在)
- **THEN** `list_clusters.py` 正常退出码 0 产出 T1 清单(含 scout 簇)

### Requirement: Stale downstream tier markers cascade-invalidate on resume

`resume_state.py` SHALL 检测「scout 启用 + scout 层未完成 + 下游 t2/t3/t4 `.done` 已存在」的**过期凭证**
状态并确定性级联失效。具体:(a) `resume_state.py --check` 在该状态存在时 SHALL 报违例并退出码 2;
(b) `resume_state.py --invalidate-stale` 提供确定性失效操作——按 tier 依赖序清除过期 `.done`
(先 `--dry-run` 列出将被清除的标记,再实际清除;承 R5.3b 破坏性操作 dry-run 保护);
(c) 失效范围 SHALL 为 t2/t3/t4 的 `.done` 标记(t2 `synthesis.json.done`/`.done`、t3 各 category `.done`、
t4 `consistency.json.done`/`.done`),**保留** t1 各簇 `.done`(t1 按簇计,scout 簇会在 fold-in 后自然成为
新 pending,无需整体清空)。编排器 `--resume` 时若 `--check` 报该违例,MUST 先运行 `--invalidate-stale`
再续跑,NEVER 静默跳过已过期 tier(替代手工 `del` 下游 marker 的 workaround)。

#### Scenario: Stale downstream markers detected on resume

- **WHEN** scout 启用、scout 未完成(scout_candidates 缺失),但 `checkpoints/t2/synthesis.json.done`、
  t3/t4 `.done` 已存在(此前基于纯 regex 输入跑完)
- **THEN** `resume_state.py --check` 报「scout 未完成但下游 t2/t3/t4 .done 存在」违例,退出码 2

#### Scenario: Invalidate-stale clears only expired aggregate markers

- **WHEN** 运行 `resume_state.py --invalidate-stale --dry-run`,随后运行 `--invalidate-stale`
- **THEN** `--dry-run` 列出 t2/t3/t4 待清除标记而不改动磁盘;实际运行时清除这些 `.done`,
  t1 各簇 `.done` 保留;清除后 `--check` 不再报该违例

#### Scenario: Resume after invalidation re-runs the aggregate tiers

- **WHEN** 上述失效后 scout 补完成(fold-in 写入 `scout_merged`、`clusters.json` 追加 scout 簇),plain
  `--resume`
- **THEN** T1 对新 scout 簇扇出、T2/T3/T4 因 marker 已清而重新综合/写规则/一致性,scout 发现并入
  `controls_inventory.json`;全程无需手工删 marker

### Requirement: Scout contribution consistency check

`resume_state.py --check` SHALL 交叉校验 scout 的「声明运行量」与「实际并入量」:当 scout 启用、
`scout_plan.json::batches[]` 非空、scout readers 全 `.done`,但 `controls_candidates.json::provenance.scout_merged`
**缺失**时 SHALL 报违例并退出码 2(scout 跑了但从未并入 = 搁浅);`scout_merged` 存在但为 0 时 SHALL 在
stdout `notes[]` 醒目披露「scout 审阅 N 批但并入 0 候选,可能召回缺口」且**非 fail-loud**(合法仓可全被
regex 覆盖)。`init_manifest.json` 的 `scout` 段 SHALL 记录 `scout_merged`(见 control-discovery「Disclose
scout coverage」)。该检查使搁浅**自报**,不再依赖用户怀疑「结果不全」。

#### Scenario: Scout ran but never merged is a hard violation

- **WHEN** scout 启用、batches=415、scout readers 全 `.done`,但 `scout_merged` 字段缺失(fold-in 未跑)
- **THEN** `resume_state.py --check` 报「scout 已跑但未并入(scout_merged 缺失)」违例,退出码 2

#### Scenario: Scout merged zero candidates is disclosed, not gating

- **WHEN** scout 完整跑完且 fold-in 写入 `scout_merged: 0`
- **THEN** `resume_state.py --check` 退出码 0,但 stdout `notes[]` 含「scout 审阅 N 批并入 0 候选」披露;
  `init_manifest.json::scout.scout_merged` = 0

#### Scenario: Scout disabled avoids the consistency check

- **WHEN** `run_config.json::no_scout` 为真
- **THEN** `resume_state.py --check` 不评估 scout 一致性,不报上述违例或披露
