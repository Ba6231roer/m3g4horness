## Context

`install.sh` 把 `releases/<platform>/{commands,agents,skills}` + **整个 `core/`** 镜像进
目标业务项目的 `<target>/.{claude,opencode}/`(`install.sh:57-75`,`core/` → `<dest>/mgh-core/`)。
这些 md 在业务项目里被宿主 agent / subagent 当提示词读进上下文。其中散落只在本仓研发
语境才有意义的引用——在业务项目环境是**悬空指针**:浪费 token,且目标项目常有自带
`AGENTS.md` 与无关编号,会误导 subagent 读客户那份。

**6-agent 全量审计结果**(读全部 ~92 shipped md,超越 `R5.*`/`FD.*` 两模式):

| 切片 | 文件 | 发现 | 处置 |
|---|---|---|---|
| mgh-init 壳 + agent 定义 | 16 | 14(全 b) | 清 |
| mgh-init stage 提示词 + fragment | 10 | 23(含 2 个 c 嫁接) | 清 |
| mgh-init I/O 契约 + core/docs | 12 | 31(全 b;`prompt-provenance.md` 干净) | 清 |
| mgh-sast 壳 + agent + sra/blst | 22 | 8(仅 sra/blst 的 `task.260630.md`) | 清 sra/blst;sast 干净 |
| mgh-sast skills | 14 | 0 | CLEAN |
| mgh-sast prompts/baselines/lens/fragments | 16 | 0 | CLEAN |

**审计新发现的同类问题(超 R5/FD)**:决策 ID(`D2/D4/D5/D8/D9/D12`)、openspec 变更夹名
(`improve-mgh-init-llm-discovery` 等)、内部上游文档引用(`glasswing_docs/09`)、仓根开发态
文件指针(`task.260630.md`)、dev-meta 措辞(`承 R5.x`/`范式锚点`/`本仓`)、票号
(`GitHub issue #11454`)、上游溯源行话(`vvah`/`design_controls` 作归因)。

约束:R1(上游归因保护)、R2(零运行时依赖)、R3(文档简练)、R5.3(脚本稳定性)、
R5.5(措辞铁律)、R5.7(确定性闭环优先)、R5.8(install 自检 + 回归测)。

## Goals / Non-Goals

**Goals:**
- shipped md 不含 8 类 dev-only 溯源 / 悬空引用;**操作性内容原样保留**(删或嫁接二选一)。
- 铁律落 AGENTS.md R5.10(覆盖完整 8 类),由确定性 lint + 回归测闭环。
- 受保护归因类(`Source:` 头 / Apache / `prompt-provenance.md` / 操作性 `design_controls` / CVE)零误伤。

**Non-Goals:**
- 不改脚本 CLI 契约、流水线阶段、产物 schema、提示词**指令性内容**(仅剥离溯源)。
- 不动 `core/scripts/*.py`、hooks `.py`、`tools/*.py`(用户豁免)。
- 不动 `AGENTS.md` 既有 R1–R5(真相源,编号合法)、`openspec/**`(不分发)。
- 不把 `vvah`/`design_controls` 作归因纳入 lint 硬边界(与受保护 Source: 头同形,机器难辨)。

## Decisions

### D1 — 「shipped md」精确边界 = install 拷贝集(单一真相)

lint 扫描集**镜像 install.sh source globs**:`releases/{claude-code/{commands,agents,skills},
opencode/{command,agent}}` + `core/prompts/**` + `core/contracts/**`。豁免:脚本 `.py`、
`AGENTS.md`、`openspec/**`、`tools/`、`tests/`、`docs/`、`README`、`task.*`、`core/docs/`
(归因记录,见 D9)。**不手维护 allowlist**——直接镜像 install source globs 防漂移。

### D2 — 剥什么 / 留什么(完整 8 类 + 受保护类)

**剥(dev-only,lint 必报除第 8 类外的前 7 类):**
1. 规则编号 `\bR\d+(\.\d+)?\b`、2. 失败 ID `\bFD\d+\b`、3. 决策 ID `\bD\d+\b`、
4. 变更夹名 `(add|fix|harden|improve|purify)-mgh-(init|sast|sra|blst)-…`、
5. `glasswing_docs/`、6. `\btask\.\d+\.md\b`、7. dev-meta `承/兑现 R\d`、`范式锚点`、
8. 上游溯源行话 `vvah`/`design_controls` **作归因**(人工,不入 lint)。

**留(操作性 / 受保护,lint 不报):**
- 输出产物路径:`<target>/AGENTS.md`、`<target>/.claude/rules/`、`<target>/.mgh-init/`、
  `never AGENTS.md directly`(指输出交付物)。
- runtime 脚本调用:`py .claude/mgh-core/scripts/*.py`、`.opencode/mgh-core/scripts/*.py`。
- 操作阶段标签:`T1`/`T2`/`T3`/`scout`/`s1`..`s9`。
- **受保护归因**(D9):`Source: vvaharness/...` 头、skills Apache 归因、`prompt-provenance.md`、
  操作性 `design_controls`、`CVE-2025-41248`。

> 关键区分:`AGENTS.md` **跟 R 编号连用** = 本仓手册引用(剥);**作输出目的地** =
> 交付物路径(留)。lint 用 `AGENTS\.md\s+R\d` 精确命中前者。

### D3 — lint 高精度模式(低假阳,前 7 类硬边界 + 第 8 类人工)

| # | 模式 | 命中 | 假阳风险 |
|---|---|---|---|
| 1 | `\bR\d+(\.\d+)?\b` | `R5.2`/`R3`/`R1–R4` | 低(`\b` 避开 `R3Service`) |
| 2 | `\bFD\d+\b` | `FD8`/`FD3` | 零 |
| 3 | `\bD\d+\b` | `D12`/`D9 = D12` | 低(审计确认本仓 shipped md 无合法 D 编号;allowlist 兜底) |
| 4 | `AGENTS\.md\s+R\d` | `AGENTS.md R1–R4` | 低(仅命中手册+规则号连用) |
| 5 | `\b(add\|fix\|harden\|improve\|purify)-mgh-(init\|sast\|sra\|blst)-[a-z0-9-]+` | `improve-mgh-init-llm-discovery` | 低(kebab 全链) |
| 6 | `glasswing_docs/` | 内部上游文档 | 零 |
| 7 | `\btask\.\d+\.md\b` | `task.260630.md` | 零 |
| 8 | `范式锚点` / `承\s*R\d+` / `兑现\s*R\d+` | dev-meta | 零 |

**不入 lint(人工)**:`vvah`/`vvaharness`/`design_controls` 作归因——与受保护 `Source:` 头 /
skill Apache 归因 / 操作性 `design_controls` **同形**,机器难辨;改由提示词护栏 + tasks 3.x
人工清理 + diff 自证覆盖。提供 `--allowlist` 兜底未来假阳(默认空)。

### D4 — 上游溯源行话作归因:`vvah`/`design_controls`(人工,与受保护类区分)

审计区分了 3 种 `vvah`/`design_controls` 出现:
- **作谱系归因**(剥):`vvah 兼容`/`vvah-compat`/`vvah 6-enum`/`vvah design_controls-compatible`
  / `### vvah alias reuse` 标题词。操作性 schema 字段/枚举/alias 表已在别处完整陈述,`vvah`
  名对目标 agent 无用。
- **受保护归因**(不动):`Source: vvaharness/...` 头(R1)、skills 的 "verbatim port from
  vvaharness (Apache-2.0)"、`core/docs/prompt-provenance.md`。
- **操作性用法**(不动):sast 提示词正文 "Account for design controls" = 威胁建模术语,
  非溯源。

→ 前者换述或删词(保留表体/字段/枚举),由 tasks 3.1.3 / 3.4.4 人工处理;不入 lint。

### D5 — AGENTS.md R5.10 措辞(承 R5.5)

recipe + 硬边界 `NEVER` + RFC-2119 + 无豁免子句,覆盖**完整 8 类**,指向 lint:

> **R5.10 分发产物纯净性**:经 install 装入目标项目的 md(命令壳 / agent 定义 / stage
> 提示词 / I/O 契约)MUST NOT 携带 dev-only 溯源 / 悬空引用——研发铁律编号(`R5.x`)、
> 失败/决策 ID(`FDn`/`Dn`)、openspec 变更夹名、`glasswing_docs/`、仓根 `task.*.md`、
> dev-meta(`承/兑现 R5.x`/`范式锚点`)、上游溯源行话作归因(`vvah`/`design_controls`);
> NEVER 把研发语境引用带进分发产物。**保留**操作语义与输出产物路径(`<target>/AGENTS.md`)。
> 受保护归因(`Source:` 头 / Apache / 归因记录)不在禁列。理由〔省 token + 防目标项目误读 +
> 平台无关〕须随规保留。由 `tools/check_distributed_purity.py` 确定性强制(承 R5.7)。

### D6 — 实现顺序与验证

按文件类逐批清(壳+agent → stage 提示词 → fragment → 契约 → sra/blst),每批跑 lint 收敛,
非整体 sed。每处 `git diff` 自证「仅删标记/括号/交叉引用句,或嫁接最简必需内容,无指令性损失」。

### D7 — 对 R5.7 baseline 的诚实定位

本变更是**非行为性文本纯净编辑**(剥溯源 / 嫁接最简内容,不改指令语义),pass-rate/variance
影响为零级。R5.7 完整 baseline→A/B 仪式对此 disproportionate;改三道轻量自证:(1) diff 仅含
标记/交叉引用删除或最简嫁接;(2) 既有 prompt/契约相关测试不退化;(3) `/mgh-init --help`、
`/mgh-sast --help` 烟测正常。**不声称完整 R5.7 A/B。**

### D8 — delete-or-graft 决策规则(承用户:不只是删,必需内容要嫁接)

每条违例二选一:
- **删 (a/b)**:被引内容目标**不需要**,或已在本 shipped 文档他处陈述 → 删标记/引用句。
- **嫁接 (c)**:被引内容目标**必需**才能正确行为 → 把**最简**必要内容(1–2 行,token 极省)
  内联到恰当位置,再删指针。**省 token 优先,非必要不贴长描述。**

审计已分类:74 处删 / 2 处嫁接(scout-audit s6 引言、opencode #11454 约束)+ 1 处混合拆分
(survey: 保留 contracts/ 删 AGENTS.md R1–R4)+ inventory alias 表保留表体剥 `vvah` 词。

### D9 — 受保护归因类(零误伤)

`Source: vvaharness/...` 头(R1 / Apache)、skills Apache 归因、`core/docs/prompt-provenance.md`、
操作性 `design_controls`、`CVE-2025-41248` —— 审计明确**不动**。tasks 6.3 终检复核在位。

## Risks / Trade-offs

- [lint 假阳误伤合法文本] → D3 仅前 7 类高精度 + `\b` 词界;`--allowlist` 行级例外。
- [误删操作语义] → D2 留/剥边界 + D8 嫁接规则;每批 `git diff` 人工核;D7(2) 回归测兜底。
- [`AGENTS.md` 双义混淆] → D2 `AGENTS\.md\s+R\d` 精确区分手册引用 vs 输出路径。
- [lint 扫描集与 install 拷贝集漂移] → D1 镜像同一 source globs。
- [`vvah` 类与受保护归因同形] → D3/D4 不入 lint,人工 + diff 自证;接受一致性风险换 lint 稳定。
- [嫁接引入冗长] → D8「最简 1–2 行」+ 用户「省 token」硬约束;diff 自证无长贴。

## Migration Plan

纯文本 + 规则 + lint,无数据/接口迁移。回滚 = `git revert`。install 自检 fail-soft(warn
不阻断),CI 测必 fail——与既有 zero-dep 自检同模式。

## Open Questions

- `rules-format-claude.md:2` 的 `Source: code.claude.com/…` URL 归因(非 vvaharness):
  默认保留(URL 归因,非悬空指针);若维护者认为会腐烂可删。tasks 3.3.3 标为可选。
- 其余 8 类处理方式已由审计定论,无 open question。
