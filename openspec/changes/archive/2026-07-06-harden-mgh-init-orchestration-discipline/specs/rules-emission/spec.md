## ADDED Requirements

### Requirement: Deterministic rule-job enumeration for T3 fan-out

`/mgh-init` 的编排器进入 T3 fan-out(按 category 出 rules)时,MUST 经确定性叶脚本
`core/scripts/list_rule_jobs.py` 取得按-category 的 pending 工作清单(对标 T1 的 `list_clusters.py`
与 scout 的 `list_scout_batches.py`,闭合 FD3 的三处扇出不对称)。`list_rule_jobs.py` SHALL 读
`<target>/.mgh-init/controls_inventory.json` 中的 categories(+ 对应 `--format`)并扫
`<target>/.mgh-init/checkpoints/t3/*.done`,stdout 输出结构化 JSON
`{total,done,pending[],format}`,`pending[]` 每项含 `{category,format,rule_path}`;stderr 仅诊断/进度;
退出码 `0/1/2`;`--help` 即其 CLI 契约(承 R5.1)。编排器 MUST NOT 手挖 inventory 取 category、
MUST NOT `py -c` 内省。脚本 MUST 自定位 `sys.path`、utf-8 读入、零第三方依赖、任意 cwd 可 `py`(承
R5.3a)。T3 产出的 rules SHALL 经既有 `assemble_rules.py --check`(见「Deterministic assembly and
purity lint」)做边界校验,失败 fail-loud(退出码 2)回退重跑(承 R5.9 边界校验泛化,该 `--check` 为
范式源头)。

#### Scenario: Orchestrator enumerates rule jobs via the leaf script
- **WHEN** 编排器进入 T3 fan-out(步骤 6)
- **THEN** 它先调用 `list_rule_jobs.py` 取 `pending[]` 再逐 category 扇出 `init-rulewriter`;不出现手挖 inventory 或 `py -c`

#### Scenario: list_rule_jobs reports total vs done for resume
- **WHEN** 部分 category 已 done(`checkpoints/t3/<category>.<format>.json.done` 存在)后再次运行
- **THEN** stdout 的 `done` 反映已完成 category 数,`pending[]` 仅含未完成 category,`total = done + len(pending)`

#### Scenario: list_rule_jobs is self-contained and offline
- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_rule_jobs.py --inventory <dir>/controls_inventory.json --checkpoints <dir>/checkpoints/t3 --format opencode` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8 读入、零第三方依赖),stdout 为合法 JSON

#### Scenario: Empty inventory handled without silent truncation
- **WHEN** `controls_inventory.json` 含 0 个 category
- **THEN** `list_rule_jobs.py` 输出 `total:0`,退出码仍 `0`,不静默丢信息
