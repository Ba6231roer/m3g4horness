# Contract: `load_controls.py` stdout — sast controls intake + scope projection

Producer: `core/scripts/load_controls.py`(确定性、stdlib)。Consumer: `/mgh-sast`
编排器——把投影后的 `controls_bundle` 注入 s2/s3/s4/s6/s8 subagent 的**任务消息**。
填补 vvah 注入缺口(`injectors/design_controls.py::load_controls`,s2/s8 消费)。

> **注入语义(本契约锁)**:控制走**任务消息**注入,**NEVER** 编辑移植的 SYSTEM
> 提示词正文(`core/prompts/stages/*.md` 一字不改);注入范围 **s2/s3/s4/s6/s8**
> (对标 vvah 消费点 + 现有提示词预留位),**不**注入 s1/s5/s7/s9;`controls_bundle`
> 经确定性脚本 `load_controls.py` 产出,scope 投影仅标 `in_scope` flag、**作 relevance
> hint**(保留 `out_of_scope_count` 与 `out_of_scope_summary`,防 under-filter 漏报)。
> 编排器取 `controls_bundle` **MUST** 走 `load_controls.py`,NEVER 手挖 inventory / `py -c`
> 内省。

## CLI(`--help` 即契约)

```
py load_controls.py --inventory <controls_inventory.json> --repo <root> [--in-scope <file>]
py load_controls.py --check    <controls_inventory.json>
```

`--inventory`/`--repo` 必填(主路径 = intake 校验 + scope 投影 + emit);`--check`
独立路径 = 仅 intake 校验(失败退出码 2,编排器回退「无控制」advisory)。
`--check` **MUST NOT** `import validate_inventory`(sast 消费侧独立实现 intake,避免
反向依赖 init 内部,见 `validate_inventory.py` 是 init 产出侧 T2 校验)。

`--in-scope <file>`:扫描的 `in_scope[]`(全仓扫描时缺省 = 全仓,所有控制 `in_scope:true`)。
接受 JSON `{"in_scope":[...]}` / 裸 `[...]`;`--diff`/`--path`/`--package` 的 scope 由编排器
经 `diff_seed.py`/`expand_scope.py` 派生后写入此文件再传入。

## stdout(结构化 JSON;stderr 仅诊断/进度)

主路径 emit `controls_bundle`:

```json
{
  "source": "mgh-init",
  "inventory_path": "<所给路径>",
  "repo": "<--repo 所给根>",
  "total": N,
  "in_scope_count": M,
  "out_of_scope_count": K,
  "in_scope": [<ControlSummary>, ...],
  "out_of_scope_summary": [{"name": "<slug>", "kind": "<canonical>"}, ...]
}
```

不变式:`total == in_scope_count + out_of_scope_count`。`source` 恒为 `"mgh-init"`
(bundle 由读 mgh-init inventory 产出;无 `--controls` 时编排器不产 bundle、manifest 标
`controls.source="none"`)。`out_of_scope_summary` 仅 name/kind(降级 hint,省 token);
in-scope 控制给完整摘要。退出码 `0/1/2`(0 成功 · 1 文件缺失/JSON 畸形 · 2 intake 违例)。

### `<ControlSummary>`(in_scope[] 每项;`kind` 归一到 canonical)

```json
{"name": "spring-method-security", "kind": "auth",
 "description": "方法级 @PreAuthorize 鉴权", "usage": "...",
 "evidence": ["src/api/Ctrl.java:42"], "entry_points": ["src/api/Ctrl.java"],
 "protects": ["src/api/**"], "gaps": ["参数化类型上可绕过"]}
```

| field | source | note |
|---|---|---|
| `name` | `Control.name` | stable slug id |
| `kind` | `Control.kind` 经别名归一 | vvah canonical 6-enum |
| `description` | `Control.description` | 控制是什么(≤2 行) |
| `usage` | `Control.usage` | dev 如何调用(rule payload) |
| `evidence` | `Control.evidence` | ≥1 `file:class:method`\|`file:line` 锚点 |
| `entry_points` | `Control.entry_points` | 经该控制路由的文件(s4 上游排除用) |
| `protects` | `Control.prots` | fnmatch globs(scope 投影求交用) |
| `gaps` | `Control.gaps` | 覆盖缺口 / 有效性警示(供 evidence-grounded 判定) |

字段对齐 `core/contracts/init/inventory.md` 的 `Control` 元素 schema(`kind`/`protects`/
`notes` 与 vvah `design_controls` 后向兼容)。摘要**不含** `role`/`confidence`/`cluster_id`
(那是 init 归并态,sast 消费无关,省 token)。

### scope 投影规则(确定性 fnmatch)

每条控制 `in_scope = True` 当且仅当(全仓扫描恒真,否则任一命中):
- 该控制 `protects` 任一 glob 经 `fnmatch.fnmatchcase`(确定性、不分平台;`\`→`/` 归一)
  命中 `in_scope[]` 中某路径;**或**
- 该控制 `entry_points` 中某文件等于、或位于 `in_scope[]` 中某路径之下(`ep == s` 或
  `ep.startswith(s + "/")`)。

投影只标 flag、**不删控制**(under-filter 时 subagent 仍可经 `out_of_scope_summary` 参考)。

## `--check` 校验项(intake 边界校验;失败退出码 2)

stdout `{"check":"controls-intake","ok":bool,"controls":N,"violations":[...]}`,stderr 诊断。
对每条控制断言:
- `name` 非空字符串;
- `kind` ∈ canonical 6-enum(`auth`/`sandbox`/`input-validation`/`aslr`/`cfi`/`other`)
  **或**可归一别名(见下);
- `evidence` 非空、元素均为非空字符串(≥1 锚点);
- `protects`(若存在)为字符串列表;`entry_points`(若存在)为字符串列表。

任一违例 → 退出码 2,stdout 不 emit 部分结果。

## `kind` 别名归一(常量、可单测;与 `inventory.md:45-48` 一致)

canonical 6-enum + 别名:

| 别名 | → canonical |
|---|---|
| `authn`/`authz`/`rbac`/`iam`/`sso` | `auth` |
| `waf`/`validation`/`sanitization`/`encoding` | `input-validation` |
| `seccomp`/`container`/`isolation` | `sandbox` |

`aslr`/`cfi`/`other` 无别名(已是 canonical)。归一表抽为 `KIND_ALIASES` 常量、可单测。

## 诚实边界(承 mgh-init CVE-2025-41248;fragment 强制)

inventory 是 `/mgh-init` 的 **LLM-induced 候选**,**断言存在不断言有效**。控制「下架」一条
finding 仅当其 `evidence` 锚点确认位于该 finding 数据流**上游**(evidence-grounded);否则只
降权、不中和。被控制影响的 finding/chain 须在 `report.md` 单列,不静默消失。详见
`core/prompts/fragments/controls-context.md`。
