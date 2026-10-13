# fix-mgh-fanout-dispatcher-hygiene

> **人话序**:扇出派发器 `fanout_runner.py` 是 mgh-init / mgh-sdr 等域共用的并发引擎,2026-10-13
> 的全流程深度评审(维护者私有文档区的 mgh-init 全流程评审报告)在它的异常分支上确认了六处
> 卫生缺陷:① 熔断前退避挂起 + 队列空 + 冷却未到期时,主循环没有 sleep,100% CPU 空转最长
> 300 秒;② 失活/超时树杀的返回值被忽略且 POSIX 侧无 SIGKILL 升级——杀失败时单元照常重入队,
> 与幸存进程并发双跑、竞写检查点,进程号还从 liveness 摘除成不可追踪孤儿;③ 检测到投毒输入
> (路径越树)后的响应动作,竟然是向被判定越树的那个路径 mkdir + 写失败标记——「检测到投毒后
> 反而执行投毒路径」;④ 孤儿清理 `--kill-stale` 的进程身份匹配用全命令行子串包含,命令行里
> 任何位置含 opencode/claude/dsh 字样的无关进程会被整树强杀;⑤ spawn 未剥离 `PWD` 环境变量,
> opencode 按 `PWD ?? cwd` 解析项目归属,宿主外手动运行时会认错项目;⑥ 审计文件名净化是
> 枚举器编码的私有漂移拷贝(缺 200 字符截断),超长单元 id 的 `.task.md`/`.run.log` 超 NTFS
> 255 上限写盘失败仅 warn。本 change 按六项逐一收口:冷却等待覆盖退避挂起态、树杀失败检测 +
> SIGKILL 升级 + liveness 保留 + 本轮禁重派、越树路径永不物化、匹配锚定到可执行 token、
> 剥离 `PWD`、文件名编码归一回单一来源。验证 = 每项先红后绿回归测试 + 既有 fanout 全量定向面
> (含 sdr tier 用例)零回归。

## Why

评审基线(VERSION 0.1.60)之后 `fanout_runner.py` 经 a092e65 重写 293 行,本批六项发现已按
**内容**在 HEAD 逐一重定位并确认仍全部存在(行号引用为当前 HEAD 位置):

| # | 缺陷 | 评审定级 | HEAD 证据 |
| --- | --- | --- | --- |
| F1 | 冷却期忙等:退避挂起 + 队列空 + 冷却未到期 = 零 sleep 自旋(默认 300s) | Medium | 主循环冷却 gate 条件含 `(queue or inflight)`,两态皆空时无 sleep 分支 |
| F2 | `_kill_tree` 返回值被忽略 + POSIX 无 SIGKILL 升级;杀失败 → 重入队双跑 + pid 摘除成孤儿 | Medium | stall/timeout 两调用点不查返回值;`_kill_tree` POSIX 只发 SIGTERM |
| F3 | path-drift 拦截的响应向被检出越树的路径 mkdir + 写 failed marker | Medium | `_write_failed_marker` 直接物化 unit 记录的 marker 路径 |
| F4 | `--kill-stale` 子进程身份匹配 `cl.find(h) >= 0` 全命令行子串包含 | Medium | `_classify_targets` 第三个析取项 |
| F5 | spawn 未剥离 `PWD`(姊妹脚本 mgh_sdr_launch 已修同形并注明机理) | Medium(校准降级) | `_run_unit` env 继承全量,两 host 形均不剥 |
| F6 | `_safe_name` 私有拷贝与 `init_tier.safe_unit_filename` 漂移(无 200 截断) | Low | 审计 `.task.md`/`.run.log` 文件名仅做 `/ \ :` → `_` |

这些路径的共同特征:全部住在**异常分支**上(风暴退避、杀失败、投毒输入、孤儿恢复、超长 id),
正常流的测试与实机跑不经过它们,所以架构评审的正面结论(槽位补位/正向 marker/原子写)不受
影响,但一旦触发,后果是资源空转、数据竞写、误杀无关进程、越树写与静默丢证据——与全仓
fail-loud 文化相悖。评审同时确认两项同域发现已被更早的 sdr 批次顺带修复(kill-stale 的 wmic
失效已加 CIM 回退、退出摘要 failed 双计已修),本批**不含**这两项。

## What Changes

`core/scripts/fanout_runner.py` 六处收口(全部异常分支,正常路径行为零变化):

1. **冷却等待覆盖退避挂起态(F1)**:主循环的冷却 gate 改为「冷却生效中且无在飞 → 分片
   sleep 等待」,不再要求队列非空;退避挂起 + 队列空 + 冷却未到期的组合从自旋变为休眠。
2. **树杀失败检测与升级(F2)**:`_kill_tree` POSIX 侧 SIGTERM 后短宽限内复查进程组存活性,
   仍存活则升级 SIGKILL;Windows 侧 `taskkill` 失败重试一次。stall/timeout 调用点检查返回值:
   确认杀失败时,该单元**不再重入队**(幸存进程拥有该单元,其终态 marker 由幸存者或后续
   resume 落盘),pid **保留在 liveness** `children[]`(供 `--kill-stale` 检出),stderr
   fail-loud + stdout 摘要新增 `kill_failed:[unit…]` 披露。
3. **path-drift 响应永不物化越树路径(F3)**:`_write_failed_marker` 写盘前校验 marker 路径
   resolve 后在 repo 锚树内:树内 → 照旧写(现有各 tier 场景语义不变);树外 → NEVER
   mkdir/写盘,stderr fail-loud recipe,该单元留磁盘 pending(有界性由既有零推进熔断承担,
   `stalled_pending[]` 披露)。
4. **kill-stale 身份匹配锚定可执行 token(F4)**:子进程匹配从「全命令行子串包含」改为
   「argv[0] 路径基名(大小写不敏感,剥 `.exe`/`.cmd`/`.bat` 扩展)∈ {opencode, claude, dsh}」;
   误杀方向(假阳性)归零,漏杀方向退回既有「PID 复用防护」路径(不杀 + 清 liveness 文件)。
5. **spawn 剥离 `PWD`(F5)**:全部 host 的子进程 env 构造改为 `os.environ` 去除 `PWD`
   (dsh 形继续附加 `MGH_TASK_TEXT`);opencode 项目归属回落到显式 cwd = repo。
6. **审计文件名编码归一(F6)**:`_safe_name` 改为 `init_tier.safe_unit_filename` 的别名
   (list_scout_batches 同款形态),超长 id 获得 200 stem 截断(含判别尾),`.task.md`/
   `.run.log` 永不超过 NTFS 255 上限;短 id 文件名逐字节不变。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `fanout-dispatch`: 5 条 requirement 修改——「ack 状态机与 marker 真相源语义承接」(marker
  写入加 repo 锚定守卫)、「宿主 CLI 探测与 headless spawn 映射」(子进程 env 剥离 PWD)、
  「`--kill-stale` 检出并清理孤儿 runner 进程树」(子进程 cmdline 匹配锚定可执行 token)、
  「在飞单元失活检测与外科手术式树杀(运行留痕)」(杀失败检测/升级/liveness 保留/本轮禁
  重派 + 运行留痕文件名编码归一)、「快败冷却与熔断前有界退避」(冷却等待覆盖退避挂起空队
  列态,禁忙等自旋)。

## Impact

- **涉改文件**:`core/scripts/fanout_runner.py`(单文件,六处;守护三镜像
  `releases/*/hooks/block_adhoc_scripts.py` 不涉及)。该文件被六域共用(TIERS =
  scout/t1/t2/t3/sdr),改动全部位于 tier 无关的共享异常分支,无 tier 分叉逻辑。
- **stdout 契约**:摘要新增 `kill_failed:[unit…]` 键(仅确认杀失败时出现;无杀失败时省略,
  同 `runtime_p50_s` 等既有可选键惯例);其余字段零增删。
- **回归面**:`tests/test_fanout_runner.py` + `tests/test_fanout_stale.py`(先红后绿新增
  ~8 组)+ `test_zero_deps` / `test_no_compile_warnings`;定向面跑完确认 sdr tier 用例零回归;
  新增 harness 调 `fanout_runner.main()` 一律显式 `--cooldown-s 0`(R5.8 纪律)。
- **VERSION**:脚本改动 → apply 会话 bump(0.1.69 → 0.1.70)+ CHANGELOG。
- **不改动**:枚举器、resume 状态机、守卫、壳与 agent 定义、install 接线;评审同域的
  wmic/CIM 回退与 failed 双计已修项不重修;预算转发(run_config `budgets.max_unit_bytes`
  无消费者)属批次 5,不在本批。
