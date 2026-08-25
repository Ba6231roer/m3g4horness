<!--
  mgh-init fan-out task message template (t3 tier). Install mirrors to
  <mgh-core>/prompts/fragments/fanout/t3-task.md. NOT loaded into any
  orchestrator context: fanout_runner.py reads this file and substitutes the
  placeholders verbatim (pure str.replace; placeholder set fixed in the
  runner's TIERS["t3"] entry — rule_path instead of checkpoint_path/slice_dir;
  rulewriter writes the rule file directly, no big-file slicing). Behavior
  rules live in stages/init-rulewriter.md (loaded via the agent definition) —
  this template carries ONLY the per-unit input fields + the load instruction,
  so there is exactly one place to maintain behavior.
-->

You are **T3 — per-category rule writer** for ONE category. Your behavior is
defined by the prompt at
`{{repo}}/.opencode/mgh-core/prompts/stages/init-rulewriter.md` (or
`{{repo}}/.claude/mgh-core/prompts/stages/init-rulewriter.md` on a claude
install) — READ it first and follow it exactly; this message supplies only
your input fields.

category: {{category}}
format (exactly one; never mix structures): {{format}}
repo (anchor root, absolute): {{repo}}
input_path (read this one file; carries this category's full controls): {{input_path}}
rule_path (write EXACTLY here): {{rule_path}}
done_marker (touch EXACTLY this after writing the rule): {{done_marker}}
failed_marker (reference only; the dispatcher writes it on a failed ack): {{failed_marker}}

Final reply = single bounded ack line only (`ok <rule_path> <n>` /
`failed <reason>`), per the stage prompt's Return-to-orchestrator section.
