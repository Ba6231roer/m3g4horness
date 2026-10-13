# dsh-command-surface Specification

## Purpose

定义 mgh 命令家族在 deepseek-harness(dsh)宿主上的命令承载面:以 user-invocable skill 形态
分发编排壳,规定其 frontmatter 契约、召唤与参数读取语义、与 claude/opencode 双壳的对等镜像
纪律、执行边界顶替声明,以及安装落位与 lint 覆盖。

## Requirements

### Requirement: mgh commands are invoked as user-invocable skills on dsh

Each shipped mgh command SHALL exist on the dsh dialect as a skill directory
`mgh-<name>/SKILL.md` whose frontmatter carries `name` (kebab-case, equal to the directory
name), `description` (shared source with the other dialects, within the 1536-character cap),
`user-invocable: true`, and `disable-model-invocation: true`. The user SHALL be able to invoke
the command by typing `/mgh-<name>`; the model SHALL NOT be able to auto-trigger an
orchestrator shell through the skill list.

#### Scenario: explicit slash invocation loads the shell
- **WHEN** 用户在 dsh 会话输入 `/mgh-sdr 复核 feature/x 分支`
- **THEN** dsh 将 mgh-sdr skill 正文注入当轮,编排器按壳内 step 0 处理参数余文

#### Scenario: model cannot self-trigger orchestration
- **WHEN** dsh 模型在普通任务中考虑调用可用 skill
- **THEN** mgh-* 编排壳不出现在模型可召唤集合(`disable-model-invocation: true`),仅用户
  斜杠路径可达

### Requirement: Arguments arrive verbatim in the triggering message

Because dsh offers no `$ARGUMENTS` templating, each dsh shell's step 0 SHALL read its flags
from the user text following the `/mgh-<name>` token in the same message, with the same
closed-set parameter table as the claude/opencode shells. `--help` SHALL print the flag table
and STOP. Zero-argument behavior SHALL mirror each command's declared default set exactly as
on the other dialects (commands declaring safe defaults execute on them; the rest print the
table and STOP). Unknown flags SHALL fail loud with the parameter table, never be guessed.

#### Scenario: help path stops before spending tokens
- **WHEN** 用户输入 `/mgh-init --help`
- **THEN** 壳打印参数表并停止,不进入编排

#### Scenario: sdr zero-arg default run preserved across dialects
- **WHEN** 用户输入裸 `/mgh-sdr`
- **THEN** 按 `--base master`/当前分支/全 6 维默认集直接进入编排,与双壳行为一致

### Requirement: dsh shells are parity mirrors with a closed dialect-delta list

A dsh shell body SHALL be a verbatim mirror of its claude/opencode counterparts except for a
closed whitelist of dialect deltas: (a) the skill frontmatter; (b) the invocation/argument-
reading paragraph; (c) the execution-boundary disclosure replacing the claude `allowed-tools`
whitelist — the dsh face states enforcement equals the three-face guard plus host
approval/sandbox; (d) tool-name spellings already normalized by the wiring face; (e) host
mechanism facts stated for dsh (sentinel env-inheritance wording, batch-clarification
channel, per-call shell timeout) SHALL be rewritten to dsh's verified behavior rather than
copying another host's incorrect claim verbatim. All concrete
deterministic command examples (script paths, flags) SHALL match the other shells verbatim,
and the contract lint SHALL assert every flag appearing in dsh shells exists in the target
script's `--help`, across all three dialects.

#### Scenario: flag drift across three dialects is caught by lint
- **WHEN** 某叶脚本新增 flag 只补进 claude 壳,dsh/opencode 壳未同步
- **THEN** 三面契约 lint 对逐字镜像断言 fail(非零退出),漂移在合入前拦截

#### Scenario: delta whitelist is exhaustive
- **WHEN** 审阅 dsh 壳与 opencode 壳的 diff
- **THEN** 差异行仅含 (a)–(e) 五类白名单方言段;出现任何其他分叉即评审不通过

### Requirement: Lazy fragment loading follows the opencode model

dsh has no cross-file auto-inclusion, so dsh shells SHALL keep detail in `core/prompts/`
fragments loaded on demand via the `REQUIRED SUB-SKILL: Use X` convention (a model-facing
marker, lazily `Read`), with every referenced path rooted at `<target>/mgh-core/`. Shell
token-budget lint SHALL cover dsh shell bodies with the same ceiling applied to the other
orchestrator shells.

#### Scenario: budget regression on a dsh shell fails lint
- **WHEN** 某 dsh 壳正文超出编排器壳 token 上限
- **THEN** 预算 lint fail(退出码 2),要求 shard-to-fit 而非删承重内容

### Requirement: install places dsh skills idempotently and self-checks them

The `--dsh` install dialect SHALL copy the five skill directories into
`<target>/.dsh/skills/` (the project-scoped dsh skill root), overwriting on reinstall, and its
self-check SHALL assert: five shells present, each frontmatter contains the four required
fields, and no shell references a path outside `<target>/mgh-core/` or the sanctioned roots.
Missing-shell state SHALL fail the install self-check loud.

#### Scenario: reinstall refreshes shells
- **WHEN** 修改 `releases/dsh/skills/mgh-sdr/SKILL.md` 后重跑 `install.sh --dsh <target>`
- **THEN** `<target>/.dsh/skills/mgh-sdr/SKILL.md` 为新内容,无重复目录,自检全绿

#### Scenario: truncated install is detected
- **WHEN** 目标 `.dsh/skills/` 仅剩 4 个 mgh 壳(人为删除)
- **THEN** install 自检 fail-soft 报缺(承既有自检姿态),CI 场景必 fail

### Requirement: dsh dispatch disclosure states the real wiring and stop surface

dsh 的 mgh-init skill 壳 SHALL 设一段**派发面实态披露**,且披露内容 SHALL 与实际接线一致,
机制自相矛盾 SHALL NOT 出现:

① **已接线 tier 闭集**:`fanout_runner` 波次派发在 dsh 上已接线的 tier 清单 SHALL 与
`fanout_runner.py` 的 TIERS 闭集(scout / scout-merge / t1 / t2 / t3)一致;同文档其他清单
(脚本 inventory 行)与该披露 SHALL NOT 各说各话。
② **交互 stage 停止清单闭集**:未建具名派发实例、运行至此 SHALL 停止并如实报告的 stage
清单 SHALL 闭集枚举——survey / resolve / T2 单上下文 `init-synthesis` / T2 rollup
(`init-synthesis-rollup`)/ scout 收尾 `init-scout-merge` / scout-merge rollup
(`init-scout-merge-rollup`)/ T4 `init-rules-consistency`;漏列任何一个会导致编排器在无派发
实例的 stage 上即兴内联执行(恰是本披露要禁止的形态)。
③ **mid-run flag 注入不可能性**:只能在 run 起始由 write_runconfig 落盘的 flag(如
`--skip-consistency`)SHALL 如实注明「run 启动后不可再注入」——编排器读到该披露时 run 已在
途中,任何「现在补传」的动作都不存在。
④ **非终态停止的处置**:停在最后一个派发 stage(t3)而 T4 未跳过时,run SHALL NOT 产生终态
`init_manifest.json`——披露 SHALL 写明该形态(`--resume` 可跨会话续跑收尾;需要跳过 T4 时
只能以 `--skip-consistency` 重新 bootstrap,已有磁盘进度按 run_config 幂等承接)、NEVER 宣称
「完成」。

#### Scenario: wired tier list matches the dispatcher's closed set

- **WHEN** 审阅 dsh mgh-init skill 的派发面披露段与同文档脚本 inventory 行
- **THEN** 披露的已接线 tier 清单为 scout / scout-merge / t1 / t2 / t3(与 TIERS 闭集一致),
  与脚本行无矛盾(现网披露漏 scout-merge 而脚本行含之,修复后两面同话)

#### Scenario: stop list is exhaustive over non-dispatched stages

- **WHEN** 编排器按披露段判断当前 stage 是否「无派发实例、须停止上报」
- **THEN** 判定依据是闭集枚举(survey / resolve / init-synthesis 单上下文 /
  init-synthesis-rollup / init-scout-merge / init-scout-merge-rollup /
  init-rules-consistency);该清单外且已接线的 stage(t1/t2/t3/scout/scout-merge 波次)照常
  派发;清单内 stage NEVER 内联执行、NEVER 自写循环替代 dispatcher

#### Scenario: mid-run skip-consistency is declared uninjectable

- **WHEN** 编排器在 run 途中读到「T4 可 `--skip-consistency` 跳过」的披露
- **THEN** 披露同时写明该 flag 属 run 起始的 write_runconfig 落盘参数、mid-run 不可注入;
  需要跳过时唯一路径 = 以该 flag 重新 bootstrap(磁盘进度幂等承接),NEVER 假装当前 run 能补传

#### Scenario: stop-at-t3-with-T4-pending discloses the no-terminal-manifest shape

- **WHEN** run 停在 t3 之后、T4 一致性未跳过,编排器核对产物
- **THEN** 披露已写明该形态无终态 `init_manifest.json`(`--resume` 续跑收尾),编排器
  NEVER 把「波次全部 done」误报为整个命令完成
