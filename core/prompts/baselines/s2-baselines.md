<!--
  Ported from vvaharness (Visa, Inc. / Project Glasswing), Apache-2.0.
  Source: vvaharness/pipeline/stages/s2_threatmodel.py::_BASELINES
  Fidelity: verbatim (dict literal rendered as markdown)
  Extracted verbatim by tools/extract_prompts.py (content-only; no
  runtime dependency on vvaharness). See core/docs/NOTICE and
  core/docs/prompt-provenance.md.
-->

### web-api
    - OWASP A01 Broken Access Control (IDOR, path traversal, forced browsing, privilege escalation)
    - OWASP A02 Cryptographic Failures (weak/missing crypto, plaintext secrets/transport)
    - OWASP A03 Injection (SQL/NoSQL/OS/LDAP/template/header)
    - OWASP A04 Insecure Design (missing rate-limit, trust-boundary assumptions)
    - OWASP A05 Security Misconfiguration (default creds, debug on, permissive CORS)
    - OWASP A07 Identification & Authentication Failures (weak session, missing MFA, JWT flaws)
    - OWASP A08 Software & Data Integrity Failures (unsafe deserialization, unsigned updates)
    - OWASP A10 Server-Side Request Forgery
    - XSS (reflected / stored / DOM)
    - CSRF / state-changing GET

### mobile
    - OWASP M1 Improper Credential Usage (hardcoded keys, token leakage)
    - OWASP M3 Insecure Authentication/Authorization
    - OWASP M5 Insecure Communication (no cert pinning, cleartext traffic)
    - OWASP M8 Security Misconfiguration (exported components, debuggable build)
    - OWASP M9 Insecure Data Storage (world-readable prefs, unencrypted DB)

### native
    - CWE-119/787 Buffer overflow (stack/heap write OOB)
    - CWE-416 Use-after-free / double-free
    - CWE-190 Integer overflow leading to undersized allocation
    - CWE-134 Format-string
    - CWE-362 TOCTOU / race condition
    - CWE-78 OS command injection via system()/exec()

### iac
    - Over-permissive IAM / RBAC (wildcard actions, cluster-admin bindings)
    - Public network exposure (0.0.0.0/0 ingress, hostNetwork, public S3/bucket)
    - Secrets committed in plaintext / env
    - Privileged or root containers, missing securityContext
    - Disabled TLS / unencrypted storage classes

### library
    - Injection via untrusted caller input (SQL/OS/path)
    - Unsafe deserialization (pickle/yaml.load/XMLDecoder/ObjectInputStream)
    - Path traversal in file-handling APIs
    - ReDoS / algorithmic-complexity DoS
