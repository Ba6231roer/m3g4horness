## MODIFIED Requirements

> 本 delta 的替换底稿 = `improve-mgh-sdr-slice-economy` 归档后的 security-design-review 基线
> (其 197 行 delta 对需求一与渲染需求已有全文,本 change 在其之上改写;归档顺序:先
> slice-economy,后本 change)。

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
  ① 测试树与测试命名:`src/test/**`、`**/test/**`、**/tests/** 目录及 `*Test.java`/
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
族对齐(含 `@RequestMapping` 及组合注解),并拼接类级 base route(平凡可判定时)),结果物化
为 `<run-dir>/external/<repo-slug>/` 下的小体积结论文件(逐仓字节预算,默认 ≤64KB,超限截断
披露),**并 SHALL 将逐路由计数物化进 context.json `external_repos[].route_hits[]`**
(`{route, count}` 列表;此前仅存在于 hits.md 文本、render 不可确定性消费),并输出该仓**根绝
对路径**供编排器写入运行域哨兵 `read_roots[]`。外部声明不存在、路径不可达、非 git 目录三者任一
SHALL 降级为 `external_repos: []` + stdout `external_skipped:<原因>`,流程继续不失败。
subagent task 消息 SHALL 仅携带物化结论文件的路径(逐字透传),NEVER 携带外部仓原始路径供
subagent 自行读取。`--check <run-dir>` 校验两类产物自洽(新增校验:`route_hits[]` 存在时
SHALL 为 `{route, count}` 列表形态)。

#### Scenario: 前端路由计数进入 context.json 可被 render 消费

- **WHEN** 存量设计声明前端仓 `D:/xxx/front`(存在且 git 可达),本分支新增路由 `/order/submit`
  与 `/cache/user/direct`,前端仓文本文件分别命中 2 处与 0 处
- **THEN** context.json `external_repos[0].route_hits` 含 `{route:"/order/submit", count:2}`
  与 `{route:"/cache/user/direct", count:0}`,render 简报表该路由行前端两列为「是 / 2 处」与
  「否 / —」;`@RequestMapping` 族路由(非组合注解)同样被计数

#### Scenario: 存量设计声明前端仓时检索结论被物化

- **WHEN** `AGENTS.md` 安全章节含「本地前端项目地址 D:/xxx/front,前端分支名与本项目一致;
  垂直越权以 buttonAuth.properties 配置为准」,且该目录存在
- **THEN** `sdr_context.py` 产出基线 slice + `external/<slug>/` 结论文件(含本分支新增接口路由在
  `buttonAuth.properties` 的命中清单 + 前端出现计数),stdout 声明 `external_repos: [{path:"D:/xxx/front",...}]`;
  后续接口单元 subagent 读到的 task 消息含该结论文件路径而非 `D:/xxx/front`

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
  = 方法定义时链写到分析可达处);前端两列 = 按 route join context.json
  `external_repos[].route_hits[]`(声明 ∧ 命中 >0 = `是`+`N 处`;声明 ∧ 0 命中 = `否`+`—`;
  无声明/不可达 = `未知`+`—`;多路由单元仅按主路由(分号串第一段)join,次路由命中不抬升
  主路由状态);维度列 = `否` 或 `是 [P-NN]`
  (该单元该维度的合并 findings 编号列表,**纯文本编号**,SHALL NOT 产出任何 md 内部锚点/
  HTML anchor——目标编辑器(obsidian/Zed)不支持内嵌锚点跳转,编号即可定位);
- **章节二「问题详述」**:合并去重后的每条 finding 一小节,统一 `P-NN` 编号(全局递增),
  标题形态 `### P-01 · <维度中文标签> · <route 或独立方法> · <severity 中文>`;正文含位置
  (`file:line`——line 取 draft 新增 `line` 字段(问题锚定行号,数值);draft 缺 `line` 时
  降级为 `file`(不硬失败,旧 draft 兼容))、风险、建议、control_ref;排序 severity 升序
  (高→提示)、同 severity 按 P-NN;
- **章节三「分支调用链图」**:仅含带真实分支(`chain[]` 存在 **非 external** 节点携带
  `branch_of`——即 java 调用扇出;mapper 终端节点按 D3 编码也带 `branch_of`,但不构成真实
  分支)的单元,每单元一张 mermaid `flowchart LR`(入口 → 逐节点 → mapper 终端虚线边);
  线性链单元(含仅 ⇢ 终端带 `branch_of` 的直连 dao 短链)SHALL NOT 入本节;
- **「无问题单元」清单**(保留,供 merge 前放行参考)+ **诚实边界节**(≥7 条,含排除集披
  露,保留现行)。

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
  `<a id=`、`{#...}`、`[text](#...)` 形态(md 内部锚点);`P-NN` 编号全局唯一且章节二可按
  编号定位

#### Scenario: 报告文件名与内容可追溯

- **WHEN** 对分支 `feature-pay` 于 2026-09-03 14:30:22 完成评审
- **THEN** 项目根出现 `mgh-sdr-feature_pay-20260903_143022.md`,头部含 branch/base/时间戳,
  章节一每行可溯源到 unit_id,章节二每条可溯源到 file:line(或 file)

#### Scenario: draft 缺 line 字段降级

- **WHEN** 某 `.done` draft 的 finding 无 `line` 字段(旧格式 draft)
- **THEN** 章节二该条位置写 `file`(无行号),渲染不失败,`--check` 不视为不一致

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
  `frontend_count` 与表格单元格一致;`issue_refs[]` 展平该行全部问题编号

#### Scenario: 报告披露排除集与分组统计

- **WHEN** 本次 run 排除了 120 个文件(测试 80/构建产物 30/静态资源 10)且 codegraph 捕获
  25 条变更集内调用边、向上锚定 8 条链
- **THEN** 报告诚实边界含排除计数与分类,manifest `counts.excluded_files == 120`;分组统计
  在报告头部「分组概览」可见,供操作者判断分组质量
