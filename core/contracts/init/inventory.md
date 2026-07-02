# Contract: `controls_inventory.json`

Producer: `init-synthesis` (T2). Consumers: `init-rulewriter` (T3), `/mgh-sra`,
`/mgh-blst`, future mgh-sast control intake. **Backward-compatible with vvah
`design_controls`** (`kind`/`protects`/`notes`).

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
| `kind` | enum | vvah 6: `auth`\|`sandbox`\|`input-validation`\|`aslr`\|`cfi`\|`other` |
| `category` | enum | init 8 (table below) |
| `description` | str | what it is, one–two lines |
| `usage` | str | how a dev SHOULD invoke it (the rule payload) |
| `evidence` | [`file:class:method`\|`file:line`] | **≥1** concrete anchor (indexed, no long code) |
| `entry_points` | [file] | flows routed through it (call-graph reverse) |
| `protects` | [fnmatch glob] | vvah-compat; derived from control + callers |
| `notes` | str | vvah-compat free-form |
| `gaps` | [str] | coverage gaps / unresolved / effectiveness caveats |
| `cluster_id` | str | groups competing controls |
| `role` | enum | `canonical`\|`competing`\|`duplicate`\|`possibly-dead` (set in **T2**) |
| `confidence` | float | 0–1; low evidence / verify-disagreement lowers it |

### `category → kind` normalization (deterministic, in discover_controls.py)

| category | kind |
|---|---|
| `input-validation` | `input-validation` |
| `authentication`, `authorization` | `auth` |
| `data-masking`, `crypto`, `csrf`, `rate-limiting`, `audit-logging` | `other` |

### vvah alias reuse (also accepted as `kind` on intake)

`authn`/`authz`/`rbac`/`iam`/`sso`→`auth`; `waf`/`validation`/`sanitization`/`encoding`→`input-validation`;
`seccomp`/`container`/`isolation`→`sandbox`.

> Effectiveness (CVE-2025-41248: `@PreAuthorize` bypass on parameterized types)
> is **out of scope** — inventory asserts existence only (see manifest `boundaries[]`).

> **输出语言**:`description`/`usage`/`gaps`/`notes`/`competing_clusters[].note` 等面向人读
> 字段用**简体中文**;`name`/`kind`/`category`/`role`/`evidence`/`protects`/`cluster_id`/`confidence`
> 等标识与结构字段保持原样(英文/符号)。
