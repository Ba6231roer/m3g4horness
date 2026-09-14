## MODIFIED Requirements

### Requirement: 任务消息由固定模板与逐字字段填充构造

fan-out 任务消息 SHALL 由固定模板 + 逐字字段填充构造:`fanout_runner.py` 内嵌 tier
模板(t1/t3/scout 共用同一占位符替换机制),同一 run 内所有单元的任务消息除字段值外逐字节
相同;占位符替换 SHALL 是纯字符串替换(无逻辑分支、无条件拼装)。模板 SHALL 携带且仅携带
per-unit 输入字段 + 行为加载指令(行为规则单一真相源在 stage 提示词,模板 NEVER 内嵌行为
逻辑)。编排器/派发器手派路径 SHALL 从同形 stdout 字段逐字填充,NEVER 手拼。

**stage 提示词位置硬钉(防漫游)**:任务模板 SHALL 把 stage 提示词路径钉死为**唯一位置**
——`{{repo}}` 内的 mgh-core 安装路径(`{{repo}}/.claude/mgh-core/prompts/stages/<stage>.md` 或
`{{repo}}/.opencode/mgh-core/prompts/stages/<stage>.md`),并 SHALL 携带硬边界:该路径
`Read` 失败(文件不存在/不可读)时 subagent SHALL **立即**回
`failed mgh-core prompts not installed at <path>` ack,**NEVER** 到其他目录(父项目、
`/home`、`/adhome`、兄弟项目、系统目录)搜索提示词或脚本——真机形态是 mgh-core 只装在根
项目而 run 在独立子项目执行,正确行为是显式失败上浮(编排器写 `.failed`),由用户安装后
`--resume`,而非跨目录漫游。

#### Scenario: 同 run 所有批的任务消息仅字段值不同
- **WHEN** dispatcher 对同一 tier 的多个单元构造任务消息
- **THEN** 除 `{{占位符}}` 字段值外,所有消息逐字节相同(模板固定、纯替换)

#### Scenario: 越树路径在 spawn 前被拦截
- **WHEN** 枚举 stdout 的某单元路径字段解析在 target 树外
- **THEN** 该单元标 failed(reason=path-drift)且 NEVER spawn

#### Scenario: t3 任务消息携带 format 与 rule_path
- **WHEN** T3 tier 派发
- **THEN** 任务消息携带 `{{format}}` 与 `{{rule_path}}` 字段(逐字来自 stdout)

#### Scenario: stage 提示词路径在任务消息中硬钉唯一位置
- **WHEN** 审阅任一 fan-out 任务模板(t1/scout/t3 同形)
- **THEN** 模板把 stage 提示词路径钉死为 `{{repo}}` 内 mgh-core 安装路径的唯一位置表述
  (「行为定义于该文件,先 Read 并严格遵循」),并含硬边界:Read 失败 → 立即
  `failed mgh-core prompts not installed` ack、NEVER 跨目录搜索提示词/脚本

#### Scenario: mgh-core 未安装时 subagent 显式失败而非漫游
- **WHEN** mgh-core 只装在根项目、run 在独立子项目,subagent Read 模板钉死的提示词路径失败
- **THEN** subagent 回 `failed mgh-core prompts not installed at <path>` ack(编排器写
  `.failed` marker),NEVER 发起对 `/home`、`/adhome`、父项目或其他目录的任何读取
