## ADDED Requirements

### Requirement: T3 原生派发与 rulewriter 原生孪生

opencode 面的 T3(按类别出规则)SHALL 按当前全局默认接入原生派发(缺省原生;子进程仅画像
显式 `runner` 回退):`list_rule_jobs` pending → 计划物化 → 波次纪律(与聚合层共用同一纪
律;默认经派发工具,缺席回退通道 A)。原生孪生 `init-rulewriter-native`(mode: subagent)
SHALL 镜像其子进程孪生的全部行为契约,并具有以下**独有**权限边界:

1. 它是评审类原生孪生中**唯一带文件写权限**者(规则文件必须落盘);其写目标 SHALL 落在
   init 运行域的受信子树内(规则输出目录 + 运行目录),越树写在运行域守卫处被拦(守卫既有
   语义,零改动);
2. done/failed 的**正向判定语义不变**(按前向 marker 判定,NEVER 从文件名反推);孤儿审计
   (glob 降级时的清单告警)语义不变;
3. `assemble_rules.py --check` 的收口契约不变——原生形态产出的规则文件与子进程形态同一校
   验器把关。

#### Scenario: 原生 T3 产规则与子进程形态可比

- **WHEN** 同一 t2 产物分别经原生与子进程 T3 出规则
- **THEN** 两形态产出的规则文件结构一致,均通过 `assemble_rules.py --check`——换派发不换
  产物契约

#### Scenario: rulewriter 写权限限受信子树

- **WHEN** 原生 rulewriter 孪生尝试写受信子树之外的路径(越树形态)
- **THEN** 运行域守卫以退出码 2 拦截并给 recipe——唯一带写权限的孪生仍被既有写侧约束收
  口,权限边界不因原生形态放宽

#### Scenario: 失败规则单元缺口披露

- **WHEN** 某规则类别单元失败且重派一轮再败
- **THEN** 该类别进入缺口披露(最终规则集如实标注缺哪些类别),孤儿审计照常——失败语义
  与覆盖披露不因通道不同而漂移
