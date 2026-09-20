> **人话序** 现象：`/mgh-sdr` 跑到一半崩溃、上下文被压缩、或换一个新会话接着跑时，编排器没有任何确定性的"我现在在哪一步、下一步该做什么"的来源，只能靠对话记忆去猜。`/mgh-init` 早就解决了这件事：磁盘上的产物加完成标记能重推出当前步骤与下一步动作，并且每一步该守的闸门、该走的路径配方都从磁盘重新注入，因此压缩与否都不影响执行路径。`/mgh-sdr` 这些一样都没接——没有运行域感知的状态查询，没有按步骤的纪律提醒，运行目录里的 `run_config.json` 只被当成"起始态意图"写进去却没人按那个用途读，运行域标记文件和写它们的配方全靠编排器手执行、中途丢失也没有"进行中却缺标记即守卫休眠"的校验，更没有确定性重写。根因：这套恢复面是随 init 长出来的，sdr 作为后加的命令没有回头补齐。改什么：把"从磁盘重推步骤"扩展到 sdr 运行域——定义 sdr 的步骤图与每步纪律表、让状态查询脚本接受 sdr 运行目录、补标记文件存在性校验与重写、把命令壳的恢复指引接上。怎么验证：在一个被人工中断的 sdr 运行目录上查询，返回的步骤与下一步动作同磁盘产物一致；标记文件缺失时查询报错并给出重写命令；同目录重复查询输出稳定。

## Why

- 现状的 sdr 恢复是**隐式**的：运行目录复用加完成标记跳过（`diff_group --materialize` 跳过已 `.done` 单元、`fanout_runner --resume` 按磁盘标记重推待办、`render_sdr_report` 可重复执行）。这些能保证"不重做已完成的工作"，但**不能回答"现在处于哪一步、下一步调什么"**。R5.4 的 disk-truth 目标是把压缩/崩溃/新会话三态坍缩为同一条恢复路径（读磁盘 → 继续），sdr 目前只覆盖了其中"标记跳过"的一半。
- 同一 gap 在 init 侧的解法已经落地并有 spec：状态查询脚本从 `<run-dir>` 全产物加跨层完成标记加 `run_config.json` 重派生 `step`/`next_action`/`tiers`/`resumable`，并由纪律表携带 per-step 的闸门形状、路径配方与适用硬边界。sdr 缺的是同一套东西的 sdr 版本，**不是新机制**。
- 直接后果之一是命令壳里那条恢复指引不可执行：壳让编排器跑 `resume_state.py --check`，而该脚本只认 init 运行目录，在 sdr 下必然退出 1。（本 change 与 `fix-mgh-sdr-fanout-callface-contract` 有交叠：后者只做"消除不可执行指引"的最小止血，本 change 提供真正的替代。）
- 一处半死契约：命令壳手执行 `printf` 往 `<run-dir>/run_config.json` 写东西，而 sdr 侧**没有任何脚本读它**。它本应作为"起始态意图"（记录 base/branch 等），使重新进入无需重述参数——但 sdr 既无读取方，也无 `--resume` 入口。（该文件另有一个**活着**的用途——codegraph 信号载体，由并存的 `fix-mgh-sdr-fanout-callface-contract` 接通；本 change 退场的是起始态那一半，保留这一半，见 design D2。）
- 运行域标记检查缺失：init 域在进行的 run 若缺标记文件，状态查询会 fail-loud 并给出重写命令（进行中却缺标记 = 守卫休眠，是安全问题而非小事）。sdr 域没有这层校验，标记文件丢失会静默退化到"守卫不生效"。

## What Changes

- **sdr 步骤图与状态重派生**：新增 sdr 域的状态查询能力（实现形态在 design 定：扩展既有状态脚本以接受运行目录/域名参数，或新增 sdr 专属脚本）。输出结构对齐既有形态，至少含 `step` / `next_action` / `resumable` / `tiers`，步图覆盖：激活与标记写入 → 基线与外部检索 → diff 分组与切片物化 → fan-out 复核 → 报告渲染与收尾。全部由 `<run-dir>/` 磁盘产物（`context.json` / `grouping.json` / `markers/*` / 报告与汇总文件）重派生，**不读对话记忆**。
- **sdr 纪律表**：per-step 携带该步的闸门（`--check` 命令与失败退出码）、路径配方（单元输入/草稿/完成标记一律取自 `diff_group` stdout 的 `pending[]` 字段，绝对路径，逐字透传）、以及适用硬边界。表内容与命令壳/片段中的承重防线保持一致，两处对同一步 MUST 输出同构结构。
- **`run_config.json` 的起始态用途退场、写入者换成脚本**：起始态（repo/base/branch）改由既有产物 `context.json`/`grouping.json` 重派生，该文件**只**承载 codegraph 信号（`{"no_codegraph": <bool>}`，唯一载荷），并改由 `sdr_context.py` 确定性 co-write（与哨兵同一副作用位置）；命令壳的三处手执行 `printf` 配方（哨兵两处 + 该文件一处）一并删除——**编排器不再读懂并执行写配方**。
- **标记文件存在性校验与重写**：sdr 状态查询支持在"run 进行中但标记文件缺失"时 fail-loud（退出码 2）并给出可执行 recipe；另提供确定性重写入口，按运行目录里记录的仓库根重建标记。重写值 MUST 取自 Python 叶脚本 stdout 的原生路径（Windows 原生形态），MUST NOT 取自 shell 的 MSYS 形态。
- **命令壳恢复指引接上**：`mgh-sdr.md` ① 层指引改为调用本 change 提供的 sdr 域状态查询；随本 change 落地后，`fix-mgh-sdr-fanout-callface-contract` 的止血写法由本 change 取代。
- **非目标**：不改派发器的失活/冷却/风暴机制（已对全部 tier 一致生效）；不改 sdr 的分组算法与报告结构；不为 sra/srr/sast/ut-init 做同样的事（见 `adopt-mgh-shared-fanout-dispatcher`）。

## Capabilities

### New Capabilities

<!-- 无。均为既有能力的运行域扩展。 -->

### Modified Capabilities

- `resume-step-discipline`: 从"/mgh-init 专属"扩展为**多命令共享**——sdr 运行域 MUST 有等价的磁盘重派生步骤与 per-step 纪律携带，输出结构与 init 同构。
- `security-design-review`: 「sdr 运行域激活与幂等 resume」要求扩充——除既有标记跳过外，新增"从磁盘重派生当前步骤与下一步动作"与"标记文件存在性校验/重写"。
- `runtime-hook-enforcement`: 标记文件（哨兵）的存在性校验与确定性重写机制从 init 域扩展到 sdr 域，使"进行中缺标记"在 sdr 同样 fail-loud。

## Impact

- **代码**：新增状态查询与步清单脚本、共享 marker 谓词模块（`core/scripts/`）；`discipline_core.py` 加域参数与 sdr 域表（纯数据 + 纯函数、无 IO）；`sdr_context.py` 加哨兵 + `run_config.json` 的 co-write 副作用与 `--no-codegraph` flag；`mgh_sdr_launch.py` 透传该 flag；`diff_group.py` 改为导入共享 marker 谓词（写入侧路径逐字不变）；`releases/claude-code/commands/mgh-sdr.md`、`releases/opencode/command/mgh-sdr.md`。派发器 `fanout_runner.py` **零改动**（其 `run_config.json` 读取面由并存 change 提供，本 change 刻意保住）。
- **契约/lint**：`tools/check_contracts.py` 增新脚本 flag 断言；`install.sh` 共定位自检列表更新；零依赖 AST 扫描覆盖新脚本。
- **测试**：新增状态派生单测（人工构造中断态运行目录的各中间态）、纪律表结构一致性测、标记校验与重写测；若复用既有脚本则扩展其既有测试文件。
- **文档**：维护者私有文档区里 `/mgh-sdr` 的命令人话说明新增"中断后如何续跑"一节；术语词典补相应条目；CHANGELOG/VERSION bump。
- **依赖/交叠**：与 `fix-mgh-sdr-fanout-callface-contract` 在"壳恢复指引"一处交叠，建议本 change 在其后落地并取代其止血写法。
- **风险**：sdr 运行目录当前没有稳定的"起始态意图"文件，步骤重派生依赖的是分散产物；若某一步崩溃后没留下可判定产物，`step` 会退化。该退化 MUST 显式披露，MUST NOT 静默猜测步骤。
