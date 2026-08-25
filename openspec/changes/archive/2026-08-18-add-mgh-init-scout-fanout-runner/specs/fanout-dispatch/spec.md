## Purpose

确定性 fan-out 派发基座:产品自带 dispatcher 叶脚本消费枚举脚本的 stdout `pending[]`,以固定模板 +
逐字字段填充构造每个 subagent 的任务消息,spawn 宿主 CLI 并发执行波次循环——派发全程零 LLM 回合,
任务输入由构造保证固定/准确。mgh-init scout 层是首个消费方;T1/T3/sra-augment 同构可复制。

## ADDED Requirements

### Requirement: Dispatcher 脚本消费 pending 清单并零 LLM 驱动波次

`fanout_runner.py`(stdlib 确定性叶脚本)SHALL 以 `list_scout_batches.py` 的 stdout JSON 为输入
(`--pending-file` 或 stdin,接受其 `pending[]`/`repo`/预算字段原样形态),在脚本内部完成波次循环:
取下 N 个 pending 单元 → 并发 spawn 宿主 CLI 子进程(每单元一个,任务消息 = 固定模板 + 该单元
`pending[]` 字段逐字填充)→ 等待/收集子进程结束 → 依磁盘 `.done`/`.failed` marker 与 ack 重派生
pending → 下一波。波次推进 SHALL 为纯代码逻辑,NEVER 产出中间 LLM 请求;波次数/并发度 SHALL 可由
`--wave N`(默认 5)配置。pending 清单 SHALL 由 dispatcher 内部按 `--orch-budget-bytes` 同源预算
分页消费(复用枚举脚本 stdout 已有的 `offset`/`effective_limit` 语义,dispatcher 对全量 pending
迭代,NEVER 要求编排器翻页)。

#### Scenario: 大量 pending 由脚本波次消化,编排器一次调用

- **WHEN** scout 层有 500 个 pending 批,编排器一次 `Bash` 调用
  `fanout_runner.py`(带 per-call `timeout`)
- **THEN** 脚本以 `--wave` 并发度内部消化全部波次,stdout 摘要报 `partial:false`、`done` 接近
  total;编排器在整个 scout tier 无逐波 LLM 决策回合

#### Scenario: 时间预算耗尽干净早退

- **WHEN** dispatcher 带 `--time-budget-ms` 运行,软时限到达时尚有 pending
- **THEN** 脚本停止发起新波次、等待在飞单元收敛,以退出码 0 + stdout `partial:true` 干净早退;
  编排器重派同一命令直至 `partial:false`

### Requirement: 任务消息由固定模板与逐字字段填充构造

每个 subagent 的任务消息 SHALL 由 dispatcher 以固定模板文件
(`core/prompts/fragments/fanout/scout-task.md`)构造:模板内占位符(如 `{{input_path}}`、
`{{checkpoint_path}}`、`{{done_marker}}`、`{{failed_marker}}`、`{{slice_dir}}`、
`{{chunk_sources_abs}}`、`{{repo}}`、`{{codegraph}}`)SHALL 以该单元 `pending[]` 对应字段与运行
配置**逐字替换**(字符串替换,非 LLM 生成);模板外正文所有单元**逐字一致**。填充后 dispatcher
SHALL 校验每个路径占位符的解析结果落在 `repo` 锚树内,任一越树 → 该单元直接记 `failed`
(`.failed` marker,reason=path-drift)、NEVER spawn。`chunk_sources_abs` SHALL 取
`list_steps.py --step scout` stdout 的 `script_abs`(绝对、逐字);codegraph 信号取
`run_config.json::codegraph`。

#### Scenario: 同 run 所有批的任务消息仅字段值不同

- **WHEN** dispatcher 为同一 run 的 scout-001 与 scout-417 构造任务消息并落盘审计副本
- **THEN** 两消息正文逐字一致,差异仅占位符字段的字面值(均来自各自 `pending[]` 项);

#### Scenario: 越树路径在 spawn 前被拦截

- **WHEN** 某 pending 项的 `checkpoint_path` 解析后落在 `repo` 锚树外(如盘符根)
- **THEN** dispatcher 不 spawn 该单元,直接写 `.failed` marker(reason=path-drift),stdout 摘要
  `failed` 计数 +1;后续波次不受影响

### Requirement: 宿主 CLI 探测与 headless spawn 映射

dispatcher SHALL 探测可用宿主 CLI(`claude` / `opencode`,PATH 查找)并映射为各自的 headless
subagent 调用:claude → `claude -p <任务消息> <agent 装载 flags>`,opencode →
`opencode run --agent init-scout <任务消息>`;子进程 cwd SHALL 为 `repo`(目标项目根)。任一宿主
CLI 均不可用 → 退出码 2 fail-loud,stderr 给出 recipe(回退 = 编排器现状波次式手派,行为不变)。
spawn 的子进程 SHALL 继承运行域守卫激活(经磁盘哨兵 `<target>/.mgh-init/.active`,env 不跨进程
亦不失效)。claude 侧 init-scout agent 定义 SHALL 可被 headless 寻址(install 落位
`.claude/agents/init-scout.md` 或等效),且 spawn flags SHALL 限定工具面
(`--allowedTools`/permission)与 stage 提示词装载等价于交互路径。

#### Scenario: opencode 可用时走 opencode run

- **WHEN** `opencode` 在 PATH,dispatcher 派发一个 scout 批
- **THEN** 子进程命令形如 `opencode run --agent init-scout "<任务消息>"`,cwd = `repo`;
  完成后该批 `.done` marker 出现

#### Scenario: 双 CLI 均缺失 fail-loud

- **WHEN** `claude` 与 `opencode` 均不在 PATH
- **THEN** dispatcher 退出码 2,stderr 说明回退 recipe(编排器按现状波次式手派);无部分 spawn

### Requirement: ack 状态机与 marker 真相源语义承接

dispatcher SHALL 承接既有 fan-out 状态语义:`ok`/`oversize` ack 或磁盘 `.done` marker → 单元
完成;`failed` ack → dispatcher 写该单元 `.failed` marker(body `{unit,reason,tier}`,终态、不重试、
不阻断当前波次);crash 无 ack 且无 marker → 单元仍 pending → `--resume` 重派(crash ≠ 确认
失败)。stdout 摘要 JSON SHALL 报 `{repo, total, done, failed, pending, wave, partial}`,退出码
`0/1/2`(成功含 partial/通用错/误用),stderr 进度与 stdout JSON 严格分流。dispatcher SHALL
幂等:重派已 `.done` 单元 NEVER 再 spawn(以磁盘 marker 为唯一真相源)。

#### Scenario: failed ack 终态且不阻断

- **WHEN** 某批 subagent 回 `failed <原因>` ack
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
SHALL 断言双壳/fragment 中出现的每个 `fanout_runner.py` flag 在其 `--help` 中存在;
`install.sh` 自检清单 SHALL 含 `fanout_runner`。

#### Scenario: --help 即契约面且 lint 通过

- **WHEN** 运行 `py fanout_runner.py --help` 与 `tools/check_contracts.py`
- **THEN** 全部 flag(`--wave`/`--time-budget-ms`/`--resume`/`--pending-file`/`--host`/…)
    列于 `--help`;壳/fragment 调用面出现的每个 flag 均被 lint 断言存在

#### Scenario: install 自检覆盖新脚本

- **WHEN** 运行 `./install.sh --claude .`
- **THEN** 自检清单含 `fanout_runner.py`,缺失时 warn(CI fail)

### Requirement: 编排器 scout 步调用面切换与回退

`init-stage/scout.md` 派发段与 `list_steps.py --step scout` 契约面 SHALL 增 dispatcher 调用行:
编排器先 `Bash` 跑 `fanout_runner.py`(per-call `timeout`),`partial:true` → 重派同一命令直至
`partial:false`;dispatcher 退出码 2(宿主 CLI 不可用)→ 回退现状波次式手派(既有
`pending[]` 翻页 + 手动 spawn 路径保留,行为不变)。scout 层后续步骤(聚合预算预判
`plan_aggregate.py`、merge/audit、fold-in 级联失效)SHALL 不变。

#### Scenario: scout fragment 指引 dispatcher-first

- **WHEN** 审阅 `core/prompts/fragments/init-stage/scout.md` 派发段
- **THEN** 派发主路径 = 一次 `Bash` 跃 `fanout_runner.py` + `partial:true` 重派;宿主 CLI
  不可用(退出码 2)时回退手派路径仍在;聚合/merge/fold-in 段未变

#### Scenario: dispatcher 路径下产物等价

- **WHEN** 同一磁盘状态分别经 dispatcher 路径与手派路径跑完 scout 层
- **THEN** 两侧 `.done`/`.failed` marker 集合与 `scout_candidates.json` 语义等价(marker body、
  候选 schema 不变)
