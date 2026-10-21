<!--
  mgh-sdr native-dispatch wave discipline (opencode face only). Loaded ON DEMAND by the
  mgh-sdr command shell when the project environment profile selects native dispatch
  (`dispatch_mode: "native"`); the shell's subprocess fan-out line stays the default and
  the permanent fallback. Install mirrors to <mgh-core>/prompts/fragments/sdr-native-dispatch.md.
  This is an ORCHESTRATOR discipline fragment, not a task template: the per-unit task
  message lives in prompts/fragments/fanout/sdr-task.md (shared with the subprocess form,
  zero-changed); the per-unit agent behavior lives in the agent definition
  sdr-review-native. Not loaded into any context automatically.
-->

# 原生派发波次纪律(/mgh-sdr,画像显式 native 时)

适用前提:step 0 读到的环境画像 `dispatch_mode == "native"`。画像缺失 / `auto` /
`runner` → 本 fragment 不适用,回到命令壳的子进程派发行(缺省形态,行为零变化)。

## 0. 看门狗先行(第一波派发前完成,不可跳过)

原生形态的挂死安全网是进程外看门狗,必须在**第一波派发之前**已在运行,且必须以
**脱离本次工具调用的独立进程**存在(工具调用结束后仍活)。

- Windows 宿主(shell 工具是 PowerShell——opencode 在 Windows 的实机形态;`&` 会被
  PowerShell 解析器直接拒绝,NEVER 用 `cmd... &` 形态):

      $p = Start-Process -FilePath <解释器> -ArgumentList @('<mgh-core>/scripts/native_watchdog.py','--run-dir','<run-dir>') -RedirectStandardOutput '<run-dir>/watchdog-boot.log' -RedirectStandardError '<run-dir>/watchdog-boot.err' -WindowStyle Hidden -PassThru; $p.Id

  (`<mgh-core>` 换成本 run 选定的安装根,全绝对路径;子进程继承父环境,故
  `OPENCODE_SESSION_ID` 宿主注入对看门狗天然可见,零手工传参;`-PassThru` 回写的
  pid 记入本 run 过程记录,供渲染完成后确需立即收尾时停止进程。)

- POSIX 宿主(shell 工具是 POSIX shell):`py <mgh-core>/scripts/native_watchdog.py
  --run-dir <run-dir> > <run-dir>/watchdog-boot.log 2>&1 &`(记录 `$!`)。

- 阈值全部用缺省。**NEVER** 前台跑看门狗(会阻塞波次)、**NEVER** 代替看门狗做会话
  中止(它是挂死处置的唯一执行者)。路径全部用**树内绝对路径**——运行域守卫对裸相对
  重定向目标是保守拦截的(无法判属即拦),绝对树内路径一次通过。
- 退出语义:run 落定(树内无活跃、无等待项)看门狗自退;`--deadline-s` 未传 = 只按
  落定自退。
- 每波边界确认它仍在:`<run-dir>/watchdog/state.json` 有近两周期内的更新 = 活;发现
  缺席 → 用同一命令再拉起一次(幂等,events 续写)。渲染完成后若仍存活:等其自退
  (落定即退,通常一个巡检周期内);确需立即收尾时按记录的 pid 停止该进程。

## 1. 波次循环(每轮 = 重物化 → 自检 → 同消息派一波 → 收尾重枚举)

每轮固定三步,**循环直到 pending 清空**:

1. **物化 + 自检**(确定性脚本,stdout 直消费):

       py <mgh-core>/scripts/emit_native_plan.py --tier sdr --repo <target> --base <ref> [--branch <ref>] --checkpoints <run-dir>/markers --inputs-dir <run-dir>/slices --profile <target>
       py <mgh-core>/scripts/emit_native_plan.py --tier sdr ...同参... --check

   `--check` 退出码 2 → 按 stderr recipe 处理(重物化即修复);计划与单元任务文件都以
   **最新一次物化**为准。每轮重跑物化 = 重枚举:pending 由磁盘标记重派生(有终态标记的
   单元自动出局),**NEVER** 自己记账「哪些派过了」。
2. **同消息并发派发当前波**:读物化 stdout 摘要(`waves[]`/`wave_size`),对当前波全部
   单元,**在同一条 assistant 消息里**发出全部子代理调用(agent `sdr-review-native`):
   - `description` = 该单元计划短号(如 `sdr-k3f7`,自计划逐字复制);
   - 任务体 = **单行令牌**:`mgh-dispatch: plan=<计划引用> unit=<短号>`——计划引用 =
     物化 stdout 摘要的 `plan_path` 逐字,短号自计划逐字复制。派发插件
     (`.opencode/plugins/mgh_dispatch.ts`)的令牌展开钩子会在子代理启动前把令牌行展开
     为该单元任务文件全文(展开结果与计划物化产物逐字一致),模型输出里因此只有这一个
     计划引用,**零任务文件路径**。**NEVER** 凭记忆转述短号、**NEVER** 拼接改写、
     **NEVER** 自撰任务正文、**NEVER** 在任务体里另写任何文件路径。
   - 展开钩子缺席(旧版安装,插件文件不在场)时的受控回退:任务体 = 固定一句 +
     该单元 `task_file` **绝对路径**(路径同样逐字自计划复制,零漂移);安装到位后
     **必须**回到令牌形。子代理收到裸令牌行且原样复述 = 钩子未生效的信号,先修安装
     再继续派发。
   **NEVER** 跨波合并派发、**NEVER** 自增并发(波次尺寸来自计划:并发与配额算术的较小
   者)、**NEVER** 逐个串行派发(同消息并发是形态的承重点:父会话单点下并发才摊得平
   时延)。
3. **波收尾重枚举**:当前波全部返回后回到第 1 步(重物化即重枚举)。子代理的成功/失败
   以磁盘标记为准(`.done`/`.failed`),回执行仅供人与日志读,**NEVER** 解析回执当进度。

## 2. 失败单元:至多一轮重派,再败接受缺口

`.failed` 在场的单元(原因非限流特征)至多重派**一轮**:

- 重派轮 = 删除该单元旧 `.failed`(唯一的编排器标记动作,且是**删除**不是写入——与
  子进程派发器 `--retry-failed` 的认领即删语义同形)→ 重物化加 `--retry-failed`(该单元
  回 pending)→ 派发一次。
- 重派再失败(新 `.failed` 再度在场)→ **接受缺口**,后续轮次不再派它;缺口随报告披露
  (渲染器读 `.failed` 计入 `failed_units[]`)。**NEVER** 无限重派循环。
- 判定「这一轮是否已经重派过」靠本会话内执行留痕(你派过它一次就是一次);恢复的新
  会话若无法判定,允许再重派一轮——代价有界(一轮配额),仍 NEVER 循环。

**限流等窗**:上一波 `.failed` 原因含限流特征(429 / rate limit / quota)→ 按环境画像
配额(`quota.window_s`,未配置按网关公开口径,如 10 分钟)等满一个窗口后再查询/重派,
把「何时等、等多久」写进本 run 的过程记录;**NEVER** 在限流窗口内连续重派烧配额。

## 3. 标记真相源(硬边界)

`.done`/`.failed` 的唯一写者是子代理自身(指令住在 `sdr-review-native` agent 定义):
成功 touch `.done`,失败自写 `.failed`(内容 `{unit_id, reason}`)。计划物化、看门狗、
编排器 **NEVER** 写任何单元标记(编排器唯一的标记动作 = 上面第 2 节的认领删除)。
被中止 / 未落标记的单元经重枚举自然回待派——中止 ≠ 失败终态,终态只能由单元自身写出。

## 4. 诚实边界(收尾总结必带)

- 止损为**波次粒度**:原生子代理没有进程树可杀,挂死单元由看门狗按静默 / 超时阈值中止
  兜底,不设更细的中途止损。
- **编排父会话是单点**:父会话挂掉则波次暂停;进度在磁盘(计划 + 标记),恢复会话经
  `resume_sdr_state.py` 接上,已完成单元不重做。
- **任务文件路径经编排器转述存在残余错抄面**:防线链 = 越树路径被运行域守卫拦(fail-loud)、
  树内错配单元因无标记经重枚举回待派、重派代价有界(至多一轮)。

## 5. 收敛 → 渲染

pending 清空(失败缺口已按第 2 节接受或为零)→ 进命令壳 render 步
(`list_sdr_steps.py --step render` 取调用行;`render_sdr_report.py --check <run-dir>`
收尾)。报告与 manifest 会披露本次派发形态与计划工件在场证据;数据与子进程形态同源,
历史对照不断档。
