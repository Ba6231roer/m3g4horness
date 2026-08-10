# Contract: shipped test-convention rule / detail files

Producer: `ut-rulewriter` subagent (rules tier, per category). Consumer: the target
project's agent (read on demand) + `assemble_test_rules.py --check` purity lint.

| format | file | shape |
|---|---|---|
| claude | `<target>/.claude/rules/test-<category>.md` | minimal YAML frontmatter (`description:`) + rule body |
| opencode | `<target>/<rules-dir>/<category>.md` (默认 `docs/test-conventions/`) | independent H1 document, neutral, NO front matter / outer sentinel |

## Rule body
每条规则 SHALL:
- 以目标项目**实际的测试夹具 / 类 / 方法名**开头(如 `UserServiceTest` / `@ExtendWith(MockitoExtension)`
  + `@InjectMocks`),然后陈述**既有约定是什么** + **新测试 MUST 遵循它**(勿自造竞争风格);
- 给具体 **usage**(怎么按此写法写新测试);
- 指向**确切锚点** `file:class:method`(可索引、可点击);NEVER 贴 > 3–5 行代码;
- 仅在相关时给 caveat(如「Mockito 静态 mock 只用于 `Clock`」);NEVER 用 caveat 作「约定缺失」占位。

### Omit conventions with no source anchor (hard boundary)
- `evidence[]` 为空 / `confidence ≤ 0.3` 无锚点 / 仅「需人评」notes → **不产规则**;gap 留
  `report.md` / `ut_manifest.json`(完整披露),规则正文 MUST NOT 携带「需人评 / weak 信号」prose。
- 本 category 全部无锚点 → **不写文件**,但仍 touch `done_marker`;NEVER 产空文件或裸 `# <Category>` 头。

### Anchor = 测试源码,非发现过程 (hard boundary)
- anchor SHALL 指向目标项目测试源码;NEVER 指向归类器/管线内部或「如何被发现」。

## 纯净性 (assemble_test_rules.py --check 强制, fail-loud 退出码 2)
规则正文泄漏即 fail:工具内部 token(`mgh-ut-init`/脚本名/`.mgh-ut-init/`)、schema 字段
(`assert_density`/`uniformity`/`weak_dominated`/`group_id`)、过程散文(`归类器子分`/`抽样提炼`/`断言密度`)、
无源码锚点约定;opencode 另查 `---` YAML 围栏(claude frontmatter 豁免)。回 rules 修正后重跑 assemble。

## 输出语言
人读正文用**简体中文**;代码、路径、`file:class:method` 锚点、标识符、枚举值保持原样。
