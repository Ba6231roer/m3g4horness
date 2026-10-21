<!--
  mgh-init scout native-dispatch wave discipline (opencode face). Loaded ON
  DEMAND by the mgh-init command shell / scout stage flow when the resolved
  dispatch form is native — the opencode install face default for consumer=init
  (no env-profile needed), or an explicit `dispatch_mode: "native"`. An
  explicit `dispatch_mode: "runner"` selects the subprocess fallback instead;
  the claude/dsh faces stay subprocess-only. Install mirrors to
  <mgh-core>/prompts/fragments/init-scout-native-dispatch.md.
  This is an ORCHESTRATOR discipline fragment, not a task template: the
  per-batch task message lives in prompts/fragments/fanout/scout-task.md
  (shared with the subprocess form, zero-changed); the per-batch agent
  behavior lives in the agent definition init-scout-native. Not loaded into
  any context automatically.
-->

# scout 原生派发波次纪律(/mgh-init,opencode 面 `consumer=init` 缺省形态)

适用前提:`env_profile.py --consumer init` 解析出 `form=native`——opencode 安装面不写任何
配置文件即缺省原生;项目画像显式 `dispatch_mode:"native"` 同样启用。项目画像显式
`dispatch_mode:"runner"` → 本 fragment 不适用,按步骤清单的 scout invocation 执行子进程
回退形态(fanout_runner 承载);claude/dsh 安装面仍只有子进程形态。**本形态只覆盖 scout
读者层**:scout-merge / rollup / audit / fold-in 仍按既有子进程段执行。

## 0. 看门狗先行(第一波派发前完成,不可跳过)

原生形态的挂死安全网是进程外看门狗,必须在**第一波派发之前**已在运行,且必须以
**脱离本次工具调用的独立进程**存在(工具调用结束后仍活)。

- Windows 宿主(shell 工具是 PowerShell——opencode 在 Windows 的实机形态;`&` 会被
  PowerShell 解析器直接拒绝,NEVER 用 `cmd... &` 形态):

      $p = Start-Process -FilePath <解释器> -ArgumentList @('<mgh-core>/scripts/native_watchdog.py','--run-dir','<init-dir>') -RedirectStandardOutput '<init-dir>/watchdog-boot.log' -RedirectStandardError '<init-dir>/watchdog-boot.err' -WindowStyle Hidden -PassThru; $p.Id

  (`<mgh-core>` 换成本 run 选定的安装根,`<init-dir>` = 本 run 的 `.mgh-init` 目录,
  全绝对路径;子进程继承父环境,故 `OPENCODE_SESSION_ID` 宿主注入对看门狗天然可见,
  零手工传参;`-PassThru` 回写的 pid 记入本 run 过程记录,供收尾后确需立即停止时使用。)

- POSIX 宿主(shell 工具是 POSIX shell):`py <mgh-core>/scripts/native_watchdog.py
  --run-dir <init-dir> > <init-dir>/watchdog-boot.log 2>&1 &`(记录 `$!`)。

- 阈值全部用缺省。**NEVER** 前台跑看门狗(会阻塞波次)、**NEVER** 代替看门狗做会话
  中止(它是挂死处置的唯一执行者)。路径全部用**树内绝对路径**——运行域守卫对裸相对
  重定向目标是保守拦截的(无法判属即拦),绝对树内路径一次通过。
- 退出语义:run 落定(树内无活跃、无等待项)看门狗自退;`--deadline-s` 未传 = 只按
  落定自退。
- 每波边界确认它仍在:`<init-dir>/watchdog/state.json` 有近两周期内的更新 = 活;发现
  缺席 → 用同一命令再拉起一次(幂等,events 续写)。收尾完成后若仍存活:等其自退
  (落定即退,通常一个巡检周期内);确需立即收尾时按记录的 pid 停止该进程。

## 1. 波次循环(每轮 = 重物化 → 自检 → 同消息派一波 → 派完该页回①)

每轮固定三步,**循环直到计划 `units_total == 0`**:

1. **物化 + 自检**(确定性脚本,stdout 直消费):

       py <mgh-core>/scripts/emit_native_plan.py --tier scout --scout-plan <init-dir>/scout_plan.json --checkpoints <init-dir>/checkpoints/scout --inputs-dir <init-dir>/inputs/scout --profile <target>
       py <mgh-core>/scripts/emit_native_plan.py --tier scout ...同参... --check

   `--check` 退出码 2 → 按 stderr recipe 处理(重物化即修复);**任一单元完成后计划按设计
   变 stale**(`--check` 报 stale/退出码 2)——波次收尾用重物化修复,NEVER 把这个退出码 2
   当故障、NEVER 消费过期计划。每轮重跑物化 = 重枚举:pending 由磁盘标记重派生(有终态
   标记的批自动出局),**NEVER** 自己记账「哪些派过了」。
   **页语义**:一次物化只覆盖枚举器当前 pending 页(编排预算会收紧页,stdout
   `units_total` 是本页单元数)——派完当前页回①重物化取下一页,直到一次物化给出
   `units_total == 0`(pending 清零)才进入第 4 节的 scout-merge;**NEVER** 把某一页的
   单元数误当全部批、**NEVER** 假设一次计划覆盖全部批、**NEVER** 手工翻
   `scout_plan.json`。
2. **同消息并发派发当前波**:读物化 stdout 摘要(`waves[]`/`wave_size`),对当前波全部
   单元,**在同一条 assistant 消息里**发出全部子代理调用(agent `init-scout-native`):
   - `description` = 该批计划短号(如 `scout-k3f7`,自计划逐字复制);
   - 任务体 = **单行令牌**:`mgh-dispatch: plan=<计划引用> unit=<短号>`——计划引用 =
     物化 stdout 摘要的 `plan_path` 逐字,短号自计划逐字复制。派发插件
     (`.opencode/plugins/mgh_dispatch.ts`)的令牌展开钩子会在子代理启动前把令牌行展开
     为该批任务文件全文(展开结果与计划物化产物逐字一致),模型输出里因此只有这一个
     计划引用,**零任务文件路径**。**NEVER** 凭记忆转述短号、**NEVER** 拼接改写、
     **NEVER** 自撰任务正文、**NEVER** 在任务体里另写任何文件路径。
   - 展开钩子缺席(旧版安装,插件文件不在场)时的受控回退:任务体 = 固定一句 +
     该批 `task_file` **绝对路径**(路径同样逐字自计划复制,零漂移);安装到位后
     **必须**回到令牌形。子代理收到裸令牌行且原样复述 = 钩子未生效的信号,先修安装
     再继续派发。
   **NEVER** 跨波合并派发、**NEVER** 自增并发(波次尺寸来自计划:并发与配额算术的较小
   者)、**NEVER** 逐个串行派发(同消息并发是形态的承重点:父会话单点下并发才摊得平
   时延)。**零批计划**:`units_total == 0` 的物化 = 没有待派批,跳过派发直接进第 4 节,
   不产生空波次、不把空计划当错误。
3. **波收尾重枚举**:当前波全部返回后回到第 1 步(重物化即重枚举)。子代理的成功/失败
   以磁盘标记为准(`.done`/`.failed`),回执行仅供人与日志读,**NEVER** 解析回执当进度。

## 2. 失败批:至多一轮重派,再败接受缺口

`.failed` 在场的批(原因非限流特征)至多重派**一轮**:

- 重派轮 = 删除该批旧 `.failed`(唯一的编排器标记动作,且是**删除**不是写入——与
  子进程派发器 `--retry-failed` 的认领即删语义同形)→ 重物化加 `--retry-failed`(该批
  回 pending)→ 派发一次。
- 重派再失败(新 `.failed` 再度在场)→ **接受缺口**,后续轮次不再派它;缺口在
  scout-merge 之前披露(终态计数入 manifest/report 既有失败披露)。**NEVER** 无限重派
  循环。
- 判定「这一轮是否已经重派过」靠本会话内执行留痕(你派过它一次就是一次);恢复的新
  会话若无法判定,允许再重派一轮——代价有界(一轮配额),仍 NEVER 循环。

**限流等窗**:上一波 `.failed` 原因含限流特征(429 / rate limit / quota)→ 按环境画像
配额(`quota.window_s`,未配置按网关公开口径,如 10 分钟)等满一个窗口后再重物化/重派,
把「何时等、等多久」写进本 run 的过程记录;**NEVER** 在限流窗口内连续重派烧配额。

## 3. 标记真相源(硬边界)

`.done`/`.failed` 的唯一写者是子代理自身(指令住在 `init-scout-native` agent 定义):
成功 touch `.done`,失败自写 `.failed`(内容 `{unit_id, reason}`)。计划物化、看门狗、
编排器 **NEVER** 写任何批标记(编排器唯一的标记动作 = 上面第 2 节的认领删除)。被中止 /
未落标记的批经重枚举自然回待派——中止 ≠ 失败终态,终态只能由批自身写出。共享任务模板
`fanout/scout-task.md` 的「reference only; the dispatcher writes it」行描述的是子进程
形态,原生形态不适用且该模板零改动。

## 4. 收敛 → 既有 scout-merge / audit / fold-in(形态不变)

`units_total == 0`(失败缺口已按第 2 节接受或为零)→ 回到命令壳 scout 步的既有
scout-merge 段:聚合预算闸门(`plan_aggregate.py --node scout-merge`)→ single-context
或 map-reduce(仍由子进程派发器承载)→ `init-scout-audit` → `merge_scout.py` fold-in。
这一段的行为、调用行与纪律**零改动**——本形态只换「读者批怎么派」,不换「查了什么、
怎么记、怎么并」。报告与 manifest 的失败披露沿用既有产物;派发形态与计划工件在场证据
按命令壳的披露要求写入收尾总结。

## 5. 诚实边界(收尾总结必带)

- 止损为**波次粒度**:原生子代理没有进程树可杀,挂死批由看门狗按静默 / 超时阈值中止
  兜底,不设更细的中途止损。
- **编排父会话是单点**:父会话挂掉则波次暂停;进度在磁盘(计划 + 标记),恢复会话经
  `resume_state.py` 接上,已完成批不重做。
- **任务文件路径经编排器转述存在残余错抄面**:防线链 = 越树路径被运行域守卫拦(fail-loud)、
  树内错配批因无标记经重枚举回待派、重派代价有界(至多一轮)。令牌形任务体下模型输出零
  任务路径(展开钩子把令牌展开为文件全文),残余面只在展开钩子缺席的旧版安装回退形态成立。
- **一次物化只覆盖当前页**:大批量 run 靠页循环推进,`units_total` 是页级数不是全量数。
