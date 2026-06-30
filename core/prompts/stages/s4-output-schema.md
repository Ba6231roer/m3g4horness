<!--
  Ported from vvaharness (Visa, Inc. / Project Glasswing), Apache-2.0.
  Source: vvaharness/pipeline/stages/s4_deepdive.py::_OUTPUT_SCHEMA
  Fidelity: verbatim
  Extracted verbatim by tools/extract_prompts.py (content-only; no
  runtime dependency on vvaharness). See core/docs/NOTICE and
  core/docs/prompt-provenance.md.
-->

Respond with ONLY a JSON object (no prose before or after):
{
  "findings": [
    {
      "file": "src/parser.c",
      "line_start": 142,
      "line_end": 158,
      "vuln_class": "heap-overflow|use-after-free|stack-overflow|format-string|integer-overflow|type-confusion|race-condition|injection|unsafe-deserialization|logic-flaw|info-leak|other",
      "cwe": "CWE-79  (single most-specific CWE id; omit if no clear mapping)",
      "title": "Under 12 words",
      "impact": "2-3 plain-language sentences: what an attacker gains, who is affected, why it matters",
      "description": "Detailed input-to-bug data flow explanation",
      "exploit_scenario": "Max 5 sentences: the specific input the attacker sends and the resulting impact",
      "preconditions": ["condition 1", "condition 2"],
      "recommendation": "Security property that must hold + specific location in THIS code and what to change",
      "code_snippet": "the vulnerable lines",
      "source_ref": "src/api/Controller.java:71   (where untrusted input enters; same as sink_ref for context-free bugs like hardcoded secrets)",
      "sink_ref": "src/parser.c:148   (where that input is used unsafely)",
      "confidence": 0.85
    }
  ]
}

An empty {"findings": []} is acceptable ONLY after you have traced every
entry point, every sink, and every cross-cutting pattern above and confirmed
each is mitigated or unreachable — never as a default. Assume at least one
exploitable defect is present in the slice.
