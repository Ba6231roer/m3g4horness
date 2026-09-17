# Review — add-mgh-ut-init (2026-08-06)

> 评审对象:`openspec/changes/add-mgh-ut-init/`(proposal/design/tasks + `test-convention-discovery` ADDED delta + `runtime-hook-enforcement` MODIFIED delta),含全部已实现产物。
> 对照基线:`openspec/specs/runtime-hook-enforcement/spec.md`、`openspec/specs/orchestration-substrate/spec.md`、8 个新脚本 `--help`、双壳、守卫实现、`core/contracts/hooks/runtime-enforcement.md`。
> 结论:**无运行时破坏,但存在 4 条必修契约/spec 违例 + 3 条高风险建议项**,按 R5.1/R5.9 语义均需在 apply 前修正。

## 结论先行

- **健全面**:五域 hook 扩展、ut-init 受信子树集、哨兵 `out_roots` 实现、双端守卫 byte-identical、`classify --check`/均匀阈值、R5.10 纯净 lint(148 文件 0 违例)、R5.6 壳预算——全部正确,未列入本表。
- **最需警惕**:spec 与壳**承诺了实际不存在的接口**(`--language`→classify、`--config ut-init` 无 profile、`validate_test_rules.py --check` 不存在),以及 spec 自带步骤图契约与实现不一致——按 spec 实现的后续改动会被这三处带偏。
- **修复会另建 openspec change 承接**,本表即为该变更的输入。

## 必修项(MUST-FIX,apply 前需修正)

| # | 严重度 | 位置 | 问题 | 失败形状 |
| --- | --- | --- | --- | --- |
| F1 | 高 | `openspec/changes/add-mgh-ut-init/specs/test-convention-discovery/spec.md:96` + `design.md:54` + `tasks.md:38-39` | 合成边界校验器 `validate_test_rules.py` 在 capability spec delta **完全缺 Requirement/Scenario**;且 design/tasks 承诺 `--check`,脚本实际只声明 `--inventory` | 按 spec 实现的流水线无义务在 synthesize 后跑 validator,坏 rules 直入 assemble;R5.9 边界契约缺位 |
| F2 | 高 | `specs/test-convention-discovery/spec.md:75` | Re-entrant resume 阻塞序列漏 `assemble`+`mutators` 两个承重阻塞步(写成 `归类→提炼→汇总→出规则→(一致性)→完成`) | 真实序列见 `resume_ut_init_state.py:35`(…→rules→assemble→consistency→mutators→done);按 spec 实现的 resume 会跳过 assemble 门与 `default_mutators.json` 产物门,直接写终态 |
| F3 | 高 | `releases/claude-code/commands/mgh-ut-init.md:34`(opencode 镜像 `:35`) | R5.1 违例:壳称 `--language` 透传给 `classify_tests.py`,但该脚本 `--help` 无此 flag;仅 `write_ut_runconfig` 声明并持久化、无消费者 | agent 照壳把 `--language` 传给 classify → argparse unrecognized,exit 2,Step 1 中断;`check_contracts.py` 只解析 bash 围栏,此 prose 声明漏检 |
| F4 | 高 | `releases/claude-code/commands/mgh-ut-init.md:35`(opencode 镜像 `:36`) + `specs/test-convention-discovery/spec.md:6` | `--config <profile>` 默认 `ut-init` 指向不存在的 `core/profiles/ut-init.yaml`,且无任何 ut 脚本声明 `--config` | sibling 命令都有实体背书(init→`init.yaml`、sast 显式 resolve profile),ut-init 是悬空引用;agent 照 sast 模式加载 `profiles/ut-init.yaml` 落空 |

## 建议项(SHOULD-FIX,同批修复或记入后续)

| # | 严重度 | 位置 | 问题 | 失败形状 |
| --- | --- | --- | --- | --- |
| F5 | 中高 | `openspec/specs/runtime-hook-enforcement/spec.md:5` | MODIFIED delta 只改 Requirements,**Purpose 段未同步**——apply 后 spec 自相矛盾:Purpose 仍写「跨四命令」而 Requirements 已五域 | 读应用后 spec 的 AI 见「四命令」,合理推断 ut-init 不在共享 hook 契约内,与五域事实相反 |
| F6 | 中高 | `core/contracts/hooks/runtime-enforcement.md:24` | 契约把哨兵 `out_roots[]` 标注为 **init only**,但守卫与 ut 壳均对 ut-init 生效(守卫无条件遍历 `_ALLOWLIST_SUBTREES` 全部域) | 维护者照契约删守卫或省略 ut 哨兵 out_roots → 合法 `--out/--rules-dir` 自定义根被误拦(exit 2);spec delta 与契约标注互相矛盾 |
| F7 | 中 | `specs/runtime-hook-enforcement/spec.md:10`(delta) | `MGH_TARGET` 优先级「env > sentinel.target > cwd」是 spec 声明,守卫不实现:两者皆缺时**降级放行、明确不用 cwd** | env 激活但无 MGH_TARGET、哨兵无 target → spec 承诺越树写被拦,守卫实际放行全部 Write,第 5 域静默丢失写约束(基线已有,delta 重述时未对齐) |
| F8 | 中 | `specs/test-convention-discovery/spec.md:5` | Parse-arguments 契约列出 `--out` 却漏 `--rules-dir`——双壳都广告它,且 runtime-hook-enforcement delta 已依赖它进哨兵 `out_roots[]` | `--format opencode --rules-dir <custom>` 不在 spec 契约面内;自定义详述根不进 out_roots,与 F6 同因可致误拦/漏记 |
| F9 | 中 | `core/scripts/write_ut_runconfig.py:87` + `core/scripts/resume_ut_init_state.py:141` | run_config 持久化 `--uniform-sample/--hetero-sample/--language`,resume 只重读 `target/format/skip_consistency`,抽样预算**永不回流** | 首跑 `--uniform-sample 8 --hetero-sample 16`,中断后 `--resume`:list_test_groups 重回默认 4/8,用户预算静默丢失(壳宣称「--resume 免重输 flag」) |
| F10 | 中 | `core/scripts/write_ut_runconfig.py:1`(trio 拷贝) | reuse/altitude:ut 拷贝 trio 绕过共享基座已参数化的 `--run-root`,使 orchestration-substrate 的「`--run-root .mgh-ut-init` 调 write_runconfig.py」场景死亡;~420 行复用管线重复(assemble_test_rules 另 72% 重复 assemble_rules) | 原子写/marker 扫描/步骤派生引擎双份漂移,risk 段自认「~480 行重复→drift」;共享基座参数化工作落空 |

## 修复建议(承接 future change 用)

- **F1/F3/F4 同源**:「壳/spec 承诺了实际不存在的接口」。修法:要么给脚本补上对应 flag(`validate --check` 别名、`classify --language`)+ 建 `core/profiles/ut-init.yaml`,要么删掉壳与 spec 里的悬空声明。推荐后者为主(精简、与 R5.5 相合)。
- **F2**:spec delta 阻塞序列改与 `resume_ut_init_state.py` 逐字一致。
- **F5/F6/F8**:MODIFIED delta 连带改 Purpose;契约去掉「init only」;spec Parse-arguments 补 `--rules-dir`。
- **F7**:spec 措辞对齐守卫/契约(env > sentinel > degrade),或守卫补 cwd 兜底(改动面更大,倾向改 spec)。
- **F9**:resume 增加对 run_config 抽样字段的回读,或壳明确「resume 不保抽样预算」。
- **F10**:若本批做,优先把 `write_ut_runconfig` 换回共享 `write_runconfig.py --run-root .mgh-ut-init`(其余拷贝可留待 /mgh-ut 第二个消费方出现再泛化,符合决策 5 演进路径)。

## 已验证正确(未列入)

五域 env/run-root 扩展、ut-init 受信子树集、基线场景零删减、哨兵 out_roots 守卫实现、双端 byte-identical、`classify --check <dir>`/均匀阈值 0.8、`--format` 必选 + 无参 STOP、R5.10 纯净 lint、R5.6 壳预算、R5.3(b) 各脚本 `--check/--dry-run/--offset`。
