# Proposal — harden-mgh-write-confinement

> **范围(本次 `/opsx:propose` 扩展后):** 对整个**变更面(mutation surface)**做确定性兜底——
> 不只 Bash 写逃逸,还覆盖越树**破坏性删**、非 temp 越树重定向、以及**工具抽象面**的三个未覆盖工具
> (opencode `apply_patch` / claude `MultiEdit` / `NotebookEdit`)。承 `harden-mgh-read-confinement`
> (读侧兜底已落地)的对称缺口审计:读侧工具抽象 + Bash 搜索已闭环,但**写/删侧**与**工具抽象面**
> 仍有 8 个同源缺口(均经真机探测复现 exit=0)。命名沿用 `harden-mgh-write-confinement`(已建立锚点),
> 实际治理「写 + 删 + 工具面变更」整面。

## Why

`block_adhoc_scripts` 守卫的**写侧只覆盖宿主原生 `Write`/`Edit` 工具**(`_SCRIPT_EXTS` + `_is_out_of_tree`
+ init/ut-init 正向清单 `_allowlist_write_blocked`),**Bash 分支**只有 `py -c` 内省 / temp-I/O /
whole-aggregate-read / file-assoc / **文件搜索(读侧 D9)** 五条规则——**没有一条针对「越树写/删路径」**。
且 `Write`/`Edit` 分支只匹配 `tool in ("Write","Edit")`,**遗漏另三个变更工具**。

真机探测(init 域激活 + `MGH_TARGET=D:\parent\sonA`,写 `D:\out\`,**全部 exit 0 放行**):

| #   | 调用形态                                                                 | 缺口类                                               | 退出码   |
| --- | -------------------------------------------------------------------- | ------------------------------------------------- | ----- |
| W1a | `Bash: Set-Content D:\out\f.json x`                                  | Bash 写动词越树                                        | **0** |
| W1b | `Bash: New-Item -ItemType File -Path D:\out\f.json -Force`           | Bash 写动词越树                                        | **0** |
| W1c | `Bash: mkdir D:\out\d` / `md`                                        | Bash 写/建目录越树                                      | **0** |
| W1d | `Bash: Copy-Item x.java D:\out\` / `Move-Item`                       | Bash 复制/移动越树                                      | **0** |
| W1e | `Bash: echo x \| tee D:\out\f.json`                                  | Bash 管道写越树                                        | **0** |
| W2  | `Bash: echo x > D:\out\f.json` / `>>`                                | 非 temp 越树重定向(`_TEMP_WRITE_RX` 只匹配 temp 前缀)        | **0** |
| W3a | `Bash: Remove-Item D:\parent\sonB -Recurse -Force`                   | 越树**破坏性删兄弟模块**(不可逆)                               | **0** |
| W3b | `Bash: py -c "import shutil; shutil.copy('a','D:/out/f')"`           | 解释器间接写(无内省 token,规则 a 漏)                          | **0** |
| W3c | `Bash: py -c "import shutil; shutil.rmtree('D:/out')"`               | 解释器间接**删**(不可逆)                                   | **0** |
| T1  | opencode `apply_patch` `patchText="*** Add File: D:\out\evil.ps1 …"` | opencode 多文件变更工具**完全不在 HANDLED** → 全绕过(含 delete)  | **0** |
| T2  | claude `MultiEdit` `file_path=D:\out\f.json`                         | claude 批量编辑工具不在 `("Write","Edit")` 分支             | **0** |
| T3  | claude `NotebookEdit` `notebook_path=D:\out\nb.ipynb`                | claude notebook 工具不在变更分支                          | **0** |
| P1  | `Bash: Set-Content D:\parent\sonA\evil.txt`                          | **树内** Bash 写**绕过 init 正向清单**(清单只管 Write/Edit 工具) | **0** |
| L1  | `Bash: py -c "open('D:/out/f','w').write('x')"`                      | 规则 a **误命中**(open( + .json)当内省拦,实为写;recipe 误导     | 2(误标) |

**同源同构**:工具抽象规则只覆盖宿主原生工具;Bash 是第二个面,有自己的「文件-I/O 动词」;另三个变更工具
是第三个面。三者共享同一检测模式(**动词集 / 工具 id + 绝对路径 token 扫描 + `is_relative_to(target)` +
cwd 默认锚点**)。`harden-mgh-read-confinement` 的 Non-Goals 明确「不改写侧三层约束」,读侧只闭环了读;
写/删侧与工具面缺口遗留至今,本 change 一次锁紧整个变更面(避免 `apply_patch` 全绕过 / `Remove-Item` 不可逆
删 单独留在生产)。

## What Changes

### Bash 分支:越树写/删/重定向(W1+W2+W3)

- 新增 **Bash 写动词集** `_WRITE_VERBS`(`New-Item`/`ni`/`Set-Content`/`sc`/`Add-Content`/`ac`/`Out-File`/
  `tee`/`mkdir`/`md`/`Copy-Item`/`cpi`/`cp`/`copy`/`xcopy`/`Move-Item`/`mi`/`mv`/`rename`/`Rename-Item`/`ri`)
  + 首动词命中检测(扫命令及 `;`/`|`/`&&`/`||` 后子命令首词,镜像 `_FILE_SEARCH_VERB_RX`)。
- 新增 **Bash 删动词集** `_DELETE_VERBS`(`Remove-Item`/`ri`/`del`/`erase`/`rm`/`rmdir`/`rd`)——破坏性,单独集
  便于 recipe 区分「写」与「删」措辞。
- 命中写/删动词时,**扫命令里所有显式绝对路径 token**(复用 `_ABS_PATH_TOKEN_RX`),逐个 `resolve()`+
  `is_relative_to(target)`,任意越树 → fail-loud;无显式绝对路径 → 走 **D4 cwd 默认锚点**(同读侧)。
- **泛化重定向规则**(W2):`_TEMP_WRITE_RX` 从「仅 temp 前缀」扩为「任意 `>`/`>>` 重定向目标」→ resolve +
  越树判定 + init/ut-init 正向清单;`_detect_temp_io` 的 temp 读回仍是独立防御(保留),但**纯越树重定向**
  不再漏(不再要求 temp 前缀)。Copy/Move 的**目标** token(末绝对路径)单独判越树。
- **树内 Bash 写正向清单**(P1):init/ut-init 域,Bash 写动词/重定向的目标即便在树内,也要落
  `_ALLOWLIST_SUBTREES`(复用 `_allowlist_write_blocked`,镜像 Write/Edit 工具层)——堵「`Set-Content
  <target>\evil.txt` 根污染」绕过清单。
- **规则 a 重标**(L1):`py -c` 写形态(`open(..,'w')`/`write(`/`makedirs`/`shutil.copy`/`shutil.rmtree`/
  `write_text`/`os.replace`)既有内省误命中,现纳入**统一越树判定**(若命令含越树绝对路径 → 写侧 recipe),
  消除「内省 recipe 误导写」;纯内省(`import json`/`load(` 读 `.json`)仍走内省 recipe。
- 解释器间接写/删(W3b/W3c):由「`py -c` 写 token 集 + 越树绝对路径扫描」共同覆盖(不单列规则,复用 W1+W3 扫描)。

### 工具抽象面:三个未覆盖变更工具(T1+T2+T3)

- **claude `MultiEdit`**(T2):`elif` 分支元组 `(Write, Edit)` 扩为 `(Write, Edit, MultiEdit)`;路径字段同
  `file_path`。一行改动,零新检测逻辑。
- **claude `NotebookEdit`**(T3):同上扩元组;路径字段取 `notebook_path`(`ti.get("file_path") or
  ti.get("notebook_path") or ti.get("path")`)。`.ipynb` **不**入 `_SCRIPT_EXTS`(notebook 是产物非运行时脚本)。
- **opencode `apply_patch`**(T1):`.ts` shim `HANDLED` 加 `apply_patch`;`normalize` 新增分支从 `args.patchText`
  解析所有 `*** (Add|Update|Delete|Move to) File: <path>` 标记(opencode patch 格式,`packages/core/src/patch.ts`
  定义)→ 透传给守卫;守卫新增 `ApplyPatch` 分支对**每个**路径跑 `_is_blocked_script_write` + 越树判定 +
  init/ut-init 正向清单。`patchText` 标记解析是 glue 适配(字段提取),判定单一来源仍在 `.py`。

### opencode 双端 parity + 防御性加固

- `.ts` shim `HANDLED` 扩到含 `apply_patch`;`normalize` 加 `apply_patch` 分支(patchText 标记提取)。
- 防御性:`edit`/`write`/`read` 的 `normalize` fallback 链加 `args?.path`(opencode schema 字段是 `path`,
  非 `filePath`;当前靠 LLM 发 camelCase 才对,加 `path` 兜底 schema-validated args 形态)。

### 提示词护栏 + 契约 + 回归测

- 写侧 recipe 下沉:`_write_recipe(domain, target)`(指向「越树写/删/重定向 fail-loud;用产出者 stdout
  `checkpoint_path`/`rule_path`/`draft_path` 绝对路径;NEVER Bash 直接 `Set-Content`/`New-Item`/`Remove-Item`
  越树;NEVER `>` 重定向越树;NEVER `apply_patch`/`MultiEdit`/`NotebookEdit` 越树」)。
- spec delta(`runtime-hook-enforcement`,**ADDED** Requirements)+ 契约 `runtime-enforcement.md` 补写/删侧表;
- `AGENTS.md` R5.7 段 B 更新「写侧 Bash 逃逸 + 工具面缺口已闭环」措辞。
- 回归测 `tests/test_block_adhoc_scripts.py`(W1-W3/P1/L1/T2/T3 全用例)+ `tests/test_opencode_hook_parity.py`
  (apply_patch 经 normalize→守卫同决策;`HANDLED` 扩;forbidden-token / new-logic-marker 加写侧符号;
  arg-name `path` fallback 用例)。

## Capabilities

### New Capabilities
<!-- 无新能力;写/删/工具面兜底是既有守卫职责的扩展。 -->

### Modified Capabilities
- `runtime-hook-enforcement`: 新增「写侧越树拦截」一族 requirement——Bash 写/删动词集越树、非 temp 越树重定向、
  init/ut-init 树内 Bash 写正向清单、claude `MultiEdit`/`NotebookEdit` 入变更分支、opencode `apply_patch`
  patchText 标记解析 + 守卫判定、规则 a 写形态重标。opencode shim `HANDLED`/`normalize` 扩到 `apply_patch`
  + arg-name 防御性 fallback;判定逻辑单一来源仍在 `.py`。

## Impact

- **Affected code**:
  - `releases/claude-code/hooks/block_adhoc_scripts.py` + `releases/opencode/hooks/block_adhoc_scripts.py`
    (双端 byte-identical):`main()` Bash 分支新增写/删动词集 + 越树扫描 + 重定向泛化 + 树内正向清单;
    `Write`/`Edit` 分支元组扩 `MultiEdit`/`NotebookEdit`;新增 `ApplyPatch` 分支 + patchText 标记解析;
    规则 a 写形态重标;`_write_recipe`;版本号 bump。
  - `releases/opencode/plugins/block_adhoc_scripts.ts`:`HANDLED` 加 `apply_patch`;`normalize` 加 apply_patch
    分支(patchText 标记提取)+ `path` fallback。
  - `core/contracts/hooks/runtime-enforcement.md`:补「写/删侧越树拦截」表 + 工具面表。
  - `openspec/specs/runtime-hook-enforcement/spec.md`:新增写/删/工具面 requirement(delta,ADDED)。
  - `tests/test_block_adhoc_scripts.py` + `tests/test_opencode_hook_parity.py`:W1-W3/P1/L1/T2/T3/apply_patch 用例
    (parent/sonA/sonB 子模块、树内根污染、target 缺失降级、非 active 域静默、in-tree 放行)。
  - `AGENTS.md` R5.7 段 B:措辞更新(写/删/工具面缺口闭环)。
- **影响面**:
  - 五命令(init/sast/sra/srr/ut-init)调用方:变更面收紧为「只写/删 target 子树内 + init/ut-init 须落
    受信子树」——**预期行为收紧**;正常 fan-out(产出者 stdout 绝对路径)不受影响;越树写/删被确定性拦截。
  - 目标项目子模块场景:`D:\parent\sonA` 跑 `/mgh-init`,`Set-Content`/`Remove-Item` 写/删 `D:\parent\sonB`
    被 fail-loud(此前 = 静默执行,可能破坏兄弟模块)。
  - opencode `apply_patch` 用户:越树 patch(含 delete)被拦(此前 = 全绕过)。
  - install/CI:hook `.ts` 与 `.py` 随 install 落目标仓,版本号 bump(R5.8);回归测覆盖写/删/工具面 parity。
- **无**第三方依赖(纯 stdlib + 既有 hook 机制);**无**数据迁移(无新产物);读侧三层约束**不动**(读侧已闭环)。
- **诚边界**:本 change 的 Bash 写/删/重定向检测是 **regex-over-observed-shape**——不穷尽所有逃逸形态
  (管道/alias/env-注入路径、PowerShell `.NET` 静态方法 `[System.IO.File]::WriteAllText`、`robocopy`、
  `fsutil` 等未覆盖),与既有 temp-I/O / file-assoc / 读侧 D9 规则同立场;观察到新逃逸形态再补。工具面
  (MultiEdit/NotebookEdit/apply_patch)是确定性工具 id 匹配,覆盖完整(这三个工具的字段已知)。
