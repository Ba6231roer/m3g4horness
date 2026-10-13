> **人话序** 现象:2026-10-13 的 mgh-sdr 全流程深度评审(缺陷编号 C1/C2/H4/M7/L6/M14)在 diff 解析层确认了两条 critical 级的「变更静默丢失」:① 中文文件名的 diff 因 git 默认给非 ASCII 路径加引号转义,解析器不认识带引号的路径头,整个文件从分组、切片到报告完全消失,且与「真没有变更」不可区分;② 接口单元超预算拆分时,「开启新 part 的那个成员」的 hunk 从不进入任何切片——绕过了两级兜底,大 controller 恰好是目标场景。另有 Windows 写盘崩溃(`@GetMapping("/**")` 把 `*` 带进文件名)、新增 controller 的路由分簇坍缩、负值参数静默空页等。根因:git 默认行为未配置、装包分支放错、字符替换集不全、hunk 归属量纲用错。改什么:每处一行到数行的小修 + 各自回归测试;同族的 quotepath 缺口在 sast 侧种子脚本一并关掉。怎么验证:中文路径文件端到端进分组、「单独不超限/合并超限」拆分后 hunk 并集无损、`/**` 路由可写盘、定向回归全绿。

## Why

- 评审(2026-10-13,基线 main HEAD `6e6ac63`)确认 `core/scripts/diff_group.py` 存在两条 critical 实现违约,均直接违反本命令核心承诺「任何 diff 文件都不得静默丢失」,且都在产品目标场景(中文企业仓、数百万行大仓的大 controller、Windows/NTFS 一等目标)可触发:
  - **C1**:git 默认 `core.quotePath=true` 把非 ASCII 路径输出为带引号的八进制转义形,解析正则不匹配该形态,文件被静默跳过——不进分组、不进 excluded 计数,若为唯一变更文件则报 `empty:true` 退出码 0,与真零 diff 不可区分。
  - **C2**:接口单元超预算贪心拆分中,`_new_part` 后的装包调用被放在 `else` 分支——每个「开启新 part 的成员」的 hunk 不进入任何 part;且此前的 absorb 步骤已把这些 hunk 记入 claimed,残差兜底按 claimed 跳过不再接住,双重静默。现有回归 fixture 恰好两个成员各自单独超限,贪心分支零覆盖。
- **H4**:单元文件名清洗只替换 `/ \ :` 三个字符,`@GetMapping("/**")` 这类常见注解把 NTFS 非法字符带进文件名,Windows 写盘抛 `OSError [Errno 22]`,traceback + 退出码 1(违约契约的 0/1/2),且留下写了一半的产物。
- **M7**:新增文件(A)的 hunk 归属按「符号数」而非「hunk 数」构造,消费方按 hunk 下标取用——新增 controller 整文件单 hunk 时只有第 1 个符号拿到 hunk,路由分簇坍缩为单单元;覆盖虽由残差兜底不丢,但安全评审最关键产物(新增 controller)的分簇质量退化。
- **L6**:`--limit` 负值被 `max(0, …)` 静默成空页,与 0 不可区分;`--check` 与互斥 flag 同传被静默忽略。
- **M14(sast 侧)**:`diff_seed.py` 的 `git diff --name-status` 未关 quotepath,非 ASCII 路径带引号尾导致扩展名匹配失败,源文件静默从扫描种子消失——安全扫描的静默覆盖缺口,与 C1 同族、同修法,同批收口。

## What Changes

- **C1**:`diff_group.py` 的 git diff 调用加 `-c core.quotePath=false`,非 ASCII 路径以原样字节输出(`errors="replace"` 解码已兜底非 UTF-8 字节);补中文名 `.java` 文件端到端回归(解析出文件与 hunk、正常进分组)。
- **C2**:`_split_interface_budget` 去掉 `else`,新建 part 后**无条件**装入该成员的 files/hunks(与「单成员超上限」分支的既有正确形态对齐);补「各成员单独 ≤ 上限、合并 > 上限」的 hunk locator 无损回归,并修现有 fixture 使贪心分支被覆盖。
- **H4**:`_safe_name` 替换集从 `/ \ :` 扩为 `/ \ : * ? < > | "`(NTFS/Windows 非法字符全集);端到端 `@GetMapping("/**")` 场景可写盘、退出码合规。
- **M7**:A 文件的 hunk 归属改为每 hunk 覆盖全部符号(按 hunk 数构造,写入时过滤越界下标);新增 controller(整文件单 hunk)的路由分簇恢复多单元。
- **L6**:`--limit` 负值退出码 2 + 可操作报错;`--check` 与互斥 flag(`--base/--branch/--offset/--limit/--summary/--include-excluded`)同传时 stderr 显式提示。
- **M14**:`diff_seed.py` git 调用加 `-c core.quotepath=false`;非 ASCII 路径源文件不再静默漏出 seed。
- **卫生**:`diff_group.py` 死 import(`os`/`shutil`)与 `raw_text` 死参数链清理。
- 版本收口:`CHANGELOG.md` + `VERSION` bump。

## Capabilities

### New Capabilities

<!-- 无。 -->

### Modified Capabilities

- `security-design-review`:新增 requirement「非 ASCII 路径保真与 Windows 写盘安全」——git 采集与产物落盘对非 ASCII 路径、NTFS 非法字符的确定性保真行为(quotePath 关闭、文件名清洗闭集、`--limit` 误用拒绝);超预算拆分的覆盖无损已有既有 requirement 承诺(实现违约修复,以回归测试兑现,不改 requirement)。
- `sast-control-intake`:新增 requirement「diff 种子的非 ASCII 路径保真」——sast 侧扫描种子生成对非 ASCII 路径源文件的保真行为。

## Impact

- **代码**:`core/scripts/diff_group.py`(C1/C2/H4/M7/L6 + 卫生)、`core/scripts/diff_seed.py`(M14,sast 侧组件)。
- **测试**:`tests/test_diff_group.py`(新增中文路径、贪心拆分无损、非法字符、A 文件归属、负值拒绝用例;修现有拆分 fixture 的盲区)、`tests/test_sdr_tier.py`(回归)、sast 面确定性阶段测试(新增 quotepath 用例)、`tests/test_zero_deps.py` / `tests/test_no_compile_warnings.py`(顺手)。
- **契约**:无新增 CLI flag(quotePath 是 git 子命令配置,不是本脚本 flag);L6 是误用报错收紧,契约 lint(`tools/check_contracts.py`)面不变。
- **分发面**:零改动(两脚本均为已分发叶脚本的 bug 修复,三面壳调用行不变)。
- **版本**:`CHANGELOG.md` + `VERSION` bump(改 `.md`/脚本必 bump)。
