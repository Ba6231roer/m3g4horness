# 实机笔记 — fix-mgh-sdr-native-dispatch(0.1.86)

机器:维护者本机(Windows,Git Bash;`python` 3.14 / `py` shim 均可用)。日期:2026-10-21。
宿主:opencode 2.1.0 常驻服务(`~/.local/state/opencode/service.json`,url 回环
`http://127.0.0.1:45278`)。模型:全部会话钉 `zai-coding-plan/glm-5.3-flash`(与本仓前
几次实机闸门同源)。

## 1. 闸门仓

`C:\DEV\_mgh_native_plan_gate`(scratch 真仓,复用计划物化 change 的闸门仓;本 change
扩充了分支 diff 并重装工作树分发面):

- 分支 `feat/security-fix` vs `master`:6 个 java 文件(UserController/OrderController/
  ReportController/OrderService/UserDao + application.properties)→ **7 个评审单元**
  (6 interface + 1 standalone;接口注解启发式把类级路由上下文拆为独立单元,与既有
  分组行为一致)。
- 分支内容是**有意埋雷的安全缺口**:无权限注解的路由、调用方可控 userId 直拼 SQL、
  未脱敏手机号查询等——供两形态对照 findings 集合。
- 安装:`bash install.sh --opencode C:/DEV/_mgh_native_plan_gate`(工作树全量分发面,
  含新 agent `sdr-review-native`、新 fragment、2.x 插件带权限闸门)。
- 环境画像:`.mgh/env-profile.json` = `{"v":1,"dispatch_mode":"native","native_concurrency":3}`
  (Run B 前写入;Run A 全程**无画像** = 子进程形态)。

## 2. 任务 5.1 + 5.3:两形态对照全链

### Run A(对照基线:子进程形态,无画像)

编排决策按命令壳等价地机械执行(确定性链,dispatch 本体 = runner):

```
cd C:/DEV/_mgh_native_plan_gate                       # 当前分支 feat/security-fix
mv .mgh/env-profile.json /tmp/…                       # Run A 全程无画像
mkdir -p .mgh-sdr/runs/20261021_runA-runner
G=.opencode/mgh-core/scripts
python $G/resume_sdr_state.py --run-dir <R> --repo . --arm-sentinel     # → armed:true
python $G/sdr_context.py --repo . --run-dir <R> --base master --branch feat/security-fix
python $G/diff_group.py --repo . --base master --branch feat/security-fix \
  --checkpoints <R>/markers --materialize <R>/slices                    # → 7 units
python $G/diff_group.py --check <R>                                     # → ok
python $G/fanout_runner.py --tier sdr --repo . --base master --branch feat/security-fix \
  --checkpoints <R>/markers --inputs-dir <R>/slices --wave 1 \
  --time-budget-ms 1500000 --call-timeout-s 540 --stall-timeout-s 300
python $G/render_sdr_report.py --run-dir <R> --repo .                   # + --check
```

(结果见 §2.1)

### Run B(原生形态,画像 native)

经服务 API 驱动一个编排器会话(与看门狗 change 闸门同驱动形):`POST /api/session`
(`location.directory` = 闸门仓)→ `POST /api/session/:id/prompt`(模型钉
`zai-coding-plan/glm-5.3-flash`;prompt = mgh-sdr 命令全文 + 「按 zero-arg 默认路径执行,
不要向用户提问」)。编排器会话按新壳执行:step 0 画像读取(native)→ 哨兵预武装 →
sdr_context → diff_group → fan-out 原生形态(fragment:看门狗先行 → emit_native_plan
物化+`--check` → 同消息并发派 `sdr-review-native` → 标记 → 重物化重枚举)→ render。

(结果见 §2.2)

### 2.1 Run A 结果(子进程形态基线)

- fan-out 分两段完成(首段 25min 软时限到点 `partial:true` 干净早退,`--resume` 接续,
  已完成单元零重做——顺带证明 resume 语义):**7/7 done,0 failed,partial:false**。
- 渲染 + `--check` ok:findings **24**(高 9 / 中 8 / 低 7),failed_units 0。
- 24 条 findings 全部落在预埋缺口上(无权限注解路由 / 调用方可控 userId 拼接 SQL /
  手机号未脱敏 / 明文口令入仓 / 入参零校验),三处口径正确(简报表、详情、诚实边界)。

### 2.2 Run B 结果与对照结论(原生形态)

驱动:会话 `ses_ea5812e37fferreRU7VcfiD8v0`(模型 `zai-coding-plan/glm-5.3-flash`),
prompt = mgh-sdr 命令全文 + zero-arg 指令,outcome **succeeded**,全程零人工介入。

编排器逐项走完了新壳的原生路径(全部由磁盘产物证实):

| 观察点 | 结果 |
| --- | --- |
| step 0 画像读取 | `.mgh/env-profile.json` native 生效,fan-out 走原生形态 |
| 看门狗先行 | `<run>/watchdog/state.json` 在第一波前出现;全程 150 周期,树内最多 4 会话(根 + 3 并发子代理),**零事件零动作**(rejected/cancelled/aborts 全 0) |
| 计划物化 | `native_plan.json` + 7 份 `<unit>.task.md`;波次 3×3(wave_size=3,concurrency);短号三方映射闭合 |
| 同消息并发 | 看门狗树快照证实 3 子代理同波在飞;7/7 单元终态 marker 齐(全部 `.done`,零失败) |
| 波间重枚举 | 第一波后计划重物化,`units_total` 7→4(重物化即重枚举生效) |
| 渲染 + 披露 | 报告 + manifest + data 齐;manifest/data `dispatch.form == "native"` + 计划工件证据;头部「派发形态」行;诚实边界 7 条(基线 6 + 原生 1) |

**对照结论(同输入两形态)**:两 run 单元粒度**零丢失**(7/7 单元两形态均有 draft,
failed 均 0)。findings 层面:(dimension, file) 归一后 A 17 项 / B 18 项,交集 16——
A 有 1 项未在 B 复现(OrderService 的「日志打印含参 SQL」被 A 记 sensitive-data,B 对
同一文件记了 sql-injection high 但未单列日志角度),B 新增 2 项 A 未报的
UserController 角度。**口径:同一单元的两个 LLM 实例非确定性差异,非派发形态丢失**
(该单元 B 侧 4 条 findings 全在预埋缺口上);「finding 丢失为零」在**单元粒度**严格
成立,在 finding 粒度受 LLM 非确定性上界约束(与子进程形态两次重跑之间的波动手性一致)。
原生形态会话总时长约 37 min;runner 形态约 60+ min(串行 8~9 min/单元,另含一次
25min 软时限暂停与 resume 接续)——3 并发 vs 串行的时延差方向明确,精确倍数受单次
会话波动上界约束,不作为效率结论只作方向证据。

**诚实记录(plan agent 字段与 fragment 的措辞差)**:计划工件 `agent` 字段沿 tier 表
写 `sdr-review-fanout`(基础件零改动面的既有值),编排器按 fragment 指派
`sdr-review-native` 实派——两字段语义不同层(计划信息字段 vs 纪律指派),实机证明
编排器未被误导;后续 hardening 若做插件令牌展开可顺带让计划携带 native agent 名。

### 2.3 缺省零变化抽查(任务 5.3)

- Run A 即无画像抽查:`list_sdr_steps.py --step fanout` 输出**无 `dispatch` 字段**、
  fanout 步 `script == "fanout_runner.py"`(子进程面逐字不变);`resume_sdr_state.py`
  同仓输出无 `dispatch` 字段;渲染产物无 `dispatch` 字段(诚实边界 6 条基线)。
- 看门狗收尾:run 落定后**无孤儿进程**(进程表零 `native_watchdog` 命中);boot.log
  末行为 cycle 150 心跳、无自退摘要行 → 与「编排器按 pid 收尾」形态一致(fragment 允许
  的两条收尾出口之一);「落定自退」语义本身已在看门狗 change 实机闸门验证(settled →
  exit 0)。

## 3. 任务 5.2:故障注入五件套

### ① 单元失败 → 至多一轮重派(inj1 + inj2,实机过)

- **inj1(真实失败注入,未命中读窗)**:在波次在飞期间删除某 pending 单元的 slice
  (确定性窗口 = 波内不再重物化),但该单元子代理已先读完 slice → 照常 `.done`,
  注入未命中。run 本身 7/7 完成——顺带再次证明波内并发与重枚举不受外部文件扰动影响。
- **inj2(植入 `.failed`,编排器反应全链,实机过)**:预置
  `{"unit_id":"OrderController___order_create","reason":"provider 500 internal error
  (simulated)"}` 后驱动恢复会话。会话留痕逐条命中纪律:resume 接上(step=fanout,
  done 0/failed 1/待派 6,dispatch=native)→ 看门狗先行(Start-Process,PID 52968
  记录在案)→ **原因分类**(「非限流特征——无 429/rate limit/quota,无需等配额窗」)
  → **认领删除旧 `.failed`**(Test-Path 复核 = False)→ 重物化带 `--retry-failed`
  (重派单元回 pending)→ 派发一轮 → 重派单元 `.done` → 7/7 收敛 → 渲染 + gate ok。
  最终 manifest:units 7,failed_units 0——**「至多一轮」且本轮即恢复,无循环**。
- **重派再败 → 缺口披露(渲染面确定性注入)**:`.failed` 在场单元由渲染器计入
  `failed_units[]` + 诚实边界「N 个评审单元失败…」条目——该闭环在 inj2 的意外岔路上
  得到**真实演练**(见下方 BOM 事件):一个单元被渲染器判为失败时,报告如实披露,
  `--check` 全程 ok。

**附带真实发现(中断竞态:done 无 draft,记为后续 hardening 候选)**:inj4 中断
命中了一个子代理的收尾窗口,留下 `report_daily.done` 在场而 draft 缺失的形态。resume
按标记判终态(不再重派该单元),渲染器按 drafts/*.json 计单元——该单元会**无声缺席**
报告。子进程形态硬杀窗口同形(非本 change 引入)。候选后续:①resume 增一条 advisory
note(done 无 draft → 提示删旧 `.done` 重派);②渲染器对 done-without-draft 计数披露。
均不在本 change 范围。

**附带真实发现(BOM 岔路,记为后续 hardening 候选)**:inj2 某重派子代理经 PowerShell
重定向写出带 UTF-8 BOM 的 draft,渲染器 JSON 解析失败 → 该单元被如实判为
`failed_units=1` + 披露行(诚实边界按设计工作);编排器读披露后定位根因,归一化 draft
后重渲染,failed_units 归零。两条候选后续:①渲染器 draft 读取改 `utf-8-sig` 容忍;
②原生 agent 定义补「写 draft 禁带 BOM」一行。均不在本 change 范围(评审本体零改动面)。

### ② 限流等窗(inj3,实机过)

植入 `{"reason":"429 Too Many Requests: rate limit exceeded, quota window reset at
+600s"}`(画像配额窗口 60s)后驱动恢复会话。会话留痕:**波次跑完 pending 清零后,
编排器先做等窗判定再重派**——逐字:「failed 标记落盘于 04:03:02,现已 04:14:13 —
画像配额窗(60s)乃至网关口径(600s)均已等满。重物化(带 `--retry-failed`)并自检」
(等窗判定以标记 mtime 为准;等待事实与看门狗 pid 一起写入 run 过程记录)→ 认领删除
→ 重物化 `--retry-failed` → 派发一次 → 单元 `.done` → 7/7 收敛 + 渲染。**至多一轮 +
限流先等窗,两条纪律同轮实证。**

### ③ 权限 ask → 无人值守不挂死(双层,实机过)

- **闸门层(运行域内,主防线)**:运行域哨兵在场时,探针子会话读 `.env` 触发的 ask 被
  权限闸门直接改写为 deny;模型收到拒绘认知后**正常收尾(outcome succeeded)**,零
  挂死、零重试绕行——与权限闸门 change 的契约一致,此处补齐了它在原生 run 上下文的
  行为学证据。
- **看门狗层(域外 backstop)**:无哨兵目录中同一 ask 形态浮出为 pending permission →
  看门狗(8s 宽限)`action_reject_permission`(文案「无人值守,继续完成本回合」)→
  子会话继续并收尾 → 树落定看门狗 `exit reason=settled code=0`。

### ④ 挂死 → 看门狗中止(inj-probe,实机过)

合成树(父 + 长静默子会话 `Start-Sleep 600`),看门狗小阈值(`--silence-s 25`):
cycle 3 `action_abort reason=silence` → 子会话 `outcome=interrupted`;树落定后看门狗
**自退 `reason=settled code=0`**(补齐 Run B 未展示的自退腿;Run B 收尾走的是纪律
允许的另一出口「按 pid 停」)。「单元回待派」腿 = 无标记单元经重枚举回 pending,已在
Run B 波间重枚举(7→4)与 inj2 重派轮(重物化 `--retry-failed` 使单元回 pending)
两处实证。

### ⑤ 中断打断 → 恢复接上(inj4,实机过)

原生 run(显式 run 目录)跑至 3/7 `.done` 时经服务 API `interrupt` 打断编排会话 →
新会话按「中断恢复」纪律接上:resume 派生 `step=fanout`、tiers 3 done / 0 failed /
7 total、`next_action.kind=subagent`(原生波次相)→ 重物化重枚举后**只派余下单元**,
已完成单元零重做(中断前两份 draft 逐字节哈希不变);跑完 7/7 + 渲染
(manifest units 7 / failed 0 / findings 21 / `dispatch:native`),outcome succeeded。
interrupt 竞态的 done-无-draft 边缘形态见上方「附带真实发现」第二条(在飞写盘于中断
后落盘补齐,终态一致)。

## 4. 附带实得(三个钉扎级发现,均已回写实现)

1. **Windows 宿主的 shell 工具是 PowerShell,POSIX `&` 后台形态直接解析失败**:
   探针会话跑 `… > <树内绝对路径> 2>&1 &` → `AmpersandNotAllowed`,瞬间退出,零后台
   进程。原生形态看门狗启动配方改为 `Start-Process … -WindowStyle Hidden -PassThru`
   (fragment §0 + discipline_core 看门狗 recipe 同步);**存活实测**:Start-Process
   启动的 90s sleep 子进程活过工具调用与会话收尾,到期自行完成并写出日志——「脱离
   工具调用的独立进程」这一看门狗存在性前提在 opencode 2.1.0 Windows 宿主成立。
2. **运行域守卫对裸相对重定向目标是保守拦截**(无法判属即拦):`> bgprobe.log`
   (目标其实在项目根内)被拦,报 `out-of-tree redirect`;换成树内**绝对**路径一次
   通过。fragment 启动配方已注明「路径全部用树内绝对路径」。
3. **`python -c` 内联解释器在运行域内被守卫确定性拦截**(既有防线,探针当场踩中):
   首个探针命令用了 `python -c` 形态被拦;模型按守卫 recipe 如实报告、未重试绕行——
   守卫与模型纪律的双向行为学证据。

(另:服务 API 形状钉扎——2.1.0 `POST /api/session` 响应带 `{"data":…}` 信封;
`POST /api/session/:id/prompt` 请求体是平铺 `{text, …}`,模型在会话创建时以
`model: {providerID, id}` 传入,`modelID` 字段名 400。)

## 5. 任务 6.1:企业 2.0.32 闸门清单(交接内网执行,不阻塞归档)

前置:内网机 `opencode --version` 确认 2.0.32;目标仓已 `install.sh --opencode` 装
0.1.86 分发面;`.mgh/env-profile.json` 写
`{"v":1,"dispatch_mode":"native","native_concurrency":2,"quota":{"calls":100,"window_s":600,"calls_per_unit":10}}`
(内网 100 次/10 分钟网关口径;并发 2 起步)。CAS 认证按维护者私档操作细则完成
(`mgh-special-auth.md` 在场时优先;原生形态下凭证走宿主会话自身 provider 配置,
不经 `--cred-file`——子进程凭证注入面不适用,这正是本 change 消灭的失败点)。

逐步(在一个交互式 opencode 会话内,目标仓为工作目录):

1. 会话内执行 `/mgh-sdr`(零参 = base=master / 当前分支 / 全 6 维)。
2. 观察点 A(step 0):`env_profile.py` 输出 `dispatch_mode=native`,stderr
   `[env-profile] ok`;随后哨兵预武装成功(stdout `armed:true`)。
3. 观察点 B(step 1-2):`sdr_context.py` / `diff_group.py` 正常产出;`--check` 退出码 0。
4. 观察点 C(fan-out 原生形态):
   a. `<run-dir>/watchdog/state.json` 在第一波派发前出现(看门狗先行);
   b. `<run-dir>/native_plan.json` + `<run-dir>/slices/*.task.md` 物化;
   c. 事件流里同一条 assistant 消息发出当前波全部子代理调用(波次尺寸 = 2);
   d. 每单元落 `<run-dir>/drafts/<unit>.json` + `markers/<unit>.done`(或自写
      `.failed`,内容含 `{unit_id, reason}`);
   e. 波间 `<run-dir>/native_plan.json` 被重物化(pending 缩小)。
5. 观察点 D(render):报告 + `sdr_manifest.json` + `sdr_report_data.json` 落盘,
   manifest 含 `dispatch.form == "native"`;报告头部有「派发形态:native」行;
   诚实边界含波次粒度止损 / 父会话单点 / 路径转述残余条目。
6. 收尾:run 落定后看门狗自退(`<run-dir>/watchdog/state.json` 末次含退出结论,
   无残留 watchdog 进程);`.mgh-sdr/.active` 已移除。
7. 预期:7 单元(或按真仓实际 diff)全部终态;对照本仓 §2 的两形态 findings 集合口径,
   CAS 网关下不再出现子进程形态的 >99% 鉴权失败(原失败场景 = headless 子进程带不出
   内网鉴权态,原生形态的子代理与父会话同宿主同鉴权)。
8. 任何一步与上述形状不符(尤其 2.0.32 的 subagent 工具/事件字段/权限面差异):
   记录差异现象与 `opencode --version` 输出,回填
   `core/contracts/fanout/runtime.md` 版本矩阵与 `core/contracts/sdr/pipeline.md`
   「原生派发形态」节,不改代码先出问题清单。

回执口径:以上观察点 A–D + 收尾全部符合 = PASS;任一不符 = 差异清单回执(阻塞企业
画像默认 native 的推广,不阻塞本仓归档)。

## 6. 定向回归与 lint 摘要

- **新增/扩展测试(先红后绿)**:`test_list_sdr_steps` 14→20(三形态快照/native 展开/
  坏画像 fail-closed/native 纪律与 resume 逐字等价);`test_resume_sdr_state` 39→46
  (无画像零 dispatch 字段/native 无计划→物化、有计划→派波/标记组合(部分完成·有失败·
  全终态)/坏画像 derive+`--check` 双路 exit 2/看门狗缺席 note);`test_render_sdr_report`
  65→69(披露行/坏画像降级/双形态同数据 diff 仅披露字段);新增
  `tests/test_sdr_native_dispatch.py` 16 锚(壳原生条件步 + 三面披露行 + fragment 各节 +
  agent 孪生克隆对账(权限块逐字 + Output schema 块逐字)+ 共享模板写者行不动 + 两契约
  节;删任一锚即红,红转绿复验过)。
- **定向回归**:sdr 面 10 文件 + 基础件(`test_env_profile`/`test_emit_native_plan`/
  `test_native_watchdog`)+ `test_zero_deps` + `test_no_compile_warnings` +
  `test_distributed_md_purity` + `test_dsh_command_surface` + `test_fanout_runner`/
  `test_fanout_stale`(回退路径)全绿;唯一失败
  `test_diff_group::test_cg_probe_failure_reason_on_stderr` 经 stash 对照为 HEAD 存量
  环境相关(与 0.1.82 全量时同一失败,与本 change 触碰面零交集)。
- **lint 四件套**:contracts 504 flags / purity 342 文件 0 违例(allowlist 174——仅
  `core/contracts/sdr/pipeline.md` 既有条目行号随新增契约节漂移重钉 139→164,条目数
  不变;初稿曾在版本矩阵行引 `core/contracts/` 树路径被 purity 拦下一次,改相对链接后
  净)/ budget 17 壳(mgh-sdr 4767 mid-tokens)/ plain_language exit 2 = 三个存量
  change proposal 缺人话序(与本 change 零交集)。
- **openspec**:`validate "fix-mgh-sdr-native-dispatch" --strict` valid;`validate
  --specs` 30/30。

## 7. 驱动注记(诚实边界)

本笔记全部原生 run 经服务 API 以**平铺文本 prompt** 驱动(命令全文嵌入 prompt);
真实用法中 `/mgh-sdr` 是 opencode 注册命令(command 面),宿主以命令调用形注入——
两种驱动形的差异在弱模型上的外显:个别会话(两例)先花十余分钟「寻找命令定义/审计
工作区」才进入编排(隐藏目录 glob 缺席、command 未注册的疑虑),随后均自行收敛按壳
执行;成功会话(Run B / inj2 / inj3)则直接进流水线。该漂移是驱动 harness 的人为物,
非分发面缺陷;实机结论以「进入编排后的行为」为准。
