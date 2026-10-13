# fix-mgh-init-enumeration-caliber — control-discovery delta

## MODIFIED Requirements

### Requirement: Shard large files for stable LLM analysis

单文件超过 `--big-file-bytes`(默认 200KB)时,系统 SHALL 先用 `chunk_sources.py`
做**确定性 AST 骨架**(imports/顶层 class/method 签名/注解,零 LLM),再只把「控制候选
函数体 ± 上下文窗口」作为切片喂给 induct,**不得整文件塞入 LLM 上下文**。非 AST 语言
SHALL 回退到带重叠的行窗口。对大文件 shard 的归纳结果,系统 MAY 再跑一道 verify
pass 交叉核验,不一致时降 `confidence`。

**骨架函数节点判定的控制流排除(Java)**:`chunk_sources.py` 的 Java 函数节点判定
(JAVA_DEF 形态)SHALL 排除控制流关键字头——`while`/`for`/`do`/`if`/`switch`/`catch`/
`finally`/`synchronized`/`try`/`return`/`new` 作为「名字 + 参数列表 + `{`」形态命中时 SHALL
NOT 产出函数节点(这些块的行区间不是方法体;Java 是本工具族首要目标语言,把循环/分支块当
方法节点会让大文件按循环体而非方法体切分、外层方法 `line_end` 被截断)。排除 SHALL 是
匹配后按捕获名字的确定性过滤(小写比较),NEVER 改动对真方法(含 `synchronized` 修饰的
方法)的识别。**输入校验**:`--in` 指向不存在的文件 SHALL 退出码 2 fail-loud(subagent
路径 typo 得到「成功 + 空骨架」是错误信号);`--line` 取值 `< 1`(含 0)SHALL 退出码 2 +
recipe(`--line 0` 曾因真值判断静默落入骨架模式,合法请求 0 行不存在)。

#### Scenario: Big file is sharded, not fed whole

- **WHEN** 一个 250KB 的 `LegacyAuthFilter.java` 含控制候选
- **THEN** induct 收到的是候选函数切片(含上下文窗口),而非整文件;切片来自 AST 骨架定位

#### Scenario: Shard disagreement lowers confidence

- **WHEN** 大文件某 shard 的归纳与 verify pass 核验不一致
- **THEN** 该控制 `confidence` 被下调,并在 report 标注

#### Scenario: Java 控制流块不产生函数节点

- **WHEN** 某 Java 文件含 `while (rs.next()) {…}`、`switch (mode) {…}`、`catch (Exception e) {…}`
  块与真方法 `public String mask(String s) {…}`
- **THEN** 骨架的函数节点含 `mask`(含其真实行区间,不被内层控制流块截断 `line_end`),
  不含 while/switch/catch 块节点;`synchronized` **修饰的真方法**(`synchronized void x() {…}`)
  仍被识别,`synchronized (lock) {…}` 块不产生节点

#### Scenario: 不存在的输入文件 fail-loud

- **WHEN** `chunk_sources.py --in <path>` 且该路径不存在
- **THEN** 退出码 2 + stderr 指认路径;NEVER 以「成功 + 空骨架」退出 0

#### Scenario: `--line 0` 被拒识而非落骨架模式

- **WHEN** 调用 `chunk_sources.py --in <file> --line 0 --out <slice.json>`
- **THEN** 退出码 2 + recipe(合法行号 ≥ 1;骨架模式 = 不传 `--line`);NEVER 静默产出整文件骨架

### Requirement: Deterministic cluster enumeration for T1 fan-out

`/mgh-init` 的编排器 MUST 经确定性叶脚本 `core/scripts/list_clusters.py` 取得 T1 工作清单,
MUST NOT 手搓 `py -c "import json…"` 式内省、MUST NOT 对 `clusters.json` 顶层做 `len()`
(那是包装字典的 key 数,非簇数)、MUST NOT **整份读** `clusters.json` 进编排器上下文(完整记录经
`--materialize` 下沉到 per-unit input 文件,见 `request-context-budget`)。`list_clusters.py` SHALL 读
`<target>/.mgh-init/clusters.json` 并扫 `<target>/.mgh-init/checkpoints/t1/*.done`,stdout 输出结构化
JSON `{repo,total,done,failed,pending[],truncated,offset,limit,effective_limit,shrunk}`,`pending[]` 每项为
**slim 壳**`{cluster_id,category,kind,shape,candidate_count,input_path,checkpoint_path,done_marker,bytes,oversize}`
(**不含** `evidence_files[]`/`usage_sites[]`/候选命中——已下沉进 `input_path` 文件);stderr 仅走诊断/进度;
退出码 `0/1/2`。脚本 SHALL 支持 `--materialize <dir>`(把每簇完整输入写到
`<dir>/<cluster_id>.input.json` + 报 `input_path`/`bytes`/`oversize`,无该 flag 时回退 read-only lite 壳
向后兼容)、`--offset`/`--limit`(分页)、`--max-unit-bytes`(超阈值簇切分为 `<cluster_id>::shard-<n>`
子单元或标 `oversize`)。当某页序列化字节 > `--orch-budget-bytes` 时 SHALL 自动收紧 `--limit`、报
`effective_limit`+`shrunk:true`。脚本的 `--help` 即其 CLI 契约(承 R5.1)。簇数权威真相源 =
`discover_controls.py` stdout `clusters` 字段 或 `list_clusters.py` stdout `total`。

**簇级计数三分(切片簇失败不吞失)**:簇级 `done`/`failed` 计数 SHALL 按三分判定——某簇的
全部单元(整簇单元,或被切分时的全部分片单元)`.done` → 该簇计 done;≥1 单元 `.failed` 且
无 pending 单元 → 该簇计 **failed**(该簇因此对 `--retry-failed` 链路可见);否则计 pending。
打包路径的独立(oversize/分片)簇 SHALL 同判。理由〔修复前「全片终态但含失败」的簇落入
done 残差公式——实测 1 簇 2 片全 `.failed` → stdout `{done:1, failed:0}`,分片失败对
`--retry-failed` 不可见、报告披露失真〕。单元级(marker)口径不变,仍是唯一真相源。

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
- **THEN** `list_clusters.py` stdout 的 `done` 反映已完成数,`pending[]` 仅含未完成簇,`total = done + failed + len(pending)`

#### Scenario: 分片全失败的簇计 failed(对 retry-failed 可见)

- **WHEN** 某 1 簇被物化为 2 个 shard 单元、两个 `.failed` marker 全部在盘(无任何 `.done`),
  再次运行 `list_clusters.py`
- **THEN** stdout 报 `done:0, failed:1, pending:0`(簇计 failed);该簇在 `--include-failed`
  重列下以 canonical shard id 重新进入 `pending[]`,`--retry-failed` 链路可见——修复前同一磁盘
  状态实测报 `{done:1, failed:0}`(失败被吞)

#### Scenario: 打包路径独立簇同判三分

- **WHEN** `--pack-bytes > 0` 模式下某独立(oversize)簇的全部 shard 单元 `.failed`
- **THEN** 该簇计 failed(NEVER 计入 `independent_done`);`cluster_done` 只数全 `.done` 簇

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

### Requirement: Fan out scout across parallel isolated byte-bounded batches

scout 深读 SHALL 按**隔离 fan-out**执行(对标 D12 T1→T2 同构):确定性脚本
`plan_scout.py` 对 `skeleton.json` 做噪声剪枝(复用 `EXCLUDE_DIR`)+ 去除 regex 已命中
文件后,把剩余 scout 目标按**字节预算**切批——每批累计 `bytes ≤ --scout-batch-bytes`
(默认 96KB),且分批前先按 `pkg` 排序以**包内聚**(同目录相关文件落同批),每批文件数
MUST NOT 超过 `--scout-batch-cap`(默认 40)。单个 `bytes > --scout-batch-bytes` 的文件
MUST 经既有 `chunk_sources.py` 切片入批,MUST NOT 整文件塞入单个 LLM 上下文。每批在一个
**独立 scout-reader subagent 上下文**深读,产出 `checkpoints/scout/<batch_id>.json`;全部
批次完成后由**单一 scout-merge subagent** 在**仅结构化记录、无原始码**上做去重、归一、
provisional `source` 标记 → `scout_candidates.json`。编排器 SHALL 以 `max_concurrent`
(默认 8)并行起 subagent、跑完一波起下一波,直至无 pending 批次。批数(= subagent 数)
SHALL 由 `ceil(Σtarget_bytes / batch_bytes)` **涌现而出**,而非固定常量。每批 SHALL 落
`checkpoints/scout/<batch_id>.json.done`;`--resume` MUST 跳过已 done 批次。

**计划自描述与 `--check` 退出码**:`plan_scout.py` 生成时 SHALL 把生成所用
`batch_bytes`/`batch_cap` 记入 `scout_plan.json` 顶层(自描述);`--check` 校验批预算 SHALL
优先使用 plan 记录值(plan 未记录时回退 CLI `--batch-bytes`,兼容存量 plan)。`--check` 对
损坏 plan(JSON 不可解析 / wrapper 形状错)SHALL 退出码 **2**(fail-loud 边界校验统一语义,
闸门 recipe 只认 2),NEVER 退出码 1。理由〔自定义批字数生成的合法 plan 在缺省 `--check`
下按默认值误报违例 → 回退循环;损坏 plan 报 1 会被编排器当作可重试通用错而非闸门违例〕。

编排器取得「待跑批清单」MUST 经确定性叶脚本 `list_scout_batches.py`(见「Deterministic
scout-batch enumeration for fan-out」),MUST NOT 手挖 `scout_plan.json`、MUST NOT `py -c`
内省。`merge_scout.py` 折叠后,`scout_candidates.json` 与改写后的 `controls_candidates.json`
为**终态**,编排器 MUST NOT 对其二次聚合或重切批。

#### Scenario: Batches sized by bytes, co-located by package

- **WHEN** scout 目标含同一 `com/acme/security/` 包下的多个相关文件
- **THEN** `scout_plan.json` 的某批同时包含这些文件,且该批累计 bytes ≤ `--scout-batch-bytes`

#### Scenario: Oversize single file is sliced, not fed whole

- **WHEN** scout 目标含一个 250KB 的 `LegacyGuard.java`,而 `--scout-batch-bytes` 为 96KB
- **THEN** 该文件经 `chunk_sources.py` 切成函数切片入批,而非整文件塞入一个 scout-reader

#### Scenario: 自定义批字数的 plan 在缺省 --check 下零违例

- **WHEN** 以 `--batch-bytes 204800` 生成 plan(顶层记录该值),随后不传 `--batch-bytes`
  运行 `plan_scout.py --check <plan>`
- **THEN** 校验按 plan 记录的 204800 判预算,合法 plan 退出码 0(修复前按缺省 98304 误报违例);
  存量无记录 plan 回退 CLI 值,行为不变

#### Scenario: 损坏 plan 的 --check 退出码 2

- **WHEN** `scout_plan.json` 内容不是合法 JSON(或顶层不是 wrapper dict)
- **THEN** `plan_scout.py --check` 退出码 **2** + stderr 诊断(NEVER 退出码 1)

#### Scenario: Batch count emerges from data, parallel waves bounded

- **WHEN** scout 目标共 ~9.6MB、`--scout-batch-bytes` 96KB、`max_concurrent` 8
- **THEN** `scout_plan.json` 产出约 100 批,编排器以每波 8 并行跑完所有批

#### Scenario: Merge operates on structured records only

- **WHEN** scout-merge 运行
- **THEN** 其输入为各 batch 的结构化候选 JSON(无原始源码),上下文规模远小于任一
  scout-reader;跨批重复报告的同一控制被去重归一

#### Scenario: Resume skips completed batches

- **WHEN** scout fan-out 中途断开,随后 `mgh-init --resume`
- **THEN** 已 done 的批次被跳过,仅继续 pending 批次,`scout_candidates.json` 最终完整

#### Scenario: Pending work-list obtained via leaf script, not hand-mining

- **WHEN** 编排器进入 scout fan-out
- **THEN** 它先调用 `list_scout_batches.py` 取 `pending[]` 再逐批扇出;不出现 `py -c` 挖 `scout_plan.json` 或 `Write _prep_scout_batches.py`

#### Scenario: Merged artifacts are terminal

- **WHEN** `merge_scout.py` 完成,`scout_candidates.json` 落盘
- **THEN** 编排器不再对其二次聚合或重切批(不出现 `_aggregate_scout.py` 之类重实现)

### Requirement: Scout candidate JSON robustness at the merge boundary

LLM subagent 产出的 scout 候选 JSON SHALL 是合法 JSON,每条 candidate SHALL 携带非空 `category`,
`evidence_snippet` SHALL 是单行安全子串(以 `'` 代 `"`、去 `\`)——结构上不可能破坏 JSON 字符串。
产出者:S3 `init-scout`(per-batch `checkpoints/scout/<batch_id>.json`)、S4 `init-scout-merge`
(`scout_candidates.json`)、`init-scout-audit`(`audit.json::audit_found[]`);S4 合并时 MUST NOT 丢弃
`category`。该约束 SHALL 写入 `core/prompts/stages/init-scout.md`、`init-scout-merge.md`、
`init-scout-audit.md` 三份提示词(双 shell 共享 `core/`,一次改双端)。

`merge_scout.py` 折入(`main()`)SHALL **NOT** 在畸形输入上抛未捕获异常(原始 traceback):
- 破损 JSON(`--scout`/`--candidates`/`--clusters` 任一 `json.loads` 失败)→ stderr 出 `lineno/colno/msg`
  诊断、stdout 出结构化错误 JSON(含 `error`/`file`/`lineno`/`colno`/`nearby`)、退出码 `1`;
- **合法 JSON 但形状错**(wrapper 非 dict、`candidates` 非 list、candidate 非 dict、cluster 记录
  非 dict 等)→ 同形结构化错误(含 `error`/`file`/`shape` 诊断)+ 退出码 `1`,NEVER 裸崩
  (audit 路径同判——该路径不经 `--check`,裸崩 = 无闸门);
- 缺 `category` 的 candidate(含 `audit_found[]` 路径,该路径不经 `--check`)→ `_normalize` **跳过**该
  candidate、stderr warn、退出码 `0`,stdout 成功摘要 SHALL 含 `skipped` 计数显式披露丢弃数。

`_normalize` 取 category SHALL 用 `c.get("category")`(非 `c["category"]` 直索引)。本要求**不**改
`discover_controls.form_clusters`(共享逻辑;`_normalize` 跳过即阻断缺 category 候选进入)。

#### Scenario: merge_scout fold-in does not crash on malformed JSON

- **WHEN** `merge_scout.py --candidates … --scout <malformed.json> --clusters …` 被调用,且 `<malformed.json>` 不是合法 JSON
- **THEN** 进程退出码 `1`、**不**抛未捕获 traceback;stdout 为含 `error`/`file`/`lineno`/`colno` 的结构化 JSON,stderr 出可操作诊断

#### Scenario: merge_scout fold-in does not crash on wrong-shape legal JSON

- **WHEN** `--candidates` 指向的文件是合法 JSON 但顶层是 list(非 wrapper dict),或
  `candidates` 键是 dict(非 list),或 audit 路径 `audit_found[]` 含非 dict 元素
- **THEN** 进程退出码 `1`、不抛未捕获 traceback;stdout 结构化错误指认文件与形状问题(audit
  路径同判),NEVER 在 `form_clusters` 深处裸崩

#### Scenario: merge_scout fold-in skips missing-category audit candidates

- **WHEN** `audit.json::audit_found[]` 含一条缺 `category` 的 candidate(该路径不经 `--check`)
- **THEN** `merge_scout.py` 折入跳过该 candidate、stderr warn 指明丢弃、退出码 `0`,stdout 摘要的 `skipped` 计数 ≥1,合法 candidate 仍正常折入

#### Scenario: merge_scout fold-in reports skipped count on success

- **WHEN** 折入完成且有 candidate 因缺 `category` 被跳过
- **THEN** stdout 成功摘要 JSON 含 `skipped` 字段(非 0),`scout_candidates_added` 仅计合法折入数

#### Scenario: Scout prompts require category and a JSON-safe snippet

- **WHEN** 审阅 `core/prompts/stages/init-scout.md` / `init-scout-merge.md` / `init-scout-audit.md`
- **THEN** 每份显式声明:每条 candidate `category` 必带(S4 合并 NEVER 丢弃)、`evidence_snippet` 为单行且以 `'` 代 `"`、去 `\` 的安全子串

#### Scenario: form_clusters untouched by the robustness fix

- **WHEN** 审阅 `discover_controls.py::form_clusters`
- **THEN** 其 `category` 取值方式与变更前一致(未改为 `.get`);缺 `category` 的 scout 候选在 `merge_scout._normalize` 即被跳过,不进入 `form_clusters`

### Requirement: Merge scout fold-in normalizes non-canonical categories deterministically

`merge_scout.py` fold-in SHALL 用**确定性别名映射**把 scout 候选的非规范类名归一为规范 8 类之一
(`input-validation`/`authentication`/`authorization`/`data-masking`/`crypto`/`rate-limiting`/`csrf`/
`audit-logging`)再写入 `controls_candidates.json` 并参与 `form_clusters`。别名表 SHALL 与
`validate_inventory.py` 的规范 8 类共享**单一真相源**(如常量/helper 放在两脚本均可导入的公共位置,
承 R2 零依赖),至少覆盖既有漂移实例:`access-control→authorization`、`auth→authentication`。
归一 SHALL 发生在 fold-in 写入前(T2 之前),使 T2 `init-synthesis` 与 `validate_inventory.py`
只见到规范类名。`merge_scout.py --check` SHALL 对每条 scout candidate 断言其 `category` 归一后 ∈
规范 8 类;未映射的非规范类 SHALL 作为违例 fail-loud 退出码 2(而非静默丢弃或放行),使类名漂移在
**fold-in 边界**被拦截、而非等到 T2 边界(`validate_inventory.py`)或静默丢进综合。**fold-in 主
路径同判**:折入(非 `--check`)遇到未映射非规范类 SHALL 同样退出码 2 fail-loud(audit 路径
同判,NEVER「audit 无闸门」)——skip+warn 仅适用于**缺字段**候选(承「Scout candidate JSON
robustness at the merge boundary」),未映射类名是可拦截的确定性漂移,静默丢弃即吞候选。

**fold-in 双文件写的原子性与凭证写序**:折入对 `controls_candidates.json` 与 `clusters.json`
两文件的重写 SHALL 各自原子(tmp + `os.replace`);写序 SHALL 为 **clusters 先、candidates 后**
(完成凭证 `provenance.scout_merged` 随 candidates 最后落盘)——凭证存在 ⟺ 两文件一致。崩溃
于两写之间 → 凭证缺失 → 重折幂等收敛(已折候选在去重集内被跳过、`fresh` 为空不再追加簇),
NEVER 出现「candidates 已并、clusters 缺 scout 簇」的带病进 T1 窗口(凭证在而簇缺失的旧窗口
形态被写序结构性消灭)。

#### Scenario: Non-canonical scout category is normalized at fold-in

- **WHEN** scout candidate 携带 `category: "access-control"`,fold-in 运行
- **THEN** 写入 `controls_candidates.json` 的该候选 `category` 为 `authorization`,并以其参与
  `form_clusters`;T2 只见规范类名

#### Scenario: merge_scout --check rejects an unmapped non-canonical category

- **WHEN** scout candidate 携带 `category: "runtime-guard"`(不在 8 类、不在别名表),运行
  `merge_scout.py --check`
- **THEN** 退出码 2,violations 报告该 candidate 的 index 与「category 非规范 8 类」issue;
  编排器据此回退重跑 scout-merge,而非带着漂移类名进入 T2

#### Scenario: fold-in 主路径对未映射类别同样 fail-loud

- **WHEN** `audit.json::audit_found[]` 或 `scout_candidates.json` 含 `category: "runtime-guard"`
  的候选,fold-in(非 `--check`)运行
- **THEN** 退出码 2 + 指认候选来源与类别;NEVER skip+warn 静默丢弃(缺 `category`/`file` 字段的
  候选仍走既有 skip+warn + `skipped` 计数语义)

#### Scenario: fold-in 两写之间崩溃后重折幂等收敛

- **WHEN** fold-in 写完 `clusters.json` 后、写 `controls_candidates.json` 前进程被杀,随后重跑
  fold-in
- **THEN** 凭证(provenance)缺失 → 重折执行;已折候选在去重集内被识别为重复(`fresh` 为空),
  clusters 不被重复追加,最终两文件一致且凭证落盘;NEVER 出现凭证在而 scout 簇缺失的带病态

#### Scenario: Canonical categories pass the fold-in check unchanged

- **WHEN** scout candidate 携带规范类名(如 `authorization`),运行 `merge_scout.py --check` 与 fold-in
- **THEN** `--check` 退出码 0;fold-in 不改写该 `category` 原值

#### Scenario: Alias source stays shared between merge_scout and validate_inventory

- **WHEN** 审阅 `merge_scout.py` / `validate_inventory.py` 的类别常量来源
- **THEN** 两脚本引用同一规范 8 类 + 别名表(单一真相源),不允许各自硬编码一份
