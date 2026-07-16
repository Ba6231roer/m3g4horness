# Evaluation runbook — codegraph enrichment (§6, R5.7 TDD-for-docs)

> Operator-run. The prompt + contract + shell changes are deterministic and
> test-covered (§5). This file captures the empirical evaluation that MUST run
> against a live codegraph index + real target repo before the change is
> considered shipped-validated. Leave `tasks.md` 6.1–6.3 unchecked until each runs.

## Already confirmed (this apply session)
- `codegraph` CLI on PATH: **v1.4.1**. ✓
- MCP `codegraph_explore` works against an existing index (this repo) — returns
  verbatim source + call path + blast radius. → confirms the host-capability
  precondition for 6.2 ("subagents CAN issue `codegraph_explore`") and 6.3's
  claude-side MCP availability. Open Question **O1 (opencode subagent MCP
  inheritance)** and the full runs below are still operator-deferred.

## Targets (local, framework-route / AOP controls)
- `C:\DEV\WebGoat` — Spring (Spring Security + deliberately vulnerable); route +
  method-security controls the text graph leaves `unresolved[]`.
- `C:\DEV\aspect-example` — AspectJ/AOP pointcut-woven controls (no textual edge).
- Neither is indexed yet. First step per target: `codegraph install --target <repo>`
  then build the index (`codegraph` CLI; ~minutes for a multi-k Java repo), so
  `<repo>/.codegraph/` exists → the step-0 detection stanza flips `codegraph=on`.

## 6.1 — Baseline (variance is the metric)
On ONE indexed target, run `/mgh-init --format claude --target <repo> --no-codegraph`
**≥3×** (delete `<repo>/.mgh-init/` between runs, or use distinct `--out`). Capture,
per run:
- scout token cost + round-trip count (from the host's subagent usage telemetry);
- `init_manifest.json::counts.unresolved` (the `unresolved[]` size codegraph should
  later drain).
Record mean + spread. The spread (not the mean) is the baseline noise floor.

## 6.2 — Blind A/B (codegraph=on vs --no-codegraph)
Same indexed target, fresh `<repo>/.mgh-init/` each time:
- **A** = `codegraph=on` (auto-detected; `.codegraph/` present, no `--no-codegraph`).
- **B** = `--no-codegraph`.
Assert on run **A**:
- (a) scout/induct/survey/resolve subagents actually issue `codegraph_explore`
  (not bypass to Read) — inspect subagent tool-use transcripts;
- (b) `init_manifest.json::codegraph.resolved_count > 0` for framework-route /
  AOP / interface→impl controls, and `codegraph.unresolved_residual < counts.unresolved` (B);
- (c) token/round-trip delta vs B on the large sample (large repo ⇒ biggest win).
Any new failure mode (e.g. subagent still self-Reads → codegraph pure overhead, the
trap the prescriptive fragment wards against) flows back into
`core/prompts/fragments/codegraph-hint.md` wording, then re-run A/B.

## 6.3 — opencode parity (resolves O1)
On the indexed target under an **opencode** host:
- confirm the opencode subagent context can invoke `codegraph_explore` MCP (the
  agent def `releases/opencode/agent/init-resolve.md` + the three stage prompts
  declare MCP-primary);
- if opencode does NOT inherit the codegraph MCP server, confirm the CLI fallback
  `codegraph explore` (Bash) works — the resolve agent def lists `bash: allow` /
  `Bash` precisely for this fallback (D2 fallback order). Record which path is live.

## Pass criteria (check 6.1–6.3 only after)
- 6.1: baseline variance recorded (≥3 runs).
- 6.2: (a) subagents issue `codegraph_explore`; (b) `resolved_count > 0` +
  residual shrinks; (c) delta recorded; no regressions vs B's `unresolved[]`.
- 6.3: opencode path confirmed (MCP or CLI fallback) on the target.
