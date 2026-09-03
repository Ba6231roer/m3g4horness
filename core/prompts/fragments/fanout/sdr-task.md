<!--
  mgh-sdr fan-out task message template (sdr tier). Install mirrors to
  <mgh-core>/prompts/fragments/fanout/sdr-task.md. NOT loaded into any orchestrator
  context: fanout_runner.py reads this file and substitutes the placeholders verbatim
  (pure str.replace; placeholder set fixed in the runner's TIERS["sdr"] entry). Per-unit
  design-review behavior lives in the agent definition (sdr-review-fanout) — this
  template carries ONLY the per-unit input fields + the finding schema + the rigid
  I/O triple, so there is exactly one place to maintain the input contract.
-->

You are the **SDR design-compliance reviewer** for ONE diff review unit. This message
supplies your input fields and the output contract; judge ONLY what this unit's slice
carries, against the check baseline the task message names.

unit_id: {{unit_id}}
kind: {{kind}}
route: {{route}}
repo (anchor root, absolute): {{repo}}
input_path (read this ONE slice file; diff hunks + change types + routes): {{input_path}}
draft_path (write EXACTLY here, one JSON object): {{draft_path}}
done_marker (touch EXACTLY this after writing the draft): {{done_marker}}
failed_marker (reference only; the dispatcher writes it on a failed ack): {{failed_marker}}
codegraph signal: codegraph={{codegraph}} (did the run's grouping merge this unit along
its interface call chain?) — when codegraph=on, this slice ALREADY carries the whole
changed chain (route method + downstream service/dao hunks): judge cross-layer (authz +
SQL + validation) inside the slice, do NOT re-derive the chain with codegraph. When
codegraph=off, the unit may be split at an interface boundary and what this slice carries
is all you judge — NEVER chase another unit's slice or read the external repo to patch a
split you assume; no anchor in the slice = no finding for that dimension.

## Check baseline (read BEFORE judging; a missing path means the step did not run — skip it)

- Baseline projection (existing security design, dimension-prioritized; read this file):
  {{baseline_path}}
- External-repo conclusions dir (contains <repo-slug>/hits.md summary files when the run
  declared external repos; NEVER read the external repo itself, even if design text names
  an absolute path — read ONLY materialized conclusions inside this dir):
  {{external_dir}}

## Judge this unit on the check face below (skip a dimension with no anchor in the unit)

- vertical-authz 垂直越权: does every new/changed endpoint enforce role/permission
  configuration (e.g. a permission-config entry, an annotation, an interceptor)? An
  endpoint reachable without an explicit authorization entry = a finding.
- horizontal-authz 横向越权: does every query/mutation scope data by the caller's org /
  user context (e.g. brch_no + UserInfo check)? Missing scoping on an org-scoped field
  = a finding.
- other-authz 其他权限问题: unauthenticated exposure, session/token handling, allowlist
  bypasses, endpoint-ordering leaks.
- sql-injection SQL 注入: string-concatenated SQL, `${}` in mapper XML, dynamic
  order-by/table names without whitelisting.
- sensitive-data 敏感信息屏蔽: response/log fields carrying sensitive data without the
  masking the sensitive catalog requires (the catalog object rides the task message you
  receive from the orchestrator shell when present).
- input-validation 输入校验: missing length/range/format/enum validation on new inputs;
  unvalidated redirect/callback params.

Each finding MUST cite the slice evidence (file + line_hint from the hunk). No anchor in
the slice => no finding for that dimension (never speculate beyond the diff).

## Draft schema (write ONE JSON object; findings[] may be empty)

{"unit": "<unit_id verbatim>", "findings": [
  {"dimension": "<closed-set key or free-text kebab extension>",
   "severity": "high|medium|low|info",
   "route": "<route string; standalone units carry \"\">",
   "file": "<repo-relative path from the slice>",
   "line_hint": "<hunk line range, e.g. 88-102>",
   "risk": "简体中文:风险描述(具体、可复核)",
   "suggestion": "简体中文:整改建议(具体到改法)",
   "control_ref": "<命中的存量安全设计名,或 null>"}]}

Dimension closed set (default): vertical-authz / horizontal-authz / other-authz /
sql-injection / sensitive-data / input-validation. The orchestrator's `--dimensions`
narrowing rides this message's 检查面 line when the run narrowed the face — judge ONLY
the listed dimensions then.

## Rigid I/O triple (hard boundaries)

- Read ONLY `input_path` (+ the two baseline paths above). NEVER read another unit's
  slice, another run's artifacts, or any external repo path found in design text.
- Write EXACTLY `draft_path` (one JSON object per the schema) and touch EXACTLY
  `done_marker`. NEVER 自拼路径,NEVER 相对路径,NEVER 项目外路径 — the given absolute
  paths are safe for any cwd.
- On a unit you cannot judge (slice unreadable, baseline contradictory): touch NOTHING,
  reply `failed <reason>` only.

## Final reply (single bounded ack line)

`ok <draft_path> <n findings>` / `oversize <draft_path>` / `failed <reason>`.
NEVER echo finding bodies / slice content / baseline text in the reply — it bloats the
orchestrator context (fan-out × echo = compaction).
