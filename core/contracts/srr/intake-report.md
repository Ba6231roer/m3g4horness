# Contract: srr intake / report I/O(`change_context.json` / `security_review_report.md` / `srr_manifest.json`)

Producer / Consumer: `/mgh-srr` 编排器、`ingest_requirements.py`(输入适配器)、
`render_report.py`(输出适配器)、复用的 sra-clarify / sra-augment / sra-consistency subagent。

`/mgh-srr` = 端口-适配器:换上「自由文本输入适配器」+「普通报告输出适配器」,**中间引擎逐字
复用 `/mgh-sra`**(sra-clarify / sra-augment / sra-consistency + security-dimensions +
codegraph-hint + `merge_memory.py` + `business_context.json` 契约,零复制零新增)。因此
**输入适配器产出的 `change_context.json` 与 `/mgh-sra` 的 `prepare_augment.py` 同 shape**(见
`../sra/augmentation.md`),subagent 零改动消费。本文件只记**相对 sra 的 delta** + 报告侧 shape。

落位:每次 intake 工作目录 = `<out-dir>`(默认 `<project>/.mgh-srr/`);业务记忆在
`<project>/.mgh-sra/business_context.json`(**与 sra 同文件同 shape**,跨 sra/srr 累积一份)。
退出码 `0/1/2`(0 成功 · 1 文件缺失/JSON 畸形 · 2 shape/intake 违例)。

## `change_context.json`(ingest `ingest_requirements.py` 产出)— 与 sra 同 shape + delta

与 sra `prepare_augment.py` 产出的**顶层字段一一对应**(`change`/`change_root`/`project_root`/
`capabilities`/`requirements`/`tasks`/`mentioned_files`/`endpoints`/`data_fields`/`role_hints`/
`candidate_controls`/`clarify_path`/`pending`/`memory`/`rules_source`/`memory_source`/`dry_run`/
`truncated`)。delta 仅在**取值语义**与**一个新字段**上:

```json
{"change":"<文档名|stdin|freeform-text>","change_root":"<abs out-dir>","project_root":"<abs>",
 "capabilities":[{"name":"freeform-review","requirements":["<section heading>", ...]}],
 "requirements":[{"capability":"freeform-review","heading":"<section>","body":"<text>"}],
 "tasks":[],
 "mentioned_files":["<file>", ...],"endpoints":["POST /api/x", ...],
 "data_fields":["bankCardNo", ...],"role_hints":["customer", ...],
 "candidate_controls":[{...}],
 "clarify_path":"<abs out-dir>/clarifications.json",
 "pending":[{"capability":"freeform-review","draft_path":"<abs>","done_marker":"<abs>"}],
 "memory":{...or null...},
 "rules_source":"<path>|none","memory_source":"<path>|none",
 "dry_run":false,"truncated":false,
 "degraded":[],
 "focus":{...or null...},
 "sensitive_catalog":{...or null...}}
```

| field | srr delta vs sra |
|---|---|
| `change` | = 输入文档名(文件 basename / 目录名 / `stdin` / `freeform-text`),非 openspec 变更名 |
| `change_root` | = `<out-dir>`(每次 intake 工作目录;drafts/clarify/state 落此),非 openspec 变更根 |
| `project_root` | = `MGH_TARGET`(向上找 `openspec/`;无则 cwd);覆盖 `<out-dir>` + `<project>/.mgh-sra/` 记忆两类写入 |
| `capabilities[]` | 默认单项 `{"name":"freeform-review",...}`(整篇 = 1 review scope);`--split` 时按 markdown `#`/`##` 标题切分为多项 |
| `requirements[]` | = 文档**段落/section 标题**作锚点(非 openspec `### Requirement:`);无标题文档→单项 `{heading:<docname>, body:<全文>}` 兜底,**全文进 body 供 subagent 语义读** |
| `tasks[]` | 恒为 `[]`(自由文本无 tasks.md) |
| `endpoints`/`data_fields`/`role_hints`/`mentioned_files` | **可选 hint**(可全空);正则机械抽取,非承重——LLM 直接读全文 |
| `candidate_controls[]` | 有 `--rules` 时复用 sra 的 `category`→`dimensions` 派生 + `file_overlap` 逻辑(与 `prepare_augment` 同);无则 `[]` |
| `pending[]` | 默认 1 项(整篇);`--split` 多项;每项 `draft_path`/`done_marker` 均 `Path.resolve()` **绝对**且在 `project_root` 子树内 |
| `memory` | 读 `<project>/.mgh-sra/business_context.json`(**与 sra 同文件**,缺失为 `null`) |
| `degraded` | **srr 新增字段**;`string[]`,标注 `.docx`/`.xlsx` 尽力抽取丢失的保真度(如 `docx-best-effort`/`list-markers-lost`/`dates-as-serial`/`cell-formats-lost`);text-native 与 `--text`/stdin 透传恒为 `[]` |
| `focus` | `--focus` 解析(`focus_scope` 闭集);**与 sra 同 shape/语义**(`{dimensions[],facets{},directive}` 或 `null`)。无 `--focus` = `null` = 全 9 维度(行为不变);`directive` 逐字透传复用的 a2/a3(零新增提示词) |
| `sensitive_catalog` | `--sensitive-catalog` 解析(`sensitive_catalog` 闭集);**与 sra 同 shape/语义**(`{version,source,categories[],items[],counts{},directive}` 或 `null`,见 `../sensitive-catalog.md`)。无 `--sensitive-catalog` = `null` = 仅现行 6 facet(行为不变);`directive` + `items[]` 逐字透传复用的 a2/a3(零新增提示词)。与 `--focus` 正交 |

**不变式**(承 sra):所有 `draft_path` MUST 解析后位于 `project_root` 子树内(供 hook 判树);
`change`/`change` 文本**逐字**进 `requirements[].body`(子助手语义读全文,缺口锚到 section 标题)。

> codegraph 富化不触本契约:与 sra 同,`change_context.json` schema 不因 codegraph 改变;
> codegraph 仅在 a2/a3 LLM 层消费(宿主 MCP/CLI,不被任何 `.py` import)。codegraph=off 时
> draft 不产 `recommended_control.call_path`,行为等价引入前。

## draft(`drafts/<cap>.md`,复用 sra-augment 产出;sra-consistency 定稿)

draft shape **逐字复用 sra**(见 `../sra/augmentation.md` 的 draft 段):`{capability, gaps[],
security_requirements[], security_tasks[]}`。`gaps[].anchor` 锚到 section 标题 / 偶尔 endpoint
/ field;锚点稀疏时产「应满足的安全属性」类缺口(无控制锚点),仍按 sra 规则处理。
`recommended_control.call_path` 为可选 advisory(仅 codegraph=on)。

## `security_review_report.md`(render `render_report.py` 产出)— 普通·简体中文·简要·面向人读

非 openspec 受管块,纯人读报告。结构(渲染时按维度/锚点组织):

```markdown
# 安全需求评审报告:<doc 名>

> 输入:<doc 名与抽取方式(text-native|docx-best-effort|xlsx-best-effort|透传)>;
> 控制来源:<rules_source|none>;项目记忆:<memory_source|none>。
> 聚焦维度:<dims>(本次仅扫描聚焦维度,范围外未覆盖)   ← 仅 `focus` 非 null 时出现
> 敏感数据目录:<字段数> 项 / <类别数> 类(据公司目录逐项查脱敏,目录外仅 6 facet)   ← 仅 `sensitive_catalog` 非 null 时出现

## 缺口(按维度)
### <dimension>
- **锚点**:<requirement/section 或 endpoint/field>
- **风险**:<为何是缺口·简体中文>
- **建议复用**:<control 名 + reason>(有 --rules 且三信号命中时;否则「无存量控制可复用」)

## 澄清过的问题
- <question> → <answer|默认·未确认>

## 诚实边界
<六条·见 srr_manifest.json boundaries[]>
```

面向人读的非代码内容用**简体中文**;锚点/路径/frontmatter 原样。

## `srr_manifest.json`(render 产出)

```json
{"doc":"<name>","rules_source":"<path>|none","memory_source":"<path>|none",
 "focus":["<维度键>", ...]|null,
 "sensitive_catalog":{"counts":{...},"source":"<path>|inline|stdin"}|null,
 "counts":{"gaps":N,"augmented_requirements":N,"referenced_controls":N,
   "clarifications_asked":N,"unconfirmed_defaults":N,
   "call_path_confirmed":N,"call_path_residual":N},
 "boundaries":["<六或七或八条·见下>"]}
```

| field | note |
|---|---|
| `focus` | 本次聚焦的维度列表(= `change_context.focus.dimensions`);`null` = 全 9 维度(未收窄)。`focus` 非 null 时 `boundaries[]` 增一条「本次仅扫描聚焦维度,范围外维度未覆盖」,报告头注聚焦维度 |
| `sensitive_catalog` | 本次生效目录的 `counts{items,full,partial,categories}` + `source`;`null` = 未用目录(仅 6 facet)。非 null 时 `boundaries[]` 增一条「据公司敏感数据目录逐项查脱敏,目录外字段类型仅按现行 6 facet 识别」,报告头注目录覆盖范围(字段数 + 类别) |

| counts field | note |
|---|---|
| `gaps` | 各 draft `gaps[]` 总数 |
| `augmented_requirements` | 各 draft `security_requirements[]` 总数 |
| `referenced_controls` | `recommended_control.name` 去重计数(有 --rules 时) |
| `clarifications_asked` | 本次 a2 发的澄清问数(取自 clarifications.json) |
| `unconfirmed_defaults` | 走 `--no-interactive` 或未回填的默认数 |
| `call_path_confirmed` | `recommended_control.call_path.confirmed=true` 条数(仅 codegraph=on 时 > 0) |
| `call_path_residual` | `confirmed=false|null` 条数;codegraph=off 时二者均 0 |

`boundaries[]`(可识别字段、MUST 全含 6 条;`focus` 非 null 时增第 7 条;`sensitive_catalog` 非 null 时增第 8 条):
1. **SRR 专属**:输入抽取对 `.docx`/`.xlsx` 是尽力而为(日期/格式/列表降级);评审覆盖受**输入完整度**上界约束——含糊的需求文档只能产锚点稀疏的泛化缺口;
2. 增补/缺口为 **LLM 候选,需人工复核**;
3. 覆盖**取决于需求文档声明 + 已记业务事实**(未声明/未记的看不到);
4. 引用控制**断言存在不断言有效**(承 mgh-init CVE-2025-41248);
5. 业务记忆为**用户断言,非代码真相**(显式代码/proposal 声明 > 用户记忆 > 默认猜测);
6. **codegraph 结构确认是可选 advisory**(承 sra 第 5 条):`call_path` 确认 N / 残留 M,**不声称全确认**;codegraph=off 时 `call_path_confirmed`/`call_path_residual` 均 0;
7. **(仅 `focus` 非 null 时)维度聚焦收窄了范围**:本次仅扫描聚焦维度(及维度内聚焦 facet),范围外维度**未覆盖**;
8. **(仅 `sensitive_catalog` 非 null 时)据公司敏感数据目录逐项查脱敏**:目录内字段类型据 mask 规则逐项查脱敏缺口,目录**外**字段类型仅按现行 6 facet 识别(目录非穷尽所有敏感字段)。

## `--check` 边界校验(各 producer 暴露)

- `ingest_requirements --check <change_context.json>`:`change_context` 结构完整(顶层字段 +
  `capabilities[]`/`requirements[]`/`pending[]`) + `pending[]` 路径绝对且在 `project_root` 子树内
  + `degraded` 为合法 `string[]` + `focus` 字段 shape(若存在:dimensions 闭集、facets 维度匹配且闭集、`null` 合法)
  + `sensitive_catalog` 字段 shape(若存在:items[] 各项 category 闭集、mask 枚举、key `<category>/<field-type>` 合法、
  label 非空、counts 自洽、`null` 合法)。退出码 2 fail-loud。
- `render_report --check <out-dir>`:`security_review_report.md` + `srr_manifest.json` shape 完整
  + counts 字段齐 + boundaries 含 ≥6 条 + `focus` 非 null 时含第 7 条聚焦披露 + `sensitive_catalog` 非 null 时含
  第 8 条目录披露 + **无 `openspec/` 路径被触及**(out-dir 不与 openspec 重叠)。

失败退出码 2 fail-loud,编排器回退重跑,**不带着破损产物继续**。
