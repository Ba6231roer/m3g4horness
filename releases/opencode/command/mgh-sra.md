---
description: After an openspec 'propose', run /mgh-sra to dimension-scan the change's specs/tasks for security gaps and augment them with anchored, reuse-existing-controls requirements + tasks. Three-signal semantic matching (dimension-fit + business-domain + business-fact) against an optional mgh-init inventory; batched clarification persisted as a cross-iteration business_context.json. Idempotent non-destructive managed-block merge. Augmentations are LLM candidates needing human review.
---

# /mgh-sra — openspec 安全设计补充(security requirements augmentation)

> 编排器 = 你(宿主 agent):按本提示词,用自身工具(Bash / 子任务 / Read / Write / Edit)把流水线
> **跑出来**,而非写成代码——确定性逻辑已在 `prepare_augment.py` / `merge_augment.py` /
> `merge_memory.py` 里,直接 `Bash` 调用即可,无需 `Read` 其源码,也不要另写 `.py` 去包装或重实现。

> **运行域**:`install.sh` 向本仓 `.opencode/plugins/` 注入 `tool.execute.before` 插件(`block-adhoc-scripts`),
> 归一化后管道喂**同一** Python 守卫(`.opencode/hooks/block_adhoc_scripts.py`,与 claude 端零差异),在
> `/mgh-sra` 运行域内拦 `py -c`/`python -c` 内省、越权 `Write *.py`、子树外 `Write`/`Edit`。纪律仍由下方铁律
> + 各 producer `--check` 边界校验兜底。`MGH_TARGET`(项目根)供守卫判树。**可靠性边界**:opencode 插件进程不继承
> mid-session bash 导出的 env,故 `MGH_SRA_ACTIVE` 仅在 opencode 启动时已就绪才激活守卫。

You are the **orchestrator** of the mgh-sra flow. Carry it out by running the deterministic
leaf scripts (Bash) and spawning stage subagents. Shared assets live at `.opencode/mgh-core/`
(mirrored from `core/`).

> **输出是 LLM 候选,非已确认要求。引用控制断言存在、不断言有效。** 每次总结都声明。

## Parse arguments(validate BEFORE spending tokens)

- `--change <name>`(默认取 `openspec/changes/` 下最新未归档变更;无则报错 STOP)
- `--rules <path>`(可选:mgh-init 的 `controls_inventory.json` 文件**或**其输出目录如 `.mgh-init/`)
- `--no-interactive`(澄清问用 `default_guess`;opencode 无原生批量问,默认即走文件回填,此 flag 进一步跳过回填用默认)
- `--dry-run`(仅产 `change_context.json` + stdout 摘要,**不写** specs/tasks/记忆)
- `--skip-consistency`(跳过 a4 跨类去重)
- `--config <profile>`(默认 `sra`)
- `--no-codegraph`(跳过可选 codegraph 富化;行为等价于引入 codegraph 前)。codegraph 检测默认 `auto`:仅当
  `<MGH_TARGET>/.codegraph/` 存在**且** PATH 有 `codegraph` 才启用;`--no-codegraph` 或检测不可用 → 富化 off(零
  codegraph 调用、a2/a3 行为与引入 codegraph 前逐字一致)

**无 actionable 参数 / `--help`** → 打印参数表后 **STOP**(零 token、零解析)。

## Orchestrator discipline(铁律)

编排器 = 宿主 agent,**不写代码**。确定性叶脚本经 `Bash` 执行;**NEVER `Read` 叶子 `.py` 源码进上下文**(报错看 stderr,不读源码)。

**硬边界(`NEVER`)**:(a) `Write` 任何 `.py`——大编排器**或**一次性微脚本(`py -c` 产物、`_prep_*.py`、`_aggregate_*.py`);(b) `Bash: py -c|python -c` 去内省/重派生产物(`import json` / `open(` / `load(` 读 `.mgh-sra/**` 或 `change_context.json`);(c) `Read` 叶子 `.py` 源码。

**implementation-intention(需 X → 合法出口 Y,NEVER `py -c`)**:
- **工作清单 + fan-out 路径** → `prepare_augment.py` stdout 即结构化 `change_context`(含 `pending[]` 每项**绝对** `draft_path`/`done_marker` + `clarify_path` + `candidate_controls` + `memory`);编排器**逐字读该 stdout**、**逐字透传**路径给 subagent;**NEVER** 自拼 `<change-root>/<cap>`、**NEVER** `py -c` 算路径、**NEVER** 相对路径;
- **瞄一眼结构** → `describe_artifact.py --keys/--sample/--shape/--field`(**NEVER** `py -c`、**NEVER** `Read` 整份大 JSON);
- **派生量** → 该量产出者的 stdout 字段;**NEVER** 自写脚本算。

**fan-out 刚性三元组**:每个 fan-out 步骤表述为 `[输入产物::字段] → script/subagent → [输出产物::字段]`;输出路径 = `prepare_augment` stdout 的 `pending[].draft_path`/`clarify_path`(绝对),编排器**逐字透传**、subagent **恰好写该绝对路径**(零拼装、零占位符)。

**边界校验**:每个确定性 stage 产物跑完执行 `<producer> --check`;失败(退出码 2)→ 回退重跑该步,**不带着破损产物继续**。

## Orchestration flow

```
0. parse + self-check(宿主 agent/model 可用;否则 STOP 给修复提示)
   · **起步**:`Bash: export MGH_SRA_ACTIVE=1`(声明运行域;激活 block-adhoc-scripts 守卫,供 hook 判树/可观测)
1. a1 prepare(Bash,确定性):
     py .opencode/mgh-core/scripts/prepare_augment.py --change <change> [--rules <path>] [--dry-run] [--no-interactive]
   → stdout = 结构化 change_context.json;产物落 <change-root>/.mgh-sra/change_context.json
   · 读该 stdout 取:`pending[]`、`clarify_path`、`candidate_controls`、`memory`、`project_root`(**NEVER** `py -c` 重挖)
   · **MGH_TARGET**:取该 stdout `project_root`(绝对项目根)→ `export MGH_TARGET=<project_root>`
   · **codegraph 检测**(发起任何 LLM subagent 之前;零 LLM token):
     `Bash: if test -d "$MGH_TARGET/.codegraph" && command -v codegraph >/dev/null 2>&1; then echo on; else echo off; fi`
     → `codegraph=on|off`。默认 `auto`(可用即启用);传 `--no-codegraph` 或检测不可用 → `codegraph=off`。该信号
     **逐字透传**进 a2/a3 subagent task 输入(仅 `codegraph=on` 时:sra-clarify 启用 advisory 预解析减问、sra-augment
     启用外科式上下文 + 对已推荐控制做 call-path advisory 确认)。codegraph 是宿主 MCP 工具 / 外部 CLI,**不** import、
     **不**新增 `pip` 依赖;`codegraph_explore`(MCP)/ `codegraph explore`(Bash)**均不**命中 block-adhoc-scripts
     拦截面(非 `py -c`/`Write *.py`/子树外写)——故 **无 hook 改动**。
   · 校验:有 `--rules` 时 `py prepare_augment.py --check <rules-path>`(退出码 2 → 回退或 advisory 无控制继续)
   · `--dry-run`:到此处 STOP(仅 change_context.json + stdout 摘要,不进 a2–a5)
2. a2 clarify(1 subagent,单上下文扫全变更):
     spawn sra-clarify({change_context 摘要 + memory + 维度目录路径 + clarify_path(绝对) + codegraph 信号(逐字)})
     → 恰好写 clarify_path:`{"clarifications":[...]}`
     · `codegraph=on`(可选 / codegraph-gated / non-fatal):sra-clarify 经 codegraph 预解析(callers→角色 / callees→敏感
       字段 / domain-sibling→鉴权范式)**减问**——仅减问(codegraph-sourced 事实优先级低于用户/代码/已记,不覆盖)、
       **不增写** codegraph 派生记忆;`codegraph=off` 时无预解析、行为等价引入前
3. 批量澄清交互(opencode 无原生批量问 → 文件回填):
   · 读 clarify_path 的 clarifications[](用 Read 或 describe_artifact;NEVER `py -c`)
   · `--no-interactive` → 全部取 default_guess;否则把 clarifications 渲染成人读 `<change-root>/.mgh-sra/clarifications.md`
     (每条:question + why_it_matters + default_guess + 留空 answer),**暂停**等用户回填 answer 字段
   · 用户回填后(或用默认)→ 写 answers.json → `py merge_memory.py --memory <MGH_TARGET>/.mgh-sra/business_context.json --answers <answers.json>`
   · 无澄清 → 跳过本步
4. a3 augment(per-capability 扇出):
   for each item in change_context.pending[](逐字透传 draft_path/done_marker):
     spawn sra-augment(隔离上下文;给:该 cap 的 requirements[] + 业务面 + candidate_controls + 增补后 memory
       + 维度目录路径 + draft_path(绝对) + done_marker(绝对) + codegraph 信号(逐字))
     → 恰好写 draft_path + touch done_marker
     · `codegraph=on`(可选 / codegraph-gated / non-fatal / bounded):sra-augment 对**已三信号命中、已推荐控制**的缺口做
       call-path advisory 确认(写 `recommended_control.call_path`;`confirmed` 不伪造、不覆盖代码/用户断言;超预算 → 每缺口
       top-1 + `confirmed:null` + 标「部分未确认」)+ data-flow/liveness/domain-sibling advisory 改善 `risk`/`note`/`reason`;
       `codegraph=off` / 无 `--rules` → 不产 `call_path`、无 advisory,三信号主流程不受影响
5. a4 consistency(除非 --skip-consistency;1 subagent):
     spawn sra-consistency({drafts_dir = <change-root>/.mgh-sra/drafts(绝对)}) → 原地覆写各 draft 定稿
6. a5 merge(Bash,确定性):
     py .opencode/mgh-core/scripts/merge_augment.py --change <change>
   → 受管块幂等追加进 specs/<cap>/spec.md + tasks.md
   · 校验:`py merge_augment.py --check <change>`(仅动受管块;退出码 2 → 回退)
   · 校验:`py merge_memory.py --check <MGH_TARGET>/.mgh-sra/business_context.json`
7. 写 sra_manifest.json(counts 含 `call_path_confirmed`/`call_path_residual` + 五条 boundaries[])+ 打印产物路径 + 边界声明
   · `counts.call_path_confirmed`/`call_path_residual` 取自各 draft `recommended_control.call_path.confirmed` 计数
     (经 `describe_artifact.py` 合法瞄结构出口,**NEVER** `py -c`);`codegraph=off` 时二者均 0
```

### Stage → component map

| Stage | How | Asset |
|---|---|---|
| a1 prepare | **script** | `core/scripts/prepare_augment.py` |
| artifact inspect | **script** | `core/scripts/describe_artifact.py` |
| a2 clarify(单上下文) | subagent `sra-clarify` | `core/prompts/stages/sra-clarify.md` + `fragments/security-dimensions.md` + `fragments/codegraph-hint.md`(`codegraph=on`) |
| 澄清交互 | 宿主(文件回填) | 渲染 `clarifications.md` 待用户填;`--no-interactive` 用默认 |
| 记忆写回 | **script** | `core/scripts/merge_memory.py` |
| a3 augment(per-cap 扇出) | subagent `sra-augment` | `core/prompts/stages/sra-augment.md` + `fragments/security-dimensions.md` + `fragments/codegraph-hint.md`(`codegraph=on`;产 `call_path` advisory) |
| a4 consistency | subagent `sra-consistency`(opt) | `core/prompts/stages/sra-consistency.md` |
| a5 合并(确定性) | **script** | `core/scripts/merge_augment.py` |
| stage boundary check | **script** | `prepare_augment`/`merge_augment`/`merge_memory` `--check` |

### Deterministic invocation (Bash)

```bash
py .opencode/mgh-core/scripts/prepare_augment.py --change <change> --rules .mgh-init
py .opencode/mgh-core/scripts/prepare_augment.py --check .mgh-init
py .opencode/mgh-core/scripts/describe_artifact.py --in <change-root>/.mgh-sra/change_context.json --keys
py .opencode/mgh-core/scripts/merge_memory.py --memory <MGH_TARGET>/.mgh-sra/business_context.json --answers <answers.json>
py .opencode/mgh-core/scripts/merge_memory.py --check <MGH_TARGET>/.mgh-sra/business_context.json
py .opencode/mgh-core/scripts/merge_augment.py --change <change>
py .opencode/mgh-core/scripts/merge_augment.py --check <change>
```

## Output(per `<change-root>/.mgh-sra/` + `<project>/.mgh-sra/`)

- `change_context.json` / `clarifications.json`(结构化)+ `clarifications.md`(人读回填,opencode)
- `drafts/<cap>.md`(a3/a4)、`merge_state.json`(a5 块外快照)、`sra_manifest.json`(counts + boundaries)
- 受管块追加进变更本身:`specs/<cap>/spec.md` + `tasks.md`
- 项目级(跨变更):`<project>/.mgh-sra/business_context.json`

## Always disclose

- 面向人读的非代码内容用**简体中文**;锚点/路径/frontmatter 原样。
- 增补为 **LLM 候选,需人工复核**;覆盖**取决于变更声明 + 已记业务事实**。
- 引用控制**断言存在不断言有效**(承 mgh-init CVE-2025-41248)。
- 业务记忆为**用户断言,非代码真相**(代码声明优先;冲突 manifest 披露)。
- 维度匹配为语义判定,可能误接或漏接;推荐带 `evidence` + 业务域相似理由,供人工复核。
- **codegraph 结构确认是可选 advisory**:`codegraph=on` 时 manifest 记 `counts.call_path_confirmed`/`call_path_residual`
  + `boundaries[]` 披露 codegraph 辅助量与残留(确认 N / 残留 M,**不声称全确认**);codegraph 静态上限(反射/DI/运行时
  分派)缩小但不归零「误接」,`call_path` 为 LLM+codegraph advisory,需人工复核。`--no-codegraph` 一键回退引入前行为。
