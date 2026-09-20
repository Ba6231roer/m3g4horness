# security-design-review Specification

## Purpose

`/mgh-sdr`(security design review)——需求分支代码变更的存量安全设计符合性复核:以
`git diff <base>..<branch>` 为输入,按接口维度 + 独立变更单元分组 fan-out,对照 mgh-init 产出的
存量安全设计与可配置检查维度(垂直/横向越权、其他权限、SQL 注入、敏感信息屏蔽、输入校验默认开)
逐单元查设计遗漏,确定性汇总渲染一份 md 报告到项目根。覆盖:diff 采集与分组、外部仓受控检索、
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
route, file, line_hint, risk(简体中文风险描述), suggestion(简体中文整改建议), control_ref
(命中的存量安全设计名或 null)}`。`sensitive-data` 维度 SHALL 依编排器透传的敏感目录执行(见
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
渲染 `<repo>/<工具名>-<分支名>-<YYYYMMDD_HHMMSS>.md`(工具名固定 `mgh-sdr`;分支名取文件系统
安全命名;时间戳到秒、本地时区)。报告 SHALL 为简体中文、面向人读,结构:

- **头部**(分支/base/时间/检查面/敏感目录来源/外部仓结论摘要 + 分组概览,保留现行);
- **章节一「简报表」**(本需求的核心结构):md 表格,**行 = 评审单元**(排序:interface 按
  route 升序、standalone 殿后按 unit_id;多路由单元按首路由参与排序),列 = 接口/方法入口、
  调用链、是否前端接口、前端使用次数、6 维度各一列(默认闭集维度;自由扩展维度各追加一列)。
  各列 SHALL 满足:入口列 = route 串(standalone 或无路由 = 该独立方法定义 `fqn_short`);
  调用链列 = 缩写链文本(按 grouping.json `units[].chain[]` 确定性渲染:仅保留类名/文件
  名:方法名,如 `OrderController.submit → OrderServiceImpl.submit`,真仓试用后由「包段
  首字母 + 类名」形态收敛,完整包路径可由 file 列还原,`·` 同类延续、`⤷` 分支(`branch_of` 宿主)、`⇢` mapper XML 终端、
  `†` 未变更节点;`chain[]` 为空(standalone/codegraph off)= 该单元方法定义短形;入口
  = 方法定义时链写到分析可达处);**入口列与调用链列的每个「类名.方法名」短形 SHALL 渲染为
  指向仓内源文件的 markdown 链接**(见本需求「源文件链接渲染」段);前端两列 = 按 route join
  context.json `external_repos[].route_hits[]`(声明 ∧ 命中 >0 = `是`+`N 处`;声明 ∧ 0 命中 =
  `否`+`—`;无声明/不可达 = `未知`+`—`;多路由单元仅按主路由(分号串第一段)join,次路由命中
  不抬升主路由状态);维度列 = `否` 或 `是 [P-NN]`
  (该单元该维度的合并 findings 编号列表,**纯文本编号**,SHALL NOT 产出任何 md 内部锚点/
  HTML anchor——目标编辑器(obsidian/Zed)不支持报告**内部**锚点跳转,编号即可定位;本约束
  SHALL NOT 及于指向仓内源文件的链接,后者是本需求的交付内容);
- **章节二「问题详述」**:合并去重后的每条 finding 一小节,统一 `P-NN` 编号(全局递增),
  标题形态 `### P-01 · <维度中文标签> · <route 或独立方法> · <severity 中文>`;正文含位置
  (`file:line`——line 取 draft 新增 `line` 字段(问题锚定行号,数值);draft 缺 `line` 时
  降级为 `file`(不硬失败,旧 draft 兼容);位置文本 SHALL 渲染为指向该源文件的 markdown
  链接(见「源文件链接渲染」段))、风险、建议、control_ref;排序 severity 升序
  (高→提示)、同 severity 按 P-NN;
- **章节三「分支调用链图」**:仅含带真实分支(`chain[]` 存在 **非 external** 节点携带
  `branch_of`——即 java 调用扇出;mapper 终端节点按 D3 编码也带 `branch_of`,但不构成真实
  分支)的单元,每单元一张 mermaid `flowchart LR`(入口 → 逐节点 → mapper 终端虚线边);
  线性链单元(含仅 ⇢ 终端带 `branch_of` 的直连 dao 短链)SHALL NOT 入本节;mermaid 节点
  标签 SHALL NOT 嵌入链接(mermaid 锚点语法跨编辑器兼容性差,跳转由章节一表格承担);
- **「无问题单元」清单**(保留,供 merge 前放行参考)+ **诚实边界节**(≥7 条,含排除集披
  露,保留现行)。

**源文件链接渲染**(本需求新增的渲染规则,报告写在目标仓根目录 ⇒ 链接目标 = 源文件相对
仓根的相对路径):

- 链接形态 `[显示文本](<相对路径>#L<line>)`;`line` 缺失或为 `null` 时 SHALL 退化为
  `[显示文本](<相对路径>)`(不带锚点;不支持锚点的编辑器对 `#L<line>` 自动退化为只打开
  文件,故有 line 就带上)。
- 路径解析:chain 节点 `file` 与 finding `file` 为相对路径(相对 `--repo`)时直接作链接
  目标(输出统一 `/` 分隔);为绝对路径时,resolve 后在 `--repo` 子树内 → 转为相对路径,
  在子树外 → **不产链接**(降级纯文本,报告里没有指向仓外的死链);字段缺失/空 → 纯文本。
  路径解析 SHALL NOT 依赖文件真实存在(diff 分支的源文件可能未检出到工作树;链接坏与否由
  编辑器呈现,渲染器只做词法判定,NEVER 因此 stat 目标文件)。
- 显示文本 = 现行短形(`fqn_short` 等,含 `†` 前缀)逐字不变;`·`/`⤷`/`⇢`/`→` 分隔符不
  入链接;mapper XML 终端(`change=external`)与普通节点同等对待(有 `file` 即链)。
- 显示文本含 `]` 等会破坏 md 链接语法的字符时,SHALL 对其做最小转义(`\]`/`\[`)或退化为
  纯文本,NEVER 产出语法破损的链接单元格。
- `sdr_manifest.json` `rows[]` 的 `entry`/`chain` 字段 SHALL 保持**纯文本短形**(不含链接
  markdown 语法)——manifest 是机器消费面;表格链接是同一数据的渲染投影。

同名报告文件已存在 SHALL 原子覆盖(时间戳到秒内重跑)。`sdr_manifest.json` SHALL 新增
`rows[]`(简报表逐行结构化投影:`{unit_id, entry, chain, frontend_is, frontend_count,
issue_refs[]}`;issue_refs = 该单元各维度问题编号的展平列表),供下游确定性消费(如未来
/mgh-blst);`counts` 语义不变;其余字段保留现行(`excluded_files` 透传等)。draft 问题记录
schema 扩展 `line`(int,可选;任务模板与 agent 定义双端同步披露)。

诚实边界 SHALL 至少含 7 条(现行 7 条语义保留):① 发现是 LLM 候选需人工复核,非确认漏洞;
② 接口分组是启发式,漏分组接口退入独立单元(分析粒度粗但覆盖不丢);③ 引用存量控制断言存在、
不断言有效;④ 外部仓结论是检索时点快照(不保证前端分支已同步);⑤ 基线经字节预算投影,低优先
级细节可能未全量投影;⑥ 敏感目录来源与覆盖范围(目录外字段仅按回退规则识别);⑦ 排除集披露。
渲染器 NEVER 写 `openspec/`、NEVER 写 run 目录与报告文件之外的目标仓文件。

#### Scenario: 简报表行覆盖全单元形态

- **WHEN** 某 run 产 4 个 interface 单元(其一为多路由合并单元)、3 个 standalone 单元、其中
  2 个 interface 单元的 `chain[]` 带**非 external** 节点的 `branch_of`(真实分支)
- **THEN** 章节一表格 7 行(排序:interface 按 route 升序、standalone 殿后);interface 行
  调用链列为缩写链(含 `⤷`/`⇢`/`†`),standalone 行为方法定义短形;带分支的 2 单元在章节三
  各有一张 mermaid 图,线性单元不出现;全部维度列为 `否` 或 `是 [P-NN]` 纯文本

#### Scenario: 前端两列三态

- **WHEN** context.json 声明外部仓且 `/order/submit` 命中 2 处、`/cache/user/direct` 0 处,
  另一路由所在 run 未声明外部仓
- **THEN** `/order/submit` 行前端两列 = `是`+`2 处`;`/cache/user/direct` 行 = `否`+`—`;
  未声明仓的 run 其全部行 = `未知`+`—`

#### Scenario: 无锚点纯文本编号引用

- **WHEN** 渲染任意带 findings 的报告
- **THEN** 简报表格维度列与章节二标题均为纯文本 `P-NN` 编号;报告全文 SHALL NOT 出现
  `<a id=`、`{#...}`、`[text](#...)` 形态(md **内部**锚点,即 `(` 后紧跟 `#` 的跳转);
  指向仓内源文件的 `[text](relative/path#L42)` 形态链接不在此禁列;`P-NN` 编号全局唯一且
  章节二可按编号定位

#### Scenario: 链节点渲染为源文件链接

- **WHEN** 某单元 `chain[]` 含节点 `{fqn_short: "OrderController.submit", file:
  "src/main/java/com/x/controller/OrderController.java", line: 42}` 与节点 `{fqn_short:
  "OrderMapper.insertOrder", file: "src/main/java/com/x/mapper/OrderMapper.java", line: null}`
- **THEN** 调用链列依次渲染 `[OrderController.submit](src/main/java/com/x/controller/OrderController.java#L42)`
  与 `[OrderMapper.insertOrder](src/main/java/com/x/mapper/OrderMapper.java)`(无锚点退化);
  分隔符不入链接,链的阅读顺序与短形文本不变

#### Scenario: 仓外与异常路径降级纯文本

- **WHEN** 某 finding 的 `file` 为仓外绝对路径,另一 chain 节点 `file` 为空串
- **THEN** 前者位置、后者链节点均保持现行纯文本形态,报告不含仓外路径链接;渲染退出码 0,
  `--check` 不报不一致

#### Scenario: manifest rows 保持纯文本

- **WHEN** 渲染完成产 manifest,表格调用链列含 markdown 链接
- **THEN** `rows[]` 对应行 `chain`/`entry` 字段为纯文本短形(不含 `[`/`]( ` 链接语法),
  与去链接化前的表格单元格文本一致

#### Scenario: 报告文件名与内容可追溯

- **WHEN** 对分支 `feature-pay` 于 2026-09-03 14:30:22 完成评审
- **THEN** 项目根出现 `mgh-sdr-feature_pay-20260903_143022.md`,头部含 branch/base/时间戳,
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

- **WHEN** 渲染完成产 manifest
- **THEN** `rows[]` 长度 = 章节一表格数据行数,逐行 `unit_id`/`entry`/`chain`/`frontend_is`/
  `frontend_count` 与表格单元格一致(链接按「去链接化后的短形文本」比对);`issue_refs[]`
  展平该行全部问题编号

#### Scenario: 报告披露排除集与分组统计

- **WHEN** 本次 run 排除了 120 个文件(测试 80/构建产物 30/静态资源 10)且 codegraph 捕获
  25 条变更集内调用边、向上锚定 8 条链
- **THEN** 报告诚实边界含排除计数与分类,manifest `counts.excluded_files == 120`;分组统计
  在报告头部「分组概览」可见,供操作者判断分组质量

### Requirement: 敏感目录复用与默认模板回退(与 sra/srr 的显式分歧)

`sensitive-data` 维度的检查清单 SHALL 按以下优先级解析:① `<repo>/.mgh-sra/sensitive_catalog.json`
存在 → 经 sibling import 复用 `sensitive_catalog` 模块解析 + 闭集校验(非法 → 退出码 2 早停,
任何 LLM token 之前);② 不存在 → **回退加载随 install 落地的默认模板**
(`.mgh-core` 内 `sensitive_catalog.json.example`,即 PIPL/GB-T 35273 37 项)作为生效目录。解析后
对象(`{version, source, categories[], items[], counts{}, directive}`)SHALL 逐字透传进 subagent
task 消息,manifest `sensitive_catalog_source` SHALL 记 `project|default-template`。该回退是
sdr 与 sra/srr(`null` → 6-facet 兜底)的**有意行为分歧**:sdr 复核的是代码 diff,收窄到 6 facet
会让公司目录缺位时的敏感数据检查显著弱于默认模板;此分歧 SHALL 在本 spec、命令壳 `--help` 文案与
报告诚实边界三处显式披露。

#### Scenario: 项目目录存在则复用

- **WHEN** `<repo>/.mgh-sra/sensitive_catalog.json` 存在且合法
- **THEN** 编排器以 `sensitive_catalog_source: "project"` 解析并透传该目录,subagent 逐项查脱敏缺口
  并标 `catalog_key`

#### Scenario: 项目目录缺失回退默认模板

- **WHEN** `<repo>/.mgh-sra/sensitive_catalog.json` 不存在
- **THEN** 编排器以 `sensitive_catalog_source: "default-template"` 加载 `.example` 默认模板并透传,
  检查面为 PIPL/GB-T 35273 37 项;manifest 与报告披露该来源

#### Scenario: 项目目录非法早停

- **WHEN** `<repo>/.mgh-sra/sensitive_catalog.json` 存在但含未知 category
- **THEN** 编排器退出码 2 + 可操作 stderr(指向该文件的违规项),不 spawn 任何 subagent

### Requirement: launcher 单命令外壳与运行域激活

新增 launcher 脚本 `core/scripts/mgh_sdr_launch.py`(**随 install 分发**;人/cron 入口,NEVER 被
宿主 subagent 调用;标准库)SHALL 支持一条命令拉起全流程:`py mgh_sdr_launch.py --repo
<abs-target> [--branch <ref>] [--base <ref>] [--host opencode|claude] [--dimensions <json>]
[--multi-branch <file>]`。launcher
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
哨兵。`--multi-branch <file>` SHALL
对清单分支**串行**逐个执行完整流程(每分支独立 run 目录 + 独立报告;单分支失败记录后继续)。
launcher 自身退出码:0 全部分支成功 · 1 运行时失败 · 2 误用(参数/宿主缺失/目标不可达)。

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
的 read_roots 扩展要求生效。哨兵的写入 SHALL 为**确定性脚本副作用**(`sdr_context.py` 完成基线投影与
外部仓检索后 co-write),SHALL NOT 依赖编排器手执行的 `Bash printf` 配方。

流程 SHALL 幂等可恢复,分**产物层**与**入口层**两件事:

- **产物层**(既有语义不变):`diff_group.py --materialize` 对已存在 `.done` marker 的单元跳过物化重复工作;
  `fanout_runner.py --resume` 按磁盘 marker 重派 pending;`render_sdr_report.py` 对 draft 齐备的 run 目录
  可重复执行(重跑覆盖同名报告)。
- **入口层**(既有语义):`resume_sdr_state.py`(见 `resume-step-discipline`)SHALL 从 `<run-dir>/`
  磁盘产物重派生 `step` / `next_action` / `discipline_reminders[]`,使压缩 / 崩溃 / 新会话三态坍缩为同一条
  恢复路径(**读磁盘 → 继续**)。恢复 SHALL 复用**既有 run 目录**(同一 `<run-dir>`),SHALL NOT 另起一个新的
  时间戳 run 目录——新建目录 = 已完成单元的 marker 不在新目录里 = 全部重做(零复用即全损)。

编排器每步完成后 SHALL 跑对应产出者 `--check`,失败(退出码 2)回退重跑,不带着破损产物继续(承 R5.9)。

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
