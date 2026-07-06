# Tasks — harden-mgh-init-orchestration-discipline

> 依赖顺序:补脚本空洞(L2,最低风险,先填真实缺口)→ 合法瞄一眼 + 派生量(L2)→ 边界 --check
> (R5.9)→ 双壳信息流固化(L1)→ subagent 白名单(L4)→ hook(L3,最大风险面,最后)→
> AGENTS.md 措辞(L5)→ 回归 + 端到端。每条可独立验收。遵守 AGENTS.md R1–R5(零依赖、文档简练、
> 复用导入、R5.1 CLI lint、R5.8 回归)。新脚本 MUST 经 `tools/check_contracts.py` 断言其 `--help`
> 含双壳镜像的所有 flag。

## 1. 补扇出 pending-list 脚本空洞(L2 / FD3;闭合 scout/T3 与 T1 的不对称)

- [x] 1.1 `core/scripts/list_scout_batches.py`:镜像 `list_clusters.py`。读 `scout_plan.json::batches[]`
      + 扫 `<target>/.mgh-init/checkpoints/scout/*.json.done`;stdout
      `{repo,total,done,pending[],truncated}`;`pending[]` 每项
      `{batch_id,targets_count,bytes,needs_slice[]}`;stderr 仅诊断;退出码 0/1/2。自定位 `sys.path`、
      utf-8、零依赖、任意 cwd。
- [x] 1.2 `core/scripts/list_rule_jobs.py`:T3 按-category pending。读 `<target>/.mgh-init/controls_inventory.json::controls[]`
      (或 categories)+ 扫 `checkpoints/t3/*.done`;stdout `{total,done,pending[]}`,`pending[]` 每项
      `{category,format,rule_path}`。同 1.1 契约。
- [x] 1.3 两份 `mgh-init.md`:scout 扇出段(步骤 3b)与 T3 扇出段(步骤 6)的「for each batch / category」
      前插入「先 `list_scout_batches.py` / `list_rule_jobs.py` 取 pending,再迭代」;`--resume` 段同步。
- [x] 1.4 `core/contracts/init/`:新增 `scout-enumeration.md`、`rule-jobs.md`(或并入 `scout-plan.md`/
      `rules-parts.md`),作为 pending 清单 stdout 的唯一 I/O 契约。

## 2. 合法瞄一眼原语(L2 / FD5;专治 issue #2 #4「先理解结构」的 py -c 反射)

- [x] 2.1 `core/scripts/describe_artifact.py`:`--in <json> [--keys] [--count] [--sample N] [--shape] [--field a.b.c]`。
      stdout JSON 摘要;stderr 诊断;退出码 0/1/2。零依赖、自定位、utf-8。`--count` 对 wrapper dict
      报「顶层 3 键 vs clusters[] 长度」并 warn(防 `len(wrapper)=3` 误判)。
- [x] 2.2 两份 `mgh-init.md`:编排器纪律段增「需要瞄一眼产物结构 → `describe_artifact.py`,NEVER
      `py -c`/`Read` 整份大 JSON」(implementation-intention 句式)。
- [x] 2.3 `core/contracts/init/describe.md`:`describe_artifact.py` 各模式输出 shape 契约。

## 3. 派生量作为 stdout 字段(L2 / FD6;消除 issue #5「自己算」)

- [x] 3.1 `core/scripts/plan_scout.py`:stdout 增 `regex_known_count`(= 已 regex 命中、排除出 scout 的
      文件数;内部 `regex_files` 已算于 `plan_scout.py:109`,仅暴露)。`scout_plan.json` 顶层同增该字段。
- [x] 3.2 `core/scripts/discover_controls.py`:stdout 摘要补 `big_files`、`unresolved_count` 等下游常查量
      (审阅既有 stdout 字段,补缺;不删既有字段)。
- [x] 3.3 `core/contracts/init/scout-plan.md` + `candidates.md`:补 `regex_known_count` 等新字段说明。

## 4. stage 边界 --check(R5.9 / FD7;openspec validate-at-boundary 泛化)

- [x] 4.1 `core/scripts/discover_controls.py`:增 `--check <out-dir>`,断言 `controls_candidates.json`/
      `clusters.json` 的 wrapper + 每条 `source` + cluster_id 唯一;退出码 0 ok / 2 违例。
- [x] 4.2 `core/scripts/plan_scout.py`:增 `--check <scout_plan.json>`,断言 batches[] 非空(除非 0 target)、
      每批 `bytes ≤ --batch-bytes`、`needs_slice` 仅含超批文件。
- [x] 4.3 `core/scripts/merge_scout.py`:增 `--check <scout_candidates.json>`,断言每条 `source:"scout"` +
      有 `file:line`。
- [x] 4.4 `core/scripts/validate_inventory.py`(或下放到 T2 后 check):断言 `controls_inventory.json`
      vvah `design_controls` 兼容字段 + 每条 `evidence` 锚点 + `category→kind` 归一。
- [x] 4.5 两份 `mgh-init.md`:每 stage 产物步骤后插「跑 `<producer> --check`,失败退出码 2 → 回退重跑」;
      既有 `assemble_rules.py --check`(步骤 6b)作为范式锚点。

## 5. 双壳信息流固化(L1 / FD1+FD2;刚性三元组 + implementation-intention)

- [x] 5.1 两份 `mgh-init.md`:编排流每个 fan-out 步骤改为 `[输入产物::字段] → script/subagent →
      [输出产物::字段]` 三元组;doubt 时刻内联 1 行 shape(如「scout_plan.json::batches[] 即你的工作
      清单,经 list_scout_batches.py 取」)。
- [x] 5.2 两份 `mgh-init.md`:merge/foldin 后显式声明「`scout_candidates.json` / `controls_candidates.json`
      / `clusters.json` 此时为**终态**,不再二次聚合/重切批」(治 issue #8 `_aggregate_scout.py`)。
- [x] 5.3 两份 `mgh-init.md`:编排器纪律段用 implementation-intention 句式重写「WHEN 需 X,触发器 Y,
      NEVER py -c」(对每个常被手搓的需求:工作清单 / 瞄结构 / 派生量 / 切大文件)。

## 6. subagent sanctioned-tools 白名单(L4 / FD8;治 issue #7 #10)

- [x] 6.1 `core/prompts/stages/init-scout.md`:「Use your tools freely」(行 31)改为「Use Read/Glob/Grep
      freely; scripts sanctioned-list only (chunk_sources.py); NEVER Write .py / py -c / python -c」;
      增「输入产物已是终态,NEVER 用代码变换/重派生」。
- [x] 6.2 同上改 `init-induct.md` / `init-survey.md` / `init-synthesis.md` / `init-rulewriter.md` /
      `init-rules-consistency.md` / `init-scout-merge.md` / `init-scout-audit.md`:各加 Sanctioned-tools 段。
- [x] 6.3 双壳 `agents/init-*.md`(claude + opencode 镜像):Hard constraints 段同步增「NEVER Write .py /
      py -c」(subagent 壳层也声明,双重防线)。

## 7. 运行时强制 hook(L3 / FD4;兑现 R5.7,最大风险面)

- [x] 7.1 `releases/claude-code/hooks/block-adhoc-scripts.sh`(或 `.py`):PreToolUse 入参读 tool+command;
      仅当 env `MGH_INIT_ACTIVE=1` 时启用;`Bash` 拦 `py -c|python -c` + 含 `import json`/`open(`/`load(`/
      `\.json`;`Write` 拦 `*.py` 且不在白名单(`core/scripts`/`tests`/`tools`/`releases/*/hooks`)。命中→
      退出码 2 + stderr recipe(指向 list_*/describe_artifact/脚本 stdout 字段)。零依赖(bash + py stdlib)。
- [x] 7.2 `install.sh`:镜像 `core/` 后,向 `<dest>/.claude/settings.json` 的 `PreToolUse` **幂等追加**
      matcher(不覆盖用户既有 hook;存在则跳过);`--no-enforce-hook` opt-out。
- [x] 7.3 `install.sh --opencode`:探测 opencode PreToolUse 能力;支持则注入等价,不支持则 stderr warn +
      跳过(fail-soft,承 R5.8)。
- [x] 7.4 两份 `mgh-init.md`:编排器起步 `Bash: export MGH_INIT_ACTIVE=1`(声明运行域);壳顶部声明
      hook 存在及其 opt-out。
- [x] 7.5 `tests/test_block_adhoc_scripts.py`:双栏正则断言——放行 `py <path>/discover_controls.py …`、
      `py tests/…`、`py -c "print(1)"`;拦截 `py -c "import json; json.load(open('x.json'))"`、
      `Write _prep_scout_batches.py`。

## 8. AGENTS.md 措辞 sharpen(L5 / FD1+FD2)

- [x] 8.1 R5.2:具名反例从 `mgh_init.py` 扩为含 `py -c "import json"` / `_prep_*.py` / `_aggregate_*.py`;
      拆 (a) 大编排器 (b) 微脚本内省 (c) Read 叶子源码 三条明线(均 `NEVER`)。
- [x] 8.2 R5.3(b):加「所有 fan-out(tier)MUST 经 `list_*`/`describe_*` 脚本产 pending 清单,编排器对
      清单迭代,NEVER 直接挖 JSON」。
- [x] 8.3 R5.7:从「倡议」升级为「交付物」——每个 `mgh-*` 命令的 #1 违例 MUST 配 PreToolUse hook(install
      时注入);hook 缺席 = CI fail(对齐 R5.8)。
- [x] 8.4 新增 **R5.9**(边界校验泛化):每 stage 产物有 `--check` 或独立 validator;编排器跑完一步 MUST
      校验再进下一步;失败 fail-loud 回退重跑(对齐 `assemble_rules.py --check` 范式)。

## 9. 契约 lint + 回归单测(R5.1 / R5.8)

- [x] 9.1 `tools/check_contracts.py`:扩到新脚本(`list_scout_batches`/`list_rule_jobs`/`describe_artifact`/
      `validate_inventory`)+ 既有脚本新 `--check` flag;断言双壳 MD 里每个 `*.py --flag` 在 `--help` 存在。
- [x] 9.2 `tests/test_list_scout_batches.py`:resume-aware pending(部分 `.done` → pending 仅含未完成);
      空/截断不静默;wrapper 误判防护。
- [x] 9.3 `tests/test_describe_artifact.py`:`--keys/--count/--sample/--shape/--field` 各模式输出 shape;
      `--count` 对 wrapper dict 的 warn。
- [x] 9.4 `tests/test_stage_check.py`:各 `--check` 对正常产物退出 0、对破损产物(py -c 改坏后)退出 2。
- [x] 9.5 既有 R5.8 回归扩面:新脚本在**非脚本目录 cwd** 子进程跑(导入鲁棒)、零依赖 AST 扫描、
      `--help` 即契约、性能不退化。
- [x] 9.6 install 自检:`install.sh` 后校验新脚本同目录共存 + hook 注入幂等(二次 install 不重复加 matcher)。

## 10. 端到端验证

- [x] 10.1 `py tests/`(全部,含新测试)绿;`tools/check_contracts.py` 0 违例;零依赖 AST 扫描无输出。
- [x] 10.2 双壳 install 自检通过(`./install.sh --claude <tmp>` / `--opencode <tmp>`):脚本就位、
      hook 注入幂等、opt-out 生效 **(本机)**。
- [x] 10.3 在合成中仓跑 `/mgh-init --format claude`:编排器全程**不出现** `py -c` 内省 / `Write _*.py`;
      hook 不误伤合法叶子调用;各 `--check` 通过 **(本机)**。
- [ ] 10.4 真机大仓(用户 Java 仓)复跑 `/mgh-init --format opencode`:scout 扇出走
      `list_scout_batches.py`、T3 走 `list_rule_jobs.py`、瞄结构走 `describe_artifact.py`;`new_issue.txt`
      10 点不复现 **(待用户真机)**。
- [x] 10.5 回滚演练:改动面清单(脚本新增/改、hook 新增、双壳改、prompt 改、AGENTS.md 改、契约改、
      测试新增);无 schema/数据迁移;`--no-enforce-hook` 可完全回退 hook 层。
