# Contract: shipped rules detail files (`<target>/<rules-dir>/<category>.md`)

Producer: `init-rulewriter` (T3, `--format opencode` only). Consumers:
`assemble_rules.py` (builds the lazy index) + the target agent (Reads on demand).
**opencode-only** — claude format writes `.claude/rules/security-<category>.md`
directly (already lazy via `paths:` scoping).

## Purpose

opencode loads the root `AGENTS.md` **eagerly and in full** into the root context, so
the rule BODIES must NOT live inline there. Instead T3 writes ONE shipped detail file
per category, and `assemble_rules.py` builds a concise lazy-load INDEX in `AGENTS.md`
that `@`-references them; the target agent Reads a detail file only when the task
touches that domain (semantic lazy load — opencode has no path-scoping). T3 fans out
per-category in isolated contexts; since each category is its own file, there is no
write race and no staging step — T3 writes the shipped file directly.

## Location & naming

- Dir: `<target>/<rules-dir>/` (default `<target>/docs/security-controls/`;
  `--rules-dir` override on `list_rule_jobs.py` / `assemble_rules.py`).
- One file per category: `<category>.md` where `<category>` ∈ init 8
  (`authentication` / `authorization` / `input-validation` / `data-masking` /
  `crypto` / `rate-limiting` / `csrf` / `audit-logging`). The stem is the
  `category` from `controls_inventory.json`.
- Categories with no implementation produce no detail file (the index simply has no
  line for that category — no orphan reference).

## Detail file shape

An **independent H1 document** — no outer sentinel (the assembler owns the
`## 安全设计` header and the `<!-- security-controls:begin/end -->` index block):

```markdown
# <Category> 安全控制

- **<Control name>**: <一句话>. 用法: <usage>. 锚点: `src/.../X.java::Class.method`. 有效性注意: <gap if any>.
- ...
```

The first `#` heading (minus the template ` 安全控制` suffix) is the index display name;
a detail file with no `#` heading falls back to its filename stem.

## Rules

- **Neutral & sentinel-free**: the detail file MUST NOT contain
  `<!-- mgh-init:… -->` or `<!-- security-controls:… -->` sentinels — those are the
  assembler's responsibility. MUST NOT be listed in `opencode.json` `instructions`
  (that field is eager and would defeat the lazy load).
- **No front matter**: opencode has no path-scoping; detail files carry NO YAML
  `---` fence and NO inventory-schema fields (`found_controls` / `evidence_count` /
  `category:` / `source:` / `evidence:`). Start with `# <Category> 安全控制`.
- **Purity**: the body SHALL describe ONLY the target project's control; `NEVER`
  mention this tool's name / scripts / pipeline tiers / internal paths
  (`assemble_rules.py --check` fails loud on leaks; see inventory.md purity rule).
- **Language**: body in 简体中文; `file::Class.method` anchors, paths, slugs stay
  verbatim.
- **Anchors only, no long code**: `file::Class.method` / `file:line`, no > 3–5
  line pastes.
- **Idempotent producer**: re-running T3 overwrites the same `<category>.md`;
  `assemble_rules.py` handles idempotent index rebuild in `AGENTS.md`.

## Assembler contract (for reference)

`assemble_rules.py --target <t> --format opencode [--rules-dir <dir>]` globs
`<rules-dir>/*.md` (sorted by filename for determinism), derives each index line's
display name + `@<rel-to-target>` reference, writes the concise
`<!-- security-controls:begin --> … :end -->` index block into `<target>/AGENTS.md`
(idempotent replace; sweeps legacy branded blocks), and purity-lints every detail
file. stdout summary reports `rules_dir`, `categories[]`, `migrated_legacy_blocks`,
`lint`, and `coverage`. See `core/scripts/assemble_rules.py --help`.

## Coverage gate(装配边界对账;两 format 共用)

装配在纯净 lint 之外做**清单↔规则覆盖对账**:`controls_inventory.json` 中每条带
evidence 的控制,至少一个 evidence token 的**路径**(整路径或文件名级;归一化大小写
与斜杠,与 T2 边界存在性闸门同一共享锚点模块)MUST 出现在其类别对应规则文件文本中
(opencode:`<rules-dir>/<cat>.md`;claude:`.claude/rules/security-<cat>.md`)。任一控制
未呈现 → opencode 面**不写盘**、退出码 2,stderr 按 category 输出未呈现计数与首 N
(默认 5,`--coverage-top`)控制名——编排器按既有 lint 违例同形路径**回 T3 修受影响
类别**(至多重派一轮);仍失败 → `assemble_rules.py --accept-coverage-gaps` 收口(唯一
放宽开关:对账照跑、披露照写,缺口计数与类别落 stdout `coverage`,编排器记入运行
报告与 manifest `boundaries[]`〔`coverage_gaps_accepted`〕,NEVER 静默放行)。通过或
放宽时 opencode 受管块尾幂等披露一行「覆盖:M/N 控制已入规则」;claude 面无受管块,
披露走 stdout + 运行报告。inventory 缺席(`--inventory` > `<target>/.mgh-init/
controls_inventory.json`)→ 对账跳过并在 stdout 披露(管线外独立使用;管线内步骤
顺序保证装配前 inventory 在场)。
