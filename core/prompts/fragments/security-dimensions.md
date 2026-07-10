<!--
  rewrite-original. 安全维度目录:驱动 sra 对变更各 capability 做系统化、逐维度的
  安全缺口发现(非泛泛 OWASP 清单)。9 维度 ×(检查什么 + 典型缺口 + 该维度缺口如何
  触发控制匹配)。面向人读正文用简体中文;维度键 / category 名保持原样(英文/符号)。
  本文件随 install 分发到目标项目,只含操作性内容(无研发态悬空引用)。
-->

# 安全维度目录(security-dimensions)

`sra-augment` 对每个 capability 的 requirements 与业务面**逐维度过一遍**,每命中一条
**具体缺口**(锚定到具体 requirement / 接口 / 字段,无锚定丢弃)。`sra-clarify` 据各维度
找「分析必需但代码/proposal/记忆都判不出」的业务事实,发澄清问。

维度可扩;缺口标注 `dimension`(下表「维度键」),维度外缺口标 `dimension: other` 保留、不丢。

| 维度 | 维度键 | 检查什么 | 典型缺口 | 该维度缺口如何触发控制匹配(category) |
|---|---|---|---|---|
| 敏感数据 | `sensitive-data` | 触及 PII / 凭据 / 金融(身份证 / 银行卡 / 手机 / 邮箱 / 密码 / token)?at-rest · in-transit · log · response 是否声明屏蔽? | 返回体含银行卡号未脱敏 | `data-masking`(at-rest/response/log 屏蔽);`crypto`(传输 / 落地加密) |
| 注入 | `injection` | 外部输入入口是否声明校验?SQLi / XSS / 命令注入 / 路径穿越 / SSRF / 反序列化 / XXE | 动态 `ORDER BY` 拼接;富文本未编码 | `input-validation`(参数校验 / 转义 / 参数化) |
| 横向越权·IDOR | `horizontal-authz` | 按 id / key 访问的资源是否校验**归属 / 租户**? | `GET /order/{id}` 未校验 id 归属 | `authorization`(归属 / 租户判定) |
| 纵向越权 | `vertical-authz` | 是否暴露管理员级操作?是否角色校验? | 普通用户可调管理接口 | `authorization`(角色 / 权限判定);`authentication`(身份边界) |
| 认证 | `authentication` | 新端点 / 资源是否在鉴权之后?session / token? | 新增公开端点暴露内部数据 | `authentication`(登录 / 会话 / token 校验) |
| 完整性·关键操作 | `integrity` | 金融状态变更 / 状态机 / 幂等 / 防重放? | 退款无幂等键;状态机可被乱序推进 | `crypto`(MAC / 签名防篡改);`csrf`(跨站请求伪造 / 状态机完整性);`authorization`(操作授权) |
| 审计 | `audit` | 安全相关操作是否记录(且不记敏感数据)? | 登录失败未审计;审计日志含明文卡号 | `audit-logging`(安全事件留痕) |
| 限流·滥用 | `rate-limiting` | 高价值端点(登录 / OTP / 支付)是否限流? | 短信验证码无频控,可被刷 | `rate-limiting`(频控 / 配额) |
| 密钥·配置 | `secrets` | 硬编码密钥 / 密钥轮换 / 配置敏感项? | 配置文件硬编码 API key | `crypto`(密钥管理 / 加密) |

## 维度 → category 触发关系(信号-1 维度契合)

缺口匹配存量控制时,**信号-1 维度契合**是必要条件:缺口的 `dimension` 与控制能治的维度
相交。控制能治的维度由其 mgh-init inventory `category` 派生(确定性映射):

| category | 能治维度(派生) |
|---|---|
| `authorization` | 横向越权·IDOR · 纵向越权 |
| `authentication` | 认证 |
| `input-validation` | 注入 |
| `data-masking` | 敏感数据 |
| `crypto` | 敏感数据 · 完整性·关键操作 · 密钥·配置 |
| `csrf` | 完整性·关键操作 |
| `rate-limiting` | 限流·滥用 |
| `audit-logging` | 审计 |

> 维度契合只做**候选收窄**(保留全部控制、只标维度),不硬切丢弃;真正的匹配还要叠加
> **业务域相似**(同业务域类似接口)+ **业务事实**(角色 / 归属)两个语义信号。仅文件
> 路径重叠**非**充分条件。

## 每维度缺口产出要求

每条缺口 MUST:
- 锚定一条**具体**变更 requirement / 接口 / 字段(它保护什么)——`anchor{requirement? , endpoint? , field?}`;
- 标 `dimension`(上表维度键;维度外标 `other`);
- 给一句风险简述(为何这是缺口);
- 无 `--rules` 时仅产「应满足的安全属性」requirement(无控制锚点);有匹配控制时附
  `recommended_control` + `evidence` + 「复用勿重造」+ 业务域相似理由。

不锚定任何 requirement / 接口 / 字段的泛泛 OWASP 清单式缺口(如「应防 SQL 注入」未指向
任一接口)**MUST 丢弃**,不进入 draft。
