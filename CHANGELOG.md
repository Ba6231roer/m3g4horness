# Changelog

All notable changes to **m3g4h⊿rness** are recorded here.
Format based on [Keep a Changelog](https://keepachangelog.com/), versioning follows
[Semantic Versioning](https://semver.org/).

`m3g4h⊿rness` (SAST tool: `/mgh-sast`) is a zero-runtime-dependency reimplementation of the
[vvaharness](https://github.com/visa/vvaharness) (Visa / Project Glasswing) 9-stage
agentic SAST pipeline. Prompt **content** is ported under Apache-2.0 (see
`core/docs/NOTICE`); no `vvaharness` code is imported or bundled.

The `0.x` line denotes initial development: structurally complete, but live
end-to-end verification is still pending (see *Pending* below).

---

## [Unreleased]

### Changed — `/mgh-init` T2 oversize category: deterministic part split + atomic slim projection (0.1.42)

A T2 unit crashed with a model context-overflow in a real run: the `authorization`
category alone serialized to 400KB > the 256KB budget, and `plan_aggregate.py`'s
old fallback ("`oversize:true` + stderr warn + dispatch anyway") sent a doomed
request. Root cause: per-category sharding treated one category as atomic even
when it alone exceeded the budget. Fix: split it (`harden-mgh-init-t2-oversize-shard`):

- **Part split**: an over-budget category is greedy-packed whole-record (existing
  glob order, deterministic) into ≤-budget parts `t2-<category>-part<N>`; the shard
  input envelope and stdout shard items carry `part_index`/`part_count` (0/1 when
  unsplit). Rollup now reconciles across shards — same category across parts AND
  across categories, same judgment signals; partial still makes NO cross-shard
  judgment. Marker-aware re-list / `.done`/`.failed` / dispatcher waves unchanged.
- **Atomic-oversize fallback**: a single record > budget is slim-projected at
  materialization (truncates `description`/`usage`/`protects`/`gaps`/`entry_points`
  to internal caps; `evidence` anchors never cut; `_slimmed` marker + stdout
  `slimmed` disclosure; `checkpoints/t1` originals never rewritten). Still over
  after slimming → exit 2 with the record file + byte count, zero dispatch.
  Dispatched T2 shards are always ≤ budget ⇒ `oversize` is always false (field
  kept for compat). scout-merge envelope/stdout byte-identical (hand-paged).
- **P2 diagnosis**: `fanout_runner.py` matches crashed units' stderr tails against
  a context-overflow signature set → `reason:context-overflow` + narrow-`--budget`
  recipe on the run.log unit line/stderr + `context_overflow[]` in the stdout
  summary; tier-agnostic, outcome semantics unchanged.
- **Zero regression**: `needs_reduce=false` small-repo stdout pinned byte-identical
  in tests; no new flags, no new dependencies.

### Changed — fanout dispatch stall containment: slot backfill + tree-kill + four-level timeout invariant (0.1.41)

`fanout_runner.py` dispatch hardened against hung subagent units burning the whole run
(`harden-mgh-fanout-stall-containment`):

- **Slot-backfill dispatch core** (was wave-barrier): in-flight capped at `--wave`, harvested
  via `concurrent.futures.wait(FIRST_COMPLETED)`, next unit backfilled immediately; queued
  units lazy-skip if their `.done`/`.failed` marker appeared since listing. A single hung unit
  no longer stalls the whole wave. `waves_run` = cumulative dispatch count; stdout contract
  otherwise unchanged (plus new `stall_killed[]`).
- **Stall detection + surgical tree-kill**: per-unit reader threads track output byte-silence;
  silence ≥ `--stall-timeout-s` (default 900, floor 60) or wall-clock ≥ `--call-timeout-s`
  → `_kill_tree` (process group, fixes `.cmd` shim orphans) → unit re-enqueued (no marker —
  crash ≠ confirmed failure). Every unit terminal state appends a `run.log`
  (`<checkpoints>/<tier>/<unit>.run.log`, stdout/stderr tails, ok included); non-ok terminals
  name it on stderr; heartbeat every `--hb-interval-s` prints `inflight/idle/done`.
- **Four-level timeout invariant, fail-loud at spawn (exit 2 + recipe)**: with
  `--time-budget-ms`, explicit `--call-timeout-s` is REQUIRED and must satisfy
  `stall-timeout-s < call-timeout-s < budget-ms × 0.8 < host per-call timeout`
  (compliant pairs: 720000/540/300 opencode, 480000/360/300 claude). Budget without
  call-timeout used to silently inherit 7200s — past every host hard-kill.
- **Zero-progress breaker, dual observation points**: disk terminal count re-listed every
  K = `--stall-waves × --wave` dispatched units AND on queue-drain re-list;
  `--stall-waves` consecutive zero-growth observations with units still outstanding →
  exit 2 + `stalled:true` + `stalled_pending[]` (id + on-disk marker existence). Deterministic
  trip math (wave=1, always-stall): trip at (stall_waves+1)×K dispatches.
- **Bugfix**: run.log previously recorded crash units as `spawn-ok` (status settled after
  evidence write); status classification now precedes the log write.
- **Call-surface sync**: the four init-stage dispatch fragments, both `mgh-sdr.md` shells,
  `discipline_core.py` fan-out recipes, and `mgh_sdr_launch.py`'s emitted command now carry
  explicit `--call-timeout-s`/`--stall-timeout-s` (launcher-emitted commands stay
  invariant-compliant); man pages gained 现象→原因→改法 sections for heartbeats, stall
  auto-recovery, run.log triage, and the breaker.
- **opencode fanout agents pinned**: all five `*-fanout.md` frontmatter permissions add
  `external_directory: deny` + `doom_loop: deny` (claude `-p` headless already auto-denies).
- **Tests**: `test_fanout_runner.py` 77 green (breaker trip/recovery math, slot backfill,
  real-child tree-kill, invariant CLI matrix), `test_fanout_stale.py` 17 green; five-tier
  `--pending-file` + `--kill-stale --dry-run` smoke; contract/purity/prompt-budget lints pass.

### Added — sdr external-repo read authorization gate (0.1.40)

`/mgh-sdr` external-repo retrieval flipped from implicit (any path declared in the existing
design docs was auto-allowed per run) to **explicit user opt-in** (`add-mgh-sdr-read-root-config`):

- **New `core/scripts/read_roots_config.py`** — the config writer for `<repo>/.mgh/read-roots.json`
  (`--target/--add/--remove/--list/--check`; exit 0/1/2; transactional all-or-nothing `--add`;
  repair-with-`.bad`-backup on malformed config; atomic write; idempotent; `--check` fail-loud
  on stale/nonexistent entries with a `--remove` recipe). Config is hand-editable, read-only
  to runs, NEVER written without explicit user consent.
- **Authorization gate, judged twice** (sdr_context.py before retrieval; mgh_sdr_launch.py
  before sentinel write — version-skew defense, semantics in lockstep with the guard's
  config reader): approved = resolve-normalized entry in config ∧ exists ∧ is-dir.
  Unapproved declarations → **zero reads**, `external_skipped:"unapproved: <path>"`,
  `pending_approval[]` in stdout + manifest.
- **pending_approval flow**: stdout → orchestrator → host session asks the user per repo.
  Consent → `read_roots_config.py --add` (one write, persistent) → re-run same args.
  Refusal → degrade with disclosure; NEVER write config without explicit consent.
- **launcher**: prompt + stderr WARN carry the approve recipe and the NEVER clause; sentinel
  `read_roots[]` = configured ∩ actually-retrieved repos ∪ operator `--read-root`.
- **render_sdr_report.py**: new `unapproved` degradation variant, disclosed distinctly from
  `not-found` (unreachable): 外部仓未授权 → 前端相关检查面未覆盖.
- **Shells** (claude + opencode mgh-sdr.md): step-1 pending_approval ask + approve recipe +
  Always-disclose bullet; **contract lint** `tools/check_contracts.py` asserts the new script
  flags + both shells' markers; **install.sh** co-location self-check adds `read_roots_config`;
  zero-dep AST scan covers it via the existing `core/scripts/*.py` glob.
- **Tests**: new `tests/test_read_roots_config.py` (16); `tests/test_sdr_context.py` (20),
  `tests/test_mgh_sdr_launch.py` (9), `tests/test_render_sdr_report.py` (18) extended.

### Added — Bash path-token allowset net + project read-roots config (0.1.39)

Guard Bash face reversed from verb-enumeration blacklist to a verb-independent fail-closed
path allowlist (`harden-mgh-bash-path-allowlist`):

- `block_adhoc_scripts.py` (claude + opencode byte-identical) adds **rule m** — appended LAST
  in the Bash rule chain: EVERY path-like token in any Bash command (drive-letter `C:\…`/`C:/…`,
  UNC `\\…`, POSIX `/…`, `..`-leading resolved against the guard cwd, `~/`-leading expanduser;
  quotes stripped; `://` URL tokens excluded; bare `~`/`..` not judged) must resolve inside the
  **unified read allow-set** = `MGH_TARGET` ∪ sentinel `read_roots[]` ∪ project config
  `read_roots[]`, or the command blocks (exit 2 + recipe naming the three allow-root classes +
  the config remedy). Closes the "verb not in any enumeration table" escape class (`robocopy`,
  `curl -o`, `[IO.File]::WriteAllText`, `Get-Content <file>`, `Expand-Archive`, …); the five
  verb tables REMAIN as refinements (write/delete recipes, cwd-drift, P1 root pollution) and
  mutation rules still run FIRST. No path token / unpinned target => pass.
- **Read allow-set unified across both faces (semantic reversal)**: sentinel `read_roots[]`
  now covers the Bash face (search/listing verbs + the net) exactly like the tool face —
  "what is readable at all is readable through any tool". The write side keeps judging
  `MGH_TARGET` alone; leaf-source / `py -c` / temp-I/O / file-assoc blocks unrelaxed.
- **New project config `<target>/.mgh/read-roots.json`** (schema `{"v":1,"read_roots":["<abs>…"]}`),
  consulted in EVERY run-domain: hand-editable, read-only, never writable, fail-closed
  (missing file = unchanged behavior; malformed JSON / wrong-typed `read_roots` = zero grants,
  no crash; each entry needs exist-and-is-dir containment).
- Accepted new blocks (previously passed): single `> /tmp/x` writes, `--flag=<out-of-tree>`
  values, `git -C <out>`, harmless out-of-tree mentions — remedy = declare a read-only root in
  the config or run outside an mgh session. Residual boundaries disclosed: unknown write verb
  into a declared read-only root; alias/variable indirection.
- `core/contracts/hooks/runtime-enforcement.md` + AGENTS.md R5.7 synced (decision-model table,
  config contract, reversal note); regression tests +24 (`TestBashPathAllowset`,
  `TestReadRootsConfig`), 3 existing cases flipped per the reversal / accepted-blocks budget;
  opencode `.ts` shim + matcher untouched (parity green).

### Added — guard listing/execution confinement + mgh-core missing-install stop-all (0.1.38)

Real-machine Linux first-run hardening (`harden-mgh-guard-listing-exec-confinement`):
mgh-core installed only in the root project while the run executes in an independent
sub-project — scout 409/409 done then T1 stuck 0/9 with the agent roaming `/home`/`/adhome`
hunting for prompts/scripts, plus a `SyntaxWarning` polluting every leaf-script stderr.

- `block_adhoc_scripts.py` (claude + opencode byte-identical) adds three Bash rules:
  **listing confinement** (rule j — `ls`/`dir`/`Get-ChildItem`/`gci` leading a simple command
  with an out-of-tree scope: explicit path token OR `..`-climbing relative OR cwd-anchor,
  mirroring the file-search rule), **interpreter execution confinement** (rule k —
  `py`/`py3`/`python`/`python3`/`python2` running a script whose first anchored
  script-extension positional argument resolves outside the tree; `--flag <path>` values are
  data paths and never judged; `py -c`/`-m` excluded), and **mgh-core missing-install
  stop-all** (rule l — a command referencing an `mgh-core/scripts` script-extension path
  absent on disk (cwd- and target-relative) or existing outside the tree => exit 2 +
  STOP-ALL recipe: stop all tasks, ask the USER to install in the CURRENT project directory,
  NEVER search other directories; checked BEFORE every other Bash rule — terminal state
  short-circuits). Target absent => degrade to pass on all three.
- fan-out task templates (`t1/t2/t3/scout-task.md`): the stage-prompt path is pinned as the
  ONLY location; Read failure => immediate `failed mgh-core prompts not installed at <path>`
  ack, NEVER cross-directory wandering. Stage prompts (`init-induct` / `init-scout` /
  `init-rulewriter`): an in-anchor expected path that does not exist gets the same
  poisoned-input treatment.
- `list_clusters.py` module docstring is now a raw string (the `` `\` `` invalid escape
  triggered a SyntaxWarning on every import-chain load, polluting stderr). New regression
  `tests/test_no_compile_warnings.py` compiles all `core/scripts/*.py` with
  `warnings.simplefilter("always")` — any Warning fails loud.
- Guard suite grows the three-rule hit/pass matrix (+40 tests → 225) including order
  regressions proving existing recipes are unaffected by the new first-position rule.

### Changed — `/mgh-sdr` report restructure: 简报表 + P-NN 详述 + 分支调用链图 (0.1.37)

Report-side readability rework (`improve-mgh-sdr-report-structure`): the per-dimension
problem list is replaced by a unit-row summary table with inlined abbreviated call
chains; problem details move to globally-numbered P-NN sections; only branched units
get a mermaid chain diagram (Plan C — maintainer-selected format sample).

- `diff_group.py`: **chain materialization** — grouping retains raw callee edges (the
  changed-set filter previously dropped unchanged downstream edges) and inverts caller
  edges, then projects each interface unit a deterministic `chain[]` node sequence
  (`{fqn_short, label, file, line, change, route?, branch_of?}`; fqn_short = package
  initials + class + `.` + method; interface→impl resolution prefers the impl; mapper
  XML terminal via one deterministic repo `*.xml` scan keyed by namespace∧statement-id;
  zero new codegraph queries). grouping.json gains `units[]` (full-unit projection with
  route/chain/status — the renderer's row truth, survives fan-out completion).
  Fixed latent `_brace_end` bug: a `//` comment permanently broke brace matching for
  all subsequent lines (methods silently dropped from the symbol map). `--check`
  validates chain node fields + legal branch_of indices.
- `sdr_context.py`: route annotation regex extended to the `@RequestMapping` family
  with class-level base-route join (look-ahead past the class declaration; a class
  annotation itself is a base, never an endpoint). `_external_retrieve` materializes
  per-route occurrence counts into context.json `external_repos[].route_hits[]`
  (`{route, count}` list; was hits.md text only) — the renderer joins it deterministically.
  The permission-config hit count field is renamed `config_hits`. `--check` validates
  the `route_hits[]` shape when present.
- `render_sdr_report.py`: three-section report — 章节一 简报表 (row = unit, sorted
  interface-by-route then standalone; columns = entry / abbreviated chain
  (`·`/`⤷`/`⇢`/`†`) / 前端两列 (route join route_hits three-state) / 6 dimension
  columns `否`|`是 [P-NN]`), 章节二 问题详述 (global P-NN, severity-asc, 位置
  `file:line` with degrade to `file`), 章节三 分支调用链图 (mermaid `flowchart LR`
  per branched unit only). NO md internal anchors anywhere (obsidian/Zed cannot jump
  them) — `--check` asserts `<a id=`/`{#`/`](#` absence and manifest rows-length ==
  table rows. Draft schema gains optional `line` (int anchor line; old drafts degrade,
  not fail). Failed units never become table rows (honesty boundary discloses them).
- sdr-task fragment + both `sdr-review-fanout` agent mirrors: draft schema documents
  `line`; both mgh-sdr shells note the three-section report structure + frontend
  two-column data source.

### Added — `/mgh-init` T2 synthesis map-stage dispatcher adoption (map-reduce), split partial/rollup prompts (0.1.36)

Over-budget T2 synthesis (`plan_aggregate --node t2` → `needs_reduce=true`)
previously fell back to per-shard manual orchestration (one LLM turn per shard,
no timeouts / kill-stale / circuit breaker). The map stage now goes through the
same deterministic dispatcher as scout/t1/t3.

- `fanout_runner.py`: TIERS adds a `t2` row (enumerator = `plan_aggregate.py
  --node t2`; template `fanout/t2-task.md`; fanout agent
  `init-synthesis-fanout`; placeholder/path set
  `input_path`/`checkpoint_path`/`done_marker`/`failed_marker` +
  `shard_id`/`categories`/`repo`). New `--init-dir`/`--budget` flags; `--tier`
  closed set is now `scout|t1|t2|t3|sdr`. plan_path special case anchors the
  sidecar/liveness home at `<init-dir>` via `run_config.json` (design D5). Wave
  loop / ack state machine / timeouts / liveness / `--kill-stale` / circuit
  breaker / sidecar reused unchanged (tier-agnostic code path untouched).
- `plan_aggregate.py` `--node t2` stdout is now a **marker-aware legal fanout
  enumerator**: top-level `repo` (= `--init-dir` parent anchor) and marker-derived
  `total`/`done`/`failed`; each shard carries `failed_marker`; `pending[]`
  excludes shards whose `.done`/`.failed` marker exists (so the dispatcher's
  re-list converges and its circuit breaker reads marker truth);
  `summary_paths`/`shards` stay the full set (rollup + disclosure).
  `needs_reduce=false` path is byte-identical. `scout-merge` (hand-paged, a
  non-goal) is untouched.
- synthesis prompts split into three states: `init-synthesis.md` (whole,
  small-repo single-context, unchanged), `init-synthesis-partial.md` (per-shard
  bounded partial → structured shard summary; no cross-shard canonical/competing),
  `init-synthesis-rollup.md` (cross-shard merge over summaries → final
  inventory). New opencode primary agents `init-synthesis-fanout.md` /
  `init-synthesis-rollup.md`; claude resolves them via `--agents` inline JSON.
- orchestrator step face: `init-stage/t2.md` is dispatcher-first
  (`needs_reduce=false` → single-context; `true` → `--kill-stale` pre +
  `fanout_runner --tier t2` + `partial:true` re-dispatch + exit-2 manual
  fallback; map all `.done` → one rollup); `list_steps.py` t2 step carries the
  dispatcher call line; `discipline_core.py` t2 adds the soft-deadline
  re-dispatch path recipe; `resume_state.py --check` treats shard markers
  without the `synthesis.json.done` rollup terminal as a LEGAL intermediate
  (advisory note, no new step id).
- contract/install: `check_contracts.py` asserts the t2 tier set + new flags;
  `install.sh` self-check mirrors `t2-task.md`, the partial/rollup stage
  prompts, and the two new opencode agents; distribution-purity lint stays
  clean.

### Fixed — `/mgh-init` done-marker identity: forward marker-path judgment + dispatcher stall circuit breaker (0.1.35)

Root cause of the observed infinite T1 re-dispatch (32 overlong-id clusters
re-burned every wave, done=476/failed=5/pending=32 frozen): `_done_ids`/
`_failed_ids` recovered unit identity from each checkpoint record's `unit`
field (T1 records never carried one) with a filename-stem fallback — short ids
aligned by luck, overlong ids truncate under `_safe_name` so stem ≠ canonical
id → judged pending forever → `done+failed` never reached `total` → tier never
completed, and the dispatcher had no zero-progress cut so the orchestrator
re-dispatch loop burned the session budget.

- `list_clusters.py` / `list_scout_batches.py`: done/failed judgment rewritten
  to **forward marker-path computation** — walk the plan artifact's canonical
  unit ids (clusters[].cluster_id + `::shard-<n>` derivations / batches[].
  batch_id), encode the exact `.done`/`.failed` marker path with the SAME
  `_safe_name` the write side uses, `is_file()` = terminal. Identity NEVER from
  a record-body field or a filename stem. glob reverse lookup demoted to a
  fail-soft **orphan audit** (stderr `warn: orphan marker …`, enters no count).
  Encoding/judgment predicates are shared in `init_tier`
  (`safe_unit_filename`/`forward_marker_paths`/`forward_done_ids`/
  `forward_failed_ids`/`orphan_markers`) — single source, judgment and
  materialization cannot drift. Sharding decision extracted to `_shard_plan` +
  `collect_canonical_ids` so the canonical-id set and the materializer agree by
  construction. Existing `.json`+`.json.done` artifacts stay valid — a stuck
  run self-heals on the next `/mgh-init --resume` (no disk surgery).
- `fanout_runner.py`: zero-progress **convergence circuit breaker** —
  `--stall-waves` (default 2) consecutive fully-joined waves with equal
  done+failed snapshots and pending non-empty → stop dispatching, **exit 2**,
  stdout `stalled:true` + `stalled_pending[]` (per stuck unit: id + actual
  on-disk `.done`/`.failed` marker existence), stderr diagnosis recipe (stop
  re-dispatching; `resume_state.py --check`). A slow-but-advancing wave resets
  the window; `partial:true`/clean paths unchanged.
- `resume_state.py`: t1/scout tier done/failed counts now use the SAME forward
  predicates (imported, not copied) — count caliber and enumerator `pending[]`
  semantics agree by construction. `--check` additions: judged-pending-but-
  marker-name-on-disk = violation (id + path + do-not-re-dispatch recipe);
  orphan markers = advisory `notes[]`; touch-only `.done` (no record body) is a
  legal form, no longer a violation. Caliber disclosure in `--help`/docstring.
- `validate_t1_records.py`: T1 records now assert a root-level `unit` field
  (identity double-cover): non-empty + `unit == cluster_id` (violation on
  drift). Historical-form discrimination: no `unit` + forward marker exists =
  **warning** (历史形态,无需处理); no `unit` + no marker = violation.
  stdout gains a恒在 `warnings[]` field.
- Templates/agents/contracts: `fanout/t1-task.md`, `stages/init-induct.md`,
  both `init-induct` agent definitions carry the `unit` field instruction;
  both `mgh-init` shells + `init-stage/t1.md`/`scout.md` fragments carry the
  stall-breaker recipe and forward-judgment semantics; `cluster-enumeration`/
  `scout-enumeration`/`resume-state`/`t1-record-schema` contracts synced.
  `check_contracts.py` FANOUT_RUNNER_REQUIRED_FLAGS += `--stall-waves`.

### Changed — `/mgh-init` fanout lifecycle hardening (liveness + `--kill-stale` orphan-tree cleanup + stderr heartbeat + count-semantics doc)

- `fanout_runner.py` dispatch mode now writes an atomic liveness file
  `<init-dir>/fanout_runner.<tier>.pid` (body `{pid, started_ts, tier, host, cmdline,
  children[]}`; an orphan signal, NOT a lock) and removes it on any exit path
  (try/finally); a hard kill leaves a residual that `--kill-stale` disambiguates.
  Children spawn switched `subprocess.run` → `subprocess.Popen` (same capture/timeout
  semantics) so in-flight host-CLI child PIDs are recorded in `children[]` per wave
  and cleared at wave end.
- New `fanout_runner.py --kill-stale [--dry-run]`: inspects liveness residuals and
  kills what they record — form ① runner PID alive + cmdline matches `fanout_runner.py`
  → whole-tree kill (Windows `taskkill /pid <pid> /T /F`; POSIX process group); form ②
  runner dead/mismatched but a recorded `children[]` PID is alive + cmdline is the host
  CLI → kill each such tree (covers "orchestrator+runner hard-killed together, LLM
  children still burning tokens"). PID-reuse guard: cmdline double condition — mismatched
  PIDs are NEVER killed (residual file removed only). Destructive-op guard: a real kill
  with detected targets requires a prior `--dry-run` review (else exit 2 + recipe);
  no stale → `killed: []` exit 0 (idempotent, tier-agnostic). stdout
  `{"kill_stale": {"killed":[{pid,tier,kind}], "removed":[...], "none":bool}}`.
- stderr heartbeat: the dispatch loop prints `[fanout_runner <tier>] +HH:MM:SS wave=<k>
  unit=<id> <event> done=<d>/<total>` at every unit spawn / unit terminal status
  (ok|failed|timeout|crash) / wave end — live progress in the opencode TUI (merged
  stdout+stderr sliding tail, `docs/opencode-context-mechanics.md` §8) and in claude
  Bash results. stdout contract unchanged (single final JSON line).
- `resume_state.py` stdout gains additive `stale_fanout[]` (scan of
  `fanout_runner.*.pid`: `{tier, pid_file, pid, pid_alive, note}`; any alive PID's note
  carries the `--kill-stale --dry-run` recipe; `[]` when none — field always present).
  `--check` discloses alive residuals in `notes[]` as ADVISORY, never a gate.
- Count-semantics documentation (resume_state docstring + `--help` epilog): three
  measures — resume_state pure `*.json.done` marker glob count / list_clusters
  record-body unit dedup (shard-aware) / directory entry count (done + failed + record
  bodies) — equal only with no shards and no orphan markers; a mismatch (e.g. 472 vs
  491) is NOT data loss.
- Orchestrator wiring: both `mgh-init` shells' resume recipe now reads
  `stale_fanout[]` first (kill stale orphans before re-dispatch); the scout/t1/t3
  stage fragments prefix every fanout dispatch with the `--kill-stale --dry-run` →
  real-kill recipe. `tools/check_contracts.py` registers `--kill-stale`.

### Changed — `/mgh-init` scout merge lost-artifact recovery (exact note + `--check` mirror violation + fold-in re-run anti-pattern + contract correction)

- `resume_state.py` `_scout_step` now splits "all reader batches done but
  `scout_candidates.json` missing" into three merge/fold-in sub-states with precise recovery
  notes: merge marker absent → merge not run (regen credential then fold-in still pending);
  merge marker + `provenance.scout_merged` present → fold-in already run (`scout_merged=N`),
  regen serves ONLY as the completion credential (no downstream consumption, LLM drift
  harmless), NEVER re-run `merge_scout.py` fold-in, after regen `resume_state` re-derives
  `step=t1`; merge marker present + `scout_merged` absent → both credential and fold-in
  pending. All three next_actions stay `init-scout-merge` (honest re-generation — the unique
  recovery path); the note no longer misreports "merge marker absent" when the marker is on disk.
- `resume_state.py --check` gains the **mirror violation**: `checkpoints/scout/merge.json.done`
  + fold-in done + `scout_candidates.json` missing → exit 2 with a regen recipe (mirror of the
  existing "credential present but merge marker absent"); recovery (credential back on disk)
  → `--check` passes.
- `discipline_core.py` scout step `nevers` gains the fold-in re-run anti-pattern (`NEVER`
  re-run `merge_scout.py` fold-in when `provenance.scout_merged` is set — re-run is
  non-idempotent: same-file re-run zeroes `scout_merged`, drifted-file re-run double-appends).
- `core/contracts/init/resume-state.md` corrects the wrong "fold-in re-run idempotent/safe"
  claim and documents the three sub-state notes + the `--check` mirror violation.

### Changed — `/mgh-init` fan-out dispatcher generalized to all tiers (scout + t1 + t3)

- `fanout_runner.py` is now **tier-aware**: `--tier scout|t1|t3` (default scout — the
  existing scout call shape `--scout-plan/--checkpoints/--inputs-dir` is unchanged).
  All tier variation lives in a single `TIERS` mapping table (enumeration script +
  forwarded flags, task template, placeholder set, anchor-tree path fields, fanout
  agent name, marker `tier` value); the wave loop, ack state machine, three-level
  timeout invariant, sidecar, and audit copies are shared with zero per-tier branches.
  t1 requires `--clusters`/`--candidates`; t3 requires `--inventory`/`--format`/
  `--rules-dir`/`--target` (closed-set validation: missing flags → exit 2).
- **T1 scout-gate pass-through**: when `list_clusters.py` refuses with exit 2
  (`scout-incomplete-gate`), the dispatcher exits 2 and forwards its stderr recipe
  verbatim (finish the scout tier first) — a gate refusal is never swallowed into a
  generic error / crash re-dispatch loop.
- **T3 `repo` anchor**: `list_rule_jobs.py` stdout now carries top-level `repo`
  (resolved absolute `--target`, same shape as `list_clusters`) — the precondition
  for the dispatcher's anchor-tree checks and subprocess cwd on the t3 tier.
- **New task templates** `core/prompts/fragments/fanout/t1-task.md` / `t3-task.md`
  (same shape as `scout-task.md`: input-field declarations + stage-prompt load
  instruction only, zero behavior-rule duplication; t3 placeholder set uses
  `rule_path`, no checkpoint/slice fields).
- **opencode fanout agent clones** `init-induct-fanout.md` / `init-rulewriter-fanout.md`
  (`mode: primary`, verbatim clone of the stage agent + fanout annotation — the
  spike-verified headless-spawn path); claude side stays inline-JSON parameterized.
- **t1/t3 fragments are dispatcher-first** (`init-stage/t1.md`/`t3.md`): main path =
  one `Bash` `fanout_runner.py --tier …` with `--time-budget-ms` wiring +
  `partial:true` re-dispatch; exit 2 → manual-dispatch fallback preserved verbatim;
  T1→T2 validate gate and t3 assemble steps untouched. `list_steps.py` t1/t3
  invocations now point at the dispatcher; `discipline_core.py` t1/t3 recipes carry
  the soft-deadline re-dispatch discipline (per-call `timeout` > `--time-budget-ms`).
- **BREAKING (run-state file rename, one-time)**: the progress sidecar is now
  `fanout_progress.<tier>.json` per tier (scout: `fanout_progress.json` →
  `fanout_progress.scout.json`). Interleaved long runs (resume) would otherwise
  overwrite a single shared file with fake backwards progress. Old-name leftovers
  are harmless (run-state disclosure, not a contract artifact; not read by
  resume/init_manifest); install does not clean them. Man page + fragments updated.
- Contract lint asserts the new flags (`--tier`/`--clusters`/`--candidates`/
  `--inventory`/`--format`/`--rules-dir`/`--target`) + the three tier templates'
  existence; `install.sh` self-check covers the fanout tier payload (templates +
  opencode fanout agent clones).

### Changed — `/mgh-init` scout dispatcher long-run timeout calibration + progress visibility

- First large-repo live resume (900-batch scale, opencode host) exposed: the scout
  fragment's dispatcher call line never passed `--time-budget-ms`, so one `Bash` call
  ran 15 minutes with zero visible output and got hard-killed by the host shell
  per-call timeout (900s) — then the orchestrator's marker-based self-healing
  re-dispatched it into a kill/re-dispatch loop (each kill losing in-flight waves),
  with no way for a human to tell "slow" from "hung".
- **Timeout invariant, documented and wired** (`core/scripts/fanout_runner.py`):
  `call-timeout-s × drain headroom < time-budget-ms < host per-call timeout`
  (≥20% headroom per level). `--call-timeout-s` default 1800→**7200** — one batch =
  one full LLM subagent run on a slow intranet endpoint (minutes-level observed), so
  ~4× headroom; better-slow-than-killed: a killed batch leaves no marker, stays
  pending, and re-dispatching wastes a whole run. `--time-budget-ms` help now carries
  the recommendation (host per-call timeout × 0.8; opencode 900000ms host → 720000,
  claude Bash 600000ms cap → 480000). The soft deadline deterministically fires
  BEFORE the host hard kill (stop starting waves → drain in-flight → exit 0 +
  `partial:true`), turning every re-dispatch into a clean early-exit instead of a
  hard kill. Deliberately NO runtime cross-validation of the two flags (budget <
  call-timeout at worst delays exit by one call-timeout; still clean, still
  resumable — a hard check would manufacture fake failures under legal combos).
- **Progress sidecar (human-facing, zero orchestrator involvement)**: the dispatcher
  atomically writes `<init-dir>/fanout_progress.json` (stdlib tempfile + os.replace)
  after every wave and on every exit, with `{ts, host, total, done, failed, pending,
  wave, waves_run, wave_done_avg_s, eta_batches, state}`, `state ∈ {running,
  exited-partial, exited-clean}`. Watch it from a second terminal
  (`Get-Content -Wait`); `done` not moving for minutes with `state:running` = the
  hang signal for a HUMAN to act on. Counts derive from the same snapshot as the
  stdout summary (unit test asserts they agree); write failures warn on stderr and
  never break the run. The orchestrator and any agent NEVER read it (not a truth
  source; `resume_state.py`/`init_manifest.json` neither read nor validate it).
- **Out-of-host manual takeover (escape hatch, documented)**: dispatcher and
  orchestrator share the disk markers as the only truth source (naturally
  mutexed), so for large-repo long runs a human may run the same dispatcher
  command directly in a terminal (no host timeout clamp, per-wave stderr readable,
  sidecar still written), then `/mgh-init --resume` back in the session.
- Wiring: `core/prompts/fragments/init-stage/scout.md` call line now exemplifies
  `--time-budget-ms` + the MUST-be-below-host-timeout invariant + the manual-run
  exit; `core/scripts/discipline_core.py` `scout-fanout-dispatcher` recipe gains
  the re-dispatch timeout discipline (per-call `timeout` > `--time-budget-ms`);
  `docs/man/mgh-init.md` risk section explains long-run visibility in plain
  language. Tests: `tests/test_fanout_runner.py` grows default-value/invariant-doc
  assertions, sidecar existence/state/count-agreement cases, and fragment/recipe
  timeout-relation doc assertions. No disk schema change; zero new runtime deps.

### Added — `/mgh-init` scout wave dispatcher (`fanout_runner.py`, zero-LLM fan-out)

- The scout tier's wave loop (take pending → spawn N subagents → collect acks → page)
  moves out of orchestrator LLM turns into a deterministic stdlib leaf script
  `core/scripts/fanout_runner.py`. The orchestrator makes ONE `Bash` call (+ re-dispatch
  the same command while `partial:true`); inside, the script consumes
  `list_scout_batches.py --materialize` stdout, builds each subagent's task message from
  a FIXED template + verbatim field substitution, spawns host-CLI subprocesses in waves
  (`--wave`, default 5; ThreadPool + per-call timeout), parses bounded acks
  (`ok`/`oversize`/`failed`), and re-derives pending from disk markers after each wave.
  Task-message path-spelling failures (format drift / drive-root drift / underscore-name
  hallucination) become impossible by construction; wave boundaries cost zero LLM turns
  (~1–3K tokens/wave saved on large repos).
- Host spawn mapping (spike-verified on both hosts): opencode →
  `opencode run --agent init-scout-fanout "<task>"` (new `mode: primary` hidden twin of
  init-scout — `opencode run` refuses `mode: subagent` primaries and silently falls back
  to the default agent); claude → `claude -p "<task>" --agents <inline JSON>
  --allowedTools …` (stdin redirected). Host detection: `--host` explicit > opencode in
  PATH > claude in PATH; neither → exit 2 + fallback recipe and the orchestrator falls
  back to the existing per-wave manual dispatch (behavior unchanged, kept verbatim in the
  scout fragment as the fallback path).
- New task-message template `core/prompts/fragments/fanout/scout-task.md` (input fields +
  stage-prompt load instruction only; zero behavior-rule duplication — behavior stays in
  `stages/init-scout.md`). Per-spawn audit copies land at
  `<inputs-dir>/<batch_id>.task.md`; `--purge-audit --dry-run` lists them (list-only
  CLI surface; deletion via host shell after review).
- Dispatcher-side path-drift interception: every path field is `Path.resolve()`-anchored
  against `repo` BEFORE spawn; out-of-tree → that unit gets a `.failed` marker
  (reason=path-drift) and is never spawned (deterministic dual of the reader-side
  poisoned-input rejection). `.done`/`.failed` marker semantics, `--resume` idempotence,
  soft `--time-budget-ms` early-exit (`partial:true`, exit 0), and stdout-JSON /
  stderr-diagnostics split all follow the existing leaf-script contracts (R5.3/R5.4).
- Affected: `core/scripts/fanout_runner.py` (new) + `list_steps.py` (scout step now
  points at the dispatcher invocation) + `discipline_core.py` (scout gains a
  dispatcher-first path recipe); `core/prompts/fragments/fanout/scout-task.md` (new) +
  `fragments/init-stage/scout.md` (dispatcher-first dispatch section; manual path kept
  as fallback) + `stages/init-scout.md` + mirrored `releases/{claude-code/agents,
  opencode/agent}/init-scout.md` (source-of-fields wording: dispatcher path);
  `releases/opencode/agent/init-scout-fanout.md` (new); both `mgh-init.md` shells
  (component table row); `install.sh` self-check list + `tools/check_contracts.py`
  (fanout_runner flag assertions); `tests/test_fanout_runner.py` (new). Zero new runtime
  deps (stdlib subprocess/concurrent.futures); no on-disk schema change.

### Added — plain-language doctrine (audience declaration + human-facing assets)

- R3 now declares an **audience** for every artifact (human / agent / dual): human-facing
  files (man pages, glossary, proposal preambles) follow plain-language norms
  (phenomenon→cause→fix, terms defined on first use); agent-facing discipline (RFC-2119,
  NEVER chains, flag tables) stays byte-stable and is explicitly NOT softened. Proposals
  open with a `> **人话序**` blockquote (~200–300 chars: phenomenon → root cause → what
  changes → how to verify); `tools/check_plain_language.py` (stdlib) enforces the
  deterministic subset — missing preamble fails loud (exit 2), known coined-jargon and
  english-atom density WARN (exit 0), scoped to human-facing files only
  (`tools/plain_language_allowlist.txt` exempts 5 pre-doctrine changes).
- New human-facing assets: `docs/glossary.md` (seeded ~45 terms; "define before use" for
  human-facing prose) and `docs/man/<cmd>.md` ×5 (plain-language pages: what it does /
  what it touches / what it produces / honest boundaries). install.sh now lands
  `docs/man/` into target projects; the 10 command shells (5 × claude/opencode) each
  carry a one-line human-reader pointer.
- `check_distributed_purity.py::SCAN_DIRS` gains `docs/man/` — shipped md set stays
  identical to install.sh globs (166 files scanned clean). Regression:
  `tests/test_plain_language.py` (13 tests) + two new purity assertions (man pages clean;
  pointers present + clean).

### Changed — `/mgh-sast` pins s4 big-file slice outputs in-tree + absolute tool-script paths
- The s4 deep-dive big-file slice output (`chunk_sources.py --out`) — the sast-side fan-out
  gap left open by `harden-mgh-init-slice-and-tool-pinning` (its Non-Goals deferred sast to
  this adoption) — is now pinned to the project tree. `list_chunks.py` stdout `pending[]`
  each gains an additive ABSOLUTE `slice_dir` = `<target>/security-scan/slices/s4/<safe(chunk_id)>/`
  (`<命令输出目录>` = grandparent of `--checkpoints` = `<target>/security-scan`, same root as
  `checkpoint_path`; `_safe_name` sanitizes `/ \ :` — a no-op on clean vvah `chunk-NN` ids,
  defensive parity with init T1's NTFS-ADS guard). The orchestrator passes `slice_dir` verbatim;
  the sast-deepdive subagent writes `chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json`
  and re-reads that exact path — NEVER a relative `--out`, NEVER a cwd/system-temp-derived path
  (opencode subagent cwd can be `…\Temp\opencode\` → out-of-tree slice → unauthorized-`Read`
  prompt), NEVER out-of-tree. `chunk_sources.py` itself stays cwd-agnostic (no tree assumption);
  the pin lives in the contract + prompt layer.
- s4 deep-dive subagents now use the ABSOLUTE tool-script path pinned to the current install:
  `list_chunks.py` stdout gains a top-level `scripts_dir` = `Path(__file__).resolve().parent`
  (the running install's `<mgh-core>/scripts/`); the orchestrator reads it in s4 fan-out and
  passes `<scripts_dir>/chunk_sources.py` verbatim. Subagents NEVER use a bare `chunk_sources.py`
  name or a relative `.claude`/`.opencode/mgh-core/scripts/…` path (multi-layer install → can
  resolve to an older copy). Tool base is taken from `list_chunks.py` (s4 already calls it), not
  init-only `list_steps.py`; install-dir stays independent of `--target`.
- Affected: `core/scripts/list_chunks.py` (additive per-pending `slice_dir` + top-level
  `scripts_dir`); `core/contracts/sast/fanout-enumeration.md` + `core/contracts/init/unit-inputs.md`;
  `core/prompts/stages/s4-system.md` + mirrored `releases/{claude-code/agents,opencode/agent}/
  sast-deepdive.md`; both `mgh-sast.md` shells (s4 fan-out `slice_dir`/`scripts_dir` transmission,
  absolute `chunk_sources` recipe); `install.sh` self-check now also verifies the sast pipeline
  scripts (`list_chunks`/`list_verify_jobs`/`prefilter`/`dedup`/`emit_sarif`) are co-located.
  Additive stdout fields — no on-disk schema change (`checkpoint_path`/`input_path`/exit-code
  semantics unchanged); lite shell omits `slice_dir` (never fans out); zero new runtime deps.

### Changed — `/mgh-init` pins big-file slice outputs in-tree + absolute tool-script paths
- The scout/T1 big-file slice output (`chunk_sources.py --out`) — the one fan-out-adjacent
  path NOT already pinned by `harden-mgh-init-fanout-output-paths` — is now pinned to the
  project tree. `list_scout_batches.py` / `list_clusters.py` stdout `pending[]` each gain an
  additive ABSOLUTE `slice_dir` = `<target>/.mgh-init/slices/<tier>/<safe(unit_id)>/`
  (`<tier>` ∈ `scout`/`t1`; `<init-dir>` = grandparent of `--checkpoints`, same root as
  `checkpoint_path`; `cluster_id` `::` NTFS-ADS-sanitized via the existing `_safe_name`).
  The orchestrator passes `slice_dir` verbatim; the scout/induct subagent writes
  `chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json` and re-reads that exact path —
  NEVER a relative `--out`, NEVER a cwd/system-temp-derived path (opencode subagent cwd can
  be `…\Temp\opencode\` → out-of-tree slice → unauthorized-`Read` prompt), NEVER out-of-tree.
  `chunk_sources.py` itself stays cwd-agnostic (no tree assumption); the pin lives in the
  contract + prompt layer.
- Fan-out subagents now use the ABSOLUTE tool-script path pinned to the current install:
  the orchestrator derives it in step 0 from `list_steps.py` stdout `script_abs` (`__file__`-
  derived = the running install's `<mgh-core>/scripts/`) and passes it verbatim. Subagents
  NEVER use a bare `chunk_sources.py` name or a relative `.opencode`/`.claude/mgh-core/
  scripts/…` path — under a multi-layer install a relative tool path can resolve to a
  DIFFERENT (older) copy. Install-dir stays independent of `--target` (install in A, analyze B).
- Affected: `core/scripts/list_scout_batches.py` + `list_clusters.py` (additive `slice_dir`);
  `core/contracts/init/{scout-enumeration,cluster-enumeration,unit-inputs}.md`;
  `core/prompts/stages/init-{scout,induct}.md` + mirrored `releases/{claude-code/agents,
  opencode/agent}/init-{scout,induct}.md`; both `mgh-init.md` shells (step-0 tool-base recipe,
  fan-out `slice_dir` transmission, `chunk_sources` example → absolute path + `<slice_dir>`
  `--out`). Additive stdout field — no on-disk schema change (`checkpoint_path`/`input_path`/
  exit-code semantics unchanged); zero new runtime deps. mgh-sast's s4/deepdive same-shape gap
  is deferred to a follow-up `harden-mgh-sast-slice-path-pinning`.

### Changed — `/mgh-init` skips test source trees during discovery (`--include-tests` opt-in)
- The discovery file-enumeration layer (`expand_scope.walk_sources` / `collect_dir`, the
  single chokepoint consumed by regex candidates, `skeleton.json`, the call graph, and scout
  targets) **additionally** prunes test source trees by default, mirroring the existing
  dot-prefix prune. A test tree hits when the repo-relative posix path starts with
  `src/test/` / `src/tests/` (Maven/Gradle/Kotlin) **or** a directory segment (not filename)
  is in `{tests, __tests__, __mocks__, spec, specs}`. Bare singular `test` is **deliberately
  not** matched (collision risk: production `com/acme/test/` helper packages, Go `test`
  packages). Test code is net noise for finding existing **production** controls — mocks/stubs
  (`@MockBean SecurityConfig`, `mock(SecurityChecker)`) materialize pseudo-controls,
  deliberately-vulnerable fixtures (VulnerableApp, disabled-TLS / widened-CORS / placeholder-
  key / dummy-JWT-issuer test configs) hit as real control features, and test code never ships.
- `discover_controls.py` gains `--include-tests` (default off = exclude; passing it re-includes
  test sources, equivalent to before this change). Polarity asymmetry (design D2): the shared
  `walk_sources`/`collect_dir` default `include_tests=True`, so callers that don't pass it —
  including `mgh-sast`'s `build_call_graph` — stay byte-identical; only `discover_controls`
  (mgh-init) opts into exclusion. Excluding test code as an mgh-sast default is a separate
  later change (not bundled here).
- discover stdout summary (partial + full) gains `tests_skipped` (non-negative int), parallel
  to `dotfiles_skipped`; `controls_candidates.json` wrapper gains an additive top-level
  `tests_skipped` so `discover_controls.py --check` can validate it (R5.9: fail-loud exit 2 if
  missing/non-int/negative). `write_runconfig.py` records `include_tests` in `run_config.json`
  for stateless `--resume`. Both `mgh-init.md` shells (claude + opencode, mirrored verbatim)
  gain the flag-table row, the `write_runconfig`/`discover_controls` call examples, and a test-
  tree honesty-boundary line in `init_manifest.json::boundaries[]` / `report.md`. No disk
  schema change to `controls_candidates`/`clusters`/`skeleton` Candidate records (only an
  additive wrapper counter); no LLM-stage prompt change (prune is at the deterministic layer).

### Changed — `/mgh-init` tolerates partial fan-out unit failure (`.failed` terminal marker)
- A confirmed fan-out unit failure (scout reader batch / T1 cluster / T3 category subagent
  returning the existing `failed <reason>` ack) is now **terminal and non-blocking**: the
  orchestrator writes a `.failed` marker sibling to `.done` (`<checkpoint_path>.failed`, body
  `{unit,reason,tier}`), the unit is excluded from resume `pending` (NOT retried), and the tier
  completes when `done + failed >= total` (not `done >= total`). `list_clusters.py` /
  `list_scout_batches.py` / `list_rule_jobs.py` emit a `failed` count + a per-item absolute
  `failed_marker` (parallel to `done_marker`, verbatim-transmitted — never self-assembled);
  `resume_state.py` derives `tiers{<tier>}.failed`, surfaces non-zero failures in `notes[]`
  (a rate > half the tier is a loud `WARNING` advisory, never a gate), and `--check` flags a
  unit carrying both `.done` and `.failed` as an ambiguous-terminal violation (exit 2).
  Failures are disclosed in `init_manifest.json::failures` (per-tier `{done,failed,total}`) +
  `boundaries[]` + `report.md`, counts read from disk (`resume_state`/`list_*` stdout), never
  conversation memory. A crash without an ack leaves no marker → unit stays pending → retried
  (crash ≠ confirmed failure); escape hatch = delete the `.failed` marker then `--resume`.
  No new CLI flag (R5.1 surface frozen; `.failed` read by glob, written via `Write` to the
  verbatim `failed_marker` path). Stage prompts + dual-shell agent defs updated to "touch
  nothing on failure, emit only the `failed` ack". Original (no `.done` ⇒ tier never completes
  ⇒ pipeline blocks, or indiscriminate retry) is the failure-shape being fixed.

### Changed — `/mgh-init` fan-out waves run to completion (no scale-driven mid-run interruption)
- Both `mgh-init.md` shells (claude + opencode, mirrored verbatim) gain a run-to-completion
  directive in the Re-entrancy & compaction section: during a fan-out wave (scout reader /
  T1 induct / T3 rulewriter) the orchestrator **MUST NOT** pause to ask the user whether to
  split / skip / abort on account of scale, and **SHALL** iterate the `list_*` pending
  work-list at `max_concurrent` until `pending` is empty. Scale and boundary facts (large
  fan-out count, partial coverage, `.failed`/skipped units, residual blind spots) **SHALL**
  flow into the existing disclosure channel — `init_manifest.json::boundaries[]` + `report.md`
  + `resume_state.py` `notes[]` — never as a mid-run blocking question; counts are read from
  disk (`resume_state.py`/`list_*` stdout), never conversation memory. The legitimate
  **pre-run** i0 advisory (`--large-repo-threshold` → suggest `--scope`+`--merge`, before
  tokens are spent) is explicitly preserved and distinguished from the mid-wave directive.
  Prompt-wording only: no new CLI flag, script, contract, hook, or stage-prompt change.

### Changed — runtime hook enforcement hardened (env-or-sentinel activation + runtime scripts read-only + init write confinement)
- **Disk-sentinel activation closes the opencode reliability boundary.** The shared guard
  `block_adhoc_scripts.py` now activates inside an mgh run-domain when **EITHER** env
  `MGH_{INIT,SAST,SRA,SRR}_ACTIVE=1` **OR** a disk sentinel `<cwd>/<run-root>/.active` exists
  (init→`.mgh-init`, sast→`security-scan`, sra→`.mgh-sra`, srr→`.mgh-srr`). The opencode `.ts`
  plugin process does not inherit mid-session bash-exported env, so env-only activation left the
  opencode guard dormant for a whole run; the sentinel (visible to the plugin via disk) closes
  that hole. Sentinel JSON `{domain,target,out_roots[],v}`, written by the orchestrator at step 0
  via Bash, removed on completion/clean-stop. New contract `core/contracts/hooks/runtime-enforcement.md`;
  new shared spec `runtime-hook-enforcement` (single source replacing scattered per-command hook wording).
- **Runtime scripts read-only (whitelist removed + script-extension set).** When active the guard
  blocks `Write`/`Edit` of any extension in `{.py,.ps1,.sh,.bash,.zsh,.bat,.cmd,.ts,.js,.mjs,.cjs}`
  with **no** path whitelist — the prior `core/scripts`/`mgh-core/scripts` + `tests`/`tools`/`hooks`
  exemptions only mattered while inactive (install/dev), at which point `main()` already exits 0.
  Leaf scripts are read-only for the orchestrator at runtime. Closes the "agent edits
  `list_clusters.py`" and "`process_*.ps1` leaks past `.py`-only" failure shapes.
- **`/mgh-init` write confinement to sanctioned subtrees.** The init domain upgrades
  out-of-tree interception to a positive allowlist: `Write`/`Edit` MUST land in
  `<target>/.mgh-init/**` / `.claude/rules/**` / `docs/security-controls/**` / `AGENTS.md` /
  sentinel `out_roots[]` — so in-tree root pollution (`temp_clusters*.json`, `process_*.ps1`) also
  fails loud. sast/sra/srr retain the out-of-tree check. `MGH_TARGET` precedence: env > sentinel.target
  > degrade. Sentinel `target` is sourced from Python leaf-script stdout (Windows-native; never bash
  `pwd`, whose MSYS `/c/…` mis-resolves in pathlib).
- **Tests:** `test_block_adhoc_scripts.py` flips the whitelist PASS tests to BLOCK, adds sentinel
  activation (env unset), sentinel-carried-target subtree block, script-ext set, init root-pollution
  block + sanctioned-subtree/out_roots pass, stale/degrade; `test_opencode_hook_parity.py` adds
  byte-identity-of-new-logic + opencode sentinel-activation checks. The `.ts` shim stays glue-only.

### Added — `/mgh-init` context resilience (re-entrant resume + bounded ack + aggregate hard-budget)
- **Re-entrant orchestrator resume state.** New `core/scripts/resume_state.py` derives the
  pipeline's current step + exact next action **purely from on-disk artifacts** (`<target>/.mgh-init/`
  products + per-tier `.done` + `run_config.json`), independent of conversation memory. compact /
  crash / new-session collapse into one recovery path: `/mgh-init --resume` whose **first action is
  `resume_state.py`**. `--check` validates on-disk self-consistency (exit 2 on violation). New
  `core/scripts/write_runconfig.py` atomically writes the start-state intent `run_config.json` at
  step 0 so resume is stateless of re-typed flags. See `core/contracts/init/resume-state.md`.
- **Bounded subagent return-to-orchestrator ack.** All 9 `init-*.md` stage prompts + dual-shell
  `agents/init-*.md` declare the final message as a single bounded ack (`ok <abs path> <count>` /
  `oversize` / `failed`) — NEVER echo the record body (which monotonically bloated orchestrator
  context across fan-out). The 5 whole-tier stages (survey/scout-merge/scout-audit/synthesis/
  rules-consistency) also moved to orchestrator-given absolute-path-verbatim output.
- **Aggregate hard-budget via map-reduce.** New `core/scripts/plan_aggregate.py` makes
  `--max-aggregate-bytes` a HARD gate at T2 (`init-synthesis`) and scout-merge (`init-scout-merge`):
  ≤ budget → single-context (byte-identical, zero regression); > budget → two-pass map-reduce
  (per-shard ≤ budget → single rollup over summaries). Replaces the prior "disclose + fallback"
  soft boundary for those two nodes (T4 rules-consistency remains soft-bounded). See
  `core/contracts/init/aggregate-sharding.md`.
- **Re-entrancy & compaction section** in both `mgh-init.md` shells: disk is the progress source of
  truth, conversation memory is only a cache; resume/compact first action is `resume_state.py`;
  context-tight clean-stop + new-session resume is preferred over manual `/compact`.
- `AGENTS.md` R5.4 / R5.5① sharpened (orchestrator-level re-entrant resume state + step-query
  recipe). `init_manifest.json` version bumped 6 → 7; `boundaries[]` reflects the hard-threshold.

### Changed
- **Restructured `AGENTS.md` R5(Agent 工具命令稳定性)for readability — 零规范内容删除。**
  跨处复述的机制去重到单一归宿(长跑可恢复 → R5.4;opencode env 不继承 → R5.7 段 B;退出码 `0/1/2`
  定义 → R5.3(b) 单次);R5.7 拆「段 A 评估方法论 + 段 B hook 强制闭环」;R5.3(b) fan-out 提升为子项;
  修 R5.5 ⑤ 孤儿 indent;合并重复的「理由须随规保留」样板为前言一行;修剪纯回声 `承 R5.x`。加 R5 头部
  「强制面索引表」。编号 R5.1–R5.10 不变。详见 change `simplify-agents-r5`。

### Added
- **Bounded per-request context for `/mgh-sra` fan-out (`request-context-budget` adoption).**
  `prepare_augment.py` now materializes each capability's complete input to its own bounded file
  and the orchestrator carries only a slim, paged work-list (it no longer whole-reads
  `change_context.json` into its context). New on `prepare_augment.py`: `--materialize <dir>`
  (writes `<change-root>/.mgh-sra/inputs/augment/<cap>.input.json` = that cap's requirements +
  per-cap business surface + the `candidate_controls` file_overlap slice + memory; `pending[]`
  becomes a slim envelope carrying `input_path`/`bytes`/`oversize`), `--offset`/`--limit` paging
  reporting `effective_limit`/`shrunk`, and `--max-unit-bytes` (192 KB; an oversize capability is
  flagged + recipe'd to split the change / `--focus` narrow — never sharded, the capability is the
  a3 atom) / `--orch-budget-bytes` (64 KB; a page over it is auto-tightened). `sra-augment` reads
  its own `input_path` (NEVER the whole `change_context.json`); the full `change_context.json`
  stays on disk for the a2 single-context whole-change scan. `sra-clarify`/`sra-consistency` gain a
  P0 soft-boundary disclosure guardrail for their aggregate inputs (`--max-aggregate-bytes`,
  256 KB — over it they advise `--focus`/split-change and surface it in
  `sra_manifest.json::boundaries[]`, non-blocking). `tools/check_contracts.py` asserts the new
  flags (R5.1); tests cover per-cap materialize (file_overlap slice)/paging/oversize + the
  whole-read discipline regression. (This lands the engine-stage `input_path` consumption the srr
  adoption deferred; the cross-cutting `request-context-budget` spec is the contract.)
- **Bounded per-request context for `/mgh-srr` fan-out (`request-context-budget` adoption).**
  The srr intake adapter now materializes each review unit's complete input to its own bounded
  file and the orchestrator carries only a slim, paged work-list (it no longer whole-reads the
  sra-shape `change_context.json` into its context). New on `ingest_requirements.py`:
  `--materialize <dir>` (writes `<out>/inputs/augment/<unit>.input.json`; `pending[]` becomes a
  slim envelope carrying `input_path`/`bytes`/`oversize`), `--offset`/`--limit` paging reporting
  `effective_limit`/`shrunk`, and `--max-unit-bytes` (192 KB; an oversize unit is flagged +
  recipe'd to `--split`/narrow the doc — never sharded, the unit is the review atom) /
  `--orch-budget-bytes` (64 KB; a page over it is auto-tightened). The reused sra engine stage
  reads its own `input_path`; the full sra-shape `change_context.json` stays on disk for stage
  consumers. `render_report.py` gains `--max-aggregate-bytes` (256 KB; P0 soft boundary — over
  it the aggregate draft input is disclosed in `srr_manifest.json::boundaries[]` + the report,
  non-blocking). `tools/check_contracts.py` asserts the new flags (R5.1); tests cover
  materialize/page/`--split`/oversize + the whole-read discipline regression. (Engine-stage
  consumption of `input_path` lands with the `/mgh-sra` adoption; intake-side lands independently.)
- **Bounded per-request context for `/mgh-sast` fan-out (`request-context-budget` adoption).**
  The s4/s6 enumeration scripts now materialize each fan-out unit's complete input to its own
  bounded file and the orchestrator carries only a slim, paged work-list (it no longer
  whole-reads `s3_chunks.json`/`s5_filtered.json` into its context). New on `list_chunks.py`:
  `--materialize <dir>` (writes `<repo>/security-scan/inputs/s4/<chunk>.input.json` = that chunk's
  `files[]` + `threat_id` + `hypothesis` + `needs_slice`; `pending[]` becomes a slim envelope
  carrying `input_path`/`bytes`/`oversize`/`needs_slice`), `--offset`/`--limit` paging reporting
  `effective_limit`/`shrunk`, `--max-unit-bytes` (192 KB; an oversize chunk — input over budget OR
  a source file over `--big-file-bytes` — is flagged + its big files listed in `needs_slice[]` for
  `chunk_sources` slicing, never the whole file fed to the LLM) / `--orch-budget-bytes` (64 KB; a
  page over it is auto-tightened), plus `--repo`/`--big-file-bytes` (200 KB) for computing
  `needs_slice`. `list_verify_jobs.py` mirrors this for s6 (`inputs/s6/<finding_id>.input.json` =
  the full finding record; an oversize finding is flagged + recipe'd to `--scope` narrow — never
  sliced, the finding is the s6 verify atom). `sast-deepdive`/`sast-verify` read their own
  `input_path` (NEVER the whole `s3_chunks.json`/`s5_filtered.json`). `mgh-sast.md` (claude +
  opencode) gains the orchestrator-discipline recipe, the s4/s6 materialize→page→pass-`input_path`
  flow, the `--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes` flag table (s1 scope /
  s2-s3 hypothesis aggregate = P0 soft boundary — over it advise `--scope`/`--diff` and surface in
  `run_manifest.json::boundaries[]` + `report.md`, non-blocking), and the `inputs/` output.
  `tools/check_contracts.py` asserts the new flags (R5.1); tests cover per-chunk/per-finding
  materialize (needs_slice/oversize)/paging + the s3/s5 whole-read discipline regression. (The
  cross-cutting `request-context-budget` spec is the contract; the `block_adhoc_scripts` hook
  already covered `MGH_SAST_ACTIVE` from the foundation — no hook change.)
- **`docs/r5-plain-language.md`**(dev-only,不分发)—— R5.1–R5.10 大白话逐条(说什么 / 为什么 /
  违反后果 / 兜底),作 AGENTS.md(AI 面向)的人类桥梁 + 去重后防单点灭失的第二副本。

### Fixed
- **`/mgh-init` scout→merge fold-in aborted with `KeyError: "file"` when a scout candidate
  lacked its `file` field** (raw traceback, the whole merge halted) — unlike `category`, which
  `merge_scout._normalize` already tolerated (skip + warn). `file` is now treated the same as
  `category`: a missing/empty `category` OR `file` makes `_normalize` return `None`, the caller
  skips that one candidate and warns (naming which required field is missing — `category` /
  `file` / both, plus the candidate `index` and any available `file:line`), and the merge
  continues. All `_normalize` field access is now `.get` (no direct-indexed required field
  remains). Defense-in-depth for when `merge_scout.py --check` is bypassed (orchestrator
  context pressure / a hand-crafted malformed `scout_candidates.json`); the `--check` gate,
  stdout/stderr/exit-code CLI contract are unchanged. Covered by `tests/test_merge_scout.py`.
- **`/mgh-init` T1 subagent `write_text` of `checkpoint_path` failed with `OSError [Errno 22]
  Invalid argument` on Windows NTFS** when `cluster_id` (or `<cid>::shard-<n>`) contained `::`
  — NTFS's Alternate-Data-Stream separator. `list_clusters.py::_paths` built the checkpoint
  filename from the **raw** `unit_id`, unlike the input filename which was already
  `_safe_name`-sanitized (`/ \ :` → `_`) — a same-source latent bug (the test helper `_mark_done`
  already sanitized, diverging from production). `_paths` now encodes the filename component via
  `_safe_name` (same function, same paradigm as `_write_unit`/`_shard_hit_count`); the canonical
  `unit_id` (with `::`) is preserved verbatim as the slim-envelope `cluster_id` field and the
  checkpoint record's `unit` field, so done detection / resume matching (which reads `unit`, not
  the filename) are unaffected. See `core/contracts/init/cluster-enumeration.md`,
  `openspec/changes/fix-mgh-init-ntfs-unit-filename/`. Covered by `tests/test_init_clusters.py`.

### Dev-meta
- **Q1 决策:**AGENTS.md 改动**不**触发分发版本 bump —— AGENTS.md 是研发手册,在 install 分发集之外
  (`SCAN_DIRS` 排除;无 VERSION 字段,版本追踪仅 CHANGELOG)。记于此,不作为 release 切出。
- **行数实际:**R5 段 97 → ~114 行(未达 design 估的 70–75)。强制面索引表(~13 行)抵消了去重收益;
  真实收益是可读性(去重 + 拆段 + 索引 + 修孤儿),非行数。

## [0.1.12] — 2026-07-27

### Added
- **Bounded per-request context for `/mgh-init` fan-out (`request-context-budget`).** The
  orchestrator no longer whole-reads a multi-unit aggregate into its context (observed: an
  opencode host reading the 426 KB `t1_pending`-style work-list whole, bloating every
  subsequent model request). Every fan-out tier now materializes each unit's complete input
  to its own bounded file and the orchestrator carries only a slim, paged work-list. New
  three-tier byte budgets (defaults; unit = bytes, a conservative upper bound for tokens):
  - **Per-unit materialization** — `list_clusters` / `list_scout_batches` / `list_rule_jobs`
    gain `--materialize <dir>`: each T1 cluster / scout batch / T3 category's complete input
    record is written to `<target>/.mgh-init/inputs/<tier>/<unit>.input.json` (idempotent,
    `--resume`-reused). `pending[]` becomes a slim envelope carrying `input_path` / `bytes` /
    `oversize` (no variable-length payload). The stage subagent (`init-induct` / `init-scout`
    / `init-rulewriter`) reads its own `input_path`; the orchestrator only passes the path.
  - **Configurable byte budgets** — `--max-unit-bytes` (192 KB; oversize clusters sharded
    into `<cluster_id>::shard-<n>`, scout batches / T3 categories flagged `oversize`),
    `--orch-budget-bytes` (64 KB; a work-list page exceeding it is auto-tightened with
    `shrunk:true`), `--max-aggregate-bytes` (256 KB; T2/merge/T4 aggregate stages — P0 soft
    boundary: disclose + advise `--scope`/`--merge`; layered reduction is a later change).
  - **Paging** — all three enumeration scripts gain `--offset` / `--limit` and report
    `effective_limit` / `shrunk`; the orchestrator pages rather than loading the whole list.
  - **Defense-in-depth hook** — `block-adhoc-scripts` (both platform twins, byte-identical;
    the opencode `.ts` shim stays pure glue) now also blocks a shell whole-read
    (`cat`/`head`/`tail`) of a multi-unit aggregate in any of the four run-domains, with a
    recipe pointing at `list_* --materialize` `input_path`. The structural fix is the primary
    lever; the hook is residual defense. (`/mgh-sast` / `/mgh-sra` / `/mgh-srr` adoption is
    deferred to follow-up changes — this release lays the cross-cutting capability and the
  `init` reference implementation.)
- **New contract** `core/contracts/init/unit-inputs.md` documenting the per-unit
  materialization schema and the four-command path conventions.
- **`init_manifest.json` version 5 → 6** (additive): `boundaries[]` gains the request-context-
  budget disclosure.

### Changed
- `init-induct` / `init-scout` / `init-rulewriter` prompts: input is now the bounded
  `input_path` file (with a NEVER-whole-read-aggregate hard rule). `init-synthesis` /
  `init-scout-merge` / `init-rules-consistency` gain a P0 aggregate-context-budget guard.
- `tools/check_contracts.py` asserts the three `list_*` scripts declare the new flags and
  the `/mgh-init` shells advertise `--max-aggregate-bytes`.

## [0.1.11] — 2026-07-23

### Added
- **Discover resilience against host shell timeouts (`/mgh-init`).** `discover_controls.py`
  no longer assumes a single host call finishes — it checkpoints a built call graph under
  `<out>/cache/` and resumes across runs, so a large repo (or an opencode/claude shell
  timeout mid-scan) is no longer total loss. New flags (all additive; defaults preserve
  prior behavior):
  - **Call-graph cache** — `<out>/cache/callgraph.json` + `manifest.json` (per-source
    `mtime`/`size` freshness). A re-run with an unchanged repo hits the cache and skips
    the two regex passes (stdout `cache_hit: true`). `--rebuild-cache` forces a rebuild
    (this flag was already advertised in the shells but was previously a dangling
    contract — it is now real and `--help`-exposed).
  - **Scan resume** — `<out>/cache/scan_progress.json` checkpoints every
    `--progress-every` files. `--resume` reuses the cache and continues scanning from the
    checkpoint without rescanning; deterministic + idempotent (resume == one-shot candidate set).
  - **Soft time budget** — `--time-budget-ms <N>` (default `0` = off). When set, discover
    stops at a safe boundary (after the call graph is built; every `--progress-every`
    files — never mid-write), persists the cache + checkpoint, and exits **0** with stdout
    `partial: true` + `resume_hint`. The orchestrator re-dispatches `--resume` until
    `partial: false`.
  - **Atomic writes** — all product JSON (`controls_candidates`/`clusters`/`skeleton`/
    `cache/*`) is written `.tmp` + `os.replace`, so a SIGKILL mid-write leaves no truncated
    artifact (`--check` never sees a broken file).
- **Per-call `timeout` recipe across all four command shells.** The `mgh-init`/`mgh-sast`/
  `mgh-sra`/`mgh-srr` orchestrators (claude + opencode) now instruct the host to pass a
  generous per-call `timeout` to long-running deterministic Bash calls, and disclose the
  opencode global `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` (default 120000; must be
  ready before opencode launches — mid-session `export` is not inherited). `mgh-init` also
  adds the `partial: true` → Bash re-dispatch `--resume` loop (never a wrapper `.py`).

### Changed
- `discover_controls.py`: the materialized source list is sorted by repo-relative path so
  the scan checkpoint index is reproducible across runs; `scan()` keeps its 6-tuple API (a
  new `run_discover()` carries the cache/resume/budget knobs). `main()` skips writing final
  products on a partial exit (only `cache/` + `scan_progress.json` land). All additive — no
  final-product schema change; `--time-budget-ms 0` and a missing cache are byte-equivalent
  to before.
- `AGENTS.md` R5.3(c) (deterministic-script recoverability) + R5.4 (per-call timeout +
  discover soft-budget re-dispatch) sharpened; `README.md` gained a host-shell-timeout
  section; new contract `core/contracts/init/discover-cache.md`; `core/contracts/init/
  candidates.md` stdout summary extended with `partial`/`resume_hint`/`cache_hit`.

### Verified
- `tests/test_discover_resilience.py` (14 tests): cache hit + equivalence, mtime/size
  invalidation, `--rebuild-cache`, midpoint-resume equivalence + idempotency, checkpoint
  preservation when the budget trips at the callgraph boundary (regression), clean partial
  exit (exit 0, no truncated product), atomic writes, `--check` after a run. Plus a
  synthetic 150-file repo converging via repeated `--resume` to the one-shot candidate set.
- Full suite green (426 tests); `tools/check_contracts.py` (now asserts the discover flags
  in `--help`) and `tools/check_distributed_purity.py` both clean; zero-runtime-dep AST scan
  clean (`os`/`time` are stdlib).

## [0.1.10] — 2026-07-20

### Added
- **Sensitive-data catalog (`--sensitive-catalog`) for `/mgh-sra` + `/mgh-srr`.** Both commands now
  accept `--sensitive-catalog <inline-json|@path|->` to declare a **company masking policy** — the
  field types that MUST be masked, each with a `mask` level (`full` / `partial`) and a rule (e.g.
  "保留后 4 位"). This extends sensitive-data recognition **beyond the legacy 6 facets**
  (id-card / bank-card / phone / email / password / token) and drives **per-item masking-gap
  detection**: for each catalog field type, the reused a2/a3 subagents check whether it is masked
  per its rule at-rest / in-transit / log / response. The default is unchanged: omit the flag =
  legacy 6 facets only (byte-equivalent behavior, a hard backward-compatibility gate). The catalog
  is **orthogonal to `--focus`** (focus narrows *which dimensions*; the catalog declares *what must
  be masked*) and the two may be passed together.
  - **New deterministic script `core/scripts/sensitive_catalog.py`** — the closed-set single source
    of truth for the 10 PIPL / GB-T 35273 categories (identity-doc / biometric / health / financial
    / location / communication / device / vehicle / general-pii / legal) and the `{full, partial}`
    mask enum; ships a **37-item default template**. CLI: `--list` / `--parse` / `--check`. Closed-set
    violations (unknown category, illegal mask, malformed `<category>/<field-type>` key, missing
    label, non-int `version`) exit **2** with an actionable message; malformed JSON / missing file
    / unreadable stdin exit **1**. Renders a **deterministic** Simplified-Chinese policy directive
    (registry order, not input order). Zero runtime deps (stdlib only), self-locating sibling
    import; stdin read as UTF-8 on any console.
  - **`prepare_augment.py` + `ingest_requirements.py`** parse + closed-set-validate
    `--sensitive-catalog` in the deterministic a1/r1 stage (before any LLM token) via the shared
    `sensitive_catalog` module, and embed the resolved `sensitive_catalog`
    (`{version, source, categories[], items[], counts{}, directive}` or `null`) as a new top-level
    `change_context.json` field. Their `--check` validates the field shape (null allowed).
  - **Shared prompt overlay** in `sra-clarify.md` + `sra-augment.md`: when the orchestrator passes a
    non-null `sensitive_catalog`, the subagents expand the sensitive-data pass to per-item masking
    gaps (anchored to a concrete requirement/endpoint/field, tagged `catalog_key`), and link a gap
    to a `data-masking` control via the existing three-signal matching (advisory — a gap is never
    dropped for lack of a matching control). `/mgh-srr` reuses these prompts verbatim → obtains the
    behavior with **zero new prompts**.
  - **mgh-init linkage (consumption only)**: catalog-driven masking gaps reuse the existing
    `data-masking → sensitive-data` dimension mapping already in `prepare_augment.py`; **no change
    to mgh-init** discovery / inventory schema / rules.
  - **Disclosure**: the orchestrator-written `sra_manifest.json` and `render_report.py`'s
    `srr_manifest.json` carry a `sensitive_catalog` field (`counts` + `source`, or null); when a
    catalog is active, a boundary line states **masking gaps were checked per the company catalog
    items; field types outside the catalog were recognized only via the legacy 6 facets**, and the
    srr report header notes the catalog coverage.
  - **Shipped `.example` template**: a committed `core/scripts/sensitive_catalog.json.example`
    (the 37-item PIPL/GB-T 35273 template) is the canonical artifact; `install.sh` copies it to
    `.mgh-sra/sensitive_catalog.json.example` in the target project. It is **not auto-applied** —
    the company must `cp` it to `sensitive_catalog.json` or pass `--sensitive-catalog @<path>` to
    activate (backward-compat gate).
  - New contract `core/contracts/sensitive-catalog.md`; `core/contracts/sra/augmentation.md` +
    `srr/intake-report.md` document the new field; `security-dimensions.md` notes the catalog as the
    6-facet extension point.
  - New tests: `tests/test_sensitive_catalog.py` (registry / parse / closed-set violations / exit
    codes / determinism / input forms incl. stdin / anti-drift: 37-items + committed `.example`
    matches `DEFAULT_TEMPLATE` / zero-deps AST); `--sensitive-catalog` + `--check` coverage added
    to `test_sra_prepare.py`, `test_srr_ingest.py`; `test_zero_deps.py` asserts
    `sensitive_catalog.py` is scanned.

### Changed
- Four command shells (claude/opencode × sra/srr): `--sensitive-catalog` in the param/flag tables,
  orchestration flow (read `change_context.sensitive_catalog`, pass verbatim into a2/a3), bash
  examples, and an "Always disclose" catalog-coverage line. `tools/check_contracts.py` asserts the
  new flags; `tools/check_distributed_purity.py` confirms the shipped md stay clean (R5.10).

### Known limitation (honest boundary)
- Per-item masking-gap detection is enforced by a **prompt overlay** (non-deterministic guardrail),
  not a hard filter — the closed-set category/mask validation, the `change_context` embedding, and
  the `--check` layers are deterministic, but which catalog items actually surface a gap depends on
  the LLM pass. The catalog is **not** an exhaustive sensitive-field list (out-of-catalog fields use
  only the 6 facets); this is disclosed in the manifest/report boundary.

---

## [0.1.9] — 2026-07-16

### Added
- **Dimension focus (`--focus`) for `/mgh-sra` + `/mgh-srr`.** Both commands now accept
  `--focus <inline-json|path>` to **narrow** the per-dimension security scan to a subset of
  the 9 dimensions, and — for the two dimensions whose catalog enumerates discrete
  sub-categories — to a per-dimension facet whitelist. The default is unchanged: omit the
  flag = scan all 9 dimensions (byte-equivalent behavior, a hard backward-compatibility
  gate).
  - **New deterministic script `core/scripts/focus_scope.py`** — the closed-set single
    source of truth for the 9 dimension keys + the `sensitive-data` (id-card / bank-card /
    phone / email / password / token) and `injection` (sqli / xss / command-injection /
    path-traversal / ssrf / deserialization / xxe) facets; the other 7 dimensions have no
    facets (whole-dimension focus). CLI: `--list` / `--parse` / `--render` / `--check`.
    Closed-set violations (unknown dimension/facet, facet on a facet-less dimension, facet
    for a dimension not in `dimensions`, empty `dimensions`) exit **2** with an actionable
    message; malformed JSON / missing file exit **1**. Renders a **deterministic**
    Simplified-Chinese directive (registry order, not input order; byte-identical across
    runs); all-9 resolves to `null` (no narrowing). Zero runtime deps (stdlib only),
    self-locating sibling import.
  - **`prepare_augment.py` + `ingest_requirements.py`** parse + closed-set-validate
    `--focus` in the deterministic a1/r1 stage (before any LLM token) via the shared
    `focus_scope` module, and embed the resolved `focus` (`{dimensions[], facets{},
    directive}` or `null`) as a new top-level `change_context.json` field. Their `--check`
    validates the `focus` field shape (polymorphic in sra: inventory OR change_context).
  - **Shared prompt overlay** in `sra-clarify.md` + `sra-augment.md`: when the orchestrator
    passes a non-null `focus.directive`, both subagents restrict their per-dimension pass
    to the listed dimensions/facets and emit nothing out-of-scope; in-scope anchoring /
    three-signal / codegraph rules are unchanged. `/mgh-srr` reuses these prompts verbatim
    → obtains the behavior with **zero new prompts**.
  - **Disclosure**: the orchestrator-written `sra_manifest.json` and `render_report.py`'s
    `srr_manifest.json` carry a `focus` field (dimension list or null); when focused, a
    boundary line states **only the focused dimensions were scanned; out-of-scope
    dimensions were not covered**, and the srr report header notes the in-scope dimensions.
  - **Catalog annotated**: `security-dimensions.md` now tags the facet keys inline on the
    `sensitive-data` / `injection` rows, in lockstep with the registry (anti-drift asserted
    by `test_focus_scope.py`).
- New tests: `tests/test_focus_scope.py` (registry / parse / closed-set violations / exit
  codes / determinism / input forms / anti-drift); `--focus` + `--check` coverage added to
  `test_sra_prepare.py`, `test_srr_ingest.py`, `test_srr_report.py`.

### Changed
- Four command shells (claude/opencode × sra/srr): `--focus` in the param/flag tables,
  orchestration flow (read `change_context.focus.directive`, pass verbatim into a2/a3),
  bash examples, and an "Always disclose" focus-scope line. `tools/check_contracts.py`
  asserts the new flags; `tests/test_zero_deps.py` asserts `focus_scope.py` is scanned.

### Known limitation (honest boundary)
- The narrowing is enforced by a **prompt overlay** (non-deterministic guardrail), not a
  hard filter — a focused run could in principle still emit a range-adjacent gap. Residual
  non-determinism is disclosed the same way as the existing prompt-guardrail boundaries;
  the closed-set / embedding / `--check` layers are deterministic. Focusing too narrowly
  can miss real gaps — this is the user's explicit choice, disclosed in the manifest/report.

---

## [0.1.8] — 2026-07-15

### Added
- **`/mgh-srr` — freeform-text security requirements review (no openspec needed).** A new command
  for the common case where requirements arrive as raw text (word/txt/md/excel or pasted) with no
  openspec structure — and possibly no concrete interfaces/fields at all. It is a **port-adapter
  over the `/mgh-sra` middle engine**: a deterministic input adapter (`ingest_requirements.py`)
  extracts the doc into an sra-shape `change_context.json`, the existing sra engine (sra-clarify /
  sra-augment / sra-consistency + 9 dimensions + three-signal control reuse + batched clarification
  + project memory) is **reused verbatim with zero new prompts**, and a deterministic output adapter
  (`render_report.py`) renders a plain, brief Simplified-Chinese `security_review_report.md` +
  `srr_manifest.json` that **never touches openspec/**.
  - **Mixed three-tier input**: `.txt/.md/.csv/.json` read natively (perfect); `.docx`/`.xlsx`
    best-effort via stdlib `zipfile` + `xml.etree` (joining all `<w:t>` within each `<w:p>` so text
    never token-fragments) with **explicit degradation flags** (dates-as-serial / list-markers /
    embedded-objects / merged-cells); a permanent `--text` / stdin **passthrough** escape hatch
    (zero degradation). Unsupported formats (`.doc`/`.xls`/scanned PDF/encrypted) exit 2 with a
    conversion recipe and emit no partial artifact.
  - Interfaces / fields / roles are **optional, non-load-bearing hints** (freeform text may have
    none); the LLM reads the full text and anchors gaps to section headings. Default = one review
    unit; `--split` fans out per markdown `#`/`##` heading (script-enumerated fan-out).
  - **Shares** `<project>/.mgh-sra/business_context.json` with `/mgh-sra` (one accumulating file
    across both tools; same schema, contract unchanged). Optional codegraph enrichment is inherited
    from the reused sra engine (`--no-codegraph` opts out, reproducing pre-codegraph behavior).
  - **Runtime discipline**: a new `MGH_SRR_ACTIVE` run-domain on the **unchanged**
    `block-adhoc-scripts` guard (claude PreToolUse + opencode `.ts` plugin, byte-identical twin),
    covering the review dir + shared project memory under `MGH_TARGET`. Same fail-soft reliability
    boundary on opencode as the other domains.
- Zero new runtime dependencies (R2): `.docx`/`.xlsx` use only the Python standard library. SRR
  reuses all sra stage prompts + fragments + `merge_memory.py` (no duplication — asserted by the
  new `test_mgh_srr_codegraph_parity.py` reuse-not-duplication tests).

### Known limitation (honest boundary)
- `/mgh-srr` input extraction is best-effort for `.docx`/`.xlsx` (dates / formats / list markers
  degraded — flagged in the report); review coverage is bounded by input completeness, so a vague
  requirement document yields only sparse, anchor-light gaps. The `--text`/stdin passthrough has no
  degradation. All other sra boundaries (LLM candidates need human review; controls asserted to
  exist not to be effective; memory is user-asserted; codegraph is optional advisory) apply unchanged.

---

## [0.1.7] — 2026-07-15

### Added
- **Optional codegraph enrichment for `/mgh-init` and `/mgh-sra` (coordinated pair).**
  When the target project has a precomputed codegraph index (`<target>/.codegraph/`)
  **and** the `codegraph` tool on PATH, both commands use it as an optional,
  detection-gated enrichment backend consumed entirely in the **LLM layer** — never
  `import`ed by any `.py`, so zero new runtime dependencies (R2) and zero changes to the
  deterministic script contracts (R5.3). Detection defaults to `auto`; `--no-codegraph`
  opts out and reproduces pre-codegraph behavior exactly (fail-soft).
  - **`/mgh-init`**: a new optional `init-resolve` stage (codegraph-gated, single context)
    resolves the framework-routed / DI / AOP / interface→impl / reflection controls the
    text/AST call graph collects into `unresolved[]`, emitting additive
    `source:"codegraph"` candidates with a real `resolved_path[]`. scout/induct/survey
    stages prefer `codegraph_explore` (MCP) / `codegraph explore` (CLI) for surgical
    context. `init_manifest.json` gains a `codegraph:{available,used,resolved_count,
    unresolved_residual}` block.
  - **`/mgh-sra`**: `sra-augment` (a3) gains an inline **call-path structural-evidence
    confirmation** — for gaps that already matched all three reuse signals, codegraph
    confirms whether the recommended control is actually wired onto the gap endpoint's
    request path, recorded as advisory `recommended_control.call_path:{confirmed,
    path[],source:"codegraph",note}` (plus data-flow / liveness / domain-sibling
    advisory facets). This upgrades signal-2 "business-domain similarity" from a semantic
    guess toward structural evidence, directly targeting SRA's "controls are asserted to
    exist, not to be effective" blind spot. Bounded + fail-soft (top-1 control per gap
    under budget; `confirmed` never fabricated; never overrides code evidence or user
    `business_context.json`). `sra_manifest.json` gains `counts.call_path_confirmed` /
    `call_path_residual` + a 5th honesty boundary; the existing four stay intact.
- **Shared codegraph steering fragment** `core/prompts/fragments/codegraph-hint.md`,
  co-owned by both changes. Prescriptive by intent — "SHALL prefer codegraph, Read only
  as fallback", never the permissive "you may" — to avoid the known trap where a subagent
  keeps self-Reading and codegraph becomes pure overhead.
- **Dual-platform parity (R5.7)**: claude + opencode both reach codegraph via MCP
  (`codegraph_explore`), with CLI (`codegraph explore`) Bash fallback. The existing
  `block-adhoc-scripts` guard is unchanged — codegraph MCP/CLI calls do not hit any of its
  ad-hoc-script surfaces — so **no new hook** is introduced.

### Known limitation (honest boundary)
- codegraph is itself a static analyzer: reflection / DI-container / runtime dispatch
  remain unresolved, so call-path confirmation shrinks but does not zero out mis-wiring.
  `call_path` is LLM+codegraph advisory needing human review; manifests disclose
  `call_path_residual` / `unresolved_residual` and never claim "fully confirmed".
- opencode's plugin process does not inherit env vars exported mid-session, so the
  `codegraph=on` signal activates reliably only when present at opencode launch; the CLI
  Bash fallback + shell bright-lines cover the gap (fail-soft).

## [0.1.6] — 2026-07-10

### Added
- **opencode runtime-discipline hook parity.** opencode now gets the same orchestrator-discipline
  enforcement Claude Code has. `install.sh --opencode` injects a `tool.execute.before` plugin
  (`.opencode/plugins/block_adhoc_scripts.ts`) that normalizes the tool event into Claude's
  PreToolUse stdin shape and pipes it to the **same** platform-neutral Python guard
  (`block_adhoc_scripts.py`, now also mirrored to `.opencode/hooks/`). The guard is unchanged —
  single decision source, byte-parity guarded by `tests/test_opencode_hook_parity.py`. New
  `tools/install_opencode_plugin.py` mirrors `tools/install_hook.py` (idempotent, merge-aware,
  `--remove`). This corrects the prior wrong premise that "opencode has no PreToolUse capability":
  opencode's hook surface is JS/TS plugins (`tool.execute.before`/`tool.execute.after`) — this was
  a porting gap, now closed (not a capability gap).

### Known limitation (honest boundary)
- opencode's plugin process does **not** inherit env vars exported mid-session via `bash` (its shell
  tool builds env from `process.env` and never writes back). So `export MGH_*_ACTIVE=1` inside a run
  may not reach the guard; the runtime gate activates only when the env is present at opencode
  launch (e.g. `MGH_*_ACTIVE=1 opencode run`). The shell bright-lines + per-stage `--check` boundary
  validation remain the real backstop either way (fail-soft). Verified against opencode v1.17.15.

### Fixed
- **`/mgh-init` scout→merge fold-in crashed on two kinds of malformed `scout_candidates.json`**
  (raw traceback, empty stdout, orchestrator unable to decide). (1) A candidate missing its
  `category` field hit a `KeyError` in `merge_scout._normalize`; (2) a broken JSON string value
  (e.g. an `evidence_snippet` with mis-escaped quotes / backslashes) raised `JSONDecodeError` —
  and `merge_scout.py --check` returned exit `1` (not `2`), so the orchestrator gate (which only
  rolls back on exit 2) let it through to `main()`, which had no `try/except`.
- Fix (defense-in-depth, three layers): `--check` now also asserts every candidate carries a
  non-empty `category`, and returns exit `2` for malformed JSON with `lineno`/`colno`/`msg` + a
  nearby byte window; `main()` wraps all `json.loads` (`--candidates` / `--scout` / `--clusters`)
  so a malformed input yields a structured stdout error + exit `1` with NO traceback, and
  `_normalize` now skips + warns on any category-less candidate (count surfaced as `skipped` in
  the success summary) — covering the `audit_found[]` path that bypasses `--check`.
  `discover_controls.form_clusters` is untouched (skipped candidates never reach it).
- The S3 / S4 / audit stage prompts now require a non-empty `category` on every candidate and a
  JSON-safe `evidence_snippet` (single line; `"` → `'`; strip `\`) — structurally incapable of
  breaking the enclosing JSON string. Covered by `tests/test_merge_scout.py`.

---

## [0.1.5] — 2026-07-07

### Fixed
- **`/mgh-init` fan-out checkpoints occasionally landed outside the project tree**
  (observed: a Windows drive root, e.g. `D:\xxx.json`). Root cause: the scout/T1/T3
  output paths were soft — placeholder templates / relative paths assembled twice (once
  by the orchestrator, once by the subagent); a misplaced subagent cwd resolved a
  relative path to the drive root. The enumeration scripts (`list_scout_batches.py` /
  `list_clusters.py` / `list_rule_jobs.py`) did not emit paths at all, so both agents
  had to assemble them.
- Fix: each enumerator now emits a **single authoritative absolute** `checkpoint_path`
  (scout/T1) / `rule_path` (T3) + `done_marker` per pending unit (via `Path.resolve()`).
  The orchestrator passes these **verbatim**; the stage prompts + double-shell agent
  defs treat them as **verbatim input fields** with a `NEVER`-boundary against
  self-assembly / invented filenames / relative paths / out-of-tree writes.
- **Defense-in-depth**: the `block-adhoc-scripts` PreToolUse hook (claude, `MGH_INIT_ACTIVE`
  run-domain) now also blocks `Write`/`Edit` whose resolved target is **outside the
  `MGH_TARGET` tree** (fail-loud, exit 2, recipe points at `list_*` stdout). `MGH_TARGET`
  is sourced from discover's absolute `repo` (via `describe_artifact --field repo`, never
  `py -c`); missing → degrade (pass). `--no-enforce-hook` opt-out unchanged; opencode
  (no PreToolUse) warns + skips.
- **AGENTS.md**: R5.3(b) extended (enumerators MUST emit exact absolute output paths);
  R5.5① gains a fan-out path recipe.
- New contract `core/contracts/init/cluster-enumeration.md` (T1 previously had no
  enumeration contract); `scout-enumeration.md` / `rule-jobs.md` gain the path fields.
- All additive: on-disk artifact schemas unchanged; no new runtime deps; no new CLI flags
  (`check_contracts` 0 violations). 181 tests pass.

### Upgrade
- Re-run `./install.sh --claude <target>` (or `--opencode`) to refresh the hook + shells
  + stage prompts. Existing checkpoints/rules are unaffected (schema unchanged).

---

## [0.1.1] — 2026-06-29

### Fixed
- **opencode agents failed validation on startup** with
  `Configuration is invalid ... invalid input: expected record, receiving string tools`.
  Cause: generated opencode agent frontmatter used `tools: read, glob, grep` (a
  string), but opencode's `tools` field is deprecated and expects a record.
  Fix: `tools` replaced by a `permission:` record (`read/glob/grep/list/bash/edit`
  → `allow|deny` derived from each agent's Claude tool set); the Claude-only
  `model: inherit` was removed (opencode markdown agents omit `model` to use the
  configured default). Verified all 8 agents parse as valid opencode frontmatter.

### Upgrade
- If you installed an earlier `0.1.0` with `--opencode`: re-run
  `bash install.sh --opencode .` (or the `.ps1`) in your project to
  overwrite the broken `.opencode/agent/sast-*.md` files, then restart opencode.

---

## [0.1.0] — 2026-06-29

Initial release.

### Added
- **9-stage SAST pipeline** as a native Claude Code / opencode command `/mgh-sast`
  (survey → threat-model → decompose → deep-dive → prefilter → verify → dedup →
  chain → SARIF). Zero runtime dependency on `vvaharness`.
- **Stage mapping** faithful to the original: LLM reasoning stages (s1/s2/s3/s4/s6/s8)
  run as subagents driven by skill lenses; deterministic stages (s5 prefilter,
  s7 dedup, s9 SARIF/CVSS/CWE) run as Python ≥3.10 stdlib scripts.
- **Verbatim prompt porting** from vvaharness via a stdlib `ast` extractor
  (`tools/extract_prompts.py`): stage system prompts, shared triage fragments,
  specialist lenses, threat baselines. s4 composed SYSTEM = 8,065 chars (matches
  the original). Provenance table in `core/docs/prompt-provenance.md`; Apache-2.0
  headers + `core/docs/NOTICE`.
- **Incremental scan** `--diff <ref>` — git-diff seed + call-chain expansion.
- **Scope scan** `--path <dir>` / `--package <pkg>` — directory/package seed +
  call-chain expansion.
- **Call-chain engine** (`core/scripts/expand_scope.py`): zero-dep text call graph
  (Java/Python/JS-TS/Go + generic), optional tree-sitter fallback, bidirectional
  BFS (default `both`/depth 2), Spring/Feign/AOP/DI framework allowlist.
- **Batch multi-repo** `--repo-file` (+ `--group-by-app`, `--keep-clones`,
  `--workspace`).
- **Dual-platform packaging**: platform-neutral shared `core/` + a Claude Code
  shell + an opencode shell. Installers `install.sh` / `install.ps1` with a
  zero-runtime-dependency self-check.
- **SARIF 2.1.0** output (`core/scripts/emit_sarif.py`) with a CVSS 3.1 base-score
  calculator (official roundup) + CWE mapping; severity always derived from the
  CVSS band and never disagrees with the score.
- **Unit tests** for the deterministic stages (`tests/test_deterministic.py`):
  9 tests covering prefilter gates, dedup merge, CVSS math, severity bands.
- **Distribution guide** (`docs/分发与使用指南.md`) for enterprise intranet rollout
  across Claude Code and opencode users.

### Known limitations
- Findings are **triage candidates, not confirmed vulnerabilities**; runs are
  non-deterministic.
- The call graph is **textual/AST-level**. It misses dynamic dispatch, reflection,
  DI, and framework routing (Spring `@*Mapping`, Feign, AOP, `@Autowired`,
  JPA/Spring Data). Framework-routed files unresolved against the seed are listed
  in `scope_manifest.unresolved[]` and the report for manual follow-up.

### Pending (not in this release)
- Live end-to-end scan against a real target repo.
- opencode live run + Claude↔opencode parity regression.
- Optional differential comparison vs upstream vvaharness output.
- `AGENTS_CN.md` / README pointer update to `/mgh-sast`.

---

## Versioning policy

- `0.x.y` — initial development; structural completeness, live verification in
  progress. Breaking changes may occur between `0.x` releases.
- `1.0.0` — first stable release once the *Pending* live-verification items close.
