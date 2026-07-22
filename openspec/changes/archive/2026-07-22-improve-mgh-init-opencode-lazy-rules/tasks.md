# Tasks — improve-mgh-init-opencode-lazy-rules

> 实现顺序按依赖:先确定性脚本(`list_rule_jobs` 契约 → `assemble_rules` 索引引擎)→ 提示词(T3 直写详述文件 +
> lazy 语义)→ 命令壳披露 + bash 示例 → manifest + 诚实边界 + VERSION → 测试/回归 + check_contracts + 自检。
> 每任务可独立验证。双 shell 共享 `core/`,脚本/提示词改动一次双端对等。claude 输出形态不变(仅披露措辞同步)。

## 1. `list_rule_jobs.py` 契约调整(design D3/D6)

- [x] 1.1 `core/scripts/list_rule_jobs.py`:新增 `--rules-dir` 参数(default `<target>/docs/security-controls`);
  opencode `_rule_path` 由 `<base>/.mgh-init/rules-parts/<cat>.md` 改为 `<abs target>/<rules-dir>/<cat>.md`
  (`--target` 经 `Path.resolve()` 绝对化,对 subagent 任意 cwd 安全)。claude 分支不变。
- [x] 1.2 stdout `pending[]` 每项 `rule_path` 仍绝对、仍逐字透传;stderr 仅诊断;退出码 `0/1/2` 不变;模块
  docstring + `--help` 同步新 `--rules-dir`(承 R5.1 `--help` 即契约)。
- [x] 1.3 自包含不变:`sys.path` 自定位、`encoding="utf-8"`、任意 cwd 可 `py`、零第三方依赖(承 R5.3/R2)。

## 2. `assemble_rules.py` 索引引擎 + 详述 lint(design D4/D5/D6)

- [x] 2.1 `core/scripts/assemble_rules.py`:`--parts` → **`--rules-dir`**(default `<target>/docs/security-controls`);
  `--out` 仍指 `AGENTS.md` 路径不变。模块 docstring + `--help` 同步(承 R5.1)。
- [x] 2.2 重写 `_opencode` 主路径:不再「读 fragment 拼单个内联块」;改为 `glob('<rules-dir>/*.md')` →
  每文件取首条 `#` 标题为展示名(回退 filename stem)+ `@<相对 target 的路径>` 引用 → 拼简洁**索引块**
  (BLOCK_HEADER + category 清单 + lazy 指令段,见 design D1 示例)→ 复用 `_merge_into` 幂等替换同哨兵块。
- [x] 2.3 lint 扫描对象由「装配后单块」改为「`<rules-dir>/*.md` 详述文件」:token 检查 + opencode `---` 围栏
  检查不变(详述文件无 front matter);命中 fail-loud(退出码 2)+ `stdout` JSON `lint.ok=false`/`violations[]`
  含 `file`/`line`/`token`。`_claude` 路径(lint `.claude/rules/security-*.md`)不变。
- [x] 2.4 stdout JSON 摘要增 `rules_dir` 字段 + `categories[]`(索引含的 category);保留 `migrated_legacy_blocks`、
  `written`、`lint`;退出码 `0/1/2` 不变。`--dry-run` / `--check` 语义保留。
- [x] 2.5 旧版「全量内联块」迁移:同哨兵 → 新版重跑自然替换为索引块(复用既有 `_merge_into`,零额外迁移逻辑);
  旧 `<!-- mgh-init:begin -->` 品牌块清扫逻辑(`_strip_legacy_blocks`)保留。
- [x] 2.6 自包含不变:`sys.path` 自定位、`encoding="utf-8"`、任意 cwd 可 `py`、零第三方依赖(承 R5.3/R2)。

## 3. 提示词:T3 直写详述文件 + lazy 语义(design D3/D5)

- [x] 3.1 `core/prompts/fragments/rules-format-opencode.md`:emission flow 改为「T3 直写
  `<rules-dir>/<cat>.md` 独立 H1 文档」(非「写暂存 fragment、脚本合并进单块」);详述文件模板由 `### <Category>`
  (H3)改为 `# <Category> 安全控制`(H1,独立文档);保留「无 front matter」「无 schema 字段」「锚点=源码」
  「无实现则不写文件 + 仍 touch done_marker」硬边界;「Never 直写 AGENTS.md」边界保留。
- [x] 3.2 同文件补 lazy 语义说明:详述文件由 `AGENTS.md` 索引块的 `@` 引用 + 按需指令加载(opencode 无
  path-scoping);T3 无需关心索引块(归 `assemble_rules.py`)。溯源注释保留(承 R1)。
- [x] 3.3 `core/prompts/stages/init-rulewriter.md`:opencode 分支由「写暂存 fragment」改为「写详述文件
  `<rules-dir>/<cat>.md`(独立 H1)」;`rule_path` 仍编排器逐字给定(绝对)、仍 NEVER 自拼路径/写相对/写
  AGENTS.md/写哨兵;两格式共享的「无实现则省略」「锚点=源码」「以实现名起头」recipe 不变。
- [x] 3.4 `core/prompts/fragments/rules-format-claude.md`:仅同步披露一句(opencode 侧已改为 lazy 索引 +
  详述文件,claude `paths:` 结构与落点不变);双端结构不混(既有硬边界)。

## 4. 命令壳披露 + bash 示例(两壳对称,design D1/D6)

- [x] 4.1 `releases/opencode/command/mgh-init.md` 与 `releases/claude-code/commands/mgh-init.md`:步骤 6/6b
  披露改为「T3 opencode 直写 `docs/security-controls/<cat>.md` 详述文件;`assemble_rules.py --rules-dir`
  扫该目录建 `AGENTS.md` 简洁索引块(惰性 `@` 引用 + 按需加载指令)+ lint 详述文件」;claude 行不变(已 lazy)。
- [x] 4.2 两壳「Deterministic invocation」bash 块:`list_rule_jobs.py` 增 `--rules-dir docs/security-controls`;
  `assemble_rules.py` 的 `--target . --format opencode` 保留(默认 `--rules-dir`);stage→组件表 `assemble_rules.py`
  行说明同步(索引生成 + 详述 lint)。
- [x] 4.3 两壳「Output」段:opencode rules 描述由「单内联受管块」改为「`AGENTS.md` 简洁索引块 +
  `docs/security-controls/<cat>.md` 详述文件(按需加载)」。`--out`/`--rules-dir` 默认值在 flag 表注明。
  无新 stage、编排流骨架不变(承 R5.6 薄壳)。

## 5. manifest + 诚实边界 + VERSION(承 R5.8/R5.10)

- [x] 5.1 `init_manifest.json`(由 i4 stage 产):增 `rules_dir` + `rules_layout:"lazy-index"` 字段(opencode);
  claude 侧记 `rules_layout:"path-scoped"`(既有行为)。manifest 文案简体中文,键名/路径原样。
- [x] 5.2 `AGENTS.md`「诚实边界」段:mgh-init opencode 输出形态那句更新(AGENTS.md 简洁索引 + 详述文件按需
  加载;lazy 加载为语义性、opencode 唯一机制,非确定性可测——对齐既有诚实边界风格)。
- [x] 5.3 两命令壳 `description:` 与版本号 bump;`--help`/无参仍打印 flag 表并 STOP(承 R5.6/R5.8)。

## 6. 测试 + 回归 + 契约 lint + 自检(承 R5.1/R5.8)

- [x] 6.1 `tests/test_assemble_rules.py` 重写 opencode 用例:详述目录含 `authentication.md`/`authorization.md`
  → `assemble_rules.py --format opencode` 产出 `AGENTS.md` 索引块(含对应 `@docs/security-controls/<cat>.md`
  行 + lazy 指令);stdout `categories[]` + `rules_dir` 正确。
- [x] 6.2 同测试:详述文件含 `found_controls:`/`evidence_count:`/`---` 围栏/`扫描器模式定义` → lint fail-loud
  (退出码 2,violations 含 token + 文件位置);claude `paths:` frontmatter 不误报(围栏检查不跑)。
- [x] 6.3 同测试:索引只引用存在的详述文件(无孤儿);整 category 无实现(T3 不写文件)→ 索引不含该行;
  详述文件无 `#` 标题 → 索引展示名回退 filename stem。
- [x] 6.4 同测试:幂等(连跑两次索引块只一块、详述文件被覆写);旧版「全量内联块」(同哨兵)被替换为索引块
  (用户其余内容不动);旧 `mgh-init:` 品牌块迁移计数正确;裸 `T1`/`category`/`缺失` 不误报。
- [x] 6.5 `tests/test_list_rule_jobs.py`(若存在,否则扩 contract 测):opencode `rule_path` =
  `<abs target>/docs/security-controls/<cat>.md`(绝对,`--target .` 仍绝对);`--rules-dir` 覆盖生效;claude 不变。
- [x] 6.6 `tools/check_contracts.py`:把 `list_rule_jobs.py --rules-dir` 与 `assemble_rules.py --rules-dir`
  纳入 CLI lint(两壳 bash 块的 flag 必须在 `--help` 声明);确认旧 `--parts` 已从两壳 bash 块移除。
- [x] 6.7 非脚本目录 cwd 子进程调用两脚本验导入鲁棒(承 R5.3a);AST 零依赖扫描覆盖两脚本(承 R2);
  全量 `py tests/` 绿;`install.sh` 自检通过(fail-soft 不阻断)。

## 7. 自检 + 边界确认

- [x] 7.1 `grep -rn "rules-parts" core/ releases/` 确认暂存目录引用已清除(除迁移逻辑 `_LEGACY`/历史注释);
  `grep -rn "rules_dir\|lazy-index" core/scripts/assemble_rules.py` 确认新字段已落。
- [x] 7.2 人工跑一次 `mgh-init --format opencode` 在样例仓:确认 `AGENTS.md` 受管块为简洁索引(category 行 +
  `@docs/security-controls/<cat>.md` + lazy 指令)、详述文件为独立 H1 文档、正文无 front matter/schema 字段/
  过程散文/缺失散文、仅含目标项目类/方法/源码锚点。
- [x] 7.3 确认零新增 pip 依赖(承 R2);未碰 `core/prompts/**` 溯源注释与上游同步锚点(承 R1);未改
  `controls_inventory.json` schema / T1/T2/T4 契约 / 哨兵字符串 / claude `paths:` 结构(承 Non-Goals)。
