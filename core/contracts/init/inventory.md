# Contract: `controls_inventory.json`

Producer: `init-synthesis` (T2). Consumers: `init-rulewriter` (T3), `/mgh-sra`,
`/mgh-blst`, future mgh-sast control intake. **Backward-compatible with
`design_controls`** (`kind`/`protects`/`notes`).

> **per-category 物化(闭合编排器整份读)**:`init-rulewriter` 需的「该 category 的全部 controls」由
> `list_rule_jobs.py --materialize <inputs/t3>` 下沉到 `<target>/.mgh-init/inputs/t3/<category>.input.json`
> (见 [`unit-inputs.md`](unit-inputs.md));subagent **读自己的 `input_path`**。slim 待办壳携
> `input_path`/`bytes`/`oversize`;超 `--max-unit-bytes` 的 category 标 `oversize:true` + recipe(建议
> `--scope`+`--merge`,**不**切分)。编排器 NEVER 整份读 `controls_inventory.json`(见 `request-context-budget`)。

Top-level:

```json
{
  "repo": "<abs repo root>",
  "format": "opencode|claude",
  "generated_at": "<iso from caller; script never sets time>",
  "controls": [<Control>, ...],
  "competing_clusters": [{"cluster_id":"...", "canonical":"<name>", "members":["<name>",...]}]
}
```

A `Control`:

| field | type | note |
|---|---|---|
| `name` | str (slug) | stable id, e.g. `spring-method-security` |
| `kind` | enum | 6: `auth`\|`sandbox`\|`input-validation`\|`aslr`\|`cfi`\|`other` |
| `category` | enum | init 8 (table below) |
| `description` | str | what it is, one–two lines |
| `usage` | str | how a dev SHOULD invoke it (the rule payload) |
| `evidence` | [`file:class:method`\|`file:line`] | **≥1** concrete anchor (indexed, no long code) |
| `entry_points` | [file] | flows routed through it (call-graph reverse) |
| `protects` | [fnmatch glob] | `design_controls`-compat; derived from control + callers |
| `notes` | str | `design_controls`-compat free-form |
| `gaps` | [str] | coverage gaps / unresolved / effectiveness caveats |
| `cluster_id` | str | groups competing controls |
| `role` | enum | `canonical`\|`competing`\|`duplicate`\|`possibly-dead` (set in **T2**) |
| `confidence` | float | 0–1; low evidence / verify-disagreement lowers it |

### evidence anchor existence(T2 边界闸门)

`validate_inventory.py` 在形状校验之外对**每条控制的每个 evidence token** 做存在性校验
(零 LLM 确定性检查;解析/解析阶梯实现是共享单一真源 `anchor_resolve.py`,装配边界
覆盖对账复用同一实现):文件按确定性阶梯解析(仓库根相对精确 → 同目录大小写不敏感 →
**全仓唯一文件名**;唯一文件名命中**算过**,计入 `by_basename` 计数——路径形态差异
不算违规);`path:line` 行号 MUST 落在 `1..len(lines)`;`path::类.方法`/`path:类.方法`
符号段逐段 MUST 在文件文本中在场。任一 `file_missing` / `line_out_of_range` /
`symbol_absent` → 退出码 2,stderr 按类列首 N 个违规 token 与所属控制名——回 T2
修正 token 本身,NEVER 宽松放行、NEVER 自动改写。仓库根 = `--repo` flag > 顶层
`repo` 字段,两者皆缺 → 退出码 2(存在性闸门 NEVER 半途跳过)。

### `category → kind` normalization (deterministic, in discover_controls.py)

| category | kind |
|---|---|
| `input-validation` | `input-validation` |
| `authentication`, `authorization` | `auth` |
| `data-masking`, `crypto`, `csrf`, `rate-limiting`, `audit-logging` | `other` |

### alias reuse (also accepted as `kind` on intake)

`authn`/`authz`/`rbac`/`iam`/`sso`→`auth`; `waf`/`validation`/`sanitization`/`encoding`→`input-validation`;
`seccomp`/`container`/`isolation`→`sandbox`.

> Effectiveness (CVE-2025-41248: `@PreAuthorize` bypass on parameterized types)
> is **out of scope** — inventory asserts existence only (see manifest `boundaries[]`).

> **输出语言**:`description`/`usage`/`gaps`/`notes`/`competing_clusters[].note` 等面向人读
> 字段用**简体中文**;`name`/`kind`/`category`/`role`/`evidence`/`protects`/`cluster_id`/`confidence`
> 等标识与结构字段保持原样(英文/符号)。
