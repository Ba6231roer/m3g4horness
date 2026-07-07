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
]
# mgh-sast shells and the shell-level (non-script) flags their flag table MUST advertise
# (--controls is the shell's own flag, not a *.py flag, so the bash-block extractor below
# does not see it — assert it directly, mirrored across both shells).
SAST_SHELLS = [
    ROOT / "releases" / "claude-code" / "commands" / "mgh-sast.md",
    ROOT / "releases" / "opencode" / "command" / "mgh-sast.md",
]
SAST_SHELL_REQUIRED_FLAGS = ["--controls"]
PY = sys.executable

# A CLI flag is `--long` or `-s` preceded by a non-word boundary (whitespace/start),
# NOT a hyphenated word/path segment like `mgh-core`, `.mgh-init`, `rules-parts`.
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

    if failures:
        print(f"✗ {len(failures)} contract violation(s):", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"✓ {checked} flag(s) across {len(shells)} shell(s) all declared in --help")
    return 0


if __name__ == "__main__":
    sys.exit(main())
