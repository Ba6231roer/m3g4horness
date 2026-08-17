## Context

承 proposal 统一根因模型:**守卫与运行上下文的「连接」在 subagent 上下文断裂**,断在三层(咨询/
激活/输入来源),每层一个通用控制。已实证:`Path.resolve()` 折叠 `..` 链正确;`install_hook.py:29`
matcher 只含 `Bash|Write|Edit`;`_resolve_domain` 只查 `<cwd>/<run-root>/.active`(锚在 target 子
目录时实测找不到);守卫 `.py` 双端 byte-identical(parity 测强制);opencode `.ts` shim `HANDLED`
已全(前置 change 已修)——但**无机制防接线面再次漂移**。

双宿主发生路径差异(评审确认,本次修正的核心):

| 宿主 | 咨询层 | 激活层 |
|---|---|---|
| claude | matcher 缺 `Read/Glob/Grep/...` → 守卫不被咨询(G1) | hook 进程 cwd 漂移 → 哨兵失联(G2) |
| opencode | shim `HANDLED` 已全(今无缺口,但有漂移风险) | **插件进程 env 不继承 mid-session 导出(既有实证)+ 哨兵发现吃 `process.cwd()` = opencode 服务器启动目录**——启动目录 ≠ target 时整 run 休眠(这是 opencode 上同型中断的根因路径) |

## Goals / Non-Goals

**Goals:**
- 每层一个通用机制:咨询层 = 接线不变量(CI 强制,双宿主);激活层 = 锚点最优 + 有界向上发现;
  来源层 = producer 物化 `repo` 锚 + reader 统一拒识 recipe(泛化全部 fan-out reader)。
- 已装项目收敛(claude matcher 幂等演进);残余边界(opencode 锚在树外)显式记录为运行要求,不静默。
- 全部改动走既有强制面:守卫单测 + 接线覆盖测 + parity 测 + install 自检 + `openspec validate --strict`。

**Non-Goals:**
- 不改 `Path.resolve()`/`is_relative_to` 判定语义(已正确)。
- 不做「禁一切盘符绝对路径」硬拦(绝对路径是 fan-out 契约正确形态;见 D4)。
- 不为 opencode 做插件进程 cwd 重定位(插件无宿主 API 可改自身 cwd;守卫侧锚点最优 + 运行要求是
  可达的边界)。
- 不为 `Glob/Grep` 的 `pattern` 内 `..` 穿越做解析(承 read-confinement D5 保守立场)。
- 不治模型幻觉本身(治「执行前拦下 + 失败可见」)。

## Decisions

### D1 — 激活层(通用):哨兵发现 = 最优锚点起有界向上 walk

`_resolve_domain(anchor)` 改为:锚 = **hook payload 的 `cwd` 字段(claude PreToolUse stdin 携带)
?? 守卫进程 cwd**(opencode 插件进程);对锚自身及每个祖先(至盘根/16 级),逐域查
`<dir>/<run-root>/.active`;任一命中 → 该域激活。域名优先序不变。

- **为何 payload `cwd` 优先**:claude hook 的 stdin JSON 携带会话/工具上下文 `cwd`,它才是**发起
  工具调用的上下文**(subagent cwd = target 子目录场景);守卫进程 cwd 只是兜底。这把「发现锚」
  从「守卫进程恰好被 spawn 在哪」(实现细节)校正为「工具调用发生在哪」(语义正确锚)。
- **为何向上而非向下**:subagent 锚的形态集合 = {target, target 子目录, temp, 任意};哨兵唯一
  确定性位置 = `<target>/<run-root>/.active`。锚在 target 子树内任意深度,向上 walk 必然命中;
  锚在树外(temp/别处启动)不命中 → 正确休眠(不误激活)。向下扫不可行(锚=target 时不该递归整树)。
- **为何有界(16 级)**:Windows 现实深度覆盖(报告场景 6 级)+ 防病态深链性能退化;每级 1 次
  stat × 5 域,激活前最坏 ~80 stat,微秒级。
- **opencode 残余边界(诚实披露)**:插件进程 cwd = opencode 服务器启动目录,env 又不继承——若用户
  从 target 外启动 opencode,锚不在 target 链上,守卫整 run 休眠。**不试图整盘扫描补偿**(性能 +
  越权);显式写进契约:「在 target 根或其子目录启动 opencode」运行要求。这优于现状(现状连从
  target 子目录启动都休眠)。
- **替代方案否决**:①「subagent 派发时 env 注入」——claude subagent env 继承未承诺、opencode 已证
  不继承;②「守卫读 run_config.json 发现」——run-root 本身就是发现问题(鸡生蛋);③「守卫侧缓存
  上次哨兵位置」——无失效语义、跨 run 污染,否决。

### D2 — 咨询层(通用):接线不变量 = 守卫分支集 ⊆ matcher ∧ ⊆ shim HANDLED,CI 强制

- `tools/install_hook.py` `_DEFAULT_MATCHER` 扩为
  `Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Glob|Grep`。
- **幂等演进**:`present` 分支加「matcher 为当前默认子集(按 `|` split 集合比较)→ 原地更新 matcher;
  非子集(用户自定义)→ 不动 + stderr 提示」;`--matcher` 显式传值跳过演进。修「已装项目永远停在
  旧 matcher」死角。
- **接线覆盖测**(新增,双宿主一个不变量):测试从守卫源码提取 `main()` 分派工具名集合(静态扫描
  `if tool == / elif tool in (` 分支),断言 ①每个 ∈ `_DEFAULT_MATCHER` split、②每个有 shim
  `normalize` 映射(`HANDLED` 集 + 映射分支)。**新增守卫分支忘扩接线面 = CI fail**——这是比「本次
  修 matcher」更顶层的控制:该缺口类(claude matcher 缺读侧、opencode 未来缺新工具面)结构性关闭。
- **为何否决「只修当前缺口」**:opencode 今天 HANDLED 已全,但 G1 类缺口的本质是「守卫分支集与
  接线面无同步不变量」——下次任何人加分支仍会忘。CI 不变量一次治类。

### D3 — 来源层(通用):producer 物化 `repo` 锚 + reader 统一拒识 recipe,泛化全部 fan-out

- **producer 侧**:`list_scout_batches.py` `_write_batch_input` 在 input.json 顶层写绝对 `repo`
  (wrapper `repo` 透传);`list_clusters.py`/`list_test_groups.py`(T1/ut-init 同形)同步统一——
  一个「fan-out input 必携锚」的契约,非 scout 特例。stdout `repo` 已在,核对即得。
- **reader 提示词侧**(`init-scout.md` 起,同形 reader 顺带):
  1. **锚定段**:工作锚 = 输入绝对 `repo` 根;自建路径 SHALL 以锚为前缀或相对锚;NEVER 凭记忆手拼
     盘符绝对路径(已观察失败:下划线目录名被概率重生成路径分隔符对)、NEVER `..` 链。
  2. **毒输入拒识段**:输入路径字段(`checkpoint_path`/`input_path`/`done_marker`/`slice_dir`)解析后
     不在锚树内 → **视为毒输入:回 `failed <suspected path drift>` ack,不 Read 不 Write**(接既有
     failed-ack 契约,编排器写 `.failed`,resume 语义不变)。
- **编排器派发侧**(`init-stage/scout.md`):「逐字节复制 stdout `pending[]` 路径字段,NEVER 手拼/
  NEVER 记忆路径/NEVER『简化』前缀」recipe(R5.5① 正面指令为主)。
- **为何锚 = input.json `repo` 而非「先 Read `.active`」**(用户建议变体):`.active` 是 run 域内部
  机制,泄进 subagent 上下文有分发纯净性相邻关切 + 多一次必做读 + 与 `repo` 信息重复。用户建议的
  精神(「先明确工作目录再操作」)由「锚 = 输入 `repo` 字段 + 首动作锚定段」承接。
- **为何不 hook 硬拦「带盘符绝对路径」**:fan-out 契约的正确形态就是绝对路径;hook 拦绝对路径会拦掉
  全部合法扇出。硬边界放「解析后越锚树」——恰是激活/咨询层修好后守卫已拦的形状;拒识把失败**提前 +
  可见**(`.failed` marker),双层互补。

### D4 — 双端同步、契约与版本

守卫 `.py` 改动(D1)后 claude → opencode 逐字节复制(parity 测强制);契约 md 同步:激活段(锚点
最优 + 向上 walk + 有界 + opencode 残余边界运行要求)、读侧场景(`..` 链/幻觉前缀)、接线覆盖表
(matcher/HANDLED ⊇ 分支集);AGENTS.md R5.7 段 B「当前兑现」扩 matcher 面 + 哨兵向上发现;版本 bump。

## Risks / Trade-offs

- **[matcher 扩面后 claude 读侧首次生效 → 行为收紧]** → 预期收紧:越树读从「权限询问中断」(软、
  弹人)变「fail-loud recipe」(硬、给模型);树内合法读零影响(判定逻辑不变,实证)。
- **[向上 walk 的 16 级 × 5 域 stat 开销]** → 未激活域最坏 ~80 stat/调用,微秒级;接受。
- **[演进既有 matcher 条目 = 改用户 settings.json]** → 只演进「我们的」条目(marker 锚定)+ 仅当
  matcher 为旧默认子集;非子集不动 + stderr 提示;`--matcher` 显式覆盖优先。回滚 = 重跑旧版 install
  或手工改回。
- **[opencode 锚在树外 → 守卫休眠(残余边界)]** → 显式契约运行要求(「在 target 根/子目录启动
  opencode」)+ 诚实边界披露;不整盘扫描。优于现状(现状从 target 子目录启动也休眠)。
- **[opencode hook 阻断 vs 宿主权限系统先后]** → `tool.execute.before` throw 在工具执行前,理论上
  先于权限询问;无法离线实证,列真机冒烟任务(5.3)。
- **[接线覆盖测的静态提取脆弱]** → 守卫 `main()` 分派形态固定(`if tool ==`/`elif tool in`),提取
  regex 简单稳定;若未来重构分派结构,测试同步(与 parity 测同维护成本)。
- **[毒输入拒识是提示词防线,概率性]** → 承认;硬兜底是咨询/激活层修好后的守卫(毒路径一旦被使用即
  拦),拒识只把失败提前 + 可见。双层:守卫确定性拦「执行」,提示词概率性拦「接受」。
- **[深树 > 16 级场景哨兵仍失联]** → 承有界;16 级覆盖现实 Windows 深度;记 Open Question 不加深。
- **[回归测需同步]** → 守卫单测 + 接线覆盖测 + matcher 演进测 + parity 测;CI 必过(R5.8)。

## Migration Plan

1. 守卫 `.py`:`_resolve_domain` 锚点最优 + 向上 walk(D1)+ 单测;claude → opencode byte 复制;
   parity 测过。
2. `install_hook.py`:matcher 默认值 + 子集演进(D2)+ 单测;接线覆盖测(D2)落地。
3. producer `repo` 锚统一(D3):`list_scout_batches` 核对/补,`list_clusters`/`list_test_groups` 同步;
   `init-scout.md` 锚定 + 拒识段;`init-stage/scout.md` 逐字节复制 recipe;同形 reader 顺带。
4. 契约 md + AGENTS.md R5.7 措辞 + 版本 bump(D4);`openspec validate --strict`。
5. install 自检 + 全量回归 + opencode 真机冒烟(5.3)。
- **回滚**:三面独立可回滚(守卫 walk / matcher+接线测 / 提示词+repo 字段);无数据迁移;产物 schema
  只增顶层 `repo` 字段(向后兼容,reader 不读该字段亦不破)。

## Open Questions

- 向上 walk 是否需要「链上目录名启发式提前终止」优化?(当前:否,~80 stat 可接受。)
- `run_config.json`/resume_state 是否也值得锚点最优 + 向上发现(与哨兵同形)?(当前:否——resume
  查询只发生在编排器 cwd=target 场景;记此备查。)
- 接线覆盖测是否进一步强制「shim `normalize` 每工具字段映射完整性」?(当前:只测工具名覆盖;
  字段级映射靠既有 parity 测。)
- T1(`list_clusters`)/ut-init reader 的锚定段是否本 change 一并加?(当前:producer `repo` 统一 +
  scout reader 先行,同形 reader「顺带最小」;若 review 觉得范围膨胀可裁——倾向保留,形态完全同源。)
