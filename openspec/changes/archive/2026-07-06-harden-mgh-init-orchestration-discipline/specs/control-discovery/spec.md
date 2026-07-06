## MODIFIED Requirements

### Requirement: Deterministic scripts are orchestrator black boxes

`/mgh-init` 的编排器是宿主 agent 本身(按 `mgh-init.md` 用自身工具跑流水线,非写代码)。命令壳 SHALL 在正文最前列声明,且把编排纪律明线**扩展到一次性微脚本**(承
`harden-mgh-init-orchestration-discipline` FD1:真机失败形状是微脚本内省,非大编排器)。agent
**MUST NOT**(硬边界,`NEVER`):

- (a) `Write` 任何 `.py`——含大编排器(`mgh_init.py`)与**一次性微脚本**(`py -c` 产物、`_prep_scout_batches.py`、
  `_aggregate_scout.py`、`<run>_helper.py` 等);
- (b) 经 `Bash` 运行 `py -c` / `python -c` 去**内省或重派生**产物(`import json` / `open(` / `load(` 读
  `.mgh-init/**` 之类);
- (c) `Read` 叶子脚本 `.py` 源码进编排上下文(报错看 stderr)。

`Write`/`Edit` 仅用于产物。调用示例 SHALL 只传脚本声明的 flag——`--format` 由 T3 `init-rulewriter`
消费,`discover_controls.py` 不接受 `--format`。当 agent 需要「工作清单 / 瞄一眼结构 / 派生量」时,
SHALL 走 implementation-intention 句式声明的合法出口:工作清单 → `list_clusters.py` /
`list_scout_batches.py` / `list_rule_jobs.py`;瞄结构 → `describe_artifact.py`;派生量 → 该量产出者
的 stdout 字段(见「Derived counts exposed as script output」)。命令壳 SHALL 在编排流以刚性三元组
`[输入产物::字段] → script/subagent → [输出产物::字段]` 表述每个 fan-out 步骤,并在 doubt 时刻内联
1 行 shape。

#### Scenario: No orchestrator or helper script is created
- **WHEN** 宿主 agent 执行 `/mgh-init`,需要取得 scout 待跑批清单
- **THEN** agent 调用 `list_scout_batches.py`,**不** `Write` `_prep_scout_batches.py` 之类一次性 `.py`,
  也**不** `py -c "import json…"` 挖 `scout_plan.json`

#### Scenario: Discover script not passed --format
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-init.md` 中 `discover_controls.py` 的调用示例
- **THEN** 这些示例不含 `--format`;`--format` 仅出现在 T3 `init-rulewriter` 阶段的描述中

#### Scenario: Scripts invoked, not read, by the orchestrator
- **WHEN** 编排器执行 i1 发现阶段
- **THEN** `discover_controls.py` / `chunk_sources.py` / `expand_scope.py` 经 Bash 执行,其源码不被 `Read` 进编排上下文

#### Scenario: Discover accepts its documented flags
- **WHEN** 以 `discover_controls.py --repo . --out ./.mgh-init`(不带 `--format`)执行
- **THEN** argparse 不报「unrecognized argument」,脚本正常进入扫描

#### Scenario: Structure-understanding reflex routes to sanctioned primitive
- **WHEN** 编排器想确认 `controls_candidates.json` / `scout_plan.json` 的结构再动手
- **THEN** 它调用 `describe_artifact.py --keys/--sample/--shape`,**不** `py -c` 读 `[0]` 或 list keys

### Requirement: Fan out scout across parallel isolated byte-bounded batches

scout 深读 SHALL 按**隔离 fan-out**执行(对标 D12 T1→T2 同构):确定性脚本
`plan_scout.py` 对 `skeleton.json` 做噪声剪枝(复用 `EXCLUDE_DIR`)+ 去除 regex 已命中
文件后,把剩余 scout 目标按**字节预算**切批——每批累计 `bytes ≤ --scout-batch-bytes`
(默认 96KB),且分批前先按 `pkg` 排序以**包内聚**(同目录相关文件落同批),每批文件数
MUST NOT 超过 `--scout-batch-cap`(默认 40)。单个 `bytes > --scout-batch-bytes` 的文件
MUST 经既有 `chunk_sources.py` 切片入批,MUST NOT 整文件塞入单个 LLM 上下文。每批在一个
**独立 scout-reader subagent 上下文**深读,产出 `checkpoints/scout/<batch_id>.json`;全部
批次完成后由**单一 scout-merge subagent** 在**仅结构化记录、无原始码**上做去重、归一、
provisional `source` 标记 → `scout_candidates.json`。编排器 SHALL 以 `max_concurrent`
(默认 8)并行起 subagent、跑完一波起下一波,直至无 pending 批次。批数(= subagent 数)
SHALL 由 `ceil(Σtarget_bytes / batch_bytes)` **涌现而出**,而非固定常量。每批 SHALL 落
`checkpoints/scout/<batch_id>.json.done`;`--resume` MUST 跳过已 done 批次。

编排器取得「待跑批清单」MUST 经确定性叶脚本 `list_scout_batches.py`(见「Deterministic
scout-batch enumeration for fan-out」),MUST NOT 手挖 `scout_plan.json`、MUST NOT `py -c`
内省。`merge_scout.py` 折叠后,`scout_candidates.json` 与改写后的 `controls_candidates.json`
为**终态**,编排器 MUST NOT 对其二次聚合或重切批。

#### Scenario: Batches sized by bytes, co-located by package
- **WHEN** scout 目标含同一 `com/acme/security/` 包下的多个相关文件
- **THEN** `scout_plan.json` 的某批同时包含这些文件,且该批累计 bytes ≤ `--scout-batch-bytes`

#### Scenario: Oversize single file is sliced, not fed whole
- **WHEN** scout 目标含一个 250KB 的 `LegacyGuard.java`,而 `--scout-batch-bytes` 为 96KB
- **THEN** 该文件经 `chunk_sources.py` 切成函数切片入批,而非整文件塞入一个 scout-reader

#### Scenario: Batch count emerges from data, parallel waves bounded
- **WHEN** scout 目标共 ~9.6MB、`--scout-batch-bytes` 96KB、`max_concurrent` 8
- **THEN** `scout_plan.json` 产出约 100 批,编排器以每波 8 并行跑完所有批

#### Scenario: Merge operates on structured records only
- **WHEN** scout-merge 运行
- **THEN** 其输入为各 batch 的结构化候选 JSON(无原始源码),上下文规模远小于任一
  scout-reader;跨批重复报告的同一控制被去重归一

#### Scenario: Resume skips completed batches
- **WHEN** scout fan-out 中途断开,随后 `mgh-init --resume`
- **THEN** 已 done 的批次被跳过,仅继续 pending 批次,`scout_candidates.json` 最终完整

#### Scenario: Pending work-list obtained via leaf script, not hand-mining
- **WHEN** 编排器进入 scout fan-out
- **THEN** 它先调用 `list_scout_batches.py` 取 `pending[]` 再逐批扇出;不出现 `py -c` 挖 `scout_plan.json` 或 `Write _prep_scout_batches.py`

#### Scenario: Merged artifacts are terminal
- **WHEN** `merge_scout.py` 完成,`scout_candidates.json` 落盘
- **THEN** 编排器不再对其二次聚合或重切批(不出现 `_aggregate_scout.py` 之类重实现)

## ADDED Requirements

### Requirement: Deterministic scout-batch enumeration for fan-out

`/mgh-init` 的编排器 MUST 经确定性叶脚本 `core/scripts/list_scout_batches.py` 取得 scout 工作清单
(对标 T1 的 `list_clusters.py`,闭合 FD3 的扇出不对称)。`list_scout_batches.py` SHALL 读
`<target>/.mgh-init/scout_plan.json::batches[]` 并扫 `<target>/.mgh-init/checkpoints/scout/*.json.done`,
stdout 输出结构化 JSON `{repo,total,done,pending[],truncated}`,`pending[]` 每项含
`{batch_id,targets_count,bytes,needs_slice[]}`;stderr 仅诊断/进度;退出码 `0/1/2`;`--help` 即其 CLI
契约(承 R5.1)。`total = len(batches[])`,`done = #已 .done`,`pending = total − done`。脚本 MUST
自定位 `sys.path`、utf-8 读入、零第三方依赖、任意 cwd 可 `py`(承 R5.3a)。

#### Scenario: Orchestrator enumerates scout batches via the leaf script
- **WHEN** 编排器进入 scout fan-out(步骤 3b)
- **THEN** 它调用 `list_scout_batches.py` 取 `pending[]`,据此逐批扇出 `init-scout`;不出现手搓 JSON 内省

#### Scenario: list_scout_batches reports total vs done for resume
- **WHEN** 部分批已 done(`checkpoints/scout/<batch_id>.json.done` 存在)后再次运行
- **THEN** stdout 的 `done` 反映已完成批数,`pending[]` 仅含未完成批,`total = done + len(pending)`

#### Scenario: list_scout_batches is self-contained and offline
- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_scout_batches.py --scout-plan <dir>/scout_plan.json --checkpoints <dir>/checkpoints/scout` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8 读入、零第三方依赖),stdout 为合法 JSON

#### Scenario: Empty or truncated scout plan handled without silent truncation
- **WHEN** `scout_plan.json::batches[]` 为空,或 `truncated: true`
- **THEN** `list_scout_batches.py` 输出 `total:0`(空)或保留 `truncated: true`(显式告警),退出码仍 `0`,不静默丢信息

### Requirement: Sanctioned artifact-inspection primitive (no ad-hoc introspection)

`/mgh-init` SHALL 提供确定性叶脚本 `core/scripts/describe_artifact.py`,作为编排器/subagent
「瞄一眼产物结构」反射的**唯一合法出口**(专治「先理解结构再动手」的 `py -c` 反射,FD5)。其 SHALL
支持 `--in <json>` + 至少下列模式之一:`--keys`(顶层键)、`--count`(数组长度,对 wrapper dict 额外
warn 顶层键数 vs 目标数组长度,防 `len(wrapper)=3` 误判)、`--sample N`(数组首 N 项)、`--shape`(轻量
schema:键 + 类型 + 数组元素 shape)、`--field a.b.c`(取嵌套字段)。stdout = JSON 摘要;stderr = 诊断;
退出码 `0/1/2`;零依赖、自定位、utf-8、任意 cwd。编排器与 subagent MUST NOT 用 `py -c`/`python -c`
或 `Read` 整份大 JSON 去内省产物结构,SHALL 改用本脚本。

#### Scenario: Count mode warns on wrapper-dict miscount
- **WHEN** 对 `clusters.json`(wrapper `{repo,clusters,truncated}`)运行 `describe_artifact.py --count`
- **THEN** stdout 报 `clusters[]` 真实长度,并对顶层 3 键给出 warn(防把 3 当簇数)

#### Scenario: Sample mode replaces reading the first element by hand
- **WHEN** 编排器想理解 `scout_plan.json::batches[]` 元素结构
- **THEN** 它运行 `describe_artifact.py --sample 1`,而非 `py -c "import json; print(json.load(open(...))['batches'][0])"`

#### Scenario: describe_artifact is self-contained and offline
- **WHEN** 从任意 cwd 以 `py <path>/describe_artifact.py --in <dir>/controls_candidates.json --keys` 执行
- **THEN** 脚本成功,stdout 为合法 JSON 摘要

### Requirement: Derived counts exposed as script output fields

下游(编排器/subagent)可能需要 list keys / len / sample 才能得到的**派生量**,MUST 由该量的**产出者**
作为 stdout 字段 emit,而非留给下游现算(消除「自己写脚本算」的动机,FD6)。具体:`plan_scout.py`
stdout 与 `scout_plan.json` 顶层 SHALL 含 `regex_known_count`(= 已被 regex 命中、排除出 scout 的文件数,
内部 `regex_files` 已算);`discover_controls.py` stdout 摘要 SHALL 含 `big_files`、`unresolved_count`
等下游常查量(不删既有字段)。派生量字段 SHALL 在对应 `core/contracts/init/*.md` 落定。

#### Scenario: regex_known count available without re-derivation
- **WHEN** 编排器需要「多少文件已被 regex 命中、不需 scout」
- **THEN** 它读 `plan_scout.py` stdout 的 `regex_known_count`,而非 `py -c` 集合运算 `controls_candidates.json`

#### Scenario: discover summary carries downstream-queried counts
- **WHEN** `discover_controls.py` 完成
- **THEN** 其 stdout 摘要含 `big_files` 与 `unresolved_count` 等字段,供编排器直接消费

### Requirement: Runtime enforcement hook for orchestrator script discipline

`install.sh` SHALL 在镜像 `core/` 后,向目标项目 `.claude/settings.json` 的 `PreToolUse` **幂等追加**
一个 hook(`releases/claude-code/hooks/block_adhoc_scripts`),在 `/mgh-init` 运行域(由编排器起步
`export MGH_INIT_ACTIVE=1` 标记)内:拦截 `Bash` 中 `py -c`/`python -c` 且含 `import json`/`open(`/
`load(`/`\.json` 的内省模式,以及 `Write` 中 `*.py` 且不在白名单(`core/scripts`/`tests`/`tools`/
`releases/*/hooks`)的写入。命中 SHALL fail-loud(退出码 2)+ stderr recipe,指向合法出口
(`list_*`/`describe_artifact.py`/脚本 stdout 字段)。非 `MGH_INIT_ACTIVE` 会话 SHALL 直接放行(零日常
噪声)。`install.sh` SHALL 提供 `--no-enforce-hook` opt-out;`--opencode` 在无等价 PreToolUse 能力时
SHALL stderr warn 并跳过注入(fail-soft,承 R5.8),此时纪律由命令壳明线 + R5.9 边界校验兜底。本条
兑现 R5.7「能 hook 就别靠自觉」的交付物承诺。

#### Scenario: Hook blocks introspection py -c during a run
- **WHEN** `MGH_INIT_ACTIVE=1` 下编排器运行 `py -c "import json; json.load(open('.mgh-init/scout_plan.json'))"`
- **THEN** hook 以退出码 2 拦截,stderr 给出「用 list_scout_batches.py / describe_artifact.py」recipe

#### Scenario: Hook passes legitimate leaf-script invocation
- **WHEN** `MGH_INIT_ACTIVE=1` 下运行 `py .claude/mgh-core/scripts/discover_controls.py --repo . --out .mgh-init`
- **THEN** hook 放行,不误伤合法叶子调用

#### Scenario: Hook is idempotent across reinstalls
- **WHEN** 对同一目标项目连续两次 `install.sh --claude`
- **THEN** `PreToolUse` 中本工具的 matcher 只出现一次,不覆盖用户既有 hook

#### Scenario: Opt-out and opencode fallback
- **WHEN** `install.sh --no-enforce-hook`,或 `--opencode` 且无 PreToolUse 能力
- **THEN** hook 不注入(或 warn 跳过),install 仍成功(fail-soft);命令壳明线 + R5.9 校验仍生效

### Requirement: Stage-boundary contract checks

每个 stage 产物的产出者 SHALL 暴露 `--check`(或独立 validator),编排器跑完一步、进下一步前 MUST
运行之;失败 MUST fail-loud(退出码 2)并回退重跑(泛化既有 `assemble_rules.py --check` 范式,承
openspec validate-at-boundary,FD7)。覆盖:`discover_controls.py --check`(candidates/clusters wrapper
+ 每条 `source` + cluster_id 唯一)、`plan_scout.py --check`(batches 非空除非 0 target、每批 bytes≤
budget、needs_slice 仅含超批文件)、`merge_scout.py --check`(每条 `source:"scout"` + file:line)、
`validate_inventory.py`(vvah design_controls 兼容 + evidence 锚点 + category→kind 归一)、既有
`assemble_rules.py --check`(rules 纯净性)。

#### Scenario: Check passes on a well-formed artifact
- **WHEN** 编排器对刚产出的 `scout_plan.json` 运行 `plan_scout.py --check`
- **THEN** 退出码 0,编排器进入下一步

#### Scenario: Check fails loud on a corrupted artifact
- **WHEN** 某 batch 的 `bytes` 超过 `--scout-batch-bytes`(或 wrapper 损坏)
- **THEN** `--check` 退出码 2,编排器回退重跑该步,不带着破损产物继续

#### Scenario: Inventory validated against design_controls schema
- **WHEN** T2 产出 `controls_inventory.json`
- **THEN** `validate_inventory.py`(或 T2 后 check)断言 vvah 兼容字段 + 每条 evidence 锚点 + category→kind 归一,失败退出码 2

### Requirement: Subagent sanctioned-tools allowlist

每个 `core/prompts/stages/init-*.md`(及双壳 `agents/init-*.md`)SHALL 声明一个 **Sanctioned tools**
白名单:读侧 `Read`(仅 input 给定文件/slice)/ `Glob` / `Grep` 自由;脚本侧**仅** `chunk_sources.py`
(若需切片);`Write`/`Edit` 仅限该 stage 的产物文件。subagent MUST NOT `Write` 任何 `.py`、MUST NOT
`py -c`/`python -c` 内省或重派生。stage 输入产物 SHALL 视为**终态**:MUST NOT 用代码变换或重派生;
需瞄结构时 SHALL 向编排器请求 `describe_artifact.py` 输出。`init-scout.md` 现有「Use your tools
freely」SHALL 改为「Use Read/Glob/Grep freely; scripts sanctioned-list only」(治 subagent 侧写脚本,
FD8)。

#### Scenario: scout-reader does not write helper scripts
- **WHEN** `init-scout` subagent 处理一个 batch
- **THEN** 它仅用 Read/Glob/Grep + `chunk_sources.py`(若 needs_slice),不 `Write .py`、不 `py -c`

#### Scenario: Stage prompt declares the allowlist
- **WHEN** 审阅 `core/prompts/stages/init-scout.md` / `init-induct.md` / `init-synthesis.md` / `init-rulewriter.md` 等
- **THEN** 每份含一个可识别的 Sanctioned-tools 段,显式列出允许的工具/脚本并 NEVER 越界

#### Scenario: Shell agent mirrors the allowlist
- **WHEN** 审阅 claude-code 与 opencode 两份 `agents/init-*.md` 的 Hard constraints 段
- **THEN** 两壳均显式声明 subagent NEVER `Write .py` / `py -c`(双壳与 prompt 双重防线)
