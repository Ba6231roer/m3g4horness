## Purpose

对 mgh-sdr「单条命令串行跑多个分支、每分支独立出报告」能力（launcher `--multi-branch`）做首次真仓端到端验证：在真实 Spring Boot 仓库上准备 3 个测试分支 + 1 个失败探针,以单条 launcher 命令串行 sweep,逐项核对规格已承诺的行为并产出问题清单。本能力约束的是**验证战役本身**的交付要求,不改动 mgh-sdr 产品行为。

## ADDED Requirements

### Requirement: 真仓测试床分支夹具

验证战役 SHALL 以 `C:/DEV/springBootTemplate`（真实 Spring Boot 仓库）为测试床,备齐 3 个测试分支（均以 `master` 为 base):既有 `sdr-dryrun`(接口聚集 + 多形态调用链形状),新建 `sdr-mb-authz`(垂直/横向越权 + 输入校验形状 + 少量非接口 standalone 文件),新建 `sdr-mb-sql-sensitive`(Mapper XML `${}` 拼接的 SQL 注入形状 + 敏感信息形状)。夹具准备 SHALL NOT 修改 `master`,且 SHALL 为每个新建分支留一份与 diff 对应的形状说明(该分支预期触发哪些复核维度),供报告核对。

#### Scenario: 三分支就绪

- **WHEN** sweep 启动前检查 `git branch` 与各分支 `git diff --stat master..<branch>`
- **THEN** 3 个分支全部存在、各自 diff 非空且形状与预置一致,`master` 无新增提交

#### Scenario: sweep 不动工作树

- **WHEN** sweep 全程执行(含失败探针分支)
- **THEN** 目标仓当前检出分支始终不变,工作树无 sweep 引入的改动(分支间切换靠 diff ref,不靠 checkout)

### Requirement: 单命令串行执行与显式宿主

真跑 SHALL 为**单条** launcher 调用:`py mgh_sdr_launch.py --repo <目标仓绝对路径> --base master --host opencode --multi-branch <清单文件>`,宿主显式钉死 opencode(维护者拍板的被测宿主);真跑前目标仓 SHALL 已安装 opencode 端分发(`.opencode/`,含命令、agent、hook 插件与 mgh-core 脚本)。清单文件 SHALL 依次含 4 行:`sdr-dryrun`、`sdr-mb-nonexistent`(故意不存在的失败探针)、`sdr-mb-authz`、`sdr-mb-sql-sensitive`。真跑前 SHALL 先以同清单同参数(加 `--dry-run`)完成一次冒烟。

#### Scenario: dry-run 冒烟

- **WHEN** 以 `--dry-run` 跑同一清单
- **THEN** 4 个分支逐个走完闸门 + 上下文准备,各自产 run 目录与编排提示词文件,零宿主 spawn、零 LLM 消耗;dry-run 对真跑的残留影响(如哨兵保留与复用行为)被如实记录

#### Scenario: 单条命令串行真跑

- **WHEN** 真跑启动
- **THEN** 4 个分支在同一 launcher 进程内逐个串行执行,输出按分支分段可辨,任一时刻至多一个宿主会话在跑

### Requirement: 失败隔离与退出码

不存在分支的失败 SHALL 是确定性早败(不 spawn 宿主、不消耗 LLM),被记录后不阻断其后的真实分支;全部跑完后 launcher SHALL 以退出码 1 结束且 stderr 含失败分支汇总列表;成功分支各自产完整报告。

#### Scenario: 探针分支失败隔离

- **WHEN** 第 2 位探针 `sdr-mb-nonexistent` 失败
- **THEN** 该分支被记为 FAILED 且原因是确定性上下文失败,第 3、4 位真实分支照常完整执行并各出报告,真实分支的产物与无失败场景等价

#### Scenario: 最终退出码与失败汇总

- **WHEN** 全部 4 个分支跑完
- **THEN** launcher 退出码为 1,stderr 有一段失败分支汇总(含 `sdr-mb-nonexistent` 及其原因),且逐分支的 ok/FAILED 行可在输出中逐一对应

### Requirement: 每分支独立产物与报告对应性

每个真实分支 SHALL 产独立 run 目录(`<repo>/.mgh-sdr/runs/<时间戳>-<分支名>/`)与独立自包含 HTML 报告 + 同源 `sdr_report_data.json` + `sdr_manifest.json`;报告内容 SHALL 与该分支自身的 diff 对应(单元、文件、维度可对上该分支预置形状)。

#### Scenario: 报告独立性与对应性

- **WHEN** 真跑完成后清点产物
- **THEN** 3 份 HTML 报告各自存在且文件名含各自分支名,任一报告的复核单元可追溯到该分支的 diff 文件与预置形状,数据 JSON 与 HTML 同源

#### Scenario: 历史残留报告不被误认

- **WHEN** 目标仓根在 sweep 前已存在旧的 `mgh-sdr-*.html` 报告文件
- **THEN** 每个分支认领的报告文件的修改时间晚于该分支 run 开始时刻;若某分支实际未产新报告,launcher 不得把历史报告记为该分支产物(若发生即记为问题)

### Requirement: 哨兵生命周期与运行域收敛

sweep 期间 `<repo>/.mgh-sdr/.active` 哨兵 SHALL 随分支生灭(每分支 run 中存在、run 后移除),全 sweep 正常结束后仓库无残留哨兵。

#### Scenario: 哨兵随分支生灭

- **WHEN** 逐分支观察哨兵文件
- **THEN** 每个分支 run 执行中哨兵存在、该分支结束后移除;全 sweep 结束后哨兵不存在,后续日常开发不被运行域守卫误拦

### Requirement: 降级路径披露被真仓验证

目标仓无存量设计基线(mgh-init rules 缺失)、敏感目录仅有 `.example` 模板——真跑 SHALL 走降级路径且如实披露:基线缺失形态、敏感目录来源为默认模板、报告含「LLM 候选非已确认漏洞」的诚实边界声明。

#### Scenario: 降级披露出现在报告与 manifest

- **WHEN** 真跑完成任一真实分支
- **THEN** 该分支 manifest 记录敏感目录来源为默认模板回退,基线缺失的降级形态在报告或 manifest 可见,报告含诚实边界声明

### Requirement: 问题清单交付

验证战役 SHALL 在本 change 目录交付 `findings.md`,内容至少含:① 每个分支的结果与关键指标(起止时间、单元数、失败计数);② 与规格预期行为的逐条比对结论(符合/偏差);③ 问题清单,每条含现象、复现方式、影响、初步定位线索;④ 观感与优化建议(非缺陷类)。每个问题条目 SHALL 信息完整到足以支撑后续独立 fix/improve change 立项,而不需要重跑才能理解。

#### Scenario: findings 可支撑后续立项

- **WHEN** 战役结束评审 findings.md
- **THEN** 规格场景逐条有「符合/偏差」结论,每个问题条目含现象/复现/影响三要素,后续 change 可直接引用条目立项而无需回访测试现场
