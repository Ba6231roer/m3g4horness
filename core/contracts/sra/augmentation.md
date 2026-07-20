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
 "rules_source":"<path>|none","truncated":false,
 "focus":{...or null...},
 "sensitive_catalog":{...or null...}}
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
| `focus` | `--focus` 解析(`focus_scope` 闭集校验) | `{dimensions[],facets{},directive}` 或 `null`。无 `--focus` = `null` = 全 9 维度(行为不变);`directive`(简体中文句子)由编排器**逐字透传** a2/a3(NEVER 重解析) |
| `sensitive_catalog` | `--sensitive-catalog` 解析(`sensitive_catalog` 闭集校验) | `{version,source,categories[],items[],counts{},directive}` 或 `null`(见 `../sensitive-catalog.md`)。无 `--sensitive-catalog` = `null` = 仅现行 6 facet(行为不变);`directive` 由编排器**逐字透传** a2/a3(NEVER 重算)。与 `--focus` 正交,可同时传 |

**不变式**:所有 `draft_path` MUST 解析后位于 `project_root` 子树内(供 PreToolUse hook 判树)。

## 维度聚焦(`focus` 字段)— 默认不动、可参数化收窄

`--focus <inline-json|path>`(inline JSON 值以 `{` 起首,或 JSON 文件路径,前导 `@` 可选)收窄逐维度扫描范围:

- 解析 + 闭集校验在确定性 a1 阶段完成(任何 LLM subagent 之前);闭集违例(未知维度/facet、facet 维度不匹配、
  空维度集)→ 退出码 2 fail-loud,不产 `change_context.json`,不消耗 token。
- `dimensions` 为 9 维度键子集(或 `"*"`/缺省 = 全 9);`facets` 仅对 `sensitive-data` / `injection` 两维度有效
  (per-dimension facet 白名单,键见 `security-dimensions.md`)。9 维度键 + facet 键的闭集真相源 = `focus_scope.py`。
- 解析后:`focus` 非 null 时含 `directive`(确定性简体中文,按 registry 顺序;同输入字节一致,可复现);
  全 9 维度且无 facet 收窄 → `focus: null`(不渲染 directive,编排器不注入收窄)。
- 收窄语义:编排器把 `focus.directive` 逐字塞进 a2/a3 task 输入;a2/a3 仅对列出维度(及维度内列出 facet)产缺口/
  发澄清,范围外不产;范围内缺口的锚定 / 丢弃 / 三信号 / codegraph 规则**不变**。
- **向后兼容(硬门)**:无 `--focus` → `focus: null` → 下游行为与引入聚焦前逐字一致。

## 敏感数据目录(`sensitive_catalog` 字段)— 默认 6 facet、可声明必屏蔽策略

`--sensitive-catalog <inline-json|@path|->`(inline JSON 值以 `{` 起首,`-` = stdin,或 JSON 文件路径,前导 `@`
可选)声明**本公司强制脱敏清单**(policy 输入,非学到的记忆),扩展 sensitive-data 维度能识别的字段类型 +
每项屏蔽规则。与 `--focus` **正交**(focus = 收窄本次扫描;目录 = 声明必屏蔽策略、扩展识别)。详见
`../sensitive-catalog.md`。

- 解析 + 闭集校验在确定性 a1 阶段完成(任何 LLM subagent 之前);闭集违例(未知 category、非法 mask、
  key/shape 不合法)→ 退出码 2 fail-loud,不产 `change_context.json`,不消耗 token。
- category 闭集 10 类(PIPL/GB-T 35273)+ `mask` 枚举 `{full,partial}` 硬闭集;`field-type` 键与 `rule` 开放。
  闭集真相源 = `sensitive_catalog.py`。
- 解析后:`sensitive_catalog` 非 null 时含 `directive`(确定性简体中文,按 registry 顺序;同输入字节一致)。
- 消费语义:编排器把 `sensitive_catalog`(含 `directive` + `items[]`)**逐字透传** a2/a3;a3 据 `items[]` 逐项查
  脱敏缺口(据 `mask`+`rule` 判 at-rest/in-transit/log/response),缺口标 `catalog_key`,经既有三信号关联
  `data-masking` 控制(advisory;无控制仍产缺口);a2 据目录字段类型发相关澄清。与 `--focus` 叠加:目录仅在
  sensitive-data 在 focus 范围内时生效。
- **向后兼容(硬门)**:无 `--sensitive-catalog` → `sensitive_catalog: null` → 下游行为与引入目录前逐字一致(仅 6 facet)。

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
 "focus":["<维度键>", ...]|null,
 "sensitive_catalog":{"counts":{...},"source":"<path>|inline|stdin"}|null,
 "counts":{"capabilities":N,"gaps":N,"augmented_requirements":N,"augmented_tasks":N,
   "referenced_controls":N,"clarifications_asked":N,"unconfirmed_defaults":N,
   "call_path_confirmed":N,"call_path_residual":N},
 "boundaries":["<五条诚实边界·见下>"]}
```

| field | note |
|---|---|
| `focus` | 本次聚焦的维度列表(= `change_context.focus.dimensions`);`null` = 全 9 维度(未收窄)。`focus` 非 null 时 `boundaries[]` SHALL 增一条「本次仅扫描聚焦维度,范围外维度未覆盖」 |
| `sensitive_catalog` | 本次生效目录的 `counts{items,full,partial,categories}` + `source`;`null` = 未用目录(仅 6 facet)。非 null 时 `boundaries[]` SHALL 增一条「据公司敏感数据目录逐项查脱敏,目录外字段类型仅按现行 6 facet 识别」(防误以为目录穷尽所有敏感字段) |

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
  + `change_context` 结构完整(顶层字段 + `pending[]` 路径绝对且在子树内)+ `focus` 字段 shape(若存在:dimensions
  闭集、facets 维度匹配且闭集、`null` 合法)+ `sensitive_catalog` 字段 shape(若存在:items[] 各项 category 闭集、
  mask 枚举、key `<category>/<field-type>` 合法、label 非空、counts 自洽、`null` 合法)。`--check` 多态:路径为
  inventory 文件/目录 → 校 inventory;为 `change_context.json` → 校结构 + focus + sensitive_catalog。
- `merge_augment --check`:合并仅动受管块、块外字节不变。
- `merge_memory --check`:记忆 shape + `fact_key` 无冲突。

失败退出码 2 fail-loud,编排器回退重跑,**不带着破损产物继续**。
