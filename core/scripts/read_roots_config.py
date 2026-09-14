#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
read_roots_config — deterministic manager for the project read-roots config
`<target>/.mgh/read-roots.json` (schema {"v":1,"read_roots":["<abs>",…]}). The config is
the PERSISTENT half of the guard's unified read allow-set (sentinel read_roots[] ∪ this
config); the /mgh-sdr authorization gate consumes the same list BEFORE any external-repo
retrieval. This script is the only sanctioned writer: the orchestrator's job stops at
"ask the user, then call this script" — it NEVER hand-assembles the JSON.

  py read_roots_config.py --target <abs-project> --add <abs-dir> [--add <abs-dir>]…
  py read_roots_config.py --target <abs-project> --remove <abs> [--remove <abs>]…
  py read_roots_config.py --target <abs-project> --list
  py read_roots_config.py --target <abs-project> --check

Modes (mutually exclusive; at most one of --list / --check / (--add|--remove)):
  add/remove  read-modify-write the config (removals apply first, then additions — an
              entry passed to both nets out to present). EVERY --add is validated BEFORE
              any write: it must be an absolute path that exists AND is a directory
              (violator => exit 2, zero partial write). --remove needs no existence
              (it is the stale-entry self-heal path); removing an absent entry is a
              no-op. Existing-entry --add is an idempotent no-op (never duplicated).
  list        print the current entries (missing config => configured: [], exit 0).
  check       fail-loud boundary validation (R5.9): config exists, schema shape valid
              (dict + v int + read_roots list of non-blank strings) AND every entry
              exists and is a directory (a stale entry grants zero on the guard side —
              --check makes that visible; violator => exit 2 + the stale entries named).

Contract (R5.3b): stdout = one structured JSON line {target, config_path, configured[],
added[], removed[]} (check mode adds check/violations[]); stderr = human diagnostics +
the change audit (every actual mutation prints its before/after entries). Exit codes
0 ok (incl. idempotent no-op) · 1 operational error (config write failed) · 2 misuse
(bad/missing args, invalid --add, --check violations). Entries are stored AND compared
as `Path.resolve()` normal forms (`D:/x` and `D:\\x` are the same entry, matching the
guard's resolve-then-judge semantics). Unknown JSON fields are preserved; `v` is
normalized to int 1 when absent/non-int; a config that is unparsable / not a dict /
with a non-list read_roots is REPAIRED on mutation: the old file is preserved verbatim
at `read-roots.json.bad` (atomic replace) and a fresh config is written (stderr warns).
Atomic write (tmp + os.replace); idempotent (re-running any mode is safe); never
interactive (flags only). Missing config + add/remove = created fresh.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/os/sys/pathlib).
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

CONFIG_REL = Path(".mgh") / "read-roots.json"


def _eprint(*a):
    print(*a, file=sys.stderr)


def _resolve(p: str) -> Path:
    return Path(p).resolve()


def _config_path(target: Path) -> Path:
    return target / CONFIG_REL


def _read_body(path: Path) -> tuple[dict | None, str | None]:
    """(body, error). Missing file => ({}, None) — caller decides whether that is fine
    (list/add) or a violation (check). Unparsable / non-dict / non-list read_roots =>
    (None, reason) — the caller's repair path. Non-string / blank entries are dropped
    with a note (they grant nothing on the guard side)."""
    if not path.is_file():
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"unparsable JSON: {e}"
    if not isinstance(data, dict):
        return None, "not a JSON object"
    roots = data.get("read_roots")
    if not isinstance(roots, list):
        return None, "read_roots is not a list"
    cleaned = []
    for r in roots:
        if isinstance(r, str) and r.strip():
            cleaned.append(r.strip())
        else:
            _eprint(f"[read-roots] note: dropped non-string/blank entry: {r!r}")
    data["read_roots"] = cleaned
    if not isinstance(data.get("v"), int) or isinstance(data.get("v"), bool):
        data["v"] = 1
    return data, None


def _repair(path: Path, reason: str) -> None:
    """Preserve the broken config verbatim at `read-roots.json.bad` (atomic replace; a
    previous .bad is superseded) so the flow keeps moving while the evidence survives."""
    bad = path.with_name(path.name + ".bad")
    try:
        os.replace(path, bad)
        _eprint(f"[read-roots] WARN: config {reason} — preserved verbatim at {bad}; "
                f"starting fresh")
    except OSError as e:
        _eprint(f"[read-roots] WARN: config {reason}; could not preserve it ({e}) — "
                f"starting fresh")


def _audit(entries: list[str]) -> str:
    return "; ".join(entries) if entries else "(empty)"


def _mutate(target: Path, adds: list[str], removes: list[str]) -> tuple[dict, int]:
    """Validated read-modify-write. Returns (stdout_payload, exit_code)."""
    path = _config_path(target)
    body, err = _read_body(path)
    if body is None:
        _repair(path, err or "malformed")
        body = {"v": 1, "read_roots": []}
    if not isinstance(body.get("v"), int) or isinstance(body.get("v"), bool):
        body["v"] = 1                      # schema field present on any write
    current = [_resolve(r) for r in body.get("read_roots", [])]
    seen = {str(p) for p in current}

    # transactional validation: EVERY --add must exist and be a dir BEFORE any write
    add_paths: list[Path] = []
    for a in adds:
        ap = Path(a)
        if not ap.is_absolute():
            _eprint(f"error: --add must be an absolute path: {a}\n"
                    f"recipe: pass the external repo's absolute root, e.g. "
                    f"--add D:/work/front")
            return {}, 2
        rp = _resolve(a)
        if not rp.is_dir():
            _eprint(f"error: --add target is not an existing directory: {a}\n"
                    f"recipe: check the path (this gate only authorizes readable "
                    f"DIRECTORY roots; a typo here silently narrows the review).")
            return {}, 2
        if str(rp) not in seen:
            add_paths.append(rp)
            seen.add(str(rp))
    remove_set = set()
    for r in removes:
        rp = Path(r)
        if not rp.is_absolute():
            _eprint(f"error: --remove must be an absolute path: {r}")
            return {}, 2
        remove_set.add(str(_resolve(r)))
    removed = [str(p) for p in current if str(p) in remove_set]
    kept = [p for p in current if str(p) not in remove_set]
    final = kept + add_paths

    if len(final) != len(current) or removed:
        body["read_roots"] = [str(p) for p in final]
        path.parent.mkdir(parents=True, exist_ok=True)
        for a in add_paths:
            _eprint(f"[read-roots] add: {a}")
        for r in removed:
            _eprint(f"[read-roots] remove: {r}")
        _eprint(f"[read-roots] {path}: {len(current)} -> {len(final)} entries "
                f"(before: {_audit([str(p) for p in current])}; "
                f"after: {_audit([str(p) for p in final])})")
        tmp = path.with_name(path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8")
            os.replace(tmp, path)
        except OSError as e:
            _eprint(f"error: config write failed: {e}")
            return {}, 1
    else:
        _eprint(f"[read-roots] no changes ({len(current)} entries, idempotent no-op)")
    return {"target": str(target), "config_path": str(path),
            "configured": [str(p) for p in final],
            "added": [str(p) for p in add_paths],
            "removed": removed}, 0


def _check(target: Path) -> tuple[dict, int]:
    path = _config_path(target)
    body, err = _read_body(path)
    violations: list[str] = []
    if body is None:
        violations.append(f"config malformed ({err}): {path}")
    elif not path.is_file():
        violations.append(f"config not found: {path}\n"
                          f"recipe: create it with `read_roots_config.py --target "
                          f"<project> --add <abs-dir>` (or skip --check on a fresh "
                          f"project — no config = zero grants, which is valid).")
    else:
        for r in body.get("read_roots", []):
            if not _resolve(r).is_dir():
                violations.append(f"stale entry (grants zero, guard fail-closed): {r}")
    if violations:
        _eprint(f"error: read_roots_config --check: {len(violations)} violation(s):")
        for v in violations:
            _eprint(f"  - {v}")
        _eprint("recipe: `--remove <stale>` the dead entries (self-heal), or re-add "
                "the moved root; a stale entry grants NOTHING on the guard side, so "
                "the review silently loses that root until fixed.")
        return {"target": str(target), "config_path": str(path),
                "configured": list(body.get("read_roots", [])) if body else [],
                "added": [], "removed": [],
                "check": "failed", "violations": violations}, 2
    _eprint(f"[read-roots] --check ok ({path}: "
            f"{len(body.get('read_roots', []))} entries, all exist and are dirs)")
    return {"target": str(target), "config_path": str(path),
            "configured": list(body.get("read_roots", [])),
            "added": [], "removed": [], "check": "ok", "violations": []}, 0


def main():
    ap = argparse.ArgumentParser(
        description="manage the project read-roots config <target>/.mgh/read-roots.json "
                    "(the persistent read-only allow-set; /mgh-sdr's external-repo "
                    "authorization gate consumes it BEFORE retrieval)")
    ap.add_argument("--target", metavar="<abs>", help="absolute target project root")
    ap.add_argument("--add", action="append", default=[], metavar="<abs>",
                    help="absolute directory root to authorize (repeatable; must exist "
                         "and be a directory; idempotent)")
    ap.add_argument("--remove", action="append", default=[], metavar="<abs>",
                    help="absolute entry to revoke (repeatable; no existence needed; "
                         "removing an absent entry is a no-op)")
    ap.add_argument("--list", action="store_true",
                    help="print the current entries (missing config => [])")
    ap.add_argument("--check", action="store_true",
                    help="validate the config (schema + every entry exists and is a "
                         "directory; violations => exit 2)")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if not args.target:
        _eprint("error: --target <abs-project> is required")
        return 2
    target = Path(args.target)
    if not target.is_dir():
        _eprint(f"error: --target not a directory: {target}")
        return 2
    target = target.resolve()
    mode_addremove = bool(args.add or args.remove)
    if args.check and (args.list or mode_addremove):
        _eprint("error: --check takes no --list/--add/--remove (one mode per call)")
        return 2
    if args.list and mode_addremove:
        _eprint("error: --list takes no --add/--remove (one mode per call)")
        return 2
    if args.check:
        payload, code = _check(target)
    elif args.list:
        path = _config_path(target)
        body, err = _read_body(path)
        if body is None:
            _eprint(f"[read-roots] WARN: config malformed ({err}) — reporting empty")
            body = {"read_roots": []}
        payload = {"target": str(target), "config_path": str(path),
                   "configured": list(body.get("read_roots", [])),
                   "added": [], "removed": []}
        code = 0
    elif mode_addremove:
        payload, code = _mutate(target, args.add, args.remove)
    else:
        _eprint("error: nothing to do — pass one of --add/--remove/--list/--check\n"
                "recipe: authorize an external repo for this project: "
                "`read_roots_config.py --target <abs-project> --add <abs-dir>`")
        return 2
    print(json.dumps(payload, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
