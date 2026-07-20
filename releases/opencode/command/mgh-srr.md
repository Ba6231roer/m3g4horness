---
description: Run /mgh-srr on a freeform requirement document (word/txt/md/excel or pasted text — no openspec needed) to get a plain security review report. It dimension-scans the text for security gaps, three-signal matches existing controls (dimension-fit + business-domain + business-fact) against an optional mgh-init inventory, asks batched clarification questions persisted as a cross-iteration business_context.json, and renders a brief Simplified-Chinese report. Reuses the /mgh-sra engine verbatim (no new prompts); output is an LLM candidate needing human review and never touches openspec/.
---

# /mgh-srr — 自由文本安全需求评审(security requirements review)

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / 子任务 / Read / Write / Edit)把流水线
> **跑出来**,而非写成代码。确定性逻辑已在 `ingest_requirements.py` / `render_report.py` + 复用的
> `merge_memory.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,也不要另写 `.py` 去包装或重实现。

> `/mgh-srr` 是 `/mgh-sra` 中间引擎的**端口-适配器**:换上「自由文本输入适配器」+
> 「普通报告输出适配器」,中间引擎(sra-clarify / sra-augment / sra-consistency + 9 维度 +
> 三信号 + 项目记忆)**逐字复用、零新增提示词**。无 openspec 的项目、纯文字需求(word/txt/
> md/excel/透传)也能做安全需求识别 + 部分设计提醒,产物只是一份普通简要报告。

> **运行域**:`install.sh` 向本仓 `.opencode/plugins/` 注入 `tool.execute.before` 插件(`block-adhoc-scripts`),
> 归一化后管道喂**同一** Python 守卫(`.opencode/hooks/block_adhoc_scripts.py`,与 claude 端零差异),在
> `/mgh-srr` 运行域内拦 `py -c`/`python -c` 内省、越权 `Write *.py`、子树外 `Write`/`Edit`。纪律仍由下方铁律
> + 各 producer `--check` 边界校验兜底。`MGH_TARGET`(项目根)供守卫判树。**可靠性边界**:opencode 插件进程不继承
> mid-session bash 导出的 env,故 `MGH_SRR_ACTIVE` 仅在 opencode 启动时已就绪才激活守卫。

You are the **orchestrator** of the mgh-srr flow. Carry it out by running the deterministic
leaf scripts (Bash) and spawning the REUSED sra stage subagents. Shared assets live at
`.opencode/mgh-core/` (mirrored from `core/`).

> **输出是 LLM 候选,非已确认要求。引用控制断言存在、不断言有效。** 每次总结都声明。

## Parse arguments(validate BEFORE spending tokens)

- `--doc <path|dir|->`(输入:`.txt/.md/.csv/.json/.docx/.xlsx` 文件、目录(扫支持文件)、`-`=stdin)
- `--text <str>`(透传:逐字用、跳过抽取;无 `--doc`/`--text` 时读 stdin)
- `--rules <path>`(可选:mgh-init 的 `controls_inventory.json` 文件**或**其输出目录如 `.mgh-init/`)
- `--focus <inline-json|path>`(可选:维度聚焦,收窄本次扫描的安全维度 + 维度内 facet。inline JSON 值以 `{`
  起首,或指向一个 JSON 文件(前导 `@` 可选)。r1 确定性解析 + 闭集校验(任何 LLM 之前);非法 → 退出码 2
  早停。与 `/mgh-sra` 同 shape/语义;复用的 a2/a3 subagent 据其收窄扫描(零新增提示词)。不传 = 全 9 维度,行为不变。
  值清单见 `focus_scope.py --list`)
- `--sensitive-catalog <inline-json|@path|->`(可选:公司强制脱敏目录。inline JSON 值以 `{` 起首,`-`=stdin,或指向一个
  JSON 文件(前导 `@` 可选)。r1 确定性解析 + 闭集校验(任何 LLM 之前);非法 → 退出码 2 早停。与 `/mgh-sra` 同
  shape/语义;复用的 a2/a3 subagent 据其逐项查脱敏缺口(零新增提示词)。与 `--focus` 正交。不传 = 仅现行 6 facet,
  行为不变。默认模板见 `sensitive_catalog.py --list`)
- `--split`(按 markdown `#`/`##` 切成多个评审单元扇出;默认整篇 = 1 单元)
- `--out <dir>`(评审工作目录,默认 `<project>/.mgh-srr/`;报告 + 产物落此)
- `--no-interactive`(澄清问用 `default_guess`;opencode 无原生批量问,默认即走文件回填,此 flag 进一步跳过回填用默认)
- `--dry-run`(仅产 `change_context.json` + stdout 摘要,**不**进 a2–a4/render、不写记忆)
- `--skip-consistency`(跳过 a4 跨单元去重)
- `--config <profile>`(默认 `srr`)
- `--no-codegraph`(跳过可选 codegraph 富化;行为等价引入 codegraph 前)。codegraph 检测默认 `auto`:
  仅当 `<MGH_TARGET>/.codegraph/` 存在**且** PATH 有 `codegraph` 才启用;`--no-codegraph` 或检测不可用
  → 富化 off(零 codegraph 调用、a2/a3 行为与引入 codegraph 前逐字一致)

**无 actionable 参数 / `--help`** → 打印参数表后 **STOP**(零 token、零解析)。

## Orchestrator discipline(铁律)

编排器 = 宿主 agent,**不写代码**。确定性叶脚本经 `Bash` 执行;**NEVER `Read` 叶子 `.py` 源码进上下文**(报错看 stderr,不读源码)。

**硬边界(`NEVER`)**:(a) `Write` 任何 `.py`——大编排器**或**一次性微脚本(`py -c` 产物、`_prep_*.py`、`_aggregate_*.py`);(b) `Bash: py -c|python -c` 去内省/重派生产物(`import json` / `open(` / `load(` 读 `.mgh-srr/**` 或 `change_context.json`);(c) `Read` 叶子 `.py` 源码。

**implementation-intention(需 X → 合法出口 Y,NEVER `py -c`)**:
- **工作清单 + fan-out 路径** → `ingest_requirements.py` stdout 即结构化 `change_context`(含 `pending[]` 每项**绝对** `draft_path`/`done_marker` + `clarify_path` + `candidate_controls` + `memory` + `degraded`);编排器**逐字读该 stdout**、**逐字透传**路径给 subagent;**NEVER** 自拼路径、**NEVER** `py -c` 算路径、**NEVER** 相对路径;
- **瞄一眼结构** → `describe_artifact.py --keys/--sample/--shape/--field`(**NEVER** `py -c`、**NEVER** `Read` 整份大 JSON);
- **派生量** → 该量产出者的 stdout 字段;**NEVER** 自写脚本算。

**fan-out 刚性三元组**:每个 fan-out 步骤表述为 `[输入产物::字段] → script/subagent → [输出产物::字段]`;输出路径 = `ingest_requirements` stdout 的 `pending[].draft_path`/`clarify_path`(绝对),编排器**逐字透传**、subagent **恰好写该绝对路径**(零拼装、零占位符)。

**边界校验**:每个确定性 stage 产物跑完执行 `<producer> --check`;失败(退出码 2)→ 回退重跑该步,**不带着破损产物继续**。报告/manifest **NEVER** 写进 `openspec/`。

## Orchestration flow

```
0. parse + self-check(宿主 agent/model 可用;否则 STOP 给修复提示)
   · **起步**:`Bash: export MGH_SRR_ACTIVE=1`(声明运行域;激活 block-adhoc-scripts 守卫,供 hook 判树/可观测)
1. r1 ingest(Bash,确定性):
     py .opencode/mgh-core/scripts/ingest_requirements.py --doc <path|dir|-> [--text <str>] [--rules <path>] [--focus <inline-json|path>] [--sensitive-catalog <inline-json|@path|->] [--split] [--out <dir>] [--dry-run] [--no-interactive]
   → stdout = 结构化 change_context.json;产物落 <out-dir>/change_context.json
   · 读该 stdout 取:`pending[]`、`clarify_path`、`candidate_controls`、`memory`、`project_root`、`requirements[]`、`degraded`、`focus`、`sensitive_catalog`(**NEVER** `py -c` 重挖)。
     `focus.directive`(简体中文句子;`focus: null` 时缺省)**逐字透传**进 a2/a3 subagent task(NEVER 重解析 / NEVER 自拼);
     `sensitive_catalog`(含 `directive`+`items[]`;`null` 时缺省)**逐字透传**进 a2/a3 subagent task(NEVER 重算 / NEVER 自拼)
   · **MGH_TARGET**:取该 stdout `project_root`(绝对项目根)→ `export MGH_TARGET=<project_root>`
   · **codegraph 检测**(发起任何 LLM subagent 之前;零 LLM token):
     `Bash: if test -d "$MGH_TARGET/.codegraph" && command -v codegraph >/dev/null 2>&1; then echo on; else echo off; fi`
     → `codegraph=on|off`。默认 `auto`(可用即启用);传 `--no-codegraph` 或检测不可用 → `codegraph=off`。该信号
     **逐字透传**进 a2/a3 subagent task 输入。codegraph 是宿主 MCP 工具 / 外部 CLI,**不** import、**不**新增 `pip`
     依赖;`codegraph_explore`(MCP)/ `codegraph explore`(Bash)**均不**命中 block-adhoc-scripts 拦截面——故 **无 hook 改动**。
   · 校验:`py ingest_requirements.py --check <out-dir>/change_context.json`(退出码 2 → 回退重跑)。
     `--rules` 的 inventory well-formed 在 ingest 内自检(畸形即退出 2)。
   · `--dry-run`:到此处 STOP(仅 change_context.json + stdout 摘要,不进 a2–a4/render)
2. a2 clarify(复用 1 subagent,单上下文扫全文):
     spawn sra-clarify({change_context 摘要 + memory + 维度目录路径 + clarify_path(绝对) + focus.directive(逐字,若非 null) + sensitive_catalog(逐字,若非 null) + codegraph 信号(逐字)})
     → 恰好写 clarify_path:`{"clarifications":[...]}`
     · `codegraph=on`(可选 / codegraph-gated / non-fatal):sra-clarify 经 codegraph 预解析**减问**;`codegraph=off` 时无预解析、行为等价引入前
3. 批量澄清交互(opencode 无原生批量问 → 文件回填):
   · 读 clarify_path 的 clarifications[](用 Read 或 describe_artifact;NEVER `py -c`)
   · `--no-interactive` → 全部取 default_guess;否则把 clarifications 渲染成人读 `<out-dir>/clarifications.md`
     (每条:question + why_it_matters + default_guess + 留空 answer),**暂停**等用户回填 answer 字段
   · 用户回填后(或用默认)→ 写 answers.json → `py merge_memory.py --memory <MGH_TARGET>/.mgh-sra/business_context.json --answers <answers.json>`
   · 无澄清 → 跳过本步
4. a3 augment(复用 subagent;per-unit 扇出):
   for each item in change_context.pending[](逐字透传 draft_path/done_marker):
     spawn sra-augment(隔离上下文;给:该单元的 requirements[] + 业务面 + candidate_controls + 增补后 memory
       + 维度目录路径 + focus.directive(逐字,若非 null) + sensitive_catalog(逐字,若非 null) + draft_path(绝对) + done_marker(绝对) + codegraph 信号(逐字))
     → 恰好写 draft_path + touch done_marker
     · `codegraph=on`(可选 / codegraph-gated / non-fatal / bounded):sra-augment 对已三信号命中、已推荐控制的缺口做
       call-path advisory 确认(写 `recommended_control.call_path`);`codegraph=off` / 无 `--rules` → 不产 `call_path`
5. a4 consistency(复用 subagent,除非 --skip-consistency):
     spawn sra-consistency({drafts_dir = <out-dir>/drafts(绝对)}) → 原地覆写各 draft 定稿
6. r2 render(Bash,确定性):
     py .opencode/mgh-core/scripts/render_report.py --drafts-dir <out-dir>/drafts --out <out-dir>
   → security_review_report.md + srr_manifest.json;NEVER 写 openspec/
   · render 读 `change_context.focus`:`focus` 非 null 时报告头注聚焦维度 + `srr_manifest.json` 记 `focus`(维度列表)
     + `boundaries[]` 增一条「本次仅扫描聚焦维度,范围外维度未覆盖」;`focus: null` 时无额外行/边界
   · render 读 `change_context.sensitive_catalog`:非 null 时报告头注目录覆盖范围(字段数 + 类别)+
     `srr_manifest.json` 记 `sensitive_catalog`(`counts`+`source`)+ `boundaries[]` 增一条「据目录逐项查脱敏,
     目录外仅 6 facet」;`sensitive_catalog: null` 时无额外行/边界
   · 校验:`py render_report.py --check <out-dir>`(报告/manifest shape + 无 openspec/ 被触及;退出码 2 → 回退)
   · 校验:`py merge_memory.py --check <MGH_TARGET>/.mgh-sra/business_context.json`
7. 打印产物路径 + 边界声明
   · counts.call_path_confirmed/call_path_residual 取自各 draft(经 describe_artifact 合法瞄结构;NEVER `py -c`);codegraph=off 时二者均 0
```

### Stage → component map

| Stage | How | Asset |
|---|---|---|
| r1 ingest | **script** | `core/scripts/ingest_requirements.py` |
| artifact inspect | **script** | `core/scripts/describe_artifact.py` |
| a2 clarify(单上下文) | subagent `sra-clarify`(复用) | `core/prompts/stages/sra-clarify.md` + `fragments/security-dimensions.md` + `fragments/codegraph-hint.md`(`codegraph=on`) |
| 澄清交互 | 宿主(文件回填) | 渲染 `clarifications.md` 待用户填;`--no-interactive` 用默认 |
| 记忆写回 | **script**(复用) | `core/scripts/merge_memory.py` |
| a3 augment(per-unit 扇出) | subagent `sra-augment`(复用) | `core/prompts/stages/sra-augment.md` + `fragments/security-dimensions.md` + `fragments/codegraph-hint.md`(`codegraph=on`;产 `call_path` advisory) |
| a4 consistency | subagent `sra-consistency`(复用,opt) | `core/prompts/stages/sra-consistency.md` |
| r2 render | **script** | `core/scripts/render_report.py` |
| stage boundary check | **script** | `ingest_requirements`/`render_report`/`merge_memory` `--check` |

### Deterministic invocation (Bash)

```bash
py .opencode/mgh-core/scripts/ingest_requirements.py --doc <path|-> --rules .mgh-init --out .mgh-srr
py .opencode/mgh-core/scripts/ingest_requirements.py --doc <path|-> --focus '{"dimensions":["sensitive-data"],"facets":{"sensitive-data":["id-card","bank-card"]}}' --out .mgh-srr
py .opencode/mgh-core/scripts/ingest_requirements.py --doc <path|-> --sensitive-catalog @.mgh-sra/sensitive_catalog.json --out .mgh-srr
py .opencode/mgh-core/scripts/focus_scope.py --list
py .opencode/mgh-core/scripts/focus_scope.py --parse '{"dimensions":["horizontal-authz"]}'
py .opencode/mgh-core/scripts/sensitive_catalog.py --list
py .opencode/mgh-core/scripts/sensitive_catalog.py --check @.mgh-sra/sensitive_catalog.json
py .opencode/mgh-core/scripts/ingest_requirements.py --check .mgh-srr/change_context.json
py .opencode/mgh-core/scripts/describe_artifact.py --in .mgh-srr/change_context.json --keys
py .opencode/mgh-core/scripts/merge_memory.py --memory <MGH_TARGET>/.mgh-sra/business_context.json --answers <answers.json>
py .opencode/mgh-core/scripts/merge_memory.py --check <MGH_TARGET>/.mgh-sra/business_context.json
py .opencode/mgh-core/scripts/render_report.py --drafts-dir .mgh-srr/drafts --out .mgh-srr
py .opencode/mgh-core/scripts/render_report.py --check .mgh-srr
```

## Output(per `<project>/.mgh-srr/` + `<project>/.mgh-sra/`)

- `change_context.json` / `clarifications.json`(结构化)+ `clarifications.md`(人读回填,opencode)
- `drafts/<unit>.md`(a3/a4,复用 sra shape)、`security_review_report.md`(人读报告)、`srr_manifest.json`(counts + boundaries)
- 项目级(跨 sra/srr):`<project>/.mgh-sra/business_context.json`(与 `/mgh-sra` 同文件同 shape,累积复用)

## Always disclose

- 面向人读的非代码内容用**简体中文**;锚点/路径/frontmatter 原样。
- 产物为 **LLM 候选,需人工复核**;覆盖**取决于需求文档声明 + 已记业务事实**。
- 引用控制**断言存在不断言有效**(存在 ≠ 有效)。
- 业务记忆为**用户断言,非代码真相**(代码声明优先;冲突 manifest 披露)。
- **维度聚焦(`--focus`)收窄了扫描范围**:本次仅扫描聚焦维度(及维度内聚焦 facet),范围外维度**未覆盖**;
  `focus: null` = 全 9 维度(默认)。报告头注 + manifest 披露聚焦维度 + 一条「范围外未覆盖」边界。
- **敏感数据目录(`--sensitive-catalog`)驱动了脱敏缺口检测**:本次据公司目录字段类型逐项查脱敏,缺口标
  `catalog_key`;目录**外**字段类型仅按现行 6 facet 识别——**目录非穷尽所有敏感字段**。`sensitive_catalog: null`
  = 仅 6 facet(默认)。报告头注 + manifest 披露目录覆盖范围 + 一条「目录外仅 6 facet」边界。
- **codegraph 结构确认是可选 advisory**:`codegraph=on` 时 manifest 记 `counts.call_path_confirmed`/`call_path_residual`
  + `boundaries[]` 披露(确认 N / 残留 M,**不声称全确认**);`--no-codegraph` 一键回退引入前行为。
- **SRR 专属**:输入抽取对 `.docx`/`.xlsx` 有已知降级(日期 / 格式 / 列表编号);`--text`/stdin 透传无降级;
  报告质量受输入完整度上界约束——含糊的需求文档只能产锚点稀疏的泛化缺口。
