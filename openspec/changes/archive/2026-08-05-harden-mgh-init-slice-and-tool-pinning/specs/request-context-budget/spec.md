## ADDED Requirements

### Requirement: All orchestrator-to-subagent fan-out paths are absolute, in-tree, and verbatim

每条 `mgh-*` 命令的 fan-out 路径纪律(R5.3b)SHALL 覆盖编排器交给 subagent 的**所有**路径,不止 `input_path`/`checkpoint_path`/`rule_path`/`done_marker`/`failed_marker`。大文件**切片输出**路径(`chunk_sources.py --out`,init scout/T1、sast s4/deepdive 用)SHALL 同纪律:由确定性枚举脚本产出绝对 `slice_dir`/`slice_path`(落命令运行域受信子树,如 `<target>/.mgh-init/slices/<tier>/<unit>/`、`<target>/security-scan/slices/s4/<chunk>/`)、编排器逐字透传、subagent 恰好写该绝对路径。subagent NEVER 自拼路径(`<target>/<id>` 占位符)、NEVER 写相对路径、NEVER 写 cwd/系统临时目录(如 `…\AppData\Local\Temp\opencode\`、`/tmp/`)派生路径、NEVER 写运行域受信子树之外(含盘符根)。无切片的命令(sra/srr)空真满足。理由〔防 opencode 下 subagent 进程 cwd = 系统临时目录致切片落树外 → 回读触发越权 `Read` 提示 + 落 hook 受信子树自动放行〕。

#### Scenario: Slice output path follows the same discipline as checkpoint paths
- **WHEN** 一个 fan-out subunit 含需切片的大文件,编排器向 subagent 透传该 unit 的路径集合
- **THEN** 集合包含切片输出路径(绝对、落运行域受信子树),与 `checkpoint_path`/`input_path` 同形(均绝对、均树内、均逐字透传);subagent 写切片到该确切绝对路径并回读之

#### Scenario: No subagent writes a slice to a cwd/temp-derived or out-of-tree path
- **WHEN** subagent 进程 cwd 为系统临时目录(如 opencode 的 `…\AppData\Local\Temp\opencode\`),且需切片一个大文件
- **THEN** subagent 写切片到编排器透传的绝对 `slice_dir`/`slice_path`(运行域受信子树内),NEVER 写 `shards.json`(相对 cwd 默认)、NEVER 写 `…\Temp\…` 派生路径、NEVER 触发对临时目录的越权 `Read`

#### Scenario: Commands without slicing vacuously satisfy
- **WHEN** 一条命令的 fan-out subagent 不产生大文件切片(如 `/mgh-sra`、`/mgh-srr` 的 augment subagent)
- **THEN** 本要求空真满足(无切片路径需钉);该命令的既有 `input_path`/`checkpoint_path` 纪律不变
