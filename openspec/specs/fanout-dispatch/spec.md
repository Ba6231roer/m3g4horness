# fanout-dispatch Specification

## Purpose

确定性 fan-out 派发基座:产品自带 dispatcher 叶脚本消费枚举脚本的 stdout `pending[]`,以固定模板 +
逐字字段填充构造每个 subagent 的任务消息,spawn 宿主 CLI 并发执行波次循环——派发全程零 LLM 回合,
任务输入由构造保证固定/准确。mgh-init scout 层是首个消费方;T1/T3/sra-augment 同构可复制。

## Requirements

### Requirement: Dispatcher 脚本消费 pending 清单并零 LLM 驱动波次

`fanout_runner.py`(stdlib 确定性叶脚本)SHALL 以 `--tier scout|t1|t3` 参数化消费各自枚举
脚本的 stdout JSON(`--pending-file` 或内部调用枚举 CLI,接受其 `pending[]`/`repo`/预算字段
原样形态):scout → `list_scout_batches.py`、t1 → `list_clusters.py --materialize`、t3 →
`list_rule_jobs.py --materialize`。脚本内部完成波次循环:取下 N 个 pending 单元 → 并发
spawn 宿主 CLI 子进程(每单元一个,任务消息 = 该 tier 固定模板 + 该单元 `pending[]` 字段
逐字填充)→ 等待/收集子进程结束 → 依磁盘 `.done`/`.failed` marker 与 ack 重派生 pending →
下一波。波次推进 SHALL 为纯代码逻辑,NEVER 产出中间 LLM 请求;波次数/并发度 SHALL 可由
`--wave N`(默认 5)配置。pending 清单 SHALL 由 dispatcher 内部按 `--orch-budget-bytes` 同源
预算分页消费(复用枚举脚本 stdout 已有的 `offset`/`effective_limit` 语义,dispatcher 对全量
pending 迭代,NEVER 要求编排器翻页)。既有 scout 调用面(`--scout-plan` 等 flag)SHALL 零
变化(缺省 `--tier` = scout)。

**枚举 stdout `repo` 锚**:三个枚举脚本 stdout SHALL 均携带 `repo`(目标仓绝对根)锚字段,
dispatcher 以之为锚树校验与子进程 cwd 的依据;`list_rule_jobs.py` stdout SHALL 补 `repo`
(取 `--target` 的 resolve 绝对值)。

**T1 scout 闸门透传**:`list_clusters.py` 因 scout 层未完成而退出码 2
(`scout-incomplete-gate`)时,dispatcher SHALL 以退出码 2 fail-loud 并透传其 stderr recipe
(先完成 scout 层),NEVER 将闸门拒识当作单元 crash 进入重派循环。

**长跑超时关系确定性化**:三级超时自内向外 SHALL 满足不变式
`call-timeout-s × 收敛余量 < time-budget-ms < 宿主 per-call timeout`,且每级留 ≥20% 余量
(在飞波次收敛 = 等最慢子进程跑完,非立即断)。`--call-timeout-s` 默认值 SHALL 为 7200
(单批 = 一次完整 LLM subagent 跑;内网慢接口实测分钟级/批,取 ~4× 余量;宁慢勿杀——单批被杀 →
无 ack 无 marker → 留 pending 重派,浪费一整跑)。`--help` 文案 SHALL 注明该不变式与推荐值。
当调用方传 `--time-budget-ms` 时,dispatcher SHALL 保证在宿主硬超时之前软时限触发(停发新波、
等在飞收敛、退出码 0 + `partial:true`),消除被硬杀的「杀→查盘→重派→又被杀」循环。该超时
契约 SHALL 对三个 tier 一致适用(t1/t3 单元 = 一次完整 LLM subagent 跑,同 scout 标定)。

#### Scenario: 大量 pending 由脚本波次消化,编排器一次调用

- **WHEN** 任一 tier(scout/t1/t3)有数百个 pending 单元,编排器一次 `Bash` 调用
  `fanout_runner.py --tier <tier>`(带 per-call `timeout`)
- **THEN** 脚本以 `--wave` 并发度内部消化全部波次,stdout 摘要报 `partial:false`、`done` 接近
  total;编排器在整个 tier 无逐波 LLM 决策回合

#### Scenario: 时间预算耗尽干净早退

- **WHEN** dispatcher 带 `--time-budget-ms` 运行,软时限到达时尚有 pending
- **THEN** 脚本停止发起新波次、等待在飞单元收敛,以退出码 0 + stdout `partial:true` 干净早退;
  编排器重派同一命令直至 `partial:false`

#### Scenario: T1 在 scout 未完成时闸门 fail-loud

- **WHEN** `run_config.json` 启用 scout 而 scout 层未完成,编排器以 `--tier t1` 调用 dispatcher
- **THEN** dispatcher 退出码 2,stderr 透传 `list_clusters.py` 的 scout-incomplete-gate recipe
  (先完成 scout 层);无单元被 spawn、无 crash 重派循环发生

#### Scenario: T3 枚举 stdout 携带 repo 锚

- **WHEN** `list_rule_jobs.py --materialize` 产出一页 pending
- **THEN** stdout JSON 顶层含 `repo`(= `--target` resolve 绝对值),dispatcher 据此锚定锚树
  校验与子进程 cwd;t3 各单元路径字段解析结果均落在该锚树内

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

### Requirement: 任务消息由固定模板与逐字字段填充构造

每个 subagent 的任务消息 SHALL 由 dispatcher 以该 tier 的固定模板文件构造:scout →
`core/prompts/fragments/fanout/scout-task.md`、t1 → `t1-task.md`、t3 → `t3-task.md`
(同目录)。模板内占位符 SHALL 以该单元 `pending[]` 对应字段与运行配置**逐字替换**(字符串
替换,非 LLM 生成);模板外正文所有单元**逐字一致**。填充后 dispatcher SHALL 校验每个路径
占位符的解析结果落在 `repo` 锚树内,任一越树 → 该单元直接记 `failed`(`.failed` marker,
reason=path-drift)、NEVER spawn。占位符集 SHALL 按 tier 取各自的路径字段集:scout/t1 =
`input_path`/`checkpoint_path`/`done_marker`/`failed_marker`/`slice_dir`;t3 =
`input_path`/`rule_path`/`done_marker`/`failed_marker`(无 checkpoint/slice;t3 `rule_path`
双格式路径——claude `.claude/rules/security-<cat>.md` 与 opencode `docs/security-controls/
<cat>.md`——均在 repo 树内,同一锚树校验覆盖)。`chunk_sources_abs`(scout/t1)SHALL 取
`list_steps.py --step <tier>` stdout 的 `script_abs`(绝对、逐字);codegraph 信号取
`run_config.json::codegraph`。t3 模板另填充 `format`(claude|opencode,来自枚举 stdout)。

#### Scenario: 同 run 所有批的任务消息仅字段值不同

- **WHEN** dispatcher 为同一 run 同一 tier 的两个单元(如 scout-001 与 scout-417、或 t1 的
  两个 cluster)构造任务消息并落盘审计副本
- **THEN** 两消息正文逐字一致,差异仅占位符字段的字面值(均来自各自 `pending[]` 项)

#### Scenario: 越树路径在 spawn 前被拦截

- **WHEN** 某 pending 项的 `checkpoint_path`(或 t3 的 `rule_path`)解析后落在 `repo` 锚树外
  (如盘符根)
- **THEN** dispatcher 不 spawn 该单元,直接写 `.failed` marker(reason=path-drift),stdout 摘要
  `failed` 计数 +1;后续波次不受影响

#### Scenario: t3 任务消息携带 format 与 rule_path

- **WHEN** dispatcher 以 `--tier t3` 为 category `authn` 构造任务消息(opencode 格式 run)
- **THEN** 消息含逐字填充的 `rule_path`(`<target>/docs/security-controls/authn.md` 绝对)、
  `format: opencode`、`input_path`/`done_marker`/`failed_marker`;该 category 的 rulewriter
  subagent 恰写 `rule_path` 并 touch `done_marker`

### Requirement: 宿主 CLI 探测与 headless spawn 映射

dispatcher SHALL 探测可用宿主 CLI(`claude` / `opencode`,PATH 查找)并映射为各自的 headless
subagent 调用,agent 名按 tier 参数化:scout → `init-scout-fanout`、t1 → `init-induct-fanout`、
t3 → `init-rulewriter-fanout`(opencode 侧均为 `mode: primary` 的 fanout agent 克隆,install
落位 `.opencode/agent/`;claude 侧经 `--agents` inline JSON 按同名单元装载,工具面白名单
等价于交互路径)。任务消息 SHALL 经 stdin 管道传递(NEVER argv——npm `.cmd` shim 截断多行
argv);子进程 cwd SHALL 为 `repo`(目标项目根)。任一宿主 CLI 均不可用 → 退出码 2
fail-loud,stderr 给出 recipe(回退 = 编排器现状波次式手派,行为不变)。spawn 的子进程
SHALL 继承运行域守卫激活(经磁盘哨兵 `<target>/.mgh-init/.active`,env 不跨进程亦不失效)。

#### Scenario: opencode 可用时走 opencode run

- **WHEN** `opencode` 在 PATH,dispatcher 以 `--tier t1` 派发一个 cluster 单元
- **THEN** 子进程命令形如 `opencode run --agent init-induct-fanout`(消息经 stdin),cwd =
  `repo`;完成后该单元 `.done` marker 出现

#### Scenario: 双 CLI 均缺失 fail-loud

- **WHEN** `claude` 与 `opencode` 均不在 PATH
- **THEN** dispatcher 退出码 2,stderr 说明回退 recipe(编排器按现状波次式手派);无部分 spawn

### Requirement: ack 状态机与 marker 真相源语义承接

dispatcher SHALL 承接既有 fan-out 状态语义:`ok`/`oversize` ack 或磁盘 `.done` marker → 单元
完成;`failed` ack → dispatcher 写该单元 `.failed` marker(body `{unit,reason,tier}`,`tier`
取当前 `--tier` 值;终态、不重试、不阻断当前波次);crash 无 ack 且无 marker → 单元仍
pending → `--resume` 重派(crash ≠ 确认失败)。stdout 摘要 JSON SHALL 报
`{repo, tier, total, done, failed, pending, wave, partial}`,退出码 `0/1/2`(成功含
partial/通用错/误用),stderr 进度与 stdout JSON 严格分流。dispatcher SHALL 幂等:重派已
`.done` 单元 NEVER 再 spawn(以磁盘 marker 为唯一真相源)。

#### Scenario: failed ack 终态且不阻断

- **WHEN** 某单元 subagent 回 `failed <原因>` ack
- **THEN** dispatcher 写 `.failed` marker(body `{unit,reason,tier}`),该单元从后续波次移除,
  其余单元照常推进;stdout 摘要 `failed` 计数 +1

#### Scenario: 子进程 crash 后 resume 重派

- **WHEN** 某子进程异常退出且无任何 marker
- **THEN** 该单元无 `.failed`(crash ≠ 确认失败),`--resume` 重派时再次 spawn

### Requirement: dispatcher 是 R5.3 确定性叶脚本

`fanout_runner.py` SHALL 满足确定性叶脚本稳定性契约:runtime 自包含(零运行时依赖,stdlib
`subprocess`/`concurrent.futures`/`argparse`/`json`/`pathlib`;`--help` 即 CLI 契约面)、
stdout=结构化 JSON 与 stderr=诊断严格分流、退出码 `0/1/2`、幂等(`--resume` 复用磁盘 marker
状态)、禁交互式 TTY、闭集参数拒歧义输入、`--time-budget-ms` 软时限 + `partial:true` 干净早退
(退出码 0)。破坏性操作(如 `--purge-audit`)SHALL 带 `--dry-run`。`tools/check_contracts.py`
SHALL 断言双壳/fragment 中出现的每个 `fanout_runner.py` flag(含 `--tier`)在其 `--help` 中
存在;`install.sh` 自检清单 SHALL 含 `fanout_runner` 与三个 tier 任务模板及 fanout agent
克隆文件。

**进度 sidecar**:dispatcher SHALL 于每波结束及每次退出(软时限早退/正常完成)时**原子写**
运行态进度快照 `<init-dir>/fanout_progress.<tier>.json`(stdlib tempfile 原子替换;scout 由
既有无后缀名 `fanout_progress.json` 改入此命名,旧名残留无害),字段 SHALL 至少含
`{ts, host, tier, total, done, failed, pending, wave, waves_run, wave_done_avg_s,
eta_batches, state}`,`state ∈ {running, exited-partial, exited-clean}`。sidecar 是**人面
运行态披露件**:编排器与任何 agent SHALL NEVER 读它进上下文(不参与 marker 真相源、不参与
resume 派生);人可经第二终端(如 `Get-Content -Wait`)实时查看。sidecar 计数 SHALL 与
stdout 摘要同源派生(单测锚定一致)。该文件是新增运行态产物,非契约产物:
`resume_state.py`/`init_manifest.json` 不读不校验它。

#### Scenario: --help 即契约面且 lint 通过

- **WHEN** 运行 `py fanout_runner.py --help` 与 `tools/check_contracts.py`
- **THEN** 全部 flag(`--tier`/`--wave`/`--time-budget-ms`/`--resume`/`--pending-file`/
    `--host`/…)列于 `--help`;壳/fragment 调用面出现的每个 flag 均被 lint 断言存在

#### Scenario: install 自检覆盖新脚本

- **WHEN** 运行 `./install.sh --claude .`
- **THEN** 自检清单含 `fanout_runner.py` 与 `prompts/fragments/fanout/` 三 tier 模板
    (scout-task/t1-task/t3-task);opencode 安装另覆盖 `init-induct-fanout.md`/
    `init-rulewriter-fanout.md` agent 克隆

#### Scenario: 每波之后 sidecar 反映最新进度

- **WHEN** dispatcher 跑完第 N 波(如 t1 done 87/300)
- **THEN** `fanout_progress.t1.json` 原子更新为最新计数与 `state:"running"`;人用第二终端查看
  即见进度推进,全程无编排器介入

#### Scenario: 退出时 sidecar 终态与 stdout 摘要一致

- **WHEN** dispatcher 软时限早退(或跑完全部)退出
- **THEN** sidecar `state` = `exited-partial`(或 `exited-clean`),其 `done`/`failed`/`pending`
  计数与 stdout 摘要 JSON 相应字段一致

#### Scenario: 编排器永不读 sidecar

- **WHEN** 审阅命令壳/fragment/`list_steps.py` 契约面与 resume 派生逻辑
- **THEN** 无任何 agent 面指令或脚本把 `fanout_progress.<tier>.json` 读进编排器上下文;进度
  查询的零 token 路径 = 人直接读文件

### Requirement: 编排器 fan-out 步调用面切换与回退

`init-stage/{scout,t1,t3}.md` 派发段与 `list_steps.py --step {scout,t1,t3}` 契约面 SHALL 增
dispatcher 调用行:编排器先 `Bash` 跑 `fanout_runner.py --tier <tier>`(per-call
`timeout`),`partial:true` → 重派同一命令直至 `partial:false`;dispatcher 退出码 2(宿主
CLI 不可用 / T1 scout 闸门)→ 回退现状波次式手派(既有 `pending[]` 翻页 + 手动 spawn 路径
保留,行为不变)。各 tier 后续步骤 SHALL 不变(t1 的 T1→T2 `validate_t1_records` 闸门、t3 的
后续 assemble 步、scout 的聚合预算预判/merge/audit/fold-in 级联失效照旧)。

**调用行超时接线**:各 tier fragment 的 dispatcher 调用行 SHALL 显式示例 `--time-budget-ms`
(推荐 = 宿主 per-call timeout × 0.8),并注明「MUST < 宿主 per-call timeout」;`list_steps.py`
各 fan-out 步 path_recipes SHALL 含软时限重派纪律(重派传 per-call `timeout` >
`--time-budget-ms`,软时限先于宿主硬杀)。**宿主外手动直跑逃生门**:各 tier fragment 与
man page SHALL 各注明——大仓长跑可由人开终端直跑同一 dispatcher 命令(无宿主超时钳制、
stderr 逐波进度直读),跑完回会话 `--resume` 接续后续步骤;dispatcher 与编排器以磁盘
marker 为唯一真相源、天然互斥。

#### Scenario: scout fragment 指引 dispatcher-first

- **WHEN** 审阅 `core/prompts/fragments/init-stage/t1.md` 与 `t3.md` 派发段
- **THEN** 派发主路径 = 一次 `Bash` 跑 `fanout_runner.py --tier t1|t3`(带 `--time-budget-ms`)
      + `partial:true` 重派;宿主 CLI 不可用(退出码 2)时回退手派路径仍在;T1→T2 validate
      闸门与 t3 后续 assemble 段未变

#### Scenario: dispatcher 路径下产物等价

- **WHEN** 同一磁盘状态分别经 dispatcher 路径与手派路径跑完同一 tier
- **THEN** 两侧 `.done`/`.failed` marker 集合与该 tier 产物语义等价(T1 checkpoint 记录、
  T3 rule 文件、marker body 不变)

#### Scenario: 调用行带软时限示例与手动直跑出口

- **WHEN** 审阅各 tier fragment dispatcher 调用行与 mgh-init man page
- **THEN** 调用行示例含 `--time-budget-ms <宿主 per-call timeout × 0.8>` 与「MUST < 宿主
      per-call timeout」提示;两处之一注明「大仓长跑可宿主外直跑同一命令,跑完回会话
      `--resume`」

#### Scenario: path_recipes 含软时限重派纪律

- **WHEN** 审阅 `discipline_core.py` t1/t3 步 `path_recipes`
- **THEN** 对应 fanout-dispatcher recipe 含「重派传 per-call `timeout` > `--time-budget-ms`」
      纪律(软时限先于宿主硬杀,重派 NEVER 退化为硬杀循环)
