# fanout-dispatch Specification [MODIFIED]

## ADDED Requirements

### Requirement: 波次零推进收敛熔断

dispatcher SHALL 检测**零推进循环**:连续 N 波(默认 2,`--stall-waves N` 可配)结束时
`done + failed` 总数无任何增加、且 pending 仍非空 → 视为收敛失败,**停止派发**,以退出码 2
fail-loud;stdout 摘要 JSON SHALL 增 `stalled:true` + `stalled_pending[]`(每个卡住单元的
id + 其 `.done`/`.failed` marker 在磁盘上的实际存在性),stderr 给诊断 recipe(停止重派;
跑 `resume_state.py --check` 诊断磁盘状态;对照本摘要逐单元排查 marker 可写性/身份漂移)。
正常早退(`partial:true`)、正常完成(`partial:false`)路径行为不变(零推进检测仅在
「pending 恒非空且进度恒为零」时触发,与合法的慢波次——在飞单元尚未收敛、下一波即推进——
不相交:判定锚在**波次边界已全部收敛后**的终态计数,不是在飞中的瞬时计数)。
理由〔pending 判定与 marker 写入任何一侧身份/权限漂移都会表现为「每波全量重派、进度恒零」
——无熔断时该循环烧尽会话预算(实测:32 个超长 id 簇每波 5 并发×30min 全部重烧,wave5
起持续不收敛);熔断把无限烧钱循环确定性截断为一次可诊断的 fail-loud〕。

#### Scenario: 连续零推进触发熔断
- **WHEN** 连续 2 波结束时 `done+failed` 计数与熔断窗口起点相同、pending 非空
- **THEN** dispatcher 停止发起新波次,退出码 2,stdout `stalled:true` +
  `stalled_pending[]`(每项含 id + marker 存在性),stderr 含 resume_state 诊断 recipe

#### Scenario: 单波零推进不触发(在飞收敛中)
- **WHEN** 某波因全部单元在飞超时无 ack 结束,但下一波推进了 done 计数
- **THEN** 熔断不触发(计数窗口重置),dispatcher 照常继续

#### Scenario: 正常 partial 早退路径不受影响
- **WHEN** `--time-budget-ms` 软时限触发干净早退,本波 `done+failed` 有推进
- **THEN** 行为与熔断引入前逐字一致(退出码 0 + `partial:true`,编排器重派)

## MODIFIED Requirements

### Requirement: ack 状态机与 marker 真相源语义承接

dispatcher SHALL 承接既有 fan-out 状态语义:`ok`/`oversize` ack 或磁盘 `.done` marker → 单元
完成;`failed` ack → dispatcher 写该单元 `.failed` marker(body `{unit,reason,tier}`,`tier`
取当前 `--tier` 值;终态、不重试、不阻断当前波次);crash 无 ack 且无 marker → 单元仍
pending → `--resume` 重派(crash ≠ 确认失败)。stdout 摘要 JSON SHALL 报
`{repo, tier, total, done, failed, pending, wave, partial}`,退出码 `0/1/2`(成功含
partial/通用错/误用),stderr 进度与 stdout JSON 严格分流。dispatcher SHALL 幂等:重派已
`.done` 单元 NEVER 再 spawn(以磁盘 marker 为唯一真相源)。**marker 真相源的读取 SHALL
与其写入同源**:dispatcher 每波重派生 pending 时消费的枚举脚本 stdout,其 done/failed
判定 SHALL 由正向 marker 路径计算产生(见 `request-context-budget` 能力同名 requirement);
dispatcher SHALL NEVER 自行从记录体字段或文件名 stem 反推单元身份。

#### Scenario: failed ack 终态且不阻断

- **WHEN** 某单元 subagent 回 `failed <原因>` ack
- **THEN** dispatcher 写 `.failed` marker(body `{unit,reason,tier}`),该单元从后续波次移除,
  其余单元照常推进;stdout 摘要 `failed` 计数 +1

#### Scenario: 子进程 crash 后 resume 重派

- **WHEN** 某子进程异常退出且无任何 marker
- **THEN** 该单元无 `.failed`(crash ≠ 确认失败),`--resume` 重派时再次 spawn

#### Scenario: 已完成单元在重派生 pending 时消失

- **WHEN** 上一波某单元已写 `.json` 记录 + touch `.done` marker(含超长 id 截断编码文件名),
  dispatcher 进入下一波重派生 pending
- **THEN** 该单元不在新 `pending[]` 中(正向 marker 路径判定 done),NEVER 再次 spawn
