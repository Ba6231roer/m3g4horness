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

**canonical id 收集器的整装守卫(分片派生仅对真超预算簇)**:整簇 id + `::shard-<n>` 分片 id 的
canonical id 收集器(枚举器自身的 done/failed 判定与 `resume_state.py` 的复算**共享导入**,单一
真相)SHALL 仅对「绝对化后整装输入字节 > `--max-unit-bytes`」的簇派生分片 id;整装簇(含无候选
命中簇)SHALL NOT 派生任何分片 id——收集器返回集 SHALL 与物化可写集逐簇一致(整装簇物化为整簇
单元,永无 `<cid>::shard-0` 输入文件,故其 id 集中永无该 id)。分片计划的整装判据 SHALL 与物化
路径的整装判据用同一度量(候选命中绝对化后的整装字节),杜绝「判据说切、物化说整装」或反向漂移。

**确定性小簇打包(配额摊薄,opt-in)**:脚本 SHALL 另支持 `--pack-bytes B`(默认 `0` = 关闭,既有
行为逐字节不变)与 `--pack-max N`(每包成员上限,默认 8)。`--pack-bytes > 0` 时,枚举单元从簇
平移为**包**:同 category 内、单簇 `bytes` ≤ `--max-unit-bytes` 的簇(oversize 与 `::shard-<n>`
子单元 SHALL NEVER 入包),按 `(bytes 升序, cluster_id 字典序)` 排序后贪心装包——加入下一簇会
超过 `--pack-bytes` 或 `--pack-max` 即封包开新包。包 id SHALL 为
`pack::<category>::<sha8(成员 cluster_id 排序拼接)前 8 位 hex>`:分区与 id 都 SHALL 是
`clusters.json` + flag 取值的**纯函数**(同输入同包同 id,跨 run 稳定)。打包模式下 `pending[]`
每项 SHALL 为包级 slim 壳——`cluster_id` 字段载**包 id**(下游派发器/ack 状态机零改动复用该
字段位),`input_path` 载**合并 input 文件**(成员完整记录的数组,单文件一次读摊薄),并新增
`members[]`:`{cluster_id, input_path, checkpoint_path, done_marker, bytes}`(成员级,全
`Path.resolve()` 绝对,逐字透传)。`total` SHALL 为包数;stdout SHALL 另披露簇级计数
`cluster_total`/`cluster_done`。**包 pending 判定 SHALL 从成员 marker 派生**:包 pending ⟺
≥1 成员的 `.done` marker 不存在;成员级 `.done`/`.failed` marker 仍是唯一真相源与恢复粒度
(crash 中断的包重派时,已完成成员由任务模板指示跳过)。`--pack-bytes 0`(或缺省)SHALL 走
既有 per-cluster 路径,stdout 形态逐字节不变(无 `members[]`/`cluster_total` 新字段亦不出现在
关闭路径)。

`--materialize` 写入的 input 文件名 stem SHALL 受长度上限约束(见「Fan-out checkpoint paths are
deterministic absolute values」),使任何 `cluster_id`(含 legacy/回归产出的超长 id)都能写出文件。
打包模式的合并 input 文件名 stem SHALL 同受该上限约束(包 id 含 `sha8` 判别尾,长度有界)。
**单簇物化写失败 MUST 隔离**:某簇 `_resolve_units` 抛 `OSError`(含磁盘写错、legacy 超长 id 之外的
不可写情形)时,系统 SHALL 为该簇写 `.failed` 终态 marker(body `{unit,reason,tier}`;文件名经 stem
截长后可写),stderr 报原因、stdout `failed` 计数 +1、**批次继续物化其余簇,退出码仍 `0`**——NEVER
因单簇失败整批 abort。若 `.failed` marker 亦写不进(运行目录系统级损坏)→ 退出码 `2` fail-loud。
打包模式下物化失败的簇 SHALL 被排除出任何包(它已有终态 marker,不再是 pending)。

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
- **THEN** `list_clusters.py` 按候选命中组切分为 `<cluster_id>::shard-<n>` 子单元,
  每子单元 `bytes` ≤ `--max-unit-bytes` 且有独立 `input_path`/`checkpoint_path`;`pending[]` 不出现超阈值整簇

#### Scenario: Fitting cluster derives no shard id(整装守卫)

- **WHEN** 某 cluster 的整装输入(候选命中绝对化后)≤ `--max-unit-bytes`,以真实候选 + 该预算调
  canonical id 收集器
- **THEN** 该簇贡献的 id 集恰为 `[<cluster_id>]`,不含任何 `<cluster_id>::shard-<n>` 派生 id(与
  物化路径「整装写整簇单元」逐簇一致);修复前该入参组合会给每个含候选簇派生一个永无 marker 的
  `::shard-0` 幽灵 id,毒化任何以该收集器计数 id 的消费方

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

#### Scenario: Packing partitions deterministically within one category

- **WHEN** 同一 `clusters.json` 以相同 `--pack-bytes`/`--pack-max` 重复枚举两次(任意 cwd、任意运行目录)
- **THEN** 两次产出的包集合逐字节一致:同成员集、同包 id(`pack::<category>::<sha8>`)、同合并
  input 内容;任一成员 id/bytes 变化 → 受影响包的 id 随之变化(纯函数,无隐藏状态)

#### Scenario: Packing never mixes categories nor admits oversize members

- **WHEN** 打包开启,存在跨 category 的小簇与一条 oversize 簇
- **THEN** 每个包的成员 category 唯一;oversize/`::shard-<n>` 单元以独立单元出现在 `pending[]`
  (形态与关闭打包时一致),NEVER 成为任何包的成员

#### Scenario: Pack pending derives from member markers, done members are excluded from work

- **WHEN** 某包 4 个成员中 1 个已有 `.done` marker,包被重派
- **THEN** 该包仍在 `pending[]`(≥1 成员缺 marker);任务模板指示 subagent 跳过已有 marker 的
  成员,仅处理其余 3 个;全部成员 marker 就位后该包从 `pending[]` 消失,`cluster_done` +4

#### Scenario: Packing off is byte-identical to the legacy path

- **WHEN** 不传 `--pack-bytes`(或传 `0`)运行新旧两版 `list_clusters.py`
- **THEN** stdout JSON 逐字段一致(不出现 `members[]`/`cluster_total`/`cluster_done`),包逻辑
  零执行;`--pack-max` 单独传入而 `--pack-bytes` 为 0 时 SHALL 退出码 2 拒识(无效组合)
