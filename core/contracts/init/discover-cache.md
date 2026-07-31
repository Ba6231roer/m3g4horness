# Contract: `<out>/cache/` + discover resilience stdout

Producer: `core/scripts/discover_controls.py` (i1, deterministic, stdlib). Consumer:
the `/mgh-init` orchestrator (resume / time-budget re-dispatch) + audit trail.

discover no longer assumes a single host call finishes. It checkpoints a built call
graph and scan progress under `<out>/cache/` so a re-run (or an orchestrator
re-dispatch with `--resume`) advances without total loss, and a soft `--time-budget-ms`
exits cleanly instead of being SIGKILL'd mid-write. All writes are atomic (`.tmp` +
`os.replace`), so a kill leaves no truncated artifact. These are **additive**: with no
cache present and `--time-budget-ms 0` (default), behavior is byte-equivalent to before.

## `<out>/cache/` layout

| file | written when | shape |
|---|---|---|
| `manifest.json` | after the call graph is built (rebuilt) | `[{rel, mtime, size}, ...]` sorted by `rel` |
| `callgraph.json` | after the call graph is built (rebuilt) | `{forward, reverse, framework_files}` |
| `scan_progress.json` | every `--progress-every` files during scan + on completion | `{scanned_index, candidates[], manifest}` |

- `manifest.json` is the **single freshness signal**. discover rebuilds the manifest
  from the current source files (each `(rel, mtime, size)`, sorted by `rel`) and compares
  it byte-for-byte against the cached one. Equal → cache hit; any source changed
  (mtime/size) → stale → rebuild. mtime granularity is filesystem-dependent; coarse on
  some Windows filesystems but acceptable.
- `callgraph.json::reverse` and `::framework_files` are serialized as sorted lists and
  rehydrated to sets on load; `forward` is `{caller: {callee: weight}}`. A cache hit
  skips the two regex passes entirely (the saved cost).
- `scan_progress.json::scanned_index` is the count of fully-scanned files (a stable
  `rel` sort makes it reproducible across runs); `candidates[]` is the accumulated
  candidate list so far. Its stored `manifest` must also match the current snapshot, or
  the checkpoint is ignored (it belongs to a different source set).

## Flags

- `--rebuild-cache` — force a call-graph rebuild + cache refresh, ignoring the
  freshness check (default: rebuild only when the cache is absent or stale).
- `--resume` — reuse the callgraph cache and scan checkpoint: skip the two graph passes
  and the already-checkpointed files, continue scanning from `scanned_index`, append
  candidates. Idempotent: resuming the same checkpoint twice yields an equivalent
  candidate set.
- `--time-budget-ms <N>` (default `0` = off) — when set, discover checks the elapsed
  time at safe boundaries only (after the call graph is built; every `--progress-every`
  files during scan — never mid atomic-write). If exceeded it writes the cache +
  checkpoint and exits **0** with stdout `partial: true`.

## Discover stdout summary (resilience fields, additive)

The one-line JSON stdout gains three fields; the existing fields are unchanged:

```json
{"candidates": N, "clusters": M, "unresolved": U, "unresolved_count": U,
 "big_files": K, "dotfiles_skipped": D, "out_of_scope": O,
 "truncated": false, "scanned": S,
 "partial": false, "resume_hint": "", "cache_hit": true}
```

| field | note |
|---|---|
| `cache_hit` | bool — the callgraph cache was loaded this run (two passes skipped) |
| `partial` | bool — discover stopped at a safe boundary within `--time-budget-ms`; only `cache/` + `scan_progress.json` landed; **no** final product was written |
| `resume_hint` | str — actionable text for the orchestrator (re-dispatch `--resume`) when `partial` is true; empty otherwise |

On `partial: true` the orchestrator **re-dispatches** `discover ... --resume` via Bash
(a host-agent loop, never a wrapper `.py`) until `partial: false`; `--check` and
downstream consumers only run on a complete run.
