## Context

`/mgh-init` 的确定性调用图(`discover_controls.build_call_graph`:name→files 两遍正则)是**纯文本/AST**
级,结构性解不动 **框架路由 / DI / AOP / interface→impl / 反射**——这些被明文丢进 `unresolved[]`
(`init-scout.md` 硬规则;`control-discovery` spec「Reuse call-graph engine」)。同时 scout/induct/survey
subagent 靠 **Read/Glob/Grep 逐文件爬**,token/轮次随仓线性涨,恰在 mgh-init 自己建议 `--scope`+
`--merge` 的大仓上最痛。

**codegraph**(外部工具,SQLite 知识图谱 + `codegraph_explore` MCP / `codegraph explore` CLI)预计算了
符号+调用边+**17 框架路由**+interface→impl+跨文件解析,单次调用返回源码+调用路径+blast radius;claude
与 opencode 双端均有 MCP;benchmark 示大仓 file-reads→~0。它是**宿主能力**,非 pip 依赖。

本变更(Tier B)让 codegraph 在**目标项目已建索引**(`<target>/.codegraph/`)时,作为**可选、检测闸控的
富化后端**进入 mgh-init 的 **LLM 层**:外科式上下文(替代 Read 爬)+ `unresolved[]` 解析器(直击诚实边界
盲区)。**确定性 `.py` 契约零改动、零新增运行时依赖、codegraph 缺席即 fail-soft 回退现状**。

## Goals / Non-Goals

**Goals:**
- codegraph 在场时:scout/induct/survey 一次 `codegraph_explore` 取符号源码+调用路径+blast radius,降低
  token/轮次(大仓收益最大);Read 仅作 codegraph 未覆盖项回退。
- 新增可选 `init-resolve` stage:用 codegraph 排空 `unresolved[]`(框架路由/DI/AOP/interface→impl),
  产 `source:"codegraph"` 证据 **additive** 并入候选集,fail-soft。
- T1 induct 拿 codegraph blast-radius 作 advisory,强化「存在≠有效」(CVE-2025-41248)。
- `init_manifest.json`/`report.md` 披露 codegraph 用量 + 残留盲区(R5.4 无静默)。
- **R5 全线合规**:不新增 `.py`、不改确定性脚本契约、不新增 hook、双端 MCP 对等。

**Non-Goals:**
- **不改** `discover_controls.py`/`plan_scout.py`/`merge_scout.py` 契约(R5.3);codegraph 不进确定性层。
- **不**把 codegraph 做成硬依赖(R2 产品特性 + 「业务项目可能没有」现实);内网无 codegraph 项目零影响。
- **不**用 codegraph 替代 regex 发现或 LLM 归纳——它是「定位/上下文化/解析」,非「分类」。
- **不做** scout 批次裁剪(Tier C,触 `plan_scout` 分批契约,R5.3 风险)——拆后续变更。
- **不碰** `/mgh-sra`/`/mgh-sast`/`/mgh-blst`(codegraph 富化 `interface_authz` 留后续;本次 mgh-init only)。

## Decisions

### D1 — codegraph 进 LLM 层,不进确定性层
codegraph 作为 MCP 工具(subagent 消费)/ `codegraph` CLI(编排器 Bash)介入,**绝不**被任何 `.py`
`import` 或在 `discover_controls.py` 里 `subprocess` 调。
- **理由**:R2(零运行时依赖)+ R5.3(确定性脚本自包含、契约稳定)。把可选外部工具耦合进稳定契约 =
  既有零依赖自检 + 内网零联网分发产品特性被破坏。LLM 层是 codegraph 的天然消费点(它本就是给 agent
  的外科式上下文工具)。
- **替代(否决)**:在 `discover_controls.py` 加 `subprocess.run(["codegraph",...])` 作 resolver——虽 `subprocess`
  是 stdlib,但把可选外部二进制编进确定性契约,违反「确定性脚本 = 黑盒、任意环境可 `py`」语义。

### D2 — 检测 = `.codegraph/` 目录 + `codegraph` on PATH;三段回退
编排器起步段(Bash)检测:`test -d <target>/.codegraph && command -v codegraph`。信号 `codegraph=on|off`
透传 subagent task。subagent 工具回退序:**① MCP `codegraph_explore`**(主,claude/opencode 双端)→
**② CLI `codegraph explore <sym>`**(Bash,MCP 不可用时)→ **③ Read/Glob/Grep**(codegraph 未覆盖语言/
超 `--big-file-bytes` 文件/索引未含项)。
- **理由**:MCP 是 codegraph 官方推荐面;CLI 兜底保证「有索引但 MCP 未注入 subagent」仍可用;Read 兜底保证
  不丢覆盖。
- 默认 `auto`;`--no-codegraph` opt-out(对齐既有 `--no-scout`/`--no-enforce-hook` 模式)。

### D3 — `init-resolve` 是新可选 stage,additive,fail-soft,单上下文(非 fan-out)
插在 **scout-merge 与 T1 之间**。输入:`unresolved[]` 文件清单(编排器经**合法出口** `describe_artifact.py
--field` 取得,NEVER `py -c`)+ repo root。用 codegraph `callers`/`explore` + 框架路由解析,对每条 unresolved
控制产出 `source:"codegraph"` 证据锚点(`file:line` + 解析出的调用路径)→ `resolved.json`,**additive** 并入
候选集(复用 `form_clusters`,不 mutate regex/scout 候选)。
- **单 subagent 上下文**(对标 `init-scout-merge`/T2 的「仅结构化记录」模式),**非 fan-out** → 无需新 `list_*`
  脚本(R5.3b 扇出规约不触发)。
- **fail-soft**:codegraph off / `unresolved[]` 为空 / 过大(超单上下文预算)→ 跳过整 stage + 摘要披露,流程
  不阻断(对标 `init-survey` 的 optional/advisory/non-fatal 语义)。
- **理由**:`unresolved[]` 正是 codegraph vs 文本图的能力差,是最独特、最高价值的契合点。

### D4 — codegraph-primary steering(主谓非「可」),规避「subagent 仍 Read」陷阱
codegraph 官方明示:「subagent 若仍自行 Read,codegraph 成纯开销」。故片段措辞用**主谓**(codegraph 在场
时 **SHALL 优先** `codegraph_explore`,Read **仅** 作回退),**非**「you may use」。并要求 subagent 在 task
输入见到 `codegraph=on` 信号才启用,避免无索引项目空跑 codegraph 调用。
- **理由**:把 codegraph 的已知失败模式(被绕过)前移成提示词硬约束,而非靠 agent 自觉。

### D5 — 双端对等:claude + opencode 均经 MCP
codegraph 官方 installer 双端注入 MCP server(`codegraph install --target claude,opencode`)。故 subagent
提示词只需声明「用 MCP `codegraph_explore`」,双壳(claude `agents/` + opencode `agent/`)镜像同一 `core/prompts/`
片段,**无需**为 opencode 写额外胶水(异于 R5.7 的 `block_adhoc_scripts` 需 `.ts` 插件,因那是宿主事件归一化,
codegraph 是 MCP 标准面)。
- **验证项(Open Question O1)**:确认 opencode subagent 上下文继承 codegraph MCP server;若不继承,fallback
  序 D2②(CLI Bash)兜底。

### D6 — 不新增 hook(R5.7 不触发新违例类)
`codegraph explore`(Bash)与 `codegraph_explore`(MCP)**均不**命中 `block_adhoc_scripts` 任一拦截面:
非 `py -c`/`python -c`、非 `Write *.py`、非子树外 `Write/Edit`(MCP 工具名 `mcp__codegraph__*` 根本不走
Bash/Write/Edit matcher)。故 codegraph 富化**不引入新的 #1 违例类**,R5.7「每命令 #1 违例配 hook」不触发
新 hook。既有 `block-adhoc-scripts`(双端)继续治理既有违例,行为不变。

### D7 — 披露 codegraph 用量,不声称全解析
`init_manifest.json` 增 `codegraph:{available,used,resolved_count,unresolved_residual}`;`report.md`/`boundaries[]`
明示「codegraph 辅助解析了 N 条、残留 M 条」+ codegraph 自身静态分析上限(反射/DI/运行时分派——缩小但不归零
`unresolved[]`)。**既有三条诚实边界不动**(文本图盲点仍真;codegraph 是其上的可选 resolver)。

## Risks / Trade-offs

- **[codegraph 自身静态上限]** 反射/DI 容器/运行时分派,codegraph 亦解不动 → `unresolved[]` 缩小不归零。
  → **缓解**:D7 显式披露 `unresolved_residual`;resolve 产物标 `confidence`,不优于 regex/scout 证据等级。
- **[subagent 绕过 codegraph 仍 Read(codegraph 成开销)]** → **缓解**:D4 主谓 steering + task 信号门控;
  R5.7 评估闭环(若实测 subagent 仍 Read,回灌片段措辞)。
- **[opencode subagent 不继承 MCP]** → **缓解**:D5 fallback D2②(CLI);O1 验证。
- **[收益随仓规模变化]** codegraph benchmark 示 token 收益「大仓显著、小仓噪声」。小仓上 codegraph 可能
  反增调用。 → **缓解**:`auto` 检测 + `--no-codegraph` opt-out;大仓(正是 mgh-init 痛点)收益最大,可接受。
- **[codegraph 索引滞后]** 文件 watcher ~1s 滞后;刚改的文件可能 stale(codegraph 自带 staleness banner)。
  → **缓解**:片段要求 subagent 见 codegraph `⚠️ pending` banner 时对该文件回退 Read(遵循 codegraph 官方指引)。
- **[新增 stage 增运行时成本]** init-resolve 多一个 subagent。 → **缓解**:off 时零成本;on 时仅对
  `unresolved[]` 非空项目起作用,且单上下文 bounded。

## Migration Plan

- **纯 additive,无迁移**:`--no-codegraph`(默认 `auto` 检测)完整保留现状;codegraph 缺席项目行为零变化;
  `controls_inventory.json` schema 不变(`source` 增一枚枚举值 `codegraph`,既有消费者按结构字段读,不破)。
- **回退**:任何子步骤失败/超预算 → 该 step fail-soft 跳过 + 披露;`--no-codegraph` 一键回到引入前行为。
- **版本**:`mgh-init.md` 两壳 + 受影响 `core/prompts/**` bump 版本号(承 R5.8)。

## Open Questions

- **O1**:opencode subagent 上下文是否继承 codegraph MCP server?(影响 D5 主路径;apply 阶段实测验证,不行
  则 fallback CLI。)
- **O2**:`init-resolve` 单上下文 vs 按 `unresolved[]` 分批(若大项目 unresolved 过大)?v1 取单上下文 + bounded
  fail-soft;若实测溢出,后续按 scout fan-out 模式分批(届时需 `list_resolve_jobs.py`,触 R5.3b)。
- **O3**:`resolved.json` 是并入 `controls_candidates.json`(经 `merge_scout.py` 扩展)还是独立消费?倾向独立
  产物 + 编排器透传给 T1(避免改 `merge_scout` 契约);apply 阶段定。
