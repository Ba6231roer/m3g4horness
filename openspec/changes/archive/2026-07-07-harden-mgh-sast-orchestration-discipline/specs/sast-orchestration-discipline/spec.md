## ADDED Requirements

### Requirement: Orchestrator is host agent with three never boundaries

`/mgh-sast` 的编排器 SHALL 是宿主 agent 本身(按 `mgh-sast.md` 用自身工具跑流水线,非写代码)。
两份 `mgh-sast.md` SHALL 在正文最前列声明此点,并把编排纪律明线扩展到一次性微脚本(承
`harden-mgh-init-orchestration-discipline` FD1)。agent **MUST NOT**(硬边界,`NEVER`):

- (a) `Write` 任何 `.py`——含大编排器(`mgh_sast.py`)与一次性微脚本(`py -c` 产物、`_prep_chunks.py`、
  `_aggregate_verify.py`、`<run>_helper.py`);
- (b) 经 `Bash` 运行 `py -c`/`python -c` 去内省或重派生产物(`import json`/`open(`/`load(` 读
  `checkpoints/**`/`scope_manifest.json` 之类);
- (c) `Read` 叶子脚本 `.py` 源码进编排上下文(报错看 stderr)。

当 agent 需要「工作清单 / 瞄一眼结构 / 派生量」时,SHALL 走 implementation-intention 句式声明的
合法出口(见下列各 Requirement)。命令壳 SHALL 以刚性三元组表述每个 fan-out 步骤。

#### Scenario: No orchestrator or helper script is created
- **WHEN** 宿主 agent 执行 `/mgh-sast`,需取得 s4 待跑 chunk 清单
- **THEN** agent 调用 `list_chunks.py`,**不** `Write` `_prep_chunks.py` 之类一次性 `.py`,也**不**
  `py -c "import json…"` 挖 `checkpoints/s4_candidates.json`

#### Scenario: Leaf scripts invoked, not read
- **WHEN** 编排器执行确定性阶段
- **THEN** `prefilter.py`/`dedup.py`/`emit_sarif.py` 经 Bash 执行,其源码不被 `Read` 进编排上下文

#### Scenario: Shell declares the discipline in both formats
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-sast.md` 顶部
- **THEN** 两壳均显式声明「编排器 = 宿主 agent,非写成代码」+ 三条 `NEVER` 明线

### Requirement: Deterministic chunk enumeration for s4 fan-out

`/mgh-sast` 的编排器 MUST 经确定性叶脚本 `core/scripts/list_chunks.py` 取得 s4 工作清单(对标
mgh-init `list_clusters.py`,闭合 s4 扇出不对称)。`list_chunks.py` SHALL 读 s3 产物的 `chunks[]`
并扫 `<repo>/security-scan/checkpoints/s4/*.json.done`,stdout 输出结构化 JSON
`{repo,total,done,pending[],truncated}`,`pending[]` 每项含
`{chunk_id,files[],threat_id,hypothesis}`;stderr 仅诊断/进度;退出码 `0/1/2`;`--help` 即其 CLI
契约(承 R5.1)。`total = len(chunks[])`,`done = #已 .done`,`pending = total − done`。脚本 MUST
自定位 `sys.path`、utf-8 读入、零第三方依赖、任意 cwd 可 `py`(承 R5.3a)。

#### Scenario: Orchestrator enumerates chunks via the leaf script
- **WHEN** 编排器进入 s4 fan-out
- **THEN** 它调用 `list_chunks.py` 取 `pending[]`,据此逐 chunk 扇出 `sast-deepdive`;不出现手搓
  JSON 内省或 `Write _prep_chunks.py`

#### Scenario: list_chunks reports total vs done for resume
- **WHEN** 部分 chunk 已 done(`checkpoints/s4/<chunk_id>.json.done` 存在)后再次运行
- **THEN** stdout 的 `done` 反映已完成数,`pending[]` 仅含未完成,`total = done + len(pending)`

#### Scenario: list_chunks is self-contained and offline
- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_chunks.py --chunks <dir>/s3_chunks.json --checkpoints <dir>/checkpoints/s4` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8、零第三方依赖),stdout 为合法 JSON

#### Scenario: Empty or truncated chunks handled without silent truncation
- **WHEN** `chunks[]` 为空,或 `truncated: true`
- **THEN** `list_chunks.py` 输出 `total:0`(空)或保留 `truncated: true`(显式告警),退出码仍 `0`,
  不静默丢信息

### Requirement: Deterministic verify-job enumeration for s6 fan-out

`/mgh-sast` 的编排器 MUST 经确定性叶脚本 `core/scripts/list_verify_jobs.py` 取得 s6 工作清单(闭合
s6 扇出不对称)。`list_verify_jobs.py` SHALL 读 s5 产物 `findings[]` 并扫
`<repo>/security-scan/checkpoints/s6/*.json.done`,stdout `{repo,total,done,pending[],truncated}`,
`pending[]` 每项 `{finding_id,file,line,vuln_class,source_ref,sink_ref}`;stderr 仅诊断;退出码
`0/1/2`;`--help` 即 CLI 契约。自定位、utf-8、零依赖、任意 cwd。

#### Scenario: Orchestrator enumerates verify jobs via the leaf script
- **WHEN** 编排器进入 s6 fan-out
- **THEN** 它调用 `list_verify_jobs.py` 取 `pending[]`,据此逐 finding 扇出 `sast-verify`;不手挖
  `s5_filtered.json` 或 `py -c`

#### Scenario: list_verify_jobs is resume-aware
- **WHEN** 部分 finding 已 done 后再次运行
- **THEN** `pending[]` 仅含未完成,`total = done + len(pending)`

### Requirement: Sanctioned structure-inspection primitive reused

`/mgh-sast` 的编排器与 subagent「瞄一眼产物结构」MUST 复用既有 `core/scripts/describe_artifact.py`
(`--keys/--count/--sample/--shape/--field`,harden-mgh-init 已交付),MUST NOT 用 `py -c`/`python -c`
或 `Read` 整份大 JSON 去内省产物结构(承 mgh-init FD5,不重造)。

#### Scenario: Structure reflex routes to sanctioned primitive
- **WHEN** 编排器想确认 `scope_manifest.json` / `s3_chunks.json` 的结构再动手
- **THEN** 它调用 `describe_artifact.py --keys/--sample/--shape`,**不** `py -c` 读 `[0]` 或 list keys

### Requirement: Stage-boundary contract checks for deterministic stages

`prefilter.py` / `dedup.py` / `emit_sarif.py` 各 SHALL 暴露 `--check <artifact>`;编排器跑完每个确定性
阶段、进下一步前 MUST 运行之;失败 MUST fail-loud(退出码 2)并回退重跑(泛化 mgh-init
`assemble_rules.py --check` 范式,承 R5.9)。校验项:`prefilter.py --check <s5_filtered.json>`(每条
finding 有 `file`/`line`/`vuln_class`/`source_ref`/`sink_ref`)、`dedup.py --check <s7_findings.json>`
(去重后无明显近重复簇)、`emit_sarif.py --check <report.sarif>`(SARIF 2.1.0 合法 + 每条
`run.invocation`)。

#### Scenario: Check passes on a well-formed artifact
- **WHEN** 编排器对刚产出的 `s5_filtered.json` 运行 `prefilter.py --check`
- **THEN** 退出码 0,编排器进入下一步

#### Scenario: Check fails loud on a corrupted artifact
- **WHEN** `s7_findings.json` 的某条 finding 缺 `file`/`line`
- **THEN** `dedup.py --check` 退出码 2,编排器回退重跑,不带着破损产物继续

### Requirement: Runtime enforcement hook for the sast run-domain

`/mgh-sast` SHALL 复用既有 `releases/claude-code/hooks/block_adhoc_scripts.py`,其激活条件 SHALL
扩展为 `MGH_INIT_ACTIVE=1` **或** `MGH_SAST_ACTIVE=1`(同一 hook、同一正则、同一白名单;本条兑现
R5.7 对 /mgh-sast #1 违例的交付物)。在 `/mgh-sast` 运行域(编排器起步 `export MGH_SAST_ACTIVE=1`)
内:拦截 `Bash` 中 `py -c`/`python -c` 且含 `import json`/`open(`/`load(`/`\.json` 的内省,以及
`Write` 中 `*.py` 且不在白名单(`core/scripts`/`tests`/`tools`/`releases/*/hooks`)的写入。命中 SHALL
fail-loud(退出码 2)+ stderr recipe,recipe SHALL 列 sast 合法出口(`list_chunks`/`list_verify_jobs`/
`describe_artifact`/脚本 stdout 字段)。非两运行域 SHALL 直接放行(零日常噪声)。`install.sh` 的
hook 注入与 `--no-enforce-hook` opt-out 行为不变(hook 已由 mgh-init 注入、幂等)。

#### Scenario: Hook blocks introspection py -c during a sast run
- **WHEN** `MGH_SAST_ACTIVE=1` 下编排器运行 `py -c "import json; json.load(open('security-scan/checkpoints/s5_filtered.json'))"`
- **THEN** hook 以退出码 2 拦截,stderr 给出「用 list_verify_jobs.py / describe_artifact.py」recipe

#### Scenario: Hook passes legitimate leaf-script invocation
- **WHEN** `MGH_SAST_ACTIVE=1` 下运行 `py .claude/mgh-core/scripts/prefilter.py --in … --out …`
- **THEN** hook 放行,不误伤合法叶子调用

#### Scenario: Non-run-domain is silent
- **WHEN** 既无 `MGH_INIT_ACTIVE` 也无 `MGH_SAST_ACTIVE` 时运行任意 Bash
- **THEN** hook 退出码 0 放行,零噪声

#### Scenario: Shell sets the run-domain flag
- **WHEN** 审阅两份 `mgh-sast.md` 编排流起步
- **THEN** 两壳均含 `export MGH_SAST_ACTIVE=1` 步骤 + hook 存在/opt-out 声明

### Requirement: Subagent sanctioned-tools allowlist

每个 LLM 阶段提示词 MUST 追加一段 Sanctioned tools 白名单(覆盖 `core/prompts/stages/` 下的
`s1-survey.md`、`s2-threat-model.md`、`s3-decompose.md`、`s4-system.md`、`s6-verify.md`、`s8-chain.md`,
以及双壳 `agents/sast-*.md`)。白名单规定:读侧 `Read`(仅 input 给定文件/slice)/ `Glob` / `Grep`
自由;脚本侧仅 `chunk_sources.py`(若需切片);`Write`/`Edit` 仅限该 stage 产物。subagent MUST NOT
`Write` 任何 `.py`、MUST NOT 经 `py -c`/`python -c` 内省或重派生。stage 输入产物 SHALL 视为终态。
该 overlay 为追加纪律段,MUST NOT 改动 vvah 移植正文与 `Source: vvaharness/...` 溯源注释(R1)。

#### Scenario: deep-dive subagent does not write helper scripts
- **WHEN** `sast-deepdive` subagent 处理一个 chunk
- **THEN** 它仅用 Read/Glob/Grep + `chunk_sources.py`(若需),不 `Write .py`、不 `py -c`

#### Scenario: Stage prompt carries the allowlist without editing ported body
- **WHEN** 审阅 `core/prompts/stages/s4-system.md` / `s6-verify.md` 等
- **THEN** 每份含一个可识别的 Sanctioned-tools 段,且 vvah 移植正文 + `Source:` 溯源注释未被修改

#### Scenario: Shell agent mirrors the allowlist
- **WHEN** 审阅 claude-code 与 opencode 两份 `agents/sast-*.md` 的 Hard constraints 段
- **THEN** 两壳均显式声明 subagent NEVER `Write .py` / `py -c`

### Requirement: Rigid fan-out triplets and terminal-state declarations

两份 `mgh-sast.md` 的编排流 SHALL 以刚性三元组 `[输入产物::字段] → script/subagent →
[输出产物::字段]` 表述每个 fan-out 步骤(s3 chunks→s4、s5 findings→s6),并在 doubt 时刻内联 1 行
shape。`s5_filtered.json` / `s7_findings.json` SHALL 被声明为**终态**——不再二次聚合/重切(不出现
`_aggregate_verify.py` 之类重实现)。

#### Scenario: Fan-out steps expressed as rigid triplets
- **WHEN** 审阅两份 `mgh-sast.md` 的 s4 / s6 fan-out 段
- **THEN** 它们以 `[产物::字段] → script/subagent → [产物::字段]` 表述,且指向 `list_chunks.py` /
  `list_verify_jobs.py` 取 pending

#### Scenario: Merged artifacts declared terminal
- **WHEN** 审阅编排流的 s5/s7 步骤
- **THEN** `s5_filtered.json` / `s7_findings.json` 被显式声明为终态,禁止二次聚合

### Requirement: Deterministic-script CLI contract compliance

`prefilter.py`/`dedup.py`/`emit_sarif.py`/`list_chunks.py`/`list_verify_jobs.py` SHALL 遵守 R5.3(b)
CLI I/O 契约:`stdout`=结构化 JSON、`stderr`=诊断/进度**严格分流**;退出码 `0/1/2`(成功/通用错/误用);
闭集参数拒歧义输入 + 可操作报错;`--help` 即 CLI 契约面。命令壳调用示例 SHALL 与脚本 `--help`
逐字镜像(承 R5.1,经 `tools/check_contracts.py` 断言)。

#### Scenario: stdout/stderr are strictly separated
- **WHEN** 任一确定性脚本运行
- **THEN** stdout 仅含结构化 JSON 摘要,诊断/进度仅在 stderr

#### Scenario: Exit codes follow 0/1/2
- **WHEN** 脚本成功 / 遇通用错 / 误用 flag
- **THEN** 退出码分别为 0 / 1 / 2

#### Scenario: Contract lint covers new scripts and flags
- **WHEN** 运行 `tools/check_contracts.py`
- **THEN** 双壳 `mgh-sast.md` 里每个 `*.py --flag`(含 `--controls`、`list_chunks`/`list_verify_jobs`
  及各 `--check`)在对应脚本 `--help` 中存在

### Requirement: Regression test coverage and zero dependencies

本变更新增脚本 MUST 有回归单测:`tests/test_list_chunks.py`(resume-aware pending、空/截断不静默)、
`tests/test_list_verify_jobs.py`;既有 `tests/test_stage_check.py` SHALL 扩到 `prefilter`/`dedup`/
`emit_sarif` `--check`;`tests/test_block_adhoc_scripts.py` SHALL 扩到 `MGH_SAST_ACTIVE` 路径(放行
合法叶子、拦截内省/越权 Write)。全部新增脚本 MUST 仅用 Python ≥3.10 标准库,MUST NOT `import
vvaharness`、MUST NOT 要求 `pip install`(承 R2)。

#### Scenario: New enumeration scripts have resume-aware tests
- **WHEN** 运行 `py tests/test_list_chunks.py` / `test_list_verify_jobs.py`
- **THEN** 部分 `.done` 时 `pending[]` 仅含未完成;空/截断显式告警

#### Scenario: Hook test covers the sast run-domain
- **WHEN** 运行 `py tests/test_block_adhoc_scripts.py`
- **THEN** 断言在 `MGH_SAST_ACTIVE=1` 下放行合法叶子调用、拦截 `py -c` 内省与越权 `Write *.py`

#### Scenario: AST scan finds no third-party imports
- **WHEN** 对新增脚本做 AST 扫描
- **THEN** 不存在非标准库 import,且无 `import vvaharness` / `from vvaharness import`
