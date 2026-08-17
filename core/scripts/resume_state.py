#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
resume_state — re-entrant orchestrator resume-state machine for /mgh-init.

The single sanctioned outlet for the orchestrator reflex "which step am I on / what do I do
next". Derives the pipeline's CURRENT step and EXACT next action PURELY from on-disk products
+ `.done` markers + `run_config.json` — independent of any conversation / session memory. This
collapses compact / crash / new-session into ONE recovery path: read disk state → continue.
System-prompt discipline is re-injected by the new session; progress is re-derived from disk,
so a model-summary compaction that drops the orchestrator-discipline prompt no longer diverges
the execution path (the orchestrator never relies on "remembering" the step).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py resume_state.py --target <dir> [--init-dir <dir>] [--run-root <name>] [--check]
       [--invalidate-stale [--dry-run]] [--rearm-sentinel]

  --target   target project root (default: .).
  --init-dir explicit run dir (full path; highest priority).
  --run-root run dir NAME under <target> (default .mgh-init; used when --init-dir absent).
  --check    boundary check (R5.9): validate on-disk state self-consistency; exit 0/2.
  --invalidate-stale
             delete stale downstream t2/t3/t4 aggregate `.done` markers (scout enabled +
             incomplete → those markers were produced from regex-only input); combine
             with --dry-run to preview. Same marker set as the merge_scout fold-in cascade.
  --dry-run  with --invalidate-stale: list the markers that would be removed, delete nothing.

  Run-dir resolution priority: --init-dir > <target>/<--run-root> (default <target>/.mgh-init).
  Default --run-root .mgh-init is byte-equivalent to the prior hard-coded behavior.

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"target":"<abs>","format":"...","step":"<enum>","resumable":bool,
   "tiers":{"discover":{done,failed,total},"scout":{done,failed,total[,merged]},"t1":{..},"t2":{..},"t3":{..},"t4":{..}},
   "next_action":{"kind":"bash|subagent|done","desc":"...","absolute_paths":["<abs>",...]},
   "notes":["..."],
   "discipline_reminders":{"gates":[{id,desc,command,fail_exit}],"path_recipes":[{id,desc,source}],"nevers":["..."]},
   "stage_flow_files":["<abs>",...]}
  tiers.scout carries an ADDITIVE `merged` field (fold-in actual scout candidates merged
  into controls_candidates.json) ONLY when controls_candidates.json::provenance.scout_merged
  exists — scout disabled / fold-in not yet run → omitted (keeps the base shape stable).
  discipline_reminders = the CURRENT step's discipline subset (gate shapes + path recipes +
  applicable NEVER), from the shared static table in discipline_core.py. It is a RESUME
  DERIVED value — NOT persisted to disk (source of truth stays `<target>/.mgh-init/` products
  + `.done`/`.failed` + run_config.json); `done`/`not-started` and unknown steps yield the
  EMPTY structure (field恒存在, shape stable). `--check` (R5.9) does not cover this field.
  stage_flow_files = the CURRENT step's SINGLE per-step stage-flow fragment
  (<mgh-core>/prompts/fragments/init-stage/<step>.md, `Path.resolve()` absolute, Windows
  native) for step ∈ discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge; EMPTY [] for
  `not-started` (bootstrap is loaded by the shell's fresh-run recipe via fixed-path Read of
  `init-stage/bootstrap.md`) and `done` (no further load). NON all-remaining (current step
  only, never the not-started step / never the rest). Also a RESUME DERIVED value — NOT
  persisted to any `<target>/.mgh-init/` file, `--check` does not cover it.
  The orchestrator Reads stage_flow_files[0] to load ONLY the current step's discipline
  (non-co-residency; the file is NOT existence-checked here so an abnormal install surfaces
  naturally as a Read failure, not a silent skip).

--invalidate-stale stdout (R5.3b):
  dry-run: {"invalidate_stale":{"dry_run":true,"markers":["<abs>",...]}}
  real:    {"invalidate_stale":{"dry_run":false,"removed":["<abs>",...]}}

--rearm-sentinel stdout (R5.3b; idempotent):
  {"rearm_sentinel":{"sentinel":"<abs .active>","domain":"mgh-init","target":"<abs>",
                     "out_roots":["<abs>",...]}}

Sentinel existence check (--check, and advisory in the resolve path): a run in progress
(run_config.json present, step != done) with <init-dir>/.active MISSING means the runtime
guard is dormant for the whole run on hosts that do not inherit mid-session env (opencode)
— scripts read-only / subtree confinement silently disabled. --check fails loud (exit 2)
with a re-arm recipe; a done step without the sentinel is NOT a violation (the run has been
torn down; the guard SHOULD be dormant). `--rearm-sentinel` deterministically rewrites the
sentinel from the persisted run_config (target + rules_dir/out-derived out_roots) — the
`/mgh-init --resume` first step MAY invoke it after compaction or a clean stop removed it.

step ∈ not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done. The blocking
sequence is discover→scout→t1→t2→t3→assemble→t4→done; survey/resolve are optional/non-fatal
(surfaced in notes[], never gate progress). Each fan-out tier (scout/t1/t3) is "complete
enough to proceed" when `done + failed >= total` (a `.failed` unit is terminal — confirmed
failure, NOT retried on --resume, NOT blocking); discover/t2/t4 carry `failed: 0` (not
applicable). Any non-zero `failed` is surfaced in `notes[]` (advisory; a rate > half the
tier is a loud WARNING, never a gate). next_action.absolute_paths are Path.resolve()
absolute values reusing the same resolution list_*/describe_artifact emit (NEVER invented /
templated <target>). `run_config.json` missing/unparseable → exit 2 + stderr recipe (re-run
/mgh-init --<flags>); NEVER silently guess the step graph.

Exit codes (R5.3b): 0 ok · 1 init-dir missing/not a dir · 2 misuse / run_config missing /
--check self-consistency violation (incl. a unit carrying BOTH .done and .failed; incl. an
in-progress run whose sentinel .active is missing — guard dormant).
Read-only (except the explicit --invalidate-stale / --rearm-sentinel actions), idempotent,
no TTY.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

# Self-locate this script's dir so the sibling `init_tier` import resolves under any
# cwd / host-agent invocation (direct `py`/`python`) — R5.3a.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Shared deterministic predicates/constants (single source of truth): scout-tier
# completion for the step derivation + stale-marker enumeration for --check /
# --invalidate-stale.
from init_tier import scout_complete, stale_marker_paths  # noqa: E402
# Shared static per-step discipline table (single source of truth, D1): the
# current step's gate shapes / path recipes / applicable NEVER subset, re-derived
# after compaction so the "how to execute THIS step" survives head-summary loss.
from discipline_core import get_discipline  # noqa: E402


def _load_json(path: Path):
    """Read + parse JSON; returns (obj, None) or (None, err_str)."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except OSError as e:
        return None, f"unreadable: {e}"
    except ValueError as e:
        return None, f"malformed JSON: {e}"


def _atomic_write_json(path: Path, obj):
    """Write `<path>.tmp` then `os.replace` (atomic; mirrors write_runconfig)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _derive_out_roots(cfg, init_dir: Path) -> list:
    """Sentinel out_roots[] re-derivation from the persisted run_config (mirror of
    write_runconfig._derive_out_roots): non-default `rules_dir` only — the run_config.json
    path itself IS inside <init-dir> (the run root is already sanctioned), so only a custom
    rules_dir extends the guard allowlist here. Default roots are built into the guard."""
    roots = []
    rd = cfg.get("rules_dir")
    if isinstance(rd, str) and rd.strip():
        target = cfg.get("target") or str(init_dir.parent.resolve())
        defaults = {
            ".mgh-init": str((Path(target) / "docs" / "security-controls").resolve()),
            ".mgh-ut-init": str((Path(target) / "docs" / "test-conventions").resolve()),
        }
        try:
            r = str(Path(rd).resolve())
            if r != defaults.get(".mgh-init"):
                roots.append(r)
        except (OSError, ValueError):
            pass
    return roots


def rearm_sentinel(init_dir: Path, cfg) -> Path:
    """Deterministically rewrite <init-dir>/.active from the persisted run_config (design
    D2): domain from the run root name, target = run_config.target (the authoritative
    persisted root), out_roots re-derived. Atomic + idempotent. Returns the sentinel path."""
    run_root = init_dir.name
    domain = "mgh-ut-init" if run_root == ".mgh-ut-init" else "mgh-init"
    target = cfg.get("target") or str(init_dir.parent.resolve())
    sentinel_path = init_dir / ".active"
    _atomic_write_json(sentinel_path, {
        "domain": domain, "target": target,
        "out_roots": _derive_out_roots(cfg, init_dir), "v": 1,
    })
    return sentinel_path


def _run_config(init_dir: Path):
    """Load run_config.json; returns (cfg, None) or (None, err_recipe)."""
    rc = init_dir / "run_config.json"
    if not rc.is_file():
        return None, ("run_config.json absent — cannot resume statelessly. Re-run "
                      "`/mgh-init --<flags>` to rebuild it (NEVER guess the step graph).")
    cfg, err = _load_json(rc)
    if cfg is None or not isinstance(cfg, dict):
        return None, (f"run_config.json {err} — re-run `/mgh-init --<flags>` to rebuild it "
                      f"(NEVER guess the step graph).")
    return cfg, None


def _count_markers(checkpoints_dir: Path, glob: str, exclude=()) -> int:
    """Count marker files under checkpoints_dir matching glob, excluding any whose stem
    or name is in `exclude`. Generic over the marker suffix: `*.json.done` (completion)
    or `*.json.failed` (terminal failure). For scout, pass exclude=("merge.json",
    "audit.json") to skip the tier-level merge/audit markers (which are not reader batches)."""
    if not checkpoints_dir.is_dir():
        return 0
    n = 0
    for m in checkpoints_dir.glob(glob):
        if m.stem in exclude or m.name in exclude:
            continue
        n += 1
    return n


def _marker_exists(*candidates: Path) -> bool:
    return any(p.is_file() for p in candidates)


def _both_marker_violations(cp: Path, label: str) -> list:
    """A unit carrying BOTH `<stem>.done` and `<stem>.failed` is an ambiguous terminal
    state (D5) — e.g. a subagent acked `failed` after already touching `.done`, or the
    orchestrator wrote `.failed` for a unit that later succeeded. Returns one violation
    dict per offending unit. A `.failed` whose sibling record body is absent is NOT a
    violation (failures may produce no record body); a `.done` without a record body is
    handled by the existing orphan-record check."""
    out = []
    if not cp.is_dir():
        return out
    for d in sorted(cp.glob("*.json.done")):
        # d.stem strips the trailing ".done" → "<id>.json"; its .failed sibling:
        sibling = d.parent / (d.stem + ".failed")
        if sibling.is_file():
            out.append({"issue": f"{label}: ambiguous terminal — both {d.name} and "
                                  f"{sibling.name} exist for one unit (delete one to resolve)"})
    return out


def _t2_done(init_dir: Path) -> bool:
    t2 = init_dir / "checkpoints" / "t2"
    return _marker_exists(t2 / "synthesis.json.done", t2 / ".done")


def _t4_done(init_dir: Path) -> bool:
    t4 = init_dir / "checkpoints" / "t4"
    return _marker_exists(t4 / "consistency.json.done", t4 / ".done")


def _scout_merge_done(init_dir: Path) -> bool:
    return _marker_exists(init_dir / "checkpoints" / "scout" / "merge.json.done")


def _foldin_done(candidates_path: Path) -> bool:
    """merge_scout.py fold-in sets controls_candidates.json::provenance.scout_merged."""
    cd, err = _load_json(candidates_path)
    if err or not isinstance(cd, dict):
        return False
    return isinstance(cd.get("provenance"), dict) and "scout_merged" in cd["provenance"]


def _scout_merged_value(candidates_path: Path):
    """Actual scout candidates merged into controls_candidates.json
    (provenance.scout_merged); None when fold-in never ran (key absent)."""
    cd, err = _load_json(candidates_path)
    if err or not isinstance(cd, dict):
        return None
    prov = cd.get("provenance")
    if not isinstance(prov, dict):
        return None
    return prov.get("scout_merged")


def _next(kind: str, desc: str, paths) -> dict:
    return {"kind": kind, "desc": desc, "absolute_paths": [str(p) for p in paths]}


# Per-step stage-flow fragment dir: `<mgh-core>/prompts/fragments/init-stage/`.
# `__file__` self-locate (R5.3a) makes the path follow the install mirror
# (claude `.claude/mgh-core/` / opencode `.opencode/mgh-core/`) with zero
# host-specific code — the fragment set is mirrored by install.sh `cp -r core/`.
_STAGE_FLOW_DIR = Path(__file__).resolve().parent.parent / "prompts" / "fragments" / "init-stage"
# Step keys that map 1:1 to a per-step fragment file (single source of truth =
# the runtime step enum). not-started (bootstrap) and done are excluded: bootstrap
# is loaded by the shell's fresh-run recipe via fixed-path Read of
# init-stage/bootstrap.md, done has no further load.
_FRAGMENT_STEPS = frozenset({
    "discover", "survey", "scout", "resolve", "t1", "t2", "t3", "assemble",
    "t4", "merge",
})


def _stage_flow_files(step: str) -> list:
    """Current step's single per-step fragment absolute path (Path.resolve()),
    or [] for not-started (bootstrap loaded by the shell's fresh-run recipe via
    fixed-path Read of init-stage/bootstrap.md) / done (no further load). NEVER
    all-remaining, NEVER the not-started step. The file is NOT existence-checked
    (an abnormal install yields an absolute path the orchestrator's Read fails on
    naturally, not a silent skip); stderr advisory is left to the caller."""
    if step not in _FRAGMENT_STEPS:
        return []
    return [str((_STAGE_FLOW_DIR / f"{step}.md").resolve())]


def resolve(init_dir: Path):
    """Build the full state dict from disk. Returns (state, None) or (None, recipe_str)
    when run_config is missing (caller exits 2)."""
    cfg, recipe = _run_config(init_dir)
    if cfg is None:
        return None, recipe

    target = cfg.get("target") or str(init_dir.parent.resolve())
    fmt = cfg.get("format") or "opencode"
    no_scout = bool(cfg.get("no_scout"))
    skip_consistency = bool(cfg.get("skip_consistency"))
    mode = cfg.get("mode") or "normal"
    notes = []

    candidates = init_dir / "controls_candidates.json"
    clusters_p = init_dir / "clusters.json"
    scout_plan = init_dir / "scout_plan.json"
    scout_candidates = init_dir / "scout_candidates.json"
    inventory = init_dir / "controls_inventory.json"
    manifest = init_dir / "init_manifest.json"
    enriched = init_dir / "i1_enriched.json"
    resolved = init_dir / "resolved.json"
    scout_cp = init_dir / "checkpoints" / "scout"
    t1_cp = init_dir / "checkpoints" / "t1"
    t3_cp = init_dir / "checkpoints" / "t3"

    # --- mode: merge short-circuit ---
    if mode == "merge":
        partials = cfg.get("merge_partials_dir") or "<partials-dir>"
        state = {
            "target": target, "format": fmt, "step": "merge", "resumable": True,
            "tiers": _empty_tiers(),
            "next_action": _next("bash",
                f"merge partial inventories from {partials} (evidence-anchor merge) then STOP",
                [Path(target)]),
            "notes": notes,
            "discipline_reminders": get_discipline("merge"),
            "stage_flow_files": _stage_flow_files("merge"),
        }
        return state, None

    # --- tier counts ---
    discover_done = candidates.is_file() and clusters_p.is_file()
    # discover partial: cache/ + scan_progress.json present but final products absent
    discover_partial = (not discover_done) and \
        (init_dir / "cache").is_dir() and (init_dir / "cache" / "scan_progress.json").is_file()

    scout_total = 0
    scout_done_count = 0
    scout_failed_count = 0
    if not no_scout and scout_plan.is_file():
        sp, err = _load_json(scout_plan)
        if not err and isinstance(sp, dict) and isinstance(sp.get("batches"), list):
            scout_total = len(sp["batches"])
    if not no_scout:
        # exclude merge.json/audit.json (tier-level markers, not reader batches)
        scout_done_count = _count_markers(scout_cp, "*.json.done",
                                          exclude=("merge.json", "audit.json"))
        scout_failed_count = _count_markers(scout_cp, "*.json.failed",
                                            exclude=("merge.json", "audit.json"))
    scout_terminal_count = scout_done_count + scout_failed_count  # gates scout tier (D3)

    clusters_total = 0
    if clusters_p.is_file():
        cl, err = _load_json(clusters_p)
        if not err and isinstance(cl, dict) and isinstance(cl.get("clusters"), list):
            clusters_total = len(cl["clusters"])
    t1_done_count = _count_markers(t1_cp, "*.json.done")
    t1_failed_count = _count_markers(t1_cp, "*.json.failed")

    t3_total = 0
    if inventory.is_file():
        inv, err = _load_json(inventory)
        if not err and isinstance(inv, dict) and isinstance(inv.get("controls"), list):
            seen = []
            for c in inv["controls"]:
                if isinstance(c, dict) and c.get("category") and c["category"] not in seen:
                    seen.append(c["category"])
            t3_total = len(seen)
    t3_done_count = _count_markers(t3_cp, f"*.{fmt}.json.done") if inventory.is_file() else 0
    t3_failed_count = _count_markers(t3_cp, f"*.{fmt}.json.failed") if inventory.is_file() else 0

    scout_tier = {"done": scout_done_count if not no_scout else 0,
                  "failed": scout_failed_count if not no_scout else 0,
                  "total": scout_total if not no_scout else 0}
    if not no_scout:
        merged = _scout_merged_value(candidates)
        if merged is not None:
            # additive: only when fold-in actually recorded a merge count (keeps the
            # base {done,failed,total} shape stable when scout is disabled / fold-in
            # not yet run).
            scout_tier["merged"] = merged
    tiers = {
        "discover": {"done": 1 if discover_done else 0, "failed": 0, "total": 1},
        "scout": scout_tier,
        "t1": {"done": t1_done_count, "failed": t1_failed_count, "total": clusters_total},
        "t2": {"done": 1 if _t2_done(init_dir) else 0, "failed": 0, "total": 1},
        "t3": {"done": t3_done_count, "failed": t3_failed_count, "total": t3_total},
        "t4": {"done": 1 if _t4_done(init_dir) else 0, "failed": 0,
               "total": 0 if skip_consistency else 1},
    }

    # --- fan-out failure disclosure (terminal failures; advisory, never a gate) ---
    for tier_name, tier_total in (("scout", scout_total if not no_scout else 0),
                                  ("t1", clusters_total), ("t3", t3_total)):
        failed_n = tiers[tier_name]["failed"]
        if failed_n > 0:
            if tier_total and failed_n > tier_total / 2:
                notes.append(f"WARNING {tier_name}: high failure rate — {failed_n}/{tier_total} "
                             f"units failed (terminal, skipped); review .failed markers before "
                             f"trusting output (advisory, NOT a gate).")
            else:
                notes.append(f"{tier_name}: {failed_n}/{tier_total} units failed (terminal, "
                             f"skipped); see .failed markers for reasons (advisory, non-gating).")

    # --- scout consistency / stale-credential disclosure (advisory; never gates/derives step) ---
    if not no_scout and not scout_complete(init_dir):
        stale = stale_marker_paths(init_dir)
        if stale:
            notes.append("stale credentials: scout incomplete but downstream t2/t3/t4 .done "
                         "exist (regex-only input) — run `resume_state.py --check` then "
                         "`--invalidate-stale` before --resume")
    if not no_scout and scout_total > 0 and scout_terminal_count >= scout_total:
        merged = _scout_merged_value(candidates)
        if merged == 0:
            notes.append(f"scout reviewed {scout_total} batch(es) but merged 0 candidates — "
                         "possible recall gap (advisory, non-gating).")

    # --- optional/non-fatal tier notes (never gate) ---
    if enriched.is_file():
        notes.append("survey: i1_enriched.json present (advisory; non-gating).")
    else:
        notes.append("survey: optional/advisory — i1_enriched.json absent does not block.")
    if not cfg.get("no_codegraph"):
        unresolved_n = 0
        if candidates.is_file():
            cd, err = _load_json(candidates)
            if not err and isinstance(cd, dict):
                unresolved_n = len(cd.get("unresolved") or [])
        if resolved.is_file():
            notes.append("resolve: resolved.json present (codegraph enrichment done).")
        elif unresolved_n:
            notes.append(f"resolve: codegraph=on, unresolved={unresolved_n} — init-resolve "
                         "recommended but optional/non-fatal; T1 proceeds from clusters.json.")
        else:
            notes.append("resolve: codegraph=on, unresolved empty — nothing to resolve.")

    # --- step resolution (blocking sequence) ---
    if not discover_done:
        step = "discover"
        hint = "--resume" if discover_partial else "(fresh)"
        nxt = _next("bash",
                    f"run discover_controls.py --repo <target> --out <init-dir> {hint}",
                    [init_dir, candidates, clusters_p])
        if discover_partial:
            notes.append("discover: partial — cache/scan_progress present; re-dispatch --resume.")
    elif (not no_scout) and not scout_complete(init_dir):
        step, nxt = _scout_step(init_dir, scout_plan, scout_candidates, candidates,
                                clusters_p, scout_cp, scout_total, scout_terminal_count, notes)
    elif clusters_total and (t1_done_count + t1_failed_count) < clusters_total:
        step = "t1"
        nxt = _next("bash",
                    "fan out init-induct per pending cluster via list_clusters.py --materialize",
                    [clusters_p, candidates, t1_cp])
    elif not _t2_done(init_dir) or not inventory.is_file():
        step = "t2"
        budget = ((cfg.get("budgets") or {}).get("max_aggregate_bytes"))
        if budget is not None:
            notes.append(f"t2: if checkpoints/t1 aggregate > {budget}B, run plan_aggregate.py "
                         "--node t2 first (map-reduce); else single-context init-synthesis.")
        nxt = _next("subagent",
                    "spawn init-synthesis (all T1 records, no raw code) -> controls_inventory.json",
                    [t1_cp, inventory, init_dir / "checkpoints" / "t2"])
    elif t3_total and (t3_done_count + t3_failed_count) < t3_total:
        step = "t3"
        nxt = _next("bash",
                    "fan out init-rulewriter per pending category via list_rule_jobs.py --materialize",
                    [inventory, t3_cp])
    elif (not skip_consistency) and not _t4_done(init_dir):
        step = "assemble"
        nxt = _next("bash",
                    "run assemble_rules.py --target <target> --format <fmt>, then spawn "
                    "init-rules-consistency (T4)",
                    [Path(target), init_dir / "checkpoints" / "t4"])
    elif manifest.is_file():
        step = "done"
        nxt = _next("done", "pipeline complete — all terminal artifacts present.", [])
    else:
        # all stages done (or T4 skipped) but manifest not yet written
        step = "done"
        tail = " (T4 skipped via --skip-consistency)" if skip_consistency else ""
        nxt = _next("done",
                    f"all stages complete{tail}; finalize: write init_manifest.json + report.md.",
                    [manifest, init_dir / "report.md"])

    resumable = not (step == "done" and manifest.is_file())
    state = {
        "target": target, "format": fmt, "step": step, "resumable": resumable,
        "tiers": tiers, "next_action": nxt, "notes": notes,
        "discipline_reminders": get_discipline(step),
        "stage_flow_files": _stage_flow_files(step),
    }
    return state, None


def _empty_tiers() -> dict:
    z = {"done": 0, "failed": 0, "total": 0}
    return {k: dict(z) for k in ("discover", "scout", "t1", "t2", "t3", "t4")}


def _scout_step(init_dir, scout_plan, scout_candidates, candidates, clusters_p,
                scout_cp, scout_total, scout_terminal_count, notes) -> tuple:
    if not scout_plan.is_file():
        return "scout", _next("bash",
                              "run plan_scout.py -> scout_plan.json (byte-budget batches)",
                              [scout_plan, scout_cp])
    if scout_total == 0:
        # plan exists, 0 batches: nothing to scout; treat complete (caller re-checks)
        return "scout", _next("bash",
                              "scout_plan has 0 targets — nothing to scout; proceed to T1",
                              [scout_plan])
    if scout_terminal_count < scout_total:
        return "scout", _next("bash",
                              "fan out init-scout readers per pending batch via "
                              "list_scout_batches.py --materialize",
                              [scout_plan, scout_cp])
    # all reader batches done
    if not (scout_candidates.is_file() and _scout_merge_done(init_dir)):
        notes.append("scout: all reader batches .done but scout_candidates.json / merge marker "
                     "absent — MUST run init-scout-merge (NEVER skip to T1 / merge_scout.py).")
        return "scout", _next("subagent",
                              "spawn init-scout-merge (all scout batch records, no raw code) "
                              "-> scout_candidates.json",
                              [scout_cp, scout_candidates,
                               init_dir / "checkpoints" / "scout" / "merge.json.done"])
    # scout_candidates + merge done, but fold-in not yet run
    notes.append("scout: scout_candidates.json present; run merge_scout.py fold-in before T1.")
    return "scout", _next("bash",
                          "run merge_scout.py --candidates .. --scout .. --clusters .. "
                          "(fold scout into controls_candidates.json + clusters.json)",
                          [candidates, scout_candidates, clusters_p])


def check(init_dir: Path) -> dict:
    """R5.9 self-consistency validation. Returns {ok, violations[], notes[]}; caller
    exits 0/2. notes[] carries advisory disclosures (scout reviewed but merged 0)."""
    violations = []
    notes = []
    cfg, recipe = _run_config(init_dir)
    if cfg is None:
        return {"ok": False, "violations": [{"issue": recipe}], "notes": []}
    no_scout = bool(cfg.get("no_scout"))
    candidates = init_dir / "controls_candidates.json"
    clusters_p = init_dir / "clusters.json"
    inventory = init_dir / "controls_inventory.json"
    scout_candidates = init_dir / "scout_candidates.json"
    scout_cp = init_dir / "checkpoints" / "scout"
    t1_cp = init_dir / "checkpoints" / "t1"
    t2_cp = init_dir / "checkpoints" / "t2"
    t3_cp = init_dir / "checkpoints" / "t3"

    # t2 marker without inventory
    if _t2_done(init_dir) and not inventory.is_file():
        violations.append({"issue": "t2 .done present but controls_inventory.json missing"})
    # inventory without t2 marker (T2 produced output but never marked — re-run T2 or touch)
    if inventory.is_file() and not _t2_done(init_dir):
        violations.append({"issue": "controls_inventory.json present but t2 marker absent"})
    # t3 .done without inventory
    if t3_cp.is_dir() and any(t3_cp.glob("*.json.done")) and not inventory.is_file():
        violations.append({"issue": "t3 .done marker(s) present but controls_inventory.json missing"})
    # scout_candidates without merge marker
    if scout_candidates.is_file() and not _scout_merge_done(init_dir):
        violations.append({"issue": "scout_candidates.json present but scout merge marker absent"})
    # orphan t1 .done (marker without sibling record)
    if t1_cp.is_dir():
        for m in sorted(t1_cp.glob("*.json.done")):
            rec = m.with_suffix("")  # strip .done -> <id>.json
            if not rec.is_file():
                violations.append({"issue": f"t1 .done marker without record: {m.name}"})
    # ambiguous terminal: a unit carrying BOTH .done and .failed (D5) — scout reader batches,
    # t1 clusters, t3 categories. (merge.json/audit.json have no .failed sibling in practice.)
    for cp, label in ((scout_cp, "scout"), (t1_cp, "t1"), (t3_cp, "t3")):
        violations.extend(_both_marker_violations(cp, label))
    # discover products inconsistent
    if clusters_p.is_file() != candidates.is_file():
        violations.append({"issue": "discover products inconsistent: controls_candidates.json and "
                                    "clusters.json must both exist or both be absent"})
    # sentinel existence: a run in progress with the guard-activation sentinel missing means
    # the runtime guard is dormant (scripts read-only / subtree confinement silently
    # disabled on hosts that do not inherit mid-session env). Fail loud with a re-arm recipe
    # — NEVER silently continue. A done run without the sentinel is NOT a violation.
    state, _ = resolve(init_dir)
    if state is not None and state.get("step") != "done":
        if not (init_dir / ".active").is_file():
            violations.append({"issue": "run in progress but <init-dir>/.active sentinel "
                                        "missing — the runtime guard is DORMANT (script writes "
                                        "read-only / subtree confinement disabled on opencode); "
                                        "re-arm: `resume_state.py --rearm-sentinel` (or re-run "
                                        "write_runconfig.py), NEVER silently continue"})
    # --- scout consistency + stale-credential checks (scout enabled only) ---
    if not no_scout:
        sp, sp_err = _load_json(init_dir / "scout_plan.json")
        batches = 0
        if not sp_err and isinstance(sp, dict) and isinstance(sp.get("batches"), list):
            batches = len(sp["batches"])
        terminal = (_count_markers(scout_cp, "*.json.done", exclude=("merge.json", "audit.json"))
                    + _count_markers(scout_cp, "*.json.failed", exclude=("merge.json", "audit.json")))
        # stale credentials: scout incomplete but downstream aggregate .done exist
        # (they were produced from regex-only input — resume must not trust them).
        if not scout_complete(init_dir):
            stale = stale_marker_paths(init_dir)
            if stale:
                violations.append({"issue": "scout enabled + incomplete but downstream "
                                            "t2/t3/t4 .done present (stale credentials from "
                                            "regex-only input) — run `resume_state.py "
                                            "--invalidate-stale` (preview: --dry-run) before --resume"})
        # scout contribution consistency: ran all batches but never merged = stranded;
        # merged 0 is disclosed as a note, NOT a gate.
        if batches > 0 and terminal >= batches:
            merged = _scout_merged_value(candidates)
            if merged is None:
                violations.append({"issue": "scout ran all batches but never merged "
                                            "(provenance.scout_merged absent) — stranded; run "
                                            "init-scout-merge + merge_scout fold-in"})
            elif merged == 0:
                notes.append(f"scout reviewed {batches} batch(es) but merged 0 candidates — "
                             "possible recall gap (advisory, not a gate)")
    return {"ok": not violations, "violations": violations, "notes": notes}


def main():
    ap = argparse.ArgumentParser(
        description="derive /mgh-init current step + next action purely from disk (re-entrant)")
    ap.add_argument("--target", default=".", help="target project root (default .)")
    ap.add_argument("--init-dir",
                    help="explicit run dir (full path; highest priority, overrides --run-root)")
    ap.add_argument("--run-root", default=".mgh-init",
                    help="run dir NAME under <target> (default .mgh-init; used when --init-dir absent)")
    ap.add_argument("--check", action="store_true",
                    help="boundary check (R5.9): validate on-disk state self-consistency, exit 0/2")
    ap.add_argument("--invalidate-stale", action="store_true",
                    help="delete stale downstream t2/t3/t4 aggregate .done markers (scout "
                         "enabled + incomplete → regex-only credentials); combine with "
                         "--dry-run to preview (same marker set as merge_scout fold-in)")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --invalidate-stale: list the markers that would be removed, "
                         "delete nothing")
    ap.add_argument("--rearm-sentinel", action="store_true",
                    help="deterministically rewrite <init-dir>/.active from run_config "
                         "(target + rules_dir-derived out_roots); the /mgh-init --resume "
                         "first step after compaction / clean-stop")
    # Emit JSON / glyphs cleanly regardless of host console codepage (e.g. cp936/gbk on
    # Chinese Windows) so stdout JSON parses everywhere. Before parse_args so --help is
    # utf-8 too. No-op on StringIO (in-process tests).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = ap.parse_args()

    if args.init_dir:
        init_dir = Path(args.init_dir).resolve()
    else:
        init_dir = (Path(args.target).resolve() / args.run_root).resolve()
    if not init_dir.is_dir():
        print(f"error: init-dir not found: {init_dir} (run /mgh-init first)", file=sys.stderr)
        return 1

    if args.invalidate_stale:
        markers = stale_marker_paths(init_dir)
        if args.dry_run:
            print(f"[resume_state --invalidate-stale --dry-run] {len(markers)} stale marker(s) "
                  f"would be removed", file=sys.stderr)
            print(json.dumps({"invalidate_stale": {"dry_run": True,
                                                   "markers": [str(p) for p in markers]}},
                             ensure_ascii=False))
            return 0
        removed = []
        for p in markers:
            try:
                p.unlink()
                removed.append(str(p))
            except OSError as e:
                print(f"warn: cannot remove {p}: {e}", file=sys.stderr)
        print(f"[resume_state --invalidate-stale] removed {len(removed)} stale marker(s)",
              file=sys.stderr)
        print(json.dumps({"invalidate_stale": {"dry_run": False, "removed": removed}},
                         ensure_ascii=False))
        return 0

    if args.check:
        result = check(init_dir)
        print(f"[resume_state --check] {init_dir}: "
              f"{'OK' if result['ok'] else str(len(result['violations'])) + ' violation(s)'}",
              file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 2

    if args.rearm_sentinel:
        cfg, recipe = _run_config(init_dir)
        if cfg is None:
            print(f"error: {recipe}", file=sys.stderr)
            return 2
        sp = rearm_sentinel(init_dir, cfg)
        print(f"[resume_state --rearm-sentinel] rewrote {sp}", file=sys.stderr)
        print(json.dumps({"rearm_sentinel": {
            "sentinel": str(sp), "domain": "mgh-ut-init" if init_dir.name == ".mgh-ut-init"
                                            else "mgh-init",
            "target": cfg.get("target") or str(init_dir.parent.resolve()),
            "out_roots": _derive_out_roots(cfg, init_dir)}}, ensure_ascii=False))
        return 0

    state, recipe = resolve(init_dir)
    if state is None:
        # run_config missing/unparseable — NEVER guess the step graph
        print(f"error: {recipe}", file=sys.stderr)
        print(json.dumps({"step": None, "resumable": False,
                          "error": "run_config missing or unparseable"}, ensure_ascii=False))
        return 2
    print(f"[resume_state] step={state['step']} resumable={state['resumable']} "
          f"tiers={{discover:{state['tiers']['discover']['done']}/{state['tiers']['discover']['total']}, "
          f"scout:{state['tiers']['scout']['done']}/{state['tiers']['scout']['total']}, "
          f"t1:{state['tiers']['t1']['done']}/{state['tiers']['t1']['total']}, "
          f"t2:{state['tiers']['t2']['done']}/{state['tiers']['t2']['total']}, "
          f"t3:{state['tiers']['t3']['done']}/{state['tiers']['t3']['total']}, "
          f"t4:{state['tiers']['t4']['done']}/{state['tiers']['t4']['total']}}} "
          f"next={state['next_action']['kind']}", file=sys.stderr)
    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
