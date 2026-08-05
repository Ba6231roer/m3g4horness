## Context

`/mgh-init` fan-out 路径纪律(R5.3b)已把 `checkpoint_path`/`rule_path`/`input_path` 钉成「`list_*` 枚举脚本产绝对路径 → 编排器逐字透传 → subagent 恰好写该绝对路径」(承 `harden-mgh-init-fanout-output-paths`,治「输出漂到盘符根」)。但大文件切片输出 `chunk_sources.py --out` 是**唯一漏网**的 fan-out 邻接路径:契约只说「call `chunk_sources.py` and read the slice」(`core/prompts/stages/init-scout.md:26`、`init-induct.md:18`),未规定写哪。

实测失败形状(opencode):scout subagent 自行发明 `--out`,其进程 cwd = `C:\Users\<u>\AppData\Local\Temp\opencode\` → 切片落 `…\Temp\opencode\scout-193-slice` → 回读触发越权 `Read` 提示。同一日志还显示 subagent 命中**父层 install** 的旧 `chunk_sources.py`(stdout `"node"` 而非当前版 `"nodes"`),因工具路径以相对 `.opencode/mgh-core/scripts/…` 引用,双层 install 下解析歧义。

约束:R2(零运行时依赖)、R5.3a(脚本 cwd 无关)、R5.5①(recipe 非 prohibition,硬边界才 NEVER)、R5.7(opencode 插件进程不继承 mid-session bash env → 路径经磁盘/stdout 传递,不经 env)、R5.10(分发纯净)。`chunk_sources.py` 当前 `--out` 默认 `shards.json`(相对 cwd)。

## Goals / Non-Goals

**Goals:**
- 切片输出钉到受信子树 `<target>/.mgh-init/slices/<tier>/<unit>/`,subagent 在树内写 + 树内回读(消除越权 `Read` 提示 + 落 hook 受信子树自动放行)。
- 工具脚本路径钉到**当前 install**(经 `list_steps.py` 的 `script_abs`),消除双层 install 下命中父层旧副本。
- 一套统一机制覆盖 scout(`needs_slice[]` 已知)与 T1(大证据文件运行时才发现)。
- 双端对等(claude/opencode),零新增依赖,`chunk_sources.py` cwd 无关性不破。

**Non-Goals:**
- 不改 `chunk_sources.py`(保持 cwd 无关 + 人类 ad-hoc 可用)。
- 不治 mgh-sast 的同形缺口(s4/deepdive)——留后续 adoption。
- 不做切片目录的 per-tier 清理脚本(`.mgh-init/` 已 gitignore + 整 run 清理,slices 随之而去;R3 简练)。
- 不改 `--target` 与 install-dir 的语义关系(仍允许 install 在 A、分析 B)。

## Decisions

### D1 — 切片输出由 `list_*` stdout 新增 `slice_dir` 钉死(非改脚本默认)

`list_scout_batches.py` / `list_clusters.py` 在每个 `pending[]` 项新增 `slice_dir`(绝对、`Path.resolve()`、落 `<init-dir>/slices/<tier>/<safe(unit_id)>/`)。编排器逐字透传;subagent 写 `chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json` 并回读该确切路径。

| 选择 | 理由 |
|---|---|
| 契约层钉路径(`list_*` 产 `slice_dir`) | 与 `checkpoint_path` 钉法同构(同由 `list_*` 产、编排器透传),单一范式;additive 字段不破既有 schema |
| 否决:改 `chunk_sources.py --out` 默认/校验 | 脚本须 cwd 无关(R5.3a)、人类 ad-hoc 可用(`list_steps` 示例 `--out ./.mgh-init/_slice.json`);让脚本假设项目树破此特性 |

### D2 — `slice_dir` + 确定性 stem 规则(非 per-file 全预算 `slice_path`)

统一用 `slice_dir`(每单元一个)+ subagent 命名 `<safe-stem>.slice.json`(`_safe_name`: `/ \ :`→`_`,复用既有)。scout 的 `needs_slice[]` 已知可 per-file 预算,但 T1 的大证据文件是 subagent 运行时才发现(`init-induct.md:18`),per-file 预算无法覆盖 T1 而不改其流。

| 选择 | 理由 |
|---|---|
| `slice_dir` + stem 规则(scout + T1 同形) | T1 运行时发现大文件 → 无法 per-file 预算;统一机制避免 scout/T1 不对称 |
| 否决:scout 走 per-file `slice_path`、T1 走 `slice_dir` | 两套机制增加提示词/测试面;「拼装」此处有界(dir=逐字绝对字段 + stem=纯文件名),不触发 R5.3b「`<target>/<id>` 拼装漂移」(原失败是 part 可空/错致盘符根漂移;此处 dir 非空绝对) |

> 边界:`<safe-stem>` 取源文件 stem(去扩展名),collision 罕见(同 unit 内同 stem 不同扩展极少);若发生,subagent 后写覆盖前写(切片为一次性读后即弃,可接受)。披露于 risks。

### D3 — 工具路径经 `list_steps.py` `script_abs` 钉到当前 install

`list_steps.py` 已从 `__file__` 派生 `script_abs`(`core/scripts/list_steps.py:178` `scripts_dir = Path(__file__).resolve().parent`)= **当前运行 install** 的脚本目录。编排器 step 0 调之取绝对工具基,把绝对 `chunk_sources` 路径透传进 scout/induct subagent task;prompt SHALL 用该绝对路径 verbatim。

| 选择 | 理由 |
|---|---|
| `list_steps.py` `script_abs`(`__file__` 派生) | 编排器从正确 install 加载 → `__file__` 指当前项目副本 → 广播绝对路径给 subagent,消除 subagent 的 `.opencode/` 上溯歧义;且经 stdout 传递,绕开 opencode「插件进程不继承 mid-session env」边界(R5.7) |
| 否决:`<target>/.opencode/mgh-core/scripts` 派生 | 假设 install-dir == target(可 install 在 A 分析 B) |
| 否决:env `MGH_TOOL_BASE` | opencode 插件进程不继承 mid-session bash env(同 R5.7 哨兵动机);stdout→task 字符串同 Bash 调用内读,无该边界 |

### D4 — `chunk_sources.py` 不改(cwd 无关性保留)

切片「写哪」由契约钉(D1),脚本保持「slice 文件、写 `--out`」的 cwd 无关契约。符合 R5.5①:recipe(「写 `--out <slice_dir>/<stem>.slice.json`」)在 prompt,非把 prohibition 打进脚本。

### D5 — 切片 Write 落既有受信子树,无需改 hook

`block-adhoc-scripts` 正向允许 `<target>/.mgh-init/**` 的 `Write`/`Edit`;`slices/<tier>/<unit>/` 在其内 → 切片 Write 自动放行,且切片 JSON 非脚本扩展名 → 不触脚本写入拦截。D1 把「树外 Write」(guard 主机上也只事后拦、非 guard 主机上直接弹越权提示)转为「树内 Write」(guard 放行 + 无提示 + 有界)。`runtime-hook-enforcement` 能力**无改**。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| `slices/` 在 `.mgh-init/` 内累积 | `.mgh-init/` 已 gitignore + 整 run 清理;slices 随之而去。每单元 ≤ 数个切片(单元内大文件数有界)。无需清理脚本(R3)。若某单元大文件多,记 `boundaries[]` |
| subagent 仍发明路径违 recipe | recipe 是正引导;硬边界 `NEVER`(相对/Temp/树外 `--out`)兜底;hook 子树守卫是确定性 backstop(guard 主机上树外 `.mgh-init` 邻接写被拦)。belt-and-suspenders |
| `list_steps.py` 自身首调命中错副本(bootstrap) | 编排器首调用相对 `.opencode/mgh-core/scripts/list_steps.py`,解析于编排器 Bash cwd(`/mgh-init` 被调项目,命令壳加载处)。若用户从歧义 cwd 调 `/mgh-init`,是 launch-cwd 问题,本修不涉;披露:从目标项目根调 `/mgh-init`(文档化调用)。下游经 `script_abs` 全钉死 |
| T1 大文件未预算致 stem collision | 见 D2 边界;切片一次性读后弃,后写覆盖可接受 |
| opencode 相对 `.opencode/` 上溯仍可能影响**编排器自身**的其它相对调用 | D3 仅钉 subagent 用的 `chunk_sources`;编排器其它脚本调用仍相对。本变更不扩到全壳相对→绝对重写(超 scope);若再现,另起 `harden-mgh-init-absolute-tool-base` |

## Migration Plan

- additive:`pending[]` 增 `slice_dir`;旧消费者忽略未知字段不受影响。
- 无 on-disk schema 迁移(slices 为 `.mgh-init/` 内 ephemeral)。
- 回退:删 `slice_dir` 字段 + 还原 prompt 即退回旧行为(subagent 又得自发明 `--out`——即回退到本变更前的不安全态,非静默)。
- 版本:受影响 `.md`/脚本 bump(承 R5.8),`install.sh` 自检 fail-soft + CI 必过(承 R5.8)。
- apply 顺序:`list_*` 加字段 → 契约 md → prompt(双端 agent 定义)→ 命令壳 recipe → 测试。

## Open Questions

- 切片目录 per-tier 完成即清,还是留整 run 清?倾向**留整 run**(最简,`.mgh-init/` 已 ephemeral)。apply 时定。
- sast adoption 是否同步立 stub?倾向**本变更 apply 后**另立 `harden-mgh-sast-slice-path-pinning`(承 split-changes 惯例),非阻塞。
- 是否在 `request-context-budget` 加一条跨命令「所有 subagent-bound 路径绝对+树内+逐字」总纲 requirement(而非仅 control-discovery)?倾向**加**(slice_path 即 fan-out 输出路径,归 R5.3b 总纲),sra/srr 无切片则空真满足。
