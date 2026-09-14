## MODIFIED Requirements

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
`--max-standalone-bytes` 继续辖 standalone 归并。`--materialize <dir>` SHALL 枚举 `pending[]`:
每项含 `unit_id`(文件系统安全命名,`/ \ :` 一律 `_`,承 NTFS ADS 教训)、`input_path`(slice
绝对路径,`Path.resolve()` 绝对且在 repo 子树内)、`draft_path`/`done_marker`/`failed_marker`
(同形绝对)、`kind`(`interface`|`standalone`)、`route`(interface 单元的路由串,合并单元
可为多路由分号连接;standalone 为空串)、`unit_bytes`;stdout 另携带 `repo` 锚、`branch`/`base`、
`total`/`done`/`failed`、`counts{interface,standalone}`、`codegraph`(bool:本次是否走调用链
分组)、`excluded{count, by_reason{}}` 与 `codegraph_stats{symbols_queried, edges_captured,
edges_in_changed_set, anchors_changed, anchors_upstream, chain_merged}`(分组可观测:即使
codegraph 整体不可用亦 SHALL 携带零值结构,调用链分组实际捕获率可诊断)。退出码 `0/1/2`;
stdout=结构化 JSON、stderr=诊断严格分流(诊断行 SHALL 含排除计数与锚定/合并摘要);
`--check <run-dir>` 校验 run 产物自洽(slice 齐备、pending 路径绝对且在 repo 子树、manifest
字段一致、新字段形态合法),失败退出 2(承 R5.9)。零变更 diff(两 ref 无差异)SHALL 退出码 0
且 `pending: []` + stdout `empty:true`,不进入 fan-out。

#### Scenario: 测试与构建产物被排除且披露

- **WHEN** 某 diff 触及 `src/main/java/.../UserService.java`、`src/test/java/.../UserServiceTest.java`
  与 `target/classes/.../UserService.class`(源码改动 + 测试 + 构建产物)
- **THEN** `diff_group.py` 仅为 `UserService.java` 产生评审单元;stdout
  `excluded.count >= 2` 且 `by_reason` 区分 `test-tree`/`build-output`;报告诚实边界列出排除
  计数

#### Scenario: 兜底开关恢复全量评审

- **WHEN** 操作者传 `--include-excluded` 重跑同一 diff
- **THEN** `*Test.java` 等文件回归 standalone 归并流程产生单元,`excluded.count == 0`

#### Scenario: SQL 与 mapper XML 不被排除

- **WHEN** 某 diff 触及 `src/main/resources/mapper/UserMapper.xml` 与 `db/migration/V2__x.sql`
- **THEN** 两文件均进入评审单元(目录聚簇),`excluded.by_reason` 不含它们

#### Scenario: 同链变更合并为接口调用链单元

- **WHEN** 某 diff 触及 `OrderController.java` 的 `@PostMapping("/order/create")` 方法、
  `OrderService.java` 的 `createOrder` 方法、`OrderDao.java` 的 `insertOrder` 方法,且 codegraph
  调用边表明 `OrderController.createOrder` → `OrderService.createOrder` → `OrderDao.insertOrder`
- **THEN** `diff_group.py --materialize` 产出 1 个 `kind=interface` 单元(route=`/order/create`,
  slice 含三者 hunk 与类级注解上下文),而非 1 个接口单元 + 2 个 standalone 单元

#### Scenario: 反射/DI 判不穿的变更落独立单元

- **WHEN** 某 diff 触及 `PayService.java` 的 `pay` 方法(经反射/DI 注入被调用,codegraph 无其
  调用边)与 `AuditService.java` 的 `log` 方法(彼此无调用边)
- **THEN** 两方法不产生 interface 单元;java 残余按目录聚类 + `--max-standalone-bytes` 归并
  (可达集不同不硬塞同链),流程退出码 0、pending 非空、不失败

#### Scenario: 共享下游按接口拆、不并成一个分量

- **WHEN** 某 diff 触及 `UserController.java` 的 `/user/detail` 与 `/user/list` 两个接口,两者都
  调变更的 `UserService.queryUser`,而 `DeptController.java` 的变更 route 也调它
- **THEN** `UserController` 文件内的同链 route 按共享链合并规则归并;`DeptController` 侧保持
  独立 interface 单元(跨 controller 不合并),`UserService.queryUser` 的 hunk 在两单元 slice
  内各出现一次;两单元若产相同 finding 由渲染侧三元组去重

#### Scenario: 无 codegraph 退化为注解+目录分组

- **WHEN** `<repo>/.codegraph/` 不存在或 PATH 无 `codegraph`
- **THEN** 分组退化为注解启发式接口单元 + 目录簇 standalone,stdout `codegraph:false` 且
  `codegraph_stats` 零值结构在;行为与无 codegraph 时逐字等价

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

#### Scenario: 合并后超预算拆续单元

- **WHEN** 某 interface 单元合并多链后 slice 超 `--max-interface-bytes`(默认 256KB)
- **THEN** 该单元确定性拆为多个 part 单元(`unit_id` 带 part 后缀),每片均在预算内,pending
  各项 `input_path` 独立

#### Scenario: codegraph 缺失时退化并携带零值统计

- **WHEN** `<repo>/.codegraph/` 不存在或 PATH 无 `codegraph`
- **THEN** 分组退化为注解启发式接口单元 + 目录簇 standalone,stdout `codegraph:false` 且
  `codegraph_stats` 各字段为 0(结构在),行为与无 codegraph 时等价

#### Scenario: 零变更 diff 空转

- **WHEN** `--base master --branch X` 且 X 与 master 无任何差异
- **THEN** 退出码 0,stdout `{"empty": true, "pending": [], ...}`,编排器不 spawn 任何
  subagent,仍渲染一份「无变更」报告

### Requirement: 统一问题记录汇总与确定性报告渲染

新增确定性叶脚本 `render_sdr_report.py`(标准库、退出码 0/1/2、`--check` 承 R5.9)SHALL 收
run 目录下全部 fan-out 单元 draft(`.done` 且 JSON 可解析者;`.failed` 单元以 stderr 汇总 +
manifest `failed_units[]` 计入,不阻断渲染),按 `{dimension, route, file}` 三元组去重合并,
渲染 `<repo>/<工具名>-<分支名>-<YYYYMMDD_HHMMSS>.md`(工具名固定 `mgh-sdr`;分支名取文件系统
安全命名;时间戳到秒、本地时区)。报告 SHALL 为简体中文、面向人读,结构:头部(分支/base/
时间/检查面/敏感目录来源/外部仓结论摘要)+ 按维度分组的问题清单(每条含 severity/route/file/
line_hint/风险/建议/control_ref)+ 「无问题单元」清单(通过复核的接口,供 merge 前放行参考)+
诚实边界节。同名报告文件已存在 SHALL 原子覆盖(时间戳到秒内重跑)。`sdr_manifest.json`(落
run 目录)SHALL 记 `{branch, base, dimensions, sensitive_catalog_source, external_repos[],
counts{units, interfaces, standalone, findings_by_severity, failed_units, excluded_files},
boundaries[]}`(`excluded_files` 自 grouping.json `excluded.count` 透传)。诚实边界 SHALL 至
少含 7 条:① 发现是 LLM 候选需人工复核,非确认漏洞;② 接口分组是启发式,漏分组接口退入独立
单元(分析粒度粗但覆盖不丢);③ 引用存量控制断言存在、不断言有效;④ 外部仓结论是检索时点快照
(不保证前端分支已同步);⑤ 基线经字节预算投影,低优先级细节可能未全量投影;⑥ 敏感目录来源与
覆盖范围(目录外字段仅按回退规则识别);⑦ **排除集披露**——本次运行按闭集排除了 N 个文件
(测试树/构建产物/静态资源/锁文件/构建脚本,按原因分类计数),它们未进入评审,可用
`--include-excluded` 兜底。渲染器 NEVER 写 `openspec/`、NEVER 写 run 目录与报告文件之外的
目标仓文件。

#### Scenario: 报告文件名与内容可追溯

- **WHEN** 对分支 `feature-pay` 于 2026-09-03 14:30:22 完成评审
- **THEN** 项目根出现 `mgh-sdr-feature_pay-20260903_143022.md`,头部含 branch/base/时间戳,
  正文按 6 维度分组列 findings,每条可溯源到 file + line_hint

#### Scenario: 部分单元 failed 不阻断渲染

- **WHEN** 10 个单元 9 个 `.done`、1 个 `.failed`
- **THEN** 渲染器汇总 9 份 draft 出报告,manifest `counts.failed_units = 1` + `failed_units[]`
  列出该单元 id 与 reason,报告诚实边界披露「1 个评审单元失败,该单元覆盖范围未复核」

#### Scenario: 重复 finding 跨单元去重

- **WHEN** 同一接口路由的两个 hunk 被拆入同组或相邻单元,各产一条 `{dimension,route,file}` 相同
  的 finding
- **THEN** 渲染器按三元组去重合并为一条(line_hint 取并集),报告不再重复列出

#### Scenario: 报告披露排除集与分组统计

- **WHEN** 本次 run 排除了 120 个文件(测试 80/构建产物 30/静态资源 10)且 codegraph 捕获
  25 条变更集内调用边、向上锚定 8 条链
- **THEN** 报告诚实边界含排除计数与分类,manifest `counts.excluded_files == 120`;分组统计
  (单元数 interface/standalone、锚定/合并摘要)在报告头部或诚实边界可见,供操作者判断
  分组质量
