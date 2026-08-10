#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
write_ut_runconfig — atomic writer of `<target>/.mgh-ut-init/run_config.json` for /mgh-ut-init.

The start-state intent record for the ut-init pipeline (copied from init's
`write_runconfig.py`; init's original is untouched). It captures the invocation flags
that DECIDE the ut step graph (format / scope / language / skip_consistency / sampling
budgets / request-context budgets), written once at step 0 (after arg parse, before
spending tokens). `resume_ut_init_state.py` consumes it so `/mgh-ut-init --resume` is
stateless — the user NEVER re-types flags. It is the START-state counterpart to the
terminal `ut_manifest.json` (version/counts/provenance); the two have disjoint lifecycles
and do not replace each other.

Atomic (`.tmp` + `os.replace`): a SIGKILL mid-write leaves at most a stale `.tmp`, never a
truncated/half-written JSON. Gitignored with the rest of `.mgh-ut-init/`.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/os/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py write_ut_runconfig.py --target <dir> --format opencode|claude [--init-dir <dir>]
       [--run-root <name>] [--scope ..] [--language <lang>] [--skip-consistency]
       [--uniform-sample N] [--hetero-sample N] [--subsplit-threshold F]
       [--max-unit-bytes B] [--orch-budget-bytes B] [--max-aggregate-bytes B]

  Run-dir resolution priority: --init-dir > <target>/<--run-root> (default
  <target>/.mgh-ut-init); run_config.json then lands at <init-dir>/run_config.json.

stdout (structured JSON; stderr = diagnostics only, R5.3b):
  {"run_config": "<abs run_config.json>", "target": "<abs target>", "format": "...",
   "mode": "normal", "skip_consistency": false}
Exit codes (R5.3b): 0 written · 2 misuse (argparse / bad budget / missing --target/--format).
Idempotent (create-if-not-exists + overwrite), no TTY.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

# Self-locate this script's dir so any future sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`). (R5.3a self-contained family.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_MAX_UNIT_BYTES = 192 * 1024      # 192KB
DEFAULT_ORCH_BUDGET_BYTES = 64 * 1024    # 64KB
DEFAULT_MAX_AGGREGATE_BYTES = 256 * 1024  # 256KB
DEFAULT_UNIFORM_SAMPLE = 4
DEFAULT_HETERO_SAMPLE = 8
DEFAULT_SUBSPLIT_THRESHOLD = 0.8


def _parse_bytes(label: str, raw) -> int:
    """Non-negative integer byte budget; exit 2 on misuse (R5.3b)."""
    try:
        v = int(raw)
    except (TypeError, ValueError):
        print(f"error: {label} must be a non-negative integer (got {raw!r})", file=sys.stderr)
        return -1
    if v < 0:
        print(f"error: {label} must be >= 0 (got {v})", file=sys.stderr)
        return -1
    return v


def _atomic_write_json(path: Path, obj):
    """Write `<path>.tmp` then `os.replace` (atomic on POSIX & same-volume Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(
        description="atomically write <target>/.mgh-ut-init/run_config.json (start-state intent)")
    ap.add_argument("--target", required=True,
                    help="target project root (recorded ABSOLUTE; the run's repo root)")
    ap.add_argument("--format", required=True, choices=["opencode", "claude"],
                    help="rule format (also selects rule_path layout; required)")
    ap.add_argument("--init-dir",
                    help="run dir full path (highest priority, overrides --run-root)")
    ap.add_argument("--run-root", default=".mgh-ut-init",
                    help="run dir NAME under <target> (default .mgh-ut-init; used when --init-dir absent)")
    ap.add_argument("--scope", help="path:<dir>|package:<pkg>|file:<glob>")
    ap.add_argument("--language", default=None, help="target language (default: JVM)")
    ap.add_argument("--skip-consistency", action="store_true", help="skip the consistency pass")
    ap.add_argument("--uniform-sample", type=int, default=DEFAULT_UNIFORM_SAMPLE,
                    help="sample size for uniform groups (default 4)")
    ap.add_argument("--hetero-sample", type=int, default=DEFAULT_HETERO_SAMPLE,
                    help="sample size for heterogeneous groups (default 8)")
    ap.add_argument("--subsplit-threshold", type=float, default=DEFAULT_SUBSPLIT_THRESHOLD,
                    help="dominant-annotation ratio >= this counts a group uniform (default 0.8)")
    ap.add_argument("--max-unit-bytes", type=int, default=DEFAULT_MAX_UNIT_BYTES)
    ap.add_argument("--orch-budget-bytes", type=int, default=DEFAULT_ORCH_BUDGET_BYTES)
    ap.add_argument("--max-aggregate-bytes", type=int, default=DEFAULT_MAX_AGGREGATE_BYTES)
    # Emit JSON / glyphs cleanly regardless of host console codepage (e.g. cp936/gbk).
    # Before parse_args so --help is utf-8 too. No-op on StringIO (in-process tests).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = ap.parse_args()

    for label, raw in (("--max-unit-bytes", args.max_unit_bytes),
                       ("--orch-budget-bytes", args.orch_budget_bytes),
                       ("--max-aggregate-bytes", args.max_aggregate_bytes)):
        if _parse_bytes(label, raw) < 0:
            return 2
    for label, raw in (("--uniform-sample", args.uniform_sample),
                       ("--hetero-sample", args.hetero_sample)):
        try:
            if int(raw) < 1:
                print(f"error: {label} must be >= 1 (got {raw})", file=sys.stderr)
                return 2
        except (TypeError, ValueError):
            print(f"error: {label} must be an integer (got {raw!r})", file=sys.stderr)
            return 2
    try:
        if not (0.0 <= args.subsplit_threshold <= 1.0):
            print(f"error: --subsplit-threshold must be in [0,1] (got {args.subsplit_threshold})",
                  file=sys.stderr)
            return 2
    except TypeError:
        print(f"error: --subsplit-threshold must be a float (got {args.subsplit_threshold!r})",
              file=sys.stderr)
        return 2

    target_abs = str(Path(args.target).resolve())
    if args.init_dir:
        init_dir = Path(args.init_dir).resolve()
    else:
        init_dir = (Path(target_abs) / args.run_root).resolve()
    rc_path = (init_dir / "run_config.json").resolve()

    run_config = {
        "target": target_abs,
        "format": args.format,
        "mode": "normal",
        "scope": args.scope,
        "language": args.language,
        "skip_consistency": bool(args.skip_consistency),
        "sampling": {
            "uniform_sample": args.uniform_sample,
            "hetero_sample": args.hetero_sample,
            "subsplit_threshold": args.subsplit_threshold,
        },
        "budgets": {
            "max_unit_bytes": args.max_unit_bytes,
            "orch_budget_bytes": args.orch_budget_bytes,
            "max_aggregate_bytes": args.max_aggregate_bytes,
        },
    }
    _atomic_write_json(rc_path, run_config)
    ack = {
        "run_config": str(rc_path),
        "target": target_abs,
        "format": args.format,
        "mode": run_config["mode"],
        "skip_consistency": run_config["skip_consistency"],
    }
    print(f"[write_ut_runconfig] wrote {rc_path} (mode={run_config['mode']}, "
          f"format={args.format}, skip_consistency={run_config['skip_consistency']})",
          file=sys.stderr)
    print(json.dumps(ack, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
