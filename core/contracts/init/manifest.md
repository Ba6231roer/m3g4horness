# Contract: `init_manifest.json` + checkpoint units

Producer: command orchestrator (i4). Consumer: humans, `/mgh-sra`, `/mgh-blst`, resume.

`init_manifest.json`:

```json
{
  "version": 5,
  "format": "opencode|claude",
  "repo": "<abs repo root>",
  "scope": {"seed": "...", "scope-mode": "defined|applicable"},
  "counts": {"candidates": 0, "controls": 0, "clusters": 0, "unresolved": 0, "out_of_scope": 0, "truncated": false},
  "scout": {"enabled": true, "skeleton_total": 0, "scout_targets": 0, "batches": 0, "deep_read_files": 0, "audit_sampled": 0, "audit_found": 0},
  "codegraph": {"available": false, "used": false, "resolved_count": 0, "unresolved_residual": 0},
  "rules": {"block": "security-controls", "rules_dir": "docs/security-controls (opencode; absent for claude)", "rules_layout": "lazy-index (opencode) | path-scoped (claude)", "categories": 0, "migrated_legacy_blocks": 0, "lint": {"ok": true, "violations": []}},
  "provenance": {"discover": "discover_controls.py", "induct": "init-induct(T1)", "synthesis": "init-synthesis(T2)", "rules": "init-rulewriter(T3)+assemble_rules.py", "scout": "init-scout/merge/audit", "resolve": "init-resolve(codegraph)"},
  "unresolved": ["<file>", ...],
  "out_of_scope": ["<file>", ...],
  "boundaries": [
    "existence-not-effectiveness: CVE-2025-41248 shows @PreAuthorize bypass on parameterized types",
    "call-graph is textual/AST-level; misses AOP/reflection/DI/framework-routing — see unresolved[]",
    "dot-prefixed paths are not scanned by default (tooling/VCS/IDE/build/config/index, e.g. .opencode/.claude/.codegraph/.github/.env) — a control whose definition site lives under a .xxx dir will not be discovered unless --include-dotfiles is passed (see discover_controls.py --help); discover stdout `dotfiles_skipped` counts the pruned sources",
    "codegraph enrichment is optional + assistive only: resolves some framework-routed/AOP/DI/interface→impl controls off unresolved[] but shrinks-not-zeros it (reflection/DI-container/runtime-dispatch residual); resolved candidates are LLM+codegraph candidates needing human review — see codegraph.* counts",
    "LLM-induced candidates — human review required",
    "scout coverage is partial, not whole-repo — see scout.* counts; generic-name + low-fan-in controls may be missed (--no-scout falls back to regex-only)",
    "scout is non-deterministic — cluster count may vary run-to-run (regex-source clusters stay deterministic)",
    "opencode rules are a lazy index in AGENTS.md + per-category detail files: opencode has no path-scoping, so on-demand loading is semantic (directive-driven), not deterministic — an agent that skips the Read may miss a reusable control; claude is path-scoped via paths: (deterministic trigger)",
    "rules purity lint covers high-precision shapes: tool-internal tokens (tool name + distinctive script names + internal paths) + inventory-schema fields (found_controls/evidence_count) + opencode YAML fences (---) + discovery-prose phrases (扫描器模式定义 etc.); bare generic words (category/缺失/锚点), bare tier words (T1/T2/scout), and generic script names remain prompt-guardrail-only, not the deterministic lint"
  ],
  "artifacts": {"candidates":".mgh-init/controls_candidates.json","resolved":".mgh-init/resolved.json (only when codegraph=on & unresolved non-empty)","inventory":".mgh-init/controls_inventory.json","rules-detail(opencode)":"docs/security-controls/*.md (shipped, per-category H1 docs)","rules":"<target>/.claude/rules|<target>/AGENTS.md (security-controls lazy index) + docs/security-controls/*.md (opencode)","report":".mgh-init/report.md"}
}
```

### Checkpoint units (`<target>/.mgh-init/checkpoints/<unit>.json`)

Work-unit granularity = isolation unit = resume unit:

| stage | unit key | file |
|---|---|---|
| i1 discover | per file (big file per shard) | `i1/<sha(file)>.json` + `.done` |
| scout reader | per batch | `scout/<batch_id>.json` + `.done` |
| T1 induct | per cluster | `t1/<cluster_id>.json` + `.done` |
| resolve (opt, codegraph-gated) | whole-repo (1) | `resolved.json` (top-level) + `checkpoints/resolve/.done` |
| T2 synthesis | whole-repo (1) | `t2/synthesis.json` + `.done` |
| T3 rulewriter | per category | `t3/<category>.<format>.json` + `.done` |
| T4 consistency | whole-repo (1) | `t4/consistency.json` + `.done` |

A unit record: `{"unit": "<id>", "status": "done", "out": "<rel path>", "bytes": N}`.
`--resume` skips any unit whose `.done` exists; `--rebuild-cache` ignores
`cache/callgraph.json` (rebuilt from source mtimes otherwise).

> **输出语言**:`boundaries[]`、`provenance` 文案、`report.md` 等面向人读内容用**简体中文**;
> 键名、路径、枚举、计数保持原样。
