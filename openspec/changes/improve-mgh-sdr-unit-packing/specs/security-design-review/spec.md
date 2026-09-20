# security-design-review Delta

## MODIFIED Requirements

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
route, file, line_hint, risk(简体中文风险描述), suggestion(简体中文整改建议), control_ref
(命中的存量安全设计名或 null)}`。`sensitive-data` 维度 SHALL 依编排器透传的敏感目录执行(见
「敏感目录复用与回退」要求);6 维度各自的判定锚点是**存量安全设计**(AGENTS.md 安全章节 +
`docs/security-controls/*.md` + 项目记忆),subagent task 消息 SHALL 逐字携带编排器从存量设计
投影出的**检查基线摘要**(确定性由 `sdr_context.py` 产出,≤ 预算字节),NEVER 要求 subagent 自行
读全部 rules 文件。

**打包形态的 I/O 约束(打包关闭时逐字不适用)**:当 `input_path` 指向的是**合并 slice**时,该
subagent 的读写面 SHALL 为**成员级**:SHALL 从合并 slice 首部的成员清单逐成员取读入内容与写入
目标,对每个成员**写该成员的 `draft_path`**、touch 该成员的 `done_marker`;SHALL NOT 写包条目的
`draft_path`(那是包级回执路径)。每个成员的 draft SHALL 仍满足本条的 schema 与「恰好读该成员
切片、恰好写该成员 draft」约束,且其 `unit` 字段 SHALL = **成员单元标识**(逐字),SHALL NOT
为包标识。单单元形态(非合并 slice)的 I/O 三元组 SHALL 逐字不变。

#### Scenario: 接口单元产出统一 schema 问题记录

- **WHEN** 某 `kind=interface` 单元(路由 `/user/detail`)的 slice 显示新增接口按入参 `brch_no`
  查询但调用链无 `UserContext.get()` 校验,而存量设计声明「横向越权须 brch_no + UserInfo 校验」
- **THEN** 该单元 draft 含一条 `{dimension:"horizontal-authz", severity:"high", route:"/user/detail",
  file:"UserController.java", risk:<未按存量设计校验的中文描述>, control_ref:<存量设计名>}` 的
  finding,且该 finding 可被渲染器与其他单元的去重合并

#### Scenario: 检查面参数化收窄

- **WHEN** 编排器传 `--dimensions '{"dimensions":["sql-injection","input-validation"]}'`
- **THEN** subagent 仅对这两个维度产出 findings(sensitive-data 目录不透传),其余维度不检查;
  manifest 记录实际检查面

#### Scenario: 非法维度键早停

- **WHEN** 编排器传 `--dimensions '{"dimensions":["crypto-audit"]}'`(非闭集且非自由文本扩展形态)
- **THEN** 编排器在任何 subagent spawn 之前以退出码 2 fail-loud,stderr 给出合法维度清单

#### Scenario: 打包单元的读写面落在成员上

- **WHEN** 某 pending 条目的 `input_path` 是合并 slice,首部成员清单列出 3 个成员及其各自
  `draft_path`/`done_marker`
- **THEN** 该 subagent 产出 3 份 draft,分别落在 3 个成员 `draft_path` 上、各自 `unit` 字段 =
  成员单元标识;3 个成员 `done_marker` 齐备;包条目自身的 `draft_path` 不被写

## ADDED Requirements

### Requirement: 接口单元确定性打包(配额摊薄,opt-in)

`diff_group.py` SHALL 提供**可选**的接口单元打包:当 `--pack-bytes <B>` 大于 0 时,把可打包的
`kind=interface` 单元确定性合并为派发单元(下称「包」),使一次派发的固定调用开销(会话启动、
读任务、读输入、写结果、回执)被多个成员单元摊薄。打包 SHALL 是**全量单元记录 + flag 取值的
纯函数**:同一份 diff 与同一组 flag 取值,跨 run 产同一组包与同一成员归属,与枚举顺序、分页
位置、运行时序无关。

**候选集与家族约束**:可入包的候选 SHALL 恰好是 `kind=interface`、非 `(part N)` 续单元、
`unit_bytes` 未超单元预算的单元。打包 SHALL 只在**同一家族**内进行,家族键 = 单元标识中
`::` 之前的宿主文件段(即同一 controller / 映射器宿主文件);跨家族 SHALL NOT 混包。
`kind=standalone` 单元 SHALL NOT 入包(其目录聚类已由 `--max-standalone-bytes` 归并);
`(part N)` 续单元与超预算单元 SHALL NEVER 入包。

**确定性分区与包标识**:同一家族内 SHALL 按 `(unit_bytes 升序, unit_id 字典序)` 排序后贪心
装包——加入下一成员会超过 `--pack-bytes` 或 `--pack-max` 即封包开新包;排序键含 `unit_id`
以保证同字节数时的全序稳定。包标识 SHALL 为成员集合的纯函数,SHALL NOT 依赖枚举次序或分页
位置。

**条目同形 + 成员清单**:打包开启时,`--materialize` 的 `pending[]` SHALL 以包条目替换其成员
条目;包条目 SHALL 与普通条目**同形**——同样的 `unit_id`/`input_path`/`draft_path`/
`done_marker`/`failed_marker`/`kind`/`route`/`unit_bytes`/`baseline_path`/`external_dir`
字段,仅多一个 `members[]`(每成员 `{unit_id, route, draft_path, done_marker, failed_marker,
input_path, unit_bytes}`)。包条目的 `unit_id` 载包标识、`kind` = `interface`、
`route` = 成员路由去重排序后以 `;` 连接、`input_path` = **合并 slice 文件**、
`unit_bytes` = 该合并文件落盘字节数(与非合并单元同一测量)。包条目全部路径 SHALL 为
`Path.resolve()` 绝对且在 repo 子树内。`grouping.json` 的 `units[]` SHALL 仍**逐成员一条**
(`unit_id` = 成员标识),SHALL NOT 被包条目替换。

**合并 slice**:每个包 SHALL 物化一份合并 slice 文件(utf-8):首部为确定性成员清单块(逐成员的
`unit_id`/`route`/`draft_path`/`done_marker`/`failed_marker` 绝对路径),其后拼接各成员单元的
slice 内容,使 subagent 一次读入即摊薄 N 次读入。成员清单块的存在与否 SHALL 是模板区分打包
形态与单单元形态的**唯一判据**。文件名 SHALL 经既有文件系统安全命名消毒(`/ \ :` → `_`,
承 NTFS ADS 教训)。

**成员级 marker 与 pending 判据**:成员级 `.done`/`.failed` marker SHALL 仍是**唯一真相源与
恢复粒度**;包条目的 pending 判据 SHALL 为「≥1 成员的 `.done` marker 不存在」,SHALL NOT 为
「包级 marker 不存在」——包级 `.done` 存在而成员 marker 缺失时该包 SHALL 仍列出为 pending。
包级 marker SHALL 落在**独立于成员 marker 的路径**上,使任何按目录枚举 marker 的单元级计数
(步骤派生、恢复、孤儿审计)不被包级回执污染。

**计数语义不变**:stdout 的 `total`/`done`/`failed`/`counts{interface,standalone}` SHALL
保持**成员级**语义,且取值与关闭打包时一致;打包视图的计数 SHALL 经**新增字段**披露
(包数 / 包 pending 数),SHALL NOT 复用既有字段改变其语义。

**边界校验**:`--check` SHALL 追加打包自洽断言——包标识 = 成员集合的确定性派生、包条目字段
与成员清单的非空与绝对性、无跨家族成员、无 `(part N)`/超预算成员、包条目 `unit_bytes` =
合并 slice 落盘字节数;失败退出码 2(承 R5.9)。

**关闭路径**:`--pack-bytes 0`(默认)时打包逻辑 SHALL 零执行,stdout 与 `grouping.json`
SHALL 与本机制引入前**逐字节一致**(不出现 `members[]`、不出现包计数新字段)。`--pack-max`
单独传入而 `--pack-bytes` 为 0 SHALL 退出码 2 拒识并给 recipe。

**非目标**:SHALL NOT 改派发器、SHALL NOT 改 draft schema、SHALL NOT 改分组算法(家族归属由
既有单元标识派生,不新增身份来源)。

#### Scenario: 同类目家族内确定性装包

- **WHEN** 某 `UserController` 文件内 4 个 interface 单元切片分别为 2KB/3KB/4KB/5KB,以
  `--pack-bytes 8KB --pack-max 3` 运行
- **THEN** 产出 2 个包(2KB+3KB 一包、4KB 一包超 `--pack-max` 前先封),成员归属与包标识对
  任意枚举顺序不变;两包 `route` 各为成员路由去重排序后的 `;` 连接

#### Scenario: 跨家族绝不混包

- **WHEN** 两个小单元分别来自 `UserController` 与 `OrderController`,两者字节数都远低于阈值
- **THEN** 它们不进入同一个包;若任一家族内不足 2 个成员,该成员以**单成员包**或按关闭路径
  形态派发,不跨文件凑包

#### Scenario: 续单元与独立单元不入包

- **WHEN** 某 diff 同时产 `(part N)` 续单元、超 `--max-interface-bytes` 的单元与若干
  standalone 单元
- **THEN** 三者均不出现在任何包的 `members[]` 中;standalone 仍按其目录聚类与字节预算归并

#### Scenario: 包 pending 由成员 marker 派生

- **WHEN** 某包 3 个成员中 2 个 `.done` marker 已就位,包级 `.done` 回执亦存在
- **THEN** 该包仍列出为 pending;重派后模板探测到 2 个已完成成员并只对第 3 个成员产出 draft

#### Scenario: 成员清单缺失即走单单元形态

- **WHEN** `input_path` 指向的文件首部不含成员清单块
- **THEN** 该单元按单单元形态复核(draft 写在 `draft_path`、touch `done_marker`),行为与打包
  机制引入前逐字一致

#### Scenario: 关闭打包时输出逐字节不变

- **WHEN** 以 `--pack-bytes 0`(默认)运行 `diff_group.py --materialize`,并与改动前同输入的
  stdout 与 `grouping.json` 对照
- **THEN** 两者逐字节一致,`pending[]` 内不出现 `members[]`,顶层不出现包计数新字段

#### Scenario: 无效 flag 组合拒识

- **WHEN** 只传 `--pack-max 4` 而 `--pack-bytes` 为默认 0
- **THEN** 脚本以退出码 2 fail-loud,stderr 给出 recipe(须同时给出 `--pack-bytes <B>`)

#### Scenario: `--check` 拦截不自洽的包

- **WHEN** 手工把某包条目的成员清单改成含一个来自别的家族的单元(或将 `unit_bytes` 改成与
  合并 slice 落盘字节数不符)
- **THEN** `diff_group.py --check <run-dir>` 以退出码 2 fail-loud

### Requirement: 打包单元的成员级复核与报告披露

打包只改变**一次派发读入多少内容**,SHALL NOT 改变单元级产物的粒度与视图:每个成员 SHALL 仍
产出一份 draft、一份 `.done` marker,报告 SHALL 仍按**成员单元**出行,步骤派生 SHALL 仍按
**成员 marker** 计数。

**派发模板双形态**:`core/prompts/fragments/fanout/sdr-task.md` SHALL 支持两种形态——单单元
形态(逐字保留)与打包形态。打包形态 SHALL:逐成员从合并 slice 首部成员清单取读入与写入目标、
逐成员写 draft(`unit` = 成员标识)并按该成员切片判定 6 维度、逐成员 touch `done_marker`;
某成员失败时 SHALL 先完成其余成员,末行 ack 单行 `failed <成员标识列表>:<原因>`,使 dispatcher
按既有状态机写**包级** `.failed`。成员标记 SHALL 在 ack 之前写就,使任一时刻中断后重派只重跑
缺失成员。

**报告与 manifest 披露**:`render_sdr_report.py` SHALL 在**本次 run 存在打包单元**时,于报告的
诚实边界节披露以打包形态复核的单元(包数与被合并的成员单元标识),并在 `sdr_manifest.json`
以新增字段承载同一事实(供下游确定性消费);**本次 run 无打包单元时该字段 SHALL NOT 出现、
报告 SHALL 逐字节等同于本机制引入前**。

**纪律表恢复指引**:命令面纪律表(确定性由 `discipline_core.py` 承载,双壳同步)SHALL 给出包级
`.failed` 的人工恢复 recipe:删包级失败回执 → 重新枚举 → 仅缺失成员重跑;并 SHALL 在
**人话说明**与**术语词典**中新增打包一节(开关、建议取值、调用次数算术、恢复指引、诚实边界)。

#### Scenario: 打包复核产成员级 draft

- **WHEN** 某包含 3 个成员,复核完成
- **THEN** `drafts/` 下出现 3 份 draft(逐成员 `unit` = 成员标识)、3 个成员 `.done` marker 与
  1 个包级 `.done` 回执;报告章节一仍为 3 行

#### Scenario: 成员失败不丢已完成成员

- **WHEN** 某包 3 个成员中第 2 个复核失败、第 1 与第 3 个成功
- **THEN** 第 1/3 个成员的 draft 与 `.done` marker 已落盘,ack 行为 `failed <成员2 标识>:<原因>`,
  dispatcher 写包级 `.failed`;按纪律表 recipe 删包级回执后重新枚举,重派仅对成员 2 产出 draft

#### Scenario: 报告披露打包形态

- **WHEN** 某 run 的 pending 含 2 个包共 7 个成员单元,渲染报告
- **THEN** 诚实边界节列出这 2 个包及其 7 个成员单元标识,`sdr_manifest.json` 含对应新增字段

#### Scenario: 无打包时报告逐字节不变

- **WHEN** 某 run 全部单元以单单元形态复核(打包关闭),渲染报告
- **THEN** 报告与 manifest 与本机制引入前**逐字节一致**,不出现打包披露字段

#### Scenario: 单元级视图不受打包影响

- **WHEN** 同一份 diff 分别以打包关/开两种配置跑完整 run
- **THEN** 报告章节一的**行集合逐行一致**(行 = 成员单元),两次 run 的成员级 `.done` marker
  可逐一核对;差异只出现在诚实边界节与派发会话数
