# Design: add-mgh-init-scout-fanout-runner

## Context

现状 scout fan-out:编排器(宿主 LLM)`Bash` 跑 `list_scout_batches.py --materialize` 取 slim
`pending[]` 页 → 亲手撰写 5 个 init-scout 任务消息 → 同回合并发 spawn → 看 ack → 下一波重跑
list。每个波次边界都是一次编排器 LLM 回合(分析文档 §1:~1–3K token/波 + 弱模型漂移面);任务
消息里的路径靠弱模型概率性复现 producer 字段,已实证失败形态:格式不一、盘符根漂移、下划线
目录名幻觉(`harden-mgh-init-scout-path-binding` 的 G3 层——provenance 缺口只加了提示词护栏,
拦不住首次生成错)。既有防线(有界性 = `request-context-budget`、树内性 + 毒输入拒识 =
path-binding)都不触及「派发循环与任务消息由 LLM 执行/撰写」本身。

分析文档(`docs/opencode-subagent-fanout-analysis.md`)已核实:subagent 创建不需要 LLM 参与;
推荐路径 D(dispatcher 脚本 spawn 宿主 CLI);开放问题两个(spike 1 并发 SQLite、spike 2
`opencode run --agent` 显式指定)。

## Goals / Non-Goals

**Goals**

- scout tier 编排器 token 从「每波 ~1–3K × 波数」降为「1 次 Bash + resume 重派 + 1 次读摘要」。
- 任务消息**由构造固定**:固定模板 + 逐字字段填充,路径拼写错误类失败(盘符根漂移/下划线幻觉/
  格式不一)从根上消失。
- 承接全部既有磁盘契约:`.done`/`.failed` marker 真相源、`--resume` 幂等、`partial:true` 干净早退、
  磁盘哨兵守卫激活、R5.3 叶脚本稳定性、零运行时依赖。
- 回退无损:宿主 CLI 不可用 → 退出码 2 + recipe → 编排器回退现状手派路径,行为不变。

**Non-Goals**

- T1/T3/sra-augment 的 dispatcher 采纳(泛化入口 `--tier` 留接口不实现,后续 change)。
- 不改 marker 契约、resume 磁盘真相源语义、scout 后续聚合/merge/fold-in 步骤。
- 不做 B 路径(`opencode serve` HTTP API)与 C 路径(插件注入 subtask parts)——分析文档已出局
  理由:运维面/串行性。
- 不引入 pip 依赖;不物化「编排器脚本」(dispatcher 是产品叶脚本,非编排器 wrapper,R5.2 边界
  见分析文档 §5)。

## Decisions

### D1: dispatcher 是产品叶脚本,消费 list stdout 而非重挖 scout_plan

`fanout_runner.py` 落 `core/scripts/`,输入 = `list_scout_batches.py` stdout JSON(编排器经 Bash
管道/`--pending-file` 传入,或 dispatcher 自己 Bash 调 list ——见 D6)。NEVER 直接读
`scout_plan.json` 聚合(那会绕过 slim 壳 + materialize 契约,重蹈 426KB 覆辙)。
**理由**:pending 清单的路径字段(`input_path`/`checkpoint_path`/`done_marker`/`failed_marker`/
`slice_dir`)已经是 producer 物化的绝对路径(单一真相源),dispatcher 只做逐字搬运。

**备选弃**:dispatcher 内部 import `list_scout_batches` 复用函数——弃,因 list 的入口形态(分页
+ materialize)即契约,函数级耦合会让两脚本契约漂移;走 CLI stdout 消费与编排器同构。

### D2: 任务消息 = 固定模板 + 字符串占位符逐字替换

新 fragment `core/prompts/fragments/fanout/scout-task.md` 是**任务消息模板**(与 stage 提示词
`stages/init-scout.md` 分工:后者仍是 subagent 行为定义,经 agent .md 装载,不随批次变化)。模板
占位符集:`{{input_path}}`/`{{checkpoint_path}}`/`{{done_marker}}`/`{{failed_marker}}`/
`{{slice_dir}}`/`{{chunk_sources_abs}}`/`{{repo}}`/`{{codegraph}}`。填充 = 纯字符串替换
(`str.replace`,非 LLM、非 format 自动推导),替换后断言模板中无残留 `{{`。派发前 dispatcher
对每个路径字段做 `Path.resolve()` 锚树校验(锚 = `repo`),越树 → 该单元 `failed`
(reason=path-drift)+ NEVER spawn——这是 path-binding G3 层从「reader 拒识」前移到「spawn 前
拦截」的确定性对偶。
**理由**:「同一系统提示 + 同格式任务内容」由构造保证;弱模型拼写错误从概率性失败变为不可能。

**审计副本**:每次 spawn 前,dispatcher 把填充后消息写到
`<init-dir>/inputs/scout/<batch_id>.task.md`(与 `input.json` 同目录,便于复盘「subagent 到底
收到了什么」)。文件小(≤2KB/批)、可 `--purge-audit` 清理(带 `--dry-run`,承 R5.3b)。

**备选弃**:把字段拼进 `--append-system-prompt`(claude)——弃,system 面不该带 per-unit 数据;
任务消息进 user 面是两宿主的自然形态(opencode `run "<prompt>"` / claude `-p "<prompt>"`)。

### D3: 宿主 spawn 映射——claude `-p` / opencode `run --agent`,cwd=repo

> **Spike 回填(2026-08-18,双宿主真机实证,spike 仓 `C:/DEV/mgh-fanout-spike`)**:见下方
> 「Spike 实证结论」小节;表格已按实证形态更新。

| 宿主 | 命令形态(spike 实证) | agent 装载(spike 实证) | 工具面限定 |
| --- | --- | --- | --- |
| claude | `claude -p "<task>" --agents <inline JSON> --allowedTools "Read Glob Grep Bash Write"`(stdin 重定向 `< /dev/null` 或等价,防 stdin 等待) | **双路实证**:① `--agents` inline JSON(`{"init-scout": {description, prompt, tools}}`,~2KB,从 install 落位 md 读出转换)✅;② 项目级 `.claude/agents/` 落位经 Task 子代理自然拾取 ✅。**采纳 ①**:一次 `-p` 调用即一个 scout 单元,不经 Task 二跳(① 是单进程直给任务消息,等价性更直接) | `--allowedTools` 白名单下 headless 无权限交互挂起(实证 Read/Glob/Grep 白名单 + 工具调用 + 单行 ack 回传) |
| opencode | `opencode run --agent init-scout-fanout "<task>"`(默认 format 即人类可读末行;`--format json` 取末条 `{"type":"text","part":{"text":…}}`) | install 落位 `.opencode/agent/init-scout-fanout.md`(`mode: primary` **新克隆**,非既有 `mode: subagent`——run.ts 拒绝 subagent 作 primary,静默降级 default agent) | agent .md `permission:` frontmatter(既有,克隆继承) |

- cwd = `repo`(目标项目根)——子进程的相对路径解析与 hook 哨兵向上发现都锚在 target 树。
- 探测顺序:`--host claude|opencode` 显式 > `opencode` in PATH > `claude` in PATH(`shutil.which`);
  均缺 → 退出码 2 + stderr recipe。
- 并发 = `concurrent.futures.ThreadPoolExecutor(max_workers=--wave)`,每 worker 一个
  `subprocess.run(cmd, timeout=per-call)`;单进程超时 → kill → 无 ack → 留 pending(crash 语义)。
- **R5.7 hook 激活**:子进程经磁盘哨兵 `<target>/.mgh-init/.active` 激活守卫(env 不跨进程亦
  不失效——哨兵本为该边界设计);dispatcher 自身不写哨兵(write_runconfig 已 co-write)。

**Spike 实证结论(1.1 / 1.2,双宿主)**:

1. **opencode `--agent` 接受但 subagent 被拒**:`opencode run --agent init-scout` 对 `mode: subagent`
   的 agent 打警告 "is a subagent, not a primary agent. Falling back to default agent"
   (源码 `packages/opencode/src/cli/cmd/run.ts:610-617` 实证)且**静默换用 build agent**——任务
   消息仍被执行但 agent 定义/权限面丢失。**结论**:dispatcher 侧用专用 fanout agent 定义
   `init-scout-fanout`(`mode: primary`,install 落位),正文=既有 init-scout(行为/纪律逐字)。
   `mode: primary` 实证被接受(agent 名出现在 `> init-scout-fanout · glm-5.3` 横幅,stage 提示词
   被读取,毒输入拒识纪律真实生效)。
2. **opencode 并发 SQLite 无锁死**:5 × 并发 `opencode run`(同仓同 cwd)全部 exit=0、互不干扰
   (分析文档 §6 开放问题 1 关闭)。
3. **stdout ack 解析面**:默认 format 的**末行**即最终回传消息(人类可读,恰好是 ack 形态);
   `--format json` 时取末条 `"type":"text"` 的 `part.text`。dispatcher 用默认 format 取末行
   (更省、解析面最小),解析失败降级只信磁盘 marker(D4 已定)。
4. **claude `-p` 双装载路均实证**:`--agents` inline JSON(agent 定义随调用传入)与项目级
   `.claude/agents/` 落位(经 Task 子代理)都工作;`--allowedTools` 白名单下 headless 完成
   Read→单行 ack,无权限交互挂起(开放问题:claude headless 权限弹窗 → 不发生)。
   **claude -p 的 stdin 必须显式重定向**(`< /dev/null`),否则报 "Input must be provided either
   through stdin or as a prompt argument"。
   注:spike 期间 z.ai 网关对 GLM-5.3 路由有持续 529(服务端过载),切 GLM-4.7(haiku 路由)
   即通——**与 spawn 机制无关**,dispatcher 不绑定模型(claude 侧模型由用户 env/默认决定)。
5. **claude 并发**:3 × 并发 `claude -p` 全部 exit=0(叠加 spike 1.1 的 opencode 5 并发,
   `--wave` 默认 5 保持;风险表「并发 SQLite」已被 opencode 侧实证关闭)。
6. **`--wave` 默认值 = 5**(提案原值,双宿主并发实证通过,保守不动)。
7. **Windows spawn 两处坑(真机冒烟暴露,已修)**:① npm 装的宿主 CLI 是 `.cmd` shim,
   `subprocess.run(["opencode", ...])` 直接 WinError 2——argv[0] 须 `shutil.which` 解析为
   绝对路径;② 多行任务消息经 argv 传递被 shim 截断(子代理只收到 `<!--` 首行)——任务消息
   改经 **stdin 管道**传递(双宿主 headless 均支持:opencode `run` 读 `Bun.stdin.text()`、
   claude `-p` stdin 模式;均实证)。

**备选弃**:B 路径 HTTP API(端口发现/鉴权/生命周期运维面)、C 路径插件注入(串行)。分析文档
§4 已论证;仅在 D 路径 spike 失败时按文档转 B。

### D4: 状态机 = 磁盘 marker 真相源 + in-memory pending 重派生

每波结束(而非每单元结束)重扫 checkpoint 目录 marker → 重派生 pending(与
`list_scout_batches` 的 `_done_ids`/`_failed_ids` 同谓词;为免跨脚本漂移,dispatcher 以「重跑
list CLI 取最新 pending」实现重派生——list 本就是幂等只读的)。波次循环:

```
while pending and not time_budget_exhausted:
    wave = pending[:N]
    spawn wave concurrently (ThreadPool)
    collect exits + acks (stdout 最后一行)
    ok/oversize + .done → done
    failed ack → dispatcher 写 .failed marker (body {unit,reason,tier})
    crash/timeout 无 ack → 留 pending
    pending = re-derive via list CLI
partial = bool(pending)
```

ack 解析 = 子进程 stdout 最后一行匹配 `ok <path> <n>` / `oversize <path>` / `failed <reason>`;
**拿不到可解析 ack 时只信磁盘 marker**(分析文档 §6 开放问题 4 的降级:`.done` 在即完成,否则
留 pending)。`failed` ack 的 `.failed` marker 由 dispatcher 写(与现状编排器写同形 body)。

**理由**:磁盘真相源语义零变化;`--resume` = 同一循环入口(list 重派生天然跳过 `.done`)。

### D5: 与 R5.2 黑盒纪律、R5.6 token 预算的关系

- **R5.2 不违**:NEVER 禁的是编排器**运行时临场写**派发脚本;dispatcher 是 dev 时写好、install
  分发的产品叶脚本(`--help` 即契约),编排器只是 `Bash` 调它(分析文档 §5 同论)。
- **R5.6**:新增 fragment `fanout/scout-task.md` 是**任务消息模板**(被 dispatcher 读,不进编排器
  上下文),不计入编排器 fragment 预算;`init-stage/scout.md` 改写后须重测 ≤ 上限(scout 步现状
  ~1.0K,改写为「dispatcher 调用 + 回退路径」预期更瘦)。双壳 mgh-init.md 不增正文(调用行进
  `list_steps.py` 契约面),token lint 照跑。

### D6: 编排器接线 =「dispatcher 自取 pending」单命令形态

调用面收敛为一条(避免编排器做管道组合——弱模型拼管道是新的概率失败面):

```
py <mgh-core>/scripts/fanout_runner.py --scout-plan <target>/.mgh-init/scout_plan.json \
   --checkpoints <target>/.mgh-init/checkpoints/scout --inputs-dir <target>/.mgh-init/inputs/scout \
   [--wave 5] [--time-budget-ms ..] [--resume]
```

dispatcher 内部:① `Bash` 调 `list_scout_batches.py --materialize`(兄弟脚本,同目录自寻址,承
R5.3a)取 stdout JSON;② 波次循环(D4);③ stdout 摘要。即 dispatcher 是 list 的**唯一消费者**,
编排器不再直接跑 list(scout 步内)。
**理由**:编排器侧「跑 list → 管道喂 dispatcher」两步合一,消灭管道拼写/路径中转失败面;
`--resume` 语义也统一(重派同一命令)。

**备选弃**:`--pending-file` 让编排器先跑 list 再喂——保留为**内部测试入口**(单测直接喂构造
JSON,不 spawn),不进编排器调用面。

### D7: spike 前置任务化(分析文档 §6 开放问题 1/2)

T2 是**闸门任务**:并发 `opencode run` SQLite 行为 + `--agent` 显式指定 + claude `-p` agent
寻址。spike 失败 → D 路径整体回退(本 change 收窄为「claude-only 或 opencode-only」或撤销),
按分析文档转 B 路径另立项。spike 结论(命令形态、flags、并发上限实测)回填本 design 的 D3
表格,task T3 起按实证形态实现。

## Risks / Trade-offs

- [并发子进程 SQLite 锁/资源争用] → spike 1 前置闸门;`--wave` 默认保守 5;失败降 `--wave 1`
  重试语义留 stderr 提示。
- [`claude -p`/`opencode run` flags 面 churn(pre-1.0)] → spawn 适配集中单点
  (`_spawn_cmd(host, task)`);flags 错误 = 子进程非零退出 → 无 ack → 留 pending → resume
  重派不丢批;真机冒烟任务覆盖双宿主。
- [claude headless 权限弹窗(非 allowlist 工具)] → `--allowedTools` 显式白名单 + agent .md
  permission 已限;冒烟任务验证 headless 下无交互挂起。
- [dispatcher 单点膨胀(状态机+spawn+模板+探测)] → 只做「派发」不做「判断」:任何语义判断
  (oversize 处置、聚合预算)留在既有脚本;预计 ~300 行,超 400 行 = 设计违例信号。
- [任务消息模板与 stage 提示词内容漂移(两处维护)] → 模板只含「输入字段声明 + 指向 stage
  提示词的既有装载指令」,行为规则一句不复制(agent .md 已指 stages/init-scout.md);回归测
  断言模板占位符集与 `pending[]` 字段集一致。
- [审计副本膨胀(几千批 × task.md)] → 单文件 ≤2KB;`--purge-audit --dry-run` 清理出口;
  默认保留(复盘价值 > 磁盘成本,~4MB/2000 批)。

## Migration Plan

1. T2 spike(双宿主 headless spawn 实证)→ 结论回填 D3;失败 → 收窄/撤销(见 D7)。
2. T3–T6 实现(dispatcher + 模板 + fragment/契约面 + install/单测)。
3. 真机冒烟:小仓(几十批)+ 大仓(数百批以上)双宿主各一轮;对照手派路径产物等价
   (marker 集合 + `scout_candidates.json` 语义)。
4. 回滚 = 壳/fragment 恢复手派正文(git revert 单 commit);dispatcher 留在树中无害(不被
   调用即无行为)。

## Open Questions

(全部已由 spike 关闭,2026-08-18 —— 结论回填 D3「Spike 实证结论」)

- ~~claude `-p` 下 `.claude/agents/` 项目级落位是否免 `--agents` 显式传~~ → 双路均实证;采纳
  `--agents` inline JSON(dispatcher 单进程直给任务消息,不经 Task 二跳)。
- ~~`opencode run` 的 stdout 最终消息格式在 `--format json` 下取哪个字段做 ack 解析~~ → 默认
  format 末行即 ack;`--format json` 备选(末条 `type:"text"` 的 `part.text`);解析失败降级
  只信磁盘 marker(D4)。
