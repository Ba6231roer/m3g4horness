## 1. 检查点路径文件名消毒(`core/scripts/list_clusters.py`)

- [x] 1.1 `_paths()`:`base = checkpoints_dir / f"{_safe_name(unit_id)}.json"`(替代原始 `unit_id`),
  使 `checkpoint_path` 与 `done_marker` 的文件名分量经 `_safe_name` 消毒;`_safe_name` 复用既有(不新增函数)。
- [x] 1.2 确认 slim envelope `cluster_id` 字段(`_slim_materialized` / `_lite`)仍携**原始** canonical
  `unit_id`(含 `::`)——身份字段不消毒,只文件名消毒。
- [x] 1.3 确认 `_done_ids` 无需改(读记录内 `unit` 字段、对文件名鲁棒);`_write_unit` / `_shard_hit_count`
  已用 `_safe_name`(输入侧),消毒范式一致。

## 2. 契约文档(如实标注消毒后文件名)

- [x] 2.1 `core/contracts/init/clusters.md`:input 文件名形态 `<cluster_id>.input.json` →
  `<safe(cluster_id)>.input.json`(顺带修既有 doc/code 漂移);示例与文字注明 `_safe_name`(`/ \ :` → `_`)。
- [x] 2.2 `core/contracts/init/unit-inputs.md`:同步标注 input / checkpoint 文件名为 `<safe(unit_id)>` 形态,
  注明 canonical `unit_id`(含 `::`)保留为 envelope/记录 `unit` 身份,文件名仅为存储编码。
- [x] 2.3 核对 `core/contracts/init/` 其余文件无「checkpoint_path = `<cid>.json` 原文」残留措辞。

## 3. 回归测试(`tests/test_init_clusters.py`)

- [x] 3.1 `test_pending_emits_absolute_paths` 更新:`exp` 改为 `(cp / f"{_safe(cid)}.json")` 消毒形态
  (`_safe` = `/ \ :` → `_`,与 `_mark_done` 同),断言消毒后绝对路径。
- [x] 3.2 新增 NTFS 消毒用例:`cluster_id` 含 `::`(如 `authorization::A::ab12`)→ `checkpoint_path`/
  `done_marker` 文件名分量 `::`→`_`、envelope `cluster_id` 仍为原始含 `::` 的 canonical id。
- [x] 3.3 新增/覆盖 resume 用例:消毒文件名 + 记录 `unit`=canonical → `_done_ids` 正确判终态、resume 不误重跑
  (复用 `test_pending_done_split_reads_record_unit` 思路,显式 seed 含 `::` 的 id)。
- [x] 3.4 `py tests/test_init_clusters.py` 全绿;`py tests/test_deterministic.py` 不退化。

## 4. 契约 / 稳定性守卫(R5)

- [x] 4.1 `py tools/check_contracts.py` 通过(本变更不动 `list_clusters.py` CLI flag,双壳 MD `--flag` ↔
  `--help` 镜像不退化)。
- [x] 4.2 确认运行时 hook(`block_adhoc_scripts` / `MGH_TARGET` 子树校验)不受影响——消毒只改文件名分量,
  目录子树 `<target>/.mgh-init/checkpoints/<tier>/` 不变;`tests/test_opencode_hook_parity.py` 不退化。
- [x] 4.3 按 R5.8 bump 版本号;`py tools/check_distributed_purity.py` 通过(契约文档措辞为操作性内容,
  不引入 dev-only 溯源 / 研发铁律编号)。
