# control-discovery Specification (delta)

## MODIFIED Requirements

### Requirement: Disclose scout coverage and residual blind spot

`init_manifest.json` SHALL 增 `scout` 段,记录:`skeleton_total`、`scout_targets`、
`batches`、`deep_read_files`、`audit_sampled`、`audit_found`、`scout_merged`(fold-in 实际并入
`controls_candidates.json` 的 scout 候选数,取值于 `merge_scout.py` 写入的
`provenance.scout_merged`;scout 未启用时该字段 SHALL 缺省/为空)、`truncated`(目标超预算时为真
并建议 `--scope`+`--merge`)。`report.md` 与 `init_manifest.json` 的 `boundaries[]` SHALL
新增披露:(1) scout 实际审视了 `skeleton_total` 中的多少、深度 Read 了多少、自检了多少
(**不声称全仓覆盖**);(2) scout 非确定,簇数 run-to-run 可能变化(regex 来源簇仍确定);
(3) 残留盲区——泛型包 + 泛型类名 + 泛型签名 + 无安全导入 + 低扇因的控制,规则与骨架均
无法识别,可能漏报。既有三条诚实边界(存在≠有效 / 调用图盲点 / 需人工复核)保持不变。

#### Scenario: Manifest reports real scout coverage numbers

- **WHEN** 一次含 scout 的运行完成
- **THEN** `init_manifest.json` 的 `scout` 段含可识别的真实计数字段(含 `scout_merged`),且不出现
  「全仓覆盖」之类断言

#### Scenario: Manifest omits scout_merged when scout disabled

- **WHEN** `--no-scout` 运行完成
- **THEN** `init_manifest.json` 的 `scout` 段不含 `scout_merged`(或为空),不声称 scout 并入量

#### Scenario: Residual blind spot is disclosed

- **WHEN** 审阅 `report.md` / `init_manifest.json` 的 `boundaries[]`
- **THEN** 其中明示「泛型命名 + 低扇因控制可能漏报」这一残留盲区,以及 scout 的非确定性

## ADDED Requirements

### Requirement: Merge scout fold-in normalizes non-canonical categories deterministically

`merge_scout.py` fold-in SHALL 用**确定性别名映射**把 scout 候选的非规范类名归一为规范 8 类之一
(`input-validation`/`authentication`/`authorization`/`data-masking`/`crypto`/`rate-limiting`/`csrf`/
`audit-logging`)再写入 `controls_candidates.json` 并参与 `form_clusters`。别名表 SHALL 与
`validate_inventory.py` 的规范 8 类共享**单一真相源**(如常量/helper 放在两脚本均可导入的公共位置,
承 R2 零依赖),至少覆盖既有漂移实例:`access-control→authorization`、`auth→authentication`。
归一 SHALL 发生在 fold-in 写入前(T2 之前),使 T2 `init-synthesis` 与 `validate_inventory.py`
只见到规范类名。`merge_scout.py --check` SHALL 对每条 scout candidate 断言其 `category` 归一后 ∈
规范 8 类;未映射的非规范类 SHALL 作为违例 fail-loud 退出码 2(而非静默丢弃或放行),使类名漂移在
**fold-in 边界**被拦截、而非等到 T2 边界(`validate_inventory.py`)或静默丢进综合。

#### Scenario: Non-canonical scout category is normalized at fold-in

- **WHEN** scout candidate 携带 `category: "access-control"`,fold-in 运行
- **THEN** 写入 `controls_candidates.json` 的该候选 `category` 为 `authorization`,并以其参与
  `form_clusters`;T2 只见规范类名

#### Scenario: merge_scout --check rejects an unmapped non-canonical category

- **WHEN** scout candidate 携带 `category: "runtime-guard"`(不在 8 类、不在别名表),运行
  `merge_scout.py --check`
- **THEN** 退出码 2,violations 报告该 candidate 的 index 与「category 非规范 8 类」issue;
  编排器据此回退重跑 scout-merge,而非带着漂移类名进入 T2

#### Scenario: Canonical categories pass the fold-in check unchanged

- **WHEN** scout candidate 携带规范类名(如 `authorization`),运行 `merge_scout.py --check` 与 fold-in
- **THEN** `--check` 退出码 0;fold-in 不改写该 `category` 原值

#### Scenario: Alias source stays shared between merge_scout and validate_inventory

- **WHEN** 审阅 `merge_scout.py` / `validate_inventory.py` 的类别常量来源
- **THEN** 两脚本引用同一规范 8 类 + 别名表(单一真相源),不允许各自硬编码一份
