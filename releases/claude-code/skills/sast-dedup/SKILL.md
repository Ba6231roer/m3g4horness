---
name: sast-dedup
description: s7 deterministic+semantic dedup. Wraps dedup.py — clusters findings by (file, CWE, line proximity) and normalized-title overlap, keeping the highest-confidence representative. Deterministic; same input → same output.
license: Apache-2.0
---

# s7 dedup (deterministic)

Wraps `.claude/mgh-core/scripts/dedup.py`.

```bash
py .claude/mgh-core/scripts/dedup.py \
  --in checkpoints/s6_verdicts.json --out checkpoints/s7_findings.json \
  --line-window 5 --title-thresh 0.6
```
Canonical findings get a `duplicates[]` field listing what was folded in.
