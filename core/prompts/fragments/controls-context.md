<!--
  Original to mgh-sast (not ported). Inlined into the task message of controls-aware
  stages (s2 / s3 / s4 / s6 / s8) when a controls_bundle is present. The ported SYSTEM
  prompts already reserve the consumption wording (s2 "design controls LOWER likelihood";
  s8 "design control genuinely blocks a chain → downrank" / `blocked_by_controls`); this
  fragment supplies the structured bundle they consume and the honesty rule.
-->

DESIGN CONTROLS — treat every entry as a CLAIMED protection, never a verified neutralizer.

A `controls_bundle` may accompany this task. It is the in-scope subset of a
`controls_inventory.json` (existence candidates induced from source), scope-projected to
this scan:

   controls_bundle = {
     "source": "mgh-init", "inventory_path": "...",
     "total": N, "in_scope_count": M, "out_of_scope_count": K,
     "in_scope": [ {name, kind, description, usage, evidence, entry_points, protects, gaps}, ... ],
     "out_of_scope_summary": [ {name, kind}, ... ]   // relevance hint only
   }

`in_scope[]` is your primary input. `out_of_scope_summary` is a fallback visibility list
— consult it only if an in-scope control clearly failed to cover a path you are auditing
(the projection can under-filter). Projection is a hint, not a verdict.

RULE 1 — existence is not effectiveness.
   The inventory asserts that a control EXISTS at an anchor; it does not assert that the
   control is correct, complete, reachable on this path, or bypass-proof. Known bypass
   classes exist (e.g. `@PreAuthorize` on parameterized types). A control present in the
   bundle NEVER by itself makes a finding disappear.

RULE 2 — neutralize only on evidence-grounded data-flow grounds.
   You may mark a finding FALSE_POSITIVE (s6) or add it to `blocked_by_controls` (s8) on
   control grounds ONLY when a control's `evidence` anchor sits on the SAME data flow,
   UPSTREAM of the source→sink path of this finding, and the control's `kind`/`usage`
   actually covers the bug class. Trace the flow; cite the upstream anchor in your
   reasoning. If you cannot place the control upstream on this flow, you MAY downrank but
   MUST NOT neutralize.

RULE 3 — gaps caveats are binding.
   A control's `gaps[]` (e.g. "parameterized types bypass", "test profile only") names
   known holes. If a gap plausibly applies to this finding, the control does NOT
   neutralize it; downrank at most.

STAGE USE (matches the reserved prompt wording):
   s2 threat-model  — a relevant in-scope control LOWERS a threat's likelihood; never to
                      zero. Record the control `name` in the threat's `controls` field.
   s3 decompose     — prefer chunks that touch an in-scope control's `entry_points` /
                      `protects` paths first (controls are where中和 claims live).
   s4 deep-dive     — do NOT exclude a source/sink region merely because a control lists
                      it under `protects`; the control may be off-path or gapped. Exclude
                      only on Rule 2 data-flow grounds.
   s6 verify        — FALSE_POSITIVE on control grounds requires Rule 2; fill the finding's
                      `controls` with the neutralizing control `name`. Otherwise downrank.
   s8 chain         — add a control to `blocked_by_controls` only under Rule 2; else
                      "design control genuinely blocks this chain" is downrank, not removal.

SURFACE WHAT YOU SUPPRESSED.
   Any finding/chain you downranked or blocked because of a control MUST be listed in the
   report's control-affected appendix (control `name`, the evidence anchor you relied on,
   and why). Nothing controlled vanishes silently — every suppression is human-reviewable.
