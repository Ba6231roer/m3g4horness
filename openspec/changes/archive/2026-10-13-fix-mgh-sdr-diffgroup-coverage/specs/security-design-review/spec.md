## ADDED Requirements

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
