# fix-mgh-init-discover-resilience — control-discovery delta

## MODIFIED Requirements

### Requirement: Skip dot-prefixed paths during discovery

确定性文件遍历(`expand_scope.walk_sources` / `collect_dir` / `build_call_graph`)SHALL 在既有
`EXCLUDE_DIR` 精确匹配之外,**额外跳过**任何「相对 repo 的路径中存在以 `.` 开头的分量」的文件
(即点前缀目录与点前缀文件,如 `.opencode/`、`.claude/`、`.codegraph/`、`.github/`、`.husky/`、
`.env`)。该跳过 SHALL 作为文件枚举层的属性,统一作用于 regex 候选、`skeleton.json`、调用图与
scout 目标集(单一 chokepoint,承「Bounded single-pass scan」与「Extract lossless source skeleton」
的单遍复用语义),使全部下游阶段一致地不见点前缀路径,而非仅 regex 一路。

**剪枝判定按 repo 相对分量**:点前缀剪枝与 `EXCLUDE_DIR` 精确匹配的判定输入 SHALL 是
`path.relative_to(repo).parts`(**repo 内分量**),NEVER 绝对路径的全部分量——repo 在磁盘上的
**祖先目录**(如 repo 放在 `D:\build\work\`、`~\.cache\repos\`、`C:\out\` 等含排除名或点前缀
分量的位置下)SHALL NOT 影响仓内文件的剪枝判定;修复前按绝对全分量判定,repo 布局撞上排除名
祖先即**整仓静默扫空**。

`discover_controls.py` SHALL 提供 `--include-dotfiles` flag(默认关);传该 flag 时 SHALL 回退到
引入本要求前的行为(纳入点前缀路径)。理由:点前缀条目按 Unix 惯例为非一方业务代码(tooling /
VCS / IDE / build / config / 索引);默认扫描它们会把工具自身脚本(如运行时纪律守卫
`block_adhoc_scripts.py`)诱导成伪业务控制,污染 inventory 与生成的 rules 并浪费 LLM 预算。
既有 `EXCLUDE_DIR` 集合**保持不变**(通用点规则吸收其点成员,非点构建/缓存目录如 `node_modules`/
`target`/`build`/`vendor` 仍由其精确匹配负责)。本要求仅用 Python 标准库(`pathlib.Parts` /
`str.startswith`),承 R2 零运行时依赖。

#### Scenario: Installed tooling under a dot-prefixed dir is not discovered by default
- **WHEN** 目标项目根下 `.opencode/plugins/` 与 `.claude/hooks/` 各含一个匹配控制特征(如鉴权/校验
  关键字)的 `.py`/`.ts` 源文件,且未传 `--include-dotfiles`
- **THEN** 这些文件不出现在 `controls_candidates.json`、`skeleton.json`、调用图、scout 目标集中;
  它们诱导出的工具脚本(如 `block_adhoc_scripts.py`)**不**作为安全控制进入 inventory / 生成的 rules

#### Scenario: --include-dotfiles re-includes dot-prefixed paths
- **WHEN** 运行 `discover_controls.py --repo . --out .mgh-init --include-dotfiles`,且 `.opencode/` 下
  含一个匹配控制特征的源文件
- **THEN** 该文件被纳入候选/skeleton/调用图(行为等价于引入本要求前),不被点前缀规则跳过

#### Scenario: Dot-prefix skip is consistent across all downstream stages
- **WHEN** 默认运行 `discover_controls.py`,且 `.codegraph/` 与 `.claude/` 下各有一个源文件
- **THEN** `skeleton.json`、调用图(`build_call_graph` 产出)、`plan_scout.py` 的 scout 目标集三者
  **均不含**这些点前缀路径(单一 chokepoint,非仅 regex 候选一路排除)

#### Scenario: Non-dot build/cache dirs remain excluded (regression guard)
- **WHEN** 默认运行发现,且 `node_modules/`、`target/`、`build/` 下各有一个源文件
- **THEN** 这些文件仍被既有 `EXCLUDE_DIR` 精确匹配跳过(通用点规则不弱化既有构建目录剪枝)

#### Scenario: Windows drive root is not mis-excluded
- **WHEN** 在 Windows 上对 `C:\DEV\<repo>` 运行发现
- **THEN** 盘符根分量(`C:\`)不以 `.` 开头,不触发点前缀跳过;repo 下正常源文件照常被发现

#### Scenario: 排除名/点前缀祖先目录不吞整仓

- **WHEN** 目标 repo 位于 `D:\build\work\<repo>`(祖先分量 `build` ∈ `EXCLUDE_DIR`)与
  `D:\repos\.cache\<repo>`(祖先分量点前缀)下,各默认运行发现
- **THEN** 两布局下 repo 内源文件照常被发现(剪枝只看 repo 相对分量);修复前按绝对全分量判定,
  这两种布局整仓静默扫空(零候选、零 skeleton,退出码 0)

### Requirement: Reuse call-graph engine for control wiring

`discover_controls.py` SHALL 导入并复用 `expand_scope.build_call_graph`(D2:导入不改写),
为每个候选控制计算:`reverse`(谁调用了该控制)、`framework_files`(Spring Security 配置
等框架标记文件)、`name_to_files`(注解/方法名 → 定义文件)。经调用图关联到的入口写入
候选 `entry_points`;无法文本解析的框架路由控制(AOP pointcut / 反射 / DI)写入
`unresolved[]`。

**调用图构建 SHALL 两遍、顺序无关**:`expand_scope.build_call_graph` SHALL 先完整遍历一次
文件集建立**完整**定义索引(`name_to_files`)与框架标记,再遍历第二次解析调用边——调用解析
MUST 面对**全部**定义,NEVER 只见到枚举顺序中先于本文件的定义。理由〔单遍边走边建索引时,
文件 A 只能解析到 rglob 顺序中先于 A 的定义 → 约一半跨文件调用边**静默丢失**(不进
`unresolved[]`,零披露),文件名一变结果就变;`discover_controls.py` 内部实现同为两遍并自证
「Order-independent」,本条把该语义确立为共用引擎的规格〕。mgh-sast 侧对本脚本的 CLI 消费
(scope resolver)同享该修复。

#### Scenario: Control entry_points populated from reverse graph
- **WHEN** 一个 sanitizer 工具方法被多个 controller 调用
- **THEN** 该候选的 `entry_points` 包含这些调用方文件

#### Scenario: AOP-advised control reported unresolved
- **WHEN** 某鉴权逻辑仅通过 AOP pointcut 织入,无文本调用边
- **THEN** 该控制出现在 `unresolved[]` 而非 `entry_points`,并在 report 披露

#### Scenario: 跨文件调用边与文件枚举顺序无关

- **WHEN** 两个 Java 文件 A(定义 `mask()` 并调用 B 的 `check()`)与 B(定义 `check()` 并调用
  A 的 `mask()`)以两种相反的文件名(交换后)分别构建调用图
- **THEN** 两种枚举顺序产出的调用图逐边一致(A→B 与 B→A 双向边均在);修复前单向边随枚举
  顺序漂移,约半数跨文件边静默缺失

### Requirement: Scoped and partial-merge analysis

`--scope path:<dir>|package:<pkg>|file:<glob>` SHALL 限定分析种子。`--scope-mode`
SHALL 区分:`defined`(默认,控制定义点在 scope 内)与 `applicable`(控制调用方/入口
触及 scope)。跨模块但定义点在 scope 外的控制 SHALL 记入 `out_of_scope[]`(披露不丢)。
`mgh-init --merge <partials-dir>` SHALL 按 `evidence`(`file:class:method`)去重合并
多次局部产物,并跨模块重算 cluster role。

**scope 歧义输入 fail-loud**:`--scope path:<不存在路径>` 与 `--package:<无任何匹配目录>`
SHALL 退出码 2 + stderr recipe(指认路径/包名),NEVER 以「空种子集 + 退出码 0」静默成功——
拼错路径产出「该模块无存量控制」的**错误安全结论**(mgh-sast 侧丢全部 findings 同形态)。
「scope 目录存在但确无源文件」是合法空集:保持退出码 0 + 空集 note(与「路径不存在」
不可混淆的是二者 MUST 可区分)。

#### Scenario: Scoped run bounds to a module
- **WHEN** `mgh-init --scope path:src/payment --scope-mode defined`
- **THEN** 仅分析定义点在 `src/payment` 内的控制;跨模块控制入 `out_of_scope[]`

#### Scenario: Partial runs merge by evidence anchor
- **WHEN** 对模块 A、B 各跑一次局部 init,再 `mgh-init --merge partials/`
- **THEN** 合并后 inventory 按 `file:class:method` 去重,同一控制不重复,cluster role 跨模块重算

#### Scenario: 拼错的 scope 路径 fail-loud 而非空集假成功

- **WHEN** `expand_scope.py --path src/paymant`(目录不存在,typo)运行
- **THEN** 退出码 2 + stderr 指认该路径;NEVER 输出 `{"in_scope": [], "count": 0}` + 退出码 0
  (修复前与「目录存在但无源文件」不可区分,下游产出「该模块无存量控制」的错误结论);
  `--package com.acme.nomatch`(零匹配目录)同判退出码 2;目录存在但无源文件保持 exit 0 + note

### Requirement: Bounded single-pass scan performance on large repos

`discover_controls.py` SHALL 对每个源文件**至多读一次磁盘**(读入后缓存文本,供调用图两遍与候选
扫描共用);`walk_sources(repo)` 在单次运行中**只遍历一次**仓库并物化文件清单,供调用图构建与候选
扫描复用;每文件**仅调用一次 `splitlines()`**;候选的 enclosing 锚点 SHALL 通过**每文件预排序的
结构节点列表 + 按行二分**求解,而非「每候选对全文反复 `finditer`」。系统 SHALL 在扫描期间向
**stderr** 周期输出进度(每 N 个文件),stdout 仅在末尾输出既有 JSON 摘要(契约不变)。在 i0 阶段
SHALL 以低成本统计源文件数,命中大仓阈值时**在开始全量扫描前**主动建议 `--scope` 分模块 + `--merge`。

**文件配额只数源文件 + 截断显式上浮**:`walk_sources` 的 `limit_files` 配额 SHALL 仅对
**源扩展名文件**计数(`SOURCE_EXT` 命中者),非源文件(.txt/.xml/.sql/资产等)MUST NOT 消耗
配额;配额触顶时 SHALL stderr 告警并经可选 accumulator 形参(镜像 `dot_skipped`/`tests_skipped`
家族形态)向调用方上浮截断信号,NEVER 静默 return。理由〔配额被非源文件消耗时,大仓的截断
位置随枚举序不可预测;且 discover 侧的 `max_files+1` 截断哨兵(多 yield 一个源文件即判
truncated)建立在「配额只数源文件」的假设上——配额混计时哨兵永不触发,截断静默〕。

本要求**不再假设 discover 在单次宿主调用内必然完成**:当目标仓大到单次调用超过宿主 shell 超时
(claude Bash / opencode shell 工具默认 120s,可被强杀于更早),discover SHALL 经 callgraph 缓存 +
scan 续点 + 软时限干净早退(见「Discover call-graph cache survives re-runs」「Discover scan resumes
from a checkpoint」「Discover soft time-budget clean exit」「Discover writes are atomic」)**跨多次
编排器调用推进且零全损**,而非依赖「5 分钟内一发跑完」。

#### Scenario: Large repo completes across re-invocations without total loss
- **WHEN** 对一个单次调用即超过宿主 shell 超时的大目标仓运行 `/mgh-init`,且某次 discover 调用被宿主
  在超时处强杀
- **THEN** 已建成的 callgraph 缓存与 scan 续点**留存可用**,编排器 Bash 重派 `discover ... --resume`
  复用缓存、从续点继续,**不**从零重跑;经有限次重派后产物完整,期间**无**「`(no output)` 全损」形态

#### Scenario: Each source file read at most once
- **WHEN** 对任意目标仓运行发现脚本(单次调用内)
- **THEN** 每个源文件的磁盘读取次数为 1(调用图两遍与候选扫描共用同一缓存文本)

#### Scenario: Progress emitted to stderr only
- **WHEN** 扫描持续进行且尚未完成
- **THEN** stderr 周期性打印已扫描文件数;stdout 不在中途打印非 JSON 内容,末尾 JSON 摘要契约不变

#### Scenario: Large repo advised to scope before scanning
- **WHEN** i0 阶段统计的源文件数超过阈值
- **THEN** 系统在开始全量扫描前提示建议 `--scope` 分模块 + `--merge`,而非静默跑到超时

#### Scenario: 非源文件不耗配额,触顶显式截断

- **WHEN** 一个仓含 2 万个 `.txt`/`.xml` 资产与 2 个 `.java` 源文件,以默认 `limit_files=20000`
  运行 `walk_sources`
- **THEN** 两个 `.java` 均被 yield(非源文件不耗配额);对一个真超配额的源文件仓,触顶时 stderr
  告警 + 调用方 accumulator 收到截断信号(修复前 `.txt` 先把配额吃完、`.java` 静默丢失且零信号)

#### Scenario: discover 截断哨兵在混合仓下如实触发

- **WHEN** 源文件数超过 `--max-files` 的仓运行 `discover_controls.py`
- **THEN** stdout 摘要 `truncated:true`(哨兵 = 多 yield 一个源文件即判);混合扩展名仓下配额
  语义同判(修复前配额被非源文件消耗,哨兵永不触发,截断静默)

### Requirement: Sanctioned artifact-inspection primitive (no ad-hoc introspection)

`/mgh-init` SHALL 提供确定性叶脚本 `core/scripts/describe_artifact.py`,作为编排器/subagent
「瞄一眼产物结构」反射的**唯一合法出口**(专治「先理解结构再动手」的 `py -c` 反射,FD5)。其 SHALL
支持 `--in <json>` + 至少下列模式之一:`--keys`(顶层键)、`--count`(数组长度,对 wrapper dict 额外
warn 顶层键数 vs 目标数组长度,防 `len(wrapper)=3` 误判)、`--sample N`(数组首 N 项)、`--shape`(轻量
schema:键 + 类型 + 数组元素 shape)、`--field a.b.c`(取嵌套字段)。stdout = JSON 摘要;stderr = 诊断;
退出码 `0/1/2`;零依赖、自定位、utf-8、任意 cwd。编排器与 subagent MUST NOT 用 `py -c`/`python -c`
或 `Read` 整份大 JSON 去内省产物结构,SHALL 改用本脚本。

**`--field` 单独使用 SHALL 有界输出**:`--field` 不与 `--keys`/`--count`/`--sample`/`--shape`
组合时,stdout SHALL 回显**截断后的值**(实现常量上限)并携带 `truncated` 标志;目标为容器
(list/dict)时 SHALL 另报元素/键计数。理由〔无界回显整份值(如整份 `clusters[]`)正是本脚本
要替代的反模式——「合法结构出口」自己击穿编排器上下文预算〕。与其它模式组合时行为不变
(模式本身有界)。

#### Scenario: Count mode warns on wrapper-dict miscount
- **WHEN** 对 `clusters.json`(wrapper `{repo,clusters,truncated}`)运行 `describe_artifact.py --count`
- **THEN** stdout 报 `clusters[]` 真实长度,并对顶层 3 键给出 warn(防把 3 当簇数)

#### Scenario: Sample mode replaces reading the first element by hand
- **WHEN** 编排器想理解 `scout_plan.json::batches[]` 元素结构
- **THEN** 它运行 `describe_artifact.py --sample 1`,而非 `py -c "import json; print(json.load(open(...))['batches'][0])"`

#### Scenario: describe_artifact is self-contained and offline
- **WHEN** 从任意 cwd 以 `py <path>/describe_artifact.py --in <dir>/controls_candidates.json --keys` 执行
- **THEN** 脚本成功,stdout 为合法 JSON 摘要

#### Scenario: `--field` 单独使用输出有界

- **WHEN** 运行 `describe_artifact.py --in clusters.json --field clusters`(目标为 5000 条的大数组)
- **THEN** stdout 回显截断后的值(≤ 实现常量上限)+ `truncated:true` + 容器计数
  (`{"type":"list","count":5000,…}` 形态);NEVER 整份 5000 条倾倒进 stdout;`--field a.b --count`
  组合形态输出不变(计数模式天然有界)

### Requirement: Stage-boundary contract checks

每个 stage 产物的产出者 SHALL 暴露 `--check`(或独立 validator),编排器跑完一步、进下一步前 MUST
运行之;失败 MUST fail-loud(退出码 2)并回退重跑(泛化既有 `assemble_rules.py --check` 范式,承
openspec validate-at-boundary,FD7)。覆盖:`discover_controls.py --check`(candidates/clusters wrapper
+ 每条 `source` + cluster_id 唯一 **+ cluster_id 长度 ≤ 160**)、`plan_scout.py --check`(batches 非空除非
0 target、每批 bytes≤ budget、needs_slice 仅含超批文件)、`merge_scout.py --check`(每条 `source:"scout"` + `file:line` +
**每条 `category` 非空** + **破损 JSON(无法 parse)亦属边界失败、退出码 2** + 给 `JSONDecodeError` 的
`lineno/colno/msg` 与错位附近字节窗诊断)、`validate_inventory.py`(vvah design_controls 兼容 + evidence
锚点 + category→kind 归一)、既有 `assemble_rules.py --check`(rules 纯净性)。

`merge_scout.py --check` 对破损 JSON SHALL 返回退出码 `2`(非 `1`),使编排器闸门(仅在退出码 2 回退)
正确触发重跑 S4;诊断 SHALL 含 `lineno`/`colno`/`msg` 字段供定位。`category` 校验 SHALL 断言非空(不断言
枚举归属,枚举归一交给 `validate_inventory.py`)。

**`--check` 对「合法 JSON 但形状错」SHALL 结构化收口**:`discover_controls.py --check` 对
「JSON 可解析但 wrapper/集合形状错」(wrapper 非 dict、`candidates`/`clusters` 非 list 等)SHALL
记 violations 并以退出码 2 收口,NEVER 在任何输入形状上抛未捕获 traceback(裸崩的退出码 1
不在编排器闸门语义内;形状错分支 MUST 把目标归一为空集后再走逐条校验循环)。

#### Scenario: Check passes on a well-formed artifact
- **WHEN** 编排器对刚产出的 `scout_plan.json` 运行 `plan_scout.py --check`
- **THEN** 退出码 0,编排器进入下一步

#### Scenario: Check fails loud on a corrupted artifact
- **WHEN** 某 batch 的 `bytes` 超过 `--scout-batch-bytes`(或 wrapper 损坏)
- **THEN** `--check` 退出码 2,编排器回退重跑该步,不带着破损产物继续

#### Scenario: discover --check 对形状错的合法 JSON 报 violations 而非裸崩

- **WHEN** `controls_candidates.json` 内容为合法 JSON 但顶层是 list(非 wrapper dict),
  运行 `discover_controls.py --check`
- **THEN** 退出码 2 + violations 含「wrapper must be {repo,candidates[],…}」;NEVER 抛
  `TypeError: 'NoneType' object is not iterable` 之类的未捕获 traceback(修复前实测裸崩)

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

### Requirement: Discover scan resumes from a checkpoint

`discover_controls.py` SHALL 在 scan 阶段周期(每 `--progress-every` 文件)原子写续点
`<out>/cache/scan_progress.json`(至少含已扫文件索引 `scanned_index` 与累积候选)。`--resume` SHALL
复用 callgraph 缓存并从 `scanned_index` 续扫、追加候选(不重扫已续点文件);续点合并 SHALL 确定性、
幂等(同一续点重跑产等价候选集)。scan 完成后续点可保留(供再次 resume)或清理,均不破坏最终产物。

**续点参数指纹(混合候选集防线)**:续点 SHALL 记录生成它的**生效扫描参数指纹**
(`--scope` 种子集形态 + `--language`);`--resume` 时当前参数与指纹不符 → SHALL 弃续点从头扫 +
stderr 披露(旧候选集按旧参数产物处置),NEVER 在旧续点上以新参数续扫(修复前换参续跑把
新旧参数的候选静默混进同一集合)。指纹相符或参数缺省时续扫语义不变。

**续点增量日志(消灭 O(n²) 写放大)**:累积候选 SHALL 经追加式
`<out>/cache/scan_journal.jsonl` 落盘——每检查点窗口只**追加**该窗口新增候选(flush + fsync),
`scan_progress.json` 仅携带小体积元数据(`scanned_index`/`candidate_count`/`cid`/参数指纹);
`--resume` 读 journal 重放累积候选。scan 完成时 journal SHALL **保留**(完成态 `--resume` 幂等
no-op 依赖它重放候选供最终产物);journal 仅在**新扫描开始**(无续点/续点失效)时截断;
journal 行数与计数不符(撕裂/篡改)→ 弃续点重扫自愈;旧内联形续点(候选在 progress 文件内)
加载兼容。修复前每检查点全量重写累积候选列表,大仓下总写放大 O(n²)(GB 级冗余写)。

#### Scenario: Resume continues scan past a kill
- **WHEN** discover 在 scan 中途被强杀,留下 `scan_progress.json`(scanned_index=K),随后
  `discover ... --resume`
- **THEN** discover 跳过前 K 个已扫文件、从第 K+1 续扫,候选集等价于一次跑完的结果

#### Scenario: Resume is idempotent
- **WHEN** 对同一续点连续两次 `--resume`
- **THEN** 两次产出的候选集等价(不重复、不丢失)

#### Scenario: 换参 resume 弃旧续点而非混合候选集

- **WHEN** 第一次以 `--scope path:src/a` 扫至中途留下续点,随后以 `--scope path:src/b --resume`
  运行
- **THEN** stderr 披露参数指纹不符、旧续点被弃,本次从头按 `src/b` 扫描;NEVER 在 `src/a` 的
  已扫候选上继续追加 `src/b` 的候选(修复前产出两个 scope 的混合集合,零披露)

#### Scenario: 检查点写放大有界(增量 journal)

- **WHEN** 一个产出 5 万候选的仓以 `--progress-every 1000` 扫描,统计 `cache/` 下续点相关的
  累计写入字节
- **THEN** journal 追加总量与候选总量同阶(O(n)),`scan_progress.json` 恒为小体积元数据;
  修复前每 1000 文件全量重写累积候选,总写放大 O(n²)

### Requirement: Discover soft time-budget clean exit

`discover_controls.py` SHALL 提供 `--time-budget-ms <N>`(默认 0=关)。当置位且在安全边界已超预算时,
discover SHALL 落全部-so-far 产物(callgraph 缓存 + scan 续点)并在 stdout 增 `partial: true` +
`resume_hint`(可操作的重派提示)后**退出码 0**(干净早退,而非被宿主 SIGKILL 全损)。未置位或
未超预算时 SHALL 一次性跑完,stdout `partial: false`。编排器 SHALL 据 stdout `partial: true`
经 Bash 重派 `--resume`(编排器循环,**NEVER** 写 wrapper `.py`;承 R5.2 黑盒纪律)直至
`partial: false`。

**安全边界覆盖调用图两 pass(最贵阶段设防)**:安全边界 SHALL 扩展至 callgraph 两 pass 内部——
每 pass 以 `--progress-every` 节奏检查 deadline;pass 1(定义索引)完成后其完整态 SHALL 落
`cache/callgraph_defs.json`(原子写),`--resume` 时 manifest 新鲜则复用、跳过 pass 1;pass 2
(调用解析)中途超限 → 当即干净 partial 早退(退出码 0 + `partial:true`),已落盘的
defs 缓存 + scan 续点(如有)留存。理由〔修复前超时检查只在「callgraph 建成后」与 scan 边界,
两 pass 本身不设防——大仓最贵阶段被宿主硬杀即零全损(scan 续点尚未产生、图缓存未落)〕。

#### Scenario: Budget exceeded triggers clean partial exit
- **WHEN** 运行 `discover_controls.py --repo . --out .mgh-init --time-budget-ms 30000`,且单次调用 30s
  内跑不完
- **THEN** discover 在安全边界落缓存/续点后退出码 0,stdout 含 `partial: true` + `resume_hint`,无产物截断

#### Scenario: Budget off finishes in one go
- **WHEN** 未传 `--time-budget-ms`(默认 0),且仓规模在单次超时内
- **THEN** discover 一次性跑完,stdout `partial: false`,行为等价于引入本要求前

#### Scenario: Orchestrator re-dispatches on partial, never via wrapper script
- **WHEN** discover stdout 为 `partial: true`
- **THEN** 编排器经 Bash 重派 `discover ... --resume`;**不** `Write` wrapper `.py` 去循环

#### Scenario: 调用图 pass 途中超限干净早退且 pass 1 可复用

- **WHEN** 大仓运行带 `--time-budget-ms` 的 discover,预算在 callgraph pass 1 完成后、pass 2
  中途耗尽
- **THEN** 退出码 0 + stdout `partial:true`,`cache/callgraph_defs.json` 已落盘;重派 `--resume`
  复用 defs 缓存跳过 pass 1、从 pass 2 续跑——NEVER 从零重建两遍;修复前 pass 2 中途被宿主
  硬杀 = 零留存(scan 续点未产生、图缓存未写)

### Requirement: Discover writes are atomic

`discover_controls.py` SHALL 原子写出所有产物 JSON(`controls_candidates.json`/`clusters.json`/`skeleton.json`/
`cache/*`):先写 `<path>.tmp` 再 `os.replace` 落盘,使进程在任意时刻被 SIGKILL 都**不**留下
截断/半写 JSON(`--check` 与下游 `json.loads` 不会读到破损文件)。原子写仅用 Python 标准库
(`os.replace`/`pathlib`),承 R2 零运行时依赖。

**原子写家族统一覆盖 scout 计划**:`plan_scout.py` 写 `scout_plan.json` SHALL 同用
`.tmp` + `os.replace` 原子写(与 discover 产物、run_config 同族纪律)——半写的 plan 是
scout 层「损坏 plan」输入的主要供给源(`scout_complete` 对截断 plan fail-open 形态的上游
治理)。

#### Scenario: Killed mid-write leaves no truncated artifact
- **WHEN** discover 在写 `controls_candidates.json` 的过程中被强杀
- **THEN** 目标仓里**不**存在截断的 `controls_candidates.json`(要么完整、要么不存在),`.tmp` 残留可被
  下次运行覆盖

#### Scenario: check passes after an interrupted run
- **WHEN** 对一次被强杀后留下完整产物的 out-dir 运行 `discover_controls.py --check`
- **THEN** `--check` 读到合法 JSON,退出码 0(无破损文件误判为边界失败)

#### Scenario: scout_plan.json 原子落盘

- **WHEN** `plan_scout.py` 在写 `scout_plan.json` 途中被强杀
- **THEN** 磁盘上要么是完整 plan、要么无 plan(NEVER 截断半写 JSON);`.tmp` 残留可被下次覆盖

### Requirement: Persisted run configuration for stateless resume

`/mgh-init` 编排器 SHALL 在 step 0(参数解析后、花 token 前)原子写出
`<target>/.mgh-init/run_config.json`(`.tmp`+`os.replace`,承 "Discover writes are atomic"),记录**决定步骤图的本次
调用 flag**:`target`(绝对)、`format`、`scope`/`scope_mode`、`no_scout`、`no_codegraph`、`skip_consistency`、
`merge`(及 `merge_partials_dir`)、`include_dotfiles`、以及 `--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes`
预算与 `--scout-*` 参数。该文件是**起始态**意图记录,与既有**终态** `init_manifest.json`(版本/计数/出处)边界清晰、
互不替代。`resume_state.py` SHALL 消费 `run_config.json` 解析可选/codepath 分支。`run_config.json` 缺失或破损时,
`resume_state.py` SHALL fail-loud(退出码 2)+ stderr recipe(指向重跑 `/mgh-init --<flags>` 重建),MUST NOT 静默猜测
步骤图。该文件随 `.mgh-init/` gitignore(承既有 unit-inputs gitignore 约定)。

**崩溃恢复锚点的持久性(fsync)**:`write_runconfig.py` 的原子写 SHALL 在 `os.replace` 前对
tmp 文件 `flush` + `os.fsync`(run_config 与哨兵、gitignore co-write 同治)——仅 `os.replace`
的原子性不保证**内容**已落盘,掉电后可能出现「replace 完成、内容零长度」的 run_config,
恰好毒化崩溃恢复的唯一锚点。

**哨兵 domain 与位置单一来源**:`--init-dir` 显式传入且其基名为**规范运行目录名**
(`.mgh-init`/`.mgh-ut-init`)时,该位置承载的哨兵 domain SHALL 与目录名一致——与
`--run-root` 派生的域冲突的错组 → 退出码 2 + recipe(修复前显式错组如
`--init-dir <t>/.mgh-init --run-root .mgh-ut-init` 会把 mgh-ut-init 域的受信子树写进
mgh-init 的哨兵,激活错误域的写允许集);custom 名 `--init-dir` 保留既有「覆盖」旗标语义
(`--init-dir wins`,既有测试钉死);默认组合(不显式传参)行为零变化。

#### Scenario: Run config written atomically at start

- **WHEN** `/mgh-init --target <t> --format opencode --no-scout` runs and reaches step 0
- **THEN** `<t>/.mgh-init/run_config.json` is written atomically (no truncated half-write survives a mid-write kill) and
  records `format`/`no_scout`/absolute `target` verbatim from the invocation

#### Scenario: Resume consumes run config

- **WHEN** `resume_state.py` runs against a `.mgh-init/` whose `run_config.json` records `no_scout=true`
- **THEN** it reports the scout tier as skipped and never directs scout fan-out, matching the original invocation intent

#### Scenario: Missing run config fails loud, not silent

- **WHEN** `resume_state.py` runs and `run_config.json` is absent or unparseable
- **THEN** it exits code `2` with a stderr recipe telling the user to re-run `/mgh-init --<flags>` to rebuild it, rather
  than silently guessing a step graph that could diverge from the original intent

#### Scenario: 原子写内容经 fsync 持久

- **WHEN** 审阅 `write_runconfig.py` 的原子写实现并对一次正常 step 0 后的文件做崩溃恢复演练
- **THEN** tmp 写入后先 `flush` + `os.fsync` 再 `os.replace`(run_config/哨兵/gitignore 三处同治);
  掉电场景下 replace 完成则内容完整,NEVER 出现零长度 run_config

#### Scenario: 错组的 init-dir/run-root 被 fail-loud 拒识

- **WHEN** 调用 `write_runconfig.py --target <t> --init-dir <t>/.mgh-init --run-root .mgh-ut-init`
  (规范名目录与域来源冲突)
- **THEN** 退出码 2 + stderr recipe 指认冲突;NEVER 写出 domain=mgh-ut-init 而落在 .mgh-init
  的哨兵;custom 名 `--init-dir` 组合与默认组合行为不变
