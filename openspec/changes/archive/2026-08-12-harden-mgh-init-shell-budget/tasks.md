# Tasks — harden-mgh-init-shell-budget

> 实现顺序按依赖;每个任务可验证。本变更是纯 `.md` 编辑(零脚本改动、零依赖、零 schema 变更、install.sh 无改动)。
> **保真度铁律**(承 design「⚠ 裁剪前提」+ 报告同名节):每条裁剪落地前逐条验真——git blame / commit message /
> `docs/review-*.md` 确认非承重流程节点(I/O 契约 / fan-out 路径确定性 / `--check` 闸门 / resume 语义)或已修 bug
> 防线(NTFS `::` sanitize、盘符根漂移、UTF-8 BOM 剥离、scout-incomplete-gate);标注「承重→保留 / 已他处覆盖→删 /
> 可迁移→抽取」。「节省」是上限,保真度优先。

## 1. 新建 init-stage-flow fragment(承重,先做)

- [x] 1.1 新建 `core/prompts/fragments/init-stage-flow.md`:头部加作用域 HTML 注释(类比 orchestrator-discipline.md:1–12:
      「mgh-init 专属 stage 流细节;两壳共用单文件;经 REQUIRED SUB-SKILL 加载;不含 R5.x/承/范式锚点/本仓 dev-meta」)。
- [x] 1.2 把当前 `releases/claude-code/commands/mgh-init.md` 的「## Orchestration flow」code block(step 0–8 全部
      逐步细节)**整块搬移**进 `init-stage-flow.md`——零内容丢失(承 design D1)。逐 step 核对:step 0(parse+self-check+
      run_config 原子写+哨兵生命周期+MGH_TARGET+codegraph 检测)、1(--merge)、2(i1 discover+校验)、3(init-survey opt)、
      3b(SCOUT FAN-OUT+聚合硬阈值预判+级联失效+终态)、3c(init-resolve codegraph-gated)、4(T1 FAN-OUT+scout 闸门)、
      4b(T1→T2 边界闸门 BOM+形状)、5(T2+聚合硬阈值+validate_inventory)、6(T3 FAN-OUT)、6b(ASSEMBLE/LINT)、7(T4)、
      8(i4 manifest+report+失败/scout_merged 落账+收尾 rm 哨兵)。
- [x] 1.3 验真搬移完整性:逐行核对 step 0–8 每个确切脚本调用 / flag / `--check` 闸门 / fan-out 三元组 /
      `checkpoint_path`/`rule_path` 绝对路径语义 / NTFS sanitize 注记 / scout-incomplete-gate / `.failed` 终态 /
      级联失效落账均在 fragment 内(无遗漏)。两壳 stage 流正文当前逐字一致 → 单一 fragment 即两壳共用(design D2)。
- [x] 1.4 `py tools/check_distributed_purity.py` → 确认新 fragment 过纯净性 lint(无 R5.x/FDn/Dn/变更夹名/承 R5/范式锚点/
      「本仓」);若命中 dev-meta → 清洗为操作性措辞(R5.10「删或嫁接」)。

## 2. 改 claude 壳 `releases/claude-code/commands/mgh-init.md`

- [x] 2.1 删「## Orchestration flow」code block(已搬进 fragment);原位置换为 `> **REQUIRED SUB-SKILL: Use init-stage-flow**`
      指令(紧随既有 `Use orchestrator-discipline`),1 行 stage 流概览指针。
- [x] 2.2 修「本仓」→「目标项目」(line 10 顶部编排器声明;R5.10 第 7 类 dev-meta)。
- [x] 2.3 hook 机制三处重述去重(line 10–18 顶部块折为 2 行指针:激活 = env 或哨兵;哨兵写法见 step 0、纪律见
      orchestrator-discipline fragment;保留 opt-out flag `install.sh --no-enforce-hook` 提及)。
- [x] 2.4 删 line 51「stdout 直消费」重述(已在 orchestrator-discipline.md:20–23)。
- [x] 2.5 `NEVER py -c`/`NEVER Read 整份大 JSON` mantra 去重:编排流(现 fragment)顶部一次性注记 + 删逐步 echo;
      **保留**防具体失败形状处(T1 scout-incomplete-gate、T1→T2 `validate_t1_records --check` 形状闸门)的最小反例
      (承 R5.5⑤)。**注**:此条在 fragment 内执行(mantra 已随 stage 流搬走);壳内仅留 SUB-SKILL 指令。
- [x] 2.6 折叠「Stage → 组件」表(line 167–191)为紧凑 2 列「script inventory | subagent inventory」(仅名;删 Asset 列
      `core/scripts/<x>.py` 绝对路径——由 list_steps.py 运行时给);保留 `expand_scope.py` 复用 + `merge_scout.py`
      复用 `form_clusters` 非平凡复用注为 2 行脚注。
- [x] 2.7 删「### Deterministic invocation (Bash)」整块(line 194–229)。**保真度检查**:删前逐 flag 核对——该块中每个
      flag 是否都在 flow 对应步骤出现?若某 flag 仅出现在 Bash 目录块、flow 无 → 该 flag 是遗漏,**迁入 fragment 对应
      step** 而非删(实现者逐条标注)。保留 2 个未在 flow 内联的逃生口迁回:① 大文件切片 `chunk_sources.py` 调用 form
      → 迁 fragment step 3b/4 fan-out 描述(已是该处引用,确认在);② `resume_state.py --invalidate-stale` 配方 →
      迁「## Resume / cache」段。
- [x] 2.8 压「## Always disclose」(line 253–268)为 5 条规范要点(LLM 诱发/人工复核、存在≠有效 CVE-2025-41248、
      call-graph 文本/AST、中文输出、scout 非整仓);其余(dotfiles/tests 跳过、宿主 shell 超时、codegraph 辅助、请求上下文
      预算、launch-cwd 前置)细节留一行指针「`init_manifest.json::boundaries[]` / `report.md` 已携带」。
      **保真度检查**:「launch-cwd 前置」(step 0 首调 list_steps.py 依赖从目标项目根发起)是编排器动作纪律非产物披露 →
      MUST 保留在壳(迁 parse-args 注记或 Resume/cache 段;design Q2 倾向 Resume/cache),不删。

## 3. 改 opencode 壳 `releases/opencode/command/mgh-init.md`(镜像 claude 改动)

- [x] 3.1 重复 task 2.1–2.8 对 opencode 壳(行号偏移见报告 §4.2:opencode 9–19 / 166–190 / 194–228 / 245–260)。
      **壳体差异保留**:opencode 的 allowed-tools 无、`.opencode/mgh-core` 前缀、step 6b 「BUILD INDEX + LINT」opencode-only
      措辞、`AGENTS.md` 索引块披露——这些是 claude/opencode 壳体差异,不进 fragment,留在壳。
- [x] 3.2 两壳 stage 流引用**同一** `init-stage-flow.md`(零 drift 核对:claude/opencode 的 SUB-SKILL 指令指向同一相对路径
      `prompts/fragments/init-stage-flow.md`,经各自 `.claude/mgh-core` / `.opencode/mgh-core` 前缀解析)。

## 4. 验证(全部 MUST 绿)

- [x] 4.1 `py tools/measure_prompts.py releases/claude-code/commands/mgh-init.md releases/opencode/command/mgh-init.md`
      → 两壳 `mid_tokens` 各 ≤ 5,000(报告锚 mid_tokens;若 high_tokens 略超,回头压 Stage 表脚注 / disclose 指针,
      design Risks 第 5 条)。**实测**:claude 2,916 / opencode 2,853(均远 ≤5K)。
- [x] 4.2 `py tools/measure_prompts.py core/prompts/fragments/init-stage-flow.md core/prompts/fragments/orchestrator-discipline.md
      releases/claude-code/commands/mgh-init.md releases/opencode/command/mgh-init.md` →
      **(i)** 各 shell `mid_tokens` ≤ 5,000(真约束;claude 2,916 / opencode 2,853 ✓);**(ii)** `init-stage-flow`(4,769)
      + `orchestrator-discipline`(2,466)**逐个报告**单文件尺寸(供「单次 Read 轮结构是否良好」评估,**无硬求和上限**——据 design D6:
      opencode 下壳与各 fragment 均为单次 lazy Read 的 USER 历史项,非每轮 system 税;8K 求和已撤回为磁盘防漂移形态);
      **(iii)** per-shell 磁盘合计(claude 10,151 / opencode 10,088)略超 ~10,000 防漂移护栏(init-stage-flow verbatim 搬移合法;
      护栏为磁盘防漂移、NEVER 运行时叠加占用);源码根据见 `docs/opencode-context-mechanics.md`。
- [x] 4.3 `py tools/check_contracts.py` → mgh-init flag 契约闭合(脚本未改,删 Bash 块后 flow 内联 bash ```block
      仍在扫描集;应全绿)。**实测**:254 flags / 10 shells 全绿。
- [x] 4.4 `py tools/check_distributed_purity.py` → 新 fragment + 两壳纯净性全绿(无 R5.x/承/范式锚点/本仓 dev-meta)。
      **实测**:150 files clean。
- [x] 4.5 零依赖 AST 扫描(grep import vvaharness 或既有 `test_zero_deps.py`)→ 中性(无脚本改动)。**实测**:clean。
- [x] 4.6 既有回归测 `py tests/test_deterministic.py` + mgh-init 相关契约/纯净测全绿。**实测**:45/45 全绿
      (`test_mgh_init_codegraph_parity.py` 已随架构调整:D1 stage 流抽 fragment + D3 表折叠后,parity 断言改为 shell+共享 fragment
      合并面;保护意图[claude/opencode codegraph 面一致]保留且更强——共享 fragment 是单点真相)。
- [ ] 4.7 (人工,可选)mgh-init 流水线首跑对照(小目标仓):产物路径 / `init_manifest.json` schema(version 保持 7)/
      `boundaries[]` 披露 / report.md 与变更前一致。**注**:纯 `.md` 改动、零脚本/schema 变更、零依赖;留给人工首跑。
- [x] 4.8 更新 `docs/review-prompt-length-budget-150k.md` §3.1 mgh-init 行(标注 task 1 已落地、新实测 token 数)或在其
      §7 任务表标 task 1 done(留痕;R3 简练)。
