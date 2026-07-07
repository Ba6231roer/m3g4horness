## ADDED Requirements

### Requirement: Accept optional controls inventory flag

`/mgh-sast` SHALL 接受**可选** flag `--controls <path>`,指向一份 `controls_inventory.json`
(`/mgh-init` 产出,`core/contracts/init/inventory.md` 约定的 `controls[]` schema)。该 flag 与既有
`--repo`/`--diff`/`--path`/`--package` 等**正交、可组合**,不构成 mutex。未传 `--controls` 时,
流水线 SHALL 以**既有行为**运行(零控制注入),不报致命错。`--help` / 无 actionable 参数时 SHALL
打印含 `--controls` 的 flag 表并停止。flag 语义在 claude-code 与 opencode 两份 `mgh-sast.md` 中
**逐字镜像**(承 R5.1:`--help` 即 CLI 契约)。

#### Scenario: Valid controls inventory is accepted
- **WHEN** 用户运行 `mgh-sast --repo ./svc --controls ./.mgh-init/controls_inventory.json`
- **THEN** 编排器读取并 intake 校验该 inventory,把投影后的控制注入 controls-aware 阶段

#### Scenario: Flag omitted preserves legacy behavior
- **WHEN** 用户运行 `mgh-sast --repo ./svc`(不带 `--controls`)
- **THEN** 流水线以既有行为运行,零控制注入,不报致命错;manifest 声明「未注入控制」

#### Scenario: Missing inventory file is advisory, not fatal
- **WHEN** `--controls` 指向的路径不存在
- **THEN** 编排器 stderr warn 并以「无控制」继续(advisory),不阻断扫描

#### Scenario: Help lists the new flag in both shells
- **WHEN** 审阅 claude-code 与 opencode 两份 `mgh-sast.md` 的 flag 表
- **THEN** 两壳均显式列出 `--controls <path>` 且语义一致

### Requirement: Deterministic controls intake and scope projection

`/mgh-sast` SHALL 提供确定性叶脚本 `core/scripts/load_controls.py`,作为控制 intake 与 scope 投影
的唯一入口。其 SHALL:`--inventory <path>` 读取 inventory;`--repo <root>` + 可选 `--in-scope <file>`
(扫描的 `in_scope[]`,全仓扫描时缺省=全仓;`--diff`/`--path`/`--package` scope 由编排器经
`diff_seed.py`/`expand_scope.py` 派生后传入)做 **scope 投影**——对每条控制按其 `protects`(fnmatch
globs)与 `entry_points`(文件路径)与 `in_scope[]` 求交,标 `in_scope: bool`;stdout 输出结构化
`controls_bundle`(含 `in_scope[]` 控制摘要、`out_of_scope_count`、`total`、`inventory_path`),
stderr 仅诊断/进度,退出码 `0/1/2`。`kind` 别名(`authn`/`authz`/`rbac`/`waf`/`seccomp`/...)SHALL
归一到 vvah 6 枚举(`auth`/`sandbox`/`input-validation`/`aslr`/`cfi`/`other`),与 init 归一一致。
脚本 MUST 自定位 `sys.path`、utf-8 读入、零第三方依赖、任意 cwd 可 `py`(承 R5.3a)。

#### Scenario: Projects the in-scope control subset
- **WHEN** inventory 含一条 `protects: ["src/api/**"]` 的鉴权控制,且扫描 `--path src/api`
- **THEN** `controls_bundle.in_scope[]` 含该控制;`out_of_scope_count` 反映未命中数

#### Scenario: Full-repo scan marks all controls in-scope
- **WHEN** 全仓扫描(无 `--in-scope`)对一份含 5 条控制的 inventory 运行
- **THEN** `total=5` 且全部 `in_scope: true`,`out_of_scope_count=0`

#### Scenario: Rejects malformed inventory with exit 2
- **WHEN** inventory 的 `controls[]` 含一条缺 `name` 或 `kind` 非 6 枚举之一的控制
- **THEN** 脚本退出码 2,stderr 给出可操作报错,stdout 不 emit 部分结果

#### Scenario: Runs self-contained from any working directory
- **WHEN** 从非脚本目录 cwd、内网无网环境执行 `py <path>/load_controls.py --inventory <p> --repo <r>`
- **THEN** 脚本成功(自定位 `sys.path`、utf-8、零第三方依赖),stdout 为合法 JSON

### Requirement: Intake boundary check before consumption

`load_controls.py` SHALL 暴露 `--check <inventory>`,在编排器消费 inventory 前校验其 well-formed:
顶层 wrapper 合法、每条控制带 `name` + `kind`(6 枚举或可归一别名)+ 至少一个 `evidence` 锚点 +
`protects` 为 fnmatch globs。失败 MUST fail-loud(退出码 2);编排器 SHALL 回退为「无控制」继续
(advisory),并在摘要披露 intake 失败。本条兑现 R5.9 在 sast 消费侧的边界校验(范式锚点:
`validate_inventory.py`);`load_controls.py` MUST NOT `import validate_inventory`(消费侧独立实现,
避免 sast 反向依赖 init 内部)。

#### Scenario: Check passes on a well-formed inventory
- **WHEN** 编排器对刚产出的 `controls_inventory.json` 运行 `load_controls.py --check <p>`
- **THEN** 退出码 0,编排器进入 intake + 投影

#### Scenario: Check fails loud on a corrupted inventory
- **WHEN** inventory 的某条控制缺 `evidence` 锚点
- **THEN** `--check` 退出码 2,编排器回退为「无控制」继续,不带着破损 inventory 进扫描

#### Scenario: No reverse dependency on init internals
- **WHEN** 审阅 `load_controls.py` 的 import
- **THEN** 不存在 `import validate_inventory` 或对 `core/scripts` init 侧模块的跨命令依赖

### Requirement: Inject controls bundle into controls-aware stages only

编排器 SHALL 把投影后的 `controls_bundle` 注入 **s2 / s3 / s4 / s6 / s8** subagent 的任务消息
(对标 vvah `design_controls` 消费点),MUST NOT 注入 s1 / s5 / s7 / s9(s1 纯结构;s5/s7/s9 确定性、
不消费控制语义)。控制 SHALL 经**任务消息**送达,而非编辑移植的 SYSTEM 提示词正文(`core/prompts/
stages/*.md` 一字不改,R1);编排器 SHALL 在任务消息 inline fragment
`core/prompts/fragments/controls-context.md` 规定消费语义。

#### Scenario: Controls-aware stages receive the bundle via task message
- **WHEN** 编排器 spawn s2/s6/s8 subagent 且 `--controls` 已传
- **THEN** 各 subagent 的任务消息含 `controls_bundle` 与 controls-context fragment

#### Scenario: Deterministic stages are unaffected
- **WHEN** s5 prefilter / s7 dedup / s9 emit_sarif 运行
- **THEN** 它们不接收也不消费 `controls_bundle`,行为与无控制时一致

#### Scenario: Ported SYSTEM prompts are not edited
- **WHEN** 审阅 `core/prompts/stages/s2-threat-model.md` / `s6-verify.md` / `s8-chain.md` 等
- **THEN** 其正文未被本变更修改(溯源注释 `Source: vvaharness/...` 保留);控制消费走任务消息 + 新增 fragment

### Requirement: Evidence-grounded control consumption

消费控制时,subagent SHALL 把控制视为「**声称的保护**」而非「已验证的中和」:一条 finding 仅当某
控制的 `evidence` 锚点确认位于该 finding 数据流**上游**时,才判为中和型 FP;s6 的 FALSE_POSITIVE
与 s8 的 `blocked_by_controls` MUST 只填入 evidence-grounded 的控制。控制存在但**不在**该数据流
上游时,SHALL 仅降权、不中和。被控制「下架」的 finding SHALL 在 `report.md` 单列供人工复核
(存在≠有效,CVE-2025-41248)。

#### Scenario: Control on the data flow neutralizes a finding
- **WHEN** s6 复核一条注入 finding,且 `controls_bundle` 含一条 `evidence` 位于该输入路径上游的
  input-validation 控制
- **THEN** 该 finding 可标 FALSE_POSITIVE,其 `controls` 字段填该控制 `name`

#### Scenario: Control exists but off-path only downranks
- **WHEN** 一条鉴权控制存在,但其 `evidence` 不在该 finding 的数据流上游
- **THEN** finding 不被中和,仅被降权;不进入 FALSE_POSITIVE

#### Scenario: Downranked-by-control findings are surfaced for review
- **WHEN** s8 把某 chain 因控制下架(`blocked_by_controls` 非空)
- **THEN** `report.md` 单列「被控制影响」的 finding/chain 供人工复核,不静默消失

### Requirement: Disclose controls provenance and honesty boundary

`run_manifest.json` SHALL 记 `controls` 段:`source`(="mgh-init" 或 "none")、`inventory_path`、
`in_scope_count`、`out_of_scope_count`、`total`。`report.md` 与 SARIF SHALL 披露:(1) 控制为
**存在**非**有效**(引用 CVE-2025-41248);(2) 控制来源 = `/mgh-init` 的 LLM-induced 候选,**需
人工复核**;(3) scope 投影的真实数字(in_scope / out_of_scope),**不声称全量控制已验证**。未传
`--controls` 的运行 SHALL 显式声明「未注入控制」。

#### Scenario: Manifest carries control provenance
- **WHEN** 一次带 `--controls` 的扫描完成
- **THEN** `run_manifest.json.controls` 段含 `source`/`inventory_path`/`in_scope_count`/`out_of_scope_count`/`total`

#### Scenario: Report discloses existence-vs-effectiveness
- **WHEN** 审阅 `report.md` 头部边界
- **THEN** 其中明示控制为「存在」非「有效」,并引用 CVE-2025-41248 类绕过风险

#### Scenario: No-controls run declares the absence
- **WHEN** 一次未传 `--controls` 的扫描完成
- **THEN** manifest `controls.source="none"` 且 report 声明「未注入控制」

### Requirement: Zero runtime dependencies and no upstream import

`load_controls.py` 及本变更新增的任何脚本 MUST 仅用 Python ≥3.10 标准库;MUST NOT `import` 任何
`vvaharness` 模块;MUST NOT 要求任何 `pip install`(承 R2)。`controls-context.md` fragment 分发
前 MUST 经 `tools/check_distributed_purity.py` 校验,不携带研发铁律编号 / 失败 ID / 内部路径等
dev-only 悬空引用(承 R5.10)。

#### Scenario: AST scan finds no third-party imports
- **WHEN** 对 `load_controls.py` 做 AST 扫描
- **THEN** 不存在非标准库 import,且无 `import vvaharness`

#### Scenario: Fragment passes distributed-purity lint
- **WHEN** `tools/check_distributed_purity.py` 扫 `core/prompts/fragments/controls-context.md`
- **THEN** 不命中研发铁律编号(`R5.x`)/失败 ID(`FDn`)/内部路径(`.mgh-init/`)等 dev-only token
