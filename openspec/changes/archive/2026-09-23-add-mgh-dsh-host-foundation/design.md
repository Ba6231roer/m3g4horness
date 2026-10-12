# add-mgh-dsh-host-foundation — Design

## Context

动机与范围见 proposal.md。此处只列承重约束:

- 守卫判定单一来源在 `core/scripts/block_adhoc_scripts.py`(零依赖 Python);claude 端经
  settings.json PreToolUse(命令 hook,exit 2 阻断),opencode 端经 `.opencode/plugins/*.ts`
  薄胶合(`tool.execute.before` → spawn 同一守卫)。dsh 加入即第三个胶合面,复用同一守卫。
- dsh 侧已核实事实(维护者本机 dsh 源码检出 0.1.5-rc.2,非本仓分发依赖;**spike 1.1 真机回填
  2026-09-23,证据行为源码 文件:行号**):
  事件 `'tools/pre-execute'` 为 waterfall,payload `ToolExecution` 的工具 id 字段是 `exec.name`、
  参数容器是 `exec.arguments`(deep-frozen,监听者**不可改写**;输入重写仍是提案未实现),无 cwd
  字段——会话目录取 `exec.agent?.session?.header.cwd`
  (`packages/core/tools/src/index.ts:153、316-342、1431、1490-1493`)。
  deny 形状 = 监听者 `return { kind: 'deny', reason }`(不调 `next()` 即整链否决;放行必须
  `return next()`,注册器采纳**最外层**监听者返回值),reason 以 `Error: <reason>` 全文写入
  isError 工具结果、模型可见,deny 路径**无长度截断**
  (`packages/core/tools/src/index.ts:596-600、1504-1523`、`vendor/cordis/src/events.ts:227-243`)。
  `$DSH_HOME` Windows 默认 `%USERPROFILE%\.dsh`(实测本机即此,profiles 目录已存在 web/headless);
  profile 自动创建仅限随发行版模板名(`packages/util/home-paths/src/index.ts:87-91`、
  `packages/boot/app-boot/src/profile.ts:156-172`)。patch 叠加顺序 bundle→profile 层
  `cordis.patch.yml`→home 层→`--patch` overlays(`packages/boot/app-boot/src/profile-context.ts:63-73`)。
  dsh 内置工具含 claude/opencode 没有的执行面:`run_code`(Python 执行器,代码字段 `code`)、`pwsh`、
  `terminal_*`、`job_*`、`str_replace_editor`(路径字段 `path`)。**Windows 特情**:`bash` 工具在
  win32 整行禁用、由 `pwsh` 孪生替代(`packages/bundle/base/cordis.patch.yml:266-272`),故 dsh
  Windows 会话的 shell 面**只有 `pwsh`**——「pwsh 并入 Bash 净网判定」在 Windows 上是主通道而非旁路。
- 约束(承既有纪律):判定逻辑 NEVER 复制到 TS 端;三端接线覆盖必须有 CI 结构性闭环;
  install 幂等 + 自检;分发内容不携带本研发仓私有引用。

## Goals / Non-judged

- 验收面 = 「deny 语义通 + 判定单源不破 + install 幂等」;**不**在本 change 验收任何
  mgh 命令端到端可跑(命令壳属后续 change)。

## Decisions

### D1 — 原生 Cordis TS shim,不走 dsh 的 Claude hooks 兼容桥

dsh 提供 `hooks-claude-code` 桥可直接执行现成 hooks.json。仍选原生插件,理由:
① 兼容桥的 PreToolUse 以 Claude 工具名词表呈现,dsh 特有旁路面(`run_code`/`pwsh`/`job_*`)
能否以原名进入桥的 payload **无文档保证**,而执法面恰恰以这些名字为主——判树必须以宿主
真实工具 id 为准;② 桥是进程级单 `configPath`、启动时读一次,与用户自有 Claude hooks 互斥,
安装侵入语义更差;③ 原生插件与 opencode `.ts` shim 同形(事件归一化 + spawn 守卫 + 按退出码
阻断),三端维护模型统一,parity 测结构不变。**代价**:新写一个 shim(~150 行内),接受。

### D2 — shim 落位与装载:`mgh-core/dsh/` 源 + profile patch 接线

shim 源码放 `releases/dsh/plugins/mgh-guard.ts`,由 install 镜像到 `<dest>/mgh-core/dsh/`
(与守卫脚本兄弟共位,沿用既有「叶脚本 co-location 自检」不变量)。接线 = 向用户 profile 的
`cordis.patch.yml` 追加一个受管块(marker 锚定,幂等,同 claude matcher 演化策略)。
**装载机制(spike 1.2 真机已裁 2026-09-23)= 候选 (b)**:profile 层 `cordis.patch.yml` 以
绝对文件路径直挂本地 `.ts`(`- insert: [{ id: mgh-guard, name: '<abs>/mgh-guard.ts' }]`,
loader 把路径型 name 转 `file://` URL,`packages/boot/app-boot/src/index.ts:333-344`),实测
`dsh --profile <p> --help` 与真实 headless 会话均装载成功、pre-execute 监听与 deny 生效。
候选 (a)(`dsh plugin add` 最小 npm 包)实测**失败**:该命令把剩余参数转发 pnpm 在 profile
目录执行,本机无 pnpm → `'pnpm' 不是内部或外部命令`(且失败仍返回退出码 0,不可依赖退出码判成败)。
故 install 的 `--dsh` 接线不依赖 npm/pnpm 面;`$DSH_HOME` 下 profile 缺失时按模板名
`--from-default-profile` 派生或提示,不静默创建。降级预案(独立 mgh profile)不需要。

### D3 — 归一化映射在 shim 层,守卫内核只加工具名分支

| dsh 工具 | shim 归一化到 | 参数改名 |
|---|---|---|
| `bash` | `Bash` | 命令字符串字段 → `command` |
| `pwsh` | `Bash`(方言同一净网判定) | 同上 |
| `read` | `Read` | 路径字段 → `file_path` |
| `write` | `Write` | → `file_path`/`content` |
| `edit` | `Edit` | → `file_path` + 编辑字段 |
| `str_replace_editor` | `ApplyPatch` 同形(从 patch 主体抽路径) | — |
| `glob`/`grep` | `Glob`/`Grep` | → `pattern`/`path`/`glob` |
| `run_code` | `RunCode`(守卫新分支) | 代码体字段 → 供内联解释器规则复用 |
| `terminal_*` / `job_*` | `TerminalIO` / `JobCtl`(守卫新分支,运行域内直接 deny+recipe) | — |

守卫内核新增分支只做「映射后的名字 → 既有规则族」的挂接,不感知 dsh 字段名;未映射 id
透传不处理(宿主自身 approval 兜底)。写侧/读侧既有规则**零放宽**照常命中。

### D4 — deny 理由通道 = 守卫 stderr 原文

shim 把守卫 stderr(含 recipe)作为 pre-execute 拒绝理由回传,让模型看到「该怎么走合法出口」
(与 claude exit2+stderr、opencode throw(message) 同构)。若实测发现 dsh 对 reason 有长度/
格式截断,recipe 尾部追加 `见 <target>/mgh-core/ 契约文档` 短指引,不牺牲主通道。

### D5 — Python 缺失 fail-soft 与 opencode 端同形;解释器探测复用守卫既有回退链

shim 找不到 `py/python3/python` 时放行 + 宿主日志一条(与 opencode shim 一致;运行域脚本
只读等执法退化为宿主 approval 体系,不静默假执法——install 自检已在镜像期证明 Python 可用,
缺 Python 属安装后环境漂移)。stdin 注入用「一次性 Buffer 写入」而非流式管道,沿用 opencode
1.18.3 兼容教训。**解释器回退顺序(spike 1.3 真机已钉 2026-09-23)**:dsh Windows 会话的 shell
面 = `pwsh`(每次调用一个新进程,无持久 state),本机实测 `py`(launcher → 3.13.2)可用而
`python`/`python3` 均不存在(9009)——shim spawn 回退链 `py` → `python3` → `python`(与守卫
既有回退链同序),首中即用。

### D6 — parity 测三面化形态

`TestWiringCoverage` 现为「守卫分派集 ⊆ claude matcher ∧ ⊆ opencode HANDLED」。扩为三端:
dsh 端从 shim 源码解析映射表(与现有对 `.ts` 的静态解析同法,不执行 TS)。既有双端
字节级守卫 parity 测不动;新增用例=同一违规 fixture 三端各跑一次守卫、断言退出码与
recipe 同源(直接 spawn 守卫模拟 payload,不经宿主)。

### D7 — Bash 前台超时语义差异(晋升后台 job 而非杀)本 change 不处理

该差异影响的是编排纪律与 fan-out 计时,归 subagent-fanout change 统一裁决(配置侧关掉
晋升 vs 纪律侧改 job_kill recipe);本 change 的 shim 只如实转发工具调用,与超时策略正交。

## Rejected / Deferred alternatives

- hooks-claude-code 桥:D1 已否。
- 把判定逻辑写进 TS 以省 spawn:否——双端白名单/净网表是 Python 单源,三面复制必然漂移。
- 「先命令壳后守卫」顺序:否——违反「执法 hook 缺席 = CI fail」的交付定义,命令面无守卫
  上线即违规。

## Risks / Trade-offs

- **[R] dsh 仍是 rc 版本,pre-execute API 与 profile 格式可能漂移** → 接线层是唯一耦合点,
  守卫与叶脚本零感知;版本自检任务里 pin 实测版本并在报错中提示兼容窗口。
- **[R] `run_code` 直接 deny 可能误伤用户自有用途** → 仅在 mgh 运行域激活时生效(哨兵即
  域边界),域外零打扰(spec 已固化为场景)。
- **[R] plugin 装载机制 (a)/(b) 未实测** → spike-first:tasks 第 1 组就是真机装载验证,
  失败走 D2 降级预案,不阻塞其余任务。
- **[代价] 三面 parity CI 增加维护** → 与双端同型,增量约一个 fixture 表。

## Migration Plan

纯增量(新方言目录 + 守卫新分支 + install 新旗标)。双端行为零变化由「dsh 方言工具名不可能
出现于双端 payload」保证,回归测兜底。回滚 = 不装 `--dsh` 即无新代码路径被激活。

## Open Questions

1. ~~pre-execute 事件 payload 的字段名与 deny 返回形状~~ **已关闭(spike 1.1)**:
   `exec.name` / `exec.arguments`(冻结)/ deny = `return {kind:'deny', reason}`,reason 全文
   进模型可见工具结果,无截断(证据已并入 Context 段)。
2. ~~`$DSH_HOME` 在 Windows 的默认落点与 profile 目录自动创建行为~~ **已关闭(spike 1.1)**:
   默认 `%USERPROFILE%\.dsh`(本机实测存在);profile 目录只为模板名自动创建,自定义 profile
   缺失时报错并提示 `dsh plugin add`——install 接线据此**不静默建 profile**(Context 段)。
3. 未映射工具面里是否还有能落盘的路径携带者(如 `web_fetch` 的 out 参数)——首跑观察期
   收集,宁滥勿缺地先进 deny-list 候选注释、逐个钉死。
   **已关闭(验收 7.4,运行时插桩普查)**:真机 headless 会话逐工具调用 + shim 临时日志
   收集到的**全部未映射 id** = `todo_write` / `web_fetch` / `get_goal` / `list_agents` /
   `skill`,裁决如下:
   - `todo_write` / `get_goal` / `list_agents`:无文件系统写形态参数 → **保持不映射**;
   - `web_fetch`:仅 `url`(schema 无 out/save 参数)→ 不落盘,**保持不映射**;若上游将来
     增落盘参数,按 ApplyPatch 同形入表;
   - `skill`:按**名**解析、解析域限于宿主自己的 skills 目录,不携带任意目标路径 →
     **保持不映射**(观察项:若实测能从会话参数指定加载目录,再裁决)。
   附带观察:`run_code` 与 `terminal_*` 在 headless profile 的工具面上不出现(bash 面 win32
   禁用、shell 走 `pwsh`),守卫对应分支以直喂 payload 验证退出码 2;`job_list` 在 init 域
   运行中确实被 `JobCtl` 分支拦截(真机 deny 证据)。
