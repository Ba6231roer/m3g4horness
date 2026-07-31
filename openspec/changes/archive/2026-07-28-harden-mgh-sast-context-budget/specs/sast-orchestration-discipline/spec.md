# sast-orchestration-discipline Delta

承 `harden-mgh-init-context-budget`(泛化):`/mgh-sast` 的两个扇出枚举叶脚本 `list_chunks.py`(s4)/
`list_verify_jobs.py`(s6)采纳 `request-context-budget` 横切能力——per-unit **输入物化** + slim 分页待办壳 +
字节预算;编排器 **NEVER** 整份读 `s3_chunks.json`/`s5_filtered.json`;`sast-deepdive`/`sast-verify` 读自己的
`input_path`。机制统辖见 `request-context-budget`。

## MODIFIED Requirements

### Requirement: Deterministic chunk enumeration for s4 fan-out

`/mgh-sast` 的编排器 MUST 经确定性叶脚本 `core/scripts/list_chunks.py` 取得 s4 工作清单(对标
mgh-init `list_clusters.py`,闭合 s4 扇出不对称),MUST NOT **整份读** `s3_chunks.json` 进编排器上下文。
`list_chunks.py` SHALL 读 s3 产物的 `chunks[]` 并扫 `<repo>/security-scan/checkpoints/s4/*.json.done`,stdout
输出结构化 JSON `{repo,total,done,pending[],truncated,offset,limit,effective_limit,shrunk}`,`pending[]` 每项
(slim 壳)含 `{chunk_id,files_count,threat_id,input_path,checkpoint_path,done_marker,bytes,oversize}`(完整
`files[]`/`hypothesis` 下沉进 `input_path` 文件);stderr 仅诊断/进度;退出码 `0/1/2`;`--help` 即其 CLI 契约
(承 R5.1)。`total = len(chunks[])`,`done = #已 .done`,`pending = total − done`。脚本 SHALL 支持
`--materialize <dir>`(把每 chunk 完整输入写到 `<dir>/<chunk_id>.input.json` + 报 `input_path`/`bytes`/
`oversize`)、`--offset`/`--limit`(分页)、`--max-unit-bytes`(超阈值且含 > `--big-file-bytes` 文件 → 强制
`needs_slice` 走 `chunk_sources` 切片,NEVER 整文件喂 LLM)。当某页字节 > `--orch-budget-bytes` 时 SHALL 自动
收紧 `--limit`、报 `effective_limit`+`shrunk:true`。`sast-deepdive` SHALL 读自己的 `input_path`(一个 chunk
的 files + threat + hypothesis)而非编排器内联传记录。脚本 MUST 自定位 `sys.path`、utf-8 读入、零第三方依赖、
任意 cwd 可 `py`(承 R5.3a)。

#### Scenario: Orchestrator enumerates chunks via the leaf script
- **WHEN** 编排器进入 s4 fan-out
- **THEN** 它调用 `list_chunks.py --materialize <inputs/s4>` 取 `pending[]`,据此逐 chunk 扇出
  `sast-deepdive`,向 subagent **透传 `input_path`**;不出现手搓 JSON 内省、`Write _prep_chunks.py` 或整份读 `s3_chunks.json`

#### Scenario: list_chunks reports total vs done for resume
- **WHEN** 部分 chunk 已 done(`checkpoints/s4/<chunk_id>.json.done` 存在)后再次运行
- **THEN** stdout 的 `done` 反映已完成数,`pending[]` 仅含未完成,`total = done + len(pending)`

#### Scenario: list_chunks is self-contained and offline
- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_chunks.py --chunks <dir>/s3_chunks.json --checkpoints <dir>/checkpoints/s4 --materialize <dir>/inputs/s4` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8、零第三方依赖),stdout 为合法 JSON,per-unit input 文件落 `<dir>/inputs/s4/`

#### Scenario: Empty or truncated chunks handled without silent truncation
- **WHEN** `chunks[]` 为空,或 `truncated: true`
- **THEN** `list_chunks.py` 输出 `total:0`(空)或保留 `truncated: true`(显式告警),退出码仍 `0`,不静默丢信息

#### Scenario: Oversize chunk respects the unit budget via slicing
- **WHEN** 某 chunk input `bytes` > `--max-unit-bytes`(或含 > `--big-file-bytes` 文件)
- **THEN** 该文件入 `needs_slice[]`,`sast-deepdive` 经 `chunk_sources.py` 切片后读 slice,NEVER 整文件喂 LLM

#### Scenario: Work-list page shrinks to the orchestrator budget
- **WHEN** 一页 `pending[]` 序列化字节 > `--orch-budget-bytes`
- **THEN** `list_chunks.py` 自动收紧 `--limit`,stdout 报 `effective_limit` + `shrunk:true`,编排器翻页

### Requirement: Deterministic verify-job enumeration for s6 fan-out

`/mgh-sast` 的编排器 MUST 经确定性叶脚本 `core/scripts/list_verify_jobs.py` 取得 s6 工作清单(闭合 s6 扇出
不对称),MUST NOT 手挖 `s5_filtered.json`、MUST NOT **整份读**之进编排器上下文。`list_verify_jobs.py` SHALL
读 s5 产物 `findings[]` 并扫 `<repo>/security-scan/checkpoints/s6/*.json.done`,stdout
`{repo,total,done,pending[],truncated,offset,limit,effective_limit,shrunk}`,`pending[]` 每项(slim 壳)含
`{finding_id,file,line,vuln_class,input_path,checkpoint_path,done_marker,bytes,oversize}`(完整 `source_ref`/
`sink_ref` 下沉进 `input_path` 文件);stderr 仅诊断;退出码 `0/1/2`;`--help` 即 CLI 契约。脚本 SHALL 支持
`--materialize <dir>`(每 finding 完整输入写到 `<dir>/<finding_id>.input.json` + 报 `input_path`/`bytes`/
`oversize`)、`--offset`/`--limit`(分页)、`--max-unit-bytes`(超阈值 → 标 `oversize` + recipe,s6 单 finding
通常不切分)。当某页字节 > `--orch-budget-bytes` 时 SHALL 自动收紧 `--limit`、报 `effective_limit`+
`shrunk:true`。`sast-verify` SHALL 读自己的 `input_path`(该 finding 的 source/sink 锚点 + 上下文)。自定位、
utf-8、零依赖、任意 cwd(承 R5.3a)。

#### Scenario: Orchestrator enumerates verify jobs via the leaf script
- **WHEN** 编排器进入 s6 fan-out
- **THEN** 它调用 `list_verify_jobs.py --materialize <inputs/s6>` 取 `pending[]`,据此逐 finding 扇出
  `sast-verify`,向 subagent **透传 `input_path`**;不手挖 `s5_filtered.json`、不 `py -c`、不整份读之

#### Scenario: list_verify_jobs is resume-aware
- **WHEN** 部分 finding 已 done 后再次运行
- **THEN** `pending[]` 仅含未完成,`total = done + len(pending)`

#### Scenario: list_verify_jobs is self-contained and offline
- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_verify_jobs.py --findings <dir>/s5_filtered.json --checkpoints <dir>/checkpoints/s6 --materialize <dir>/inputs/s6` 执行
- **THEN** 脚本成功(自定位、utf-8、零依赖),stdout 为合法 JSON,per-finding input 文件落 `<dir>/inputs/s6/`

#### Scenario: Work-list page shrinks to the orchestrator budget
- **WHEN** 一页 `pending[]` 序列化字节 > `--orch-budget-bytes`
- **THEN** `list_verify_jobs.py` 自动收紧 `--limit`,stdout 报 `effective_limit` + `shrunk:true`,编排器翻页
