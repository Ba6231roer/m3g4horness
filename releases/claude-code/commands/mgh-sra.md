---
description: After an openspec 'propose', run /mgh-sra to dimension-scan the change's specs/tasks for security gaps and augment them with anchored, reuse-existing-controls requirements + tasks. Three-signal semantic matching (dimension-fit + business-domain + business-fact) against an optional mgh-init inventory; batched clarification questions persist a cross-iteration business_context.json. Idempotent non-destructive managed-block merge. Augmentations are LLM candidates needing human review.
allowed-tools: Read, Glob, Grep, Bash, Agent, Write, Edit
---

# /mgh-sra — openspec 安全设计补充(security requirements augmentation)

> 人类读者:通俗说明见 `docs/man/mgh-sra.md`。

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / Agent / Read / Write / Edit /
> AskUserQuestion)把流水线**跑出来**,而非写成代码——确定性逻辑已在 `prepare_augment.py` /
> `merge_augment.py` / `merge_memory.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,也不要另写
> `.py` 去包装或重实现。

> **运行域 + hook**:`install.sh` 向本仓 `.claude/settings.json` 注入 PreToolUse hook
> (`block-adhoc-scripts`),在 `/mgh-sra` 运行域内拦 `py -c`/`python -c` 内省、**一切脚本扩展名写入**
> (`.py`/`.ps1`/`.sh`/`.ts`/…;叶脚本 read-only)、**以及 resolved 目标不在 `MGH_TARGET` 子树内的
> `Write`/`Edit`**(子树外写入,如盘符根;命中退出码 2 + stderr recipe)。编排器**起步先**
> `Bash: export MGH_SRA_ACTIVE=1` 标记运行域 + 写磁盘哨兵 `<project>/.mgh-sra/.active`,并在 a1 后
> `export MGH_TARGET=<绝对项目根>`(供 hook 判树;缺失则该条降级放行)。
> opt-out = `install.sh --no-enforce-hook`(纪律仍由下方铁律 + 边界校验兜底)。守卫激活 = env **或** 磁盘哨兵
> (哨兵绕开 opencode「插件不继承 mid-session env」的可靠性边界,见 `core/contracts/hooks/runtime-enforcement.md`)。

You are the **orchestrator** of the mgh-sra flow. Carry it out by running the deterministic
leaf scripts (Bash) and spawning stage subagents (Agent). Shared assets live at
`.claude/mgh-core/` (mirrored from `core/`).

> **输出是 LLM 候选,非已确认要求。引用控制断言存在、不断言有效。** 每次总结都声明。

## Parse arguments(validate BEFORE spending tokens)

- `--change <name>`(默认取 `openspec/changes/` 下最新未归档变更;无则报错 STOP)
- `--rules <path>`(可选:mgh-init 的 `controls_inventory.json` 文件**或**其输出目录如 `.mgh-init/`)
- `--focus <inline-json|path>`(可选:维度聚焦,收窄本次扫描的安全维度 + 维度内 facet。inline JSON 值以 `{`
  起首,或指向一个 JSON 文件(前导 `@` 可选)。a1 确定性解析 + 闭集校验(任何 LLM 之前);非法 → 退出码 2
  早停。不传 = 全 9 维度,行为不变。值清单见 `focus_scope.py --list`)
- `--sensitive-catalog <inline-json|@path|->`(可选:公司强制脱敏目录,声明本次须逐项查脱敏缺口的必屏蔽
  字段类型 + 屏蔽级别(`full`/`partial`)+ 规则。inline JSON 值以 `{` 起首,`-`=stdin,或指向一个 JSON 文件
  (前导 `@` 可选)。a1 确定性解析 + 闭集校验(任何 LLM 之前);非法 → 退出码 2 早停。与 `--focus` **正交**
  (focus 收窄范围、目录声明必屏蔽策略),可同时传。不传 = 仅按现行 6 facet 识别敏感数据,行为不变。
  默认模板见 `sensitive_catalog.py --list`)
- `--no-interactive`(澄清问用 `default_guess`、不暂停问用户;产物标「未确认·默认」)
- `--dry-run`(仅产 `change_context.json` + stdout 摘要,**不写** specs/tasks/记忆)
- `--skip-consistency`(跳过 a4 跨类去重)
- `--config <profile>`(默认 `sra`)
- `--no-codegraph`(跳过可选 codegraph 富化;行为等价于引入 codegraph 前)。codegraph 检测默认 `auto`:仅当
  `<MGH_TARGET>/.codegraph/` 存在**且** PATH 有 `codegraph` 才启用;`--no-codegraph` 或检测不可用 → 富化 off(零
  codegraph 调用、a2/a3 行为与引入 codegraph 前逐字一致)
- **请求上下文预算**(`request-context-budget`,确定性边界强制每次大模型请求 ≤ 阈值;单位字节):
  `--max-unit-bytes <N>`(单 capability 物化输入上限,默认 192KB;oversize 标 `oversize` + recipe,**不**切分——capability 是 a3 原子)·
  `--orch-budget-bytes <N>`(编排器单次请求可见的待办壳页上限,默认 64KB;超则自动分页收紧,stdout `shrunk:true`)·
  `--max-aggregate-bytes <N>`(a2/a4 聚合输入上限,默认 256KB;P0 软边界,超则建议 `--focus`/分变更 + `sra_manifest.json::boundaries[]` 披露)

**无 actionable 参数 / `--help`** → 打印参数表后 **STOP**(零 token、零解析)。

## Orchestrator discipline(铁律)

编排器 = 宿主 agent,**不写代码**。确定性叶脚本经 `Bash` 执行;**NEVER `Read` 叶子 `.py` 源码进上下文**(报错看 stderr,不读源码)。

**硬边界(`NEVER`)**:(a) `Write` 任何 `.py`——大编排器**或**一次性微脚本(`py -c` 产物、`_prep_*.py`、`_aggregate_*.py`);(b) `Bash: py -c|python -c` 去内省/重派生产物(`import json` / `open(` / `load(` 读 `.mgh-sra/**` 或 `change_context.json`);(c) `Read` 叶子 `.py` 源码。

**`NEVER` 向系统临时目录写中间文件再回读**:确定性脚本 stdout 在 Bash tool result(最后一行是 JSON),直接消费;NEVER 重定向到 `$env:TEMP`/`%TEMP%`/`/tmp` 再回读。

**implementation-intention(需 X → 合法出口 Y,NEVER `py -c`)**:
- **工作清单 + fan-out 路径** → `prepare_augment.py --materialize` stdout 即 **slim 分页**待办壳(含 `pending[]` 每项**绝对** `draft_path`/`done_marker`/`input_path`/`bytes`/`oversize` + `clarify_path` + `project_root` + `offset`/`effective_limit`/`shrunk`);编排器**逐字读该 stdout**、**逐字透传**路径给 subagent;**NEVER** 自拼 `<change-root>/<cap>`、**NEVER** `py -c` 算路径、**NEVER** 相对路径;
- **需某 cap 完整输入** → `prepare_augment --materialize` stdout 的 `pending[].input_path`(绝对,该 cap 的 requirements + 业务面 + candidate_controls 切片 + memory);**NEVER** 整份读 `change_context.json`、**NEVER** `py -c`、**NEVER** 内联传记录给 subagent(subagent **自读** `input_path`);
- **瞄一眼结构** → `describe_artifact.py --keys/--sample/--shape/--field`(**NEVER** `py -c`、**NEVER** `Read` 整份大 JSON);
- **派生量** → 该量产出者的 stdout 字段(`prepare` stdout `requirements_count`/`candidate_controls_count`;`merge_augment` stdout `merged[].requirements/tasks`);**NEVER** 自写脚本算。

**fan-out 刚性三元组**:每个 fan-out 步骤表述为 `[输入产物::字段] → script/subagent → [输出产物::字段]`;路径 = `prepare_augment` stdout 的 `pending[].input_path`(subagent 读)/`draft_path`/`clarify_path`(绝对),编排器**逐字透传**、subagent **自读 `input_path`** + **恰好写 `draft_path`**(零拼装、零占位符)。

**边界校验**:每个确定性 stage 产物跑完执行 `<producer> --check`;失败(退出码 2)→ 回退重跑该步,**不带着破损产物继续**。

## Orchestration flow

```
0. parse + self-check(宿主 agent/model 可用;否则 STOP 给修复提示)
   · **起步**:`Bash: export MGH_SRA_ACTIVE=1`(声明运行域,激活 PreToolUse hook,含子树外 Write/Edit 拦截)
   · **哨兵(磁盘激活信号,opencode 可靠激活兜底)**:`mkdir -p .mgh-sra && printf '%s' '{"domain":"mgh-sra","target":"","out_roots":[],"v":1}' > .mgh-sra/.active`
     (cwd = 项目根;step 0 仅激活,target 待 a1 后填)。守卫激活 = `MGH_SRA_ACTIVE=1` env **或** 该哨兵
     (opencode 插件进程不继承 mid-session env → 哨兵兜底)。完成态(step 7)/ 干净停止 `rm .mgh-sra/.active`。
1. a1 prepare(Bash,确定性):
     py .claude/mgh-core/scripts/prepare_augment.py --change <change> [--rules <path>] [--focus <inline-json|path>] [--sensitive-catalog <inline-json|@path|->] --materialize <change-root>/.mgh-sra/inputs/augment [--offset N] [--limit N] [--max-unit-bytes B] [--orch-budget-bytes B] [--dry-run] [--no-interactive]
   → stdout = **slim 分页**摘要(`--materialize`);全量 `change_context.json` 仍落 <change-root>/.mgh-sra/change_context.json 供 a2 单上下文扫全变更读
   · 读该 **slim stdout** 取:`pending[]`(每项绝对 draft_path/done_marker/input_path/bytes/oversize)、`clarify_path`、
     `project_root`、`focus`、`sensitive_catalog`、`requirements_count`、`candidate_controls_count`、`has_memory`、
     `offset`/`limit`/`effective_limit`/`shrunk`(**NEVER** 整份读 `change_context.json`、**NEVER** `py -c` 重挖)。
     `focus` 为 `{dimensions[],facets{},directive}` 或 `null`;`focus.directive`(简体中文句子)是收窄指令——**逐字透传**
     进 a2/a3 subagent task(NEVER 重解析 / NEVER 自拼);`focus: null` = 全 9 维度,不注入指令。`sensitive_catalog` 为
     `{directive,items[],counts{},...}` 或 `null`;**逐字透传**(含 `directive`+`items[]`)进 a2/a3 subagent task
     (NEVER 重算 / NEVER 自拼);`sensitive_catalog: null` = 仅现行 6 facet,不注入目录
   · **翻页**(单页 > `--orch-budget-bytes` 时 stdout `shrunk:true`):按 `offset` += `effective_limit` 重派
     `prepare_augment` 取下一页(翻页循环由编排器,**NEVER** wrapper `.py`);`--resume` 经各 `done_marker` 跳过已 `.done` capability
   · **MGH_TARGET**(供 hook 判树):取该 stdout `project_root`(绝对项目根)→ `export MGH_TARGET=<project_root>`
     (覆盖变更子树 + 项目记忆 `<project>/.mgh-sra/` 两类写入;NEVER 用裸 `.` 相对)。
     **重写哨兵 target**(opencode 子树守卫就绪):`printf '%s' '{"domain":"mgh-sra","target":"<project_root>","out_roots":[],"v":1}' > .mgh-sra/.active`
     (project_root 来自 prepare_augment stdout,Windows 原生;**NEVER** bash `pwd`)。
   · **codegraph 检测**(发起任何 LLM subagent 之前;零 LLM token):
     `Bash: if test -d "$MGH_TARGET/.codegraph" && command -v codegraph >/dev/null 2>&1; then echo on; else echo off; fi`
     → `codegraph=on|off`。默认 `auto`(可用即启用);传 `--no-codegraph` 或检测不可用 → `codegraph=off`。该信号
     **逐字透传**进 a2/a3 subagent task 输入(仅 `codegraph=on` 时:sra-clarify 启用 advisory 预解析减问、sra-augment
     启用外科式上下文 + 对已推荐控制做 call-path advisory 确认)。codegraph 是宿主 MCP 工具 / 外部 CLI,**不** import、
     **不**新增 `pip` 依赖;`codegraph_explore`(MCP)/ `codegraph explore`(Bash)**均不**命中 block-adhoc-scripts
     拦截面(非 `py -c`/`Write *.py`/子树外写)——故 **无 hook 改动**。
   · 校验:有 `--rules` 时 `py prepare_augment.py --check <rules-path>`(inventory well-formed;退出码 2 → 回退或 advisory 无控制继续)
   · `--dry-run`:到此处 STOP(仅 change_context.json + stdout 摘要,**不**进 a2–a5、不写 specs/tasks/记忆)
2. a2 clarify(1 subagent,单上下文扫全变更):
     spawn sra-clarify({change_context 摘要 + memory + 维度目录路径 + clarify_path(绝对) + focus.directive(逐字,若非 null) + sensitive_catalog(逐字,若非 null) + codegraph 信号(逐字)})
     → 恰好写 clarify_path:`{"clarifications":[{id,capability,dimension,question,why_it_matters,default_guess,fact_key}, ...]}`
     · `codegraph=on`(可选 / codegraph-gated / non-fatal):sra-clarify 经 codegraph 预解析(callers→角色 / callees→敏感
       字段 / domain-sibling→鉴权范式)**减问**——仅减问(codegraph-sourced 事实优先级低于用户/代码/已记,不覆盖)、
       **不增写** codegraph 派生记忆;`codegraph=off` 时无预解析、行为等价引入前
3. 批量澄清交互(编排器,宿主原生 AskUserQuestion):
   · 读 clarify_path 的 clarifications[](NEVER `py -c`;用 Read 或 describe_artifact)
   · `--no-interactive` → 全部取 default_guess;否则**暂停一次**、一次性呈现全部(每条带 default_guess,用户可秒批/改/跳过)
   · 收答案 → 写临时 answers.json → `py .claude/mgh-core/scripts/merge_memory.py --memory <MGH_TARGET>/.mgh-sra/business_context.json --answers <answers.json>`
     (按 fact_key 幂等累积进项目级记忆;首跑创建 + version)
   · 无澄清 → 跳过本步
4. a3 augment(per-capability 扇出,≤ max_concurrent):
   for each item in 当前页 pending[](读 a1 slim stdout;逐字透传 input_path/draft_path/done_marker):
     spawn sra-augment(隔离上下文,一个 capability 一个;给:该 cap 的 **input_path**(subagent **自读**,含 requirements[] + 业务面
       + candidate_controls 切片 + memory,≤ `--max-unit-bytes`)+ 维度目录路径 + focus.directive(逐字,若非 null)
       + sensitive_catalog(逐字,若非 null) + draft_path(绝对) + done_marker(绝对) + codegraph 信号(逐字))
     → 恰好写 draft_path(结构化 JSON draft)+ touch done_marker
     · oversize capability(`oversize:true`):recipe 分变更跑 / `--focus` 收窄维度(capability **不**切分——a3 原子)
     · `codegraph=on`(可选 / codegraph-gated / non-fatal / bounded):sra-augment 对**已三信号命中、已推荐控制**的缺口做
       call-path advisory 确认(写 `recommended_control.call_path`;`confirmed` 不伪造、不覆盖代码/用户断言;超预算 → 每缺口
       top-1 + `confirmed:null` + 标「部分未确认」)+ data-flow/liveness/domain-sibling advisory 改善 `risk`/`note`/`reason`;
       `codegraph=off` / 无 `--rules` → 不产 `call_path`、无 advisory,三信号主流程不受影响
5. a4 consistency(除非 --skip-consistency;1 subagent):
     spawn sra-consistency({drafts_dir = <change-root>/.mgh-sra/drafts(绝对)})
     → 原地覆写各 draft 为定稿(跨类去重、消冲突、同控制归一)
6. a5 merge(Bash,确定性):
     py .claude/mgh-core/scripts/merge_augment.py --change <change>
   → 受管块 `<!-- mgh-sra:begin --> … <!-- mgh-sra:end -->` 幂等追加进各 specs/<cap>/spec.md
     (`## ADDED Requirements` 下)+ tasks.md;无 capability specs 时建 specs/security-augmentation/spec.md
   · 校验:`py merge_augment.py --check <change>`(仅动受管块、块外字节不变;退出码 2 → 回退)
   · 校验:`py merge_memory.py --check <MGH_TARGET>/.mgh-sra/business_context.json`(shape + fact_key 无冲突)
7. 写 <change-root>/.mgh-sra/sra_manifest.json(change/rules_source/memory_source/**focus**/**sensitive_catalog**/counts 含
   `call_path_confirmed`/`call_path_residual`/boundaries[])+ 打印产物路径 + 边界声明
   · `focus` = 本次聚焦的维度列表(取自 `change_context.focus.dimensions`;`null` = 全 9 维度)
   · `focus` 非 null 时,`boundaries[]` 增一条:**「本次仅扫描聚焦维度,范围外维度未覆盖」**(防用户误以为全量);
     `focus: null` 时无该额外边界
   · `sensitive_catalog` = 本次生效目录的 `counts{items,full,partial,categories}` + `source`(取自
     `change_context.sensitive_catalog`;`null` = 未用目录,仅 6 facet);非 null 时 `boundaries[]` 增一条:
     **「据公司敏感数据目录逐项查脱敏,目录外字段类型仅按现行 6 facet 识别」**(防误以为目录穷尽所有敏感字段)
   · `counts.call_path_confirmed`/`call_path_residual` 取自各 draft `recommended_control.call_path.confirmed` 计数
     (经 `describe_artifact.py` 合法瞄结构出口,**NEVER** `py -c`);`codegraph=off` 时二者均 0
   · **请求上下文预算命中**(取自 a1 slim stdout + a2/a4 信号):有 `oversize:true` capability / `shrunk:true` 页 / a2·a4 聚合超
     `--max-aggregate-bytes` 时,`boundaries[]` 各增一条披露(「capability 超单输入阈值,建议分变更/`--focus`」「聚合超软阈值,未硬界」);
     无命中则无该类边界。a3 per-capability 输入 ≤ `--max-unit-bytes`、编排器单页 ≤ `--orch-budget-bytes` 确定性有界
   · **收尾移除哨兵**:`rm .mgh-sra/.active`(run 完成;避免残留哨兵锁死日常开发)
```

### Stage → component map

| Stage | How | Asset |
|---|---|---|
| a1 prepare | **script** | `core/scripts/prepare_augment.py`(解析变更 + 信号-1 预筛 + 载记忆 + 枚举 draft) |
| artifact inspect | **script** | `core/scripts/describe_artifact.py`(瞄结构合法出口;NEVER `py -c`/`Read` 整份大 JSON) |
| a2 clarify(单上下文) | subagent `sra-clarify` | `core/prompts/stages/sra-clarify.md` + `fragments/security-dimensions.md` + `fragments/codegraph-hint.md`(`codegraph=on`) |
| 澄清交互 | 宿主 `AskUserQuestion` | claude 原生(批量一次问);`--no-interactive` 用默认 |
| 记忆写回 | **script** | `core/scripts/merge_memory.py`(fact_key 幂等累积) |
| a3 augment(per-cap 扇出) | subagent `sra-augment` | `core/prompts/stages/sra-augment.md` + `fragments/security-dimensions.md` + `fragments/codegraph-hint.md`(`codegraph=on`;产 `call_path` advisory) |
| a4 consistency | subagent `sra-consistency`(opt) | `core/prompts/stages/sra-consistency.md` |
| a5 合并(确定性) | **script** | `core/scripts/merge_augment.py`(幂等受管块→specs/tasks) |
| stage boundary check | **script** | `prepare_augment`/`merge_augment`/`merge_memory` `--check` |

### Deterministic invocation (Bash)

**长跑 Bash 超时纪律**:给 `prepare_augment`/`merge_augment`/`merge_memory` 等长跑确定性 Bash 调用传一个慷慨的 per-call `timeout`(claude Bash 工具与 opencode shell 工具均接受毫秒级 `timeout`;claude 上限 600000ms),勿依赖默认超时中途强杀(opencode 实测 60s/官方 120s;claude 120s)。

```bash
py .claude/mgh-core/scripts/prepare_augment.py --change <change> --rules .mgh-init
py .claude/mgh-core/scripts/prepare_augment.py --change <change> --rules .mgh-init --materialize .mgh-sra/inputs/augment --offset 0 --limit 50 --max-unit-bytes 196608 --orch-budget-bytes 65536
py .claude/mgh-core/scripts/prepare_augment.py --change <change> --focus '{"dimensions":["horizontal-authz","vertical-authz"]}'
py .claude/mgh-core/scripts/prepare_augment.py --change <change> --focus config/focus.json
py .claude/mgh-core/scripts/prepare_augment.py --change <change> --sensitive-catalog @.mgh-sra/sensitive_catalog.json
py .claude/mgh-core/scripts/focus_scope.py --list
py .claude/mgh-core/scripts/focus_scope.py --parse '{"dimensions":["sensitive-data"],"facets":{"sensitive-data":["id-card","bank-card"]}}'
py .claude/mgh-core/scripts/sensitive_catalog.py --list
py .claude/mgh-core/scripts/sensitive_catalog.py --parse @.mgh-sra/sensitive_catalog.json
py .claude/mgh-core/scripts/sensitive_catalog.py --check @.mgh-sra/sensitive_catalog.json
py .claude/mgh-core/scripts/prepare_augment.py --check .mgh-init
py .claude/mgh-core/scripts/describe_artifact.py --in <change-root>/.mgh-sra/change_context.json --keys
py .claude/mgh-core/scripts/merge_memory.py --memory <MGH_TARGET>/.mgh-sra/business_context.json --answers <answers.json>
py .claude/mgh-core/scripts/merge_memory.py --check <MGH_TARGET>/.mgh-sra/business_context.json
py .claude/mgh-core/scripts/merge_augment.py --change <change>
py .claude/mgh-core/scripts/merge_augment.py --check <change>
```

## Output(per `<change-root>/.mgh-sra/` + `<project>/.mgh-sra/`)

- `change_context.json` — a1 解析的结构化变更上下文(capabilities/requirements/endpoints/data_fields/role_hints/candidate_controls/pending/memory;全量落盘供 a2 单上下文扫全变更读)
- `inputs/augment/<cap>.input.json` — per-capability 物化输入(a3 subagent 自读;≤ `--max-unit-bytes`)
- `clarifications.json` — a2 发的澄清问(批量呈现给用户)
- `drafts/<cap>.md` — a3 逐 capability 的增补草稿(JSON),a4 定稿
- `merge_state.json` — a5 块外字节快照(供 `--check`)
- `sra_manifest.json` — counts + 四条 boundaries[]
- 受管块追加进变更本身:`specs/<cap>/spec.md`(`## ADDED Requirements` 下)+ `tasks.md`
- 项目级(跨变更):`<project>/.mgh-sra/business_context.json`(roles/domains/sensitive_fields/interface_authz/business_rules/clarifications)

## Always disclose

- **请求上下文预算(确定性边界)**:每次大模型请求 ≤ 配置阈值(`--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes`);`oversize`/`shrunk`/聚合超限在 `sra_manifest.json::boundaries[]` 披露(无静默溢出)。**P0 软边界**:a2/a4 聚合节点目前为「披露 + `--focus`/分变更 回退」,分层归约留后续;**不声称** P0 已对聚合节点提供硬阈值。a3 per-capability 输入 + 编排器请求确定性有界。

- **宿主 shell 超时**:opencode 可经环境变量 `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认 120000)提升全局 shell 超时,但**须在 opencode 启动前就绪**(会话中途 `export` 不被 opencode 插件进程继承);per-call `timeout`(见上方长跑 Bash 超时纪律)是跨宿主公共杠杆、会话内即时生效。claude Bash per-call `timeout` 上限 600000ms。

- 面向人读的非代码内容(`sra_manifest.json` 的 `boundaries[]`/文案、增补 requirement/task 正文)用**简体中文**;锚点/路径/frontmatter 原样。
- 增补为 **LLM 候选,需人工复核**。
- 覆盖**取决于变更声明 + 已记业务事实**(未声明 / 未记的看不到)。
- 引用控制**断言存在不断言有效**(承 mgh-init CVE-2025-41248:存在≠有效)。
- 业务记忆为**用户断言,非代码真相**(显式代码/proposal 声明 > 用户记忆 > 默认猜测;冲突时代码为准,manifest 披露)。
- **维度聚焦(`--focus`)收窄了扫描范围**:本次仅扫描聚焦维度(及维度内聚焦 facet),范围外维度**未覆盖**;
  `focus: null` = 全 9 维度(默认)。聚焦是用户显式选择,manifest 披露聚焦维度 + 一条「范围外未覆盖」边界。
- **敏感数据目录(`--sensitive-catalog`)驱动了脱敏缺口检测**:本次据公司目录字段类型逐项查脱敏(at-rest/in-transit/
  log/response),缺口标 `catalog_key` 并经三信号关联 `data-masking` 控制(advisory);目录**外**字段类型仅按现行
  6 facet 识别——**目录非穷尽所有敏感字段**。`sensitive_catalog: null` = 仅 6 facet(默认)。manifest 披露目录
  覆盖范围(字段数 + 类别)+ 一条「目录外仅 6 facet」边界。
- 维度匹配为语义判定,可能误接或漏接;推荐带 `evidence` + 业务域相似理由,供人工复核。
- **codegraph 结构确认是可选 advisory**:`codegraph=on` 时 manifest 记 `counts.call_path_confirmed`/`call_path_residual`
  + `boundaries[]` 披露 codegraph 辅助量与残留(确认 N / 残留 M,**不声称全确认**);codegraph 静态上限(反射/DI/运行时
  分派)缩小但不归零「误接」,`call_path` 为 LLM+codegraph advisory,需人工复核。`--no-codegraph` 一键回退引入前行为。
