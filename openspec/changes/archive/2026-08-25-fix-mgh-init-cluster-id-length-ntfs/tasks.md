## 1. 上游:`discover_controls.py` — cluster_id 总长有界

- [x] 1.1 新增模块常量 `MAX_CLUSTER_ID_CHARS = 160`(NTFS 255 单分量上限,为 `::shard-<n>` + 后缀留余量)
- [x] 1.2 新增 `_bound_slot(s, cap)`(保头保尾 + 8-hex 槽位 hash;`cap<=9` 时退化为 `_sha(s)[:cap]`)与
      `_bounded_cluster_id(key, slot_a, slot_b)`(sha8 恒对完整 key;`len(key)<=budget` 时逐字返回
      `f"{key}::{sha8}"`;超预算时对 `slot_a==slot_b` 去重显示槽位 / 否则双槽各截,总长恰 ≤160)
- [x] 1.3 `form_clusters` centralized 分支改调 `_bounded_cluster_id(key, home, head["file"])`
      (`home = head["anchor"].get("class") or head["anchor"].get("method") or head["file"]`);
      distributed 分支保持 `f'{key}::{_sha(key)}'` 不动
- [x] 1.4 `_run_check` 的 cluster_id 校验链在 duplicate 分支旁增长度断言:
      `len(str(cid)) > MAX_CLUSTER_ID_CHARS` → violation `cluster_id too long`,退出码 2

## 2. 下游:`list_clusters.py` — stem 截长 + 单簇失败隔离

- [x] 2.1 新增模块常量 `MAX_UNIT_FILENAME_STEM = 200`;`_safe_name` 在字符消毒后加长度截断
      (超限保尾部 ~60 字符判别段,`head~tail` 总长恰 200;短 id 逐字不变)
- [x] 2.2 `main()` 的 `--materialize` 分支把每簇 `_resolve_units` 包 `try/except OSError`:
      失败 → stderr 报 `cluster <cid> materialize failed` + 写 `.failed` 终态 marker
      (body `{unit, reason, tier}`, 用 `_paths(...)[2]`,文件名经 stem 截断可写) + `clusters_failed += 1` +
      `continue`;`.failed` 亦写不进 → 退出码 2 fail-loud
- [x] 2.3 更新 `list_clusters.py` 模块 docstring 与 `--materialize` 的 `--help` 文案
      (R5.1 契约面):文件名 stem 截长上限 + 单簇失败 → `.failed` 终态 + 批次继续

## 3. 契约文档

- [x] 3.1 `core/contracts/init/clusters.md`:cluster_id 字段注「总长 ≤ 160,超预算截显示槽位、保
      sha8 判别尾」+ `home==file` 去重;补「单簇物化写失败 → `.failed` 终态 + failed 计数 + 批次继续
      (`.failed` 亦失败 → 退出码 2)」
- [x] 3.2 `core/contracts/init/unit-inputs.md`:`_safe_name` 消毒注扩为「字符消毒 + stem 长度截断
      (≤200,保尾判别段)」,canonical id 仍只作 envelope/`unit` 字段

## 4. 回归测试:`tests/test_init_clusters.py`

- [x] 4.1 新增 `TestClusters` 用例:构造 anchor 无 class/method 的 centralized 候选(路径被塞进类名槽位,
      未截断 id 达 267 字符)→ `form_clusters` 产出的 `cluster_id` ≤ 160、`::` 出现次数为 2(去重)、
      尾部 sha8 等于对未截断 key 的 `_sha`
- [x] 4.2 新增 `TestClusters` 用例:短 id 簇(普通 class + 短路径)→ `cluster_id` 与手拼的
      `f'{key}::{_sha(key)}'` 逐字相等(约束前后不变)
- [x] 4.3 新增 `TestListClusters` 用例:`_safe_name` 对 267 字符 id 返回 ≤ 200、以消毒头开头、以
      含 sha8 的尾部结尾;两个仅中段不同的长 id 映射到不同 stem(不碰撞);短 id 逐字不变
- [x] 4.4 新增 `TestListClustersMaterialize` 用例:267 字符 id 的簇 `--materialize` 退出码 0、
      input 文件创建成功(stem ≤ 200)、envelope `cluster_id` 为完整 canonical id;
      以截断 stem + `unit` 字段标记 done 后 `--resume` 正确跳过
- [x] 4.5 新增 `TestListClustersMaterialize` 用例:`mock.patch` 使某簇 `_resolve_units` 抛 `OSError`
      → 该簇写 `.failed`(body `unit`=canonical)、stdout `failed` +1、其余簇照常物化、退出码 0

## 5. 验证

- [x] 5.1 `py tests/test_init_clusters.py` 全绿
- [x] 5.2 `tools/check_contracts.py` + `tools/check_distributed_purity.py` + 零依赖 AST 扫描
      (`grep import vvaharness` 无命中)不回归
- [x] 5.3 构造含超长 cluster_id 的 `clusters.json` fixture → `discover_controls.py --check` 退出码 2、
      violations 报「cluster_id too long」;`list_clusters.py --materialize` 对该 fixture 退出码 0、
      全部簇物化成功
