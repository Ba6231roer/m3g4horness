## ADDED Requirements

### Requirement: 聚合层(t1/t2/scout-merge)原生派发形态

opencode 面的 t1(按簇归纳)、t2(综合)、scout-merge(分片合并)SHALL 按当前全局默认接入
原生派发(缺省原生;子进程派发仅画像显式 `runner` 时回退,回退路径行为不变)。三层共用探查
层已验证的原生纪律:计划物化(既有 tier 泛化入口,枚举器与 run 目录锚定不变)→ 波次派发
(同消息并发/`description`=短号/任务消息=任务文件内容逐字)→ 标记自写(done/failed,标记
真相源不变量沿用)→ 波次间重物化重枚举 → 失败单元至多一轮重派 → 看门狗无人值守兜底。
**通道选择**:聚合层 SHALL 默认经派发工具执行(一次工具调用按计划跑完全部波次,零 LLM 波次
回合);工具不可用(未安装/加载失败)SHALL 按 fragment 指引回退编排器波次纪律(通道 A),
两层回退(通道 A / 子进程)均显式披露。

**各层不变量(MUST 逐项保持)**:

- **t1**:pack 打包摊薄与成员/checkpoint 语义、scout 完成闸门透传、簇级 done/failed 三分计
  数不变;原生孪生 `init-induct-native`(mode: subagent,权限镜像其子进程孪生)。
- **t2**:`needs_reduce=false`(单上下文装得下)时**零派发语义保持**——不产计划、不建会
  话,与既有行为逐字节一致;rollup 路径的分片计划与 **rollup manifest 消费形态不变**(清单
  文件先行,待合并者读 manifest 永不直接展开全量路径);原生孪生 `init-synthesis-native`
  (单上下文与 rollup 两形态同一定义)。
- **scout-merge**:分片字节预算与瘦身投影语义、**任一分片失败/缺失时不 rollup 并披露**的
  语义不变;marker 感知枚举不变;原生孪生 `init-scout-merge-native`。

**resume 与披露**:`resume_state.py` / `list_steps.py` SHALL 派生聚合层原生形态的步骤与可
执行下一步(进度纯磁盘重派生);`init_manifest` 与规则产物报告 SHALL 披露实际派发形态与通
道(A/工具);claude/dsh 面维持子进程形态并显式披露分歧。

#### Scenario: t1 大规模经派发工具零 LLM 波次

- **WHEN** t1 计划含数百 pack 单元,编排器一次派发工具调用跑全部波次
- **THEN** 编排器回合数不随簇数线性增长(一次调用 + 摘要),全部 pack 的 checkpoint 语义与
  子进程形态一致——聚合规模不再是编排器回合的放大器

#### Scenario: t2 装得下仍零派发

- **WHEN** 某类别输入整体在单请求预算内(`needs_reduce=false`)
- **THEN** 原生形态下同样零建会话、零计划工件——「装得下不派」是不变量,不因换形态而丢

#### Scenario: rollup 先读 manifest

- **WHEN** t2 走 rollup 路径,待合并者消费分片摘要清单
- **THEN** 消费面是 manifest 文件路径而非全量路径数组——原生形态不复活「全量路径进上下文」
  的旧问题

#### Scenario: scout-merge 缺片不合并

- **WHEN** 某分片失败(失败标记在场)或缺失,scout-merge 层收尾
- **THEN** 不执行 rollup,缺口在产物与报告中如实披露——分片预算与缺片语义在原生形态逐字
  保持

#### Scenario: 工具缺席回退通道 A 且披露

- **WHEN** 派发插件未安装或加载失败,聚合层按 fragment 指引走编排器波次纪律
- **THEN** 波次照常推进且产物契约不变,派发形态与通道在 manifest 披露中如实记录为回退

#### Scenario: 聚合层中断续跑

- **WHEN** t1 进行到一半会话中断,恢复后按状态查询续跑
- **THEN** 已完成簇零重做,剩余簇经重物化派发,scout 完成闸门不被绕过——进度仍纯磁盘重派
  生
