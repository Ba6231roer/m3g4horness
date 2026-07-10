## Why

`/mgh-init` 让 Agent 知道「项目**已有什么**安全设计」;`/mgh-sast` 找「代码里**漏了什么**」。
但两者都在**代码已写之后**才介入。真实痛点:openspec `propose` 产出的 specs/tasks
**根本不含安全维度**——新需求设计阶段没人系统想过:敏感字段(身份证 / 银行卡)有没有
屏蔽?新接口有没有 SQLi / XSS 面?**每个接口的权限校验做了吗?横纵越权怎么处理?**
等 SAST 扫到已是事后补救(贵、且常返工)。`/mgh-sra`(Security Requirements Augmentation)
填这块:在 `propose` 之后、`apply` 之前,对变更的 specs/tasks 做**增量、非破坏性**的
安全设计补充。

两件事是 sra 的核心(不是"又一条流水线"):

1. **系统化查缺漏 + 准确接存量设计**:用一个**安全维度目录**(敏感数据 / 注入 / 认证 /
   横向越权·IDOR / 纵向越权 / 完整性 / 审计 / 限流 / 密钥配置)逐维度过变更的能力与
   requirements,产出**具体缺口**;再对每个缺口做**三信号匹配**找到该用的存量设计——
   (a) 维度契合(控制 `category` 治该维度)、(b) **业务域相似**(该控制守护的是不是同业务域
   的类似接口——「以前类似接口怎么处理越权的」)、(c) **业务事实**(这个接口哪些角色用 /
   资源归属模型)。其中 (b)(c) 已**超出代码控制层、进入业务理解**——而这部分知识常不在
   代码里(在 DB / 业务文档 / 人脑),工具运行期拿不到。
2. **问答确认 + 长期业务记忆**:为补 (c) 的盲区,sra 在分析中遇到判不出的业务事实时
   **停下来问用户**(批量收集、一次问、带默认猜测),并把答案沉淀成**项目级、跨迭代累积**
   的 `business_context.json`(角色 / 业务域 / 必屏蔽字段 / 已知接口越权范式 / 业务规则)。
   下个新变更的 sra 读这份累积记忆 → 问得更少、业务匹配更准(类似 mgh-init 把存量控制沉淀
   成 inventory,这里把**业务语义**沉淀成记忆)。

## What Changes

- **新增 `/mgh-sra` 命令**(claude + opencode 双壳),替换现有 TODO 骨架。
- **新增安全维度目录** `core/prompts/fragments/security-dimensions.md`:9 维度 ×
  (检查什么 + 典型缺口),驱动系统化缺口发现(非泛泛 OWASP 清单)。
- **新增确定性脚本** `core/scripts/prepare_augment.py`(标准库):解析变更
  (proposal/design/specs/tasks)→ `change_context.json`;`--rules` 时做**信号-1 维度契合**
  预筛(`category` 过滤 + 文件重叠 hint);载入项目级 `business_context.json`(若存在);
  枚举 per-capacity 增补工作单元(每项**绝对** draft 路径,承 R5.3b)。`--check`(R5.9)。
- **新增确定性脚本** `core/scripts/merge_augment.py`(标准库):把增补草稿**幂等合并**进
  变更 specs(受管块 `<!-- mgh-sra:begin --> … <!-- mgh-sra:end -->`)+ tasks.md,
  **非破坏性**;`--check`。
- **新增确定性脚本** `core/scripts/merge_memory.py`(标准库):把用户问答答案**幂等合并**
  进项目级 `business_context.json`(按 `fact_key` 去重累积,跨迭代);`--check`。
- **新增 stage 提示词**:`sra-clarify.md`(单上下文扫全变更,据维度目录找「分析必需但缺失」
  的业务事实 → 发澄清问,跨类去重)、`sra-augment.md`(per-capacity 扇出:逐维度查缺口 +
  三信号匹配存量控制 + 锚定增补)、`sra-consistency.md`(跨类去重定稿)。
- **新增 subagent** `sra-clarify` / `sra-augment` / `sra-consistency`(双 shell 镜像)与
  `mgh-sra` profile(`core/profiles/sra.yaml`)。
- **交互闭环**:编排器批量收集 `clarifications[]` → **暂停、一次性问用户**(每条带默认猜测,
  可秒批 / 改 / `--no-interactive` 跳过用默认)→ 答案经 `merge_memory.py` 写回记忆 → 用增补
  记忆跑 augment。
- **新增契约** `core/contracts/sra/augmentation.md`(`change_context` / draft / merge shape)
  与 `core/contracts/sra/business-context.md`(`business_context.json` + `clarification` shape)。
- **扩 `block-adhoc-scripts.py`(install 注入目标仓)** 加运行域 `MGH_SRA_ACTIVE` + 子树守卫
  (治 #1 违例 = 微脚本内省 / 越权写;`MGH_TARGET`=项目根,覆盖变更子树 + 项目记忆)。
- **新增单测** `tests/test_sra_prepare.py` / `test_sra_merge.py` / `test_sra_memory.py`。
- **诚实边界**:产物明示「增补为 LLM 候选需人工复核 / 覆盖取决于变更声明 + 已记业务事实 /
  引用控制断言存在不断言有效(承 mgh-init CVE-2025-41248)/ 记忆为用户断言非代码真相」。

## Capabilities

### New Capabilities
- `security-augmentation`: 在 openspec `propose` 之后对变更 specs/tasks 做**维度驱动的安全
  缺口分析** + **三信号语义匹配存量控制**(维度契合 / 业务域相似 / 业务事实)→ 增量、非破坏性、
  锚定既有控制的增补。定义「解析变更 → 维度查缺口 → 三信号匹配 → 幂等合并」的契约。
- `business-context-memory`: sra 分析中遇到代码 / proposal / inventory 都判不出的业务事实
  (角色 / 业务域 / 必屏蔽字段 / 已知接口越权范式 / 业务规则)时,经**批量澄清问答**沉淀为
  **项目级、跨迭代累积**的结构化记忆 `business_context.json`,供 sra 匹配(信号-3)与未来
  `/mgh-blst` 消费。定义「澄清发问 → 批量暂停问 → 记忆幂等累积 → 跨迭代复用」的契约。

### Modified Capabilities
<!-- 无。两个能力全新;control-discovery / rules-emission / sast-* 不变。 -->

## Impact

- **新增**:3 脚本 + 维度 fragment + 3 stage 提示词 + 3 subagent(双壳)+ profile + 2 契约 +
  3 单测。
- **改动**:替换两份 `mgh-sra.md` 骨架;`block-adhoc-scripts.py` 加 `MGH_SRA_ACTIVE` 运行域
  + 子树守卫;`install.sh` 纳入 sra 资产;`docs/upstream-index.md` 登记 mgh-sra = rewrite-original
  (无 vvah 源);`AGENTS.md` 状态表 `/mgh-sra` 🚧 → ✅。
- **依赖**:零新增运行时依赖(R2);不 `import vvaharness`、不 import 兄弟命令内部。
- **无 BREAKING**:新增命令 + 新增能力;现有命令 / 产物字节级不变。
- **产物消费方**:增补写进 openspec 变更本身(specs/tasks);业务记忆 `business_context.json`
  跨 sra 迭代累积,并为未来 `/mgh-blst`(据角色 / 越权范式设计业务耦合测试)预留消费口。
