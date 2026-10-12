---
name: mgh-sra
description: After an openspec 'propose', run /mgh-sra to dimension-scan the change's specs/tasks for security gaps and augment them with anchored, reuse-existing-controls requirements + tasks. Three-signal semantic matching (dimension-fit + business-domain + business-fact) against an optional mgh-init inventory; batched clarification persisted as a cross-iteration business_context.json. Idempotent non-destructive managed-block merge. Augmentations are LLM candidates needing human review.
user-invocable: true
disable-model-invocation: true
---

# /mgh-sra — openspec 安全设计补充(security requirements augmentation)

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / 子任务 / Read / Write / Edit)把流水线
> **跑出来**,而非写成代码——确定性逻辑已在 `prepare_augment.py` / `merge_augment.py` /
> `merge_memory.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,也不要另写 `.py` 去包装或重实现。

> **运行域**:dsh 端执行边界 = 守卫三面执法(读/写/Bash 净网)+ 宿主 approval/sandbox(顶替 claude 端
> `allowed-tools` 白名单,诚实披露)——单一判定源 `mgh-core/dsh/block_adhoc_scripts.py`,经 profile
> 受管块接线的 `mgh-core/dsh/mgh-guard.ts` 在工具执行前喂入归一化事件,在
> `/mgh-sra` 运行域内拦 `py -c`/`python -c` 内省、**一切脚本扩展名写入**(`.py`/`.ps1`/`.sh`/`.ts`/…;叶脚本 read-only)、
> 子树外 `Write`/`Edit`。纪律仍由下方铁律 + 各 producer `--check` 边界校验兜底。`MGH_TARGET`(项目根)供守卫判树。
> 编排器**起步先** `bash: export MGH_SRA_ACTIVE=1` + 写磁盘哨兵 `<project>/.mgh-sra/.active`,a1 后 `export MGH_TARGET=<绝对项目根>`
> 并重写哨兵 `target`。守卫激活 = env **或** 磁盘哨兵——**哨兵关闭了宿主 shim 进程不继承 mid-session bash 导出 env
> 的可靠性边界**(见 `core/contracts/hooks/runtime-enforcement.md`)。

> **召唤语义(dsh)**:`/mgh-sra` 由用户显式召唤(本 skill 对模型自触发关闭);其后同一用户消息的
> 余文即参数,**step 0 从触发消息逐字读取**(dsh 无 `$ARGUMENTS` 模板、参数零预处理)。

You are the **orchestrator** of the mgh-sra flow. Carry it out by running the deterministic
leaf scripts (Bash) and delegating stage work to the named stage tools (`mgh_sra_*`,
composed by the mgh profile; see「dsh 派发面」). Shared assets live at `mgh-core/`
(mirrored from `core/`).

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
- `--no-interactive`(澄清问用 `default_guess`;dsh 经宿主 `ask_user_question` 原生批量问(headless/无问答通道时文件回填兜底),此 flag 跳过问答直接取默认)
- `--dry-run`(仅产 `change_context.json` + stdout 摘要,**不写** specs/tasks/记忆)
- `--skip-consistency`(跳过 a4 跨类去重)
- `--config <profile>`(默认 `sra`)
- `--no-codegraph`(跳过可选 codegraph 富化;行为等价于引入 codegraph 前)。codegraph 检测默认 `auto`:仅当
  `<MGH_TARGET>/.codegraph/` 存在**且** PATH 有 `codegraph` 才启用;`--no-codegraph` 或检测不可用 → 富化 off(零
  codegraph 调用、a2/a3 行为与引入 codegraph 前逐字一致)
- **请求上下文预算**(`request-context-budget`,确定性边界强制每次大模型请求 ≤ 阈值;单位字节):
  `--max-unit-bytes <N>`(单 capability 物化输入上限,默认 192KB;oversize 标 `oversize` + recipe,**不**切分——capability 是 a3 原子)·
  `--orch-budget-bytes <N>`(编排器单次请求可见的待办壳页上限,默认 64KB;超则自动分页收紧,stdout `shrunk:true`)·
  `--max-aggregate-bytes <N>`(a2/a4 聚合输入上限,默认 96KB;P0 软边界,超则建议 `--focus`/分变更 + `sra_manifest.json::boundaries[]` 披露)

**无 actionable 参数 / `--help`** → 打印参数表后 **STOP**(零 token、零解析)。

## Orchestrator discipline(铁律)

编排器 = 宿主 agent,**不写代码**。确定性叶脚本经 `Bash` 执行;**NEVER `Read` 叶子 `.py` 源码进上下文**(报错看 stderr,不读源码)。

**硬边界(`NEVER`)**:(a) `Write` 任何 `.py`——大编排器**或**一次性微脚本(`py -c` 产物、`_prep_*.py`、`_aggregate_*.py`);(b) `Bash: py -c|python -c` 去内省/重派生产物(`import json` / `open(` / `load(` 读 `.mgh-sra/**` 或 `change_context.json`);(c) `Read` 叶子 `.py` 源码。

**`NEVER` 向系统临时目录写中间文件再回读**:确定性脚本 stdout 在 Bash tool result(最后一行是 JSON),直接消费;NEVER 重定向到 `$env:TEMP`/`%TEMP%`/`/tmp` 再回读。

**implementation-intention(需 X → 合法出口 Y,NEVER `py -c`)**:
- **工作清单 + fan-out 路径** → `prepare_augment.py --materialize` stdout 即 **slim 分页**待办壳(含 `pending[]` 每项**绝对** `draft_path`/`done_marker`/`input_path`/`bytes`/`oversize` + `clarify_path` + `project_root` + `offset`/`effective_limit`/`shrunk`);编排器**逐字读该 stdout**、**逐字透传**路径给 subagent;**NEVER** 自拼 `<change-root>/<cap>`、**NEVER** `py -c` 算路径、**NEVER** 相对路径;
- **需某 cap 完整输入** → `prepare_augment --materialize` stdout 的 `pending[].input_path`(绝对,该 cap 的 requirements + 业务面 + candidate_controls 切片 + memory);**NEVER** 整份读 `change_context.json`、**NEVER** `py -c`、**NEVER** 内联传记录给 subagent(subagent **自读** `input_path`);
- **瞄一眼结构** → `describe_artifact.py --keys/--sample/--shape/--field`(**NEVER** `py -c`、**NEVER** `Read` 整份大 JSON);
- **派生量** → 该量产出者的 stdout 字段(`prepare` stdout `requirements_count`/`candidate_controls_count`);**NEVER** 自写脚本算。

**fan-out 刚性三元组**:每个 fan-out 步骤表述为 `[输入产物::字段] → script/subagent → [输出产物::字段]`;路径 = `prepare_augment` stdout 的 `pending[].input_path`(subagent 读)/`draft_path`/`clarify_path`(绝对),编排器**逐字透传**、subagent **自读 `input_path`** + **恰好写 `draft_path`**(零拼装、零占位符)。

> **dsh 派发面(已接线)**:本壳 a2/a3/a4 的 stage 子代理 = mgh profile 组合的**具名派发工具实例**
> (`mgh_sra_clarify` / `mgh_sra_augment` / `mgh_sra_consistency`;persona 构建期装载、工具面白名单
> 内置)。运行至派发步 SHALL **按名调用**对应工具(绝对路径逐字透传),**NEVER** 以泛型 subagent
> 顶替、**NEVER** 用内联执行假装派发;若当前会话无这些工具(= 未经 `dsh --profile mgh` 启动或
> install 未接线)SHALL 停止并如实报告:重跑 `install.sh --dsh <target>` 后经该 profile 启动
> (进度已在磁盘、可跨会话续跑)。

**边界校验**:每个确定性 stage 产物跑完执行 `<producer> --check`;失败(退出码 2)→ 回退重跑该步,**不带着破损产物继续**。

## Orchestration flow

> **REQUIRED SUB-SKILL: Use sra-flow-dsh** — 执行任一 flow 步骤之前 MUST `read`
> `mgh-core/prompts/fragments/sra-flow-dsh.md`(完整 step 0–7:运行域 + 哨兵激活 → a1
> prepare+materialize → a2 clarify → 批量澄清 → a3 augment 扇出 → a4 consistency → a5 merge →
> manifest + 哨兵移除)。壳内保留:参数表 / 铁律 / Stage→component 表 / 确定性调用面 / 产物 / 边界披露。

骨架:0 self-check → 1 a1 prepare → 2 a2 clarify → 3 批量澄清 → 4 a3 augment(扇出)→ 5 a4
consistency → 6 a5 merge → 7 manifest + 收尾(哨兵移除)。

### Stage → component map

| Stage | How | Asset |
|---|---|---|
| a1 prepare | **script** | `core/scripts/prepare_augment.py` |
| artifact inspect | **script** | `core/scripts/describe_artifact.py` |
| a2 clarify(单上下文) | 具名工具 `mgh_sra_clarify` | `core/prompts/stages/sra-clarify.md` + `fragments/security-dimensions.md` + `fragments/codegraph-hint.md`(`codegraph=on`) |
| 澄清交互 | 宿主(文件回填) | 渲染 `clarifications.md` 待用户填;`--no-interactive` 用默认 |
| 记忆写回 | **script** | `core/scripts/merge_memory.py` |
| a3 augment(per-cap 扇出) | 具名工具 `mgh_sra_augment` | `core/prompts/stages/sra-augment.md` + `fragments/security-dimensions.md` + `fragments/codegraph-hint.md`(`codegraph=on`;产 `call_path` advisory) |
| a4 consistency | 具名工具 `mgh_sra_consistency`(opt) | `core/prompts/stages/sra-consistency.md` |
| a5 合并(确定性) | **script** | `core/scripts/merge_augment.py` |
| stage boundary check | **script** | `prepare_augment`/`merge_augment`/`merge_memory` `--check` |

### Deterministic invocation (Bash)

**长跑 Bash 超时纪律**:给 `prepare_augment`/`merge_augment`/`merge_memory` 等长跑确定性 Bash 调用传一个慷慨的 per-call `timeout`(dsh 工具调用接受显式毫秒 `timeout` 入参,受部署上限收敛),勿依赖默认超时中途强杀。

```bash
py mgh-core/scripts/prepare_augment.py --change <change> --rules .mgh-init
py mgh-core/scripts/prepare_augment.py --change <change> --rules .mgh-init --materialize .mgh-sra/inputs/augment --offset 0 --limit 50 --max-unit-bytes 196608 --orch-budget-bytes 65536
py mgh-core/scripts/prepare_augment.py --change <change> --focus '{"dimensions":["horizontal-authz","vertical-authz"]}'
py mgh-core/scripts/prepare_augment.py --change <change> --focus config/focus.json
py mgh-core/scripts/prepare_augment.py --change <change> --sensitive-catalog @.mgh-sra/sensitive_catalog.json
py mgh-core/scripts/focus_scope.py --list
py mgh-core/scripts/focus_scope.py --parse '{"dimensions":["sensitive-data"],"facets":{"sensitive-data":["id-card","bank-card"]}}'
py mgh-core/scripts/sensitive_catalog.py --list
py mgh-core/scripts/sensitive_catalog.py --parse @.mgh-sra/sensitive_catalog.json
py mgh-core/scripts/sensitive_catalog.py --check @.mgh-sra/sensitive_catalog.json
py mgh-core/scripts/prepare_augment.py --check .mgh-init
py mgh-core/scripts/describe_artifact.py --in <change-root>/.mgh-sra/change_context.json --keys
py mgh-core/scripts/merge_memory.py --memory <MGH_TARGET>/.mgh-sra/business_context.json --answers <answers.json>
py mgh-core/scripts/merge_memory.py --check <MGH_TARGET>/.mgh-sra/business_context.json
py mgh-core/scripts/merge_augment.py --change <change>
py mgh-core/scripts/merge_augment.py --check <change>
```

## Output(per `<change-root>/.mgh-sra/` + `<project>/.mgh-sra/`)

- `change_context.json`(全量落盘供 a2 单上下文扫全变更读)/ `inputs/augment/<cap>.input.json`(per-capability 物化输入,a3 subagent 自读;≤ `--max-unit-bytes`)/ `clarifications.json`(结构化)+ `clarifications.md`(人读回填,无问答通道兜底)
- `drafts/<cap>.md`(a3/a4)、`merge_state.json`(a5 块外快照)、`sra_manifest.json`(counts + boundaries)
- 受管块追加进变更本身:`specs/<cap>/spec.md` + `tasks.md`
- 项目级(跨变更):`<project>/.mgh-sra/business_context.json`

## Always disclose

- **请求上下文预算(确定性边界)**:每次大模型请求 ≤ 配置阈值(`--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes`);`oversize`/`shrunk`/聚合超限在 `sra_manifest.json::boundaries[]` 披露(无静默溢出)。**P0 软边界**:a2/a4 聚合节点目前为「披露 + `--focus`/分变更 回退」,分层归约留后续;**不声称** P0 已对聚合节点提供硬阈值。a3 per-capability 输入 + 编排器请求确定性有界。

- **宿主 shell 超时**:dsh 工具调用经显式毫秒 `timeout` 入参传 per-call 超时(受部署上限收敛、会话内即时生效);per-call `timeout`(见上方长跑 Bash 超时纪律)是跨宿主公共杠杆。其余宿主备查:opencode 可经环境变量 `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认 120000,须启动前就绪、会话中途 export 不被插件进程继承)提升全局默认;claude Bash per-call `timeout` 上限 600000ms。

- 面向人读的非代码内容用**简体中文**;锚点/路径/frontmatter 原样。
- 增补为 **LLM 候选,需人工复核**;覆盖**取决于变更声明 + 已记业务事实**。
- 引用控制**断言存在不断言有效**(承 mgh-init CVE-2025-41248)。
- 业务记忆为**用户断言,非代码真相**(代码声明优先;冲突 manifest 披露)。
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
