# Contract: runtime hook enforcement (`block_adhoc_scripts`)

Producer: orchestrator shell step 0 (Bash `printf` writes the sentinel; `write_runconfig.py`
may co-write it for `/mgh-init` as an optimization). Consumer: the shared guard
`releases/{claude-code/hooks,opencode/hooks}/block_adhoc_scripts.py` (byte-identical twin;
the opencode `.ts` plugin is glue-only and pipes to the same `.py`). Spec:
`openspec/specs/runtime-hook-enforcement/spec.md`.

> **激活 = env 或磁盘哨兵。** 守卫在一个 mgh 运行域内激活当且仅当
> (a) env `MGH_<DOM>_ACTIVE=1` 已设,**或** (b) `<cwd>/<run-root>/.active` 哨兵存在。
> 哨兵绕开 opencode「插件进程不继承 mid-session bash 导出的 env」的可靠性边界——env-only
> 激活在 opencode 上整 run 休眠,哨兵兜底。运行域外(二者皆无):退出码 0 放行(零日常噪声)。

## Sentinel `<cwd>/<run-root>/.active`

```json
{"domain": "mgh-init", "target": "<abs target>", "out_roots": ["<abs>..."], "v": 1}
```

| Field | Purpose |
|---|---|
| `domain` | `mgh-init` / `mgh-sast` / `mgh-sra` / `mgh-srr` (advisory; discovery is by path) |
| `target` | abs project root (Windows-native; **MUST** come from a Python leaf-script stdout — `describe_artifact --field repo` / `prepare_augment`/`ingest_requirements` stdout `project_root` / `write_runconfig` stdout `target` — never bash `pwd`, which emits MSYS `/c/...` that pathlib mis-resolves on Windows) |
| `out_roots[]` | abs roots for customized `--out` / `--rules-dir` (init only; honors custom output locations without over-blocking) |
| `v` | schema version |

### Per-domain run-root (sentinel location, cwd-relative)

| Domain | env flag | run-root | sentinel path |
|---|---|---|---|
| `mgh-init` | `MGH_INIT_ACTIVE` | `.mgh-init` | `<cwd>/.mgh-init/.active` |
| `mgh-sast` | `MGH_SAST_ACTIVE` | `security-scan` | `<cwd>/security-scan/.active` |
| `mgh-sra` | `MGH_SRA_ACTIVE` | `.mgh-sra` | `<cwd>/.mgh-sra/.active` |
| `mgh-srr` | `MGH_SRR_ACTIVE` | `.mgh-srr` | `<cwd>/.mgh-srr/.active` |

### Lifecycle

- **step 0 (orchestrator, Bash)**: after `export MGH_<DOM>_ACTIVE=1`, write the sentinel.
  `target` filled from the first Python leaf-script stdout that yields the abs project root
  (init: `write_runconfig`/`describe_artifact`; sra: `prepare_augment`; srr: `ingest_requirements`;
  sast: activation-only — `target` empty, out-of-tree uses `MGH_TARGET` env on claude / degrades
  on opencode, sast output already narrowed to `security-scan/`).
- **completion / clean-stop (orchestrator, Bash)**: `rm <sentinel>` so a stale sentinel does
  not arm the guard during subsequent day-to-day dev. Residual (crash without cleanup) only
  blocks script writes, never JSON/`.md`/reads; user may `rm` manually.

## MGH_TARGET resolution (subtree check)

Precedence: **env `MGH_TARGET` > `sentinel.target` > degrade**. When both are absent the
subtree check degrades to pass (cwd is the implicit run root — sentinel discovery is
cwd-relative — but is **not** used as a hard block target, to avoid over-blocking when no
target was pinned).

## Runtime write discipline (active guard)

1. **Bash `py -c`/`python -c` introspection** of artifacts (`import json` / `open(` / `load(` /
   `.json`) → exit 2 + recipe.
2. **Script-write block** — `Write`/`Edit` of any extension in
   `_SCRIPT_EXTS = {.py, .ps1, .sh, .bash, .zsh, .bat, .cmd, .ts, .js, .mjs, .cjs}` → exit 2.
   **No path whitelist** (the prior `core/scripts` + `tests`/`tools`/`hooks` exemptions only
   mattered while inactive, at which point `main()` already returned 0). Leaf scripts are
   read-only at runtime. `.json`/`.md` are not in the set (legit artifacts).
3. **Write confinement** — `Write`/`Edit` resolved target:
   - **all domains**: block if OUTSIDE the resolved `MGH_TARGET` tree (drive root, `%TEMP%`,
     another project dir).
   - **`mgh-init` additionally** (positive allowlist): block unless inside a sanctioned subtree.
     `out_roots[]` extends the allowlist. sast/sra/srr retain the out-of-tree check **without**
     the allowlist.
4. **Bash whole-read** of a multi-unit aggregate (cat/head/tail/type/Get-Content of
   `clusters.json` / `controls_candidates.json` / `scout_plan.json` / `controls_inventory.json`
   / `s3_chunks.json` / `s5_filtered.json` / `scope_manifest.json` / `change_context.json`)
   → exit 2 (request-context-budget defense-in-depth; structural fix = `list_* --materialize`).

### `mgh-init` sanctioned subtrees (positive allowlist)

| Subtree | Purpose |
|---|---|
| `<target>/.mgh-init/**` | artifacts / checkpoints / inputs / manifest / report / sentinel |
| `<target>/.claude/rules/**` | claude rules output |
| `<target>/docs/security-controls/**` | opencode per-category detail files |
| `<target>/AGENTS.md` | opencode lazy index |
| `out_roots[]` (sentinel) | customized `--out` / `--rules-dir` abs roots |

A hit → exit 2 + stderr recipe pointing at `list_*` / `describe_artifact` / producer stdout
`checkpoint_path` / `rule_path` / `draft_path`.

## Cross-references

- Guard source (single decision source): `releases/claude-code/hooks/block_adhoc_scripts.py`
  (opencode twin byte-identical; parity test `tests/test_opencode_hook_parity.py`).
- Guard unit tests: `tests/test_block_adhoc_scripts.py`.
- Install / opt-out (`--no-enforce-hook`): `install.sh` + `core/contracts/.../spec.md` per command.
