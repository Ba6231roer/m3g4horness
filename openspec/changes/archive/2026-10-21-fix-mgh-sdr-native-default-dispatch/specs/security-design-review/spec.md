## MODIFIED Requirements

### Requirement: fan-out 评审单元与 6 维度默认检查面

编排器 SHALL 按环境画像解析的派发形态执行 fan-out 评审,**评审本体(检查面、schema、纪律)
与形态无关**:

- **子进程形态(显式回退)**:经 `fanout_runner.py --tier sdr` 波次派发:每个 pending 单元
  一个 subagent(`sdr-review-fanout` agent 定义;claude 侧经 `--agents` inline JSON,opencode
  侧 `mode: primary` 克隆),任务消息由固定模板 `core/prompts/fragments/fanout/sdr-task.md` +
  该单元 `pending[]` 字段逐字填充。该形态是 claude/dsh 安装面的缺省,也是 opencode 安装面在
  画像显式 `dispatch_mode:"runner"` 时的唯一回退路径。
- **原生形态(opencode 面,缺省)**:opencode 安装面在画像缺失或 `dispatch_mode:"auto"` 时
  SHALL 缺省启用原生形态,显式 `dispatch_mode:"native"` 同样启用。每个 pending 单元一个原生
  子代理(`sdr-review-native` agent 定义,`mode: subagent`),任务消息 = 该单元经计划物化产出
  的任务文件内容(同源模板逐字填充,编排器仅逐字转述文件);成功 touch `done_marker`、失败
  **自写** `failed_marker`(带原因;该指令仅存在于原生 agent 定义,子进程形态的模板行与派发
  器写标记行为零改动)。

缺省与覆盖的解析 SHALL 由环境画像的单一路径给出:**在 `/mgh-sdr` 这个消费者上**,opencode
安装面 = 原生,claude 与其它安装面 = 子进程;显式 `native`/`runner` 覆盖缺省;坏画像
fail-closed。该缺省 SHALL 只作用于 sdr 消费方,`/mgh-init` 等其它命令的缺省形态 SHALL 保持
不变。编排面 SHALL NOT 各自维护第二套「未写画像就按子进程」的判断。

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

### Requirement: 原生派发的波次纪律与无人值守闭环

fan-out 的解析形态为 native 时(opencode 安装面在画像缺失或 `auto` 时的缺省,或画像显式
`dispatch_mode:"native"`),`/mgh-sdr` 的 fan-out 步 SHALL 按以下闭环执行;显式
`dispatch_mode:"runner"` 回退到子进程形态,claude/dsh 安装面仍为子进程形态。

- **形态选择**:step 0 读环境画像并解析形态(`env_profile.py --consumer sdr`,宿主面取本
  安装面);画像坏文件按既有 fail-closed 契约(退出码 2 + recipe)。opencode 面解析为 native
  但缺原生资产时退出码 2 + 重装/显式 runner recipe,NEVER 静默回退子进程。
- **物化与自检**:每轮以 `emit_native_plan.py --tier sdr` 物化计划(任务文件 + 波次表 +
  短单元号)并跑 `--check`;波次尺寸用计划给定值(并发与配额算术的较小者)。
- **波次派发**:编排器**同一条 assistant 消息**并发发出当前波全部 N 个子代理调用——每调用
  `description` = 该单元短号、任务体 = 单行令牌 `mgh-dispatch: plan=<计划引用>
  unit=<短号>`(计划引用自物化 stdout、短号自计划逐字;派发插件的令牌展开钩子展开为任务
  文件全文;展开钩子缺席的旧版安装回退 = 固定句 + 任务文件绝对路径逐字透传);SHALL NEVER
  跨波合并、NEVER 自增并发、NEVER 自撰任务文本、NEVER 拼接或改写路径。
- **波次间重枚举**:每波收尾后重跑计划物化(pending 由磁盘标记重派生)取下一波;失败单元
  (`.failed` 在场)至多重派一轮,重派再失败 SHALL 接受缺口并在报告披露;上一波失败原因含
  限流特征时,SHALL 按画像配额窗口等待后再查询(等窗为纪律性指示,等待事实入 run 留痕)。
- **看门狗接线**:native 步 SHALL 以后台形态启动看门狗——根会话取宿主注入的会话环境变量、
  `--run-dir` 为当前 run 目录、阈值用缺省;run 落定后看门狗自退;编排器 NEVER 代替看门狗做
  会话中止。
- **标记真相源不变量**:`.done`/`.failed` 的唯一写者是子代理自身(成功 touch `.done`;失败
  自写 `.failed` 带原因——该指令仅存在于原生 agent 定义);计划物化、看门狗、编排器 SHALL
  NEVER 写任何单元标记;被中止/未落标记的单元经重枚举自然回待派。
- **报告与披露**:报告与 manifest SHALL 在「本次 run 的计划工件在场 ∧ 解析形态 native」时
  披露实际派发形态与计划工件在场证据(含 `source` = 画像显式选择或宿主缺省、`host_face`、
  `profile_exists`);诚实边界 SHALL 披露:止损为波次粒度(无进程树杀,挂死由看门狗中止兜底)、
  编排父会话是单点、任务文件路径经编排器转述存在残余错抄面(令牌形下模型输出零任务路径,
  残余面仅在展开钩子缺席的回退形态成立;防线 = 越树即被守卫拦 + 错配单元经重枚举回待派 +
  至多一轮重派的有界代价)。
- **三面分歧披露**:原生形态在 opencode 面为缺省、claude/dsh 面保留子进程形态;壳与规格
  SHALL 显式披露该分歧(属宿主机制差异),后续按宿主能力另行接入。

#### Scenario: 缺省零变化

- **WHEN** 项目无环境画像(或 `dispatch_mode` 为 `auto`),`/mgh-sdr` 在 opencode 安装面运行
- **THEN** fan-out 步走原生形态;同一项目在 claude/dsh 安装面(或显式 `runner` 画像)运行
  fan-out 步走子进程形态,行为与其改动前逐字节一致——缺省切换只作用于 opencode 面的 sdr

#### Scenario: 同消息并发派发一波

- **WHEN** 原生形态当前波有 3 个待派单元
- **THEN** 编排器在一条 assistant 消息内发出 3 个子代理调用(description=短号,任务体=单行
  令牌),展开钩子把令牌展开为各自任务文件全文,全部返回后进入波次间重枚举——不存在逐个
  串行派发、自撰任务文本或模型转述任务路径

#### Scenario: 失败单元至多一轮重派

- **WHEN** 某单元 `.failed` 在场(原因非限流特征)
- **THEN** 重枚举将其列入至多一轮的重派;重派再失败后该单元进入缺口披露,后续波次不再派
  它——失败单元不会无限循环

#### Scenario: 挂死单元由看门狗收口回待派

- **WHEN** 原生形态下某子会话挂死(无标记产出),看门狗超阈值将其中止
- **THEN** 该单元因无标记在下次重枚举回到待派;全程无任何一方代写标记——中止 ≠ 失败终
  态,终态只能由单元自身执行纪律写出

#### Scenario: 报告披露派发形态

- **WHEN** 某 run 产出了 `native_plan.json` 与报告,解析形态为 native(包括没有环境画像
  文件的 opencode 缺省 run)
- **THEN** 报告、manifest 与数据文件含派发形态披露(含来源:画像显式或宿主缺省)与计划
  工件在场证据;诚实边界含波次粒度止损、父会话单点、路径转述残余三条——读者能区分「这次
  怎么派的」与「查了什么」

#### Scenario: 三面分歧可见

- **WHEN** 比对三面 mgh-sdr 壳的 fan-out 步
- **THEN** opencode 面以原生形态为缺省并只保留显式 runner 回退指引,claude/dsh 面为子进程
  形态,且各面如实披露当前分歧——不是静默的镜像断裂

## ADDED Requirements

### Requirement: opencode 缺省原生派发的编排面一致性

opencode 安装面的 `/mgh-sdr` 编排面 SHALL 把缺省原生形态作为主路径,并保证各入口对派发形态
给出同一个答案:

- 命令壳 SHALL 在主流程中只展开原生派发步骤(看门狗 → 计划物化 → 同消息派子代理 → 重枚举
  → 渲染);子进程派发细则 SHALL 只在解析形态为 `runner` 时由步骤清单给出,命令壳的缺省流程
  SHALL NOT 把子进程派发写成主路径或回退默认。
- 步骤清单(`list_sdr_steps.py`)与恢复查询(`resume_sdr_state.py`)SHALL 使用环境画像解析后的
  形态,而不是只认原始 `dispatch_mode:"native"`;opencode 面缺省画像时 fanout 步 SHALL 给出
  原生 arc,恢复 `next_action` SHALL 给出原生动作,SHALL NOT 提示子进程派发。
- 报告渲染(`render_sdr_report.py`)SHALL 在「本次 run 的计划工件在场 ∧ 解析形态为 native」时
  披露原生派发,包括没有环境画像文件的 opencode 缺省 run。
- 首选零打断入口(`mgh_sdr_launch.py`)SHALL 按宿主与画像解析后的形态生成编排提示词:opencode
  缺省生成原生派发提示词,SHALL NOT 硬编码子进程派发调用;claude 宿主或显式 `runner` 时生成
  子进程回退提示词。
- 宿主面不支持原生(如 claude)且画像显式 `native` 时,launcher SHALL 在 spawn 宿主前以退出
  码 2 + recipe 拒绝,NEVER 静默按子进程运行。
- opencode 面解析为 native 但安装树缺 `sdr-review-native` agent 或原生波次纪律 fragment 时,
  编排面 SHALL 在进入 fan-out 前以退出码 2 + 重装 recipe 拒绝,NEVER 静默回退子进程。
- claude/dsh 安装面的命令壳、步骤输出与报告披露 SHALL 保持改动前的子进程主路径,不因
  opencode 的缺省变更而改变。

#### Scenario: opencode 无画像的步骤与恢复都指原生

- **WHEN** opencode 安装面的项目没有 `.mgh/env-profile.json`,执行
  `list_sdr_steps.py --step fanout` 或 `resume_sdr_state.py`
- **THEN** fanout 步的可执行入口是计划物化(`emit_native_plan.py`),顶层 `dispatch.form` 为
  `native`;恢复的 `next_action` 指向原生物化/派波次动作,不出现 `fanout_runner.py`

#### Scenario: opencode 无画像的 shell 不展示子进程主路径

- **WHEN** 检查 opencode 安装面的 `/mgh-sdr` 命令壳
- **THEN** 主流程与确定性调用清单只给出原生派发步骤;命令壳文本不把子进程派发写成缺省路径,
  只在解析形态为 `runner` 的说明里指向步骤清单给出的回退调用行

#### Scenario: launcher 缺省生成原生提示词

- **WHEN** 在 opencode 宿主上执行 `mgh_sdr_launch.py`(无 `--host claude`,项目无画像或画像为
  `auto`)
- **THEN** 生成的编排提示词第 3 步是原生派发(看门狗、计划物化、同消息派子代理、重枚举),
  提示词不含硬编码的 `fanout_runner.py` 调用;`--dry-run` 即可检查该提示词

#### Scenario: 宿主不支持显式 native 时 fail-closed

- **WHEN** 项目画像写着 `{"dispatch_mode":"native"}`,launcher 以 `--host claude` 启动
- **THEN** launcher 在 spawn 宿主前退出码 2,stderr 给出「原生形态仅 opencode 支持;改用
  `--host opencode` 或把画像改为 `runner`」的 recipe;NEVER 静默改为子进程运行

#### Scenario: 原生资产缺席时 fail-closed

- **WHEN** opencode 安装面解析为 native,但 `sdr-review-native` agent 或原生波次纪律 fragment
  不在安装树中(版本错配/部分拷贝)
- **THEN** 编排面在进入 fan-out 前退出码 2,stderr 给出重跑 `install.sh --opencode` 或显式
  `dispatch_mode:"runner"` 的 recipe;NEVER 静默回退子进程

#### Scenario: 显式 runner 三面一致回退

- **WHEN** opencode 安装面的项目画像写着 `{"dispatch_mode":"runner"}`
- **THEN** 命令壳、步骤清单、恢复查询与 launcher 提示词一致回到子进程派发回退路径;原生计划
  与看门狗不启用,回退路径的调用行与超时不变式保持改动前一致;特殊授权按下一要求的可选入口
  处理,不再预置凭证命令

#### Scenario: 缺省原生 run 的报告披露

- **WHEN** opencode 面缺省原生 run 产出了 `native_plan.json` 与报告,项目没有环境画像文件
- **THEN** 报告、`sdr_manifest.json` 与 `sdr_report_data.json` 如实披露 `dispatch.form = native`
  与计划工件在场证据;没有计划工件的 run 仍按「字段缺席 = 不适用」不披露

#### Scenario: claude/dsh 输出不变

- **WHEN** claude 或 dsh 安装面无画像执行 `/mgh-sdr` 的步骤查询与恢复查询
- **THEN** 输出仍是改动前的子进程形态(fanout 步 = 子进程派发、无 `dispatch` 字段),命令壳
  仍如实披露本面仅子进程形态

### Requirement: 特殊授权说明只作可选项目入口

`/mgh-sdr` 编排面 SHALL 把特殊授权说明当作**可选的、项目所有的手工入口**,而不是流程内置的
鉴权分支:

- 入口路径 SHALL 是 `<repo>/.mgh/special-auth.md`;步骤清单的 `special_auth` 字段 SHALL 报告
  `{present, path}`(存在时 `path` 为绝对路径)。
- 存在该文件时,命令壳、launcher 提示词与恢复输出 SHALL 只加一句「先 Read 该说明,按其鉴权
  说明执行」;不存在时 SHALL 零动作、零额外提示。
- sdr 流程的提示词、调用行与 `next_action` SHALL NOT 硬编码 `cred_source.json`、
  `mgh_credentials.py`、`--cred-file` 或 `credential_expired` 的凭证准备步骤。说明要求什么
  操作由说明自身表达,流程不替它预设命令。
- `install.sh` SHALL NOT 把维护者随包的 `mgh-special-auth.md` 复制进目标项目;目标里旧的
  安装树副本 SHALL 被删除并给出迁移提示。维护者私有源文件不在本要求范围内。
- `fanout_runner.py --cred-file` 与 `mgh_credentials.py` 可保留为手动/遗留能力,但 SHALL NOT
  被任何 sdr 流程引用;其派发行为与既有测试不受本要求影响。

#### Scenario: 项目级说明存在时只给一句入口

- **WHEN** `<repo>/.mgh/special-auth.md` 存在,执行 `list_sdr_steps.py`、`resume_sdr_state.py`
  或生成 launcher 提示词
- **THEN** `special_auth.present` 为 true 且 `path` 是该文件的绝对路径;shell/launcher/恢复
  输出只含「先 Read 该文件」的入口句,不含 `mgh_credentials.py`、`cred_source.json`、
  `--cred-file` 或 `credential_expired`

#### Scenario: 项目级说明缺席时零动作

- **WHEN** `<repo>/.mgh/special-auth.md` 不存在
- **THEN** `special_auth` 为 `{present: false, path: null}`;shell/launcher/恢复输出不出现
  特殊授权提示,通用流程与退出码不变

#### Scenario: install 不再注入失效说明

- **WHEN** 维护者仓库根部存在 `mgh-special-auth.md`(或目标里已有旧的
  `<dest>/mgh-core/mgh-special-auth.md`),执行安装
- **THEN** 该文件不会被复制进目标;旧的安装树副本被删除并打印迁移提示(改放到
  `<项目>/.mgh/special-auth.md`);通用安装输出与退出码不变

#### Scenario: 手动凭证能力仍可用但不进 sdr 流程

- **WHEN** 高级用户显式给子进程派发器传 `--cred-file <run>/cred.json`(例如非 opencode 宿主
  的自定义编排)
- **THEN** `fanout_runner.py` 仍按既有契约完成凭证注入与过期分类;该能力不出现在任何 sdr
  命令壳、launcher 提示词、步骤清单或恢复输出中
