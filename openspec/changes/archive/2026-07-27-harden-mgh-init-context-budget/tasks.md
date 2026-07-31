# Tasks — harden-mgh-init-context-budget(地基:init 落地 + 立横切 spec)

> 本 change = 地基。实现顺序:共享逻辑 → init 三 `list_*` → stage 提示词 → 命令壳 → hook/lint → 测试 →
> install/版本。承 R2/R5.2/R5.3a/b/R5.5/R5.8/R5.9/R5.10。机制统辖见 `request-context-budget` spec(含四命令映射表,
> 标 sast/sra/srr = 后续 adoption change)。P0 = 本 change;P1(聚合分层归约)留后续。
>
> **sast/sra/srr 不在本 change**——由 `harden-mgh-{sast,sra,srr}-context-budget` 各自照本 change 的 init 模式采纳。

## 1. 契约 + 共享预算/物化逻辑(地基,四命令复用)

- [x] 1.1 新增 `core/contracts/init/unit-inputs.md`:per-unit input 物化契约(路径 `<target>/.mgh-init/inputs/<tier>/<unit>.input.json`、
      schema、幂等·`--resume`、`bytes`/`oversize`、子单元 `::shard-<n>` 派生);附四命令路径约定(init `.mgh-init/inputs/`、
      sast `security-scan/inputs/`、sra `.mgh-sra/inputs/`、srr `<out-dir>/inputs/`——供后续 adoption 引用)
- [x] 1.2 `core/contracts/init/clusters.md` + `inventory.md` 消费侧增注:完整记录经 `list_* --materialize` 下沉到
      input 文件,subagent 读 `input_path`(不再整份读 `clusters.json`/inventory)
- [x] 1.3 共享预算逻辑(标准库;优先内联为各 `list_*` 私有函数,零依赖 AST 扫描集不变):字节测、`--max-unit-bytes`
      切分/标注、`--offset`/`--limit` + `--orch-budget-bytes` 自动收紧页宽、`effective_limit`/`shrunk` 计算

## 2. init 枚举脚本(参考实现)

- [x] 2.1 `list_clusters.py`:增 `--materialize`/`--offset`/`--limit`/`--max-unit-bytes`/`--orch-budget-bytes`;slim 壳
      (去 `evidence_files[]`,加 `input_path`/`bytes`/`oversize`);物化每簇完整记录(簇字段 + 候选命中回查
      `controls_candidates.json` + usage_sites);oversize 切 `::shard-<n>`;页宽自动收紧;退出码/依赖/cwd(承 R5.3a/b)
- [x] 2.2 `list_scout_batches.py`:同构(`--max-unit-bytes` 与 `--batch-bytes` 取 min;超大文件 `needs_slice` → `chunk_sources`)
- [x] 2.3 `list_rule_jobs.py`:同构(oversize category 标 `oversize` 不切)

## 3. init stage 提示词(subagent 改读 `input_path`)

- [x] 3.1 `init-induct.md`:输入段改「读 `input_path`」(簇记录 + 候选命中 + usage_sites);hard rules 加「NEVER 整份读
      `clusters.json`,NEVER `py -c`」
- [x] 3.2 `init-scout.md`:输入段改「读 `input_path`」(batch 完整 targets);`needs_slice` 语义不变
- [x] 3.3 `init-rulewriter.md`:输入段改「读 `input_path`」(该 category 的 controls)
- [x] 3.4 `init-synthesis.md`/`init-scout-merge.md`/`init-rules-consistency.md`:增聚合 `bytes` 披露护栏(超 `--max-aggregate-bytes`
      → 建议 `--scope`+`--merge`、披露本 stage 聚合未硬界;P0 软边界,P1 分层归约占位)

## 4. init 命令壳(claude + opencode 双端)

- [x] 4.1 两份 `mgh-init.md`「Orchestrator discipline」:增 recipe「需某单元完整记录 → `list_* --materialize` 的
      `pending[].input_path`(绝对);NEVER 整份读 `clusters.json`/`controls_inventory.json`/`scout_plan.json`,NEVER `py -c`,
      NEVER 内联传记录给 subagent」
- [x] 4.2 两份 flow:scout(3b)/T1(4)/T3(6) 三 tier 统一「`list_* --materialize <inputs/<tier>>` → 按
      `offset`/`effective_limit` 分页迭代 `pending[]`(透传 `input_path`)→ subagent 读 `input_path`」;翻页循环由编排器
      (NEVER wrapper `.py`,承 R5.2)
- [x] 4.3 两份 parse 段 + flag 表:加 `--max-unit-bytes`(192KB)/`--orch-budget-bytes`(64KB)/`--max-aggregate-bytes`(256KB)
- [x] 4.4 两份「Always disclose」:增「单次请求 ≤ 配置阈值;`oversize`/`shrunk`/聚合超限在 `init_manifest.json::boundaries[]`+
      `report.md` 披露;P0 聚合为软边界」
- [x] 4.5 保持 R5.6 token 预算(≤500 行/≤5k tokens;详情移 `core/prompts/`;无 `@` 内联)+ R5.10 纯净性

## 5. hook + 契约 lint(地基,一次覆盖四运行域)

- [x] 5.1 `releases/claude-code/hooks/block_adhoc_scripts.py` + `releases/opencode/hooks/block_adhoc_scripts.py` + opencode
      `block_adhoc_scripts.ts`:recipe 增「整份读多单元聚合 → 指向 `input_path`/`describe_artifact`」;判定逻辑单一来源、
      双端 parity;四运行域 `MGH_{INIT,SAST,SRA,SRR}_ACTIVE` 可靠性边界不变(**后续 sast/sra/srr adoption 直接复用,不再改 hook**)
- [x] 5.2 `tools/check_contracts.py`:扩 flag 覆盖——init 三 `list_*` 的 `--materialize`/`--offset`/`--limit`/
      `--max-unit-bytes`/`--orch-budget-bytes`;`mgh-init.md` 的 `--max-aggregate-bytes`(R5.1 CLI lint;**后续各 adoption 各加各命令的 flag**)

## 6. 测试(R5.8 回归,init)

- [x] 6.1 `tests/test_init_clusters.py` 等扩:物化产出 `<unit>.input.json` + `input_path`/`bytes`/`oversize`;slim 壳无
      `evidence_files[]`;分页 `offset`/`limit`;页宽自动收紧 `shrunk:true`;oversize 切 `::shard-<n>` 且各 ≤ 预算
- [x] 6.2 `tests/` 增 `list_scout_batches`/`list_rule_jobs` 同构测(物化/分页/oversize 处置差异)
- [x] 6.3 回归:整份读多单元产物(`Read`/`cat`/`py -c` 整份 `clusters.json` 等)在 `MGH_INIT_ACTIVE=1` 下被 hook 拦
      (exit 2 + recipe 指向 `input_path`)
- [x] 6.4 性能不退化(物化单遍 I/O、per-unit O(1)、无第二次全仓遍历,R5.4)+ 零依赖 AST 扫描集不变 + R5.1 CLI lint 过

## 7. install 自检 + 版本 + 收尾

- [x] 7.1 `install.sh` 共定位自检:无新脚本名(复用三 `list_*`);`inputs/` 随 `.mgh-init/`;fail-soft 自检不阻断 install、
      CI 必 fail(承 R5.8)
- [x] 7.2 命令壳 + 三 `list_*` 脚本 bump 版本号
- [x] 7.3 `openspec validate harden-mgh-init-context-budget --strict` 过;`/opsx:apply` ready
