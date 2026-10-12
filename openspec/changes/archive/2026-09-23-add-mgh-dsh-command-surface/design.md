# add-mgh-dsh-command-surface — Design

## Context

动机见 proposal.md。承重现状:双壳(claude/opencode)是手工对等镜像 + 契约 lint 兜底;
命令壳正文有 token 硬预算与分发纯净 lint;5 条已发布命令 = sast/init/sra/srr/sdr。

## Decisions

### D1 — 落 `.dsh/skills/`,不落 `.agents/skills/`

两个都是 dsh 项目级 skill 根。选 `.dsh/skills`(rank 100 优先级最高、语义专属 dsh):
`.agents/skills` 是跨 agent 共享根,放这里会让未适配 dsh 的其它 agent 扫到跑不通的壳
(壳内路径约定按 dsh 方言写)。冲突面:`.dsh/` 若已被用户他用,仅新增 `skills/` 子目录。

### D2 — `disable-model-invocation: true`

编排壳是全量流水线入口,模型自触发 = 用户未付出注意力却烧数万 token;召唤权归用户与
双端「用户敲斜杠」语义对等。stage 级 lazy fragments 不在 skill 面(仍是按需 Read),不受影响。

### D3 — 手写第三镜像 + lint 三面化,不做壳转换器

生成器(从 claude 壳机械转 dsh)会吞掉两类必要方言段(召唤语义、边界披露)且引入新构建
资产;现状双壳已是手写对等镜像 + lint 兜底,第三镜像沿用同模型。三面一致性用最廉价的
机器抓手:flag 集存在断言(既有契约 lint 扩扫 `releases/dsh/skills/**`)+ diff 白名单段
人工评审(spec 场景已固化)。

### D4 — change 3 落地前,dsh 壳的 fan-out 段显式降级

init/sdr/sra 的扇出步在 dsh 上暂不可派发(无 `--host dsh`、无 tier 装载)。壳内该段落加
一条 dsh 独有披露:「扇出派发面在 dsh 宿主尚未接线,运行至该步 SHALL 停并如实报告进度
在磁盘、可跨 change 恢复」——复用既有 stall/resume 语义,不假装能跑。sast 的 subagent
stage 派发同理走该披露。降级段在 change 3 收尾任务中删除(**交接备忘**:本 change 只加披露、不删——删除动作归
`add-mgh-dsh-subagent-fanout` 收尾任务;本条即挂账处,不另建指针文件)。

### D5 — 参数读取 = step 0 解析触发消息余文

dsh 把用户消息与 skill 正文一同注入当轮,编排器(= 宿主 agent)天然可见余文;不引入任何
解析脚本,与 claude 壳「从命令输入行解析 flag」的文本纪律同形。

## Risks / Trade-offs

- **[R] 三镜像漂移窗口期**(三面 lint 落地前) → 本 change 内 lint 与壳同 PR 交付。
- **[R] dsh skill 一层深扫描 + kebab-case name 约束**与未来新增命令(如 mgh-ut)兼容 →
  目录形状已按该约束设计,新增即加目录。
- **[取舍] description 三端共享**可能偏 dsh 场景过信息 → 接受,一致性优先。

## Migration Plan

纯新增方言 + install 扩面;回滚 = 删除 `<target>/.dsh/skills/mgh-*`。双壳零改动(原设计)——**apply 期
经维护者拍板的唯一例外**:mgh-sra/mgh-srr 三端壳的 Orchestration flow 段抽为 lazy fragment
(`sra-flow-{claude,opencode,dsh}.md` / `srr-flow-…`,壳留 REQUIRED SUB-SKILL 指针 + 骨架行),清存量超
5000 mid_tokens 债(原 claude sra 5460 / srr 5148、opencode sra 5101、dsh sra 5223 / srr 5013);抽取为
**整段搬家、逐字保留**,三面壳与三面 fragment 各自维持逐字镜像 parity。

## Open Questions

1. ~~dsh 对 skill 正文注入的截断策略(64KB 上下文预算是否覆盖 skill)~~
   **已关闭(tasks 1.2 实测)**:dsh 对 skill 正文**无尺寸上限**——截断只发生在技能目录的
   description 展示层,正文完整注入当轮。壳按 R5.6 token 预算自限,预期不触发。
