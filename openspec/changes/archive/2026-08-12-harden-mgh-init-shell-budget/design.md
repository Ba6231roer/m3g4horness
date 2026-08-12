## Context

`docs/review-prompt-length-budget-150k.md` 实测 mgh-init 编排器壳 9,361 tok(claude)/ 9,224 tok(opencode),
突破 R5.6 的 5,000 tok 硬上限;编排器分发足迹 11,827 / 11,690 突破 8,000 tok。双害:① 每轮固定开销过大,
多轮 fan-out 下更早触发自动压缩;② 关键一次性动作(`.active` 哨兵 write step 0)被深埋在 268/259 行密集
code block 中,短上下文模型易漏读 → opencode 上 hook 激活的唯一可靠路径静默失效。

当前壳结构(两壳镜像,行号见报告 §4.2):
- 顶部 hook 机制重述三处之一(10–18)、parse-args(27–43)、orchestrator-discipline SUB-SKILL(45–51)、
  **编排流 53–165(110 行 / ~4,500 tok,最大块)**、Stage→组件表(167–191)、**Deterministic invocation Bash
  目录块(194–229,36 行重复 flow)**、Resume/cache(231–237)、Output(239–251)、Always disclose(253–268)。
- 已有 fragment 范式:`orchestrator-discipline.md`(2,466 tok)经 `REQUIRED SUB-SKILL` 加载,壳瘦身成功先例
  (change `extract-shared-substrate` 建立该范式 + `orchestration-substrate` spec 治理)。

报告 §4.2 结论:**「无法不结构性动刀达到 5K」——抽编排流细节进新 fragment 是唯一路径**(单项 ~3,500 tok
节省,是达到 5K 的承重杠杆)。

**保真度铁律**(承报告「⚠ 裁剪前提」):历史提示词是多轮迭代沉淀;大量看似冗余的 mantra/反例/边界披露实为
针对真实失败形状的承重防御。本变更 MUST 先验真每条裁剪,确认非关键流程节点或已他处覆盖,方可删/迁。

## Goals / Non-Goals

**Goals:**
- mgh-init 两壳经 `tools/measure_prompts.py` 实测 `mid_tokens` 各 ≤ 5,000 tok(R5.6 硬上限;据 D6,壳 = 触发轮 USER 首条消息、primacy 区,5K 是真约束)。
- **分发足迹目标改为非求和形态**(据 D6 重接地):壳 ≤ 5,000 + 各 fragment 按「单次 Read 轮尺寸」逐个评估,**不**强制 `shell + fragments` 求和 ≤ 8,000(该 8K 是磁盘求和、与 opencode 运行时模型矛盾,见 D6)。
- 关键一次性动作(`.active` 哨兵)在精简后的壳中**更突出**(skip-risk 收益,与压缩独立)。
- mgh-init 流水线可观测行为**零变化**(产物 / schema / stdout / 退出码 / fan-out 边界 / `--check` 闸门)。
- 两壳 stage 流正文零 drift(共用单一 `init-stage-flow.md`)。
- 新 fragment 过分发纯净性 lint(R5.10)。

**Non-Goals(本变更不做,留后续单独 propose):**
- §6.3 新增 `tools/check_distributed_prompt_budget.py` lint + CI 接入(防再次静默突破)——本变更用既有
  `measure_prompts.py` 做落地后人工实测验证,**不**建自动化 lint;自动化留后续。
- §7 任务 2–9(sast/sra/srr 壳瘦身、specialist-hints 切分、sra-augment codegraph 抽 fragment、
  rules-format-opencode 压缩、5 壳统一哨兵 callout、ut-init/sast 薄余量预防裁剪)。
- R5.6 措辞修正(把「500 行」改 token-derived 行数指引)——AGENTS.md 编辑,**非**本变更产物路径(已于本变更外完成:AGENTS.md R5.6 现「行数非硬约束(已废 500 行)」+ 重新接地 5,000 tok 为四股压力收敛点 + 新增 shard-to-fit;本变更的 5,000 tok 目标与 shard 方法路径不变)。
- `.active` 哨兵写入从「依赖编排器 printf」改为 `write_runconfig.py` 确定性副作用(报告 §8 deferred)。

## Decisions

### D1 — 抽编排流 step 0–8 细节进 `init-stage-flow.md`;壳保留 parse-args + 表 + Resume + Output + disclose

**决定**:新建 `core/prompts/fragments/init-stage-flow.md`,**整块搬移**当前壳的「## Orchestration flow」
code block(step 0–8 全部逐步细节)进该 fragment。壳经 `REQUIRED SUB-SKILL: Use init-stage-flow` 引用
(紧随既有的 `Use orchestrator-discipline`)。壳保留:parse-args、orchestrator-discipline SUB-SKILL、
init-stage-flow SUB-SKILL、Stage→组件表(折叠,见 D3)、Resume/cache、Output、Always disclose(精简,见 D4)。

**理由**(why fragment vs 内联瘦身):报告 §4.2 已证即便做完所有具体裁剪(~2,240 tok 节省)壳仍 ~7,100 tok,
**无法不结构性动刀达 5K**。编排流本身 ~4,500 tok 是最大块且高度自洽(逐步流水线正文),抽 fragment 后壳
~4,200 tok + 1 fragment,精确达 5K。fragment 模式有 `extract-shared-substrate` 成功先例、install.sh 已
镜像 `core/prompts/` 无需改、双壳共用单文件零 drift。

**备选**(considered & rejected):
- (a) 只做具体裁剪不抽 fragment → 数学上达不到 5K(reject)。
- (b) 抽 stage 流进多个 per-tier fragment(scout.md / t1.md / t2.md …)→ 过度切分,编排流是线性序贯、非
  按需分支,单文件更利于 agent 一次加载读完;且报告测算单 fragment 即够(reject)。
- (c) 把 stage 流也塞进 `orchestrator-discipline.md` → 该 fragment 的 spec 明确「host-agnostic、不绑定
  init 专属名」;stage 流含大量 init 专属脚本/产物名,塞进去破坏其宿主无关契约、且未来 mgh-ut-init 等
  会复用 orchestrator-discipline 不能染 init 内容(reject)。

### D2 — `init-stage-flow.md` 是 init 专属但**两壳共用单一文件**

**决定**:尽管 init-stage-flow 含 init 专属内容(非 host-agnostic),claude 与 opencode **引用同一文件**
(`core/prompts/fragments/init-stage-flow.md`)。两壳 stage 流正文当前已是逐字一致(仅壳体措辞与
`.claude/mgh-core` / `.opencode/mgh-core` 前缀差异);stage 流正文内的路径前缀**不写死**(用 `<target>/.mgh-init`
与 `.claude/mgh-core`/`.opencode/mgh-core` 由壳侧 SUB-SKILL 加载解析的既有约定——当前 stage 流已如此)。

**理由**:零 drift、单点真相、镜像零成本。壳体差异(allowed-tools、claude `.claude/rules` vs opencode
`AGENTS.md` 索引块、step 6b 措辞)留在壳,不进 fragment;stage 流正文是 host-agnostic 的流水线步骤。

**风险**:若未来 claude/opencode stage 流需要分叉(host-agnostic 假设破裂)→ 见 Risks。

### D3 — Stage→组件表折叠为紧凑 2 列;删「Deterministic invocation (Bash)」整块

**决定**:
- **Stage 表**(167–191):Asset 列删每阶段 `core/scripts/<x>.py` 绝对路径(flow 已内联 + 绝对路径由
  `list_steps.py` 运行时给);折为「script inventory | subagent inventory」紧凑表(仅名)。保留非平凡复用注
  (`expand_scope.py` 复用、`merge_scout.py` 复用 `form_clusters`)为 2 行脚注——这些是「非显而易见的复用」,
  agent 不读源码会错过。
- **Bash 目录块**(194–229):整块删(36 行全 flag 命令目录,与 flow 重复内联)。保留 2 个**未在 flow 内联**
  的逃生口迁回原生步骤:① 大文件切片 `chunk_sources.py` 调用 form(迁入 step 3b/4 的 fan-out 描述,已是
  该处引用);② `resume_state.py --invalidate-stale` 配方(迁入 Resume/cache 段,该语义本就属于 resume)。

**理由**:报告 §4.2 实测 Stage 表省 ~400、Bash 块省 ~900。Bash 块是「重复编排流步骤 2/3b/4/4b/5/6/6b 已内联
的全 flag 命令」纯冗余;R5.1 契约 lint 靠脚本 `--help`(脚本未改,flag 闭合不受影响)。

**保真度验证**(承「⚠ 裁剪前提」):删 Bash 块前 MUST 确认其中每个 flag 都在 flow 对应步骤出现(flow 内联调用
即是该 flag 的契约面);若某 flag 仅出现在 Bash 目录块、flow 无 → 该 flag 是遗漏,不是冗余,**迁入 flow**
而非删。这是实现者逐条标注的检查点。

### D4 — Always disclose 压 16→5 条;细节落 boundaries[]/report.md

**决定**:压为 5 条规范要点:① LLM 诱发/人工复核;② 存在≠有效(CVE-2025-41248);③ call-graph 文本/AST
漏动态分派;④ 中文输出;⑤ scout 非整仓覆盖。其余(dotfiles/tests 跳过、宿主 shell 超时、codegraph 辅助、
请求上下文预算、launch-cwd 前置)细节**已在 `init_manifest.json::boundaries[]` / `report.md` 由脚本写入**,
disclose 仅留一行指针「`boundaries[]` 已携带,仅 `report.md` 复述」。

**理由**:报告 §4.2 实测省 ~500。这些披露是**给最终用户读的产物内容**,其权威来源是脚本写入的
`boundaries[]`/`report.md`(运行时落盘);壳内 disclose 是编排器「记得在摘要里陈述」的提示,不需重复脚本
已强制的全部细节。**保留**5 条最核心、且非脚本强制、需编排器主动陈述的。

**保真度验证**:launch-cwd 前置(step 0 首调 `list_steps.py` 依赖从目标项目根发起)是**编排器动作纪律**非
产物披露——MUST 确认其在壳内仍以「编排纪律」形式保留(迁 parse-args 注记或 Resume/cache,不删)。

### D5 — hook 机制三处重述去重 + 「本仓」修 + mantra 去重

**决定**:
- hook 机制三处重述(顶部 10–18、step 0 的 57–69、orchestrator-discipline fragment 16–18/43):顶部折为
  2 行指针(激活 = env 或哨兵;哨兵写法见 step 0、纪律见 fragment);**保留 opt-out flag 提及**(R5.7 透明度)。
- 顶部「本仓」→「目标项目」(claude:10 / opencode:9,R5.10 第 7 类 dev-meta)。
- `NEVER py -c`/`NEVER Read 整份大 JSON` mantra 8+ 次:编排流顶部一次性注记 + 删逐步 echo;**保留**防具体
  失败形状处(T1 的 scout-incomplete-gate line 128、T1→T2 的 `validate_t1_records --check` 形状闸门)——这些是
  「agent 可能猜不到边界」的最小反例(承 R5.5⑤)。
- 删 line 51「stdout 直消费」重述(已在 orchestrator-discipline fragment:20–23)。

**理由**:报告 §4.2 实测共省 ~440(hook 220 + 本仓 5 + mantra 140 + stdout 80)。mantra 去重承 R5.5⑤
「禁令清楚则不举例」:抽象 NEVER 顶部一次即足,仅在「agent 可能猜不到边界」处留最小反例。

### D6 — 预算模型重接地:壳 ≤5K 是真约束;「足迹 ≤8K 求和」撤回为磁盘防漂移上限

**背景(冲突所在)**:apply 时实测数学不可达——`init-stage-flow(~4,500 mid) + orchestrator-discipline(2,466) = ~6,991`,
8,000 求和上限下仅剩 ~1,009 tok 给整个壳(parse-args+表+resume+output+disclose),parse-args 单项即破。
原报告 §7 任务 1(本变更的源头)**只**约束壳 ≤5,000;**8,000 上限只出现在 design 目标 + 任务 4.2,从未像 5K 那样严密推导过**。

**根因(opencode 源码核实,见 `docs/opencode-context-mechanics.md`)**:`tools/measure_prompts.py:107` 对各文件 `mid_tokens`
**求和**,是**磁盘文件大小估算器**,非运行时上下文足迹模型。把「shell + 所有 fragments」按磁盘大小相加,等价于假设三者
**同时是每轮 system 开销**——但 opencode 实际(`packages/opencode/src/session/prompt.ts:1432-1451` 壳 = 一次性 USER 消息;
`1257-1269` system 每轮由 `env+instructions+mcp+skills-list` 重派生;`@file`/REQUIRED SUB-SKILL 经 `157-191` 仅产出 USER part)
**否决该假设**:壳与各 fragment 都是**单次 lazy Read 的 USER 历史项**,不是每轮叠加 system 税。报告自身 §2.1/§6.2 已撤回
「压缩由壳尺寸驱动」的因果链。**8K 求和上限 = 反真实的过约束**。

**决定**:
- **保留**:壳 ≤5,000 tok(真约束——壳是触发轮 USER 首条消息、primacy 区,lost-in-the-middle + 防回归;据报告 §2.4 四股压力)。
- **撤回为弱形态**:不再强制 `shell + init-stage-flow + orchestrator-discipline` 求和 ≤8,000。fragment 改为**逐个评估**
  (「单次 Read 轮的尺寸是否结构良好 + 是否会与另一个 fragment 在 history 稳态叠加」),**不强制求和**。
- **保留一个磁盘防漂移上限作 lint 护栏**(防回归,非运行时占用声明):`shell + orchestrator-discipline + init-stage-flow` 的 `mid_tokens`
  合计 ≤ ~10,000(≈ 5K 壳 + 一个典型 lazy-Read fragment 的余量),**明确标注其根据 = 磁盘大小防漂移**,NEVER 标注为「运行时叠加占用」。

**对 D1/D2 的影响**:**零**。`init-stage-flow` ≈4,500 mid 在新模型下**合法**(它是单次 Read 的 USER 项,非每轮 system 税;
且老化入 head、`resume_state.py` 磁盘兜底,编排器后期不需它——见 `docs/opencode-context-mechanics.md` §5)。D1/D2 不动。

**备选**(considered & rejected):
- (a) 为省上下文把早期 step 内容塞进 **opencode skill**,冀「用完被压缩丢掉」→ **reject**:opencode `PRUNE_PROTECTED_TOOLS=["skill"]`
  (`compaction.ts:31,303`)使 skill body **更难**淘汰(受 prune 保护),且 skill 列表常驻每轮 system——**反向**,见 opencode-context-mechanics §4。
- (b) 把 init-stage-flow 切成更小 fragment 凑求和 ≤3K → reject:线性序贯流水线不应过度切分(D1 备选 b 已 reject);且求和上限本身已撤回(D6)。
- (c) 维持 8K 求和上限、砍 D1 保真度凑达标 → reject:承重内容不可删(报告「⚠ 裁剪前提」);且上限本身错(D6)。

**落地验证调整**:task 4.2 由「求和 ≤8,000」改为「(i) 壳 ≤5,000;(ii) `init-stage-flow` 单文件尺寸报告(供逐个评估,无硬上限);
(iii) 三者磁盘合计 ≤~10,000(防漂移 lint,标注根据)」。

## Risks / Trade-offs

- **[stage 流进 fragment 后,弱模型可能跳过加载 init-stage-flow → 漏跑步骤]** → **Mitigation**:
  ① 壳内 SUB-SKILL 指令用「REQUIRED」(RFC-2119,与 orchestrator-discipline 同级);② 壳的 Stage→组件表 +
  parse-args 仍给编排器「全图」概览(步骤数 + 每步组件),即使跳过 fragment 也不至于完全失向;③ `resume_state.py`
  是磁盘真相源,任何漏步在 `--resume` 时从磁盘重派生兜底(承 R5.4);④ 这是 fragment 模式的既有 trade-off
  (orchestrator-discipline 同样如此),不是本变更引入的新风险。
- **[裁剪误删承重内容]** → **Mitigation**:每个裁剪点落地前逐条验真(承报告「⚠ 裁剪前提」):git blame /
  commit message / `docs/review-*.md` 确认非已修 bug 防线;「节省」是上限,保真度优先。tasks.md 列出每条
  裁剪的「承重→保留 / 已他处覆盖→删 / 可迁移→抽取」标注检查点。
- **[claude/opencode stage 流分叉假设破裂]** → **Mitigation**:当前两壳 stage 流正文已逐字一致(本变更前);
  若未来分叉,split fragment 或壳内 inline 是 escape hatch(不破坏 spec,spec 允许「壳体差异留在壳」)。
- **[落地后实测仍略超 5K(token 估算区间)]** → **Mitigation**:`measure_prompts.py` 报 low/mid/high 三值;
  预算决策锚 mid_tokens,但报告已预留 high_tokens 余量(5K 在 zh-dense ~145–200 行);若 high 略超,进一步压
  Stage 表脚注 / disclose 指针(D3/D4 有余量)。
- **[删 Bash 目录块影响契约 lint]** → **Mitigation**:`check_contracts.py` 从 bash 块提取 flag 断言;但
  flow 内联调用同样是 bash ```block,flag 仍在扫描集内(脚本未改,`--help` 闭合不变)。验证:跑
  `check_contracts.py` 全绿。
- **[无自动化 lint → 未来再次静默突破]** → **Trade-off, accepted**:本变更不建 `check_distributed_prompt_budget.py`
  (留后续);靠 R5.6 措辞 + 本次实测 + 未来 lint 任务(§6.3 deferred)。这是有意识的范围收窄。
- **[预算模型重接地(D6)改了任务 4.2 的验收形态]** → **Mitigation**:原 8K 求和验收被替换为「壳 ≤5K + fragment 逐个评估 +
  磁盘合计 ≤~10K(防漂移)」三段;三者均有源码/实测根据(opencode 运行时模型见 `docs/opencode-context-mechanics.md`,
  报告 §2.1/§6.2 已撤回壳尺寸→压缩因果链)。D1/D2 保真度不受影响(init-stage-flow ≈4.5K 在新模型下合法)。

## Migration Plan

无数据迁移 / 无 schema 变更 / 无脚本改动。部署 = 标准 install.sh(新 fragment 自动镜像)。回滚 = git revert
(纯 `.md` 变更)。验证序列(实现完成后):
1. `py tools/measure_prompts.py releases/claude-code/commands/mgh-init.md releases/opencode/command/mgh-init.md` →
   两壳 mid_tokens ≤ 5,000(真约束;D6)。
2. `py tools/measure_prompts.py core/prompts/fragments/init-stage-flow.md core/prompts/fragments/orchestrator-discipline.md` →
   **逐个报告**(单文件尺寸,供「单次 Read 轮结构是否良好」评估,**无硬求和上限**);另记三者磁盘合计 ≤~10,000 作防漂移 lint 上限
   (标注根据 = 磁盘大小防漂移,非运行时叠加占用;D6)。
3. `py tools/check_contracts.py` → mgh-init flag 契约闭合(脚本未改,应不变)。
4. `py tools/check_distributed_purity.py` → 新 fragment + 两壳纯净性(R5.10,无 R5.x/承/本仓)。
5. 既有回归测 `py tests/test_deterministic.py`(及 mgh-init 相关契约/纯净/零依赖测)全绿。
6. (可选,人工)mgh-init 流水线首跑对照:产物/边界披露与变更前一致。

## Open Questions

- **Q1**:`init-stage-flow.md` 是否需在头部加溯源/作用域注释(类比 orchestrator-discipline.md:1–12 的 HTML
  注释)?→ **倾向是**:说明「init 专属 stage 流细节;两壳共用单文件;经 REQUIRED SUB-SKILL 加载」+ 不含
  R5.x/承 dev-meta(承 R5.10)。实现者落地时加。
- **Q2**:Always disclose 的「launch-cwd 前置」(D4 保真度验证提到)最终落点——parse-args 注记 vs Resume/cache 段?
  → **倾向 Resume/cache**(与「新 session 重注入 env」同属跨 session 纪律);实现者定。
