# 实机笔记:add-mgh-native-dispatch-tool(本机 opencode 2.1.0)

> **受众:双受众**(维护者评审 + 归档后供后来者对账)。记录 2026-10-21 在本机
> `opencode2 v2.1.0` + `zai-coding-plan/glm-5.3-flash` 上对派发插件 `mgh_dispatch.ts`
> 的实机闸门结果。所有结论标注「实测」;标注「未测」的不得当作已证事实。

## 0. 结果总览

| 闸门 | 结果 |
| --- | --- |
| 4.1 小计划全链(一次调用跑完 ≥2 波) | **过**:5 单元 / 3 波 [2,2,1] 一次 `mgh_dispatch` 调用全部 `done`,摘要与磁盘标记逐一对上 |
| 4.2 幂等重入 | **过**:再调用 `dispatched:0, skipped_terminal:5`,零新会话 |
| 4.2 错抄短号 fail-loud | **过**:`units:["sdr-zzzz"]` → 工具错误 + recipe(`未知短号…`),零会话 |
| 4.2 中止级联 | **过**:中断编排器会话 → 波 1 两个活跃子会话 `outcome:interrupted`,波 2 未创建,`/api/session/active` 清空(零孤儿) |
| 4.2 令牌展开端到端 | **过**:令牌行调用内置 subagent 工具,子代理在任务全文中找到只存在于任务文件的 nonce(`NONCE-FOUND`) |
| 附加:primary 形态拒绝(真计划) | **过**:原版物化计划(agent=`sdr-review-fanout`,primary 孪生)→ 工具错误 + recipe,零会话 |
| 附加:任务文件不可读 fail-loud | **过**(事故中实证,见 §3):任务文件路径损坏 → 工具错误 + recipe,子代理未启动 |
| 4.3 企业 2.0.32 只读探测 | **未测**(交接内网,不阻塞归档;复现清单见 §5) |

## 1. 环境

- 宿主:`opencode2 v2.1.0`(常驻 service;`opencode2 run` 连同一服务,实测期间 pid 不变)。
- 模型:编排器与子代理均 `zai-coding-plan/glm-5.3-flash`(本机订阅模型,非企业弱模型)。
- 被测安装:`install.sh --opencode` 落入隔离小仓 `C:\DEV\_mgh_native_tool_gate\repo`
  (guard + dispatch 两插件、六命令壳、agent 孪生齐全);插件源为本 change 工作区版本。
- 测试计划:
  - `gate1` = **真实 sdr 链**物化(diff_group 4 个 ~40KB java 文件按缺省 64KB standalone
    预算分成 4+1 单元〔第 5 个是 install 落地的 `.mgh-sra/sensitive_catalog.json.example`
    被列入 diff〕,`--wave-size 2` → 3 波〔2,2,1〕)。物化 + `--check` 全过。
  - `gate2`/`gate5` = 手写探针计划(形状与物化计划一致):gate2 = probe-slow 慢单元
    4 个 2 波(级联闸门用);gate5 = probe-echo 单元 1 个(令牌闸门用)。
- **重要口径**:当前 tier 语义下 `emit_native_plan.py` 写进计划的 `agent` 字段是**子进程
  primary 孪生**(`sdr-review-fanout`);本工具按规格拒绝 primary(真计划上实测拒绝分支
  正确触发)。全链闸门用**字段编辑后的计划副本**(`agent` 改为 `sdr-review-native`,
  其余逐字同物化产物)跑通——这正是规格预留的形态:计划承载 subagent 孪生名属于第 7/8
  个 change(init 接入)要标准化的字段语义,sdr 本身不切换到本工具(本 change 非目标)。

## 2. 4.1 全链实测记录

一次编排器会话(`opencode2 run`,agent build)内调用
`mgh_dispatch {"plan": ".mgh-sdr/runs/gate1/native_plan.gate.json"}`(项目相对形,项目根
解析实测正确),工具内跑完 3 波,返回摘要(逐字):

```json
{"plan":".mgh-sdr/runs/gate1/native_plan.gate.json","mode":"all","waves_run":[1,2,3],"dispatched":5,"skipped_terminal":0,"done":5,"failed":0,"no_marker":0,"failed_units":[],"no_marker_units":[],"units":[{"id":"sdr-pqkq","wave":1,"session":"ses_ea3d6976affeXTc20q46vqTsQU","status":"done"},{…},{"id":"sdr-hypj","wave":3,"session":"ses_ea3cfee5fffeK0z0CAhD52Gf9Z","status":"done"}],"aborted":false}
```

- 磁盘对账:`markers/` 下 5 个 `.done`(含 dotfile `.mgh-sra.done`)+ 4 个 review 草稿
  JSON,与摘要 `done:5` 逐一对上;摘要零 findings、零任务文本(编排器上下文只进摘要)。
- 会话对账(过滤 `/api/session`):编排器 → 5 个子会话,`parentID` 全部指向编排器,
  `title` = 计划短号逐字,agent = `sdr-review-native`。
- 波次屏障:会话时间线显示波 1 全部终态后波 2 才创建(工具内顺序推进,全程零 LLM 波次
  回合——编排器只发了一次工具调用)。
- 子代理的 `sdr-review-native` 真实执行了评审(写草稿 + touch `.done`),说明「任务消息 =
  任务文件逐字 + 内置同款框架首行」的注入在真机上被弱模型正确执行。

## 3. 4.2 故障面实测记录

1. **幂等重入**:同一计划再调用一次 → `{"dispatched":0,"skipped_terminal":5,…,
   "waves_run":[]}`(逐字),零新会话——重试 = 幂等重入实测成立。
2. **错抄短号**:`units:["sdr-zzzz"]` → 工具错误逐字:
   `未知短号: sdr-zzzz;recipe: 合法短号只来自计划工件(native_plan.json 的
   waves[].units[].id,或物化 stdout 摘要)——NEVER 凭记忆转述`;会话清单零新增。
3. **primary 拒绝**:原版物化计划(gate3 重新物化、全新 markers、agent=
   `sdr-review-fanout`)→ 工具错误逐字:
   `agent sdr-review-fanout 是 primary 形态,不能作为子代理派发;recipe: 各 tier 需要
   各自的 subagent 形态孪生定义(mode: subagent)——NEVER 降级尝试或静默换名`。
   附带口径验证:全终态计划(无待派单元)提前返回摘要、**不**触发 agent/深度闸门
   (规格语义 = 创建前校验,零创建则无需校验;摘要如实报 skipped)。
4. **中止级联**:gate2 慢计划(probe-slow,Start-Sleep 90)派发中,经 HTTP
   `POST /api/session/<编排器>/interrupt` 中止编排器会话:
   - 波 1 两个活跃子会话 `outcome:interrupted`(级联逐个 interrupt 实测触发);
   - 波 2 未创建(每波创建前检查中止信号);
   - 中断后 `/api/session/active` 为空集(零孤儿子会话继续烧配额);
   - gate2 `markers/` 零标记(中止 ≠ 失败终态,单元经重物化自然回待派);
   - 编排器 CLI 收尾输出 `Tool execution interrupted`(工具调用被中止,级联先于返回完成)。
5. **令牌展开端到端**:编排器以令牌行
   `mgh-dispatch: plan=.mgh-sdr/runs/gate5/native_plan.json unit=pp-a1b2` 调用**内置
   subagent 工具**(agent=probe-echo,其纪律 = 在任务 prompt 中找 nonce):子代理回复
   `NONCE-FOUND`——nonce 只存在于任务文件中,证明钩子把令牌行展开成了文件全文后放行,
   编排器输出零任务文件路径。反向(非令牌文本)零干扰由形状锚与探针第 5b 步
   (TOKEN-ABSENT 语义)覆盖。
6. **任务文件不可读 fail-loud**(事故中实证):gate5 计划首版路径串损坏
   (`\r`/`\t` 控制字符注入文件名)→ 工具错误逐字:
   `任务文件不可读: <path> (ENOENT…);recipe: 计划与任务文件以最新一次
   emit_native_plan.py 物化为准——重跑物化后重试`,子代理未启动。该事故同时实证:
   插件对计划路径**逐字信任但逐字校验可读性**,坏路径在 spawn 前收口。

## 4. 诚实边界(本机实测的边界)

- 本机模型是订阅级 GLM-5.3-flash,不是企业弱模型;企业网关下的表现未测。
- 中止级联由**宿主中止信号**驱动:实测路径 = 会话级 interrupt(HTTP)→ 工具 signal
  触发 → 级联。编排器进程被直接杀死(而非会话 interrupt)的形态未测(子会话可能由
  常驻 service 继续推进——该形态的兜底是看门狗,不是本工具)。
- 配额自限(波间睡等)本机未实测(无企业配额画像);算术由 CI 镜像样例 +
  fake-host 冒烟(31 项)覆盖,画像缺省路径(零节流)实测成立。
- 深度上限保守缺省 1(宿主配置在插件面不可达)未实测越界场景(默认单层形态合法,
  越界形态按形状锚覆盖)。
- `wave`/`units` 选择面、`no-marker` 分类、`failed` 分类由 fake-host 冒烟覆盖
  (31 项全过),本机未单独实测(真实失败单元需要真 429/挂死,属看门狗/编排层演练)。

## 5. 企业 2.0.32 只读探测交接清单(不阻塞归档)

在企业内网机器上(宿主 2.0.32,只读探测,不接真实 CAS 凭证跑业务):

1. **插件加载**:`install.sh --opencode <目标项目>` 后跑任意会话,查服务日志确认
   `mgh_dispatch.ts` 无 `failed to load plugin` WARN(2.0.32 与 2.1.0 的模块契约差异
   在守卫插件迁移时已核对;本文件同契约)。
2. **工具注册**:会话内让模型调用 `mgh_dispatch --help` 等价物(或直接调用一个空计划)
   确认自定义工具出现在工具面(probe_echo 在 2.1.0 实测过;2.0.32 的
   `tool.transform` 面需同形确认)。
3. **会话域 API 面**:一次最小派发(单单元探针计划,agent 用任一 subagent 孪生)确认
   `session.create/prompt/wait/interrupt` 四原语在 2.0.32 可用;`session.wait` 在
   2.0.32 是 experimental 端点(`/api/experimental/session/wait`),重点确认。
4. **权限断言面**:`permission.assert(subagent)` 在 2.0.32 的动作名/资源面与 2.1.0
   是否一致(差异 → 回填 fanout runtime 契约版本矩阵 + 插件适配)。
5. **差异回填**:以上任一差异记入 `core/contracts/fanout/runtime.md`「native dispatch
   tool」版本矩阵;无法适配的差异升级为 fix change,不静默降级。

## 6. 复现指引(摘要)

- 隔离仓:`C:\DEV\_mgh_native_tool_gate\repo`(.gitignore 排除 `.opencode/`、
  `.mgh-sdr/`;feat 分支 4 个 ~40KB java 文件 + install 落地的 `.mgh-sra` 示例)。
- 物化:`py <mgh-core>/scripts/diff_group.py --repo <repo> --base master --branch feat
  --checkpoints <run>/markers --materialize <run>/slices` → `emit_native_plan.py --tier
  sdr … --wave-size 2`;`--check` 同参。
- 派发:`opencode2 run --model zai-coding-plan/glm-5.3-flash --agent build "<一次性
  工具调用指令>"`(编排器指令保持单调用、单职责,弱模型才不失稳)。
- 中止:Python 标准库读 `~/.local/state/opencode/service.json` → Basic auth →
  `GET /api/session`、`POST /api/session/:id/interrupt`、
  `GET /api/session?parentID=<orch>`。
- 关键命令与全部回执已存:`/c/DEV/_mgh_native_tool_gate/run{1,6}.out`。
