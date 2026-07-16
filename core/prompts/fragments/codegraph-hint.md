<!--
  rewrite-original (mgh-init / codegraph enrichment hint). No vvaharness port.
  Inlined into the task message of codegraph-aware stages (scout / induct /
  survey / resolve) ONLY when the orchestrator signals `codegraph=on`.
  Prescriptive by intent: "codegraph=on → SHALL prefer codegraph, Read only as
  fallback", never the permissive "you may use codegraph" — that wording lets a
  subagent keep self-Reading and turns codegraph into pure overhead.
-->

CODEGRAPH SURGICAL CONTEXT — engage only when the orchestrator signal is
`codegraph=on`. When the signal is `codegraph=off` (or absent), IGNORE this
fragment entirely and read files as usual; do not issue any codegraph call.

When `codegraph=on`, the target repo has a precomputed knowledge graph
(`<target>/.codegraph/`) plus the `codegraph` tool on PATH. That graph already
holds every symbol, call edge, framework route (Spring `@*Mapping` / Feign / AOP
pointcuts / `@Autowired` / JPA), and interface→implementation, reachable in one
call. Re-deriving that by Read/Glob/Grep is the exact work codegraph already did.

PREFER CODEGRAPH, FALL BACK TO READ — in this fixed order:

1. **Primary — MCP `codegraph_explore`**. For a target symbol / file / natural
   question, call `codegraph_explore "<names or question>"` once. It returns the
   verbatim, line-numbered source of the relevant symbols grouped by file, PLUS
   the call path among them (including framework-route and interface→impl hops
   that textual grep cannot follow) and a blast-radius summary of what depends on
   them. Treat its returned source the same way you would a `Read` result — it is
   Read-equivalent and safe to reason from.
2. **Fallback A — CLI `codegraph explore`** (Bash). Use it ONLY if the MCP tool is
   not available in your context: `codegraph explore "<names or question>"` prints
   the same output.
3. **Fallback B — `Read` / `Glob` / `Grep`**. Use these ONLY for items codegraph
   does NOT cover:
   - a file in a **non-indexed language**,
   - a file larger than the run's `--big-file-bytes` (codegraph may elide very
     large files; for these, slice via `chunk_sources.py` as the stage already
     instructs, do not whole-Read),
   - a symbol codegraph's index does not contain (it returns nothing for it), or
   - a file codegraph itself flags as stale — when a `codegraph_explore` / CLI
     result carries a `⚠️ pending sync` / `pending` staleness banner naming a
     file, that file's index may lag the working tree; Read that file directly to
     avoid reasoning from stale source.

STEERING RULES (binding when `codegraph=on`):
- **SHALL prefer `codegraph_explore`** (or CLI `codegraph explore` if MCP is
  absent) as the first move for any symbol / call-path / framework-route question.
  **MUST NOT** open the same file with `Read` when codegraph already returned its
  source for that symbol.
- **SHALL fall back to `Read`** only under one of the four uncovered cases above,
  and only for the specific uncovered file/symbol — never abandon codegraph for
  the whole task because one file is uncovered.
- **MUST NOT** invent codegraph output. Every `file:line` you cite SHALL come from
  either a codegraph-returned real symbol or a file you actually Read. If
  codegraph returns nothing and Read confirms no control, emit nothing for it
  (precision over recall — same hard rule as the rest of the stage).
- codegraph is a **locator / contextualizer / resolver**, not a classifier. It
  does not decide category, kind, canonical-vs-competing, or effectiveness — those
  stay the stage's judgment. Existence ≠ effectiveness still holds: a control
  codegraph resolves onto a request path is still a CLAIMED protection, never a
  verified neutralizer.

BLAST RADIUS IS ADVISORY. When a stage uses codegraph's blast-radius (who depends
on a control; whether it sits on a live request path vs dead code), treat it as
**advisory evidence**, never as proof of effectiveness — it strengthens
"existence ≠ effectiveness" reasoning, it does not override it.
