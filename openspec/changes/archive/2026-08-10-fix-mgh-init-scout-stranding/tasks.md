# fix-mgh-init-scout-stranding — Tasks

## 1. Shared substrate: init_tier.py (单一真相源)

- [x] 1.1 新建 `core/scripts/init_tier.py`(零依赖):`INIT_CATEGORIES`(规范 8 类)、`CATEGORY_ALIASES`
      (`access-control→authorization`、`auth→authentication`)、`normalize_category(c)`、`scout_complete(init_dir)`
      (复刻 `resume_state._scout_complete` 判定:scout_plan 在 **且** (0 batch **或** (readers 终态 **且**
      `scout_candidates.json`+`merge.json.done` **且** fold-in `provenance.scout_merged` 完)))。
- [x] 1.2 `resume_state.py` 改为调用 `init_tier.scout_complete`(消除 `_scout_complete`/`_scout_step` 内嵌判定),
      跑既有 `tests/test_resume_state.py` 确认行为不变。
- [x] 1.3 `validate_inventory.py` 的 `KIND`/`INIT_CATEGORIES` 改从 `init_tier` 导入(常量单一来源),
      `discover_controls.py` 的 `KIND` 亦改导入;跑既有 zero-dep / AST 扫描测。
- [x] 1.4 版本号 bump(承 R5.8)。

## 2. D1 — T1 确定性闸门(list_clusters.py)

- [x] 2.1 `list_clusters.py` 从 `--clusters` 推导 init-dir(`Path(args.clusters).parent`),读
      `<init-dir>/run_config.json`;存在且 `no_scout` falsy → 调 `init_tier.scout_complete`。
- [x] 2.2 scout 未完成 → stderr 给 recipe(读 `resume_state.py` stdout 先完成 scout 层;`--no-scout` 可显式
      绕行)+ 退出码 2 + stdout `{"error":"scout-incomplete-gate",...}`,**不产 `pending[]`**;
      run_config 缺失 / `no_scout` 为真 → 闸门跳过(向后兼容)。
- [x] 2.3 docstring/`--help` 增闸门行为说明(承 R5.1;无新 flag)。
- [x] 2.4 `tests/test_list_clusters.py` 增 4 形状:未完→exit2 无 pending / 0 batch 过 / no_scout 过 / 完→过。

## 3. D2 — 级联失效(merge_scout.py + resume_state.py)

- [x] 3.1 `merge_scout.py` fold-in 在 `scout_candidates_added > 0` 时删除下游聚合 `.done`
      (`checkpoints/t2/{synthesis.json.done,.done}`、`t3/*.json.done`、`t4/{consistency.json.done,.done}`),
      stderr 注明「fold-in 并入 N → 级联失效 t2/t3/t4」;stdout 摘要增 `invalidated_tiers[]`;
      `scout_candidates_added == 0` 时不删。
- [x] 3.2 `resume_state.py` 新增 `--invalidate-stale [--dry-run]`:删除「scout 未完 + 下游 .done」过期凭证
      (范围同 3.1,抽共享 `_stale_marker_paths(init_dir)`),`--dry-run` 只列不删。
- [x] 3.3 `resume_state.py --check` 增违例:「scout 启用 + scout 未完成 + t2/t3/t4 任一 `.done` 存在」→
      violations + 退出码 2。
- [x] 3.4 `resume_state.resolve()` 在检测到过期凭证状态时加 `notes[]` 提示(不改 step 判定)。
- [x] 3.5 `tests/test_resume_state.py` 增:过期凭证违例(4 形状)、`--invalidate-stale` dry-run/实删一致性。
- [x] 3.6 `tests/test_merge_scout.py` 增:fold-in 并入>0 删 marker / ==0 不删、stdout `invalidated_tiers[]`。

## 4. D3 — fold-in 边界类别归一(merge_scout.py)

- [x] 4.1 `merge_scout._normalize` 调 `init_tier.normalize_category`;归一后仍非 `INIT_CATEGORIES` → 跳过 +
      stderr warn(防 `--check` 被绕行时崩溃)。
- [x] 4.2 `merge_scout.py --check`(`_run_check`)对每条 candidate 断言归一后 `category ∈ INIT_CATEGORIES`;
      非规范 → violations 记 index+issue,退出码 2。
- [x] 4.3 `tests/test_merge_scout.py` 增:别名归一命中(`access-control→authorization`)、未映射跳过、
      `--check` 枚举断言失败 exit 2 / 规范类 exit 0。

## 5. D4 — scout 一致性检查 + manifest 落账

- [x] 5.1 `resume_state.py --check` 增违例:「scout 启用 + `scout_plan.batches>0` + readers 全终态 +
      `provenance.scout_merged` 缺失」→ 退出码 2;`scout_merged` 存在但为 0 → `notes[]` 披露(非 gate)。
- [x] 5.2 `resume_state.resolve()` stdout `tiers.scout` 增 `merged` 字段(读 `provenance.scout_merged` 现值;
      fold-in 未跑时缺省)。
- [x] 5.3 双壳 mgh-init.md(claude/opencode)i4 段补一行:读 `resume_state` stdout `tiers.scout.merged` 写入
      `init_manifest.json::scout.scout_merged`(纯操作语义,承 R5.10)。
- [x] 5.4 `core/contracts/init/manifest.md` `scout` 段增 `scout_merged`;`resume-state.md` 增
      `tiers.scout.merged` + `--invalidate-stale` 契约。
- [x] 5.5 `tests/test_resume_state.py` 增 D4 违例与 notes、`tiers.scout.merged` 字段形状。

## 6. 双壳命令壳 + 契约增补

- [x] 6.1 双壳 mgh-init.md:scout fold-in 行注明「并入>0 级联失效下游 .done」;resume 段补
      `--check` 过期凭证违例 → `--invalidate-stale` recipe;`list_clusters` 行注明闸门 exit 2 处理。
      全部纯操作语义、不引研发编号(FDn/R5.x/openspec 夹名),双壳字节级对等。
- [x] 6.2 `core/contracts/init/cluster-enumeration.md` / `scout-plan.md` 增闸门退出码 2 形状与
      fold-in 级联失效说明。
- [x] 6.3 `tools/check_contracts.py` 无新 flag 断言变化;`resume_state --invalidate-stale`/`--dry-run`
      需出现在双壳调用示例(契约 lint 过)。
- [x] 6.4 `tests/test_distributed_md_purity.py` / `test_opencode_hook_parity.py` / `test_zero_deps.py`
      照跑不退化。

## 7. 回归 + 手工复现

- [x] 7.1 全量回归测:`py tests/test_resume_state.py` + `test_merge_scout.py` + `test_list_clusters.py`
      + `test_distributed_md_purity.py` + `test_zero_deps.py` + `test_opencode_hook_parity.py` 全绿。
- [x] 7.2 `py tools/check_contracts.py` + `py tools/check_distributed_purity.py` 通过。
- [x] 7.3 手工复现(review 场景):造「scout 未完 + t2/t3/t4 done」磁盘态 → `resume_state.py --check`
      报过期凭证违例 → `--invalidate-stale --dry-run` → `--invalidate-stale` → scout 补完 → plain
      `--resume` 重跑 T1–T4,`scout_merged` 落账 `init_manifest.json`。
- [x] 7.4 确认 `--no-scout` 路径全程不受闸门/一致性检查影响(回归行为不变)。
