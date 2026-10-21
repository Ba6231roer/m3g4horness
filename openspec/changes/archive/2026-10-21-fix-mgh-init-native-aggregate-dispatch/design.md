## Context

现状与约束(动机见 proposal「Why」;原生路线前七个 change 已归档):

- 探查层接入(`fix-mgh-init-native-scout-dispatch`)已验证的模式:control-discovery 派发
  requirement 升双形态 + ADDED 波次纪律、`init-scout-native` 孪生、fragment 纪律下沉、
  实机笔记。缺省形态已被 `fix-mgh-sdr-native-default-dispatch` 翻转为「opencode 面缺省原
  生、子进程显式回退」。
- 派发工具(通道 B)已落地:`mgh_dispatch` 一次调用按计划跑完全部波次,短号进/全文出,取
  消级联与配额自限齐备;聚合层是它在此规模的首批消费者。
- 计划物化入口 tier 泛化(t1/t2/t3/scout-merge 均在既有 TIERS 表),枚举器与 run 目录锚定
  不变——本 change 对四层枚举/校验脚本零改动。
- 各层既有不变量(见 specs delta 逐项):t1 pack/闸门/三分计数;t2 零派发与 rollup
  manifest;scout-merge 分片预算与缺片不合并;t3 正向判定/孤儿审计/`--check` 收口。
- 约束:壳预算(R5.6,纪律下沉 fragment);R5.11(SDD 不引本仓私有文档路径);孪生克隆对
  账惯例;版本矩阵 = 本机 2.1.0 实机 + 企业 2.0.32 交接。

## Goals / Non-Goals

**Goals:** 四层原生接入且各层不变量逐字保持;大规模层零 LLM 波次;回退完整;产物与 runner
形态可比。

**Non-Goals:** 不动四层产出契约与校验器;不动基础件与派发工具(只读消费);不做 claude/dsh
接入与 ut-init;不在本 change 拆层(四层一个 change 收官,实机闸门分层验收控制风险——与
原规划「可拆」授权一致,若 apply 期发现面过大可按层拆任务组先行收口 scout-merge/t1)。

## Decisions

- **D1 通道默认 B、回退 A**:聚合层默认走派发工具(t1 数百 pack 是其目标场景;纪律最简——
  一次调用 + 摘要);工具缺席按 fragment 回退通道 A(探查层同构);两层回退均披露。否决
  「按单元数动态选通道」(把判定塞给编排器/弱模型,fragment 复杂化;工具对小规模同样正确)。
- **D2 t2 零派发是不变量**:needs_reduce=false 时不产计划、不建会话,与通道选择无关——
  「装得下不派」优先于「换形态」。rollup 消费面保持 manifest 文件先行。
- **D3 rulewriter-native 唯一带写权限孪生**:edit 写权限 + 既有运行域守卫受信子树约束(零
  改动),克隆对账锚「其余孪生零写权限」——权限面不因原生化放宽。
- **D4 四孪生一次齐**:induct/synthesis/scout-merge/rulewriter 四只 native 孪生同批落,克
  隆对账逐只锚;避免「层接了、孪生缺」的半态。
- **D5 壳与 fragment**:opencode 壳聚合步换原生骨架(紧凑);聚合纪律进 init 原生 fragment
  (扩既有或新增聚合节);claude/dsh 面一行分歧披露。
- **D6 跨层最小侵入**:`list_steps.py`/`resume_state.py` 增原生聚合分支(同形状扩展);
  `init_manifest` 增派发形态/通道披露;报告渲染零改动(数据源不变)。

## Risks / Trade-offs

- [四层一个 change 面大] → 分层任务组 + 分层实机验收;apply 期可按层先行合并(scout-merge
  → t1 → t2 → t3),每层产物可比性独立把关。
- [通道 B 在聚合层首次大规模真跑] → 本机中规模闸门(回合数不随簇数线性涨)+ 摘要/标记一致
  性对账;企业真仓交接。
- [rulewriter 写权限面] → 守卫越树拦截既有闸门复验(实机注入越树写样例)。
- [t2 rollup 形态多] → 零派发/单上下文/rollup 三形态各留场景锚,manifest 消费形状不变。

## Migration Plan

实现分层推进(scout-merge → t1 → t2 → t3),每层定向测试绿后进下一层;本机全链 + 故障面
闸门;企业真仓交接;回滚 = 画像显式 runner(整条流水线回子进程形态,产物互通)。

## Open Questions

- 聚合纪律是扩探查层 fragment 还是新增聚合专用 fragment——apply 期按预算 lint 与按需加载
  粒度定,契约不受影响。
