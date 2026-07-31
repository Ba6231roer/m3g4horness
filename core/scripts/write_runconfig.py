#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
write_runconfig — atomic writer of `<target>/.mgh-init/run_config.json` for /mgh-init.

The start-state intent record: it captures the invocation flags that DECIDE the step graph
(format / scope / no_scout / no_codegraph / skip_consistency / merge / budgets / scout-*),
written once at step 0 (after arg parse, before spending tokens). `resume_state.py` consumes
it to resolve optional/codepath branches, so `/mgh-init --resume` is stateless — the user
NEVER re-types flags. It is the START-state counterpart to the terminal `init_manifest.json`
(version/counts/provenance); the two have disjoint lifecycles and do not replace each other.

Atomic (`.tmp` + `os.replace`): a SIGKILL mid-write leaves at most a stale `.tmp`, never a
truncated/half-written JSON (承 discover_controls._atomic_write_json). Gitignored with the
rest of `.mgh-init/`.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/os/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py write_runconfig.py --target <dir> --format opencode|claude [--init-dir <dir>]
       [--scope ..] [--scope-mode defined|applicable] [--no-scout] [--no-codegraph]
       [--skip-consistency] [--merge <partials-dir>] [--include-dotfiles]
       [--max-unit-bytes B] [--orch-budget-bytes B] [--max-aggregate-bytes B]
       [--scout-budget N] [--scout-batch-bytes B] [--scout-batch-cap N] [--scout-audit-pct N]
       [--language <lang>] [--rules-dir <path>] [--out <path>]

stdout (structured JSON; stderr = diagnostics only, R5.3b):
  {"run_config": "<abs run_config.json>", "target": "<abs target>", "format": "...",
   "mode": "normal|merge", "no_scout": false, "no_codegraph": false, "skip_consistency": false}
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
# host-agent invocation (direct `py`/`python`). write_runconfig currently has no sibling
# import, but the guard keeps it in the self-contained family (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_MAX_UNIT_BYTES = 192 * 1024      # 192KB
DEFAULT_ORCH_BUDGET_BYTES = 64 * 1024    # 64KB
DEFAULT_MAX_AGGREGATE_BYTES = 256 * 1024  # 256KB
DEFAULT_SCOUT_BATCH_BYTES = 96 * 1024    # 96KB
DEFAULT_SCOUT_BATCH_CAP = 40
DEFAULT_SCOUT_AUDIT_PCT = 15


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
        description="atomically write <target>/.mgh-init/run_config.json (start-state intent)")
    ap.add_argument("--target", required=True,
                    help="target project root (recorded ABSOLUTE; the run's repo root)")
    ap.add_argument("--format", required=True, choices=["opencode", "claude"],
                    help="rule format (also selects rule_path layout; required)")
    ap.add_argument("--init-dir",
                    help=".mgh-init output dir (default: <target>/.mgh-init)")
    ap.add_argument("--scope", help="path:<dir>|package:<pkg>|file:<glob>")
    ap.add_argument("--scope-mode", choices=["defined", "applicable"], default="defined")
    ap.add_argument("--no-scout", action="store_true",
                    help="skip LLM scout discovery (legacy regex-only)")
    ap.add_argument("--no-codegraph", action="store_true",
                    help="skip optional codegraph enrichment")
    ap.add_argument("--skip-consistency", action="store_true", help="skip T4")
    ap.add_argument("--merge", metavar="<partials-dir>",
                    help="merge multiple scoped runs (sets mode=merge; then STOP)")
    ap.add_argument("--include-dotfiles", action="store_true",
                    help="scan dot-prefixed paths (.opencode/.claude/.codegraph/.github/.env)")
    ap.add_argument("--max-unit-bytes", type=int, default=DEFAULT_MAX_UNIT_BYTES)
    ap.add_argument("--orch-budget-bytes", type=int, default=DEFAULT_ORCH_BUDGET_BYTES)
    ap.add_argument("--max-aggregate-bytes", type=int, default=DEFAULT_MAX_AGGREGATE_BYTES)
    ap.add_argument("--scout-budget", type=int, default=0, help="0 = all targets")
    ap.add_argument("--scout-batch-bytes", type=int, default=DEFAULT_SCOUT_BATCH_BYTES)
    ap.add_argument("--scout-batch-cap", type=int, default=DEFAULT_SCOUT_BATCH_CAP)
    ap.add_argument("--scout-audit-pct", type=int, default=DEFAULT_SCOUT_AUDIT_PCT)
    ap.add_argument("--language", default=None)
    ap.add_argument("--rules-dir", default=None,
                    help="opencode detail dir (default <target>/docs/security-controls)")
    ap.add_argument("--out", default=None,
                    help="explicit run_config.json path (default <init-dir>/run_config.json)")
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
                       ("--max-aggregate-bytes", args.max_aggregate_bytes),
                       ("--scout-batch-bytes", args.scout_batch_bytes)):
        if _parse_bytes(label, raw) < 0:
            return 2
    for label, raw in (("--scout-budget", args.scout_budget),
                       ("--scout-batch-cap", args.scout_batch_cap),
                       ("--scout-audit-pct", args.scout_audit_pct)):
        try:
            if int(raw) < 0:
                print(f"error: {label} must be >= 0 (got {raw})", file=sys.stderr)
                return 2
        except (TypeError, ValueError):
            print(f"error: {label} must be an integer (got {raw!r})", file=sys.stderr)
            return 2

    target_abs = str(Path(args.target).resolve())
    init_dir = Path(args.init_dir).resolve() if args.init_dir \
        else (Path(target_abs) / ".mgh-init").resolve()
    rc_path = Path(args.out).resolve() if args.out else (init_dir / "run_config.json").resolve()

    run_config = {
        "target": target_abs,
        "format": args.format,
        "mode": "merge" if args.merge else "normal",
        "scope": args.scope,
        "scope_mode": args.scope_mode,
        "no_scout": bool(args.no_scout),
        "no_codegraph": bool(args.no_codegraph),
        "skip_consistency": bool(args.skip_consistency),
        "include_dotfiles": bool(args.include_dotfiles),
        "merge": args.merge,
        "merge_partials_dir": args.merge,
        "language": args.language,
        "rules_dir": args.rules_dir,
        "budgets": {
            "max_unit_bytes": args.max_unit_bytes,
            "orch_budget_bytes": args.orch_budget_bytes,
            "max_aggregate_bytes": args.max_aggregate_bytes,
        },
        "scout": {
            "budget": args.scout_budget,
            "batch_bytes": args.scout_batch_bytes,
            "batch_cap": args.scout_batch_cap,
            "audit_pct": args.scout_audit_pct,
        },
    }
    _atomic_write_json(rc_path, run_config)
    ack = {
        "run_config": str(rc_path),
        "target": target_abs,
        "format": args.format,
        "mode": run_config["mode"],
        "no_scout": run_config["no_scout"],
        "no_codegraph": run_config["no_codegraph"],
        "skip_consistency": run_config["skip_consistency"],
    }
    print(f"[write_runconfig] wrote {rc_path} (mode={run_config['mode']}, "
          f"format={args.format}, no_scout={run_config['no_scout']})", file=sys.stderr)
    print(json.dumps(ack, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
