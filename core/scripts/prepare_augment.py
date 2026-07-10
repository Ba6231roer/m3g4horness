#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
prepare_augment — deterministic a1 for /mgh-sra: parse an openspec change into a
structured `change_context.json`, signal-1 pre-filter candidate controls from a
mgh-init inventory, load project-level business memory, and enumerate the
per-capability augmentation work-list with ABSOLUTE draft paths.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/re/sys/pathlib). Does NOT
import load_controls / validate_inventory / any sibling command — reads the
inventory with a self-contained json.load + minimal shape check (decoupled).

CLI contract (`--help` is the contract surface, R5.1):
  py prepare_augment.py --change <name> [--rules <path>] [--out <dir>]
                        [--dry-run] [--no-interactive]
  py prepare_augment.py --check <rules-path-or-dir>

  --change <name>   target change (default: newest dir under openspec/changes/)
  --rules <path>    mgh-init controls_inventory.json FILE or its output DIR
                    (e.g. <project>/.mgh-init); auto-discovered when a dir
  --out <dir>       output dir (default: <change-root>/.mgh-sra)
  --dry-run         produce change_context.json + stdout summary only (orchestrator
                    skips the merge steps; flag echoed for the orchestrator)
  --no-interactive  clarification uses default guesses (flag echoed for orchestrator)
  --check <path>    intake validation only: validate the inventory at <path> is
                    well-formed (controls[] + each has name/evidence); exit 2 on
                    violation. <path> may be a file or a dir (auto-discover).

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b): the full
`change_context.json` object (the orchestrator reads `pending[]` from it; see
core/contracts/sra/augmentation.md). In --check mode stdout =
{"check":"augment-intake","ok":bool,"controls":N,"violations":[...]}.

Exit codes (R5.3b): 0 ok · 1 file missing / JSON malformed / change not found ·
2 misuse (argparse) or intake-shape violation (--check).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

# Self-locate so any future sibling import resolves under any cwd (R5.3a).
# prepare_augment has no sibling import today; the guard keeps it self-contained.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── dimension ↔ category mapping (signal-1; mirrors security-dimensions.md) ──
DIMENSIONS_BY_CATEGORY = {
    "authorization": ["horizontal-authz", "vertical-authz"],
    "authentication": ["authentication"],
    "input-validation": ["injection"],
    "data-masking": ["sensitive-data"],
    "crypto": ["sensitive-data", "integrity", "secrets"],
    "csrf": ["integrity"],
    "rate-limiting": ["rate-limiting"],
    "audit-logging": ["audit"],
}

# ── mechanical signal extractors (high-precision; feed the LLM, not the verdict) ──
_ENDPOINT_RX = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/[A-Za-z0-9_./{}~:-]+)")
_FILE_RX = re.compile(
    r"\b[A-Za-z0-9_./@-]+\.(?:java|kt|py|ts|tsx|js|jsx|go|rb|php|cs|rs|c|cpp|cc|h|hpp|scala|sql|xml|yml|yaml|properties)\b")
_IDENT_RX = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")
_SENS_SUBSTR = ("card", "bankcard", "phone", "mobile", "email", "password",
                "passwd", "token", "secret", "idcard", "idno", "ssn", "certno",
                "credential", "pan")
_ROLE_HAS_RX = re.compile(r"has(?:Role|Roles)\(\s*['\"]([A-Za-z_][\w-]*)['\"]\s*\)")
_ROLE_ALLOWLIST = {"customer", "user", "admin", "merchant", "operator", "tenant",
                   "manager", "agent", "root", "superadmin", "staff", "vip"}

_SECTION_RX = re.compile(r"^##\s+(ADDED|MODIFIED)\s+Requirements\s*$", re.MULTILINE)
_REQ_HEAD_RX = re.compile(r"^###\s+Requirement:\s*(.+?)\s*$", re.MULTILINE)


def _find_project_root(start: Path):
    """Walk up from `start` to the first dir containing an `openspec/` subdir."""
    p = start.resolve()
    for cand in [p, *p.parents]:
        if (cand / "openspec").is_dir():
            return cand
    return None


def _dedupe_keep(seq):
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _extract_signals(text: str):
    """Return (data_fields, role_hints, mentioned_files, endpoints) from free text."""
    method_matches = list(_ENDPOINT_RX.finditer(text))
    captured_paths = {m.group(2) for m in method_matches}
    endpoints = _dedupe_keep(m.group(1) + " " + m.group(2) for m in method_matches)
    # bare /api/... paths only when not already covered by a METHOD/path capture
    bare = [m.group(1) for m in re.finditer(r"(?<![A-Za-z])(/api/[A-Za-z0-9_./{}~:-]+)", text)
            if m.group(1) not in captured_paths]
    endpoints = _dedupe_keep(endpoints + bare)

    sens, roles, files = [], [], []
    for m in _IDENT_RX.finditer(text):
        tok = m.group(0)
        low = tok.lower()
        if any(s in low for s in _SENS_SUBSTR):
            sens.append(tok)
        if low in _ROLE_ALLOWLIST:
            roles.append(tok)
    roles = _dedupe_keep(roles + [m.group(1) for m in _ROLE_HAS_RX.finditer(text)])
    files = _dedupe_keep(m.group(0) for m in _FILE_RX.finditer(text)
                         if "/" in m.group(0) or m.group(0).count(".") >= 2)
    return _dedupe_keep(sens), _dedupe_keep(roles), files, endpoints


def _parse_specs(specs_dir: Path):
    """Yield (capability, [(heading, body), ...]) for every specs/<cap>/spec.md.
    Requirements live under `## ADDED|MODIFIED Requirements` sections."""
    if not specs_dir.is_dir():
        return
    for spec in sorted(specs_dir.glob("*/spec.md")):
        cap = spec.parent.name
        text = spec.read_text(encoding="utf-8")
        reqs = _requirements_in(text)
        yield cap, reqs


def _requirements_in(text: str):
    """Collect (heading, body) for `### Requirement:` entries that live INSIDE a
    `## ADDED|MODIFIED Requirements` section (delta-spec convention)."""
    lines = text.splitlines()
    in_req_section = False
    reqs = []
    cur_head, cur_body = None, []

    def _flush():
        nonlocal cur_head, cur_body
        if cur_head is not None:
            reqs.append((cur_head, "\n".join(cur_body).strip()))
            cur_head, cur_body = None, []

    for line in lines:
        if line.startswith("## "):
            _flush()
            in_req_section = bool(_SECTION_RX.match(line))
            continue
        if line.startswith("### Requirement:"):
            _flush()
            m = _REQ_HEAD_RX.match(line)
            if in_req_section and m:
                cur_head = m.group(1).strip()
                cur_body = []
            continue
        if cur_head is not None:
            cur_body.append(line)
    _flush()
    return reqs


def _parse_tasks(tasks_path: Path):
    if not tasks_path.is_file():
        return []
    out = []
    for line in tasks_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if re.match(r"^-\s*\[[ xX]\]\s+\S", s):
            out.append(s)
    return out


def _resolve_rules(path: Path):
    """Return (inventory_path, inventory_dict) for a file or .mgh-init dir, or (None, None)."""
    if path.is_file():
        return path, json.loads(path.read_text(encoding="utf-8"))
    if path.is_dir():
        inv = path / "controls_inventory.json"
        if inv.is_file():
            return inv, json.loads(inv.read_text(encoding="utf-8"))
    return None, None


def _check_inventory(inv):
    """Minimal intake validation (decoupled from validate_inventory). Returns
    (ok, [violation_strings], controls_count)."""
    violations = []
    if not isinstance(inv, dict):
        return False, ["top-level JSON is not an object"], 0
    controls = inv.get("controls")
    if not isinstance(controls, list):
        return False, ["missing or non-list `controls[]`"], 0
    for i, c in enumerate(controls):
        if not isinstance(c, dict):
            violations.append(f"controls[{i}]: not an object")
            continue
        name = c.get("name")
        if not isinstance(name, str) or not name.strip():
            violations.append(f"controls[{i}]: missing/empty `name`")
        ev = c.get("evidence")
        if not isinstance(ev, list) or not ev or not all(isinstance(e, str) and e.strip() for e in ev):
            violations.append(f"controls[{i}]: `evidence` must be a non-empty list of strings")
    return (len(violations) == 0), violations, len(controls)


def _candidate_controls(inv, mentioned_files):
    """Signal-1 pre-filter: derive dimensions from category + mark file overlap.
    Never hard-drops a control (only tags)."""
    norm_files = [f.replace("\\", "/").lower() for f in mentioned_files]
    out = []
    for c in inv.get("controls", []):
        if not isinstance(c, dict):
            continue
        cat = c.get("category")
        entry_points = c.get("entry_points") or c.get("protects") or []
        norm_eps = [str(e).replace("\\", "/").lower() for e in entry_points]
        overlap = any(ep and (ep in mf or mf in ep)
                      for ep in norm_eps for mf in norm_files)
        out.append({
            "name": c.get("name"),
            "category": cat,
            "dimensions": DIMENSIONS_BY_CATEGORY.get(cat, []),
            "entry_points": entry_points,
            "evidence": c.get("evidence") or [],
            "file_overlap": overlap,
        })
    return out


def _emit_change_context(args, project_root: Path, change_root: Path, change: str):
    # --- gather change text ---
    blobs = {}
    for name in ("proposal.md", "design.md"):
        p = change_root / name
        if p.is_file():
            blobs[name] = p.read_text(encoding="utf-8")
    full_text = "\n".join(blobs.values())

    # --- capabilities / requirements from specs ---
    capabilities, requirements = [], []
    for cap, reqs in _parse_specs(change_root / "specs"):
        headings = [h for h, _ in reqs]
        capabilities.append({"name": cap, "requirements": headings})
        for h, body in reqs:
            requirements.append({"capability": cap, "heading": h, "body": body})

    tasks = _parse_tasks(change_root / "tasks.md")

    # --- mechanical signals over the WHOLE change (proposal+design+specs+tasks) ---
    scan_text = full_text + "\n" + "\n".join(r["body"] for r in requirements) + "\n" + "\n".join(tasks)
    sens, roles, files, endpoints = _extract_signals(scan_text)

    # --- candidate controls (signal-1) ---
    candidate_controls, rules_source = [], "none"
    if args.rules:
        rules_path = Path(args.rules)
        try:
            inv_path, inv = _resolve_rules(rules_path)
        except (OSError, ValueError) as e:
            print(f"error: could not read --rules {rules_path}: {e}", file=sys.stderr)
            sys.exit(1)
        if inv is None:
            print(f"error: --rules not a controls_inventory.json file or .mgh-init dir: {rules_path}",
                  file=sys.stderr)
            sys.exit(1)
        ok, violations, _ = _check_inventory(inv)
        if not ok:
            print("error: --rules inventory malformed; run `prepare_augment.py --check "
                  f"{rules_path}` for details: {violations[:3]}", file=sys.stderr)
            sys.exit(2)
        candidate_controls = _candidate_controls(inv, files)
        rules_source = str(inv_path)

    # --- project-level business memory ---
    memory_path = project_root / ".mgh-sra" / "business_context.json"
    memory = None
    if memory_path.is_file():
        try:
            memory = json.loads(memory_path.read_text(encoding="utf-8"))
            if not isinstance(memory, dict):
                memory = None
        except (OSError, ValueError):
            memory = None

    # --- pending work-list (absolute draft paths under the project subtree) ---
    out_dir = Path(args.out).resolve() if args.out else (change_root / ".mgh-sra")
    drafts_dir = out_dir / "drafts"
    cap_names = [c["name"] for c in capabilities] or ["security-augmentation"]
    pending = []
    for cap in cap_names:
        draft_path = (drafts_dir / f"{cap}.md").resolve()
        pending.append({
            "capability": cap,
            "draft_path": str(draft_path),
            "done_marker": str(draft_path.with_name(draft_path.name + ".done")),
        })

    change_context = {
        "change": change,
        "change_root": str(change_root),
        "project_root": str(project_root),
        "capabilities": capabilities,
        "requirements": requirements,
        "tasks": tasks,
        "mentioned_files": files,
        "endpoints": endpoints,
        "data_fields": sens,
        "role_hints": roles,
        "candidate_controls": candidate_controls,
        "clarify_path": str((out_dir / "clarifications.json").resolve()),
        "pending": pending,
        "memory": memory,
        "rules_source": rules_source,
        "memory_source": str(memory_path) if memory is not None else "none",
        "dry_run": bool(args.dry_run),
        "truncated": False,
    }

    # --- structural invariant: pending paths under the project subtree (D8) ---
    bad = [p["draft_path"] for p in pending
           if not Path(p["draft_path"]).resolve().is_relative_to(project_root.resolve())]
    if bad:
        print(f"error: draft path drifted outside the project subtree: {bad}", file=sys.stderr)
        sys.exit(2)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "change_context.json").write_text(
        json.dumps(change_context, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[prepare_augment] change={change} caps={len(capabilities)} reqs={len(requirements)} "
          f"tasks={len(tasks)} endpoints={len(endpoints)} sens_fields={len(sens)} "
          f"candidate_controls={len(candidate_controls)} memory={'yes' if memory else 'no'} "
          f"pending={len(pending)} -> {out_dir / 'change_context.json'}", file=sys.stderr)
    return change_context


def _run_check(rules_arg):
    path = Path(rules_arg)
    try:
        inv_path, inv = _resolve_rules(path)
    except (OSError, ValueError) as e:
        print(f"error: could not read {path}: {e}", file=sys.stderr)
        return 1
    if inv is None:
        print(f"error: not a controls_inventory.json file or .mgh-init dir: {path}", file=sys.stderr)
        return 1
    ok, violations, n = _check_inventory(inv)
    summary = {"check": "augment-intake", "ok": ok, "controls": n, "violations": violations}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[prepare_augment] --check {inv_path}: controls={n} ok={ok} "
          f"violations={len(violations)}", file=sys.stderr)
    return 0 if ok else 2


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="a1 for /mgh-sra: parse openspec change -> change_context.json + "
                    "signal-1 candidate pre-filter + absolute draft work-list")
    ap.add_argument("--change", help="target change name (default: newest under openspec/changes/)")
    ap.add_argument("--rules", help="mgh-init controls_inventory.json FILE or its output DIR")
    ap.add_argument("--out", help="output dir (default: <change-root>/.mgh-sra)")
    ap.add_argument("--dry-run", action="store_true",
                    help="produce change_context.json + summary only (orchestrator skips merges)")
    ap.add_argument("--no-interactive", action="store_true",
                    help="clarification uses default guesses (flag echoed for orchestrator)")
    ap.add_argument("--check", nargs="?", const="", default=None, metavar="PATH",
                    help="intake validation only: validate inventory at PATH (file or dir)")
    args = ap.parse_args()

    if args.check is not None:
        target = args.check.strip() or (args.rules or "").strip()
        if not target:
            print("error: --check needs a path (or pair with --rules)", file=sys.stderr)
            return 2
        return _run_check(target)

    project_root = _find_project_root(Path.cwd())
    if project_root is None:
        print("error: not inside a project (no openspec/ dir found upward from cwd)",
              file=sys.stderr)
        return 1
    changes_dir = project_root / "openspec" / "changes"
    if args.change:
        change_root = (changes_dir / args.change).resolve()
        if not change_root.is_dir():
            print(f"error: change not found: {change_root}", file=sys.stderr)
            return 1
        change = args.change
    else:
        candidates = [d for d in changes_dir.iterdir() if d.is_dir()]
        if not candidates:
            print(f"error: no unarchived changes under {changes_dir}", file=sys.stderr)
            return 1
        change_root = max(candidates, key=lambda d: d.stat().st_mtime).resolve()
        change = change_root.name

    ctx = _emit_change_context(args, project_root, change_root, change)
    print(json.dumps(ctx, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
