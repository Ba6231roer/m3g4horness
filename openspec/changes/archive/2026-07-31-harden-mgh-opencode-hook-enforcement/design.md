## Context

`block_adhoc_scripts.py`(claude `PreToolUse` + opencode `.ts` 插件共用同一 Python 守卫)是 R5.7 的
**确定性交付物**——把「编排器黑盒纪律」从提示词自觉升级为运行时硬边界。但 `/mgh-init` 真机跑暴露
**守卫整 run 形同虚设**:agent 改了 `list_clusters.py`/`merge_scout.py`、写 `process_*.ps1`/`_*.py`、
往项目根 dump `temp_clusters1~n.json`、读写 `%LocalAppData%\Temp`。审计守卫定位到**四条缝隙**(见
proposal「Why」),根因集中在两点:**激活靠 mid-session env(opencode 不继承→休眠)** 与 **白名单过宽
(把 agent 改叶脚本当 install 写放行)**。

既有底子:`.ts` 插件已是纯胶水(事件归一化 → 管道喂 `.py` → 据退出码 2 阻断),判定逻辑单一来源在
`.py`;`_is_out_of_tree` 子树守卫、`_is_whole_aggregate_read`、`_is_introspect_py_c` 三条规则齐备;四域
(`MGH_{INIT,SAST,SRA,SRR}_ACTIVE`)已 wired。本变更**不重写守卫架构**,只修激活模型 + 收紧写入判定 +
补 init 受信子树,并把分散在各命令 spec 的 hook 要求收敛进新共享 spec `runtime-hook-enforcement`。

与 `harden-mgh-init-context-resilience` 的关系:**正交、无 apply 依赖**。context-resilience 治「上下文
压力下丢步骤序列」(跳过 `init-scout-merge` → 读 `merge_scout.py` 源码反推格式 → 造畸形
`scout_candidates.json`),本变更治「守卫不激活 + 白名单过宽」(agent 改叶脚本 / `py -c` 微脚本内省 /
读写 `%TEMP%` + 新报 `process_*`/`temp_clusters*`)。两者可任意先后 apply。哨兵机制**不依赖**
`run_config.json`(本变更自带的 Bash 写哨兵独立可用;init 的 `write_runconfig.py` 若已 apply 可兼带哨兵,
纯属优化、非依赖)。

> **词汇**:下文「缝隙 1/2/3/4」= proposal「Why」枚举的四条守卫缝隙(1 激活靠 mid-session env;
> 2 白名单误放行叶脚本编辑;3 只拦 `.py`; 4 子树守卫只挡树外)。本变更自洽引用,不依赖任何外部问题清单。

## Goals / Non-Goals

**Goals:**
- **守卫在 opencode 上可靠激活**(治缝隙 1):磁盘哨兵绕开「插件不继承 mid-session env」;哨兵携
  `target_abs` 使 `MGH_TARGET` 在 opencode step 0 即就绪。
- **运行域脚本只读**(治缝隙 2+3:见 D2 取消白名单 + D3 扩展名集):运行域内一切脚本扩展名写入 fail-loud。
- **init 写入限定受信子树**(治缝隙 4;缝隙 1 的 `%TEMP%` 写亦被挡):正向允许清单挡树外**与**树内非受信位置。
- **收敛 hook 契约到单一 spec**:新 `runtime-hook-enforcement` 取代分散重复的 per-command hook 要求。

**Non-Goals:**
- **不改守卫架构**:`.ts` 仍是胶水;判定单一来源在 `.py`(双端 parity 不破)。
- **不收紧 sast/sra/srr 的写入子树**(只 init 加正向允许清单;三域保留既有「树外拦截」,未报告根污染)。
- **不改「压力下打断征求」编排行为(非 hook)**:提示词护栏,hook 拦工具调用管不了「agent 是否提问」;
  归 `harden-mgh-init-context-resilience` 编排行为段(同「干净停止 vs 打断」主题)或另立小 change(见
  proposal Scope boundary + `new_issue26073101.txt`)。
- **不做声明式 step manifest**(衍生想法):见 D6,另立任务。
- **不改 introspection / aggregate-whole-read 规则**(已是稳定防御;只在共享 spec 引述)。
- **不覆盖「agent 改非脚本产物」**(如改 `.md` rules 正文)——那是 rules-purity lint / T4 职责,非 hook。

## Decisions

### D1 — 激活 = env **或** 磁盘哨兵(治 opencode 不继承 mid-session env)

哨兵文件 `<target>/.mgh-<domain>/.active`,JSON:`{"domain":"mgh-init","target":"<abs target>",
"out_roots":["<abs>..."],"v":1}`。编排器 step 0 经 **Bash** 写(`printf '%s' '{...}' > <path>`,
或 init 由 `write_runconfig.py` 兼带——优化项,非依赖);run 完成 / 干净停止时移除。

守卫 `main()` 激活判定 = `MGH_*_ACTIVE=1` env **或** `<cwd>/.mgh-<domain>/.active` 存在。哨兵发现
**cwd-relative**(各域 run 根:init→`.mgh-init/`、sast→`security-scan/`、sra→`.mgh-sra/`、srr→`.mgh-srr/`);
`target_abs` 从哨兵取(优于 cwd,支撑 target≠cwd 的子树判定)。MGH_TARGET 取值优先级:**env > 哨兵.
target > cwd**。

- **vs 默认激活 / run-dir 存在即激活**:太 fuzzy(stale `.mgh-init/` 会让日常开发也被守卫),拒。
- **vs opencode 启动检测**:不解决 mid-session 起 run,拒。
- **为何 cwd-relative**:opencode 插件 `cwd: process.cwd()`、claude hook cwd = 项目根;`/mgh-*` 实际均
  target=cwd 运行。target≠cwd 的异型 setup:claude 走 env 覆盖,opencode 为罕见边界(open question Q1)。
- **为何 Bash 写而非新脚本**:加新脚本 = 加 R5.1 契约面;`printf` 零依赖、host-neutral、无新 contract。

### D2 — 运行域脚本只读:取消白名单豁免(治缝隙 2)

`_is_blocked_py_write` 现放过 `"core/scripts" in path` + `_WL_SEGMENTS={tests,tools,hooks}`。这些豁免
**只在守卫未激活(install/dev 态)有意义**——而未激活时 `main()` 早 return 0,豁免根本走不到。**运行域内
无任何合法脚本写入**(产物全是 JSON/`.md`:checkpoints、inputs、rules、manifest、report)。故守卫激活时
**拦截一切脚本扩展名写入**,豁免全删。叶脚本对 agent = **read-only**。install/CI 在未激活态跑,不受影响。

- **为何安全**:审计全部 sanctioned runtime 写——`discover_controls`/`merge_scout`/`assemble_rules`/
  各 `list_*` 写 JSON/`.md`;subagent 写 JSON checkpoint + `.md` rule + ack。**零**合法 `.py`/`.ps1`/`.ts` 写。

### D3 — 脚本扩展名集(治 `.ps1` 漏过)

`_is_blocked_py_write` 只看 `.py`。扩为集合 `_SCRIPT_EXTS = {.py, .ps1, .sh, .bash, .zsh, .bat, .cmd,
.ts, .js, .mjs, .cjs}`(含 opencode 插件胶水 `.ts`——install 时未激活可写,运行域内 agent 写即 adhoc)。
`.json`/`.md` **不进集**(合法产物),其位置由 D4 受信子表管。

### D4 — init 正向受信子树允许清单(治缝隙 4)

`_is_out_of_tree` 只挡树外。init 域升级为**正向允许清单**:Write/Edit resolved 目标 MUST 落入:

| 受信子树 | 用途 |
|---|---|
| `<target>/.mgh-init/**` | 全部 artifacts / checkpoints / inputs / manifest / report / 哨兵 |
| `<target>/.claude/rules/**` | claude rules 产物 |
| `<target>/docs/security-controls/**` | opencode 详述文件 |
| `<target>/AGENTS.md` | opencode 惰性索引 |
| `out_roots[]`(哨兵携,自定义 `--out`/`--rules-dir`) | 用户自定义产物根 |

**树外**(盘符根/`%TEMP%`)**与** **树内非受信**(项目根 `temp_clusters*.json`、`process_*.ps1`)均 fail-loud
(退出码 2)+ recipe。sast/sra/srr **不加正向清单**(保留既有树外拦截;未报告根污染,后续可对称收紧)。

- **为何 init-only**:根污染证据仅 init;三域产物路径已各自收窄(`.mgh-sra/`/`.mgh-srr/`/`security-scan/`)。
- **`out_roots[]` 治 over-block**:`--out`/`--rules-dir` 自定义到非默认位置时,编排器把解析后的绝对根写进
  哨兵,守卫据之放行——既挡污染又不误伤合法自定义产物。

### D5 — `.ts` 插件不改(单一判定来源留在 `.py`)

哨兵发现 / env 判定 / 扩展名集 / 受信子树 / 白名单 **全在 `.py`**。`.ts` 仍是「事件归一化 + 管道 +
据退出码 2 阻断」的胶水(已 `env: process.env` 继承 + `cwd: process.cwd()`,哨兵经磁盘可见,无需改)。
双端 parity(`tests/test_opencode_hook_parity.py`)不破。

### D6 — 与衍生想法(声明式 step manifest)/ 路径漂移的关系:hook 是确定性 backbone,manifest 另立

「路径漂移」(drift 到非项目目录 / 错路径 / 错格式)有两类互补解法:**硬边界**(本变更:哨兵+受信子树+
脚本只读,确定性、零上下文)与 **正向引导**(manifest:告知确切路径/格式,概率性、耗 token)。本变更用
hook 确定性 backbone 治路径漂移。manifest 的**残量**(统一声明式 step→{脚本路径/输入格式/产物路径/产物格式} 表)
**已被大幅覆盖**:`resume_state.py`(step/next_action)、`run_config.json`/`init_manifest.json`(磁盘态)、
fan-out 绝对路径契约(R5.3b `checkpoint_path`/`rule_path`)、`mgh-init.md` 的 stage→组件表 +
implementation-intention recipes。补全残量与 R5.6 token 预算(用户明示关切)直接冲突 → 另立
`improve-mgh-init-deterministic-step-manifest`(context-resilience apply 后)。本变更**不**扩 token。

## Risks / Trade-offs

- **[运行域脚本写入全拦 = 行为变更]** → 缓解:此为**预期治本**(运行域无合法脚本写);install/CI 未激活态
  不受影响;`tests/test_block_adhoc_scripts.py::test_pass_whitelisted_py_write` 翻为 BLOCK 断言(契约更新)。
- **[哨兵 crash 后残留 → 日常开发被守卫]** → 缓解:编排器完成/干净停止时移除;stale 检测(哨兵 mtime >
  阈值视为 stale degrade,Q2);用户可手 `rm`;残留期间只挡脚本写,不挡 JSON/`.md`/读。
- **[init 受信子表漏列 → over-block 合法写]** → 缓解:据 `mgh-init.md` Output 节穷举默认子树 + `out_roots[]`
  承载自定义 + 单测覆盖每一受信/非受信位置 + `--no-enforce-hook` 兜底。
- **[target≠cwd 的 opencode 异型 setup]** → 缓解:env(claude)覆盖;opencode 罕见,Q1 待决(哨兵路径可由
  env `MGH_TARGET` 提示定位)。
- **[`.ts`/`.js` 进扩展名集可能误伤]** → 缓解:运行域内无合法 `.ts`/`.js` 写(插件 install 时未激活写);
  未激活态日常前端开发不受影响。
- **[共享 spec 与 per-command hook 要求的边界]** → 缓解:共享 spec 收激活/脚本只读/受信子树(跨域同构);
  per-command 保留域细节(env var、aggregates、recipe 指向的 `list_*`、scenarios)。

## Migration Plan

- **纯 additive + 收紧**:守卫 `.py` 改激活模型 + 扩展名集 + 删白名单 + init 受信子表(既有规则不动);
  新共享 spec `runtime-hook-enforcement`;3 个 per-command hook 要求 MODIFIED(引用共享契约);命令壳加
  step-0 写哨兵 / 完成移除;AGENTS.md R5.7 段 B + R5.2 措辞;契约 `core/contracts/hooks/runtime-enforcement.md`。
- **无磁盘 schema 迁移**(哨兵是新文件、随 run 生灭、gitignore)。
- **回滚**:`git revert` 即整体回退(守卫回到 env-only + 白名单;哨兵文件无人写即自灭)。VERSION bump +
  CHANGELOG(R5.8)。
- **交付顺序**(见 tasks):L1 守卫 `.py` 四改 + 单测(翻白名单断言、加哨兵/扩展名/根污染/受信子树)→
  L2 新共享 spec + 3 per-command delta → L3 契约 → L4 命令壳(四壳 step-0 哨兵 + 移除)→
  L5 AGENTS.md R5.7/R5.2 → L6 opencode parity 测 + 端到端(模拟 opencode env 未继承→哨兵激活)。

## Open Questions

- **Q1(target≠cwd 的 opencode setup)**:哨兵 cwd-relative 发现是否够?是否接受 env `MGH_TARGET`
  提示哨兵路径?**建议**:cwd-relative 为主 + env `MGH_TARGET` 作哨兵定位提示(零额外机制)。留 impl。
- **Q2(哨兵 stale 检测)**:是否给哨兵加 mtime stale 阈值(如 >24h degrade)防 crash 残留?**建议**:加
  轻量 mtime 检查(防残留锁死日常开发);阈值留 impl。
- **Q3(哨兵由谁写)**:init 用 `write_runconfig.py` 兼带(若 context-resilience 已 apply)还是统一 Bash
  `printf`?**建议**:统一 Bash `printf`(零依赖、不耦合 context-resilience);`write_runconfig` 兼带为优化。
- **Q4(sast/sra/srr 是否同步加正向受信子表)**:本变更 init-only;三域后续是否对称收紧?**建议**:待三域
  报告根污染再做(本变更不留缺口,因三域产物路径已收窄)。
