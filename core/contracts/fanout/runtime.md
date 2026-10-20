# Contract: fan-out 运行契约(host spawn / tier 装载 / 超时调平)

Producer: 本契约是脚本族 `fanout_runner.py`(dispatcher)、`emit_native_plan.py` +
`env_profile.py`(原生派发计划面,见下「native plan」节)与三宿主 headless 派发形的**单一
登记处**;装载资产由 install 生成(见下「tier 装载文件」),消费方 = dispatcher、三面命令壳
的扇出段、回归测(`tests/test_fanout_runner.py` 命令形快照)。任何宿主派发形的改动 MUST
同步本契约 + 对应快照测,NEVER 只改代码不改本文件。

## 宿主 spawn 形(每单元一次 headless 子进程,任务模板逐字构造、派发零 LLM 回合)

| host | 命令形 | 任务正文通道 | 活性信号 |
| --- | --- | --- | --- |
| opencode | `opencode run --agent <tier-agent>` | stdin 管道 | 默认输出逐 token |
| claude | `claude -p --agents <inline JSON> --allowedTools <白名单>` | stdin 管道 | `-p` 输出逐 token |
| dsh | `dsh --profile mgh --patch <mgh-core>/dsh/tiers/<tier>.yml -` | **子进程 env `MGH_TASK_TEXT`**(argv 仅无内容占位符 `-`) | plain 模式:reasoning 增量逐 chunk 写 stderr、终稿写 stdout |

- 自动探测次序 = `opencode` > `claude` > `dsh`(仅追加链末;已装双端的机器默认行为零变化);
  显式 `--host` 恒优先。三者 PATH 全缺 → 退出码 2 + 回退 recipe(编排器波次式手派)。
- 子进程 cwd = `repo`(目标项目根);任务模板里的 `{{mgh_core}}` 占位符由 dispatcher 按
  自身安装位置填充(`Path(__file__)` 上两级,三端分别是 `.claude/mgh-core`、
  `.opencode/mgh-core`、根级 `mgh-core/`),让所有宿主单元自读同一份
  `…/prompts/stages/*.md`——模板只有一条路径,无宿主前缀猜测。
- **dsh 无 stdin 任务通道(实测)**:headless 只认 argv 位置参数且非空必需;多行 argv 经
  npm `.cmd` shim 在首个换行处截断(实测复现)。故正文走 env:`--patch` 装载文件的固定
  模板行 `task: !!js process.env.MGH_TASK_TEXT` 覆盖任务来源(装载层优先于 argv 注入,
  实测),argv 的 `-` 仅为占位。任务全文 ≤190KB 多行含特殊字符实测字节级保真。
- stall/树杀/波次/熔断/cooldown 与宿主无关、全复用:`taskkill /pid <pid> /T /F` 对
  `cmd.exe → node → sandbox-runner → powershell` 全链有效(实测无孤儿);
  `--kill-stale` 的 cmdline 标记集含 `opencode`/`claude`/`dsh`。
- 并发 session:dsh 每 run 自生成 `session-<uuid>`、每 session 目录独立锁,多进程并发
  零互踩(实测);`--session-id` 是接管既有会话的 debug 通道,NEVER 进产品派发形。

## 子进程执行环境注入(可选;两 flag 全缺席 = 与上表逐字节一致)

| flag | host 域 | 子进程 env 增设 | 磁盘物化(plan 工件同级的 run/init 目录下) |
| --- | --- | --- | --- |
| `--cred-file <run>/cred.json` | 仅 opencode 形(claude/dsh 退出码 2 拒识,NEVER 静默退化;in-process 测试钩子 `test` 形允许物化验证) | `XDG_CONFIG_HOME=<…>/childcfg/<unit>` + `XDG_DATA_HOME=<…>/ocdata/<unit>`(按单元) | `<…>/childcfg/<unit>/opencode/opencode.json` = 全局配置副本,仅 `provider_id` 定位的 provider 覆盖为静态 `options.baseURL`+`options.apiKey`(**provider id 不变**——model id 前缀耦合;`keep_plugins:false` 时摘 plugin 列表);幂等,重派/续期重物化结果一致 |
| `--isolate-data` | opencode 形(其它形 stderr note 后忽略) | 仅 `XDG_DATA_HOME=<…>/ocdata/<unit>` | `<…>/ocdata/<unit>/`(log/sqlite/repos 随变量隔离,消除并发 fat client 互踩) |

- cred 文件 schema 闭集 `{v, baseURL, apikey, provider_id, global_config, keep_plugins,
  expired_signatures[]}`,校验器单源在 `mgh_credentials.py`(生产者与 dispatcher import
  同一个);缺文件/坏 JSON/缺字段/空 apikey → 启动期退出码 2,零 spawn 零枚举副作用。
  apikey 只落子配置文件一处,NEVER 出现在 stdout/stderr/marker/run.log/遥测。
- env 注入经 `_UNIT_ENV` 注册表(派发线程登记、`_run_unit` 认领,其 9 参签名冻结);
  物化失败 = 该单元 pre-spawn 失败(`.failed` marker,reason `cred-materialize: …`)。
- **凭证过期快停**:非 ok 终态(crash/timeout/stall/failed ack)输出尾部按
  `expired_signatures[]`(大小写不敏感子串)扫描;首个命中 → 停止新派发(优先级高于
  限流风暴截断与快败冷却),在飞照常收割,退出码 2;stdout `credential_expired` +
  `credential_expired_units[]`;stderr recipe = 重取证 → 更新 cred 文件 → 同参
  `--resume --retry-failed`。marker 语义不变(命中单元按既有合同落盘);空特征集 =
  扫描面不激活;签名漂移 → 退化到既有 stall/冷却兜底(签名层 NEVER 唯一防线)。
- **special-auth advisory**:安装树存在 `<mgh-core>/mgh-special-auth.md`(维护者随包
  分发,NEVER 提交 git;install 做「源在场才落盘」收敛复制)且未传 `--cred-file` →
  派发前 stderr 一行提示(不阻塞、不改退出码,全 tier 一致)。
- **`--dry-run` 纯计划**:零写盘零 spawn(审计副本/liveness/sidecar/marker/子配置全
  跳过),单元清单 + 将写路径 + 命令形 + pre-spawn 锚检查预判只走 stdout,退出码 0;
  `--kill-stale`/`--purge-audit` 的 dry-run 审视守卫是独立语义,不变。

## native plan(原生派发的确定性计划工件)

Producer: `emit_native_plan.py`(计划物化)+ `env_profile.py`(项目环境画像读取);消费方
= 后续接入原生派发的命令壳/步骤清单(编排会话直接派同宿主 subagent,零 headless 子进程)。
**首个消费方 = `/mgh-sdr`(opencode 面,环境画像显式 `dispatch_mode:"native"` 时)**:
波次循环、标记写者、看门狗接线与报告披露的编排契约见
[`sdr/pipeline.md`](../sdr/pipeline.md)「原生派发形态」节;子进程派发器形态
(`fanout_runner.py --tier sdr`)是缺省与永久回退——画像缺失/auto/runner 一律回退形态,
行为逐字节不变,两形态的单元输入构造同源零漂移。
两脚本与子进程派发器的关系 = **旁路供给面**:`emit_native_plan.py` 以兄弟导入复用派发器
的 tier 表、枚举器调用与 run 目录锚定、模板加载与逐字填充、锚树校验、安全文件名(**派发器
源码零改动、其行为零变化**),使原生形态与子进程形态的单元输入构造零漂移。

### 工件布局

| 工件 | 内容 |
| --- | --- |
| `<run>/native_plan.json` | 计划本体 `{v, tier, agent, repo, wave_size, wave_size_source, units_total, waves[]}`;每波 `{wave, units[]}`,每单元 = 枚举器 pending 字段**逐字透传** + `{id, unit_id, task_file}`,路径全绝对。`<run>` = 计划工件的锚定目录(与派发器 sidecar 同锚:sdr = grouping.json 所在 run 目录,t2/scout-merge = init 目录,其余 tier = 计划工件父目录) |
| `<inputs-dir>/<unit>.task.md` | 每单元完整任务消息,模板逐字填充(填后断言无残留 `{{`),与派发器执行时写的审计副本**同路径同内容**——派发器后跑 = 幂等重写同内容 |

- **确定性**:内容无时间戳、单元按规范 id 稳定排序、序列化固定(`ensure_ascii=False,
  indent=2, sort_keys` + 换行结尾)——同输入两次物化**逐字节一致**(计划 = 磁盘状态与
  flag 的纯函数,是 `--check`「重物化即修复」的前提)。
- **波次尺寸** = `min(并发, max(1, quota.calls // quota.calls_per_unit))`;并发 =
  `--wave-size` > 环境画像 `native_concurrency`(缺省 3);配额只来自环境画像;
  `wave_size_source` 记录取小者来源(`concurrency|quota`,平局记 concurrency)。**静态
  算术**:运行期准入(配额滑窗/冷却/风暴截断)仍属派发器与看门狗层,计划只定形状。
- stdout 摘要(单行 JSON):tool/tier/agent/units_total/waves/wave_size/
  wave_size_source/plan_path/inputs_dir。

### 短号规则(防错抄)

- 形如 `<tier>-<4 字符>`(如 `sdr-k3f7`):sha1(规范单元 id)基 32 小写、剔除易混字符
  (`0/1/i/l/o`)取 4 字符。
- **防错抄不变量**:同一次产出的计划内任意两短号编辑距离 ≥2(单字符错抄不命中另一合法
  号);冲突按 `sha1(unit_id + ":" + salt)`(salt = 1,2,…)确定性重派生,同输入同结果。
- **稳定**:短号派生自规范 id 而非序号——pending 集缩小(断点续跑、部分完成)后存活单元
  短号不变。诚实边界:经加盐解冲突的单元,短号依赖当次全集的冲突解(同集确定性、跨集理论
  可漂);消费方引用走计划内三方映射,`--check` 按当次磁盘状态重派生校验。
- 短号**只作模型转述与人对账**,NEVER 参与文件系统路径构造(路径永远来自枚举器透传);
  计划保存「短号 ↔ 规范 id ↔ 任务文件/产物/标记绝对路径」三方映射。

### 环境画像(`<项目>/.mgh/env-profile.json`)

schema(全键可选、未知字段忽略;quota 在场时三键齐全):

```
{"v":1, "dispatch_mode":"auto|runner|native",
 "native_concurrency":<int 1..5>,
 "quota":{"calls":<int>0>, "window_s":<int>0>, "calls_per_unit":<int>0>}}
```

- **缺文件 = 现状缺省**(`auto` → 解析为现状派发形态;缺省并发 3、无配额)——画像落地后
  任何既有命令的行为零变化。`auto` 的缺省解析**钉死为「现状派发形态」**;任何细化(如按
  认证形态切 native)须另立变更,NEVER 实现层暗改。
- **fail-closed**:坏 JSON/非对象/未知或非整数 `v`/枚举域外取值/并发越界(含非整数与
  布尔)/quota 残缺或非正 → CLI 退出码 2 + recipe(文件路径 + 违规字段),导入形态抛
  `EnvProfileError`(ValueError 子类);NEVER 静默回退缺省(静默回退会让「以为配了
  native 实际跑 runner」的错配不可见)。
- `env_profile.py --check` 零副作用校验并报告实际解析结果(缺文件 = 合法缺省态,exit 0)。

### `emit_native_plan.py --check`(零修复校验,失败退出码 2 + 差异清单 + recipe)

①内存重物化与磁盘 `native_plan.json` 及全部 task 文件**逐字节比对**;②计划单元集与枚举
器当前 pending 一致(已完成单元使计划过时 → 如实报 stale,NEVER 当有效计划通过);③全部
路径绝对且过锚树检查(锚树违规在重物化阶段即以退出码 2 + reason 拒绝);④模板无残留占位
符;⑤短号映射闭合且两两编辑距离 ≥2。零自动修复——重跑同参物化即修复;派发器遗留的旧
`*.task.md` 审计副本(已完成单元)**不算**违规(派发器从不删除它们)。

### 零副作用声明

物化与 `--check` 全程:不 spawn 任何模型宿主进程、不读写凭证、不建子进程隔离目录
(childcfg/ocdata)、不写/touch 任何完成或失败标记、不写 sidecar/liveness——唯一子进程 =
tier 枚举器(pending 的确定性来源,既有幂等契约)。「派发器行为零变化」由其源码零改动
构造保证。

## native watchdog(原生派发运行树的进程外安全网)

`native_watchdog.py`(零依赖叶脚本,`--help` 即契约):独立于编排会话的常驻
观察者,经本机宿主服务的 HTTP 面观测「根会话 + 全部后代」,对卡住形态确定性处置。启动形态
(谁在何时拉起、参数怎么接线)属编排纪律,不在本节。

### 服务发现与回环限定

- 发现依序:`--service-json <path>` > `[XDG_STATE_HOME 或 ~/.local/state]/opencode/
  service.json`(内容 `{url, password, …}`,HTTP Basic,固定用户名);鉴权失败或连接丢失
  → 重读注册文件再试一次(服务重启会换密码),仍失败计入不可达。密码只存内存,NEVER 进
  events/state/stdout/stderr。
- **回环限定**:注册文件 url 主机 ∉ {127.0.0.1, localhost, ::1} → 退出码 2 + recipe,
  不发起任何连接(工具携带本机凭证,NEVER 可被指向上非本机服务);HTTP 重定向一律拒绝
  (3xx 不得携带凭证离机)。

### 作用域与树外零触碰

- 根会话 id = `--root` > `OPENCODE_SESSION_ID` 环境变量;后代按父 id 递归枚举(BFS,
  分页跟随 cursor,规模上限 500)。
- **每次动作前重走目标祖先链**(对服务实时 GET,NEVER 信任枚举快照),不收敛到根 → 放弃
  动作 + `abandoned_out_of_tree` 事件;树外会话只被列表枚举(只读)涉及,NEVER 成为处置
  目标。根不存在 → 退出码 2 + recipe,不进入空巡检;中途从树上消失的会话,其中止/未收口
  状态随之清除。

### 巡检判定(阈值 = 收敛上界,非健康诊断)

每 `--poll-s` 周期(缺省 15)对树内每会话采集:活跃态(`/api/session/active`)、等待授权、
等待表单、最近持久进展(会话 `time.updated` 与最新消息时间的最大值;工具边界由宿主折叠进
updated;字段缺失 = 无该项,NEVER 猜)。授权与表单请求自身无时间戳 → 看门狗维护「首见」
时刻。判定阈值(全可配,缺省如下):

| 形态 | 判定 | 缺省 |
| --- | --- | --- |
| 等待授权 | 首见起超 `--ask-grace-s` | 90 秒(0 = 首见即拒,纯无人值守) |
| 等待表单/问询 | 首见起超 `--form-grace-s` | 90 秒 |
| 后代静默 | 活跃中且无持久进展超 `--silence-s` | 1200 秒(> 宿主响应头+流超时+重试余量) |
| 后代超总时长 | 创建起超 `--unit-deadline-s` | 3600 秒 |
| 中止未落定 | 中止后仍活跃超 `--interrupt-settle-s` | 45 秒 |

终态会话(outcome succeeded/failed/interrupted)NEVER 是中止候选。根会话适用授权/表单
宽限,但静默/超时默认只记录(见动作阶梯)。落定 = 树内无任何会话「活跃或有等待项」,
持续一个确认周期(连续两周期)。

### 动作阶梯(全受 `--dry-run` 约束:dry-run 只报告拟动作,零写请求)

1. 等待授权超宽限 → 回复 `decision=reject + message`(一句「无人值守,继续完成本回合」
   提示);**NEVER 回复批准**(源码级锚:唯一 decision 字面量为 reject);
2. 等待表单超宽限 → 取消(DELETE)并附提示;
3. 后代静默或超总时长 → 中止该会话(`interrupt?resume=false`;该端点响应**不带** `{"data":…}`
   信封、直接返回 `{interrupted,…}`——2.1.0 实机钉扎,其余端点均带信封;宿主作用域机制连带
   收口其挂起工具与 shell,本工具**不**直接管理 shell API);单元因无标记自然回待办重派;
4. 复核窗后仍活跃 → 再中止一次;仍活跃 → 记「未收口」(unresolved),NEVER 无限重试;
   写请求落空(目标已在两动作间消失)= 他人已解决,记 skip 事件、NEVER 计入动作数;
5. 根静默/超时 → 默认仅记录(`root_stall` 事件);`--interrupt-root` 显式开启才可中止根
   (中止根连带取消整波在飞子代理,最后手段)。

动作与事件种类(闭集):`pending_seen` / `action_reject_permission` /
`action_cancel_form` / `action_abort` / `unresolved` / `settled_after_abort` /
`abandoned_out_of_tree` / `action_skipped_gone` / `root_stall` / `cycle_unreachable` /
`exit`。

### 工件与退出

- `--run-dir <dir>` 时:`<dir>/watchdog/events.jsonl` 逐事件追加 + `<dir>/watchdog/
  state.json` 原子写(tmp+rename,每周期至多一次,末次含退出结论);缺 `--run-dir` 零
  落盘仅摘要;工件目录不可写 = stderr 告警 + 继续执法(审计降级,不停摆)。
- stdout 恰好一行 JSON 摘要(模式/周期数/树内会话数/各类动作计数/未收口清单/dry-run
  标记/退出原因);stderr 心跳与 recipe;严格分流。
- 退出码:0 = 单扫完成 / 树落定 / `--deadline-s` 预算耗尽且无未收口;2 = 需要人(存在
  未收口挂死、服务持续不可达(常驻连续 3 周期)、根缺失、注册文件缺失或非回环);1 = 误用
  (缺根、非法阈值)。`--once` 单扫即退;常驻自退 = 落定或预算到点,NEVER 孤儿常驻。

### 非目标

零单元标记写入(`.done`/`.failed` 的唯一写者是单元执行纪律);NEVER 自动重启宿主服务
(共享服务,重启是人的决定,只记录建议);不直接管理 shell API(会话中止已连带收口);
不做限流/配额判定(决策留在计划器与编排纪律);不消费事件流(SSE 易失,轮询+持久时间戳
已够判定);不接入命令壳(接入是后续 change)。

### 版本矩阵

| 宿主版本 | 状态 |
| --- | --- |
| opencode 2.1.0 | 实机验证(API 面经本机服务探测 + 源码 openapi 钉扎) |
| opencode 2.0.32 | 待探测(`--once --dry-run` 只读面;差异回填本表) |

## tier 装载文件(dsh 专属,a 档 = 配置装载)

`<mgh-core>/dsh/tiers/<tier>.yml`(tier ∈ scout|scout-merge|t1|t2|t3|sdr)由 `install.sh --dsh` 从
`releases/dsh/agents/<tier>.md` 编译生成(构建期生成器,幂等重写;缺件 install 期
fail-loud)。dispatcher 派发前断言装载文件存在,缺件 → 退出码 2 + recipe、零 spawn。
每份内容(全固定模板,仅 persona/禁用集随 tier 不同):

| 段 | 作用 |
| --- | --- |
| `headless-runner config.task = !!js process.env.MGH_TASK_TEXT` | env 任务通道(见上) |
| `system-prompt config.personaPrefix = <agent 定义正文>` | 叶行为提示词装载(行为可证:子代理回述装载内容) |
| `tool-bash` / `tool-pwsh` `enableRunInBackground: false` | 显式后台 job 通道关闭 |
| 非白名单工具插件行 `disabled: true` | 工具面收窄(见下粒度边界) |

- **白名单粒度 = 整插件(dsh 端粗粒度,实测边界)**:顶层无 per-tool allow/deny 配置面;
  `read`/`write`/`edit` 同插件 `tool-fs` 不可拆。残余违例面(越树写、`py -c` 内省、
  `run_code`、`job_*` 等)由运行域守卫三面执法兜底(守卫激活经磁盘哨兵,子进程继承)。
- **超时合同**:dsh shell 工具超时即终止(无自动晋升后台 job);与 claude/opencode 的
  「超时=杀+重派」一致,派发壳层无需 job_kill 方言段。

## 交互式 stage 具名委派实例(dsh)

非扇出 stage 派发经 mgh profile 组合的具名委派工具(`dsh-tool-subagent` insert 行,
`toolName` = stage 实例名、`persona` 装载、`toolFilter` 收窄);壳文本按名逐字拾取,
NEVER 泛型 subagent 顶替。具名实例清单与 `releases/dsh/agents/` 同源生成。

## mgh profile(运行载体)

`$DSH_HOME/profiles/mgh`:install 只建/只改这一个 profile(package.json 声明
base+headless bundle + `cordis.patch.yml` 受管块),用户自有 profile 零触碰。受管块内容 =
守卫 shim 挂载(绝对 `.ts` 路径)∪ shell 超时策略行(`enableRunInBackground: false`)∪
具名委派实例行。`--profile mgh` 缺失时 dispatcher
fail-loud 并给出创建 recipe(install `--dsh` 重跑)。

## 诚实边界(dsh 端前置条件)

- dsh headless 需用户自配模型 provider:`install.sh --dsh` 自检只证 CLI 与 profile 在场,
  **不证**可跑通端到端;provider 未配时首个派发单元以宿主报错终止(单元无 ack → 保持
  pending,`--resume` 语义不变)。
- 装载键名/事件形状随 dsh 版本漂移:本契约与生成器按装机版 **0.1.5-rc.2** 实测钉死;
  升级 dsh 后先跑定向回归再放量。
- 白名单粗粒度差异(见上)是宿主能力边界,非实现缺口。
