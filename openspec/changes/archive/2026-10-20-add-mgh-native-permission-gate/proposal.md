> **人话序** 现象:工具族跑长任务时基本没人在旁边守着,而子代理一旦碰到需要「问用户一句」的
> 场景(读项目外的目录、读 .env、发起问询),宿主就会弹一个授权/问询框,没人应答它就一直
> 等——真实事故是挂到第二天早上用户回来才看到那个框,整个 run 白白停了一夜。根因:这类
> 「询问」在宿主侧没有超时,也没有「无人值守就别问」的开关;工具族此前只管「工具调用该不该
> 放行」,没有管「该不该问」。改什么:给 opencode 2.x 的守卫插件加一道权限闸门——在询问真
> 正产生之前就把「要问」改写成「拒绝并给出替代做法」,唯独用户事先批准过的外部只读目录放
> 行(那是用户已经点过头的);同时给工具族自带的子代理定义补上「禁止问询」。怎么验证:单测
> 锚住闸门规则与插件形状;实机复现原故障场景,确认询问数恒为零、模型收到拒绝文案后正常收
> 尾,域外(非 mgh 运行)行为零变化。

## Why

- opencode 2.x 的权限询问(`ask`)没有超时:`Permission.assert` 在等待回答的挂起上无界;
  无应答者(TUI 无人值守、纯服务形态会话)时工具纤程永久挂起——已实机复现(等待授权的
  pending 在 20 秒观察窗内无任何自动应答,源码无超时)。这是无人值守长跑的结构性挂死面。
- 工具族的守卫只覆盖「工具调用拦截」(`tool.execute.before`),不覆盖「权限层询问」:
  询问发生在权限层,守卫既看不到也拦不住;`question` 动作默认还是 allow,子代理可以直接
  向用户发问,无人应答同样挂死。
- 已实机验证 2.x 提供 `permission.evaluate` 钩子:它在询问创建**之前**触发,可把 `ask` 改
  写为 `deny`(改写后 pending 数为零,模型收到拒绝文案后正常收尾)——这是「永不弹问」的
  根治位置,而不是「弹了再自动拒绝」。
- 这是原生子代理派发路线的第二个前置:第一个前置(插件 2.x 迁移)已归档;没有这道闸门,
  任何无人值守原生派发都会在第一次越目录读或问询上挂死。

## What Changes

- **权限闸门钩子**:守卫插件(同一个文件、同一个 default 导出)在 `setup` 内增注册
  `permission.evaluate` 钩子(同样 await 注册)。规则(仅运行域内生效):
  ① `effect === "ask"` → 改写为 `deny` 并附一句「替代做法」提示,唯一例外是
  `external_directory` 且全部资源都落在当前运行域哨兵声明的 `read_roots[]` 之内——此时改写
  为 `allow`(来源是用户事先批准的只读根,不批准就该拒,不能留成 ask 挂死);
  ② `action === "question"`(任意非 deny 效果)→ 改写为 `deny` 并附「走批量澄清/续跑流程」
  提示;③ `deny` 效果不碰(钩子在规则级 deny 短路之后才触发,本就不可达);
  ④ 域外(项目内六个运行根都无 `.active` 哨兵)一律不动——日常工作零影响。
- **运行域识别(TS 侧,胶水)**:插件用 `setup` 已捕获的项目根,检查六个运行根
  (`.mgh-init`/`security-scan`/`.mgh-sra`/`.mgh-srr`/`.mgh-ut-init`/`.mgh-sdr`)下的
  `.active` 哨兵存在性;命中则读该哨兵 JSON 取 `read_roots[]`。不做向上走链(比守卫的
  16 级上溯窄——哨兵在祖先目录属于别的项目范围,见 design 决策)。哨兵 JSON 损坏按「无
  read_roots」处理(询问一律 deny,fail-closed)。
- **agent 定义兜底层**:opencode 面 mgh 自带 agent 定义补 `question: deny`(现状零覆盖,
  `question` 默认 allow);需要隔离外部目录的 agent 确保 `external_directory: deny` 在场
  (fanout 孪生已有,补遗漏)。规则级 deny 在权限层短路,插件缺席时这层仍生效。
- **诚实边界(预登记)**:`permission.evaluate` 管不到 Form/MCP elicitation(另一套问询
  机制)、管不到 provider-executed 工具(不过本地钩子)、管不到不做权限断言的自定义工具;
  这些残余挂死面由下一个 change(看门狗)兜底,本 change 只披露不处理。
- **非目标**:不做常驻看门狗;不做原生子代理派发;不动 Python 守卫(工具调用拦截语义零改
  动);不动 claude/dsh 两面(claude 面问询形态不同,dsh 面另行评估)。

## Capabilities

### New Capabilities

<!-- 无。 -->

### Modified Capabilities

- `runtime-hook-enforcement`: ①新增 requirement「运行域内权限询问闸门(opencode 2.x
  permission.evaluate)」——ask 改写规则、question 拒绝、read_roots 放行例外、域外零影响、
  CI 形状锚、残余边界披露;②MODIFIED「opencode 2.x 插件模块契约与形状自检」——钩子注册
  从单一 `tool.execute.before` 推广为「全部钩子(tool 与 permission 两面)均 await 注册」,
  CI 形状断言同步覆盖两面。

## Impact

- **代码**:`releases/opencode/plugins/block_adhoc_scripts.ts`(同一 setup 增注册
  permission.evaluate;工具面钩子与 Python 守卫零改动);`releases/opencode/agent/*.md`
  补 `question: deny` 兜底(及个别 `external_directory: deny` 补漏)。
- **契约**:`core/contracts/hooks/runtime-enforcement.md` 增权限闸门节(改写规则表、哨兵
  read_roots 例外、域外零影响、残余边界)。
- **测试**:`tests/test_opencode_hook_parity.py`(闸门源码形状断言:evaluate 钩子注册被
  await、ask→deny 改写、question 拒绝、read_roots 放行分支、六运行根哨兵检查在场);
  既有 `TestShimV2ModuleShape` 断言扩展到 permission 面;定向回归面同上一 change(hook 三
  端接线族)。
- **实机闸门**:本机 2.1.0 + 企业 2.0.32 双版本——原故障复现场景(越目录读触发 ask 的
  agent)在闸门下 pending 恒为零、会话正常收尾;域外项目 ask 行为不变(弹窗照常)。
- **VERSION/CHANGELOG**:按仓库惯例 bump。
