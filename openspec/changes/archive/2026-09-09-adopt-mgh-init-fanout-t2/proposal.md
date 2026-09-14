# Proposal: adopt-mgh-init-fanout-t2

> **人话序**
> **现象**:scout / T1 / T3 三个 fan-out tier 已由 `fanout_runner.py` 波次派发(一次 Bash + 重派、
> 零 LLM 回合、三级超时、熔断、孤儿清理);但 T2 综合在大仓超 `--max-aggregate-bytes` 触发 map-reduce 时,
> 其 **map 阶段**(按 category 拆 shard、每 shard 一个 partial-synthesis subagent)仍是编排器**手动逐 shard 扇出**
> ——逐次撰写任务消息、无超时接线、无 kill-stale、无熔断,和已淘汰的 T1/T3 手派旧形态同款。
> **根因**:t1/t3 采纳时把 T2(及 scout-merge)明确列为「同构可复制、后续 change」的非目标,map 阶段的派发态
> 从 `plan_aggregate.py` 直接漏给了编排器手派。**改什么**:`fanout_runner.py` 新增 `--tier t2`(map 阶段,
> 枚举 = `plan_aggregate.py --node t2`,任务模板/agent 各一),synthesis 提示词拆为 whole/partial/rollup 三态,
> rollup 仍是 map 之后单独一步;`plan_aggregate.py --node t2` stdout 补 `repo`/`failed_marker` 枚举字段;
> scout-merge 不动。**怎么验证**:单测 tier 参数化 + 契约 lint(`--tier t2` flag)+ 双宿主大仓真机冒烟
> (map 全 `.done`、rollup 产出 inventory 与手派路径 marker 集合等价)。

## Why

`adopt-mgh-init-fanout-t1-t3` 把 dispatcher 从 scout 专用泛化到 T1/T3 时,在 Non-Goals 里明确收窄:
「不治 … scout-merge shard 等其它 fanout 的采纳(同构可复制,后续 change)」。T2 的 map-reduce map 阶段
正是这个被遗留的同构 fan-out,至今仍是编排器逐波手派。承重经验对 T2 同样成立且尚未兑现:

| 经验(scout/t1/t3 已实证) | T2 map 阶段现状缺口 |
| --- | --- |
| 派发循环下沉纯代码波次(1 次 Bash + `partial:true` 重派,零 LLM 回合) | 编排器读 `plan_aggregate` stdout 逐 shard 手派,每 shard 一次 LLM 回合 + 弱模型漂移面 |
| 任务消息 = 固定模板 + 枚举 stdout 逐字填充 + spawn 前锚树拦截 | 逐次手写;`plan_aggregate --node t2` stdout 无 `repo` 锚、无 `failed_marker`,锚树校验无从谈起 |
| 三级超时不变式 + 宁慢勿杀 + sidecar + 宿主外直跑逃生门 | 均无接线;大仓 T1 记录数百簇超预算时同样会遭遇「杀→查盘→重派→又被杀」循环 |
| `--kill-stale` 孤儿清理 + 零推进熔断 | T2 手派的 shard 子进程无 liveness 登记、无熔断,被宿主硬杀后孤儿继续烧 token |
| opencode `mode: primary` fanout agent 克隆 + stdin 传消息 | T2 无 `init-synthesis-fanout` 克隆,headless spawn 不可寻址 |

且 T2 map 阶段与 t1/t3 的派发形态同构(枚举 stdout slim `pending[]` + per-unit 物化 `input_path` +
`.done`/`.failed` marker 真相源):每个 category shard 就是一个 isolation unit,partial-synthesis subagent 读
`input_path`、写 `checkpoint_path`、touch `done_marker`。泛化是复制已验证机制,非新设计。

## What Changes

- **`fanout_runner.py` 新增 `--tier t2`**(map 阶段):`--tier` 闭集 `scout|t1|t3|sdr` → `scout|t1|t2|t3|sdr`;
  t2 tier 的枚举脚本 = `plan_aggregate.py --node t2`(经 `--init-dir`/`--budget`/`--materialize` 转发),任务模板
  = `fanout/t2-task.md`,fanout agent = `init-synthesis-fanout`(partial-synthesis),占位符/锚树路径字段 =
  `input_path`/`checkpoint_path`/`done_marker`/`failed_marker` + `shard_id`/`categories`/`repo`。波次循环、ack
  状态机、三级超时、liveness、`--kill-stale`、零推进熔断、进度 sidecar(`fanout_progress.t2.json`)零改动复用
  (tier 无关代码路径不变)。
- **`plan_aggregate.py --node t2` stdout 补枚举字段**:顶层补 `repo`(取 `--init-dir` 上溯的 `<target>` 绝对根,
  与 `list_rule_jobs` 同源)+ 每 shard 补 `failed_marker`(与 `done_marker` 同目录 `.<id>.json.failed`);使 stdout
  成为 dispatcher 可消费的合法枚举(补齐 `repo` 锚树校验与 `.failed` 终态两个前提)。`needs_reduce=false` 路径
  (pending 空)逐字不变。
- **synthesis 提示词拆三态**:`stages/init-synthesis.md`(whole,单上下文,小仓路径)——逐字不变;新增
  `stages/init-synthesis-partial.md`(per-shard 有界 partial,产结构化 shard 摘要)+ `stages/init-synthesis-rollup.md`
  (仅吞各 shard 摘要,跨 category canonical/competing 归并 → 终态 inventory)。对应新增 opencode agent 克隆
  `init-synthesis-fanout.md`(mode primary)与 `init-synthesis-rollup.md`;claude 侧经 `--agents` inline JSON
  按同名装载(无新增落位文件)。
- **`init-stage/t2.md` fragment 改 dispatcher-first**:先跑 `plan_aggregate.py --node t2` 判 `needs_reduce`;
  `false` → 既有 single-context `init-synthesis` 逐字不变;`true` → 主路径一次 `Bash` 跑
  `fanout_runner.py --tier t2`(+ `partial:true` 重派、`--kill-stale` 前置、`--time-budget-ms` 接线)→ map 全
  `.done` 后,单一 `init-synthesis-rollup` 仅吞 `rollup.summary_paths` 写 `controls_inventory.json` +
  `synthesis.json.done`。退出码 2(宿主 CLI 不可用)→ 回退现状手派路径(原文保留);rollup 之后的
  `validate_inventory` 校验步不变。
- **`list_steps.py` + `discipline_core.py` t2 步契约面**:t2 步补 dispatcher 调用行 + `--tier t2` path_recipe
  (软时限重派纪律);`tools/check_contracts.py` 断言 `--tier t2` 等新 flag;`install.sh` 自检清单覆盖新模板 /
  agent 文件;版本号 bump。

## Capabilities

### New Capabilities

(无——`fanout-dispatch` 基座已存在,本 change 是其消费方从 scout/t1/t3/sdr 扩到 T2)

### Modified Capabilities

- `fanout-dispatch`:新增 t2 tier 条目挂入既有 TIERS 单点映射表——枚举脚本 `plan_aggregate.py`、任务模板
  `fanout/t2-task.md`、fanout agent `init-synthesis-fanout`、占位符/路径字段集、`repo`/`failed_marker` 枚举字段
  前置;map 阶段的波次/超时/熔断/liveness/`--kill-stale`/sidecar 零改动复用(tier 无关路径不变)。
- `control-discovery`:「Aggregate nodes enforce a hard request budget via map-reduce」requirement 增量——
  T2 map 阶段从「编排器为每 shard 扇出 partial-synthesis subagent」改为「dispatcher 以 `--tier t2` 波次驱动
  map 阶段 + 单一 rollup」;partial/rollup 提示词分态;scout-merge 手派语义逐字不变(非目标)。
- `request-context-budget`:「Dispatcher-driven tier keeps the orchestrator out of paging」scenario 的
  dispatcher 采纳 tier 集合从 `scout / t1 / t3` 扩为 `scout / t1 / t2 / t3`——T2 map 阶段编排器一次 `Bash` 调用
  (+重派),不手动翻页、不逐次撰写任务消息。

## Impact

- **代码**:`core/scripts/fanout_runner.py`(TIERS 增 t2 行)、`core/scripts/plan_aggregate.py`(stdout `repo` +
  `failed_marker`)、`core/prompts/fragments/fanout/t2-task.md` 新增、`core/prompts/stages/{init-synthesis-partial,
  init-synthesis-rollup}.md` 新增、`core/prompts/fragments/init-stage/t2.md` 派发段改写、`releases/opencode/agent/
  {init-synthesis-fanout,init-synthesis-rollup}.md` 新增、`core/scripts/list_steps.py` + `core/scripts/
  discipline_core.py`(t2 步契约面与 recipe)、`tools/check_contracts.py`(新 flag lint)、`install.sh`
  (镜像/自检清单)、`docs/man/mgh-init.md`(sidecar 名 + 手动直跑说明)、`tests/test_fanout_runner.py` +
  `tests/test_plan_aggregate.py` 扩展、CHANGELOG/VERSION bump。
- **既有安装项目**:重跑 `install.sh` 获新模板/agent/脚本;无磁盘 schema 变更(`run_config.json`/
  `init_manifest.json` 不动;`checkpoints/t2/shards/` 下 shard `.done` 是既有 `plan_aggregate` 已定义的中间
  marker,rollup 终态 `synthesis.json.done` 不变)。
- **风险**:① t2 枚举条件性(`needs_reduce`)——dispatcher 只在编排器判定 `needs_reduce=true` 后被调用,
  `needs_reduce=false`(pending 空)时 dispatcher 幂等空转、编排器走 single-context;需单测锚定「空 pending =
  良性 no-op,不误报 stalled」。② partial/rollup 提示词分态是忠实度风险点,需 R5.7 段 A 评估(baseline →
  blind A/B → 全新实例大仓首跑)。③ `checkpoints/t2/shards/` 中间 marker 与 rollup 终态 marker 的 resume 派生
  (t2 未完 = map 未完或 rollup 未完)须由 `resume_state.py --check` 校验磁盘自洽,不引入新步骤 id。
- **非目标**:不治 scout-merge shard 的 map-reduce 采纳(同为 `plan_aggregate --node scout-merge` 手派,同构
  可复制,后续 change);不改 marker/resume/翻页契约与 T1→T2/T2→T3 后续步骤语义;不治 T4(整仓一致性 pass,
  非 per-unit,fan-out 不适用;其聚合预算仍 P0 软边界,独立 concern);不引入 pip 依赖。
