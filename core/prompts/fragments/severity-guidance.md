<!--
  Ported from vvaharness (Visa, Inc. / Project Glasswing), Apache-2.0.
  Source: vvaharness/util/prompts.py::SEVERITY_GUIDANCE
  Fidelity: verbatim
  Extracted verbatim by tools/extract_prompts.py (content-only; no
  runtime dependency on vvaharness). See core/docs/NOTICE and
  core/docs/prompt-provenance.md.
-->

SEVERITY — rate the exploit, not the bug class. "SQL injection" is not a
severity; "unauthenticated SQLi reachable from the internet" is.

STEP 1 — write down three things first:
   - Preconditions: every "attacker must already have/know/be" required.
   - Access level: anonymous / any authenticated user / privileged role /
     same-host.
   - Blast radius: one record, one tenant, the whole service, or the
     underlying host.

STEP 2 — map to a tier:
   HIGH    Reachable with no auth (or any low-privilege session), zero or one
           precondition, and the impact is RCE, auth bypass, or bulk
           cardholder/PII exposure.
   MEDIUM  Needs a valid session OR a couple of realistic preconditions;
           impact is scoped (single user, partial data, integrity only).
   LOW     Three or more stacked preconditions, local/adjacent access only,
           or impact limited to availability of a non-critical component.

STEP 3 — downgrade triggers (apply after step 2):
   - Sits in test/example/debug/non-prod code        → drop one tier.
   - Requires a second independent vuln to matter    → drop one tier.
   - Can't decide between two tiers                  → pick the lower one.
     A mis-labelled HIGH burns reviewer trust faster than a cautious MEDIUM.
