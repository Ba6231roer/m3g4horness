# Design: fix-mgh-init-cluster-id-length-ntfs

## Context

Motivation 见 `proposal.md`「Why」。现状:

- `form_clusters`(`core/scripts/discover_controls.py:687`)对 centralized 簇拼
  `key = f'{category}::{home}::{file}'`,`home = anchor.class or anchor.method or candidate.file`;
  `cluster_id = f'{key}::{sha1(key)[:12]}'`。anchor 无 class/method 时 `home` 回退为完整文件路径,
  与 `file` 槽位重复 → id 可达 267 字符。
- `list_clusters.py::_safe_name` 只做字符替换(`/` `\` `:` → `_`,治 NTFS ADS `::`),不限制长度;
  `_write_unit`/`_paths`/`_slice_dir` 都以 `<safe(id)>` 作文件名/目录名分量。
- `main()` 的 `for cluster in clusters:` 循环内 `_resolve_units` 无 try/except → 单簇写失败即整批 abort。
- `discover_controls._run_check`(`--check`)断言 cluster_id 唯一,不断言长度。

约束(承 AGENTS.md):R2 零运行时依赖(stdlib only)、R5.1 `--help` 即契约面、R5.3b stdout/stderr 分流 +
退出码 `0/1/2` + 幂等、R5.9 `--check` fail-loud、文件名 stem 已受 `_safe_name` 纪律约束(承
`fix-mgh-init-ntfs-unit-filename`;canonical id 只作 envelope/`unit` 字段,身份不进文件名)。

## Goals / Non-Goals

**Goals:**
- 任何 `cluster_id`(含上游产出的超长 id 与 legacy `clusters.json` 里的历史超长 id)派生出的文件名都**可写**。
- 单簇物化写失败不再拖垮整批;失败可被编排器以既有 `.failed` 终态语义消费。
- 普通短 id 的 `cluster_id`、输入文件名、checkpoint 路径**逐字不变**(改动只影响超长 id)。
- 唯一性/恢复判别身份稳定:尾部 sha8 恒对**未截断完整 key** 计算,任何簇与改动前逐字相同。
- `--check` 对 producer 回归 fail-loud。

**Non-Goals:**
- 不改 `_safe_name` 的**字符**消毒语义(只增长度截断;不引入保留名/CON/NUL/尾点尾空格处理——类名与
  posix 路径派生的 id 不会命中这些形态,且单簇失败隔离兜底)。
- 不改 distributed 簇的 id(`pattern` 短、从不过长);scout 候选经 `merge_scout.py` 复用同一
  `form_clusters`,自动获得同样的界(无独立改动)。
- 不动命令壳 / 编排流 / hook / 哨兵(改动全在已分发确定性脚本 + 契约 + 测试)。
- 不新增 CLI flag(长度常量为内部不变量,内建)。

## Decisions

### D1 — 上游:`form_clusters` 给 cluster_id 总长上界(≤ 160)

机制:`_bounded_cluster_id(key, slot_a, slot_b)` 在 `form_clusters` 的 centralized 分支调用(distributed
分支保持 `f'{key}::{_sha(key)}'` 不动):

```python
MAX_CLUSTER_ID_CHARS = 160  # NTFS 255 单分量上限;为 ::shard-<n>(≤11) + 后缀(≤11) 留足余量

def _bound_slot(s: str, cap: int) -> str:
    if len(s) <= cap:
        return s
    if cap <= 9:
        return _sha(s)[:cap]
    keep = cap - 9                              # 1 '~' + 8 hex 槽位内 hash
    half = keep // 2
    return f"{s[:half]}~{_sha(s)[:8]}~{s[-(keep - half):]}"

def _bounded_cluster_id(key: str, slot_a: str, slot_b: str) -> str:
    sha8 = _sha(key)                            # 对完整 key(未截断)——判别身份不变
    budget = MAX_CLUSTER_ID_CHARS - len(sha8) - 2      # 预留 "::{sha8}"
    if len(key) <= budget:
        return f"{key}::{sha8}"                 # 短 id → 逐字不变(byte-identical)
    category = key.split("::", 1)[0]
    if slot_a == slot_b:                        # 路径被塞进类名槽位(重复)→ 显示槽位去重
        return f"{category}::{_bound_slot(slot_a, budget - len(category) - 2)}::{sha8}"
    cap = (budget - len(category) - 4) // 2     # 减两个 "::"
    return f"{category}::{_bound_slot(slot_a, cap)}::{_bound_slot(slot_b, cap)}::{sha8}"
```

`form_clusters` centralized 分支改为(其余不动):
`home = head["anchor"].get("class") or head["anchor"].get("method") or head["file"]`;
`cluster_id = _bounded_cluster_id(key, home, head["file"])`。

关键性质:
- **sha8 不变**:`_sha(key)` 恒对完整 key(未截断、与当前代码逐字相同的 key 串)计算 → 任何簇的
  sha8 尾与改动前逐字相同;短 id 完整串也逐字相同(仅超长时截显示槽位)。
- **总长有界**:`budget = 160 - 12 - 2 = 146`。去重分支 id = `category + 2 + cap + 2 + 12` 恰 160;
  非去重分支 = `category + 2 + cap + 2 + cap + 2 + 12` 恰 160。
- **路径保头保尾**:`_bound_slot` 保留目录头 + 文件名尾 + 8-hex 槽位 hash;槽位 hash 仅作显示消歧,
  真正的唯一性是尾部全 key sha8 与 checkpoint `unit` 字段,故槽位 hash 碰撞无正确性影响。
- **确定性**:同输入 → 同 id;跨进程/平台稳定。

**替代方案(否决)**:① 让 `home` 回退不再取整路径(治重复)——不解决深路径 `file` 槽位本身过长,
且改动 key 构造会改 sha。② 整串从右截断(只留 category + 路径头 + sha8)——正确(唯一性靠 sha8)但
丢 `file` 槽位显示;作为 D1 的退化形态被中间省略号方案取代。

### D2 — 下游:`_safe_name` 加 stem 长度截断(≤ 200,保尾判别段)

`list_clusters.py::_safe_name` 扩为:先字符消毒,再截长:

```python
MAX_UNIT_FILENAME_STEM = 200  # NTFS 255 − ".input.json"(11);最坏 stem 200 → 211 ≤ 255

def _safe_name(unit_id: str) -> str:
    s = unit_id.replace("/", "_").replace("\\", "_").replace(":", "_")
    if len(s) <= MAX_UNIT_FILENAME_STEM:
        return s
    head = s[: MAX_UNIT_FILENAME_STEM - 60]                 # 140
    tail = s[-(MAX_UNIT_FILENAME_STEM - len(head) - 1):]    # 59
    return head + "~" + tail                                # 140 + 1 + 59 = 200
```

- 保留尾部 ~60 字符(含全 key sha8 的 12 hex + 路径文件名尾)→ 两个不同 id 只有头 140 与尾 59 全同才
  碰撞 = 需要 sha8(48-bit)碰撞,可忽略;即便理论碰撞,envelope `unit` 字段仍是权威身份。
- 使 input/`checkpoint`/`done`/`failed`/`slice_dir` 文件**永远可写**——含 legacy 267 字符 id 的
  `clusters.json`(旧版 discover 产出,未经 D1 约束)。这是对「checkpoints 文件根本无法创建」的**直接修复**:
  文件名可建 → 该簇可被标记 `.failed` 终态 → resume 不再永久 pending。
- `_done_ids`/`_failed_ids` 的 stem 回退(`unit = record.stem`)本已是 best-effort(`::` 消毒后 stem 就
  不等于 canonical id);长度截断不改变该回退的语义(主路径仍读记录内 `unit` 字段)。

**替代方案(否决)**:纯截断 `s[:200]`(丢尾部 sha8)→ 长 id 间磁盘碰撞风险。保留名/CON/NUL/尾点尾空格
处理——不引入(见 Non-Goals;单簇失败隔离兜底)。

### D3 — 单簇物化写失败隔离(批次继续)

`list_clusters.main()` 的 `--materialize` 分支,把每簇 `_resolve_units` 包 try/except:

```python
try:
    units = list(_resolve_units(cid, cluster, hits, args.max_unit_bytes, inputs_dir, repo_path))
except OSError as e:
    print(f"error: cluster {cid} materialize failed: {e}", file=sys.stderr)
    failed_path = _paths(checkpoints_dir, cid)[2]
    try:
        Path(failed_path).write_text(json.dumps(
            {"unit": cid, "reason": f"materialize failed: {e}", "tier": "t1"},
            ensure_ascii=False), encoding="utf-8")
    except OSError:
        print(f"error: cannot write failed marker for {cid} — systemic run-dir failure", file=sys.stderr)
        return 2
    clusters_failed += 1
    continue
```

- `.failed` marker 文件名经 D2 stem 截断**可写**;body 为既有 `{unit, reason, tier}` 终态语义,
  `_failed_ids` 下次运行直接排除 → 不再永久 pending、不重派。
- 其余簇照常物化;stdout `failed` 计数 +1;退出码仍 `0`(与编排器 ack 失败走 `.failed` 的既有语义一致)。
- `.failed` 也写不进 = 运行目录系统级损坏 → 退出码 `2` fail-loud(承 R5.3b/R5.9)。
- 部分已写的 shard input 残留无害(幂等覆盖;该簇已终态,subagent 不再读它)。

**替代方案(否决)**:① 整批 fail-loud(退出码 2)——这正是本 change 要修的「首个即整批失败」。② 静默
跳过 + stderr warn——簇从 `pending[]` 消失、编排器无从得知,等于丢簇,违背 R5.3b「不静默丢信息」。

### D4 — `discover_controls.py --check` 断言 cluster_id 长度(承 R5.9)

`_run_check` 的 cluster_id 校验链(`discover_controls.py:794`)在「duplicate」分支旁新增:

```python
elif len(str(cid)) > MAX_CLUSTER_ID_CHARS:
    violations.append({"file": "clusters.json", "index": i,
                       "issue": f"cluster_id length {len(str(cid))} > {MAX_CLUSTER_ID_CHARS}"})
```

编排器在 discover 后、T1 前跑 `--check`;未来 producer 回归(超长 id 再出现)被闸门拦下、退出码 2、
回退重跑 discover(其 `form_clusters` 现产有界 id)。

## Risks / Trade-offs

- **[长 id 显示前缀变化]** 超长 id 的 `cluster_id` 字符串变了(显示槽位被截)。→ 这些 id 改动前就
  无法建 checkpoint/input 文件(必失败),无既有 resume 状态可破坏;sha8 判别尾不变;下游消费的
  `unit`/`cluster_id` 字段语义不变。短 id 逐字不变。
- **[`_safe_name` 截断 → 文件名字符串 ≠ canonical id]** 磁盘文件名不再是 id 的可逆编码。→ 既有
  `_done_ids`/`_failed_ids` 已按「读记录内 `unit` 字段」设计,文件名只作散列键;本 change 不改变该
  约定,仅增加长度维度(同 `::` 消毒同构)。
- **[槽位 hash 碰撞]** `_bound_slot` 内 8-hex hash 与 `_safe_name` 尾部 60 字符截断在极端下可能同形。
  → 仅为显示/文件名消歧;唯一性权威是完整 key 的 sha8(48-bit)+ checkpoint `unit` 字段,碰撞无
  正确性影响。
- **[`.failed` 写入失败兜底]** 单簇隔离要求 `.failed` 也可写;若运行目录整体损坏(写不进任何文件),
  退出码 2。→ 显式 fail-loud,不静默;该状态是系统级,应停止而非带伤继续。

## Migration Plan

- 一次性代码 + 契约 + 测试改动,无数据迁移:`clusters.json` 重新 discover 即产有界 id;legacy
  `clusters.json` 的超长 id 经 D2 直接可物化,无需重跑。
- 回滚:本 change 不新增 CLI 面,回滚 = 还原两个脚本 + 契约 + 测试(常量内建、无外部状态)。
- 部署顺序:脚本(discover + list_clusters)→ 契约文档 → 测试;`tests/test_init_clusters.py` 全绿 +
  `tools/check_contracts.py`/`tools/check_distributed_purity.py` 不回归。

## Open Questions

无。设计决策(D1 预算数值 160/200、失败语义)不改变 specs 或任务拆分;如实现期发现路径中 `::`
罕见形态影响 `key.split("::", 1)`,可在实现内以「从 `head` 重算 home/file」替代拆分(不影响外部行为)。
