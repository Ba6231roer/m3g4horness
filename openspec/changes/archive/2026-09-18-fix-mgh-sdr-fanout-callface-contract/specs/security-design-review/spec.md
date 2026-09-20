## MODIFIED Requirements

### Requirement: sdr 运行域守卫激活与幂等 resume

`/mgh-sdr` SHALL 为第 6 个运行域:env `MGH_SDR_ACTIVE=1` 或磁盘哨兵 `<repo>/.mgh-sdr/.active`
(向上 walk 发现,承既有激活契约)激活守卫;哨兵 `read_roots[]` 声明的外部只读根按 `runtime-hook-enforcement`
的 read_roots 扩展要求生效。哨兵的写入 SHALL 为**确定性脚本副作用**(`sdr_context.py` 完成基线投影与
外部仓检索后 co-write),SHALL NOT 依赖编排器手执行的 `Bash printf` 配方。

流程 SHALL 幂等可恢复,分**产物层**与**入口层**两件事:

- **产物层**(既有语义不变):`diff_group.py --materialize` 对已存在 `.done` marker 的单元跳过物化重复工作;
  `fanout_runner.py --resume` 按磁盘 marker 重派 pending;`render_sdr_report.py` 对 draft 齐备的 run 目录
  可重复执行(重跑覆盖同名报告)。
- **入口层**(既有语义):`resume_sdr_state.py`(见 `resume-step-discipline`)SHALL 从 `<run-dir>/`
  磁盘产物重派生 `step` / `next_action` / `discipline_reminders[]`,使压缩 / 崩溃 / 新会话三态坍缩为同一条
  恢复路径(**读磁盘 → 继续**)。恢复 SHALL 复用**既有 run 目录**(同一 `<run-dir>`),SHALL NOT 另起一个新的
  时间戳 run 目录——新建目录 = 已完成单元的 marker 不在新目录里 = 全部重做(零复用即全损)。

编排器每步完成后 SHALL 跑对应产出者 `--check`,失败(退出码 2)回退重跑,不带着破损产物继续(承 R5.9)。

**恢复指引 MUST 域内可执行**:命令壳给出的恢复、排障与"磁盘状态是否正常"判定指引,SHALL 只引用
在 sdr 运行目录下可实际执行的脚本——即接受 `--run-dir <sdr run dir>`(或等价的 `<run-dir>` 位置参数)
且不依赖其它运行域目录布局的产出者(如 `diff_group.py --check <run-dir>`)。命令壳 SHALL NOT 让
编排器调用以 `<target>/.mgh-init` 为默认状态根、在 sdr 运行目录下必然以"目录不存在"失败的脚本
(如 `resume_state.py`,其运行目录解析为 `--init-dir > <target>/<run-root=默认 .mgh-init>`);此类
跨域引用 SHALL 在 sdr 场景视为坏指引,因为它百分之百失败并使编排器在真实拥塞形态下失去判据。
该约束 SHALL NOT 被读成"指引只能有一个":`resume_sdr_state.py`(入口层状态重派生,域内可执行)与
`diff_group.py --check <run-dir>`(产物层完整性)是**两件不同的事**,SHALL 并存——前者回答"我做到哪一步、
下一步跑什么",后者回答"分组产物有没有坏"。二者语义不同,SHALL NOT 互相替代:产物完好而以产物检查
代替状态查询会丢失"下一步";状态可派生而产物已坏时,状态查询本身不校验产物。

**已披露的入口层缺口(既有披露,本 change 不修)**:`mgh_sdr_launch.py` 每次调用按当前时刻**新建**
`<repo>/.mgh-sdr/runs/<ts>-<branch>/`,且无 `--resume` / `--run-dir` 参数;故「经 launcher 同样参数重跑即续跑」
**目前不成立**(会落到新目录、从头再跑)。续跑入口为:由调用方已知 run 目录时,经命令壳的显式
`--run-dir` + `resume_sdr_state.py --run-dir <abs>` 继续。launcher 侧的 run 目录复用 SHALL 由后续 change 补齐。

#### Scenario: 崩溃后 resume 零全损推进

- **WHEN** fan-out 中途宿主中断(部分单元 `.done`、部分 pending),调用方带着**同一个** run 目录路径回来
- **THEN** `resume_sdr_state.py --run-dir <abs>` 报 `step="fanout"` 与确切重派命令;`diff_group.py --materialize`
  复用既有 run 目录(按 resume 语义),dispatcher 仅重派未 `.done` 单元,已完成单元零重复消耗;最终报告覆盖全部单元

#### Scenario: launcher 重跑会新建 run 目录(缺口如实成立)

- **WHEN** 对同一 branch 再次运行 `mgh_sdr_launch.py`(同参数)
- **THEN** 产生一个新的 `<repo>/.mgh-sdr/runs/<ts>-<branch>/` 目录,上一次 run 的 marker 不被复用;
  该行为 SHALL 在命令壳的恢复指引与 `/mgh-sdr` 的诚实边界中披露(不得宣称「重跑 launcher 即续跑」)

#### Scenario: 完成/干净停止后哨兵移除

- **WHEN** 流程跑完(报告渲染完成)或用户干净停止(含 `--dry-run` 早退之外的正常退出路径)
- **THEN** `<repo>/.mgh-sdr/.active` 被移除;残留哨兵的 run(宿主被硬杀)由下次 launcher 启动时
  检测并复用/清理,不静默锁死日常开发

#### Scenario: 壳内恢复指引在真实 sdr 运行目录可执行

- **WHEN** 审阅命令壳的恢复/排障段并按其中逐字给出的命令实跑(工作目录为任意 sdr 运行目录)
- **THEN** 每条被引用的检查命令以退出码 0(状态正常)或 2(状态异常,fail-loud)返回,NEVER 因
  "状态根目录不存在"以退出码 1 失败;命令中出现的脚本参数与 sdr 运行目录的实际布局一致
  (`--check <run-dir>` 形态在册)

#### Scenario: 拥塞形态的产物自检是域内命令

- **WHEN** 编排器遇到 `stalled:true` 需要先判定"磁盘上分组产物有没有坏"再同参重派
- **THEN** 它跑 `diff_group.py --check <run-dir>`(域内可执行,退出码 0/2),NEVER 跑在 sdr 运行目录下
  必然以退出码 1 失败的跨域脚本;该命令的语义边界(校验产物完整性、非运行进度自洽性)SHALL 在该指引
  处就近披露,使编排器不会把它读成完整的恢复面
