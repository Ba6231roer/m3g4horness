# Contract: `init_manifest.json` + checkpoint units

Producer: command orchestrator (i4). Consumer: humans, `/mgh-sra`, `/mgh-blst`, resume.

`init_manifest.json`:

```json
{
  "version": 2,
  "format": "opencode|claude",
  "repo": "<abs repo root>",
  "scope": {"seed": "...", "scope-mode": "defined|applicable"},
  "counts": {"candidates": 0, "controls": 0, "clusters": 0, "unresolved": 0, "out_of_scope": 0, "truncated": false},
  "scout": {"enabled": true, "skeleton_total": 0, "scout_targets": 0, "batches": 0, "deep_read_files": 0, "audit_sampled": 0, "audit_found": 0},
  "rules": {"block": "security-controls", "categories": 0, "migrated_legacy_blocks": 0, "lint": {"ok": true, "violations": []}},
  "provenance": {"discover": "discover_controls.py", "induct": "init-induct(T1)", "synthesis": "init-synthesis(T2)", "rules": "init-rulewriter(T3)+assemble_rules.py", "scout": "init-scout/merge/audit"},
  "unresolved": ["<file>", ...],
  "out_of_scope": ["<file>", ...],
  "boundaries": [
    "existence-not-effectiveness: CVE-2025-41248 shows @PreAuthorize bypass on parameterized types",
    "call-graph is textual/AST-level; misses AOP/reflection/DI/framework-routing — see unresolved[]",
    "LLM-induced candidates — human review required",
    "scout coverage is partial, not whole-repo — see scout.* counts; generic-name + low-fan-in controls may be missed (--no-scout falls back to regex-only)",
    "scout is non-deterministic — cluster count may vary run-to-run (regex-source clusters stay deterministic)",
    "rules purity lint covers only high-precision tool-internal tokens (tool name + distinctive script names + internal paths); bare tier words (T1/T2/scout) and generic script names are covered by the prompt guardrail, not the deterministic lint"
  ],
  "artifacts": {"candidates":".mgh-init/controls_candidates.json","inventory":".mgh-init/controls_inventory.json","rules-parts(opencode)":".mgh-init/rules-parts/*.md","rules":"<target>/.claude/rules|<target>/AGENTS.md (security-controls block)","report":".mgh-init/report.md"}
}
```

### Checkpoint units (`<target>/.mgh-init/checkpoints/<unit>.json`)

Work-unit granularity = isolation unit = resume unit:

| stage | unit key | file |
|---|---|---|
| i1 discover | per file (big file per shard) | `i1/<sha(file)>.json` + `.done` |
| scout reader | per batch | `scout/<batch_id>.json` + `.done` |
| T1 induct | per cluster | `t1/<cluster_id>.json` + `.done` |
| T2 synthesis | whole-repo (1) | `t2/synthesis.json` + `.done` |
| T3 rulewriter | per category | `t3/<category>.<format>.json` + `.done` |
| T4 consistency | whole-repo (1) | `t4/consistency.json` + `.done` |

A unit record: `{"unit": "<id>", "status": "done", "out": "<rel path>", "bytes": N}`.
`--resume` skips any unit whose `.done` exists; `--rebuild-cache` ignores
`cache/callgraph.json` (rebuilt from source mtimes otherwise).

> **输出语言**:`boundaries[]`、`provenance` 文案、`report.md` 等面向人读内容用**简体中文**;
> 键名、路径、枚举、计数保持原样。
