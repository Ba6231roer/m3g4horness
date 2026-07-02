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

#### Scenario: Detect Spring authorization annotation
- **WHEN** 扫描到 `@PreAuthorize` / `@PostAuthorize` / `@Secured` / `@RolesAllowed`
- **THEN** 产出一条 `category: authorization` 候选,含文件与行号

#### Scenario: Detect sensitive-data masking utility
- **WHEN** 扫描到含 `mask` / `redact` / `脱敏` / `@JsonSerialize` 脱敏器 / Luhn 校验等方法特征
- **THEN** 产出一条 `category: data-masking` 候选

#### Scenario: Exclude non-source / build directories
- **WHEN** 候选落在 `target/`、`node_modules/`、`build/`、`vendor/` 等 `EXCLUDE_DIR`
- **THEN** 该候选被跳过,不计入 `controls_candidates.json`

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

`/mgh-init` 的编排器是宿主 agent 本身(按 `mgh-init.md` 用自身工具跑流水线,非写代码)。命令壳 SHALL 在正文最前列声明:确定性逻辑封装在 `discover_controls.py` / `chunk_sources.py`,直接 `Bash` 调用;agent MUST NOT `Write` 任何 `.py`(编排器/包装器/重实现),MUST NOT `Read` 叶子脚本 `.py` 源码进上下文(报错看 stderr),`Write`/`Edit` 仅用于产物;调用示例 SHALL 只传脚本声明的 flag——`--format` 由 T3 `init-rulewriter` 消费,`discover_controls.py` 不接受 `--format`。

#### Scenario: No orchestrator script is created
- **WHEN** 宿主 agent 执行 `/mgh-init`
- **THEN** agent 不 `Write` 任何 `.py`,而是用自身工具按提示词编排;命令壳正文最前列声明此角色定位

#### Scenario: Discover script not passed --format
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md` 中 `discover_controls.py` 的调用示例
- **THEN** 这些示例不含 `--format`;`--format` 仅出现在 T3 `init-rulewriter` 阶段的描述中

#### Scenario: Scripts invoked, not read, by the orchestrator
- **WHEN** 编排器执行 i1 发现阶段
- **THEN** `discover_controls.py` / `chunk_sources.py` / `expand_scope.py` 经 Bash 执行,其源码不被 `Read` 进编排上下文

#### Scenario: Discover accepts its documented flags
- **WHEN** 以 `discover_controls.py --repo . --out ./.mgh-init`(不带 `--format`)执行
- **THEN** argparse 不报「unrecognized argument」,脚本正常进入扫描

