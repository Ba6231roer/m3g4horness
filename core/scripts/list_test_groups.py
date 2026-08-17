#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
list_test_groups — ut-init fan-out work-list enumerator (extract + rules tiers).

The single sanctioned work-list primitive for /mgh-ut-init (mirrors init's
list_clusters / list_rule_jobs). Two tiers:

  --tier extract — reads classify's `test_groups.json`, picks a REPRESENTATIVE sample
    of member files per group (uniform groups -> `--sample-uniform`, hetero -> more via
    `--sample-hetero`), materializes `inputs/extract/<group>.input.json` (group record +
    sampled file contents, bounded by `--max-unit-bytes`), and emits a pending[] item
    per group with absolute `input_path` / `checkpoint_path` / `done_marker` /
    `failed_marker` (the orchestrator passes them VERBATIM to the ut-extract subagent).

  --tier rules — reads `test_rules_inventory.json`, enumerates distinct convention
    categories, materializes `inputs/rules/<category>.input.json` (that category's full
    rules), and emits a pending[] item per category with `rule_path` (claude:
    <target>/.claude/rules/test-<cat>.md; opencode: <target>/docs/test-conventions/<cat>.md)
    + `done_marker` / `failed_marker`.

Every emitted path is `Path.resolve()` ABSOLUTE (safe for any subagent cwd, incl.
Windows drive-relative); NEVER template `<target>/<id>`. Sampling is deterministic
(sorted members, first-N). Exit codes (R5.3b): 0 ok (incl. empty groups) · 1 input
missing/malformed · 2 misuse. stdout=JSON / stderr=progress strictly split; no TTY.
Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate this script's dir (self-contained family, R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_MAX_UNIT_BYTES = 192 * 1024      # 192KB
DEFAULT_ORCH_BUDGET_BYTES = 64 * 1024    # 64KB
DEFAULT_SAMPLE_UNIFORM = 4
DEFAULT_SAMPLE_HETERO = 8


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
    """Filesystem-safe encoding for input/checkpoint FILENAMES. Group ids / category
    names may carry `::` (NTFS Alternate-Data-Stream separator -> write fails on Windows)."""
    return unit_id.replace("/", "_").replace("\\", "_").replace(":", "_")


def _shrink_page(page: list, orch_budget: int):
    if orch_budget <= 0 or not page:
        return page, len(page), False
    eff = len(page)
    while eff > 1 and _byte_len(page[:eff]) > orch_budget:
        eff -= 1
    return page[:eff], eff, eff < len(page)


def _paths(checkpoints_dir: Path, unit_id: str):
    base = (checkpoints_dir / f"{_safe_name(unit_id)}.json")
    return (str(base),
            str(base.with_name(base.name + ".done")),
            str(base.with_name(base.name + ".failed")))


def _load_json(path: Path, label: str):
    if not path.is_file():
        print(f"error: {label} not found: {path}", file=sys.stderr)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed {label}: {e}", file=sys.stderr)
        return None


def _unit_of_record(marker: Path):
    """Canonical unit id from the sibling record / marker body, falling back to the
    safe-encoded filename stem. Group ids / categories may carry `::` (filenames are
    `_safe_name`-encoded, so the stem NEVER matches the canonical id for those)."""
    try:
        body = json.loads(marker.read_text(encoding="utf-8"))
        if isinstance(body, dict) and body.get("unit"):
            return body["unit"]
    except (OSError, ValueError):
        pass
    return None


def _done_ids(checkpoints_dir: Path, pattern: str) -> set:
    if not checkpoints_dir.is_dir():
        return set()
    out = set()
    for m in checkpoints_dir.glob(pattern):
        unit = _unit_of_record(m)
        if unit is not None:
            out.add(unit)
            continue
        # fallback: sibling record <id>.json (canonical `unit` field) then filename stem.
        rec = m.with_suffix("")  # "<id>.json.done" -> "<id>.json"
        if rec.is_file():
            try:
                body = json.loads(rec.read_text(encoding="utf-8"))
                if isinstance(body, dict) and body.get("unit"):
                    out.add(body["unit"])
                    continue
            except (OSError, ValueError):
                pass
        stem = m.name
        for suf in (".json.done",):
            if stem.endswith(suf):
                stem = stem[: -len(suf)]
        out.add(stem)
    return out


def _failed_ids(checkpoints_dir: Path, pattern: str) -> set:
    if not checkpoints_dir.is_dir():
        return set()
    out = set()
    for m in checkpoints_dir.glob(pattern):
        unit = _unit_of_record(m)
        if unit is not None:
            out.add(unit)
            continue
        stem = m.name
        if stem.endswith(".json.failed"):
            stem = stem[: -len(".json.failed")]
        out.add(stem)
    return out


# ---------------------------------------------------------------- extract tier
def _sample_files(group: dict, sample_uniform: int, sample_hetero: int):
    """Deterministic representative sample of a group's members (sorted, first-N)."""
    members = sorted(group.get("members") or [])
    if group.get("uniformity") == "hetero":
        return members[:max(sample_hetero, sample_uniform)]
    return members[:max(sample_uniform, 1)]


def _materialize_extract(inputs_dir: Path, group: dict, sample: list, repo: Path,
                         max_unit_bytes: int):
    """Build `inputs/extract/<group>.input.json` (group record + sampled contents), trimming
    the sample to fit max_unit_bytes. Returns (unit_id, input_path, bytes, oversize)."""
    unit_id = group.get("id") or group.get("layer") or "unknown"
    base = {
        "group_id": unit_id,
        "repo": str(repo),
        "layer": group.get("layer"),
        "family": group.get("family"),
        "uniformity": group.get("uniformity"),
        "assert_density": group.get("assert_density"),
        "member_count": group.get("member_count", len(group.get("members") or [])),
        "all_members": sorted(group.get("members") or []),
        "sample": [],
    }
    cur = sample
    while True:
        body = dict(base, sample=[{"file": f, "path": str((repo / f).resolve()),
                                   "content": (repo / f).read_text(encoding="utf-8",
                                                                   errors="replace")}
                                  for f in cur])
        if _byte_len(body) <= max_unit_bytes or len(cur) <= 1:
            break
        cur = cur[: max(len(cur) // 2, 1)]
    inputs_dir.mkdir(parents=True, exist_ok=True)
    path = (inputs_dir / f"{_safe_name(unit_id)}.input.json").resolve()
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    oversize = _byte_len(body) > max_unit_bytes
    return unit_id, str(path), path.stat().st_size, oversize


def _run_extract(args) -> int:
    data = _load_json(Path(args.groups), "test_groups.json")
    if data is None:
        return 1
    if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
        print("error: test_groups.json must be a wrapper {repo,groups[]}", file=sys.stderr)
        return 1
    repo = Path(data.get("repo") or Path(args.groups).parent.parent).resolve()
    checkpoints_dir = (Path(args.checkpoints).resolve() if args.checkpoints
                       else (Path(args.groups).parent / "checkpoints" / "extract").resolve())
    inputs_dir = Path(args.materialize).resolve() if args.materialize else None

    done = _done_ids(checkpoints_dir, "*.json.done")
    failed = _failed_ids(checkpoints_dir, "*.json.failed")
    all_units, done_count = [], 0
    for g in data["groups"]:
        if not isinstance(g, dict) or not g.get("id"):
            continue
        uid = g["id"]
        cp, dm, fm = _paths(checkpoints_dir, uid)
        if uid in failed:
            continue
        if uid in done:
            done_count += 1
            continue
        item = {
            "group_id": uid,
            "layer": g.get("layer"),
            "family": g.get("family"),
            "uniformity": g.get("uniformity"),
            "member_count": g.get("member_count", len(g.get("members") or [])),
            "checkpoint_path": cp, "done_marker": dm, "failed_marker": fm,
            "slice_dir": str((checkpoints_dir.parent.parent / "slices" / "extract"
                              / _safe_name(uid)).resolve()),
        }
        # pre-create the slice dir (chunk_sources.py writes into it; it does not mkdir itself).
        Path(item["slice_dir"]).mkdir(parents=True, exist_ok=True)
        if inputs_dir:
            sample = _sample_files(g, args.sample_uniform, args.sample_hetero)
            if sample:
                _uid, ipath, nbytes, oversize = _materialize_extract(
                    inputs_dir, g, sample, repo, args.max_unit_bytes)
                item["input_path"] = ipath
                item["bytes"] = nbytes
                item["oversize"] = oversize
                item["sample_size"] = len(sample)
                if oversize:
                    print(f"warn: group {uid} sample oversize (> {args.max_unit_bytes}B); "
                          f"recipe: slice big files via chunk_sources.py (never whole-feed)",
                          file=sys.stderr)
            else:
                item["input_path"] = None
                item["bytes"] = 0
                item["oversize"] = False
                item["sample_size"] = 0
        all_units.append(item)

    req_limit = args.limit if args.limit is not None else len(all_units)
    page = all_units[args.offset: args.offset + max(0, req_limit)]
    page, eff, shrunk = _shrink_page(page, args.orch_budget_bytes)
    total = len(data["groups"])
    result = {
        "tier": "extract", "repo": str(repo), "total": total, "done": done_count,
        "failed": len(failed), "pending": page, "offset": args.offset,
        "limit": req_limit, "effective_limit": eff, "shrunk": shrunk,
    }
    print(f"[list_test_groups] extract tier: {total} group(s), {done_count} done, "
          f"{len(failed)} failed, page offset={args.offset} eff={eff} shrunk={shrunk}",
          file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


# ------------------------------------------------------------------ rules tier
def _rule_path(target_abs: str, rules_dir_abs: str, category: str, fmt: str) -> str:
    if fmt == "claude":
        return f"{target_abs.rstrip('/')}/.claude/rules/test-{category}.md"
    return f"{rules_dir_abs.rstrip('/')}/{category}.md"


def _run_rules(args) -> int:
    data = _load_json(Path(args.inventory), "test_rules_inventory.json")
    if data is None:
        return 1
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        print("error: test_rules_inventory.json must be a wrapper {repo,rules[]}",
              file=sys.stderr)
        return 1
    rules = data["rules"]
    seen = []
    for r in rules:
        if isinstance(r, dict) and r.get("category") and r["category"] not in seen:
            seen.append(r["category"])
    categories = sorted(seen)

    checkpoints_dir = (Path(args.checkpoints).resolve() if args.checkpoints
                       else (Path(args.inventory).parent / "checkpoints" / "rules").resolve())
    inputs_dir = Path(args.materialize).resolve() if args.materialize else None
    target_abs = str(Path(args.target).resolve())
    rules_rel = args.rules_dir or "docs/test-conventions"
    rules_dir_path = Path(rules_rel)
    if not rules_dir_path.is_absolute():
        rules_dir_path = Path(target_abs) / rules_rel
    rules_dir_abs = str(rules_dir_path.resolve())

    by_cat = {}
    if inputs_dir:
        for r in rules:
            if isinstance(r, dict) and r.get("category"):
                by_cat.setdefault(r["category"], []).append(r)

    done = _done_ids(checkpoints_dir, f"*.{args.format}.json.done")
    failed = _failed_ids(checkpoints_dir, f"*.{args.format}.json.failed")
    all_units, failed_count = [], 0
    for cat in categories:
        if cat in failed:
            failed_count += 1
            continue
        dm = str(checkpoints_dir / f"{_safe_name(cat)}.{args.format}.json.done")
        fm = str(checkpoints_dir / f"{_safe_name(cat)}.{args.format}.json.failed")
        if cat in done:
            continue
        item = {
            "category": cat, "format": args.format,
            "rule_path": _rule_path(target_abs, rules_dir_abs, cat, args.format),
            "done_marker": dm, "failed_marker": fm,
        }
        if inputs_dir:
            ipath, nbytes = _write_category_input(inputs_dir, cat, by_cat.get(cat, []),
                                                  repo=str(Path(args.target).resolve()))
            item["input_path"] = ipath
            item["bytes"] = nbytes
            oversize = nbytes > args.max_unit_bytes
            item["oversize"] = oversize
            if oversize:
                print(f"warn: category {cat} oversize ({nbytes}B > {args.max_unit_bytes}B); "
                      f"recipe: advise --scope + --merge to shrink the category (NOT sharded — "
                      f"rulewriter needs the whole-category view)", file=sys.stderr)
        all_units.append(item)

    req_limit = args.limit if args.limit is not None else len(all_units)
    page = all_units[args.offset: args.offset + max(0, req_limit)]
    page, eff, shrunk = _shrink_page(page, args.orch_budget_bytes)
    total = len(categories)
    result = {
        "tier": "rules", "total": total, "done": len(done), "failed": failed_count,
        "pending": page, "format": args.format, "offset": args.offset,
        "limit": req_limit, "effective_limit": eff, "shrunk": shrunk,
    }
    print(f"[list_test_groups] rules tier: {total} category(ies), {len(done)} done, "
          f"{failed_count} failed, page offset={args.offset} eff={eff} shrunk={shrunk}",
          file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _write_category_input(inputs_dir: Path, category: str, records: list, repo: str = ""):
    """Rules-tier materialized input; `repo` (absolute target root) rides top-level as the
    fan-out input anchor (same contract as the extract tier + init's producers)."""
    inputs_dir.mkdir(parents=True, exist_ok=True)
    inp = {"category": category, "repo": repo, "rules": records}
    path = (inputs_dir / f"{_safe_name(category)}.input.json").resolve()
    path.write_text(json.dumps(inp, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path), path.stat().st_size


def main():
    ap = argparse.ArgumentParser(
        description="enumerate /mgh-ut-init fan-out work-list (extract per group / rules per category)")
    ap.add_argument("--tier", choices=["extract", "rules"], default="extract",
                    help="work-list tier (extract: per group from test_groups.json; "
                         "rules: per category from test_rules_inventory.json)")
    # extract tier
    ap.add_argument("--groups", help="test_groups.json (extract tier)")
    ap.add_argument("--sample-uniform", type=int, default=DEFAULT_SAMPLE_UNIFORM,
                    help=f"sample size for uniform groups (default {DEFAULT_SAMPLE_UNIFORM})")
    ap.add_argument("--sample-hetero", type=int, default=DEFAULT_SAMPLE_HETERO,
                    help=f"sample size for heterogeneous groups (default {DEFAULT_SAMPLE_HETERO})")
    # rules tier
    ap.add_argument("--inventory", help="test_rules_inventory.json (rules tier)")
    ap.add_argument("--format", choices=["opencode", "claude"],
                    help="rule format (rules tier; determines rule_path)")
    ap.add_argument("--target", default=".", help="target project root (default .)")
    ap.add_argument("--rules-dir",
                    help="opencode rules detail dir (default <target>/docs/test-conventions); "
                         "opencode rule_path = <abs target>/<rules-dir>/<cat>.md "
                         "(relative resolves against --target; ignored for claude)")
    # shared paging/materialize
    ap.add_argument("--checkpoints", help="tier checkpoint dir (default <init>/checkpoints/<tier>)")
    ap.add_argument("--materialize", metavar="<inputs-dir>",
                    help="write each unit's bounded input to <dir>/<unit>.input.json "
                         "(+ input_path/bytes/oversize; slim envelope if omitted)")
    ap.add_argument("--offset", type=int, default=0, help="page offset (default 0)")
    ap.add_argument("--limit", type=int, default=None, help="max items per page (default all)")
    ap.add_argument("--max-unit-bytes", type=int, default=DEFAULT_MAX_UNIT_BYTES,
                    help=f"per-unit input byte cap (default {DEFAULT_MAX_UNIT_BYTES})")
    ap.add_argument("--orch-budget-bytes", type=int, default=DEFAULT_ORCH_BUDGET_BYTES,
                    help=f"orchestrator single-request page byte cap (default "
                         f"{DEFAULT_ORCH_BUDGET_BYTES}; page auto-tightened + shrunk:true)")
    # Emit JSON / glyphs cleanly regardless of host console codepage (e.g. cp936/gbk).
    # Before parse_args so --help is utf-8 too. No-op on StringIO (in-process tests).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = ap.parse_args()

    if args.offset < 0:
        print("error: --offset must be >= 0", file=sys.stderr)
        return 2
    for label, raw in (("--max-unit-bytes", args.max_unit_bytes),
                       ("--orch-budget-bytes", args.orch_budget_bytes)):
        if _parse_bytes(label, raw) < 0:
            return 2
    for label, raw in (("--sample-uniform", args.sample_uniform),
                       ("--sample-hetero", args.sample_hetero)):
        try:
            if int(raw) < 1:
                print(f"error: {label} must be >= 1 (got {raw})", file=sys.stderr)
                return 2
        except (TypeError, ValueError):
            print(f"error: {label} must be an integer (got {raw!r})", file=sys.stderr)
            return 2

    if args.tier == "extract":
        if not args.groups:
            print("error: --tier extract requires --groups <test_groups.json>", file=sys.stderr)
            return 2
        return _run_extract(args)
    if not args.inventory or not args.format:
        print("error: --tier rules requires --inventory + --format opencode|claude",
              file=sys.stderr)
        return 2
    return _run_rules(args)


if __name__ == "__main__":
    sys.exit(main())
