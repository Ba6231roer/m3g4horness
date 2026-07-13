# Tasks — fix-mgh-init-opencode-agents-md-noise

> 实现顺序按依赖:先确定性 lint 扩展(可独立测)→ 提示词护栏(治三类噪声)→ rules-format fragment
> 模板 → 命令壳披露 + 诚实边界 → 测试/回归 → 自检 + VERSION bump。每个任务可独立验证。双 shell 共享
> `core/`,提示词/脚本改动一次双端对等。

## 1. 确定性 lint 扩展 `assemble_rules.py`(治 N1/N2 高精度形状,design D4)

- [x] 1.1 `core/scripts/assemble_rules.py`:`FORBIDDEN_TOKENS` 扩增 inventory schema 字段 `found_controls`、`evidence_count`;扩增特征过程散文短语 `扫描器模式定义`、`扫描器内部正则`、`扫描器定义`、`锚点:扫描器`(半角)、`锚点：扫描器`(全角)。注释里同步更新「高精度 token 集」与 D4 哲学说明(裸通用词不入集)。
- [x] 1.2 新增 opencode 结构检查:opencode 受管块(`<!-- security-controls:begin --> … :end -->` 内正文)出现任意 `---` YAML 围栏行(`^---+\s*$`)→ 记 violation(token 标为 `---` YAML fence)。该检查**仅 `_opencode` 路径**生效;`_claude` 路径**不**跑围栏检查(claude 合法用 `paths:` frontmatter)。
- [x] 1.3 lint 诊断输出与退出码保持契约:命中 → `stdout` JSON `lint.ok=false` + `violations[]`(含 `file`/`line`/`token`)、`stderr` 报位置、退出码 `2`(fail-loud);不写盘。
- [x] 1.4 模块 docstring +「Purity lint」注释段同步:新增三类检测项(schema 字段 / 过程散文 / opencode 围栏)+ claude 围栏豁免 + 裸通用词不入集的诚实边界说明;与 AGENTS.md 诚实边界措辞锁定一致(design D4)。
- [x] 1.5 自包含不变:`sys.path` 自定位、`encoding="utf-8"`、任意 cwd 可 `py`、零第三方依赖(承 R5.3/R2);`--help` 文本无新 flag(CLI 契约不变,承 R5.1)。

## 2. 提示词护栏:`init-rulewriter.md`(治 N2/N3,两格式共享,design D3)

- [x] 2.1 `core/prompts/stages/init-rulewriter.md`:「Rule body」段增「无实现则省略」recipe——一条规则 SHALL 对应有具体源码锚点(`file:class:method`/`file:line`)的存量实现;inventory 无源码锚点的控制(扫描器期望但源码无实现)→ emit no rule;整 category 全无实现 → 不写 fragment 文件 + 仍 touch `done_marker`。判据:复用 `evidence[]` 空 / `role:"possibly-dead"` 无锚点 / 仅「期望未命中」notes。
- [x] 2.2 同文件增「锚点=源码」recipe:`锚点:`/Anchor SHALL 指向目标项目源码位置;`NEVER` 指向扫描器内部/正则定义/「如何发现」。
- [x] 2.3 同文件增「以实现名起头」recipe:规则以目标项目实际类/方法/配置名起头;控制 ID 可选,带则 `NEVER` 附 `(缺失)`/`(扫描器…)` 过程性后缀。
- [x] 2.4 「Rule body」既有的「notes gaps/effectiveness caveats briefly」收紧:caveat 只针对**既有控制的有效性**(如「只覆盖 POST 非 GET」),`NEVER` 用于「控制缺失」占行;措辞用 recipe + `NEVER` + RFC-2119(`SHALL`/`MUST`),无豁免子句(承 R5.5①②③)。

## 3. rules-format fragment 模板(治 N1,design D2)

- [x] 3.1 `core/prompts/fragments/rules-format-opencode.md`:加硬边界——fragment SHALL 以 `### <Category>` 起;`NEVER` 带 YAML `---` 围栏;`NEVER` 出现 inventory schema 字段(`found_controls`/`evidence_count`/`category:`/`source:`/`evidence:` 作 frontmatter 键)。明确「opencode 无 front matter(claude 才有 `paths:`)」。Fragment 模板示例保持最小(标题 + 控制名 + 用法 + 源码锚点 + 必要 caveat)。
- [x] 3.2 `core/prompts/fragments/rules-format-opencode.md`:`锚点:` 字段模板示例强化为指向目标项目源码(`src/.../X.java::Class.method`),旁注 `NEVER` 指向扫描器内部;「Rule-body purity」段补「无实现则省略」一句(指向 init-rulewriter 的同一硬边界)。
- [x] 3.3 `core/prompts/fragments/rules-format-claude.md`:`paths:` 仍是唯一 frontmatter(明确 `NEVER` 抄 inventory schema 字段 `found_controls`/`evidence_count` 进 frontmatter);「锚点=源码」「无实现则省略」护栏同步一句(双端对等,结构/`paths:` 不变)。

## 4. 命令壳披露 + 诚实边界(两壳对称,design D1/D4)

- [x] 4.1 `releases/opencode/command/mgh-init.md` 与 `releases/claude-code/commands/mgh-init.md`:T3/6b 步骤披露一句「T3 fragment 禁 front matter / inventory schema 字段 / 过程散文 / 无实现项;`assemble_rules.py --check` 扩展 lint 兜底」(编排流不变,只增可观测披露);stage→组件表 `assemble_rules.py` 行 lint 说明同步。无新 flag、无新确定性调用(承 R5.6 薄壳)。
- [x] 4.2 `AGENTS.md`「诚实边界」段:mgh-init 纯净性那句补——lint 现亦覆盖 inventory schema 字段(`found_controls`/`evidence_count`)+ opencode YAML 围栏 + 特征过程散文短语(`扫描器模式定义` 等);裸通用词(`category`/`缺失`/泛指 `锚点`)仍仅提示词覆盖、非确定性可测(design D4 诚实边界)。
- [x] 4.3 两壳 `description:` 与版本号 bump(承 R5.6/R5.8);`--help`/无参仍打印 flag 表并 STOP。

## 5. 测试 + 回归(承 R5.8)

- [x] 5.1 `tests/test_assemble_rules.py` 扩:opencode 受管块含 `found_controls:` / `evidence_count:` → lint fail-loud(退出码 2,violations 含 token)。
- [x] 5.2 同测试扩:opencode 受管块正文含 `---` 围栏行 → fail-loud;含 `扫描器模式定义` / `锚点：扫描器内部正则定义` → fail-loud。
- [x] 5.3 同测试扩 claude 不误报:`.claude/rules/security-x.md` 以合法 `---\npaths:\n  - "src/**"\n---` 开头 → claude lint 退出码 0(围栏检查不跑);裸 `category`/`缺失` 在正文 → 不误报。
- [x] 5.4 同测试扩:T3 整 category 无实现不写 fragment 文件时,`assemble_rules.py --format opencode` 受管块不含该 category 空标题(回归 D5:无空标题噪声)。
- [x] 5.5 回归:幂等(连跑两次受管块只一块)、旧块迁移、用户内容保留、裸 `T1`/`T2` 不误报 不退化(前序 `fix-mgh-init-rules-purity` 既有用例保持绿)。
- [x] 5.6 非脚本目录 cwd 子进程调用 `assemble_rules.py` 验导入鲁棒(承 R5.3a);AST 零依赖扫描覆盖(承 R2);`tools/check_contracts.py` 把 `assemble_rules.py --help` 纳入 CLI lint(无新 flag,承 R5.1)。
- [x] 5.7 全量 `py tests/` 绿;`install.sh` 自检通过(fail-soft 不阻断)。

## 6. 自检 + 边界确认

- [x] 6.1 `grep -rnE "found_controls|evidence_count|扫描器模式定义|扫描器内部正则" core/scripts/assemble_rules.py` 确认新 token 已入 `FORBIDDEN_TOKENS`;`grep -rn "扫描器定义" core/prompts/` 确认提示词 recipe 已落。
- [x] 6.2 人工跑一次 `mgh-init --format opencode` 在样例仓:确认 `AGENTS.md` 受管块为单个中性块、正文无 front matter / 无 schema 字段 / 无过程散文 / 无「缺失」散文、仅含目标项目类/方法/源码锚点。
- [x] 6.3 确认零新增 pip 依赖(承 R2);未碰 `core/prompts/**` 溯源注释与上游同步锚点(承 R1);未改 `controls_inventory.json` schema / T1–T4 契约 / CLI flag(承 Non-Goals)。
