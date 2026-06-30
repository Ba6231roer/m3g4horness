<!--
  Ported from vvaharness (Visa, Inc. / Project Glasswing), Apache-2.0.
  Source: vvaharness/util/prompts.py::SELF_VERIFICATION
  Fidelity: verbatim
  Extracted verbatim by tools/extract_prompts.py (content-only; no
  runtime dependency on vvaharness). See core/docs/NOTICE and
  core/docs/prompt-provenance.md.
-->

GATE EVERY FINDING ON THESE FIVE CHECKS — drop it if any fail:

1. REACHABLE   An external or lower-privileged caller can actually hit this
               code path. Walk backward from the sink and name the entry point.
2. UNMITIGATED No validation, encoding, allow-list, or framework control
               between source and sink already neutralizes it.
3. CONCRETE    You can state the exact payload and the exact effect in one
               sentence. "Could potentially" = not a finding.
4. IN SCOPE    It does not match any exclusion group A–E above.
5. CITED       Both source_ref and sink_ref are real file:line locations you
               read in this codebase. For single-site issues (hardcoded key,
               weak cipher constant) use the same ref for both. No line
               numbers = no proof of data flow = do not emit.

SEVERITY SANITY: count the preconditions you just listed. Multiple "must
already have X" steps, or impact limited to non-prod code, caps the finding
at MEDIUM or below.
