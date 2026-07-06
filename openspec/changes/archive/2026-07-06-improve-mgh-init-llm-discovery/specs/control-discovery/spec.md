## MODIFIED Requirements

### Requirement: Discover security control candidates deterministically

`discover_controls.py` SHALL 用 Python ≥3.10 标准库,按文件名/扩展 + 内容模式 + 注解
特征扫描候选控制,覆盖类别:`input-validation`、`data-masking`、`authentication`、
`authorization`、`crypto`、`rate-limiting`、`csrf`、`audit-logging`。扫描 MUST 复用
`expand_scope.py` 的 `SOURCE_EXT` / `EXCLUDE_DIR`(排除 `node_modules`/`target`/
`build`/`vendor` 等)。每条候选 SHALL 记录 `file`、`line`、`category`、匹配模式、片段。

本确定性扫描是发现候选的 **fast-path 来源之一**(双源并集的另一源是 LLM scout 层,
见「LLM scout discovers controls beyond the token allowlist」)。每条 regex 候选 SHALL
带 `source: "regex"`。`_QUICK_RX` 预过滤不命中的文件 MUST NOT 被丢弃出发现流程——
它们 SHALL 仍进入 `skeleton.json`(见「Extract lossless source skeleton」),保持对
scout 层可见。「不命中规范 token」本身 MUST NOT 成为排除一个文件被 LLM 审视的理由。

#### Scenario: Detect Spring authorization annotation
- **WHEN** 扫描到 `@PreAuthorize` / `@PostAuthorize` / `@Secured` / `@RolesAllowed`
- **THEN** 产出一条 `category: authorization`、`source: "regex"` 候选,含文件与行号

#### Scenario: Detect sensitive-data masking utility
- **WHEN** 扫描到含 `mask` / `redact` / `脱敏` / `@JsonSerialize` 脱敏器 / Luhn 校验等方法特征
- **THEN** 产出一条 `category: data-masking`、`source: "regex"` 候选

#### Scenario: Exclude non-source / build directories
- **WHEN** 候选落在 `target/`、`node_modules/`、`build/`、`vendor/` 等 `EXCLUDE_DIR`
- **THEN** 该候选被跳过,不计入 `controls_candidates.json`

#### Scenario: Custom control missing canonical tokens stays discoverable
- **WHEN** 一个自研鉴权类 `PermGuard`(命名不撞任何规范 token)落在非 `EXCLUDE_DIR`
- **THEN** 它不产出 regex 候选,但仍出现在 `skeleton.json` 中、对 scout 层可见(即:
  「不命中 token」不会把它排除出发现流程,只是不由 regex 这一路发现)

## ADDED Requirements

### Requirement: Extract lossless source skeleton for LLM selection

`discover_controls.py` SHALL 在其既有单遍文件遍历中,为**每个**源文件机械抽取一份
**无损骨架**并 emit 到 `skeleton.json`,字段:`file`、`lang`、`pkg`(由相对路径推)、
`classes[]`(复用既有 `CLASS_RX`)、`method_sigs[]`(复用 `JAVA_DEF`/`DEF_CALL`)、
`imports[]`(新增按 `lang` 分派的 `import`/`#include`/`require`/`from…import` 正则)、
`fan_in`(来自既有 reverse graph)、`bytes`。抽取 MUST NOT 判定「该文件是否为安全控制」
——骨架仅是供 LLM 选择「读谁」的廉价元数据,所有语义判断留给 scout 层。抽取 MUST 复用
既有单遍 I/O(每文件至多读一次),MUST NOT 引入对仓库的第二次遍历。

#### Scenario: Skeleton carries mechanical metadata only
- **WHEN** `discover_controls.py` 运行
- **THEN** `skeleton.json` 每条含 `pkg/classes/imports/method_sigs/fan_in/bytes`,且不含
  「是否控制」之类的语义判定字段

#### Scenario: Skeleton covers files the regex skipped
- **WHEN** 某文件不含任何规范 token(被 `_QUICK_RX` 预过滤跳过)
- **THEN** 该文件仍出现在 `skeleton.json` 中(预过滤只跳过 regex 候选生成,不跳过骨架抽取)

#### Scenario: Single-pass extraction without a second walk
- **WHEN** 对任意目标仓运行发现脚本
- **THEN** 仓库源文件遍历次数为 1(骨架抽取搭 regex 扫描与调用图构建的同一次遍历)

### Requirement: LLM scout discovers controls beyond the token allowlist

`/mgh-init` SHALL 在 i1 与 T1 之间插入一个 **LLM scout 发现层**:scout subagent 读取
`skeleton.json` 中的目标行 + repo root,**自适应地**(无固定词表)用自身工具(Glob/Grep/
Read)寻找 regex 漏掉的自研安全控制,对确认者按 Candidate schema 子集产出锚点候选
(`file/line/category/kind/anchor/shape/evidence_snippet/confidence`),每条带
`source: "scout"`。scout 输出 SHALL 经 `scout_candidates.json` 与 regex 候选**并集**
后,走既有 `form_clusters`(簇形成逻辑不变)。每条 scout 候选 MUST ground 在该 subagent
实际 Read 过的真实 `file:line`;无证据的候选 MUST 降 `confidence` 或丢弃。scout 发现
DI/AOP/反射等文本调用图无法解析的控制时,SHALL 并入既有 `unresolved[]` 并标 `source`。

#### Scenario: Custom control found by scout, missed by regex
- **WHEN** 项目含一个零规范 token 的自研鉴权 `PermGuard`,且未传 `--no-scout`
- **THEN** scout 层产出一条 `source: "scout"` 的 authorization 候选,其 evidence 指向真实
  Read 过的 `PermGuard` 锚点;该控制进入候选并集并形成簇

#### Scenario: Scout proposal without evidence is dropped
- **WHEN** scout subagent 试图产出一个未实际 Read 过文件证据的候选
- **THEN** 该候选被丢弃或标 `confidence: low`,不进入高置信候选集

#### Scenario: No-scout flag preserves legacy regex-only behavior
- **WHEN** 运行 `mgh-init --no-scout`
- **THEN** scout 层不执行,候选集仅含 `source: "regex"`(等价于引入 scout 前的行为)

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

#### Scenario: Batches sized by bytes, co-located by package
- **WHEN** scout 目标含同一 `com/acme/security/` 包下的多个相关文件
- **THEN** `scout_plan.json` 的某批同时包含这些文件,且该批累计 bytes ≤ `--scout-batch-bytes`

#### Scenario: Oversize single file is sliced, not fed whole
- **WHEN** scout 目标含一个 250KB 的 `LegacyGuard.java`,而 `--scout-batch-bytes` 为 96KB
- **THEN** 该文件经 `chunk_sources.py` 切成函数切片入批,而非整文件塞入一个 scout-reader

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

### Requirement: Self-audit scout rejections to bound false negatives

scout 批次完成后,系统 SHALL 随机抽取 `--scout-audit-pct`(默认 15%)个被 scout 判定
「无控制」的目标,交一个**怀疑论偏置**的 `init-scout-audit` subagent 复核(对标 s6
「assume WRONG until confirmed」):尝试证明该目标**实为**被漏报的控制。若审计发现漏报,
SHALL 将该目标回灌(重跑其所属批次或直接补候选),并在 `init_manifest.json` 记录
`audit_found`。抽样 MUST 确定性(脚本选样,可复现)。审计 MUST NOT 对全部拒绝项 100%
复核(成本不可接受)。

#### Scenario: Audit catches a scout false negative
- **WHEN** scout 漏判一个自研脱敏工具为「无控制」,且它落入 audit 抽样
- **THEN** audit subagent 复核发现它实为 data-masking 控制,该候选被补回候选集,manifest
  的 `audit_found` 计数 +1

#### Scenario: Audit sample is deterministic and bounded
- **WHEN** 对同一 skeleton 两次运行(同 seed)
- **THEN** audit 抽到的目标集相同;且抽样数 = `ceil(rejected × audit_pct)`,非全量复核

### Requirement: Disclose scout coverage and residual blind spot

`init_manifest.json` SHALL 增 `scout` 段,记录:`skeleton_total`、`scout_targets`、
`batches`、`deep_read_files`、`audit_sampled`、`audit_found`、`truncated`(目标超预算时为真
并建议 `--scope`+`--merge`)。`report.md` 与 `init_manifest.json` 的 `boundaries[]` SHALL
新增披露:(1) scout 实际审视了 `skeleton_total` 中的多少、深度 Read 了多少、自检了多少
(**不声称全仓覆盖**);(2) scout 非确定,簇数 run-to-run 可能变化(regex 来源簇仍确定);
(3) 残留盲区——泛型包 + 泛型类名 + 泛型签名 + 无安全导入 + 低扇因的控制,规则与骨架均
无法识别,可能漏报。既有三条诚实边界(存在≠有效 / 调用图盲点 / 需人工复核)保持不变。

#### Scenario: Manifest reports real scout coverage numbers
- **WHEN** 一次含 scout 的运行完成
- **THEN** `init_manifest.json` 的 `scout` 段含可识别的真实计数字段,且不出现「全仓覆盖」
  之类断言

#### Scenario: Residual blind spot is disclosed
- **WHEN** 审阅 `report.md` / `init_manifest.json` 的 `boundaries[]`
- **THEN** 其中明示「泛型命名 + 低扇因控制可能漏报」这一残留盲区,以及 scout 的非确定性
