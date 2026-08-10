# harden-mgh-opencode-hook-binding — 设计

## Resolution(2026-08-10 —— 根因确认 + fix 落地 + 已验证)

**根因(opencode 1.18.3 in-opencode probe 实测,非推测)**:shim `runGuard` 的 `Bun.spawn({stdin: <string>})`
在 opencode 自带 Bun 上**抛 TypeError**(`stdio must be 'inherit'|'pipe'|'ignore'|Bun.file|number|null`,拒收字符串
stdin)→ catch → **fail-soft-pass(code 0)** → `code===2` 永不成立 → 守卫在 opencode 上**从未阻断**。probe 否决了
其余全部候选(插件自动加载 ✓、`tool.execute.before` 触发 ✓、`plugin_cwd=项目根` ✓、哨兵在 ✓、guard 在场 ✓、
tool-id `"bash"` + `output.args.command` ✓——见下方「取证更新」)。

**fix(已落地、已验证)**:`releases/opencode/plugins/block_adhoc_scripts.ts::runGuard` `stdin: stdin` →
`stdin: new Blob([stdin])`(+ 承重注释);`tests/test_opencode_hook_parity.py` 加源码形态回归断言(CI 跑不了 Bun);
`VERSION` 0.1.23;真实 opencode shim 复测 `py -c "import json; json.load(open('x.json'))"` **被拦** ✓。守卫 `.py`
(单一决策源 + 双端字节一致 invariant)未动。

**未做(本变更 out-of-scope,记为 deferred)**:`MGH_HOOK_DEBUG` 可观测性 + 安装期插件自检——会让本类 fail-soft
静默吞错更快暴露;另立或后续(见记忆 `opencode-plugin-runtime-gotchas`)。下方 Goals/Non-Goals、Decisions 等段
为调查过程中的推理(部分基于早先假设,已被「取证更新」与本 Resolution 收窄/取代),保留作调查日记。

## Context

`docs/review-mgh-init-t1-record-schema-drift.md` §十一(D7):一条 `py -c` 内省 one-liner(「修 BOM」)在
`/mgh-init --resume` 运行域内由 LLM 自发执行,未被 `block_adhoc_scripts` 拦截 → 25 个 T1 checkpoint 归零。
R5.2/R5.7 的确定性闭环在 opencode 上失败了。

已确认事实(用户会话日志 + 源码,非推测):
- **Python 守卫(单一决策源)无责**:激活满足(env `MGH_INIT_ACTIVE=1` + 哨兵 `<target>/.mgh-init/.active`
  四 key 完整);检测满足(`_PYC_RX:69` 命中 `py -c` + `_INTRO_TOKENS:71` 命中 `open(`/`.json`)→
  `_is_introspect_py_c` 应 True → 守卫应 exit 2)。激活与检测均无漏判。
- **失效在 opencode `.ts` shim 绑定层**(`releases/opencode/plugins/block_adhoc_scripts.ts`),5 候选源码不可
  区分(opencode 运行时事实):① tool id 不匹配(`HANDLED={"bash","write","edit"}`,opencode 真实 shell 工具
  id 可能 ≠ `"bash"`);② 事件参数路径错位(`normalize` 读 `output.args.command`,实际可能不在 `output.args`);
  ③ cwd 不对(`process.cwd()` ≠ `<target>` → 哨兵找不到);④ 插件未加载(导出形状/注册不符);⑤ fail-soft
  默认放行(`:81-84` 只 `code===2` throw,其余 pass)。
- **parity 测盲区**:`tests/test_opencode_hook_parity.py` 覆盖**归一化映射**(`normalize` 镜像)+ **守卫双端字节
  一致**(`CC_GUARD==OC_GUARD`)+ 「shim 不重实现守卫逻辑」。**不覆盖**运行时「插件是否加载/触发/cwd 对不对」
  → parity 过但绑定可破。守卫 `.py` 不可责、不可改(单一决策源 + 字节一致 invariant)。

## 取证更新(2026-08-10,用户实机 + opencode 官方文档;fix 正文待实验后据实重写)

用户在真实 opencode 全新 session 实测 + 核对官方文档([Plugins](https://opencode.ai/docs/plugins/),
2026-08-07),收窄原 5 候选:

- **Python guard 决策逻辑独立可用 ✓**(用户实机:`MGH_INIT_ACTIVE=1` pipe payload,1.1–1.5 全符合设计)——再次印证守卫无责。
- **激活语义 ✓** = env 或哨兵;运行域外 return 0(line 285)是设计意图(只在 orchestrator run-domain 生效)。
- **候选 #1(tool-id)/ #2(事件路径)否决**:官方文档示例逐字一致——bash 用 `input.tool === "bash"` +
  `output.args.command`;read 用 `output.args.filePath`。我们 shim 的 `HANDLED`/`normalize` 正确。
- **候选 #4「需 opencode.json 注册」否决**:官方文档明示本地 `.opencode/plugins/*.ts` **启动时自动加载,无需
  opencode.json**;`opencode.json` 的 `"plugin":[]` 是给 **npm 包名**用的(塞本地路径会被当包名解析失败)。
  `install_opencode_plugin.py` docstring「auto-loads ... NO config registration」本来就对。**fix 方向绝非写 opencode.json。**
- **用户「全新 session 没拦截」被其 #3(无激活)单独完全解释**,非「插件未加载」——证加载与否须**激活态**测。

**修法收窄(待实验确认)**:cwd 鲁棒用插件 ctx 的 `directory`(官方插件函数签名提供
`{project, client, $, directory, worktree}`,`directory`=cwd),**非** `process.cwd()`(插件进程 cwd 可能
≠ 项目根,文档未保证)、**非** 本设计原 D2 的 `import.meta.url` 推导。原 D2(import.meta.url)降级为备选。

**剩余活跃假设**(决定性实验裁定):H-cwd(用 `ctx.directory` 修)/ H-load(模块加载期抛错:`Bun.spawn`·
`node:url`·`import.meta.url` 在插件运行时可用性,文档未保证)/「激活态其实能拦」(原 D7 事故另查:当时激活
是否真在 / 版本差)。实验:激活态(env 启动 OR 哨兵)+ 不写 opencode.json + 跑 `py -c "import json;
json.load(open('x.json'))"` → 拦/不拦裁定。

**追加(2026-08-10,opencode 1.18.3 实测)**:激活态实验 A(env 启动)与 B(哨兵)**均未拦截**;
5 行 probe(`.opencode/plugins/_probe.ts`,module-load / 函数注册 / tool.execute.before 三 marker)**全出** →
**1.18.3 自动加载 `.opencode/plugins/*.ts` 成立、plugin 函数被调、`tool.execute.before` 对 `bash` 触发**。故
**#4「插件未加载」与 H-load「加载期抛错」均被实测否决**;DEBUG 无 plugin 日志 = 1.18.3 不打 plugin 加载日志
(红鲱鱼)。失败**定位在我们 shim 的 `runGuard`**(hook 触发之后):嫌疑——
- **S1 stdin 未正确 pipe** → 守卫 `json.load(sys.stdin)` 读空 → except → return 0(「never block」);
- **S2 `Bun.spawn`/`Bun` 在插件 ctx 不可用** → `runGuard` 抛 → catch fail-soft pass(code 0);
- **S3 守卫 cwd=`process.cwd()` ≠ 项目根** → `<cwd>/.mgh-init/.active` 找不到哨兵 → 不激活(env 亦可能未继承);
- **S4 `guardPath()`(`new URL("../hooks/…", import.meta.url)`)解析错或 guard 未镜像到 `.opencode/hooks/`** →
  py 报错、code≠2 → pass。
下一 probe(runGuard 插桩:记 cwd/guard_exists/sentinel/spawn 结果/exit code/stderr)裁定 S1–S4,再据实定稿 fix。

**根因确认(2026-08-10,probe v2 复现)**:`spawn=THREW TypeError: stdio must be an array of
'inherit'/'pipe'/'ignore'/Bun.file(pathOrFd)/number/null` —— **S2 坐实为真根因**:opencode 1.18.3 自带 Bun 的
`Bun.spawn({stdin: <string>})` **拒收字符串 stdin**(受收集仅 `{'inherit','pipe','ignore',Bun.file,number,null}`);
shim `runGuard` 传 `stdin: stdin`(JSON 字符串)→ **每次调用都抛 TypeError** → catch 既非 ENOENT 也不 continue →
**fail-soft pass(返回 code 0)** → `code === 2` 永不成立 → 永不 throw 阻断。probe v2 复用 shim 同款 `stdin: <string>`,
**确定性地复现**了该失败。同时 `plugin_cwd=项目根` ✓(排除 S3)、`guard_exists=true` ✓(排除 S4)、`sentinel_at_cwd=true` ✓。
**fix**(待 probe v3 确认 delivery):`stdin: "pipe"` + `proc.stdin.write(payload); proc.stdin.end()`(仅用受收值);
S1(stdin 读空)随之消解。守卫 `.py` 不动;改动仅在 shim `runGuard`。

## Goals / Non-Goals

**Goals:**
- 取证优先:把 5 候选从「源码猜」变成「运行时定位」——shim 诊断模式 `MGH_HOOK_DEBUG=1` 在真实 opencode 会话
  记录 handler 触发/`input.tool`/`output.args` 形状/cwd/守卫调用与退出码,定位真凶后再校准。
- 立即加固(独立于真凶,确定性可现在实现):① shim 从**插件自身位置**解析项目根作守卫 cwd(候选 #3 闭合);
  ② 安装期插件自检(在场 + 结构 + 导出形状,承 R5.8)→ 候选 #4 在安装期可现;③ fail-soft 收窄到瞬时 spawn
  错误 + `MGH_HOOK_DEBUG=1` 使静默不强制可观测。
- 按发现校准:修 `HANDLED`/`normalize` 匹配真实 opencode 工具接口,parity 测锁定。
- 守卫 `.py`(单一决策源)**不改**,双端字节一致 invariant 保持。

**Non-Goals:**
- 不改守卫 `block_adhoc_scripts.py`(Python 单一决策源;激活/检测已确认正确)。
- 不翻 fail-soft 为 fail-closed(瞬时 spawn 错误 fail-closed 会破坏会话;改为「可观测 + 安装期可检」)。
- 不重实现 D6 减害(无 BOM 地基在 `fix-mgh-init-t1-record-schema-drift`,交叉引用)。
- 不追求 CI 内全自动验证「插件在真实 opencode 加载/触发」(需 opencode 运行时,是人工取证步骤;CI 验证
  「在场 + 结构 + 导出形状 + 项目根解析」这一可达上限)。

## Decisions

### D1 — 取证优先,非「猜了再改」

5 候选是 opencode 运行时事实,源码层不可区分。**第一步是实现诊断模式 + 真实 opencode 取证**,定位真凶后
才校准 `HANDLED`/`normalize`。NEVER 凭源码直接改候选 #1(tool id)——若真凶是 #4(未加载),改 tool id 是
空操作且留下残留漏洞。

理由〔源码不可定 + 猜错=白工+残留漏洞 + 诊断模式使复验廉价〕。承记忆「verify before trusting」与 review 自陈
「待确认(opencode 运行时取证)」。

### D2 — cwd 从插件自身位置解析(implement-now,严格更鲁棒)

shim 用 `import.meta.url`(plugin = `<project>/.opencode/plugins/block_adhoc_scripts.ts`)推导项目根(含
`.opencode/` 的目录),作守卫子进程 cwd,**不**只靠 `process.cwd()`。无论真凶是否为 cwd(#3),这都是严格
更鲁棒(插件文件位置 = 项目根的确定锚点),故**无条件立即实现**,不等取证。

理由〔插件位置是项目根的确定锚点 + 与真凶正交 + 闭候选 #3〕。claude 端不变(PreToolUse 已 cwd=项目根)。

### D3 — 安装期插件自检(承 R5.8,implement-now)

`install.sh --opencode` 装后断言:① 插件文件在场;② 结构/词法有效(含 `tool.execute.before` handler key +
`HANDLED` + `normalize` + 守卫 spawn 关键标记);③ 导出形状匹配 opencode 插件接口契约。失败 = install
warn(fail-soft install)+ CI fail。**.ts 不在零依赖 AST 扫描集**(`test_opencode_hook_parity::test_ts_not_in_
zero_dep_scan_set`),故自检用**结构 grep/标记断言**(非完整类型检查,非语义)——这是 install 期可达上限。

候选 #4(未加载/形状不符)在安装期可现,而非运行时静默。理由〔承 R5.8 install 自检 + 把运行时事实的子集
(在场/结构/形状)前移到确定性安装期 + .ts 扫描集约束决定用结构断言〕。

### D4 — fail-soft 收窄 + 可观测,非 fail-closed

保留 fail-soft-pass 用于**真·瞬时**守卫 spawn 错误(python 缺失/ENOENT/spawn 失败)——fail-closed 会在
python 抖动时破坏会话,更糟。问题不是 fail-soft 本身,是「静默不强制」**不可见**。故:① fail-soft 限于瞬时
spawn 错误;② `MGH_HOOK_DEBUG=1` 下 fail-soft/pass 路径打 log;③ 「未接线/不可加载」经 D3 安装期可现。

理由〔fail-closed 破坏会话更糟 + 真问题是不可见 + 可观测+安装可检收窄静默窗口〕。承 review §十一候选 4
权衡。

### D5 — 守卫 .py 不改;全部修复在 shim + install + 测

守卫 `block_adhoc_scripts.py` 是单一决策源,双端字节一致 invariant(`CC_GUARD==OC_GUARD`)由 parity 测强制。
所有 D7 修复落在 `.ts` shim(cwd 解析、诊断、fail-soft、按发现校准 HANDLED/normalize)+ `install.sh`(自检)+
`tests/`(parity 扩展)。守卫逻辑零改动 → invariant 自动保持。

理由〔单一决策源不可破 + 字节一致是产品特性〕。

### D6 — D6 减害交叉引用(独立降爆炸半径)

`fix-mgh-init-t1-record-schema-drift` 的无 BOM 地基消除「修 BOM」动机 → 即便 D7 绑定窗口残留,这类由 BOM
诱发的 LLM 自发脚本失去触发器。本变更不重实现,仅在 design/impact 交叉引用,表明 D7 风险经两条独立路径收敛
(绑定可靠 + 诱因消除)。

## Risks / Trade-offs

- [取证需真实 opencode 会话,CI 不可全自动] → 取证为人工步骤(apply 在此暂停);implement-now 部分(cwd/自检/
  诊断/fail-soft)CI 可测,校准取证门控。Migration Plan 明示此约束。
- [插件位置假设:`<project>/.opencode/plugins/`] → 为 `install.sh` 部署路径;用户重定位插件则解析破。Mitigation:
  解析点即 install 落盘点;D3 自检断言插件在预期位置;契约 doc 记此假设。
- [install 自检无法对 .ts 完整类型检查(无 opencode/Bun)] → 用结构标记断言(在场 + 关键 token + 导出形状),
  非语义。明确其为结构层、非完整类型检查;运行时「加载/触发」仍靠 `MGH_HOOK_DEBUG` 取证。
- [校准可能跨 opencode 版本漂移] → 取证 + parity 测为所测 opencode 版本钉绑定;opencode 升级需重取证。诊断
  模式使复验廉价;契约 doc 记「升级需重取证」。
- [fail-soft 对瞬时错误残留窗口] → 接受(fail-closed 更糟);诊断 log + 安装自检使窗口可观测/可检而非静默;
  + D6 减害降爆炸半径。

## Migration Plan

1. shim:`import.meta.url` 推导项目根作守卫 cwd(替/补 `process.cwd()`)+ `MGH_HOOK_DEBUG=1` 诊断日志 +
   fail-soft 收窄(瞬时 spawn 错误才 pass,且 debug 下打 log)。implement-now,CI 可测。
2. `install.sh --opencode`:插件自检(在场 + 结构标记 + 导出形状),fail-soft install + CI fail。
3. `tests/test_opencode_hook_parity.py` 扩展:shim 项目根解析断言 + 导出形状/结构标记断言(不重实现守卫逻辑
   的 invariant 保持)。
4. `core/contracts/hooks/runtime-enforcement.md`:增「opencode 绑定可验证性」段(诊断模式 + 安装自检 + cwd
   鲁棒 + fail-soft 边界)。
5. **取证(人工,门控校准)**:真实 opencode `/mgh-init --resume` 会话设 `MGH_HOOK_DEBUG=1` + `MGH_INIT_ACTIVE=1`
   + 哨兵,跑已知 `py -c` 内省命令,据日志定位 5 候选真凶,记录发现。
6. 按发现校准:修 `HANDLED` 工具 id 集和/或 `normalize` 事件参数路径;parity 测增锁定测。
7. 手工复现:确认 D7 one-liner 形状(`py -c` + `open(` + `.json`)在 opencode 现被阻断(exit 2 + recipe)。
8. `VERSION` bump(承 R5.8);全量回归 + parity + 纯净 + 零依赖照跑。

回滚:任一步回归失败 revert 对应文件 + 版本回退。shim 改动不破坏守卫(.py 不动);install 自检 fail-soft 不
阻断 install。

## Open Questions

- opencode 真实 shell 工具 id + `tool.execute.before` 事件参数路径:**取证待定**(pre-取证不可定;tasks 门控
  于发现)。候选:`"bash"` + `output.args.command` / `output.args.filePath`(当前假设)vs `shell`/`exec` 等。
- opencode 是否暴露插件加载确认(使安装自检能验「已注册」而非仅「在场」):依赖 opencode 版本;安装自检达
  「在场 + 结构 + 导出形状」这一仓内可达上限,运行时「注册/触发」靠 `MGH_HOOK_DEBUG` 取证。
