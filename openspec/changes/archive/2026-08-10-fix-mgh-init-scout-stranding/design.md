# fix-mgh-init-scout-stranding — 设计

## Context

全仓 `/mgh-init` run 的真实失败形状(2026-08-07):scout readers 跑了 413/415 批,但
`scout_candidates.json` 从未生成,scout 发现搁浅在 `checkpoints/scout/`;T1–T4 却全部 `.done`。
管线实质跑成 regex-only,权限控制(access-control/auth)一直在 scout checkpoint 里、从未并入
inventory。根因链:scout-merge 未跑 + 编排器越过 scout 层直奔 T1;后续 plain `--resume` 又因
t2/t3/t4 `.done` 是「基于不完整输入的过期凭证」而跳过 T1–T4。

现状相关事实(磁盘/源码,非推测):
- `resume_state.py` 已正确**报告** `step=scout`(`_scout_complete:333`),但**不阻止**编排器越过去跑 T1
  ——无确定性闸门。`--check`(`check():381`)也没有「scout 未完 + 下游已 done」违例。
- `list_clusters.py`(T1 枚举)只读 `clusters.json` + `checkpoints/t1`,不知 scout 状态 → 无法自检。
- `merge_scout.py` fold-in(`main():148`)只追加 scout 簇到 `clusters.json`,**不**级联失效下游 `.done`;
  `_normalize`(`:28`)不校验类名枚举归属。
- 规范 8 类真相源现散两处:`validate_inventory.py:38-45`(`KIND`/`INIT_CATEGORIES`)与
  `discover_controls.py:136`(`KIND`);`init-scout.md:55` 钉类名靠 prompt。漂移实例
  `access-control`/`auth` 无确定性归一。
- `init_manifest.json::scout`(manifest.md 契约)记 `skeleton_total/targets/batches/deep_read/audit_*`,
  **无 `scout_merged`**;无「scout 跑 N 批但并入 0」一致性检查。

## Goals / Non-Goals

**Goals:**
- D1:scout 启用且未完成时,T1 枚举**确定性拒绝**(退出码 2),编排器无法再越过 scout 层。
- D2:tier 间数据依赖不变量——scout fold-in 实际并入后**自动级联失效**下游聚合 `.done`
  (t2/t3/t4),恢复免手工删 marker;`--check` 对「scout 未完 + 下游已 done」的过期凭证状态
  fail-loud,`--invalidate-stale` 提供显式失效兜底(带 `--dry-run`)。
- D3:非规范类名在 **fold-in 边界**确定性归一(别名表 `access-control→authorization`、
  `auth→authentication`),`merge_scout.py --check` 断言归一后 ∈ 规范 8 类;T2 只见规范类名。
- D4:scout 一致性检查——「scout 启用 + batches>0 + readers done + `scout_merged` 缺失」fail-loud;
  「`scout_merged`=0」notes 披露(非 gate);`init_manifest.json::scout.scout_merged` 落账。
- 全程零运行时依赖(R2)、双壳字节级对等、契约 lint / 回归测覆盖、命令壳分布纯净(R5.10)。

**Non-Goals:**
- 不改 `run_config.json` / `init_manifest.json` 磁盘 schema(仅在既有 `scout` 段增字段,不改段结构)。
- 不新增 tier、不改既有 step 枚举(`resume-state.md` 真值表不变)。
- 不做类别**语义推断**(LLM 归哪类交给 scout 提示词);本设计只做**确定性别名映射 + 枚举归属断言**。
- 不改 `--no-scout` 行为(regex-only 仍是显式合法路径,闸门跳过)。
- 不修 scout-merge 提示词本身(类名漂移的 LLM 侧收敛不在本变更;确定性兜底已够)。

## Decisions

### D1 — T1 闸门:list_clusters.py 自检 run_config + scout 完成态,不新增 flag

`list_clusters.py` 从 `--clusters` 值推导 init-dir(`Path(args.clusters).parent`),读
`<init-dir>/run_config.json`:
- `run_config.json` **存在**且 `no_scout` falsy → 进入闸门:复用共享谓词
  `scout_complete(init_dir)`(见 D1 下方「共享谓词」)判 scout 层完成;**未完成 → stderr 给 recipe
  (「读 `resume_state.py` stdout `step`/`next_action` 先完成 scout 层;`--no-scout` 可显式绕行」)+
  退出码 2 + stdout 报 `{"error":"scout-incomplete-gate", ...}`,**不产 `pending[]`**。
- `run_config.json` 缺失(裸 `clusters.json` / 单测夹具)→ 闸门跳过(无法判 scout 启用,保守放行,
  与现有「`--candidates` 缺失时降级」一致)。
- `no_scout` 为真 → 闸门跳过(显式 regex-only 合法)。

选择**自动自检**而非显式 `--gate` flag:编排器跑 T1 必经 `list_clusters.py`,自动闸门**无法被忘记**
(传不传 flag 都拦);显式 flag 依赖编排器记得传,违背「确定性兜底」。且不新增 CLI flag,
R5.1 契约面不变(仅 docstring/`--help` 增闸门行为说明)。
替代考虑(否决):放 `resume_state.py` 拦截——它只**报告** step 不**执行**任何产出,编排器可跳过调用;
放 runtime hook——overkill,且 `list_clusters` 是天然单一 chokepoint。

### 共享谓词 scout_complete() + 规范 8 类/别名表(单一真相源)

新建 `core/scripts/init_tier.py`(零依赖,被 `list_clusters` / `resume_state` / `merge_scout` /
`validate_inventory` 兄弟导入,承 R5.3a `sys.path` 自定位):
- `scout_complete(init_dir) -> bool`:复刻 `resume_state._scout_complete` 判定(scout_plan 在 **且**
  (0 batch **或** (readers 终态 **且** `scout_candidates.json`+`merge.json.done` **且** fold-in 完)));
  `resume_state` 改为调用它,消除双实现漂移。
- `INIT_CATEGORIES`(规范 8 类)+ `CATEGORY_ALIASES`(`access-control→authorization`,`auth→authentication`)
  + `normalize_category(c)`。`validate_inventory.KIND` / `discover_controls.KIND` 与 `INIT_CATEGORIES`
  改为从本模块导入(行为不变,单一来源)。承 R2:`init_tier.py` 仅标准库。

理由〔单一真相源防漂移 + 兄弟导入零新依赖 + 确定性〕。

### D2 — 级联失效:fold-in 实际并入后自动清下游聚合 .done;resume_state 增 --invalidate-stale

**主机制(fold-in 级联)**:`merge_scout.py` fold-in 在 `scout_candidates_added > 0`(真实并入
非 0)时,删除下游聚合 `.done` 标记:`checkpoints/t2/{synthesis.json.done,.done}`、
`checkpoints/t3/*.json.done`、`checkpoints/t4/{consistency.json.done,.done}`,stderr 注明
「scout fold-in 并入 N 候选 → 级联失效 t2/t3/t4 .done,resume 重综合」。理由:fold-in 是「T1 输入
`clusters.json`/`controls_candidates.json` 变更」的唯一确定性发生点,也是 t1 重枚举(t1 新簇自然
pending、无需清 t1 marker)之后 T2 必重跑的前提。`scout_candidates_added == 0`(全重复/全失败)时
不失效(输入没变,下游 .done 仍有效)。

**检测/兜底**:`resume_state.py`:
- `--check` 增两条违例(fail-loud 退出码 2):
  - 「scout 启用 + scout 未完成 + t2/t3/t4 任一 `.done` 存在」= 过期凭证状态(基于不完整输入产出的
    下游标记);
  - D4 的「scout 启用 + `scout_plan.batches>0` + readers 全终态 + `scout_merged` 缺失」= 搁浅。
- 新增 `--invalidate-stale [--dry-run]`:删除上述过期下游 `.done`(与 fold-in 级联同款范围,抽共享
  helper `_stale_marker_paths(init_dir)`),`--dry-run` 只列不删。承 R5.3b 破坏性操作 dry-run 保护。
- `resolve()` 不改 step 判定(scout 未完本就会报 `step=scout`);仅在检测到过期凭证状态时加 `notes[]`
  提示「下游 .done 为过期凭证,先跑 `--check`/`--invalidate-stale`」。

理由〔上游输入变更点是级联失效的单一可靠触发点 + 显式兜底承 R5.9 + 恢复免手工删 marker〕。
替代考虑(否决):resume_state 每次 resolve 自动删 marker——`resolve` 是只读探针(契约「read-only leaf」),
删文件违背其只读语义;改为 `--invalidate-stale` 显式子命令,编排器按 recipe 调。

### D3 — fold-in 边界归一:merge_scout._normalize + --check 断言

- `merge_scout._normalize` 调用 `init_tier.normalize_category(category)`;归一后**仍不在** `INIT_CATEGORIES`
  的候选 → 跳过 + stderr warn(既有「缺字段跳过」同款优雅降级,防 `--check` 被绕行时崩溃)。
- `merge_scout.py --check`(`_run_check:99`)新增对每条 candidate:归一后 `category ∈ INIT_CATEGORIES`;
  非规范 → violations 记 index + issue,退出码 2(编排器回退重跑 scout-merge)。位置在 **fold-in 边界**
  (比 `validate_inventory.py`(T2 边界)更早),T2 只见规范类名。
- `validate_inventory.py` 保留既有 category→kind 校验,但常量改从 `init_tier` 导入(单一来源)。

理由〔归一前移到最早确定性边界 + fail-loud 在 fold-in 而非 T2〕。

### D4 — scout 一致性检查 + manifest 落账

- `resume_state.py --check` 增 D4 违例(见 D2)+ `resolve()` stdout `tiers.scout` 增 `merged` 字段
  (读 `controls_candidates.json::provenance.scout_merged` 现值;fold-in 未跑时缺省)。
- 编排器 i4 写 `init_manifest.json` 时,把 `resume_state` stdout `tiers.scout.merged` 写入
  `scout.scout_merged`(既有 `scout` 段增字段,不改段结构)。双壳 mgh-init.md 的 i4 段补一行(承 R5.10
  纯操作语义:「读 resume_state stdout 的 `tiers.scout.merged` 写入 `scout.scout_merged`」)。
- `manifest.md` 契约 `scout` 段增 `scout_merged`(scout 未启用或缺省为空)。

理由〔搁浅自报 + 归属真实数字落账,不靠用户怀疑「结果不全」〕。

### 契约与回归

- 新增 stdout/CLI 契约写进 `core/contracts/init/{resume-state,cluster-enumeration,scout-plan,manifest}.md`:
  `list_clusters` 闸门退出码 2 形状、`resume_state --invalidate-stale`、`tiers.scout.merged`、
  `scout.scout_merged`。
- 双壳 mgh-init.md(claude/opencode)补:scout 段 fold-in 行注明「并入>0 级联失效下游 .done」;
  i4 段补 `scout_merged` 落账;resume 段补 `--check` 过期凭证违例 → `--invalidate-stale` recipe。
  全部纯操作语义,不引研发编号(承 R5.10,`tools/check_distributed_purity.py` CI 必过)。
- `tools/check_contracts.py` 继续机械化断言(无新 flag,仅 docstring 变化;`resume_state --invalidate-stale`
  /`--dry-run` 需镜像进双壳示例)。
- 回归测(`tests/`):
  - `test_resume_state.py`:过期凭证违例(4 形状)、`--invalidate-stale` dry-run/实删、`tiers.scout.merged`、
    D4 违例与 notes。
  - `test_list_clusters.py`:闸门 4 形状(未完→exit2 无 pending / 0 batch 过 / no_scout 过 / 完→过)。
  - `test_merge_scout.py`:归一(别名命中 / 未映射跳过)、`--check` 枚举断言、fold-in 级联删除
    (并入>0 删 / ==0 不删)、`init_tier` 导入路径。
  - `test_zero_deps.py` / `test_distributed_md_purity.py`:零依赖 + 双壳纯净不变式照跑。
- 版本号 bump(承 R5.8);`install.sh` 自检照跑。

## Risks / Trade-offs

- [闸门误伤合法 0-batch scout] → `scout_complete` 明确 0 batch = complete(现状已如此),单测覆盖。
- [list_clusters 自动推导 init-dir 在 `--clusters` 非 init 目录时误判] → 仅当同目录 `run_config.json`
  存在才启用闸门;裸集群(单测/第三方调用)无 run_config → 跳过,向后兼容。
- [fold-in 级联删 marker 在 `--check` 被绕行时静默] → 删除必有 stderr 注明 + 退出摘要字段
  `invalidated_tiers[]`;`--check`/`--invalidate-stale` 双端兜底;幂等(重复 fold-in 无新并入则不删)。
- [别名表覆盖不全,新漂移类名仍过] → `--check` 枚举断言是硬边界(未映射即 exit 2),宁可回退重跑
  scout-merge 也不带漂移进 T2;别名表是**已知实例**的最小集,可后续扩展(非本变更目标)。
- [`--invalidate-stale --dry-run` 输出与实删偏离] → dry-run 与实删共用同一 `_stale_marker_paths`,
  单测断言两者一致。

## Migration Plan

1. 建 `core/scripts/init_tier.py`(共享谓词 + 类别常量),`resume_state`/`validate_inventory` 改导入,
   跑既有回归测确认行为不变。
2. `merge_scout.py`:归一 + `--check` 枚举断言 + fold-in 级联删除。
3. `list_clusters.py`:闸门(自检 run_config + `scout_complete`)。
4. `resume_state.py`:`--invalidate-stale [--dry-run]` + `--check` 两违例 + `tiers.scout.merged`。
5. 契约 md + 双壳 mgh-init.md 增补;manifest 落账。
6. 回归测 + 契约 lint + 纯净 lint + 版本 bump。
7. 手工复现(旧 review 场景):删 `run_config`?不——用既有 `.mgh-init` 造「scout 未完 + 下游 done」,
   验 `--check` 违例 → `--invalidate-stale --dry-run` → `--invalidate-stale` → scout 补完 → plain
   `--resume` 重跑 T1–T4,`scout_merged` 落账。回滚:任何一步回归失败则 revert 对应脚本 + 版本回退
   (marker 删除仅影响本轮 resume,不破坏源产物)。

## Open Questions

- fold-in 级联删除的触发阈值用 `scout_candidates_added > 0`(建议):audit_found 并入也计入 `added`,
  已含;若未来 fold-in 改语义需复核触发点。
- `tiers.scout.merged` 与 manifest `scout.scout_merged` 在 `scout_merged` 为 0 时以「0」落账还是
  缺省:设计为**缺省/空**(scout 未启用或缺省;0 是「跑了但并入 0」的合法值,落 0,由 D4 notes 披露)。
