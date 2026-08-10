#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
resume_ut_init_state — re-entrant orchestrator resume-state machine for /mgh-ut-init.

The single sanctioned outlet for the orchestrator reflex "which step am I on / what do I do
next" for ut-init. Derives the pipeline's CURRENT step and EXACT next action PURELY from
on-disk products + `.done`/`.failed` markers + `run_config.json` — independent of any
conversation / session memory. This collapses compact / crash / new-session into ONE
recovery path: read disk state → continue. Copied from init's `resume_state.py` and adapted
to the ut step graph (a「归类 classify」prelude, NO codegraph-resolve step, ut product names);
init's `resume_state.py` is ZERO-changed (its blast radius stays isolated, R5.4).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py resume_ut_init_state.py --target <dir> [--init-dir <dir>] [--run-root <name>] [--check]

  --target   target project root (default: .).
  --init-dir explicit run dir (full path; highest priority).
  --run-root run dir NAME under <target> (default .mgh-ut-init; used when --init-dir absent).
  --check    boundary check (R5.9): validate on-disk state self-consistency; exit 0/2.

  Run-dir resolution priority: --init-dir > <target>/<--run-root> (default
  <target>/.mgh-ut-init).

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"target":"<abs>","format":"...","step":"<enum>","resumable":bool,
   "tiers":{"classify":{done,failed,total},"extract":{..},"synthesize":{..},
            "rules":{..},"assemble":{..},"consistency":{..},"mutators":{..}},
   "next_action":{"kind":"bash|subagent|done","desc":"...","absolute_paths":["<abs>",...]},
   "notes":["..."],
   "sampling":{"uniform_sample":N,"hetero_sample":N,"subsplit_threshold":F}}

step ∈ not-started|classify|extract|synthesize|rules|assemble|consistency|mutators|done.
The blocking sequence is classify→extract→synthesize→rules→assemble→consistency→mutators→done.
The fan-out tiers (extract per layer-group, rules per convention-category) are "complete
enough to proceed" when `done + failed >= total` (a `.failed` unit is terminal — confirmed
failure, NOT retried on --resume, NOT blocking). classify/synthesize/assemble/mutators carry
`failed: 0` (not applicable). Any non-zero `failed` is surfaced in `notes[]` (advisory).
next_action.absolute_paths are Path.resolve() absolute values reusing the same resolution
list_test_groups.py emits (NEVER invented / templated). `run_config.json` missing/unparseable
→ exit 2 + stderr recipe (re-run /mgh-ut-init --<flags>); NEVER silently guess the step graph.
The sampling budget persisted in `run_config.json` (`uniform_sample`/`hetero_sample`/
`subsplit_threshold`) is read back so `--resume` does NOT silently re-default it: the extract
tier `next_action` carries `--sample-uniform`/`--sample-hetero` and the state surfaces `sampling`.

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
# host-agent invocation (direct `py`/`python`). (R5.3a self-contained family.)
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
                      "`/mgh-ut-init --<flags>` to rebuild it (NEVER guess the step graph).")
    cfg, err = _load_json(rc)
    if cfg is None or not isinstance(cfg, dict):
        return None, (f"run_config.json {err} — re-run `/mgh-ut-init --<flags>` to rebuild it "
                      f"(NEVER guess the step graph).")
    return cfg, None


def _count_markers(checkpoints_dir: Path, glob: str) -> int:
    """Count marker files under checkpoints_dir matching glob (`*.json.done` or
    `*.json.failed`)."""
    if not checkpoints_dir.is_dir():
        return 0
    return len(list(checkpoints_dir.glob(glob)))


def _marker_exists(*candidates: Path) -> bool:
    return any(p.is_file() for p in candidates)


def _both_marker_violations(cp: Path, label: str) -> list:
    """A unit carrying BOTH `<stem>.done` and `<stem>.failed` is an ambiguous terminal
    state — e.g. a subagent acked `failed` after already touching `.done`, or the
    orchestrator wrote `.failed` for a unit that later succeeded. Returns one violation
    dict per offending unit."""
    out = []
    if not cp.is_dir():
        return out
    for d in sorted(cp.glob("*.json.done")):
        sibling = d.parent / (d.stem + ".failed")
        if sibling.is_file():
            out.append({"issue": f"{label}: ambiguous terminal — both {d.name} and "
                                  f"{sibling.name} exist for one unit (delete one to resolve)"})
    return out


def _marker_unit(marker: Path):
    """Canonical unit id from a marker: a `.failed` marker carries {unit,...} in-body; a
    `.done` marker's sibling record `<id>.json` carries the canonical `unit` field (the
    filename is `_safe_name`-encoded and may NOT match a `::`-containing group id)."""
    try:
        body = json.loads(marker.read_text(encoding="utf-8"))
        if isinstance(body, dict) and body.get("unit"):
            return body["unit"]
    except (OSError, ValueError):
        pass
    rec = marker.with_suffix("")
    try:
        body = json.loads(rec.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(body, dict) and body.get("unit"):
        return body["unit"]
    return None


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
    skip_consistency = bool(cfg.get("skip_consistency"))
    # Read back the sampling budget persisted by write_ut_runconfig so --resume does NOT
    # silently re-default it (run_config.json is the single source of start-state intent).
    # Absent on a legacy/partial run_config -> None (degrade; never guess, never block).
    samp = cfg.get("sampling") if isinstance(cfg.get("sampling"), dict) else {}
    uniform_sample = samp.get("uniform_sample")
    hetero_sample = samp.get("hetero_sample")
    subsplit_threshold = samp.get("subsplit_threshold")
    notes = []

    test_groups = init_dir / "test_groups.json"
    inventory = init_dir / "test_rules_inventory.json"
    mutators = init_dir / "default_mutators.json"
    manifest = init_dir / "ut_manifest.json"
    extract_cp = init_dir / "checkpoints" / "extract"
    rules_cp = init_dir / "checkpoints" / "rules"
    assemble_cp = init_dir / "checkpoints" / "assemble"
    consistency_cp = init_dir / "checkpoints" / "consistency"

    # --- tier counts ---
    classify_done = test_groups.is_file()

    extract_total = 0
    if test_groups.is_file():
        tg, err = _load_json(test_groups)
        if not err and isinstance(tg, dict) and isinstance(tg.get("groups"), list):
            extract_total = len(tg["groups"])
    extract_done = _count_markers(extract_cp, "*.json.done")
    extract_failed = _count_markers(extract_cp, "*.json.failed")

    synthesize_done = inventory.is_file()

    rules_total = 0
    if inventory.is_file():
        inv, err = _load_json(inventory)
        if not err and isinstance(inv, dict) and isinstance(inv.get("rules"), list):
            seen = []
            for r in inv["rules"]:
                if isinstance(r, dict) and r.get("category") and r["category"] not in seen:
                    seen.append(r["category"])
            rules_total = len(seen)
    rules_done = _count_markers(rules_cp, "*.json.done")
    rules_failed = _count_markers(rules_cp, "*.json.failed")

    assemble_done = _marker_exists(assemble_cp / ".done", assemble_cp / "assemble.json.done")
    consistency_done = _marker_exists(consistency_cp / ".done",
                                      consistency_cp / "consistency.json.done")
    mutators_done = mutators.is_file()

    tiers = {
        "classify": {"done": 1 if classify_done else 0, "failed": 0, "total": 1},
        "extract": {"done": extract_done, "failed": extract_failed, "total": extract_total},
        "synthesize": {"done": 1 if synthesize_done else 0, "failed": 0, "total": 1},
        "rules": {"done": rules_done, "failed": rules_failed, "total": rules_total},
        "assemble": {"done": 1 if assemble_done else 0, "failed": 0, "total": 1},
        "consistency": {"done": 1 if consistency_done else 0, "failed": 0,
                        "total": 0 if skip_consistency else 1},
        "mutators": {"done": 1 if mutators_done else 0, "failed": 0, "total": 1},
    }

    # --- fan-out failure disclosure (terminal failures; advisory, never a gate) ---
    for tier_name, tier_total in (("extract", extract_total), ("rules", rules_total)):
        failed_n = tiers[tier_name]["failed"]
        if failed_n > 0:
            if tier_total and failed_n > tier_total / 2:
                notes.append(f"WARNING {tier_name}: high failure rate — {failed_n}/{tier_total} "
                             f"units failed (terminal, skipped); review .failed markers before "
                             f"trusting output (advisory, NOT a gate).")
            else:
                notes.append(f"{tier_name}: {failed_n}/{tier_total} units failed (terminal, "
                             f"skipped); see .failed markers for reasons (advisory, non-gating).")

    # --- step resolution (blocking sequence) ---
    if not classify_done:
        step = "classify"
        nxt = _next("bash",
                    "run classify_tests.py --repo <target> --out <init-dir> "
                    "-> test_groups.json",
                    [test_groups])
    elif extract_total and (extract_done + extract_failed) < extract_total:
        step = "extract"
        # carry the read-back sampling budget so the fan-out re-materializes at the same
        # sample sizes; --resume MUST NOT silently re-default uniform/hetero.
        sample_hint = ""
        if isinstance(uniform_sample, int) and isinstance(hetero_sample, int):
            sample_hint = f" --sample-uniform {uniform_sample} --sample-hetero {hetero_sample}"
        nxt = _next("bash",
                    f"fan out ut-extract per pending group via "
                    f"list_test_groups.py --tier extract --materialize{sample_hint}",
                    [test_groups, extract_cp])
    elif not synthesize_done:
        step = "synthesize"
        nxt = _next("subagent",
                    "spawn ut-synthesize (all per-group observations, no raw code) "
                    "-> test_rules_inventory.json",
                    [extract_cp, inventory, init_dir / "checkpoints" / "synthesize"])
    elif rules_total and (rules_done + rules_failed) < rules_total:
        step = "rules"
        nxt = _next("bash",
                    "fan out ut-rulewriter per pending category via "
                    "list_test_groups.py --tier rules --materialize",
                    [inventory, rules_cp])
    elif not assemble_done:
        step = "assemble"
        nxt = _next("bash",
                    "run assemble_test_rules.py --target <target> --format <fmt>, "
                    "then touch checkpoints/assemble/.done",
                    [Path(target), assemble_cp])
    elif (not skip_consistency) and not consistency_done:
        step = "consistency"
        nxt = _next("subagent",
                    "spawn ut-rules-consistency (in-place edits to rule/detail files) "
                    "+ checkpoints/consistency/.done",
                    [rules_cp, consistency_cp])
    elif not mutators_done:
        step = "mutators"
        nxt = _next("bash",
                    "run derive_mutators.py --repo <target> --out <init-dir> "
                    "-> default_mutators.json",
                    [mutators])
    elif manifest.is_file():
        step = "done"
        nxt = _next("done", "pipeline complete — all terminal artifacts present.", [])
    else:
        # all stages done (or consistency skipped) but manifest not yet written
        step = "done"
        tail = " (consistency skipped via --skip-consistency)" if skip_consistency else ""
        nxt = _next("done",
                    f"all stages complete{tail}; finalize: write ut_manifest.json + report.md.",
                    [manifest, init_dir / "report.md"])

    resumable = not (step == "done" and manifest.is_file())
    sampling_out = {}
    if isinstance(uniform_sample, int):
        sampling_out["uniform_sample"] = uniform_sample
    if isinstance(hetero_sample, int):
        sampling_out["hetero_sample"] = hetero_sample
    if isinstance(subsplit_threshold, (int, float)):
        sampling_out["subsplit_threshold"] = subsplit_threshold
    state = {
        "target": target, "format": fmt, "step": step, "resumable": resumable,
        "tiers": tiers, "next_action": nxt, "notes": notes, "sampling": sampling_out,
    }
    return state, None


def _empty_tiers() -> dict:
    z = {"done": 0, "failed": 0, "total": 0}
    return {k: dict(z) for k in ("classify", "extract", "synthesize", "rules",
                                 "assemble", "consistency", "mutators")}


def check(init_dir: Path) -> dict:
    """R5.9 self-consistency validation. Returns {ok, violations[]}; caller exits 0/2."""
    violations = []
    cfg, recipe = _run_config(init_dir)
    if cfg is None:
        return {"ok": False, "violations": [{"issue": recipe}]}
    test_groups = init_dir / "test_groups.json"
    inventory = init_dir / "test_rules_inventory.json"
    extract_cp = init_dir / "checkpoints" / "extract"
    rules_cp = init_dir / "checkpoints" / "rules"
    consistency_cp = init_dir / "checkpoints" / "consistency"

    # synthesize marker without inventory
    if (init_dir / "checkpoints" / "synthesize").is_dir() and \
            any((init_dir / "checkpoints" / "synthesize").glob("*.json.done")) and \
            not inventory.is_file():
        violations.append({"issue": "synthesize .done present but "
                                    "test_rules_inventory.json missing"})
    # extract .done without test_groups
    if extract_cp.is_dir() and any(extract_cp.glob("*.json.done")) and not test_groups.is_file():
        violations.append({"issue": "extract .done marker(s) present but test_groups.json missing"})
    # rules .done without inventory
    if rules_cp.is_dir() and any(rules_cp.glob("*.json.done")) and not inventory.is_file():
        violations.append({"issue": "rules .done marker(s) present but "
                                    "test_rules_inventory.json missing"})
    # consistency .done present but skipped flag (contradiction)
    if cfg.get("skip_consistency") and (consistency_cp / ".done").is_file():
        violations.append({"issue": "skip_consistency=true but consistency .done marker present"})
    # ambiguous terminal: a unit carrying BOTH .done and .failed (fan-out tiers)
    for cp, label in ((extract_cp, "extract"), (rules_cp, "rules")):
        violations.extend(_both_marker_violations(cp, label))
    # extract markers referencing a group not in test_groups.json (marker filenames are
    # _safe_name-encoded, so the canonical group id MUST come from the sibling record).
    if test_groups.is_file():
        tg, err = _load_json(test_groups)
        known = set()
        if not err and isinstance(tg, dict) and isinstance(tg.get("groups"), list):
            known = {g.get("id") for g in tg["groups"] if isinstance(g, dict) and g.get("id")}
        for cp in (extract_cp,):
            if cp.is_dir():
                for m in cp.glob("*.json.done"):
                    unit = _marker_unit(m)
                    if unit is not None and unit not in known:
                        violations.append({"issue": f"extract .done marker for unknown group: "
                                                    f"{unit} (not in test_groups.json)"})
    return {"ok": not violations, "violations": violations}


def main():
    ap = argparse.ArgumentParser(
        description="derive /mgh-ut-init current step + next action purely from disk (re-entrant)")
    ap.add_argument("--target", default=".", help="target project root (default .)")
    ap.add_argument("--init-dir",
                    help="explicit run dir (full path; highest priority, overrides --run-root)")
    ap.add_argument("--run-root", default=".mgh-ut-init",
                    help="run dir NAME under <target> (default .mgh-ut-init; used when --init-dir absent)")
    ap.add_argument("--check", action="store_true",
                    help="boundary check (R5.9): validate on-disk state self-consistency, exit 0/2")
    # Emit JSON / glyphs cleanly regardless of host console codepage (e.g. cp936/gbk).
    # Before parse_args so --help is utf-8 too. No-op on StringIO (in-process tests).
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
        print(f"error: init-dir not found: {init_dir} (run /mgh-ut-init first)", file=sys.stderr)
        return 1

    if args.check:
        result = check(init_dir)
        print(f"[resume_ut_init_state --check] {init_dir}: "
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
    print(f"[resume_ut_init_state] step={state['step']} resumable={state['resumable']} "
          f"tiers={{classify:{state['tiers']['classify']['done']}/{state['tiers']['classify']['total']}, "
          f"extract:{state['tiers']['extract']['done']}/{state['tiers']['extract']['total']}, "
          f"synthesize:{state['tiers']['synthesize']['done']}/{state['tiers']['synthesize']['total']}, "
          f"rules:{state['tiers']['rules']['done']}/{state['tiers']['rules']['total']}, "
          f"assemble:{state['tiers']['assemble']['done']}/{state['tiers']['assemble']['total']}, "
          f"consistency:{state['tiers']['consistency']['done']}/{state['tiers']['consistency']['total']}, "
          f"mutators:{state['tiers']['mutators']['done']}/{state['tiers']['mutators']['total']}}} "
          f"next={state['next_action']['kind']}", file=sys.stderr)
    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
