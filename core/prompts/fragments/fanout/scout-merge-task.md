<!--
  mgh-init fan-out task message template (scout-merge tier — S4 scout candidate
  merge MAP stage). Install mirrors to
  <mgh-core>/prompts/fragments/fanout/scout-merge-task.md. NOT loaded into any
  orchestrator context: fanout_runner.py reads this file and substitutes the
  placeholders verbatim (pure str.replace; placeholder set fixed in the runner's
  TIERS["scout-merge"] entry). Behavior rules live in
  stages/init-scout-merge-partial.md (loaded via the agent definition) — this
  template carries ONLY the per-unit input fields + the load instruction, so
  there is exactly one place to maintain behavior. The dispatcher drives the
  MAP stage only; the ROLLUP is a separate orchestrator step.
-->

You are **S4 — per-shard partial scout merge** for ONE shard of the scout batch
aggregate. Your behavior is defined by the prompt at
`{{mgh_core}}/prompts/stages/init-scout-merge-partial.md` — READ it first and
follow it exactly; this message supplies
only your input fields. That path is the stage prompt's ONLY location: if the
Read fails, immediately reply `failed mgh-core prompts not installed at <path>`
— NEVER search other directories (parent project, /home, /adhome, siblings) for
prompts or scripts.

shard_id: {{shard_id}}
batches (batch_ids this shard covers; also declared in the
input file): {{batches}}
repo (anchor root, absolute): {{repo}}
input_path (read this one file; carries this shard's bounded scout candidate
records): {{input_path}}
checkpoint_path (write your structured shard summary exactly here):
{{checkpoint_path}}
done_marker (touch EXACTLY this after writing the summary): {{done_marker}}
failed_marker (reference only; the dispatcher writes it on a failed ack):
{{failed_marker}}

Final reply = single bounded ack line only (`ok <checkpoint_path> <n>` /
`failed <reason>`), per the stage prompt's Return-to-orchestrator section.
