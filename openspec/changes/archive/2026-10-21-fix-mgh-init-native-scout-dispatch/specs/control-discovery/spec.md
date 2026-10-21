## MODIFIED Requirements

### Requirement: Fan out scout across parallel isolated byte-bounded batches

scout 深读 SHALL 按**隔离 fan-out**执行(对标 D12 T1→T2 同构):确定性脚本
`plan_scout.py` 对 `skeleton.json` 做噪声剪枝(复用 `EXCLUDE_DIR`)+ 去除 regex 已命中
文件后,把剩余 scout 目标按**字节预算**切批——每批累计 `bytes ≤ --scout-batch-bytes`
(默认 96KB),且分批前先按 `pkg` 排序以**包内聚**(同目录相关文件落同批),每批文件数
MUST NOT 超过 `--scout-batch-cap`(默认 40)。单个 `bytes > --scout-batch-bytes` 的文件
MUST 经既有 `chunk_sources.py` 切片入批,MUST NOT 整文件塞入单个 LLM 上下文。每批在一个
**独立 scout-reader subagent 上下文**深读,产出 `checkpoints/scout/<batch_id>.json`;全部
批次完成后由**单一 scout-merge subagent** 在**仅结构化记录、无原始码**上做去重、归一、
provisional `source` 标记 → `scout_candidates.json`。批数(= subagent 数)
SHALL 由 `ceil(Σtarget_bytes / batch_bytes)` **涌现而出**,而非固定常量。每批 SHALL 落
`checkpoints/scout/<batch_id>.json.done`;`--resume` MUST 跳过已 done 批次。

**派发形态由环境画像解析器选择**:`mgh-init` SHALL 经
`env_profile.resolve(<target>, consumer="init")` 解析(与 sdr 同一解析器、不同消费者)。
`consumer=init ∧ host=opencode` SHALL 缺省解析 `native`——**没有画像文件或 `auto` 也
原生**(用户已拍板 mgh-init 全流程转向 opencode 缺省原生);显式
`dispatch_mode:"runner"` SHALL 回退子进程;`consumer=generic`、claude/dsh/other 面 SHALL
仍解析 `runner`。显式 `dispatch_mode` SHALL 覆盖缺省;坏画像 SHALL fail-closed(退出码 2 +
recipe)。仅当解析形态为 `native` 且 `host_face=="opencode"` 时走原生形态:确定性计划物化 +
编排器同一条 assistant 消息并发派原生子代理(agent `init-scout-native`,
`mode: subagent`),波次尺寸来自计划的 `wave_size`(环境画像并发与配额算术的较小者),不适用
`max_concurrent` 默认 8。显式 runner、`consumer=generic`、claude/dsh/other 面走子进程形态
(下列 `max_concurrent`/`fanout_runner.py` 行为逐字节不变,是永久回退路径)。解析为 native
时还 SHALL 检查 scout 原生资产(`agent/init-scout-native.md` 与
`prompts/fragments/init-scout-native-dispatch.md`),缺一退出码 2 + 重装/显式 runner recipe,
NEVER 静默回退。两种形态共用同一批规划、同一 checkpoint/marker 路径、同一 merge/fold-in;
原生形态的波次纪律与无人值守闭环见「Native scout dispatch wave discipline and unattended
loop」。claude/dsh 面保留子进程形态并在壳与规格中显式披露(宿主机制差异,不做静默镜像
断裂)。

**计划自描述与 `--check` 退出码**:`plan_scout.py` 生成时 SHALL 把生成所用
`batch_bytes`/`batch_cap` 记入 `scout_plan.json` 顶层(自描述);`--check` 校验批预算 SHALL
优先使用 plan 记录值(plan 未记录时回退 CLI `--batch-bytes`,兼容存量 plan)。`--check` 对
损坏 plan(JSON 不可解析 / wrapper 形状错)SHALL 退出码 **2**(fail-loud 边界校验统一语义,
闸门 recipe 只认 2),NEVER 退出码 1。理由〔自定义批字数生成的合法 plan 在缺省 `--check`
下按默认值误报违例 → 回退循环;损坏 plan 报 1 会被编排器当作可重试通用错而非闸门违例〕。

编排器取得「待跑批清单」MUST 经确定性叶脚本 `list_scout_batches.py`(见「Deterministic
scout-batch enumeration for fan-out」),MUST NOT 手挖 `scout_plan.json`、MUST NOT `py -c`
内省。原生形态的物化脚本 SHALL 复用同一枚举器(不另造 pending 来源)。`merge_scout.py`
折叠后,`scout_candidates.json` 与改写后的 `controls_candidates.json` 为**终态**,编排器
MUST NOT 对其二次聚合或重切批。

#### Scenario: Batches sized by bytes, co-located by package

- **WHEN** scout 目标含同一 `com/acme/security/` 包下的多个相关文件
- **THEN** `scout_plan.json` 的某批同时包含这些文件,且该批累计 bytes ≤ `--scout-batch-bytes`

#### Scenario: Oversize single file is sliced, not fed whole

- **WHEN** scout 目标含一个 250KB 的 `LegacyGuard.java`,而 `--scout-batch-bytes` 为 96KB
- **THEN** 该文件经 `chunk_sources.py` 切成函数切片入批,而非整文件塞入一个 scout-reader

#### Scenario: 自定义批字数的 plan 在缺省 --check 下零违例

- **WHEN** 以 `--batch-bytes 204800` 生成 plan(顶层记录该值),随后不传 `--batch-bytes`
  运行 `plan_scout.py --check <plan>`
- **THEN** 校验按 plan 记录的 204800 判预算,合法 plan 退出码 0;存量无记录 plan 回退
  CLI 值,行为不变

#### Scenario: 损坏 plan 的 --check 退出码 2

- **WHEN** `scout_plan.json` 内容不是合法 JSON(或顶层不是 wrapper dict)
- **THEN** `plan_scout.py --check` 退出码 **2** + stderr 诊断(NEVER 退出码 1)

#### Scenario: Batch count emerges from data, parallel waves bounded

- **WHEN** scout 目标共 ~9.6MB、`--scout-batch-bytes` 96KB,子进程形态
- **THEN** `scout_plan.json` 产出约 100 批,编排器以每波 `max_concurrent`(默认 8)并行跑完
  所有批

#### Scenario: Native form keeps the same batch semantics

- **WHEN** opencode 面、`consumer=init`(无画像缺省 native 或显式 `dispatch_mode:"native"`),
  scout 目标含 3 个批
- **THEN** 原生形态仍以同一 3 个 `batch_id`、同一 checkpoint/marker 路径、同一
  `chunk_sources.py` 切片语义产出;只是派发方式换为计划物化 + 原生子代理,发现本体与
  merge/fold-in 不变

#### Scenario: opencode init 无画像即原生

- **WHEN** opencode 安装面、项目无 `.mgh/env-profile.json`(或 `dispatch_mode:"auto"`),
  `list_steps.py --step scout` / `resume_state.py` 以 `consumer=init` 解析
- **THEN** 解析形态为 `native`(`source=host-default`),scout 步给出 `emit_native_plan.py`
  物化入口与原生 `next_action`;不要求用户手写画像,也不因缺画像回退子进程

#### Scenario: 其它消费者与安装面仍 runner

- **WHEN** 无画像或画像为 `auto`,消费者为 `generic` 或当前为 claude/dsh/other 安装面
- **THEN** 解析形态仍为 `runner`,scout 步保持既有子进程调用行、无 `dispatch`/`native_arc`
  ——opencode init 的缺省原生不扩散到其它消费者或安装面

#### Scenario: 显式 runner 在 opencode init 回退

- **WHEN** opencode 安装面、画像写着 `{"dispatch_mode":"runner"}`,`consumer=init`
- **THEN** 解析形态为 `runner`,scout 步回到子进程调用行、无 `dispatch`/`native_arc`——
  原生缺省可被显式关闭,回退路径保持可用

#### Scenario: Merge operates on structured records only

- **WHEN** scout-merge 运行(任一形态)
- **THEN** 其输入为各 batch 的结构化候选 JSON(无原始源码),上下文规模远小于任一
  scout-reader;跨批重复报告的同一控制被去重归一

#### Scenario: Resume skips completed batches

- **WHEN** scout fan-out 中途断开,随后 `mgh-init --resume`
- **THEN** 已 done 的批次被跳过,仅继续 pending 批次,`scout_candidates.json` 最终完整;
  原生形态同样按磁盘标记重派生,不依赖对话记忆

#### Scenario: Pending work-list obtained via leaf script, not hand-mining

- **WHEN** 编排器进入 scout fan-out
- **THEN** 它先经确定性枚举器取 `pending[]`(子进程形态 = `list_scout_batches.py`;
  原生形态 = `emit_native_plan.py` 复用的同一枚举器),不出现 `py -c` 挖
  `scout_plan.json` 或 `Write _prep_scout_batches.py`

#### Scenario: Merged artifacts are terminal

- **WHEN** `merge_scout.py` 完成,`scout_candidates.json` 落盘
- **THEN** 编排器不再对其二次聚合或重切批(不出现 `_aggregate_scout.py` 之类重实现)

## ADDED Requirements

### Requirement: Native scout dispatch wave discipline and unattended loop

当解析形态为原生(`consumer=init ∧ host=opencode`,缺省或显式 `dispatch_mode:"native"`)
时,`/mgh-init` 的 scout 层 SHALL 按以下闭环执行;显式 runner、`consumer=generic`、
claude/dsh/other 面 SHALL 保持既有子进程形态逐字节不变(永久回退路径)。

- **形态选择**:`mgh-init` SHALL 经 `env_profile.resolve(<target>, consumer="init")`
  解析(与 sdr 同一解析器、不同消费者),坏文件按 `env_profile` 的 fail-closed 契约
  (退出码 2 + recipe,NEVER 静默回退缺省)。仅当解析形态为 `native` 且
  `host_face=="opencode"` 时走原生;解析为 native 时 SHALL 在进入 fan-out 前检查 scout
  原生资产(`agent/init-scout-native.md` 与
  `prompts/fragments/init-scout-native-dispatch.md`),缺一退出码 2 + 重装/显式 runner
  recipe,NEVER 静默回退子进程。解析形态为 native 但 `host_face != "opencode"`(如
  claude 面显式 `native`)时,SHALL 退出码 2 + recipe(原生仅 opencode;改用 runner 或
  opencode 面),NEVER 静默按子进程运行。
- **物化与自检**:每轮以 `emit_native_plan.py --tier scout --scout-plan
  <init-dir>/scout_plan.json --checkpoints <init-dir>/checkpoints/scout --inputs-dir
  <init-dir>/inputs/scout --profile <target>` 物化计划(任务文件 + 波次表 + 短单元号),物化
  后以同参跑 `--check`;`--check` 退出码 2 → 按 stderr recipe 重物化,NEVER 消费过期计划。
- **页语义**:一次物化只覆盖枚举器当前 pending 页(`--orch-budget-bytes` 会收紧页);
  编排器 SHALL 在派完当前页后**重物化**取下一页,循环直到计划 `units_total == 0`;
  NEVER 假设一次计划覆盖全部批,NEVER 自行记账「哪些派过了」。
- **波次派发**:编排器**同一条 assistant 消息**并发发出当前波全部 N 个子代理调用(agent
  `init-scout-native`,`mode: subagent`)——每调用 `description` = 该批计划短号;任务体 =
  单行令牌 `mgh-dispatch: plan=<plan_path> unit=<短号>`(计划引用自物化 stdout 逐字复制,
  短号自计划逐字复制;派发插件的令牌展开钩子在子代理启动前换成任务文件全文)。令牌展开
  钩子缺席的旧版安装 SHALL 回退为「固定一句 + 该批任务文件绝对路径逐字透传」。编排器
  NEVER 跨波合并、NEVER 自增并发、NEVER 自撰任务文本、NEVER 拼接或改写路径。
- **零批计划**:`units_total == 0` 时 SHALL 跳过派发,直接进入既有 scout-merge/audit/
  fold-in 段——不产生空波次,不把空计划当错误。
- **标记真相源**:`.done`/`.failed` 的唯一写者是子代理自身(成功 touch `.done`;失败自写
  `.failed`,内容 `{unit_id, reason}`——该指令仅存在于原生 agent 定义;共享任务模板的
  「reference only; the dispatcher writes it」行保持不动)。计划物化、看门狗、编排器 SHALL
  NEVER 写任何批标记(编排器唯一标记动作 = 重派认领时删除旧 `.failed`)。
- **失败批**:`.failed` 为终态;至多重派一轮(重派轮 = 删除旧 `.failed` + 重物化带
  `--retry-failed` + 派发一次);重派再败 SHALL 接受缺口,在 scout-merge 之前披露,后续
  轮次不再派它;NEVER 无限重派。
- **限流等窗**:上一波 `.failed` 原因含限流特征(429 / rate limit / quota)时,SHALL 按画像
  配额窗口(`quota.window_s`,未配置按网关公开口径)等满一个窗口后再重物化/重派,等待事实
  入 run 留痕;NEVER 在限流窗口内连续重派烧配额。
- **无人值守**:第一波派发前 SHALL 以后台形态启动看门狗——根会话取宿主注入的会话环境变量、
  `--run-dir <init-dir>`、阈值用缺省;run 落定后看门狗自退;编排器 NEVER 代替看门狗做会话
  中止。
- **步骤/恢复形态感知**:原生形态下 `list_steps.py --step scout` SHALL 给出物化入口
  (`emit_native_plan.py`)与 `native_arc`(materialize → waves),`resume_state.py` SHALL 给出
  顶层 `dispatch` 与指向「重物化 → 派当前波」的 `next_action`。`dispatch` SHALL 与 sdr 同形:
  `{form, source, profile_exists, host_face, consumer, profile_path, plan_present,
  native_agent, discipline_fragment}`,其中 scout 的 `consumer` 为 `"init"`、
  `source` 区分 `profile`/`host-default`(无画像的 opencode init 是 `host-default`);
  显式 runner/claude/other 时两脚本 stdout 逐字节不变(不出现新字段),坏画像退出码 2 +
  recipe。进度仍纯磁盘重派生。
- **报告与披露**:`init_manifest.json` 的 `scout` 段在原生形态下 SHALL 增
  `dispatch: {form:"native", source, profile_exists, host_face, consumer, plan_path,
  plan_present, native_agent}`(值取自 `list_steps.py`/`resume_state.py` stdout,不靠模型
  记忆);`report.md` 与 `boundaries[]` SHALL 披露实际派发形态与计划工件在场证据。诚实边界
  SHALL 披露:止损为波次粒度(无进程树杀,挂死由看门狗中止兜底)、编排父会话是单点、任务
  文件路径转述的残余错抄面(令牌展开落地后只剩短号错抄;防线 = 越树守卫 + 重枚举回待派 +
  至多一轮重派)、一次物化只覆盖当前页。
- **三面分歧披露**:本原生形态当前仅 opencode 面;claude/dsh 面保留子进程形态,壳与规格
  SHALL 显式披露该分歧(属宿主机制差异),后续按宿主能力另行接入。

#### Scenario: 显式 runner 与 claude/dsh 零变化

- **WHEN** opencode 面画像显式 `dispatch_mode:"runner"`,或命令从 claude/dsh/other 安装面
  运行,或 `consumer=generic`
- **THEN** scout 步走现行子进程形态,stdout/产物/步骤清单与该形态改动前一致——缺省原生的
  变更只作用于 `consumer=init ∧ host=opencode`;显式 runner 与其它面仍是可审计的回退路径

#### Scenario: 同消息并发派一波

- **WHEN** 原生形态当前波有 3 个待派批
- **THEN** 编排器在一条 assistant 消息内发出 3 个子代理调用(`description`=短号,任务体=
  令牌行或回退的固定句+任务文件绝对路径),全部返回后重物化进入下一页——不存在逐个串行
  派发或自撰任务文本

#### Scenario: 页循环覆盖全部批

- **WHEN** `scout_plan.json` 有 400 批,但一次物化因 `--orch-budget-bytes` 只装下 81 批
- **THEN** 编排器派完这 81 批后重物化,继续下一 81 批,直到 `units_total == 0`;
  不把「81 批」误当全部,也不手工翻 `scout_plan.json`

#### Scenario: 失败批至多一轮重派

- **WHEN** 某批 `.failed` 在场(原因非限流特征)
- **THEN** 重物化带 `--retry-failed` 将其重新列入至多一轮;重派再失败后该批进入缺口
  披露,后续波次不再派它——失败批不会无限循环

#### Scenario: 挂死单元由看门狗收口回待派

- **WHEN** 原生形态下某子会话挂死(无标记产出),看门狗超阈值将其中止
- **THEN** 该批因无标记在下次重物化回到待派;全程无任何一方代写标记——中止 ≠ 失败终态,
  终态只能由单元自身执行纪律写出

#### Scenario: 权限闸门在派发前关闭

- **WHEN** 原生形态下某个 scout 子代理尝试访问项目外目录
- **THEN** 运行域的 `permission.evaluate` 闸门在授权请求产生前把它改写成拒绝并附替代做法,
  `pending` 授权请求数为 0;子代理收到明确失败后继续本回合,不会挂到隔夜

#### Scenario: scout 原生资产缺席 fail-closed

- **WHEN** opencode 面、解析形态 native(无画像缺省或显式),但安装树缺
  `init-scout-native` agent 或 `init-scout-native-dispatch` fragment
- **THEN** `list_steps`/`resume_state`/壳在进入 fan-out 前退出码 2,stderr 给出重跑
  `install.sh --opencode` 或显式 `{"dispatch_mode":"runner"}` 的 recipe;NEVER 静默回退
  子进程

#### Scenario: 宿主不支持显式 native 时 fail-closed

- **WHEN** 项目画像写着 `{"dispatch_mode":"native"}`,`consumer=init`,命令从 claude/dsh/
  other 安装面运行
- **THEN** init 编排面在进入 fan-out 前退出码 2,stderr 给出「原生仅 opencode;改
  `dispatch_mode:"runner"` 或换 opencode 面」的 recipe;NEVER 静默按子进程运行

#### Scenario: 步骤与恢复暴露原生形态

- **WHEN** opencode 面、`consumer=init`(无画像缺省 native 或显式 native)时分别运行
  `list_steps.py --step scout` 与 `resume_state.py`
- **THEN** 前者给出 `emit_native_plan.py` 物化入口与 `native_arc`,后者给出 `dispatch`
  (`form/source/profile_exists/host_face/consumer=init/plan_present/native_agent/...`;
  无画像时 `source=host-default`)与指向「重物化 → 派当前波」的 `next_action`;显式
  runner 或 claude/dsh 面时两脚本 stdout 逐字节回到既有形状,坏画像退出码 2 + recipe

#### Scenario: 报告与清单披露派发形态

- **WHEN** 原生形态 scout 收尾写 `init_manifest.json` / `report.md`
- **THEN** manifest 的 `scout.dispatch` 含 form/source/profile_exists/host_face/
  consumer=init/plan_path/plan_present/native_agent,report 与 boundaries 披露「本次 scout
  怎么派的」与计划工件在场证据;诚实边界含波次粒度止损、父会话单点、路径转述残余、一次
  物化只覆盖当前页四条

#### Scenario: 三面分歧可见

- **WHEN** 比对三面 `mgh-init` 壳的 scout 步
- **THEN** opencode 面含原生条件步,claude/dsh 面为子进程形态,且各面如实披露当前分歧
  ——不是静默的镜像断裂
