# Design — harden-mgh-init-shell-timeout

## Context

`/mgh-init` 的 i1 发现阶段靠单一确定性脚本 `discover_controls.py`(walk→index→callgraph 两遍→scan→
末尾一次性写产物)。它在 opencode 下被宿主 shell 默认超时(实测 60s / 官方 120s)强杀;claude Bash 默认
120s 同墙。被杀 = 全损:无 checkpoint、无部分产物、stderr 进度被「完成才回显」吞 → `(no output)`;
`--resume` 无从下手(最终文件没落盘)。

现状两个缺口:(1) 4 份命令壳从不提超时(`releases/` grep 零命中);(2) `discover_controls.py` 无缓存、
无续点、无早退,而 `control-discovery` spec **早已要求** `cache/callgraph.json` + `--rebuild-cache`
(脚本 `argparse` 连 `--rebuild-cache` 都没有 → 悬空契约)。本设计同时补「超时配置」与「discover 韧性」,
落地用户选定的「配置 + discover 韧性」范围。约束:R2 零运行时依赖、R5.2 编排器黑盒(不写 wrapper `.py`)、
R5.3 确定性脚本稳定性契约、R5.7 opencode 不继承 mid-session env。

## Goals / Non-Goals

**Goals:**
- discover **零全损**:任一时刻被 SIGKILL 都留下可复用的 callgraph 缓存 + scan 续点;重跑提速。
- discover **跨多次编排器调用推进**:软时限干净早退(`partial:true` / 退出码 0),编排器 Bash 重派
  `--resume` 直至完成——对「单次调用必然超时」的超大仓也能收敛。
- 双壳编排器**主动给长跑确定性 Bash 传 per-call `timeout`**;opencode 超时配置项被披露(含 pre-launch 边界)。
- 关闭 `--rebuild-cache` 悬空契约;兑现 spec 既有 callgraph-cache 条款。

**Non-Goals:**
- 不改任何命令的**最终产物 schema**(全 additive)。
- 不对 sast/sra/srr 的确定性脚本做韧性改造(仅给它们的壳加 per-call timeout recipe;reported 缺口是 init)。
- 不切分/重写 callgraph 算法;不引入后台进程/`nohup`/平台特定 spawn;不引第三方依赖。
- 不在开源仓引入任何网络/上传逻辑(与 telemetry seam 无关)。

## Decisions

**FD1 — per-call `timeout` 是跨宿主主杠杆,env 变量是次选。**
claude Bash 与 opencode shell 工具都接受毫秒级 per-call `timeout`,且**会话内即时生效**;而
`OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` 须 opencode 启动前就绪(R5.7:mid-session `export` 不被
opencode 插件进程继承,与 `MGH_*_ACTIVE` 同根因)。故 recipe 以 per-call `timeout` 为主,env 变量作
全局兜底披露。*替代*:仅靠 env 变量(拒——会话内不可改、双壳不对称)。

**FD2 — discover 韧性 = callgraph 缓存 + scan 续点 + 软时限早退 + 原子写;不切分 callgraph。**
callgraph pass2 需**完整** `name_to_files`(name→files)才能解析调用,是 all-or-nothing,无法按目录
chunk 后再合并(否则跨块调用边丢失)。故可 checkpoint 的边界仅两处:(a) index+callgraph 建成 → 落
`cache/callgraph.json`;(b) scan 按文件 → 落 `cache/scan_progress.json`。这两处覆盖了「读全部文件 + 两遍
正则」的主要开销,且对算法零扰动。*替代*:(i) 后台进程 spawn(拒——平台脆弱、违 R5.3 自包含);
(ii) 按目录多次 discover + 合并(拒——每块 callgraph 不完整,合并需新逻辑;用户面已有 `--scope`+`--merge`
逃生口);(iii) 仅调大 timeout(拒——不治全损、不治 >10min 仓)。

**FD3 — 缓存新鲜度按源文件 mtime + manifest。**
缓存侧车 `<out>/cache/manifest.json` 记每个源文件 `(rel, mtime, size)`;重跑比对,任一变更即视为过期。
*替代*:内容 hash(拒——读全文件算 hash 与重建等价开销,违背「缓存省的是重建」初衷)。mtime 粒度
(Windows 较粗)可接受;`--rebuild-cache` 为强制覆盖出口。

**FD4 — 软时限仅在「安全边界」早退,退出码 0 + `partial:true`(非非零)。**
安全边界 = callgraph 建成后、scan 每 `--progress-every` 文件处——**绝不**在 atomic 写的中途(故 FD5 恒成立)。
早退用退出码 0 + stdout `partial:true`/`resume_hint`,**不**用非零码:R5.9 边界校验把退出码 2 当 fail-loud
回退,而 partial 是「推进中」非「失败」。*替代*:非零退出(拒——触发错误的回退语义)。

**FD5 — 原子写 = `.tmp` + `os.replace`(仅 py stdlib)。**
所有产物 JSON 经临时文件 + `os.replace` 落盘(POSIX/Windows 同卷原子),SIGKILL 不留截断 JSON;`.tmp`
残留下次覆盖。*替代*:fsync 链(拒——过度工程;`os.replace` 已足)。

**FD6 — resume 循环 = 编排器 Bash 重派,NEVER wrapper `.py`(R5.2)。**
`partial:true` 的重派由编排器(宿主 agent)按命令壳 recipe 用 Bash 再调 `discover ... --resume`;discover
本身无自循环、无重派。硬边界 `NEVER Write wrapper .py`(承 R5.2 黑盒纪律)。

**FD7 — stdout 契约 additive;`--check` 不变。**
仅增 `partial`(bool)/`resume_hint`(str)(+ 缓存命中标志);`candidates/clusters/unresolved_count/big_files/…`
逐字不变;`--check` 路径不触缓存/续点逻辑,退出码语义不变。

**FD8 — 范围:init 得完整韧性;sast/sra/srr 仅 per-call timeout recipe。**
reported 失败与契约改动都在 init/control-discovery;sast/sra/srr 的长跑脚本(prefilter/dedup/emit_sarif、
prepare/merge、ingest/render)同具潜在超时墙,但本变更只给它们的壳加同形 recipe(小、同因、即时止血),
不对其脚本做韧性改造(留待后续 focused change),以保本变更聚焦、可审。

## Risks / Trade-offs

- [scan_progress 跨运行确定性] → `walk_sources` 枚举顺序若不稳,`scanned_index` 续点会错位。**缓解(FD-OQ1)**:
  discover 在 index 前对物化文件清单**按 rel 路径稳定排序**,使 `scanned_index` 可复现(单测断言)。
- [partial 死循环] → budget 设太小 → 无限重派。**缓解**:编排器 recipe 带 sane 上界(重派次数 ≤ N;超限则
  改建议 `--scope`+`--merge`);stdout `resume_hint` 文本提示。
- [opencode per-call timeout 是否有硬顶 < 600000ms] → web 资料未明。**缓解**:即便有顶,软时限+resume(FD2/FD4)
  是独立安全网(每次调用 budget ≤ 该顶即可推进);OQ 待真机核实。
- [缓存膨胀] → callgraph 大仓可达数十 MB JSON。**缓解**:只存图 dicts(reverse/framework/name_to_files)+
  manifest,**不**存原始文本(每运行重读,O(files) IO 可接受);省的是两遍正则。`cache/` 可 `.gitignore`。
- [`--rebuild-cache` 从悬空→真实] → 旧调用若依赖「argparse 报错」属极不可能;属**收紧**非破坏。**缓解**:
  默认无缓存=每次重建(行为同前),向后兼容。

## Migration Plan

纯 additive:`--time-budget-ms` 默认 0=关(默认路径行为不变);缓存不存在=重建(同前);stdout 仅增字段;
`--rebuild-cache` 真实化(收紧)。部署:随下次 `install.sh` bump 版本号镜像即可。**回滚**:`git revert` +
版本号回退;无 schema/数据迁移;discover 韧性层全部可选(删缓存/续点代码即回到单发行为)。

## Open Questions

- **OQ1**:物化文件清单的稳定排序键(rel 路径字典序)是否对所有目标语言/路径形态(含 Windows 盘符、
  symlink)都给出可复现 `scanned_index`?实施首步用合成多语言仓确定性核验,结论回灌 FD-OQ1。
- **OQ2**:opencode per-call `timeout` 的实际上限是否 ≥ 600000ms?真机首跑核验;若更低,把 recipe 的
  默认推荐值与 `--time-budget-ms` 的协调值(≤ 该顶)写入命令壳,并把软时限+resume 作为主安全网。
- **OQ3**:partial 重派上界 N 取值(初拟按 `ceil(总预算 / budget)`,封顶如 20)——实施时据合成大仓
  实测定,写入 recipe。
