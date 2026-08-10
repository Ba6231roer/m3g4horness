#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
derive_mutators — deterministic pitest mutator derivation for /mgh-ut-init.

Parses `<target>`'s pitest configuration (pom.xml / build.gradle / build.gradle.kts) and
emits `<target>/.mgh-ut-init/default_mutators.json` for downstream /mgh-ut --mutators
consumption. No pitest config found → builtin pitest standard mutator set
(`source:"builtin-fallback"`) + parser_notes disclosure.

Pinned fallback set (pitest official DEFAULTS group):
  CONDITIONALS_BOUNDARY, INCREMENTS, INVERT_NEGS, MATH, NEGATE_CONDITIONALS,
  RETURN_VALS, VOID_METHOD_CALLS.

Parsing is tolerant regex over the build files (no third-party XML/parser dependency):
  pom.xml          — find `<mutators>…</mutators>` and extract `<mutator>NAME</mutator>`.
  build.gradle*    — find `mutators = […]` / `mutators = setOf(…)` and extract quoted tokens.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/os/pathlib/re/sys).
CLI contract (`--help` is the contract surface, R5.1):
  py derive_mutators.py --repo <target> [--out <dir>] [--check <out-dir>]
stdout (structured JSON; stderr = diagnostics only, R5.3b):
  {"source":"pitest-config|builtin-fallback","mutators":[...],"parser_notes":[...],
   "output":"<abs default_mutators.json>"}
Exit codes (R5.3b): 0 ok · 1 general · 2 misuse / --check violation. Idempotent (overwrite),
no TTY.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path

# Self-locate this script's dir (self-contained family, R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

BUILTIN_MUTATORS = [
    "CONDITIONALS_BOUNDARY", "INCREMENTS", "INVERT_NEGS", "MATH",
    "NEGATE_CONDITIONALS", "RETURN_VALS", "VOID_METHOD_CALLS",
]
_MUTATORS_BLOCK = re.compile(r"<mutators>(.*?)</mutators>", re.DOTALL)
_MUTATOR_TAG = re.compile(r"<mutator>\s*(.*?)\s*</mutator>", re.DOTALL)
_GRADLE_BRACKET = re.compile(r"mutators\s*=\s*\[(.*?)\]", re.DOTALL)
_GRADLE_SETOF = re.compile(r"mutators\s*=\s*setOf\s*\((.*?)\)", re.DOTALL)
_QUOTED = re.compile(r"['\"]([A-Za-z0-9_,\-]+)['\"]")


def _parse_pom(text: str) -> tuple[list, list]:
    notes = []
    mutators = []
    if "pitest" not in text:
        return mutators, notes
    for block in _MUTATORS_BLOCK.findall(text):
        for m in _MUTATOR_TAG.findall(block):
            name = m.strip()
            if name and name not in mutators:
                mutators.append(name)
    if not mutators:
        notes.append("pom.xml mentions pitest but no <mutators> block found")
    return mutators, notes


def _parse_gradle(text: str, notes: list) -> list:
    mutators = []
    # bracket form (groovy):  mutators = ["DEFAULTS", "INCREMENTS"]
    m = _GRADLE_BRACKET.search(text)
    toks = _QUOTED.findall(m.group(1)) if m else []
    if not toks:
        # kts form:  mutators = setOf("DEFAULTS", "INCREMENTS")
        m = _GRADLE_SETOF.search(text)
        toks = _QUOTED.findall(m.group(1)) if m else []
    for tok in toks:
        if tok and tok not in mutators:
            mutators.append(tok)
    return mutators


def _derive(repo: Path) -> dict:
    """Return {source, mutators, parser_notes}."""
    notes = []
    pom = repo / "pom.xml"
    if pom.is_file():
        notes.append(f"checked {pom.name}")
        mutators, mnotes = _parse_pom(pom.read_text(encoding="utf-8", errors="replace"))
        notes.extend(mnotes)
        if mutators:
            return {"source": "pitest-config", "mutators": mutators, "parser_notes": notes}
    for name in ("build.gradle", "build.gradle.kts"):
        p = repo / name
        if not p.is_file():
            continue
        notes.append(f"checked {name}")
        mutators = _parse_gradle(p.read_text(encoding="utf-8", errors="replace"), notes)
        if mutators:
            return {"source": "pitest-config", "mutators": mutators, "parser_notes": notes}
    notes.append("no pitest mutator config found in pom.xml / build.gradle / "
                 "build.gradle.kts — using builtin pitest standard set")
    return {"source": "builtin-fallback", "mutators": list(BUILTIN_MUTATORS),
            "parser_notes": notes}


def _atomic_write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _run_check(outdir: Path) -> int:
    violations = []
    p = outdir / "default_mutators.json"
    if not p.is_file():
        violations.append({"file": "default_mutators.json", "issue": "missing"})
    else:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            violations.append({"file": "default_mutators.json", "issue": f"malformed: {e}"})
            data = None
        if isinstance(data, dict):
            if data.get("source") not in ("pitest-config", "builtin-fallback"):
                violations.append({"file": "default_mutators.json",
                                   "issue": "source must be pitest-config|builtin-fallback"})
            if not isinstance(data.get("mutators"), list) or not data["mutators"]:
                violations.append({"file": "default_mutators.json",
                                   "issue": "mutators must be a non-empty list"})
            if not isinstance(data.get("parser_notes"), list):
                violations.append({"file": "default_mutators.json",
                                   "issue": "parser_notes must be a list"})
        else:
            violations.append({"file": "default_mutators.json",
                               "issue": "wrapper must be {source,mutators[],parser_notes[]}"})
    ok = not violations
    print(f"[derive_mutators --check] {outdir}: {'OK' if ok else f'{len(violations)} violation(s)'}",
          file=sys.stderr)
    print(json.dumps({"check": "derive_mutators", "ok": ok, "violations": violations},
                     ensure_ascii=False))
    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(
        description="deterministically derive pitest default mutators for /mgh-ut-init")
    ap.add_argument("--repo", default=".", help="target project root (default .)")
    ap.add_argument("--out", help="run dir for default_mutators.json (default <repo>/.mgh-ut-init)")
    ap.add_argument("--check", metavar="<out-dir>",
                    help="validate an existing run-dir's default_mutators.json (R5.9); exit 0/2")
    # Emit JSON / glyphs cleanly regardless of host console codepage (e.g. cp936/gbk).
    # Before parse_args so --help is utf-8 too. No-op on StringIO (in-process tests).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = ap.parse_args()

    if args.check:
        return _run_check(Path(args.check).resolve())
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"error: --repo not a directory: {repo}", file=sys.stderr)
        return 1
    outdir = Path(args.out) if args.out else (repo / ".mgh-ut-init")
    outdir.mkdir(parents=True, exist_ok=True)

    result = _derive(repo)
    out_path = (outdir / "default_mutators.json").resolve()
    _atomic_write_json(out_path, result)
    print(f"[derive_mutators] source={result['source']} "
          f"mutators={len(result['mutators'])} -> {out_path}", file=sys.stderr)
    print(json.dumps({**result, "output": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
