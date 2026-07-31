## MODIFIED Requirements

### Requirement: Bounded single-pass scan performance on large repos

`discover_controls.py` SHALL 对每个源文件**至多读一次磁盘**(读入后缓存文本,供调用图两遍与候选
扫描共用);`walk_sources(repo)` 在单次运行中**只遍历一次**仓库并物化文件清单,供调用图构建与候选
扫描复用;每文件**仅调用一次 `splitlines()`**;候选的 enclosing 锚点 SHALL 通过**每文件预排序的
结构节点列表 + 按行二分**求解,而非「每候选对全文反复 `finditer`」。系统 SHALL 在扫描期间向
**stderr** 周期输出进度(每 N 个文件),stdout 仅在末尾输出既有 JSON 摘要(契约不变)。在 i0 阶段
SHALL 以低成本统计源文件数,命中大仓阈值时**在开始全量扫描前**主动建议 `--scope` 分模块 + `--merge`。

本要求**不再假设 discover 在单次宿主调用内必然完成**:当目标仓大到单次调用超过宿主 shell 超时
(claude Bash / opencode shell 工具默认 120s,可被强杀于更早),discover SHALL 经 callgraph 缓存 +
scan 续点 + 软时限干净早退(见「Discover call-graph cache survives re-runs」「Discover scan resumes
from a checkpoint」「Discover soft time-budget clean exit」「Discover writes are atomic」)**跨多次
编排器调用推进且零全损**,而非依赖「5 分钟内一发跑完」。

#### Scenario: Large repo completes across re-invocations without total loss
- **WHEN** 对一个单次调用即超过宿主 shell 超时的大目标仓运行 `/mgh-init`,且某次 discover 调用被宿主
  在超时处强杀
- **THEN** 已建成的 callgraph 缓存与 scan 续点**留存可用**,编排器 Bash 重派 `discover ... --resume`
  复用缓存、从续点继续,**不**从零重跑;经有限次重派后产物完整,期间**无**「`(no output)` 全损」形态

#### Scenario: Each source file read at most once
- **WHEN** 对任意目标仓运行发现脚本(单次调用内)
- **THEN** 每个源文件的磁盘读取次数为 1(调用图两遍与候选扫描共用同一缓存文本)

#### Scenario: Progress emitted to stderr only
- **WHEN** 扫描持续进行且尚未完成
- **THEN** stderr 周期性打印已扫描文件数;stdout 不在中途打印非 JSON 内容,末尾 JSON 摘要契约不变

#### Scenario: Large repo advised to scope before scanning
- **WHEN** i0 阶段统计的源文件数超过阈值
- **THEN** 系统在开始全量扫描前提示建议 `--scope` 分模块 + `--merge`,而非静默跑到超时

## ADDED Requirements

### Requirement: Discover call-graph cache survives re-runs

`discover_controls.py` SHALL 在两遍调用图建成后将结果(`forward`/`reverse`/`framework_files`/
`name_to_files` 等重建所需态)原子写到 `<out>/cache/callgraph.json`;重跑时 SHALL 按源文件 mtime
判定缓存新鲜度——源未变更且未传 `--rebuild-cache` 时 SHALL 加载缓存、跳过两遍 callgraph 重建。该缓存
是「跨调用零全损推进」与「重跑提速」的基础(兑现既有「Resumable, checkpointed execution」的
callgraph-cache 条款,关闭 `--rebuild-cache` 悬空契约)。`--rebuild-cache` flag SHALL 真实存在且经
`--help` 暴露(承 R5.1);默认行为(无缓存或缓存失效=每次重建)向后兼容。

#### Scenario: Cache hit skips callgraph rebuild
- **WHEN** discover 完成一次写入 `cache/callgraph.json` 后,源文件未变更即再次运行
- **THEN** discover 加载缓存、跳过两遍 callgraph 重建,stdout 摘要含缓存命中标志

#### Scenario: Stale cache rebuilt on source change
- **WHEN** 缓存存在但某源文件 mtime 新于缓存,或传 `--rebuild-cache`
- **THEN** discover 重建调用图并刷新缓存(不返回过期结果)

#### Scenario: rebuild-cache is a real documented flag
- **WHEN** 运行 `discover_controls.py --help`
- **THEN** `--rebuild-cache` 出现在参数表(argparse 认识,不报 unrecognized)

### Requirement: Discover scan resumes from a checkpoint

`discover_controls.py` SHALL 在 scan 阶段周期(每 `--progress-every` 文件)原子写续点
`<out>/cache/scan_progress.json`(至少含已扫文件索引 `scanned_index` 与累积候选)。`--resume` SHALL
复用 callgraph 缓存并从 `scanned_index` 续扫、追加候选(不重扫已续点文件);续点合并 SHALL 确定性、
幂等(同一续点重跑产等价候选集)。scan 完成后续点可保留(供再次 resume)或清理,均不破坏最终产物。

#### Scenario: Resume continues scan past a kill
- **WHEN** discover 在 scan 中途被强杀,留下 `scan_progress.json`(scanned_index=K),随后
  `discover ... --resume`
- **THEN** discover 跳过前 K 个已扫文件、从第 K+1 续扫,候选集等价于一次跑完的结果

#### Scenario: Resume is idempotent
- **WHEN** 对同一续点连续两次 `--resume`
- **THEN** 两次产出的候选集等价(不重复、不丢失)

### Requirement: Discover soft time-budget clean exit

`discover_controls.py` SHALL 提供 `--time-budget-ms <N>`(默认 0=关)。当置位且在安全边界(callgraph
建成后、scan 每 `--progress-every` 文件)已超预算时,discover SHALL 落全部-so-far 产物(callgraph
缓存 + scan 续点)并在 stdout 增 `partial: true` + `resume_hint`(可操作的重派提示)后**退出码 0**
(干净早退,而非被宿主 SIGKILL 全损)。未置位或未超预算时 SHALL 一次性跑完,stdout `partial: false`。
编排器 SHALL 据 stdout `partial: true` 经 Bash 重派 `--resume`(编排器循环,**NEVER** 写 wrapper `.py`;
承 R5.2 黑盒纪律)直至 `partial: false`。

#### Scenario: Budget exceeded triggers clean partial exit
- **WHEN** 运行 `discover_controls.py --repo . --out .mgh-init --time-budget-ms 30000`,且单次调用 30s
  内跑不完
- **THEN** discover 在安全边界落缓存/续点后退出码 0,stdout 含 `partial: true` + `resume_hint`,无产物截断

#### Scenario: Budget off finishes in one go
- **WHEN** 未传 `--time-budget-ms`(默认 0),且仓规模在单次超时内
- **THEN** discover 一次性跑完,stdout `partial: false`,行为等价于引入本要求前

#### Scenario: Orchestrator re-dispatches on partial, never via wrapper script
- **WHEN** discover stdout 为 `partial: true`
- **THEN** 编排器经 Bash 重派 `discover ... --resume`;**不** `Write` wrapper `.py` 去循环

### Requirement: Discover writes are atomic

`discover_controls.py` SHALL 原子写出所有产物 JSON(`controls_candidates.json`/`clusters.json`/`skeleton.json`/
`cache/*`):先写 `<path>.tmp` 再 `os.replace` 落盘,使进程在任意时刻被 SIGKILL 都**不**留下
截断/半写 JSON(`--check` 与下游 `json.loads` 不会读到破损文件)。原子写仅用 Python 标准库
(`os.replace`/`pathlib`),承 R2 零运行时依赖。

#### Scenario: Killed mid-write leaves no truncated artifact
- **WHEN** discover 在写 `controls_candidates.json` 的过程中被强杀
- **THEN** 目标仓里**不**存在截断的 `controls_candidates.json`(要么完整、要么不存在),`.tmp` 残留可被
  下次运行覆盖

#### Scenario: check passes after an interrupted run
- **WHEN** 对一次被强杀后留下完整产物的 out-dir 运行 `discover_controls.py --check`
- **THEN** `--check` 读到合法 JSON,退出码 0(无破损文件误判为边界失败)

### Requirement: Long-running deterministic Bash calls carry a per-call timeout

每份 `mgh-*.md` 命令壳的编排器 SHALL 给**长跑确定性 Bash 调用**传一个慷慨的 per-call `timeout`
(claude Bash 工具与 opencode shell 工具均接受毫秒级 `timeout` 参数)。对 init,长跑脚本含
`discover_controls.py`(尤其带 `--time-budget-ms`)/`plan_scout.py`/`merge_scout.py`;对带 `--time-budget-ms`
的 discover,`timeout` SHALL 略大于该 budget,编排器见 stdout `partial: true` 即 Bash 重派 `--resume`。
命令壳 SHALL 在边界/披露段说明:opencode 用户**可**经环境变量
`OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS`(默认 120000)提升全局默认,但该变量**须在 opencode
启动前就绪**(mid-session `export` 不被 opencode 插件进程继承,与 R5.7 `MGH_*_ACTIVE` 可靠性边界同根因);
per-call `timeout` 是跨宿主公共杠杆,可在会话中即时生效。该 recipe 是横切编排纪律(镜像
`sast-orchestration-discipline`/`security-augmentation`/`freeform-security-review`)。

#### Scenario: Shell recipe tells the orchestrator to pass a per-call timeout
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md`
- **THEN** 两壳均显式要求长跑确定性 Bash 调用携带 per-call `timeout`,并据 discover stdout `partial`
  决定是否 Bash 重派 `--resume`

#### Scenario: opencode env-var boundary disclosed
- **WHEN** 审阅 `mgh-init.md` 边界段与 README
- **THEN** 其中明示 `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` 须 opencode 启动前设置、mid-session
  `export` 不生效,并指 per-call `timeout` 为会话内即时生效的替代
