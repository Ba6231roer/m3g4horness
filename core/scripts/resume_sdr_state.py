#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
resume_sdr_state — re-entrant orchestrator resume-state machine for /mgh-sdr.

The single sanctioned outlet for the orchestrator reflex "which step am I on / what do I
do next" for sdr. Derives the pipeline's CURRENT step and EXACT next action PURELY from
on-disk products — `<run-dir>/context.json`, `<run-dir>/grouping.json`, the unit markers
`<run-dir>/markers/<unit_id>.{done,failed}` and the terminal `<run-dir>/sdr_manifest.json`
— independent of any conversation / session memory. This collapses compact / crash /
new-session into ONE recovery path: read disk → continue. Sister script of init's
`resume_state.py` and ut-init's `resume_ut_init_state.py`; those two are ZERO-changed
(their blast radius stays isolated, R5.4).

Two deliberate differences from the ut-init sibling:

  * NO `run_config.json` dependency. The only step whose start state (base/branch) has no
    on-disk derivation is `not-started` — and that is precisely the step with ZERO
    completed work, so re-supplying the parameters re-runs it losslessly. The start state
    is therefore disclosed as a degradation, never guessed
    (see `security-design-review`: run_config carries ONLY the codegraph signal).
  * Step identity is derived from FORWARD marker paths over the canonical unit-id set
    (`sdr_tier`, shared with the enumerator `diff_group.py`) — never from a filename glob
    and never from `grouping.json::units[].status` (an enumeration-time snapshot that is
    stale the moment fan-out starts).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/os/subprocess/sys/pathlib).

CLI contract (`--help` is the contract surface, R5.1):
  py resume_sdr_state.py --run-dir <abs> [--repo <abs>] [--check] [--rearm-sentinel]

  --run-dir        the sdr run dir (REQUIRED — sdr has no unique default: the launcher
                   stamps `<repo>/.mgh-sdr/runs/<ts>-<branch>/`, so every run differs).
  --repo           target repo root; optional (derived from context.json, else from the
                   `<repo>/.mgh-sdr/runs/<…>` layout).
  --check          boundary check (R5.9): validate on-disk state self-consistency, exit 0/2.
  --rearm-sentinel rewrite `<repo>/.mgh-sdr/.active` deterministically from disk, exit 0.

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"repo":"<abs>","run_dir":"<abs>","base":"<ref>","branch":"<ref>","step":"<enum>",
   "resumable":bool,"tiers":{"done":N,"failed":N,"total":N},
   "next_action":{"kind":"bash|subagent|done","desc":"...","absolute_paths":["<abs>",...]},
   "notes":["..."],
   "discipline_reminders":{"gates":[...],"path_recipes":[...],"nevers":[...]},
   "stale_fanout":[{"tier":..,"pid_file":..,"pid":..,"pid_alive":bool,"note":"..."}]}

step ∈ not-started|group|fanout|render|done — the step NAME is the CURRENT TODO step
("not-started" = run this step next), matching init's t1/t2 convention. The blocking
sequence is context → group → fanout → render → done, and a step is "complete enough to
proceed" when `done + failed >= total` (a `.failed` unit is terminal — a confirmed
failure, NOT retried on --resume, NOT blocking). Any non-zero `failed` is surfaced in
`notes[]` (advisory). Every path on stdout is `Path.resolve()` absolute (Windows-native,
NEVER a shell MSYS form).

Exit codes (R5.3b): 0 ok · 1 run-dir missing/not a dir · 2 misuse (argparse) or
underivable state (malformed context.json/grouping.json, or a `--check` violation) —
the script NEVER guesses a step from a damaged product. Read-only, idempotent, no TTY.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Self-locate this script's dir so sibling imports resolve under any cwd / host-agent
# invocation (direct `py`/`python`). (R5.3a self-contained family.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from discipline_core import get_discipline  # noqa: E402
from sdr_tier import (  # noqa: E402
    forward_done_ids, forward_failed_ids, forward_marker_paths, orphan_markers,
)

# The run dir layout the launcher stamps and the shell accepts:
# <repo>/.mgh-sdr/runs/<ts>-<branch>/  →  the repo root is three levels up.
RUN_ROOT_NAME = ".mgh-sdr"
RUNS_DIRNAME = "runs"
SENTINEL = Path(RUN_ROOT_NAME) / ".active"

STEPS = ("not-started", "group", "fanout", "render", "done")
# Steps during which the runtime guard is expected to be armed: the run already has
# products on disk, so a missing sentinel means the guard is silently asleep (the
# read-confinement / script-read-only defenses do not apply ⇒ not an operational
# nuisance but a security regression). `not-started` has nothing to protect yet;
# `done` means the run is wound down and the guard SHOULD be dormant.
SENTINEL_REQUIRED_STEPS = ("group", "fanout", "render")


def _eprint(*a):
    print(*a, file=sys.stderr)


def _load_json(path: Path):
    """Read + parse JSON; returns (obj, None) or (None, err_str)."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except OSError as e:
        return None, f"unreadable: {e}"
    except ValueError as e:
        return None, f"malformed JSON: {e}"


def _script_abs(name: str) -> str:
    """Absolute path of a sibling leaf script (same install dir — R5.3a)."""
    return str(Path(__file__).resolve().parent / name)


def _repo_from_layout(run_dir: Path):
    """Derive the repo root from the standard `<repo>/.mgh-sdr/runs/<name>` layout.
    Returns None when the run dir does not follow it (NEVER guesses a parent)."""
    if run_dir.parent.name == RUNS_DIRNAME \
            and run_dir.parent.parent.name == RUN_ROOT_NAME:
        return str(run_dir.parent.parent.parent)
    return None


def _marker_out(checkpoints: Path, unit_id: str) -> tuple:
    """(done_marker, failed_marker) as Path objects, via the SHARED forward predicate
    (never a filename glob, never a record-body field)."""
    _, done, failed = forward_marker_paths(checkpoints, unit_id)
    return Path(done), Path(failed)


def _pid_alive(pid) -> bool:
    """OS process-table liveness probe (stdlib only; mirrors the dispatcher's own
    probe so the two never disagree about "is this PID still around"). Windows:
    `tasklist /fi "PID eq <pid>" /fo csv /nh` (a dead PID prints an info line with
    no csv row). POSIX: /proc/<pid>."""
    if not isinstance(pid, int) or pid <= 0:
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


def _scan_stale_fanout(run_dir: Path) -> list:
    """Residual liveness files `<run-dir>/fanout_runner.<tier>.pid` (a hard-killed
    runner leaves one behind). Advisory: reports the tier, the PID and whether that
    PID is still in the process table, plus the sanctioned cleanup recipe."""
    out = []
    for pf in sorted(run_dir.glob("fanout_runner.*.pid")):
        if not pf.is_file():
            continue
        body, err = _load_json(pf)
        tier = pf.name[len("fanout_runner."):-len(".pid")]
        pid = body.get("pid") if isinstance(body, dict) else None
        if err:
            out.append({"tier": tier, "pid_file": str(pf.resolve()), "pid": None,
                        "pid_alive": False,
                        "note": f"liveness file unreadable ({err}) — a residual file from a "
                                f"hard-killed runner; `fanout_runner.py --tier {tier} "
                                f"--kill-stale --dry-run` inspects and clears it"})
            continue
        alive = _pid_alive(pid)
        if alive:
            note = (f"PID {pid} is STILL in the process table — a runner for this run dir "
                    f"may be alive; inspect before re-dispatching: `fanout_runner.py "
                    f"--tier {tier} --kill-stale --dry-run` (then drop --dry-run to kill "
                    f"the orphan tree)")
        else:
            note = (f"residual liveness file (PID {pid} is gone) — a hard-killed runner "
                    f"left it; clear with `fanout_runner.py --tier {tier} --kill-stale`")
        out.append({"tier": tier, "pid_file": str(pf.resolve()),
                    "pid": pid if isinstance(pid, int) else None,
                    "pid_alive": bool(alive), "note": note})
    return out


def _next(kind: str, desc: str, paths) -> dict:
    return {"kind": kind, "desc": desc, "absolute_paths": [str(p) for p in paths]}


def _resolve_repo(ctx, grp, args, run_dir: Path, notes: list) -> str:
    """Repo root, in priority order: context.json (disk truth) > --repo > the run-dir
    layout. A disagreement between context.json and --repo is disclosed. Returns ""
    when underivable — the caller MUST NOT invent one."""
    disk_repo = ctx.get("repo") if isinstance(ctx, dict) else None
    layout = _repo_from_layout(run_dir)
    if disk_repo:
        if args.repo and str(Path(args.repo).resolve()) != str(Path(disk_repo).resolve()):
            notes.append(f"--repo {args.repo!r} disagrees with context.json::repo "
                         f"{disk_repo!r}; context.json is the disk truth and wins.")
        return str(Path(disk_repo).resolve())
    if args.repo:
        return str(Path(args.repo).resolve())
    if layout:
        return str(Path(layout).resolve())
    return ""


def resolve(run_dir: Path, args) -> tuple:
    """Build the full state dict from disk. Returns (state, None) or (None, recipe)
    when a product exists but cannot be read (caller exits 2 — NEVER guess)."""
    notes: list = []
    ctx_path = run_dir / "context.json"
    grp_path = run_dir / "grouping.json"
    manifest = run_dir / "sdr_manifest.json"
    checkpoints = run_dir / "markers"
    slices = run_dir / "slices"

    ctx = {}
    if ctx_path.is_file():
        ctx, err = _load_json(ctx_path)
        if not isinstance(ctx, dict):
            return None, (f"context.json {err or 'is not a JSON object'} — re-run "
                          f"`sdr_context.py --repo <abs> --run-dir {run_dir}` "
                          f"(deterministic, idempotent); NEVER guess the step graph.")

    grp = {}
    if grp_path.is_file():
        grp, err = _load_json(grp_path)
        if not isinstance(grp, dict):
            return None, (f"grouping.json {err or 'is not a JSON object'} — re-run "
                          f"`diff_group.py ... --checkpoints {checkpoints} "
                          f"--materialize {slices}`; NEVER guess the step graph.")

    repo = _resolve_repo(ctx, grp, args, run_dir, notes)

    # --- start state (base/branch) -------------------------------------------
    base = ctx.get("base") or grp.get("base") or ""
    branch = ctx.get("branch") or grp.get("branch") or ""
    if isinstance(ctx, dict) and isinstance(grp, dict) and ctx.get("base") and grp.get("base") \
            and ctx["base"] != grp["base"]:
        notes.append(f"base disagrees between context.json ({ctx['base']!r}) and "
                     f"grouping.json ({grp['base']!r}); context.json wins.")
    if isinstance(ctx, dict) and isinstance(grp, dict) and ctx.get("branch") and grp.get("branch") \
            and ctx["branch"] != grp["branch"]:
        notes.append(f"branch disagrees between context.json ({ctx['branch']!r}) and "
                     f"grouping.json ({grp['branch']!r}); context.json wins.")

    # --- canonical unit ids + marker judgment --------------------------------
    # `units[]` (NOT `pending[]`) is the canonical set: pending[] is re-enumeration
    # output and drops units that already finished. Judgment is forward-marker
    # existence; `units[].status` is an enumeration-time snapshot and is NEVER read.
    units = grp.get("units") if isinstance(grp, dict) else None
    unit_ids = [u.get("unit_id") for u in units
                if isinstance(u, dict) and u.get("unit_id")] if isinstance(units, list) else []
    total = len(unit_ids)
    done_ids = forward_done_ids(checkpoints, unit_ids)
    failed_ids = forward_failed_ids(checkpoints, unit_ids)
    orphans = orphan_markers(checkpoints, unit_ids)

    # --- step derivation (short-circuit, disk existence only) ----------------
    if not ctx_path.is_file():
        step = "not-started"
    elif not grp_path.is_file():
        step = "group"
    elif len(done_ids) + len(failed_ids) < total:
        step = "fanout"
    elif not manifest.is_file():
        step = "render"
    else:
        step = "done"

    # --- disclosures ---------------------------------------------------------
    excluded = grp.get("excluded") if isinstance(grp, dict) else None
    excluded_count = excluded.get("count", 0) if isinstance(excluded, dict) else 0
    if grp_path.is_file() and total == 0:
        if grp.get("empty"):
            notes.append("zero-diff: the branch has no changes at all — 0 units to review, "
                         "so the fan-out step is vacuously complete (0 >= 0) and the "
                         "pipeline advances to render (NEVER idles in fan-out).")
        elif excluded_count > 0:
            notes.append(f"every changed file was excluded by the closed exclusion set "
                         f"(total=0, excluded={excluded_count}) — 0 units to review, so the "
                         f"fan-out step is vacuously complete and the pipeline advances to "
                         f"render (this is NOT a zero-diff run; re-run with "
                         f"--include-excluded to review them anyway).")
        else:
            notes.append("grouping.json lists no units (total=0) — the fan-out step is "
                         "vacuously complete; verify the enumeration if a review was expected.")
    pending_n = total - len(done_ids) - len(failed_ids)
    if step == "fanout":
        notes.append(f"{pending_n}/{total} unit(s) have no terminal marker yet "
                     f"(done={len(done_ids)} failed={len(failed_ids)}).")
    if failed_ids:
        notes.append(f"{len(failed_ids)}/{total} unit(s) terminated as FAILED (terminal — "
                     f"NOT retried on --resume); see the .failed markers and each unit's "
                     f"run.log under {checkpoints}/sdr/ for the reason (advisory, non-gating).")
    if orphans:
        notes.append(f"{len(orphans)} orphan marker file(s) on disk belong to no canonical "
                     f"unit id (legacy/renamed run products); they are NOT counted as "
                     f"terminal: {', '.join(orphans[:5])}"
                     f"{' …' if len(orphans) > 5 else ''}")
    if not repo:
        notes.append("repo could not be derived from context.json or the "
                     "`<repo>/.mgh-sdr/runs/<…>` layout — pass `--repo <abs>` explicitly "
                     "(the script NEVER invents a repository root).")

    # --- next action ---------------------------------------------------------
    if step == "not-started":
        notes.append("start state is not on disk yet (context.json absent): --base / "
                     "--branch cannot be re-derived and MUST be supplied again — this is "
                     "NOT data loss, it is the one step with ZERO completed work, so "
                     "re-running it with the same parameters restores the run completely.")
        repo_arg = repo if repo else "<repo abs>"
        desc = (f"run `py {_script_abs('sdr_context.py')} --repo {repo_arg} "
                f"--run-dir {run_dir} --base {base or 'master'} "
                f"--branch {branch or '<当前分支>'}` — this step also writes the run's "
                f"codegraph signal (run_config.json) and the runtime-guard sentinel")
        nxt = _next("bash", desc, [run_dir] + ([repo] if repo else []))
    elif step == "group":
        nxt = _next("bash",
                    f"run `py {_script_abs('diff_group.py')} --repo {repo} "
                    f"--base {base or 'master'} --branch {branch} "
                    f"--checkpoints {checkpoints} --materialize {slices}`, then "
                    f"`py {_script_abs('diff_group.py')} --check {run_dir}` "
                    f"(exit 2 → fix and re-run; NEVER carry a broken work-list into fan-out)",
                    [repo, checkpoints, slices, grp_path])
    elif step == "fanout":
        nxt = _next("bash",
                    f"run `py {_script_abs('fanout_runner.py')} --tier sdr --repo {repo} "
                    f"--base {base or 'master'} --branch {branch} "
                    f"--checkpoints {checkpoints} --inputs-dir {slices} "
                    f"--time-budget-ms 480000 --call-timeout-s 360 --stall-timeout-s 300` "
                    f"(four-level timeout invariant; opencode hosts calibrated to 900s use "
                    f"720000/540/300) — unit paths come from that command's own "
                    f"`pending[]`, never hand-built",
                    [repo, checkpoints, slices, grp_path])
    elif step == "render":
        nxt = _next("bash",
                    f"run `py {_script_abs('render_sdr_report.py')} --run-dir {run_dir} "
                    f"--repo {repo}`, then "
                    f"`py {_script_abs('render_sdr_report.py')} --check {run_dir}`",
                    [run_dir, repo, manifest])
    else:
        nxt = _next("done",
                    "pipeline complete — every unit reached a terminal marker and "
                    "sdr_manifest.json is present (the report was written first).",
                    [])

    state = {
        "repo": repo,
        "run_dir": str(run_dir),
        "base": base,
        "branch": branch,
        "step": step,
        "resumable": step != "done",
        "tiers": {"done": len(done_ids), "failed": len(failed_ids), "total": total},
        "next_action": nxt,
        "notes": notes,
        "discipline_reminders": get_discipline(step, domain="sdr"),
        "stale_fanout": _scan_stale_fanout(run_dir),
    }
    return state, None


def check(run_dir: Path, args) -> dict:
    """R5.9 self-consistency validation. Returns {ok, violations[], notes[]}."""
    violations: list = []
    notes: list = []
    state, recipe = resolve(run_dir, args)
    if state is None:
        return {"ok": False, "violations": [{"issue": recipe}], "notes": []}

    repo = state["repo"]
    step = state["step"]
    checkpoints = run_dir / "markers"
    grp_path = run_dir / "grouping.json"

    # (1) guard window: run in progress but the sentinel is missing = guard asleep.
    if step in SENTINEL_REQUIRED_STEPS:
        if not repo:
            notes.append("sentinel check SKIPPED: repo is underivable, so the sentinel "
                         "location `<repo>/.mgh-sdr/.active` cannot be resolved — pass "
                         "`--repo <abs>` to make this check effective.")
        elif not (Path(repo) / SENTINEL).is_file():
            violations.append({"issue":
                f"runtime-guard sentinel MISSING while the run is in progress "
                f"(step={step}): {Path(repo) / SENTINEL} — the guard (script read-only / "
                f"target-subtree confinement) is silently ASLEEP for this run. Re-arm it: "
                f"`py {_script_abs('resume_sdr_state.py')} --rearm-sentinel "
                f"--run-dir {run_dir}`"})
    elif step == "not-started":
        notes.append("sentinel check not applicable: no run product exists yet "
                     "(the step that writes the sentinel has not run).")
    elif step == "done":
        notes.append("sentinel check not applicable: the run is wound down and the guard "
                     "is expected to be dormant.")

    # (2) ambiguous terminal: one unit carrying BOTH .done and .failed.
    units = None
    grp, err = _load_json(grp_path) if grp_path.is_file() else ({}, None)
    if isinstance(grp, dict):
        units = grp.get("units")
    unit_ids = [u.get("unit_id") for u in units
                if isinstance(u, dict) and u.get("unit_id")] if isinstance(units, list) else []
    for uid in unit_ids:
        dm, fm = _marker_out(checkpoints, uid)
        if dm.is_file() and fm.is_file():
            violations.append({"issue":
                f"ambiguous terminal for unit {uid!r}: BOTH {dm.name} and {fm.name} exist "
                f"— delete one to resolve (a unit cannot be both done and failed)"})

    # (3) work-list / enumeration-record agreement (the pending[] the dispatcher will
    #     consume must name units the canonical set knows about).
    if isinstance(grp, dict):
        known = set(unit_ids)
        pend = grp.get("pending")
        if isinstance(pend, list):
            for u in pend:
                uid = u.get("unit_id") if isinstance(u, dict) else None
                if uid and uid not in known:
                    violations.append({"issue":
                        f"grouping.json pending[] names unit {uid!r} which is absent from "
                        f"its own units[] — re-run diff_group.py (the work-list and the "
                        f"enumeration record disagree)"})

    # (4) orphan markers: advisory only (they never enter any done/failed set).
    orphans = orphan_markers(checkpoints, unit_ids)
    if orphans:
        notes.append(f"{len(orphans)} orphan marker file(s) belong to no canonical "
                     f"unit id (advisory, NOT counted as terminal): "
                     f"{', '.join(orphans[:5])}{' …' if len(orphans) > 5 else ''}")

    if state["stale_fanout"]:
        for s in state["stale_fanout"]:
            notes.append(f"stale fan-out liveness file ({s['tier']}): {s['note']}")

    return {"ok": not violations, "violations": violations, "notes": notes}


def rearm_sentinel(run_dir: Path, args) -> tuple:
    """Deterministically rewrite `<repo>/.mgh-sdr/.active` from disk. Returns
    (payload, exit_code). `target` = context.json::repo; `read_roots[]` = the
    external roots recorded in context.json that STILL exist as directories (fail
    closed: a vanished path is dropped, never re-declared). Paths are produced by
    Python (Windows-native) — NEVER a shell MSYS form. Atomic + idempotent."""
    ctx_path = run_dir / "context.json"
    if not ctx_path.is_file():
        return ({"error": "context.json absent — there is no run start state to rebuild "
                          "the sentinel from. The sentinel is written by `sdr_context.py` "
                          "as a script side effect; run that step first."}, 2)
    ctx, err = _load_json(ctx_path)
    if not isinstance(ctx, dict):
        return ({"error": f"context.json {err or 'is not a JSON object'} — cannot rebuild "
                          f"the sentinel."}, 2)
    repo = ctx.get("repo") or args.repo
    if not repo:
        return ({"error": "repo not derivable from context.json and --repo was not given — "
                          "pass `--repo <abs>` (NEVER guess a repository root)."}, 2)
    repo = Path(repo).resolve()
    roots = []
    for e in ctx.get("external_repos") or []:
        if not isinstance(e, dict):
            continue
        p = e.get("path")
        if not p:
            continue
        rp = Path(p)
        if rp.is_dir() and str(rp) not in roots:
            roots.append(str(rp))
    body = {"domain": "mgh-sdr", "target": str(repo), "out_roots": [],
            "read_roots": roots, "v": 1}
    sp = repo / SENTINEL
    sp.parent.mkdir(parents=True, exist_ok=True)
    tmp = sp.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, sp)
    except OSError as e:
        return ({"error": f"cannot write sentinel {sp}: {e}"}, 2)
    return ({"rearm_sentinel": {"sentinel_path": str(sp), "target": str(repo),
                                "read_roots": roots, "domain": "mgh-sdr", "v": 1}}, 0)


def main():
    ap = argparse.ArgumentParser(
        description="derive /mgh-sdr current step + next action purely from disk "
                    "(re-entrant; the sanctioned resume entry for the sdr run domain)")
    ap.add_argument("--run-dir",
                    help="the sdr run dir (REQUIRED — sdr has no unique default run dir; "
                         "the launcher stamps <repo>/.mgh-sdr/runs/<ts>-<branch>/)")
    ap.add_argument("--repo", help="target repo root (optional; derived from context.json "
                                   "or the <repo>/.mgh-sdr/runs/<…> layout)")
    ap.add_argument("--check", action="store_true",
                    help="boundary check (R5.9): validate on-disk state self-consistency "
                         "(sentinel presence for the guard window, ambiguous terminals, "
                         "work-list agreement); exit 0/2")
    ap.add_argument("--rearm-sentinel", action="store_true",
                    help="deterministically rewrite <repo>/.mgh-sdr/.active from "
                         "context.json (atomic, idempotent); exit 0/2")
    # Emit JSON / glyphs cleanly regardless of host console codepage (e.g. cp936/gbk).
    # Before parse_args so --help is utf-8 too. No-op on StringIO (in-process tests).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = ap.parse_args()

    if not args.run_dir:
        _eprint("error: --run-dir <abs> is required (sdr has no unique default run dir; "
                "find it under <repo>/.mgh-sdr/runs/)")
        return 2
    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        _eprint(f"error: run dir not found: {run_dir}\n"
                f"recipe: pass the run dir the launcher/shell reported "
                f"(`<repo>/.mgh-sdr/runs/<ts>-<branch>/`); create it first if this is a "
                f"fresh run.")
        return 1

    if args.rearm_sentinel:
        payload, code = rearm_sentinel(run_dir, args)
        if code == 0:
            _eprint(f"[resume_sdr_state --rearm-sentinel] sentinel rewritten: "
                    f"{payload['rearm_sentinel']['sentinel_path']} "
                    f"(read_roots={len(payload['rearm_sentinel']['read_roots'])})")
        else:
            _eprint(f"error: {payload['error']}")
        print(json.dumps(payload, ensure_ascii=False))
        return code

    if args.check:
        result = check(run_dir, args)
        _eprint(f"[resume_sdr_state --check] {run_dir}: "
                f"{'OK' if result['ok'] else str(len(result['violations'])) + ' violation(s)'}")
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 2

    state, recipe = resolve(run_dir, args)
    if state is None:
        # a product exists but cannot be read — NEVER guess the step graph
        _eprint(f"error: {recipe}")
        print(json.dumps({"step": None, "resumable": False,
                          "error": "run state underivable from disk"},
                         ensure_ascii=False))
        return 2
    t = state["tiers"]
    _eprint(f"[resume_sdr_state] step={state['step']} resumable={state['resumable']} "
            f"tiers={{done:{t['done']}, failed:{t['failed']}, total:{t['total']}}} "
            f"next={state['next_action']['kind']}")
    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
