# control-discovery Delta

承 `harden-mgh-init-context-budget`:三个扇出枚举叶脚本(`list_clusters`/`list_scout_batches`/
`list_rule_jobs`)增 per-unit **输入物化**(`--materialize`)+ `input_path`/`bytes`/`oversize` +
`--offset`/`--limit` 分页;编排器 **NEVER** 整份读多单元产物;subagent 读自己的 `input_path`。预算语义
统一落 `request-context-budget` 能力;本 delta 只改 `control-discovery` 的枚举契约。T3 此前**无**独立
枚举 requirement(仅散见于「Deterministic scripts are orchestrator black boxes」),本 delta 补齐。

## MODIFIED Requirements

### Requirement: Deterministic cluster enumeration for T1 fan-out

`/mgh-init` 的编排器 MUST 经确定性叶脚本 `core/scripts/list_clusters.py` 取得 T1 工作清单,
MUST NOT 手搓 `py -c "import json…"` 式内省、MUST NOT 对 `clusters.json` 顶层做 `len()`
(那是包装字典的 key 数,非簇数)、MUST NOT **整份读** `clusters.json` 进编排器上下文(完整记录经
`--materialize` 下沉到 per-unit input 文件,见 `request-context-budget`)。`list_clusters.py` SHALL 读
`<target>/.mgh-init/clusters.json` 并扫 `<target>/.mgh-init/checkpoints/t1/*.done`,stdout 输出结构化
JSON `{repo,total,done,pending[],truncated,offset,limit,effective_limit,shrunk}`,`pending[]` 每项为
**slim 壳**`{cluster_id,category,kind,shape,candidate_count,input_path,checkpoint_path,done_marker,bytes,oversize}`
(**不含** `evidence_files[]`/`usage_sites[]`/候选命中——已下沉进 `input_path` 文件);stderr 仅走诊断/进度;
退出码 `0/1/2`。脚本 SHALL 支持 `--materialize <dir>`(把每簇完整输入写到
`<dir>/<cluster_id>.input.json` + 报 `input_path`/`bytes`/`oversize`,无该 flag 时回退 read-only lite 壳
向后兼容)、`--offset`/`--limit`(分页)、`--max-unit-bytes`(超阈值簇切分为 `<cluster_id>::shard-<n>`
子单元或标 `oversize`)。当某页序列化字节 > `--orch-budget-bytes` 时 SHALL 自动收紧 `--limit`、报
`effective_limit`+`shrunk:true`。脚本的 `--help` 即其 CLI 契约(承 R5.1)。簇数权威真相源 =
`discover_controls.py` stdout `clusters` 字段 或 `list_clusters.py` stdout `total`。

#### Scenario: Orchestrator enumerates clusters via the leaf script
- **WHEN** 编排器进入 T1 fan-out(步骤 4)
- **THEN** 它调用 `list_clusters.py --materialize <inputs/t1>` 取 `pending[]`,据此逐簇扇出 `init-induct`,
  向 subagent **透传 `input_path`**;不出现手搓 JSON 内省,不整份读 `clusters.json`

#### Scenario: list_clusters reports total vs done for resume
- **WHEN** 部分簇已 done(`checkpoints/t1/<cluster_id>.json.done` 存在)后再次运行
- **THEN** `list_clusters.py` stdout 的 `done` 反映已完成数,`pending[]` 仅含未完成簇,`total = done + len(pending)`

#### Scenario: list_clusters is self-contained and offline
- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_clusters.py --clusters <dir>/clusters.json --checkpoints <dir>/checkpoints/t1 --materialize <dir>/inputs/t1` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8 读入、零第三方依赖),stdout 为合法 JSON,per-unit input 文件落 `<dir>/inputs/t1/`

#### Scenario: Empty or truncated clusters handled without silent truncation
- **WHEN** `clusters.json` 的 `clusters[]` 为空,或 `truncated: true`
- **THEN** `list_clusters.py` 输出 `total:0`(空)或保留 `truncated: true`(截断显式告警),退出码仍 `0`,不静默丢信息

#### Scenario: Slim envelope excludes variable-length payload
- **WHEN** 审阅 `list_clusters.py` stdout 的 `pending[]` 元素
- **THEN** 壳含 `{cluster_id,category,kind,shape,candidate_count,input_path,checkpoint_path,done_marker,bytes,oversize}`,
  **不含** `evidence_files[]`/`usage_sites[]`(已下沉进 `input_path` 文件)

#### Scenario: Oversize cluster is sharded within the unit budget
- **WHEN** 某 cluster 物化输入 `bytes` > `--max-unit-bytes`
- **THEN** `list_clusters.py` 按 `evidence_files`/`usage_sites` 组切分为 `<cluster_id>::shard-<n>` 子单元,
  每子单元 `bytes` ≤ `--max-unit-bytes` 且有独立 `input_path`/`checkpoint_path`;`pending[]` 不出现超阈值整簇

#### Scenario: Work-list page shrinks to the orchestrator budget
- **WHEN** 一页 `pending[]` 序列化字节 > `--orch-budget-bytes`
- **THEN** `list_clusters.py` 自动收紧 `--limit`,stdout 报 `effective_limit` + `shrunk:true`(stderr 告警),
  编排器据 `offset`/`effective_limit` 翻页

### Requirement: Deterministic scout-batch enumeration for fan-out

`/mgh-init` 的编排器 MUST 经确定性叶脚本 `core/scripts/list_scout_batches.py` 取得 scout 工作清单
(对标 T1 的 `list_clusters.py`,闭合 FD3 的扇出不对称),MUST NOT **整份读** `scout_plan.json` 进编排器
上下文。`list_scout_batches.py` SHALL 读 `<target>/.mgh-init/scout_plan.json::batches[]` 并扫
`<target>/.mgh-init/checkpoints/scout/*.json.done`,stdout 输出结构化 JSON
`{repo,total,done,pending[],truncated,offset,limit,effective_limit,shrunk}`,`pending[]` 每项含
`{batch_id,targets_count,bytes,needs_slice[],input_path,checkpoint_path,done_marker,oversize}`;stderr 仅
诊断/进度;退出码 `0/1/2`;`--help` 即其 CLI 契约(承 R5.1)。`total = len(batches[])`,
`done = #已 .done`,`pending = total − done`。脚本 SHALL 支持 `--materialize <dir>`(把每批完整 `targets[]`
输入写到 `<dir>/<batch_id>.input.json` + 报 `input_path`)、`--offset`/`--limit`(分页)、
`--max-unit-bytes`(与 `plan_scout --batch-bytes` 取 `min` 作硬上限;超 `--big-file-bytes` 文件强制
`needs_slice` 走 `chunk_sources`)。当某页字节 > `--orch-budget-bytes` 时 SHALL 自动收紧 `--limit`、报
`effective_limit`+`shrunk:true`。脚本 MUST 自定位 `sys.path`、utf-8 读入、零第三方依赖、任意 cwd 可 `py`
(承 R5.3a)。

#### Scenario: Orchestrator enumerates scout batches via the leaf script
- **WHEN** 编排器进入 scout fan-out(步骤 3b)
- **THEN** 它调用 `list_scout_batches.py --materialize <inputs/scout>` 取 `pending[]`,据此逐批扇出
  `init-scout`,向 subagent **透传 `input_path`**;不出现手搓 JSON 内省,不整份读 `scout_plan.json`

#### Scenario: list_scout_batches reports total vs done for resume
- **WHEN** 部分批已 done(`checkpoints/scout/<batch_id>.json.done` 存在)后再次运行
- **THEN** stdout 的 `done` 反映已完成批数,`pending[]` 仅含未完成批,`total = done + len(pending)`

#### Scenario: list_scout_batches is self-contained and offline
- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_scout_batches.py --scout-plan <dir>/scout_plan.json --checkpoints <dir>/checkpoints/scout --materialize <dir>/inputs/scout` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8 读入、零第三方依赖),stdout 为合法 JSON,per-unit input 文件落 `<dir>/inputs/scout/`

#### Scenario: Empty or truncated scout plan handled without silent truncation
- **WHEN** `scout_plan.json::batches[]` 为空,或 `truncated: true`
- **THEN** `list_scout_batches.py` 输出 `total:0`(空)或保留 `truncated: true`(显式告警),退出码仍 `0`,不静默丢信息

#### Scenario: Oversize batch respects the unit budget via slicing
- **WHEN** 某批 input `bytes` > `--max-unit-bytes`(或含 > `--big-file-bytes` 文件)
- **THEN** 该文件入 `needs_slice[]`,`init-scout` 经 `chunk_sources.py` 切片后读 slice,NEVER 整文件喂 LLM

#### Scenario: Work-list page shrinks to the orchestrator budget
- **WHEN** 一页 `pending[]` 序列化字节 > `--orch-budget-bytes`
- **THEN** `list_scout_batches.py` 自动收紧 `--limit`,stdout 报 `effective_limit` + `shrunk:true`,编排器翻页

> T3(`list_rule_jobs.py`)的等价物化/分页/预算改造见 `rules-emission` delta(T3 rule 产出归该 capability);
> 三 tier 的统一语义由 `request-context-budget` 横切能力统辖。
