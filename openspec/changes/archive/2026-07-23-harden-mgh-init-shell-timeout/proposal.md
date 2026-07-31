## Why

opencode 的 shell 工具在默认超时(实测 60s / 官方 120s)会强杀 `discover_controls.py`,
而该脚本是**单发不可恢复**的:walk→index→callgraph(2 pass)→scan 全部跑完才在 `main()`
末尾一次性写产物。中途被 SIGKILL → 零产物、零 checkpoint、stderr 进度被宿主「完成才回显」吞掉
→ 用户看到 `(no output)`,且 `--resume` 无从下手(最终文件根本没落盘,重跑从零开始)。
Claude Code 的 Bash 同样有 120s 默认墙,大仓一样会被切——这是**双壳**缺口,不只是 opencode。

两层根因:(1) **两份命令壳从头到尾没提超时**(`releases/` 全量 grep `timeout|600000|60000|120000`
零命中),编排器从不给长跑确定性脚本传 per-call `timeout`,也没文档化 opencode 的可配置项;
(2) `discover_controls.py` 无 callgraph 缓存、无 scan 续点、无软时限早退——而
`control-discovery` spec **早已要求** `cache/callgraph.json` + `--rebuild-cache`(「Resumable,
checkpointed execution」),实现从未兑现(脚本 `argparse` 甚至没有 `--rebuild-cache`)。本变更
既补「超时配置」也补「discover 韧性」,直接兑现用户「配置 + discover 韧性」的选定范围。

## What Changes

按杠杆从高到低、侵入从低到高分三层:

- **Layer 1 — discover 超时韧性(改 `core/scripts/discover_controls.py`,R2 零依赖,init/control-discovery)**:
  - **callgraph 缓存**:build 后原子写 `<out>/cache/callgraph.json`;重跑时按源文件 mtime 失效,
    命中即跳过两遍 callgraph 重建(兑现 spec 既有要求 + 关闭 `--rebuild-cache` 悬空契约)。
  - **scan 续点**:原子写 `<out>/cache/scan_progress.json`(`scanned_index` + 累积候选);`--resume`
    复用 callgraph 缓存并从续点继续扫描、合并候选。
  - **软时限 `--time-budget-ms`**(默认 0=关):在安全边界(callgraph 建成后、scan 每 `--progress-every`
    文件)若已超预算 → 落全部-so-far 产物 + stdout 增 `partial:true` / `resume_hint`、**退出码 0**
    (干净退出,而非被 SIGKILL 全损)。
  - **原子写**:所有产物 `.tmp`+`os.replace`,使 SIGKILL 不留截断 JSON。
  - stdout 契约 **additive**(增 `partial`/`resume_hint`,`candidates/clusters/...` 字段不变);`--check` 不变。
- **Layer 2 — per-call 超时 recipe(改 4 份命令壳,横切编排纪律)**:编排器 SHALL 给长跑确定性 Bash
  调用传慷慨的 per-call `timeout`(claude Bash 与 opencode shell 工具均接受);对带 `--time-budget-ms` 的
  discover,`timeout` 略大于 budget,见 stdout `partial:true` 则 **Bash 重派 `--resume`**(编排器循环,
  **NEVER** 写 wrapper `.py`)。覆盖 init/sast/sra/srr 四壳的长跑脚本。
- **Layer 3 — opencode 超时配置披露(文档)**:README + 命令壳边界段文档化
  `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认 120000;**须 opencode 启动前就绪**——mid-session
  `export` 不生效,与 R5.7 `MGH_*_ACTIVE` 可靠性边界同根因)。

非目标(明确不做):不改任何命令现有最终产物 schema(全 additive);不向 `core/scripts/` 引入第三方依赖(承 R2);
不 import `vvaharness`;不在开源仓引入任何网络/上传代码。

## Capabilities

### New Capabilities
<!-- 无新能力。discover 韧性落在既有 control-discovery;超时 recipe 是横切编排纪律,落到既有 4 个命令 spec。 -->

### Modified Capabilities
- `control-discovery`:discover 从「单发不可恢复」升级为「callgraph 缓存 + scan 续点 + 软时限干净早退 +
  原子写」(兑现既有「Resumable, checkpointed execution」与「Bounded single-pass scan performance」
  的 host-timeout 场景);`discover_controls.py` 增 `--time-budget-ms` / `--rebuild-cache`(真实化);
  init 命令壳增 per-call timeout recipe + `partial:true` 重派 `--resume`;README/壳披露 opencode 超时配置。
  下游 `merge_scout` / `form_clusters` / `controls_inventory.json` 磁盘格式**不变**(全 additive)。
- `sast-orchestration-discipline`:mgh-sast 命令壳的长跑确定性 Bash(prefilter/dedup/emit_sarif)SHALL 传
  per-call `timeout` + opencode 超时配置披露(与 init 同形 recipe)。
- `security-augmentation`:mgh-sra 命令壳的长跑确定性 Bash(prepare_augment/merge_augment/merge_memory)
  SHALL 传 per-call `timeout` + 同形披露。
- `freeform-security-review`:mgh-srr 命令壳的长跑确定性 Bash(ingest_requirements/render_report)
  SHALL 传 per-call `timeout` + 同形披露。

## Impact

- **改脚本**(`core/scripts/discover_controls.py`,单文件):增 callgraph 缓存读写、scan 续点、
  `--time-budget-ms` 软早退、原子写。R2 零依赖(py stdlib `os.replace`/`time.monotonic`/`pathlib`);
  自定位 `sys.path`、utf-8、stdout=JSON/stderr=进度、退出码 `0/1/2`、任意 cwd 可跑(承 R5.3)。
- **改命令壳**:4 份 `mgh-{init,sast,sra,srr}.md`(claude + opencode = 8 份)增 per-call timeout recipe
  + opencode 超时配置披露;init 两壳另增「discover `partial:true` → Bash 重派 `--resume`」recipe。
- **改契约**:`core/contracts/init/` 增 discover 缓存/续点/早退的 stdout 字段说明(`partial`/`resume_hint`)
  与 `cache/` 布局(callgraph.json / scan_progress.json)。
- **改文档**:README opencode 超时段(default + pre-launch env 变量 + mid-session 不生效边界)。
- **改测试**:`tests/` 增 callgraph 缓存命中/失效、scan 续点幂等、`--time-budget-ms` 早退 `partial:true`、
  原子写抗截断的确定性单测;既有 `tests/test_init_discover.py` 扩 stdout 字段断言。
- **改 AGENTS.md**:R5.3(b)/R5.4 增「长跑确定性 Bash SHALL 传 per-call timeout;discover 软时限早退由
  编排器 Bash 重派 `--resume`,NEVER 写 wrapper `.py`」。任一 `.md`/脚本改动 bump 版本号(承 R5.8)。
- **依赖**:零新增运行时依赖(R2)。不 import `vvaharness`。
- **BREAKING / 风险**:`--rebuild-cache` 从「悬空(脚本不认)」变为「真实 flag」——属**收紧**而非破坏
  (旧行为=每次重建;新行为默认仍每次重建除非缓存命中,语义向后兼容)。`--time-budget-ms` 默认 0=关,
  默认路径行为不变。无 schema/数据迁移;产物字段全 additive;`/mgh-init` 既有功能与最终产物不变。
