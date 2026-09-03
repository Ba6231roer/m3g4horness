<!--
  mgh-init fan-out task message template (t1 tier). Install mirrors to
  <mgh-core>/prompts/fragments/fanout/t1-task.md. NOT loaded into any
  orchestrator context: fanout_runner.py reads this file and substitutes the
  placeholders verbatim (pure str.replace; placeholder set fixed in the
  runner's TIERS["t1"] entry). Behavior rules live in stages/init-induct.md
  (loaded via the agent definition) — this template carries ONLY the per-unit
  input fields + the load instruction, so there is exactly one place to
  maintain behavior.
-->

You are **T1 — per-cluster inductor** for ONE cluster unit. Your behavior is
defined by the prompt at `{{repo}}/.opencode/mgh-core/prompts/stages/init-induct.md`
(or `{{repo}}/.claude/mgh-core/prompts/stages/init-induct.md` on a claude
install) — READ it first and follow it exactly; this message supplies only
your input fields.

cluster_id: {{cluster_id}}
repo (anchor root, absolute): {{repo}}
input_path (read this one file; carries the cluster record + candidate hits): {{input_path}}
checkpoint_path (write EXACTLY here): {{checkpoint_path}}
done_marker (touch EXACTLY this after writing the checkpoint): {{done_marker}}
failed_marker (reference only; the dispatcher writes it on a failed ack): {{failed_marker}}
slice_dir (in-tree dir for runtime-discovered big-file slices): {{slice_dir}}
chunk_sources (absolute tool script, invoke verbatim as `py "<path>"`): {{chunk_sources_abs}}
codegraph signal: codegraph={{codegraph}}

The checkpoint record you write MUST carry a root-level `unit` field whose value is
EXACTLY the `cluster_id` line above (the canonical unit id, `::shard-<n>` form when
this unit is a shard) — identity double-cover so the record is self-describing.
NEVER invent a different value.

Final reply = single bounded ack line only (`ok <checkpoint_path> <n>` /
`failed <reason>`), per the stage prompt's Return-to-orchestrator section.
