## Why

`/mgh-sast` 找的是「代码里有什么漏洞」,但从不回答「这个项目**已经**沉淀了哪些
可复用的安全设计」。结果是:AI(和新人)写新代码时反复**重新发明**输入校验、脱敏、
鉴权封装,既制造不一致,又把 SAST 喂成误报源——把团队**已做好的防护**当成漏洞报。

这是上游 vvaharness 早就有的概念(`design_controls.yaml`:团队**手工**声明既有控制,
s2/s6/s8 据此降 likelihood / 判 FP / 重排严重度),但 **mgh-sast 重写时未移植该机制**
(doc 09 §1.2 确认:`grep design_controls` 全空)。手工声明门槛高、易过期。

`/mgh-init` 补这块:**自动**从存量代码发现并归纳既有安全控制,产出 (1) 结构化的
`controls_inventory.json`(与 vvah `design_controls` schema 兼容,可被 mgh-sra /
mgh-blst / 未来 mgh-sast 控制入口消费)与 (2) AI 编程 Agent 可直接加载的 **rules**
(Claude Code `.claude/rules/` 或 opencode `AGENTS.md`,二选一,结构严格不混用)。

> 理论基础:`glasswing_docs/09_防御侧三问…` §1(Q1「既有控制识别」)三层组合建议
> (规则快扫 → 调用图建模 → LLM 语义归纳)。受 R2(零运行时依赖)约束,本实现
> **不引入 Semgrep / CodeQL**——采用与 `mgh-sast` 的 `expand_scope.py` 相同的
> 文本/AST + 框架 allowlist 取舍,并显式披露这一边界。

## What Changes

- **新增 `/mgh-init` 命令**(Claude Code + opencode 双 shell),替换现有 TODO 骨架:
  扫描存量代码 → 归纳既有安全设计 → 生成 Agent rules。参数 `--target` / `--format`
  (必选)/ `--out` / `--scope` / `--language`。
- **新增确定性发现脚本** `core/scripts/discover_controls.py`(Python ≥3.10 标准库):
  按 kind(输入校验 / 脱敏 / 鉴权 / 鉴权认证 / 加密 / 限流防重放 / CSRF / 审计)
  的文件名 + 内容模式 + 注解特征扫描候选,并**复用 `expand_scope.py` 的调用图引擎**
  关联「每个控制被谁调用 / 接入哪些入口」。产出 `controls_candidates.json` + `unresolved[]`。
  **流式逐文件**、关闭静默截断上限(改 `--max-files` 显式告警)。
- **新增大文件分片脚本** `core/scripts/chunk_sources.py`(标准库 AST):>`--big-file-bytes`
  的文件先产 AST 骨架再切候选函数切片,保证大文件 LLM 分析稳定准确。
- **规模/可恢复/可局部能力**:`--resume`(按文件/shard/cluster/category 工作单元
  checkpoint + 调用图缓存)、`--scope path|package|file` + `--scope-mode defined|applicable`
  局部分析、`mgh-init --merge` 按 evidence 去重合并多次局部产物、**竞争实现聚类 +
  canonical 选定**(同 category 多套鉴权/脱敏自动归并标 `role`)。
- **新增归纳 / 出 rules 的 SYSTEM 提示词**(`core/prompts/stages/init-*.md`):
  把候选聚类归纳为「这是什么控制、怎么用、入口在哪、覆盖缺口」,再按 `--format`
  渲染为目标 Agent 的 rules 结构。提示词带 vvah 溯源注释设计风格(若移植则标注,
  纯自创则标注 `rewrite-original`)。
- **新增 subagent 定义**(`init-survey` / `init-induct`(T1)/ `init-synthesis`(T2)/
  `init-rulewriter`(T3)/ `init-rules-consistency`(T4,可选))与 `mgh-init` profile
  (`core/profiles/init.yaml`),沿用 mgh-sast 的 frontmatter / per-chunk 扇出 / 脚本调用 /
  JSON I/O 约定。**隔离优先**:每个控制簇 / 每个 category 各在独立 LLM 上下文处理(D12)。
- **新增契约** `core/contracts/init/`:`controls_inventory.json` 与
  `controls_candidates.json` 的 schema。**inventory schema 与 vvah
  `Control{name, kind, protects, notes}` 向后兼容**(扩展 `category` / `usage` /
  `evidence` / `entry_points` / `gaps`)。
- **新增单测** `tests/test_init_discover.py`:验证 `discover_controls.py` 的模式命中、
  调用图关联、零依赖 AST 扫描。
- **诚实边界写入产物**:`init_manifest.json` + `report.md` 明示「**控制存在 ≠ 控制有效**
  (CVE-2025-41248:参数化类型上 `@PreAuthorize` 可绕过)」、调用图盲点(AOP / 反射 /
  DI / 框架路由)、LLM 归纳候选需人工复核。

## Capabilities

### New Capabilities
- `control-discovery`: 从存量代码自动发现并归纳既有安全控制——确定性模式扫描 +
  调用图关联(复用 `expand_scope.py`)+ LLM 语义归纳 → 结构化
  `controls_inventory.json`(与 vvah `design_controls` schema 兼容)。定义「发现什么、
  如何归类、覆盖缺口如何披露」的契约。
- `rules-emission`: 把 inventory 渲染为**目标 Agent 可加载**的 rules——Claude Code 走
  `.claude/rules/*.md`(path-scoped `paths:` frontmatter,官方机制)或 opencode 走
  根目录 `AGENTS.md`(不支持 path-scoping / dot-dir)。**两者结构严格不混用**,
  `--format` 必选;非破坏性(已有 rules / AGENTS.md 时追加受管块,不覆盖)。

### Modified Capabilities
<!-- 无既有 spec。openspec/specs/ 当前为空,全部为新增。 -->

## Impact

- **新增代码**:`core/scripts/discover_controls.py`、`core/scripts/chunk_sources.py`、`core/prompts/stages/init-{survey,induct,rulewriter}.md`、`core/contracts/init/*.md`、`core/profiles/init.yaml`、`releases/{claude-code,opencode}/` 下的 `mgh-init` 命令 + `init-*` subagent、`tests/test_init_discover.py`、`tests/test_chunk_sources.py`。
- **改动代码**:替换 `releases/claude-code/commands/mgh-init.md` 与
  `releases/opencode/command/mgh-init.md` 的 TODO 骨架为真实实现。
- **install.sh**:把 `init-*` subagent / prompts / `discover_controls.py` 纳入
  `--claude` / `--opencode` 安装清单(沿用现有 core 镜像到 `.claude/mgh-core/` 的模式)。
- **依赖**:**零新增运行时依赖**(R2)。`discover_controls.py` 仅用标准库
  (`argparse/ast/collections/json/pathlib/re/sys`);不 import 任何 `vvaharness/`。
- **无 BREAKING**:新增命令 + 新增能力;现有 `/mgh-sast` 不受影响。
- **产物消费方**:`/mgh-sra`(读 rules 引导 specs/tasks)、`/mgh-blst`(据 inventory 找
  「未走统一校验」的接口)、未来 mgh-sast 控制入口(读 `controls_inventory.json`)。
