## ADDED Requirements

### Requirement: 装配边界的清单↔规则覆盖对账门与缺口披露

`assemble_rules.py`(两 format 共用)SHALL 在纯净 lint 之外做覆盖对账:`controls_inventory.json`
中每条控制的 evidence token(路径或文件名级)MUST 出现在其类别对应的规则文件文本中
(opencode:`<rules-dir>/<cat>.md`;claude:`.claude/rules/security-*.md` 中该类别文件;
匹配 = 整路径或文件名在文本中出现,复用锚点解析共享模块的归一化)。任一控制未呈现 →
opencode 面**不写盘**、退出码 2,stderr 按 category 输出未呈现计数与首 N(默认 5)控制名,
编排器按既有 lint 违例同形路径回 T3 修;claude 面退出码 2 并列同名清单。通过时
(或显式放宽时)opencode 受管块 SHALL 追加一行覆盖披露(形如「覆盖:M/N 控制已入规则,
缺口清单见运行报告」),幂等重写;`--accept-coverage-gaps` 是唯一放宽开关:仍执行对账、
仍写披露行、缺口计数与类别 SHALL 落运行报告/台账(boundaries),NEVER 静默放行。

#### Scenario: 全呈现通过且披露

inventory 45 条控制全部在对应类别文件中命中证据 → 退出码 0,受管块出现
「覆盖:45/45」披露行,重复装配幂等(行内容不变)。

#### Scenario: 未呈现即拒写盘

inventory 691 条控制仅 45 条命中 → 退出码 2,AGENTS.md 未被写入,stderr 含
`missing=646` 与按 category 计数、首 5 个未呈现控制名;编排器按 lint 违例同形回 T3。

#### Scenario: 显式放宽仍披露

同上状态传 `--accept-coverage-gaps` → 写盘进行,受管块披露「覆盖:45/691」,台账
boundaries 记 `coverage_gaps_accepted` 与按 category 计数。

#### Scenario: claude 面同判

claude format 下同样对账;未呈现 → 退出码 2 并输出同名清单(不涉及 AGENTS.md 写盘)。
