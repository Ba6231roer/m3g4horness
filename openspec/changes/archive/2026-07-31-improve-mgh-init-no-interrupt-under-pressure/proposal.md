## Why

`/mgh-init` is an exploratory, human-reviewed pipeline whose fan-out tiers (scout reader batches,
T1 per-cluster induction, T3 per-category rule writing) can number in the hundreds to ~1000 units.
At that scale the orchestrator (host agent) sometimes **pauses mid-wave to ask the user** whether to
split / skip / abort, temporarily interrupting a run the user expects to run comprehensively to
completion. The user wants stable, full execution — with scale and boundary facts surfaced in the
run summary, **not** as blocking questions that stall the wave.

This is an **orchestrator prompt / conversational-behavior** gap, not a hook gap: the runtime hook
intercepts tool calls (`Write`/`Bash`/`Edit`); it cannot govern whether the agent *stops to ask the
user*. The disclosure channel it should use instead already exists
(`init_manifest.json::boundaries[]` + `report.md` + `resume_state.py` `notes[]`).

## What Changes

- Add a **run-to-completion orchestration directive** to both `/mgh-init` command shells
  (`releases/claude-code/commands/mgh-init.md` + `releases/opencode/command/mgh-init.md`, mirrored
  verbatim): during a fan-out wave (scout / T1 / T3), the orchestrator **MUST NOT** pause to ask the
  user whether to split / skip / abort on account of scale; it **MUST** drive each wave to completion
  (iterate the `list_*` pending work-list at `max_concurrent` until no pending units remain).
- Scale + boundary facts (large fan-out count, partial scout coverage, any `.failed` / skipped units,
  residual blind spots) **SHALL** flow into the **existing disclosure channel** —
  `init_manifest.json::boundaries[]` + `report.md` + `resume_state.py` `notes[]` — **NEVER** as a
  mid-run blocking user question. Counts are read from disk (`resume_state.py` / `list_*` stdout),
  never from agent memory.
- **Preserve** the legitimate **pre-run** advisory: the existing i0 `--large-repo-threshold` →
  suggest `--scope` + `--merge` happens **before tokens are spent** and stays unchanged. The new
  directive forbids interruption only **after** a run is committed (mid-wave). The distinction
  (pre-token advisory vs mid-run execution) is made explicit in the shell.
- **Prompt-wording only**: no new CLI flag (R5.1 surface frozen), no deterministic-script change, no
  runtime-hook change, no contract schema change, no stage-prompt change. The disclosure fields and
  fan-out enumeration primitives it leans on already exist.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `control-discovery`: add a requirement that `/mgh-init` fan-out waves **run to completion without
  scale-driven user interruption** — scale and boundary facts are disclosed via existing artifacts
  (`init_manifest.json` / `report.md` / `resume_state.py` `notes[]`), never as a blocking question
  mid-run. The legitimate pre-run `--scope`+`--merge` advisory is explicitly out of scope (it fires
  before tokens are spent).

## Impact

- **Orchestrator shells** (`releases/{claude-code/commands,opencode/command}/mgh-init.md`): one short
  recipe line in the fan-out / Re-entrancy & compaction area of each shell, mirrored verbatim
  (respects R5.6 token budget / R3 concision — a directive, not a section).
- **No deterministic scripts** (`core/scripts/`): untouched — no new flag, no I/O contract change
  (`tools/check_contracts.py` unaffected).
- **No contracts** (`core/contracts/init/`): the disclosure fields consumed already exist; no schema
  change.
- **No runtime hook / stage prompts**: the directive governs host-agent conversational behavior; the
  hook and subagent prompts are unchanged.
- `VERSION` bump; `tools/check_distributed_purity.py` must still pass (operational prose only, no
  dev-only refs per R5.10).
