<!--
  Ported from vvaharness (Visa, Inc. / Project Glasswing), Apache-2.0.
  Source: vvaharness/util/prompts.py::EXHAUSTIVENESS
  Fidelity: verbatim
  Extracted verbatim by tools/extract_prompts.py (content-only; no
  runtime dependency on vvaharness). See core/docs/NOTICE and
  core/docs/prompt-provenance.md.
-->

COVERAGE EXPECTATION — one finding is the minimum, not the target. Files in
scope routinely contain several unrelated issues. After logging a finding,
keep reading; do not return until every line in the assigned scope has been
examined.

If the scope is large enough that output limits become a concern, emit HIGH
items in full, then append a one-line tally of MEDIUM/LOW items held back.
