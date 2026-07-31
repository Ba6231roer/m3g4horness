## Context

`/mgh-init` fan-out tiers (scout reader batches, T1 per-cluster induction, T3 per-category rule
writing) are isolated per-unit and can number in the hundreds to ~1000. Each unit is driven off a
deterministic `list_*` work-list at `max_concurrent` waves until `pending` is empty; scale and
boundary facts are already disclosable via `init_manifest.json::boundaries[]`, `report.md`, and
`resume_state.py` `notes[]`, with counts read from disk.

The gap is the host agent's **conversational behavior**: at large fan-out scale it sometimes stops
mid-wave to ask the user whether to split / skip / abort, interrupting a run the user expects to run
to completion. The runtime hook cannot govern this — it intercepts tool calls (`Write`/`Bash`/`Edit`),
not whether the agent pauses to ask. So the fix is an orchestrator prompt directive, not a hook or
script.

Constraints: R2 (zero runtime deps), R5.1 (CLI `--help` is the contract; no new flags), R5.5
(normative verbs, recipes over prohibitions except hard boundaries), R5.6 (shell token budget), R5.7
(dual-shell parity), R5.10 (distributed artifacts carry no dev-only prose).

## Goals / Non-Goals

**Goals:**
- A run-to-completion directive in both `/mgh-init` shells: during a fan-out wave, MUST NOT pause to
  ask the user about split / skip / abort on account of scale; MUST drive the wave to completion.
- Scale + boundary facts flow into the **existing** disclosure channel (manifest `boundaries[]` /
  `report.md` / `resume_state.py` `notes[]`), never as a mid-run blocking question.
- Make the **pre-run vs mid-run** distinction explicit so the legitimate pre-token
  `--scope`+`--merge` advisory is preserved.

**Non-Goals:**
- No new CLI flag, no deterministic-script change, no contract schema change, no runtime-hook change,
  no stage-prompt change (the directive governs the host agent, not subagents).
- No removal of the pre-run `--large-repo-threshold` advisory (it fires before tokens are spent).
- No hard failure-rate abort or retry policy — those belong to
  `improve-mgh-init-partial-fanout-tolerance` (`.failed` markers), a separate change.

## Decisions

**D1 — Scope = orchestrator command-shell prompt only (non-hook, non-script).** The gap is
conversational (stopping to ask), which no tool-call hook can govern. The fix is one directive line
in `mgh-init.md` (both shells). *Alt — fold into `harden-mgh-init-context-resilience` (issue option
(a))*: rejected — that change is **archived / applied**, so it cannot be merged into; a standalone
change can target the same "Re-entrancy & compaction" section, so (a)'s content placement is
preserved without reopening a closed change (issue option (b)). *Alt — a runtime hook*: rejected;
hooks intercept tool calls, not conversational pauses.

**D2 — Mid-run interruption forbidden; pre-run advisory preserved.** Two scale-handling moments are
distinct: (1) **pre-token** i0 advisory (`--large-repo-threshold` → suggest `--scope`+`--merge`) is
legitimate R5.4 practice ("扫描前廉价计数 + 命中阈值前置建议,取代「跑满再超时」") and **stays**;
(2) **post-commit / mid-wave** pausing to ask split / skip / abort is what the directive forbids.
*Why not also kill (1)*: the pre-run advisory prevents the "跑满再超时" failure mode at zero token
cost; removing it regresses R5.4. The reported phenomenon is mid-run interruption, not pre-run advice.

**D3 — Disclosure channel = existing artifacts, no new field.** Scale + boundaries flow into the
already-present `init_manifest.json::boundaries[]` + `report.md` + `resume_state.py` `notes[]`. No
new contract field, no schema change. Counts read from disk (`resume_state.py` / `list_*` stdout),
never agent memory — consistent with the disk-truth discipline. *Alt — a dedicated "scale advisory"
field*: rejected (YAGNI + R5.6 token budget + R3 concision; `boundaries[]` is the established sink).

**D4 — One recipe line, not a section (R5.6 / R3).** The directive is a short normative line in the
fan-out / Re-entrancy & compaction area, not a new verbose section. Wording uses RFC-2119 verbs
(`MUST NOT` / `SHALL`) per R5.5③; no long code block (R3). This keeps the shell within its token
budget while making the boundary machine-recognizable for the spec scenario.

**D5 — Dual-shell verbatim mirror; no CLI flag.** Both `releases/claude-code/commands/mgh-init.md`
and `releases/opencode/command/mgh-init.md` get the identical directive (R5.7 parity). No new CLI
flag ⇒ `tools/check_contracts.py` unaffected (R5.1).

## Risks / Trade-offs

- **The directive is non-deterministic (prompt wording)** → a hook cannot enforce "don't ask."
  Mitigation: normative `MUST NOT` wording + a spec scenario pinning **disclosure as the only
  scale-handling channel** (the disclosure side IS deterministic and testable via
  `init_manifest.json` / `report.md` / `resume_state.py`). The "no interrupt" side is prompt-guarded,
  consistent with how other orchestrator-behavior rules in the shell are enforced.
- **Apparent conflict with the pre-run advisory** → mitigated by D2's explicit pre-token vs
  post-commit split; the directive scopes only post-commit mid-wave behavior.
- **Token cost** → negligible: one recipe line per shell (respects R5.6 / R3).

## Migration Plan

- **Additive**: a one-line prompt edit per shell; no data migration, no schema change, no flag.
  Old behavior (occasional mid-run question) is simply removed.
- **Rollback**: revert the directive line in both shells; no artifact impact.
- `VERSION` bump; `tools/check_contracts.py` unaffected (no new flag);
  `tools/check_distributed_purity.py` must still pass (operational prose only, no dev-only refs).

## Open Questions

- **Q1**: should the directive also mandate scale/boundary disclosure at *small* scale? **Recommend
  NO** — keep scoped to "scale ⇒ no interrupt + disclose"; small-scale disclosure is already governed
  by the existing "Disclose honesty boundaries" / scout-coverage / codegraph-coverage requirements.
- **Q2**: should the pre-run `--large-repo-threshold` advisory be weakened so the agent never raises
  scale at all? **Recommend NO** (D2) — it is a zero-cost pre-token gate that prevents the
  "跑满再超时" failure mode; the user's concern is mid-run interruption, not pre-run advice.
