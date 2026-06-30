---
name: sast-prefilter
description: s5 deterministic confidence/evidence gate. Wraps prefilter.py — drops findings missing source_ref/sink_ref line numbers, below the confidence threshold, or in test/example/build paths. Deterministic; same input → same output.
license: Apache-2.0
---

# s5 pre-filter (deterministic)

Wraps `.claude/mgh-core/scripts/prefilter.py` (the primary FP defense).

```bash
py .claude/mgh-core/scripts/prefilter.py \
  --in checkpoints/s4_candidates.json --out checkpoints/s5_filtered.json \
  --min-confidence 0.4 [--scope-file checkpoints/scope_manifest.json]
```
Emits `{"kept":[…],"dropped":[{finding,dropped_reason}]}`. Mirrors the original
s5 evidence gate + EXCLUSION_RULES groups A/E (no real attacker / noise floor).
