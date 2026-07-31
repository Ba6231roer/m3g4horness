# Implementation Tasks

> 顺序依 design 的 Migration Plan:**先做大白话文档(零风险 + 作教训第二副本,保护后续去重)**,再重组 AGENTS.md R5,最后按映射表核对零丢失。
> 所有任务对齐 spec `agents-md-discipline` 三 requirement。

## 1. 大白话配套文档(D10 · 零风险 · 先交付)

- [x] 1.1 创建 `docs/r5-plain-language.md`,逐条 R5.1–R5.10 用大白话写**四要素**:这条说什么 / 为什么有 / 违反会怎样 / 哪个工具或 hook 兜底。
- [x] 1.2 覆盖自检:文档含全部 10 子规则(R5.1–R5.10),每条四要素齐全;`docs/` 确认在 `tools/check_distributed_purity.py::SCAN_DIRS` 之外(不分发)。

## 2. AGENTS.md R5 重组(D1–D9 · 原地改)

- [x] 2.1 **D8 + D7**:R5 段前言加「各子规则 `理由〔…〕` 括号 MUST 随规保留、NEVER 软化」单声明;头部加「强制面索引表」(rule → 机制 → 入口)。
- [x] 2.2 **D2**:合并 R5.3(c) 长跑可恢复内容入 R5.4 为权威表述;R5.3(c) 改 1 行指针「→ 见 R5.4」。
- [x] 2.3 **D3**:删 R5.4 末悬空「env 不继承,承 R5.7」前向引用,改干净指针「env 继承边界见 R5.7 段 B」;内容单归宿 R5.7 段 B。
- [x] 2.4 **D4**:拆 R5.7 为同号两段——段 A「评估方法论」+ 段 B「hook 强制闭环」(不增子号)。
- [x] 2.5 **D5**:R5.3(b) fan-out 提升为子项「扇出与路径」;主体留 CLI I/O 契约;R5.2 加指针到该子项。
- [x] 2.6 **D6**:折回 R5.5 ⑤「禁令清楚则不举例」对齐 ①–④ indent(修孤儿格式 bug)。
- [x] 2.7 **D9**:修剪纯回声 `承 R5.x`(R5.4 末「承 R5.2」、R5.10「承 R5.7」删;有溯源价值如 R5.2 FD1、R5.3(b) fanout 留)。
- [x] 2.8 退出码 `0/1/2` 去重:定义仅 R5.3(b) 主体 1 次(原 4 处);R5.4「退出码 0」、R5.9/R5.3(b) 子项「退出码 2」为具体值非定义,保留。

## 3. 验收与核对(零教训丢失 · 对齐 refactor-safety req)

- [x] 3.1 按 design「current → new 映射表」逐条核:resumability 单归宿 R5.4 ✓、env 不继承单归宿 R5.7 段 B ✓、全部教训有归宿。
- [x] 3.2 `git diff AGENTS.md` 人工 review:仅 8 处预期改动、无 collateral、语义未变、编号 R5.1–R5.10 未重排未删号。
- [x] 3.3 行数核对:**实际 R5 段 97 → ~114 行**(未达 design 估的 70–75)。原因:强制面索引表(~13 行)抵消去重收益。真实收益是可读性(去重 + 拆段 + 索引 + 修孤儿),非行数;详见 CHANGELOG `Dev-meta`。如需压行数可删表(表亦存于 `docs/r5-plain-language.md`),但表对齐 R3「表格优先」、治「5 强制规则散落无索引」,建议留。
- [x] 3.4 `openspec validate simplify-agents-r5 --strict` 通过 ✓;`CHANGELOG.md` `[Unreleased]` 记一笔 ✓。
- [x] 3.5 (Open Question Q1) 决策:AGENTS.md 改动**不**触发 R5.8 分发版本 bump —— 非分发产物(SCAN_DIRS 排除;无 VERSION 字段,版本追踪仅 CHANGELOG)。已记于 CHANGELOG `Dev-meta`。
