## Why

`docs/review-prompt-length-budget-150k.md` 实测:mgh-init 编排器壳 **9,361 tok(claude)/ 9,224 tok(opencode)**,突破
R5.6 的 5,000 tok 硬上限(+4,361 / +4,224);**编排器分发足迹(壳 + fragments)11,827 / 11,690 也突破 8,000 tok**
(+3,827 / +3,690)。双害:① 壳是每轮固定开销,9K+ tok 在多轮 fan-out(list_* 分页可尖刺 ~20K tok/页)下更早
触发自动压缩;② 关键一次性动作(`.active` 哨兵写入,step 0)被深埋在 268/259 行密集 code block 中,**短上下文
模型易漏读** → opencode 上 hook 激活的唯一可靠路径静默失效而流水线仍跑完(无错误反馈)。本变更是该报告 §7
任务 1,只处理 mgh-init 壳的「超长」(报告 §7 任务 6/7/8/9 与 §6.3 lint 强制**不在本变更范围**,留后续单独推进)。

## What Changes

- **抽编排流细节进新 fragment `core/prompts/fragments/init-stage-flow.md`**(按需经 `REQUIRED SUB-SKILL` 加载,
  镜像 `orchestrator-discipline` 的 fragment 模式):承载 mgh-init stage 流的**逐步细节正文**(step 0–8 的
  run_config 写、哨兵生命周期、codegraph 检测、discover/scout/T1/T2/T3/T4 的 fan-out 刚性三元组与校验、
  聚合硬阈值、失败/级联失效落账等)。壳保留 parse-args + SUB-SKILL 指令 + Stage→组件表 + Resume/cache +
  Output + Always disclose。
- **删「Deterministic invocation (Bash)」整块**(claude 194–229 / opencode 194–228):36 行扁平目录与编排流步骤
  重复内联;保留 2 个**未在 flow 内联**的逃生口(大文件切片 `chunk_sources.py` form、`resume_state.py
  --invalidate-stale` 配方)迁回原生步骤。
- **折叠「Stage → 组件」表**(claude 167–191 / opencode 166–190)为紧凑 2 列「script inventory | subagent
  inventory」(仅名,绝对路径由 `list_steps.py` 运行时给;保留 expand_scope/form_clusters 非平凡复用注为脚注)。
- **压「Always disclose」**(claude 253–268 / opencode 245–260):16 条 → 5 条规范要点;细节迁「`boundaries[]` 已
  携带,仅 `report.md` 复述」一行(细节已落 `init_manifest.json::boundaries[]` / `report.md`)。
- **去重 hook 机制三处重述**(claude 10–18 / opencode 9–19):顶部折为 2 行指针(激活 = env 或哨兵;哨兵写法见
  step 0、纪律见 fragment)。
- **删 `NEVER py -c` / `NEVER Read 整份大 JSON` mantra 8+ 次重复**:编排流顶部一次性注记;删逐步 echo;仅保留防
  具体失败形状处(T1 的 scout-incomplete-gate、T1→T2 的 `--check` 形状闸门)。
- **修 R5.10 dev-meta**:claude:10 / opencode:9「本仓」→「目标项目」(在分发提示词中歧义:目标 agent 可能误读为
  m3g4horness 研发仓)。
- **删 line 51「stdout 直消费」重述**(已在 orchestrator-discipline fragment:20–23)。
- **测量验证**:落地后双壳经 `tools/measure_prompts.py` 实测 **≤ 5,000 tok**(claude + opencode;真约束);
  `init-stage-flow.md` + `orchestrator-discipline.md` **逐个报告**单文件尺寸(无硬求和上限) + 三者磁盘合计 ≤~10,000
  作防漂移 lint(据 design D6 + `docs/opencode-context-mechanics.md` §6:opencode 下壳与 fragments 均为单次 lazy Read 的
  USER 历史项、非每轮 system 税,8K 求和已撤回为磁盘防漂移形态)。
- 行为零变化:不删任何承重流程节点(I/O 契约 / fan-out 路径确定性 / `--check` 闸门 / resume 语义 / 已修 bug
  防线如 NTFS `::` sanitize、盘符根漂移、UTF-8 BOM 剥离、scout-incomplete-gate);所有裁剪点**落地前逐条验真**
  (承报告「⚠ 裁剪前提:保真度优先」)。

## Capabilities

### New Capabilities

_(无。本变更不引入新能力;它是 `orchestration-substrate` 既有「壳经 fragment 引用纪律正文」范式的 mgh-init 专属
延伸——把 stage 流细节同样 fragment 化。无新 spec。)_ 

### Modified Capabilities

- `orchestration-substrate`: 新增 mgh-init 专属 stage-flow fragment 的契约(壳经 `REQUIRED SUB-SKILL` 引用
  `init-stage-flow.md`,承载 stage 流逐步细节;壳保留 init 专属的 parse-args / Stage→组件表 / Resume / Output /
  Always disclose / `list_steps.py`/`write_runconfig.py` 调用面)。**这是 spec 级行为变化**:编排流细节的载体从
  「壳内联」变为「壳 + 按需加载 fragment」,且壳的 token 预算从无约束收紧为「≤ 5,000 tok(R5.6 硬上限,经
  `tools/measure_prompts.py` 实测)」。原「壳经 REQUIRED SUB-SKILL 引用 fragment」requirement 仅约束
  orchestrator-discipline;本变更把同一范式扩到 stage 流细节。

## Impact

- **Affected code**:
  - 新 fragment `core/prompts/fragments/init-stage-flow.md`(宿主无关?**否**——承载 init 专属 stage 流;但 claude
    与 opencode **共用同一份** stage 流正文,两壳仅壳体措辞差异,故 fragment 单文件、双壳引用,零正文 drift)。
  - 改 `releases/claude-code/commands/mgh-init.md` + `releases/opencode/command/mgh-init.md`(瘦身:删 Bash 目录块、
    折叠 Stage 表、压 disclose、去重 mantra、修「本仓」、加 `REQUIRED SUB-SKILL: Use init-stage-flow`)。
  - `install.sh`:**无改动**(已镜像整个 `core/` → `mgh-core/`,新 fragment 自动随之分发)。
  - 无脚本改动(零 `core/scripts/*.py` 改动)→ 契约 lint(`tools/check_contracts.py`)对 mgh-init 的 flag 断言**不变**;
    仅删的 Bash 目录块中的 flag 若在 flow 仍有调用则保留、否则确认无壳级依赖。
- **影响面**:
  - mgh-init 流水线**可观测行为零变化**(产物流水线、产物路径、stdout schema、退出码不变)。
  - 目标项目:无感知差异(install 分发同一组文件;多一个 fragment 经 SUB-SKILL 按需加载)。
  - 弱上下文模型:获益——壳更短 + `.active` 哨兵动作更突出 → skip-risk 降低(报告发起本分析的原始关切)。
- **无**第三方依赖(R2:本变更是 `.md` 编辑 + 既有 stdlib 测量工具,零新 import)。
- **无**数据迁移 / **无** manifest schema 变更(`init_manifest.json::version` 保持 7;R5.8「bump 版本号」针对
  schema 变更,本变更无 schema 变更)。
- lint 守护:`tools/check_distributed_purity.py`(新 fragment 是分发产物,须过纯净性 lint:无 R5.x/承/范式锚点/
  本仓 dev-meta)、`tools/check_contracts.py`(壳改动后 flag 契约仍闭合)、零依赖 AST 扫描(无脚本改动,中性)、
  既有回归测全绿。
- **范围声明(本 propose 不处理)**:报告 §7 任务 2(sast-deepdive specialist-hints 切分)、3(sra-augment
  codegraph 抽 fragment)、4/5(sra/srr 壳瘦身)、6(rules-format-opencode 压缩)、7(5 壳统一哨兵 callout)、
  8/9(薄余量预防裁剪)、§6.3(新增 `check_distributed_prompt_budget.py` lint + CI 接入)——留后续单独 propose
  (承 `split-cross-cutting-openspec-changes`:keep apply context bounded;承用户「后续」意向)。
