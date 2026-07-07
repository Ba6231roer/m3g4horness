## Why

`/mgh-init` 经 `harden-mgh-init-orchestration-discipline`(archive)固化了编排纪律后,真机大仓
首跑的「编排器/subagent 写一次性微脚本(`py -c` 内省、`_prep_*.py`)去重派生产物」失败模式
被收敛。`/mgh-sast` 是**同一代**重写,却**停在 mgh-init 硬化之前的状态**:双壳 `mgh-sast.md`
无「编排器 = 宿主 agent 不写代码」声明、无三条 `NEVER` 明线、无 implementation-intention 出口、
无扇出枚举脚本(s4 chunks / s6 verify 拿不到 `list_*` pending → 必然手挖 `checkpoints/*.json`)、
确定性阶段(prefilter/dedup/emit_sarif)无 `--check`、无运行时 hook(既有
`block_adhoc_scripts.py` 仅在 `MGH_INIT_ACTIVE` 域内生效)。即 **mgh-init 的 FD1 失败形状在 mgh-sast
上原样存在、且无任何运行时护栏**。大仓首跑必然复现。

## What Changes

按杠杆从高到低、侵入从低到高分五层(与 `harden-mgh-init` 同构;Layer 3 复用既有 hook):

- **Layer 1 — 固化信息流(改双壳,0 新代码)**:`mgh-sast.md` 顶部声明「编排器 = 宿主 agent,
  非写代码」+ 三条 `NEVER`(a 大编排器 `mgh_sast.py` / (b) `py -c` 内省 `checkpoints/*.json`、
  `scope_manifest.json` / (c) `Read` 叶子脚本源码);编排流每个 fan-out 步骤改刚性三元组
  `[输入产物::字段] → script/subagent → [输出产物::字段]`;implementation-intention 句式;声明
  s5/s7 产物为终态。
- **Layer 2 — 补扇出枚举脚本(R2 零依赖)**:`core/scripts/list_chunks.py`(s3→s4 扇出 pending,
  镜像 `list_clusters.py`)、`core/scripts/list_verify_jobs.py`(s5→s6 扇出 pending);复用既有
  `describe_artifact.py`(harden-mgh-init 已交付)作合法瞄一眼。
- **Layer 3 — 运行时强制 hook(兑现 R5.7)**:**泛化**既有 `releases/claude-code/hooks/block_adhoc_scripts.py`
  的激活条件为 `MGH_INIT_ACTIVE=1` **OR** `MGH_SAST_ACTIVE=1`(同一 hook、同一正则;recipe 增列
  sast 合法出口 `list_chunks`/`list_verify_jobs`/`describe_artifact`)。`install.sh` 注入逻辑不变
  (hook 已注入);`mgh-sast` 编排器起步 `export MGH_SAST_ACTIVE=1`。
- **Layer 4 — subagent 纪律下沉(改 `core/prompts/stages/s*.md` + 双壳 `agents/sast-*.md`)**:
  每个 LLM 阶段加 Sanctioned-tools 白名单(Read/Glob/Grep 自由、脚本仅 `chunk_sources.py`、
  `NEVER Write .py` / `py -c`、输入产物为终态)。**追加纪律 overlay,不改 vvah 移植正文**(R1,
  与 harden-mgh-init 对 `init-*.md` 的处理一致)。
- **Layer 5 — 确定性阶段 `--check`(R5.9)+ AGENTS.md 措辞 sharpen**:prefilter/dedup/emit_sarif
  增 `--check`;R5.7「当前兑现」行扩到 /mgh-sast、R5.9「当前覆盖」行扩到 sast 确定性阶段。

## Capabilities

### New Capabilities

- `sast-orchestration-discipline`:`/mgh-sast` 的编排器纪律——编排器 = 宿主 agent(三条 `NEVER`
  明线)、扇出经 `list_chunks.py`/`list_verify_jobs.py` 枚举、确定性阶段 `--check` 边界校验、
  运行时 hook 强制、subagent sanctioned-tools 白名单。

### Modified Capabilities

<!-- 无。hook 激活域扩展以**新增** sast 侧 hook 需求落在本变更的 `sast-orchestration-discipline`
     内(同一 hook 文件、共享正则/白名单);既有 control-discovery 的 hook 需求(MGH_INIT_ACTIVE 域)
     仍成立、不改。纯净性规则不变。 -->

## Impact

- **新增脚本**(`core/scripts/`):`list_chunks.py`、`list_verify_jobs.py`(R2 零依赖、自定位、
  utf-8、stdout=JSON/stderr=诊断、退出码 `0/1/2`)。`describe_artifact.py` 已存在,直接复用。
- **改动脚本**:`prefilter.py`/`dedup.py`/`emit_sarif.py` 增 `--check`(R5.9)。
- **改动 hook**:`releases/claude-code/hooks/block_adhoc_scripts.py` 激活域扩 `MGH_SAST_ACTIVE`;
  recipe 增列 sast 出口。`install.sh` 注入逻辑不变(hook 已注入,幂等)。
- **改动提示词**:`core/prompts/stages/s1-survey.md` ... `s8-chain.md`(LLM 阶段)各**追加**
  Sanctioned-tools 段(不动 vvah 正文);双壳 `agents/sast-*.md` hard constraints 同步。
- **改动命令壳**:两份 `mgh-sast.md` 编排器纪律段 + 刚性三元组 + 终态声明 + hook 声明 +
  `export MGH_SAST_ACTIVE=1`。
- **改动 AGENTS.md**:R5.7「当前兑现」/ R5.9「当前覆盖」行扩到 /mgh-sast。
- **新增/扩测**:`tests/test_list_chunks.py`、`tests/test_list_verify_jobs.py`;扩
  `test_stage_check.py`(prefilter/dedup/emit_sarif `--check`)、`test_block_adhoc_scripts.py`
  (`MGH_SAST_ACTIVE` 路径)、`tools/check_contracts.py`(新脚本/flag)。
- **依赖**:零新增运行时依赖(R2)。不 `import vvaharness`。
- **BREAKING / 风险**:hook 激活域扩展属既有跨项目侵入的增量(幂等、opt-out `--no-enforce-hook`
  不变);无 schema/数据迁移;产物全部 additive。与 `add-mgh-sast-design-controls` 正交,可任意
  顺序 apply;同时 apply 时双壳改动在不同段落合并。
