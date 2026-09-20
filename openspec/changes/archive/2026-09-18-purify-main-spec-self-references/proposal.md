> **人话序**
>
> 打开 `openspec/specs/` 下任意一份主 spec,会读到「本变更 SHALL 使该措辞消失」「(自本变更起)」
> 「本变更生效后审阅……」这类句子。问题是:**主 spec 描述的是系统「当前」应当怎样,里面却塞满了
> 「某一次变更做了 / 没做什么」的过程叙述**。而「本变更」在主 spec 里**指不到任何东西** —— 读者
> 不知道是哪一次变更;归档目录虽然还在,但得靠自己去 `archive/` 里翻。根因是主 spec 并非手写,
> 而是历次变更归档时由 delta 合并进来的:delta 的语境是「这次要改成什么」,天然带「本变更」,
> 原样搬运就把自指词带进了长期文档。本次把这些自指表述清掉,共 20 处 / 8 个文件,分两类 ——
> 过程叙述与「(自本变更起)」时间戳标记;另有一条 requirement 通篇以「变更前」为参照,整条删除。
> 验证方式:改完全仓扫描应为 0 处(仅剩 2 处具名引用,本次有意不动);`openspec validate --specs
> --strict` 22 项全过;逐处比对确认删掉的是过程叙述、不是行为契约。

## Why

主 spec 是长期文档,读者是「未来第一次接触这个能力的人」和「据此判断实现是否符合契约的 agent」。
这两类读者都不掌握「本变更」指的是哪一次 —— 该表述在主 spec 里无法解析,是一处**悬空自指**。

这个缺陷不是手写失误,而是 **delta 合并机制的固有副作用**:delta 用「本变更」是准确的(它的语境
就是这一次变更),但归档把 delta 原样搬进主 spec 后,语境丢失,自指词变成了悬空引用。

因此本次清扫同时是一次**机制性修补**:确立「合并进主 spec 的文本以常设表述为准」这条口径,避免
同类问题在后续每次归档时继续复现。

## What Changes

按性质分两类清扫,共 20 处 / 8 个文件:

- **过程叙述(16 处)** —— 「本变更生效后审阅 X」「本变更新增的脚本」「本变更 SHALL 使…消失」等。
  删掉自指半句或改写为常设表述,行为契约原样保留。
- **时间戳标记(4 处)** —— `(自本变更起)` 括注(全在 `orchestration-substrate`)。删括注,文意不变。
- **整条 requirement 删除(1 条,计入上列 16 处内)** —— `orchestration-substrate` 的「行为保持
  ——既有回归测全绿 + mgh-init 字节级一致」。该条标题、首句、场景均以「变更前」为参照系,通篇是
  **变更相对的非目标声明**,按 spec 的定义(描述系统应当怎样)本就不该住在主 spec。
  它承载的「回归测 / 零依赖 / bump 版本号」三条要求由 `AGENTS.md` 的 R5.8 与 R2 常设承载,不丢信息。

**明确不在范围内**:名为 `improve-mgh-init-codegraph-enrichment` 等**具名**引用(2 处)保留 —— 它们
可解析,属另一档问题(主 spec 绑死单次变更),另案处理。已归档 change 的 delta 一律**不**回溯改写:
归档是冻结的历史记录。

## Capabilities

### New Capabilities

无。本次不引入任何新能力。

### Modified Capabilities

无。**这是本次 change 刻意声明的边界**:清扫只删过程叙述与括注,**不触碰任何行为契约** ——
系统对外可观测行为零变化,因此没有 capability 的行为规格需要修改。零 delta 由
`.openspec.yaml` 的 `skip_specs: true` 显式声明(而非靠发明一条假 requirement 去满足校验)。

改动直接落在 `openspec/specs/**`,由 tasks 逐处记录,可回滚、可审计。

## Impact

- **受影响文件**:`openspec/specs/` 下 8 份主 spec —— `orchestration-substrate`、
  `control-discovery`、`sast-control-intake`、`rules-emission`、`security-augmentation`、
  `sensitive-catalog`、`sast-orchestration-discipline`、`resume-step-discipline`。
- **不受影响**:`core/**`、`releases/**`、`tools/**`、`tests/**` 全部不动;无代码、无命令、无提示词、
  无契约变更。
- **分发面**:主 spec 不随 `install.sh` 分发,故本改动对目标项目零影响。
- **验证**:全仓扫描归零 + `openspec validate --specs --strict` 全过。
