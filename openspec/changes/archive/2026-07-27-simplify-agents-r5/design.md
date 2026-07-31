## Context

`AGENTS.md` R5(91–187 行,~97 行,10 子规则)是「Agent 工具命令稳定性」铁律,经多轮迭代堆叠。
**所有教训承重,不得删除**;问题纯结构:同一机制跨处复述、R5.7 塞 4 关切、R5.3(b) 过载、R5.5 ⑤ 孤儿、样板重复。

**硬约束**(不可破):
- 不改 R5.1–R5.10 编号 —— 全仓引用(`core/prompts/**`、R5.10 禁引清单、memory、changes)+ R5.10 本身管辖编号。
- `AGENTS.md` 与 `docs/` **不在分发集**(`tools/check_distributed_purity.py::SCAN_DIRS` L52–62 显式排除)→ 重组**零 CI 影响**。
- 不改任何规则**语义/强弱**,只重组表述与位置。

## Goals / Non-Goals

**Goals:**
- 去重跨处复述(长跑可恢复机制、opencode env 不继承、退出码 `0/1/2`)。
- 拆 R5.7(评估方法论 / hook 强制闭环)、修 R5.5 ⑤ 孤儿、减载 R5.3(b)。
- 加 R5 头部「强制面索引表」+ 合并「理由须随规保留」样板。
- 新增大白话配套文档(`docs/r5-plain-language.md`,dev-only)。
- **零教训删除**(以「current → new 映射表」逐条可核)。

**Non-Goals:**
- 不改编号、不改语义、不改代码/脚本/分发产物/install 行为。
- 不把 R5 重写为全新话题分组(保持演进式、可追溯)。

## Decisions

**D1 — 不改编号,只重组内容。** Why: R5.x 是全仓稳定锚点,改号=断链。Alt(重排为话题分组)→ 拒,断链成本 > 收益。

**D2 — 长跑可恢复机制:R5.4 为权威表述,R5.3(c) 改 1 行指针。** R5.3(c)(脚本侧 SHALL 支持 cache/续点/`--time-budget-ms`/`partial:true`)与 R5.4(编排器侧 per-call timeout / re-dispatch `--resume` / NEVER wrapper loop)是同一机制两面,现 `--time-budget-ms`/`partial:true`/exit-0 逐字重复。合并入 R5.4,R5.3(c) 留指针占号。**全教训保留**:零全损 / 跨宿主 / 不假设单次跑完 / NEVER wrapper loop / opencode timeout 须启动前就绪 / per-call timeout SHALL 传。

**D3 — opencode env 不继承:单归宿放 R5.7 hook 段,删 R5.4 悬空前向引用。** R5.4 末「mid-session export 不被插件进程继承,承 R5.7 `MGH_*_ACTIVE` 同根因」是前向悬空引用(读者到 R5.7 才能解)。单归宿消除。

**D4 — R5.7 拆同号两段(不增子号):**
- 段 A **「评估方法论」**:baseline(无该提示词跑 ≥5 次 capture 失败模式,variance 是指标)→ blind A/B(pass rate/tokens)→ 新命令 A 实例写、全新 B 实例大仓首跑、观察漂移 → 新失败模式回灌本节。
- 段 B **「hook 强制闭环」**:每 `mgh-*` #1 违例 MUST 配 runtime hook(install 注入、**双端对等**:claude `.claude/settings.json` PreToolUse + opencode `.opencode/plugins/*.ts` `tool.execute.before`);`.ts` = opencode 宿主原生胶水(Bun 运行、非 pip,R2 定性),仅事件归一化+管道+据退出码阻断;判定逻辑单一来源 `block_adhoc_scripts.py`(双端字节级 parity,`tests/test_opencode_hook_parity.py`);**可靠性边界**:插件进程不继承 mid-session bash env(`shell.ts::shellEnv` 只读 `process.env`)→ `MGH_*_ACTIVE` 仅启动前就绪才激活,未激活 fail-soft(命令壳明线 + R5.9 兜底);hook 缺席 = CI fail(对齐 R5.8);当前兑现 `block-adhoc-scripts`(四运行域 `MGH_{INIT,SAST,SRA,SRR}_ACTIVE`)。
Why: 4 无关关切挤一 bullet 是全节最难读处;同号拆段保稳定。Alt(拆 R5.7+R5.8 新号)→ 拒,断链现有 R5.8/5.9/5.10。

**D5 — R5.3(b) 减载,拆显式子项(不挪窝)。** 保留主体「CLI I/O 契约」(stdout/stderr 严格分流、退出码 `0/1/2`、幂等、禁 TTY、闭集参数拒歧义+可操作报错、`--dry-run`、`--offset` 分页)。fan-out 枚举 + 绝对输出路径 + `MGH_TARGET` 子树守卫 拆为 R5.3(b) 下显式子项「**扇出与路径**」(脚本产 `pending[]` 含 `checkpoint_path`/`rule_path`/`done_marker` 均 `Path.resolve()` 绝对;编排器逐字透传、subagent 逐字写;NEVER 拼路径/占位符/相对路径;`MGH_TARGET` 供 hook 判树,越子树 fail-loud exit 2)。Why: 现 ~8 规则一墙,拆子项给视觉结构;fan-out 是脚本产清单的契约属脚本侧,不挪 R5.2。R5.2 保留「编排器对清单迭代、NEVER 挖 JSON」视角,删与之重复的 NEVER 拼路径表述(统一在 R5.3(b) 子项,R5.2 指针)。

**D6 — 修 R5.5 ⑤ 孤儿:折回 R5.5 父项下,对齐 ①–④ indent。** 现 ⑤(L146)是顶层 bullet,脱离「指令性 MD 措辞」语境,纯格式 bug。

**D7 — R5 头部加「强制面索引表」(表格,承 R3):**

| 规则           | 强制机制                               | 入口                                        |
| ------------ | ---------------------------------- | ----------------------------------------- |
| R5.1 契约 lint | 机械化 flag 存在断言                      | `tools/check_contracts.py`                |
| R5.2 黑盒纪律    | runtime hook 阻断越权 Write/微脚本        | `block_adhoc_scripts.py` + `MGH_*_ACTIVE` |
| R5.3 脚本稳定性   | 自包含 + I/O 契约(脚本自验)                 | 回归测 `tests/`                              |
| R5.4 长跑可观测   | per-call `timeout` + `--resume` 重派 | 编排器 Bash 纪律                               |
| R5.7 hook 闭环 | 双端 runtime hook + CI               | `block_adhoc_scripts.py` + CI             |
| R5.8 自检+回归   | install 自检 + 回归测                   | `install.sh` + `tests/`                   |
| R5.9 边界校验    | `--check` fail-loud(exit 2)        | 各产出者 `--check`                            |
| R5.10 分发纯净   | purity lint                        | `tools/check_distributed_purity.py`       |

Why: 5 条强制规则散落,无整体图;表给一眼索引。

**D8 — 合并「理由须随规保留/勿软化」样板为 R5 前言一行。** 前言加:「各子规则的 `理由〔…〕` 括号是承重教训,MUST 随规保留、NEVER 软化。」 删 R5.2/R5.4/R5.5①/R5.10 各自重复的「须随规保留/勿软化」尾巴,**保留**各自 `理由〔…〕` 内容。

**D9 — 修剪纯回声溯源。** `承 R5.x` 若仅指回前文无新增信息(如 R5.4 末「承 R5.2」已被 NEVER wrapper loop 表达)→ 删;若携带溯源价值(如 R5.2「承 `harden-mgh-init-orchestration-discipline` FD1」带失败形状来源)→ 留。Why: AGENTS.md 是研发仓手册,溯源链是研发语境正当资产(R5.10 不扫 AGENTS.md),但纯回声仍冗余,按「是否新增信息」裁。

**D10 — 大白话配套文档 `docs/r5-plain-language.md`(dev-only,不分发)。** 逐条 R5.1–R5.10 大白话:这条说什么、为什么有、违反会怎样、哪个工具/hook 兜底。面向新人 onboarding。`docs/` 在 SCAN_DIRS 之外,不进分发、不膨胀 AGENTS.md(承 R3)。**亦作教训的第二副本**,防去重后单点灭失。

### Current → New 映射表(apply 时逐条核对,防丢)

| 现位置(line) | 教训内容 | 新归宿 |
|---|---|---|
| R5.3(c) L126–128 | cache/续点/soft-deadline/`partial:true` | **合并入 R5.4**;R5.3(c)→1 行指针 |
| R5.4 L129–136 | per-call timeout/`--resume`/NEVER wrapper/opencode timeout 就绪 | R5.4(权威) |
| R5.4 L133 悬空 | env 不继承 `承 R5.7` | **删悬空**,内容单归宿 R5.7 段 B |
| R5.7 L151–164 | 方法论 + hook + .ts 定性 + env 边界 | R5.7 段 A(方法论)+ 段 B(hook) |
| R5.3(b) L115–125 | I/O 契约 + fan-out + 路径 + MGH_TARGET | R5.3(b) 主体 + 子项「扇出与路径」 |
| R5.5 ⑤ L146 | 禁令清楚则不举例 | R5.5 ⑤(折回父项) |
| R5.2/R5.4/R5.5①/R5.10 尾 | 「理由须随规保留」样板 | R5 前言单声明;`理由〔…〕` 各留 |
| 退出码 `0/1/2` 多处 | R5.3(b)/5.3(c)/5.4/5.9 | R5.3(b) 主体 + R5.9 各 1 次,余删 |

## Risks / Trade-offs

- **[重组误删教训 / 改语义]** → 映射表逐条核 + apply 后 `git diff AGENTS.md` 人工 review;AGENTS.md 不进 CI 扫描无自动门,靠人工 + 映射表。
- **[去重后某教训成单点,未来误删即灭失]** → D10 大白话文档作人类可读第二副本,双处冗余防单点。
- **[合并样板后「勿软化」语气减弱]** → 前言声明用 RFC-2119(`MUST 保留 / NEVER 软化`)保机器可检语气。
- **[R5.7 拆段后现存 `承 R5.7` 引用歧义]** → 现有引用多指 hook 部分;拆段后 R5.7 仍含 hook 段,不断链。

## Migration Plan

1. **D10 大白话文档**(零风险,独立产物,立即交付)。
2. **AGENTS.md R5 重组**(D1–D9),按映射表逐块改。
3. `git diff AGENTS.md`,逐条核对每条原教训有归宿 + 语义未变。
4. `CHANGELOG.md` 记一笔。

## Open Questions

- **Q1**:AGENTS.md 改动是否触发 R5.8「bump 版本号」?倾向 **不触发**(非分发产物;版本 bump 针对分发命令壳 VERSION 字段),CHANGELOG 记一笔。待维护者确认。
- **Q2**:「强制面索引表」(D7)放 R5 头部还是 `docs/`?倾向 **R5 头部**(与规则同处,索引化)。待确认。
