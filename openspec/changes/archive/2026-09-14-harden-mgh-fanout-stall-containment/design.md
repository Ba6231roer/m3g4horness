# design — harden-mgh-fanout-stall-containment

## Context

派发器现状(`core/scripts/fanout_runner.py`):波次屏障循环(`:1326-1327` 一次 join 全波)、
`Popen + communicate(timeout=call-timeout-s)`、超时路径 `proc.kill()`(`:559-560`)、
零推进熔断锚在波次边界(`:1351-1373`)。liveness/`--kill-stale`/sidecar/心跳已有。

故障现场(T1 resume,2026-09-14):两波各 1 子代理挂死(不同单元、输入 1.6–4.3KB、单元 A
重派后正常完成 → 非内容确定性),4 槽位陪等,宿主 15/60min per-call 硬杀整树,卡死单元无
marker 重派。已排除:残留进程(ps 全灭、`--kill-stale --dry-run` 无目标)、进度派生偏差
(resume_state 计数准确 176→180→184)、输入体积。

**opencode 源码证据**(本地仓 v1.18.16,装机 1.18.18):

| 事实 | 位置 | 对故障的意义 |
| --- | --- | --- |
| LLM 请求无整体超时(`timeout: false`),`chunkTimeout` 仅显式配置才生效 | `packages/opencode/src/provider/provider.ts:1763,1746` | **1.18.18 上唯一确认的无限挂面**:内网接口 SSE 流中段停摆 → 子进程零输出永久等;与现场完全吻合(无输出、无 marker、换单元随机复现、重派自愈) |
| 响应头超时 300s 仅个别 provider 类型默认启用,且只护到响应头 | `provider.ts:35,208` | 流中段不受保护 |
| run 非交互模式对 `question`/`plan_*` 显式 deny;权限 ask 事件由 run 内循环 auto-reject(`--auto` 则 approve) | `packages/opencode/src/cli/cmd/run.ts:430-448,796-815`;落地点 commit `1275c71a63`(2026-02-02) | 装机 1.18.18 权限 ask **不挂**(自动拒绝);但 2026-02 前版本 ask=无应答者=永久挂——跨版本挂面仍活着 |
| 权限 ask 无超时:`Deferred.await(deferred)` 挂起至有应答者 | `packages/opencode/src/permission/index.ts:101-106` | 上述跨版本挂面的机制本体 |
| 默认权限含 ask 类:`external_directory: {"*":"ask"}`、`doom_loop: ask`、`read *.env ask` | `packages/opencode/src/agent/agent.ts:108-136` | fanout agent frontmatter 只钉了 `read/glob/grep/list/bash/edit`,`external_directory`/`doom_loop` 落默认 ask(spike 期「子代理读 /tmp 停住要确认」即此触发面) |
| agent markdown frontmatter 支持 `permission:` 且合并进 agent 规则集(后合并者胜) | `agent.ts:293` + `packages/core/src/v1/config/agent.ts:38` | 钉扎落点:fanout agent 定义内显式化,版本无关 |

结构性结论:子进程挂死(LLM/网络/工具任意环节)不可消除,派发器必须自带**有界收敛**;
现状的波次屏障 + 无失活检测 + 非树杀 + 无留痕 + 不变式无校验,把单点挂死放大为
「整 run 停摆 → 宿主硬杀 → 重派再挂」循环且事后无证据。两条新守卫 spec 与本故障无关
(守卫是确定性拒绝,无等待应答路径)。

## Goals / Non-Goals

**Goals:**

- 单个在飞挂死的代价上界 = 一个槽位 × `--stall-timeout-s`(默认 15min),绝不外溢为整 run 停摆或宿主硬杀。
- 任何非 ok 终态都有磁盘证据(`*.run.log`),事后定位零猜测。
- 超时配置错误在 spawn 前拦截(fail-loud),不再静默退化。
- fanout 子会话对权限 ask 免疫(版本无关)。

**Non-Goals:**

- 不修 opencode 上游(建议项见 Open Questions);不依赖装机版本行为。
- 不改 ack 状态机/marker 真相源/枚举脚本/`--kill-stale`/liveness/sidecar 契约。
- 不把子进程输出流式转发进宿主 TUI(只做摘要心跳——逐行转发会冲爆 stderr,宿主把 stderr 收进结果即冲爆上下文)。
- 不上 `--auto`/`--yolo`(自动批准会放大越树授权面,与 read-confinement 反向)。

## Decisions

**D1 槽位补位调度(非屏障、非每完成全量重列)。** 每单元一个 future(`ThreadPoolExecutor`),
`concurrent.futures.wait(FIRST_COMPLETED, timeout=1s)` 轮询收割;收割即从内存 pending 队列
补位。**替代案 A(现状波次屏障)= 故障放大器,否**;**替代案 B(每终态全量重列枚举脚本)
费用 O(N×重列) 且与在飞写 marker 并发竞态,否**——补位前对下一单元 `.done`/`.failed`
marker `stat` 懒校验(O(1)、磁盘真相),run 结束与熔断窗口各做一次全量重列(汇总/熔断判定)。
`waves_run`/心跳 `wave=` 字段名不变、语义改为派发序数/累计派发数(消费方 fragments 只读
`partial`/`stalled`/`done`/`failed`,零消费方受影响)。

**D2 失活检测 = 字节级静默时长(非 CPU/内存探针、非仅绝对超时)。** 每在飞子进程两条读线程
(stdout/stderr)滚动更新 `last_byte_ts` 并缓存尾部(供 D4);静默 ≥ `--stall-timeout-s`
(默认 900,下限 60 否则退出码 2)→ 树杀。LLM 子代理正常态持续产出(tool 调用/文本流),
静默是挂死的高信度信号;healthy 单元分钟级(现场 2.5–3min),900s ≈ 5× 余量。误杀代价 =
留 pending 重派一次(run.log 可查),与现状 call-timeout 误杀同形但便宜 8×。
**替代案(仅 call-timeout)= 现状已证明失效**(7200s 兜底永远排在宿主硬杀之后)。

**D3 树杀统一复用 `_kill_tree`(`taskkill /pid <pid> /T /F`;POSIX killpg)。** 修
`proc.kill()` 孤儿 bug:Windows 直接子进程是 `.cmd` shim 层,真 host-CLI 进程在其下,
`proc.kill()` 必留孤儿继续烧 token(`--kill-stale` 只覆盖宿主硬杀形态,覆盖不到 runner 自身
超时形态;liveness `children[]` 记的还是 shim PID)。失活与 call-timeout 两条杀路径同改。

**D4 每单元 run.log 留痕。** 读线程缓存的 stdout/stderr 尾部(各 8KB 截断)落盘
`<checkpoints>/<tier>/<unit>.run.log`,文件名净化与 audit 副本同源(`/ \ :`→`_`,NTFS ADS
教训);ok 亦写(统一代码路径,体积小);非 ok 终态必写且 stderr 诊断行附绝对路径。
**替代案(仅 stderr detail 200 chars)= 现状,本次事故正因无证据而只能靠猜,否。**

**D5 不变式启动 fail-loud(R5.9 范式)。** 规则:传 `--time-budget-ms` ⇒ MUST 显式传
`--call-timeout-s` 且 `< budget×0.8`,且 `--stall-timeout-s < --call-timeout-s`;违反退出码 2
+ 合规取值 recipe,**spawn 之前**拦截。未传 budget(宿主外手动直跑)⇒ 默认组合放行 +
一次性 stderr 提示。**替代案(warn-only)否**——本次事故即静默错配(默认 7200 > 900s 宿主
预算),硬杀循环正是 spec 明文警告的退化形态;不校验等于把同一坑留给下一次。

**D6 fanout agent 钉扎 `external_directory: deny` + `doom_loop: deny`。** deny = 工具报错、
agent 按模板纪律适配(与 read-confinement 拒绝语义同向),ask = 无应答者挂(旧版)/静默
reject(新版,行为不可控且日志无因)。`--auto` 批准一切,放大越树读授权面(守卫 shim
fail-soft 时无第二道),否。合并语义:agent frontmatter 最后合并者胜(`agent.ts:293`),deny
生效;core 对显式 external_directory deny 的 `Truncate.GLOB` 自动 allow 合并不受影响
(pattern 级,opencode 自己的 truncate 目录可读,无害)。claude 侧不动(`-p` headless +
`--allowedTools` 白名单外自动拒绝,无问询挂面)。

**D7 熔断重锚:spawn 计数窗口 × 磁盘进度,双观察点。** 槽位补位下不存在波次边界;观察点
(a) = 每新派发 K=`--stall-waves × --wave` 个单元后全量重列一次磁盘终态计数;观察点 (b) =
队列耗尽且在飞归零后重派生发现仍有待派单元时(治「队列只剩坏死单元永远凑不满 K」的尾巴:
A 杀→重派→再杀,两次队列耗尽重列皆零增长 → 2 个观察点即熔断,一次 run 内 ~2 次尝试截断,
而非跨调用无限重派)。连续 `--stall-waves` 次零增长且队列非空 → stalled 退出 2
(`stalled_pending[]` 披露不变)。失活树杀不增磁盘计数 → 确定性挂死单元由熔断截断披露;
偶发失活(重派成功)重置窗口。**替代案(时间窗)受机器负载抖动影响,否**;锚磁盘计数
(非事件计数)才能治「每轮重派、磁盘恒零」的原病根。

**D8 心跳周期在飞披露(60s)。** 每分钟一行:在飞单元 id + 距该子进程上次输出秒数。现场
「57 分钟零输出不可判读」的直接对策;逐输出转发否(Non-Goals)。

## Risks / Trade-offs

- [失活误杀长思考/长工具单元] → 阈值 900s(5× healthy)+ run.log 留痕 + 留 pending 重派自愈;`--stall-timeout-s` 可调;下限 60 拒识。
- [内存 pending 队列与磁盘 marker 分歧] → 补位前 stat 懒校验 + 结束/熔断全量重列;marker 仍是唯一真相源。
- [字段语义重定义(`waves_run`/`wave=`)误伤消费方] → 契约面消费方(fragments/编排器纪律)只读 partial/stalled/done/failed/pending;spec 已显式声明语义。
- [软时限后仍在飞单元的收敛可越过 budget(至多 +call-timeout)] → 20% 余量堆叠(budget=宿主×0.8、call<budget×0.8)使越界通常仍落在宿主预算内;需要硬保证时调小 call-timeout(残余披露,非承诺消除)。
- [树杀偶发失败(进程恰已退出)] → 沿用现有 warn + 单元留 pending,语义不变。
- [D6 deny 使 doom_loop 反复失败不可见地循环] → 调用继续报错、run.log 可见,与 1.18.18 auto-reject 现状等价;且 D2+D7 保证任何此类循环有界。
- [心跳噪音(claude 宿主 stderr 收进结果)] → 60s 一行 × 分钟级单元 = 每 run 数十行,可接受;间隔可配。

## Migration Plan

纯脚本 + agent 定义 + 提示词调用面变更,无磁盘 schema 变化:install 即生效,`install.sh`
自检清单文件名不变。运行中 run 不可热升级(等 `partial:false` 或 `--kill-stale` 清理后装)。
回滚 = git revert 单点;新增 `*.run.log` 为附加产物,旧版本忽略之,无冲突。

## Open Questions

- 上游建议(另立 issue,不在本 change):opencode provider 默认 `chunkTimeout`;旧版 run 模式 ask 无应答者应即时 fail 而非无限挂。
- `--stall-timeout-s` 是否需按 tier 分档(sdr 审查单元更快)——先统一 900s,大仓实跑数据回来再校准。
