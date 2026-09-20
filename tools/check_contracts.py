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
    ROOT / "releases" / "claude-code" / "commands" / "mgh-ut-init.md",
    ROOT / "releases" / "opencode" / "command" / "mgh-ut-init.md",
    ROOT / "releases" / "claude-code" / "commands" / "mgh-sdr.md",
    ROOT / "releases" / "opencode" / "command" / "mgh-sdr.md",
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
# list_clusters.py t1 packing flags (deterministic small-cluster packing adoption) MUST be
# declared in its --help (R5.1 contract surface) — list_*-scoped, hence not in the shared
# LIST_SCRIPT_FLAGS above (the other enumeration scripts have no packing).
LIST_CLUSTERS_PACK_SCRIPT = ROOT / "core" / "scripts" / "list_clusters.py"
LIST_CLUSTERS_PACK_FLAGS = ["--pack-bytes", "--pack-max"]
LIST_SCRIPTS = [
    ROOT / "core" / "scripts" / "list_clusters.py",
    ROOT / "core" / "scripts" / "list_scout_batches.py",
    ROOT / "core" / "scripts" / "list_rule_jobs.py",
    ROOT / "core" / "scripts" / "list_chunks.py",
    ROOT / "core" / "scripts" / "list_verify_jobs.py",
    ROOT / "core" / "scripts" / "list_test_groups.py",
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
RESUME_REQUIRED_FLAGS = ["--target", "--init-dir", "--run-root", "--check"]
# /mgh-init tier-aware wave dispatcher flags that MUST appear in fanout_runner.py --help
# (fanout-dispatch adoption, scout + t1 + t3; R5.1 contract surface). Asserted directly
# so the contract holds even if a shell's fenced example is trimmed — --help IS the interface.
FANOUT_RUNNER_SCRIPT = ROOT / "core" / "scripts" / "fanout_runner.py"
FANOUT_RUNNER_REQUIRED_FLAGS = ["--tier", "--scout-plan", "--clusters", "--candidates",
                                "--init-dir", "--budget",
                                "--inventory", "--format", "--rules-dir", "--target",
                                "--repo", "--base", "--branch",
                                "--checkpoints", "--inputs-dir", "--host",
                                "--wave", "--time-budget-ms", "--call-timeout-s",
                                "--stall-waves", "--resume",
                                "--kill-stale", "--pending-file", "--purge-audit",
                                "--dry-run", "--template",
                                "--cooldown-s", "--no-rate-limit-stop", "--retry-failed"]
# The --tier closed set MUST advertise the t2 tier (map stage adoption): argparse prints the
# choices verbatim in --help's usage line — assert the expanded set textually (a trimmed shell
# example / prose can't fake it; the usage line is argparse-generated).
FANOUT_TIER_SET_HELP = "{scout,t1,t2,t3,sdr}"
# Per-tier task-message templates the dispatcher reads (fanout-dispatch tier adoption);
# existence asserted so a trimmed mirror cannot silently break dispatch.
FANOUT_TEMPLATES = [
    ROOT / "core" / "prompts" / "fragments" / "fanout" / "scout-task.md",
    ROOT / "core" / "prompts" / "fragments" / "fanout" / "t1-task.md",
    ROOT / "core" / "prompts" / "fragments" / "fanout" / "t2-task.md",
    ROOT / "core" / "prompts" / "fragments" / "fanout" / "t3-task.md",
    ROOT / "core" / "prompts" / "fragments" / "fanout" / "sdr-task.md",
]
# /mgh-sdr deterministic leaf flags that MUST appear in each script's --help (R5.1
# contract surface). Asserted directly so the contract holds even if a shell's fenced
# example is trimmed — --help IS the interface the agent learns from.
DIFF_GROUP_SCRIPT = ROOT / "core" / "scripts" / "diff_group.py"
DIFF_GROUP_REQUIRED_FLAGS = ["--repo", "--base", "--branch", "--checkpoints",
                             "--materialize", "--max-standalone-bytes",
                             "--max-interface-bytes", "--include-excluded", "--offset",
                             "--limit", "--resume", "--check", "--include-failed"]
SDR_CONTEXT_SCRIPT = ROOT / "core" / "scripts" / "sdr_context.py"
SDR_CONTEXT_REQUIRED_FLAGS = ["--repo", "--run-dir", "--base", "--branch", "--dimensions",
                              "--baseline-budget-bytes", "--external-budget-bytes",
                              "--read-root", "--no-codegraph", "--check"]
RENDER_SDR_SCRIPT = ROOT / "core" / "scripts" / "render_sdr_report.py"
RENDER_SDR_REQUIRED_FLAGS = ["--run-dir", "--repo", "--out-dir", "--check"]
SDR_LAUNCH_SCRIPT = ROOT / "core" / "scripts" / "mgh_sdr_launch.py"
SDR_LAUNCH_REQUIRED_FLAGS = ["--repo", "--branch", "--base", "--host", "--dimensions",
                             "--multi-branch", "--read-root", "--no-codegraph", "--dry-run"]
# /mgh-sdr resume surface: the sdr-domain state query + step manifest MUST declare their
# flags in --help (R5.1 contract surface), so an agent that learns interfaces from --help
# can always reach them — the same guarantee the init/ut-init siblings carry.
RESUME_SDR_SCRIPT = ROOT / "core" / "scripts" / "resume_sdr_state.py"
RESUME_SDR_REQUIRED_FLAGS = ["--run-dir", "--repo", "--check", "--rearm-sentinel"]
LIST_SDR_STEPS_SCRIPT = ROOT / "core" / "scripts" / "list_sdr_steps.py"
LIST_SDR_STEPS_REQUIRED_FLAGS = ["--target", "--step"]
# /mgh-sdr external-repo authorization gate: the config writer's flags MUST be declared
# in its --help (R5.1 contract surface), and both shells MUST carry the authorization
# step (the script invocation + the pending_approval disclosure) — mirrored assertion so
# a trimmed shell cannot silently drop the user-decision gate.
READ_ROOTS_SCRIPT = ROOT / "core" / "scripts" / "read_roots_config.py"
READ_ROOTS_REQUIRED_FLAGS = ["--target", "--add", "--remove", "--list", "--check"]
SDR_SHELLS = [
    ROOT / "releases" / "claude-code" / "commands" / "mgh-sdr.md",
    ROOT / "releases" / "opencode" / "command" / "mgh-sdr.md",
]
SDR_SHELL_REQUIRED_MARKERS = ["read_roots_config.py", "pending_approval"]
# /mgh-sdr codegraph signal: the switch MUST NOT go dead again. The carrier is the run dir's
# `run_config.json` (single source, no env-var middleman) and the dispatcher MUST consume it —
# so (a) the consumer-less env var MUST NOT reappear, (b) the shell MUST advertise the flag AND
# the carrier it rides (a declared flag with no carrier = dead switch), and (c) the dispatcher's
# sdr branch MUST NOT reinstate the early `off` return.
SDR_CODEGRAPH_DEAD_ENV_VAR = "MGH_SDR_CODEGRAPH"
SDR_CODEGRAPH_FLAG = "--no-codegraph"
SDR_CODEGRAPH_CARRIER_MARKERS = ["run_config.json", "no_codegraph"]
SDR_CODEGRAPH_DEAD_READ = 'tier_key == "sdr"'
# ...and the signal MUST be DERIVED from the same predicate the grouper acts on, never a
# second copy of the probe. A re-inlined probe is how "run_config says on" comes apart from
# "the grouping degraded and merged no chain": the reviewer is then told its slice already
# carries the whole chain and must not look elsewhere, which is a false instruction, not a
# cosmetic mismatch. One predicate lives in sdr_tier; both sides import it.
SDR_CODEGRAPH_PROBE_MODULE = ROOT / "core" / "scripts" / "sdr_tier.py"
SDR_CODEGRAPH_PROBE_MARKER = "codegraph_available"
SDR_CODEGRAPH_PROBE_CONSUMERS = [ROOT / "core" / "scripts" / "diff_group.py",
                                 ROOT / "core" / "scripts" / "sdr_context.py"]
SDR_CODEGRAPH_RAW_PROBE = 'shutil.which("codegraph")'
# /mgh-sdr recovery + troubleshooting pointers MUST be executable in the sdr run domain: the
# shell MUST point at a <run-dir>-shaped producer check, and MUST NOT cross-reference a script
# whose state root lives in another run domain (resume_state.py resolves to <target>/.mgh-init
# by default, so against an sdr run dir it exits 1 with "init-dir not found" — 100% failure,
# and the flag-existence lint below cannot see that).
SDR_SHELL_FORBIDDEN_SCRIPTS = ["resume_state.py"]
SDR_SHELL_REQUIRED_CHECK_FORM = "diff_group.py --check"
# ... and the sdr resume entry MUST be the sdr-domain script (the init-domain one is
# forbidden above), mirrored across both shells.
SDR_SHELL_REQUIRED_RESUME_MARKER = "resume_sdr_state.py"
# Run-level state (guard sentinel + codegraph signal) MUST be written by a SCRIPT side
# effect, never by an orchestrator-executed shell recipe: a `printf > <path>` write is
# a command the orchestrator must read and execute correctly, and a mis-read silently
# disarms the guard / kills the codegraph signal. Assert the recipe shapes are gone.
SDR_SHELL_FORBIDDEN_WRITE_SHAPES = ["> <run-dir>/run_config.json", "> .mgh-sdr/.active"]
PLAN_AGG_SCRIPT = ROOT / "core" / "scripts" / "plan_aggregate.py"
PLAN_AGG_REQUIRED_FLAGS = ["--node", "--init-dir", "--budget", "--materialize",
                           "--offset", "--limit", "--orch-budget-bytes",
                           "--include-failed"]
# --include-failed (failed-terminal bounded re-dispatch adoption) MUST be declared in
# each of the five tier enumerators' --help (R5.1 contract surface) — the dispatcher's
# --retry-failed forwards it, so identity always comes from the enumerator.
INCLUDE_FAILED_SCRIPTS = [
    ROOT / "core" / "scripts" / "list_scout_batches.py",
    ROOT / "core" / "scripts" / "list_clusters.py",
    ROOT / "core" / "scripts" / "plan_aggregate.py",
    ROOT / "core" / "scripts" / "list_rule_jobs.py",
    ROOT / "core" / "scripts" / "diff_group.py",
]
INCLUDE_FAILED_FLAG = "--include-failed"
WRITE_RUNCONFIG_SCRIPT = ROOT / "core" / "scripts" / "write_runconfig.py"
WRITE_RUNCONFIG_REQUIRED_FLAGS = ["--target", "--format", "--init-dir", "--run-root", "--scope",
                                  "--no-scout", "--no-codegraph", "--skip-consistency",
                                  "--merge", "--include-dotfiles", "--max-aggregate-bytes"]
# /mgh-ut-init shells advertise the shell-level request-context-budget + format flag
# (--max-aggregate-bytes is consumed by the orchestrator for the synthesize aggregate node,
# not a *.py; --format is the required format mutex). Asserted in text, mirrored across both
# shells (R5.1).
UT_INIT_SHELLS = [
    ROOT / "releases" / "claude-code" / "commands" / "mgh-ut-init.md",
    ROOT / "releases" / "opencode" / "command" / "mgh-ut-init.md",
]
UT_INIT_SHELL_REQUIRED_FLAGS = ["--max-aggregate-bytes", "--format"]
# /mgh-ut-init leaf flags that MUST appear in each script's --help (R5.1 contract surface).
# Asserted directly so the contract holds even if a shell's fenced example is trimmed.
CLASSIFY_SCRIPT = ROOT / "core" / "scripts" / "classify_tests.py"
CLASSIFY_REQUIRED_FLAGS = ["--repo", "--out", "--scope", "--check", "--subsplit-threshold"]
ASSEMBLE_TEST_SCRIPT = ROOT / "core" / "scripts" / "assemble_test_rules.py"
ASSEMBLE_TEST_REQUIRED_FLAGS = ["--target", "--format", "--check", "--rules-dir"]
VALIDATE_TEST_SCRIPT = ROOT / "core" / "scripts" / "validate_test_rules.py"
VALIDATE_TEST_REQUIRED_FLAGS = ["--inventory"]
DERIVE_MUTATORS_SCRIPT = ROOT / "core" / "scripts" / "derive_mutators.py"
DERIVE_MUTATORS_REQUIRED_FLAGS = ["--repo", "--out", "--check"]
RESUME_UT_SCRIPT = ROOT / "core" / "scripts" / "resume_ut_init_state.py"
RESUME_UT_REQUIRED_FLAGS = ["--target", "--init-dir", "--run-root", "--check"]
WRITE_UT_RUNCONFIG_SCRIPT = ROOT / "core" / "scripts" / "write_ut_runconfig.py"
WRITE_UT_RUNCONFIG_REQUIRED_FLAGS = ["--target", "--format", "--init-dir", "--run-root",
                                     "--skip-consistency", "--uniform-sample",
                                     "--hetero-sample", "--subsplit-threshold",
                                     "--max-aggregate-bytes"]
LIST_UT_STEPS_SCRIPT = ROOT / "core" / "scripts" / "list_ut_steps.py"
LIST_UT_STEPS_REQUIRED_FLAGS = ["--target", "--step"]
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

    # list_clusters.py packing flags MUST be declared in its --help (t1 packing adoption).
    if not LIST_CLUSTERS_PACK_SCRIPT.is_file():
        failures.append(f"script not found: {LIST_CLUSTERS_PACK_SCRIPT}")
    else:
        declared = declared_flags(LIST_CLUSTERS_PACK_SCRIPT)
        if declared is None:
            failures.append("list_clusters.py: `--help` failed")
        else:
            for flag in LIST_CLUSTERS_PACK_FLAGS:
                if flag not in declared:
                    failures.append(
                        f"list_clusters.py: --help missing required {flag!r}")

    # --include-failed MUST be declared in each of the five tier enumerators'
    # --help (failed-terminal bounded re-dispatch adoption; R5.1 contract surface).
    for script in INCLUDE_FAILED_SCRIPTS:
        if not script.is_file():
            failures.append(f"script not found: {script}")
            continue
        declared = declared_flags(script)
        if declared is None:
            failures.append(f"{script.name}: `--help` failed")
            continue
        if INCLUDE_FAILED_FLAG not in declared:
            failures.append(
                f"{script.name}: --help missing required {INCLUDE_FAILED_FLAG!r}")

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
                              (WRITE_RUNCONFIG_SCRIPT, WRITE_RUNCONFIG_REQUIRED_FLAGS),
                              (FANOUT_RUNNER_SCRIPT, FANOUT_RUNNER_REQUIRED_FLAGS)):
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

    # fanout_runner --tier closed set MUST include t2 (map-stage adoption): the argparse usage
    # line prints the choices verbatim — assert the expanded set (a prose mention can't fake it).
    if FANOUT_RUNNER_SCRIPT.is_file():
        r = subprocess.run([PY, str(FANOUT_RUNNER_SCRIPT), "--help"], capture_output=True)
        if r.returncode != 0:
            failures.append("fanout_runner.py: `--help` failed")
        elif FANOUT_TIER_SET_HELP not in r.stdout.decode("utf-8", "replace"):
            failures.append(
                f"fanout_runner.py: --tier choices must advertise t2 ({FANOUT_TIER_SET_HELP})")

    # fanout_runner per-tier task templates MUST exist (tier-aware dispatch reads them).
    for template in FANOUT_TEMPLATES:
        if not template.is_file():
            failures.append(f"fanout task template not found: {template}")

    # /mgh-sdr leaf flags MUST be declared in each script's --help (R5.1 contract surface).
    for script, req_flags in ((DIFF_GROUP_SCRIPT, DIFF_GROUP_REQUIRED_FLAGS),
                              (SDR_CONTEXT_SCRIPT, SDR_CONTEXT_REQUIRED_FLAGS),
                              (RENDER_SDR_SCRIPT, RENDER_SDR_REQUIRED_FLAGS),
                              (SDR_LAUNCH_SCRIPT, SDR_LAUNCH_REQUIRED_FLAGS),
                              (READ_ROOTS_SCRIPT, READ_ROOTS_REQUIRED_FLAGS),
                              (RESUME_SDR_SCRIPT, RESUME_SDR_REQUIRED_FLAGS),
                              (LIST_SDR_STEPS_SCRIPT, LIST_SDR_STEPS_REQUIRED_FLAGS)):
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

    # /mgh-sdr shells MUST carry the external-repo authorization step (both the
    # read_roots_config.py invocation and the pending_approval disclosure), MUST keep the
    # codegraph switch attached to a real consumer (carrier present, dead env var absent),
    # and MUST keep every recovery/troubleshooting pointer executable inside the sdr run
    # domain (no cross-domain state-root references).
    for shell in SDR_SHELLS:
        if not shell.is_file():
            failures.append(f"shell not found: {shell}")
            continue
        text = shell.read_text(encoding="utf-8")
        for marker in SDR_SHELL_REQUIRED_MARKERS:
            if marker not in text:
                failures.append(f"{shell.name}: external-repo authorization step "
                                f"missing {marker!r}")
        if SDR_CODEGRAPH_DEAD_ENV_VAR in text:
            failures.append(f"{shell.name}: {SDR_CODEGRAPH_DEAD_ENV_VAR} has no consumer and "
                            f"MUST NOT reappear (the signal rides run_config.json)")
        if SDR_CODEGRAPH_FLAG not in text:
            failures.append(f"{shell.name}: flag table missing required {SDR_CODEGRAPH_FLAG!r}")
        for marker in SDR_CODEGRAPH_CARRIER_MARKERS:
            if marker not in text:
                failures.append(f"{shell.name}: codegraph signal carrier missing {marker!r} "
                                f"(declaring {SDR_CODEGRAPH_FLAG} with no carrier = dead switch)")
        for bad in SDR_SHELL_FORBIDDEN_SCRIPTS:
            if bad in text:
                failures.append(f"{shell.name}: references {bad}, whose state root is another "
                                f"run domain — 100% failure against an sdr run dir")
        if SDR_SHELL_REQUIRED_CHECK_FORM not in text:
            failures.append(f"{shell.name}: missing the in-domain recovery check "
                            f"{SDR_SHELL_REQUIRED_CHECK_FORM!r}")
        if SDR_SHELL_REQUIRED_RESUME_MARKER not in text:
            failures.append(f"{shell.name}: missing the sdr-domain resume entry "
                            f"{SDR_SHELL_REQUIRED_RESUME_MARKER!r} (the orchestrator has no "
                            f"executable way back into an interrupted run)")
        for shape in SDR_SHELL_FORBIDDEN_WRITE_SHAPES:
            if shape in text:
                failures.append(f"{shell.name}: hand-executed write recipe {shape!r} reappeared "
                                f"— run-level state (sentinel / run_config.json) MUST be a "
                                f"script side effect, never a recipe the orchestrator executes")

    # The sdr codegraph signal MUST have a live consumer: reinstating the dispatcher's early
    # `off` return for sdr would make the shell's switch dead again (R5.1 contract completeness).
    if not FANOUT_RUNNER_SCRIPT.is_file():
        failures.append(f"script not found: {FANOUT_RUNNER_SCRIPT}")
    elif SDR_CODEGRAPH_DEAD_READ in FANOUT_RUNNER_SCRIPT.read_text(encoding="utf-8"):
        failures.append(f"fanout_runner.py: {SDR_CODEGRAPH_DEAD_READ!r} reinstates the "
                        f"always-off sdr early return (dead switch for {SDR_CODEGRAPH_FLAG})")

    # The codegraph signal MUST be probed ONCE. The grouper (`diff_group.py`) decides whether
    # to merge units along the call chain; the signal writer (`sdr_context.py`) decides what
    # every unit's task message claims about that. Same fact, so same predicate — a re-inlined
    # `shutil.which("codegraph")` is a second implementation waiting to drift.
    if not SDR_CODEGRAPH_PROBE_MODULE.is_file():
        failures.append(f"script not found: {SDR_CODEGRAPH_PROBE_MODULE}")
    elif f"def {SDR_CODEGRAPH_PROBE_MARKER}(" not in \
            SDR_CODEGRAPH_PROBE_MODULE.read_text(encoding="utf-8"):
        failures.append(f"{SDR_CODEGRAPH_PROBE_MODULE.name}: missing the shared "
                        f"{SDR_CODEGRAPH_PROBE_MARKER}() predicate")
    for consumer in SDR_CODEGRAPH_PROBE_CONSUMERS:
        if not consumer.is_file():
            failures.append(f"script not found: {consumer}")
            continue
        src = consumer.read_text(encoding="utf-8")
        if SDR_CODEGRAPH_PROBE_MARKER not in src:
            failures.append(f"{consumer.name}: does not use the shared "
                            f"{SDR_CODEGRAPH_PROBE_MARKER}() — the codegraph signal and the "
                            f"grouping decision would be computed from different rules")
        if SDR_CODEGRAPH_RAW_PROBE in src:
            failures.append(f"{consumer.name}: re-inlines the codegraph probe "
                            f"({SDR_CODEGRAPH_RAW_PROBE}); import it from "
                            f"{SDR_CODEGRAPH_PROBE_MODULE.name} instead")

    # /mgh-ut-init shells must advertise the shell-level request-context-budget + format flag.
    for shell in UT_INIT_SHELLS:
        if not shell.is_file():
            failures.append(f"shell not found: {shell}")
            continue
        text = shell.read_text(encoding="utf-8")
        for flag in UT_INIT_SHELL_REQUIRED_FLAGS:
            if flag not in text:
                failures.append(f"{shell.name}: flag table missing required {flag!r}")

    # /mgh-ut-init leaf flags MUST be declared in each script's --help (R5.1).
    for script, req_flags in ((CLASSIFY_SCRIPT, CLASSIFY_REQUIRED_FLAGS),
                              (ASSEMBLE_TEST_SCRIPT, ASSEMBLE_TEST_REQUIRED_FLAGS),
                              (VALIDATE_TEST_SCRIPT, VALIDATE_TEST_REQUIRED_FLAGS),
                              (DERIVE_MUTATORS_SCRIPT, DERIVE_MUTATORS_REQUIRED_FLAGS),
                              (RESUME_UT_SCRIPT, RESUME_UT_REQUIRED_FLAGS),
                              (WRITE_UT_RUNCONFIG_SCRIPT, WRITE_UT_RUNCONFIG_REQUIRED_FLAGS),
                              (LIST_UT_STEPS_SCRIPT, LIST_UT_STEPS_REQUIRED_FLAGS)):
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
