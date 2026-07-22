# Contract: `controls_candidates.json`

Producer: `core/scripts/discover_controls.py` (i1, deterministic, stdlib).
Consumer: `init-induct` (T1, per-cluster) and audit trail.

Top-level shape:

```json
{
  "repo": "<abs repo root>",
  "scope": {"mode": "defined|applicable", "seed": "path:src/x|package:com.x|file:*", "scope-mode": "defined"},
  "generated_by": "discover_controls.py",
  "candidates": [<Candidate>, ...],
  "truncated": false,
  "max_files_note": "warned-and-continued when source files > --max-files",
  "unresolved": ["<file>", ...],
  "out_of_scope": ["<file>", ...]
}
```

A `Candidate` (one control-shaped hit):

```json
{
  "id": "C-0001",
  "file": "src/main/java/com/bank/auth/SecurityConfig.java",
  "line": 42,
  "category": "authorization",
  "kind": "auth",
  "pattern": "@EnableMethodSecurity",
  "anchor": {"class": "SecurityConfig", "method": null, "kind": "class|method|annotation|field"},
  "snippet": "  @EnableMethodSecurity ...",
  "shape": "centralized",
  "cluster_id": "authorization::SecurityConfig",
  "entry_points": ["src/main/java/com/bank/api/TransferController.java"],
  "big_file": false,
  "source": "regex|scout|regex+scout|codegraph"
}
```

- `category` ∈ the 8 init categories (see inventory.md).
- `kind` ∈ 6-enum (see `category→kind` map in inventory.md).
- `anchor` = nearest enclosing class/method (textual via DEF_CALL) for indexing.
- `shape` ∈ `centralized` (util/filter/config/interceptor def) | `distributed` (annotation scattered across files).
- `cluster_id` = `category::anchor` (deterministic T1 isolation unit).
- `entry_points` = immediate caller files of `file` (from reverse call graph).
- `big_file` = file bytes > `--big-file-bytes` (feed via chunk_sources slice, not whole).
- `source` ∈ `{regex, scout, regex+scout, codegraph}`(可选,additive):候选来源——regex fast-path、
  LLM scout 发现层、或 `init-resolve` 经 codegraph 解析 `unresolved[]` 得到的候选;缺省视作 `regex`。
  `codegraph` 候选 additive 并入(见 `core/contracts/init/resolved.md`),与 `regex`/`scout` 同为结构标识,
  适用相同纯净性规则;该值的出现 MUST NOT 使人读字段引入 codegraph 工具名或「经索引解析」之类过程描述。
- `unresolved[]` = framework-routed/Feign/AOP/DI files with no textual edge (call-graph blind spot).
- `out_of_scope[]` = cross-module controls whose def-site is outside `--scope` (disclosed, not dropped).
- **文件枚举剪枝(单 chokepoint)**:遍历跳过任一以 `.` 开头的路径分量(tooling/VCS/IDE/build/config/
  索引,如 `.opencode`/`.claude`/`.codegraph`/`.github`/`.env`),统一作用于 regex 候选、`skeleton.json`、
  调用图、scout 目标集。`discover_controls.py --include-dotfiles` 覆盖(回退到扫描点前缀路径)。
  `EXCLUDE_DIR`(精确名匹配,含 `node_modules`/`target`/`build`/`vendor` 等非点构建/缓存目录)**保持不变**。
  故候选 `file`、`unresolved[]`、`out_of_scope[]` 均不含点前缀路径。

### Producer stdout summary (downstream reads these, never re-derives)

`discover_controls.py` prints a one-line JSON summary on stdout;编排器/subagent 需要的
**派生量**由产出者直接 emit,而非留给下游 list keys / len / 自写脚本:

```json
{"candidates": N, "clusters": M, "unresolved": U, "unresolved_count": U,
 "big_files": K, "dotfiles_skipped": D, "out_of_scope": O, "truncated": false, "scanned": S}
```

| field | note |
|---|---|
| `big_files` | 超 `--big-file-bytes` 的源文件数(T1/scout 切片决策的下游常查量) |
| `unresolved_count` | `len(unresolved[])`(`unresolved` 的别名,便于直接消费) |
| `dotfiles_skipped` | 默认剪枝跳过的点前缀**源**文件计数(披露/排查用);`--include-dotfiles` 时为 `0` |
