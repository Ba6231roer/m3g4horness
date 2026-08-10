<!--
  Host-agnostic orchestrator discipline — the substrate shared across every mgh-*
  command shell that drives a deterministic-script + subagent fan-out pipeline
  (mgh-init today; mgh-ut-init / mgh-ut to come). Consumed via
  `REQUIRED SUB-SKILL: Use orchestrator-discipline` from each shell. The shell keeps
  its OWN stage flow, exact script names, exact product names, run-domain sentinel,
  and boundary disclosures; this fragment holds ONLY the discipline that is identical
  across hosts (claude / opencode) and across commands. Install mirrors it to
  <mgh-core>/prompts/fragments/orchestrator-discipline.md. Wording is deliberately
  generic (abstract script / product nouns) so each command's shell supplies the
  concrete instances in its stage flow.
-->

## Orchestrator discipline

编排器 = 宿主 agent,**不写代码**。确定性叶脚本经 `Bash` 执行;**NEVER `Read` 叶子 `.py` 源码进上下文**(报错看 stderr,不读源码)。

**硬边界(`NEVER`)**:(a) `Write` 任何脚本扩展名(`.py`/`.ps1`/`.sh`/`.ts`/…)——大编排器**或**一次性微脚本(`py -c` 产物、`_prep_*.py`、`_aggregate_*.py`、`<run>_helper.py`);(b) `Bash: py -c|python -c` 去内省/重派生产物(`import json` / `open(` / `load(` 读该命令运行目录 `**`);(c) `Read` 叶子 `.py` 源码。

**`NEVER` 向系统临时目录写中间文件再回读**:编排器 MUST NOT 把确定性脚本 stdout 重定向到磁盘文件再回读——尤其 `$env:TEMP` / `%TEMP%` / `/tmp` / `TMPDIR`。Bash tool result 已含 stdout,**直接从工具返回值取 JSON(最后一行)、在你的推理里解析 `pending[]`**;**NEVER** 用文件中介。同一条 Bash 调用内「写 temp + 回读」的配对模式视为违纪。

**implementation-intention(需 X → 触发器 Y,NEVER `py -c`)**——每个常被手搓的需求都有合法出口:
- **取确定性脚本的 JSON 输出** → 经 Bash 跑该脚本、从工具返回值取 stdout(最后一行是 JSON)、在你的推理里解析 `pending[]`;**NEVER** 把 stdout 重定向到磁盘文件、**NEVER** `$env:TEMP`/`%TEMP%`/`/tmp`/`TMPDIR`;
- **每步确切脚本路径 / 调用行 / IO shape** → 该命令的 step-enumeration 脚本 stdout(或 `--step <id>` 单步);宿主前缀自动派生,**NEVER** 猜 `scripts/` vs `mgh-core/scripts/`、**NEVER** 漏宿主前缀;
- **subagent 用的绝对工具脚本路径**(大文件切片等共享工具)→ step-enumeration 脚本 stdout `script_abs`(`__file__` 派生 = 当前 install 的 `<mgh-core>/scripts/` 目录);step 0 取该绝对基,把绝对工具路径**逐字透传**进 subagent task(subagent 用该绝对路径 verbatim;**NEVER** 裸名、**NEVER** 相对 `<mgh-core>/scripts/…`——多层 install 下相对路径可解析到**别的**旧副本;**NEVER** 从 `--target` 拼、**NEVER** 从 mid-session env 读);
- **工作清单(fan-out 待办)** → 该命令的 `list_*` 枚举脚本(每个 fan-out tier 一个);
- **某 fan-out 单元的完整记录** → `list_* --materialize <inputs/<tier>>` stdout `pending[]` 每项的 `input_path`(绝对,subagent **自读**;≤ 单元字节预算);**NEVER** 整份读该 tier 的聚合产物(编排器只装 slim 分页待办壳)、**NEVER** `py -c`、**NEVER** 把记录体内联塞进 subagent task(只透传 `input_path`);
- **某 fan-out 单元的输出路径** → `list_*` stdout `pending[]` 每项的 `checkpoint_path` / `rule_path`(视 tier 而定,或该命令 `list_*` 为该 tier 暴露的等价输出路径字段;均**绝对**)+ `done_marker` + `failed_marker` + `slice_dir`(大文件切片输出目录);**NEVER** 自拼 `<target>/<id>`、**NEVER** `py -c` 算路径、**NEVER** 相对路径;切片 `--out` = `<slice_dir>/<safe-stem>.slice.json`(subagent 写 + 回读该确切绝对路径;NEVER 相对 `--out`、NEVER cwd/Temp 派生、NEVER 树外);
- **fan-out 单元 `failed` ack**(subagent 回 `failed <原因>`)→ 编排器 `Write` 该单元 `failed_marker`(= `list_*` stdout `pending[].failed_marker`,绝对、**逐字透传**、body `{unit,reason,tier}`;**NEVER** 自拼 `<checkpoint_path>.failed`、**NEVER** `py -c`、**NEVER** 让 subagent 写);**不重试**该单元、**不阻断**当前波次,继续下一单元。`.failed` = **终态**(resume 不重派,区别于 `.done` 的成功完成);crash 无 ack → 无 marker → 单元仍 `pending` → 重派(crash ≠ 确认失败,安全重试非静默丢失)。tier 完成门 = `done+failed>=total`(见 resume-state 脚本 stdout `tiers`)。
- **瞄一眼结构** → artifact-inspect 脚本(各壳 stage 流给确切名;`--keys/--sample/--shape/--field`);**NEVER** `py -c`、**NEVER** `Read` 整份大 JSON;
- **派生量** → 该量产出者的 stdout 字段;**NEVER** 自写脚本算。
- **当前步骤 / 下一步** → 该命令的 resume-state 脚本 stdout `step`/`next_action`/`tiers`(进度纯从磁盘该命令运行目录重派生);**NEVER** 靠对话记忆判步骤、**NEVER** `py -c` 重算、**NEVER** `Read` 整份聚合 JSON 倒推进度。`--resume` 或任何压缩事件后**第一步**调之。

**fan-out 刚性三元组**:每个 fan-out 步骤表述为 `[输入产物::字段] → script/subagent → [输出产物::字段]`;输出路径 = `list_*` stdout 的 `checkpoint_path` / `rule_path`(绝对),编排器**逐字透传**进 subagent task、subagent **恰好写该绝对路径**(零拼装、零占位符)。doubt 时刻 inline 1 行 shape(如「某 plan 产物 `::batches[]` 即你的工作清单,经该命令的 `list_*` 取;每项 `checkpoint_path` 即该批产物绝对路径」)。

**终态声明**:某 tier 的 fold-in / merge 脚本完成后,该 tier 的聚合产物为**终态**——不再二次聚合 / 重切批(不出现 `_aggregate_*.py` 之类重实现)。

**边界校验**:每个 stage 产物跑完执行 `<producer> --check`(或独立 validator 脚本);失败(退出码 2)→ 回退重跑该步,**不带着破损产物继续**。

**LLM 子代理 fan-out 产物形状闸门**(独立 validator;`/mgh-init` 的 T1 记录 validator = `validate_t1_records.py`):fan-out 波次完成后、进下游聚合前 SHALL 跑该 validator `--check`;违例(退出码 2,如形状漂移)→ 对 stdout `violations[]` 每项**外科式**失效该单元 `.done` marker(`rm <violations[].file>.done`)+ 重跑该 tier `list_*` 重枚举该单元为 pending 重派(**仅违例单元、非整波重做**);**NEVER** 带破损子代理产物进下游聚合(下游按契约字段直取,读漂移形状会静默丢弃该单元)。LLM 产物的写出编码漂移(UTF-8 BOM 等)是无损宿主产物 → 始终先跑该 validator 的无损剥离(如 `--strip-bom`,idempotent),**不**当作 shape 违例去 re-spawn(re-spawn 一个 LLM 单元去修宿主写入是浪费,且不修编码地基)。

**长跑 Bash 超时纪律**:给长跑确定性 Bash 调用传一个慷慨的 per-call `timeout`(claude Bash 与 opencode shell 工具均接受毫秒级 `timeout`,会话内即时生效——跨宿主公共杠杆,优先用之),勿依赖宿主默认超时中途强杀。对带软时限(`--time-budget-ms` 类)的长跑脚本,`timeout` 取略大于 budget;**见该脚本 stdout `partial:true` → 用 Bash 重派 `<script> ... --resume`** 推进(编排器循环、**NEVER** 写 wrapper `.py` 循环),带 sane 重派次数上界,超限则建议 `--scope`+`--merge` 分模块;`partial:false` 即该步完成、写最终产物。产物落盘均原子(`.tmp`+`os.replace`)。
- **opencode 全局 shell 超时可靠性边界**:opencode 可经环境变量提升全局 shell 超时,但**须在 opencode 启动前就绪**(会话中途 `export` 不被 opencode 插件进程继承);故 per-call `timeout`(见上)才是会话内即时生效的可靠杠杆(具体 env-var 名与 claude per-call 上限值见各壳 Always disclose)。

## Re-entrancy & compaction

> **进度真相源 = 磁盘该命令运行目录(checkpoints / `.done` / `.failed` / 产物 / 起始态 intent 文件);对话记忆只是缓存,不是真相源。** 这把 compact / crash / 新 session 三种中断坍缩为**同一种恢复路径**——「读磁盘状态 → 继续」。

1. claude `/compact` 与 opencode 自动压缩(~95% 触发)是**模型生成摘要**,**可能丢掉**命令壳灌入的编排纪律系统提示词(硬边界 / fan-out 三元组 / NEVER 拼路径)。故续跑 SHALL **NEVER** 依赖「记得自己在第几步」。
2. **`--resume` 或任何压缩事件后,编排器第一步 SHALL 调该命令的 resume-state 脚本** 从磁盘重派生 `step` + `next_action` + `tiers`,据此继续 fan-out / 下一步(见上方「当前步骤 / 下一步」recipe)。压缩后:resume-state 脚本给当前 step → 据以 step-enumeration 脚本 `--step <id>` 取确切调用行。
3. 上下文吃紧时编排器 **MAY** **干净停止**(跑完当前 fan-out 波次、落 `.done`、不留半截单元)→ **新 session `<command> --resume` 续**;此路径**优于**人工 `/compact`(后者摘要可能丢编排纪律导致执行路径偏离)。新 session 重灌命令壳 = 完整纪律提示词,进度由磁盘重派生,故 compact 是否丢提示词**无关紧要**。干净停止**亦** 移除运行域哨兵(或留待 resume step 0 重写覆盖;残留哨兵只挡脚本写、不挡 JSON/`.md`/读)。
4. 既有 per-call `timeout` + 长跑 `partial:true` + `--resume` 纪律**保持不变**。起始态 intent 文件作起始态、终态 manifest 作终态(磁盘 schema 不变)。
5. **`.failed` = 终态**(确认失败,区别于 `.done` 的成功完成):`--resume` 跳过 `.failed` 单元(**不重派**);crash 无 ack → 无 marker → 单元仍 `pending` → 重派(crash ≠ 确认失败)。escape hatch = 人工 `rm <unit>.json.failed` 后 `--resume` 重派该单元。失败计数从磁盘(resume-state 脚本 / `list_*` stdout `tiers`/`failed`)读,**NEVER** 对话记忆。
6. **fan-out 波次 run-to-completion**:任一 fan-out 波次进行中,编排器 **MUST NOT** 因规模大(数百至 ~1000 单元)停下征求用户「拆分/跳过/终止」、**SHALL** 迭代 `list_*` stdout `pending[]`(以 `max_concurrent` 并发起 subagent)跑到 `pending` 为空。规模与边界(大 fan-out 计数 / 部分覆盖 / `.failed`/跳过单元 / 残留盲区)**SHALL** 流入既有披露渠道(终态 manifest `boundaries[]` + 人读报告 + resume-state 脚本 `notes[]`)——**NEVER** 作为运行中阻塞式提问;披露计数取自磁盘 resume-state 脚本 / `list_*` stdout(**NEVER** 对话记忆)。
