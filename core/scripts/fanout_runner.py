#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
fanout_runner — deterministic tier-aware slot-backfill dispatcher for /mgh-init
fan-out (tiers: scout | scout-merge | t1 | t2 | t3; sdr for /mgh-sdr).

Replaces the per-unit orchestrator LLM turn with a pure-code loop: consume the
pending work-list from the tier's enumeration script (`--materialize` mode)
stdout, build each subagent's task message from a FIXED template + verbatim
field substitution, and spawn host-CLI subprocesses under an in-flight cap of
`--wave`: any unit reaching a terminal state (ok/failed/timeout/stall/crash)
immediately frees its slot and the next queued unit is dispatched (SLOT
BACKFILL — a hung unit occupies only its own slot, never the whole run; there
is no wave barrier). Before taking a unit from the queue the dispatcher lazily
stats its `.done`/`.failed` marker (already terminal on disk → skipped, never
spawned). Zero LLM turns inside the dispatch loop; every path field is passed
verbatim from the enumerator stdout (path spelling failures become impossible
by construction).

Tier mapping (single point, TIERS below): each tier names its enumeration
script + forwarded flags, task-message template, placeholder set, anchor-tree
path fields, fanout agent name, and marker `tier` value. The backfill loop, ack
state machine, timeouts, sidecar, and audit copies are shared — no per-tier
branches in the loop body.

  scout: list_scout_batches.py --scout-plan/--checkpoints/--materialize
         template fanout/scout-task.md; agent init-scout-fanout
  t1:    list_clusters.py --clusters/--candidates/--checkpoints/--materialize
         template fanout/t1-task.md; agent init-induct-fanout
         (list_clusters exit 2 = scout-incomplete-gate → passed through as
         exit 2 with its stderr recipe; NEVER swallowed into a crash loop)
  t2:    plan_aggregate.py --node t2/--init-dir/[--budget]/--materialize
         (map stage only; rollup is a separate orchestrator step)
         template fanout/t2-task.md; agent init-synthesis-fanout
         (marker-aware enumerator: D2a — plan_aggregate excludes terminal
         shards from pending[] and reports total/done/failed; plan_path =
         <init-dir>/run_config.json so the sidecar/liveness home = <init-dir>)
  scout-merge:
         plan_aggregate.py --node scout-merge/--init-dir/[--budget]/--materialize
         (map stage only; rollup is a separate orchestrator step; same
         marker-aware enumerator + run_config.json home as t2; shards are
         hard-bounded at candidate granularity)
         template fanout/scout-merge-task.md; agent init-scout-merge-fanout
  t3:    list_rule_jobs.py --inventory/--format/--rules-dir/--checkpoints/
         --target/--materialize
         template fanout/t3-task.md; agent init-rulewriter-fanout
         (placeholder set uses rule_path, no checkpoint_path/slice_dir)

Task message template: `<mgh-core>/prompts/fragments/fanout/<tier>-task.md`
(placeholder set per tier, documented below). An audit copy of each filled
message is written to `<inputs-dir>/<unit>.task.md` (small; `--purge-audit`
lists them).

Host spawn mapping (spike-verified, see change design D3):
  opencode: `opencode run --agent <tier-agent>` (cwd=repo, task via stdin)
            — the fanout agents are `mode: primary` clones of the stage
              agents (opencode `run` refuses `mode: subagent` agents and
              silently falls back to the default agent).
  claude:   `claude -p --agents <inline JSON> --allowedTools ...`
            (cwd=repo, task via stdin)
  dsh:      `dsh --profile mgh --patch <mgh-core>/dsh/tiers/<tier>.yml -`
            (cwd=repo; the task text travels via the child env var
             `MGH_TASK_TEXT`, NOT stdin/argv — headless has no stdin task
             channel and multi-line argv truncates at the first newline
             through the npm `.cmd` shim; the tier mount file's fixed
             template row `task: !!js process.env.MGH_TASK_TEXT` routes the
             env var into the headless runner. Pre-spawn gate: mount file or
             `mgh` profile missing → exit 2 + recipe, zero spawns.)
Host detection: `--host` explicit > opencode in PATH > claude in PATH > dsh in
PATH (shutil.which; dsh appended at the chain end — dual-host machines keep
their existing behavior); none present → exit 2 + fallback recipe (the
orchestrator falls back to the existing manual dispatch, behavior unchanged).

Child execution-environment isolation (OPTIONAL, default OFF — absent flags
mean a byte-identical legacy spawn). These are MANUAL/LEGACY capabilities: no
mgh command flow references them (the sdr flow neither presets credential
commands nor appends --cred-file):
  --cred-file <run>/cred.json  static credential injection (opencode host form
            only; claude/dsh forms exit 2): per-unit child config
            `<run>/childcfg/<unit>/opencode/opencode.json` (a copy of the
            global config with the cred-declared provider overridden to the
            static baseURL + apikey entry, id unchanged) + child env
            `XDG_CONFIG_HOME` (per-unit child config dir) and
            `XDG_DATA_HOME` (`<run>/ocdata/<unit>`) — the child sees ONLY its
            own config (no login flow of its own; SSO gateways with one-time
            tickets make per-child logins structurally fail) and its own data
            dir (logs/sqlite/repos stop colliding across concurrent fat
            clients). Schema of the cred file is validated by
            `mgh_credentials.validate_cred_payload` (the SAME validator the
            producer runs — one closed set); acquire the file via
            `mgh_credentials.py`. The apikey is never echoed to stdout/stderr
            or written anywhere except the child config file.
  --isolate-data   per-unit `XDG_DATA_HOME` alone (no credentials) — for
            deployments whose only problem is the concurrent data-dir
            collision. Implied by --cred-file.
Credential-expiry fast-stop: with --cred-file, non-ok terminals get their
output tails scanned against the cred file's `expired_signatures[]`; the first
hit stops NEW dispatch immediately (priority above the rate-limit storm and
cooldowns), exit 2, stdout `credential_expired` + `credential_expired_units`,
stderr recipe = re-acquire → update cred file → `--resume --retry-failed`.
Disk marker semantics unchanged. Special-auth advisory: when the PROJECT
carries `<repo>/.mgh/special-auth.md` (optional, deployment-owned) and no
--cred-file was passed, one stderr note points at it — command-agnostic, all
tiers, exit code untouched.
--dry-run (dispatch form) is a PURE PLAN: zero writes, zero spawns — the unit
list, the would-write paths and the command form go to stdout; the
--kill-stale/--purge-audit review guards are separate and unchanged.

State machine (disk markers are the ONLY truth source): `ok`/`oversize` ack or
`.done` marker → done; `failed` ack → this script writes the `.failed` marker
(body {unit,reason,tier}; terminal, not retried, does not block other slots);
stall/timeout/crash/spawn-error with no ack and no marker → the unit is
re-enqueued for in-run re-dispatch AND stays pending for `--resume` (crash !=
confirmed failure). Unparsable stdout → trust the disk markers only.

Per-unit stall detection + surgical tree kill: two reader threads per child
roll a byte-level last-output timestamp + an 8KB tail per stream; silence >=
the run's EFFECTIVE silence window (initial value = `--stall-timeout-s`,
default 900) or total runtime >= `--call-timeout-s` kills that unit's WHOLE
process tree (`taskkill /pid <pid> /T /F` — the npm `.cmd` shim chain's real
host-CLI process dies too, never an orphan burning tokens; POSIX that unit's
own process group: SIGTERM, then a short grace re-check and SIGKILL
escalation while the group still survives). The kill NEVER reaches the
dispatcher: units are spawned with `start_new_session`, so each leads its own
session. "No ack, no marker" → the unit stays pending for re-dispatch —
UNLESS the kill itself FAILED (survived SIGKILL / both taskkill passes): then
the survivor OWNS the unit — no re-dispatch this run, the pid stays in the
liveness children[] for `--kill-stale`, and the summary's `kill_failed[]`
names it (the unit's marker lands whenever the survivor finishes, else a
later `--resume` re-dispatches).

The silence criterion means "this unit has produced nothing for that long", NOT
"this unit is hung": on a rate-limited gateway the usual cause is the call
sitting in the gateway's queue, which is locally indistinguishable from a real
hang (the same silence, the same zero output). It is a CONVERGENCE BOUND for
this run — an upper limit on how long one slot may sit idle — never a health
diagnosis. A killed unit re-queues at the tail, so a false kill throws away the
work already done AND re-pays the queue behind the same congestion. Two escape
hatches: `--stall-timeout-s 0` disables the criterion outright (then
`--call-timeout-s` alone bounds convergence), and the effective window WIDENS
within a run the moment a stall-killed unit completes on re-dispatch
(`W <- min(2W, --call-timeout-s x 0.8)`, stderr-disclosed once per triggering
unit, always <= `--call-timeout-s`) — self-evidence that the window was too
tight for this run's contention. Widening is per-run only, never persisted.

Every spawn terminal (ok included) appends the captured stdout/stderr tails to
`<checkpoints>/<tier>/<unit-id-sanitized>.run.log`; non-ok terminals name the
run.log absolute path on stderr.

Session isolation boundary: because units lead their own session, an
interactive Ctrl-C delivered to the dispatcher no longer reaches the in-flight
units. The dispatcher's exit path tree-kills whatever is still registered
before deregistering, so a normal Ctrl-C stop leaves nothing behind; a HARD
kill (SIGKILL, where no exit path runs) leaves orphans disclosed by the
liveness file and cleared with `--kill-stale`.

Zero runtime deps (Python >=3.10 stdlib: argparse/codecs/collections/
concurrent.futures/datetime/json/os/pathlib/shutil/signal/subprocess/sys/
tempfile/threading/time).

CLI contract (`--help` is the contract surface, R5.1):
  py fanout_runner.py --tier scout|scout-merge|t1|t2|t3|sdr [tier flags] [options]

  scout tier (default; existing call shape unchanged):
    --scout-plan <scout_plan.json> --checkpoints <scout-dir>
    --inputs-dir <inputs-dir>
  t1 tier:
    --clusters <clusters.json> --candidates <controls_candidates.json>
    --checkpoints <t1-dir> --inputs-dir <inputs-dir>
  t2 tier (map stage only):
    --init-dir <target>/.mgh-init [--budget <bytes>]
    --checkpoints <t2-dir> --inputs-dir <inputs/t2>
    (run_config.json under --init-dir anchors the sidecar/liveness home;
    the enumerator reports needs_reduce + marker-aware pending)
  scout-merge tier (map stage only; call shape identical to t2, enumerator
  node = scout-merge):
    --init-dir <target>/.mgh-init [--budget <bytes>]
    --checkpoints <scout-dir> --inputs-dir <inputs/scout-merge>
  t3 tier:
    --inventory <controls_inventory.json> --format opencode|claude
    --rules-dir <rules-dir> --target <target> --checkpoints <t3-dir>
    --inputs-dir <inputs-dir>

  --tier            scout|scout-merge|t1|t2|t3|sdr (default scout). Selects the
                   enumeration script, template, placeholder set, and fanout
                   agent.
  --checkpoints     tier checkpoint dir (markers live here; forwarded).
                   REQUIRED for dispatch; OPTIONAL for --kill-stale recovery
                   (scan hint only).
  --inputs-dir      per-unit input dir (forwarded as --materialize; audit
                   copies `<unit>.task.md` land here too). REQUIRED for
                   dispatch; OPTIONAL for --kill-stale recovery (scan hint
                   only).
  --host            claude|opencode|dsh explicit; default: opencode in PATH,
                   else claude in PATH, else dsh in PATH, else exit 2 + recipe.
  --wave            in-flight subprocess cap (default 5) — a slot-backfill
                    concurrency limit, not a batch size.
  --time-budget-ms  soft deadline: stop dispatching new units, drain in-flight,
                    exit 0 with partial:true (re-dispatch the same command).
                    RECOMMENDED = host per-call timeout x 0.8 (e.g. host
                    900000ms -> 720000; claude host caps Bash at 600000ms ->
                    480000). MUST stay BELOW the host per-call timeout so the
                    soft deadline always fires first (a host hard-kill loses
                    in-flight units and degenerates into a kill/re-dispatch
                    loop). When passed, `--call-timeout-s` MUST be passed
                    explicitly and stay below budget x 0.8 (spawn-time
                    validation, exit 2 otherwise).
  --call-timeout-s  per-subprocess absolute timeout in seconds (default 7200s,
                    calibrated for slow intranet LLM endpoints: one unit = one
                    full LLM subagent run at minutes-level, ~4x headroom;
                    better-slow-than-killed — a killed unit leaves no marker,
                    stays pending, and re-dispatch wastes a whole run). The
                    kill path is the whole-tree kill (see stall detection).
  --stall-timeout-s per-unit output-silence window in seconds, INITIAL value.
                    FOUR-segment value domain: `0` = disable the criterion
                    outright; 1..59 = rejected with exit 2 (this is the HARD
                    REJECTION FLOOR = 60); 60.. = a valid silence window. The
                    default 900 is the OUT-OF-HOST MANUAL-RUN default ONLY —
                    it is NEVER the rejection floor and MUST NOT be called one;
                    a host-driven run (one that passes --time-budget-ms) MUST
                    pass this flag explicitly with a value < --call-timeout-s,
                    NEVER relying on the default (the host-driven
                    --call-timeout-s is far smaller, so the stall < call
                    spawn-time check would exit 2 and make the tier unusable);
                    recommended host-driven value: 300.
                    No stdout/stderr bytes for this long -> the
                    unit's whole process tree is killed and the unit stays
                    pending for re-dispatch. Byte-silence means the unit
                    produced NOTHING for that long; it does NOT mean the unit
                    is hung — on a rate-limited gateway the usual cause is the
                    call waiting in the gateway's queue, which is locally
                    indistinguishable from a real hang. The criterion's job is
                    to bound how long one slot may sit idle (this run's
                    convergence bound), never to diagnose unit health.
                    Byte-silence means BOTH streams idle (the clock takes the
                    newer of the two streams' last-byte stamps), so a unit
                    whose stderr never emits is not mistaken for silent.
                    Calibration: default = p99(completed-unit runtime) x 2,
                    rounded down to the minute and never below the calibrated
                    900 (a property of the DEFAULT, not of the accepted value
                    domain — see the four-segment domain above) (observed
                    sample n=84: p50 134s / p95 229s / p99 325s / max 325s ->
                    650s -> 600s -> floor 900s). That sample is the SURVIVING
                    population only — units killed for gateway queueing are
                    absent from it by construction — so it is an upper estimate
                    for healthy units and MUST NOT be read as "past this it
                    deserves to die". Re-calibrate from the runtime_* fields
                    every exit reports (see stdout below). The EFFECTIVE window
                    widens within a run on false-kill self-evidence: if a
                    stall-killed unit completes on re-dispatch, the window
                    becomes min(2x current, --call-timeout-s x 0.8) for the
                    rest of the run and the event is disclosed on stderr.
                    `0` disables the silence criterion entirely — then
                    convergence is bounded by `--call-timeout-s` ALONE, so a
                    host-driven run (where the host hard timeout also applies)
                    SHOULD tighten that value; the `stall < call` ordering
                    constraint does not apply in this mode. The kill is
                    session-scoped: units lead their own session, so it NEVER
                    terminates the dispatcher.
  --hb-interval-s   stderr in-flight heartbeat period in seconds (default 60).

  TIMEOUT INVARIANT (four levels, inner < outer, >=20% headroom per level):
    stall-timeout-s < call-timeout-s < time-budget-ms x 0.8 < host per-call
    timeout
  `--stall-timeout-s 0` (criterion disabled) drops the innermost level: only
  `call-timeout-s < time-budget-ms x 0.8` is then checked.
  Spawn-time validation (fail-loud, exit 2 + compliant-values recipe BEFORE
  any spawn or enumerator side effect): passing --time-budget-ms REQUIRES an
  explicit --call-timeout-s below budget x 0.8, and stall < call whenever the
  stall criterion is on (`--stall-timeout-s > 0`). The
  defaults (call 7200 > any hour-level host budget) are for out-of-host
  manual runs only — a host-driven run that kept them is guaranteed to
  degenerate into the host hard-killing the tree first (observed 2026-09-14).
  Applies to all tiers identically (a t1/t3/sdr unit = one full LLM subagent
  run, same calibration as scout).

  QUOTA ADMISSION MODE (optional, all tiers): `--quota-calls N` +
  `--quota-window-s W` (BOTH required to activate) arm an ESTIMATED
  sliding-window admission gate for calls-per-window-rate-limited gateways:
  the dispatcher tracks this run's unit-dispatch timestamps, and a new unit is
  only dispatched while `dispatches-in-window x K + K <= N` (K =
  `--quota-calls-per-unit`, default 10 — a conservative upper bound of the
  model calls one unit burns INSIDE its host-CLI child, which the dispatcher
  cannot observe). Short on margin -> no dispatch; the loop sleeps in <=1s
  shards until the earliest timestamps slide out of the window, in-flight
  units keep running and harvesting throughout, and each wait episode is
  disclosed on stderr with the arithmetic and the expected resume time. The
  wait is bounded by the remaining time budget (exhausted -> the existing
  soft-deadline partial exit; `--resume` starts a fresh window — the window is
  in-process only, the gateway-side spend is never tracked across processes).
  Quota mode also upgrades storm cooldowns whose requeue events include a
  rate-limit-signature crash: the cooldown then waits out the quota window
  reset (last signature event + W) instead of the fixed --cooldown-s, and the
  crash-storm truncation fires only AFTER one full window-reset wait has
  completed and rate-limit crashes still recur (before that, a window
  exhaustion is treated as self-healing). HONEST BOUNDARY: admission is an
  ESTIMATE (real per-unit call counts are gateway-side facts); an
  underestimate can still eat a 429 — the window-reset cooldown and the
  truncation layer backstop it. Without the quota flags every tier's
  dispatch/cooldown/truncation/stdout/sidecar behavior is byte-identical to
  the pre-quota runner (the stdout `quota` key is absent).
  --resume          re-derive pending from disk markers (same entry point as a
                    fresh call; kept for call-shape parity with the shell).
  --pending-file    TEST HOOK: consume the tier listing from a file instead of
                    invoking the enumerator (never spawns; ignores --host).
  --kill-stale      orphan-tree cleanup: inspect the liveness file(s)
                    `fanout_runner.<tier>.pid` and kill what it records:
                    form (1) runner PID alive AND cmdline matches
                    `fanout_runner.py` -> kill the whole tree (Windows
                    `taskkill /pid <pid> /T /F`; POSIX process-group
                    SIGTERM, re-checked and escalated to SIGKILL while the
                    group survives); form (2) runner PID dead/mismatched BUT
                    a `children[]` PID is alive AND its cmdline's EXECUTABLE
                    TOKEN (argv[0] path basename — case-insensitive,
                    .exe/.cmd/.bat stripped, never a substring match over the
                    whole command line) is the host CLI (`opencode`/
                    `claude`/`dsh`) -> kill each such child tree. Covers "the runner
                    was hard-killed along with the orchestrator but its host-CLI
                    children keep burning tokens". Mismatched/dead PIDs are
                    NEVER killed (PID-reuse guard: the cmdline must match —
                    a reused PID is only a stale record, the liveness file is
                    just removed). Process cmdline probes try classic `wmic`
                    first and fall back to the PowerShell CIM query (wmic is
                    removed on Windows 11 24H2+); when a PID is alive but
                    EVERY probe is unavailable the command fails loud (exit 2,
                    stderr recipe) and NO liveness file is removed —
                    undecidable orphan ownership preserves the evidence, never
                    "zero kills + destroy evidence + fake success". The scan
                    root anchors on the tier plan artifact's run dir (the same
                    plan-path re-anchoring the dispatch side uses: sdr's
                    directory-shaped --repo and t2's --init-dir resolve to the
                    run dir, not its parent), falling back to the
                    checkpoints/inputs-dir neighbourhoods; both artifact flags
                    are OPTIONAL in this mode. Needed after a HARD kill only:
                    units lead their own session, so an interactive Ctrl-C no
                    longer reaches them through the tty, and the dispatcher's
                    exit path tree-kills whatever is still registered before
                    deregistering. DESTRUCTIVE: a real kill REQUIRES a prior
                    `--dry-run` review — invoking `--kill-stale` without
                    `--dry-run` when targets are detected exits 2 + recipe
                    (same guard shape as --purge-audit). Idempotent: no stale
                    -> `killed: []`, exit 0. Tier-agnostic (works for all
                    tiers identically; mechanism depends only on the liveness
                    file-name convention). stdout =
                    {"kill_stale": {"killed":[{"pid","tier","kind"}],
                    "removed":[pid-files], "none":bool}}.
  --purge-audit     `<inputs-dir>/*.task.md` audit cleanup (dry-run LIST ONLY;
                    actual deletion = remove the files with the host shell
                    after reviewing the listing; destructive op guard, R5.3b).
  --dry-run         with --kill-stale: list the PIDs that would be killed, kill
                    nothing; with --purge-audit: list without deleting; alone:
                    skip dispatch (fill audit copies, spawn nothing).
  --template        override the task-message template path (default: sibling
                    prompts/fragments/fanout/<tier>-task.md of this install).

Liveness file (`<init-dir>/fanout_runner.<tier>.pid`): the dispatcher mode
(none of --kill-stale/--purge-audit/--pending-file) atomically writes it at
startup — body {pid, started_ts, tier, host, cmdline, children[]} where
children[] = the in-flight host-CLI child PIDs ({pid, unit, tier}, registered
at each spawn via the Popen pid, removed at that unit's terminal event) — and
deletes it on ANY exit path (try/finally). It is an ORPHAN SIGNAL, not a lock:
a hard-killed runner leaves the file behind and `--kill-stale` disambiguates
via PID liveness + cmdline matching. Not read by resume_state for progress
(disk markers remain the only truth source).

stderr heartbeat: per-unit spawn / per-unit terminal status
(ok|failed|timeout|crash|stall) lines shaped
`[fanout_runner <tier>] +HH:MM:SS wave=<seq> unit=<id> <event> done=<d>/<total>`
(wave= = that unit's dispatch ordinal this run; elapsed = time.monotonic()
relative to runner start), plus every `--hb-interval-s` one in-flight
disclosure line per running unit:
`[fanout_runner <tier>] +HH:MM:SS inflight=<k> unit=<id> idle=<s>s
done=<d>/<total>` (idle = seconds since that child's last output — a human
watches the host TUI distinguish "slow" from "hung"). Host TUIs (opencode
Bash tool renders the merged stdout+stderr sliding tail while running; claude
includes stderr in the Bash result) surface these lines live. stdout contract
unchanged: still exactly one JSON summary line at the end.

stdout (structured JSON summary; stderr = diagnostics/progress only, R5.3b):
  {"runner": "fanout_runner", "tier": "scout|scout-merge|t1|t2|t3|sdr", "repo": "...",
   "host": "claude|opencode|dsh|test", "total": N, "done": M, "failed": F,
   "pending": P, "wave": W, "waves_run": K, "partial": bool,
   "stall_killed": [units stall-killed this run],
   "runtime_p50_s": S, "runtime_p95_s": S, "runtime_max_s": S
                     (COMPLETED units' runtimes, integer seconds; all three
                     omitted — absent, never 0 — when the run completed none),
   "stall_killed_slots_s": X, "stall_killed_slot_pct": P
                     (cost visibility, always present: seconds of slot time
                     burnt by stall kills this run, and that as a share of this
                     run's slot-seconds = elapsed x --wave; 0 / 0.0 when nothing
                     was stall-killed),
   "stall_window_s": W (the run's EFFECTIVE silence window at exit — present
                     ONLY when the adaptive widening fired this run),
   "stalled": bool,
   "stalled_pending": [{"id", "done_marker_exists", "failed_marker_exists"}]
                     (only when stalled:true),
   "kill_failed": [units whose tree-kill FAILED (only when non-empty; the
                   survivor owns each — no re-dispatch this run, pid kept in
                   liveness children[] for --kill-stale)],
   "context_overflow": [units whose crash stderr matched a context-overflow
                     signature (only when non-empty; additive diagnosis —
                     the narrow---budget recipe rides the unit's run.log and
                     stderr lines; outcome semantics unchanged)],
   "audit_purged": [names] (with --purge-audit),
   "kill_stale": {killed, removed, none} (with --kill-stale),
   "quota": {calls, window_s, calls_per_unit, admission_waits}
                     (quota admission mode only — the key is ABSENT without
                     the quota flags; calls/window_s/calls_per_unit echo the
                     configured quota, admission_waits counts this run's
                     dispatch-pause episodes; the sidecar carries the same
                     body, derived from the same snapshot)}
(waves_run = cumulative units dispatched this run; the summary's `wave` stays
the concurrency cap.)

Zero-progress convergence circuit breaker (--stall-waves, default 2): slot
backfill has no wave boundary, so TWO observation points feed the same
zero-growth counter (each re-derives the done+failed terminal count from disk
once, markers = only truth): (a) every K = --stall-waves x --wave newly
dispatched units; (b) the queue-drain re-list — when the queue is empty,
in-flight is zero, and the disk re-derivation STILL shows pending units, that
observation counts too and those units get one more attempt round in THIS run
(the lone-poison-unit tail "kill -> re-dispatch -> kill" that never fills a
K-window is truncated in-run after --stall-waves consecutive zero-growth
observations, instead of bouncing partial:true to the orchestrator for an
endless cross-call re-dispatch loop). Trip = stop dispatching, drain, exit 2,
stdout stalled:true + stalled_pending[] (per stuck unit: id + its actual
.done/.failed marker existence on disk), stderr diagnosis recipe (stop re-
dispatching; diagnose via `resume_state.py --check`; cross-check each unit's
marker existence). A stall-killed unit does NOT raise the disk count (no
marker) — a deterministically-hung unit is exactly what this breaker
truncates; an occasional stall whose re-dispatch succeeds resets the window.
Deadline partial early-exit and clean completion stdout/exit codes are
unchanged.

Progress sidecar (human-facing run-state disclosure, written on dispatch
windows + on every exit): <init-dir>/fanout_progress.<tier>.json — the
init-dir that holds the tier's plan artifact (scout_plan.json / clusters.json /
controls_inventory.json) — holds {ts, host, tier, total, done, failed,
pending, wave, waves_run, wave_done_avg_s, eta_batches, state} with state in
{running, exited-partial, exited-clean} (wave = concurrency cap; waves_run =
cumulative dispatches; wave_done_avg_s = mean per-unit runtime this run). It
carries the SAME cost-visibility fields as the stdout summary (runtime_p50_s /
runtime_p95_s / runtime_max_s / stall_killed_slots_s / stall_killed_slot_pct,
plus stall_window_s when the window widened) from the same snapshot.
It is FOR HUMANS: watch it from a second terminal (e.g. `Get-Content -Wait`);
the orchestrator and any agent NEVER read it (not a truth source, not a
contract artifact — resume_state.py and init_manifest.json neither read nor
validate it; a stale copy — including a pre-rename `fanout_progress.json` —
is harmless). Counts derive from the same snapshot as the stdout summary
(single test asserts they agree). Write failures warn on stderr and never
break the run.

Exit codes (R5.3b): 0 ok (incl. partial:true) · 1 misuse of inputs
(tier artifact/inputs-dir missing, template unreadable, unparsable pending) ·
2 CLI misuse / host CLI unavailable / tier gate refusal (t1
scout-incomplete-gate passed through with the enumerator's stderr recipe,
fail-loud) / timeout-invariant violation (spawn-time, exit 2 + compliant-
values recipe) / zero-progress stall (convergence circuit breaker, dispatch-
window anchored; stdout carries stalled:true + stalled_pending[]). Idempotent;
no TTY; reads/writes only inside the repo-anchored tree (every path field is
resolve()-anchored against `repo` before spawn; out-of-tree → that unit is
marked failed with reason=path-drift and NEVER spawned).
"""
from __future__ import annotations
import argparse
import codecs
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

# Self-locate this script's dir so sibling scripts / the prompts tree resolve
# under any cwd / host-agent invocation (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from init_tier import safe_unit_filename  # noqa: E402 — sibling import (below)
from mgh_credentials import validate_cred_payload  # noqa: E402 — sibling import:
# one closed-set cred schema shared with the producer script (the dispatcher
# never redefines what "a valid cred file" means)

DEFAULT_WAVE = 5
# Calibrated for slow intranet LLM endpoints (one unit = one full LLM subagent
# run, observed minutes-level per unit): ~4x headroom over the smoke-test
# worst case. Better-slow-than-killed: a killed unit leaves NO marker, so it
# stays pending and re-dispatching it wastes an entire run.
DEFAULT_CALL_TIMEOUT_S = 7200
# Initial per-unit byte-silence (stall) window, seconds. Calibration: default
# = p99(completed-unit runtime) x 2, rounded down to the minute, never below
# STALL_TIMEOUT_FLOOR_S. Substituting the observed sample (n=84 completed
# units: p50 134s / p95 229s / p99 325s / max 325s) gives 650s -> 600s ->
# floor -> 900s, i.e. this constant is unchanged; the calibration's value is
# the two conclusions it forces: (a) 900s is 2.8x the completed population's
# MAX, so "the default is too tight" is false for healthy units; (b) the
# killed units ran 600s+ and 1600s+, far outside that population's support —
# they are NOT the tail of the same distribution, so no higher constant
# rescues them (measured: raising 600s -> 1600s moved false kills 5 -> 4 while
# doubling each one's cost). The sample is the SURVIVING population only —
# units killed for gateway queueing are absent by construction — so it bounds
# HEALTHY units and MUST NOT be read as "past this it deserves to die".
# Byte silence means "no output right now"; on a rate-limited gateway the
# usual cause is the call waiting in the gateway queue, locally
# indistinguishable from a real hang. Two escape hatches carry what a
# constant cannot: `--stall-timeout-s 0` disables the criterion (convergence
# then bounded by --call-timeout-s alone) and the effective window
# self-widens within a run on false-kill evidence (see
# _widen_stall_window). Re-calibrate from each exit's runtime_* fields.
DEFAULT_STALL_TIMEOUT_S = 900
# Rejection floor for --stall-timeout-s: 1..STALL_TIMEOUT_FLOOR_S-1 exits 2
# (below the floor the false-kill rate dominates). The other legal value is
# 0 = the silence criterion is disabled outright.
STALL_TIMEOUT_FLOOR_S = 60
# Convergence headroom used by BOTH timeout-invariant checks that keep an
# outer level exploitable by the inner one: the soft deadline must fire below
# the host per-call timeout (time-budget-ms x this < host), and the adaptive
# silence window must stay below the absolute per-call kill
# (stall-window <= --call-timeout-s x this). One constant so the two cannot
# drift apart.
CONVERGENCE_HEADROOM = 0.8
# Periodic in-flight heartbeat period, seconds: one stderr line per running
# unit disclosing its seconds-since-last-output so a human watching the host
# TUI distinguishes "slow" from "hung" (the 2026-09-14 incident ran 57 silent
# minutes with no readable signal).
DEFAULT_HB_INTERVAL_S = 60
# Convergence-circuit-breaker window multiplier (--stall-waves N): slot
# backfill has no wave boundary, so the breaker re-anchors on a dispatch
# window — every K = N x --wave newly dispatched units the disk terminal count
# is re-derived once; N consecutive zero-growth re-derivations with units
# still queued = zero-progress loop (deterministic hang kill→re-dispatch→kill,
# or identity/permission drift where every dispatch re-derives the same
# pending set) → stop dispatching, exit 2 + stalled diagnosis. 2 not 1: a
# legal slow window (in-flight units call-timeout with no ack; the next window
# advances) must not trip.
DEFAULT_STALL_WAVES = 2
# Per-stream run.log tail cap (chars): bounded evidence, never unbounded
# capture (stdout of an LLM subagent can be huge; the tail answers "what was
_TAIL_CAP = 8192

# Active per-unit output sinks (uid -> (out_sink, err_sink)): `_dispatch`
# registers the pair BEFORE calling `_run_unit`, which claims (pops) it —
# the reader threads then roll the dispatcher-registered dicts and the
# periodic in-flight heartbeat reads live last-output stamps (design D4:
# idle = seconds since the child's REAL last byte, never since dispatch).
# Module-level because `_run_unit`'s call signature is a frozen 9-arg
# surface (fixed-arity direct callers and test fakes depend on it); the
# register→claim pair is same-thread sequential in the dispatch path (no
# lock needed), uids are unique among in-flight units, and `_dispatch`
# clears any unclaimed entry defensively after the call.
_UNIT_SINKS: dict = {}

# Context-overflow signature match (P2 diagnosis, ADDITIVE ONLY — never
# changes any unit's success/failure outcome): a crashed unit's stderr tail is
# matched case-insensitively against these provider/host wordings for the
# "request exceeds the model context" rejection. A hit marks the run.log unit
# line and the stdout summary with reason:context-overflow + the narrow---
# budget recipe, so the orchestrator/human goes straight to the sharding fix
# instead of treating it as a generic crash. A miss = today's generic crash
# line (never misleading). Append new host wordings here as observed in real
# runs (each host phrases the provider's rejection differently).
CONTEXT_OVERFLOW_SIGS = (
    "context length",
    "prompt is too long",
    "request too large",
    "maximum context",
    "context window",
    "too many tokens",
)
_OVERFLOW_MARK = "reason:context-overflow"
_OVERFLOW_RECIPE = ("context-overflow signature matched — the request exceeded the "
                    "model context; recipe: narrow --budget (--max-aggregate-bytes) "
                    "and re-run")

# Fast-fail storm resilience (design D1/D2/D4: event-driven cooldown = self-heal
# layer; crash-tail rate-limit signatures = fast-stop + disclosure layer; the
# signature layer is NEVER the only defense — signature drift degrades to the
# event path).
# Sliding window (implementation constants, not flags): requeue events
# (crash/timeout/stall/spawn-error units returning to the queue tail) within
# this window arm a cooldown. failed: acks and pre-spawn anchor failures
# terminate WITHOUT requeueing — deliberately never counted (a deterministic
# config error must not fake a provider storm).
REQUEUE_WINDOW_S = 120
REQUEUE_THRESHOLD = 3
DEFAULT_COOLDOWN_S = 300
# Quota admission mode (optional): per-unit call ESTIMATE default. A unit's
# real model-call count burns inside its host-CLI child and is structurally
# invisible to the dispatcher (the gateway is the only true meter), so the
# admission gate runs on this conservative UPPER bound: throttling too hard
# costs wall time, busting the estimate busts the quota (429 storms + wasted
# retries cost whole re-runs). Real-run data flows back via the gateway-side
# counters; calibrate DOWNWARD from 10, never up past the observed worst.
DEFAULT_QUOTA_CALLS_PER_UNIT = 10
# Rate-limit crash-tail signatures (case-insensitive substrings over BOTH
# output tails; crash terminal states only — ok/failed/timeout/stall are never
# classified). A hit marks the crash detail with _RATELIMIT_MARK (same ride-
# along pattern as _OVERFLOW_MARK); append new gateway wordings as real run.log
# evidence surfaces them.
RATE_LIMIT_SIGS = ("429", "too many requests", "rate limit", "quota")
_RATELIMIT_MARK = "reason:rate-limit"
_RATELIMIT_RECIPE = (
    "rate-limit crash storm truncated — every crash tail in the window matched "
    "a quota signature; recipe: wait one full quota window (gateway-configured, "
    "e.g. 10 min) before resuming via --resume; calibrate --wave per "
    "floor(quota-calls-per-minute x 0.8 / per-unit calls-per-minute); a "
    "liveness/stall tree-kill is NOT a crash and never counts here; disable "
    "this truncation with --no-rate-limit-stop")

# Static credential injection + per-unit execution-environment isolation
# (optional; both flags default OFF = byte-identical legacy spawn env). The
# cred schema validator is imported from mgh_credentials (single source).
_CRED_EXPIRED_MARK = "reason:credential-expired"
_CRED_EXPIRED_RECIPE = (
    "credential-expired signature matched — the gateway rejected the static "
    "token; recipe: re-acquire credentials (mgh_credentials.py, or per the "
    "special-auth deployment doc when present), update the cred file, then "
    "re-run with --resume --retry-failed (done units are never re-dispatched)")
SPECIAL_AUTH_DOC = Path(".mgh") / "special-auth.md"


def _special_auth_doc_path(repo) -> Path:
    """Optional PROJECT-owned entry (`<repo>/.mgh/special-auth.md`, placed by the
    deployment): present = the project carries its own authentication
    instructions and the orchestrator/runner points at them; absent = generic
    flows only. The maintainer's install-tree copy is retired (install no longer
    distributes it)."""
    return Path(repo) / SPECIAL_AUTH_DOC


# Per-unit extra spawn env (uid -> dict), the env twin of _UNIT_SINKS:
# module-level because _run_unit's 9-arg signature is frozen (fixed-arity
# direct callers and test fakes depend on it); register→claim is same-thread
# sequential in the dispatch path. Unregistered uid (or an empty registry)
# changes NOTHING — the legacy env construction is byte-identical.
_UNIT_ENV: dict = {}


def _load_cred_file(path_str: str) -> dict | None:
    """Read + validate the cred payload (closed set, validator = the
    producer's). Returns the normalized dict (global_config expanduser'd) or
    None after printing the error + recipe; the caller exits 2 BEFORE any
    spawn or enumerator side effect."""
    p = Path(path_str).expanduser()
    try:
        body = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _eprint(f"error: cred file unreadable: {p} ({e})")
        _eprint("recipe: (re-)acquire via `mgh_credentials.py --source "
                "<run>/cred_source.json --out <run>/cred.json`, or per the "
                "special-auth deployment doc when present")
        return None
    problems = validate_cred_payload(body)
    if problems:
        _eprint(f"error: cred file failed schema validation: {p}")
        for q in problems:
            _eprint(f"  - {q}")
        _eprint("recipe: re-acquire via `mgh_credentials.py --source "
                "<run>/cred_source.json --out <run>/cred.json`, or per the "
                "special-auth deployment doc when present")
        return None
    body["global_config"] = os.path.expanduser(body["global_config"])
    return body


def _cred_expired_tail(cred: dict, out_tail: str, err_tail: str) -> bool:
    """True when either output tail carries a token-expiry signature
    (case-insensitive substring). The signatures come from the cred file
    (`expired_signatures[]`), so gateway-specific rejection wordings are
    deployment data, never code. An empty signature list disables the scan
    (classification behavior identical to running without a cred file)."""
    sigs = cred.get("expired_signatures") or []
    if not sigs:
        return False
    low_o, low_e = (out_tail or "").lower(), (err_tail or "").lower()
    return any(sig.lower() in low_o or sig.lower() in low_e for sig in sigs)


def _materialize_child_config(cred: dict, unit_cfg_dir: Path) -> Path:
    """Write one unit's child config: a copy of the cred-declared global
    host-CLI config with the cred-declared provider overridden to the static
    entry (baseURL + apikey). Everything else (plugins/agents/model/…) is
    preserved verbatim; the provider ID stays IDENTICAL (model ids are
    `<provider>/<model>` — renaming the provider would break the prefix
    coupling). Idempotent: the same inputs produce the same file, so re-
    dispatch/`--resume` re-materialization is safe, and a re-acquired (rotated)
    token flows into the next materialization. The apikey lands ONLY here —
    never stdout/stderr/markers/run.log/telemetry. Raises ValueError/OSError;
    the caller converts a failure into that unit's pre-spawn failure."""
    gp = Path(cred["global_config"])
    try:
        cfg = json.loads(gp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"global config unreadable: {gp} ({e})")
    if not isinstance(cfg, dict):
        raise ValueError(f"global config is not a JSON object: {gp}")
    providers = cfg.get("provider")
    if not isinstance(providers, dict) or cred["provider_id"] not in providers:
        raise ValueError(
            f"provider {cred['provider_id']!r} not found in global config {gp} "
            f"— recipe: align the cred source's provider_id with the config's "
            f"provider entry (see the special-auth deployment doc)")
    if not cred["keep_plugins"]:
        cfg.pop("plugin", None)
    node = providers[cred["provider_id"]]
    if not isinstance(node, dict):
        raise ValueError(f"provider entry is not an object: {cred['provider_id']!r}")
    options = node.setdefault("options", {})
    if not isinstance(options, dict):
        raise ValueError(f"provider options is not an object: "
                         f"{cred['provider_id']!r}")
    options["baseURL"] = cred["baseURL"]
    options["apiKey"] = cred["apikey"]
    target = unit_cfg_dir / "opencode" / "opencode.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return target


def _orphan_advisory(init_dir: Path, tier: str) -> None:
    """Startup advisory (non-blocking, exit-code neutral): a residual liveness
    file for this tier means the previous run was hard-killed (the normal exit
    path deletes it). A live, matching runner = another dispatch may be
    running right now; a dead one = orphan children may exist. Either way the
    recipe is the existing `--kill-stale` machinery — no new cleanup path."""
    pid_file = init_dir / f"fanout_runner.{tier}.pid"
    if not pid_file.is_file():
        return
    ins = _inspect_liveness(pid_file)
    if ins is None:
        return
    if ins.get("runner_alive") and ins.get("runner_matches"):
        _eprint(f"[fanout_runner] note: a runner for tier {tier} appears ALIVE "
                f"(pid {ins['body'].get('pid')}, started "
                f"{ins['body'].get('started_ts')}) — another dispatch may "
                f"still be running; proceed only if intentional "
                f"(`fanout_runner.py --kill-stale --dry-run` lists it)")
    else:
        _eprint(f"[fanout_runner] note: stale liveness file "
                f"({pid_file.name}) — the previous run was hard-killed; "
                f"orphan children may exist. Recipe: "
                f"`fanout_runner.py --kill-stale --dry-run` lists them, "
                f"review then re-run without --dry-run to clear")

# ---------------------------------------------------------------------------
# Tier mapping (single point of tier variation, design D1/D2). The wave loop,
# ack state machine, timeouts, sidecar, and audit copies read from this table;
# no per-tier branches elsewhere.
# ---------------------------------------------------------------------------
# Placeholders are pure str.replace, never format()-derived: what the template
# says is what the subagent gets (D2). Common placeholders every tier fills:
#  <id-field> (unit identity: batch_id/cluster_id/shard_id/category per tier),
#  input_path, done_marker, failed_marker, repo; the init tiers (scout/t1/t2/t3)
#  add mgh_core (absolute mgh-core install root of this script — one derivation
#  covers all three hosts, so templates carry ONE stage-prompt path instead of
#  guessing the .opencode/.claude prefix). scout/t1 add
#  checkpoint_path, slice_dir, chunk_sources_abs, codegraph; t2 adds
#  shard_id, categories (checkpoint_path without slice_dir/chunk_sources —
#  partial-synthesis reads a bounded shard record, writes a summary
#  checkpoint, never slices); t3 adds rule_path, category, format.
_SCOUT_PATH_FIELDS = ("input_path", "checkpoint_path", "done_marker",
                      "failed_marker", "slice_dir")
_T2_PATH_FIELDS = ("input_path", "checkpoint_path", "done_marker",
                   "failed_marker")
_T3_PATH_FIELDS = ("input_path", "rule_path", "done_marker", "failed_marker")

TIERS = {
    "scout": {
        "list_script": "list_scout_batches.py",
        # forwarded flags appended after the tier artifacts (fn(args) -> [str]);
        # --retry-failed implies the enumerator's --include-failed (identity
        # always from the enumerator, never filename-derived).
        "list_args": lambda a: ["--scout-plan", a.scout_plan,
                                "--checkpoints", a.checkpoints,
                                "--materialize", a.inputs_dir]
            + (["--include-failed"] if getattr(a, "retry_failed", False) else []),
        # unit-budget tier: run_config.budgets.max_unit_bytes is forwarded as
        # --max-unit-bytes (see _unit_budget_flag); aggregate tiers (t2 /
        # scout-merge) are a different budget family (--max-aggregate-bytes).
        "unit_budget": True,
        "required_args": ("scout_plan", "checkpoints", "inputs_dir"),
        # artifact whose dir = init-dir (sidecar home + run_config neighbor)
        "plan_arg": "scout_plan",
        "template_rel": Path("prompts") / "fragments" / "fanout" / "scout-task.md",
        "path_fields": _SCOUT_PATH_FIELDS,
        "placeholders": _SCOUT_PATH_FIELDS + ("batch_id", "chunk_sources_abs",
                                              "repo", "codegraph", "mgh_core"),
        "id_field": "batch_id",
        "agent": "init-scout-fanout",
        "agent_desc": "mgh-init S3 scout-reader (fanout dispatch, primary)",
        "agent_tools": "Read Glob Grep Bash Write",
        "uses_codegraph": True,
        "uses_chunk_sources": True,
    },
    "t1": {
        "list_script": "list_clusters.py",
        "list_args": lambda a: ["--clusters", a.clusters,
                                "--candidates", a.candidates,
                                "--checkpoints", a.checkpoints,
                                "--materialize", a.inputs_dir]
            + (["--include-failed"] if getattr(a, "retry_failed", False) else []),
        "unit_budget": True,
        "required_args": ("clusters", "candidates", "checkpoints", "inputs_dir"),
        "plan_arg": "clusters",
        "template_rel": Path("prompts") / "fragments" / "fanout" / "t1-task.md",
        "path_fields": _SCOUT_PATH_FIELDS,
        "placeholders": _SCOUT_PATH_FIELDS + ("cluster_id", "chunk_sources_abs",
                                              "repo", "codegraph", "mgh_core"),
        "id_field": "cluster_id",
        "agent": "init-induct-fanout",
        "agent_desc": "mgh-init T1 per-cluster inductor (fanout dispatch, primary)",
        "agent_tools": "Read Glob Grep Bash Write",
        "uses_codegraph": True,
        "uses_chunk_sources": True,
    },
    # t2 = T2 SYNTHESIS map stage (design D1/D2/D5 + D2a marker-aware
    # enumerator). NOT a full tier in the scout/t1/t3 sense — the map stage is
    # dispatched here, but the ROLLUP is a separate orchestrator step (its
    # terminal marker `synthesis.json.done` != any shard `.done`; single reduce,
    # not a wave). The enumerator is plan_aggregate.py --node t2 (marker-aware
    # pending since D2a); plan_arg = init_dir with a run_config.json special
    # case so the sidecar/liveness home = <init-dir>. The agent
    # init-synthesis-fanout runs a per-shard BOUNDED partial synthesis
    # (stages/init-synthesis-partial.md) — never slices, never cross-shard
    # canonical/competing (uses_codegraph=False, uses_chunk_sources=False).
    "t2": {
        "list_script": "plan_aggregate.py",
        # plan_aggregate --node t2; --budget forwarded only when the caller set
        # it (else plan_aggregate's own DEFAULT_BUDGET applies).
        "list_args": lambda a: ["--node", "t2", "--init-dir", a.init_dir]
            + (["--budget", str(a.budget)] if a.budget is not None else [])
            + ["--materialize", a.inputs_dir]
            + (["--include-failed"] if getattr(a, "retry_failed", False) else []),
        "required_args": ("init_dir", "checkpoints", "inputs_dir"),
        # plan_arg attr whose dir = init-dir; the main() special case below
        # re-anchors plan_path onto <init-dir>/run_config.json (D5) so the
        # sidecar + liveness home (plan_path.parent) = <init-dir>.
        "plan_arg": "init_dir",
        "template_rel": Path("prompts") / "fragments" / "fanout" / "t2-task.md",
        "path_fields": _T2_PATH_FIELDS,
        "placeholders": _T2_PATH_FIELDS + ("shard_id", "categories", "repo",
                                           "mgh_core"),
        "id_field": "shard_id",
        "agent": "init-synthesis-fanout",
        "agent_desc": "mgh-init T2 per-shard partial synthesis (fanout dispatch, primary)",
        "agent_tools": "Read Glob Grep Bash Write",
        "uses_codegraph": False,
        "uses_chunk_sources": False,
    },
    # scout-merge = S4 scout candidate merge MAP stage — same shape as t2
    # (plan_aggregate enumerator, marker-aware pending; the ROLLUP is a
    # separate orchestrator step, its terminal marker `merge.json.done` !=
    # any shard `.done`). Enumerator = plan_aggregate.py --node scout-merge
    # (hard-bounded candidate-granularity shards). The agent
    # init-scout-merge-fanout runs a per-shard BOUNDED partial merge
    # (stages/init-scout-merge-partial.md) — never cross-shard dedup
    # (uses_codegraph=False, uses_chunk_sources=False).
    "scout-merge": {
        "list_script": "plan_aggregate.py",
        # plan_aggregate --node scout-merge; --budget forwarded only when the
        # caller set it (else plan_aggregate's own DEFAULT_BUDGET applies).
        "list_args": lambda a: ["--node", "scout-merge", "--init-dir", a.init_dir]
            + (["--budget", str(a.budget)] if a.budget is not None else [])
            + ["--materialize", a.inputs_dir]
            + (["--include-failed"] if getattr(a, "retry_failed", False) else []),
        "required_args": ("init_dir", "checkpoints", "inputs_dir"),
        "plan_arg": "init_dir",
        "template_rel": Path("prompts") / "fragments" / "fanout" / "scout-merge-task.md",
        "path_fields": _T2_PATH_FIELDS,
        "placeholders": _T2_PATH_FIELDS + ("shard_id", "batches", "repo",
                                           "mgh_core"),
        "id_field": "shard_id",
        "agent": "init-scout-merge-fanout",
        "agent_desc": "mgh-init S4 per-shard partial scout merge (fanout dispatch, primary)",
        "agent_tools": "Read Glob Grep Bash Write",
        "uses_codegraph": False,
        "uses_chunk_sources": False,
    },
    "t3": {
        "list_script": "list_rule_jobs.py",
        "list_args": lambda a: ["--inventory", a.inventory,
                                "--format", a.fmt,
                                "--rules-dir", a.rules_dir,
                                "--target", a.target,
                                "--checkpoints", a.checkpoints,
                                "--materialize", a.inputs_dir]
            + (["--include-failed"] if getattr(a, "retry_failed", False) else []),
        "unit_budget": True,
        "required_args": ("inventory", "fmt", "rules_dir", "target",
                          "checkpoints", "inputs_dir"),
        "plan_arg": "inventory",
        "template_rel": Path("prompts") / "fragments" / "fanout" / "t3-task.md",
        "path_fields": _T3_PATH_FIELDS,
        "placeholders": _T3_PATH_FIELDS + ("category", "format", "repo",
                                           "mgh_core"),
        "id_field": "category",
        "agent": "init-rulewriter-fanout",
        "agent_desc": "mgh-init T3 per-category rule writer (fanout dispatch, primary)",
        # rulewriter edits rule/detail files → needs Edit too
        "agent_tools": "Read Glob Grep Bash Write Edit",
        "uses_codegraph": False,
        "uses_chunk_sources": False,
    },
    "sdr": {
        "list_script": "diff_group.py",
        "list_args": lambda a: ["--repo", a.repo,
                                "--base", a.base,
                                "--branch", a.branch or "",
                                "--checkpoints", a.checkpoints,
                                "--materialize", a.inputs_dir]
            + (["--include-failed"] if getattr(a, "retry_failed", False) else []),
        "required_args": ("repo", "base", "checkpoints", "inputs_dir"),
        "plan_arg": "repo",
        # plan_path = the repo root: `grouping.json` lives at <run-dir>/grouping.json =
        # <checkpoints>/../grouping.json, so the sidecar + liveness home (plan_path.parent)
        # is the run dir — same <init-dir>/ neighbor semantics as the init tiers.
        "template_rel": Path("prompts") / "fragments" / "fanout" / "sdr-task.md",
        "path_fields": ("input_path", "draft_path", "done_marker", "failed_marker"),
        "placeholders": ("input_path", "draft_path", "done_marker", "failed_marker",
                         "unit_id", "kind", "route", "repo", "codegraph",
                         "baseline_path", "external_dir"),
        "id_field": "unit_id",
        "agent": "sdr-review-fanout",
        "agent_desc": "mgh-sdr per-unit design review (fanout dispatch, primary)",
        "agent_tools": "Read Glob Grep Bash Write",
        "uses_codegraph": True,
        "uses_chunk_sources": False,
    },
}


def _eprint(*a):
    print(*a, file=sys.stderr)


def _safe_name(unit_id: str) -> str:
    """Filesystem-safe audit/run-log filename — ALIAS of the enumerator's
    encoding (`init_tier.safe_unit_filename`: `/ \\ :` sanitize + 200-stem cap
    with a discriminant tail). One encoding source shared with the marker
    paths: audit copies and run.logs stay name-identical to what the
    enumerator materializes, and an id of ANY length yields a writable
    filename (the pre-fix private copy had no cap → a >249-char unit id wrote
    a >255-char filename that failed on NTFS with only a warn)."""
    return safe_unit_filename(unit_id)


def _in_tree(path_str: str | None, repo: Path) -> bool:
    """True iff path_str resolves inside the repo anchor tree (or is not a str)."""
    if not isinstance(path_str, str) or not path_str:
        return False
    try:
        resolved = Path(path_str).resolve()
        return resolved == repo or repo in resolved.parents
    except (OSError, ValueError):
        return False


def _load_template(tier: dict, template_arg: str | None) -> str:
    """Read the task-message template (explicit path > sibling install copy)."""
    tp = Path(template_arg) if template_arg \
        else Path(__file__).resolve().parent.parent / tier["template_rel"]
    if not tp.is_file():
        _eprint(f"error: task template not found: {tp}")
        sys.exit(1)
    try:
        return tp.read_text(encoding="utf-8")
    except OSError as e:
        _eprint(f"error: task template unreadable: {e}")
        sys.exit(1)


def _codegraph_signal(plan_path: Path, tier_key: str = "") -> str:
    """Derive `codegraph=on|off` from run_config.json (no_codegraph flag),
    sibling of the tier plan artifact. Missing/unparseable → off (legacy).
    All tiers share this ONE source: the sdr tier binds its plan artifact to
    `<run-dir>/grouping.json`, so `plan_path.parent` IS the sdr run dir — the same
    neighbour semantics as init's `<init-dir>/run_config.json`. `tier_key` is kept
    for signature stability (the call site passes it) and is NOT consulted;
    `run_config.json` is the sole carrier of the signal for every tier, so the
    grouping stage and the task-fill stage read the same fact."""
    rc = plan_path.parent / "run_config.json"
    try:
        cfg = json.loads(rc.read_text(encoding="utf-8"))
        return "off" if cfg.get("no_codegraph") else "on"
    except (OSError, ValueError):
        return "off"


def _chunk_sources_abs() -> str:
    """Absolute chunk_sources.py path = sibling of this script (same install,
    same derivation as list_steps.py stdout script_abs)."""
    return str(Path(__file__).resolve().parent / "chunk_sources.py")


def _mgh_core_root() -> str:
    """Absolute mgh-core install root = parent dir of scripts/ — on all three
    hosts this resolves to the tree the unit reads (`.claude/mgh-core`,
    `.opencode/mgh-core`, or dsh's root-level `mgh-core/`). Single source for
    the `{{mgh_core}}` placeholder, so templates carry ONE stage-prompt path
    and no host-prefix guessing."""
    return str(Path(__file__).resolve().parent.parent)


def _fill_template(tier: dict, template: str, unit: dict, repo_str: str,
                   codegraph: str) -> str:
    """Pure verbatim substitution; asserts no residual `{{` after filling."""
    values = {k: unit.get(k, "") for k in tier["placeholders"]
              if k not in ("repo", "codegraph", "chunk_sources_abs", "format",
                           "mgh_core")}
    if tier["uses_chunk_sources"]:
        values["chunk_sources_abs"] = _chunk_sources_abs()
    values["repo"] = repo_str
    values["codegraph"] = codegraph
    values["mgh_core"] = _mgh_core_root()
    values["format"] = unit.get("format", "")
    msg = template
    for ph in tier["placeholders"]:
        msg = msg.replace("{{" + ph + "}}", str(values.get(ph, "")))
    if "{{" in msg:
        _eprint("error: unfilled {{...}} placeholder remains in task message "
                f"(template/template-set mismatch for unit "
                f"{unit.get(tier['id_field'])!r})")
        sys.exit(1)
    return msg


def _anchor_check(tier: dict, unit: dict, repo: Path) -> str | None:
    """Return a failure reason iff any path field resolves outside the repo
    tree (path-drift interception BEFORE spawn; complements the reader-side
    poisoned-input rejection with a dispatcher-side deterministic guard)."""
    for field in tier["path_fields"]:
        v = unit.get(field)
        if not _in_tree(v, repo):
            return f"path-drift: {field}={v!r} resolves outside repo anchor {repo}"
    return None


def _write_failed_marker(tier: dict, unit: dict, reason: str,
                         repo: Path) -> bool:
    """Write the terminal `.failed` marker (same body shape the orchestrator
    writes on a failed ack: {unit, reason, tier}; `tier` = current --tier
    value). Idempotent. REPO-ANCHORED GUARD: the marker path is checked
    against the repo anchor BEFORE any mkdir/write — an out-of-tree marker
    (poisoned/tampered pending listing) is NEVER materialized: the response to
    a detected poisoned path must not be to execute it. Both entries (the
    path-drift interception and the explicit failed ack) share this one write
    point. Returns True when the marker is in-tree (written or already
    present) — on False the caller MUST NOT count the unit as failed-written
    (the marker is the only truth source; a count without disk evidence is a
    fabrication) and the unit stays disk-pending, bounded by the zero-progress
    breaker."""
    fm = unit.get("failed_marker")
    uid = unit.get(tier["id_field"])
    if not fm:
        _eprint(f"warn: unit {uid}: no failed_marker field — no marker written")
        return False
    if not _in_tree(fm, repo):
        _eprint(f"error: unit {uid}: refused to materialize out-of-tree failed "
                f"marker {fm!r} (outside repo anchor {repo}) — the path-drift "
                f"response never executes the detected poisoned path. Recipe: "
                f"check whether the --checkpoints root was pointed outside the "
                f"anchor tree or the pending listing was tampered with; the "
                f"unit stays disk-pending (no marker) and the zero-progress "
                f"breaker bounds the run")
        return False
    p = Path(fm)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(json.dumps({"unit": uid,
                                 "reason": reason, "tier": tier_name(tier)},
                                ensure_ascii=False), encoding="utf-8")
    return True


def tier_name(tier: dict) -> str:
    """Reverse-lookup the tier key for marker bodies (TIERS values carry no
    back-pointer; identity lookup keeps a single source of truth)."""
    for name, t in TIERS.items():
        if t is tier:
            return name
    return "scout"


def _dsh_tier_mount(tier_id: str) -> Path:
    """dsh tier mount file = install-generated `<mgh-core>/dsh/tiers/<tier>.yml`
    (built by install.sh from releases/dsh/agents/ via gen_dsh_tiers.py; the
    dispatcher NEVER generates it at runtime)."""
    return Path(__file__).resolve().parent.parent / "dsh" / "tiers" / f"{tier_id}.yml"


def _dsh_precheck(tier_id: str) -> str | None:
    """Pre-spawn gate for the dsh host (zero-spawn fail-loud): the tier mount
    file and the `mgh` profile must exist. Returns a failure message with a
    regeneration recipe, or None when the dispatch can proceed. The mount is
    the load-bearing asset (persona + env task channel + tool narrowing all
    ride it); the profile is dsh's run carrier — `--profile mgh` missing would
    make every unit die on a host error without a single useful ack."""
    mount = _dsh_tier_mount(tier_id)
    if not mount.is_file():
        return (f"dsh tier mount file missing: {mount}\n"
                "recipe: rerun `install.sh --dsh <target>` (regenerates "
                "mgh-core/dsh/tiers/ from releases/dsh/agents/); NEVER "
                "hand-write the mount")
    dsh_home = Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh"))
    if not (dsh_home / "profiles" / "mgh").is_dir():
        return (f"dsh profile 'mgh' missing under {dsh_home / 'profiles'}\n"
                "recipe: rerun `install.sh --dsh <target>` (creates/wires the "
                "mgh profile; user-owned profiles are never touched)")
    return None


def _spawn_cmd(tier: dict, host: str) -> list[str]:
    """Host-CLI argv for one unit; the task message travels via STDIN for
    opencode/claude, never argv (npm `.cmd` shims on Windows truncate
    multi-line argv at the first newline — observed as the subagent receiving
    only `<!--`). Both hosts read the piped message when no positional message
    is given (opencode `run` Bun.stdin.text(); claude `-p` stdin mode;
    spike-verified). dsh headless has NO stdin task channel (spike fact): argv
    carries only the inert `-` placeholder + the `--patch` mount path, and the
    task text rides the child env `MGH_TASK_TEXT` (see `_run_unit`)."""
    if host == "opencode":
        return [_host_exe("opencode"), "run", "--agent", tier["agent"]]
    if host == "dsh":
        return [_host_exe("dsh"), "--profile", "mgh", "--patch",
                str(_dsh_tier_mount(tier_name(tier))), "-"]
    # claude: -p + --agents inline JSON (the agent definition; the task
    # message arrives via stdin) + tool whitelist.
    agents_json = json.dumps({tier["agent"]: {
        "description": tier["agent_desc"],
        "prompt": "Your task message arrives on stdin; follow it exactly.",
        "tools": tier["agent_tools"].split(),
    }}, ensure_ascii=False)
    return [_host_exe("claude"), "-p", "--agents", agents_json,
            "--allowedTools", tier["agent_tools"]]


def _parse_ack(stdout_text: str) -> str | None:
    """Parse the LAST non-empty stdout line as `ok|oversize|failed ...`.

    opencode default format prints the final assistant message as the last
    line; claude -p prints the final result text. Both match the bounded-ack
    contract. Unparsable → None → caller trusts disk markers only (D4)."""
    lines = [ln.strip() for ln in (stdout_text or "").splitlines() if ln.strip()]
    if not lines:
        return None
    last = lines[-1]
    if last.startswith(("ok ", "ok")) or last in ("ok",):
        return "ok"
    if last.startswith("oversize"):
        return "oversize"
    if last.startswith("failed"):
        return "failed:" + last[len("failed"):].strip()[:200]
    return None


def _context_overflow(err_tail: str) -> bool:
    """True when the stderr tail carries a context-overflow signature
    (case-insensitive, tier-agnostic — every tier's units die the same way
    when their input busts the model context). Diagnosis only."""
    low = (err_tail or "").lower()
    return any(sig in low for sig in CONTEXT_OVERFLOW_SIGS)


def _rate_limited_tail(out_tail: str, err_tail: str) -> bool:
    """True when either output tail carries a rate-limit signature
    (case-insensitive substring, both streams — the provider's rejection can
    surface on either). Crash-terminal classification only; the caller never
    consults this for ok/failed/timeout/stall outcomes."""
    low_o, low_e = (out_tail or "").lower(), (err_tail or "").lower()
    return any(sig in low_o or sig in low_e for sig in RATE_LIMIT_SIGS)


def _cooldown_cap_s(cooldown_s: float, deadline: float | None, now: float,
                    unit_durations: list[float], inflight_count: int) -> float:
    """Max cooldown seconds the remaining time budget allows (design D3):
    remaining budget minus an in-flight convergence margin (observed avg unit
    duration x in-flight count — the slots should get the chance to converge
    after the wait); <= 0 = no budget for any cooldown (degrade to continuing
    immediately + stderr disclosure). No deadline (out-of-host manual run) =
    uncapped. Pure function; the seam keeps the arithmetic micro-testable."""
    if deadline is None:
        return float(cooldown_s)
    remaining = deadline - now
    margin = ((sum(unit_durations) / len(unit_durations)) * inflight_count
              if unit_durations and inflight_count else 0.0)
    return remaining - margin


def _quota_admission(dispatch_times: list[float], window_s: int, calls: int,
                     per_unit: int, now: float) -> tuple[bool, int, float]:
    """Pure arithmetic behind the quota-mode admission gate (quota mode is an
    ESTIMATE: the dispatcher sees only its own dispatch timestamps, never the
    per-unit call counts that burn inside the host-CLI children).

    Admissible iff `dispatches-in-window x K + K <= N` (the next unit's K
    estimated calls must still fit). When inadmissible, returns the monotonic
    ts at which admission re-opens: enough of the OLDEST timestamps must slide
    out of the window for the in-window count to drop to `calls // per_unit -
    1`; that is the (`in-window - max-in-window`)-th oldest timestamp plus the
    window length. A window that can never admit (K > N even at zero
    dispatches) reports `now` — the caller owns the wait cadence (it must
    never busy-spin on a resume ts that is already in the past).

    Returns `(admissible, used_calls, resume_ts)`; `resume_ts` is 0.0 when
    admissible. No mutation of `dispatch_times` — the caller owns the list.
    Pure; kept module-level so the arithmetic is micro-testable without a
    run."""
    recent = [t for t in dispatch_times if now - t <= window_s]
    used = len(recent) * per_unit
    if used + per_unit <= calls:
        return True, used, 0.0
    max_in_window = max(0, calls // per_unit - 1)
    need_slide = len(recent) - max_in_window
    if need_slide <= 0:
        return False, used, float(now)
    resume = sorted(recent)[need_slide - 1] + window_s
    return False, used, resume


def _widened_stall_window(current: int, call_timeout_s: int) -> int:
    """The effective silence window after ONE false-kill self-evidence event:
    double it, clamped to the `--call-timeout-s` convergence margin (design
    D3 — the absolute per-call kill must stay reachable with >=20% headroom, so
    the silence kill can never be scheduled at or past it). Returning
    `current` unchanged means "already at the ceiling": the caller reads that
    as "no widening left to disclose", which is also what keeps a run from
    announcing the same ceiling repeatedly. Pure; the arithmetic is
    micro-testable without a run."""
    cap = int(call_timeout_s * CONVERGENCE_HEADROOM)
    return min(current * 2, cap)


def _percentile_int(values: list[float], pct: int) -> int:
    """Nearest-rank percentile of `values` in whole seconds.

    Nearest-rank (sorted[ceil(pct/100 x n) - 1]) rather than an interpolating
    variant: the result is always an OBSERVED value, so every figure the
    summary discloses is a real unit's wall time — which is the entire point
    (calibrating the silence window against observed runtimes). Integer
    ceiling arithmetic keeps the script free of a `math` import. Caller
    guarantees `values` is non-empty."""
    s = sorted(values)
    n = len(s)
    rank = (pct * n + 99) // 100        # ceil(pct/100 x n)
    return int(round(s[max(0, min(n - 1, rank - 1))]))


def _elapsed_prefix(t0: float) -> str:
    """`+HH:MM:SS` elapsed since t0 (monotonic), for stderr heartbeat lines."""
    el = max(0, int(time.monotonic() - t0))
    hh, rem = divmod(el, 3600)
    mm, ss = divmod(rem, 60)
    return f"+{hh:02d}:{mm:02d}:{ss:02d}"


def _tail_stream(stream, sink: dict) -> None:
    """Reader-thread body: roll `sink["ts"]` (monotonic ts of the last byte on
    this stream — the stall-detection signal) and `sink["tail"]` (last
    _TAIL_CAP chars — run.log evidence). Exits at EOF or on any stream error
    (a dead child's pipes simply close).

    Reads through the BINARY buffer with `read1()`, which returns as soon as
    ANY byte lands. `TextIOWrapper.read(4096)` blocks until 4096 characters
    accumulate (or EOF), so `ts` would only advance once per 4096-char chunk —
    a low-volume but perfectly healthy unit would then look silent and be
    stall-killed at spawn + threshold. Incremental decoding keeps multi-byte
    UTF-8 sequences split across reads intact."""
    dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
    reader = getattr(stream, "buffer", stream)
    read1 = getattr(reader, "read1", None)
    try:
        while True:
            chunk = read1(4096) if read1 is not None else reader.read(4096)
            if not chunk:
                break
            if isinstance(chunk, bytes):
                chunk = dec.decode(chunk)
            with sink["lock"]:
                sink["ts"] = time.monotonic()
                sink["tail"] = (sink["tail"] + chunk)[-_TAIL_CAP:]
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _write_run_log(path: Path, uid: str, status: str, detail: str,
                   out_tail: str, err_tail: str) -> None:
    """Append one per-attempt evidence block to the unit's run.log
    `<checkpoints>/<tier>/<unit>.run.log` (tails already capped at _TAIL_CAP
    each by the reader threads). APPEND, not overwrite: a stall-killed
    attempt's evidence must survive a later successful re-dispatch. Failure is
    a stderr warning only — evidence I/O must never break the dispatch loop."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"===== attempt {datetime.now().astimezone().isoformat(timespec='seconds')} "
                    f"unit: {uid} status: {status} =====\n")
            if detail:
                f.write(f"detail: {detail}\n")
            f.write(f"----- stdout tail (last {_TAIL_CAP} chars) -----\n{out_tail}\n")
            f.write(f"----- stderr tail (last {_TAIL_CAP} chars) -----\n{err_tail}\n")
    except OSError as e:
        _eprint(f"warn: run.log unwritable for {uid} at {path}: {e}")


def _run_unit(host: str, cmd: list[str], task: str, cwd: Path,
              call_timeout_s: int, stall_timeout_s: int = 0,
              run_log_path: Path | None = None, uid: str = "",
              on_spawn=None) -> tuple[str, str | None, str, int | None, bool]:
    """Spawn one subprocess with the task message piped to stdin; returns
    (status, ack, detail, child_pid, stall_killed, kill_ok).

    status ∈ spawn-ok | spawn-error | timeout | stall | crash — ack is the
    parsed bounded ack (None if unparsable or the child was killed). Two
    reader threads track byte-level last-output time per stream; the monitor
    loop (1s granularity) tree-kills the child on output silence >=
    stall_timeout_s (stall) or total runtime >= call_timeout_s (timeout) —
    both via `_kill_tree` (whole tree: the npm .cmd shim chain's real host-CLI
    process dies too, NEVER an orphan burning tokens). `kill_ok` is that
    kill's reported outcome on the stall/timeout paths (True = tree gone or
    SIGKILL delivered; False = the process survived every attempt — the
    caller must NOT re-dispatch, see TestKillFailureDisposition semantics);
    True whenever no kill was attempted. A killed child gets NO
    ack (trust nothing after a kill); the caller re-derives truth from disk.
    on_spawn(pid) fires immediately after a successful Popen (the caller
    registers the liveness children[] entry at SPAWN time, not terminal).
    run_log_path: when set, one evidence block (stdout/stderr tails) is
    appended at every terminal, ok included. stall_killed=True only for the
    silence-triggered kill (the stdout summary discloses these in
    stall_killed[]). `stall_timeout_s` is the run's EFFECTIVE silence window
    for THIS attempt (the caller snapshots it at dispatch, so a mid-run
    widening applies to units dispatched afterwards) — 0 means the criterion
    is disabled and the silence branch never fires.
    Output sinks: the dispatcher registers the unit's active sinks in
    `_UNIT_SINKS` (uid-keyed) before calling this; the reader threads then
    roll THOSE dicts, so the dispatcher's periodic heartbeat reads live
    last-output stamps (idle = seconds since the child's real last byte,
    not since dispatch — design D4). Unregistered uid (direct / test
    callers) → private sinks, behavior unchanged.

    Task delivery is host-shaped: opencode/claude get the task piped to stdin;
    dsh gets it as child env `MGH_TASK_TEXT` (headless has no stdin task
    channel — the tier mount's `task: !!js process.env.MGH_TASK_TEXT` row
    reads the env; argv carries only the inert `-` placeholder so the task
    text NEVER enters the command line). The child env strips `PWD` for ALL
    host forms: opencode resolves project identity as PWD ?? cwd, so an
    inherited PWD (out-of-host manual launch from another directory's shell —
    Git Bash always exports it) overrode cwd=repo; claude/dsh don't read PWD,
    stripping is side-effect-free for them. Stall detection/kill/cooldown are
    host-agnostic."""
    env = {k: v for k, v in os.environ.items() if k != "PWD"}
    # Per-unit execution-environment injection (the env twin of the sink
    # claim): _dispatch registers `_UNIT_ENV[uid]` (XDG_CONFIG_HOME /
    # XDG_DATA_HOME for the static-credential + data-isolation modes) right
    # before calling this; an unclaimed/unregistered uid changes NOTHING.
    extra_env = _UNIT_ENV.pop(uid, None)
    if extra_env:
        env.update(extra_env)
    stdin_mode = subprocess.PIPE
    if host == "dsh":
        env["MGH_TASK_TEXT"] = task
        stdin_mode = subprocess.DEVNULL
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, stdin=stdin_mode, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=str(cwd), text=True,
            encoding="utf-8", errors="replace", env=env,
            # POSIX: setsid() so the unit leads its OWN session/process group.
            # `_kill_tree`'s killpg then scopes to this unit's tree — without
            # it the child shares the dispatcher's group and the kill would
            # take the dispatcher down with it (the kill happens before the
            # stall evidence is written, so there is not even a trace).
            # POSIX-only parameter; passing False on Windows keeps that
            # branch's behavior byte-identical (it kills via taskkill /T /F).
            start_new_session=(os.name != "nt"))
    except OSError as e:
        return "spawn-error", None, f"spawn failed: {e}", None, False, True
    if on_spawn is not None:
        try:
            on_spawn(proc.pid)
        except Exception:
            pass
    t_start = time.monotonic()
    pair = _UNIT_SINKS.pop(uid, None)
    if pair is not None:
        out_sink, err_sink = pair          # dispatcher-registered active sinks
    else:
        lock = threading.Lock()
        out_sink = {"ts": t_start, "tail": "", "lock": lock}
        err_sink = {"ts": t_start, "tail": "", "lock": lock}
    lock = out_sink["lock"]
    readers = [
        threading.Thread(target=_tail_stream, args=(proc.stdout, out_sink),
                         daemon=True),
        threading.Thread(target=_tail_stream, args=(proc.stderr, err_sink),
                         daemon=True),
    ]
    for th in readers:
        th.start()
    if proc.stdin is not None:  # dsh: DEVNULL, task already in env
        try:
            proc.stdin.write(task)
            proc.stdin.flush()
        except OSError:
            pass  # child died before consuming stdin — monitor/reap below handles it
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass
    status: str | None = None
    detail = ""
    was_stalled = False
    kill_ok = True          # only a kill that FAILED flips this to False
    call_deadline = t_start + call_timeout_s
    while True:
        try:
            proc.wait(timeout=1)
            break  # exited on its own
        except subprocess.TimeoutExpired:
            pass
        now = time.monotonic()
        with lock:
            # max = the NEWER of the two last-output stamps = "both streams
            # emitted no bytes for this long". An idle stream MUST NOT make a
            # healthy unit look stalled: both sinks start at t_start and only
            # advance on real bytes, so `min` would read "one stream silent"
            # as "the unit is silent" and kill it at spawn + stall-timeout.
            last_out = max(out_sink["ts"], err_sink["ts"])
        if stall_timeout_s and now - last_out >= stall_timeout_s:
            kill_ok = _kill_tree(proc.pid)
            status, was_stalled = "stall", True
            detail = (f"output silent >= {stall_timeout_s}s (stall-timeout; "
                      "tree-killed; no ack)")
            break
        if now >= call_deadline:
            kill_ok = _kill_tree(proc.pid)
            status = "timeout"
            detail = (f"per-call timeout exceeded ({call_timeout_s}s; "
                      "tree-killed; no ack)")
            break
    # Reap + drain: give the killed/exited child and its reader threads a
    # bounded window to flush the pipes into the sinks (evidence for run.log).
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass
    for th in readers:
        th.join(timeout=30)
    out_tail, err_tail = out_sink["tail"], err_sink["tail"]
    if status is None:
        # natural exit: settle the terminal status BEFORE the evidence write
        # (a crash must be recorded as "crash" in run.log, never the
        # placeholder "spawn-ok")
        ack = _parse_ack(out_tail)
        if proc.returncode != 0 and ack is None:
            status = "crash"
            detail = f"exit={proc.returncode}; stderr tail: {err_tail[-300:]}"
            if _context_overflow(err_tail):
                # P2 diagnosis only (design D6): the mark rides FIRST in the
                # detail so the bounded stderr line, the run.log detail line,
                # and the stdout summary classification all carry it. Never
                # changes the outcome — the unit still stays pending.
                detail = f"{_OVERFLOW_MARK} ({_OVERFLOW_RECIPE}); {detail}"
            elif _rate_limited_tail(out_tail, err_tail):
                # rate-limit classification rides the detail the same way; the
                # dispatcher's storm window consumes it. Disjoint from overflow
                # (elif): an overflow crash is never also a rate-limit crash.
                detail = f"{_RATELIMIT_MARK}; {detail}"
        else:
            status = "spawn-ok"
            detail = out_tail.strip().splitlines()[-1] if out_tail.strip() else ""
    if run_log_path is not None:
        _write_run_log(run_log_path, uid, status, detail, out_tail, err_tail)
    if status == "stall":
        return ("stall", None, detail, proc.pid, True, kill_ok)
    if status == "timeout":
        return ("timeout", None, detail, proc.pid, False, kill_ok)
    if status == "crash":
        return ("crash", None, detail, proc.pid, False, True)
    return ("spawn-ok", ack, detail, proc.pid, False, True)


def _unit_budget_flag(tier: dict, args) -> list:
    """`["--max-unit-bytes", <v>]` built from the run's OWN record, for unit-budget
    tiers (scout/t1/t3, marked `unit_budget` in TIERS). Source = `<init-dir>/
    run_config.json::budgets.max_unit_bytes` — the value step 0 recorded, which
    the enumerators previously never saw (the budget was recorded and silently
    ignored; sharding stayed on the 192KB default). The resume-side t1
    recomputation reads the SAME file (COUPLING LOCKSTEP — both sides switched
    in the same change, never a second CLI flag, or the two budget sources can
    diverge and re-deadlock custom-budget sharded runs). Missing run_config
    (manual direct run outside a host session — legitimate), missing field, or
    a non-positive/non-integer value → no flag: the enumerator default applies,
    byte-identical to legacy runs. A present-but-unreadable run_config gets a
    one-line stderr note instead of an exit (too harsh = the rejected design)."""
    if not tier.get("unit_budget"):
        return []
    plan_attr = tier.get("plan_arg")
    raw = getattr(args, plan_attr, None) if plan_attr else None
    if not raw:
        return []
    plan_path = Path(raw)
    init_dir = plan_path if plan_attr == "init_dir" else plan_path.parent
    rc_path = init_dir / "run_config.json"
    if not rc_path.is_file():
        _eprint(f"note: {rc_path} absent — enumerator default unit budget applies "
                f"(manual direct run outside a host session)")
        return []
    try:
        cfg = json.loads(rc_path.read_text(encoding="utf-8"))
        v = (cfg.get("budgets") or {}).get("max_unit_bytes")
    except (OSError, ValueError, AttributeError):
        _eprint(f"note: {rc_path} unreadable — enumerator default unit budget applies")
        return []
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        return []
    return ["--max-unit-bytes", str(v)]


def _list_pending(tier: dict, args) -> dict:
    """Invoke the tier's sibling enumeration script in --materialize mode and
    return its stdout JSON (the single pending source; NEVER re-dig tier
    aggregates).

    Exit-code semantics (design D4): the enumerator's exit 2 (tier gate
    refusal, e.g. t1 scout-incomplete-gate, or CLI misuse) is PASSED THROUGH
    as exit 2 with its stderr recipe verbatim — a gate refusal is "do not
    enter this tier", never a unit crash, and MUST NOT degenerate into a
    crash/re-dispatch loop. Exit 1 (bad inputs) stays exit 1."""
    cmd = [sys.executable,
           str(Path(__file__).resolve().parent / tier["list_script"])] \
        + tier["list_args"](args) \
        + _unit_budget_flag(tier, args)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode == 2:
        _eprint(f"error: {tier['list_script']} exited 2 (gate/CLI refusal); "
                f"stderr recipe forwarded verbatim:\n{(r.stderr or '')[-800:]}")
        sys.exit(2)
    if r.returncode != 0:
        _eprint(f"error: {tier['list_script']} exited {r.returncode}: "
                f"{(r.stderr or '')[-400:]}")
        sys.exit(1)
    try:
        return json.loads(r.stdout)
    except ValueError as e:
        _eprint(f"error: unparsable {tier['list_script']} stdout: {e}")
        sys.exit(1)


def _host_exe(host: str) -> str:
    """Resolve the host CLI to an executable path Windows can spawn.

    npm-installed CLIs are `.cmd` shims on Windows (`%APPDATA%/npm/opencode.cmd`);
    `subprocess.run(["opencode", ...])` without shell=True fails with WinError 2
    on the bare name. `shutil.which` resolves PATHEXT properly, so spawn the
    resolved absolute path. Falls back to the bare name (POSIX) when which
    finds nothing.
    """
    resolved = shutil.which(host)
    return resolved if resolved else host


def _detect_host(explicit: str | None, tier: dict) -> str:
    """--host explicit > opencode in PATH > claude in PATH > dsh in PATH
    (dsh appended at the chain end: dual-host machines keep their existing
    probe behavior unchanged); else exit 2 + recipe."""
    if explicit:
        if explicit not in ("claude", "opencode", "dsh"):
            _eprint(f"error: --host must be claude|opencode|dsh (got {explicit!r})")
            sys.exit(2)
        if shutil.which(explicit) is None:
            _eprint(f"error: --host {explicit} not found in PATH")
            sys.exit(2)
        return explicit
    if shutil.which("opencode"):
        return "opencode"
    if shutil.which("claude"):
        return "claude"
    if shutil.which("dsh"):
        return "dsh"
    _eprint("error: no host CLI found (none of `opencode`/`claude`/`dsh` in PATH).\n"
            f"fallback recipe: dispatch {tier_name(tier)} waves manually per the "
            f"tier's stage fragment (list_* paging + per-unit subagent spawn); "
            "behavior is unchanged.")
    sys.exit(2)


def _write_sidecar(init_dir: Path, tier: str, payload: dict) -> None:
    """Atomically write the human-facing progress sidecar
    `<init-dir>/fanout_progress.<tier>.json`.

    Run-state disclosure for HUMANS (second-terminal `Get-Content -Wait`);
    never read by the orchestrator or any agent, never consulted by
    resume/init_manifest. Failure to write is a stderr warning only — it must
    never break the dispatch loop. Atomic: tempfile in the same dir +
    os.replace (no half-written file on crash). Per-tier filename: t1/t3 and
    scout may interleave on long runs (resume), and a single shared file
    would overwrite with fake backwards progress."""
    target = init_dir / f"fanout_progress.{tier}.json"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(target.parent),
                                        prefix=".fanout_progress.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
                f.write("\n")
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except OSError as e:
        _eprint(f"warn: fanout_progress.{tier}.json write failed (non-fatal): {e}")


def _liveness_body(tier: str, host: str) -> dict:
    """The liveness body dict, single source: the initial write AND the
    read-back rebuild in main() must stay shape-identical (the dispatcher
    reuses this dict across children[] refreshes, so started_ts/cmdline
    stability rides it, not the file)."""
    return {
        "pid": os.getpid(),
        "started_ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tier": tier,
        "host": host,
        "cmdline": list(sys.argv),
        "children": [],
    }


def _write_liveness(init_dir: Path, tier: str, host: str) -> Path:
    """Atomically write the liveness file `<init-dir>/fanout_runner.<tier>.pid`
    (orphan signal, NOT a lock — a same-run-dir second runner is a user's
    explicit action). Body {pid, started_ts, tier, host, cmdline, children[]};
    children[] starts empty and is refreshed per wave by
    `_update_liveness_children`. Atomic: tempfile in the same dir + os.replace
    (same shape as _write_sidecar). Write failure is a stderr warning only —
    it must never break the dispatch loop."""
    target = init_dir / f"fanout_runner.{tier}.pid"
    _atomic_write_json(target, _liveness_body(tier, host))
    return target


def _atomic_write_json(target: Path, body: dict) -> None:
    """tempfile + os.replace atomic JSON write (mirror of _write_sidecar's
    atomicity core, reused by the liveness file). Failure = stderr warning,
    never fatal (the dispatch loop must not break on signal-file I/O)."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(target.parent),
                                        prefix=".fanout_runner.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False, indent=1)
                f.write("\n")
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except OSError as e:
        _eprint(f"warn: {target.name} write failed (non-fatal): {e}")


def _update_liveness_children(liveness_path: Path, body: dict,
                              children: list) -> None:
    """Atomically refresh `children[]` in the liveness file (each entry
    {pid, unit, tier}): a child is registered AT SPAWN (on_spawn fires with
    the Popen pid) and removed AT that unit's terminal event, so the registry
    reflects the true in-flight set at any instant — a runner hard-killed
    mid-run leaves behind exactly its still-running children. Failure is a
    stderr warning only (non-fatal by the same contract as the initial
    write)."""
    body["children"] = children
    _atomic_write_json(liveness_path, body)


def _hb(t0: float, tier: str, seq: int, uid: str, event: str,
        done: int, total: int) -> None:
    """One stderr heartbeat line at a dispatch-loop key node (unit spawn /
    unit terminal status: ok|failed|timeout|crash|stall). `seq` = the unit's
    dispatch ordinal this run (heartbeat field `wave=`, name kept). opencode's
    Bash tool renders the merged stdout+stderr sliding tail while running ->
    these lines are the live TUI progress; stdout's single-JSON-line contract
    is untouched."""
    _eprint(f"[fanout_runner {tier}] {_elapsed_prefix(t0)} "
            f"wave={seq} unit={uid} {event} done={done}/{total}")


def _hb_inflight(t0: float, tier: str, k: int, uid: str, idle_s: int,
                 done: int, total: int, stall_window_s: int) -> None:
    """One periodic stderr in-flight disclosure line (--hb-interval-s): unit
    id + seconds since its child's last output — a human watching the host TUI
    distinguishes "slow" from "hung" live (the 2026-09-14 incident ran 57
    silent minutes unreadable). stdout's single-JSON-line contract untouched.

    `stall_window_s` = the silence window THIS unit is being judged against
    (its dispatch-time snapshot of the run's effective window; 0 = criterion
    disabled this run, disclosed as `off`). Without it an adaptive window
    makes `idle` unreadable: the same `idle=1000s` means "kill is imminent"
    under W=900 and "nothing to see" under W=1800."""
    win = f"{stall_window_s}s" if stall_window_s else "off"
    _eprint(f"[fanout_runner {tier}] {_elapsed_prefix(t0)} "
            f"inflight={k} unit={uid} idle={idle_s}s stall_window={win} "
            f"done={done}/{total}")


# Host-CLI cmdline markers for the PID-reuse guard: a child PID is only killed
# when its cmdline actually is the host CLI (opencode/claude/dsh); a runner PID
# only when it still names fanout_runner.py.
_RUNNER_MARK = "fanout_runner"
_HOST_CLIS = ("opencode", "claude", "dsh")


def _pid_alive(pid: int) -> bool:
    """OS process-table liveness probe. Windows: `tasklist /fi "PID eq <pid>"`
    (a dead PID prints an info line with no csv row); POSIX: `/proc/<pid>`."""
    if pid is None or pid <= 0:
        return False
    if os.name == "nt":
        try:
            r = subprocess.run(
                ["tasklist", "/fi", f"PID eq {pid}", "/fo", "csv", "/nh"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False
        for ln in (r.stdout or "").splitlines():
            ln = ln.strip()
            if ln.startswith('"') and f'","{pid}",' in ln:
                return True
        return False
    return Path(f"/proc/{pid}").exists()


def _pid_cmdline_cim(pid: int) -> str | None:
    """PowerShell CIM cmdline probe — the fallback for machines where the
    classic `wmic` tool no longer exists (removed on Windows 11 24H2+; the
    wmic-only probe silently disabled the whole kill-stale path there while
    orphans kept burning tokens). PowerShell is a Windows core component:
    zero added dependency. Returns the command line ("" = probed fine, none
    reported) or None when the PROBE ITSELF is unusable (powershell missing,
    the CIM query failed, or it timed out — the caller fail-louds on None)."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}')"
             f".CommandLine"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return (r.stdout or "").strip()


def _pid_cmdline(pid: int) -> str | None:
    """Full cmdline of a PID. None = the probe is UNAVAILABLE on this machine
    (every probe path failed — the caller must fail loud instead of guessing
    orphan ownership); "" = probed fine but no cmdline retrievable (the
    process died between the liveness and cmdline probes). Windows: classic
    `wmic` first, the PowerShell CIM probe on probe-tool failure (wmic removed
    on Win11 24H2+); POSIX: /proc/<pid>/cmdline (NUL-separated), best-effort
    "" on failure (H5 is a Windows-shaped defect)."""
    if os.name == "nt":
        try:
            r = subprocess.run(
                ["wmic", "process", "where", f"processid={pid}", "get",
                 "commandline", "/value"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return _pid_cmdline_cim(pid)
        for ln in (r.stdout or "").splitlines():
            ln = ln.strip()
            if ln.lower().startswith("commandline="):
                return ln.split("=", 1)[1].strip()
        return ""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


# POSIX kill-escalation ladder constants (signal ids ride getattr fallbacks so
# the ladder is importable/patchable on Windows too), plus the grace window
# SIGTERM gets before escalating and the poll slice inside it.
_SIGTERM = getattr(signal, "SIGTERM", 15)
_SIGKILL = getattr(signal, "SIGKILL", 9)
_KILL_TREE_GRACE_S = 1.5
_KILL_TREE_POLL_S = 0.05


def _kill_tree(pid: int) -> bool:
    """Kill a whole process tree. Returns True = the tree is confirmed gone
    (or the SIGKILL escalation was delivered); False = it survived every
    attempt — callers treat that as KILL-FAILED (the survivor owns the unit:
    no re-dispatch, pid kept in liveness, stderr fail-loud + stdout
    kill_failed[]).

    Windows: `taskkill /pid <pid> /T /F` (/T is the only reliable whole-tree
    kill — the host CLIs are npm `.cmd` shim chains), retried ONCE on a
    nonzero exit (a freshly spawned shim chain can outrun the first pass).
    POSIX: SIGTERM to the unit's own process group (spawns run with
    `start_new_session`, so killpg scopes to that unit's tree, NEVER the
    caller's), then a short grace window re-checks group liveness (signal-0
    killpg poll) and ESCALATES to SIGKILL while the group still survives —
    SIGTERM alone is advisory to wedge-shaped descendants, and a kill that
    silently failed used to re-queue the unit for a concurrent double-run.
    Callers (the stall/timeout path and the exit-path cleanup) survive the
    kill they issue."""
    if os.name == "nt":
        for _ in range(2):
            try:
                r = subprocess.run(["taskkill", "/pid", str(pid), "/T", "/F"],
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=60)
                if r.returncode == 0:
                    return True
            except (OSError, subprocess.TimeoutExpired):
                pass
        return False
    try:
        pgid = os.getpgid(pid)
    except OSError:
        pgid = None
    if pgid is None:
        # A unit is a session leader (start_new_session) so getpgid normally
        # cannot fail, but a PID that is already reaped or never became a
        # group leader still deserves the direct-child attempt rather than a
        # silent no-op.
        try:
            os.kill(pid, _SIGTERM)
            return True
        except OSError:
            return False
    try:
        os.killpg(pgid, _SIGTERM)
    except (OSError, ProcessLookupError):
        pass  # group already gone
    deadline = time.monotonic() + _KILL_TREE_GRACE_S
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True              # group confirmed gone inside the grace
        except OSError:
            break                    # undecidable (e.g. permission) → escalate
        time.sleep(_KILL_TREE_POLL_S)
    delivered = False
    try:
        os.killpg(pgid, _SIGKILL)
        delivered = True
    except (OSError, ProcessLookupError):
        pass
    try:
        os.kill(pid, _SIGKILL)       # direct-child fallback for non-leaders
        delivered = True
    except (OSError, ProcessLookupError):
        pass
    return delivered


def _stale_liveness_files(init_dirs) -> list:
    """Residual liveness files `fanout_runner.*.pid` under any of init_dirs
    (a single dir or a list; deduped by resolved path, sorted)."""
    if not isinstance(init_dirs, (list, tuple)):
        init_dirs = [init_dirs]
    seen = {}
    for d in init_dirs:
        if not d.is_dir():
            continue
        for pf in d.glob("fanout_runner.*.pid"):
            seen[pf.resolve()] = pf
    return [seen[k] for k in sorted(seen)]


def _inspect_liveness(pid_file: Path) -> dict | None:
    """Parse a liveness file -> {body, runner_alive, runner_matches,
    live_children:[{pid,unit,tier}], probe_unavailable}. Unparsable/missing ->
    None (the caller then only removes the residual file, never kills).
    probe_unavailable=True: a live PID's cmdline could not be probed by ANY
    available probe — orphan ownership is UNDECIDABLE; the caller fail-louds
    and preserves the evidence instead of guessing (never the silent
    "zero kills + destroy evidence + fake success" path)."""
    try:
        body = json.loads(pid_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    pid = body.get("pid")
    runner_alive = isinstance(pid, int) and _pid_alive(pid)
    runner_matches = False
    probe_unavailable = False
    if runner_alive:
        cl = _pid_cmdline(pid)
        if cl is None:
            probe_unavailable = True
        else:
            runner_matches = _RUNNER_MARK in cl
    live_children = []
    for ch in body.get("children") or []:
        if not isinstance(ch, dict):
            continue
        cpid = ch.get("pid")
        if isinstance(cpid, int) and _pid_alive(cpid):
            ccl = _pid_cmdline(cpid)
            if ccl is None:
                probe_unavailable = True
                continue
            live_children.append({"pid": cpid, "unit": ch.get("unit"),
                                  "tier": ch.get("tier"), "cl": ccl})
    return {"body": body, "runner_alive": runner_alive,
            "runner_matches": runner_matches, "live_children": live_children,
            "probe_unavailable": probe_unavailable}


def _cmdline_exe_token(cl: str) -> str:
    """Executable token of a raw cmdline string: a leading quoted span (Windows
    quotes executable paths containing spaces) else the first whitespace-
    separated token → unified separators → basename → lowercased →
    .exe/.cmd/.bat stripped. The host-CLI identity match anchors HERE: a host
    name anywhere else in the command line (an editor holding
    `claude-meeting.txt`, a script path containing `dsh`) is never an identity
    match — the old whole-cmdline substring disjunct tree-killed unrelated
    processes."""
    cl = (cl or "").strip()
    if not cl:
        return ""
    if cl[0] in "\"'":
        end = cl.find(cl[0], 1)
        tok = cl[1:end] if end != -1 else cl[1:]
    else:
        tok = cl.split(None, 1)[0]
    base = tok.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for ext in (".exe", ".cmd", ".bat"):
        if base.endswith(ext):
            return base[:-len(ext)]
    return base


def _classify_targets(inspected: list) -> list:
    """PID-reuse double guard: return only {pid, tier, kind} entries that may
    be killed — kind=runner iff the runner PID is alive AND its cmdline names
    fanout_runner.py; kind=child iff the runner is dead/mismatched AND the
    child PID is alive AND its cmdline's EXECUTABLE TOKEN is the host CLI
    (never a substring match over the whole command line). Everything else =
    a stale record: the liveness file is removed, nothing is killed."""
    targets = []
    for ins in inspected:
        tier = ins["body"].get("tier") or "unknown"
        if ins["runner_alive"] and ins["runner_matches"]:
            targets.append({"pid": ins["body"]["pid"], "tier": tier,
                            "kind": "runner"})
            continue
        if ins["runner_alive"] and not ins["runner_matches"]:
            continue  # PID reused by an unrelated process — never kill
        for ch in ins["live_children"]:
            if _cmdline_exe_token(ch.get("cl") or "") in _HOST_CLIS:
                targets.append({"pid": ch["pid"], "tier": ch["tier"] or tier,
                                "kind": "child"})
    return targets


_REVIEW_MARKER = "fanout_runner.kill-stale.reviewed"


def _kill_stale(init_dir: Path, dry_run: bool) -> tuple:
    """--kill-stale core. Returns (result_dict, exit_code).

    Destructive-op guard (stateful two-step, --purge-audit shape adapted):
    the script is stateless, so a real kill REQUIRES a prior `--dry-run`
    review — --dry-run with detected targets writes the review marker
    `<init-dir>/<_REVIEW_MARKER>`; a real kill with detected targets and no
    marker exits 2 + recipe (review first). The marker is consumed by the
    real kill. No targets -> exit 0 `killed:[]` in both forms (idempotent;
    residual files still removed on the real pass — stale-record cleanup is
    not destructive).

    Form (1) runner alive+cmdline-matches -> kill tree (kind=runner); form
    (2) runner dead/mismatched but recorded host-CLI children alive -> kill
    each tree (kind=child). Every killed entry is reported with its kind.
    init_dir may be a single dir or several candidate run dirs (checkpoints
    parent + inputs-dir parent in the standard <init-dir>/ tier-subdir layout
    they coincide; a flat caller-provided layout is covered by scanning both)."""
    init_dirs = init_dir if isinstance(init_dir, (list, tuple)) else [init_dir]
    if not init_dirs:
        # No scan root derivable (kill-stale with zero artifact flags): an
        # honest empty result — there is nothing recorded anywhere to scan.
        return {"kill_stale": {"killed": [], "removed": [], "none": True}}, 0
    pid_files = _stale_liveness_files(init_dirs)
    inspected = [i for i in (_inspect_liveness(p) for p in pid_files)
                 if i is not None]
    if any(i.get("probe_unavailable") for i in inspected):
        # Undecidable orphan ownership: keep EVERY piece of evidence, kill
        # nothing, and fail loud — the silent "zero kills + delete the
        # liveness files + exit 0" path is exactly the failure shape this
        # guard exists to close (wmic-less machines used to hit it every
        # time; the CIM fallback covers them, and THIS covers the rest).
        _eprint("error: kill-stale cannot decide orphan ownership — a live "
                "PID's command line is unprovable on this machine (the "
                "classic wmic probe is unavailable AND the PowerShell CIM "
                "probe failed). NOTHING was killed and NO liveness file was "
                "removed: the evidence stays on disk. Recipe: probe the PIDs "
                "by hand (`powershell -NoProfile -Command \"Get-CimInstance "
                "Win32_Process -Filter 'ProcessId=<pid>' | "
                "Select-Object ProcessId,CommandLine\"`), kill confirmed "
                "orphans with the host shell, and only then delete the "
                "`fanout_runner.<tier>.pid` files.")
        return {"kill_stale": {"killed": [], "removed": [],
                               "none": False}}, 2
    targets = _classify_targets(inspected)
    marker_dir = init_dirs[0]
    marker = marker_dir / _REVIEW_MARKER
    if not pid_files:
        return {"kill_stale": {"killed": [], "removed": [], "none": True}}, 0
    if dry_run:
        _eprint(f"kill-stale (dry-run): {len(targets)} target(s) would be "
                f"killed: {targets}")
        if targets:
            _atomic_write_json(marker, {
                "reviewed_ts": datetime.now().astimezone().isoformat(
                    timespec="seconds"),
                "targets": targets})
        return {"kill_stale": {"killed": targets, "removed": [],
                               "none": not targets}}, 0
    if targets and not marker.is_file():
        _eprint("error: --kill-stale targets detected but no prior --dry-run "
                "review (destructive op guard, R5.3b). Recipe: run "
                "`fanout_runner.py --kill-stale --dry-run --checkpoints <dir>` "
                "first, review the listed PIDs, then re-run without --dry-run.")
        return {"kill_stale": {"killed": [], "removed": [],
                               "none": False}}, 2
    killed = []
    for t in targets:
        ok = _kill_tree(t["pid"])
        killed.append({"pid": t["pid"], "tier": t["tier"], "kind": t["kind"]})
        if not ok:
            _eprint(f"warn: kill of pid {t['pid']} ({t['kind']}) failed — "
                    f"process may have exited concurrently")
    removed = []
    for p in pid_files:
        try:
            p.unlink()
            removed.append(str(p))
        except OSError as e:
            _eprint(f"warn: cannot remove {p}: {e}")
    try:
        marker.unlink(missing_ok=True)  # consume the review credential
    except OSError as e:
        _eprint(f"warn: cannot remove {marker}: {e}")
    none = not (killed or removed)
    return {"kill_stale": {"killed": killed, "removed": removed,
                           "none": none}}, 0


def _purge_audit(inputs_dir: Path, dry_run: bool) -> list[str]:
    """List `<inputs-dir>/*.task.md` audit copies (dry-run listing only; the
    CLI surface is list-only — actual deletion happens via the host shell
    after the operator reviews the listing; destructive-op guard, R5.3b)."""
    purged = []
    if not inputs_dir.is_dir():
        return purged
    for f in sorted(inputs_dir.glob("*.task.md")):
        purged.append(f.name)
    return purged


def main() -> int:
    ap = argparse.ArgumentParser(
        description="deterministic tier-aware slot-backfill dispatcher for /mgh-init "
                    "+ /mgh-sdr fan-out (tiers: scout/scout-merge/t1/t2/t3/sdr; zero LLM turns; "
                    "fixed template + verbatim fields; in-flight-capped host-CLI "
                    "spawn; per-unit stall kill)")
    ap.add_argument("--tier", choices=["scout", "scout-merge", "t1", "t2", "t3", "sdr"],
                    default="scout",
                    help="fan-out tier (default scout). Selects the enumeration "
                         "script, task template, placeholder set, and fanout agent; "
                         "scout call shape (--scout-plan etc.) is unchanged. t2 tier "
                         "(map stage only): plan_aggregate.py --node t2 "
                         "--init-dir/[--budget]/--materialize. scout-merge tier "
                         "(map stage only; identical call shape): plan_aggregate.py "
                         "--node scout-merge --init-dir/[--budget]/--materialize. "
                         "sdr tier: diff_group.py "
                         "--repo/--base/--branch/--checkpoints/--materialize")
    # scout artifacts (scout tier)
    ap.add_argument("--scout-plan",
                    help="path to scout_plan.json (scout tier; forwarded to "
                         "list_scout_batches)")
    # t1 artifacts (t1 tier)
    ap.add_argument("--clusters",
                    help="path to clusters.json (t1 tier; forwarded to "
                         "list_clusters)")
    ap.add_argument("--candidates",
                    help="path to controls_candidates.json (t1 tier; hit lookup "
                         "for --materialize)")
    # t2 artifacts (t2 tier; forwarded to plan_aggregate --node t2)
    ap.add_argument("--init-dir",
                    help="path to .mgh-init dir (t2 tier; forwarded to "
                         "plan_aggregate --init-dir; run_config.json under it "
                         "anchors the sidecar/liveness home)")
    ap.add_argument("--budget", type=int, default=None,
                    help="per-request aggregate byte cap (t2 tier; forwarded to "
                         "plan_aggregate --budget; default None -> plan_aggregate "
                         "DEFAULT_BUDGET)")
    # t3 artifacts (t3 tier)
    ap.add_argument("--inventory",
                    help="path to controls_inventory.json (t3 tier; forwarded to "
                         "list_rule_jobs)")
    ap.add_argument("--format", dest="fmt", choices=["opencode", "claude"],
                    help="rule format (t3 tier; determines rule_path)")
    ap.add_argument("--rules-dir",
                    help="opencode rules detail dir (t3 tier; rule_path base)")
    ap.add_argument("--target", default=".",
                    help="target project root (t3 tier; rule_path base, default .)")
    # sdr tier artifacts (forwarded to diff_group.py)
    ap.add_argument("--repo",
                    help="absolute target git repo root (sdr tier; forwarded to "
                         "diff_group + the tree anchor)")
    ap.add_argument("--base", default="master",
                    help="base ref (sdr tier; default master; forwarded to diff_group)")
    ap.add_argument("--branch", default="",
                    help="branch ref (sdr tier; default: current branch, resolved by "
                         "diff_group; forwarded verbatim)")
    # shared
    ap.add_argument("--checkpoints", default=None,
                    help="tier checkpoint dir (markers; forwarded to the tier's "
                         "list script). REQUIRED for dispatch; OPTIONAL for "
                         "--kill-stale recovery (scan hint only — the run dir is "
                         "then anchored by the tier's plan artifact, e.g. "
                         "--scout-plan/--init-dir/--repo)")
    ap.add_argument("--inputs-dir", default=None,
                    help="per-unit input dir (forwarded as --materialize; audit "
                         "<unit>.task.md copies land here). REQUIRED for dispatch; "
                         "OPTIONAL for --kill-stale recovery (scan hint only)")
    ap.add_argument("--host", choices=["claude", "opencode", "dsh"],
                    help="explicit host CLI; default: opencode in PATH, else claude, "
                         "else dsh, else exit 2 + manual-dispatch fallback recipe")
    ap.add_argument("--wave", type=int, default=DEFAULT_WAVE,
                    help=f"in-flight subprocess cap (default {DEFAULT_WAVE}) - a "
                         f"slot-backfill concurrency limit, not a batch size: any "
                         f"unit reaching a terminal state frees its slot and the "
                         f"next queued unit is dispatched immediately")
    ap.add_argument("--time-budget-ms", type=int, default=None,
                    help="soft deadline in ms: stop dispatching new units, drain "
                         "in-flight, exit 0 with partial:true (re-dispatch the same "
                         "command). RECOMMENDED = host per-call timeout x 0.8 (host "
                         "900000ms -> 720000; claude Bash cap 600000ms -> 480000); "
                         "MUST stay BELOW the host per-call timeout (soft deadline "
                         "fires before the host hard kill; four-level invariant: "
                         "stall-timeout-s < call-timeout-s < time-budget-ms x 0.8 < "
                         "host per-call timeout, >=20%% per level — the innermost "
                         "level is dropped when --stall-timeout-s 0). When passed, "
                         "--call-timeout-s MUST be passed explicitly and stay below "
                         "budget x 0.8 (spawn-time validation, exit 2 otherwise)")
    ap.add_argument("--call-timeout-s", type=int, default=None,
                    help=f"per-subprocess absolute timeout in seconds (default "
                         f"{DEFAULT_CALL_TIMEOUT_S} for out-of-host manual runs; "
                         f"calibrated for slow intranet LLM endpoints, ~4x headroom; "
                         f"better-slow-than-killed: a killed unit leaves no marker, "
                         f"stays pending, re-dispatch wastes a whole run). When "
                         f"--time-budget-ms is passed this flag MUST be passed "
                         f"explicitly and stay below budget x 0.8. The kill path is "
                         f"the whole-tree kill (see --stall-timeout-s)")
    ap.add_argument("--stall-timeout-s", type=int, default=None,
                    help=f"per-unit output-silence window in seconds, INITIAL "
                         f"value. FOUR-segment value domain: 0 = disable the "
                         f"criterion outright; 1..{STALL_TIMEOUT_FLOOR_S - 1} = "
                         f"rejected with exit 2 (this is the HARD REJECTION "
                         f"FLOOR = {STALL_TIMEOUT_FLOOR_S}); {STALL_TIMEOUT_FLOOR_S}"
                         f".. = a valid silence window. The default "
                         f"{DEFAULT_STALL_TIMEOUT_S} is the OUT-OF-HOST MANUAL-RUN "
                         f"default ONLY - it is NEVER a rejection floor and MUST "
                         f"NOT be described as one (the floor is "
                         f"{STALL_TIMEOUT_FLOOR_S}). When --time-budget-ms is "
                         f"passed (a host-driven run) this flag MUST be passed "
                         f"explicitly and stay below --call-timeout-s (the same "
                         f"four-level invariant) - NEVER omit it and rely on the "
                         f"default {DEFAULT_STALL_TIMEOUT_S}: the host-driven "
                         f"--call-timeout-s is far smaller, so the "
                         f"stall < call spawn-time check would refuse to start "
                         f"with exit 2 and make the tier unusable. Recommended "
                         f"host-driven value: 300. Semantics: no "
                         f"stdout/stderr bytes for this long -> "
                         f"that unit's whole process tree is killed (taskkill "
                         f"/T /F - the .cmd shim chain's real host-CLI process "
                         f"dies too) and the unit stays pending for re-dispatch. "
                         f"Byte-silence means the unit produced NOTHING for that "
                         f"long; it does NOT mean the unit is hung - on a "
                         f"rate-limited gateway the usual cause is the call "
                         f"waiting in the gateway's queue, which is locally "
                         f"indistinguishable from a real hang (same silence, same "
                         f"zero output). The criterion's job is to bound how long "
                         f"one slot may sit idle in this run - a convergence "
                         f"bound - never to diagnose unit health. Silence means "
                         f"BOTH streams idle (the clock takes the newer of the "
                         f"two streams' last-byte stamps), so a unit whose stderr "
                         f"never emits is not mistaken for silent. Default "
                         f"calibration: p99(completed-unit runtime) x 2, rounded "
                         f"down to the minute and never below "
                         f"{DEFAULT_STALL_TIMEOUT_S} (observed sample n=84: p50 "
                         f"134s / p95 229s / p99 325s / max 325s -> 650s -> 600s "
                         f"-> floor {DEFAULT_STALL_TIMEOUT_S}s). That sample is "
                         f"the SURVIVING population only - units killed for "
                         f"gateway queueing are absent from it by construction - "
                         f"so it bounds healthy units and MUST NOT be read as "
                         f"'past this it deserves to die'. Re-calibrate from the "
                         f"runtime_* fields every exit reports. The EFFECTIVE "
                         f"window widens within a run on false-kill "
                         f"self-evidence: if a stall-killed unit then completes "
                         f"on re-dispatch in the same run, the window becomes "
                         f"min(2x current, --call-timeout-s x "
                         f"{CONVERGENCE_HEADROOM}) for the rest of the run "
                         f"(stderr-disclosed, once per triggering unit). 0 "
                         f"disables the criterion outright - convergence is then "
                         f"bounded by --call-timeout-s ALONE, so a host-driven run "
                         f"SHOULD tighten that value; the 'stall < call' ordering "
                         f"constraint does not apply in this mode. A mis-killed "
                         f"unit re-dispatches and its "
                         f"<checkpoints>/<tier>/<unit>.run.log keeps the evidence, "
                         f"but it also loses the work already done AND its queue "
                         f"position. Kill scope is the unit's own session (units "
                         f"are spawned with start_new_session) - it NEVER "
                         f"terminates the dispatcher, and an interactive Ctrl-C no "
                         f"longer reaches in-flight units (the exit path "
                         f"tree-kills them; a hard kill's orphans are cleared with "
                         f"--kill-stale)")
    ap.add_argument("--hb-interval-s", type=int, default=DEFAULT_HB_INTERVAL_S,
                    help=f"stderr in-flight heartbeat period in seconds (default "
                         f"{DEFAULT_HB_INTERVAL_S}): one line per running unit "
                         f"(unit id + seconds since its child's last output) so a "
                         f"human distinguishes 'slow' from 'hung' live from the "
                         f"host TUI; stdout stays a single JSON line")
    ap.add_argument("--stall-waves", type=int, default=DEFAULT_STALL_WAVES,
                    help=f"convergence circuit breaker window multiplier: every "
                         f"--stall-waves x --wave dispatched units the disk "
                         f"terminal count (done+failed markers) is re-derived once; "
                         f"--stall-waves consecutive zero-growth re-derivations "
                         f"with units still queued/in-flight -> stop dispatching, "
                         f"exit 2 (default {DEFAULT_STALL_WAVES}; stdout carries "
                         f"stalled:true + stalled_pending[] with each stuck unit's "
                         f"marker existence; a stall-killed unit does not raise the "
                         f"disk count, so a deterministic hang is truncated here; "
                         f"recipe: stop re-dispatching, diagnose via "
                         f"resume_state.py --check)")
    ap.add_argument("--resume", action="store_true",
                    help="re-derive pending from disk markers (same entry point as a "
                         "fresh call; kept for call-shape parity)")
    ap.add_argument("--cooldown-s", type=int, default=DEFAULT_COOLDOWN_S,
                    help=f"fast-fail storm cooldown in seconds (default "
                         f"{DEFAULT_COOLDOWN_S}; 0 = off): when >= "
                         f"{REQUEUE_THRESHOLD} requeue events (crash/timeout/stall/"
                         f"spawn-error units returning to the queue tail; failed "
                         f"acks and pre-spawn anchor failures NEVER count — they "
                         f"terminate without requeueing) accumulate within a "
                         f"{REQUEUE_WINDOW_S}s sliding window, new dispatch pauses "
                         f"for this many seconds while in-flight units keep "
                         f"running and harvesting. The wait is capped by the "
                         f"remaining --time-budget-ms minus an in-flight "
                         f"convergence margin (observed avg unit duration x "
                         f"in-flight count); when the budget cannot cover it the "
                         f"cooldown degrades to continuing immediately with a "
                         f"stderr disclosure. Also arms the pre-breaker backoff: "
                         f"when the zero-progress breaker is about to exit 2, one "
                         f"single 'cooldown -> full disk re-derivation -> re-"
                         f"observe' round runs first (disk growth disarms the "
                         f"breaker; still zero growth exits 2 stalled) — never "
                         f"more than once per call. 0 disables the cooldown AND "
                         f"the pre-breaker backoff. stdout summary carries "
                         f"cooldowns:<n>")
    ap.add_argument("--quota-calls", type=int, default=None,
                    help="quota admission mode: model-call budget per window "
                         "(N) for calls-per-window-rate-limited gateways (e.g. "
                         "100 calls / 10 min -> --quota-calls 100 "
                         "--quota-window-s 600). MUST be passed together with "
                         "--quota-window-s — passing only one, or passing "
                         "--quota-calls-per-unit alone, is rejected with exit 2 "
                         "+ recipe (same spawn-time fail-loud shape as the "
                         "timeout invariant); value domain >= 1. The gate is an "
                         "ESTIMATE: a unit's real call count burns inside its "
                         "host-CLI child and is invisible to this dispatcher, "
                         "so admission runs on dispatches-in-window x K + K <= "
                         "N; an underestimate can still eat a 429 (the "
                         "window-reset cooldown and the crash-storm truncation "
                         "backstop it). Without both flags the runner is "
                         "byte-identical to the pre-quota behavior")
    ap.add_argument("--quota-window-s", type=int, default=None,
                    help="quota admission mode: window length in seconds (W); "
                         "MUST be passed together with --quota-calls (pairing "
                         "enforced at startup, exit 2 otherwise); value domain "
                         ">= 1. The dispatcher tracks its own unit-dispatch "
                         "timestamps over this sliding window; a short-of-"
                         "margin dispatch pauses in <=1s sleep shards until the "
                         "earliest timestamps slide out (in-flight units keep "
                         "running and harvesting; each wait episode discloses "
                         "the arithmetic and the expected resume time on "
                         "stderr; the wait is bounded by the remaining time "
                         "budget). The window is in-process: --resume starts a "
                         "fresh window and never tracks gateway-side spend "
                         "across processes. In quota mode a storm cooldown "
                         "carrying a rate-limit-signature crash waits out this "
                         "window's reset (last signature event + W) instead of "
                         "the fixed --cooldown-s, and the crash-storm "
                         "truncation fires only after one full reset wait has "
                         "completed and rate-limit crashes still recur")
    ap.add_argument("--quota-calls-per-unit", type=int, default=None,
                    help=f"quota admission mode: per-unit model-call ESTIMATE "
                         f"(K, default {DEFAULT_QUOTA_CALLS_PER_UNIT}). The "
                         f"default is the conservative upper bound of the "
                         f"observed 5-10 calls per unit: throttle too hard and "
                         f"a run goes slower than it must; bust the estimate "
                         f"and the quota breaks (429 storm + wasted retries "
                         f"cost whole re-runs) — calibrate DOWNWARD from real "
                         f"gateway-side counters, never above the observed "
                         f"worst. MUST NOT be passed without the "
                         f"--quota-calls/--quota-window-s pair (exit 2)")
    ap.add_argument("--no-rate-limit-stop", dest="rate_limit_stop",
                    action="store_false",
                    help="disable the rate-limit crash-storm fast-path truncation "
                         "(default: ON). With it on, every crashed unit's output "
                         "tails are classified against quota signatures "
                         "(429 / too many requests / rate limit / quota, "
                         "case-insensitive, crash terminal states only); when >= "
                         "--wave crashes since the last disk terminal advance are "
                         "ALL rate-limit, dispatch stops immediately (fast path, "
                         "ahead of any new cooldown) and the runner exits 2 with "
                         "stdout rate_limited:true + rate_limited_crashes:[ids] "
                         "and a stderr wait-one-quota-window recipe. Signature "
                         "drift (all crashes classify unknown) degrades gracefully: "
                         "no truncation, the event-driven cooldown and the breaker "
                         "still backstop. Non-rate-limit crashes never count "
                         "toward the threshold")
    ap.add_argument("--retry-failed", action="store_true",
                    help="re-dispatch units the tier enumerator re-lists as failed "
                         "(it is invoked with --include-failed when this flag is "
                         "set — unit identity ALWAYS comes from the enumerator, "
                         "never from filename stems). At claim the unit's .failed "
                         "marker is deleted (the failure evidence stays in the "
                         "unit's *.run.log) and the unit dispatches normally; a "
                         "re-failure writes a fresh marker (naturally bounded — "
                         "failed acks never requeue) and each unit is retried at "
                         "most once per call. stdout summary carries "
                         "retried_failed:<n>. Orchestrator discipline: at most "
                         "one --retry-failed round per tier wrap-up (failed>0 "
                         "with provider-transient run.log shape), then accept the "
                         "gap and disclose it in the report")
    ap.add_argument("--kill-stale", action="store_true",
                    help="orphan-tree cleanup: inspect <init-dir>/fanout_runner.<tier>.pid "
                         "liveness files and kill what they record (runner tree; or, when "
                         "the runner is dead, recorded host-CLI child trees — matched by "
                         "the EXECUTABLE TOKEN (argv[0] basename, .exe/.cmd/.bat stripped, "
                         "never a whole-cmdline substring match, so an unrelated process "
                         "merely mentioning a host name in its arguments is never killed)). "
                         "Needed after "
                         "a HARD kill only: units lead their own session, so an "
                         "interactive Ctrl-C no longer reaches in-flight units through "
                         "the tty, and the dispatcher's exit path tree-kills whatever is "
                         "still registered before deregistering. DESTRUCTIVE: run with "
                         "--dry-run first - a real kill with detected targets and "
                         "no prior dry-run review exits 2 + recipe. Idempotent; "
                         "tier-agnostic")
    ap.add_argument("--pending-file", metavar="<list-stdout.json>",
                    help="TEST HOOK: consume the tier listing from a file "
                         "(no spawn, no list invocation)")
    ap.add_argument("--purge-audit", action="store_true",
                    help="delete <inputs-dir>/*.task.md audit copies (with --dry-run: "
                         "list only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --purge-audit: list without deleting; alone: PURE PLAN "
                         "— zero writes zero spawns, unit list + would-write paths + "
                         "command form on stdout, exit 0")
    ap.add_argument("--cred-file", metavar="<run>/cred.json",
                    help="MANUAL/LEGACY static credential injection (no mgh "
                         "command flow uses it; opencode host form only; "
                         "claude/dsh exit 2): per-unit child config with the "
                         "cred-declared provider overridden to baseURL+apiKey "
                         "(id unchanged) + child env XDG_CONFIG_HOME/XDG_DATA_HOME "
                         "per unit — children never run their own login flow; "
                         "apikey reaches only the child config file, NEVER "
                         "stdout/stderr/logs. Validated by the mgh_credentials "
                         "validator (acquire the file there first). Bad/missing "
                         "file exits 2 before any spawn. Absent flag = "
                         "byte-identical legacy spawn")
    ap.add_argument("--isolate-data", action="store_true",
                    help="per-unit child data dir via XDG_DATA_HOME "
                         "(<plan-dir>/ocdata/<unit>) WITHOUT credential "
                         "injection — logs/sqlite/repos stop colliding across "
                         "concurrent children (opencode host form; other hosts: "
                         "noted and ignored). --cred-file implies it. Absent = "
                         "legacy shared data dir")
    ap.add_argument("--template", metavar="<tier-task.md>",
                    help="override task-message template path (default: sibling "
                         "prompts/fragments/fanout/<tier>-task.md of this install)")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.wave < 1:
        _eprint("error: --wave must be >= 1")
        return 2
    if args.time_budget_ms is not None and args.time_budget_ms < 0:
        _eprint("error: --time-budget-ms must be >= 0")
        return 2
    # Explicit-flag detection BEFORE defaults fill in (argparse default=None):
    # the invariant distinguishes "caller chose this value" from "default".
    call_explicit = args.call_timeout_s is not None
    if args.call_timeout_s is None:
        args.call_timeout_s = DEFAULT_CALL_TIMEOUT_S
    if args.call_timeout_s < 1:
        _eprint("error: --call-timeout-s must be >= 1")
        return 2
    if args.stall_timeout_s is None:
        args.stall_timeout_s = DEFAULT_STALL_TIMEOUT_S
    # Value domain: 0 (criterion disabled) or >= STALL_TIMEOUT_FLOOR_S. The
    # 1..floor-1 band is rejected rather than silently clamped: it is the
    # shape of a typo'd calibration, and a value that low false-kills
    # everything. The recipe names BOTH legal exits (raise it, or turn the
    # criterion off) — hiding the off-switch behind `--call-timeout-s - 1`
    # made it undiscoverable.
    if 0 < args.stall_timeout_s < STALL_TIMEOUT_FLOOR_S:
        _eprint(f"error: --stall-timeout-s {args.stall_timeout_s} is below the "
                f"floor: legal values are 0 (disable the silence criterion) or "
                f">= {STALL_TIMEOUT_FLOOR_S} (byte-silence floor — healthy LLM "
                f"units run minutes-level, so below {STALL_TIMEOUT_FLOOR_S}s "
                f"the false-kill rate dominates). Recipe: pass "
                f"--stall-timeout-s 0 to turn the criterion off (convergence is "
                f"then bounded by --call-timeout-s alone), or a value >= "
                f"{STALL_TIMEOUT_FLOOR_S} such as --stall-timeout-s 300")
        return 2
    if args.stall_timeout_s < 0:
        _eprint(f"error: --stall-timeout-s must be >= 0 (0 disables the silence "
                f"criterion; any other legal value is >= "
                f"{STALL_TIMEOUT_FLOOR_S})")
        return 2
    if args.hb_interval_s < 1:
        _eprint("error: --hb-interval-s must be >= 1")
        return 2
    if args.stall_waves < 1:
        _eprint("error: --stall-waves must be >= 1")
        return 2
    if args.cooldown_s < 0:
        _eprint("error: --cooldown-s must be >= 0 (0 disables the fast-fail "
                "cooldown and the pre-breaker backoff)")
        return 2

    # Quota-mode pairing + value domain, spawn-time fail-loud (same shape as
    # the timeout invariant: reject BEFORE any spawn or enumerator side
    # effect). Quota mode activates iff --quota-calls AND --quota-window-s are
    # BOTH explicitly passed; anything else (--quota-calls-per-unit alone, or
    # either half of the pair alone) is the shape of a truncated invocation —
    # a half-armed gate that would neither throttle nor fail loudly is exactly
    # the silent-misconfiguration shape the timeout invariant exists to kill.
    quota_paired = args.quota_calls is not None and args.quota_window_s is not None
    quota_half = (args.quota_calls is not None) != (args.quota_window_s is not None)
    if quota_half or (args.quota_calls_per_unit is not None and not quota_paired):
        _eprint("error: quota flags are not paired: quota admission mode "
                "activates only when BOTH --quota-calls N and --quota-window-s "
                "W are passed; --quota-calls-per-unit is an optional refinement "
                "of that pair and is never legal alone")
        _eprint("recipe: pass the pair, e.g. for a 100-calls-per-10-min "
                "gateway --quota-calls 100 --quota-window-s 600 "
                "[--quota-calls-per-unit 8]")
        return 2
    quota_mode = quota_paired
    if quota_mode:
        if args.quota_calls < 1 or args.quota_window_s < 1:
            _eprint(f"error: --quota-calls {args.quota_calls} / "
                    f"--quota-window-s {args.quota_window_s} must both be >= 1 "
                    f"(value domain N >= 1, W >= 1)")
            _eprint("recipe: e.g. --quota-calls 100 --quota-window-s 600 for a "
                    "100-calls-per-10-min gateway")
            return 2
    if args.quota_calls_per_unit is not None and args.quota_calls_per_unit < 1:
        _eprint("error: --quota-calls-per-unit must be >= 1 (a unit burns at "
                "least one model call)")
        return 2
    if args.quota_calls_per_unit is None:
        args.quota_calls_per_unit = DEFAULT_QUOTA_CALLS_PER_UNIT
    if quota_mode and args.quota_calls_per_unit > args.quota_calls:
        _eprint(f"hint: --quota-calls-per-unit {args.quota_calls_per_unit} > "
                f"--quota-calls {args.quota_calls}: even the FIRST unit of a "
                f"window cannot fit the estimate, so no unit will ever be "
                f"dispatched (the run waits out its time budget and exits "
                f"partial) — check the flags against the gateway quota")

    # Cred payload validation BEFORE anything runs (zero enumerator side
    # effects on a bad file — the fail-loud happens at startup, spawn-time
    # never sees an invalid payload; the validator is the producer's own).
    cred = None
    if args.cred_file:
        cred = _load_cred_file(args.cred_file)
        if cred is None:
            return 2

    tier = TIERS[args.tier]

    # Plan-path re-anchoring — ONE anchor shared by the dispatch path AND the
    # kill-stale scan (the liveness/sidecar home = plan_path.parent on both
    # sides). Every input is None-tolerant because kill-stale recovery runs
    # in exactly the broken states where artifact flags may be omitted:
    # whatever is present anchors, what is missing stays None.
    plan_raw = getattr(args, tier["plan_arg"], None)
    checkpoints = Path(args.checkpoints) if args.checkpoints else None
    inputs_dir = Path(args.inputs_dir) if args.inputs_dir else None
    plan_path = Path(plan_raw) if plan_raw else None
    # sdr: plan_arg = repo (a DIRECTORY anchor); the actual plan artifact is the run dir's
    # grouping.json (<checkpoints>/../grouping.json). liveness/sidecar home (plan_path.parent)
    # = the run dir — same <init-dir>/ neighbor semantics as the init tiers.
    if plan_path is not None and tier["list_script"] == "diff_group.py":
        anchor = checkpoints.parent if checkpoints is not None else plan_path
        plan_path = (anchor / "grouping.json").resolve()
    # t2/scout-merge: plan_arg = init_dir (a DIRECTORY anchor); the dispatcher's plan artifact is
    # <init-dir>/run_config.json (design D5) so the sidecar/liveness home (plan_path.parent)
    # = <init-dir> — same neighbor semantics as the other init tiers. run_config.json is
    # written by write_runconfig at step 0, so it always exists under a live run.
    if plan_path is not None and tier["list_script"] == "plan_aggregate.py":
        plan_path = (plan_path / "run_config.json").resolve()

    # --kill-stale recovery mode: NEVER requires the tier plan artifacts (it
    # runs in exactly the broken-state contexts where they may be missing).
    # Scan root = plan_path.parent — the run dir where the dispatcher actually
    # writes the liveness file (the naive "parent of whatever parameter shape
    # came in" inference scanned the repo parent / repo root for sdr's
    # directory-shaped --repo and reported none:true while the evidence sat
    # in the run dir). Without a plan artifact, fall back to the
    # checkpoints/inputs-dir neighbourhoods (standard <init-dir>/<sub>/
    # layouts: the parent's parent and parent). Tier-agnostic by
    # construction: the scan is a `fanout_runner.*.pid` glob.
    if args.kill_stale:
        if plan_path is not None:
            init_dirs = [plan_path.parent]
        else:
            init_dirs = []
            for p in (checkpoints, inputs_dir):
                if p is None:
                    continue
                rp = p.resolve()
                for cand in (rp.parent.parent, rp.parent):
                    if cand not in init_dirs:
                        init_dirs.append(cand)
        if not init_dirs:
            _eprint("hint: --kill-stale without any artifact flag has no run "
                    "dir to anchor the scan (pass the tier's plan artifact or "
                    "--checkpoints to target the run dir); nothing scanned")
        result, code = _kill_stale(init_dirs, args.dry_run)
        print(json.dumps(result, ensure_ascii=False))
        return code

    # Closed-set validation: every required tier artifact flag MUST be present
    # (R5.3b reject-ambiguous-inputs; fail-loud with the exact missing flag).
    missing = [f"--{a.replace('_', '-')}" for a in tier["required_args"]
               if not getattr(args, a, None)]
    if missing:
        _eprint(f"error: --tier {args.tier} requires {', '.join(missing)} "
                f"(got none); re-run with the tier's artifact flags — see "
                f"--help for the per-tier call shapes")
        return 2

    # Four-level timeout invariant, spawn-time fail-loud (design D5): the
    # defaults are calibrated for out-of-host manual runs; a host-driven run
    # that passes --time-budget-ms while keeping the 7200s default call-timeout
    # is GUARANTEED to degenerate into the host hard-killing the whole tree
    # first (observed 2026-09-14) — reject BEFORE any spawn or enumerator side
    # effect. budget=0 is exempt from the budget-vs-call levels (it can never
    # dispatch anything; the protective purpose is moot) but stall < call still
    # holds. Applies to all tiers identically.
    budget = args.time_budget_ms
    invariant_problems = []
    if budget is not None and budget > 0:
        budget_s = budget / 1000.0
        if not call_explicit:
            invariant_problems.append(
                f"--time-budget-ms {budget} passed without an explicit "
                f"--call-timeout-s (default {DEFAULT_CALL_TIMEOUT_S}s >= "
                f"budget x 0.8 = {budget_s * 0.8:.0f}s -> the soft deadline can "
                f"never fire before the per-call kill)")
        elif args.call_timeout_s >= budget_s * 0.8:
            invariant_problems.append(
                f"--call-timeout-s {args.call_timeout_s} must be < "
                f"time-budget-ms x 0.8 ({budget_s * 0.8:.0f}s)")
    # Only checked when the criterion is ON: with --stall-timeout-s 0 there is
    # no silence kill to order against the absolute one (design D2).
    stall_problem = False
    if args.stall_timeout_s > 0 and args.stall_timeout_s >= args.call_timeout_s:
        stall_problem = True
        invariant_problems.append(
            f"--stall-timeout-s {args.stall_timeout_s} must be < "
            f"--call-timeout-s {args.call_timeout_s} (a unit must hit the "
            f"silence kill before the absolute kill)")
    if invariant_problems:
        _eprint("error: timeout invariant violated:\n  - "
                + "\n  - ".join(invariant_problems))
        if stall_problem:
            # The commonest cause is a host-driven call that OMITTED the flag and
            # silently took the out-of-host default — say so, or the reader "fixes"
            # it by raising --call-timeout-s (which breaks the budget level instead).
            _eprint(f"recipe: pass --stall-timeout-s explicitly and keep it below "
                    f"--call-timeout-s — NEVER omit it and rely on the default "
                    f"{DEFAULT_STALL_TIMEOUT_S}s (a host-driven --call-timeout-s is "
                    f"far smaller, so the default is refused here by construction)")
        _eprint("recipe (compliant example for a 900000ms host / 720000ms "
                "budget): --time-budget-ms 720000 --call-timeout-s 540 "
                "--stall-timeout-s 300  (four levels, >=20% headroom per "
                "level: stall-timeout-s < call-timeout-s < time-budget-ms x "
                "0.8 < host per-call timeout; see --help). To turn the silence "
                "criterion off instead, pass --stall-timeout-s 0 — the "
                "stall < call level then does not apply and --call-timeout-s "
                "alone bounds convergence")
        return 2
    if budget is None:
        _eprint(f"hint: no --time-budget-ms (out-of-host manual run): "
                f"--call-timeout-s {args.call_timeout_s}s / --stall-timeout-s "
                f"{args.stall_timeout_s}s apply, no host hard-kill clamp above "
                f"them")

    if not plan_path.is_file():
        _eprint(f"error: {tier['plan_arg'].replace('_', '-')} artifact not found: "
                f"{plan_path}")
        return 1

    # --purge-audit: destructive op guarded by --dry-run (R5.3b), then stop.
    purged = []
    if args.purge_audit:
        if not args.dry_run:
            _eprint("error: --purge-audit requires --dry-run (destructive op guard, "
                    "R5.3b); run with --dry-run first to review the listing")
            return 2
        purged = _purge_audit(inputs_dir, dry_run=True)
        _eprint(f"purge-audit (dry-run): {len(purged)} audit file(s) would be deleted: "
                f"{purged[:10]}{'...' if len(purged) > 10 else ''}")
        result = {"runner": "fanout_runner", "tier": args.tier,
                  "purge_audit": "dry-run",
                  "would_delete": len(purged), "files": purged}
        print(json.dumps(result, ensure_ascii=False))
        return 0

    # Pending source: --pending-file (test hook) > sibling list CLI (D1/D6).
    if args.pending_file:
        try:
            listing = json.loads(Path(args.pending_file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            _eprint(f"error: unparsable --pending-file: {e}")
            return 1
        host = "test"
    else:
        listing = _list_pending(tier, args)
        # plan_aggregate nodes (t2 / scout-merge), needs_reduce=false: the aggregate input
        # fits the budget → single-context path, NOTHING to dispatch. The orchestrator is
        # not required to pre-check, so a dispatched run converges idempotently: 0 units,
        # partial:false, exit 0 (never the missing-`repo` error — that path is only for
        # listings that actually carry work).
        if listing.get("needs_reduce") is False:
            _eprint(f"[fanout_runner] {args.tier}: listing needs_reduce=false — nothing "
                    f"to dispatch (single-context aggregate)")
            summary = {"runner": "fanout_runner", "tier": args.tier,
                       "total": 0, "done": 0, "failed": 0, "pending": 0,
                       "waves_run": 0, "partial": False, "stall_killed": [],
                       "stalled": False,
                       "note": "aggregate input <= budget — single-context path, "
                               "no shards dispatched"}
            if quota_mode:
                # nothing was dispatched, so the wait count is trivially 0 —
                # but the configured quota still belongs in the summary
                summary["quota"] = {"calls": args.quota_calls,
                                    "window_s": args.quota_window_s,
                                    "calls_per_unit": args.quota_calls_per_unit,
                                    "admission_waits": 0}
            print(json.dumps(summary, ensure_ascii=False))
            return 0
        host = _detect_host(args.host, tier)
        if host == "dsh":
            # Pre-spawn gate: mount file / mgh profile missing → exit 2 +
            # recipe with ZERO spawns (never a wave of host-error crashes).
            problem = _dsh_precheck(args.tier)
            if problem:
                _eprint(f"error: dsh dispatch precheck failed: {problem}")
                return 2
    # Static-injection host gate: the child-config mechanism is shaped by the
    # opencode form (global config + XDG variables). Other host forms exit 2
    # rather than silently degrading to a no-credential dispatch (the failure
    # mode this flag exists to fix would come back as a stall storm). The
    # in-process test hook ("test") is allowed for materialization-only
    # verification — it never spawns.
    if cred is not None and host not in ("opencode", "test"):
        _eprint(f"error: --cred-file injection is implemented for the opencode "
                f"host form only (resolved host: {host})")
        _eprint("recipe: dispatch with --host opencode, or drop --cred-file "
                "for hosts that carry their own authentication")
        return 2
    if args.isolate_data and host not in ("opencode", "test"):
        _eprint(f"note: --isolate-data ignored for host {host} (XDG data "
                f"isolation is an opencode-form mechanism)")

    repo_str = listing.get("repo") or ""
    if not repo_str:
        _eprint("error: pending listing carries no `repo` anchor")
        return 1
    repo = Path(repo_str).resolve()
    if not repo.is_dir():
        _eprint(f"error: repo anchor is not a directory: {repo}")
        return 1

    template = _load_template(tier, args.template)
    codegraph = _codegraph_signal(plan_path, args.tier)
    total = int(listing.get("total", 0))
    done0 = int(listing.get("done", 0))
    failed0 = int(listing.get("failed", 0))

    # --dry-run dispatch form: PURE PLAN (short-circuit BEFORE the wave
    # machine — no liveness write, no sidecar, no audit copies, no markers,
    # no childcfg materialization, no spawn). The plan carries what a real
    # run WOULD write per unit; the pre-spawn anchor check runs read-only so
    # a path-drift unit shows up as would_fail_pre_spawn instead of writing a
    # .failed marker. (--kill-stale/--purge-audit dry-run review guards are
    # separate and returned earlier.) The tier's own enumerator ran above with
    # its established idempotent contract — the dispatcher's own disk surface
    # stays untouched.
    if args.dry_run:
        plan_entries = []
        for unit in listing.get("pending", []):
            uid = unit.get(tier["id_field"], "?")
            entry = {
                "unit": uid,
                "audit_path": str((inputs_dir /
                                   f"{_safe_name(str(uid))}.task.md").resolve()),
                "done_marker": unit.get("done_marker"),
                "failed_marker": unit.get("failed_marker"),
                "command": " ".join(_spawn_cmd(tier, host)),
            }
            reason = _anchor_check(tier, unit, repo)
            if reason:
                entry["would_fail_pre_spawn"] = reason
            plan_entries.append(entry)
        result = {"runner": "fanout_runner", "tier": args.tier,
                  "repo": repo_str, "host": host, "total": total,
                  "plan_units": len(plan_entries), "dry_run": True,
                  "note": "pure plan — nothing written, nothing spawned "
                          "(audit copies, markers, liveness, sidecar, child "
                          "configs and child processes are all skipped)",
                  "plan": plan_entries}
        print(json.dumps(result, ensure_ascii=False))
        return 0

    deadline = (time.monotonic() + args.time_budget_ms / 1000.0
                if args.time_budget_ms is not None else None)
    waves_run = 0            # cumulative units dispatched this run (slot backfill)
    failed_written: list[str] = []
    stall_killed: list[str] = []
    kill_failed: list[str] = []    # units whose tree-kill FAILED (survivor owns)
    overflow_units: list[str] = []  # crashes whose stderr matched an overflow signature
    unit_durations: list[float] = []
    # Cost visibility (design D4): durations split by OUTCOME, so the runtime
    # distribution the window is calibrated against holds COMPLETED units only
    # — a killed unit's runtime is an artifact of the window itself, not a
    # sample of the population the window is supposed to sit above, and mixing
    # the two would inflate every reported percentile. (unit_durations stays
    # the all-outcomes list the cooldown's convergence margin and the sidecar's
    # wave_done_avg_s already consume.)
    done_durations: list[float] = []
    stall_kill_durations: list[float] = []
    # Adaptive silence window (design D3): the run's EFFECTIVE window, with the
    # flag supplying only its initial value. Widened by false-kill
    # self-evidence, discarded with the run (NEVER persisted, NEVER written
    # back onto args), and read at each dispatch so a widening reaches the
    # units dispatched afterwards.
    stall_window_s = int(args.stall_timeout_s)
    stall_widened = False          # did a widening actually happen this run?
    widen_units: set[str] = set()  # units that already contributed evidence
    stall_lock = threading.Lock()  # guards stall_window_s + widen_units
    skipped_terminal = 0     # units lazy-skipped: marker already terminal on disk
    stalled = False
    # Fast-fail storm state (design D1/D2/D4). Three counters that NEVER share
    # a window: (1) requeue_times — the cooldown's sliding time window;
    # (2) storm_state["crashes"] — the storm truncation's window, anchored on
    # disk terminal advance (ok/failed marker landing clears it), not on time;
    # (3) the breaker's dispatch-window counter below.
    storm_lock = threading.Lock()
    requeue_times: list[float] = []   # monotonic ts of crash/timeout/stall/spawn-error requeues
    storm_state = {"rate_limited": False, "crashes": [], "units": []}
    # Credential-expiry fast-stop state (--cred-file only; guarded by the
    # same lock — worker threads arm it, the main thread's gates read it).
    cred_state = {"expired": False, "units": []}
    # Per-unit child environment roots (--cred-file / --isolate-data): both
    # live beside the tier's plan artifact (sdr: the run dir; init tiers: the
    # init dir). Unused (plain Paths, never created) when no flag is active.
    childcfg_root = plan_path.parent / "childcfg"
    ocdata_root = plan_path.parent / "ocdata"
    inject_active = cred is not None or args.isolate_data
    cooldown_until = 0.0     # monotonic ts until which new dispatch is paused
    cooldowns = 0            # cooldowns performed this run (stdout `cooldowns`)
    backoff_used = False     # pre-breaker backoff: at most once per call
    backoff_pending = False  # armed backoff awaiting its post-cooldown re-derivation
    # Quota admission state (quota mode only; every var stays untouched and
    # unread without the flag pair). quota_dispatch_times feeds the
    # sliding-window estimate; last_rl_event_ts is the most recent
    # rate-limit-signature CRASH ts (the window-reset cooldown's anchor);
    # quota_reset_pending_ts tracks a cooldown that is waiting out a FULL
    # window reset, and quota_window_completed_ts is the ts such a wait
    # actually completed — the crash-storm truncation only counts rate-limit
    # crashes at/after it (等满窗口才截断).
    quota_dispatch_times: list[float] = []  # monotonic ts of THIS run's dispatches
    quota_admission_waits = 0               # dispatch-pause episodes (stdout/sidecar)
    quota_wait_active = False               # inside an admission-wait episode?
    last_rl_event_ts: float | None = None
    rl_crash_times: list[float] = []        # every rate-limit crash ts this run
    quota_reset_pending_ts: float | None = None
    quota_window_completed_ts: float | None = None
    retried_once: set[str] = set()   # --retry-failed: per-unit once-per-call bound
    retried_failed = 0       # markers deleted at claim this run (stdout `retried_failed`)
    # Zero-progress circuit breaker, dispatch-window anchored: every K =
    # --stall-waves x --wave newly dispatched units, re-derive the disk
    # terminal count once; --stall-waves consecutive zero-growth re-derivations
    # with units still queued → convergence failure.
    window_k = args.stall_waves * args.wave
    dispatched_since_window = 0
    window_left = args.stall_waves
    last_terminal_count = None
    last_window_snap: dict = {}
    # kill-failed units are disk-pending but NEVER queueable again this run;
    # the breaker's trip condition must see them (they are the "units still to
    # dispatch" the stalled disclosure reports) and the exit summary must not
    # drop them from pending
    last_stuck_pending: list = []

    def _rate_limited() -> bool:
        with storm_lock:
            return storm_state["rate_limited"]

    def _cred_expired() -> bool:
        with storm_lock:
            return cred_state["expired"]

    def _quota_state() -> tuple[bool, int, float]:
        """(admissible, used_calls, resume_ts) for the quota gate at now;
        arithmetic lives in the module-level pure `_quota_admission`."""
        return _quota_admission(quota_dispatch_times, args.quota_window_s,
                                args.quota_calls, args.quota_calls_per_unit,
                                time.monotonic())

    def _quota_body() -> dict:
        """stdout/sidecar quota disclosure (single truth source: both the
        terminal sidecar write and the exit summary spread THIS dict, so the
        two can never disagree). Empty without the flag pair — the key is
        absent, never null, matching the optional-key shape of
        runtime_p50_s/stall_window_s."""
        if not quota_mode:
            return {}
        return {"quota": {"calls": args.quota_calls,
                          "window_s": args.quota_window_s,
                          "calls_per_unit": args.quota_calls_per_unit,
                          "admission_waits": quota_admission_waits}}

    def _cooldown_budget_cap() -> float:
        """Max cooldown seconds the remaining time budget allows (design D3);
        arithmetic lives in the module-level pure `_cooldown_cap_s`."""
        return _cooldown_cap_s(args.cooldown_s, deadline, time.monotonic(),
                               unit_durations, len(inflight))

    def _start_cooldown(why: str, quota_reset: bool = True) -> None:
        """Arm one gate-based cooldown: pause NEW dispatch until
        cooldown_until (in-flight units keep running and harvesting); budget-
        capped, disclosed on stderr, and it consumes the requeue window (the
        next cooldown needs fresh events). NEVER sleeps here — the dispatch
        loop's gates do the waiting so harvesting is never blocked.

        Quota mode (`quota_reset=True`, storm cooldowns only — the pre-breaker
        backoff passes False and keeps the plain --cooldown-s semantics: zero
        progress is not necessarily a quota shape, so its wait must never be
        amplified to window scale): when the triggering requeue events include
        a rate-limit-signature crash, the endpoint becomes
        max(regular endpoint, last signature event + W) — wait out the quota
        window reset rather than a fixed number of seconds. The reset wait is
        capped by the same remaining-time-budget arithmetic; a truncated (not
        fully waited) reset never marks the window as completed, so the
        crash-storm truncation's "等满窗口才截断" precondition stays honest."""
        nonlocal cooldown_until, cooldowns
        nonlocal quota_reset_pending_ts
        cap = _cooldown_budget_cap()
        dur = min(float(args.cooldown_s), cap)
        reset_full = False
        reset_note = ""
        if quota_reset and quota_mode and args.quota_window_s:
            with storm_lock:
                rl_ts = last_rl_event_ts
            if rl_ts is not None:
                now = time.monotonic()
                reset_end = rl_ts + args.quota_window_s
                dur = max(float(args.cooldown_s), reset_end - now)
                # Budget cap applies to deadline-driven runs only: with no
                # --time-budget-ms there is no budget to cap with (the plain
                # path's `min(cooldown_s, cap)` degenerates to cooldown_s for
                # that same reason — clamping the reset with it would silently
                # shrink every out-of-host window wait back to --cooldown-s).
                if deadline is not None:
                    dur = min(dur, cap)
                reset_full = (now + dur) >= (reset_end - 1e-9)
                reset_note = (" — waiting out the quota window reset "
                              f"(last rate-limit signature event + "
                              f"{args.quota_window_s}s)")
        if dur <= 0:
            _eprint(f"[fanout_runner] cooldown skipped ({why}): remaining time "
                    f"budget cannot cover it (cap {cap:.0f}s) — continuing "
                    f"immediately")
            return
        with storm_lock:
            requeue_times.clear()
            cooldown_until = time.monotonic() + dur
            cooldowns += 1
            nth = cooldowns
        if reset_full:
            quota_reset_pending_ts = cooldown_until
        _eprint(f"[fanout_runner] cooldown #{nth} ({why}): fast-fail requeue "
                f"threshold hit — pausing NEW dispatch for {dur:.0f}s"
                + reset_note
                + (f" (capped from {args.cooldown_s}s by remaining time budget)"
                   if dur < args.cooldown_s and not reset_note else "")
                + (" (window-reset wait truncated by remaining time budget — "
                   "NOT a full window)"
                   if reset_note and not reset_full else "")
                + "; in-flight units keep running and harvesting")

    def _maybe_cooldown() -> None:
        """Arm a storm cooldown iff the sliding window holds enough requeue
        events. Runs on the dispatch (main) thread only; the storm-truncation
        fast path takes priority over arming a new cooldown."""
        with storm_lock:
            if storm_state["rate_limited"] or cred_state["expired"]:
                return
            now = time.monotonic()
            recent = [t for t in requeue_times if now - t <= REQUEUE_WINDOW_S]
            requeue_times[:] = recent
            armed = (args.cooldown_s > 0 and now >= cooldown_until
                     and len(recent) >= REQUEUE_THRESHOLD)
        if armed:
            _start_cooldown(f">={REQUEUE_THRESHOLD} requeues in "
                            f"{REQUEUE_WINDOW_S}s window")

    def _cost_payload() -> dict:
        """Cost-visibility fields (design D4), derived ONCE for both the stdout
        summary and the sidecar so the two can never disagree.

        Omissions are deliberate: `runtime_*` is absent (never 0) when the run
        completed no unit, because 0 seconds would read as "instant units"
        rather than "no data"; `stall_window_s` is absent unless the window
        actually widened. The always-present pair answers "what did this run's
        window cost me": `stall_killed_slots_s` = slot-seconds spent on units
        that were silence-killed, and the pct denominator is this run's total
        slot-seconds (elapsed x --wave = the parallel capacity the window had
        to work with), i.e. the share of capacity the kills burnt."""
        slots_s = round(sum(stall_kill_durations), 1)
        capacity_s = max(0.0, time.monotonic() - t0) * args.wave
        body = {
            "stall_killed_slots_s": slots_s,
            "stall_killed_slot_pct": (round(slots_s / capacity_s * 100, 1)
                                      if capacity_s > 0 else 0.0),
        }
        if done_durations:
            body["runtime_p50_s"] = _percentile_int(done_durations, 50)
            body["runtime_p95_s"] = _percentile_int(done_durations, 95)
            body["runtime_max_s"] = int(round(max(done_durations)))
        if stall_widened:
            body["stall_window_s"] = stall_window_s
        return body

    def _sidecar_payload(state: str, snap_dict: dict, pending_now: list,
                         cost: dict | None = None,
                         quota: dict | None = None) -> dict:
        """Sidecar body — counts derive from the SAME snapshot as the stdout
        summary (single source; test asserts the two agree). `cost` lets the
        terminal caller pass the one `_cost_payload()` dict the stdout summary
        also uses: the slot-time percentage divides by a LIVE elapsed-time
        measurement, so two separate calls would not agree bit-for-bit and the
        sidecar/stdout equality guarantee would be lost to rounding. `quota`
        is the same single-source story for the quota disclosure block."""
        if cost is None:
            cost = _cost_payload()
        if quota is None:
            quota = _quota_body()
        done_n = int(snap_dict.get("done", done0))
        # Same max-of-two-views as the exit summary (design D3): the snapshot
        # and the write ledger count the same markers — summing double-counts
        # whenever the snapshot is fresh.
        failed_n = max(int(snap_dict.get("failed", failed0)),
                       failed0 + len(set(failed_written)))
        pending_n = len(pending_now)
        avg = (sum(unit_durations) / len(unit_durations)) if unit_durations else 0.0
        return {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),  # local tz
            "host": host,
            "tier": args.tier,
            "total": total,
            "done": done_n,
            "failed": failed_n,
            "pending": pending_n,
            "wave": args.wave,
            "waves_run": waves_run,
            "wave_done_avg_s": round(avg, 1),
            # Conservative ETA (one unit per in-flight slot): a human reference
            # number, precision NOT promised.
            "eta_batches": pending_n,
            "state": state,
            **cost,
            **quota,
        }

    def _snapshot() -> dict:
        """Re-derive pending via the list CLI (or the frozen test listing,
        before the first dispatch) — disk markers remain the only truth source
        (D4)."""
        if args.pending_file and waves_run == 0:
            return listing
        if args.pending_file:
            return {"repo": repo_str, "total": total, "done": done0,
                    "failed": failed0, "pending": []}  # test hook: single pass
        return _list_pending(tier, args)

    snap = _snapshot()
    id_field = tier["id_field"]
    queue: deque = deque(snap.get("pending", []))
    _eprint(f"[fanout_runner] tier={args.tier} host={host} repo={repo} "
            f"total={total} pending={len(queue)} wave={args.wave} "
            f"codegraph={codegraph}")
    # Special-auth advisory (command-agnostic, all tiers): the optional
    # deployment doc is present but this run dispatches without static
    # injection — one stderr note, exit code and behavior untouched.
    _auth_doc = _special_auth_doc_path(repo)
    if cred is None and _auth_doc.is_file():
        _eprint(f"[fanout_runner] note: special-auth entry present "
                f"({_auth_doc}) — read it when needed and follow its own "
                f"instructions; this run dispatches WITHOUT static injection")
    # Orphan advisory (non-blocking): a residual liveness file means the
    # previous run ended hard; read it BEFORE the write below replaces it.
    _orphan_advisory(plan_path.parent, args.tier)

    # Liveness registration (orphan signal, NOT a lock): written for EVERY
    # dispatch exit path via try/finally below; a hard kill leaves it behind
    # and --kill-stale disambiguates. The body dict is reused (mutated only in
    # its `children` field) so the started_ts/cmdline stay stable across
    # refreshes.
    liveness_path = _write_liveness(plan_path.parent, args.tier, host)
    try:
        liveness_body = json.loads(liveness_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # L12: the write above already warned (non-fatal contract) — a failed
        # write leaves nothing to read back (read-only run dir). Rebuild the
        # same body in place so the run continues and children[] refreshes
        # keep working; the file simply stays absent until a write succeeds.
        liveness_body = _liveness_body(args.tier, host)
    children_now: list = []
    children_lock = threading.Lock()
    hb_state = {"done": done0}
    hb_lock = threading.Lock()
    t0 = time.monotonic()
    # in-flight output sinks for the periodic heartbeat: uid -> (out_sink, err_sink)
    sinks: dict = {}
    sinks_lock = threading.Lock()
    next_hb = t0 + args.hb_interval_s
    pool = ThreadPoolExecutor(max_workers=args.wave)
    inflight: dict = {}  # Future -> unit (main loop only)

    def _hb_count(inc: int = 0) -> int:
        with hb_lock:
            hb_state["done"] += inc
            return hb_state["done"]

    def _next_unit() -> dict | None:
        """Pop the next dispatchable unit from the in-memory queue; marker
        lazy-check first (disk truth, O(1)): a unit whose .done/.failed marker
        already exists is skipped, never re-spawned — the queue snapshot may be
        stale by the time a slot frees. With --retry-failed a .failed marker is
        instead DELETED at claim (once per unit per call; the failure evidence
        stays in the unit's *.run.log) and the unit dispatches normally."""
        nonlocal skipped_terminal, retried_failed
        while True:
            try:
                unit = queue.popleft()
            except IndexError:
                return None
            dm, fm = unit.get("done_marker"), unit.get("failed_marker")
            uid = unit.get(id_field, "?")
            try:
                if dm and Path(dm).is_file():
                    skipped_terminal += 1
                    _eprint(f"[fanout_runner] unit {uid}: "
                            f"marker already terminal on disk — skip (lazy check)")
                    continue
                if fm and Path(fm).is_file():
                    if args.retry_failed and uid not in retried_once:
                        retried_once.add(uid)
                        try:
                            Path(fm).unlink()
                        except OSError as e:
                            _eprint(f"warn: cannot delete failed marker for "
                                    f"{uid} at {fm}: {e} — skip (lazy check)")
                            skipped_terminal += 1
                            continue
                        retried_failed += 1
                        _eprint(f"[fanout_runner] unit {uid}: --retry-failed — "
                                f".failed marker deleted at claim, re-dispatching "
                                f"(evidence kept in the unit's run.log)")
                        return unit
                    skipped_terminal += 1
                    _eprint(f"[fanout_runner] unit {uid}: "
                            f"marker already terminal on disk — skip (lazy check)")
                    continue
            except OSError:
                pass
            return unit

    def _register_child(uid: str):
        def _reg(pid: int) -> None:
            # liveness children[] registers AT SPAWN (_run_unit fires this with
            # the Popen pid) and the entry is removed at that unit's terminal —
            # the registry reflects the true in-flight set at any instant.
            with children_lock:
                children_now.append({"pid": pid, "unit": uid, "tier": args.tier})
                _update_liveness_children(liveness_path, liveness_body,
                                          list(children_now))
        return _reg

    def _terminal_children_rm(child_pid: int | None) -> None:
        if child_pid is None:
            return
        with children_lock:
            children_now[:] = [c for c in children_now
                               if c["pid"] != child_pid]
            _update_liveness_children(liveness_path, liveness_body,
                                      list(children_now))

    def _maybe_widen_window(uid: str) -> None:
        """False-kill self-evidence (design D3): a unit that was stall-killed
        (no ack, no marker) and then COMPLETED on re-dispatch within this same
        run is hard proof that the window was too tight for this run's
        contention — the unit was never hung, it was waiting. Relax the window
        for the units dispatched from here on.

        Bounded by the same convergence margin the timeout invariant uses
        (`--call-timeout-s x CONVERGENCE_HEADROOM`), so the absolute per-call
        kill always stays reachable. Counted once per unit: a unit that is
        killed-and-succeeds repeatedly is ONE piece of evidence, not N —
        otherwise a single flaky unit would ratchet the window to the ceiling.
        No-op when the criterion is off (nothing to widen) or when the window
        is already at the ceiling (nothing to disclose)."""
        nonlocal stall_window_s, stall_widened
        if args.stall_timeout_s <= 0:
            return
        with stall_lock:
            if uid in widen_units or uid not in stall_killed:
                return
            widen_units.add(uid)
            new_w = _widened_stall_window(stall_window_s, args.call_timeout_s)
            if new_w <= stall_window_s:
                return  # already at the ceiling: no event, no disclosure
            old_w, stall_window_s = stall_window_s, new_w
            stall_widened = True
        cap = int(args.call_timeout_s * CONVERGENCE_HEADROOM)
        _eprint(f"[fanout_runner] stall window widened {old_w}s -> {new_w}s "
                f"(unit {uid} was stall-killed and then completed on "
                f"re-dispatch in this run — evidence the window was too tight "
                f"here; ceiling = --call-timeout-s {args.call_timeout_s} x "
                f"{CONVERGENCE_HEADROOM} = {cap}s; applies to units dispatched "
                f"from here on)")

    def _dispatch(unit: dict, seq: int) -> None:
        nonlocal last_rl_event_ts
        uid = unit.get(id_field, "?")
        # Anchor-tree interception BEFORE spawn (path-drift never spawns).
        reason = _anchor_check(tier, unit, repo)
        if reason:
            if _write_failed_marker(tier, unit, reason, repo):
                failed_written.append(uid)
            _hb(t0, args.tier, seq, uid, "failed", _hb_count(), total)
            _eprint(f"[fanout_runner] unit {uid}: FAILED pre-spawn ({reason})")
            # pre-spawn failed terminal = disk terminal advance → clears the
            # storm window
            with storm_lock:
                storm_state["crashes"].clear()
            return
        task = _fill_template(tier, template, unit, repo_str, codegraph)
        if args.dry_run:
            # Unreachable via main() (the pure-plan short-circuit returns
            # before the wave machine); kept as a write-purity backstop so a
            # future refactor cannot silently reintroduce dry-run writes.
            _eprint(f"[fanout_runner] unit {uid}: dry-run — no write, no spawn")
            return
        audit = inputs_dir / f"{_safe_name(uid)}.task.md"
        try:
            audit.parent.mkdir(parents=True, exist_ok=True)
            audit.write_text(task, encoding="utf-8")
        except OSError as e:
            _eprint(f"warn: audit copy unwritable for {uid}: {e}")
        # Per-unit execution-environment injection (static credentials and/or
        # data isolation; opencode form only, gated at startup — the in-
        # process "test" host also materializes, for verification without a
        # spawn). Materialize the child config FIRST (a failure is that
        # unit's pre-spawn failure, never a half-configured spawn), then hand
        # the XDG env to _run_unit via the _UNIT_ENV registry — its 9-arg
        # signature is frozen.
        if inject_active:
            safe_uid = _safe_name(str(uid))
            unit_cfg_dir = childcfg_root / safe_uid
            unit_data_dir = ocdata_root / safe_uid
            extra_env = {}
            if cred is not None:
                try:
                    _materialize_child_config(cred, unit_cfg_dir)
                    unit_data_dir.mkdir(parents=True, exist_ok=True)
                except (OSError, ValueError) as e:
                    reason = f"cred-materialize: {e}"
                    if _write_failed_marker(tier, unit, reason, repo):
                        failed_written.append(uid)
                    _hb(t0, args.tier, seq, uid, "failed", _hb_count(), total)
                    _eprint(f"[fanout_runner] unit {uid}: FAILED pre-spawn "
                            f"({reason[:200]})")
                    return
                extra_env["XDG_CONFIG_HOME"] = str(unit_cfg_dir)
            extra_env["XDG_DATA_HOME"] = str(unit_data_dir)
            if host != "test":
                _UNIT_ENV[uid] = extra_env
        if host == "test":
            _eprint(f"[fanout_runner] unit {uid}: test hook — no spawn")
            return
        cmd = _spawn_cmd(tier, host)
        # Snapshot the run's effective silence window for THIS attempt (design
        # D3): the unit is judged against one fixed window for the whole
        # attempt, so a mid-flight widening never retroactively moves the
        # criterion of a unit already running — it reaches the next dispatch.
        # The same snapshot is what this unit's heartbeat lines disclose.
        window = stall_window_s
        out_sink = {"ts": time.monotonic(), "tail": ""}
        err_sink = {"ts": out_sink["ts"], "tail": ""}
        sink_lock = threading.Lock()
        out_sink["lock"] = sink_lock
        err_sink["lock"] = sink_lock
        with sinks_lock:
            sinks[uid] = (out_sink, err_sink, window)
        # Hand the SAME dicts to _run_unit's reader threads (M2): from here
        # the heartbeat's idle reads live last-output stamps.
        _UNIT_SINKS[uid] = (out_sink, err_sink)
        _hb(t0, args.tier, seq, uid, "spawn", _hb_count(), total)
        spawn_t0 = time.monotonic()
        run_log = (Path(args.checkpoints) / args.tier /
                   f"{_safe_name(uid)}.run.log").resolve()
        status, ack, detail, child_pid, was_stalled, kill_ok = _run_unit(
            host, cmd, task, repo, args.call_timeout_s,
            window, run_log, uid, _register_child(uid))
        # Defensive clear (a faked/direct _run_unit that never claims leaves
        # the entry behind; a real one already popped it).
        _UNIT_SINKS.pop(uid, None)
        _UNIT_ENV.pop(uid, None)
        # Credential-expiry classification (only with --cred-file): scan BOTH
        # output tails on every non-ok terminal (crash/timeout/stall/spawn-
        # error and failed acks) against the cred file's signatures. The first
        # hit arms the fast-stop (gates read cred_state); the unit's own
        # terminal branch below keeps its EXISTING disk semantics (failed ack
        # → .failed marker; others stay pending for re-dispatch) — the
        # classification is a stop-and-recipe layer, never a new marker shape.
        if (cred is not None and cred["expired_signatures"]
                and (status != "spawn-ok"
                     or (ack is not None and ack.startswith("failed:")))):
            if _cred_expired_tail(cred, out_sink["tail"], err_sink["tail"]):
                with storm_lock:
                    if uid not in cred_state["units"]:
                        cred_state["units"].append(uid)
                    cred_state["expired"] = True
                _eprint(f"[fanout_runner] unit {uid}: {_CRED_EXPIRED_MARK}")
                _eprint(f"[fanout_runner] {_CRED_EXPIRED_RECIPE}")
        elapsed = time.monotonic() - spawn_t0
        unit_durations.append(elapsed)
        if was_stalled:
            # slot-seconds burnt by a silence kill (design D4 cost visibility)
            stall_kill_durations.append(elapsed)
        with sinks_lock:
            sinks.pop(uid, None)
        if was_stalled:
            stall_killed.append(uid)
        if ack is not None and ack.startswith("failed:"):
            if _write_failed_marker(tier, unit, ack[len("failed:"):], repo):
                failed_written.append(uid)
            _hb(t0, args.tier, seq, uid, "failed", _hb_count(), total)
            _eprint(f"[fanout_runner] unit {uid}: failed ack → .failed marker")
            # failed terminal = disk terminal advance → clears the storm window
            with storm_lock:
                storm_state["crashes"].clear()
            _terminal_children_rm(child_pid)
        elif status in ("timeout", "crash", "spawn-error", "stall"):
            _hb(t0, args.tier, seq, uid,
                "stall" if status == "stall" else
                "timeout" if status == "timeout" else "crash",
                _hb_count(), total)
            if not kill_ok:
                # KILL-FAILED: the tree survived every kill attempt — the
                # survivor OWNS this unit. Re-dispatching would run the unit
                # concurrently with the process we failed to kill and race
                # its checkpoint; the pid STAYS in liveness children[] so
                # --kill-stale can still find it (removing it here minted an
                # untrackable orphan).
                kill_failed.append(uid)
                _eprint(f"[fanout_runner] unit {uid}: TREE-KILL FAILED after "
                        f"{status} — the process survived every kill attempt "
                        f"and OWNS this unit: NO re-dispatch this run (its "
                        f"marker lands whenever the survivor finishes, else "
                        f"a later --resume re-dispatches); pid kept in the "
                        f"liveness children[]. Recipe: "
                        f"`fanout_runner.py --kill-stale --dry-run` lists "
                        f"the survivor")
                return
            _eprint(f"[fanout_runner] unit {uid}: {status} ({detail[:200]}) → "
                    f"stays pending (re-dispatch); run.log: {run_log}")
            if status == "crash" and detail.startswith(_OVERFLOW_MARK):
                # P2 diagnosis: surface the sharding fix; the unit itself keeps
                # the unchanged crash semantics below (stays pending).
                overflow_units.append(uid)
                _eprint(f"[fanout_runner] unit {uid}: {_OVERFLOW_RECIPE}")
            # Terminal-less unit (no ack, no marker): back into the queue tail
            # for in-run re-dispatch. The dispatch-window breaker is what
            # truncates a deterministically hung unit's kill→re-dispatch cycle.
            queue.append(unit)
            # requeue event → the cooldown's sliding time window counts it
            # (failed acks and pre-spawn anchor failures never get here).
            with storm_lock:
                requeue_times.append(time.monotonic())
            if status == "crash":
                # crash-tail rate-limit classification (the mark rode the
                # detail out of _run_unit); crash terminal states only.
                rl = detail.startswith(_RATELIMIT_MARK)
                _eprint(f"[fanout_runner] unit {uid}: crash_cause="
                        f"{'rate-limit' if rl else 'unknown'}")
                with storm_lock:
                    storm_state["crashes"].append((uid, rl))
                    if rl:
                        # quota mode anchors: the window-reset cooldown waits
                        # from the LAST signature event; the truncation's
                        # "等满窗口才截断" precondition counts signature
                        # crashes at/after a fully-waited reset (main thread
                        # sets quota_window_completed_ts; GIL-atomic float
                        # read here inside the lock).
                        last_rl_event_ts = time.monotonic()
                        rl_crash_times.append(last_rl_event_ts)
                    waited_full_reset = (
                        not quota_mode
                        or (quota_window_completed_ts is not None
                            and any(t >= quota_window_completed_ts
                                    for t in rl_crash_times)))
                    truncated = (args.rate_limit_stop
                                 and not storm_state["rate_limited"]
                                 and len(storm_state["crashes"]) >= args.wave
                                 and all(r for _, r in storm_state["crashes"])
                                 and waited_full_reset)
                    if truncated:
                        storm_state["rate_limited"] = True
                        storm_state["units"] = list(dict.fromkeys(
                            u for u, _ in storm_state["crashes"]))
                if truncated:
                    # storm fast path: takes priority over arming a new
                    # cooldown — the dispatch loop stops and exits 2.
                    _eprint(f"[fanout_runner] unit {uid}: rate-limit crash "
                            f"storm ({args.wave} quota-signature crash(es) "
                            f"since the last disk advance) — stopping dispatch")
                    _eprint(f"[fanout_runner] {_RATELIMIT_RECIPE}")
                    if quota_mode:
                        _eprint(f"[fanout_runner] quota mode: a full window "
                                f"reset was already waited and rate-limit "
                                f"crashes still recur — verify --quota-calls "
                                f"{args.quota_calls} / --quota-window-s "
                                f"{args.quota_window_s} / "
                                f"--quota-calls-per-unit "
                                f"{args.quota_calls_per_unit} against the "
                                f"gateway's actual quota")
            _terminal_children_rm(child_pid)
        else:
            _hb(t0, args.tier, seq, uid, "ok", _hb_count(1), total)
            _eprint(f"[fanout_runner] unit {uid}: {ack or 'marker-only'} ({detail[:120]})")
            # ok terminal = disk terminal advance → clears the storm window
            with storm_lock:
                storm_state["crashes"].clear()
            _terminal_children_rm(child_pid)
            done_durations.append(elapsed)
            # False-kill self-evidence (design D3): completing after having
            # been stall-killed earlier in this run is what widens the window.
            # Ordered after the terminal bookkeeping so stderr reads
            # "unit ok" and then "window widened".
            _maybe_widen_window(uid)

    def _fill() -> bool:
        """Top up in-flight slots from the queue (slot backfill). Returns True
        when the soft deadline stopped new dispatches. A storm truncation, an
        active cooldown, or a short-of-margin quota window also stop NEW
        dispatches but return False — they are not soft stops; the loop's
        gates own the wait.

        Quota admission gate (quota mode only) sits AFTER the cooldown gate
        and BEFORE the unit pop (the mermaid order in the change design: the
        two gates are orthogonal — `--wave` caps in-flight slots, the quota
        window caps the dispatch RATE; effective concurrency =
        min(wave, free quota margin / K)). Not admissible -> no pop, one
        wait-episode disclosure, and the loop's gates wait: with in-flight
        units the harvest poll (1s) re-enters here, with none the main loop's
        quota gate sleeps in <=1s shards toward the resume ts — never a busy
        spin."""
        nonlocal waves_run, dispatched_since_window
        nonlocal quota_admission_waits, quota_wait_active
        stopped = False
        while len(inflight) < args.wave:
            if _cred_expired():
                break  # credential fast-stop: highest-priority dispatch stop
            if _rate_limited():
                break  # storm fast path: no new dispatch, no cooldown arming
            if deadline is not None and time.monotonic() >= deadline:
                stopped = True
                break
            _maybe_cooldown()
            if time.monotonic() < cooldown_until:
                break  # cooldown: pause new dispatch; in-flight keep harvesting
            if quota_mode and queue:
                # gated on a non-empty queue: with nothing left to dispatch
                # an admission check would disclose (and count) a wait
                # episode for work that does not exist (drain-time artifact)
                admissible, used, resume_ts = _quota_state()
                if not admissible:
                    if not quota_wait_active:
                        quota_admission_waits += 1
                        quota_wait_active = True
                        resume_wall = (datetime.now().astimezone()
                                       + timedelta(seconds=max(0.0,
                                                               resume_ts - time.monotonic())))
                        _eprint(f"[fanout_runner] quota admission wait "
                                f"#{quota_admission_waits}: estimated "
                                f"{used} call(s) spent in the last "
                                f"{args.quota_window_s}s "
                                f"(dispatches x K={args.quota_calls_per_unit}) "
                                f"+ next unit's {args.quota_calls_per_unit} > "
                                f"budget {args.quota_calls} — pausing NEW "
                                f"dispatch until the window slides "
                                f"(~{resume_wall.strftime('%H:%M:%S')}); "
                                f"in-flight units keep running and harvesting "
                                f"(ESTIMATE: real per-unit call counts are "
                                f"gateway-side facts)")
                    break
                quota_wait_active = False
            unit = _next_unit()
            if unit is None:
                break
            # Re-check AFTER the pop, BEFORE the submit (design D1): the
            # truncation flags are set by worker threads when a crash's
            # bookkeeping lands, so the loop-top check can go stale across
            # the pop's marker stats. The popped unit is NOT put back — a
            # truncation terminates the whole run, so it stays disk-marker
            # pending for --resume exactly like its queue-mates behind it.
            if _cred_expired():
                break
            if _rate_limited():
                break
            waves_run += 1
            if quota_mode:
                now = time.monotonic()
                quota_dispatch_times.append(now)
                # Bound the list: entries older than the window can never
                # admit again (the pure helper filters, but the append-only
                # list would otherwise grow for the whole run).
                horizon = args.quota_window_s
                quota_dispatch_times[:] = [t for t in quota_dispatch_times
                                           if now - t <= horizon]
            inflight[pool.submit(_dispatch, unit, waves_run)] = unit
            dispatched_since_window += 1
        return stopped

    def _soft_stop_msg() -> None:
        _eprint(f"[fanout_runner] soft time budget reached; stopping new "
                f"dispatches ({len(queue)} pending stay resumable)")

    def _breaker_observe(wsnap: dict, stuck_pending: list = ()) -> bool:
        """One zero-progress breaker observation (design D7, both points):
        advance the zero-growth window from a fresh disk re-derivation; True =
        tripped (stalled) with units still to dispatch. Growth, or the first
        observation ever, resets the window. The trip arms the one bounded
        pre-breaker backoff (design D3) when it has not been used and the
        time budget still allows a cooldown; only a still-zero-growth backoff
        re-derivation (resolved at the top of the dispatch loop) finally sets
        stalled. `stuck_pending` = disk-pending units the dispatcher will
        NEVER re-queue this run (kill-failed) — they are still "to dispatch"
        from the disk's point of view, so they satisfy the trip condition and
        ride the stalled disclosure, but only the zero-growth window bounds
        how long the run keeps giving the survivor a chance."""
        nonlocal dispatched_since_window, last_window_snap
        nonlocal last_terminal_count, window_left, stalled
        nonlocal backoff_used, backoff_pending, last_stuck_pending
        dispatched_since_window = 0
        last_window_snap = wsnap
        last_stuck_pending = list(stuck_pending)
        terminal_count = (int(wsnap.get("done", 0))
                          + int(wsnap.get("failed", 0))
                          + len(set(failed_written)))
        if (last_terminal_count is not None
                and terminal_count == last_terminal_count):
            window_left -= 1
        else:
            window_left = args.stall_waves
        last_terminal_count = terminal_count
        _write_sidecar(plan_path.parent, args.tier,
                       _sidecar_payload("running", wsnap, list(queue)))
        if window_left <= 0 and (queue or inflight or stuck_pending):
            if (not backoff_used and args.cooldown_s > 0
                    and _cooldown_budget_cap() > 0):
                backoff_used = True
                backoff_pending = True
                # quota_reset=False: the backoff's cooldown keeps the plain
                # --cooldown-s length (zero progress is not necessarily a
                # quota shape — NEVER amplify it to window scale)
                _start_cooldown("pre-breaker backoff", quota_reset=False)
                _eprint("[fanout_runner] zero-progress breaker armed — one "
                        "bounded backoff before failing: cooldown, then a "
                        "full disk re-derivation decides (growth resumes "
                        "dispatch, zero growth exits)")
                return False
            stalled = True
        return stalled

    def _stall_diag(how: str) -> None:
        _eprint(f"[fanout_runner] STALLED ({how}): {args.stall_waves} "
                f"consecutive zero-growth re-derivation(s) of the disk "
                f"done+failed terminal count with units still to dispatch — "
                f"stopping dispatch (pending units remain resumable). Note: a "
                f"stall-killed unit does NOT raise the disk count (no marker) "
                f"— a unit that dies on every attempt surfaces here. Recipe: "
                f"stop re-dispatching this command; diagnose via "
                f"`resume_state.py --target <target> --check` and cross-check "
                f"each unit's marker existence against stalled_pending[] below "
                f"(marker-unwritable / identity drift / deterministic stall).")

    try:
        stopped = _fill()
        if stopped:
            _soft_stop_msg()
        # Slot-backfill rounds: harvest terminal futures (FIRST_COMPLETED, 1s
        # poll granularity) and backfill each freed slot immediately — a hung
        # unit occupies only its own slot, NEVER the whole run. When queue AND
        # in-flight both drain, the drain re-list (breaker observation point
        # b) decides: more pending on disk → one more in-run round; nothing →
        # clean exit.
        while not (stalled or stopped or _rate_limited() or _cred_expired()):
            # Quota window-reset completion (quota mode): the armed cooldown
            # whose endpoint includes the FULL window reset has now been
            # actually waited out — stamp the completion ts. The crash-storm
            # truncation counts only rate-limit crashes at/after it (等满窗口
            # 才截断); a budget-truncated reset never arms this (see
            # _start_cooldown's reset_full).
            if (quota_reset_pending_ts is not None
                    and time.monotonic() >= quota_reset_pending_ts):
                quota_window_completed_ts = quota_reset_pending_ts
                quota_reset_pending_ts = None
                _eprint("[fanout_runner] quota window reset fully waited — "
                        "rate-limit crashes from here on are truncation-"
                        "eligible (the window no longer explains them)")
            # Backoff resolution (design D3): the armed pre-breaker backoff's
            # deciding re-derivation, once its cooldown has expired and
            # nothing is in flight. Disk growth disarms the breaker; zero
            # growth exits stalled (at most one backoff per call).
            if (backoff_pending and not inflight
                    and time.monotonic() >= cooldown_until):
                backoff_pending = False
                wsnap = _snapshot()
                grown = (int(wsnap.get("done", 0)) + int(wsnap.get("failed", 0))
                         + len(set(failed_written))) > last_terminal_count
                if grown:
                    window_left = args.stall_waves
                    _eprint("[fanout_runner] backoff re-derivation shows disk "
                            "progress — breaker disarmed, resuming dispatch")
                else:
                    last_window_snap = wsnap
                    stalled = True
                    _stall_diag("pre-breaker backoff re-derivation is still "
                                "zero-growth")
                    break
            # Cooldown gate: with nothing in flight, idle-wait the cooldown
            # out (1s chunks) — an intentional pause must not burn breaker
            # observations or re-list subprocesses. The DRAINED state (queue
            # empty too — the pre-breaker backoff arms exactly at a drain
            # point) MUST sleep as well: requiring a non-empty queue here
            # used to spin the loop with ZERO sleep for the whole cooldown
            # (default 300s of one core). With in-flight units the harvest
            # loop below keeps running (cooldown only pauses NEW dispatch,
            # via _fill).
            if time.monotonic() < cooldown_until and not inflight:
                time.sleep(min(1.0, max(0.001,
                                        cooldown_until - time.monotonic())))
                continue
            # Quota gate (quota mode, nothing in flight): idle-wait the
            # window out in <=1s shards until admission re-opens — same
            # intentional-pause discipline as the cooldown gate above (NEVER
            # a busy spin, NEVER a breaker observation, NEVER a re-list
            # subprocess). The wait is bounded by the soft deadline: past it,
            # stop and surface the existing partial exit. With in-flight
            # units the harvest loop's 1s poll keeps both harvesting and
            # re-entering _fill (whose quota gate re-checks admission).
            # Breaker isolation (design D2): BOTH breaker observation anchors
            # key on NEW dispatches — point (a) fires only after
            # `dispatched_since_window >= window_k` (increments at spawn
            # only), and this gate `continue`s past the point-(b) drain
            # re-list. Zero dispatches while quota-waiting therefore means
            # zero observations: an admission pause can never be misread as
            # zero PROGRESS.
            if quota_mode and queue and not inflight:
                admissible, _used, resume_ts = _quota_state()
                if not admissible:
                    if deadline is not None and time.monotonic() >= deadline:
                        stopped = True
                        _soft_stop_msg()
                        break
                    delay = resume_ts - time.monotonic()
                    # delay <= ~0 (never-admissible window, K > N): sleep a
                    # full chunk — re-checking sooner cannot change the
                    # verdict, and polling fast would be a busy spin.
                    time.sleep(min(1.0, delay) if delay > 0.05 else 1.0)
                    continue
            while inflight:
                ready, _ = wait(list(inflight), timeout=1.0,
                                return_when=FIRST_COMPLETED)
                for fut in ready:
                    unit = inflight.pop(fut)
                    try:
                        fut.result()
                    except SystemExit:
                        raise
                    except Exception as e:
                        _eprint(f"warn: unit {unit.get(id_field, '?')} dispatch "
                                f"thread error: {e}")
                if stalled:
                    break
                if _fill():
                    stopped = True
                    _soft_stop_msg()
                    break
                elif dispatched_since_window >= window_k:
                    # Observation point (a): K = --stall-waves x --wave units
                    # dispatched since the last check → re-derive the disk
                    # terminal count once (markers = only truth). Anchored on
                    # NEW dispatches BY DESIGN: a quota-mode admission wait
                    # dispatches nothing, so it cannot burn observations or
                    # trip the breaker (zero dispatch != zero progress).
                    if _breaker_observe(_snapshot()):
                        _stall_diag("dispatch window")
                        break
                # Periodic in-flight heartbeat (disclosure, --hb-interval-s):
                # unit id + seconds since its child's last output.
                now = time.monotonic()
                if now >= next_hb:
                    next_hb = now + args.hb_interval_s
                    with sinks_lock:
                        live = list(sinks.items())
                    for uid, (o, e, w) in live:
                        # Same source as the stall criterion (_run_unit): the
                        # NEWER of the two stamps, so the disclosed idle never
                        # disagrees with the value that would trigger a kill —
                        # and `w` is that same attempt's window, so the
                        # disclosed idle is readable against it.
                        idle = max(0, int(now - max(o["ts"], e["ts"])))
                        _hb_inflight(t0, args.tier, len(live), uid, idle,
                                     _hb_count(), total, w)
            if stalled or stopped or _rate_limited() or _cred_expired():
                break
            if backoff_pending:
                # a backoff is armed: its deciding re-derivation at the top of
                # the loop owns the next decision — never re-list/observe
                # (point b) while it is pending.
                continue
            # Observation point (b) — drain re-list (design D7): queue empty
            # and in-flight zero. Re-derive pending from disk; units still
            # pending get one more zero-growth-bounded attempt round in THIS
            # run (the lone-poison-unit tail "kill → re-dispatch → kill" is
            # truncated in-run instead of bouncing partial:true to the
            # orchestrator forever). A post-cooldown pass can reach this point
            # with a non-empty in-memory queue (crash requeues waiting out the
            # cooldown) — de-duplicate against it so a unit is never queued
            # twice.
            wsnap = _snapshot()
            pending_now = wsnap.get("pending") or []
            if not pending_now:
                break  # clean drain: nothing left to dispatch
            queued_ids = {u.get(id_field) for u in queue}
            # kill-failed units are disk-pending but their survivor owns them
            # — NEVER re-queued; they ride the breaker as stuck pending so the
            # run stays bounded and the disclosure names them
            stuck = [u for u in pending_now if u.get(id_field) in kill_failed]
            queue.extend(u for u in pending_now
                         if u.get(id_field) not in queued_ids
                         and u.get(id_field) not in kill_failed)
            if _breaker_observe(wsnap, stuck):
                _stall_diag("queue drained but the disk re-list still shows "
                            "pending units")
                break
            stopped = _fill()
            if stopped:
                _soft_stop_msg()
        pool.shutdown(wait=True)

        if stalled:
            snap = last_window_snap or snap
            # queue + kill-failed stuck units (disk-pending, never queueable)
            pending_units = list(queue) + list(last_stuck_pending)
        else:
            snap = _snapshot()
            pending_units = snap.get("pending") or []
            if not pending_units and queue:
                pending_units = list(queue)
            if waves_run == 0 and skipped_terminal and not queue:
                # every queued unit was lazy-skipped as already-terminal on
                # disk; the frozen test listing cannot reflect that — disk
                # markers are the truth, nothing is pending
                pending_units = []
        done_now = int(snap.get("done", done0))
        # Two views of the SAME fact (markers written this run): the disk
        # re-list already counts them, and so does the in-run write ledger —
        # take the MAX, never the sum (a full-failure re-list run used to
        # report every failure twice; --retry-failed and the report gap
        # disclosure consume this number).
        failed_now = max(int(snap.get("failed", failed0)),
                         failed0 + len(set(failed_written)))
        partial = bool(pending_units)
        # Cost visibility (design D4) computed ONCE and shared by the terminal
        # sidecar write and the stdout summary below, so the two agree by
        # construction rather than by rounding. Same single-source story for
        # the quota disclosure block.
        cost = _cost_payload()
        quota_body = _quota_body()
        # Terminal sidecar state (counts consistent with the stdout summary below
        # by construction — both derive from {snap, failed_written}).
        _write_sidecar(plan_path.parent, args.tier,
                       _sidecar_payload(
                           "exited-partial" if partial else "exited-clean",
                           snap, pending_units, cost, quota_body))
        result = {
            "runner": "fanout_runner",
            "tier": args.tier,
            "repo": repo_str,
            "host": host,
            "total": total,
            "done": done_now,
            "failed": failed_now,
            "pending": len(pending_units),
            "wave": args.wave,
            "waves_run": waves_run,
            "partial": partial,
            "stall_killed": stall_killed,
            "stalled": stalled,
            # Cost visibility (design D4) — literally the same dict the
            # terminal sidecar was written from, so a second-terminal watcher
            # and the exit summary agree by construction.
            **cost,
            **quota_body,
        }
        if stalled:
            # per-stuck-unit diagnosis: id + ACTUAL on-disk marker existence (the
            # pending derivation says not-terminal; the disk may disagree — that
            # gap IS the drift being surfaced).
            idf = tier["id_field"]
            result["stalled_pending"] = [
                {"id": u.get(idf),
                 "done_marker_exists": Path(u["done_marker"]).is_file()
                 if u.get("done_marker") else None,
                 "failed_marker_exists": Path(u["failed_marker"]).is_file()
                 if u.get("failed_marker") else None}
                for u in pending_units]
        if overflow_units:
            # P2 diagnosis disclosure (additive; absent when no crash matched
            # an overflow signature — stdout stays byte-identical otherwise).
            # De-duplicated in dispatch order: a re-dispatched unit crashes
            # once per attempt, but the summary names the UNIT once.
            result["context_overflow"] = list(dict.fromkeys(overflow_units))
        if kill_failed:
            # kill-failure disclosure (additive; absent when every tree-kill
            # succeeded — same optional-key shape as runtime_p50_s): the
            # survivor owns each named unit until a later --resume or
            # --kill-stale closes it out
            result["kill_failed"] = list(dict.fromkeys(kill_failed))
        # Fast-fail storm resilience disclosures (additive keys; existing
        # fields zero add/remove). rate_limited_crashes is present only when
        # the truncation fired (same conditional-disclosure shape as
        # context_overflow).
        rate_limited_trig = _rate_limited()
        result["cooldowns"] = cooldowns
        result["retried_failed"] = retried_failed
        result["rate_limited"] = rate_limited_trig
        if rate_limited_trig:
            with storm_lock:
                result["rate_limited_crashes"] = list(storm_state["units"])
        # Credential-expiry fast-stop disclosure (additive keys; absent when
        # no signature matched — same conditional shape as rate_limited).
        cred_expired_trig = _cred_expired()
        if cred_expired_trig:
            result["credential_expired"] = True
            with storm_lock:
                result["credential_expired_units"] = list(cred_state["units"])
        _eprint(f"[fanout_runner] done ({args.tier}): {result['done']}/{total} done, "
                f"{result['failed']} failed, {result['pending']} pending, partial={partial}"
                + (", STALLED" if stalled else "")
                + (", RATE-LIMIT STORM" if rate_limited_trig else "")
                + (", CRED-EXPIRED" if cred_expired_trig else ""))
        print(json.dumps(result, ensure_ascii=False))
        return 2 if (stalled or rate_limited_trig or cred_expired_trig) else 0
    finally:
        pool.shutdown(wait=True)
        # Exit-path cleanup of STILL-REGISTERED children, BEFORE deregistering
        # them. Units run in their own session (start_new_session), so an
        # interrupt (Ctrl-C) no longer reaches them through the tty's process
        # group; the normal path has already converged the pool
        # (shutdown(wait=True)), but an interrupt leaves live children behind.
        # Killing them here keeps them from becoming UNTRACKABLE orphans —
        # clearing children_now and deleting the liveness file is exactly what
        # would hide them from a later `--kill-stale`. This call never hits the
        # dispatcher itself (see _kill_tree). A hard kill (SIGKILL) skips this
        # finally entirely: the liveness file stays on disk and `--kill-stale`
        # still detects the residue — that path is intentionally unchanged.
        with children_lock:
            leftover = list(children_now)
        for c in leftover:
            try:
                if not _kill_tree(c["pid"]):
                    _eprint(f"warn: exit cleanup could not tree-kill child "
                            f"pid {c['pid']} (unit {c.get('unit', '?')})")
            except Exception as e:  # never let cleanup break the exit path
                _eprint(f"warn: exit cleanup error for pid {c['pid']}: {e}")
        # Liveness deregistration on ANY exit path (incl. partial early-exit,
        # list-CLI sys.exit, unexpected exception). Hard-kill leaves the file
        # behind — a legal residual state disambiguated by --kill-stale.
        with children_lock:
            children_now.clear()
        _update_liveness_children(liveness_path, liveness_body, [])
        try:
            liveness_path.unlink(missing_ok=True)
        except OSError as e:
            _eprint(f"warn: cannot remove liveness file {liveness_path.name}: {e}")


if __name__ == "__main__":
    sys.exit(main())
