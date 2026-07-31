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
  py prepare_augment.py --change <name> [--rules <path>] [--focus <inline-json|path>]
                        [--sensitive-catalog <inline-json|@path|->] [--out <dir>]
                        [--materialize <inputs-dir>] [--offset N] [--limit N]
                        [--max-unit-bytes B] [--orch-budget-bytes B]
                        [--dry-run] [--no-interactive]
  py prepare_augment.py --check <rules-path-or-dir|change_context.json>

  --change <name>   target change (default: newest dir under openspec/changes/)
  --rules <path>    mgh-init controls_inventory.json FILE or its output DIR
                    (e.g. <project>/.mgh-init); auto-discovered when a dir
  --focus <json|path>  optional security-dimension focus (inline JSON beginning with
                    `{` or a path to a JSON file; leading `@` tolerated). Narrows the
                    per-dimension scan to a subset of the 9 dimensions + optional
                    per-dimension facets. Parsed + closed-set-validated via the shared
                    focus_scope module (sibling import) BEFORE any LLM; embedded as the
                    `focus` field of change_context.json (object or null). Omit = all 9
                    dimensions (behavior unchanged). Invalid → exit 2, no context emitted.
  --sensitive-catalog <json|@path|->
                    optional company masking-policy catalog (inline JSON beginning with
                    `{`, `-` for stdin, or a path to a JSON file; leading `@` tolerated).
                    Declares the field types that MUST be masked + their mask level/rule;
                    extends sensitive-data recognition beyond the legacy 6 facets. Parsed
                    + closed-set-validated via the shared sensitive_catalog module (sibling
                    import) BEFORE any LLM; embedded as the `sensitive_catalog` field of
                    change_context.json (object or null). Omit = legacy 6 facets only
                    (behavior unchanged). Invalid → exit 2, no context emitted.
  --out <dir>       output dir (default: <change-root>/.mgh-sra)
  --materialize <dir>  write each capability's COMPLETE input to <dir>/<cap>.input.json and
                    emit a SLIM paged stdout (pending[] carries input_path/bytes/oversize, no
                    requirement bodies); the orchestrator passes input_path to sra-augment,
                    which reads its own bounded file. The full change_context.json is still
                    written under <out>/ (a2 stage consumer). Omit = backward-compat full
                    change_context on stdout (legacy/debug).
  --offset N        page offset into the not-done pending[] (default 0)
  --limit N         max pending items per page (default: all not-done)
  --max-unit-bytes B   per-capability input byte cap (default 192KB). A capability over the cap
                    is flagged oversize:true + a recipe (split the change / --focus narrow); the
                    capability is the a3 atom and is NEVER sharded.
  --orch-budget-bytes B  orchestrator single-request page byte cap (default 64KB). A page over
                    the cap is auto-tightened; stdout reports effective_limit + shrunk:true.
  --dry-run         produce change_context.json + stdout summary only (orchestrator
                    skips the merge steps; flag echoed for the orchestrator)
  --no-interactive  clarification uses default guesses (flag echoed for orchestrator)
  --check <path>    intake validation only. <path> polymorphic: an inventory file/dir
                    (controls[] + each has name/evidence) OR a produced change_context.json
                    (top-level fields + pending[] absolute & in subtree + pending input_path
                    absolute & in subtree + focus field shape + sensitive_catalog field shape);
                    exit 2 on violation.

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  - default (no --materialize): the full `change_context.json` object (legacy/debug; the
    orchestrator reads `pending[]` / `clarify_path` / `candidate_controls` / `memory` from it).
  - with --materialize: a SLIM paged envelope — {change, change_root, project_root,
    clarify_path, memory_source, rules_source, dry_run, focus, sensitive_catalog, total, done,
    pending[<slim: capability/draft_path/done_marker/input_path/bytes/oversize>], offset, limit,
    effective_limit, shrunk, requirements_count, candidate_controls_count, has_memory}. The
    orchestrator NEVER loads the whole change_context.json; it pages pending[] and passes each
    input_path to sra-augment.
The full change_context.json is always written to <out>/change_context.json on disk (a2 consumer).
In --check mode stdout = {"check":"augment-intake","ok":bool,"controls":N,"violations":[...]}.

Exit codes (R5.3b): 0 ok · 1 file missing / JSON malformed / change not found ·
2 misuse (argparse) or intake-shape violation (--check).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

# Self-locate so the sibling import resolves under any cwd (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))
# Shared focus-scope registry + parse/validate/render (single source of truth for the
# --focus narrowing flag; closed-set-validated here, before any LLM subagent).
import focus_scope
# Shared sensitive-catalog registry + parse/validate/render (single source of truth
# for the --sensitive-catalog company masking-policy flag; closed-set-validated here,
# before any LLM subagent). Orthogonal to --focus.
import sensitive_catalog

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

# Per-request context budgets (request-context-budget; bytes = conservative token upper bound).
DEFAULT_MAX_UNIT_BYTES = 192 * 1024    # 192KB — per-capability materialized input cap
DEFAULT_ORCH_BUDGET_BYTES = 64 * 1024  # 64KB — orchestrator single-request page cap


def _parse_bytes(label: str, raw) -> int:
    """Non-negative integer byte budget; returns -1 sentinel on misuse (caller exit 2)."""
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


def _safe_unit_name(name: str) -> str:
    """Filesystem-safe input filename for a capability. Capability names come from specs/<cap>/
    dir names (already path-safe), but `::` (NTFS ADS separator) is belt-and-suspenders guarded."""
    return name.replace("/", "_").replace("\\", "_").replace(":", "_")


def _shrink_page(page: list, orch_budget: int):
    """Tighten a page so its serialized bytes <= orch_budget (keep >=1 item). Returns
    (page, effective_limit, shrunk)."""
    if orch_budget <= 0 or not page:
        return page, len(page), False
    eff = len(page)
    while eff > 1 and _byte_len(page[:eff]) > orch_budget:
        eff -= 1
    return page[:eff], eff, eff < len(page)


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


def _unit_input(cap_name, reqs, inv, memory, doc_signals, doc_candidate_controls):
    """A capability's COMPLETE input record for the sra-augment stage (per-capability augment).
    Body = this cap's requirements (heading+body) + per-cap-extracted business surface + the
    candidate_controls SLICE (controls whose entry_points overlap this cap's mentioned_files —
    reuses the `_candidate_controls` file_overlap judgment, D1) + shared memory. The fallback
    capability (no specs) gets the doc-wide signals + full candidate set (whole-change view).
    Bounded by --max-unit-bytes (oversize -> flag + recipe, NEVER sharded: capability = a3 atom)."""
    if reqs:
        body = "\n\n".join(b for _, b in reqs)
        sens, roles, files, endpoints = _extract_signals(body)
        cc = ([c for c in _candidate_controls(inv, files) if c.get("file_overlap")]
              if inv is not None else [])
    else:
        # fallback capability (no specs): whole-change view (doc-wide signals + full candidate set)
        sens, roles, files, endpoints = doc_signals
        cc = doc_candidate_controls
    return {
        "capability": cap_name,
        "requirements": [{"heading": h, "body": b} for h, b in reqs],
        "endpoints": endpoints,
        "data_fields": sens,
        "role_hints": roles,
        "mentioned_files": files,
        "candidate_controls": cc,
        "memory": memory,
    }


def _write_unit_input(inputs_dir: Path, cap_name: str, inp: dict):
    """Write `<inputs_dir>/<cap>.input.json` (idempotent overwrite); return (abs path, bytes)."""
    inputs_dir.mkdir(parents=True, exist_ok=True)
    path = (inputs_dir / f"{_safe_unit_name(cap_name)}.input.json").resolve()
    path.write_text(json.dumps(inp, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path), path.stat().st_size


def _emit_change_context(args, project_root: Path, change_root: Path, change: str):
    # --- gather change text ---
    blobs = {}
    for name in ("proposal.md", "design.md"):
        p = change_root / name
        if p.is_file():
            blobs[name] = p.read_text(encoding="utf-8")
    full_text = "\n".join(blobs.values())

    # --- capabilities / requirements from specs ---
    capabilities, requirements, reqs_by_cap = [], [], {}
    for cap, reqs in _parse_specs(change_root / "specs"):
        headings = [h for h, _ in reqs]
        capabilities.append({"name": cap, "requirements": headings})
        reqs_by_cap.setdefault(cap, []).extend(reqs)
        for h, body in reqs:
            requirements.append({"capability": cap, "heading": h, "body": body})

    tasks = _parse_tasks(change_root / "tasks.md")

    # --- mechanical signals over the WHOLE change (proposal+design+specs+tasks) ---
    scan_text = full_text + "\n" + "\n".join(r["body"] for r in requirements) + "\n" + "\n".join(tasks)
    sens, roles, files, endpoints = _extract_signals(scan_text)

    # --- candidate controls (signal-1) ---
    candidate_controls, rules_source, inv = [], "none", None
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
    materialize = bool(args.materialize)
    inputs_dir = Path(args.materialize).resolve() if materialize else None
    max_unit_bytes = args.max_unit_bytes
    if materialize:
        # inputs MUST land inside the run-domain subtree (hook判树); fail-loud otherwise.
        try:
            if not inputs_dir.resolve().is_relative_to(project_root.resolve()):
                print(f"error: --materialize dir outside project subtree: {inputs_dir}",
                      file=sys.stderr)
                sys.exit(2)
        except (OSError, ValueError) as e:
            print(f"error: --materialize dir unresolvable: {inputs_dir}: {e}", file=sys.stderr)
            sys.exit(2)
    doc_signals = (sens, roles, files, endpoints)
    cap_names = list(reqs_by_cap.keys()) or ["security-augmentation"]
    pending = []
    oversize_count = 0
    for cap in cap_names:
        draft_path = (drafts_dir / f"{cap}.md").resolve()
        item = {
            "capability": cap,
            "draft_path": str(draft_path),
            "done_marker": str(draft_path.with_name(draft_path.name + ".done")),
        }
        if materialize:
            inp = _unit_input(cap, reqs_by_cap.get(cap, []), inv, memory,
                              doc_signals, candidate_controls)
            input_path, nbytes = _write_unit_input(inputs_dir, cap, inp)
            oversize = nbytes > max_unit_bytes
            if oversize:
                oversize_count += 1
                print(f"warn: capability {cap} input ({nbytes}B > {max_unit_bytes}B) -> oversize; "
                      f"recipe: split the change / --focus narrow (capability not sharded)",
                      file=sys.stderr)
            item["input_path"] = input_path
            item["bytes"] = nbytes
            item["oversize"] = oversize
        pending.append(item)

    # --- focus (dimension narrowing; closed-set-validated here, before any LLM) ---
    focus = _resolve_focus(args)
    # --- sensitive-catalog (company masking policy; closed-set-validated here) ---
    catalog = _resolve_sensitive_catalog(args)

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
        "focus": focus,
        "sensitive_catalog": catalog,
    }

    # --- structural invariant: pending draft + input paths under the project subtree (hook判树) ---
    bad = [p["draft_path"] for p in pending
           if not Path(p["draft_path"]).resolve().is_relative_to(project_root.resolve())]
    bad += [p["input_path"] for p in pending if p.get("input_path")
            and not Path(p["input_path"]).resolve().is_relative_to(project_root.resolve())]
    if bad:
        print(f"error: path drifted outside the project subtree: {bad}", file=sys.stderr)
        sys.exit(2)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "change_context.json").write_text(
        json.dumps(change_context, ensure_ascii=False, indent=2), encoding="utf-8")

    focus_desc = ("all9" if focus is None
                  else f"narrowed({len(focus['dimensions'])}d"
                       + (f",{sum(len(v) for v in focus['facets'].values())}f)" if focus['facets'] else ")"))
    catalog_desc = ("none" if catalog is None
                    else f"{catalog['counts']['items']}items({catalog['counts']['categories']}cat)")

    if not materialize:
        # backward-compat: full change_context on stdout (legacy/debug path, behavior unchanged)
        print(f"[prepare_augment] change={change} caps={len(capabilities)} reqs={len(requirements)} "
              f"tasks={len(tasks)} endpoints={len(endpoints)} sens_fields={len(sens)} "
              f"candidate_controls={len(candidate_controls)} memory={'yes' if memory else 'no'} "
              f"focus={focus_desc} catalog={catalog_desc} pending={len(pending)} "
              f"-> {out_dir / 'change_context.json'}",
              file=sys.stderr)
        return change_context

    # SLIM paged envelope: orchestrator NEVER loads the whole change_context.json.
    done = sum(1 for p in pending if Path(p["done_marker"]).is_file())
    live = [p for p in pending if not Path(p["done_marker"]).is_file()]
    req_limit = args.limit if args.limit is not None else len(live)
    page = live[args.offset: args.offset + max(0, req_limit)]
    page, eff, shrunk = _shrink_page(page, args.orch_budget_bytes)
    slim = {
        "change": change,
        "change_root": str(change_root),
        "project_root": str(project_root),
        "clarify_path": change_context["clarify_path"],
        "memory_source": change_context["memory_source"],
        "rules_source": rules_source,
        "dry_run": bool(args.dry_run),
        "focus": focus,
        "sensitive_catalog": catalog,
        "total": len(pending),
        "done": done,
        "pending": page,
        "offset": args.offset,
        "limit": req_limit,
        "effective_limit": eff,
        "shrunk": shrunk,
        "requirements_count": len(requirements),
        "candidate_controls_count": len(candidate_controls),
        "has_memory": memory is not None,
    }
    print(f"[prepare_augment] change={change} caps={len(capabilities)} reqs={len(requirements)} "
          f"candidate_controls={len(candidate_controls)} memory={'yes' if memory else 'no'} "
          f"focus={focus_desc} catalog={catalog_desc} oversize={oversize_count} "
          f"pending={len(live)} done={done} page offset={args.offset} eff={eff} shrunk={shrunk} "
          f"-> {out_dir / 'change_context.json'}",
          file=sys.stderr)
    return slim


def _resolve_focus(args):
    """Resolve --focus (inline JSON | path) via the shared focus_scope module BEFORE any
    LLM subagent. Returns the resolved focus object or None (no --focus = all 9).
    Prints actionable stderr + exits 1 (read/parse failure) / 2 (closed-set violation).
    Shared with ingest_requirements via sibling import."""
    if not getattr(args, "focus", None):
        return None
    try:
        return focus_scope.resolve(args.focus)
    except focus_scope.FocusInputError as e:
        print(f"error: invalid --focus: {e}", file=sys.stderr)
        sys.exit(1)
    except focus_scope.FocusViolation as v:
        for msg in v.messages:
            print(f"error: invalid --focus: {msg}", file=sys.stderr)
        sys.exit(2)


def _resolve_sensitive_catalog(args):
    """Resolve --sensitive-catalog (inline JSON | @path | -) via the shared
    sensitive_catalog module BEFORE any LLM subagent. Returns the resolved catalog
    object or None (no flag = legacy 6 facets). Prints actionable stderr + exits 1
    (read/parse failure) / 2 (closed-set violation). Shared with ingest_requirements."""
    if not getattr(args, "sensitive_catalog", None):
        return None
    try:
        return sensitive_catalog.resolve(args.sensitive_catalog)
    except sensitive_catalog.CatalogInputError as e:
        print(f"error: invalid --sensitive-catalog: {e}", file=sys.stderr)
        sys.exit(1)
    except sensitive_catalog.CatalogViolation as v:
        for msg in v.messages:
            print(f"error: invalid --sensitive-catalog: {msg}", file=sys.stderr)
        sys.exit(2)


def _check_change_context(ctx):
    """Validate a produced change_context.json: required top-level fields + pending[]
    paths absolute & in project_root subtree + focus field shape (null = all 9, valid)."""
    if not isinstance(ctx, dict):
        return ["top-level JSON is not an object"]
    violations = []
    for f in ("change", "change_root", "project_root", "capabilities",
              "requirements", "pending", "clarify_path"):
        if f not in ctx:
            violations.append(f"missing top-level field: {f}")
    pr = ctx.get("project_root")
    pending = ctx.get("pending")
    if not isinstance(pending, list):
        violations.append("pending is not a list")
    else:
        for item in pending:
            if not isinstance(item, dict):
                violations.append("pending item is not an object")
                continue
            dp = item.get("draft_path")
            if not dp:
                violations.append("pending item missing draft_path")
                continue
            try:
                rp = Path(dp).resolve()
                if not rp.is_absolute():
                    violations.append(f"draft_path not absolute: {dp}")
                elif pr and not rp.is_relative_to(Path(pr).resolve()):
                    violations.append(f"draft_path outside project subtree: {dp}")
            except (OSError, ValueError):
                violations.append(f"draft_path unresolvable: {dp}")
            # materialized fields (additive — only when prepare ran with --materialize)
            ip = item.get("input_path")
            if ip is not None:
                try:
                    rip = Path(ip).resolve()
                    if not rip.is_absolute():
                        violations.append(f"input_path not absolute: {ip}")
                    elif pr and not rip.is_relative_to(Path(pr).resolve()):
                        violations.append(f"input_path outside project subtree: {ip}")
                except (OSError, ValueError):
                    violations.append(f"input_path unresolvable: {ip}")
                if not isinstance(item.get("bytes"), int):
                    violations.append("pending item has input_path but bytes missing/not int")
                if not isinstance(item.get("oversize"), bool):
                    violations.append("pending item has input_path but oversize missing/not bool")
    if "focus" in ctx:
        violations.extend(focus_scope.validate_resolved(ctx.get("focus")))
    if "sensitive_catalog" in ctx:
        violations.extend(sensitive_catalog.validate_resolved(ctx.get("sensitive_catalog")))
    return violations


def _run_check(target_arg):
    path = Path(target_arg)
    # polymorphic artifact resolution: inventory file/dir OR change_context.json file/dir
    target_file = None
    if path.is_file():
        target_file = path
    elif path.is_dir():
        for cand in ("controls_inventory.json", "change_context.json"):
            if (path / cand).is_file():
                target_file = path / cand
                break
    if target_file is None:
        print(f"error: not an inventory or change_context artifact: {path}", file=sys.stderr)
        return 1
    try:
        data = json.loads(target_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: could not read {target_file}: {e}", file=sys.stderr)
        return 1
    if isinstance(data, dict) and isinstance(data.get("controls"), list):
        # inventory validation (existing path)
        ok, violations, n = _check_inventory(data)
        summary = {"check": "augment-intake", "ok": ok, "controls": n, "violations": violations}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"[prepare_augment] --check {target_file}: inventory controls={n} ok={ok} "
              f"violations={len(violations)}", file=sys.stderr)
        return 0 if ok else 2
    # otherwise: treat as a produced change_context.json (structure + focus field)
    violations = _check_change_context(data)
    summary = {"check": "augment-intake", "ok": not violations, "violations": violations}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[prepare_augment] --check {target_file}: change_context ok={not violations} "
          f"violations={len(violations)}", file=sys.stderr)
    return 0 if not violations else 2


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
    ap.add_argument("--focus", default=None,
                    help="optional security-dimension focus (inline JSON beginning with `{` or a "
                         "JSON file path; leading `@` tolerated) — narrows the per-dimension scan. "
                         "Omit = all 9 dimensions")
    ap.add_argument("--sensitive-catalog", default=None, metavar="INLINE-JSON|@PATH|-",
                    help="optional company masking-policy catalog (inline JSON beginning with `{`, "
                         "`-` for stdin, or a JSON file path; leading `@` tolerated) — declares the "
                         "field types that MUST be masked. Omit = legacy 6 facets only")
    ap.add_argument("--out", help="output dir (default: <change-root>/.mgh-sra)")
    ap.add_argument("--materialize", metavar="<inputs-dir>",
                    help="write each capability's complete input to <dir>/<cap>.input.json and emit "
                         "a slim paged stdout (input_path/bytes/oversize; backward-compat full "
                         "stdout if omitted)")
    ap.add_argument("--offset", type=int, default=0, help="page offset (default 0)")
    ap.add_argument("--limit", type=int, default=None,
                    help="max pending items per page (default: all not-done)")
    ap.add_argument("--max-unit-bytes", type=int, default=DEFAULT_MAX_UNIT_BYTES,
                    help=f"per-capability input byte cap (default {DEFAULT_MAX_UNIT_BYTES}; "
                         f"oversize capability flagged + recipe, not sharded)")
    ap.add_argument("--orch-budget-bytes", type=int, default=DEFAULT_ORCH_BUDGET_BYTES,
                    help=f"orchestrator single-request page byte cap (default "
                         f"{DEFAULT_ORCH_BUDGET_BYTES}; page auto-tightened + shrunk:true)")
    ap.add_argument("--dry-run", action="store_true",
                    help="produce change_context.json + summary only (orchestrator skips merges)")
    ap.add_argument("--no-interactive", action="store_true",
                    help="clarification uses default guesses (flag echoed for orchestrator)")
    ap.add_argument("--check", nargs="?", const="", default=None, metavar="PATH",
                    help="intake validation only: validate inventory at PATH (file or dir)")
    args = ap.parse_args()

    if args.offset < 0:
        print("error: --offset must be >= 0", file=sys.stderr)
        return 2
    for label, raw in (("--max-unit-bytes", args.max_unit_bytes),
                       ("--orch-budget-bytes", args.orch_budget_bytes)):
        if _parse_bytes(label, raw) < 0:
            return 2

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
