## Why

`/mgh-sast` 是 vvaharness 9 阶段流水线的零依赖重写,但**漏掉了上游
`design_controls` 注入**(`docs/upstream/04-completeness-gaps.md` gap #10:
`injectors/design_controls.py::load_controls`,s2/s8 消费)。当前 `/mgh-sast`
无任何控制输入 flag;而阶段 SYSTEM 提示词(s2/s3/s4/s6/s8)已**逐字保留** vvah 的
「design controls 降低 likelihood / 上游中和即 FP / 阻断 chain」措辞——威胁与 chain
的 `controls` 字段却恒为 `"none"`,提示词在等一个从未到达的输入。与此同时 `/mgh-init`
已能产出 `controls_inventory.json`(`core/contracts/init/inventory.md`,`controls[]`
与 vvah `design_controls` 后向兼容),正好填补该输入。让 `/mgh-sast` 消费它,可降低
FP、对齐上游保真度,并打通 `mgh-init → mgh-sast` 的控制流闭环。

## What Changes

- 两份 `mgh-sast.md`(claude + opencode)新增**可选** flag `--controls <path>`
  (指向 `controls_inventory.json`)。不传 = 现有行为字节级不变(additive,无 BREAKING)。
- 新增确定性叶脚本 `core/scripts/load_controls.py`:读 inventory + **intake 校验** +
  按扫描 scope(`--repo`/`--path`/`--package`/`--diff` 派生的 `in_scope[]`)用 `protects`/
  `entry_points` fnmatch **投影**出 in-scope 控制子集;stdout 结构化 JSON、stderr 诊断、
  退出码 `0/1/2`;带 `--check <inventory>`(R5.9 intake 边界校验)。
- 编排器把投影后的 `controls_bundle` 注入 s2/s3/s4/s6/s8 subagent 的**任务消息**——
  **不改动移植的 SYSTEM 提示词正文**(R1:控制走任务消息,提示词已预留消费位)。
- 新增 fragment `core/prompts/fragments/controls-context.md`(rewrite-original):规定
  subagent 如何消费控制摘要 + 诚实边界(存在≠有效,CVE-2025-41248)。
- 新增契约 `core/contracts/sast/controls-intake.md`:`load_controls.py` stdout shape +
  注入各阶段的 `controls_bundle` shape。
- 诚实披露:`run_manifest.json` + `report.md` 增控制来源与「存在≠有效」边界;无 controls
  时显式声明「未注入控制」。

## Capabilities

### New Capabilities

- `sast-control-intake`:`/mgh-sast` 消费 `/mgh-init` 产出的安全设计控制
  (`controls_inventory.json`),按 scope 投影后注入 s2/s3/s4/s6/s8,用于降低威胁
  likelihood、判定上游中和型 FP、阻断被控制覆盖的 exploit chain。

### Modified Capabilities

<!-- 无。mgh-sast 此前无 spec;control-discovery / rules-emission / distribution-purity 不变。 -->

## Impact

- **新增脚本**:`core/scripts/load_controls.py`(R2 零依赖、自定位 `sys.path`、utf-8、
  stdout=JSON / stderr=诊断、退出码 `0/1/2`、`--check`)。
- **改动命令壳**:两份 `mgh-sast.md` 加 `--controls` flag + 编排流 intake 步骤 + 注入点。
- **新增提示词 fragment**:`core/prompts/fragments/controls-context.md`(原创;不动
  `core/prompts/stages/*.md` 正文)。
- **新增契约**:`core/contracts/sast/controls-intake.md`。
- **改动产物**:`run_manifest.json` / `report.md` 增控制边界披露(additive)。
- **新增单测**:`tests/test_load_controls.py`(intake 校验、scope 投影、`--check` 边界);
  扩 `tools/check_contracts.py` 断言新 flag/脚本。
- **依赖**:零新增运行时依赖(R2);不 `import vvaharness`。
- **正交性**:与 `harden-mgh-sast-orchestration-discipline` 逻辑正交,可任意顺序 apply;
  同时 apply 时双壳改动落在不同段落,无冲突。
