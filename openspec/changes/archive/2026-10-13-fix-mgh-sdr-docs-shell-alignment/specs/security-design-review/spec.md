## MODIFIED Requirements

### Requirement: 敏感目录复用与默认模板回退(与 sra/srr 的显式分歧)

`sensitive-data` 维度的检查清单 SHALL 按以下优先级解析:① `<repo>/.mgh-sra/sensitive_catalog.json`
存在 → 经 sibling import 复用 `sensitive_catalog` 模块解析 + 闭集校验(非法 → 退出码 2 早停,
任何 LLM token 之前);② 不存在 → **回退加载随 install 落地的默认模板**
(`.mgh-core` 内 `sensitive_catalog.json.example`,即 PIPL/GB-T 35273 37 项)作为生效目录。解析后
对象(`{version, source, categories[], items[], counts{}, directive}`)SHALL 由 `sdr_context.py`
**物化为 run 目录内的独立文件**(`<run-dir>/sensitive_catalog.json`),该文件的**绝对只读路径**
SHALL 经任务模板三元组搭载进每一个 subagent task 消息(与外部仓结论文件的路径透传同构;
编排器与 launcher 提示词 SHALL 指认该文件路径,SHALL NOT 内嵌目录对象本体——launcher 侧
NEVER 对该对象做静默截断)。manifest `sensitive_catalog_source` SHALL 记
`project|default-template`。该回退是 sdr 与 sra/srr(`null` → 6-facet 兜底)的**有意行为分歧**:
sdr 复核的是代码 diff,收窄到 6 facet 会让公司目录缺位时的敏感数据检查显著弱于默认模板;此分歧
SHALL 在本 spec、命令壳 `--help` 文案与报告诚实边界三处显式披露。

#### Scenario: 项目目录存在则复用

- **WHEN** `<repo>/.mgh-sra/sensitive_catalog.json` 存在且合法
- **THEN** 编排器以 `sensitive_catalog_source: "project"` 解析,对象物化为
  `<run-dir>/sensitive_catalog.json`,每个 subagent 的 task 消息携带该文件只读路径,subagent
  逐项查脱敏缺口并标 `catalog_key`

#### Scenario: 项目目录缺失回退默认模板

- **WHEN** `<repo>/.mgh-sra/sensitive_catalog.json` 不存在
- **THEN** 编排器以 `sensitive_catalog_source: "default-template"` 加载 `.example` 默认模板,
  物化与路径搭载同上,检查面为 PIPL/GB-T 35273 37 项;manifest 与报告披露该来源

#### Scenario: 项目目录非法早停

- **WHEN** `<repo>/.mgh-sra/sensitive_catalog.json` 存在但含未知 category
- **THEN** 编排器退出码 2 + 可操作 stderr(指向该文件的违规项),不 spawn 任何 subagent

#### Scenario: 敏感目录文件对每个维度子代理可达

- **WHEN** 主路径 run 中任一 subagent(含 sensitive-data 维度)收到任务消息
- **THEN** 消息三元组含敏感目录物化文件的绝对只读路径,该文件存在于 run 目录且内容为解析后
  目录对象(NEVER 出现「维度声称可读目录而消息中无任何搭载」的不可达形态);launcher 编排
  提示词对该文件只作路径指认,无内嵌、无截断

## ADDED Requirements

### Requirement: 分发面披露与实现事实同步

sdr 的分发面文档(三面命令壳、三面 agent 定义、dsh SKILL、任务模板、`core/contracts/sdr/**`
与 `core/contracts/hooks/**` 契约文档)对**机制存在性**的声称 SHALL 与实现事实一致:

- 声称「随消息下发/透传」的数据 SHALL 有真实搭载通道(模板占位符或三元组槽位);未接线的
  机制 SHALL 明示披露为未生效(如「收窄当前不下发:不进入评审单元的任务消息」),SHALL NOT
  声称透传/收窄已生效——契约文档与壳的披露 SHALL 互相一致,SHALL NOT 出现契约称透传、壳称
  不下发的矛盾。
- 宿主/入口能力声称 SHALL 与实现的支持面一致:launcher 的宿主支持面(opencode|claude)在
  dsh 面被引用时 SHALL 附支持面披露(dsh-only 部署直接走壳内路径),SHALL NOT 把不支持的
  宿主组合标为「首选」。
- 同一规范在三面镜像中的措辞 SHALL 语义一致且采用完整规范形(约束层级逐条可辨,如超时
  不变式的 budget/call/stall 三层),SHALL NOT 以压缩括号注形引入绑定歧义;agent 定义等静态
  分发文件 SHALL NOT 含运行时永不替换的字面模板占位符。
- 契约文档的 producer/lifecycle 描述 SHALL 覆盖全部域的实际写入器(含 sdr 域哨兵的确定性
  写入生命周期:预武装 → 协同细化 → 确定性重写 → 中途存在性校验),字段清单 SHALL 与脚本
  实际产出的字段集一致(pending[]、stdout 摘要、manifest counts 三处),SHALL NOT 含
  「写入器尚未落地」类过时表述。

#### Scenario: 壳与契约对 --dimensions 的口径一致

- **WHEN** 读者对照三面壳的 `--dimensions` 披露与 sdr 流水线契约文档的对应段
- **THEN** 两处均如实陈述「收窄经闭集校验与 manifest 记录,当前不进入评审单元的任务消息」;
  不存在「契约称透传」的矛盾表述

#### Scenario: dsh 面对 launcher 的能力披露

- **WHEN** dsh-only 部署(无 opencode/claude CLI)的读者按 SKILL 指引考虑 launcher 入口
- **THEN** SKILL 明示 launcher 仅能 spawn opencode/claude 宿主,dsh-only 部署直接走壳内
  编排路径(NEVER 把不可用组合标为首选而使用户在 host gate 处早退)

#### Scenario: 三面超时规范同形

- **WHEN** 对照三面命令壳的超时不变式段
- **THEN** 三面均为完整规范形(budget/call/stall 三层约束逐条可辨、宿主具体数值位于调用
  占位符);agent 定义中不存在运行时永不替换的字面 `{{ }}` 占位符

#### Scenario: hooks 契约覆盖 sdr 哨兵生命周期

- **WHEN** 读者仅凭 hooks 运行时契约文档理解 sdr 域哨兵的写入与校验
- **THEN** 文档给出与实现一致的确定性写入生命周期(预武装、协同细化、重写、存在性校验)
  与全部写入器清单;NEVER 得出「哨兵由编排器临时命令写入」或「确定性写入器尚未落地」的
  相反结论

### Requirement: launcher 异常路径卫生与上游产物消费防护

launcher(`mgh_sdr_launch.py`)SHALL:

- **上游 stdout 消费防护**:对子步骤脚本(`sdr_context.py` 等)的 stdout JSON 消费 SHALL
  容错——输出缺失/错形/类型不符 SHALL 转为该分支的 FAILED 记录(stderr 给原因,多分支清单
  继续后续分支,退出码语义不变),SHALL NEVER 以裸 traceback 崩溃;失败路径 SHALL NOT 留下
  「既非成功也非记录失败」的静默态(此时已写入的运行域哨兵 SHALL 被移除或按哨兵生命周期
  契约可被恢复工具检出自愈)。
- **哨兵移除路径的诚实性**:正常完成路径移除运行域哨兵;异常/中断路径的哨兵残留 SHALL 是
  可被恢复工具检出的状态(恢复入口的存在性校验给出重武装 recipe)——launcher SHALL NOT
  以「无论成败一律移除哨兵」的方式使**仍在运行的宿主 run** 失去运行域守卫;死代码外壳
  SHALL 清理(行为与既有语义一致,NEVER 借卫生之名改变哨兵生存语义)。

#### Scenario: 上游输出错形记分支失败而非崩溃

- **WHEN** 多分支 run 中某分支的 `sdr_context` stdout 为空或非 JSON
- **THEN** launcher 将该分支记 FAILED(stderr 原因:上游产物不可解析),后续分支照常执行,
  最终退出码 1;NEVER 以 traceback 中断整个清单

#### Scenario: 异常残留哨兵可自愈

- **WHEN** run 因中断残留运行域哨兵,用户随后调用恢复入口
- **THEN** 恢复入口的存在性校验检出哨兵状态并给出重武装/清理 recipe;launcher 侧无空壳
  死代码,正常路径哨兵照常移除
