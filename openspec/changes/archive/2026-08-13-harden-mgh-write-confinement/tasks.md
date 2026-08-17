# Tasks — harden-mgh-write-confinement

> 写/删/工具面变更侧确定性兜底:运行域内 Bash 写/删动词、非 temp 重定向、解释器间接写/删的越树目标 →
> fail-loud(退出码 2)+ 写/删 recipe;claude `MultiEdit`/`NotebookEdit` + opencode `apply_patch` 入变更分支。
> 守卫双端 byte-identical;opencode shim 仅扩 `HANDLED`/`normalize`(apply_patch patchText 标记提取为 glue;
> 判定单一来源仍在 `.py`)。承 `harden-mgh-read-confinement`(读侧已闭环)的对称缺口。

## 1. 守卫写/删侧分支:Bash 写/删动词集(W1+W3)

- [x] 1.1 `releases/claude-code/hooks/block_adhoc_scripts.py`:新增 `_WRITE_VERBS`(`New-Item`/`ni`/
  `Set-Content`/`sc`/`Add-Content`/`ac`/`Out-File`/`tee`/`mkdir`/`md`/`Copy-Item`/`cpi`/`cp`/`copy`/`xcopy`/
  `Move-Item`/`mi`/`mv`/`rename`/`Rename-Item`)+ `_DELETE_VERBS`(`Remove-Item`/`ri`/`del`/`erase`/`rm`/`rmdir`/
  `rd`,破坏性单独集)。
- [x] 1.2 新增 `_MUTATION_VERB_RX`(逐字镜像 `_FILE_SEARCH_VERB_RX`,group(1)=命中动词,据此选写/删 recipe)
  + `_out_of_tree_mutation(command, target, cwd, verb) -> tuple[bool, str]`(返回 `(<命中>, <写|删>)`):
  动词命中 → 扫所有显式绝对路径 token(`_ABS_PATH_TOKEN_RX`),Copy/Move 取**末** token(目标)判越树,
  单路径动词任意越树 token 即 True;无显式绝对路径 → D4 cwd 默认锚点(`cwd.is_relative_to(target)`
  False → True);target 缺失 → False(降级)。
- [x] 1.3 `main()` Bash 分支:在既有 Bash 规则之后(文件搜索 D9 之后)调 `_out_of_tree_mutation`,命中写 →
  stderr `_write_recipe` + `return 2`;命中删 → `_write_recipe`(delete 措辞段)+ `return 2`。
  operand-vs-arg:非写/删动词命令不进此分支。

## 2. 守卫重定向泛化(W2)

- [x] 2.1 新增 `_REDIRECT_RX = re.compile(r'>>?\s*"?'?'?([^\s;"\'&|]+)')` 捕获任意 `>`/`>>` 重定向目标
  (非仅 temp 前缀)。`_TEMP_WRITE_RX`/`_detect_temp_io` **保留**(temp 读回独立防御)。
- [x] 2.2 `main()` Bash 分支:扫 `_REDIRECT_RX`,对捕获目标 `resolve()` + 越树判定(`_is_out_of_tree`)+
  init/ut-init 正向清单(D5 `_allowlist_write_blocked`),越树 / 非受信子树 → `_write_recipe` + `return 2`。
  temp 目标仍由 `_detect_temp_io` 先判(顺序:temp-I/O 先 → 重定向后,避免 recipe 错配)。

## 3. 守卫树内 Bash 写正向清单(P1,init/ut-init)

- [x] 3.1 init/ut-init 域,Bash 写动词/重定向目标即便在树内,**也**判 `_ALLOWLIST_SUBTREES`(复用
  `_allowlist_write_blocked`,镜像 Write/Edit 工具层):`Set-Content <target>\evil.txt`(根污染)→ 拦。
  sast/sra/srr 只判越树(无正向清单,同 Write/Edit 工具层)。在 1.3 / 2.2 命中后、放行前补此判。

## 4. 守卫工具抽象面:claude MultiEdit / NotebookEdit(T2+T3)

- [x] 4.1 `main()` 的 `elif tool in ("Write", "Edit"):` 扩为 `elif tool in ("Write", "Edit", "MultiEdit",
  "NotebookEdit"):`。路径提取 `path = ti.get("file_path") or ti.get("notebook_path") or ti.get("path") or ""`
  (MultiEdit=`file_path`,NotebookEdit=`notebook_path`)。后续 `_is_blocked_script_write` + 越树 + 正向清单
  逐字复用。`.ipynb` **不**入 `_SCRIPT_EXTS`(notebook 非运行时脚本)。

## 5. 守卫工具抽象面:opencode apply_patch(T1)

- [x] 5.1 守卫新增 `elif tool == "ApplyPatch":` 分支:`tool_input.paths[]` 每个 + `tool_input.operations[]`
  (add/update/delete/move,对齐标记),对**每个**路径跑 `_is_blocked_script_write`(add/update 脚本扩展名)+
  越树判定 + init/ut-init 正向清单;delete 操作走删侧 recipe 措辞;**任意一个**路径命中 → fail-loud +
  `return 2`。
- [x] 5.2 patchText 标记解析函数(若放守卫侧,只做 `*** (Add|Update|Delete) File: <path>` / `*** Move to:
  <path>` 行提取;**或**全留 shim `normalize`,守卫只吃 `paths[]`——见任务 7.2 取舍,二选一,默认 shim 提取)。

## 6. 守卫规则 a 写形态重标(L1)

- [x] 6.1 `_PYC_RX` 命中后,重构判定顺序:**先**扫命令是否含越树绝对路径 token(`_ABS_PATH_TOKEN_RX`
  resolve 越树)+ 写 token(`_PYC_WRITE_TOKENS = {makedirs, write(, write_text, write_bytes, shutil.copy,
  shutil.move, shutil.rmtree, os.replace, os.rename, os.remove, os.unlink}`)→ 写侧 recipe;**再**判内省
  token(`import json`/`load(` 读 `.json`)→ 内省 recipe;均无 → 放行。
- [x] 6.2 消除「内省 recipe 误导写」:`py -c "open('D:/out/f','w').write('x')"` 走写侧 recipe(非内省);
  `py -c "import os; os.makedirs('D:/out/d')"`(无内省 token)现由越树扫描拦(此前漏)。合法内省
  (`import json; load(` 读 `.json`)仍内省 recipe(行为不变)。

## 7. 守卫公共:recipe + 文档 + 版本

- [x] 7.1 写侧 recipe 函数 `_write_recipe(domain, target, kind)`(`kind=write|delete`):写措辞指向「用产出者
  stdout `checkpoint_path`/`rule_path`/`draft_path` 绝对路径;NEVER Bash `Set-Content`/`New-Item`/`tee`/`>`
  越树;NEVER `apply_patch`/`MultiEdit`/`NotebookEdit` 越树」;删措辞追加「删除不可逆;NEVER
  `Remove-Item`/`del`/`rm`/`rmtree` 越树含兄弟模块」。工具抽象命中(D6/D7)与 Bash 命中(D1-D3)共用。
- [x] 7.2 模块 docstring + 顶部「Blocks the real-world failure shapes」清单补写/删侧(失败形态:越树写/删
  via Bash + 越树重定向 + MultiEdit/NotebookEdit/apply_patch 越树 + 规则 a 写重标)。
- [x] 7.3 守卫版本号 bump(若文件头有版本标记;否则记入 install 自检受影响清单,R5.8)。
  > **落地说明**:守卫 `.py` 文件头**无**版本标记(install.sh 自检仅做脚本共存 + 分布纯净性,
  > 无版本号字段);R5.8 由回归测(157 + 38 用例)+ `TestGuardByteParity`(双端 byte-identical)
  > + `check_distributed_purity.py` 兜底,而非版本号戳。

## 8. 守卫双端 byte-parity

- [x] 8.1 把改后的 `releases/claude-code/hooks/block_adhoc_scripts.py` **逐字节**复制到
  `releases/opencode/hooks/block_adhoc_scripts.py`(单一真相源 = claude 侧;opencode twin 仅镜像)。
- [x] 8.2 跑 `py tests/test_opencode_hook_parity.py::TestGuardByteParity` 确认双端 byte-identical。

## 9. opencode shim 扩 apply_patch + arg-name 防御性(glue-only)

- [x] 9.1 `releases/opencode/plugins/block_adhoc_scripts.ts`:`HANDLED` 加 `apply_patch`(集合从
  `{bash,write,edit,read,glob,grep}` 扩到含 `apply_patch`)。
- [x] 9.2 `normalize()` 加 `apply_patch` 分支:从 `args?.patchText` 解析所有 `*** (Add|Update|Delete) File:
  <path>` / `*** Move to: <path>` 标记行(opencode `packages/core/src/patch.ts:35-51` 格式),透传
  `{tool_name:"ApplyPatch", tool_input:{paths:[...], operations:[...]}}`。**标记提取是 glue,不含越树/
  扩展名判定**(forbidden-token 测覆盖)。
- [x] 9.3 防御性(D9):`edit`/`write`/`read` 的 fallback 链 `args?.filePath ?? args?.file_path` 扩加
  `?? args?.path`(opencode schema 字段是 `path`);`grep` 源字段 `args?.glob` 改 `args?.include ?? args?.glob`
  (schema 字段是 `include`)。零行为变化(防御 schema-validated args 形态)。

## 10. spec + 契约文档 + AGENTS.md

- [x] 10.1 `openspec/specs/runtime-hook-enforcement/spec.md`:本 change 的 delta 已在
  `specs/runtime-hook-enforcement/spec.md`(ADDED 七条 requirement:Bash 写动词 / Bash 删动词 / 重定向 /
  树内 Bash 写正向清单 / MultiEdit+NotebookEdit / apply_patch / arg-name 防御);apply 时合并入主 spec
  (由 opsx:apply / archive 处理,本任务仅确认 delta 完整)。
- [x] 10.2 `core/contracts/hooks/runtime-enforcement.md`:补「写/删侧越树拦截」段(写/删动词集 + 越树 token
  扫描 + cwd 默认锚点 + 重定向泛化 + 树内正向清单 + MultiEdit/NotebookEdit/apply_patch 工具面表 + 规则 a
  写重标 + target 缺失降级 + recipe 文案);「Runtime I/O discipline」表加写/删侧行。
- [x] 10.3 `AGENTS.md` R5.7 段 B:更新「写侧 Bash 逃逸 + 工具面缺口(MultiEdit/NotebookEdit/apply_patch)
  已闭环」措辞(承 R3 精炼;不复制规则条文;改既有「write-side Bash escape gap 待 harden-mgh-write-
  confinement」注为「已落地」)。

## 11. 回归测 + parity 测(写/删/工具面用例)

- [x] 11.1 `tests/test_block_adhoc_scripts.py`:新增 `TestWriteSideConfinement` ——
  - **W1 写动词**:`Set-Content`/`New-Item`/`mkdir`/`Out-File`/`tee`/`Add-Content` 越树拦;`Copy-Item`/`Move-Item`
    目标越树拦(源在树内仍拦目标);`Set-Content`(cwd=parent)D4 越树拦;in-tree 受信子树放行;
    `py … --out x.json` 非写动词不误伤;
  - **W3 删动词**:`Remove-Item D:\parent\sonB -Recurse -Force` 越树拦(删侧 recipe 措辞);`rm -rf D:\out` 拦;
    `py -c "shutil.rmtree('D:/out')"` 拦(规则 a 写 token + 越树);
  - **W2 重定向**:`echo x > D:\out\f.json` 越树拦;`>>` 拦;`> <target>\evil.txt` init 根污染拦(P1);
    `> <target>\.mgh-init\report\out.json` 受信子树放行;temp 读回仍由 `_detect_temp_io` 拦;
  - **P1 树内 Bash 写**:`Set-Content <target>\evil.txt` init 拦;`<target>\.mgh-init\…` 放行;sast 域树内放行;
  - **T2/T3 工具面**:`MultiEdit file_path=D:\out\f` 拦;`NotebookEdit notebook_path=D:\out\nb.ipynb` 拦;
    in-tree 受信子树放行;
  - **L1 规则 a 重标**:`py -c "open('D:/out/f','w').write('x')"` 写侧 recipe(非内省);`py -c "import json;
    json.load(open('x.json'))"` 仍内省 recipe(行为不变);
  - **降级 / 静默**:target 缺失写侧降级放行;非 active 域静默放行。
- [x] 11.2 `tests/test_opencode_hook_parity.py`:
  - 改 `test_bash_write_edit_read_glob_grep_handled`(或新 `test_*_apply_patch_handled`):assert `HANDLED`
    含 `apply_patch`;`normalize` 覆盖 `apply_patch`(patchText 标记提取);
  - `test_shim_exists_and_is_glue_only` 的 forbidden-token 列表加 `_WRITE_VERBS`/`_DELETE_VERBS`/
    `_out_of_tree_mutation`/`_REDIRECT_RX`/`_PYC_WRITE_TOKENS`/`ApplyPatch`(守卫侧符号禁现 shim);
  - `test_both_guards_embed_new_sentinel_logic` 的 marker 列表加同款写侧符号;
  - 新增 opencode apply_patch parity 用例(patchText 含越树 add/delete → 经 normalize → 守卫同决策 exit 2;
    in-tree patch 放行);arg-name `path` fallback 用例(write 带 `path` 字段越树 → 拦,非空 filePath 退化)。
- [x] 11.3 跑全量回归:`py tests/test_block_adhoc_scripts.py` + `py tests/test_opencode_hook_parity.py` +
  `py tests/test_deterministic.py`(确保守卫改动未破坏既有读侧/写侧工具层契约)。

## 12. 验收 + install 自检

- [x] 12.1 `openspec validate harden-mgh-write-confinement --strict`(spec delta 合法,已过初验)。
- [x] 12.2 `tools/check_contracts.py` + `tools/check_distributed_purity.py`(写侧 recipe 措辞无 dev-meta
  漏出;命令壳调用契约未变)。
- [x] 12.3 `tools/measure_prompts.py` / prompt-budget lint(若改编排器 fragment 的写侧 recipe 段,token 不超
  R5.6 上限)。
- [x] 12.4 install 自检(`install.sh --claude .` 干跑或受控目标)确认 hook `.py`/`.ts` 同目录共存 + 写/删/
  工具面逻辑随 install 落目标仓;版本号 bump 反映在 install 自检(R5.8)。
- [x] 12.5 手测(可选,真机):init 域 + `MGH_TARGET=D:\parent\sonA`,触发 `Set-Content`/`Remove-Item`/
  `echo > D:\out`/`apply_patch`(opencode)/`MultiEdit`/`NotebookEdit` 越树 → 确认 fail-loud + recipe(非静默)。
  > **落地说明**:真机手测为可选项;CI 可测的等价覆盖已由 `TestWriteSideConfinement` 全用例
  > (W1/W3/W2/P1/T2/T3/L1/降级/静默)对**装好的守卫**逐条 subprocess 实跑验证(见 12.4 干跑:
  > 装好的 `.claude/hooks/block_adhoc_scripts.py` 对 Set-Content/Remove-Item/redirect/MultiEdit/
  > ApplyPatch 越树全部 exit 2)。opencode 真机 `apply_patch`(Bun 运行时)留待 opencode 会话手测。
