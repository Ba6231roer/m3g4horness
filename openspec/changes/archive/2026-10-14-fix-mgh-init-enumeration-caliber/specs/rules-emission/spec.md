# fix-mgh-init-enumeration-caliber — rules-emission delta

## MODIFIED Requirements

### Requirement: Deterministic rule-job enumeration for T3 fan-out

`/mgh-init` 的编排器进入 T3 fan-out(按 category 出 rules)时,MUST 经确定性叶脚本
`core/scripts/list_rule_jobs.py` 取得按-category 的 pending 工作清单(对标 T1 `list_clusters.py` 与 scout
`list_scout_batches.py`),MUST NOT 手挖 inventory 取 category、MUST NOT `py -c` 内省、MUST NOT **整份读**
`controls_inventory.json` 进编排器上下文(完整记录经 `--materialize` 下沉到 per-unit input 文件,见
`request-context-budget`)。`list_rule_jobs.py` SHALL 读 `<target>/.mgh-init/controls_inventory.json` 的
categories(+ 对应 `--format`)+ `--rules-dir`(默认 `<target>/docs/security-controls`),done/failed
判定 SHALL 为**正向 marker 路径计算**——对每个 canonical 单元 id(`<category>.<fmt>`,单源公式)
用与物化同一共享编码函数(`init_tier.safe_unit_filename` 别名,NEVER 私有拷贝)算出
`<cat>.<fmt>.json.done/failed` 路径,`is_file()` 即终态;磁盘 marker glob SHALL 降级为**孤儿审计**
(stderr 告警不对应任何 canonical 单元的 marker,不改变 pending 语义)——与 T1/scout 两枚举器
同构,NEVER 以「记录体字段 + 文件名 stem 反推」作判定。stdout 输出结构化 JSON
`{total,done,failed,pending[],format,offset,limit,effective_limit,shrunk}`,`pending[]` 每项(slim 壳)含
`{category,format,rule_path,done_marker,input_path,bytes,oversize}`(`rule_path`/`done_marker`/`input_path`
绝对);stderr 仅诊断/进度;退出码 `0/1/2`;`--help` 即其 CLI 契约(承 R5.1)。opencode `rule_path` SHALL 为
`<abs target>/<rules-dir>/<cat>.md`。脚本 SHALL 支持 `--materialize <dir>`(把每 category 完整 controls 写到
`<dir>/<category>.input.json` + 报 `input_path`/`bytes`/`oversize`)、`--offset`/`--limit`(分页)。单 category
input `bytes` > `--max-unit-bytes` 时 SHALL 标 `oversize:true` + recipe 建议 `--scope`+`--merge`(**不**切分
category,rulewriter 需整 category 视图)。当某页字节 > `--orch-budget-bytes` 时 SHALL 自动收紧 `--limit`、报
`effective_limit`+`shrunk:true`。`init-rulewriter` SHALL 读自己的 `input_path`(一个 category 的 controls)而非
编排器内联传记录。脚本 MUST 自定位 `sys.path`、utf-8 读入、零第三方依赖、任意 cwd 可 `py`(承 R5.3a)。T3 产出
的详述文件 SHALL 经既有 `assemble_rules.py --check` 做边界校验,失败 fail-loud(退出码 2)回退重跑(承 R5.9)。

#### Scenario: Orchestrator enumerates rule jobs via the leaf script

- **WHEN** 编排器进入 T3 fan-out(步骤 6)
- **THEN** 它先调用 `list_rule_jobs.py --format <format> --materialize <inputs/t3> --rules-dir <dir>` 取
  `pending[]` 再逐 category 扇出 `init-rulewriter`,向 subagent **透传 `input_path`**;不出现手挖 inventory、
  `py -c` 或整份读 inventory

#### Scenario: done/failed 判定正向计算(与另两枚举器同构)

- **WHEN** 某 category 的 `<cat>.<fmt>.json.done` marker 在盘(其名与 canonical 单元 id 的共享编码
  一致),且磁盘另有孤儿 marker(不对应任何 inventory category)
- **THEN** 该 category 判 done、从 `pending[]` 消失;孤儿 marker 仅 stderr 告警(不抬高 `done`
  计数、不改变 pending 语义);判定 NEVER 依赖 marker 记录体字段或文件名 stem 反推

#### Scenario: list_rule_jobs reports total vs done for resume

- **WHEN** 部分 category 已 done(`checkpoints/t3/<category>.<format>.json.done` 存在)后再次运行
- **THEN** stdout 的 `done` 反映已完成 category 数,`pending[]` 仅含未完成 category,`total = done + failed + len(pending)`

#### Scenario: list_rule_jobs is self-contained and offline

- **WHEN** 从任意 cwd、内网无网环境以 `py <path>/list_rule_jobs.py --inventory <dir>/controls_inventory.json --checkpoints <dir>/checkpoints/t3 --format opencode --rules-dir <dir>/docs/security-controls --materialize <dir>/inputs/t3` 执行
- **THEN** 脚本成功(自定位 `sys.path`、utf-8 读入、零第三方依赖),stdout 为合法 JSON,per-category input 文件落 `<dir>/inputs/t3/`

#### Scenario: Empty inventory handled without silent truncation

- **WHEN** `controls_inventory.json` 含 0 个 category
- **THEN** `list_rule_jobs.py` 输出 `total:0`,退出码仍 `0`,不静默丢信息

#### Scenario: Oversize category is flagged not sharded

- **WHEN** 某 category input `bytes` > `--max-unit-bytes`
- **THEN** `list_rule_jobs.py` 标 `oversize:true` + stderr recipe 建议 `--scope`+`--merge`;**不**切分 category

#### Scenario: Work-list page shrinks to the orchestrator budget

- **WHEN** 一页 `pending[]` 序列化字节 > `--orch-budget-bytes`
- **THEN** `list_rule_jobs.py` 自动收紧 `--limit`,stdout 报 `effective_limit` + `shrunk:true`,编排器翻页
