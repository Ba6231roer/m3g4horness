#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
write_runconfig — atomic writer of `<target>/.mgh-init/run_config.json` for /mgh-init.

The start-state intent record: it captures the invocation flags that DECIDE the step graph
(format / scope / no_scout / no_codegraph / skip_consistency / budgets / scout-*; --merge is REFUSED — see the recipe at the refusal site),
written once at step 0 (after arg parse, before spending tokens). `resume_state.py` consumes
it to resolve optional/codepath branches, so `/mgh-init --resume` is stateless — the user
NEVER re-types flags. It is the START-state counterpart to the terminal `init_manifest.json`
(version/counts/provenance); the two have disjoint lifecycles and do not replace each other.

Atomic (`.tmp` + `os.replace`): a SIGKILL mid-write leaves at most a stale `.tmp`, never a
truncated/half-written JSON (承 discover_controls._atomic_write_json). Gitignored with the
rest of `.mgh-init/` — the gitignore is CO-WRITTEN by this script (see below), making the
promise mechanical instead of aspirational.

Run-dir gitignore co-write (deterministic side-effect, same posture as the sentinel):
alongside run_config.json the script ALSO writes `<init-dir>/.gitignore` with the single
line `*` — the run dir's checkpoints / inputs / progress artifacts stay out of the target
project's git (bank environments: leaked scan products are a real risk; the shells and
contracts promise this gitignore and this script is its single deterministic writer).
Idempotent — an existing `.gitignore` is NEVER rewritten or appended (user-tuned file
stays); the target project's own root `.gitignore` is zero-touch (the file lands INSIDE
the run dir only). `--check` reports a missing gitignore at WARN level (not blocking:
isolation is a promise, not run correctness).

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
  py write_runconfig.py --target <dir> --check   (verify on-disk run state, no writes)

  Run-dir resolution priority: --init-dir > <target>/<--run-root> (default <target>/.mgh-init);
  run_config.json then lands at <init-dir>/run_config.json (or --out). Default --run-root
  .mgh-init is byte-equivalent to the prior hard-coded behavior.

stdout (structured JSON; stderr = diagnostics only, R5.3b):
  {"run_config": "<abs run_config.json>", "target": "<abs target>", "format": "...",
   "no_scout": false, "no_codegraph": false, "skip_consistency": false,
   "sentinel": "<abs .active>", "gitignore": "<abs .gitignore>"}
  --check: {"check": "ok", "run_config": .., "sentinel": .., "gitignore": ..,
            "sentinel_present": bool, "gitignore_present": bool}
Exit codes (R5.3b): 0 written · 2 misuse (argparse / bad budget / missing --target) or
--check on a bootstrapped-less run dir. Idempotent (create-if-not-exists + overwrite),
no TTY.
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
DEFAULT_MAX_AGGREGATE_BYTES = 96 * 1024  # 96KB (= 98304) — uniform --max-aggregate-bytes default
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


def _atomic_write_text(path: Path, text: str):
    """Write `<path>.tmp` then `os.replace` (atomic on POSIX & same-volume Windows),
    with `flush` + `os.fsync` BEFORE the replace: os.replace's atomicity does NOT
    flush file CONTENT — without fsync a power cut can land a zero-length
    run_config (the crash-recovery anchor) after a "successful" replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _atomic_write_json(path: Path, obj):
    _atomic_write_text(path, json.dumps(obj, indent=2, ensure_ascii=False))


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
    ap.add_argument("--max-aggregate-bytes", type=int, default=DEFAULT_MAX_AGGREGATE_BYTES,
                    help="aggregate-stage input byte cap (default 98304 = 96KB; worst-case "
                         "~2 bytes/token → ≤ ~48K tokens per dispatched aggregate request)")
    ap.add_argument("--scout-budget", type=int, default=0, help="0 = all targets")
    ap.add_argument("--scout-batch-bytes", type=int, default=DEFAULT_SCOUT_BATCH_BYTES)
    ap.add_argument("--scout-batch-cap", type=int, default=DEFAULT_SCOUT_BATCH_CAP)
    ap.add_argument("--scout-audit-pct", type=int, default=DEFAULT_SCOUT_AUDIT_PCT)
    ap.add_argument("--language", default=None)
    ap.add_argument("--rules-dir", default=None,
                    help="opencode detail dir (default <target>/docs/security-controls)")
    ap.add_argument("--out", default=None,
                    help="explicit run_config.json path (default <init-dir>/run_config.json)")
    ap.add_argument("--check", action="store_true",
                    help="verify on-disk run state (run_config.json + sentinel + "
                         "gitignore) WITHOUT writing; missing run_config.json exits 2, "
                         "missing sentinel/gitignore is a warn-level stderr report "
                         "(gitignore absence = run dir not git-isolated)")
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

    # --merge refusal (H11(b)): the mode has NO deterministic implementation
    # (no merge script exists anywhere) — refuse with a recipe instead of
    # recording a mode the pipeline cannot execute, NEVER silently swallow it.
    if args.merge:
        print("error: --merge is not supported: no deterministic merger exists, so "
              "the mode has no executable path. Run scoped passes independently "
              "(--scope path:<module>, one run per module) — the partial products "
              "stay independent on disk; cross-module comparison is manual. "
              "NEVER hand-merge inventories via LLM (no gate, no deterministic "
              "dedup).", file=sys.stderr)
        return 2

    target_abs = str(Path(args.target).resolve())
    if args.init_dir:
        init_dir = Path(args.init_dir).resolve()
    else:
        init_dir = (Path(target_abs) / args.run_root).resolve()
    rc_path = Path(args.out).resolve() if args.out else (init_dir / "run_config.json").resolve()
    sentinel_path = init_dir / ".active"
    gitignore_path = init_dir / ".gitignore"

    if args.check:
        if not rc_path.is_file():
            print(f"error: run_config.json missing at {rc_path} (run not bootstrapped; "
                  f"re-run write_runconfig without --check)", file=sys.stderr)
            return 2
        sent_present = sentinel_path.is_file()
        gi_present = gitignore_path.is_file()
        if not sent_present:
            print(f"warn: sentinel missing at {sentinel_path} (runtime guard dormant; "
                  f"re-run write_runconfig or resume_state --rearm-sentinel)", file=sys.stderr)
        if not gi_present:
            print(f"warn: {gitignore_path} missing (run dir is NOT git-isolated; "
                  f"re-run write_runconfig without --check to co-write it)", file=sys.stderr)
        print(json.dumps({"check": "ok", "run_config": str(rc_path),
                          "sentinel": str(sentinel_path), "gitignore": str(gitignore_path),
                          "sentinel_present": sent_present,
                          "gitignore_present": gi_present}, ensure_ascii=False))
        return 0

    # Sentinel domain/location consistency (M6): a sentinel written INTO a
    # canonically-named run dir MUST carry that dir's domain — a mismatched
    # explicit combo (e.g. --run-root .mgh-ut-init with --init-dir <t>/.mgh-init)
    # activates the WRONG domain's trusted subtrees at that location. A
    # custom-named --init-dir keeps the documented "--init-dir wins" override.
    _CANON_RUN_DIRS = {".mgh-init": "mgh-init", ".mgh-ut-init": "mgh-ut-init"}
    if args.init_dir and init_dir.name in _CANON_RUN_DIRS:
        _domain_from_run_root = ("mgh-ut-init" if args.run_root == ".mgh-ut-init"
                                 else "mgh-init")
        if _CANON_RUN_DIRS[init_dir.name] != _domain_from_run_root:
            print(f"error: --init-dir {init_dir} is a canonical run dir but "
                  f"--run-root {args.run_root} derives the other domain's sentinel "
                  f"there (would activate the wrong domain's trusted subtrees). "
                  f"Pass --run-root {init_dir.name} to match, or use a "
                  f"non-canonical --init-dir.", file=sys.stderr)
            return 2

    run_config = {
        "target": target_abs,
        "format": args.format,
        "scope": args.scope,
        "scope_mode": args.scope_mode,
        "no_scout": bool(args.no_scout),
        "no_codegraph": bool(args.no_codegraph),
        "skip_consistency": bool(args.skip_consistency),
        "include_dotfiles": bool(args.include_dotfiles),
        "include_tests": bool(args.include_tests),
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
    sentinel = {
        "domain": "mgh-ut-init" if args.run_root == ".mgh-ut-init" else "mgh-init",
        "target": target_abs,
        "out_roots": _derive_out_roots(args, target_abs),
        "v": 1,
    }
    _atomic_write_json(sentinel_path, sentinel)
    # Run-dir gitignore co-write (deterministic side-effect, same posture as the
    # sentinel): the shells/contracts promise "run dir is gitignored"; this script is
    # its single deterministic writer. Body `*` ignores everything inside the run dir.
    # NEVER rewrite/append an existing file (user-tuned stays); the target project's
    # own root .gitignore is zero-touch — this lands INSIDE the run dir only.
    if not gitignore_path.exists():
        _atomic_write_text(gitignore_path, "*\n")
    ack = {
        "run_config": str(rc_path),
        "target": target_abs,
        "format": args.format,
        "no_scout": run_config["no_scout"],
        "no_codegraph": run_config["no_codegraph"],
        "skip_consistency": run_config["skip_consistency"],
        "sentinel": str(sentinel_path),
        "gitignore": str(gitignore_path),
    }
    print(f"[write_runconfig] wrote {rc_path} (format={args.format}, "
          f"no_scout={run_config['no_scout']}) + sentinel "
          f"{sentinel_path} + gitignore {gitignore_path}", file=sys.stderr)
    print(json.dumps(ack, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
