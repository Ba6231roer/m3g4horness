# mgh-* 提示词长度分析报告

> 面向维护者;目的:(a) 修正 R5.6 的预算模型,(b) 拆分各超长提示词的修复任务。
> 测量源:`py tools/measure_prompts.py`,数据采集日期 2026-08-10。所有行号引用 `releases/claude-code/` 与 `releases/opencode/`(镜像)。
>
> **2026-08-12 勘误增补**:见下方 **§9「分发足迹 ≠ 运行时叠加占用」模型勘误**。apply `harden-mgh-init-shell-budget`
> 时发现「`shell + fragments` 求和 ≤ 8,000」与 opencode 运行时模型矛盾(数学不可达),已据 opencode 源码核实重接地;
> 完整源码引用与机制说明见 [`docs/opencode-context-mechanics.md`](opencode-context-mechanics.md)。

---

## 1. TL;DR

**R5.6 同时设了「500 行」和「5,000 token」两个上限,但只有 TOKEN 是约束性的——这些 zh-dense 提示词的承载比是 ~25–35 tok/line,5K token 在 ~145–200 行就到顶,「500 行」上限松了 2.5–3.5 倍,直接放任作者越过真实的 5K TOKEN 上限。** 实测 5 个编排器壳中 **3 个已经突破自身规约的 5K 上限**:mgh-init 9,361(claude)/ 9,224(opencode)、mgh-sra 5,460 / 5,101、mgh-srr 5,148(仅 claude;opencode 4,885 勉强在线下);mgh-sast(4,543 / 4,421)与 mgh-ut-init(4,807 / 4,936)在线下但余量极薄。子 agent 侧有两个硬突破:sast-deepdive s4 = 6,989、sra-augment a3 = 5,274(off)/ 6,288(on,后者同时被 mgh-srr 继承)。**第二重问题(发起本分析的原始关切)**:壳也是关键一次性动作(`.active` 哨兵写入)被深埋的地方——它在 opencode 上是 hook 激活的唯一可靠路径,弱/短上下文模型一旦漏读,守护静默失效而流水线仍跑完(无错误反馈)。**裁剪有双重收益**:既给多轮 fan-out 让压缩余量,又提升弱模型对关键动作的执行忠实度。

---

## 2. 150K 预算推导(opencode 源码核实 + 外部权威;撤回"150K 算出 5000"的错误推导)

> **方法学纠错(本节核心)**:此前一版曾写"150K 上下文算出壳 ≤5,000 tok"——**这是假精度,撤回**。本节据 opencode 源码核实(`C:\DEV\opencode`)与外部权威(LLM "lost-in-the-middle" 论文 + 通用 system-prompt 预算指南)重推。结论:5,000 仍是硬上限,但**它的根据换了**(见 §2.4),不再是上下文算术。

### 2.1 opencode 平台事实(源码核实,非假设)

| 事实 | 源码 | 对预算的影响 |
|---|---|---|
| **命令/agent 体无平台尺寸上限** | `packages/core/src/v1/config/command.ts`、`agent.ts`:`template`/`prompt` 为裸 `Schema.String`,loader 仅 `trim()` 无截断 | **无 Codex 式 8KB 硬顶** → R5.6 旧"≤5000(Codex 8KB)"的根据失效 |
| **命令体 = 触发消息(一次性 USER 历史),非每轮 system** | `session/prompt.ts:1432-1451`(`templateParts`→user part);system 块每步重建自 `env+instructions+mcp+skills`(`prompt.ts:1264-1269`) | **压缩阈值不绑定壳尺寸**:壳进历史一次、不随轮次累乘 |
| **AGENTS.md 每步重读入 system** | `session/instruction.ts:60-68,110-153`(walk `findUp AGENTS/CLAUDE/CONTEXT.md`)+ `prompt.ts:1260,1266` | 目标项目 AGENTS 体积 = **外部不可控常驻开销**(mgh-* 不预算) |
| **子 agent 继承 AGENTS,且 agent.prompt 替换 per-model base** | `tool/task.ts:200-214`(child session 走同一 loop → 重读 AGENTS);`session/llm/request.ts:60`(`.prompt` replaces base) | 子 agent 有效 system = **agent def stage 提示词**(替换 ~8–15K base)+ 继承的 AGENTS.md |
| **opencode 自带 auto-compact 阈值 < 模型窗口** | `session/overflow.ts:8-34`:`tokens.total ≥ model.limit.input − reserved`,`reserved = min(20000, maxOutput)` | 150K 模型 → **~130K 即压缩**(非 150K),由**累积工具结果 + AGENTS** 驱动,非壳尺寸 |
| **跨文件引用仅 `@<path>`/`!cmd` 机械内联;其余模型解释** | `config/markdown.ts:5-14`、`prompt.ts:157-191` | "REQUIRED SUB-SKILL: Use X" = lazy `Read`(模型解释),确认 fragment 模型成立 |

### 2.2 外部权威(支撑 5000 的真正根据)

| 来源 | 要点 | 落到 mgh-* |
|---|---|---|
| **Lost in the Middle**(Liu et al. 2023, cited 5,798+,arXiv:2307.03172) | Transformer 对长上下文呈 **U 形注意力**:首/尾强、中段衰减。关键信息埋在**中间**显著掉准——**所有 transformer 模型固有,非"弱模型"专属** | **这是发起本分析的原始关切的权威根据**:`.active` 哨兵写入埋在 268 行壳的 `:66`(中段)= 注意力衰减区 = skip 风险。**壳变短 + 关键动作前置/突出 = 直接治本** |
| **system-prompt 预算 = 窗口 5–10%**(多源:Medium/Data-Science-Collective;myengineeringpath 实测 128K 窗给 system ~2–5K) | system 块建议 ≤ 窗口 5–10% | opencode 下 **system 块 = base 提示词(~8–15K,平台税)+ 目标 AGENTS(外部)+ skills**;mgh-* 壳**不在 system 块**(是 USER 消息)→ 5–10% 规则**直接约束子 agent 的 stage 提示词**(它替换 base、与继承 AGENTS 共占 system 预算)→ **子 agent 有效系统应保守 ≤5K** |
| **Anthropic 原则**("smallest high-signal token set maximizing outcome") | 高信号优先,非盲目最小化 | 支撑**保真度优先**裁剪法(删冗余/重复/dev-meta,保承重流程/防线) |

### 2.3 拆分:EXTERNAL(不可控)/ DISTRIBUTED(可控)

| 类别 | 内容 | 是否 R5.6 预算对象 |
|---|---|---|
| **EXTERNAL / 不可控**(只占窗) | opencode per-model base 提示词 ~8–15K;平台工具定义;**目标项目自有的 AGENTS.md/CLAUDE.md(每步重读,体积由目标定,未知)** | ❌ 不是 |
| **DISTRIBUTED / 可控**(R5.6 预算对象,install.sh 分发) | 编排器 = 壳(触发消息)+ 壳经「REQUIRED SUB-SKILL」懒加载的 fragments;子 agent = 薄 agent def + stage(替换 base、与继承 AGENTS 共占 system 预算)+ stage 加载的 fragments | ✅ 是 |

**显式澄清**:本研发仓的 AGENTS.md(5,833 tok)/ CLAUDE.md(~370 tok)是**研发态专属、绝不分发**(R5.10;install.sh 不携带)。研发仓内测试时它们被宿主额外加载 = 研发态附加成本,**绝不滚入**目标产品的 mgh-* 预算。

### 2.4 硬上限的真正根据(撤回"150K 算术")

**5,000 tok 仍是硬上限,但根据换了**——四股独立压力共同落在 ~5K,**其中任何一个都不是"150K 算出来"**:

| 压力 | 来源 | 对壳/子 agent 的约束 |
|---|---|---|
| **lost-in-the-middle 注意力衰减** | 外部权威(§2.2) | 壳越长、关键动作越易落中段衰减区 → 越短+越突出越好(**无干净数**,但 ~2× 于结构良好壳即冗余信号) |
| **system 块 5–10% 预算** | 外部权威(§2.2) | **直接约束子 agent**(stage 替换 base、与继承 AGENTS 共占)→ 子 agent 有效系统保守 ≤5K |
| **经验:结构良好的 mgh-* 壳自然落 ~4.5–5K** | 本报告实测:mgh-sast 4,543 / mgh-ut-init 4,807–4,936 | 编排器壳 ≈ 5K 是**经验承载重量**(parse-args + flow 骨架 + SUB-SKILL 指针 + 表 + 披露,细节已分片) |
| **防松散迭代再膨胀(回归)** | 工程需要 | 无硬上限 = 几个迭代后又超回本次优化前(发起本分析的目的)→ **硬上限本身就是交付物** |

**→ 5,000 tok(硬上限)** = 这四股的**收敛点**,非上下文算术产物。mgh-init 9,361 ≈ 该量的 **2×** = 冗余信号明确(非"刚好超标")。**子 agent 有效系统同样 ≤5K**(第二股直接约束)。

### 2.5 行 ↔ token 比(纠正 500 行误判,保留)

| 事实 | 数值 |
|---|---|
| zh-dense 壳的承载比 | ~25–35 tok/line |
| 5,000 tok 对应行数 | ~**145–200 行** |
| R5.6「500 行」上限的松倍 | ~2.5–3.5x 过松 |
| 结论 | **TOKEN 是约束性维度**;500 行降为 token-derived 的**行数指引**(非硬上限) |

---

## 3. 各命令实测

### 3.1 mgh-init

**编排器**

| 壳 | tok | 行 | 加载 fragment | 分发足迹 | 突破? |
|---|---|---|---|---|---|
| claude `mgh-init.md` | 9,361 | 268 | orchestrator-discipline.md(2,466) | 11,827 | ✅ 壳突破 5K(+4,361)、足迹突破 8K(+3,827) |
| opencode `mgh-init.md` | 9,224 | 259 | 同上 | 11,690 | ✅ 壳突破(+4,224)、足迹突破 |

> **落地后实测(change `harden-mgh-init-shell-budget`,§7 任务 1 已完成)**:壳瘦身达标——claude
> `mgh-init.md` **2,916 mid / 91 行**、opencode **2,853 mid / 84 行**(均 ≤ 5,000 真约束)。编排流 step 0–8 细节
> 抽进新共享 fragment `core/prompts/fragments/init-stage-flow.md`(**4,769 mid / 130 行**,两壳经
> `REQUIRED SUB-SKILL: Use init-stage-flow` 加载同一文件,零 drift),壳保留 parse-args + Stage→组件表(折叠)+ Resume·cache
> + Output + Always disclose(精简)+ Bash 目录块删除。**预算模型重接地(见 D6)**:`measure_prompts.py` 是磁盘文件
> 大小估算器(各文件 mid 求和),非运行时足迹模型——opencode 下壳与各 fragment 均为单次 lazy Read 的 USER 历史项(非每轮 system 税),
> 故「shell+fragments 求和」反真实;真约束 = 壳 ≤5K(primacy 区 + 防回归)。磁盘防漂移上限(per-shell 壳+两 fragment
> ≈ 2,916+4,769+2,466 = 10,151 / 2,853+4,769+2,466 = 10,088)略超 ~10,000 护栏(init-stage-flow verbatim 搬移合法),
> 标注为磁盘防漂移、**NEVER** 运行时叠加占用。源码根据见 `docs/opencode-context-mechanics.md`。


**子 agent**(均不突破 5K)

| role | def | stage | fragments | 有效系统 | 突破? |
|---|---|---|---|---|---|
| init-induct(T1) | 621 | 1,997 | codegraph-hint 1,014(if on) | 3,632 | ❌ |
| init-resolve(codegraph-gated) | 762 | 2,107 | codegraph-hint 1,014(always) | 3,883 | ❌ |
| **init-rulewriter(T3)** | 630 | 2,094 | rules-format-claude 708 / **opencode 1,316** | 3,432 / **4,040**(worst) | ❌ 但最贴近 |
| init-scout(per-batch) | 652 | 2,359 | codegraph-hint 1,014(if on) | 4,025(2nd worst) | ❌ |
| init-scout-merge | 352 | 1,183 | — | 1,535 | ❌ |
| init-scout-audit(opt) | 385 | 1,023 | — | 1,408 | ❌ |
| init-survey(opt) | 317 | 1,028 | exclusion-rules 612 + codegraph-hint 1,014(if on) | 2,971 | ❌ |
| init-synthesis(T2) | 351 | 1,265 | — | 1,616 | ❌ |
| init-rules-consistency(T4 opt) | 378 | 930 | — | 1,308 | ❌ |

### 3.2 mgh-sast

**编排器**(不直接加载 fragment 进自身上下文)

| 壳 | tok | 行 | 分发足迹 | 突破? |
|---|---|---|---|---|
| claude `mgh-sast.md` | 4,543 | 191 | 4,543(余量 457) | ❌ 在线下 |
| opencode `mgh-sast.md` | 4,421 | 177 | 4,421(余量 579) | ❌ 在线下 |
| 条件:--controls | +controls-context.md(930)inlined 进 s2/s3/s4/s6/s8 的 TASK msg(非编排器上下文) | → 5,473 / 5,351 | 仍 < 8K |

**子 agent**

| role | def | stage | fragments | 有效系统 | 突破? |
|---|---|---|---|---|---|
| sast-survey(s1) | 408 | 574 | — | 982 | ❌ |
| sast-threat-model(s2) | 329 | 926 | s2-baselines 579 + stride-by-kind 120 | 1,954 | ❌ |
| sast-decompose(s3) | 356 | 635 | (specialist-hints 仅按名引用) | 991 | ❌ |
| **sast-deepdive(s4)** | 799 | 2,533 | **specialist-hints.md 全量 3,657** | **6,989** | ✅ **突破 +1,989** |
| sast-verify(s6) | 499 | 972 | — | 1,471 | ❌ |
| sast-chain(s8) | 324 | 671 | — | 995 | ❌ |
| sast-triage | 332 | 0 | (skill on-demand) | ~332 | ❌ |
| sast-scope-resolver | 334 | 0 | (自包含) | 334 | ❌ |

注:s4-system.md(2,533)是 R1 字节稳定 verbatim 移植,**非裁剪对象**;杠杆是 specialist-hints 切分,不是改移植文。

### 3.3 mgh-sra

**编排器**(壳不直接加载 fragment)

| 壳 | tok | 行 | 分发足迹 | 突破? |
|---|---|---|---|---|
| claude `mgh-sra.md` | 5,460 | — | 5,460 | ✅ 壳突破 +460 |
| opencode `mgh-sra.md` | 5,101 | — | 5,101 | ❌ 在线下(余量 899) |

**子 agent**

| role | def | stage | fragments | 有效系统 | 突破? |
|---|---|---|---|---|---|
| **sra-augment(a3)** | 807 | 3,227 | security-dimensions 1,240(always)+ codegraph-hint 1,014(if on) | **5,274 off / 6,288 on** | ✅ **双模均突破** |
| sra-clarify(a2) | 649 | 1,804 | security-dimensions 1,240 + codegraph-hint 1,014(if on) | 3,693 off / 4,707 on | ❌ |
| sra-consistency(a4) | 453 | 896 | — | 1,349 | ❌ |

注:controls-context.md(930)/ severity-guidance.md(403)是 mgh-sast 专用,**不属于 sra 足迹**(任务提示列错,实测零引用)。

### 3.4 mgh-srr

**编排器**(壳不直接加载 fragment;复用 sra 引擎,无新 fragment)

| 壳 | tok | 行 | 分发足迹 | 突破? |
|---|---|---|---|---|
| claude `mgh-srr.md` | 5,148 | 208 | 5,148 | ✅ 壳突破 +148 |
| opencode `mgh-srr.md` | 4,885 | — | 4,885 | ❌ 在线下(余量 115,极薄) |

**子 agent**(全部复用 sra,足迹中性;继承 sra-augment 的突破)

| role | 有效系统 | 突破? |
|---|---|---|
| sra-clarify(复用) | 3,693 off / 4,707 on | ❌ |
| **sra-augment(复用)** | **5,274 off / 6,288 on** | ✅ **继承自 /mgh-sra** |
| sra-consistency(复用) | 1,349 | ❌ |

mgh-srr 新增的真正适配器内容仅 ~2,500–3,000 tok(r1 ingest / r2 render / opencode 回填 / SRR 边界);其余 ~2,000 tok 是重述已存在于共享 sra agent+stage 的纪律/fan-out/codegraph。

### 3.5 mgh-ut-init

**编排器**

| 壳 | tok | 行 | 加载 fragment | 分发足迹 | 突破? |
|---|---|---|---|---|---|
| claude `mgh-ut-init.md` | 4,807 | — | orchestrator-discipline(2,466) | 7,273(余量 727) | ❌ 在线下 |
| opencode `mgh-ut-init.md` | 4,936 | — | 同上 | 7,402(余量 598,壳余量仅 64) | ❌ 但极薄 |

**子 agent**(全部 < 50% 预算,最干净的同族)

| role | def | stage | 有效系统 |
|---|---|---|---|
| ut-extract | 544 | 1,605 | 2,149 |
| ut-rulewriter | 516 | 1,912 | 2,428 |
| ut-synthesize | 436 | 1,402 | 1,838 |
| ut-rules-consistency | 415 | 915 | 1,330 |

ut-init 是后写的、按 5K 上限设计;**作为 mgh-blst 的正面参考范式**。

---

## ⚠ 裁剪前提:保真度优先(全局通用,适用于 §4 全部裁剪建议与 §7 全部任务)

> **历史提示词是多轮迭代沉淀的产物**——其中大量看似冗余的「NEVER …」mantra、反例、边界披露
> 与重复配方,实为针对**真实失败形状**(承 R5.2「理由〔…〕」)的承重防御与已修 bug 的防线,
> **不是无意义的重复**。
>
> 执行 §4 任何裁剪/合并、或 §7 任一任务时,**MUST 先验真被删内容的来由**,确认它不是:
> 1. **关键处理流程节点**——某 stage 的 I/O 契约、fan-out 路径确定性、`--check` 闸门、
>    续点/resume 语义。这类 **NEVER 删,只能迁移**(fragment 化 / 抽共享),不消除。
> 2. **问题/失败的规避或修复方式**——如 NTFS `::` 文件名 sanitize、盘符根漂移、UTF-8 BOM 剥离、
>    scout-incomplete-gate、codegraph 不命中守护的边界解释。删前**先查** git blame / commit message /
>    `docs/review-*.md`,确认该防线已在别处覆盖;否则**保留**。
>
> **节省 token 是目标,保真度优先**:宁可保留少量「看似冗余但承重」的内容,也不为省 token 丢掉
> 一道曾修过的防线。每条 §4 建议的「节省」是**上限**;落地前由实现者逐条标注
> 「承重→保留 / 已他处覆盖→删 / 可迁移→抽取」。R1(上游引用非必要不改)对移植提示词同样适用——
> 切勿为达 5K 而改 vvah verbatim 移植正文(如 s4-system.md)。

---

## 4. 膨胀点与裁剪建议

### 4.1 R5.10 dev-meta 删除(免费必做,purity + 清晰度)

| 位置 | 问题 | 处理 | 节省 |
|---|---|---|---|
| `mgh-init.md:10` / opencode:9 | 「本仓」= 研发仓措辞,在分发提示词中歧义(目标 agent 可能误读为 m3g4horness 研发仓) | 改为「目标项目」 | ~5 |
| `mgh-sra.md:210` / opencode:198 | 「承 mgh-init」= R5.10 第 7 类 dev-meta(承重教训标记,`tools/check_distributed_purity.py` 已标记「承」) | 删前缀;保留 CVE-2025-41248(受保护操作性归因) | ~12 |

### 4.2 mgh-init 编排器壳(最大单项)

| 位置 | 问题 | 建议 | 节省 |
|---|---|---|---|
| `mgh-init.md:194-229`(opencode:194-228) | 「Deterministic invocation (Bash)」36 行扁平目录,重复编排流步骤 2/3b/4/4b/5/6/6b 已内联的全 flag 命令 | 删整块;仅保留 2 个未内联逃生口(大文件切片 form line 218、resume --invalidate-stale 配方 210-211)迁回原生步骤 | ~900 |
| `mgh-init.md:53-165`(结构性) | 即便做完上述所有具体裁剪(~2,240 tok → ~7,100 tok 壳),**无法不结构性动刀达到 5K**:编排流本身 110 行 / ~4,500 tok | 抽每步子细节进新 fragment `init-stage-flow.md`(按需加载,镜像 orchestrator-discipline);壳保留 parse-args + SUB-SKILL 指令 + 表 + 披露 → ~4,200 tok + 1 fragment。**达到 5K 的唯一路径** | ~3,500 |
| `mgh-init.md:253-268`(opencode:245-260) | 「Always disclose」16 条,大量重述 flow step 8 已写入 report.md/init_manifest.json::boundaries[] 的内容(dotfiles/tests/budget/timeout) | 压缩为 5 条规范要点(LLM 诱发/人工复核、存在≠有效 CVE-2025-41248、call-graph 文本/AST、中文输出、scout/非整仓);细节迁「boundaries[] 已携带,仅 report.md 复述」一行 | ~500 |
| `mgh-init.md:167-191`(opencode:166-191) | 「Stage → 组件」25 行表,Asset 列重述每阶段 `core/scripts/<x>.py` 路径(已在 flow 内联);(opt)/fan-out 语义也被 flow 重述 | 折叠为紧凑 2 列「script inventory | subagent inventory」(仅名,无路径——绝对路径由 list_steps.py 运行时给);保留非平凡复用注(expand_scope/form_clusters)为 2 行脚注 | ~400 |
| `mgh-init.md:10-18`(opencode:9-19) | hook 机制三处重述(此处、step 0 的 57-69、orchestrator-discipline.md:16-18,43) | 顶部折为 2 行指针(激活 = env 或 哨兵;哨兵写法见 step 0、纪律见 fragment);保留 opt-out flag 提及 | ~220 |
| `mgh-init.md:79,82,96,113,114,121,123,142` | 「NEVER py -c 自算」/「NEVER Read 整份大 JSON」mantra 重述 8+ 次 | 编排流顶部一次性注记;删逐步 echo;仅保留防具体失败形状处(line 128 scout-incomplete-gate) | ~140 |
| `mgh-init.md:45-51`(opencode:45-51) | 「REQUIRED SUB-SKILL」加载 2,466-tok fragment 后,line 51 重述「stdout 直消费」(已在 fragment:20-23) | 保留 line 47 SUB-SKILL 指令 + line 49 的 init 专项指针;删 line 51 | ~80 |

### 4.3 mgh-sast

| 位置 | 问题 | 建议 | 节省 |
|---|---|---|---|
| `core/prompts/lenses/specialist-hints.md:10-259`(全文件 3,657 tok) | sast-deepdive 全量 Read 仅取 1 个 specialist section(驱动 s4 = 6,989 突破);文件按 6 个 `###` 干净分段(crypto ~320 / logic-bug ~470 / access-control ~600 / deserialization ~420 / batch-etl ~540 / **iac ~1,230 独占 1/3**) | 切为 `lenses/<specialist>.md`(每文件 320–1,230);agent def 已收 chunk 的 `specialist` 字段——指示仅 Read `lenses/<specialist>.md`(或编排器传绝对路径,镜像 chunk_sources)。**保留溯源头**(R1)。更新 stage-map + agent:17 | ~2,900 |
| `mgh-sast.md:142 + :182`(opencode:139 + :170) | per-call timeout 纪律两处重述(「Deterministic invocation」前言段 + 「Always disclose」) | 留「Deterministic invocation」1 行(canonical);「Always disclose」仅留限制披露 | ~130 |
| `mgh-sast.md:36`(opencode:34) | --max-unit-bytes 等 3 个 flag 的 ~210 tok 括号注,重述默认值/溢出/shrunk 行为(脚本已强制 + run_manifest 披露);违反 R5.1(脚本 --help 即契约面) | 压一行:默认与溢出披露见各脚本 --help + run_manifest.json::boundaries[] | ~140 |
| `mgh-sast.md:48-53`(opencode:46-51) | implementation-intention 5 bullets 每条重述 NEVER 链(py-c / 裸名 / 相对路径) | 一个 lead-in 统一禁令,再列合法出口;**保留所有具体失败形状示例**(多层 install 裸名、D 盘根漂移——承重) | ~120 |
| sast-deepdive agent:44-52 + 5 个 sast agent 的 Hard constraints | ~150–180 tok ×6 近重复(可选) | 抽 `fragments/subagent-discipline.md`(~150),各 agent 引用;或压 2 行(工具 frontmatter 已禁 .py Write) | ~100 |

### 4.4 mgh-sra

| 位置 | 问题 | 建议 | 节省 |
|---|---|---|---|
| `sra-augment.md:71-103`(Task 3 4-facet codegraph 块) | ~33 行 / ~1,000 tok,fire 仅当 codegraph=on 且已三信号匹配;stage 自承「4 facet 共用同一机制」;且 on-path 上叠加 codegraph-hint fragment(1,014)→ ~2,000 tok codegraph 叠栈;off-path 仍带在静态系统提示(致 5,274 突破) | 抽进 gated fragment `fragments/codegraph-structural-evidence.md`(仅 codegraph=on 时 Read);4 facet 压为「共机制陈述 + 紧凑表(facet | 解什么 | 落哪:call_path 字段 vs risk/note/reason)」 | ~700 |
| `mgh-sra.md:201-221`(opencode:190-209) | 「Always disclose」~21 行 / ~730 tok 重述 step 7(claude:137-149)的 boundaries[] 构造机制(focus 212-213、sensitive-catalog 214-217、codegraph advisory 219-221) | step 7 保留构造法;disclose 仅留用户面指针(LLM 候选、覆盖依赖声明、存在≠有效 CVE-2025-41248、focus 收窄、catalog 非穷尽、codegraph advisory)→ ~8 行 | ~300 |
| `sra-augment` agent:27-36 | codegraph enrichment + call_path advisory recap(~10 行)重复 stage Task 3 + codegraph-hint fragment | 抽 agent def 为「READ it and follow」指针 + 加载前可能违反的 NEVER(Write .py、draft_path 逐字绝对、不碰 specs/tasks);删 codegraph/call_path recap | ~250 |
| `sra-augment.md:35-46` | sensitive-catalog overlay 重述多遍(per-item check、catalog_key、advisory、「无控制仍发 gap」、focus 叠加、null=6-facet) | 压 ~5 行;「无控制仍发 gap」「叠加 focus」各仅留 1 次(也见 Task 2 line 58-59 与 security-dimensions fragment) | ~150 |
| `mgh-sra.md:96-102`(opencode:92-98) | codegraph 检测块 7 行解释「为何不命中 block-adhoc-scripts 拦截面」= 实现辩护(R5.x 味) | 压:检测一行 + 信号逐字透传 a2/a3 + 「codegraph 是宿主 MCP/CLI,无 pip」;删「为何不命中守护」辩护 | ~120 |
| `mgh-sra.md:62-68`(opencode:59-65) | implementation-intention(4 bullets)与「fan-out 刚性三元组」(~3 行)编码同一 fan-out 路径纪律 | 合并刚性三元组进 impl-intention 的 fan-out bullet;`[输入产物::字段]→script/subagent→[输出产物::字段]` 记法仅 1 次 | ~100 |
| `sra-augment.md:142-149` | 「输出纯净性」8 行重推人读 vs 结构字段(与 schema 105-122 部分重复) | 压 3 行:规则 + 1 示例;让 JSON schema 承载字段枚举 | ~100 |
| `mgh-sra.md:47-51`(opencode:44-47) | 3 个 budget flag 长 zh 句(默认值/P0 caveat/oversize 配方) | 折 3 行表(flag | default | semantics);P0 caveat 迁「Always disclose」(已出现) | ~90 |
| `sra-clarify` agent:26-31 | codegraph callers recap(~6 行)重复 stage 38-56 | 抽 1 行「codegraph rules per stage;只减问、MUST NOT 增写 memory」 | ~180 |
| `sra-clarify.md:68-73` | P0 软边界配方 6 行(唯一定义处,但与壳 budget 块 + disclose 措辞重叠) | 保留(行为唯一定义)压 3 行 | ~60 |
| `mgh-sra.md:159,162`(opencode:152,155) | stage→component map 列 fragment 为 Asset(文档化子 agent 加载内容,有诱导编排器提前 Read 的风险) | Asset 列仅指 stage prompt 路径;stage 自声明加载哪些 fragment | ~40 |

### 4.5 mgh-srr(壳自身;子 agent 见 §4.4 sra 共享)

| 位置 | 问题 | 建议 | 节省 |
|---|---|---|---|
| `mgh-srr.md:61-76`(opencode:59-74) | 「Orchestrator discipline(铁律)」~16 行 / ~650 tok,重述硬边界 + fan-out 刚性三元组(也在每个 sra-* agent def + 共享 orchestrator-discipline.md);路径透传配方已在 flow step 1/4 内联 | NEVER-list 压 3 紧凑 bullet(不 Write .py / 不 py -c / 不 Read 叶 .py);删刚性三元组表述;留 --check 边界行 | ~300 |
| `mgh-srr.md:18-24`(opencode:16-22) | 7 行 blockquote 重述 hook 激活原理(env-OR-哨兵、opencode 插件 env 继承边界、runtime-enforcement.md 指针)every run;机制原理已在该契约文档 | 压 2 行:step 0 写 / step 1 重写 / step 7 rm + 激活语义指针;删 opencode-inheritance 解释 | ~200 |
| `mgh-srr.md:37-44`(opencode:35-42) | --focus / --sensitive-catalog 各重述同一验证契约(r1 parse + closed-set + 同 sra shape + 复用 a2/a3 零新增提示词),「零新增/复用」出现 3x | 共享契约列 flag 后陈述 1 次;per-flag 仅留 shape-specific 细节 | ~120 |
| `mgh-srr.md:100-104`(opencode:97-101) | codegraph 检测块解释「宿主 MCP/CLI,no pip,no hook change」= 安装时背景,非每轮操作 | 压 2 行:if-test + 信号透传;删 no-pip/no-hook-change 辩护(归安装文档) | ~120 |
| `mgh-srr.md:192-193`(opencode:184-185) | Always-disclose 重释 budget 机制(已在 Parse args:54-57)与 shell-timeout(已在 :161) | 压 1 行:budgets 按 --max-*-bytes;over-budget 在 srr_manifest.json::boundaries[] + report;P0 soft on render aggregate | ~120 |

### 4.6 mgh-ut-init(余量薄,主要修 skip-risk)

| 位置 | 问题 | 建议 | 节省 |
|---|---|---|---|
| opencode `mgh-ut-init.md:170`(claude:166) | 「宿主 shell 超时」披露第三处重述 opencode env 继承边界(已在壳 hook 块 17-19 + orchestrator-discipline.md:43) | 压 1 行:env 须启动前就绪 + per-call timeout 即时杠杆(见 fragment) | ~120 |
| opencode `mgh-ut-init.md:17-19`(claude ~17-18) | 磁盘哨兵存在理由 3 行(opencode 插件不继承 mid-session env)= 可靠性理论,非编排器动作(opencode 壳比 claude 重 129 tok 主因) | 压 1 行:激活 = env 或 磁盘哨兵(哨兵兜底 opencode env 边界);删 runtime-enforcement.md 指针(hook 作者用,非编排器) | ~110 |
| opencode `mgh-ut-init.md:9-16`(claude:10-17) | hook intro 混运行时事实与安装时信息;`install.sh --no-enforce-hook`(line 16)是安装时——编排器从不调用;MGH_TARGET 此处与 step 0(64-65)双述 | 删 opt-out flag 句(归安装文档);hook intro 的 MGH_TARGET 细节换指针,step 0 为唯一权威配方 | ~90 |
| `mgh-ut-init.md:127-141`(opencode)/ :124-137(claude) | 「Deterministic invocation (Bash)」~14 行部分重述 flow 内联;两长 list_test_groups.py 例(全 flag)重复 step 2/4 | 保留作 CLI 契约镜像(R5.1),但两长例压为规范形式 + `--offset/--limit/--max-unit-bytes/--orch-budget-bytes` 占位符注 1 次 | ~80 |

---

## 5. Fragment 加载图(复合开销视图)

| Fragment | tok | 编排器加载? | 子 agent 加载 | 跨命令共享? |
|---|---|---|---|---|
| **orchestrator-discipline.md** | 2,466 | mgh-init / mgh-ut-init(经 REQUIRED SUB-SKILL);mgh-sra / mgh-srr **不直接加载**(壳内自带纪律段) | — | ✅ init / ut-init(sra/srr 壳内文本式重述,未抽 fragment) |
| **codegraph-hint.md** | 1,014 | ❌ | init-survey/scout/induct/resolve(if on)、sra-clarify/augment(if on)、sast 各 stage | ✅ init / sra / sast |
| **security-dimensions.md** | 1,240 | ❌ | sra-clarify(always)、sra-augment(always) | ✅ sra(及 srr 复用) |
| **specialist-hints.md** | 3,657 | ❌ | **sast-deepdive(s4)全量 Read**(USER prompt)——唯一突破驱动 | sast 专用 |
| rules-format-opencode.md | 1,316 | ❌ | init-rulewriter(opencode worst path) | init 专用 |
| rules-format-claude.md | 708 | ❌ | init-rulewriter(claude) | init 专用 |
| exclusion-rules.md | 612 | ❌ | init-survey(always) | init 专用 |
| controls-context.md | 930 | ❌(仅 --controls 时 inlined 进 s2/s3/s4/s6/s8 TASK msg) | — | sast 专用 |
| severity-guidance.md | 403 | ❌ | sast severity rating | sast 专用 |
| s2-baselines.md / s2-stride-by-kind.md | 579 / 120 | ❌ | sast-threat-model(s2) | sast 专用 |

**预算编制双重计数风险(警示)**:
- codegraph-hint.md(1,014)在 init / sra / sast 三命令分别计费——**不要在跨命令汇总时把它当共享节余**(它是 per-subagent-invocation 的)。
- security-dimensions.md(1,240)被 sra-clarify 与 sra-augment 各加载一次——**同一物理文件、单点真相、零物理重复**(复用范式正确);token 节余机会在 stage 内联的 codegraph Task-3 与 fragment 的去重(见 §4.4)。
- specialist-hints.md 是**单点最大可切分 fragment**(3,657 tok 干净按 6 个 `###` 分段),切分收益最大(2,900 tok)且仅影响 sast。

**复用机会**:orchestrator-discipline 已是共享;建议把 sra-augment codegraph Task-3 抽为 gated fragment 后,**codegraph-hint + 新 codegraph-structural-evidence** 形成 codegraph 主题双 fragment(codegraph=on 才加载),off-path(默认,无 `.codegraph/`)的 sra-augment 直降 ~1,200 tok 进 5K 线下。

---

## 6. R5.6 修正建议(已落地到 AGENTS.md)

### 6.1 已修正内容(AGENTS.md R5.6 现状)

- **撤回**旧「≤500 行 / ≤5000 tok(Codex 8KB)」——Codex 8KB 根据失效(opencode 无平台尺寸上限,§2.1),500 行松 2.5–3.5×。
- **保留 5,000 tok 硬上限**,但根据换成 §2.4 四股压力(lost-in-the-middle + system 5–10% + 经验承载重量 + 防回归)。
- TOKEN 是约束维度;LINE 降为 drafting 指引。
- 新增**保真度优先**落地方式:删冗余/重复/R5.10 dev-meta + 迁可分片细节进 lazy fragment;**MUST NOT** 删承重处理流程节点与已修 bug 防线(见「⚠ 裁剪前提:保真度优先」);超尺寸壳 **shard-to-fit**(抽子流程进 lazy fragment),NEVER 靠删承重内容硬凑达标。
- lint = fail-loud 防回归 + 增量 review。

### 6.2 裁剪的三股理由(据 §2 重推)

1. **lost-in-the-middle 注意力衰减(发起本分析的原始关切,权威根据)**:Transformer 对长上下文呈 U 形注意力,关键信息埋中段显著掉准(所有模型固有,非"弱模型"专属)。9,361-tok/268-行壳把 `.active` 哨兵写入埋在 `:66`(中段衰减区)= skip 风险根因。**壳变短 + 关键动作前置/突出 = 直接治本**。
2. **system 块预算(子 agent 受约束)**:子 agent stage 替换 base 提示词、与继承 AGENTS 共占 system 块 ≤ 窗口 5–10% → 子 agent 有效系统保守 ≤5K。
3. **防松散迭代再膨胀(硬上限本身是交付物)**:无硬上限 = 几个迭代后又超回本次优化前。硬上限是回归护栏,不是上下文算术。

> 注:**压缩不再是壳尺寸的约束**(壳是一次性 USER 历史,非每轮 system;opencode ~130K auto-compact 由累积工具结果+AGENTS 驱动)。压缩的真正杠杆是 `--orch-budget-bytes`(工具结果纪律),非壳——此前"压缩 → 壳要小"的因果链**撤回**。

### 6.3 lint 强制(防回归 fail-loud + 增量 review)

`tools/measure_prompts.py` 已存在(stdlib,本报告测量源,`mid_tokens` 工作值 + 高/低区间)。建议新增 `tools/check_distributed_prompt_budget.py`(或并入 `tools/check_contracts.py`):

- **fail-loud 硬断言**:每个 mgh-* 编排器壳(claude+opencode 双壳)≤ 5,000 tok;每个子 agent 有效系统(agent def + stage + 声明加载的 fragments)≤ 5,000 tok。超 → exit 2(对齐 R5.9)。
- **增量 review**:相对上次 release 基线的字节/token 增长超阈值 → 报告(review,非 fail)。防慢漂移积累成突破。
- 接入 CI(R5.8:CI 必 fail),与 `check_contracts.py` / `check_distributed_purity.py` 并列。

### 6.4 关键一次性动作的突出化(承 lost-in-the-middle)

跨 5 命令的 `.active` 哨兵生命周期(write step 0 / rewrite step 1 / rm step N)目前埋在密集 flow code block 中段(注意力衰减区)。建议:每壳顶部加 labeled callout(如「**STEP 0 MUST:** export `MGH_*_ACTIVE=1` 且写哨兵;**STEP N MUST:** rm 哨兵」)——**净 token 中性、把关键动作从衰减区移到首部(primacy)区,执行忠实度大增**。

---

## 7. 拆任务清单(供后续 /opsx:propose 切分,不在本报告实现)

> 排序:编排器壳按 token 节省量降序 → 最差子 agent stage。每个任务 = 一行目标 + 归属的 §4 bloat_targets。
>
> **5,000 tok 是硬上限**(§2.4 四股压力;§6.3 lint fail-loud 强制)。到达方式 = **shard-to-fit 保真**:超尺寸壳/子 agent 经「抽子流程/专题进 lazy fragment(只迁移、不删除)」+「删冗余/重复/R5.10 dev-meta」收敛到 ≤5K。**MUST NOT 靠删承重处理流程节点或已修 bug 防线硬凑达标**(见上方「⚠ 裁剪前提:保真度优先」——每个裁剪点落地前先验真)。mgh-init 9,361 的 faithful-trim 地板 ~7,100 > 5K ⇒ **必须** shard(抽 `init-stage-flow.md`),印证 shard 是该壳达标的唯一保真路径。
>
> **执行前必读上方「⚠ 裁剪前提:保真度优先」**:每个裁剪点落地前先验真是否为承重流程节点或已修 bug 的防线;「节省」是上限,保真度优先。

| # | 任务 | 目标(一行) | 归属 bloat_targets |
|---|---|---|---|
| 1 | **fix/harden-mgh-init-shell-budget** ✅ **DONE**(claude 9,361→2,916 / opencode 9,224→2,853;fragment `init-stage-flow.md` 4,769;预算模型重接地 D6) | mgh-init 壳 9,361 → ≤5,000:抽编排流细节进 `init-stage-flow.md` fragment(壳保留 parse-args + SUB-SKILL + 表 + 披露 ~4,200 tok + 1 fragment)+ 删重复 Bash 目录 + 折叠 stage 表 + 压 disclose + 修「本仓」 | mgh-init §4.2 全部(尤其 194-229 删、53-165 结构性抽 fragment、253-268 压、167-191 折、10-18/45-51/79-142 去重、10「本仓」修) |
| 2 | **fix/harden-mgh-sast-deepdive-specialist-hints** | sast-deepdive s4 6,989 → ≤5,000:切 `specialist-hints.md`(3,657)为 `lenses/<specialist>.md` 6 文件,agent 仅 Read 对应单文件;保留溯源头(R1) | mgh-sast §4.3 specialist-hints 项(+ stage-map / agent:17 更新) |
| 3 | **fix/harden-mgh-sra-augment-codegraph-extract**(同时治 mgh-srr 继承) | sra-augment a3 5,274/6,288 → off ≤5,000:抽 stage Task-3 4-facet codegraph 块(71-103)进 gated fragment `codegraph-structural-evidence.md`(仅 codegraph=on 加载);stage 留 3 行指针;同步删 agent def 的 codegraph recap | mgh-sra §4.4 sra-augment.md:71-103 + agent:27-36(注:mgh-srr 子 agent 复用 sra,自动受益) |
| 4 | **fix/harden-mgh-sra-shell-budget** | mgh-sra 壳 5,460 → ≤5,000:压「Always disclose」重述 step 7、codegraph 检测辩护、budget flag 块、impl-intention/刚性三元组合并、删「承 mgh-init」 | mgh-sra §4.4 壳行(201-221、96-102、210 承 mgh-init、47-51、62-68、159/162) |
| 5 | **fix/harden-mgh-srr-shell-budget** | mgh-srr 壳 5,148 → ≤5,000:压 Orchestrator-discipline NEVER-list、hook 原理 blockquote、focus/sensitive-catalog 验证契约去重、codegraph 检测辩护、budget/timeout 重释 | mgh-srr §4.5(61-76、18-24、37-44、100-104、192-193) |
| 6 | **improve-mgh-init-rulewriter-rules-format-opencode** | init-rulewriter opencode worst path 4,040 → ~3,400:审 `rules-format-opencode.md`(1,316,~1.8x claude)压 AGENTS.md-index-block 模板为 schema 示例 + 3 行规则,趋向 claude fragment(708)密度 | mgh-init §3.1/§4.2 init-rulewriter subagent note |
| 7 | **harden-mgh-*-sentinel-prominence**(跨 5 命令,token 中性) | 5 壳统一:把 `.active` 哨兵 write/rewrite/rm 提升为顶部 labeled callout(零净 token,治弱模型 skip-risk) | §6.4;每壳 BURIED CRITICAL ACTION 项(mgh-init.md:66、mgh-sast.md:66、mgh-sra.md:94-95、mgh-srr.md:83/96/142、mgh-ut-init.md:58-65) |
| 8(可选) | **trim-mgh-ut-init-shell-headroom** | ut-init opencode 壳 4,936(余量 64):删 env 继承第三处重释、opt-out flag、list_test_groups 例压规范形式 | mgh-ut-init §4.6(170、17-19、9-16、127-141) |
| 9(可选) | **trim-mgh-sast-shell-headroom** | sast 壳 4,543(余量 457):timeout 去重、budget flag gloss 压、NEVER 链 lead-in | mgh-sast §4.3 壳项(142/182、36、48-53) |

> 任务 1–6 是治「超长」;任务 7 治「skip-risk」(发起本分析的原始关切,token 中性故与超长独立);任务 8–9 是薄余量的预防性裁剪(非突破)。

---

## 8. 暂缓项(deferred)

维护者**已单独确认**的待办(不属本分析设计,仅登记):将 `.active` 哨兵写入从「依赖编排器 printf 提示词」改为 `write_runconfig.py` 的**确定性副作用**(+ `resume_state.py --check` 校验哨兵存在),应用于全部 5 命令——从根上消除弱模型漏写哨兵的 skip-risk(与本报告 §6.4 的提示词突出化是同一问题的两条互补路径:§6.4 是提示词内治标、本项是脚本侧治本)。本报告**不设计其实现**,留待后续单独推进。

---

## 9. 「分发足迹 ≠ 运行时叠加占用」模型勘误(2026-08-12 增补)

> **触发**:apply `harden-mgh-init-shell-budget` 时,本报告 §3.1 的「编排器分发足迹(壳 + fragments)≤ 8,000」目标
> 与 design D1/D2 数学冲突——`init-stage-flow(~4,500) + orchestrator-discipline(2,466) = ~6,991`,8K 求和下仅剩 ~1,009
> tok 给整个壳,parse-args 单项即破。复盘发现:**8,000 求和上限只出现在本报告 §3.1/§7 任务 1 之外的 design 目标,从未像 5K
> 那样严密推导**。本节据 opencode 源码核实,把它**重接地**。完整机制 + 源码行号 + 复核清单见
> [`docs/opencode-context-mechanics.md`](opencode-context-mechanics.md)。

### 9.1 错在哪

`tools/measure_prompts.py:107` 对各文件 `mid_tokens` **求和**,是**磁盘文件大小估算器**。
把「shell + 所有 fragments」按磁盘大小相加,等价于隐含假设三者**同时是每轮 system 开销**。opencode 源码否决该假设:

| 事实 | opencode 源码 | 含义 |
|---|---|---|
| 命令壳 = 一次性 USER 消息,非每轮 system | `packages/opencode/src/session/prompt.ts:1432-1451`(壳 → USER parts)、`prompt.ts:635,656`(持久化为 User 消息) | 壳只在触发轮进历史;**不随轮次累乘** |
| system 块每轮由 `env+instructions+mcp+skills-list` 重派生 | `prompt.ts:1257-1269` | 壳、fragment **不在** system 块 |
| `@file` / `REQUIRED SUB-SKILL` 仅产出 USER part(模型 lazy Read) | `prompt.ts:157-191`(`resolvePromptParts`,只处理 `@file`/`@agent`,**无 fragment/include 自动内联**) | fragment 进上下文 = 单次 Read 的 USER 历史项 |
| 自动压缩由累积工具结果 + AGENTS 驱动,约 130K 触发 | `overflow.ts:22-34`(`count >= input - reserved`,`reserved=min(20000,...)`);`prompt.ts:1161-1168` | 压缩**不**由壳尺寸驱动(本报告 §2.1/§6.2 已撤回该因果链) |

⇒ 壳与各 fragment **从不**作为「每轮叠加的 system 税」同时存在。「足迹 = shell + fragments 求和 ≤ 8,000」把它们当成同时驻留的每轮开销,**反真实**。

### 9.2 重接地(新预算模型)

| 上限 | 形态 | 根据 | 状态 |
|---|---|---|---|
| **壳 ≤ 5,000 mid tok** | 磁盘 + 触发轮 USER 项 | lost-in-the-middle(壳 = primacy 区首条 USER)+ 防回归 + 经验承载重量(本报告 §2.4 四股) | **保留,真约束** |
| **fragment 逐个评估** | 「单次 Read 轮的尺寸是否结构良好」 + 「是否与另一 fragment 在 history 稳态叠加」 | opencode 运行时模型(fragment = 单次 lazy Read 的 USER 项,§9.1) | **新;无硬求和** |
| **磁盘合计 ≤ ~10,000(防漂移 lint)** | `shell + orchestrator-discipline + init-stage-flow` 的 `mid_tokens` 求和 | **磁盘大小防漂移**(防松散迭代再膨胀),**非**运行时叠加占用声明 | **替换原 8,000**;明确标注根据 |

**关键含义**:`init-stage-flow` ≈4,500 mid 在新模型下**合法**(它是单次 Read 的 USER 项;老化入 head、`resume_state.py`
磁盘兜底,编排器后期不需它——见 opencode-context-mechanics §5)。原 8,000 求和造成的「数学不可达」消失。
**不**需要为省上下文把早期 step 塞进 opencode skill——skill body 受 prune 保护(`compaction.ts:31,303` `PRUNE_PROTECTED_TOOLS=["skill"]`)
反而更难淘汰,且 skill 列表常驻每轮 system(见 opencode-context-mechanics §4)。fragment 懒加载**已经是**「用完自然老化」的正确范式。

### 9.3 对本报告他处的影响

- **§3.1 mgh-init 表**「分发足迹 11,827/11,690」:数值本身(磁盘求和)仍可作「防漂移」基线引用,但**不可**解读为「运行时每轮叠加占用」。应加注「= 磁盘文件求和,非运行时足迹(§9)」。
- **§7 任务 1** 的目标行(`→ ≤5,000`)不变;其隐含的「+fragment 求和」应按 §9.2 改为「fragment 逐个评估 + 磁盘合计 ≤~10K 防漂移」。
- **§6.3 lint 设计**:硬断言只保留「壳 ≤5,000」+「子 agent 有效系统 ≤5,000」;fragment 不做求和硬断言,改增量 review(磁盘大小漂移)。
- §2.1/§6.2 既有的「压缩不由壳尺寸驱动」结论**被本次勘误强化**(§9.1 给出更完整源码引用),不动。

### 9.4 落地

本勘误已写回 `harden-mgh-init-shell-budget` 的 design(新增 **D6 预算模型重接地**)、proposal(测量验证行)、
spec(壳 token 预算 requirement + 两 Scenario)、tasks(task 4.2 验收形态)。D1/D2/D3/D4/D5 **不动**(保真度路径正确,冲突来自预算模型而非内容迁移)。

---

## 测量方法与不确定性

- token 为**估算区间**(tokenizer 不确定):ASCII 4 chars/tok;CJK/其他多字节按 1.2–2.0 chars/tok(中心 1.5)。报告用 mid_tokens 作工作值;预算决策锚定**字符/行**(确定性)而非 token。
- 行 ↔ token 比 ~25–35 tok/line 为 zh-dense 壳实测;mgh-init 最密(~35)。
- 测量工具:`tools/measure_prompts.py`(stdlib,R2;dev-time,不分发)。
