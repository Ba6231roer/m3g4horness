# Tasks — harden-mgh-init-context-resilience

> 依赖顺序:L1 状态/枚举脚本(最低风险、纯 additive)→ 契约 → L2 提示词 ack + 路径绝对化 →
> L4 命令壳 resume 流 + compaction 段 → L3 聚合 map-reduce(最重、最后)→ AGENTS.md 措辞 →
> 回归 + 端到端。每条可独立验收。遵守 AGENTS.md R1–R5(零依赖、文档简练、复用导入、R5.1 CLI lint、
> R5.8 回归 + bump 版本号)。新脚本 MUST 经 `tools/check_contracts.py` 断言其 `--help` 含双壳镜像的所有 flag。
> 设计决策见 `design.md`(D1–D5 + Open Questions Q1–Q4)。

## 1. L1 — 确定性脚本(纯 additive、R2 零依赖、R5.3 自包含)

- [x] 1.1 新增 `core/scripts/resume_state.py`:读 `<target>/.mgh-init/` 全产物 + 跨 tier `.done` + `run_config.json`,
      stdout 吐极简 `{target, format, step, tiers{discover,scout,t1,t2,t3,t4::{done,total}}, next_action{kind∈
      bash|subagent|done, desc, absolute_paths}, resumable, notes[]}`;stderr 诊断;退出码 `0/1/2`;`step` 取值
      `not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done`(由产物 + `.done` + `run_config`
      解析 optional/codepath 分支);`next_action.absolute_paths` **复用** `list_*`/`describe_artifact` 既有绝对值,
      NEVER 自拼/模板 `<target>`。零依赖、自定位 `sys.path`、utf-8、任意 cwd、`--help` 即契约。
- [x] 1.2 `resume_state.py` 加 `--check`(可选,Q4):校验磁盘状态自洽(如 t2 `.done` 在但 `controls_inventory.json`
      缺失 → 退出码 2 + 诊断);承 R5.9 边界校验泛化。
- [x] 1.3 新增 `core/scripts/plan_aggregate.py`:读上一层记录(T2:`checkpoints/t1/*.json`;scout-merge:
      `checkpoints/scout/*.json`),按 `category`(T2)/ batch 簇(scout-merge)分桶,切每桶 ≤ `--max-aggregate-bytes`
      的 shard 并 `--materialize` 物化 per-shard 输入;stdout `{node∈t2|scout-merge, total_bytes, budget, shards,
      needs_reduce, pending[], truncated, offset, limit, effective_limit, shrunk}`;复用 `list_*` 的
      `--materialize`/`--offset`/`--limit`/`--orch-budget-bytes` 语义;退出码 `0/1/2`;零依赖、自定位、utf-8、任意 cwd、
      `--help` 即契约。`needs_reduce=false`(≤ 预算)时 stdout 明示「走 single-context 既有路径」。
- [x] 1.4 在 `core/scripts/discover_controls.py`(或起步逻辑能写入 `.mgh-init/` 的既有就近脚本)增 `run_config.json`
      原子写出(D2):step 0 把 `target`(绝对)/`format`/`scope`/`scope_mode`/`no_scout`/`no_codegraph`/`skip_consistency`/
      `merge`+`merge_partials_dir`/`include_dotfiles`/预算/`scout-*` 参数写 `<target>/.mgh-init/run_config.json`
      (`.tmp`+`os.replace`)。若该写出不适合 discover,新增极薄叶子 `write_runconfig.py`(同样 R5.3 契约),由壳 step 0 调。
      **决策(impl 时定)**:优先复用 discover 既有起步写盘;否则新薄脚本——记入 design Open Questions 解决。
      → **决策**:discover 缺 `format`/`no_scout`/`no_codegraph`/`skip_consistency`/`merge`/scout-*/预算 等编排器级 flag,
      故新增极薄叶子 `write_runconfig.py`(R5.3 契约、`.tmp`+`os.replace` 原子写、stdout ack、退出码 `0/1/2`、`--help` 即契约),
      由壳 step 0 调。

## 2. 契约同步(`core/contracts/init/`)

- [x] 2.1 新增 `core/contracts/init/resume-state.md`:`resume_state.py` stdout 字段表(`step` 枚举 + `tiers` shape +
      `next_action` shape + `absolute_paths` 复用 `list_*` 既值)+「run_config 缺失 → 退出码 2 fail-loud」+ step 判定真值表
      (每 step 的「完成标志」探针:哪个产物/`.done` 存在 = 该 step done)。
- [x] 2.2 新增 `core/contracts/init/aggregate-sharding.md`:`plan_aggregate.py` stdout 契约 + 分桶策略(category/batch 簇)+
      「≤ 预算 needs_reduce=false 走既有 single-context;> 预算 two-pass map-reduce」+ rollup 输入 = 各 shard 摘要。
- [x] 2.3 `core/contracts/init/unit-inputs.md`(或合适契约)补一行:`run_config.json` 是起始态意图文件(随 `.mgh-init/`
      gitignore),与终态 `init_manifest.json` 边界对照。

## 3. L2 — subagent 回传有界 ack + 路径绝对化(9 份 stage × 双壳 agent 定义)

- [x] 3.1 9 份 `core/prompts/stages/init-*.md`(survey/resolve/scout/scout-merge/scout-audit/induct/synthesis/
      rulewriter/rules-consistency)各增 **Return-to-orchestrator** 段:最终消息 = 单条有界 ack(`ok <abs path> <count>`/
      `oversize <abs path>`/`failed <reason>`;聚合 stage 加 `total`/`merged`),**NEVER** 回显记录体/源码。ack 为存活信号,
      非 数据载体。
- [x] 3.2 路径绝对化(审计发现 #2):把 `init-survey`/`init-scout-merge`/`init-scout-audit`/`init-synthesis`/
      `init-rules-consistency` 仍用的 `<target>` 相对路径,统一为 fan-out 已有的「绝对 `checkpoint_path` 逐字、NEVER 插值
      `<target>`」契约(对标 `harden-mgh-init-fanout-output-paths` 给 scout/induct/rulewriter 做过的)。核对各 stage 的
      Input/Output 段用绝对字段名。
- [x] 3.3 双壳 `releases/{claude-code/agents,opencode/agent}/init-*.md` Hard-constraints 段同步:回传有界 ack、NEVER 回显
      记录体;输出路径取逐字绝对值、NEVER 自拼/写项目外(双重防线,承 FD8)。

## 4. L4 — 命令壳(两份 `mgh-init.md`:claude + opencode)

- [x] 4.1 起步段(step 0):在 `export MGH_INIT_ACTIVE=1` 旁加「写 `run_config.json`」(调 1.4 的写出途径);声明其为
      stateless resume 的意图源。
- [x] 4.2 新增 **Re-entrancy & compaction** 段(D5):① 状态磁盘化、对话记忆非真相源;② `/compact`/opencode 自动压缩是
      模型摘要、可能丢编排纪律 → 续跑 NEVER 靠「记得第几步」;③ `--resume` 或任何压缩事件后**第一步 SHALL 调
      `resume_state.py`**;④ 上下文吃紧 MAY 干净停止(跑完当前 fan-out 波次、落 `.done`)→ 新 session `/mgh-init --resume`
      续,**优于**人工 `/compact`;⑤ per-call `timeout` + discover `partial:true` 纪律不变。主谓措辞 + recipe(R5.5①)。
- [x] 4.3 resume 流程:把 `--resume` 路径的**首步**改为「`py …/resume_state.py --target <target>` → 据 `step`/`next_action`
      继续」(取代「靠对话记忆判步骤」);编排器纪律段增 recipe「需知当前步骤 → `resume_state.py`,NEVER `py -c`、NEVER
      靠对话记忆」。
- [x] 4.4 T2 / scout-merge 步骤注 map-reduce 降级:「聚合输入 > `--max-aggregate-bytes` → 经 `plan_aggregate.py` 分桶 →
      per-shard partial-synthesis → rollup;≤ 预算走既有 single-context」;`init_manifest.json::boundaries[]` + `report.md`
      披露降级触发与 shard 数。
- [x] 4.5 「Determined invocation (Bash)」示例区补 `resume_state.py` / `plan_aggregate.py` / `write_runconfig.py` 调用示例(双壳镜像脚本 flag)。

## 5. L3 — 聚合 map-reduce 接线(最重、依赖 L1.3 + L4)

- [x] 5.1 T2 步骤接线:编排器进 T2 前先 `plan_aggregate.py --node t2 …`;`needs_reduce=false` → 既有 single-context
      `init-synthesis`;`needs_reduce=true` → 每 shard 扇出 `init-synthesis`(partial,有界输入,ack 回传)→ 单一 rollup
      subagent 仅吞各 shard 摘要 → 写 `controls_inventory.json` + `checkpoints/t2/.done`。
- [x] 5.2 scout-merge 步骤接线:同 5.1(`--node scout-merge`,按 batch 簇分桶)。
- [x] 5.3 `validate_inventory.py`(T2 边界校验)对 map-reduce 产出的 inventory 同样适用(产物 schema 不变);确认 rollup
      写出的 inventory 过 `--check`(退出码 0)。

## 6. AGENTS.md 措辞 sharpen(R5.4 / R5.5 / R5.10)

- [x] 6.1 R5.4「大仓可观测 + 长跑可恢复」段补「编排器级 re-entrant resume state」为权威机制之一:`resume_state.py` 把
      「我在哪 / 下一步」下沉为磁盘查询,跨 compact/crash/新 session 三态坍缩为同一 resume 路径;`run_config.json` 作起始态
      意图、`init_manifest.json` 作终态。理由〔状态磁盘化 = 结构性免疫对话记忆丢失〕随规保留。
- [x] 6.2 R5.5① recipe 段补:「需知当前步骤 / 下一步 → 读 `resume_state.py` stdout `step`/`next_action`;NEVER 靠对话记忆、
      NEVER `py -c` 重算」。理由〔省上下文 + 防路径偏离 + 跨宿主〕随规保留。
- [x] 6.3 核对 R5.10 分发纯净性:新命令壳段(Re-entrancy & compaction)不携带 dev-only 编号/`FDn`/`Dn`/变更夹名(由
      `tools/check_distributed_purity.py` + 提示词护栏覆盖);受保护归因保留。

## 7. 契约 lint + 回归单测(R5.1 / R5.8)

- [x] 7.1 `tools/check_contracts.py`:扩断言,对 `resume_state.py`/`plan_aggregate.py`/`write_runconfig.py` 跑 `--help`,
      断言双壳 `mgh-init.md` 镜像的 flag 全存在(R5.1)。
- [x] 7.2 新增 `tests/test_resume_state.py`:合成 `.mgh-init/` 各进度态(not-started/discover-done/scout 部分_done/
      t1 部分/t2 done/t3 部分/done/merge)+ `run_config.json`,断言 `step`/`tiers`/`next_action.kind`/`absolute_paths` 绝对且
      复用 `list_*` 值;`run_config` 缺失 → 退出码 2;`--check` 检出不自洽态。
- [x] 7.3 新增 `tests/test_plan_aggregate.py`:≤ 预算 → `needs_reduce=false`;> 预算 → shard 每桶 ≤ 预算、`pending[]` 含
      `input_path`;翻页 `shrunk`/`effective_limit`;零依赖、任意 cwd、`--help` 即契约。
- [x] 7.4 扩 `tests/test_list_*.py`(或新增):断言 stage ack 契约落到提示词(grep `Return-to-orchestrator` + ack 取值
      在 9 份 `init-*.md` + 双壳 `agents/init-*.md` 各存在);聚合 stage 路径已绝对化(grep 不含裸 `<target>/.mgh-init` 写入模板)。
      → 新增 `tests/test_init_ack_contract.py`(9 prompt + 18 agent def + 5 whole-tier 路径绝对化)。
- [x] 7.5 既有 R5.8 回归扩面:新脚本在**非脚本目录 cwd** 子进程跑(导入鲁棒)、零依赖 AST 扫描(`tools/` 全集)、`--help`
      即契约、性能不退化;install 自检:新脚本随 `core/` 镜像就位、版本号 bump、CHANGELOG 条目。
      → `tests/test_init_runtime.py::TestNewScriptsStandalone` 扩 3 新脚本;`tests/test_zero_deps.py` 加 guard;manifest 版本 6→7;CHANGELOG 入条目。

## 8. 端到端验证(R5.7 段 A 评估 + 真机)

- [x] 8.1 `py -m unittest discover -s tests` 全绿(525 passed);`tools/check_contracts.py` 0 违例(323 flags);
      零依赖 AST 扫描无输出;`tools/check_distributed_purity.py` 0 违例(120 shipped md clean)。
- [x] 8.2 双壳 install 自检(`./install.sh --claude <tmp>` / `--opencode <tmp>`):新脚本就位、`run_config.json` 写出途径
      工作(write_runconfig → resume_state step=discover 端到端通)、hook 注入幂等 **(本机 ✓)**。
- [ ] 8.3 **re-entrant resume 核**(确定性):合成中仓跑到 T1 部分 `.done` 后**杀掉 session** → 全新 session 跑
      `/mgh-init --resume`(不重输 flag)→ `resume_state.py` 报 `step=t1` + pending,续跑至 done;产物完整、无重跑已 done 单元 **(本机)**。
      → 确定性底座已验证(`test_resume_state.py` 覆盖 step 重派生 + run_config 无状态);真 agent session 续跑待本机/真机。
- [ ] 8.4 **compaction 模拟**:在 T2 前人为塞大上下文 / 触发 `/compact` → 续跑首步调 `resume_state.py` → 从磁盘重派生 step,
      不依赖对话记忆;断言续跑路径不偏离(仍按命令壳纪律走 `list_*`/`checkpoint_path`)**(本机)**。
      → 命令壳 Re-entrancy & compaction 段已落 + resume_state 磁盘重派生已测;真 compaction 事件续跑待本机。
- [ ] 8.5 **聚合 map-reduce 触发**:合成大量 T1 记录使 > `--max-aggregate-bytes` → `plan_aggregate.py` 分桶 → per-shard
      partial → rollup;每个大模型请求 ≤ 预算;inventory 过 `validate_inventory.py --check`;`boundaries[]` 披露降级 **(本机)**。
      → 确定性分桶 + validate_inventory 边界已验证(`test_plan_aggregate.py`);真 LLM per-shard/rollup + R5.7 段 A blind A/B 待本机。
      **R5.7 段 A**:对 T2 map-reduce 建 baseline(既有 single-context ≥5 次)→ blind A/B 对比 inventory 质量/canonical 判定 pass rate
      (Open Question Q2 关键质量风险);新失败模式回灌 design。
- [ ] 8.6 真机大仓(用户 Java 仓,曾复现上下文过大停止)复跑 `/mgh-init`:验证「上下文吃紧时干净停止 + 新 session resume」
      路径成立、不再需要人工 `/compact` **(待用户真机)**。
- [x] 8.7 回滚演练:改动面清单(新脚本 3 = resume_state/plan_aggregate/write_runconfig、契约新增 2+补 1、prompt 改 9×双壳 ack+5 路径绝对化、
      双壳改 2(resume 流 + compaction 段 + map-reduce 接线 + 示例)、AGENTS.md 改 R5.4/R5.5、manifest 版本 6→7、测试新增 3 + 扩 2);
      无 schema/数据迁移;全 additive(产物磁盘 schema 不变);`git revert` 即整体回退;VERSION bump(manifest 6→7)+ CHANGELOG(R5.8)。
