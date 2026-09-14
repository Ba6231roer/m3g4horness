# Tasks: adopt-mgh-init-fanout-t2

## 1. 枚举脚本扩展(plan_aggregate.py)

- [x] 1.1 `core/scripts/plan_aggregate.py --node t2` stdout 顶层补 `repo`(=`--init-dir` resolve 父目录,`.mgh-init` 恒在 `<target>/.mgh-init` 下)、每 `pending[]` shard 项补 `failed_marker`(与 `done_marker` 同目录 `.<shard_id>.json.failed`);`needs_reduce=false` 路径 stdout 逐字不变
- [x] 1.2 扩展 `tests/test_plan_aggregate.py`:断言 `--node t2` 时 `repo`/`failed_marker` 字段存在且绝对、`needs_reduce=false` 零回归
- [x] 1.3(D2a,实现期补 scope)`--node t2`(仅 t2;scout-merge 手派不动)`needs_reduce=true` 时:pending[] 排除已有 `.done`/`.failed` marker 的 shard,顶补 marker 派生 `total`/`done`/`failed`;`summary_paths`/`shards` 仍为全集;`needs_reduce=false` 逐字不变;test 断言排终态 + 计数

## 2. fanout_runner.py t2 tier

- [x] 2.1 TIERS 增 `"t2"` 行:`list_script="plan_aggregate.py"`、`list_args` 转发 `--node t2 --init-dir/--budget/--materialize`、`required_args`、`plan_arg="init_dir"`、`template_rel` 指 `fanout/t2-task.md`、`path_fields`=`input_path/checkpoint_path/done_marker/failed_marker`、`placeholders` 加 `shard_id/categories/repo`、`id_field="shard_id"`、`agent="init-synthesis-fanout"`、`agent_tools="Read Glob Grep Bash Write"`、`uses_codegraph=False`、`uses_chunk_sources=False`
- [x] 2.2 `fanout_runner.py` argparse 增 `--init-dir`/`--budget`(t2 必需 flag);main() 加 `if tier["list_script"]=="plan_aggregate.py": plan_path=(Path(args.init_dir)/"run_config.json").resolve()` 特例(仿 sdr `diff_group.py` 特例,使 sidecar/liveness 家目录=`<init-dir>`)
- [x] 2.3 新建 `core/prompts/fragments/fanout/t2-task.md`(仅输入字段声明 + 指向 `stages/init-synthesis-partial.md` 的装载指令,零行为规则复制;`shard_id`/`categories`/`input_path`/`checkpoint_path`/`done_marker`/`failed_marker`/`repo`)
- [x] 2.4 扩展 `tests/test_fanout_runner.py`:t2 tier 参数化用例——枚举消费、模板逐字填充、空 pending(`needs_reduce=false`)幂等空转不误报 `stalled`、越树路径 spawn 前 `.failed` 拦截、既有四 tier 零漂移

## 3. synthesis 提示词分态 + agent 定义

- [ ] 3.1 R5.7 段 A baseline:在超预算大仓样本上跑现有 whole 综合 `init-synthesis`,capture 失败模式(≥5 次)(**待真机评估,见 apply 汇报**)
- [x] 3.2 新建 `core/prompts/stages/init-synthesis-partial.md`(per-shard 有界 partial:读 `input_path` 的 shard 记录,产结构化 shard 摘要写 `checkpoint_path`;显式 **NEVER 跨 shard 做 canonical/competing 判定**;沿用「NEVER Write .py / py -c」+ 有界 ack 硬边界)
- [x] 3.3 新建 `core/prompts/stages/init-synthesis-rollup.md`(仅吞 `rollup.summary_paths` 各 shard 摘要,跨 category canonical/competing 归并 → 终态 inventory;从摘要恢复 competing 成员;输出 schema 同 whole)
- [x] 3.4 新建 `releases/opencode/agent/init-synthesis-fanout.md` + `init-synthesis-rollup.md`(`mode: primary` 克隆,正文指各自 stage 提示词);claude 侧经 `--agents` inline JSON 按同名装载(无新增落位文件)

## 4. 编排器 step 面切换

- [x] 4.1 `core/prompts/fragments/init-stage/t2.md` 派发段改 dispatcher-first:`needs_reduce=false` → single-context `init-synthesis` 逐字不变;`true` → 先 `--kill-stale --dry-run` 前置,再一次 `Bash` 跑 `fanout_runner.py --tier t2`(+ `--time-budget-ms` 接线、`partial:true` 重派、退出码 2 回退手派),map 全 `.done` 后单一 `init-synthesis-rollup` 吞 `rollup.summary_paths` 写 inventory + `synthesis.json.done`
- [x] 4.2 `core/scripts/list_steps.py` t2 步契约面(script_name/cli_args/input/output)补 dispatcher 调用行(含 `--tier t2` 与 `--init-dir`/`--budget`)
- [x] 4.3 `core/scripts/discipline_core.py` t2 `path_recipes` 增软时限重派纪律(重派传 per-call `timeout` > `--time-budget-ms`)
- [x] 4.4 `core/scripts/resume_state.py --check` 增 t2 中间态磁盘自洽校验:存在 `checkpoints/t2/shards/*.done`/`.failed` 而 `synthesis.json.done` 缺失 = 「map 未完 / rollup 未完」合法中间态(非违例),与「t2 完成」区分;不新增步骤 id

## 5. 契约 lint + install + 分发纯净

- [x] 5.1 `tools/check_contracts.py` 断言 `--tier t2` 与 `plan_aggregate.py` 新增 flag 在其 `--help` 存在
- [x] 5.2 `install.sh` 镜像清单 + 自检覆盖 `t2-task.md`、`init-synthesis-partial.md`/`init-synthesis-rollup.md`、opencode `init-synthesis-fanout.md`/`init-synthesis-rollup.md`(双端对等)
- [x] 5.3 分发纯净:`check_distributed_purity.py` / 人工检查新 fragment/agent 不含 R5.x/FDn/Dn/openspec 夹名等 dev-only 悬空引用

## 6. 文档 + 版本 + 真机验证

- [x] 6.1 `docs/man/mgh-init.md`:补 `fanout_progress.t2.json` sidecar 名、T2 map 阶段 dispatcher 语义、宿主外手动直跑说明
- [x] 6.2 VERSION / CHANGELOG bump(0.1.36)
- [ ] 6.3 全套回归测 `py tests/` 通过(**1071 全绿,已跑**)+ 双宿主(claude/opencode)大仓真机冒烟:map 全 `.done`、rollup 产出 inventory 过 `validate_inventory.py --check`、与手派路径 marker 集合等价(**待真机评估,见 apply 汇报**)
- [ ] 6.4 R5.7 段 A blind A/B:whole 综合 vs map-reduce 三态 的 pass-rate/token 对比 + 全新 B 实例大仓首跑观察漂移,失败模式回灌(**待真机评估,见 apply 汇报**)
