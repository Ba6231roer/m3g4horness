<!--
  rules-format fragment — Claude Code (verified 2026-06).
  Source: code.claude.com/docs/en/memory.md (organize-rules-with-.claude/rules,
  path-specific-rules). Canonical project-level rules mechanism for Claude Code.
-->

# Claude Code rules format (use ONLY when `--format claude`)

Claude Code auto-discovers `.claude/rules/**/*.md` recursively. Each file MAY
carry YAML frontmatter `paths:` (path-specific scoping — the rule loads only
when editing matching files). No other frontmatter is required.

## File: `<target>/.claude/rules/security-<category>.md`

```markdown
---
paths:
  - "<protects glob 1>"
  - "<protects glob 2>"
---

# Security: <Category>

## <Control name> — reuse, do not reinvent
New code handling <what> MUST use the existing <control> rather than reimplementing it.

- **What**: <one line>
- **Use it at**: <usage — how to call/annotate>
- **Anchor**: `src/.../X.java::Class.method` (line N)
- **Caveat**: <gap/effectiveness note, if any>

<repeat per control in this category>
```

## Rules
- **输出语言**:规则正文用**简体中文**;`paths:` frontmatter、文件路径、`file::Class.method`
  锚点、slug、枚举值保持原样(英文/符号不变)。下方模板仅示结构,实际产出中文正文。
- `paths:` is derived from the controls' `protects` globs; omit the field only if
  no meaningful path scope exists.
- One file per category. Filename `security-<category>.md`.
- Anchors are `file::Class.method` or `file:line` — clickable, no long code (R3).
- **Never** emit `AGENTS.md` or `.opencode/...` in this format (that is opencode).

> Verified against Claude Code docs as of 2026-06; record the verification date
> in `init_manifest.json`. If the host version disagrees, prefer the host.
