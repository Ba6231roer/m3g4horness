## Context

`/mgh-init` fan-out tiers — scout reader batches, T1 per-cluster induction, T3 per-category rule
writing — are isolated per-unit and can number in the hundreds to ~1000. Each unit has a
checkpoint record (`<id>.json`) + a `.done` marker (`<checkpoint_path>.done`); `--resume` skips
units whose `.done` exists. The stage prompts (from `harden-mgh-init-context-resilience`) already
emit a bounded `failed <reason>` ack on failure, and `resume_state.py` re-derives progress purely
from disk (`done_count < total` gates each tier).

The gap: a failed unit has **no `.done`**, so `resume_state.py` derives `done < total` indefinitely
→ the tier never completes → the pipeline blocks at that tier (or the orchestrator retries the
same unit indiscriminately). For an exploratory, human-reviewed pipeline, a few failed units
among ~1000 should not stall the whole run.

Constraints: R2 (zero runtime deps), R5.1 (CLI `--help` is the contract; no new flags unless
mirrored in both shells), R5.3 (scripts self-contained, stdout JSON / stderr diagnostics), R5.9
(`--check` boundary validation), R5.10 (distributed artifacts carry no dev-only prose).

## Goals / Non-Goals

**Goals:**
- A terminal failure marker `.failed` distinct from `.done`, so a confirmed failure is not
  retried and does not block.
- Tier completion gate becomes `done + failed >= total`.
- Failures disclosed in `init_manifest.json` + `report.md`, with counts read from disk
  (`resume_state.py` / `list_*` stdout), never from agent memory.
- `--check` catches ambiguous terminal state (both `.done` and `.failed` for one unit).

**Non-Goals:**
- No hard failure-rate abort (disclose, don't block; the pipeline is human-reviewed).
- No retry/backoff policy — failure is terminal. Escape hatch = user deletes the `.failed`
  marker (documented), then `--resume` retries it.
- T2 / scout-merge **aggregation** failures (whole-tier single-context or rollup) are a
  different problem and out of scope.
- `improve-mgh-init-no-interrupt-under-pressure` (scale ⇒ run to completion, don't ask) and
  `improve-mgh-init-deterministic-step-manifest` are separate changes.

## Decisions

**D1 — `.failed` marker is a sibling of `.done`.** `<checkpoint_path>.failed` (parallel to
`done_marker = <checkpoint_path>.done`). The marker file carries a tiny body
`{"unit":"<id>","reason":"<short>","tier":"<scout|t1|t3>"}` so disclosure can group by tier and a
human can drill into the reason; marker **existence** is the terminal signal (body is advisory).
`list_*` pending items gain a `failed_marker` absolute path (parallel to `done_marker`) so the
orchestrator never self-assembles a path (R5.3b).
*Why sibling not a subdir*: byte-identical to the `.done` discovery pattern (`_done_ids` globs
`*.json.done` → add `_failed_ids` globbing `*.json.failed`); zero new path topology.

**D2 — The orchestrator writes `.failed`; the subagent only emits the ack.** On receiving a
`failed <reason>` ack, the orchestrator writes the unit's `failed_marker` and moves on. The
subagent's failure path touches nothing (it already emits the ack).
*Alt (b) — subagent touches a `failed_marker`*: rejected; a failure path is often a crash/timeout
that cannot reliably touch a marker, and it threads another field through 9 stage prompts.
*Alt (c) — a `mark_failed.py` leaf script*: rejected; overkill for "write one marker," and it
adds CLI surface that `tools/check_contracts.py` must mirror across both shells.
*Crash semantics*: a unit whose subagent crashed with **no ack** leaves no `.failed` and no
`.done` ⇒ stays `pending` ⇒ retried on resume. This is correct: crash ≠ confirmed terminal
failure. Only an explicit `failed` ack becomes terminal.

**D3 — Tier gate is `done + failed >= total`.** `resume_state.py` currently gates t1/t3/scout on
`done_count < total`. New rule: gate on `(done_count + failed_count) < total`. `tiers{}` gains a
`failed` field per tier (`{done, failed, total}`). Scout reader batches use the same treatment
(`_scout_batch_done_count` ⇒ `_scout_batch_terminal_count = done + failed`); scout-merge proceeds
over the successful batches.

**D4 — No hard failure-rate gate; disclose + advisory only.** The pipeline is exploratory and
human-reviewed; "allow individual failures, lose a little data" is the explicit intent. So no
abort threshold and **no new CLI flag** (R5.1 frozen). A high rate (e.g. failed > 50% of a tier)
surfaces as a **loud `notes[]`** entry from `resume_state.py` + a prominent `boundaries[]` line,
not a gate.

**D5 — `--check` flags both-marker ambiguity.** A unit carrying **both** `.done` and `.failed`
is an ambiguous terminal state (e.g. subagent acked `failed` but had already touched `.done`
before crashing) ⇒ `resume_state.py --check` reports it and exits 2 (R5.9). A `.failed` marker
whose sibling record is absent is **not** a violation (failure may produce no record body).

**D6 — Disclosure is disk-grounded.** The orchestrator writes `init_manifest.json::failures`
(per-tier `{done,failed,total}`) + a `boundaries[]` line and a `report.md` line, with the counts
**read from `resume_state.py` stdout `tiers` / `list_*` stdout `failed`** — never agent memory.
This mirrors how `dotfiles_skipped` / `oversize` / `shrunk` are already disclosed.

**D7 — `.failed` read by glob, not a new data structure.** `_failed_ids()` mirrors `_done_ids()`
(reads `*.json.failed`, derives the unit id from the sibling record's `unit` field, filename-stem
fallback). Rule jobs use `*.<fmt>.json.failed` (parallel to `*.<fmt>.json.done`).

## Risks / Trade-offs

- **Silent mass loss if many units fail** → mitigation: per-tier `failed` counts in manifest +
  report, a loud `notes[]` advisory at high rate, and per-unit `.failed` bodies for drill-down.
  The human reviews the manifest before trusting the inventory.
- **Orchestrator forgets to write `.failed` on a `failed` ack** → the unit stays `pending` ⇒
  retried on next resume. This is a **safe degradation** (extra retry, not silent loss); the
  recipe + a spec scenario pin the behavior.
- **Both-marker race** (`.done` and `.failed` coexist) → `--check` flags it (D5).
- **Reduced scout coverage** when reader batches fail → disclosed via `scout.failures` + the
  existing "scout coverage is partial" boundary (scout was already partial/non-deterministic).
- **Token cost** is negligible: one new field per `list_*` pending item + one `failed` count; no
  new prompt section in the command shell beyond a short recipe line (respects R5.6 / R3).

## Migration Plan

- **Additive**: old runs without `.failed` markers behave identically (`failed` count 0,
  `done+failed>=total` reduces to `done>=total`). No data migration.
- **Rollback**: revert scripts/prompts; leftover `.failed` files become inert orphans. (If code
  reverts to done-only, an orphan `.failed` is neither done nor failed ⇒ unit becomes pending
  again ⇒ retried — safe, not lossy.)
- `VERSION` bump; `tools/check_contracts.py` unaffected (no new CLI flag);
  `tools/check_distributed_purity.py` must still pass (operational prose only, no dev-only refs).

## Open Questions

- **Q1**: add an optional `--max-failure-rate` abort flag? **Recommend NO** — YAGNI + R5.1
  surface freeze; disclose-only is sufficient for a human-reviewed pipeline. Revisit if a run
  ever loses >50% silently.
- **Q2**: `.failed` body shape — keep minimal `{"unit","reason","tier"}`, or add a retry hint?
  **Recommend minimal**; the human decides retry by deleting the marker.
- **Q3**: disclosure granularity — per-tier counts vs per-unit listing in the report? **Recommend
  per-tier counts in manifest/report** + per-unit `.failed` bodies on disk for drill-down (keep
  `report.md` brief per R3).
