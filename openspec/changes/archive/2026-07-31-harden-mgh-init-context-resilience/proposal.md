## Why

`/mgh-init` 真机运行在**不确定上下文上限**的宿主上(claude / opencode),偶发「上下文过大 → 任务停止」。
当前唯一的恢复手段是**人工 `/compact` 后手输「继续」**,这违反工具使用设想,且更糟的是——
**`/compact` 与 opencode 自动压缩(~95% 触发)都是模型生成的摘要**,可能丢掉 `mgh-init` 命令壳灌入的
**编排纪律系统提示词**(硬边界 / fan-out 三元组 / `NEVER` 拼路径),导致续跑时**执行路径偏离**。

`mgh-init` 已有**很厚**的上下文韧性底子(per-tier `list_*` 的 done/pending、`.done` resume gating、
discover cache/续点/`partial:true`、`--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes`、
subagent 隔离)。但全面审计后发现**四条未被覆盖的缝隙**,正是「停止 + 难恢复」的根因:

1. **无编排器级「我在哪 / 下一步」确定性出口。** 8 步流水的「当前步骤」目前由**编排器对话记忆**判定——
   这恰好是 compact / crash / 新 session 会**丢**的东西。各 `list_*` 只报单 tier 的 done/pending,没有一个
   单一确定性查询能回答「跨全流程,哪步完了、下一步确切做什么、带绝对路径」。
2. **subagent 回传大小无规。** 9 份 stage 提示词全部只规约「写哪个文件 + touch `.done`」,**对「回传给编排器
   的最终消息」集体沉默**(审计确认)。于是 subagent 可能**回显整份记录体**回编排器;尤其 `init-synthesis`(T2)、
   `init-scout-merge` 两个聚合节点的 checkpoint 文件**就是全量聚合记录**,若被编排器内联读回,上下文随 fan-out
   **单调膨胀**。`--max-aggregate-bytes` 只管 subagent 的**输入**,不管编排器**读回**。
3. **聚合节点(T2 / scout-merge)为「P0 软边界」——仅披露,无硬阈值。** 当簇/批很多时,T2 一次请求吞全部 T1
   记录,是**剩余的真实单请求溢出风险**(shell 已自认未对聚合节点提供硬阈值)。
4. **无 compaction-aware 设计。** 没有任何地方声明「所有可恢复流水线状态都在磁盘 `.mgh-init/`,对话记忆只是
   缓存不是真相源」,也没告诉编排器:上下文吃紧时**应当干净停止 + 新 session 用 `/mgh-init --resume` 续**,
   而非依赖会丢系统提示词的人工 `/compact`。

## What Changes

统一原则:**把 `.mgh-init/` 当作进度的唯一真相源,「我在哪 / 下一步」永远从磁盘重派生,绝不依赖对话记忆。**
由此 compact / crash / 新 session 三种中断**坍缩为同一种恢复路径**——「读磁盘状态 → 继续」,系统提示词由新
session 重灌、进度由磁盘重派生,绕开「compact 丢提示词」根因。按「治本(可恢复)→ 治标(少溢出)」分四层:

- **Layer 1 — 编排器级 re-entrant resume state(治本 / 用户 1.1)**:新增确定性叶脚本
  `core/scripts/resume_state.py`,读 `.mgh-init/` 全部产物 + 跨 tier `.done` 标记,stdout 吐**极简**状态
  `{step, tiers{discover/scout/t1/t2/t3/t4 各自 done/total}, next_action{kind, cmd_hint 或 spawn_hint,
  absolute_paths}, resumable}`(stderr 诊断、退出码 0/1/2、零依赖、自定位、utf-8、任意 cwd,承 R5.3)。
  起步段(step 0)把**本次调用 flag** 原子写入 `<target>/.mgh-init/run_config.json`(`format`/`scope`/`scout`/
  `codegraph`/`skip-consistency` 等),使 `--resume` **无需用户重输 flag** 即可纯从磁盘续。
- **Layer 2 — subagent 回传大小纪律(治标 / 用户 1.2 + 审计发现 #1#2)**:9 份 `init-*.md` stage 提示词 +
  双壳 `agents/init-*.md` 增 **Return-to-orchestrator** 段:回传**仅**一条有界 ack(`ok <abs checkpoint_path>
  <count>` 或 `failed <reason>` / 聚合节点 `ok <abs path> <total> <merged>`),**NEVER** 回显记录体。同步把
  survey/audit/scout-merge/synthesis/T4 仍用的 `<target>` 相对路径统一为 fan-out 已有的「绝对路径逐字」
  契约(审计发现 #2:路径处理当前跨 stage 不一致)。
- **Layer 3 — 聚合节点硬阈值 + map-reduce 降级(治标 / 用户 1.2 + 兑现 shell 已披露的 P0 软边界 TODO)**:
  把 `--max-aggregate-bytes` 从「披露 + 建议 `--scope`/`--merge`」升级为**硬闸门**——T2/scout-merge 输入
  ≤ 预算时行为不变(单上下文);**超预算**时自动按 category(或 batch 簇)分桶 → 每桶一个 bounded
  partial-synthesis subagent → 单一 rollup subagent 在**仅各桶摘要**上归并(两段 map-reduce,每请求有界)。
  闸门 + 降级由确定性叶脚本 `core/scripts/plan_aggregate.py`(或既有 `list_*` 扩展)决策与物化。
- **Layer 4 — compaction-aware 编排(治本 / 用户 1.3 + 直击「compact 丢提示词」恐惧)**:两份 `mgh-init.md`
  增「Re-entrancy & compaction」段,声明:① 所有可恢复状态在磁盘,对话记忆非真相源;② **resume / compact 后
  第一步 SHALL 调 `resume_state.py` 重派生 step + next_action**,NEVER 靠「记得自己在第几步」;③ 上下文吃紧时
  **MAY 干净停止**(跑完当前 fan-out 波次、落 `.done`)→ 新 session `/mgh-init --resume` 续,**优于**人工 `/compact`
  (后者摘要可能丢编排纪律);④ 既有 per-call `timeout` + discover `partial:true` 纪律不变。

## Capabilities

### New Capabilities
<!-- 无新能力。四层均落在既有 control-discovery(编排/resume/聚合/T2)/ rules-emission(T3 回传)内。 -->

### Modified Capabilities
- `control-discovery`:编排器「当前步骤 + 下一步」从**对话记忆**升级为**确定性 `resume_state.py` 产出的磁盘
  重派生状态**(re-entrant);`--resume` 支持纯从 `.mgh-init/run_config.json` + `.done` 续,无需重输 flag;
  T2/scout-merge 聚合输入从「P0 软边界(披露)」升级为**硬阈值 + 自动 map-reduce 降级**;所有 init stage
  subagent 回传统一为有界 ack(绝不回显记录体);新增「compaction-aware 编排」要求(状态磁盘化、resume/compact
  后先 `resume_state.py`)。discover 的 cache/续点/`partial:true`/原子写 **不变**。
- `rules-emission`:`init-rulewriter`(T3)回传统一为有界 ack(`ok <abs rule_path> <category>`),`assemble_rules.py
  --check` 纯净性 lint 不变;T3 fan-out 路径契约不变。

## Impact

- **新脚本**(`core/scripts/`):`resume_state.py`(跨 tier 状态机 + next_action)、`plan_aggregate.py`(聚合分桶
  决策 + 物化)。全 R2 零依赖、自定位 `sys.path`、utf-8、stdout=JSON / stderr=诊断、退出码 `0/1/2`、任意 cwd、
  `--help` 即契约(承 R5.1/R5.3)。`tools/check_contracts.py` 须学其 flag(双壳镜像)。
- **改提示词**:9 份 `core/prompts/stages/init-*.md` 增 Return-to-orchestrator 段 + 路径绝对化;双壳
  `agents/init-*.md` Hard-constraints 同步(双重防线)。
- **改命令壳**:两份 `mgh-init.md`(claude + opencode)起步段(写 `run_config.json`)、新增 Re-entrancy &
  compaction 段、resume 流程首步调 `resume_state.py`、T2 步骤注 map-reduce 降级。
- **改契约**:新增 `core/contracts/init/resume-state.md` + `aggregate-sharding.md`;`unit-inputs.md` /
  `clusters.md` 等不动。
- **改 hook / 单测**:hook 运行域**无扩展**(resume_state/plan_aggregate 是既有 `core/scripts` 白名单内的叶子
  脚本);新增 `tests/test_resume_state.py`、`test_plan_aggregate.py`;既有 `test_list_*` 扩 ack 字段断言。
- **改 AGENTS.md**:R5.4 长跑可恢复段补「编排器级 re-entrant resume state(磁盘为进度真相源,跨 compact/crash/
  新 session)」为权威机制之一;R5.5① recipe 补「需知当前步骤 → `resume_state.py`,NEVER 靠对话记忆」。
- **依赖**:零新增运行时依赖(R2)。不 import `vvaharness`。
- **BREAKING / 风险**:`run_config.json` 是新增磁盘产物(随 `.mgh-init/` gitignore);聚合 map-reduce 仅在
  **超预算**时触发(小仓行为逐字不变);回传 ack 改变的是 stage 提示词对「最终消息」的规约(编排器原本就只该
  探 `.done`,不依赖回传内容)。design 覆盖:map-reduce 两段性、resume_state 对 optional/codepath 分支
  (scout/survey/resolve/t4/--merge/--no-scout)的 step 判定、run_config 与既有 `init_manifest.json`(终态)的
  边界、ack 契约 schema。无既有磁盘 schema 迁移;`/mgh-init` 既有产物与功能不变。
