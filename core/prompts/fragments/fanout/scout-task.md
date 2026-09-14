<!--
  mgh-init fan-out task message template (scout tier). Install mirrors to
  <mgh-core>/prompts/fragments/fanout/scout-task.md. NOT loaded into any
  orchestrator context: fanout_runner.py reads this file and substitutes the
  placeholders verbatim (pure str.replace; placeholder set fixed in the
  runner's PLACEHOLDERS tuple). Behavior rules live in stages/init-scout.md
  (loaded via the agent definition) — this template carries ONLY the per-unit
  input fields + the load instruction, so there is exactly one place to
  maintain behavior.
-->

You are **S3 — scout-reader** for ONE scout batch. Your behavior is defined by
the prompt at `{{repo}}/.opencode/mgh-core/prompts/stages/init-scout.md` (or
`{{repo}}/.claude/mgh-core/prompts/stages/init-scout.md` on a claude install) —
READ it first and follow it exactly; this message supplies only your input
fields. That path is the stage prompt's ONLY location: if the Read fails,
immediately reply `failed mgh-core prompts not installed at <path>` — NEVER
search other directories (parent project, /home, /adhome, siblings) for prompts
or scripts.

batch_id: {{batch_id}}
repo (anchor root, absolute): {{repo}}
input_path (read this one file; carries targets[] + needs_slice[]): {{input_path}}
checkpoint_path (write EXACTLY here): {{checkpoint_path}}
done_marker (touch EXACTLY this after writing the checkpoint): {{done_marker}}
failed_marker (reference only; the dispatcher writes it on a failed ack): {{failed_marker}}
slice_dir (in-tree dir for needs_slice[] big-file slices): {{slice_dir}}
chunk_sources (absolute tool script, invoke verbatim as `py "<path>"`): {{chunk_sources_abs}}
codegraph signal: codegraph={{codegraph}}

Final reply = single bounded ack line only (`ok <checkpoint_path> <n>` /
`failed <reason>`), per the stage prompt's Return-to-orchestrator section.
