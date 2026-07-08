## Why

`/mgh-init` 真机运行时,**3b-fanout(init-scout)、T1(init-induct)、T3(init-rulewriter)
的个别 subagent 会把 checkpoint 产物(`xxx.json` / 被误命名为 `xxxraw.json`)写到非项目目录**
(实测:Windows D 盘根目录)。根因不是「subagent 不守规矩」,而是**输出路径从未被钉死成一个
确定性的绝对路径值**:

- 路径在所有地方都以**模板占位符 / 相对路径**形态出现——`init-scout.md` 写
  `<target>/.mgh-init/checkpoints/scout/<batch_id>.json`、`init-induct.md` 更直接写裸相对路径
  `.mgh-init/checkpoints/t1/<cluster_id>.json`(连 `<target>` 前缀都没有)。
- **枚举脚本 `list_scout_batches.py` / `list_clusters.py` 的 stdout 根本不含路径**——`_lite()`
  只吐 `{batch_id,…}` / `{cluster_id,…}`,没有 `checkpoint_path`、没有 `done_marker`。
  (`list_rule_jobs.py` 吐了 `rule_path` 但默认 `--target .` → 仍是相对路径,且无 `done_marker`。)
- 于是路径要由**两个 agent 两次拼装**:编排器先拼、再传占位符、subagent 再拼。subagent 的 cwd
  一旦不在项目根(Windows 盘符相对解析、或宿主侧 `cd` 残留),相对路径就解析到**盘符根** → `D:\xxx.json`。

`harden-mgh-init-orchestration-discipline` 把「写微脚本内省」治住了,但**输出路径契约本身仍是软的**
(占位符 + 相对路径 + 双 agent 拼装)。本变更把「每个 fan-out 单元的输出路径」从「软模板」升级为
「枚举脚本产出的**单一权威绝对路径**」,直接兑现用户既定要求——**各 agent 的输入输出固定,流程稳定、
不靠 agent 临场拼路径 / 不靠多余文件检索**。

## What Changes

按杠杆从高到低、侵入从低到高分四层(Layer 1/2/4 纯仓库内;Layer 3 沿用既有 hook 运行域):

- **Layer 1 — 枚举脚本拥有输出路径(改 3 脚本,R2 零依赖,纯 additive stdout 字段)**:
  - `list_scout_batches.py`:pending 每项增 `checkpoint_path` + `done_marker`(从已 `.resolve()` 的
    `--checkpoints` dir + `batch_id` 拼,**绝对路径**)。
  - `list_clusters.py`:pending 每项增 `checkpoint_path` + `done_marker`(同上,用 `cluster_id`)。
  - `list_rule_jobs.py`:`rule_path` 改 `Path(target).resolve()`(绝对);pending 每项增 `done_marker`
    (`<checkpoints>/<cat>.<format>.json.done`)。
- **Layer 2 — subagent 提示词钉死路径为逐字输入字段(改 3 stage × 双壳 agent 定义)**:
  `init-scout` / `init-induct` / `init-rulewriter` 的 Input 增 `checkpoint_path`(及 `rule_path`/`done_marker`)
  为**编排器逐字给定**;Output 段改为「Write 恰好 `checkpoint_path` 字段给定的**绝对路径**,NEVER 自行拼 /
  NEVER 发明文件名 / NEVER 写相对路径 / NEVER 写盘符根」(implementation-intention 句式,硬边界 `NEVER`)。
- **Layer 4 — 编排流刚性三元组携带逐字路径(改两份 `mgh-init.md`)**:fan-out spawn 调用表述为
  `[list_* stdout::pending[].checkpoint_path] → spawn subagent({…, checkpoint_path, done_marker}) →
  [恰好写该绝对路径]`;起步 `export MGH_TARGET=<abs target>` 供 hook 判树。无占位符拼装。
- **Layer 3 — 运行时防越界 hook(承 R5.7,defense-in-depth)**:扩 `block-adhoc_scripts.py` 运行域,
  在 `MGH_INIT_ACTIVE=1` 内额外拦 `Write`/`Edit` 其 resolved 目标**不在 `MGH_TARGET` 子树内**者 →
  fail-loud(退出码 2)+ stderr recipe(指向 `checkpoint_path` 字段)。`--no-enforce-hook` opt-out 沿用;
  opencode 不支持 PreToolUse 时降级 warn + 跳过(承 R5.8 fail-soft)。
- **措辞(AGENTS.md)**:R5.3(b)「扇出即脚本枚举」**扩展**为「枚举脚本亦产出每个待跑单元的**确切绝对
  输出路径**(`checkpoint_path` + `done_marker`),编排器逐字透传、subagent 逐字写,NEVER 拼路径」;
  R5.5① 的「该做什么」补 fan-out 路径 recipe。

## Capabilities

### New Capabilities
<!-- 无新能力。输出路径钉死是横切纪律,落在既有 control-discovery(scout+T1)/ rules-emission(T3)内。 -->

### Modified Capabilities
- `control-discovery`:scout 与 T1 fan-out 的 checkpoint 输出路径从「占位符 / 相对路径、双 agent 拼装」
  **升级为枚举脚本(`list_scout_batches.py` / `list_clusters.py`)产出的单一权威绝对路径**;subagent 提示词
  与命令壳把路径当逐字输入字段处理、禁止拼路径;运行时 hook 拒绝子树外写入。下游
  `merge_scout` / `form_clusters` / `controls_inventory.json` 磁盘格式**不变**(全 additive)。
- `rules-emission`:T3 fan-out 同理——`list_rule_jobs.py` 产出绝对 `rule_path` + `done_marker`;
  `init-rulewriter` 把 `rule_path` 当逐字字段;`assemble_rules.py --check` 纯净性 lint 不变。

## Impact

- **改脚本**(`core/scripts/`):`list_scout_batches.py` / `list_clusters.py` / `list_rule_jobs.py` 增路径
  字段。全 R2 零依赖、自定位 `sys.path`、utf-8、stdout=JSON / stderr=诊断、退出码 `0/1/2`、任意 cwd 可跑(承 R5.3)。
- **改提示词**:3 个 `core/prompts/stages/init-*.md`(scout/induct/rulewriter)Input/Output 段钉死路径;
  双壳 `agents/init-*.md` Hard-constraints 段同步(双重防线)。
- **改命令壳**:两份 `mgh-init.md`(claude + opencode)fan-out 三元组 + 起步 `export MGH_TARGET`。
- **改契约**:`core/contracts/init/` `scout-enumeration.md`、`rule-jobs.md` 增 `checkpoint_path`/`done_marker`;
  新增 `cluster-enumeration.md`(T1 之前无枚举契约,只有 wrapper `clusters.md`)。
- **改 hook + 单测**:`releases/claude-code/hooks/block_adhoc_scripts.py` 增越界 Write/Edit matcher;
  `tests/test_block_adhoc_scripts.py` 增越界断言;新增/扩 `tests/test_list_scout_batches.py`、
  `test_init_clusters.py` 断言路径字段为绝对且落在 `--checkpoints` 子树。
- **改 AGENTS.md**:R5.3(b) 扩展 + R5.5① recipe。任一 `.md`/脚本改动 bump 版本号(承 R5.8)。
- **依赖**:零新增运行时依赖(R2)。不 import `vvaharness`。
- **BREAKING / 风险**:hook 把「子树外 Write/Edit」纳入拦截——属既有跨项目侵入面的**扩展**,design FD4
  覆盖 `--no-enforce-hook` opt-out、幂等、opencode 降级、fail-soft。无 schema/数据迁移;产物字段全 additive;
  `/mgh-init` 既有功能与产物不变,仅收紧输出路径契约。
