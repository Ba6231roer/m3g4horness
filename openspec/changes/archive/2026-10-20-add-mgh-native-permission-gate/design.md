## Context

现状与约束(动机见 proposal「Why」;上一 change `fix-mgh-opencode2-plugin-compat` 已归档):

- 插件已是 2.x 形态:default 导出 `{ id, setup }`,`setup` 内 `await ctx.tool.hook("execute.before",
  cb)` 注册工具面守卫管道,并已捕获 `ctx.location.directory` 为 `projectRoot`(逐调用注入
  payload `cwd`)。本 change 在同一 `setup` 内增注册 `permission.evaluate`。
- 2.x 权限层事实(本机 2.1.0 实测 + 源码):`permission.evaluate` 钩子在效果计算后、询问创建
  前触发,事件含 `{ sessionID, agent, action, resources, effect, message? }`,`effect`/`message`
  可变,原地改写生效;规则级 deny 在钩子前短路(改写 deny→allow 不可达);钩子对所有会话
  (含子代理)生效;询问本身无超时,无应答者即永久挂起。
- 哨兵契约:`.active` JSON 含 `{domain,target,out_roots[],read_roots[],v}`(read_roots 为绝
  对路径数组,sdr 声明经用户确认的外部仓);六个运行根
  `.mgh-init`/`security-scan`/`.mgh-sra`/`.mgh-srr`/`.mgh-ut-init`/`.mgh-sdr`。
- 版本矩阵:企业 2.0.32 + 本机 2.1.0;`permission.evaluate` 在两版的行为差异列入实机闸门。
- agent 定义现状:opencode 面 mgh agent 的 `permission:` map **没有任何 `question` 条目**
  (默认 agent 上 `question` 为 allow);fanout 孪生已有 `external_directory: deny`。

## Goals / Non-Goals

**Goals:**

- 运行域内任何权限询问在产生前被确定性关闭(pending 恒为零),模型收到可操作的替代提示后
  能继续收尾。
- 用户事先批准的只读外部根(read_roots)照常可用——外部仓工作流零回归。
- 域外(非 mgh 运行)行为零变化。
- 插件缺席时仍有一层规则级兜底(mgh 自带 agent 的 `question`/`external_directory` deny)。

**Non-Goals:**

- 不做常驻看门狗(对漏网 Form/MCP elicitation 的兜底是下一个 change)。
- 不改 Python 守卫(工具调用拦截语义零改动)。
- 不动 claude/dsh 面。
- 不处理 Form/MCP elicitation 与 provider-executed 工具(只披露)。
- 不做项目级 opencode 配置文件的自动写入(企业可选的手工配置样例只作文档说明,不进代码)。

## Decisions

### D1 闸门住在现有守卫插件里(同文件、同 setup、双钩子)

- **决策**:`block_adhoc_scripts.ts` 的 `setup` 内增 `await ctx.permission.hook("evaluate",
  cb)`;不另立插件文件。
- **理由**:同一运行域语义、同一哨兵发现、同一 install 面;两个文件会引入「闸门在而守卫不
  在」的组合态,自检与实机验证面翻倍。双钩子也强化单一安装单元的可解释性。
- **备选否决**:独立 `mgh_permission_gate.ts` 插件——被否(上述组合态);把闸门做进 Python
  守卫——被否(权限层改写必须同步发生在宿主进程内,spawn-per-evaluate 既慢又改变 fail-soft
  形状)。

### D2 运行域识别:项目根六运行根直查,不向上走链(比守卫窄,有意为之)

- **决策**:闸门只检查 `<projectRoot>/<六个运行根>/.active` 存在性;不做守卫那样的 16 级祖
  先上溯。
- **理由**:插件的位置(`ctx.location.directory`)就是 mgh 安装与运行的项目;祖先目录里的哨兵
  属于**别的**项目范围的运行,从本项目插件去改写那个项目的询问是越权且易误伤。窄激活的代
  价是「运行目录是项目根的严格子目录」的场景不被闸门覆盖——但 mgh 六域的运行根都钉在项目
  根(契约如此),该场景在工具族内不存在。
- **备选否决**:复刻守卫的向上走链——被否(越权面);env 激活(`MGH_*_ACTIVE`)——被否(2.x
  插件进程继承的是服务进程 env,会话中途导出不达;哨兵是唯一可靠信号,与既有结论一致)。

### D3 read_roots 放行例外:全资源归属才 allow,部分归属按 deny

- **决策**:`action === "external_directory"` 且 `effect === "ask"` 时,若**全部** resources
  都落在命中哨兵的 `read_roots[]` 内 → 改写 `allow`;否则(含部分在内)→ 按普通 ask 改写
  `deny`。
- **理由**:read_roots 的语义就是「用户已批准的只读根」(read-roots 配置流:声明 → 用户拍板
  → 写入);把已批准的询问留在 ask 等于保留挂死面,把未批准的放行等于绕过用户同意。全/无
  二值化避免「部分放行」这种没有用户同意基础的中间态。资源与根的归属判断做大小写与路径
  分隔符归一(资源面是正斜杠形如 `C:/a/b/*`,哨兵根是宿主原生形),纯前缀成员检查,属胶水。
- **备选否决**:ask 一律 deny 不做例外——被否(sdr 外部仓受控检索会从「询问」变「被拒」,
  外部仓工作流回归);ask 且在根内 → 保留 ask 等人——被否(无人值守即挂死)。

### D4 question 拒绝只对非 deny 效果改写,域内恒拒

- **决策**:运行域内 `action === "question"` 且 `effect !== "deny"` → 改写 `deny` + 「走批量
  澄清/断点续跑」提示。mgh 自带 agent 定义同时补规则级 `question: deny`(兜底层,插件缺席
  时仍生效;规则级 deny 短路在钩子前,两层不冲突)。
- **理由**:`question` 在默认 agent 上 allow——它不是「问权限」而是「向用户发问」,与工具族
  的无人值守纪律(批量澄清沉淀、断点续跑)相反。两层(规则 deny + 钩子改写)分别覆盖「插件
  在场」与「插件缺席」两种形态。
- **备选否决**:只做 agent 定义层——被否(用户会话/其它 agent 的 question 不经 mgh agent 定
  义,闸门要覆盖运行域内一切会话);只做钩子层——被否(插件拒载时兜底消失,违背分层)。

### D5 钩子内判定的「单一真相源」例外声明

- **决策**:闸门的三条改写规则(ask→deny / read_roots 全属→allow / question→deny)住在 TS,
  是对「判定单一来源在 Python」的一次**显式声明例外**:判定集合是固定枚举、无正则、无路径
  策略推理,规格逐条锚定并由 CI 形状断言覆盖;工具调用拦截的全部判定仍单一住在 Python 守卫。
- **理由**:权限层改写没有同步跨进程委托的形态(spawn-per-evaluate 不可接受);把「固定两条
  半规则」留在 TS 的风险(漂移)由 CI 形状锚 + 实机闸门压住。
- **备选否决**:TS 只读哨兵、经 Unix socket/文件让 Python 决策——被否(引入新 IPC 面与常
  驻进程,复杂度远超两条固定规则的价值)。

### D6 诊断与异常面:fail-closed 于询问、fail-open 于宿主

- **决策**:哨兵 JSON 解析失败按「无 read_roots」处理(ask→deny,fail-closed);钩子内任何
  异常捕获后按域外原样返回(NEVER 因闸门崩溃影响宿主权限判定),best-effort `console.warn`
  诊断。改写函数无状态、无缓存(哨兵 step 0 落盘后立即生效;stat+小 JSON 解析的成本相对
  「每次工具调用已 spawn 一个 Python 进程」可忽略)。
- **理由**:闸门自身的故障面不应大于它消除的故障面;fail-closed 只作用于「询问」(拒了可以走
  替代路径),fail-open 作用于「宿主权限机制」(坏了会伤一切会话)。

## Risks / Trade-offs

- [read_roots 归属判断的平台差异(大小写/分隔符/尾斜杠)] → 归一化函数带往返测试样例
  (Windows 反斜杠/正斜杠/大小写混合);实机闸门含一条真实外部仓资源样例。
- [2.0.32 与 2.1.0 的 evaluate 事件字段差异] → 双版本实机闸门;若字段名有差异,实现按「字段
  缺失即域外/原样返回」防御,差异记录进契约版本矩阵。
- [agent 定义补 `question: deny` 的面遗漏(33 个定义)] → 任务里用脚本化检查(源面断言:opencode
  面 agent 全含 `question:` 条目)而非逐个手改的口头约定。
- [用户误把闸门当「权限管理器」期待更细策略] → 契约与诚实边界明确:闸门只做「无人值守关询
  问」,不做按目录/按动作的授权策略;授权策略仍属 read-roots 配置流与宿主配置。
- [残余挂死面(Form/MCP/provider-executed/无断言自定义工具)] → 本 change 只披露;下一个
  change(看门狗)以 `reject + message` 兜底。

## Migration Plan

1. 实现插件闸门 + agent 定义兜底;本机 2.1.0 实机验证(pending=0 / 域外不变 / 外部根放行)。
2. 企业 2.0.32 复测(同套样例;由内网执行,参照实机闸门清单)。
3. 合入后随下一次 install 分发;无磁盘迁移(纯插件/agent 定义变更)。
4. 回滚:revert 插件与 agent 定义即可;哨兵与守卫零改动。

## Open Questions

- `question` 动作在 2.0.32 的默认效果是否与 2.1.0 一致(allow)——双版本闸门回答;若 2.0.32
  默认已是 deny,兜底层仍无害保留。
- `permission.evaluate` 事件的 `resources` 在 external_directory 上的通配尾缀形态(`/*`)在
  两版本是否一致——归一化实现按「剥尾缀后前缀匹配」防御,实测确认。
