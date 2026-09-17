# mgh-init 上下文预算优化分析(权威版)

> ⚠ **2026-08-12 重要增补 — 目标重定向(读本文件前先读本节)**:后续维护者澄清**真实目标是「提准确度 / 防跑偏」,
> 不是「省 token」**(见下方「§A 准确度优先(真实目标)」)。本文件 §1–7 原是在「预算」框架下写的,**仍作为预算机理参考有效**,
> 但**决策以 §A 为准**。核心翻转:① 归档 drift-fix spec 审计显示**大部分跑偏根因不是压缩**(12/14 是契约/path/shape/dicipline gap);
> ② R5.4 disk-truth 让压缩**可存活但有 gap**(进度可重派生,但「执行纪律 HOW」不在盘上 → 压缩后 same-session 仍可能跑偏);
> ③ 因此**头号准确度杠杆 = 补全 R5.4**(`resume_state.py`/`list_steps --step` 带 per-step 纪律),**不是** 拆 prompt / 不是 subagent 隔离。
> subagent 独立 150K 属性**机制成立但非决定性**(见 §A.4)。

> 面向维护者。**目的(原预算框架)**:在「用户可用大模型只有 150K 上下文」的硬约束下,把 mgh-init 整条流水线的**运行时上下文足迹**
> 压到稳态安全区,并消除关键一次性动作(`.active` 哨兵)的 skip-risk。本文件**取代** `docs/review-prompt-length-budget-150k.md`
> (后者已废,见 §0);后续 mgh-sra / mgh-srr / mgh-sast / mgh-ut-init 的预算优化复用本文件方法论与杠杆表。
>
> **机制全部经 opencode 源码核实**(核实时点 2026-08-12,源码路径相对 `C:\DEV\opencode`)。完整机制 + 源码行号见
> [`docs/opencode-context-mechanics.md`](opencode-context-mechanics.md)(已于本次纠错,Read 输出**受 prune 回收**)。
>
> 测量源:`py tools/measure_prompts.py`(stdlib,R2;`mid_tokens` 工作值)。**token 是估算区间,决策锚字符/行(确定性)**。

---

## §A. 准确度优先(真实目标:防跑偏,不是省 token)

> 本节由准确度目标的后台 agent(aa6dd51141adb1192)回灌。**决策优先级高于 §1–7 的预算框架**。

### §A.1 核心翻转:跑偏根因 ≠ 压缩(归档 spec 审计)

维护者原假设「大部分跑偏由压缩丢关键信息导致」。agent 抽样审计**归档 drift-fix spec 的明文根因**:
**口径说明**:审计对象 = `openspec/changes/archive/` 下**修跑偏/修 bug** 的 fix/harden spec;**排除优化型 spec**(如 `harden-mgh-init-shell-budget`——它是 prompt 预算优化、非 drift-fix,虽其 harm #1 提到「更早触发自动压缩」)。实际审计 14 个,分布如下。

| 根因类别 | 数量 | 代表 spec(全部经 proposal 明文核实) | 压缩导致? |
|---|---|---|---|
| **契约/规格 gap**(缺 `clusters.md`、缺 `list_*`、缺 `--check` validator、缺 `.failed` marker、缺 scout-incomplete-gate) | ~6 | `fix-mgh-init-cluster-fanout`、`improve-mgh-init-partial-fanout-tolerance`、`fix-mgh-init-scout-stranding`、`fix-mgh-init-merge-scout-missing-file`、`harden-mgh-init-slice-and-tool-pinning`、`fix-mgh-init-orch-tempfile-leak` | ❌ |
| **LLM 输出 shape drift**(T1 嵌套 `controls[]`、T3 YAML 围栏、schema 字段泄漏) | ~3 | `fix-mgh-init-t1-record-schema-drift`、`fix-mgh-init-opencode-agents-md-noise`、`fix-mgh-init-stability` | ❌ |
| **纪律/覆盖 gap**(R5.2 瞄准错形状、缺 sanctioned 原语、超时韧性) | ~3 | `harden-mgh-init-orchestration-discipline`、`harden-mgh-init-shell-timeout`、`improve-mgh-init-no-interrupt-under-pressure` | ❌ |
| **压缩相关**(已核 proposal 明文含 compaction) | **2** | `harden-mgh-init-context-resilience`(Why 首条直指「`/compact` 与自动压缩丢提示词」+ Layer 4 compaction-aware;**但它是多层根因**,无确定性 resume 是另一主层)、`harden-mgh-init-context-budget`(编排器整读 426KB `t1_pending.json` → 溢出触压缩;根因是无 per-unit materialization,压缩是**后果**非**因**) | △(压缩相关但非单一主因) |

⇒ **「压缩是跑偏主因」不被归档 spec 支持**(14 个里仅 2 个压缩相关、且均为多层根因中的一层)。大部分跑偏是**确定性 gate / 契约 / path / shape** 问题——由 R5.9 `--check` validator + R5.3(b) 绝对路径 pinning 逐步关闭,**与是否压缩无关**。
⇒ **「用 subagent 隔离防压缩」是在治次要病因**,且对 scout-stranding / schema-drift / partial-fanout 这类会**把失败藏进不可见 subagent**,反而劣化。

### §A.2 R5.4 disk-truth 的真实 gap(跑偏的真机制)

R5.4(`AGENTS.md:145-160`)让压缩**可存活**(进度 `step`/`tiers`/`next_action` 从磁盘重派生),**但不保证压缩后 same-session 执行正确**:

| 盘上有 | 盘上**没有**(压缩后 same-session 丢失 → 跑偏源) |
|---|---|
| `step`/`tiers`/`next_action`/`run_config`/`init_manifest`/checkpoints/`.done`/`.failed` | **执行纪律 HOW**:三条 NEVER、fan-out 刚性三元组、`.failed` ack 配方、绝对路径逐字透传、**T1→T2 shape-gate**(`validate_t1_records --strip-bom`+`--check`)、scout-incomplete-gate |

压缩 head 摘要模板(`core/compaction.ts:18-40`:`## Objective`/`## Important Details`/`## Work State`/`## Next Move`/`## Relevant Files`)只保留「做了什么」,**不保留「规则是什么」**。
`resume_state.py` stdout(**已核 `resume_state.py:33-41`**)实为 **7 字段**:`{target, format, step, resumable, tiers{discover,scout,t1,t2,t3,t4}, next_action, notes}`——**含 `step`+`tiers`+`next_action`,但不 emit 纪律配方** → 压缩后编排器知道**在哪步**,不知道**该步的执行纪律**。
这正是 `2026-08-10-fix-mgh-init-t1-record-schema-drift` 类 bug 的温床:T1→T2 gate 被压缩摘要丢掉 → 编排器忘了跑 → schema 漂移静默进 T2。

### §A.3 头号准确度杠杆:补全 R5.4(让压缩无损)

**option A(推荐)**:`resume_state.py` / `list_steps --step` 带 **per-step `discipline_reminders[]`**(该步的 gate + 路径配方 + 适用 NEVER)。
压缩后一次磁盘读 = 同时恢复「在哪步」+「怎么执行」。**确定性、disk-backed、model-independent、覆盖全部 stage、抗任意压缩强度**。
- 已核 `list_steps.py --step <id>` 现输出 `{step, kind, script, script_abs, invocation, input, output}`(`list_steps.py:196-204`,调用行 + I/O 契约)——**缺纪律子集**。option A = 扩 `--step` 输出携带 per-step 纪律(`--check` 闸门形状、scout-incomplete-gate、T1→T2 gate、NEVER 反例)。
- option B:压缩事件触发重 Read `orchestrator-discipline.md`(操作纪律,弱模型难强制)。
- option C(设计既有首选):compaction 风险时 clean-stop + 新 session 重 shell(完整恢复纪律)——已在 `orchestrator-discipline.md` Re-entrancy §3,加固即可。

### §A.4 subagent 独立 150K:机制成立但非决定性

- **机制确认**:subagent 有独立 150K(`task.ts:156-213`),只回 last text part(`task.ts:213`),内部工作不占父上下文。维护者的核心假设**机制正确**。
- **但放大它不决定性**:① 编排器上下文增长主项是 ~68 枚举 stdout + ~68 bounded ack(**非** subagent 内部工作,那已隔离);② 典型 mid-size 仓(~68 fan-out)编排器稳态 ~30K,**远低于 130K,根本不压缩**——压缩只在大仓(~1000+ 单元)或重 debug 交错才咬;③ 「stage-driver 回收 1 摘要而非 N ack」确能省 ~15K,但需 `subagent_depth≥2`(`task.ts:111`,默认 1,用户配置、本仓不控)+ 受信强模型 driver;④ **env 不回传**(`MGH_INIT_ACTIVE`/`MGH_TARGET` 从 child bash 不回父)→ step 0 **无法完全委派**,编排器仍须自己 export。
- ⇒ subagent stage-driver 是**真但窄**的杠杆(仅 3b/4 stage、仅大仓、仅 opt 条件全满),**排在补全 R5.4 / 哨兵确定性 / validator / 劝开 prune / clean-stop-resume 之后**(见 §A.5)。

### §A.5 准确度目标下的杠杆排序(决策以此为准)

| 排序 | 杠杆 | 治 | 为何最高/低 | 状态 |
|---|---|---|---|---|
| **1** | **补全 R5.4**(`resume_state`/`list_steps --step` 带 per-step 纪律,§A.3 option A) | 跑偏 | 唯一治「压缩后 same-session 丢执行纪律」真 gap;确定性、model-independent、覆盖全 stage | **待 propose(最高优先)** |
| 2 | 哨兵确定性副作用(`write_runconfig.py` + `resume_state --check`,旧 §4 方案 4) | 哨兵 skip | 唯一治 B;prompt-independent | 待 propose(跨 5 命令) |
| 3 | per-stage `--check` validator(R5.9 扩覆盖) | 跑偏 | **这是历史上关闭 12/14 drift bug 的东西** | 持续 |
| 4 | 劝/助开 `compaction.prune:true`(旧 §4 方案 1a/1b) | 压缩 | opt-in 用户压缩问题**消失**(稳态 ~50–70K);v1-only | 待落地(一行披露 + 可选插件) |
| 5 | clean-stop-resume on compaction 风险(既有首选路径,加固) | 跑偏 | 新 session 重 shell 完整恢复纪律;廉价 | 加固 |
| 6 | 缩壳 + 拆 fragment(旧 §4 方案 2/3,R5.6) | 预算(非准确度) | 预算收益,对准确度边际 | 已部分做(init 壳已 2.9K) |
| 7 | **stage-driver subagent(3b/4)**(维护者假设 4,准确度版) | 压缩 | 真但窄:~15K 省、仅大仓、需 depth≥2+受信 driver、env 不回传 | **仅当 1–6 不足时** |
| — | 「搬 stage 正文进 subagent」(budget 版 H4) | — | **否决**(预算+准确度双败;藏漂移、增分发字节) | 不做 |

### §A.6 对旧 §4 方案 2/3 决断的影响 + 维护者拍板(2026-08-12)

旧 §4 把「方案 2(`--step` 按需)vs 方案 3(按阶段拆 fragment)」当**预算**问题决断。**在准确度目标下头号杠杆是补全 R5.4(§A.3),方案 2/3 降为预算层次要项**:
- 它们的「非同时驻留」是**预算**收益,不是准确度收益。
- `list_steps --step` 的**准确度**价值,只在它携带纪律子集时兑现 → 那时它就是 **§A.3 option A(补全 R5.4)的载体**,不是预算裁剪。

**维护者拍板(2026-08-12)**:prompt/预算层**走方案 2B**(规格见下方 §B);**准确度头号杠杆(补全 R5.4,§A.3)另立 proposal、另会话推进**——两条路径**分离**,§B 只管预算层。本文件已涵盖所有关键信息(§A 准确度结论 + §1–7 预算机理 + §B 方案 2B 规格);新会话 proposal 直接读本文件即可,无需依赖本会话对话。

---

## §B. 方案 2B 规格(prompt/预算层拍板形态,2026-08-12)

> 维护者拍板的 prompt/预算层方案。**与准确度头号杠杆(§A.3 补全 R5.4)正交、分离**——§B 不承担准确度目标,只做预算层的「非同时驻留」。
> 注意:§B 用 `list_steps.py --step` 取调用行 + I/O 契约,**不**让它携带纪律子集(那是 §A.3 的事;若两路径合并,见 §B.5)。

### §B.1 `list_steps.py --step <id>` 现状(已 codegraph 核实,2026-08-12)

`core/scripts/list_steps.py:60-169,212-249`。`--step <id>` 输出**单 step** 的:
```
{step, kind, script, script_abs, invocation, input, output}
```
- `invocation` = `py <script_abs> <cli_args>`(确切调用行,`_invocation` `:183-187`)。
- `input/output` = `{artifact, shape, path_pattern}`(I/O 契约)。
- `kind ∈ {bash, subagent}`;闭集 `--step`,未知 id 退出码 2(`:236-242`)。
- 已覆盖 step:`not-started/discover/survey/scout/resolve/t1/t2/t3/assemble/t4/merge/done`。

⇒ **机械层(调用行 + I/O 契约)已现成、零新代码**。

### §B.2 `list_steps --step` 的 gap(相对 `init-stage-flow.md` 每步正文)

| step | `--step` 给的 | `init-stage-flow` 里**额外**有的(纪律/承重防御,§B.4 落到按步 fragment) |
|---|---|---|
| `t1` | `list_clusters.py` 调用行 + I/O | **scout-incomplete-gate**(scout 启用未完→退出码 2)、分页 `shrunk`、`failed` ack、oversize `::shard-<n>` 切片 |
| `discover` | `discover_controls.py` 调用行 | `MGH_TARGET` 从 `repo` 字段重设、`--check` 闸门、`--resume` 跳过语义 |
| `scout` | `list_scout_batches.py` 调用行 | 批数涌现公式、`needs_slice`/切片、scout-merge `needs_reduce` 分支、级联失效 |
| `t3` | `list_rule_jobs.py` 调用行 | `assemble_rules --check` lint 形状、`failed` ack |
| (各 subagent step) | `kind:subagent`,无 invocation | 该 subagent 的 fan-out 边界、`input_path`/`checkpoint_path` 透传、`failed` 终态 |

⇒ `--step` 给**调用契约**(机械层,适合脚本 stdout、R5.1 友好);纪律/闸门/反例(承重防御,承 R5.5⑤)**留给按步 fragment**——不让脚本「解释自身纪律」(避 R5.1 张力)。

### §B.3 方案 2B 形态(拍板)

**`list_steps.py --step`(现成,给调用行+I/O)+ 按步拆 `init-stage-flow.md` 为多 fragment(给纪律)+ resume 时只加载当前步**:

```
resume/压缩后编排器恢复路径:
  resume_state.py --target <t>          → stdout {target, format, step, resumable, tiers, next_action, notes}(7 字段,现成)
  list_steps.py --step <step>           → stdout {step, kind, script, script_abs, invocation, input, output}(调用契约,现成)
  Read init-stage/<step>.md             → 该步纪律(gate/NEVER 反例/fan-out 边界;现成 step 枚举,见 §B.3.1)
  执行完该步 → 重跑 resume_state.py 拿下一步 → 循环
```

- **非同时驻留(当前步 only,非 all-remaining)**:编排器**只加载当前 step 的单个 fragment**(实测平均 ~0.4K/步,见 §B.3.2),非整份 init-stage-flow(4.8K)。默认用户 + opt-in 用户**都**拿到这条预算收益。
- **调用契约零 drift**:`invocation` 由脚本单一真相生成,不再依赖 fragment 手写调用行(治 D 盘根漂移类历史 bug 的同源风险)。
- **不增脚本「解释自身纪律」负担**:纪律仍在 prompt fragment(R5.1 友好)。

### §B.3.1 step 枚举映射(init-stage-flow 0–8 ↔ list_steps/resume_state enum)

**决策(消歧,评审 agent 标记的关键缺口)**:fragment 文件名 + `stage_flow_files[]` **统一 key 在 `list_steps.py`/`resume_state.py` 的 step 枚举**上
(`resume_state.py:46`: `not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`)——因为 resume_state 就 emit 该枚举,
`--step` 也吃该枚举,三者同 key 零重映射。**init-stage-flow 的 0–8 编号只是文档结构,不是运行时枚举**。

| init-stage-flow 块 | 运行时 step(fragment 文件名 = `<step>.md`) | 归属 |
|---|---|---|
| step 0(bootstrap:run_config+哨兵+codegraph) | **`bootstrap`**(壳自持,不在运行时枚举) | 加载一次;含哨兵/run_config/MGH_TARGET 配方 |
| step 1(--merge) | `merge` | — |
| step 2 discover | `discover` | — |
| step 3 survey(opt) | `survey` | — |
| step 3b scout | `scout` | — |
| step 3c resolve(opt) | `resolve` | — |
| step 4 T1 **+ step 4b gate** | **`t1`**(4b 的 T1→T2 shape-gate **并入 t1 fragment**,同文件) | gate 是 t1 的收尾 |
| step 5 T2 | `t2` | — |
| step 6 T3 | `t3` | — |
| step 6b assemble/lint | **`assemble`**(清单里独立 step,非并入 t3) | `list_steps.py` 已有独立 `assemble` 条目 |
| step 7 T4 | `t4` | — |
| step 8 manifest/report+收尾 | `done` | 含哨兵 rm 配方 |

⇒ **fragment 集 = `init-stage/{bootstrap, discover, survey, scout, resolve, t1, t2, t3, assemble, t4, merge, done}.md`(12 文件)**。
`stage_flow_files[]` = **当前 step 的单个** `init-stage/<step>.md` 绝对路径(§B.4#2)。

### §B.3.2 尺寸(拆分后实测基线 2026-08-12)

`init-stage-flow.md`(拆分前 4,769 mid / 130 行)拆 12 文件后实测(per-file `mid_tokens` / 行):

| fragment | mid | 行 | fragment | mid | 行 |
|---|---|---|---|---|---|
| bootstrap | 793 | 27 | t2 | 349 | 14 |
| discover | 330 | 19 | t3 | 395 | 16 |
| survey | 136 | 13 | assemble | 263 | 17 |
| scout | 1,031 | 31 | t4 | 96 | 11 |
| resolve | 553 | 21 | merge | 75 | 10 |
| t1 | 860 | 23 | done | 364 | 15 |

磁盘合计 **5,245 mid**(12 文件,≤ ~10,000 防漂移 lint ✓;纯迁移 + 12 个头部注释,无内容膨胀)。
单次加载**平均 ~437/步**,重步 scout(1,031)/t1(860),轻步 merge(75)/t4(96)——**非同时驻留**,编排器只加载当前步
单个 fragment,替代原整份 4,769。两壳 `mid_tokens`:**claude 3,048** / **opencode 2,986**(各 ≤ 5,000 ✓)。

### §B.4 实现要点(供新会话 proposal 直接采用)

1. **拆 `core/prompts/fragments/init-stage-flow.md`(4.8K/130 行)→ `fragments/init-stage/{bootstrap,discover,survey,scout,resolve,t1,t2,t3,assemble,t4,merge,done}.md`**(实测平均 ~0.44K/步,重步 scout 1,031 / t1 860,见 §B.3.2 尺寸表)。保留头部溯源注释(承 R1;D1 既有约定)。两壳共用单文件集(承 D2);`install.sh:53,78`(`cp -r core/ → mgh-core/`)自动镜像新目录,无需改 install。
2. **`resume_state.py` stdout 增 `stage_flow_files[]`**:值 = **当前 step 的单个** `init-stage/<step>.md` 绝对路径(`Path.resolve()`,非 step 0、非 all-remaining)。`Path.resolve()` 绝对、逐字透传给编排器(承 R5.3(b) fan-out 路径契约)。当前 stdout 7 字段基座见 `resume_state.py:33-41`,为**增量**字段。
3. **壳 SUB-SKILL 指令改**(现位置 `releases/claude-code/commands/mgh-init.md:41-49`、opencode 镜像同处):从「Use init-stage-flow(整文件)」→ 「`resume_state` 拿当前步 → `list_steps --step` 拿调用行 → Read `stage_flow_files[]`(当前步 fragment)」。壳体进一步瘦身(去掉整文件加载语义)。
4. **R5.4 resume 兼容**:磁盘真相源不变(`.mgh-init/` 产物 + `.done`/`.failed`);`stage_flow_files[]` 是 resume 衍生量、非持久态。
5. **保真度(承报告「⚠ 裁剪前提」)**:拆分**只迁移、不删**;scout-incomplete-gate / T1→T2 shape-gate / 级联失效等承重反例**必须**随对应 step 进 fragment,NEVER 丢。
6. **溯源**:`list_steps.py` 由 `2026-08-01-improve-mgh-init-deterministic-step-manifest` 创建;改 `--step` 输出/`_STEPS` 枚举前先读该 spec 的 step-manifest 契约(承 R1/R5.1)。

### §B.5 与 §A.3(补全 R5.4)的关系——两路径分离,可后合并

| | §B(本节,预算层) | §A.3(准确度头号) |
|---|---|---|
| 目标 | 预算(非同时驻留) | 准确度(压缩后 same-session 恢复纪律) |
| 改 `list_steps --step`? | ❌ 用现状(调用行+I/O) | ✅ 扩它携带 `discipline_reminders[]` |
| 改 `resume_state.py`? | ✅ 增 `stage_flow_files[]` | ✅ 增 `discipline_reminders[]` |
| 拆 fragment? | ✅ 按步拆 | 独立(可不拆) |

**两路径正交、可并行 propose**。若未来合并:`list_steps --step` 既给调用行又给纪律子集 → `discipline_reminders[]` 直接来自按步 fragment 的纪律段(单一真相),§B 的拆分成为 §A.3 的数据源。**但当前分离推进**,互不阻塞。

---



## 0. 与旧报告的关系(为何取代)

`review-prompt-length-budget-150k.md` 的**结论大部分仍对**(5,000 tok 壳上限、lost-in-the-middle、保真度优先裁剪),
但**两处理论地基需要纠正**:

1. **§9「分发足迹 ≠ 运行时叠加占用」的重接地,方向对、收益归因错**。它说「fragment 是单次 lazy Read 的 USER 项、非每轮 system 税」——
   **事实为真,但与收益无关**。fragment 的真收益是「内容从 USER 文本区(只压缩回收)迁到工具输出区(**prune 每轮可回收**)」,
   详见本文件 §1.2 与机制文档 §5(已纠错)。
2. **旧报告隐含把「缩壳」与「哨兵可靠性」捆绑**——其实是两个正交问题(见 §2 病根/药对照)。缩壳治不了哨兵 skip-risk;
   哨兵治本靠脚本侧确定性副作用(§5 方案 C),与 prompt 尺寸无关。

⇒ 旧报告的**实测数据表(§3 各命令实测)**仍有引用价值(磁盘大小基线),但**预算模型与归因以本文件为准**。

---

## 1. 问题背景

### 1.1 硬约束:150K 窗口

用户可用的最强模型(典型 GLM/Claude 等长上下文模型)上下文窗口 ~150K。opencode 不是到 150K 才动作——
**自动压缩阈值 ≈ `input − reserved`**,`reserved = min(20000, maxOutput)`(`overflow.ts:8-34`)→ 150K 模型**约 130K 即触发压缩**。
压缩是整段 head 摘要(head 工具输出截断到 2K、user/assistant 文本摘要成 ≤4096 tok blob),**有损**——一旦编排器关键纪律
(fan-out 路径、`--check` 闸门、哨兵配方)落进被摘要的 head,弱模型恢复后可能失向。

⇒ 目标不是「不超过 150K」,而是「**稳态足迹远低于 130K,尽量推迟/避免压缩**;且即便压缩,disk(`resume_state.py`)能无损重派生进度」。

### 1.2 关键机制非对称(承重,本次纠错的核心)

opencode 有**两种**降上下文手段,内容落在哪一区决定它的命运:

| 区 | 内容形态 | 回收机制 | 何时回收 |
|---|---|---|---|
| **USER 文本区** | 命令**壳体**(触发轮的一条 USER 消息) | 仅**压缩**@~130K(head 摘要) | 很晚、且有损 |
| **工具输出区** | Read 输出 / Bash stdout / Grep / **Agent(subagent `task`)结果** / fragment | **prune 每轮检查**(`compaction.ts:279-323`)**仅当 `compaction.prune:true`**;否则只靠压缩 | **早**(若 prune 开):滚出尾部 40K 保护窗即清;另压缩时截断 2K |

> **纠错 1(2026-08-12)**:旧机制文档把「Read 输出 / fragment」标为不受 prune——**错**。源码核实:prune 遍历**所有**
> `type === "tool"` part(`compaction.ts:301`),仅跳过 `PRUNE_PROTECTED_TOOLS=["skill"]`(`:31,303`)。Read 工具 id `"read"`
> (`read.ts:69`)、subagent 工具 id `"task"`(`task.ts:24`)均**不在保护集 → 受 prune 回收**。**唯一真不受 prune 的是 USER 文本(命令壳体)**。
>
> **⚠ 纠错 2(2026-08-12,承重,改变全局结论)**:`compaction.prune` **默认 `false`**(`packages/core/src/v1/config/config.ts:154-156`)。
> prune 仅当用户 opencode 配置显式 `compaction.prune: true` 才跑(`compaction.ts:281`)。**默认用户:prune 从不运行**,
> 工具输出区(Read/fragment/subagent/stdout)**单调累积到 ~130K 压缩**,与 USER 文本区同命运(只是压缩时前者截断 2K、后者进摘要)。
> ⇒ 「区迁移」收益**仅对 opt-in 用户成立**;对默认用户,区迁移**几乎无运行时收益**(都要等压缩)。
> 另:**v2 core runner 无 prune**(`packages/core/src/session/compaction.ts` 无 `PRUNE_*`)→ prune 杠杆是 v1-only,未来 opencode 升级可能失效。

**这一非对称是杠杆支点,但被 prune 默认关「打折」**:

```
prune=true(opt-in 用户):  把内容从 [USER 文本区] 迁到 [工具输出区] = 真收益(更早被 prune 回收,不必等压缩)
prune=false(默认用户):   区迁移 ≈ 无运行时收益(两区都单调累积到压缩;唯一差别是压缩时工具输出截断 2K、USER 文本进摘要)
```

⇒ **对默认用户,真正稳态省 token 的只有「缩壳」**(USER 文本区、每短 1 tok 都真省,且壳是 primacy 区)。
拆 fragment / 区迁移 / subagent 化对默认用户主要是「压缩时少进 2K 截断 vs 摘要 blob」的差别 + 「分散非同时驻留」,**远非旧报告暗示的运行时红利**。
prune-friendly fan-out(§4 方案 1)的 ROI 因此**从「高」降为「opt-in 用户才高、默认用户低」**——核心动作变成「**建议/强制用户开 prune**」。

- 缩壳(9,361 → 2,916)的收益 = 壳体本身变短(primacy 区更突出 + 壳体是 USER 文本、只能压缩回收,故每短 1 tok 都真省)。
- 拆 fragment 的收益 = **stage 流正文从「若 inline 则嵌入 USER 壳体(只压缩回收)」迁到「Read 输出(prune 可回收)」**——这是真收益,
  且收益机制不是旧报告说的「非 system 税」(那为真但与收益无关)。
- fan-out 的 stdout / subagent 结果**天然在工具输出区**——prune 本应每轮回收它们;若它们没被回收,是 fan-out 纪律问题(见 §3.3、§4)。

### 1.3 当前实测(mgh-init,2026-08-12 复测,非采信旧报告)

| 产物 | mid tok | 行 | 形态 | 落区 |
|---|---|---|---|---|
| claude 壳 `mgh-init.md` | 2,916 | 91 | USER 文本(触发轮) | USER 文本区(只压缩) |
| opencode 壳 `mgh-init.md` | 2,853 | 84 | 同上 | 同上 |
| `orchestrator-discipline.md` | 2,466 | 54 | Read 输出(lazy) | 工具输出区(prune 可回收) |
| `init-stage-flow.md` | 4,769 | 130 | Read 输出(lazy) | 工具输出区(prune 可回收) |
| 磁盘合计(壳 + 2 fragment) | **10,151** / **10,088** | — | — | — |

磁盘合计 ~10K 超旧的 ~10K 防漂移 lint 线,**但磁盘大小 ≠ 运行时占用**(三者不同区、不同回收命运)。真约束是运行时稳态足迹,见 §3。

---

## 2. 两个正交问题(必须分开治)

```
问题 A:运行时上下文预算(稳态足迹压低 / 推迟压缩)        问题 B:关键一次性动作(.active 哨兵)的可靠性
  └─ 杠杆在「区迁移 + prune-friendly fan-out + 缩壳」        └─ 杠杆在「哨兵 = 脚本确定性副作用」(与 prompt 尺寸无关)
  └─ 旧报告把这俩捆绑 → 缩壳被包装成治 B,其实只治 A          └─ 治本 = write_runconfig.py 副作用 + resume_state --check 校验
```

| | 问题 A(预算) | 问题 B(哨兵可靠性) |
|---|---|---|
| 病状 | 多轮 fan-out 下足迹增长、早触压缩 | 弱模型漏写哨兵 → hook 静默失效、流水线仍跑完 |
| 病根 | **默认用户:工具输出区单调累积(prune 默认关)** + 壳过长 | 哨兵写入是「软依赖」(靠模型读懂并执行 prompt 文字) |
| 治标 | 缩壳(默认用户真省)/ 拆 fragment / 区迁移 | 哨兵 callout 前置(报告 §6.4,token 中性) |
| 治本(opt-in) | **开 prune**(`compaction.prune:true`)+ fan-out 已是 slim(§4 方案 1) | 哨兵 = `write_runconfig.py` 确定性副作用(§5 方案 C) |
| 治本(默认) | **缩壳 + 拆 fragment**(区迁移对默认用户收益打折,但仍是最可靠的)+ disk resume 兜压缩 | 同上 |
| 是否相关 | 互相独立 | 互相独立 |

⇒ **本文件的推荐方案分别给 A、B 各自的治本路径**,不再混为一谈。

---

## 3. 运行时足迹建模(prune 默认关 → 决定每条杠杆的真实 ROI)

### 3.1 两类 prune 用户,两套稳态(承 §1.2 纠错 2)

```
足迹 = [SYSTEM 块(每轮重派生,不累积)]                          ← 外部不可控(base ~8-15K + 目标 AGENTS + skills 列表)
     + [USER 文本区: 命令壳体(~2.9K,全程在,只压缩回收)]         ← 可控;只能靠「缩」;默认/opt-in 都真省
     + [工具输出区: fragments + fan-out stdout + subagent 结果]  ← 命运分裂:
            prune=true(opt-in): 每轮回收,稳态有界(纪律好 ≈ 40K 保护窗附近)
            prune=false(默认):  单调累积到 ~130K 压缩(与 USER 区同命运,仅压缩时截断 2K vs 摘要 blob)
```

### 3.2 fan-out 纪律体检(后台 agent 已核:已 uniformly slim,**无需改脚本**)

后台 agent(a814fb30)核:`list_clusters`/`list_scout_batches`/`list_rule_jobs`/`plan_aggregate` **全部**已 slim-on-stdout + fat-on-disk
(`--materialize`,`pending[]` 只携带路径/计数、不含候选体);`discover_controls`/`plan_scout`/`merge_scout` stdout 仅百字节级摘要;
subagent 结果是 `part.tool==="task"`(不在保护集 → prunable)。**没有任何脚本往 stdout 倒聚合 JSON**。

⇒ **关键结论**:fan-out 层**已经是 prune-friendly by construction**。没有脚本要改。`--orch-budget-bytes=64KB` 默认值经核**已在 40K-token
保护窗内**(64KB ≈ 16–25K tok),无需下调。编排器纪律(禁手挖整份 JSON、`describe_artifact --field` 瞄窄字段)已是 R5.3(b) 契约。

### 3.3 prune 触发算术(仅 opt-in 用户)

prune(`compaction.ts:279-323`)每轮检查:倒序扫 `type:"tool"` part,保护最近 `PRUNE_PROTECT=40000` tok、跳过最近 2 轮、可回收量 >
`PRUNE_MINIMUM=20000` 才清。opt-in 用户下一次典型 mgh-init(~70 subagent + 枚举)约在第 15–25 个 fan-out 处 prune 开始清旧页/旧 ack,
稳态护住 ~40K 窗口,**很可能整 run 不触压缩**。默认用户则相反:全累积,T2/T3 阶段触 ~130K 压缩,靠 disk resume(R5.4)存活。

### 3.4 当前足迹画像(按用户类型)

| 用户 | 壳体 | fragment | fan-out stdout/subagent | 稳态峰值 | 是否触压缩 |
|---|---|---|---|---|---|
| **opt-in(prune:true)** | 2.9K(全程) | 回收后≈0 | 回收后≈40K 窗 | ~50–70K | **大概率不触**(prune 护住) |
| **默认(prune:false)** | 2.9K(全程) | 累积到压缩摘要 | 累积到压缩截断 | **~130K 触压缩** | **触**(靠 R5.4 disk resume 存活) |

⇒ **默认用户是悲观情形**:稳态会触压缩。对它,真省 token 的只有「缩壳」(USER 区每短 1 tok 都真省,且 primacy 区);
拆 fragment/区迁移是「压缩时少进 2K 截断而非摘要 blob」+「非同时驻留」的次要收益。**所以默认用户的头号杠杆 = 缩壳 + 拆 fragment,
而非 prune-friendly fan-out**(后者对默认用户 ≈ 无用,因 prune 不跑)。

---

## 4. 推荐方案

> 排序 = **默认用户优先**(prune 默认关 → 缩壳/拆 fragment 是最可靠杠杆)+ opt-in 用户的额外红利。
> 每条标:治哪个问题(A 预算 / B 哨兵)、对哪类用户有效、运行时收益、成本、R5.x 风险。
> **方案 1 结论已由后台 agent(a814fb30)回灌;方案 5(stages-into-subagents = 用户假设 4)待 agent(ac9d8180)回灌。**

### 方案 1(治 A,**默认用户低 / opt-in 用户高**):prune-friendly fan-out —— 已是 by construction,核心动作 = 劝开 prune

**后台 agent 结论(已核)**:fan-out 层**已经是 prune-friendly**——`list_*`/`plan_aggregate` 全 slim-on-stdout + fat-on-disk,
`discover`/`plan_scout`/`merge_scout` 仅百字节摘要,subagent 结果 `part.tool==="task"`(prunable)。**没有脚本要改**,
`--orch-budget-bytes=64KB` 默认值经核已在 40K-token 保护窗内、无需下调。编排器纪律(禁手挖整份 JSON)已是 R5.3(b) 契约。

⇒ 「prune-friendly fan-out」**不是要做的事,而是已经做完的事**。真正可做的只有一条:

- **(1a) 劝/助用户开 prune**:在 mgh-init「Always disclose」+ README 加一行「**建议 opencode 配 `compaction.prune: true`**:
  开启后 fan-out stdout/subagent 结果/fragment 每轮自动回收,整 run 大概率不触压缩」。opt-in 用户据此从「~130K 触压缩」
  降到「~50–70K 稳态不触」——**这才是 prune 机制的全部红利**(仅对 opt-in 用户)。
- **(1b,可选)install 期自动开 prune**:R5.7 已有 opencode `.ts` 插件机制;可考虑 install 时注入一个插件把 `compaction.prune:true`
  带进目标项目(类比 `block-adhoc-scripts`)。**待 spike**(open question:插件能否改 compaction 配置)。
- **治**:A。**对默认用户收益**:≈ 0(prune 不跑)。**对 opt-in 用户收益**:高(推迟/避免压缩)。
  **成本**:低(1a 一行披露)~ 中(1b 插件)。**R5.x 风险**:低。**v2 风险**:**prune 是 v1-only**,v2 core runner 无 prune → 此红利未来可能消失。

### 方案 2(治 A,**默认+opt-in 都中 ROI**):stage 流按需工具化——**已被 §B 取代(2B = 2+3 合体,维护者拍板)**

**核心**:把 `init-stage-flow` 逐步正文从「预存的 Read 输出(4.8K)」改成按需获取——**调用契约走 `list_steps.py --step <id>`(现成 stdout),纪律正文走按步 fragment,resume 只加载当前步**。
完整规格见 **§B**(2026-08-12 维护者拍板形态),本节仅保留历史机理供参考:
- `list_steps.py --step` **已存在**(`orchestrator-discipline.md:24` 引用;输出 shape 已核实 = `{step,kind,script,script_abs,invocation,input,output}`,见 §B.1;**缺纪律子集** → 纪律留 fragment,见 §B.2)。
- 收益:**非同时驻留**(只加载当前步 fragment,平均 ~0.4K,非全 4.8K);opt-in 额外 prunable + 可再生成。
- **R5.x 风险**:低(纪律仍在 fragment,不让脚本解释自身纪律)。

### 方案 3(治 A,**默认+opt-in 都中 ROI**,低成本):按阶段拆 `init-stage-flow` —— **并入 §B(方案 2B 的文件拆分侧)**

**核心**:`init-stage-flow.md` 单文件(4.8K)→ 按 step 拆多文件 + `resume_state.py` stdout 增 `stage_flow_files[]`(当前 step 单文件)。
**已被 §B 吸收**:方案 2B = 方案 2(`--step` 给调用契约)+ 方案 3(拆 fragment 给纪律)的合体。实现要点(枚举映射 / 路径约定 / 尺寸)见 **§B.3.1–§B.4**。

### 方案 4(治 B,**唯一治本**,中成本):哨兵写入 = `write_runconfig.py` 确定性副作用

**核心**:把 `.active` 哨兵写入从「编排器 printf 提示词(软依赖)」改成 `write_runconfig.py` 的**确定性副作用**——脚本一跑哨兵必在。
`resume_state.py --check` 校验哨兵存在(缺 → fail-loud 退出码 2 + recipe)。

- 治**:B(唯一治本,与预算正交)。**运行时收益**:无关。**成本**:中(改 `write_runconfig.py` 写哨兵 + `resume_state --check` 校验,
  跨 5 命令——按 [[split-cross-cutting-openspec-changes]] 拆 foundation + per-command)。**R5.x 风险**:中(副作用须 idempotent + 干净停止 rm;
  哨兵 schema `{domain,target,out_roots[],v}` 不变)。
- **做完方案 4,「哨兵埋中段」skip-risk 从根消除**;方案 1–3 纯为预算。

### 方案 5(用户假设 4,stages-into-subagents):**已由 agent(ac9d8180)回灌 → 否决**

**核心**:把 mgh-init 各 stage(尤其 step 0 自检)搬进 stage-driver subagent,stage 正文随 subagent system 走,主 agent 只回收结论。

**机制 + 算术判定**(agent 已核 + 量化):
- subagent 结果 `part.tool==="task"`、**prunable**(同 Read/Bash)→ 把 stage 搬进 subagent **不把它移出工具输出区**,只是换一种方式进同一区。
  - **默认用户**:两路径都单调累积到压缩 → **H4 无稳态收益**(只换「压缩时 2K 截断 vs 进 USER 摘要 blob」的次要差别;而 init-stage-flow 本就是 Read 输出、已属 2K 截断桶,H4 不跨桶)。
  - **opt-in 用户**:两路径都在工具输出区、滚出 40K 窗即清 → **H4 与现状 lazy-Read fragment 打平,无独立优势**。
- **字节算术(agent 量化)**:拆成 8 个 stage-driver subagent → subagent defs ~8–11K(非 prune 的 agent 身份,每轮进 child system)+ 编排器增 ~1–1.6K spawn 指令(非 prune 的 USER 文本),删 init-stage-flow 4.8K。**磁盘净增 ~+4–8K mid tok,且几乎全在非 prune 区** → 对 opt-in 用户是**净退化**(把可 prune 的 fragment 换成不可 prune 的 subagent def)。
- **逐 stage 体检(0/8 有预算胜出)**:
  - **step 2 discover / step 4b / 6b**:body 极小(≤0.5K)或纯确定性 Bash,无正文可迁 → 退步。
  - **fan-out stage 3b/4/6**:LLM 工作已在 init-scout/induct/rulewriter 隔离;包装「循环控制」进另一层 subagent = 加层不隔离新工作 + 在 subagent def 里**复制**编排器纪律(分页/`.failed` ack/`--check` 闸门)→ **明显退步**。
  - **step 2 discover 的致命缺陷**:编排器须把 `MGH_TARGET` export 进**自己**的 env 以武装下游子树守卫;subagent export 的 env **不回传父** → 委派破坏 env 连续性契约。
  - **step 0 bootstrap**:唯一有「独立价值」的 stage,但**价值在可靠性(B)不在预算(A)**——见下。

**哨兵可靠性交互(治 B 角度)**:把 step 0 搬进 purpose-built `init-bootstrap` subagent(整份 job = 写 run_config+哨兵+codegraph)能让哨兵从「埋在 8 段流程的中段」变成「subagent 的首要任务」,**降低 in-prompt skip-risk**。**但**:这只是把 skip-risk **上移一层**——编排器新增软依赖「记得先 spawn init-bootstrap」,弱模型若忘了 spawn,哨兵/run_config/env **全没写**,比现状(至少编排器首动作是 `export MGH_INIT_ACTIVE=1`)更糟。⇒ **H4-at-step-0 是 attentional mitigation(让东西显眼),治本应是 structural mitigation(让东西自动)= 方案 4**(`write_runconfig.py` 副作用,prompt-independent、任意 inattention 等级都存活)。
另:env 不回传的硬约束使「subagent 拥有哨兵」目标本身就打折——编排器仍须在 spawn **前** `export MGH_INIT_ACTIVE=1`(否则 guard 在 bootstrap subagent 内休眠),即编排器仍拥有最可靠性敏感的 env 写。

**裁决**:**否决 H4 作为通用架构**。它是五个候选里 ROI 最低的:字节从可 prune 区迁到不可 prune 区(净增 ~4–8K),8 个 stage 0 个预算胜出,fan-out stage 明显退步,step 0 的可靠性价值被方案 4 完全支配。唯一可保留的极窄 spike:step 0 作方案 4 的**补充**(非替代)——但即便如此也由方案 4 主导。
**附带新发现**:`list_steps.py --step <id>` **已存在**(`orchestrator-discipline.md:24`;输出 shape 已核实 = `{step,kind,script,script_abs,invocation,input,output}`,见 §B.1)→ 方案 2(按需工具化)**已部分建成**,成本比预估低,且 H4 的边际价值进一步缩小(§B 方案 2B 已吸收该现成能力)。

### 丢弃:假设 3(拆 mgh-init 成多 session / 子任务)

**确认无价值**(用户已判,我复核机制后同意):
- mgh-init 已有 `resume_state.py`(R5.4)做跨 session/compact/crash 无损恢复(磁盘是真相源)——「拆 session 求存活」已被覆盖。
- 拆 session/子任务**倍增**哨兵 skip-risk(N session = N 次 step 0 哨兵写入机会)+ **倍增** shell/fragment 重载(每 session 重读)。
- step 0 自检**很便宜**(regex 文件计数,无 LLM);贵的 T1/T3 fan-out 才是 token 大头,且它们**已是** subagent 隔离上下文。
- ⇒ 拆 session 治不了 A 也治不了 B,反而劣化两者。

---

## 5. 杠杆对照表(给后续 mgh-* 复用;**默认用户**视角优先,因 prune 默认关)

> ⚠ **被 §A 覆盖标注(2026-08-12)**:本节是**预算框架**视图。**决策以 §A.5 为准**——准确度头号杠杆(补全 R5.4)本节未列,补一行于此(见末行);「拆 fragment / 区迁移」本节标「中」,§A 将其**降为预算项**(准确度收益仅经补全 R5.4 兑现)。

| 杠杆 | 治 | 默认用户收益 | opt-in 用户收益 | 成本 | R5.x 风险 | 适用 |
|---|---|---|---|---|---|---|
| **补全 R5.4**(`resume_state`/`list_steps --step` 带 per-step `discipline_reminders[]`,§A.3) | **准确度(跑偏)** | **高**(压缩后 same-session 恢复执行纪律,disk-backed) | 高 | 中 | 低 | **全命令,最高优先** |
| **缩壳**(壳 ≤5K) | A | **真省**(USER 区每短 1 tok 都省;primacy 区) | 同 | 低 | 低 | 壳 >5K 的命令(mgh-sra/srr) |
| **拆 fragment / 区迁移**(方案 2B,§B) | A | 中(非同时驻留,当前步 only) | 中高(prunable) | 低 | 低 | 有大段 inline 正文(init 已拍板 2B) |
| **prune-friendly fan-out**(方案 1) | A | **≈0**(prune 默认不跑) | **高**(整 run 不触压缩) | 低(劝开)~中(插件) | 低 | opt-in 用户;**v1-only** |
| **开 prune**(方案 1a/1b) | A | N/A(本身是开关) | **高**(解锁 prune 全红利) | 低~中 | 低 | 所有 opt-in 场景 |
| **按需工具化 `list_steps --step`**(方案 2,§B) | A | 中(非同时驻留 + 可再生成) | 中高(零预存 + prunable) | 低–中 | 低 | 线性序贯 stage 流 |
| **哨兵确定性副作用**(方案 4) | B | N/A(治可靠性) | N/A | 中 | 中 | 所有 mgh-*(5 命令) |

---

## 6. 行动顺序(建议;**默认用户视角优先**)

> ⚠ **被 §A 覆盖标注(2026-08-12)**:本节是**预算框架**行动顺序。**决策以 §A.5 为准**——准确度头号杠杆(补全 R5.4)置于最前,预算项(拆 fragment/缩壳)排在准确度之后。
> **认知翻转(预算层)**:prune 默认关 → 「prune-friendly fan-out 是治本高 ROI」对默认用户 ≈ 无用;默认用户真省 token 头号杠杆 = **缩壳 + 拆 fragment(非同时驻留)**;prune 红利仅 opt-in、v1-only。

1. **立即(本会话已做)**:纠错机制文档(Read 输出受 prune + **prune 默认关** + subagent `task` 可 prune)+ 本文档 §A/§B 落盘。
2. **头号(准确度,§A.3,待 propose)**:补全 R5.4——`resume_state`/`list_steps --step` 带 per-step `discipline_reminders[]`。压缩后 same-session 恢复执行纪律,防跑偏治本。
3. **次优先(治 A 预算层,§B)**:方案 2B——`list_steps --step`(现成)+ 拆 `init-stage-flow` 为按步 fragment + `resume_state` 增 `stage_flow_files[]`(当前步单文件)。规格见 §B.3–§B.4。
4. **并行(治 A,opt-in 高 ROI,低成本)**:方案 1a——mgh-init「Always disclose」+ README 加「建议开 `compaction.prune:true`」一行。
5. **治本(治 B,与预算正交,独立 propose)**:方案 4 哨兵确定性副作用——拆 foundation + per-command(承 [[split-cross-cutting-openspec-changes]])。
6. **复用**:把 §A.5 排序 + §5 杠杆表 + **prune 默认关**事实应用到 mgh-sra/srr/sast/ut-init(壳 5.1–5.5K 略超/贴线;
   主杠杆 = 补全 R5.4(准确度)+ **缩壳**(预算)+ 拆 fragment;劝开 prune 是 opt-in 红利)。

---

## 7. 不确定性 / 待回灌

- **方案 1b 可行性**:opencode `.ts` 插件能否在 install 期把 `compaction.prune:true` 带进目标项目(类比 block-adhoc-scripts)——待 spike。
- **方案 2 现状核实 → 已闭合(2026-08-12,codegraph 核实)**:`list_steps.py --step <id>` 输出 `{step,kind,script_abs,invocation,input,output}` = **调用行 + I/O 契约**,**不含**纪律子集(gate/NEVER 反例)。
  ⇒ 维护者拍板 **方案 2B**:`--step`(现成,给调用行)+ 按步拆 fragment(给纪律)+ resume 只加载当前步。详见 **§B**。原「方案 2 vs 3」决断已被 §B 取代(2B = 2+3 合体的预算层形态)。
- **方案 4 跨命令**:`write_runconfig.py` 是否存在于所有 5 命令、哨兵副作用是否破坏既有 idempotency——待核。
- **方案 5(H4,stages-into-subagents)已回灌 → 否决**:见 §4 方案 5。8 stage 0 个预算胜出,字节净增 ~4–8K(迁到非 prune 区),step 0 可靠性价值被方案 4 支配。**不推进**。
- **prune 未来**:opencode v2 core runner 无 prune;若未来默认翻 true 且移植 v2,方案 1 红利扩大;若 v2 落地无 prune,方案 1 价值缩。
- **claude-code 侧 subagent 结果 fate 未核**:H4 agent 只验了 opencode `task.ts:24`(`part.tool==="task"`,prunable);claude code 的 Task 工具结果 part 类型 + 是否有 prune 等价物**未源码核实**(claude code 压缩模型不同,~92% 阈值)。结论(subagent 结果无特权)大概率成立,但 claude 侧待补验。
