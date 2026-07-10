#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
merge_memory — deterministic memory-merge for /mgh-sra: accumulate user
clarification answers into the project-level business_context.json by `fact_key`,
idempotently, for cross-iteration reuse.

Memory lives at <project>/.mgh-sra/business_context.json (project root = the dir
containing openspec/; NOT inside any change — survives across changes). Each
answer is upserted into clarifications[] by fact_key: an existing fact_key is
updated IN PLACE (with updated_at) and never duplicated; a new fact_key is
appended. First run creates the file with version:1. All writes land under
MGH_TARGET (the project subtree). See core/contracts/sra/business-context.md.

Memory is user-asserted, not code truth (explicit code/proposal declarations
override memory); this script only persists the Q&A log — it does not arbitrate
against code.

Zero runtime deps (Python >=3.10 stdlib: argparse/datetime/json/sys/pathlib).

CLI contract (`--help` is the contract surface, R5.1):
  py merge_memory.py --memory <path> --answers <json-file>
  py merge_memory.py --check <memory-path>

  --memory <path>      path to business_context.json (under <project>/.mgh-sra/)
  --answers <json>     JSON file: {"<fact_key>": "<value>", ...} OR
                       [{"fact_key": "..", "value": ".."}, ...]
  --check <path>       validate memory shape (version + clarifications[] each with
                       fact_key/value/source) and fact_key uniqueness; exit 2 on
                       violation.

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"memory":"<path>","updated":N,"appended":N,"total_clarifications":N,"created":bool}
In --check mode: {"check":"memory","ok":bool,"clarifications":N,"violations":[...]}.

Exit codes (R5.3b): 0 ok · 1 file missing / JSON malformed ·
2 misuse (argparse) or shape / fact_key violation.
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_EMPTY = {"version": 1, "roles": [], "domains": [], "sensitive_fields": [],
          "interface_authz": [], "business_rules": [], "clarifications": []}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_answers(path: Path):
    """Return [(fact_key, value)] from a JSON object {k:v} or list[{fact_key,value}]."""
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    if isinstance(data, dict):
        for k, v in data.items():
            out.append((str(k), v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)))
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict) or "fact_key" not in item or "value" not in item:
                print(f"error: answer entry missing fact_key/value: {item}", file=sys.stderr)
                sys.exit(2)
            v = item["value"]
            out.append((str(item["fact_key"]),
                        v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)))
    else:
        print("error: --answers JSON must be an object or a list", file=sys.stderr)
        sys.exit(2)
    return out


def _check_shape(mem) -> tuple[bool, list]:
    v = []
    if not isinstance(mem, dict):
        return False, ["top-level JSON is not an object"]
    if not isinstance(mem.get("version"), int):
        v.append("`version` missing or not an int")
    cl = mem.get("clarifications")
    if not isinstance(cl, list):
        v.append("`clarifications` missing or not a list")
        return (len(v) == 0), v
    seen = set()
    for i, c in enumerate(cl):
        if not isinstance(c, dict):
            v.append(f"clarifications[{i}]: not an object")
            continue
        fk = c.get("fact_key")
        if not isinstance(fk, str) or not fk.strip():
            v.append(f"clarifications[{i}]: missing/empty `fact_key`")
        elif fk in seen:
            v.append(f"clarifications[{i}]: duplicate `fact_key` {fk!r}")
        else:
            seen.add(fk)
        if "value" not in c:
            v.append(f"clarifications[{i}]: missing `value`")
        if c.get("source") != "user-asserted":
            v.append(f"clarifications[{i}]: `source` must be 'user-asserted'")
    return (len(v) == 0), v


def _run_merge(args):
    memory_path = Path(args.memory).resolve()
    if memory_path.is_file():
        try:
            mem = json.loads(memory_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"error: memory malformed: {e}", file=sys.stderr)
            return 1
        if not isinstance(mem, dict):
            print("error: memory top-level JSON is not an object", file=sys.stderr)
            return 2
        created = False
        mem.setdefault("version", 1)
        mem.setdefault("clarifications", [])
    else:
        mem = json.loads(json.dumps(_EMPTY))  # deep copy of the empty skeleton
        created = True

    answers = _load_answers(Path(args.answers))
    cl = mem["clarifications"] if isinstance(mem.get("clarifications"), list) else []
    by_key = {c.get("fact_key"): i for i, c in enumerate(cl)
              if isinstance(c, dict) and isinstance(c.get("fact_key"), str)}
    updated, appended = 0, 0
    for fk, val in answers:
        if fk in by_key:
            cl[by_key[fk]] = {"fact_key": fk, "value": val,
                              "source": "user-asserted", "updated_at": _now_iso()}
            updated += 1
        else:
            by_key[fk] = len(cl)
            cl.append({"fact_key": fk, "value": val, "source": "user-asserted",
                       "updated_at": None})
            appended += 1
    mem["clarifications"] = cl

    ok, violations = _check_shape(mem)
    if not ok:
        print(f"error: merged memory fails shape check: {violations}", file=sys.stderr)
        return 2

    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"memory": str(memory_path), "updated": updated, "appended": appended,
               "total_clarifications": len(cl), "created": created}
    print(f"[merge_memory] {memory_path}: updated={updated} appended={appended} "
          f"total={len(cl)} created={created}", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _run_check(path):
    memory_path = Path(path).resolve()
    if not memory_path.is_file():
        print(f"error: memory not found: {memory_path}", file=sys.stderr)
        return 1
    try:
        mem = json.loads(memory_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: memory malformed: {e}", file=sys.stderr)
        return 1
    ok, violations = _check_shape(mem)
    n = len(mem.get("clarifications", [])) if isinstance(mem, dict) else 0
    summary = {"check": "memory", "ok": ok, "clarifications": n, "violations": violations}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[merge_memory] --check {memory_path}: clarifications={n} ok={ok} "
          f"violations={len(violations)}", file=sys.stderr)
    return 0 if ok else 2


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="memory-merge for /mgh-sra: idempotent fact_key accumulation "
                    "into project-level business_context.json")
    ap.add_argument("--memory", help="path to business_context.json")
    ap.add_argument("--answers", help="JSON file of answers (object or list)")
    ap.add_argument("--check", nargs="?", const="", default=None, metavar="PATH",
                    help="validate memory shape + fact_key uniqueness at PATH")
    args = ap.parse_args()

    if args.check is not None:
        target = args.check.strip() or (args.memory or "").strip()
        if not target:
            print("error: --check needs a memory path (or pair with --memory)", file=sys.stderr)
            return 2
        return _run_check(target)
    if not args.memory or not args.answers:
        print("error: --memory and --answers are required (use --check <path> to validate)",
              file=sys.stderr)
        return 2
    return _run_merge(args)


if __name__ == "__main__":
    sys.exit(main())
