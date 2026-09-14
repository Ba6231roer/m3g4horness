# Contract: runtime hook enforcement (`block_adhoc_scripts`)

Producer: for `/mgh-init` (and `/mgh-ut-init`, which shares the writer), the sentinel is a
**deterministic side-effect of `write_runconfig.py`** (co-written atomically with
`run_config.json`; `resume_state.py --check` validates its existence mid-run and
`--rearm-sentinel` rewrites it from the persisted `run_config.target` on resume); other
domains write it from the orchestrator shell step 0 (Bash). Consumer: the shared guard
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

Optional field (absent by default; absence preserves the shape byte-for-byte):

```json
{"domain": "mgh-sdr", "target": "<abs target>", "out_roots": [], "read_roots": ["<abs external repo>"], "v": 1}
```

| Field | Purpose |
|---|---|
| `domain` | `mgh-init` / `mgh-sast` / `mgh-sra` / `mgh-srr` / `mgh-ut-init` / `mgh-sdr` (advisory; discovery is by path) |
| `target` | abs project root (Windows-native; **MUST** come from a Python leaf-script stdout — `describe_artifact --field repo` / `prepare_augment`/`ingest_requirements` stdout `project_root` / `write_runconfig` stdout `target` — never bash `pwd`, which emits MSYS `/c/...` that pathlib mis-resolves on Windows) |
| `out_roots[]` | abs roots for customized `--out` / `--rules-dir` (init & ut-init; honors custom output locations without over-blocking) |
| `read_roots[]` | **optional** abs external READ-ONLY roots (sdr: confirmed external repos the launcher/sdr_context actually searched). BOTH read faces honor them: the tool face (`Read`/`Glob`/`Grep`) AND the Bash face (search/listing verbs + the catch-all path-token allowset, rule m) — **语义反转** (the prior "tool-face only; Bash search verbs judged against `MGH_TARGET` alone" decision is reversed; what is readable at all is readable through any tool). The write side (tool + Bash verb + redirect + delete) is NEVER honored — judged against `MGH_TARGET` alone; likewise the leaf-source / `py -c` / temp-I/O / file-assoc blocks. **read_roots 最小化纪律**: declare only roots actually searched in this run — NEVER a user-supplied catch-all / drive root. Fail-closed: a declared root must exist and be a directory at judgment time; a missing root grants zero. |
| `v` | schema version |

`out_roots[]` (write-side allowlist extension, init/ut-init) and `read_roots[]` (read-side-only
extension, any domain) are independent fields with disjoint effects.

### Project read-roots config `<target>/.mgh/read-roots.json`

A per-project, hand-editable config extends the unified read allow-set in EVERY run-domain
(guard reads it on every active call, once — same order as the sentinel read):

```json
{"v": 1, "read_roots": ["<abs root>", "..."]}
```

| Aspect | Contract |
|---|---|
| Location | `<MGH_TARGET>/.mgh/read-roots.json` (inside the target tree — writes to it are governed by the ordinary write-confinement rules) |
| Union | entries merge with the sentinel's `read_roots[]` into ONE allow-set feeding the tool-face read rule, the Bash search/listing rules, and the rule-m catch-all net — the SAME set on both faces |
| Read-only | a config root NEVER grants write access (write side judges `MGH_TARGET` alone) and NEVER relaxes the leaf-source / `py -c` / temp-I/O / file-assoc blocks |
| Fail-closed | missing file = behavior identical to no config; malformed JSON / `read_roots` not a list / non-dict body = zero grants, no crash, no other judgment altered; each entry needs exist-and-is-dir containment at judgment time (a missing entry grants zero) |
| Tolerance | unknown fields ignored; non-string / blank entries skipped |
| Authoring | hand-editable by the user; the deterministic writer (sdr approval flow) is a follow-up change and not required |

**语义反转注记**: with rule m in place the Bash face judges paths directly (verb-independently),
so the prior decision that a declared root NEVER becomes a Bash-searchable location is REVERSED —
"凡允许读的目录,用什么工具读都放行". The read/write asymmetry is deliberate: declared roots are
readable, never writable.

### Per-domain run-root (sentinel location, discovered on the anchor chain)

| Domain | env flag | run-root | sentinel path |
|---|---|---|---|
| `mgh-init` | `MGH_INIT_ACTIVE` | `.mgh-init` | `<dir>/.mgh-init/.active` |
| `mgh-sast` | `MGH_SAST_ACTIVE` | `security-scan` | `<dir>/security-scan/.active` |
| `mgh-sra` | `MGH_SRA_ACTIVE` | `.mgh-sra` | `<dir>/.mgh-sra/.active` |
| `mgh-srr` | `MGH_SRR_ACTIVE` | `.mgh-srr` | `<dir>/.mgh-srr/.active` |
| `mgh-sdr` | `MGH_SDR_ACTIVE` | `.mgh-sdr` | `<dir>/.mgh-sdr/.active` |
| `mgh-ut-init` | `MGH_UT_INIT_ACTIVE` | `.mgh-ut-init` | `<dir>/.mgh-ut-init/.active` |

`<dir>` runs over the anchor-to-drive-root chain (anchor itself first, then each ancestor,
bounded to 16 levels / the filesystem root). The anchor = payload `cwd` (claude) ?? guard
process cwd (opencode).

### Lifecycle

- **step 0 (deterministic for init/ut-init)**: after `export MGH_<DOM>_ACTIVE=1`,
  `write_runconfig.py` co-writes the sentinel as a side-effect of its atomic
  `run_config.json` write — `target` = the already-computed Windows-native `target_abs`,
  `out_roots[]` derived from non-default `--out`/`--rules-dir` (default product roots are
  built into the guard allowlist and never listed). The orchestrator NEVER needs a
  `printf` recipe; the script running IS the sentinel existing. Other domains (sra/srr/
  sast) write it from the orchestrator step 0: `target` from the first Python leaf-script
  stdout that yields the abs project root (sra: `prepare_augment`; srr: `ingest_requirements`;
  sast: activation-only — `target` empty, out-of-tree uses `MGH_TARGET` env on claude /
  degrades on opencode, sast output already narrowed to `security-scan/`).
- **existence check (`resume_state.py --check`, init/ut-init)**: a run in progress
  (`run_config.json` present ∧ step ≠ `done`) with the sentinel missing = the guard is
  DORMANT → fail-loud (exit 2) with a re-arm recipe; a `done` run without the sentinel is
  NOT a violation (the guard should be dormant then).
- **resume re-arm (`resume_state.py --rearm-sentinel`, init/ut-init)**: deterministically
  rewrites the sentinel from the persisted `run_config.target` (+ `rules_dir`-derived
  out_roots) — the `--resume` / post-compaction first step; atomic + idempotent. Single
  source convention: fresh run → `write_runconfig` side-effect; resume → `resume_state`
  re-arm; both derive from `run_config`, never from an orchestrator `printf`.
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
   including sibling modules"). Unrecognized write-shaped verbs (`robocopy`/`fsutil`/`.NET`
   static methods/…) are no longer a silent pass: the rule-m catch-all net beneath blocks any
   out-of-tree token they carry — with the READ-net recipe (allowed roots + config remedy),
   not the write recipe, since the verb was never recognized as a write verb.

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
NOT a positive-allowlist check within the tree (any file inside the target tree is readable;
the goal is "stay in the working project", not "stay in a sanctioned subtree"). The allow-set
is the **unified read allow-set** = resolved `MGH_TARGET` tree ∪ sentinel `read_roots[]` ∪
project config `read_roots[]` — the SAME set on the tool face and the Bash face. It
replaces the soft failure (a cross-module read reaching the host **permission prompt and
interrupting the run**) with a fail-loud recipe. `MGH_TARGET` absent => the read checks
degrade to pass (NEVER a hard read block when no target was pinned; the script-ext write
block / `py -c` / temp-I/O / file-assoc blocks still fire).

| Layer | Tool / shape | Anchor | Blocked when |
|---|---|---|---|
| Tool abstraction | `Read` | `file_path` | resolved `file_path` outside the target tree **and** outside every declared `read_roots[]` root (sentinel ∪ config; a root must exist + be a dir at judgment time, else grants zero) |
| Tool abstraction | `Read` (leaf-source rule) | `file_path` | script extension ∧ `mgh-core/scripts` path segment (installed leaf script source — the read-side peer of "leaf scripts read-only"; target-project `.py` and non-script artifacts pass; fires even in the degrade-no-target case). NEVER relaxed by `read_roots[]` |
| Tool abstraction | `Glob` / `Grep` | `path` (default = cwd) | resolved `path` outside the target tree **and** outside every declared `read_roots[]` root; `path` absent + cwd outside both (cwd-drift leak) |
| Tool abstraction | — | `pattern` / `glob` | **NOT parsed** (the `path` anchor is authoritative; conservative vs false positives) |
| Bash escape | `Bash: rg`/`ripgrep`/`grep`/`egrep`/`fgrep`/`findstr`/`find`/`fd`/`ag`/`ack` (leading token of the command or a sub-command after `;`/`\|`/`&&`/`\|\|`) | any explicit absolute-path argument OR cwd | any absolute-path arg resolves outside the unified allow-set, OR no abs path + cwd outside both |
| Bash escape | `Bash: ls`/`dir`/`Get-ChildItem`/`gci` (leading token) | any path argument (cwd-relative `..` folded) OR cwd | any argument resolves outside the unified allow-set, OR no path + cwd outside both |
| Bash catch-all (rule m) | **ANY `Bash` command** — every path-like token (drive-letter `C:\…`/`C:/…`, UNC `\\…`, POSIX `/…`, `..`-leading [resolved vs guard cwd], `~/`-leading; bare `~`/`..` NOT tokens; `://` URL tokens excluded) | token resolution | ANY token resolves outside the unified allow-set → exit 2 + recipe naming the three allow-root classes (target tree / sentinel `read_roots[]` / config `read_roots[]`) + the config remedy. **Verb-independent, runs LAST (after all enumeration rules)** — mutation-shaped hits surface their write/delete recipe first; the enumeration tables REMAIN IN FORCE as refinements (write/delete recipes, cwd-drift, P1 root pollution). No path token => pass; unpinned target => degrade |
| Path resolution | `..` chain (e.g. `<target>\aa\bb\cc\..\..\..\..\xxxx` folding to a drive root) | the resolved path | `Path.resolve()` folds `..` segments; a chain that climbs out of the tree resolves outside and is blocked (the reported D-root permission-prompt interrupt shape) |
| Path resolution | hallucinated out-of-tree prefix (an underscore dir name regenerated as a separator pair, e.g. `acme_wing` → `acme\wing`) | the resolved path | resolves outside the tree and is blocked by the same out-of-tree judgment — no directory-name semantics are attempted |

**Residual boundaries (rule m, disclosed — same style as the honest-boundary docs)**: ① an
UNKNOWN write verb writing INTO a declared read-only root passes the net (token inside the
read allow-set; the mutation rules do not recognize the verb) — governed by the sdr
approval-flow change once declared roots are user-approved; ② alias/variable indirection
(`$p='D:\out'; cp x $p`) extracts no bare path token → leaks (same no-shell-parser stance as
every other Bash rule); ③ the interpreter-exec rule (executed script location) keeps judging
`MGH_TARGET` alone — declared roots are read-only, running code from them is not a read.

A hit → exit 2 + stderr **read-side recipe** (points at "read only this batch's `input_path`/
`targets[]`; anchor `Glob`/`Grep` (and `rg`/`grep`/… in Bash) at the repo root; NEVER read
the parent dir / sibling modules"; when roots are declared the recipe adds "declared roots
(sentinel ∪ config) are not a wildcard"). The rule-m recipe instead names the three
allow-root classes + the `<target>/.mgh/read-roots.json` remedy. Regex-over-observed-shape:
pipes/aliases/env-injected paths in the Bash file-search form are NOT guaranteed (same
stance as the temp-I/O and file-association rules). Under the pre-rule-m search/listing
rules a `--flag <path>` value on a non-search verb did NOT trip — the rule-m net NOW judges
every token including flag values (an accepted new block: `--flag=<out-of-tree>` values,
`git -C <out>`, harmless out-of-tree mentions).

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
