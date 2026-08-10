# fix-mgh-init-scout-stranding

## Why

一次全仓 `/mgh-init` run(scout 开启)只产出 2 类规则:scout readers 跑了 413/415 批,但汇总产物
`scout_candidates.json` 从未生成,scout 发现全部搁浅在 `checkpoints/scout/` 里、从未并入 inventory;
T1–T4 却全部 `.done`——编排器越过未完成的 scout 层直奔下游,管线实质跑成 regex-only,且无任何报错。
根因:scout 层被越过 + 下游已跑完的 tier 的 `.done` 标记成为「基于不完整输入的过期凭证」。修复后,
scout 不再可被静默跳过,下游 `.done` 会随上游输入变更自动级联失效,恢复无需手工删 marker。

## What Changes

- **D1 — 确定性 tier 闸门**:`list_clusters.py`(T1 工作清单产出者,编排器跑 T1 必经)在 scout 启用
  (`no_scout:false`) 且 scout 层未完成时 **fail-loud 退出码 2** 并拒绝产出 T1 清单,附 recipe
  (先跑 scout 层)。`resume_state.py --check` 增加同条件违例断言。tier 顺序从「仅靠提示词强制」升级为
  「确定性闸门强制」。
- **D2 — 级联失效**:`resume_state.py` 检测「scout 启用 + scout 未完成 + 下游 t1/t2/t3/t4 `.done`
  存在」→ 判定下游 `.done` 为**过期凭证**(基于 regex-only 输入产出),提供确定性失效操作
  (`--invalidate-stale`,先 `--dry-run`),使 scout 补完后 plain `--resume` 自动重跑 T1–T4,
  **免手工删 marker**。
- **D3 — scout 类别归一前移**:`merge_scout.py` fold-in 用**确定性别名映射**归一非规范类名
  (`access-control→authorization`、`auth→authentication` 等);`merge_scout.py --check` 在 fold-in
  边界断言 category ∈ 规范 8 类(归一后),T2 不再吃漂移类名。
- **D4 — scout 贡献一致性检查**:`resume_state.py --check` 交叉校验「scout 开启 + `scout_plan`
  batches>0 + `provenance.scout_merged` 缺失或 0」→ fail-loud(缺失=搁浅)或醒目披露(0=可能召回缺口),
  搁浅自报而非靠用户怀疑。

## Capabilities

### New Capabilities

- `scout-tier-gate`:确定性的 scout→T1 tier 顺序强制与下游 `.done` 级联失效——`list_clusters.py`
  闸门 + `resume_state.py` 过期凭证检测/失效。独立成 spec,因为它引入的是**新的确定性不变量**
  (上游未完成则下游不可产出;上游输入变更则下游标记失效),不同于既有「按产物探测 step」的弱约束。

### Modified Capabilities

- `control-discovery`:
  - `merge_scout.py` fold-in 增加确定性类别归一(非规范类名→规范 8 类),`--check` 断言类别枚举归属;
  - `list_clusters.py`(T1 枚举)增加 scout-complete 前置闸门;
  - `resume_state.py --check` 增加 scout 一致性断言(搁浅 / 贡献 0)。

## Impact

| 面 | 文件 | 变化 |
|---|---|---|
| 确定性脚本 | `core/scripts/list_clusters.py` | T1 枚举前置 scout-complete 闸门(exit 2) |
| 确定性脚本 | `core/scripts/resume_state.py` | 过期凭证检测 + `--invalidate-stale`(dry-run 保护)+ `--check` 违例 |
| 确定性脚本 | `core/scripts/merge_scout.py` | fold-in 类别别名归一 + `--check` 类别枚举断言 |
| 类别真相源 | `core/scripts/validate_inventory.py`(或 discover_controls) | 规范 8 类 + 别名表单一来源,供 merge_scout 复用 |
| 命令壳(双端) | `releases/{claude-code/commands,opencode/command}/mgh-init.md` | 闸门/失效操作调用示例逐字镜像(承 R5.1);不引研发编号(承 R5.10) |
| 编排纪律片段 | `core/prompts/fragments/orchestrator-discipline.md` | scout 闸门 + 级联失效的 recipe 措辞(非 prohibition) |
| 契约 | `core/contracts/init/*` | 新增闸门/失效操作返回契约 |
| 回归测 | `tests/test_resume_state.py` / `test_merge_scout.py` / `test_list_clusters.py` / `test_distributed_md_purity.py` / `test_zero_deps.py` | 闸门、级联失效、别名归一、契约 lint、零依赖 |
| 分发纯净 | `tools/check_distributed_purity.py` | 命令壳增补不得引入悬空引用 |

不引入 pip 依赖(承 R2);不改 `run_config.json` / `init_manifest.json` 磁盘 schema;不新增 tier
(仍 discover→scout→t1→t2→t3→t4)。`--no-scout` 路径行为不变。
