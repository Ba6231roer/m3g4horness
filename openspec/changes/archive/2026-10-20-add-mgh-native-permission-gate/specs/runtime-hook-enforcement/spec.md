## ADDED Requirements

### Requirement: 运行域内权限询问闸门(opencode 2.x permission.evaluate)

opencode 守卫插件 SHALL 在权限询问产生之前把它在运行域内确定性关闭:同一插件 default 导出的
`setup` 内注册 `permission.evaluate` 钩子(注册在 `setup` 返回前被 `await`),回调为纯函数(只依据
事件字段与磁盘哨兵改写 `event.effect` / `event.message`,无外部副作用,重复求值幂等)。规则:

1. **域外零影响**:项目根的六个运行根(`.mgh-init`/`security-scan`/`.mgh-sra`/`.mgh-srr`/
   `.mgh-ut-init`/`.mgh-sdr`)下均无 `.active` 哨兵时,回调 SHALL 原样返回,不改写任何效果——
   非 mgh 日常使用的询问行为与无本插件时完全一致。
2. **ask 改写 deny**:运行域内 `effect === "ask"` SHALL 改写为 `deny`,`event.message` 附一句
   可操作的替代提示(说明无人值守运行不接受交互式批准,引导走受信路径/受控物化)。**唯一例
   外**:`action === "external_directory"` 且**全部** resources 都落在当前命中哨兵的
   `read_roots[]` 之内时,SHALL 改写为 `allow`——这些根是用户事先批准的只读外部目录,放行来
   源是用户同意,不批准的(或部分在外的)一律 deny,NEVER 保留 ask(保留即挂死)。
3. **question 拒绝**:运行域内 `action === "question"` 且效果非 deny 时 SHALL 改写为 `deny`
   并附「走批量澄清/断点续跑流程」提示——`question` 在默认 agent 上是 allow,不经此规则即为
   无人应答挂死面。
4. **deny 不碰**:规则级 `deny` 在钩子之前已短路,回调对 deny 效果无需(也不会)求值。
5. **哨兵读取 fail-closed**:命中哨兵的 JSON 不可解析时按「无 read_roots」处理(询问一律
   deny);哨兵存在性检查与 JSON 解析失败 NEVER 抛出影响宿主——异常时按域外处理(原样返回)
   并记录 best-effort 诊断。
6. **glue 边界声明**:本钩子包含的判定仅限上述固定改写规则(询问面),工具调用拦截的判定
   仍单一住在 Python 守卫;`read_roots` 的语义来源是哨兵(由确定性脚本写盘),插件只做成员
   归属检查。
7. **残余边界披露**:本闸门管不到 Form/MCP elicitation(另一套问询机制,不经
   `permission.evaluate`)、管不到 provider-executed 工具(不过本地权限层)、管不到不做权限
   断言的自定义工具——这些残余挂死面在契约与诚实边界中披露,由后续看门狗兜底。

#### Scenario: 运行域内越目录读的 ask 被改写为 deny

- **WHEN** 运行域内(`<项目>/.mgh-sdr/.active` 在场)某 agent 配置 `external_directory: ask`,
  其会话发起项目外路径读取,资源**不在**哨兵 `read_roots[]` 内
- **THEN** 权限询问根本不产生(pending 恒为零),工具调用以 deny + 替代提示失败,模型看到提
  示后继续本回合收尾——不出现「等待授权挂起」(修复前:pending 无超时,无人值守挂到用户回
  来)

#### Scenario: 用户批准的只读根放行

- **WHEN** 同上场景但资源全部落在哨兵 `read_roots[]`(如 sdr 声明并经用户确认的外部前端仓)
  内,效果为 ask
- **THEN** 改写为 allow,外部受控检索照常进行——外部仓工作流不因闸门回归;部分在内部分在
  外的资源集合按 deny 处理(NEVER 部分放行)

#### Scenario: question 在运行域内被拒绝

- **WHEN** 运行域内子代理调用 `question` 动作(默认 agent 上该动作 allow)
- **THEN** 改写为 deny + 「走批量澄清/续跑」提示,子代理收到失败继续——不出现无人应答的问
  询挂起

#### Scenario: 域外零影响

- **WHEN** 项目内六个运行根均无 `.active`(非 mgh 运行),任一会话触发任意 ask(如读 `.env`)
- **THEN** 闸门原样返回,宿主正常弹询问/按其默认处理——日常使用与无本插件一致

#### Scenario: 哨兵 JSON 损坏时 fail-closed 且不伤宿主

- **WHEN** 命中的 `.active` 哨兵内容不可解析,运行域内发生 ask
- **THEN** 按「无 read_roots」处理(ask 改写 deny),插件不抛出、不影响宿主其余权限判定;
  best-effort 诊断可见

#### Scenario: CI 形状锚

- **WHEN** CI 检查插件源码(无 opencode 运行时)
- **THEN** 源码形状断言要求 `await ctx.permission.hook("evaluate"` 注册在场、ask→deny 改写
  与 question 拒绝与 read_roots 放行三分支在场、六运行根哨兵检查在场——移除任一分支即
  fail-loud

#### Scenario: 改写幂等(重复求值)

- **WHEN** 同一权限断言因回复批量重评估等原因再次触发钩子
- **THEN** 改写是事件字段与磁盘哨兵的纯函数,重复求值结果一致,无累计副作用

## MODIFIED Requirements

### Requirement: opencode 2.x 插件模块契约与形状自检

The opencode `.ts` shim SHALL satisfy the opencode 2.x plugin module contract: a **default
export** of the form `{ id: <string>, setup: <async function> }`, with **every** hook the
plugin registers — the `tool.execute.before` guard pipe AND the `permission.evaluate` gate —
registered via the plugin context's hook APIs **and each registration awaited inside `setup`
before `setup` returns** (a fire-and-forget registration lets the first tool call slip past
an unregistered hook). The hook callbacks SHALL receive a **single event object** — the tool
callback reads the tool id from `event.tool` and the tool arguments from `event.input`, the
permission callback reads the action/resources/effect from its evaluation event — the 1.x
two-parameter `(input, output)` callback form is removed. The shim SHALL remain glue-only
(activation gating, regexes, whitelists, subtree decisions live only in the Python guard; the
permission gate's fixed ask-rewrite rules are the one declared in-process exception, spec'd
at the gate requirement). The repo's CI SHALL statically assert the module shape (default
export with `id` + `setup` present; both hook registrations awaited; the 1.x named-export
form absent) so a future opencode module-contract change cannot silently disable the guard
again — opencode's own plugin-load failure is fail-soft (a WARN in the service log, sessions
continue), so shape drift SHALL be caught by CI, not by runtime. The shim file targets the
2.x contract; 1.x opencode installations keep the previously released shim file (no
dual-shape file — a file satisfying both contracts is not expressible, and carrying two
files would double the wiring surface).

#### Scenario: 2.x 服务加载插件并触发单事件对象回调

- **WHEN** opencode 2.x 加载 mgh 插件(项目 `.opencode/plugins/` 自动发现)且任一会话发
  起工具调用或权限断言
- **THEN** 插件以 default 导出被接受(服务日志无 `Plugin must export a default
  definition…` 拒载记录),`tool.execute.before` 与 `permission.evaluate` 回调各收到其单事件
  对象——不存在 `(input, output)` 双参形态

#### Scenario: 注册竞态防护

- **WHEN** 插件 `setup` 尚未返回时会话已发起首个被管工具调用或权限断言
- **THEN** 因两类钩子注册都在 `setup` 内被 `await`,该调用/断言仍命中已注册的管道——不存在
  「注册未完成 → 漏过 → 守卫/闸门静默缺席整段早期会话」的窗口

#### Scenario: CI 静态形状自检

- **WHEN** CI 检查插件源码(无 opencode 运行时)
- **THEN** 源码形状断言要求 `export default` + `{ id` 存在、`await ctx.tool.hook(` 与
  `await ctx.permission.hook(`(两注册均被 await)存在,且 1.x 具名导出形态
  (`export const BlockAdhocScripts` / 双参回调)缺席——模块契约漂移从「运行期静默拒载」变为
  CI fail-loud

#### Scenario: 宿主拒载的 fail-soft 边界保持披露

- **WHEN** 宿主自身因任何原因未加载插件(宿主侧加载失败按其设计 fail-soft,仅 WARN)
- **THEN** mgh 不在插件内自救;「守卫缺席 → PASS」的运行期 fail-soft 契约不变,守卫不在
  场的事实由 install 自检与实机验证闸门(双版本加载检查)在安装/验证期暴露,不靠运行期
  症状发现
