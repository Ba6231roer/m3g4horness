# Design — harden-mgh-init-orchestration-discipline

> 承 `proposal.md` 的五层。本文件给关键决策的**选择 / 理由 / 备选(否决)**,可证伪。R3 简练:
> 不贴长代码,用 `文件:行号` 索引。

## Context

`/mgh-init` 经 `fix-mgh-init-stability` / `improve-mgh-init-llm-discovery` /
`fix-mgh-init-cluster-fanout` / `fix-mgh-init-rules-purity` 五次迭代后,确定性脚本
(`plan_scout`/`merge_scout`/`list_clusters`/`chunk_sources`/`assemble_rules`)与 R5.2/R5.3
规则已就位,但真机大仓首跑(`new_issue.txt` 记 10 点)仍大量出现**编排器与 subagent 写一次性
微脚本**(`py -c "import json…"`、`_prep_scout_batches.py`、`_aggregate_scout.py`)去内省/重派生
已有产物。

当前确定性事实:

- `grep -niE "py -c|内省|introspect" AGENTS.md` = **0 命中**——R5.2/R5.3 未覆盖微脚本内省形态。
- R5.2 具名反例是 `mgh_init.py`(大编排器);agent 写 `py -c`/`_prep_*.py` 时**不模式匹配成「写编排器」**,
  明线不触发。即规则**打错了失败形状**(前五次治的是「读源码 / 错 flag / 大编排器」,真机是「微脚本内省」)。
- `grep add_argument core/scripts/plan_scout.py` 实证:无 `--checkpoints`——`plan_scout` 产**全部**
  batch、不按 `.done` 过滤。T1 扇出有 `list_clusters.py`(resume-aware pending),**scout / T3 扇出无对应物**
  → 编排器拿「待跑清单」只能自挖 JSON → `_prep_scout_batches.py` 是填真实脚本空洞,非瞎写。
- 全仓 `find . -name hooks.json` = **空**——R5.7「能 hook 就别靠自觉」明写却从未给头号违例建 hook。
- 仅 `assemble_rules.py --check` / `list_clusters.py` 是边界校验/工作清单;openspec validate-at-boundary
  范式**半采纳**。

三条结构性原因(规则写了、agent 不照做):① 契约是「参考」非「运行时」(shell 12KB 过密,R5.6 禁 `@`
内联 → doubt 时刻未被指向 contract → 反射写 `py -c` 瞄一眼);② 无「合法瞄一眼」原语(Read 整份贵,
唯一便宜手段=写脚本);③ 无运行时强制(0 hook)。

**init 全流程逐步骤 I/O + 不稳定审计**(本变更覆盖范围;✅=已固化,⚠️=有空洞,🔴=本次新增固化):

| Step             | 输入                        | 执行                             | 输出                           | 风险                                               | 固化                          |
| ---------------- | ------------------------- | ------------------------------ | ---------------------------- | ------------------------------------------------ | --------------------------- |
| i0 自检            | repo                      | `discover_controls` 计数         | stderr 进度+大仓建议               | 低                                                | ✅                           |
| i1 discover      | repo+cache                | `discover_controls.py`         | candidates+clusters+skeleton | list keys/len/sample「理解结构」(#4)                   | 🔴 `--check` + describe     |
| i1b survey(opt)  | clusters                  | `init-survey`                  | i1_enriched(advisory)        | 当 T1 输入                                          | ✅ 已标 non-fatal              |
| 3b-plan          | skeleton+candidates       | `plan_scout.py`                | scout_plan + stdout 摘要       | 重读/重切批(#1,#6)                                    | 🔴 暴露 regex_known_count(#5) |
| 3b-fanout        | scout_plan::batches       | per-batch `init-scout`(+chunk) | checkpoints/scout/<id>       | 🔴 **无 pending 脚本/无 resume 过滤**;subagent 写脚本(#7) | 🔴 list_scout_batches + 白名单 |
| 3b-merge         | checkpoints/scout/*       | `init-scout-merge`             | scout_candidates             | 重写聚合 `_aggregate_scout`(#8)                      | 🔴 声明终态                     |
| 3b-audit(opt)    | scout 拒绝项                 | `init-scout-audit`             | audit.json                   | 低                                                | ✅                           |
| 3b-foldin        | cand+scout+audit+clusters | `merge_scout.py`               | 改写 cand+追加 clusters          | 低                                                | ✅                           |
| 4 T1 枚举          | clusters+ckpt/t1          | `list_clusters.py`             | stdout pending(resume)       | —                                                | ✅ **模板**                    |
| 4 T1 扇出          | pending[]                 | `init-induct`(+chunk)          | checkpoints/t1/<id>          | subagent 写脚本                                     | 🔴 白名单                      |
| 5 T2             | 全部 t1                     | `init-synthesis`               | inventory                    | 边界无校验                                            | 🔴 validate_inventory       |
| 6 T3 扇出          | inventory cats            | `init-rulewriter` per cat      | rules+ckpt/t3                | 🔴 **无按-cat pending**                            | 🔴 list_rule_jobs           |
| 6b assemble/lint | rules                     | `assemble_rules.py --check`    | AGENTS.md 块/lint             | —                                                | ✅ **范式源头**                  |
| 7 T4             | rules                     | `init-rules-consistency`       | in-place+ckpt/t4             | 改坏                                               | 🔴 lint 复跑                  |
| 8 i4             | 全部                        | 宿主写                            | manifest+report              | 漏披露                                              | 🔴 schema-check             |

约束:R2 零运行时依赖;R5.1 双壳 flag 逐字镜像且 `--help` 即契约;R5.2 编排器=宿主 agent、确定性
叶脚本经 Bash、禁 `.py`/禁 Read 源码(本变更**扩展到禁微脚本/禁 py -c**);R5.3 叶脚本自包含 +
stdout=JSON/stderr=进度 + 退出码 `0/1/2`;R5.6 壳 ≤500 行;R5.8 任一 `.md`/脚本改动 bump 版本号 + 回归。

## Goals / Non-Goals

**Goals:**
- 编排器与 subagent **永不**写一次性微脚本 / `py -c` 内省——工作清单、瞄结构、派生量各有合法出口。
- 闭合 scout / T3 扇出与 T1 的 pending-list 不对称(新增 `list_scout_batches.py` / `list_rule_jobs.py`)。
- 给「先理解结构再动手」反射一个合法出口(`describe_artifact.py`)。
- 兑现 R5.7:为 #1 违例(微脚本)交付 PreToolUse hook(双壳)。
- 泛化边界 `--check`(R5.9):每 stage 产物有校验,编排器跑完一步校验再进下一步。
- 全程零新增运行时依赖;双壳镜像;回归测 + CLI lint 通过。

**Non-Goals:**
- 不改成簇/归纳算法、不动 T2 及之后的语义;scout 只往候选集加料的既有契约不变。
- 不重构既有脚本(只加 `--check` / 暴露派生字段),不改既有产物磁盘 schema(全 additive)。
- 不引入 tree-sitter / Semgrep / 任何 `pip install`。
- 不抽通用 `list_pending.py`(留 FD3 备选,本次按 tier 各一个)。

## Decisions

### FD1 — 失败形状错配是根因(非规则不够)
**选择**:把 R5.2 明线**扩展到一次性微脚本**,具名真实反例(`py -c "import json"` / `_prep_*.py`)。
**理由**:`new_issue.txt` 10 点全是微脚本内省/重派生,而既有规则反例是 `mgh_init.py`(大编排器),不
模式匹配。bright-line 须落在 agent 真实会写的形状上(承 superpowers `persuasion-principles.md`
Authority 原则:绝对语言 + 具名反例消除「这是不是例外?」)。
**备选(否决)**:只收紧措辞——历史已证「效果一般」(动机与机会都还在),MUST 配 FD3(填空洞)/FD5
(合法瞄一眼)/FD4(hook)。

### FD2 — 借鉴映射(superpowers / openspec → 本仓)
**选择**:Authority+Commitment+Implementation-intentions(superpowers `persuasion-principles.md`,
Meincke 2025 N=28000,33%→72%)+ skill 内置脚本调用范式(`systematic-debugging/find-polluter.sh`)
+ 确定性 hook(`hooks/hooks.json`)+ validate-at-boundary(openspec `validate`)。
**理由**:superpowers 实证 discipline-enforcing 场景 bright-line 最有效;openspec validate 是每边界
强制 schema 的成熟范式(本仓半采纳)。
**备选(否决)**:纯自创纪律框架——重造已证有效的轮子,且偏离「可参考项目」既定方向。

### FD3 — 补 scout / T3 扇出的 pending-list 脚本(闭合不对称)
**选择**:新增 `list_scout_batches.py` + `list_rule_jobs.py`,各**镜像 `list_clusters.py`**(
读产物 + 扫 `*.done`,stdout `{total,done,pending[],...}`,退出码 0/1/2)。
**理由**:T1 已有 `list_clusters.py` 作成功先例;`plan_scout.py` 无 `--checkpoints`(grep 实证)→
编排器只能自挖 `scout_plan.json`(issue #1/#6);T3 同理无按-category pending。
**备选(暂缓)**:通用 `list_pending.py --tier scout|t1|t3`——DRY 但各 tier pending 项 shape 不同
(batch / cluster / category),通用化会丢字段或加 `--fields` 复杂度。三脚本若现明显重复,后续再抽
helper(非本次范围)。

### FD4 — hook 跨项目注入的边界(本变更最大风险面)
**选择**:`install.sh` 向目标项目 `.claude/settings.json` 的 `PreToolUse` **幂等追加** matcher,在
`MGH_INIT_ACTIVE=1` 运行域内:拦 `Bash: py -c|python -c` 含 `import json`/`open(`/`load(`/`.json` 的
内省,拦 `Write: *.py` 不在白名单(`core/scripts`/`tests`/`tools`/`releases/*/hooks`)。命中 fail-loud
(退出码 2)+ stderr recipe。非运行域直接放行。`--no-enforce-hook` opt-out;`--opencode` 无 PreToolUse
能力时 warn + 跳过(fail-soft,承 R5.8)。
**理由**:兑现 R5.7「能 hook 就别靠自觉」;superpowers `hooks.json` 是确定性闭环范式;用户已选「做
hook,双壳都注」。正则须双栏单测(放行合法叶子调用、拦截内省/越权 Write)。
**备选(否决)**:不建 hook,仅靠 L1/L2/L4/L5——历史证「靠自觉效果一般」,且 R5.7 已立规却未交付。

### FD5 — describe_artifact.py 形态(合法瞄一眼)
**选择**:独立通用脚本 `--in <json> [--keys] [--count] [--sample N] [--shape] [--field a.b.c]`;
`--count` 对 wrapper dict 额外 warn(防 `len(wrapper)=3` 误判)。
**理由**:「先理解结构」是稳定反射,无法靠禁令消除,正解是给便宜正确的 sanctioned 出口;describe 是
跨产物通用反射,集中一个比每脚本各加 `--describe` 更 DRY、更易教。
**备选(否决)**:每脚本加 `--describe`——6+ 脚本各加一套,且不跨产物。

### FD6 — 派生量作为 stdout 字段(消除「自己算」)
**选择**:下游可能 list keys/len/sample 才能得到的派生量,MUST 由产出者 emit。`plan_scout.py` stdout
+ scout_plan 增 `regex_known_count`(内部 `regex_files` 已算于 `plan_scout.py:109`);`discover_controls.py`
stdout 补 `big_files`/`unresolved_count`。
**理由**:issue #5 agent 写脚本算「222 个 regex_known」,因 `plan_scout` 内部已算却未暴露。原则:
「下游常查量」= 产出者应直接 emit。
**备选(否决)**:留给下游 `describe_artifact --field` 现算——仍多一步且语义不清;emit 更省、更确定。

### FD7 — stage 边界 --check(R5.9,openspec validate 范式)
**选择**:每 stage 产物的产出者暴露 `--check`(或独立 validator),编排器跑完一步、进下一步前 MUST
校验;失败 fail-loud(退出码 2)回退重跑。覆盖 discover/plan_scout/merge_scout/validate_inventory/
assemble_rules(既有)。
**理由**:泛化 `assemble_rules.py --check` 既有范式;openspec validate-at-boundary 成熟;进一步降
「自己 list keys 确认结构」的动机(校验已保证 shape)。
**备选(部分采纳)**:独立 `core/validators/*.py` 目录——仅跨多产物的综合校验(inventory)用独立
validator;单产物 check 优先下放产出者(DRY、零重复解析)。

### FD8 — subagent sanctioned-tools 白名单
**选择**:每个 `core/prompts/stages/init-*.md`(+ 双壳 `agents/init-*.md`)加 Sanctioned-tools 段:
Read/Glob/Grep 自由、脚本仅 `chunk_sources.py`、NEVER `Write .py`/`py -c`;输入产物为终态,NEVER 用
代码变换/重派生。`init-scout.md`「Use your tools freely」改为受限自由。
**理由**:issue #7/#10 subagent 也写脚本;prompt + 壳双声明是双重防线。
**备选(否决)**:仅改壳——subagent 实际读的是 stages/*.md,壳改不到。

### FD9 — 层间关系与最小可发布集
**选择**:一次性交付五层 + R5.9;tasks 按依赖排序、每条独立可验收。
**理由**:措辞(L5)单独「效果一般」(历史);L1 消除 doubt 动机、L2 消除剩余动机+填空洞、L4 治
subagent、L3 消除机会、R5.9 防漂移——五者互补,缺一则动机/机会仍存。
**备选(暂缓)**:分两变更(先 L1/L2/L4/L5+R5.9,后 L3)——用户已选同变更内交付 hook,不分。

## Risks / Trade-offs

- **hook 跨项目侵入**:install 往目标 `.claude/settings.json` 注 matcher。缓解:幂等追加(不覆盖用户
  既有 hook)、`MGH_INIT_ACTIVE` 作用域(非运行域零噪声)、`--no-enforce-hook` opt-out、opencode 降级
  warn+跳过(fail-soft)。回退:opt-out 可完全回退 hook 层,产物仍靠 L1/L2/L4/L5+R5.9。
- **hook 正则误伤合法调用**:缓解:白名单(`core/scripts`/`tests`/`tools`/`releases/*/hooks`)+ 双栏
  单测(放行 `py <path>/discover_controls.py`、`py tests/`、`py -c "print(1)"`;拦截内省/越权 Write)。
- **措辞单独无效**:历史实证 R5.2/R5.3「效果一般」——故本变更必配 L2/L3,非纯文档。
- **脚本数增多**:新增 3(list_scout_batches/list_rule_jobs/describe_artifact)+ 各 `--check`。可接受
  (承 `list_clusters.py` 已验形态);通用 `list_pending` 抽象留后续评估。

## Migration Plan

- **无 schema/数据迁移**:既有产物磁盘格式不变,全部 additive(新 stdout 字段、新 `--check`、新脚本、
  新 hook)。下游 `mgh-sra`/`mgh-blst`/未来 mgh-sast 控制入口消费的 `controls_inventory.json` 不变。
- **hook 注入幂等**:二次 install 不重复加 matcher;`--no-enforce-hook` 可完全不注入。
- **AGENTS.md R5.x 改动是收紧**(加明线 + R5.7 升交付物 + 新增 R5.9),不放松任何既有约束,无回退风险。
- **版本号**:任一 `.md`/脚本改动 bump(承 R5.8)。

## Open Questions

- **通用 `list_pending.py` vs 每 tier 一个**(FD3):本次选每 tier 一个(承 `list_clusters` 形态);
  实施时若三脚本重复显著,重估抽象。
- **opencode PreToolUse 真机能力**(FD4):设计已备降级路径(warn+跳过);实施时需在真实 opencode
  环境探测其 hook 能力,确认降级触发条件。
