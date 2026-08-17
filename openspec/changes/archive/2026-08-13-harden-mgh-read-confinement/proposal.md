## Why

`/mgh-init`(及其余 `mgh-*`)运行时的读侧**未受限**:`block_adhoc_scripts` 守卫只拦
`Bash`/`Write`/`Edit`,对 `Read`/`Glob`/`Grep` 在活跃运行域内**无条件放行**。当工作目录是某
parent 仓的子模块(如 `D:\parent\sonA`,同级还有 `sonB`)时,隔离的 scout subagent(及其余 reader
tier)偶尔 `Read`/`Glob` 上级 `D:\parent\` 或兄弟 `D:\parent\sonB\` 的文件——命中宿主权限询问,
**任务被中断**。这是**确定性兜底缺口**:写侧有三层硬约束(`_SCRIPT_EXTS` + 越树写 + 受信子树正向清单),
读侧却**完全靠提示词自觉**(stage prompt 的 `Read / Glob / Grep freely` + subagent 约束)。提示词是
概率性约束,会随上下文压缩丢失、被弱模型忽略、或被「Glob 兄弟包确认 fan_in」这类合法读诱惑带偏——故
**周期性复发**。历史类似修复(写侧 allowlist、`MGH_TARGET` 子树判定)只补了写侧,读侧缺口仍在。需把读侧
也下沉为 hook 确定性兜底:运行域内 `Read`/`Glob`/`Grep` 越出 `MGH_TARGET` 子树 → fail-loud(退出码 2)+ recipe,
让流程稳定只在工作目录读写查。

## What Changes

- **读侧确定性兜底**(核心):`block_adhoc_scripts.py` 在活跃运行域内**新增对 `Read`/`Glob`/`Grep` 的越树
  拦截**——目标路径(或 Glob/Grep 的 path/glob 模式锚点根)解析后落在已解析 `MGH_TARGET` 子树**外** →
  退出码 2 + stderr recipe 指向「只在本批 `targets[]`/`input_path` 内读」。复用既有 `_resolve_target`(
  env `MGH_TARGET` > 哨兵.`target` > degrade)与 `_is_out_of_tree` 同款判定;**target 缺失时降级放行**
  (与写侧一致,避 over-block)。
- **Bash 文件搜索命令越界拦截**(堵逃逸):agent 可在 `Bash` 里直接跑 `rg`/`grep`/`findstr`/`find`/`fd`/
  `ag`/`ack` 绕过 Grep 工具抽象(opencode/claude 的 Grep 工具底层即 ripgrep,已被读侧 `path` 锚点覆盖;
  此条治「直接命令」形态)。守卫 Bash 分支新增文件搜索动词集命中检测 + 显式绝对路径 token 越界扫描
  + cwd 默认锚点(D4 同款)判定,命中 fail-loud。承 regex-over-observed-shape、不穷尽管道/alias/env 注入形态。
- **opencode 双端 parity**:`block_adhoc_scripts.ts` 的 `HANDLED` 集合从 `{bash,write,edit}` 扩到
  `{bash,write,edit,read,glob,grep}`,`normalize` 补 read/glob/grep 的 `tool_input`(file_path / path /
  pattern / glob / path 透传)。判定逻辑单一来源仍在 `.py`(`.ts` 仅 glue)。
- **subagent 路径绝对化加固**:`list_scout_batches.py`(及 init 其余 `list_*`)的 `pending[]` 每项
  `targets[]` 的 `file` 字段**MUST** 是相对 `MGH_TARGET` 的解析为绝对路径(或显式 `repo_relative`+编排器
  透传绝对根),消除「subagent 拿到相对路径、cwd 漂移到 parent、解析到上级」的歧义(承 R5.3(b) 扇出路径
  绝对化,但读侧此前未对 `targets[].file` 做绝对化校验)。
- **提示词护栏对齐**(读侧 recipe 下沉):各 reader stage prompt(`init-scout`/`init-survey`/`init-induct`
  及 ut 对应 reader)的「`Read / Glob / Grep freely`」措辞 **改写为有界 recipe**——「只 `Read` 本批
  `input_path`/`targets[]` 与其文件;`Glob`/`Grep` 的 path **MUST** 落在 repo 根;NEVER 读 repo 根上层、
  NEVER 读兄弟模块」,并告知 hook 会确定性兜底。删 `freely` 词(它诱导越界)。
- **第 6 条 hook 规则入 spec**:`runtime-hook-enforcement` spec 新增「读侧越树拦截」requirement + 场景;
  契约 `core/contracts/hooks/runtime-enforcement.md` 补读侧表;`tests/test_block_adhoc_scripts.py` +
  `tests/test_opencode_hook_parity.py` 扩读侧用例(含 parent/sonA/sonB 子模块形态)。

## Capabilities

### New Capabilities
<!-- 无新能力;读侧兜底是既有守卫职责的扩展。 -->

### Modified Capabilities
- `runtime-hook-enforcement`: 新增「读侧越树拦截」requirement——活跃运行域内 `Read`/`Glob`/`Grep` 的目标/锚点
  路径解析落在 `MGH_TARGET` 子树外 SHALL fail-loud(退出码 2)+ recipe;opencode shim `HANDLED` 集合与
  `normalize` 扩到读侧工具;target 缺失降级放行(与写侧一致);哨兵 `target` 字段作为读侧子树判定来源
  (承 env > 哨兵 > degrade 既有优先级)。

## Impact

- **Affected code**:
  - `releases/claude-code/hooks/block_adhoc_scripts.py` + `releases/opencode/hooks/block_adhoc_scripts.py`
    (双端 byte-identical):`main()` 新增 `Read`/`Glob`/`Grep` 分支 + 读侧越树判定函数
    (复用 `_resolve_target`/`_is_out_of_tree`);读侧 recipe 文案。
  - `releases/opencode/plugins/block_adhoc_scripts.ts`:`HANDLED` 加 `read`/`glob`/`grep`;`normalize` 扩。
  - `core/scripts/list_scout_batches.py` (+ init 其余 `list_*` reader 枚举脚本):
    `pending[].targets[].file` 绝对化(或 repo_relative + 显式 repo 根字段)。
  - `core/prompts/stages/init-{scout,survey,induct}.md` + ut 对应 reader:读侧 `freely` → 有界 recipe。
  - `core/contracts/hooks/runtime-enforcement.md`:补读侧规则表。
  - `openspec/specs/runtime-hook-enforcement/spec.md`:新增读侧 requirement(delta)。
  - `tests/test_block_adhoc_scripts.py` + `tests/test_opencode_hook_parity.py`:读侧用例
    (parent/sonA/sonB 子模块、target 缺失降级、in-tree 放行)。
- **影响面**:
  - 五命令(init/sast/sra/srr/ut-init)调用方:读侧收紧为「只读 target 子树」——**这是预期行为收紧**,
    正常 fan-out(reader 只读本批 target + repo 内 Grep/Glob)不受影响;越界读被确定性拦截。
  - 目标项目子模块场景:`D:\parent\sonA` 跑 `/mgh-init`,读 `D:\parent\sonB`/`D:\parent` 被 fail-loud
    (此前 = 权限询问中断)。
  - install/CI:hook `.ts` 与 `.py` 随 install 落目标仓,版本号 bump(R5.8);回归测覆盖读侧 parity。
- **无**第三方依赖(纯 stdlib + 既有 hook 机制);**无**数据迁移(读侧无新产物);**无**写入面变化
  (写侧三层约束不动)。`codegraph` MCP 读侧**不在** hook 拦截面(MCP 工具非 `Read`/`Glob`/`Grep`,
  其越界读由既有「`codegraph=on` 仅覆盖索引语言 + 回退 Read 受限」提示词约束)。
