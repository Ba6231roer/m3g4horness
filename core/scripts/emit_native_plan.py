#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
emit_native_plan — deterministic materializer of native-dispatch plans.

Produces, for one fan-out tier, the disk artifacts an orchestrator needs to
dispatch units as NATIVE subagents (same host process, no headless child CLI):
the per-unit task messages, the wave split, and a short anti-miscopy unit id —
all BEFORE any model turn. It is a bypass SUPPLY face next to the subprocess
dispatcher (fanout_runner.py), not a replacement: the dispatcher's source is
never touched and its behavior never changes. Unit inputs are built by the SAME
module-level assets the dispatcher uses (tier table, enumerator call + run-dir
anchoring, template load, verbatim fill, anchor-tree check, safe filenames), so
native-form and subprocess-form unit construction cannot drift.

Usage (per-tier artifact flags mirror the dispatcher verbatim — they are
forwarded to the same tier enumerator):

  py emit_native_plan.py --tier sdr --repo <abs> --base <ref> [--branch <ref>]
     --checkpoints <run>/checkpoints --inputs-dir <run>/inputs
     [--profile <abs-project>] [--wave-size N] [--retry-failed]
     [--template <sdr-task.md>] [--check]
  py emit_native_plan.py --tier scout --scout-plan <scout_plan.json>
     --checkpoints <ck> --inputs-dir <in> [common flags]
  py emit_native_plan.py --tier t1 --clusters <clusters.json>
     --candidates <controls_candidates.json> --checkpoints <ck> --inputs-dir <in>
     [--pack-bytes B [--pack-max N]]
  py emit_native_plan.py --tier t2 --init-dir <.mgh-init> [--budget N]
     --checkpoints <ck> --inputs-dir <in>
  py emit_native_plan.py --tier scout-merge --init-dir <.mgh-init> [--budget N]
     --checkpoints <ck> --inputs-dir <in>
  py emit_native_plan.py --tier t3 --inventory <controls_inventory.json>
     --format opencode|claude --rules-dir <dir> --target <abs>
     --checkpoints <ck> --inputs-dir <in>

Artifacts (run dir = the plan artifact's directory, the same anchor the
dispatcher uses for its progress sidecar; for sdr that is the grouping.json
dir, for t2/scout-merge the init dir):

  <run>/native_plan.json          tier scout + tier sdr (the two single-tier
                                  consumers of the un-suffixed name).
  <run>/native_plan_<tier>.json   the four aggregate tiers (t1 / t2 / t3 /
                                  scout-merge) — one plan file PER TIER so the
                                  layers sharing one init dir never overwrite
                                  each other's plan evidence.
                                  {v, tier, agent, repo, wave_size, wave_size_source,
                                  units_total, waves[{wave, units[]}]} — every unit
                                  entry = the enumerator's pending fields verbatim
                                  plus {id, unit_id, task_file}; all paths absolute.
  <inputs-dir>/<unit>.task.md  the complete task message, verbatim template
                            fill (same path AND same content as the audit copy
                            the dispatcher writes when it dispatches).

The plan body's `agent` field carries the tier's NATIVE subagent twin (e.g.
init-induct-native), NOT the subprocess primary twin the dispatcher's tier
table names — the dispatch tool (`mgh_dispatch`) refuses primary-mode agents
before any spawn, and the orchestrator's channel-A wave loop spawns the
subagent twin by name. The tier table itself is untouched; the mapping lives
here with the other native-only semantics.

Zero-dispatch invariant (t2 / scout-merge): when the tier enumerator reports
`needs_reduce=false` (aggregate input fits one request), the plan is NEVER
written — no plan artifact, no sessions. The single-context stage runs as the
orchestrator's ordinary subagent call, byte-identical to the subprocess form;
this emit exits 0 with the note and touches nothing.

Determinism: no timestamps anywhere; units sorted by canonical id; fixed
serialization (ensure_ascii=False, indent=2, sort_keys, trailing newline);
the same inputs re-materialize BYTE-IDENTICAL artifacts (a pure function of
disk state + flags — the re-materialize-is-repair property --check relies on).

Short unit ids: <tier>-<4 chars> derived from sha1(canonical id) base32
lowercase with confusable chars (0/1/i/l/o) removed. Within one plan any two
ids sit at edit distance >= 2 (a one-char mis-transcription can never hit
another legal id); collisions resolve by deterministic re-derivation with an
incrementing salt (sha1(unit_id + ":" + salt)). Ids derive from the canonical
id, not from ordinals, so a shrunk pending set (resume) keeps surviving units'
ids unchanged. Short ids are for model transcription and human reconciliation
ONLY — they never take part in filesystem path construction (paths always
come verbatim from the enumerator).

Wave size: min(concurrency, max(1, quota.calls // quota.calls_per_unit)).
Concurrency = --wave-size > env-profile native_concurrency (default 3);
quota comes from the env profile only. wave_size_source records which side
won ("concurrency" on a tie). Static arithmetic only — runtime admission
(throttling, cooldown, storm truncation) stays with the dispatcher/watchdog
layers; this plan defines SHAPE, not pacing.

Zero dispatch side effects: no model host process is spawned, no credential
file is read or written, no child-config/XDG isolation dir is created, no
done/failed marker is touched. The ONLY subprocess is the tier enumerator
(the deterministic pending source). fanout_runner.py itself is imported, never
executed, never modified.

--check (zero-repair validation; exit 2 + named violations + re-materialize
recipe on any failure): (1) in-memory re-materialization compared byte-for-
byte against the on-disk plan AND every task file; (2) the plan's unit set
against the enumerator's CURRENT pending (a completed unit makes the plan
stale — reported, never passed); (3) every path absolute and inside the repo
anchor tree; (4) no residual template placeholders; (5) short-id mapping
closed and pairwise edit distance >= 2. Extra *.task.md audit copies left by
earlier dispatched units are NOT violations (the dispatcher never deletes
them). No auto-repair ever: re-running the emit with the same flags IS the
repair, and --check exists to say exactly when that is needed.

Contract: stdout = one structured JSON line (emit: tool/tier/agent/
units_total/waves/wave_size/wave_size_source/plan_path/inputs_dir; --check
adds check + violations). stderr = progress + recipes. Exit codes: 0 ok ·
1 bad inputs (plan artifact missing, template unreadable, unparsable pending,
missing repo anchor) · 2 misuse (missing/invalid flags, anchor-tree violation,
env-profile failure, --check violations). Idempotent; no TTY; reads/writes
only inside the repo-anchored tree. Zero runtime deps (Python >=3.10 stdlib).
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

# Self-locate so the sibling dispatcher + profile reader resolve under any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fanout_runner as fr          # sibling import — read-only reuse
import env_profile

PLAN_NAME = "native_plan.json"
PLAN_V = 1
TOOL_NAME = "emit_native_plan"
SHORT_LEN = 4
# Per-tier plan filename: the two incumbent single-tier consumers (scout, sdr)
# keep the un-suffixed `native_plan.json`; the four aggregate tiers share one
# init dir, so each gets its own suffixed file (native_plan_t1.json etc.) —
# layers never overwrite each other's plan evidence.
AGGREGATE_TIERS = ("t1", "t2", "t3", "scout-merge")
# The plan body's agent = the tier's NATIVE subagent twin (the dispatcher's
# tier table names the subprocess primary twin for ITS face; the native plan
# must carry the subagent-mode twin the host spawns — the dispatch tool
# refuses primary-mode agents before any spawn).
NATIVE_AGENTS = {
    "scout": "init-scout-native",
    "t1": "init-induct-native",
    "t2": "init-synthesis-native",
    "scout-merge": "init-scout-merge-native",
    "t3": "init-rulewriter-native",
    "sdr": "sdr-review-native",
}


def plan_filename(tier_id: str) -> str:
    """The tier's plan filename inside the run dir (see AGGREGATE_TIERS)."""
    if tier_id in AGGREGATE_TIERS:
        return f"native_plan_{tier_id}.json"
    return PLAN_NAME
# confusable chars removed from the base32-lowercase alphabet (digits 2-7 keep;
# 0/1 never occur in base32 but stay listed so the exclusion set is explicit)
SHORT_EXCLUDE = frozenset("01ilo")
MAX_SALT = 4096


def _eprint(*a):
    print(*a, file=sys.stderr)


# ---------------------------------------------------------------------------
# short-id derivation (pure)
# ---------------------------------------------------------------------------

def _short_body(unit_id: str, salt: int) -> str:
    """The 4-char body for one unit id and salt step (sha1 -> base32 lower ->
    drop confusables -> take 4). A 20-byte digest yields ~29 usable chars, so
    the pad branch is astronomically unlikely but stays deterministic."""
    key = unit_id if salt == 0 else f"{unit_id}:{salt}"
    b32 = base64.b32encode(hashlib.sha1(key.encode("utf-8")).digest())
    body = "".join(c for c in b32.decode("ascii").lower()
                   if c not in SHORT_EXCLUDE)
    if len(body) < SHORT_LEN:
        pad = base64.b32encode(hashlib.sha1((key + "#pad").encode("utf-8"))
                               .digest()).decode("ascii").lower()
        body += "".join(c for c in pad if c not in SHORT_EXCLUDE)
    return body[:SHORT_LEN]


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance (small strings; DP with one rolling row)."""
    if a == b:
        return 0
    if not a or not b:
        return len(a) + len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1,          # deletion
                           cur[j - 1] + 1,       # insertion
                           prev[j - 1] + (ca != cb)))  # substitution
        prev = cur
    return prev[-1]


def _assign_short_ids(tier_id: str, unit_ids: list) -> dict:
    """Greedy assignment in canonical-id order: each unit keeps its salt-0
    body unless it sits at edit distance < 2 from an already-assigned body,
    in which case it re-derives with salt 1, 2, ... until it fits. Deterministic
    for a given pending set; the whole-set invariant (pairwise distance >= 2)
    holds by construction."""
    assigned: list[str] = []
    result: dict[str, str] = {}
    for uid in sorted(unit_ids):
        uid = str(uid)
        for salt in range(MAX_SALT):
            body = _short_body(uid, salt)
            if all(_edit_distance(body, b) >= 2 for b in assigned):
                assigned.append(body)
                result[uid] = f"{tier_id}-{body}"
                break
        else:  # pragma: no cover — unbounded salt stream cannot exhaust
            _eprint(f"error: short-id assignment did not converge for unit "
                    f"{uid!r} within {MAX_SALT} salt rounds")
            sys.exit(1)
    return result


# ---------------------------------------------------------------------------
# wave-size arithmetic (pure; static shape, not runtime pacing)
# ---------------------------------------------------------------------------

def _resolve_wave(args) -> tuple:
    """(wave_size, wave_size_source). concurrency = --wave-size > env-profile
    native_concurrency > default; quota (env profile only) caps it with
    max(1, calls // calls_per_unit). Tie -> concurrency."""
    if args.wave_size is not None and args.wave_size < 1:
        _eprint(f"error: --wave-size must be >= 1 (got {args.wave_size})")
        sys.exit(2)
    quota = None
    conc = env_profile.DEFAULT_NATIVE_CONCURRENCY
    if args.profile is not None:
        profile_dir = Path(args.profile)
        if not profile_dir.is_dir():
            _eprint(f"error: --profile not a directory: {profile_dir}\n"
                    f"recipe: pass the project root that holds "
                    f".mgh/env-profile.json (or drop --profile for defaults)")
            sys.exit(2)
        try:
            profile = env_profile.load(profile_dir)
        except env_profile.EnvProfileError as e:
            _eprint(f"error: env profile rejected: {e}\n"
                    f"recipe: fix or delete the env-profile config — a "
                    f"malformed profile is NEVER silently treated as defaults")
            sys.exit(2)
        conc = profile.native_concurrency
        quota = profile.quota
    if args.wave_size:
        conc = args.wave_size
    if quota:
        per_window = max(1, quota["calls"] // quota["calls_per_unit"])
        ws = min(conc, per_window)
        src = "concurrency" if conc <= per_window else "quota"
        return ws, src
    return conc, "concurrency"


# ---------------------------------------------------------------------------
# plan computation (shared by emit and --check; pure w.r.t. disk writes)
# ---------------------------------------------------------------------------

def _compute(tier, tier_id, args, listing, inputs_dir, plan_path):
    """Build (plan_body, [(task_path, task_text), ...]) entirely in memory.
    Hard failures exit before any write: missing repo anchor (1), anchor-tree
    violation (2), unfilled placeholder (1, inside the fill). Zero units skip
    the repo requirement (nothing to anchor-check)."""
    repo_str = listing.get("repo") or ""
    units = list(listing.get("pending") or [])
    repo = None
    if units:
        if not repo_str:
            _eprint("error: pending listing carries no `repo` anchor")
            sys.exit(1)
        repo = Path(repo_str).resolve()
        if not repo.is_dir():
            _eprint(f"error: repo anchor is not a directory: {repo}")
            sys.exit(1)

    template = fr._load_template(tier, args.template)
    codegraph = fr._codegraph_signal(plan_path, tier_id)
    ordered = sorted(units,
                     key=lambda u: str(u.get(tier["id_field"], "")))

    # anchor-tree interception BEFORE any fill or write: a path-drift unit is
    # refused for the whole materialization (compute-then-write means zero
    # partial artifacts) — the response to a poisoned listing is never to
    # execute it, and unlike the dispatcher no .failed marker is written
    # (zero side effects).
    for unit in ordered:
        reason = fr._anchor_check(tier, unit, repo)
        if reason:
            _eprint(f"error: unit {unit.get(tier['id_field'])!r}: {reason}")
            _eprint("recipe: check whether --checkpoints/--inputs-dir were "
                    "pointed outside the repo anchor tree or the pending "
                    "listing was tampered with; re-materialize only after the "
                    "listing is clean")
            sys.exit(2)

    short_ids = _assign_short_ids(
        tier_id, [str(u.get(tier["id_field"], "")) for u in ordered])

    entries, tasks = [], []
    for unit in ordered:
        uid = str(unit.get(tier["id_field"], ""))
        task = fr._fill_template(tier, template, unit, repo_str, codegraph)
        task_path = inputs_dir / f"{fr._safe_name(uid)}.task.md"
        entry = dict(unit)                 # enumerator fields verbatim
        entry["id"] = short_ids[uid]       # + the three native-plan fields
        entry["unit_id"] = uid
        entry["task_file"] = str(task_path)
        entries.append(entry)
        tasks.append((task_path, task))

    ws, src = _resolve_wave(args)
    chunks = [entries[i:i + ws] for i in range(0, len(entries), ws)]
    waves = [{"wave": n, "units": chunk} for n, chunk in enumerate(chunks, 1)]
    body = {"v": PLAN_V, "tier": tier_id, "agent": NATIVE_AGENTS[tier_id],
            "repo": repo_str, "wave_size": ws, "wave_size_source": src,
            "units_total": len(entries), "waves": waves}
    return body, tasks


def _serialize(body: dict) -> str:
    return json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _materialize(plan_path: Path, body: dict, tasks) -> None:
    """Write phase (only after a fully successful compute): task files first
    (plain write, byte-identical to the dispatcher's audit copies), then the
    plan atomically last — a crash mid-materialize leaves no plan and --check
    reports the drift; re-materializing is the repair."""
    for task_path, task in tasks:
        task_path.parent.mkdir(parents=True, exist_ok=True)
        task_path.write_text(task, encoding="utf-8")
        _eprint(f"[emit_native_plan] task file: {task_path}")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = plan_path.with_name(plan_path.name + ".tmp")
    tmp.write_text(_serialize(body), encoding="utf-8")
    os.replace(tmp, plan_path)
    _eprint(f"[emit_native_plan] plan: {plan_path} "
            f"({body['units_total']} unit(s), {len(body['waves'])} wave(s), "
            f"wave_size={body['wave_size']} ({body['wave_size_source']}))")


# ---------------------------------------------------------------------------
# --check (zero-repair validation)
# ---------------------------------------------------------------------------

def _disk_units(body: dict) -> list:
    out = []
    for w in body.get("waves") or []:
        if isinstance(w, dict):
            for u in w.get("units") or []:
                if isinstance(u, dict):
                    out.append(u)
    return out


def _check_mode(tier, tier_id, args, listing, inputs_dir, plan_path) -> int:
    violations: list[str] = []
    disk_text = None
    disk_body = None
    if not plan_path.is_file():
        violations.append(f"plan not found: {plan_path}")
    else:
        disk_text = plan_path.read_text(encoding="utf-8")
        try:
            disk_body = json.loads(disk_text)
        except ValueError as e:
            violations.append(f"plan unparsable ({e}): {plan_path}")

    if disk_body is not None:
        units = _disk_units(disk_body)
        # (5) short-id mapping closed + pairwise edit distance >= 2
        seen_ids, seen_uids = {}, {}
        for u in units:
            for k in ("id", "unit_id", "task_file"):
                v = u.get(k)
                if not isinstance(v, str) or not v:
                    violations.append(f"unit entry missing {k!r}: {u!r}")
            sid, uid = u.get("id"), u.get("unit_id")
            if isinstance(sid, str) and sid:
                if sid in seen_ids:
                    violations.append(f"mapping not closed: duplicate short "
                                      f"id {sid!r} ({seen_ids[sid]!r} and "
                                      f"{uid!r})")
                seen_ids[sid] = uid
            if isinstance(uid, str) and uid:
                if uid in seen_uids:
                    violations.append(f"mapping not closed: duplicate unit id "
                                      f"{uid!r}")
                seen_uids[uid] = sid
        id_list = [i for i in seen_ids if isinstance(i, str)]
        for i in range(len(id_list)):
            for j in range(i + 1, len(id_list)):
                if _edit_distance(id_list[i], id_list[j]) < 2:
                    violations.append(
                        f"short ids at edit distance < 2: {id_list[i]!r} vs "
                        f"{id_list[j]!r} — a one-char mis-transcription could "
                        f"hit another legal unit")

    # (1)+(2)+(3)+(4) recompute from CURRENT disk state and compare
    body, tasks = _compute(tier, tier_id, args, listing, inputs_dir,
                           plan_path)
    if disk_text is not None and disk_text != _serialize(body):
        cur_ids = {e["unit_id"] for e in
                   [u for w in body["waves"] for u in w["units"]]}
        disk_ids = set(seen_uids) if disk_body is not None else set()
        if disk_ids - cur_ids:
            violations.append(
                f"plan is stale: units no longer pending (completed since the "
                f"plan was made): {sorted(disk_ids - cur_ids)}")
        elif cur_ids - disk_ids:
            violations.append(
                f"plan is behind: new pending units missing: "
                f"{sorted(cur_ids - disk_ids)}")
        else:
            violations.append(
                f"plan content drift vs re-materialization (tampered or "
                f"environment changed): {plan_path}")
    for task_path, task in tasks:
        if not task_path.is_file():
            violations.append(f"task file missing: {task_path}")
        elif task_path.read_text(encoding="utf-8") != task:
            violations.append(f"task file drifted: {task_path}")

    summary = {"tool": TOOL_NAME, "tier": tier_id, "agent": NATIVE_AGENTS[tier_id],
               "units_total": body["units_total"],
               "waves": len(body["waves"]), "wave_size": body["wave_size"],
               "wave_size_source": body["wave_size_source"],
               "plan_path": str(plan_path), "inputs_dir": str(inputs_dir)}
    if violations:
        summary["check"] = "failed"
        summary["violations"] = violations
        _eprint(f"error: emit_native_plan --check: {len(violations)} "
                f"violation(s):")
        for v in violations:
            _eprint(f"  - {v}")
        _eprint("recipe: re-run the same emit command to re-materialize — "
                "the plan is a deterministic product of disk state, NEVER a "
                "hand-edited file; if the unit set moved on, consuming the "
                "stale plan is exactly what this check prevents")
        print(json.dumps(summary, ensure_ascii=False))
        return 2
    summary["check"] = "ok"
    summary["violations"] = []
    _eprint(f"[emit_native_plan] --check ok: {plan_path} "
            f"({body['units_total']} unit(s), {len(body['waves'])} wave(s))")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="deterministic native-dispatch plan materializer: per-unit "
                    "task messages + wave split + short unit ids as disk "
                    "artifacts, reusing the subprocess dispatcher's tier "
                    "table/enumerator/template/anchor assets (dispatcher "
                    "source untouched, zero dispatch side effects)")
    ap.add_argument("--tier", required=True,
                    choices=["scout", "scout-merge", "t1", "t2", "t3", "sdr"],
                    help="fan-out tier (same closed set as the dispatcher; "
                         "selects the enumeration script, task template, "
                         "placeholder set, and fanout agent)")
    # per-tier artifact flags — names mirror the dispatcher and are forwarded
    # verbatim to the tier enumerator (the shared pending source)
    ap.add_argument("--scout-plan", help="scout_plan.json (scout tier)")
    ap.add_argument("--clusters", help="clusters.json (t1 tier)")
    ap.add_argument("--candidates",
                    help="controls_candidates.json (t1 tier)")
    ap.add_argument("--init-dir",
                    help=".mgh-init dir (t2 / scout-merge tiers)")
    ap.add_argument("--budget", type=int, default=None,
                    help="per-request aggregate byte cap (t2 / scout-merge; "
                         "default None -> plan_aggregate DEFAULT_BUDGET)")
    ap.add_argument("--inventory",
                    help="controls_inventory.json (t3 tier)")
    ap.add_argument("--format", dest="fmt",
                    choices=["opencode", "claude"],
                    help="rule format (t3 tier; determines rule_path)")
    ap.add_argument("--rules-dir", help="rules output dir (t3 tier)")
    ap.add_argument("--target",
                    help="absolute target project root (t3 tier)")
    ap.add_argument("--repo", help="absolute git repo root (sdr tier)")
    ap.add_argument("--base", help="base ref (sdr tier)")
    ap.add_argument("--branch",
                    help="branch ref (sdr tier; empty = current branch)")
    ap.add_argument("--checkpoints",
                    help="checkpoint/marker dir (all tiers; forwarded to the "
                         "enumerator)")
    ap.add_argument("--inputs-dir",
                    help="per-unit input dir (all tiers; task files land "
                         "here, same layout as the dispatcher's audit copies)")
    ap.add_argument("--retry-failed", action="store_true",
                    help="include units whose .failed marker exists "
                         "(forwarded as the enumerator's --include-failed)")
    ap.add_argument("--template", metavar="<tier-task.md>",
                    help="task template override (default: the sibling "
                         "prompts/fragments/fanout/<tier>-task.md of this "
                         "install)")
    ap.add_argument("--pack-bytes", type=int, default=None, metavar="B",
                    help="t1 ONLY: forward list_clusters --pack-bytes "
                         "(small-cluster packing, opt-in quota amortization; "
                         "pack pending units carry the same path fields, so "
                         "everything downstream is pack-transparent). Refused "
                         "on every other tier (exit 2)")
    ap.add_argument("--pack-max", type=int, default=None, metavar="N",
                    help="t1 ONLY: forward list_clusters --pack-max (per-pack "
                         "member cap, default 8; requires --pack-bytes)")
    ap.add_argument("--wave-size", type=int, metavar="N",
                    help="concurrency override for the wave split (default: "
                         "env-profile native_concurrency, else 3; still capped "
                         "by the profile quota arithmetic)")
    ap.add_argument("--profile", metavar="<abs-project>",
                    help="project root holding .mgh/env-profile.json "
                         "(dispatch form / native concurrency / quota; "
                         "malformed profile => exit 2)")
    ap.add_argument("--check", action="store_true",
                    help="zero-repair validation of the existing plan "
                         "artifacts (byte-for-byte re-materialization "
                         "compare, unit set vs current pending, anchor tree, "
                         "placeholders, short-id invariants; violations => "
                         "exit 2 + re-materialize recipe)")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    tier = fr.TIERS[args.tier]

    # t1-only pack passthrough (closed set: any pack flag on another tier, or
    # --pack-max without --pack-bytes, is a misuse). Forwarded to the tier's
    # own enumerator flags via a LOCAL list_args wrapper — the dispatcher's
    # tier table stays byte-identical.
    pack_flags: list[str] = []
    if args.pack_bytes is not None or args.pack_max is not None:
        if args.tier != "t1":
            _eprint(f"error: --pack-bytes/--pack-max are t1-only flags "
                    f"(got --tier {args.tier})")
            return 2
        if args.pack_bytes is None or args.pack_bytes <= 0:
            _eprint("error: --pack-bytes must be a positive integer (and is "
                    "required when any pack flag is passed)")
            return 2
        pack_flags = ["--pack-bytes", str(args.pack_bytes)]
        if args.pack_max is not None:
            if args.pack_max <= 0:
                _eprint(f"error: --pack-max must be a positive integer "
                        f"(got {args.pack_max})")
                return 2
            pack_flags += ["--pack-max", str(args.pack_max)]
    if pack_flags:
        base_list_args = tier["list_args"]
        tier = dict(tier)
        tier["list_args"] = lambda a, _base=base_list_args, _pf=list(pack_flags): \
            _base(a) + _pf

    # closed-set validation: every required tier artifact flag MUST be present
    missing = [f"--{a.replace('_', '-')}" for a in tier["required_args"]
               if not getattr(args, a, None)]
    if missing:
        _eprint(f"error: --tier {args.tier} requires {', '.join(missing)} "
                f"(got none); re-run with the tier's artifact flags — see "
                f"--help for the per-tier call shapes")
        return 2

    # plan-path re-anchoring — the SAME anchor derivation the dispatcher's
    # main() applies (sdr: <checkpoints>/../grouping.json; t2/scout-merge:
    # <init-dir>/run_config.json; others: the plan artifact itself). The plan
    # artifact's parent is the run dir where native_plan.json lands.
    plan_raw = getattr(args, tier["plan_arg"], None)
    checkpoints = Path(args.checkpoints) if args.checkpoints else None
    inputs_dir = Path(args.inputs_dir) if args.inputs_dir else None
    plan_path = Path(plan_raw) if plan_raw else None
    if plan_path is not None and tier["list_script"] == "diff_group.py":
        anchor = checkpoints.parent if checkpoints is not None else plan_path
        plan_path = (anchor / "grouping.json").resolve()
    if plan_path is not None and tier["list_script"] == "plan_aggregate.py":
        plan_path = (plan_path / "run_config.json").resolve()

    if not plan_path.is_file():
        _eprint(f"error: {tier['plan_arg'].replace('_', '-')} artifact not "
                f"found: {plan_path}")
        return 1
    plan_path = plan_path.resolve()
    inputs_dir = (inputs_dir.resolve() if inputs_dir is not None else None)
    # the plan lands NEXT TO the (re-anchored) plan artifact — never on it;
    # aggregate tiers carry their tier-suffixed filename (never overwrite a
    # sibling layer's plan)
    plan_out = plan_path.parent / plan_filename(args.tier)

    listing = fr._list_pending(tier, args)

    # Zero-dispatch invariant (t2 / scout-merge): needs_reduce=false means the
    # aggregate fits one request — the single-context stage is the
    # orchestrator's ordinary subagent call and NO plan artifact is written
    # ("fits => do not dispatch" outranks "switch form"). Zero writes, exit 0.
    if args.tier in ("t2", "scout-merge") and listing.get("needs_reduce") is False:
        summary = {"tool": TOOL_NAME, "tier": args.tier,
                   "agent": NATIVE_AGENTS[args.tier],
                   "repo": listing.get("repo") or "",
                   "units_total": 0, "waves": 0, "wave_size": 0,
                   "wave_size_source": "concurrency",
                   "plan_path": str(plan_out), "inputs_dir": str(inputs_dir),
                   "note": ("aggregate input <= budget — single-context path, "
                            "zero units to dispatch; no plan artifact is "
                            "written (the single-context stage runs as the "
                            "orchestrator's ordinary subagent call)")}
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    if args.check:
        return _check_mode(tier, args.tier, args, listing, inputs_dir,
                           plan_out)

    body, tasks = _compute(tier, args.tier, args, listing, inputs_dir,
                           plan_path)
    _materialize(plan_out, body, tasks)
    summary = {"tool": TOOL_NAME, "tier": args.tier,
               "agent": NATIVE_AGENTS[args.tier],
               "repo": body["repo"], "units_total": body["units_total"],
               "waves": len(body["waves"]), "wave_size": body["wave_size"],
               "wave_size_source": body["wave_size_source"],
               "plan_path": str(plan_out), "inputs_dir": str(inputs_dir)}
    if listing.get("needs_reduce") is False:
        summary["note"] = ("aggregate input <= budget — single-context path, "
                           "zero units to dispatch")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
