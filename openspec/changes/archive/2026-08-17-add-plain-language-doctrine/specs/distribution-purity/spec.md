## MODIFIED Requirements

### Requirement: Shipped md artifacts are free of dev-only provenance and dangling references

Shipped md artifacts MUST be free of dev-only provenance and dangling references.

经 `install.sh` 装入目标项目的所有 md 工具产物(命令壳、agent 定义、subagent stage
提示词、I/O 契约、skills、**面向人类的命令 man 说明**)MUST NOT 携带任何只在本仓研发语境
才有意义的引用。在业务项目环境这些是**悬空指针**——浪费 token,且目标项目常有自带
`AGENTS.md` / 无关编号,会误导 subagent。被禁类别 SHALL 覆盖(经 6-agent 全量审计确认的完整清单):

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

本约束的「shipped md」文件集 SHALL 与 `install.sh` 实际拷贝的 source globs 同源(命令壳 /
agents / skills / `core/prompts/**` / `core/contracts/**` / **`docs/man/**`**),二者不得漂移。
脚本 `.py`、`AGENTS.md` 本身、`openspec/**` SHALL NOT 在本约束范围内。

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
- **THEN** 该溯源注释可保留(脚本只被执行,注释面向本仓维护者),不在约束范围

#### Scenario: Man page is shipped and scanned

- **WHEN** `docs/man/<cmd>.md` 经 `install.sh` 分发到目标项目
- **THEN** 它属于 shipped md 文件集,SHALL 被 `check_distributed_purity.py` 扫描;人话措辞自然规避悬空引用,但仍受本 lint 兜底
