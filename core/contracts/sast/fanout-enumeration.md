# Contract: `list_chunks.py` / `list_verify_jobs.py` stdout (sast fan-out work-lists)

Producer: `core/scripts/list_chunks.py` + `core/scripts/list_verify_jobs.py`
(deterministic, stdlib). Consumer: `/mgh-sast` orchestrator s4 / s6 fan-out. Closes the
fan-out asymmetry: sast now has the `list_clusters.py`-equivalent for both fan-out tiers.
编排器取「待跑 chunk / finding 清单」MUST 走这两个脚本,NEVER 手挖 `s3_chunks.json` /
`s5_filtered.json` / `py -c` 内省。

## CLI(`--help` 即契约)

```
py list_chunks.py       --chunks   <s3_chunks.json>   [--checkpoints <s4-dir>]
py list_verify_jobs.py  --findings <s5_filtered.json> [--checkpoints <s6-dir>]
```

默认 checkpoint 目录(sast 聚合产物平铺在 `checkpoints/`,per-unit 在子目录):
`list_chunks` → `<s3_chunks.json 所在目录>/s4`;`list_verify_jobs` → `<s5_filtered.json 所在目录>/s6`。

## stdout(结构化 JSON;stderr 仅诊断)

```json
{"repo": null, "total": N, "done": M, "pending": [...], "truncated": false}
```

不变式(两脚本同):`total == done + len(pending)`。空清单(`total:0`)→ 退出码仍 `0`,
不静默丢信息。退出码 `0/1/2`。

### `<ChunkLite>`(list_chunks pending[] 每项)

```json
{"chunk_id": "chunk-01", "files": ["src/parser.c", "src/parser.h"],
 "threat_id": "T3", "hypothesis": "..."}
```

| field | source | note |
|---|---|---|
| `chunk_id` | `s3_chunks.json::chunks[].id` | vvah s3 的 unit 键是 `id`("chunk-NN"),lite 重投影为 `chunk_id` |
| `files` | `chunks[].files` | 该 chunk 的文件集 |
| `threat_id` | `chunks[].threat_id` | 关联威胁(s2) |
| `hypothesis` | `chunks[].hypothesis` | 狩猎假设 |

`s3_chunks.json` 是 vvah `{rationale, chunks[]}` 包装(无 `repo`/`truncated`;`repo` 输出 `null`、
`truncated` 输出 `false`)。也接受裸 `chunks[]` 列表。

### `<FindingLite>`(list_verify_jobs pending[] 每项)

```json
{"finding_id": "F-001", "file": "src/api/Controller.java", "line": 71,
 "vuln_class": "injection", "source_ref": "src/api/Controller.java:71",
 "sink_ref": "src/db/Query.java:42"}
```

| field | source | note |
|---|---|---|
| `finding_id` | 见下「finding_id 派生」 | filename-safe,作 checkpoint 键 |
| `file` | `kept[].file` | |
| `line` | `kept[].line_start` | vvah 字段是 `line_start`,lite 重投影为 `line` |
| `vuln_class` | `kept[].vuln_class` | |
| `source_ref` / `sink_ref` | `kept[].source_ref` / `sink_ref` | |

`s5_filtered.json` 是 prefilter.py 输出 `{kept[], dropped[], stats}`(findings 在 **`kept[]`**,
非 `findings[]`)。也接受 `{findings[]}` 包装或裸列表。

### finding_id 派生(list_verify_jobs)

- 优先用规范 Finding 的 `id`(如 "F-001",见 `core/contracts/README.md`)。
- 缺失时(vvah s4 原始输出无 id)从 `{file, line_start, vuln_class}` 派生稳定 base,经
  filename-safe 投影(非 `[A-Za-z0-9._-]` → `-`)。
- 同 base 冲突 → 按文件序追加 `-2`/`-3`(位置消歧;prefilter 确定 → `kept[]` 序稳定 → resume 稳定)。

## checkpoint 约定(本契约定义)

per-unit fan-out 检查点写 `<repo>/security-scan/checkpoints/<tier>/<unit_id>.json` +
`<unit_id>.json.done`(`unit_id` 即上面的 `chunk_id` / `finding_id`,filename-safe)。
枚举脚本扫 `*.json.done` 取 marker stem = `unit_id`,**不读** sibling 记录字段。

| tier | dir | unit_id 来源 |
|---|---|---|
| s4 | `checkpoints/s4/` | `chunks[].id`(list_chunks → `chunk_id`) |
| s6 | `checkpoints/s6/` | Finding `id` 或派生(list_verify_jobs → `finding_id`) |
