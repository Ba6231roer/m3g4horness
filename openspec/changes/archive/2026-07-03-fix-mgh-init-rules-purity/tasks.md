# Tasks — fix-mgh-init-rules-purity

> 实现顺序按依赖:先确定性脚本(可独立测)→ 提示词护栏 + T3 暂存 → fragment 模板 → 契约 →
> 命令壳编排 → manifest → 测试/回归 → 自检。每个任务可独立验证。

## 1. 确定性装配 + lint 脚本 `assemble_rules.py`

- [x] 1.1 新建 `core/scripts/assemble_rules.py`:argparse 契约 `--target/--format/--parts/--out/--check/--dry-run`;`--help` 即唯一契约面(承 R5.1)。
- [x] 1.2 实现装配:读 `<target>/.mgh-init/rules-parts/<category>.md` 全部 fragment → 合并为 `<target>/AGENTS.md` 单个 `<!-- security-controls:begin --> … :end -->` 受管块;块存在则替换、不存在则追加;用户其余内容不动(幂等)。
- [x] 1.3 实现旧块迁移:扫 `<!-- mgh-init:begin` 开头的旧受管块,首次运行清出再写新块,计数记 `migrated_legacy_blocks`(避免孤儿重复)。
- [x] 1.4 实现 `--check` lint:对 opencode 受管块 + claude `.claude/rules/security-*.md` 扫描禁用 token 集(design D4),命中 fail-loud(退出码 2)+ stderr 报文件/位置;裸 `T1`/`T2`/`T3`/`scout` 不入集。
- [x] 1.5 I/O 分流:`stdout`=JSON 摘要 `{format,block,categories[],migrated_legacy_blocks,lint:{ok,violations[]}}`、`stderr`=进度、退出码 `0/1/2`;`--dry-run` 不写盘。
- [x] 1.6 自包含:`sys.path.insert(0, dir-of-__file__)`、`encoding="utf-8"`、任意 cwd 可 `py`、零第三方依赖(承 R5.3/R2)。

## 2. 提示词纯净性护栏 + T3 暂存 fragment

- [x] 2.1 `core/prompts/stages/init-induct.md`:人读字段(`description`/`usage`/`gaps`)加 recipe + `NEVER` 硬边界(禁工具名/脚本名/层级/内部路径/过程描述),无豁免子句(承 R5.5①②③)。
- [x] 2.2 `core/prompts/stages/init-scout.md`、`init-scout-merge.md`、`init-scout-audit.md`、`init-survey.md`:同上护栏(覆盖 `evidence_snippet`/`gaps`/note 类人读字段)。
- [x] 2.3 `core/prompts/stages/init-synthesis.md`:加「综合时剥离残留工具内部引用」职责(T2 防线),保留 `source` 结构字段。
- [x] 2.4 `core/prompts/stages/init-rulewriter.md`:加规则正文纯净护栏(同 2.1);**删除** per-category 哨兵指令 `<!-- mgh-init:begin:<category> -->`;改指令为「写暂存 fragment 到 `<target>/.mgh-init/rules-parts/<category>.md`(opencode,无外层哨兵)」;claude 仍写 `security-<category>.md`。
- [x] 2.5 `core/prompts/stages/init-rules-consistency.md`:明确 T4 **只**做语义一致性(命名/锚点/跨 category 去重),**不**做装配/不碰哨兵(单一职责,design D2)。

## 3. rules-format fragment 模板

- [x] 3.1 `core/prompts/fragments/rules-format-opencode.md`:哨兵改中性 `<!-- security-controls:begin --> … :end -->` 单块;模板收紧到最小形态(category 小节 → 控制名 + 用法 + `file::Class.method` 锚点 + caveat);去 `mgh-init` 字样;声明「T3 写暂存 fragment,`assemble_rules.py` 装配」。
- [x] 3.2 `core/prompts/fragments/rules-format-claude.md`:加规则正文纯净护栏引用(结构/`paths:` 不变)。

## 4. 契约文件

- [x] 4.1 新建 `core/contracts/init/rules-parts.md`:定义暂存 fragment 契约(路径 `<target>/.mgh-init/rules-parts/<category>.md`、中性无外层哨兵、正文语言规则、与 inventory category 的对应)。

## 5. 命令壳编排流(两壳对称)

- [x] 5.1 `releases/opencode/command/mgh-init.md`:T3 步骤改为「写暂存 fragment」;新增「装配」步骤 `py .opencode/mgh-core/scripts/assemble_rules.py --target . --format opencode`;stage→组件表加 `assemble_rules.py` 行;确定性调用示例补 assemble;line 7 编排器声明段补「T3 写 fragment、装配由脚本」。
- [x] 5.2 `releases/claude-code/commands/mgh-init.md`:同 5.1(claude 无装配,但补 `assemble_rules.py --format claude --check` lint 步骤);调用示例镜像脚本 `--help`。
- [x] 5.3 两壳 `description:` / 版本号 bump(承 R5.6/R5.8);`--help`/无参仍打印 flag 表并 STOP。

## 6. install 镜像 + manifest

- [x] 6.1 `install.sh`:`assemble_rules.py` 纳入镜像清单 + 同目录共存自检(fail-soft:自检失败只 warn 不阻断 install,承 R5.8)。
- [x] 6.2 `init_manifest.json` 增字段:`rules_block`(`security-controls`)、`lint:{ok,violations[]}`、`migrated_legacy_blocks`;manifest 文案简体中文(承 rules-emission 现有要求)。

## 7. 测试 + 回归(承 R5.8)

- [x] 7.1 `tests/` 新增 `test_assemble_rules.py`:幂等(连跑两次受管块只一块)、旧块迁移、用户内容保留、`--check` 命中禁用 token fail-loud、裸 `T1` 不误报。
- [x] 7.2 非脚本目录 cwd 子进程调用 `assemble_rules.py` 验导入鲁棒(承 R5.3a)。
- [x] 7.3 AST 零依赖扫描覆盖 `assemble_rules.py`(承 R2)。
- [x] 7.4 `tools/check_contracts.py`:把 `assemble_rules.py --help` 纳入 CLI lint,断言双壳 MD 里 assemble 的 flag 都存在(承 R5.1)。
- [x] 7.5 全量 `py tests/` 绿;`install.sh` 自检通过。

## 8. 自检 + 边界披露

- [x] 8.1 `grep -rnE "mgh-init:begin" core/ releases/` 应无残留(旧品牌哨兵已全清)。
- [x] 8.2 `AGENTS.md`「诚实边界」段补一句:纯净性 lint 仅覆盖高精度工具内部 token,裸层级词(T1/T2/scout)泄漏由提示词护栏覆盖、非确定性可测(design D4 诚实边界)。
- [x] 8.3 人工跑一次 `mgh-init --format opencode` 在样例仓,确认 `AGENTS.md` 受管块为单个中性块、正文无脚本名/工具名/层级描述。
