# Tasks — harden-mgh-sra-context-budget(sra 采纳)

> 依赖地基 `harden-mgh-init-context-budget` 先落地。机制照搬地基。承 R2/R5.2/R5.3a/b/R5.5/R5.8/R5.9/R5.10。

## 1. sra 枚举脚本

- [x] 1.1 `prepare_augment.py`:增 `--materialize`/`--offset`/`--limit`/`--max-unit-bytes`/`--orch-budget-bytes`;per-cap 物化
      (该 cap `requirements[]` + 相关 endpoints/data_fields/role_hints[复用 `_candidate_controls` 的 file_overlap 判定] +
      `candidate_controls` 切片 + memory)到 `<change-root>/.mgh-sra/inputs/<cap>.input.json`;`pending[]` 加
      `input_path`/`bytes`/`oversize`;oversize 标注(分变更/`--focus`,不切 cap);页宽自动收紧
      (`effective_limit`/`shrunk:true`);退出码/依赖/cwd(承 R5.3a/b);保留无 `--materialize` 旧路径

## 2. sra stage 提示词

- [x] 2.1 `sra-augment.md`:输入段改「读 `input_path`」(该 cap 完整输入);hard rules 加「NEVER 整份读
      `change_context.json`,NEVER `py -c`」
- [x] 2.2 `sra-clarify.md`/`sra-consistency.md`:增聚合 `bytes` 披露护栏(a2 单上下文扫全变更 / a4 全部 drafts;超
      `--max-aggregate-bytes` → 建议 `--focus`/分变更 + 披露未硬界,P0 软边界)

## 3. sra 命令壳(双端)

- [x] 3.1 两份 `mgh-sra.md`「Orchestrator discipline」:增 recipe「需某 cap 完整输入 → `prepare_augment --materialize`
      的 `pending[].input_path`;NEVER 整份读 `change_context.json`,NEVER `py -c`,NEVER 内联传记录」
- [x] 3.2 两份 flow:a3 统一「`prepare_augment --materialize <inputs>` → 按 `offset`/`effective_limit` 分页迭代
      `pending[]`(透传 `input_path`)→ `sra-augment` 读 `input_path`」;翻页循环由编排器(NEVER wrapper `.py`)
- [x] 3.3 两份 parse 段 + flag 表:加 `--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes` 及默认值
- [x] 3.4 两份 disclose:增「单次请求 ≤ 配置阈值;`oversize`/`shrunk`/聚合超限披露」;保持 R5.6 token 预算 + R5.10 纯净性

## 4. 契约 lint + 测试

- [x] 4.1 `tools/check_contracts.py`:扩 `prepare_augment` flag + `mgh-sra.md` flag(R5.1 CLI lint)
- [x] 4.2 `tests/` 增 `prepare_augment` per-cap 物化(切片语义:file_overlap 过滤)/分页/oversize 标注测 + 纪律回归
      (整份读 `change_context.json` 在 `MGH_SRA_ACTIVE=1` 下被 hook 拦,exit 2 + recipe)
- [x] 4.3 性能不退化 + 零依赖 AST 扫描集不变 + R5.1 CLI lint 过

## 5. 版本 + 收尾

- [x] 5.1 `mgh-sra.md` 壳 + `prepare_augment.py` bump 版本号
- [x] 5.2 `openspec validate harden-mgh-sra-context-budget --strict` 过;`/opsx:apply` ready(地基先行)
