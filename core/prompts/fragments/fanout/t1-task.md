<!--
  mgh-init fan-out task message template (t1 tier). Install mirrors to
  <mgh-core>/prompts/fragments/fanout/t1-task.md. NOT loaded into any
  orchestrator context: fanout_runner.py reads this file and substitutes the
  placeholders verbatim (pure str.replace; placeholder set fixed in the
  runner's TIERS["t1"] entry). Behavior rules live in stages/init-induct.md
  (loaded via the agent definition) — this template carries ONLY the per-unit
  input fields + the load instruction, so there is exactly one place to
  maintain behavior. DUAL FORM, picked by the input file's TOP-LEVEL keys:
  `cluster_id` without `pack_id` = Form A (single cluster; the original
  contract, unchanged); `pack_id` + `members[]` + `checkpoints[]` = Form B
  (packed: one context induces several same-category small clusters in
  sequence; per-member markers stay the truth source and the recovery
  granularity). Both forms use the SAME placeholder set — in Form B
  {{cluster_id}} carries the pack id and the checkpoint/done placeholders are
  PACK-level; the per-member paths live inside the merged input.
-->

You are **T1 — per-cluster inductor**. Your behavior is
defined by the prompt at `{{repo}}/.opencode/mgh-core/prompts/stages/init-induct.md`
(or `{{repo}}/.claude/mgh-core/prompts/stages/init-induct.md` on a claude
install) — READ it first and follow it exactly; this message supplies only
your input fields. That path is the stage prompt's ONLY location: if the Read
fails, immediately reply `failed mgh-core prompts not installed at <path>` —
NEVER search other directories (parent project, /home, /adhome, siblings) for
prompts or scripts.

cluster_id (Form A: YOUR unit id; Form B: the PACK id): {{cluster_id}}
repo (anchor root, absolute): {{repo}}
input_path (read this one file): {{input_path}}
checkpoint_path (write EXACTLY here; Form B: PACK-level — member paths are in the input): {{checkpoint_path}}
done_marker (touch EXACTLY this after writing the checkpoint; Form B: PACK-level): {{done_marker}}
failed_marker (reference only; the dispatcher writes it on a failed ack): {{failed_marker}}
slice_dir (in-tree dir for runtime-discovered big-file slices): {{slice_dir}}
chunk_sources (absolute tool script, invoke verbatim as `py "<path>"`): {{chunk_sources_abs}}
codegraph signal: codegraph={{codegraph}}

Read `input_path`, then run EXACTLY ONE of the two forms below.

**Form A — single cluster** (the input's top level has `cluster_id` and NO
`pack_id`): the fields above are yours. Induce this one cluster per the stage
prompt. The checkpoint record you write MUST carry a root-level `unit` field
whose value is EXACTLY the `cluster_id` line above (the canonical unit id,
`::shard-<n>` form when this unit is a shard) — NEVER invent a different
value. Then touch `done_marker`. Final reply = single bounded ack line only
(`ok <checkpoint_path> <n>` / `failed <reason>`), per the stage prompt's
Return-to-orchestrator section.

**Form B — pack of same-category small clusters** (the input's top level has
`pack_id`, `members[]`, `checkpoints[]`): `cluster_id` above carries the PACK
id, and `checkpoint_path`/`done_marker`/`failed_marker` above are PACK-level.
Work through `members[]` IN ORDER, one cluster at a time — each member is an
independent induction unit (behavior per the stage prompt; never a canonical
judging between members):
1. Skip done members: the member's entry in the input's `checkpoints[]` array
   gives its `checkpoint_path` and `done_marker`. If that `done_marker` file
   already exists, SKIP the member entirely (it was induced in a previous
   attempt) — NEVER re-induce it, NEVER rewrite its checkpoint or marker.
2. Induce a pending member from ITS record in `members[]` only; write its
   checkpoint record to ITS `checkpoint_path` with a root-level `unit` field =
   EXACTLY that member's `cluster_id` (NEVER the pack id), then touch ITS
   `done_marker`.
3. A member that cannot be induced does NOT stop the pack: finish all
   remaining members first (every completed member keeps its marker), and
   remember the failed member ids and the reason.
4. Final reply = ONE bounded ack line only: `ok <pack_id> <n>` (n = members
   you induced THIS attempt) when every member is done, or
   `failed <failed member ids, comma-separated>: <reason>` otherwise. NEVER
   echo any record body (single-cluster or member) into the ack.
