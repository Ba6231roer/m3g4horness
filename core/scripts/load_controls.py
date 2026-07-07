#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
load_controls — sast controls intake + scope projection (deterministic, stdlib).

Fills vvaharness gap #10 (injectors/design_controls.py::load_controls, consumed by
s2/s8). Reads a /mgh-init `controls_inventory.json`, intake-validates it, projects the
in-scope control subset against the scan's `in_scope[]`, and emits a `controls_bundle`
for the orchestrator to inject into s2/s3/s4/s6/s8 subagent task messages.

Two CLI modes (`--help` IS the contract surface, R5.1):
  py load_controls.py --inventory <controls_inventory.json> --repo <root> [--in-scope <f>]
  py load_controls.py --check    <controls_inventory.json>

Intake is the sast CONSUMPTION-side boundary check (R5.9); it MUST NOT import the init
producer-side `validate_inventory.py` (avoids a sast→init reverse dependency). kind
aliases normalize to the vvah canonical 6-enum (single source of truth: the alias table
in core/contracts/init/inventory.md:45-48).

stdout (R5.3b) = structured JSON (`controls_bundle` / check report); stderr = diagnostics
only. Exit codes (R5.3b): 0 ok · 1 missing/malformed · 2 intake violation / misuse.
Zero runtime deps (Python >=3.10 stdlib: argparse/fnmatch/json/pathlib/sys).
"""
from __future__ import annotations
import argparse
import fnmatch
import json
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). load_controls currently has no sibling
# import (it MUST NOT import validate_inventory), but the guard keeps it in the
# self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

# vvah canonical 6-enum (core/contracts/init/inventory.md:24).
VVAH_KINDS = {"auth", "sandbox", "input-validation", "aslr", "cfi", "other"}

# kind alias → canonical normalization (single source of truth:
# core/contracts/init/inventory.md:45-48). aslr/cfi/other have no alias (already canonical).
KIND_ALIASES = {
    "authn": "auth", "authz": "auth", "rbac": "auth", "iam": "auth", "sso": "auth",
    "waf": "input-validation", "validation": "input-validation",
    "sanitization": "input-validation", "encoding": "input-validation",
    "seccomp": "sandbox", "container": "sandbox", "isolation": "sandbox",
}


def normalize_kind(kind):
    """Return the canonical 6-enum for a kind, or None if not recognized/normalizable."""
    if kind in VVAH_KINDS:
        return kind
    return KIND_ALIASES.get(kind)


# --- intake validation (shared by --check and the main path) ---

def _validate_control(c, index):
    """Return a list of violation dicts for one control."""
    if not isinstance(c, dict):
        return [{"index": index, "issue": "control not an object"}]
    where = {"index": index, "name": c.get("name")}
    v = []
    name = c.get("name")
    if not isinstance(name, str) or not name.strip():
        v.append({**where, "issue": "missing/empty name"})
    kind = c.get("kind")
    canon = normalize_kind(kind) if isinstance(kind, str) else None
    if canon is None:
        v.append({**where, "issue": f"kind {kind!r} not a canonical 6-enum or normalizable alias"})
    ev = c.get("evidence")
    if not isinstance(ev, list) or not ev:
        v.append({**where, "issue": "evidence must be a non-empty list"})
    elif not all(isinstance(a, str) and a.strip() for a in ev):
        v.append({**where, "issue": "evidence anchors must be non-empty strings"})
    for key in ("protects", "entry_points"):
        val = c.get(key)
        if val is not None and not (isinstance(val, list)
                                    and all(isinstance(x, str) for x in val)):
            v.append({**where, "issue": f"{key} must be a list of strings"})
    return v


def _intake(inv):
    """Validate the wrapper + every control. Return (controls_list_or_None, violations)."""
    if not isinstance(inv, dict):
        return None, [{"issue": "inventory must be a JSON object"}]
    controls = inv.get("controls")
    if not isinstance(controls, list):
        return None, [{"issue": "inventory.controls must be a list"}]
    violations = []
    for i, c in enumerate(controls):
        violations.extend(_validate_control(c, i))
    return controls, violations


def _load_inventory(path):
    """Return (parsed_json, None) or (None, exit_code) on missing/malformed."""
    p = Path(path)
    if not p.is_file():
        print(f"error: controls_inventory not found: {p}", file=sys.stderr)
        return None, 1
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as e:
        print(f"error: malformed controls_inventory: {e}", file=sys.stderr)
        return None, 1


# --- scope projection (deterministic fnmatch) ---

def _norm(p):
    """Repo-path normalize: backslash→slash, strip surrounding slashes (cross-platform)."""
    return str(p).replace("\\", "/").strip("/")


def _control_in_scope(c, scope_list):
    """True if any protects glob or entry_points intersects scope_list (fnmatchcase)."""
    protects = c.get("protects") if isinstance(c.get("protects"), list) else []
    eps = c.get("entry_points") if isinstance(c.get("entry_points"), list) else []
    for s in scope_list:
        sn = _norm(s)
        if not sn:
            continue
        for g in protects:
            if fnmatch.fnmatchcase(sn, _norm(g)):
                return True
        for ep in eps:
            epn = _norm(ep)
            if epn and (epn == sn or epn.startswith(sn + "/")):
                return True
    return False


def _read_in_scope(path):
    """Read in_scope[] from a JSON {in_scope:[...]} / bare list, else newline-delimited."""
    raw = path.read_text(encoding="utf-8")
    stripped = raw.strip()
    if stripped and stripped[0] in "{[":
        data = json.loads(raw)
        if isinstance(data, dict):
            ls = data.get("in_scope")
            if not isinstance(ls, list):
                raise ValueError("in-scope JSON object has no 'in_scope' list")
            return [str(x) for x in ls]
        if isinstance(data, list):
            return [str(x) for x in data]
        raise ValueError("in-scope file must be a JSON list or {in_scope:[...]}")
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def _summary(c):
    kind = c.get("kind")
    return {
        "name": c.get("name"),
        "kind": normalize_kind(kind) if isinstance(kind, str) else kind,
        "description": c.get("description", ""),
        "usage": c.get("usage", ""),
        "evidence": c.get("evidence") or [],
        "entry_points": c.get("entry_points") or [],
        "protects": c.get("protects") or [],
        "gaps": c.get("gaps") or [],
    }


def _run_check(path):
    inv, err = _load_inventory(path)
    if inv is None:
        return err
    controls, violations = _intake(inv)
    if controls is None:
        violations = violations or [{"issue": "controls not a list"}]
        n = 0
    else:
        n = len(controls)
    ok = not violations
    print(f"[load_controls --check] {path}: controls={n}, "
          f"{'OK' if ok else f'{len(violations)} violation(s)'}", file=sys.stderr)
    print(json.dumps({"check": "controls-intake", "ok": ok, "controls": n,
                      "violations": violations}, ensure_ascii=False))
    return 0 if ok else 2


def _run_intake_project(inventory, repo, in_scope_file):
    inv, err = _load_inventory(inventory)
    if inv is None:
        return err
    controls, violations = _intake(inv)
    if controls is None:
        print(f"error: {(violations or [{}])[0].get('issue', 'controls not a list')}",
              file=sys.stderr)
        return 2
    if violations:
        print(f"[load_controls] intake failed: {len(violations)} violation(s); "
              f"aborting projection (no partial emit)", file=sys.stderr)
        print(json.dumps({"check": "controls-intake", "ok": False,
                          "controls": len(controls),
                          "violations": violations}, ensure_ascii=False))
        return 2

    if in_scope_file:
        try:
            scope_list = _read_in_scope(Path(in_scope_file))
        except (OSError, ValueError) as e:
            print(f"error: cannot read --in-scope: {e}", file=sys.stderr)
            return 1
    else:
        scope_list = None  # full-repo scan → every control in scope

    in_scope_summaries, out_of_scope_summary = [], []
    for c in controls:
        hit = True if scope_list is None else _control_in_scope(c, scope_list)
        if hit:
            in_scope_summaries.append(_summary(c))
        else:
            out_of_scope_summary.append(
                {"name": c.get("name"),
                 "kind": normalize_kind(c.get("kind")) if isinstance(c.get("kind"), str)
                 else c.get("kind")})

    bundle = {
        "source": "mgh-init",
        "inventory_path": inventory,
        "repo": repo,
        "total": len(controls),
        "in_scope_count": len(in_scope_summaries),
        "out_of_scope_count": len(out_of_scope_summary),
        "in_scope": in_scope_summaries,
        "out_of_scope_summary": out_of_scope_summary,
    }
    print(f"[load_controls] {inventory}: total={bundle['total']}, "
          f"in_scope={bundle['in_scope_count']}, "
          f"out_of_scope={bundle['out_of_scope_count']}", file=sys.stderr)
    print(json.dumps(bundle, ensure_ascii=False))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="load_controls.py",
        description="sast controls intake + scope projection (deterministic). Emits a "
                    "controls_bundle for s2/s3/s4/s6/s8 injection, or --check validates an "
                    "inventory at the intake boundary (R5.9).")
    ap.add_argument("--inventory", metavar="PATH",
                    help="controls_inventory.json to intake + project (main path)")
    ap.add_argument("--repo", metavar="ROOT",
                    help="repo root (required with --inventory; echoed into the bundle)")
    ap.add_argument("--in-scope", metavar="FILE", dest="in_scope",
                    help="scan in_scope[] (JSON {in_scope:[...]} / list / newline-delimited); "
                         "omit = full-repo scan (all controls in scope)")
    ap.add_argument("--check", metavar="PATH",
                    help="intake-validate an inventory only (no projection); fail exit 2")
    args = ap.parse_args(argv)

    # emit diagnostics cleanly regardless of host console codepage (e.g. cp936)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.check:
        return _run_check(args.check)
    if not args.inventory:
        ap.error("--inventory <PATH> (or --check <PATH>) is required")  # exits 2 (misuse)
    if not args.repo:
        print("error: --repo <ROOT> is required with --inventory", file=sys.stderr)
        return 2
    return _run_intake_project(args.inventory, args.repo, args.in_scope)


if __name__ == "__main__":
    sys.exit(main())
