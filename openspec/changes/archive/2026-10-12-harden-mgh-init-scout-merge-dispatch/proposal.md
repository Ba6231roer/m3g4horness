# Proposal — harden-mgh-init-scout-merge-dispatch

> **人话序**:大仓实跑 `/mgh-init` 时,「侦察结果合并」这一步(scout-merge,把多个侦察批次
> 各自发现的候选控制去重合并成一份总表)出了两类事故:① 它切出来的单个数据分片有 265KB /
> 269KB,而企业内网可用的大模型上下文窗口只有 150K token——单个分片就可能撑爆一次请求;
> 而且现行规则允许「单批记录超大也照发」。② 这一步是全流水线唯一还让主控模型**手工派发**
> 子代理的聚合节点:实测模型找到了子代理定义文件,却又跑去系统全局目录(`/root/.config/opencode/`)
> 继续找,最后向人弹权限请求,无人值守运行被打断。根因很清楚:预算默认值太宽(256KB)+
> 超大分片不设硬上限 + 手派路径天然给模型留了「自己猜路径」的空间——而 T2 综合步骤早在
> 上一轮改造里已经验证过正确形态:由确定性脚本逐字给子代理传绝对路径与代理名,模型零猜测。
> 本次改三件事:聚合预算默认收紧到 96KB(按最坏情况的 token 换算,单次请求输入 ≈ 4 万
> token 量级,150K 窗口绰绰有余);scout-merge 分片设**硬上限**(超大的批次按候选粒度确定性
> 再切,单条候选瘦身,瘦身后仍超就报错退出、一个都不发);把 scout-merge 完整接入既有波次
> 调度器,派发形态与 T2 逐步一致。另外附一份「已跑挂的现场如何退回切分点重来」的操作
> runbook(删哪些文件、改哪处配置、怎么验证)。验证方式:确定性单测全覆盖新行为 + 在
> 同一台目标仓上按 runbook 清理后 `--resume` 复跑 scout-merge 段。

## Why

企业内网模型上下文窗口只有 ~150K token,而 `/mgh-init` 的 scout-merge 聚合节点当前
(a) 默认输入预算 256KB 且**单个侦察批记录超预算时不拆分、原样派发**(实跑切出
265KB/269KB 分片),(b) 仍是**编排器手派** subagent 的最后一个聚合节点——任务消息由模型
逐次撰写,导致实测「找到 agent 定义又去全局目录翻找、最终向人要权限」的无人值守中断。
T2 聚合节点已经走过同形演化(marker-aware 枚举器 + `fanout_runner --tier t2` + 固定任务
模板 + 绝对路径逐字透传),scout-merge 当年被显式豁免为「hand-paged non-goal」;手派引发的
路径/定义漂移故障使该豁免的前提失效。

## What Changes

- **聚合预算默认收紧**:`--max-aggregate-bytes` 默认值 256KB → **96KB**(与
  `--scout-batch-bytes` 默认同值;按仓内 token 启发式的保守换算,CJK 密集内容最坏
  ~2.5 字节/token → 单分片输入 ≤ ~40K token,叠加 stage 提示词与回传仍远低于 120K 目标)。
  同步 `plan_aggregate.DEFAULT_BUDGET`、`write_runconfig` / `write_ut_runconfig` /
  `render_report` 的默认常量与三面壳 `mgh-init` 预算文案。flag 仍可显式覆盖。
- **scout-merge 分片硬上限**(**BREAKING**,反转「scout-merge envelope 逐字节不变」既有
  承诺):单批记录自身超预算时,不再 warn+原样派发,而是**按候选(candidate)粒度**确定性
  贪心再切为 ≤ 预算的分片;单条候选仍超预算 → 确定性散文瘦身投影(截
  `evidence_snippet`/描述类字段,锚点与结构字段永不截,与 T2 既有瘦身同形);瘦身后仍超 →
  退出码 2 fail-loud、零派发。不变式:**任何被派发的 scout-merge 分片输入 ≤ 预算**。
- **scout-merge 接入波次调度器**(镜像 t2 tier 全套):
  - `fanout_runner.py --tier` 闭集扩为 `scout|t1|t2|t3|sdr|scout-merge`;
  - `plan_aggregate.py --node scout-merge` 变 **marker-aware**(pending 排除 `.done`/
    `.failed` 终态、stdout 补 `total/done/failed`、每 shard 项补 `failed_marker`、支持
    `--include-failed`),供 dispatcher 收敛重列;
  - 新任务模板 `core/prompts/fragments/fanout/scout-merge-task.md` + 新 fanout agent
    `init-scout-merge-fanout`(opencode `mode: primary` 克隆 / claude inline `--agents`
    同名 / dsh tier mount)——任务消息由模板逐字填充,绝对路径逐字透传,**模型不再撰写
    派发消息、不再有机会翻目录**;
  - 新 stage 提示词 `init-scout-merge-partial.md` / `init-scout-merge-rollup.md`;rollup
    仍是编排器单步(吞各 shard 摘要 → 写 `scout_candidates.json` + `merge.json.done`);
  - 手派路径降级为「宿主 CLI 不可用(exit 2 + recipe)」时的回退,行为与 dispatcher 等价;
  - `install.sh` 自检、`tools/gen_dsh_tiers.py` 闭集、`tools/check_contracts.py`、三面壳
    (claude/opencode/dsh)`mgh-init` 的 tier 清单与 scout 步流程、`init-stage/scout.md`
    fragment、`list_steps.py` 同步。
- **在跑现场的 re-entry runbook**(非规格,交付进 design + tasks):如何把已切出 3 个大
  shard 的进行中 run 退回「切分点」——删 `<target>/.mgh-init/inputs/scout-merge/`、
  `checkpoints/scout/shards/`、`checkpoints/scout/merge.json[.done]`、
  `scout_candidates.json`(如已产出),把 `run_config.json` 的 `budgets.max_aggregate_bytes`
  改为新默认,`--resume` 后由 `resume_state.py` 磁盘派生自动回到 scout 步的
  plan_aggregate 闸门;侦察批产物(`checkpoints/scout/<batch>.json`)保留不重跑。

## Capabilities

### New Capabilities

(无——全部落在两个既有能力上)

### Modified Capabilities

- `request-context-budget`:聚合预算默认值 256KB → 96KB(flag 表 + 默认场景改写);
  scout-merge 聚合节点从「分片后 oversize 批仍可整发」升级为「每个派发分片强制 ≤ 预算」
  (并入「No silent context overflow」对聚合节点的既有要求的具体化)。
- `fanout-dispatch`:`--tier` 闭集新增 `scout-merge` 成员,派发形态镜像 t2 tier 需求段
  (marker-aware 枚举、固定模板、fanout agent 克隆、三宿主接线、needs_reduce=false 时
  幂等空转、锚树 path-drift 拦截)。

## Impact

- **脚本**:`core/scripts/plan_aggregate.py`(scout-merge 打包器重写 + marker-aware 推广 +
  瘦身复用)、`fanout_runner.py`(TIERS 表增行 + oversize recipe 文案)、
  `write_runconfig.py` / `write_ut_runconfig.py` / `render_report.py`(默认常量)、
  `list_steps.py`(scout 步调用行)。
- **提示词/壳**:`core/prompts/stages/init-scout-merge.md`(删「P0 软边界/oversize 原样回传」
  旧段,改 map-reduce + dispatcher 消费形态)+ 新增 partial/rollup 两份;
  `core/prompts/fragments/init-stage/scout.md`;三面壳 `mgh-init`(预算文案、stage→组件表、
  fanout tier 清单)。
- **agent/分发面**:`releases/{claude-code/agents,opencode/agent,dsh/agents}/` 新增
  `init-scout-merge-fanout`(+ opencode/dsh 的 `init-scout-merge-rollup`);
  `tools/gen_dsh_tiers.py` `REQUIRED_TIERS`;`install.sh` 自检清单。
- **测试**:`test_plan_aggregate`、`test_fanout_runner`(新 tier 用例,harness 层
  `--cooldown-s 0` 约)、`test_gen_dsh_tiers`、`test_init_runtime` / `test_list_steps` /
  `test_dsh_command_surface`、契约与纯净 lint(`check_contracts` /
  `check_distributed_purity` / prompt budget)。
- **不动**:scout-tier-gate 的完成判据(`merge.json.done` 仍是终态凭证)、`merge_scout.py`
  fold-in 与级联失效逻辑、T1/scout 批 reader 面、scout-merge single-context 小仓路径
  (`needs_reduce=false` 行为不变)。
