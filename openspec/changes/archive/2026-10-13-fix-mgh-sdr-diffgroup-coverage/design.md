# Design — fix-mgh-sdr-diffgroup-coverage

> 修复对象:2026-10-13 mgh-sdr 全流程深度评审的 diff 解析层缺陷(C1/C2/H4/M7/L6 + sast 侧 M14)。
> 每条均为评审报告已复现确认的实现缺陷;本 design 记录修法选型与防回归口径。

## D1 — quotePath 关闭点:`_git` 封装单点注入,非解析器适配

**C1 修法选型**:`git -c core.quotePath=false diff …`(配置注入)而非「让解析器识别带引号的
八进制转义形态」。

- 否决解析器适配:需完整实现 git 的 C 风格引号语法(引号包裹、八进制转义、引号内转义),
  复杂且与 git 行为漂移耦合;git 自身提供确定性开关。
- 注入位置:统一在 `_git` 封装层加 `-c core.quotePath=false`(所有 git 子命令统一带上,廉价
  且一致——`rev-parse` 等不输出路径的命令带上无害);NEVER 依赖调用方环境变量
  (`GIT_CONFIG_*` 跨机不可控)。
- 解码不变:既有 `errors="replace"` 已兜底非 UTF-8 字节;quotePath 关闭后路径按原始字节解码,
  中文名可正常还原。
- **M14 同形**:diff_seed.py 的 `git diff --name-status` 调用加 `-c core.quotepath=false`
  (键名小写与 C1 等价,git 配置键大小写不敏感;两脚本写法统一为 `core.quotePath=false`)。

## D2 — C2 修法:`_new_part` 后无条件 `_fill`,与单成员超限分支同形

- 现状:`_split_interface_budget` 贪心分支 `acc = _new_part(...)` 后 `_fill(acc, c)` 挂在
  `else:` 下,新 part 的开启成员 files 为空;且此前 absorb 已把该成员 hunk 记入 claimed,
  残差兜底按 claimed 跳过 → 双重静默丢失。
- 修法:去掉 `else`,`_new_part` 之后无条件 `_fill(acc, c)`(容量判定由 `_fill` 内部与外层
  循环共同保证:能走到这里说明当前成员必须开新 part,装入即正确)。对照正确形态:同函数
  「单成员超上限」分支在 `_new_part` 后手动 `acc.files.append(fd)`——两分支统一为
  「新建 part 必装当前成员」。
- 附带症状(part 挂成员 a 路由标签却装成员 b 文件)随修复自然消除,不单独立规。
- 防回归:**修复现有 `test_interface_budget_splits_parts` fixture 的盲区**——现有用例两成员
  各自单独超限,全走「单成员超上限」分支;新增「各成员单独 ≤ cap、合并 > cap」用例,断言
  hunk locator 并集 == 拆分前全集(评审复现形态:双成员各 1880B、合并 2648B、cap=2264)。

## D3 — H4 修法:替换集扩为 NTFS 非法字符闭集,不引入哈希唯一化

- `_safe_name` 替换集 `/ \ :` → `/ \ : * ? < > | "`(九字符);Windows 保留名(CON/NUL 等)
  与结尾点/空格的既有处理不动。
- 否决「unit_id 哈希化」:人读性是 unit_id 的既有价值(route/文件名可读),清洗集扩全后
  碰撞面不变(与现状同级),不值得为极端重名引入不可读标识。
- 路由串在 slice 正文与报告中的呈现**不变**(清洗只作用于落盘文件名)——测试断言两者的区分。

## D4 — M7 修法:A 文件归属对齐「每 hunk」量纲

- 现状:A 文件 `owner = list(range(len(syms)))`(每符号一列表),消费方按 hunk 下标
  `owner[j]` 取 → 单 hunk 时只有符号 0 拿到 hunk。
- 修法:A 文件构造为 `[list(range(len(syms)))] * len(fd.hunks)`(每 hunk 覆盖全部符号),
  与 M 文件的「每 hunk 一项」量纲对齐;写入映射时过滤越界下标(防御符号表与 hunk 数不一致
  的畸形输入,不抛错)。
- 回归:新增 controller(多路由方法、整文件单 hunk)→ 各路由方法进入 changed/anchors,
  分组单元数 > 1;断言与注释宣称的意图一致。

## D5 — L6 修法:误用显式退出码 2,双向不静默

- `--limit < 0` → argparse 后校验,退出码 2 + stderr 报合法范围(负值是误用,SHALL NOT
  clamp 成空页;与 0/1/2 退出码契约一致)。
- `--check` 与互斥 flag 同传 → stderr 逐个列出被忽略的旗标(退出语义不变:`--check` 照常
  执行)——保守方向,不把「编排器手滑多传」升级为 fail-loud,但消除静默。

## D6 — M14 附带卫生:种子过滤口径统一

- `SOURCE_EXT` 去重(现有重复 `.ts`);`deleted[]` 与 `seed[]` 同权适用源码扩展名过滤
  (现状 deleted[] 不滤,口径不一致)。均为数行小修,随 M14 同文件同批落地。

## D7 — diff_group 卫生

- 删死 import(`os`/`shutil`,以 AST/运行验证无引用后删除);`raw_text` 死参数链
  (:126-133)删除参数并同步调用点。零行为变化,`test_zero_deps`/`test_no_compile_warnings`
  顺手兜底。

## 测试与验收口径

- 定向回归:`tests/test_diff_group.py`、`tests/test_sdr_tier.py`、sast 面确定性阶段测试
  (`test_deterministic` 等);新增用例见各 D 节;`tests/test_zero_deps.py` +
  `tests/test_no_compile_warnings.py` 顺手。
- 每条修复的回归用例 MUST 复现评审所述失败形状(修复前红、修复后绿)——C1 中文路径、
  C2 贪心无损、H4 `/**` 写盘、M7 分簇不坍缩、L6 误用拒绝、M14 中文路径进 seed。
- 不跑全量(非跨面改动);发布前由维护者按仓库惯例跑全量。
