#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""check_contracts — R5.1 CLI contract lint.

For each shell command `.md`, extract every `py .../<script>.py --flag ...`
invocation from its fenced ```bash blocks and assert each `--flag` is declared in
that script's `--help` (the contract surface). A shell using a flag the script does
not declare = contract violation (the agent learns the interface from `--help`, so
`--help` MUST match the shells exactly).

Default scope: the two /mgh-init shells (claude + opencode). Override with
`--shells a.md b.md`. Zero runtime deps (Python >=3.10 stdlib).

Exit: 0 ok · 1 contract violation / shell or script missing.
Run: py tools/check_contracts.py
"""
from __future__ import annotations
import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "core" / "scripts"
DEFAULT_SHELLS = [
    ROOT / "releases" / "claude-code" / "commands" / "mgh-init.md",
    ROOT / "releases" / "opencode" / "command" / "mgh-init.md",
    ROOT / "releases" / "claude-code" / "commands" / "mgh-sast.md",
    ROOT / "releases" / "opencode" / "command" / "mgh-sast.md",
    ROOT / "releases" / "claude-code" / "commands" / "mgh-sra.md",
    ROOT / "releases" / "opencode" / "command" / "mgh-sra.md",
    ROOT / "releases" / "claude-code" / "commands" / "mgh-srr.md",
    ROOT / "releases" / "opencode" / "command" / "mgh-srr.md",
]
# mgh-sast shells and the shell-level (non-script) flags their flag table MUST advertise
# (--controls is the shell's own flag, not a *.py flag, so the bash-block extractor below
# does not see it — assert it directly, mirrored across both shells).
SAST_SHELLS = [
    ROOT / "releases" / "claude-code" / "commands" / "mgh-sast.md",
    ROOT / "releases" / "opencode" / "command" / "mgh-sast.md",
]
# --controls is the shell's own flag; --max-aggregate-bytes is the shell-level
# request-context-budget flag consumed by the orchestrator for the s1/s2-s3 aggregate
# nodes (not a *.py). Both asserted in text, mirrored across both shells (R5.1).
SAST_SHELL_REQUIRED_FLAGS = ["--controls", "--max-aggregate-bytes"]
# /mgh-init shells advertise shell-level request-context-budget flags that are NOT passed
# to any *.py (--max-aggregate-bytes is consumed by the orchestrator). Asserted in text,
# mirrored across both shells (R5.1).
INIT_SHELLS = [
    ROOT / "releases" / "claude-code" / "commands" / "mgh-init.md",
    ROOT / "releases" / "opencode" / "command" / "mgh-init.md",
]
INIT_SHELL_REQUIRED_FLAGS = ["--max-aggregate-bytes"]
# discover_controls.py resilience flags that MUST appear in its --help (the contract
# surface). Asserted directly (not via shell bash blocks) so the contract holds even if a
# shell's fenced example is trimmed — --help IS the interface the agent learns from.
DISCOVER_SCRIPT = ROOT / "core" / "scripts" / "discover_controls.py"
DISCOVER_REQUIRED_FLAGS = ["--time-budget-ms", "--rebuild-cache", "--resume"]
# init list_* materialization/paging flags that MUST appear in each enumeration script's
# --help (request-context-budget; R5.1 contract surface). Asserted directly so the contract
# holds even if a shell's fenced example is trimmed.
LIST_SCRIPT_FLAGS = ["--materialize", "--offset", "--limit", "--max-unit-bytes", "--orch-budget-bytes"]
LIST_SCRIPTS = [
    ROOT / "core" / "scripts" / "list_clusters.py",
    ROOT / "core" / "scripts" / "list_scout_batches.py",
    ROOT / "core" / "scripts" / "list_rule_jobs.py",
    ROOT / "core" / "scripts" / "list_chunks.py",
    ROOT / "core" / "scripts" / "list_verify_jobs.py",
]
# /mgh-srr intake + render adapter flags that MUST appear in their scripts' --help
# (request-context-budget adoption; R5.1 contract surface). Asserted directly so the contract
# holds even if a shell's fenced example is trimmed — --help IS the interface the agent learns.
INGEST_SCRIPT = ROOT / "core" / "scripts" / "ingest_requirements.py"
INGEST_REQUIRED_FLAGS = ["--materialize", "--offset", "--limit", "--max-unit-bytes", "--orch-budget-bytes"]
RENDER_SCRIPT = ROOT / "core" / "scripts" / "render_report.py"
RENDER_REQUIRED_FLAGS = ["--max-aggregate-bytes"]
# /mgh-srr shells advertise the shell-level request-context-budget flag (--max-aggregate-bytes
# is consumed by the orchestrator, not a *.py), mirrored across both shells (R5.1).
SRR_SHELLS = [
    ROOT / "releases" / "claude-code" / "commands" / "mgh-srr.md",
    ROOT / "releases" / "opencode" / "command" / "mgh-srr.md",
]
SRR_SHELL_REQUIRED_FLAGS = ["--max-aggregate-bytes"]
# /mgh-sra prepare_augment materialization/paging flags that MUST appear in its --help
# (request-context-budget adoption; R5.1 contract surface). Asserted directly so the contract
# holds even if a shell's fenced example is trimmed.
PREPARE_SCRIPT = ROOT / "core" / "scripts" / "prepare_augment.py"
PREPARE_REQUIRED_FLAGS = ["--materialize", "--offset", "--limit", "--max-unit-bytes", "--orch-budget-bytes"]
# /mgh-sra shells advertise the shell-level request-context-budget flag (--max-aggregate-bytes
# is consumed by the orchestrator for a2/a4, not a *.py), mirrored across both shells (R5.1).
SRA_SHELLS = [
    ROOT / "releases" / "claude-code" / "commands" / "mgh-sra.md",
    ROOT / "releases" / "opencode" / "command" / "mgh-sra.md",
]
SRA_SHELL_REQUIRED_FLAGS = ["--max-aggregate-bytes"]
# /mgh-init re-entrant resume + aggregate-sharding leaf flags that MUST appear in their
# --help (the contract surface). Asserted directly so the contract holds even if a shell's
# fenced example is trimmed — --help IS the interface the agent learns from.
RESUME_SCRIPT = ROOT / "core" / "scripts" / "resume_state.py"
RESUME_REQUIRED_FLAGS = ["--target", "--init-dir", "--check"]
PLAN_AGG_SCRIPT = ROOT / "core" / "scripts" / "plan_aggregate.py"
PLAN_AGG_REQUIRED_FLAGS = ["--node", "--init-dir", "--budget", "--materialize",
                           "--offset", "--limit", "--orch-budget-bytes"]
WRITE_RUNCONFIG_SCRIPT = ROOT / "core" / "scripts" / "write_runconfig.py"
WRITE_RUNCONFIG_REQUIRED_FLAGS = ["--target", "--format", "--init-dir", "--scope",
                                  "--no-scout", "--no-codegraph", "--skip-consistency",
                                  "--merge", "--include-dotfiles", "--max-aggregate-bytes"]
PY = sys.executable

# A CLI flag is `--long` or `-s` preceded by a non-word boundary (whitespace/start),
# NOT a hyphenated word/path segment like `mgh-core`, `.mgh-init`, `security-controls`.
_FLAG = r"(?<![\w-])(--?[a-zA-Z][\w-]*)"


def declared_flags(script_path: Path):
    """Return the set of flags the script declares in --help, or None if --help fails.

    Decodes leniently: --help text may contain non-ASCII help strings emitted in the
    host console codepage (e.g. cp936 on Chinese Windows); flag names are ASCII, so
    `errors="replace"` never affects detection.
    """
    r = subprocess.run([PY, str(script_path), "--help"], capture_output=True)
    if r.returncode != 0:
        return None
    text = r.stdout.decode("utf-8", "replace")
    return {m.group(1) for m in re.finditer(_FLAG, text)}


def extract_invocations(md_text: str):
    """Yield (script_basename, [flags]) for each `py .../script.py ...` in ```bash blocks.

    Joins backslash-continued lines first so multi-line invocations parse as one command.
    """
    for block in re.findall(r"```bash\n(.*?)```", md_text, re.DOTALL):
        joined = re.sub(r"\\\n", " ", block)
        for line in joined.splitlines():
            line = line.strip()
            if not line.startswith("py "):
                continue
            m = re.search(r"([\w-]+\.py)", line)
            if not m:
                continue
            yield m.group(1), re.findall(_FLAG, line)


def main():
    ap = argparse.ArgumentParser(
        description="R5.1 CLI contract lint: shell script flags must be declared in --help")
    ap.add_argument("--shells", nargs="*",
                    help="override shell MD paths (default: both mgh-init shells)")
    args = ap.parse_args()
    shells = [Path(s) for s in args.shells] if args.shells else DEFAULT_SHELLS
    # emit status glyphs cleanly regardless of host console codepage (e.g. cp936/gbk)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    failures, checked = [], 0
    for shell in shells:
        if not shell.is_file():
            failures.append(f"shell not found: {shell}")
            continue
        for script, flags in extract_invocations(shell.read_text(encoding="utf-8")):
            sp = SCRIPTS / script
            if not sp.is_file():
                failures.append(f"{shell.name}: references {script} (not in {SCRIPTS})")
                continue
            declared = declared_flags(sp)
            if declared is None:
                failures.append(f"{shell.name}: `{script} --help` failed")
                continue
            for f in flags:
                checked += 1
                if f not in declared:
                    failures.append(
                        f"{shell.name}: `{script}` uses {f!r} not declared in --help")

    # shell-level flags: the mgh-sast flag table must advertise --controls (R5.1 mirror).
    for shell in SAST_SHELLS:
        if not shell.is_file():
            failures.append(f"shell not found: {shell}")
            continue
        text = shell.read_text(encoding="utf-8")
        for flag in SAST_SHELL_REQUIRED_FLAGS:
            if flag not in text:
                failures.append(f"{shell.name}: flag table missing required {flag!r}")

    # /mgh-init shells must advertise the shell-level request-context-budget flag.
    for shell in INIT_SHELLS:
        if not shell.is_file():
            failures.append(f"shell not found: {shell}")
            continue
        text = shell.read_text(encoding="utf-8")
        for flag in INIT_SHELL_REQUIRED_FLAGS:
            if flag not in text:
                failures.append(f"{shell.name}: flag table missing required {flag!r}")

    # discover resilience flags MUST be declared in discover_controls.py --help (contract).
    if not DISCOVER_SCRIPT.is_file():
        failures.append(f"script not found: {DISCOVER_SCRIPT}")
    else:
        declared = declared_flags(DISCOVER_SCRIPT)
        if declared is None:
            failures.append("discover_controls.py: `--help` failed")
        else:
            for flag in DISCOVER_REQUIRED_FLAGS:
                if flag not in declared:
                    failures.append(
                        f"discover_controls.py: --help missing required {flag!r}")

    # init list_* materialization/paging flags MUST be declared in each script's --help.
    for script in LIST_SCRIPTS:
        if not script.is_file():
            failures.append(f"script not found: {script}")
            continue
        declared = declared_flags(script)
        if declared is None:
            failures.append(f"{script.name}: `--help` failed")
            continue
        for flag in LIST_SCRIPT_FLAGS:
            if flag not in declared:
                failures.append(f"{script.name}: --help missing required {flag!r}")

    # /mgh-srr intake (ingest_requirements) + render adapter flags MUST be declared in the
    # respective script's --help (request-context-budget adoption; R5.1).
    for script, req_flags in ((INGEST_SCRIPT, INGEST_REQUIRED_FLAGS),
                              (RENDER_SCRIPT, RENDER_REQUIRED_FLAGS)):
        if not script.is_file():
            failures.append(f"script not found: {script}")
            continue
        declared = declared_flags(script)
        if declared is None:
            failures.append(f"{script.name}: `--help` failed")
            continue
        for flag in req_flags:
            if flag not in declared:
                failures.append(f"{script.name}: --help missing required {flag!r}")

    # /mgh-srr shells must advertise the shell-level request-context-budget flag.
    for shell in SRR_SHELLS:
        if not shell.is_file():
            failures.append(f"shell not found: {shell}")
            continue
        text = shell.read_text(encoding="utf-8")
        for flag in SRR_SHELL_REQUIRED_FLAGS:
            if flag not in text:
                failures.append(f"{shell.name}: flag table missing required {flag!r}")

    # /mgh-sra prepare_augment materialization/paging flags MUST be declared in its --help
    # (request-context-budget adoption; R5.1).
    if not PREPARE_SCRIPT.is_file():
        failures.append(f"script not found: {PREPARE_SCRIPT}")
    else:
        declared = declared_flags(PREPARE_SCRIPT)
        if declared is None:
            failures.append("prepare_augment.py: `--help` failed")
        else:
            for flag in PREPARE_REQUIRED_FLAGS:
                if flag not in declared:
                    failures.append(f"prepare_augment.py: --help missing required {flag!r}")

    # /mgh-sra shells must advertise the shell-level request-context-budget flag.
    for shell in SRA_SHELLS:
        if not shell.is_file():
            failures.append(f"shell not found: {shell}")
            continue
        text = shell.read_text(encoding="utf-8")
        for flag in SRA_SHELL_REQUIRED_FLAGS:
            if flag not in text:
                failures.append(f"{shell.name}: flag table missing required {flag!r}")

    # /mgh-init re-entrant resume + aggregate-sharding leaf flags MUST be declared in each
    # script's --help (re-entrance + hard-budget gate; R5.1 contract surface).
    for script, req_flags in ((RESUME_SCRIPT, RESUME_REQUIRED_FLAGS),
                              (PLAN_AGG_SCRIPT, PLAN_AGG_REQUIRED_FLAGS),
                              (WRITE_RUNCONFIG_SCRIPT, WRITE_RUNCONFIG_REQUIRED_FLAGS)):
        if not script.is_file():
            failures.append(f"script not found: {script}")
            continue
        declared = declared_flags(script)
        if declared is None:
            failures.append(f"{script.name}: `--help` failed")
            continue
        for flag in req_flags:
            if flag not in declared:
                failures.append(f"{script.name}: --help missing required {flag!r}")

    if failures:
        print(f"✗ {len(failures)} contract violation(s):", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"✓ {checked} flag(s) across {len(shells)} shell(s) all declared in --help")
    return 0


if __name__ == "__main__":
    sys.exit(main())
