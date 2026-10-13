# fix-mgh-init-prompts-contracts-sync

> **人话序**:收官批。2026-10-13 全流程深度评审(维护者私有文档区)在 mgh-init 的 stage 提示词
> 与 I/O 契约文档层还留着一组失实,外加两个跨批遗留。**核心是 `--merge` 模式没有任何可执行
> 路径**:三面壳参数表声明它可用、resume 状态机会把编排器路由到 `merge` 步,但被指向的
> `merge_inventories.py` 全仓不存在——编排器拿到「脚本不存在」只能即兴用大模型徒手合并
> inventory,没有闸门、没有确定性去重。评审给了两条路:(a) 实现一个确定性合并脚本(工作量大,
> 且没有任何真实用户诉求背书);(b) 三面拒绝该模式(传入即退出码 2 + 指认「无确定性实现」)+
> 清掉全部死引用(壳 flag 表/流程清单/状态机 merge 步/fragment/契约行/规格措辞)。**本批选
> (b)**:fail-loud、诚实、零新面;(a) 若未来有真实诉求可独立立项。其余:base agent 与 fanout
> 克隆的回传 ack 枚举漂移(批次 4 删了克隆侧的 oversize ack 而 base 面没删,导致 parity 回归
> 测试现在就是红的——本批把 base 面同步删,并从规格的 ack 取值枚举中移除 oversize);约十处
> stage 提示词失实(把源码证据字段列为「中文化对象」会诱导弱模型翻译代码行、init-survey 用
> repo 相对路径且读白名单与第 1 步互斥、init-rulewriter 缺读侧三件套、init-induct 未覆盖 pack
> 形态与 canonical 8 类等);约十处契约文档失实(cluster_id 公式写 sha8 实为 sha1 前 12、
> scout-plan 引用不存在的 flag 名、candidates 的幻影 source 值、unit-inputs 的陈旧 done 检测
> 描述等);两处笔误。验证 = parity 测试转绿 + merge 拒绝红绿测 + 提示词/契约/分发面 lint
> 四件套 + 定向回归面全绿。

## Why

批次 1-6 已归档(HEAD 153c5b9,VERSION 0.1.73);本批全部发现按内容在 HEAD 核定位确认:

| # | 项 | 现态证据 |
| --- | --- | --- |
| H11 | `--merge` 无可执行路径(拍板项) | 三面壳 flag 表/描述/流程清单、write_runconfig、resume_state merge 短路、list_steps merge 行、step-manifest merge 行、init-stage/merge.md fragment 全链在;`merge_inventories.py` 不存在 |
| 三.15 | base agent ack 枚举漂移 | `TestAgentCloneParity` 在 HEAD 即红;opencode+claude 两面 base agent(init-scout/induct/rulewriter)仍枚举 `oversize <绝对路径>` ack |
| P1 | evidence_snippet 列为中文化对象 | `init-scout.md:136`(与「单行安全子串」契约矛盾,弱模型会翻译代码行);init-resolve 同形 |
| P2 | init-induct 未覆盖 Form B pack + canonical 8 类 | `init-induct.md` 无 pack 指引;schema 段 category 未列规范 8 类 |
| P3 | init-survey 相对路径 + 白名单互斥 | 第 1 步 `Read .mgh-init/...`(repo 相对);白名单「仅 evidence_files」禁读第 1 步要求的两文件 |
| P4 | init-rulewriter 缺读侧三件套 | 13 份中唯一无「锚 repo 根/NEVER 越界/Bash 搜索同禁」段 |
| P5 | init-rules-consistency「managed block」措辞 | 与 Task-4 详述文件矛盾 |
| P6 | rules-format 两文件 `--check` 覆盖面夸大 | 「fails loud on any leak」实况 FORBIDDEN_TOKENS 有意排除裸 tier 词等 |
| P7 | init-scout `regex_known[]` 幽灵输入字段 | 全链路无 producer |
| C1-C9 | 契约失实批 | clusters.md sha8 公式失真(实为 4 段 + sha1 前 12);scout-plan.md 幻影 flag 名(`--scout-batch-bytes`,真名 `--batch-bytes`);candidates.md 幻影 source `regex+scout`;unit-inputs.md「done 检测读 unit 字段」陈旧(批次 5 已改 forward marker)+ bytes 按 tier 漂移未分列;manifest.md「unit record」形状无产出者;三枚举器契约缺 `--materialize/--offset/--limit/--orch-budget-bytes`/分页四字段;resolved.md additive 无确定性出口;step-manifest/resume-state 词表含 merge |
| L1-L2 | 笔误 | t2.md `openmode`;controls-context.md `中和` 中英混杂 |
| — | 孤儿 fragment 结论订正 | 评审称 self-verification/severity-guidance/exhaustiveness 无加载者;核查发现 sast-deepdive 分发面(opencode+claude)引用它们——**非孤儿,保留**,订正记录 |

不修(留维护者):批次 4 拍板项 A(edit: deny live 验证需人工参与)、拍板项 B(第 10 类基线
186 行全家族扫尾,交接三.14 推荐独立小批)。

## What Changes

1. **H11 选 (b)——`--merge` 全链拒绝**:write_runconfig 保留 argparse 声明但传入即退出码 2 +
   recipe;run_config 不再记录 `mode`/`merge_partials_dir`;resume_state 删 merge 短路分支 +
   步词表去 merge;list_steps 删 merge 行;删 init-stage/merge.md;三面壳 flag 表/描述/流程清单
   去 `--merge`(传之 = 未知 flag,argparse exit 2);step-manifest/resume-state 契约词表与行同步;
   规格 7+1 处 MODIFIED(含全部「建议 --scope+--merge」advice 措辞改「--scope 分模块,产物独立」)。
2. **ack 枚举收口(三.15)**:base agent 六面(opencode+claude 的 init-scout/induct/rulewriter)删
   `oversize` ack 枚举(与批次 4 克隆侧同判);规格 bounded-ack requirement 同步移除;
   dispatcher `_parse_ack` 容错不动。
3. **提示词七修**(P1-P7,见上表)。
4. **契约九修**(C1-C9,以源码实况为准;init-artifacts-reference 既有「字段解释以源码为准」
   requirement 的执行面,无新 delta)。
5. **两处笔误**(L1-L2)。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `control-discovery`: 7 条 requirement——「Scoped and partial-merge analysis」(--merge 显式
  拒绝)、「Persisted run configuration for stateless resume」(不记录 merge)、「Re-entrant
  orchestrator resume state (disk as single source of truth)」(步词表去 merge + 场景改述)、
  「Bounded single-pass scan performance on large repos」(advice 措辞)、「Disclose scout
  coverage and residual blind spot」(advice 措辞)、「Fan-out waves run to completion without
  scale-driven user interruption」(pre-run advice 措辞)、「Subagent return-to-orchestrator is
  a bounded ack」(oversize 移出 ack 取值)。
- `request-context-budget`: 1 条 requirement——「Aggregate-stage inputs are bounded or
  disclosed」(advice 措辞)。

## Impact

- **涉改面**:脚本 3(write_runconfig/resume_state/list_steps)+ 壳 ×3 + agent 定义六面 +
  stage 提示词 8 + fragments(merge.md 删、t2/controls-context 笔误)+ 契约 10 + 规格 delta 2
  能力;VERSION bump + CHANGELOG。
- **测试**:TestAgentCloneParity 转绿;merge 拒绝红绿测(write_runconfig/resume_state/
  list_steps);test_distributed_md_purity / test_recipe_visibility / test_dsh_command_surface /
  test_agent_stage_contract / test_init_flag_table_contract + budget/purity/contracts lints +
  test_resume_state / test_list_steps / test_write_runconfig 定向面。
- **风险与边界**:壳改动触发三面镜像纪律与 budget lint;fragment 删除涉及 install 分发集
  (install 自检 inventory 断言需核对不点名 merge.md);批次 4 拍板项 A/B 不在本批。
