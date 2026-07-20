# Contract: sensitive-data catalog(`sensitive_catalog.json` / `change_context.sensitive_catalog`)

Producer / Consumer:`sensitive_catalog.py`(loader/validator,单一真相源)、
`prepare_augment.py`(sra a1)/ `ingest_requirements.py`(srr r1)(解析 + 嵌字段)、
sra-clarify / sra-augment subagent(据 `directive` + `items[]` 逐项查脱敏缺口)。

项目级**公司强制脱敏清单**(policy 输入,**非**学到的记忆):声明本公司必屏蔽的字段类型 +
屏蔽级别 + 规则,被 sra/srr 共享消费。**与 `--focus` 正交**:focus 收窄「本次扫哪些维度」;
目录声明「哪些字段类型 MUST 屏蔽」并扩展 sensitive-data 识别(超出 6 facet)。默认位置
`<project>/.mgh-sra/sensitive_catalog.json`(项目根 = 含 `openspec/` 的目录)。退出码 `0/1/2`
(0 成功 · 1 文件缺失/stdin 错/JSON 畸形 · 2 闭集/shape 违例)。

## `sensitive_catalog.json`(用户手写 / `.example` 模板裁剪)

```json
{"version": 1,
 "items": {
   "<category>/<field-type>": {"label": "<简体中文>", "mask": "full|partial", "rule": "<提示串>|null"}
 }}
```

| field | rule |
|---|---|
| `version` | 顶层 int 必填(模板 = `1`);法规更新时 bump |
| `items` | 非空对象;键 = `<category>/<field-type>`(均 `[a-z0-9-]+` 小写 kebab) |
| `category` | **闭集 10 类**(PIPL / GB-T 35273):`identity-doc`/`biometric`/`health`/`financial`/`location`/`communication`/`device`/`vehicle`/`general-pii`/`legal`。闭集真相源 = `sensitive_catalog.py::CATEGORIES`。未知 → exit 2 |
| `field-type` | 公司自有**开放**词汇(`[a-z0-9-]+`),不与 `--focus` 6 facet 共享闭集 |
| `label` | 非空简体中文(面向人读) |
| `mask` | **闭集枚举** `{full, partial}`:`full` = 不可展示原始值(`rule` 可 null);`partial` = 保留 `rule` 描述的部分。非闭集值 → exit 2 |
| `rule` | 自由提示串(法务自然语言,如「保留后 4 位」「保留姓」)或 null。后续可演进为结构化 schema(届时 bump version) |

## `change_context.sensitive_catalog`(a1/r1 解析后嵌入)

`prepare_augment` / `ingest_requirements` 在任何 LLM 之前经 sibling import 解析 + 闭集校验,嵌入:

```json
{"version": 1, "source": "<inline|stdin|<path>>",
 "categories": ["<闭集 category>", ...],
 "items": [{"key":"<category>/<field-type>","category":"<cat>","label":"..","mask":"..","rule":"..|null"}],
 "counts": {"items": N, "full": N, "partial": N, "categories": N},
 "directive": "<确定性简体中文策略摘要>"}
```

| field | note |
|---|---|
| `source` | `"inline"` / `"stdin"` / 文件绝对路径(解析来源) |
| `categories[]` | 去重 + 按 registry 闭集序排序 |
| `items[]` | 扁平、去重 + 按 `category` 闭集序排序(同 category 内按 `field-type` 字典序);每项含 `key`/`category`/`label`/`mask`/`rule` |
| `counts` | `items`(总项数)、`full`/`partial`(mask 计数)、`categories`(覆盖类别数) |
| `directive` | 确定性简体中文策略摘要(类别数 + 字段数 + 全/部分屏蔽计数 + 「须按 mask 规则在 at-rest/in-transit/log/response 脱敏,未脱敏记缺口」+ 「无目录时按现行 6 facet」)。编排器**逐字透传** a2/a3(NEVER 重算/重拼) |

`directive` 确定性:同输入字节 → 同输出 directive(可复现,无随机)。`null`(无 `--sensitive-catalog` 且无
默认目录文件)→ 无 directive 注入 → sensitive-data 维度行为逐字等价引入目录前(仅 6 facet)。

## 目录如何驱动 sensitive-data 维度

`sra-augment`(a3)/ `sra-clarify`(a2)收到非空 `sensitive_catalog` 时,把 sensitive-data 维度的逐项检查
**扩展**为对 `items[]` 每个字段类型的脱敏缺口检测:据 `mask`+`rule` 判该字段 at-rest / in-transit / log /
response 是否按规则脱敏;未脱敏即产 sensitive-data 缺口,锚定具体 requirement/接口/字段并标
`catalog_key`(= 该项 `key`)。`--focus` 覆盖层叠加:目录仅在 sensitive-data 在 focus 范围内时生效。
`sensitive_catalog: null` → 仅按现行 6 facet。srr 逐字复用这两份提示词,零新增提示词获得该行为。

## mgh-init 脱敏控制关联(advisory,sra 仅消费)

目录驱动的脱敏缺口经**既有三信号匹配**(维度契合 / 业务域相似 / 业务事实)命中
`candidate_controls[]` 中 `category: data-masking` 控制时(`dimensions` 含 `sensitive-data`,映射已存在于
`prepare_augment.py::DIMENSIONS_BY_CATEGORY`),a3 为该缺口附 `recommended_control` + `evidence` +
「复用勿另起脱敏封装」。关联 **advisory**:无匹配控制(或无 `--rules`)缺口仍产出(无控制锚点),**MUST NOT**
硬丢。**不改 mgh-init 发现 / inventory schema / rules**(sra 仅读 `controls_inventory.json`)。

## `.example` 模板(随分发,不自动应用)

`install.sh` 在目标项目落地 `.mgh-sra/sensitive_catalog.json.example`(37 项 PIPL/GB-T 35273 默认模板)。
模板的提交态真相源 = `core/scripts/sensitive_catalog.json.example`(= `sensitive_catalog.py::DEFAULT_TEMPLATE`
= `--list` 的 `default_template`;由 `tests/test_sensitive_catalog.py` anti-drift 断言三者同步)。模板 **MUST NOT**
自动应用为生效目录(自动应用改默认行为、违向后兼容硬门);公司显式 `cp` 为 `sensitive_catalog.json` 或经
`--sensitive-catalog @<path>` 指定才生效。

## `--check` 边界校验

`sensitive_catalog.py --check <json|@path|->`:仅校验(无渲染无副作用),stdout =
`{"check":"sensitive-catalog","ok":bool,"violations":[...]}`,退出码 `0/1/2`。`prepare_augment --check` /
`ingest_requirements --check` 对 `change_context.sensitive_catalog`(若非 null)做 shape 校验(items[] 各项
category 闭集、mask 枚举、key `<category>/<field-type>` 合法、label 非空、counts 自洽);违例 exit 2。
