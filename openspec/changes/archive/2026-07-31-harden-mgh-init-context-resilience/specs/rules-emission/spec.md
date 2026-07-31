## ADDED Requirements

### Requirement: init-rulewriter returns a bounded ack to the orchestrator

`init-rulewriter`(T3 per-category rulewriter)subagent 的**最终回传消息** SHALL 是**单条有界 ack**——取值之一
`ok <绝对 rule_path> <category>`、`oversize <绝对 rule_path> <category>`、`failed <简短原因>`——且 **MUST NOT** 回显规则
正文、inventory 记录体、或源码(承 control-discovery「Subagent return-to-orchestrator is a bounded ack」的横切纪律,
专治 T3 fan-out 完成时编排器上下文随 category 数单调膨胀)。该 ack 仅为存活/成功信号;编排器 SHALL 据 ack + `.done`
标记判断该 category 成败,MUST NOT 为继续 fan-out 而内联 `Read` 规则/详述文件回编排器上下文。该契约 SHALL 同时写入
`core/prompts/stages/init-rulewriter.md` 与双壳 `agents/init-rulewriter.md` 的 Hard-constraints 段(双重防线)。
`assemble_rules.py --check` 纯净性 lint、T3 fan-out 绝对 `rule_path` 契约(承 rules-emission 既有要求)**保持不变**。

#### Scenario: rulewriter prompt declares the bounded ack

- **WHEN** 审阅 `core/prompts/stages/init-rulewriter.md`
- **THEN** 该提示词含一个 Return-to-orchestrator 段,声明最终消息为单条有界 ack(`ok <abs rule_path> <category>` 等)、
  NEVER 回显规则正文/inventory 记录体

#### Scenario: Orchestrator does not inline-read rules to continue fan-out

- **WHEN** 一个 init-rulewriter subagent 完成并回传 `ok <abs rule_path> <category>`,编排器进入下一 category
- **THEN** 编排器仅记 ack 为成功信号 + 探 `.done`;它 **不** `Read` 该规则/详述文件内联回上下文

#### Scenario: Shell agent definition mirrors the ack contract

- **WHEN** 审阅 claude-code 与 opencode 两份 `agents/init-rulewriter.md` 的 Hard-constraints 段
- **THEN** 两壳均显式声明 subagent 回传为有界 ack、NEVER 回显正文(双壳与 prompt 双重防线)
