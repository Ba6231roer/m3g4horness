## Why

`/mgh-init` is an exploratory, human-reviewed pipeline whose fan-out tiers (scout reader
batches, T1 per-cluster induction, T3 per-category rule writing) can number in the hundreds to
~1000 units. Today a unit that fails has no `.done` marker, so `resume_state.py` derives
`done < total` forever → **that tier never reaches completion and the whole pipeline blocks**
(or the orchestrator retries the same unit indiscriminately). A handful of failed units should
not stall an otherwise-complete 1000-unit run: `/mgh-init` tolerates losing a little data, as
long as the loss is **marked terminal, not retried on resume, and disclosed** in the manifest
and report.

The dependency that blocked this is now in place: `harden-mgh-init-context-resilience` shipped
`.done`-based re-entrant resume (`resume_state.py` + `run_config.json`), and the 9 stage prompts
already emit a bounded `failed <reason>` ack. What is missing is a **terminal failure marker
distinct from `.done`** and the resume/gating/disclosure logic that consumes it.

## What Changes

- Introduce a **`.failed` marker** sibling to `.done` (`<checkpoint_path>.failed`) as the
  terminal-state signal for a fan-out unit that failed confirmed (subagent returned the existing
  `failed <reason>` ack). Crashes with no ack leave no marker → unit stays pending → retried on
  resume (crash ≠ confirmed failure).
- `list_clusters.py` / `list_scout_batches.py` / `list_rule_jobs.py`: collect `.failed` ids
  (parallel to `_done_ids`), **exclude them from `pending`** (terminal, not retried), and emit a
  `failed` count + a `failed_marker` absolute path per pending item (parallel to `done_marker`,
  so the orchestrator never self-assembles a path).
- `resume_state.py`: a tier is **"complete enough to proceed" when `done + failed >= total`**
  (not `done >= total`); `tiers{}` gains a `failed` field per tier; failures surface in `notes[]`.
  `--check` flags a unit carrying **both** `.done` and `.failed` as an ambiguous-terminal
  self-consistency violation (exit 2).
- Orchestrator (`mgh-init.md`, dual shells): on a `failed` ack → write the `failed_marker`
  (`{unit, reason, tier}`), do **not** retry that unit, do **not** block; continue the wave. After
  the tier, disclose failure count/rate in `init_manifest.json` (new `failures` counts + a
  `boundaries[]` line) and `report.md`, with counts **read from disk via `resume_state.py` /
  `list_*` stdout** (NEVER agent memory).
- No hard failure-rate abort (the pipeline is exploratory/human-reviewed; disclose, don't block).
  A high rate is surfaced as a loud advisory note, not a gate. **No new CLI flag** (R5.1 surface
  frozen; `.failed` is read by glob, written by the orchestrator via `Write` to a path it reads
  verbatim from `list_*` stdout).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `control-discovery`: add a requirement that fan-out unit failures are **tolerated as terminal
  non-blocking state** — a failed unit is marked `.failed` (distinct from `.done`), excluded from
  resume `pending`, counted toward tier completion (`done + failed >= total`), and disclosed in
  `init_manifest.json` + `report.md`. Today's behavior (no `.done` ⇒ tier never completes ⇒
  pipeline blocks, or indiscriminate retry) becomes the failure-shape being fixed.

## Impact

- **Deterministic scripts** (`core/scripts/`): `list_clusters.py`, `list_scout_batches.py`,
  `list_rule_jobs.py` (`.failed` id collection, `pending` exclusion, `failed` count,
  `failed_marker` field); `resume_state.py` (tier gating `done+failed>=total`, `tiers.failed`,
  `notes` disclosure, `--check` both-marker violation).
- **Contracts** (`core/contracts/init/`): `clusters.md`, `scout`/`rule-jobs` pending-item
  contracts, `resume-state.md` (gating truth table + `tiers.failed`), `manifest.md`
  (`failures` counts + boundary disclosure).
- **Orchestrator shells** (`releases/{claude-code/commands,opencode/command}/mgh-init.md`):
  fan-out `failed`-ack recipe + manifest/report disclosure + re-entrancy note that `.failed` is
  terminal on resume.
- **Stage prompts** (`core/prompts/stages/init-{induct,scout,rulewriter}.md`): minor — on failure,
  emit the existing `failed` ack and touch nothing (the orchestrator records `.failed`).
- **Tests** (`tests/`): `.failed` excluded from `pending`; `done+failed>=total` gates the tier;
  resume does not retry `.failed`; `--check` flags both-marker ambiguity.
- **Runtime hook**: unaffected — `.failed` is a data marker under the trusted `.mgh-init/`
  subtree, not a script extension; `MGH_TARGET` subtree check and `block_adhoc_scripts` unchanged.
- `VERSION` bump; `tools/check_distributed_purity.py` + `tools/check_contracts.py` unchanged
  (no new CLI flag, no dev-only prose introduced).
