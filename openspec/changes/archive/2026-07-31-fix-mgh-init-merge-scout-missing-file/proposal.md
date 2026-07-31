## Why

`merge_scout.py::_normalize` 对 `file` 字段**直索引**(`c["file"]`),而同函数内的 `category`
字段已是 `.get` + 缺字段 `return None`(由调用方 skip-with-warn)的容错模式。当某条 scout
candidate 缺 `file` 字段时,`_normalize` 抛 `KeyError: "file"` 并**整条 merge 中止**——而非像
缺 `category` 那样优雅跳过。正常流程下 `merge_scout.py --check` 已挡缺 `file` 候选;只有在 `--check`
被绕行时(如上下文压力下编排器跳过 merge 闸门、或手工造的畸形 `scout_candidates.json`)才会撞上。
本变更补脚本侧鲁棒性(defense-in-depth),把 `file` 对齐 `category` 的容错范式。

## What Changes

- `merge_scout.py::_normalize`:`file` 由直索引 `c["file"]` 改为与 `category` 同一 None-return
  守卫(`if not c.get("category") or not c.get("file"): return None`),`file` 字段取值改 `.get`。
- `_normalize` docstring 更新:返回 `None` 的条件由「缺 `category`」泛化为「缺任一必填字段
  (`category` / `file`)」。
- 调用方 skip-with-warn 措辞(`[merge_scout] warn: scout candidate #i … missing category - skipped`)
  泛化为「missing required field (category|file)」,如实指出缺哪个字段。
- 扫一遍 `_normalize` 其余字段:当前仅 `file` 为直索引,其余已是 `.get`;确保无其它直索引必填字段。

## Capabilities

### New Capabilities
<!-- 无新增 capability -->

### Modified Capabilities
- `control-discovery`: merge 归一路径(`merge_scout.py::_normalize`)对缺必填字段的 scout candidate
  SHALL 优雅跳过(skip + warn)而非抛异常中止,与既有 `category` 容错范式对齐(把 `file` 纳入同一守卫)。

## Impact

- **代码**:`core/scripts/merge_scout.py`(`_normalize` 函数体 + docstring + 调用方 warn 措辞)。
  该脚本是单一真相源,经 `install.sh` 镜像到目标项目的 `.claude/mgh-core/scripts/` 与 opencode 对应位置。
- **契约**:`_normalize` 返回 `None` 的语义从「仅缺 category」扩为「缺 category 或 file」;不改
  `merge_scout.py` 的 CLI I/O 契约(stdout JSON / stderr 诊断 / 退出码 0|1|2 全不变)。
- **测试**:`tests/test_deterministic.py` 增「缺 file 的 candidate → skip + warn、不抛异常」回归用例。
- **依赖**:无。零运行时依赖不变(承 R2,纯标准库)。
