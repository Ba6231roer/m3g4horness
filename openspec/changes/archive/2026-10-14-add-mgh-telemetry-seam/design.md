## Context

本 change 有两版历史：2026-07 初版（能力名 `run-receipt-seam`，「开源仓零网络 + 企业 overlay 外置」，从未实现）；2026-10-14 第一版重做（17 个编排壳各 +1 行埋点调用，fire-and-forget）。第一版在 apply 前被维护者复审判决：**用户只有 ~150K 上下文窗口，壳上下文比什么都宝贵**，遥测这种低价值内容不应加重每次读壳的负担；且当时实测两壳预算已贴顶（dsh mgh-sdr 4997/5000、opencode mgh-ut-init 4976/5000），埋点行还需做预算对冲手术。维护者改拍板：**埋点放进启动路径上已有的确定性脚本内部，壳零改动**，并要求逐命令核实可行性（sast 缓做另立占位提案）。

逐命令启动链核实结果（2026-10-14，读壳与脚本实证）：

| 命令 | 启动路径上已有的确定性脚本 | 结论 |
| --- | --- | --- |
| mgh-init | `write_runconfig.py`（step 0，全新启动必经）；`resume_state.py`（resume 入口与全程查询共用） | 可挂；resume 需冷却判别（见 D6） |
| mgh-ut-init | `write_ut_runconfig.py` / `resume_ut_init_state.py`（与 init 同构） | 可挂，同上 |
| mgh-sdr | **启动初始化本就已脚本化**：step 0 预武装哨兵 = `resume_sdr_state.py --arm-sentinel`（壳明令 NEVER 手写 printf）；step 1 `sdr_context.py` 写 run_config.json（携真实 `--base/--branch/--dimensions` argv）；续跑 = `resume_sdr_state.py` derive | 可挂，且壳零改动 |
| mgh-sra | `prepare_augment.py`（a1 prepare，唯一入口；`--materialize` 分页会多次调用） | 可挂；分页重入需冷却 |
| mgh-srr | `ingest_requirements.py`（唯一入口；`--materialize` 可重跑） | 可挂，同上 |
| mgh-sast | **无**——壳 step 0 没有任何 Python 脚本，哨兵由编排器 printf 写（壳原文自述「sast 无 step-0 Python abs-repo 源」） | 不可挂；接入需先造启动缝（新脚本 + 壳调用行），优先级低 → 占位提案缓做 |

其余约束不变：R2 辖「零 pip 依赖」而非「零网络」（`urllib`/`socket`/`getpass` 均标准库，`test_zero_deps` 以 `sys.stdlib_module_names` 判定自动通过）；用户环境为企业内网受限设备、Windows（域账号）与 Linux 皆有；七个挂载脚本全部已用 `sys.path.insert` 兄弟导入模式（逐一核实），fire 的接入方式与仓库惯例同形。

## Goals / Non-Goals

**Goals:**

- 每条已发布命令（sast 除外）的启动路径上报一条遥测：字段 username / ip / operation / method / params / time 六项闭集。
- 采集全部走最低权限路径，逐级降级、全败填 `unknown`；发送 fire-and-forget，任何失败静默跳过；**挂载脚本的既有行为（stdout/stderr/退出码/产物 schema/时延）在遥测缺席、故障、超时三种情况下完全不变**。
- 17 个编排壳零改动；预算 lint、契约 lint 的现有格局不动。
- 接口文档随本 change 交付，服务端由维护者按文档另行实现；客户端在服务端就绪前默认完全惰性。

**Non-Goals:**

- 不接入 mgh-sast（另立占位提案 `add-mgh-sast-telemetry`，两句话背景，缓做）。
- 不做耗时统计：`time` 恒为 10，只为兼容服务端历史遥测表的既有列。
- 不做重试、本地队列、批量聚合；允许丢数。
- 不追求「编排会话」的精确切分：resume/查询以冷却窗口近似（见 D6 的误差披露）。
- 不做匿名化/哈希：username 存原文（服务端在内网，口径由部署方自决；清掉端点配置即整体停报）。

## Decisions

### D1 — 埋点位置：启动路径既有脚本内 fire（维护者 2026-10-14 拍板，取代第一版的壳埋点）

第一版（壳 +1 行）与第二版（脚本内挂）的实质差异：

| 维度 | 壳埋点（第一版，已废） | 脚本内埋点（选定） |
| --- | --- | --- |
| 壳 token | 每壳 +55–65 tok，两壳需对冲手术 | **0** |
| 触发确定性 | LLM 执行，偶发跳过=少计 | 脚本执行，必达 |
| 覆盖均匀性 | 六命令同一模式 | 逐命令选挂载点（表见 Context），sast 缺口 |
| resume 语义 | 天然精确（壳入口=会话入口） | 冷却窗口近似（D6） |
| 新增风险 | 预算对冲可能伤壳内容保真 | 遥测异常必须与宿主脚本完全隔离（D5） |

拍板理由：用户 150K 上下文窗口比任何东西都宝贵（R5.6 的立规本意），遥测是不太重要的功能，不该占壳；而逐命令核实证明脚本内方案覆盖 5/6 命令。代价（resume 近似、逐脚本隔离义务）都可控且诚实可披露。

### D2 — 挂载点清单（七脚本、八个语义入口）

| # | 脚本 | 命令/时机 | params 来源 | marker_dir |
| --- | --- | --- | --- | --- |
| 1 | `write_runconfig.py` | mgh-init 全新启动 | 真实 argv（`" ".join(sys.argv[1:])`） | `<target>/.mgh-init` |
| 2 | `resume_state.py` | mgh-init resume 入口与全程查询 | `--resume` + run_config.json 内用户 flag 重建（尽力而为） | `<target>/.mgh-init` |
| 3 | `write_ut_runconfig.py` | mgh-ut-init 全新启动 | 真实 argv | `<target>/.mgh-ut-init` |
| 4 | `resume_ut_init_state.py` | mgh-ut-init resume/查询 | 同 #2 | `<target>/.mgh-ut-init` |
| 5 | `sdr_context.py` | mgh-sdr 全新启动（step 1） | 真实 argv（含 `--base/--branch/--dimensions`） | `<run-dir>` |
| 6 | `resume_sdr_state.py` | mgh-sdr 续跑（derive 路径）与查询 | `--resume` + run_config 重建 | `<run-dir>` |
| 7 | `prepare_augment.py` | mgh-sra 入口（a1，分页可重入） | 真实 argv | change 根（与 change_context.json 同目录） |
| 8 | `ingest_requirements.py` | mgh-srr 入口（`--materialize` 可重跑） | 真实 argv | `<out-dir>` |

不挂在 `resume_sdr_state --arm-sentinel` 路径：它虽是精确的 step-0 入口，但发生时 run_config.json 尚未写出、拿不到用户参数（只有 `--run-dir/--repo`），挂了反而产出无意义 params；sdr 全新的上报交给 step 1 的 `sdr_context`（真实 argv + 冷却标记同样盖住它）。

### D3 — 采集链：每字段固定降级序列，全败 `unknown`（与第一版一致）

- **username**：`USERNAME`（Windows，通常已无域）→ `USER`/`LOGNAME`（POSIX）→ `getpass.getuser()` → `whoami` 子进程 → `unknown`；域剥离对**任何一级**取得的值统一生效（按 `\` 取末段）。
- **ip**：对端点主机 UDP `connect()` 后读 `getsockname()`（纯本机路由表查询、不发包、零特权，得「到服务端会走的出口 IP」）→ 公共参考地址同法 → 解析本机主机名 → `unknown`。结果可能是 `127.0.0.1` 或 IPv6，按字符串原样上报。
- **发送**：`urllib.request` 显式空 `ProxyHandler({})` 绕过代理环境变量直连；内部总超时约 2s。

### D4 — 载荷契约：六字段闭集 + `time=10`（与第一版一致）

`username`（已剥域）/ `ip` / `operation`（闭集中文，见 D7）/ `method`（`mgh-xxx` 原名）/ `params`（≤500 字符截断）/ `time`（**恒为整数 10**，服务端历史遥测表既有列，本工具不计耗时）。`Content-Type: application/json; charset=utf-8`；仅 2xx 判成功、响应体忽略；不重试。

### D5 — `mgh_telemetry.py` 双形态与宿主脚本隔离义务

模块同时提供：`fire(method, params, marker_dir)` 供七个挂载脚本导入调用；CLI（`--method`/`--params`/`--marker-dir`）供人调试与单测。`fire` 内部**吞掉一切异常**；挂载侧再用 try 包住 import + 调用（约 4 行）：

```python
try:
    import mgh_telemetry
    mgh_telemetry.fire("mgh-init", " ".join(sys.argv[1:]), run_root)
except Exception:
    pass
```

隔离义务的必要性：挂载点里有 step 0 要害脚本（`write_runconfig` 系），若遥测能让它崩，全体用户启动即挂。两种故障都要防：**模块级故障**（import 失败——如目标项目装了旧版 `mgh-core`、脚本与模块版本错位）由挂载侧 try 兜住；**运行级故障**（网络/磁盘/任何意外）由 `fire` 内部裸 except 兜住。CLI 退出码：一切结果 0（含发送失败——fire-and-forget 的失败不是调用方该处理的错误）、argparse 误用 2；docstring Exit codes 段显式声明该 R5.3 偏差。壳内不再引用本模块，`check_contracts` 不覆盖它，契约由 `--help` 与专属单测承载。

### D6 — resume/查询判别：参数区分不了，用冷却标记

实证：mgh-init 壳里「resume 入口」与「每步执行前查询」对 `resume_state.py` 的调用行**逐字相同**（都是 `py …/resume_state.py --target <target>`），sdr 的续跑 derive 同理——**从参数上无法区分「流程重启」与「过程查询」**。可行判别是模块自维护**冷却标记**：`fire` 写 `<marker_dir>/telemetry_last.json`（时间戳 + method），距上次成功上报不足阈值（模块常量，默认 30 分钟）则静默跳过。效果：

- 全新启动：新 run 目录/新 marker → 必报（#1/#3/#5/#7/#8 真实 argv）。
- resume 入口：距上次活动通常 ≥30 分钟 → 报（#2/#4/#6，params 以 `--resume` 起头重建）。
- 全程反复查询/分页重入：冷却窗口内 → 抑制。
- sdr `--multi-branch`：每分支独立 run-dir → 每分支各一条（每条分支复核是真实工作单元，接口文档向服务端言明该口径）。

**诚实误差**（写进 interface.md 与 README 披露）：长时间 fan-out（>30 分钟）后的过程查询会多计一条；停跑 <30 分钟内的重启会漏计。统计口径 = 「活动窗口开始次数」，不是严格的会话数。阈值取 30 分钟是查询间隔（分钟级）与人工离开时长（通常更长）之间的折中，实现为模块常量便于调。

### D7 — operation 中文命名闭集（单源在模块；与第一版一致）

`mgh-init`→项目安全设计初始化、`mgh-sdr`→安全设计复核、`mgh-sra`→需求安全增强、`mgh-srr`→需求安全评审、`mgh-sast`→静态安全扫描、`mgh-ut-init`→测试约定初始化；映射外 method 回退 method 原文。

### D8 — 端点配置与网络代码进仓边界（与第一版一致）

R2 的产品特性是零 pip 依赖，不是禁网络。端点 = env `MGH_TELEMETRY_URL` > 模块内置默认常量（初始**空** = 发布即惰性）> 静默跳过。服务端就绪后填一行常量或逐机设 env 即激活。未配置时不发任何包。

### D9 — 接口文档落点（与第一版一致）

本 change 内 `interface.md` 即交付物（维护者现在就可以拿去实现服务端）；apply 时落 `docs/mgh-telemetry-api.md`（本 change 需求本身包含写这份文档，属 R5.11 豁免）。分发面（命令壳、`core/contracts/**`、挂载脚本）NEVER 引用该文档。

## Risks / Trade-offs

- [遥测异常波及 step 0 要害脚本] → 双层隔离（D5：fire 内裸 except + 挂载侧 try 包 import）；专测覆盖「模块缺失/网络死亡/磁盘只读」三种故障下宿主脚本退出码与产物不变。
- [resume 计数是近似（D6 误差）] → 已向服务端与使用者双向披露；sdr fresh、各命令 fresh 路径仍精确。
- [每分支一条使 multi-branch 事件数 > 壳入口数] → 口径即「每次真实复核工作」，接口文档言明。
- [挂载脚本 +4 行 × 7 处的维护成本] → 模式统一（同一四行），AGENTS.md 映射表挂到 test_mgh_telemetry。
- [端点配错时每次冷启动多等 ≤~2s] → 未配置 = 零开销；文档建议服务端就绪并连通验证后再下发配置。
- [params 含内网路径] → 服务端在内网；README/AGENTS.md 披露字段集；`MGH_TELEMETRY_URL` 置空即关闭。
- [服务端自签 https 失败] → 客户端不特判证书；接口文档建议内网 http 或有效证书。

## Migration Plan

纯增量、无破坏：新增模块 + 七脚本各几行 + 测试 + install 自检 +1 + 文档披露；壳零改动。回滚 = 端点配置置空（行为即回到无遥测）或移除七处 try 块。服务端实现与接入节奏完全独立。无数据迁移。

## Open Questions

- 无待拍板项。埋点位置（脚本内）、resume 冷却近似、sast 缓做均已是维护者 2026-10-14 拍板项；服务端 URL 待维护者实现后提供（激活方式见 D8）。
