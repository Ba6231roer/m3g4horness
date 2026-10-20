## MODIFIED Requirements

### Requirement: fan-out 评审单元与 6 维度默认检查面

编排器 SHALL 经 `fanout_runner.py --tier sdr` 波次派发评审:每个 pending 单元一个 subagent
(`sdr-review-fanout` agent 定义;claude 侧经 `--agents` inline JSON,opencode 侧 `mode: primary`
克隆),任务消息由固定模板 `core/prompts/fragments/fanout/sdr-task.md` + 该单元 `pending[]` 字段
逐字填充。subagent SHALL **恰好读** `input_path`(slice 文件)、**恰好写** `draft_path`(统一
JSON 问题记录)+ touch `done_marker`,NEVER 读其他单元的 slice 或其他分支产物。默认检查维度 SHALL
为闭集 6 项:`vertical-authz`(垂直越权)、`horizontal-authz`(横向越权)、`other-authz`(其他
权限问题)、`sql-injection`(SQL 注入)、`sensitive-data`(敏感信息屏蔽)、`input-validation`(
输入校验);检查面 SHALL 经 `--dimensions <inline-json|@path>` 参数化收窄或扩展(闭集校验,维度键
闭集 + 扩展维度仅作自由文本检查项透传;非法键退出码 2 早停,任何 LLM token 之前)。每条问题
记录(draft `findings[]` 项)SHALL 统一 schema:`{dimension, severity(high|medium|low|info),
route, file, line_hint, line(int,问题锚定行,可选), risk(风险描述,写法见下方写作纪律),
suggestion(整改建议,写法见下方写作纪律), repro(可选,复现方式), fix_diff(可选,修复
前后代码对比), control_ref(命中的存量安全设计名或 null)}`。

**单遍往返纪律(调用次数收敛)**:任务模板 SHALL 逐字承载一段任务措辞,要求 subagent 把
**全部输入**(slice + 基线投影 + 敏感目录文件〔存在时〕 + 外部结论〔存在时〕)在**第一批
工具调用里并行读入**,随后一次性完成全部 6 维判断,再把「写 draft + touch done_marker」合为
同批写出,最后回单行 ack;措辞 SHALL 明示 NEVER 逐文件多轮往返读入、NEVER 分批多次写出
(调用次数限流网关下,每个评审单元的模型调用数是硬成本,往返翻倍 = 配额翻倍)。三面
`sdr-review-fanout` agent 定义(opencode/claude agent 定义与 dsh tier agent)SHALL 含与该措辞
一致的单行指针。**诚实边界**:该纪律是提示词级约束——降低但不保证每单元调用数,真实调用数
只能网关侧度量;本纪律 NEVER 改变读/写的路径闭集与刚性三元组语义(读哪些文件、写哪个
draft、touch 哪个 marker 的既有边界逐字不变,只约束往返次数)。

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

**壳派发行串行与配额指引(调用次数限流网关的缺省姿态)**:`mgh-sdr` 命令壳三面镜像
(opencode / claude / dsh)编排流的 sdr 派发规范行 SHALL 默认带 `--wave 1`——规范行的载体
为壳内联**或**运行时步骤清单 `list_sdr_steps.py --step fanout` 的 invocation(两者并存时
SHALL 逐字一致);launcher(`mgh_sdr_launch.py`)的 resume 指引行同形同步;参数表与
`--help` 文案 SHALL 注明「调用次数限流的内网网关建议并发 1~2」与配额三 flag(`--quota-calls`/
`--quota-window-s`/`--quota-calls-per-unit`)的用法示例。`--wave` 的脚本级默认值不在本
requirement 的约束面内(见 `fanout-dispatch` 能力);本条只约束 sdr 壳呈现给编排器的规范调用
形态。壳 token 预算 SHALL 维持既有上限(dsh 面 5000 token 硬顶),新增指引的余量优先经
「步骤级调用行与 recipe 下沉步骤清单 stdout / 脚本 `--help`」取得(工具输出可被宿主压缩
清理,壳常驻不膨胀——与 `mgh-init` 壳的既有瘦身机制同构),删并冗余措辞仅作兜底。

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

#### Scenario: 单遍往返纪律进任务模板与三面 agent 定义

- **WHEN** 检查 `sdr-task.md` 任务模板与三面 agent 定义(opencode/claude `sdr-review-fanout`、
  dsh tier agent)的产物文件
- **THEN** 模板含「全部输入第一批并行读入 → 一次判断 → 写 draft 与 touch marker 同批 →
  单行 ack」的单遍措辞,且明示 NEVER 逐文件多轮往返;三面 agent 定义各含与之一致的单行
  指针(确定性文档面,机器可对账);读/写路径闭集与刚性三元组的既有措辞逐字保留

#### Scenario: 壳派发规范行默认串行并给配额指引

- **WHEN** 审阅三面 `mgh-sdr` 壳的 sdr 派发规范行(含其载体 `list_sdr_steps.py --step fanout`
  的 invocation,并存时两者逐字一致)与 `mgh_sdr_launch.py` 的 resume 指引行、参数表
- **THEN** 规范行默认带 `--wave 1`;参数表注明内网建议并发 1~2 与配额三 flag 用法示例;
  三面镜像逐字一致(dsh 面路径根为 `mgh-core/`);壳 token 预算 lint 通过(余量经步骤清单/
  `--help` 外包取得,dsh 面显著低于既有 4997 水位而非贴顶硬凑)

#### Scenario: 检查面参数化收窄

- **WHEN** 编排器传 `--dimensions '{"dimensions":["sql-injection","input-validation"]}'`
- **THEN** subagent 仅对这两个维度产出 findings(sensitive-data 目录不透传),其余维度不检查;
  manifest 记录实际检查面

#### Scenario: 非法维度键早停

- **WHEN** 编排器传 `--dimensions '{"dimensions":["crypto-audit"]}'`(非闭集且非自由文本扩展形态)
- **THEN** 编排器在任何 subagent spawn 之前以退出码 2 fail-loud,stderr 给出合法维度清单

### Requirement: 切片物化的字节闸门与超预算三级处置

`diff_group.py` 的字节预算 SHALL 以**物化出去的切片文件的实际字节数**为判据,而非打包期的估算量。测量
SHALL 复用与物化同一个渲染逻辑(单一真相源),**NEVER** 并行维护第二套尺寸估算;测量值 SHALL 为渲染文本
的 utf-8 编码字节数。打包期的成员大小(standalone 目录簇归并、interface 成分贪心打包)SHALL 一律改用该
实测值判定,既有「路由序排序确定性」与「**不切文件中部**」两条规则不变。

实测超预算时,处置 SHALL 按以下固定顺序进行,前者可解则不进下一级:

1. **无损重切**:单元含多个文件且实测超预算 → 按既有贪心打包规则再切为续单元(`unit_id` 沿用既有
   `-partN` 形态命名,`chain[]` 随每一份续单元携带,与既有规则一致),每份续单元实测 ≤ 其适用上限。
   本级的 `SHALL NOT` 丢失任何 hunk、`SHALL NOT` 截断任何内容——单元数增加是唯一代价。
2. **上下文瘦身**:仅当单元**已不可再切**(单文件原子残渣)且仍超预算时,SHALL 对该单元的描述性上下文块
   按确定性上限截断(字符串与列表两种形态均须处理)。**证据锚点 MUST NOT 被截断**——diff 正文、文件
   清单、hunk 定位头(`@@ <path> @@ new-file lines N+C`)、以及被下游校验器检查的字段全部保留。截断
   MUST 在切片文件内以可见标记呈现(形如 `… (截断:K 行 / 原 N 字节)`),使子代理知晓其上下文不完整;
   被截字段与原始字节数 MUST 记入产出。
3. **fail-loud 零派发**:瘦身后仍超预算 → 退出码 2,stderr MUST 报出该单元的 `unit_id`、适用上限、实测
   字节数与最大贡献文件。判定 SHALL 发生在写出任何切片文件与待办清单**之前**(零副作用),使
   `fanout_runner --tier sdr` 对枚举脚本退出码 2 的原样透传即等价于零派发。

三级处置 SHALL NOT 引入任何新增 CLI flag:`--max-standalone-bytes`(standalone 簇归并上限)与
`--max-interface-bytes`(interface 单元上限)仍是唯二的预算调节杆,两级内部瘦身上限为脚本内模块常量。
适用上限的选取 SHALL 为:standalone 单元用前者,interface 单元(含其续单元)用后者。

**默认上限按目标模型窗口校准(2026-10-15 立)**:`--max-interface-bytes` 的默认值 SHALL 为
**96KB(98304 字节)**;`--max-standalone-bytes` 的默认值 SHALL 维持 **64KB(65536 字节)**。校准
口径 SHALL 记录于 `--help` 文案与命令壳参数表,并满足:interface 单元的**最坏上下文栈** = 切片
96KB + 基线投影(默认 32KB)+ 外部仓结论(默认每仓 64KB)+ 任务消息与输出余量,按本仓 token
启发式(CJK 密集 ≈ 2 字节/token、代码 ≈ 3–4 字节/token 的保守口径)折算约 55~70K token,
对 150K token 上下文窗口的弱模型留足余量;standalone 单元同口径最坏约 53K token,无溢出风险,
维持 64KB 以免归并上限缩小推高单元数(调用次数限流网关下,单元数即调用数)。**单元数代价的
如实呈现**:interface 上限从 256KB 降到 96KB 会让原本不切的大接口被切出更多 `-partN` 续单元
(重切不降低输入完整度,不属报告披露面),该取舍 SHALL 在 `--help` 与参数表中一句话说明;
大窗口宽松环境的用户 SHALL 显式传 flag 调大(256KB 旧默认仍是合法显式取值)。**resume 预算
粘滞**:run 目录已存在携带预算记录的 `grouping.json` 且本次调用未显式传两个预算 flag 时,
`diff_group.py` SHALL 复用该记录中的两个上限值(同一 run 的单元身份 NEVER 因版本升级后的默认值
漂移而改变——`fanout_runner --tier sdr` 每次调用都重跑物化,上限漂移会让大接口的重切份数变化、
`-partN` 单元 id 漂移,已 done 单元被当作新单元重派,在调用次数限流网关下等于白烧整份配额);
显式传 flag 仍 SHALL 优先生效,且新上限引发的单元重切 SHALL 正常发生(操作者显式改预算是
合法动作)。

`grouping.json` SHALL 新增顶层预算记录(本次运行实际生效的两个上限)与每单元瘦身痕迹
(`slimmed{字段名: 原始字节数}`;未截断为空对象)。`--check <run-dir>` SHALL 在相应字段存在时断言
`pending[]` 每项的 `unit_bytes` ≤ 其适用上限、且 `slimmed` 结构合法(值为整数映射);字段缺失(旧
`grouping.json`)SHALL 跳过该断言,不得因此判违规——向后兼容与既有 `excluded`/`codegraph_stats`/
`chain[]` 的增量字段同例。人读报告的诚实边界 SHALL 在本次运行发生过瘦身时披露被瘦身单元及其降低的
输入完整度(重切本身不降低完整度,不属披露面)。

预算内路径 SHALL 逐字节不变:切片文本、`pending[]` 既有字段、退出码与既有 stderr 行均与引入本要求前
一致。

#### Scenario: 多文件单元实测超预算时无损重切

- **WHEN** 一个含多个文件的 standalone 单元(或一个 interface 单元的多个成分)渲染后实测字节 > 其适用上限,
  而其中任一文件单独渲染 ≤ 上限
- **THEN** 该单元按既有贪心规则切成多个续单元,每份续单元实测 ≤ 上限;所有 hunk 与上下文一份不少地分布
  在续单元中(并集与切分前等价),不触发瘦身、不 fail-loud

#### Scenario: 单文件原子残渣经瘦身仍可复核

- **WHEN** 一个单元只剩单文件且渲染实测 > 上限,但其超出量可由截断描述性上下文块(注解上下文 / 符号表)
  消除
- **THEN** 该单元被物化,切片内的上下文块带可见截断标记、diff 正文与文件清单与 hunk 定位头完整保留;
  `grouping.json` 该项 `slimmed` 记录被截字段与原始字节数;运行不 fail-loud

#### Scenario: 单文件原子残渣瘦身仍超预算则零副作用终止

- **WHEN** 单个文件的 diff 正文本身即超过上限(截断上下文块无法把实测降到上限内)
- **THEN** `diff_group.py` 退出码 2,stderr 报出该单元 `unit_id`、适用上限、实测字节数与最大贡献文件;
  该次运行不写出任何切片文件、不写出可被派发器消费的待办清单;`fanout_runner --tier sdr` 透传退出码 2,
  零子代理被派出

#### Scenario: 闸门判据与切片产物同源

- **WHEN** 任一单元被物化,`pending[]` 项携带 `unit_bytes`
- **THEN** 该值等于其切片文件的实际字节数,且 ≤ 该单元的适用上限(瘦身单元亦同——判据与产物出自同一渲染)

#### Scenario: 预算内路径逐字节不变

- **WHEN** 一次运行的每个单元实测均 ≤ 适用上限
- **THEN** 每份切片文本与 `pending[]` 既有字段与引入本要求前逐字节一致;退出码与既有 stderr 行不变;
  新增的预算记录与空 `slimmed` 是仅有的增量

#### Scenario: 旧 grouping.json 仍是 --check 合规产物

- **WHEN** `--check <run-dir>` 面对一份不含预算记录与 `slimmed` 的旧 `grouping.json`
- **THEN** 预算断言被跳过,退出码 0(旧产物逐字兼容);含新字段时断言生效,超上限或结构非法则退出码 2

#### Scenario: 瘦身痕迹进入报告边界声明

- **WHEN** 一次运行中有单元被瘦身后派发
- **THEN** 渲染报告的诚实边界列出被瘦身单元及其"上下文经截断、输入完整度低于常规单元"的说明;未发生
  瘦身时该条目不出现

#### Scenario: 新默认上限在 help 与壳参数表一致呈现

- **WHEN** 审阅 `py diff_group.py --help` 与三面 `mgh-sdr` 壳参数表、规范示例行
- **THEN** `--max-interface-bytes` 默认标注 96KB(98304)、`--max-standalone-bytes` 默认标注 64KB;
  校准口径(150K 窗口反算 + 最坏上下文栈算术)与「单元数代价」一句话均在;规范示例行不再显式传
  256KB 旧值;三面镜像与 `--help` 数值一致(确定性文档面,机器可对账)

#### Scenario: 大接口在新默认下无损重切为续单元

- **WHEN** 某 interface 单元渲染后实测 200KB(旧默认 256KB 下不切),以新默认 96KB 运行同 diff
- **THEN** 该单元被切为多份 `-partN` 续单元,每份实测 ≤ 96KB,hunk 一份不丢;`grouping.json` 预算
  记录两个上限为新默认值;报告对重切无额外披露(重切不降低完整度)

#### Scenario: 显式传旧默认仍是合法取值

- **WHEN** 大窗口环境的用户显式传 `--max-interface-bytes 262144`
- **THEN** 运行按 256KB 上限执行(与旧默认行为一致),预算记录如实记录 262144;无告警、无强制收窄

#### Scenario: resume 时预算记录粘滞,单元身份不漂移

- **WHEN** 某 run 的 `grouping.json` 预算记录为 256KB(旧默认时代开出),工具升级后(新默认
  96KB)以 `--resume` 同参重派,调用未显式传预算 flag
- **THEN** 本次物化沿用记录中的 256KB,`-partN` 单元 id 与该 run 既有 marker 完全对齐,已 done
  单元零重派;若操作者显式传 `--max-interface-bytes 98304`,则新上限生效、重切正常发生且预算
  记录更新为新值
