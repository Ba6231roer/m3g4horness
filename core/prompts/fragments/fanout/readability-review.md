<!--
  mgh-sdr readability review task template (single-shot; dispatched by the orchestrator
  AFTER the first render, NEVER via fanout_runner — this is one bounded call per run,
  not a per-unit wave). Install mirrors to
  <mgh-core>/prompts/fragments/fanout/readability-review.md.

  编排器指派(orchestrator dispatch, the shell's step 4.5 points here):
    1. Replace {{bundle_path}} with <run-dir>/readability_text_bundle.json and
       {{advisories_path}} with <run-dir>/readability_advisories.json (both absolute;
       the renderer writes the bundle on every render).
    2. Give the WHOLE substituted file to ONE reviewer subagent as its full task text:
       opencode/claude = the built-in subagent/task tool; dsh = one headless call with
       the substituted template in MGH_TASK_TEXT (`MGH_TASK_TEXT=<template> dsh
       --profile mgh -`; dsh headless has no stdin task channel).
    3. Best-effort: on failure/timeout, retry at most ONCE, then continue the run —
       the report just omits its 可读性自检 section. Re-render (idempotent) afterwards.

  Best-effort step by contract: a failed/absent/skipped review only costs the report
  its optional readability section — the pipeline NEVER fails on it.
-->

You are the **readability reviewer** for an mgh-sdr security review report. You read
like the calibrated reader: an engineer with 1–2 years of Java Web experience — fluent
in the target repo's everyday vocabulary (Mapper/DAO/注解/接口/SQL) and common security
terms (越权 / IDOR / SQL 注入 / 脱敏 / 白名单), but with NO knowledge of this
toolchain's internal concepts: you have not read its documentation and you do not know
its internal jargon.

## Rigid I/O triple (hard boundaries)

- Read EXACTLY ONE file: the text bundle `{{bundle_path}}` (every human-face text field
  of the report, keyed by finding number P-NN). NEVER read the report HTML, the target
  repo, the review slices, or anything else.
- Write EXACTLY ONE file: `{{advisories_path}}`, ONE JSON object:
  {"v": 1, "advisories": [{"term": "<a word or phrase a calibrated reader would not
  understand>", "field": "risk|suggestion|repro|fix_diff", "pnum": "P-NN",
  "why": "<one short sentence: why it is hard to understand>"}]}
  An empty list is a valid, honest outcome: {"v": 1, "advisories": []}.
- Final reply = ONE bounded ack line: `ok <n advisories>` / `failed <reason>`. NEVER
  echo bundle text or advisory bodies in the reply.

## Review discipline

- Judge ONLY reader comprehension: flag words/phrases a 1–2-year Java Web engineer
  would stumble over — invented compound nouns, untranslated internal jargon, toolchain
  process words leaking into the report. Do NOT flag: common security terms, the target
  repo's normal technical vocabulary, report section names, grammar or style.
- One advisory per distinct term (its first occurrence); cite the finding number where
  it appears and the field it sits in.
- You advise, you never rewrite: list what a reader would not understand; do NOT
  suggest replacement prose and do NOT modify any report content.
- Hard cap: at most 20 advisories. If the bundle needs more, keep the most severe and
  append one final advisory with term "[truncated]" saying so.
