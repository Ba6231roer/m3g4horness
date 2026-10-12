# Tasks — harden-mgh-init-scout-merge-dispatch

## 1. 聚合预算默认收紧(D1)

- [x] 1.1 `core/scripts/plan_aggregate.py`:`DEFAULT_BUDGET = 96*1024`,`--help` 文案给出 96KB + token 换算依据;`write_runconfig.py` / `write_ut_runconfig.py` / `render_report.py` 的 `DEFAULT_MAX_AGGREGATE_BYTES` 同步 98304
- [x] 1.2 三面壳 `mgh-init`(claude/opencode/dsh)预算行「聚合输入上限,默认 256KB」→「96KB」;同步任何引用 256KB 的 fragment/契约文本
- [x] 1.3 新增默认值一致性断言(同名 flag 各脚本 `--help` 均声明 98304)并入 `tools/check_contracts.py` 或 `tests/test_plan_aggregate.py`

## 2. plan_aggregate scout-merge 硬界打包(D2)+ marker-aware 枚举(D3)

- [x] 2.1 重写 `_shard_by_batch_cluster` → 候选粒度稳定序贪心装箱;shard 项 `batches` 改为覆盖的去重 batch_id 列表;≤预算批整批同 shard 时与旧装箱退化等价(单测断言)
- [x] 2.2 病态单候选确定性瘦身投影(scout 字段表:`evidence_snippet`/`snippet` 截 4096B、`entry_points` ≤16;结构字段永不截;原 checkpoint 不回写;stdout `slimmed` 留痕)
- [x] 2.3 瘦身后仍超 → 退出码 2、零物化零派发、stderr 指认来源记录路径(镜像 t2 atomic-oversize)
- [x] 2.4 `marker_aware` 从 `node=="t2"` 扩为 `node in {"t2","scout-merge"}`:pending 排除终态、stdout 补 `total/done/failed`、scout-merge shard 项含 `failed_marker`;`--include-failed` 对 scout-merge 生效;移除 scout-merge 的 `oversize:true` 照发路径与对应 warn 文案(`fanout_runner.py:456` recipe 文本走查)
- [x] 2.5 `tests/test_plan_aggregate.py`:新增超预算批切批、原子候选瘦身、fail-loud、marker-aware 重列、`needs_reduce=false` 分支 stdout 逐字节不变 五组用例;t2 既有用例逐字保留

## 3. fanout_runner 接入 `--tier scout-merge`(D3)

- [x] 3.1 TIERS 表增 `scout-merge` 行(枚举/模板/agent/占位符/`plan_arg=init_dir` 复用 t2 特例、`id_field=shard_id`、无 codegraph/切片);`--tier` choices 与 `--help` 闭集同步;sidecar 名 `fanout_progress.scout-merge.json`
- [x] 3.2 新建模板 `core/prompts/fragments/fanout/scout-merge-task.md`(占位符 = 4 路径字段 + `shard_id`/`batches`/`repo`/`mgh_core`;钉死 stage 提示词唯一位置 + 「读不到即 `failed`、NEVER 翻目录」纪律,与 t2-task.md 同文风)
- [x] 3.3 `tests/test_fanout_runner.py` 新 tier 用例(harness 层 `--cooldown-s 0` 约):模板填充、marker 懒校验、path-drift spawn 前 `.failed`、`needs_reduce=false` 幂等空转、既有五 tier 零漂移

## 4. stage 提示词与 agent 面(D4)

- [x] 4.1 `core/prompts/stages/init-scout-merge.md`:删「P0 软边界/超界回 `oversize` ack」旧段(single-context 输入由闸门保证 ≤ 预算),其余纪律不变
- [x] 4.2 新建 `init-scout-merge-partial.md`(单 shard 去重/归一 → 摘要 checkpoint + 有界 ack;禁跨 shard 判断、禁写终态产物)与 `init-scout-merge-rollup.md`(仅吞 `summary_paths` → 跨 shard 归并 → 写 `scout_candidates.json` wrapper + touch `merge.json.done`;产物必须原样过 `merge_scout.py --check`)
- [x] 4.3 摘要 checkpoint schema 增段进 `core/contracts/init/scout-plan.md`(候选直存形状,与 `_normalize`/`_key` 兼容,不新增适配字段)
- [x] 4.4 三面 fanout/rollup agent 定义:opencode `init-scout-merge-fanout.md`(`mode: primary`、hidden、permission 同 `init-synthesis-fanout`)+ `init-scout-merge-rollup.md`;claude `agents/init-scout-merge-fanout.md`;dsh `releases/dsh/agents/scout-merge.md`(委托 leaf prompt 形态)

## 5. 编排壳 / fragment / steps 接线(D6)

- [x] 5.1 `core/prompts/fragments/init-stage/scout.md`:「spawn init-scout-merge 前先判聚合预算」段重写为 dispatcher-first(闸门命令 + `--tier scout-merge` 调用行含四级超时合规示例 + 熔断/冷却 recipe + rollup 单步 + `.failed` 不得 rollup),手派路径降级标注为 exit 2 回退并补「定义文件唯一位置」纪律;三面镜像
- [x] 5.2 三面壳 `mgh-init`:Stage→组件表 fanout_runner tier 清单加 scout-merge(map 段)、subagent 表补 `init-scout-merge-fanout`/`-rollup`;壳正文 token ≤ 5000 走查(`tools/measure_prompts.py`)
- [x] 5.3 `core/scripts/list_steps.py`:scout 步 `cli_args` 增 `--tier scout-merge --init-dir <init-dir> --budget <max-aggregate-bytes> --checkpoints <init-dir>/checkpoints/scout --inputs-dir <init-dir>/inputs/scout-merge` 行;`resume_state.py` 步骤派生零改动确认(t2 预算 note 文案走查)
- [x] 5.4 `discipline_core.py` tier/预算相关文本同步;`tools/gen_dsh_tiers.py` `REQUIRED_TIERS` 加 `scout-merge`

## 6. 分发接线与自检

- [x] 6.1 `install.sh`:自检清单覆盖新模板/agent/stage 提示词/契约行;三端镜像一致性(三面壳同查,R5.1)
- [x] 6.2 `tools/check_contracts.py`:提取三面壳与 scout.md 的 `*.py --flag` 断言存在(含 `--tier scout-merge`、新默认 help 文案)
- [x] 6.3 定向回归:`tests/test_plan_aggregate.py` `test_fanout_runner` `test_fanout_stale` `test_gen_dsh_tiers` `test_dsh_command_surface` `test_dsh_hook_parity` `test_list_steps` `test_init_runtime` `test_distributed_md_purity` `test_plain_language` + `test_zero_deps` `test_no_compile_warnings`;跨面(install 自检/hook 接线)→ 全量一次

## 7. 存量现场 re-entry 演练(design「Migration Plan」runbook,即用户第 3 问)

> **2026-09-28 状态**:真实目标仓不在本机;已交付 Linux·无 root 版执行手册
> `docs/man/mgh-init-scout-merge-reentry-runbook.md`(步骤 1–6 + 回滚 + 失败速查)。
> 7.1–7.3 由维护者在该机照手册执行;执行中的偏差回灌本 change 后再勾选。

- [ ] 7.1 按 runbook 步骤 1–4 在真实目标仓执行:`--kill-stale` 审孤儿 → 删 `inputs/scout-merge/`、`checkpoints/scout/shards/`、`merge.json[.done]`、`scout_candidates.json`、`fanout_progress.scout-merge.json` → 核对 `controls_candidates.json::provenance.scout_merged` 走分支 A/B → 改 `run_config.json` 预算为 98304
- [ ] 7.2 `/mgh-init --resume` 实跑观察:`resume_state` 回 scout 步 → 96KB 重切 → dispatcher 波次零人工介入(无权限弹窗、无翻目录找 agent)→ rollup → `merge_scout --check` 通过 → T1–T4 推进
- [ ] 7.3 验证收口:所有 `inputs/scout-merge/*.input.json` ≤ 98304B;`boundaries[]`/`report.md` 记录 shard 数、批切分与瘦身痕迹;把实跑偏差回灌 design/runbook 修订(评估驱动,承 R5.7 段 A)

## 8. 收口

- [x] 8.1 bump 版本号(所有改动 `.md`/脚本,R5.8);`openspec validate --strict` 通过
- [x] 8.2 诚实边界更新:AGENTS.md「诚实边界」段 `/mgh-init` 行补 scout-merge 分片/派发一句话(如需);人话序人工闸门自查(只读 proposal 人话序 + 本 tasks 能复述现象→根因→改什么→怎么验证)
