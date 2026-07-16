# Contract: sra augmentation I/O(`change_context.json` / draft / `sra_manifest.json`)

Producer / Consumer: `/mgh-sra` 编排器与 sra-clarify / sra-augment / sra-consistency subagent。
定义「解析变更 → 维度查缺口 → 三信号匹配 → 幂等合并」各阶段产物 shape。所有落位:
变更产物在 `<change-root>/.mgh-sra/`;业务记忆在 `<project>/.mgh-sra/`(见
`business-context.md`)。退出码 `0/1/2`(0 成功 · 1 文件缺失/JSON 畸形 · 2 shape/intake 违例)。

## `change_context.json`(a1 `prepare_augment.py` 产出)

```json
{"change":"<name>","change_root":"<abs>","project_root":"<abs>",
 "capabilities":[{"name":"<cap>","requirements":["<req heading>", ...]}],
 "requirements":[{"capability":"<cap>","heading":"<req>","body":"<text>"}],
 "tasks":["<task line>", ...],
 "mentioned_files":["<file>", ...],
 "endpoints":["POST /api/transfer", ...],
 "data_fields":["bankCardNo", ...],
 "role_hints":["customer","admin", ...],
 "candidate_controls":[{"name":"...","category":"...","dimensions":["..."],
   "entry_points":[...],"evidence":[...],"file_overlap":false}],
 "pending":[{"capability":"<cap>","draft_path":"<abs>","done_marker":"<abs>"}],
 "memory":{...or null...},
 "rules_source":"<path>|none","truncated":false}
```

| field | source | note |
|---|---|---|
| `change` / `change_root` | `--change` 解析 | 变更名 + 变更根(含 proposal/design/specs/tasks) |
| `project_root` | 解析(`openspec/` 所在目录) | `= MGH_TARGET`;覆盖变更子树 + 项目记忆两类写入 |
| `capabilities[]` | `specs/<cap>/spec.md` 的 `## ADDED\|MODIFIED Requirements` 下 `### Requirement:` | 每 capability 一项,带其 `requirements[]` 标题 |
| `requirements[]` | 同上 | 扁平化 `{capability, heading, body}`,供 subagent 锚定 |
| `tasks[]` | `tasks.md` 的 `- [ ]` / `- [x]` 条目 | 现有任务(机械抽取业务面信号) |
| `mentioned_files[]` / `endpoints[]` / `data_fields[]` / `role_hints[]` | 正则机械抽取自全变更文本 | 业务面信号(供维度分析);无则空 |
| `candidate_controls[]` | 读 `--rules` inventory(信号-1) | 每控制 `dimensions` 由 `category` 派生;`file_overlap` = 其 `entry_points`/`protects` 与 `mentioned_files` 相交;无 `--rules` 时空 |
| `clarify_path` | `prepare_augment` 派生 | `clarifications.json` 的**绝对**路径;a2 sra-clarify 逐字写它(编排器读它批量发问) |
| `pending[]` | 按 capability 枚举 | 每项 `draft_path`/`done_marker` 均 `Path.resolve()` **绝对**;无 capability specs 时单项 `capability:"security-augmentation"` |
| `memory` | 读 `<project>/.mgh-sra/business_context.json` | 缺失为 `null`(空记忆起步) |

**不变式**:所有 `draft_path` MUST 解析后位于 `project_root` 子树内(供 PreToolUse hook 判树)。

> **codegraph 富化不触本契约**:`change_context.json` schema **不变**——`candidate_controls` 仍是 `prepare_augment.py`
> 的文本抽取(信号-1,`_ENDPOINT_RX`/`_ROLE_HAS_RX`/`_SENS_SUBSTR` 文本正则)。codegraph 是宿主能力(MCP / CLI),
> 仅在 a2/a3 **LLM 层**消费(外科式上下文 + call_path advisory),**从不**被任何 `.py` import / subprocess,不进
> `change_context.json`。codegraph 的唯一结构产物是 draft 的**可选** `recommended_control.call_path`(见下)。

## draft(`drafts/<cap>.md`,a3 sra-augment 产出;a4 consistency 定稿)

draft 是**结构化 JSON**(写在绝对 `draft_path`),含可渲染的 spec / task 内容:

```json
{"capability":"<cap>",
 "gaps":[{"dimension":"horizontal-authz",
   "anchor":{"requirement":"发起转账","endpoint":"POST /api/transfer","field":"bankCardNo"},
   "risk":"<为何是缺口>",
   "recommended_control":{"name":"..","evidence":"file:c:m","rule_path":"..","reason":"<业务域相似理由>",
     "call_path":{"confirmed":true,"path":[{"file":"..","line":N,"edge":".."}],"source":"codegraph","note":"<简体中文>"}}|null,
   "matched_signals":{...}|null}],
 "security_requirements":[{"heading":"<Requirement: ...>","body":"<简体中文·锚定+控制>"}],
 "security_tasks":["- [ ] <安全任务·锚定+控制>"]}
```

| field | note |
|---|---|
| `gaps[].dimension` | 安全维度键(见 `core/prompts/fragments/security-dimensions.md`);维度外 `other` |
| `gaps[].anchor` | MUST 命中 ≥1 具体 requirement / endpoint / field;无锚定缺口丢弃 |
| `gaps[].recommended_control` | 仅三信号同时命中时给(`{name,evidence,rule_path,reason}` + 可选 `call_path`);无 `--rules` 时 `null` |
| `gaps[].recommended_control.call_path` | **可选,仅 `codegraph=on` 时出现**(advisory)。`{confirmed:bool\|null, path:[{file,line,edge}], source:"codegraph", note}`;`confirmed:true`=控制接在请求路径上(强化复用措辞)、`false`=存在但未确认接入(降级置信 + caveat)、`null`=未判定 / 裁剪。render-time only:a5 渲染时仅影响推荐措辞 / 置信标注,**不增删受管块结构**;`codegraph=off` 时该字段缺省(valid)。`confirmed` 不伪造、不覆盖代码 evidence / 用户 `business_context.json` 断言 |
| `gaps[].matched_signals` | `{dimension_fit:bool, business_domain:bool, business_fact:bool}`;仅文件重叠不算业务域命中 |
| `security_requirements[]` / `security_tasks[]` | 渲染进 specs / tasks 的受管块;每条锚定 + 「复用勿重造」措辞(`call_path.confirmed:true` 强化、`false` 降级) |

## `sra_manifest.json`(编排器最终产出)

```json
{"change":"<name>","rules_source":"<path>|none","memory_source":"<path>|none",
 "counts":{"capabilities":N,"gaps":N,"augmented_requirements":N,"augmented_tasks":N,
   "referenced_controls":N,"clarifications_asked":N,"unconfirmed_defaults":N,
   "call_path_confirmed":N,"call_path_residual":N},
 "boundaries":["<五条诚实边界·见下>"]}
```

| counts field | note |
|---|---|
| `call_path_confirmed` | `recommended_control.call_path.confirmed=true` 的条数(仅 `codegraph=on` 时 > 0) |
| `call_path_residual` | `confirmed=false` 或 `null` 的条数(未确认 / 未判定 / 裁剪);`codegraph=off` 时 `call_path_confirmed`/`call_path_residual` **均为 0**(或字段缺省) |

`boundaries[]`(可识别字段、MUST 全含):
1. 增补为 **LLM 候选,需人工复核**;
2. 覆盖**取决于变更声明 + 已记业务事实**(未声明 / 未记的看不到);
3. 引用控制**断言存在不断言有效**(承 mgh-init CVE-2025-41248);
4. 业务记忆为**用户断言非代码真相**(显式代码/proposal 声明 > 用户记忆 > 默认猜测);
5. **codegraph 结构确认是可选 advisory**:`boundaries[]` SHALL 披露 codegraph 是否辅助、`call_path` 确认了多少
   (`call_path_confirmed`)、残留多少未确认(`call_path_residual`)——**不声称全确认**;codegraph 自身静态分析上限
   (反射 / DI 容器 / 运行时分派)缩小但**不归零**「误接」,`call_path` 为 LLM+codegraph advisory,需人工复核。
   `codegraph=off` 时披露「codegraph 未辅助」。

## `--check` 边界校验(各 producer 暴露)

- `prepare_augment --check`:inventory(若给)well-formed(`controls[]` + 每条 `name`/`evidence`)
  + `change_context` 结构完整(顶层字段 + `pending[]` 路径绝对且在子树内)。
- `merge_augment --check`:合并仅动受管块、块外字节不变。
- `merge_memory --check`:记忆 shape + `fact_key` 无冲突。

失败退出码 2 fail-loud,编排器回退重跑,**不带着破损产物继续**。
