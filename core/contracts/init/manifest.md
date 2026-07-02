# Contract: `init_manifest.json` + checkpoint units

Producer: command orchestrator (i4). Consumer: humans, `/mgh-sra`, `/mgh-blst`, resume.

`init_manifest.json`:

```json
{
  "version": 1,
  "format": "opencode|claude",
  "repo": "<abs repo root>",
  "scope": {"seed": "...", "scope-mode": "defined|applicable"},
  "counts": {"candidates": 0, "controls": 0, "clusters": 0, "unresolved": 0, "out_of_scope": 0, "truncated": false},
  "provenance": {"discover": "discover_controls.py", "induct": "init-induct(T1)", "synthesis": "init-synthesis(T2)", "rules": "init-rulewriter(T3)"},
  "unresolved": ["<file>", ...],
  "out_of_scope": ["<file>", ...],
  "boundaries": [
    "existence-not-effectiveness: CVE-2025-41248 shows @PreAuthorize bypass on parameterized types",
    "call-graph is textual/AST-level; misses AOP/reflection/DI/framework-routing — see unresolved[]",
    "LLM-induced candidates — human review required"
  ],
  "artifacts": {"candidates":".mgh-init/controls_candidates.json","inventory":".mgh-init/controls_inventory.json","rules":"<target>/.claude/rules|<target>/AGENTS.md","report":".mgh-init/report.md"}
}
```

### Checkpoint units (`<target>/.mgh-init/checkpoints/<unit>.json`)

Work-unit granularity = isolation unit = resume unit (D9 = D12):

| stage | unit key | file |
|---|---|---|
| i1 discover | per file (big file per shard) | `i1/<sha(file)>.json` + `.done` |
| T1 induct | per cluster | `t1/<cluster_id>.json` + `.done` |
| T2 synthesis | whole-repo (1) | `t2/synthesis.json` + `.done` |
| T3 rulewriter | per category | `t3/<category>.<format>.json` + `.done` |
| T4 consistency | whole-repo (1) | `t4/consistency.json` + `.done` |

A unit record: `{"unit": "<id>", "status": "done", "out": "<rel path>", "bytes": N}`.
`--resume` skips any unit whose `.done` exists; `--rebuild-cache` ignores
`cache/callgraph.json` (rebuilt from source mtimes otherwise).

> **输出语言**:`boundaries[]`、`provenance` 文案、`report.md` 等面向人读内容用**简体中文**;
> 键名、路径、枚举、计数保持原样。
