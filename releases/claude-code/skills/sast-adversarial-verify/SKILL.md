---
name: sast-adversarial-verify
description: s6 adversarial-verify lens — second-opinion review of a candidate finding; decide TRUE vs FALSE_POSITIVE and assign a CVSS 3.1 vector.
license: Apache-2.0
---

# s6 verify lens

<!--
  Lens content is the verbatim ported prompt in core/prompts/stages/s6-verify.md — referenced, not
  duplicated, so the core is the single source of truth. See
  core/docs/prompt-provenance.md.
-->
Apply the ported prompt at **core/prompts/stages/s6-verify.md** as your
lens for this stage. It is a verbatim port from vvaharness (Apache-2.0) — use it
unchanged to keep scanning effectiveness aligned with the original pipeline.
