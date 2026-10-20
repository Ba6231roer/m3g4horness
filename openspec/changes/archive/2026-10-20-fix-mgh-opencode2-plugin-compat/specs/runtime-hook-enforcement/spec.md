## ADDED Requirements

### Requirement: opencode 2.x 插件模块契约与形状自检

The opencode `.ts` shim SHALL satisfy the opencode 2.x plugin module contract: a **default
export** of the form `{ id: <string>, setup: <async function> }`, with the
`tool.execute.before` hook registered via the plugin context's tool-hook API **and the
registration awaited inside `setup` before `setup` returns** (a fire-and-forget registration
lets the first tool call slip past an unregistered hook). The hook callback SHALL receive a
**single event object** and read the tool id from `event.tool` and the tool arguments from
`event.input` — the 1.x two-parameter `(input, output)` callback form is removed. The shim
SHALL remain glue-only (activation gating, regexes, whitelists, subtree decisions live only
in the Python guard). The repo's CI SHALL statically assert the module shape (default export
with `id` + `setup` present; the 1.x named-export form absent) so a future opencode
module-contract change cannot silently disable the guard again — opencode's own plugin-load
failure is fail-soft (a WARN in the service log, sessions continue), so shape drift SHALL be
caught by CI, not by runtime. The shim file targets the 2.x contract; 1.x opencode
installations keep the previously released shim file (no dual-shape file — a file satisfying
both contracts is not expressible, and carrying two files would double the wiring surface).

#### Scenario: 2.x 服务加载插件并触发单事件对象回调

- **WHEN** opencode 2.x 加载 mgh 插件(项目 `.opencode/plugins/` 自动发现)且任一会话发
  起工具调用
- **THEN** 插件以 default 导出被接受(服务日志无 `Plugin must export a default
  definition…` 拒载记录),`tool.execute.before` 回调收到含
  `tool/sessionID/agent/messageID/id/input` 的事件对象——不存在 `(input, output)` 双参形态

#### Scenario: 注册竞态防护

- **WHEN** 插件 `setup` 尚未返回时会话已发起首个被管工具调用
- **THEN** 因钩子注册在 `setup` 内被 `await`,该调用仍命中已注册的守卫管道——不存在
  「注册未完成 → 调用漏过 → 守卫静默缺席整段早期会话」的窗口

#### Scenario: CI 静态形状自检

- **WHEN** CI 检查插件源码(无 opencode 运行时)
- **THEN** 源码形状断言要求 `export default` + `{ id` + `await ctx.tool.hook(`(注册被
  await)存在,且 1.x 具名导出形态(`export const BlockAdhocScripts` / 双参回调)缺席——
  模块契约漂移从「运行期静默拒载」变为 CI fail-loud

#### Scenario: 宿主拒载的 fail-soft 边界保持披露

- **WHEN** 宿主自身因任何原因未加载插件(宿主侧加载失败按其设计 fail-soft,仅 WARN)
- **THEN** mgh 不在插件内自救;「守卫缺席 → PASS」的运行期 fail-soft 契约不变,守卫不在
  场的事实由 install 自检与实机验证闸门(双版本加载检查)在安装/验证期暴露,不靠运行期
  症状发现

## MODIFIED Requirements

### Requirement: opencode shim feeds the guard payload via a Bun-compatible stdin

The opencode `.ts` shim SHALL feed the guard subprocess its JSON payload via a Bun-compatible
`stdin` form — `new Blob([<stringified payload>])` (or the `"pipe"` + `proc.stdin.write/end`
form). The shim MUST NOT pass a bare string to `Bun.spawn`'s `stdin`: opencode's bundled Bun
rejects a string stdin (`TypeError: stdio must be 'inherit'|'pipe'|'ignore'|Bun.file|number|null`),
which throws inside the shim's guard-invocation path; the shim's fail-soft handling then returns a
pass and the guard silently never blocks (the D7 incident — a `py -c` introspection one-liner ran
unblocked and zeroed 25 T1 checkpoints). The Python guard (single decision source) is unchanged.
**守卫脚本缺失时 SHALL fail-soft 放行**:shim 在 spawn 前做守卫文件存在性预检(缺失 → 放行 +
一条诊断日志,不 spawn)——python 对不存在的脚本文件以退出码 2 退出(`can't open file`),与守卫的
阻断退出码同值;无预检时一次守卫文件缺失/错位会被误判为 deny(与 fail-soft 契约「守卫不在 → PASS」
矛盾)。stderr 含 python「can't open file」签名的退出码 2 亦 SHALL 按 fail-soft 处理(存在性预检的
兜底)。

**2.x 形态增补**:回调从 2.x 单事件对象取参——工具名读 `event.tool`,工具参数读
`event.input`(1.x 的 `(input, output)` 双参形态移除);payload SHALL 携带 `cwd` 字段 =
插件 `setup` 时捕获的项目根(`ctx.location.directory`)——2.x 插件随常驻服务进程运行,
服务进程 cwd 与被分析项目无关,不注入则守卫锚点链(哨兵发现与相对 token 判定)系统性指错
地方;守卫侧既有优先级(payload `cwd` > 守卫进程 cwd)不变,Python 侧零改动。非阻断诊断
(1.x 经 `ctx.client.app.log` 上报)在 2.x 无对应通道,SHALL 降级为 best-effort 输出;
阻断契约(守卫退出码 2 → throw stderr 作 recipe)不变。

#### Scenario: a py -c introspection one-liner is blocked in opencode

- **WHEN** an opencode session is inside an mgh run-domain (env `MGH_*_ACTIVE=1` at opencode launch
  OR the `<cwd>/<run-root>/.active` sentinel present) and the model issues a Bash `py -c` command
  carrying introspection tokens (`import json` / `open(` / `load(` / `.json`)
- **THEN** the shim feeds the normalized payload to the guard as `new Blob([stdin])`, the guard
  exits 2, the shim throws and the tool call is blocked (the model sees the sanctioned-primitive
  recipe) — the guard is NOT silently disabled by a stdin-delivery throw

#### Scenario: missing guard file degrades to a pass, not a deny

- **WHEN** the guard script file is absent/moved at the shim's resolved path(an incomplete or
  skewed install), and a handled tool call occurs inside a run-domain
- **THEN** the existence pre-check fails → the shim passes the call + logs one diagnostic
  (fail-soft);python's can't-open-file exit 2 is NEVER interpreted as a deny(修复前该形态 =
  误判 deny,与「守卫不在 → PASS」契约矛盾)

#### Scenario: 2.x 服务进程 cwd 非项目根时锚点仍正确

- **WHEN** opencode 2.x 常驻服务进程的 cwd 在别处(如用户主目录),项目内存在
  `<项目>/.mgh-init/.active` 哨兵,模型发起 `bash` 越树写或含 `..` 相对 token 的命令
- **THEN** shim 注入的 payload `cwd` = 项目根,守卫的哨兵发现与相对 token 判定都以项目根
  为锚(修复前回退服务进程 cwd → 哨兵整链发现不到 → 守卫对整个 run 休眠,越树写静默放行)

#### Scenario: the shim source form is regression-guarded in CI

- **WHEN** the shim source is checked in CI (no Bun runtime available)
- **THEN** a parity-test source-form assertion requires `new Blob([stdin])` AND the guard-file
  existence pre-check AND the 2.x single-event-object read(`event.tool`/`event.input`)AND the
  `cwd` injection(`ctx.location.directory` 捕获后写入 payload)to be present, preventing a
  silent revert to a bare string stdin, to exit-code-conflating deny logic, or to the un-anchored
  2.x form (the runtime delivery itself is verified manually in opencode on both 2.0.x and 2.1.x)

### Requirement: opencode shim normalizes read-side tools to the guard

The opencode `.ts` shim SHALL feed the guard for `read`/`glob`/`grep` tool events (in addition to
`bash`/`write`/`edit`), normalizing opencode's camelCase args to the Claude `{tool_name, tool_input}`
stdin shape the guard expects: `read` → `{tool_name:"Read", tool_input:{file_path}}`;
`glob` → `{tool_name:"Glob", tool_input:{pattern, path}}`; `grep` →
`{tool_name:"Grep", tool_input:{pattern, path, glob}}`. The shim SHALL remain glue-only — the
read-side out-of-tree decision logic lives ONLY in the Python guard (single decision source, zero
drift). The shim's `HANDLED` set SHALL include `read`/`glob`/`grep` alongside `bash`/`write`/`edit`.
**2.x 工具名增补**:opencode 2.x 更名的工具 id 与 1.x 旧 id SHALL 同时收敛到同一守卫面——
`shell`(2.x 的 bash 更名)与 `bash` 都映射 `{tool_name:"Bash", tool_input:{command}}`;
2.x 的补丁工具 id(若与 `apply_patch` 不同名)与 `apply_patch` 都走补丁面提取。`read`/
`glob`/`grep` 在 2.x 名字不变。

#### Scenario: opencode read event is normalized and decided by the guard

- **WHEN** an opencode session is inside an `mgh-init` run-domain and the model issues a `read` tool
  call with `filePath=D:\parent\sonB\x.java` (outside `target=D:\parent\sonA`)
- **THEN** the shim normalizes it to `{tool_name:"Read", tool_input:{file_path:"D:\\parent\\sonB\\x.java"}}`,
  feeds it to the guard (single decision source) via `new Blob([stdin])`, the guard exits 2, and the
  shim throws to abort the tool call (the model sees the read-side recipe) — the read-side decision
  does not drift between platforms

#### Scenario: 2.x `shell` id 收敛到同一 Bash 面

- **WHEN** opencode 2.x 会话处于运行域内,模型经更名后的 `shell` 工具发起 `py -c` 内省命令
- **THEN** shim 把 `shell` 事件映射为 `{tool_name:"Bash", tool_input:{command}}` 喂守卫,
  守卫按 Bash 面判定并阻断(修复前 HANDLED 不含 `shell` → 事件漏过守卫 → 微脚本内省在 2.x
  裸奔)

#### Scenario: shim remains glue-only for the read side

- **WHEN** the shim source is checked in CI
- **THEN** a parity-test source-form assertion requires the shim to normalize `read`/`glob`/`grep`
  AND forbids it from reimplementing the read-side decision logic (e.g. `_read_out_of_tree` /
  `_out_of_tree_file_search` / `is_relative_to` / target resolution MUST NOT appear in the shim —
  single decision source)

### Requirement: opencode shim arg-name defense-in-depth for write/edit/read

The opencode `.ts` shim's `normalize` SHALL read the file path for `edit`/`write`/`read` from a fallback chain
`args.filePath ?? args.file_path ?? args.path` (the opencode tool schema field is `path`; relying solely on `filePath`
— which the LLM emits in camelCase — would silently yield an empty path if opencode ever passes schema-validated
args). This is a defense-in-depth with zero behavior change for the current camelCase-emitting LLM; it closes a
latent parity gap where a schema-validated `path` arg would bypass confinement (empty `file_path` → guard degrades to
pass). The `grep` source field SHALL be read as `args.include ?? args.glob` (the opencode schema field is `include`).
**2.x 形态下该链语义不变**:参数自 2.x 事件对象的 `event.input` 读取,回退链与字段名沿用。

#### Scenario: opencode write with schema-validated path arg is still confined

- **WHEN** an opencode session is inside an `mgh-init` run-domain and the model issues a `write` tool call whose args
  carry the path under the schema field `path` (not `filePath`), targeting `D:\out\f.json`
- **THEN** the shim's fallback chain resolves the path from `args.path`, the guard blocks the out-of-tree write with
  exit 2 + the write-side recipe (rather than silently passing on an empty `filePath`)

#### Scenario: 2.x 事件对象参数仍走同一回退链

- **WHEN** opencode 2.x 事件对象 `event.input` 携带 schema 校验形参数(`path` 字段而非
  `filePath`),目标越树
- **THEN** shim 自 `event.input` 读参并按同一回退链解析出路径,守卫照常阻断(2.x 事件形状
  不引入新的空路径旁路)

### Requirement: Guard tool-surface wiring coverage enforced by CI

The guard's decision-branch tool set (every tool name the guard's `main()` dispatches on:
`Bash`, `Write`, `Edit`, `MultiEdit`, `NotebookEdit`, `ApplyPatch`, `Read`, `Glob`, `Grep`, plus
the dsh-dialect names mapped in by the third wiring face) SHALL be fully covered by ALL THREE
host wiring faces, and a CI regression test SHALL enforce it: (a) the claude-side default
PreToolUse matcher injected by `tools/install_hook.py` SHALL contain every guard tool name;
(b) the opencode `.ts` shim's `HANDLED` set (plus its `normalize` mapping) SHALL cover every
guard tool name (via its lowercase mapping),**并且同一守卫面在 opencode 2.x 与 1.x 的两代
工具 id SHALL 同时在收(converged)——`shell`/`bash` → Bash、2.x 补丁工具 id/`apply_patch` →
ApplyPatch**;(c) the dsh `.ts` shim's handled-tool set (plus its dsh→guard name mapping,
including the tools admitted only through the dsh dialect: the bundled code runner, the
PowerShell tool, the terminal I/O tools, the job tools, and the patch-shaped editor) SHALL
cover every guard tool name reachable on dsh. Adding a guard decision branch without extending
all wiring faces SHALL fail the regression test (exit non-zero), structurally closing the
"dead branch" gap class on all three hosts — the claude matcher previously covered only
`Bash|Write|Edit`, leaving the read-side branches unconsulted (an out-of-tree `Read` reached
the host permission prompt and interrupted the run instead of failing loud with a recipe), and
nothing prevented the same drift on either host.

#### Scenario: matcher covers the full guard tool surface on fresh install

- **WHEN** `install.sh --claude <target>` 注入 PreToolUse hook
- **THEN** settings.json 的 matcher 含守卫全部分派工具名(`Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Glob|Grep`)

#### Scenario: reinstall evolves a narrower legacy matcher in place

- **WHEN** 目标项目 settings.json 已有 `block_adhoc_scripts` 条目且 matcher 为旧的
  `Bash|Write|Edit`,重跑 `install.sh --claude`
- **THEN** 该条目的 matcher 被更新为全工具面默认值(按 command 内 `block_adhoc_scripts` marker 锚定,
  只改 matcher、不动用户自定义 command;用户自定义非子集 matcher 不动 + stderr 提示;幂等)

#### Scenario: CI fails when a guard branch lacks wiring coverage

- **WHEN** 守卫源新增一个分派工具名(如未来加 `WebFetch`),而 matcher、opencode shim `HANDLED`
  或 dsh shim 分派集任一端未同步扩
- **THEN** 接线覆盖回归测 fail(非零退出)——「新增分支忘扩接线面」从「静默死代码」变为 CI 拦截

#### Scenario: opencode 工具更代时两代 id 同时在收由 CI 强制

- **WHEN** opencode 2.x 更名某工具(bash→shell)且 shim 增补新 id 而删掉旧 id(或反之只留旧 id)
- **THEN** 接线覆盖回归测对 opencode 面断言「两代 id 并存收敛到同一守卫面」——删掉任一代 id
  即 fail(防止「升级断代」与「回退断代」两种静默漏收)

#### Scenario: out-of-tree Read is consulted by the guard on claude

- **WHEN** claude 会话处于 `mgh-init` 运行域(激活),模型 `Read` 一个越树路径(如 `..` 链折叠后落
  `D:\xxxx`)
- **THEN** PreToolUse hook 被触发(matcher 含 `Read`)→ 守卫退出码 2 → 工具调用被阻断、模型看到
  read-side recipe;**不出现**宿主 D 盘根权限询问(报告的中断形态消除)

### Requirement: 哨兵发现与路径判定共用单一 cwd 源

守卫内**判定用 cwd**(`..` 相对 token 解析、listing/mutation 的 cwd 缺省锚、`Glob`/`Grep` 无 `path`
时的锚)SHALL 与**哨兵发现的锚**同源:payload `cwd` 字段(host 携带会话/工具上下文 cwd 时)优先,
回退守卫进程 cwd。SHALL NOT 判定走 `Path.cwd()` 而发现走 payload `cwd` 的双源形态——两源可错根
(claude 面 payload cwd = 发起调用的会话上下文,守卫进程 cwd 可在别处),错根时相对路径按错误根解析、
无 `path` 的读面按错误锚判定,产生系统性误判(该拦不拦 / 误拦)。payload `cwd` 存在但不可解析时回退
进程 cwd(NEVER 因锚不可用而崩溃)。**opencode 2.x 面**:插件随常驻服务进程运行,服务进程 cwd 与
被分析项目无关,shim SHALL 在 `setup` 时捕获 `ctx.location.directory`(项目根)并作为 payload
`cwd` 字段逐调用注入——「无 `cwd` 字段回退进程 cwd」不再是 opencode 面的依赖路径(claude/dsh 面
各自携带 cwd 的既有形态不变;进程 cwd 回退仅作最后兜底)。

#### Scenario: claude 面 payload cwd 同时驱动哨兵发现与相对 token 判定

- **WHEN** claude 面 payload 携带 `cwd=D:\parent\sonA\sub`(守卫进程 cwd 在别处),命令为
  `type ..\..\secret.txt` 且 `MGH_TARGET=D:\parent\sonA`
- **THEN** 守卫以 payload `cwd` 解析 `..` 相对 token(与哨兵发现同一锚)→ 落在树外 → exit 2 +
  recipe(修复前按进程 cwd 解析,错根时误判)

#### Scenario: opencode 2.x 插件注入项目根作锚

- **WHEN** opencode 2.x 常驻服务进程 cwd 在用户主目录,项目 `<项目>/.mgh-sdr/runs/…` 运行域哨兵
  在 `<项目>/.mgh-sdr/.active`,模型经 `shell` 工具发起含树外绝对路径的命令
- **THEN** shim 注入 payload `cwd=<项目根>` → 哨兵发现自项目根向上走链命中 `.active` → 守卫激活
  并以同一锚判定路径(修复前回退服务进程 cwd → 哨兵发现空转 → 守卫休眠)

#### Scenario: 无 payload cwd 的面回退进程 cwd(行为不变)

- **WHEN** 某面发来的 payload 无 `cwd` 字段(claude/dsh 均携带 cwd,此为兜底路径)
- **THEN** 判定与发现均以守卫进程 cwd 为锚(既有行为;单一来源,无双源错根面)
