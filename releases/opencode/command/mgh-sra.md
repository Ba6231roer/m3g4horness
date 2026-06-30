---
description: TODO stub. After an openspec 'propose', run this to analyse and augment specs/tasks with security-design content. If mgh-init rules exist, the added tasks guide which rules to read. Not yet implemented.
---

# /mgh-sra — openspec 安全设计补充 (TODO, opencode)

> **状态:TODO — 尚未实现。** 本文件仅为空命令骨架。
> 完整功能定义见仓库根 `task.260630.md`。

## 预期用途

在 openspec **`propose` 之后**运行,对生成的 specs / tasks 做**安全设计补充分析**。

### 与 `/mgh-init` 的协作
若存在 `/mgh-init` 产出的 rules,补充的 **tasks** 应**显式引导查阅对应 rules**
(如"实现 X 时须遵循 rules 中记录的权限校验封装")。

### 预期参数(占位,尚未解析)
- `--change <name>` — openspec 变更名(默认最新)
- `--rules <path>` — `/mgh-init` 产出的 rules(可选)

## TODO
后续变更实现(见 `task.260630.md`)。当前收到本命令:打印"未实现"说明 + 参数表,
**不消耗 token**。
