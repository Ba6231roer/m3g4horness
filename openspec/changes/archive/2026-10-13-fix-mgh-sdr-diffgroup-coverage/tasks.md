# Tasks — fix-mgh-sdr-diffgroup-coverage

> 每组先红后绿:新增回归用例在修复前 MUST 复现缺陷(红),修复后转绿。缺陷位置与修法以
> 2026-10-13 评审明细为准,实施时以实际代码为准(评审基线 HEAD `6e6ac63`)。

## 1. C1 — quotePath 关闭(diff_group.py)

- [x] 1.1 在 `_git` 封装层为全部 git 调用统一注入 `-c core.quotePath=false`(单点;NEVER 依赖环境变量)
- [x] 1.2 新增回归:临时 git 仓 + 中文文件名 `.java` 变更(默认 git 配置,NEVER 预设 quotePath)→ 解析出该文件、hunk 完整、进入分组;修复前用例红
- [x] 1.3 新增回归:唯一变更文件为中文路径 → `empty:false` + 计数正确(修复前:`empty:true` 静默丢失)

## 2. C2 — 贪心拆分无条件装包(diff_group.py `_split_interface_budget`)

- [x] 2.1 去掉 `_fill(acc, c)` 外层 `else`;`_new_part` 后无条件装入当前成员(与单成员超限分支同形)
- [x] 2.2 修现有 `test_interface_budget_splits_parts` fixture 盲区:保留原两成员单独超限用例,新增「各成员单独 ≤ cap、合并 > cap」用例(参考形态:双成员各 1880B、合并 2648B、cap=2264)
- [x] 2.3 新增断言:hunk locator 并集 == 拆分前全集(无损);part 路由标签与装载成员一致;修复前用例红

## 3. H4 — 文件名清洗闭集(diff_group.py `_safe_name`)

- [x] 3.1 替换集扩为 `/ \ : * ? < > | "`;Windows 保留名/结尾点空格既有处理不动
- [x] 3.2 新增回归:含 `@GetMapping("/**")` 的变更在 Windows 形态下写盘成功、退出码与 stdout 合约形态(修复前:`OSError [Errno 22]` 裸崩)
- [x] 3.3 断言:清洗只影响落盘文件名,slice 正文与 grouping.json 中的路由串不变

## 4. M7 — A 文件 hunk 归属量纲(diff_group.py)

- [x] 4.1 A 文件归属改为每 hunk 覆盖全部符号(`[list(range(len(syms)))] * len(hunks)` 语义),写入侧过滤越界下标
- [x] 4.2 新增回归:新增 controller(多路由方法、整文件单 hunk)→ 各路由方法进 changed/anchors,分组单元数 > 1(修复前坍缩为单单元)

## 5. L6 — 误用显式拒绝(diff_group.py)

- [x] 5.1 `--limit < 0` → 退出码 2 + stderr 可操作报错(不再 clamp 成空页)
- [x] 5.2 `--check` 与互斥 flag 同传 → stderr 逐个提示被忽略旗标(退出语义不变)
- [x] 5.3 新增两条误用回归

## 6. M14 — sast 侧种子保真(diff_seed.py)

- [x] 6.1 `git diff --name-status` 调用加 `-c core.quotePath=false`(与 1.1 同形同写法)
- [x] 6.2 `SOURCE_EXT` 去重;`deleted[]` 适用与 `seed[]` 同一的源码扩展名过滤
- [x] 6.3 新增回归:非 ASCII 路径 `.java` 源文件进 `seed[]`、无引号尾伪条目;删除的非 ASCII 源文件按同一口径进 `deleted[]`

## 7. 卫生(diff_group.py)

- [x] 7.1 删死 import(`os`/`shutil`;删除前以引用扫描确认零使用)
- [x] 7.2 删 `raw_text` 死参数链并同步调用点

## 8. 收口

- [x] 8.1 定向回归:`python tests/test_diff_group.py`、`python tests/test_sdr_tier.py`、sast 面确定性阶段测试、`python tests/test_zero_deps.py`、`python tests/test_no_compile_warnings.py`
- [x] 8.2 `python tools/check_contracts.py`(确认无新 flag 断言破坏)、`python tools/check_distributed_purity.py`
- [x] 8.3 `CHANGELOG.md` + `VERSION` bump
