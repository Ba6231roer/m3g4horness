# Tasks — add-mgh-init

> 依赖顺序:契约/配置 → 确定性脚本+单测 → 提示词 → subagent → 命令壳 → 安装/自检 → 验证。
> 每条可独立验收。遵守 AGENTS.md R1–R4(零依赖、文档简练、路径规约)。

## 1. 契约与配置(地基,先定形)

- [x] 1.1 写 `core/contracts/init/candidates.md`:定义 `controls_candidates.json` schema(每条:`file/line/category/pattern/snippet/entry_points[]/unresolved?`),含示例片段(≤5 行)。
- [x] 1.2 写 `core/contracts/init/inventory.md`:定义 `controls_inventory.json` schema(`name/kind/category/description/usage/evidence[]/entry_points[]/protects[]/gaps[]/confidence` + 规模字段 `cluster_id`/`role∈{canonical,competing,duplicate,possibly-dead}` + `out_of_scope[]`),标注 vvah `design_controls` 兼容字段(`kind/protects/notes`)与 `category→kind` 归一表。
- [x] 1.3 写 `core/contracts/init/manifest.md`:定义 `init_manifest.json`(`format/count/provenance/unresolved[]/out_of_scope[]/boundaries[]`)+ `checkpoints/` 单元 schema(`<unit>.json` + done 标记)。
- [x] 1.4 写 `core/profiles/init.yaml`:角色 `discover`(脚本,无模型)/`induct`/`rulewriter`(`model: inherit`)、tools(`Read,Glob,Grep,Bash`)、budget,沿用 `default.yaml` 结构。

## 2. 确定性发现脚本(i1)+ 单测

- [x] 2.1 写 `core/scripts/discover_controls.py`(标准库):**流式逐文件**按 8 类 `category` 扫候选;`from expand_scope import build_call_graph, walk_sources, FRAMEWORK_RX, SOURCE_EXT` 复用(D2 导入不改写),**关闭 `walk_sources` 20000 静默上限**(改显式 `--max-files`,超限告警并继续);支持 `--scope path|package|file` + `--scope-mode defined|applicable`;为每候选算 `reverse`(调用方=`entry_points`)、标 `framework_files`、收 `unresolved[]`;`--category→kind` 归一;CLI:`--repo --out --scope? --scope-mode? --language? --max-files?`,JSON 出 `controls_candidates.json`。
- [x] 2.2 写 `tests/test_init_discover.py`:样例 fixture(含 `@PreAuthorize`、mask 工具、`@Valid`、Cipher 工具)验证命中正确 `category`;验证 `EXCLUDE_DIR` 跳过;验证 `reverse` wiring 填 `entry_points`;验证 AOP-only 控制进 `unresolved[]`。
- [x] 2.3 AST 扫描 + 运行确认 `discover_controls.py` 零第三方 import、零 `vvaharness` import;`py tests/test_init_discover.py` 全绿。
- [x] 2.4 **簇形成(确定性,决定 T1 隔离单元)**:`discover_controls.py` 另出 `clusters.json`——每簇 = 候选定义点 + 调用图邻居文件集(D2 `reverse`);标记**集中式**(util/filter/config) vs **分布式**(注解 `@PreAuthorize`/`@Valid`);分布式使用点**抽样**(有上限,防爆上下文);簇 = T1 隔离单元 = D9 checkpoint 单元。
- [x] 2.5 `tests/test_init_clusters.py`:验证集中式簇含定义点+代表性调用方、分布式簇含启用配置类+抽样站点、抽样有上限、跨 scope 控制入 `out_of_scope[]`。

## 3. 提示词(survey / T1 归纳 / T2 综合 / T3 出 rules / T4 一致性)

- [x] 3.1 写 `core/prompts/stages/init-survey.md`:把 s1-survey 的「找攻击面」改写为「按候选清单 + 文件摘录取证既有控制」,复用 exclusion-rules fragment 排除测试/构建代码;头注 `rewrite-original`(纯自创)或标注 vvah 溯源(若引用片段)。
- [x] 3.2 写 `core/prompts/stages/init-induct.md`(**T1 per-cluster**):输入 = 单簇文件集(大文件先 D7 切片)+ 候选元数据;输出**单簇结构化控制记录**(`name/category/kind/usage/evidence/entry_points/gaps/confidence`);**强制**带 `file:class:method` 证据、低证据降 `confidence`;**显式禁止**做 canonical/competing 判定(看不到别簇)。
- [x] 3.3 写 `core/prompts/stages/init-synthesis.md`(**T2 跨簇综合**):输入 = 全部 T1 记录(结构化 JSON,无原始码);做跨模块聚类、D8 canonical/role 选定、去重、命名归一 → `controls_inventory.json`。
- [x] 3.4 写 `core/prompts/stages/init-rulewriter.md`(**T3 per-category**):按 `--format` 分支(claude `.claude/rules/` path-scoped vs opencode 根 `AGENTS.md`),规则指向具体锚点、给「复用勿重造」usage、≤3–5 行内联代码;非破坏性受管块规则。
- [x] 3.5 写 `core/prompts/stages/init-rules-consistency.md`(**T4 一致性**,可选):输入 = 全部 T3 草稿;跨类命名/引用一致性、去重。
- [x] 3.6 写 `core/prompts/fragments/rules-format-claude.md` 与 `rules-format-opencode.md`:固化两种格式实测结构(2026-06),供 rulewriter 严格遵循、防混用。
- [x] 3.7 **输出语言**:5 个阶段提示词 + 2 个 format fragment + 2 命令壳 + 2 contract 各加「面向人读非代码内容用简体中文」规则;代码/路径/`file:class:method` 锚点/标识符/frontmatter 保持原样(D13)。

## 4. Subagent 定义

- [x] 4.1 写 `releases/claude-code/agents/init-survey.md`(frontmatter `name/description/tools/model: inherit`,调用 `discover_controls.py`,JSON I/O)。
- [x] 4.2 写 `releases/claude-code/agents/init-induct.md`(**T1 per-cluster 扇出**:每簇一个独立上下文,消费该簇 `clusters.json` 条目 + 文件集 → 单簇结构化记录;禁做 canonical 判定)。
- [x] 4.3 写 `releases/claude-code/agents/init-synthesis.md`(**T2 综合**:消费全部 T1 记录 → 定 canonical/role、去重 → `controls_inventory.json`)。
- [x] 4.4 写 `releases/claude-code/agents/init-rulewriter.md`(**T3 per-category 扇出**:每 category 一个独立上下文,出 rules 草稿)。
- [x] 4.5 写 `releases/claude-code/agents/init-rules-consistency.md`(**T4**,可选:消费全部 T3 草稿,跨类一致性)。
- [x] 4.6 在 `releases/opencode/agent/` 镜像 4.1–4.5 五个 agent(opencode frontmatter 约定)。

## 5. 命令壳(替换 TODO 骨架)

- [x] 5.1 重写 `releases/claude-code/commands/mgh-init.md`:i0 参数解析+零 token 守卫(`--format` 必选校验、`--help`/无参打印表 STOP)、i1 确定性发现 + **i2 = T1 扇出(per-cluster)→ T2 综合**、**i3 = T3 扇出(per-category)→ T4 一致性**(D12;对标 `mgh-sast.md` 的 stage→component 表 + per-chunk 扇出 + Bash 脚本调用范式)、产物路径、诚实边界披露。
- [x] 5.2 重写 `releases/opencode/command/mgh-init.md`:同 5.1,opencode 调用约定。
- [x] 5.3 校验两壳的参数表一致、且 `--format` 互斥语义明确。

## 6. 安装、自检、文档

- [x] 6.1 更新 `install.sh`:把 `init-*` agent、`init-*` 提示词、`discover_controls.py`、`core/contracts/init/`、`init.yaml` 纳入 `--claude`/`--opencode` 安装清单(沿用镜像到 `.claude/mgh-core/` 的模式)。
- [x] 6.2 零依赖自检:`grep -rnE "^[[:space:]]*(import[[:space:]]+vvaharness|from[[:space:]]+vvaharness[[:space:]]+import)" --include=*.py .` 应无输出;AST 扫描新增脚本无第三方 import。
- [x] 6.3 更新 `docs/upstream-index.md`:登记 mgh-init 与 vvah `design_controls`(`vvaharness/injectors/design_controls.py` + `models.py::Control`)的对应关系——标注「**自动发现**,非手工声明移植;schema 兼容」,保真度/差异一栏写清。
- [x] 6.4 更新 `AGENTS.md` 命令状态表:`/mgh-init` 由 🚧 TODO → ✅ 可用(实现完成后)。

## 7. 规模 / 大文件 / 可恢复性 / 可局部

- [x] 7.1 写 `core/scripts/chunk_sources.py`(标准库 AST):文件 >`--big-file-bytes` 时产出 AST 骨架(imports/class/method 签名/注解)+ 候选函数切片(± 上下文窗口);复用 `expand_scope.DEF_CALL` 语言分派;非 AST 语言回退带重叠行窗口;CLI:`--in <file> --big-file-bytes <N> --out shards.json`。
- [x] 7.2 `tests/test_chunk_sources.py`:验证大文件按 class/method 边界切、不切断函数、切片含候选 + 上下文;小文件不分片。
- [x] 7.3 **T2 综合**(`init-synthesis`)做**竞争聚类 + canonical 选定**(D8;**非** T1):同 `category` 聚类,canonicality 加权(框架背书/调用图入度/包位置/注解化)定 `role`;非 canonical 保留;report 出「竞争控制」专节。
- [x] 7.4 大文件 verify pass:可选 subagent 对大文件 shard 归纳交叉核验,不一致降 `confidence`(D7.3)。
- [x] 7.5 checkpoint + `--resume`:按文件/shard/cluster/category 单元落 `checkpoints/<unit>.json`+done;`--resume` 跳过已完成并合并 parts。
- [x] 7.6 调用图缓存:`cache/callgraph.json` 全仓建一次,`--rebuild-cache` / mtime 失效重建。
- [x] 7.7 `--scope` + `--scope-mode defined|applicable`:局部种子;跨模块控制入 `out_of_scope[]`。
- [x] 7.8 `mgh-init --merge <partials-dir>`:按 `evidence`(`file:class:method`)去重合并多次局部产物,跨模块重算 cluster role。
- [x] 7.9 命令壳(claude/opencode `mgh-init.md`)接入新参数:`--resume`/`--scope`/`--scope-mode`/`--merge`/`--big-file-bytes`/`--max-files`/`--rebuild-cache`。

## 8. 端到端验证

- [x] 8.1 `./install.sh --claude .` 与 `--opencode .` 各装一次,确认 mgh-init 资产就位。
- [x] 8.2 在一个样例 Spring 仓运行 `mgh-init --format claude`:确认产出 `.claude/rules/security-*.md`(带合法 `paths:` frontmatter)+ `controls_inventory.json` + `init_manifest.json`,人工抽查锚点准确性。
- [x] 8.3 同仓运行 `mgh-init --format opencode`:确认产出根 `AGENTS.md`(分节、无 `.opencode/AGENTS.md`),幂等重跑仅替换受管块。
- [x] 8.4 确认 `init_manifest.json`/`report.md` 含三条诚实边界(存在≠有效/CVE-2025-41248、调用图盲点、需人工复核)。
- [x] 8.5 规模验证:对含 **>200KB 大文件** + **两套鉴权**的样例仓跑一次——确认大文件被分片而非整喂、竞争实现被聚类且标 `role`、`out_of_scope[]`/`unresolved[]` 披露。
- [x] 8.6 可恢复/可局部验证:`--scope path:<m>` 跑两模块 → `--merge` 合并去重;中途 `Ctrl-C` 后 `--resume` 续跑产物完整;`--rebuild-cache` 重建调用图。
- [x] 8.7 `py tests/test_init_discover.py` + `py tests/test_chunk_sources.py` + `py tests/test_deterministic.py` 全绿,零依赖自检无输出。
