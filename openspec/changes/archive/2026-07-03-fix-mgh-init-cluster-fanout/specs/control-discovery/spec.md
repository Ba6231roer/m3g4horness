## ADDED Requirements

### Requirement: Cluster inventory file contract

`clusters.json`(由 `discover_controls.py` 产出)MUST 是一个**包装字典**`{repo, clusters[], truncated}`,
其中 `clusters[]` 为 T1 隔离单元列表,**不是**顶层数组。每条 Cluster 记录 SHALL 携带
`cluster_id`、`category`、`kind`、`shape∈{centralized,distributed}`、`evidence_files[]`、
`usage_sites[]`、`candidate_ids[]`(源 `discover_controls.py:409` 的 `form_clusters`)。簇级
MUST NOT 携带 `entry_points`(`entry_points` 在 candidate 上,仅 distributed shape 被 set)。
该结构 SHALL 在 `core/contracts/init/clusters.md` 落定为唯一 I/O 契约。

#### Scenario: clusters.json is a wrapper dict, not a bare list
- **WHEN** `discover_controls.py` 写出 `clusters.json`
- **THEN** 顶层为对象 `{repo, clusters, truncated}`;簇列表在 `clusters` 键下,对顶层 `len()` 得 3 而非簇数

#### Scenario: Cluster record shape is documented and stable
- **WHEN** 消费者(init-induct / init-survey / list_clusters)读取一条簇
- **THEN** 该记录含 `cluster_id/category/kind/shape/evidence_files[]/usage_sites[]/candidate_ids[]`,且无簇级 `entry_points`

#### Scenario: Contract file exists as single source of truth
- **WHEN** 检查 `core/contracts/init/`
- **THEN** 存在 `clusters.md`,逐字段描述包装结构与 Cluster 记录,与 `candidates.md`/`inventory.md` 并列

### Requirement: Deterministic cluster enumeration for T1 fan-out

`/mgh-init` 的编排器 MUST 经确定性叶脚本 `core/scripts/list_clusters.py` 取得 T1 工作清单,
MUST NOT 手搓 `py -c "import json…"` 式内省、MUST NOT 对 `clusters.json` 顶层做 `len()`
(那是包装字典的 key 数,非簇数)。`list_clusters.py` SHALL 读 `<target>/.mgh-init/clusters.json`
并扫 `<target>/.mgh-init/checkpoints/t1/*.done`,stdout 输出结构化 JSON
`{repo,total,done,pending[],truncated}`,`pending[]` 每项含
`{cluster_id,category,kind,shape,evidence_files[],candidate_count}`;stderr 仅走诊断/进度;
退出码 `0/1/2`。脚本的 `--help` 即其 CLI 契约(承 R5.1)。簇数权威真相源 =
`discover_controls.py` stdout `clusters` 字段 或 `list_clusters.py` stdout `total`。

#### Scenario: Orchestrator enumerates clusters via the leaf script
- **WHEN** 编排器进入 T1 fan-out(步骤 4)
- **THEN** 它调用 `list_clusters.py` 取 `pending[]`,据此逐簇扇出 `init-induct`;不出现手搓 JSON 内省

#### Scenario: list_clusters reports total vs done for resume
- **WHEN** 部分簇已 done(`checkpoints/t1/<cluster_id>.json.done` 存在)后再次运行
- **THEN** `list_clusters.py` stdout 的 `done` 反映已完成数,`pending[]` 仅含未完成簇,`total = done + len(pending)`

#### Scenario: list_clusters is self-contained and offline
- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_clusters.py --clusters <dir>/clusters.json --checkpoints <dir>/checkpoints/t1` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8 读入、零第三方依赖),stdout 为合法 JSON

#### Scenario: Empty or truncated clusters handled without silent truncation
- **WHEN** `clusters.json` 的 `clusters[]` 为空,或 `truncated: true`
- **THEN** `list_clusters.py` 输出 `total:0`(空)或保留 `truncated: true`(截断显式告警),退出码仍 `0`,不静默丢信息

### Requirement: init-survey is optional, advisory, and non-fatal

init-survey 子阶段 SHALL 是**可选**的;其产出 `i1_enriched.json` 当前仅作**审计/T2 参考**,
**不是** T1(`init-induct`)的输入(T1 直接读 `clusters.json`)。`i1_enriched.json` 缺失 MUST NOT
阻断流水线、MUST NOT 触发致命错误处理。当簇数过大(单 subagent 上下文装不下整仓簇)时,编排器
SHALL 跳过 init-survey。命令壳 MUST 在步骤 3 显式声明上述 optional/advisory/non-fatal/bounded 语义。

#### Scenario: Missing i1_enriched does not break the run
- **WHEN** init-survey 未产出 `i1_enriched.json`(被跳过或返回空)
- **THEN** 编排器不报致命错误,T1 继续从 `clusters.json` 正常扇出

#### Scenario: init-survey skipped on large cluster count
- **WHEN** `list_clusters.total` 超过壳声明的上界
- **THEN** 编排器跳过 init-survey 步骤,直接进入 T1,并在摘要披露该跳过

#### Scenario: Shell declares the advisory semantics
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md` 步骤 3
- **THEN** 两壳均显式标注 init-survey 为 optional + advisory(非 T1 输入)+ non-fatal + 大簇跳过
