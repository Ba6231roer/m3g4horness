## Context

mgh-init 提示词面 = 命令壳(92 行)+ `orchestrator-discipline`(54 行)+ 12 个 per-step fragment + 8 个 stage 提示词。
历次 change(`harden-mgh-init-orchestration-discipline`、`harden-mgh-init-shell-budget`、
`split-mgh-init-stage-flow-per-step`、`complete-r5-4-per-step-discipline`、`harden-mgh-init-scout-path-binding`
等)已把绝大部分编排纪律下沉到:守卫 `block_adhoc_scripts.py`(9 条 Bash/工具面规则)、`resume_state.py`
(`step`/`next_action`/`discipline_reminders[]`/`stage_flow_files[]`)、`list_*`(绝对路径 + 物化)、
`--check` validators、`write_runconfig.py`(原子 run_config)。

本 change 只补两条仍为纯提示词的承重纪律(见 proposal §Why),动机不赘述。

## Goals / Non-Goals

**Goals:**
- 哨兵写入/存在性校验/`--resume` re-arm 全部确定性化(脚本副作用 + `--check` 校验),消除「弱模型漏写哨兵 → 守卫休眠」。
- 叶源码 Read 从提示词 NEVER 变 hook 确定性拦截,删对应提示词要求。
- 结论先行地记录「哪些能搬、哪些不能搬、哪些不推荐搬」的审计结论(供后续 mgh-* 复用)。

**Non-Goals:**
- 不做「gate 执行顺序 → hook 状态机」强制(见 Decisions D4)。
- 不删 `export MGH_INIT_ACTIVE=1` / `export MGH_TARGET=<repo>`(见 Decisions D5)。
- 不把哨兵确定性副作用推广到其它 4 命令(ut-init/sast/sra/srr)本次落地——本 change 只做 mgh-init,其它命令
  的 runconfig 写入器(`write_ut_runconfig`/`prepare_augment`/`ingest_requirements`)留作 follow-up(承
  [[split-cross-cutting-openspec-changes]] 的 foundation + per-command 拆分原则)。
- 不治「弱模型不执行 `--check` 闸门」这一通用软依赖(已由 `discipline_reminders[]` 磁盘化兜底,非本 change 范围)。

## Decisions

### D1 — 哨兵写入载体:`write_runconfig.py` 副作用(而非新脚本 / 新 flag)

`write_runconfig.py` 已原子写 `run_config.json`、已算 Windows 原生 `target_abs`、已接收 `--out`/`--rules-dir`
(可派生 `out_roots[]`)。让它 co-write `<init-dir>/.active` 是**零新接口**的确定性副作用——脚本一跑哨兵必在,不依赖
编排器读懂 `printf` 配方。

- **备选 A(新 `--activate` flag)**:需扩 CLI 契约面(R5.1),且引入「写 run_config vs 写哨兵」两个动作的调用顺序软依赖——否。
- **备选 B(独立 `write_sentinel.py`)**:多一个 leaf 脚本、多一次编排器 Bash 调用、多一处 R5.3(a) 自包含样板——否。
- **幂等性**:`write_runconfig` 本就 create-if-not-exists + overwrite;哨兵 co-write 同幂等(重写覆盖无害)。新鲜 run 与
  `--resume` 重跑 `write_runconfig` 都自动重写哨兵。

`out_roots[]` 派生:默认产物根(`<target>/.mgh-init`、`<target>/.claude/rules`、`<target>/docs/security-controls`、
`<target>/AGENTS.md`)已在 `_ALLOWLIST_SUBTREES` 内置、不列;仅当 `--out`/`--rules-dir` 非默认时把解析后的绝对根列进
`out_roots[]`(与现 bootstrap `printf` 语义一致)。

### D2 — 哨兵存在性校验 + re-arm 载体:`resume_state.py`

`resume_state.py` 已读 `run_config.json`、已判 `step`、已有 `--check`(R5.9 边界校验)。哨兵存在性校验是 `--check`
的**增补条件**(非新字段):`run_config` 存在 ∧ step ≠ `done` ∧ `<init-dir>/.active` 缺失 → violation(退出码 2)+ recipe。
re-arm 是 resume 路径的确定性动作:`resume_state` 从 `run_config.target`(+ 可选 `rules_dir`/`out` 派生 out_roots)重写
`<init-dir>/.active`——`--resume` 或压缩后第一步即可靠激活,不再靠「重跑 bootstrap 提示词里的 printf」。

- **为何不并入 `--activate` 新 flag**:re-arm 依赖 `run_config.target`(盘上已持久化),`resume_state` 天然拥有它;新 flag
  会让「写哨兵」出现两个入口(新 run 走 write_runconfig、resume 走 resume_state),语义漂移风险。统一约定:**新 run 哨兵
  由 `write_runconfig` 写;resume 哨兵由 `resume_state` 的 re-arm 写;二者都从 `run_config.target` 派生,单一真相**。
- 边界:`done` 步哨兵缺失非违例(流水线已收尾,守卫本应休眠)。

### D3 — 叶源码 Read 拦截的路径判别:`mgh-core/scripts` 段 + 脚本扩展名

守卫是双端 byte-identical 孪生,不能硬编码宿主前缀。判别规则 = **resolve 后 `file_path` 落在含 `mgh-core/scripts`
路径段的目录下 ∧ 扩展名 ∈ 脚本集**。对 claude(`.claude/mgh-core/scripts/`)与 opencode(`.opencode/mgh-core/scripts/`)
都命中;对目标项目自身 `.py`、`mgh-core/` 下的 `.md`(prompts)、非脚本产物均不误伤。

- **为何不按「所有 `.py` in-tree 都拦」**:会误伤「瞄一眼目标项目源码」的合法读(如 T1 子代理读 evidence 锚点旁的
  `.py`)。`mgh-core/scripts` 段是叶脚本的安装判别锚。
- **为何读侧也拦(不只写侧)**:写侧已拦「改脚本」;读侧拦的是「把叶源码拖进上下文 debug」的 token 膨胀 + 内部推理诱惑
  (150K 低窗口下 3–10K/脚本是实质稀释)。与提示词 NEVER 语义完全一致,是它的确定性化。
- **接线覆盖**:新读分支是守卫 `main()` 里的 `Read` 分支内新增判定,不新增工具名——现有接线覆盖测(matcher/HANDLED)
  无需扩工具集;但 parity 测须断言 `.py` 双端 byte-identical。

### D4 — gate 执行顺序 → hook 状态机:**不推荐,分析后否决**

用户问题「还有哪些能搬进 hook」的候选之一是:把「进 T2 前 MUST 跑 `validate_t1_records --check`」这类 gate 顺序
做成 PreToolUse hook——拦截「spawn `init-synthesis` subagent 而 t1 gate marker 缺失」。分析结论:**否决**。

- 需 hook 解析 `Agent` 工具调用的 `subagent_type` → 映射到 stage → 查该 stage 的 gate marker(盘上哪个 `.done`/校验产物),
  把守卫从**无状态工具面判定**变成**流水线状态机**——与现有守卫的 stateless/stateless-dispatch 架构冲突。
- 脆弱:subagent 名、gate marker 命名、stage 顺序三者任一漂移即误拦/漏拦;维护成本高于收益。
- `discipline_reminders[].gates[]` 已把 gate 形状磁盘化(压缩后可恢复),是**更便宜、更抗漂移**的同一目标实现——
  它治「压缩后忘记跑 gate」,hook 状态机治「当场不跑 gate」,后者收益边际、成本陡增。
- 裁决:gate 顺序留作提示词 + `discipline_reminders[]` + `--check` 闸门,不做 hook 状态机。

### D5 — `MGH_TARGET` / `MGH_INIT_ACTIVE` env 导出:保留,不删

- `export MGH_INIT_ACTIVE=1`:claude 端在哨兵写出**之前**的即时激活源(step 0 首动作就 arm 守卫);opencode 端
  插件进程不继承、本就无效(靠哨兵)。哨兵确定性化后 env 是 belt-and-suspenders,**保留**(成本一行,收益即时 arm)。
- `export MGH_TARGET=<repo>`:哨兵 `target`(= write_runconfig 的 `target_abs`,与 `controls_candidates.json::repo`
  文档上一致)已使 `_resolve_target` 可回退到 `sentinel.target`。但 `repo` 是 discover 的权威根、`--target` 是用户入参,
  二者在 `--scope`/子目录入参等边角下**可能不同**;删掉 env 导出会弱化读/写侧子树判定精度。**保留**为权威根兜底,
  不在本 change 里做「冗余裁剪」。

### D6 — 审计结论总表(「哪些能搬、哪些不能」,供复用)

| 提示词纪律 | 现强制 | 可搬? | 本 change |
|---|---|---|---|
| `py -c` 内省 / 脚本扩展名写 / 越树写读 / 聚合整读 / 文件关联 / Bash 文件搜索/写删/重定向逃逸 / 工具面写(MultiEdit/NotebookEdit/apply_patch)/ temp-I/O | hook | 已搬 | — |
| fan-out 路径逐字透传(绝对) | 脚本 `list_*` stdout | 已搬 | — |
| 步骤派生 / next_action / per-step 纪律 / stage 流文件 | 脚本 `resume_state`/`discipline_core` | 已搬 | — |
| `--check` 边界校验 | 脚本 validator | 已搬 | — |
| run_config 原子写 | 脚本 `write_runconfig` | 已搬 | — |
| **`.active` 哨兵写入** | **提示词 `printf`** | **脚本副作用** | ✅ D1 |
| **`.active` 哨兵存在性校验** | **无** | **脚本 `--check`** | ✅ D2 |
| **`.active` 哨兵 resume re-arm** | **提示词** | **脚本 re-arm** | ✅ D2 |
| **「NEVER Read 叶子 .py 源码」** | **提示词 NEVER** | **hook 读侧** | ✅ D3 |
| `MGH_INIT_ACTIVE` / `MGH_TARGET` env 导出 | 提示词 | 部分冗余、保留 | ❌ D5 |
| gate 执行顺序(进下一步前 MUST `--check`) | 提示词 + `discipline_reminders` | 不推荐(hook 状态机) | ❌ D4 |
| subagent 派发(failed ack / input_path verbatim) | 提示词(+ hook 已拦路径面) | LLM 判断 | — |
| fan-out run-to-completion / Always disclose / `--help` 零 token | 提示词 | LLM 判断 / 输出内容 | — |

## Risks / Trade-offs

- **[哨兵存在性校验误拦「手工删哨兵的调试 run」]** → recipe 给 re-arm 出口(`resume_state` re-arm / 重跑 `write_runconfig`),
  且仅当 `run_config` 存在 ∧ 未 `done` 才 fail,日常开发态(无 run_config)零噪声。
- **[叶源码读拦截过度收紧]** → 判别锚 `mgh-core/scripts` 段 + 扩展名双条件,目标项目自身 `.py` 与 `.md` 不误伤;
  拦截语义与既有提示词 NEVER 完全一致,是预期收紧。
- **[opencode 上 hook 与宿主权限系统先后顺序]** → 与既有读/写侧同型,列真机冒烟(不改变 `Path.resolve()` 语义)。
- **[`out_roots[]` 派生与 `_ALLOWLIST_SUBTREES` 漂移]** → `write_runconfig` 只列非默认根;受信子树权威仍在守卫
  `_ALLOWLIST_SUBTREES` + 契约 md,`out_roots[]` 仅扩展,不改内置子树。
- **[写侧/读侧 parity 与接线覆盖回归]** → 叶源码读分支不新增工具名(接线覆盖集不变),但 parity 测须断言双端 `.py`
  byte-identical + 新分支单测覆盖。

## Migration Plan

1. 改 `write_runconfig.py`(co-write 哨兵)、`resume_state.py`(`--check` 哨兵校验 + re-arm)、守卫 `.py`(叶源码读分支,
   双端同步)、`bootstrap.md`(删 `printf` 配方,改「write_runconfig 已自动写」)、`orchestrator-discipline`/`discipline_core`
   (删叶源码 NEVER)、契约 md、版本号 bump。
2. 回归:单测(哨兵副作用/`--check` 校验/叶源码读拦截/parity/接线覆盖)全绿。
3. 既有安装项目:重跑 `install.sh` 镜像新脚本/守卫;`write_runconfig` 哨兵副作用幂等,旧 run 无哨兵 → 下次 step 0 自愈。
4. Rollback:守卫是 byte-identical 增量分支,回滚 = revert 单文件;`write_runconfig` 哨兵副作用移除后回退到 `printf`
   (bootstrap 配方已在 git 历史)。

## Open Questions

(无——哨兵 re-arm 的精确触发点(fresh vs resume)已在 D2 定死,不阻塞 tasks。)
