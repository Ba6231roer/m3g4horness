<!--
  Ported from vvaharness (Visa, Inc. / Project Glasswing), Apache-2.0.
  Source: vvaharness/util/prompts.py::EXCLUSION_RULES
  Fidelity: verbatim
  Extracted verbatim by tools/extract_prompts.py (content-only; no
  runtime dependency on vvaharness). See core/docs/NOTICE and
  core/docs/prompt-provenance.md.
-->

OUT OF SCOPE — do not report:

A. NO REAL ATTACKER
   - Code that is unreachable in production: tests, fixtures, samples, dead branches,
     build/tooling scripts run only on a developer's own workstation.
   - Inputs that can only be set by someone who already has shell or deploy access
     to the same host (local argv, local env). Exception: if the value crosses a
     boundary — CI/CD job parameters, scheduler args, shared config in a repo or
     mount that a different team or service can write — treat it as untrusted and
     report (usually LOW).

B. NO SECURITY IMPACT
   - Crashes from bad config, missing keys, import failures, or null derefs that
     don't expose data or grant access.
   - Functionality working as designed (legacy crypto kept for migration,
     compression, intentional wildcard CORS on a public asset, etc.).
   - Non-security randomness or placeholder secrets (jitter, test seeds,
     dev-profile fallbacks) when the prod value is injected from Vault/HSM/KMS.

C. WRONG LAYER
   - Server-side bug classes (SSRF, authZ, path traversal) raised against pure
     client/browser code — enforcement belongs to the service.
   - Memory-corruption findings in managed languages (Java, C#, Go, Python, JS)
     unless the code drops into JNI / cgo / unsafe / native bindings.
   - "../" in object-store or blob keys where the key space is flat and no
     filesystem boundary exists to cross.
   - SSRF where only the path is influenced; attacker must steer host or scheme.

D. HANDLED ELSEWHERE
   - Vulnerable third-party library versions — covered by the SCA/dependency
     pipeline, not this scan.
   - Pure volumetric / rate-limit DoS — infra concern. Still report
     input-driven complexity blowups (regex backtracking, recursive expansion,
     unbounded allocation from a single request).

E. NOISE FLOOR
   - Log injection / log forging with no downstream parser.
   - Prompt text passed to an LLM (tracked under the AI-governance program,
     not SAST).
   - Theoretical best-practice gaps with no demonstrated path to data exposure,
     auth bypass, or code execution.
