# Contract: 业务记忆 `business_context.json` + 澄清 shape

Producer: sra-clarify(发澄清问)/ `merge_memory.py`(幂等写回答案)。
Consumer: sra-augment(信号-3 业务事实)/ sra-clarify(去重发问)/ 后续 sra 迭代(累积复用)/
未来 `/mgh-blst`(越权测试消费 `roles[]` / `interface_authz[]`)。

**落位**:`<project>/.mgh-sra/business_context.json`(项目根 = 含 `openspec/` 的目录;**不在**
任一变更内,跨变更存活)。与 mgh-init 把代码控制沉淀成 `controls_inventory.json` **同构**:
一个记控制,一个记业务语义。退出码 `0/1/2`。

## `business_context.json`

```json
{"version":1,
 "roles":[{"name":"customer","capabilities":["..."],"boundary":"<能力边界>"}],
 "domains":[{"name":"支付","representative_endpoints":["POST /api/transfer"]}],
 "sensitive_fields":[{"name":"bankCardNo","reason":"金融凭据","mask":"保留后 4 位"}],
 "interface_authz":[{"endpoint":"POST /refund","model":"按 customer_id 归属","roles":["customer"]}],
 "business_rules":[{"rule":"<业务规则简体中文>"}],
 "clarifications":[{"fact_key":"refund.roles","value":"仅 customer",
   "source":"user-asserted","updated_at":null}]}
```

| field | note |
|---|---|
| `version` | schema 版本(向前兼容校验用,`merge_memory --check` 按版本校验) |
| `roles[]` | 角色 + 能力边界(信号-3;跨接口复用一份) |
| `domains[]` | 业务域 → 代表接口(信号-2 业务域相似匹配) |
| `sensitive_fields[]` | 业务定制必屏蔽字段 + 原因 + 屏蔽方式 |
| `interface_authz[]` | 已知接口 → 越权处理范式(**直接答「以前类似接口怎么做」**;下轮相似接口复用) |
| `business_rules[]` | 影响安全分析的业务规则 |
| `clarifications[]` | 问答日志,每条 `{fact_key, value, source, updated_at}`;`source` 恒为 `user-asserted` |

**记忆是用户断言,非代码真相**(显式代码/proposal 声明 > 用户记忆 > 默认猜测)。记忆条目
MUST NOT 覆盖代码既有声明;冲突时代码为准,manifest 披露冲突项。

## `clarification`(a2 sra-clarify 产出;编排器批量暂停问用户)

```json
{"id":"C-001","capability":"payment-api","dimension":"horizontal-authz",
 "question":"`POST /refund` 哪些角色用?",
 "why_it_matters":"越权缺口匹配需角色边界;无角色则无法判归属",
 "default_guess":"假设仅 customer 角色用","fact_key":"refund.roles"}
```

| field | note |
|---|---|
| `id` | 本次澄清编号 |
| `capability` / `dimension` | 归属 capability + 触发维度 |
| `question` / `why_it_matters` | 问什么 + 为何影响安全分析 |
| `default_guess` | 默认猜测(可秒批 / 改 / `--no-interactive` 跳过用默认) |
| `fact_key` | 幂等键;已记 `fact_key` 不重发(`merge_memory` 据其去重累积) |

## 幂等累积(`merge_memory.py`)

把用户答案按 `fact_key` 累积进 `clarifications[]`(及对应 `roles[]`/`domains[]`/等):已存在
`fact_key` **原地更新** + 记 `updated_at`;新 `fact_key` 追加。首跑无文件则创建 + `version: 1`。
重跑同变更不重复累积。所有写落在 `project_root`(= `MGH_TARGET`)子树内。

## 跨迭代复用(下游消费契约)

记忆累积越多,后续 sra 迭代:澄清数递减(已记事实不发问)、业务域匹配更准(直接复用
`interface_authz[]`)。`roles[]` / `interface_authz[]` / `sensitive_fields[]` 预留
`/mgh-blst` 消费口(据角色 + 越权范式设计业务耦合测试)。
