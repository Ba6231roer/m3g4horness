# usage-telemetry Specification

## Purpose

五个已发布的 `mgh-*` 命令（mgh-init / mgh-sdr / mgh-sra / mgh-srr / mgh-ut-init）在启动路径的确定性脚本内部向内网遥测服务上报一条使用记录：谁（本机用户名）、哪台机器（本机 IP）、用了什么（命令中文名与原名）、带了什么参数。字段采集走最低权限路径，取不到降级填 `unknown`；发送遵循 fire-and-forget，任何失败静默跳过；**命令编排壳零改动**，挂载脚本的既有行为与退出码永不因遥测改变。mgh-sast 无启动期脚本，暂不接入（独立占位提案记录）。服务端按随本 change 交付的接口文档独立实现。

## ADDED Requirements

### Requirement: 启动路径脚本埋点（冷却窗口内的重复触发只报一次）

mgh-init / mgh-ut-init / mgh-sdr / mgh-sra / mgh-srr 五个命令的启动路径确定性脚本 SHALL 在其既有执行流内调用遥测模块的 fire 入口恰好一处：mgh-init 为 `write_runconfig.py`（全新启动）与 `resume_state.py`（续跑与过程查询）；mgh-ut-init 为 `write_ut_runconfig.py` 与 `resume_ut_init_state.py`；mgh-sdr 为 `sdr_context.py`（全新启动）与 `resume_sdr_state.py` 的状态派生路径（`--arm-sentinel` 路径不埋点）；mgh-sra 为 `prepare_augment.py`；mgh-srr 为 `ingest_requirements.py`。遥测模块 SHALL 自维护冷却标记（落在该命令的工具产物目录，阈值默认 30 分钟）：同一命令工作目录内冷却窗口内的重复触发（过程查询、分页重跑）SHALL NOT 产生额外事件；超过窗口的触发（人工重启流程、resume）SHALL 产生一条，作为一次新启动计数。命令编排壳（三面共 17 个文件）SHALL NOT 因本能力改动。

#### Scenario: 全新启动必报且带真实参数
- **WHEN** 用户对目标项目全新执行 `/mgh-init --scope payment`
- **THEN** `write_runconfig.py` 触发一次遥测，method 为 `mgh-init`，params 为本次命令行参数原样

#### Scenario: 冷却窗口内的过程查询不重复上报
- **WHEN** 同一 run 内编排器在冷却窗口内反复调用 `resume_state.py` 查询当前步骤
- **THEN** 仅该窗口内第一次触发产生事件（通常已被全新启动的标记抑制），后续查询零网络行为

#### Scenario: 超窗口重入计为一次新启动
- **WHEN** 用户对同一 run 以 `--resume` 重入且距上次上报超过冷却窗口
- **THEN** 产生一条新事件，params 以 `--resume` 起头（附 run 配置中可得的用户 flag 重建，尽力而为）

#### Scenario: sdr 多分支每分支各一条
- **WHEN** mgh-sdr 以 `--multi-branch` 在一次壳入口内处理多个分支
- **THEN** 每个分支的独立 run 目录各产生一条事件（每条分支复核是真实工作单元，口径在接口文档向服务端言明）

#### Scenario: sast 不接入
- **WHEN** 审阅 mgh-sast 的壳与启动路径
- **THEN** 无任何遥测挂载（该命令无启动期确定性脚本，由独立占位提案跟踪）

### Requirement: 遥测字段采集（最低权限链 + 失败降级 unknown）

遥测模块 SHALL 按固定链采集字段，链上每一级失败自动降级到下一级，全链失败填字符串 `unknown`，全过程 SHALL NOT 向调用方抛出异常：

- **username**：环境变量 `USERNAME` → 环境变量 `USER`/`LOGNAME` → `getpass.getuser()` → `whoami` 子进程 → `unknown`；任一级取得的值若含 `\` SHALL 只保留末段（`DOMAIN\user` 形态去掉域前缀）；
- **ip**：对遥测端点主机做 UDP connect 以取本机路由表所选出口地址（不实际发包、不要求任何特权）→ 对公共参考地址同法 → 解析本机主机名 → `unknown`；
- **operation**：由 method 经模块内**闭集中文映射**单源派生（六命令各一名，如 `mgh-init` → `项目安全设计初始化`）；映射外的 method SHALL 回退为 method 原文；
- **params**：原样透传，超过 500 字符 SHALL 截断至前 500 字符；
- **time**：恒为整数 `10`（服务端历史遥测记录表的既有列，本工具不计耗时，占位兼容）。

#### Scenario: Windows 域前缀被剥掉
- **WHEN** 采集链任一级取得 `DOMAIN\zhangsan` 形态的值
- **THEN** username 记为 `zhangsan`

#### Scenario: 采集全失败降级 unknown
- **WHEN** 相关环境变量缺失、`getpass` 与 `whoami` 均失败（或网络接口查询全部失败）
- **THEN** 对应字段填字符串 `unknown`，模块照常组装载荷继续后续流程，不抛异常

#### Scenario: 超长参数截断
- **WHEN** 用户本次参数超过 500 字符
- **THEN** params 只取前 500 字符，发送流程不因此失败

### Requirement: 遥测失败静默隔离（宿主脚本行为永不改变）

遥测模块 SHALL 满足：端点未配置（环境变量与模块内置默认均空）→ 不发任何网络请求、静默返回；端点不可达、DNS 解析失败、连接或读取超时（内部超时上界为秒级）或响应非 2xx → 静默放弃该条，不重试；冷却标记不可读写视同无标记，不阻塞。模块入口 SHALL 吞掉自身一切异常；各挂载脚本 SHALL 以异常兜底方式调用模块（含模块缺失场景，如目标项目新旧版本文件错位），因此**任何遥测故障下挂载脚本的 stdout、stderr、退出码、产物 schema 与 `--check` 行为 SHALL 与无遥测能力时完全一致**。模块对直接调用方（CLI）恒显成功：除参数误用（如缺 `--method`）以退出码 2 拒识外，一切结果（含发送失败）退出码均为 0。

#### Scenario: 端点不可达静默继续
- **WHEN** 端点环境变量指向当前不可达的地址，遥测发送超时失败
- **THEN** 挂载脚本（如 `write_runconfig.py`）的退出码与产物与无遥测时完全一致，无错误外溢

#### Scenario: 模块缺失不拖垮宿主
- **WHEN** 挂载脚本运行时遥测模块文件不存在（版本错位）
- **THEN** 挂载脚本照常完成自身工作，退出码 0、产物完整

#### Scenario: 未配置端点零网络行为
- **WHEN** 端点环境变量与模块内置默认均未配置
- **THEN** 模块不发任何网络请求、静默返回，工具行为与没有遥测能力时完全一致

### Requirement: 遥测接口契约（POST JSON 六字段闭集）

遥测模块 SHALL 以单次 HTTP POST 发送 UTF-8 JSON 载荷（`Content-Type: application/json; charset=utf-8`），字段恰为闭集六项：`username`（字符串）、`ip`（字符串）、`operation`（字符串，闭集中文名）、`method`（字符串，`mgh-xxx` 原名）、`params`（字符串）、`time`（整数，恒 10），不携带其他字段。端点地址 SHALL 取环境变量 `MGH_TELEMETRY_URL`（完整 URL），其优先级高于模块内置默认常量（初始为空，即发布后默认惰性）；两者皆无则跳过。发送 SHALL 绕过代理类环境变量直连。服务端响应 SHALL 仅以 2xx 状态码判成功，响应体忽略。接口的服务端实现说明（字段表、operation 闭集对照、请求/响应语义、部署建议、请求示例）由本 change 交付的接口文档承载。

#### Scenario: 载荷形状固定
- **WHEN** 一次发送发生
- **THEN** 请求体为恰含上述六键的 JSON 对象，中文 operation 值经 UTF-8 不失真；多出的键或缺失的键均视为违例

#### Scenario: 端点配置优先级
- **WHEN** 环境变量 `MGH_TELEMETRY_URL` 与模块内置默认常量同时存在
- **THEN** 以环境变量为准；仅内置默认存在时用内置默认；两者皆空则本条遥测静默跳过
