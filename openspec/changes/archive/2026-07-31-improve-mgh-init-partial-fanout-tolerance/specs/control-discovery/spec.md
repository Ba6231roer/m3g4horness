## ADDED Requirements

### Requirement: Partial fan-out unit failure tolerance

A confirmed `/mgh-init` fan-out unit failure SHALL be treated as a terminal, non-blocking state distinct from completion. This covers the scout-reader batch, T1 per-cluster induction, and T3 per-category rule-writing tiers: when a unit's subagent returns the existing `failed <reason>` ack, the orchestrator SHALL record it with a `.failed` marker sibling to its `.done` marker (`<checkpoint_path>.failed`); the unit SHALL NOT be retried on `--resume` and SHALL NOT block tier completion. A tier SHALL be considered complete enough to proceed when `done + failed >= total` (not `done >= total`).

The orchestrator (host agent) SHALL write the `.failed` marker on receiving a `failed` ack — the
subagent touches nothing on failure (it only emits the ack). A unit whose subagent crashed
without producing any ack SHALL leave neither `.done` nor `.failed` and SHALL remain pending
(crash is not a confirmed terminal failure).

The `list_clusters.py`, `list_scout_batches.py`, and `list_rule_jobs.py` work-list producers
SHALL exclude `.failed` units from `pending[]`, SHALL emit a `failed` count in stdout, and SHALL
emit a `failed_marker` absolute path per pending item (parallel to `done_marker`). `resume_state.py`
SHALL derive each tier's `failed` count from `.failed` markers, gate tier completion on
`done + failed >= total`, surface non-zero failures in `notes[]`, and flag a unit carrying both
`.done` and `.failed` as a `--check` self-consistency violation (exit 2).

#### Scenario: A failed unit is marked terminal and excluded from pending

- **WHEN** a T1 cluster subagent returns `failed evidence parse error` for cluster `authZ::shard-0`
  and the orchestrator writes its `failed_marker` (`checkpoints/t1/<safe(authZ::shard-0)>.json.failed`)
- **THEN** the next `list_clusters.py --checkpoints <t1-dir>` run does NOT list that unit in
  `pending[]`, and its stdout `failed` count is incremented

#### Scenario: A tier proceeds when done plus failed reaches total

- **WHEN** a tier has `total=1000` units, of which 997 are `.done` and 3 are `.failed`
- **THEN** `resume_state.py` reports `step` past that tier (it does not gate on `done < total`),
  `tiers[<tier>].failed == 3`, and the pipeline proceeds to the next stage

#### Scenario: Resume does not retry a failed unit

- **WHEN** the pipeline is re-entered with `mgh-init --resume` after a unit was marked `.failed`
- **THEN** `resume_state.py` does not surface that unit in `next_action` / `pending`, and the
  orchestrator does not re-dispatch it

#### Scenario: A crash is not a confirmed failure and is retried

- **WHEN** a subagent crashes mid-unit leaving neither `.done` nor `.failed`
- **THEN** the unit remains `pending` and `resume_state.py` re-dispatches it on the next resume

#### Scenario: Both done and failed for one unit is a check violation

- **WHEN** a unit carries both `<checkpoint_path>.done` and `<checkpoint_path>.failed`
- **THEN** `resume_state.py --check` reports the ambiguous terminal state and exits 2

#### Scenario: A failed unit with no checkpoint record body is not a violation

- **WHEN** a `.failed` marker exists but its sibling checkpoint record `<id>.json` is absent
  (the subagent failed before writing the record)
- **THEN** `resume_state.py --check` does not flag it (absent record is expected for failures)

### Requirement: Fan-out failures are disclosed in artifacts

The orchestrator SHALL disclose fan-out unit failures in `init_manifest.json` and `report.md`.
The `failures` counts SHALL be read from disk via `resume_state.py` stdout `tiers` or `list_*`
stdout `failed` fields — NEVER from agent conversation memory. The `list_*` producers and
`resume_state.py` SHALL expose failure counts as structured output fields.

#### Scenario: Work-list producers expose failed count and failed_marker path

- **WHEN** the orchestrator runs `list_clusters.py` / `list_scout_batches.py` / `list_rule_jobs.py`
  over a checkpoint dir containing `.failed` markers
- **THEN** stdout carries a `failed` integer count, and each `pending[]` item carries an absolute
  `failed_marker` path parallel to its `done_marker`

#### Scenario: resume_state reports failed per tier

- **WHEN** a tier has any `.failed` units
- **THEN** `resume_state.py` stdout `tiers[<tier>]` includes a `failed` count, and `notes[]`
  contains a disclosure entry naming the tier, the failed count, and the total

#### Scenario: The manifest and report disclose the failure rate

- **WHEN** the orchestrator finalizes `init_manifest.json` and `report.md` after a tier with
  `failed > 0`
- **THEN** `init_manifest.json` carries a `failures` object (per-tier `{done,failed,total}` or
  equivalent) and a `boundaries[]` entry disclosing that fan-out units failed and were skipped,
  and `report.md` surfaces the same fact in its disclosure section

#### Scenario: High failure rate produces a loud advisory

- **WHEN** a tier's failed count exceeds half its total
- **THEN** `resume_state.py` `notes[]` elevates the disclosure to a prominent advisory (the run
  still proceeds; this is not a gate)
