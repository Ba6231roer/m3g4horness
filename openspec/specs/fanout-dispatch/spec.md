# fanout-dispatch Specification

## Purpose

确定性 fan-out 派发基座:产品自带 dispatcher 叶脚本消费枚举脚本的 stdout `pending[]`,以固定模板 +
逐字字段填充构造每个 subagent 的任务消息,spawn 宿主 CLI 并发执行波次循环——派发全程零 LLM 回合,
任务输入由构造保证固定/准确。mgh-init scout 层是首个消费方;T1/T3/sra-augment 同构可复制。

## Requirements

### Requirement: Dispatcher 脚本消费 pending 清单并零 LLM 驱动槽位补位循环

`fanout_runner.py`(stdlib 确定性叶脚本)SHALL 以 `--tier scout|t1|t2|t3|sdr` 参数化消费各自枚举
脚本的 stdout JSON(`--pending-file` 或内部调用枚举 CLI,接受其 `pending[]`/`repo`/预算字段
原样形态):scout → `list_scout_batches.py`、t1 → `list_clusters.py --materialize`、t2 →
`plan_aggregate.py --node t2`、t3 → `list_rule_jobs.py --materialize`、sdr → `diff_group.py`。
派发 SHALL 为**槽位补位循环**而非波次屏障:在飞子进程数 SHALL ≤ `--wave N`(默认 5);
任一单元到达终态(ok/failed/timeout/stall/crash)SHALL 立即从 pending 队列取下一单元补位
spawn,NEVER 等待同批全部收敛。补位取下一单元前 SHALL 对其 `.done`/`.failed` marker 做
存在性懒校验(marker 已存在 → 跳过不 spawn,取再下一单元);队列耗尽且在飞归零后 SHALL 按
磁盘 marker 重派生终态汇总。单元终态判定与 marker 真相源语义不变(见 ack 状态机 requirement);
一个在飞单元挂死 SHALL 只占用其槽位,NEVER 阻断其余槽位的派发与推进。循环全程 SHALL 零
LLM 请求;`--wave` 为在飞并发上限;心跳行 `wave=` 字段 SHALL 为该单元在本 run 内的派发序号,
sidecar `waves_run` SHALL 为累计派发单元数(字段名不变,语义重定义)。

**枚举 stdout `repo` 锚**:枚举脚本 stdout SHALL 均携带 `repo`(目标仓绝对根)锚字段,
dispatcher 以之为锚树校验与子进程 cwd 的依据。

**T1 scout 闸门透传**:`list_clusters.py` 因 scout 层未完成而退出码 2
(`scout-incomplete-gate`)时,dispatcher SHALL 以退出码 2 fail-loud 并透传其 stderr recipe
(先完成 scout 层),NEVER 将闸门拒识当作单元 crash 进入重派循环。sdr 枚举 gate 形退出码 2
同形透传。

**四级超时关系确定性化 + 启动校验**:自内向外四级 SHALL 满足不变式
`--stall-timeout-s(失活)< --call-timeout-s(绝对兜底)× 收敛余量 < time-budget-ms <
宿主 per-call timeout`,且每级留 ≥20% 余量。`--call-timeout-s` 默认值 SHALL 为 7200
(宁慢勿杀依据不变);新增 `--stall-timeout-s` 默认 900(字节级失活判定,见失活检测
requirement;healthy 单元分钟级,5× 余量)。**dispatcher SHALL 在 spawn 任何单元前校验**:
调用方传 `--time-budget-ms` 时 MUST 同时显式传 `--call-timeout-s` 且其值 `< time-budget-ms × 0.8`,
且 `--stall-timeout-s < --call-timeout-s`——违反 SHALL 退出码 2 + 可操作 recipe(给出合规
取值示例),NEVER 带违例不变式进入派发(默认 `--call-timeout-s 7200` 大于任何小时级宿主
预算,静默错配必然退化为宿主硬杀循环);未传 `--time-budget-ms`(宿主外手动直跑)时
默认值组合 SHALL 可用,stderr 打一次性提示。当调用方传 `--time-budget-ms` 时,dispatcher
SHALL 保证在宿主硬超时之前软时限触发(停发新补位、等在飞收敛——失活检测保证收敛有界——
退出码 0 + `partial:true`)。该超时契约 SHALL 对全部 tier 一致适用。

#### Scenario: 大量 pending 由槽位补位循环消化,编排器一次调用

- **WHEN** 任一 tier 有数百个 pending 单元,编排器一次 `Bash` 调用
  `fanout_runner.py --tier <tier>`(带 per-call `timeout`)
- **THEN** 脚本以 ≤ `--wave` 在飞补位循环内部消化全部单元,stdout 摘要报 `partial:false`、
  `done` 接近 total;编排器在整个 tier 无逐单元 LLM 决策回合

#### Scenario: 单个在飞挂死只废一槽,其余槽位继续推进

- **WHEN** 某在飞单元的子进程挂死无输出,同批其余单元陆续到达终态
- **THEN** dispatcher 在其余单元终态时立即补位派发后续单元,done 计数持续增长;挂死单元占
  槽至失活判定(或 call-timeout)被树杀后留 pending;全 run 推进 NEVER 停摆

#### Scenario: 补位前 marker 懒校验跳过已完成单元

- **WHEN** 补位取到的下一单元其 `.done`(或 `.failed`)marker 已在磁盘
- **THEN** dispatcher 不 spawn 该单元,直接取后续单元;磁盘 marker 仍是唯一真相源,已终态
  单元 NEVER 再次 spawn

#### Scenario: 时间预算耗尽干净早退

- **WHEN** dispatcher 带 `--time-budget-ms` 运行,软时限到达时尚有 pending
- **THEN** 脚本停止发起新补位、等在飞单元收敛(失活检测保证收敛有界),以退出码 0 +
  stdout `partial:true` 干净早退;编排器重派同一命令直至 `partial:false`

#### Scenario: 超时不变式违例 spawn 前 fail-loud

- **WHEN** 调用传 `--time-budget-ms 720000` 但未显式传 `--call-timeout-s`(默认 7200 ≥
  budget×0.8),或 `--stall-timeout-s ≥ --call-timeout-s`
- **THEN** dispatcher 退出码 2,stderr recipe 给出合规取值示例(如
  `--call-timeout-s 540 --stall-timeout-s 300`);零单元被 spawn、零枚举副作用

#### Scenario: 手动直跑(无 budget)默认组合可用

- **WHEN** 人开终端直跑 `fanout_runner.py --tier t1`(不传 `--time-budget-ms`)
- **THEN** 默认 `--stall-timeout-s 900 < --call-timeout-s 7200` 校验通过,正常运行;
  stderr 一次性提示(宿主外直跑无宿主超时钳制)

#### Scenario: T1 在 scout 未完成时闸门 fail-loud

- **WHEN** `run_config.json` 启用 scout 而 scout 层未完成,编排器以 `--tier t1` 调用 dispatcher
- **THEN** dispatcher 退出码 2,stderr 透传 `list_clusters.py` 的 scout-incomplete-gate recipe
  (先完成 scout 层);无单元被 spawn、无 crash 重派循环发生

#### Scenario: 软时限先于宿主硬超时触发

- **WHEN** 宿主 per-call timeout = 900000ms,dispatcher 以 `--time-budget-ms 720000
  --call-timeout-s 540 --stall-timeout-s 300` 运行
- **THEN** dispatcher 在 ~720s 停发新补位并等在飞收敛,以退出码 0 + `partial:true` 退出;
  宿主硬超时(900s)NEVER 触发;重派循环的每一轮都是干净早退而非硬杀

#### Scenario: call-timeout 与 stall-timeout 默认值按内网慢接口标定

- **WHEN** 审阅 `py fanout_runner.py --help` 的 `--call-timeout-s`/`--stall-timeout-s`
  默认值与文案
- **THEN** 默认 7200s / 900s,文案注明四级超时不变式与「宁慢勿杀」依据(被杀单批无 marker
  留 pending,重派浪费一整跑)、失活判定的低误杀余量(healthy 单元分钟级 ×5)

### Requirement: 任务消息由固定模板与逐字字段填充构造

fan-out 任务消息 SHALL 由固定模板 + 逐字字段填充构造:`fanout_runner.py` 内嵌 tier
模板(t1/t3/scout 共用同一占位符替换机制),同一 run 内所有单元的任务消息除字段值外逐字节
相同;占位符替换 SHALL 是纯字符串替换(无逻辑分支、无条件拼装)。模板 SHALL 携带且仅携带
per-unit 输入字段 + 行为加载指令(行为规则单一真相源在 stage 提示词,模板 NEVER 内嵌行为
逻辑)。编排器/派发器手派路径 SHALL 从同形 stdout 字段逐字填充,NEVER 手拼。

**stage 提示词位置硬钉(防漫游)**:任务模板 SHALL 把 stage 提示词路径钉死为**唯一位置**
——`{{repo}}` 内的 mgh-core 安装路径(`{{repo}}/.claude/mgh-core/prompts/stages/<stage>.md` 或
`{{repo}}/.opencode/mgh-core/prompts/stages/<stage>.md`),并 SHALL 携带硬边界:该路径
`Read` 失败(文件不存在/不可读)时 subagent SHALL **立即**回
`failed mgh-core prompts not installed at <path>` ack,**NEVER** 到其他目录(父项目、
`/home`、`/adhome`、兄弟项目、系统目录)搜索提示词或脚本——真机形态是 mgh-core 只装在根
项目而 run 在独立子项目执行,正确行为是显式失败上浮(编排器写 `.failed`),由用户安装后
`--resume`,而非跨目录漫游。

#### Scenario: 同 run 所有批的任务消息仅字段值不同
- **WHEN** dispatcher 对同一 tier 的多个单元构造任务消息
- **THEN** 除 `{{占位符}}` 字段值外,所有消息逐字节相同(模板固定、纯替换)

#### Scenario: 越树路径在 spawn 前被拦截
- **WHEN** 枚举 stdout 的某单元路径字段解析在 target 树外
- **THEN** 该单元标 failed(reason=path-drift)且 NEVER spawn

#### Scenario: t3 任务消息携带 format 与 rule_path
- **WHEN** T3 tier 派发
- **THEN** 任务消息携带 `{{format}}` 与 `{{rule_path}}` 字段(逐字来自 stdout)

#### Scenario: stage 提示词路径在任务消息中硬钉唯一位置
- **WHEN** 审阅任一 fan-out 任务模板(t1/scout/t3 同形)
- **THEN** 模板把 stage 提示词路径钉死为 `{{repo}}` 内 mgh-core 安装路径的唯一位置表述
  (「行为定义于该文件,先 Read 并严格遵循」),并含硬边界:Read 失败 → 立即
  `failed mgh-core prompts not installed` ack、NEVER 跨目录搜索提示词/脚本

#### Scenario: mgh-core 未安装时 subagent 显式失败而非漫游
- **WHEN** mgh-core 只装在根项目、run 在独立子项目,subagent Read 模板钉死的提示词路径失败
- **THEN** subagent 回 `failed mgh-core prompts not installed at <path>` ack(编排器写
  `.failed` marker),NEVER 发起对 `/home`、`/adhome`、父项目或其他目录的任何读取

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
`.done` 单元 NEVER 再 spawn(以磁盘 marker 为唯一真相源)。**marker 真相源的读取 SHALL
与其写入同源**:dispatcher 每波重派生 pending 时消费的枚举脚本 stdout,其 done/failed
判定 SHALL 由正向 marker 路径计算产生(见 `request-context-budget` 能力同名 requirement);
dispatcher SHALL NEVER 自行从记录体字段或文件名 stem 反推单元身份。

#### Scenario: failed ack 终态且不阻断

- **WHEN** 某单元 subagent 回 `failed <原因>` ack
- **THEN** dispatcher 写 `.failed` marker(body `{unit,reason,tier}`),该单元从后续波次移除,
  其余单元照常推进;stdout 摘要 `failed` 计数 +1

#### Scenario: 子进程 crash 后 resume 重派

- **WHEN** 某子进程异常退出且无任何 marker
- **THEN** 该单元无 `.failed`(crash ≠ 确认失败),`--resume` 重派时再次 spawn

#### Scenario: 已完成单元在重派生 pending 时消失

- **WHEN** 上一波某单元已写 `.json` 记录 + touch `.done` marker(含超长 id 截断编码文件名),
  dispatcher 进入下一波重派生 pending
- **THEN** 该单元不在新 `pending[]` 中(正向 marker 路径判定 done),NEVER 再次 spawn

### Requirement: 波次零推进收敛熔断(滚动磁盘进度窗口)

dispatcher SHALL 检测**零磁盘推进循环**:熔断观察点 SHALL 为以下两处——(a) 每新派发
K 个单元(K = `--stall-waves` × `--wave`);(b) 队列耗尽且在飞归零后重派生发现仍有待派
单元时(治「队列只剩坏死单元永远凑不满 K」的尾巴形态)。每个观察点从磁盘重派生一次
done+failed 终态计数(marker 唯一真相源);连续 `--stall-waves`(默认 2)次重派生计数
零增加、且队列仍有待派单元 → 视为收敛失败,**停止派发**,以退出码 2 fail-loud;stdout 摘要 JSON SHALL 报
`stalled:true` + `stalled_pending[]`(每个卡住单元的 id + 其 `.done`/`.failed` marker 在磁盘
上的实际存在性),stderr 给诊断 recipe(停止重派;跑 `resume_state.py --check` 诊断磁盘状态;
对照本摘要逐单元排查 marker 可写性/身份漂移)。单元失活被树杀属于终态事件但**不增加磁盘
计数**——同一单元反复失活(确定性挂死)SHALL 由本熔断截断并在 `stalled_pending[]` 披露。
正常早退(`partial:true`)、正常完成(`partial:false`)路径行为不变。理由〔窗口重锚:槽位
补位下不存在波次边界,判定锚平移为滚动磁盘进度;既治「每轮全量重派、磁盘进度恒零」的身份/
权限漂移,也治「同一单元确定性挂死反复烧」〕。

#### Scenario: 确定性挂死单元被熔断截断

- **WHEN** 某单元每次派发都失活被树杀(无 marker),其后续单元正常推进一波后队列只剩该单元
- **THEN** 连续 2 个滚动窗口磁盘计数零增加且该单元仍待派 → dispatcher 停止派发,退出码 2,
  stdout `stalled:true` + `stalled_pending[]`(该单元 id + marker 均不存在),stderr 含
  resume_state 诊断 recipe

#### Scenario: 失活杀后重派成功不触发熔断

- **WHEN** 某单元一次失活被树杀,重派后正常完成(done 计数增加)
- **THEN** 熔断不触发(计数窗口重置),dispatcher 照常继续

#### Scenario: 正常 partial 早退路径不受影响

- **WHEN** `--time-budget-ms` 软时限触发干净早退,窗口内 `done+failed` 有推进
- **THEN** 行为与熔断引入前逐字一致(退出码 0 + `partial:true`,编排器重派)

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

### Requirement: Dispatcher liveness 登记(启动写、退出删、波次记子进程)

`fanout_runner.py` 派发模式(非 `--kill-stale`/`--purge-audit`)启动时 SHALL 原子写 liveness
文件 `<init-dir>/fanout_runner.<tier>.pid`(body `{pid, started_ts, tier, host, cmdline,
children[]}`;`pid` = 当前进程 PID,`cmdline` = `sys.argv` 原样列表;`children[]` = 当前
在飞宿主 CLI 子进程的 `{pid, unit, tier}` 列表,每波 spawn 后原子更新——子进程经
`subprocess.Popen` spawn 以取得 PID),任一退出路径(正常完成、partial 早退、异常退出)
SHALL 删除之(try/finally 兜底;进程被硬杀时文件残留——残留文件由 `--kill-stale` 的 PID
存活检测消歧,非错误)。该文件是**人机两用孤儿信号**:编排器/后续 resume 据此检出「还有
(或曾有)fanout 在跑」,不作为进度真相源(进度真相源仍是磁盘 marker)。

#### Scenario: 派发运行期间 liveness 文件存在且含在飞子进程

- **WHEN** runner 以派发模式运行(tier 任一)且已进入波次循环
- **THEN** `<init-dir>/fanout_runner.<tier>.pid` 存在,body 携带当前进程 PID、`tier`/`host`
  与 `children[]`(在飞子进程 PID + 单元 id)

#### Scenario: 干净退出删除 liveness 文件

- **WHEN** runner 完成(含 `partial:true` 早退)退出
- **THEN** liveness 文件不存在;再次以同参运行不会把旧文件误判为活跃实例

### Requirement: `--kill-stale` 检出并清理孤儿 runner 进程树(含 runner 已死的存活子进程)

`fanout_runner.py --kill-stale --tier <t> --checkpoints <dir> --inputs-dir <dir>`(其余 tier
artifact flag 同派发模式)SHALL 处理 liveness 文件的两种残留形态:
① runner PID 仍存活且 cmdline 含 `fanout_runner.py` → 杀整个进程树(Windows
`taskkill /pid <pid> /T /F`,POSIX 进程组 SIGTERM)——覆盖「runner 还在跑」形态;
② runner PID 已死(或 cmdline 不匹配)但其 `children[]` 记录的宿主 CLI 子进程 PID 仍存活
且 cmdline 是宿主 CLI(`opencode`/`claude`)→ 逐个连树杀——覆盖「runner 与编排器被连带
硬杀(如用户杀掉整个 opencode 进程)、子进程 LLM 调用仍在烧 token」形态。两形态处理后均
删除 liveness 文件。stdout JSON 报 `{"kill_stale": {"killed": [{"pid","tier","kind":
"runner"|"child"}], "removed": [pid-file], "none": bool}}`;无任何 stale → `killed:[]`
退出码 0(幂等,可安全重复调用)。破坏性守卫(R5.3b):真实杀进程 SHALL 先经
`--dry-run`(列出将杀 PID,不杀);缺 `--dry-run` 且检出将杀目标 → 退出码 2 + recipe。
`--kill-stale` SHALL 对全部 tier 同构适用(含未来新增 tier——机制只依赖 liveness 文件名
约定,不含 tier 分支)。

#### Scenario: 孤儿 runner 被检出并杀死

- **WHEN** 上次运行被宿主硬杀,runner 进程仍在跑,liveness 文件残留且 PID 活跃
- **THEN** `--kill-stale --dry-run` 列出该 PID(kind=runner);去掉 `--dry-run` 后进程树
  终止、liveness 文件删除、stdout `killed` 非空、退出码 0

#### Scenario: runner 已死但记录的子进程仍存活(宿主连带被杀形态)

- **WHEN** 用户杀掉整个 opencode 进程(runner 是其 Bash 子进程,连带死亡),但 runner 记录
  在 `children[]` 里的宿主 CLI 子进程(opencode run 单元)仍存活烧 token,liveness 文件残留
- **THEN** `--kill-stale` 检出 runner PID 已死、`children[]` 中 PID 存活且 cmdline 为宿主
  CLI,逐个连树杀(kind=child);被杀单元无 `.done`/`.failed` marker → 留 pending,本轮
  resume 重派(重派前先经本命令清理,无双跑)

#### Scenario: 无孤儿时幂等空转

- **WHEN** 无残留 liveness 文件(或文件残留但记录的所有 PID 均已死/被复用为非 fanout 进程)
- **THEN** `--kill-stale` 退出码 0、`killed:[]`,残留文件被清理,不杀任何无辜进程

#### Scenario: PID 复用误杀防护

- **WHEN** liveness 文件残留但其中某 PID 已被操作系统复用为一个非 fanout/宿主 CLI 进程
- **THEN** `--kill-stale` 不杀该进程,仅删除残留 liveness 文件(runner 按 cmdline 含
  `fanout_runner.py`、子进程按 cmdline 为宿主 CLI 双条件才杀)

### Requirement: 派发循环 stderr 心跳(宿主 TUI 实时可见)

`fanout_runner.py` 派发循环 SHALL 在每个关键节点向 **stderr**(诊断流,R5.3b 分流不变)打
单行心跳:`[fanout_runner <tier>] wave=<k> unit=<id> <event> done=<d>/<total>`(event ∈
spawn|ok|failed|timeout|crash|wave-end;至少覆盖:每单元 spawn、每单元终结状态、每波结束)。
心跳 SHALL 携带自首次 spawn 起的相对耗时(`+HH:MM:SS`)。stdout 契约 SHALL 零变化(stdout
仍只含末尾一行 JSON 摘要)。宿主 TUI(opencode)对 running 态 Bash 工具实时渲染
stdout+stderr 合并流的滑动尾部(源码核实:`shell.ts` `handle.all = merge(stdout, stderr)` →
`metadata.output` → TUI 刷新),故心跳行 = 实时进度可见;claude 侧 stderr 亦入 Bash 结果。

#### Scenario: opencode TUI 实时显示 fanout 进度

- **WHEN** runner 在 opencode 会话内经 Bash 工具长跑,单元陆续完成
- **THEN** TUI 该 Bash 工具的输出区持续刷新心跳行(wave/unit/done 计数随推进变化),
  用户无需第二终端即可区分「正常慢」与「卡死」

#### Scenario: stdout JSON 契约不变

- **WHEN** 审阅 runner stdout 全部输出
- **THEN** stdout 仍只在结束时输出一行结构化 JSON 摘要(shape 与既有字段不变);心跳只出现在
  stderr

### Requirement: sdr tier dispatches diff-review units through the shared wave machine

`fanout_runner.py` 的 `--tier` 闭集 SHALL 扩为 `scout|t1|t3|sdr`,新增 `sdr` 条目挂入既有 TIERS
单点映射表:枚举脚本 = `diff_group.py`(`--repo/--base/--branch/--checkpoints/--materialize` 转发)、
任务模板 = `core/prompts/fragments/fanout/sdr-task.md`、fanout agent = `sdr-review-fanout`、
占位符集 = 路径字段(`input_path`/`draft_path`/`done_marker`/`failed_marker`)+ `unit_id`/
`kind`/`route`/`repo`/`codegraph`。波次循环、ack 状态机、三级超时不变式、liveness 登记、
`--kill-stale`、零推进熔断、进度 sidecar(`<init-dir>/fanout_progress.sdr.json`)SHALL 对 sdr
tier 零改动复用(tier 无关代码路径不变);`diff_group.py` 的 gate 形退出码 2(如 base ref 不存在)
SHALL 与 t1 scout-incomplete-gate 同形透传(fail-loud + stderr recipe,NEVER 进入重派循环)。
`install.sh` 自检清单与 fanout agent 自检 SHALL 覆盖 `diff_group` 脚本、`sdr-task.md` 模板与
`sdr-review-fanout` agent 克隆;`tools/check_contracts.py` 覆盖引用 `diff_group.py` /
`render_sdr_report.py` / `sdr_context.py` 的壳调用 flag。既有 scout/t1/t3 三 tier 的调用面、模板、
agent、行为 SHALL 逐字不变。

#### Scenario: sdr tier 经共享状态机波次消化

- **WHEN** `diff_group.py --materialize` 产出 12 个 pending 单元,编排器一次调用
  `fanout_runner.py --tier sdr --repo <abs> --base master --branch X --checkpoints <dir> --inputs-dir <dir>`
- **THEN** dispatcher 以 `--wave` 并发度内部消化全部波次,每单元 spawn 一个 `sdr-review-fanout`
  subagent(任务消息 = `sdr-task.md` 模板逐字填充),stdout 摘要含 `tier:"sdr"`;软时限早退 /
  resume / 熔断行为与既有 tier 一致

#### Scenario: sdr 单元越树路径 spawn 前拦截

- **WHEN** 某 pending 项的 `draft_path` 解析后落在 `repo` 锚树外
- **THEN** dispatcher 不 spawn,直接写 `.failed` marker(reason=path-drift),后续波次不受影响
  (与既有 tier 同一 `_anchor_check` 代码路径)

#### Scenario: 既有 tier 行为零漂移

- **WHEN** 对 scout/t1/t3 各自的枚举产物运行既有调用面并比对本次变更前后的 stdout 摘要与模板
  填充结果
- **THEN** 三 tier 的枚举脚本、模板、agent、占位符集、波次行为逐字一致(TIERS 表增行不触既有行)

### Requirement: t2 tier dispatches T2 partial-synthesis through the shared wave machine

`fanout_runner.py` 的 `--tier` 闭集 SHALL 扩为 `scout|t1|t2|t3|sdr`,新增 `t2` 条目挂入既有 TIERS
单点映射表:枚举脚本 = `plan_aggregate.py`(`--node t2` + `--init-dir`/`--budget`/`--materialize`
转发)、任务模板 = `core/prompts/fragments/fanout/t2-task.md`、fanout agent = `init-synthesis-fanout`、
占位符/路径字段集 = `input_path`/`checkpoint_path`/`done_marker`/`failed_marker` +
`shard_id`/`categories`/`repo`(与 t3 同形:无 `slice_dir`/`chunk_sources`/`codegraph`,partial-synthesis
只读结构化 shard 记录、写摘要 checkpoint、不切大文件)。波次循环、ack 状态机、三级超时不变式、liveness
登记、`--kill-stale`、零推进熔断、进度 sidecar(`<init-dir>/fanout_progress.t2.json`)SHALL 对 t2 tier
零改动复用(tier 无关代码路径不变;TIERS 表增行不触既有 scout/t1/t3/sdr 行)。

**枚举字段前置**:`plan_aggregate.py --node t2 --materialize` 的 stdout SHALL 成为 dispatcher 可消费的
合法枚举——顶层补 `repo`(=`--init-dir` resolve 的父目录,`.mgh-init` 恒在 `<target>/.mgh-init` 下)、
marker 派生 `total`/`done`/`failed`,每 `pending[]` shard 项补 `failed_marker`(与 `done_marker` 同目录
`.<shard_id>.json.failed`),且 `pending[]` 排除已有 `.done`/`.failed` marker 的 shard(dispatcher 波次重列 →
pending 收缩;`summary_paths`/`shards` 仍为全集)。dispatcher 据此锚树校验(`_anchor_check`)与 `.failed`
终态写入;任一 shard 路径解析落在 `repo` 锚树外 → spawn 前记 `failed`(reason=path-drift),不进入重派循环。
`needs_reduce=false`(pending 空)时 dispatcher SHALL 幂等空转(0 单元、`partial:false`,不误报 `stalled`),
该路径由编排器在调用 dispatcher 前判定并改走 single-context `init-synthesis`(行为不变)。

`install.sh` 自检清单与 fanout agent 自检 SHALL 覆盖 `plan_aggregate.py` 脚本、`t2-task.md` 模板与
`init-synthesis-fanout` agent 克隆;`tools/check_contracts.py` 覆盖 `--tier t2` 与 `plan_aggregate.py`
新增 flag。既有 scout/t1/t3/sdr 四 tier 的调用面、模板、agent、行为 SHALL 逐字不变。

#### Scenario: t2 tier 经共享状态机波次消化 map 阶段

- **WHEN** 大仓 T1 记录 > `--max-aggregate-bytes`,`plan_aggregate.py --node t2 --materialize` 产出 K 个
  category shard,编排器一次调用 `fanout_runner.py --tier t2 --init-dir <init-dir> --budget 262144
  --checkpoints <t2-dir> --inputs-dir <inputs/t2>`
- **THEN** dispatcher 以 `--wave` 并发度内部消化全部波次,每 shard 一个 `init-synthesis-fanout`
  subagent(任务消息 = `t2-task.md` 模板逐字填充),stdout 摘要含 `tier:"t2"`;软时限早退 / resume / 熔断
  行为与既有 tier 一致

#### Scenario: plan_aggregate t2 stdout 携带 repo 与 failed_marker

- **WHEN** `plan_aggregate.py --node t2 --init-dir <target>/.mgh-init --materialize <inputs/t2>` 产出一页
  shard pending
- **THEN** stdout JSON 顶层含 `repo`(=`<target>` resolve 绝对值),每 shard 项含 `failed_marker`(绝对,
  `.<shard_id>.json.failed`);dispatcher 据此锚定锚树校验与 `.failed` 终态写入

#### Scenario: t2 shard 越树路径 spawn 前拦截

- **WHEN** 某 shard 项的 `checkpoint_path`(或 `failed_marker`)解析后落在 `repo` 锚树外
- **THEN** dispatcher 不 spawn 该 shard,直接写 `.failed` marker(reason=path-drift),后续波次不受影响
  (与既有 tier 同一 `_anchor_check` 代码路径)

#### Scenario: needs_reduce=false 时 dispatcher 幂等空转

- **WHEN** 编排器误以 `--tier t2` 调用 dispatcher,但 `plan_aggregate.py --node t2` 判定
  `needs_reduce=false`(pending 空)
- **THEN** dispatcher 以 0 单元、`partial:false` 干净完成(不误报 `stalled:true`);编排器走 single-context
  `init-synthesis` 路径行为不变

#### Scenario: 既有 tier 行为零漂移

- **WHEN** 对 scout/t1/t3/sdr 各自的枚举产物运行既有调用面并比对本次变更前后的 stdout 摘要与模板填充结果
- **THEN** 四 tier 的枚举脚本、模板、agent、占位符集、波次行为逐字一致(TIERS 表增行不触既有行)

### Requirement: 在飞单元失活检测与外科手术式树杀(运行留痕)

dispatcher SHALL 对每个在飞子进程跟踪其 stdout/stderr 的**字节级最后输出时刻**:静默时长
≥ `--stall-timeout-s`(默认 900;`< 60` 拒识退出码 2)→ 判定该单元失活,**仅杀该单元的整个
进程树**(Windows `taskkill /pid <pid> /T /F`——`.cmd` shim 链下的真实 host-CLI 进程 SHALL
一并终止,NEVER 留孤儿继续烧 token;POSIX 进程组 SIGTERM),无 ack 无 marker → 单元留
pending 重派。`--call-timeout-s` 绝对兜底超时的杀路径 SHALL 使用同一树杀机制(取代仅杀直接
子进程的 `proc.kill()`——Windows 上那是 shim 层,真进程必成孤儿)。失活判定 SHALL 对全部
tier 一致;误杀边界由余量承担(healthy 单元分钟级,默认阈值 ~5×),被误杀单元重派自愈且
run.log 留痕可查。

**每单元运行留痕**:dispatcher SHALL 将每单元子进程的 stdout/stderr 尾部(各自截断上限)落盘
`<checkpoints>/<tier>/<单元 id 文件名安全形>.run.log`(文件名净化规则与 audit 副本同源,
`/ \ :` → `_`);ok 终态亦写(体积小),timeout/stall/crash/failed 终态 MUST 写;失活/超时的
stderr 诊断行 SHALL 附 run.log 绝对路径——事后定位以证据为准,NEVER 依赖事后猜测。

**stdout/心跳披露**:stdout 摘要 SHALL 新增 `stall_killed:[<unit>…]`(本次 run 失活树杀的
单元,既有字段不变);派发循环 SHALL 以默认 60s 周期向 stderr 打在飞披露行(在飞单元 id +
距其子进程上次输出的秒数),人从宿主 TUI 实时区分「正常慢」与「卡死」。

#### Scenario: 失活单元被外科树杀,其余单元不受影响

- **WHEN** 某在飞子进程静默超过 `--stall-timeout-s`,同批其余单元正常推进
- **THEN** 仅该单元进程树被终止(含 shim 链真进程),其余单元与后续补位照常;该单元无
  marker 留 pending;stdout 摘要 `stall_killed` 含其 id

#### Scenario: 树杀不留孤儿 shim 链

- **WHEN** 失活(或 call-timeout)树杀一个经 `.cmd` shim spawn 的 opencode 子进程
- **THEN** shim 层与真实 host-CLI 进程一并终止(`taskkill /T /F` 整树),无任何后代进程
  存活烧 token;`--kill-stale` 事后检查无该 run 的存活子进程

#### Scenario: 非 ok 终态运行留痕可诊断

- **WHEN** 某单元以 timeout/stall/crash 终态结束
- **THEN** `<checkpoints>/<tier>/<unit>.run.log` 存在且含该子进程输出尾部;stderr 诊断行
  附该文件绝对路径;事后可从日志尾部读出子进程最后行为(如权限拒绝、流停摆前的输出)

#### Scenario: 周期在飞心跳披露静默时长

- **WHEN** 某在飞单元子进程已静默 5 分钟,其余单元在跑
- **THEN** stderr 每分钟出现该单元的在飞披露行(unit id + 距上次输出秒数),静默秒数单调
  增长直至失活判定;stdout 单行 JSON 契约不变

### Requirement: headless fanout agent 无问询钉扎

opencode fanout agent 克隆(`init-scout-fanout`/`init-induct-fanout`/`init-synthesis-fanout`/
`init-rulewriter-fanout`/`sdr-review-fanout`)的 frontmatter `permission:` SHALL 显式钉扎
opencode 默认权限表中全部 **ask 类**为确定性终局:`external_directory: deny`、
`doom_loop: deny`(既有 `read/glob/grep/list/bash/edit` 钉扎不变)。headless 派发的子会话
SHALL NEVER 进入权限问询等待——问询面在无应答者的 `run` 模式下 = 永久挂(2026-02 前版本),
或有应答者时 = 静默 auto-reject(行为不可控);显式 deny = 工具报错、agent 按纪律适配,与
opencode 版本无关。树内读面不受影响(`read: allow` 钉扎保持,含 `.env` 类分析证据)。
claude 侧 spawn 面不变(`-p` headless + `--allowedTools` 白名单外自动拒绝,无问询挂死面)。

#### Scenario: fanout agent 定义 ask 类全部显式化

- **WHEN** 审阅任一 opencode fanout agent 克隆的 frontmatter `permission:` 块
- **THEN** `external_directory` 与 `doom_loop` 均为显式 `deny`,与既有 `read/glob/grep/
  list/bash/edit` 钉扎并存;无任何权限项依赖 opencode 默认 ask 行为

#### Scenario: 越目录读在 headless 下确定性拒绝

- **WHEN** fanout 子代理尝试读项目目录之外的路径(旧版 opencode 下该触发曾表现为权限问询挂死)
- **THEN** 该工具调用被显式 deny 规则立即拒绝(工具报错),agent 按任务模板纪律留在
  `{{repo}}` 树内继续;子进程不挂死、不等待任何应答者
