## MODIFIED Requirements

### Requirement: 宿主 CLI 探测与 headless spawn 映射

dispatcher SHALL 探测可用宿主 CLI(`claude` / `opencode` / `dsh`,PATH 查找)并映射为各自的
headless subagent 调用,agent 名按 tier 参数化:scout → `init-scout-fanout`、t1 →
`init-induct-fanout`、t3 → `init-rulewriter-fanout`(opencode 侧均为 `mode: primary` 的
fanout agent 克隆,install 落位 `.opencode/agent/`;claude 侧经 `--agents` inline JSON 按同名
单元装载,工具面白名单等价于交互路径;dsh 侧经 `dsh --profile <mgh profile> --patch
<tier 装载文件> -` 装载,装载物由 install 从 `releases/dsh/agents/` 编译生成)。自动探测次序
SHALL 保持既有 claude/opencode 相对次序不变、`dsh` 仅追加在链末(已装双端的老机器默认行为
零变化);显式 `--host` 恒优先于探测。spawn 的 dsh 子进程 SHALL 使用 plain 输出模式(推理/
进度持续产生 stderr/stdout 字节流)供双 reader 静默检测消费,**NEVER** 用按步提交事件的机器
可读输出做活性信号(事件稀疏会喂大误杀窗口)。任务消息的正文 SHALL NOT 出现在 argv 里
(npm `.cmd` shim 实测在首个换行处截断多行 argv,对 dsh 同样成立):claude/opencode 经 stdin
管道传递;dsh headless 无 stdin 任务通道(实测),经**进程环境注入**投递——dispatcher 把任务
全文放入子进程 env 的 `MGH_TASK_TEXT`,tier 装载文件的固定模板行以该 env 覆盖任务来源,
argv 仅携带无内容占位符 `-`。子进程 cwd SHALL 为 `repo`(目标项目根);子进程 env SHALL
剥离 `PWD`(全部 host 形一致,dsh 形继续附加 `MGH_TASK_TEXT`)——opencode 按
`PWD ?? cwd` 解析项目归属,继承的 `PWD`(宿主外从其它目录的 shell 拉起 runner 时指向别处)
会使子会话把非 repo 目录认成项目;剥离后归属回落到显式 cwd = `repo`(claude/dsh 不读
`PWD`,剥离无副作用)。任一宿主 CLI 均不可用
→ 退出码 2 fail-loud,stderr 给出 recipe(回退 = 编排器现状波次式手派,行为不变)。spawn 的
子进程 SHALL 继承运行域守卫激活(经磁盘哨兵 `<target>/.mgh-init/.active`,env 不跨进程亦不
失效)。

凭证注入模式(见「子进程执行环境隔离与静态凭证注入(可选激活)」要求的 `--cred-file`)
下,opencode 形子进程 env SHALL 在剥离 `PWD` 的基础上**按单元增设** `XDG_CONFIG_HOME`
(指向该单元子配置目录)与 `XDG_DATA_HOME`(指向该单元独立数据目录)——两变量的取值、
子配置物化与 secret 卫生由该要求承载,命令形/任务通道/cwd 语义本要求不变。`--isolate-data`
单独传入时 opencode 形 SHALL 仅增设 `XDG_DATA_HOME`。注入与隔离均未激活时,子进程 env
构造 SHALL 与本要求既有文本逐字段一致(零新增变量)。

#### Scenario: opencode 可用时走 opencode run
- **WHEN** `opencode` 在 PATH,dispatcher 以 `--tier t1` 派发一个 cluster 单元
- **THEN** 子进程命令形如 `opencode run --agent init-induct-fanout`(消息经 stdin),cwd =
  `repo`;完成后该单元 `.done` marker 出现

#### Scenario: 双 CLI 均缺失 fail-loud
- **WHEN** `claude`、`opencode`、`dsh` 三者在 PATH 全缺失
- **THEN** dispatcher 退出码 2,stderr 说明回退 recipe(编排器按现状波次式手派);无部分 spawn

#### Scenario: 仅装 dsh 的机器可完成扇出
- **WHEN** 机器只有 `dsh` 在 PATH,`--tier scout` 派发
- **THEN** 子进程命令形如 `dsh --profile <mgh> --patch <tiers/scout 装载文件> -`(任务全文
  经子进程 env `MGH_TASK_TEXT` 投递、argv 仅占位符),stall 检测吃其 plain 模式字节流;
  单元按既有 marker/ack 合同收口

#### Scenario: 双端既有次序不受 dsh 加入影响
- **WHEN** 机器同时装有 opencode 与 dsh
- **THEN** 自动探测仍选 opencode(dsh 在链末);`--host dsh` 显式指定才切 dsh

#### Scenario: 宿主外手动运行时子进程项目归属正确

- **WHEN** 维护者从非 repo 目录的 shell(其 `PWD` 指向别处)手动拉起
  `fanout_runner.py --tier t1`,host 探测为 opencode
- **THEN** spawn 的 opencode 子进程 env 不含 `PWD`,项目归属按 cwd = `repo` 解析(NEVER 把
  继承的 `PWD` 目录认成项目);dsh 形子进程 env 同样不含 `PWD` 且仍携带 `MGH_TASK_TEXT`

#### Scenario: 注入模式下子进程 env 按单元增设 XDG 变量
- **WHEN** `--cred-file` 激活、host 为 opencode,dispatcher 派发单元 U
- **THEN** 该单元子进程 env 不含 `PWD`、含 `XDG_CONFIG_HOME=<run>/childcfg/<U>` 与
  `XDG_DATA_HOME=<run>/ocdata/<U>`;命令形仍为 `opencode run --agent <tier-agent>`、任务
  仍经 stdin、cwd 仍为 `repo`

## ADDED Requirements

### Requirement: 子进程执行环境隔离与静态凭证注入(可选激活)

dispatcher SHALL 提供可选的子进程执行环境隔离,激活面为两个 flag(全 tier 通用,机制落在
共享派发循环一处):

- `--cred-file <path>`:静态凭证注入。仅 opencode host 形有效;其它 host 形传入 SHALL
  退出码 2 + recipe(注入仅 opencode 形,**NEVER** 静默退化成无凭证派发)。
- `--isolate-data`:仅数据目录隔离(opencode host 形按单元设 `XDG_DATA_HOME`;其它 host 形
  stderr note 后忽略,属无害冗余而非误用)。

两 flag 均未传入时,派发行为、子进程 env、目录物化 SHALL 与既有行为逐字节一致(缺席零
变化)。两 flag 对全部 tier(scout/t1/t2/t3/sdr)同构适用。

`--cred-file` 激活时,dispatcher SHALL:

1. **启动时一次性读取并校验 cred 文件**(进程内不热更新;续期后重跑 runner 即用新值)。
   schema 为闭集 `{v, baseURL, apikey, provider_id, global_config, keep_plugins,
   expired_signatures[]}`;文件缺失/坏 JSON/缺必填字段/空 apikey → 退出码 2 fail-loud +
   recipe(重跑 `mgh_credentials.py` 取证),零 spawn。文件内 `~` 前缀路径由脚本侧
   expanduser 解析(命令行 NEVER 携带家目录字面路径,规避运行域守卫 Bash 面路径净网)。
2. **按单元物化子配置**:对每个待派发单元 U,写 `<run>/childcfg/<U>/opencode/opencode.json`
   = 全局 opencode 配置(cred 文件 `global_config` 指向)的副本,仅把 `provider_id` 定位的
   provider 覆盖为静态入口(`baseURL` + `apikey` 即 cred 文件值,结构保持 openai-compatible
   形);plugin/agent/model 等其余内容保留(`keep_plugins:false` 时移除 plugin 列表,供插件
   干扰静态入口的场合)。provider id SHALL 保持不变(model id 的 `<provider>/<model>` 前缀
   耦合)。物化幂等:同 run 重派/`--resume` 重物化结果一致;已 `.done` 单元不重派。apikey
   **只能**来自 cred 文件(凭证中心),**NEVER** 从全局配置抄占位值。
3. **spawn env 注入**:`XDG_CONFIG_HOME` 指向该单元 childcfg 根、`XDG_DATA_HOME` 指向
   `<run>/ocdata/<U>`——子进程只见自己的子配置(不自登录)与独立数据目录
   (log/sqlite/repos 随变量隔离,消除并发 fat client 互踩)。
4. **secret 卫生**:apikey SHALL NOT 出现在 stdout/stderr/marker/run.log/报告产物/遥测参数
   的任何位置;披露面仅 cred 文件路径、`provider_id` 与 `baseURL`。子进程凭证落地仅子配置
   文件一处。

#### Scenario: 注入激活后子配置物化与 env 注入
- **WHEN** `--cred-file <run>/cred.json` 传入且 host 为 opencode,派发单元 U
- **THEN** `<run>/childcfg/<U>/opencode/opencode.json` 存在,其 provider `<provider_id>` 为
  `baseURL` + `apikey` 静态入口且 id 不变,plugin/agent/model 与全局配置一致;子进程 env 含
  指向该单元的 `XDG_CONFIG_HOME` 与 `XDG_DATA_HOME`;该子进程不触发登录闭环

#### Scenario: cred 文件损坏 fail-loud
- **WHEN** cred 文件缺 `apikey` 字段或为坏 JSON
- **THEN** dispatcher 退出码 2、零 spawn,stderr recipe 指向重新取证(`mgh_credentials.py`)

#### Scenario: 非 opencode host 拒识
- **WHEN** `--cred-file` 传入且 host 为 claude
- **THEN** dispatcher 退出码 2 + recipe(注入仅 opencode 形;claude 形凭证走 claude 自身机制)

#### Scenario: apikey 不落任何留痕面
- **WHEN** 注入模式完成任意单元的派发与收口
- **THEN** stdout 摘要、stderr、marker、run.log、报告产物中均无 apikey 明文(只可能有
  cred 文件路径、provider_id、baseURL)

#### Scenario: 两 flag 缺席时行为零变化
- **WHEN** 派发不传 `--cred-file` 与 `--isolate-data`
- **THEN** 子进程 env 与既有契约逐字段一致(无任何 XDG 新增变量),无 childcfg/ocdata 物化

#### Scenario: resume 幂等续跑
- **WHEN** 同一 run 目录 `--resume` 重派
- **THEN** 已 `.done` 单元不重派;未完单元的子配置重物化结果一致;cred 文件已续期则新值
  生效

### Requirement: 凭证过期分类与暂停续跑

dispatcher SHALL 在 `--cred-file` 激活时,对**非 ok 终态**(crash/timeout/stall/failed ack)
单元的输出尾部(与 crash 原因分类同源的数据面)做确定性凭证过期特征扫描:特征集 = cred
文件 `expired_signatures[]`(大小写不敏感子串匹配);命中 → 该单元记凭证过期原因,计入
stdout 摘要 `credential_expired:true` 与 `credential_expired_units[]`,与 stall 计数、限流
crash 分类**分开统计**。特征集为空时扫描面不激活,分类行为与无 cred 文件时一致。

**暂停截断**:首个命中后 dispatcher SHALL 立即停止派发剩余单元(优先级高于限流风暴截断
与快败冷却),已派发在飞单元照常收割记账,以退出码 2 收口;stderr 给出配方:按
special-auth 部署文档(在场时)或 `mgh_credentials.py` 重新取证 → 更新 cred 文件 → 同参
`--resume --retry-failed` 续跑。磁盘 marker 语义不变:命中单元的 `.failed`/marker 按既有
合同如实落盘,续跑经 `--retry-failed` 重派,已完成单元零丢失。特征漂移(新网关措辞)→
不命中 → 走既有 stall/冷却兜底——签名层是快停与披露,**NEVER** 唯一防线。

#### Scenario: 过期特征命中即暂停
- **WHEN** cred 文件 `expired_signatures` 含 `"401"`,3 个单元相继 crash 且输出尾部含 401
  特征
- **THEN** dispatcher 停止派发剩余单元,退出码 2;stdout `credential_expired:true` +
  `credential_expired_units` 含 3 个单元 id;stderr 给重新取证与 resume 配方;在飞单元收割
  后正常记账

#### Scenario: 与限流分类分开计数
- **WHEN** 同一 run 内既有尾部含 `429` 的 crash 又有尾部含 `401` 的 crash
- **THEN** `401` 单元只进 `credential_expired_units`,不进限流风暴截断的判定集;限流截断
  (要求窗口内 crash 全部为限流特征)不因混合而触发

#### Scenario: 空特征集零变化
- **WHEN** cred 文件未携带 `expired_signatures`
- **THEN** 无凭证过期扫描,非 ok 终态按既有分类路径收口

#### Scenario: 续期后续跑零丢失
- **WHEN** 凭证续期、cred 文件更新后,同参 `--resume --retry-failed` 重派
- **THEN** 已 `.done` 单元不重跑,命中单元重派且子配置用新 apikey 物化

### Requirement: 派发 `--dry-run` 纯计划(零写盘零 spawn)

dispatcher 的 `--dry-run`(独立传入的派发计划形态)**SHALL** 为纯计划:零子进程 spawn、零
文件写盘——含 `<inputs-dir>/*.task.md` 审计副本、目录创建、marker、liveness 登记、任何
状态文件;计划摘要(单元清单、将写的审计与 marker 路径、派发命令形)只走 stdout。
`--kill-stale` / `--purge-audit` 的 `--dry-run` 前置审视守卫语义不变(破坏性操作的审视
门,与本要求的计划形态互不侵蚀)。

#### Scenario: dry-run 零写盘
- **WHEN** `--dry-run` 对 N 个 pending 单元跑派发计划
- **THEN** 磁盘零新增零修改(审计副本不写、无目录创建),stdout 含 N 个单元的计划与将写
  路径,退出码 0

#### Scenario: 去掉 dry-run 后正常派发
- **WHEN** 同参去掉 `--dry-run` 重跑
- **THEN** 审计副本物化与子进程派发照既有合同进行

#### Scenario: special-auth 部署文档在场的通用提示
- **WHEN** 安装树存在 `<mgh-core>/mgh-special-auth.md` 且派发未传 `--cred-file`
- **THEN** dispatcher 在派发开始前向 stderr 发一行 advisory(该文档在场、凭证准备与
  `--cred-file` 用法见文档);提示不阻塞、不改变退出码与派发行为,对全部 tier 一致

### Requirement: 凭证中心一次性取证(mgh_credentials.py)

fanout 基础设施 SHALL 含一个确定性叶脚本 `mgh_credentials.py`(零运行时依赖,命令无关、
全部 mgh-* 流程共用),职责 = **一次性**取得模型网关凭证并产出统一 secret 载荷,供 dispatcher
静态注入给 N 个子进程共用——子进程 **NEVER** 各自走登录闭环。契约:

- CLI 为扁平 flag 形(与全族脚本一致,无子命令):取证 =
  `py mgh_credentials.py --source <run>/cred_source.json --out <run>/cred.json
  [--login-timeout-s <s>]`;校验 = `py mgh_credentials.py --check <run>/cred.json`。
  `--source` 是参数文件(编排器写入 run 目录;取证模式与全部企业参数——env 变量名、
  环境文件路径、全局 opencode 配置路径、model、provider_id、baseURL、过期特征集——由
  special-auth 部署文档提供取值;命令行与参数文件路径均落 run 目录内,**NEVER** 在命令行
  携带家目录字面路径,规避运行域守卫 Bash 面路径净网)。
  `--out` 产物的 schema 为「子进程执行环境隔离」要求的闭集;写入权限 best-effort 收紧
  (POSIX 0600);`--check` 校验既有文件 schema 完整性(零联网、不验 token 有效性——
  有效性由派发面的凭证过期分类兜底)。
- **校验器单源**:cred 文件闭集 schema 的校验函数由本脚本导出,dispatcher(fanout_runner)
  import 同一个——生产者与消费者 NEVER 各自定义「什么是合法 cred 文件」。
- 取证三模式(参数文件 `mode` 字段,顺序即文档建议的优先级):
  1. `inherit`:读本进程环境变量取 token(宿主会话已完成登录时其 env 已注入,零登录)。
  2. `env-file`:解析 KEY=VALUE 环境文件取变量(桌面侧插件落盘的凭证文件)。
  3. `login-process`:起一次带插件的一次性登录进程取证——物化本地探测插件(泛型模板:
     把指定 env 变量值写入指定输出路径)→ 临时把该插件追加进全局 opencode 配置的 plugin
     列表 → spawn 一次性登录子进程(浏览器侧 CAS 由登录自动化插件或人工完成)→ 捕获
     token → **外科式还原全局配置**(还原前重读当前文件、仅移除自己追加的条目,NEVER
     盲目整文件回写覆盖并发修改)→ 写输出文件。还原 SHALL 在 try/finally 中:取证
     超时/失败同样还原;超时上限可配,超时 → 退出码 2 + recipe(预期浏览器弹窗、检查登录
     自动化插件与回调端口占用)。
- stdout = 结构化摘要(模式、变量名、成败、输出路径;**NEVER** token 值),stderr = 进度与
  诊断;退出码 0/1/2 按确定性叶脚本契约。

#### Scenario: inherit 模式零登录取证
- **WHEN** 宿主会话已完成登录,`mode:"inherit"` 且指定变量存在于本进程 env
- **THEN** 脚本零登录零 spawn,直接写 cred.json;stdout 摘要不含 token 值

#### Scenario: env-file 模式解析凭证文件
- **WHEN** `mode:"env-file"` 且指定文件存在、含指定变量
- **THEN** 脚本解析 KEY=VALUE 取值写 cred.json;文件缺失或无该变量 → 退出码 2 + recipe
  (按文档下一模式取证)

#### Scenario: login-process 失败也还原全局配置
- **WHEN** `mode:"login-process"` 且登录子进程超时未取到 token
- **THEN** 脚本退出码 2 + recipe,且全局 opencode 配置中自己追加的插件条目已被移除
  (重读后外科式移除,其余内容不变)

#### Scenario: --check 只验 schema 不联网
- **WHEN** 对既有 cred.json 跑 `--check`
- **THEN** 校验闭集 schema 完整性与非空 apikey;不发起任何网络请求,不判定 token 是否
  仍有效
