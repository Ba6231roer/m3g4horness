# m3g4h⊿rness installer (Windows PowerShell)
# Usage: .\install.ps1 [-Platform claude|opencode|dsh] [-Target .] [-DshProfile <name>] [-NoEnforceHook]
[CmdletBinding()]
param(
  [ValidateSet('claude','opencode','dsh')][string]$Platform = 'claude',
  [string]$Target = '.',
  [string]$DshProfile = '',
  [switch]$NoEnforceHook
)
$ErrorActionPreference = 'Stop'
$Here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = (Resolve-Path $Target).Path
$ShellSrc = Join-Path $Here "releases\$Platform"
$CoreSrc  = Join-Path $Here 'core'
if (-not (Test-Path $ShellSrc)) { throw "unknown platform shell: $ShellSrc" }
if (-not (Test-Path $CoreSrc))  { throw "missing core/: $CoreSrc" }

# 1) zero-dependency check
$bad = Get-ChildItem $Here -Recurse -Include *.py,*.md -File |
  Select-String -Pattern 'import +vvaharness|from +vvaharness'
if ($bad) { Write-Host "x zero-dependency check FAILED:" -ForegroundColor Red; $bad; exit 1 }
Write-Host "v zero-dependency check passed (no import vvaharness)"

# 2) destination
$Dest = Join-Path $Target $(if ($Platform -eq 'claude') { '.claude' } elseif ($Platform -eq 'opencode') { '.opencode' } else { '.' })

# 3) copy shell + core
function Copy-Dir($src, $dstRel) {
  $dst = Join-Path $Dest $dstRel
  New-Item -ItemType Directory -Force -Path $dst | Out-Null
  Copy-Item -Path "$src\*" -Destination $dst -Recurse -Force
}
if ($Platform -eq 'claude') {
  if (Test-Path "$ShellSrc\commands") { Copy-Dir "$ShellSrc\commands" 'commands' }
  if (Test-Path "$ShellSrc\agents")   { Copy-Dir "$ShellSrc\agents"   'agents' }
  if (Test-Path "$ShellSrc\skills")   { Copy-Dir "$ShellSrc\skills"   'skills' }
} elseif ($Platform -eq 'opencode') {
  if (Test-Path "$ShellSrc\command") { Copy-Dir "$ShellSrc\command" 'command' }
  if (Test-Path "$ShellSrc\agent")   { Copy-Dir "$ShellSrc\agent"   'agent' }
} elseif ($Platform -eq 'dsh') {
  # dsh skills: five shells land in the project-scoped skill root <target>\.dsh\skills\
  # (verified load root; distinct from user-home ~/.dsh). Refresh in place = idempotent.
  # Unconditional: -NoEnforceHook skips wiring only (shells != enforcement).
  if (Test-Path "$ShellSrc\skills") {
    $SkillDst = Join-Path $Target '.dsh\skills'
    New-Item -ItemType Directory -Force -Path $SkillDst | Out-Null
    Copy-Item -Path "$ShellSrc\skills\*" -Destination $SkillDst -Recurse -Force
  }
}
Copy-Dir $CoreSrc 'mgh-core'
Write-Host "v installed $Platform shell into $Dest"

# 5c) dsh face placement + profile wiring (mirror of install.sh step 5c; add-mgh-dsh-host-
#     foundation + add-mgh-dsh-subagent-fanout D6/D7). Shim + sibling guard copy, generated
#     tier mounts (tools\gen_dsh_tiers.py) and the named-delegates fragment always land in
#     <target>\mgh-core\dsh\; enforcement + stage delegation = one idempotent managed block
#     in the 'mgh' profile's cordis.patch.yml (tools\install_dsh_wiring.py --delegates-file).
#     The mgh profile is the sole composition face (fan-out spawns hardcode `dsh --profile
#     mgh`); user profiles are never touched. Missing dsh home / non-mgh -DshProfile -> fail
#     loud BEFORE any wiring. -NoEnforceHook mirrors + creates the skeleton but skips wiring.
if ($Platform -eq 'dsh') {
  $DshDir = Join-Path $Target 'mgh-core\dsh'
  New-Item -ItemType Directory -Force -Path $DshDir | Out-Null
  Copy-Item -Force (Join-Path $Here 'releases\dsh\plugins\mgh-guard.ts') $DshDir
  Copy-Item -Force (Join-Path $Here 'core\scripts\block_adhoc_scripts.py') $DshDir
  Write-Host "v mirrored dsh shim + guard sibling into $DshDir"
  foreach ($f in @('mgh-guard.ts','block_adhoc_scripts.py')) {
    if (-not (Test-Path (Join-Path $DshDir $f))) {
      Write-Host "W self-check (non-blocking): missing dsh face file: mgh-core\dsh\$f" -ForegroundColor Yellow
    }
  }
  # dsh skills self-check (fail-soft here, CI enforces; mirror of install.sh step 5c):
  # five shells present, four kebab-case frontmatter fields each, no host-prefixed
  # install-root reference (.opencode/.claude + mgh-core).
  $skillProblems = @()
  foreach ($sk in @('mgh-sdr','mgh-sast','mgh-init','mgh-sra','mgh-srr')) {
    $sf = Join-Path $Target ".dsh\skills\$sk\SKILL.md"
    if (-not (Test-Path $sf)) { $skillProblems += "$sk (missing)"; continue }
    $t = Get-Content $sf -Raw -Encoding UTF8
    if (($t -notmatch "(?m)^name: $sk`$") -or ($t -notmatch '(?m)^description:') `
        -or ($t -notmatch '(?m)^user-invocable: true') -or ($t -notmatch '(?m)^disable-model-invocation: true') `
        -or ($t -match '\.(opencode|claude)/mgh-core')) { $skillProblems += "$sk (frontmatter/rooting)" }
  }
  if ($skillProblems.Count) {
    Write-Host "W self-check (non-blocking): dsh skills problems: $($skillProblems -join ', ') (.dsh\skills\; CI enforces)" -ForegroundColor Yellow
  } else {
    Write-Host "v dsh skills placed: .dsh\skills\{mgh-sdr,mgh-sast,mgh-init,mgh-sra,mgh-srr}\SKILL.md (frontmatter + rooting clean)"
  }
  # Tier mounts + named-delegation fragment (mirror of install.sh): generation failure =
  # fail-loud at install, never deferred to first dispatch; --check = deterministic 1:1
  # assertion mounts<->definitions (warn-only per R5.8, CI enforces).
  py (Join-Path $Here 'tools\gen_dsh_tiers.py') --agents (Join-Path $Here 'releases\dsh\agents') `
    --out (Join-Path $DshDir 'tiers') --delegates-out (Join-Path $DshDir 'delegates.patch.yml')
  if ($LASTEXITCODE -ne 0) { throw "x dsh tier generation failed (fail-loud, no partial placement)" }
  py (Join-Path $Here 'tools\gen_dsh_tiers.py') --agents (Join-Path $Here 'releases\dsh\agents') `
    --out (Join-Path $DshDir 'tiers') --delegates-out (Join-Path $DshDir 'delegates.patch.yml') --check
  if ($LASTEXITCODE -eq 0) {
    Write-Host "v dsh tier mounts current: mgh-core\dsh\tiers\{scout,t1,t2,t3,sdr}.yml + delegates.patch.yml (1:1 with agents definitions)"
  } else {
    Write-Host "W self-check (non-blocking): dsh tier mounts drift from releases\dsh\agents\ definitions (re-run install; CI enforces)" -ForegroundColor Yellow
  }
  $DshHome = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $HOME '.dsh' }
  if (-not (Test-Path $DshHome)) { throw "x dsh home not found ($DshHome); install/boot dsh first or set DSH_HOME -- nothing wired" }
  $ProfilesDir = Join-Path $DshHome 'profiles'
  # mgh profile is the sole composition face (D7): fan-out spawns hardcode
  # 'dsh --profile mgh', named delegates ride its managed block; user profiles are
  # never touched. A wrong -DshProfile = wiring nothing -> fail loud.
  if ($DshProfile -and $DshProfile -ne 'mgh') {
    throw "x -DshProfile '$DshProfile' is not honored: the mgh composition face is fixed to the 'mgh' profile (dispatcher spawns 'dsh --profile mgh'); drop the flag or pass mgh"
  }
  $DshProfile = 'mgh'
  # profile skeleton (add-only, foreign package.json collision = fail-loud); NOT gated by
  # -NoEnforceHook -- _dsh_precheck needs the profile dir even when enforcement is off.
  py (Join-Path $Here 'tools\create_dsh_profile.py') --dsh-home $DshHome
  if ($LASTEXITCODE -ne 0) { throw "x mgh profile skeleton failed (fail-loud, nothing wired)" }
  $PatchFile = Join-Path $ProfilesDir "$DshProfile\cordis.patch.yml"
  if (-not $NoEnforceHook) {
    $shimWin = (Join-Path $DshDir 'mgh-guard.ts')
    py (Join-Path $Here 'tools\install_dsh_wiring.py') --patch-file $PatchFile --shim $shimWin `
      --delegates-file (Join-Path $DshDir 'delegates.patch.yml')
    if ($LASTEXITCODE -ne 0) { throw "x dsh profile wiring failed (fail-loud, no partial wiring): $PatchFile" }
    Write-Host "v wired mgh composition block (guard shim + timeout policy + named delegates) into dsh profile 'mgh' ($PatchFile; idempotent managed block)"
  } else {
    Write-Host ". -NoEnforceHook: mgh skeleton + tier mounts landed but composition block NOT wired (guard dormant; named stage tools absent)"
  }
}
