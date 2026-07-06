# Tasks — improve-mgh-init-llm-discovery

> 依赖顺序:契约/profile → 确定性脚本(discover 增骨架+source / plan_scout)+ 单测 →
> scout 提示词 → scout subagent(双 shell)→ 命令壳插 scout 段 → 安装/文档 → 端到端验证。
> 每条可独立验收。遵守 AGENTS.md R1–R5(零依赖、文档简练、命令壳薄壳、确定性脚本黑盒)。
> scout 是 i1 与 T1 之间的**纯加法插入**——下游 `form_clusters`/T1/T2/T3/T4 不改。

## 1. 契约与 profile(地基,先定形)

- [x] 1.1 改 `core/contracts/init/candidates.md`:`Candidate` 增**可选** `source ∈ {regex, scout, regex+scout}` 字段(additive,向后兼容);`Cluster` 同理(取成员多数或 `regex+scout`)。
- [x] 1.2 新增 `core/contracts/init/skeleton.md`:定义 `skeleton.json` schema(每文件 `file/lang/pkg/classes[]/imports[]/method_sigs[]/fan_in/bytes`),标明「纯机械抽取、不含语义判定」、由 `discover_controls.py` 单遍产出。
- [x] 1.3 新增 `core/contracts/init/scout-plan.md`:定义 `scout_plan.json`(`batches[]`:每批 `batch_id/targets[]/bytes/truncated`)+ `scout_candidates.json`(Candidate 子集 + `source:"scout"`)。
- [x] 1.4 改 `core/profiles/init.yaml`:增 `scout:` 块(`enabled:true / model:inherit / budget_files / batch_bytes:96KB / batch_cap:40 / audit_pct:15 / max_concurrent:8`)+ `fanout.scout_per_batch: true`。

## 2. 确定性脚本:discover 增骨架+source(D2);plan_scout(D4-S2)+ 单测

- [x] 2.1 改 `core/scripts/discover_controls.py`:在既有单遍(`index_files`/`build_call_graph`)里,为每文件抽 `imports[]`(按 `lang` 分派的 `import`/`#include`/`require`/`from…import` 正则),与既有 `pkg`/`classes`/`method_sigs`/`fan_in`/`bytes` 合并 → emit `skeleton.json`。**保 FD3 单遍**——不新增遍历、每文件至多读一次。
- [x] 2.2 改 `discover_controls.py`:`scan_candidates` 产出的每条 regex 候选带 `source:"regex"`;`_QUICK_RX` 预过滤的语义仅「跳过 regex 候选生成」,**不跳过 skeleton 抽取**(skeleton 覆盖全部源文件)。
- [x] 2.3 新增 `core/scripts/plan_scout.py`(标准库;`sys.path.insert` 自定位,承 `Standalone script invocation robustness`):读 `skeleton.json`,噪声剪枝(复用 `expand_scope.EXCLUDE_DIR`)+ 去 regex 已命中文件 → scout 目标;按 `pkg` 排序后按 `bytes ≤ --scout-batch-bytes` 切批 + 每批 ≤ `--scout-batch-cap`;单文件超批 → 标记走 `chunk_sources.py`;超 `--scout-budget` 标 `truncated` 并建议 `--scope`+`--merge`。CLI:`--skeleton <f> --candidates <f> --out <scout_plan.json> --batch-bytes --batch-cap --budget`;stdout=摘要 JSON,stderr=进度。
- [x] 2.4 新增 `tests/test_skeleton.py`:验证 skeleton 含 `pkg/classes/imports/method_sigs/fan_in/bytes`;验证被 regex 跳过的文件仍在 skeleton;验证单遍(遍历计数=1)。
- [x] 2.5 新增 `tests/test_scout_plan.py`:验证按字节+包内聚切批、每批 bytes≤预算且文件数≤cap、超批文件标记切片、超 budget 标 truncated、同 seed 抽样可复现。
- [x] 2.6 AST 扫描 + 零依赖自检:`plan_scout.py`/改动后的 `discover_controls.py` 无第三方 import、无 `vvaharness` import;`py tests/test_init_*.py`(回归)+ 新测全绿。
- [x] 2.7 新增 `core/scripts/merge_scout.py`(实现期补):scout 候选 + audit_found 折入 `controls_candidates.json` 并向 `clusters.json` **追加** scout 簇;**复用** `discover_controls.form_clusters`(空 reverse graph,无逻辑漂移);regex 簇与 usage_sites 不变。CLI:`--candidates --scout [--audit] --clusters --sample`。

## 3. scout 提示词(S3 深读 / S4 merge / 自检 audit)

- [x] 3.1 新增 `core/prompts/stages/init-scout.md`(**S3 per-batch**):输入 = 该批 skeleton 行 + repo root + regex 已知控制(避免重复);任务 = 自适应 Glob/Grep/Read 找 regex 漏掉的自研控制 → Candidate 子集锚点(`source:"scout"`);**硬约束**每条 ground 在真 Read 过的 `file:line`、允许「这批没控制」、精度优先于召回;DI/AOP 控制进 `unresolved`;头注 `rewrite-original`。
- [x] 3.2 新增 `core/prompts/stages/init-scout-merge.md`(**S4 单点**):输入 = 全部 S3 结构化候选(无原始码);任务 = 跨批去重(同 evidence 锚点)、命名归一、provisional `source` 标记 → `scout_candidates.json`;**不判 canonical**(留给 T2,对标 D12 协调洞察)。
- [x] 3.3 新增 `core/prompts/stages/init-scout-audit.md`(**自检**,D5):输入 = 随机抽样的「scout 拒绝项」骨架;任务 = 怀疑论偏置(对标 s6「assume WRONG until confirmed」)尝试证明其**实为**漏报控制;发现漏报 → 回灌;头注 `rewrite-original`。
- [x] 3.4 三提示词各加「输出语言」规则(承 D13):面向人读非代码内容用简体中文;锚点/路径/标识符/枚举保持原样。

## 4. scout subagent 定义(双 shell 镜像)

- [x] 4.1 新增 `releases/claude-code/agents/init-scout.md`(frontmatter `name/description/tools:Read,Glob,Grep,Bash/model:inherit`;消费 `scout_plan.json` 一批 → `checkpoints/scout/<batch>.json`;per-batch 隔离上下文)。
- [x] 4.2 新增 `releases/claude-code/agents/init-scout-merge.md`(单点,读全部 S3 结构化记录 → `scout_candidates.json`)。
- [x] 4.3 新增 `releases/claude-code/agents/init-scout-audit.md`(读抽样拒绝项 → 回灌/记 `audit_found`)。
- [x] 4.4 在 `releases/opencode/agent/` 镜像 4.1–4.3 三个 agent(opencode frontmatter 约定)。

## 5. 命令壳:在 i1 与 T1 之间插入 scout fan-out 段(双 shell)

- [x] 5.1 改 `releases/claude-code/commands/mgh-init.md`:Orchestration flow 在 i1 之后、T1 之前插入 scout 段——`py plan_scout.py …` → 以 `max_concurrent` 并行 fan-out `init-scout`(per-batch)→ `init-scout-merge`;自检 `init-scout-audit`;`merge_scout.py` 折入候选 + 追加 scout 簇。Stage→component 表增 scout 五行。参数表增 `--no-scout`/`--scout-budget`/`--scout-batch-bytes`/`--scout-batch-cap`/`--scout-audit-pct`。增编排器声明(承 `Deterministic scripts are orchestrator black boxes`):`plan_scout.py`/`merge_scout.py` 经 Bash 调用、源码不 Read 进上下文、不 Write `.py` 编排器。
- [x] 5.2 改 `releases/opencode/command/mgh-init.md`:同 5.1,opencode 调用约定。
- [x] 5.3 校验两壳参数表一致;`--no-scout` 时 scout 段整体跳过(等价旧行为)。

## 6. 安装、自检、文档

- [x] 6.1 改 `install.sh`:把 `init-scout`/`init-scout-merge`/`init-scout-audit` agent、对应提示词、`plan_scout.py`、新 `core/contracts/init/skeleton.md`+`scout-plan.md` 纳入 `--claude`/`--opencode` 清单(镜像到 `.claude/mgh-core/`)。core/ 整树 cp,新资产自动随装;self-check 循环已加 `plan_scout`/`merge_scout`。
- [x] 6.2 零依赖自检:`grep -rnE "^[[:space:]]*(import[[:space:]]+vvaharness|from[[:space:]]+vvaharness[[:space:]]+import)" --include=*.py .` 应无输出;AST 扫描 `plan_scout.py` + 改动后 `discover_controls.py` 无第三方 import。
- [x] 6.3 改 `core/contracts/init/manifest.md`:`init_manifest.json` 增 `scout` 段字段定义 + `boundaries[]` 新增「scout 覆盖数字 / 非确定性 / 残留盲区」披露条目。
- [x] 6.4 更新 `docs/upstream-index.md`:mgh-init 段补注「发现层由 regex-only 闸门升级为 regex fast-path ∪ LLM scout 双源(自创,非上游同步项)」。

## 7. fan-out / 大文件 / 可恢复(scout 专属;部分条款已在 2/5 落地)

- [x] 7.1 字节预算+包内聚分批(D4-a/b):`plan_scout.py::plan_batches` 实现 bytes 切批 + pkg 排序内聚;`test_scout_plan.py` 覆盖。
- [x] 7.2 单超批文件切片(D4-d):`plan_scout.py` 标 `needs_slice`;命令壳指示 scout-reader 遇此先 `chunk_sources.py` 切片,非整文件喂 LLM。
- [x] 7.3 并行波次(D4-e):命令壳指示编排器以 `max_concurrent` 起波、`pending[]` 空即止(同 `list_clusters.py` 范式)。
- [x] 7.4 checkpoint + `--resume`(D9 同构):命令壳指示每批落 `checkpoints/scout/<batch_id>.json.done`;`--resume` 跳过已 done 批次;S4 merge 整体一个 `.done`。契约见 `manifest.md` 检查点表。
- [x] 7.5 自检采样(D5):命令壳指示 `init-scout-audit` 随机抽样 rejected × `audit_pct`;`audit_found` 经 `merge_scout.py --audit` 回灌并记 manifest。

## 8. 端到端验证

- [x] 8.1 `./install.sh --claude <tmp>` 验证通过(scout 脚本 co-located、prompts/agents/contracts 镜像就位);`--opencode` 同源逻辑对称。
- [x] 8.2 **对照验证(核心,确定性半已验证)**:含自研 `PermGuard`(零规范 token)的样例仓——`discover` 不产 PermGuard 候选(regex 漏)但 skeleton 含它(`regex_hit:false`)→ `plan_scout` 把它列为唯一 scout 目标 → `merge_scout` 折入后 clusters.json **追加** PermGuard 的 authorization 簇,regex 簇(SecurityConfig/MaskUtil)不变。`--no-scout` = 该折入前快照(PermGuard 缺失)= 旧行为,已对照。**LLM 半**(init-scout 真实读 PermGuard 出候选)需宿主 agent 实跑,候选 schema 已被 merge_scout 消化证明(见 smoke)。
- [x] 8.3 **fan-out 验证(逻辑已测)**:`test_scout_plan.py` 覆盖批数=ceil(Σbytes/budget)、每批 bytes≤预算且包内聚、每批文件数≤cap、超批标 `needs_slice`、超 budget 标 truncated、batch_id 顺序。800 目标的 wall-clock 波次时序需宿主 agent 实跑。
- [x] 8.4 **覆盖披露验证(契约级)**:`manifest.md` 已定义 `scout` 段字段 + `boundaries[]` 两条新边界;两命令壳「Always disclose」已写明不声称全仓覆盖 + 非确定性 + 残留盲区。运行期 manifest 由编排器 i4 落盘。
- [x] 8.5 **下游无回归**:smoke 确认 regex 簇与 evidence_files 合并后不变;`list_clusters.py`/T1–T4 契约未改;`controls_inventory.json` schema 不变(vvah 兼容)。
- [x] 8.6 `py -m pytest tests/` 全绿(45 passed);零依赖自检无输出;AST 扫描 `plan_scout.py`/`merge_scout.py`/改动后 `discover_controls.py` 仅标准库 + 兄弟 `expand_scope`/`discover_controls` 导入。
- [x] 8.7 bump `VERSION` 0.1.2 → 0.1.3(承 R5.8)。

> **待宿主 agent 实跑项(非阻塞)**:8.2 的 LLM 半(init-scout 真实读码出候选)、8.3 的并行波次 wall-clock、8.4 的运行期 manifest 落盘——这些需真实宿主 agent 驱动 subagent 才能端到端跑;确定性管道(skeleton→plan_scout→merge_scout 折入)已由 smoke + 单测全验证。
