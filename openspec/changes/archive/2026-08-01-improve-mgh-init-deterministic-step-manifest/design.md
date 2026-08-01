# Design — improve-mgh-init-deterministic-step-manifest

## Context

`new_issue26073002.txt` #1 + 「衍生想法」:模型在 opencode 下把脚本路径猜成 `scripts/merge_scout.py`
(实际 `.opencode/mgh-core/scripts/`),靠自探索重试才找到;用户要求把每步 {输入格式/脚本绝对路径/
产物路径/产物格式} 以「每次执行都能准确确认」的形式落地。D6(`harden-mgh-opencode-hook-enforcement`
design)显式把「统一声明式 step manifest」列为**残量**,并指出它与 R5.6 token 预算**直接冲突**——
本变更的核⼼设计约束就是**用零提示词 token 的方式补这块残量**。

**既有覆盖盘点(D6 已核实,本变更不重做)**:

| manifest 子项 | 已有机制 | 覆盖 |
|---|---|---|
| 当前 step / next_action | `resume_state.py` stdout `step`/`next_action` | ✅ |
| 磁盘态(起/终态) | `run_config.json` / `init_manifest.json` | ✅ |
| fan-out 单元输出绝对路径 | `list_*` stdout `checkpoint_path`/`rule_path`/`done_marker`/`failed_marker`(R5.3b) | ✅ |
| stage→脚本/提示词组件 | 命令壳 `Stage → component map` | ✅ |
| 调用示例(含宿主前缀) | 命令壳 `Deterministic invocation (Bash)` 块 | ✅(但**散落 + 宿主前缀硬编码**) |
| implementation-intention recipe | 命令壳 Orchestrator discipline 段 | ✅ |

**未被覆盖的残量(本变更治)** = 每步「确切脚本调用行 + 输入/产物 shape」以**运行时可查、零提示词 token、
宿主前缀正确-by-construction** 的形式存在。#1 的失败形状 = 上下文压力下模型没合成散落信息、转而猜
宿主前缀(`.claude/mgh-core/` vs `.opencode/mgh-core/`)。

## Goals / Non-goals

**Goals**:
- G1 消除「猜宿主前缀」失败类:每步确切脚本调用行**经脚本安装位置派生**,模型逐字直抄,无可猜空间。
- G2 零提示词 token:manifest 是**运行时 stdout**,NEVER 内联进提示词正文(护 R5.6,直击 D6 冲突点)。
- G3 pre-run 可查:无 `run_config.json` / `.mgh-init/` 前置(治 #1 多发于 run 起步/中途/压缩后)。
- G4 与既有 `list_*` 族同构:命名、self-contained 契约(R5.3)、`--help` 即契约面(R5.1)一致。

**Non-goals**:
- N1 **不**把全量 manifest 表塞进任一提示词(正是 D6 警告的 R5.6 冲突;本变更反其道,做运行时出口)。
- N2 **不**改既有确定性脚本契约、不改磁盘 schema、不加 CLI flag 到既有脚本(纯 additive 新脚本)。
- N3 **不**扩到 sast/sra/srr(本变更 init-scoped,对齐 issue 范围;pattern 可后置移植,见 D5)。
- N4 **不**替代命令壳既有 `Deterministic invocation` 示例块 / inline flow(它们仍可直抄;manifest 是
  「确认 / 兜底 / 压缩后重建置信」互补层,非替代)。

## Design decisions

### D1 — 新增 `list_steps.py` 独立叶脚本(不扩 `resume_state.py`,不内联表)

三选一:

| 方案 | 优点 | 缺点 | 裁决 |
|---|---|---|---|
| **A 新增 `list_steps.py`**(本选) | 与 `list_*` 族同构;零磁盘前置(pre-run 可查);不碰「热文件」`resume_state.py`(近期被 context-resilience + partial-fanout 两改);关注点分离(静态契约 vs 磁盘态) | 新脚本(R5.2 评估,见下);step id 与 resume_state 各一份→需一致性测 | ✅ |
| B 扩 `resume_state.py`(加 `--manifest`/`next_invocation` 字段) | 单一 step-graph owner;复用「resume step 1 = resume_state」纪律;无新脚本 | 要求 `run_config.json` 存在(否则 exit 2)→ **pre-run 不可查**(弱化 G3);把静态契约塞进磁盘派生工具(气味);热文件再加担=回归风险 | ✗ |
| C 命令壳顶部内联统一表 | 一处可读 | **扩两份提示词 token**(直撞 R5.6,正是 D6 警告);双壳各一份→手镜像漂移 | ✗ |

**R5.2 评估(新增脚本合规性)**:`list_steps.py` 是纯 stdlib 只读枚举脚本,与既有 `list_chunks`/
`list_clusters`/`list_rule_jobs`/`list_scout_batches`/`list_verify_jobs` 同族(全是「emit 规范化清单」
叶脚本),非运行时依赖、非包装器、非内省微脚本。`install.sh` 镜像到 `.claude/mgh-core/scripts/` 与
`.opencode/mgh-core/scripts/`。合规。

### D2 — 宿主前缀经 `__file__` 派生 → 正确-by-construction(无可猜空间)

`list_steps.py` 把每步脚本调用行 emit 为**绝对路径**,该路径 = `Path(__file__).resolve().parent / "<sibling>.py"`
(本脚本所在 `scripts/` 目录的同族文件)。

- claude install 下 `__file__` = `<target>/.claude/mgh-core/scripts/list_steps.py` → 同族路径
  `<target>/.claude/mgh-core/scripts/discover_controls.py`;opencode install 下同理落 `.opencode/`。
- **「宿主前缀」概念坍缩**:不需要「检测宿主再选前缀」——脚本 emit 它**实际所在** scripts 目录的同族
  绝对路径,哪个宿主装的就对哪个宿主。**双壳 `.claude/` vs `.opencode/` 手镜像漂移**这一整类失效模式
  从根上消除(对齐 `list_*` 的 `checkpoint_path` 绝对化纪律,R5.3b)。
- dev 仓下(`core/scripts/list_steps.py`)emit `core/scripts/<x>.py`——dev 位置,亦正确。
- 模型逐字直抄绝对路径(任意 cwd 安全,无相对路径歧义);**NEVER** 猜 `scripts/` vs `mgh-core/scripts`、
  **NEVER** 漏宿主前缀。

### D3 — 静态契约,零磁盘前置(pre-run 可查,G3)

`list_steps.py` **不读** `run_config.json`、**不扫** `.mgh-init/`、**不依赖**任何 run 态产物。step→IO 表是
**静态的**(管线定义不变则不变),故任意时刻可 `py list_steps.py` 查询——包括 run 起步前、压缩后、
纯文档审阅。这与 `resume_state.py`(磁盘派生、要求 run_config)形成互补分工:

- 「我在哪 / 下一步干什么」→ `resume_state.py`(磁盘真相);
- 「这一步的确切调用行 / 全量 step→IO map」→ `list_steps.py`(静态契约)。

二者**配套**用(压缩后:`resume_state` 给 step → `list_steps --step <id>` 给确切调用行)。

### D4 — 契约镜像 + 跨脚本一致性测(防双真相源漂移)

step id 在两处:`list_steps.py`(静态表)与 `resume_state.py`(step 枚举 + 阻塞序列)。为防漂移:

- **人读单一真相源** `core/contracts/init/step-manifest.md`:逐 step 列 {script(相对 `core/scripts/`)、
  输入产物 + shape、产物路径 + shape},与 `list_steps.py` stdout 镜像,并列于既有 init 契约。
- **一致性单测** `tests/test_list_steps.py`:断言 `list_steps.py` emit 的 step id 集与 `resume_state.py`
  的 step 枚举(`not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`)**一致**
  (或 documented 超集);断言每 step 的 script 名在 `core/scripts/` 实际存在(防指向幽灵脚本);
  断言 claude/opencode 两 install 镜像下前缀均正确(测安装镜像,非 dev 位置)。
- **不**共享 step-definition 模块(会让两脚本耦合 + 增 import 面);一致性测足矣(承 R5.8 回归兜底)。

### D5 — scope:init-only;pattern 可后置移植(不为本变更做)

本变更 init-scoped(对齐 issue #1 范围 + partial-fanout 的 init-scoped 先例)。sast/sra/srr 各有 stage→脚本
映射,理论上同样受益于 `list_steps`-style 出口,但:① 各命令的 step 图独立、无共享 owner;② 本次 issue
未报告 sast/sra/srr 的路径漂移;③ 跨命令统一 manifest 是更大跨切设计(与 R5.6/上下文预算交互复杂)。
→ 本变更**不**做;在 `step-manifest.md` 契约留一句「pattern 可经对称 `list_steps` 后置移植到其它 mgh-*」
作为未来锚点,不落实现。

### D6 — 命令壳 recipe:1 行,净 token 中性或略降

双壳 Orchestrator discipline 段 +1 行确认 recipe(见 proposal What Changes)。既有 `Deterministic invocation`
示例块 + inline flow **保留**(示例可直抄,manifest 非替代)。**不强求**删除既有散落路径硬编码(风险 >
收益,且示例块对直抄有用);仅在 recipe 点明「逐字可执行的每步确切调用行 → `list_steps.py` stdout」。
故净 token ≈ 中性(+1 行 recipe,manifest 表不内联)。若审阅时发现明显冗余散落路径可去重,属 opportunistic,
非本变更硬指标。

## Risks / Trade-offs

- **[双真相源 step id 漂移]** → 缓解:跨脚本一致性单测(D4);契约 `step-manifest.md` 作人读锚点;step 枚举
  变更(新加 stage)时两处同步 + 测必 fail(R5.8)。
- **[manifest stdout 被「总是调用」→ 挤占 stdout 预算]** → 缓解:`list_steps.py` 默认摘要(每 step 1 行紧凑
  JSON);`--step <id>` 单步;`--all`/默认行为在 `--help` 契约明示(不静默截断,承 R5.3b)。
- **[新脚本 = 新 CLI 契约面,R5.1 lint 面]** → 缓解:`tools/check_contracts.py` 按既有机制断言双壳引用的
  `list_steps.py` 每个 flag 经 `--help` 存在;`list_steps.py --help` 自身即契约面。
- **[模型不记得调用 `list_steps.py`]** → 缓解:recipe 写进 Orchestrator discipline 段(always-loaded 壳正文,
  1 行);与 `resume_state` 配对出现(压缩后首步调 resume_state,recipe 紧邻提示 `list_steps` 取确切调用行)。
  残余风险 = 提示词护栏层(非确定性),记入诚实边界。
- **[dev 位置 vs install 位置 emit 路径不同]** → 非风险:`__file__` 派生在两上下文均正确(dev emit dev
  同族路径;install emit install 同族路径);测覆盖两形态。

## Migration Plan

- **纯 additive**:新脚本 `list_steps.py` + 新契约 `step-manifest.md` + 双壳 +1 行 recipe + 新测;既有脚本 /
  磁盘 schema / CLI flag / stage 提示词**零改动**。
- **install 镜像**:`install.sh` 把 `list_steps.py` 随 `core/scripts/` 镜像到 `.claude/mgh-core/scripts/` 与
  `.opencode/mgh-core/scripts/`(既有镜像机制,无需特殊处理);自检 fail-soft 校验同目录共存(承 R5.8)。
- **版本号 bump**(承 R5.8);`tools/check_contracts.py` + `tools/check_distributed_purity.py` 绿(新契约仅操作性内容)。
