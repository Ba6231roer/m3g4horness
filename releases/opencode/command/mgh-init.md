---
description: TODO stub. Discover existing security designs in a project (input-validation / sensitive-data masking wrappers, authz components, centralised controls) and emit agent-consumable rules. Generates opencode OR Claude Code rules — structurally different, selected via --format. Not yet implemented.
---

# /mgh-init — discover security designs → agent rules (TODO, opencode)

> **状态:TODO — 尚未实现。** 本文件仅为空命令骨架。
> 完整功能定义见仓库根 `task.260630.md`。

## 预期用途

扫描当前项目**存量代码**,识别团队已沉淀的可复用**安全设计**(输入校验封装、
敏感信息脱敏、权限校验组件等),生成 opencode 或 Claude Code 可直接消费的 **rules**。

### 预期参数(占位,尚未解析)
- `--target <dir>` — 待分析项目(默认 `.`)
- `--format opencode|claude` — 生成哪种 rules 结构(**必选**;两者结构不同,
  必须严格按目标 Agent 的 rules 格式学习后生成)
- `--out <path>` — rules 输出路径

> 产物供 `/mgh-sra`、`/mgh-blst` 消费。

## TODO
后续变更实现(见 `task.260630.md`)。当前收到本命令:打印"未实现"说明 + 参数表,
**不消耗 token**。
