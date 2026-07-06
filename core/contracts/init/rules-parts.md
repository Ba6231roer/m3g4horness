# Contract: staged rules fragments (`<target>/.mgh-init/rules-parts/<category>.md`)

Producer: `init-rulewriter` (T3, `--format opencode` only). Consumer:
`assemble_rules.py` (merges into root `AGENTS.md`). **opencode-only** — claude
format writes `.claude/rules/security-<category>.md` directly (no staging).

## Purpose

T3 fans out per-category in isolated contexts; writing the single root `AGENTS.md`
concurrently would race / interleave. So each T3 subagent writes a **neutral staged
fragment** (one category), and the deterministic `assemble_rules.py` later merges
them into ONE managed block — eliminating the race and keeping the root context
minimal + brand-free.

## Location & naming

- Dir: `<target>/.mgh-init/rules-parts/`
- One file per category: `<category>.md` where `<category>` ∈ init 8
  (`authentication` / `authorization` / `input-validation` / `data-masking` /
  `crypto` / `rate-limiting` / `csrf` / `audit-logging`). The stem is the
  `category` from `controls_inventory.json`.
- Categories with no inventory entry produce no fragment (the assembler simply has
  nothing to merge for that category).

## Fragment shape

A bare category section — **no outer sentinel**, no H2 header (the assembler owns
the `## 安全设计` header and the `<!-- security-controls:begin/end -->` sentinels):

```markdown
### <Category>
- **<Control name>**: <一句话>. 用法: <usage>. 锚点: `src/.../X.java::Class.method`. 缺口: <gap if any>.
- ...
```

## Rules

- **Neutral & sentinel-free**: the fragment MUST NOT contain
  `<!-- mgh-init:… -->` or `<!-- security-controls:… -->` sentinels — those are the
  assembler's responsibility.
- **Purity**: the body SHALL describe ONLY the target project's control; `NEVER`
  mention this tool's name / scripts / pipeline tiers / internal paths
  (`assemble_rules.py --check` fails loud on leaks; see inventory.md purity rule).
- **Language**: body in 简体中文; `file::Class.method` anchors, paths, slugs stay
  verbatim.
- **Anchors only, no long code**: `file::Class.method` / `file:line`, no > 3–5
  line pastes.
- **Idempotent producer**: re-running T3 overwrites the same `<category>.md`; the
  assembler handles idempotent merge into `AGENTS.md`.

## Assembler contract (for reference)

`assemble_rules.py --target <t> --format opencode` globs `<parts>/*.md` (sorted by
filename for determinism), concatenates bodies under the managed block, and writes
`<target>/AGENTS.md`. stdout summary reports `categories[]`,
`migrated_legacy_blocks`, and `lint`. See `core/scripts/assemble_rules.py --help`.
