<!--
  mgh-init fan-out task message template (t2 tier — T2 synthesis MAP stage).
  Install mirrors to <mgh-core>/prompts/fragments/fanout/t2-task.md. NOT loaded
  into any orchestrator context: fanout_runner.py reads this file and
  substitutes the placeholders verbatim (pure str.replace; placeholder set fixed
  in the runner's TIERS["t2"] entry). Behavior rules live in
  stages/init-synthesis-partial.md (loaded via the agent definition) — this
  template carries ONLY the per-unit input fields + the load instruction, so
  there is exactly one place to maintain behavior. The dispatcher drives the
  MAP stage only; the ROLLUP is a separate orchestrator step.
-->

You are **T2 — per-shard partial synthesis** for ONE shard of the T1 record
aggregate. Your behavior is defined by the prompt at
`{{mgh_core}}/prompts/stages/init-synthesis-partial.md` — READ it first and
follow it exactly; this message supplies
only your input fields. That path is the stage prompt's ONLY location: if the
Read fails, immediately reply `failed mgh-core prompts not installed at <path>`
— NEVER search other directories (parent project, /home, /adhome, siblings) for
prompts or scripts.

shard_id: {{shard_id}}
categories (this shard covers exactly these T1 categories; also declared in the
input file): {{categories}}
repo (anchor root, absolute): {{repo}}
input_path (read this one file; carries this shard's bounded T1 records):
{{input_path}}
checkpoint_path (write your structured shard summary EXACTLY here):
{{checkpoint_path}}
done_marker (touch EXACTLY this after writing the summary): {{done_marker}}
failed_marker (reference only; the dispatcher writes it on a failed ack):
{{failed_marker}}

After writing the summary checkpoint, validate its JSON syntax READ-ONLY: run
`py -m json.tool <checkpoint_path>` (discard stdout). A non-zero exit means
the record is malformed — treat THIS unit as failed (reply the `failed` ack /
`.failed` marker; NEVER touch `done_marker`, NEVER rewrite the record just to
make the check pass).

Final reply = single bounded ack line only (`ok <checkpoint_path> <n>` /
`failed <reason>`), per the stage prompt's Return-to-orchestrator section.
