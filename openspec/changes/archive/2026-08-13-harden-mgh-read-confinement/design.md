## Context

`/mgh-init`(及 `mgh-sast`/`mgh-sra`/`mgh-srr`/`mgh-ut-init`)的隔离 reader subagent(scout
最典型)在运行域内只**应**读当前工作目录(target 子树)的文件。当前**写侧**有三层确定性兜底
(`block_adhoc_scripts.py`:`_SCRIPT_EXTS` 写拦 + 越树写拦 + init/ut-init 受信子树正向清单),
但**读侧完全靠提示词自觉**:守卫 `main()` 只分派 `Bash`/`Write`/`Edit`(`elif tool in ("Write","Edit")`),
对 `Read`/`Glob`/`Grep` 在活跃域内**直接落到函数末尾 `return 0` 放行**;opencode shim 的
`HANDLED = {bash,write,edit}` 同款排除读侧。

现实失败形态(用户报告):工作目录是某 parent 仓的子模块(`D:\parent\sonA`,同级 `sonB`)。
scout subagent 拿到 batch 的 `targets[]`(各含 `file`)+ repo 根,在「Glob 兄弟包确认 fan_in」
这类合法读的诱导下,或因上下文压缩丢失「只读本 batch」约束,偶尔 `Read`/`Glob` 上级 `D:\parent\`
或兄弟 `D:\parent\sonB\` 的文件。宿主(无论 claude 还是 opencode)对这些越界路径发起**权限询问**,
**任务被中断**——这是非 fail-loud 的最坏形态:不是守卫拦下给 recipe,而是弹给人、阻塞流水线。

为何周期性复发:提示词约束是**概率性**的(弱模型忽略、压缩丢失、合法读诱惑带偏);历史修复
(写侧 allowlist、`MGH_TARGET` 子树)只补了写侧。需把读侧也下沉为 hook 确定性兜底——与写侧
**同形**:运行域内读侧目标解析落在 `MGH_TARGET` 子树外 → fail-loud(退出码 2)+ recipe。

> 读侧有两个面,二者都需兜底:
> - **工具抽象层**:`Read`/`Glob`/`Grep`(claude)/ `read`/`glob`/`grep`(opencode,内置 `grep` 工具
>   底层即 ripgrep)→ D1–D6 覆盖(取 `file_path`/`path` 锚点)。
> - **Bash 直接命令**:agent 持 `Bash` 工具,可直接跑 `rg`/`grep`/`findstr`/`find`/`fd`/`ag`/`ack`
>   绕过 Grep 工具抽象(opencode 默认带 ripgrep,`rg` 在 PATH)→ **D9 覆盖**(走 Bash 分支,现有 Bash
>   规则不针对「越界搜索路径」)。

> 设计前提(已核实):`Read` 工具 `file_path`;`Glob` 工具 `pattern` + 可选 `path`(锚点根,缺省=cwd);
> `Grep` 工具 `pattern` + 可选 `path`(锚点根)+ `glob`。读侧拦截判的是**这些路径字段解析后是否在
> `MGH_TARGET` 子树内**。Glob/Grep 无 `path` 时锚点=cwd——见决策 D4(cwd-as-anchor 降级)。

## Goals / Non-Goals

**Goals:**
- 运行域内 `Read`/`Glob`/`Grep` 越出 `MGH_TARGET` 子树 → fail-loud(退出码 2)+ 读侧 recipe,
  **消除权限询问中断**(把弹人的软失败变成给 recipe 的硬失败)。
- 运行域内 `Bash` 直接调文件搜索命令(`rg`/`grep`/`findstr`/`find`/`fd`/`ag`/`ack`,绕过 Grep 工具抽象)
  越出 `MGH_TARGET` 子树 → 同款 fail-loud(堵 agent 退化为 `Bash: rg …` 的逃逸路径;opencode 默认带 ripgrep)。
- 双端对等(claude `PreToolUse` + opencode `.ts` 插件),判定逻辑单一来源在 `.py`(`.ts` 仅 glue)。
- 复用既有 `_resolve_target`(env `MGH_TARGET` > 哨兵.`target` > degrade)+ 子树判定语义,
  与写侧**零分叉**。
- target 缺失(既无 env 又无哨兵.`target`)→ 读侧降级放行(与写侧一致,避 over-block)。
- subagent 路径绝对化加固:`list_scout_batches.py` 等 `pending[].targets[].file` 明确为 repo-相对
  或绝对,消除「相对路径 + cwd 漂移 → 解析到上级」歧义。
- 读侧提示词从 `freely` 改有界 recipe,告知 hook 兜底。

**Non-Goals:**
- **不**拦 `codegraph_explore` MCP 工具(非 `Read`/`Glob`/`Grep`,其越界由既有「`codegraph=on`
  仅覆盖索引语言、回退 Read 受限」提示词约束;MCP 工具不在本 hook 拦截面)。
- **不**改写侧三层约束(读侧是新增分支,写侧逻辑不动)。
- **不**做「读白名单」(不要求读路径必须在受信子树——读侧只需「在 target 子树内」,
  比 init 写侧正向清单**宽松**:repo 内任意文件可读,只是不许出 repo)。
- **不**拦非运行域(日常 dev 的 Read/Glob/Grep 零感知,与写侧同)。
- **不**做 Glob `pattern` 内 `..` 路径穿越的精细化解析(见 D5,保守取 `path` 锚点判定)。
- **不**穷尽所有 Bash 文件搜索逃逸形态(D9):管道/alias/env-注入路径不保证覆盖,只拦「显式绝对路径
  token + cwd 默认锚点」两个观察到的主力形态(与既有 temp-I/O / file-assoc 规则同立场)。

## Decisions

### D1 — 读侧拦截 = 写侧越树判定的同形扩展(非新机制)

复用 `_resolve_target` 拿 target、复用「`Path(p).resolve().is_relative_to(target)`」语义。
新增 `Read`/`Glob`/`Grep` 分支,调用一个新的 `_read_out_of_tree(tool_input, target) -> bool`
(逻辑与 `_is_out_of_tree` 同款,但读侧从多个字段取路径)。target 缺失 → 返回 False(降级放行)。

**为何不在守卫里复用 `_is_out_of_tree` 直调**:读侧要从 1–2 个字段取路径(Read=`file_path`;
Glob/Grep=`path` 锚点优先,缺省 cwd),且 Glob/Grep 的 `pattern` 本身可能含路径前缀——需一个
取路径的小适配层。判定核心(是否 `is_relative_to(target)`)与写侧**逐字一致**。

### D2 — Glob/Grep 取 `path` 锚点,`pattern` 内路径保守不解析

Glob/Grep 的**作用域**由 `path` 字段决定(opencode `path`/claude `path`);`pattern` 是 glob/regex,
通常相对 `path`。拦截判 `path` 解析后是否在 target 子树内。`path` 缺省 = cwd:
- cwd 在 target 子树内(正常:cwd=target 或 target/.mgh-init)→ 放行;
- cwd 在 target 外(异常:cwd 漂到 parent)→ **D4 处理**。

`pattern` 内的 `../` 前缀等穿越形态**不解析**(D5):regex 解析 glob pattern 内的相对穿越既脆弱
又易误伤(合法 `**/*.java` 不该被拦)。保守只判 `path` 锚点;`pattern` 穿越由「reader 只对本批
`targets[]`」提示词 + target 子树判定共同约束(若 `path` 在树内、`pattern` 越界,实际 Read 越界
文件时会再被 Read 分支拦——读侧是**多工具协同兜底**,非单点)。

### D3 — Read 多路径 / Grep 无 path 的边界

- **Read `file_path`**:单路径,直接判。
- **Grep 无 `path`、有 `glob`**:`glob` 是文件名 pattern 非路径(opencode/claude 语义),锚点=cwd
  → 走 D4 cwd 判定。
- **Glob/Grep `path` 是文件而非目录**:`Path(path).resolve()` 后判 `is_relative_to(target)`
  仍成立(文件必在其父目录子树内),无需特判。

### D4 — cwd-as-anchor 降级(Glob/Grep 无 `path` 时)

Glob/Grep 缺省锚点=cwd。守卫已 `cwd = Path.cwd()`。判 `cwd.is_relative_to(target)`:
- True → 放行(正常 cwd=target 子树);
- False → fail-loud + recipe「Glob/Grep 无 path 锚点且 cwd 不在 target 子树;显式传 path 落在
  repo 根,或确保 cwd 在 target 内」。

**理由**:cwd 漂到 target 外(如 opencode 把 cwd 设成 temp、或子模块场景 cwd=parent)正是
失败形态之一;此时无 path 锚点的 Glob/Grep 会扫到上级目录——该拦。但若 target 本身缺失(D1 降级),
整条读侧放行,不触发 D4。

### D5 — `pattern` 内 `..` 穿越不解析(保守,防误伤)

不在守卫里解析 glob/regex `pattern` 的相对路径段。理由:① regex/glob 语法跨工具不一致,解析
易误伤合法 pattern;② 读侧已有多工具协同兜底(`path` 锚点 + Read 单文件判);③ 守卫是
regex-over-observed-shape,不声称穷尽(与既有 temp-I/O / file-assoc 规则同立场,D7)。
若未来观察到 `path` 在树内 + `pattern` 穿越逃逸的真实失败,再补(记录为本设计 Open Question)。

### D6 — opencode shim 扩 `HANDLED` + `normalize`,判定仍只在 `.py`

`block_adhoc_scripts.ts`:`HANDLED` 加 `read`/`glob`/`grep`;`normalize` 补:
- `read` → `{tool_name:"Read", tool_input:{file_path: args.file_path ?? args.filePath}}`
- `glob` → `{tool_name:"Glob", tool_input:{pattern: args.pattern, path: args.path}}`
- `grep` → `{tool_name:"Grep", tool_input:{pattern: args.pattern, path: args.path, glob: args.glob}}`

`.ts` **不**含任何判定逻辑(承 D7 glue-only;`test_shim_exists_and_is_glue_only` 的 forbidden
token 列表会扩 `_read_out_of_tree`/`_out_of_tree_file_search`)。parity 测 `test_only_bash_write_edit_handled`
**改为** `test_bash_write_edit_read_glob_grep_handled`(assert HANDLED 含五项)。

### D7 — subagent `targets[].file` 绝对化(消除 cwd 漂移歧义)

`list_scout_batches.py`(及 init 其余 reader 枚举脚本)的 `pending[].targets[].file` 当前是
`scout_plan.json` 里的形态(扫描产出,多为 repo-相对或绝对)。**加固**:`input.json` 物化时,
每个 `targets[].file` 解析为**绝对路径**(相对 `repo` 字段解析),并保留一个 `repo_relative`
字段(原值)供记录。subagent 拿到的 `file` 一律绝对 → 即便 cwd 漂移,Read 绝对路径也在 target
子树内(被 hook 放行);若 subagent 自行拼相对路径越界,则被 D1–D4 拦。

**为何连带改这**:hook 兜底拦越界,但**正本清源**是让 subagent 拿到的路径本就在树内——绝对化
消除「相对路径 + cwd 漂移 → 解析到上级」这条非主观越界路径(承 R5.3(b) 扇出路径绝对化精神,
补读侧 `targets[].file`)。

### D8 — 读侧 recipe 文案(指向本批/树内)

读侧命中 → stderr recipe(类写侧):
```
blocked: read outside the MGH_TARGET tree in <domain> run-domain: <path/tool>
  target tree = <target>
  Read/Glob/Grep MUST stay inside the target tree (your cwd's project). Read only this
  batch's input_path / targets[]; for sibling-package confirmation use Glob/Grep with an
  explicit `path` anchored at the repo root. NEVER read the parent dir or sibling modules.
```
recipe 不引受信子树(读侧无正向清单,只判 target 子树)。Bash 文件搜索命中(D9)复用同款 recipe。

### D9 — Bash 直接文件搜索命令(rg/grep/findstr/find/fd/ag/ack)的读侧越界拦截

agent 除原生 `Read`/`Glob`/`Grep` 工具外,**还有 `Bash` 工具**,可在 Bash 里直接跑文件搜索
二进制(`rg "pattern" D:\parent\sonB`、`findstr /S … D:\parent`、`find D:\parent\sonB …`)——
这**绕过 Grep 工具抽象**,走守卫的 `Bash` 分支,而现有 Bash 规则(`py -c`/temp-I/O/
whole-aggregate-read/file-assoc)**都不针对「越界搜索路径」**(`_READ_VERB` 只含
`cat|head|tail|type|Get-Content|gc`)。这是 D1–D8 之外的真实读侧逃逸路径(用户补充确认:opencode
默认带 ripgrep,`rg` 在 PATH)。

> **澄清两种 ripgrep 形态**:① opencode 内置 `grep` 工具(底层 ripgrep)/claude `Grep` 工具
> (底层 ripgrep)→ 走工具抽象(`tool.execute.before` 的 `grep` / PreToolUse 的 `Grep`),`path`
> 锚点已被 D1–D6 覆盖,**底层 rg 跑不跑不重要**(其搜索范围由被约束的 `path` 决定)。② agent 在
> `Bash` 里**直接**调 `rg`/`grep`/… → 走 Bash 分支,**D9 治理**。
> (若未来 opencode 暴露独立 `rg` 工具 id,则 D6 `HANDLED` 一并加 `rg`;当前据 opencode 工具集其
> 文件搜索工具名为 `grep`,直接 rg 走 Bash。)

设计(保守,承 D5/D7「regex-over-observed-shape、不声称穷尽」立场):
- 新增 Bash 文件搜索动词集 `_FILE_SEARCH_VERBS = {rg, ripgrep, grep, egrep, fgrep, findstr,
  find, fd, ag, ack}`。守卫扫描命令的首动词(及 `;`/`|`/`&&`/`||` 后子命令首词)是否命中。
- 命中时,**扫描命令字符串里所有「显式绝对路径 token」**(Windows 盘符 `[A-Za-z]:[\\/]…` /
  POSIX `/…` / UNC `\\…`),逐个 `resolve()` + `is_relative_to(target)`;**任意一个**落 target 外
  → fail-loud + 读侧 recipe(D8 同款文案)。
- 无显式绝对路径 token(如 `rg "pattern"`,默认递归 cwd)→ 走 **D4 同款 cwd 判定**:
  `cwd.is_relative_to(target)` 为 False(cwd 漂到 parent)→ fail-loud;target 缺失 → 整条降级放行。

**为何不精确解析「哪个 token 是 pattern / 哪个是 path」**:rg/grep/find 语法各异(`rg PAT PATH…` /
`grep OPT PAT FILE…` / `find PATH EXPR`),精确分词脆弱且易误伤。全扫「绝对路径 token」是更稳的
近似——合法的 `rg PATTERN`(pattern 非路径)不会被匹配,只有命令里**真出现一个盘符/根绝对路径**
且落 target 外才拦。

误伤面:`rg "C:\\literal\\in\\pattern" D:\tree\in` 这种 pattern 字面量含盘符路径的极罕见形态会
误拦(agent 改 pattern 即可);接受此误伤换覆盖,承非穷尽标注。管道/重定向/alias/env-注入路径等
复杂形态**不保证**覆盖(与既有 temp-I/O / file-assoc 规则同立场)。

## Risks / Trade-offs

- **[误伤合法 repo 内读]** → 读侧只判「在 target 子树内」(非受信子树正向清单),repo 内任意
  文件可读,误伤面比写侧窄;且 target 缺失降级放行。Glob/Grep 无 path 锚点走 D4 cwd 判,
  正常 cwd=target 不误伤。
- **[`pattern` 穿越逃逸未被拦]**(D5)→ 多工具协同兜底(Read 单文件判 + path 锚点判);保守
  防误伤优先;记为 Open Question,观察真实失败再补。
- **[Bash `rg`/`grep`/… 复杂形态未穷尽]**(D9)→ 守卫只扫「显式绝对路径 token + cwd 默认锚点」;
  管道/alias/env 注入路径不保证覆盖。读侧是多工具协同兜底(工具抽象层 D1–D6 + Bash 文件搜索 D9);
  观察到新逃逸形态再补(承 regex-over-observed-shape)。
- **[opencode cwd 可能非 target]** → D4 显式判 cwd,漂移即 fail-loud + recipe(优于静默越界);
  哨兵 `target` 字段为读侧子树判定的可靠来源(承写侧 env > 哨兵 > degrade)。
- **[回归测需同步]** → `test_only_bash_write_edit_handled` 改;forbidden-token / new-logic-marker
  列表加 `_read_out_of_tree`/`_out_of_tree_file_search`/`_FILE_SEARCH_VERBS`;新增读侧 + Bash 文件
  搜索用例(parent/sonA/sonB、target 缺失降级、in-tree 放行)。CI 必过(R5.8)。
- **[提示词 `freely` 诱导]** → 读侧 recipe 下沉到 stage prompt(删 freely),但 hook 是确定性兜底,
  提示词收紧是正引导、非唯一防线(承 R5.5① shaping 失败用 recipe)。

## Migration Plan

1. 守卫 `.py`(双端 byte-identical)加读侧分支:`_read_out_of_tree`(工具抽象层 Read/Glob/Grep)+
   `_out_of_tree_file_search`(Bash rg/grep/find/…)+ `_FILE_SEARCH_VERBS` 集;版本号 bump。
2. opencode shim `HANDLED` + `normalize` 扩;parity 测改 + 加读侧用例。
3. `list_scout_batches.py` 等 `targets[].file` 绝对化(向后兼容:保留 `repo_relative`)。
4. reader stage prompt 删 `freely`、加有界读 recipe。
5. spec delta + 契约 md + 回归测;`openspec validate`;install 自检。
- **回滚**:读侧分支是新增(不改写侧);回滚 = 还原 `.py`/`.ts`/测/prompt。无数据迁移、无产物
  schema 破坏(`targets[].file` 绝对化是 input.json 物化层,reader 既读绝对也兼容)。

## Open Questions

- D5 `pattern` 穿越逃逸:是否需要观察真实失败后再补 `pattern` 内 `..` 解析?(当前:否,保守。)
- D9 Bash 文件搜索:管道/alias/env-注入路径形态未覆盖,观察真实逃逸后再补?(当前:否,保守。)
- 读侧是否需要 `--read-scope` opt-out(类似 `--no-enforce-hook`)?(当前:否,target 缺失已降级。)
- **[同源缺口,另起 change]** 本次只治读侧 Bash 逃逸(D9:agent 在 Bash 直接调文件**搜索**绕过 Grep 工具)。
  对称地,agent 还可在 Bash 直接调文件**写**命令绕过宿主 `Write`/`Edit` 工具(其越树写由工具抽象
  规则 `_is_out_of_tree` 覆盖)——已实测放行:`New-Item -Path D:\out…` / `Set-Content D:\out\f` /
  `"x" > D:\out\f.json` / `mkdir D:\out\d` / `Copy-Item x D:\out\` 均退出码 0。这是写侧 Bash 逃逸
  (本 change 不动写侧,见 Non-Goals),由 `harden-mgh-write-confinement`(新 change)治理:同款
  「文件-I/O 动词集 + 显式绝对路径越树 token 扫描 + cwd 默认锚点」,复用本 change 的 `_ABS_PATH_TOKEN_RX`
  与 D4/D9 形态。本 change 的 read-side 规则与该 write-side 规则**结构同构**,设计可移植。
