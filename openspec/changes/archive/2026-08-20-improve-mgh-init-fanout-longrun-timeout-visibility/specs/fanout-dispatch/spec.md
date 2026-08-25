> **依赖序**:本 delta MODIFY `fanout-dispatch` 能力的 requirements;该能力由
> `add-mgh-init-scout-fanout-runner`(尚在 changes/ 未归档)首次引入。**本 change MUST 在其
> 归档之后再 archive/apply**(归档序:add-mgh-init-scout-fanout-runner → 本 change)。

## MODIFIED Requirements

### Requirement: Dispatcher 脚本消费 pending 清单并零 LLM 驱动波次

`fanout_runner.py`(stdlib 确定性叶脚本)SHALL 以 `list_scout_batches.py` 的 stdout JSON 为输入
(`--pending-file` 或 stdin,接受其 `pending[]`/`repo`/预算字段原样形态),在脚本内部完成波次循环:
取下 N 个 pending 单元 → 并发 spawn 宿主 CLI 子进程(每单元一个,任务消息 = 固定模板 + 该单元
`pending[]` 字段逐字填充)→ 等待/收集子进程结束 → 依磁盘 `.done`/`.failed` marker 与 ack 重派生
pending → 下一波。波次推进 SHALL 为纯代码逻辑,NEVER 产出中间 LLM 请求;波次数/并发度 SHALL 可由
`--wave N`(默认 5)配置。pending 清单 SHALL 由 dispatcher 内部按 `--orch-budget-bytes` 同源预算
分页消费(复用枚举脚本 stdout 已有的 `offset`/`effective_limit` 语义,dispatcher 对全量 pending
迭代,NEVER 要求编排器翻页)。

**长跑超时关系确定性化**:三级超时自内向外 SHALL 满足不变式
`call-timeout-s × 收敛余量 < time-budget-ms < 宿主 per-call timeout`,且每级留 ≥20% 余量
(在飞波次收敛 = 等最慢子进程跑完,非立即断)。`--call-timeout-s` 默认值 SHALL 为 7200
(单批 = 一次完整 LLM subagent 跑;内网慢接口实测分钟级/批,取 ~4× 余量;宁慢勿杀——单批被杀 →
无 ack 无 marker → 留 pending 重派,浪费一整跑)。`--help` 文案 SHALL 注明该不变式与推荐值。
当调用方传 `--time-budget-ms` 时,dispatcher SHALL 保证在宿主硬超时之前软时限触发(停发新波、
等在飞收敛、退出码 0 + `partial:true`),消除被硬杀的「杀→查盘→重派→又被杀」循环。

#### Scenario: 大量 pending 由脚本波次消化,编排器一次调用

- **WHEN** scout 层有 500 个 pending 批,编排器一次 `Bash` 调用
  `fanout_runner.py`(带 per-call `timeout`)
- **THEN** 脚本以 `--wave` 并发度内部消化全部波次,stdout 摘要报 `partial:false`、`done` 接近
  total;编排器在整个 scout tier 无逐波 LLM 决策回合

#### Scenario: 时间预算耗尽干净早退

- **WHEN** dispatcher 带 `--time-budget-ms` 运行,软时限到达时尚有 pending
- **THEN** 脚本停止发起新波次、等待在飞单元收敛,以退出码 0 + stdout `partial:true` 干净早退;
  编排器重派同一命令直至 `partial:false`

#### Scenario: 软时限先于宿主硬超时触发

- **WHEN** 宿主 per-call timeout = 900000ms,dispatcher 以 `--time-budget-ms 720000` 运行
  (内网慢接口,单批跑数分钟)
- **THEN** dispatcher 在 ~720s 停发新波并等在飞收敛,以退出码 0 + `partial:true` 退出;
  宿主硬超时(900s)NEVER 触发;重派循环的每一轮都是干净早退而非硬杀

#### Scenario: call-timeout 默认值按内网慢接口标定

- **WHEN** 审阅 `py fanout_runner.py --help` 的 `--call-timeout-s` 默认值与文案
- **THEN** 默认 7200s,文案注明三级超时不变式(`call-timeout-s < time-budget-ms < 宿主
  per-call timeout`,每级 ≥20% 余量)与「宁慢勿杀」依据(被杀单批无 marker 留 pending,
  重派浪费一整跑)

### Requirement: dispatcher 是 R5.3 确定性叶脚本

`fanout_runner.py` SHALL 满足确定性叶脚本稳定性契约:runtime 自包含(零运行时依赖,stdlib
`subprocess`/`concurrent.futures`/`argparse`/`json`/`pathlib`;`--help` 即 CLI 契约面)、
stdout=结构化 JSON 与 stderr=诊断严格分流、退出码 `0/1/2`、幂等(`--resume` 复用磁盘 marker
状态)、禁交互式 TTY、闭集参数拒歧义输入、`--time-budget-ms` 软时限 + `partial:true` 干净早退
(退出码 0)。破坏性操作(如 `--purge-audit`)SHALL 带 `--dry-run`。`tools/check_contracts.py`
SHALL 断言双壳/fragment 中出现的每个 `fanout_runner.py` flag 在其 `--help` 中存在;
`install.sh` 自检清单 SHALL 含 `fanout_runner`。

**进度 sidecar**:dispatcher SHALL 于每波结束及每次退出(软时限早退/正常完成)时**原子写**
(`<init-dir>/fanout_progress.json`,stdlib tempfile 原子替换)运行态进度快照,字段 SHALL 至少含
`{ts, host, total, done, failed, pending, wave, waves_run, wave_done_avg_s, eta_batches, state}`,
`state ∈ {running, exited-partial, exited-clean}`。sidecar 是**人面运行态披露件**:编排器与任何
agent SHALL NEVER 读它进上下文(不参与 marker 真相源、不参与 resume 派生);人可经第二终端
(如 `Get-Content -Wait`)实时查看。sidecar 计数 SHALL 与 stdout 摘要同源派生(单测锚定一致)。
该文件是新增运行态产物,非契约产物:`resume_state.py`/`init_manifest.json` 不读不校验它。

#### Scenario: --help 即契约面且 lint 通过

- **WHEN** 运行 `py fanout_runner.py --help` 与 `tools/check_contracts.py`
- **THEN** 全部 flag(`--wave`/`--time-budget-ms`/`--resume`/`--pending-file`/`--host`/…)
    列于 `--help`;壳/fragment 调用面出现的每个 flag 均被 lint 断言存在

#### Scenario: install 自检覆盖新脚本

- **WHEN** 运行 `./install.sh --claude .`
- **THEN** 自检清单含 `fanout_runner.py`,缺失时 warn(CI fail)

#### Scenario: 每波之后 sidecar 反映最新进度

- **WHEN** dispatcher 跑完第 N 波(如 done 347/1000)
- **THEN** `fanout_progress.json` 原子更新为最新计数与 `state:"running"`;人用第二终端查看
  即见进度推进,全程无编排器介入

#### Scenario: 退出时 sidecar 终态与 stdout 摘要一致

- **WHEN** dispatcher 软时限早退(或跑完全部)退出
- **THEN** sidecar `state` = `exited-partial`(或 `exited-clean`),其 `done`/`failed`/`pending`
  计数与 stdout 摘要 JSON 相应字段一致

#### Scenario: 编排器永不读 sidecar

- **WHEN** 审阅命令壳/fragment/`list_steps.py` 契约面与 resume 派生逻辑
- **THEN** 无任何 agent 面指令或脚本把 `fanout_progress.json` 读进编排器上下文;进度查询的
  零 token 路径 = 人直接读文件

### Requirement: 编排器 scout 步调用面切换与回退

`init-stage/scout.md` 派发段与 `list_steps.py --step scout` 契约面 SHALL 增 dispatcher 调用行:
编排器先 `Bash` 跑 `fanout_runner.py`(per-call `timeout`),`partial:true` → 重派同一命令直至
`partial:false`;dispatcher 退出码 2(宿主 CLI 不可用)→ 回退现状波次式手派(既有
`pending[]` 翻页 + 手动 spawn 路径保留,行为不变)。scout 层后续步骤(聚合预算预判
`plan_aggregate.py`、merge/audit、fold-in 级联失效)SHALL 不变。

**调用行超时接线**:scout fragment 的 dispatcher 调用行 SHALL 显式示例 `--time-budget-ms`
(推荐 = 宿主 per-call timeout × 0.8),并注明「MUST < 宿主 per-call timeout」;`list_steps.py`
scout 步 path_recipes SHALL 含软时限重派纪律(重派传 per-call `timeout` > `--time-budget-ms`,
软时限先于宿主硬杀)。**宿主外手动直跑逃生门**:fragment 与 man page SHALL 各注明——大仓长跑
可由人开终端直跑同一 dispatcher 命令(无宿主超时钳制、stderr 逐波进度直读),跑完回会话
`--resume` 接续后续步骤;dispatcher 与编排器以磁盘 marker 为唯一真相源、天然互斥。

#### Scenario: scout fragment 指引 dispatcher-first

- **WHEN** 审阅 `core/prompts/fragments/init-stage/scout.md` 派发段
- **THEN** 派发主路径 = 一次 `Bash` 跃 `fanout_runner.py` + `partial:true` 重派;宿主 CLI
  不可用(退出码 2)时回退手派路径仍在;聚合/merge/fold-in 段未变

#### Scenario: dispatcher 路径下产物等价

- **WHEN** 同一磁盘状态分别经 dispatcher 路径与手派路径跑完 scout 层
- **THEN** 两侧 `.done`/`.failed` marker 集合与 `scout_candidates.json` 语义等价(marker body、
  候选 schema 不变)

#### Scenario: 调用行带软时限示例与手动直跑出口

- **WHEN** 审阅 scout fragment dispatcher 调用行与 mgh-init man page
- **THEN** 调用行示例含 `--time-budget-ms <宿主 per-call timeout × 0.8>` 与「MUST < 宿主
  per-call timeout」提示;两处之一注明「大仓长跑可宿主外直跑同一命令,跑完回会话 `--resume`」

#### Scenario: path_recipes 含软时限重派纪律

- **WHEN** 审阅 `discipline_core.py` scout 步 `path_recipes`
- **THEN** `scout-fanout-dispatcher` recipe 含「重派传 per-call `timeout` > `--time-budget-ms`」
  纪律(软时限先于宿主硬杀,重派 NEVER 退化为硬杀循环)
