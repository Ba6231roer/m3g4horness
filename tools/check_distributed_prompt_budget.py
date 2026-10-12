#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""check_distributed_prompt_budget — R5.6 orchestrator-shell token budget lint.

Asserts every shipped orchestrator shell body stays within the R5.6 hard ceiling
(mid_tokens <= 5000, measured with the same estimator as tools/measure_prompts.py).
An oversized shell MUST be shard-to-fit (move detail into a lazy fragment), never
trimmed of load-bearing content.

Scan set: the mgh-* orchestrator shells across all three dialects (claude commands,
opencode command, dsh skills/SKILL.md). Exit: 0 ok / 2 violation (fail-loud, CI).
Zero runtime deps (Python >=3.10 stdlib). Run: py tools/check_distributed_prompt_budget.py
"""
from __future__ import annotations
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from measure_prompts import measure_one  # noqa: E402

ROOT = HERE.parent
CEILING_MID_TOKENS = 5000

# Orchestrator shells = command faces only (not agents/stages/fragments; those have
# their own per-system budgets).
SHELLS = [
    ROOT / "releases" / "claude-code" / "commands" / f"mgh-{c}.md"
    for c in ("sast", "init", "sra", "srr", "sdr", "ut-init")
] + [
    ROOT / "releases" / "opencode" / "command" / f"mgh-{c}.md"
    for c in ("sast", "init", "sra", "srr", "sdr", "ut-init")
] + [
    ROOT / "releases" / "dsh" / "skills" / f"mgh-{c}" / "SKILL.md"
    for c in ("sast", "init", "sra", "srr", "sdr")
]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    violations = []
    report = []
    for shell in SHELLS:
        if not shell.is_file():
            violations.append(f"shell not found: {shell}")
            continue
        m = measure_one(shell)
        report.append(f"  {m['path']}  mid_tokens={m['mid_tokens']}")
        if m["mid_tokens"] > CEILING_MID_TOKENS:
            violations.append(
                f"{m['path']}: mid_tokens {m['mid_tokens']} > R5.6 ceiling "
                f"{CEILING_MID_TOKENS} — shard-to-fit (lazy fragment), NEVER trim "
                f"load-bearing content")
    print("orchestrator shell budget report (ceiling mid_tokens <= "
          f"{CEILING_MID_TOKENS}):")
    print("\n".join(report))
    if violations:
        print(f"✗ {len(violations)} budget violation(s):", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 2
    print(f"✓ {len(SHELLS)} orchestrator shell(s) within budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
