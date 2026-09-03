# t1-record-schema-gate Specification [MODIFIED]

## MODIFIED Requirements

### Requirement: T1 记录形状契约与边界校验

T1 checkpoint 记录(每 cluster / 每 `<cluster_id>::shard-<n>` 单元一个)SHALL 携带根级
`cluster_id`、`name`、`category`(canonical 8)、`kind`(vvah 6)、`evidence`(≥1 非空锚点)、
`entry_points`(列表)、`confidence`(数值);`category`→`kind` SHALL 匹配确定性映射;根级
`controls[]` 嵌套 SHALL 判 violation。**增量**:记录体 SHALL 另携带根级 `unit` 字段 =
canonical 单元 id(整簇跑 = `cluster_id`;分片跑 = `<cluster_id>::shard-<n>`,与
`cluster_id` 字段值相同)——**身份双保险**:done/failed 判定的唯一真相源是正向 marker 路径
计算(见 `request-context-budget` 能力),记录体 `unit` 字段不承载判定职责,但 SHALL 使
glob 反查(孤儿审计、人工比对、跨工具诊断)能恢复正确身份,不再依赖文件名 stem 反推。
`validate_t1_records.py --check` SHALL 断言 `unit` 存在且为非空字符串;`unit` 与
`cluster_id` 不一致 SHALL 判 violation(同记录内身份自洽)。

理由〔实测失败形状:超长 cluster_id 的记录文件名被截断编码,done 判定若依赖「读记录体
`unit` 字段」而产出者从未写该字段,则每个记录都落入 stem 兜底——短 id 侥幸对齐、长 id
永久判 pending → fan-out 无限重派。正向计算修复判定本身;`unit` 字段让记录体自描述,
消除「反推」这一整类漂移面〕。

#### Scenario: 记录体携带 unit 字段
- **WHEN** init-induct 写一条 T1 checkpoint 记录(整簇或分片)
- **THEN** 根级 `unit` = 编排器透传的 canonical 单元 id;`validate_t1_records.py --check`
  对缺失/空 `unit` 判 violation

#### Scenario: unit 与 cluster_id 同记录内自洽
- **WHEN** 记录体 `unit` ≠ `cluster_id`(漂移签名)
- **THEN** `--check` 判 violation(列出 file + 两值),外科式重派该单元

#### Scenario: unit 缺失不破坏正向判定
- **WHEN** 修复前产出的历史记录无 `unit` 字段(修复后 `--check` 判 violation、外科重派,
  或运行域直接以正向 marker 判 done)
- **THEN** done/failed 判定结果与 `unit` 字段无关;历史 run `--resume` 自愈不受影响
