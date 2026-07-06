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
  "source": "regex|scout|regex+scout"
}
```

- `category` ∈ the 8 init categories (see inventory.md).
- `kind` ∈ vvah 6-enum (see `category→kind` map in inventory.md).
- `anchor` = nearest enclosing class/method (textual via DEF_CALL) for indexing.
- `shape` ∈ `centralized` (util/filter/config/interceptor def) | `distributed` (annotation scattered across files).
- `cluster_id` = `category::anchor` (deterministic T1 isolation unit).
- `entry_points` = immediate caller files of `file` (from reverse call graph).
- `big_file` = file bytes > `--big-file-bytes` (feed via chunk_sources slice, not whole).
- `source` ∈ `{regex, scout, regex+scout}`(可选,additive):候选来源——regex fast-path
  或 LLM scout 发现层(`improve-mgh-init-llm-discovery`);缺省视作 `regex`。
- `unresolved[]` = framework-routed/Feign/AOP/DI files with no textual edge (call-graph blind spot).
- `out_of_scope[]` = cross-module controls whose def-site is outside `--scope` (disclosed, not dropped).
