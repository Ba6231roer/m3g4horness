#!/usr/bin/env bash
# m3g4h⊿rness installer — copies a platform shell + core/ into a project.
# Usage: ./install.sh [--claude|--opencode|--dsh] [target_project_dir]
#   default platform: claude ; default target: current dir
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM="claude"
TARGET="${TARGET:-.}"
ENFORCE_HOOK="1"   # inject PreToolUse hook (R5.7); --no-enforce-hook opts out
DSH_PROFILE="${DSH_PROFILE:-}"   # --dsh: accepted only as 'mgh' (the fixed composition face); other names fail loud

while [[ $# -gt 0 ]]; do
  case "$1" in
    --claude)  PLATFORM="claude"; shift;;
    --opencode) PLATFORM="opencode"; shift;;
    --dsh)     PLATFORM="dsh"; shift;;
    --dsh-profile) DSH_PROFILE="${2:?--dsh-profile needs a profile name}"; shift 2;;
    --no-enforce-hook) ENFORCE_HOOK="0"; shift;;
    -h|--help)
      echo "Usage: $0 [--claude|--opencode|--dsh] [--dsh-profile <name>] [--no-enforce-hook] [target_project_dir]"; exit 0;;
    *) TARGET="$1"; shift;;
  esac
done

TARGET="$(cd "$TARGET" && pwd)"
case "$PLATFORM" in
  claude)   SHELL_SRC="$HERE/releases/claude-code"; DEST_REL=".claude";;
  opencode) SHELL_SRC="$HERE/releases/opencode";    DEST_REL=".opencode";;
  dsh)      SHELL_SRC="$HERE/releases/dsh";         DEST_REL=".";;
esac
CORE_SRC="$HERE/core"

[[ -d "$SHELL_SRC" ]] || { echo "✗ unknown platform shell: $SHELL_SRC" >&2; exit 1; }
[[ -d "$CORE_SRC" ]]  || { echo "✗ missing core/: $CORE_SRC" >&2; exit 1; }

# 1) Zero RUNTIME-dependency check: no real Python import of vvaharness.
#    (Prose attribution like "ported from vvaharness" in .md is allowed.)
if grep -rnE "^[[:space:]]*(import[[:space:]]+vvaharness|from[[:space:]]+vvaharness[[:space:]]+import)" "$HERE" --include=*.py >/dev/null 2>&1; then
  echo "✗ zero-dependency check FAILED: found runtime import of vvaharness:" >&2
  grep -rnE "^[[:space:]]*(import[[:space:]]+vvaharness|from[[:space:]]+vvaharness[[:space:]]+import)" "$HERE" --include=*.py >&2 || true
  exit 1
fi
echo "✓ zero-dependency check passed (no runtime import of vvaharness)"

# 2) Decide destination by platform.
case "$PLATFORM" in
  claude)   DEST="$TARGET/.claude";;
  opencode) DEST="$TARGET/.opencode";;
  dsh)      DEST="$TARGET";;   # dsh has no project-native dir (no auto-discovery); everything
                               # rides mgh-core/ + the profile wiring written to $DSH_HOME.
esac

# 3) Copy the shell-specific files + shared core.
copy_tree() {
  local src="$1" rel="$2"
  local dst="$DEST/$rel"
  mkdir -p "$dst"
  cp -r "$src/." "$dst/"
}

# Shell payload mirrors into the platform-native layout.
case "$PLATFORM" in
  claude)
    [[ -d "$SHELL_SRC/commands" ]] && { mkdir -p "$DEST/commands"; cp -r "$SHELL_SRC/commands/." "$DEST/commands/"; }
    [[ -d "$SHELL_SRC/agents" ]]   && { mkdir -p "$DEST/agents";   cp -r "$SHELL_SRC/agents/."   "$DEST/agents/"; }
    [[ -d "$SHELL_SRC/skills" ]]   && { mkdir -p "$DEST/skills";   cp -r "$SHELL_SRC/skills/."   "$DEST/skills/"; }
    [[ -d "$SHELL_SRC/hooks" ]]    && { mkdir -p "$DEST/hooks";    cp -r "$SHELL_SRC/hooks/."    "$DEST/hooks/"; }
    ;;
  opencode)
    [[ -d "$SHELL_SRC/command" ]]  && { mkdir -p "$DEST/command";  cp -r "$SHELL_SRC/command/."  "$DEST/command/"; }
    [[ -d "$SHELL_SRC/agent" ]]    && { mkdir -p "$DEST/agent";    cp -r "$SHELL_SRC/agent/."    "$DEST/agent/"; }
    # Guard payload (platform-neutral block_adhoc_scripts.py); the .ts plugin that pipes to it
    # is placed idempotently by install_opencode_plugin.py in step 5 (mirrors claude hooks/).
    [[ -d "$SHELL_SRC/hooks" ]]    && { mkdir -p "$DEST/hooks";    cp -r "$SHELL_SRC/hooks/."    "$DEST/hooks/"; }
    ;;
  dsh)
    # dsh skills: the five orchestrator shells land in the project-scoped dsh skill
    # root <target>/.dsh/skills/ (verified load root; distinct from user-home ~/.dsh).
    # cp refreshes in place = idempotent overwrite, no duplicate dirs. Placement is
    # unconditional (--no-enforce-hook only skips guard wiring; shells ≠ enforcement).
    # The pre-execute shim + sibling guard copy land in <target>/mgh-core/dsh/ in step 5c.
    [[ -d "$SHELL_SRC/skills" ]] && { mkdir -p "$TARGET/.dsh/skills"; cp -r "$SHELL_SRC/skills/." "$TARGET/.dsh/skills/"; }
    ;;
esac
# Shared core always lands at <dest>/mgh-core so both shells reference one copy.
# This single copy includes every command/agent/prompt/script/contract/profile
# under core/ and releases/<platform>/ — so /mgh-sast AND /mgh-init (and their
# agents, prompts, discover_controls.py, chunk_sources.py, contracts/init/) ship
# together without per-command enumerate.
mkdir -p "$DEST/mgh-core"
cp -r "$CORE_SRC/." "$DEST/mgh-core/"

# 4) Self-check (fail-soft per R5.8): the /mgh-init discover/scout/assemble pipeline
#    needs these scripts co-located — discover_controls.py / chunk_sources.py do
#    `from expand_scope import ...`, merge_scout.py does `from discover_controls import
#    form_clusters`, and assemble_rules.py is invoked by the orchestrator after T3
#    (opencode assembly + purity lint). /mgh-sast's deterministic stages
#    (list_chunks/list_verify_jobs/prefilter/dedup/emit_sarif) are likewise invoked by the
#    orchestrator. A missing sibling breaks i1 / scout fold-in / opencode assembly / a sast
#    stage at runtime. Warn only (don't block a partial install); CI / tests enforce
#    co-location (R5.8: CI 必 fail).
_missing=()
for s in expand_scope discover_controls chunk_sources plan_scout merge_scout assemble_rules \
         list_clusters list_scout_batches list_rule_jobs plan_aggregate list_steps describe_artifact validate_inventory validate_t1_records \
         discipline_core fanout_runner \
         prepare_augment merge_augment merge_memory ingest_requirements render_report \
         list_chunks list_verify_jobs prefilter dedup emit_sarif \
         classify_tests list_test_groups assemble_test_rules validate_test_rules derive_mutators \
         resume_ut_init_state write_ut_runconfig list_ut_steps \
         diff_group sdr_context render_sdr_report mgh_sdr_launch read_roots_config \
         resume_sdr_state list_sdr_steps sdr_tier; do
  [[ -f "$DEST/mgh-core/scripts/$s.py" ]] || _missing+=("$s.py")
done
if (( ${#_missing[@]} )); then
  echo "⚠ self-check (non-blocking): missing co-located scripts in $DEST/mgh-core/scripts/: ${_missing[*]}" >&2
  echo "  (partial install? /mgh-init, /mgh-sast, /mgh-sra, /mgh-srr, /mgh-ut-init, or /mgh-sdr may fail at runtime; CI enforces co-location)" >&2
else
  echo "✓ mgh-init + mgh-sast + mgh-sra + mgh-srr + mgh-ut-init + mgh-sdr scripts co-located: expand_scope/discover_controls/chunk_sources/plan_scout/merge_scout/assemble_rules + list_clusters/list_scout_batches/list_rule_jobs/plan_aggregate/list_steps/describe_artifact/validate_inventory + fanout_runner(tier-aware dispatcher: scout/scout-merge/t1/t2/t3/sdr) + prepare_augment/merge_augment/merge_memory + ingest_requirements/render_report + list_chunks/list_verify_jobs/prefilter/dedup/emit_sarif + classify_tests/list_test_groups/assemble_test_rules/validate_test_rules/derive_mutators/resume_ut_init_state/write_ut_runconfig/list_ut_steps + diff_group/sdr_context/render_sdr_report/mgh_sdr_launch/read_roots_config/resume_sdr_state/list_sdr_steps/sdr_tier"
fi

# 4a) Fan-out tier payload self-check (fail-soft per R5.8): the tier-aware
#     dispatcher reads per-tier task templates, and opencode installs address
#     the fanout agent clones (mode: primary) by name at spawn time — a missing
#     file breaks that tier's dispatch at runtime. Warn only; CI enforces.
_fanout_missing=()
for t in scout-task scout-merge-task t1-task t2-task t3-task sdr-task; do
  [[ -f "$DEST/mgh-core/prompts/fragments/fanout/$t.md" ]] || _fanout_missing+=("prompts/fragments/fanout/$t.md")
done
# T2 synthesis map-reduce split prompts (t2 map-stage adoption): the partial (per-shard) and
# rollup (cross-shard reduce) stage prompts mirror with the whole-core copy; a missing file
# breaks the over-budget map-reduce path at runtime. Shared by both platforms (core copy).
# scout-merge joins the same map-reduce family (dispatcher-consumed S4 map + rollup).
for s in init-synthesis-partial init-synthesis-rollup init-scout-merge-partial init-scout-merge-rollup; do
  [[ -f "$DEST/mgh-core/prompts/stages/$s.md" ]] || _fanout_missing+=("prompts/stages/$s.md")
done
if [[ "$PLATFORM" == "opencode" ]]; then
  for a in init-scout-fanout init-induct-fanout init-synthesis-fanout init-synthesis-rollup \
           init-scout-merge-fanout init-scout-merge-rollup \
           init-rulewriter-fanout sdr-review-fanout; do
    [[ -f "$DEST/agent/$a.md" ]] || _fanout_missing+=("agent/$a.md")
  done
fi
if (( ${#_fanout_missing[@]} )); then
  echo "⚠ self-check (non-blocking): missing fan-out tier payload: ${_fanout_missing[*]}" >&2
else
  echo "✓ fan-out tier payload co-located: prompts/fragments/fanout/{scout,scout-merge,t1,t2,t3,sdr}-task.md + prompts/stages/init-synthesis-{partial,rollup}.md + prompts/stages/init-scout-merge-{partial,rollup}.md$( [[ "$PLATFORM" == "opencode" ]] && echo " + agent/{init-scout,init-induct,init-synthesis-fanout,init-synthesis-rollup,init-scout-merge-fanout,init-scout-merge-rollup,init-rulewriter,sdr-review}-fanout.md" )"
fi

# 4b) Distribution-purity self-check (R5.10; fail-soft per R5.8): shipped md MUST be
#     free of dev-only provenance / dangling references (rule/decision ids, change-
#     folder names, glasswing_docs/, task.*.md, dev-meta). Warn only on violation —
#     don't block a partial install; CI / tests enforce purity.
if py "$HERE/tools/check_distributed_purity.py" >/dev/null 2>&1; then
  echo "✓ distribution-purity check passed (shipped md clean, R5.10)"
else
  echo "⚠ distribution-purity check FAILED (non-blocking, R5.8 fail-soft): shipped md carries dev-only provenance" >&2
  echo "  run 'py tools/check_distributed_purity.py' for details; CI enforces purity" >&2
fi

# 5) Runtime discipline hook injection (R5.7 deliverable). Both platforms get an equivalent
#    block-adhoc-scripts enforcement path through the SAME Python guard; the hook surfaces differ:
#      claude   = .claude/settings.json PreToolUse command hook -> py .claude/hooks/block_adhoc_scripts.py
#      opencode = .opencode/plugins/*.ts tool.execute.before plugin -> py .opencode/hooks/block_adhoc_scripts.py
#      dsh      = profile cordis.patch.yml -> mgh-core/dsh/mgh-guard.ts -> py mgh-core/dsh/block_adhoc_scripts.py
#                 (placed + wired in step 5c; the block below covers only claude/opencode)
#    (opencode auto-loads .opencode/plugins/*.ts at startup; no config registration.) --no-enforce-hook
#    opts out entirely; discipline then rests on the shell bright-lines + R5.9 checks. Injection
#    failures are fail-soft (warn, non-blocking; CI enforces, R5.8).
if [[ "$ENFORCE_HOOK" == "1" ]]; then
  if [[ "$PLATFORM" == "claude" ]]; then
    SETTINGS="$DEST/settings.json"
    HOOK_CMD="py .claude/hooks/block_adhoc_scripts.py"
    if py "$HERE/tools/install_hook.py" --settings "$SETTINGS" --hook-command "$HOOK_CMD" >/dev/null; then
      echo "✓ injected PreToolUse hook (block-adhoc-scripts) into $SETTINGS (idempotent; --no-enforce-hook to skip)"
    else
      echo "⚠ hook injection failed (non-blocking, R5.8 fail-soft); discipline via shell bright-lines + R5.9" >&2
    fi
  elif [[ "$PLATFORM" == "opencode" ]]; then
    # opencode: place the tool.execute.before plugin (.ts) that pipes to the shared guard.
    # (dsh is NOT handled here — its placement + wiring lives in the dedicated 5c block.)
    if py "$HERE/tools/install_opencode_plugin.py" \
          --plugins-dir "$DEST/plugins" \
          --source "$HERE/releases/opencode/plugins/block_adhoc_scripts.ts" >/dev/null; then
      echo "✓ injected block-adhoc-scripts plugin (tool.execute.before) into $DEST/plugins (idempotent; --no-enforce-hook to skip)"
    else
      echo "⚠ plugin injection failed (non-blocking, R5.8 fail-soft); discipline via shell bright-lines + R5.9" >&2
    fi
  fi
else
  # (dsh's opt-out message lives in the dedicated 5c block; this one speaks claude/opencode faces.)
  [[ "$PLATFORM" == "dsh" ]] || echo "• --no-enforce-hook: block-adhoc-scripts enforcement not injected; discipline via shell bright-lines + R5.9"
fi

# 5c) dsh third-face placement + wiring (add-mgh-dsh-host-foundation; fan-out assets per
#     add-mgh-dsh-subagent-fanout D6/D7). dsh does NOT auto-discover project-local config,
#     so: (1) the shim + a sibling guard copy always mirror into <target>/mgh-core/dsh/,
#     and tier mount files + the named-delegates fragment are GENERATED there from
#     releases/dsh/agents/ (gen_dsh_tiers.py; generation failure = fail-loud at install);
#     (2) enforcement + stage delegation = one idempotent managed block in the 'mgh'
#     profile's cordis.patch.yml (install_dsh_wiring.py --delegates-file) — the mgh profile
#     is the sole composition face (fan-out spawns hardcode `dsh --profile mgh`); the
#     installer only creates/updates THAT profile (create_dsh_profile.py, add-only), user
#     profiles are never touched. Missing $DSH_HOME or a non-mgh --dsh-profile -> fail
#     loud (exit non-zero) BEFORE any wiring.
#     --no-enforce-hook keeps (1) + the mgh skeleton and skips (2) (guard dormant, warn).
if [[ "$PLATFORM" == "dsh" ]]; then
  mkdir -p "$TARGET/mgh-core/dsh"
  cp "$HERE/releases/dsh/plugins/mgh-guard.ts" "$TARGET/mgh-core/dsh/"
  cp "$HERE/core/scripts/block_adhoc_scripts.py" "$TARGET/mgh-core/dsh/"
  echo "✓ mirrored dsh shim + guard sibling into $TARGET/mgh-core/dsh (co-location self-checked below)"
  # dsh face self-check (fail-soft per R5.8, same posture as step 4): the shim resolves its
  # guard as a SIBLING (./block_adhoc_scripts.py next to mgh-guard.ts), so the mirror layout
  # must be complete right after placement. Warn only; CI enforces.
  _dsh_missing=()
  [[ -f "$TARGET/mgh-core/dsh/mgh-guard.ts" ]] || _dsh_missing+=("mgh-core/dsh/mgh-guard.ts")
  [[ -f "$TARGET/mgh-core/dsh/block_adhoc_scripts.py" ]] || _dsh_missing+=("mgh-core/dsh/block_adhoc_scripts.py")
  [[ -f "$TARGET/mgh-core/scripts/block_adhoc_scripts.py" ]] || _dsh_missing+=("mgh-core/scripts/block_adhoc_scripts.py (core canonical)")
  if (( ${#_dsh_missing[@]} )); then
    echo "⚠ self-check (non-blocking): missing dsh face files: ${_dsh_missing[*]} (shim+guard MUST be siblings in mgh-core/dsh/; CI enforces)" >&2
  else
    echo "✓ dsh face co-located: mgh-core/dsh/{mgh-guard.ts,block_adhoc_scripts.py} + core canonical guard"
  fi
  # dsh skills self-check (fail-soft here, CI enforces via test_install_dsh): the five
  # shells placed in step 3 must exist under <target>/.dsh/skills/, each SKILL.md
  # carrying the four kebab-case frontmatter fields, and none referencing a host-prefixed
  # install root (.opencode/.claude + mgh-core must be target-root relative). Placement
  # and this check are NOT gated by --no-enforce-hook (shells ≠ enforcement).
  _skill_missing=()
  for _sk in mgh-sdr mgh-sast mgh-init mgh-sra mgh-srr; do
    _f="$TARGET/.dsh/skills/$_sk/SKILL.md"
    if [[ ! -f "$_f" ]]; then
      _skill_missing+=("$_sk (missing)")
    elif ! grep -q "^name: $_sk\$" "$_f" || ! grep -q '^description:' "$_f" \
      || ! grep -q '^user-invocable: true' "$_f" || ! grep -q '^disable-model-invocation: true' "$_f"; then
      _skill_missing+=("$_sk (frontmatter 四字段)")
    elif grep -q '\.\(opencode\|claude\)/mgh-core' "$_f"; then
      _skill_missing+=("$_sk (host-prefixed mgh-core ref)")
    fi
  done
  if (( ${#_skill_missing[@]} )); then
    echo "⚠ self-check (non-blocking): dsh skills problems: ${_skill_missing[*]} (<target>/.dsh/skills/; CI enforces)" >&2
  else
    echo "✓ dsh skills placed: .dsh/skills/{mgh-sdr,mgh-sast,mgh-init,mgh-sra,mgh-srr}/SKILL.md (frontmatter + rooting clean)"
  fi
  # Tier mounts + named-delegation fragment (fanout dispatch reads mgh-core/dsh/tiers/<tier>.yml
  # per spawn; install_dsh_wiring embeds the delegates into the mgh managed block). Compile-time
  # generation landing in the target tree —缺件/失败在 install 期 fail-loud,不拖到首次派发。
  if ! py "$HERE/tools/gen_dsh_tiers.py" --agents "$HERE/releases/dsh/agents" \
       --out "$TARGET/mgh-core/dsh/tiers" \
       --delegates-out "$TARGET/mgh-core/dsh/delegates.patch.yml"; then
    echo "✗ dsh tier generation failed (fail-loud, no partial placement)" >&2
    exit 1
  fi
  # self-check (deterministic 1:1: every fan-out tier has a current mount AND delegates match
  # the agents definition set; --check compares would-write vs on-disk, never writes). Warn
  # only per R5.8; CI enforces.
  if py "$HERE/tools/gen_dsh_tiers.py" --agents "$HERE/releases/dsh/agents" \
       --out "$TARGET/mgh-core/dsh/tiers" \
       --delegates-out "$TARGET/mgh-core/dsh/delegates.patch.yml" --check; then
    echo "✓ dsh tier mounts current: mgh-core/dsh/tiers/{scout,t1,t2,t3,sdr}.yml + delegates.patch.yml (1:1 with agents definitions)"
  else
    echo "⚠ self-check (non-blocking): dsh tier mounts drift from releases/dsh/agents/ definitions (re-run install; CI enforces)" >&2
  fi
  if [[ ! -d "${DSH_HOME:-$HOME/.dsh}" ]]; then
    echo "✗ dsh home not found (${DSH_HOME:-$HOME/.dsh}); install/boot dsh first or set DSH_HOME — nothing wired" >&2
    exit 1
  fi
  PROFILES_DIR="${DSH_HOME:-$HOME/.dsh}/profiles"
  # mgh profile = 唯一组合面(D7):扇出派发逐子进程硬编码 `dsh --profile mgh` 装载,具名委派
  # 实例经该 profile 受管块组合 —— 用户自有 profile 零触碰(install 只建/只改 mgh 这一个)。
  # 旧「唯一既有 profile / --dsh-profile 任意名」语义废弃:接错 profile = 没接,fail-loud。
  if [[ -n "$DSH_PROFILE" && "$DSH_PROFILE" != "mgh" ]]; then
    echo "✗ --dsh-profile '$DSH_PROFILE' is not honored: the mgh composition face is fixed to the 'mgh' profile (dispatcher spawns \`dsh --profile mgh\`); drop the flag or pass mgh" >&2
    exit 1
  fi
  DSH_PROFILE="mgh"
  # profile skeleton (base+headless bundles package.json + cordis.yml stub; add-only, foreign
  # package.json collision = fail-loud never-rewrite). NOT gated by --no-enforce-hook:
  # _dsh_precheck requires the profile dir to exist even when enforcement is off.
  if ! py "$HERE/tools/create_dsh_profile.py" --dsh-home "${DSH_HOME:-$HOME/.dsh}"; then
    echo "✗ mgh profile skeleton failed (fail-loud, nothing wired)" >&2
    exit 1
  fi
  PATCH_FILE="$PROFILES_DIR/$DSH_PROFILE/cordis.patch.yml"
  if [[ "$ENFORCE_HOOK" == "1" ]]; then
    _shim_win="$(cygpath -w "$TARGET/mgh-core/dsh/mgh-guard.ts" 2>/dev/null || echo "$TARGET/mgh-core/dsh/mgh-guard.ts")"
    if ! py "$HERE/tools/install_dsh_wiring.py" --patch-file "$PATCH_FILE" --shim "$_shim_win" \
         --delegates-file "$TARGET/mgh-core/dsh/delegates.patch.yml"; then
      echo "✗ dsh profile wiring failed (fail-loud, no partial wiring): $PATCH_FILE" >&2
      exit 1
    fi
    echo "✓ wired mgh composition block (guard shim + timeout policy + named delegates) into dsh profile 'mgh' ($PATCH_FILE; idempotent managed block)"
  else
    echo "• --no-enforce-hook: mgh skeleton + tier mounts landed but composition block NOT wired (guard dormant; named stage tools absent)"
  fi
fi

# NOTE: the repo-root docs/ tree (man pages, glossary, upstream index, analysis
# notes) is the maintainer's private workspace and is deliberately NOT installed
# into target projects — nothing shipped may point at it. tools/check_distributed_purity.py
# enforces that; see R5.10 in AGENTS.md.

# 6) Land the PIPL/GB-T 35273 sensitive-catalog .example template (D11). The committed
#    core/scripts/sensitive_catalog.json.example is the canonical 37-item template (kept in
#    sync with sensitive_catalog.py::DEFAULT_TEMPLATE by tests/test_sensitive_catalog.py
#    anti-drift). NOT auto-applied — the company MUST `cp` it to sensitive_catalog.json or
#    pass `--sensitive-catalog @<path>` to activate (D9 backward-compat hard gate: no catalog
#    = legacy 6 facets, behavior unchanged). Fail-soft (R5.8): warn only, don't block install.
EXAMPLE_SRC="$CORE_SRC/scripts/sensitive_catalog.json.example"
EXAMPLE_DIR="$TARGET/.mgh-sra"
mkdir -p "$EXAMPLE_DIR"
if [[ -f "$EXAMPLE_SRC" ]]; then
  cp "$EXAMPLE_SRC" "$EXAMPLE_DIR/sensitive_catalog.json.example"
  echo "✓ landed .mgh-sra/sensitive_catalog.json.example (PIPL/GB-T 35273 37-item template; NOT auto-applied — cp to sensitive_catalog.json or use --sensitive-catalog to activate)"
else
  echo "⚠ sensitive_catalog.json.example not landed (source missing: $EXAMPLE_SRC; non-blocking, R5.8 fail-soft)" >&2
fi

echo "✓ installed $PLATFORM shell into $DEST"
echo "  commands: /mgh-sast, /mgh-init, /mgh-sra, /mgh-srr, /mgh-ut-init, /mgh-sdr ($PLATFORM)"
echo "Run /mgh-sast --help, /mgh-init --help, /mgh-sra --help, /mgh-srr --help, /mgh-ut-init --help, or /mgh-sdr --help to verify."
