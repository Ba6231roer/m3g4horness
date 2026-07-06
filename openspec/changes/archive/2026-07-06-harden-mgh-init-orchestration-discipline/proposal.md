## Why

`fix-mgh-init-stability` / `improve-mgh-init-llm-discovery` / `fix-mgh-init-cluster-fanout`
连续五次迭代后,确定性脚本(`plan_scout`/`merge_scout`/`list_clusters`/`chunk_sources`/
`assemble_rules`)与 R5.2/R5.3 规则都已就位。但真机大仓首跑(`new_issue.txt` 记 10 个问题)
仍大量出现:**编排器与 subagent 写一次性微脚本**(`py -c "import json…"`、`_prep_scout_batches.py`、
`_aggregate_scout.py`)去**内省与重派生**已有产物,而非调用既有脚本。

根因:R5.2/R5.3 **打错了失败形状**。规则覆盖的是「`Read` 叶子 `.py` 源码 / `Write` 大编排器
(`mgh_init.py`)/ 错误 flag」,而真机失败是**一次性微脚本内省**(`new_issue.txt` 全 10 点)。
R5.2 具名反例是 `mgh_init.py`(大编排器),agent 写 `py -c` 时**不会模式匹配成「写编排器」**,
明线不触发。`grep -niE "py -c|内省|introspect" AGENTS.md` = **0 命中**——规则未落在真实失败上。

三条结构性原因(详见 design FD1):

1. **契约是「参考」不是「运行时」**:shell 12KB 过密,doubt 时刻未被指向 contract;R5.6 禁
   `@` 内联 → 契约不载入 → agent 不信任 → 反射写 `py -c` 瞄一眼。
2. **无「合法瞄一眼」原语**:Read 整份贵(200 target),唯一便宜手段=写脚本;瞄=写代码。
3. **无运行时强制**:全仓 0 hook;R5.7 明写「能 hook 就别靠自觉」却从未给头号违例建 hook。

外加一个**真实功能缺口**(非措辞):T1 扇出有 `list_clusters.py`(resume-aware pending 清单),
**scout 扇出与 T3 扇出无对应物**。`plan_scout.py` 无 `--checkpoints` arg(grep 实证),产全部
batch、不能按 `.done` 过滤 → 编排器拿「待跑批清单」只能自挖 `scout_plan.json` → `_prep_scout_batches.py`
不是瞎写,是**填一个真实存在的脚本空洞**。

借鉴(详见 design FD2):superpowers `skills/writing-skills/persuasion-principles.md` 实证
Authority+Commitment+Implementation-intentions 把 compliance 33%→72%(N=28000);其 `hooks/hooks.json`
+ `systematic-debugging/find-polluter.sh`(skill 内置脚本,调用而非重写)是确定性闭环范式。
openspec 的 `validate`-at-boundary 是「每产物边界强制 schema」范式,本仓半采纳(仅
`assemble_rules.py --check`),应泛化。

## What Changes

按杠杆从高到低、侵入从低到高分五层(Layer 1/2/4/5 纯仓库内;Layer 3 跨项目注入 hook):

- **Layer 1 — 固化信息流(改双壳,0 新代码)**:编排流的每个 fan-out 步骤改成刚性三元组
  `[输入产物::字段] → script/subagent → [输出产物::字段]`;doubt 时刻内联 1 行 shape;显式声明
  merge/foldin 后产物为**终态**,不再二次处理。用 implementation-intention 句式(「当你需要 X,
  触发器是 Y,NEVER `py -c`」)取代软描述。
- **Layer 2 — 补脚本空洞 + 合法瞄一眼(新脚本,R2 零依赖)**:
  - `list_scout_batches.py`(镜像 `list_clusters.py`,resume-aware pending 批清单)——闭合 scout 扇出不对称;
  - `list_rule_jobs.py`(T3 按-category pending;或一个通用 `list_pending.py --tier scout|t1|t3`);
  - `describe_artifact.py`(`--keys/--sample/--count/--shape`)——专治「先理解结构」的 `py -c` 反射;
  - `plan_scout.py` 暴露 `regex_known_count` 等派生量(issue #5)——消除「自己算」的动机。
- **Layer 3 — 运行时强制 hook(兑现 R5.7,superpowers 范式)**:`install.sh` 注入 PreToolUse hook
  (claude)/ 等价(opencode),在 `/mgh-init` 运行域内拦截:
  - `Bash: py -c|python -c` 含 `import json`/`open(`/`load(` 的内省模式 → fail-loud + recipe(指向 Layer2 原语);
  - `Write: *.py` 不在 `{core/scripts}` 白名单 → fail-loud + recipe。
  hook 脚本仅标准库;带 `--no-enforce-hook` 安装期 opt-out;opencode 不支持 PreToolUse 时降级为 install warn + 强化 MD。
- **Layer 4 — subagent 纪律下沉(改 `core/prompts/stages/init-*.md`)**:每个 stage 加
  「Sanctioned tools」白名单 + 「输入已是终态,NEVER 用代码变换/内省」;`init-scout` 现有
  「Use your tools freely」改为受限自由(可 Read/Glob/Grep,NEVER `Write .py` / `py -c`)。
- **Layer 5 — AGENTS.md 措辞 sharpen**:R5.2 具名反例从 `mgh_init.py` 换成真实形状
  (`py -c "import json"` / `_prep_*.py`);拆「大编排器」与「微脚本内省」两条明线;R5.3(b) 加
  「扇出即脚本枚举」条;R5.7 从倡议升级为交付物;**新增 R5.9**(边界校验泛化,承 openspec validate)。

## Capabilities

### New Capabilities
<!-- 无新能力。orchestration-discipline 是横切关注点,落在既有 control-discovery / rules-emission 内。 -->

### Modified Capabilities
- `control-discovery`:编排器纪律从「不写大编排器 / 不读源码」**扩展为不写微脚本 / 不 `py -c` 内省**;
  scout 扇出经新 `list_scout_batches.py` 取 pending(闭合与 T1 的不对称);新增合法瞄一眼原语
  `describe_artifact.py`;派生量作为脚本 stdout 字段;**运行时 hook 强制**;**stage 边界 `--check`**;
  subagent sanctioned-tools 白名单。下游 `form_clusters → T1 → T2 → T3 → T4` 流水线不变。
- `rules-emission`:T3 扇出经新 `list_rule_jobs.py`(或共享 `list_pending.py`)取按-category pending;
  既有 `assemble_rules.py --check` 作为边界校验范式的源头,泛化到其它产物。

## Impact

- **新增脚本**(`core/scripts/`):`list_scout_batches.py`、`list_rule_jobs.py`(或 `list_pending.py`)、
  `describe_artifact.py`、各既有脚本的 `--check` 增补(discover/plan_scout/merge_scout/list_clusters)。
  全部 R2 零依赖、自定位 `sys.path`、utf-8、stdout=JSON/stderr=诊断、退出码 0/1/2(承 R5.3)。
- **新增 hook**:`releases/claude-code/hooks/block-adhoc-scripts.{sh,py}`(+ opencode 等价 / 降级)与
  `install.sh` 注入逻辑(向目标项目 `.claude/settings.json` 的 `PreToolUse.Use` 加 matcher)。
- **改动脚本**:`plan_scout.py` stdout 增 `regex_known_count` 等派生字段 + `--check`;
  `discover_controls.py`/`merge_scout.py` 增 `--check`。
- **改动提示词**:全部 `core/prompts/stages/init-*.md` 增 Sanctioned-tools 白名单 + 输入终态条款;
  `init-scout.md` 「Use your tools freely」改受限自由。
- **改动命令壳**:两份 `mgh-init.md` 编排流改刚性三元组 + 合法原语指针 + hook 声明。
- **改动 AGENTS.md**:R5.2 / R5.3(b) / R5.7 sharpen + 新增 R5.9。
- **改动契约**:`core/contracts/init/` 增 `scout-enumeration.md`、`describe.md`;`scout-plan.md` 补
  `regex_known_count` 字段。
- **新增单测**:`tests/test_list_scout_batches.py`(resume-aware pending)、`test_describe_artifact.py`
  (keys/sample/count/shape)、`test_block_adhoc_scripts.py`(hook 正则:放行合法调用、拦截内省/越权 Write)、
  `test_stage_check.py`(各 `--check` 边界)、既有 R5.1 CLI lint 扩到新脚本。
- **依赖**:零新增运行时依赖(R2)。hook 脚本仅 bash + python 标准库;不 import `vvaharness`。
- **BREAKING / 风险**:hook 注入目标项目 `.claude/settings.json` 属**跨项目侵入**——design FD4 覆盖
  opt-out(`--no-enforce-hook`)、幂等合并(不覆盖用户既有 hook)、opencode 侧 PreToolUse 支持度差异的
  降级路径、以及「自检失败只 warn 不阻断 install」(承 R5.8 fail-soft)。无 schema/数据迁移;产物全部
  additive。`/mgh-init` 既有功能与产物不变,仅收紧编排纪律。
