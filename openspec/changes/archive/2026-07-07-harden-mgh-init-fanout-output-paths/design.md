# Design — harden-mgh-init-fanout-output-paths

> 承 `proposal.md` 四层。本文件给关键决策的**选择 / 理由 / 备选(否决)**,可证伪。R3 简练:
> 不贴长代码,用 `文件:行号` 索引。与 `harden-mgh-init-orchestration-discipline` 同族——那次治
> 「微脚本内省」,本次治「输出路径契约软」(二者互补:前者管 agent *读*什么、后者管 agent *写*到哪)。

## Context

`/mgh-init` 的 fan-out(scout / T1 / T3)每个待跑单元都要由一个隔离 subagent 把 checkpoint 产物
写到 `<target>/.mgh-init/checkpoints/<tier>/<unit>.json` 并 touch `.done`。真机偶发 subagent 把
产物写到**非项目目录**(Windows D 盘根目录的 `xxx.json` / 被误命名 `xxxraw.json`)。

当前确定性事实(本变更覆盖范围的根因证据):

- `init-scout.md:87` Output 段:`Write <target>/.mgh-init/checkpoints/scout/<batch_id>.json`——**占位符
  模板**,且 Input 段(`init-scout.md:21-27`)只列 `batch / repo root / regex_known[]`,**`<target>` 根本
  不是具名输入字段**;subagent 要自己把「repo root」当 `<target>` 再拼路径。
- `init-induct.md:68` Output 段:`Write .mgh-init/checkpoints/t1/<cluster_id>.json`——**裸相对路径**,
  连 `<target>` 前缀都没有,直接对 subagent 的 cwd 求值。
- `init-rulewriter.md:60-64` Output 段:已部分正确(「to the path given by the orchestrator」+ `list_rule_jobs.py`
  吐 `rule_path`),但 `list_rule_jobs.py:75` `--target` 默认 `"."` → `rule_path` 仍**相对**;且无 `done_marker`,
  `.done` 路径仍由 prompt 模板拼。
- 枚举脚本 `list_scout_batches.py:65-71` `_lite()`、`list_clusters.py:66-74` `_lite()` 的 pending 项
  **完全不含路径字段**——只有 `batch_id` / `cluster_id`。grep `checkpoint_path|out_path|done_marker`
  全仓仅命中 `merge_scout.py` / `assemble_rules.py`(它们是产出者,非枚举器)。
- `harden-mgh-init-orchestration-discipline` 已立 R5.3(b)「扇出即脚本枚举」,但**只到「产 pending 清单」,
  没到「产确切输出路径」**。路径仍是双 agent 拼装的软契约。

三条结构性原因(为何路径会漂到盘符根):

1. **路径是「模板」不是「值」**——占位符 / 相对路径要被两个 agent 各拼一次,任一处 cwd 错位即漂移。
2. **枚举脚本不产路径**——唯一能确定性、一次性算出绝对路径的角色没承担这职责,反而把拼装下放给 agent。
3. **subagent 的 cwd 不可假设**——隔离 subagent 上下文的 cwd 由宿主决定(Windows 下可能盘符相对、
   或残留 `cd`),相对路径对其不安全;只有**绝对路径**对任意 cwd 安全。

| fan-out | 当前路径形态 | 枚举脚本路径字段 | 漂移风险 |
|---|---|---|---|
| scout | `<target>/…/<batch_id>.json`(占位符 + `<target>` 非具名输入) | 无 | 🔴 高(实测 D 盘根) |
| T1 | `.mgh-init/…/<cluster_id>.json`(裸相对) | 无 | 🔴 高 |
| T3 | `rule_path`(相对,`--target .` 默认)+ `.done` 模板 | 仅 `rule_path`(相对) | 🟡 中 |

约束:R2 零运行时依赖;R5.1 双壳 flag 逐字镜像且 `--help` 即契约;R5.2 编排器=宿主 agent、禁 `.py`/
禁微脚本/禁 Read 源码;R5.3 叶脚本自包含 + stdout=JSON/stderr=进度 + 退出码 `0/1/2`;R5.5① recipe 取代
prohibition、硬边界才 `NEVER`;R5.6 壳 ≤500 行;R5.7 能 hook 别靠自觉;R5.8 改动 bump + 回归;R5.10 分发
md 纯净(新增路径字段属操作语义,保留;不引入 dev-only 编号)。

## Goals / Non-Goals

**Goals:**
- 每个 fan-out 单元的输出路径成为**单一权威绝对路径值**,由枚举脚本(`list_scout_batches` /
  `list_clusters` / `list_rule_jobs`)产出,编排器逐字透传、subagent 逐字写,**全程零拼装**。
- subagent 提示词把路径当**逐字输入字段**,显式禁止拼路径 / 发明文件名 / 相对路径 / 写盘符根。
- 运行时 hook 拒绝子树外 Write/Edit(defense-in-depth,承 R5.7),把偶发漂移从「静默写错地」变「fail-loud」。
- 全程零新增运行时依赖;双壳镜像;回归测 + CLI lint 通过;产物磁盘格式不变(全 additive)。

**Non-Goals:**
- 不改 fan-out 的并发 / 切批 / 簇化算法;scout→merge→foldin 既有契约不变。
- 不重构既有脚本(只加路径字段);不改既有产物磁盘 schema。
- 不把路径校验做成独立 validator 目录(路径正确性由枚举脚本产出 + hook 兜底,非 `--check` 范畴;
  `--check` 仍管 schema shape)。
- 不引入 tree-sitter / Semgrep / 任何 `pip install`。

## Decisions

### FD1 — 枚举脚本拥有输出路径(单一权威值;扩 R5.3(b))
**选择**:`list_scout_batches.py` / `list_clusters.py` 的 `_lite()` 各增 `checkpoint_path` +
`done_marker`,从**已 `.resolve()` 的 `--checkpoints` dir**(`list_scout_batches.py:98-99`、
`list_clusters.py:101-102` 已算)拼 `batch_id` / `cluster_id`,得**绝对路径**。`list_rule_jobs.py`
`rule_path` 改 `Path(args.target).resolve()`、增 `done_marker`(`_rule_path`/`_done_categories` 已有
拼装逻辑可复用)。绝对路径用 `Path.resolve()`(Windows 下可能 `\\?\` 前缀,Write 仍接受)。
**理由**:R5.3(b) 已立「扇出即脚本枚举」——枚举器是唯一确定性、一次性、对 `--checkpoints` 有全知的角色;
让它顺带产路径,消灭双 agent 拼装。绝对路径对任意 subagent cwd 安全(治结构性原因 ②③)。
**备选(否决)**:在编排器(命令壳)里拼路径——又回到「agent 拼路径」,且双壳各拼一份易不一致。

### FD2 — subagent 提示词钉死路径为逐字字段(治结构性原因 ①)
**选择**:3 个 stage 提示词 `core/prompts/stages/init-{scout,induct,rulewriter}.md` 的 Input 段增
`checkpoint_path`(rulewriter 还有 `rule_path` + `done_marker`)为「编排器逐字给定」;Output 段从模板
改为「Write 恰好 `checkpoint_path` 给定的**绝对路径**」+ 硬边界 `NEVER`:自行拼 / 发明文件名 / 写相对路径 /
写盘符根(R5.5① recipe:「写到这个字段给定的路径」+ 硬边界 `NEVER` 拼路径)。双壳 `agents/init-*.md`
Hard-constraints 段同步(双重防线,承 `harden-mgh-init-orchestration-discipline` FD8 范式)。
**理由**:subagent 实际读的是 stages/*.md(承 FD8 否决「只改壳」的理由);逐字字段 + 硬边界消除「占位符怎么填」
的 doubt 时刻。
**备选(否决)**:只在 prompt 里把模板换成「请写绝对路径」——没给值,subagent 仍要自己拼,等于没治。

### FD3 — 编排流刚性三元组携带逐字路径(治「双 agent 拼装」)
**选择**:两份 `mgh-init.md` 的 fan-out 段(3b scout / 步骤4 T1 / 步骤6 T3)spawn 调用改为
`spawn init-scout({batch, repo_root, regex_known[], checkpoint_path, done_marker})`(T1/T3 同形);三元组表述
`[list_* stdout::pending[].checkpoint_path] → spawn subagent(逐字透传) → [恰好写该绝对路径]`;起步段
`Bash: export MGH_INIT_ACTIVE=1` 旁加 `export MGH_TARGET="$(… 绝对 target …)"` 供 hook 判树。
**理由**:编排器从 `list_*` stdout **复制**路径字段、逐字塞进 subagent task——零拼装(承 R5.2「编排器不挖 JSON
不拼」的延伸:连路径也不拼,只透传)。
**备选(否决)**:编排器用 `<batch_id>` 自己拼 `<target>/.mgh-init/...`—— reintroduce 拼装;且 target 绝对化
逻辑散在壳里。

### FD4 — 运行时防越界 hook(承 R5.7,defense-in-depth)
**选择**:扩既有 `releases/claude-code/hooks/block_adhoc_scripts.py`(已 `MGH_INIT_ACTIVE` 运行域 + `block-adhoc-scripts`
matcher 族),增一条:运行域内 `Write`/`Edit` 的 resolved 目标**不以 `MGH_TARGET`(resolved)为前缀**者 →
退出码 2 + stderr recipe(「路径须取自 `list_*` stdout 的 `checkpoint_path`;你正写到 `<target>` 之外」)。
`MGH_TARGET` 缺失 → 该条放行(不阻断,降级为仅靠 FD1-3)。`--no-enforce-hook` opt-out 沿用;opencode 无
PreToolUse 时 warn + 跳过(fail-soft,承 R5.8)。
**理由**:R5.7「能 hook 就别靠自觉」;FD1-3 是正引导(给对路径),hook 是兜底(挡错路径),二者互补。
子树判定廉价(`Path.resolve()` + `is_relative_to`)、O(1),不触发文件检索。
**备选(否决)**:不做 hook,纯靠 FD1-3——路径已钉死,偶发漂移概率大降但非零(如 subagent 误读字段);
hook 把残余风险从「静默」变「fail-loud」,值这点侵入。

### FD5 — 绝对路径的 Windows `\\?\` 与 cwd 鲁棒(实施注意,非决策分歧)
**选择**:枚举脚本统一 `Path(...).resolve()` 产绝对路径;不 `os.path.normcase`、不强去 `\\?\`(Write 接受);
`MGH_TARGET` 在壳里以 `py -c` 之外的途径取绝对值——复用 `discover_controls.py` 既有的 repo-root resolve
(其 stdout 已含绝对 `repo`),编排器直接读该 stdout 字段作 `MGH_TARGET`,**不另写 `py -c`**(守 R5.2)。
**理由**:避免为「取绝对 target」引入新微脚本(那是 `harden-mgh-init-orchestration-discipline` 刚治掉的违例);
复用既有 stdout 字段。
**备选(否决)**:`py -c "import os;print(os.path.abspath('.'))"`——命中 R5.2 微脚本明线,否决。

## Risks / Trade-offs

- **hook 子树判定的边界误伤** → 缓解:`MGH_TARGET` = discover stdout 的绝对 `repo`(可信);只拦 resolved 目标
  **不**在其下者(高信号:`D:\x.json` 必命中);合法的 `.claude/rules/security-*.md`(T3 claude 直写)在
  `<target>` 子树内 → 放行。`MGH_TARGET` 缺失 → 该条降级放行(不阻断)。双栏单测覆盖(放行子树内、拦子树外)。
- **Windows `\\?\` 路径** → Write 接受;`is_relative_to` 在 3.10 stdlib 可用(注:3.9 才加,本仓 ≥3.10 OK)。
- **opencode 无 PreToolUse** → 沿用既有降级(warn + 跳过),纪律仍由 FD1-3 + 提示词护栏兜底。
- **prompt 改动量** → 3 stage ×(core + claude agent + opencode agent)= 9 处,但每处仅 Input/Output 段微调,
  机械且可证伪(场景测试)。
- **新增 stdout 字段破坏下游** → `merge_scout` / `form_clusters` / `assemble_rules` 不消费 `list_*` 的
  pending 项(它们读 `scout_candidates.json` / `clusters.json` / inventory);pending 项加字段对它们无影响。
  additive,无破坏。

## Migration Plan

- **无 schema/数据迁移**:既有产物磁盘格式不变;`list_*` stdout 仅 additive(新字段),旧消费者忽略即可。
- **hook 扩展幂等**:`install.sh` 注入 matcher 时与既有 `block-adhoc-scripts` 同条目幂等合并;二次 install
  不重复加;`--no-enforce-hook` 完全 opt-out。
- **AGENTS.md R5.3(b) / R5.5① 改动是收紧**(扩枚举脚本职责 + 加路径 recipe),不放松既有约束,无回退风险。
- **版本号**:任一 `.md`/脚本改动 bump(承 R5.8)。
- **回退**:opt-out 可完全回退 hook 层;路径钉死(FD1-3)为提示词/脚本层,回退 = revert 该 commit,无数据风险。

## Open Questions

- **`MGH_TARGET` 取值源**(FD5):优先复用 `discover_controls.py` stdout 的绝对 `repo` 字段;实施时确认该字段
  在所有 `--scope` 模式下都是项目绝对根(而非 scope 子目录)——若是 scope 子目录,需在壳里改取
  `--target` 的 resolve。实施首步验证之。
- **`is_relative_to` 最低 Python**:本仓声明 ≥3.10,`Path.is_relative_to` 自 3.9 入 stdlib,OK;实施时回归
  `test_zero_deps.py` + 非脚本目录 cwd 子进程跑(承 R5.8)确认无降级。

### Resolved (实施首步验证,task 4.3)

- **`MGH_TARGET` 取值源 —— 已验证,修正 FD5 措辞**:`discover_controls.py` 的 **stdout 不含 `repo`**
  (stdout = `{candidates,clusters,unresolved,unresolved_count,big_files,out_of_scope,truncated,scanned}`,
  见 `discover_controls.py:668`)。`repo` 仅写入**磁盘产物** `controls_candidates.json` / `clusters.json` /
  `skeleton.json`(`repo = str(Path(args.repo).resolve())`,`discover_controls.py:597/637/651`)。`--scope`
  只经 `resolve_seed` 收窄**被扫描文件**,从不改 `repo`——故 `repo` 在所有 `--scope` 模式下都是**绝对项目根**
  (= `--repo` resolve),非 scope 子目录。结论:`MGH_TARGET` 取 `controls_candidates.json::repo`(绝对根),
  经**合法瞄结构出口** `describe_artifact.py --field repo` 读取(非 `discover` stdout,但仍是确定性脚本 stdout
  字段、仍是 discover 算出的绝对 repo),编排器**逐字** export。`--help`/契约 lint 不受影响(无新 flag)。实施已按此落地(见两份 `mgh-init.md` step 2)。
- **`is_relative_to` —— 已验证**:`Path.is_relative_to` 自 3.9 入 stdlib,本仓 ≥3.10 OK;`test_zero_deps.py`
  与非脚本目录 cwd 子进程跑(task 7.6/8.1)确认无降级。
