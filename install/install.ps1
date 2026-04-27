# install.ps1 — install/update the planner Clawpilot skill (Windows).
#
# Usage:
#   .\install.ps1
#   .\install.ps1 -FromUrl https://github.com/msft-hub-tlv/planner.git

param(
  [string]$FromUrl = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$SkillDir  = Join-Path $env:USERPROFILE ".copilot\m-skills\planner"
$BinDir    = Join-Path $env:USERPROFILE ".copilot\bin"
$BackupDir = Join-Path $env:USERPROFILE (".copilot\m-skills\_backups\planner-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
$MinPyMajor = 3
$MinPyMinor = 10

function Cyan($m)  { Write-Host $m -ForegroundColor Cyan }
function Green($m) { Write-Host $m -ForegroundColor Green }
function Red($m)   { Write-Host $m -ForegroundColor Red }

if ($FromUrl) {
  $work = Join-Path ([System.IO.Path]::GetTempPath()) "planner"
  if (Test-Path $work) { Remove-Item -Recurse -Force $work }
  Cyan "▶ Cloning $FromUrl → $work"
  git clone --depth 1 $FromUrl $work
  $RepoRoot = $work
}

# ── Python ─────────────────────────────────────────────────────────────
Cyan "▶ Locating Python ≥ $MinPyMajor.$MinPyMinor"
$py = $null
foreach ($cand in @("python3.13","python3.12","python3.11","python3.10","python","py")) {
  if (Get-Command $cand -ErrorAction SilentlyContinue) {
    $ok = & $cand -c "import sys;exit(0 if sys.version_info>=($MinPyMajor,$MinPyMinor) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $py = $cand; break }
  }
}
if (-not $py) { Red "Python $MinPyMajor.$MinPyMinor+ not found. Install from python.org."; exit 1 }
Green "  using $((& $py --version))"

# ── stage ──────────────────────────────────────────────────────────────
if (Test-Path $SkillDir) {
  Cyan "▶ Backing up existing skill → $BackupDir"
  New-Item -ItemType Directory -Force -Path (Split-Path $BackupDir) | Out-Null
  Copy-Item -Recurse -Force $SkillDir $BackupDir
}

Cyan "▶ Installing skill → $SkillDir"
New-Item -ItemType Directory -Force -Path $SkillDir | Out-Null
robocopy "$RepoRoot\skill" $SkillDir /MIR /XD ".venv" ".cache" /NFL /NDL /NJH /NJS | Out-Null
Copy-Item "$RepoRoot\VERSION" "$SkillDir\VERSION" -Force

# ── venv ───────────────────────────────────────────────────────────────
Cyan "▶ Creating venv at $SkillDir\.venv"
& $py -m venv "$SkillDir\.venv"
$venvPy = Join-Path $SkillDir ".venv\Scripts\python.exe"
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r "$SkillDir\requirements.txt"

# ── launcher ───────────────────────────────────────────────────────────
Cyan "▶ Installing launcher → $BinDir\planner.cmd"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
@"
@echo off
"$venvPy" "$SkillDir\scripts\planner.py" %*
"@ | Set-Content -Encoding ASCII (Join-Path $BinDir "planner.cmd")

Green ("✅ planner skill installed (v" + (Get-Content "$SkillDir\VERSION") + ")")
Write-Host @"

Next steps:
  1. Ensure $BinDir is on your PATH.
  2. Sign in:   planner auth
  3. Try:       planner resolve "<your planner.cloud.microsoft URL>"
  4. Restart Clawpilot to pick up the new /planner skill.
"@
