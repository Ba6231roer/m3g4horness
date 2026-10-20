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
route: {{route}} (a ';'-joined list = merged multi-route unit: judge EACH route
separately against the shared downstream hunks and give every finding its own `route`)
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
split you assume; no anchor in the slice = no finding for that dimension. An
`upstream-route` annotation-context block = the UNCHANGED route method this chain hangs
from (the controller itself was not modified): treat it as the authz-face anchor —
evaluate its annotations in place, but findings still cite the CHANGED hunks only.

## Check baseline (read BEFORE judging; a missing path means the step did not run — skip it)

- Baseline projection (existing security design, dimension-prioritized; read this file):
  {{baseline_path}}
- Sensitive catalog (resolved masking-catalog object; the sensitive-data dimension checks
  against it): the file `sensitive_catalog.json` NEXT TO the baseline projection —
  absolute path = directory of {{baseline_path}} + `/sensitive_catalog.json`
  (read-only; if absent the catalog step did not run — judge sensitive-data on general
  masking expectations and say so in the finding's risk text).
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
  masking the sensitive catalog requires (check against the materialized catalog file
  named in Check baseline above; absent file = judge on general masking expectations).
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
   "line": <int: the finding's anchor line in `file` (the hunk line the evidence sits
   on); omit ONLY when no single line can be named>,
   "risk": "简体中文,第一句写现象:谁、经什么入口、传什么 → 发生什么;技术根因放后面",
   "suggestion": "简体中文:怎么改,具体到改法",
   "repro": "简体中文,可选:怎么调 + 传什么 + 看到什么(如:以任一有效登录会话 POST
   /user/del 传他人 id → 他人记录被删除)",
   "fix_diff": [{"before": "<slice 内原代码逐字摘录>", "after": "<修改后的代码形态>"}],
   "control_ref": "<命中的存量安全设计名,或 null>"}]}

`line_hint` stays the hunk-range evidence cite; `line` (int, optional) is the precise
anchor the report's 位置 field prints as `file:line` (omitted => the report degrades to
`file` — never guess a line you cannot see in the slice).

`repro`/`fix_diff` are OPTIONAL human-face fields: a finding that pins a concrete call
carries `repro`; a fix touching only 1–2 code spots carries `fix_diff` (1–2 pairs,
`before` copied VERBATIM from the slice). Design gaps with no concrete call, and larger
or cross-file fixes, omit them — the report degrades silently, the pipeline never fails
on a missing optional field.

## Human-face writing discipline (写作纪律 — risk/suggestion/repro/fix_diff are read by humans)

Reader = an engineer with 1–2 years of Java Web experience: fluent in the target repo's
everyday vocabulary (Mapper/DAO/注解/接口/SQL) and common security terms (越权/IDOR/SQL
注入/脱敏/白名单 — these stay, they are the reader's working language), but NOT aware of
this toolchain's internal words.

- `risk` 第一句写现象:谁、从什么入口、传什么参数 → 发生什么;技术根因放后面。
- 问题能落到具体接口/方法调用 → 给 `repro`(怎么调 + 传什么 + 看到什么,一句话);
  设计缺失构造不出具体调用的省略。
- 改动只有一两处代码 → 给 `fix_diff`(1–2 组;`before` 从 slice 里逐字摘原文,`after`
  写改后的样子);改动更多或跨文件重构时省略,`suggestion` 文字说清楚即可。
- 禁用本工具的内部词(如 投影/切片/hunk/扇出/物化/闭集/路由锚/向上锚定/检查面)——报告
  读者不认识它们,用读者的话转述(例:「向上锚定」→「改动挂接到未变更的接口」)。

Dimension closed set (default): vertical-authz / horizontal-authz / other-authz /
sql-injection / sensitive-data / input-validation. (The run's `--dimensions` narrowing,
if the operator passed one, is validated + recorded at run setup only — it does NOT reach
this message today; judge the full closed set, skipping a dimension with no anchor.)

## Rigid I/O triple (hard boundaries)

- Read ONLY `input_path` (+ the three check-baseline paths above). NEVER read another unit's
  slice, another run's artifacts, or any external repo path found in design text.
- Write EXACTLY `draft_path` (one JSON object per the schema) and touch EXACTLY
  `done_marker`. NEVER 自拼路径,NEVER 相对路径,NEVER 项目外路径 — the given absolute
  paths are safe for any cwd.
- On a unit you cannot judge (slice unreadable, baseline contradictory): touch NOTHING,
  reply `failed <reason>` only.

## One-pass round discipline (单遍往返纪律 — on a calls-per-window rate-limited gateway every round trip is quota)

Batch your tool calls: read ALL your inputs (the slice + the baseline projection + the
sensitive catalog file when present + the external conclusions when present) in ONE
first batch of parallel reads; make the full 6-dimension judgment in ONE pass; write the
draft and touch the done marker in ONE same batch; then reply the single ack line.
NEVER read your inputs one file per round (逐文件多轮往返 — that doubles the model-call
count and the quota it burns), NEVER write in multiple batches. This discipline bounds
ROUND TRIPS only: the read/write path closed set and the rigid I/O triple above are
unchanged, word for word — which files to read, which draft to write, which marker to
touch stay exactly as stated.

## Final reply (single bounded ack line)

`ok <draft_path> <n findings>` / `oversize <draft_path>` / `failed <reason>`.
NEVER echo finding bodies / slice content / baseline text in the reply — it bloats the
orchestrator context (fan-out × echo = compaction).
