## MODIFIED Requirements

### Requirement: 确定性 diff 采集与接口维度分组

新增确定性叶脚本 `diff_group.py`(Python ≥3.10 标准库、零运行时依赖、自定位、任意 cwd 可 `py`,
承 R5.3a)SHALL 作为 `/mgh-sdr` 的枚举与切分唯一入口:以 `--repo <abs-root>` + `--base <ref>`
(默认 `master`)+ `--branch <ref>`(默认当前分支,经 `git rev-parse --abbrev-ref HEAD` 确定性
解析)运行 `git diff --no-color <base>..<branch>`,取得变更文件清单与 hunk。脚本 SHALL 先提取
**变更符号集**(diff hunk 锚到首个 added 行的宿主方法/接口:注解 + 方法声明 brace 域
确定性本地扫描作单一边界源——codegraph `node --file --symbols-only` 为 markdown 符号
表、无机器 endLine,不作边界源;无法映射的 hunk 归文件级变更),随后按以下
闭集规则分组:

- **调用链分组(codegraph 可用时)**:当 `<repo>/.codegraph/` 存在 ∧ PATH 有 `codegraph` 时,对
  每个变更符号 SHALL 跑 `codegraph callers --json` / `callees --json` 取调用边,在变更符号集上
  建图(仅保留两端均在变更集内的边)并并查集求连通分量;含 ≥1 路由注解符号的分量 → **`interface`
  单元**(= 该接口的完整下游链:路由方法 + 被调的变更 service/dao 的 hunk 合并进一个 slice),
  `route` 取该路由注解方法的 route 串;无路由分量 → **`standalone` 单元**。
- **退化分组(codegraph 不可用)**:当 codegraph 不可用时 SHALL 退化为注解启发式接口单元 + 目录簇
  standalone 归并(接口文件内按接口方法切、剩余文件按目录聚类,`--max-standalone-bytes` 控制单
  单元 slice 上限),行为与无 codegraph 时逐字等价。

两种模式下,分组 SHALL 是**启发式非承诺**:接口识别失败(无注解、非 java web)或调用边判不穿
(反射/DI/AOP 残差)SHALL 退化为 standalone 单元,流程不失败。**共享下游** SHALL 按接口拆:一个
变更符号被多个 interface 分量引用时不合并成一个分量,该符号 hunk 在每个引用它的 interface 单元
slice 内重复(受 `unit_bytes` 预算),跨单元重复 finding 交渲染侧三元组去重。每单元 SHALL 物化
一份**只读 slice 文件**(diff hunk + 有限邻近上下文,含文件相对路径、变更类型 A/M/D/R 标注),落
`<repo>/.mgh-sdr/runs/<ts>/slices/`。`--materialize <dir>` SHALL 枚举 `pending[]`:每项含
`unit_id`(文件系统安全命名,`/ \ :` 一律 `_`,承 NTFS ADS 教训)、`input_path`(slice 绝对路径,
`Path.resolve()` 绝对且在 repo 子树内)、`draft_path`/`done_marker`/`failed_marker`(同形绝对)、
`kind`(`interface`|`standalone`)、`route`(interface 单元的路由串,standalone 为空串)、
`unit_bytes`;stdout 另携带 `repo` 锚、`branch`/`base`、`total`/`done`/`failed`、
`counts{interface,standalone}`、`codegraph`(bool:本次是否走调用链分组)。退出码 `0/1/2`;
stdout=结构化 JSON、stderr=诊断严格分流;`--check <run-dir>` 校验 run 产物自洽(slice 齐备、
pending 路径绝对且在 repo 子树、manifest 字段一致),失败退出 2(承 R5.9)。零变更 diff(两 ref
无差异)SHALL 退出码 0 且 `pending: []` + stdout `empty:true`,不进入 fan-out。

#### Scenario: 同链变更合并为接口调用链单元

- **WHEN** 某 diff 触及 `OrderController.java` 的 `@PostMapping("/order/create")` 方法、
  `OrderService.java` 的 `createOrder` 方法、`OrderDao.java` 的 `insertOrder` 方法,且 codegraph
  调用边表明 `OrderController.createOrder` → `OrderService.createOrder` → `OrderDao.insertOrder`
- **THEN** `diff_group.py --materialize` 产出 1 个 `kind=interface` 单元(route=`/order/create`,
  slice 含三者 hunk 与类级注解上下文),而非 1 个接口单元 + 2 个 standalone 单元

#### Scenario: 反射/DI 判不穿的变更落独立单元

- **WHEN** 某 diff 触及 `PayService.java` 的 `pay` 方法(经反射/DI 注入被调用,codegraph 无其
  调用边)与 `AuditService.java` 的 `log` 方法(彼此无调用边)
- **THEN** 两方法各落一个 `kind=standalone` 单元(拆多个、不硬塞),流程退出码 0、pending 非空、
  不失败

#### Scenario: 共享下游按接口拆、不并成一个分量

- **WHEN** 某 diff 触及 `UserController.java` 的 `/user/detail` 与 `/user/list` 两个接口,两者都
  调变更的 `UserService.queryUser`
- **THEN** 产出 2 个 `kind=interface` 单元(`/user/detail`、`/user/list`),`UserService.queryUser`
  的 hunk 在两单元 slice 内各出现一次;两单元若产相同 finding 由渲染侧三元组去重

#### Scenario: 无 codegraph 退化为注解+目录分组

- **WHEN** `<repo>/.codegraph/` 不存在或 PATH 无 `codegraph`
- **THEN** 分组退化为注解启发式接口单元 + 目录簇 standalone,stdout `codegraph:false`;行为与无
  codegraph 时逐字等价

#### Scenario: 零变更 diff 空转

- **WHEN** `--base master --branch X` 且 X 与 master 无任何差异
- **THEN** 退出码 0,stdout `{"empty": true, "pending": [], ...}`,编排器不 spawn 任何 subagent,
  仍渲染一份「无变更」报告
