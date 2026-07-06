#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
describe_artifact — sanctioned "glance at artifact structure" primitive for /mgh-init.

The one legitimate outlet for the orchestrator's / subagent's "understand the structure
before acting" reflex (harden-mgh-init-orchestration-discipline FD5). Replaces
`py -c "import json; print(json.load(open(...))['x'][0])"` and `Read`-the-whole-big-JSON.
Cross-artifact generic, so one script beats adding `--describe` to every producer.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/sys/pathlib).

CLI contract (`--help` is the contract surface, R5.1):
  py describe_artifact.py --in <json>
       [--keys] [--count] [--sample N] [--shape] [--field a.b.c]

  --keys       top-level keys (dict) / length (list)
  --count      collection length; for a wrapper dict reports EACH list-valued key's real
               length + warns that len(wrapper) is NOT a count (prevents the
               `len({repo,clusters,truncated}) == 3` miscount)
  --sample N   first N elements of the target list
  --shape      lightweight schema: keys -> type (+ list element shape)
  --field      dotted path a.b.c narrowing the target before applying the mode

At least one of {--keys,--count,--sample,--shape,--field} is required.

stdout = JSON summary (R5.3b); stderr = diagnostics only. Exit codes (R5.3b):
0 ok · 1 input missing/malformed · 2 misuse. Idempotent, read-only, no TTY.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). describe_artifact currently has no
# sibling import, but the guard keeps it in the self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _type_name(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "dict"
    if v is None:
        return "null"
    return type(v).__name__


def _navigate(data, path: str):
    """Follow a dotted path (dict keys + int indices). Returns (value, ok)."""
    cur = data
    for seg in path.split("."):
        if isinstance(cur, list):
            if not (seg.lstrip("-").isdigit() and len(seg.lstrip("-")) > 0):
                return None, False
            idx = int(seg)
            if idx < 0 or idx >= len(cur):
                return None, False
            cur = cur[idx]
        elif isinstance(cur, dict):
            if seg not in cur:
                return None, False
            cur = cur[seg]
        else:
            return None, False
    return cur, True


def _first_list_key(d: dict):
    """First top-level key (insertion order) whose value is a list, or None."""
    for k, v in d.items():
        if isinstance(v, list):
            return k
    return None


def _element_shape(v):
    """One-level shape of a list element or scalar."""
    if isinstance(v, dict):
        return {k: _type_name(val) for k, val in v.items()}
    return _type_name(v)


def main():
    ap = argparse.ArgumentParser(
        description="describe an artifact's structure (sanctioned introspection outlet)")
    ap.add_argument("--in", dest="inp", required=True, help="path to the JSON artifact")
    ap.add_argument("--keys", action="store_true", help="top-level keys / length")
    ap.add_argument("--count", action="store_true",
                    help="collection length (warns on wrapper-dict miscount)")
    ap.add_argument("--sample", type=int, metavar="N", help="first N elements of the target list")
    ap.add_argument("--shape", action="store_true", help="lightweight schema")
    ap.add_argument("--field", metavar="a.b.c", help="narrow target via dotted path first")
    args = ap.parse_args()

    if not any([args.keys, args.count, args.sample is not None, args.shape, args.field]):
        print("error: pick at least one of --keys/--count/--sample/--shape/--field",
              file=sys.stderr)
        return 2

    p = Path(args.inp)
    if not p.is_file():
        print(f"error: artifact not found: {p}", file=sys.stderr)
        return 1
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: malformed JSON: {e}", file=sys.stderr)
        return 1

    out = {}
    if args.field:
        val, ok = _navigate(data, args.field)
        if not ok:
            print(f"error: field path not found: {args.field}", file=sys.stderr)
            return 1
        out["field"] = args.field
        out["type"] = _type_name(val)
        target = val
        if not any([args.keys, args.count, args.sample is not None, args.shape]):
            out["value"] = val
            print(json.dumps(out, ensure_ascii=False))
            return 0
    else:
        target = data

    # --keys
    if args.keys:
        if isinstance(target, dict):
            out["keys"] = list(target.keys())
            out["type"] = "dict"
        elif isinstance(target, list):
            out["type"] = "list"
            out["length"] = len(target)
        else:
            out["type"] = _type_name(target)
            out["value"] = target

    # --count
    if args.count:
        if isinstance(target, list):
            out["count"] = len(target)
        elif isinstance(target, dict):
            counts = {k: len(v) for k, v in target.items() if isinstance(v, list)}
            out["counts"] = counts
            out["top_level_keys"] = len(target)
            print(f"warn: target is a dict with {len(target)} top-level key(s); "
                  f"len(wrapper)={len(target)} is NOT a collection count — "
                  f"counts[] reports each list-valued key's real length",
                  file=sys.stderr)
        else:
            out["count"] = 1

    # --sample N
    if args.sample is not None:
        lst, over = target, None
        if isinstance(target, dict):
            k = _first_list_key(target)
            if k is None:
                print("error: --sample needs a list; target dict has no list-valued key",
                      file=sys.stderr)
                return 2
            lst, over = target[k], k
        if not isinstance(lst, list):
            print("error: --sample needs a list target (use --field to pick one)", file=sys.stderr)
            return 2
        n = max(0, args.sample)
        out["sample"] = lst[:n]
        if over:
            out["over"] = over

    # --shape
    if args.shape:
        if isinstance(target, dict):
            shp = {}
            for k, v in target.items():
                if isinstance(v, list):
                    shp[k] = {"type": "list", "length": len(v),
                              "element": _element_shape(v[0]) if v else None}
                else:
                    shp[k] = _type_name(v)
            out["shape"] = shp
        elif isinstance(target, list):
            out["shape"] = {"type": "list", "length": len(target),
                            "element": _element_shape(target[0]) if target else None}
        else:
            out["shape"] = _type_name(target)

    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
