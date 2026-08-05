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
{"repo": null, "total": N, "done": M, "pending": [...], "truncated": false,
 "offset": 0, "limit": K, "effective_limit": k, "shrunk": false,
 "scripts_dir": "<abs <mgh-core>/scripts dir of THIS install>"}
```

顶层 `scripts_dir` = `Path(__file__).resolve().parent`(list_chunks `__file__` 派生 = 当前运行 install
的 `<mgh-core>/scripts/`,绝对、host-agnostic)。编排器在 s4 fan-out 读它,把 `<scripts_dir>/chunk_sources.py`
作为**绝对工具路径**逐字透传给 sast-deepdive(NEVER 裸名 / 相对 `.claude`|`.opencode/mgh-core/scripts/…`——
多层 install 下相对路径可上溯解析到**别的**旧副本)。s6 不切片,`list_verify_jobs` 无 `scripts_dir`。

不变式(两脚本同):`total == done + len(pending)`。空清单(`total:0`)→ 退出码仍 `0`,
不静默丢信息。退出码 `0/1/2`。

### `<ChunkLite>`(list_chunks pending[] 每项)

**`--materialize` slim 壳**(fan-out 受信形态;可变长负载 `files[]`/`hypothesis` 下沉进 `input_path` 文件):
```json
{"chunk_id": "chunk-01", "files_count": 2, "threat_id": "T3", "needs_slice": [],
 "input_path": "<abs>/inputs/s4/chunk-01.input.json",
 "checkpoint_path": "<abs>/checkpoints/s4/chunk-01.json",
 "done_marker": "<abs>/checkpoints/s4/chunk-01.json.done",
 "slice_dir": "<abs>/slices/s4/chunk-01/", "bytes": 4096, "oversize": false}
```
**lite 壳**(无 `--materialize`,backward-compat、不进 fan-out,不带 `slice_dir`):
```json
{"chunk_id": "chunk-01", "files": ["src/parser.c", "src/parser.h"],
 "threat_id": "T3", "hypothesis": "..."}
```

| field | source | note |
|---|---|---|
| `chunk_id` | `s3_chunks.json::chunks[].id` | vvah s3 的 unit 键是 `id`("chunk-NN"),lite 重投影为 `chunk_id` |
| `files` / `hypothesis` | `chunks[].files` / `.hypothesis` | lite 壳字段;slim 壳改为 `files_count` + 下沉进 `input_path` |
| `threat_id` | `chunks[].threat_id` | 关联威胁(s2) |
| `input_path`/`checkpoint_path`/`done_marker`/`bytes`/`oversize`/`needs_slice` | slim 壳字段 | 见 `list_chunks.py --help`;编排器逐字透传,subagent 读 `input_path`、写 `checkpoint_path`、touch `done_marker` |
| `slice_dir` | slim 壳衍生 | **绝对**;`<命令输出目录>/slices/s4/<safe(chunk_id)>/`(`<命令输出目录>` = `--checkpoints` 祖父目录 = `<target>/security-scan`,与 `checkpoint_path` 同根;`_safe_name` 消毒文件名分量,干净 `chunk-NN` 为 no-op)。编排器**逐字透传**;sast-deepdive 对 `needs_slice[]` 大文件写 `<scripts_dir>/chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json`(`<safe-stem>` 取源文件 stem)并**回读该确切绝对路径**——NEVER 相对 `--out`、NEVER cwd/Temp 派生、NEVER 树外。仅 slim 壳 |

`s3_chunks.json` 是 vvah `{rationale, chunks[]}` 包装(无 `repo`/`truncated`;`repo` 输出 `null`、
`truncated` 输出 `false`)。也接受裸 `chunks[]` 列表。`slice_dir`/`scripts_dir`/`input_path`/
`checkpoint_path`/`done_marker` **仅存于本 stdout**,不写入磁盘 schema(切片落 `<slice_dir>` 下
ephemeral、随 `security-scan/` gitignore)。

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
