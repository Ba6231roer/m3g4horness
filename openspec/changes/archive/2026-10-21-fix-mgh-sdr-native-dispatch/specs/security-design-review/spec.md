## ADDED Requirements

### Requirement: 原生派发的波次纪律与无人值守闭环

当环境画像显式选择原生形态(`dispatch_mode: "native"`)时,`/mgh-sdr` 的 fan-out 步 SHALL 按
以下闭环执行,且本闭环 SHALL 满足「缺省零变化」:画像缺失/auto/runner 时现行子进程形态行为
逐字节不变,子进程形态永久保留为回退路径。

- **形态选择**:step 0 读环境画像;画像坏文件按既有 fail-closed 契约(退出码 2 + recipe)。
- **物化与自检**:每轮以 `emit_native_plan.py --tier sdr` 物化计划(任务文件 + 波次表 +
  短单元号)并跑 `--check`;波次尺寸用计划给定值(并发与配额算术的较小者)。
- **波次派发**:编排器**同一条 assistant 消息**并发发出当前波全部 N 个子代理调用——每调用
  `description` = 该单元短号、任务体 = 固定一句 + 该单元任务文件绝对路径(自计划逐字透
  述);SHALL NEVER 跨波合并、NEVER 自增并发、NEVER 自撰任务文本、NEVER 拼接或改写路径。
- **波次间重枚举**:每波收尾后重跑计划物化(pending 由磁盘标记重派生)取下一波;失败单元
  (`.failed` 在场)至多重派一轮,重派再失败 SHALL 接受缺口并在报告披露;上一波失败原因含
  限流特征时,SHALL 按画像配额窗口等待后再查询(等窗为纪律性指示,等待事实入 run 留痕)。
- **看门狗接线**:native 步 SHALL 以后台形态启动看门狗——根会话取宿主注入的会话环境变量、
  `--run-dir` 为当前 run 目录、阈值用缺省;run 落定后看门狗自退;编排器 NEVER 代替看门狗做
  会话中止。
- **标记真相源不变量**:`.done`/`.failed` 的唯一写者是子代理自身(成功 touch `.done`;失败
  自写 `.failed` 带原因——该指令仅存在于原生 agent 定义);计划物化、看门狗、编排器 SHALL
  NEVER 写任何单元标记;被中止/未落标记的单元经重枚举自然回待派。
- **报告与披露**:报告与 manifest SHALL 披露实际派发形态与计划工件在场证据;诚实边界 SHALL
  披露:止损为波次粒度(无进程树杀,挂死由看门狗中止兜底)、编排父会话是单点、任务文件路
  径经编排器转述存在残余错抄面(防线 = 越树即被守卫拦 + 错配单元经重枚举回待派 + 至多一轮
  重派的有界代价)。
- **三面分歧披露**:本原生形态当前仅 opencode 面;claude/dsh 面保留子进程形态,壳与规格
  SHALL 显式披露该分歧(属宿主机制差异),后续按宿主能力另行接入。

#### Scenario: 缺省零变化

- **WHEN** 项目无环境画像(或 dispatch_mode 为 auto/runner),`/mgh-sdr` 运行
- **THEN** fan-out 步走现行子进程形态,全部产物与行为与主分支一致——原生接入是纯选择加入,
  不引入任何缺省行为变化

#### Scenario: 同消息并发派发一波

- **WHEN** 原生形态当前波有 3 个待派单元
- **THEN** 编排器在一条 assistant 消息内发出 3 个子代理调用(description=短号,任务体=固定
  句+任务文件绝对路径),全部返回后进入波次间重枚举——不存在逐个串行派发或自撰任务文本

#### Scenario: 失败单元至多一轮重派

- **WHEN** 某单元 `.failed` 在场(原因非限流特征)
- **THEN** 重枚举将其列入至多一轮的重派;重派再失败后该单元进入缺口披露,后续波次不再派
  它——失败单元不会无限循环

#### Scenario: 挂死单元由看门狗收口回待派

- **WHEN** 原生形态下某子会话挂死(无标记产出),看门狗超阈值将其中止
- **THEN** 该单元因无标记在下次重枚举回到待派;全程无任何一方代写标记——中止 ≠ 失败终
  态,终态只能由单元自身执行纪律写出

#### Scenario: 报告披露派发形态

- **WHEN** 原生形态 run 渲染报告
- **THEN** 报告与 manifest 含派发形态披露与计划工件在场证据;诚实边界含波次粒度止损、父会
  话单点、路径转述残余三条——读者能区分「这次怎么派的」与「查了什么」

#### Scenario: 三面分歧可见

- **WHEN** 比对三面 mgh-sdr 壳的 fan-out 步
- **THEN** opencode 面含原生形态条件步,claude/dsh 面为子进程形态,且各面如实披露当前分歧
  ——不是静默的镜像断裂

## MODIFIED Requirements

### Requirement: fan-out 评审单元与 6 维度默认检查面

编排器 SHALL 按环境画像选择的派发形态执行 fan-out 评审,**评审本体(检查面、schema、纪律)
与形态无关**:

- **子进程形态(回退,现行)**:经 `fanout_runner.py --tier sdr` 波次派发:每个 pending 单元
  一个 subagent(`sdr-review-fanout` agent 定义;claude 侧经 `--agents` inline JSON,opencode
  侧 `mode: primary` 克隆),任务消息由固定模板 `core/prompts/fragments/fanout/sdr-task.md` +
  该单元 `pending[]` 字段逐字填充。
- **原生形态(opencode 面,画像显式 native 时)**:每个 pending 单元一个原生子代理
  (`sdr-review-native` agent 定义,`mode: subagent`),任务消息 = 该单元经计划物化产出的任
  务文件内容(同源模板逐字填充,编排器仅逐字转述文件);成功 touch `done_marker`、失败**自
  写** `failed_marker`(带原因;该指令仅存在于原生 agent 定义,子进程形态的模板行与派发器
  写标记行为零改动)。

两种形态下 subagent 均 SHALL **恰好读** `input_path`(slice 文件)、**恰好写** `draft_path`
(统一 JSON 问题记录),NEVER 读其他单元的 slice 或其他分支产物。默认检查维度 SHALL
为闭集 6 项:`vertical-authz`(垂直越权)、`horizontal-authz`(横向越权)、`other-authz`(其他
权限问题)、`sql-injection`(SQL 注入)、`sensitive-data`(敏感信息屏蔽)、`input-validation`(输入
校验);检查面 SHALL 经 `--dimensions <inline-json|@path>` 参数化收窄或扩展(闭集校验,维度键
闭集 + 扩展维度仅作自由文本检查项透传;非法键退出码 2 早停,任何 LLM token 之前)。每条问题
记录(draft `findings[]` 项)SHALL 统一 schema:`{dimension, severity(high|medium|low|info),
route, file, line_hint, line(int,问题锚定行,可选), risk(风险描述,写法见下方写作纪律),
suggestion(整改建议,写法见下方写作纪律), repro(可选,复现方式), fix_diff(可选,修复
前后代码对比), control_ref(命中的存量安全设计名或 null)}`。

**人类面字段写作纪律**(任务模板 SHALL 逐字承载,三面 agent 定义的 Output schema 行同步):
`risk`/`suggestion`/`repro`/`fix_diff` 是给人读的文本——读者画像见能力
`human-facing-output-discipline`(一两年 Java Web 经验的工程师,不懂本工具内部概念)。
写法上 SHALL:

- `risk` 第一句写现象:谁、从什么入口、传什么参数 → 发生什么;技术根因放后面。
- 问题能落到具体接口/方法调用时 SHALL 带 `repro`,写「怎么调 + 传什么 + 看到什么」
  (示例:以任一有效登录会话 POST /user/del 传他人 id → 他人记录被删除);设计缺失类
  构造不出具体调用的,可以省略。
- 改动只有一两处代码时 SHALL 带 `fix_diff`(1–2 组 `{before, after}`;`before` 从 slice
  里逐字摘原文,`after` 写改后的样子);改动更多或跨文件重构时省略,`suggestion` 文字
  说清楚即可。
- 禁用能力 `human-facing-output-discipline` 闭集里的内部词;越权、IDOR、SQL 注入、脱敏、
  白名单这类安全常用词是读者的工作语言,不受限。

`sensitive-data` 维度 SHALL 依编排器透传的敏感目录执行(见
「敏感目录复用与回退」要求);6 维度各自的判定锚点是**存量安全设计**(AGENTS.md 安全章节 +
`docs/security-controls/*.md` + 项目记忆),subagent task 消息 SHALL 逐字携带编排器从存量设计
投影出的**检查基线摘要**(确定性由 `sdr_context.py` 产出,≤ 预算字节),NEVER 要求 subagent 自行
读全部 rules 文件。

#### Scenario: 接口单元产出统一 schema 问题记录

- **WHEN** 某 `kind=interface` 单元(路由 `/user/detail`)的 slice 显示新增接口按入参 `brch_no`
  查询但调用链无 `UserContext.get()` 校验,而存量设计声明「横向越权须 brch_no + UserInfo 校验」
- **THEN** 该单元 draft 含一条 `{dimension:"horizontal-authz", severity:"high", route:"/user/detail",
  file:"UserController.java", risk:<未按存量设计校验的中文描述>, control_ref:<存量设计名>}` 的
  finding,且该 finding 可被渲染器与其他单元的去重合并

#### Scenario: 可复现问题携带复现方式

- **WHEN** slice 显示新增接口 `/user/del` 直接以请求参数 `id` 调用 DAO 删除(无归属校验)
- **THEN** 该 finding 带 `repro`,内容是「怎么调 + 传什么 + 看到什么」(如:以任一有效登录
  会话 POST `/user/del` 传他人 `id` → 他人记录被删除),不含闭集词

#### Scenario: 局部修复携带前后代码对比

- **WHEN** 某 finding 的整改点 = 在 DAO 查询单处追加数据归属条件
- **THEN** 该 finding 带 `fix_diff: [{before: <slice 内原查询原文>, after: <含归属条件的
  修改后形态>}]`;整改点超过 2 处或属跨文件重构的 finding 省略该字段

#### Scenario: 写作纪律进任务模板与 agent 定义

- **WHEN** 检查 `sdr-task.md` 任务模板与三面 agent 定义(opencode/claude `sdr-review-fanout`、
  dsh tier agent)的产物文件
- **THEN** 模板含写作纪律节和扩字段后的 draft schema 示例,输出字段的描述文字自身零闭集词,
  三面 agent 定义的 Output schema 行与之一致(确定性文档面,机器可对账);原生孪生
  `sdr-review-native` 的 Output schema 行与之一致,额外仅增失败标记自写指令

#### Scenario: 检查面参数化收窄

- **WHEN** 编排器传 `--dimensions '{"dimensions":["sql-injection","input-validation"]}'`
- **THEN** subagent 仅对这两个维度产出 findings(sensitive-data 目录不透传),其余维度不检查;
  manifest 记录实际检查面

#### Scenario: 非法维度键早停

- **WHEN** 编排器传 `--dimensions '{"dimensions":["crypto-audit"]}'`(非闭集且非自由文本扩展形态)
- **THEN** 编排器在任何 subagent spawn 之前以退出码 2 fail-loud,stderr 给出合法维度清单

#### Scenario: 原生形态产出同一 schema

- **WHEN** 原生形态某单元的 slice 显示同类越权缺失
- **THEN** 该单元 draft 的 findings 与子进程形态同一 schema、同一写作纪律、同一判定锚点(检
  查基线摘要同源)——换派发形态不换评审本体,报告可跨形态对照

#### Scenario: 原生失败标记自写

- **WHEN** 原生形态某单元执行失败(如 provider 错误后收尾)
- **THEN** 该子代理自写 `failed_marker`(内容含单元 id 与原因)并单行回执 `failed <原因>`;
  子进程形态不受影响(模板行与派发器写标记行为零改动)——两形态的失败终态语义等价、写者
  不同且各自单一
