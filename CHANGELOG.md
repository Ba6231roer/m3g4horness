# Changelog

All notable changes to **m3g4h⊿rness** are recorded here.
Format based on [Keep a Changelog](https://keepachangelog.com/), versioning follows
[Semantic Versioning](https://semver.org/).

`m3g4h⊿rness` (SAST tool: `/mgh-sast`) is a zero-runtime-dependency reimplementation of the
[vvaharness](https://github.com/visa/vvaharness) (Visa / Project Glasswing) 9-stage
agentic SAST pipeline. Prompt **content** is ported under Apache-2.0 (see
`core/docs/NOTICE`); no `vvaharness` code is imported or bundled.

The `0.x` line denotes initial development: structurally complete, but live
end-to-end verification is still pending (see *Pending* below).

---

## [Unreleased]

### Added — opencode 权限询问闸门:无人值守运行零挂起(ask/question 询问在产生前确定性关闭)(0.1.83)

`add-mgh-native-permission-gate`(openspec 变更,规格增量 `runtime-hook-enforcement`
1 ADDED + 1 MODIFIED)。opencode 2.x 的权限询问(`ask`)无超时,无应答者(TUI 无人值守、
纯服务形会话)时工具纤程永久挂起——无人值守长跑的结构性挂死面;工具族守卫此前只管
「工具调用该不该放行」,不管「该不该问」。

- **权限闸门**(releases/opencode/plugins/block_adhoc_scripts.ts,同一插件同一 `setup`
  增注册第二钩子 `await ctx.permission.hook("evaluate", cb)`,防首调用竞态契约与工具面
  一致):运行域内(六运行根 `.mgh-init`/`security-scan`/`.mgh-sra`/`.mgh-srr`/
  `.mgh-ut-init`/`.mgh-sdr` 直查 `<项目根>/<运行根>/.active`,**不向上走链**——祖先目录
  哨兵属别的项目,越权改写)三条固定改写:①`ask` → `deny` + 替代提示,唯一例外
  `external_directory` 且**全部**资源落在哨兵 `read_roots[]`(用户事先批准的只读外部根)
  → `allow`(部分在外一律 deny,NEVER 保留 ask);②`question` 非 deny → `deny` + 批量
  澄清/断点续跑提示;③allow/域外一律不动。哨兵 JSON 损坏按域激活 + 空 read_roots 处理
  (fail-closed 于询问);钩子内任何异常按域外原样返回 + best-effort 诊断(fail-open 于
  宿主)。此为「判定单一来源在 Python」的**显式声明例外**(固定两条半规则、无正则、无
  路径策略推理,CI 形状锚覆盖),工具调用拦截判定仍单一住在 Python 守卫。
- **agent 定义兜底层**(releases/opencode/agent/*.md 全 32 个):全量补 `question: deny`
  (2.x 默认 Build agent 显式 question allow;实机验证 pin 生效形态为工具对 agent 工具集
  直接不可见);5 个非 fanout 孪生兄弟(init-induct/rulewriter/scout/scout-merge/synthesis)
  补漏 `external_directory: deny`(以既有孪生为准)。规则级 deny 短路在钩子前,插件缺席
  时该层独立兜底。
- **测试与契约**:`tests/test_opencode_hook_parity.py` 新增 `TestPermissionGateShape`
  (evaluate 注册被 await/三分支标记/六运行根常量/直查无走链/fail-closed/归一化纯函数
  Python 镜像往返样例:反斜杠/正斜杠/大小写/尾 `/*` 通缀/边界不误配)+
  `TestAgentQuestionDenyPinned`(32 agent 全量 question pin + 11 agent external_directory
  pin,删任一即红;变异证明四组全红);`assert_shim_v2_shape` 扩展双钩子注册均被 await
  (安装副本检查共享);`core/contracts/hooks/runtime-enforcement.md` 增权限闸门节(改写
  规则表/窄激活声明/fail-closed·fail-open 双向/兜底层/四类残余披露/版本矩阵)。
- **实机闸门**(2.1.0,scratch `C:\DEV\_mgh_oc2_gate` 热重载加载零拒载):声明根读放行、
  `.env` 读与 `question` 调用被闸门改写(提示逐字可见、pending 恒为零、会话正常收尾)、
  损坏哨兵 fail-closed、拆哨兵后宿主询问机制原样接管、普通项目零介入;新事实回填:
  2.1.0 默认 agent `external_directory` 为 allow(经 `*` 兜底),ask 面现实入口 =
  显式 ask 配置/`.env` 内置 ask/`question` 工具。企业 2.0.32 闸门待内网执行(复现清单
  随 change 实机笔记)。
- **诚实边界(残余挂死面,本 change 只披露)**:Form/MCP elicitation(另一套问询机制)、
  provider-executed 工具(不过本地权限层)、不做权限断言的自定义工具、宿主拒载插件的
  fail-soft —— 由后续看门狗 change 兜底;根 AGENTS.md 诚实边界同步。

### Fixed — opencode 守卫插件迁移 2.x 模块契约:拒载断代修复 + 锚点显式注入 + 两代工具 id 收敛 (0.1.82)

`fix-mgh-opencode2-plugin-compat`(openspec 变更,规格增量 `runtime-hook-enforcement`
1 ADDED + 5 MODIFIED)。opencode 2.x 把插件模块契约改为「default 导出 `{id, setup}`」,
mgh 原守卫插件是 1.x 具名导出,实测被 2.x 拒载且**拒载只是日志一行 WARN、会话照常**——
升级当天起 opencode 面整条运行域防线(越树读写拦截/微脚本阻断/叶脚本只读)静默消失。
同时 2.x 把插件搬进常驻服务进程(进程 cwd 与项目无关,哨兵锚点链断裂),并把 `bash`
工具更名为 `shell`。

- **插件壳迁移**(releases/opencode/plugins/block_adhoc_scripts.ts,判定逻辑零改动,
  仍全部在 Python 守卫):default 导出 `{ id: "block-adhoc-scripts", async setup(ctx) }`,
  钩子经 `await ctx.tool.hook("execute.before", cb)` 注册(setup 内 await 完成防首调用
  竞态);回调改读单事件对象(`event.tool`/`event.input`);1.x 双参形态移除。不做双形状
  文件(1.x 面企业已无部署,装错版本的静默面会翻倍;1.x 用户保留旧版随包文件,升级后
  重装即换新)。
- **锚点显式注入**:`setup` 捕获 `ctx.location.directory`(会话项目根)逐调用写入
  payload `cwd` 字段;守卫侧「payload cwd > 守卫进程 cwd」优先级链既有,Python 零改动。
  服务进程 cwd 在哪都不再影响哨兵发现与 `..` 相对 token 判定(迁移前从别处启动宿主 =
  守卫整 run 休眠)。
- **两代工具 id 收敛**:`shell`(2.x)与 `bash`(1.x)同映射 Bash 面;`patch`(2.x)与
  `apply_patch`(1.x)同走 `patchText` 标记提取(源码钉扎:同参数名同标记语法,同一
  解析器)。同一份安装文件被 2.0.x/2.1.x 任一版本加载都全量受管;「升级断代/回退断代」
  两种静默漏收由 CI 强制。
- **诊断通道降级**:1.x 的 app-log 诊断通道 2.x 不存在,非阻断诊断改 `console.warn`
  best-effort;阻断契约(守卫退出码 2 → reject 回调、stderr 作 recipe 面向模型)逐字不变,
  fail-soft(守卫缺席 → 放行)不变。
- **CI 静态形状断言**:`test_opencode_hook_parity` 新增 2.x 形状组(default 导出 + await
  注册 + 锚点捕获/注入 + 单事件取参在场;1.x 具名导出/双参回调/旧诊断通道缺席),安装
  副本同源断言(防「装了旧形状文件被静默拒载」复发);守卫新增 payload cwd 锚点场景
  (项目根锚激活 + 判定同源)。
- **agent frontmatter**:2.x 自动迁移 `bash→shell` 等权限键,`permission:` map 原样保留
  (惰性键 `doom_loop`/`list` 不动);实机抽查两个 fanout agent:shell 可用、edit 拒
  (工具面直接收走)、越权写被守卫二次拦截。
- **实机闸门**(记录在本 change 目录实机笔记):本机 2.1.0 全样例过(加载无拒载/越树
  write·edit 拦/shell 内省拦/叶脚本写拦/`..` token 拦/越树读拦/sanctioned 放行);2.x
  `patch` 工具未暴露给默认模型工具集(映射由源码 + CI + 单测承担,边界已披露);企业
  2.0.32 闸门复现清单就绪,归档前须内网执行并回执。
- 契约同步:`core/contracts/hooks/runtime-enforcement.md` 新增「opencode 2.x plugin
  module contract」节(模块契约/事件形状/锚点注入/诊断降级/双代工具表/版本矩阵
  2.0.32+2.1.0);README 已知边界补 opencode 1.x 断代说明。

### Fixed — SDR fan-out 凭证注入与执行环境隔离:CAS 网关下子进程零登录 + 共享目录去互踩 (0.1.81)

`fix-mgh-sdr-fanout-auth-isolation`(openspec 变更,规格增量 `fanout-dispatch` 4 处
requirement〔3 ADDED + 1 MODIFIED〕+ `security-design-review` 1 处 ADDED)。依据企业内网
Linux 真仓实测:fan-out 的 N 个 opencode 子进程各自走 CAS 登录闭环(票据单次有效 +
127.0.0.1 回调端口互抢)→ 除波次最前一个外全部 300 秒零输出转 stall,6 个复核单元仅
1 个 standalone 存活;Windows 补充实测暴露全部子进程共享 `~/.local/share/opencode`
(sqlite/log/repos)的并发互踩(`database is locked`/`EPERM` 随机崩溃,重试吃满槽位)。
根因都在「让每个子进程自理凭证与状态」,调参不可修(降 wave 5→2 无改善已实测)。

- **静态凭证注入(可选,默认关)**:`fanout_runner.py` 新增 `--cred-file <run>/cred.json`
  (仅 opencode host 形;claude/dsh 退出码 2 拒识 NEVER 静默退化;in-process 测试钩子
  允许物化验证)。激活后按单元物化子配置 `<run>/childcfg/<unit>/opencode/opencode.json`
  (全局配置副本,仅 cred 指定 provider 覆盖为静态 baseURL+apiKey,**provider id 不变**
  ——model id 前缀耦合;`keep_plugins:false` 时摘 plugin 列表),spawn env 按单元增设
  `XDG_CONFIG_HOME` + `XDG_DATA_HOME`——子进程只见自己的子配置(不自登录)与独立数据
  目录(log/sqlite/repos 随变量隔离,消除互踩)。cred 文件闭集 schema 校验器单源在
  `mgh_credentials.py`(生产者与 dispatcher import 同一个);缺文件/坏 JSON/缺字段 →
  启动期退出码 2 零 spawn 零枚举副作用;物化失败 = 该单元 pre-spawn 失败(`.failed`
  marker);幂等,续期后重物化新值生效。apikey 只落子配置文件一处,NEVER 进
  stdout/stderr/marker/run.log/遥测。`--isolate-data` 单独开关(无凭证场景单治数据库锁;
  其它 host note 后忽略)。两 flag 全缺席 = 派发行为/env 逐字节不变(既有 203 测全绿)。
- **凭证中心一次性取证**:新增 `core/scripts/mgh_credentials.py`(命令无关,全部 mgh-*
  流程共用):三模式 inherit(读本进程 env,宿主会话已登录则零登录)→ env-file(KEY=VALUE
  凭证文件)→ login-process(物化泛型探测插件 → 外科式追加进全局 opencode 配置 plugin
  列表 → 起一次 `opencode run --print-logs` 登录子进程〔预期浏览器弹窗〕→ 捕获 token →
  try/finally **外科式还原**全局配置〔重读盘仅摘自己条目,并发修改幸存;失败/超时同样
  还原〕→ 写 cred.json 权限收紧 0600)。企业参数(变量名/路径/provider/baseURL/过期
  特征)全部住参数文件 `cred_source.json`(special-auth 部署文档提供取值;`~` 路径脚本内
  expanduser,命令行 NEVER 携家目录字面路径——运行域守卫 Bash 面路径净网相容);
  stdout 摘要 NEVER 含 token;`--check` 只验 schema 零联网。
- **凭证过期独立分类与暂停续跑**:`--cred-file` 激活时,非 ok 终态输出尾部按 cred 文件
  `expired_signatures[]`(大小写不敏感子串)扫描;首个命中 → 停止新派发(优先级高于限流
  风暴截断与快败冷却),在飞照常收割,退出码 2:stdout `credential_expired` +
  `credential_expired_units[]`,stderr recipe = 重取证 → 更新 cred 文件 → 同参
  `--resume --retry-failed`(已完成单元零丢失)。与 stall/限流分开统计;marker 语义不变;
  空特征集 = 扫描不激活;签名漂移优雅退化到既有兜底(签名层 NEVER 唯一防线)。
- **`--dry-run` 纯计划**:派发形态改为零写盘零 spawn 短路(不再写 `<inputs-dir>/*.task.md`
  审计副本/liveness/sidecar;此前审计副本写入是使用者误以为「零副作用」的实底),单元
  清单 + 将写路径 + 命令形 + pre-spawn 锚检查预判只走 stdout,退出码 0;`--kill-stale`/
  `--purge-audit` 的 dry-run 审视守卫语义不变。壳披露同步:三面 mgh-sdr 壳如实列明壳级
  dry-run 会产生 run 目录/context.json/哨兵(**不是**零副作用试跑)。
- **special-auth 部署面覆盖机制(命令无关)**:可选部署面文件 `mgh-special-auth.md`
  (企业认证与执行环境手册,wizard 插件/CAS 细节/取证三步/故障对照只住在里面;
  `.gitignore` 排除,维护者随包分发)。引导两路落地:sdr 面 = `list_sdr_steps.py` stdout
  顶层 `special_auth{present,path}` 字段(该清单唯一允许的磁盘探测,docstring 承诺同步
  收窄)+ 三面 mgh-sdr 壳 fan-out 步前引导行(在场 → 先读文档、凭证准备与派发 flag 以
  文档为准,**NEVER 链硬边界不可被文档放宽**;缺席 → 通用流程逐字节不变)+
  `resume_sdr_state.py` fanout 步在场提示一行;通用面 = `fanout_runner.py` 在文档在场
  未传 `--cred-file` 时 stderr 一行 advisory——mgh-init/ut-init 等扇出零改壳即被覆盖。
  `install.sh`/`install.ps1` 复制收敛:源在场才落盘 `<dest>/mgh-core/`,源缺席移除目标
  侧残留(收敛态 = 目标副本当且仅当源存在;三态有测)。
- **启动孤儿 advisory**:runner 启动时检出本 tier 残留 liveness 文件 → stderr 一行
  (存活匹配 runner = 提醒已有派发在跑;残留 = 上次硬杀,recipe 指向既有
  `--kill-stale --dry-run`)。非阻塞、不改退出码,复用既有清理机制零新路径。
- **超时四级不变式冻结**:`stall-timeout < call-timeout < budget×0.8 < 宿主上限` 与全部
  默认值零改动(mgh-init 专项实验校准结论承袭);注入移除子进程登录等待后首 token 即
  业务时延,慢模型场景由既有 wave/配额机制消化。
- **配套**:新增 `test_mgh_credentials` 18 测(三模式/外科还原含并发修改幸存/`--check`/
  权限/stdout 无 token)+ `test_fanout_runner` 增 20 测(物化形状幂等续期/cred 损坏
  fail-loud/host 拒识/401 端到端截断〔真 _run_unit + spy Popen〕/dry-run 全树快照零写/
  advisory 两态/孤儿提示/env 认领语义;全套 223 测绿)+ `test_install_special_auth`
  (install 三态收敛,真跑 install)+ `test_list_sdr_steps`/`test_resume_sdr_state` 各扩
  两态;契约同步(`core/contracts/fanout/runtime.md` 注入/过期/纯计划节 +
  `core/contracts/sdr/pipeline.md` run 目录布局补 `childcfg/`/`ocdata/`/`cred*.json`);
  `docs/glossary.md` 补凭证中心/静态注入/子配置目录/数据目录隔离四词条(零企业词汇);
  `docs/man/mgh-sdr.md` 补通用机制段;AGENTS.md 环境约束节加必读指引(细节下沉不入 git
  的 `docs/enterprise-environment.md`)+ R5.9/映射表/诚实边界三处;`tools/
  check_distributed_purity.py` SDD 豁免登记本 change(交付物含 docs/ 路径)+
  `purity_allowlist.txt` pipeline.md 钉扎随行号漂移同步;`install.sh` 共定位自检清单补
  `mgh_credentials`;VERSION 0.1.80→0.1.81。
- **修正批(首次真仓反馈:fanout 起飞前没读 special-auth 文档)**:定位 = launcher
  (零打断优选入口)是规划漏掉的第四消费面——`_build_prompt` 把 step 2–5 连调用行硬编码,
  宿主会话从不经清单拿到 `special_auth` 字段。修:`_build_prompt` 探测
  `<mgh-core>/mgh-special-auth.md`,在场 → 提示词插凭证准备前置块(读文档 → 写
  cred_source.json → 跑 mgh_credentials.py)+ step 3 调用行条件追加 `--cred-file`,launcher
  spawn 前 stderr 披露一行;缺席 → 提示词逐字节不变。resume 面同步加固:fanout 步指引从
  `notes[]` 前置进 `next_action.desc`(恢复编排器逐字执行 desc,NEVER 假定其读 notes);
  三面壳 step 3 措辞收紧为「前置检查(先于 invocation,不可跳过)」。
- **真机机制验证(本机 opencode 1.18.31 + 本地 OpenAI 兼容假网关)**:`opencode debug
  paths` 在 `XDG_CONFIG_HOME`/`XDG_DATA_HOME` 下确认 data/log/repos/config 四路径全部
  重定向进单元目录(**F7 Windows 侧从 C 级升级为已验证**;`state`/`cache`/`bin` 不随
  变量,共享但低争用);子进程日志确认加载 `childcfg/<unit>/opencode/opencode.json`;
  假网关收到真实子进程的 `POST /v1/chat/completions`,`authorization=Bearer <注入
  token>` 与 `model=<模型>` 逐字命中——静态凭证从 cred.json → 子配置 → HTTP 头全链坐实,
  全程零登录闭环。运行注意:自定义 openai-compatible provider 的配置节点 MUST 带
  `models` 映射(缺则 opencode 报 Unexpected server error 且请求不出网)。
- **诚实边界**:保留 plugin 下子进程不自登录、探测插件触发钩子、`opencode run -c` 语义
  三项仍待企业真仓复核(交接清单在 change tasks 10.3);dsh host 同构注入未实现(拒识 +
  special-auth 文档 follow-up 节);mgh-init/ut-init 的清单字段引导未接(advisory 已覆盖
  其扇出)。

### Changed — SDR 配额自适应扇出:估算式准入节流 + 窗口复位冷却 + 切片默认校准 (0.1.80)

`fix-mgh-sdr-quota-adaptive-fanout`(openspec 变更,规格增量回写 `fanout-dispatch` 3 处
requirement + `security-design-review` 2 处 requirement)。依据 2026-10-15 真仓实测:67 个
评审单元 × 每单元 5~10 次模型调用 ≈ 350~670 次,在「每 10 分钟 100 次」限流网关下纯排队
35~67 分钟;默认并发 5、固定 300 秒冷却、256KB 切片上限三个量都按「不限流大窗口环境」设的,
组合起来在限流网关上自我放大(429 → 重派 → 再 429 → 重试烧配额)。

- **派发器配额准入(可选模式,全部 tier 通用)**:`fanout_runner.py` 新增配额三 flag
  `--quota-calls N` / `--quota-window-s W` / `--quota-calls-per-unit K`(默认 10 = 实测
  保守上界,宁慢 NEVER 打穿配额)。N 与 W 成对传入才激活(半配启动校验退出码 2 + recipe,
  与超时不变式违例同形);激活后 `_fill()` 维护本 run 派发时间戳滑动窗口,「窗口内已派发数 ×
  K + K ≤ N」才派,余量不足暂停新派发、分片 sleep(≤1s)等窗口滑动、在飞照常收割,每段等待
  stderr 披露估算口径与预计恢复时刻;stdout 摘要与 sidecar 增
  `quota{calls,window_s,calls_per_unit,admission_waits}`(单一真相源,未配置时该键缺席)。
  **未配置配额 flag 时全部 tier 派发/冷却/截断/stdout/sidecar 逐字节不变**(既有 178 测
  全绿为闸门;零推进熔断只锚新派发,准入等待不误触)。
- **配额窗口复位冷却**:配额模式下,触发快败冷却的 requeue 事件含限流特征 crash 时,冷却
  终点改为 `max(常规终点, 最近特征事件时刻 + W)`——等满窗口复位而非固定 300 秒;仍受
  「剩余时间预算 − 在飞收敛余量」封顶(截断如实披露,截断的等待不算「等满」);非限流事件
  与熔断前退避的冷却时长不变。
- **等满窗口才截断**:配额模式下限流 crash 风暴截断追加前提「至少一次 rate-limit crash
  发生在一次已完整等到的窗口复位冷却之后」——窗口耗尽先自我恢复,等满一个完整窗口仍限流
  才截断(说明配额参数配错),recipe 增「核对配额三 flag 与网关实际配额」一行;
  `--no-rate-limit-stop` 禁用面不变;非配额模式截断条件零改动。
- **切片默认校准 + resume 预算粘滞**:`diff_group.py` 的 `DEFAULT_MAX_INTERFACE_BYTES`
  256KB → 96KB(98304;按 150K 窗口反算最坏上下文栈约 55~70K token,旧默认 95~120K 顶溢出
  边缘);standalone 维持 64KB(最坏约 53K token 无溢出风险,调小只推高单元数反噬配额);
  校准算术与「单元数代价」进 `--help`;run 目录已有 grouping.json 预算记录且未显式传
  flag → 复用记录值(单元身份跨版本升级不漂移,done 单元零重派),显式传 flag 优先并更新
  记录;256KB 旧默认仍是合法显式取值。
- **单遍往返纪律**:`sdr-task.md` 任务模板增「全部输入第一批并行读入 → 一次判断 → 写
  draft 与 touch marker 同批 → 单行 ack,NEVER 逐文件多轮往返」,明示只约束往返次数、
  读/写路径闭集与刚性三元组逐字不变;三面 `sdr-review-fanout` agent 定义(opencode /
  claude / dsh tier)增逐字一致的单行指针(测试锚定)。
- **sdr 壳派发串行缺省 + 步骤清单外包(design D8 A 案)**:三面 `mgh-sdr` 壳规范派发行默认
  `--wave 1`(内网串行最稳 + opencode 并行子进程数据库锁前科,双理由收敛;脚本级
  `DEFAULT_WAVE=5` 不动);`list_sdr_steps.py --step fanout` invocation 携 `--wave 1` 与
  配额三 flag 用法示例,`--step group` discipline 增切片预算校准口径,`--step fanout`
  discipline 增限流窗口等待 recipe——步骤清单成为壳外包后的断言新家;launcher
  `mgh_sdr_launch.py` resume 指引行同步;壳 token 预算经外包取得真实余量(dsh 面
  4997 → 4372 / 5000,purity 基线净缩 12 条存量钉扎)。
- **文档**:维护者 man 页 `/mgh-sdr` 补「配额模式」人话一节(参数 / 建议值 / 调用次数
  算术 / 估算诚实边界);术语词典补「配额窗口」「准入节流」;README `/mgh-sdr` 诚实边界补
  估算式披露;AGENTS.md 用户画像表频控行加配额 flag 指针。
- **测试**:`test_fanout_runner` 增 25 测(准入算术纯函数 7 + 启动校验 8 + 准入闸端到端
  6 + 窗口复位/等满窗口截断 4;harness 层 `--cooldown-s 0`,配额小窗口值控墙钟;红验 =
  stash 实现后新测全红);`test_diff_group` 增 4 测(默认值锚 / ~160KB 接口在新默认下
  重切 -partN 每份 ≤96KB 且对 262144 显式值不切 / 粘滞两向 / 无记录回退默认);
  `test_human_face_vocab` 增单遍纪律三面文档对账 3 测;`test_list_sdr_steps` 增清单
  invocation/discipline 断言新家 3 测。

### Added — 启动路径使用遥测:脚本内埋点 + 冷却窗口,17 个命令壳零改动 (0.1.79)

- 新能力规格 `usage-telemetry`:五条已发布命令(mgh-init / mgh-sdr / mgh-sra / mgh-srr /
  mgh-ut-init)在**启动路径上已有的确定性脚本内部**向内网遥测服务上报一条使用记录——埋点
  方案为脚本内挂载(2026-10-14 维护者拍板,取代第一版的壳埋点:用户 ~150K 上下文窗口比
  什么都宝贵,遥测这类低价值内容不占壳 token,且第一版实测两壳预算已贴顶、埋点行还需做
  预算对冲手术);**17 个编排壳一个字不动**。mgh-sast 无启动期 Python 脚本,不在本版接入
  (占位提案 `add-mgh-sast-telemetry` 记录背景,缓做)。
- 新增遥测模块 `core/scripts/mgh_telemetry.py`(仅标准库,导入 + CLI 双形态):
  `fire(method, params, marker_dir)` 完成采集与上报——username(五级降级链,Windows 域
  前缀剥离)→ ip(UDP connect 路由表探测,不发包、零特权)→ operation(六命令闭集中文
  映射单源,映射外回退原名)→ params(500 字符截断)→ `time` 恒为整数 10(服务端历史
  遥测表遗留列,占位兼容);单次 HTTP POST(UTF-8 JSON,显式空 `ProxyHandler` 直连,内部
  超时约 2s);采集全链逐级降级、全败填 `unknown`;发送失败/超时/端点未配置一律静默跳过;
  `fire` 自身绝不抛异常。
- **冷却标记** `<marker-dir>/telemetry_last.json`(时间戳 + method,阈值默认 30 分钟):
  同一 run 的过程查询/分页重入不重复上报,超窗口的重入(--resume)计一次新启动。诚实
  误差已双向披露(模块 docstring + README + AGENTS.md):统计口径是「活动窗口开始次数」,
  不是精确会话数——超 30 分钟的长任务中途查询会多计、30 分钟内快速重启会漏计。
- 七个挂载点(均为既有启动路径脚本,各 +几行 try 包裹的 import+fire):`write_runconfig.py`
  / `resume_state.py`(mgh-init 全新启动与 resume/查询,后者 params 以 `--resume` 起头并
  从 run_config.json 尽力重建用户 flag)、`write_ut_runconfig.py` / `resume_ut_init_state.py`
  (mgh-ut-init 同构)、`sdr_context.py` + `resume_sdr_state.py` 的状态派生路径(mgh-sdr;
  `--arm-sentinel` 路径不埋点——发生时拿不到用户参数)、`prepare_augment.py`(mgh-sra)、
  `ingest_requirements.py`(mgh-srr)。挂载脚本的 stdout/stderr/退出码/产物 schema/
  `--check` 行为在遥测缺席、故障、超时三种情况下与无遥测完全一致(双层隔离:`fire` 内
  吞异常 + 挂载侧 try 包 import,模块缺失即版本错位也不拖垮宿主)。
- **端点配置** = env `MGH_TELEMETRY_URL` > 模块内置默认常量(初始**空**) > 静默跳过:
  发布即完全惰性,未配置时零网络、零磁盘、零时延;服务端就绪后回填一行常量或逐机设 env
  即激活。服务端接口契约(字段表、operation 闭集对照、请求/响应语义、部署建议、请求示例)
  见 `docs/mgh-telemetry-api.md`(维护者文档区,随本 change 交付;分发面不引用它)。
- 配套面:`install.sh` 共定位自检清单 +`mgh_telemetry`;新增 `tests/test_mgh_telemetry.py`
  36 测(闭集内容锚/采集链 mock 降级/载荷六键契约/端点优先级/冷却窗口/失败隔离/CLI 退出
  码/挂载存在性锚含「17 壳零遥测 token」)+ 八个挂载脚本既有测试文件各补 `TestTelemetryMount`
  类(fire 被调形状 + fire 抛异常/模块缺失宿主契约不变);`tools/check_distributed_purity.py`
  的 R5.11 豁免集 +本 change(docs/ 接口文档即交付物);AGENTS.md(R2 stdlib 模块列举、
  改动面→测试映射表、诚实边界)与 README(「使用统计(遥测)」披露段)各补使用统计披露;
  `docs/glossary.md` 补「遥测/埋点/端点」词条。VERSION 0.1.78→0.1.79。

### Added — 人类面输出纪律:词表单源 + 读者评审,mgh-sdr 报告首落地 (0.1.78)

- 新能力规格 `human-facing-output-discipline`(人类面表面登记制 + 校准读者画像 + 内部词汇
  闭集与两面守卫 + 读者模拟评审 + 写作纪律;初版登记 = mgh-sdr HTML 报告全文 + 数据文件
  人类文本字段)。凡是人要读的产物不许出现只有本工具研发者才懂的词;过程文档按上下文预算
  保持紧凑,不在辖内。
- 新增词表单源 `core/scripts/human_face_vocab.py`:核心 10 词条(投影/切片/hunk/扇出/物化/
  待办壳/facet/闭集/vvah/vvaharness,每条带「人话替身」)+ 按域补充词(sdr 激活;init/
  ut-init、sra、sast/srr 预置数据,登记时才激活)+ `scan_text` 扫描函数;零依赖、无 CLI。
  同形词守则:同形不同义按域收精确词形、NEVER 单词子串禁(「锚点/锚定/基线/单元/哨兵/
  存量/簇/扫描器」全不收——「锚点」是产品概念,只有「路由锚/向上锚定/锚定单元」是 sdr
  算法词)。增长闭环 = 读者评审建议 + 维护者人工发现 → 确认 → 加一行 → 同步改内容锚测试;
  `tests/test_human_face_vocab.py` 以精确集内容锚定「改词不改测试 = 红」。
- `render_sdr_report.py` 确定性文案平实化:分组概览改「评审分组:N 个接口单元、M 个独立文件
  单元(共 K 个)」+「调用链分析:启用——N 个变更接口作为分组入口、M 处改动挂接到未变更
  接口、同入口链路合并 K 组」平实主句,调用边计数收进默认折叠「分组诊断」明细(信息不丢,
  默认视图不闹;grouping.json 字段不动);诚实边界 ①–⑦ 与排除/失败/截断披露逐条转述
  (「目录聚簇/投影/闭集/facet/切片/hunk/检查面」等黑话全数清除,语义保留);头部标签
  「检查面:」改「检查维度:」。新守卫测 `DeterministicCopyVocabGuardTest` 全量提取
  boundaries 变体/概览/模板文本/标签常量扫闭集,漏改即红(确定性文案命中 = 实现缺陷)。
- draft 问题记录 schema 增两个可选人类面字段:`repro`(复现方式:怎么调 + 传什么 + 看到
  什么)与 `fix_diff`(1–2 组 `{before, after}`,`before` 从 slice 逐字摘原文)。问题卡片
  渲染「复现方式」行 + 「修改前/修改后」上下堆叠 `<pre>` 代码块(等宽;文本走 textContent
  注入路线,`</script>`/`<!--` 由 `_json_embed` 转义继续覆盖);数据文件 `findings[]` 透传,
  HTML 与 JSON 同源;旧 draft 缺字段安静省略(渲染与 `--check` 不失败);跨单元三元组去重时
  两个新字段按首个携带者回填(risk/suggestion 维持首写者赢)。
- `--check` 增模型文本闭集扫描(`risk`/`suggestion`/`repro`/`fix_diff` 含对比块两侧):
  命中仅 stderr 计数告警(字段名 + 词),退出码与文本零改动、绝不改写——模型措辞是软质量,
  不因它卡死跑完的长流程;确定性文案闭集合规由回归测试保障,不入 `--check` 面。告警面与
  回归测试 import 同一词表模块(单一真相源,全仓无第二份副本)。
- 读者模拟评审(拦词表拦不住的临场新造词):每次渲染原子写出
  `<run-dir>/readability_text_bundle.json`(合并后全部问题记录的人类面文本单束,评审唯一
  输入);编排器在首次渲染后派发**一次**有界评审子代理(新任务模板
  `core/prompts/fragments/fanout/readability-review.md`:恰好读束 → 恰好写
  `readability_advisories.json` → 单行 ack,至多 20 条建议)后**重渲染**(幂等原子覆盖):
  建议文件可解析 → 数据文件增 `readability[]` + 报告增默认折叠「可读性自检」小节 + stderr
  计数;缺席/不可解析/空产出 → 小节与字段省略 + stderr note,退出码不变、resume 收尾不受
  影响(尽力而为;只建议不改写,建议词经维护者确认才进词表)。
- 提示词与三面镜像同步:`sdr-task.md` 扩字段 schema + 写作纪律节(读者画像/`risk` 首句写
  现象/复现形态示例/前后对比适用条件/禁词,输出字段描述文字自身改读者语言——模型模仿字段
  描述语域,这是防污染最高杠杆点);三面 agent 定义(opencode/claude `sdr-review-fanout`、
  dsh `sdr`)Output schema 行字节一致 + 纪律指针;三面 mgh-sdr 壳加 step 4.5 可读性评审
  (尽力而为、失败 NEVER 重试超过一次、NEVER 阻断 run;派发机制按各宿主——dsh 走
  `MGH_TASK_TEXT` env 无 stdin 通道)。壳预算对冲:step 4 报告结构描述与「报告形态」披露条
  去重(内容并入 step 4),三面增量净零,dsh skill 维持 4997/5000。
- `core/contracts/sdr/pipeline.md` 同步:run 目录布局补两个约定路径、draft schema 块扩
  可选字段 + 兼容降级、render 契约行补平实文案/复现修复对比/文本束与自检小节/`--check`
  告警面、编排器 step 链补评审与重渲染。`install.sh` 自检清单补 `human_face_vocab` 脚本
  与 `readability-review.md` fragment(co-location 断言)。
- 测试:新增 `tests/test_human_face_vocab.py` 18 测(核心/sdr 精确集内容锚、预置域抽查、
  同形负向锚、扫描命中/边界/域门控、双端同源 import、模板与三面 agent 定义/壳对账);
  `test_render_sdr_report` 增 13 测(确定性文案禁词守卫 ×3、复现/修复对比渲染与畸形降级
  ×3、`--check` 告警与干净对照 ×2、文本束与自检小节缺席/消费/坏产出 ×5)+ 存量措辞锚随
  平实化更新(「向上锚定 8」→ 新句式锚)。定向面 10 套全绿;全量回归 66 文件除
  `test_diff_group` 一例 codegraph probe 措辞失败(经 stash 对照为 HEAD 存量、环境相关,
  非本 change 引入)外全绿;lint 四件套过(contracts 465 flags / purity 334 文件零违例,
  基线钉扎随插入行号漂移同步更新且条目数不变 / budget 17 壳全过 / plain_language exit 2
  为既有噪音)。

### Added — /mgh-sdr launcher 内联多分支清单 `--branch-list` (0.1.77)

- `mgh_sdr_launch.py` 新增 `--branch-list "b1,b2"`：逗号分隔的分支名内联清单，引号包住
  直接写在命令行上——临时比两三个分支时不必先建清单文件。解析规则：按逗号切分、逐项去
  首尾空白、重复分支保序去重（只跑一次）；**空项拒识**（`a,,b`、结尾多逗号、全空白 →
  退出码 2 并报出第几项，绝不静默跳过——被吞掉的分支就是无声的复核缺口）；**无注释语法**
  （每个逗号项都是字面分支名）。与文件喂法 `--multi-branch` **互斥**：同给 → 退出码 2 +
  recipe（逗号在 git 分支名中合法，"值含逗号即列表"的双重语义对合法分支名有歧义，故独立
  参数 + 显式拒识，不猜优先级）；与单分支 `--branch` 同给时内联清单优先（与
  `--multi-branch` 压过 `--branch` 的既有行为同形）。内联清单汇入与 `--multi-branch`
  完全相同的串行逐分支流程（每分支独立 run 目录 + 独立报告，退出码 0/1/2 语义不变）；
  `--help` 载明该 flag（launcher 的唯一契约面）。README 多分支段同步补第三种喂法。

### Added — README 补 /mgh-sdr launcher 完整命令行与参数示例 (0.1.76)

- 多分支批量复核段补全:`--host opencode`、`--dry-run` 冒烟、`--branch` 单分支、`--open`、退出码 0/1/2、
  `branches.txt` 格式(一行一分支/`#` 注释/重复去重);修正示例脚本路径——原文 `<安装目录>/mgh-core/scripts/`
  是 dsh 面布局,opencode 面(首选宿主)实为 `<项目>/.opencode/mgh-core/scripts/`,照抄会找不到文件;顺带
  披露 0.1.75 的失败证据落点(`host_error.log` 免翻全局日志)。

### Added — 研发流程规则：openspec SDD 工件按人类可读写作（只约束增量） (0.1.76)

- AGENTS.md 研发铁律 R3 增补一条：proposal / design / tasks / spec delta 按人类面可读写作。
  动机：这些工件是维护者评审的对象，此前沿用了 agent 面的压缩文风（复合名词堆叠、嵌套括号、
  连发的规范动词），维护者评审越来越吃力；而 SDD 工件与目标用户的 150K 预算完全无关——本仓
  研发阶段上下文 1M、token 无限制，压缩没有正当性。规则要点：基准读者 = 一两年 Java Web 经验、
  不了解本项目内部语境的工程师；完整句子、一句一个信息；术语首现给白话解释；禁自造复合名词；
  括号嵌套 ≤1 层；RFC-2119 只用于真正的规范断言。openspec 结构约束与人话序要求不变；历史归档
  与既有主规格存量段落不回溯。纯流程文档规则，无代码改动。

### Fixed — /mgh-sdr launcher 失败可诊断性:扇出子会话 provider 错误时间窗证据落盘(上轮真仓复测 F1) (0.1.75)

- **F1 收口——`--print-logs --log-level ERROR` 对扇出子会话 provider 错误行为级无效**:该 flag 组合只路由
  opencode **父 run 进程自身**的日志;编排器经 Bash 派发的扇出 subagent 是独立会话,其 provider 错误(2026-10-13
  实测 2 次 `AI_APICallError` stream 断连)只落用户级全局日志 `~/.local/share/opencode/log/opencode.log`,
  launcher stderr 零浮出——「失败可诊断」承诺在其目标失败形态上不成立,排障须脱离 run 目录人肉翻全局日志。
  现在:flags 保留(父进程自身错误仍尽力披露,承诺面在 docstring/spec 双处收窄),宿主退出后 launcher 从全局日志
  **时间窗提取** `level=ERROR` 行逐字落盘 `<run-dir>/host_error.log`(两行来源/窗口头注;opencode 宿主、真跑分支、
  **成功与失败同治**——被 opencode 内部重试吸收的瞬时断连同样留痕);stderr 披露一行证据计数与路径;分支 FAILED 时
  失败信封与 `FAILED BRANCHES` 汇总携带证据文件指针,零捕获时 recipe 改指全局日志绝对路径;提取一律 fail-soft
  (全局日志缺失/不可读/无任何 `timestamp=` 键/ERROR 行时间戳不可解析 → stderr note 注明假定路径——opencode 换
  路由时自我暴露——**NEVER** 影响分支判定与退出码);证据文件三态可区分(缺席=未提取/仅头注=零捕获/有正文=窗内
  ERROR 行);诚实边界:时间窗提取是诊断近似,同机并发 opencode 会话窗内 ERROR 行可能混入。规格 launcher 要求
  第 ⑧ 项改述为真实机制 + 3 个新 scenario;`test_mgh_sdr_launch` 新增 `TestHostErrorEvidence` 11 测
  (窗界/解析拒绝/多字节逐字/三态/fail-soft/claude 跳过/失败指针),假宿主面全局日志钉扎 hermetic(测试永不读
  真机全局日志)。

### Fixed — mgh-init 收官对齐:`--merge` 显式拒绝 / base agent ack 枚举收口 / stage 提示词七修 / 契约九修 等 (0.1.74)

- **H11 拍板项选 (b)——`--merge` 全链显式拒绝**:该模式声明的 `merge_inventories.py` 全仓不存在(无可执行路径),
  编排器只能即兴 LLM 徒手合并(无闸门无确定性去重)。现在:`write_runconfig.py` 对 `--merge` 退出码 2 + recipe
  (指认无确定性实现、多次分模块运行产物独立);run_config 不再记录 `mode`/`merge_partials_dir`;resume_state 删
  merge 短路分支 + 步词表去 `merge`(历史遗留 `mode=merge` 旧 run 按磁盘产物正常派生);list_steps 删 merge 行;
  `init-stage/merge.md` fragment 删除;三面壳 flag 表/描述/流程清单去 `--merge`;规格 8 处 MODIFIED(含全部
  「建议 `--scope`+`--merge`」advice 措辞改「`--scope` 分模块,产物独立」)。(a) 实现确定性合并脚本留待真实诉求立项。
- **ack 枚举收口(批次 5 遗留三.15)**:全部 agent 定义(三面 20 个:opencode/claude 的 base + fanout/rollup 克隆 +
  dsh tier agent)回传 ack 枚举删 `oversize <绝对路径>`——stage Return 段从未定义 oversize ack 的行为;base 与克隆
  漂移致 `TestAgentCloneParity` 在 HEAD 即红,本批同步后转绿;规格 bounded-ack requirement 把 oversize 移出取值枚举
  (dispatcher `_parse_ack` 历史容错不动;T3 枚举器的 `oversize:true` 输入侧标注不变)。
- **stage 提示词七修**:①`evidence_snippet` 移出「中文化对象」枚举(init-scout/init-resolve——它是逐字源码行,
  翻译即破坏证据锚定);②init-induct 补 Form B pack 形态指引(pack id/members[]/成员级 checkpoint/包级 marker)+
  schema 补 canonical 8 类与「自造类名被闸门拒」;③init-survey 第 1 步改绝对路径 + 读白名单补列该两文件(消互斥);
  ④init-rulewriter 补读侧三件套(锚 repo 根/NEVER 越界/Bash 搜索同禁);⑤init-rules-consistency「managed block」
  改详述文件表述;⑥rules-format 两文件 `--check` 覆盖面如实(FORBIDDEN_TOKENS 实况;裸 tier 词有意不拦);
  ⑦init-scout 删 `regex_known[]` 幽灵输入字段。
- **契约九修(以源码为准)**:clusters.md cluster_id 公式改实况(集中式 4 段含 file 槽位;判别尾 = sha1 前 12 hex,
  源码内名 sha8 实取 [:12]);scout-plan.md 幻影 flag 改真名(`--batch-bytes`/`--batch-cap`)+ 补计划自描述;
  candidates.md 删幻影 source `regex+scout`;unit-inputs.md done 检测改 forward marker 实况 + bytes 按 tier 分列;
  manifest.md 删「unit record」幻影形状 + resolve 行注记非确定性;三枚举器契约补实况 CLI flag/分页四字段/恒等式
  改述/pack 模式补记;resolved.md 补「additive 无确定性出口」披露;step-manifest/resume-state 词表与 merge 行同步。
- **笔误**:t2.md `openmode`→`opencode`;controls-context.md `中和`→mitigation。
- **测试**:merge 拒绝红绿(write_runconfig exit 2 + recipe/payload 无 mode 字段/resume_state 词表无 merge + 旧 run
  兼容派生/list_steps 无 merge_inventories 死引用);TestAgentCloneParity 红→绿;定向面 11 文件全绿(write_runconfig 28/
  resume_state 81/list_steps 15/stuck_run_selfheal/dsh_command_surface/init_flag_table_contract/agent_stage_contract/
  recipe_visibility/distributed_md_purity/zero_deps/no_compile_warnings);lint 四件套过(contracts 465 flags/budget 17 壳/
  purity 323 文件零违例/validate --strict);实机冒烟过(--merge 拒绝 recipe + 零产物 + 正常 ack 无 mode)。
- **评审判定订正**:self-verification/severity-guidance/exhaustiveness 三 fragment 非孤儿(sast-deepdive 分发面引用
  实存),保留不动。

### Fixed — mgh-init 发现层扫描韧性:调用图单遍丢边 / 配额混计静默截断 / scope 拼错静默空集 / --check 形状错裸崩 / 续点混合候选集 / 调用图无软时限 / 检查点写放大 等 11 项 (0.1.73)

- **调用图两遍化(H5)**:`expand_scope.build_call_graph` 由单遍(边走边建 def 索引,文件只能解析到枚举序
  在前的定义 → 约半数跨文件边静默丢失、不进 `unresolved[]`)改两遍——pass 1 建完整定义索引、pass 2 对
  完整索引解析调用,与文件枚举顺序无关(镜像 `discover_controls` 内部两遍实现);mgh-sast 的 scope
  resolver CLI 消费面同享修复,输出 shape 零变化。
- **文件配额只数源文件(H6)**:`walk_sources` 的 `limit_files` 仅对源扩展名文件计数(.txt/.xml/.sql 等资产
  不再耗配额);触顶 stderr 告警 + 新 `limit_hit` accumulator 上浮截断信号(镜像 dot_skipped 家族)——
  修复前混合仓的截断点随枚举序不可预测,且 discover 的 `max_files+1` 截断哨兵(建立在「配额只数源文件」
  假设上)永不触发、源文件静默丢失。
- **scope 歧义输入 fail-loud(H7)**:`expand_scope` 的 `--path` 指向不存在目录 / `--package` 零匹配 →
  退出码 2 + recipe(修复前静默空集 + exit 0,拼错路径产出「该模块无存量控制」的错误安全结论,sast 侧
  同病丢全部 findings);「目录存在但无源文件」保持 exit 0 + note(合法空集)。
- **discover --check 形状错收口(M1)**:「合法 JSON 但 wrapper/集合形状错」在 not-list 分支归一 `[]` 后报
  violations + 退出码 2——修复前 `enumerate(None)` 裸崩 TypeError(实机复现),退出码 1 不在编排器闸门
  语义内。
- **续点参数指纹(M2)**:`scan_progress.json` 记录生效扫描参数指纹(scope 形态 + language);`--resume`
  参数与指纹不符 → 弃续点从头扫 + stderr 披露——修复前换参续跑把新旧参数的候选静默混进同一集合;存量
  无指纹续点视作相符(兼容)。
- **调用图软时限(M3)**:deadline 检查扩至两 pass 内部(`--progress-every` 节奏,修复前最贵阶段不设防、
  超宿主超时零全损);pass 1 完成态落 `cache/callgraph_defs.json` 供 resume 复用(defs 命中跳过 pass 1);
  pass 内超限 → 干净 partial 早退(exit 0 + `partial:true`),既有 scan 续点保留。
- **续点增量日志(M4)**:累积候选改追加式 `cache/scan_journal.jsonl`(每检查点窗口只写新增,flush+fsync),
  `scan_progress.json` 瘦身为小体积元数据(索引/计数/指纹)——总写放大由每边界全量重写累积列表的
  O(n²) 降为 O(n);journal 与计数不符(撕裂/篡改)→ 弃续点重扫自愈;完成态保留 journal(幂等 resume
  重放候选);旧内联形续点(无 journal)加载兼容。
- **plan_scout 原子写(M5)**:`scout_plan.json` 改 `.tmp` + `os.replace`(原子写家族统一)——半写 plan 是
  scout 层「损坏 plan」输入的主要供给源。
- **step 0 持久性(M6)**:`write_runconfig.py` 原子写补 flush + `os.fsync` 再 replace(run_config / 哨兵 /
  gitignore 三处 co-write 同治)——修复前掉电后 `os.replace` 可落零长度 run_config(崩溃恢复唯一锚点);
  哨兵一致性:init_dir 基名为规范运行目录名(`.mgh-init`/`.mgh-ut-init`)而 `--run-root` 派生另一域 →
  退出码 2(修复前错组把错误域的受信子树写进哨兵);custom 名 `--init-dir` 保留既有「覆盖」语义。
- **describe --field 有界输出(M7)**:单独使用时值经 `VALUE_ECHO_CAP`(4096)截断 + `truncated` 标志 +
  容器 `{type,count,sample≤4}`——修复前整份值无界倾倒 stdout(该脚本要替代的反模式);与 `--count` 等
  模式组合行为不变。
- **剪枝按 repo 相对分量(M8)**:`walk_sources`/`collect_dir` 的 EXCLUDE_DIR 与点前缀剪枝判定改
  `p.relative_to(repo).parts`(修复前检查绝对路径全部分量,repo 放在 `build/`/`.cache/` 等排除名或点前缀
  **祖先**目录下即整仓静默扫空,实测 0 产出)。

### Fixed — mgh-init 枚举/聚合层口径分裂收口:簇级计数吞失败 / t2 预算口径 / 单元预算无消费 / scout 广告路径分叉 / T3 判定反推 / rollup 全量路径进 stdout 等 11 项 (0.1.72)

- **簇级计数三分(H4)**:`list_clusters.py` 两条计数路径(无打包 / 打包)的簇级计数由残差公式改
  逐簇三分(全部单元 `.done` → done;全终态含失败 → **failed**,对 `--retry-failed` 可见;否则
  pending)——修复前「1 簇 2 片全 `.failed`」被计为 `{done:1, failed:0}`,分片失败被吞;打包模式
  `cluster_done` 同改只数全 `.done` 簇。
- **t2 聚合物化口径(H8)**:`plan_aggregate.py` t2 分桶/瘦身判定由紧凑序列化字节统一为物化口径
  (信封 + 缩进 + CRLF,镜像 scout-merge 既有形态)——修复前 96KB 预算物化出 ~1.23× 超预算文件;
  `pending[].bytes` 回填落盘文件 `st_size`;`total_bytes`(输入规模披露)保持紧凑口径。
- **单元预算消费闭环(B1,批次 1 锁步兑现)**:`fanout_runner.py` 派发前读 `<init-dir>/run_config.json`
  的 `budgets.max_unit_bytes`,为正整数即向 scout/t1/t3 枚举器透传 `--max-unit-bytes`(此前该值
  只被记录、无任何消费方);`canonical_unit_ids_for_run` 增可选预算参数,`resume_state.py` t1 复算
  同 change 切到 run_config 值——派发物化与状态机复算恒同源,自定义预算 run 不再复活「复算只见
  整簇 id → step 永卡 t1」死锁;缺 run_config 两侧同退共享默认。
- **scout 广告路径编码同源(B2)**:`list_scout_batches.py` pending 广告的 checkpoint/done/failed
  路径改经共享 forward 编码函数产出(死 import 转正)——修复前广告裸 bid 拼接、判定侧编码,
  `::`/超长 id 的批「marker 写得到、判定看不见」→ 无限重派。
- **T3 判定正向化(B3)**:`list_rule_jobs.py` done/failed 判定改 forward marker 路径计算(canonical
  `<cat>.<fmt>` 单元集正向判,与 T1/scout 同构),glob 降级为孤儿审计(stderr 告警不进计数);
  私有 `_safe_name` 改 `init_tier.safe_unit_filename` 别名(编码单源);failed marker body `unit`
  字段仅作诊断对照。
- **分页卫生(M1)**:list_clusters / list_scout_batches / list_rule_jobs / plan_aggregate 四枚举器
  `--limit < 1` → 退出码 2 + recipe(与 `--offset` 校验对称;修复前空页 `effective_limit=0` 报成功,
  按 offset 推进的编排器原地自旋)。
- **scout 计划自描述(M2)**:`plan_scout.py` 生成时把 `batch_bytes`/`batch_cap` 记进 plan 顶层;
  `--check` 优先按 plan 记录值判预算(缺记录的存量 plan 回退 CLI 值)——修复前自定义批字数的合法
  plan 在缺省 `--check` 下按 98304 误报违例;损坏 plan(不可解析 / wrapper 形状错 / 缺失)退出码
  统一 **2**(闸门 recipe 只认 2,修复前 1)。
- **切片器三修(M3)**:`chunk_sources.py` JAVA_DEF 匹配后按捕获名确定性后过滤控制流关键字
  (while/for/do/if/switch/catch/finally/synchronized/try/return/new/throw)——修复前循环/分支块
  被当函数节点,大文件按循环体切分且外层方法 `line_end` 被截断;`--in` 不存在 → 退出码 2 fail-loud
  (修复前「成功 + 空骨架」);`--line < 1` → 退出码 2(修复前 `--line 0` 真值判断静默落骨架模式)。
- **fold-in 韧性(M4)**:`merge_scout.py` 双文件写改原子写 + 写序反转(clusters 先、携凭证的
  candidates 后,凭证在 ⟺ 两文件一致)+ 追加簇按 id 去重(两写间崩溃后重折幂等收敛,修复前
  重复追加);未映射非规范类别在 fold-in 主路径(含 audit 路径)fail-loud 退出码 2(镜像 `--check`;
  缺字段候选保持 skip+warn 既有语义);合法 JSON 形状错(wrapper 非 dict / candidates 非 list /
  candidate 非 dict / audit_found 形状错)→ 结构化错误 + 退出码 1,不裸崩。
- **rollup manifest(M5)**:`plan_aggregate.py` needs_reduce 时原子物化
  `<shard_cp_dir>/rollup_manifest.json`(全量 shard 摘要路径 + output + done_marker,幂等);
  stdout `rollup` 段改携 `summary_paths_manifest` 绝对路径,`NEVER` 携带全量 `summary_paths` 数组
  (1000 shard ≈ 100KB 会击穿 64KB 编排器单次回复承诺);`init-synthesis-rollup` / 
  `init-scout-merge-rollup` stage 提示词 + 两面 rollup agent 定义 + 两契约(aggregate-sharding /
  scout-plan)同步「先 Read manifest 取 summary_paths」消费形态;`needs_reduce:false` 路径逐字节不变。
- **死常量清理(L1)**:删除 `list_clusters.py` 本地 `MAX_UNIT_FILENAME_STEM = 200` 重定义
  (自称 alias 实为独立副本,上游改值即静默漂移;单源 = init_tier import)。
- **lint 基线**:`tools/purity_allowlist.txt` 三条钉扎随 rollup 消费面行号漂移同步更新(条目数不变,
  本批未新增任何分发面违例)。


### Fixed — 分发面死链与披露/契约失实收口:codegraph-hint 与 rules-format 死链、dsh 派发披露失实、壳 flag 表死旗、agent/stage 契约对形、run 目录 gitignore 兑现、install 卫生 (0.1.71)

- **死链修复(第 10 类)**:六个 stage 提示词(init-{scout,induct,survey,resolve} + sra-{clarify,augment})的
  `core/prompts/fragments/codegraph-hint.md` 引用改为「同安装 prompts 树兄弟目录」表述(宿主中立,单源
  一处修六处);rules-format 四面引用(stage + claude/opencode 三 agent 定义)改各自安装布局路径(dsh
  `t3.md` 先例形态);三面 init 壳 Output 节 `core/contracts/init/{clusters,unit-inputs}.md` 改安装布局路径;
  codegraph-hint 头注失实的「Inlined into the task message」机制陈述改为实况(按信号 Read 的独立 fragment);
  `orchestrator-discipline` 头注「to come」清单改实况(ut-init 已发布,待发布仅 mgh-blst)。
- **lint 兜底**:`check_distributed_purity.py` 新增第 10 类(`core/(prompts|contracts|scripts)/` 源码树
  路径前缀,md-only),存量非 init 切片命中(186 行)以 `tools/purity_allowlist.txt` 钉基线放行
  (自动加载、只减不增,陈旧钉扎由测试检出);`check_contracts.py` 新增 init 壳参数表对账(死旗
  `--out`/`--config` 显式钉禁 + 三面 flag 表同集 + 条目对账消费脚本 `--help` 并集)。
- **dsh 派发披露实况**:`releases/dsh/skills/mgh-init/SKILL.md` 已接线 tier 清单补 scout-merge(与
  fanout_runner TIERS 闭集一致);交互 stage 停止清单闭集补 T2 单上下文 `init-synthesis`、T2 rollup、
  scout-merge rollup;`--skip-consistency` 注明 run 起始参数、mid-run 不可注入;停在 t3 后 T4 未跳过
  = 无终态 `init_manifest.json` 的形态与 `--resume` 收尾写明。
- **壳参数表对账**:`--out`/`--config` 死旗从三面 init 壳移除;claude 面补 `--rules-dir` 行(三面同文);
  call-graph 缓存句三面统一为实况(缓存跨 run 复用、mtime/size 失效、`--rebuild-cache` 强制重建);
  claude Output 节与 assemble_rules 表格单元向 opencode/dsh 形态对齐(白名单方言差异保留)。
- **run 目录 git 隔离兑现**:`write_runconfig.py` step 0 落盘时确定性 co-write `<run-root>/.gitignore`
  (单行 `*`;已存在则不重写,目标根 .gitignore 零触碰);新增 `--check`(run_config 缺失 exit 2,
  sentinel/gitignore 缺失 warn 级报告)。
- **agent/stage 契约对形**:init-scout-fanout / init-induct-fanout / init-scout-audit(双面)删除其
  stage 未定义的 `oversize` ack 枚举(dispatcher `_parse_ack` 容错不变);`init-scout-audit` 权限钉扎与
  stage 授权一致(opencode `bash: allow`;claude `tools:` 补 Bash + Write),Input 补编排器透传的
  `slice_dir`,编排器手派透传清单同步。
- **install 卫生与自检**:分发拷贝后 prune `__pycache__`(claude/opencode 面辖 DEST,dsh 面仅辖
  mgh-core/ + .dsh/ 永不扫目标自有目录);claude 补发 `init-scout-merge-rollup.md`(以 opencode 面为源
  镜像);install 自检新增「mgh-init 壳 subagent inventory 点名的 agent 定义文件必须存在」断言
  (fail-soft,claude/opencode 面);fan-out payload 成功消息的 agent 清单核准(原 brace 展开列出不存在
  的 `*-fanout-fanout.md` 形态)。


### Fixed — 扇出派发器 6 缺陷卫生收口:冷却忙等自旋 / 树杀失败无升级无处置 / 越树 marker 反被物化 / kill-stale 子串误杀 / spawn 未剥 PWD / 审计文件名编码漂移 (0.1.70)

- **冷却忙等自旋**:熔断前退避恰在 drain 点武装(队列空、在飞零),旧冷却 gate 要求队列非空
  才 sleep → 零 sleep 自旋烧满一个核最长 300s。gate 改 `cooldown 未到期 ∧ 无在飞` 即休眠
  (≤1s 分片),队列空不空都等。
- **树杀失败检测与升级**:`_kill_tree` POSIX 侧 SIGTERM 后短宽限内复查进程组存活性,仍存活
  升级 SIGKILL(组杀 + 直接 kill 兜底);Windows 侧 `taskkill` 失败重试一次。返回 False(杀
  失败)时:单元本 run 不再重派(幸存进程拥有该单元,防并发双跑竞写检查点)、pid 保留在
  liveness `children[]` 供 `--kill-stale` 检出(不再摘除成不可追踪孤儿)、stderr fail-loud +
  stdout 摘要新增可选键 `kill_failed:[unit…]`(无杀失败时省略)。stall/timeout 两调用点检查
  返回值,杀成功路径语义逐字不变。
- **越树 marker 永不物化**:path-drift 拦截检出越树路径后的响应曾是向该路径 mkdir + 写
  `.failed` marker——「检测到投毒后反而执行投毒路径」。`_write_failed_marker` 写盘前按 repo
  锚 resolve 校验(显式 failed ack 与 path-drift 两入口同判):树内照旧、树外 NEVER
  mkdir/写盘 + stderr recipe,单元留磁盘 pending,不虚增 `failed` 计数,有界性由既有零推进
  熔断承担(`stalled_pending[]` 披露含 stuck 单元)。
- **kill-stale 身份匹配锚定可执行 token**:子进程判定从「全命令行小写子串包含」改为
  「argv[0] 路径基名(引号闭合 span 优先,统一分隔符、小写、剥 `.exe`/`.cmd`/`.bat`)∈
  {opencode, claude, dsh}」——`notepad C:\notes\claude-meeting.txt` 这类宿主名仅在参数里的
  无关进程不再被整树强杀;漏杀方向退回既有 PID 复用防护路径(宁漏勿错)。runner 侧匹配不动。
- **spawn 剥离 PWD**:全部 host 的子进程 env 统一 `os.environ` 去除 `PWD`(dsh 形继续附加
  `MGH_TASK_TEXT`)——opencode 按 `PWD ?? cwd` 解析项目归属,宿主外手动拉起 runner 时继承的
  `PWD` 会压制显式 `cwd=repo` 使子会话认错项目;claude/dsh 不读 `PWD`,剥离无副作用。
- **审计文件名编码归一**:`_safe_name` 改为 `init_tier.safe_unit_filename` 的别名(镜像
  list_scout_batches 形态),超长单元 id 获得 200 stem 截断(保判别尾),`.task.md`/`.run.log`
  永不超 NTFS 255 上限写失败(旧私有拷贝只做 `/ \ :` 替换、无截断);短 id 输出逐字节不变,
  audit/run.log 文件名与枚举器 marker 路径同名一致。
- 测试:先红后绿新增 8 组(`TestCooldownWaitCoversDrainedBackoff`/
  `TestKillFailureDisposition`/`TestKillTreeEscalation`/`TestWriteFailedMarkerAnchor`/
  path-drift 越树 CLI 级/`TestSpawnEnvStripsPwd`/`TestSafeNameEncoding` ×3/
  kill-stale 锚定 ×2)+ 既有 `_run_unit` 返回面 17 处 unpack 随 6 元组返回(新增 `kill_ok`
  元素)同步;`test_fanout_runner` 173/174 绿 + `test_fanout_stale` 31/31 绿 +
  zero-deps/no-compile 绿。唯一失败 `TestRateLimitStorm.test_all_rate_limit_storm_truncates_fast`
  (waves_run 3≠2)经 HEAD worktree 对照为**存量失败**(HEAD 同断言同值失败),与本批无关。
  sdr tier 用例(`TestDshHost` 等)零回归。

### Fixed — 守卫域 13 缺陷收口:redirect 越树四域放行 / stdin 未强制 UTF-8(GBK 中文 Windows 守卫整域休眠)/ 写目的地三入口翻转等(H2+H3+H13+M×7+L×3,2026-10-13 评审批次 2) (0.1.69)

- **H2(高危,实测复现)redirect 越树拦截对四域不可达**:`_redirect_in_sanctioned` 是「init/ut-init
  受信子树白名单」查询函数却被复用在语义相反的调用点(树外拦截豁免),对无 allowlist 的
  sast/sra/srr/sdr 直接放行——`echo x > <声明的只读根>/f` 全链路 exit 0,「声明只读根永不可写」
  被击穿。新增单一谓词 `_bash_write_dest_blocked` 统一三个 Bash 写入口(Bash 写动词 / `>`/`>>`
  redirect / `py -c` 写形态重标记),按域逐字镜像各自 Write/Edit 工具面:init/ut-init 走
  `_allowlist_write_blocked`(受信子树 + AGENTS.md + 哨兵 `out_roots`),四域树外即拦、树内放行;
  `read_roots` 在任何写面永不豁免。净网(rule m)对 allowlist 域同样放行 `out_roots` 令牌
  (写谓词已判合法的目的地不再被读侧 recipe 二次拦);`_redirect_in_sanctioned` 删除,
  `_emit_bash_write_block` 死参 `out_roots` 移除。
- **H3(高危,实机 A/B)stdin 未强制 UTF-8**:`json.load(sys.stdin)` 解码随控制台代码页走,
  中文 Windows(GBK 管道)下 UTF-8 payload 被按 cp936 错解 → `cwd` 锚点损坏 → 哨兵发现失败 →
  域判 None → **六域全部规则对整场 run 静默放行**。改 `sys.stdin.buffer.read()` +
  `decode("utf-8", "replace")`(StringIO 替身 getattr 回退;不可解析 payload 维持 exit 0 fail-soft)。
  实机抽查:PYTHONIOENCODING=gbk + chcp 936 子进程喂 UTF-8 payload → 拦截生效。
- **out_roots 三入口翻转(连坐修复)**:同一授权写根,Write/Edit 工具面放行、Bash 写动词却拦
  (`_emit_bash_write_block` 的 `out_roots` 形参从未被读)——三入口现同判。
- **H13(文档失实)两处按域改述残留哨兵语义**:`orchestrator-discipline.md` 与
  `runtime-enforcement.md` 原宣称「残留哨兵只挡脚本写、不挡 JSON/`.md`/读」,与实现矛盾
  (实测 init/ut-init 域哨兵激活 = 受信子树外**一切写**全拦 + 树外读拦 ≈ 日常开发全面写锁;
  四域 = 脚本写 + 越树写 + 树外读拦)。两处均补处置路径(rm / resume 重写;init 完成态残留已被
  `resume_state --check` 检出);回归测把该语义钉死(init 哨兵下受信子树外 `.md`/`.json` 写拦)。
- **判定/哨兵双 cwd 源合一**:路径判定(`..` 相对 token、cwd 缺省锚)此前用 `Path.cwd()` 而哨兵
  发现用 payload `cwd`,错根时系统性误判;现统一 `judge_cwd`(payload `cwd` 优先、回退进程 cwd)。
- **解释器规则误拦/绕过收口**:`py -m pytest <树外.py>` / `py -c "…" <树外.py>` 的尾随参数不再被
  误当执行脚本(token 走查遇 `-c`/`-m`(含 `py-c` 粘连形)即退出,负向前瞻死代码删除);
  `python3.11 -c` / `python3.12 - <<EOF` 带点版本绕过全部内省与 heredoc 检测(版本段
  `[0-9]*` → `[0-9.]*`)。
- **规则 l 搜索模式误触 stop-all**:`grep -n "mgh-core/scripts/run.py" notes.md` 的引号内模式被当
  磁盘引用触发最重阻断;改按简单命令分段,搜索动词(rg/grep/findstr/find/…)段的首个非旗标操作数
  (模式)豁免,读动词(cat/type/Get-Content)不豁免(stop-all 面不缩)。
- **双 shim fail-soft 修真(opencode + dsh)**:python 对缺失守卫文件以退出码 2 退出
  (`can't open file`),与阻断退出码同值——守卫缺失/错位会被误判为 deny。spawn 前补
  `existsSync`(node:fs)存在性预检(缺失 → 放行 + 诊断),退出码 2 且 stderr 含
  「can't open file」签名亦按 fail-soft 放行(TOCTOU 兜底);parity 测加源形态断言防回退。
- **其余 medium/low**:`get_discipline` 改 `copy.deepcopy` 返回(消费方一次 append 曾永久污染
  跨域共享纪律表,`dict(_EMPTY)` 浅拷贝形态一并消灭);净网路径 token 左边界类补 `<`/`>`
  (`echo x >D:/out/f` 无空格重定向形态此前提取不到 token);f2 叶源码拦截路径段比较改大小写
  不敏感(`.CLAUDE/Mgh-Core/Scripts` 变体不再绕过);模块 docstring 规则 (m) 重复段删除。
- **测试**:17 条先红后绿(`test_block_adhoc_scripts` 7 组 25 测:写目的地统一/stdin 编码/解释器
  规则/规则 l 豁免/单一 cwd 源/净网边界+f2 大小写/H13 语义锚;双 parity 各 1;纪律表污染 1;
  另 6 条语义锚修复前后均绿),`test_block_adhoc_scripts` 全文件 300 测零回归;定向面
  (parity ×2 / install_hook / install_opencode_plugin / install_dsh / resume_state / list_steps /
  zero_deps / no_compile_warnings)全绿;purity 324 文件零违例;contracts / budget lint 零变化
  (plain_language exit 2 为存量,HEAD 同态,本批两 md 零警告)。守卫三份镜像字节一致。


### Fixed — /mgh-init resume 状态机 CR-1 分片簇死锁 + 口径合一/done 可达/哨兵闭环/契约同步(CR-1+H12+t3 裸 glob 等 11 项,2026-10-13 评审批次 1) (0.1.68)

- **CR-1(唯一 Critical)分片簇死锁**:`resume_state.py` 的 t1 id 集从「空候选集 + 零预算退化
  调用收集器」改为经 `list_clusters.py` 生产者侧共享函数 `canonical_unit_ids_for_run` 按真实候选 +
  共享默认单元预算**复算**;`tiers.t1` 改**单元口径**(整簇 id + 真超预算簇 `::shard-<n>` 分片 id,
  `total`=单元数),t1 闸门按单元总数收敛——修复前分片簇只写分片级 marker、状态机永判
  `done+failed < total`,`--resume` 无限空转重派(数百万行 Java 仓注解簇超预算切分是常态)。
  预算锚共享默认常量(runner 今日不透传自定义预算,复算与物化口径严格一致;转发落地时两处
  锁步切换已写注记)。
- **幽灵 shard-0(评审实验新发现)**:`list_clusters.py` `_shard_plan` 补整装守卫——绝对化整装体
  ≤ 预算返回 `[]`(判据与 `_resolve_units` 整装短路同度量,杜绝「判据说切、物化说整装」漂移);
  `collect_canonical_ids` 改产**恰为可物化单元集**(整装簇 → 整簇 id;超预算簇 → **仅**分片 id,
  整簇 id 不再混入)。修复前每个含候选簇都派生一个永无 marker 的 `::shard-0`。
- **manifest 短路(D4)**:`init_manifest.json` 在 → step=done 提到全部 tier 闸门之前,完成态 run
  不再被下游计数口径漂移拉回执行态重派(tier 计数照实披露)。
- **t3 前向口径(D5)**:t3 done/failed 从裸 glob 改为 inventory categories × format 的 canonical id
  正向判定(id 公式由 `list_rule_jobs.py` 单一来源导出 `rule_unit_ids`,枚举器 marker 路径同函数
  消费,逐字节等价);孤儿 marker 不再抬高 done 静默跳过 pending category;`--check` 孤儿/判定
  一致性审计扩到 t3 目录(此前仅 scout/t1)。
- **done 步可达(H12)**:`_FRAGMENT_STEPS` 增 `done`,step=done(含 finalize 分支)→
  `stage_flow_files[]` 返回 done.md——manifest 收尾 + 失败落账 + **移除哨兵**纪律经既有
  「Read stage_flow_files[0]」壳配方恢复可达(长跑压缩后恢复到收尾态不再失联,残留哨兵不再
  写锁目标项目);merge 短路分支补 `stale_fanout` 字段(「字段恒存在」承诺兑现,消费方不再
  KeyError)。
- **`--check` 哨兵生命周期双向闭环**:新增「完成态哨兵残留」违例(manifest 在 + `.active` 在 →
  exit 2 + `rm` 移除 recipe),与既有「进行中缺哨兵」违例构成闭环。
- **`--invalidate-stale` 收口(D8)**:前置判定复用「scout 启用 + 未完成」同判据(不满足 → 诚实
  空转删零文件 exit 0,不再删有效下游凭证迫使 T2-T4 全量重跑);unlink 失败收集 → exit 2 +
  stdout `removed[]`/`failed[]` 如实区分;`--check`/`--rearm-sentinel` argparse 互斥组、
  `--dry-run` 单独传 exit 2。
- **t2 闸门前置 + fragment 头注如实化(D7)**:`t2.md` 头部补无条件 `validate_t1_records
  --strip-bom`+`--check` 前置闸门(resume 直落 t2 不再跳闸门);survey/resolve/t4 头注删
  「Loaded per-step via resume_state」虚假声明改如实可达性陈述;`assemble.md` 尾部补「进 T4 前
  Read t4.md」固定路径配方。
- **两份契约同步 + 防再漂移(D9)**:`resume-state.md` 补 `--run-root`/`--rearm-sentinel`、
  `discipline_reminders`/`stage_flow_files`/`stale_fanout` 三个恒存在 stdout 字段、t1 单元口径
  真值表、哨兵双向违例与 t3 审计、`--invalidate-stale` 新语义;`step-manifest.md` Step→IO 表
  scout/t1/t2/t3 四行按实态纠偏(fanout_runner 派发优先、scout 补 extra_invocations,失同步
  约 7 周);`tests/test_list_steps.py` 新增契约表↔实现同步回归断言防再漂移。
- 新增回归 17 条先红后绿(`test_resume_state` 12 + `test_list_clusters` 2 + `test_list_steps` 1,
  另断言翻转 2 条:done 步 stage_flow_files 由 `[]` 翻为 done.md 路径)+ harness 增 SystemExit
  捕获助手;定向面 6 文件全绿(resume_state 80 / list_clusters 27 / list_steps 13 /
  list_scout_batches / zero_deps / no_compile_warnings);contracts 465 flag / purity 328 文件 /
  budget 17 壳过,plain_language 输出与改前逐字节一致;实机抽查:真实物化器切 3 shard 全
  `.done` → step 收敛 t2 + `--check` 零孤儿误报;残缺 t1 + manifest → step=done/ resumable=false;
  manifest + 残留 `.active` → 新违例命中。

### Fixed — /mgh-sdr 文档/壳/契约面披露对齐 + launcher/describe 健壮性收口(M6/M15–M20/L9/L10 + L1/L2/M12/M13/L3,2026-10-13 评审) (0.1.67)

- **M6+L3 敏感目录物化与路径透传**:`sdr_context.py` 把解析后敏感目录对象物化为
  `<run-dir>/sensitive_catalog.json`(与 context.json 同步确定性单遍;stdout/context 新增
  `sensitive_catalog_path`;`--check` 增量校验物化文件存在 + shape,旧产物缺字段兼容),
  任务模板 `sdr-task.md` 检查基线路径组新增该文件只读路径(经既有 `{{baseline_path}}`
  槽位派生同目录文件名——**fanout_runner 占位符集零改动**,残留 `{{` 检查不触);launcher
  `_build_prompt` 删除目录对象内嵌与 `[:4000]` 静默截断、改只读路径指认(「逐字透传」声称
  恢复成立);三面 agent 定义 Input/判定纪律同步。修复前主路径 sensitive-data 维度永远
  拿不到项目敏感目录且无任何披露。
- **M18+L9 dimensions 披露对齐**:`pipeline.md` `--dimensions` 段改写为与三面壳同口径
  (收窄仅闭集校验 + manifest 记录,**不**进入评审单元任务消息;真正接线后恢复现文的备注
  留存);三面 agent 定义删「检查面 note 收窄维度」句(描述永不触发的机制),任务模板同族
  句一并改正;对照验收 grep 零残留。
- **M15 dsh SKILL launcher 披露**:补「launcher 仅 spawn opencode/claude 宿主,dsh-only
  部署直接走壳内路径」,同段等量精简(召唤语义/派发面引用同步收紧),token budget
  lint 过(4998/5000 贴顶)。
- **M16/M17 三面措辞对齐**:opencode/dsh 壳 step 3 超时不变式段对齐 claude 完整规范形
  (`--call-timeout-s` MUST 显式传且 < budget×0.8、`--stall-timeout-s`(≥60) MUST < call,
  宿主具体数值落调用行 720000/540/300),消除压缩括号注形绑定歧义;三面 agent 判定纪律
  统一 claude 精确散文形,opencode 面删运行时永不替换的 `{{ baseline path … }}` 字面占位符。
- **M19/M20 契约文档补全**:`pipeline.md` 三处字段清单按脚本实际产出逐项核对补全——
  diff_group `pending[]` 补 `slimmed/chain/baseline_path/external_dir`;sdr_context stdout 补
  `base/branch/effective_baseline_budget/baseline_truncated_bytes/pending_approval[]/`
  `sensitive_catalog_path` 与 `external_repos[]` 完整 item 形;render manifest `counts` 补
  `findings/excluded_files`;run 目录布局/`--summary`/`--check` 行同步。`runtime-enforcement.md`
  补 sdr 哨兵确定性生命周期六步(预武装 → co-write → launcher 二次闸门刷新 → re-arm →
  存在性校验 → 完成移除),Authoring 行改「两个已落地确定性写入器」(`read_roots_config
  --add` 与 `sdr_context --approve-external` 共享同一原子写实现),target 来源清单补
  sdr_context stdout `repo`。
- **L10 壳参数表转发槽位**:三面壳 step 2 调用行与示例块补 `--max-standalone-bytes`/
  `--max-interface-bytes`/`--include-excluded` 槽位(示例块补默认值 65536/262144,
  contracts lint 465 flag 全过——此前三 flag 仅参数表声明、无任何转发面)。
- **L1/L2 launcher 健壮性**:空 `try/finally` 死代码外壳删除(哨兵生存语义**零变化**——
  异常路径 NEVER 一律移哨兵,运行中 run 不失守,残留经恢复入口检出/下次启动复用);
  sdr_context stdout 消费(`json.loads` + 字段下标)包 `_UpstreamOutputError` →
  per-branch FAILED(stderr 原因、多分支清单继续后续分支、退出码语义不变、非 traceback);
  新增回归 3 条(单分支错形 FAILED 不崩且残哨保留 / multi-branch 首分支错形后续分支照常
  跑完整流程 / 空 JSON 对象同形 FAILED)。
- **M12/M13 describe_artifact 健壮性**:`--field` 列表索引守卫从 `isdigit()` 预判改
  try-int(`isdigit` 收 `²`/`٥` 而 `int()` 拒收的 traceback 面消除,畸形段优雅退出 1);
  补全族最后一个缺的控制台 utf-8 reconfigure 块(与兄弟脚本同形——`ensure_ascii=False`
  中文值在 cp936 控制台即崩);新增回归 3 条(unicode 数字段优雅报错 / 负索引不崩 /
  中文值正常输出)。
- **卫生(零行为变化)**:`resume_sdr_state.py` STEPS 死常量与 `_resolve_repo` grp 死参数
  删除;`sdr_tier.py` probe 失败原因如实区分(`MGH_CODEGRAPH_BIN` 指向陈旧路径 vs PATH 无
  binary,不再统一报 "no binary";断言翻转 1 条);`mgh_sdr_launch.py` 函数内重复
  `import os` 收敛模块头。
- 回归:新增 11 条先红后绿(test_sdr_context 4 + test_mgh_sdr_launch 4 +
  test_describe_artifact 3)+ 断言翻转/扩充 2 条(sdr_tier probe 理由、summary projection
  字段集);定向面全绿(sdr_context 51 / launch 33 / describe 11 / sdr_tier 11 /
  resume_sdr_state 35 / list_sdr_steps 9 / failure_chain 2 / distributed_md_purity 30 /
  dsh_command_surface 6 + zero_deps / no_compile_warnings);contracts 465 flag /
  prompt_budget 17 壳 / purity 326 文件过;plain_language 输出与本 change 改动前逐字节
  一致(exit 2 系四个其他活跃 change 的 proposal 缺人话序,先前已存在、非本 change 引入)。
  specs 同步 security-design-review 1 MODIFIED + 2 ADDED requirement。

### Fixed — /mgh-sdr 外部仓受控检索层六缺陷收口(H6/M8/M9/M10/L4/L5 + read_roots_config L11,2026-10-13 评审) (0.1.66)

- `core/scripts/sdr_context.py` 单文件收口,先红后绿:**H6** 外部仓结论目录键从裸
  basename 改 `basename + "-" + sha8(resolved 路径前 8 位十六进制)` 消歧形态——两个
  同名 basename 的已批准仓(projA/front 与 projB/front)不再共享同一结论目录互相
  覆盖(前仓人读证据不可恢复丢失、记录指向他仓内容、`--check` 仅存在性检查照常
  放行);声明去重键同步改 resolved 字符串,同一仓含 `..` 的变体写法去重为一次
  检索一份结论(此前双倍检索 + 同目录错配)。**M8** 目录跳过判定不再看绝对路径
  全组件——遍历只发生在仓内,外部仓祖先目录名叫 build/dist(如 `D:\ci\build\front`)
  不再把整仓误跳成静默假零(「前端是否引用新路由」信号曾被无声否定);仓内真实
  `build/` 目录照常跳过。**M10** 每仓遍历从「每个声明配置名一次无剪枝 rglob(≤5 次)
  + 一次 `rglob("*")` 出现计数」最多 6 遍全树 I/O 改为单遍 `os.walk(topdown=True)`:
  `dirs[:]` 原位删除 skip_dirs 实现下钻前真剪枝(.git/node_modules 不再被枚举),
  配置命中与文本收集一趟完成;dirs/files 排序保证幂等重跑产物字节一致;路由出现
  计数逻辑(`_new_routes` 正则 + 类级 base 拼接)零变化。**M9** 实际生效的
  `--baseline-budget-bytes` 写入 `context.json` 新增 `effective_baseline_budget`
  字段,`--check` 基线尺寸断言按记录值判定(字段缺失/错型按默认预算向后兼容,旧
  产物不误报)——合法调大预算的运行不再被硬编码「默认值 ×4」误否决成 exit 2。
  **L4** 同名分支缺失的回退归因改「回退当前检出分支」(如实描述实际行为;否决探测
  origin/HEAD,不引入远端/网络依赖与不确定分支语义)。**L5** 外部路径候选提取排除
  含 `://` 的 token,存量文本里的 GitHub URL 不再被盘符 regex 切出
  `not-found: s://github.com/...` 伪条目噪声。
- `core/scripts/read_roots_config.py` **L11**:配置目录 `mkdir(parents=True)` 挪进
  受护写块,`.mgh` 已作为文件存在时从裸 traceback 改为 stderr 人类诊断(含 recipe)
  + 契约退出码 1,零行为语义变化。
- 回归:新增 10 条先红后绿(test_sdr_context 9 条:同名双仓独立结论+证据各指其仓/
  `..` 变体去重单检索/祖先 build 不误伤+仓内 build 照常跳过/剪枝目录零读取+结果
  对拍+幂等字节一致/大预算 check 过/字段驱动判定/旧产物缺字段兼容/回退归因串/
  URL 候选排除;test_read_roots_config 1 条:`.mgh` 为文件 → 诊断+退出码 1 非裸
  traceback),断言翻转 1 条(stderr 逐仓行按新 slug 形态改正则);修复前 8 红,
  修复后定向面 47+17+13+1 测全绿,授权/fail-closed 面既有用例零改动通过;
  contracts 459 flag/purity 330 文件过;specs 同步 1 条 ADDED requirement(外部仓
  检索物化与过滤的正确性)。

### Fixed — fanout_runner 派发器七缺陷收口(M4/H5/M1/M2/M3/M5/L12,2026-10-13 评审;六域共用基座) (0.1.65)

- `core/scripts/fanout_runner.py` 单文件收口,先红后绿:**M4** 限流截断竞态——
  补位循环 pop 之后、`pool.submit` 之前复查截断旗标,命中即丢弃本次提交(单元留
  磁盘 marker 语义待 `--resume`),「取单元→提交」窗口不再越过已生效旗标;
  `TestRateLimitStorm` 连跑 5 次全绿。**H5** `_pid_cmdline` Windows 分支改
  「wmic 先试 + PowerShell CIM(`Get-CimInstance Win32_Process`,单次超时 + 确定
  性解析)回退」——wmic 已于 Win11 24H2+ 移除,探测恒空串曾致 `--kill-stale`
  永远零杀却照删证据文件、退出码 0 假成功;现 PID 存活但两种探测均不可用 →
  fail-loud(退出码 2 + 手工探测 recipe)、不删任何 liveness 文件;
  `removed` 非空 ⇒ `none:false` 对齐 spec。**M1** 退出摘要与 sidecar 的
  `failed` 计数改 `max(磁盘快照, 起始 + 本 run 写入)`(双源相加曾把全败 10 单元
  报成 20;`--retry-failed` 决策与报告缺口披露消费该字段)。**M2** 活跃输出 sink
  经 `_UNIT_SINKS` 注册表接入 `_run_unit` reader 线程(`_run_unit` 9 参调用形
  冻结不变,注册→claim 同线程顺序),心跳 `idle` 恢复「距子进程真实末字节的
  秒数」承诺语义(此前读从未接线的死副本,持续输出的健康单元恒显示「疑似
  卡死」);心跳行字段名与 stdout 契约零变化。**M3** plan-path 再锚定逻辑前移
  到 kill-stale 分支之前、扫描根改 `plan_path.parent`(sdr 目录形 `--repo`/
  t2 `--init-dir` 曾按朴素父目录推断扫到仓父目录/仓根报 `none:true`,而
  liveness 实际在 run 目录);scout/t1/t3 文件形参数行为不变。**M5**
  `--checkpoints/--inputs-dir` 改可选(默认 None;kill-stale 恢复模式下二者仅
  是扫描提示),仓内全部恢复配方原样可跑(此前 `--inputs-dir` argparse 必填,
  配方退出 2);非 kill-stale 路径缺参仍走闭集校验可操作报错(t2/scout-merge
  `required_args` 补 `checkpoints`,派发行为与原必填逐字等价);零锚定 → 诚实
  空结果 + stderr 提示。**L12** liveness 读回包 try/except,写失败(契约声明仅
  警告)后读回失败就地重建 body,只读 run 目录不再整 run traceback。新增回归
  13 条(test_fanout_stale +10:wmic 缺失 CIM 回退分类/CIM 失败模式/探测全不可用
  证据保全/removed⇒none:false/sdr 与 t2 扫描根锚定/配方省参可跑/零锚定空转/
  读回重建;test_fanout_runner +3:failed 单计(摘要+sidecar)/sink 注册表 claim
  与滚动/未注册私有 sink);定向面全绿(fanout_runner 160 / fanout_stale 29 /
  zero_deps / no_compile_warnings),contracts 459 flag / purity lint 过;
  VERSION 0.1.65

### Fixed — /mgh-sdr 报告渲染器缺陷收口(C3/H1/H2/H3/M11/L7/L8,2026-10-13 评审) (0.1.64)

- `core/scripts/render_sdr_report.py` 单文件收口,全部先红后绿:**C3** `_href_of`
  相对路径补「首段含冒号即放弃链接化」双判定点(入口原始值 + 归一后最终 rel)——
  `javascript:` 载荷(无空格无圆括号)曾原样进入 `<a href>`(normpath 把 `//` 折叠
  为 `/` 而 WHATWG 对特殊 scheme 容忍单斜杠,载荷存活)、`C:foo` 盘符相对路径曾成
  坏链接;canonical 数据字段原样保留(只不做链接,不删数据)。**H1** `_merge_findings`
  severity 取值单点守卫(`isinstance(sev, str) ∧ 闭集内`否则落 `medium`,stderr 一次
  性提示)——severity 为 list/dict 曾致渲染与 `--check` 双路径裸 traceback(退出码 1,
  违约 0/1/2 契约)。**H3** `_json_embed` 转义链追加 `<!--` → `<\u0021--`(parse
  等价)——草稿引述含 `<!--<script>` 时 HTML 解析器曾进入 script-data-double-escaped
  状态,真 `</script>` 被忽略、页面渲染 JS 全被吞成空白壳,且 `--check` 的 regex 取块
  恰停在浏览器忽略的同一终止符上(exit 0 校验盲)。**H2** 「跳过 failed 单元」谓词
  提取为单一具名判定 `_is_failed`,前端两列的行侧改「过滤后 zip」与建 rows 同源——
  曾对全量单元 zip,从首个 failed 单元起整体错一位(一列残留占位「—」、其后每行
  继承**前一单元**的前端值,错误数据写进 manifest/data/HTML 三载体、`--check` 同错
  检不出)。**M11** `_frontend_pair` 子串包含改精确等值——REST 嵌套路由
  (`/api/user` 与 `/api/user/list`)曾把短路由的命中算到长路由头上(「无前端使用」
  标成「有」,方向性误导)。**L7** 删页面 `escapeHtml` 死函数,失实注释改为如实陈述
  (全程 textContent/setAttribute,无字符串级拼装)。**L8** `--check` 恒假守卫
  (构造方式决定永假的「manifest 须在 run 目录」)改为真实校验 `manifest['report']`
  落在 repo 根内(repo 根取 grouping.json,缺则按 `<repo>/.mgh-sdr/runs/<ts>` 形态
  推导;均缺则跳过不误伤)。
- 测试:`tests/test_render_sdr_report.py` 新增 9 条回归 + 1 条断言翻转(scheme/
  盘符相对 href 载荷、scheme finding 端到端降级且数据保真、severity 错型单元级 +
  端到端双路径、敌意 `<!--<script>` 引述端到端、failed 单元前端两列对齐三载体一致、
  嵌套前缀路由双向精确 join、report 指向仓外 exit 2、escapeHtml 缺席)。修复前
  10 条全红、其余 40 条既有用例全绿不受扰。
- 版本:VERSION 0.1.64。

### Fixed — /mgh-sdr diff 解析层缺陷收口(C1/C2/H4/M7/L6 + sast 侧 M14,2026-10-13 评审) (0.1.63)

- `core/scripts/diff_group.py`:**C1** `_git` 封装单点注入 `-c core.quotePath=false`
  ——git 默认把非 ASCII 路径输出为引号八进制转义形,解析器不识别导致整文件从分组/
  `excluded` 计数/`empty` 判定中静默消失(唯一变更时报 `empty:true` 退出 0,与真零
  diff 不可区分);**C2** `_split_interface_budget` 贪心分支去掉 `_fill` 外层
  `else`——「开启新 part 的成员」hunk 曾落入零个 part 且 absorb 已记 claimed(残差
  兜底不再接住,双重静默丢失);**H4** `_safe_name` 清洗集 `/ \ :` 扩为 NTFS 非法字符
  闭集 `/ \ : * ? < > | "`(`@GetMapping("/**")` 曾致 Windows 写盘裸
  `OSError [Errno 22]`,违约 0/1/2 退出码契约);**M7** A 文件 hunk 归属从「每符号」
  量纲改为「每 hunk 覆盖全部符号」+ 消费端兼容 list 形(新增 controller 整文件单
  hunk 时路由分簇曾坍缩);**L6** `--limit` 负值由静默 clamp 空页改为退出码 2 +
  可操作报错,`--check` 与互斥旗标(`--base/--branch/--offset/--limit/--summary/
  --include-excluded`)同传时 stderr 逐个显式提示被忽略旗标(退出语义不变);卫生:
  删死 import(`os`/`shutil`)与 `raw_text` 死参数链。
- `core/scripts/diff_seed.py`(sast 侧):**M14** `git diff --name-status` 加
  `-c core.quotePath=false`(与 C1 同族同修法,非 ASCII 源文件曾因引号尾粘连扩展名
  匹配失败而静默漏出 seed);`SOURCE_EXT` 去重(重复 `.ts`);`deleted[]` 与
  `seed[]` 同权适用源码扩展名过滤。
- 测试:`tests/test_diff_group.py` 新增 7 条回归(中文路径进分组 / 中文路径唯一变更
  非 empty / `/**` 路由 Windows 写盘 + 路由串保真 / 新增 controller 单 hunk 分簇不
  坍缩 / 贪心拆分「各成员单独 ≤ cap、合并 > cap」hunk locator 并集无损 + part 路由
  标签与装载成员一致 / `--limit` 负值拒绝 / `--check` 同传旗标提示),原两成员单独
  超限用例保留、贪心分支盲区以独立用例补齐;新增 `tests/test_diff_seed.py`(非
  ASCII 源文件进 seed、deleted[] 同口径)。全部先红后绿。
- 版本:VERSION 0.1.63。

### Added — /mgh-sdr 全流程深度代码评审报告落盘(根概览 + docs 明细;3 critical + 6 high,均实机验证) (0.1.62)

- 新增根 `mgh-sdr-review.md`(概览:严重度统计、流水线缺陷落点 mermaid、修复顺序建议
  与分组选项对比、修复后定向测试映射)与 `docs/review-mgh-sdr-pipeline-2026-10-13.md`
  (24 文件逐条明细:位置/影响/修复建议/复现验证/健康面确认清单)。按
  open-code-review-delegate 流程执行(ocr 规则分组 + 6 批 subagent 逐文件全读 + 4 组
  独立二次验证 subagent,覆盖率 24/24 零 skipped)。发现:3 critical(quotePath 引号
  路径中文文件整文件静默丢失 / 超预算贪心拆分丢「开启 part 成员」的 hunk / 报告
  `<a href>` 的 javascript: scheme 注入)+ 6 high(render severity 错型双路径崩 /
  failed 单元前端两列 zip 错位 / `<!--`+`<script` 双转义吞页 JS 且 --check 盲 /
  NTFS 非法字符致 Windows 写盘崩 / wmic 于 Win11 24H2+ 移除致 --kill-stale 全盲且
  销毁证据 / 同名 basename 外部仓结论互相覆盖)+ 20 medium + 12 low;9 条
  critical/high 与限流截断竞态(本机回归测试确定性红)全部独立复现确认,零整体误报。
  仅文档零代码改动;作为后续修复 change 的工作清单。

### Added — /mgh-init 全流程深度代码评审报告落盘 docs/(1 critical + 14 high,均实机验证) (0.1.61)

- 新增 `docs/review-mgh-init-full-pipeline-2026-10-13.md`:对 /mgh-init 全流程(壳三面 /
  agent 16 / 脚本 20 / 契约 18 / 提示词 40,共 97 文件)的全量文件评审(非 diff)明细,
  按 open-code-review-delegate 流程执行(ocr 规则分组 + 12 批 subagent 逐文件全读 +
  7 个二次验证 subagent,critical/high 全部含实机复现或代码级复核)。含按优先级排序的
  修复工作清单、1 critical(resume 状态机对分片簇死锁)+ 14 high(守卫 redirect 四域
  放行 / stdin GBK 休眠 / kill-stale wmic 失效 / 分发死链等)+ 68 medium + 19 low、
  二次验证校准记录与经核验无问题面。仅文档,零代码改动;作为后续修复战役的输入。

### Changed — 顶级文档重写(命令/宿主优先级、用户画像、过时信息清理)+ install 默认宿主改 opencode (0.1.60)

- **顶级文档重写**:根 `README.md` 与根 `AGENTS.md` 按当前产品形态重写——命令优先级
  (init/sdr 为主力,排在前)、宿主优先级(opencode → dsh → claude)、AGENTS 新增
  「用户画像与设计目标」对照表(内网弱模型/频控/大仓/银行级安全要求 → 各研发铁律的
  必然推论);README 新增「适用环境」与 sdr/ut-init 章节,删除与命令 `--help` 重复的
  全量 flag 表。过时信息清理:命令表补 `mgh-ut-init`、删除已失效的 `task.260630.md`
  引用、「详见 openspec/changes/add-mgh-*」死链改为 `openspec/specs/` 能力规格指针、
  守卫运行域五→六(补 `MGH_SDR_ACTIVE`)、R5.6/R5.8/R5.9 与实测对齐(token 预算 lint
  已落地;全量回归 66 文件/1546 测)、R5.9 `--check` 覆盖清单补全 sdr/ut-init。
- **install 默认宿主 claude → opencode**:`install.sh` 与 `install.ps1` 不带宿主 flag
  时默认安装 opencode 面(与宿主优先级一致);显式 `--claude|--opencode|--dsh` 行为
  不变,幂等性不受影响。
- **可参考项目恢复(条件存在口径)**:superpowers / OpenSpec / codegraph /
  deepseek-harness 四个参考仓路径保留在 AGENTS.md,口径改为「路径存在时才参考其源码,
  不存在跳过、NEVER 找」。
- **sdr man 页报告口径更新**:`docs/man/mgh-sdr.md` 的人读报告描述从项目根 `.md` 更新为
  自包含单文件 `.html`(浏览器双击即读;机器读数据在 run 目录 `sdr_report_data.json`)。
- **AGENTS.md 减负(vvah 背景降级)**:整节删除「mgh-sast 与原项目 vvaharness 的关系
  (必读)」与 R4 迁移历史——`/mgh-sast` 已非功能主力,背景常驻每个会话只耗 token;
  mermaid 移植流向图与改名历史摘抄至 `docs/upstream-vvah-background.md`(维护者私有
  文档区,按需查阅),逐项映射权威仍在 `docs/upstream-index.md`;R4 编号保留空缺
  (防 R5.x 引用重排),仍有效的两条操作性事实(工具脚本从仓库根运行 / extract_prompts
  默认路径)留在 R4 存根。
- 杂项:`docs/glossary.md` 补 3 条(切片 `--scope` / mgh-core / 零参执行);根 `CLAUDE.md`
  规则枚举补 R5。

### Fixed — /mgh-sdr 多分支 sweep 六缺陷:失败探针早败、报告按分支认领、spawn 环境卫生、可诊断性、守卫通配误拦 (0.1.59)

多分支真仓验证战役(findings 2026-10-12)暴露的六个产品缺陷一次收口:

- **分支存在性预检(修「不存在分支烧一轮 LLM 还被标成功」)**:launcher 对每个待跑分支
  在**任何副作用之前**(run 目录 / 哨兵 / 提示词 / 宿主 spawn)先 `git rev-parse --verify`
  预检;不可解析 → 该分支确定性早败(零 spawn、零 LLM、零产物),记 FAILED 后后续分支
  照常;真跑与 `--dry-run`、单分支与 `--multi-branch` 同一预检——dry-run 由此获得对清单
  的真实校验力(含无效分支 → 退出 1,不再假绿)。
- **报告认领以本分支 run 目录 manifest 为准(修跨分支产物污染)**:宿主退出 0 后只认
  `<run-dir>/sdr_manifest.json` 的 `report` 字段(渲染器同一事务原子写);manifest 缺失或
  报告文件不在盘 → FAILED(no-report);「仓根最新 `mgh-sdr-*.html` glob」整体删除,跨分支
  认领在结构上不可能。退出码 1 的覆盖面随之扩为:分支不存在 / sdr_context 失败 / 宿主非零
  退出 / 退出 0 但未产报告。
- **spawn 环境卫生(修 opencode 会话全落错项目)**:spawn 宿主 CLI 时剥离子进程环境中的
  `PWD`(opencode 按 `PWD ?? cwd` 解析项目归属);从任意非目标仓 cwd 启动,会话都落在
  launcher 显式传入的 cwd = 目标仓。
- **可诊断性 + `--model` 透传(修失败现场只有一句错误信封)**:opencode spawn 固定追加
  `--print-logs --log-level ERROR`(provider 形失败在 launcher stderr 可定位);launcher
  新增 `--model <provider/model>`,两宿主同名透传、未传不附加——替代手改项目级
  opencode.json 的环境绕行。
- **守卫通配 token 归一(修「仓根找报告」合法命令被误拦)**:Bash 分派入口单点归一——
  引号闭合绝对路径后紧邻的 glob 段剥引号拼为单 token(`ls "<target>"/*.html` 不再把
  `/*.html` 碎片按盘符根解析);含 `*`/`?` 的 token 按首个元字符前的前缀判属。文件搜索 /
  目录列举 / 兜底净网三判定共用归一后 token 流;树外前缀与 `..` 越树前缀照旧拦截。
- **发布面**:三端守卫拷贝同步(core canonical = claude = opencode,字节级 parity);
  `VERSION` bump。

诚实边界随动(AGENTS.md):通配按**去通配前缀**判属,glob 展开结果不判定(与
regex-over-string 立场一致);别名/变量间接照旧不可见。渲染器 / 分组 / fan-out 零变化;
三面命令壳零变化(壳未逐字枚举 launcher flags,契约面在 launcher `--help`)。

### Changed — 简报表调用链两级显示 + 扩展维度中文列头 (0.1.58)

真仓首跑(springBootTemplate,8 单元 / 23 findings)反馈的阅读性迭代:

- **调用链两级显示**:主链(入口 → 流转 · 同类延续)保持正常字号不缩进;分支(`⤷`)与
  mapper 终端(`⇢`)段整体落入缩进、小字号、左侧竖线的子块,按段换行不拆节点——长链
  (真实项目二十余节点的常见形态)从一条平铺长行变为主次分明的两级结构。段序与字形不变,
  自上而下阅读即纯文本链逐字还原;数据文件与 manifest 完全不受影响(纯视图层分组)。
- **扩展维度列头中文**:自由扩展维度是 fan-out 任务的 sanctioned 行为,真仓出现的
  `architecture-layering` 在列头与问题详述标题显示中文名(架构分层);渲染器内置已见扩展
  维度的标签表,未见扩展维度回退显示原始键。数据面始终保存原始键,机器 join 不变。

### Changed — sdr 评审报告从 Markdown 换成自包含单文件 HTML:数据/呈现分离,阅读体验归浏览器 (0.1.57)

`/mgh-sdr` 的评审报告此前是 `.md` 文件:读者必须装 Markdown 阅读工具,简报表里的 P-NN
编号不能点击跳转(目标编辑器不支持内部锚点,规格为此明令禁止锚点),调用链图用 mermaid
语法、呈现质量取决于编辑器插件。本次把「人读呈现」从编辑器限制里解出来:

- **报告形态**:`<repo>/mgh-sdr-<分支>-<时间戳>.md` → **同名 `.html` 自包含单文件**
  (样式/脚本/数据全内嵌,零外部引用,file:// 双击即读、离线可用)。**BREAKING**:报告
  扩展名与格式变更;历史 `.md` 报告不迁移不回写。
- **canonical 数据文件**:新增 `<run-dir>/sdr_report_data.json`——报告全量结构化数据,
  与 HTML 内嵌数据块由构造保证同源,`--check` 校验 JSON 等价;下游确定性消费(未来
  /mgh-blst、报告 diff 工具)以它为接口,NEVER 去解析 HTML。
- **章节三调用链图**:mermaid → 渲染器确定性生成的**内嵌 SVG**(分层布局 + 正交折线,
  mapper 终端虚线边、未变更节点 `†` 前缀保留),页内滚轮缩放、拖拽平移;mermaid 依赖归零。
- **简报表可交互**:severity/维度筛选(纯视图态,不改写数据文件)、P-NN 页内锚点跳转;
  链节点与问题位置渲染为仓内源文件链接(部分浏览器对 `.java` 等扩展名可能下载而非打开,
  报告诚实边界披露)。
- **随动**:launcher `mgh_sdr_launch.py` 新增 `--open`(默认 off,跑完自动开浏览器);
  三面命令壳、sdr 契约、`list_sdr_steps` render 步 path_pattern 同步;`--check` 扩展
  (数据文件存在可解析、与内嵌块 JSON 等价、`.html` 结构标记断言,违例退出码 2)。

诚实修正:本次**不减少 LLM token**——fan-out 侧本来就是「子代理只写 JSON + 脚本确定性
渲染」,报告正文从不花 token;真实收益是阅读体验与数据/呈现分离。渲染器 CLI 形状、
manifest schema、fan-out 契约零变化;`resume_sdr_state.py` 渲染判定键(`sdr_manifest.json`
存在)不受扩展名切换影响。

### Changed — scout 候选聚合从「超界照发」变硬预算:96KB 默认、候选粒度装箱、dispatcher 波次派发 (0.1.56)

`/mgh-init` 的 scout-merge 聚合节点此前是软边界:输入超预算时靠提示词自律「回 `oversize`
再手工翻页扇出」，且默认预算 256KB 对内网 ~150K token 窗口(最坏 ~2 bytes/token)偏大。
本次把它升级为与 T2 综合同构的**硬预算闸门 + 波次派发**：

- **预算收紧**:聚合默认预算 256KB → **96KB**(`plan_aggregate`/`write_runconfig`/
  `write_ut_runconfig`/`render_report` 同名默认一致，`check_contracts` 断言)。
- **硬界装箱**:`plan_aggregate --node scout-merge` 改为**候选粒度稳定序贪心装箱**(物化
  文件 ≤ 预算由构造保证);病态单候选确定性瘦身投影(只截 `evidence_snippet`/`snippet`/
  `entry_points`，去重锚点等结构字段永不截，原 checkpoint 不回写);瘦后仍超 → 退出码 2、
  零物化零派发(旧「warn + 照发 oversize」路径两节点同退)。
- **dispatcher 接入**:`fanout_runner --tier scout-merge`(map 段波次 + marker-aware 重列
  + 四级超时/熔断/冷却全部复用);新增 `init-scout-merge-partial`/`-rollup` 两级 stage
  提示词与 opencode/claude/dsh 三面 agent 定义;手派路径降级为退出码 2 回退。
- **接线**:scout fragment 段重写为 dispatcher-first、三面壳组件表/tier 清单、
  `list_steps --step scout` 增 `extra_invocations`、`discipline_core` 三条新 recipe、
  `gen_dsh_tiers.REQUIRED_TIERS`、install 自检清单。

### Added — dsh subagent fan-out: the dispatcher grows a third host, stage delegation rides named tool instances, and the five shells retire their degradation blocks (0.1.55)

Route A's closing piece. `fanout_runner.py` now spawns dsh headless children:
`dsh --profile mgh --patch <mgh-core>/dsh/tiers/<tier>.yml -` with the task text riding
the child env `MGH_TASK_TEXT` (measured spike overturned the spec's stdin assumption —
headless has no stdin task channel, and multi-line argv dies at the first newline of the
npm `.ts` shim; the maintainer approved the env channel). Host auto-detection appends
`dsh` LAST (opencode > claude > dsh — dual-host machines see zero behavior change), and
an explicit `--host` always wins. Before any dsh spawn the dispatcher gate-asserts the
tier mount file and the `mgh` profile dir exist — missing = exit 2 + regenerate recipe,
zero spawns. Stage prompts no longer ask subagents to guess `.opencode` vs `.claude`:
the four init templates carry one `{{mgh_core}}` placeholder the dispatcher fills from
its own install position.

- **Third-dialect agent source → compiled mounts**: `releases/dsh/agents/` holds one
  definition per fan-out tier (scout/t1/t2/t3/sdr) and per interactive stage
  (8×`sast-*` + 3×`sra-*`); `tools/gen_dsh_tiers.py` compiles tiers to
  `<target>/mgh-core/dsh/tiers/*.yml` and a named-delegation patch fragment, `--check`
  giving the deterministic 1:1 mounts↔definitions assertion install runs fail-loud.
- **mgh profile = sole composition face**: `tools/create_dsh_profile.py` creates the
  skeleton (base+headless bundles, add-only, foreign package.json = collision
  fail-loud, user profiles never touched); `install_dsh_wiring.py --delegates-file`
  composes the managed block = guard shim ∪ timeout policy (`enableRunInBackground:
  false`, closing the background-job channel) ∪ 11 named delegate tools (persona loaded
  at build time, `toolFilter` built in). The old "sole existing profile / --dsh-profile
  any name" inference is gone — a non-mgh name now fails loud (wrong profile = wiring
  nothing). `install.sh`/`install.ps1 --dsh` wire all of the above idempotently.
- **Shells**: the five dsh shells drop change 2's fan-out degradation blockquotes;
  sast/sra/srr dispatch wording picks the named instances verbatim
  (`mgh_sast_deepdive`, `mgh_sra_clarify`, …), sdr/init disclose the now-wired tier
  dispatch, and mgh-init honestly keeps a residual-degradation note for the interactive
  init stages (survey/resolve/scout-merge/T4 have no named instances in this change).
- **Contract**: `core/contracts/fanout/runtime.md` registers the spawn shape, tier
  mounting, timeout levelling (dsh terminates on timeout, matching the shipped
  kill-and-redispatch contract), coarse per-plugin tool whitelist (host capability
  boundary), and the provider precondition (install self-check proves CLI presence,
  not end-to-end runnability). Pinned to dsh 0.1.5-rc.2.
- **Tested**: `test_fanout_runner::TestDshHost` (spawn-shape snapshots, env-channel
  byte fidelity incl. CJK/quotes, precheck gate through the real `main()` with zero
  spawns), `test_fanout_stale` dsh cmdline kill form, `test_gen_dsh_tiers`, and
  `test_install_dsh` end-to-end (tiers+delegates land, mgh profile wired, user profile
  untouched, reinstall byte-stable, non-mgh name rejected).

### Added — dsh command surface: five user-invocable skill shells, three-face lints, and the sra/srr shard-to-fit that paid off the legacy token debt (0.1.54)

Change 1 gave dsh a guard; a guard with no commands is a locked door with no hallway.
This lands the command carrying surface: each `mgh-*` orchestrator shell ships on dsh
as a project-scoped skill (`<target>/.dsh/skills/mgh-<name>/SKILL.md`, kebab-case
`user-invocable: true` + `disable-model-invocation: true` — user slash-invocation only,
the model cannot self-trigger orchestration), a verbatim mirror of its claude/opencode
siblings except a closed five-class dialect whitelist (frontmatter / invocation
semantics / execution-boundary disclosure replacing claude's `allowed-tools` / tool-name
spelling / host mechanism facts rewritten per dsh's verified behavior — dsh *does* batch
questions via `ask_user_question`, its shim *does not* inherit mid-session env, its
tool calls *do* take a per-call ms `timeout`). Fan-out steps carry an honest D4
degradation blockquote (stop at the dispatch step, report disk-resumable progress) until
change 3 wires subagent dispatch.

- **Three-face lints**: `check_contracts.py` now extracts `*.py --flag` from all 17
  shells (459 flags asserted against `--help`); new
  `tools/check_distributed_prompt_budget.py` asserts every orchestrator shell body
  ≤ 5,000 mid_tokens; purity lint's scan set gained `releases/dsh/skills`; new
  `tests/test_dsh_command_surface.py` pins frontmatter shape, `mgh-core/`-rooted asset
  references, and lazy-fragment pointer resolvability.
- **Shard-to-fit (maintainer-approved, faithfulness-first)**: the lint exposed
  pre-existing debt (claude sra 5460 / srr 5148, opencode sra 5101, dsh sra 5223 /
  srr 5013 mid_tokens). The `## Orchestration flow` sections of mgh-sra/mgh-srr moved
  **verbatim** into six lazy fragments (`core/prompts/fragments/{sra,srr}-flow-
  {claude,opencode,dsh}.md`, ~1.7–2.2K tok each, loaded via `REQUIRED SUB-SKILL`), each
  shell keeping a skeleton pointer; all 17 shells now pass with zero content deleted.
  The two sra/srr codegraph parity tests now assert against shell + its own-face flow
  fragment (the stanzas moved verbatim with the section; discipline unchanged).
- **Install**: `install.sh --dsh` / `install.ps1 -Platform dsh` place the five skill
  dirs idempotently and self-check presence + frontmatter four fields + rooting
  (fail-soft at install, loud in CI via `test_install_dsh::TestDshSkillsInstall`);
  placement is NOT gated by `--no-enforce-hook` (shells ≠ enforcement).
- **Verified against dsh 0.1.5-rc.2 source**: skill bodies have no size cap (only
  catalog descriptions truncate) — design Open Question 1 closed, no truncation risk.
- **Pending**: subagent dispatch on dsh (change 3 `add-mgh-dsh-subagent-fanout` owns
  wiring it and deleting the D4 paragraphs); real-machine acceptance `/mgh-sdr` default
  run + guard interaction.

### Added — dsh becomes the third guarded host: pre-execute shim, bypass-tool coverage, `install.sh --dsh` (0.1.53)

The guard (`block_adhoc_scripts.py`) previously spoke to two hosts — claude via a
PreToolUse command hook, opencode via a `tool.execute.before` plugin. dsh
(deepseek-harness) had no wiring at all: its own `run_code` / `pwsh` / terminal /
background-job tools were complete bypasses around every discipline the other two
hosts enforce, and installing mgh into a dsh project meant trusting the agent's
self-restraint.

- **dsh shim (glue only)**: `releases/dsh/plugins/mgh-guard.ts` subscribes to dsh's
  `tools/pre-execute` waterfall, normalizes dsh tool ids onto the guard's canonical
  names (`pwsh`→`Bash`, `str_replace_editor`→`ApplyPatch` with paths extracted from
  the command payload, etc.), spawns the sibling `block_adhoc_scripts.py` with a
  one-shot stdin Buffer, and turns exit code 2 into `{kind:"deny", reason:<guard
  stderr>}` — the recipe text reaches the model verbatim. Interpreter fallback
  `py`→`python3`→`python`; no Python / guard crash / unmapped tool id ⇒ pass with a
  log line (fail-soft, never blocks day-to-day dev). Activation is the same
  env-or-disk-sentinel discovery as the other two faces (anchor = session-header cwd
  carried in the payload).
- **New guard branches (single decision source stays Python)**: `RunCode`
  (domain-active → deny + recipe pointing at the sanctioned leaf-script exit; shape
  only, body never sniffed) and `TerminalIO`/`JobCtl` (interactive-terminal /
  background-job bypasses → domain-active deny). `pwsh` needed zero new code —
  normalized to `Bash` it hits the existing verb tables + the rule-m path net
  verbatim.
- **Install dialect**: `install.sh --dsh` / `install.ps1 -Platform dsh` mirror the
  shim + a sibling guard copy into `<target>/mgh-core/dsh/` and wire them into a dsh
  profile's `cordis.patch.yml` through an idempotent marker-anchored managed block
  (`tools/install_dsh_wiring.py`; a stale block is replaced in place, the user's own
  entries never touched). dsh has no project-auto-discovery, so the profile layer IS
  the mount point. Missing `$DSH_HOME` / zero-or-multiple profiles → fail loud
  before any write; `--no-enforce-hook` mirrors but skips wiring.
- **Three-face wiring invariant**: the claude matcher, the opencode `HANDLED` set,
  and the dsh `TOOL_MAP` must all cover every guard dispatch branch — a new branch
  without all three faces extended now fails CI. Guard copies gained a core
  canonical (`core/scripts/block_adhoc_scripts.py`) with the claude/opencode/dsh
  siblings asserted byte-identical.

Verification: targeted hook-face tests (265 guard + 44 opencode-parity + 12 dsh-parity
+ 9 install-dsh + install-hook/plugin suites, all green); purity + contracts lint
green; live first-run on a real dsh session saw out-of-tree write/read denials,
`pwsh` out-of-tree write denial, and zero interference in a non-run-domain repo.

### Changed — /mgh-sdr accepts zero args as the highest-frequency invocation, and step 0 probes the Python interpreter once so no command ever guesses (0.1.52)

Two daily frictions stacked on `/mgh-sdr`. Zero args — "current branch vs master,
all 6 dimensions", the dominant real usage — hit the family STOP discipline and
demanded a parameter just to unlock a run whose defaults already live in the
scripts' argparse. And with `py` (Windows Python Launcher) hardcoded in ~30 shell
examples, any machine without it entered an "interpreter not found → rename and
retry" loop that burned one context round per miss.

- **Zero args = declared defaults**: `--help` still prints the table and STOPs
  (unchanged); no arguments at all proceeds with base=`master` / current branch /
  all 6 dimensions. On the default path the shell omits `--base`/`--branch`
  outright and never runs `git rev-parse` itself — the resolved `base`/`branch`
  come back in step 1 stdout, and the run directory is named `<ts>` only.
  R5.6 gained the matching exception: a shell may execute on zero args only when
  its parameter table annotates a default for EVERY entry (now machine-checkable);
  the other mgh-* shells keep the old STOP unchanged.
- **Step 0 interpreter probe**: one Bash command tries `py`, `python`, `python3`
  with `;`-separation and emits a `PYPROBE <name> OK|UNAVAILABLE` line for each —
  all candidates visible in a single call, chosen by rc 0 AND version ≥3.10 (the
  short-circuit `||` chain was rejected: it hides the remaining versions, and the
  Microsoft Store stub passes existence checks while failing at rc 49). The `py`
  in every example is a canonical token replaced verbatim by the selected
  interpreter; after a compaction or crash the orchestrator re-runs the probe
  (one cheap command) rather than guessing per command. The probe result never
  lands on disk (`run_config.json` / sentinel schemas unchanged); all candidates
  failing → clean stop before step 1 with the probe output disclosed.

Verification: contract lint (330 flags) and both shells' prompt budget (4572 /
4601 `mid_tokens`, ceiling 5000) pass; purity + plain-language targeted tests
pass; a no-`py` PATH simulation in a fresh clone probed once (selected `python`
3.13.2) and ran step 0 sentinel-arm → step 1 with no `--base`/`--branch` (stdout
resolved `base=master` / `branch=main`) → step 2 `--check` → sentinel removal
with zero per-command interpreter trial-and-error.

### Added — the /mgh-sdr orchestrator gets in-register exits for every failure-window temptation; the guard wakes BEFORE step 1 can fail (0.1.51)

One real `/mgh-sdr` run produced a four-action violation chain, and every action
SUCCEEDED: the orchestrator invented an approval flag `sdr_context.py` never had, then —
while the trial-and-error loop had the guard asleep (the sdr sentinel was only a step-1
*success* side effect, and opencode never inherits mid-session env) — parsed a producer's
stdout through a `python3 - <<'EOF'` heredoc, relayed 31KB of stdout through `/tmp` and
read it back, and finally processed the run artifacts with `py -c`. Three holes stacked: the approval
loop straddled two scripts (reporter vs writer), guard activation parasited on the success
path, and the sanctioned inspection exit (`describe_artifact.py`) was invisible to the sdr
shell until the guard itself recommended it in a block message.

- **The invented capability became real.** `sdr_context.py --approve-external <abs>`
  (repeatable) registers a user-consented root through the SAME validated atomic writer
  `read_roots_config.py --add` uses (direct import, design D1), retrieves it THIS run, and
  lands it in the sentinel `read_roots[]` — consent → approve → search closes in one
  command. Approval semantics hold: the flag is passed ONLY after explicit user consent in
  the host session; `--check` now WARNs (exit unchanged) when `pending_approval[]` is
  non-empty, so a skipped approval leaves a product-level trace.
- **Failed guesses route to exits.** An unknown flag whose name hits the
  `{approve, read, external, root}` word-roots now fails with argparse's native error PLUS
  a copy-pasteable two-line recipe (absolute self-path; the `--approve-external` form and
  the equivalent `read_roots_config.py --add` + re-run). Non-matching unknown flags keep
  argparse's exact native failure. `sdr_context.py` / `diff_group.py` gained `--summary`
  stdout projections (fixed-shape key figures; `external_repos[]` drops `route_hits[]`; disk
  artifacts byte-identical, same execution tail-projection, no new files) — the direct
  answer to the big-stdout → temp-file temptation; per-file retrieval stderr collapsed to
  one line per repo.
- **The guard is awake during the failure window.** `resume_sdr_state.py --arm-sentinel`
  (argparse-mutually-exclusive with `--rearm-sentinel`) writes the minimal sentinel at
  step 0 — target from `--repo` or the `<repo>/.mgh-sdr/runs/<ts>/` layout, same-target
  re-arm is a no-op that NEVER clears `read_roots[]`, different-target refuses to anchor a
  second tree. Step 1's success co-write still refines it. The shell's clean-stop step now
  carries the residual-sentinel `rm` line.
- **Heredoc/here-string closed on both faces.** `_PY_INLINE_RX` blocks interpreter + stdin
  `<<`/`<<<` by SHAPE alone (segmented on `;`/`&&`/`|`, no body-token sniffing — heredoc
  bodies are often invisible to a token gate); the `-c` path stays body-token-gated so
  benign `py -c` behavior is byte-unchanged; a bare `-` without `<<` stays a pass
  (minimal-interception surface, new shapes get added as real machines report them).
  Both guard copies stay byte-identical; the interception-surface wording expanded in
  lockstep across the fragment, both sdr shells and
  `core/contracts/hooks/runtime-enforcement.md` (three feed shapes, one phrasing).
- **Exits visible before the incident, enforced mechanically.** Both sdr shells now carry
  the exact `describe_artifact.py --in <abs> --keys/--field/--sample` recipes at steps 1/2
  plus the stdout-direct-consumption declaration; the launcher's pending-approval hint
  recommends `--approve-external` (equivalent path kept). A new `check_contracts.py` rule
  extracts every `\w+\.py` from the guard's `_WORKLIST`/`_recipe` text and fails the build
  (exit 2, per-domain `(domain, missing-script)` pairs) if a recommended primitive is
  absent from that domain's shells ∪ the shared fragment — the recommendation/visibility
  correspondence stops being a convention.
- **Verified**: the four real-chain actions固化 as an end-to-end replay in
  `tests/test_sdr_failure_chain.py` (invented flag → exit 2 + copy-pasteable recipe; the
  recipe transcribed verbatim closes approval + retrieval in ONE run; heredoc / `/tmp`
  relay / `py -c` all blocked exit 2 with `describe_artifact.py` in the recipe; a
  sentinel-only activation proves the opencode env-inheritance boundary is closed by disk);
  6 recipe-visibility cases incl. the reverse case (delete the fragment literal → lint must
  fail); targeted suites for every touched face + full regression green; contract lint
  covers the new flags (330 flags / 12 shells); purity lint clean; shells 4146 / 4175
  mid_tokens (budget 5000, no shard needed).

### Changed — the sdr report's three locate-points became clickable source-file links; unlocatable paths degrade to the exact old text (0.1.50)

`/mgh-sdr` reports solved "readable" (the chain short forms) but not "reachable" — a human
reviewing a suspicious hop had to hunt the class through the repo by hand, several hops per
finding, every review. The data was already on disk: chain nodes carry `file` + `line` from
grouping, and the report lands at the repo root, so a repo-relative path IS the link.

- **Three render points, one helper.** `render_sdr_report.py` gains `_source_link(text, file,
  line, repo)`, used by the 简报表 entry column (standalone method-def forms; route strings
  never link), every chain node, and the 章节二 position line — `[Ctl.submit](src/…#L42)`,
  anchor omitted when no line (mapper XML terminals are the natural case). Short-form
  construction and link wrapping stay two layers: `†` rides inside the text, `→`/`·`/`⤷`/`⇢`
  separators stay outside the link.
- **Purely lexical resolution, zero broken links by construction.** Absolute paths are
  rebased onto `--repo` (`normcase` absorbs the Windows case-insensitive drive); outside the
  subtree, empty/missing, leading `..`, or a path with spaces/parens → the plain-text form,
  byte-identical to the old report. The renderer NEVER stats the target (a diff branch's file
  may not be checked out; stat-based judgment would make the report depend on checkout state).
  Display-text `[`/`]` get minimal escapes; finding `line_hint` info is NEVER dropped to buy a
  link.
- **Machine surface untouched.** `sdr_manifest.json` `rows[].entry/chain` stay plain short
  forms (link wrapping is a render projection); the `--check` internal-anchor ban (`](#`)
  cannot misfire on `](src/…#L42)` — the `#` there is preceded by a path segment — now stated
  as a comment. The `P-NN` dimension columns remain pure text as decided.
- **Verified**: 11 new `_source_link` unit cases + a 3-unit end-to-end (anchored links,
  no-anchor mapper terminal, `†` inside the link, out-of-repo/empty-file degradations,
  manifest-vs-table equality after de-linking) in `tests/test_render_sdr_report.py` (29 tests);
  a springBootTemplate dry-run (grouping-only env + hand drafts, reused from the report-structure
  change) rendered 59 links, all targets present on disk, spot-checked anchors landing exactly
  on their method declarations, and a timestamp-normalised diff against the pre-change renderer
  confirmed the ONLY changed lines are the three render points (head / 章节三 mermaid /
  no-issue list / honesty boundary byte-identical). `--check` passes on both render outputs;
  contract and purity lints clean; command shells unchanged (they never carried the
  plain-short-form wording).

### Added — the sdr run domain gains a disk-derived resume surface; run-level state stops being an orchestrator recipe (0.1.49)

`/mgh-sdr` could already avoid redoing finished work (a `.done` unit is skipped, `--resume`
re-dispatches only what is missing, the renderer overwrites its own report), but it could not
answer **"which step am I on / what do I run next"**. After a crash, after a context
compaction, or in a fresh session the orchestrator had only the conversation to go on — and
the conversation is a cache, not a source of truth. `/mgh-init` has had the other half for a
long time (re-derive the step from the run dir, re-inject that step's defenses); sdr never got
it. Two related gaps came with it: the sentinel guarding the run was written by a shell recipe
the orchestrator had to read and execute correctly, and the run dir carried a start-state file
nothing consumed.

- **`resume_sdr_state.py`** — the single sanctioned outlet for the sdr reflex "where am I /
  what next". `step` is derived purely from `<run-dir>/` disk products (`context.json` /
  `grouping.json` / unit markers / `sdr_manifest.json`) over the closed set
  `not-started|group|fanout|render|done`, where the step name is the **current TODO step**.
  It never reads conversation memory and never guesses from a damaged product (an unreadable
  `context.json`/`grouping.json` exits 2 with a recipe). stdout carries `step`, `resumable`,
  `tiers`, `next_action{kind,desc,absolute_paths[]}` with verbatim absolute paths, `notes[]`,
  `discipline_reminders`, and a `stale_fanout[]` scan of leftover `fanout_runner.*.pid`
  liveness files. `--check` fail-louds on the states that matter; `--rearm-sentinel` rebuilds
  the guard sentinel deterministically.
- **Per-step discipline travels with the resume.** `discipline_core.get_discipline(step,
  domain="init")` gained a `domain` parameter and an sdr table (default domain output is
  byte-identical, so the existing callers are untouched). A resumed run is handed the same
  gates, path recipes (unit paths come from the enumerator's stdout, verbatim) and `NEVER`
  boundaries it would have had at the start — the defense line is re-injected from disk rather
  than remembered.
- **`list_sdr_steps.py`** answers the complementary question ("the exact invocation for any
  step") with zero disk preconditions, mirroring the init/ut-init siblings; its `--step`
  discipline is asserted byte-identical to `resume_sdr_state.py`'s for the same step.
- **One rule for unit identity.** New `sdr_tier.py` holds the forward marker-path predicate,
  imported by BOTH the writer (`diff_group.py`, which was concatenating marker paths inline)
  and the resume reader. A second copy of that concatenation is how "the enumerator says
  pending while the disk holds a marker" becomes an infinite re-dispatch loop. Marker paths are
  reproduced verbatim — no sanitizing or truncation is added, because the id is already
  sanitized when the unit is built and re-encoding it would rename every existing marker.
- **Run-level state is now a script side effect.** `sdr_context.py` — the one step both
  entries (launcher and host session) pass through — co-writes the guard sentinel
  `<repo>/.mgh-sdr/.active` and `<run-dir>/run_config.json` atomically. The shell's three
  hand-executed `printf` recipes are gone; the orchestrator no longer has to read and execute a
  write recipe correctly for the guard to be armed. The launcher keeps its own sentinel write as
  an **idempotent refresh**, because it is the second authorization judgment (roots are
  re-checked against the project config immediately before the host CLI is spawned, so a
  version-skewed sibling cannot leak an unapproved root).
- **`run_config.json` keeps one job, script-written.** Its only payload is the codegraph signal
  `{"no_codegraph": bool}`; the shell's auto-detection result is passed to `sdr_context.py` as
  `--no-codegraph` (the launcher gained the same flag) instead of being written by hand. The
  start state (repo/base/branch) is deliberately NOT written there — it is re-derived from
  `context.json` / `grouping.json`, and the resume script does not read the file at all. Legacy
  run dirs carrying start-state fields are ignored, not deleted.
- **The start state is disclosed, never guessed.** The one step with no on-disk start state is
  `not-started`, and that is also the one step with zero completed work — so re-supplying
  `--base`/`--branch` restores it losslessly. The script says so in `notes[]`, gives an
  executable call with defaults, and refuses to run `git` to guess a branch (using the wrong
  branch for a diff costs more than typing one flag).
- **Both command guides' recovery section now points somewhere that runs.** It names
  `resume_sdr_state.py --run-dir <abs>`, states the precondition (recovery must carry the SAME
  run dir — a fresh timestamped dir loses every marker), and says the progress and the defenses
  are disk-derived, so whether the conversation survived is irrelevant. The init-domain
  `resume_state.py` pointer (which resolves to `.mgh-init` and exits 1 against an sdr run dir) is
  gone. Two honesty boundaries were added: re-running the launcher creates a NEW run dir (never
  claim "re-run the launcher and it resumes"), and `--dimensions` narrowing is closed-set
  validated but **not** dispatched to review units.

Tests: 29 new cases for the resume state machine over synthetic run dirs (empty dir, context
only, grouping only, partial terminals, all-terminal, rendered, zero-diff, all-excluded, a
stale `status` field that must NOT be trusted, a legacy `run_config.json` that must be ignored,
a sentinel missing at each of the three guard-window steps, re-arm idempotence, and two calls
against one disk state producing byte-identical stdout), 7 for the shared marker predicate
including a real-git end-to-end assertion that the predicate reproduces `diff_group`'s emitted
paths byte-for-byte, 8 for the step manifest (including the cross-script discipline equality),
and 11 extending the existing sdr context / launcher suites (sentinel presence and
minimalism on every run, vanished roots dropped, the signal payload carrying only
`no_codegraph`, idempotent refresh, and the launcher's pre-spawn re-judgment still rejecting an
unapproved root). `tools/check_contracts.py` now asserts the new scripts' flags, that each shell
names the sdr-domain resume entry, and that a hand-executed `printf` write recipe cannot
reappear. `install.sh`'s co-location self-check covers the three new scripts. The two command
guides stay byte-mirrored apart from host-specific lines; each is ~3.4K tokens, within budget.

### Fixed — the sdr codegraph switch had three write ends and no reader; its recovery pointer could never run (0.1.49)

`/mgh-sdr` handed the shared dispatcher a codegraph switch that nothing consumed, and a
troubleshooting step that failed every single time.

- **The switch was dead.** The command shells exported `MGH_SDR_CODEGRAPH`, wrote a
  `no_codegraph` field into the run dir's `run_config.json`, and advertised `--no-codegraph` —
  none of it read by any script. The dispatcher's `_codegraph_signal()` returned `off` early for
  the sdr tier, so every review sub-agent's task message said `codegraph=off` ("this unit may be
  split at an interface boundary") while the grouping stage in the SAME run had already merged
  those units along the call chain and loaded the whole chain into the slice. Two stages of one
  run disagreeing about the same fact, and the disagreement told the reviewer to ignore exactly
  the cross-layer information grouping had just given it.
- **One carrier, and a real consumer.** `MGH_SDR_CODEGRAPH` is deleted rather than wired up: an
  environment variable has no consumers today and, on the opencode host, is unreliable anyway
  (the plugin process does not inherit mid-session `export`s). The signal now rides the run dir's
  `run_config.json` alone, written by `sdr_context.py` (the one step both entries pass through)
  and read by the dispatcher. The sdr plan anchor is already `<run-dir>/grouping.json`, so its
  parent IS the run dir: the sdr tier falls into the exact same read path as the init tiers with
  zero path changes, which is what makes the two stages agree by construction rather than by two
  logics kept in sync.
- **The signal is probed, not declared.** Closing the reader exposed the same defect one layer
  down: the value written into `run_config.json` was still whatever the caller happened to
  assert. The launcher asserted `on` unconditionally (its flag defaulted to off-by-absence, and
  nothing on that path ever looked at the repo), so on an unindexed repo the grouping stage
  degraded to no chain while every task message still promised "this slice already carries the
  whole changed chain: judge cross-layer inside it, do NOT re-derive" — a false instruction, and
  precisely the side-disagreement this change exists to remove. The availability predicate now
  lives once, in `sdr_tier.py`, and `sdr_context.py` derives the signal from it (repo indexed AND
  a `codegraph` binary resolves), exactly as `diff_group.py` decides whether to merge units along
  the chain. `--no-codegraph` survives as an explicit force-off **of the signal**; the shells no
  longer carry a second probe of their own. Note what that flag does and does not do: measured on
  an indexed repo, passing it flips the task message to `off` while `diff_group` still reports
  `codegraph: true` and still merges along the chain. That is deliberate and now stated as such
  everywhere the flag appears — it buys reviewers a conservative reading, it does NOT re-run the
  grouping without the index. (The earlier text claimed "zero codegraph calls, behaviour
  equivalent", which was never true of the grouping path.)
- **The recovery pointer was cross-domain.** The "fast-fail storm" step asked the orchestrator to
  run `resume_state.py --check` as proof that the disk was healthy before re-dispatching a
  stalled wave. That script resolves its state root to `<target>/.mgh-init` and has no form that
  accepts an sdr run dir, so against an sdr run it exits 1 ("dir not found") 100% of the time —
  turning the orchestrator's judgment into noise. It is replaced by `diff_group.py --check
  <run-dir>`, which does run in that domain (exit 0/2). Its meaning is narrower and is stated
  next to the command: it validates the **grouping artifacts** (grouping.json + slices +
  markers), not **run-progress consistency**. A full sdr resume surface is out of scope here.
- **Timeout wording pinned, zero values changed.** `--stall-timeout-s` has two numbers that are
  easy to confuse: `60` is the hard rejection floor (`1..59` exits 2) and `900` is the
  out-of-host manual-run default. `--help` now states the four-segment domain and labels each
  number explicitly, and says that a host-driven call MUST pass the flag explicitly below
  `--call-timeout-s`, NEVER rely on the default. The spawn-time recipe for a violated
  `stall < call` ordering now names the usual cause (an omitted flag) alongside its two exits.
  **No value changed**: the constants, the validation logic and the `300` used by every
  `/mgh-init` tier and by `/mgh-sdr` are untouched. Dropping the flag to "use the default" would
  make every host-driven tier unstartable (exit 2 before any spawn).

Tests: the sdr signal's three states (no field → `on`, `no_codegraph: true` → `off`,
missing/unparseable → `off` with no stderr noise) plus an end-to-end CLI case proving the
`{{codegraph}}` placeholder flips with the run dir's config; a guard that the four init tiers
still read the same carrier and that `tier_key` no longer branches; the probe's both-halves and
degradation cases, and that an indexed repo reports `on` through the launcher with no flag
(the case the old default got wrong); the omitted-stall rejection with all three recipe exits.
`tools/check_contracts.py` now fails the build if the dead env var returns, if a shell declares
`--no-codegraph` without the carrier it rides, if a shell points at a cross-domain script, if
the dispatcher's sdr early-return is reinstated, or if either consumer re-inlines the probe
instead of importing the shared predicate.

### Changed — the sdr slice budget is judged on the rendered slice, and an over-budget unit is re-split, slimmed, or refused — never dispatched (0.1.50)

`/mgh-sdr` promised "one unit input ≤ the byte budget", but the packing layer judged that
budget with an **estimate** — the sum of each file's diff-text length plus a flat 64 bytes per
file — while the subagent actually reads the **rendered slice**, which also carries a header, a
file list, an annotation-context block, a symbol table and one `@@` locator line per hunk. Two
paths escaped with no check at all: a multi-file unit that estimated under but rendered over,
and a single file whose own diff exceeded the cap (the source admitted it in a comment:
*"one oversize file may still exceed it (merged-capped, never split mid-file)"*). This is the
same tolerated gap `/mgh-init` closed in its T2 aggregation, where "warn and send anyway"
produced a real request-context overflow that killed the whole unit.

The judge is now the artifact: one measurement function renders the unit with the very renderer
that materializes it and takes the utf-8 byte count. Packing-time member sizes, the
`pending[].unit_bytes` field and the `--check` assertion all read that one number. Over budget,
three dispositions run in order, and the first that resolves it wins:

1. **Lossless re-split** — a multi-file unit is greedy-packed by path into `-partN` continuation
   units, each measured ≤ cap. No hunk is dropped, no content truncated; more units is the only
   cost. This is the existing greedy rule finally running on the right judge, not a new splitter.
2. **Context slim** — only for an atomic residue (one file left; a file is never split
   mid-file). The descriptive blocks (`ann_ctx` / `sym_ctx`) are truncated to module-constant
   caps with a visible `… (截断:K 行 / 原 N 字节)` marker in the slice and a `slimmed{}` record in
   the run record. The evidence anchors — diff bodies, the file list, the hunk locators, the
   header fields — are never touched: truncating the diff would make the review reach
   conclusions on partial evidence, which on a pre-merge security gate is worse than not running.
3. **Fail-loud, zero dispatch** — still over cap → exit 2 naming the unit id, its cap, the
   measured bytes and the largest contributing file, with a recipe (raise the cap / narrow the
   diff range / review that file out-of-band). The judgement happens **before** any slice or
   `grouping.json` is written, so with nothing on disk for the dispatcher to consume, "the
   enumerator refused" and "no subagent was spawned" are the same statement.

Disclosure is not optional: the run record gains a top-level `budget{}` and a per-unit
`slimmed{}`, `--check` asserts `unit_bytes ≤ cap` when those fields are present (an old
`grouping.json` without them still exits 0 — same incremental-field contract as `excluded` /
`codegraph_stats` / `chain[]`), and the report's honesty boundary names every slimmed unit so a
"no finding" from one is not read with the same weight as from a normal unit.

No new flags: `--max-standalone-bytes` / `--max-interface-bytes` remain the only levers; the two
slim caps are module constants. In-budget runs are byte-identical apart from the new `budget{}`
and empty `slimmed{}` fields.

Tests: the multi-file over-budget case re-splits with the parts' hunk-locator set equal to an
un-split run's (lossless), with the old `cap + 1024` tolerance tightened to `cap`; an atomic
residue whose overage is carried by the symbol table is slimmed (marker visible, diff body and
locators intact, `slimmed` recorded, exit 0); an atomic residue whose own diff body is over
refuses with exit 2 and **zero** slices, zero `grouping.json` and empty stdout; `unit_bytes`
equals the landed file's byte count for every unit; a pinned slice text guards the in-budget
no-regression line; `--check` covers the new-field assertions and the old-record skip; and the
dispatcher passes the refusal through as exit 2 against a real repo with nothing written.

### Changed — fanout silence is no longer proof of a hang: explicit off-switch + false-kill self-evidence + cost disclosure (0.1.48)

`--stall-timeout-s` was the only defense against a hung unit, and it silently doubled as a health
verdict. Under a rate-limited gateway that verdict is simply wrong: a unit with no output is
usually a call **sitting in the gateway queue**, which is byte-for-byte identical to a real hang.
Killing it does not shorten the queue — it discards the work already done and re-queues behind the
same congestion. Raising the constant does not fix it either (measured: 600s killed 5 units, 1600s
still killed 4, at 2.7x the cost each — 4 x 1600s = 6400 slot-seconds, 40-60% of that run's 5-slot
capacity).

- **Semantics rewritten wherever it is stated.** Byte silence now reads as "this unit has produced
  nothing for this long"; `--help`, the module docstring and both command guides say explicitly
  that it is NOT hang evidence, that the criterion's only legitimate job is bounding how long one
  slot may sit idle in this run, and that it cannot locally distinguish queueing from a hang. The
  old "high-signal hang indicator" wording is gone, along with the glossary entry that repeated it.
- **`--stall-timeout-s 0` = explicit off.** The value domain is now `0` or `>= 60`; `1..59` still
  exits 2, and both that error and the invariant recipe name BOTH exits (raise it, or pass 0).
  With the criterion off the `stall < call` ordering constraint does not apply and
  `--call-timeout-s` alone bounds convergence (so a host-driven run should tighten it). The only
  previous off-switch was `--call-timeout-s - 1` — an undocumented hack the old `--help` text
  argued against.
- **False-kill self-evidence + bounded widening.** If a unit the window killed then completes on
  re-dispatch in the same run, that is the one hard local proof the silence was not fatal: the
  effective window becomes `min(2W, --call-timeout-s x 0.8)` for units dispatched afterwards
  (stderr-disclosed once per triggering unit; per-unit, so one flaky unit cannot ratchet it to the
  ceiling; per-run, never persisted, never written back onto the flag). Each attempt snapshots the
  window at spawn, so a widening never retroactively moves the criterion of a unit already running.
- **Cost visibility.** Every exit's stdout summary and progress sidecar now carry
  `runtime_p50_s` / `runtime_p95_s` / `runtime_max_s` (COMPLETED units only — a killed unit's
  runtime is an artifact of the window, not a sample of the population the window sits above; all
  three are omitted, never 0, when nothing completed), `stall_killed_slots_s` and
  `stall_killed_slot_pct` (slot-seconds burnt by silence kills, and that as a share of the run's
  slot-seconds = elapsed x `--wave`), plus `stall_window_s` when the window actually widened.
  Existing fields are unchanged; the sidecar values are literally the same dict the summary is
  built from, so the two cannot drift apart on rounding.
- **Default value: unchanged at 900, now with a stated calibration.** `p99(completed-unit
  runtime) x 2`, rounded down to the minute, floor 900. Substituting the observed sample (n=84:
  p50 134s / p95 229s / p99 325s / max 325s) gives 650s -> 600s -> 900s. The calibration's value
  is the two conclusions it forces, both disclosed in `--help`: 900s is 2.8x the completed
  population's MAX (so "the default is too tight" is false for healthy units), and the killed
  units ran 600s+ / 1600s+ — outside that population's support, NOT its tail, so no higher
  constant rescues them. The sample is the SURVIVING population only, so it MUST NOT be read as
  "past this it deserves to die" — which is exactly why the adaptive widening exists instead.
- **Heartbeat discloses the window.** The in-flight line gains `stall_window=<w>s` (or `off` in
  disabled mode): with an adaptive window, `idle=1000s` is unreadable on its own — it means "kill
  is imminent" at W=900 and "nothing to see" at W=1800.

Tests: 20 added/updated across `tests/test_fanout_runner.py` and `tests/test_fanout_stale.py` —
the two pure helpers (`_widened_stall_window`, `_percentile_int`), the widening and its ceiling,
per-unit evidence dedup, the disabled mode at both the dispatch level (every attempt handed window
0) and the `_run_unit` level (the same silent child stall-killed at window 2, left to the call
timeout at window 0), the value-domain rejections with both recipe exits, the cost fields'
presence/omission and sidecar/stdout equality, and the widened heartbeat line format. Two existing
contract assertions were updated because this change is what they assert (the exact stdout key set,
and the below-floor rejection wording). No new flags, no dependency changes.

### Fixed — fanout stall handling killed the dispatcher itself, and mis-read "silence" twice (0.1.47)

Running the `/mgh-init` scout dispatcher directly on Linux (nohup, own terminal) died at
**~10 minutes** on three consecutive runs — no stdout summary, progress sidecar stuck at
`"running"`, `--kill-stale` reporting no orphans: the shape of a hard kill that never reached a
normal exit. Three defects, all on the stall-handling path:

- **The tree kill killed the caller.** POSIX tree kill is `os.killpg(os.getpgid(pid))`, and unit
  children were spawned **without a new session** — so they shared the dispatcher's process group,
  and killing a stalled unit killed the dispatcher. The kill also happens before the stall
  evidence is written, so nothing was logged at all. Units now spawn with `start_new_session`, so
  `killpg` scopes to that unit's own tree. Windows (`taskkill /T /F`) was never affected and is
  unchanged.
- **The silence criterion pointed the wrong way.** Both stream timestamps start at the spawn
  instant and only advance on real bytes, so `min(out_ts, err_ts)` meant "**at least one** stream
  has been quiet this long". Any child that never writes to stderr (common) was therefore judged
  stalled at `spawn + --stall-timeout-s` — which is exactly the 600s / 10-minute death. Now
  `max(...)`: silence means **both** streams went quiet, matching the flag's own
  "no stdout/stderr bytes for this long" wording. The heartbeat's `idle` disclosure uses the same
  source so it can never disagree with the kill criterion.
- **Reads were not byte-level.** Found while locking the fix with a test. `_tail_stream` used
  `TextIOWrapper.read(4096)`, which **blocks until 4096 characters accumulate or EOF**, so the
  "last output" stamp advanced once per 4096-char chunk rather than per byte — a low-volume but
  perfectly healthy unit kept both stamps parked at spawn and was still stall-killed after the
  `max` fix. Now `stream.buffer.read1(4096)` (returns as soon as any byte lands) plus an
  incremental UTF-8 decoder, which is what the function's own docstring ("ts of the last byte on
  this stream") already claimed.

**Boundary change — Ctrl-C no longer propagates to in-flight units.** Because units now lead their
own session, an interactive interrupt reaches only the dispatcher. Its exit path therefore
tree-kills whatever is still registered *before* clearing the registry and deleting the liveness
file — otherwise those children would become orphans that nothing could later find (not even
`--kill-stale`). A hard kill (SIGKILL, where no exit path runs) still leaves the liveness file
behind for `--kill-stale`, and that path is deliberately unchanged. The boundary is disclosed in
the `--stall-timeout-s` / `--kill-stale` `--help` text and in the `/mgh-init` and `/mgh-sdr`
command guides.

Four regression tests added (single-stream silence does not stall-kill; both-stream silence still
does; `_kill_tree` does not terminate its caller, asserted from a child process so a regression
surfaces as an exit code instead of silently killing the test runner; the exit path tree-kills
still-registered children and removes the liveness file). No new flags, no stdout field changes,
no dependency changes.

### Changed — SDD artifacts (openspec) must not point at the private `docs/` tree (0.1.46)

The repo-root `docs/` tree is the maintainer's private workspace: whether it is even committed is
the maintainer's call, so another clone may simply not have it. Distribution was already fenced
off; the *tracked* openspec record was not. A `proposal.md` / spec / task list saying "see the
rationale in that private file" is read by every later agent, and sends them to a file that may
not exist. New rule **R5.11** closes that:

- **Prohibited**: any path under the repo-root `docs/` tree in `openspec/specs/**` or
  `openspec/changes/**` — including the case where that path is the artifact's *subject* (a spec
  defining a doc that lives there). Bare mentions of the directory with no entry after it are
  prose, not pointers, and stay legal.
- **Exempt**: `openspec/changes/archive/**` (frozen history — retro-editing it would be busywork
  that also falsifies the record) and the docs-writing change whose deliverable IS a file there.
- **Replacement style**: name the role, not the path — "维护者私有文档区里的命令人话说明",
  "术语词典", "fan-out 运行手册".
- `check_distributed_purity.py` gained a third scan surface (`openspec/specs/**` +
  `openspec/changes/**`, archive skipped) that applies **pattern 9 only** — SDD artifacts
  legitimately cite rule ids / decision ids / change names on nearly every line, so the other
  families would be pure noise there. Scan set 228 → 272.
- Two false-positive bugs surfaced and were fixed while wiring this up: `glasswing_docs/09`
  matched as if it contained a `docs/09` path entry (a `docs` tail inside a longer word is not a
  path segment), and a bare `docs/` with nothing after it was treated as a pointer.
- Six active specs and two active changes de-referenced. Two of them
  (`distribution-purity`, `plain-language-doctrine`) had also become **factually stale** from the
  previous entry — they still described man pages as shipped and `docs/man/**` as part of the
  purity scan set — and were corrected to match the code.
- `tests/test_distributed_md_purity.py` covers the new surface: the three-way scan-mode dispatch,
  the archive + carve-out skips, and the pointer/exempt matrix (29 tests).

### Changed — repo-root `docs/` dropped from distribution; man pages no longer installed (0.1.45)

The repo-root `docs/` tree (man pages, glossary, upstream index, review/analysis notes) is
the maintainer's private workspace and was never meant to ship. It had drifted: `install.sh`
copied `docs/man/` into `<target>/docs/man/`, and all 12 command shells carried a
`> 人类读者:通俗说明见 docs/man/<cmd>.md。` pointer. Both are dead ends for anyone but this
working copy — `docs/man/mgh-sdr.md` was not even git-tracked, so a fresh clone installed the
tree without the very page two shells pointed at. Fixed in both directions:

- `install.sh` no longer lands `docs/man/`; the 12 shell pointers are deleted outright (not
  reworded — a reworded pointer is still a reference to a non-shipped tree). `install.ps1`
  never had the step, so the two installers now agree instead of silently diverging.
- `check_distributed_purity.py` gained pattern 9 (**repo-root `docs/` reference**:
  `docs/man/*`, `docs/glossary.md`, `docs/upstream-index.md`, `docs/upstream/**`, …) and now
  scans the shipped runtime surface too — `core/scripts/**`, `releases/*/hooks/**`,
  `releases/opencode/plugins/**`, `*.py`/`*.ts`/`*.json` — not just md (scan set 185 → 228).
  Nine script comments citing an upstream doc path or an openspec change-folder name were
  cleaned (e.g. `discover_controls.py` cited the upstream design-doc path).
- Patterns split into two families by who can hit them: **pointers** (change-folder names,
  upstream doc paths, repo-root docs) are scanned in every shipped file; **dev-manual
  vocabulary** (`R5.x`/`FDn`/`Dn`/dev-meta) only in shipped md. The host agent is required to
  run the scripts without reading their source, so an `R5.9` in a script comment never reaches
  the target, while the pointer a reader might follow is exactly what must not dangle.
- Two families sharing the `docs/` prefix stay legal and are pinned by tests: the target
  project's **runtime-generated** `docs/security-controls/` + `docs/test-conventions/`, and
  the `core/docs/` Apache-2.0 attribution records (ships as `<dest>/mgh-core/docs/`).
  `core/prompts/**` is skipped for pattern 9 — it is an R1-frozen verbatim port whose body
  mentions the *upstream* project's own doc layout (`docs/manifests/tree`,
  `docs/config/non-code files`), so flagging it would be an unfixable failure. That prose is
  the one known residual: it still ships, because R1 forbids editing it.
- Docs corrected where they described `docs/` as shippable: AGENTS.md R5.10 gained the 9th
  prohibited class, the R3 audience table split `人类·随包分发` from `人类·仅研发仓`, and the
  directory-tree comments in AGENTS.md + README.md no longer call `docs/` a "分发指南".
- `tests/test_distributed_md_purity.py` guard **inverted**. It used to assert the opposite
  (man pages MUST ship; every shell MUST carry the pointer) — a guard that would have actively
  blocked this fix. It now asserts `docs/` is not a scan root, no shipped file points at it,
  the two exempt families stay clean, and the script-family split holds (21 → 26 tests).

### Added — fanout crash-storm resilience: fast-fail cooldown + rate-limit storm truncation + bounded failed re-dispatch (0.1.44)

Quota-limited intranet gateways (observed: 100 calls / 10 min) turn a full quota
into a **fast-fail storm**: units die in seconds (opencode retries a 429 twice,
source-verified `retries: 2`), the runner requeues them with zero delay, the next
wave hits the quota again — a full storm cycle (1–2 min) runs far faster than the
10-minute quota window recovers, burning the night on
storm → breaker → resume → storm. Worse, a polite `failed:` ack after a provider
error writes a terminal `.failed` marker that enumerators exclude — the tier
"completes" with a coverage hole. Builds on the landed stall-containment
prerequisite (output-tail buffers / run.log evidence + slot-backfill loop are the
classification data source and cooldown mount point)
(`harden-mgh-fanout-crash-storm-resilience`):

- **Fast-fail cooldown** (`fanout_runner.py --cooldown-s`, default 300; `0` = off,
  also disables the pre-breaker backoff): ≥3 requeue events (crash/timeout/stall/
  spawn-error units returning to the queue tail; failed acks and pre-spawn anchor
  failures never count — they terminate without requeueing) within a 120s sliding
  window pause NEW dispatch while in-flight units keep running and harvesting.
  The wait is capped by remaining `--time-budget-ms` minus an in-flight convergence
  margin (pure `_cooldown_cap_s`); budget-starved cooldowns degrade to continuing
  immediately with a stderr disclosure. stdout adds `cooldowns:<n>`.
- **Pre-breaker bounded backoff**: when the zero-progress breaker is about to exit
  2 and the budget allows, one single "cooldown → full disk re-derivation →
  re-observe" round runs first — disk growth disarms the breaker, still-zero-growth
  exits stalled. At most once per call; the `stalled` contract is byte-identical.
- **Rate-limit crash classification + storm truncation** (`--no-rate-limit-stop`
  disables): every crash terminal's output tails (reader-thread buffers, the
  stall-containment data source) are classified against `429` / `too many
  requests` / `rate limit` / `quota` (case-insensitive; crash terminals only —
  ok/failed/timeout/stall never classified; overflow-marked crashes stay
  overflow). Crashes ≥ `--wave` since the last disk terminal advance that are ALL
  rate-limit stop dispatch immediately (fast path, ahead of any new cooldown) and
  exit 2 with `rate_limited:true` + `rate_limited_crashes:[ids]` + a wait-one-
  quota-window recipe. Signature drift (all unknown) degrades gracefully to the
  cooldown + breaker path; non-rate-limit crashes never count toward the threshold.
- **Bounded failed re-dispatch**: the five tier enumerators
  (`list_scout_batches`/`list_clusters`/`plan_aggregate`/`list_rule_jobs`/
  `diff_group`) gain `--include-failed` (default off = byte-identical stdout):
  failed units re-enter `pending[]` under their canonical ids with their existing
  `failed_marker` absolute paths (identity always from the enumerator's forward
  derivation, never filename stems; done counts stay marker-truth via a
  re-inclusion add-back). `fanout_runner.py --retry-failed` forwards
  `--include-failed` to the enumerator and deletes a claimed unit's `.failed`
  marker at claim (evidence stays in the unit's `*.run.log`); a re-failure writes
  a fresh marker and each unit is retried at most once per call. stdout adds
  `retried_failed:<n>`.
- **Call-surface discipline**: `discipline_core.py` + `init-stage/{scout,t1,t3}.md`
  + both sdr shells gain two recipe branches — `stalled:true` with a clean
  `resume_state --check` → provider congestion → re-dispatch the same command
  (NEVER rewrite inputs / delete markers / write micro-scripts); tier wrap-up
  `failed>0` with a provider-transient run.log shape → at most one `--retry-failed`
  round, then accept the gap and disclose. Contract lint
  (`tools/check_contracts.py`) asserts the three new runner flags and the five
  enumerator `--include-failed` flags.
- **Diagnostics invariants**: three counters that never share a window (cooldown
  requeue-time window / storm disk-advance window / breaker dispatch window); the
  post-cooldown drain re-list de-duplicates against the in-memory queue so a unit
  is never queued twice; summary keys are additive only
  (`cooldowns`/`retried_failed`/`rate_limited` always; `rate_limited_crashes`
  conditional, same shape as `context_overflow`).

### Added — `/mgh-init` T1 deterministic small-cluster packing — quota amortization, opt-in (0.1.43)

Quota-constrained intranet LLM gateways bill per call (observed: 100 calls / 10 min),
and every T1 unit pays a fixed 3–5 call overhead (session start / read task / read
input / ack) regardless of cluster size. A real run with 221 small clusters
(inputs 1.6–4.3KB) spent ≈900 calls — near a third of the quota — on overhead alone.
Bigger waves cannot help under a call-rate cap; fewer units can
(`improve-mgh-init-t1-cluster-packing`):

- **Pack partition** (`list_clusters.py --pack-bytes B`, default 0 = off; `--pack-max N`
  member cap, default 8): same-category clusters whose whole-cluster input fits
  `--max-unit-bytes` are sorted by `(bytes asc, cluster_id)` and greedily packed;
  oversize/`::shard-<n>` units and terminal-failed clusters never enter a pack. Pack id
  = `pack::<category[:64]>::<sha8(sorted member ids)>` — partition and id are pure
  functions of `clusters.json` + flag values (same input, same packs, any cwd).
- **One merged input per pack** (`<inputs/t1>/<safe(pack_id)>.input.json`, body
  `{repo, pack_id, category, members[], checkpoints[]}`): one subagent Read amortizes
  the fixed overhead over all members. `pending[]` pack items carry the pack id in the
  `cluster_id` field slot (dispatcher + ack state machine consume it unchanged) and a
  `members[]` list with per-member absolute paths; stdout adds `cluster_total`/
  `cluster_done` (packing path only). Paging and `--orch-budget-bytes` shrink apply
  to the packed list unchanged.
- **Cluster-level markers stay the only truth source**: a pack is pending iff ≥1
  member lacks `.done`; a re-dispatched pack skips done members via the dual-form task
  template (`fanout/t1-task.md` Form B: probe `checkpoints[]` → skip done → induce per
  member → `unit` = member cluster_id → ack `ok <pack_id> <n>` /
  `failed <member ids>: <reason>`). Recovery granularity stays cluster-level; a
  pack-level `.failed` (written by the dispatcher on a failed pack ack) recovers by
  deleting the marker and re-listing. Pack-level markers are excluded from the orphan
  audit (`init_tier.orphan_markers`).
- **Zero changes** to `fanout_runner.py` (packed pending flows through the same field
  slots), T1 record schema, `validate_t1_records.py`, the T2 records gate, and
  `resume_state.py` (cluster-level counting is pack-agnostic by construction).
- **Enablement surface**: the orchestrator's `list_clusters.py` call lines
  (`init-stage/t1.md` manual path + `discipline_core.py` t1-pack recipe + man page);
  suggested quota value 16384. The dispatcher main path does not yet forward the flag
  (its enumerator argv is fixed by the zero-change constraint) — hand-dispatch path
  enables packing today; dispatcher pass-through is a small follow-up if wanted.
- Off-path regression is byte-identical (no new stdout fields, zero pack code);
  invalid combinations (`--pack-max` without `--pack-bytes`, packing without
  `--materialize`) exit 2.

### Changed — `/mgh-init` T2 oversize category: deterministic part split + atomic slim projection (0.1.42)

A T2 unit crashed with a model context-overflow in a real run: the `authorization`
category alone serialized to 400KB > the 256KB budget, and `plan_aggregate.py`'s
old fallback ("`oversize:true` + stderr warn + dispatch anyway") sent a doomed
request. Root cause: per-category sharding treated one category as atomic even
when it alone exceeded the budget. Fix: split it (`harden-mgh-init-t2-oversize-shard`):

- **Part split**: an over-budget category is greedy-packed whole-record (existing
  glob order, deterministic) into ≤-budget parts `t2-<category>-part<N>`; the shard
  input envelope and stdout shard items carry `part_index`/`part_count` (0/1 when
  unsplit). Rollup now reconciles across shards — same category across parts AND
  across categories, same judgment signals; partial still makes NO cross-shard
  judgment. Marker-aware re-list / `.done`/`.failed` / dispatcher waves unchanged.
- **Atomic-oversize fallback**: a single record > budget is slim-projected at
  materialization (truncates `description`/`usage`/`protects`/`gaps`/`entry_points`
  to internal caps; `evidence` anchors never cut; `_slimmed` marker + stdout
  `slimmed` disclosure; `checkpoints/t1` originals never rewritten). Still over
  after slimming → exit 2 with the record file + byte count, zero dispatch.
  Dispatched T2 shards are always ≤ budget ⇒ `oversize` is always false (field
  kept for compat). scout-merge envelope/stdout byte-identical (hand-paged).
- **P2 diagnosis**: `fanout_runner.py` matches crashed units' stderr tails against
  a context-overflow signature set → `reason:context-overflow` + narrow-`--budget`
  recipe on the run.log unit line/stderr + `context_overflow[]` in the stdout
  summary; tier-agnostic, outcome semantics unchanged.
- **Zero regression**: `needs_reduce=false` small-repo stdout pinned byte-identical
  in tests; no new flags, no new dependencies.

### Changed — fanout dispatch stall containment: slot backfill + tree-kill + four-level timeout invariant (0.1.41)

`fanout_runner.py` dispatch hardened against hung subagent units burning the whole run
(`harden-mgh-fanout-stall-containment`):

- **Slot-backfill dispatch core** (was wave-barrier): in-flight capped at `--wave`, harvested
  via `concurrent.futures.wait(FIRST_COMPLETED)`, next unit backfilled immediately; queued
  units lazy-skip if their `.done`/`.failed` marker appeared since listing. A single hung unit
  no longer stalls the whole wave. `waves_run` = cumulative dispatch count; stdout contract
  otherwise unchanged (plus new `stall_killed[]`).
- **Stall detection + surgical tree-kill**: per-unit reader threads track output byte-silence;
  silence ≥ `--stall-timeout-s` (default 900, floor 60) or wall-clock ≥ `--call-timeout-s`
  → `_kill_tree` (process group, fixes `.cmd` shim orphans) → unit re-enqueued (no marker —
  crash ≠ confirmed failure). Every unit terminal state appends a `run.log`
  (`<checkpoints>/<tier>/<unit>.run.log`, stdout/stderr tails, ok included); non-ok terminals
  name it on stderr; heartbeat every `--hb-interval-s` prints `inflight/idle/done`.
- **Four-level timeout invariant, fail-loud at spawn (exit 2 + recipe)**: with
  `--time-budget-ms`, explicit `--call-timeout-s` is REQUIRED and must satisfy
  `stall-timeout-s < call-timeout-s < budget-ms × 0.8 < host per-call timeout`
  (compliant pairs: 720000/540/300 opencode, 480000/360/300 claude). Budget without
  call-timeout used to silently inherit 7200s — past every host hard-kill.
- **Zero-progress breaker, dual observation points**: disk terminal count re-listed every
  K = `--stall-waves × --wave` dispatched units AND on queue-drain re-list;
  `--stall-waves` consecutive zero-growth observations with units still outstanding →
  exit 2 + `stalled:true` + `stalled_pending[]` (id + on-disk marker existence). Deterministic
  trip math (wave=1, always-stall): trip at (stall_waves+1)×K dispatches.
- **Bugfix**: run.log previously recorded crash units as `spawn-ok` (status settled after
  evidence write); status classification now precedes the log write.
- **Call-surface sync**: the four init-stage dispatch fragments, both `mgh-sdr.md` shells,
  `discipline_core.py` fan-out recipes, and `mgh_sdr_launch.py`'s emitted command now carry
  explicit `--call-timeout-s`/`--stall-timeout-s` (launcher-emitted commands stay
  invariant-compliant); man pages gained 现象→原因→改法 sections for heartbeats, stall
  auto-recovery, run.log triage, and the breaker.
- **opencode fanout agents pinned**: all five `*-fanout.md` frontmatter permissions add
  `external_directory: deny` + `doom_loop: deny` (claude `-p` headless already auto-denies).
- **Tests**: `test_fanout_runner.py` 77 green (breaker trip/recovery math, slot backfill,
  real-child tree-kill, invariant CLI matrix), `test_fanout_stale.py` 17 green; five-tier
  `--pending-file` + `--kill-stale --dry-run` smoke; contract/purity/prompt-budget lints pass.

### Added — sdr external-repo read authorization gate (0.1.40)

`/mgh-sdr` external-repo retrieval flipped from implicit (any path declared in the existing
design docs was auto-allowed per run) to **explicit user opt-in** (`add-mgh-sdr-read-root-config`):

- **New `core/scripts/read_roots_config.py`** — the config writer for `<repo>/.mgh/read-roots.json`
  (`--target/--add/--remove/--list/--check`; exit 0/1/2; transactional all-or-nothing `--add`;
  repair-with-`.bad`-backup on malformed config; atomic write; idempotent; `--check` fail-loud
  on stale/nonexistent entries with a `--remove` recipe). Config is hand-editable, read-only
  to runs, NEVER written without explicit user consent.
- **Authorization gate, judged twice** (sdr_context.py before retrieval; mgh_sdr_launch.py
  before sentinel write — version-skew defense, semantics in lockstep with the guard's
  config reader): approved = resolve-normalized entry in config ∧ exists ∧ is-dir.
  Unapproved declarations → **zero reads**, `external_skipped:"unapproved: <path>"`,
  `pending_approval[]` in stdout + manifest.
- **pending_approval flow**: stdout → orchestrator → host session asks the user per repo.
  Consent → `read_roots_config.py --add` (one write, persistent) → re-run same args.
  Refusal → degrade with disclosure; NEVER write config without explicit consent.
- **launcher**: prompt + stderr WARN carry the approve recipe and the NEVER clause; sentinel
  `read_roots[]` = configured ∩ actually-retrieved repos ∪ operator `--read-root`.
- **render_sdr_report.py**: new `unapproved` degradation variant, disclosed distinctly from
  `not-found` (unreachable): 外部仓未授权 → 前端相关检查面未覆盖.
- **Shells** (claude + opencode mgh-sdr.md): step-1 pending_approval ask + approve recipe +
  Always-disclose bullet; **contract lint** `tools/check_contracts.py` asserts the new script
  flags + both shells' markers; **install.sh** co-location self-check adds `read_roots_config`;
  zero-dep AST scan covers it via the existing `core/scripts/*.py` glob.
- **Tests**: new `tests/test_read_roots_config.py` (16); `tests/test_sdr_context.py` (20),
  `tests/test_mgh_sdr_launch.py` (9), `tests/test_render_sdr_report.py` (18) extended.

### Added — Bash path-token allowset net + project read-roots config (0.1.39)

Guard Bash face reversed from verb-enumeration blacklist to a verb-independent fail-closed
path allowlist (`harden-mgh-bash-path-allowlist`):

- `block_adhoc_scripts.py` (claude + opencode byte-identical) adds **rule m** — appended LAST
  in the Bash rule chain: EVERY path-like token in any Bash command (drive-letter `C:\…`/`C:/…`,
  UNC `\\…`, POSIX `/…`, `..`-leading resolved against the guard cwd, `~/`-leading expanduser;
  quotes stripped; `://` URL tokens excluded; bare `~`/`..` not judged) must resolve inside the
  **unified read allow-set** = `MGH_TARGET` ∪ sentinel `read_roots[]` ∪ project config
  `read_roots[]`, or the command blocks (exit 2 + recipe naming the three allow-root classes +
  the config remedy). Closes the "verb not in any enumeration table" escape class (`robocopy`,
  `curl -o`, `[IO.File]::WriteAllText`, `Get-Content <file>`, `Expand-Archive`, …); the five
  verb tables REMAIN as refinements (write/delete recipes, cwd-drift, P1 root pollution) and
  mutation rules still run FIRST. No path token / unpinned target => pass.
- **Read allow-set unified across both faces (semantic reversal)**: sentinel `read_roots[]`
  now covers the Bash face (search/listing verbs + the net) exactly like the tool face —
  "what is readable at all is readable through any tool". The write side keeps judging
  `MGH_TARGET` alone; leaf-source / `py -c` / temp-I/O / file-assoc blocks unrelaxed.
- **New project config `<target>/.mgh/read-roots.json`** (schema `{"v":1,"read_roots":["<abs>…"]}`),
  consulted in EVERY run-domain: hand-editable, read-only, never writable, fail-closed
  (missing file = unchanged behavior; malformed JSON / wrong-typed `read_roots` = zero grants,
  no crash; each entry needs exist-and-is-dir containment).
- Accepted new blocks (previously passed): single `> /tmp/x` writes, `--flag=<out-of-tree>`
  values, `git -C <out>`, harmless out-of-tree mentions — remedy = declare a read-only root in
  the config or run outside an mgh session. Residual boundaries disclosed: unknown write verb
  into a declared read-only root; alias/variable indirection.
- `core/contracts/hooks/runtime-enforcement.md` + AGENTS.md R5.7 synced (decision-model table,
  config contract, reversal note); regression tests +24 (`TestBashPathAllowset`,
  `TestReadRootsConfig`), 3 existing cases flipped per the reversal / accepted-blocks budget;
  opencode `.ts` shim + matcher untouched (parity green).

### Added — guard listing/execution confinement + mgh-core missing-install stop-all (0.1.38)

Real-machine Linux first-run hardening (`harden-mgh-guard-listing-exec-confinement`):
mgh-core installed only in the root project while the run executes in an independent
sub-project — scout 409/409 done then T1 stuck 0/9 with the agent roaming `/home`/`/adhome`
hunting for prompts/scripts, plus a `SyntaxWarning` polluting every leaf-script stderr.

- `block_adhoc_scripts.py` (claude + opencode byte-identical) adds three Bash rules:
  **listing confinement** (rule j — `ls`/`dir`/`Get-ChildItem`/`gci` leading a simple command
  with an out-of-tree scope: explicit path token OR `..`-climbing relative OR cwd-anchor,
  mirroring the file-search rule), **interpreter execution confinement** (rule k —
  `py`/`py3`/`python`/`python3`/`python2` running a script whose first anchored
  script-extension positional argument resolves outside the tree; `--flag <path>` values are
  data paths and never judged; `py -c`/`-m` excluded), and **mgh-core missing-install
  stop-all** (rule l — a command referencing an `mgh-core/scripts` script-extension path
  absent on disk (cwd- and target-relative) or existing outside the tree => exit 2 +
  STOP-ALL recipe: stop all tasks, ask the USER to install in the CURRENT project directory,
  NEVER search other directories; checked BEFORE every other Bash rule — terminal state
  short-circuits). Target absent => degrade to pass on all three.
- fan-out task templates (`t1/t2/t3/scout-task.md`): the stage-prompt path is pinned as the
  ONLY location; Read failure => immediate `failed mgh-core prompts not installed at <path>`
  ack, NEVER cross-directory wandering. Stage prompts (`init-induct` / `init-scout` /
  `init-rulewriter`): an in-anchor expected path that does not exist gets the same
  poisoned-input treatment.
- `list_clusters.py` module docstring is now a raw string (the `` `\` `` invalid escape
  triggered a SyntaxWarning on every import-chain load, polluting stderr). New regression
  `tests/test_no_compile_warnings.py` compiles all `core/scripts/*.py` with
  `warnings.simplefilter("always")` — any Warning fails loud.
- Guard suite grows the three-rule hit/pass matrix (+40 tests → 225) including order
  regressions proving existing recipes are unaffected by the new first-position rule.

### Changed — `/mgh-sdr` report restructure: 简报表 + P-NN 详述 + 分支调用链图 (0.1.37)

Report-side readability rework (`improve-mgh-sdr-report-structure`): the per-dimension
problem list is replaced by a unit-row summary table with inlined abbreviated call
chains; problem details move to globally-numbered P-NN sections; only branched units
get a mermaid chain diagram (Plan C — maintainer-selected format sample).

- `diff_group.py`: **chain materialization** — grouping retains raw callee edges (the
  changed-set filter previously dropped unchanged downstream edges) and inverts caller
  edges, then projects each interface unit a deterministic `chain[]` node sequence
  (`{fqn_short, label, file, line, change, route?, branch_of?}`; fqn_short = package
  initials + class + `.` + method; interface→impl resolution prefers the impl; mapper
  XML terminal via one deterministic repo `*.xml` scan keyed by namespace∧statement-id;
  zero new codegraph queries). grouping.json gains `units[]` (full-unit projection with
  route/chain/status — the renderer's row truth, survives fan-out completion).
  Fixed latent `_brace_end` bug: a `//` comment permanently broke brace matching for
  all subsequent lines (methods silently dropped from the symbol map). `--check`
  validates chain node fields + legal branch_of indices.
- `sdr_context.py`: route annotation regex extended to the `@RequestMapping` family
  with class-level base-route join (look-ahead past the class declaration; a class
  annotation itself is a base, never an endpoint). `_external_retrieve` materializes
  per-route occurrence counts into context.json `external_repos[].route_hits[]`
  (`{route, count}` list; was hits.md text only) — the renderer joins it deterministically.
  The permission-config hit count field is renamed `config_hits`. `--check` validates
  the `route_hits[]` shape when present.
- `render_sdr_report.py`: three-section report — 章节一 简报表 (row = unit, sorted
  interface-by-route then standalone; columns = entry / abbreviated chain
  (`·`/`⤷`/`⇢`/`†`) / 前端两列 (route join route_hits three-state) / 6 dimension
  columns `否`|`是 [P-NN]`), 章节二 问题详述 (global P-NN, severity-asc, 位置
  `file:line` with degrade to `file`), 章节三 分支调用链图 (mermaid `flowchart LR`
  per branched unit only). NO md internal anchors anywhere (obsidian/Zed cannot jump
  them) — `--check` asserts `<a id=`/`{#`/`](#` absence and manifest rows-length ==
  table rows. Draft schema gains optional `line` (int anchor line; old drafts degrade,
  not fail). Failed units never become table rows (honesty boundary discloses them).
- sdr-task fragment + both `sdr-review-fanout` agent mirrors: draft schema documents
  `line`; both mgh-sdr shells note the three-section report structure + frontend
  two-column data source.

### Added — `/mgh-init` T2 synthesis map-stage dispatcher adoption (map-reduce), split partial/rollup prompts (0.1.36)

Over-budget T2 synthesis (`plan_aggregate --node t2` → `needs_reduce=true`)
previously fell back to per-shard manual orchestration (one LLM turn per shard,
no timeouts / kill-stale / circuit breaker). The map stage now goes through the
same deterministic dispatcher as scout/t1/t3.

- `fanout_runner.py`: TIERS adds a `t2` row (enumerator = `plan_aggregate.py
  --node t2`; template `fanout/t2-task.md`; fanout agent
  `init-synthesis-fanout`; placeholder/path set
  `input_path`/`checkpoint_path`/`done_marker`/`failed_marker` +
  `shard_id`/`categories`/`repo`). New `--init-dir`/`--budget` flags; `--tier`
  closed set is now `scout|t1|t2|t3|sdr`. plan_path special case anchors the
  sidecar/liveness home at `<init-dir>` via `run_config.json` (design D5). Wave
  loop / ack state machine / timeouts / liveness / `--kill-stale` / circuit
  breaker / sidecar reused unchanged (tier-agnostic code path untouched).
- `plan_aggregate.py` `--node t2` stdout is now a **marker-aware legal fanout
  enumerator**: top-level `repo` (= `--init-dir` parent anchor) and marker-derived
  `total`/`done`/`failed`; each shard carries `failed_marker`; `pending[]`
  excludes shards whose `.done`/`.failed` marker exists (so the dispatcher's
  re-list converges and its circuit breaker reads marker truth);
  `summary_paths`/`shards` stay the full set (rollup + disclosure).
  `needs_reduce=false` path is byte-identical. `scout-merge` (hand-paged, a
  non-goal) is untouched.
- synthesis prompts split into three states: `init-synthesis.md` (whole,
  small-repo single-context, unchanged), `init-synthesis-partial.md` (per-shard
  bounded partial → structured shard summary; no cross-shard canonical/competing),
  `init-synthesis-rollup.md` (cross-shard merge over summaries → final
  inventory). New opencode primary agents `init-synthesis-fanout.md` /
  `init-synthesis-rollup.md`; claude resolves them via `--agents` inline JSON.
- orchestrator step face: `init-stage/t2.md` is dispatcher-first
  (`needs_reduce=false` → single-context; `true` → `--kill-stale` pre +
  `fanout_runner --tier t2` + `partial:true` re-dispatch + exit-2 manual
  fallback; map all `.done` → one rollup); `list_steps.py` t2 step carries the
  dispatcher call line; `discipline_core.py` t2 adds the soft-deadline
  re-dispatch path recipe; `resume_state.py --check` treats shard markers
  without the `synthesis.json.done` rollup terminal as a LEGAL intermediate
  (advisory note, no new step id).
- contract/install: `check_contracts.py` asserts the t2 tier set + new flags;
  `install.sh` self-check mirrors `t2-task.md`, the partial/rollup stage
  prompts, and the two new opencode agents; distribution-purity lint stays
  clean.

### Fixed — `/mgh-init` done-marker identity: forward marker-path judgment + dispatcher stall circuit breaker (0.1.35)

Root cause of the observed infinite T1 re-dispatch (32 overlong-id clusters
re-burned every wave, done=476/failed=5/pending=32 frozen): `_done_ids`/
`_failed_ids` recovered unit identity from each checkpoint record's `unit`
field (T1 records never carried one) with a filename-stem fallback — short ids
aligned by luck, overlong ids truncate under `_safe_name` so stem ≠ canonical
id → judged pending forever → `done+failed` never reached `total` → tier never
completed, and the dispatcher had no zero-progress cut so the orchestrator
re-dispatch loop burned the session budget.

- `list_clusters.py` / `list_scout_batches.py`: done/failed judgment rewritten
  to **forward marker-path computation** — walk the plan artifact's canonical
  unit ids (clusters[].cluster_id + `::shard-<n>` derivations / batches[].
  batch_id), encode the exact `.done`/`.failed` marker path with the SAME
  `_safe_name` the write side uses, `is_file()` = terminal. Identity NEVER from
  a record-body field or a filename stem. glob reverse lookup demoted to a
  fail-soft **orphan audit** (stderr `warn: orphan marker …`, enters no count).
  Encoding/judgment predicates are shared in `init_tier`
  (`safe_unit_filename`/`forward_marker_paths`/`forward_done_ids`/
  `forward_failed_ids`/`orphan_markers`) — single source, judgment and
  materialization cannot drift. Sharding decision extracted to `_shard_plan` +
  `collect_canonical_ids` so the canonical-id set and the materializer agree by
  construction. Existing `.json`+`.json.done` artifacts stay valid — a stuck
  run self-heals on the next `/mgh-init --resume` (no disk surgery).
- `fanout_runner.py`: zero-progress **convergence circuit breaker** —
  `--stall-waves` (default 2) consecutive fully-joined waves with equal
  done+failed snapshots and pending non-empty → stop dispatching, **exit 2**,
  stdout `stalled:true` + `stalled_pending[]` (per stuck unit: id + actual
  on-disk `.done`/`.failed` marker existence), stderr diagnosis recipe (stop
  re-dispatching; `resume_state.py --check`). A slow-but-advancing wave resets
  the window; `partial:true`/clean paths unchanged.
- `resume_state.py`: t1/scout tier done/failed counts now use the SAME forward
  predicates (imported, not copied) — count caliber and enumerator `pending[]`
  semantics agree by construction. `--check` additions: judged-pending-but-
  marker-name-on-disk = violation (id + path + do-not-re-dispatch recipe);
  orphan markers = advisory `notes[]`; touch-only `.done` (no record body) is a
  legal form, no longer a violation. Caliber disclosure in `--help`/docstring.
- `validate_t1_records.py`: T1 records now assert a root-level `unit` field
  (identity double-cover): non-empty + `unit == cluster_id` (violation on
  drift). Historical-form discrimination: no `unit` + forward marker exists =
  **warning** (历史形态,无需处理); no `unit` + no marker = violation.
  stdout gains a恒在 `warnings[]` field.
- Templates/agents/contracts: `fanout/t1-task.md`, `stages/init-induct.md`,
  both `init-induct` agent definitions carry the `unit` field instruction;
  both `mgh-init` shells + `init-stage/t1.md`/`scout.md` fragments carry the
  stall-breaker recipe and forward-judgment semantics; `cluster-enumeration`/
  `scout-enumeration`/`resume-state`/`t1-record-schema` contracts synced.
  `check_contracts.py` FANOUT_RUNNER_REQUIRED_FLAGS += `--stall-waves`.

### Changed — `/mgh-init` fanout lifecycle hardening (liveness + `--kill-stale` orphan-tree cleanup + stderr heartbeat + count-semantics doc)

- `fanout_runner.py` dispatch mode now writes an atomic liveness file
  `<init-dir>/fanout_runner.<tier>.pid` (body `{pid, started_ts, tier, host, cmdline,
  children[]}`; an orphan signal, NOT a lock) and removes it on any exit path
  (try/finally); a hard kill leaves a residual that `--kill-stale` disambiguates.
  Children spawn switched `subprocess.run` → `subprocess.Popen` (same capture/timeout
  semantics) so in-flight host-CLI child PIDs are recorded in `children[]` per wave
  and cleared at wave end.
- New `fanout_runner.py --kill-stale [--dry-run]`: inspects liveness residuals and
  kills what they record — form ① runner PID alive + cmdline matches `fanout_runner.py`
  → whole-tree kill (Windows `taskkill /pid <pid> /T /F`; POSIX process group); form ②
  runner dead/mismatched but a recorded `children[]` PID is alive + cmdline is the host
  CLI → kill each such tree (covers "orchestrator+runner hard-killed together, LLM
  children still burning tokens"). PID-reuse guard: cmdline double condition — mismatched
  PIDs are NEVER killed (residual file removed only). Destructive-op guard: a real kill
  with detected targets requires a prior `--dry-run` review (else exit 2 + recipe);
  no stale → `killed: []` exit 0 (idempotent, tier-agnostic). stdout
  `{"kill_stale": {"killed":[{pid,tier,kind}], "removed":[...], "none":bool}}`.
- stderr heartbeat: the dispatch loop prints `[fanout_runner <tier>] +HH:MM:SS wave=<k>
  unit=<id> <event> done=<d>/<total>` at every unit spawn / unit terminal status
  (ok|failed|timeout|crash) / wave end — live progress in the opencode TUI (merged
  stdout+stderr sliding tail, `docs/opencode-context-mechanics.md` §8) and in claude
  Bash results. stdout contract unchanged (single final JSON line).
- `resume_state.py` stdout gains additive `stale_fanout[]` (scan of
  `fanout_runner.*.pid`: `{tier, pid_file, pid, pid_alive, note}`; any alive PID's note
  carries the `--kill-stale --dry-run` recipe; `[]` when none — field always present).
  `--check` discloses alive residuals in `notes[]` as ADVISORY, never a gate.
- Count-semantics documentation (resume_state docstring + `--help` epilog): three
  measures — resume_state pure `*.json.done` marker glob count / list_clusters
  record-body unit dedup (shard-aware) / directory entry count (done + failed + record
  bodies) — equal only with no shards and no orphan markers; a mismatch (e.g. 472 vs
  491) is NOT data loss.
- Orchestrator wiring: both `mgh-init` shells' resume recipe now reads
  `stale_fanout[]` first (kill stale orphans before re-dispatch); the scout/t1/t3
  stage fragments prefix every fanout dispatch with the `--kill-stale --dry-run` →
  real-kill recipe. `tools/check_contracts.py` registers `--kill-stale`.

### Changed — `/mgh-init` scout merge lost-artifact recovery (exact note + `--check` mirror violation + fold-in re-run anti-pattern + contract correction)

- `resume_state.py` `_scout_step` now splits "all reader batches done but
  `scout_candidates.json` missing" into three merge/fold-in sub-states with precise recovery
  notes: merge marker absent → merge not run (regen credential then fold-in still pending);
  merge marker + `provenance.scout_merged` present → fold-in already run (`scout_merged=N`),
  regen serves ONLY as the completion credential (no downstream consumption, LLM drift
  harmless), NEVER re-run `merge_scout.py` fold-in, after regen `resume_state` re-derives
  `step=t1`; merge marker present + `scout_merged` absent → both credential and fold-in
  pending. All three next_actions stay `init-scout-merge` (honest re-generation — the unique
  recovery path); the note no longer misreports "merge marker absent" when the marker is on disk.
- `resume_state.py --check` gains the **mirror violation**: `checkpoints/scout/merge.json.done`
  + fold-in done + `scout_candidates.json` missing → exit 2 with a regen recipe (mirror of the
  existing "credential present but merge marker absent"); recovery (credential back on disk)
  → `--check` passes.
- `discipline_core.py` scout step `nevers` gains the fold-in re-run anti-pattern (`NEVER`
  re-run `merge_scout.py` fold-in when `provenance.scout_merged` is set — re-run is
  non-idempotent: same-file re-run zeroes `scout_merged`, drifted-file re-run double-appends).
- `core/contracts/init/resume-state.md` corrects the wrong "fold-in re-run idempotent/safe"
  claim and documents the three sub-state notes + the `--check` mirror violation.

### Changed — `/mgh-init` fan-out dispatcher generalized to all tiers (scout + t1 + t3)

- `fanout_runner.py` is now **tier-aware**: `--tier scout|t1|t3` (default scout — the
  existing scout call shape `--scout-plan/--checkpoints/--inputs-dir` is unchanged).
  All tier variation lives in a single `TIERS` mapping table (enumeration script +
  forwarded flags, task template, placeholder set, anchor-tree path fields, fanout
  agent name, marker `tier` value); the wave loop, ack state machine, three-level
  timeout invariant, sidecar, and audit copies are shared with zero per-tier branches.
  t1 requires `--clusters`/`--candidates`; t3 requires `--inventory`/`--format`/
  `--rules-dir`/`--target` (closed-set validation: missing flags → exit 2).
- **T1 scout-gate pass-through**: when `list_clusters.py` refuses with exit 2
  (`scout-incomplete-gate`), the dispatcher exits 2 and forwards its stderr recipe
  verbatim (finish the scout tier first) — a gate refusal is never swallowed into a
  generic error / crash re-dispatch loop.
- **T3 `repo` anchor**: `list_rule_jobs.py` stdout now carries top-level `repo`
  (resolved absolute `--target`, same shape as `list_clusters`) — the precondition
  for the dispatcher's anchor-tree checks and subprocess cwd on the t3 tier.
- **New task templates** `core/prompts/fragments/fanout/t1-task.md` / `t3-task.md`
  (same shape as `scout-task.md`: input-field declarations + stage-prompt load
  instruction only, zero behavior-rule duplication; t3 placeholder set uses
  `rule_path`, no checkpoint/slice fields).
- **opencode fanout agent clones** `init-induct-fanout.md` / `init-rulewriter-fanout.md`
  (`mode: primary`, verbatim clone of the stage agent + fanout annotation — the
  spike-verified headless-spawn path); claude side stays inline-JSON parameterized.
- **t1/t3 fragments are dispatcher-first** (`init-stage/t1.md`/`t3.md`): main path =
  one `Bash` `fanout_runner.py --tier …` with `--time-budget-ms` wiring +
  `partial:true` re-dispatch; exit 2 → manual-dispatch fallback preserved verbatim;
  T1→T2 validate gate and t3 assemble steps untouched. `list_steps.py` t1/t3
  invocations now point at the dispatcher; `discipline_core.py` t1/t3 recipes carry
  the soft-deadline re-dispatch discipline (per-call `timeout` > `--time-budget-ms`).
- **BREAKING (run-state file rename, one-time)**: the progress sidecar is now
  `fanout_progress.<tier>.json` per tier (scout: `fanout_progress.json` →
  `fanout_progress.scout.json`). Interleaved long runs (resume) would otherwise
  overwrite a single shared file with fake backwards progress. Old-name leftovers
  are harmless (run-state disclosure, not a contract artifact; not read by
  resume/init_manifest); install does not clean them. Man page + fragments updated.
- Contract lint asserts the new flags (`--tier`/`--clusters`/`--candidates`/
  `--inventory`/`--format`/`--rules-dir`/`--target`) + the three tier templates'
  existence; `install.sh` self-check covers the fanout tier payload (templates +
  opencode fanout agent clones).

### Changed — `/mgh-init` scout dispatcher long-run timeout calibration + progress visibility

- First large-repo live resume (900-batch scale, opencode host) exposed: the scout
  fragment's dispatcher call line never passed `--time-budget-ms`, so one `Bash` call
  ran 15 minutes with zero visible output and got hard-killed by the host shell
  per-call timeout (900s) — then the orchestrator's marker-based self-healing
  re-dispatched it into a kill/re-dispatch loop (each kill losing in-flight waves),
  with no way for a human to tell "slow" from "hung".
- **Timeout invariant, documented and wired** (`core/scripts/fanout_runner.py`):
  `call-timeout-s × drain headroom < time-budget-ms < host per-call timeout`
  (≥20% headroom per level). `--call-timeout-s` default 1800→**7200** — one batch =
  one full LLM subagent run on a slow intranet endpoint (minutes-level observed), so
  ~4× headroom; better-slow-than-killed: a killed batch leaves no marker, stays
  pending, and re-dispatching wastes a whole run. `--time-budget-ms` help now carries
  the recommendation (host per-call timeout × 0.8; opencode 900000ms host → 720000,
  claude Bash 600000ms cap → 480000). The soft deadline deterministically fires
  BEFORE the host hard kill (stop starting waves → drain in-flight → exit 0 +
  `partial:true`), turning every re-dispatch into a clean early-exit instead of a
  hard kill. Deliberately NO runtime cross-validation of the two flags (budget <
  call-timeout at worst delays exit by one call-timeout; still clean, still
  resumable — a hard check would manufacture fake failures under legal combos).
- **Progress sidecar (human-facing, zero orchestrator involvement)**: the dispatcher
  atomically writes `<init-dir>/fanout_progress.json` (stdlib tempfile + os.replace)
  after every wave and on every exit, with `{ts, host, total, done, failed, pending,
  wave, waves_run, wave_done_avg_s, eta_batches, state}`, `state ∈ {running,
  exited-partial, exited-clean}`. Watch it from a second terminal
  (`Get-Content -Wait`); `done` not moving for minutes with `state:running` = the
  hang signal for a HUMAN to act on. Counts derive from the same snapshot as the
  stdout summary (unit test asserts they agree); write failures warn on stderr and
  never break the run. The orchestrator and any agent NEVER read it (not a truth
  source; `resume_state.py`/`init_manifest.json` neither read nor validate it).
- **Out-of-host manual takeover (escape hatch, documented)**: dispatcher and
  orchestrator share the disk markers as the only truth source (naturally
  mutexed), so for large-repo long runs a human may run the same dispatcher
  command directly in a terminal (no host timeout clamp, per-wave stderr readable,
  sidecar still written), then `/mgh-init --resume` back in the session.
- Wiring: `core/prompts/fragments/init-stage/scout.md` call line now exemplifies
  `--time-budget-ms` + the MUST-be-below-host-timeout invariant + the manual-run
  exit; `core/scripts/discipline_core.py` `scout-fanout-dispatcher` recipe gains
  the re-dispatch timeout discipline (per-call `timeout` > `--time-budget-ms`);
  `docs/man/mgh-init.md` risk section explains long-run visibility in plain
  language. Tests: `tests/test_fanout_runner.py` grows default-value/invariant-doc
  assertions, sidecar existence/state/count-agreement cases, and fragment/recipe
  timeout-relation doc assertions. No disk schema change; zero new runtime deps.

### Added — `/mgh-init` scout wave dispatcher (`fanout_runner.py`, zero-LLM fan-out)

- The scout tier's wave loop (take pending → spawn N subagents → collect acks → page)
  moves out of orchestrator LLM turns into a deterministic stdlib leaf script
  `core/scripts/fanout_runner.py`. The orchestrator makes ONE `Bash` call (+ re-dispatch
  the same command while `partial:true`); inside, the script consumes
  `list_scout_batches.py --materialize` stdout, builds each subagent's task message from
  a FIXED template + verbatim field substitution, spawns host-CLI subprocesses in waves
  (`--wave`, default 5; ThreadPool + per-call timeout), parses bounded acks
  (`ok`/`oversize`/`failed`), and re-derives pending from disk markers after each wave.
  Task-message path-spelling failures (format drift / drive-root drift / underscore-name
  hallucination) become impossible by construction; wave boundaries cost zero LLM turns
  (~1–3K tokens/wave saved on large repos).
- Host spawn mapping (spike-verified on both hosts): opencode →
  `opencode run --agent init-scout-fanout "<task>"` (new `mode: primary` hidden twin of
  init-scout — `opencode run` refuses `mode: subagent` primaries and silently falls back
  to the default agent); claude → `claude -p "<task>" --agents <inline JSON>
  --allowedTools …` (stdin redirected). Host detection: `--host` explicit > opencode in
  PATH > claude in PATH; neither → exit 2 + fallback recipe and the orchestrator falls
  back to the existing per-wave manual dispatch (behavior unchanged, kept verbatim in the
  scout fragment as the fallback path).
- New task-message template `core/prompts/fragments/fanout/scout-task.md` (input fields +
  stage-prompt load instruction only; zero behavior-rule duplication — behavior stays in
  `stages/init-scout.md`). Per-spawn audit copies land at
  `<inputs-dir>/<batch_id>.task.md`; `--purge-audit --dry-run` lists them (list-only
  CLI surface; deletion via host shell after review).
- Dispatcher-side path-drift interception: every path field is `Path.resolve()`-anchored
  against `repo` BEFORE spawn; out-of-tree → that unit gets a `.failed` marker
  (reason=path-drift) and is never spawned (deterministic dual of the reader-side
  poisoned-input rejection). `.done`/`.failed` marker semantics, `--resume` idempotence,
  soft `--time-budget-ms` early-exit (`partial:true`, exit 0), and stdout-JSON /
  stderr-diagnostics split all follow the existing leaf-script contracts (R5.3/R5.4).
- Affected: `core/scripts/fanout_runner.py` (new) + `list_steps.py` (scout step now
  points at the dispatcher invocation) + `discipline_core.py` (scout gains a
  dispatcher-first path recipe); `core/prompts/fragments/fanout/scout-task.md` (new) +
  `fragments/init-stage/scout.md` (dispatcher-first dispatch section; manual path kept
  as fallback) + `stages/init-scout.md` + mirrored `releases/{claude-code/agents,
  opencode/agent}/init-scout.md` (source-of-fields wording: dispatcher path);
  `releases/opencode/agent/init-scout-fanout.md` (new); both `mgh-init.md` shells
  (component table row); `install.sh` self-check list + `tools/check_contracts.py`
  (fanout_runner flag assertions); `tests/test_fanout_runner.py` (new). Zero new runtime
  deps (stdlib subprocess/concurrent.futures); no on-disk schema change.

### Added — plain-language doctrine (audience declaration + human-facing assets)

- R3 now declares an **audience** for every artifact (human / agent / dual): human-facing
  files (man pages, glossary, proposal preambles) follow plain-language norms
  (phenomenon→cause→fix, terms defined on first use); agent-facing discipline (RFC-2119,
  NEVER chains, flag tables) stays byte-stable and is explicitly NOT softened. Proposals
  open with a `> **人话序**` blockquote (~200–300 chars: phenomenon → root cause → what
  changes → how to verify); `tools/check_plain_language.py` (stdlib) enforces the
  deterministic subset — missing preamble fails loud (exit 2), known coined-jargon and
  english-atom density WARN (exit 0), scoped to human-facing files only
  (`tools/plain_language_allowlist.txt` exempts 5 pre-doctrine changes).
- New human-facing assets: `docs/glossary.md` (seeded ~45 terms; "define before use" for
  human-facing prose) and `docs/man/<cmd>.md` ×5 (plain-language pages: what it does /
  what it touches / what it produces / honest boundaries). install.sh now lands
  `docs/man/` into target projects; the 10 command shells (5 × claude/opencode) each
  carry a one-line human-reader pointer.
- `check_distributed_purity.py::SCAN_DIRS` gains `docs/man/` — shipped md set stays
  identical to install.sh globs (166 files scanned clean). Regression:
  `tests/test_plain_language.py` (13 tests) + two new purity assertions (man pages clean;
  pointers present + clean).

### Changed — `/mgh-sast` pins s4 big-file slice outputs in-tree + absolute tool-script paths
- The s4 deep-dive big-file slice output (`chunk_sources.py --out`) — the sast-side fan-out
  gap left open by `harden-mgh-init-slice-and-tool-pinning` (its Non-Goals deferred sast to
  this adoption) — is now pinned to the project tree. `list_chunks.py` stdout `pending[]`
  each gains an additive ABSOLUTE `slice_dir` = `<target>/security-scan/slices/s4/<safe(chunk_id)>/`
  (`<命令输出目录>` = grandparent of `--checkpoints` = `<target>/security-scan`, same root as
  `checkpoint_path`; `_safe_name` sanitizes `/ \ :` — a no-op on clean vvah `chunk-NN` ids,
  defensive parity with init T1's NTFS-ADS guard). The orchestrator passes `slice_dir` verbatim;
  the sast-deepdive subagent writes `chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json`
  and re-reads that exact path — NEVER a relative `--out`, NEVER a cwd/system-temp-derived path
  (opencode subagent cwd can be `…\Temp\opencode\` → out-of-tree slice → unauthorized-`Read`
  prompt), NEVER out-of-tree. `chunk_sources.py` itself stays cwd-agnostic (no tree assumption);
  the pin lives in the contract + prompt layer.
- s4 deep-dive subagents now use the ABSOLUTE tool-script path pinned to the current install:
  `list_chunks.py` stdout gains a top-level `scripts_dir` = `Path(__file__).resolve().parent`
  (the running install's `<mgh-core>/scripts/`); the orchestrator reads it in s4 fan-out and
  passes `<scripts_dir>/chunk_sources.py` verbatim. Subagents NEVER use a bare `chunk_sources.py`
  name or a relative `.claude`/`.opencode/mgh-core/scripts/…` path (multi-layer install → can
  resolve to an older copy). Tool base is taken from `list_chunks.py` (s4 already calls it), not
  init-only `list_steps.py`; install-dir stays independent of `--target`.
- Affected: `core/scripts/list_chunks.py` (additive per-pending `slice_dir` + top-level
  `scripts_dir`); `core/contracts/sast/fanout-enumeration.md` + `core/contracts/init/unit-inputs.md`;
  `core/prompts/stages/s4-system.md` + mirrored `releases/{claude-code/agents,opencode/agent}/
  sast-deepdive.md`; both `mgh-sast.md` shells (s4 fan-out `slice_dir`/`scripts_dir` transmission,
  absolute `chunk_sources` recipe); `install.sh` self-check now also verifies the sast pipeline
  scripts (`list_chunks`/`list_verify_jobs`/`prefilter`/`dedup`/`emit_sarif`) are co-located.
  Additive stdout fields — no on-disk schema change (`checkpoint_path`/`input_path`/exit-code
  semantics unchanged); lite shell omits `slice_dir` (never fans out); zero new runtime deps.

### Changed — `/mgh-init` pins big-file slice outputs in-tree + absolute tool-script paths
- The scout/T1 big-file slice output (`chunk_sources.py --out`) — the one fan-out-adjacent
  path NOT already pinned by `harden-mgh-init-fanout-output-paths` — is now pinned to the
  project tree. `list_scout_batches.py` / `list_clusters.py` stdout `pending[]` each gain an
  additive ABSOLUTE `slice_dir` = `<target>/.mgh-init/slices/<tier>/<safe(unit_id)>/`
  (`<tier>` ∈ `scout`/`t1`; `<init-dir>` = grandparent of `--checkpoints`, same root as
  `checkpoint_path`; `cluster_id` `::` NTFS-ADS-sanitized via the existing `_safe_name`).
  The orchestrator passes `slice_dir` verbatim; the scout/induct subagent writes
  `chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json` and re-reads that exact path —
  NEVER a relative `--out`, NEVER a cwd/system-temp-derived path (opencode subagent cwd can
  be `…\Temp\opencode\` → out-of-tree slice → unauthorized-`Read` prompt), NEVER out-of-tree.
  `chunk_sources.py` itself stays cwd-agnostic (no tree assumption); the pin lives in the
  contract + prompt layer.
- Fan-out subagents now use the ABSOLUTE tool-script path pinned to the current install:
  the orchestrator derives it in step 0 from `list_steps.py` stdout `script_abs` (`__file__`-
  derived = the running install's `<mgh-core>/scripts/`) and passes it verbatim. Subagents
  NEVER use a bare `chunk_sources.py` name or a relative `.opencode`/`.claude/mgh-core/
  scripts/…` path — under a multi-layer install a relative tool path can resolve to a
  DIFFERENT (older) copy. Install-dir stays independent of `--target` (install in A, analyze B).
- Affected: `core/scripts/list_scout_batches.py` + `list_clusters.py` (additive `slice_dir`);
  `core/contracts/init/{scout-enumeration,cluster-enumeration,unit-inputs}.md`;
  `core/prompts/stages/init-{scout,induct}.md` + mirrored `releases/{claude-code/agents,
  opencode/agent}/init-{scout,induct}.md`; both `mgh-init.md` shells (step-0 tool-base recipe,
  fan-out `slice_dir` transmission, `chunk_sources` example → absolute path + `<slice_dir>`
  `--out`). Additive stdout field — no on-disk schema change (`checkpoint_path`/`input_path`/
  exit-code semantics unchanged); zero new runtime deps. mgh-sast's s4/deepdive same-shape gap
  is deferred to a follow-up `harden-mgh-sast-slice-path-pinning`.

### Changed — `/mgh-init` skips test source trees during discovery (`--include-tests` opt-in)
- The discovery file-enumeration layer (`expand_scope.walk_sources` / `collect_dir`, the
  single chokepoint consumed by regex candidates, `skeleton.json`, the call graph, and scout
  targets) **additionally** prunes test source trees by default, mirroring the existing
  dot-prefix prune. A test tree hits when the repo-relative posix path starts with
  `src/test/` / `src/tests/` (Maven/Gradle/Kotlin) **or** a directory segment (not filename)
  is in `{tests, __tests__, __mocks__, spec, specs}`. Bare singular `test` is **deliberately
  not** matched (collision risk: production `com/acme/test/` helper packages, Go `test`
  packages). Test code is net noise for finding existing **production** controls — mocks/stubs
  (`@MockBean SecurityConfig`, `mock(SecurityChecker)`) materialize pseudo-controls,
  deliberately-vulnerable fixtures (VulnerableApp, disabled-TLS / widened-CORS / placeholder-
  key / dummy-JWT-issuer test configs) hit as real control features, and test code never ships.
- `discover_controls.py` gains `--include-tests` (default off = exclude; passing it re-includes
  test sources, equivalent to before this change). Polarity asymmetry (design D2): the shared
  `walk_sources`/`collect_dir` default `include_tests=True`, so callers that don't pass it —
  including `mgh-sast`'s `build_call_graph` — stay byte-identical; only `discover_controls`
  (mgh-init) opts into exclusion. Excluding test code as an mgh-sast default is a separate
  later change (not bundled here).
- discover stdout summary (partial + full) gains `tests_skipped` (non-negative int), parallel
  to `dotfiles_skipped`; `controls_candidates.json` wrapper gains an additive top-level
  `tests_skipped` so `discover_controls.py --check` can validate it (R5.9: fail-loud exit 2 if
  missing/non-int/negative). `write_runconfig.py` records `include_tests` in `run_config.json`
  for stateless `--resume`. Both `mgh-init.md` shells (claude + opencode, mirrored verbatim)
  gain the flag-table row, the `write_runconfig`/`discover_controls` call examples, and a test-
  tree honesty-boundary line in `init_manifest.json::boundaries[]` / `report.md`. No disk
  schema change to `controls_candidates`/`clusters`/`skeleton` Candidate records (only an
  additive wrapper counter); no LLM-stage prompt change (prune is at the deterministic layer).

### Changed — `/mgh-init` tolerates partial fan-out unit failure (`.failed` terminal marker)
- A confirmed fan-out unit failure (scout reader batch / T1 cluster / T3 category subagent
  returning the existing `failed <reason>` ack) is now **terminal and non-blocking**: the
  orchestrator writes a `.failed` marker sibling to `.done` (`<checkpoint_path>.failed`, body
  `{unit,reason,tier}`), the unit is excluded from resume `pending` (NOT retried), and the tier
  completes when `done + failed >= total` (not `done >= total`). `list_clusters.py` /
  `list_scout_batches.py` / `list_rule_jobs.py` emit a `failed` count + a per-item absolute
  `failed_marker` (parallel to `done_marker`, verbatim-transmitted — never self-assembled);
  `resume_state.py` derives `tiers{<tier>}.failed`, surfaces non-zero failures in `notes[]`
  (a rate > half the tier is a loud `WARNING` advisory, never a gate), and `--check` flags a
  unit carrying both `.done` and `.failed` as an ambiguous-terminal violation (exit 2).
  Failures are disclosed in `init_manifest.json::failures` (per-tier `{done,failed,total}`) +
  `boundaries[]` + `report.md`, counts read from disk (`resume_state`/`list_*` stdout), never
  conversation memory. A crash without an ack leaves no marker → unit stays pending → retried
  (crash ≠ confirmed failure); escape hatch = delete the `.failed` marker then `--resume`.
  No new CLI flag (R5.1 surface frozen; `.failed` read by glob, written via `Write` to the
  verbatim `failed_marker` path). Stage prompts + dual-shell agent defs updated to "touch
  nothing on failure, emit only the `failed` ack". Original (no `.done` ⇒ tier never completes
  ⇒ pipeline blocks, or indiscriminate retry) is the failure-shape being fixed.

### Changed — `/mgh-init` fan-out waves run to completion (no scale-driven mid-run interruption)
- Both `mgh-init.md` shells (claude + opencode, mirrored verbatim) gain a run-to-completion
  directive in the Re-entrancy & compaction section: during a fan-out wave (scout reader /
  T1 induct / T3 rulewriter) the orchestrator **MUST NOT** pause to ask the user whether to
  split / skip / abort on account of scale, and **SHALL** iterate the `list_*` pending
  work-list at `max_concurrent` until `pending` is empty. Scale and boundary facts (large
  fan-out count, partial coverage, `.failed`/skipped units, residual blind spots) **SHALL**
  flow into the existing disclosure channel — `init_manifest.json::boundaries[]` + `report.md`
  + `resume_state.py` `notes[]` — never as a mid-run blocking question; counts are read from
  disk (`resume_state.py`/`list_*` stdout), never conversation memory. The legitimate
  **pre-run** i0 advisory (`--large-repo-threshold` → suggest `--scope`+`--merge`, before
  tokens are spent) is explicitly preserved and distinguished from the mid-wave directive.
  Prompt-wording only: no new CLI flag, script, contract, hook, or stage-prompt change.

### Changed — runtime hook enforcement hardened (env-or-sentinel activation + runtime scripts read-only + init write confinement)
- **Disk-sentinel activation closes the opencode reliability boundary.** The shared guard
  `block_adhoc_scripts.py` now activates inside an mgh run-domain when **EITHER** env
  `MGH_{INIT,SAST,SRA,SRR}_ACTIVE=1` **OR** a disk sentinel `<cwd>/<run-root>/.active` exists
  (init→`.mgh-init`, sast→`security-scan`, sra→`.mgh-sra`, srr→`.mgh-srr`). The opencode `.ts`
  plugin process does not inherit mid-session bash-exported env, so env-only activation left the
  opencode guard dormant for a whole run; the sentinel (visible to the plugin via disk) closes
  that hole. Sentinel JSON `{domain,target,out_roots[],v}`, written by the orchestrator at step 0
  via Bash, removed on completion/clean-stop. New contract `core/contracts/hooks/runtime-enforcement.md`;
  new shared spec `runtime-hook-enforcement` (single source replacing scattered per-command hook wording).
- **Runtime scripts read-only (whitelist removed + script-extension set).** When active the guard
  blocks `Write`/`Edit` of any extension in `{.py,.ps1,.sh,.bash,.zsh,.bat,.cmd,.ts,.js,.mjs,.cjs}`
  with **no** path whitelist — the prior `core/scripts`/`mgh-core/scripts` + `tests`/`tools`/`hooks`
  exemptions only mattered while inactive (install/dev), at which point `main()` already exits 0.
  Leaf scripts are read-only for the orchestrator at runtime. Closes the "agent edits
  `list_clusters.py`" and "`process_*.ps1` leaks past `.py`-only" failure shapes.
- **`/mgh-init` write confinement to sanctioned subtrees.** The init domain upgrades
  out-of-tree interception to a positive allowlist: `Write`/`Edit` MUST land in
  `<target>/.mgh-init/**` / `.claude/rules/**` / `docs/security-controls/**` / `AGENTS.md` /
  sentinel `out_roots[]` — so in-tree root pollution (`temp_clusters*.json`, `process_*.ps1`) also
  fails loud. sast/sra/srr retain the out-of-tree check. `MGH_TARGET` precedence: env > sentinel.target
  > degrade. Sentinel `target` is sourced from Python leaf-script stdout (Windows-native; never bash
  `pwd`, whose MSYS `/c/…` mis-resolves in pathlib).
- **Tests:** `test_block_adhoc_scripts.py` flips the whitelist PASS tests to BLOCK, adds sentinel
  activation (env unset), sentinel-carried-target subtree block, script-ext set, init root-pollution
  block + sanctioned-subtree/out_roots pass, stale/degrade; `test_opencode_hook_parity.py` adds
  byte-identity-of-new-logic + opencode sentinel-activation checks. The `.ts` shim stays glue-only.

### Added — `/mgh-init` context resilience (re-entrant resume + bounded ack + aggregate hard-budget)
- **Re-entrant orchestrator resume state.** New `core/scripts/resume_state.py` derives the
  pipeline's current step + exact next action **purely from on-disk artifacts** (`<target>/.mgh-init/`
  products + per-tier `.done` + `run_config.json`), independent of conversation memory. compact /
  crash / new-session collapse into one recovery path: `/mgh-init --resume` whose **first action is
  `resume_state.py`**. `--check` validates on-disk self-consistency (exit 2 on violation). New
  `core/scripts/write_runconfig.py` atomically writes the start-state intent `run_config.json` at
  step 0 so resume is stateless of re-typed flags. See `core/contracts/init/resume-state.md`.
- **Bounded subagent return-to-orchestrator ack.** All 9 `init-*.md` stage prompts + dual-shell
  `agents/init-*.md` declare the final message as a single bounded ack (`ok <abs path> <count>` /
  `oversize` / `failed`) — NEVER echo the record body (which monotonically bloated orchestrator
  context across fan-out). The 5 whole-tier stages (survey/scout-merge/scout-audit/synthesis/
  rules-consistency) also moved to orchestrator-given absolute-path-verbatim output.
- **Aggregate hard-budget via map-reduce.** New `core/scripts/plan_aggregate.py` makes
  `--max-aggregate-bytes` a HARD gate at T2 (`init-synthesis`) and scout-merge (`init-scout-merge`):
  ≤ budget → single-context (byte-identical, zero regression); > budget → two-pass map-reduce
  (per-shard ≤ budget → single rollup over summaries). Replaces the prior "disclose + fallback"
  soft boundary for those two nodes (T4 rules-consistency remains soft-bounded). See
  `core/contracts/init/aggregate-sharding.md`.
- **Re-entrancy & compaction section** in both `mgh-init.md` shells: disk is the progress source of
  truth, conversation memory is only a cache; resume/compact first action is `resume_state.py`;
  context-tight clean-stop + new-session resume is preferred over manual `/compact`.
- `AGENTS.md` R5.4 / R5.5① sharpened (orchestrator-level re-entrant resume state + step-query
  recipe). `init_manifest.json` version bumped 6 → 7; `boundaries[]` reflects the hard-threshold.

### Changed
- **Restructured `AGENTS.md` R5(Agent 工具命令稳定性)for readability — 零规范内容删除。**
  跨处复述的机制去重到单一归宿(长跑可恢复 → R5.4;opencode env 不继承 → R5.7 段 B;退出码 `0/1/2`
  定义 → R5.3(b) 单次);R5.7 拆「段 A 评估方法论 + 段 B hook 强制闭环」;R5.3(b) fan-out 提升为子项;
  修 R5.5 ⑤ 孤儿 indent;合并重复的「理由须随规保留」样板为前言一行;修剪纯回声 `承 R5.x`。加 R5 头部
  「强制面索引表」。编号 R5.1–R5.10 不变。详见 change `simplify-agents-r5`。

### Added
- **Bounded per-request context for `/mgh-sra` fan-out (`request-context-budget` adoption).**
  `prepare_augment.py` now materializes each capability's complete input to its own bounded file
  and the orchestrator carries only a slim, paged work-list (it no longer whole-reads
  `change_context.json` into its context). New on `prepare_augment.py`: `--materialize <dir>`
  (writes `<change-root>/.mgh-sra/inputs/augment/<cap>.input.json` = that cap's requirements +
  per-cap business surface + the `candidate_controls` file_overlap slice + memory; `pending[]`
  becomes a slim envelope carrying `input_path`/`bytes`/`oversize`), `--offset`/`--limit` paging
  reporting `effective_limit`/`shrunk`, and `--max-unit-bytes` (192 KB; an oversize capability is
  flagged + recipe'd to split the change / `--focus` narrow — never sharded, the capability is the
  a3 atom) / `--orch-budget-bytes` (64 KB; a page over it is auto-tightened). `sra-augment` reads
  its own `input_path` (NEVER the whole `change_context.json`); the full `change_context.json`
  stays on disk for the a2 single-context whole-change scan. `sra-clarify`/`sra-consistency` gain a
  P0 soft-boundary disclosure guardrail for their aggregate inputs (`--max-aggregate-bytes`,
  256 KB — over it they advise `--focus`/split-change and surface it in
  `sra_manifest.json::boundaries[]`, non-blocking). `tools/check_contracts.py` asserts the new
  flags (R5.1); tests cover per-cap materialize (file_overlap slice)/paging/oversize + the
  whole-read discipline regression. (This lands the engine-stage `input_path` consumption the srr
  adoption deferred; the cross-cutting `request-context-budget` spec is the contract.)
- **Bounded per-request context for `/mgh-srr` fan-out (`request-context-budget` adoption).**
  The srr intake adapter now materializes each review unit's complete input to its own bounded
  file and the orchestrator carries only a slim, paged work-list (it no longer whole-reads the
  sra-shape `change_context.json` into its context). New on `ingest_requirements.py`:
  `--materialize <dir>` (writes `<out>/inputs/augment/<unit>.input.json`; `pending[]` becomes a
  slim envelope carrying `input_path`/`bytes`/`oversize`), `--offset`/`--limit` paging reporting
  `effective_limit`/`shrunk`, and `--max-unit-bytes` (192 KB; an oversize unit is flagged +
  recipe'd to `--split`/narrow the doc — never sharded, the unit is the review atom) /
  `--orch-budget-bytes` (64 KB; a page over it is auto-tightened). The reused sra engine stage
  reads its own `input_path`; the full sra-shape `change_context.json` stays on disk for stage
  consumers. `render_report.py` gains `--max-aggregate-bytes` (256 KB; P0 soft boundary — over
  it the aggregate draft input is disclosed in `srr_manifest.json::boundaries[]` + the report,
  non-blocking). `tools/check_contracts.py` asserts the new flags (R5.1); tests cover
  materialize/page/`--split`/oversize + the whole-read discipline regression. (Engine-stage
  consumption of `input_path` lands with the `/mgh-sra` adoption; intake-side lands independently.)
- **Bounded per-request context for `/mgh-sast` fan-out (`request-context-budget` adoption).**
  The s4/s6 enumeration scripts now materialize each fan-out unit's complete input to its own
  bounded file and the orchestrator carries only a slim, paged work-list (it no longer
  whole-reads `s3_chunks.json`/`s5_filtered.json` into its context). New on `list_chunks.py`:
  `--materialize <dir>` (writes `<repo>/security-scan/inputs/s4/<chunk>.input.json` = that chunk's
  `files[]` + `threat_id` + `hypothesis` + `needs_slice`; `pending[]` becomes a slim envelope
  carrying `input_path`/`bytes`/`oversize`/`needs_slice`), `--offset`/`--limit` paging reporting
  `effective_limit`/`shrunk`, `--max-unit-bytes` (192 KB; an oversize chunk — input over budget OR
  a source file over `--big-file-bytes` — is flagged + its big files listed in `needs_slice[]` for
  `chunk_sources` slicing, never the whole file fed to the LLM) / `--orch-budget-bytes` (64 KB; a
  page over it is auto-tightened), plus `--repo`/`--big-file-bytes` (200 KB) for computing
  `needs_slice`. `list_verify_jobs.py` mirrors this for s6 (`inputs/s6/<finding_id>.input.json` =
  the full finding record; an oversize finding is flagged + recipe'd to `--scope` narrow — never
  sliced, the finding is the s6 verify atom). `sast-deepdive`/`sast-verify` read their own
  `input_path` (NEVER the whole `s3_chunks.json`/`s5_filtered.json`). `mgh-sast.md` (claude +
  opencode) gains the orchestrator-discipline recipe, the s4/s6 materialize→page→pass-`input_path`
  flow, the `--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes` flag table (s1 scope /
  s2-s3 hypothesis aggregate = P0 soft boundary — over it advise `--scope`/`--diff` and surface in
  `run_manifest.json::boundaries[]` + `report.md`, non-blocking), and the `inputs/` output.
  `tools/check_contracts.py` asserts the new flags (R5.1); tests cover per-chunk/per-finding
  materialize (needs_slice/oversize)/paging + the s3/s5 whole-read discipline regression. (The
  cross-cutting `request-context-budget` spec is the contract; the `block_adhoc_scripts` hook
  already covered `MGH_SAST_ACTIVE` from the foundation — no hook change.)
- **`docs/r5-plain-language.md`**(dev-only,不分发)—— R5.1–R5.10 大白话逐条(说什么 / 为什么 /
  违反后果 / 兜底),作 AGENTS.md(AI 面向)的人类桥梁 + 去重后防单点灭失的第二副本。

### Fixed
- **`/mgh-init` scout→merge fold-in aborted with `KeyError: "file"` when a scout candidate
  lacked its `file` field** (raw traceback, the whole merge halted) — unlike `category`, which
  `merge_scout._normalize` already tolerated (skip + warn). `file` is now treated the same as
  `category`: a missing/empty `category` OR `file` makes `_normalize` return `None`, the caller
  skips that one candidate and warns (naming which required field is missing — `category` /
  `file` / both, plus the candidate `index` and any available `file:line`), and the merge
  continues. All `_normalize` field access is now `.get` (no direct-indexed required field
  remains). Defense-in-depth for when `merge_scout.py --check` is bypassed (orchestrator
  context pressure / a hand-crafted malformed `scout_candidates.json`); the `--check` gate,
  stdout/stderr/exit-code CLI contract are unchanged. Covered by `tests/test_merge_scout.py`.
- **`/mgh-init` T1 subagent `write_text` of `checkpoint_path` failed with `OSError [Errno 22]
  Invalid argument` on Windows NTFS** when `cluster_id` (or `<cid>::shard-<n>`) contained `::`
  — NTFS's Alternate-Data-Stream separator. `list_clusters.py::_paths` built the checkpoint
  filename from the **raw** `unit_id`, unlike the input filename which was already
  `_safe_name`-sanitized (`/ \ :` → `_`) — a same-source latent bug (the test helper `_mark_done`
  already sanitized, diverging from production). `_paths` now encodes the filename component via
  `_safe_name` (same function, same paradigm as `_write_unit`/`_shard_hit_count`); the canonical
  `unit_id` (with `::`) is preserved verbatim as the slim-envelope `cluster_id` field and the
  checkpoint record's `unit` field, so done detection / resume matching (which reads `unit`, not
  the filename) are unaffected. See `core/contracts/init/cluster-enumeration.md`,
  `openspec/changes/fix-mgh-init-ntfs-unit-filename/`. Covered by `tests/test_init_clusters.py`.

### Dev-meta
- **Q1 决策:**AGENTS.md 改动**不**触发分发版本 bump —— AGENTS.md 是研发手册,在 install 分发集之外
  (`SCAN_DIRS` 排除;无 VERSION 字段,版本追踪仅 CHANGELOG)。记于此,不作为 release 切出。
- **行数实际:**R5 段 97 → ~114 行(未达 design 估的 70–75)。强制面索引表(~13 行)抵消了去重收益;
  真实收益是可读性(去重 + 拆段 + 索引 + 修孤儿),非行数。

## [0.1.12] — 2026-07-27

### Added
- **Bounded per-request context for `/mgh-init` fan-out (`request-context-budget`).** The
  orchestrator no longer whole-reads a multi-unit aggregate into its context (observed: an
  opencode host reading the 426 KB `t1_pending`-style work-list whole, bloating every
  subsequent model request). Every fan-out tier now materializes each unit's complete input
  to its own bounded file and the orchestrator carries only a slim, paged work-list. New
  three-tier byte budgets (defaults; unit = bytes, a conservative upper bound for tokens):
  - **Per-unit materialization** — `list_clusters` / `list_scout_batches` / `list_rule_jobs`
    gain `--materialize <dir>`: each T1 cluster / scout batch / T3 category's complete input
    record is written to `<target>/.mgh-init/inputs/<tier>/<unit>.input.json` (idempotent,
    `--resume`-reused). `pending[]` becomes a slim envelope carrying `input_path` / `bytes` /
    `oversize` (no variable-length payload). The stage subagent (`init-induct` / `init-scout`
    / `init-rulewriter`) reads its own `input_path`; the orchestrator only passes the path.
  - **Configurable byte budgets** — `--max-unit-bytes` (192 KB; oversize clusters sharded
    into `<cluster_id>::shard-<n>`, scout batches / T3 categories flagged `oversize`),
    `--orch-budget-bytes` (64 KB; a work-list page exceeding it is auto-tightened with
    `shrunk:true`), `--max-aggregate-bytes` (256 KB; T2/merge/T4 aggregate stages — P0 soft
    boundary: disclose + advise `--scope`/`--merge`; layered reduction is a later change).
  - **Paging** — all three enumeration scripts gain `--offset` / `--limit` and report
    `effective_limit` / `shrunk`; the orchestrator pages rather than loading the whole list.
  - **Defense-in-depth hook** — `block-adhoc-scripts` (both platform twins, byte-identical;
    the opencode `.ts` shim stays pure glue) now also blocks a shell whole-read
    (`cat`/`head`/`tail`) of a multi-unit aggregate in any of the four run-domains, with a
    recipe pointing at `list_* --materialize` `input_path`. The structural fix is the primary
    lever; the hook is residual defense. (`/mgh-sast` / `/mgh-sra` / `/mgh-srr` adoption is
    deferred to follow-up changes — this release lays the cross-cutting capability and the
  `init` reference implementation.)
- **New contract** `core/contracts/init/unit-inputs.md` documenting the per-unit
  materialization schema and the four-command path conventions.
- **`init_manifest.json` version 5 → 6** (additive): `boundaries[]` gains the request-context-
  budget disclosure.

### Changed
- `init-induct` / `init-scout` / `init-rulewriter` prompts: input is now the bounded
  `input_path` file (with a NEVER-whole-read-aggregate hard rule). `init-synthesis` /
  `init-scout-merge` / `init-rules-consistency` gain a P0 aggregate-context-budget guard.
- `tools/check_contracts.py` asserts the three `list_*` scripts declare the new flags and
  the `/mgh-init` shells advertise `--max-aggregate-bytes`.

## [0.1.11] — 2026-07-23

### Added
- **Discover resilience against host shell timeouts (`/mgh-init`).** `discover_controls.py`
  no longer assumes a single host call finishes — it checkpoints a built call graph under
  `<out>/cache/` and resumes across runs, so a large repo (or an opencode/claude shell
  timeout mid-scan) is no longer total loss. New flags (all additive; defaults preserve
  prior behavior):
  - **Call-graph cache** — `<out>/cache/callgraph.json` + `manifest.json` (per-source
    `mtime`/`size` freshness). A re-run with an unchanged repo hits the cache and skips
    the two regex passes (stdout `cache_hit: true`). `--rebuild-cache` forces a rebuild
    (this flag was already advertised in the shells but was previously a dangling
    contract — it is now real and `--help`-exposed).
  - **Scan resume** — `<out>/cache/scan_progress.json` checkpoints every
    `--progress-every` files. `--resume` reuses the cache and continues scanning from the
    checkpoint without rescanning; deterministic + idempotent (resume == one-shot candidate set).
  - **Soft time budget** — `--time-budget-ms <N>` (default `0` = off). When set, discover
    stops at a safe boundary (after the call graph is built; every `--progress-every`
    files — never mid-write), persists the cache + checkpoint, and exits **0** with stdout
    `partial: true` + `resume_hint`. The orchestrator re-dispatches `--resume` until
    `partial: false`.
  - **Atomic writes** — all product JSON (`controls_candidates`/`clusters`/`skeleton`/
    `cache/*`) is written `.tmp` + `os.replace`, so a SIGKILL mid-write leaves no truncated
    artifact (`--check` never sees a broken file).
- **Per-call `timeout` recipe across all four command shells.** The `mgh-init`/`mgh-sast`/
  `mgh-sra`/`mgh-srr` orchestrators (claude + opencode) now instruct the host to pass a
  generous per-call `timeout` to long-running deterministic Bash calls, and disclose the
  opencode global `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` (default 120000; must be
  ready before opencode launches — mid-session `export` is not inherited). `mgh-init` also
  adds the `partial: true` → Bash re-dispatch `--resume` loop (never a wrapper `.py`).

### Changed
- `discover_controls.py`: the materialized source list is sorted by repo-relative path so
  the scan checkpoint index is reproducible across runs; `scan()` keeps its 6-tuple API (a
  new `run_discover()` carries the cache/resume/budget knobs). `main()` skips writing final
  products on a partial exit (only `cache/` + `scan_progress.json` land). All additive — no
  final-product schema change; `--time-budget-ms 0` and a missing cache are byte-equivalent
  to before.
- `AGENTS.md` R5.3(c) (deterministic-script recoverability) + R5.4 (per-call timeout +
  discover soft-budget re-dispatch) sharpened; `README.md` gained a host-shell-timeout
  section; new contract `core/contracts/init/discover-cache.md`; `core/contracts/init/
  candidates.md` stdout summary extended with `partial`/`resume_hint`/`cache_hit`.

### Verified
- `tests/test_discover_resilience.py` (14 tests): cache hit + equivalence, mtime/size
  invalidation, `--rebuild-cache`, midpoint-resume equivalence + idempotency, checkpoint
  preservation when the budget trips at the callgraph boundary (regression), clean partial
  exit (exit 0, no truncated product), atomic writes, `--check` after a run. Plus a
  synthetic 150-file repo converging via repeated `--resume` to the one-shot candidate set.
- Full suite green (426 tests); `tools/check_contracts.py` (now asserts the discover flags
  in `--help`) and `tools/check_distributed_purity.py` both clean; zero-runtime-dep AST scan
  clean (`os`/`time` are stdlib).

## [0.1.10] — 2026-07-20

### Added
- **Sensitive-data catalog (`--sensitive-catalog`) for `/mgh-sra` + `/mgh-srr`.** Both commands now
  accept `--sensitive-catalog <inline-json|@path|->` to declare a **company masking policy** — the
  field types that MUST be masked, each with a `mask` level (`full` / `partial`) and a rule (e.g.
  "保留后 4 位"). This extends sensitive-data recognition **beyond the legacy 6 facets**
  (id-card / bank-card / phone / email / password / token) and drives **per-item masking-gap
  detection**: for each catalog field type, the reused a2/a3 subagents check whether it is masked
  per its rule at-rest / in-transit / log / response. The default is unchanged: omit the flag =
  legacy 6 facets only (byte-equivalent behavior, a hard backward-compatibility gate). The catalog
  is **orthogonal to `--focus`** (focus narrows *which dimensions*; the catalog declares *what must
  be masked*) and the two may be passed together.
  - **New deterministic script `core/scripts/sensitive_catalog.py`** — the closed-set single source
    of truth for the 10 PIPL / GB-T 35273 categories (identity-doc / biometric / health / financial
    / location / communication / device / vehicle / general-pii / legal) and the `{full, partial}`
    mask enum; ships a **37-item default template**. CLI: `--list` / `--parse` / `--check`. Closed-set
    violations (unknown category, illegal mask, malformed `<category>/<field-type>` key, missing
    label, non-int `version`) exit **2** with an actionable message; malformed JSON / missing file
    / unreadable stdin exit **1**. Renders a **deterministic** Simplified-Chinese policy directive
    (registry order, not input order). Zero runtime deps (stdlib only), self-locating sibling
    import; stdin read as UTF-8 on any console.
  - **`prepare_augment.py` + `ingest_requirements.py`** parse + closed-set-validate
    `--sensitive-catalog` in the deterministic a1/r1 stage (before any LLM token) via the shared
    `sensitive_catalog` module, and embed the resolved `sensitive_catalog`
    (`{version, source, categories[], items[], counts{}, directive}` or `null`) as a new top-level
    `change_context.json` field. Their `--check` validates the field shape (null allowed).
  - **Shared prompt overlay** in `sra-clarify.md` + `sra-augment.md`: when the orchestrator passes a
    non-null `sensitive_catalog`, the subagents expand the sensitive-data pass to per-item masking
    gaps (anchored to a concrete requirement/endpoint/field, tagged `catalog_key`), and link a gap
    to a `data-masking` control via the existing three-signal matching (advisory — a gap is never
    dropped for lack of a matching control). `/mgh-srr` reuses these prompts verbatim → obtains the
    behavior with **zero new prompts**.
  - **mgh-init linkage (consumption only)**: catalog-driven masking gaps reuse the existing
    `data-masking → sensitive-data` dimension mapping already in `prepare_augment.py`; **no change
    to mgh-init** discovery / inventory schema / rules.
  - **Disclosure**: the orchestrator-written `sra_manifest.json` and `render_report.py`'s
    `srr_manifest.json` carry a `sensitive_catalog` field (`counts` + `source`, or null); when a
    catalog is active, a boundary line states **masking gaps were checked per the company catalog
    items; field types outside the catalog were recognized only via the legacy 6 facets**, and the
    srr report header notes the catalog coverage.
  - **Shipped `.example` template**: a committed `core/scripts/sensitive_catalog.json.example`
    (the 37-item PIPL/GB-T 35273 template) is the canonical artifact; `install.sh` copies it to
    `.mgh-sra/sensitive_catalog.json.example` in the target project. It is **not auto-applied** —
    the company must `cp` it to `sensitive_catalog.json` or pass `--sensitive-catalog @<path>` to
    activate (backward-compat gate).
  - New contract `core/contracts/sensitive-catalog.md`; `core/contracts/sra/augmentation.md` +
    `srr/intake-report.md` document the new field; `security-dimensions.md` notes the catalog as the
    6-facet extension point.
  - New tests: `tests/test_sensitive_catalog.py` (registry / parse / closed-set violations / exit
    codes / determinism / input forms incl. stdin / anti-drift: 37-items + committed `.example`
    matches `DEFAULT_TEMPLATE` / zero-deps AST); `--sensitive-catalog` + `--check` coverage added
    to `test_sra_prepare.py`, `test_srr_ingest.py`; `test_zero_deps.py` asserts
    `sensitive_catalog.py` is scanned.

### Changed
- Four command shells (claude/opencode × sra/srr): `--sensitive-catalog` in the param/flag tables,
  orchestration flow (read `change_context.sensitive_catalog`, pass verbatim into a2/a3), bash
  examples, and an "Always disclose" catalog-coverage line. `tools/check_contracts.py` asserts the
  new flags; `tools/check_distributed_purity.py` confirms the shipped md stay clean (R5.10).

### Known limitation (honest boundary)
- Per-item masking-gap detection is enforced by a **prompt overlay** (non-deterministic guardrail),
  not a hard filter — the closed-set category/mask validation, the `change_context` embedding, and
  the `--check` layers are deterministic, but which catalog items actually surface a gap depends on
  the LLM pass. The catalog is **not** an exhaustive sensitive-field list (out-of-catalog fields use
  only the 6 facets); this is disclosed in the manifest/report boundary.

---

## [0.1.9] — 2026-07-16

### Added
- **Dimension focus (`--focus`) for `/mgh-sra` + `/mgh-srr`.** Both commands now accept
  `--focus <inline-json|path>` to **narrow** the per-dimension security scan to a subset of
  the 9 dimensions, and — for the two dimensions whose catalog enumerates discrete
  sub-categories — to a per-dimension facet whitelist. The default is unchanged: omit the
  flag = scan all 9 dimensions (byte-equivalent behavior, a hard backward-compatibility
  gate).
  - **New deterministic script `core/scripts/focus_scope.py`** — the closed-set single
    source of truth for the 9 dimension keys + the `sensitive-data` (id-card / bank-card /
    phone / email / password / token) and `injection` (sqli / xss / command-injection /
    path-traversal / ssrf / deserialization / xxe) facets; the other 7 dimensions have no
    facets (whole-dimension focus). CLI: `--list` / `--parse` / `--render` / `--check`.
    Closed-set violations (unknown dimension/facet, facet on a facet-less dimension, facet
    for a dimension not in `dimensions`, empty `dimensions`) exit **2** with an actionable
    message; malformed JSON / missing file exit **1**. Renders a **deterministic**
    Simplified-Chinese directive (registry order, not input order; byte-identical across
    runs); all-9 resolves to `null` (no narrowing). Zero runtime deps (stdlib only),
    self-locating sibling import.
  - **`prepare_augment.py` + `ingest_requirements.py`** parse + closed-set-validate
    `--focus` in the deterministic a1/r1 stage (before any LLM token) via the shared
    `focus_scope` module, and embed the resolved `focus` (`{dimensions[], facets{},
    directive}` or `null`) as a new top-level `change_context.json` field. Their `--check`
    validates the `focus` field shape (polymorphic in sra: inventory OR change_context).
  - **Shared prompt overlay** in `sra-clarify.md` + `sra-augment.md`: when the orchestrator
    passes a non-null `focus.directive`, both subagents restrict their per-dimension pass
    to the listed dimensions/facets and emit nothing out-of-scope; in-scope anchoring /
    three-signal / codegraph rules are unchanged. `/mgh-srr` reuses these prompts verbatim
    → obtains the behavior with **zero new prompts**.
  - **Disclosure**: the orchestrator-written `sra_manifest.json` and `render_report.py`'s
    `srr_manifest.json` carry a `focus` field (dimension list or null); when focused, a
    boundary line states **only the focused dimensions were scanned; out-of-scope
    dimensions were not covered**, and the srr report header notes the in-scope dimensions.
  - **Catalog annotated**: `security-dimensions.md` now tags the facet keys inline on the
    `sensitive-data` / `injection` rows, in lockstep with the registry (anti-drift asserted
    by `test_focus_scope.py`).
- New tests: `tests/test_focus_scope.py` (registry / parse / closed-set violations / exit
  codes / determinism / input forms / anti-drift); `--focus` + `--check` coverage added to
  `test_sra_prepare.py`, `test_srr_ingest.py`, `test_srr_report.py`.

### Changed
- Four command shells (claude/opencode × sra/srr): `--focus` in the param/flag tables,
  orchestration flow (read `change_context.focus.directive`, pass verbatim into a2/a3),
  bash examples, and an "Always disclose" focus-scope line. `tools/check_contracts.py`
  asserts the new flags; `tests/test_zero_deps.py` asserts `focus_scope.py` is scanned.

### Known limitation (honest boundary)
- The narrowing is enforced by a **prompt overlay** (non-deterministic guardrail), not a
  hard filter — a focused run could in principle still emit a range-adjacent gap. Residual
  non-determinism is disclosed the same way as the existing prompt-guardrail boundaries;
  the closed-set / embedding / `--check` layers are deterministic. Focusing too narrowly
  can miss real gaps — this is the user's explicit choice, disclosed in the manifest/report.

---

## [0.1.8] — 2026-07-15

### Added
- **`/mgh-srr` — freeform-text security requirements review (no openspec needed).** A new command
  for the common case where requirements arrive as raw text (word/txt/md/excel or pasted) with no
  openspec structure — and possibly no concrete interfaces/fields at all. It is a **port-adapter
  over the `/mgh-sra` middle engine**: a deterministic input adapter (`ingest_requirements.py`)
  extracts the doc into an sra-shape `change_context.json`, the existing sra engine (sra-clarify /
  sra-augment / sra-consistency + 9 dimensions + three-signal control reuse + batched clarification
  + project memory) is **reused verbatim with zero new prompts**, and a deterministic output adapter
  (`render_report.py`) renders a plain, brief Simplified-Chinese `security_review_report.md` +
  `srr_manifest.json` that **never touches openspec/**.
  - **Mixed three-tier input**: `.txt/.md/.csv/.json` read natively (perfect); `.docx`/`.xlsx`
    best-effort via stdlib `zipfile` + `xml.etree` (joining all `<w:t>` within each `<w:p>` so text
    never token-fragments) with **explicit degradation flags** (dates-as-serial / list-markers /
    embedded-objects / merged-cells); a permanent `--text` / stdin **passthrough** escape hatch
    (zero degradation). Unsupported formats (`.doc`/`.xls`/scanned PDF/encrypted) exit 2 with a
    conversion recipe and emit no partial artifact.
  - Interfaces / fields / roles are **optional, non-load-bearing hints** (freeform text may have
    none); the LLM reads the full text and anchors gaps to section headings. Default = one review
    unit; `--split` fans out per markdown `#`/`##` heading (script-enumerated fan-out).
  - **Shares** `<project>/.mgh-sra/business_context.json` with `/mgh-sra` (one accumulating file
    across both tools; same schema, contract unchanged). Optional codegraph enrichment is inherited
    from the reused sra engine (`--no-codegraph` opts out, reproducing pre-codegraph behavior).
  - **Runtime discipline**: a new `MGH_SRR_ACTIVE` run-domain on the **unchanged**
    `block-adhoc-scripts` guard (claude PreToolUse + opencode `.ts` plugin, byte-identical twin),
    covering the review dir + shared project memory under `MGH_TARGET`. Same fail-soft reliability
    boundary on opencode as the other domains.
- Zero new runtime dependencies (R2): `.docx`/`.xlsx` use only the Python standard library. SRR
  reuses all sra stage prompts + fragments + `merge_memory.py` (no duplication — asserted by the
  new `test_mgh_srr_codegraph_parity.py` reuse-not-duplication tests).

### Known limitation (honest boundary)
- `/mgh-srr` input extraction is best-effort for `.docx`/`.xlsx` (dates / formats / list markers
  degraded — flagged in the report); review coverage is bounded by input completeness, so a vague
  requirement document yields only sparse, anchor-light gaps. The `--text`/stdin passthrough has no
  degradation. All other sra boundaries (LLM candidates need human review; controls asserted to
  exist not to be effective; memory is user-asserted; codegraph is optional advisory) apply unchanged.

---

## [0.1.7] — 2026-07-15

### Added
- **Optional codegraph enrichment for `/mgh-init` and `/mgh-sra` (coordinated pair).**
  When the target project has a precomputed codegraph index (`<target>/.codegraph/`)
  **and** the `codegraph` tool on PATH, both commands use it as an optional,
  detection-gated enrichment backend consumed entirely in the **LLM layer** — never
  `import`ed by any `.py`, so zero new runtime dependencies (R2) and zero changes to the
  deterministic script contracts (R5.3). Detection defaults to `auto`; `--no-codegraph`
  opts out and reproduces pre-codegraph behavior exactly (fail-soft).
  - **`/mgh-init`**: a new optional `init-resolve` stage (codegraph-gated, single context)
    resolves the framework-routed / DI / AOP / interface→impl / reflection controls the
    text/AST call graph collects into `unresolved[]`, emitting additive
    `source:"codegraph"` candidates with a real `resolved_path[]`. scout/induct/survey
    stages prefer `codegraph_explore` (MCP) / `codegraph explore` (CLI) for surgical
    context. `init_manifest.json` gains a `codegraph:{available,used,resolved_count,
    unresolved_residual}` block.
  - **`/mgh-sra`**: `sra-augment` (a3) gains an inline **call-path structural-evidence
    confirmation** — for gaps that already matched all three reuse signals, codegraph
    confirms whether the recommended control is actually wired onto the gap endpoint's
    request path, recorded as advisory `recommended_control.call_path:{confirmed,
    path[],source:"codegraph",note}` (plus data-flow / liveness / domain-sibling
    advisory facets). This upgrades signal-2 "business-domain similarity" from a semantic
    guess toward structural evidence, directly targeting SRA's "controls are asserted to
    exist, not to be effective" blind spot. Bounded + fail-soft (top-1 control per gap
    under budget; `confirmed` never fabricated; never overrides code evidence or user
    `business_context.json`). `sra_manifest.json` gains `counts.call_path_confirmed` /
    `call_path_residual` + a 5th honesty boundary; the existing four stay intact.
- **Shared codegraph steering fragment** `core/prompts/fragments/codegraph-hint.md`,
  co-owned by both changes. Prescriptive by intent — "SHALL prefer codegraph, Read only
  as fallback", never the permissive "you may" — to avoid the known trap where a subagent
  keeps self-Reading and codegraph becomes pure overhead.
- **Dual-platform parity (R5.7)**: claude + opencode both reach codegraph via MCP
  (`codegraph_explore`), with CLI (`codegraph explore`) Bash fallback. The existing
  `block-adhoc-scripts` guard is unchanged — codegraph MCP/CLI calls do not hit any of its
  ad-hoc-script surfaces — so **no new hook** is introduced.

### Known limitation (honest boundary)
- codegraph is itself a static analyzer: reflection / DI-container / runtime dispatch
  remain unresolved, so call-path confirmation shrinks but does not zero out mis-wiring.
  `call_path` is LLM+codegraph advisory needing human review; manifests disclose
  `call_path_residual` / `unresolved_residual` and never claim "fully confirmed".
- opencode's plugin process does not inherit env vars exported mid-session, so the
  `codegraph=on` signal activates reliably only when present at opencode launch; the CLI
  Bash fallback + shell bright-lines cover the gap (fail-soft).

## [0.1.6] — 2026-07-10

### Added
- **opencode runtime-discipline hook parity.** opencode now gets the same orchestrator-discipline
  enforcement Claude Code has. `install.sh --opencode` injects a `tool.execute.before` plugin
  (`.opencode/plugins/block_adhoc_scripts.ts`) that normalizes the tool event into Claude's
  PreToolUse stdin shape and pipes it to the **same** platform-neutral Python guard
  (`block_adhoc_scripts.py`, now also mirrored to `.opencode/hooks/`). The guard is unchanged —
  single decision source, byte-parity guarded by `tests/test_opencode_hook_parity.py`. New
  `tools/install_opencode_plugin.py` mirrors `tools/install_hook.py` (idempotent, merge-aware,
  `--remove`). This corrects the prior wrong premise that "opencode has no PreToolUse capability":
  opencode's hook surface is JS/TS plugins (`tool.execute.before`/`tool.execute.after`) — this was
  a porting gap, now closed (not a capability gap).

### Known limitation (honest boundary)
- opencode's plugin process does **not** inherit env vars exported mid-session via `bash` (its shell
  tool builds env from `process.env` and never writes back). So `export MGH_*_ACTIVE=1` inside a run
  may not reach the guard; the runtime gate activates only when the env is present at opencode
  launch (e.g. `MGH_*_ACTIVE=1 opencode run`). The shell bright-lines + per-stage `--check` boundary
  validation remain the real backstop either way (fail-soft). Verified against opencode v1.17.15.

### Fixed
- **`/mgh-init` scout→merge fold-in crashed on two kinds of malformed `scout_candidates.json`**
  (raw traceback, empty stdout, orchestrator unable to decide). (1) A candidate missing its
  `category` field hit a `KeyError` in `merge_scout._normalize`; (2) a broken JSON string value
  (e.g. an `evidence_snippet` with mis-escaped quotes / backslashes) raised `JSONDecodeError` —
  and `merge_scout.py --check` returned exit `1` (not `2`), so the orchestrator gate (which only
  rolls back on exit 2) let it through to `main()`, which had no `try/except`.
- Fix (defense-in-depth, three layers): `--check` now also asserts every candidate carries a
  non-empty `category`, and returns exit `2` for malformed JSON with `lineno`/`colno`/`msg` + a
  nearby byte window; `main()` wraps all `json.loads` (`--candidates` / `--scout` / `--clusters`)
  so a malformed input yields a structured stdout error + exit `1` with NO traceback, and
  `_normalize` now skips + warns on any category-less candidate (count surfaced as `skipped` in
  the success summary) — covering the `audit_found[]` path that bypasses `--check`.
  `discover_controls.form_clusters` is untouched (skipped candidates never reach it).
- The S3 / S4 / audit stage prompts now require a non-empty `category` on every candidate and a
  JSON-safe `evidence_snippet` (single line; `"` → `'`; strip `\`) — structurally incapable of
  breaking the enclosing JSON string. Covered by `tests/test_merge_scout.py`.

---

## [0.1.5] — 2026-07-07

### Fixed
- **`/mgh-init` fan-out checkpoints occasionally landed outside the project tree**
  (observed: a Windows drive root, e.g. `D:\xxx.json`). Root cause: the scout/T1/T3
  output paths were soft — placeholder templates / relative paths assembled twice (once
  by the orchestrator, once by the subagent); a misplaced subagent cwd resolved a
  relative path to the drive root. The enumeration scripts (`list_scout_batches.py` /
  `list_clusters.py` / `list_rule_jobs.py`) did not emit paths at all, so both agents
  had to assemble them.
- Fix: each enumerator now emits a **single authoritative absolute** `checkpoint_path`
  (scout/T1) / `rule_path` (T3) + `done_marker` per pending unit (via `Path.resolve()`).
  The orchestrator passes these **verbatim**; the stage prompts + double-shell agent
  defs treat them as **verbatim input fields** with a `NEVER`-boundary against
  self-assembly / invented filenames / relative paths / out-of-tree writes.
- **Defense-in-depth**: the `block-adhoc-scripts` PreToolUse hook (claude, `MGH_INIT_ACTIVE`
  run-domain) now also blocks `Write`/`Edit` whose resolved target is **outside the
  `MGH_TARGET` tree** (fail-loud, exit 2, recipe points at `list_*` stdout). `MGH_TARGET`
  is sourced from discover's absolute `repo` (via `describe_artifact --field repo`, never
  `py -c`); missing → degrade (pass). `--no-enforce-hook` opt-out unchanged; opencode
  (no PreToolUse) warns + skips.
- **AGENTS.md**: R5.3(b) extended (enumerators MUST emit exact absolute output paths);
  R5.5① gains a fan-out path recipe.
- New contract `core/contracts/init/cluster-enumeration.md` (T1 previously had no
  enumeration contract); `scout-enumeration.md` / `rule-jobs.md` gain the path fields.
- All additive: on-disk artifact schemas unchanged; no new runtime deps; no new CLI flags
  (`check_contracts` 0 violations). 181 tests pass.

### Upgrade
- Re-run `./install.sh --claude <target>` (or `--opencode`) to refresh the hook + shells
  + stage prompts. Existing checkpoints/rules are unaffected (schema unchanged).

---

## [0.1.1] — 2026-06-29

### Fixed
- **opencode agents failed validation on startup** with
  `Configuration is invalid ... invalid input: expected record, receiving string tools`.
  Cause: generated opencode agent frontmatter used `tools: read, glob, grep` (a
  string), but opencode's `tools` field is deprecated and expects a record.
  Fix: `tools` replaced by a `permission:` record (`read/glob/grep/list/bash/edit`
  → `allow|deny` derived from each agent's Claude tool set); the Claude-only
  `model: inherit` was removed (opencode markdown agents omit `model` to use the
  configured default). Verified all 8 agents parse as valid opencode frontmatter.

### Upgrade
- If you installed an earlier `0.1.0` with `--opencode`: re-run
  `bash install.sh --opencode .` (or the `.ps1`) in your project to
  overwrite the broken `.opencode/agent/sast-*.md` files, then restart opencode.

---

## [0.1.0] — 2026-06-29

Initial release.

### Added
- **9-stage SAST pipeline** as a native Claude Code / opencode command `/mgh-sast`
  (survey → threat-model → decompose → deep-dive → prefilter → verify → dedup →
  chain → SARIF). Zero runtime dependency on `vvaharness`.
- **Stage mapping** faithful to the original: LLM reasoning stages (s1/s2/s3/s4/s6/s8)
  run as subagents driven by skill lenses; deterministic stages (s5 prefilter,
  s7 dedup, s9 SARIF/CVSS/CWE) run as Python ≥3.10 stdlib scripts.
- **Verbatim prompt porting** from vvaharness via a stdlib `ast` extractor
  (`tools/extract_prompts.py`): stage system prompts, shared triage fragments,
  specialist lenses, threat baselines. s4 composed SYSTEM = 8,065 chars (matches
  the original). Provenance table in `core/docs/prompt-provenance.md`; Apache-2.0
  headers + `core/docs/NOTICE`.
- **Incremental scan** `--diff <ref>` — git-diff seed + call-chain expansion.
- **Scope scan** `--path <dir>` / `--package <pkg>` — directory/package seed +
  call-chain expansion.
- **Call-chain engine** (`core/scripts/expand_scope.py`): zero-dep text call graph
  (Java/Python/JS-TS/Go + generic), optional tree-sitter fallback, bidirectional
  BFS (default `both`/depth 2), Spring/Feign/AOP/DI framework allowlist.
- **Batch multi-repo** `--repo-file` (+ `--group-by-app`, `--keep-clones`,
  `--workspace`).
- **Dual-platform packaging**: platform-neutral shared `core/` + a Claude Code
  shell + an opencode shell. Installers `install.sh` / `install.ps1` with a
  zero-runtime-dependency self-check.
- **SARIF 2.1.0** output (`core/scripts/emit_sarif.py`) with a CVSS 3.1 base-score
  calculator (official roundup) + CWE mapping; severity always derived from the
  CVSS band and never disagrees with the score.
- **Unit tests** for the deterministic stages (`tests/test_deterministic.py`):
  9 tests covering prefilter gates, dedup merge, CVSS math, severity bands.
- **Distribution guide** (`docs/分发与使用指南.md`) for enterprise intranet rollout
  across Claude Code and opencode users.

### Known limitations
- Findings are **triage candidates, not confirmed vulnerabilities**; runs are
  non-deterministic.
- The call graph is **textual/AST-level**. It misses dynamic dispatch, reflection,
  DI, and framework routing (Spring `@*Mapping`, Feign, AOP, `@Autowired`,
  JPA/Spring Data). Framework-routed files unresolved against the seed are listed
  in `scope_manifest.unresolved[]` and the report for manual follow-up.

### Pending (not in this release)
- Live end-to-end scan against a real target repo.
- opencode live run + Claude↔opencode parity regression.
- Optional differential comparison vs upstream vvaharness output.
- `AGENTS_CN.md` / README pointer update to `/mgh-sast`.

---

## Versioning policy

- `0.x.y` — initial development; structural completeness, live verification in
  progress. Breaking changes may occur between `0.x` releases.
- `1.0.0` — first stable release once the *Pending* live-verification items close.
