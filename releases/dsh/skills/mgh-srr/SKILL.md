---
name: mgh-srr
description: Run /mgh-srr on a freeform requirement document (word/txt/md/excel or pasted text — no openspec needed) to get a plain security review report. It dimension-scans the text for security gaps, three-signal matches existing controls (dimension-fit + business-domain + business-fact) against an optional mgh-init inventory, asks batched clarification questions persisted as a cross-iteration business_context.json, and renders a brief Simplified-Chinese report. Reuses the /mgh-sra engine verbatim (no new prompts); output is an LLM candidate needing human review and never touches openspec/.
user-invocable: true
disable-model-invocation: true
---

# /mgh-srr — 自由文本安全需求评审(security requirements review)

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / 子任务 / Read / Write / Edit)把流水线
> **跑出来**,而非写成代码。确定性逻辑已在 `ingest_requirements.py` / `render_report.py` + 复用的
> `merge_memory.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,也不要另写 `.py` 去包装或重实现。

> `/mgh-srr` 是 `/mgh-sra` 中间引擎的**端口-适配器**:换上「自由文本输入适配器」+
> 「普通报告输出适配器」,中间引擎(sra-clarify / sra-augment / sra-consistency + 9 维度 +
> 三信号 + 项目记忆)**逐字复用、零新增提示词**。无 openspec 的项目、纯文字需求(word/txt/
> md/excel/透传)也能做安全需求识别 + 部分设计提醒,产物只是一份普通简要报告。

> **运行域**:dsh 端执行边界 = 守卫三面执法(读/写/Bash 净网)+ 宿主 approval/sandbox(顶替 claude 端
> `allowed-tools` 白名单,诚实披露)——单一判定源 `mgh-core/dsh/block_adhoc_scripts.py`,经 profile
> 受管块接线的 `mgh-core/dsh/mgh-guard.ts` 在工具执行前喂入归一化事件,在
> `/mgh-srr` 运行域内拦 `py -c`/`python -c` 内省、**一切脚本扩展名写入**(`.py`/`.ps1`/`.sh`/`.ts`/…;叶脚本 read-only)、
> 子树外 `Write`/`Edit`。纪律仍由下方铁律 + 各 producer `--check` 边界校验兜底。`MGH_TARGET`(项目根)供守卫判树。
> 编排器**起步先** `bash: export MGH_SRR_ACTIVE=1` + 写磁盘哨兵 `<project>/.mgh-srr/.active`,r1 后 `export MGH_TARGET=<绝对项目根>`
> 并重写哨兵 `target`。守卫激活 = env **或** 磁盘哨兵——**哨兵关闭了宿主 shim 进程不继承 mid-session bash 导出 env
> 的可靠性边界**(见 `core/contracts/hooks/runtime-enforcement.md`)。

> **召唤语义(dsh)**:`/mgh-srr` 由用户显式召唤(本 skill 对模型自触发关闭);其后同一用户消息的
> 余文即参数,**step 0 从触发消息逐字读取**(dsh 无 `$ARGUMENTS` 模板、参数零预处理)。

You are the **orchestrator** of the mgh-srr flow. Carry it out by running the deterministic
leaf scripts (Bash) and delegating to the REUSED sra named stage tools (`mgh_sra_*`,
composed by the mgh profile; see「dsh 派发面」). Shared assets live at
`mgh-core/` (mirrored from `core/`).

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
- `--no-interactive`(澄清问用 `default_guess`;dsh 经宿主 `ask_user_question` 原生批量问(headless/无问答通道时文件回填兜底),此 flag 跳过问答直接取默认)
- `--dry-run`(仅产 `change_context.json` + stdout 摘要,**不**进 a2–a4/render、不写记忆)
- `--skip-consistency`(跳过 a4 跨单元去重)
- `--config <profile>`(默认 `srr`)
- `--no-codegraph`(跳过可选 codegraph 富化;行为等价引入 codegraph 前)。codegraph 检测默认 `auto`:
  仅当 `<MGH_TARGET>/.codegraph/` 存在**且** PATH 有 `codegraph` 才启用;`--no-codegraph` 或检测不可用
  → 富化 off(零 codegraph 调用、a2/a3 行为与引入 codegraph 前逐字一致)
- **请求上下文预算**(`request-context-budget`,确定性边界强制每次大模型请求 ≤ 阈值;单位字节):
  `--max-unit-bytes <N>`(单 fan-out 单元物化输入上限,默认 192KB;oversize 单元标 `oversize` + recipe,**不**切分——单元是评审原子)·
  `--orch-budget-bytes <N>`(编排器单次请求可见的待办壳页上限,默认 64KB;超则自动分页收紧,stdout `shrunk:true`)·
  `--max-aggregate-bytes <N>`(render 聚合输入上限,默认 96KB;P0 软边界,超则建议 `--split`/`--focus` + `srr_manifest.json::boundaries[]`/报告披露)

**无 actionable 参数 / `--help`** → 打印参数表后 **STOP**(零 token、零解析)。

## Orchestrator discipline(铁律)

编排器 = 宿主 agent,**不写代码**。确定性叶脚本经 `Bash` 执行;**NEVER `Read` 叶子 `.py` 源码进上下文**(报错看 stderr,不读源码)。

**硬边界(`NEVER`)**:(a) `Write` 任何 `.py`——大编排器**或**一次性微脚本(`py -c` 产物、`_prep_*.py`、`_aggregate_*.py`);(b) `Bash: py -c|python -c` 去内省/重派生产物(`import json` / `open(` / `load(` 读 `.mgh-srr/**` 或 `change_context.json`);(c) `Read` 叶子 `.py` 源码。

**`NEVER` 向系统临时目录写中间文件再回读**:确定性脚本 stdout 在 Bash tool result(最后一行是 JSON),直接消费;NEVER 重定向到 `$env:TEMP`/`%TEMP%`/`/tmp` 再回读。

**implementation-intention(需 X → 合法出口 Y,NEVER `py -c`)**:
- **工作清单 + fan-out 路径** → `ingest_requirements.py --materialize <out-dir>/inputs/augment` stdout 即 **slim 分页**摘要(`pending[]` 每项**绝对** `draft_path`/`done_marker`/`input_path`/`bytes`/`oversize` + `clarify_path` + `offset`/`limit`/`effective_limit`/`shrunk`);编排器**逐字读该 slim stdout**、**逐字透传** `input_path` 给复用的 sra 引擎 stage(subagent **自读** `input_path`,≤ `--max-unit-bytes`);**NEVER** 整份读 sra-shape `change_context.json`、**NEVER** 自拼路径、**NEVER** `py -c` 算路径、**NEVER** 相对路径、**NEVER** 把单元记录内联塞进 subagent task(只透传 `input_path`);
- **瞄一眼结构** → `describe_artifact.py --keys/--sample/--shape/--field`(**NEVER** `py -c`、**NEVER** `Read` 整份大 JSON);
- **派生量** → 该量产出者的 stdout 字段;**NEVER** 自写脚本算。

**fan-out 刚性三元组**:每个 fan-out 步骤表述为 `[输入产物::字段] → script/subagent → [输出产物::字段]`;路径 = `ingest_requirements` stdout 的 `pending[].input_path`(subagent 读)/`draft_path`/`clarify_path`(绝对),编排器**逐字透传**、subagent **自读 `input_path`** + **恰好写 `draft_path`**(零拼装、零占位符)。

> **dsh 派发面(已接线)**:本壳 a2/a3/a4 复用 `/mgh-sra` 的**具名派发工具实例**(mgh profile
> 组合;`mgh_sra_clarify` / `mgh_sra_augment` / `mgh_sra_consistency`,persona 构建期装载、工具面
> 白名单内置,零新增实例)。运行至派发步 SHALL **按名调用**对应工具(绝对路径逐字透传),
> **NEVER** 以泛型 subagent 顶替、**NEVER** 用内联执行假装派发;若当前会话无这些工具(= 未经
> `dsh --profile mgh` 启动或 install 未接线)SHALL 停止并如实报告:重跑 `install.sh --dsh <target>`
> 后经该 profile 启动(进度已在磁盘、可跨会话续跑)。

**边界校验**:每个确定性 stage 产物跑完执行 `<producer> --check`;失败(退出码 2)→ 回退重跑该步,**不带着破损产物继续**。报告/manifest **NEVER** 写进 `openspec/`。

## Orchestration flow

> **REQUIRED SUB-SKILL: Use srr-flow-dsh** — 执行任一 flow 步骤之前 MUST `read`
> `mgh-core/prompts/fragments/srr-flow-dsh.md`(完整 step 0–7:运行域 + 哨兵激活 → r1
> ingest+materialize → a2 clarify → 批量澄清 → a3 augment 扇出 → a4 consistency → r2 render 报告 →
> manifest + 哨兵移除)。壳内保留:参数表 / 铁律 / Stage→component 表 / 确定性调用面 / 产物 / 边界披露。

骨架:0 self-check → 1 r1 ingest → 2 a2 clarify → 3 批量澄清 → 4 a3 augment(扇出)→ 5 a4
consistency → 6 r2 render → 7 manifest + 收尾(哨兵移除)。

### Stage → component map

| Stage | How | Asset |
|---|---|---|
| r1 ingest | **script** | `core/scripts/ingest_requirements.py` |
| artifact inspect | **script** | `core/scripts/describe_artifact.py` |
| a2 clarify(单上下文) | 具名工具 `mgh_sra_clarify`(复用) | `core/prompts/stages/sra-clarify.md` + `fragments/security-dimensions.md` + `fragments/codegraph-hint.md`(`codegraph=on`) |
| 澄清交互 | 宿主(文件回填) | 渲染 `clarifications.md` 待用户填;`--no-interactive` 用默认 |
| 记忆写回 | **script**(复用) | `core/scripts/merge_memory.py` |
| a3 augment(per-unit 扇出) | 具名工具 `mgh_sra_augment`(复用) | `core/prompts/stages/sra-augment.md` + `fragments/security-dimensions.md` + `fragments/codegraph-hint.md`(`codegraph=on`;产 `call_path` advisory) |
| a4 consistency | 具名工具 `mgh_sra_consistency`(复用,opt) | `core/prompts/stages/sra-consistency.md` |
| r2 render | **script** | `core/scripts/render_report.py` |
| stage boundary check | **script** | `ingest_requirements`/`render_report`/`merge_memory` `--check` |

### Deterministic invocation (Bash)

**长跑 Bash 超时纪律**:给 `ingest_requirements`/`render_report` 等长跑确定性 Bash 调用传一个慷慨的 per-call `timeout`(dsh 工具调用接受显式毫秒 `timeout` 入参,受部署上限收敛),勿依赖默认超时中途强杀。

```bash
py mgh-core/scripts/ingest_requirements.py --doc <path|-> --rules .mgh-init --out .mgh-srr
py mgh-core/scripts/ingest_requirements.py --doc <path|-> --focus '{"dimensions":["sensitive-data"],"facets":{"sensitive-data":["id-card","bank-card"]}}' --out .mgh-srr
py mgh-core/scripts/ingest_requirements.py --doc <path|-> --sensitive-catalog @.mgh-sra/sensitive_catalog.json --out .mgh-srr
py mgh-core/scripts/ingest_requirements.py --doc <path|-> --split --out .mgh-srr --materialize .mgh-srr/inputs/augment --offset 0 --limit 50 --max-unit-bytes 196608 --orch-budget-bytes 65536
py mgh-core/scripts/focus_scope.py --list
py mgh-core/scripts/focus_scope.py --parse '{"dimensions":["horizontal-authz"]}'
py mgh-core/scripts/sensitive_catalog.py --list
py mgh-core/scripts/sensitive_catalog.py --check @.mgh-sra/sensitive_catalog.json
py mgh-core/scripts/ingest_requirements.py --check .mgh-srr/change_context.json
py mgh-core/scripts/describe_artifact.py --in .mgh-srr/change_context.json --keys
py mgh-core/scripts/merge_memory.py --memory <MGH_TARGET>/.mgh-sra/business_context.json --answers <answers.json>
py mgh-core/scripts/merge_memory.py --check <MGH_TARGET>/.mgh-sra/business_context.json
py mgh-core/scripts/render_report.py --drafts-dir .mgh-srr/drafts --out .mgh-srr --max-aggregate-bytes 98304
py mgh-core/scripts/render_report.py --check .mgh-srr
```

## Output(per `<project>/.mgh-srr/` + `<project>/.mgh-sra/`)

- `change_context.json` / `clarifications.json`(结构化)+ `clarifications.md`(人读回填,无问答通道兜底)
- `inputs/augment/<unit>.input.json`(per-unit 物化输入,a3 subagent 自读,≤ `--max-unit-bytes`)、`drafts/<unit>.md`(a3/a4,复用 sra shape)、`security_review_report.md`(人读报告)、`srr_manifest.json`(counts + boundaries)
- 项目级(跨 sra/srr):`<project>/.mgh-sra/business_context.json`(与 `/mgh-sra` 同文件同 shape,累积复用)

## Always disclose

- **请求上下文预算(确定性边界)**:每次大模型请求 ≤ 配置阈值(`--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes`);`oversize`/`shrunk`/聚合超限在 `srr_manifest.json::boundaries[]` + 报告披露(无静默溢出)。**P0 软边界**:render 聚合节点目前为「披露 + `--split`/`--focus` 回退」,分层归约留后续;**不声称** P0 已对聚合节点提供硬阈值。扇出 per-unit 输入 + 编排器请求确定性有界。
- **宿主 shell 超时**:dsh 工具调用经显式毫秒 `timeout` 入参传 per-call 超时(受部署上限收敛、会话内即时生效);per-call `timeout`(见上方长跑 Bash 超时纪律)是跨宿主公共杠杆。其余宿主备查:opencode 可经环境变量 `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认 120000,须启动前就绪、会话中途 export 不被插件进程继承)提升全局默认;claude Bash per-call `timeout` 上限 600000ms。

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
