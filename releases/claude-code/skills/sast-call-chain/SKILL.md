---
name: sast-call-chain
description: Call-chain scope expansion for incremental/scoped SAST. Wraps the deterministic expand_scope.py engine (zero-dep text call graph + optional tree-sitter + bidirectional BFS + Spring/Feign/AOP framework hints). Produces scope_manifest.json.
license: Apache-2.0
---

# Call-chain scope expansion

Thin skill wrapper over the deterministic engine
`.claude/mgh-core/scripts/expand_scope.py` (zero runtime deps).

## When to use
The `sast-scope-resolver` agent invokes this for `--diff` / `--path` /
`--package` scans. Inputs: a seed (from `diff_seed.py`), direction, depth.

## Invocation
```bash
py .claude/mgh-core/scripts/diff_seed.py --repo <root> --diff <ref> --out checkpoints/seed.json
py .claude/mgh-core/scripts/expand_scope.py --repo <root> \
  --seed-file checkpoints/seed.json --direction both --depth 2 --out checkpoints/scope_manifest.json
```
The engine builds a per-language textual call graph, expands reachable files,
adds Spring/Feign/AOP/DI framework-hint files, and records unresolved framework
edges (the call-graph blind spot) in `scope_manifest.unresolved[]`.
