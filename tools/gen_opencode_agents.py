#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Dev tool: mirror the Claude stage agents into opencode agent format.

opencode has no native Agent-Skills concept, so lens content is PATH-REFERENCED
from core/prompts (single source of truth). Each opencode agent mirrors the
Claude agent's stage role with opencode markdown-agent frontmatter
(description, mode, permission record) and references the same core/prompts
file(s). Note: opencode's `tools` field is deprecated and must be a record;
we use `permission` (allow/ask/deny per tool).

Run: py tools/gen_opencode_agents.py
"""
import re
from pathlib import Path

SRC = Path("releases/claude-code/agents")
DST = Path("releases/opencode/agent")


def permission_block(claude_tools_str):
    """Build an opencode `permission:` record from the Claude tools list.

    opencode permission keys: read/edit/glob/grep/list/bash/task/... each
    allow|ask|deny. (opencode `tools` is deprecated and, unlike Claude Code,
    must be a record — a comma string fails validation.)
    """
    t = {x.strip() for x in claude_tools_str.split(",") if x.strip()}
    bash = "allow" if "Bash" in t else "deny"
    edit = "allow" if ("Write" in t or "Edit" in t) else "deny"
    return ("permission:\n"
            "  read: allow\n"
            "  glob: allow\n"
            "  grep: allow\n"
            "  list: allow\n"
            f"  bash: {bash}\n"
            f"  edit: {edit}")


def convert(text):
    # split frontmatter + body
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return text
    fm, body = m.group(1), m.group(2)
    desc = re.search(r"^description:\s*(.+)$", fm, re.M).group(1).strip().rstrip('"')
    tools = "Read, Glob, Grep"
    tm = re.search(r"^tools:\s*(.+)$", fm, re.M)
    if tm:
        tools = tm.group(1).strip()
    # opencode paths use .opencode/mgh-core instead of .claude/mgh-core
    body = body.replace(".claude/mgh-core", ".opencode/mgh-core")
    # opencode markdown agent frontmatter: description (required) + mode +
    # permission record. `model` omitted → uses the configured default.
    new_fm = (f"---\n"
              f"description: {desc}\n"
              f"mode: subagent\n"
              f"{permission_block(tools)}\n"
              f"---\n")
    return new_fm + body


def main():
    DST.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in sorted(SRC.glob("*.md")):
        out = DST / p.name
        out.write_text(convert(p.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"  wrote opencode/agent/{p.name}")
        n += 1
    print(f"[ok] {n} opencode agents generated (path-reference core/prompts)")


if __name__ == "__main__":
    main()
