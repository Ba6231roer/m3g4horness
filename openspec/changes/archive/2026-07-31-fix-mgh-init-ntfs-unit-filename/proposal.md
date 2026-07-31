## Why

`list_clusters.py::_paths` 用**原始 `unit_id`**(含 `cluster_id` 的 `::`,以及 shard 的
`::shard-<n>`)拼 `checkpoint_path` / `done_marker`,**未消毒**。NTFS 上 `::` 是 Alternate-Data-Stream
分隔符 → subagent 在 Windows 把 `checkpoint_path` 逐字 `write_text` 时 `OSError [Errno 22] Invalid argument`。
同一脚本的**输入文件名**已由 `_safe_name`(`/ \ :` → `_`)消毒(`_write_unit`),但**检查点路径漏消毒**——
这是同源 latent bug(memory `cluster-id-double-colon-ntfs-filename` 已记「checkpoint_path 仍未消毒」,
本变更兑现该记忆)。注意:issue #2 现象里的**输入文件** errno 22 在 `harden-mgh-init-context-budget`
已修( `_safe_name` 已用于 `_write_unit`);本变更只补**仍未消毒的检查点路径**。

## What Changes

- `list_clusters.py::_paths`:`base = checkpoints_dir / f"{_safe_name(unit_id)}.json"`,使
  `checkpoint_path` 与 `done_marker` 的**文件名分量**经 `_safe_name` 消毒(与输入文件名同一函数、同一范式)。
- **保持 canonical 身份不变**:slim envelope 的 `cluster_id` 字段、以及 subagent 写入检查点记录的 `unit`
  字段,SHALL 继续携带**原始** `unit_id`(含 `::`);只有**文件名**被编码。done 检测(`_done_ids`)读记录内
  `unit` 字段,不依赖文件名 → 消毒不影响 resume 匹配。
- 契约文档:`core/contracts/init/clusters.md`、`core/contracts/init/unit-inputs.md` 如实标注文件名为
  `<safe(unit_id)>` 形态(顺带修既有输入文件名 doc/code 漂移:文档现写 `<cluster_id>.input.json`,
  代码实际写 `<safe(cluster_id)>.input.json`)。
- 回归测:`tests/test_init_clusters.py::test_pending_emits_absolute_paths` 改为断言**消毒后**路径,
  并增「`::` cluster_id → 文件名消毒、envelope/记录 `unit` 保留 canonical」用例。

## Capabilities

### New Capabilities
<!-- 无新增 capability -->

### Modified Capabilities
- `control-discovery`: fan-out 枚举脚本产出的 `checkpoint_path` / `done_marker` 的**文件名分量** SHALL
  经 `_safe_name` 消毒(NTFS/POSIX 文件系统安全,治 `::` 导致的 errno 22),同时 canonical `unit_id`
  保留为 envelope `cluster_id` 与检查点记录 `unit` 字段(done 检测与身份语义不变)。

## Impact

- **代码**:`core/scripts/list_clusters.py`(`_paths` 单点;`_safe_name` 已存在,复用)。
- **契约**:`core/contracts/init/clusters.md`、`core/contracts/init/unit-inputs.md`(文件名形态措辞;schema
  字段集不变)。`checkpoint_path`/`done_marker` 的**值形态**变化(文件名分量消毒)——是契约级可见变化,
  需同步 spec/test。
- **测试**:`tests/test_init_clusters.py`(更新 `test_pending_emits_absolute_paths` + 新增 NTFS 消毒用例)。
- **依赖**:无。零运行时依赖不变(承 R2,纯标准库)。运行时 hook(`MGH_TARGET` 子树校验)不受影响——
  消毒只改文件名分量,目录子树(`.mgh-init/checkpoints/t1/`)不变。
