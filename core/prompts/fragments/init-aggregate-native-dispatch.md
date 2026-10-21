<!--
  mgh-init aggregate-layer native-dispatch discipline (opencode face). Loaded
  ON DEMAND by the mgh-init command shell / the t1/t2/t3 stage flows and the
  scout step's merge segment when the resolved dispatch form is native — the
  opencode install face default for consumer=init (no env-profile needed), or
  an explicit `dispatch_mode: "native"`. An explicit
  `dispatch_mode: "runner"` selects the subprocess fallback instead; the
  claude/dsh faces stay subprocess-only. Install mirrors to
  <mgh-core>/prompts/fragments/init-aggregate-native-dispatch.md.
  This is an ORCHESTRATOR discipline fragment, not a task template: the
  per-unit task message lives in prompts/fragments/fanout/{t1,t2,t3,
  scout-merge}-task.md (shared with the subprocess form, zero-changed); the
  per-unit agent behavior lives in the init-*-native agent definitions.
  Not loaded into any context automatically.
-->

# 聚合层原生派发纪律(/mgh-init,opencode 面 `consumer=init` 缺省形态)

适用前提:`env_profile.py --consumer init` 解析出 `form=native`(与 scout 读者层
同一解析、同一缺省)。**本 fragment 只覆盖四个聚合层的 map 派发段**:t1(按簇/
按包归纳)、t2(综合 map 分片)、scout-merge(分片合并 map 段)、t3(按类别出
规则)。各层的**单上下文段**(t2 `needs_reduce=false` 的 init-synthesis、
scout-merge `needs_reduce=false` 的 init-scout-merge)、**rollup 段**
(init-synthesis-rollup / init-scout-merge-rollup)、audit / fold-in / assemble
按既有段执行,不原生化。画像显式 `dispatch_mode:"runner"` 或 claude/dsh 面 →
各步既有子进程段(fanout_runner)逐字适用,零变化。

## 0. 看门狗先行(第一波派发前完成,不可跳过)

与 scout 读者层同一看门狗、同一参数(首次拉起后整条流水线共用;已在运行则
每层波次边界只确认存活):

- Windows 宿主(shell 工具是 PowerShell;NEVER 用 `cmd... &` 形态):

      $p = Start-Process -FilePath <解释器> -ArgumentList @('<mgh-core>/scripts/native_watchdog.py','--run-dir','<init-dir>') -RedirectStandardOutput '<init-dir>/watchdog-boot.log' -RedirectStandardError '<init-dir>/watchdog-boot.err' -WindowStyle Hidden -PassThru; $p.Id

- POSIX 宿主:`py <mgh-core>/scripts/native_watchdog.py --run-dir <init-dir> > <init-dir>/watchdog-boot.log 2>&1 &`(记录 `$!`)。

- 阈值全部用缺省;`--deadline-s` 未传 = 只按落定自退。NEVER 前台跑看门狗、
  NEVER 代替看门狗做会话中止。路径全部用树内绝对路径。每层波次边界确认
  `<init-dir>/watchdog/state.json` 仍在近两周期内更新 = 活;缺席 → 同命令再拉起
  一次(幂等)。收尾完成后等其自退;确需立即收尾按记录的 pid 停止。

## 1. 每层固定循环(页语义,与 scout 读者层同构)

每层进入 map 派发段后,循环直到该层计划 `units_total == 0`:

1. **物化 + 自检**(确定性脚本,stdout 直消费;各层计划文件名 = 本层专属,
   互不覆写):

       py <mgh-core>/scripts/emit_native_plan.py --tier t1 --clusters <init-dir>/clusters.json --candidates <init-dir>/controls_candidates.json --checkpoints <init-dir>/checkpoints/t1 --inputs-dir <init-dir>/inputs/t1 --profile <target> [--pack-bytes 16384 --pack-max 8]
       py <mgh-core>/scripts/emit_native_plan.py --tier t2 --init-dir <init-dir> --budget <max-aggregate-bytes> --checkpoints <init-dir>/checkpoints/t2 --inputs-dir <init-dir>/inputs/t2 --profile <target>
       py <mgh-core>/scripts/emit_native_plan.py --tier scout-merge --init-dir <init-dir> --budget <max-aggregate-bytes> --checkpoints <init-dir>/checkpoints/scout --inputs-dir <init-dir>/inputs/scout-merge --profile <target>
       py <mgh-core>/scripts/emit_native_plan.py --tier t3 --inventory <init-dir>/controls_inventory.json --format <fmt> --rules-dir <rules-dir> --target <target> --checkpoints <init-dir>/checkpoints/t3 --inputs-dir <init-dir>/inputs/t3 --profile <target>

   物化后同参跑 `--check`。退出码 2 → 按 stderr recipe 处理(重物化即修复);
   任一单元完成后计划按设计变 stale——波次收尾用重物化修复,NEVER 把这个
   退出码 2 当故障、NEVER 消费过期计划。每轮重跑物化 = 重枚举(pending 由磁盘
   标记重派生)。**计划文件按 tier 命名、互不覆写**:t1 = `native_plan_t1.json`、
   t2 = `native_plan_t2.json`、t3 = `native_plan_t3.json`、scout-merge =
   `native_plan_scout-merge.json`(scout 读者层用既有 `native_plan.json`;
   路径以物化 stdout `plan_path` 逐字为准)。**页语义**:一次物化只覆盖枚举器
   当前 pending 页,stdout `units_total` 是本页单元数——派完当前页回①重物化
   取下一页,`units_total == 0` 才离开本层循环。**NEVER** 假设一次计划覆盖全部
   单元、NEVER 手工翻各层聚合 JSON。

2. **通道 B(默认):一次派发工具调用跑完本页全部波次**——工具 `mgh_dispatch`
   输入只带计划引用:`{"plan": "<物化 stdout plan_path 逐字>"}`(整份计划 =
   本页全部波次,波内并发 = 计划波次尺寸、波间顺序;可选 `wave` / `units`
   互斥窄化,常规整页调用不传)。工具在宿主进程内派完全部波次,编排器
   零 LLM 波次回合;返回摘要 = 计数 + 短号清单 + 会话 id(zero findings)。
   以摘要与磁盘标记对账:done/failed/no-marker 计数与 `checkpoints/<tier>/`
   标记一致。
   **NEVER** 在工具外自建波次循环替代它、NEVER 把单元任务路径写进工具输入
   (闭集只收计划引用/短号)。
3. **通道 A(回退,工具缺席时)**:`mgh_dispatch` 工具不在本机工具集(未安装/
   加载失败/调用即报未知工具)→ 按探查层同构的编排器波次纪律派发:对当前波
   全部单元在**同一条 assistant 消息**发出子代理调用(agent = 计划 `agent`
   字段逐字,如 `init-induct-native`;`description` = 该单元计划短号;任务体 =
   单行令牌 `mgh-dispatch: plan=<计划引用> unit=<短号>`,展开钩子缺席的旧版
   安装回退 = 固定句 + `task_file` 绝对路径逐字)。回退事实写入本 run 过程
   记录并在 manifest 披露;**NEVER** 因工具缺席静默换子进程形态(那是画像
   `runner` 才有的显式回退)。NEVER 跨波合并派发、NEVER 自增并发、NEVER
   逐个串行派发。
4. **波收尾重枚举**:工具摘要返回(或通道 A 当前波全部返回)后回到第 1 步。
   单元的成功/失败以磁盘标记为准(`.done`/`.failed`),回执行仅供人与日志读,
   NEVER 解析回执当进度。

## 2. 各层不变量(逐项保持,零改动)

- **t1**:pack 打包摊薄透传(`--pack-bytes`/`--pack-max` 经物化器转发枚举器;
  包 id `pack::<category>::<sha8>`、成员级 `.done` 是唯一真相源与恢复粒度,
  重派轮已完成成员被任务模板跳过);scout 完成闸门(`scout-incomplete-gate`)
  透传——枚举器退出码 2 = 先完成 scout 层,NEVER 以纯 regex 簇继续;波次收尾
  后的 T1→T2 形状闸门(`validate_t1_records --strip-bom + --check`)照常必跑。
- **t2**:聚合预算闸门先行(`plan_aggregate.py --node t2 --budget …` 判
  `needs_reduce`)——`needs_reduce=false` 时**零派发**:
  物化器不产计划、不建会话(stdout note 即此信号),单上下文
  `init-synthesis` 照既有段执行;
  `needs_reduce=true` 才进第 1 节循环(`--budget` 与闸门同值)。rollup 段消费
  **manifest 文件先行**:待合并者读 `rollup.summary_paths` 清单路径,NEVER
  直接展开全量路径数组进上下文。
- **scout-merge**:与 t2 同构的预算闸门(`--node scout-merge`);分片字节预算、
  候选粒度装箱、病态单候选瘦身投影留痕语义不变;**任一分片 `.failed` 或缺失
  → 不 rollup**,缺口在产物与报告披露,NEVER 带缺片合并(缺该分片摘要 =
  静默丢候选)。
- **t3**:done/failed 判定 = 正向 marker 路径计算(NEVER 从文件名反推);孤儿
  marker 清单告警照常;产物收口 = `assemble_rules.py --check`(原生形态产出
  的规则文件与子进程形态同一校验器把关)。`init-rulewriter-native` 是
  **唯一带写权限**的原生评审孪生,写面只开规则产物(越树写被运行域守卫拦)。

## 3. 失败单元:至多一轮重派,再败接受缺口

`.failed` 在场的单元(原因非限流特征)至多重派**一轮**:删除该单元旧
`.failed`(唯一编排器标记动作,删除不是写入,与派发器 `--retry-failed` 认领
即删同形)→ 重物化加 `--retry-failed`(该单元回 pending)→ 走第 1 节循环
派发一次。重派再失败 → **接受缺口**,后续轮次不再派它;t1/t3 缺口入
manifest `failures` 既有披露,t2/scout-merge 缺片按第 2 节不 rollup 并披露。
判定「这一轮是否已经重派过」靠本会话内执行留痕;恢复的新会话若无法判定,
允许再重派一轮(代价有界),仍 NEVER 无限重派循环。

**限流等窗**:上一波 `.failed` 原因含限流特征(429 / rate limit / quota)→
按环境画像配额(`quota.window_s`,未配置按网关公开口径,如 10 分钟)等满一个
窗口后再重物化/重派,把「何时等、等多久」写进本 run 过程记录;NEVER 在限流
窗口内连续重派烧配额。

## 4. 标记真相源(硬边界)

`.done`/`.failed` 的唯一写者是子代理自身(指令住在各 `init-*-native` agent
定义):成功 touch `.done`,失败自写 `.failed`(内容 `{unit_id, reason}`)。
计划物化、派发工具、看门狗、编排器 **NEVER** 写任何单元标记(派发工具按
磁盘标记收割、终态跳过,自身零标记写面;编排器唯一例外 = 第 3 节的认领删除)。
被中止 / 未落标记的单元经重枚举自然回待派——中止 ≠ 失败终态。共享任务模板
`fanout/{t1,t2,t3,scout-merge}-task.md` 的
「reference only; the dispatcher writes it」行描述的是子进程形态,原生形态
不适用且该模板零改动。

## 5. 收敛与披露

各层 `units_total == 0`(失败缺口已按第 3 节接受或为零)→ 按该步 stage
fragment 的既有段收尾(t1 → T1→T2 闸门;t2 → rollup / 校验;t3 → assemble;
scout-merge → rollup → audit → fold-in)。收尾写 `init_manifest.json` 时披露
实际派发形态与通道:`dispatch` 字段(与 resume_state 同源)+ 聚合层披露
(每层计划工件 `native_plan_<tier>.json` 在场证据 + 实际通道 A/B + 回退事实);
回退(通道 A / 子进程)均如实记录,NEVER 声称未发生的通道。

## 6. 诚实边界(收尾总结必带)

- 止损为**波次粒度**:原生子代理没有进程树可杀,挂死单元由看门狗按静默 /
  超时阈值中止兜底。
- **编排父会话是单点**:父会话挂掉则波次暂停;进度在磁盘(计划 + 标记),
  恢复会话经 `resume_state.py` 接上,已完成单元不重做。
- **一次物化只覆盖当前页**:大批量层靠页循环推进,`units_total` 是页级数不是
  全量数;通道 B 一次调用跑完的是**本页**的波次。
- 通道 A 回退下任务文件路径经编排器转述存在残余错抄面(防线 = 越树守卫 +
  重枚举回待派 + 至多一轮重派);令牌形任务体下该残余面只在展开钩子缺席的
  旧版安装回退形态成立。
