# add-mgh-dsh-subagent-fanout

## Why

> **人话序** 现象:前两个 change 让 dsh 有了守卫执法与命令入口,但流水线跑到扇出步仍会
> 按降级披露停住——`/mgh-init` 的 scout/T1/T3、`/mgh-sdr` 的 6 维度复核、`/mgh-sast` 的各
> stage 子代理,都要求「按名装载一个带工具白名单的隔离子代理,headless 跑完一个单元」。
> dispatcher(`fanout_runner.py`)目前只会 spawn `claude -p` 与 `opencode run` 两种宿主
> 命令行,dsh 不在探测表里;dsh 侧也没有 markdown 子代理加载器。根因:子代理是宿主方言
> 资产的第二个未覆盖面。改什么:① dsh 子代理定义方言(第三份 agent 文本 → install 生成
> tier 级装载配置,叶 SYSTEM 提示词与工具白名单按 spike 定案的两档之一挂载);②
> `fanout_runner.py` 新增 `--host dsh` 派发形(`dsh --profile … --patch <tier> -`,任务走
> stdin);③ dsh 的「前台命令超时晋升后台 job」语义与本项目「超时=杀+重派」纪律的调平;
> ④ 交互式 stage 派发(非脚本扇出,编排器直接点名派子代理)的 dsh 形。怎么验证:真机
> `/mgh-init` scout 小波次 + `/mgh-sdr` 全维度扇出跑通,marker/resume/熔断行为与双端
> 一致;完成后删除上一个 change 留下的扇出降级段。

- **价值**:本 change 完成时,路线 A 收口——dsh 成为与 claude/opencode 对等的第三宿主,
  五条已发布命令端到端可跑(除各自既有的诚实边界外无 dsh 特有缺功能)。
- **为何独立**:它同时动 `fanout_runner.py`(核心调度面)与子代理方言,与命令壳文本面
  (change 2)正交;合进 change 2 会让「纯文本方言」与「调度语义」两类风险混排,首跑排障
  无法归因。
- **依赖**:change 1(shim 装载机制与 profile 接线经验、守卫对扇出子进程生效)与
  change 2(D4 降级段在此删除;壳召唤路径已就绪)。

## What Changes

- **`fanout_runner.py` 新增 dsh host**:`--host` 枚举加 `dsh`;PATH 探测链 = 显式 `--host`
  优先 > 既有探测次序不变、`dsh` 追加在链末(**已有 claude/opencode 机器默认行为零变化**);
  命令形 `dsh --profile <mgh profile> --patch <tier装载文件> -`,任务经 stdin(沿用
  「NEVER argv」教训,dsh 同为 npm `.cmd` shim)、cwd = `repo`;波次/双 reader 静默检测/
  树杀/熔断/cooldown **全部复用不动**(宿主无关);stall 判定用 plain 输出模式(推理走
  stderr、字节流持续)而非 `--json`(事件按步提交,静默窗口会误杀)。
- **子代理定义第三方言** `releases/dsh/agents/`:fan-out 克隆三件
  (scout/induct/rulewriter,对位 opencode `*-fanout`)+ sast 各 stage 子代理;install 由
  生成脚本把每份 agent 文本编译为 tier 级装载文件(patch/preset YAML,含叶 SYSTEM 提示词
  与工具白名单;挂载机制按 spike 在「配置装载 vs 任务前置」两档定案)。
- **交互式 stage 派发形**:mgh profile 组合 dsh 的委派工具,每个 stage 一个具名实例
  (工具名对位 claude 的按名拾取),编排器壳 dsh 方言以该工具名派发;隔离上下文语义不变。
- **Bash 超时语义调平**:tier 配置显式关宿主「超时晋升后台 job」,使长跑叶脚本回到
  「超时=终止」合同;若宿主侧不可关,则 dsh 壳扇出段改用 `job_kill` recipe 方言(二选一,
  spike 定)。
- **install `--dsh` 扩面 + 三面收口**:agents→tier 文件生成入 install;`--kill-stale`、
  liveness 登记、marker/ack 契约零变化;删除 change 2 各 dsh 壳内的扇出降级段;三面
  契约 lint 复跑。
- **非目标**:不改 claude/opencode 派发路径与既有探测优先级;不引入 dsh 原生
  in-process 子代理瀑布替代脚本 dispatcher(违背「派发全程零 LLM 回合」基座设计);
  不做 dsh Web/桌面面的集成。

## Capabilities

### New Capabilities

- `dsh-agent-surface`: dsh 上子代理与 tier 的承载契约——agent 定义方言、tier 装载文件生成
  与挂载两档语义、交互式 stage 具名派发、宿主超时纪律调平。

### Modified Capabilities

- `fanout-dispatch`: 「宿主 CLI 探测与 headless spawn 映射」从双宿主扩为三宿主——探测链
  末位追加 dsh(默认次序不变)、spawn 命令形与 stall 字节活性模式入契约;不可用回退
  recipe 措辞同步三面。

## Impact

- **新增**:`releases/dsh/agents/`、tier 生成脚本(`tools/` 构建期)、`tests/` dsh 派发用例
  (挂既有 fake-dispatch harness,遵守 in-process 测 `--cooldown-s 0` 陷阱规)。
- **修改**:`core/scripts/fanout_runner.py`(host 枚举/探测/命令形,不动调度内核)、
  `install.sh`/`install.ps1`、dsh 壳五份(删降级段 + stage 派发表述)、fan-out 相关契约文档、
  研发手册测试映射与版本号。
- **不受影响**:既有双宿主任何行为、全部产物 schema、marker/resume 磁盘协议、守卫。
- **风险集中面**:`fanout_runner.py` 属真子进程/计时器慢测区——本 change 定向跑
  `test_fanout_runner`/`test_fanout_stale`,全量留发布闸。
