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

Sentinel co-write (deterministic side-effect): alongside run_config.json the script ALSO
atomically writes `<init-dir>/.active` — the disk sentinel that activates the
block_adhoc_scripts runtime guard on hosts whose plugin process does not inherit
mid-session env (opencode): `{"domain":"mgh-init"|"mgh-ut-init" (by --run-root),
"target":<abs target>,"out_roots":[non-default --out/--rules-dir abs roots],"v":1}`.
Idempotent — the script running IS the sentinel existing; the orchestrator NEVER needs a
Bash printf recipe. `/mgh-init --resume` re-arms it via resume_state.py (plain invocation
rewrites it from run_config.target).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/os/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py write_runconfig.py --target <dir> [--format opencode|claude] [--init-dir <dir>]
       [--run-root <name>] [--scope ..] [--scope-mode defined|applicable] [--no-scout]
       [--no-codegraph] [--skip-consistency] [--merge <partials-dir>] [--include-dotfiles]
       [--include-tests] [--max-unit-bytes B] [--orch-budget-bytes B] [--max-aggregate-bytes B]
       [--scout-budget N] [--scout-batch-bytes B] [--scout-batch-cap N] [--scout-audit-pct N]
       [--language <lang>] [--rules-dir <path>] [--out <path>]

  Run-dir resolution priority: --init-dir > <target>/<--run-root> (default <target>/.mgh-init);
  run_config.json then lands at <init-dir>/run_config.json (or --out). Default --run-root
  .mgh-init is byte-equivalent to the prior hard-coded behavior.

stdout (structured JSON; stderr = diagnostics only, R5.3b):
  {"run_config": "<abs run_config.json>", "target": "<abs target>", "format": "...",
   "mode": "normal|merge", "no_scout": false, "no_codegraph": false, "skip_consistency": false,
   "sentinel": "<abs .active>"}
Exit codes (R5.3b): 0 written · 2 misuse (argparse / bad budget / missing --target).
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


def _derive_out_roots(args, target_abs: str) -> list:
    """Non-default product roots for the sentinel's out_roots[]: `--out` and `--rules-dir`
    (each resolved ABSOLUTE against cwd) when they differ from the defaults. Default product
    roots (<target>/.mgh-init | .mgh-ut-init, .claude/rules, docs/security-controls |
    docs/test-conventions, <target>/AGENTS.md) are BUILT INTO the guard's allowlist and are
    NEVER listed (design D1: out_roots[] only EXTENDS, it does not mirror). `--out` here is
    the run_config.json path (not a rules dir) — its parent dir is the custom run root."""
    roots = []
    if args.out:
        try:
            roots.append(str(Path(args.out).resolve().parent))
        except (OSError, ValueError):
            pass
    if args.rules_dir:
        defaults = {
            ".mgh-init": str((Path(target_abs) / "docs" / "security-controls").resolve()),
            ".mgh-ut-init": str((Path(target_abs) / "docs" / "test-conventions").resolve()),
        }
        try:
            rd = str(Path(args.rules_dir).resolve())
            if rd != defaults.get(args.run_root):
                roots.append(rd)
        except (OSError, ValueError):
            pass
    # de-dup, order-stable (an --out inside --rules-dir would otherwise list the parent twice)
    seen, out = set(), []
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser(
        description="atomically write <target>/.mgh-init/run_config.json (start-state intent)")
    ap.add_argument("--target", required=True,
                    help="target project root (recorded ABSOLUTE; the run's repo root)")
    ap.add_argument("--format", default="opencode", choices=["opencode", "claude"],
                    help="rule format (default opencode; pass claude for .claude/rules/*.md)")
    ap.add_argument("--init-dir",
                    help="run dir full path (highest priority, overrides --run-root)")
    ap.add_argument("--run-root", default=".mgh-init",
                    help="run dir NAME under <target> (default .mgh-init; used when --init-dir absent)")
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
    ap.add_argument("--include-tests", action="store_true",
                    help="scan test source trees (src/test | src/tests prefix; "
                         "tests/__tests__/__mocks__/spec/specs dir segment)")
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
    if args.init_dir:
        init_dir = Path(args.init_dir).resolve()
    else:
        init_dir = (Path(target_abs) / args.run_root).resolve()
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
        "include_tests": bool(args.include_tests),
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
    # Sentinel co-write (deterministic side-effect): the disk activation signal for the
    # runtime guard. domain derives from --run-root (init vs ut-init share this writer);
    # target reuses the already-computed Windows-native target_abs. Idempotent overwrite.
    sentinel_path = init_dir / ".active"
    sentinel = {
        "domain": "mgh-ut-init" if args.run_root == ".mgh-ut-init" else "mgh-init",
        "target": target_abs,
        "out_roots": _derive_out_roots(args, target_abs),
        "v": 1,
    }
    _atomic_write_json(sentinel_path, sentinel)
    ack = {
        "run_config": str(rc_path),
        "target": target_abs,
        "format": args.format,
        "mode": run_config["mode"],
        "no_scout": run_config["no_scout"],
        "no_codegraph": run_config["no_codegraph"],
        "skip_consistency": run_config["skip_consistency"],
        "sentinel": str(sentinel_path),
    }
    print(f"[write_runconfig] wrote {rc_path} (mode={run_config['mode']}, "
          f"format={args.format}, no_scout={run_config['no_scout']}) + sentinel "
          f"{sentinel_path}", file=sys.stderr)
    print(json.dumps(ack, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
