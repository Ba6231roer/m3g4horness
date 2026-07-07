# Design — harden-mgh-sast-orchestration-discipline

> 承 `proposal.md` 的五层,与 `harden-mgh-init-orchestration-discipline`(archive)**同构**。
> 给关键决策的**选择 / 理由 / 备选(否决)**,可证伪。R3 简练:不贴长代码,用 `文件:行号` 索引。

## Context

`/mgh-sast` 与 `/mgh-init` 是同一代零依赖重写,但**只固化了 mgh-init 的编排纪律**。mgh-init 经
`harden-mgh-init-orchestration-discipline`(archive)落地了:三条 `NEVER` 明线、扇出枚举脚本
(`list_clusters`/`list_scout_batches`/`list_rule_jobs`)、合法瞄一眼(`describe_artifact.py`)、
边界 `--check`、运行时 hook(`block_adhoc_scripts.py`,`MGH_INIT_ACTIVE` 域)、subagent sanctioned-tools
白名单。`/mgh-sast` **停在硬化之前**:

- `releases/claude-code/commands/mgh-sast.md:8` 仅说 "You are the orchestrator ... by spawning stage
  subagents and running deterministic scripts",**无**「非写成代码」明线、**无** `NEVER` 条款。
- s4 "fan out per chunk"(:41,:56)、s6 "fan out + majority vote"(:42)——**无 `list_chunks.py` /
  `list_verify_jobs.py`**,编排器拿 pending 只能手挖 `checkpoints/s4_candidates.json` /
  `s5_filtered.json` → 写 `_prep_chunks.py`(填真实脚本空洞,与 mgh-init FD1 同形)。
- 确定性阶段 `prefilter.py`/`dedup.py`/`emit_sarif.py` **无 `--check`**(R5.9 缺)。
- `block_adhoc_scripts.py:67` 仅 `MGH_INIT_ACTIVE=="1"` 激活——**mgh-sast 运行域零护栏**。
- `core/prompts/stages/s1-survey.md` 等无 Sanctioned-tools 白名单(subagent 可 `Write .py` / `py -c`)。

**mgh-sast 全流程 fan-out 逐步骤 I/O(本变更覆盖范围;🔴=本次新增固化,✅=已固化)**:

| Step | 输入 | 执行 | 输出 | 风险 | 固化 |
|---|---|---|---|---|---|
| scope | repo+diff/path/pkg | `sast-scope-resolver`(+`diff_seed`/`expand_scope`) | scope_manifest | 单 subagent,非 fan-out | 🔴 `--check`(次要) |
| s1 survey | in_scope | `sast-survey` | s1 结构快照 | 低 | ✅ |
| s2 threat-model | s1 | `sast-threat-model` | s2 threats | 低 | ✅ |
| s3 decompose | s2 | `sast-decompose` | s3 chunks | 低 | ✅ |
| **s4 fan-out** | **s3 chunks** | per-chunk `sast-deepdive` | checkpoints/s4/<id> | 🔴 **无 pending 脚本/无 resume 过滤**;subagent 写脚本 | 🔴 `list_chunks` + 白名单 |
| s5 prefilter | s4 candidates | `prefilter.py` | s5_filtered | 边界无校验 | 🔴 `--check` |
| **s6 fan-out** | **s5 findings** | per-finding `sast-verify`(vote) | checkpoints/s6/<id> | 🔴 **无 pending 脚本** | 🔴 `list_verify_jobs` |
| s7 dedup | s6 verdicts | `dedup.py` | s7_findings | 边界无校验 | 🔴 `--check` |
| s8 chain | s7 | `sast-chain` | s8 chains | 低 | ✅ |
| s9 SARIF | findings | `emit_sarif.py` | report.sarif | 边界无校验 | 🔴 `--check` |

约束:R1(移植提示词正文非必要不改)、R2(零依赖)、R5.2/R5.3(编排器=宿主 agent + 扇出即脚本枚举
+ CLI I/O 契约)、R5.7(运行时 hook 交付物)、R5.9(边界 `--check`)、R5.10(分发纯净)。

## Goals / Non-Goals

**Goals:**
- mgh-sast 编排器与 subagent **永不**写一次性微脚本 / `py -c` 内省——工作清单、瞄结构、派生量各有
  合法出口(镜像 mgh-init FD1)。
- 闭合 s4/s6 扇出的 pending-list 不对称(新增 `list_chunks.py` / `list_verify_jobs.py`)。
- 确定性阶段(prefilter/dedup/emit_sarif)有 `--check` 边界校验(R5.9)。
- 兑现 R5.7:为 /mgh-sast #1 违例(微脚本内省)配运行时 hook(复用既有 hook,扩激活域)。
- 全程零新增运行时依赖;双壳镜像;回归测 + CLI lint。

**Non-Goals:**
- 不改 9 阶段算法 / 提示词正文 / SARIF schema;只收紧编排纪律 + 追加 sanctioned-tools overlay。
- 不为 `--repo-file` 批处理 rows 建 `list_batch_rows.py`(rows 是用户提供的文件、非产物,风险低;
  留 open question)。
- 不引入 tree-sitter / Semgrep / 任何 `pip install`。
- 不改 mgh-init 侧任何产物/脚本(仅扩 hook 激活域 + AGENTS.md 措辞)。

## Decisions

### FD1 — 编排器 = 宿主 agent + 三条 NEVER 明线(镜像 harden-mgh-init FD1)
**选择**:双壳 `mgh-sast.md` 顶部声明「编排器 = 宿主 agent,按本提示词用自身工具跑流水线,**非写成
代码**」;三条 `NEVER`(a) `Write` 任何 `.py`(大编排器 `mgh_sast.py` 或一次性微脚本 `py -c` 产物、
`_prep_chunks.py`、`_aggregate_verify.py`);(b) `Bash: py -c|python -c` 内省/重派生产物
(`import json`/`open(`/`load(` 读 `checkpoints/**`/`scope_manifest.json`);(c) `Read` 叶子 `.py` 源码。
**理由**:mgh-init FD1 已证「明线打错失败形状」是根因;sast 同代重写、同形失败,须落同一明线。
**备选(否决)**:只加措辞——mgh-init 历史证「效果一般」,MUST 配 FD3(填空洞)/FD5(hook)。

### FD2 — 扇出枚举脚本 `list_chunks.py` + `list_verify_jobs.py`(闭合不对称)
**选择**:两脚本各**镜像 `list_clusters.py`**。`list_chunks.py` 读 s3 产物的 `chunks[]` + 扫
`checkpoints/s4/*.done`,stdout `{repo,total,done,pending[],truncated}`,`pending[]` 每项
`{chunk_id,files,threat_id,hypothesis}`;`list_verify_jobs.py` 读 s5 产物 `findings[]` + 扫
`checkpoints/s6/*.done`,stdout `{total,done,pending[]}`,`pending[]` 每项 `{finding_id,file,line,
vuln_class}`。stderr 仅诊断;退出码 `0/1/2`;自定位 `sys.path`、utf-8、零依赖、任意 cwd。
**理由**:s4/s6 是 sast 仅有的真 fan-out tier(对标 mgh-init 的 T1/scout);无 pending 脚本 → 编排器
手挖 JSON / 写 `_prep_*.py`(填真实空洞,非瞎写)。
**备选(否决)**:通用 `list_pending.py --tier chunks|verify`——两 tier pending 项 shape 不同
(chunk / finding),通用化丢字段(承 mgh-init FD3 同论)。

### FD3 — 复用既有 `describe_artifact.py`(不重造)
**选择**:mgh-sast 编排器「瞄一眼产物结构」MUST 用 harden-mgh-init 已交付的 `describe_artifact.py`
(`--keys/--count/--sample/--shape/--field`),**不**为 sast 另建。
**理由**:describe 是跨产物通用反射,集中一个比每命令各建更 DRY(mgh-init FD5 同论)。
**备选(否决)**:sast 自建 `describe_sast_artifact.py`——重复、跨命令不一致。

### FD4 — 运行时 hook:泛化既有 `block_adhoc_scripts.py` 激活域(本变更最大杠杆)
**选择**:把 `block_adhoc_scripts.py:67` 的激活条件从 `MGH_INIT_ACTIVE=="1"` 扩为
`MGH_INIT_ACTIVE=="1" or MGH_SAST_ACTIVE=="1"`(**同一 hook、同一正则、同一白名单**);recipe 增列
sast 合法出口(`list_chunks`/`list_verify_jobs`/`describe_artifact`/脚本 stdout 字段)。mgh-sast 编排器
起步 `export MGH_SAST_ACTIVE=1`。`install.sh` 注入逻辑不变(hook 已由 mgh-init 注入、幂等)。
**理由**:R5.7「每个 mgh-* #1 违例 MUST 配 hook」;sast #1 违例 = 微脚本内省,与 init **同形**,
共享一个 hook 比双 hook 更 DRY、误伤面更小、维护更省。
**备选(否决①)**:新建 `block_adhoc_sast_scripts.py` + install 双注入——重复正则、双倍误伤面、
双份维护。**备选(否决②)**:不建 hook 仅靠 MD——mgh-init FD4 历史证「靠自觉效果一般」。
**风险**:recipe 同时含 init + sast 原语略长——只在命中时打印,可接受;双栏单测覆盖
(`MGH_SAST_ACTIVE` 下放行合法叶子、拦截内省/越权 Write)。

### FD5 — 确定性阶段 `--check`(R5.9)
**选择**:`prefilter.py --check <s5_filtered.json>`、`dedup.py --check <s7_findings.json>`、
`emit_sarif.py --check <report.sarif>`(或 findings 输入)。编排器跑完每步、进下一步前 MUST 校验;
失败 fail-loud(退出码 2)→ 回退重跑。校验项 = 各产物 well-formed(s5 每条 finding 有 file/line/
vuln_class/source_ref/sink_ref;s7 去重后无明近_dup;s9 SARIF 合法 2.1.0 + 每条 run.invocation)。
**理由**:泛化 mgh-init `assemble_rules.py --check` 范式(承 openspec validate-at-boundary);防破损
产物静默传到下游。
**备选(部分采纳)**:scope 脚本(`diff_seed`/`expand_scope`)`--check` 标次要 task / open question
(scope_manifest 已有 `unresolved[]` 披露,边界校验收益小于三确定性阶段)。

### FD6 — subagent sanctioned-tools 白名单(L4;R1 合规的追加 overlay)
**选择**:`core/prompts/stages/s1-survey.md`/`s2-threat-model.md`/`s3-decompose.md`/`s4-system.md`/
`s6-verify.md`/`s8-chain.md`(LLM 阶段)各**追加**一段 Sanctioned-tools(Read/Glob/Grep 自由、脚本
仅 `chunk_sources.py`(若需切片)、`NEVER Write .py` / `py -c`、输入产物为终态);双壳
`agents/sast-*.md` hard constraints 同步。
**R1 合规**:vvah 移植正文(`Source: vvaharness/...` 以下)**一字不改**;sanctioned-tools 段是
**追加**的纪律 overlay(与 harden-mgh-init 对 `init-*.md` 的处理同形、有先例)。
**理由**:subagent 实读 `stages/*.md`,壳改不到;prompt + 壳双声明是双重防线(mgh-init FD8 同论)。
**备选(否决)**:仅改壳——subagent 读 stages/*.md,壳改无效。

### FD7 — 双壳信息流固化(L1):刚性三元组 + 终态声明
**选择**:`mgh-sast.md` 编排流每个 fan-out 步骤改 `[输入产物::字段] → script/subagent →
[输出产物::字段]`(s3 chunks→s4、s5 findings→s6);声明 `s5_filtered.json`/`s7_findings.json` 为
**终态**(不再二次聚合);implementation-intention 句式(需工作清单→`list_chunks`/`list_verify_jobs`;
瞄结构→`describe_artifact`;派生量→产出者 stdout)。
**理由**:mgh-init FD1+FD2 证刚性三元组 + 终态声明能消除 doubt 时刻的手搓动机。
**备选(否决)**:保留现有散文式编排流——doubt 时刻无 shape 指引 → 反射写 `py -c`。

### FD8 — AGENTS.md 措辞 sharpen(L5)
**选择**:R5.7「当前兑现」行从 `/mgh-init` 扩为 `/mgh-init + /mgh-sast`(`block-adhoc-scripts.py`
覆盖双命令 #1 违例);R5.9「当前覆盖」行增 `prefilter`/`dedup`/`emit_sarif` `--check`。R5.2/R5.3
已是命令通用(确认覆盖 sast,无需改条文)。
**理由**:R5.7/R5.9 的「当前兑现/覆盖」清单是可检交付物,须反映 sast 落地。
**备选(否决)**:不改 AGENTS.md——「当前兑现」行与实际脱节,误导后续维护者。

## Risks / Trade-offs

- **hook 激活域扩展**:既有跨项目侵入的增量。缓解:同一 hook、幂等、`MGH_SAST_ACTIVE` 作用域(非
  sast 运行域零噪声)、`--no-enforce-hook` opt-out 不变;双栏单测覆盖 `MGH_SAST_ACTIVE` 路径。
- **hook 正则误伤合法调用**:缓解:白名单(`core/scripts`/`tests`/`tools`/`releases/*/hooks`)+
  双栏单测(放行 `py <path>/prefilter.py`、拦截内省/越权 Write)——既有测试已验证 init 域,sast 域
  共享同一正则。
- **追加 sanctioned-tools overlay 误伤 R1**:缓解:tasks 显式标注「只追加、不改 vvah 正文、溯源注释
  保留」;回归测 + 人工审。
- **脚本数增多**:新增 2(list_chunks/list_verify_jobs)。可接受(承 `list_clusters`/`list_scout_batches`
  已验形态)。

## Migration Plan

- **无 schema/数据迁移**:全部 additive(新脚本、新 `--check`、hook 激活域扩展、追加 overlay)。
- **hook 幂等**:二次 install 不重复加 matcher;`--no-enforce-hook` opt-out 不变。
- **版本号**:任一 `.md`/脚本改动 bump(承 R5.8)。
- **回滚**:opt-out 可完全回退 hook 层;移除新脚本/`--check`/overlay 即回退;AGENTS.md 措辞收紧无回退风险。

## Open Questions

- `--repo-file` 批处理 rows 是否需 `list_batch_rows.py`?倾向**非目标**(用户文件、非产物、风险低);
  实施时若发现编排器手挖 csv 再评估。
- scope 脚本(`diff_seed`/`expand_scope`)是否加 `--check`?倾向**次要 task**(scope_manifest 已有
  `unresolved[]` 披露);实施时评估收益。
