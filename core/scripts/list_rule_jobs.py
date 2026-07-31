#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
list_rule_jobs — deterministic T3 work-list producer for /mgh-init.

Reads `controls_inventory.json` (categories from controls[]) and the T3 checkpoint dir,
then prints the authoritative per-category pending work-list as JSON on stdout. Closes
the fan-out asymmetry: T1 has `list_clusters.py`, scout has `list_scout_batches.py`, T3
has this. Replaces hand-rolled `py -c "import json..."` introspection of the inventory
(R5.2).

Per-unit input materialization (`--materialize`, request-context-budget): each category's
COMPLETE controls are written to `<dir>/<category>.input.json`; `pending[]` carries
`input_path`/`bytes`/`oversize`. The orchestrator passes `input_path` verbatim;
`init-rulewriter` reads its own bounded file (NEVER the whole `controls_inventory.json`).
A category is NEVER sharded (rulewriter needs the whole-category view); oversize
categories are flagged + a recipe advises `--scope`+`--merge`.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_rule_jobs.py --inventory <controls_inventory.json>
       --format opencode|claude [--checkpoints <t3-dir>] [--target <dir>] [--rules-dir <dir>]
       [--materialize <inputs-dir>] [--offset N] [--limit N]
       [--max-unit-bytes B] [--orch-budget-bytes B]

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"total": N, "done": M, "failed": F, "pending": [<RuleJobLite>, ...], "format": "...",
   "offset": 0, "limit": K, "effective_limit": k, "shrunk": false}
  - pending[] item: {category, format, rule_path, done_marker, failed_marker, input_path, bytes, oversize}
  - failed     = #confirmed-failed categories (`.failed` marker; terminal, excluded from
                 pending, NOT retried on --resume; done+failed+pending = total). Crash with
                 no `failed` ack → no marker → category stays pending.
  - input_path = ABSOLUTE per-category input file (rulewriter reads this).
  - rule_path  = ABSOLUTE (claude -> <abs target>/.claude/rules/security-<cat>.md;
                 opencode -> <abs target>/<rules-dir>/<cat>.md).
  - failed_marker = ABSOLUTE `<abs checkpoints>/<cat>.<fmt>.json.failed` (body
                 {unit,reason,tier} written by the orchestrator on a `failed` ack).
  - oversize   = category input bytes > --max-unit-bytes (flagged + recipe; NOT sharded).

Exit codes (R5.3b): 0 ok (incl. empty inventory) · 1 inventory missing/malformed ·
2 misuse (argparse / bad budget). Idempotent, no TTY.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). list_rule_jobs currently has no sibling
# import, but the guard keeps it in the self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_MAX_UNIT_BYTES = 192 * 1024    # 192KB
DEFAULT_ORCH_BUDGET_BYTES = 64 * 1024  # 64KB


def _parse_bytes(label: str, raw) -> int:
    try:
        v = int(raw)
    except (TypeError, ValueError):
        print(f"error: {label} must be a non-negative integer (got {raw!r})", file=sys.stderr)
        return -1
    if v < 0:
        print(f"error: {label} must be >= 0 (got {v})", file=sys.stderr)
        return -1
    return v


def _byte_len(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _safe_name(unit_id: str) -> str:
    """Filesystem-safe input filename (category names are slugs, but guard anyway)."""
    return unit_id.replace("/", "_").replace("\\", "_").replace(":", "_")


def _rule_path(target: str, rules_dir_abs: str, category: str, fmt: str) -> str:
    """Absolute rule output path for one category.
    claude  -> <abs target>/.claude/rules/security-<cat>.md
    opencode-> <abs rules-dir>/<cat>.md  (rules-dir resolved against target)
    """
    if fmt == "claude":
        return f"{target.rstrip('/')}/.claude/rules/security-{category}.md"
    return f"{rules_dir_abs.rstrip('/')}/{category}.md"


def _done_categories(checkpoints_dir: Path, fmt: str):
    """Completed categories by scanning `<category>.<format>.json.done` markers."""
    done = set()
    if not checkpoints_dir.is_dir():
        return done
    suffix = f".{fmt}.json.done"
    for marker in sorted(checkpoints_dir.glob(f"*.{fmt}.json.done")):
        name = marker.name
        if not name.endswith(suffix):
            continue
        cat = name[: -len(suffix)]  # strip ".<fmt>.json.done" -> <category>
        done.add(cat)
    return done


def _failed_categories(checkpoints_dir: Path, fmt: str):
    """TERMINAL-FAILED categories (confirmed failure; excluded from `pending`, NOT retried
    on `--resume`). Marker = `<category>.<fmt>.json.failed` (sibling of `.done`); the
    orchestrator writes its body `{unit,reason,tier}` on a `failed` ack — `unit` is the
    category, read in-body (covers the no-record-body failure case); falls back to the
    filename stem (categories are clean slugs, so stem derivation is reliable). A crash
    with no `failed` ack leaves no marker → category stays pending and IS retried
    (crash ≠ confirmed terminal failure)."""
    failed = set()
    if not checkpoints_dir.is_dir():
        return failed
    suffix = f".{fmt}.json.failed"
    for marker in sorted(checkpoints_dir.glob(f"*.{fmt}.json.failed")):
        name = marker.name
        if not name.endswith(suffix):
            continue
        cat = None
        try:
            body = json.loads(marker.read_text(encoding="utf-8"))
            if isinstance(body, dict):
                cat = body.get("unit") or None
        except (OSError, ValueError):
            cat = None
        if not cat:
            cat = name[: -len(suffix)]  # strip ".<fmt>.json.failed" -> <category>
        failed.add(cat)
    return failed


def _write_category_input(inputs_dir: Path, category: str, controls: list):
    """Write `<dir>/<category>.input.json` (this category's full controls); idempotent.
    Returns (abs input_path, file bytes)."""
    inputs_dir.mkdir(parents=True, exist_ok=True)
    inp = {"category": category, "controls": controls}
    path = (inputs_dir / f"{_safe_name(category)}.input.json").resolve()
    path.write_text(json.dumps(inp, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path), path.stat().st_size


def _shrink_page(page: list, orch_budget: int):
    if orch_budget <= 0 or not page:
        return page, len(page), False
    eff = len(page)
    while eff > 1 and _byte_len(page[:eff]) > orch_budget:
        eff -= 1
    return page[:eff], eff, eff < len(page)


def main():
    ap = argparse.ArgumentParser(
        description="list pending T3 rule jobs from controls_inventory.json (deterministic work-list)")
    ap.add_argument("--inventory", required=True,
                    help="path to controls_inventory.json ({format, controls[]})")
    ap.add_argument("--format", required=True, choices=["opencode", "claude"],
                    help="rule format (determines rule_path; also the run's --format)")
    ap.add_argument("--checkpoints",
                    help="T3 checkpoint dir (default: <inventory>/../checkpoints/t3)")
    ap.add_argument("--target", default=".",
                    help="target project root for rule_path (default .)")
    ap.add_argument("--rules-dir",
                    help="opencode rules detail dir (default <target>/docs/security-controls); "
                         "opencode rule_path = <abs target>/<rules-dir>/<cat>.md "
                         "(relative paths resolve against --target; ignored for claude)")
    ap.add_argument("--materialize", metavar="<inputs-dir>",
                    help="write each category's complete controls to <dir>/<category>.input.json "
                         "(+ input_path/bytes/oversize; backward-compat lite shell if omitted)")
    ap.add_argument("--offset", type=int, default=0, help="page offset (default 0)")
    ap.add_argument("--limit", type=int, default=None, help="max items per page (default: all)")
    ap.add_argument("--max-unit-bytes", type=int, default=DEFAULT_MAX_UNIT_BYTES,
                    help=f"per-category input byte cap (default {DEFAULT_MAX_UNIT_BYTES}; "
                         f"oversize categories flagged + recipe, NOT sharded)")
    ap.add_argument("--orch-budget-bytes", type=int, default=DEFAULT_ORCH_BUDGET_BYTES,
                    help=f"orchestrator single-request page byte cap (default "
                         f"{DEFAULT_ORCH_BUDGET_BYTES}; page auto-tightened + shrunk:true)")
    args = ap.parse_args()

    if args.offset < 0:
        print("error: --offset must be >= 0", file=sys.stderr)
        return 2
    for label, raw in (("--max-unit-bytes", args.max_unit_bytes),
                       ("--orch-budget-bytes", args.orch_budget_bytes)):
        if _parse_bytes(label, raw) < 0:
            return 2

    inv_path = Path(args.inventory)
    if not inv_path.is_file():
        print(f"error: controls_inventory.json not found: {inv_path}", file=sys.stderr)
        return 1
    try:
        inv = json.loads(inv_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed controls_inventory.json: {e}", file=sys.stderr)
        return 1
    if not isinstance(inv, dict) or not isinstance(inv.get("controls"), list):
        print("error: controls_inventory.json must be a wrapper {format, controls[]}",
              file=sys.stderr)
        return 1

    controls = inv["controls"]
    # distinct categories in file order (deterministic), then sorted for stability
    seen = []
    for c in controls:
        if isinstance(c, dict) and c.get("category") and c["category"] not in seen:
            seen.append(c["category"])
    categories = sorted(seen)

    checkpoints_dir = (Path(args.checkpoints).resolve() if args.checkpoints
                       else (inv_path.parent / "checkpoints" / "t3").resolve())
    done = _done_categories(checkpoints_dir, args.format)
    failed = _failed_categories(checkpoints_dir, args.format)
    # controls grouped by category (one pass) for materialization
    by_cat = {}
    if args.materialize:
        for c in controls:
            if isinstance(c, dict) and c.get("category"):
                by_cat.setdefault(c["category"], []).append(c)
    inputs_dir = Path(args.materialize).resolve() if args.materialize else None

    # Resolve target ONCE to an absolute path (FD5): a relative rule_path is unsafe (would
    # resolve to the drive root on a misplaced cwd). rule_path / done_marker are the single
    # authoritative values the orchestrator passes VERBATIM.
    target_abs = str(Path(args.target).resolve())
    rules_rel = args.rules_dir or "docs/security-controls"
    rules_dir_path = Path(rules_rel)
    if not rules_dir_path.is_absolute():
        rules_dir_path = Path(target_abs) / rules_rel
    rules_dir_abs = str(rules_dir_path.resolve())

    all_units = []
    failed_count = 0
    for cat in categories:
        if cat in done:
            continue
        if cat in failed:  # confirmed failure (terminal; NOT retried on --resume)
            failed_count += 1
            continue
        item = {
            "category": cat,
            "format": args.format,
            "rule_path": _rule_path(target_abs, rules_dir_abs, cat, args.format),
            "done_marker": str(checkpoints_dir / f"{cat}.{args.format}.json.done"),
            "failed_marker": str(checkpoints_dir / f"{cat}.{args.format}.json.failed"),
        }
        if args.materialize:
            ipath, nbytes = _write_category_input(inputs_dir, cat, by_cat.get(cat, []))
            oversize = nbytes > args.max_unit_bytes
            if oversize:
                print(f"warn: category {cat} oversize ({nbytes}B > {args.max_unit_bytes}B); "
                      f"recipe: advise --scope + --merge to shrink the category (NOT sharded — "
                      f"rulewriter needs the whole-category view)", file=sys.stderr)
            item["input_path"] = ipath
            item["bytes"] = nbytes
            item["oversize"] = oversize
        all_units.append(item)

    total = len(categories)
    done_count = total - len(all_units) - failed_count
    req_limit = args.limit if args.limit is not None else len(all_units)
    page = all_units[args.offset: args.offset + max(0, req_limit)]
    page, eff, shrunk = _shrink_page(page, args.orch_budget_bytes)
    result = {
        "total": total,
        "done": done_count,
        "failed": failed_count,
        "pending": page,
        "format": args.format,
        "offset": args.offset,
        "limit": req_limit,
        "effective_limit": eff,
        "shrunk": shrunk,
    }
    print(f"controls_inventory.json: {total} category(ies), {done_count} done, "
          f"{failed_count} failed, {len(all_units)} pending; page offset={args.offset} "
          f"eff={eff} shrunk={shrunk} (checkpoints: {checkpoints_dir})", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
