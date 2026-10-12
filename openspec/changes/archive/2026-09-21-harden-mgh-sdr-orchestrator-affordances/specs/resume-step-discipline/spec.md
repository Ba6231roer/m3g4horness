## MODIFIED Requirements

### Requirement: sdr 运行域的状态重派生(resume_sdr_state.py)

新增确定性叶脚本 `core/scripts/resume_sdr_state.py`(Python ≥3.10 标准库、零运行时依赖、自定位、
任意 cwd 可 `py`)SHALL 为 `/mgh-sdr` 恢复面「我现在在哪一步 / 下一步调什么」的唯一出口。
其 `step` 与 `next_action` SHALL 纯从 `<run-dir>/` 磁盘产物重派生——`context.json` / `grouping.json` /
单元 marker(`<run-dir>/markers/<unit_id>.done|.failed`)/ `sdr_manifest.json`——SHALL NOT 读对话记忆,
SHALL NOT 读取 `<run-dir>/run_config.json`(该文件只承载 codegraph 信号,不含起始态;见
`security-design-review`)。起始态一律来自 `context.json` / `grouping.json`。

init 域既有脚本 `core/scripts/resume_state.py` SHALL 保持**零改动**(其 blast radius 隔离);sdr 域以
**姊妹脚本**形态落地,与既有 ut-init 域 `resume_ut_init_state.py` 同范式。

sdr 的 run 目录有两种产生路径(launcher 的 `<repo>/.mgh-sdr/runs/<ts>-<branch>/` 与命令壳的
`--run-dir`),该脚本 SHALL 对两者一视同仁——**只吃一个 run 目录**,不对目录命名做任何假设。

CLI 契约(`--help` 即契约面):
`py resume_sdr_state.py --run-dir <abs> [--repo <abs>] [--check] [--rearm-sentinel] [--arm-sentinel]`

- `--run-dir` 为**必填**(sdr 无唯一缺省 run 目录,`runs/<ts>` 每次不同);缺该 flag → argparse 退出码 2。
- `--run-dir` 指向不存在的目录 → 退出码 1(路径错/误用,stderr 给可操作 recipe)。
- `--check` 自洽校验失败 → 退出码 2;`--rearm-sentinel` 成功 → 退出码 0;其余 → 退出码 0。
- `--repo` 可省:按 `<run-dir>` 路径布局(`<repo>/.mgh-sdr/runs/<…>`)推导;推不出时相关字段降级并在
  `notes[]` 披露(见「起始态不可重派生时的显式退化披露」)。
- `--arm-sentinel`(step 0 预武装,与 `--rearm-sentinel` 互斥):**写**最小哨兵
  `<repo>/.mgh-sdr/.active`(`target` 取 `--repo`,缺失且布局推不出 → 退出码 2 + recipe),
  幂等与 target 冲突语义按 `runtime-hook-enforcement` 的 sdr 哨兵要求执行;成功 → 退出码 0,
  stdout 单对象 JSON 含 `sentinel_path`(绝对)/`armed`(本次新写为 `true`、已存在同 target 为
  `false`)/`target`。该 flag 是**写侧**动作,SHALL NOT 改变本脚本其余字段的只读派生语义。

stdout SHALL 为单对象 JSON(stdout = 结构化 JSON、stderr = 诊断/进度严格分流),至少含:

| 字段 | 语义 |
|---|---|
| `repo` / `run_dir` | 绝对路径(Windows 原生,Python `Path.resolve()` 产出,NEVER shell 的 MSYS 形态) |
| `base` / `branch` | 从 `context.json`(缺则 `grouping.json`)重派生;两者冲突以 `context.json` 为准并在 `notes[]` 披露 |
| `step` | 闭集枚举,**当前待办步** |
| `resumable` | 布尔;`step == "done"` → `false` |
| `tiers` | `{done, failed, total}`(口径见「计数口径披露与自洽校验」) |
| `next_action` | `{kind: "bash"\|"subagent"\|"done", desc, absolute_paths[]}` |
| `notes[]` | 披露与 advisory(退化、缺口、失败单元、孤儿 marker 等) |
| `discipline_reminders` | 当前步纪律子集 `{gates[], path_recipes[], nevers[]}`(字段恒存在) |
| `stale_fanout[]` | `<run-dir>/fanout_runner.*.pid` 残留扫描 `{tier, pid_file, pid, pid_alive, note}`(字段恒存在) |

`tiers` 的 `done`/`failed` SHALL 为「canonical 单元 id 的正向 marker 路径存在性」判定(与 `diff_group.py`
的枚举口径**同源**),SHALL NOT 由 glob 文件数或文件名 stem 反推(身份漂移类缺陷的确定性防线)。

`step == "not-started"` 时 `next_action` SHALL 同时携带 step 0 预武装的确切命令
(`resume_sdr_state.py --run-dir <abs> --repo <abs> --arm-sentinel`)作为该步 recipe 的前置行,使恢复
路径与首发路径给出同一条上膛指令。

#### Scenario: 中断的 run 返回磁盘一致的步骤与下一步

- **WHEN** 一个 fan-out 中途被打断的 sdr run(部分单元 `.done`、部分 pending)被 `resume_sdr_state.py --run-dir <abs>` 查询
- **THEN** stdout `step="fanout"`,`next_action.kind="bash"` 且 `desc` 载明 `fanout_runner.py --tier sdr` 的确切调用,
  `next_action.absolute_paths[]` 为逐字取自磁盘的 repo / checkpoints / slices 绝对路径(无占位符、无相对路径);
  `notes[]` 披露未终态单元计数

#### Scenario: 同一磁盘状态重复查询输出稳定

- **WHEN** 磁盘状态不变时对同一 run 目录连续调用两次
- **THEN** 两次 stdout 逐字一致(纯函数于磁盘状态,幂等)

#### Scenario: 重派生不读任何「起始态」文件

- **WHEN** 对一个**含**历史遗留 `run_config.json` 的旧 run 目录查询
- **THEN** 该文件既不被读取也不影响输出(base/branch 全部来自 `context.json`/`grouping.json`)

#### Scenario: arm-sentinel 写最小哨兵且回报绝对路径

- **WHEN** 对尚未起步的 run 目录执行 `resume_sdr_state.py --run-dir <abs> --repo <abs> --arm-sentinel`
- **THEN** `<repo>/.mgh-sdr/.active` 存在(`read_roots:[]`),stdout `armed=true`、`sentinel_path` 为
  Windows 原生绝对路径;再次执行同命令 → `armed=false` 且哨兵文件逐字不变

#### Scenario: not-started 的 next_action 携带上膛配方

- **WHEN** `context.json` 不存在的 run 目录被查询
- **THEN** `step="not-started"`,`next_action` 的确切命令文本含 `--arm-sentinel` 前置行,恢复的编排器
  无需翻壳即可知道先武装再跑 step 1
