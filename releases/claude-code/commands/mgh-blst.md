---
description: TODO stub. Design business-coupled security test cases from interface logic + mgh-init rules — e.g. acquire different user accounts, swap auth material, and probe broken object/functional authorization. Not yet implemented.
allowed-tools: Read, Glob, Grep, Bash, Agent, Write, Edit
---

# /mgh-blst — 业务安全测试案例设计 (TODO)

> **状态:TODO — 尚未实现。** 本文件仅为空命令骨架。
> 完整功能定义见仓库根 [`task.260630.md`](../../../task.260630.md)。

## 预期用途

结合**业务接口逻辑**与 `/mgh-init` 产出的 rules,设计与**业务功能强耦合**的
安全测试案例(区别于通用漏洞清单)。

### 典型场景(示例)
- **越权(IDOR / 横向 & 纵向)**:如何获取不同用户的账户/凭据,在接口测试时
  **替换对应 auth 信息**后重放,校验是否可访问他人资源
- 基于业务流的**多步组合**(下单→支付→退款各环节的鉴权边界)
- 利用 rules 中记录的校验封装,识别**绕过点**(哪些接口未走统一校验)

### 预期参数(占位,尚未解析)
- `--target <dir>` — 业务代码仓
- `--rules <path>` — `/mgh-init` 产出的 rules
- `--api <endpoint>` — 聚焦某接口/模块(可选)

## TODO
在后续变更中实现(见 `task.260630.md`)。当前收到本命令时:打印"未实现"说明 +
参数表 + 指向 `task.260630.md`,**不消耗 token**。
