> **人话序** 守卫现在拦 Bash 命令的思路是「先认出危险动词，再查它的路径」：五张动词表（搜索/写/删/列目录/解释器）之外的动作，哪怕带着项目外的路径也直接放行——`robocopy`、`curl -o`、`cat` 别的项目文件今天都拦不住，每发现一个新逃逸就得再补一个词。根因是黑名单追不上逃逸面，而 mgh-* 干活的位置其实很明确：目标项目加少数几个外部只读目录。本次把 Bash 面反转成白名单：命令里出现的任何路径，解析后不在允许集（目标项目 + 已声明外部只读目录 + 新增项目配置 `.mgh/read-roots.json`）内就拦，与动词无关；原动词表降级为补充手段（区分写/删提示、补相对路径覆盖）。外部只读目录新增项目级配置文件，只读、永不可写。验证：单测新增未知动词、配置合并、坏配置不放大权限等用例；双端同一守卫文件，parity 测试不变。

## Why

- 守卫的 Bash 面是**动词枚举触发**的路径判定：五张手维护的动词表（`_FILE_SEARCH_VERBS`/`_WRITE_VERBS`/`_DELETE_VERBS`/`_LISTING_VERBS`/`_INTERPRETERS`）先认动词，命中才检查其路径 token。每条 Bash 规则都自带「regex-over-observed-shape、不保证穷尽」免责——表外动词携带树外路径**直接放行**。已可复演的漏过形状：`robocopy <in-tree> <盘外备份>`、`curl -o <盘外路径> …`、`[IO.File]::WriteAllText('盘外','…')`、`Get-Content <树外任意文件>`、`Expand-Archive -DestinationPath <盘外>`。
- 历史修法是**每发现一个逃逸加一个词**（写侧 Bash 直写 → `harden-mgh-write-confinement`；opencode `apply_patch` 全绕过 → 同 change 补），维护成本线性涨且永远有下一个词。
- 模型错位：工具面（Write/Edit/Read/Glob/Grep）**早已是允许集模型**（target 树、init/ut-init 受信子树、`read_roots[]`），只有 Bash 面是黑名单。产品事实上 mgh-* 的合法工作集是封闭的——target 树 + 极少数外部只读根——天然适合白名单。

## What Changes

- **Bash 面反转为路径允许集判定**：任何 `Bash` 命令中出现的绝对路径 / `..` 引导 / `~` 引导 token，解析后不在读允许集内 → 拦（退出码 2 + recipe），**与动词无关**。无路径 token 的命令不受影响。
- **读允许集统一为三源并集**：`MGH_TARGET` 树 ∪ 激活文件 `read_roots[]` ∪ 新增项目配置文件 `read_roots[]`。工具面与 Bash 面同集——**语义反转**：推翻既有 spec 显式决定的「`read_roots[]` NEVER 成为 Bash 可搜索位置」（当时 Bash 面无路径判定，外部根只开放给 Read/Glob/Grep；反转后「凡允许读的目录，用什么工具读都放行」，写侧仍判 target 不变）。
- **新增项目级只读配置 `<target>/.mgh/read-roots.json`**（schema `{"v":1,"read_roots":["<abs>…"]}`）：全部六个 mgh 域生效；条目只读、永不可写；fail-closed（条目不存在/非目录 = 零授权；文件损坏 = 零授权且不崩溃）；手工可编辑，缺文件 = 行为不变。
- **写侧强度不变**：写/删/重定向仍判 `MGH_TARGET`（init/ut-init 另加受信子树正向清单）；已声明的只读外部根 NEVER 变为可写位置。
- **降级策略不变**：守卫激活但未钉 target 时，路径判定放行（脚本扩展名写、`py -c` 内省等其余规则照旧）；非 mgh 会话零噪声不变。
- **动词规则保留为精化层**，不删除：提供写/删区分措辞、cwd 漂移覆盖（无显式路径时）、init/ut-init 树内根污染（P1）；全量 token 判定作为结构性最后防线垫在其后。
- 非目标（明确不做）：不动 `py -c` 内省 token 表 / temp 目录模式 / 聚合文件名清单（行为纪律，非路径范畴）；不给 sast/sra/srr/sdr 写侧升正向受信子树清单；守卫不引入交互确认或黑名单豁免机制；零 pip 依赖不变。

## Capabilities

### New Capabilities

<!-- 无。Bash 面反转与配置文件都是 runtime-hook-enforcement 既有能力的要求级变更。 -->

### Modified Capabilities

- `runtime-hook-enforcement`: ① 新增「Bash 路径 token 全量允许集判定」（与动词无关的 fail-closed 最后防线）；② 新增「项目级 read-roots 配置文件」（位置、schema、全域生效、只读、fail-closed 语义）；③ 修改既有「哨兵 read_roots 只读外部根」要求——只读放宽从仅工具面扩到 Bash 面（写侧、叶脚本源码拦截面维持仅 target）。

## Impact

- **代码**：`releases/claude-code/hooks/block_adhoc_scripts.py` 与 `releases/opencode/hooks/block_adhoc_scripts.py`（字节级 twin，判定逻辑单一来源）新增 token 扫描 + 配置读取；opencode `.ts` shim **不动**（`bash` 事件已在 HANDLED 面）；`tests/test_block_adhoc_scripts.py` 新增判定用例；双端 parity 测试口径不变。
- **契约/文档**：`core/contracts/hooks/runtime-enforcement.md`、`openspec/specs/runtime-hook-enforcement/spec.md`（经本 change 的 delta）、AGENTS.md R5.7 段措辞同步、CHANGELOG/VERSION bump。
- **下游 change**：`add-mgh-sdr-read-root-config`（sdr 审批流 + 配置确定性写脚本）建立在本 change 的配置文件之上；基础层落地后手工编辑配置即生效，sdr 审批流属体验增强、可独立跟进。
- **协调**：当前工作树存在未提交的 mgh-sdr 系列改动触及同一 spec 文件，本 change apply 前需先落或合并现有未提交工作。
