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
  py resume_state.py --target <dir> [--init-dir <dir>] [--check]

  --target   target project root (default: .). init-dir = <target>/.mgh-init.
  --init-dir explicit .mgh-init dir (overrides <target>/.mgh-init).
  --check    boundary check (R5.9): validate on-disk state self-consistency; exit 0/2.

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"target":"<abs>","format":"...","step":"<enum>","resumable":bool,
   "tiers":{"discover":{done,failed,total},"scout":{..},"t1":{..},"t2":{..},"t3":{..},"t4":{..}},
   "next_action":{"kind":"bash|subagent|done","desc":"...","absolute_paths":["<abs>",...]},
   "notes":["..."]}

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
--check self-consistency violation (incl. a unit carrying BOTH .done and .failed). Read-only,
idempotent, no TTY.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). resume_state currently has no sibling import,
# but the guard keeps it in the self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _load_json(path: Path):
    """Read + parse JSON; returns (obj, None) or (None, err_str)."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except OSError as e:
        return None, f"unreadable: {e}"
    except ValueError as e:
        return None, f"malformed JSON: {e}"


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


def _next(kind: str, desc: str, paths) -> dict:
    return {"kind": kind, "desc": desc, "absolute_paths": [str(p) for p in paths]}


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

    tiers = {
        "discover": {"done": 1 if discover_done else 0, "failed": 0, "total": 1},
        "scout": {"done": scout_done_count if not no_scout else 0,
                  "failed": scout_failed_count if not no_scout else 0,
                  "total": scout_total if not no_scout else 0},
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
    elif (not no_scout) and not _scout_complete(init_dir, scout_plan, scout_candidates,
                                                candidates, scout_total, scout_terminal_count):
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
    }
    return state, None


def _empty_tiers() -> dict:
    z = {"done": 0, "failed": 0, "total": 0}
    return {k: dict(z) for k in ("discover", "scout", "t1", "t2", "t3", "t4")}


def _scout_complete(init_dir, scout_plan, scout_candidates, candidates,
                    scout_total, scout_terminal_count) -> bool:
    """Scout tier fully done = plan exists AND (0 batches OR (scout_candidates + merge.done +
    fold-in all done)). `scout_terminal_count` (done+failed reader batches) is accepted for
    symmetry with `_scout_step` but not used here — completion is gated on the merge/fold-in
    artifacts, not the reader-batch count."""
    if not scout_plan.is_file():
        return False
    if scout_total == 0:
        return True  # nothing to scout
    if not (scout_candidates.is_file() and _scout_merge_done(init_dir)):
        return False
    return _foldin_done(candidates)


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
    """R5.9 self-consistency validation. Returns {ok, violations[]}; caller exits 0/2."""
    violations = []
    cfg, recipe = _run_config(init_dir)
    if cfg is None:
        return {"ok": False, "violations": [{"issue": recipe}]}
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
    return {"ok": not violations, "violations": violations}


def main():
    ap = argparse.ArgumentParser(
        description="derive /mgh-init current step + next action purely from disk (re-entrant)")
    ap.add_argument("--target", default=".", help="target project root (default .)")
    ap.add_argument("--init-dir", help="explicit .mgh-init dir (default <target>/.mgh-init)")
    ap.add_argument("--check", action="store_true",
                    help="boundary check (R5.9): validate on-disk state self-consistency, exit 0/2")
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
        init_dir = (Path(args.target).resolve() / ".mgh-init").resolve()
    if not init_dir.is_dir():
        print(f"error: init-dir not found: {init_dir} (run /mgh-init first)", file=sys.stderr)
        return 1

    if args.check:
        result = check(init_dir)
        print(f"[resume_state --check] {init_dir}: "
              f"{'OK' if result['ok'] else str(len(result['violations'])) + ' violation(s)'}",
              file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 2

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
