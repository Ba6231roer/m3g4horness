# control-discovery Specification

## Purpose
TBD - created by archiving change add-mgh-init. Update Purpose after archive.
## Requirements
### Requirement: Parse arguments and guard zero-token no-op

`/mgh-init` SHALL accept `--target <dir>`(默认 `.`)、`--format opencode|claude`
(**必选**)、`--out <path>`、`--scope <dir|package>`、`--language <lang>`、
`--config <profile>`。当无 actionable 参数或传 `--help` 时,系统 MUST 仅打印参数表
与指向 `task.260630.md` 的说明后**停止,不消耗 token、不做任何分析**。

#### Scenario: Missing required --format
- **WHEN** 用户运行 `mgh-init --target ./svc` 未提供 `--format`
- **THEN** 系统打印「`--format` 必选」错误 + 参数表并停止,不扫描代码

#### Scenario: Help / no actionable args
- **WHEN** 用户运行 `mgh-init --help` 或不带任何参数
- **THEN** 系统打印参数表后停止,零 LLM 调用、零代码扫描

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
- **WHEN** 候选落在 `target/`、`node_modules/`、`build`/`vendor/` 等 `EXCLUDE_DIR`
- **THEN** 该候选被跳过,不计入 `controls_candidates.json`

#### Scenario: Custom control missing canonical tokens stays discoverable
- **WHEN** 一个自研鉴权类 `PermGuard`(命名不撞任何规范 token)落在非 `EXCLUDE_DIR`
- **THEN** 它不产出 regex 候选,但仍出现在 `skeleton.json` 中、对 scout 层可见(即:
  「不命中 token」不会把它排除出发现流程,只是不由 regex 这一路发现)

### Requirement: Zero runtime dependencies

`discover_controls.py` 及所有新增脚本 MUST 仅用 Python 标准库(`argparse/ast/collections/
datetime/json/math/pathlib/re/subprocess/sys` 同类)。MUST NOT `import` 任何 `vvaharness`
模块;MUST NOT 要求 Semgrep / CodeQL / tree-sitter 或任何 `pip install`。

#### Scenario: AST scan finds no third-party imports
- **WHEN** 对新增 `.py` 做 AST 扫描
- **THEN** 不存在非标准库 import,且无 `import vvaharness` / `from vvaharness import`

#### Scenario: Runs fully offline
- **WHEN** 在无网络内网环境对样例仓运行
- **THEN** i1 确定性发现阶段正常产出 `controls_candidates.json`

### Requirement: Reuse call-graph engine for control wiring

`discover_controls.py` SHALL 导入并复用 `expand_scope.build_call_graph`(D2:导入不改写),
为每个候选控制计算:`reverse`(谁调用了该控制)、`framework_files`(Spring Security 配置
等框架标记文件)、`name_to_files`(注解/方法名 → 定义文件)。经调用图关联到的入口写入
候选 `entry_points`;无法文本解析的框架路由控制(AOP pointcut / 反射 / DI)写入
`unresolved[]`。

#### Scenario: Control entry_points populated from reverse graph
- **WHEN** 一个 sanitizer 工具方法被多个 controller 调用
- **THEN** 该候选的 `entry_points` 包含这些调用方文件

#### Scenario: AOP-advised control reported unresolved
- **WHEN** 某鉴权逻辑仅通过 AOP pointcut 织入,无文本调用边
- **THEN** 该控制出现在 `unresolved[]` 而非 `entry_points`,并在 report 披露

### Requirement: Emit design_controls-compatible inventory

`controls_inventory.json` SHALL 为每条归纳后的控制携带:`name`(slug)、`kind`(vvah
6 枚举之一:`auth`/`sandbox`/`input-validation`/`aslr`/`cfi`/`other`)、`category`(细分类)、
`description`、`usage`、
`evidence`(至少一个 `file:class:method` 锚点)、`entry_points`、`protects`(fnmatch
globs,vvah 兼容)、`gaps`、`confidence`。`category → kind` 归一 MUST 确定且可测
(如 `authorization`/`authentication`→`auth`,`data-masking`/`crypto`/`csrf`/`audit`/
`rate-limiting`→`other`,`input-validation`→`input-validation`)。

#### Scenario: kind normalized from aliases
- **WHEN** 归纳出 `authorization` 类控制
- **THEN** 其 `kind` 为 `auth`,与 vvah `design_controls` 别名归一一致

#### Scenario: Every control cites concrete evidence
- **WHEN** inventory 写入一条控制
- **THEN** `evidence` 至少含一个 `file:class:method`(或 `file:line`)锚点,可被索引

### Requirement: LLM induction grounded in evidence

`init-induct` subagent SHALL 仅基于 i1 候选 + 相关文件摘录归纳控制语义(这是什么、怎么用、
入口、缺口)。MUST NOT 凭空生成无证据支撑的控制;低证据候选 MUST 降 `confidence` 或丢弃。
归纳提示词 SHALL 带溯源注释(若移植 vvah 片段标注 `Source:`;纯自创标注
`rewrite-original`)。

#### Scenario: Hallucinated control without evidence is dropped
- **WHEN** LLM 试图归纳一条 i1 候选中无任何文件证据的控制
- **THEN** 该控制被丢弃或标 `confidence: low`,不进入高置信 inventory

### Requirement: Isolated per-cluster induction with cross-cluster synthesis

归纳 SHALL 按 **T1/T2 两层**执行(D12):T1 为**每个控制簇**扇出一个**独立 subagent 上下文**,
仅读该簇文件集(大文件先分片)+ 候选元数据,产出结构化控制记录且**不得做 canonical 判定**
(隔离单元看不到别簇);T2 为单一综合上下文,仅读全部 T1 的**结构化记录**(无原始码),
完成跨模块聚类、canonical/role 选定(D8)、去重与命名归一。出 rules SHALL 按 **T3/T4 两层**:
T3 每 category 一个独立上下文出草稿,T4 可选一致性 pass。**隔离单元边界 = checkpoint 单元
边界**(同一边界同时服务质量与可恢复)。

#### Scenario: Each cluster induced in its own isolated context
- **WHEN** 一个项目有 3 个独立控制簇(鉴权 filter、脱敏工具、加密工具)
- **THEN** 产出 ≥3 个独立 T1 subagent 上下文,各自只读本簇文件,互不串扰

#### Scenario: Canonical decided in synthesis, not in isolated units
- **WHEN** 两个模块各自被独立 T1 归纳出鉴权控制
- **THEN** canonical/competing 判定发生在 T2 综合(可见两者);T1 记录中不含 canonical 判定

#### Scenario: Synthesis operates on structured records only
- **WHEN** T2 综合运行
- **THEN** 其输入为 T1 结构化 JSON 记录(无原始源码),上下文规模远小于任一 T1

### Requirement: Disclose honesty boundaries in artifacts

`report.md` 与 `init_manifest.json` MUST 明示三条边界:(1) 控制为「**存在**」非「**有效**」
(引用 CVE-2025-41248:参数化类型上 `@PreAuthorize` 可绕过);(2) 调用图为文本/AST 级,
漏 AOP/反射/DI/框架路由,未解析项见 `unresolved[]`;(3) 归纳结果为 LLM 候选,**需人工复核**。

#### Scenario: Manifest carries all three disclaimers
- **WHEN** 一次运行完成
- **THEN** `init_manifest.json` 含上述三条边界声明的可识别字段

### Requirement: Shard large files for stable LLM analysis

单文件超过 `--big-file-bytes`(默认 200KB)时,系统 SHALL 先用 `chunk_sources.py`
做**确定性 AST 骨架**(imports/顶层 class/method 签名/注解,零 LLM),再只把「控制候选
函数体 ± 上下文窗口」作为切片喂给 induct,**不得整文件塞入 LLM 上下文**。非 AST 语言
SHALL 回退到带重叠的行窗口。对大文件 shard 的归纳结果,系统 MAY 再跑一道 verify
pass 交叉核验,不一致时降 `confidence`。

#### Scenario: Big file is sharded, not fed whole
- **WHEN** 一个 250KB 的 `LegacyAuthFilter.java` 含控制候选
- **THEN** induct 收到的是候选函数切片(含上下文窗口),而非整文件;切片来自 AST 骨架定位

#### Scenario: Shard disagreement lowers confidence
- **WHEN** 大文件某 shard 的归纳与 verify pass 核验不一致
- **THEN** 该控制 `confidence` 被下调,并在 report 标注

### Requirement: Cluster competing controls and designate canonical

当同 `category`(如 authorization、data-masking)存在 2+ 候选时,i2 归纳 SHALL 将其
聚类,按 canonicality 加权(框架背书 / 调用图入度 / `security`·`common`·`config` 包位置 /
注解化)选定主实现。每条控制 inventory 项 SHALL 带 `cluster_id` 与
`role∈{canonical,competing,duplicate,possibly-dead}`。非 canonical 控制 **MUST 保留**
(只标 role、不删)。report SHALL 含「竞争控制」专节。

#### Scenario: Two auth implementations clustered with canonical picked
- **WHEN** 项目同时存在 Spring `SecurityConfig` 过滤器链与一套散落的 `if(user.isAdmin())`
- **THEN** 两者归入同一 `cluster_id`,前者 `role: canonical`(框架背书 + 高入度),后者
  `role: competing`,两者均保留进 inventory

#### Scenario: Canonical selection surfaces bypass candidates
- **WHEN** 存在标为 canonical 的鉴权控制
- **THEN** report「竞争控制」专节列出非 canonical / possibly-dead 实现,供 `/mgh-blst`
  据此找未走 canonical 的接口

### Requirement: Resumable, checkpointed execution

系统 SHALL 按工作单元 checkpoint:`i1` 按文件(大文件按 shard)、`i2` 按 cluster、
`i3` 按 category,每单元落 `<target>/.mgh-init/checkpoints/<unit>.json` + done 标记。
`--resume` SHALL 跳过已完成单元并合并 parts。调用图 SHALL 缓存到
`<target>/.mgh-init/cache/callgraph.json`(全仓建一次;`--rebuild-cache` 或源文件 mtime
变化时失效重建)。

#### Scenario: Resume skips completed units
- **WHEN** 一次运行中途断开,随后 `mgh-init --resume`
- **THEN** 已 done 的文件/cluster/category 单元被跳过,仅继续未完成单元,产物最终完整

#### Scenario: Call graph cached across runs
- **WHEN** 源文件未变更,第二次运行
- **THEN** 复用 `cache/callgraph.json`,不重建全图

### Requirement: Scoped and partial-merge analysis

`--scope path:<dir>|package:<pkg>|file:<glob>` SHALL 限定分析种子。`--scope-mode`
SHALL 区分:`defined`(默认,控制定义点在 scope 内)与 `applicable`(控制调用方/入口
触及 scope)。跨模块但定义点在 scope 外的控制 SHALL 记入 `out_of_scope[]`(披露不丢)。
`mgh-init --merge <partials-dir>` SHALL 按 `evidence`(`file:class:method`)去重合并
多次局部产物,并跨模块重算 cluster role。

#### Scenario: Scoped run bounds to a module
- **WHEN** `mgh-init --scope path:src/payment --scope-mode defined`
- **THEN** 仅分析定义点在 `src/payment` 内的控制;跨模块控制入 `out_of_scope[]`

#### Scenario: Partial runs merge by evidence anchor
- **WHEN** 对模块 A、B 各跑一次局部 init,再 `mgh-init --merge partials/`
- **THEN** 合并后 inventory 按 `file:class:method` 去重,同一控制不重复,cluster role 跨模块重算

### Requirement: Standalone script invocation robustness

`discover_controls.py` 与 `chunk_sources.py` SHALL 在 `from expand_scope import …` 之前,把
**本脚本所在目录**显式插入 `sys.path`(`sys.path.insert(0, str(Path(__file__).resolve().parent))`),
使其在**任意工作目录**、经**宿主 agent 的任意调用方式**(直接 `py`/`python` 执行)下都能定位同目录
的 `expand_scope.py`。两脚本 MUST NOT 仅依赖「运行时自动把脚本目录加入 `sys.path[0]`」这一隐式行为
来保障兄弟导入,MUST NOT 要求用户以 `python -c "exec(…)"` 方式绕行(该方式在 Windows 中文 locale
下会触发 gbk 解码错误)。

#### Scenario: Runs from a different working directory
- **WHEN** 宿主 agent 从目标仓根目录(非脚本所在目录)执行 `py <path>/discover_controls.py --repo . --out ./.mgh-init`
- **THEN** 脚本成功 import `expand_scope`,不报 `No module named 'expand_scope'`,正常产出 candidates/clusters

#### Scenario: Direct execution needs no python -c workaround
- **WHEN** 用户按文档以 `py`/`python` 直接执行 `chunk_sources.py` / `discover_controls.py`
- **THEN** 无需借助 `python -c "exec(open(...).read())"` 即可运行,从而不触发 Windows gbk 编码错误

### Requirement: Bounded single-pass scan performance on large repos

`discover_controls.py` SHALL 对每个源文件**至多读一次磁盘**(读入后缓存文本,供调用图两遍与候选
扫描共用);`walk_sources(repo)` 在单次运行中**只遍历一次**仓库并物化文件清单,供调用图构建与候选
扫描复用;每文件**仅调用一次 `splitlines()`**;候选的 enclosing 锚点 SHALL 通过**每文件预排序的
结构节点列表 + 按行二分**求解,而非「每候选对全文反复 `finditer`」。系统 SHALL 在扫描期间向
**stderr** 周期输出进度(每 N 个文件),stdout 仅在末尾输出既有 JSON 摘要(契约不变)。在 i0 阶段
SHALL 以低成本统计源文件数,命中大仓阈值时**在开始全量扫描前**主动建议 `--scope` 分模块 + `--merge`。

#### Scenario: Large repo finishes within the host timeout
- **WHEN** 对一个约两万个源文件的目标仓运行 `/mgh-init`(默认 `--max-files`)
- **THEN** `discover_controls.py` 在 5 分钟内完成,不被宿主 300s 超时强杀

#### Scenario: Each source file read at most once
- **WHEN** 对任意目标仓运行发现脚本
- **THEN** 每个源文件的磁盘读取次数为 1(调用图两遍与候选扫描共用同一缓存文本)

#### Scenario: Progress emitted to stderr only
- **WHEN** 扫描持续进行且尚未完成
- **THEN** stderr 周期性打印已扫描文件数;stdout 不在中途打印非 JSON 内容,末尾 JSON 摘要契约不变

#### Scenario: Large repo advised to scope before scanning
- **WHEN** i0 阶段统计的源文件数超过阈值
- **THEN** 系统在开始全量扫描前提示建议 `--scope` 分模块 + `--merge`,而非静默跑到超时

### Requirement: Deterministic scripts are orchestrator black boxes

`/mgh-init` 的编排器是宿主 agent 本身(按 `mgh-init.md` 用自身工具跑流水线,非写代码)。命令壳 SHALL 在正文最前列声明,且把编排纪律明线**扩展到一次性微脚本**(承
`harden-mgh-init-orchestration-discipline` FD1:真机失败形状是微脚本内省,非大编排器)。agent
**MUST NOT**(硬边界,`NEVER`):

- (a) `Write` 任何 `.py`——含大编排器(`mgh_init.py`)与**一次性微脚本**(`py -c` 产物、`_prep_scout_batches.py`、
  `_aggregate_scout.py`、`<run>_helper.py` 等);
- (b) 经 `Bash` 运行 `py -c` / `python -c` 去**内省或重派生**产物(`import json` / `open(` / `load(` 读
  `.mgh-init/**` 之类);
- (c) `Read` 叶子脚本 `.py` 源码进编排上下文(报错看 stderr)。

`Write`/`Edit` 仅用于产物。调用示例 SHALL 只传脚本声明的 flag——`--format` 由 T3 `init-rulewriter`
消费,`discover_controls.py` 不接受 `--format`。当 agent 需要「工作清单 / 瞄一眼结构 / 派生量」时,
SHALL 走 implementation-intention 句式声明的合法出口:工作清单 → `list_clusters.py` /
`list_scout_batches.py` / `list_rule_jobs.py`;瞄结构 → `describe_artifact.py`;派生量 → 该量产出者
的 stdout 字段(见「Derived counts exposed as script output」)。命令壳 SHALL 在编排流以刚性三元组
`[输入产物::字段] → script/subagent → [输出产物::字段]` 表述每个 fan-out 步骤,并在 doubt 时刻内联
1 行 shape。

#### Scenario: No orchestrator or helper script is created
- **WHEN** 宿主 agent 执行 `/mgh-init`,需要取得 scout 待跑批清单
- **THEN** agent 调用 `list_scout_batches.py`,**不** `Write` `_prep_scout_batches.py` 之类一次性 `.py`,
  也**不** `py -c "import json…"` 挖 `scout_plan.json`

#### Scenario: Discover script not passed --format
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md` 中 `discover_controls.py` 的调用示例
- **THEN** 这些示例不含 `--format`;`--format` 仅出现在 T3 `init-rulewriter` 阶段的描述中

#### Scenario: Scripts invoked, not read, by the orchestrator
- **WHEN** 编排器执行 i1 发现阶段
- **THEN** `discover_controls.py` / `chunk_sources.py` / `expand_scope.py` 经 Bash 执行,其源码不被 `Read` 进编排上下文

#### Scenario: Discover accepts its documented flags
- **WHEN** 以 `discover_controls.py --repo . --out ./.mgh-init`(不带 `--format`)执行
- **THEN** argparse 不报「unrecognized argument」,脚本正常进入扫描

#### Scenario: Structure-understanding reflex routes to sanctioned primitive
- **WHEN** 编排器想确认 `controls_candidates.json` / `scout_plan.json` 的结构再动手
- **THEN** 它调用 `describe_artifact.py --keys/--sample/--shape`,**不** `py -c` 读 `[0]` 或 list keys

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
- **WHEN** 检查 `core/contracts/`
- **THEN** 存在 `init/clusters.md`,逐字段描述包装结构与 Cluster 记录,与 `candidates.md`/`inventory.md` 并列

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

### Requirement: Inventory human-readable fields exclude tool-internal content

`controls_inventory.json` 的面向人读字段 SHALL 只描述目标项目的安全控制本身,且 MUST NOT
携带任何本工具内部信息。受约束的人读字段为 `description`、`usage`、`gaps`、`notes`、
`competing_clusters[].note`。被禁止的工具内部信息包括:本工具名、发现/归纳脚本名
(`discover_controls.py`、`chunk_sources.py`、`plan_scout.py`、`merge_scout.py`、
`list_clusters.py`、`assemble_rules.py` 等)、作为过程描述的流水线层级标签
(`T1`、`T2`、`T3`、`scout`)、内部路径(`.mgh-init/`、`checkpoints/`、`rules-parts/`),以及
任何「如何被本工具发现或归纳」的过程描述。结构/标识字段(`name`、`kind`、`category`、`role`、
`cluster_id`、`evidence`、`protects`、`entry_points`、`confidence`)与目标项目的 evidence 锚点、
文件路径 SHALL 保持原样。该约束 SHALL 同时写入 T1 `init-induct`、S3 `init-scout`、
T2 `init-synthesis` 的提示词,作为 shipped rules 纯净性的源头防线。结构字段 `source`
(取值 `regex` 或 `scout`)SHALL 保留为结构标识,供 manifest 与审计使用,不视为人读正文泄漏。

#### Scenario: usage field describes target-project invocation only

- **WHEN** T1 归纳出 Spring 方法级安全控制,写入其 `usage` 字段
- **THEN** `usage` 以「开发者如何调用/注解」陈述目标项目用法,不含 `discover_controls.py` 或「经 regex 发现」等过程描述

#### Scenario: gaps field states effectiveness caveats only

- **WHEN** T1 发现参数化类型上 `@PreAuthorize` 的绕过形态,写入 `gaps`
- **THEN** `gaps` 描述该控制的有效性缺口(目标项目语义),不含 `chunk_sources.py`、`.mgh-init/checkpoints/` 等工具内部引用

#### Scenario: source field retained as structural tag

- **WHEN** 一条控制由 scout 子阶段发现
- **THEN** 其结构字段 `source: "scout"` 保留(供 manifest/审计);该值不是人读正文,不构成泄漏

#### Scenario: T2 strips residual tool-internal references

- **WHEN** 某 T1 记录的人读字段不慎带入工具内部引用,T2 `init-synthesis` 综合该记录
- **THEN** T2 在写入 `controls_inventory.json` 前剥离这些引用,使最终 inventory 人读字段干净

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

### Requirement: Deterministic scout-batch enumeration for fan-out

`/mgh-init` 的编排器 MUST 经确定性叶脚本 `core/scripts/list_scout_batches.py` 取得 scout 工作清单
(对标 T1 的 `list_clusters.py`,闭合 FD3 的扇出不对称)。`list_scout_batches.py` SHALL 读
`<target>/.mgh-init/scout_plan.json::batches[]` 并扫 `<target>/.mgh-init/checkpoints/scout/*.json.done`,
stdout 输出结构化 JSON `{repo,total,done,pending[],truncated}`,`pending[]` 每项含
`{batch_id,targets_count,bytes,needs_slice[]}`;stderr 仅诊断/进度;退出码 `0/1/2`;`--help` 即其 CLI
契约(承 R5.1)。`total = len(batches[])`,`done = #已 .done`,`pending = total − done`。脚本 MUST
自定位 `sys.path`、utf-8 读入、零第三方依赖、任意 cwd 可 `py`(承 R5.3a)。

#### Scenario: Orchestrator enumerates scout batches via the leaf script
- **WHEN** 编排器进入 scout fan-out(步骤 3b)
- **THEN** 它调用 `list_scout_batches.py` 取 `pending[]`,据此逐批扇出 `init-scout`;不出现手搓 JSON 内省

#### Scenario: list_scout_batches reports total vs done for resume
- **WHEN** 部分批已 done(`checkpoints/scout/<batch_id>.json.done` 存在)后再次运行
- **THEN** stdout 的 `done` 反映已完成批数,`pending[]` 仅含未完成批,`total = done + len(pending)`

#### Scenario: list_scout_batches is self-contained and offline
- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_scout_batches.py --scout-plan <dir>/scout_plan.json --checkpoints <dir>/checkpoints/scout` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8 读入、零第三方依赖),stdout 为合法 JSON

#### Scenario: Empty or truncated scout plan handled without silent truncation
- **WHEN** `scout_plan.json::batches[]` 为空,或 `truncated: true`
- **THEN** `list_scout_batches.py` 输出 `total:0`(空)或保留 `truncated: true`(显式告警),退出码仍 `0`,不静默丢信息

### Requirement: Sanctioned artifact-inspection primitive (no ad-hoc introspection)

`/mgh-init` SHALL 提供确定性叶脚本 `core/scripts/describe_artifact.py`,作为编排器/subagent
「瞄一眼产物结构」反射的**唯一合法出口**(专治「先理解结构再动手」的 `py -c` 反射,FD5)。其 SHALL
支持 `--in <json>` + 至少下列模式之一:`--keys`(顶层键)、`--count`(数组长度,对 wrapper dict 额外
warn 顶层键数 vs 目标数组长度,防 `len(wrapper)=3` 误判)、`--sample N`(数组首 N 项)、`--shape`(轻量
schema:键 + 类型 + 数组元素 shape)、`--field a.b.c`(取嵌套字段)。stdout = JSON 摘要;stderr = 诊断;
退出码 `0/1/2`;零依赖、自定位、utf-8、任意 cwd。编排器与 subagent MUST NOT 用 `py -c`/`python -c`
或 `Read` 整份大 JSON 去内省产物结构,SHALL 改用本脚本。

#### Scenario: Count mode warns on wrapper-dict miscount
- **WHEN** 对 `clusters.json`(wrapper `{repo,clusters,truncated}`)运行 `describe_artifact.py --count`
- **THEN** stdout 报 `clusters[]` 真实长度,并对顶层 3 键给出 warn(防把 3 当簇数)

#### Scenario: Sample mode replaces reading the first element by hand
- **WHEN** 编排器想理解 `scout_plan.json::batches[]` 元素结构
- **THEN** 它运行 `describe_artifact.py --sample 1`,而非 `py -c "import json; print(json.load(open(...))['batches'][0])"`

#### Scenario: describe_artifact is self-contained and offline
- **WHEN** 从任意 cwd 以 `py <path>/describe_artifact.py --in <dir>/controls_candidates.json --keys` 执行
- **THEN** 脚本成功,stdout 为合法 JSON 摘要

### Requirement: Derived counts exposed as script output fields

下游(编排器/subagent)可能需要 list keys / len / sample 才能得到的**派生量**,MUST 由该量的**产出者**
作为 stdout 字段 emit,而非留给下游现算(消除「自己写脚本算」的动机,FD6)。具体:`plan_scout.py`
stdout 与 `scout_plan.json` 顶层 SHALL 含 `regex_known_count`(= 已被 regex 命中、排除出 scout 的文件数,
内部 `regex_files` 已算);`discover_controls.py` stdout 摘要 SHALL 含 `big_files`、`unresolved_count`
等下游常查量(不删既有字段)。派生量字段 SHALL 在对应 `core/contracts/init/*.md` 落定。

#### Scenario: regex_known count available without re-derivation
- **WHEN** 编排器需要「多少文件已被 regex 命中、不需 scout」
- **THEN** 它读 `plan_scout.py` stdout 的 `regex_known_count`,而非 `py -c` 集合运算 `controls_candidates.json`

#### Scenario: discover summary carries downstream-queried counts
- **WHEN** `discover_controls.py` 完成
- **THEN** 其 stdout 摘要含 `big_files` 与 `unresolved_count` 等字段,供编排器直接消费

### Requirement: Runtime enforcement hook for orchestrator script discipline

`install.sh` SHALL 在镜像 `core/` 后,**双端对等**注入运行时纪律守卫 `block_adhoc_scripts`(单一
Python 标准库脚本、零运行时依赖,承 R2),使 Claude Code 与 opencode 用户获得对等的运行时强制:

- **claude**:`install_hook.py` 向目标 `.claude/settings.json` 的 `PreToolUse` **幂等追加**一条命令
  hook(matcher `Bash|Write|Edit` → `py .claude/hooks/block_adhoc_scripts.py`)。
- **opencode**:`install_opencode_plugin.py` 向目标 `.opencode/plugins/` **幂等落**一个订阅
  `tool.execute.before` 的 `.ts` 插件(`block_adhoc_scripts.ts`)。opencode 的 hook 形态即 JS/TS
  插件(非 Claude 的 settings.json 命令式 hook),等价事件为 `tool.execute.before`(pre-tool,可阻断)/
  `tool.execute.after`(post-tool)。该插件是 opencode 原生胶水(非 Python `pip` 依赖),把 opencode
  工具事件**归一化**为 Claude PreToolUse 的 stdin 形态(`{tool_name, tool_input}`),管道喂给**同一**
  `block_adhoc_scripts.py`,据其退出码 2 阻断该工具调用、否则放行。

守卫在 `/mgh-init` 运行域(由编排器起步 `export MGH_INIT_ACTIVE=1` 标记)内:拦截 `Bash` 中
`py -c`/`python -c` 且含 `import json`/`open(`/`load(`/`\.json` 的内省模式,以及 `Write` 中 `*.py`
且不在白名单(`core/scripts`/`tests`/`tools`/`releases/*/hooks`)的写入,以及(init/sra 域)resolved
目标落在 `MGH_TARGET` 子树外的 `Write`/`Edit`。命中 SHALL fail-loud(退出码 2)+ stderr recipe,指向
合法出口(`list_*`/`describe_artifact.py`/脚本 stdout 字段)。非运行域会话 SHALL 直接放行(零日常
噪声)。`install.sh` SHALL 提供 `--no-enforce-hook` opt-out;仅当某端的 hook 注入或核验失败时(claude:
settings.json 写入失败;opencode:`tool.execute.before` 在目标 opencode 版本不可用/不触发)SHALL
stderr warn 并跳过**该端**注入(fail-soft,承 R5.8),此时纪律由命令壳明线 + R5.9 边界校验兜底。本条
兑现 R5.7「能 hook 就别靠自觉」——双端均有等价 hook 路径,opencode 不再被当作「无 hook 能力」而跳过。

#### Scenario: Hook blocks introspection py -c during a run (claude)
- **WHEN** `MGH_INIT_ACTIVE=1` 下编排器运行 `py -c "import json; json.load(open('.mgh-init/scout_plan.json'))"`
- **THEN** hook 以退出码 2 拦截,stderr 给出「用 list_scout_batches.py / describe_artifact.py」recipe

#### Scenario: Hook passes legitimate leaf-script invocation (claude)
- **WHEN** `MGH_INIT_ACTIVE=1` 下运行 `py .claude/mgh-core/scripts/discover_controls.py --repo . --out .mgh-init`
- **THEN** hook 放行,不误伤合法叶子调用

#### Scenario: Hook is idempotent across reinstalls (claude)
- **WHEN** 对同一目标项目连续两次 `install.sh --claude`
- **THEN** `PreToolUse` 中本工具的 matcher 只出现一次,不覆盖用户既有 hook

#### Scenario: opencode plugin blocks the same introspection via the shared gate
- **WHEN** `MGH_INIT_ACTIVE=1` 下 opencode 触发 `tool.execute.before`,且该 Bash 为 `py -c "import json; json.load(open('.mgh-init/scout_plan.json'))"`
- **THEN** `.ts` 插件把事件归一化为 `{tool_name:"Bash", tool_input:{command:...}}` 管道喂给 `block_adhoc_scripts.py`,据退出码 2 阻断该调用,stderr 出同一 recipe;守卫判定逻辑与 claude 端零差异(单一来源)

#### Scenario: opencode plugin is idempotent across reinstalls
- **WHEN** 对同一目标项目连续两次 `install.sh --opencode`
- **THEN** `.opencode/plugins/` 中本工具插件只落一份(幂等替换同名文件、不覆盖用户既有其它插件)

#### Scenario: Opt-out and per-platform fail-soft
- **WHEN** `install.sh --no-enforce-hook`,或某端 hook 注入/核验失败(含 opencode `tool.execute.before` 在目标版本不可用)
- **THEN** 该端 hook 不注入(warn 跳过),install 仍成功(fail-soft);命令壳明线 + R5.9 校验仍生效

### Requirement: Stage-boundary contract checks

每个 stage 产物的产出者 SHALL 暴露 `--check`(或独立 validator),编排器跑完一步、进下一步前 MUST
运行之;失败 MUST fail-loud(退出码 2)并回退重跑(泛化既有 `assemble_rules.py --check` 范式,承
openspec validate-at-boundary,FD7)。覆盖:`discover_controls.py --check`(candidates/clusters wrapper
+ 每条 `source` + cluster_id 唯一)、`plan_scout.py --check`(batches 非空除非 0 target、每批 bytes≤
budget、needs_slice 仅含超批文件)、`merge_scout.py --check`(每条 `source:"scout"` + `file:line` +
**每条 `category` 非空** + **破损 JSON(无法 parse)亦属边界失败、退出码 2** + 给 `JSONDecodeError` 的
`lineno/colno/msg` 与错位附近字节窗诊断)、`validate_inventory.py`(vvah design_controls 兼容 + evidence
锚点 + category→kind 归一)、既有 `assemble_rules.py --check`(rules 纯净性)。

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

### Requirement: Subagent sanctioned-tools allowlist

每个 `core/prompts/stages/init-*.md`(及双壳 `agents/init-*.md`)SHALL 声明一个 **Sanctioned tools**
白名单:读侧 `Read`(仅 input 给定文件/slice)/ `Glob` / `Grep` 自由;脚本侧**仅** `chunk_sources.py`
(若需切片);`Write`/`Edit` 仅限该 stage 的产物文件。subagent MUST NOT `Write` 任何 `.py`、MUST NOT
`py -c`/`python -c` 内省或重派生。stage 输入产物 SHALL 视为**终态**:MUST NOT 用代码变换或重派生;
需瞄结构时 SHALL 向编排器请求 `describe_artifact.py` 输出。`init-scout.md` 现有「Use your tools
freely」SHALL 改为「Use Read/Glob/Grep freely; scripts sanctioned-list only」(治 subagent 侧写脚本,
FD8)。

#### Scenario: scout-reader does not write helper scripts
- **WHEN** `init-scout` subagent 处理一个 batch
- **THEN** 它仅用 Read/Glob/Grep + `chunk_sources.py`(若 needs_slice),不 `Write .py`、不 `py -c`

#### Scenario: Stage prompt declares the allowlist
- **WHEN** 审阅 `core/prompts/stages/init-scout.md` / `init-induct.md` / `init-synthesis.md` / `init-rulewriter.md` 等
- **THEN** 每份含一个可识别的 Sanctioned-tools 段,显式列出允许的工具/脚本并 NEVER 越界

#### Scenario: Shell agent mirrors the allowlist
- **WHEN** 审阅 claude-code 与 opencode 两份 `agents/init-*.md` 的 Hard constraints 段
- **THEN** 两壳均显式声明 subagent NEVER `Write .py` / `py -c`(双壳与 prompt 双重防线)

### Requirement: Fan-out checkpoint paths are deterministic absolute values

scout 与 T1 fan-out 的每个待跑单元的**输出路径** SHALL 是由确定性枚举脚本产出的**单一权威绝对路径值**,
而非占位符模板或相对路径。`list_scout_batches.py` 与 `list_clusters.py` 的 stdout `pending[]` 每项
SHALL 额外包含 `checkpoint_path`(待写产物文件的**绝对路径**)与 `done_marker`(对应 `.done` 标记的
**绝对路径**),二者均由该脚本从其 `--checkpoints` 参数(已 `resolve()`)拼单元 id 得出。编排器 SHALL
把 `list_*` stdout 中的 `checkpoint_path` / `done_marker` **逐字透传**进对应 subagent 的 task 输入,
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
  `<绝对 checkpoints dir>/<batch_id>.json` 与 `<绝对 checkpoints dir>/<batch_id>.json.done`

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

#### Scenario: Existing on-disk artifact schema unchanged
- **WHEN** 本变更生效后审阅 `checkpoints/scout/<batch_id>.json` 与 `checkpoints/t1/<cluster_id>.json`
- **THEN** 其磁盘内容 schema 与变更前一致(新增的 `checkpoint_path`/`done_marker` 仅存在于 `list_*` stdout,不写入产物文件)

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
- 缺 `category` 的 candidate(含 `audit_found[]` 路径,该路径不经 `--check`)→ `_normalize` **跳过**该
  candidate、stderr warn、退出码 `0`,stdout 成功摘要 SHALL 含 `skipped` 计数显式披露丢弃数。

`_normalize` 取 category SHALL 用 `c.get("category")`(非 `c["category"]` 直索引)。本要求**不**改
`discover_controls.form_clusters`(共享逻辑;`_normalize` 跳过即阻断缺 category 候选进入)。

#### Scenario: merge_scout fold-in does not crash on malformed JSON
- **WHEN** `merge_scout.py --candidates … --scout <malformed.json> --clusters …` 被调用,且 `<malformed.json>` 不是合法 JSON
- **THEN** 进程退出码 `1`、**不**抛未捕获 traceback;stdout 为含 `error`/`file`/`lineno`/`colno` 的结构化 JSON,stderr 出可操作诊断

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
- **WHEN** 本变更生效后审阅 `discover_controls.py::form_clusters`
- **THEN** 其 `category` 取值方式与变更前一致(未改为 `.get`);缺 `category` 的 scout 候选在 `merge_scout._normalize` 即被跳过,不进入 `form_clusters`

