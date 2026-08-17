## Why

`harden-mgh-read-confinement`(2026-08-13 归档)后,scout 阶段 subagent 仍出现三类真实中断(**双宿主均发生**,claude 与 opencode):①
`Read D:\parent1\parent2\curr_proj\aa\bb\cc\..\..\..\..\..\..\xxxx`(`..` 链回溯到 D 盘根)触发宿主
**D 盘根权限询问**、任务中断;② S3 scout subagent 任务输入里 `checkpoint_path` 被编排器(弱模型)
拼成 `D:\.mgh-init\checkpoints\…`(盘符根漂移),实际应为 `D:\parent1\parent2\curr_proj\.mgh-init\…`;
③ 目录名幻觉 `Read D:\acme\wing\curr_proj\…`——实际目录是 `D:\acme_wing\curr_proj`(下划线目录名被概率性
误生成为路径分隔符,弱模型 150K 上下文仅消耗 4% 时即发生,证明这不是注意力稀释,而是
**弱模型路径概率生成**的固有失败形态)。

判定逻辑本身**已实证无问题**(`Path.resolve()` 折叠 `..` 链后 `is_relative_to(target)` = False)。
真正的根因是一个统一的问题类——**守卫与运行上下文的「连接」在 subagent 上下文里断裂**,断在三层:

| 层 | 缺口 | claude 实证 | opencode 实证 |
| --- | --- | --- | --- |
| **咨询(consultation)**:宿主是否把该工具事件交给守卫判 | G1:claude PreToolUse matcher 只含 `Bash\|Write\|Edit`(`tools/install_hook.py:29`)——`Read`/`Glob`/`Grep`/`MultiEdit`/`NotebookEdit` **根本不触发守卫**,读侧分支在 claude 端是死代码,越树 Read 直达权限询问 | ✅ 代码实证 | opencode shim `HANDLED` 已含全工具面(前置 change 已修)——**今天无缺口,但无任何机制防再次漂移**(新增守卫分支而忘扩 HANDLED 无 CI 拦) |
| **激活(activation)**:守卫进程是否发现运行域(env/哨兵) | G2:哨兵发现是 **cwd-only**(`<cwd>/<run-root>/.active`)。锚目录不对时哨兵找不到 → 守卫休眠 → 读/写侧全部降级放行 | hook 进程 cwd 随会话/子目录漂移即失联 | opencode 插件进程 env **不继承** mid-session 导出(既有实证),哨兵是唯一可靠激活;而哨兵发现吃 `process.cwd()` = opencode 服务器**启动目录**,启动目录 ≠ target(如在上级目录/别处启动)→ 整 run 休眠——**这是 opencode 上同样发生问题的根因路径** |
| **输入来源(provenance)**:subagent 拿到的路径是否来自确定性 producer | G3:编排器(弱模型)扇出任务输入的路径是概率生成的——盘符根漂移、目录名幻觉。既有防线只有提示词「verbatim」(概率性);读侧无路径来源校验,subagent 拿错 `input_path` 直接 Read 越树 → 中断 | ✅ 用户报告 | ✅ 同形(宿主无关) |

三层各自的**通用控制**(一个机制治一层,非逐 bug 打补丁):

1. **咨询层 → 接线不变量(CI 强制)**:守卫源码的工具分支集 = matcher(claude)与 `HANDLED`(opencode)
   SHALL 覆盖的全集,由回归测断言——**新增守卫分支而忘扩接线面 = CI fail**,该缺口类结构性关闭(双宿主)。
2. **激活层 → 锚点最优 + 向上发现**:哨兵发现从「cwd-only 单点」扩为「最优锚点起有界向上 walk」
   (claude 锚 = hook payload `cwd`(缺省进程 cwd);opencode 锚 = 进程 cwd)——锚在 target 子树内**任意深度**
   都能命中;锚在树外(opencode 从别处启动)是**显式记录的残余边界**(降级放行,不误激活),契约 md 给出
   「在 target 根启动 opencode」的运行要求。
3. **来源层 → producer 物化锚 + reader 统一拒识 recipe**:所有 `--materialize` 产出者在 input.json 顶层
   写绝对 `repo` 锚(泛化到 scout/T1/ut-init,非只 scout);所有 reader stage 提示词携带**同款**「锚定 +
   毒输入拒识」recipe(路径字段解析后不在锚树内 → 回 `failed` ack,不 Read 不 Write);编排器派发段携带
   「逐字节复制 stdout `pending[]` 路径字段」recipe。绝对路径仍是 fan-out 契约正确形态,**不**硬拦盘符路径。

## What Changes

- **咨询层**:`tools/install_hook.py` `_DEFAULT_MATCHER` 扩为
  `Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Glob|Grep`;已装条目幂等演进(matcher 为旧默认子集 → 原地更新,
  用户自定义不动);新增**接线覆盖回归测**(守卫分支集 ⊆ matcher ∧ ⊆ shim `HANDLED` 映射,CI 强制,双宿主)。
- **激活层**:守卫 `_resolve_domain` 改「最优锚点(payload `cwd` ?? 进程 cwd)起向上 walk ≤16 级/盘根」;
  claude 侧 hook stdin 的 `cwd` 字段优先为锚;env-first 激活语义不变;残余边界(锚在树外)写进契约。
- **来源层**:`list_scout_batches.py` 等全部 `--materialize` producer 的 input.json 顶层统一携带绝对 `repo`;
  `init-scout.md`(及同形 reader)加锚定 + 毒输入拒识段;`init-stage/scout.md` 派发段加逐字节复制 recipe。
- **回归**:守卫单测(向上 walk 各锚形态、`..` 链/幻觉前缀拦截)、接线覆盖测、matcher 演进测、
  parity 测(双端 `.py` byte-identical;`.ts` shim 逻辑不动)、契约 md 同步、真机 opencode 冒烟
  (hook 阻断 vs 宿主权限询问的先后顺序实证)。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `runtime-hook-enforcement`:① activation requirement——哨兵发现从 cwd-only 扩为「最优锚点起向上 walk」;
  ② read-side requirement——补 `..` 链折叠、幻觉前缀、opencode subagent 场景;③ 新增「守卫工具面接线覆盖」
  requirement(matcher/HANDLED ⊇ 守卫分支集,CI 强制);④ 新增「reader 锚定 + 毒输入拒识 + producer 物化
  `repo` 锚」requirement(来源层,泛化到全部 fan-out reader)。

## Impact

- **代码**:`releases/claude-code/hooks/block_adhoc_scripts.py` + `releases/opencode/hooks/`(byte-identical
  同步)、`tools/install_hook.py`、`core/prompts/stages/init-scout.md`(及同形 reader)、
  `core/prompts/fragments/init-stage/scout.md`、`core/scripts/list_scout_batches.py`(核对/补 `repo`;
  `list_clusters.py`/`list_test_groups.py` 同步统一)、`tests/test_block_adhoc_scripts.py`、
  `tests/test_opencode_hook_parity.py`(扩接线覆盖断言)、`tests/test_install_hook.py`(matcher 演进)、
  `core/contracts/hooks/runtime-enforcement.md`、AGENTS.md R5.7 段 B 措辞、版本号 bump。
- **既有安装项目**:重跑 `install.sh` 后 matcher 演进(幂等);opencode 侧无 install 面改动(shim 不动)。
- **风险**:matcher 扩面后 claude 端读侧守卫首次真正生效——越树读从「权限询问中断」变「fail-loud recipe」,
  **预期收紧**;向上 walk 残余边界(锚在树外)显式记录为运行要求,不静默;opencode hook 与宿主权限系统的
  先后顺序无法离线实证,列真机冒烟任务。
- **非目标**:不治弱模型路径幻觉本身(只治「幻觉路径执行前拦下 + 失败可见」);不改 `Path.resolve()` 语义
  (已实证正确);不做「禁一切盘符绝对路径」硬拦(绝对路径是 fan-out 契约正确形态)。
