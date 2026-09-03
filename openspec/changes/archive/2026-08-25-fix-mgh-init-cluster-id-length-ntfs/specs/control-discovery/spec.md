# control-discovery Specification [MODIFIED]

## MODIFIED Requirements

### Requirement: Cluster inventory file contract

`clusters.json`(由 `discover_controls.py` 产出)MUST 是一个**包装字典**`{repo, clusters[], truncated}`,
其中 `clusters[]` 为 T1 隔离单元列表,**不是**顶层数组。每条 Cluster 记录 SHALL 携带
`cluster_id`、`category`、`kind`、`shape∈{centralized,distributed}`、`evidence_files[]`、
`usage_sites[]`、`candidate_ids[]`(源 `discover_controls.py:409` 的 `form_clusters`)。簇级
MUST NOT 携带 `entry_points`(`entry_points` 在 candidate 上,仅 distributed shape 被 set)。
该结构 SHALL 在 `core/contracts/init/clusters.md` 落定为唯一 I/O 契约。

`cluster_id` SHALL 长度有界(总长 ≤ 160 字符):当显示部分(含 home/file 路径槽位)超预算时,系统 SHALL
对显示槽位做截断(路径保留目录头 + 文件名尾 + 槽位 hash 判别),使总长不超界;但尾部 `::{sha8}` 判别段
SHALL 始终对**未截断的完整 key** 计算并保留——同一输入下任何簇的 sha8 判别尾与引入长度约束前**逐字相同**,
长度本就在界内的短 id 其完整 `cluster_id` 亦逐字不变。当 `home == file`(路径被塞进类名槽位)时,系统
SHALL 去重显示槽位(同一路径不重复出现两次)。长度上界保证所有以 `cluster_id` 派生的文件名
(input/checkpoint/`done`/`failed`/`slice_dir`)落在 NTFS 255 字符单分量上限内可写。

#### Scenario: clusters.json is a wrapper dict, not a bare list
- **WHEN** `discover_controls.py` 写出 `clusters.json`
- **THEN** 顶层为对象 `{repo, clusters, truncated}`;簇列表在 `clusters` 键下,对顶层 `len()` 得 3 而非簇数

#### Scenario: Cluster record shape is documented and stable
- **WHEN** 消费者(init-induct / init-survey / list_clusters)读取一条簇
- **THEN** 该记录含 `cluster_id/category/kind/shape/evidence_files[]/usage_sites[]/candidate_ids[]`,且无簇级 `entry_points`

#### Scenario: Contract file exists as single source of truth
- **WHEN** 检查 `core/contracts/`
- **THEN** 存在 `init/clusters.md`,逐字段描述包装结构与 Cluster 记录,与 `candidates.md`/`inventory.md` 并列

#### Scenario: overlong path-in-class-slot cluster_id is bounded
- **WHEN** 一条 centralized 候选的 anchor 无 class/method,`home` 回退为完整文件路径且与 `file` 相同(路径被塞进类名槽位),未截断 id 将达 267 字符
- **THEN** `form_clusters` 产出的 `cluster_id` 总长 ≤ 160;显示槽位保留路径目录头 + 文件名尾(同一路径不重复出现两次);尾部 `::{sha8}` 与对**未截断完整 key** 算得的值相同(判别身份不变)

#### Scenario: short cluster_ids are byte-identical after the bound
- **WHEN** 一条簇的 `category`/`home`/`file` 拼接后总长本就在 160 内(普通项目常见形态)
- **THEN** 其 `cluster_id` 与引入长度约束前**逐字相同**(截断仅作用于超长 id)

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

`--materialize` 写入的 input 文件名 stem SHALL 受长度上限约束(见「Fan-out checkpoint paths are
deterministic absolute values」),使任何 `cluster_id`(含 legacy/回归产出的超长 id)都能写出文件。
**单簇物化写失败 MUST 隔离**:某簇 `_resolve_units` 抛 `OSError`(含磁盘写错、legacy 超长 id 之外的
不可写情形)时,系统 SHALL 为该簇写 `.failed` 终态 marker(body `{unit,reason,tier}`;文件名经 stem
截长后可写),stderr 报原因、stdout `failed` 计数 +1、**批次继续物化其余簇,退出码仍 `0`**——NEVER
因单簇失败整批 abort。若 `.failed` marker 亦写不进(运行目录系统级损坏)→ 退出码 `2` fail-loud。

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

#### Scenario: input filename stem is length-capped for overlong cluster_id
- **WHEN** 一条 legacy `cluster_id` 超过文件名 stem 上限(如 267 字符,旧版 discover 产出、未经上游长度约束)
- **THEN** `--materialize` 写出 `<inputs>/<safe(id)>.input.json`,其文件名 stem 被截到 ≤ 上限(保留尾部判别段),
  文件成功创建;envelope `cluster_id` 字段仍为完整 canonical id

#### Scenario: one unmaterializable cluster does not abort the batch
- **WHEN** `clusters.json` 含一条物化写失败(`OSError`)的簇,`--materialize` 枚举它
- **THEN** 该簇被写 `.failed` 终态 marker(文件名可写)、stderr 报原因、stdout `failed` 计数 +1,
  **其余簇照常物化**,退出码 `0`;若 `.failed` 亦写不进 → 退出码 `2` fail-loud,不静默丢簇

### Requirement: Stage-boundary contract checks

每个 stage 产物的产出者 SHALL 暴露 `--check`(或独立 validator),编排器跑完一步、进下一步前 MUST
运行之;失败 MUST fail-loud(退出码 2)并回退重跑(泛化既有 `assemble_rules.py --check` 范式,承
openspec validate-at-boundary,FD7)。覆盖:`discover_controls.py --check`(candidates/clusters wrapper
+ 每条 `source` + cluster_id 唯一 **+ cluster_id 长度 ≤ 160**)、`plan_scout.py --check`(batches 非空除非
0 target、每批 bytes≤ budget、needs_slice 仅含超批文件)、`merge_scout.py --check`(每条 `source:"scout"`
+ `file:line` + **每条 `category` 非空** + **破损 JSON(无法 parse)亦属边界失败、退出码 2** + 给
`JSONDecodeError` 的 `lineno/colno/msg` 与错位附近字节窗诊断)、`validate_inventory.py`(vvah
design_controls 兼容 + evidence 锚点 + category→kind 归一)、既有 `assemble_rules.py --check`(rules 纯净性)。

`merge_scout.py --check` 对破损 JSON SHALL 返回退出码 `2`(非 `1`),使编排器闸门(仅在退出码 2 回退)
正确触发重跑 S4;诊断 SHALL 含 `lineno`/`colno`/`msg` 字段供定位。`category` 校验 SHALL 断言非空(不断言
枚举归属,枚举归一交给 `validate_inventory.py`)。

#### Scenario: Check passes on a well-formed artifact
- **WHEN** 编排器对刚产出的 `scout_plan.json` 运行 `plan_scout.py --check`
- **THEN** 退出码 0,编排器进入下一步

#### Scenario: Check fails loud on a corrupted artifact
- **WHEN** 某 batch 的 `bytes` 超过 `--scout-batch-bytes`(或 wrapper 损坏)
- **THEN** `--check` 退出码 2,编排器回退重跑该步,不带着破损产物继续

#### Scenario: merge_scout --check rejects a candidate missing category
- **WHEN** `scout_candidates.json` 的某条 candidate 缺 `category` 字段(或为空)
- **THEN** `merge_scout.py --check` 退出码 2,violations 报告该 candidate 的 index 与 issue,编排器回退重跑 S4

#### Scenario: merge_scout --check rejects malformed JSON with line:col diagnostics
- **WHEN** `scout_candidates.json` 不是合法 JSON(如字符串值内转义错位)
- **THEN** `merge_scout.py --check` 退出码 `2`(非 `1`),stderr/stdout 诊断含 `lineno`/`colno`/`msg` 与错位附近字节窗,编排器回退重跑 S4

#### Scenario: Inventory validated against design_controls schema
- **WHEN** T2 产出 `controls_inventory.json`
- **THEN** `validate_inventory.py`(或 T2 后 check)断言 vvah 兼容字段 + 每条 evidence 锚点 + category→kind 归一,失败退出码 2

#### Scenario: discover --check rejects an overlong cluster_id
- **WHEN** `clusters.json` 的某条 `cluster_id` 超 160 字符(producer 回归)
- **THEN** `discover_controls.py --check` 退出码 2,violations 报该簇 index 与「cluster_id 超长」issue,
  编排器在 discover 后、T1 前被闸门拦下

### Requirement: Fan-out checkpoint paths are deterministic absolute values

scout 与 T1 fan-out 的每个待跑单元的**输出路径** SHALL 是由确定性枚举脚本产出的**单一权威绝对路径值**,
而非占位符模板或相对路径。`list_scout_batches.py` 与 `list_clusters.py` 的 stdout `pending[]` 每项
SHALL 额外包含 `checkpoint_path`(待写产物文件的**绝对路径**)与 `done_marker`(对应 `.done` 标记的
**绝对路径**),二者均由该脚本从其 `--checkpoints` 参数(已 `resolve()`)拼单元 id 得出。

`checkpoint_path` / `done_marker` 的**文件名分量** SHALL 经文件系统消毒(复用 `_safe_name`:`/`、`\`、`:`
→ `_`),使含 `::`(NTFS Alternate-Data-Stream 分隔符)或 `/` 的 `cluster_id` / shard id 派生的文件名在
Windows NTFS 上可写(否则 `write_text` 报 `OSError [Errno 22]`)。除字符消毒外,`_safe_name` SHALL **兼做
stem 长度截断**:文件名 stem 超上限(200 字符)时,SHALL 截断但**保留尾部 ~60 字符判别段**(含 sha8 尾),
使超长 id 派生的文件名**亦**可写、且两个不同 id 在磁盘上**不碰撞**。canonical 单元 id(含 `::`)SHALL 原样
保留为 slim envelope 的 `cluster_id` 字段与检查点记录内的 `unit` 字段——**只有文件名被编码,身份不变**;
done 检测读记录内 `unit` 字段、不依赖文件名,故消毒与截断均不影响 resume 匹配。

编排器 SHALL 把 `list_*` stdout 中的 `checkpoint_path` / `done_marker` **逐字透传**进对应 subagent 的 task 输入,
MUST NOT 自行用 `<target>` / `<batch_id>` / `<cluster_id>` 占位符拼路径,也 MUST NOT 用 `py -c` 算路径。

`init-scout` / `init-induct` subagent 的 stage 提示词 SHALL 把 `checkpoint_path`(与 `done_marker`)
列为**编排器逐字给定**的输入字段,其 Output 段 SHALL 要求「Write 恰好 `checkpoint_path` 给定的绝对路径
并 touch `done_marker`」;且 SHALL 以硬边界 `NEVER` 禁止:自行拼路径、发明文件名(如 `xxxraw.json`)、
写相对路径、写到项目目录之外(含盘符根)。

路径 SHALL 为绝对路径(经 `Path.resolve()`),使其对 subagent 的任意工作目录安全。运行时 hook(在
`MGH_INIT_ACTIVE` 运行域内)SHALL 拦截 `Write`/`Edit` 其 resolved 目标不以 resolved `MGH_TARGET`
为前缀的调用,失败 fail-loud(退出码 2)+ stderr 指向 `list_*` stdout 的 `checkpoint_path` 字段;
`MGH_TARGET` 缺失时该拦截条放行(降级)。`MGH_TARGET` SHALL 由编排器在起步段设置,且其取值 MUST
复用既有确定性脚本的绝对路径 stdout 字段(如 `discover_controls.py` 的 `repo`),MUST NOT 经 `py -c`
现算(守 `harden-mgh-init-orchestration-discipline` 的微脚本明线)。

#### Scenario: Enumeration script emits absolute checkpoint path per pending unit
- **WHEN** `list_scout_batches.py --scout-plan …/scout_plan.json --checkpoints …/checkpoints/scout` 运行
- **THEN** stdout `pending[]` 每项含 `checkpoint_path` 与 `done_marker`,二者均为绝对路径,且分别等于
  `<绝对 checkpoints dir>/<safe(batch_id)>.json` 与 `<绝对 checkpoints dir>/<safe(batch_id)>.json.done`
  (`safe` = `_safe_name`,`batch_id` 通常不含 `::`,消毒为幂等 no-op)

#### Scenario: Checkpoint filename is sanitized for NTFS-unsafe cluster_id
- **WHEN** `list_clusters.py` 对一条 `cluster_id` 含 `::`(如 `authorization::SecCfg::ab12cd34`)、或 shard id
  含 `::shard-<n>` 的待跑单元产出 `pending[]`,运行宿主为 Windows
- **THEN** 该项 `checkpoint_path` / `done_marker` 的**文件名分量**把 `::`(及 `/` `\`)替换为 `_`
  (可经 `write_text` 写下、不报 Errno 22);该项 envelope `cluster_id` 字段仍为**原始**含 `::` 的 canonical id;
  subagent 写入的检查点记录内 `unit` 字段为该 canonical id;`_done_ids` 据此 `unit` 字段正确判终态

#### Scenario: Checkpoint filename is length-capped for overlong cluster_id
- **WHEN** `list_clusters.py` 对一条 legacy `cluster_id` 达 267 字符的待跑单元产出 `pending[]`,宿主为 Windows
- **THEN** 该项 `checkpoint_path`/`done_marker`/`failed_marker` 的文件名分量被截到 ≤ 200(保尾判别段),
  文件名可写、不与其它 id 碰撞;envelope `cluster_id` 仍为原始 canonical id;`_done_ids` 读记录 `unit`
  字段判终态,不受文件名截断影响

#### Scenario: Existing on-disk artifact schema unchanged
- **WHEN** 本变更生效后审阅 `checkpoints/scout/<safe(batch_id)>.json` 与 `checkpoints/t1/<safe(cluster_id)>.json`
- **THEN** 其磁盘**内容** schema 与变更前一致(记录内 `unit` = canonical id、`status`、`out`、`bytes` 等);
  文件名经 `_safe_name` 消毒(含 stem 长度截断);`checkpoint_path`/`done_marker` 仅存在于 `list_*` stdout,不写入产物文件内容

#### Scenario: Orchestrator passes path verbatim, never interpolates
- **WHEN** 编排器取得 scout / T1 的 `pending[]` 并起 subagent
- **THEN** subagent task 输入里的输出路径**逐字等于** `list_*` stdout 的 `checkpoint_path`,
  编排器**不**出现 `<target>`/`<batch_id>`/`<cluster_id>` 占位符拼装,也**不** `py -c` 算路径

#### Scenario: Subagent writes exactly the given absolute path
- **WHEN** 一个 init-scout / init-induct subagent 在工作目录 ≠ 项目根(含 Windows 盘符相对 cwd)的隔离上下文运行
- **THEN** 它把产物写到输入字段 `checkpoint_path` 给定的绝对路径(落在 `<target>/.mgh-init/checkpoints/<tier>/` 下),
  **不**写到盘符根或任何项目外目录,**不**发明文件名

#### Scenario: Out-of-tree write is blocked at runtime
- **WHEN** 运行域(`MGH_INIT_ACTIVE=1`)内一个 `Write`/`Edit` 的 resolved 目标不以 resolved `MGH_TARGET` 为前缀
- **THEN** PreToolUse hook 以退出码 2 拒绝,并在 stderr 给出「路径须取自 `list_*` stdout 的 `checkpoint_path`」recipe
