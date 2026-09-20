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

### Changed — the sdr report's three locate-points became clickable source-file links; unlocatable paths degrade to the exact old text (0.1.50)

`/mgh-sdr` reports solved "readable" (the chain short forms) but not "reachable" — a human
reviewing a suspicious hop had to hunt the class through the repo by hand, several hops per
finding, every review. The data was already on disk: chain nodes carry `file` + `line` from
grouping, and the report lands at the repo root, so a repo-relative path IS the link.

- **Three render points, one helper.** `render_sdr_report.py` gains `_source_link(text, file,
  line, repo)`, used by the 简报表 entry column (standalone method-def forms; route strings
  never link), every chain node, and the 章节二 position line — `[Ctl.submit](src/…#L42)`,
  anchor omitted when no line (mapper XML terminals are the natural case). Short-form
  construction and link wrapping stay two layers: `†` rides inside the text, `→`/`·`/`⤷`/`⇢`
  separators stay outside the link.
- **Purely lexical resolution, zero broken links by construction.** Absolute paths are
  rebased onto `--repo` (`normcase` absorbs the Windows case-insensitive drive); outside the
  subtree, empty/missing, leading `..`, or a path with spaces/parens → the plain-text form,
  byte-identical to the old report. The renderer NEVER stats the target (a diff branch's file
  may not be checked out; stat-based judgment would make the report depend on checkout state).
  Display-text `[`/`]` get minimal escapes; finding `line_hint` info is NEVER dropped to buy a
  link.
- **Machine surface untouched.** `sdr_manifest.json` `rows[].entry/chain` stay plain short
  forms (link wrapping is a render projection); the `--check` internal-anchor ban (`](#`)
  cannot misfire on `](src/…#L42)` — the `#` there is preceded by a path segment — now stated
  as a comment. The `P-NN` dimension columns remain pure text as decided.
- **Verified**: 11 new `_source_link` unit cases + a 3-unit end-to-end (anchored links,
  no-anchor mapper terminal, `†` inside the link, out-of-repo/empty-file degradations,
  manifest-vs-table equality after de-linking) in `tests/test_render_sdr_report.py` (29 tests);
  a springBootTemplate dry-run (grouping-only env + hand drafts, reused from the report-structure
  change) rendered 59 links, all targets present on disk, spot-checked anchors landing exactly
  on their method declarations, and a timestamp-normalised diff against the pre-change renderer
  confirmed the ONLY changed lines are the three render points (head / 章节三 mermaid /
  no-issue list / honesty boundary byte-identical). `--check` passes on both render outputs;
  contract and purity lints clean; command shells unchanged (they never carried the
  plain-short-form wording).

### Added — the sdr run domain gains a disk-derived resume surface; run-level state stops being an orchestrator recipe (0.1.49)

`/mgh-sdr` could already avoid redoing finished work (a `.done` unit is skipped, `--resume`
re-dispatches only what is missing, the renderer overwrites its own report), but it could not
answer **"which step am I on / what do I run next"**. After a crash, after a context
compaction, or in a fresh session the orchestrator had only the conversation to go on — and
the conversation is a cache, not a source of truth. `/mgh-init` has had the other half for a
long time (re-derive the step from the run dir, re-inject that step's defenses); sdr never got
it. Two related gaps came with it: the sentinel guarding the run was written by a shell recipe
the orchestrator had to read and execute correctly, and the run dir carried a start-state file
nothing consumed.

- **`resume_sdr_state.py`** — the single sanctioned outlet for the sdr reflex "where am I /
  what next". `step` is derived purely from `<run-dir>/` disk products (`context.json` /
  `grouping.json` / unit markers / `sdr_manifest.json`) over the closed set
  `not-started|group|fanout|render|done`, where the step name is the **current TODO step**.
  It never reads conversation memory and never guesses from a damaged product (an unreadable
  `context.json`/`grouping.json` exits 2 with a recipe). stdout carries `step`, `resumable`,
  `tiers`, `next_action{kind,desc,absolute_paths[]}` with verbatim absolute paths, `notes[]`,
  `discipline_reminders`, and a `stale_fanout[]` scan of leftover `fanout_runner.*.pid`
  liveness files. `--check` fail-louds on the states that matter; `--rearm-sentinel` rebuilds
  the guard sentinel deterministically.
- **Per-step discipline travels with the resume.** `discipline_core.get_discipline(step,
  domain="init")` gained a `domain` parameter and an sdr table (default domain output is
  byte-identical, so the existing callers are untouched). A resumed run is handed the same
  gates, path recipes (unit paths come from the enumerator's stdout, verbatim) and `NEVER`
  boundaries it would have had at the start — the defense line is re-injected from disk rather
  than remembered.
- **`list_sdr_steps.py`** answers the complementary question ("the exact invocation for any
  step") with zero disk preconditions, mirroring the init/ut-init siblings; its `--step`
  discipline is asserted byte-identical to `resume_sdr_state.py`'s for the same step.
- **One rule for unit identity.** New `sdr_tier.py` holds the forward marker-path predicate,
  imported by BOTH the writer (`diff_group.py`, which was concatenating marker paths inline)
  and the resume reader. A second copy of that concatenation is how "the enumerator says
  pending while the disk holds a marker" becomes an infinite re-dispatch loop. Marker paths are
  reproduced verbatim — no sanitizing or truncation is added, because the id is already
  sanitized when the unit is built and re-encoding it would rename every existing marker.
- **Run-level state is now a script side effect.** `sdr_context.py` — the one step both
  entries (launcher and host session) pass through — co-writes the guard sentinel
  `<repo>/.mgh-sdr/.active` and `<run-dir>/run_config.json` atomically. The shell's three
  hand-executed `printf` recipes are gone; the orchestrator no longer has to read and execute a
  write recipe correctly for the guard to be armed. The launcher keeps its own sentinel write as
  an **idempotent refresh**, because it is the second authorization judgment (roots are
  re-checked against the project config immediately before the host CLI is spawned, so a
  version-skewed sibling cannot leak an unapproved root).
- **`run_config.json` keeps one job, script-written.** Its only payload is the codegraph signal
  `{"no_codegraph": bool}`; the shell's auto-detection result is passed to `sdr_context.py` as
  `--no-codegraph` (the launcher gained the same flag) instead of being written by hand. The
  start state (repo/base/branch) is deliberately NOT written there — it is re-derived from
  `context.json` / `grouping.json`, and the resume script does not read the file at all. Legacy
  run dirs carrying start-state fields are ignored, not deleted.
- **The start state is disclosed, never guessed.** The one step with no on-disk start state is
  `not-started`, and that is also the one step with zero completed work — so re-supplying
  `--base`/`--branch` restores it losslessly. The script says so in `notes[]`, gives an
  executable call with defaults, and refuses to run `git` to guess a branch (using the wrong
  branch for a diff costs more than typing one flag).
- **Both command guides' recovery section now points somewhere that runs.** It names
  `resume_sdr_state.py --run-dir <abs>`, states the precondition (recovery must carry the SAME
  run dir — a fresh timestamped dir loses every marker), and says the progress and the defenses
  are disk-derived, so whether the conversation survived is irrelevant. The init-domain
  `resume_state.py` pointer (which resolves to `.mgh-init` and exits 1 against an sdr run dir) is
  gone. Two honesty boundaries were added: re-running the launcher creates a NEW run dir (never
  claim "re-run the launcher and it resumes"), and `--dimensions` narrowing is closed-set
  validated but **not** dispatched to review units.

Tests: 29 new cases for the resume state machine over synthetic run dirs (empty dir, context
only, grouping only, partial terminals, all-terminal, rendered, zero-diff, all-excluded, a
stale `status` field that must NOT be trusted, a legacy `run_config.json` that must be ignored,
a sentinel missing at each of the three guard-window steps, re-arm idempotence, and two calls
against one disk state producing byte-identical stdout), 7 for the shared marker predicate
including a real-git end-to-end assertion that the predicate reproduces `diff_group`'s emitted
paths byte-for-byte, 8 for the step manifest (including the cross-script discipline equality),
and 11 extending the existing sdr context / launcher suites (sentinel presence and
minimalism on every run, vanished roots dropped, the signal payload carrying only
`no_codegraph`, idempotent refresh, and the launcher's pre-spawn re-judgment still rejecting an
unapproved root). `tools/check_contracts.py` now asserts the new scripts' flags, that each shell
names the sdr-domain resume entry, and that a hand-executed `printf` write recipe cannot
reappear. `install.sh`'s co-location self-check covers the three new scripts. The two command
guides stay byte-mirrored apart from host-specific lines; each is ~3.4K tokens, within budget.

### Fixed — the sdr codegraph switch had three write ends and no reader; its recovery pointer could never run (0.1.49)

`/mgh-sdr` handed the shared dispatcher a codegraph switch that nothing consumed, and a
troubleshooting step that failed every single time.

- **The switch was dead.** The command shells exported `MGH_SDR_CODEGRAPH`, wrote a
  `no_codegraph` field into the run dir's `run_config.json`, and advertised `--no-codegraph` —
  none of it read by any script. The dispatcher's `_codegraph_signal()` returned `off` early for
  the sdr tier, so every review sub-agent's task message said `codegraph=off` ("this unit may be
  split at an interface boundary") while the grouping stage in the SAME run had already merged
  those units along the call chain and loaded the whole chain into the slice. Two stages of one
  run disagreeing about the same fact, and the disagreement told the reviewer to ignore exactly
  the cross-layer information grouping had just given it.
- **One carrier, and a real consumer.** `MGH_SDR_CODEGRAPH` is deleted rather than wired up: an
  environment variable has no consumers today and, on the opencode host, is unreliable anyway
  (the plugin process does not inherit mid-session `export`s). The signal now rides the run dir's
  `run_config.json` alone, written by `sdr_context.py` (the one step both entries pass through)
  and read by the dispatcher. The sdr plan anchor is already `<run-dir>/grouping.json`, so its
  parent IS the run dir: the sdr tier falls into the exact same read path as the init tiers with
  zero path changes, which is what makes the two stages agree by construction rather than by two
  logics kept in sync.
- **The signal is probed, not declared.** Closing the reader exposed the same defect one layer
  down: the value written into `run_config.json` was still whatever the caller happened to
  assert. The launcher asserted `on` unconditionally (its flag defaulted to off-by-absence, and
  nothing on that path ever looked at the repo), so on an unindexed repo the grouping stage
  degraded to no chain while every task message still promised "this slice already carries the
  whole changed chain: judge cross-layer inside it, do NOT re-derive" — a false instruction, and
  precisely the side-disagreement this change exists to remove. The availability predicate now
  lives once, in `sdr_tier.py`, and `sdr_context.py` derives the signal from it (repo indexed AND
  a `codegraph` binary resolves), exactly as `diff_group.py` decides whether to merge units along
  the chain. `--no-codegraph` survives as an explicit force-off **of the signal**; the shells no
  longer carry a second probe of their own. Note what that flag does and does not do: measured on
  an indexed repo, passing it flips the task message to `off` while `diff_group` still reports
  `codegraph: true` and still merges along the chain. That is deliberate and now stated as such
  everywhere the flag appears — it buys reviewers a conservative reading, it does NOT re-run the
  grouping without the index. (The earlier text claimed "zero codegraph calls, behaviour
  equivalent", which was never true of the grouping path.)
- **The recovery pointer was cross-domain.** The "fast-fail storm" step asked the orchestrator to
  run `resume_state.py --check` as proof that the disk was healthy before re-dispatching a
  stalled wave. That script resolves its state root to `<target>/.mgh-init` and has no form that
  accepts an sdr run dir, so against an sdr run it exits 1 ("dir not found") 100% of the time —
  turning the orchestrator's judgment into noise. It is replaced by `diff_group.py --check
  <run-dir>`, which does run in that domain (exit 0/2). Its meaning is narrower and is stated
  next to the command: it validates the **grouping artifacts** (grouping.json + slices +
  markers), not **run-progress consistency**. A full sdr resume surface is out of scope here.
- **Timeout wording pinned, zero values changed.** `--stall-timeout-s` has two numbers that are
  easy to confuse: `60` is the hard rejection floor (`1..59` exits 2) and `900` is the
  out-of-host manual-run default. `--help` now states the four-segment domain and labels each
  number explicitly, and says that a host-driven call MUST pass the flag explicitly below
  `--call-timeout-s`, NEVER rely on the default. The spawn-time recipe for a violated
  `stall < call` ordering now names the usual cause (an omitted flag) alongside its two exits.
  **No value changed**: the constants, the validation logic and the `300` used by every
  `/mgh-init` tier and by `/mgh-sdr` are untouched. Dropping the flag to "use the default" would
  make every host-driven tier unstartable (exit 2 before any spawn).

Tests: the sdr signal's three states (no field → `on`, `no_codegraph: true` → `off`,
missing/unparseable → `off` with no stderr noise) plus an end-to-end CLI case proving the
`{{codegraph}}` placeholder flips with the run dir's config; a guard that the four init tiers
still read the same carrier and that `tier_key` no longer branches; the probe's both-halves and
degradation cases, and that an indexed repo reports `on` through the launcher with no flag
(the case the old default got wrong); the omitted-stall rejection with all three recipe exits.
`tools/check_contracts.py` now fails the build if the dead env var returns, if a shell declares
`--no-codegraph` without the carrier it rides, if a shell points at a cross-domain script, if
the dispatcher's sdr early-return is reinstated, or if either consumer re-inlines the probe
instead of importing the shared predicate.

### Changed — the sdr slice budget is judged on the rendered slice, and an over-budget unit is re-split, slimmed, or refused — never dispatched (0.1.50)

`/mgh-sdr` promised "one unit input ≤ the byte budget", but the packing layer judged that
budget with an **estimate** — the sum of each file's diff-text length plus a flat 64 bytes per
file — while the subagent actually reads the **rendered slice**, which also carries a header, a
file list, an annotation-context block, a symbol table and one `@@` locator line per hunk. Two
paths escaped with no check at all: a multi-file unit that estimated under but rendered over,
and a single file whose own diff exceeded the cap (the source admitted it in a comment:
*"one oversize file may still exceed it (merged-capped, never split mid-file)"*). This is the
same tolerated gap `/mgh-init` closed in its T2 aggregation, where "warn and send anyway"
produced a real request-context overflow that killed the whole unit.

The judge is now the artifact: one measurement function renders the unit with the very renderer
that materializes it and takes the utf-8 byte count. Packing-time member sizes, the
`pending[].unit_bytes` field and the `--check` assertion all read that one number. Over budget,
three dispositions run in order, and the first that resolves it wins:

1. **Lossless re-split** — a multi-file unit is greedy-packed by path into `-partN` continuation
   units, each measured ≤ cap. No hunk is dropped, no content truncated; more units is the only
   cost. This is the existing greedy rule finally running on the right judge, not a new splitter.
2. **Context slim** — only for an atomic residue (one file left; a file is never split
   mid-file). The descriptive blocks (`ann_ctx` / `sym_ctx`) are truncated to module-constant
   caps with a visible `… (截断:K 行 / 原 N 字节)` marker in the slice and a `slimmed{}` record in
   the run record. The evidence anchors — diff bodies, the file list, the hunk locators, the
   header fields — are never touched: truncating the diff would make the review reach
   conclusions on partial evidence, which on a pre-merge security gate is worse than not running.
3. **Fail-loud, zero dispatch** — still over cap → exit 2 naming the unit id, its cap, the
   measured bytes and the largest contributing file, with a recipe (raise the cap / narrow the
   diff range / review that file out-of-band). The judgement happens **before** any slice or
   `grouping.json` is written, so with nothing on disk for the dispatcher to consume, "the
   enumerator refused" and "no subagent was spawned" are the same statement.

Disclosure is not optional: the run record gains a top-level `budget{}` and a per-unit
`slimmed{}`, `--check` asserts `unit_bytes ≤ cap` when those fields are present (an old
`grouping.json` without them still exits 0 — same incremental-field contract as `excluded` /
`codegraph_stats` / `chain[]`), and the report's honesty boundary names every slimmed unit so a
"no finding" from one is not read with the same weight as from a normal unit.

No new flags: `--max-standalone-bytes` / `--max-interface-bytes` remain the only levers; the two
slim caps are module constants. In-budget runs are byte-identical apart from the new `budget{}`
and empty `slimmed{}` fields.

Tests: the multi-file over-budget case re-splits with the parts' hunk-locator set equal to an
un-split run's (lossless), with the old `cap + 1024` tolerance tightened to `cap`; an atomic
residue whose overage is carried by the symbol table is slimmed (marker visible, diff body and
locators intact, `slimmed` recorded, exit 0); an atomic residue whose own diff body is over
refuses with exit 2 and **zero** slices, zero `grouping.json` and empty stdout; `unit_bytes`
equals the landed file's byte count for every unit; a pinned slice text guards the in-budget
no-regression line; `--check` covers the new-field assertions and the old-record skip; and the
dispatcher passes the refusal through as exit 2 against a real repo with nothing written.

### Changed — fanout silence is no longer proof of a hang: explicit off-switch + false-kill self-evidence + cost disclosure (0.1.48)

`--stall-timeout-s` was the only defense against a hung unit, and it silently doubled as a health
verdict. Under a rate-limited gateway that verdict is simply wrong: a unit with no output is
usually a call **sitting in the gateway queue**, which is byte-for-byte identical to a real hang.
Killing it does not shorten the queue — it discards the work already done and re-queues behind the
same congestion. Raising the constant does not fix it either (measured: 600s killed 5 units, 1600s
still killed 4, at 2.7x the cost each — 4 x 1600s = 6400 slot-seconds, 40-60% of that run's 5-slot
capacity).

- **Semantics rewritten wherever it is stated.** Byte silence now reads as "this unit has produced
  nothing for this long"; `--help`, the module docstring and both command guides say explicitly
  that it is NOT hang evidence, that the criterion's only legitimate job is bounding how long one
  slot may sit idle in this run, and that it cannot locally distinguish queueing from a hang. The
  old "high-signal hang indicator" wording is gone, along with the glossary entry that repeated it.
- **`--stall-timeout-s 0` = explicit off.** The value domain is now `0` or `>= 60`; `1..59` still
  exits 2, and both that error and the invariant recipe name BOTH exits (raise it, or pass 0).
  With the criterion off the `stall < call` ordering constraint does not apply and
  `--call-timeout-s` alone bounds convergence (so a host-driven run should tighten it). The only
  previous off-switch was `--call-timeout-s - 1` — an undocumented hack the old `--help` text
  argued against.
- **False-kill self-evidence + bounded widening.** If a unit the window killed then completes on
  re-dispatch in the same run, that is the one hard local proof the silence was not fatal: the
  effective window becomes `min(2W, --call-timeout-s x 0.8)` for units dispatched afterwards
  (stderr-disclosed once per triggering unit; per-unit, so one flaky unit cannot ratchet it to the
  ceiling; per-run, never persisted, never written back onto the flag). Each attempt snapshots the
  window at spawn, so a widening never retroactively moves the criterion of a unit already running.
- **Cost visibility.** Every exit's stdout summary and progress sidecar now carry
  `runtime_p50_s` / `runtime_p95_s` / `runtime_max_s` (COMPLETED units only — a killed unit's
  runtime is an artifact of the window, not a sample of the population the window sits above; all
  three are omitted, never 0, when nothing completed), `stall_killed_slots_s` and
  `stall_killed_slot_pct` (slot-seconds burnt by silence kills, and that as a share of the run's
  slot-seconds = elapsed x `--wave`), plus `stall_window_s` when the window actually widened.
  Existing fields are unchanged; the sidecar values are literally the same dict the summary is
  built from, so the two cannot drift apart on rounding.
- **Default value: unchanged at 900, now with a stated calibration.** `p99(completed-unit
  runtime) x 2`, rounded down to the minute, floor 900. Substituting the observed sample (n=84:
  p50 134s / p95 229s / p99 325s / max 325s) gives 650s -> 600s -> 900s. The calibration's value
  is the two conclusions it forces, both disclosed in `--help`: 900s is 2.8x the completed
  population's MAX (so "the default is too tight" is false for healthy units), and the killed
  units ran 600s+ / 1600s+ — outside that population's support, NOT its tail, so no higher
  constant rescues them. The sample is the SURVIVING population only, so it MUST NOT be read as
  "past this it deserves to die" — which is exactly why the adaptive widening exists instead.
- **Heartbeat discloses the window.** The in-flight line gains `stall_window=<w>s` (or `off` in
  disabled mode): with an adaptive window, `idle=1000s` is unreadable on its own — it means "kill
  is imminent" at W=900 and "nothing to see" at W=1800.

Tests: 20 added/updated across `tests/test_fanout_runner.py` and `tests/test_fanout_stale.py` —
the two pure helpers (`_widened_stall_window`, `_percentile_int`), the widening and its ceiling,
per-unit evidence dedup, the disabled mode at both the dispatch level (every attempt handed window
0) and the `_run_unit` level (the same silent child stall-killed at window 2, left to the call
timeout at window 0), the value-domain rejections with both recipe exits, the cost fields'
presence/omission and sidecar/stdout equality, and the widened heartbeat line format. Two existing
contract assertions were updated because this change is what they assert (the exact stdout key set,
and the below-floor rejection wording). No new flags, no dependency changes.

### Fixed — fanout stall handling killed the dispatcher itself, and mis-read "silence" twice (0.1.47)

Running the `/mgh-init` scout dispatcher directly on Linux (nohup, own terminal) died at
**~10 minutes** on three consecutive runs — no stdout summary, progress sidecar stuck at
`"running"`, `--kill-stale` reporting no orphans: the shape of a hard kill that never reached a
normal exit. Three defects, all on the stall-handling path:

- **The tree kill killed the caller.** POSIX tree kill is `os.killpg(os.getpgid(pid))`, and unit
  children were spawned **without a new session** — so they shared the dispatcher's process group,
  and killing a stalled unit killed the dispatcher. The kill also happens before the stall
  evidence is written, so nothing was logged at all. Units now spawn with `start_new_session`, so
  `killpg` scopes to that unit's own tree. Windows (`taskkill /T /F`) was never affected and is
  unchanged.
- **The silence criterion pointed the wrong way.** Both stream timestamps start at the spawn
  instant and only advance on real bytes, so `min(out_ts, err_ts)` meant "**at least one** stream
  has been quiet this long". Any child that never writes to stderr (common) was therefore judged
  stalled at `spawn + --stall-timeout-s` — which is exactly the 600s / 10-minute death. Now
  `max(...)`: silence means **both** streams went quiet, matching the flag's own
  "no stdout/stderr bytes for this long" wording. The heartbeat's `idle` disclosure uses the same
  source so it can never disagree with the kill criterion.
- **Reads were not byte-level.** Found while locking the fix with a test. `_tail_stream` used
  `TextIOWrapper.read(4096)`, which **blocks until 4096 characters accumulate or EOF**, so the
  "last output" stamp advanced once per 4096-char chunk rather than per byte — a low-volume but
  perfectly healthy unit kept both stamps parked at spawn and was still stall-killed after the
  `max` fix. Now `stream.buffer.read1(4096)` (returns as soon as any byte lands) plus an
  incremental UTF-8 decoder, which is what the function's own docstring ("ts of the last byte on
  this stream") already claimed.

**Boundary change — Ctrl-C no longer propagates to in-flight units.** Because units now lead their
own session, an interactive interrupt reaches only the dispatcher. Its exit path therefore
tree-kills whatever is still registered *before* clearing the registry and deleting the liveness
file — otherwise those children would become orphans that nothing could later find (not even
`--kill-stale`). A hard kill (SIGKILL, where no exit path runs) still leaves the liveness file
behind for `--kill-stale`, and that path is deliberately unchanged. The boundary is disclosed in
the `--stall-timeout-s` / `--kill-stale` `--help` text and in the `/mgh-init` and `/mgh-sdr`
command guides.

Four regression tests added (single-stream silence does not stall-kill; both-stream silence still
does; `_kill_tree` does not terminate its caller, asserted from a child process so a regression
surfaces as an exit code instead of silently killing the test runner; the exit path tree-kills
still-registered children and removes the liveness file). No new flags, no stdout field changes,
no dependency changes.

### Changed — SDD artifacts (openspec) must not point at the private `docs/` tree (0.1.46)

The repo-root `docs/` tree is the maintainer's private workspace: whether it is even committed is
the maintainer's call, so another clone may simply not have it. Distribution was already fenced
off; the *tracked* openspec record was not. A `proposal.md` / spec / task list saying "see the
rationale in that private file" is read by every later agent, and sends them to a file that may
not exist. New rule **R5.11** closes that:

- **Prohibited**: any path under the repo-root `docs/` tree in `openspec/specs/**` or
  `openspec/changes/**` — including the case where that path is the artifact's *subject* (a spec
  defining a doc that lives there). Bare mentions of the directory with no entry after it are
  prose, not pointers, and stay legal.
- **Exempt**: `openspec/changes/archive/**` (frozen history — retro-editing it would be busywork
  that also falsifies the record) and the docs-writing change whose deliverable IS a file there.
- **Replacement style**: name the role, not the path — "维护者私有文档区里的命令人话说明",
  "术语词典", "fan-out 运行手册".
- `check_distributed_purity.py` gained a third scan surface (`openspec/specs/**` +
  `openspec/changes/**`, archive skipped) that applies **pattern 9 only** — SDD artifacts
  legitimately cite rule ids / decision ids / change names on nearly every line, so the other
  families would be pure noise there. Scan set 228 → 272.
- Two false-positive bugs surfaced and were fixed while wiring this up: `glasswing_docs/09`
  matched as if it contained a `docs/09` path entry (a `docs` tail inside a longer word is not a
  path segment), and a bare `docs/` with nothing after it was treated as a pointer.
- Six active specs and two active changes de-referenced. Two of them
  (`distribution-purity`, `plain-language-doctrine`) had also become **factually stale** from the
  previous entry — they still described man pages as shipped and `docs/man/**` as part of the
  purity scan set — and were corrected to match the code.
- `tests/test_distributed_md_purity.py` covers the new surface: the three-way scan-mode dispatch,
  the archive + carve-out skips, and the pointer/exempt matrix (29 tests).

### Changed — repo-root `docs/` dropped from distribution; man pages no longer installed (0.1.45)

The repo-root `docs/` tree (man pages, glossary, upstream index, review/analysis notes) is
the maintainer's private workspace and was never meant to ship. It had drifted: `install.sh`
copied `docs/man/` into `<target>/docs/man/`, and all 12 command shells carried a
`> 人类读者:通俗说明见 docs/man/<cmd>.md。` pointer. Both are dead ends for anyone but this
working copy — `docs/man/mgh-sdr.md` was not even git-tracked, so a fresh clone installed the
tree without the very page two shells pointed at. Fixed in both directions:

- `install.sh` no longer lands `docs/man/`; the 12 shell pointers are deleted outright (not
  reworded — a reworded pointer is still a reference to a non-shipped tree). `install.ps1`
  never had the step, so the two installers now agree instead of silently diverging.
- `check_distributed_purity.py` gained pattern 9 (**repo-root `docs/` reference**:
  `docs/man/*`, `docs/glossary.md`, `docs/upstream-index.md`, `docs/upstream/**`, …) and now
  scans the shipped runtime surface too — `core/scripts/**`, `releases/*/hooks/**`,
  `releases/opencode/plugins/**`, `*.py`/`*.ts`/`*.json` — not just md (scan set 185 → 228).
  Nine script comments citing an upstream doc path or an openspec change-folder name were
  cleaned (e.g. `discover_controls.py` cited the upstream design-doc path).
- Patterns split into two families by who can hit them: **pointers** (change-folder names,
  upstream doc paths, repo-root docs) are scanned in every shipped file; **dev-manual
  vocabulary** (`R5.x`/`FDn`/`Dn`/dev-meta) only in shipped md. The host agent is required to
  run the scripts without reading their source, so an `R5.9` in a script comment never reaches
  the target, while the pointer a reader might follow is exactly what must not dangle.
- Two families sharing the `docs/` prefix stay legal and are pinned by tests: the target
  project's **runtime-generated** `docs/security-controls/` + `docs/test-conventions/`, and
  the `core/docs/` Apache-2.0 attribution records (ships as `<dest>/mgh-core/docs/`).
  `core/prompts/**` is skipped for pattern 9 — it is an R1-frozen verbatim port whose body
  mentions the *upstream* project's own doc layout (`docs/manifests/tree`,
  `docs/config/non-code files`), so flagging it would be an unfixable failure. That prose is
  the one known residual: it still ships, because R1 forbids editing it.
- Docs corrected where they described `docs/` as shippable: AGENTS.md R5.10 gained the 9th
  prohibited class, the R3 audience table split `人类·随包分发` from `人类·仅研发仓`, and the
  directory-tree comments in AGENTS.md + README.md no longer call `docs/` a "分发指南".
- `tests/test_distributed_md_purity.py` guard **inverted**. It used to assert the opposite
  (man pages MUST ship; every shell MUST carry the pointer) — a guard that would have actively
  blocked this fix. It now asserts `docs/` is not a scan root, no shipped file points at it,
  the two exempt families stay clean, and the script-family split holds (21 → 26 tests).

### Added — fanout crash-storm resilience: fast-fail cooldown + rate-limit storm truncation + bounded failed re-dispatch (0.1.44)

Quota-limited intranet gateways (observed: 100 calls / 10 min) turn a full quota
into a **fast-fail storm**: units die in seconds (opencode retries a 429 twice,
source-verified `retries: 2`), the runner requeues them with zero delay, the next
wave hits the quota again — a full storm cycle (1–2 min) runs far faster than the
10-minute quota window recovers, burning the night on
storm → breaker → resume → storm. Worse, a polite `failed:` ack after a provider
error writes a terminal `.failed` marker that enumerators exclude — the tier
"completes" with a coverage hole. Builds on the landed stall-containment
prerequisite (output-tail buffers / run.log evidence + slot-backfill loop are the
classification data source and cooldown mount point)
(`harden-mgh-fanout-crash-storm-resilience`):

- **Fast-fail cooldown** (`fanout_runner.py --cooldown-s`, default 300; `0` = off,
  also disables the pre-breaker backoff): ≥3 requeue events (crash/timeout/stall/
  spawn-error units returning to the queue tail; failed acks and pre-spawn anchor
  failures never count — they terminate without requeueing) within a 120s sliding
  window pause NEW dispatch while in-flight units keep running and harvesting.
  The wait is capped by remaining `--time-budget-ms` minus an in-flight convergence
  margin (pure `_cooldown_cap_s`); budget-starved cooldowns degrade to continuing
  immediately with a stderr disclosure. stdout adds `cooldowns:<n>`.
- **Pre-breaker bounded backoff**: when the zero-progress breaker is about to exit
  2 and the budget allows, one single "cooldown → full disk re-derivation →
  re-observe" round runs first — disk growth disarms the breaker, still-zero-growth
  exits stalled. At most once per call; the `stalled` contract is byte-identical.
- **Rate-limit crash classification + storm truncation** (`--no-rate-limit-stop`
  disables): every crash terminal's output tails (reader-thread buffers, the
  stall-containment data source) are classified against `429` / `too many
  requests` / `rate limit` / `quota` (case-insensitive; crash terminals only —
  ok/failed/timeout/stall never classified; overflow-marked crashes stay
  overflow). Crashes ≥ `--wave` since the last disk terminal advance that are ALL
  rate-limit stop dispatch immediately (fast path, ahead of any new cooldown) and
  exit 2 with `rate_limited:true` + `rate_limited_crashes:[ids]` + a wait-one-
  quota-window recipe. Signature drift (all unknown) degrades gracefully to the
  cooldown + breaker path; non-rate-limit crashes never count toward the threshold.
- **Bounded failed re-dispatch**: the five tier enumerators
  (`list_scout_batches`/`list_clusters`/`plan_aggregate`/`list_rule_jobs`/
  `diff_group`) gain `--include-failed` (default off = byte-identical stdout):
  failed units re-enter `pending[]` under their canonical ids with their existing
  `failed_marker` absolute paths (identity always from the enumerator's forward
  derivation, never filename stems; done counts stay marker-truth via a
  re-inclusion add-back). `fanout_runner.py --retry-failed` forwards
  `--include-failed` to the enumerator and deletes a claimed unit's `.failed`
  marker at claim (evidence stays in the unit's `*.run.log`); a re-failure writes
  a fresh marker and each unit is retried at most once per call. stdout adds
  `retried_failed:<n>`.
- **Call-surface discipline**: `discipline_core.py` + `init-stage/{scout,t1,t3}.md`
  + both sdr shells gain two recipe branches — `stalled:true` with a clean
  `resume_state --check` → provider congestion → re-dispatch the same command
  (NEVER rewrite inputs / delete markers / write micro-scripts); tier wrap-up
  `failed>0` with a provider-transient run.log shape → at most one `--retry-failed`
  round, then accept the gap and disclose. Contract lint
  (`tools/check_contracts.py`) asserts the three new runner flags and the five
  enumerator `--include-failed` flags.
- **Diagnostics invariants**: three counters that never share a window (cooldown
  requeue-time window / storm disk-advance window / breaker dispatch window); the
  post-cooldown drain re-list de-duplicates against the in-memory queue so a unit
  is never queued twice; summary keys are additive only
  (`cooldowns`/`retried_failed`/`rate_limited` always; `rate_limited_crashes`
  conditional, same shape as `context_overflow`).

### Added — `/mgh-init` T1 deterministic small-cluster packing — quota amortization, opt-in (0.1.43)

Quota-constrained intranet LLM gateways bill per call (observed: 100 calls / 10 min),
and every T1 unit pays a fixed 3–5 call overhead (session start / read task / read
input / ack) regardless of cluster size. A real run with 221 small clusters
(inputs 1.6–4.3KB) spent ≈900 calls — near a third of the quota — on overhead alone.
Bigger waves cannot help under a call-rate cap; fewer units can
(`improve-mgh-init-t1-cluster-packing`):

- **Pack partition** (`list_clusters.py --pack-bytes B`, default 0 = off; `--pack-max N`
  member cap, default 8): same-category clusters whose whole-cluster input fits
  `--max-unit-bytes` are sorted by `(bytes asc, cluster_id)` and greedily packed;
  oversize/`::shard-<n>` units and terminal-failed clusters never enter a pack. Pack id
  = `pack::<category[:64]>::<sha8(sorted member ids)>` — partition and id are pure
  functions of `clusters.json` + flag values (same input, same packs, any cwd).
- **One merged input per pack** (`<inputs/t1>/<safe(pack_id)>.input.json`, body
  `{repo, pack_id, category, members[], checkpoints[]}`): one subagent Read amortizes
  the fixed overhead over all members. `pending[]` pack items carry the pack id in the
  `cluster_id` field slot (dispatcher + ack state machine consume it unchanged) and a
  `members[]` list with per-member absolute paths; stdout adds `cluster_total`/
  `cluster_done` (packing path only). Paging and `--orch-budget-bytes` shrink apply
  to the packed list unchanged.
- **Cluster-level markers stay the only truth source**: a pack is pending iff ≥1
  member lacks `.done`; a re-dispatched pack skips done members via the dual-form task
  template (`fanout/t1-task.md` Form B: probe `checkpoints[]` → skip done → induce per
  member → `unit` = member cluster_id → ack `ok <pack_id> <n>` /
  `failed <member ids>: <reason>`). Recovery granularity stays cluster-level; a
  pack-level `.failed` (written by the dispatcher on a failed pack ack) recovers by
  deleting the marker and re-listing. Pack-level markers are excluded from the orphan
  audit (`init_tier.orphan_markers`).
- **Zero changes** to `fanout_runner.py` (packed pending flows through the same field
  slots), T1 record schema, `validate_t1_records.py`, the T2 records gate, and
  `resume_state.py` (cluster-level counting is pack-agnostic by construction).
- **Enablement surface**: the orchestrator's `list_clusters.py` call lines
  (`init-stage/t1.md` manual path + `discipline_core.py` t1-pack recipe + man page);
  suggested quota value 16384. The dispatcher main path does not yet forward the flag
  (its enumerator argv is fixed by the zero-change constraint) — hand-dispatch path
  enables packing today; dispatcher pass-through is a small follow-up if wanted.
- Off-path regression is byte-identical (no new stdout fields, zero pack code);
  invalid combinations (`--pack-max` without `--pack-bytes`, packing without
  `--materialize`) exit 2.

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
