<!--
  rules-format fragment — opencode (verified 2026-06).
  Source: opencode.ai/docs/rules ; GitHub issue #11454 (.opencode/AGENTS.md NOT loaded).
  opencode loads AGENTS.md from project root (+ parents walking up). No
  path-scoping; no dot-directory support.
-->

# opencode rules format (use ONLY when `--format opencode`)

opencode's project-level rules live in a single **root `AGENTS.md`**. It walks
parent directories for more `AGENTS.md`; it does **not** load `.opencode/AGENTS.md`
(issue #11454) and has no per-path scoping. So all categories go into ONE file,
as sections.

## File: `<target>/AGENTS.md`

Append (within a managed sentinel block — non-destructive):

```markdown
<!-- mgh-init:begin -->
## Security design — reuse, do not reinvent

The project already encapsulates these security controls. When writing new
code, reuse them instead of reimplementing.

### <Category 1>
- **<Control name>**: <one line>. Use: <usage>. Anchor: `src/.../X.java::Class.method`.
  Caveat: <gap if any>.
- ...

### <Category 2>
- ...
<!-- mgh-init:end -->
```

## Rules
- **输出语言**:各 category 小节正文用**简体中文**;sentinel 标记、文件路径、`file::Class.method`
  锚点、slug 保持原样(英文/符号不变)。下方模板仅示结构,实际产出中文正文。
- ONE root `AGENTS.md`. Do NOT create `.opencode/AGENTS.md`.
- Category sections inside the single managed block; idempotent re-run replaces
  only the `<!-- mgh-init:begin --> … <!-- mgh-init:end -->` block.
- Anchors `file::Class.method` / `file:line`; no long code (R3).
- **Never** emit `.claude/rules/` in this format (that is Claude Code).

> Verified against opencode docs as of 2026-06; record in `init_manifest.json`.
