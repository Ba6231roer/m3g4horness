---
description: TODO stub. Design business-coupled security test cases from interface logic + mgh-init rules — e.g. acquire different user accounts, swap auth material, and probe broken object/functional authorization. Not yet implemented.
---

# /mgh-blst — 业务安全测试案例设计 (TODO, opencode)

> **状态:TODO — 尚未实现。** 本文件仅为空命令骨架。
> 完整功能定义见仓库根 `task.260630.md`。

## 预期用途

结合**业务接口逻辑**与 `/mgh-init` 产出的 rules,设计与**业务功能强耦合**的
安全测试案例(如获取不同用户账户、替换 auth 信息后重放以检验越权)。

### 预期参数(占位,尚未解析)
- `--target <dir>` — 业务代码仓
- `--rules <path>` — `/mgh-init` 产出的 rules
- `--api <endpoint>` — 聚焦某接口/模块(可选)

## TODO
后续变更实现(见 `task.260630.md`)。当前收到本命令:打印"未实现"说明 + 参数表,
**不消耗 token**。
