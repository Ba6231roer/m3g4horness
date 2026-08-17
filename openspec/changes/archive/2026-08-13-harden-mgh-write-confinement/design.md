## Context

`block_adhoc_scripts` 守卫(双端 byte-identical,`releases/{claude-code,opencode}/hooks/block_adhoc_scripts.py`)
已对**读侧**做了三层确定性兜底(`harden-mgh-read-confinement` 落地):工具抽象 `Read`/`Glob`/`Grep` 越树拦
+ Bash 文件搜索 `rg`/`grep`/… 越树拦(D9)。**写侧**亦有工具抽象三层(`_SCRIPT_EXTS` + `_is_out_of_tree` +
init/ut-init 正向清单 `_allowlist_write_blocked`)。但审计确认**写/删侧 + 工具面**仍有 8 个同源缺口:

- **Bash 分支无写/删动词集**:现有 Bash 规则(`py -c` 内省 / temp-I/O / whole-aggregate-read / file-assoc /
  文件搜索)**都不针对「越树写/删路径」**。`New-Item`/`Set-Content`/`mkdir`/`Copy-Item`/`Move-Item`/`tee`/
  `Remove-Item` 全部放行(真机 exit 0)。
- **`_TEMP_WRITE_RX` 只匹配 temp 前缀**:`echo x > D:\out\f.json`(非 temp 越树)漏。
- **规则 a 误标写形态**:`py -c "open(..,'w')"` 被 `_INTRO_TOKENS`(open(+.json)当内省拦,recipe 误导。
- **工具抽象分支只匹配 `(Write,Edit)`**:claude `MultiEdit`/`NotebookEdit` 落到 `return 0` 放行。
- **opencode `apply_patch` 不在 shim `HANDLED`**:多文件 add/update/**delete**,路径藏 `patchText` → 全绕过。
- **init/ut-init 正向清单只管 Write/Edit 工具**:`Set-Content <target>\evil.txt`(树内根污染,Bash)绕过清单。

> 写侧有三个面,三者都需兜底:
> - **工具抽象层**:`Write`/`Edit`(已覆盖)+ `MultiEdit`/`NotebookEdit`(claude,T2/T3 漏)+ `apply_patch`
>   (opencode,T1 漏)。
> - **Bash 直接写/删命令**:agent 持 `Bash`,直接调文件写/删动词绕过 `Write`/`Edit` 工具抽象(W1/W3)。
> - **Bash 重定向**:非 temp 越树 `>`/`>>`(W2)。
> 三者共享同一检测模式(**动词集 / 工具 id + 绝对路径 token 扫描 + `is_relative_to(target)` + cwd 默认锚点**),
> 与读侧 D9 / 既有 `_TEMP_WRITE_RX` 同立场(regex-over-observed-shape)。

> 设计前提(已核实):claude `MultiEdit` 字段 `{file_path, edits[]}`;`NotebookEdit` 字段
> `{notebook_path, cell_id, new_source}`;opencode `apply_patch` 字段 `{patchText}`,路径在标记行
> `*** (Add|Update|Delete) File: <path>` / `*** Move to: <path>`(`C:\DEV\opencode\packages\core\src\patch.ts:35-51`)。
> opencode `edit`/`write`/`read` 的 schema 字段名是 `path`(`packages/core/src/tool/{edit,write,read}.ts`),
> 非当前 shim 假设的 `filePath`。

## Goals / Non-Goals

**Goals:**
- 运行域内 Bash 写/删动词(`New-Item`/`Set-Content`/`mkdir`/`Copy-Item`/`Move-Item`/`tee`/`Remove-Item`/…)的
  越树目标 → fail-loud(退出码 2)+ 写侧 recipe。
- 运行域内非 temp 越树 `>`/`>>` 重定向 → 同款 fail-loud(泛化 `_TEMP_WRITE_RX`)。
- 运行域内 Bash **破坏性删**(`Remove-Item`/`del`/`rm`/`rmdir`/`shutil.rmtree`)越树 → fail-loud + **删侧
  措辞 recipe**(删除不可逆,recipe 明示)。
- init/ut-init 域内 **Bash 写/重定向目标即便在树内也要落受信子树**(P1)——复用 `_allowlist_write_blocked`,
  堵 Bash 根污染绕过 Write/Edit 工具层清单。
- 工具面:claude `MultiEdit`/`NotebookEdit` 入变更分支(T2/T3);opencode `apply_patch` 入 `HANDLED` +
  patchText 标记解析 + 守卫判定(T1)。越树 → fail-loud。
- 规则 a 写形态重标(L1):消除「内省 recipe 误导写」;统一越树判定。
- 双端对等(claude `PreToolUse` + opencode `.ts` 插件),判定逻辑单一来源在 `.py`(`.ts` 仅 glue +
  patchText 标记字段提取)。
- 复用既有 `_resolve_target`(env `MGH_TARGET` > 哨兵.`target` > degrade)+ `_ABS_PATH_TOKEN_RX` + 子树判定
  语义,与读侧/写侧**零分叉**。target 缺失 → 写/删侧降级放行(与读/写侧一致,避 over-block)。

**Non-Goals:**
- **不**穷尽所有 Bash 写/删逃逸形态(D7):管道/alias/env-注入路径、PowerShell `.NET` 静态方法
  (`[System.IO.File]::WriteAllText`/`::Delete`)、`robocopy`/`fsutil`/`certutil` 等不保证覆盖(承
  regex-over-observed-shape;与 temp-I/O / file-assoc / 读侧 D9 同立场)。观察到新真实逃逸再补。
- **不**做「写白名单 opt-out」(target 缺失已降级;`--no-enforce-hook` 既有)。
- **不**改读侧三层约束(读侧已闭环,本 change 只动写/删/工具面)。
- **不**把 `.ipynb` 入 `_SCRIPT_EXTS`(notebook 是产物非运行时脚本;NotebookEdit 只做越树 + 受信子树判)。
- **不**拦非运行域(日常 dev 的 Bash 写/删零感知,与读/写侧同)。
- **不**做 patch 语义级解析(只取 `*** File: <path>` 标记行路径,不解析 hunk diff 内容)。

## Decisions

### D1 — 写/删侧拦截 = 读侧 D9 的同形扩展(非新机制)

复用 `_resolve_target` 拿 target、复用「`Path(p).resolve().is_relative_to(target)`」语义、复用
`_ABS_PATH_TOKEN_RX` 扫命令里的显式绝对路径 token。新增 `_WRITE_VERBS`/`_DELETE_VERBS` 集与
`_out_of_tree_mutation(command, target, cwd, verb_set) -> bool`(逻辑与 `_out_of_tree_file_search` 同款,
但动词集是写/删而非搜索)。target 缺失 → 返回 False(降级放行,与读/写侧一致)。

**为何写与删分两集**:删(`Remove-Item`/`rm`/…)语义是**破坏性不可逆**,recipe 措辞需明示「NEVER 删除
target 子树外的任何路径;删除不可逆」,区别于写 recipe(指向产出者 stdout 绝对路径)。分集让 recipe 精准。

### D2 — 写/删动词集 + 首动词命中检测(镜像 `_FILE_SEARCH_VERB_RX`)

- `_WRITE_VERBS = {New-Item, ni, Set-Content, sc, Add-Content, ac, Out-File, tee, mkdir, md,
  Copy-Item, cpi, cp, copy, xcopy, Move-Item, mi, mv, rename, Rename-Item, ri}`(PowerShell + POSIX + 别名)。
- `_DELETE_VERBS = {Remove-Item, ri, del, erase, rm, rmdir, rd}`(破坏性,单独集)。
- 首动词命中检测 `_MUTATION_VERB_RX = re.compile(r'(?:^|[;|&])\s*(?:&&|\|\|)?\s*(' + "|".join(WRITE|DELETE)
  + r')\b', re.IGNORECASE)`(逐字镜像 `_FILE_SEARCH_VERB_RX`,group(1)=动词,据此选 recipe)。
- Copy/Move 的**目标** token:动词命中后,扫所有绝对路径 token,**末**token(目标)判越树(源 token 在树内
  合法,只判目标)。对 `New-Item`/`Set-Content` 等「单路径」动词,任意越树 token 即拦。

### D3 — 非 temp 越树重定向(W2):泛化 `_TEMP_WRITE_RX`

当前 `_TEMP_WRITE_RX` 只匹配 `$env:TEMP`/`%TEMP%`/`/tmp`/`$TMPDIR` 前缀 + **要求同命令读回**
(`_detect_temp_io` 的 AND 条件)。泛化为:
- 新增 `_REDIRECT_RX = re.compile(r'>>?\s*"?\'?([^\s;"\'&|]+)')` 捕获**任意** `>`/`>>` 重定向目标。
- 对捕获的目标 `resolve()` + 越树判定 + init/ut-init 正向清单(D5);temp 目标仍由 `_detect_temp_io`
  独立处理(读回防御,保留)。
- **不**要求读回(纯越树重定向 `echo x > D:\out\f` 亦拦)。temp 读回是另一条防御,与本规则正交。

**误伤面**:`echo x > out.txt`(相对路径,resolve 到 cwd 子树)若 cwd 在 target 内 → 放行(正常);
`py producer.py > logs.txt`(树内相对)放行。只有越树绝对路径才拦。

### D4 — cwd 默认锚点(写/删动词无显式绝对路径时,镜像读侧 D4)

写/删动词命中、命令**无**任何显式绝对路径 token(如 `Set-Content evil.txt`)→ 目标默认相对 cwd。判
`cwd.is_relative_to(target)`:
- False(cwd 漂到 target 外,如子模块 cwd=parent)→ fail-loud + recipe「Bash 写/删无显式路径且 cwd 不在
  target 子树;用产出者 stdout 绝对路径,或确保 cwd 在 target 内」。
- True → 进 D5(init/ut-init 树内正向清单判)。
- target 缺失 → 整条降级放行(D1),不触发 D4。

### D5 — init/ut-init 树内 Bash 写正向清单(P1):复用 `_allowlist_write_blocked`

init/ut-init 域,Bash 写动词/重定向的目标即便在树内,**也要落** `_ALLOWLIST_SUBTREES`(复用
`_allowlist_write_blocked`,与 Write/Edit 工具层逐字同款):`Set-Content <target>\evil.txt`(根污染)→ 拦。
sast/sra/srr 只判越树(D1),无正向清单(与 Write/Edit 工具层一致)。

**为何连带**:正向清单的威胁模型是「根污染」(`temp_clusters*.json`/`process_*.ps1`),原只管 Write/Edit
工具;Bash `Set-Content <target>\evil.txt` 同形绕过。镜像到 Bash 侧,堵缺口。

### D6 — claude MultiEdit / NotebookEdit 入变更分支(T2/T3)

- `elif tool in ("Write", "Edit"):` 扩为 `elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):`。
- 路径字段提取:`path = ti.get("file_path") or ti.get("notebook_path") or ti.get("path") or ""`
  (MultiEdit=`file_path`,NotebookEdit=`notebook_path`,兼容 `path`)。
- 后续 `_is_blocked_script_write` + 越树 + 正向清单逐字复用。`.ipynb` **不**入 `_SCRIPT_EXTS`(notebook 非
  运行时脚本;NotebookEdit 只判越树 + 受信子树)。

**零新检测逻辑**:纯工具 id 扩展 + 路径字段兼容。一行元组 + 一行字段提取。

### D7 — opencode apply_patch(T1):patchText 标记解析 + 守卫多路径判定

- `.ts` shim `HANDLED` 加 `apply_patch`;`normalize` 新增分支:从 `args.patchText` 解析所有标记行
  `*** (Add|Update|Delete) File: <path>` / `*** Move to: <path>`(opencode patch 格式,
  `packages/core/src/patch.ts:35-51`),透传为 `{tool_name:"ApplyPatch", tool_input:{paths:[<path>...],
  operations:[add|update|delete|move]...}}`。**标记解析是字段提取(glue),判定单一来源在 `.py`**。
- 守卫新增 `elif tool == "ApplyPatch":` 分支:对 `tool_input.paths[]` **每个**路径跑 `_is_blocked_script_write`
  (add/update 的脚本扩展名)+ 越树判定(D1)+ init/ut-init 正向清单(D5);**任意一个**路径命中 → fail-loud +
  写/删 recipe(delete 操作走删侧措辞)。
- `.ts` shim **不**含越树/扩展名判定逻辑(forbidden-token 测会加 `_out_of_tree_mutation`/`_WRITE_VERBS`/
  `_DELETE_VERBS`/`ApplyPatch` 守卫侧符号,确保 shim 不重实现)。

**为何 patchText 解析放 shim 而非守卫**:opencode 的 `args` 是 camelCase 原始形态;守卫吃 claude 形态
`{tool_name, tool_input}`。patchText 标记提取是**归一化**(把多路径 blob 拆成 `paths[]`),与既有
`normalize` 把 `filePath`→`file_path` 同性质(glue)。判定仍在守卫。

### D8 — 规则 a 写形态重标(L1):统一越树判定,删误导 recipe

`_INTRO_TOKENS` 当前含 `open(`/`load(`/`.json` 会误命中 `py -c "open('D:/out/f','w').write('x')"`(写)
当内省拦,recipe 误导。重构:
- `_PYC_RX` 命中后,**先**判命令是否含越树绝对路径 token(D1 扫描):是 → 写侧 recipe(越树写);否 →
  再判内省 token(`import json`/`load(` 读 `.json`),是 → 内省 recipe。
- 扩 `_PYC_WRITE_TOKENS = {makedirs, write(, write_text, write_bytes, shutil.copy, shutil.move,
  shutil.rmtree, os.replace, os.rename, os.remove, os.unlink}` 做写形态识别(recipe 措辞精准)。
- **纯越树**(`py -c "import os; os.makedirs('D:/out/d')"` 无内省 token)现由 D1 越树扫描覆盖(此前漏)。

**为何不删 `_INTRO_TOKENS` 的 `open(`**:合法内省(`py -c "import json; json.load(open('x.json'))"`)
仍需内省拦;只是写形态先走越树判定,recipe 不误导。顺序:越树(写)→ 内省(读)→ 放行。

### D9 — opencode arg-name 防御性 fallback(P-arg)

`.ts` shim `normalize` 的 `edit`/`write`/`read` fallback 链从 `args?.filePath ?? args?.file_path` 扩为
`args?.filePath ?? args?.file_path ?? args?.path`(opencode schema 字段名是 `path`;当前靠 LLM 发 camelCase
才对,加 `path` 兜底 schema-validated args 形态,防御性,零行为变化)。`grep` 源字段从 `args?.glob` 改
`args?.include ?? args?.glob`(schema 字段是 `include`,承 schema 诚实)。

### D10 — 写/删侧 recipe 文案(D8 同款,写与删分措辞)

写侧命中 → stderr recipe:
```
blocked: <write|delete|redirect|apply_patch|multiedit|notebookedit> outside the MGH_TARGET tree
  in <domain> run-domain: <path/tool>
  target tree = <target>
  Writes/Moves/Copies MUST land inside the target tree. Use the producer's stdout path
  (checkpoint_path / rule_path / draft_path — already absolute, inside <target>/.mgh-init |
  .claude/rules | docs/security-controls | .mgh-ut-init | docs/test-conventions for init/ut-init).
  NEVER Bash Set-Content / New-Item / tee / > redirect outside the tree; NEVER apply_patch /
  MultiEdit / NotebookEdit outside the tree.
```
删侧命中(`_DELETE_VERBS` / apply_patch delete 操作)追加:「**删除不可逆**;NEVER Remove-Item / del / rm /
rmtree outside the target tree, including sibling modules.」

## Risks / Trade-offs

- **[误伤合法树内写/删]** → 写/删只判「在 target 子树内」(sast/sra/srr)+ init/ut-init 受信子树(D5);
  target 缺失降级放行。正常 fan-out(产出者 stdout 绝对路径)不受影响。cwd 默认锚点(D4)正常 cwd=target
  不误伤。
- **[Bash 写/删复杂形态未穷尽]**(D7 Non-Goal)→ 守卫只扫「显式绝对路径 token + cwd 默认锚点」;管道/alias/
  env 注入路径、`.NET` 静态方法、`robocopy`/`fsutil` 不保证覆盖。承 regex-over-observed-shape;观察到新
  真实逃逸再补。
- **[Copy/Move 目标 token 误判]**(D2)→ 取末绝对路径为目标;`Copy-Item a b c D:\out\` 多目标形态取末(一般
  正确);罕见多目标越界形态可能漏(承非穷尽)。
- **[重定向泛化误伤]**(D3)→ `> out.txt`(相对,cwd 在树内)放行;只有越树绝对路径才拦。`2>` stderr 重定向
  若指向越树绝对路径亦拦(保守,可接受)。
- **[apply_patch 标记解析依赖 opencode 格式]**(D7)→ 仅认 `*** (Add|Update|Delete) File:` / `*** Move to:`
  (opencode `patch.ts` 定义);若 opencode 改格式需同步(承版本耦合;parity 测覆盖)。
- **[规则 a 重标改变既有内省行为]**(L1/D8)→ 纯越树写 `py -c "os.makedirs('D:/out')"` 此前放行,现拦
  (**预期收紧**);合法内省(`import json; load(` 读 `.json`)仍走内省 recipe(行为不变)。回归测覆盖两类。
- **[回归测需同步]** → `test_bash_write_edit_read_glob_grep_handled` 扩(apply_patch);forbidden-token /
  new-logic-marker 列表加 `_WRITE_VERBS`/`_DELETE_VERBS`/`_out_of_tree_mutation`/`_REDIRECT_RX`/
  `_PYC_WRITE_TOKENS`/`ApplyPatch`;新增写/删/重定向/工具面用例。CI 必过(R5.8)。
- **[提示词护栏]** → 写侧 recipe 下沉到编排器 fragment(stage prompt「写产物」段),但 hook 是确定性兜底,
  提示词是正引导、非唯一防线(承 R5.5①)。

## Migration Plan

1. 守卫 `.py`(双端 byte-identical)加写/删侧:`_WRITE_VERBS`/`_DELETE_VERBS`/`_MUTATION_VERB_RX`/
   `_out_of_tree_mutation` + `_REDIRECT_RX`(泛化重定向)+ D5 树内正向清单(Bash 侧)+ `MultiEdit`/
   `NotebookEdit` 入元组(D6)+ `ApplyPatch` 分支(D7)+ 规则 a 重标(D8)+ `_write_recipe`;版本号 bump。
2. opencode shim `HANDLED` + `normalize` 扩(apply_patch + arg-name fallback,D7/D9);parity 测改 + 加用例。
3. 把改后的 claude 侧 `.py` **逐字节**复制到 opencode 侧;跑 `TestGuardByteParity`。
4. spec delta(ADDED Requirements)+ 契约 md + AGENTS.md R5.7 段 B 措辞;`openspec validate --strict`。
5. 回归测 + install 自检。
- **回滚**:写/删侧分支是新增(不改读侧);回滚 = 还原 `.py`/`.ts`/测/契约。无数据迁移、无产物 schema 破坏。

## Open Questions

- D7 `.NET` 静态方法 / `robocopy`/`fsutil` 写逃逸:观察真实失败后再补?(当前:否,承非穷尽。)
- D2 Copy/Move 多目标形态:是否需更精确的目标 token 解析?(当前:取末,承非穷尽。)
- `2>`/`&>` stderr/stdout 合并重定向越树:是否纳入 D3?(当前:`>>?` 覆盖 stdout/stderr `>`/`>>`;
  `&>` 合并形态暂不覆盖,承非穷尽。)
- apply_patch `*** Move to:` 是否等同写(move = 源删 + 目标写)?(当前:是,目标路径走越树 + 受信子树判。)
