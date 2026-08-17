# Tasks — harden-mgh-read-confinement

> 读侧确定性兜底:运行域内 `Read`/`Glob`/`Grep` 越出 `MGH_TARGET` 子树 → fail-loud(退出码 2)+ recipe。
> 守卫双端 byte-identical;opencode shim 仅扩 `HANDLED`/`normalize`(判定单一来源仍在 `.py`)。

## 1. 守卫读侧分支:工具抽象层 Read/Glob/Grep(claude canonical,双端同源)

- [x] 1.1 `releases/claude-code/hooks/block_adhoc_scripts.py`:新增 `_read_out_of_tree(tool_input, target, cwd) -> bool`
  ——从 `Read.file_path` / `Glob.path` / `Grep.path` 取锚点路径(Glob/Grep 无 `path` 时锚点=cwd),
  `Path.resolve().is_relative_to(target)` 判越界;target 缺失 / 路径空 / 不可解析 → 返回 False(降级放行,
  与 `_is_out_of_tree` 同款)。cwd 作锚点时判 `cwd.is_relative_to(target)`(D4)。
- [x] 1.2 `main()` 新增 `Read`/`Glob`/`Grep` 分支(在 `elif tool in ("Write","Edit")` 之后):active 域内调
  `_read_out_of_tree`,命中 → stderr 读侧 recipe(D8 文案)+ `return 2`;非 active 已在开头 `return 0`。

## 1b. 守卫读侧分支:Bash 文件搜索命令 rg/grep/findstr/find/fd/ag/ack(D9)

- [x] 1b.1 新增 `_FILE_SEARCH_VERBS` 集(`rg`/`ripgrep`/`grep`/`egrep`/`fgrep`/`findstr`/`find`/`fd`/`ag`/
  `ack`)+ 首动词命中检测(扫命令及 `;`/`|`/`&&`/`||` 后子命令首词)。
- [x] 1b.2 新增 `_out_of_tree_file_search(command, target, cwd) -> bool`:命中文件搜索动词时,扫命令里所有
  显式绝对路径 token(Windows `[A-Za-z]:[\\/]…`/POSIX `/…`/UNC `\\…`),逐个 `resolve()`+
  `is_relative_to(target)`,任意越界 → True;无显式绝对路径 → 走 D4 cwd 判定(`cwd.is_relative_to(target)`
  为 False → True)。target 缺失 → False(降级)。
- [x] 1b.3 `main()` Bash 分支:在既有 Bash 规则之后(或并列)调 `_out_of_tree_file_search`,命中 → 读侧
  recipe(D8 同款)+ `return 2`。注意 operand-vs-arg:非文件搜索动词命令(如 `py … --in x.java`)不进此分支。

## 1c. 守卫公共:recipe + 文档 + 版本

- [x] 1c.1 读侧 recipe 函数 `_read_recipe(domain, target)`(类 `_recipe`,指向「只读本批 input_path/targets[];
  Glob/Grep 显式 path 锚 repo 根;Bash 搜索命令同理;NEVER 读 parent/兄弟模块」),不引受信子树(读侧无正向
  清单)。工具抽象层命中(D1)与 Bash 文件搜索命中(D9)共用此 recipe。
- [x] 1c.2 模块 docstring + 顶部注释补读侧拦截描述(失败形态:`Read`/`Glob`/`Grep` 越树读 + Bash `rg`/`grep`/…
  越界搜 → 弹人中断 → 改 fail-loud);更新「Blocks the real-world failure shapes」清单(加读侧两条)。
- [x] 1c.3 守卫版本号 bump(若文件头有版本标记;否则记入 install 自检受影响清单)。

## 2. 守卫双端 byte-parity

- [x] 2.1 把改后的 `releases/claude-code/hooks/block_adhoc_scripts.py` **逐字节**复制到
  `releases/opencode/hooks/block_adhoc_scripts.py`(单一真相源 = claude 侧;opencode twin 仅镜像)。
- [x] 2.2 跑 `py tests/test_opencode_hook_parity.py::TestGuardByteParity` 确认双端 byte-identical。

## 3. opencode shim 扩读侧(glue-only)

- [x] 3.1 `releases/opencode/plugins/block_adhoc_scripts.ts`:`HANDLED` 集合从 `{bash,write,edit}` 扩到
  `{bash,write,edit,read,glob,grep}`;更新 D7 parity 注释(读侧现在 handled;**Bash 直接 rg/grep 走 Bash
  分支无需加 HANDLED**,只有原生 read/glob/grep 工具加)。
- [x] 3.2 `normalize()` 补 `read`/`glob`/`grep` 分支:`read`→`{tool_name:"Read",tool_input:{file_path}}`;
  `glob`→`{tool_name:"Glob",tool_input:{pattern,path}}`;`grep`→`{tool_name:"Grep",tool_input:{pattern,path,glob}}`
  (camelCase→snake_case,缺省空串)。
- [x] 3.3 确认 shim **不含**判定逻辑(`is_relative_to`/target 解析/`_read_out_of_tree`/
  `_out_of_tree_file_search`/`_FILE_SEARCH_VERBS` 等禁词不出现)。

## 4. subagent 路径绝对化加固(正本清源)

- [x] 4.1 `core/scripts/list_scout_batches.py`:`_materialize_input`(物化 `<batch_id>.input.json`)时,把
  每个 `targets[].file` 解析为**绝对路径**(相对 plan 的 `repo` 字段解析),保留 `repo_relative` 字段(原值)。
- [x] 4.2 同步检查 init 其余 reader 枚举脚本(`list_clusters.py`/`list_rule_jobs.py`)的 fan-out `targets[].file`
  形态;若同样可相对,同款绝对化(向后兼容:reader 读绝对路径不受影响)。
- [x] 4.3 各脚本 `--check`(R5.9)若已校验 schema,补「`file` 绝对或带 `repo_relative`」断言。

## 5. 读侧提示词 recipe 下沉(删 freely)

- [x] 5.1 `core/prompts/stages/init-scout.md`:「Use Read / Glob / Grep freely」→ 有界 recipe(「Read 本批
  `input_path`/`targets[]`;Glob/Grep 的 path 锚 repo 根;**Bash 搜索命令同理,NEVER `rg`/`grep`/`find` …
  越出 repo**;NEVER 读 repo 根上层、NEVER 读兄弟模块;hook 会确定性兜底越界读」)。同步改
  「The repo root (so you can Read / Glob / Grep)」措辞为有界。
- [x] 5.2 `core/prompts/stages/init-survey.md` / `init-induct.md`(及其余含 `freely` / 泛读措辞的 reader
  stage):同款收紧(含 Bash 搜索命令约束)。
- [x] 5.3 ut 对应 reader stage(`core/prompts/stages/ut-*.md` 读侧)同款(若存在泛读措辞)。
- [x] 5.4 agent 定义 `releases/{claude-code,opencode}/agents/init-scout.md`(及 reader agent)的 tools 列表
  不变(读侧工具仍需),仅措辞对齐(若 agent 定义含读侧 freely 措辞)。

## 6. spec + 契约文档

- [x] 6.1 `openspec/specs/runtime-hook-enforcement/spec.md`:本 change 的 delta 已在
  `specs/runtime-hook-enforcement/spec.md`(ADDED 三条 requirement:读侧工具抽象 + opencode 读侧 normalize +
  Bash 文件搜索);apply 时合并入主 spec(由 opsx:apply / archive 处理,本任务仅确认 delta 完整)。
- [x] 6.2 `core/contracts/hooks/runtime-enforcement.md`:补「读侧越树拦截」段(读侧规则表:Read 取 file_path、
  Glob/Grep 取 path 锚点 / cwd、**Bash 文件搜索动词集 + 显式绝对路径 token 扫描 + cwd 默认锚点**、target
  缺失降级、recipe 文案);更新「Runtime write discipline」标题为「Runtime I/O discipline」或并列加
  「Runtime read discipline」小节。
- [x] 6.3 `AGENTS.md` R5.7 段 B:补读侧拦截(工具抽象 + Bash 文件搜索)为 #1 违例兜底的扩展(措辞精炼,
  承 R3;不复制规则条文)。

## 7. 回归测 + parity 测(读侧用例)

- [x] 7.1 `tests/test_block_adhoc_scripts.py`:新增 `TestReadSideConfinement` ——
  Read parent/sonB 越界拦、Read in-tree 放行、Glob path=sonB 越界拦、Grep 无 path + cwd=parent 越界拦(D4)、
  Grep path=repo-root 放行、target 缺失降级放行、非 active 域静默放行;**+ Bash 文件搜索(D9)**:
  `rg pat D:\parent\sonB` 越界拦、`rg pat`(cwd=parent)越界拦(D4)、`rg pat D:\parent\sonA\src` 放行、
  `findstr`/`find`/`grep` 同款、`py … --in x.java` 非搜索动词不误伤、非 active 域静默放行。
- [x] 7.2 `tests/test_opencode_hook_parity.py`:
  - 改 `test_only_bash_write_edit_handled` → `test_bash_write_edit_read_glob_grep_handled`(assert `HANDLED`
    含五项;`normalize` 覆盖 read/glob/grep);
  - `test_shim_exists_and_is_glue_only` 的 forbidden-token 列表加 `_read_out_of_tree`/
    `_out_of_tree_file_search`/`_FILE_SEARCH_VERBS`;
  - `test_both_guards_embed_new_sentinel_logic` 的 marker 列表加 `_read_out_of_tree`/
    `_out_of_tree_file_search`/`_FILE_SEARCH_VERBS`;
  - 新增 opencode 读侧 parity 用例(read/glob/grep 经 normalize → guard 同决策;Bash rg 走 Bash 分支同决策)。
- [x] 7.3 跑全量回归:`py tests/test_block_adhoc_scripts.py` + `py tests/test_opencode_hook_parity.py` +
  `py tests/test_deterministic.py`(确保路径绝对化未破坏既有 init 枚举契约)。

## 8. 验收 + install 自检

- [x] 8.1 `openspec validate harden-mgh-read-confinement --strict`(spec delta 合法)。
- [x] 8.2 `tools/check_contracts.py` + `tools/check_distributed_purity.py`(读侧 recipe 措辞无 dev-meta 漏出;
  命令壳调用契约未变)。
- [x] 8.3 `tools/measure_prompts.py` / prompt-budget lint(reader stage 改措辞后 token 不超 R5.6 上限)。
- [x] 8.4 install 自检(`install.sh --claude .` 干跑或受控目标)确认 hook `.py`/`.ts` 同目录共存 + 读侧
  逻辑随 install 落目标仓;版本号 bump 反映在 install 自检(R5.8)。
- [x] 8.5 手测(可选,opencode 真机):子模块场景 `D:\parent\sonA` 跑 `/mgh-init`,触发 scout 越界读
  (Read/Glob/Grep + Bash rg)→ 确认 fail-loud + recipe(非权限询问中断)。
