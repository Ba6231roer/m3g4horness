> **人话序** 现象:大仓库「发现存量安全控制」的流水线里,探查层(几百上千个单元)已经改成
> 了原生子代理派发,但它后面的三个归纳/综合层和分片合并层还在用旧的子进程派发器——同一
> 条流水线一半新一半旧,企业内网跑到这些层就又撞上鉴权墙。根因:上一轮只接了探查层,聚合各
> 层(按簇归纳、按类别综合、分片合并)各有各的打包/预算/rollup 语义,被有意留到跑通之后再
> 接。改什么:把 t1/t2/t3/scout-merge 四个聚合层全部接上原生派发——沿用同一套计划物化与波次
> 纪律,各层既有语义一个不动(打包摊薄、装得下就零派发、分片预算、缺片不合并);给每层补
> 原生子代理定义,其中出规则的一层是唯一需要文件写权限的;大规模层默认走「一次调用跑完全
> 部波次」的派发工具,编排器不再逐波亲手循环。怎么验证:小仓全链原生跑通且产物与旧形态可
> 比;大规模层用派发工具跑、编排器回合数不随单元数线性涨;失败/缺口/续跑/预算全有披露;显
> 式画像可完整回退旧形态。

## Why

- 原生派发路线已落地六件基础与消费方 change(插件迁移/权限闸门/计划物化/看门狗/sdr 接入/
  派发工具)加探查层接入;opencode 面缺省已是原生、子进程仅显式回退。init 的聚合四层
  (t1/t2/t3/scout-merge)是最后残留的子进程派发面——企业内网整条流水线仍会在归纳阶段撞墙。
- 聚合层各层语义重、面广(打包摊薄、集群闸门、装得下零派发、分片预算、缺片不合并、规则
  写盘),这是当初有意拆两段的原因;探查层跑通后,模式(计划物化 + 波次纪律 + 原生孪生 +
  fragment)已验证,现在按同一模式收尾。
- t1 的簇量可达数百,是「编排器逐波循环」会退化的规模——派发工具(一次调用跑完全部波次,
  已归档落地)正是为此准备;聚合层是它的首批真实消费者之一。

## What Changes

- **四层接入原生派发**(opencode 面;缺省原生、子进程显式回退,与既有全局默认一致):
  - **t1(按簇归纳)**:`list_clusters` pending → 计划物化 → 波次纪律(同消息派发/标记自
    写/重物化重枚举/至多一轮重派);pack 打包摊薄、checkpoint 语义、scout 完成闸门透传全
    部不变;原生孪生 `init-induct-native`。
  - **t2(综合)**:`plan_aggregate` 分片 → 计划物化;**`needs_reduce=false` 时零派发语义保
    持**(装得下就不派、不产计划);rollup 的 manifest 消费形态不变;原生孪生
    `init-synthesis-native`(单上下文与 rollup 两形态)。
  - **t3(出规则)**:`list_rule_jobs` → 计划物化 → 波次纪律;done/failed 正向判定与孤儿审
    计语义不变;原生孪生 `init-rulewriter-native`——**唯一带文件写权限的原生评审孪生**
    (写规则文件,受运行域守卫的受信子树约束)。
  - **scout-merge(分片合并)**:分片预算与 rollup 语义不变;**缺 shard 不 rollup 并披露**
    不变;原生孪生 `init-scout-merge-native`。
- **通道选择**:聚合层默认走派发工具(一次调用跑完全部波次,零 LLM 波次回合——t1 数百
  pack 正是该工具的目标场景);工具不可用时按 fragment 指引回退通道 A(编排器波次纪律,
  与探查层同构)。
- **跨层接线**:`list_steps.py`/`resume_state.py` 聚合层原生形态派生(进度仍纯磁盘重派
  生);`init_manifest` 与规则产物报告披露实际派发形态;壳(opencode 面)聚合步换原生骨架,
  纪律详情下沉 fragment(预算不破);claude/dsh 面维持现状并披露分歧。
- **非目标**:不动四层各自的产出契约与校验器(`validate_t1_records`/`assemble_rules
  --check`/孤儿审计);不动计划物化/看门狗/派发工具/画像脚本(只读消费);不做 claude/dsh
  接入;不做 ut-init。

## Capabilities

### New Capabilities

<!-- 无。 -->

### Modified Capabilities

- `control-discovery`: ADDED「聚合层(t1/t2/scout-merge)原生派发形态」——三层的派发升级、
  各层不变量(pack/闸门/零派发/manifest/分片缺片)、通道选择与回退、标记真相源、resume 派
  生覆盖。
- `rules-emission`: ADDED「T3 原生派发与 rulewriter 原生孪生」——t3 派发升级、唯一带写权限
  孪生的权限边界(受信子树 + 守卫拦截)、正向判定与孤儿审计不变、产物可比。

## Impact

- **代码**:新增 4 个原生孪生 agent(`init-induct-native` / `init-synthesis-native` /
  `init-rulewriter-native` / `init-scout-merge-native`,均 `mode: subagent`);init 原生纪律
  fragment 扩聚合层(或新增聚合 fragment);`list_steps.py` / `resume_state.py` 聚合层原生
  分支;`init_manifest` 披露;opencode 面 `mgh-init.md` 聚合步骨架。
- **零改动面**:`native_watchdog.py` / `mgh_dispatch.ts` / `fanout_runner.py`(tier 表
  零改动)/ 四层枚举与校验脚本 / claude/dsh 壳。**apply 期修订**:`emit_native_plan.py`
  与 `env_profile.py` 实际动了——前者按根手册既有 MUST 约束(「aggregate 层接原生前
  MUST 先引入按 tier 的计划命名」)落地按 tier 计划命名 + 计划 `agent` 字段换原生孪生
  映射 + t1 pack flag 透传 + t2/scout-merge 零派发不产计划(四处均为原生语义、派发器
  源码仍零改动);后者 init 资产门从 2 资产扩为 7 资产(fail-closed 语义不变)。
- **契约**:`core/contracts/init/` 流水线契约增聚合层原生形态节;fanout 契约 native 段消费
  方清单补聚合层。
- **测试**:`test_list_clusters` / `test_plan_aggregate` / `test_list_rule_jobs` /
  `test_resume_state` / `test_list_steps` / `test_validate_t1_records` / `test_assemble_rules`
  的原生分支用例 + 孪生克隆对账 + fragment 形状锚;lint 四件套 + 壳预算 lint +
  `openspec validate --strict`。
- **实机闸门**:本机 2.1.0——小仓全链原生 smoke(发现→scout→t1→t2→t3→rules)产物与
  runner 形态可比;t1 中规模走派发工具(编排器回合数不随簇数线性涨);故障面(单层单元失
  败/scout-merge 缺 shard/中断续跑);显式画像 runner 回退抽查。企业 2.0.32 全链真仓交接
  (附步骤,不阻塞归档)。
- **VERSION/CHANGELOG**:按仓库惯例 bump。
