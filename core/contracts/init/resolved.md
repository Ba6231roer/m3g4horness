# Contract: `resolved.json`

Producer: `init-resolve` subagent (optional, codegraph-gated stage between
scout-merge and T1; runs in a SINGLE context — no fan-out). Consumer: orchestrator
(additive fold-in into the candidate set before T1) + audit trail.

This artifact exists ONLY when the orchestrator signal is `codegraph=on` AND
`controls_candidates.json::unresolved[]` is non-empty. Otherwise the stage is
skipped and `resolved.json` is not produced (fail-soft; the pipeline is unchanged).

Top-level shape:

```json
{
  "repo": "<abs repo root>",
  "resolved": [<Candidate-subset, source:"codegraph">, ...],
  "unresolved_residual": ["<file>", ...]
}
```

A `resolved` entry (additive candidate; same shape contract as a scout candidate,
plus `resolved_path[]`):

```json
{
  "file": "src/main/java/com/bank/auth/MethodAspect.java",
  "line": 42,
  "category": "authorization",
  "kind": "auth",
  "anchor": {"class": "MethodAspect", "method": "around", "kind": "method"},
  "shape": "centralized|distributed",
  "evidence_snippet": "≤120 chars, single JSON-safe line codegraph/Read returned",
  "confidence": 0.0,
  "source": "codegraph",
  "resolved_path": ["src/.../TransferController.java:88", "src/.../MethodAspect.java:42"]
}
```

- `category` ∈ the 8 init categories (see inventory.md); MUST be non-empty.
- `kind` ∈ 6-enum (see `category→kind` map in inventory.md).
- `anchor` = nearest enclosing class/method/annotation the control declares.
- `shape` ∈ `centralized` | `distributed`.
- `evidence_snippet` = JSON-safe single line (`"`→`'`, strip `\`); from the
  codegraph-returned or Read-fallback source. Grounds the candidate.
- `confidence` = SHALL NOT exceed regex/scout evidence grade (existence ≠
  effectiveness; CVE-2025-41248). codegraph confirms wiring/existence, NOT that
  the control is correct/bypass-proof.
- `source` = `"codegraph"` (fixed for every entry from this producer; the same
  structural tag enum as `regex`/`scout` in candidates.md — additive, same purity
  rules, never a human-readable process description).
- `resolved_path[]` = the call/route path codegraph returned (entry point → … →
  this control), each element a real `file:line` / `file:symbol`. MUST be
  non-empty — it is the proof the control is wired (vs dead code) and the additive
  value this stage contributes over the text/AST call graph.
- `unresolved_residual[]` = entries codegraph could not resolve either (pure
  runtime reflection / DI-container dispatch / dynamic proxy with no static edge).
  Shrinks-not-zeros `unresolved[]`; counted into `init_manifest.json::codegraph.unresolved_residual`.

### Fold-in (additive, by the orchestrator)

`resolved[]` joins the same candidate stream as regex/scout candidates and goes
through the unchanged `form_clusters` clustering (cluster-formation logic is not
mutated; no regex/scout candidate is altered). `source: "codegraph"` is retained
as the structural tag into `controls_candidates.json` / `controls_inventory.json`
for manifest + audit. T1/T2/T3 consume these candidates identically to scout ones.
