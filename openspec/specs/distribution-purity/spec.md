# distribution-purity Specification

## Purpose

让 `install.sh` 装进目标项目的每一件产物都是**自足**的:目标环境里不存在的东西(研发态编号、
变更夹名、上游文档路径、维护者私有文档区)一律不许被引用,否则目标 agent 会去追一个不存在的
指针。约束由确定性 lint 强制,install 自检 fail-soft、回归测试 fail-loud 闭环。

## Requirements
### Requirement: Shipped artifacts are free of dev-only provenance and dangling references

Shipped artifacts MUST be free of dev-only provenance and dangling references.

经 `install.sh` 装入目标项目的所有工具产物(命令壳、agent 定义、subagent stage
提示词、I/O 契约、skills、运行时脚本与插件)MUST NOT 携带任何只在本仓研发语境才有意义的引用。在业务项目
环境这些是**悬空指针**——浪费 token,且目标项目常有自带 `AGENTS.md` / 无关编号,会误导
subagent。被禁类别 SHALL 覆盖(原 6-agent 全量审计确认的清单 + 后续增补):

1. **研发铁律编号** `R\d`/`R\d.\d`:`R5.2`、`R5.9`、`R5.7`、`R5.4`、`R3`、`R2`、`R1–R4`。
2. **失败/发现 ID** `\bFD\d+\b`:`FD8`、`FD3`、`FD5`、`FD6`。
3. **设计决策 ID** `\bD\d+\b`:`D2`、`D4`、`D5`、`D8`、`D9`、`D12`(含 `D9 = D12` 形态)。
4. **openspec 变更夹名**:`improve-mgh-init-llm-discovery`、`harden-mgh-init-orchestration-discipline`
   等 `(add|fix|harden|improve|purify)-mgh-(init|sast|sra|blst)-…` kebab 名。
5. **内部上游文档引用**:`glasswing_docs/09 §x.x`。
6. **仓根开发态文件指针**:`task.260630.md`(install 不分发,在目标里不存在)。
7. **dev-meta 措辞**:`承 R5.x`、`兑现 R5.x`、`范式锚点`、`本仓`(指本研发仓时)。
8. **上游溯源行话作归因**:`vvah`/`vvaharness`/`design_controls` 当**作谱系归因**使用时
   (与下面「受保护类」的 `Source:` 头 / Apache 归因 / 操作性 schema 匹配区分——后者保留)。
9. **本仓根 `docs/` 指针**:维护者私有文档区的任意内容(命令人话说明、术语词典、上游对照表、
   分析与 review 笔记)。该目录 install **不**拷贝进目标项目,故分发产物里指向它的每一处都是
   死链,且会把目标 agent 引向一个根本不存在的目录。

**豁免面(与第 9 类同形,机器须放行)**:目标项目里由工具**运行时生成**的 `docs/security-controls/`、
`docs/test-conventions/`(mgh-init / mgh-ut-init 的输出目录),以及 `core/docs/NOTICE`、
`core/docs/prompt-provenance.md`(Apache-2.0 归属,随 `core/` 落到 `<dest>/mgh-core/docs/`)。
`core/prompts/**` 是 R1 冻结的逐字移植正文,其正文提及**上游项目**自己的文档布局且不可编辑,
故第 9 类对它豁免。

本约束的「shipped」文件集 SHALL 与 `install.sh` 实际拷贝的 source globs 同源(命令壳 /
agents / skills / `core/prompts/**` / `core/contracts/**` / 运行时脚本 `core/scripts/**` /
`releases/<platform>/hooks/**` / `releases/opencode/plugins/**`),二者不得漂移。**第 9 类对
md 与运行时脚本一律生效;第 1–8 类只对 md 生效**——目标 agent 被要求不读叶子脚本源码(报错只
看 stderr),脚本注释里的规则编号 / 决策 ID 是面向本仓维护者的合法速记,不会误导目标。

**SDD 产物**(`openspec/specs/**` 与 `openspec/changes/**`,已归档的除外)SHALL NOT 出现第 9 类
引用(承 R5.11);第 1–8 类在 SDD 产物里是**合法**的(spec 本就逐条引用规则编号),不在本约束范围。

#### Scenario: Decision-ID parenthetical is a violation

- **WHEN** 某 shipped agent 定义含 `Runs in an ISOLATED context for ONE cluster (D12)`
- **THEN** `(D12)` 决策 ID SHALL 被剥离,隔离语义(`ISOLATED context for ONE cluster`)保留

#### Scenario: openspec change-folder name as provenance is a violation

- **WHEN** 某 shipped stage 提示词含 `Part of improve-mgh-init-llm-discovery:`
- **THEN** 该变更夹名 SHALL 被剥离;其后紧跟的操作性说明(为何该 tier 存在)保留

#### Scenario: Repo-root dev-file pointer is a violation

- **WHEN** 某 shipped 命令壳(mgh-sra/mgh-blst)含 `见 task.260630.md`
- **THEN** 该指针 SHALL 被剥离(`task.260630.md` 不分发,目标里不存在);「TODO 未实现 + 打印参数表」指令保留

#### Scenario: Cross-reference to dev manual is a violation

- **WHEN** 某 shipped 提示词含 `See core/contracts/init/ and AGENTS.md R1–R4`
- **THEN** `AGENTS.md R1–R4` 交叉引用 SHALL 被剥离;`core/contracts/init/`(随 core/ 分发)指针保留(见「Preserve-or-graft」)

#### Scenario: Output-artifact path reference is preserved

- **WHEN** 某 shipped agent 定义含 `never write AGENTS.md directly` 或 `<target>/AGENTS.md`
- **THEN** 这些引用 SHALL 原样保留(指工具输出交付物,非本仓手册),不构成违例

#### Scenario: Script provenance comments are exempt

- **WHEN** `core/scripts/*.py` 或 hook `.py` 注释含 `# hardens R5.2`
- **THEN** 该溯源注释可保留(脚本只被执行,注释面向本仓维护者),不在第 1–8 类约束范围

#### Scenario: Repo-root docs pointer is a violation

- **WHEN** 某 shipped 命令壳含一行「人类读者:通俗说明见 …」指向维护者私有文档区里的命令人话说明
- **THEN** 该指针 SHALL 被整行删除(不是改写——改写后的指针仍是对私有文档区的引用);命令壳其余纪律原样保留

#### Scenario: Script pointer to a dev-only path is a violation

- **WHEN** 某 shipped 运行时脚本注释含 `glasswing_docs/09 §1.3` 或 `Part of improve-mgh-init-llm-discovery`
- **THEN** lint 以退出码 2 报出(第 9 类与变更夹名同为「读者会去跟、会扑空」的指针),注释里的规则编号不受影响

### Requirement: Dangling references resolved by delete-or-graft, never losing operational content

剥离悬空引用 SHALL NOT 丢失操作性内容。每个违例 SHALL 按二选一处理:(a/b) **删除**——
当被引内容在目标生产环境**不需要**(或已在本 shipped 文档他处陈述),删标记/引用句,周边
操作语义原样留;或 (c) **嫁接**——当被引内容是目标 LLM **必需知晓**才能正确行为时,把
**最简**必要内容(1–2 行,token 极省)内联到恰当位置,再删指针。**NEVER** 只删指针而丢
必需内容,也 NEVER 把非必要的长描述整段搬过来(省 token 优先)。

#### Scenario: Operational quote preserved while attribution dropped

- **WHEN** 某 shipped 提示词含 `Skeptic bias mirrors mgh-sast s6 ("assume WRONG until confirmed"):`
- **THEN** 清理后保留 `Skeptic bias — "assume WRONG until confirmed":`(载重内容内联),仅删 `mirrors mgh-sast s6` 悬空指针

#### Scenario: Operational constraint preserved while ticket number dropped

- **WHEN** 某 fragment 含 `Source: …; GitHub issue #11454 (.opencode/AGENTS.md NOT loaded).`
- **THEN** 清理后保留 `(.opencode/AGENTS.md NOT loaded)` 约束,仅删 `GitHub issue #11454` 票号

#### Scenario: Hybrid reference split — keep shipped half, drop dangling half

- **WHEN** 某 shipped 提示词含 `See core/contracts/init/ and AGENTS.md R1–R4`
- **THEN** 保留 `core/contracts/init/`(随 core/ 分发,合法),删 `and AGENTS.md R1–R4`(仓根手册不分发)

#### Scenario: Upstream-jargon framing dropped, operational table body kept

- **WHEN** 某 I/O 契约含 `### vvah alias reuse` 小节及其 alias 映射表
- **THEN** 标题与行标里的 `vvah` 谱系词 SHALL 剥离;alias 映射表体(目标 intake 实际接受的别名)SHALL 原样保留

#### Scenario: Validation instruction retained without the rule tag

- **WHEN** 命令壳原含 `校验(R5.9):py …/discover_controls.py --check …(退出码 2 → 回退)`
- **THEN** 清理后 `--check` 步骤、退出码 2、回退语义全部保留,仅 `(R5.9)` 标记消失

### Requirement: Protected attribution classes are not altered

下列**受保护类** SHALL NOT 被当作 dev-only 溯源剥离——它们是合法的许可证归因 / 操作性
引用 / 真实外部约束:(1) `core/prompts/**` 头部的 `Source: vvaharness/...` Apache-2.0
归因注释(承 R1);(2) skills 里的 Apache-2.0 归因(如 "verbatim port from vvaharness
(Apache-2.0)");(3) `core/docs/prompt-provenance.md`(归因记录本身);(4) `design_controls`
作**操作性**匹配语义使用时(如 sast "Account for design controls");(5) 真实外部约束引用
(如 `CVE-2025-41248`)。第 8 类「上游溯源行话」禁令**仅**命中作谱系归因的 `vvah`/`design_controls`,
MUST NOT 误伤上述受保护类。

#### Scenario: Source header attribution preserved

- **WHEN** 某 sast stage 提示词头部含 `<!-- Ported from vvaharness … Source: vvaharness/… -->`
- **THEN** 该头注释 SHALL 原样保留(R1 / Apache-2.0 归因),不构成违例

#### Scenario: Skill Apache attribution preserved

- **WHEN** 某 sast skill 含 `verbatim port from vvaharness (Apache-2.0)`
- **THEN** 该归因 SHALL 保留(许可证 NOTICE 义务),不构成违例

#### Scenario: Operational design_controls usage preserved

- **WHEN** 某 sast 提示词正文用 `design controls` 描述威胁建模的操作性概念
- **THEN** 该用法 SHALL 保留(非谱系归因,是操作性术语),不构成违例

### Requirement: Distribution purity enforced by a deterministic high-precision lint

SHALL 提供确定性叶脚本 `tools/check_distributed_purity.py`,对 shipped 文件集与 SDD 产物扫描
**高精度**禁用模式(零/低假阳,合法操作性文本不误伤):

- **指针族**(指向目标环境不存在的东西;对 md 与运行时脚本**都**生效):
  - openspec 变更夹名 `\b(add|fix|harden|improve|purify)-mgh-(init|sast|sra|blst|srr|ut-init)-[a-z0-9-]+`
  - 内部上游文档 `glasswing_docs/`
  - 仓根开发态文件 `\btask\.\d+\.md\b`
  - 本仓根 `docs/` 引用(`repo_docs`;按上文「豁免面」三族甄别,并放行上游文档 URL)
- **词汇族**(研发手册的裸编号;仅对 **md** 生效):
  - 规则编号 `\bR\d+(\.\d+)?\b`
  - 失败/发现 ID `\bFD\d+\b`
  - 决策 ID `\bD\d+\b`
  - 本仓手册交叉引用 `AGENTS\.md\s+R\d`
  - dev-meta 措辞 `范式锚点`、`承\s*R\d+(\.\d+)?`、`兑现\s*R\d+(\.\d+)?`

命中任一 SHALL fail-loud(退出码 2)并经 stderr 报具体文件、行号与命中 token;stdout SHALL
输出结构化 JSON 摘要(`{scanned, violations[], allowlisted}`)。`<target>/AGENTS.md`、
runtime 脚本路径 `.claude/mgh-core/scripts/*.py`、操作阶段标签 `T1`/`s1`..`s9`、
`<target>/docs/security-controls/` 与 `core/docs/**` MUST NOT 被误报。

**上游溯源行话**(`vvah`/`vvaharness`/`design_controls` 作归因)SHALL NOT 纳入 lint 硬边界
——因其与受保护的 `Source:` 头 / skill Apache 归因 / 操作性 `design_controls` 同形,机器
难辨,改由提示词护栏 + 人工清理覆盖(design D4)。脚本 SHALL 提供 `--allowlist <file>`
行级例外(默认空)兜底假阳,并遵守 R5.3 稳定性契约(`--help` 即契约、stdout=JSON /
stderr=诊断分流、退出码 `0/1/2`、任意 cwd 可 `py`、`encoding="utf-8"`、零运行时依赖)。

#### Scenario: Lint fails loud on a leaked rule ID

- **WHEN** 某 shipped 命令壳含 `R5.2`,执行 `check_distributed_purity.py`
- **THEN** 脚本以退出码 2 失败,stderr 报该文件与命中 `R5.2`,stdout JSON `violations[]` 含该条

#### Scenario: Lint catches decision-ID and change-folder provenance

- **WHEN** 某 shipped 提示词含 `(D12)` 或 `Part of improve-mgh-init-llm-discovery`
- **THEN** lint 以退出码 2 报这两类(决策 ID / 变更夹名),与规则 ID 同级处理

#### Scenario: Lint preserves operational paths and stage labels

- **WHEN** 某 shipped agent 含 `py .claude/mgh-core/scripts/list_clusters.py` 与 `T1 per-cluster`
- **THEN** lint 不把它们报为违例(runtime 路径与操作阶段标签合法)

#### Scenario: Lint is self-contained and offline

- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/check_distributed_purity.py` 执行
- **THEN** 脚本成功(自定位、utf-8、零第三方依赖),AST 扫描无非标准库 import

#### Scenario: Allowlist suppresses a known false positive

- **WHEN** 未来出现一例合法命中,经 `--allowlist fp.txt` 指向该行
- **THEN** 该行不计入违例,stdout JSON `allowlisted` 反映被豁免条目数

### Requirement: Install self-check and CI regression close the loop

`install.sh` SHALL 在镜像后运行 `check_distributed_purity.py` 作 fail-soft 自检(违例只 warn
到 stderr,不阻断 install;承 R5.8)。CI 回归测试 `tests/test_distributed_md_purity.py` SHALL
以子进程跑该脚本并断言退出码 0;违例 = CI fail。任何 shipped `.md` 改动 SHALL bump 版本号。

#### Scenario: Install warns but proceeds on a violation

- **WHEN** `install.sh` 镜像后 purity 自检发现违例
- **THEN** stderr 打印 warn(非阻断),install 继续完成;CI 测单独必 fail

#### Scenario: CI fails on a shipped-md violation

- **WHEN** 某 PR 在 shipped md 引入 `R5.2` 或 `(D12)`,CI 跑 `test_distributed_md_purity.py`
- **THEN** 该测试以非零退出码失败,阻断合入

