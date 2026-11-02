param(
  [string]$Message = "chore: sync teachings and docs",
  [string]$RepoDir = "C:\WORK\QA_MultiAgents for AR &CR"
)

$ErrorActionPreference = "Stop"
Set-Location $RepoDir

git rev-parse --is-inside-work-tree | Out-Null
git add -A

$staged = @(git diff --cached --name-only)
if (-not $staged -or $staged.Count -eq 0) {
  Write-Host "Nothing to commit."
  exit 0
}

$bad = $staged | Where-Object { $_ -match '(?i)local_secrets|(^|/)\.env$|\.pem$|ghp_[A-Za-z0-9]+' }
if ($bad) {
  throw "Refusing to commit secret-looking paths: $($bad -join ', ')"
}

git commit -m $Message

$pushEnv = @{}
if ($env:GITHUB_TOKEN) {
  $basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$($env:GITHUB_TOKEN)"))
  git -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $basic" push origin HEAD
} elseif ($env:GH_TOKEN) {
  $basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$($env:GH_TOKEN)"))
  git -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $basic" push origin HEAD
} else {
  git push origin HEAD
}

git log -1 --oneline
Write-Host "Synced: https://github.com/soulimed/qa-multiagents-ar-cr"
