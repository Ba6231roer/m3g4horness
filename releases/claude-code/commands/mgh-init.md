---
description: Discover existing reusable security controls in a project (input-validation / data-masking / authentication / authorization / crypto / rate-limiting / csrf / audit-logging) and emit agent-consumable rules (opencode: concise AGENTS.md lazy index + per-category detail files under docs/security-controls/; claude: path-scoped .claude/rules/*.md). Three-tier isolation-first pipeline (deterministic discover → T1 per-cluster induct → T2 synthesis → T3 per-category rules → T4 consistency). --format claude|opencode required (structures differ, never mix). Supports --scope/--resume/--merge and large-file sharding. Findings are LLM-induced candidates needing human review.
allowed-tools: Read, Glob, Grep, Bash, Agent, Write, Edit
---

# /mgh-init — discover existing security controls → agent rules

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / Agent / Read / Write / Edit)把流水线**跑出来**,而非写成代码——确定性逻辑已在 `discover_controls.py` / `chunk_sources.py` / `plan_scout.py` / `merge_scout.py` / `assemble_rules.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,也不要另写 `.py` 去包装或重实现。claude 下 T3 直写 `.claude/rules/security-<cat>.md`,由 `assemble_rules.py --format claude --check` 做纯净性 lint(见步骤 6b)。

> **运行域 + hook**:`install.sh` 向本仓 `.claude/settings.json` 注入 PreToolUse
> hook(`block-adhoc-scripts`),在 `/mgh-init` 运行域内拦 `py -c`/`python -c` 内省、**一切脚本扩展名写入**
> (`.py`/`.ps1`/`.sh`/`.ts`/…;叶脚本 read-only)、**以及 resolved 目标未落入受信子树的 `Write`/`Edit`**
> (init 正向允许清单:`<target>/.mgh-init/**`/`.claude/rules/**`/`docs/security-controls/**`/`AGENTS.md`/
> 哨兵 `out_roots[]`;命中退出码 2 + stderr recipe 指向 `list_*` stdout 的 `checkpoint_path`)。编排器**起步先**
> `Bash: export MGH_INIT_ACTIVE=1` 标记运行域 + 写磁盘哨兵 `<target>/.mgh-init/.active`,并在 discover 后
> `export MGH_TARGET=<绝对 repo>`(供 hook 判树;缺失则该条降级放行)。opt-out = `install.sh --no-enforce-hook`
> (纪律仍由下方铁律 + 边界校验兜底)。守卫激活 = env **或** 磁盘哨兵(哨兵绕开 opencode「插件不继承
> mid-session env」的可靠性边界,见 `core/contracts/hooks/runtime-enforcement.md`)。

You are the **orchestrator** of the mgh-init pipeline. Carry it out by running the
deterministic leaf scripts (Bash) and spawning stage subagents (Agent). Shared assets
live at `.claude/mgh-core/` (mirrored from `core/`).

> **Output is LLM-induced, not confirmed. Controls are "existing", not "effective".**
> Human review required. State this in every summary.

## Parse arguments (validate BEFORE spending tokens)

- `--target <dir>` (default `.`)
- `--format opencode|claude` — **required** (mutex). Missing → error + STOP.
- `--out <path>` (claude default `<target>/.claude/rules`; opencode default `<target>/AGENTS.md`)
- `--scope path:<dir>|package:<pkg>|file:<glob>` + `--scope-mode defined|applicable` (default `defined`)
- `--language <lang>`, `--max-files <N>`, `--big-file-bytes <N>` (default 200KB), `--sample <N>` (default 8), `--progress-every <N>` (默认 1000), `--large-repo-threshold <N>` (默认 15000;超阈值则前置建议 `--scope`+`--merge`)
- `--include-dotfiles` (默认关;扫描点前缀路径 `.opencode`/`.claude`/`.codegraph`/`.github`/`.env`。默认跳过——tooling/VCS/IDE/build/config/索引 非一方业务代码;控制定义点落在 `.xxx` 内时传此 flag 纳入)
- `--resume` (skip units whose `.done` **or** `.failed` exists — both terminal) · `--rebuild-cache` (rebuild call graph)
- `--merge <partials-dir>` (merge multiple scoped runs; then STOP)
- `--skip-consistency` (skip T4) · `--config <profile>` (default `init`)
- `--no-scout` (skip LLM scout discovery; legacy regex-only behavior) · `--scout-budget <N>` (0=全量目标) · `--scout-batch-bytes <N>` (默认 96KB) · `--scout-batch-cap <N>` (默认 40) · `--scout-audit-pct <N>` (默认 15)
- **请求上下文预算**(`request-context-budget`,确定性边界强制每次大模型请求 ≤ 阈值;单位字节):`--max-unit-bytes <N>`(单 fan-out 单元物化输入上限,默认 192KB;oversize 簇切 `::shard-<n>`、scout 批/T3 category 标 `oversize`)· `--orch-budget-bytes <N>`(编排器单次请求可见的待办壳页上限,默认 64KB;超则自动分页收紧,stdout `shrunk:true`)· `--max-aggregate-bytes <N>`(聚合输入上限,默认 256KB;T2/scout-merge 经 `plan_aggregate.py` **硬阈值**——> 预算自动 map-reduce;T4 仍软边界 + `--scope`/`--merge` 回退;触发 + shard 数进 `boundaries[]`/`report.md`)
- `--no-codegraph` (skip optional codegraph enrichment; legacy behavior). codegraph 检测默认 `auto`:仅当 `<target>/.codegraph/` 存在**且** PATH 有 `codegraph` 才启用;`--no-codegraph` 或不可用 → 富化 off(行为等价于引入 codegraph 前)

**No actionable args / `--help`** → print the flag table and STOP (zero tokens).

## Orchestrator discipline(铁律)

编排器 = 宿主 agent,**不写代码**。确定性叶脚本经 `Bash` 执行;**NEVER `Read` 叶子 `.py` 源码进上下文**(报错看 stderr,不读源码)。

**硬边界(`NEVER`)**:(a) `Write` 任何 `.py`——大编排器(`mgh_init.py`)**或**一次性微脚本(`py -c` 产物、`_prep_scout_batches.py`、`_aggregate_scout.py`、`<run>_helper.py`);(b) `Bash: py -c|python -c` 去内省/重派生产物(`import json` / `open(` / `load(` 读 `.mgh-init/**`);(c) `Read` 叶子 `.py` 源码。

**implementation-intention(需 X → 触发器 Y,NEVER `py -c`)**——每个常被手搓的需求都有合法出口:
- **每步确切脚本路径 / 调用行 / IO shape** → `list_steps.py` stdout(或 `--step <id>` 单步);宿主前缀自动派生,**NEVER** 猜 `scripts/` vs `mgh-core/scripts/`、**NEVER** 漏宿主前缀;
- **工作清单** → `list_clusters.py`(T1)/ `list_scout_batches.py`(scout)/ `list_rule_jobs.py`(T3);
- **某 fan-out 单元的完整记录** → `list_* --materialize <inputs/<tier>>` stdout `pending[]` 每项的 `input_path`(绝对,subagent **自读**;≤ `--max-unit-bytes`);**NEVER** 整份读 `clusters.json`/`controls_candidates.json`/`scout_plan.json`/`controls_inventory.json`(编排器只装 slim 分页待办壳)、**NEVER** `py -c`、**NEVER** 把记录体内联塞进 subagent task(只透传 `input_path`);
- **某 fan-out 单元的输出路径** → `list_*` stdout `pending[]` 每项的 `checkpoint_path`(scout/T1)/ `rule_path`(T3)+ `done_marker` + `failed_marker`(均**绝对**);**NEVER** 自拼 `<target>/<id>`、**NEVER** `py -c` 算路径、**NEVER** 相对路径;
- **fan-out 单元 `failed` ack**(subagent 回 `failed <原因>`)→ 编排器 `Write` 该单元 `failed_marker`(= `list_*` stdout `pending[].failed_marker`,绝对、**逐字透传**、body `{unit,reason,tier}`;**NEVER** 自拼 `<checkpoint_path>.failed`、**NEVER** `py -c`、**NEVER** 让 subagent 写);**不重试**该单元、**不阻断**当前波次,继续下一单元。`.failed` = **终态**(resume 不重派,区别于 `.done` 的成功完成);crash 无 ack → 无 marker → 单元仍 `pending` → 重派(crash ≠ 确认失败,安全重试非静默丢失)。tier 完成门 = `done+failed>=total`(见 `resume_state.py` stdout `tiers`)。
- **瞄一眼结构** → `describe_artifact.py --keys/--sample/--shape/--field`(**NEVER** `py -c`、**NEVER** `Read` 整份大 JSON);
- **派生量** → 该量产出者的 stdout 字段(`discover` stdout `big_files`/`unresolved_count`;`plan_scout` stdout/`scout_plan.json` `regex_known_count`);**NEVER** 自写脚本算。
- **当前步骤 / 下一步** → `resume_state.py --target <target>` stdout `step`/`next_action`/`tiers`(进度纯从磁盘 `<target>/.mgh-init/` 重派生);**NEVER** 靠对话记忆判步骤、**NEVER** `py -c` 重算、**NEVER** `Read` 整份聚合 JSON 倒推进度。`--resume` 或任何压缩事件后**第一步**调之。

**fan-out 刚性三元组**:每个 fan-out 步骤表述为 `[输入产物::字段] → script/subagent → [输出产物::字段]`;输出路径 = `list_*` stdout 的 `checkpoint_path`/`rule_path`(绝对),编排器**逐字透传**进 subagent task、subagent **恰好写该绝对路径**(零拼装、零占位符)。doubt 时刻 inline 1 行 shape(如「`scout_plan.json::batches[]` 即你的工作清单,经 `list_scout_batches.py` 取;每项 `checkpoint_path` 即该批产物绝对路径」)。

**终态声明**:`merge_scout.py`/foldin 完成后,`scout_candidates.json` / `controls_candidates.json` / `clusters.json` 为**终态**——不再二次聚合 / 重切批(不出现 `_aggregate_scout.py` 之类重实现)。

**边界校验**:每个 stage 产物跑完执行 `<producer> --check`(或独立 `validate_inventory.py`);失败(退出码 2)→ 回退重跑该步,**不带着破损产物继续**。

**长跑 Bash 超时纪律**:给长跑确定性 Bash 调用(`discover_controls.py`/`plan_scout.py`/`merge_scout.py`)传一个慷慨的 per-call `timeout`(claude Bash 与 opencode shell 工具均接受毫秒级 `timeout`),勿依赖宿主默认超时(opencode 实测 60s/官方 120s;claude 120s)中途强杀。对带 `--time-budget-ms` 的 discover,`timeout` 取略大于 budget;**见 discover stdout `partial:true` → 用 Bash 重派 `discover ... --resume`** 推进(编排器循环、**NEVER** 写 wrapper `.py` 循环),带 sane 重派次数上界,超限则建议 `--scope`+`--merge` 分模块;`partial:false` 即 discover 完成、写最终产物。discover 产物落盘均原子(`.tmp`+`os.replace`),见 `core/contracts/init/discover-cache.md`。

## Re-entrancy & compaction

> **进度真相源 = 磁盘 `<target>/.mgh-init/`(checkpoints / `.done` / 产物 / `run_config.json`);对话记忆只是缓存,不是真相源。** 这把 compact / crash / 新 session 三种中断坍缩为**同一种恢复路径**——「读磁盘状态 → 继续」。

1. claude `/compact` 与 opencode 自动压缩(~95% 触发)是**模型生成摘要**,**可能丢掉**本命令壳灌入的编排纪律系统提示词(硬边界 / fan-out 三元组 / NEVER 拼路径)。故续跑 SHALL **NEVER** 依赖「记得自己在第几步」。
2. **`--resume` 或任何压缩事件后,编排器第一步 SHALL 调 `resume_state.py`** 从磁盘重派生 `step` + `next_action` + `tiers`,据此继续 fan-out / 下一步(见上方「当前步骤 / 下一步」recipe)。压缩后:`resume_state.py` 给当前 step → 据以 `list_steps.py --step <id>` 取确切调用行(配套语义,单步确切脚本路径 / 调用行 / IO shape)。
3. 上下文吃紧时编排器 **MAY** **干净停止**(跑完当前 fan-out 波次、落 `.done`、不留半截单元)→ **新 session `/mgh-init --resume` 续**;此路径**优于**人工 `/compact`(后者摘要可能丢编排纪律导致执行路径偏离——直击用户痛点)。新 session 重灌命令壳 = 完整纪律提示词,进度由磁盘重派生,故 compact 是否丢提示词**无关紧要**。干净停止**亦** `rm <target>/.mgh-init/.active` 移除哨兵(或留待 resume step 0 重写覆盖;残留哨兵只挡脚本写、不挡 JSON/`.md`/读)。
4. 既有 per-call `timeout` + discover `partial:true` + `--resume` 纪律**保持不变**(本段为 additive)。`run_config.json` 作起始态意图、`init_manifest.json` 作终态(磁盘 schema 不变)。
5. **`.failed` = 终态**(确认失败,区别于 `.done` 的成功完成):`--resume` 跳过 `.failed` 单元(**不重派**);crash 无 ack → 无 marker → 单元仍 `pending` → 重派(crash ≠ 确认失败)。escape hatch = 人工 `rm <unit>.json.failed` 后 `--resume` 重派该单元。失败计数从磁盘(`resume_state.py`/`list_*` stdout `tiers`/`failed`)读,**NEVER** 对话记忆(见步骤 8)。
5. **fan-out 波次 run-to-completion**:scout reader / T1 induct / T3 rulewriter 任一波次进行中,编排器 **MUST NOT** 因规模大(数百至 ~1000 单元)停下征求用户「拆分/跳过/终止」、**SHALL** 迭代 `list_*` stdout `pending[]`(以 `max_concurrent` 并发起 subagent)跑到 `pending` 为空。规模与边界(大 fan-out 计数 / 部分覆盖 / `.failed`/跳过单元 / 残留盲区)**SHALL** 流入既有披露渠道——`init_manifest.json::boundaries[]` + `report.md` + `resume_state.py` `notes[]`——**NEVER** 作为运行中阻塞式提问;披露计数取自磁盘 `resume_state.py`/`list_*` stdout(**NEVER** 对话记忆)。仅约束**运行已提交后**(波次进行中);i0 花 token **前**的 `--large-repo-threshold` → 建议 `--scope`+`--merge` 前置建议保持不变(见步骤 0)。

## Orchestration flow

```
0. parse + self-check (host agent/model available; else STOP with fix hint;发现脚本统计源文件数,超 `--large-repo-threshold` 则建议 `--scope`+`--merge`(**花 token 前**前置建议;波次进行中不再因规模打断,见 Re-entrancy & compaction),扫描期向 stderr 打印进度)
   · **起步**:`Bash: export MGH_INIT_ACTIVE=1`(声明运行域,激活 PreToolUse hook,含子树外 Write/Edit 拦截)
   · **run_config(无状态 resume 意图源)**:起步后、花 token 前,**原子写** `<target>/.mgh-init/run_config.json`
     (起始态意图:记决定步骤图的本次 flag;与终态 `init_manifest.json` 边界清晰、互不替代):
     `py .claude/mgh-core/scripts/write_runconfig.py --target <abs target> --format <fmt> [--no-scout] [--no-codegraph] [--skip-consistency] [--merge <dir>] [--include-dotfiles] [--scope ..] [--scope-mode ..] [--max-aggregate-bytes ..] [--max-unit-bytes ..] [--orch-budget-bytes ..] [--scout-* ..]`
     该文件使 `/mgh-init --resume` **无需重输 flag**;`resume_state.py` 据它解析 optional/codepath 分支。
     `--resume` 复用既有 run_config(不覆盖);新 run(`.mgh-init/` 不存在或被清)重写。
   · **哨兵(磁盘激活信号,opencode 可靠激活兜底)**:`write_runconfig.py` stdout 的 `target` 即**绝对项目根**
     (Windows 原生、供守卫 `Path.resolve()` 判树;**NEVER** 用 bash `pwd`,其 MSYS `/c/...` 在 Windows pathlib 误解析)。
     据此写哨兵:
     `printf '%s' '{"domain":"mgh-init","target":"<write_runconfig stdout 的 target>","out_roots":[<非默认 --out/--rules-dir 解析后绝对根,默认产物根不列>],"v":1}' > <target>/.mgh-init/.active`
     守卫激活 = `MGH_INIT_ACTIVE=1` env **或** 该哨兵(opencode 插件进程不继承 mid-session env → 哨兵兜底,使
     脚本只读 / 受信子树守卫在 opencode 上整 run 可靠激活)。哨兵携 `target` 使 `MGH_TARGET` 在 opencode step 0 即就绪。
     完成态(step 8)/ 干净停止 `rm <target>/.mgh-init/.active`(避免残留锁死日常开发);`--resume` step 0 重写覆盖。
   · **MGH_TARGET**(供 hook 判树):`controls_candidates.json::repo` 即**绝对项目根**(= 哨兵 `target`,二者一致)。该产物首次 discover 后落盘、**`--resume` 时 discover 跳过但产物仍在**——故编排器在 fan-out 前(无论本次是否实跑 discover)**逐字读**该字段并 `export MGH_TARGET=<repo>`。取值经 `describe_artifact.py --field repo`(合法瞄结构出口),**NEVER** `py -c` 自算、**NEVER** 用裸 `.` 相对。hook 在 `MGH_TARGET` 缺失时该条**降级放行**(不阻断)。
   · **codegraph 检测**(花 token 之前):`Bash: if test -d <target>/.codegraph && command -v codegraph >/dev/null 2>&1; then echo on; else echo off; fi`
     → `codegraph=on|off`。默认 `auto`(可用即启用);传 `--no-codegraph` 或检测不可用 → `codegraph=off`。该信号**逐字透传**进
     scout/induct/survey/resolve subagent task 输入(仅 `codegraph=on` 时这些 stage 启用 codegraph 外科式上下文 + 执行 `init-resolve` stage)。
1. IF --merge: merge partial inventories by evidence anchor → STOP
2. i1 discover (Bash, deterministic, streaming):
     py .claude/mgh-core/scripts/discover_controls.py --repo <target> --out <target>/.mgh-init
        [--scope .. --scope-mode .. --language .. --max-files .. --big-file-bytes .. --sample ..]
   → controls_candidates.json (regex, `source:regex`) + clusters.json + skeleton.json  (skip on --resume if present & not --rebuild-cache)
   · 派生量直读 discover stdout:`candidates/clusters/unresolved_count/big_files`(NEVER `py -c` 自算)
   · **MGH_TARGET**:discover 跑过后(产物在盘上)取其 `repo` 字段(绝对根)——
     `py .claude/mgh-core/scripts/describe_artifact.py --in <target>/.mgh-init/controls_candidates.json --field repo`
     → stdout `{"value":"<绝对 target>"}`;`export MGH_TARGET=<该 value>`(供 hook 判树;NEVER `py -c` 自算)。
     **`--resume` 时 discover 跳过,但 `controls_candidates.json` 仍在 → 同法重设 `MGH_TARGET`**(别让子树守卫在 resume 上 fail-soft)。
   · 校验:`py .claude/mgh-core/scripts/discover_controls.py --check <target>/.mgh-init`(wrapper + 每条 `source` + cluster_id 唯一;退出码 2 → 回退重跑)
3. (optional) init-survey subagent → i1_enriched.json
   · **advisory + non-fatal**:产出仅作审计/T2 参考,**非 T1 输入**(T1 读 `clusters.json`);
     缺失 `i1_enriched.json` **不阻断**、不报致命错。`total` 过大(单 subagent 装不下整仓簇)
     时**跳过**,并在摘要披露。
3b. SCOUT FAN-OUT (除非 `--no-scout`)——让 LLM 找出 regex 闸门漏掉的自研控制:
     [skeleton.json + controls_candidates.json] → plan_scout.py → [scout_plan.json::batches[]]
     py .claude/mgh-core/scripts/plan_scout.py --skeleton <target>/.mgh-init/skeleton.json \
        --candidates <target>/.mgh-init/controls_candidates.json --out <target>/.mgh-init/scout_plan.json \
        [--batch-bytes .. --batch-cap .. --budget ..]
     · 批数涌现 = ceil(Σtarget_bytes / --scout-batch-bytes);按包内聚切批,每批字节≤预算且文件数≤cap。派生量 `regex_known_count` 在 stdout / `scout_plan.json` 顶层(NEVER 自算)。
     · 校验:`py .claude/mgh-core/scripts/plan_scout.py --check <target>/.mgh-init/scout_plan.json`(batches 非空除非 0 target、每批 bytes≤预算、needs_slice 仅含超批文件;退出码 2 → 回退)。
     [scout_plan.json::batches[]] → list_scout_batches.py --materialize → [stdout slim pending[](每项 `input_path`/`oversize`/`needs_slice`/`checkpoint_path`/`done_marker`)](禁手挖 `scout_plan` / `py -c`)
     py .claude/mgh-core/scripts/list_scout_batches.py --scout-plan <target>/.mgh-init/scout_plan.json --checkpoints <target>/.mgh-init/checkpoints/scout --materialize <target>/.mgh-init/inputs/scout
     按 `offset`/`effective_limit` 翻页(单页 > `--orch-budget-bytes` 时 `shrunk:true`;NEVER wrapper `.py`);per batch in page `pending[]`(**每批一个隔离 subagent 上下文**;`--resume` 跳过已 `.done`/`.failed`):
       - spawn init-scout(透传 `input_path` + checkpoint_path + done_marker + failed_marker;subagent 读 `input_path`,needs_slice 文件自行 `chunk_sources` 切片,**绝不**整文件喂 LLM)→ 成功则恰好写 `checkpoint_path`(绝对) + touch `done_marker`;失败回 `failed <原因>` ack → 编排器写 `failed_marker`、不重试不阻断(见上「fan-out 单元 `failed` ack」)
     spawn init-scout-merge 前**先判聚合预算** — `py .claude/mgh-core/scripts/plan_aggregate.py --node scout-merge --init-dir <target>/.mgh-init --budget <max-aggregate-bytes> [--materialize <target>/.mgh-init/inputs/scout-merge]`
       · `needs_reduce=false`(≤ 预算)→ 既有 single-context `init-scout-merge`(只见全部 scout 批记录,无原始码)→ `scout_candidates.json` + `checkpoints/scout/merge.json.done`
       · `needs_reduce=true`(> 预算)→ 每 shard(batch 簇)扇出 `init-scout-merge`(partial;读 shard `input_path`,ack 回传)→ 单一 rollup 仅吞各 shard 摘要 → `scout_candidates.json` + `checkpoints/scout/merge.json.done`。每请求 ≤ 预算。
     · 校验:`py .claude/mgh-core/scripts/merge_scout.py --check <target>/.mgh-init/scout_candidates.json`(每条 `source:"scout"` + file:line;退出码 2 → 回退)。
     spawn init-scout-audit(随机 ≈--scout-audit-pct 的 scout 拒绝项)→ checkpoints/scout/audit.json + .done
     py .claude/mgh-core/scripts/merge_scout.py --candidates <target>/.mgh-init/controls_candidates.json \
        --scout <target>/.mgh-init/scout_candidates.json --audit <target>/.mgh-init/checkpoints/scout/audit.json \
        --clusters <target>/.mgh-init/clusters.json
     · 候选集并入 `source:"scout"`;clusters.json **追加** scout 簇(regex 簇与其 usage_sites 不变)。复用 `discover_controls.form_clusters`,无逻辑漂移。
     · **终态**:`scout_candidates.json` / `controls_candidates.json` / `clusters.json` 此时为终态——不再二次聚合 / 重切批(NEVER `_aggregate_scout.py`)。
3c. (optional, codegraph-gated) init-resolve — 仅当 `codegraph=on` **且** `unresolved[]` 非空时执行;
     排空文本/AST 图结构性漏掉的框架路由 / DI / AOP / interface→impl / 反射控制。**non-fatal + bounded**:
     [controls_candidates.json::unresolved[]] → describe_artifact.py --field → init-resolve subagent → [resolved.json]
     · 取 `unresolved[]` 清单(合法瞄结构出口,**NEVER** `py -c`、**NEVER** `Read` 整份大 JSON):
       `py .claude/mgh-core/scripts/describe_artifact.py --in <target>/.mgh-init/controls_candidates.json --field unresolved`
       → stdout `{"field":"unresolved","value":["<file>",...]}`;空列表 → 跳过本 stage(摘要披露)。
     · spawn init-resolve({unresolved[], repo root, checkpoint_path=<target>/.mgh-init/resolved.json(绝对),
       done_marker=<target>/.mgh-init/checkpoints/resolve/.done(绝对)}, codegraph=on)
       → 恰好写 `checkpoint_path`(绝对)+ touch `done_marker`(产 `{repo, resolved[]{…source:"codegraph", resolved_path[]}, unresolved_residual[]}`,见 `core/contracts/init/resolved.md`)
     · **additive 并入 T1 候选流**:`resolved[]` 按既有 `category::anchor` 簇键由编排器路由到对应簇的 candidate hits(additive;**不** mutate regex/scout 候选、**不**改任何确定性脚本;簇形成语义与既有 form_clusters 一致)。`source:"codegraph"` 结构标签一路保留进 inventory/manifest。`unresolved_residual[]` 残留计 manifest `codegraph.unresolved_residual`。
     · **MGH_TARGET / 子树守卫**:`resolved.json` 写在 `<target>/.mgh-init/` 下,既有子树守卫覆盖;`checkpoint_path` 是编排器**逐字给定**的绝对路径(NEVER 拼装 `<target>/<id>`、NEVER 占位符、NEVER 相对)。
     · **fail-soft / non-fatal**:`codegraph=off` / `unresolved[]` 为空 / 清单过大超单 subagent 上下文预算 → 跳过整 stage + 摘要披露,流水线**不阻断**、不报致命错(对标 init-survey 的 optional/advisory/non-fatal 语义)。T1 从 `clusters.json` 正常扇出不受影响。
4. T1 FAN-OUT — 经确定性脚本枚举 + per-unit 物化(**禁手搓**;`clusters.json` 是包装字典
   `{repo,clusters[],truncated}`,对顶层 `len()` 得 3 **不是**簇数;编排器 NEVER 整份读 `clusters.json`):
   [clusters.json::clusters[]] → list_clusters.py --materialize → [stdout slim pending[](每项 `input_path`/`bytes`/`oversize`/`checkpoint_path`/`done_marker`)]
     py .claude/mgh-core/scripts/list_clusters.py --clusters <target>/.mgh-init/clusters.json --checkpoints <target>/.mgh-init/checkpoints/t1 --candidates <target>/.mgh-init/controls_candidates.json --materialize <target>/.mgh-init/inputs/t1
     → stdout `{repo,total,done,pending[],truncated,offset,limit,effective_limit,shrunk}`;物化每簇完整记录(簇字段 + 候选命中回查 `controls_candidates.json`)到 `inputs/t1/<unit>.input.json`(≤ `--max-unit-bytes`;oversize 簇切 `<cluster_id>::shard-<n>`)
   按 `offset`/`effective_limit` 翻页(单页 > `--orch-budget-bytes` 时 `shrunk:true`;NEVER wrapper `.py`);for each unit in page `pending[]`(NOT `clusters.json` 顶层;`--resume` 跳过已 `.done`/`.failed`):
     - spawn init-induct(透传 `input_path` + checkpoint_path + done_marker + failed_marker;subagent 读 `input_path`,大证据文件自行 `chunk_sources` 切片)
     → 成功则恰好写 `checkpoint_path`(绝对) + touch `done_marker`;失败回 `failed <原因>` ack → 编排器写 `failed_marker`、不重试不阻断(见上「fan-out 单元 `failed` ack」)
5. T2: **先判聚合预算** — `py .claude/mgh-core/scripts/plan_aggregate.py --node t2 --init-dir <target>/.mgh-init --budget <max-aggregate-bytes> [--materialize <target>/.mgh-init/inputs/t2]`
     · `needs_reduce=false`(≤ `--max-aggregate-bytes`,常见小仓)→ 既有 **single-context** `init-synthesis`(sees all T1 records, no raw code)→ `controls_inventory.json` + `checkpoints/t2/.done`(行为等价于引入硬阈值前)。
     · `needs_reduce=true`(> 预算)→ 每 shard 扇出 `init-synthesis`(partial;读 shard `pending[].input_path`,ack 回传,恰好写 `pending[].checkpoint_path`)→ 单一 **rollup** `init-synthesis` 仅吞 `rollup.summary_paths`(各 shard 摘要,非原始记录全集)→ 写 `controls_inventory.json` + `checkpoints/t2/.done`。**每个大模型请求 ≤ 预算**。
   · 校验:`py .claude/mgh-core/scripts/validate_inventory.py --inventory <target>/.mgh-init/controls_inventory.json`(`design_controls` 兼容字段 + 每条 evidence 锚点 + category→kind 归一;退出码 2 → 回退重跑;map-reduce rollup 产物 schema 不变,同样适用)。
   · 降级触发 + shard 数进 `init_manifest.json::boundaries[]` + `report.md`(无静默溢出)。
6. T3 FAN-OUT — 经确定性脚本枚举 + per-category 物化(**禁手挖** inventory / `py -c`;编排器 NEVER 整份读 `controls_inventory.json`):
   [controls_inventory.json::controls[].category] → list_rule_jobs.py --materialize → [stdout slim pending[](每项 `input_path`/`bytes`/`oversize`/`rule_path`/`done_marker`)]
     py .claude/mgh-core/scripts/list_rule_jobs.py --inventory <target>/.mgh-init/controls_inventory.json --format <format> --checkpoints <target>/.mgh-init/checkpoints/t3 --target <target> --rules-dir <target>/docs/security-controls --materialize <target>/.mgh-init/inputs/t3
     → stdout `{total,done,pending[],format,offset,limit,effective_limit,shrunk}`;物化每 category 完整 controls 到 `inputs/t3/<category>.input.json`(oversize 标 `oversize` + recipe,**不**切分)
   按 `offset`/`effective_limit` 翻页;per category in page `pending[]`(WITHOUT `.done`/`.failed`;`--resume` 跳过):
     - spawn init-rulewriter(透传 `input_path` + --format + rule_path + done_marker + failed_marker;subagent 读 `input_path`)
     → 成功则恰好写 `rule_path`(绝对;claude: `.claude/rules/security-<cat>.md`;opencode: 详述文件 `docs/security-controls/<cat>.md`)+ touch `done_marker`;失败回 `failed <原因>` ack → 编排器写 `failed_marker`、不重试不阻断(见上「fan-out 单元 `failed` ack」)
6b. ASSEMBLE / LINT (Bash, deterministic; uses the run's --format, after T3 / before T4):
     py .claude/mgh-core/scripts/assemble_rules.py --target <target> --format <format>
   · opencode: 扫 `<rules-dir>/*.md` 详述文件建 `<target>/AGENTS.md` 简洁**惰性索引块**(幂等、迁移旧 `mgh-init:` 块、内置 lint);正文留详述文件按需加载
   · claude: 无索引(T3 已直写文件),仅对 `.claude/rules/security-*.md` 做纯净性 lint
   · lint(fail-loud 退出码 2)= 规则正文泄漏:T3 禁 front matter / inventory schema 字段
     (`found_controls`/`evidence_count`)/ 过程散文(`扫描器模式定义` 等)/ 无源码锚点的控制;lint 覆盖
     工具内部 token + schema 字段 + 特征过程散文(opencode 另查 `---` YAML 围栏;claude `paths:` frontmatter 豁免)。
     回 T3 修正后重跑
7. T4 (unless --skip-consistency): spawn init-rules-consistency
     → in-place edits to rule files (claude) / detail files (opencode) + checkpoints/t4/.done
8. i4: write init_manifest.json + report.md; print artifact paths + disclaimers
   · manifest 含 `codegraph:{available,used,resolved_count,unresolved_residual}`:`available`=检测到 `.codegraph/`+CLI;`used`=`codegraph=on` 且 `init-resolve` 实跑;`resolved_count`/`unresolved_residual` 取自 `resolved.json`(经
     `py .claude/mgh-core/scripts/describe_artifact.py --in <target>/.mgh-init/resolved.json --field resolved --count` 计数,NEVER `py -c`);`codegraph=off` 时 `used=false`/`resolved_count=0`,不出现解析计数。report.md 同步披露 codegraph 用量 + 残留盲区。
   · **fan-out 失败披露**(任一 tier `failed>0`):据 `resume_state.py` stdout `tiers[<tier>].failed`(磁盘真相、**NEVER** 对话记忆)写 `init_manifest.json::failures`(per-tier `{done,failed,total}`)+ `boundaries[]`(「fan-out 单元确认失败、已跳过、终局需人评」)+ `report.md` 同步披露失败计数/率。
   · **收尾移除哨兵**:`rm <target>/.mgh-init/.active`(run 完成;避免残留哨兵锁死日常开发)
```

### Stage → component map

| Stage | How | Asset |
|---|---|---|
| i1 discover | **script** | `core/scripts/discover_controls.py` (+ `expand_scope.py` reuse) |
| i1 big-file slice | **script** | `core/scripts/chunk_sources.py` |
| artifact inspect | **script** | `core/scripts/describe_artifact.py` (瞄结构合法出口;NEVER `py -c`/`Read` 整份大 JSON) |
| i1 survey (opt) | subagent `init-survey` | `core/prompts/stages/init-survey.md` |
| resolve (opt) | subagent `init-resolve` (codegraph-gated, single context) | `core/prompts/stages/init-resolve.md` + `fragments/codegraph-hint.md` |
| T1 enumerate | **script** | `core/scripts/list_clusters.py` (pending work-list;包 `clusters.json` 包装字典) |
| T3 enumerate | **script** | `core/scripts/list_rule_jobs.py` (pending 按-category 清单;禁手挖 inventory) |
| T1 induct | subagent `init-induct` (fan out per cluster) | `core/prompts/stages/init-induct.md` |
| T2 synthesis | subagent `init-synthesis` | `core/prompts/stages/init-synthesis.md` |
| T3 rulewriter | subagent `init-rulewriter` (fan out per category) | `core/prompts/stages/init-rulewriter.md` + `fragments/rules-format-{claude,opencode}.md` |
| T3 assemble/lint | **script** | `core/scripts/assemble_rules.py` (opencode: build concise lazy index in AGENTS.md from `<rules-dir>/*.md` + legacy migration; both formats: `--check` purity lint over detail/rule files: tool tokens + schema fields + YAML fences[opencode] + discovery prose) |
| T4 consistency | subagent `init-rules-consistency` (opt) | `core/prompts/stages/init-rules-consistency.md` |
| scout plan | **script** | `core/scripts/plan_scout.py` (byte-budget + pkg-co-located batches) |
| scout enumerate | **script** | `core/scripts/list_scout_batches.py` (pending 批清单;闭合与 T1 的不对称) |
| scout reader | subagent `init-scout` (fan out per batch) | `core/prompts/stages/init-scout.md` |
| scout merge | subagent `init-scout-merge` | `core/prompts/stages/init-scout-merge.md` |
| scout audit | subagent `init-scout-audit` (opt) | `core/prompts/stages/init-scout-audit.md` |
| scout fold-in | **script** | `core/scripts/merge_scout.py` (reuses `discover_controls.form_clusters`) |
| inventory validate | **script** | `core/scripts/validate_inventory.py` (T2 边界;`design_controls` 兼容 + evidence 锚点 + kind 归一) |
| stage boundary check | **script** | `discover_controls`/`plan_scout`/`merge_scout` `--check`(每 stage 产物校验) |

### Deterministic invocation (Bash)

```bash
py .claude/mgh-core/scripts/discover_controls.py --repo . --out ./.mgh-init
# escape hatch: 控制定义点在 .opencode/.claude/.codegraph/.github 等 .xxx 内时才纳入(默认跳过点前缀路径)
py .claude/mgh-core/scripts/discover_controls.py --repo . --out ./.mgh-init --include-dotfiles
py .claude/mgh-core/scripts/discover_controls.py --check ./.mgh-init
# 大仓韧性:软时限干净早退(给 Bash per-call timeout 略大于 budget;见 stdout partial:true 即重派 --resume)
py .claude/mgh-core/scripts/discover_controls.py --repo . --out ./.mgh-init --time-budget-ms 120000
py .claude/mgh-core/scripts/discover_controls.py --repo . --out ./.mgh-init --resume
# step 0 起步态:写 run_config(无状态 resume 意图);--resume / 压缩后首步 = resume_state 重派生 step
py .claude/mgh-core/scripts/write_runconfig.py --target . --format claude --no-scout
py .claude/mgh-core/scripts/resume_state.py --target .
py .claude/mgh-core/scripts/resume_state.py --target . --check
# 聚合硬阈值闸门(T2 / scout-merge):≤ 预算 single-context;> 预算 map-reduce
py .claude/mgh-core/scripts/plan_aggregate.py --node t2 --init-dir ./.mgh-init --budget 262144 --materialize ./.mgh-init/inputs/t2
py .claude/mgh-core/scripts/plan_aggregate.py --node scout-merge --init-dir ./.mgh-init --budget 262144
py .claude/mgh-core/scripts/describe_artifact.py --in ./.mgh-init/controls_candidates.json --keys
py .claude/mgh-core/scripts/list_clusters.py --clusters ./.mgh-init/clusters.json --checkpoints ./.mgh-init/checkpoints/t1 --candidates ./.mgh-init/controls_candidates.json --materialize ./.mgh-init/inputs/t1 --offset 0 --limit 50 --max-unit-bytes 196608 --orch-budget-bytes 65536
py .claude/mgh-core/scripts/chunk_sources.py --in <big_file> --big-file-bytes 204800 --line <L> --out ./.mgh-init/_slice.json
py .claude/mgh-core/scripts/plan_scout.py --skeleton ./.mgh-init/skeleton.json --candidates ./.mgh-init/controls_candidates.json --out ./.mgh-init/scout_plan.json --batch-bytes 98304 --batch-cap 40
py .claude/mgh-core/scripts/plan_scout.py --check ./.mgh-init/scout_plan.json
py .claude/mgh-core/scripts/list_scout_batches.py --scout-plan ./.mgh-init/scout_plan.json --checkpoints ./.mgh-init/checkpoints/scout --materialize ./.mgh-init/inputs/scout --offset 0 --limit 50 --max-unit-bytes 196608 --orch-budget-bytes 65536
py .claude/mgh-core/scripts/merge_scout.py --candidates ./.mgh-init/controls_candidates.json --scout ./.mgh-init/scout_candidates.json --audit ./.mgh-init/checkpoints/scout/audit.json --clusters ./.mgh-init/clusters.json
py .claude/mgh-core/scripts/merge_scout.py --check ./.mgh-init/scout_candidates.json
py .claude/mgh-core/scripts/validate_inventory.py --inventory ./.mgh-init/controls_inventory.json
py .claude/mgh-core/scripts/list_rule_jobs.py --inventory ./.mgh-init/controls_inventory.json --format claude --checkpoints ./.mgh-init/checkpoints/t3 --target . --rules-dir docs/security-controls --materialize ./.mgh-init/inputs/t3 --offset 0 --limit 50 --max-unit-bytes 196608 --orch-budget-bytes 65536
py .claude/mgh-core/scripts/assemble_rules.py --target . --format claude --check
```

### Resume / cache
- **`--resume` 首步** = `py .claude/mgh-core/scripts/resume_state.py --target <target>` → 读 stdout `step`/`next_action`/`tiers` 继续(进度纯从磁盘 `<target>/.mgh-init/` 重派生;**NEVER** 靠对话记忆判步骤)。`--check` 可在起步校验磁盘状态自洽(退出码 2 = 不自洽)。
- **新 session 运行域 env 重注入**:`--resume` 走同一命令壳 step 0 → 重新 `export MGH_INIT_ACTIVE=1`;并在 fan-out 前从既有 `controls_candidates.json::repo` 重设 `MGH_TARGET`(产物在盘上、`describe_artifact.py --field repo`,无需重跑 discover)。**确定性脚本本身不读 env**(flag + 磁盘驱动),env 仅影响 hook 子树守卫强度。
- Work units (isolation unit): i1 per file, **scout per batch**, T1 per cluster, T2/T4 whole, T3 per category.
- `<target>/.mgh-init/checkpoints/<tier>/<unit>.json.done`(成功)**或** `.failed`(确认失败)= 终态,gate `--resume`(均跳过、不重派);`run_config.json` 使 `--resume` 免重输 flag。
- Call graph is rebuilt by discover each run; pass `--rebuild-cache` to force (mtime-based skip otherwise).

## Output (per `<target>/.mgh-init/`)

- `controls_candidates.json` — raw deterministic hits + scout candidates(audit trail;每条带 `source`)
- `skeleton.json` — 无损逐文件元数据(scout 输入;纯机械抽取,不含语义判定)
- `scout_plan.json` — scout 批次规划(字节预算 + 包内聚)
- `scout_candidates.json` — merge 后的 scout 候选(`source:"scout"`)+ `unresolved[]`
- `clusters.json` — T1 isolation units (centralized/distributed,regex 簇 + 追加的 scout 簇);包装结构 `{repo,clusters[],truncated}` 见 `core/contracts/init/clusters.md`
- `controls_inventory.json` — structured (`design_controls`-compatible); downstream input for `/mgh-sra`, `/mgh-blst`, future mgh-sast control intake
- `checkpoints/**` — per-unit artifacts (resume)
- `inputs/<tier>/<unit>.input.json` — per-unit materialized fan-out inputs (subagent 自读;≤ `--max-unit-bytes`;随 `.mgh-init/` gitignore;见 `core/contracts/init/unit-inputs.md`)
- `init_manifest.json` — version/format/counts/provenance/unresolved[]/out_of_scope[]/boundaries[]
- `report.md` — human-readable summary (+「competing controls」section)
- rules → claude:`<target>/.claude/rules/security-*.md`;opencode:`<target>/AGENTS.md` 简洁**惰性索引块** `<!-- security-controls:begin --> … :end -->` + 每实现 category 一个详述文件 `<target>/docs/security-controls/<cat>.md`(均经 `assemble_rules.py` 纯净性 lint)

## Always disclose
- 面向人读的非代码内容(`report.md`、`init_manifest.json` 的 `boundaries[]`/文案、rules 正文)
  用**简体中文**;锚点/路径/frontmatter 保持原样。

- LLM-induced candidates — human review required.
- **Existence ≠ effectiveness** (CVE-2025-41248: `@PreAuthorize` bypass on parameterized types).
- Call-graph is textual/AST-level — misses AOP/reflection/DI/framework-routing; surface `unresolved[]`.
- **宿主 shell 超时**:opencode 可经环境变量 `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认 120000)提升全局 shell 超时,但**须在 opencode 启动前就绪**(会话中途 `export` 不被 opencode 插件进程继承);per-call `timeout`(见「Orchestrator discipline」长跑 Bash 超时纪律)是跨宿主公共杠杆、会话内即时生效。claude Bash per-call `timeout` 上限 600000ms。
- **点前缀路径默认不扫描**(tooling/VCS/IDE/build/config/索引,如 `.opencode`/`.claude`/`.codegraph`/`.github`):控制定义点落在 `.xxx` 内时默认不会被发现,须传 `--include-dotfiles` 才纳入;discover stdout `dotfiles_skipped` 计本次跳过的点前缀源文件数;`report.md` / `init_manifest.json::boundaries[]` 披露该边界。
- For ≥1.5M-line repos: prefer `--scope` per module + `--merge` over a single full-repo run.
- **Scout coverage is partial, not whole-repo**:`init_manifest.json` 记 `scout.{skeleton_total, scout_targets, batches, deep_read_files, audit_sampled, audit_found}`;只声称「审视/深读/自检」的真实数字,**不声称全仓覆盖**。
- Scout 非确定:簇数 run-to-run 可能变化(regex 来源簇仍确定)。残留盲区:泛型包 + 泛型类名 + 无安全导入 + 低扇因的控制可能漏(`--no-scout` 回退纯 regex)。
- **codegraph 富化是可选 + 辅助**:`init_manifest.json` 记 `codegraph.{available,used,resolved_count,unresolved_residual}`;codegraph 解析缩小但**不归零** `unresolved[]`(反射 / DI 容器 / 运行时分派残留),resolved = LLM+codegraph 候选,需人工复核。**不声称全解析**。`--no-codegraph` 一键回退引入前行为。
- **请求上下文预算(确定性边界)**:每次大模型请求 ≤ 配置阈值(`--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes`);`oversize`/`shrunk`/聚合超限在 `init_manifest.json::boundaries[]` + `report.md` 披露(无静默溢出)。**T2/scout-merge 已硬阈值**:经 `plan_aggregate.py` —— 聚合输入 > `--max-aggregate-bytes` 自动两段 map-reduce(每 shard ≤ 预算 → rollup 仅吞摘要),≤ 预算走 single-context。**T4 仍软边界**:规则全集聚合目前为「披露 + `--scope`/`--merge` 回退」。扇出 per-unit 输入 + 编排器请求确定性有界。
