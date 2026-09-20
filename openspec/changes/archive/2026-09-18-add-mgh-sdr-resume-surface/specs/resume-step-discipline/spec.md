## ADDED Requirements

### Requirement: sdr 运行域的状态重派生(resume_sdr_state.py)

新增确定性叶脚本 `core/scripts/resume_sdr_state.py`(Python ≥3.10 标准库、零运行时依赖、自定位、
任意 cwd 可 `py`,承 R5.3a)SHALL 为 `/mgh-sdr` 恢复面「我现在在哪一步 / 下一步调什么」的唯一出口。
其 `step` 与 `next_action` SHALL 纯从 `<run-dir>/` 磁盘产物重派生——`context.json` / `grouping.json` /
单元 marker(`<run-dir>/markers/<unit_id>.done|.failed`)/ `sdr_manifest.json`——SHALL NOT 读对话记忆,
SHALL NOT 读取 `<run-dir>/run_config.json`(该文件在本 change 只承载 codegraph 信号,不含起始态;
见 `security-design-review`)。起始态一律来自 `context.json` / `grouping.json`。

init 域既有脚本 `core/scripts/resume_state.py` SHALL 保持**零改动**(其 blast radius 隔离);sdr 域以
**姊妹脚本**形态落地,与既有 ut-init 域 `resume_ut_init_state.py` 同范式。

sdr 的 run 目录有两种产生路径(launcher 的 `<repo>/.mgh-sdr/runs/<ts>-<branch>/` 与命令壳的
`--run-dir`),该脚本 SHALL 对两者一视同仁——**只吃一个 run 目录**,不对目录命名做任何假设。

CLI 契约(`--help` 即契约面,R5.1):
`py resume_sdr_state.py --run-dir <abs> [--repo <abs>] [--check] [--rearm-sentinel]`

- `--run-dir` 为**必填**(sdr 无唯一缺省 run 目录,`runs/<ts>` 每次不同);缺该 flag → argparse 退出码 2。
- `--run-dir` 指向不存在的目录 → 退出码 1(路径错/误用,stderr 给可操作 recipe)。
- `--check` 自洽校验失败 → 退出码 2;`--rearm-sentinel` 成功 → 退出码 0;其余 → 退出码 0。
- `--repo` 可省:按 `<run-dir>` 路径布局(`<repo>/.mgh-sdr/runs/<…>`)推导;推不出时相关字段降级并在
  `notes[]` 披露(见「起始态不可重派生时的显式退化披露」)。

stdout SHALL 为单对象 JSON(R5.3b:stdout = 结构化 JSON,stderr = 诊断/进度严格分流),至少含:

| 字段 | 语义 |
|---|---|
| `repo` / `run_dir` | 绝对路径(Windows 原生,Python `Path.resolve()` 产出,NEVER shell 的 MSYS 形态) |
| `base` / `branch` | 从 `context.json`(缺则 `grouping.json`)重派生;两者冲突以 `context.json` 为准并在 `notes[]` 披露 |
| `step` | 闭集枚举,**当前待办步** |
| `resumable` | 布尔;`step == "done"` → `false` |
| `tiers` | `{done, failed, total}`(口径见下) |
| `next_action` | `{kind: "bash"\|"subagent"\|"done", desc, absolute_paths[]}` |
| `notes[]` | 披露与 advisory(退化、缺口、失败单元、孤儿 marker 等) |
| `discipline_reminders` | 当前步纪律子集 `{gates[], path_recipes[], nevers[]}`(字段恒存在) |
| `stale_fanout[]` | `<run-dir>/fanout_runner.*.pid` 残留扫描 `{tier, pid_file, pid, pid_alive, note}`(字段恒存在) |

`tiers` 的 `done`/`failed` SHALL 为「canonical 单元 id 的正向 marker 路径存在性」判定(与 `diff_group.py`
的枚举口径**同源**),SHALL NOT 由 glob 文件数或文件名 stem 反推(身份漂移类缺陷的确定性防线)。

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

### Requirement: sdr 步骤图、终止凭证与 marker 谓词单一真相

`resume_sdr_state.py` SHALL 按下列确定性规则派生 `step`(按序短路;判据全部是 `<run-dir>/` 下的磁盘存在性,
无任何对话态输入),`next_action` 为该步的确切调用。`step` 名 = **当前待办步**(与 init 域 `t1`/`t2` 语义一致:
`step` 说「下一步要做什么」,而非「上一步做完了什么」):

| `step` | 判据 | `next_action` 指向 |
|---|---|---|
| `not-started` | `context.json` 不存在 | `sdr_context.py --repo <abs> --run-dir <abs>`(该步同时完成运行域激活:哨兵由 `sdr_context` 确定性 co-write) |
| `group` | `context.json` 存在、`grouping.json` 不存在 | `diff_group.py --repo <abs> --base <ref> --branch <ref> --checkpoints <run-dir>/markers --materialize <run-dir>/slices` |
| `fanout` | `grouping.json` 存在、且未全部单元终态 | `fanout_runner.py --tier sdr --repo <abs> --base <ref> --branch <ref> --checkpoints <run-dir>/markers --inputs-dir <run-dir>/slices`(带四级超时三参数) |
| `render` | 全部单元终态(`done + failed ≥ total`)且 `sdr_manifest.json` 不存在 | `render_sdr_report.py --run-dir <abs> --repo <abs>` |
| `done` | `sdr_manifest.json` 存在 | 无(run 已收尾,`resumable=false`) |

- **终止凭证**:整条 run 的终态凭证 SHALL 为 `<run-dir>/sdr_manifest.json`(与 init 域 `init_manifest.json`
  同角色);该文件不存在 ⇒ run 未收尾。
- **零 diff / 全排除**:`grouping.json::empty == true`,或 `total == 0` 但 `excluded.count > 0`(diff 全被
  排除集吃掉)⇒ fan-out 步空跑即完成(`0 ≥ 0`),`step` 直接推进到 `render`,SHALL NOT 停在 fan-out 空转。
- **单元终态判据**:SHALL 只看 marker 文件(`done_marker` / `failed_marker`)是否存在,
  SHALL NOT 采信 `grouping.json::units[].status`(该字段在**枚举时点**算出,fan-out 之后即陈旧)。
- **marker 谓词单一真相**:单元 marker 路径的拼接规则 SHALL 定义**一次**,由写入方 `diff_group.py`
  与读取方 `resume_sdr_state.py` **共享导入**(新共享模块,与 init 域 `init_tier.py` 承载
  `forward_marker_paths`/`forward_done_ids` 同范式),SHALL NOT 各写一份拼接
  (口径分叉 = 「枚举说 pending、磁盘说有 marker」的无限重派缺陷类)。

#### Scenario: 全终态的 run 推进到渲染步

- **WHEN** 某 run 的全部单元都已终态(`.done` + `.failed` ≥ `total`),但 `sdr_manifest.json` 不存在
- **THEN** stdout `step="render"`,`next_action` 为 `render_sdr_report.py --run-dir <abs> --repo <abs>` 的调用

#### Scenario: 零 diff 的 run 不停在 fan-out 空转

- **WHEN** `git diff` 为空(`grouping.json::empty == true`,`total == 0`)
- **THEN** stdout `step="render"`(fan-out 步因 `0 ≥ 0` 视为已完成),`notes[]` 载明零变更

#### Scenario: 陈旧 status 字段不参与判定

- **WHEN** `grouping.json::units[].status` 全部写 `pending`(枚举时点快照),但磁盘 marker 显示多数单元已终态
- **THEN** stdout `tiers` 的 `done`/`failed` 反映**磁盘 marker 真相**(不采信 `status` 字段),`step` 相应推进到 `render`

### Requirement: 起始态不可重派生时的显式退化披露

在 `not-started` 步,`context.json` 尚未存在,起始态(尤其 `--base` / `--branch`)在磁盘上**无可判定产物**。
该脚本 SHALL 在此情形**显式披露**退化,SHALL NOT 静默猜测步骤或参数:`notes[]` SHALL 载明「起始态未落盘,
需重新给定」,`next_action.desc` SHALL 给出可执行的重新给参调用(含默认值提示 — `--base master`、
`--branch` 为当前分支),`repo` SHALL 在可由 run 目录路径推出时给出,推不出则要求 `--repo` 显式传入。

该退化 SHALL NOT 被描述为数据丢失:这一步恰是**零已完成工作**的步(run 目录刚建立),重新给参重跑即完整恢复。
`run_config.json` 之所以可以退场,正是由这一条支撑——唯一「磁盘上没有起始态」的步,也正是唯一「没有工作可丢」的步。

#### Scenario: 空 run 目录查询披露退化并重新给参

- **WHEN** 对刚建立、尚无任何产物的 `<repo>/.mgh-sdr/runs/<ts>/` 查询
- **THEN** stdout `step="not-started"`、`resumable=true`;`notes[]` 载明起始态未落盘;
  `next_action.desc` 给出 `sdr_context.py --repo <abs> --run-dir <abs> --base master --branch <当前分支>` 形态的可执行调用

#### Scenario: 推不出 repo 时不猜

- **WHEN** `--run-dir` 指向的路径不符合 `<repo>/.mgh-sdr/runs/<…>` 布局、且未传 `--repo`
- **THEN** `repo` 为空且 `notes[]` 指明需显式传 `--repo`;SHALL NOT 编造一个仓库根

### Requirement: sdr 纪律表与 per-step 纪律携带

`core/scripts/discipline_core.py` SHALL 从「init 单域静态表」扩展为**按域分表**:
`get_discipline(step, domain="init")` 默认域 `init`(既有两处调用零改动),新增 `domain="sdr"` 表,
其 key 与 `resume_sdr_state.py` 的 step 闭集一致(`not-started|group|fanout|render|done`)。

sdr 各步的纪律子集 SHALL 携带:

- **gate 闸门形状**:该步产出者的 `--check` 命令 + 退出码 2 fail-loud 语义
  (`sdr_context.py --check` / `diff_group.py --check` / `render_sdr_report.py --check`);
- **路径配方**:fan-out 单元的输入切片 / 草稿 / 完成标记 / 失败标记 = `diff_group.py` stdout
  `pending[].input_path|draft_path|done_marker|failed_marker`(**绝对、逐字透传**);
  `baseline_path` / `external_dir` 同源;
- **适用 NEVER 硬边界**(该步的硬边界,如 `NEVER 自拼路径`、`NEVER py -c 内算路径`、`NEVER Read 叶子源码`)。

纪律表内容 SHALL 与 `mgh-sdr.md` 双壳的 Orchestration flow 承重防线保持一致(同一步两处 MUST 输出同构内容):
fan-out 刚性三元组、四级超时不变式(`--stall-timeout-s < --call-timeout-s < --time-budget-ms × 0.8`)、
每步 `--check`、快败冷却形态与 `--retry-failed` 配方、非 ok 单元的 `run.log` 证据路径。

该纪律子集是 **resume 衍生量、非持久态**:不写入任何磁盘文件,`--check` 不涉及该字段;
无纪律的步(`done` / `not-started`)与未知步 SHALL 返回**空结构**(三键恒存在,shape 稳定)。

#### Scenario: fan-out 步的 resume 携带路径配方与硬边界

- **WHEN** 编排器对处于 fan-out 步的 run 调用 `resume_sdr_state.py`
- **THEN** stdout `discipline_reminders.path_recipes[]` 含「单元路径取自 `diff_group.py` stdout `pending[]` 字段、绝对逐字透传」配方,
  `discipline_reminders.gates[]` 含 `diff_group.py --check`(失败退出码 2),
  `discipline_reminders.nevers[]` 含该步硬边界;三者与 `mgh-sdr.md` 双壳同一步的措辞同构

#### Scenario: 无纪律的步返回空数组而非缺字段

- **WHEN** 当前步是 `done`(run 已收尾)
- **THEN** stdout 仍含 `discipline_reminders` 且三键均为空数组(字段恒存在,shape 稳定)

### Requirement: list_sdr_steps.py --step 携带同 step 纪律子集

新增 `core/scripts/list_sdr_steps.py` SHALL 输出 sdr 步清单
`{steps:[{step, kind, script, script_abs, invocation, input, output, discipline}]}`:
`invocation` 为可复制粘贴的调用行,`script_abs` 由 `__file__` 自定位派生,`discipline` 与
`resume_sdr_state.py` 当前步的 `discipline_reminders[]` **逐字一致**(同一 step,同一纪律单一真相)。

`--step <id>` SHALL 只接受**命名 id**(闭集);未知 id → 退出码 2 + stderr 可操作提示;
不新增 CLI flag(纪律是 stdout 字段,非 flag,R5.1 契约面不受扰动)。

#### Scenario: list_sdr_steps 与 resume_sdr_state 纪律逐字一致

- **WHEN** 对同一 run 分别调用 `list_sdr_steps.py --step group` 与 `resume_sdr_state.py --run-dir <abs>`(当前步 group)
- **THEN** 前者的 `discipline` 与后者的 `discipline_reminders[]` 逐字一致

#### Scenario: 未知 step id 闭集拒收

- **WHEN** 调用 `list_sdr_steps.py --step bogus`
- **THEN** 退出码 2 + stderr 列出已知 id;stdout 不产 JSON
