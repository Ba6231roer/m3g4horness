<!--
  mgh-init stage-flow — survey (step 3, optional). Install mirrors to <mgh-core>/prompts/fragments/init-stage/.
  Reachability: survey is an optional/advisory stage — resume_state.py step derivation NEVER
  routes here (it never gates progress); the ORCHESTRATOR decides to run this stage and loads
  this file by fixed-path Read.
-->

## survey (step 3)

```
3. (optional) init-survey subagent → i1_enriched.json
   · **advisory + non-fatal**:产出仅作审计/T2 参考,**非 T1 输入**(T1 读 `clusters.json`);
     缺失 `i1_enriched.json` **不阻断**、不报致命错。`total` 过大(单 subagent 装不下整仓簇)
     时**跳过**,并在摘要披露。
```
