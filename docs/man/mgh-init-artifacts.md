# `/mgh-init` 阶段产物字段参考

> **受众:人类**。本文是给维护者 / 首次读产物的人看的**字段级参考**:
> `.mgh-init/` 下每个产物文件里有什么字段、每个字段的取值是什么意思、缺了/坏了会怎样。
> 本文**只讲产物字段**,不讲怎么跑命令、不讲流程节点——那两件事分别看
> [`docs/man/mgh-init.md`](mgh-init.md)(用法)与 [`docs/mgh-init-工作流程详解.md`](../../mgh-init-工作流程详解.md)(节点流程)。
> 三份文档互补、互相链到;本文不复述它们的内容。
>
> **字段事实唯一依据 = 产出者脚本 / `core/contracts/init/` 契约**。脚本字段变更时本文 SHALL 同步更新,
> 不得凭记忆撰写(本仓已有多起 agent 虚构 before/after 的记录)。

---

## 0. 阅读指南:怎么用这份参考

一次完整运行会在 `<你的项目>/.mgh-init/` 下留下十几个中间产物。你看到某个文件,想知道
「它是干嘛的、字段什么意思、状态健康吗」——按文件查本文对应章节即可。每个文件章节统一四块:

1. **文件作用与 wrapper 结构**——这个文件回答什么问题、顶层长什么样(很多产物是"包装字典",
   列表数据挂在某个键下,不是顶层数组)。
2. **字段表**——字段名 + 取值语义。
3. **枚举取值说明**——`shape: centralized|distributed` 这类可取值各代表什么。
4. **谁消费它 + 缺失/异常影响**——哪些脚本/阶段读它,缺了或内容异常时流水线会怎样。

判断运行是否健康时,最常用的是这几个:判断"我在哪一步 / 下一步干嘛"读
`resume_state.py` 的 stdout(进度真相源在磁盘,不是对话记忆);盯长跑进度看
`fanout_progress.<tier>.json`;看最终统计与边界看 `init_manifest.json` + `report.md`。

---

## 1. 控制侧产物

### 1.1 `run_config.json` — 本次运行意图(起始态)

**作用与 wrapper**:本次调用的 flag 快照,决定步骤图(format / scope / no_scout / no_codegraph /
skip_consistency / merge / 预算 / scout-*)。由 `write_runconfig.py` 在 step 0 原子写出
(`.tmp` + `os.replace`,中途被杀最多留一个旧 `.tmp`,不会留半个 JSON)。它是**起始态意图**,
与终态的 `init_manifest.json` 边界清晰、互不替代。

```json
{"target": "<abs repo>", "format": "opencode|claude", "mode": "normal|merge", "...": "...", "budgets": {"..."}, "scout": {"..."}}
```

| 字段 | 取值 | 说明 |
|---|---|---|
| `target` | str | 绝对 repo 根;本次运行的分析对象 |
| `format` | enum | `opencode`\|`claude`,规则输出格式 |
| `mode` | enum | `normal`(全流水线)\|`merge`(多 scope 分片合并,写完即停) |
| `scope` | str\|null | `path:<dir>`\|`package:<pkg>`\|`file:<glob>`;null = 全仓 |
| `scope_mode` | enum | `defined`(只扫定义域)\|`applicable`(只保留被 seed 调用的候选) |
| `no_scout` | bool | true = 跳过 LLM scout 层,纯 regex |
| `no_codegraph` | bool | true = 跳过可选 codegraph 富化 |
| `skip_consistency` | bool | true = 跳过 T4 一致性 |
| `include_dotfiles` / `include_tests` | bool | 是否扫点前缀路径 / 测试源码树 |
| `merge` / `merge_partials_dir` | str\|null | 分片合并源目录(mode=merge 时用) |
| `language` / `rules_dir` | str\|null | 语言过滤 / opencode 详述目录 |
| `budgets` | dict | `max_unit_bytes`(每 fan-out 单元上限)/ `orch_budget_bytes`(编排器单页上限)/ `max_aggregate_bytes`(聚合上限) |
| `scout` | dict | `budget`(0=全目标)/ `batch_bytes` / `batch_cap` / `audit_pct` |

**谁消费它**:`resume_state.py`(stateless resume 的意图源,使 `/mgh-init --resume` 免重输 flag)、
`list_clusters.py`(scout 闸门判定)、`fanout_runner.py`(codegraph 开关信号)。

**缺失/异常影响**:`run_config.json` 缺失或不可解析 → `resume_state.py` **退出码 2** fail-loud
(绝不静默猜步骤图),recipe = 重跑 `/mgh-init --<flags>` 重建。随 `.mgh-init/` gitignore。

### 1.2 `.active` 哨兵 — 运行时守卫的磁盘激活信号

**作用与 wrapper**:声明"现在有个 mgh 命令在跑、目标是哪个目录",用于激活
`block_adhoc_scripts` 运行时守卫(opencode 插件进程不继承会话中途导出的环境变量,靠磁盘哨兵绕开)。

```json
{"domain": "mgh-init|mgh-ut-init", "target": "<abs repo>", "out_roots": ["<abs>", "..."], "v": 1}
```

| 字段 | 取值 | 说明 |
|---|---|---|
| `domain` | enum | `mgh-init`\|`mgh-ut-init`(由运行目录名推导) |
| `target` | str | 绝对 target(Windows 原生形态) |
| `out_roots` | [str] | **非默认**的 `--out` / `--rules-dir` 绝对根(只扩展、不镜像默认根) |
| `v` | int | 1,schema 版本 |

**谁消费它**:运行时守卫(激活判据 = env `MGH_*_ACTIVE=1` 或磁盘哨兵存在)。

**缺失/异常影响**:运行中(step != done)哨兵缺失 = 守卫休眠(脚本只读 / 越树拦截静默失效)→
`resume_state.py --check` 退出码 2 + re-arm recipe(`resume_state.py --rearm-sentinel`
确定性重写,或重跑 `write_runconfig.py`);run 正常完成时 `done.md` 收尾会 `rm` 掉它(避免残留锁死日常开发)。
step=done 时无哨兵**不**算违例(运行已拆,守卫本就该休眠)。

---

## 2. 发现侧产物(discover,确定性)

### 2.1 `controls_candidates.json` — 原始命中审计轨迹

**作用与 wrapper**:正则扫描的全部"疑似控制"命中 + 披露字段。由 `discover_controls.py` 一次写出。

```json
{"repo": "<abs>", "scope": {"mode": "defined|applicable", "seed": "...", "scope-mode": "..."},
 "generated_by": "discover_controls.py", "candidates": [<Candidate>, ...], "truncated": false,
 "tests_skipped": 0, "max_files_note": "...", "unresolved": ["<file>", ...], "out_of_scope": ["<file>", ...]}
```

`Candidate`(一条控制形状的命中):

| 字段 | 取值 | 说明 |
|---|---|---|
| `id` | str | `C-NNNN`,确定性递增 |
| `file` / `line` | path / int | 命中文件(相对 repo 的 posix 路径)与行号 |
| `category` | enum | 规范 8 类(见 §7) |
| `kind` | enum | vvah 6 类(见 §7 的 category→kind 表) |
| `pattern` | str | 命中的正则 token(如 `@EnableMethodSecurity`) |
| `anchor` | dict | `{class, method, kind}`——最近的类/方法包裹(文本级);`kind` ∈ `class\|method\|annotation\|field` |
| `snippet` | str | 命中行截断片段(≤160 字符) |
| `shape` | enum | `centralized`\|`distributed`(见 §2.2 枚举说明) |
| `cluster_id` | str\|null | 由 `form_clusters` 回填(发现阶段写完才有) |
| `entry_points` | [file] | 反向调用图上的直接调用方(≤8 个) |
| `big_file` | bool | 文件字节 > `--big-file-bytes`,须切片不能整读 |
| `source` | enum | `regex`\|`scout`\|`regex+scout`\|`codegraph`(缺省视作 `regex`) |

**枚举取值说明——`source`**:候选来源。regex 快路径、LLM scout 发现层、或 init-resolve 经
codegraph 解析 `unresolved[]` 得到的候选;是结构标识(同类纯净性规则),不是给人看的过程描述。
`regex+scout` 表示同一文件被两个来源命中。

**枚举取值说明——`shape`**(详细见 §2.2):`centralized` = 控制定义在一处(util/filter/config/
interceptor 类),按锚点归簇;`distributed` = 注解类控制跨文件散落,按 token 归簇。

**wrapper 级披露字段**:

| 字段 | 取值 | 说明 |
|---|---|---|
| `truncated` | bool | 扫描因 `--max-files` warn-and-continue 截断过(不静默) |
| `tests_skipped` | int | 默认剪枝跳过的测试源码树**源**文件数(`--include-tests` 时 = 0) |
| `max_files_note` | str | 截断时的披露说明,否则 `"ok"` |
| `unresolved[]` | [file] | 框架路由/Feign/AOP/DI 文件,文本调用图连不到任何候选(诚实披露盲区) |
| `out_of_scope[]` | [file] | 跨模块控制,定义点在 `--scope` 之外(披露、不丢弃) |

fold-in 后附加:`merge_scout.py` 在 wrapper 顶层追加 `provenance.scout_merged`(实际并入的 scout 候选数)。

**谁消费它**:`list_clusters.py --materialize`(候选命中回查)、`merge_scout.py`(fold-in)、
T1/T2、审计轨迹。

**缺失/异常影响**:与 `clusters.json` 必须同在或同缺(否则 `resume_state --check` 报
"discover products inconsistent");`--check` 断言 wrapper 形态 + 每候选带 `source` + `file`,
`tests_skipped` 须为非负整数。

### 2.2 `clusters.json` — T1 隔离单元清单

**作用与 wrapper**:把候选归成簇,每簇 = 一个 T1 归纳单元。**包装字典,非顶层数组**——对顶层
`len()` 得 3(`repo`/`clusters`/`truncated`),**不是**簇数;簇数真相源 = `discover_controls.py`
stdout 的 `clusters` 字段或 `list_clusters.py` stdout 的 `total`。

```json
{"repo": "<abs repo root>", "clusters": [<Cluster>, ...], "truncated": false}
```

`Cluster`(一个 T1 单元):

| 字段 | 取值 | 说明 |
|---|---|---|
| `cluster_id` | str | 确定性单元标识,形态见下;**总长 ≤ 160**(超预算截显示槽位、保留 sha8 判别尾) |
| `category` | enum | 规范 8 类 |
| `kind` | enum | vvah 6 类 |
| `shape` | enum | `centralized`\|`distributed`(见下) |
| `evidence_files` | [file] | T1 必读文件集;centralized = 成员去重,distributed = `usage_sites[:3]` |
| `usage_sites` | [file] | 使用点;distributed 上限 `--sample`;centralized = 证据文件 + 少量直接调用方 |
| `candidate_ids` | [`C-NNNN`] | 本簇成员候选 id(回指 `controls_candidates.json`) |

**枚举取值说明——`shape`**:
- `centralized`:控制定义在一处(一个 util / filter / config / interceptor 类),按**锚点**
  `category::anchor::file` 归簇。典型:`SecurityConfig` 里的整套授权配置。
- `distributed`:注解类控制跨文件散落,按 **token** `category::pattern` 归簇(同一注解出现在
  很多文件里)。典型:`@PreAuthorize` / `@Valid` 散落在各 controller。

**`cluster_id` 形态**(详见 `docs/glossary.md` 词条):
- centralized:`{category}::{anchor}::{file}::{sha8}`(sha8 = 完整 key 的 sha1 前 8 hex,判别身份);
  超长时截显示槽位(保目录头 + 文件名尾 + 槽位 hash)。
- distributed:`{category}::{pattern}::{sha8}`。
- 文件名是**存储编码非身份**:`cluster_id` 含 `::`(NTFS 的 Alternate-Data-Stream 分隔符),
  落盘文件名须经 `_safe_name` 消毒(`/` `\` `:` → `_`)+ stem 截长(≤200);canonical id 原样保留
  在 envelope / 检查点记录的 `unit` 字段。

**谁消费它**:`list_clusters.py`(T1 待办清单)、T1 每簇、`init-survey`(可选 advisory)。

**缺失/异常影响**:大仓上 `clusters[]` 可达数百——禁止单 subagent 整份装载;T1 经
`list_clusters.py` 逐簇隔离扇出。`truncated` = 扫描截断过,编排器须在 report 披露。空
`checkpoints/t1` + 数百簇是**正常前置态**(T1 还没开始),见 §6 的"830 簇场景"。

### 2.3 `skeleton.json` — 全仓结构地图(供 scout 选读)

**作用与 wrapper**:每个源文件的**纯机械**结构元数据(不含"是不是控制"的语义判定),是 scout
层选择"读谁"的全仓地图。由 `discover_controls.py` 与候选**同一趟**写出,覆盖全部非点前缀源文件
(包括被正则跳过的)。

```json
{"repo": "<abs>", "generated_by": "discover_controls.py", "files": [<FileSkeleton>, ...]}
```

`FileSkeleton`:

| 字段              | 取值     | 说明                                                        |
| --------------- | ------ | --------------------------------------------------------- |
| `file`          | path   | 相对 repo 的 posix 路径                                        |
| `lang`          | enum   | 语言键(java/python/js/ts/go/c/ruby/php)                      |
| `pkg`           | path   | 由 file 推导的目录,scout 按它做包内聚分批                               |
| `classes[]`     | [name] | 类/接口/枚举/record 名(去重,有上限)                                  |
| `imports[]`     | [str]  | import / `#include` / require / `from…import` 命中串(去重,有上限) |
| `method_sigs[]` | [name] | 定义名(len>2)                                                |
| `fan_in`        | int    | 反向调用图上该文件被多少文件调用(共享控制信号)                                  |
| `bytes`         | int    | 文件字节数,scout 按它做字节预算分批                                     |
| `big`           | bool   | 文件字节 > `--big-file-bytes`;与候选 `big_file` 同源,供 discover stdout `big_files` 统计 |
| `regex_hit`     | bool   | 是否已被 i1 正则命中(命中者已产候选,scout 不重复扫)                          |

**谁消费它**:`plan_scout.py`(scout 分批规划)、discover stdout 的 `big_files` 统计 + 审计。

**缺失/异常影响**:`plan_scout.py` 读不到它 → 退出码 1 fail-loud(输入缺失);scout 层没有
地图可选目标。`big` 缺失时 `big_files` 统计回退到候选去重计数(非完整文件数)。

---

## 3. Advisory 产物(可选,缺失不阻断)

### 3.1 `i1_enriched.json` — survey 富化

**作用与 wrapper**:`init-survey` 子代理(可选 LLM 富化层)对候选/簇做轻量 sanity-check +
校正(category/kind 纠偏、明显误报标 `confidence: low`)后的输出。**advisory**:不是 T1 的输入,
`resume_state.py` 只把它记进 `notes[]`。

**取值语义**:形态宽松(`list_steps.py` 标注为 `{summary[]}`;`init-survey.md` 的写法是"带校正的
candidates/clusters")。**不需要**逐字段对齐——它是给人读/审计的辅助件,不是契约面。

**谁消费它**:人读、审计轨迹;没有任何确定性脚本读它。

**缺失/异常影响**:缺失**不阻断**(`resume_state.py` notes:`"survey: optional/advisory —
i1_enriched.json absent does not block"`)。

### 3.2 `resolved.json` — codegraph 解析结果(可选)

**作用与 wrapper**:仅当 `codegraph=on` **且** `controls_candidates.json::unresolved[]` 非空时,
`init-resolve` 子代理产出;把文本调用图解不了的框架路由/AOP/DI 控制补一批候选。

```json
{"repo": "<abs>", "resolved": [<Candidate-subset, source:"codegraph">, ...], "unresolved_residual": ["<file>", ...]}
```

| 字段 | 取值 | 说明 |
|---|---|---|
| `resolved[]` | [Candidate-subset] | 每项是候选子集 + `source:"codegraph"` + **`resolved_path[]`**(codegraph 返回的调用/路由路径,每元素是真实 `file:line`/`file:symbol`,证明控制"接上了"而非死代码) |
| `unresolved_residual[]` | [file] | codegraph 也解不了的(纯反射/DI 容器/动态代理),只缩小不清零 |

**谁消费它**:编排器(additive 并入候选集,再走既有的 `form_clusters` 归簇);`init_manifest.json`
记 `codegraph.resolved_count` / `unresolved_residual`。

**缺失/异常影响**:缺失 = resolve 步被跳过(fail-soft,流水线不变);`resume_state.py` notes 披露
`"resolve: codegraph=on, unresolved=N — init-resolve recommended but optional/non-fatal"`。
`confidence` 不高——codegraph 只证明接线/存在,**不**证明有效(CVE-2025-41248)。

---

## 4. Scout 层产物

### 4.1 `scout_plan.json` — 侦察批计划

**作用与 wrapper**:`plan_scout.py` 把 regex 盲区文件切成字节有界、包内聚的批次,每批 = 一个
scout-reader 单元。

```json
{"repo": "<abs>", "generated_by": "plan_scout.py", "targets_total": 812,
 "regex_known_count": 222, "truncated": false, "batches": [<Batch>, ...]}
```

| 字段 | 取值 | 说明 |
|---|---|---|
| `targets_total` | int | scout 目标文件数(regex 盲区) |
| `regex_known_count` | int | 已被 regex 命中、排除出 scout 的文件数(产出者 emit,下游直接读禁自算) |
| `truncated` | bool | 目标超 `--scout-budget` 被截(编排器须建议 `--scope`+`--merge`) |
| `batches[]` | [Batch] | `{batch_id, targets[], bytes, needs_slice[]}` |

`Batch`:`batch_id` = `scout-NNN`(确定性,= checkpoint 单元名);`targets[]` = 本批 skeleton 行
(已按 pkg 排序 → 包内聚);`bytes` = 累计字节,须 ≤ `--scout-batch-bytes`;`needs_slice[]` =
单文件超预算者,scout-reader 须经 `chunk_sources.py` 切片读、**不整文件喂 LLM**。

**谁消费它**:`resume_state.py`(scout 层派生)、`list_scout_batches.py`(待办清单)、fanout 派发。

**缺失/异常影响**:scout 启用且缺它 → `resume_state.py` next_action = `plan_scout.py`。0 批次 =
没东西可侦察,`scout_complete` 视为真。

### 4.2 `checkpoints/scout/<batch_id>.json` — 每批侦察记录 + 终态标记

**作用与 wrapper**:每个 scout-reader 单元写完的检查点记录;同目录 `.done`/`.failed` 是终态标记。

记录体(由 `init-scout` 写):
```json
{"batch_id": "scout-001", "candidates": [<anchor>, ...], "unresolved": ["<file>", ...]}
```

**取值语义**:`candidates[]` = 本批发现的候选子集(带 `source:"scout"`);`unresolved[]` =
DI/AOP/反射等文本图解不了的控制文件(并入既有 `unresolved[]`)。

**终态标记约定**(scout / t1 / t3 三 tier 通用):
- `<id>.json.done`(空文件,touch 即成功):`list_*` 读**记录体的 `unit`/`batch_id` 字段**(或退而求其次文件名 stem)判完成;
- `<id>.json.failed`(body `{unit, reason, tier}`):确认失败,**终态**、resume 不重派、计入 tier 完成;
  失败无记录体仍可匹配(in-body 的 `unit`)。crash 无 ack → 无 marker → 单元仍 pending → resume 重派
  (**crash ≠ 确认失败**)。
- 人类可删 `.failed` 后 `--resume` 重派该单元。

本目录还有两个 **tier 级** marker:`merge.json.done`(scout 合并完成凭证)与 `audit.json`
(抽查结果,`merge_scout.py` 读它的 `audit_found[]`)。两者**不是** reader 批,计数时排除。

**谁消费它**:`list_scout_batches.py`(done/failed 判定)、`resume_state.py`(tier 计数)、
`init-scout-merge`(合并所有批记录)。

**缺失/异常影响**:读者批 `done+failed>=total` 但 `scout_candidates.json` 缺 → 完成凭证丢失,
`resume_state.py` 按 merge/fold-in 子状态给精确 note,唯一恢复路径 = spawn `init-scout-merge`
**诚实重生成**(绝不重跑非幂等的 `merge_scout.py` fold-in)。

### 4.3 `scout_candidates.json` — 合并后的侦察候选(完成凭证)

**作用与 wrapper**:`init-scout-merge`(单上下文,只看结构化记录不看源码)合并所有 reader 批的
候选。

```json
{"repo": "<abs>", "candidates": [<Candidate-subset, source:"scout">, ...], "unresolved": ["<file>", ...]}
```

**取值语义**:候选是 Candidate 子集(`file/line/category/kind/anchor/shape/evidence_snippet/confidence`)
且 `source:"scout"`;`unresolved[]` 并入既有 `unresolved[]`。类别归一在 fold-in 边界
(`merge_scout.py` 调 `normalize_category`,`access-control→authorization` 等;未映射的非规范类
在 `--check` 边界 fail-loud,不带漂移进 T2)。

**谁消费它**:`merge_scout.py`(fold-in 到 `controls_candidates.json` + 追加 `clusters.json`)、
`resume_state.py`(scout 完成凭证)。

**缺失/异常影响**:`scout_candidates.json` 缺失 + merge marker 在 + fold-in 已跑 = 凭证丢失
(`resume_state --check` 报镜像违例,退出码 2)→ 经 `init-scout-merge` 诚实重生成(内容仅作完成
凭证、无下游消费、LLM 漂移无害)。`merge_scout.py --check` 断言每候选 `source:"scout"` +
`file:line` + 规范 8 类 category。

---

## 5. T1 产物

### 5.1 `checkpoints/t1/<cluster_id>.json` — 每簇归纳记录

**作用与 wrapper**:`init-induct`(每簇隔离上下文)写的控制记录,**根级对象、每簇一条**。
T1→T2 边界由 `validate_t1_records.py` 机械校验(先 `--strip-bom` 再 `--check`)。

**字段表**(根级契约字段,`validate_t1_records.py` 断言):

| 字段 | 类型 | 说明 |
|---|---|---|
| `cluster_id` | str | 非空;canonical 簇 id |
| `name` | str | 非空 kebab slug(如 `spring-method-security`) |
| `category` | enum | 规范 8 类 |
| `kind` | enum | vvah 6 类;`category`→`kind` 须命中确定性映射 |
| `evidence` | [`file:class:method`\|`file:line`] | **≥1** 条真实读过的非空锚点 |
| `entry_points` | [file] | 流经它的调用方(可空) |
| `confidence` | number | int/float(bool 拒绝) |
| `description`/`usage`/`protects`/`gaps` | 散文 | **不**被断言(合法波动范围宽) |

**形状漂移签名**:出现根级 `controls[]` 键 = `nested controls[] drift` 违例(observed 失败形状:
字段被塞进 `controls[n]` 而不是根级)。命中即退出码 2,外科式重派该簇(`rm <file>.done` →
重跑 `list_clusters` 重派),NEVER 带破损记录进 T2。

**"830 簇场景"(空 checkpoints/t1 + clusters.json 有 830 簇)**:
这是 **T1 尚未开始的正常前置态,不是损坏**。原因:T1 受**确定性层序闸门**约束——`run_config.json`
启用 scout(`no_scout=false`)而 scout 层未完成时,`list_clusters.py` 直接退出码 2
(`{"error":"scout-incomplete-gate"}`,无 `pending[]`),**无法**对纯 regex 簇集扇出 T1(治"搁浅 scout
直奔 T1"的失败)。因此:先完成 scout 层(读 `resume_state.py` stdout 的 `step`/`next_action`),
或显式 `--no-scout` 走纯 regex。判断 T1 是否健康用 `resume_state.py`(tiers.t1.done/failed/total),
不用"目录空不空"猜。

**谁消费它**:`list_clusters.py`(done 判定,读记录 `unit` 字段)、`resume_state.py`(tier 计数)、
`validate_t1_records.py`(形状闸门)、`init-synthesis`(T2 综合)。

**缺失/异常影响**:`--check` 空目录 = `ok:true, records:0`(T1 是否跑过由 `resume_state` 判,
不是形状 validator 的职责)。

---

## 6. T2 产物

### 6.1 `controls_inventory.json` — 已有安全控制总清单

**作用与 wrapper**:`init-synthesis`(T2,单上下文,只看 T1 记录不看源码)归纳出的跨产品清单,
**与 vvah `design_controls` 向后兼容**(`kind`/`protects`/`notes`)。下游 `/mgh-sra`、`/mgh-blst`
消费它,故破损必须在 T2 边界 fail-loud(`validate_inventory.py`),不能带病传播。

```json
{"repo": "<abs>", "format": "opencode|claude", "generated_at": "<iso>",
 "controls": [<Control>, ...], "competing_clusters": [{"cluster_id":"...", "canonical":"<name>", "members":["<name>",...]}]}
```

`Control`:

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | str(slug) | 稳定 id,如 `spring-method-security` |
| `kind` | enum | vvah 6 类 |
| `category` | enum | 规范 8 类 |
| `description` | str | 是什么,1–2 行(简体中文) |
| `usage` | str | 开发者应该怎么调用(规则正文,简体中文) |
| `evidence` | [`file:class:method`\|`file:line`] | **≥1** 条具体锚点(索引用,不贴长代码) |
| `entry_points` | [file] | 流经它的调用方 |
| `protects` | [fnmatch glob] | `design_controls` 兼容;从控制 + 调用方推导 |
| `notes` | str | `design_controls` 兼容自由文本 |
| `gaps` | [str] | 覆盖缺口 / 未解析 / 有效性 caveat |
| `cluster_id` | str | 分组竞争控制 |
| `role` | enum | `canonical`\|`competing`\|`duplicate`\|`possibly-dead`(**T2 设**) |
| `confidence` | float | 0–1;低证据 / 验证分歧会压低 |

**枚举取值说明——规范 8 类 + category→kind 映射**(确定性,源头 `init_tier.KIND`):

| category | kind |
|---|---|
| `input-validation` | `input-validation` |
| `authentication`、`authorization` | `auth` |
| `data-masking`、`crypto`、`csrf`、`rate-limiting`、`audit-logging` | `other` |

kind 的 vvah 6 枚举:`auth`\|`input-validation`\|`sandbox`\|`aslr`\|`cfi`\|`other`。
alias 复用(入账也认):`authn`/`authz`/`rbac`/`iam`/`sso`→`auth`;`waf`/`validation`/`sanitization`/`encoding`→`input-validation`;`seccomp`/`container`/`isolation`→`sandbox`。

**谁消费它**:`list_rule_jobs.py`(T3 待办)、`validate_inventory.py`(T2 边界闸门)、
`resume_state.py`(t3 层派生)、`/mgh-sra`、`/mgh-blst`。

**缺失/异常影响**:`validate_inventory.py` 断言 wrapper `{format, controls[]}` + 每控制带
`name`/`kind`(vvah 6)/`category`(init 8)/`category`→`kind` 归一 + ≥1 非空证据锚点;违例退出码 2。
`resume_state --check` 也查"t2 `.done` 在但 inventory 缺"等不一致。

---

## 7. T3 / 装配 / 收尾产物

### 7.1 `checkpoints/t3/*.<fmt>.json` — 每分类规则写的终态标记

**作用与 wrapper**:T3(init-rulewriter,每分类隔离上下文)的 checkpoint 目录。真正的产出 = 落盘的
**规则文件** `rule_path`(claude:`.claude/rules/security-<cat>.md`;opencode:`<rules-dir>/<cat>.md`
详述文件);本目录的 `<category>.<fmt>.json.done` / `.failed` 是**终态标记**(`.json` 记录体为可选、
无确定性消费方)。`<fmt>` = `opencode`|`claude`,按 run 的 `--format`。

**取值语义**:`list_rule_jobs.py` 对每个待写分类 emit `{category, format, rule_path, done_marker,
failed_marker, input_path, bytes, oversize}`。category **不切分**(rulewriter 需整分类视图);
超 `--max-unit-bytes` 标 `oversize` + recipe(建议 `--scope`+`--merge`)。

**谁消费它**:`list_rule_jobs.py` / `resume_state.py`(done/failed 计数)、`assemble_rules.py`
(opencode 扫详述文件建索引)。

**缺失/异常影响**:一个分类所有控制都无源码锚点 → 不产规则文件但仍 touch `done_marker`
(该分类视为已处理);`assemble_rules.py` 纯净性 lint 失败(规则正文泄漏工具内部 token /
schema 字段 / 过程散文 / opencode `---` 围栏)→ 退出码 2,回 T3 修正后重跑。

### 7.2 `init_manifest.json` — 终态统计 + 边界披露

**作用与 wrapper**:由**编排器**在收尾步(i4)写出,是本次运行的**结果**(与起始态的
`run_config.json` 互不替代)。版本 / 计数 / 出处 / 诚实边界全在此。

```json
{"version": 7, "format": "opencode|claude", "repo": "<abs>",
 "scope": {"seed": "...", "scope-mode": "defined|applicable"},
 "counts": {"candidates": 0, "controls": 0, "clusters": 0, "unresolved": 0, "out_of_scope": 0, "truncated": false},
 "failures": {"scout": {"done":0,"failed":0,"total":0}, "t1": {"done":0,"failed":0,"total":0}, "t3": {"done":0,"failed":0,"total":0}},
 "scout": {"enabled": true, "skeleton_total": 0, "scout_targets": 0, "batches": 0, "deep_read_files": 0, "audit_sampled": 0, "audit_found": 0, "scout_merged": 0},
 "codegraph": {"available": false, "used": false, "resolved_count": 0, "unresolved_residual": 0},
 "rules": {"block": "security-controls", "rules_dir": "...", "rules_layout": "...", "categories": 0, "migrated_legacy_blocks": 0, "lint": {"ok": true, "violations": []}},
 "provenance": {"discover": "...", "induct": "...", "synthesis": "...", "rules": "...", "scout": "...", "resolve": "..."},
 "unresolved": ["<file>", ...], "out_of_scope": ["<file>", ...],
 "boundaries": ["existence-not-effectiveness: ...", "call-graph is textual/AST-level ...", "..."]}
```

**取值语义要点**:`counts` = 各产物计数;`failures` = 三个 fan-out tier 的**确认失败**披露
(读数取自 `resume_state.py` stdout,磁盘真相、绝不凭对话记忆);`scout.scout_merged` = fold-in
实际并入的 scout 候选数(缺省 = 没声称);`codegraph.available/used` = 检测到 `.codegraph/`+CLI /
`codegraph=on` 且 init-resolve 实跑;`boundaries[]` = 人类读的诚实边界清单(existence≠effectiveness、
文本调用图盲区、请求预算、点前缀/测试剪枝、codegraph 辅助性、LLM 候选需人审、re-entrant resume、
partial fan-out 容忍、scout 部分覆盖、opencode 惰性索引语义等)。

**谁消费它**:人读、`/mgh-sra`、`/mgh-blst`、`resume_state.py`(done 判定)。

**缺失/异常影响**:它是 `step=done` 的完成凭证——缺失时 `resume_state.py` 报
`step=done, resumable=true`,next_action = "finalize: write init_manifest.json + report.md"。

### 7.3 `report.md` — 人读总结

**作用与 wrapper**:收尾步由编排器写的**人读总结**(简体中文):产物路径 + 各阶段计数 + 诚实边界
(fan-out 失败披露、codegraph 用量与残留盲区、scout 部分覆盖、LLM 候选需人工复核等)。**非契约面**、
无机械 schema——给维护者一个"这次跑完到底发现什么、还有什么没覆盖"的入口。

**谁消费它**:人类维护者。

**缺失/异常影响**:终端报告;缺失不影响 resume/下游消费(真相都在 JSON 产物里),但它是"不读
JSON 也能懂"的门面,收尾步应始终写出。

---

## 8. 运行态披露(给人看的进度)

### 8.1 `fanout_progress.<tier>.json` — 长跑进度快照

**作用与 wrapper**:`fanout_runner.py`(scout/t1/t3 三 tier 的确定性波次派发器)每波 + 每次退出
原子刷新的人读进度 sidecar。**给人看**(第二终端 `Get-Content -Wait`);编排器 / 任何 agent
**从不读它**——它不是真相源、不是契约产物,`resume_state.py` 与 `init_manifest.json` 既不读也不校验;
残留的旧副本(含改名前 `fanout_progress.json`)无害。

```json
{"ts": "<ISO 本地时间>", "host": "opencode|claude|test", "tier": "scout|t1|t3",
 "total": 830, "done": 12, "failed": 0, "pending": 818, "wave": 5, "waves_run": 3,
 "wave_done_avg_s": 42.5, "eta_batches": 818, "state": "running"}
```

| 字段 | 取值 | 说明 |
|---|---|---|
| `ts` | ISO | 本地时间戳(秒精度) |
| `host` | enum | `claude`\|`opencode`\|`test` |
| `tier` | enum | `scout`\|`t1`\|`t3`(每 tier 一个文件,防 resume 交错互相覆盖) |
| `total`/`done`/`failed`/`pending` | int | 计数与同波次 stdout 摘要同源(single source) |
| `wave` / `waves_run` | int | 并发度 / 已跑波次 |
| `wave_done_avg_s` | float | 单波均耗(参考值,非承诺精度) |
| `eta_batches` | int | 保守 ETA(按每波槽位一个单元粗估) |
| `state` | enum | `running`\|`exited-partial`(软时限早退,可 `--resume` 重派)\|`exited-clean`(跑完) |

**谁消费它**:人类维护者(第二终端盯 `done` 是否在涨;`done` 长时间不涨且 `state` 一直是
`running` 才需介入)。

**缺失/异常影响**:写失败只 stderr warn、永不中断派发循环(伴生文件的正确姿态)。

---

## 9. 附:同目录其它运行时文件

以下文件是 `.mgh-init/` 的一部分,但非流水线主产物,简要列出:

| 路径 | 是什么 | 说明 |
|---|---|---|
| `cache/manifest.json` | 调用图缓存新鲜度快照 | `[{rel,mtime,size}]`,按 rel 排序;discover 与当前源码逐字节比对,变脏即重建 |
| `cache/callgraph.json` | 调用图缓存 | `{forward, reverse, framework_files}`;命中跳过两趟正则 |
| `cache/scan_progress.json` | 扫描续点 | `{scanned_index, candidates[], manifest}`;`--resume` 从此继续 |
| `inputs/<tier>/<unit>.input.json` | 每个 fan-out 单元的**完整输入**物化 | 由 `list_* --materialize` 写;subagent 只读自己的 `input_path`,编排器 NEVER 整份读聚合 |
| `slices/<tier>/<unit>/` | 大文件切片输出 | `chunk_sources.py --out` 落这里;绝对、树内、随运行域清理 |
| `checkpoints/t2/synthesis.json`(+`.done`)、`checkpoints/t4/consistency.json.done`(或 `t4/.done`) | 聚合 tier 完成 marker | T2/T4 为全仓单上下文,完成即一个 marker |

**Marker 通用约定**(全 tier):`<id>.json.done` = 完成(空 touch);`<id>.json.failed` =
确认失败(终态、不重派、计 tier 完成);crash 无 ack = 无 marker = 仍 pending = resume 重派。
`resume_state.py --check` 会抓"同一单元 `.done` 与 `.failed` 并存"的歧义终态。
