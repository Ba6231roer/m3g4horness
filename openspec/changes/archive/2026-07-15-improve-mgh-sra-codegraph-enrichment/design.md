## Context

`/mgh-sra` 的三信号匹配里,**信号-2「业务域相似」是语义判定**——靠接口路径文本相似 + `file_overlap`
(`prepare_augment.py` 文本相交 flag)推断「这条存量控制守护的是同业务域类似接口」。这条信号回答不了
**结构性**问题:**该控制到底接没接到这条缺口的接口的请求路径上?**——而它恰恰由 `@PreAuthorize`/AOP
pointcut/DI 织入的拦截器/Feign 路由表等**框架路由**决定,文本/AST 解不动(与 mgh-init 文本调用图
`build_call_graph` 同源盲点,落到 mgh-init 就是 `unresolved[]`)。结果:「文件重叠」的存量控制可能被
语义误推为「可复用」,而它其实根本不在该接口请求链上(对这条缺口近乎死代码)——正是 SRA 自己的诚实
边界「维度匹配为语义判定,可能误接或漏接」+「引用控制断言存在不断言有效」。

同时 a3 `sra-augment` subagent 靠 **Read/Glob/Grep 逐文件爬**核验锚点真实;`prepare_augment.py` 的业务面
抽取器(`_ENDPOINT_RX`/`_ROLE_HAS_RX`/`_SENS_SUBSTR`)也全是文本正则,抓不到框架注解/路由表里的真实端点与角色。

**codegraph**(外部工具,SQLite 知识图谱 + `codegraph_explore` MCP / `codegraph explore` CLI)预计算了
符号+调用边+**17 框架路由**+interface→impl+跨文件解析,单次调用返回源码+调用路径+blast radius;claude
与 opencode 双端均有 MCP。它是**宿主能力**,非 pip 依赖。

本变更(Tier B,与 `improve-mgh-init-codegraph-enrichment` 对称)让 codegraph 在**目标项目已建索引**
(`<target>/.codegraph/`)时,作为**可选、检测闸控的富化后端**进入 mgh-sra 的 **LLM 层**:外科式上下文
(替代 Read 爬)+ **★ 请求路径结构确认**(把信号-2 从语义判定升级为结构证据,直击 SRA 盲区,对标
mgh-init 的 `unresolved[]` 解析)。**确定性 `.py` 契约零改动、零新增运行时依赖、codegraph 缺席即
fail-soft 回退现状**。

**姊妹变更协同**:若 `improve-mgh-init-codegraph-enrichment` 先 apply,inventory 里的控制已含
`source:"codegraph"`(经 init-resolve 解析的框架路由控制);SRA 透明消费(同 schema),且本变更额外确认
「该控制是否在缺口接口请求路径上」——两路 codegraph 富化叠加,「存在≠有效」边界在 SRA 处再收窄一层。

## Goals / Non-Goals

**Goals:**
- codegraph 在场时:sra-clarify/sra-augment 一次 `codegraph_explore` 取符号源码+调用路径+blast radius,降低
  token/轮次(大仓收益最大);Read 仅作 codegraph 未覆盖项回退。
- **★ a3 call_path 确认信号**:当 `codegraph=on` 且某缺口已有 `recommended_control`(三信号命中),subagent
  用 codegraph 解析「该控制是否接在该缺口接口的请求路径上」→ draft 记 `call_path:{confirmed,path[],source:"codegraph",note}`
  (advisory)。确认 → 强化「复用」措辞;不在路径 → 降级置信 + 注「控制存在但未确认接入此接口」。bounded +
  fail-soft(每 cap a3 上下文内,只对已推荐控制做;(缺口×控制)过多 → top-N + 披露)。
- a2 clarify 次要 advisory:codegraph `callers` 预解析「谁调用该接口」→ 减少部分角色/归属澄清问(优先级低于
  用户断言/代码声明)。
- `sra_manifest.json`/`boundaries[]` 披露 codegraph 用量 + 残留未确认(R5.4 无静默)。
- **R5 全线合规**:不新增 `.py`、不改确定性脚本契约、不新增 hook、双端 MCP 对等。

**Non-Goals:**
- **不改** `prepare_augment.py`/`merge_augment.py`/`merge_memory.py` 契约(R5.3);codegraph 不进确定性层,
  `change_context.json` schema 不变。
- **不**把 codegraph 做成硬依赖(R2 + 「业务项目可能没有」现实);内网无 codegraph 项目零影响。
- **不**用 codegraph 替代维度查缺口或三信号语义匹配——它是「上下文化 + 结构确认」,非「分类/判定」;
  call_path 是 **advisory**,非确定性断言,不覆盖代码/用户证据。
- **不做** a3 批次裁剪 / a4 重构(触 prepare_augment 分批或 a4 契约,R5.3 风险)——拆后续变更。
- **不**把 call_path 做成独立 fan-out stage(对标但**异于** mgh-init 的独立 `init-resolve` stage,见 D3)。
- **不做** codegraph **播种** `business_context.json`(自动产 `interface_authz[]`/`sensitive_fields[]`/`roles[]`
  初始条目,标 `source:"codegraph-suggested"`)——这是真实可优化点(减少跨迭代澄清 + 富化 `/mgh-blst` 消费口),
  但触 `business_context.json` schema + `merge_memory.py` 累积语义 + 记忆优先级模型(代码派生 vs 用户断言),
  属 Tier C,本变更显式**拆后续变更**(对标 mgh-init 把 scout 批次裁剪拆后续)。本变更 a2 clarify 仅**减问**
  (预解析后不发的澄清),不**增写** codegraph 派生记忆条目。
- **不碰** `/mgh-init`/`/mgh-sast`/`/mgh-blst`(本变更 mgh-sra only)。

## Decisions

### D1 — codegraph 进 LLM 层,不进确定性层
codegraph 作为 MCP 工具(a2/a3 subagent 消费)/ `codegraph` CLI(编排器 Bash)介入,**绝不**被任何 `.py`
`import` 或在 `prepare_augment.py` 里 `subprocess` 调。
- **理由**:R2(零运行时依赖)+ R5.3(`prepare_augment.py` 自包含、契约稳定)。把可选外部工具耦合进稳定契约 =
  既有零依赖自检 + 内网零联网分发产品特性被破坏。LLM 层是 codegraph 的天然消费点。`prepare_augment.py` 的
  `_ENDPOINT_RX`/`_ROLE_HAS_RX`/`_SENS_SUBSTR` 抽取器**保持文本**(确定性信号-1 不动),codegraph 只在下游
  LLM 层 refine。
- **替代(否决)**:在 `prepare_augment.py` 加 `subprocess.run(["codegraph",...])` 做 call_path 预解析、写进
  `candidate_controls`——虽 `subprocess` 是 stdlib,但把可选外部二进制编进确定性契约,违反「确定性脚本 =
  黑盒、任意环境可 `py`」语义,且 `candidate_controls` schema 变更触 R5.3。

### D2 — 检测 = `.codegraph/` 目录 + `codegraph` on PATH;三段回退
编排器 step 1(a1)后检测:`test -d <MGH_TARGET>/.codegraph && command -v codegraph`(`<MGH_TARGET>` = a1 stdout
的 `project_root`,编排器已 `export`)。信号 `codegraph=on|off` 透传进 a2/a3 subagent task 输入。subagent 工具
回退序:**① MCP `codegraph_explore`**(主,claude/opencode 双端)→ **② CLI `codegraph explore <sym>`**(Bash,
MCP 不可用时)→ **③ Read/Glob/Grep**(codegraph 未覆盖语言/超 `--big-file-bytes` 文件/索引未含项/`⚠️ pending` banner 文件)。
- **理由**:MCP 是 codegraph 官方推荐面;CLI 兜底保证「有索引但 MCP 未注入 subagent」仍可用;Read 兜底保证不丢覆盖。
- 默认 `auto`;`--no-codegraph` opt-out(对齐既有 `--rules`/`--skip-consistency` 可选 flag 模式)。

### D3 — ★ codegraph 结构证据 inline 在 a3,非独立 stage(异于 mgh-init 的独立 init-resolve)
codegraph 结构证据**嵌入 a3 `sra-augment`**(每 capability 一个隔离上下文)的「Task 2 三信号匹配」之后,作为
**对已 `recommended_control` / 已锚定缺口的附加 advisory 解析**,**非**独立 stage、**非**新 fan-out。**四个 facet**
共用同一 codegraph 机制(`codegraph_explore` 调用路径 / `callers` / `callees` + 框架路由),按**契约最小化**分层:

- **(1) call-path(首要,唯一入 draft 结构字段)**——已推荐控制是否接在缺口接口**请求路径上**(入口 → 受保护资源);
  `callees`/`callers` + 框架路由解析(`@PreAuthorize`/AOP/DI/Feign)。产出 draft `recommended_control.call_path:
  {confirmed, path[], source:"codegraph", note}`。
- **(2) data-flow 可达性**(advisory,改善 `risk`/锚点,非新字段)——缺口敏感字段是否真被该接口流向/返回/落日志
  (`callees`);治 sensitive-data/injection 维度伪缺口(字段不可达 → 该缺口降级/丢弃)。
- **(3) 控制存活 liveness**(advisory,入 `note`)——推荐控制是否有 caller(`callers`/blast radius),还是近乎死代码;
  强化「存在≠有效」。
- **(4) domain-sibling 聚类**(advisory,改善信号-2 `reason`,非新字段)——枚举该接口同业务域兄弟接口及其守卫控制
  (`callers`/`callees` 结构聚类);把信号-2「业务域相似」从文本路径相似升级为结构聚类。

**为何只有 call-path 入结构字段**:facet 2–4 的产物是「改善既有 `evidence`/`risk`/`reason` 质量的 advisory」,无独立
机器可检契约;把它们都结构化会徒增 draft schema + a5 渲染分支,违反 Tier B 契约最小化。call-path 有明确的
`confirmed` 三态(在路径/不在/未判定)+ 可渲染措辞分支,值得结构化。facet 2–4 由 a3 stanza 指引 subagent「用 codegraph
改善这些字段」,不进 schema。

- **理由(为何异于 mgh-init 的独立 init-resolve)**:mgh-init 的 `unresolved[]` 是一个**独立、量大的输入清单**,
  需独立 stage + 单上下文 bounded;而 mgh-sra 的结构证据是「**已有三信号命中的推荐控制 + 已锚定缺口**」的 refinement——
  每 capability 的推荐控制/缺口数天然有界,**天然落在 a3 既有隔离上下文内**,无需独立 stage。不引入新 fan-out →
  **不触发 R5.3b 的 `list_*` 扇出规约** → 零新确定性脚本。这比 mgh-init 的独立 resolve 更轻。
- **bounded + fail-soft**:每缺口只对**已推荐控制**做、且首要做 call-path facet;(缺口×控制×facet)过多超单 a3 上下文
  预算 → subagent 解析**每缺口 top-1 推荐的 call-path facet**、其余 `confirmed:null` + 该 draft 标注「部分未确认」,
  摘要披露,流程不阻断。facet 2–4 在预算紧张时**先于** call-path 被裁剪(它们是 advisory 增强,非首要)。
- **与 a4 的边界**:a3 产结构证据,a4 `sra-consistency` 只**透传 + 归一措辞**(同控制多 cap 引用时 call_path 表述一致),
  **不重算**(a4 不跑 codegraph;结构证据是 a3 的产出,a4 仅跨 cap 去重/消冲突)。

### D4 — codegraph-primary steering(主谓非「可」),规避「subagent 仍 Read」陷阱
codegraph 官方明示:「subagent 若仍自行 Read,codegraph 成纯开销」。故片段措辞用**主谓**(codegraph 在场时
**SHALL 优先** `codegraph_explore`,Read **仅** 作回退),**非**「you may use」。并要求 subagent 在 task 输入见到
`codegraph=on` 信号才启用,避免无索引项目空跑 codegraph 调用。
- **理由**:把 codegraph 的已知失败模式(被绕过)前移成提示词硬约束,而非靠 agent 自觉。

### D5 — 双端对等:claude + opencode 均经 MCP
codegraph 官方 installer 双端注入 MCP server。故 a2/a3 subagent 提示词只需声明「用 MCP `codegraph_explore`」,
双壳(claude `core/prompts/stages/sra-*.md` 由双 shell 共享)镜像同一 `core/prompts/` 片段,**无需**为 opencode
写额外胶水。
- **验证项(Open Question O1)**:确认 opencode subagent 上下文继承 codegraph MCP server;若不继承,fallback 序
  D2②(CLI Bash)兜底(与 mgh-init 变更 O1 同)。

### D6 — 不新增 hook(R5.7 不触发新违例类)
`codegraph explore`(Bash)与 `codegraph_explore`(MCP)**均不**命中 `block_adhoc_scripts` 任一拦截面:非 `py -c`/
`python -c`、非 `Write *.py`、非子树外 `Write/Edit`(MCP 工具名 `mcp__codegraph__*` 根本不走 Bash/Write/Edit
matcher)。故 codegraph 富化**不引入新的 #1 违例类**,R5.7「每命令 #1 违例配 hook」不触发新 hook。既有
`block-adhoc-scripts`(双端)继续治理既有违例,行为不变。

### D7 — 披露 codegraph 用量,不声称全确认
`sra_manifest.json::counts` 增 `call_path_confirmed`(经 codegraph 确认在请求路径上的推荐数)与
`call_path_residual`(未确认/`confirmed:null`/`confirmed:false` 的推荐数);`boundaries[]` 新增披露:(1) codegraph
是否辅助、确认了多少、残留多少(**不声称全确认**);(2) codegraph 自身静态分析上限——反射/DI 容器/运行时分派,
缩小但不归零「误接」,call_path 为 LLM+codegraph advisory,需人工复核。**既有四条诚实边界不动**(语义匹配仍真;
codegraph 是其上的可选结构确认)。

### D8 — 复用 mgh-init 变更的 codegraph-hint.md 片段(跨变更共享资产)
本变更**复用** `core/prompts/fragments/codegraph-hint.md`——该片段是**通用 steering**(用 MCP/CLI、Read 回退、
主谓非「可」),非 init 专属。由姊妹变更 `improve-mgh-init-codegraph-enrichment` 引入。
- **跨变更顺序**:两变更可任意顺序 apply。若 SRA 先 apply 且片段缺失,本变更**新建**之(内容与 init 变更的
  fragment 字节级一致);init 变更后 apply 时幂等跳过(片段已存在)。反之亦然。
- **替代(否决)**:为 SRA 单写 `codegraph-hint-sra.md`——DRY 违例 + 双倍 token + 双份维护。SRA 特有的 call_path
  语义**不进片段**,inline 进 `sra-augment.md` 的 `codegraph=on` stanza(片段管「怎么用 codegraph」,stanza 管
  「SRA 拿 codegraph 做什么」)。

### D9 — call_path 是 LLM advisory,非确定性断言,不改合并契约
call_path 确认是 a3 subagent **读 codegraph 输出后产出的 advisory 字段**,写入 draft 自由 JSON。它:
- **不改** a5 `merge_augment.py` 契约(渲染时 call_path 仅影响推荐措辞/置信标注,如「经 codegraph 确认接入
  此接口请求路径」vs「控制存在但未确认接入」,不增删受管块结构);
- **优先级低于**代码 evidence 与用户 `business_context.json` 断言——call_path 不覆盖前者;
- **非确定性 `--check` 对象**(它是 LLM advisory,无机器可检契约;`merge_augment --check` 仍只校验块外字节不变)。

## Risks / Trade-offs

- **[codegraph 自身静态上限]** 反射/DI 容器/运行时分派,codegraph 亦解不动 → call_path 对这些控制判 `null`/`false`。
  → **缓解**:D7 显式披露 `call_path_residual`;call_path 标 advisory,不优于代码 evidence。
- **[call_path 误判(框架路由解析假阳/假阴)]** codegraph 把某控制判为「在路径上」但运行时其实被绕过(或反之)。
  → **缓解**:call_path 是 advisory,manifest 明示「LLM+codegraph 候选需复核」;不阻断推荐,只调措辞/置信。
- **[data-flow 假阳/假阴(facet 2)]** codegraph 判某敏感字段「被该接口流向」但实际只在不可达分支/被脱敏后才返回
  (假阳),或跨进程/序列化链路 codegraph 看不到(假阴)。 → **缓解**:data-flow 仅 advisory 改善 `risk`,不结构化、
  不阻断;subagent 见 codegraph `⚠️ pending`/跨进程边界时回退保守判定。
- **[domain-sibling 聚类噪声(facet 4)]** 同域兄弟接口判定可能把仅路径前缀相似但语义不同的接口归一类(噪声)。
  → **缓解**:仅作信号-2 `reason` 的 advisory 增强(非新匹配门),不改变三信号命中判据;`reason` 须附业务域理由。
- **[subagent 绕过 codegraph 仍 Read(codegraph 成开销)]** → **缓解**:D4 主谓 steering + task 信号门控;R5.7 评估闭环。
- **[opencode subagent 不继承 MCP]** → **缓解**:D5 fallback D2②(CLI);O1 验证。
- **[(缺口×控制)对过多,单 a3 上下文溢出]** 大变更 + 多控制时 call_path 解析量超预算。 → **缓解**:D3 bounded
  top-N(每缺口 top-1 推荐)+ fail-soft + 披露 `call_path_residual`。
- **[收益随仓规模变化]** codegraph benchmark 示「大仓显著、小仓噪声」。 → **缓解**:`auto` 检测 + `--no-codegraph`
  opt-out;大仓(正是 mgh-sra 痛点)收益最大,可接受。
- **[跨变更片段冲突]** 两变更都「新建」同一片段,内容须字节一致。 → **缓解**:D8 规定内容一致 + 幂等;
  `tests/test_distributed_md_purity.py` 覆盖片段存在性(承 R5.8);apply 顺序无关。
- **[新增 a3 解析增运行时成本]** call_path 多 codegraph 调用。 → **缓解**:off 时零成本;on 时仅对已推荐控制
  (bounded),且外科式上下文本身已省 Read。

## Migration Plan

- **纯 additive,无迁移**:`--no-codegraph`(默认 `auto` 检测)完整保留现状;codegraph 缺席项目行为零变化;
  `change_context.json`/`business_context.json` schema 不变;draft 增 optional `call_path` 字段,既有消费者按结构
  字段读,缺失即 `null` 不破;`sra_manifest.json` 增计数字段(既有消费者忽略未知字段)。
- **回退**:任何子步骤失败/超预算 → 该 step fail-soft 跳过 + 披露;`--no-codegraph` 一键回到引入前行为。
- **版本**:`mgh-sra.md` 两壳 + 受影响 `core/prompts/stages/sra-*.md` bump 版本号(承 R5.8)。

## Open Questions

- **O1**:opencode subagent 上下文是否继承 codegraph MCP server?(影响 D5 主路径;apply 阶段实测验证,不行则
  fallback CLI。与 mgh-init 变更 O1 同。)
- **O2**:结构证据的 bounded 预算怎么分?v1 取**每缺口 top-1 推荐控制、首要做 call-path facet**;facet 2–4(data-flow/
  liveness/domain-sibling)在预算允许时做、紧张时先于 call-path 被裁剪。若实测 a3 上下文仍溢出,后续可拆独立
  `sra-resolve` fan-out stage(届时需 `list_resolve_jobs.py`,触 R5.3b,另起变更)。
- **O3**:call_path 的 `path[]` 粒度(全调用链 vs 仅「控制↔接口」直接边)?v1 取**控制到接口请求入口的最短路径**
  (足够回答「接没接上」,省 token);apply 阶段定。
- **O4**:a2 clarify 用 codegraph `callers` 减问,「谁调用」是否真能映射到「角色」?(框架内部 caller ≠ 业务角色。)
  v1 取保守:仅当 caller 能明确映射到记忆 `roles[]` 已知角色时减问,否则仍发澄清。apply 阶段验证噪声。
