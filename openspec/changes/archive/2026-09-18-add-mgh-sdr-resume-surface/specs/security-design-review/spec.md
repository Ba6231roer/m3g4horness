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
- **入口层**(本 change 补齐):`resume_sdr_state.py`(见 `resume-step-discipline`)SHALL 从 `<run-dir>/`
  磁盘产物重派生 `step` / `next_action` / `discipline_reminders[]`,使压缩 / 崩溃 / 新会话三态坍缩为同一条
  恢复路径(**读磁盘 → 继续**)。恢复 SHALL 复用**既有 run 目录**(同一 `<run-dir>`),SHALL NOT 另起一个新的
  时间戳 run 目录——新建目录 = 已完成单元的 marker 不在新目录里 = 全部重做(零复用即全损)。

编排器每步完成后 SHALL 跑对应产出者 `--check`,失败(退出码 2)回退重跑,不带着破损产物继续(承 R5.9)。

**已披露的入口层缺口(本 change 不修)**:`mgh_sdr_launch.py` 每次调用按当前时刻**新建**
`<repo>/.mgh-sdr/runs/<ts>-<branch>/`,且无 `--resume` / `--run-dir` 参数;故「经 launcher 同样参数重跑即续跑」
**目前不成立**(会落到新目录、从头再跑)。本 change 的续跑入口为:由调用方已知 run 目录时,经命令壳的显式
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

## ADDED Requirements

### Requirement: sdr 运行目录无起始态文件;codegraph 信号由脚本确定性写出

`/mgh-sdr` 的运行目录 SHALL NOT 携带**起始态**文件:`run_config.json` 内的起始态字段
(repo / base / branch / 维度相关开关)SHALL NOT 由任何一方写入,亦 SHALL NOT 被任何一方读取。
起始态 SHALL 从既有磁盘产物重派生:repo / base / branch 由 `sdr_context.py` 产出的
`<run-dir>/context.json` 承载(`diff_group.py` 亦将其写进 `grouping.json`);run 目录布局本身
(`<repo>/.mgh-sdr/runs/<…>`)给出 repo。两处记录冲突时以 `context.json` 为准并在 `notes[]` 披露。

`<run-dir>/run_config.json` 作为**codegraph 信号载体**保留,但其唯一载荷 SHALL 为
`{"no_codegraph": <bool>}`(dispatcher 的 `{{codegraph}}` 占位符来源,见 `fanout-dispatch`),
且 SHALL 由**确定性脚本副作用**写出——`sdr_context.py` 完成基线投影与外部仓检索后 co-write
(与其哨兵写入同一副作用位置,取 `--no-codegraph` flag)。命令壳 SHALL NOT 再手执行 `Bash printf`
配方写该文件;launcher SHALL 经 `_run_context` 透传 `--no-codegraph`,使两条入口写出同源内容。
缺失 / 不可解析一律落 `off`(既有 legacy 语义不变)。

唯一在磁盘上**无**起始态可派生的步是 `not-started`(context.json 尚未写出),而该步也是**零已完成工作**的
步:重新给参(`--base` / `--branch`)重跑即完整恢复,不构成恢复面缺口——这一条 SHALL 由
`resume-step-discipline` 的「起始态不可重派生时的显式退化披露」断言。

#### Scenario: 运行目录里没有起始态字段

- **WHEN** 一次完整的 `/mgh-sdr` run 结束,审阅 `<run-dir>/run_config.json`
- **THEN** 该文件(若存在)只含 `no_codegraph` 一个字段;无 repo / base / branch / 维度字段;
  repo/base/branch 可从 `context.json` 与 `grouping.json` 读出

#### Scenario: 壳中不再有手执行的写入配方

- **WHEN** 审阅 `mgh-sdr.md` 双壳的 Orchestration flow
- **THEN** 两壳都不含写 `run_config.json` 或哨兵的 `printf` 配方(两者都改由 `sdr_context.py` 写出);
  两壳关于该点的措辞一致

#### Scenario: 两条入口写出同源的 codegraph 信号

- **WHEN** 分别经 launcher 与经宿主会话的 `sdr_context.py` 启动同一 branch 的 run
- **THEN** 两条路径产生的 `<run-dir>/run_config.json` 内容同构(同一 `--no-codegraph` 取值 →
  同一载荷),均由脚本写出而非编排器手执行

### Requirement: sdr 双壳恢复指引接上状态查询

`releases/claude-code/commands/mgh-sdr.md` 与 `releases/opencode/command/mgh-sdr.md` SHALL 在恢复/中断段
指引编排器**首调** `resume_sdr_state.py --run-dir <abs>`,从 stdout 读 `step` / `next_action` /
`discipline_reminders[]`,再按该步纪律执行(闸门 → 路径配方 → 硬边界)。壳中指向 init 域脚本
(`resume_state.py`)的调用 SHALL 被移除——该脚本只认 init 运行目录,在 sdr 下必然失败(不可执行指引)。

该段 SHALL 陈述续跑的前置条件(**带着同一个 run 目录路径**),并如实披露 launcher 重跑会新建 run 目录。
壳 SHALL 声明恢复路径的抗压缩性:进度与纪律纯从磁盘重派生,与对话记忆是否保留无关。

#### Scenario: 壳的恢复指引可执行

- **WHEN** 编排器在 sdr 中断后按壳的恢复段执行第一步
- **THEN** 该步给出的是 `resume_sdr_state.py --run-dir <abs>`(sdr 域脚本)而非 init 域的 `resume_state.py`;
  按其 stdout 的 `next_action` 继续即接上流水线

#### Scenario: 双壳恢复段文案一致

- **WHEN** 比对 claude 壳与 opencode 壳的恢复段
- **THEN** 两者对同一恢复路径的措辞同构(宿主差异只留在工具名/路径前缀层)
