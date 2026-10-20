# fix-mgh-sdr-quota-adaptive-fanout

> **人话序** 现象:`/mgh-sdr` 在真实企业内网仓上跑不顺畅——网关限流 100 次调用 / 10 分钟,模型上下文只有 150K 且较弱,而派发器默认并发 5、快败冷却固定 300 秒、接口切片默认上限 256KB,三个量都没按这两个真实上限校准:并发把配额窗口瞬间打穿,429 后等 5 分钟窗口还没复位就重派,超大切片把弱模型的上下文顶到溢出边缘,溢出又引发重试,重试再烧配额。根因:每个评审单元的子代理内部要烧 5~10 次模型调用,发生在宿主命令行子进程里,派发器看不见,于是并发、冷却、输入预算三个旋钮都只能按"不限流的大窗口环境"设默认值。改什么:派发器新增配额感知准入(按窗口内已派发数 × 每单元调用估算节流)、命中限流特征时冷却改为"等到窗口复位"、sdr 壳派发行默认串行、任务模板加"一次并行读入全部输入 → 一次判断 → 一次写出"的单遍纪律、接口切片默认上限按 150K 窗口反算降到 96KB。怎么验证:小窗口仿网关脚本冒烟配额节流与窗口复位冷却,单测锁非配额路径逐字节不变,budget lint 锁 dsh 壳不超限。

## Why

- **真仓实测暴露的算术**(2026-10-15 维护者反馈):一次运行 67 个评审单元,每单元实测烧 5~10 次模型调用,合计约 350~670 次;在 100 次 / 10 分钟的配额下,纯排队就要 35~67 分钟。若每单元还发生多次往返(读切片、读基线、读敏感目录各算一轮),次数直接翻倍,配额根本不够。
- **当前默认组合在限流网关上自我放大**:`fanout_runner.py` 的 `--wave` 默认 5(无配额意识,`_fill()` 只按在飞槽位补位);快败冷却默认固定 300 秒——600 秒的配额窗口没复位就恢复派发,立刻再吃 429;接口切片默认 256KB,叠加 32KB 基线投影与 64KB 外部仓结论后,单次请求输入约 95~120K token,顶到 150K 窗口边缘,弱模型上表现为慢、截断、失败、重试,每次重试都在烧配额。
- **派发器结构性看不见调用数**:每个单元由宿主命令行子进程(`opencode run` / `claude -p` / dsh)拉起一个子代理会话,模型调用发生在会话内部,派发器只能数"派了几个单元",数不到"网关收了几次调用"。所以配额节流只能做成**估算式准入**(每单元调用数用保守估算值),不可能做成精确计数——这一定位本身要写进诚实边界。
- **需求已被既有 recipe 证明**:限流风暴截断的 stderr recipe 里早已写着手工校准公式「wave = floor(8 ÷ 每子每分钟调用数)」,说明"按配额算并发"是真实诉求,只是目前靠人在故障后手算。本 change 把它变成机器内建。
- **单遍纪律的一半已是现状,另一半缺措辞**:一个单元本来就在一个会话里判完全部 6 个维度(不存在按维度拆会话);缺的是任务模板没有明确要求"把读入合并成一批、把写出合并成一批",子代理自然的逐文件往返让调用数翻倍。

## What Changes

- **派发器配额准入(新增 flag 三件套,可选)**:`fanout_runner.py` 新增 `--quota-calls N`、`--quota-window-s W`、`--quota-calls-per-unit K`(估算值,默认保守取 10)。配额模式下,`_fill()` 派发前按"滑动窗口内已派发单元数 × K"估算已耗调用,余量不足一个单元则不派,等待窗口滑动(分片 sleep,受剩余时间预算约束,预算耗尽走既有软时限早退 + `--resume` 语义)。**未配置配额 flag 时行为与现状逐字节一致**(全部 tier)。
- **配额窗口复位冷却**:配额模式下,命中限流特征(`429`/`too many requests`/`rate limit`/`quota`)的快败事件把冷却终点定在「最后一次限流特征出现时刻 + 窗口时长」,替代固定 `--cooldown-s`;仍受既有"剩余时间预算封顶"逻辑约束,预算不够时截断等待并如实披露。非配额模式的冷却语义不变。
- **截断语义(仅配额模式)**:限流特征 crash 先吃窗口复位冷却自我恢复;只有**等满一个完整窗口后仍**出现限流特征才触发既有截断退出(说明配额参数配错或网关比声明更紧)。非配额模式截断阈值(窗口内 crash 数 ≥ `--wave`)不变。
- **sdr 壳与 launcher 默认串行**:三面 `mgh-sdr` 壳的规范派发行与 launcher 恢复指引默认带 `--wave 1`(内网串行最稳;opencode 并行子进程另有数据库锁前科,串行是双理由收敛),参数表文档给"内网建议 1~2"与配额 flag 用法;壳 token 预算按净零对冲(dsh 面 4997/5000,只余个位数余量)。
- **单遍往返纪律(任务措辞)**:`sdr-task.md` 模板与三面 `sdr-review-fanout` agent 定义增加一段任务措辞:全部输入(切片 + 基线 + 敏感目录 + 外部结论)**一次并行读入** → 一次判断 → **一次写出**(写 draft 与 touch marker 同批)→ 单行 ack;明示不要逐文件多轮往返。诚实边界:这是提示词纪律,降低但不保证调用数,真实调用数只能在网关侧度量。
- **切片默认上限校准**:`diff_group.py` 的 `DEFAULT_MAX_INTERFACE_BYTES` 256KB → 96KB(按 150K 窗口反算,给基线/敏感目录/外部结论/输出留余量);`DEFAULT_MAX_STANDALONE_BYTES` 维持 64KB(实测最坏上下文栈约 53K token 无溢出风险,再调小只会增加单元数反噬配额——对维护者建议值的偏离,算术见 design)。
- **文档与诚实边界同步**:命令人话说明、壳参数表、`--help` 文案、CHANGELOG/VERSION。

## Capabilities

### New Capabilities

<!-- 无。 -->

### Modified Capabilities

- `fanout-dispatch`:三处 requirement 修改——「Dispatcher 脚本消费 pending 清单并零 LLM 驱动槽位补位循环」增配额准入节流段(估算口径、flag 契约、等待与预算约束、未配置零变化);「快败冷却与熔断前有界退避」增配额窗口复位冷却段;「crash 原因分类与限流 crash 风暴截断」增配额模式"等满窗口才截断"语义。
- `security-design-review`:两处 requirement 修改——「fan-out 评审单元与 6 维度默认检查面」增单遍往返纪律(模板与三面 agent 定义的任务措辞契约)+ 壳派发行串行与配额指引;「切片物化的字节闸门与超预算三级处置」钉默认上限校准口径(interface 96KB / standalone 64KB,附 150K 窗口反算依据)。

## Impact

- **代码**:`core/scripts/fanout_runner.py`(准入节流、窗口复位冷却、截断语义、新 flag、`--help`、stdout 摘要增配额披露字段);`core/scripts/diff_group.py`(默认常量 + Usage 文案);`core/prompts/fragments/fanout/sdr-task.md`(单遍纪律段);三面 `mgh-sdr` 壳(`releases/opencode/command/`、`releases/claude-code/commands/`、`releases/dsh/skills/mgh-sdr/`)与三面 `sdr-review-fanout` agent 定义、dsh tier agent;`core/scripts/mgh_sdr_launch.py`(恢复指引行同步)。
- **契约/lint**:`tools/check_contracts.py` 增新 flag 断言(三面壳镜像);`tools/check_distributed_prompt_budget.py` 断言 dsh 壳不超 5000(净零对冲);purity 常规面。
- **测试**:`test_fanout_runner` 增配额面(准入算术 / 窗口复位冷却 / 等满窗口才截断 / 非配额路径逐字节回归;harness 层显式 `--cooldown-s 0`,小窗口值控墙钟);`test_diff_group`(默认值锚);`test_distributed_md_purity` / `test_dsh_command_surface` / agent 克隆 parity / `test_mgh_sdr_launch` 随分发面更新;`test_zero_deps` / `test_no_compile_warnings` 顺手带上。
- **文档**:维护者私有文档区里 `/mgh-sdr` 的命令人话说明补配额一节(参数、建议值、调用次数算术);术语词典按需补"配额窗口/准入节流"条目;CHANGELOG/VERSION bump。
- **与休眠提案的关系**:`improve-mgh-sdr-unit-packing`(打包降单元数,已规划未实施)的量化前提是"每单元 5~10 次调用";本 change 把每单元调用数往下压,会改变那份提案的成本收益比。本 change 不实现打包,两案不冲突、先到先得。
- **诚实边界**:准入节流是估算式(每单元调用数对派发器不可观测);单遍纪律是提示词级约束,非确定性可测;切片默认校准以本仓目标环境(150K 弱模型 + 调用次数限流网关)为基准,大窗口宽松环境的用户应显式调大 flag。
