# Stage I/O contracts (JSON)

All inter-stage artifacts are plain JSON written to `<target>/checkpoints/`.
The canonical finding shape (mirrors the s4 OUTPUT_SCHEMA) is
`finding.schema.json`.

| File | Producer | Consumer | Shape |
|---|---|---|---|
| `s1_context.json` | s1 survey | s2, s3 | file inventory, call graph, entry points, sinks |
| `s2_threats.json` | s2 threat-model | s3 | assets, trust boundaries, ranked threats |
| `s3_chunks.json` | s3 decompose | s4 | analysis chunks (file sets + lens) |
| `s4_candidates.json` | s4 deep-dive | s5 | `{"findings": [Finding, ...]}` |
| `s5_filtered.json` | s5 prefilter (script) | s6 | `{"kept":[Finding],"dropped":[{finding,reason}]}` |
| `s6_verdicts.json` | s6 verify | s7 | `[{...finding, verdict:"TRUE|FALSE_POSITIVE", cvss_vector}]` |
| `s7_findings.json` | s7 dedup (script) | s8 | `{"findings":[Finding]}` (canonical) |
| `s8_chains.json` | s8 chain | s9 / report | `{...findings, chains:[...]}` |
| `findings.json` | (final) | s9 / report | `{"findings":[Finding]}` |
| `scope_manifest.json` | scope-resolver | s1 | seed + in_scope + unresolved |

A `Finding` object:

```json
{
  "id": "F-001",
  "title": "Unauthenticated SQLi in login (≤12 words)",
  "vuln_class": "injection",
  "cwe": "CWE-89",
  "file": "src/api/Controller.java",
  "line_start": 71, "line_end": 78,
  "impact": "2-3 sentences: attacker gain, who, why",
  "description": "input->bug data flow",
  "exploit_scenario": "specific payload + effect",
  "preconditions": ["condition 1"],
  "recommendation": "property to enforce + where + what to change",
  "code_snippet": "vulnerable lines",
  "source_ref": "src/api/Controller.java:71",
  "sink_ref": "src/db/Query.java:42",
  "confidence": 0.85,
  "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
  "cvss_score": 9.8,
  "severity": "Critical",
  "verdict": "TRUE",
  "dropped_reason": null
}
```

`severity` is ALWAYS derived from the CVSS 3.1 base-score band and can never
disagree with `cvss_score` (see `emit_sarif.py::severity_band`):
Critical 9.0–10.0 · High 7.0–8.9 · Medium 4.0–6.9 · Low 0.1–3.9 · Info (no path).

## sra 增补 + 业务记忆契约

`/mgh-sra`(openspec 安全设计补充)的 I/O 与业务记忆契约:

| File | Scope | Shape |
|---|---|---|
| `sra/augmentation.md` | sra 增补 I/O | `change_context.json` / draft(`gaps[]`+`security_requirements[]`+`security_tasks[]`)/ `sra_manifest.json` + 各 producer `--check` |
| `sra/business-context.md` | 项目级业务记忆 | `business_context.json`(`roles[]`/`domains[]`/`sensitive_fields[]`/`interface_authz[]`/`clarifications[]`)+ `clarification` shape + `merge_memory` 幂等累积 |
