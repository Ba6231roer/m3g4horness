## Context

`cluster_id` 形如 `{category}::{anchor|pattern}::{sha8}`(见 `core/contracts/init/clusters.md`),
shard id 再加 `::shard-<n>`。`::` 在 NTFS 文件**名**里是 Alternate-Data-Stream 分隔符 →
`write_text` 报 `OSError [Errno 22]`。本仓 `list_clusters.py` 已用 `_safe_name`(`/ \ :` → `_`)消毒
**输入文件名**(`_write_unit`,承 `harden-mgh-init-context-budget`),但 `_paths()` 产出的
`checkpoint_path` / `done_marker` 仍用**原始** `unit_id` 拼文件名 → subagent 在 Windows 逐字写即崩。
测试基础设施 `_mark_done` 已自行消毒文件名,与生产 `_paths()` 不一致 = latent bug 的直接证据。

## Goals / Non-Goals

**Goals:**
- `checkpoint_path` / `done_marker` 的文件名分量经 `_safe_name` 消毒,与输入文件名同一范式、同一函数。
- canonical `unit_id`(含 `::`)保留为:slim envelope `cluster_id` 字段 + 检查点记录内 `unit` 字段。
- 契约文档如实反映消毒后文件名形态(顺带修输入文件名的既有 doc/code 漂移)。

**Non-Goals:**
- **不**改 `form_clusters` 的 cluster_id 生成(不去掉 `::`)——深层改 id 会波及 `clusters.md` 契约、所有
  消费方、resume 匹配语义,风险大;表层消毒已治标且不破坏 id 语义(见 D1)。深层作后续独立评估。
- **不**做长度截断 + 哈希后缀(issue 真机跑里模型自行加的)。`cluster_id = category::anchor::sha8` 有界、
  checkpoints 目录短(`.mgh-init/checkpoints/t1/`),无真实 MAX_PATH 命中证据;且输入文件名亦无长度帽,
  只给检查点加帽会引入不一致。若将来撞 MAX_PATH,另立 change 对称加帽。
- **不**改 `_done_ids`(已读记录内 `unit` 字段、对文件名鲁棒)、不改运行时 hook 子树校验。
- **不**扩到 scout 侧(`list_scout_batches.py`):`batch_id` 不含 `::`,不受影响;若将来含,同 `_safe_name`。

## Decisions

**D1 — 表层消毒(复用 `_safe_name`),非深层改 id 生成。**
`_paths()` 的 `base` 由 `checkpoints_dir / f"{unit_id}.json"` 改为 `checkpoints_dir / f"{_safe_name(unit_id)}.json"`。
- *Why*:治「文件名含 `::` 写不下」是**文件系统编码层**问题,与 id **语义**无关;表层消毒 = 最小、可逆、
  与既有输入文件名范式一致。深层改 id 去掉 `::` 会改契约格式,波及面大且无额外收益。
- *Alt*:深层改 `form_clusters` id 生成 → 改 `{category}::{anchor}::{sha8}` 契约、`clusters.md`、resume
  `unit` 匹配、所有读 cluster_id 的脚本/提示词;风险高、收益仅省一次 `_safe_name`;**否决**(作后续评估)。

**D2 — canonical 身份保留(只编文件名,不改身份字段)。**
envelope `cluster_id` 与记录内 `unit` 继续携原始 `unit_id`(含 `::`);仅文件名分量消毒。
- *Why*:cluster_id 是 T1 隔离/resume 的**身份**,跨产物引用、done 匹配都靠它;改身份会污染语义。文件名只是
  存储编码,身份与编码解耦是正解。done 检测读记录内 `unit` 字段(非文件名),故消毒不破 resume。

**D3 — 复用既有 `_safe_name`,不新增函数 / 不加长度逻辑。**
`_safe_name` 已存在并被 `_write_unit` / `_shard_hit_count` 使用;`_paths` 直接调,零新增代码面。
- *Why*:单一消毒真相源;输入文件名与检查点文件名同范式,可读、可测、防回归。

## Risks / Trade-offs

- **[Risk] `checkpoint_path` 值形态变化 → 破坏读旧路径的下游。**
  Mitigation:`checkpoint_path` 是 `list_*` stdout 即时派生、subagent 当次逐字写;无持久消费方读「旧形态」。
  既有磁盘记录文件名此前在 Windows 根本写不下(0.x live-verify 未覆盖),故无「旧可读文件」需兼容。
- **[Risk] 消毒后 done 检测失配 → resume 误重跑。**
  Mitigation:`_done_ids` 读记录内 `unit` 字段(canonical),不靠文件名;测试 `test_pending_done_split_reads_record_unit`
  覆盖。增 NTFS 消毒回归用例显式验证「文件名消毒 + unit 字段 canonical → resume 正确」。
- **[Risk] 掩盖深层 id 含 `::` 的设计异味。**
  Mitigation:非目标但披露——`::` 作为 id 分隔符是有意的可读性设计(`category::anchor::sha8`);本变更不假装
  深层无问题,仅把「写不下文件」这个表层硬伤先堵掉,深层评估留作后续(见 Non-Goals)。

## Migration Plan

单脚本单函数改动 + 同步契约文档与测试。`install.sh` 镜像 `core/scripts/list_clusters.py` 与
`core/contracts/init/*.md` 到目标项目即生效。无数据迁移(checkpoint 记录 schema 不变)。回滚 = `_paths()`
还原为原始 `unit_id` 拼文件名(仅 Windows 重新变脆)。

## Open Questions

无(表层 vs 深层已定 D1 表层;长度截断已定 Non-Goal)。
