## MODIFIED Requirements

> 说明:本 delta 里**未触及的段落逐字保留主规格原文**(原文是紧凑文风,可读化留给后续
> 专门的规格人化 change,避免本 change 承担语义漂移风险);本 change 新增或修改的段落
> 按仓库 SDD 可读规则书写。

### Requirement: fan-out 评审单元与 6 维度默认检查面

编排器 SHALL 经 `fanout_runner.py --tier sdr` 波次派发评审:每个 pending 单元一个 subagent
(`sdr-review-fanout` agent 定义;claude 侧经 `--agents` inline JSON,opencode 侧 `mode: primary`
克隆),任务消息由固定模板 `core/prompts/fragments/fanout/sdr-task.md` + 该单元 `pending[]` 字段
逐字填充。subagent SHALL **恰好读** `input_path`(slice 文件)、**恰好写** `draft_path`(统一
JSON 问题记录)+ touch `done_marker`,NEVER 读其他单元的 slice 或其他分支产物。默认检查维度 SHALL
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
  三面 agent 定义的 Output schema 行与之一致(确定性文档面,机器可对账)

#### Scenario: 检查面参数化收窄

- **WHEN** 编排器传 `--dimensions '{"dimensions":["sql-injection","input-validation"]}'`
- **THEN** subagent 仅对这两个维度产出 findings(sensitive-data 目录不透传),其余维度不检查;
  manifest 记录实际检查面

#### Scenario: 非法维度键早停

- **WHEN** 编排器传 `--dimensions '{"dimensions":["crypto-audit"]}'`(非闭集且非自由文本扩展形态)
- **THEN** 编排器在任何 subagent spawn 之前以退出码 2 fail-loud,stderr 给出合法维度清单

### Requirement: 统一问题记录汇总与确定性报告渲染

新增确定性叶脚本 `render_sdr_report.py`(标准库、退出码 0/1/2、`--check` 承 R5.9)SHALL 收
run 目录下全部 fan-out 单元 draft(`.done` 且 JSON 可解析者;`.failed` 单元以 stderr 汇总 +
manifest `failed_units[]` 计入,不阻断渲染),按 `{dimension, route, file}` 三元组去重合并,
渲染 `<repo>/<工具名>-<分支名>-<YYYYMMDD_HHMMSS>.html`(工具名固定 `mgh-sdr`;分支名取文件系统
安全命名;时间戳到秒、本地时区)。报告 SHALL 为**自包含单文件 HTML**:样式、脚本、数据全部
内嵌,SHALL NOT 引用任何外部资源(网络 URL 的脚本/样式/字体/数据、CDN、外链图片一概不产),
file:// 双击用任意现代浏览器打开即可阅读,不依赖联网与任何已安装工具。报告 SHALL 为简体中文、
面向人读,结构:

- **头部**(分支/base/时间/检查面/敏感目录来源/外部仓结论摘要 + 分组概览):分组概览 SHALL
  满足本需求「报告确定性文案措辞」段和能力 `human-facing-output-discipline` 的出口守卫
  要求;
- **章节一「简报表」**(本需求的核心结构):HTML 表格,**行 = 评审单元**(排序:interface 按
  route 升序、standalone 殿后按 unit_id;多路由单元按首路由参与排序),列 = 接口/方法入口、
  调用链、是否前端接口、前端使用次数、6 维度各一列(默认闭集维度;自由扩展维度各追加一列)。
  各列 SHALL 满足:入口列 = route 串(standalone 或无路由 = 该独立方法定义 `fqn_short`);
  调用链列 = 缩写链文本(按 grouping.json `units[].chain[]` 确定性渲染:仅保留类名/文件
  名:方法名,如 `OrderController.submit → OrderServiceImpl.submit`,真仓试用后由「包段
  首字母 + 类名」形态收敛,完整包路径可由 file 列还原,`·` 同类延续、`⤷` 分支(`branch_of` 宿主)、`⇢` mapper XML 终端、
  `†` 未变更节点;`chain[]` 为空(standalone/codegraph off)= 该单元方法定义短形;入口
  = 方法定义时链写到分析可达处);**入口列与调用链列的每个「类名.方法名」短形 SHALL 渲染为
  指向仓内源文件的链接**(见本需求「源文件链接渲染」段);前端两列 = 按 route join
  context.json `external_repos[].route_hits[]`(声明 ∧ 命中 >0 = `是`+`N 处`;声明 ∧ 0 命中 =
  `否`+`—`;无声明/不可达 = `未知`+`—`;多路由单元仅按主路由(分号串第一段)join,次路由命中
  不抬升主路由状态);维度列 = `否` 或 `是 [P-NN]`(该单元该维度的合并 findings 编号列表,
  **P-NN SHALL 为页内锚点链接**,点击跳转到章节二对应条目——HTML 形态下页内跳转由本报告
  自身保证,SHALL NOT 依赖任何外部工具;原 MD 形态下「SHALL NOT 产出内部锚点」的禁令
  系目标编辑器不支持所致,随报告形态切换一并废止;本约束 SHALL NOT 及于指向仓内源文件的
  链接,后者是本需求的交付内容);
- **章节二「问题详述」**:合并去重后的每条 finding 一小节,统一 `P-NN` 编号(全局递增,
  条目锚点 = 其页内跳转目标),标题形态 `P-01 · <维度中文标签> · <route 或独立方法> ·
  <severity 中文>`;正文含位置(`file:line`——line 取 draft 新增 `line` 字段(问题锚定行号,
  数值);draft 缺 `line` 时降级为 `file`(不硬失败,旧 draft 兼容);位置文本 SHALL 渲染为
  指向该源文件的链接(见「源文件链接渲染」段))、风险、建议、control_ref,以及两项可选
  展示——**复现方式**(draft 带 `repro` 就渲染一行「复现方式」;没有就省略,不报错)与
  **修复对比**(draft 带 `fix_diff` 就按 1–2 组「修改前/修改后」代码块渲染:等宽字体、
  上下堆叠、代码文本走 textContent 注入路线;没有就省略,不报错);排序 severity
  升序(高→提示)、同 severity 按 P-NN;
- **章节三「分支调用链图」**:仅含带真实分支(`chain[]` 存在 **非 external** 节点携带
  `branch_of`——即 java 调用扇出;mapper 终端节点按编码也带 `branch_of`,但不构成真实
  分支)的单元,每单元一张**内嵌 SVG 有向图**(渲染器按 `chain[]` 确定性生成分层布局:
  入口 → 逐节点 → mapper 终端虚线边;`⤷` 分支、`⇢` 终端、`†` 未变更节点语义全部保留),
  SHALL 支持缩放与平移(页内交互),SHALL NOT 依赖任何外部图形库;线性链单元(含仅 ⇢ 终端
  带 `branch_of` 的直连 dao 短链)SHALL NOT 入本节;SVG 节点 SHALL NOT 承载源文件超链接
  (源文件跳转统一由章节一表格与章节二承担,图形节点仅悬停提示 `file:line`);
- **「无问题单元」清单**(保留,供 merge 前放行参考)+ **诚实边界节**(≥7 条,含排除集披露,
  保留现行)。

**报告确定性文案措辞**:报告里全部由渲染器**确定性产出**的文案——头部分组概览、诚实边界
条目、排除/失败/截断披露、章节标题、表头、图例——SHALL 用校准读者(一两年 Java Web 开发
经验的工程师,见能力 `human-facing-output-discipline`)能顺读的平实简体中文书写,SHALL NOT
携带分组算法/流水线的实现词汇。禁用闭集 = 能力 `human-facing-output-discipline` 的核心
词表 + sdr 域补充词表(路由锚、向上锚定、锚定单元、目录聚簇、判不穿、残余归并、链合并、
检查面,及概览分类语境的 interface / standalone)。闭集词的概念要用
读者的话转述(词表每个词条都带公认的人话替身,如「向上锚定」→「改动挂接到未变更的接口」);分组诊断的数字(调用边数等)
SHALL 保留在数据文件里,报告默认视图可以收进默认折叠的「分组诊断」明细——信息不丢,
默认视图不闹。诚实边界 ①–⑦ 条的**语义逐条保留**,措辞按本段转述。

**读者模拟评审与文本束**(拦模型临场新造的难懂词,机制见能力 `human-facing-output-discipline`
的「读者模拟评审」要求):渲染 SHALL 同步写出 `<run-dir>/readability_text_bundle.json`——
合并后全部人类面文本字段(P-NN + risk/suggestion/repro/fix_diff 文本)的单一文本束,它是
读者模拟评审的唯一输入。编排器 SHALL 在首次渲染后派发**一次**有界评审 subagent(任务模板
`core/prompts/fragments/fanout/readability-review.md`:读文本束 → 写
`<run-dir>/readability_advisories.json` → 回传单行有界 ack),然后**重渲染**(渲染幂等、原子
覆盖):建议文件存在且可解析 → 数据文件增可选 `readability[]` 字段、报告增设默认折叠的
「可读性自检」小节 + stderr 报一条计数;缺席或不可解析 → 小节与字段省略 + stderr note。
评审是尽力而为:未派发、失败、空产出都不阻断流程、不改退出码、不影响 resume 收尾;
评审 SHALL NOT 改写任何产物正文;建议词经维护者确认后进闭集(「发现 → 沉淀」增长闭环)。

**源文件链接渲染**(渲染规则,报告写在目标仓根目录 ⇒ 链接目标 = 源文件相对仓根的相对路径):

- 链接形态 `<a href="<相对路径>#L<line>">显示文本</a>`;`line` 缺失或为 `null` 时 SHALL
  退化为 `<a href="<相对路径>">显示文本</a>`(不带锚点)。
- 路径解析:chain 节点 `file` 与 finding `file` 为相对路径(相对 `--repo`)时直接作链接
  目标(输出统一 `/` 分隔);为绝对路径时,resolve 后在 `--repo` 子树内 → 转为相对路径,
  在子树外 → **不产链接**(降级纯文本,报告里没有指向仓外的死链);字段缺失/空 → 纯文本。
  路径解析 SHALL NOT 依赖文件真实存在(diff 分支的源文件可能未检出到工作树;链接坏与否由
  浏览器呈现,渲染器只做词法判定,NEVER 因此 stat 目标文件)。
- 显示文本 = 现行短形(`fqn_short` 等,含 `†` 前缀)逐字不变;`·`/`⤷`/`⇢`/`→` 分隔符不
  入链接;mapper XML 终端(`change=external`)与普通节点同等对待(有 `file` 即链)。
- 显示文本与属性值含 HTML 敏感字符(`<`/`>`/`&`/`"` 等)时 SHALL 做实体转义,NEVER 产出
  语法破损的标记;数据面(数据文件/manifest)SHALL NOT 因此引入任何 HTML 标记。
- `sdr_manifest.json` `rows[]` 与数据文件 `rows[]` 的 `entry`/`chain` 字段 SHALL 保持
  **纯文本短形**(不含任何链接语法/HTML 标记)——两者是机器消费面;表格链接是同一数据
  的渲染投影。

**数据文件**:渲染 SHALL 同步写出 `<run-dir>/sdr_report_data.json`,承载报告全量结构化
数据(单元行 `rows[]`、合并去重后的 `findings[]`(含 P-NN/维度/severity/位置/风险/建议/
control_ref,以及可选的复现方式 `repro`、修复对比 `fix_diff`)、分支调用链图数据、诚实边界
条目、头部元信息,以及可选的 `readability[]` 建议清单——「可读性自检」小节的数据源),
HTML 内嵌**同一份数据**(JSON 等价一致)——人读 HTML 与机器读 JSON 同源;下游确定性消费
(如未来 /mgh-blst、报告后处理工具)SHALL 以数据文件为接口,新字段按「字段缺席 = 不适用」
消费。`--check` SHALL 校验:数据文件存在且可解析、与 HTML 内嵌数据一致、manifest 计数与
draft 实际一致;另 SHALL 对模型文本字段(`risk`/`suggestion`/`repro`/`fix_diff` 的说明文本)
做闭集扫描(闭集取值 import 能力 `human-facing-output-discipline` 的单源模块)——命中只在
stderr 打计数告警(字段名 + 词),SHALL NOT 改变退出码:模型措辞是软质量,不能因为它卡死
跑完的长流程;确定性文案的闭集合规由回归测试保障,不入 `--check` 面。

同名报告文件已存在 SHALL 原子覆盖(时间戳到秒内重跑)。`sdr_manifest.json` `rows[]`
(`{unit_id, entry, chain, frontend_is, frontend_count, issue_refs[]}`;issue_refs = 该单元
各维度问题编号的展平列表)语义不变;`counts` 语义不变;其余字段保留现行(`excluded_files`
透传等)。draft 问题记录 schema 增可选 `repro`/`fix_diff` 字段(`line` int 可选保留;
本 change 之前的旧 draft 没有这些字段 = 章节二省略对应展示,渲染不失败;任务模板与
agent 定义双端同步披露)。

诚实边界 SHALL 至少含 7 条(现行 7 条语义保留):① 发现是 LLM 候选需人工复核,非确认漏洞;
② 接口分组是启发式,漏分组接口退入独立单元(分析粒度粗但覆盖不丢);③ 引用存量控制断言存在、
不断言有效;④ 外部仓结论是检索时点快照(不保证前端分支已同步);⑤ 基线经字节预算投影,低优先
级细节可能未全量投影;⑥ 敏感目录来源与覆盖范围(目录外字段仅按回退规则识别);⑦ 排除集披露。
各条措辞 SHALL 满足「报告确定性文案措辞」段。
渲染器 NEVER 写 `openspec/`、NEVER 写 run 目录、数据文件与报告文件之外的目标仓文件;历史
`.md` 报告 SHALL NOT 被回写或迁移。

#### Scenario: 分组概览与诚实边界的平实措辞

- **WHEN** 渲染一个 codegraph=on 的 run(分组统计含 `anchors_changed=4`、`anchors_upstream=2`)
- **THEN** 头部分组概览输出平实中文(如「按变更接口归组 4 条调用链、2 处改动挂接到未变更
  接口」形态),全文确定性文案不含禁用闭集词(「路由锚」「向上锚定」等);诊断数字可在
  默认折叠的明细中保留,数据文件字段不变

#### Scenario: 复现方式与修复对比的渲染

- **WHEN** 某 `.done` draft 的 finding 带 `repro:"以任一有效会话 POST /user/del 传他人 id
  → 他人记录被删除"` 和 `fix_diff:[{before:"deleteById(id)",after:"deleteByIdAndOwner(id,
  currentUserId)"}]`
- **THEN** 章节二该 P-NN 条目渲染「复现方式」文本行和一组「修改前/修改后」代码块(等宽、
  逐字注入、无 HTML 语法破损),数据文件 `findings[]` 对应项带这两字段

#### Scenario: 旧 draft 无新字段省略

- **WHEN** 某 `.done` draft 的 finding 没有 `repro`/`fix_diff` 字段(本 change 之前产出的
  旧 draft)
- **THEN** 章节二该条目不出现「复现方式」行和修复对比块,渲染不失败,`--check` 不视为
  不一致

#### Scenario: --check 禁词扫描只告警

- **WHEN** 某 draft 的 `risk` 文本包含「基线投影」(闭集词)
- **THEN** `render_sdr_report.py --check` 对该 run 的退出码与没有该词时相同,stderr 带至少
  一条计数告警(字段名 + 词)

#### Scenario: 文本束与可读性自检小节

- **WHEN** 某 run 9 份 draft 合并渲染,编排器随后派发读者模拟评审、建议文件落盘,再重渲染
- **THEN** 首次渲染就产出 `readability_text_bundle.json`(每条 P-NN 的人类面文本);重渲染
  后数据文件带 `readability[]` 字段、报告含默认折叠的「可读性自检」小节,正文其余内容与
  退出码不变,`--check` 的数据等价校验通过

#### Scenario: 评审缺席报告仍完整

- **WHEN** 读者模拟评审未派发或建议文件不可解析
- **THEN** 数据文件与报告都没有 `readability` 字段/小节,渲染退出码不变;resume 把该 run
  收尾为完成(评审缺席不是失败)

#### Scenario: 简报表行覆盖全单元形态

- **WHEN** 某 run 产 4 个 interface 单元(其一为多路由合并单元)、3 个 standalone 单元、其中
  2 个 interface 单元的 `chain[]` 带**非 external** 节点的 `branch_of`(真实分支)
- **THEN** 章节一表格 7 数据行(排序:interface 按 route 升序、standalone 殿后);interface 行
  调用链列为缩写链(含 `⤷`/`⇢`/`†`),standalone 行为方法定义短形;带分支的 2 单元在章节三
  各有一张内嵌 SVG,线性单元不出现;全部维度列为 `否` 或可点击的 `是 [P-NN]` 页内锚点链接

#### Scenario: 前端两列三态

- **WHEN** context.json 声明外部仓且 `/order/submit` 命中 2 处、`/cache/user/direct` 0 处,
  另一路由所在 run 未声明外部仓
- **THEN** `/order/submit` 行前端两列 = `是`+`2 处`;`/cache/user/direct` 行 = `否`+`—`;
  未声明仓的 run 其全部行 = `未知`+`—`

#### Scenario: 无锚点纯文本编号引用

- **WHEN** 渲染任意带 findings 的报告
- **THEN** `P-NN` 编号全局唯一且章节二可按编号定位;简报表格维度列的 `P-NN` 为**页内锚点
  链接**,点击在浏览器内跳转到章节二对应条目(页内跳转零外部依赖;原 MD 形态的内部锚点
  禁令随报告形态切换废止);数据文件与 manifest 的 `issue_refs[]` 仍为纯文本编号(不含
  链接语法)

#### Scenario: 链节点渲染为源文件链接

- **WHEN** 某单元 `chain[]` 含节点 `{fqn_short: "OrderController.submit", file:
  "src/main/java/com/x/controller/OrderController.java", line: 42}` 与节点 `{fqn_short:
  "OrderMapper.insertOrder", file: "src/main/java/com/x/mapper/OrderMapper.java", line: null}`
- **THEN** 调用链列依次渲染 `href="src/main/java/com/x/controller/OrderController.java#L42"`
  与 `href="src/main/java/com/x/mapper/OrderMapper.java"`(无锚点退化)的链接,显示文本为
  短形;分隔符不入链接,链的阅读顺序与短形文本不变

#### Scenario: 仓外与异常路径降级纯文本

- **WHEN** 某 finding 的 `file` 为仓外绝对路径,另一 chain 节点 `file` 为空串
- **THEN** 前者位置、后者链节点均保持纯文本形态(无 `<a>`),报告不含仓外路径链接;渲染退出码
  0,`--check` 不报不一致

#### Scenario: manifest rows 保持纯文本

- **WHEN** 渲染完成产数据文件与 manifest,HTML 表格调用链列含源文件链接
- **THEN** `sdr_manifest.json` 与 `sdr_report_data.json` 对应行 `chain`/`entry` 字段均为
  纯文本短形(不含 `<a>`/`href` 等任何链接语法/HTML 标记),与「去链接化后的表格单元格
  文本」一致

#### Scenario: 报告文件名与内容可追溯

- **WHEN** 对分支 `feature-pay` 于 2026-09-03 14:30:22 完成评审
- **THEN** 项目根出现 `mgh-sdr-feature_pay-20260903_143022.html`,头部含 branch/base/时间戳,
  章节一每行可溯源到 unit_id,章节二每条可溯源到 file:line(或 file)

#### Scenario: draft 缺 line 字段降级

- **WHEN** 某 `.done` draft 的 finding 无 `line` 字段(旧格式 draft)
- **THEN** 章节二该条位置写 `file`(无行号),有链接时渲染为不带 `#L` 锚点的文件链接,
  渲染不失败,`--check` 不视为不一致

#### Scenario: 部分单元 failed 不阻断渲染

- **WHEN** 10 个单元 9 个 `.done`、1 个 `.failed`
- **THEN** 渲染器汇总 9 份 draft 出报告,manifest `counts.failed_units = 1` + `failed_units[]`
  列出该单元 id 与 reason,报告诚实边界披露「1 个评审单元失败,该单元覆盖范围未复核」;失败
  单元不出现在章节一表格行(其覆盖未复核),仅在诚实边界披露

#### Scenario: 重复 finding 跨单元去重

- **WHEN** 同一接口路由的两个 hunk 被拆入同组或相邻单元,各产一条 `{dimension,route,file}` 相同
  的 finding
- **THEN** 渲染器按三元组去重合并为一条(line_hint 取并集),章节二仅一条 P-NN,引用它的
  单元行维度列共享该编号

#### Scenario: manifest rows 投影与表格一致

- **WHEN** 渲染完成产数据文件与 manifest
- **THEN** `sdr_report_data.json` `rows[]` 与 `sdr_manifest.json` `rows[]` 逐行一致,长度 =
  章节一表格数据行数,`unit_id`/`entry`/`chain`/`frontend_is`/`frontend_count` 与表格单元格
  一致(链接按「去链接化后的短形文本」比对);`issue_refs[]` 展平该行全部问题编号

#### Scenario: 报告披露排除集与分组统计

- **WHEN** 本次 run 排除了 120 个文件(测试 80/构建产物 30/静态资源 10)且 codegraph 捕获
  25 条变更集内调用边、向上锚定 8 条链
- **THEN** 报告诚实边界含排除计数与分类,manifest `counts.excluded_files == 120`;分组统计
  在报告头部「分组概览」以平实措辞可见(满足「报告确定性文案措辞」段;明细数字可收纳于
  默认折叠的「分组诊断」),供操作者判断分组质量

#### Scenario: 报告离线自包含

- **WHEN** 渲染任意报告并在文本层面检查产物
- **THEN** HTML 内不含任何 `http://`/`https://` 的脚本、样式、字体、数据引用(外链图片同为
  零),样式与脚本全部内嵌,数据存在于内嵌数据块;断网环境下 file:// 打开全部章节可读、
  章节三图形可见

#### Scenario: 数据文件与内嵌数据一致且 --check 可校验

- **WHEN** 渲染完成,随后对同一 run 目录跑 `--check`
- **THEN** `<run-dir>/sdr_report_data.json` 存在、可解析,且与 HTML 内嵌数据块 JSON 等价
  (同数据两种载体);`--check` 退出码 0;人为破坏数据文件或内嵌块之一后 `--check` 退出码 2

#### Scenario: 章节三 SVG 零外部依赖且语义保留

- **WHEN** 某 branched 单元 `chain[]` 含一个 `branch_of` 分支宿主、一个 mapper 终端节点
  (`change=external`)与一个未变更节点(`†`)
- **THEN** 该单元章节三为内嵌 `<svg>`(非 mermaid 代码块、非 canvas、不加载任何图形库),
  mapper 终端边为虚线样式,未变更节点带 `†` 前缀,分支拓扑与 `chain[]` 一致;图形可缩放平移

#### Scenario: 视图筛选不回写数据

- **WHEN** 读者在章节一按 severity 或单维度筛选表格行
- **THEN** 仅不匹配行被隐藏(纯视图态),`sdr_report_data.json` 与 `sdr_manifest.json` 的
  `rows[]` 不因此变化;重新打开报告后全部行恢复
