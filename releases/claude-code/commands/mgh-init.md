---
description: TODO stub. Discover existing security designs in a project (input-validation / sensitive-data masking wrappers, authz components, centralised controls) and emit agent-consumable rules. Generates opencode OR Claude Code rules — structurally different, selected via --format. Not yet implemented.
allowed-tools: Read, Glob, Grep, Bash, Agent, Write, Edit
---

# /mgh-init — discover security designs → agent rules (TODO)

> **状态:TODO — 尚未实现。** 本文件仅为空命令骨架。
> 完整功能定义见仓库根 [`task.260630.md`](../../../task.260630.md)。

## 预期用途

扫描当前项目**存量代码**,识别团队已沉淀的可复用**安全设计**,据此生成 AI 编程
Agent(opencode 或 Claude Code)可直接消费的 **rules**。

### 识别对象(示例)
- **输入校验**封装:统一 sanitizer / validator / schema 守卫的方法或注解
- **敏感信息脱敏**辅助:卡号/身份证/手机号/凭据的 mask/redact 工具
- **权限校验**组件:拦截器、过滤器、`@PreAuthorize` 等注解、鉴权 AOP
- 其它集中式安全控制(加密、限流、防重放等)

### 预期参数(占位,尚未解析)
- `--target <dir>` — 待分析项目(默认 `.`)
- `--format opencode|claude` — 生成哪种 rules 结构(**必选**;两者结构不同,
  必须严格按目标 Agent 的 rules 格式学习后生成,不可混用)
- `--out <path>` — rules 输出路径

> 产物供 `/mgh-sra`(补充 specs/tasks 时引导读取哪些 rules)与 `/mgh-blst`
> (设计业务安全测试案例)消费。

## TODO
在后续变更中实现(见 `task.260630.md`)。当前收到本命令时:打印"未实现"说明 +
参数表 + 指向 `task.260630.md`,**不消耗 token、不做任何分析**。
