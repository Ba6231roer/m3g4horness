## Why

mgh-init 的提示词已经把大量编排纪律下沉到确定性 hook(`block_adhoc_scripts`)+ 脚本(`resume_state`/`list_*`/`--check`
validator),但审计整条提示词面(命令壳 + `orchestrator-discipline` + 12 个 per-step fragment + 8 个 stage 提示词)后,
仍有**两条承重纪律是纯提示词软依赖**——模型若没读懂/没执行,防线就静默失效,且正是 150K 低上下文窗口下「注意力稀释 →
执行偏离任务提示词规划」的典型温床:

1. **`.active` 哨兵写入是 `printf` 提示词**(`init-stage/bootstrap.md:20`)。哨兵是 opencode 上 hook 激活的**唯一**可靠路径
   (插件进程不继承 mid-session env),弱模型漏写哨兵 → 整 run 守卫休眠 → 脚本只读 / 越树写 / `py -c` 内省全部静默放行。
   这是 `docs/mgh-init-budget-analysis.md` §A.5 排序 #2 的「哨兵确定性副作用」,在 #1(补全 R5.4,已归档
   `complete-r5-4-per-step-discipline`)完成后已是**头号剩余稳定杠杆**。
2. **「NEVER Read 叶子 `.py` 源码」是提示词**(`orchestrator-discipline.md:16` + `discipline_core.py` nevers)。读叶源码
   既浪费上下文(单个脚本 200–900 行 ≈ 3–10K tok,debug 循环连读几个即加速触压缩),又诱导 agent 想「改」脚本(写侧已拦)。

本 change 把这两条从「提示词要求」改成「确定性 hook / 脚本强制」:哨兵改为 `write_runconfig.py` 的确定性副作用 +
`resume_state --check` 的存在性校验;叶源码 Read 改为 hook 读侧新增分支。直接收益 = 消除「弱模型漏写哨兵」这一真实
失败形状 + 删掉两处提示词要求(省 token);本质收益 = 稳定性(防线不依赖模型读懂提示词)。

## What Changes

- **哨兵确定性副作用(治 #1,flagship)**:`write_runconfig.py` 在原子写 `run_config.json` 的同时**确定性写**
  `<init-dir>/.active` 哨兵(`domain`/`target`/`out_roots[]`/`v`,target 取既有的 Windows 原生 `target_abs`,
  `out_roots[]` 从 `--out`/`--rules-dir` 派生)——哨兵写不再是编排器 `printf`。`resume_state.py --check` 增
  **哨兵存在性校验**:`run_config.json` 存在且流水线未 `done` 时 `.active` 缺失 → 退出码 2 + recipe(守卫休眠 =
  fail-loud)。`--resume` 重派经 `resume_state` 的确定性 re-arm(从 `run_config.target` 重写哨兵)。
- **叶源码 Read 拦截(治 #2,secondary)**:hook 读侧新增分支——运行域内 `Read` 一个落在已安装
  `<mgh-core>/scripts/` 镜像下的 `.py` → 退出码 2 + recipe(报错看 stderr)。从 `orchestrator-discipline` +
  `discipline_core.py` 删除对应 `NEVER` 提示词要求。
- **提示词瘦身**:`bootstrap.md` 删 `printf` 哨兵配方(改为「write_runconfig 已自动写哨兵,`--resume` 经
  resume_state re-arm」);`orchestrator-discipline`/`discipline_core` 删叶源码 NEVER。
- **回归**:`write_runconfig` 哨兵副作用单测、`resume_state --check` 哨兵校验单测、hook 叶源码读拦截单测 +
  接线覆盖断言(守卫分支集 ⊆ matcher ∧ ⊆ shim `HANDLED`)、parity 测(双端 `.py` byte-identical)、
  `core/contracts/hooks/runtime-enforcement.md` 同步。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `runtime-hook-enforcement`:
  1. **activation requirement 增补**——哨兵写入 SHALL 是确定性脚本副作用(`write_runconfig`),非编排器 `printf`;
     `resume_state --check` SHALL 校验「流水线进行中 + 哨兵缺失 = 退出码 2」。
  2. **read-side requirement 增补**——运行域内 `Read` 已安装 `<mgh-core>/scripts/` 下的叶脚本 `.py` 源码 SHALL 被
     fail-loud 拦截(leaf scripts read-only 的读侧对偶,不再仅靠提示词 NEVER)。

## Impact

- **代码**:`core/scripts/write_runconfig.py`(哨兵副作用)、`core/scripts/resume_state.py`(`--check` 哨兵校验 +
  re-arm)、`releases/{claude-code,opencode}/hooks/block_adhoc_scripts.py`(byte-identical 同步,叶源码读分支)、
  `core/prompts/fragments/init-stage/bootstrap.md`(删 printf 配方)、`core/prompts/fragments/orchestrator-discipline.md`
  (删叶源码 NEVER)、`core/scripts/discipline_core.py`(删对应 nevers)、`core/contracts/hooks/runtime-enforcement.md`、
  `tools/install_hook.py`(matcher 若需)、`tests/test_block_adhoc_scripts.py`、`tests/test_opencode_hook_parity.py`
  (接线覆盖)、`tests/test_resume_state.py`/`tests/test_write_runconfig.py`(若存在)、AGENTS.md R5.7 措辞、版本号 bump。
- **既有安装项目**:重跑 `install.sh` 镜像新脚本/hook;`write_runconfig` 哨兵副作用是幂等增量(既有无哨兵 run 也自愈)。
- **风险**:哨兵存在性校验可能对「手工删哨兵的调试 run」fail-loud(recipe 给出 re-arm 出口);叶源码读拦截是
  预期收紧(与提示词 NEVER 一致);opencode hook 与宿主权限系统先后顺序仍列真机冒烟。
- **非目标**:不做「gate 执行顺序 → hook 状态机」强制(分析结论:耦合流水线状态机 + subagent 名,脆弱,ROI 低,见 design);
  不改 `MGH_TARGET` env 导出(保留为 belt-and-suspenders,虽哨兵 `target` 已使其冗余,见 design);
  不治「弱模型不执行 `--check` 闸门」的通用软依赖(已由 `discipline_reminders[]` 磁盘化兜底)。
