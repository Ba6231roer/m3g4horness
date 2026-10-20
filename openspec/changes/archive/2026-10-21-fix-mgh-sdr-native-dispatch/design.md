## Context

现状与约束(动机见 proposal「Why」;四个基础件 change 已归档):

- 可复用面(全部已落地,本 change 零改动它们):`env_profile.py`(画像读取,fail-closed)、
  `emit_native_plan.py`(计划物化:任务文件 + 波次表 + 短号,marker 感知的重物化即重枚举)、
  `native_watchdog.py`(常驻看门狗,根会话取 `OPENCODE_SESSION_ID` 环境变量——宿主 shell
  工具自动注入,`--run-dir`,零标记写入)、权限闸门插件(ask 在产生前关闭)。
- sdr 现行链:`list_sdr_steps.py` 步骤 kinds 只有 bash|done;fan-out 步 = `fanout_runner
  --tier sdr`;`resume_sdr_state.py` 从磁盘重派生 step/next_action;报告读 drafts+标记。
- 任务模板 `sdr-task.md` 已含 `{{failed_marker}}` 占位符,现行注释「reference only; dispatcher
  writes it on a failed ack」;`diff_group` 的 pending 字段本就含 failed_marker。**原生失败自写
  指令放进 agent 定义即可,模板与 runner 零改动**(模板头注释明确 per-unit 行为住在 agent 定
  义)。
- 现行 fanout 孪生 `sdr-review-fanout.md`:`mode: primary + hidden`(给 `opencode run --agent`
  子进程用;2.x 的 subagent 工具拒收 primary 模式)——原生形态需要 `mode: subagent` 孪生。
- 壳预算约束(R5.6):mgh-sdr 壳接近预算,波次纪律详情必须下沉 fragment 按需加载。
- 版本矩阵:本机 2.1.0 实机 + 企业 2.0.32(交接闸门)。

## Goals / Non-Goals

**Goals:**

- 原生形态端到端可用:画像 → 计划 → 波次派发 → 标记 → 重枚举 → 报告,全程无人值守闭环
  (权限闸门 + 看门狗)。
- 评审本体零漂移:六维契约、draft schema、基线投影、报告数据源与子进程形态完全同源。
- 缺省零变化:无画像时行为逐字节照旧;子进程形态永久回退。
- 三面分歧显式披露,不做静默镜像断裂。

**Non-Goals:**

- 不动检查本体(draft schema/写作纪律/基线投影/敏感目录)。
- 不做插件令牌展开(见 D3 残余防线;留后续 hardening,候选并入第 6 个 change)。
- 不做通道 B(插件派发工具)、不改 claude/dsh 面、不动四个基础件脚本与插件。
- 不做 auto 的智能解析(special-auth 在场→native 等,画像 auto 钉死现状,演进另立 change)。

## Decisions

### D1 激活 = 画像显式 native;缺省/auto/runner 一律现行形态

- **决策**:仅 `dispatch_mode: "native"` 走原生;其余(含画像缺失)走子进程形态。
- **理由**:基础件 change 已把 auto 缺省钉死为现状(规格级);首个消费方以显式 opt-in 落
  地,零意外面;企业验证通过后再议 auto 细化(另立 change)。子进程形态永久保留为回退——
  它在非 CAS 环境仍是更优解,且是企业 2.1 服务复用形态下的兜底。
- **备选否决**:auto 按 special-auth 在场切 native(隐式切换,行为可惊讶;且违反既有规格钉
  死);native 设为缺省(违背零变化承诺)。

### D2 中继形态:description=短号 + 任务体=固定句+任务文件绝对路径

- **决策**:编排器每单元的子代理调用 = `description` 填计划短号、`prompt` = 固定一句(「读
  取并逐字执行以下任务文件」)+ 任务文件绝对路径(自计划/重物化 stdout 逐字透传);路径全
  程不出现在编排器自己的生成文本里(只从工具结果复制)。
- **理由**:这是既有扇出路径纪律(R5.3b/R5.5①)在原生面的自然延伸;短号进 description 使
  人/日志/事件流可对账;本机 6 单元试点实测 6/6 逐字节转述正确(方向性证据)。
- **残余与防线(诚实)**:单路径错抄仍可能(试点非认证)。防线链:①越树漂移 → 守卫拦
  (fail-loud,2026-07 失败形态已结构性关闭);②树内错配 → 双跑浪费 + 漏者无标记回待派,
  由重枚举与至多一轮重派兜住(代价有界:一轮配额);③彻底清零 = 插件令牌展开(prompt 只
  含短号,插件按计划展开任务全文)——留后续 hardening change,本 design 明确不阻塞企业首
  验(残余是浪费型不是污染型)。

### D3 标记写者:原生子代理自写 done/failed,模板与 runner 零改动

- **决策**:`sdr-review-native` agent 定义承载两条标记指令(成功 touch `done_marker`;
  失败自写 `failed_marker`,内容 `{unit_id, reason}`)与单行回执契约(`ok/oversize/failed`,
  沿用 runner ack 形态供人与日志读;编排器不解析回执,只信磁盘)。任务模板的
  `{{failed_marker}}` 行注释保持「reference only; the dispatcher writes it」不动——子进程形
  态行为零变化;原生形态由 agent 定义补语义,两种形态失败终态等价、写者各自单一。
- **理由**:模板是双形态共享面,改它必然触碰 runner 行为(子进程子代理也会看到新指令,
  产生双写序问题);agent 定义是 per-unit 行为的钦定居所(模板头注释),原生孪生本就是独
  立文件。
- **备选否决**:改模板加失败自写行(触碰 runner,零变化承诺破);失败不写标记靠重枚举(缺
  口无终态,与既有 retry-failed/披露语义断档)。

### D4 波次循环:重跑计划物化 = 重枚举;至多一轮重派;限流等窗

- **决策**:波次间直接重跑 `emit_native_plan.py`(marker 感知,pending 重派生)+ 读其 stdout
  摘要取下一波;`.failed` 单元至多重派一轮(重枚举的 pending 会再列它一次,编排器按纪律仅
  重派一轮——纪律在壳/fragment,判定依据是标记与首轮留痕);重派再败进缺口披露。上一波
  `.failed` 原因含限流特征 → 按画像配额窗口等待后重查询,等待事实入 run 留痕。
- **理由**:重物化即重枚举,不造第二个进度账本(磁盘标记唯一真相源);重派一轮与既有
  retry-failed 纪律同构;等窗是对子进程形态「窗口重置冷却」的纪律性对偶(无进程内计时器,
  由编排器按画像参数执行)。
- **备选否决**:新造 pending 查询脚本(与计划物化重复);无限重派(失败单元烧配额循环);
  限流判定下沉脚本(把 LLM 判断混进确定性面)。

### D5 看门狗接线:后台启动、宿主注入根会话、落定自退

- **决策**:native 步开波次前以宿主 shell 的后台执行形态启动 `native_watchdog.py`,参数:
  根会话取 `OPENCODE_SESSION_ID`(宿主 shell 工具自动注入,零手工传参)、`--run-dir` 当前
  run、阈值缺省;run 落定看门狗自退;若渲染完成后仍存活,壳纪律按其自退语义等待/按 pid 停
  (纪律文本进 fragment)。编排器 NEVER 代替看门狗做会话中止。
- **理由**:根会话环境变量注入是宿主机制(源码核对),编排器零额外参数且天然正确;后台形
  态保证编排器挂住时看门狗仍活(它要兜的恰是这种);`--deadline-s`/落定自退保证不留孤儿。
- **备选否决**:前台跑看门狗(阻塞编排器);波次边界 `--once` 巡检(父被阻塞时到不了,基
  础件 change 已论证)。

### D6 步骤/恢复/报告的形态感知,最小侵入

- **决策**:`list_sdr_steps.py` 在原生形态(画像判定 + 计划工件在场佐证)把 fan-out 步展开
  为「物化(bash)→ 波次派发(编排器纪律,fragment 指针)→ 渲染(bash)」的形状并给可执行
  下一步;`resume_sdr_state.py` 的 step/next_action 派生增加原生分支(进度仍纯磁盘重派
  生,恢复指引首调状态查询的既有契约不变);`render_sdr_report.py` 增派发形态披露行(依据
  = 计划工件在场 + 画像),数据源不变。
- **理由**:三脚本的既有契约(stdout 形状/退出码/--check)是编排器与守卫的锚,原生分支以
  「同形状新增字段/新步形」落,不动既有字段语义。
- **备选否决**:为原生另起一套步骤/恢复脚本(两套真相源,镜像维护面翻倍)。

### D7 三面分歧:白名单类宿主差异 + 显式披露,不做静默断裂

- **决策**:opencode 面 `mgh-sdr.md` 增原生条件步(紧凑骨架,详情下沉新 fragment 按需加
  载,R5.6 预算不破);claude/dsh 面不动;三面在 fan-out 步各以一行如实写明当前形态支持面
  (opencode:子进程+原生;claude/dsh:子进程)。
- **理由**:三面逐字镜像的白名单本就含「主机机制事实按宿主实测定制」;原生派发当前只按
  opencode 2.x 设计与验证,把 claude/dsh 壳写成原生才是虚假披露。分歧进规格(ADDED 场景)
  与壳,镜像对账测试(若有)按白名单类豁免并锚定披露行存在。
- **备选否决**:三面同步写原生(claude/dsh 未验证,虚假);opencode 面原生详情全进壳(预
  算破)。

## Risks / Trade-offs

- [弱模型一回合发 N 个调用/逐字转述的忠实度(6 单元试点非认证)] → 方向性证据 + 防线链
  (D2)+ 故障注入闸门;企业真仓 6 单元对照是硬闸门;令牌展开插件为既知后续。
- [看门狗后台形态在宿主 shell 生命周期下的存活边界(前台子代理阻塞父会话时看门狗必须在,
  会话中止时它应随 run 收尾)] → `--deadline-s`/落定自退兜底;实机闸门含「编排器挂住时看门
  狗仍处置」用例。
- [2.0.32 与 2.1.0 的原生面差异(subagent 工具/事件字段)] → 企业闸门原失败场景 6 单元对
  照;差异回填契约版本矩阵。
- [重物化每波重写计划文件(与上波逐字节不同——pending 缩小)] → 语义即重枚举,非漂移;
  `--check` 在「有单元完成」时按设计报 stale,编排器纪律以最新物化为准。
- [壳预算回归] → fragment 下沉 + 预算 lint 入任务;新增壳文本控制在条件步骨架量级。
- [agent 孪生漂移(fanout 与 native 双生)] → 克隆对账测试锚定两者 Output schema 行一致,
  native 额外行仅失败自写指令;维护纪律入契约。

## Migration Plan

1. 实现 + 本机 2.1.0 全链与故障注入闸门;缺省零变化抽查。
2. 企业 2.0.32:CAS 真仓 6 单元对照(原失败场景;交接内网,附步骤);通过后企业画像设
   `native`。
3. 合入分发;无数据迁移(drafts/标记形状不变);回滚 = 画像改回 runner / revert 壳与脚本,
  run 目录产物两形态互通。

## Open Questions

- 等窗指示是否需要在 run 留痕中带「预计恢复时刻」(子进程形态窗口重置冷却有此披露)——
  apply 期按 fragment 文案定,不影响契约。
- 波次执行痕迹(每波起止与单元清单)是否在 run 目录留独立小文件供报告披露引用——倾向并
  入 watchdog events.jsonl 已有观测,不另造文件;apply 期定。
