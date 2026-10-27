#!/usr/bin/env bash
# m3g4h⊿rness installer — copies a platform shell + core/ into a project.
# Usage: ./install.sh [--claude|--opencode|--dsh] [--dsh-profile <name>] [--no-enforce-hook] [--pack[=<output.zip>]] [target_project_dir]
#   default platform: opencode ; default target: current dir
#   --pack[=<output.zip>]: build a skillhub-ready opencode distribution zip from a
#     staging install instead of installing (opencode only; refuses --claude/--dsh,
#     --no-enforce-hook, a positional target, and a missing/empty VERSION)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM="opencode"
TARGET="${TARGET:-.}"
ENFORCE_HOOK="1"   # inject PreToolUse hook (R5.7); --no-enforce-hook opts out
DSH_PROFILE="${DSH_PROFILE:-}"   # --dsh: accepted only as 'mgh' (the fixed composition face); other names fail loud
PACK=""   # ""=install mode; "__default__"=pack with the versioned default name; else explicit zip path
TARGET_GIVEN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --claude)  PLATFORM="claude"; shift;;
    --opencode) PLATFORM="opencode"; shift;;
    --dsh)     PLATFORM="dsh"; shift;;
    --dsh-profile) DSH_PROFILE="${2:?--dsh-profile needs a profile name}"; shift 2;;
    --no-enforce-hook) ENFORCE_HOOK="0"; shift;;
    --pack)    PACK="__default__"; shift;;
    --pack=*)  PACK="${1#--pack=}"; [[ -n "$PACK" ]] || { echo "✗ --pack= needs an output zip path (bare --pack takes the versioned default name)" >&2; exit 2; }; shift;;
    -h|--help)
      echo "Usage: $0 [--claude|--opencode|--dsh] [--dsh-profile <name>] [--no-enforce-hook] [--pack[=<output.zip>]] [target_project_dir]"; exit 0;;
    *) TARGET="$1"; TARGET_GIVEN="1"; shift;;
  esac
done

# Pack preflight (add-mgh-opencode-pack): pack mode builds a skillhub-ready opencode
# zip from a staging install instead of installing into a project. Refuse up front,
# before any work: non-opencode faces (claude/dsh rewrite existing host config /
# machine-local profile state, which zip extraction cannot do), the enforcement
# opt-out (a release always ships the guard + dispatch plugins), a positional target
# (staging is created internally), and a missing/empty VERSION (an unversioned
# release zip is exactly the stale-package accident this mode exists to prevent).
if [[ -n "$PACK" ]]; then
  [[ -z "$TARGET_GIVEN" ]] || { echo "✗ --pack stages internally; a target_project_dir argument has no meaning here" >&2; exit 2; }
  [[ "$PLATFORM" == "opencode" ]] || { echo "✗ --pack supports the opencode face only (got --$PLATFORM): claude/dsh installs rewrite existing host config or machine-local profile state, which zip extraction cannot do" >&2; exit 2; }
  [[ "$ENFORCE_HOOK" == "1" ]] || { echo "✗ --pack always ships the guard + dispatch plugins; drop --no-enforce-hook" >&2; exit 2; }
  [[ -f "$HERE/VERSION" ]] || { echo "✗ VERSION file missing: cannot name a versioned release zip" >&2; exit 2; }
  MGH_VERSION="$(tr -d '[:space:]' < "$HERE/VERSION")"
  [[ -n "$MGH_VERSION" ]] || { echo "✗ VERSION file is empty: cannot name a versioned release zip" >&2; exit 2; }
fi

# 0) Interpreter probe (installer twin of the command shells' step-0 probe): dev/CI
#    machines vary — `py` may be the real launcher or a broken Store placeholder, and
#    so may `python`/`python3`, per machine. Take the first candidate that is a real
#    Python >= 3.10 and use it for every interpreter call below. Fail loud: a machine
#    without any usable interpreter cannot run the toolchain's scripts anyway, so
#    fail-soft warns here would only defer the breakage to first /mgh-* use.
PY_BIN=""
for _c in py python python3; do
  if "$_c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    PY_BIN="$_c"
    break
  fi
done
[[ -n "$PY_BIN" ]] || { echo "✗ no usable Python interpreter (tried py/python/python3; need >= 3.10) — required for self-checks, hook/plugin wiring and --pack" >&2; exit 1; }
echo "✓ interpreter: $PY_BIN ($("$PY_BIN" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null))"

TARGET="$(cd "$TARGET" && pwd)"
PACK_STAGING=""
if [[ -n "$PACK" ]]; then
  PACK_STAGING="$(mktemp -d "${TMPDIR:-/tmp}/mgh-pack.XXXXXX")"
  TARGET="$PACK_STAGING"
  trap 'echo "✗ pack failed; staging kept at: $PACK_STAGING" >&2' ERR
fi
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

# 3a) Bytecode-cache prune: the local `core/scripts/__pycache__/` rides the wholesale
#     core/ copy — NEVER land it in the target project (foreign machine cache, pure
#     noise, and a target-side purity hazard). Pruned AFTER the copy (robust for any
#     copy implementation), scoped to the trees THIS install owns (dsh's DEST is the
#     target root itself, so there the sweep is limited to mgh-core/ + .dsh/ — never
#     the target's own pre-existing dirs).
case "$PLATFORM" in
  claude|opencode) _prune_dirs=("$DEST");;
  dsh)             _prune_dirs=("$TARGET/mgh-core" "$TARGET/.dsh");;
esac
find "${_prune_dirs[@]}" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
# Loose bytecode files (build-machine residue riding the release tree) are pruned too —
# the __pycache__ sweep above never sees them. Extension of the same hygiene contract
# (add-mgh-opencode-pack D8); a shipped zip makes the residue user-visible.
find "${_prune_dirs[@]}" \( -name '*.pyc' -o -name '*.pyo' \) -type f -delete 2>/dev/null || true

# 3b) Special-auth is a PROJECT-owned optional entry (<target>/.mgh/special-auth.md),
#     never an install artifact. The maintainer's package-side doc is NOT copied
#     into the target; a stale install-tree copy left by an older version is
#     removed with a migration hint (the runtime probes only the project path).
AUTH_DST="$DEST/mgh-core/mgh-special-auth.md"
if [[ -f "$AUTH_DST" ]]; then
  rm -f "$AUTH_DST"
  echo "✓ removed legacy install-tree special-auth doc; place a valid note at <target>/.mgh/special-auth.md if this project needs one"
fi

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
         diff_group sdr_context render_sdr_report human_face_vocab mgh_sdr_launch read_roots_config \
         resume_sdr_state list_sdr_steps sdr_tier env_profile emit_native_plan native_watchdog \
         mgh_telemetry mgh_credentials; do
  [[ -f "$DEST/mgh-core/scripts/$s.py" ]] || _missing+=("$s.py")
done
if (( ${#_missing[@]} )); then
  echo "⚠ self-check (non-blocking): missing co-located scripts in $DEST/mgh-core/scripts/: ${_missing[*]}" >&2
  echo "  (partial install? /mgh-init, /mgh-sast, /mgh-sra, /mgh-srr, /mgh-ut-init, or /mgh-sdr may fail at runtime; CI enforces co-location)" >&2
else
  echo "✓ mgh-init + mgh-sast + mgh-sra + mgh-srr + mgh-ut-init + mgh-sdr scripts co-located: expand_scope/discover_controls/chunk_sources/plan_scout/merge_scout/assemble_rules + list_clusters/list_scout_batches/list_rule_jobs/plan_aggregate/list_steps/describe_artifact/validate_inventory + fanout_runner(tier-aware dispatcher: scout/scout-merge/t1/t2/t3/sdr) + prepare_augment/merge_augment/merge_memory + ingest_requirements/render_report + list_chunks/list_verify_jobs/prefilter/dedup/emit_sarif + classify_tests/list_test_groups/assemble_test_rules/validate_test_rules/derive_mutators/resume_ut_init_state/write_ut_runconfig/list_ut_steps + diff_group/sdr_context/render_sdr_report/human_face_vocab/mgh_sdr_launch/read_roots_config/resume_sdr_state/list_sdr_steps/sdr_tier/env_profile/emit_native_plan/native_watchdog/mgh_telemetry/mgh_credentials"
fi

# 4a) Fan-out tier payload self-check (fail-soft per R5.8): the tier-aware
#     dispatcher reads per-tier task templates, and opencode installs address
#     the fanout agent clones (mode: primary) by name at spawn time — a missing
#     file breaks that tier's dispatch at runtime. Warn only; CI enforces.
_fanout_missing=()
for t in scout-task scout-merge-task t1-task t2-task t3-task sdr-task readability-review; do
  [[ -f "$DEST/mgh-core/prompts/fragments/fanout/$t.md" ]] || _fanout_missing+=("prompts/fragments/fanout/$t.md")
done
# Native-dispatch assets (opencode face defaults /mgh-sdr to native): the wave
# discipline fragment is core-shipped; the agent clone below lives in the host's
# agent/ dir. Missing either is a fail-soft warn here (CI enforces; the runtime
# asset gate in env_profile.require_native_assets refuses dispatch loudly).
[[ -f "$DEST/mgh-core/prompts/fragments/sdr-native-dispatch.md" ]] || _fanout_missing+=("prompts/fragments/sdr-native-dispatch.md")
[[ -f "$DEST/mgh-core/prompts/fragments/init-scout-native-dispatch.md" ]] || _fanout_missing+=("prompts/fragments/init-scout-native-dispatch.md")
[[ -f "$DEST/mgh-core/prompts/fragments/init-aggregate-native-dispatch.md" ]] || _fanout_missing+=("prompts/fragments/init-aggregate-native-dispatch.md")
# T2 synthesis map-reduce split prompts (t2 map-stage adoption): the partial (per-shard) and
# rollup (cross-shard reduce) stage prompts mirror with the whole-core copy; a missing file
# breaks the over-budget map-reduce path at runtime. Shared by both platforms (core copy).
# scout-merge joins the same map-reduce family (dispatcher-consumed S4 map + rollup).
for s in init-synthesis-partial init-synthesis-rollup init-scout-merge-partial init-scout-merge-rollup; do
  [[ -f "$DEST/mgh-core/prompts/stages/$s.md" ]] || _fanout_missing+=("prompts/stages/$s.md")
done
if [[ "$PLATFORM" == "opencode" ]]; then
  for a in init-scout-fanout init-induct-fanout init-synthesis-fanout init-synthesis-rollup \
           init-scout-merge-fanout init-scout-merge-rollup init-scout-native \
           init-induct-native init-synthesis-native init-scout-merge-native \
           init-rulewriter-native \
           init-rulewriter-fanout sdr-review-fanout sdr-review-native; do
    [[ -f "$DEST/agent/$a.md" ]] || _fanout_missing+=("agent/$a.md")
  done
fi
if (( ${#_fanout_missing[@]} )); then
  echo "⚠ self-check (non-blocking): missing fan-out tier payload: ${_fanout_missing[*]}" >&2
else
  echo "✓ fan-out tier payload co-located: prompts/fragments/fanout/{scout,scout-merge,t1,t2,t3,sdr}-task.md + prompts/fragments/fanout/readability-review.md + prompts/fragments/{sdr-native-dispatch,init-scout-native-dispatch,init-aggregate-native-dispatch}.md + prompts/stages/init-synthesis-{partial,rollup}.md + prompts/stages/init-scout-merge-{partial,rollup}.md$( [[ "$PLATFORM" == "opencode" ]] && echo " + agent/{init-scout-fanout,init-induct-fanout,init-synthesis-fanout,init-synthesis-rollup,init-scout-merge-fanout,init-scout-merge-rollup,init-scout-native,init-induct-native,init-synthesis-native,init-scout-merge-native,init-rulewriter-native,init-rulewriter-fanout,sdr-review-fanout,sdr-review-native}.md" )"
fi

# 4b-2) Distribution-completeness self-check (fail-soft; CI enforces via
#       tests/test_distributed_md_purity.py): every agent definition the mgh-init
#       shell's subagent inventory names MUST exist in the platform's agent set — a
#       named-but-missing file is a dangling spawn instruction (claude once shipped
#       without init-scout-merge-rollup.md). dsh is NOT checked here: its agents are
#       tier-named (scout.md / t1.md / …) by design, so the 1:1 name mapping only
#       applies to the claude + opencode faces.
if [[ "$PLATFORM" == "claude" || "$PLATFORM" == "opencode" ]]; then
  _init_shell="$DEST/commands/mgh-init.md"
  _agent_dir="$DEST/agents"
  [[ "$PLATFORM" == "opencode" ]] && { _init_shell="$DEST/command/mgh-init.md"; _agent_dir="$DEST/agent"; }
  _agent_missing=()
  while IFS= read -r _a; do
    [[ -f "$_agent_dir/$_a.md" ]] || _agent_missing+=("$_a.md")
  done < <(grep -o '`init-[a-z0-9-]*`' "$_init_shell" | tr -d '`' | sort -u)
  if (( ${#_agent_missing[@]} )); then
    echo "⚠ self-check (non-blocking): mgh-init shell inventory names agent files missing from $_agent_dir/: ${_agent_missing[*]} (CI enforces)" >&2
  else
    echo "✓ mgh-init subagent inventory complete: every named agent definition exists in $_agent_dir/"
  fi
fi

# 4b) Distribution-purity self-check (R5.10; fail-soft per R5.8): shipped md MUST be
#     free of dev-only provenance / dangling references (rule/decision ids, change-
#     folder names, glasswing_docs/, task.*.md, dev-meta). Warn only on violation —
#     don't block a partial install; CI / tests enforce purity.
_purity_ok=0
if "$PY_BIN" "$HERE/tools/check_distributed_purity.py" >/dev/null 2>&1; then
  _purity_ok=1
  echo "✓ distribution-purity check passed (shipped md clean, R5.10)"
else
  echo "⚠ distribution-purity check FAILED (non-blocking, R5.8 fail-soft): shipped md carries dev-only provenance" >&2
  echo "  run '$PY_BIN tools/check_distributed_purity.py' for details; CI enforces purity" >&2
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
    if "$PY_BIN" "$HERE/tools/install_hook.py" --settings "$SETTINGS" --hook-command "$HOOK_CMD" >/dev/null; then
      echo "✓ injected PreToolUse hook (block-adhoc-scripts) into $SETTINGS (idempotent; --no-enforce-hook to skip)"
    else
      echo "⚠ hook injection failed (non-blocking, R5.8 fail-soft); discipline via shell bright-lines + R5.9" >&2
    fi
  elif [[ "$PLATFORM" == "opencode" ]]; then
    # opencode: place the tool.execute.before plugin (.ts) that pipes to the shared guard,
    # PLUS the mgh_dispatch native-dispatch plugin — a fixed two-file set; the installer
    # manages exactly those two filenames and never touches the user's other plugins.
    # (dsh is NOT handled here — its placement + wiring lives in the dedicated 5c block.)
    if "$PY_BIN" "$HERE/tools/install_opencode_plugin.py" \
          --plugins-dir "$DEST/plugins" \
          --source-dir "$HERE/releases/opencode/plugins" >/dev/null; then
      echo "✓ injected opencode plugins (block-adhoc-scripts guard + mgh-dispatch) into $DEST/plugins (idempotent; --no-enforce-hook to skip)"
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
  if ! "$PY_BIN" "$HERE/tools/gen_dsh_tiers.py" --agents "$HERE/releases/dsh/agents" \
       --out "$TARGET/mgh-core/dsh/tiers" \
       --delegates-out "$TARGET/mgh-core/dsh/delegates.patch.yml"; then
    echo "✗ dsh tier generation failed (fail-loud, no partial placement)" >&2
    exit 1
  fi
  # self-check (deterministic 1:1: every fan-out tier has a current mount AND delegates match
  # the agents definition set; --check compares would-write vs on-disk, never writes). Warn
  # only per R5.8; CI enforces.
  if "$PY_BIN" "$HERE/tools/gen_dsh_tiers.py" --agents "$HERE/releases/dsh/agents" \
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
  if ! "$PY_BIN" "$HERE/tools/create_dsh_profile.py" --dsh-home "${DSH_HOME:-$HOME/.dsh}"; then
    echo "✗ mgh profile skeleton failed (fail-loud, nothing wired)" >&2
    exit 1
  fi
  PATCH_FILE="$PROFILES_DIR/$DSH_PROFILE/cordis.patch.yml"
  if [[ "$ENFORCE_HOOK" == "1" ]]; then
    _shim_win="$(cygpath -w "$TARGET/mgh-core/dsh/mgh-guard.ts" 2>/dev/null || echo "$TARGET/mgh-core/dsh/mgh-guard.ts")"
    if ! "$PY_BIN" "$HERE/tools/install_dsh_wiring.py" --patch-file "$PATCH_FILE" --shim "$_shim_win" \
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

# 7) Pack mode (add-mgh-opencode-pack): everything above ran against the staging dir.
#    The fail-soft self-checks upgrade to a hard gate here — a zip user sees no warns,
#    and a missing-asset release fails a whole enterprise fleet silently — plus four
#    pack-only assertions, then the zip is written once, last, so no half-built package
#    can exist. Staging is kept and its path printed on any failure.
if [[ -n "$PACK" ]]; then
  cp "$HERE/releases/opencode/SKILL.md" "$TARGET/SKILL.md"
  _pack_fail=()
  if (( ${#_missing[@]} )); then _pack_fail+=("mgh-core scripts missing: ${_missing[*]}"); fi
  if (( ${#_fanout_missing[@]} )); then _pack_fail+=("fan-out payload missing: ${_fanout_missing[*]}"); fi
  if [[ "$_purity_ok" != "1" ]]; then _pack_fail+=("distribution-purity check failed"); fi
  if declare -p _agent_missing >/dev/null 2>&1 && (( ${#_agent_missing[@]} )); then
    _pack_fail+=("mgh-init subagent inventory incomplete: ${_agent_missing[*]}")
  fi
  for _p in plugins/block_adhoc_scripts.ts plugins/mgh_dispatch.ts hooks/block_adhoc_scripts.py; do
    [[ -f "$DEST/$_p" ]] || _pack_fail+=(".opencode/$_p missing")
  done
  for _c in mgh-blst mgh-init mgh-sast mgh-sdr mgh-sra mgh-srr mgh-ut-init; do
    [[ -f "$DEST/command/$_c.md" ]] || _pack_fail+=("command/$_c.md missing")
  done
  [[ -f "$TARGET/SKILL.md" ]] || _pack_fail+=("SKILL.md missing (releases/opencode/SKILL.md)")
  [[ -f "$TARGET/.mgh-sra/sensitive_catalog.json.example" ]] || _pack_fail+=(".mgh-sra/sensitive_catalog.json.example missing")
  if (( ${#_pack_fail[@]} )); then
    for _f in "${_pack_fail[@]}"; do echo "✗ pack gate: $_f" >&2; done
    echo "✗ pack aborted; staging kept at: $TARGET" >&2
    exit 2
  fi
  if [[ "$PACK" == "__default__" ]]; then
    OUT_ZIP="$PWD/m3g4horness-$MGH_VERSION-opencode.zip"
  else
    OUT_ZIP="$PACK"
  fi
  if "$PY_BIN" "$HERE/tools/pack_release.py" --staging "$TARGET" --out "$OUT_ZIP"; then
    trap - ERR
    rm -rf "$TARGET"
    echo "✓ packed opencode release: $OUT_ZIP"
    echo "  upload this zip to the intranet skillhub; users extract its CONTENTS at a project root (SKILL.md is upload-format only, safe to delete)"
  else
    echo "✗ packing failed; staging kept at: $TARGET" >&2
    exit 2
  fi
  exit 0
fi

echo "✓ installed $PLATFORM shell into $DEST"
echo "  commands: /mgh-sast, /mgh-init, /mgh-sra, /mgh-srr, /mgh-ut-init, /mgh-sdr ($PLATFORM)"
echo "Run /mgh-sast --help, /mgh-init --help, /mgh-sra --help, /mgh-srr --help, /mgh-ut-init --help, or /mgh-sdr --help to verify."
