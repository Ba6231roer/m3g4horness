---
name: sast-sarif
description: s9 deterministic SARIF 2.1.0 emission with CVSS 3.1 + CWE. Wraps emit_sarif.py — computes CVSS base score from each vector, derives severity from the official band (label never disagrees with score), maps CWE ids, writes report.sarif.
license: Apache-2.0
---

# s9 SARIF emission (deterministic)

Wraps `.claude/mgh-core/scripts/emit_sarif.py` (stdlib CVSS 3.1 calculator).

```bash
py .claude/mgh-core/scripts/emit_sarif.py \
  --in checkpoints/findings.json --out security-scan/report.sarif \
  --repo-name <name> --application-id <id>
```
Severity bands: Critical 9.0–10 · High 7.0–8.9 · Medium 4.0–6.9 · Low 0.1–3.9 ·
Info (no demonstrated path). Also writes `report.sarif.findings.json` with the
enriched severity/score for the report assembler.
