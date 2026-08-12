## MODIFIED Requirements

### Requirement: 壳经 REQUIRED SUB-SKILL 引用 fragment,不内联重复纪律正文

`mgh-init.md`(claude + opencode 两壳)SHALL 经 `REQUIRED SUB-SKILL: Use orchestrator-discipline`
标记引用上述 fragment,并从壳正文中**移除**被 fragment 覆盖的宿主无关纪律正文块(三条 `NEVER` 边界
详述、implementation-intention recipe 详述、fan-out 刚性三元组详述)。壳 SHALL 保留一句指引(「编排器
= 宿主 agent;完整纪律见 orchestrator-discipline fragment」)+ 壳内 init 专属内容(stage 流、确切
`list_*`/`resume_state.py` 调用行、产物清单、`MGH_INIT_ACTIVE`/哨兵、init 边界披露)。两壳引用同一个
fragment(零正文 drift)。

**stage 流细节的载体**(自本变更起):mgh-init stage 流的**逐步细节正文**(step 0–8 的 run_config 写、
哨兵生命周期、codegraph 检测、discover/scout/T1/T2/T3/T4 的 fan-out 刚性三元组与 `--check` 校验、
聚合硬阈值、scout 级联失效落账、fan-out 失败落账等)SHALL 抽进 init 专属 fragment
`core/prompts/fragments/init-stage-flow.md`,壳经 `REQUIRED SUB-SKILL: Use init-stage-flow` 引用;
壳内**仅保留** parse-args + SUB-SKILL 指令 + Stage→组件表(紧凑) + Resume/cache + Output + Always
disclose(精简)。两壳引用**同一个** `init-stage-flow.md`(零正文 drift;壳体 claude/opencode 差异
留在壳,stage 流正文 host-agnostic 由壳侧的 `.claude/mgh-core` / `.opencode/mgh-core` 前缀覆盖)。

**壳 token 预算**(自本变更起):mgh-init 两壳经 `tools/measure_prompts.py` 实测 `mid_tokens` 各
**SHALL ≤ 5,000 tok**(R5.6 硬上限;壳 = 触发轮 USER 首条消息、primacy 区,lost-in-the-middle + 防回归,
据 `docs/opencode-context-mechanics.md` §1/§6)。**编排器 fragments**(init-stage-flow + orchestrator-discipline)
SHALL **逐个评估**单次 Read 轮尺寸是否结构良好(**不**强制求和 ≤ N);三者磁盘 `mid_tokens` 合计 SHALL ≤ ~10,000
作**防漂移** lint 上限(标注根据 = 磁盘大小防漂移,**非**运行时叠加占用——opencode 下壳与各 fragment 均为单次
lazy Read 的 USER 历史项、非每轮 system 税,见 `docs/opencode-context-mechanics.md` §1/§6)。

#### Scenario: 两壳引用 orchestrator-discipline + init-stage-flow 两 fragment 而非内联

- **WHEN** 审阅 `releases/claude-code/commands/mgh-init.md` 与 `releases/opencode/command/mgh-init.md`
- **THEN** 两壳均含 `REQUIRED SUB-SKILL: Use orchestrator-discipline` 与 `REQUIRED SUB-SKILL: Use init-stage-flow`;
  且均**不**再内联 implementation-intention recipe 详述块与三条 `NEVER` 边界详述块(在 orchestrator-discipline)
  及 stage 流逐步细节正文(在 init-stage-flow)

#### Scenario: init 专属调用面与表留在壳内

- **WHEN** 审阅两壳的 parse-args / Stage→组件表 / Resume·cache / Output / Always disclose 段
- **THEN** 确切脚本名(`discover_controls.py`/`list_clusters.py`/`list_scout_batches.py`/`list_rule_jobs.py`/
  `resume_state.py`/`write_runconfig.py` 等)、确切 flag、产物路径、`MGH_INIT_ACTIVE`/`.mgh-init/.active` 哨兵
  指针、`list_steps.py` 调用面仍在壳内(未随 stage 流细节一并移出)

#### Scenario: 壳 token 实测 ≤ 5,000 tok

- **WHEN** 运行 `py tools/measure_prompts.py releases/claude-code/commands/mgh-init.md releases/opencode/command/mgh-init.md`
- **THEN** 两文件 `mid_tokens` 各 ≤ 5,000;另对 `init-stage-flow.md` + `orchestrator-discipline.md` 逐个报告单文件尺寸
  (无硬求和上限);三者磁盘 `mid_tokens` 合计 ≤ ~10,000(防漂移 lint,据 `docs/opencode-context-mechanics.md` §6)

#### Scenario: init-stage-flow fragment 通过分发纯净性 lint

- **WHEN** 运行 `tools/check_distributed_purity.py`
- **THEN** `init-stage-flow.md` 不含 `R5.x`/`FDn`/`Dn`/变更夹名/`承 R5`/`范式锚点`/「本仓」dev-meta
  (操作性语义如 `--check`/退出码 2/`NEVER`/确切脚本名保留)

#### Scenario: 两壳 stage 流正文逐字一致(零 drift)

- **WHEN** 审阅两壳各自引用的 `init-stage-flow.md`
- **THEN** 两壳引用**同一文件**(`core/prompts/fragments/init-stage-flow.md` 单一真相源);无 claude/opencode
  各自内联的 stage 流正文副本

## ADDED Requirements

### Requirement: mgh-init stage 流细节抽 init-stage-flow fragment,行为零变化

SHALL 存在 `core/prompts/fragments/init-stage-flow.md`,承载 mgh-init 编排流 step 0–8 的逐步细节正文。
该 fragment 是 **init 专属**(非宿主无关——含 init 专属脚本名/产物名/fan-out 三元组),但**两壳共用同一份**
(claude 与 opencode 仅壳体措辞差异,stage 流正文 host-agnostic)。该 fragment SHALL **完整搬移**当前壳内
stage 流的全部承重内容——不删任何 I/O 契约节点、fan-out 路径确定性、`--check` 闸门、resume 语义、已修 bug
防线(NTFS `::` 文件名 sanitize、盘符根漂移防护、UTF-8 BOM 剥离、scout-incomplete-gate、`.failed` 终态、
级联失效)。壳内 Stage→组件表折叠为紧凑「script inventory | subagent inventory」(仅名;绝对路径由
`list_steps.py` 运行时给);「Deterministic invocation (Bash)」整块删除,仅 2 个未在 flow 内联的逃生口
(大文件切片 `chunk_sources.py` form、`resume_state.py --invalidate-stale` 配方)迁回原生步骤。
「Always disclose」压为 5 条规范要点,细节落 `init_manifest.json::boundaries[]` / `report.md`。

#### Scenario: fragment 承载完整 stage 流(零内容丢失)

- **WHEN** 审阅 `init-stage-flow.md`
- **THEN** 其覆盖 step 0(parse + self-check + run_config 原子写 + 哨兵生命周期 + MGH_TARGET + codegraph 检测)、
  step 1(--merge)、step 2(i1 discover + 校验)、step 3(init-survey opt)、step 3b(SCOUT FAN-OUT 含聚合硬阈值
  预判 + 级联失效 + 终态)、step 3c(init-resolve codegraph-gated)、step 4(T1 FAN-OUT + scout 闸门)、
  step 4b(T1→T2 边界闸门 BOM+形状)、step 5(T2 + 聚合硬阈值 + validate_inventory)、step 6(T3 FAN-OUT)、
  step 6b(ASSEMBLE/LINT)、step 7(T4)、step 8(i4 manifest + report + 失败/scout_merged 落账 + 收尾 rm 哨兵);
  每步保留确切脚本调用、确切 flag、`--check` 闸门、fan-out 三元组、`checkpoint_path`/`rule_path` 绝对路径语义

#### Scenario: 壳删 Bash 目录块但保留逃生口

- **WHEN** 审阅两壳
- **THEN** 两壳**无**「### Deterministic invocation (Bash)」整块目录;但大文件切片 `chunk_sources.py` 调用 form
  与 `resume_state.py --invalidate-stale` 配方仍在(迁入 stage 流对应步骤或 Resume/cache 段)

#### Scenario: mgh-init 流水线可观测行为零变化

- **WHEN** 默认运行 `/mgh-init` 与 `/mgh-init --resume`
- **THEN** 产物路径、产物 schema(`controls_candidates.json`/`clusters.json`/`controls_inventory.json`/
  `init_manifest.json`/`report.md`/rules)、stdout schema、退出码、fan-out 单元边界、`--check` 闸门行为
  与变更前逐字一致(无回归);`init_manifest.json::version` 保持 7(无 schema 变更)

### Requirement: 「本仓」dev-meta 修正为「目标项目」

两壳顶部编排器声明中的「本仓」措辞(指 m3g4horness 研发仓)SHALL 改为「目标项目」——该措辞出现在
**分发给目标 agent** 的提示词中,目标 agent 可能误读为「m3g4horness 研发仓」而非其所在的目标项目,
造成歧义。R5.10 第 7 类 dev-meta(指本研发仓时的「本仓」)由 `tools/check_distributed_purity.py` 守护;
本变更 SHALL 使该措辞在两壳顶部消失。

#### Scenario: 两壳顶部无「本仓」措辞

- **WHEN** 审阅 `releases/claude-code/commands/mgh-init.md` 与 `releases/opencode/command/mgh-init.md` 顶部编排器声明
- **THEN** 「本仓」改为「目标项目」(或等价无歧义措辞);`tools/check_distributed_purity.py` 对该 dev-meta 通过
