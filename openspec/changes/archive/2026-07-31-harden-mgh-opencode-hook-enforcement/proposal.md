## Why

`/mgh-init` 真机跑里出现一连串**黑盒纪律失守**——agent 改核心叶子脚本(`list_clusters.py`/`merge_scout.py`)、
在项目根写 `process_induct.ps1`/`process_clusters.ps1`/`_*.py` 微脚本、往项目根 dump `temp_clusters1~n.json`、
读写 `%LocalAppData%\Temp` 等非项目目录——而 R5.7 的运行时 hook 本该**确定性兜底**这一切。审计共享守卫
`releases/claude-code/hooks/block_adhoc_scripts.py` 定位到**四条让守卫形同虚设的缝隙**:

1. **激活靠 mid-session env(opencode 全程休眠)**:守卫只在 `MGH_*_ACTIVE=1` 经 env 激活,而 opencode
   `.ts` 插件进程**不继承 mid-session bash 导出的 env**(已被记录为「可靠性边界、未激活则 fail-soft」)→
   opencode 上守卫**整 run 休眠**,于是 `py -c`/一次性微脚本内省、读写 `%LocalAppData%\Temp` 等非项目目录、
   模型猜错脚本路径(`scripts/` vs `.opencode/mgh-core/scripts/`)均畅通无阻;`MGH_TARGET` 同根因也拿不到 →
   子树外/`%TEMP%` 守卫一并空转。
2. **白名单把「agent 改叶脚本」误判成「install 写叶脚本」放行**:`_is_blocked_py_write` 的
   `"core/scripts" in path` 段匹配,让运行域内编辑 `mgh-core/scripts/*.py`(实测:`list_clusters.py`/
   `merge_scout.py`)畅通无阻。
3. **只拦 `.py`,不拦 `.ps1`/`.sh`/`.bat`**:`process_induct.ps1`/`process_clusters.ps1` 直接漏过。
4. **子树守卫只挡「树外」,不挡「树内根污染」**:`_is_out_of_tree` 放行任何 `MGH_TARGET` 内写入,含项目根
   `temp_clusters1~n.json`。

这四条**都不是上下文压缩问题**,只是恰好发生在一次压力大的跑里;姊妹变更 `harden-mgh-init-context-resilience`
只治「上下文压力下丢步骤序列」(跳过 `init-scout-merge` → 读 `merge_scout.py` 源码反推格式 → 造畸形
`scout_candidates.json`)。本变更治上述四条守卫缝隙,是其余一切纪律的地基——**未修则一切提示词纪律皆为
建议性**(agent 曾因此能直接改核心脚本)。

> **Scope boundary(本变更 ≠ 该问题集的完整修复)**:本变更是某次 `/mgh-init` 真机问题分析的 **hook 守卫
> 子集**(治:agent 改核心脚本 / `py -c` 微脚本内省 / 读写 `%TEMP%` / 项目根 dump 临时脚本与聚合)。同次
> 分析的**非 hook 剩余项各需独立 change,不在本变更内**(详见 `new_issue26073101.txt`):
> - 「上下文压力下丢步骤序列」→ `harden-mgh-init-context-resilience`(已立);
> - 「压力下停下来征求拆分/跳过」(**提示词行为,非 hook**,本变更不收)→ 归 context-resilience 编排行为段或另立;
> - `merge_scout.py::_normalize` 的 `KeyError "file"` 防御 → `fix-mgh-init-merge-scout-missing-file`;
> - NTFS `::` 致 unit 输入文件名 `Errno 22` → `fix-mgh-init-ntfs-unit-filename`;
> - 探索性任务允许个别 fan-out 单元失败 → `improve-mgh-init-partial-fanout-tolerance`;
> - 模型猜错脚本路径 + 声明式 step manifest(衍生想法)→ `improve-mgh-init-deterministic-step-manifest`。

## What Changes

把守卫从「靠 mid-session env 激活 + 宽松白名单」升级为「**磁盘哨兵激活 + 运行域脚本只读 + 写入限定
受信子树**」的确定性闭环:

- **磁盘哨兵激活(治缝隙 1)**:编排器 step 0 经 `Bash` 写 `<target>/.mgh-<domain>/.active` 哨兵
  (`{domain,target_abs}`);守卫激活 = `MGH_*_ACTIVE=1` env **或** 哨兵存在。哨兵经磁盘可见,**绕开**
  opencode 插件不继承 mid-session env 的可靠性边界(关掉「整 run 休眠 → 微脚本内省 / 读写 `%TEMP%` / 猜错
  脚本路径均失拦」);哨兵同时携带 `target_abs`,使 `MGH_TARGET` 在 opencode 上 step 0 即就绪(不必等 discover
  后)。run 完成 / 干净停止时编排器移除哨兵。**双端对等**(claude env 仍工作,哨兵为兜底;opencode 靠哨兵)。
- **运行域脚本只读(治缝隙 2+3)**:守卫激活时**拦截一切脚本扩展名写入**(`.py`/`.ps1`/`.sh`/`.bash`/`.bat`/`.cmd`/
  `.ts`/`.js` 等),**取消** `core/scripts`/`mgh-core/scripts` 与 `tests`/`tools`/`hooks` 白名单豁免——这些豁免
  只在守卫未激活(install/dev 态)有意义;运行域内**无任何合法脚本写入**(产物全是 JSON/`.md`)。叶脚本对
  agent 为 **read-only**(关掉「agent 改 `list_clusters.py`/`merge_scout.py`」)。
- **写入限定受信子树(治缝隙 4,init 域)**:把 init 域「树外拦截」升级为**正向受信子树允许清单**——
  Write/Edit 的 resolved 目标 MUST 落在 `<target>/.mgh-init/**`、`<target>/.claude/rules/**`、
  `<target>/docs/security-controls/**`、`<target>/AGENTS.md` 之一;**树外**(盘符根/`%TEMP%`)**与**树内非受信
  位置(项目根 `temp_clusters*.json`、`process_*.ps1`)均 fail-loud(退出码 2)+ recipe。sast/sra/srr 保留既有
  「树外拦截」(未报告根污染,后续可对称收紧)。
- **AGENTS.md R5.7 段 B 更新**:opencode「env 不继承 → fail-soft」可靠性边界**由哨兵关闭**;守卫双端可靠
  激活。R5.2 白名单措辞同步(运行域脚本只读)。
- **衍生想法(声明式 step manifest)**:本变更用 hook 的**确定性 backbone** 治「读写非项目目录 / 错路径」;
  manifest 是**正向引导互补**,已被 `resume_state.py`/`run_config.json` + 既有 fan-out 绝对路径契约 + stage→组件表
  大幅覆盖,残量(统一声明式表)与 R5.6 token 预算冲突 → 另立 `improve-mgh-init-deterministic-step-manifest`
  (见 design D6,非本变更范围)。

## Capabilities

### New Capabilities
- `runtime-hook-enforcement`:跨四命令(`/mgh-init`|`/mgh-sast`|`/mgh-sra`|`/mgh-srr`)共享的运行时纪律守卫
  契约——激活(env-or-哨兵)、运行域脚本只读、脚本扩展名集、写入受信子树限定。**单一真相源**,取代当前
  分散在各命令 spec、措辞漂移的重复 hook 要求。

### Modified Capabilities
- `control-discovery`:init 域 step 0 增写哨兵、完成态移除;hook 要求改为引用 `runtime-hook-enforcement`
  共享契约;init 域新增「写入受信子树允许清单」要求。
- `sast-orchestration-discipline`:sast 域 hook 要求的激活/白名单条款改为引用 `runtime-hook-enforcement`;
  域细节(env var、aggregates、树外拦截)保留。
- `freeform-security-review`:srr 域 hook 要求同步引用共享契约(激活 + 脚本只读)。

> **sra(`security-augmentation`)不改**:该 spec 无独立 hook 要求,仅 L128 一句「漂出子树触发 hook 拦截」
> 仍准确;共享 `runtime-hook-enforcement` 自动权威,sra 无需 delta。

## Impact

- **改守卫**:`releases/claude-code/hooks/block_adhoc_scripts.py`(激活 = env-or-哨兵 + 脚本扩展名集 +
  取消白名单豁免 + init 受信子树允许清单 + 读哨兵取 `target_abs`)。`releases/opencode/plugins/block_adhoc_scripts.ts`
  **无判定逻辑变更**(仍是胶水:事件归一化 + 管道 + 据退出码 2 阻断;哨兵/env/白名单判定全在 `.py`,双端
  parity 不破)。
- **改命令壳**:两份 `mgh-init.md`(step 0 写哨兵 + 完成移除);`mgh-sast.md`/`mgh-sra.md`/`mgh-srr.md`
  step 0 同步写各域哨兵、完成移除。
- **改 AGENTS.md**:R5.7 段 B(opencode 可靠性边界由哨兵关闭、守卫双端可靠激活)+ R5.2(运行域脚本只读)。
- **改契约**:新增 `core/contracts/hooks/runtime-enforcement.md`(哨兵 schema + 受信子树表 + 脚本扩展名集)。
- **改单测**:`tests/test_block_adhoc_scripts.py` 翻 `test_pass_whitelisted_py_write` → 运行域 **BLOCK**;新增
  哨兵激活(env 未设仍激活)、哨兵携 `target_abs` 的树外拦截、`.ps1`/`.sh` 拦截、init 根污染拦截、受信子树
  放行;`tests/test_opencode_hook_parity.py` 扩哨兵路径 parity。
- **依赖**:零新增运行时依赖(R2)。哨兵 = Bash 写一个 JSON 小文件(无新脚本依赖;`write_runconfig.py` 可兼带,
  但本变更**不依赖** `harden-mgh-init-context-resilience` apply)。
- **BREAKING / 风险**:运行域内**所有**脚本扩展名写入现被拦(此前 `mgh-core/scripts/*.py` 放行)——此为**预期
  治本**(运行域无合法脚本写);install/CI 在守卫未激活态运行,不受影响。受信子树允许清单若漏列 init 合法
  写位置会 over-block → 缓解:清单据 `mgh-init.md` Output 节穷举 + 单测覆盖 + design 评估降级开关。
