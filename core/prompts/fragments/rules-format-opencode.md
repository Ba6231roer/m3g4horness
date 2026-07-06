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

## Emission flow (two steps — T3 writes fragments, a script assembles)

1. **T3 `init-rulewriter`** writes ONE staged fragment per category to
   `<target>/.mgh-init/rules-parts/<category>.md` — a bare category section,
   **no outer sentinel**, never `AGENTS.md` directly.
2. **`assemble_rules.py`** merges every fragment into a single **neutral** managed
   block in `<target>/AGENTS.md` (idempotent replace; preserves user content;
   sweeps legacy branded blocks on first run; purity-lints the result).

## Fragment body (what T3 writes — `<category>.md`, no sentinel)

```markdown
### <Category>
- **<Control name>**: <一句话>. 用法: <usage>. 锚点: `src/.../X.java::Class.method`. 缺口: <gap if any>.
- ...
```

## Assembled managed block (what ends up in `AGENTS.md` — owned by the script)

```markdown
<!-- security-controls:begin -->
## 安全设计 — 复用,勿重造

<各 fragment 顺序拼接>
<!-- security-controls:end -->
```

## Rules
- **输出语言**:各 category 小节正文用**简体中文**;中性哨兵标记、文件路径、
  `file::Class.method` 锚点、slug 保持原样(英文/符号不变)。上方模板仅示结构,实际产出中文正文。
- ONE root `AGENTS.md`. Do NOT create `.opencode/AGENTS.md`.
- T3 MUST NOT emit any sentinel or write `AGENTS.md` directly; `assemble_rules.py`
  owns the single `<!-- security-controls:begin --> … <!-- security-controls:end -->`
  block. The neutral sentinel carries **no tool name**.
- Anchors `file::Class.method` / `file:line`; no long code (R3).
- **Rule-body purity**: describe ONLY the target project's control; `NEVER` mention
  this tool's name / scripts / pipeline tiers / internal paths — `assemble_rules.py
  --check` fails loud on any leak.
- **Never** emit `.claude/rules/` in this format (that is Claude Code).

> Verified against opencode docs as of 2026-06; record in `init_manifest.json`.
