#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
list_sdr_steps — deterministic step invocation manifest for /mgh-sdr.

Emits the canonical per-step invocation manifest as JSON on stdout. Each step carries
{step, kind, script, script_abs, invocation, input{}, output{}, discipline} where
`script_abs` is derived from this script's location
(`Path(__file__).resolve().parent / <script_name>`) — the host prefix
(`.claude/mgh-core/` vs `.opencode/mgh-core/`) is inferred from where the script is
installed, NEVER hardcoded or passed via prompt. Sister script of init's
`list_steps.py` and ut-init's `list_ut_steps.py`; both are untouched.

Zero disk preconditions: does NOT read `context.json`, does NOT scan
`<repo>/.mgh-sdr/`, does NOT depend on any run-state artifact. Queryable pre-run, during
compaction recovery, or for pure documentation review. The ONE allowed disk probe is the
optional special-auth deployment doc (`<mgh-core>/mgh-special-auth.md`, maintainer-carried,
absent in generic installs): its presence is reported in the top-level `special_auth`
field so the orchestrator can consult it before the fan-out step; no other state is read.

Complements `resume_sdr_state.py` (disk-derived "where am I / what's next"):
resume_sdr_state gives the CURRENT step; list_sdr_steps gives the exact invocation line
for ANY step. Use together after --resume/compaction: resume gives `step` →
`list_sdr_steps.py --step <id>` gives its invocation and its discipline subset.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/pathlib/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py list_sdr_steps.py [--target <dir>] [--step <id>]

  --target   target project root (default: .); accepted for future extension,
             validated as a directory, not used in manifest content (static contract).
  --step     emit only the single step with this id (e.g., "group", "fanout"); NAMED ids
             only, NOT numeric indices; exits 2 if not recognized (closed set, R5.3b).
             Default: emit all steps.

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"steps": [{step, kind, script, script_abs, invocation, input{}, output{}, discipline}],
   "special_auth": {present, path}}
  - special_auth = {present: bool, path: <abs>|null} — presence of the optional
                   special-auth deployment doc in this install tree. present=true →
                   the orchestrator reads it BEFORE the fan-out step and follows it
                   for credential preparation and dispatch flags; present=false →
                   the generic flow needs nothing else.
  - step        = step id (enum matching resume_sdr_state.py)
  - kind        = "bash" | "done"
  - script      = sibling script file name (None for the terminal step)
  - script_abs  = absolute path to the script (<mgh-core>/scripts/<name>.py,
                 derived from __file__; host-agnostic)
  - invocation  = copy-pasteable Bash invocation line: "py <script_abs> <args>".
                 The fanout line is the sdr-shell canonical dispatch form: `--wave 1`
                 (intranet serial default; 1~2 advised when concurrent) + the quota
                 flag triple (`--quota-calls/--quota-window-s/--quota-calls-per-unit`,
                 estimate-based admission for calls-per-window gateways; optional,
                 zero change when unset). The group step's discipline carries the
                 slice-budget default caliber (interface 96KB / standalone 64KB,
                 resume-sticky via grouping.json's budget record).
  - input{}     = {artifact: "<name>", shape: "<shape>"}
  - output{}    = {artifact: "<name>", shape: "<shape>", path_pattern: "<pattern>"}
  - discipline  = per-step discipline subset {gates[], path_recipes[], nevers[]}
                (gate shapes / fan-out path recipes / applicable NEVER) — identical
                to resume_sdr_state.py stdout `discipline_reminders` for the same step
                (shared static table in discipline_core.py, domain="sdr";
                `done`/`not-started` → EMPTY structure). The fanout entry carries the
                full fast-fail storm tri-layer recipe (stalled-provider congestion /
                rate-limit window wait / retry-failed once) and the group entry the
                slice-budget calibration.

Exit codes (R5.3b): 0 ok · 1 target not a dir · 2 misuse (--step not found).
Idempotent, no TTY, read-only.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate so sibling imports resolve under any cwd / host-agent invocation.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Shared static per-step discipline table (single source of truth): identical to
# resume_sdr_state.py stdout `discipline_reminders` for the same step (the test
# asserts byte-verbatim equality). discipline_core is pure data — no IO.
from discipline_core import get_discipline  # noqa: E402


# Static step→IO table, defined once. The step id set matches resume_sdr_state.py's
# closed set (`not-started|group|fanout|render|done`) — cross-script consistency guard.
# Each entry: {step, kind, script_name, cli_args, input, output}.
# `script_abs` is derived at runtime from __file__.
_STEPS = [
    {
        "step": "not-started",
        "kind": "bash",
        "script_name": "sdr_context.py",
        "cli_args": ("--repo <target> --run-dir <run-dir> [--base <ref>] "
                     "[--branch <ref>] [--dimensions <json>] [--no-codegraph]"),
        "input": {"artifact": None, "shape": None},
        "output": {"artifact": "context.json", "shape": "{repo,base,branch,baseline_path,external_repos[]}",
                   "path_pattern": "<run-dir>/context.json (+ baseline.md; co-writes the "
                                   "run_config.json codegraph signal and the .mgh-sdr/.active sentinel)"},
    },
    {
        "step": "group",
        "kind": "bash",
        "script_name": "diff_group.py",
        "cli_args": ("--repo <target> --base <ref> --branch <ref> "
                     "--checkpoints <run-dir>/markers --materialize <run-dir>/slices"),
        "input": {"artifact": "context.json", "shape": "{repo,base,branch}"},
        "output": {"artifact": "grouping.json",
                   "shape": "{repo,empty,total,units[],excluded,pending[],budget,"
                            "slimmed}",
                   "path_pattern": "<run-dir>/grouping.json (+ <run-dir>/slices/*.slice.md)"},
    },
    {
        "step": "fanout",
        "kind": "bash",
        "script_name": "fanout_runner.py",
        # 规范行默认 --wave 1(内网串行最稳,opencode 并行子进程另有数据库锁前科;
        # 要并发建议 1~2)。配额三 flag 供调用次数限流网关(如 100 次/10 分钟):
        # 估算式准入按「窗口内已派发数×K」节流,K 默认 10=保守上界,未配置零变化。
        "cli_args": ("--tier sdr --repo <target> --base <ref> [--branch <ref>] "
                     "--checkpoints <run-dir>/markers --inputs-dir <run-dir>/slices "
                     "--wave 1 --time-budget-ms <ms> --call-timeout-s <s> "
                     "--stall-timeout-s <s> "
                     "[--quota-calls <N> --quota-window-s <W> "
                     "[--quota-calls-per-unit <K>]] [--resume]"),
        "input": {"artifact": "grouping.json::pending[]", "shape": "[unit work-list]"},
        "output": {"artifact": "drafts/*.json + markers/*.{done,failed}",
                   "shape": "[per-unit draft + terminal marker]",
                   "path_pattern": "<run-dir>/drafts/<unit_id>.json"},
    },
    {
        "step": "render",
        "kind": "bash",
        "script_name": "render_sdr_report.py",
        "cli_args": "--run-dir <run-dir> --repo <target>",
        "input": {"artifact": "drafts/*.json", "shape": "[per-unit findings]"},
        "output": {"artifact": "report + sdr_manifest.json",
                   "shape": "{sections[],counts} + terminal manifest",
                   "path_pattern": "<target>/mgh-sdr-<branch>-<ts>.html + <run-dir>/sdr_manifest.json (+ <run-dir>/sdr_report_data.json)"},
    },
    {
        "step": "done",
        "kind": "done",
        "script_name": None,  # terminal state: no script
        "cli_args": None,
        "input": {"artifact": None, "shape": None},
        "output": {"artifact": "sdr_manifest.json",
                   "shape": "{version,counts,boundaries[]}",
                   "path_pattern": "<run-dir>/sdr_manifest.json"},
    },
]


def _special_auth() -> dict:
    """Presence probe for the optional special-auth deployment doc (the ONE
    disk probe this manifest makes; see module docstring). present=false is
    the generic-install shape and carries path=null."""
    doc = Path(__file__).resolve().parent.parent / "mgh-special-auth.md"
    if doc.is_file():
        return {"present": True, "path": str(doc)}
    return {"present": False, "path": None}


def _script_abs(script_name: str | None) -> str | None:
    """Derive absolute script path from __file__. None for steps with no leaf script."""
    if script_name is None:
        return None
    # This script resides in <mgh-core>/scripts/; siblings are in the same dir.
    sibling = Path(__file__).resolve().parent / script_name
    return str(sibling) if sibling.exists() else None


def _invocation(script_abs: str | None, cli_args: str | None) -> str | None:
    """Build a copy-pasteable Bash invocation line. None for scriptless steps."""
    if script_abs is None or cli_args is None:
        return None
    return f"py {script_abs} {cli_args}"


def _build_step(entry: dict) -> dict:
    """Build one output step entry from its static definition."""
    step_id = entry["step"]
    script_name = entry["script_name"]
    script_abs = _script_abs(script_name)
    return {
        "step": step_id,
        "kind": entry["kind"],
        "script": script_name,
        "script_abs": script_abs,
        "invocation": _invocation(script_abs, entry["cli_args"]),
        "input": entry["input"],
        "output": entry["output"],
        "discipline": get_discipline(step_id, domain="sdr"),
    }


def main():
    ap = argparse.ArgumentParser(
        description="emit /mgh-sdr per-step invocation manifest (deterministic, zero "
                    "disk pre-req)")
    ap.add_argument("--target", default=".",
                    help="target project root (default .); accepted for future extension")
    ap.add_argument("--step", metavar="<id>",
                    help="emit only the single step with this id (e.g. group, fanout); "
                         "named ids only; NOT numeric indices; exits 2 if not recognized "
                         "(closed set)")
    # Emit JSON / glyphs cleanly regardless of host console codepage (e.g. cp936/gbk).
    # No-op on StringIO (in-process tests).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = ap.parse_args()

    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"error: target not a directory: {target}", file=sys.stderr)
        return 1

    steps = [_build_step(e) for e in _STEPS]
    step_ids = {s["step"] for s in steps}

    if args.step:
        if args.step not in step_ids:
            msg = f"error: unknown step id: {args.step!r} (known: {sorted(step_ids)})"
            if args.step.isdigit():
                msg += ("; step ids are NAMED enums (from resume_sdr_state.py stdout "
                        "step, or run list_sdr_steps.py without --step to list all); "
                        "numeric indices are NOT accepted")
            print(msg, file=sys.stderr)
            return 2
        steps = [s for s in steps if s["step"] == args.step]
        print(f"[list_sdr_steps] emitting single step: {args.step}", file=sys.stderr)
    else:
        print(f"[list_sdr_steps] emitting {len(steps)} steps (use --step <id> for "
              f"single step)", file=sys.stderr)

    print(json.dumps({"steps": steps, "special_auth": _special_auth()},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
