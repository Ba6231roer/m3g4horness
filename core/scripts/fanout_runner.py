#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
fanout_runner — deterministic tier-aware wave dispatcher for /mgh-init fan-out
(tiers: scout | t1 | t3).

Replaces the per-wave orchestrator LLM turn with a pure-code loop: consume the
pending work-list from the tier's enumeration script (`--materialize` mode)
stdout, build each subagent's task message from a FIXED template + verbatim
field substitution, spawn host-CLI subprocesses concurrently in waves, parse
bounded acks, and re-derive pending from disk markers after each wave. Zero LLM
turns inside the dispatch loop; every path field is passed verbatim from the
enumerator stdout (path spelling failures become impossible by construction).

Tier mapping (single point, TIERS below): each tier names its enumeration
script + forwarded flags, task-message template, placeholder set, anchor-tree
path fields, fanout agent name, and marker `tier` value. The wave loop, ack
state machine, timeouts, sidecar, and audit copies are shared — no per-tier
branches in the loop body.

  scout: list_scout_batches.py --scout-plan/--checkpoints/--materialize
         template fanout/scout-task.md; agent init-scout-fanout
  t1:    list_clusters.py --clusters/--candidates/--checkpoints/--materialize
         template fanout/t1-task.md; agent init-induct-fanout
         (list_clusters exit 2 = scout-incomplete-gate → passed through as
         exit 2 with its stderr recipe; NEVER swallowed into a crash loop)
  t3:    list_rule_jobs.py --inventory/--format/--rules-dir/--checkpoints/
         --target/--materialize
         template fanout/t3-task.md; agent init-rulewriter-fanout
         (placeholder set uses rule_path, no checkpoint_path/slice_dir)

Task message template: `<mgh-core>/prompts/fragments/fanout/<tier>-task.md`
(placeholder set per tier, documented below). An audit copy of each filled
message is written to `<inputs-dir>/<unit>.task.md` (small; `--purge-audit`
lists them).

Host spawn mapping (spike-verified, see change design D3):
  opencode: `opencode run --agent <tier-agent> "<task>"` (cwd=repo)
            — the fanout agents are `mode: primary` clones of the stage
              agents (opencode `run` refuses `mode: subagent` agents and
              silently falls back to the default agent).
  claude:   `claude -p "<task>" --agents <inline JSON> --allowedTools ...`
            (cwd=repo, stdin redirected from /dev/null)
Host detection: `--host` explicit > opencode in PATH > claude in PATH
(shutil.which); neither present → exit 2 + fallback recipe (the orchestrator
falls back to the existing per-wave manual dispatch, behavior unchanged).

State machine (disk markers are the ONLY truth source): `ok`/`oversize` ack or
`.done` marker → done; `failed` ack → this script writes the `.failed` marker
(body {unit,reason,tier}; terminal, not retried, does not block the wave);
crash/timeout with no ack and no marker → unit stays pending → `--resume`
re-dispatches it (crash != confirmed failure). Unparsable stdout → trust the
disk markers only.

Zero runtime deps (Python >=3.10 stdlib: argparse/concurrent.futures/datetime/
json/os/pathlib/shutil/signal/subprocess/sys/tempfile/threading/time).

CLI contract (`--help` is the contract surface, R5.1):
  py fanout_runner.py --tier scout|t1|t3 [tier flags] [options]

  scout tier (default; existing call shape unchanged):
    --scout-plan <scout_plan.json> --checkpoints <scout-dir>
    --inputs-dir <inputs-dir>
  t1 tier:
    --clusters <clusters.json> --candidates <controls_candidates.json>
    --checkpoints <t1-dir> --inputs-dir <inputs-dir>
  t3 tier:
    --inventory <controls_inventory.json> --format opencode|claude
    --rules-dir <rules-dir> --target <target> --checkpoints <t3-dir>
    --inputs-dir <inputs-dir>

  --tier            scout|t1|t3 (default scout). Selects the enumeration
                   script, template, placeholder set, and fanout agent.
  --checkpoints     tier checkpoint dir (markers live here; forwarded).
  --inputs-dir      per-unit input dir (forwarded as --materialize; audit
                   copies `<unit>.task.md` land here too).
  --host            claude|opencode explicit; default: opencode in PATH, else
                   claude in PATH, else exit 2 + recipe.
  --wave            concurrent subprocesses per wave (default 5).
  --time-budget-ms  soft deadline: stop starting new waves, drain in-flight,
                    exit 0 with partial:true (re-dispatch the same command).
                    RECOMMENDED = host per-call timeout x 0.8 (e.g. host
                    900000ms -> 720000; claude host caps Bash at 600000ms ->
                    480000). MUST stay BELOW the host per-call timeout so the
                    soft deadline always fires first (a host hard-kill loses
                    in-flight waves and degenerates into a kill/re-dispatch
                    loop).
  --call-timeout-s  per-subprocess timeout (default 7200s, calibrated for
                    slow intranet LLM endpoints: one unit = one full LLM
                    subagent run at minutes-level, ~4x headroom; better-slow-
                    than-killed — a killed unit leaves no marker, stays
                    pending, and re-dispatch wastes a whole run). Timeout ->
                    kill -> no ack -> unit stays pending.

  TIMEOUT INVARIANT (inner < outer, >=20% headroom per level):
    call-timeout-s x drain headroom < time-budget-ms < host per-call timeout
  (drain = wait for the slowest in-flight subprocess to finish, not an
  immediate cut; the levels above are defaults/recommendations — the
  INVARIANT is the contract, the numbers are calibration). Applies to all
  three tiers identically (a t1/t3 unit = one full LLM subagent run, same
  calibration as scout).
  --resume          re-derive pending from disk markers (same entry point as a
                    fresh call; kept for call-shape parity with the shell).
  --pending-file    TEST HOOK: consume the tier listing from a file instead of
                    invoking the enumerator (never spawns; ignores --host).
  --kill-stale      orphan-tree cleanup: inspect the liveness file(s)
                    `fanout_runner.<tier>.pid` and kill what it records:
                    form (1) runner PID alive AND cmdline matches
                    `fanout_runner.py` -> kill the whole tree (Windows
                    `taskkill /pid <pid> /T /F`; POSIX process-group SIGTERM);
                    form (2) runner PID dead/mismatched BUT a `children[]` PID
                    is alive AND its cmdline is the host CLI (`opencode`/
                    `claude`) -> kill each such child tree. Covers "the runner
                    was hard-killed along with the orchestrator but its host-CLI
                    children keep burning tokens". Mismatched/dead PIDs are
                    NEVER killed (PID-reuse guard: the cmdline must match —
                    a reused PID is only a stale record, the liveness file is
                    just removed). DESTRUCTIVE: a real kill REQUIRES a prior
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
children[] = the in-flight host-CLI child PIDs of the current wave ({pid,
unit, tier}, refreshed after each wave's spawns and cleared at wave end via
subprocess.Popen pids) — and deletes it on ANY exit path (try/finally). It is
an ORPHAN SIGNAL, not a lock: a hard-killed runner leaves the file behind and
`--kill-stale` disambiguates via PID liveness + cmdline matching. Not read by
resume_state for progress (disk markers remain the only truth source).

stderr heartbeat: the dispatch loop prints one line per key node — per-unit
spawn / per-unit terminal status (ok|failed|timeout|crash) / wave end — shaped
`[fanout_runner <tier>] +HH:MM:SS wave=<k> unit=<id> <event> done=<d>/<total>`
(elapsed = time.monotonic() relative to runner start). Host TUIs (opencode
Bash tool renders the merged stdout+stderr sliding tail while running; claude
includes stderr in the Bash result) surface these lines live. stdout contract
unchanged: still exactly one JSON summary line at the end.

stdout (structured JSON summary; stderr = diagnostics/progress only, R5.3b):
  {"runner": "fanout_runner", "tier": "scout|t1|t3", "repo": "...",
   "host": "claude|opencode|test", "total": N, "done": M, "failed": F,
   "pending": P, "wave": W, "waves_run": K, "partial": bool,
   "stalled": bool,
   "stalled_pending": [{"id", "done_marker_exists", "failed_marker_exists"}]
                     (only when stalled:true),
   "audit_purged": [names] (with --purge-audit),
   "kill_stale": {killed, removed, none} (with --kill-stale)}

Zero-progress convergence circuit breaker (--stall-waves, default 2): after each
fully-joined wave, done+failed is snapshotted; N consecutive equal snapshots with
pending non-empty → stop dispatching, exit 2, stdout stalled:true +
stalled_pending[] (per stuck unit: id + its actual .done/.failed marker existence
on disk), stderr diagnosis recipe (stop re-dispatching; diagnose via
`resume_state.py --check`; cross-check each unit's marker existence). A legal slow
wave (in-flight units call-timeout with no ack) does NOT trip: the next wave that
advances progress resets the window. partial early-exit / clean completion paths
are byte-identical to pre-breaker behavior (the breaker only fires on
"pending perpetually non-empty AND progress perpetually zero").

Progress sidecar (human-facing run-state disclosure, written each wave + on
every exit): <init-dir>/fanout_progress.<tier>.json — the init-dir that holds
the tier's plan artifact (scout_plan.json / clusters.json /
controls_inventory.json) — holds {ts, host, tier, total, done, failed,
pending, wave, waves_run, wave_done_avg_s, eta_batches, state} with state in
{running, exited-partial, exited-clean}. It is FOR HUMANS: watch it from a
second terminal (e.g. `Get-Content -Wait`); the orchestrator and any agent
NEVER read it (not a truth source, not a contract artifact — resume_state.py
and init_manifest.json neither read nor validate it; a stale copy — including
a pre-rename `fanout_progress.json` — is harmless). Counts derive from the
same snapshot as the stdout summary (single test asserts they agree). Write
failures warn on stderr and never break the run.

Exit codes (R5.3b): 0 ok (incl. partial:true) · 1 misuse of inputs
(tier artifact/inputs-dir missing, template unreadable, unparsable pending) ·
2 CLI misuse / host CLI unavailable / tier gate refusal (t1
scout-incomplete-gate passed through with the enumerator's stderr recipe,
fail-loud) / zero-progress stall (convergence circuit breaker,
`--stall-waves` consecutive waves with no done+failed progress and pending
non-empty; stdout carries stalled:true + stalled_pending[]). Idempotent; no
TTY; reads/writes only inside the repo-anchored tree (every path field is
resolve()-anchored against `repo` before spawn; out-of-tree → that unit is
marked failed with reason=path-drift and NEVER spawned).
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Self-locate this script's dir so sibling scripts / the prompts tree resolve
# under any cwd / host-agent invocation (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_WAVE = 5
# Calibrated for slow intranet LLM endpoints (one unit = one full LLM subagent
# run, observed minutes-level per unit): ~4x headroom over the smoke-test
# worst case. Better-slow-than-killed: a killed unit leaves NO marker, so it
# stays pending and re-dispatching it wastes an entire run.
DEFAULT_CALL_TIMEOUT_S = 7200
# Convergence-circuit-breaker window (default 2 waves, --stall-waves N): after
# each fully-joined wave, snapshot done+failed; N consecutive equal snapshots
# with pending still non-empty = zero-progress loop (pending 判定与 marker 写入
# 任何一侧身份/权限漂移都表现为「每波全量重派、进度恒零」) → stop dispatching,
# exit 2 + stalled diagnosis. 2 not 1: a legal slow wave (in-flight units
# call-timeout with no ack; the NEXT wave advances) must not trip; a真卡死
# unit's pending set is wave-invariant, so 2 waves provably catches it.
DEFAULT_STALL_WAVES = 2

# ---------------------------------------------------------------------------
# Tier mapping (single point of tier variation, design D1/D2). The wave loop,
# ack state machine, timeouts, sidecar, and audit copies read from this table;
# no per-tier branches elsewhere.
# ---------------------------------------------------------------------------
# Placeholders are pure str.replace, never format()-derived: what the template
# says is what the subagent gets (D2). Common placeholders every tier fills:
#  <id-field> (unit identity: batch_id/cluster_id/category per tier),
#  input_path, done_marker, failed_marker, repo. scout/t1 add
#  checkpoint_path, slice_dir, chunk_sources_abs, codegraph; t3 adds
#  rule_path, category, format.
_SCOUT_PATH_FIELDS = ("input_path", "checkpoint_path", "done_marker",
                      "failed_marker", "slice_dir")
_T3_PATH_FIELDS = ("input_path", "rule_path", "done_marker", "failed_marker")

TIERS = {
    "scout": {
        "list_script": "list_scout_batches.py",
        # forwarded flags appended after the tier artifacts (fn(args) -> [str])
        "list_args": lambda a: ["--scout-plan", a.scout_plan,
                                "--checkpoints", a.checkpoints,
                                "--materialize", a.inputs_dir],
        "required_args": ("scout_plan", "checkpoints", "inputs_dir"),
        # artifact whose dir = init-dir (sidecar home + run_config neighbor)
        "plan_arg": "scout_plan",
        "template_rel": Path("prompts") / "fragments" / "fanout" / "scout-task.md",
        "path_fields": _SCOUT_PATH_FIELDS,
        "placeholders": _SCOUT_PATH_FIELDS + ("batch_id", "chunk_sources_abs",
                                              "repo", "codegraph"),
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
                                "--materialize", a.inputs_dir],
        "required_args": ("clusters", "candidates", "checkpoints", "inputs_dir"),
        "plan_arg": "clusters",
        "template_rel": Path("prompts") / "fragments" / "fanout" / "t1-task.md",
        "path_fields": _SCOUT_PATH_FIELDS,
        "placeholders": _SCOUT_PATH_FIELDS + ("cluster_id", "chunk_sources_abs",
                                              "repo", "codegraph"),
        "id_field": "cluster_id",
        "agent": "init-induct-fanout",
        "agent_desc": "mgh-init T1 per-cluster inductor (fanout dispatch, primary)",
        "agent_tools": "Read Glob Grep Bash Write",
        "uses_codegraph": True,
        "uses_chunk_sources": True,
    },
    "t3": {
        "list_script": "list_rule_jobs.py",
        "list_args": lambda a: ["--inventory", a.inventory,
                                "--format", a.fmt,
                                "--rules-dir", a.rules_dir,
                                "--target", a.target,
                                "--checkpoints", a.checkpoints,
                                "--materialize", a.inputs_dir],
        "required_args": ("inventory", "fmt", "rules_dir", "target",
                          "checkpoints", "inputs_dir"),
        "plan_arg": "inventory",
        "template_rel": Path("prompts") / "fragments" / "fanout" / "t3-task.md",
        "path_fields": _T3_PATH_FIELDS,
        "placeholders": _T3_PATH_FIELDS + ("category", "format", "repo"),
        "id_field": "category",
        "agent": "init-rulewriter-fanout",
        "agent_desc": "mgh-init T3 per-category rule writer (fanout dispatch, primary)",
        # rulewriter edits rule/detail files → needs Edit too
        "agent_tools": "Read Glob Grep Bash Write Edit",
        "uses_codegraph": False,
        "uses_chunk_sources": False,
    },
}


def _eprint(*a):
    print(*a, file=sys.stderr)


def _safe_name(unit_id: str) -> str:
    """Filesystem-safe audit filename (mirrors list_scout_batches._safe_name)."""
    return unit_id.replace("/", "_").replace("\\", "_").replace(":", "_")


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


def _codegraph_signal(plan_path: Path) -> str:
    """Derive `codegraph=on|off` from run_config.json (no_codegraph flag),
    sibling of the tier plan artifact. Missing/unparseable → off (legacy)."""
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


def _fill_template(tier: dict, template: str, unit: dict, repo_str: str,
                   codegraph: str) -> str:
    """Pure verbatim substitution; asserts no residual `{{` after filling."""
    values = {k: unit.get(k, "") for k in tier["placeholders"]
              if k not in ("repo", "codegraph", "chunk_sources_abs", "format")}
    if tier["uses_chunk_sources"]:
        values["chunk_sources_abs"] = _chunk_sources_abs()
    values["repo"] = repo_str
    values["codegraph"] = codegraph
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


def _write_failed_marker(tier: dict, unit: dict, reason: str) -> None:
    """Write the terminal `.failed` marker (same body shape the orchestrator
    writes on a failed ack: {unit, reason, tier}; `tier` = current --tier
    value). Idempotent."""
    fm = unit.get("failed_marker")
    if not fm:
        return
    p = Path(fm)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(json.dumps({"unit": unit.get(tier["id_field"]),
                                 "reason": reason, "tier": tier_name(tier)},
                                ensure_ascii=False), encoding="utf-8")


def tier_name(tier: dict) -> str:
    """Reverse-lookup the tier key for marker bodies (TIERS values carry no
    back-pointer; identity lookup keeps a single source of truth)."""
    for name, t in TIERS.items():
        if t is tier:
            return name
    return "scout"


def _spawn_cmd(tier: dict, host: str) -> list[str]:
    """Host-CLI argv for one unit; the task message travels via STDIN, never
    argv (npm `.cmd` shims on Windows truncate multi-line argv at the first
    newline — observed as the subagent receiving only `<!--`). Both hosts read
    the piped message when no positional message is given (opencode `run`
    Bun.stdin.text(); claude `-p` stdin mode; spike-verified)."""
    if host == "opencode":
        return [_host_exe("opencode"), "run", "--agent", tier["agent"]]
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


def _run_unit(host: str, cmd: list[str], task: str, cwd: Path,
              call_timeout_s: int) -> tuple[str, str | None, str, int | None]:
    """Spawn one subprocess with the task message piped to stdin; returns
    (status, ack, detail, child_pid).

    status ∈ spawn-ok | spawn-error | timeout | crash — ack is the parsed
    bounded ack (None if unparsable). child_pid = the OS PID of the spawned
    host CLI (for the liveness `children[]` registry; None when spawn failed).
    Popen + communicate(timeout=) is the exact equivalent of the former
    subprocess.run(timeout=) capture semantics, plus the PID. On timeout the
    child is killed (run() does the same internally) and reaped. spawn/
    timeout/crash produce no marker here; the caller re-derives truth from
    disk."""
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=str(cwd), text=True,
            encoding="utf-8", errors="replace")
    except OSError as e:
        return "spawn-error", None, f"spawn failed: {e}", None
    try:
        out, err = proc.communicate(input=task, timeout=call_timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            out, err = proc.communicate(timeout=30)
        except (subprocess.TimeoutExpired, ValueError):
            out, err = "", ""
        return ("timeout", None,
                "per-call timeout exceeded (killed; no ack)", proc.pid)
    ack = _parse_ack(out)
    if proc.returncode != 0 and ack is None:
        return ("crash", None,
                f"exit={proc.returncode}; stderr tail: {(err or '')[-300:]}",
                proc.pid)
    return ("spawn-ok", ack,
            out.strip().splitlines()[-1] if out.strip() else "", proc.pid)


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
        + tier["list_args"](args)
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
    """--host explicit > opencode in PATH > claude in PATH; else exit 2 + recipe."""
    if explicit:
        if explicit not in ("claude", "opencode"):
            _eprint(f"error: --host must be claude|opencode (got {explicit!r})")
            sys.exit(2)
        if shutil.which(explicit) is None:
            _eprint(f"error: --host {explicit} not found in PATH")
            sys.exit(2)
        return explicit
    if shutil.which("opencode"):
        return "opencode"
    if shutil.which("claude"):
        return "claude"
    _eprint("error: no host CLI found (neither `opencode` nor `claude` in PATH).\n"
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


def _write_liveness(init_dir: Path, tier: str, host: str) -> Path:
    """Atomically write the liveness file `<init-dir>/fanout_runner.<tier>.pid`
    (orphan signal, NOT a lock — a same-run-dir second runner is a user's
    explicit action). Body {pid, started_ts, tier, host, cmdline, children[]};
    children[] starts empty and is refreshed per wave by
    `_update_liveness_children`. Atomic: tempfile in the same dir + os.replace
    (same shape as _write_sidecar). Write failure is a stderr warning only —
    it must never break the dispatch loop."""
    target = init_dir / f"fanout_runner.{tier}.pid"
    body = {
        "pid": os.getpid(),
        "started_ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tier": tier,
        "host": host,
        "cmdline": list(sys.argv),
        "children": [],
    }
    _atomic_write_json(target, body)
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
    """Atomically refresh `children[]` in the liveness file after a wave's
    spawns (each entry {pid, unit, tier}); cleared by writing [] at wave end.
    Failure is a stderr warning only (non-fatal by the same contract as the
    initial write)."""
    body["children"] = children
    _atomic_write_json(liveness_path, body)


def _hb(t0: float, tier: str, wave_no: int, uid: str, event: str,
        done: int, total: int) -> None:
    """One stderr heartbeat line at a dispatch-loop key node (unit spawn /
    unit terminal status / wave end). opencode's Bash tool renders the merged
    stdout+stderr sliding tail while running -> these lines are the live TUI
    progress; stdout's single-JSON-line contract is untouched."""
    el = max(0, int(time.monotonic() - t0))
    hh, rem = divmod(el, 3600)
    mm, ss = divmod(rem, 60)
    _eprint(f"[fanout_runner {tier}] +{hh:02d}:{mm:02d}:{ss:02d} "
            f"wave={wave_no} unit={uid} {event} done={done}/{total}")


# Host-CLI cmdline markers for the PID-reuse guard: a child PID is only killed
# when its cmdline actually is the host CLI (opencode/claude); a runner PID
# only when it still names fanout_runner.py.
_RUNNER_MARK = "fanout_runner"
_HOST_CLIS = ("opencode", "claude")


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


def _pid_cmdline(pid: int) -> str:
    """Best-effort full cmdline of a PID ("" on any failure / unsupported
    platform). Windows: `wmic process where processid=<pid> get commandline`
    (tasklist carries only the image name — not enough to distinguish the
    runner from another python process); POSIX: /proc/<pid>/cmdline (NUL-
    separated)."""
    if os.name == "nt":
        try:
            r = subprocess.run(
                ["wmic", "process", "where", f"processid={pid}", "get",
                 "commandline", "/value"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return ""
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


def _kill_tree(pid: int) -> bool:
    """Kill a whole process tree. Windows: `taskkill /pid <pid> /T /F` (/T is
    the only reliable whole-tree kill — the host CLIs are npm `.cmd` shim
    chains). POSIX: kill the process group; the runner's dispatch spawns are
    NOT started in a new session (start_new_session would change existing
    spawn behavior), so children share the runner's process group — this kill
    therefore also hits the (already dying) runner side of the tree; orphaned
    grandchildren are reaped by the host process group (disclosed limit)."""
    if os.name == "nt":
        try:
            r = subprocess.run(["taskkill", "/pid", str(pid), "/T", "/F"],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=60)
            return r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        return True
    except (OSError, ProcessLookupError):
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except OSError:
            return False


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
    live_children:[{pid,unit,tier}]}. Unparsable/missing -> None (the caller
    then only removes the residual file, never kills)."""
    try:
        body = json.loads(pid_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    pid = body.get("pid")
    runner_alive = isinstance(pid, int) and _pid_alive(pid)
    runner_matches = False
    if runner_alive:
        cl = _pid_cmdline(pid)
        runner_matches = _RUNNER_MARK in cl
    live_children = []
    for ch in body.get("children") or []:
        if not isinstance(ch, dict):
            continue
        cpid = ch.get("pid")
        if isinstance(cpid, int) and _pid_alive(cpid):
            live_children.append({"pid": cpid, "unit": ch.get("unit"),
                                  "tier": ch.get("tier"),
                                  "cl": _pid_cmdline(cpid)})
    return {"body": body, "runner_alive": runner_alive,
            "runner_matches": runner_matches, "live_children": live_children}


def _classify_targets(inspected: list) -> list:
    """PID-reuse double guard: return only {pid, tier, kind} entries that may
    be killed — kind=runner iff the runner PID is alive AND its cmdline names
    fanout_runner.py; kind=child iff the runner is dead/mismatched AND the
    child PID is alive AND its cmdline is the host CLI. Everything else = a
    stale record: the liveness file is removed, nothing is killed."""
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
            cl = (ch.get("cl") or "").replace("\\", "/").lower()
            base = cl.rsplit("/", 1)[-1].split(".exe")[0] if cl else ""
            if any(base == h or base.startswith(h + " ") or cl.find(h) >= 0
                   for h in _HOST_CLIS):
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
    pid_files = _stale_liveness_files(init_dirs)
    inspected = [i for i in (_inspect_liveness(p) for p in pid_files)
                 if i is not None]
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
        description="deterministic tier-aware wave dispatcher for /mgh-init "
                    "fan-out (scout/t1/t3; zero LLM turns; fixed template + "
                    "verbatim fields; host-CLI spawn)")
    ap.add_argument("--tier", choices=["scout", "t1", "t3"], default="scout",
                    help="fan-out tier (default scout). Selects the enumeration "
                         "script, task template, placeholder set, and fanout agent; "
                         "scout call shape (--scout-plan etc.) is unchanged")
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
    # shared
    ap.add_argument("--checkpoints", required=True,
                    help="tier checkpoint dir (markers; forwarded to the tier's "
                         "list script)")
    ap.add_argument("--inputs-dir", required=True,
                    help="per-unit input dir (forwarded as --materialize; audit "
                         "<unit>.task.md copies land here)")
    ap.add_argument("--host", choices=["claude", "opencode"],
                    help="explicit host CLI; default: opencode in PATH, else claude, "
                         "else exit 2 + manual-dispatch fallback recipe")
    ap.add_argument("--wave", type=int, default=DEFAULT_WAVE,
                    help=f"concurrent subprocesses per wave (default {DEFAULT_WAVE})")
    ap.add_argument("--time-budget-ms", type=int, default=None,
                    help="soft deadline in ms: stop starting waves, drain in-flight, "
                         "exit 0 with partial:true (re-dispatch the same command). "
                         "RECOMMENDED = host per-call timeout x 0.8 (host 900000ms -> "
                         "720000; claude Bash cap 600000ms -> 480000); MUST stay BELOW "
                         "the host per-call timeout (soft deadline fires before the "
                         "host hard kill; invariant: call-timeout-s x drain headroom "
                         "< time-budget-ms < host per-call timeout, >=20%% per level)")
    ap.add_argument("--call-timeout-s", type=int, default=DEFAULT_CALL_TIMEOUT_S,
                    help=f"per-subprocess timeout in seconds (default "
                         f"{DEFAULT_CALL_TIMEOUT_S}; calibrated for slow intranet LLM "
                         f"endpoints, ~4x headroom; better-slow-than-killed: a killed "
                         f"unit leaves no marker, stays pending, re-dispatch wastes "
                         f"a whole run)")
    ap.add_argument("--stall-waves", type=int, default=DEFAULT_STALL_WAVES,
                    help=f"convergence circuit breaker: stop dispatching and exit 2 "
                         f"after N consecutive waves with ZERO done+failed progress "
                         f"and pending non-empty (default {DEFAULT_STALL_WAVES}; "
                         f"stdout carries stalled:true + stalled_pending[] with each "
                         f"stuck unit's marker existence; recipe: stop re-dispatching, "
                         f"diagnose via resume_state.py --check)")
    ap.add_argument("--resume", action="store_true",
                    help="re-derive pending from disk markers (same entry point as a "
                         "fresh call; kept for call-shape parity)")
    ap.add_argument("--kill-stale", action="store_true",
                    help="orphan-tree cleanup: inspect <init-dir>/fanout_runner.<tier>.pid "
                         "liveness files and kill what they record (runner tree; or, when "
                         "the runner is dead, recorded host-CLI child trees). DESTRUCTIVE: "
                         "run with --dry-run first — a real kill with detected targets and "
                         "no prior dry-run review exits 2 + recipe. Idempotent; tier-agnostic")
    ap.add_argument("--pending-file", metavar="<list-stdout.json>",
                    help="TEST HOOK: consume the tier listing from a file "
                         "(no spawn, no list invocation)")
    ap.add_argument("--purge-audit", action="store_true",
                    help="delete <inputs-dir>/*.task.md audit copies (with --dry-run: "
                         "list only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --purge-audit: list without deleting; alone: skip dispatch")
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
    if args.call_timeout_s < 1:
        _eprint("error: --call-timeout-s must be >= 1")
        return 2
    if args.stall_waves < 1:
        _eprint("error: --stall-waves must be >= 1")
        return 2

    tier = TIERS[args.tier]

    # --kill-stale recovery mode: NEVER requires the tier plan artifacts (it
    # runs in exactly the broken-state contexts where they may be missing) —
    # only --checkpoints (+ --inputs-dir by argparse). Tier-agnostic by
    # construction: the liveness scan is a `fanout_runner.*.pid` glob.
    if args.kill_stale:
        plan_flag = getattr(args, tier["plan_arg"], None)
        if plan_flag:
            init_dirs = [Path(plan_flag).parent]
        else:
            # candidate run dirs: checkpoints' grandparent + inputs-dir's
            # grandparent (they coincide in the standard <init-dir>/<sub>/
            # layout; both scanned so a flat layout still resolves)
            cps, ips = Path(args.checkpoints).resolve(), Path(args.inputs_dir).resolve()
            init_dirs = []
            for p in (cps.parent.parent, ips.parent.parent, cps.parent, ips.parent):
                if p not in init_dirs:
                    init_dirs.append(p)
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

    plan_path = Path(getattr(args, tier["plan_arg"]))
    checkpoints = Path(args.checkpoints)
    inputs_dir = Path(args.inputs_dir)
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
        host = _detect_host(args.host, tier)

    repo_str = listing.get("repo") or ""
    if not repo_str:
        _eprint("error: pending listing carries no `repo` anchor")
        return 1
    repo = Path(repo_str).resolve()
    if not repo.is_dir():
        _eprint(f"error: repo anchor is not a directory: {repo}")
        return 1

    template = _load_template(tier, args.template)
    codegraph = _codegraph_signal(plan_path)
    total = int(listing.get("total", 0))
    done0 = int(listing.get("done", 0))
    failed0 = int(listing.get("failed", 0))

    deadline = (time.monotonic() + args.time_budget_ms / 1000.0
                if args.time_budget_ms is not None else None)
    waves_run = 0
    failed_written: list[str] = []
    wave_durations: list[float] = []
    soft_deadline_hit = False
    stalled = False
    # zero-progress circuit breaker state: terminal-count snapshot after each
    # fully-joined wave (anchor = wave-boundary final state, NOT in-flight counts);
    # N consecutive equal snapshots with pending non-empty → convergence failure.
    stall_waves_left = args.stall_waves
    last_terminal_count = None

    def _sidecar_payload(state: str, snap_dict: dict, pending_now: list) -> dict:
        """Sidecar body — counts derive from the SAME snapshot as the stdout
        summary (single source; test asserts the two agree)."""
        done_n = int(snap_dict.get("done", done0))
        failed_n = int(snap_dict.get("failed", failed0)) + len(set(failed_written))
        pending_n = len(pending_now)
        avg = (sum(wave_durations) / len(wave_durations)) if wave_durations else 0.0
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
            # Conservative ETA (one unit per wave slot): a human reference
            # number, precision NOT promised.
            "eta_batches": pending_n,
            "state": state,
        }

    def _snapshot() -> dict:
        """Re-derive pending via the list CLI (or the frozen test listing, first
        iteration only) — disk markers remain the only truth source (D4)."""
        if args.pending_file and waves_run == 0:
            return listing
        if args.pending_file:
            return {"repo": repo_str, "total": total, "done": done0,
                    "failed": failed0, "pending": []}  # test hook: single pass
        return _list_pending(tier, args)

    snap = _snapshot()
    pending = snap.get("pending", [])
    id_field = tier["id_field"]
    _eprint(f"[fanout_runner] tier={args.tier} host={host} repo={repo} "
            f"total={total} pending={len(pending)} wave={args.wave} "
            f"codegraph={codegraph}")

    # Liveness registration (orphan signal, NOT a lock): written for EVERY
    # dispatch exit path via try/finally below; a hard kill leaves it behind
    # and --kill-stale disambiguates. The body dict is reused (mutated only in
    # its `children` field) so the started_ts/cmdline stay stable across
    # per-wave refreshes.
    liveness_path = _write_liveness(plan_path.parent, args.tier, host)
    liveness_body = json.loads(liveness_path.read_text(encoding="utf-8"))
    children_now: list = []
    children_lock = threading.Lock()
    hb_state = {"done": done0}
    hb_lock = threading.Lock()
    t0 = time.monotonic()

    def _hb_count(inc: int = 0) -> int:
        with hb_lock:
            hb_state["done"] += inc
            return hb_state["done"]

    try:
        while pending:
            if deadline is not None and time.monotonic() >= deadline:
                _eprint(f"[fanout_runner] soft time budget reached; stopping new waves "
                        f"({len(pending)} pending stay resumable)")
                soft_deadline_hit = True
                break
            wave = pending[: args.wave]
            waves_run += 1
            wave_t0 = time.monotonic()
            _eprint(f"[fanout_runner] wave {waves_run}: dispatching {len(wave)} unit(s): "
                    f"{[u.get(id_field) for u in wave]}")

            def _dispatch(unit: dict) -> None:
                uid = unit.get(id_field, "?")
                # Anchor-tree interception BEFORE spawn (path-drift never spawns).
                reason = _anchor_check(tier, unit, repo)
                if reason:
                    _write_failed_marker(tier, unit, reason)
                    failed_written.append(uid)
                    _hb(t0, args.tier, waves_run, uid, "failed", _hb_count(), total)
                    _eprint(f"[fanout_runner] unit {uid}: FAILED pre-spawn ({reason})")
                    return
                task = _fill_template(tier, template, unit, repo_str, codegraph)
                audit = inputs_dir / f"{_safe_name(uid)}.task.md"
                try:
                    audit.parent.mkdir(parents=True, exist_ok=True)
                    audit.write_text(task, encoding="utf-8")
                except OSError as e:
                    _eprint(f"warn: audit copy unwritable for {uid}: {e}")
                if host == "test":
                    _eprint(f"[fanout_runner] unit {uid}: test hook — no spawn")
                    return
                if args.dry_run:
                    # --dry-run alone: fill audit copies, spawn nothing (R5.3b
                    # contract; also the no-LLM smoke path over the real list CLI).
                    _eprint(f"[fanout_runner] unit {uid}: dry-run — no spawn")
                    return
                cmd = _spawn_cmd(tier, host)
                _hb(t0, args.tier, waves_run, uid, "spawn", _hb_count(), total)
                status, ack, detail, child_pid = _run_unit(
                    host, cmd, task, repo, args.call_timeout_s)
                if child_pid is not None:
                    with children_lock:
                        children_now.append({"pid": child_pid, "unit": uid,
                                             "tier": args.tier})
                        _update_liveness_children(liveness_path, liveness_body,
                                                  list(children_now))
                if ack is not None and ack.startswith("failed:"):
                    _write_failed_marker(tier, unit, ack[len("failed:"):])
                    failed_written.append(uid)
                    _hb(t0, args.tier, waves_run, uid, "failed", _hb_count(), total)
                    _eprint(f"[fanout_runner] unit {uid}: failed ack → .failed marker")
                elif status in ("timeout", "crash", "spawn-error"):
                    _hb(t0, args.tier, waves_run, uid,
                        "timeout" if status == "timeout" else "crash",
                        _hb_count(), total)
                    _eprint(f"[fanout_runner] unit {uid}: {status} ({detail[:200]}) → "
                            f"stays pending (resume re-dispatches)")
                else:
                    _hb(t0, args.tier, waves_run, uid, "ok", _hb_count(1), total)
                    _eprint(f"[fanout_runner] unit {uid}: {ack or 'marker-only'} ({detail[:120]})")

            with ThreadPoolExecutor(max_workers=len(wave)) as pool:
                list(pool.map(_dispatch, wave))

            wave_durations.append(time.monotonic() - wave_t0)
            # Wave end: clear the in-flight children registry + wave-end
            # heartbeat line.
            with children_lock:
                children_now.clear()
            _update_liveness_children(liveness_path, liveness_body, [])
            _hb(t0, args.tier, waves_run, "-", "wave-end", _hb_count(), total)
            snap = _snapshot()
            pending = snap.get("pending", [])
            # Per-wave sidecar refresh (counts = snapshot-derived, same source as
            # the stdout summary; human watches from a second terminal, zero
            # orchestrator involvement).
            _write_sidecar(plan_path.parent, args.tier,
                           _sidecar_payload("running", snap, pending))
            # Zero-progress circuit breaker: every unit of this wave fully joined,
            # so the terminal count here is the wave-boundary FINAL state. N
            # consecutive zero-progress waves with pending non-empty = identity/
            # permission drift between pending derivation and marker writes
            # (each wave re-dispatches the same finished units, progress stays 0)
            # → stop dispatching, exit 2 with per-unit diagnosis. This REPLACES
            # the old same-size heuristic (which only caught a full-wave crash
            # and never fired when the enumerator misjudged units as pending).
            terminal_count = (int(snap.get("done", 0)) + int(snap.get("failed", 0))
                              + len(failed_written))
            if pending:
                if last_terminal_count is not None and terminal_count == last_terminal_count:
                    stall_waves_left -= 1
                else:
                    stall_waves_left = args.stall_waves - 1
                last_terminal_count = terminal_count
                if stall_waves_left <= 0:
                    stalled = True
                    _eprint(f"[fanout_runner] STALLED: {args.stall_waves} consecutive "
                            f"wave(s) with zero done+failed progress and "
                            f"{len(pending)} pending — stopping dispatch (pending "
                            f"units remain resumable). Recipe: stop re-dispatching "
                            f"this command; diagnose via "
                            f"`resume_state.py --target <target> --check` and "
                            f"cross-check each unit's marker existence against "
                            f"stalled_pending[] below (marker-unwritable / "
                            f"identity drift).")
                    break
            else:
                stall_waves_left = args.stall_waves
                last_terminal_count = None

        done_now = int(snap.get("done", done0))
        failed_now = int(snap.get("failed", failed0)) + len(failed_written)
        # Reconcile: markers written this run may not be reflected in the last
        # snapshot if the wave bailed before re-listing.
        if failed_written:
            failed_now = max(failed_now, failed0 + len(set(failed_written)))
        partial = bool(pending)
        # Terminal sidecar state (counts consistent with the stdout summary below
        # by construction — both derive from {snap, failed_written}).
        _write_sidecar(plan_path.parent, args.tier,
                       _sidecar_payload(
                           "exited-partial" if partial else "exited-clean",
                           snap, pending))
        result = {
            "runner": "fanout_runner",
            "tier": args.tier,
            "repo": repo_str,
            "host": host,
            "total": total,
            "done": done_now,
            "failed": failed_now,
            "pending": len(pending),
            "wave": args.wave,
            "waves_run": waves_run,
            "partial": partial,
            "stalled": stalled,
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
                for u in pending]
        if args.dry_run:
            result["dry_run"] = True
        _eprint(f"[fanout_runner] done ({args.tier}): {result['done']}/{total} done, "
                f"{result['failed']} failed, {result['pending']} pending, partial={partial}"
                + (", STALLED" if stalled else ""))
        print(json.dumps(result, ensure_ascii=False))
        return 2 if stalled else 0
    finally:
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
