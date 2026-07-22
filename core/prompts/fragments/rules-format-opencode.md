<!--
  rules-format fragment — opencode (verified 2026-06).
  Source: opencode.ai/docs/rules (.opencode/AGENTS.md NOT loaded; "Manual Instructions
  in AGENTS.md" = keep AGENTS.md concise, @-reference detail guides, load lazily).
  opencode loads AGENTS.md from project root (+ parents walking up) eagerly into the
  root context. No path-scoping; no dot-directory support — so rule BODIES live in
  per-category detail files loaded on demand, and AGENTS.md carries only a concise
  lazy-load INDEX (built by assemble_rules.py).
-->

# opencode rules format (use ONLY when `--format opencode`)

opencode's project-level rules live in a single **root `AGENTS.md`**, which it loads
**eagerly and in full** into the root context (it walks parent directories for more
`AGENTS.md`; it does **not** load `.opencode/AGENTS.md` and has no per-path scoping).
So AGENTS.md MUST stay concise: it carries only a **lazy-load index** of the rule
categories, and the rule **bodies** live in **one independent detail file per category**,
loaded on demand.

## Emission flow (T3 writes detail files directly; a script builds the index)

1. **T3 `init-rulewriter`** writes ONE shipped detail file per category directly to
   `<target>/<rules-dir>/<category>.md` (default `<target>/docs/security-controls/<cat>.md`;
   `--rules-dir` override) — an **independent H1 document**, neutral, no outer sentinel,
   **never** `AGENTS.md` directly.
2. **`assemble_rules.py`** globs `<rules-dir>/*.md`, builds the concise **index block**
   in `<target>/AGENTS.md` (one `@<rel>` line per detail file; display name = the file's
   first `#` heading, fallback filename stem), idempotently replacing the same-sentinel
   block (preserves user content; sweeps legacy branded blocks on first run; purity-lints
   the detail files).

## Detail file body (what T3 writes — `<rules-dir>/<category>.md`, independent H1)

```markdown
# <Category> 安全控制

- **<Control name>**: <一句话>. 用法: <usage>. 锚点: `src/.../X.java::Class.method`. 有效性注意: <仅既有控制的有效性,如「只覆盖 POST」;无则省略>
- ...
```

## Index block (what ends up in `AGENTS.md` — owned by the script, NOT T3)

```markdown
<!-- security-controls:begin -->
## 安全设计 — 复用,勿重造

本项目已梳理出以下**既有可复用安全控制**...**按需加载**:仅当要改动的代码涉及某领域时,用 Read 工具读对应文件;勿预先全加载(省上下文)。
- <展示名> → @docs/security-controls/<category>.md
> 涉及以上领域的新代码 MUST 先 Read 对应文件、复用既有实现;无对应文件 = 该领域无梳理出的存量控制。
<!-- security-controls:end -->
```

## Lazy-load semantics

opencode has **no path-scoping**, so detail files are NOT auto-triggered by path. Loading
is **semantic**: the index block's `@<rel>` reference plus its on-demand directive
("Read the detail file only when the task touches that domain") drive the lazy load —
verbatim-aligned with opencode docs "Manual Instructions in AGENTS.md". T3 does NOT need
to know about or write the index block; `assemble_rules.py` owns it. The detail file
itself carries NO front matter (opencode would not use it anyway; front matter only
wastes the context loaded on demand).

## Rules
- **No front matter (hard boundary)**: opencode has **no** path-scoping and detail files
  carry **no** front matter (only claude uses `paths:`). A detail file SHALL start with
  `# <Category> 安全控制`; NEVER open with a `---` YAML fence; NEVER carry inventory-schema
  field names (`found_controls` / `evidence_count` / `category:` / `source:` / `evidence:`)
  as front matter or metadata. `assemble_rules.py --check` fails loud (exit 2) on any `---`
  fence or schema-field leak inside a detail file.
- **输出语言**:各 category 详述文件正文用**简体中文**;中性哨兵标记、文件路径、
  `file::Class.method` 锚点、slug 保持原样(英文/符号不变)。上方模板仅示结构,实际产出中文正文。
- ONE root `AGENTS.md` (index only) + detail files under `<rules-dir>/`. Do NOT create
  `.opencode/AGENTS.md`; do NOT list detail files in `opencode.json` `instructions`
  (that field is **eager** — it would load everything into the root context, defeating
  this format's purpose).
- T3 MUST NOT emit any sentinel or write `AGENTS.md` directly; `assemble_rules.py` owns
  the single `<!-- security-controls:begin --> … <!-- security-controls:end -->` index
  block. The neutral sentinel carries **no tool name**.
- Anchors `file::Class.method` / `file:line` SHALL point at **target-project source**
  only (e.g. `src/.../X.java::Class.method`); NEVER point at scanner / regex internals
  or "how it was discovered"; no long code.
- **Rule-body purity**: describe ONLY the target project's control; `NEVER` mention
  this tool's name / scripts / pipeline tiers / internal paths / scanner-or-regex
  definitions — `assemble_rules.py --check` fails loud on any leak. A control with no
  source anchor gets **no rule**; if the whole category has no implementation, write
  **no detail file** and still touch `done_marker` (see `init-rulewriter.md`).
- **Never** emit `.claude/rules/` in this format (that is Claude Code).

> Verified against opencode docs as of 2026-06; record in `init_manifest.json`.
