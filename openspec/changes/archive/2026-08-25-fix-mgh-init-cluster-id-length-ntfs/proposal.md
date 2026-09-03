# Proposal: fix-mgh-init-cluster-id-length-ntfs

> **人话序**
> **现象**:大仓 830 簇 T1 在 Windows 上整批卡死——`list_clusters.py --materialize` 一遇到第一条
> cluster_id 超长的簇就抛 `OSError`(文件名超出 NTFS 255 字符单分量上限),后面全部夭折;这些簇的
> checkpoint/`done`/`failed` 文件也根本建不出来,永远留在 `pending`,T1 无法推进。
> **根因**:`form_clusters` 拼 cluster_id 时,`home` 槽位在 class/method 检测失败时回退成**整个文件路径**,
> 又和必带的 `file` 槽位重复 → `{category}::{整条路径}::{整条路径}::{sha8}` 可达 267 字符;而
> `_safe_name` 只把 `/` `\` `:` 换成 `_`,不截长度;`--materialize` 的枚举循环无 per-cluster 容错,
> 首个即炸整批。
> **改什么**:① `form_clusters` 给 cluster_id 加总长上限(只截「显示槽位」、保留对完整 key 算的 sha8 尾做
> 唯一/恢复判别;普通短 id 逐字不变,sha8 尾对任何簇都不变);② `_safe_name` 加文件名 stem 长度上限
> (保尾,磁盘上不碰撞,旧 clusters.json 的超长 id 也能建出文件);③ `--materialize` 单簇写失败隔离
> (写 `.failed` 终态、批次继续);④ `discover_controls.py --check` 断言 id 长度上限,回归 fail-loud。
> **怎么验证**:构造 267 字符 id 的簇 → materialize 成功建出截断 stem 的文件、envelope 保留全 id;
> `--check` 对超长 id 退出码 2;单测覆盖(上游截断 / stem 截断 / 单簇失败隔离)。

## Why

`/mgh-init` 的 T1 隔离单元边界 = cluster_id(clusters.json 里 `form_clusters` 产出的确定性 id),它同时
是:① 输入文件名 `<safe(cluster_id)>.input.json` 的来源;② `checkpoint_path`/`done_marker`/`failed_marker`
与 `slice_dir` 的命名来源;③ resume 的判别身份。当它超过 NTFS 255 字符单分量上限时,**所有**以此派生的
文件名都写不进磁盘——这就是「遇首个即整批失败」的触发点。用户实测:某大仓(830 簇、scout 并入后)部分
簇的 `cluster_id` 达 267 字符,`list_clusters --materialize` 在 Windows 上跑不通。

根因链有三层,必须一起处理才算闭环:

1. **上游产长 id**:`form_clusters`(`discover_controls.py:687`)对 centralized 簇拼
   `key = f'{category}::{home}::{file}'`,`home = anchor.class or anchor.method or candidate.file`。
   当 class/method 检测失败(竞争簇把路径塞进类名槽位),`home` 回退成完整文件路径,与 `file` 槽位重复;
   即便 class 正常,深路径仓里 `file` 槽位本身就长 → id 逼近/超过 255。
2. **消毒不防长**:`list_clusters._safe_name` 只替换 `/` `\` `:` → `_`(治 NTFS ADS `::`),不限制长度。
3. **批次无容错**:`main()` 的 `for cluster in clusters` 循环不包 try/except,任何一条簇的 `_write_unit`
   抛 `OSError` 即整批退出;且该簇的 checkpoint 文件建不出 → 永远 pending、`--resume` 也绕不开。

本 change 以「上游截长 + 下游 stem 截长兜底 + 单簇失败隔离 + 边界校验」四件套封死,使任何簇的 id 都
能产出可写文件名、任何单簇写失败都不再拖垮整批。

## What Changes

- **上游:cluster_id 总长有界**(`discover_controls.form_clusters`):
  - 新增 `MAX_CLUSTER_ID_CHARS = 160`。id 仍形如 `{category}::{anchor|pattern}::{sha8}`;当显示部分超预算时,
    对 home/file 显示槽位做**保头保尾 + 槽位内 hash** 的截断(路径只留目录头 + 文件名尾),总长 ≤ 160。
  - 唯一性/恢复判别**不变**:sha8 始终对**完整 key**(未截断)计算、保留在 id 尾部 → 任何簇的 sha8 尾与
    改动前逐字相同,短 id(占绝大多数)的完整 id 也逐字不变,改动只影响超长 id 的显示前缀。
  - `home == file`(路径被塞进类名槽位)时,显示槽位去重(不再同一路径出现两次)。
- **下游:`_safe_name` 加 stem 长度上限**(`list_clusters.py`):
  - 新增 `MAX_UNIT_FILENAME_STEM = 200`。消毒 `/ \ :` → `_` 后仍超限则截断,但**保留尾部 ~60 字符**
    (含 sha8 判别尾),保证:两个不同 id 在磁盘上不碰撞;input/checkpoint/`done`/`failed`/`slice_dir`
    文件**永远可写**——包括旧版 discover 产的、长度未受上游约束的 legacy `clusters.json`。
  - canonical unit id 仍只作 envelope `cluster_id` + 检查点记录 `unit` 字段(身份不进文件名),resume
    匹配不受截断影响(既有约定,承 `fix-mgh-init-ntfs-unit-filename`)。
- **单簇写失败隔离**(`list_clusters.py --materialize`):
  - 每簇 `_resolve_units` 包 try/except(`OSError`);失败 → 写 `.failed` 终态 marker(body
    `{unit, reason, tier}`,文件名经 stem 截断**可写**)+ stderr 报原因 + `failed` 计数 +1,**批次继续**,
    不再整批 abort。`.failed` 也写不进(系统级损坏)→ 退出码 2 fail-loud。
- **边界校验(R5.9)**:`discover_controls.py --check` 增断言 `len(cluster_id) ≤ MAX_CLUSTER_ID_CHARS`,
  违例退出码 2;编排器在 discover 后、T1 前跑 `--check`,未来 producer 回归被闸门拦下。
- **契约与文档**:`core/contracts/init/clusters.md`(cluster_id 长度上界 + `_safe_name` stem 上限 +
  单簇物化失败 → `.failed`)、`core/contracts/init/unit-inputs.md`(stem 截长注)、`list_clusters.py`
  docstring/`--help`(R5.1 契约面同步)。
- **回归测试**:`tests/test_init_clusters.py` 增四类用例(见 Capabilities 的验证场景)。

无 shell(命令壳)改动:四件套都在已分发确定性脚本与契约文档内,不新增 CLI flag(常量内建)。

## Capabilities

### New Capabilities
<!-- 无:全部落在既有 control-discovery 能力内,不新建 capability。 -->

### Modified Capabilities
- `control-discovery`: 四条既有 requirement 发生 spec 级行为变化——
  - **Cluster inventory file contract**:`cluster_id` 加总长上界(≤ 160),显示槽位可截断、sha8 尾不变;
  - **Deterministic cluster enumeration for T1 fan-out**:`--materialize` 输入文件名 stem 受长上限约束,
    单簇物化写失败 → 写 `.failed` 终态 + `failed` 计数 + 批次继续(不再整批 abort);
  - **Fan-out checkpoint paths are deterministic absolute values**:`_safe_name` 除字符消毒外**兼做长度
    截断**(保尾、防磁盘碰撞),`checkpoint_path`/`done_marker`/`failed_marker` 文件名对超长 id 亦可写;
  - **Stage-boundary contract checks**:`discover_controls.py --check` 增 `cluster_id` 长度断言(退出码 2)。

## Impact

- **代码**:`core/scripts/discover_controls.py`(`form_clusters` 截长 + `--check` 长度断言);
  `core/scripts/list_clusters.py`(`_safe_name` stem 截长 + `--materialize` 单簇失败隔离 + docstring)。
- **契约文档**:`core/contracts/init/clusters.md`、`core/contracts/init/unit-inputs.md`。
- **测试**:`tests/test_init_clusters.py` 增:上游超长 id 截断 / `_safe_name` stem 截断保尾 /
  267 字符 id 的 `--materialize` 成功且 envelope 保留全 id / 单簇写失败 → `.failed` + 批次继续。
- **行为兼容**:普通短 id 的 `cluster_id`、输入文件名、checkpoint 路径**逐字不变**;`--check` 新增长度
  违例只在「id 超长」这一此前静默写失败的状态上 fail-loud;无新增 CLI flag、无运行域/哨兵/hook 变化。
- **风险**:低。改动限 discover 产 id 与 list_clusters 物化路径;sha8 判别尾保持不变使 resume 身份语义
  稳定;legacy 超长 id 从「必失败」变为「可写 + 可终态」。唯一注意 = 需 `validate_t1_records` 等下游
  不假设 id 内含完整路径(本 change 不改变下游对该字段的消费,`unit` 字段语义不变)。
