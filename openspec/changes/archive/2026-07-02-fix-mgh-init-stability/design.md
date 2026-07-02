## Context

`/mgh-init`(`add-mgh-init`,已归档)实现完整,但首次在真实大仓(opencode,目标仓 21611 个
Java 文件)实战时连续踩 5 个问题(`mgh-init-issues.md`),任务中止。问题不重叠,根因分三层:

| 问题 | 层 | 根因(已核实) |
|---|---|---|
| 1.1 编排器读 `.py` 进上下文 | 编排纪律 | `mgh-init.md` 未声明「脚本是黑盒」 |
| 1.2 `discover_controls.py --format opencode` 被拒 | 契约 | 两份命令壳把 `--format` 写进发现脚本调用;**该脚本无 `--format` 参数**(`main()` 仅 `--repo/--out/--scope/--scope-mode/--language/--max-files/--big-file-bytes/--sample`)。`--format` 属 T3 `init-rulewriter` |
| 1.3 21611 文件 300s 超时 | 性能 | `build_call_graph_bounded()` 两遍 × `scan()` 一遍 = 每文件读 3 次;`walk_sources(repo)` 在两处各遍历全仓一次;`scan()` 内**每候选** `text.splitlines()` ×2 + `_enclosing()` 对**全文 finditer** → 大文件上拟线性爆炸 |
| 1.4 `No module named 'expand_scope'` | 导入鲁棒性 | `from expand_scope import …` 依赖「`py script.py` 自动把脚本目录加进 `sys.path[0]`」;非规范调用(错 cwd / 包装器 / `python -c exec`)下失效。`install.sh` **已**随 `cp -r core/.` 拷了 `expand_scope.py`(line 72),故非缺文件,是导入脆弱 |
| 1.5 `python -c exec` 触发 gbk 错误 | (1.4 的绕行副作用) | 该绕行用 locale 默认编码读 UTF-8 脚本;Windows 中文 locale=gbk → 解码失败。脚本自身读源码已显式 `encoding="utf-8"` |

约束:R2 零运行时依赖;R1 复用 `expand_scope.py`(导入不改写,延续 D2);产物 schema 不变
(`controls_candidates.json`/`clusters.json` 字段与候选集合须等价);stdout 末尾 JSON 摘要契约不变。
利益相关方:任何中大型目标仓的 `/mgh-init` 首跑;opencode + claude-code 双壳;下游 `/mgh-sra`/
`/mgh-blst`(消费 inventory,不感知本次内部重写)。

## Goals / Non-Goals

**Goals:**
- `/mgh-init` 在**数万源文件**的目标仓上**首跑即成**(5 分钟内、无人工干预参数试错)。
- 发现脚本**可作为黑盒被宿主 agent 直接执行**——任意 cwd、任意调用方式,不报 import 错、不需
  `python -c exec` 绕行。
- 命令壳↔脚本**契约自洽**:调用示例只传脚本实际声明的 flag。
- 编排器**不把确定性脚本读进上下文**(对齐 `mgh-sast.md`)。
- 零新增运行时依赖;产物 schema 与候选语义零回归。

**Non-Goals:**
- **不**引入多进程/线程并发扫描(`multiprocessing` 虽是标准库,但 Windows + opencode 子进程
  约束下风险高;算法层单遍重写已足够把 21611 文件压进分钟级,列为 Open Question)。
- **不**改 `expand_scope.py` 本体(延续 D2/R1;硬化只在 `discover_controls.py`/`chunk_sources.py`
  的导入侧)。
- **不**改产物 schema、不改 CLI 合法参数集(仅修文档对不存在 flag 的误用)。
- **不**判定控制「有效」、不实现 sra/blst(沿用既有 Non-Goals)。
- **不**调小 `--max-files` 默认值(D11「无静默截断」原则不变);大仓改由 i0 前置建议 + 单遍提速解决。

## Decisions

### FD1 — 契约修正:移除发现脚本上的 `--format`(`--format` 属 T3)

`discover_controls.py` 是 **format 无关**的:它只产 `controls_candidates.json` + `clusters.json`,
与 `--format claude|opencode` 无关;`--format` 只在 T3 `init-rulewriter` 渲染 rules 时消费(见
`rules-emission` spec)。修法:删除 `releases/claude-code/commands/mgh-init.md` 与
`releases/opencode/command/mgh-init.md` 中 `discover_controls.py` 调用示例里的 `--format`
(opencode ×2 处:编排流 + 确定性调用块;claude ×1 处:确定性调用块——其编排流块本就未带)。

**为何不反向「给 discover 加 `--format`」(否决)**:会让 format 无关的确定性脚本背负一个它不用的
参数,污染契约、误导「发现阶段也分 format」。`--format` 的语义边界(仅 T3)是 `rules-emission`
spec 已确立的正确设计,应改文档而非迁就错误文档。

### FD2 — 兄弟导入自定位(`sys.path.insert`),不改 install / 不抽包

在 `discover_controls.py` / `chunk_sources.py` 的 `from expand_scope import …` **之前**插入:

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
```

使其在任意 cwd / 宿主调用方式下都能定位同目录 `expand_scope.py`。

**否决替代:**① 改 `install.sh` 把脚本拷到别处 / 打包——`cp -r core/.` 已正确拷全;问题在导入
脆弱非缺文件,改安装不治本。② 抽 `core/scripts/_callgraph.py` 共享模块(Open Questions 里 D2 已
提过的方向)——超出本次硬化范围,且同样需要导入侧 robust,先不抽。③ 把 `expand_scope` 内联进
两个脚本——违反 R1/D2「复用导入不改写」,膨胀维护面。`sys.path.insert` 是 Python 处理「同目录
兄弟模块」的标准 robust 模式,改动最小、可单测覆盖。

> `__file__` 在「直接 `py`/`python script.py`」下始终有定义;唯一无 `__file__` 的是
> `python -c "exec(open(...).read())"`(即 1.5 的绕行)——本决策的目标正是让该绕行**不再被需要**。

### FD3 — 单遍 I/O 重写(性能核心)

四个互独立优化,合起来把「每文件读 3 次 + 每候选全文 finditer」降到「每文件读 1 次 + 每候选
O(log n)」:

| 优化 | 现状(爆炸点) | 改法 |
|---|---|---|
| 文件读取 | `build_call_graph_bounded` pass1+pass2 + `scan` = 读 3 次 | 读一次缓存 `(rel,lang,text,lines)` 到 list,三阶段共用 |
| 仓库遍历 | `walk_sources(repo)` 在 graph 与 scan 各调一次 = 全仓 rglob ×2 | 物化一次 `(path,lang,rel)` 清单,两阶段复用 |
| splitlines | `scan` 内**每候选** `text.splitlines()` ×2(line 260) | 每文件**一次**预算 `lines`,候选按索引取 |
| enclosing | `_enclosing` **每候选**对全文 `CLASS_RX.finditer` + `def.finditer` | 每文件**一次**预排序结构节点(class/fn 的 `line_start`),候选按行**二分**取最近前驱 |

**否决替代:多进程并行**(`multiprocessing` 池分片扫描)——虽标准库、提速明显,但:Windows
spawn 成本高、与 opencode/claude 已有的子进程层叠可能冲突、序列化大文本有内存压力、调试面变大。
算法层单遍已把 I/O 与每候选复杂度压下,先不做并发(记入 Open Questions,实测后若仍不够再加)。

> 内存:缓存全部文件文本在 ≥1.5M 行仓上可能显大——以 `--max-files`(默认 200000)为天然上限,
> 且大仓本就被 FD4 引导去 `--scope` 分模块。单文件文本在 `--big-file-bytes`(200KB)以上的仍走
> 缓存(发现阶段需全文做调用图),分片只影响**喂 LLM** 的切片(D7,不变)。

### FD4 — 可观测:i0 大仓预检 + stderr 进度

- **i0 预检**:命令壳在扫描前以低成本统计源文件数(复用 `walk_sources` 物化的清单计数),超阈值
  (如 >15000)时**在扫描前**主动提示「建议 `--scope` 分模块 + `--merge`」,取代「跑 5 分钟再超时」。
- **stderr 进度**:`discover_controls.py` 扫描期每 N(如 1000)文件向 **stderr** 打印进度
  (`scanned=… clusters_so_far=…`)。stdout 仍在末尾打印既有 JSON 摘要——**契约不变**,进度走
  stderr 不污染 stdout JSON。

**为何不直接调小 `--max-files` 默认(否决)**:违反 D11「无静默截断」(显式告警并继续)。大仓的正确
出口是 `--scope`+`--merge`(D10),由 FD4 前置建议引导,而非悄悄少扫。

### FD5 — 编排器黑盒纪律(对齐 mgh-sast)

在两份 `mgh-init.md` 顶部「You are the orchestrator」段后加显式条款:**确定性脚本
(`discover_controls.py`/`chunk_sources.py`/`expand_scope.py`)是黑盒,经 Bash 执行,禁止 `Read`
进上下文;仅 subagent 的 `core/prompts/stages/*.md` 按需读取**。与 `mgh-sast.md` 的「黑盒脚本调用」
范式对齐(其编排器不读 `prefilter.py`/`dedup.py` 源码)。

### FD6 — 安装自检 + 回归单测

- **install.sh**:镜像 `core/` 后校验 `expand_scope.py`/`discover_controls.py`/`chunk_sources.py`
  三者在 `<dest>/mgh-core/scripts/` 同目录共存,缺一报错。`cp -r core/.` 已覆盖,显式校验为防御
  部分/陈旧安装 + 自文档化。
- **`tests/test_init_runtime.py`**(新增):(a) 把两脚本作为子进程在**非脚本目录的 cwd** 下执行,
  断言不报 import 错;(b) 单遍重写后对同一 fixture 的候选集合与「黄金」**等价**(字段/聚类不变);
  (c) 大文件 + 多候选的简单计时断言(不退化到旧的每候选全文 finditer 量级)。

### FD7 — 编排器即宿主 agent,禁止代码化(强化 FD5;实测反馈追加)

实测反馈:opencode 即使在 FD5 的「黑盒」提示下,仍 (a) `Read` 叶子脚本源码进上下文,
(b) 误判「编排器应是 Python 脚本」而 `Write` 出 `mgh_init.py`。根因:原措辞「**Implement** it
by running…」的 "implement" + 黑盒规则位置靠后 → agent 把流水线当成「待实现的代码」。

修法(置于两份 `mgh-init.md` 正文**最前列**的「角色铁律」,优先级最高):

1. **明示角色**:编排器 = 宿主 agent 本人,用自身工具(Bash/Agent/Read/Write/Edit)按提示词
   **跑**流水线,不是写代码。
2. **显式禁止 codegen**:MUST NOT `Write` 任何 `.py`(具名反例 `mgh_init.py` / `orchestrator.py` /
   包装器)。确定性逻辑已在叶子脚本,直接调用。
3. **禁止读源码**:MUST NOT `Read` 叶子 `.py` 源码;报错看 stderr。
4. **界定合法 `Write`**:仅产物(rules / inventory / manifest / report / checkpoints)。
5. 去 trigger 词:「Implement it」→「Carry it out」。

**为何不反向「真的提供一个 `mgh_init.py` 编排器」(否决)**:会把 LLM 阶段(T1/T2/T3/T4 扇出、
subagent 调度、归纳)塞进 Python,违背「LLM 阶段由宿主 agent 的 subagent 执行」的核心架构
(D1/D12),且无法用标准库零依赖地驱动 LLM。编排器天然是 prompt,不是脚本——与 `mgh-sast.md`
同构。FD5 的「黑盒」是被忽略的弱信号;FD7 把它升级为正文首条硬铁律 + 具名反例 + 角色澄清。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 单遍重写引入候选集合回归(顺序/去重/聚类变化) | FD6(b) 黄金等价单测;既有 `test_init_discover.py`/`test_init_clusters.py` 双重保护;`clusters.json` 字段不变 |
| 缓存全文件文本在大仓内存膨胀 | 以 `--max-files` 为上限;FD4 引导大仓 `--scope`;单遍本身减少「多次 read_text」的峰值重复占用 |
| `sys.path.insert` 在极罕见情况改变了用户同名模块的解析优先级 | 只插**脚本自身所在目录**,该目录即 `expand_scope.py` 的权威位置,语义正确;单测覆盖 |
| stderr 进度被某些宿主当作错误流误判 | stderr 是进度/日志的标准去向;stdout JSON 契约不变;进度文案明确为信息性 |
| 单遍仍不够快(超大规模仓 >10 万文件) | FD4 前置建议 `--scope`;Open Questions 留并发后路;阈值可调 |
| `--format` 移除后,旧文档/笔记里仍写 `--format` | 命令壳是唯一权威调用源;双壳同步改;无外部 API 消费者 |

## Migration Plan

1. 按 tasks 落地:先 FD2(导入硬化)+ FD1(契约修正)→ 再 FD3(单遍重写)+ FD4(可观测)→
   FD5(编排纪律)→ FD6(自检 + 单测)。
2. `py tests/test_init_discover.py` + `tests/test_init_clusters.py` + `tests/test_chunk_sources.py`
   + 新 `tests/test_init_runtime.py` + `tests/test_deterministic.py` 全绿;零依赖自检无输出。
3. `./install.sh --opencode <javarepo>` 后,在该 21611 文件仓实测 `/mgh-init --format opencode`,
   确认 <5min 完成、产物齐全、无 import/编码错误。
4. 同仓 `--format claude` 复测。
5. **回滚**:纯内部重写 + 文档修正 + 单测新增;回滚 = 还原 4 个文件 + 删 1 测试,无数据迁移、
   无 schema 变更。

## Open Questions

- **是否需要并发扫描?** 先以 FD3 单遍 + FD4 `--scope` 引导覆盖数万级文件;若实测 >10 万文件仍超时,
  再评估 `multiprocessing` 分片(需实测 Windows/opencode 子进程叠加下的稳定性)。
- **i0 大仓预检的文件数阈值**定多少?倾向 15000(对应「首跑即可能 >5min」的经验线),实测校准。
- **进度打印频率** N:倾向 1000 文件一次(平衡噪声与 liveness),实测调。
