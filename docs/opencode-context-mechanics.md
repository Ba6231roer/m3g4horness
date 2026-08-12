# opencode 上下文与压缩机制(mgh-* 开发参考)

> **用途**:当本仓开发涉及「提示词会占多少上下文 / 何时触发压缩 / fragment 何时被丢弃 / skill 能否被自动淘汰」时,
> **先读本文件**。所有断言经 opencode 源码核实(核实时点 2026-08-12;opencode `packages/opencode` 与 `packages/core` 双路径)。
> 源码路径相对 `C:\DEV\opencode`。**opencode 双路径并存**:v1(`packages/opencode/src/session/`)是当前主运行路径,
> v2(`packages/core/src/session/`)是较新 core runner;两者压缩逻辑同形,本文以 v1 为主、v2 差异处标注。
>
> 本文件是**操作性参考**(R3:面向 AI、索引化、简练),不是 opencode 官方文档。机制本身会随 opencode 版本变,
> 引用前**按行号回源码复核**(行号会漂移,函数名/常量名更稳定)。

---

## 0. TL;DR(给 mgh-* 的三条可操作结论)

1. **命令壳 = 一次性 USER 消息,不是每轮 system**。`/mgh-init` 的壳体只在触发那一轮进 USER 历史;
   之后每轮的 system 块由 `env + instructions(AGENTS) + mcp + skills-列表` **重新派生**(§1)。
   ⇒ **壳尺寸不随轮次累乘**,「每轮固定开销」是误述。
2. **opencode 无 step-aware 淘汰**。只有两种降上下文手段:压缩(整段 head 摘要,溢出阈值触发,§2)+ prune(只清工具输出,§3)。
   没有任何东西按「N 轮未使用」或「步骤完成」丢弃单个 fragment/skill。
3. **skill 受 prune 保护,反而更难被淘汰**。`PRUNE_PROTECTED_TOOLS = ["skill"]`(`compaction.ts:31,303`)。
   想用「skill + 等压缩丢掉它」来省上下文是**反向**:skill body 进来后比 lazy-Read fragment 更持久。
   ⇒ mgh-* 的「fragment 经 REQUIRED SUB-SKILL 懒加载」**已经是**「用完自然老化」的正确范式(§5)。

---

## 1. 每轮上下文是怎么组装的(命令壳 / fragment / skill 各落在哪)

```
每轮 LLM 请求 = [SYSTEM 块] + [HISTORY(对话历史,持续累积)]
```

**SYSTEM 块**:每轮**重新派生**,不进历史、不累积。组装点 `packages/opencode/src/session/prompt.ts:1257-1269`:

```
system = [...env, ...instructions, ...(mcpInstructions?[...]:[]), ...(skills?[...]:[])]
```

- `env`(工作目录 / git / 平台 / 日期 / 项目引用)— `system.ts:60-96`
- `instructions`(AGENTS.md / CLAUDE.md 等指令文件,walk `findUp`)— `instruction.ts`,`prompt.ts:1260`
- `mcp` server 指令 — `system.ts:112-128`
- `skills` **列表**(仅 name+description,**不是 body**)— `system.ts:98-110`,每轮重渲染

**HISTORY(真正会增长、会触发压缩的部分)**:USER/assistant 消息 + 工具结果,按序累积,受压缩/prune 管理。

### 各类内容落在哪一张表(承 §0 结论 1)

| 内容类型 | 落在哪 | 每轮 system 开销? | 受 prune? | 压缩时? |
|---|---|---|---|---|
| `/mgh-init` **壳体** | 一次性 **USER 消息**(触发轮) | ❌ 仅触发轮 | ❌(非工具输出) | 入 head → 摘要化 |
| 经 `@file` / **REQUIRED SUB-SKILL 的 Read** | Read 产出的 **USER 文本 part**(读取轮) | ❌ 单轮 | ❌ | 老化入 head → 摘要化 |
| **fragment** 本身(磁盘文件) | 不主动进上下文;被 Read 才进 | ❌ | ❌ | 同上 |
| **skill body**(模型调用 skill 工具后) | **工具结果** | ❌ 单次加载后驻留 | ❌ **受保护** | 仅整段压缩摘要 |
| **skill 列表**(name+desc) | **SYSTEM 每轮** | ✅(很小) | N/A(每轮重生) | N/A |
| 目标项目 **AGENTS.md** | **SYSTEM 每轮** | ✅(外部不可控) | N/A | N/A |
| 普通**工具结果**(Bash stdout 等) | 工具结果 in history | ❌ | ✅(§3) | 入 head → 截断摘要 |

**命令壳注入点**(`prompt.ts:1432-1451`):`/mgh-init` 的 `template` 经 `resolvePromptParts`(`@file`→file part,`@agent`→agent part)解析,
结果 `parts` 进 `prompt()` → `createUserMessage` 持久化为**一条 USER 消息**(`prompt.ts:635,656`)。
**壳体从不进 system 块**——`command()` 全程不碰 system 组装。

> **关键澄清**:`REQUIRED SUB-SKILL: Use X` 在命令壳里**只是模型解释的文本指令**,opencode **不解析、不内联**
> (全仓 grep `fragment`/`include`/`inline` 仅命中 `Array.includes` 等无关项;唯一文件引用机制是 `@<path>` 经
> `resolvePromptParts` `prompt.ts:157-191` 变 file part)。fragment 进上下文**只靠模型自己发 Read**——纯 lazy Read。

---

## 2. 自动压缩(整段 head 摘要)

**何时触发(v1,主运行路径)**——两处自动入口:

- **post-turn 检查**(`prompt.ts:1161-1168`):每轮 assistant 结束后,`compaction.isOverflow({tokens: lastFinished.tokens, model})` 为真 → `compaction.create({auto:true})`。
- **流中溢出**(`prompt.ts:1320-1328`):provider 流中返回 `"compact"`(上下文超限信号)→ `compaction.create({auto:true, overflow:true})`。
- **手动**:`/compact`(`command.execute.before` 钩子 `prompt.ts:1460`,`task.type==="compaction"` 分支 `prompt.ts:1149-1159`)。

**溢出阈值**(`packages/opencode/src/session/overflow.ts`):

```
isOverflow = count >= usable(input)         // overflow.ts:22-34
count      = tokens.total || (input+output+cache.read+cache.write)   // :32
usable     = model.limit.input ? max(0, input - reserved)            // :17-19
              : max(0, context - maxOutputTokens)                      // (无 input limit 时)
reserved   = cfg.compaction?.reserved ?? min(20000, maxOutputTokens)  // :8,14-16
```

- **绝对阈值,非百分比**(对比 Claude Code 的 ~92%)。150K 模型 → 约 130K 即触发(取决于 `maxOutputTokens`)。
- `cfg.compaction?.auto === false` 关闭(`overflow.ts:28`)。
- 触发量 = **整次请求 token 估计**(system + history + tools),经 `Token.estimate(JSON.stringify(...))`(`compaction.ts:216-222`)。
- 摘要模型:`"compaction"` agent 的 model,否则用户消息的 model(`compaction.ts:364-367`)。

**压缩做什么**(`compaction.ts:224-275 select`):把 history 切成 **head(摘要)+ tail(原样保留)**:

- tail = 最近 `tail_turns` 轮(默认 `DEFAULT_TAIL_TURNS = 2`,`compaction.ts:32`),受 token 预算约束
  (`preserveRecentBudget = cfg.preserve_recent_tokens ?? min(8000, max(2000, 25%·usable))`,`compaction.ts:33-34,116-121`)。
- head = 更早的全部消息 → `serialize`(`compaction.ts:55-86`)喂摘要器,**工具输出截断到 `TOOL_OUTPUT_MAX_CHARS=2000`**(`compaction.ts:30,52-53`)。
- 摘要模板(core `compaction.ts:16-46`,固定 Markdown:Objective/Important Details/Work State[Completed/Active/Blocked]/Next Move/Relevant Files),
  输出上限 `SUMMARY_OUTPUT_TOKENS=4096`(core `compaction.ts:15`)。
- 压缩后历史重排为 `[压缩 user 标记, 摘要 assistant, ...保留 tail, continue user]`(`message-v2.ts:521-572 filterCompacted`)。

**v2 差异**(core runner):触发点 `packages/core/src/session/runner/llm.ts:215`(`compactIfNeeded` 在每次 LLM 调用前);
阈值 `core/compaction.ts:225-236`(`estimate > context_limit - max(output_limit, buffer=20000)`);
tail 改为按 token 保留 `DEFAULT_KEEP_TOKENS=8000`(core `compaction.ts:13`)。逻辑同形。

---

## 3. prune(只清工具输出,每轮跑)

`compaction.prune`(`compaction.ts:279-323`),**每个 loop 迭代末尾跑**(`prompt.ts:1338`):

- 仅当 `cfg.compaction?.prune === true` 启用(`compaction.ts:281`)。
- 从最新消息**倒序**扫工具 part,累计其输出 token;**保护最近 `PRUNE_PROTECT=40000` token 的工具输出**(`compaction.ts:29,307`)。
- 跳过最近 2 轮(`compaction.ts:296-297`),遇到已压缩的旧工具输出即停(`compaction.ts:304`)。
- **`PRUNE_PROTECTED_TOOLS = ["skill"]`**(`compaction.ts:31,303`):**skill 工具输出永不被 prune**。
- 仅当可 prune 量 > `PRUNE_MINIMUM=20000`(`compaction.ts:28,314`)才实际清(置 `part.state.time.compacted`,清空输出文本)。
- **只清工具输出文本**,不碰 USER 消息、system、命令壳体。

> ⇒ **prune 治不了「壳/fragment 太长」**——它们不是工具输出。prune 真正帮 mgh-* 的是回收**确定性脚本的大 stdout**
> (`list_*` 分页、`discover_controls` 产物),这正是 R5.3(b)「stdout=JSON 严格分流 + 摘要 + 分页」与 `--orch-budget-bytes` 的杠杆。

---

## 4. skill 能否被「自动淘汰」?(承 §0 结论 3)

**不能按步骤淘汰,且比 fragment 更难 prune。** skill 机制存在且完整(`packages/core/src/skill.ts`、
`packages/opencode/src/skill/`、`SkillTool` `tool/skill.ts:12-70`):

- skill **列表**(name+desc)每轮在 system(`system.ts:98-110`)。
- skill **body** 仅在模型调用 `skill` 工具时进上下文,作为**工具结果**(`skill.ts:46-61` 包 `<skill_content>`)。
- 该工具结果**受 prune 保护**(`PRUNE_PROTECTED_TOOLS=["skill"]`),只有整段压缩(head 摘要)才能消化它。
- 无 `paths:` 作用域自动加载(`skills.paths` 仅指发现目录,`v1/config/skills.ts:6-8`;不按路径触碰触发)。

**对 mgh-* 的含义**:把「早期 step 内容」塞进 skill 以期「用完被压缩丢掉」——**反向**:
① skill body 受保护、比 lazy-Read fragment 更持久;② skill 列表常驻每轮 system;③ 还要新增 skill 发现/分发成本。
**正确范式是现状的 fragment 懒加载**(见 §5)。

---

## 5. 那 mgh-* 的「fragment 用完自然老化」到底怎么实现?

不需要任何特殊机制——`REQUIRED SUB-SKILL: Use <fragment>` 的 lazy-Read **本身**就是「加载一次 → 老化 → 压缩时摘要」的模型:

```
轮次     SYSTEM(每轮重派生)            HISTORY(累积,受压缩/prune 管)
─────    ─────────────────────         ─────────────────────────────────
 1       env+AGENTS+mcp+skills-list    [U] /mgh-init 壳体(parse-args+表+SUB-SKILL 指令)
 2       同上(壳不在)                  [U](Read orchestrator-discipline)  ← 编排器发 Read
 3       同上                           [U](Read init-stage-flow)          ← 早期 step 内容
 4..k    同上                           [tool] list_steps/discover/list_* stdout(受 prune 回收)
 k+1..   同上                           [tool] 更多 fan-out 结果 ──────▶ 累积增长
 ~130K   同上                           ⚡ 触发压缩 → head(含早期 step 那次 Read)被摘要
```

- 早期 step 的 fragment Read 出现在**第 3 轮的 USER 文本**,之后被后续工具结果堆压、**自然老化入 head 中段**——
  这正是期望行为(编排器后期不再需要它;`resume_state.py` 是磁盘真相源,见 R5.4)。
- 到下一个 ~130K 压缩点,它随 head 一起被摘要——**无需 step-aware 淘汰**。
- **它不是每轮 system 开销**(§1 表),所以「它在 history 里驻留到压缩」不构成每轮税。

⇒ `init-stage-flow` fragment(`harden-mgh-init-shell-budget` D1/D2)是**正确且最优**的载体:
单次 lazy Read、自然老化、磁盘兜底。**不**需要为它引入 skill。

---

## 6. 对 R5.6 预算模型的修正(承 §0 结论 1)

`tools/measure_prompts.py` 是**磁盘文件大小估算器**(`measure_prompts.py:107` 对各文件 `mid_tokens` 求和),
**不是运行时上下文足迹模型**。把它当「shell + fragments 同时驻留每轮 system」相加,会得到**反真实的过约束**
(如 `init-stage-flow(~4500) + orchestrator-discipline(~2466) = ~6991`,看似无空间留给壳——但三者从不同时是每轮 system 开销)。

R5.6 的 5,000 tok 壳上限**仍成立**,但**根据是**:
1. **lost-in-the-middle**(U 形注意力):壳是触发轮的**首条 USER 消息**——primacy 区,模型最可靠的行为指令源;
   越短越突出、关键动作(如 `.active` 哨兵)越不易落中段衰减区。
2. **防松散迭代再膨胀**:硬上限本身是回归护栏交付物。
3. 经验:结构良好的 mgh-* 壳自然落 ~4.5–5K。

**不成立/应弱化的**:「编排器分发足迹 = shell + 所有 fragments 求和 ≤ 8,000」——
该 8,000 把**非同时驻留**的文件按磁盘大小相加,**与 §1 的运行时模型矛盾**。应改为:
- 壳 ≤ 5,000(磁盘 + 触发轮 USER 项,真约束)。
- fragment:按「单次 Read 轮的尺寸」逐个评估(结构是否良好),**不强制求和 ≤ N**。
- 若要一个「防回归」的总盘子上限,标注其**根据是磁盘大小防漂移**,而非运行时叠加占用。

详见 [`docs/review-prompt-length-budget-150k.md`](review-prompt-length-budget-150k.md) §2.1 与本次修订新增节。

---

## 7. 何时回查本文件 + 复核清单

**触发查阅**:设计/改任何 `mgh-*` 壳或 fragment 时算尺寸;考虑「用 skill 省上下文」;
解释「为何 fragment 不会每轮烧 token」;评估压缩何时会吃掉某段历史;设计 `--orch-budget-bytes`/prune 杠杆。

**复核清单**(机制会随 opencode 版本变;改本文件前必跑):
- [ ] 溢出阈值仍在 `overflow.ts:22-34`(`isOverflow`/`usable`,`reserved=min(20000,...)`)。
- [ ] 触发点仍在 `prompt.ts:1161-1168`(post-turn)与 `1320-1328`(流中)。
- [ ] prune 保护常量仍在 `compaction.ts:28-31`(`PRUNE_MINIMUM/PROTECT`、`PRUNE_PROTECTED_TOOLS=["skill"]`)。
- [ ] 命令壳仍走 `prompt.ts:1432-1451`(USER parts,非 system);system 组装仍在 `1257-1269`。
- [ ] 摘要模板/上限仍在 core `compaction.ts:16-46` + `SUMMARY_OUTPUT_TOKENS=4096`。
- [ ] 仍无 fragment/include 自动内联(`resolvePromptParts` `prompt.ts:157-191` 仅处理 `@file`/`@agent`)。

> 数据点(本次核实,2026-08-12):opencode `mgh-init` 壳 9,224 mid tok / 259 行;`orchestrator-discipline` 2,466 mid tok / 54 行。
> 行号引用 opencode 源;token/行引用本仓 `tools/measure_prompts.py`。
