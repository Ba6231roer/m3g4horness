# Contract: runtime hook enforcement (`block_adhoc_scripts`)

Producer: orchestrator shell step 0 (Bash `printf` writes the sentinel; `write_runconfig.py`
may co-write it for `/mgh-init` as an optimization). Consumer: the shared guard
`releases/{claude-code/hooks,opencode/hooks}/block_adhoc_scripts.py` (byte-identical twin;
the opencode `.ts` plugin is glue-only and pipes to the same `.py`). Spec:
`openspec/specs/runtime-hook-enforcement/spec.md`.

> **激活 = env 或磁盘哨兵(最优锚点起有界向上发现)。** 守卫在一个 mgh 运行域内激活当且仅当
> (a) env `MGH_<DOM>_ACTIVE=1` 已设,**或** (b) 锚到盘根链上任一级 `<dir>/<run-root>/.active`
> 哨兵存在。锚 = **最优可用 cwd 信号**:hook stdin payload 的 `cwd` 字段(claude PreToolUse
> 携带会话/工具 cwd——发起工具调用的那个上下文)优先,缺省回退守卫进程 cwd(opencode 插件
> 进程)。哨兵发现从锚自身起**向上 walk**(锚 → 逐祖先,至盘根或 16 级有界,先到者止),每级
> 查 `<dir>/<run-root>/.active`。向上 walk 闭合锚错配缺口:reader subagent(或从别处启动的
> 宿主)锚 cwd 是 target 子目录任意深度,仍能在 `<target>/<run-root>/.active` 命中哨兵——旧
> cwd-only 单点发现在该锚下找不到哨兵 → 守卫休眠 → 读/写侧全部静默降级放行。哨兵绕开
> opencode「插件进程不继承 mid-session bash 导出的 env」的可靠性边界。运行域外(锚起向上
> walk 全链有界皆无哨兵且无 env):退出码 0 放行(零日常噪声)。
>
> **opencode 残余边界(显式运行要求,非缺陷)**:插件进程 cwd = opencode 服务器启动目录,env
> 又不继承——若从 target 树**外**启动 opencode,锚不在 target 链上,守卫整 run 休眠。守卫
> **NEVER 整盘扫描补偿**(性能 + 越权)。运行要求:**在 target 根或其子目录启动 opencode**。
> 这优于现状(现状连从 target 子目录启动都休眠)。

## Sentinel `<dir>/<run-root>/.active` (anchored upward discovery)

```json
{"domain": "mgh-init", "target": "<abs target>", "out_roots": ["<abs>..."], "v": 1}
```

| Field | Purpose |
|---|---|
| `domain` | `mgh-init` / `mgh-sast` / `mgh-sra` / `mgh-srr` / `mgh-ut-init` (advisory; discovery is by path) |
| `target` | abs project root (Windows-native; **MUST** come from a Python leaf-script stdout — `describe_artifact --field repo` / `prepare_augment`/`ingest_requirements` stdout `project_root` / `write_runconfig` stdout `target` — never bash `pwd`, which emits MSYS `/c/...` that pathlib mis-resolves on Windows) |
| `out_roots[]` | abs roots for customized `--out` / `--rules-dir` (init & ut-init; honors custom output locations without over-blocking) |
| `v` | schema version |

### Per-domain run-root (sentinel location, discovered on the anchor chain)

| Domain | env flag | run-root | sentinel path |
|---|---|---|---|
| `mgh-init` | `MGH_INIT_ACTIVE` | `.mgh-init` | `<dir>/.mgh-init/.active` |
| `mgh-sast` | `MGH_SAST_ACTIVE` | `security-scan` | `<dir>/security-scan/.active` |
| `mgh-sra` | `MGH_SRA_ACTIVE` | `.mgh-sra` | `<dir>/.mgh-sra/.active` |
| `mgh-srr` | `MGH_SRR_ACTIVE` | `.mgh-srr` | `<dir>/.mgh-srr/.active` |
| `mgh-ut-init` | `MGH_UT_INIT_ACTIVE` | `.mgh-ut-init` | `<dir>/.mgh-ut-init/.active` |

`<dir>` runs over the anchor-to-drive-root chain (anchor itself first, then each ancestor,
bounded to 16 levels / the filesystem root). The anchor = payload `cwd` (claude) ?? guard
process cwd (opencode).

### Lifecycle

- **step 0 (orchestrator, Bash)**: after `export MGH_<DOM>_ACTIVE=1`, write the sentinel.
  `target` filled from the first Python leaf-script stdout that yields the abs project root
  (init: `write_runconfig`/`describe_artifact`; sra: `prepare_augment`; srr: `ingest_requirements`;
  ut-init: `write_ut_runconfig`; sast: activation-only — `target` empty, out-of-tree uses
  `MGH_TARGET` env on claude / degrades on opencode, sast output already narrowed to
  `security-scan/`).
- **completion / clean-stop (orchestrator, Bash)**: `rm <sentinel>` so a stale sentinel does
  not arm the guard during subsequent day-to-day dev. Residual (crash without cleanup) only
  blocks script writes, never JSON/`.md`/reads; user may `rm` manually.

## MGH_TARGET resolution (subtree check)

Precedence: **env `MGH_TARGET` > `sentinel.target` > degrade**. When both are absent the
subtree check degrades to pass (the anchor is the implicit run-root context — sentinel
discovery is anchor-relative — but is **not** used as a hard block target, to avoid
over-blocking when no target was pinned).

## Runtime write discipline (active guard)

1. **Bash `py -c`/`python -c` introspection** of artifacts (`import json` / `open(` / `load(` /
   `.json`) → exit 2 + recipe.
2. **Script-write block** — `Write`/`Edit` of any extension in
   `_SCRIPT_EXTS = {.py, .ps1, .sh, .bash, .zsh, .bat, .cmd, .ts, .js, .mjs, .cjs}` → exit 2.
   **No path whitelist** (the prior `core/scripts` + `tests`/`tools`/`hooks` exemptions only
   mattered while inactive, at which point `main()` already returned 0). Leaf scripts are
   read-only at runtime. `.json`/`.md` are not in the set (legit artifacts).
3. **Write confinement** — `Write`/`Edit` resolved target:
   - **all five domains**: block if OUTSIDE the resolved `MGH_TARGET` tree (drive root, `%TEMP%`,
     another project dir).
   - **`mgh-init` AND `mgh-ut-init` additionally** (positive allowlist): block unless inside a
     sanctioned subtree (see the two tables below). `out_roots[]` extends the allowlist.
     sast/sra/srr retain the out-of-tree check **without** the allowlist.
4. **Bash whole-read** of a multi-unit aggregate (cat/head/tail/type/Get-Content of
   `clusters.json` / `controls_candidates.json` / `scout_plan.json` / `controls_inventory.json`
   / `s3_chunks.json` / `s5_filtered.json` / `scope_manifest.json` / `change_context.json`)
   → exit 2 (request-context-budget defense-in-depth; structural fix = `list_* --materialize`).
5. **Write/delete-side out-of-tree interception (Bash + tool face)** — the read-side's symmetric
   closure for the mutation surface. `MGH_TARGET` precedence + `is_relative_to(target)` semantics
   identical to (3) and the read side; target absent ⇒ degrade to pass. Regex-over-observed-shape
   (does NOT claim exhaustive coverage of pipes/aliases/env-injected paths, PowerShell `.NET`
   static methods, `robocopy`/`fsutil` — same stance as temp-I/O / file-assoc / read-side Bash
   file-search).

   | Surface | Verb / shape | Destination judged | Blocked when |
   |---|---|---|---|
   | Bash write verb | `New-Item`/`ni`, `Set-Content`/`sc`, `Add-Content`/`ac`, `Out-File`, `tee`, `mkdir`/`md`, `Copy-Item`/`cpi`/`cp`/`copy`/`xcopy`, `Move-Item`/`mi`/`mv`, `rename`/`Rename-Item` (leading token of the command or a sub-command after `;`/`\|`/`&&`/`\|\|`) | any out-of-tree absolute-path token; Copy/Move/xcopy = LAST token (destination) | destination resolves outside `MGH_TARGET` tree, OR no explicit path + cwd outside the target tree |
   | Bash delete verb | `Remove-Item`/`ri`, `del`, `erase`, `rm`, `rmdir`/`rd` (leading token) | any out-of-tree absolute-path token | outside `MGH_TARGET` tree, OR no path + cwd outside the target tree → **delete-side recipe** (irreversible; NEVER sibling modules) |
   | Bash redirect | `>` / `>>` to any target (generalizes the temp-only redirect) | the redirect target | resolves outside `MGH_TARGET` tree (temp targets still caught by the retained temp-I/O rule) |
   | In-tree Bash write (P1) | write verb / redirect destination INSIDE `MGH_TARGET` | the destination | `mgh-init`/`mgh-ut-init`: outside a sanctioned subtree (root pollution `Set-Content <target>\evil.txt`) — mirrors the Write/Edit tool-layer allowlist. sast/sra/srr: pass (no allowlist) |
   | Rule-a relabel (L1) | `py -c` WRITE/DELETE shape (`write(`/`makedirs`/`shutil.copy`/`shutil.move`/`shutil.rmtree`/`os.replace`/`os.rename`/`os.remove`/`os.unlink`/`write_text`/`write_bytes`) | any out-of-tree absolute path | outside `MGH_TARGET` tree → write/delete recipe (NOT introspection); pure in-tree `py -c` writes governed by the tool layer |
   | Tool face | claude `MultiEdit`/`NotebookEdit` (`file_path` / `notebook_path`) enter the write-confinement branch like `Write`/`Edit` | the path | outside tree / blocked script-ext / (init/ut-init) non-sanctioned subtree. `.ipynb` is NOT a script-ext (artifact) |
   | Tool face | opencode `apply_patch` (`paths[]` extracted from `patchText` `*** (Add\|Update\|Delete) File:` / `*** Move to:` markers by the `.ts` shim; delete op → delete wording) | each path | ANY path outside tree / blocked script-ext / non-sanctioned subtree |

   A hit → exit 2 + stderr **write-side recipe** (points at producer stdout `checkpoint_path` /
   `rule_path` / `draft_path` absolute paths; NEVER Bash `Set-Content`/`New-Item`/`tee`/`>` /
   `apply_patch`/`MultiEdit`/`NotebookEdit` outside the tree). A delete hit additionally calls
   out irreversibility ("NEVER `Remove-Item`/`del`/`rm`/`rmtree` outside the target tree,
   including sibling modules").

### `mgh-init` sanctioned subtrees (positive allowlist)

| Subtree | Purpose |
|---|---|
| `<target>/.mgh-init/**` | artifacts / checkpoints / inputs / manifest / report / sentinel |
| `<target>/.claude/rules/**` | claude rules output |
| `<target>/docs/security-controls/**` | opencode per-category detail files |
| `<target>/AGENTS.md` | opencode lazy index |
| `out_roots[]` (sentinel) | customized `--out` / `--rules-dir` abs roots |

### `mgh-ut-init` sanctioned subtrees (positive allowlist)

Same shape as init (ut-init writes rules into the project root too): `mgh-ut-init` is the
fifth run-domain and the second rules-writing command.

| Subtree | Purpose |
|---|---|
| `<target>/.mgh-ut-init/**` | artifacts / checkpoints / inputs / run_config / sentinel |
| `<target>/.claude/rules/**` | claude test-convention rules output (`test-*.md`) |
| `<target>/docs/test-conventions/**` | opencode per-category detail files |
| `<target>/AGENTS.md` | opencode lazy index |
| `out_roots[]` (sentinel) | customized `--out` / `--rules-dir` abs roots |

A hit → exit 2 + stderr recipe pointing at `list_*` / `describe_artifact` / producer stdout
`checkpoint_path` / `rule_path` / `draft_path`.

## Runtime read discipline (active guard)

The read side is the **peer** of the write discipline — same `MGH_TARGET` precedence
(env > sentinel.`target` > degrade), same `Path.resolve().is_relative_to(target)` semantics,
NOT a positive-allowlist check (any file inside the target tree is readable; the goal is
"stay in the working project", not "stay in a sanctioned subtree"). It replaces the soft
failure (a cross-module read reaching the host **permission prompt and interrupting the
run**) with a fail-loud recipe. `MGH_TARGET` absent => the read check degrades to pass
(NEVER a hard read block when no target was pinned; the script-ext write block / `py -c` /
temp-I/O / file-assoc blocks still fire).

| Layer | Tool / shape | Anchor | Blocked when |
|---|---|---|---|
| Tool abstraction | `Read` | `file_path` | resolved `file_path` outside the target tree |
| Tool abstraction | `Glob` / `Grep` | `path` (default = cwd) | resolved `path` outside; `path` absent + cwd outside (cwd-drift leak) |
| Tool abstraction | — | `pattern` / `glob` | **NOT parsed** (the `path` anchor is authoritative; conservative vs false positives) |
| Bash escape | `Bash: rg`/`ripgrep`/`grep`/`egrep`/`fgrep`/`findstr`/`find`/`fd`/`ag`/`ack` (leading token of the command or a sub-command after `;`/`\|`/`&&`/`\|\|`) | any explicit absolute-path argument OR cwd | any absolute-path arg resolves outside, OR no abs path + cwd outside |
| Path resolution | `..` chain (e.g. `<target>\aa\bb\cc\..\..\..\..\xxxx` folding to a drive root) | the resolved path | `Path.resolve()` folds `..` segments; a chain that climbs out of the tree resolves outside and is blocked (the reported D-root permission-prompt interrupt shape) |
| Path resolution | hallucinated out-of-tree prefix (an underscore dir name regenerated as a separator pair, e.g. `acme_wing` → `acme\wing`) | the resolved path | resolves outside the tree and is blocked by the same out-of-tree judgment — no directory-name semantics are attempted |

A hit → exit 2 + stderr **read-side recipe** (points at "read only this batch's `input_path`/
`targets[]`; anchor `Glob`/`Grep` (and `rg`/`grep`/… in Bash) at the repo root; NEVER read
the parent dir / sibling modules"). Regex-over-observed-shape: pipes/aliases/env-injected
paths in the Bash file-search form are NOT guaranteed (same stance as the temp-I/O and
file-association rules); a `--flag <path>` argument on a non-search verb does NOT trip.

### Read-side path materialization (scout / T1 fan-out)

`list_scout_batches.py` / `list_clusters.py` materialize each fan-out unit's file paths
(`targets[].file` / `evidence_files[]` / `usage_sites[]` / candidate `file`) **ABSOLUTE**
(resolved against the plan's `repo`), keeping the original as `repo_relative`. A subagent
thus resolves the same file under any cwd AND stays inside the target tree (so the read
check passes it) — closing the non-subjective out-of-tree read path (fan-out output paths
are already absolute for the write side; this extends that absolutization to the read side).

## Guard tool-surface wiring coverage (CI-enforced invariant)

The guard's decision-branch tool set (every tool name `main()` dispatches on: `Bash`,
`Write`, `Edit`, `MultiEdit`, `NotebookEdit`, `ApplyPatch`, `Read`, `Glob`, `Grep`) SHALL
be fully covered by **BOTH** host wiring faces, enforced by a regression test:

| Face | What must cover every guard tool name | Where |
|---|---|---|
| claude install face | the default PreToolUse matcher `_DEFAULT_MATCHER` (`\|`-split) | `tools/install_hook.py` |
| opencode plugin face | the `.ts` shim `HANDLED` set + its lowercase `normalize` mapping | `releases/opencode/plugins/block_adhoc_scripts.ts` |

Adding a guard decision branch WITHOUT extending both wiring faces SHALL fail the regression
test (`tests/test_opencode_hook_parity.py::TestWiringCoverage`) — structurally closing the
"dead branch" gap class on both hosts. The claude matcher previously covered only
`Bash|Write|Edit`, leaving the read-side / tool-face branches unconsulted (an out-of-tree
`Read` reached the host permission prompt and interrupted the run instead of failing loud
with a recipe); nothing prevented the same drift on opencode. Reinstall evolves a legacy
matcher (`Bash|Write|Edit` ⊂ default) in place; a user-customized non-subset matcher is left
untouched (stderr note).

## Cross-references

- Guard source (single decision source): `releases/claude-code/hooks/block_adhoc_scripts.py`
  (opencode twin byte-identical; parity test `tests/test_opencode_hook_parity.py`).
- Guard unit tests: `tests/test_block_adhoc_scripts.py` (incl. upward-walk sentinel discovery).
- Wiring coverage test: `tests/test_opencode_hook_parity.py::TestWiringCoverage`.
- Install / opt-out (`--no-enforce-hook`): `install.sh` + `core/contracts/.../spec.md` per command.
