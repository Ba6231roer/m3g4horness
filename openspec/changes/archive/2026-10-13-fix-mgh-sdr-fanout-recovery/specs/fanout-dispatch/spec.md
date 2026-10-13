## MODIFIED Requirements

### Requirement: `--kill-stale` 检出并清理孤儿 runner 进程树(含 runner 已死的存活子进程)

`fanout_runner.py --kill-stale --tier <t> [--checkpoints <dir>] [--inputs-dir <dir>]`(其余 tier
artifact flag 同派发模式;`--checkpoints`/`--inputs-dir` 在 kill-stale 恢复模式 SHALL 可省略——
该模式下二者仅是扫描提示,省略时本功能照常工作,既有含参调用形不受影响)SHALL 处理 liveness
文件的两种残留形态:
① runner PID 仍存活且 cmdline 含 `fanout_runner.py` → 杀整个进程树(Windows
`taskkill /pid <pid> /T /F`,POSIX 进程组 SIGTERM)——覆盖「runner 还在跑」形态;
② runner PID 已死(或 cmdline 不匹配)但其 `children[]` 记录的宿主 CLI 子进程 PID 仍存活
且 cmdline 是宿主 CLI(`opencode`/`claude`)→ 逐个连树杀——覆盖「runner 与编排器被连带
硬杀(如用户杀掉整个 opencode 进程)、子进程 LLM 调用仍在烧 token」形态。两形态处理后均
删除 liveness 文件。stdout JSON 报 `{"kill_stale": {"killed": [{"pid","tier","kind":
"runner"|"child"}], "removed": [pid-file], "none": bool}}`;无任何 stale → `killed:[]`
退出码 0(幂等,可安全重复调用;存在被删除的 pid 文件时 `none` SHALL 为 false)。
破坏性守卫(R5.3b):真实杀进程 SHALL 先经 `--dry-run`(列出将杀 PID,不杀);缺
`--dry-run` 且检出将杀目标 → 退出码 2 + recipe。`--kill-stale` SHALL 对全部 tier 同构适用
(含未来新增 tier——机制只依赖 liveness 文件名约定,不含 tier 分支)。

**cmdline 探测的跨版本可用性(Windows)**:进程命令行探测 SHALL 不依赖单一平台工具——
SHALL 先试经典探测途径,失败(工具缺失/不可执行)时 SHALL 回退到 Windows CIM 探测
(PowerShell `Get-CimInstance Win32_Process`,PowerShell 为 Windows 核心组件,零附加依赖);
回退探测 SHALL 有单次超时与确定性输出解析。当 PID 确认存活但两种探测均不可用、cmdline 无法
判定时,SHALL fail-loud:stderr 披露探测不可用与后果,SHALL NOT 删除任何 liveness 文件,
SHALL NOT 以退出码 0 报告成功——孤儿归属无法判定时证据 SHALL 保留(孤儿进程 SHALL NOT 在
「静默零杀 + 销毁证据 + 假成功」路径上流失)。

**扫描根锚定**:kill-stale 的 liveness 扫描根 SHALL 与派发侧写入根使用**同一锚定逻辑**——
SHALL 锚定到 liveness 文件实际所在的 run 目录(经既有 plan-path 再锚定),SHALL NOT 按
「tier 参数形态的朴素父目录推断」扫描(该推断对目录形参数/仓根形参数会扫到无关目录而漏检)。

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

#### Scenario: 经典探测工具缺失时 CIM 回退检出目标

- **WHEN** Windows 上经典 cmdline 探测工具不存在(新版 Windows 已移除),孤儿 runner 与
  宿主 CLI 子进程真实存活,liveness 文件残留
- **THEN** 探测经 CIM 回退取得两者 cmdline,按双条件正确分类出 runner 与 child 目标;
  `--dry-run` 列出目标、真实执行连树杀并删除 liveness 文件(NEVER「零 targets + 删证据 +
  假成功」)

#### Scenario: 探测完全不可用时保全证据并 fail-loud

- **WHEN** PID 存活但两种 cmdline 探测途径均不可用(如受控环境禁用两者)
- **THEN** `--kill-stale` stderr 披露探测不可用,不删除任何 liveness 文件,退出码非 0;
  恢复决策留给调用方(NEVER 静默零杀且销毁证据后报成功)

#### Scenario: sdr 形态调用的扫描根命中真实 run 目录

- **WHEN** sdr tier 的规范恢复调用形执行(kill-stale + sdr 参数形态),liveness 文件位于
  run 目录
- **THEN** 扫描根锚定到该 run 目录,liveness 被检出并按形态处理(NEVER 扫到仓库父目录/
  仓根而报 `none:true`)

#### Scenario: 恢复配方省略 artifact 参数可运行

- **WHEN** 调用方按仓内恢复配方原样执行 kill-stale(仅 `--kill-stale --tier <t>`,省略
  `--checkpoints/--inputs-dir`)
- **THEN** 命令进入 kill-stale 分支正常执行(NEVER 因参数必填校验在 argparse 层退出)

### Requirement: crash 原因分类与限流 crash 风暴截断

`fanout_runner.py` SHALL 在单元以 **crash 终态**(非零退出或无 ack 回执)结束后,对该单元的
输出尾部(stdout/stderr 缓存尾,数据源 = 失活检测/运行留痕机制)做**确定性限流特征分类**:
命中特征集 `429`/`too many requests`/`rate limit`/`quota`(大小写不敏感,子串匹配)→ 该单元记
`crash_cause:"rate-limit"`,否则 `"unknown"`。分类 SHALL 对全部 tier 一致(共享派发循环,一处
生效);ok/failed/timeout/stall 终态 SHALL NOT 参与分类(仅 crash)。

**限流 crash 风暴截断(快路径止损)**:dispatcher SHALL 维护一个**crash 风暴观察窗口**(自上次
磁盘终态推进〔任一单元 ok/failed marker 落盘〕起累计的 crash 事件);当窗口内 crash 计数
≥ `--wave` **且全部** `crash_cause:"rate-limit"` 时,SHALL 立即停止派发剩余单元并**优先于新一轮
冷却**直接截断,以退出码 2 fail-loud:stdout 摘要报 `rate_limited:true` +
`rate_limited_crashes:[<unit>…]`,stderr 给**冷却 recipe**——等满一个配额窗口再 resume(窗口
时长以网关配置为准,如 10 分钟)、wave 校准公式(`wave = floor(8 ÷ 每子每分钟调用数)`,8 =
配额每分钟上限 × 80% 安全余量)、提示失活树杀不属 crash、提及本截断可经
`--no-rate-limit-stop` 禁用。截断 SHALL 先于零推进熔断触发(快路径);零推进熔断(慢路径,含
其熔断前一次退避)行为不变,仍是兜底。`--no-rate-limit-stop` 传入时 SHALL 完全跳过本截断。
**优雅退化**:特征集漂移(新网关措辞)→ 分类全 unknown → 本截断不触发,快败冷却路径照常
自愈兜底——文本签名仅是快停与披露层,NEVER 是唯一防线。非限流 crash(unknown)SHALL NEVER
计入风暴判定。

**截断与补位派发的同步语义**:「立即停止派发」SHALL 覆盖补位循环的取单元窗口——截断旗标
生效后,dispatcher SHALL NOT 再向网关提交任何新单元;主线程在**取单元之后、提交 spawn 之前**
SHALL 复查截断状态(或将派发决策与截断旗标置于同一同步域),使补位窗口 SHALL NOT 越过已生效
的截断旗标;已提交的在飞单元不受影响,照常收割记账。

#### Scenario: 限流 crash 风暴被立即截断

- **WHEN** 配额耗尽,一个观察窗口内 `--wave 5` 个单元相继 crash 且输出尾部均含 `429`/
  `Too Many Requests` 特征
- **THEN** 第 5 个 crash 终态判定完成后 dispatcher 停止派发(优先于再等一轮冷却),退出码 2,
  stdout `rate_limited:true` + `rate_limited_crashes` 含 5 个单元 id,stderr 冷却 recipe 给出
  等窗与 wave 公式;零推进熔断未被等待触发(快路径先停)

#### Scenario: 截断落地前补位窗口不越过旗标

- **WHEN** 截断旗标已生效,主线程补位循环已取出下一单元、尚未提交 spawn
- **THEN** 该单元不被提交(取单元后 spawn 前的复查命中截断状态),网关不再收到新请求;
  该回归场景连跑多次(≥5)结果稳定,NEVER 间歇放行

#### Scenario: 特征漂移时优雅退化到冷却路径

- **WHEN** 网关换用新错误措辞,窗口内 5 个 crash 输出尾部均不含任何特征串
- **THEN** 分类全 unknown → 风暴截断不触发;快败冷却(事件驱动)照常触发自愈,熔断兜底不变

#### Scenario: 单次偶发限流 crash 不触发截断

- **WHEN** 窗口内仅 1 个单元 crash 且带限流特征,其余单元正常终态推进
- **THEN** crash 计数 < `--wave`,不截断;该单元留 pending 照常重派,后续磁盘推进把窗口清零

#### Scenario: 混入非限流 crash 不触发截断

- **WHEN** 窗口内 5 个 crash 中 4 个带限流特征、1 个 `unknown`(如脚本缺陷)
- **THEN** 风暴条件不满足(须全部 rate-limit),不截断;unknown crash 走既有语义(留 pending/
  零推进熔断兜底)

#### Scenario: 禁用 flag 回退

- **WHEN** 调用传 `--no-rate-limit-stop` 且发生限流 crash 风暴
- **THEN** 无快路径截断,冷却与熔断路径行为与未引入本机制逐字一致

#### Scenario: ok/failed/timeout/stall 终态不参与分类

- **WHEN** 某单元 output 尾部含 `429` 字样但以 ok 终态收尾(如子代理在报告文本里引用了 429)
- **THEN** 不产生任何 crash_cause 记录,不进风暴计数;仅 crash 终态参与分类
