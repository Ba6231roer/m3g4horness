# Design: adopt-mgh-init-fanout-t2

## Context

`fanout_runner.py` 已是 tier-aware 确定性 dispatcher(`--tier scout|t1|t3|sdr`),TIERS 单点映射表
(枚举脚本 / 任务模板 / 占位符集 / fanout agent / path_fields)驱动共享的波次循环、ack 状态机、三级超时、
liveness 登记、`--kill-stale`、零推进熔断、进度 sidecar,无 per-tier 分支。T2 综合在大仓超
`--max-aggregate-bytes` 时由 `plan_aggregate.py --node t2` 做硬预算 map-reduce:按 `category` 切成有界
shard、物化 per-shard 输入,然后**编排器逐 shard 手派** partial-synthesis subagent + 单一 rollup。
本 change 只把 T2 的 **map 阶段**切到 dispatcher;rollup 仍为单独一步。scout-merge(同为
`plan_aggregate --node scout-merge`)保持手派(非目标)。

## Goals / Non-Goals

**Goals:**
- T2 map 阶段继承 dispatcher 全套机制:纯代码波次、任务模板逐字填充、spawn 前锚树拦截、三级超时、
  熔断、孤儿清理、sidecar——消除「逐 shard 一次 LLM 回合 + 弱模型漂移面 + 无超时/熔断」的旧形态。
- synthesis 提示词分态,让 partial(per-shard)与 rollup(跨 shard)各有唯一行为定义(当前是共用 whole 提示词、
  手写任务、欠规约)。
- `plan_aggregate.py --node t2` stdout 成为合法 fanout 枚举(补 `repo`/`failed_marker`)。

**Non-Goals:**
- 不采纳 scout-merge shard(上游于 T1,同构可复制,后续 change)。
- 不治 T4(整仓一致性 pass,非 per-unit,fan-out 不适用;其聚合预算仍 P0 软边界,独立 concern)。
- 不改 marker/resume/翻页契约与 T1→T2 / T2→T3 后续步骤语义;不引入 pip 依赖。

## Decisions

### D1 — t2 是 TIERS 增行(map 阶段),rollup 留在编排器一步

`fanout_runner.py` 是纯 map dispatcher(每单元一个终态 marker)。T2 map 阶段 = 每 category shard 一个
partial-synthesis subagent,是纯 map,直接增 TIERS 行即可复用波次/ack/超时/熔断/liveness/sidecar。
rollup 的终态 marker(`checkpoints/t2/synthesis.json.done`)≠ 各 shard 的 `.done` marker,不能当普通单元
完成;且 rollup 是单一 reduce(非波次),天然属于编排器一步(与 t3 波次后的 `assemble` 步同构)。

- 备选(否决):给 fanout_runner 加两段 map-reduce 模式(map 波次 + 自动触发 rollup)。会为一个 tier 复杂化
  波次机、模糊「dispatcher=纯 map、每单元终态 marker」不变式,且 rollup 输入(`rollup.summary_paths` 全集)
  与 per-unit 输入不同构。

### D2 — t2 枚举复用 `plan_aggregate.py --node t2`,不新写 list 脚本

`plan_aggregate.py --node t2 --materialize` 已产 `pending[]`(shard_id/input_path/checkpoint_path/
done_marker/bytes/oversize/categories),接近 `list_*` 形态。补顶层 `repo` + 每 shard `failed_marker` +
**t2 排终态**(见下)即成为合法 marker-aware 枚举器,不重写分桶逻辑。

- **D2a(实现期发现,补 scope)**:plan_aggregate 是纯 planner,`pending[]` 恒含全部 shard、不读
  `checkpoints/t2/shards/` 的 `.done`/`.failed` marker。dispatcher 波次循环靠「重列 → pending 收缩」收敛
  (与 `list_clusters`/`list_rule_jobs` 同形),且零推进熔断依赖枚举器上报 marker 派生计数;缺此则每波
  重派已完成 shard、两波后误熔断。故 `--node t2`(仅 t2;scout-merge 保持手派、非目标不动)在
  `needs_reduce=true` 时:顶补 `total`/`done`/`failed`(marker 派生),`pending[]` 排除已有
  `.done`/`.failed` 的 shard;`summary_paths`/`shards` 仍为全集(rollup 吞全部摘要 + boundaries 披露)。
  `needs_reduce=false` 路径逐字不变。

- 备选(否决):新 `list_synthesis_shards.py` 包装 plan_aggregate。多一份脚本、分桶逻辑拆两处;`needs_reduce`
  决策本就住在 plan_aggregate,复用更省。
- 备选(否决):dispatcher 侧 spawn 前跳过已 `.done` unit。改 tier 无关共享代码路径,scout/t1/t3/sdr
  同受波及,回归面宽;且不改枚举器则熔断信号仍失真。

### D3 — `repo` 由 `--init-dir` 派生,不加 `--target`

`.mgh-init` 恒在 `<target>/.mgh-init` 下(契约),故 `repo = init_dir.resolve().parent` 精确。`failed_marker`
= `done_marker` 同目录 `.<shard_id>.json.failed`(与 `list_rule_jobs` 的 `.<cat>.<fmt>.json.failed` 同构)。

- 备选(否决):给 plan_aggregate 加 `--target`。plan_aggregate 已锚定 `--init-dir`,父目录派生零成本、无歧义;
  `list_rule_jobs` 用 `--target` 是因为它锚的是 `--inventory`(可任意路径),非本场景。

### D4 — `needs_reduce` 闸门在编排器侧,dispatcher 不感知

`init-stage/t2.md` 本就先跑 `plan_aggregate.py --node t2` 判 `needs_reduce`。dispatcher 只在
`needs_reduce=true` 时被调用;`needs_reduce=false`(pending 空)时 dispatcher 幂等空转(0 单元、
`partial:false`,不误报 `stalled`),但编排器已改走 single-context `init-synthesis`。这保持
「dispatcher 的 pending 即真相源」模型不变,不引入「single-context 信号」的新 stdout 分支。

### D5 — t2 的 sidecar/liveness 家目录锚定 `<init-dir>`

sidecar/liveness 家目录 = `plan_path.parent`(tier 无关代码,`_write_sidecar`/`_write_liveness` 用
`plan_path.parent`)。scout/t1/t3 的 `plan_arg` 指向 `<init-dir>` 下的 plan 产物文件,parent 即 `<init-dir>`。
t2 无单一 plan 产物文件,故仿 sdr 的 `grouping.json` 特例:以 `--init-dir/run_config.json` 为 `plan_path`
(`run_config.json` 恒在 `<init-dir>` 下),使 `plan_path.parent == <init-dir>`,且 `_codegraph_signal` 仍读
`<init-dir>/run_config.json`(t2 partial 的 `uses_codegraph=false`,该值不参与填充,但读取不破坏)。

- 实现落点:TIERS["t2"]["plan_arg"] = `"init_dir"`(映射到 args),并在 main() 加
  `if tier["list_script"] == "plan_aggregate.py": plan_path = (Path(args.init_dir)/"run_config.json").resolve()`
  ——与 sdr 的 `if tier["list_script"] == "diff_group.py"` 特例同形。

### D6 — synthesis 提示词拆三态 + 两个新 agent

现状 `stages/init-synthesis.md` 只描述 whole 综合;t2.md 片段把同一 agent 复用于 partial/rollup 并手写任务,
欠规约且与「You see ALL T1 records」矛盾。拆为:

| 提示词 | 行为 | agent(openmode 落位 / claude inline) |
| --- | --- | --- |
| `init-synthesis.md`(逐字不变) | whole 单上下文(小仓) | `init-synthesis`(既有) |
| `init-synthesis-partial.md`(新) | per-shard 有界 partial,产结构化 shard 摘要;**不做跨 shard canonical/competing** | `init-synthesis-fanout`(新,mode primary) |
| `init-synthesis-rollup.md`(新) | 仅吞各 shard 摘要,跨 category canonical/competing 归并 → 终态 inventory | `init-synthesis-rollup`(新) |

三态输出 schema 一致(`design_controls`-compatible),`validate_inventory.py --check` 同路径适用。
partial 与 rollup 均沿用既有「NEVER Write .py / py -c」「有界 ack」硬边界。

### D7 — marker 语义:shard 为中间态,终态 marker 不变

rollup 终态 marker `checkpoints/t2/synthesis.json.done` 不变;shard marker 在 `checkpoints/t2/shards/`
(plan_aggregate 已定义)。`resume_state.py` 的「t2 done」仍 = `synthesis.json.done` 存在(不变);**不新增
步骤 id**。`--resume` 重入 map 阶段 = 重跑 `--tier t2`(marker 幂等跳过 done shard)。`resume_state.py --check`
需新增一条磁盘自洽校验:存在 shard `.done`/`.failed` 而 `synthesis.json.done` 缺失 = 「t2 map 未完 / rollup 未完」
(合法中间态,非违例),以区分「t2 进行中」与「t2 完成」。

### D8 — R5.7 段 A 评估(partial/rollup 新提示词)

改 `core/prompts/**` 前先建 baseline(无该提示词跑 ≥5 次 capture 失败模式)→ blind A/B(whole 综合 vs
map-reduce 三态)对 pass-rate/token → 新实例大仓首跑观察漂移。partial 的「不跨 shard 判定」边界与 rollup 的
「摘要语义不丢 competing 信息」是本 change 忠实度主风险,单测无法覆盖,靠评估驱动。

## Risks / Trade-offs

- **[partial/rollup 语义漂移]** partial 做多了(跨 shard 判定)或 rollup 摘要丢 competing 信号 →
  canonical/competing 判定劣化。→ D8 评估 + partial 提示词显式「NEVER 跨 shard canonical/competing」+
  rollup 提示词显式「从各摘要恢复 competing 成员」。
- **[t2 枚举条件性]** `--tier t2` 被误调(needs_reduce=false)时若 dispatcher 把空 pending 当 stalled 会误熔断。
  → 单测锚定「空 pending = 0 单元 partial:false、不误报 stalled」+ 编排器侧 `needs_reduce` 闸门前置(D4)。
- **[两段 = t2 步两个编排器动作]** t2 fragment 会变长(map dispatcher 行 + rollup 步)。→ R5.6 薄壳纪律:
  fragment 只放骨架,detail 下沉 per-step 已按需加载;`description:` 与 shell token 硬上限不破。
- **[resume 中间态]** 新增 `checkpoints/t2/shards/` 中间 marker,`--resume`/`resume_state --check` 需正确区分
  「map 未完」与「t2 完」。→ D7 的 `--check` 磁盘自洽校验 + 回归测。

## Migration Plan

- 无磁盘 schema 变更(`run_config.json`/`init_manifest.json` 不动;`checkpoints/t2/shards/` 是既有
  plan_aggregate 已定义的中间目录)。
- 既有安装项目重跑 `install.sh` 获新 `fanout_runner.py`(t2 行)、`t2-task.md`、`init-synthesis-partial.md`/
  `init-synthesis-rollup.md`、opencode `init-synthesis-fanout.md`/`init-synthesis-rollup.md` 克隆。
- 回滚 = 回退到 `needs_reduce=true` 时走旧手派路径(dispatcher 退出码 2 回退手派仍保留),非破坏性。
