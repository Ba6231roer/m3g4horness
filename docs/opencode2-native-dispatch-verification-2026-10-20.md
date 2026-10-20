# opencode 2.1.0 原生派发能力实测记录(2026-10-20)

> **受众:人类·仅研发仓**(维护者决策文档)。本文是
> [docs/fanout-native-dispatch-5why-2026-10-20.md](fanout-native-dispatch-5why-2026-10-20.md)
> 的实测证据底座:前面两份分析基于源码静态阅读,本文记录在本机
> `opencode2` v2.1.0 上实际跑出来的结果。所有结论标注「实测」的都可在本机复现;
> 标注「未测」的不得当作已证事实。
>
> 测试目录(仓外,非产品代码):
> `C:\DEV\_mgh_oc2_probe`(权限/钩子/工具探针)、`C:\DEV\_mgh_oc2_p4`(路径转述试点)。

---

## 0. 实测总结论

1. **v1 插件在 2.1 被拒载,实锤**:mgh 现有守卫插件按 v1 具名导出,2.1 日志明确报
   `Plugin must export a default definition with an id and an effect or setup function`;
   加载失败只是 WARN,fail-soft 继续。**企业升级 2.1 当天,opencode 面守卫静默失效**。
2. **v2 插件可用**:`export default { id, async setup(ctx) { ... } }` 正常加载;
   `tool.execute.before`、`permission.evaluate` 钩子在主会话与**子代理会话**里都实测触发;
   插件注册的自定义工具(`probe_echo`)被模型成功调用。
3. **原生子代理派发可用**:同一条 assistant 消息里的多个 `subagent` 调用并发执行;
   6 个单元试点中 6 个子会话全部完成;子会话可按 `parentID` 通过 HTTP API 枚举。
4. **`opencode2 run` 连的是同一个常驻 service**:跑前后 service pid 不变(88380),
   新会话出现在同一服务里。**「子进程=独立认证域」这个给 runner 判死刑的前提,
   在 2.1 上不再成立**(企业环境仍需实测确认;见 §7 D8)。
5. **P11 权限询问挂死已实测复现**:HTTP 创建的会话(无客户端应答)越目录读取时
   出现 pending `external_directory`,20 秒内没有任何自动应答;源码无超时,理论上无限挂。
   - `reject + message` 回复 → 约 10 秒内模型收到拒绝并正常收尾(succeeded);
   - `interrupt` → pending 清空,会话 `outcome=interrupted`;
   - `permission.evaluate` 钩子把 `ask` 改写成 `deny` → **pending 数为 0**,
     模型收到明确的拒绝文案后正常收尾。**这是无人值守「永不弹问」的根治手段。**
6. **P4 路径转述试点**:6 个含长路径、下划线、中文、空格、诱饵目录的单元,
   编排器 6/6 逐字转述、6/6 子代理读对文件、6/6 nonce 正确、零诱饵命中,76 秒完成。
   这是**阳性试点,不是认证**:样本只有 6 个,且用的是本机 GLM-5.3-flash,不是企业弱模型。
   按统计计算,72 次零错误也只能把 95% 上界压到约 4.2%,不能证明「接近零」。

---

## 1. 环境与基线

| 项 | 值 | 证据 |
| --- | --- | --- |
| CLI | `opencode2` → `C:\Users\megah\AppData\Local\opencode2\opencode2` | `command -v opencode2` |
| 版本 | `opencode v2.1.0` | `opencode2 --version` |
| 状态目录 | `C:\Users\megah\.local\state\opencode` | `opencode2 debug paths` |
| 服务注册文件 | `C:\Users\megah\.local\state\opencode\service.json` | 实际文件;内容 `{id,version,url,pid,password}`(密码已脱敏) |
| 服务 URL | `http://127.0.0.1:45278` | service.json;Windows 重映射端口 |
| 服务 pid | 88380(实测期间未变) | service.json 前后读取 |
| 可用模型 | `zai-coding-plan/glm-5.3-flash` 等 | `opencode2 models`;免费模型被本机 IP 风控拒绝 |
| 测试模型 | `zai-coding-plan/glm-5.3-flash` | 本文所有模型调用均用它 |

> 注意:`opencode2 plugin list` 会把 v1 插件列为 `local`,**但这只是配置项列表,
> 不代表加载成功**——加载失败要看日志(§2)。

---

## 2. V1:守卫插件 v1 形状被 2.1 拒载(实测)

**操作**:在仓库 `C:\DEV\m3g4horness`(已安装 mgh 的 `.opencode/plugins/block_adhoc_scripts.ts`)
运行任意会激活插件的命令,然后查 `~/.local/share/opencode/log/opencode.log`。

**日志原文(短引)**:

```
level=WARN message="failed to load plugin"
target="C:\\DEV\\m3g4horness\\.opencode\\plugins\\block_adhoc_scripts.ts"
cause="Cause([Fail(PluginModule.LoadError: Plugin must export a default definition
with an id and an effect or setup function. (cause: SchemaError(Missing key
  at [\"default\"])))])"
```

**结论**:
- 2.1 的模块契约只接受 `export default { id, effect|setup }`;
  mgh 的 `export const BlockAdhocScripts = async (ctx) => ({...})` 不满足。
- 失败是 **fail-soft**(仅 WARN),会话继续——所以表面上「一切正常」,实际没有守卫。
- 这是独立于扇出转向的 **P0 急件**:升级 2.1 前必须先迁移守卫插件。

**对照**:在 `_mgh_oc2_probe` 写 `export default { id, async setup(ctx) {...} }`,
`setup` 里 `await ctx.tool.hook(...)` 后写标记文件;实测 `probe_loaded.txt` 出现
`setup-start` / `hooks-registered`,插件加载成功。
**注意**:`setup` 必须是 `async` 并 `await` 钩子注册;同步写法在第一次工具调用前
可能还没注册完成(实测第一次尝试没有捕获到调用,改 async 后正常)。

---

## 3. V2:HTTP API + service.json 发现(实测)

用 Python 标准库读取 `service.json`,以 HTTP Basic(`opencode:<password>`)打 API:

| 路径 | 状态 | 说明 |
| --- | --- | --- |
| `GET /api/info` | 200 | 返回 version 2.1.0、pid 88380、URL |
| `GET /api/session?limit=3` | 200 | 返回会话列表(含 location/model/outcome/time) |
| `GET /api/session/active` | 200 | 返回本进程正在执行的会话集合 |
| `GET /api/permission/request` | 200 | 返回 location 范围内的 pending 授权请求 |

**结论**:「Python 脚本发现服务 + 读会话/权限/中断」这条通道**实测可用**,
不需要 npm 依赖,符合 mgh 零依赖约束。

---

## 4. V3:钩子在主会话与子会话都触发(实测)

插件注册两个钩子并落 JSONL:

- `tool.execute.before`:记录 `tool/sessionID/agent/input`;
- `permission.evaluate`:记录 `action/resources/effect/sessionID/agent`。

实测结果:
- 主会话 `read` 工具触发 `execute.before` 与 `permission.evaluate`
  (`action=read`, `effect=allow`)。
- 原生子代理会话的工具调用**同样触发** `execute.before`:
  子会话 `ses_ea75d7953...` 与 `ses_ea75d7952...` 的 `read`(agent `probe-child`)
  都被同一插件记录。**守卫对子代理零降级的源码结论,实测成立。**
- `permission.evaluate` 对子会话同样触发(源码结论 + 主会话实测;子会话的 ask 场景
  在 §6 的 pending 复现中由同一服务处理)。

---

## 5. V4:原生子代理并发与自定义工具(实测)

### 5.1 并发

编排 agent 在一条 assistant 消息里发出两个 `subagent` 调用:
- 两次 `execute.before` 时间戳:`1792488408742` / `1792488408744`(相差 2ms);
- 两个子会话 ID 不同,两个子代理都读了 `notes.txt` 并返回 nonce;
- 父会话收到两个完成结果后回复 `DONE`。

**结论**:同消息多子代理并发派发**实测成立**。

### 5.2 子会话枚举

用 `GET /api/session?parentID=<父会话>` 查到 6 个子会话(agent `p4-child`,
parentID 正确,outcome `succeeded`),与插件钩子记录的 6 个子会话 ID 完全一致。
**结论**:看门狗按 `parentID` 枚举后代的路径**实测可用**。

### 5.3 自定义插件工具

`ctx.tool.transform(editor => editor.add({ name: "probe_echo", ... }))` 注册工具;
模型被要求调用它,实际调用成功,输出 `ECHO HELLO`,`execute.before` 捕获到
`tool=probe_echo`。**结论**:通道 B(插件自定义派发工具)的基础能力**实测可用**。

---

## 6. V5:P11 权限询问挂死的复现与三种处置(实测)

测试 agent `probe-ask` 的权限:
`read: allow / bash: deny / edit: deny / execute: deny / external_directory: ask`。
让它读取项目外文件 `C:\DEV\m3g4horness\VERSION`。

### 6.1 `opencode2 run`(有内置非交互应答器)

输出:

```
! permission requested: external_directory (C:/DEV/m3g4horness/*); auto-rejecting
✗ Read C:/DEV/m3g4horness/VERSION failed
Error: This non-interactive run cannot ask the user for permission, so the request
was rejected. Continue without this action.
```

模型收到拒绝后继续收尾,**不挂**。`permission.evaluate` 记录到 `action=external_directory`,
`effect=ask`。

### 6.2 HTTP 创建的会话(无客户端应答 = 无人值守)

用 `POST /api/session` 在 `_mgh_oc2_probe` 创建会话(agent `probe-ask`),
`POST /api/session/:id/prompt` 发送同样的越目录读取指令。

观测:
- 前 18 秒 `active=true`、pending=0;
- t+20s 出现 pending:
  `{"action":"external_directory","resources":["C:/DEV/m3g4horness/*"],...}`;
- **没有任何自动应答**;源码中 `Permission.assert` 的 `Deferred.await` 无超时,
  因此无人值守会无限挂起。

**这就是维护者确认的「隔夜挂死」的 2.1 复现。**

### 6.3 处置 A:`reject + message`

对 pending 请求 `POST /api/session/:id/permission/:rid/reply`
`{"decision":"reject","message":"Unattended mgh run: ..."}`:
- 约 10 秒后会话 `outcome=succeeded`;
- 模型收到拒绝文案并正常收尾,没有中断整个回合。

**结论**:看门狗对漏网 ask 的首选动作是 `reject + message`,不是杀会话。

### 6.4 处置 B:`interrupt`

对 pending ask 的会话 `POST /api/session/:id/interrupt`:
- pending 立即清空(0);
- 会话 `outcome=interrupted`。

**结论**:interrupt 对挂起 ask 有效,但粒度是整个会话(会丢掉该单元本回合的进展)。
作为最后手段,不作为首选。

### 6.5 处置 C:`permission.evaluate` 把 ask 改写成 deny(推荐)

插件在 `permission.evaluate` 钩子里,当运行域标记文件存在且 `event.effect === "ask"` 时:

```ts
event.effect = "deny"
event.message = "Unattended mgh run: interactive approval is disabled. ..."
```

实测结果:
- 日志 `rewritten: true`;
- **pending 数始终为 0**(根本没有创建授权请求);
- 会话 14 秒内 `succeeded`,模型看到
  `permission.rejected: Unattended mgh run: interactive approval is disabled...`
  并继续收尾。

**结论**:这是无人值守「永不弹问」的根治手段。配置层再加 `external_directory`/
`question` 的硬 deny 作为插件失败时的 floor。

---

## 7. V6:P4 路径转述 6 单元试点(实测,阳性但不构成认证)

### 7.1 设计

- 6 个单元,覆盖三类路径:普通长路径、`acme_wing_项目`(下划线,带
  `acme-wing_项目` 与 `acme\wing_项目` 两个诱饵)、`案件材料 2026/登录鉴权_模块`
  (中文+空格,带 `案件材料2026` 诱饵)。
- manifest 为 JSON,路径是 Windows 反斜杠绝对路径。
- 编排 agent 读取 manifest,按单元逐个调用 `subagent`,prompt 里只放
  `TASK_FILE=<绝对路径>` + `ACTION=READ_AND_ECHO`;
- 子代理只读该路径并回 `ECHO <首行>`。

### 7.2 结果

| 指标 | 结果 |
| --- | --- |
| 编排器发出的 `subagent` 调用数 | 6/6 |
| prompt 中的 `TASK_FILE` 与 manifest 逐字节相等 | **6/6** |
| 子代理实际读取路径与 manifest 相等 | **6/6** |
| 子代理回显 nonce 正确 | **6/6** |
| 命中诱饵(`DECOY_OK`) | **0** |
| 总耗时 | 76 秒 |

**结论**:在这 6 个样本、本机 GLM-5.3-flash、路径已物化的条件下,
「一个绝对路径 + 固定一句话」的转述**没有出现错误**。这支持「原生转述可行」的
方向,但**不能**证明错误率接近零:
- 6 个样本的 95% 置信上界约 39%(零错误时);
- 即使 72 次零错误,上界仍约 4.2%;若真实错误率 1%,72 次全对的概率约 48%;
- 本机模型不是企业弱模型;企业网关的上下文压力、压缩、长任务未覆盖。

### 7.3 生产防线(不依赖实验结论)

无论试点结果多好,生产 native 派发都必须有确定性校验:
- 子代理调用前,插件按 `native_plan.json` 校验 `description`(unit id)与
  `prompt` 中的路径属于同一单元、单元未 `.done/.failed`;
- 不匹配 → `Tool.Error` + recipe,不启动子代理;
- 更好的形态是让模型只输出**短 unit id** 或 **wave 号**,由插件从计划读长路径
  (见 5why 文档 P4 的结构性缓解)。

---

## 8. V7:D8 预确认——`opencode2 run` 连共享 service(实测)

- 跑 `opencode2 run` 前后读取 `service.json`:pid 始终 88380,URL 不变;
- 新会话出现在 `/api/session` 列表里,location 指向测试目录;
- 说明 `run` 没有另起一个独立认证域的进程,而是连到常驻 service。

**含义**:
- 2.1 上「子进程=独立认证域」的前提**不成立**;`opencode2 run` 的 CAS 再登录问题
  可能不复存在(企业环境仍需实测)。
- 这给「不删 runner、降级保留」提供了另一条路:升级 2.1 后,旧 runner 的
  spawn 形态可能只需小改即可复活,作为 native 模式的兜底。
- 但它不改变本轮的推荐:原生派发在形态上更简单、无进程管理/无 XDG/无输出尾扫描,
  仍是主路线。

---

## 9. 尚未实测(不得当作已证)

1. **企业 CAS 真机**:2.1 服务进程在 CAS 环境下的登录/刷新/401-重登-续跑全链;
   本机用的是 zai-coding-plan 订阅模型,不是企业网关。
2. **企业弱模型**:本机 GLM-5.3-flash 不是企业内网弱模型;P4 试点不能外推。
3. **权限 ask 的企业配置来源**:企业是显式 `external_directory: ask`,还是 v1 旧配置
   迁移导致未命中;决定要在哪一层加 deny。
4. **`opencode2 run` 在企业的 service 复用**:本机已证同 service;企业是否也常驻
   同一 service、是否有 TUI 在跑,需要现场确认。
5. **看门狗的常驻形态**:Windows 下 detached Python、服务重启、密码变化、
   SSE 断流等,尚未做长跑压测。
6. **子代理工具调用的守卫拦截**:钩子触发已证;但「守卫真的拦住越树写/读并给出 recipe」
   需要迁移后的守卫插件在 2.1 上实测。
7. **插件 API 稳定性**:2.x 仍在演进,锁版本与回归测试尚未建立。
8. **压缩后再定向**:6 单元试点没有触发压缩;init 级 900 批的 3–4 次压缩未测。

---

## 10. 复现指引(摘要)

- 探针目录:`C:\DEV\_mgh_oc2_probe`(agent `probe-ask` / `probe-child` / `probe-orch` /
  `probe-tool`;插件 `.opencode/plugins/probe.ts`)。
- P4 试点目录:`C:\DEV\_mgh_oc2_p4`(manifest.json、6 个 task 文件、诱饵目录、
  `.opencode/plugins/recorder.ts`)。
- 关键命令:
  - `opencode2 --version` / `opencode2 debug paths` / `opencode2 service status`
  - `opencode2 run --model zai-coding-plan/glm-5.3-flash --agent <agent> "<prompt>"`
  - Python 读 `~/.local/state/opencode/service.json` → Basic auth → `/api/session`、
    `/api/session/:id/prompt`、`/api/session/:id/permission`、`.../interrupt`、
    `.../permission/:rid/reply`。
- 日志:`~/.local/share/opencode/log/opencode.log`(插件拒载的 WARN 在这里)。

---

## 11. 诚实边界

本文的「实测」仅指本机 `opencode2` v2.1.0 + 本机模型 + 本机 Windows 环境;
企业内网、企业网关、企业弱模型、企业 CAS 流程均未在本机复现。所有「生产可用」
结论都必须经过企业真机验证;本文只证明**机制存在、可被驱动、可被拦截/恢复**,
不证明**企业环境下稳定**。
