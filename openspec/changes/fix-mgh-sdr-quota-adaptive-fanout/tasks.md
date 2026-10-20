## 1. 派发器配额准入(fanout_runner.py)

- [x] 1.1 新增配额三 flag(`--quota-calls`/`--quota-window-s`/`--quota-calls-per-unit`,默认 K=10)与启动校验:配对要求(只传其一或 K 单独传入 → 退出码 2 + recipe,零单元 spawn)、取值域(N/W/K ≥ 1);`--help` 文案含估算口径与诚实边界(与超时不变式违例同形)
- [x] 1.2 `_fill()` 准入判定:维护本 run 派发时间戳滑动窗口,`最近 W 秒派发数 × K + K ≤ N` 才派;不满足时分片 sleep(≤1s)等窗口滑动,在飞照常收割;每段等待 stderr 披露一行(估算口径 + 预计恢复时刻);`--wave` 仍是槽位上限(两重闸门正交)
- [x] 1.3 stdout 摘要与 sidecar 增 `quota{calls,window_s,calls_per_unit,admission_waits}`(单一真相源派生,两侧恒一致;未配置时该键缺席)

## 2. 配额窗口复位冷却

- [x] 2.1 触发冷却的快败 requeue 事件中命中 `RATE_LIMIT_SIGS` 者,冷却终点改为 `max(常规终点, 最近特征事件时刻 + W)`;仍受既有「剩余时间预算 − 在飞收敛余量」封顶,截断如实披露;非限流特征事件与熔断前有界退避的冷却时长不变
- [x] 2.2 确认零推进熔断不受准入等待影响(熔断观察只锚在新派发上),必要时在观察锚处补防御性注释

## 3. 等满窗口才截断

- [x] 3.1 配额模式下截断条件追加「至少一次 rate-limit crash 发生在一次已完整等到的配额窗口复位冷却之后」;截断 recipe 增「核对配额三 flag 与网关实际配额一致」一行;`--no-rate-limit-stop` 禁用面不变
- [x] 3.2 非配额模式截断路径零改动(既有 `rate_limit_stop` 测试全数沿用通过)

## 4. 派发器测试(先红后绿;harness 层显式 `--cooldown-s 0`,配额用小窗口值控墙钟)

- [x] 4.1 红:配额 flag 未配对/非法取值 → 退出码 2 + recipe + 零 spawn
- [x] 4.2 红:准入算术——余量不足暂停新派发、在飞收割照常、窗口滑动后恢复;`quota.admission_waits` 计数
- [x] 4.3 红:配额等待撞软时限 → 退出码 0 + `partial:true` 干净早退(resume 后窗口重起算)
- [x] 4.4 红:限流特征事件冷却等到窗口复位(终点 = 特征时刻 + W);非限流事件冷却仍固定 `--cooldown-s`
- [x] 4.5 红:等满窗口自我恢复不截断 / 等满窗口后仍限流才截断(recipe 含核对行)/ 未配置时第 wave 个全特征 crash 即截断(零变化)
- [x] 4.6 红:不传配额 flag 的 stdout/stderr/sidecar 与改动前逐字节一致(既有字段零增删、无 `quota` 键)
- [x] 4.7 红:准入等待期间零派发不误触零推进熔断

## 5. 切片默认校准与预算粘滞(diff_group.py)

- [x] 5.1 `DEFAULT_MAX_INTERFACE_BYTES` 256KB → 96KB(98304);standalone 维持 64KB;Usage/`--help` 写校准算术(最坏上下文栈折算 + 单元数代价一句话)
- [x] 5.2 resume 预算粘滞:run 目录已有携带预算记录的 `grouping.json` 且未显式传 flag → 复用记录值;显式 flag 优先并更新记录
- [x] 5.3 测试:新默认值锚(`--help` 与实际生效一致)/ 200KB 接口在新默认下重切 `-partN` 每份 ≤96KB / 粘滞两向(未传沿用记录、显式覆盖)/ 显式传 262144 合法;既有预算面测试(`test_diff_group`)全绿

## 6. 单遍往返纪律(分发面)

- [x] 6.1 `core/prompts/fragments/fanout/sdr-task.md` 增单遍纪律段:全部输入第一批并行读入 → 一次判断 → 写 draft + touch marker 同批 → 单行 ack;明示 NEVER 逐文件多轮往返;显式声明读/写路径闭集与刚性三元组不变
- [x] 6.2 三面 `sdr-review-fanout` agent 定义(opencode/claude agent 与 dsh tier agent)增与模板一致的单行指针
- [x] 6.3 测试:模板措辞锚(存在性 + 与刚性三元组共存)+ 三面 agent 定义逐字对账(agent 克隆 parity 测试扩展)

## 7. 三面壳、launcher 与步骤清单外包(design D8 A 案,漂移则降 B)

- [x] 7.1 `list_sdr_steps.py` 各步 invocation/discipline 扩容:fanout 步 invocation 增 `--wave 1` 与配额三 flag 用法示例;group 步带预算默认值口径;步骤级 recipe(快败风暴三层、gate 细则)随 discipline 承载;`--help` 契约面同步
- [x] 7.2 三面 `mgh-sdr` 壳编排流改 init 式骨架:每步先 `py …/list_sdr_steps.py --step <id>` 取确切调用行与纪律再执行(B 降级 = 仅外包本案触碰分节,调用行仍内联);参数表保留「内网建议并发 1~2」与配额 flag 一句话指引;dsh 面 4997/5000 经外包取得真实余量(净零删并仅兜底),三面逐字镜像
- [x] 7.3 `core/scripts/mgh_sdr_launch.py` resume 指引行同步(`--wave 1` + 配额 flag 提示);`diff_group.py`/`fanout_runner.py` 的 `--help` 承载校准算术与配额语义(壳内对应长句迁出后的新家)
- [x] 7.4 测试/ lint:`test_list_sdr_steps`(invocation 含 `--wave 1`/配额示例、discipline 完整性锚——调用行迁出壳后的断言新家)、`test_dsh_command_surface`、`test_mgh_sdr_launch`、budget lint(三面 ≤ 上限且 dsh 显著低于 4997)、purity、`tools/check_contracts.py`(新 flag 对账;壳扫描面缩小后确认无 flag 断言丢失)

## 8. 文档与版本

- [x] 8.1 维护者私有文档区 `/mgh-sdr` 命令人话说明补配额一节(参数、建议值、调用次数算术、单遍纪律、估算式诚实边界);术语词典按需补「配额窗口/准入节流」条目
- [x] 8.2 README `/mgh-sdr` 段与诚实边界补配额模式一句(估算式、未配置零变化);AGENTS.md 用户画像表对应行加配额 flag 指针(一句话)
- [x] 8.3 VERSION bump + CHANGELOG 分组条目

## 9. 验证与收尾

- [x] 9.1 定向回归全绿:`test_fanout_runner` `test_fanout_stale`(既有风暴/冷却/失活套件 = init 真仓验证参数的锁定器,全绿是 D9 隔离论证的硬闸门)`test_diff_group` `test_list_sdr_steps` `test_distributed_md_purity` `test_dsh_command_surface` `test_mgh_sdr_launch` + agent parity 相关 + `test_zero_deps` `test_no_compile_warnings`
- [x] 9.2 lint 四件套:contracts / purity / budget / plain_language(存量噪音零新增)
- [x] 9.3 实机冒烟:假宿主 CLI 模拟限流网关(可控注入 429 尾),隔离小仓全链验证——配额节流按算术暂停/恢复、窗口复位冷却终点、等满窗口不截断、未传 flag 行为照旧;`diff_group` 新默认重切与粘滞各验一例;**壳外包忠实度专测**(A 案:编排器每步先调 `list_sdr_steps --step` 再执行,漂移即降 B 案)
- [x] 9.4 全量回归闸门(fanout_runner 为 init/sdr 共享跨面):`for f in tests/test_*.py` 全绿(既有环境相关存量失败按仓库惯例 stash 对照定性)
