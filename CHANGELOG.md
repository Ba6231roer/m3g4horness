# Changelog

All notable changes to **m3g4h⊿rness** are recorded here.
Format based on [Keep a Changelog](https://keepachangelog.com/), versioning follows
[Semantic Versioning](https://semver.org/).

`m3g4h⊿rness` (SAST tool: `/mgh-sast`) is a zero-runtime-dependency reimplementation of the
[vvaharness](https://github.com/visa/vvaharness) (Visa / Project Glasswing) 9-stage
agentic SAST pipeline. Prompt **content** is ported under Apache-2.0 (see
`core/docs/NOTICE`); no `vvaharness` code is imported or bundled.

The `0.x` line denotes initial development: structurally complete, but live
end-to-end verification is still pending (see *Pending* below).

---

## [Unreleased]

### Changed — `/mgh-sast` pins s4 big-file slice outputs in-tree + absolute tool-script paths
- The s4 deep-dive big-file slice output (`chunk_sources.py --out`) — the sast-side fan-out
  gap left open by `harden-mgh-init-slice-and-tool-pinning` (its Non-Goals deferred sast to
  this adoption) — is now pinned to the project tree. `list_chunks.py` stdout `pending[]`
  each gains an additive ABSOLUTE `slice_dir` = `<target>/security-scan/slices/s4/<safe(chunk_id)>/`
  (`<命令输出目录>` = grandparent of `--checkpoints` = `<target>/security-scan`, same root as
  `checkpoint_path`; `_safe_name` sanitizes `/ \ :` — a no-op on clean vvah `chunk-NN` ids,
  defensive parity with init T1's NTFS-ADS guard). The orchestrator passes `slice_dir` verbatim;
  the sast-deepdive subagent writes `chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json`
  and re-reads that exact path — NEVER a relative `--out`, NEVER a cwd/system-temp-derived path
  (opencode subagent cwd can be `…\Temp\opencode\` → out-of-tree slice → unauthorized-`Read`
  prompt), NEVER out-of-tree. `chunk_sources.py` itself stays cwd-agnostic (no tree assumption);
  the pin lives in the contract + prompt layer.
- s4 deep-dive subagents now use the ABSOLUTE tool-script path pinned to the current install:
  `list_chunks.py` stdout gains a top-level `scripts_dir` = `Path(__file__).resolve().parent`
  (the running install's `<mgh-core>/scripts/`); the orchestrator reads it in s4 fan-out and
  passes `<scripts_dir>/chunk_sources.py` verbatim. Subagents NEVER use a bare `chunk_sources.py`
  name or a relative `.claude`/`.opencode/mgh-core/scripts/…` path (multi-layer install → can
  resolve to an older copy). Tool base is taken from `list_chunks.py` (s4 already calls it), not
  init-only `list_steps.py`; install-dir stays independent of `--target`.
- Affected: `core/scripts/list_chunks.py` (additive per-pending `slice_dir` + top-level
  `scripts_dir`); `core/contracts/sast/fanout-enumeration.md` + `core/contracts/init/unit-inputs.md`;
  `core/prompts/stages/s4-system.md` + mirrored `releases/{claude-code/agents,opencode/agent}/
  sast-deepdive.md`; both `mgh-sast.md` shells (s4 fan-out `slice_dir`/`scripts_dir` transmission,
  absolute `chunk_sources` recipe); `install.sh` self-check now also verifies the sast pipeline
  scripts (`list_chunks`/`list_verify_jobs`/`prefilter`/`dedup`/`emit_sarif`) are co-located.
  Additive stdout fields — no on-disk schema change (`checkpoint_path`/`input_path`/exit-code
  semantics unchanged); lite shell omits `slice_dir` (never fans out); zero new runtime deps.

### Changed — `/mgh-init` pins big-file slice outputs in-tree + absolute tool-script paths
- The scout/T1 big-file slice output (`chunk_sources.py --out`) — the one fan-out-adjacent
  path NOT already pinned by `harden-mgh-init-fanout-output-paths` — is now pinned to the
  project tree. `list_scout_batches.py` / `list_clusters.py` stdout `pending[]` each gain an
  additive ABSOLUTE `slice_dir` = `<target>/.mgh-init/slices/<tier>/<safe(unit_id)>/`
  (`<tier>` ∈ `scout`/`t1`; `<init-dir>` = grandparent of `--checkpoints`, same root as
  `checkpoint_path`; `cluster_id` `::` NTFS-ADS-sanitized via the existing `_safe_name`).
  The orchestrator passes `slice_dir` verbatim; the scout/induct subagent writes
  `chunk_sources.py --out <slice_dir>/<safe-stem>.slice.json` and re-reads that exact path —
  NEVER a relative `--out`, NEVER a cwd/system-temp-derived path (opencode subagent cwd can
  be `…\Temp\opencode\` → out-of-tree slice → unauthorized-`Read` prompt), NEVER out-of-tree.
  `chunk_sources.py` itself stays cwd-agnostic (no tree assumption); the pin lives in the
  contract + prompt layer.
- Fan-out subagents now use the ABSOLUTE tool-script path pinned to the current install:
  the orchestrator derives it in step 0 from `list_steps.py` stdout `script_abs` (`__file__`-
  derived = the running install's `<mgh-core>/scripts/`) and passes it verbatim. Subagents
  NEVER use a bare `chunk_sources.py` name or a relative `.opencode`/`.claude/mgh-core/
  scripts/…` path — under a multi-layer install a relative tool path can resolve to a
  DIFFERENT (older) copy. Install-dir stays independent of `--target` (install in A, analyze B).
- Affected: `core/scripts/list_scout_batches.py` + `list_clusters.py` (additive `slice_dir`);
  `core/contracts/init/{scout-enumeration,cluster-enumeration,unit-inputs}.md`;
  `core/prompts/stages/init-{scout,induct}.md` + mirrored `releases/{claude-code/agents,
  opencode/agent}/init-{scout,induct}.md`; both `mgh-init.md` shells (step-0 tool-base recipe,
  fan-out `slice_dir` transmission, `chunk_sources` example → absolute path + `<slice_dir>`
  `--out`). Additive stdout field — no on-disk schema change (`checkpoint_path`/`input_path`/
  exit-code semantics unchanged); zero new runtime deps. mgh-sast's s4/deepdive same-shape gap
  is deferred to a follow-up `harden-mgh-sast-slice-path-pinning`.

### Changed — `/mgh-init` skips test source trees during discovery (`--include-tests` opt-in)
- The discovery file-enumeration layer (`expand_scope.walk_sources` / `collect_dir`, the
  single chokepoint consumed by regex candidates, `skeleton.json`, the call graph, and scout
  targets) **additionally** prunes test source trees by default, mirroring the existing
  dot-prefix prune. A test tree hits when the repo-relative posix path starts with
  `src/test/` / `src/tests/` (Maven/Gradle/Kotlin) **or** a directory segment (not filename)
  is in `{tests, __tests__, __mocks__, spec, specs}`. Bare singular `test` is **deliberately
  not** matched (collision risk: production `com/acme/test/` helper packages, Go `test`
  packages). Test code is net noise for finding existing **production** controls — mocks/stubs
  (`@MockBean SecurityConfig`, `mock(SecurityChecker)`) materialize pseudo-controls,
  deliberately-vulnerable fixtures (VulnerableApp, disabled-TLS / widened-CORS / placeholder-
  key / dummy-JWT-issuer test configs) hit as real control features, and test code never ships.
- `discover_controls.py` gains `--include-tests` (default off = exclude; passing it re-includes
  test sources, equivalent to before this change). Polarity asymmetry (design D2): the shared
  `walk_sources`/`collect_dir` default `include_tests=True`, so callers that don't pass it —
  including `mgh-sast`'s `build_call_graph` — stay byte-identical; only `discover_controls`
  (mgh-init) opts into exclusion. Excluding test code as an mgh-sast default is a separate
  later change (not bundled here).
- discover stdout summary (partial + full) gains `tests_skipped` (non-negative int), parallel
  to `dotfiles_skipped`; `controls_candidates.json` wrapper gains an additive top-level
  `tests_skipped` so `discover_controls.py --check` can validate it (R5.9: fail-loud exit 2 if
  missing/non-int/negative). `write_runconfig.py` records `include_tests` in `run_config.json`
  for stateless `--resume`. Both `mgh-init.md` shells (claude + opencode, mirrored verbatim)
  gain the flag-table row, the `write_runconfig`/`discover_controls` call examples, and a test-
  tree honesty-boundary line in `init_manifest.json::boundaries[]` / `report.md`. No disk
  schema change to `controls_candidates`/`clusters`/`skeleton` Candidate records (only an
  additive wrapper counter); no LLM-stage prompt change (prune is at the deterministic layer).

### Changed — `/mgh-init` tolerates partial fan-out unit failure (`.failed` terminal marker)
- A confirmed fan-out unit failure (scout reader batch / T1 cluster / T3 category subagent
  returning the existing `failed <reason>` ack) is now **terminal and non-blocking**: the
  orchestrator writes a `.failed` marker sibling to `.done` (`<checkpoint_path>.failed`, body
  `{unit,reason,tier}`), the unit is excluded from resume `pending` (NOT retried), and the tier
  completes when `done + failed >= total` (not `done >= total`). `list_clusters.py` /
  `list_scout_batches.py` / `list_rule_jobs.py` emit a `failed` count + a per-item absolute
  `failed_marker` (parallel to `done_marker`, verbatim-transmitted — never self-assembled);
  `resume_state.py` derives `tiers{<tier>}.failed`, surfaces non-zero failures in `notes[]`
  (a rate > half the tier is a loud `WARNING` advisory, never a gate), and `--check` flags a
  unit carrying both `.done` and `.failed` as an ambiguous-terminal violation (exit 2).
  Failures are disclosed in `init_manifest.json::failures` (per-tier `{done,failed,total}`) +
  `boundaries[]` + `report.md`, counts read from disk (`resume_state`/`list_*` stdout), never
  conversation memory. A crash without an ack leaves no marker → unit stays pending → retried
  (crash ≠ confirmed failure); escape hatch = delete the `.failed` marker then `--resume`.
  No new CLI flag (R5.1 surface frozen; `.failed` read by glob, written via `Write` to the
  verbatim `failed_marker` path). Stage prompts + dual-shell agent defs updated to "touch
  nothing on failure, emit only the `failed` ack". Original (no `.done` ⇒ tier never completes
  ⇒ pipeline blocks, or indiscriminate retry) is the failure-shape being fixed.

### Changed — `/mgh-init` fan-out waves run to completion (no scale-driven mid-run interruption)
- Both `mgh-init.md` shells (claude + opencode, mirrored verbatim) gain a run-to-completion
  directive in the Re-entrancy & compaction section: during a fan-out wave (scout reader /
  T1 induct / T3 rulewriter) the orchestrator **MUST NOT** pause to ask the user whether to
  split / skip / abort on account of scale, and **SHALL** iterate the `list_*` pending
  work-list at `max_concurrent` until `pending` is empty. Scale and boundary facts (large
  fan-out count, partial coverage, `.failed`/skipped units, residual blind spots) **SHALL**
  flow into the existing disclosure channel — `init_manifest.json::boundaries[]` + `report.md`
  + `resume_state.py` `notes[]` — never as a mid-run blocking question; counts are read from
  disk (`resume_state.py`/`list_*` stdout), never conversation memory. The legitimate
  **pre-run** i0 advisory (`--large-repo-threshold` → suggest `--scope`+`--merge`, before
  tokens are spent) is explicitly preserved and distinguished from the mid-wave directive.
  Prompt-wording only: no new CLI flag, script, contract, hook, or stage-prompt change.

### Changed — runtime hook enforcement hardened (env-or-sentinel activation + runtime scripts read-only + init write confinement)
- **Disk-sentinel activation closes the opencode reliability boundary.** The shared guard
  `block_adhoc_scripts.py` now activates inside an mgh run-domain when **EITHER** env
  `MGH_{INIT,SAST,SRA,SRR}_ACTIVE=1` **OR** a disk sentinel `<cwd>/<run-root>/.active` exists
  (init→`.mgh-init`, sast→`security-scan`, sra→`.mgh-sra`, srr→`.mgh-srr`). The opencode `.ts`
  plugin process does not inherit mid-session bash-exported env, so env-only activation left the
  opencode guard dormant for a whole run; the sentinel (visible to the plugin via disk) closes
  that hole. Sentinel JSON `{domain,target,out_roots[],v}`, written by the orchestrator at step 0
  via Bash, removed on completion/clean-stop. New contract `core/contracts/hooks/runtime-enforcement.md`;
  new shared spec `runtime-hook-enforcement` (single source replacing scattered per-command hook wording).
- **Runtime scripts read-only (whitelist removed + script-extension set).** When active the guard
  blocks `Write`/`Edit` of any extension in `{.py,.ps1,.sh,.bash,.zsh,.bat,.cmd,.ts,.js,.mjs,.cjs}`
  with **no** path whitelist — the prior `core/scripts`/`mgh-core/scripts` + `tests`/`tools`/`hooks`
  exemptions only mattered while inactive (install/dev), at which point `main()` already exits 0.
  Leaf scripts are read-only for the orchestrator at runtime. Closes the "agent edits
  `list_clusters.py`" and "`process_*.ps1` leaks past `.py`-only" failure shapes.
- **`/mgh-init` write confinement to sanctioned subtrees.** The init domain upgrades
  out-of-tree interception to a positive allowlist: `Write`/`Edit` MUST land in
  `<target>/.mgh-init/**` / `.claude/rules/**` / `docs/security-controls/**` / `AGENTS.md` /
  sentinel `out_roots[]` — so in-tree root pollution (`temp_clusters*.json`, `process_*.ps1`) also
  fails loud. sast/sra/srr retain the out-of-tree check. `MGH_TARGET` precedence: env > sentinel.target
  > degrade. Sentinel `target` is sourced from Python leaf-script stdout (Windows-native; never bash
  `pwd`, whose MSYS `/c/…` mis-resolves in pathlib).
- **Tests:** `test_block_adhoc_scripts.py` flips the whitelist PASS tests to BLOCK, adds sentinel
  activation (env unset), sentinel-carried-target subtree block, script-ext set, init root-pollution
  block + sanctioned-subtree/out_roots pass, stale/degrade; `test_opencode_hook_parity.py` adds
  byte-identity-of-new-logic + opencode sentinel-activation checks. The `.ts` shim stays glue-only.

### Added — `/mgh-init` context resilience (re-entrant resume + bounded ack + aggregate hard-budget)
- **Re-entrant orchestrator resume state.** New `core/scripts/resume_state.py` derives the
  pipeline's current step + exact next action **purely from on-disk artifacts** (`<target>/.mgh-init/`
  products + per-tier `.done` + `run_config.json`), independent of conversation memory. compact /
  crash / new-session collapse into one recovery path: `/mgh-init --resume` whose **first action is
  `resume_state.py`**. `--check` validates on-disk self-consistency (exit 2 on violation). New
  `core/scripts/write_runconfig.py` atomically writes the start-state intent `run_config.json` at
  step 0 so resume is stateless of re-typed flags. See `core/contracts/init/resume-state.md`.
- **Bounded subagent return-to-orchestrator ack.** All 9 `init-*.md` stage prompts + dual-shell
  `agents/init-*.md` declare the final message as a single bounded ack (`ok <abs path> <count>` /
  `oversize` / `failed`) — NEVER echo the record body (which monotonically bloated orchestrator
  context across fan-out). The 5 whole-tier stages (survey/scout-merge/scout-audit/synthesis/
  rules-consistency) also moved to orchestrator-given absolute-path-verbatim output.
- **Aggregate hard-budget via map-reduce.** New `core/scripts/plan_aggregate.py` makes
  `--max-aggregate-bytes` a HARD gate at T2 (`init-synthesis`) and scout-merge (`init-scout-merge`):
  ≤ budget → single-context (byte-identical, zero regression); > budget → two-pass map-reduce
  (per-shard ≤ budget → single rollup over summaries). Replaces the prior "disclose + fallback"
  soft boundary for those two nodes (T4 rules-consistency remains soft-bounded). See
  `core/contracts/init/aggregate-sharding.md`.
- **Re-entrancy & compaction section** in both `mgh-init.md` shells: disk is the progress source of
  truth, conversation memory is only a cache; resume/compact first action is `resume_state.py`;
  context-tight clean-stop + new-session resume is preferred over manual `/compact`.
- `AGENTS.md` R5.4 / R5.5① sharpened (orchestrator-level re-entrant resume state + step-query
  recipe). `init_manifest.json` version bumped 6 → 7; `boundaries[]` reflects the hard-threshold.

### Changed
- **Restructured `AGENTS.md` R5(Agent 工具命令稳定性)for readability — 零规范内容删除。**
  跨处复述的机制去重到单一归宿(长跑可恢复 → R5.4;opencode env 不继承 → R5.7 段 B;退出码 `0/1/2`
  定义 → R5.3(b) 单次);R5.7 拆「段 A 评估方法论 + 段 B hook 强制闭环」;R5.3(b) fan-out 提升为子项;
  修 R5.5 ⑤ 孤儿 indent;合并重复的「理由须随规保留」样板为前言一行;修剪纯回声 `承 R5.x`。加 R5 头部
  「强制面索引表」。编号 R5.1–R5.10 不变。详见 change `simplify-agents-r5`。

### Added
- **Bounded per-request context for `/mgh-sra` fan-out (`request-context-budget` adoption).**
  `prepare_augment.py` now materializes each capability's complete input to its own bounded file
  and the orchestrator carries only a slim, paged work-list (it no longer whole-reads
  `change_context.json` into its context). New on `prepare_augment.py`: `--materialize <dir>`
  (writes `<change-root>/.mgh-sra/inputs/augment/<cap>.input.json` = that cap's requirements +
  per-cap business surface + the `candidate_controls` file_overlap slice + memory; `pending[]`
  becomes a slim envelope carrying `input_path`/`bytes`/`oversize`), `--offset`/`--limit` paging
  reporting `effective_limit`/`shrunk`, and `--max-unit-bytes` (192 KB; an oversize capability is
  flagged + recipe'd to split the change / `--focus` narrow — never sharded, the capability is the
  a3 atom) / `--orch-budget-bytes` (64 KB; a page over it is auto-tightened). `sra-augment` reads
  its own `input_path` (NEVER the whole `change_context.json`); the full `change_context.json`
  stays on disk for the a2 single-context whole-change scan. `sra-clarify`/`sra-consistency` gain a
  P0 soft-boundary disclosure guardrail for their aggregate inputs (`--max-aggregate-bytes`,
  256 KB — over it they advise `--focus`/split-change and surface it in
  `sra_manifest.json::boundaries[]`, non-blocking). `tools/check_contracts.py` asserts the new
  flags (R5.1); tests cover per-cap materialize (file_overlap slice)/paging/oversize + the
  whole-read discipline regression. (This lands the engine-stage `input_path` consumption the srr
  adoption deferred; the cross-cutting `request-context-budget` spec is the contract.)
- **Bounded per-request context for `/mgh-srr` fan-out (`request-context-budget` adoption).**
  The srr intake adapter now materializes each review unit's complete input to its own bounded
  file and the orchestrator carries only a slim, paged work-list (it no longer whole-reads the
  sra-shape `change_context.json` into its context). New on `ingest_requirements.py`:
  `--materialize <dir>` (writes `<out>/inputs/augment/<unit>.input.json`; `pending[]` becomes a
  slim envelope carrying `input_path`/`bytes`/`oversize`), `--offset`/`--limit` paging reporting
  `effective_limit`/`shrunk`, and `--max-unit-bytes` (192 KB; an oversize unit is flagged +
  recipe'd to `--split`/narrow the doc — never sharded, the unit is the review atom) /
  `--orch-budget-bytes` (64 KB; a page over it is auto-tightened). The reused sra engine stage
  reads its own `input_path`; the full sra-shape `change_context.json` stays on disk for stage
  consumers. `render_report.py` gains `--max-aggregate-bytes` (256 KB; P0 soft boundary — over
  it the aggregate draft input is disclosed in `srr_manifest.json::boundaries[]` + the report,
  non-blocking). `tools/check_contracts.py` asserts the new flags (R5.1); tests cover
  materialize/page/`--split`/oversize + the whole-read discipline regression. (Engine-stage
  consumption of `input_path` lands with the `/mgh-sra` adoption; intake-side lands independently.)
- **Bounded per-request context for `/mgh-sast` fan-out (`request-context-budget` adoption).**
  The s4/s6 enumeration scripts now materialize each fan-out unit's complete input to its own
  bounded file and the orchestrator carries only a slim, paged work-list (it no longer
  whole-reads `s3_chunks.json`/`s5_filtered.json` into its context). New on `list_chunks.py`:
  `--materialize <dir>` (writes `<repo>/security-scan/inputs/s4/<chunk>.input.json` = that chunk's
  `files[]` + `threat_id` + `hypothesis` + `needs_slice`; `pending[]` becomes a slim envelope
  carrying `input_path`/`bytes`/`oversize`/`needs_slice`), `--offset`/`--limit` paging reporting
  `effective_limit`/`shrunk`, `--max-unit-bytes` (192 KB; an oversize chunk — input over budget OR
  a source file over `--big-file-bytes` — is flagged + its big files listed in `needs_slice[]` for
  `chunk_sources` slicing, never the whole file fed to the LLM) / `--orch-budget-bytes` (64 KB; a
  page over it is auto-tightened), plus `--repo`/`--big-file-bytes` (200 KB) for computing
  `needs_slice`. `list_verify_jobs.py` mirrors this for s6 (`inputs/s6/<finding_id>.input.json` =
  the full finding record; an oversize finding is flagged + recipe'd to `--scope` narrow — never
  sliced, the finding is the s6 verify atom). `sast-deepdive`/`sast-verify` read their own
  `input_path` (NEVER the whole `s3_chunks.json`/`s5_filtered.json`). `mgh-sast.md` (claude +
  opencode) gains the orchestrator-discipline recipe, the s4/s6 materialize→page→pass-`input_path`
  flow, the `--max-unit-bytes`/`--orch-budget-bytes`/`--max-aggregate-bytes` flag table (s1 scope /
  s2-s3 hypothesis aggregate = P0 soft boundary — over it advise `--scope`/`--diff` and surface in
  `run_manifest.json::boundaries[]` + `report.md`, non-blocking), and the `inputs/` output.
  `tools/check_contracts.py` asserts the new flags (R5.1); tests cover per-chunk/per-finding
  materialize (needs_slice/oversize)/paging + the s3/s5 whole-read discipline regression. (The
  cross-cutting `request-context-budget` spec is the contract; the `block_adhoc_scripts` hook
  already covered `MGH_SAST_ACTIVE` from the foundation — no hook change.)
- **`docs/r5-plain-language.md`**(dev-only,不分发)—— R5.1–R5.10 大白话逐条(说什么 / 为什么 /
  违反后果 / 兜底),作 AGENTS.md(AI 面向)的人类桥梁 + 去重后防单点灭失的第二副本。

### Fixed
- **`/mgh-init` scout→merge fold-in aborted with `KeyError: "file"` when a scout candidate
  lacked its `file` field** (raw traceback, the whole merge halted) — unlike `category`, which
  `merge_scout._normalize` already tolerated (skip + warn). `file` is now treated the same as
  `category`: a missing/empty `category` OR `file` makes `_normalize` return `None`, the caller
  skips that one candidate and warns (naming which required field is missing — `category` /
  `file` / both, plus the candidate `index` and any available `file:line`), and the merge
  continues. All `_normalize` field access is now `.get` (no direct-indexed required field
  remains). Defense-in-depth for when `merge_scout.py --check` is bypassed (orchestrator
  context pressure / a hand-crafted malformed `scout_candidates.json`); the `--check` gate,
  stdout/stderr/exit-code CLI contract are unchanged. Covered by `tests/test_merge_scout.py`.
- **`/mgh-init` T1 subagent `write_text` of `checkpoint_path` failed with `OSError [Errno 22]
  Invalid argument` on Windows NTFS** when `cluster_id` (or `<cid>::shard-<n>`) contained `::`
  — NTFS's Alternate-Data-Stream separator. `list_clusters.py::_paths` built the checkpoint
  filename from the **raw** `unit_id`, unlike the input filename which was already
  `_safe_name`-sanitized (`/ \ :` → `_`) — a same-source latent bug (the test helper `_mark_done`
  already sanitized, diverging from production). `_paths` now encodes the filename component via
  `_safe_name` (same function, same paradigm as `_write_unit`/`_shard_hit_count`); the canonical
  `unit_id` (with `::`) is preserved verbatim as the slim-envelope `cluster_id` field and the
  checkpoint record's `unit` field, so done detection / resume matching (which reads `unit`, not
  the filename) are unaffected. See `core/contracts/init/cluster-enumeration.md`,
  `openspec/changes/fix-mgh-init-ntfs-unit-filename/`. Covered by `tests/test_init_clusters.py`.

### Dev-meta
- **Q1 决策:**AGENTS.md 改动**不**触发分发版本 bump —— AGENTS.md 是研发手册,在 install 分发集之外
  (`SCAN_DIRS` 排除;无 VERSION 字段,版本追踪仅 CHANGELOG)。记于此,不作为 release 切出。
- **行数实际:**R5 段 97 → ~114 行(未达 design 估的 70–75)。强制面索引表(~13 行)抵消了去重收益;
  真实收益是可读性(去重 + 拆段 + 索引 + 修孤儿),非行数。

## [0.1.12] — 2026-07-27

### Added
- **Bounded per-request context for `/mgh-init` fan-out (`request-context-budget`).** The
  orchestrator no longer whole-reads a multi-unit aggregate into its context (observed: an
  opencode host reading the 426 KB `t1_pending`-style work-list whole, bloating every
  subsequent model request). Every fan-out tier now materializes each unit's complete input
  to its own bounded file and the orchestrator carries only a slim, paged work-list. New
  three-tier byte budgets (defaults; unit = bytes, a conservative upper bound for tokens):
  - **Per-unit materialization** — `list_clusters` / `list_scout_batches` / `list_rule_jobs`
    gain `--materialize <dir>`: each T1 cluster / scout batch / T3 category's complete input
    record is written to `<target>/.mgh-init/inputs/<tier>/<unit>.input.json` (idempotent,
    `--resume`-reused). `pending[]` becomes a slim envelope carrying `input_path` / `bytes` /
    `oversize` (no variable-length payload). The stage subagent (`init-induct` / `init-scout`
    / `init-rulewriter`) reads its own `input_path`; the orchestrator only passes the path.
  - **Configurable byte budgets** — `--max-unit-bytes` (192 KB; oversize clusters sharded
    into `<cluster_id>::shard-<n>`, scout batches / T3 categories flagged `oversize`),
    `--orch-budget-bytes` (64 KB; a work-list page exceeding it is auto-tightened with
    `shrunk:true`), `--max-aggregate-bytes` (256 KB; T2/merge/T4 aggregate stages — P0 soft
    boundary: disclose + advise `--scope`/`--merge`; layered reduction is a later change).
  - **Paging** — all three enumeration scripts gain `--offset` / `--limit` and report
    `effective_limit` / `shrunk`; the orchestrator pages rather than loading the whole list.
  - **Defense-in-depth hook** — `block-adhoc-scripts` (both platform twins, byte-identical;
    the opencode `.ts` shim stays pure glue) now also blocks a shell whole-read
    (`cat`/`head`/`tail`) of a multi-unit aggregate in any of the four run-domains, with a
    recipe pointing at `list_* --materialize` `input_path`. The structural fix is the primary
    lever; the hook is residual defense. (`/mgh-sast` / `/mgh-sra` / `/mgh-srr` adoption is
    deferred to follow-up changes — this release lays the cross-cutting capability and the
  `init` reference implementation.)
- **New contract** `core/contracts/init/unit-inputs.md` documenting the per-unit
  materialization schema and the four-command path conventions.
- **`init_manifest.json` version 5 → 6** (additive): `boundaries[]` gains the request-context-
  budget disclosure.

### Changed
- `init-induct` / `init-scout` / `init-rulewriter` prompts: input is now the bounded
  `input_path` file (with a NEVER-whole-read-aggregate hard rule). `init-synthesis` /
  `init-scout-merge` / `init-rules-consistency` gain a P0 aggregate-context-budget guard.
- `tools/check_contracts.py` asserts the three `list_*` scripts declare the new flags and
  the `/mgh-init` shells advertise `--max-aggregate-bytes`.

## [0.1.11] — 2026-07-23

### Added
- **Discover resilience against host shell timeouts (`/mgh-init`).** `discover_controls.py`
  no longer assumes a single host call finishes — it checkpoints a built call graph under
  `<out>/cache/` and resumes across runs, so a large repo (or an opencode/claude shell
  timeout mid-scan) is no longer total loss. New flags (all additive; defaults preserve
  prior behavior):
  - **Call-graph cache** — `<out>/cache/callgraph.json` + `manifest.json` (per-source
    `mtime`/`size` freshness). A re-run with an unchanged repo hits the cache and skips
    the two regex passes (stdout `cache_hit: true`). `--rebuild-cache` forces a rebuild
    (this flag was already advertised in the shells but was previously a dangling
    contract — it is now real and `--help`-exposed).
  - **Scan resume** — `<out>/cache/scan_progress.json` checkpoints every
    `--progress-every` files. `--resume` reuses the cache and continues scanning from the
    checkpoint without rescanning; deterministic + idempotent (resume == one-shot candidate set).
  - **Soft time budget** — `--time-budget-ms <N>` (default `0` = off). When set, discover
    stops at a safe boundary (after the call graph is built; every `--progress-every`
    files — never mid-write), persists the cache + checkpoint, and exits **0** with stdout
    `partial: true` + `resume_hint`. The orchestrator re-dispatches `--resume` until
    `partial: false`.
  - **Atomic writes** — all product JSON (`controls_candidates`/`clusters`/`skeleton`/
    `cache/*`) is written `.tmp` + `os.replace`, so a SIGKILL mid-write leaves no truncated
    artifact (`--check` never sees a broken file).
- **Per-call `timeout` recipe across all four command shells.** The `mgh-init`/`mgh-sast`/
  `mgh-sra`/`mgh-srr` orchestrators (claude + opencode) now instruct the host to pass a
  generous per-call `timeout` to long-running deterministic Bash calls, and disclose the
  opencode global `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` (default 120000; must be
  ready before opencode launches — mid-session `export` is not inherited). `mgh-init` also
  adds the `partial: true` → Bash re-dispatch `--resume` loop (never a wrapper `.py`).

### Changed
- `discover_controls.py`: the materialized source list is sorted by repo-relative path so
  the scan checkpoint index is reproducible across runs; `scan()` keeps its 6-tuple API (a
  new `run_discover()` carries the cache/resume/budget knobs). `main()` skips writing final
  products on a partial exit (only `cache/` + `scan_progress.json` land). All additive — no
  final-product schema change; `--time-budget-ms 0` and a missing cache are byte-equivalent
  to before.
- `AGENTS.md` R5.3(c) (deterministic-script recoverability) + R5.4 (per-call timeout +
  discover soft-budget re-dispatch) sharpened; `README.md` gained a host-shell-timeout
  section; new contract `core/contracts/init/discover-cache.md`; `core/contracts/init/
  candidates.md` stdout summary extended with `partial`/`resume_hint`/`cache_hit`.

### Verified
- `tests/test_discover_resilience.py` (14 tests): cache hit + equivalence, mtime/size
  invalidation, `--rebuild-cache`, midpoint-resume equivalence + idempotency, checkpoint
  preservation when the budget trips at the callgraph boundary (regression), clean partial
  exit (exit 0, no truncated product), atomic writes, `--check` after a run. Plus a
  synthetic 150-file repo converging via repeated `--resume` to the one-shot candidate set.
- Full suite green (426 tests); `tools/check_contracts.py` (now asserts the discover flags
  in `--help`) and `tools/check_distributed_purity.py` both clean; zero-runtime-dep AST scan
  clean (`os`/`time` are stdlib).

## [0.1.10] — 2026-07-20

### Added
- **Sensitive-data catalog (`--sensitive-catalog`) for `/mgh-sra` + `/mgh-srr`.** Both commands now
  accept `--sensitive-catalog <inline-json|@path|->` to declare a **company masking policy** — the
  field types that MUST be masked, each with a `mask` level (`full` / `partial`) and a rule (e.g.
  "保留后 4 位"). This extends sensitive-data recognition **beyond the legacy 6 facets**
  (id-card / bank-card / phone / email / password / token) and drives **per-item masking-gap
  detection**: for each catalog field type, the reused a2/a3 subagents check whether it is masked
  per its rule at-rest / in-transit / log / response. The default is unchanged: omit the flag =
  legacy 6 facets only (byte-equivalent behavior, a hard backward-compatibility gate). The catalog
  is **orthogonal to `--focus`** (focus narrows *which dimensions*; the catalog declares *what must
  be masked*) and the two may be passed together.
  - **New deterministic script `core/scripts/sensitive_catalog.py`** — the closed-set single source
    of truth for the 10 PIPL / GB-T 35273 categories (identity-doc / biometric / health / financial
    / location / communication / device / vehicle / general-pii / legal) and the `{full, partial}`
    mask enum; ships a **37-item default template**. CLI: `--list` / `--parse` / `--check`. Closed-set
    violations (unknown category, illegal mask, malformed `<category>/<field-type>` key, missing
    label, non-int `version`) exit **2** with an actionable message; malformed JSON / missing file
    / unreadable stdin exit **1**. Renders a **deterministic** Simplified-Chinese policy directive
    (registry order, not input order). Zero runtime deps (stdlib only), self-locating sibling
    import; stdin read as UTF-8 on any console.
  - **`prepare_augment.py` + `ingest_requirements.py`** parse + closed-set-validate
    `--sensitive-catalog` in the deterministic a1/r1 stage (before any LLM token) via the shared
    `sensitive_catalog` module, and embed the resolved `sensitive_catalog`
    (`{version, source, categories[], items[], counts{}, directive}` or `null`) as a new top-level
    `change_context.json` field. Their `--check` validates the field shape (null allowed).
  - **Shared prompt overlay** in `sra-clarify.md` + `sra-augment.md`: when the orchestrator passes a
    non-null `sensitive_catalog`, the subagents expand the sensitive-data pass to per-item masking
    gaps (anchored to a concrete requirement/endpoint/field, tagged `catalog_key`), and link a gap
    to a `data-masking` control via the existing three-signal matching (advisory — a gap is never
    dropped for lack of a matching control). `/mgh-srr` reuses these prompts verbatim → obtains the
    behavior with **zero new prompts**.
  - **mgh-init linkage (consumption only)**: catalog-driven masking gaps reuse the existing
    `data-masking → sensitive-data` dimension mapping already in `prepare_augment.py`; **no change
    to mgh-init** discovery / inventory schema / rules.
  - **Disclosure**: the orchestrator-written `sra_manifest.json` and `render_report.py`'s
    `srr_manifest.json` carry a `sensitive_catalog` field (`counts` + `source`, or null); when a
    catalog is active, a boundary line states **masking gaps were checked per the company catalog
    items; field types outside the catalog were recognized only via the legacy 6 facets**, and the
    srr report header notes the catalog coverage.
  - **Shipped `.example` template**: a committed `core/scripts/sensitive_catalog.json.example`
    (the 37-item PIPL/GB-T 35273 template) is the canonical artifact; `install.sh` copies it to
    `.mgh-sra/sensitive_catalog.json.example` in the target project. It is **not auto-applied** —
    the company must `cp` it to `sensitive_catalog.json` or pass `--sensitive-catalog @<path>` to
    activate (backward-compat gate).
  - New contract `core/contracts/sensitive-catalog.md`; `core/contracts/sra/augmentation.md` +
    `srr/intake-report.md` document the new field; `security-dimensions.md` notes the catalog as the
    6-facet extension point.
  - New tests: `tests/test_sensitive_catalog.py` (registry / parse / closed-set violations / exit
    codes / determinism / input forms incl. stdin / anti-drift: 37-items + committed `.example`
    matches `DEFAULT_TEMPLATE` / zero-deps AST); `--sensitive-catalog` + `--check` coverage added
    to `test_sra_prepare.py`, `test_srr_ingest.py`; `test_zero_deps.py` asserts
    `sensitive_catalog.py` is scanned.

### Changed
- Four command shells (claude/opencode × sra/srr): `--sensitive-catalog` in the param/flag tables,
  orchestration flow (read `change_context.sensitive_catalog`, pass verbatim into a2/a3), bash
  examples, and an "Always disclose" catalog-coverage line. `tools/check_contracts.py` asserts the
  new flags; `tools/check_distributed_purity.py` confirms the shipped md stay clean (R5.10).

### Known limitation (honest boundary)
- Per-item masking-gap detection is enforced by a **prompt overlay** (non-deterministic guardrail),
  not a hard filter — the closed-set category/mask validation, the `change_context` embedding, and
  the `--check` layers are deterministic, but which catalog items actually surface a gap depends on
  the LLM pass. The catalog is **not** an exhaustive sensitive-field list (out-of-catalog fields use
  only the 6 facets); this is disclosed in the manifest/report boundary.

---

## [0.1.9] — 2026-07-16

### Added
- **Dimension focus (`--focus`) for `/mgh-sra` + `/mgh-srr`.** Both commands now accept
  `--focus <inline-json|path>` to **narrow** the per-dimension security scan to a subset of
  the 9 dimensions, and — for the two dimensions whose catalog enumerates discrete
  sub-categories — to a per-dimension facet whitelist. The default is unchanged: omit the
  flag = scan all 9 dimensions (byte-equivalent behavior, a hard backward-compatibility
  gate).
  - **New deterministic script `core/scripts/focus_scope.py`** — the closed-set single
    source of truth for the 9 dimension keys + the `sensitive-data` (id-card / bank-card /
    phone / email / password / token) and `injection` (sqli / xss / command-injection /
    path-traversal / ssrf / deserialization / xxe) facets; the other 7 dimensions have no
    facets (whole-dimension focus). CLI: `--list` / `--parse` / `--render` / `--check`.
    Closed-set violations (unknown dimension/facet, facet on a facet-less dimension, facet
    for a dimension not in `dimensions`, empty `dimensions`) exit **2** with an actionable
    message; malformed JSON / missing file exit **1**. Renders a **deterministic**
    Simplified-Chinese directive (registry order, not input order; byte-identical across
    runs); all-9 resolves to `null` (no narrowing). Zero runtime deps (stdlib only),
    self-locating sibling import.
  - **`prepare_augment.py` + `ingest_requirements.py`** parse + closed-set-validate
    `--focus` in the deterministic a1/r1 stage (before any LLM token) via the shared
    `focus_scope` module, and embed the resolved `focus` (`{dimensions[], facets{},
    directive}` or `null`) as a new top-level `change_context.json` field. Their `--check`
    validates the `focus` field shape (polymorphic in sra: inventory OR change_context).
  - **Shared prompt overlay** in `sra-clarify.md` + `sra-augment.md`: when the orchestrator
    passes a non-null `focus.directive`, both subagents restrict their per-dimension pass
    to the listed dimensions/facets and emit nothing out-of-scope; in-scope anchoring /
    three-signal / codegraph rules are unchanged. `/mgh-srr` reuses these prompts verbatim
    → obtains the behavior with **zero new prompts**.
  - **Disclosure**: the orchestrator-written `sra_manifest.json` and `render_report.py`'s
    `srr_manifest.json` carry a `focus` field (dimension list or null); when focused, a
    boundary line states **only the focused dimensions were scanned; out-of-scope
    dimensions were not covered**, and the srr report header notes the in-scope dimensions.
  - **Catalog annotated**: `security-dimensions.md` now tags the facet keys inline on the
    `sensitive-data` / `injection` rows, in lockstep with the registry (anti-drift asserted
    by `test_focus_scope.py`).
- New tests: `tests/test_focus_scope.py` (registry / parse / closed-set violations / exit
  codes / determinism / input forms / anti-drift); `--focus` + `--check` coverage added to
  `test_sra_prepare.py`, `test_srr_ingest.py`, `test_srr_report.py`.

### Changed
- Four command shells (claude/opencode × sra/srr): `--focus` in the param/flag tables,
  orchestration flow (read `change_context.focus.directive`, pass verbatim into a2/a3),
  bash examples, and an "Always disclose" focus-scope line. `tools/check_contracts.py`
  asserts the new flags; `tests/test_zero_deps.py` asserts `focus_scope.py` is scanned.

### Known limitation (honest boundary)
- The narrowing is enforced by a **prompt overlay** (non-deterministic guardrail), not a
  hard filter — a focused run could in principle still emit a range-adjacent gap. Residual
  non-determinism is disclosed the same way as the existing prompt-guardrail boundaries;
  the closed-set / embedding / `--check` layers are deterministic. Focusing too narrowly
  can miss real gaps — this is the user's explicit choice, disclosed in the manifest/report.

---

## [0.1.8] — 2026-07-15

### Added
- **`/mgh-srr` — freeform-text security requirements review (no openspec needed).** A new command
  for the common case where requirements arrive as raw text (word/txt/md/excel or pasted) with no
  openspec structure — and possibly no concrete interfaces/fields at all. It is a **port-adapter
  over the `/mgh-sra` middle engine**: a deterministic input adapter (`ingest_requirements.py`)
  extracts the doc into an sra-shape `change_context.json`, the existing sra engine (sra-clarify /
  sra-augment / sra-consistency + 9 dimensions + three-signal control reuse + batched clarification
  + project memory) is **reused verbatim with zero new prompts**, and a deterministic output adapter
  (`render_report.py`) renders a plain, brief Simplified-Chinese `security_review_report.md` +
  `srr_manifest.json` that **never touches openspec/**.
  - **Mixed three-tier input**: `.txt/.md/.csv/.json` read natively (perfect); `.docx`/`.xlsx`
    best-effort via stdlib `zipfile` + `xml.etree` (joining all `<w:t>` within each `<w:p>` so text
    never token-fragments) with **explicit degradation flags** (dates-as-serial / list-markers /
    embedded-objects / merged-cells); a permanent `--text` / stdin **passthrough** escape hatch
    (zero degradation). Unsupported formats (`.doc`/`.xls`/scanned PDF/encrypted) exit 2 with a
    conversion recipe and emit no partial artifact.
  - Interfaces / fields / roles are **optional, non-load-bearing hints** (freeform text may have
    none); the LLM reads the full text and anchors gaps to section headings. Default = one review
    unit; `--split` fans out per markdown `#`/`##` heading (script-enumerated fan-out).
  - **Shares** `<project>/.mgh-sra/business_context.json` with `/mgh-sra` (one accumulating file
    across both tools; same schema, contract unchanged). Optional codegraph enrichment is inherited
    from the reused sra engine (`--no-codegraph` opts out, reproducing pre-codegraph behavior).
  - **Runtime discipline**: a new `MGH_SRR_ACTIVE` run-domain on the **unchanged**
    `block-adhoc-scripts` guard (claude PreToolUse + opencode `.ts` plugin, byte-identical twin),
    covering the review dir + shared project memory under `MGH_TARGET`. Same fail-soft reliability
    boundary on opencode as the other domains.
- Zero new runtime dependencies (R2): `.docx`/`.xlsx` use only the Python standard library. SRR
  reuses all sra stage prompts + fragments + `merge_memory.py` (no duplication — asserted by the
  new `test_mgh_srr_codegraph_parity.py` reuse-not-duplication tests).

### Known limitation (honest boundary)
- `/mgh-srr` input extraction is best-effort for `.docx`/`.xlsx` (dates / formats / list markers
  degraded — flagged in the report); review coverage is bounded by input completeness, so a vague
  requirement document yields only sparse, anchor-light gaps. The `--text`/stdin passthrough has no
  degradation. All other sra boundaries (LLM candidates need human review; controls asserted to
  exist not to be effective; memory is user-asserted; codegraph is optional advisory) apply unchanged.

---

## [0.1.7] — 2026-07-15

### Added
- **Optional codegraph enrichment for `/mgh-init` and `/mgh-sra` (coordinated pair).**
  When the target project has a precomputed codegraph index (`<target>/.codegraph/`)
  **and** the `codegraph` tool on PATH, both commands use it as an optional,
  detection-gated enrichment backend consumed entirely in the **LLM layer** — never
  `import`ed by any `.py`, so zero new runtime dependencies (R2) and zero changes to the
  deterministic script contracts (R5.3). Detection defaults to `auto`; `--no-codegraph`
  opts out and reproduces pre-codegraph behavior exactly (fail-soft).
  - **`/mgh-init`**: a new optional `init-resolve` stage (codegraph-gated, single context)
    resolves the framework-routed / DI / AOP / interface→impl / reflection controls the
    text/AST call graph collects into `unresolved[]`, emitting additive
    `source:"codegraph"` candidates with a real `resolved_path[]`. scout/induct/survey
    stages prefer `codegraph_explore` (MCP) / `codegraph explore` (CLI) for surgical
    context. `init_manifest.json` gains a `codegraph:{available,used,resolved_count,
    unresolved_residual}` block.
  - **`/mgh-sra`**: `sra-augment` (a3) gains an inline **call-path structural-evidence
    confirmation** — for gaps that already matched all three reuse signals, codegraph
    confirms whether the recommended control is actually wired onto the gap endpoint's
    request path, recorded as advisory `recommended_control.call_path:{confirmed,
    path[],source:"codegraph",note}` (plus data-flow / liveness / domain-sibling
    advisory facets). This upgrades signal-2 "business-domain similarity" from a semantic
    guess toward structural evidence, directly targeting SRA's "controls are asserted to
    exist, not to be effective" blind spot. Bounded + fail-soft (top-1 control per gap
    under budget; `confirmed` never fabricated; never overrides code evidence or user
    `business_context.json`). `sra_manifest.json` gains `counts.call_path_confirmed` /
    `call_path_residual` + a 5th honesty boundary; the existing four stay intact.
- **Shared codegraph steering fragment** `core/prompts/fragments/codegraph-hint.md`,
  co-owned by both changes. Prescriptive by intent — "SHALL prefer codegraph, Read only
  as fallback", never the permissive "you may" — to avoid the known trap where a subagent
  keeps self-Reading and codegraph becomes pure overhead.
- **Dual-platform parity (R5.7)**: claude + opencode both reach codegraph via MCP
  (`codegraph_explore`), with CLI (`codegraph explore`) Bash fallback. The existing
  `block-adhoc-scripts` guard is unchanged — codegraph MCP/CLI calls do not hit any of its
  ad-hoc-script surfaces — so **no new hook** is introduced.

### Known limitation (honest boundary)
- codegraph is itself a static analyzer: reflection / DI-container / runtime dispatch
  remain unresolved, so call-path confirmation shrinks but does not zero out mis-wiring.
  `call_path` is LLM+codegraph advisory needing human review; manifests disclose
  `call_path_residual` / `unresolved_residual` and never claim "fully confirmed".
- opencode's plugin process does not inherit env vars exported mid-session, so the
  `codegraph=on` signal activates reliably only when present at opencode launch; the CLI
  Bash fallback + shell bright-lines cover the gap (fail-soft).

## [0.1.6] — 2026-07-10

### Added
- **opencode runtime-discipline hook parity.** opencode now gets the same orchestrator-discipline
  enforcement Claude Code has. `install.sh --opencode` injects a `tool.execute.before` plugin
  (`.opencode/plugins/block_adhoc_scripts.ts`) that normalizes the tool event into Claude's
  PreToolUse stdin shape and pipes it to the **same** platform-neutral Python guard
  (`block_adhoc_scripts.py`, now also mirrored to `.opencode/hooks/`). The guard is unchanged —
  single decision source, byte-parity guarded by `tests/test_opencode_hook_parity.py`. New
  `tools/install_opencode_plugin.py` mirrors `tools/install_hook.py` (idempotent, merge-aware,
  `--remove`). This corrects the prior wrong premise that "opencode has no PreToolUse capability":
  opencode's hook surface is JS/TS plugins (`tool.execute.before`/`tool.execute.after`) — this was
  a porting gap, now closed (not a capability gap).

### Known limitation (honest boundary)
- opencode's plugin process does **not** inherit env vars exported mid-session via `bash` (its shell
  tool builds env from `process.env` and never writes back). So `export MGH_*_ACTIVE=1` inside a run
  may not reach the guard; the runtime gate activates only when the env is present at opencode
  launch (e.g. `MGH_*_ACTIVE=1 opencode run`). The shell bright-lines + per-stage `--check` boundary
  validation remain the real backstop either way (fail-soft). Verified against opencode v1.17.15.

### Fixed
- **`/mgh-init` scout→merge fold-in crashed on two kinds of malformed `scout_candidates.json`**
  (raw traceback, empty stdout, orchestrator unable to decide). (1) A candidate missing its
  `category` field hit a `KeyError` in `merge_scout._normalize`; (2) a broken JSON string value
  (e.g. an `evidence_snippet` with mis-escaped quotes / backslashes) raised `JSONDecodeError` —
  and `merge_scout.py --check` returned exit `1` (not `2`), so the orchestrator gate (which only
  rolls back on exit 2) let it through to `main()`, which had no `try/except`.
- Fix (defense-in-depth, three layers): `--check` now also asserts every candidate carries a
  non-empty `category`, and returns exit `2` for malformed JSON with `lineno`/`colno`/`msg` + a
  nearby byte window; `main()` wraps all `json.loads` (`--candidates` / `--scout` / `--clusters`)
  so a malformed input yields a structured stdout error + exit `1` with NO traceback, and
  `_normalize` now skips + warns on any category-less candidate (count surfaced as `skipped` in
  the success summary) — covering the `audit_found[]` path that bypasses `--check`.
  `discover_controls.form_clusters` is untouched (skipped candidates never reach it).
- The S3 / S4 / audit stage prompts now require a non-empty `category` on every candidate and a
  JSON-safe `evidence_snippet` (single line; `"` → `'`; strip `\`) — structurally incapable of
  breaking the enclosing JSON string. Covered by `tests/test_merge_scout.py`.

---

## [0.1.5] — 2026-07-07

### Fixed
- **`/mgh-init` fan-out checkpoints occasionally landed outside the project tree**
  (observed: a Windows drive root, e.g. `D:\xxx.json`). Root cause: the scout/T1/T3
  output paths were soft — placeholder templates / relative paths assembled twice (once
  by the orchestrator, once by the subagent); a misplaced subagent cwd resolved a
  relative path to the drive root. The enumeration scripts (`list_scout_batches.py` /
  `list_clusters.py` / `list_rule_jobs.py`) did not emit paths at all, so both agents
  had to assemble them.
- Fix: each enumerator now emits a **single authoritative absolute** `checkpoint_path`
  (scout/T1) / `rule_path` (T3) + `done_marker` per pending unit (via `Path.resolve()`).
  The orchestrator passes these **verbatim**; the stage prompts + double-shell agent
  defs treat them as **verbatim input fields** with a `NEVER`-boundary against
  self-assembly / invented filenames / relative paths / out-of-tree writes.
- **Defense-in-depth**: the `block-adhoc-scripts` PreToolUse hook (claude, `MGH_INIT_ACTIVE`
  run-domain) now also blocks `Write`/`Edit` whose resolved target is **outside the
  `MGH_TARGET` tree** (fail-loud, exit 2, recipe points at `list_*` stdout). `MGH_TARGET`
  is sourced from discover's absolute `repo` (via `describe_artifact --field repo`, never
  `py -c`); missing → degrade (pass). `--no-enforce-hook` opt-out unchanged; opencode
  (no PreToolUse) warns + skips.
- **AGENTS.md**: R5.3(b) extended (enumerators MUST emit exact absolute output paths);
  R5.5① gains a fan-out path recipe.
- New contract `core/contracts/init/cluster-enumeration.md` (T1 previously had no
  enumeration contract); `scout-enumeration.md` / `rule-jobs.md` gain the path fields.
- All additive: on-disk artifact schemas unchanged; no new runtime deps; no new CLI flags
  (`check_contracts` 0 violations). 181 tests pass.

### Upgrade
- Re-run `./install.sh --claude <target>` (or `--opencode`) to refresh the hook + shells
  + stage prompts. Existing checkpoints/rules are unaffected (schema unchanged).

---

## [0.1.1] — 2026-06-29

### Fixed
- **opencode agents failed validation on startup** with
  `Configuration is invalid ... invalid input: expected record, receiving string tools`.
  Cause: generated opencode agent frontmatter used `tools: read, glob, grep` (a
  string), but opencode's `tools` field is deprecated and expects a record.
  Fix: `tools` replaced by a `permission:` record (`read/glob/grep/list/bash/edit`
  → `allow|deny` derived from each agent's Claude tool set); the Claude-only
  `model: inherit` was removed (opencode markdown agents omit `model` to use the
  configured default). Verified all 8 agents parse as valid opencode frontmatter.

### Upgrade
- If you installed an earlier `0.1.0` with `--opencode`: re-run
  `bash install.sh --opencode .` (or the `.ps1`) in your project to
  overwrite the broken `.opencode/agent/sast-*.md` files, then restart opencode.

---

## [0.1.0] — 2026-06-29

Initial release.

### Added
- **9-stage SAST pipeline** as a native Claude Code / opencode command `/mgh-sast`
  (survey → threat-model → decompose → deep-dive → prefilter → verify → dedup →
  chain → SARIF). Zero runtime dependency on `vvaharness`.
- **Stage mapping** faithful to the original: LLM reasoning stages (s1/s2/s3/s4/s6/s8)
  run as subagents driven by skill lenses; deterministic stages (s5 prefilter,
  s7 dedup, s9 SARIF/CVSS/CWE) run as Python ≥3.10 stdlib scripts.
- **Verbatim prompt porting** from vvaharness via a stdlib `ast` extractor
  (`tools/extract_prompts.py`): stage system prompts, shared triage fragments,
  specialist lenses, threat baselines. s4 composed SYSTEM = 8,065 chars (matches
  the original). Provenance table in `core/docs/prompt-provenance.md`; Apache-2.0
  headers + `core/docs/NOTICE`.
- **Incremental scan** `--diff <ref>` — git-diff seed + call-chain expansion.
- **Scope scan** `--path <dir>` / `--package <pkg>` — directory/package seed +
  call-chain expansion.
- **Call-chain engine** (`core/scripts/expand_scope.py`): zero-dep text call graph
  (Java/Python/JS-TS/Go + generic), optional tree-sitter fallback, bidirectional
  BFS (default `both`/depth 2), Spring/Feign/AOP/DI framework allowlist.
- **Batch multi-repo** `--repo-file` (+ `--group-by-app`, `--keep-clones`,
  `--workspace`).
- **Dual-platform packaging**: platform-neutral shared `core/` + a Claude Code
  shell + an opencode shell. Installers `install.sh` / `install.ps1` with a
  zero-runtime-dependency self-check.
- **SARIF 2.1.0** output (`core/scripts/emit_sarif.py`) with a CVSS 3.1 base-score
  calculator (official roundup) + CWE mapping; severity always derived from the
  CVSS band and never disagrees with the score.
- **Unit tests** for the deterministic stages (`tests/test_deterministic.py`):
  9 tests covering prefilter gates, dedup merge, CVSS math, severity bands.
- **Distribution guide** (`docs/分发与使用指南.md`) for enterprise intranet rollout
  across Claude Code and opencode users.

### Known limitations
- Findings are **triage candidates, not confirmed vulnerabilities**; runs are
  non-deterministic.
- The call graph is **textual/AST-level**. It misses dynamic dispatch, reflection,
  DI, and framework routing (Spring `@*Mapping`, Feign, AOP, `@Autowired`,
  JPA/Spring Data). Framework-routed files unresolved against the seed are listed
  in `scope_manifest.unresolved[]` and the report for manual follow-up.

### Pending (not in this release)
- Live end-to-end scan against a real target repo.
- opencode live run + Claude↔opencode parity regression.
- Optional differential comparison vs upstream vvaharness output.
- `AGENTS_CN.md` / README pointer update to `/mgh-sast`.

---

## Versioning policy

- `0.x.y` — initial development; structural completeness, live verification in
  progress. Breaking changes may occur between `0.x` releases.
- `1.0.0` — first stable release once the *Pending* live-verification items close.
