# Contract: fan-out 运行契约(host spawn / tier 装载 / 超时调平)

Producer: 本契约是脚本族 `fanout_runner.py`(dispatcher)与三宿主 headless 派发形的**单一
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
