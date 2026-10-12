# add-mgh-dsh-subagent-fanout — Design

## Context

动机与范围见 proposal.md。承重现状:`fanout_runner.py` 是产品自带 dispatcher——固定模板
构造任务、stdin 喂宿主 CLI headless 子进程、波次 ThreadPool、双 reader 字节静默 + 树杀 +
熔断/cooldown;除「命令形映射 + 探测」外全部宿主无关。opencode 端教训(`run` 拒
`mode: subagent`、须 primary 克隆)与 claude 端(`--agents` inline JSON)是两档既有装载形。

## Decisions

### D1 — 探测链末位追加 dsh，显式 `--host` 恒优先

既有优先级(opencode 先行)是双端机器的现场事实，不改;新宿主只加枚举值。默认行为零变化
由 fake-dispatch 用例断言(既有命令形快照不动)。

### D2 — dsh 活性信号 = plain 模式字节流，不用 `--json`

`--json` 的 text/final 事件按**步提交**(非逐 token)，多步长思考会出现分钟级零字节窗口，
直接喂大 stall 误杀。plain 模式推理增量持续走 stderr，与 opencode 端同形，双 reader 逻辑
零改动。`--json` 仅留作人工 debug 通道，不进产品路径。

> **SPIKE 定案(真机 0.1.5-rc.2)：成立**——headless plain 模式 reasoning 增量逐 chunk 写
> stderr、终稿写 stdout(实测连续字节流)。同批实测推翻投递假设:**headless 无 stdin 任务
> 通道**(stdin 仅用作 EOF 关停信号),任务只走 argv 位置参数且非空必需,而多行 argv 经
> npm `.cmd` shim 实测**在首个换行处截断**(旧教训在 dsh 复现)。定案投递形 = **env 通道**:
> dispatcher 经进程环境注入 `MGH_TASK_TEXT=<任务全文>`,tier 装载文件用固定模板行
> `task: !!js process.env.MGH_TASK_TEXT` 覆盖 headless-runner 的任务来源,argv 只留无内容
> 占位符 `-`;装载层覆盖优先于 argv 注入(实测胜出),190KB 多行含特殊字符任务字节级保真
> 到达并被子代理逐字回述。NEVER-argv 的初衷(正文不进命令行)保持为真。

### D3 — tier 装载两档,spike 定档；b 档的安全底线写死

- **a 档(优先)**：`--patch` 指向的 tier 文件装载叶 SYSTEM 提示词 + 宿主侧工具白名单
  (对位 claude inline JSON / opencode agent md)。
- **b 档(兜底)**：dispatcher 固定模板把提示词文件内容前置进 stdin 任务(仍零 LLM 回合、
  模板构造)，工具面收窄**只由守卫三面 + 宿主 approval 承载**。b 档可接受的边界：守卫的
  `RunCode`/`JobCtl`/越树判定(change 1)恰是白名单想挡的违例面，执法不缺位；差异只剩
  「宿主原生 approval 弹窗可能多于 a 档白名单」。
  档位选定后写入 fan-out 运行契约，三面壳与测试同读一份(spec 已锁单档不混用)。

> **SPIKE 定案(2026-09-23 真机, dsh 0.1.5-rc.2)：a 档成立**。tier 装载文件(YAML patch)经
> `--patch` 可覆盖顶层 headless run 的 `system-prompt.personaPrefix`(persona 注入行为可证:
> 子代理正确回述装载内代号)并按插件行 `disabled: true` 整面禁用工具;细粒度 per-tool
> allow/deny 在顶层**不存在**(仅子代理实例配置面有),故白名单为**整插件粗粒度**
> (read/write 同插件 `tool-fs` 不可拆),残余违例面由守卫三面兜底——维护者已拍板接受。
> 叶 SYSTEM 提示词正文由生成器嵌入 persona(定义文件按路径引用 `mgh-core/prompts/`,不复制)。

### D4 — 超时调平首选宿主配置关晋升，方言 recipe 是下策

tier/profile patch 里关 dsh shell 工具的超时晋升(若可配)。「超时=终止」合同与 R5.4 权威处
一致、方言段最少。不可配才走壳内 `job_kill` 追加步——那会把宿主分歧渗进文本面，须在
契约里显式登记(承「结构免疫优于自觉」的既有立场)。

> **SPIKE 定案(真机 0.1.5-rc.2)：首选路线,且比预案更干净**——该版本 shell 工具**不存在
> 「超时自动晋升后台 job」**(超时即 deadline kill,与终止合同天然一致;晋升语义只存在于
> 新版源码,装机版无)。唯一分歧面是模型**显式** `run_in_background: true`(job 通道),
> tier 装载文件对 `tool-bash`/`tool-pwsh` 各写一行 `enableRunInBackground: false` 即关闭
> (实测配置生效);`job_*` 工具面另由守卫 `JobCtl` deny 兜底。不需要壳内 `job_kill` 方言段。

### D5 — 交互式 stage 用具名委派实例，不用泛型委派

每个 stage 一个具名工具实例(profile/preset 组合)，壳文本按名拾取，与 claude 端模型
diff 最小、可被契约 lint 三面断言；「泛型 subagent + 任务前置」形态把 stage 提示词装载
推给编排器自觉，违背派发模板化立场。具名实例清单由 `releases/dsh/agents/` 文件集决定,
生成器与 install 同源消费。

> **SPIKE 定案：成立**——tier/profile patch 的 `insert` 行挂 `dsh-tool-subagent` 插件
> (独立 `id` + `toolName` + `persona` + `toolFilter.allow`)实测生效,具名工具出现在子代理
> 可调用面;同插件多行共存是 base bundle 既有形态。

### D6 — tier 装载文件 = 构建期生成物、install 落地、入 purity lint 扫描面

生成脚本放 `tools/`(构建期，不分发)；输出 `<target>/mgh-core/dsh/tiers/*` 是分发物,
自动进纯净度与零依赖扫描。生成失败(fan-out 定义缺件)在 install 期 fail-loud,不拖到
运行时(承 R5.9 边界校验)。

### D7 — mgh profile 为运行载体

扇出与交互派发统一经 `dsh --profile mgh`(change 1 降级预案升正):profile 组合 shim、
委派工具具名实例与超时策略；tier 差异经逐次 `--patch` 叠加。用户自有 profile 不被改动,
install 只增不改(幂等)。

> **SPIKE 补充(真机验证)**:自定义 profile 目录(`$DSH_HOME/profiles/mgh`,package.json 声明
> base+headless 两个 bundle)可被 `--profile mgh` 启动,bundle 经 dsh 安装锚点解析、无需
> `dsh plugin add`(空 dependencies 实测可跑)。shim 挂载沿用 change 1 的受管块机制(插件
> `name` = 绝对 `.ts` 路径)。install 只建/只改 mgh 这一个 profile,用户自有 profile 零触碰。

## Risks / Trade-offs

- **[R] wave 并发 = 多枚 dsh node 进程，机器负载高于既双端实测基线未知** → 首跑用
  `--wave 2` 标定，必要时 dsh 端默认并发降档写入契约(参数面而非代码面)。
- **[R] dsh headless 需用户自配模型 provider——install 自检只证 CLI 在场，不证可跑通** →
  真机验收任务显式覆盖；契约「诚实边界」段补一句 dsh 端前置条件。
- **[R] rc 版本漂移(装载键名/事件形状)** → 装载物集中在生成器一处，漂移改一处；
  spike 记录 pin 的实测版本。
- **[取舍] b 档白名单弱化**换取不被宿主配置能力卡死交付；底线由守卫三面保证(D3)。

## Migration Plan

增量:host 枚举 + 生成器 + profile 资产 + 壳删降级段。回滚 = 移除 dsh 分支枚举即回双端
形态，产物 schema/marker 协议零触碰。

## Open Questions

(全部已由 2026-09-23 真机 spike 关闭,结论内联进 D2/D3/D4/D5/D7 与契约文档)

1. ~~`--patch` 能否设**顶层** agent 的系统提示词/工具面~~ → **a 档成立**(persona 注入
   行为可证 + 整插件禁用;细粒度白名单顶层不存在,粗粒度 + 守卫兜底已被接受)。
2. ~~headless 并发 session 互踩?~~ → **不互踩**:每 run 自生成 `session-<uuid>`、每 session
   目录独立锁,双并发实测零冲突;无需 `--session-id`(该 flag 是接管既有会话,非常规派发形)。
3. ~~`taskkill /T` 对 dsh 树?~~ → **有效**:`cmd.exe → node → sandbox runner → powershell`
   全链一次杀净无孤儿;`--kill-stale` 的 cmdline 标记集需加 `dsh`。
