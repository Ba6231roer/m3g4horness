# add-mgh-sast-telemetry

> **人话序**：mgh-sast 目前收不到使用遥测，因为它是唯一一个「启动路径上没有任何确定性 Python 脚本」的命令——其余五条命令的遥测（见 `add-mgh-telemetry-seam`）都挂在现成的启动脚本里，壳零改动；sast 的 step 0 只有编排器手写的 bash（哨兵是 printf 出来的，壳原文自述「sast 无 step-0 Python abs-repo 源」）。要接入遥测，得先给 sast 造一个启动缝（类似 init 的 `write_runconfig`：新脚本接管哨兵预武装/run 目录初始化，壳改成一行脚本调用），再在该脚本里挂遥测。本提案只占位记录背景，优先级低，待 mgh-ut-init 的 dsh 面补齐或 sast 有其他启动缝改造需求时一并做。

## Why

使用遥测（能力 `usage-telemetry`，由 `add-mgh-telemetry-seam` 建立）覆盖了 mgh-init / mgh-sdr / mgh-sra / mgh-srr / mgh-ut-init 五条命令；mgh-sast 因缺少启动期确定性脚本而暂缺，运营统计中 sast 的使用量会系统性缺失。

## What Changes

- 为 mgh-sast 新增启动期确定性脚本（接管现由编排器 bash 手写的哨兵预武装、run 目录初始化，同 `write_runconfig` 模式），并在其中挂载 `mgh_telemetry.fire("mgh-sast", …)`。
- 三面 mgh-sast 壳 step 0 的对应 bash 行改为该脚本的一行调用（唯一需要动壳的命令；预算余量见 `add-mgh-telemetry-seam` 的 design 记录，claude 面余 153 tok、opencode 面 4421、dsh 面 4717，均可行）。
- 接口文档（`add-mgh-telemetry-seam` 交付）无需变更：method=`mgh-sast`、operation=`静态安全扫描` 已在闭集对照表内。

## Capabilities

### New Capabilities
<!-- 无独立能力：接入点是既有 usage-telemetry 能力的第 6 个挂载点，届时以该能力的
     MODIFIED delta 扩挂载点清单，本 change 设 skip_specs 只做占位记录。 -->

### Modified Capabilities
<!-- 实施时：usage-telemetry（挂载点清单 + sast 场景）。本占位 change 无 delta。 -->

## Impact

- 代码：新增 1 个 sast 启动脚本 + 单测；三面 mgh-sast 壳各改 1 行；`add-mgh-telemetry-seam` 的模块零改动。
- 前置依赖：`add-mgh-telemetry-seam` 已实施（遥测模块已存在）。
