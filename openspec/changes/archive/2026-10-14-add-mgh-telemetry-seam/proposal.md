# add-mgh-telemetry-seam

> **人话序**：运维方想回答「这套安全工具族谁在用、用得多不多」，但现在工具装进企业内网项目里跑，没有任何使用记录。根因是各命令启动时没有上报环节。本 change 把遥测埋点放进**各命令启动路径上已有的确定性脚本内部**（init/ut-init 的 runconfig 写入脚本、sdr 的上下文与续跑脚本、sra/srr 的入口脚本），调用一个独立遥测小模块：把本机用户名（去掉域前缀）、本机 IP、命令中文名、命令原名、执行参数发给内网遥测服务，另带恒为 10 的 `time` 字段（服务端历史表遗留列，占位兼容）。采集走最低权限做法，取不到填 `unknown`；发送失败或没配地址就静默跳过；**17 个命令壳一个字都不动**，用户 150K 上下文零新增负担。验证方式：遥测模块单测覆盖采集降级、冷却窗口与失败隔离；七个挂载脚本各自补「fire 被调且异常被吞」用例；接口文档随本 change 交付，服务端按文档实现后配一个地址即可看到记录。

## Why

企业内网部署 `mgh-*` 工具族之后，部署方无法回答「谁在用、用了哪些命令、用得频不频」：工具目前没有任何上报环节。需要一个轻量的使用遥测通道——命令启动即上报一次，尽力而为、允许丢弃，且在任何受限设备（无管理员权限、弱网、未配服务）上都零影响。

**埋点位置的决策过程**（2026-10-14，两轮）：第一版 propose 选了「17 个编排壳各加一行埋点调用」；维护者复审判定**壳上下文比什么都宝贵**（用户只有 ~150K 上下文窗口，壳常驻历史，遥测这种低价值内容不该占壳 token），改为脚本内埋点。经逐命令核实启动链，脚本内方案可行：init 家族有 `write_runconfig` 系、sdr 的启动初始化本就已脚本化（哨兵预武装/run_config 都是脚本副作用）、sra/srr 有单一入口脚本；唯一没有启动脚本的 mgh-sast 优先级低，另立占位提案缓做。

> 本 change 于 2026-07 曾提案过一版（能力名 `run-receipt-seam`，思路是「开源仓零网络 + 企业 overlay 外置上传」）。该约束前提已被维护者推翻：本工具族的实际运行方就是企业内网部署组织，遥测网络调用直接进仓。旧增量从未实现、主规格中也无 `run-receipt-seam`，本版整体取代，删除旧 delta。

## What Changes

- 新增确定性模块 `core/scripts/mgh_telemetry.py`（仅标准库，**可导入 + 可 CLI 双形态**）：`fire(method, params, marker_dir)` 完成采集与上报——username（Windows 域前缀剥离，五级降级链）→ IP（本机路由表查询，不发包、不要求特权）→ operation（由 method 经模块内闭集中文映射单源派生）→ params（超 500 字符截断）→ `time` 恒为整数 10；单次 HTTP POST（UTF-8 JSON）发往配置端点；**冷却标记**（默认 30 分钟）落工具产物目录，同一 run 的反复查询不重复上报；发送失败、超时、端点未配置一律静默跳过；`fire` 自身绝不抛异常。
- **七个挂载点**（均为已存在的启动路径脚本，壳零改动）：`write_runconfig.py`（mgh-init 全新启动）、`resume_state.py`（mgh-init resume/查询）、`write_ut_runconfig.py` + `resume_ut_init_state.py`（mgh-ut-init 同构）、`sdr_context.py` + `resume_sdr_state.py`（mgh-sdr 全新启动/续跑）、`prepare_augment.py`（mgh-sra 入口）、`ingest_requirements.py`（mgh-srr 入口）。
- **mgh-sast 不在本 change 内接入**（无启动期 Python 脚本，接入需先为其造启动缝，优先级低）：另立占位提案 `add-mgh-sast-telemetry` 记录背景，缓做。
- 新增能力规格 `usage-telemetry`；删除旧版 `run-receipt-seam` delta（见 Why）。
- 交付**遥测接口文档**（本 change 内 `interface.md`，apply 时落维护者文档区 `docs/mgh-telemetry-api.md`）：字段表、闭集中文 operation 对照、请求/响应语义、部署建议与请求示例，供服务端按契约独立实现。该文档属于「交付物本身」，是 R5.11 对 `docs/` 路径禁令的豁免对象。
- 配套面：`install.sh` 共定位自检清单 +`mgh_telemetry`；新增 `tests/test_mgh_telemetry.py` + 七个挂载脚本既有测试各补一条隔离用例；AGENTS.md（R2 stdlib 模块列举、改动面→测试映射表、诚实边界）与 README 各补使用统计披露；`docs/glossary.md` 补「遥测/埋点/端点」词条。

## Capabilities

### New Capabilities
- `usage-telemetry`：`mgh-*` 命令启动路径上的脚本内使用遥测——挂载点与触发语义（全新启动必报、resume/查询按冷却窗口近似会话切分）、字段采集的最低权限链与 `unknown` 降级、失败静默隔离（宿主脚本行为与退出码永不改变）、HTTP 载荷六字段闭集契约与端点配置优先级。

### Modified Capabilities
<!-- 无。遥测是横切的新观测能力，其要求在新 capability 内以「每条已发布 mgh-* 命令的启动路径脚本」表述，
     不拆改 control-discovery / security-design-review 等既有能力的任何 requirement。 -->

## Impact

- **代码**：新增 `core/scripts/mgh_telemetry.py` + `tests/test_mgh_telemetry.py`；七个既有脚本各 +少量行（try 包裹的 import + fire 调用）；`install.sh` 自检清单 +1。**17 个编排壳零改动**。
- **壳预算（R5.6）**：零影响——dsh mgh-sdr（4997/5000）等紧预算壳不再被触碰，第一版方案的最大落地风险（预算对冲手术）随之消除。
- **契约面变化**：壳内不再有 `mgh_telemetry.py` 调用，`tools/check_contracts.py` 不覆盖遥测；模块契约由 `--help` docstring + 专属单测承载。
- **铁律对齐**：R2 零 pip 依赖不变——`urllib`/`socket`/`getpass` 均标准库，`test_zero_deps` 以 `sys.stdlib_module_names` 判定自动通过；R5.3 契约有一处**有意偏差**（发送失败也退出码 0，见 design D5）；挂载脚本的既有 I/O 契约（stdout/stderr/退出码/产物 schema）零变化；R5.10 分发纯净——新脚本不含研发语境指针。
- **诚实边界**：遥测是尽力而为的统计——resume 计数是**冷却窗口近似**（长时间 fan-out 后的查询会多计、短间隔重启会漏计，见 design D6）；未配置端点时工具完全不上网；params 可能含项目路径等内网信息，服务端在内网、README 与 AGENTS.md 向使用者披露。
