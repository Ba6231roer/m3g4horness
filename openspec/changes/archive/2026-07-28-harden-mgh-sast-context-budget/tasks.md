# Tasks — harden-mgh-sast-context-budget(sast 采纳)

> 依赖地基 `harden-mgh-init-context-budget` 先落地(`request-context-budget` spec + `unit-inputs.md` 契约 +
> hook recipe + `list_clusters.py` 参考实现)。机制逐字照搬地基,不重新设计。承 R2/R5.2/R5.3a/b/R5.5/R5.8/R5.9/R5.10。

## 1. sast 枚举脚本(照搬地基模式)

- [x] 1.1 `list_chunks.py`:增 `--materialize`/`--offset`/`--limit`/`--max-unit-bytes`/`--orch-budget-bytes`;物化每 chunk
      完整输入(`files[]`+`threat_id`+`hypothesis`)到 `security-scan/inputs/s4/<chunk_id>.input.json`;slim 壳(完整
      `files[]` 下沉,加 `input_path`/`bytes`/`oversize`);oversize 且含 > `--big-file-bytes` 文件 → `needs_slice` →
      `chunk_sources`;页宽自动收紧(`effective_limit`/`shrunk:true`);退出码/依赖/cwd(承 R5.3a/b)
- [x] 1.2 `list_verify_jobs.py`:同构(物化 finding 完整 source/sink 锚点到 `security-scan/inputs/s6/<finding_id>.input.json`;
      oversize 标 `oversize` 不切;页宽自动收紧)

## 2. sast stage 提示词

- [x] 2.1 `sast-deepdive.md`:输入段改「读 `input_path`」(chunk files + threat + hypothesis);hard rules 加
      「NEVER 整份读 `s3_chunks.json`,NEVER `py -c`」
- [x] 2.2 `sast-verify.md`:输入段改「读 `input_path`」(finding source/sink 锚点 + 上下文)

## 3. sast 命令壳(双端)

- [x] 3.1 两份 `mgh-sast.md`「Orchestrator discipline」:增 recipe「需某单元完整记录 → `list_chunks`/`list_verify_jobs`
      `--materialize` 的 `pending[].input_path`;NEVER 整份读 `s3_chunks.json`/`s5_filtered.json`,NEVER `py -c`,NEVER 内联传记录」
- [x] 3.2 两份 flow:s4/s6 统一「`list_* --materialize <inputs/<tier>>` → 按 `offset`/`effective_limit` 分页迭代
      `pending[]`(透传 `input_path`)→ subagent 读 `input_path`」;翻页循环由编排器(NEVER wrapper `.py`)
- [x] 3.3 两份 parse 段 + flag 表:加 `--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes` 及默认值
- [x] 3.4 两份 disclose:增「单次请求 ≤ 配置阈值;`oversize`/`shrunk` 披露」;保持 R5.6 token 预算 + R5.10 纯净性

## 4. 契约 lint + 测试

- [x] 4.1 `tools/check_contracts.py`:扩 sast 两脚本 flag + `mgh-sast.md` flag(R5.1 CLI lint)
- [x] 4.2 `tests/` 增 `list_chunks`/`list_verify_jobs` 物化/分页/oversize 切片测 + 纪律回归(整份读 s3/s5 产物在
      `MGH_SAST_ACTIVE=1` 下被 hook 拦,exit 2 + recipe)
- [x] 4.3 性能不退化 + 零依赖 AST 扫描集不变 + R5.1 CLI lint 过

## 5. 版本 + 收尾

- [x] 5.1 `mgh-sast.md` 壳 + 两脚本 bump 版本号
- [x] 5.2 `openspec validate harden-mgh-sast-context-budget --strict` 过;`/opsx:apply` ready(地基先行)
