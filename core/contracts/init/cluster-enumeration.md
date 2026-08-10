# Contract: `list_clusters.py` stdout (T1 pending work-list)

Producer: `core/scripts/list_clusters.py` (deterministic, stdlib). Consumer: orchestrator
T1 fan-out(步骤 4)。编排器取「待跑簇清单」MUST 走本脚本,NEVER 手挖 `clusters.json`
/ `py -c` 内省(`clusters.json` 是包装字典 `{repo,clusters[],truncated}`,对顶层 `len()`
得 3 **不是**簇数;簇数真相源 = `list_clusters.py` stdout 的 `total`)。

CLI(`--help` 即契约):
```
py list_clusters.py --clusters <clusters.json> [--checkpoints <t1-dir>]
```

> **scout-tier 闸门(确定性 tier 顺序)**:`<clusters.json 同目录>/run_config.json` 存在且 `no_scout`
> falsy(scout 启用)而 scout 层未完成(`init_tier.scout_complete` false)→ **退出码 2** + stdout
> `{"error":"scout-incomplete-gate",...}` + **不产 `pending[]`**,stderr 给 recipe(读
> `resume_state.py` 的 `step`/`next_action` 先完成 scout 层;`--no-scout` 可显式绕行)。`run_config`
> 缺失(裸 clusters.json / 测试夹具)或 `no_scout` 为真 → 闸门跳过(向后兼容)。编排器 MUST NOT 以纯
> regex 簇清单继续 T1。

stdout(结构化 JSON;stderr 仅诊断):
```json
{"repo": "...", "total": N, "done": M, "failed": F, "pending": [<ClusterLite>, ...], "truncated": false}
```

`<ClusterLite>`:
```json
{"cluster_id": "authorization::Sec::<sha8>", "category": "authorization", "kind": "auth",
 "shape": "centralized", "evidence_files": ["src/.../Sec.java"], "candidate_count": 2,
 "checkpoint_path": "<abs>/checkpoints/t1/authorization__Sec__<sha8>.json",
 "done_marker": "<abs>/checkpoints/t1/authorization__Sec__<sha8>.json.done",
 "failed_marker": "<abs>/checkpoints/t1/authorization__Sec__<sha8>.json.failed",
 "slice_dir": "<abs>/slices/t1/authorization__Sec__<sha8>/"}
```
> `cluster_id` 含 `::`(NTFS ADS 分隔符)→ `checkpoint_path`/`done_marker`/`failed_marker`/`slice_dir` 的**文件名分量**经
> `_safe_name`(`/`、`\`、`:` → `_`)消毒(`::`→`__`);envelope `cluster_id` 字段保留**原始** canonical id。

| field | note |
|---|---|
| `total` | `len(clusters.json::clusters[])`(真簇数,非 wrapper key 数) |
| `done` | `#已 done` 簇(`checkpoints/t1/<safe(cluster_id)>.json.done` 存在;按记录 `unit` 字段 robust 读取) |
| `failed` | `#终态失败` 簇(`<safe(cluster_id)>.json.failed` 存在;**终态、排除出 pending、resume 不重试**)。crash 无 `failed` ack → 无 marker → 仍 `pending` → resume 重派(crash ≠ 确认失败) |
| `pending[]` | 未 done **且** 未 failed 簇,文件序;每项 `{cluster_id,category,kind,shape,evidence_files[],candidate_count,checkpoint_path,done_marker,failed_marker,slice_dir}` |
| `checkpoint_path` | **绝对**;由 `--checkpoints`(已 `resolve()`)拼 `<safe(cluster_id)>.json` 得出(`_safe_name` 消毒文件名分量)。编排器**逐字透传**给 T1 subagent,subagent **恰好写该绝对路径**(NEVER 自拼 `<target>/<cluster_id>`、NEVER 裸相对路径 `.mgh-init/...`、NEVER 写项目外)。 |
| `done_marker` | **绝对**;`<checkpoint_path>.done`,subagent 成功写完产物后 touch 它。 |
| `failed_marker` | **绝对**;`<checkpoint_path>.failed`(与 `.done` sibling)。**编排器**在收到 subagent `failed <reason>` ack 后 `Write` 它(body `{unit,reason,tier}`;路径取本 stdout `pending[].failed_marker` 逐字透传,NEVER 自拼)。subagent 失败路径 **touch nothing**。 |
| `slice_dir` | **绝对**;`<init-dir>/slices/t1/<safe(cluster_id)>/`(`<init-dir>` = `--checkpoints` 祖父目录 = `<target>/.mgh-init`,与 `checkpoint_path` 同根)。编排器**逐字透传**给 T1 subagent;subagent 对**运行时发现**的超 `--big-file-bytes` 大证据文件写 `chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json` 并**回读该确切绝对路径**(T1 大文件非预列入 `needs_slice[]`、运行时才发现)。subagent **NEVER** 写相对 `--out`、**NEVER** 写 cwd/Temp 派生路径、**NEVER** 写树外。`<safe-stem>` 取源文件 stem 经 `_safe_name` 消毒。 |
| `truncated` | 透传 `clusters.json::truncated`(无静默截断) |

不变式(非切分簇):`total == done + failed + len(pending)`。空 clusters(0 候选)→ `total:0`,退出码仍 `0`。

> **T1→T2 形状闸门**:T1 fan-out 写出的 `checkpoints/t1/*.json`(记录 schema + validator 契约见
> [`t1-record-schema.md`](t1-record-schema.md))在进 T2 前 SHALL 经 `validate_t1_records.py --strip-bom`
> 然后 `--check`;形状漂移(嵌套 `controls[]`/缺字段/枚举越界)退出码 2 → 失效违例簇 `.done` marker、
> 重跑本脚本重派该簇,NEVER 带破损记录进 T2(T2 按契约字段直取会静默丢弃漂移记录)。
退出码 `0/1/2`。`checkpoint_path`/`done_marker`/`failed_marker`/`slice_dir` **仅存在于本 stdout**,不写入磁盘产物
(磁盘 `checkpoints/t1/<safe(cluster_id)>.json` schema 不变;记录内 `unit` = canonical cluster_id;切片落 `<slice_dir>` 下 ephemeral、随 `.mgh-init/` gitignore)。
