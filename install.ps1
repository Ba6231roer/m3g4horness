# m3g4h⊿rness installer (Windows PowerShell)
# Usage: .\install.ps1 [-Platform claude|opencode] [-Target .]
[CmdletBinding()]
param(
  [ValidateSet('claude','opencode')][string]$Platform = 'claude',
  [string]$Target = '.'
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
$Dest = Join-Path $Target $(if ($Platform -eq 'claude') { '.claude' } else { '.opencode' })

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
} else {
  if (Test-Path "$ShellSrc\command") { Copy-Dir "$ShellSrc\command" 'command' }
  if (Test-Path "$ShellSrc\agent")   { Copy-Dir "$ShellSrc\agent"   'agent' }
}
Copy-Dir $CoreSrc 'mgh-core'
Write-Host "v installed $Platform shell into $Dest"
