<#
  Push a storage-format XHTML body into a Confluence Cloud page via REST API.
  Auth: Basic (email + API token) read from the env file; token is never printed.
  Every team value is a parameter; the skill's scripts/rn_tools.py fills them
  from the team's desk settings (wiki.instance, the wiki login file, the
  release-notes page labels) and runs the page-title check first.
  Usage:
    python ../scripts/rn_tools.py wiki --page <id> --body <stem>.confluence.xml --version <v>
    python ../scripts/rn_tools.py wiki ... --apply                     # write body + ensure the labels
    ./wiki-push.ps1 -PageId <id> -BodyFile .\x.xml -EnvFile <file> -BaseUrl <wiki> -SkipLabels   # body only
  Dry-run by default: shows current page title/version, label gaps, writes nothing.

  After -Apply, missing Confluence labels from -Labels are POSTed to
  /rest/api/content/{id}/label (idempotent).

  Transport: the PUT goes through curl.exe, NOT Invoke-RestMethod. On this host
  Invoke-RestMethod hangs indefinitely on the Confluence Cloud PUT and its
  -TimeoutSec never fires, leaving you unable to tell whether the write landed;
  the identical request through curl returns in seconds (verified 2026-09-17).
  Reads still use Invoke-RestMethod, which is unaffected.
#>
param(
  [Parameter(Mandatory)][string]$PageId,
  [Parameter(Mandatory)][string]$BodyFile,
  [Parameter(Mandatory)][string]$EnvFile,
  [Parameter(Mandatory)][string]$BaseUrl,
  [string]$Title,                    # optional: override page title (defaults to current)
  [string]$Message,                  # optional: version comment shown in page history
  [string[]]$Labels = @(),           # Confluence labels to ensure (the team's release-notes page labels)
  [switch]$SkipLabels,               # do not touch labels (rare; non-release-notes pages)
  [switch]$Apply
)
$ErrorActionPreference = 'Stop'
[System.Net.ServicePointManager]::Expect100Continue = $false
[System.Net.ServicePointManager]::DefaultConnectionLimit = 10

if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
  throw "curl.exe not found on PATH. It ships with Windows 10+ and is required: Invoke-RestMethod hangs on this endpoint's PUT."
}

# ---- credentials (never printed) ----
if (-not (Test-Path $EnvFile)) { throw "Env file not found: $EnvFile" }
$kv = @{}
Get-Content $EnvFile | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
  $p = $_ -split '=', 2; $kv[$p[0].Trim()] = $p[1].Trim()
}
$email = $kv['CONFLUENCE_CLOUD_EMAIL']
$token = $kv['CONFLUENCE_CLOUD_API_TOKEN']
if (-not $email -or -not $token) { throw "CONFLUENCE_CLOUD_EMAIL / CONFLUENCE_CLOUD_API_TOKEN missing in $EnvFile" }
$auth = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${email}:${token}"))
$h = @{ Authorization = $auth; 'Content-Type' = 'application/json' }
$cred = "${email}:${token}"          # for curl -u; never echoed

if (-not (Test-Path $BodyFile)) { throw "Body file not found: $BodyFile" }
$body = Get-Content $BodyFile -Raw -Encoding UTF8

# ---- body sanity: storage format has no DTD, so only the five predefined XML
# entities are legal. &mdash; &middot; &rarr; and friends are hard parse errors
# that Confluence rejects or mangles -- catch them here, not after publishing.
$badEntities = [regex]::Matches($body, '&[a-zA-Z][a-zA-Z0-9]*;') |
  ForEach-Object { $_.Value } |
  Where-Object { $_ -notin @('&amp;', '&lt;', '&gt;', '&quot;', '&apos;') } |
  Select-Object -Unique
if ($badEntities) {
  throw ("Body contains non-XML entities: {0}. Storage format has no DTD -- replace them with literal Unicode characters." -f ($badEntities -join ', '))
}
try {
  $probe = '<root xmlns:ac="http://atlassian.com/content" xmlns:ri="http://atlassian.com/resource/identifier">' + $body + '</root>'
  [xml]$null = $probe
} catch {
  throw "Body is not well-formed XML: $($_.Exception.Message)"
}

# ---- current page state ----
$cur = Invoke-RestMethod -Headers $h -Uri "$BaseUrl/rest/api/content/${PageId}?expand=version,space"
$curVer = [int]$cur.version.number
$newVer = $curVer + 1
if (-not $Title) { $Title = $cur.title }
"Page      : $PageId  '$($cur.title)'  (space $($cur.space.key))"
"Version   : $curVer -> $newVer"
"Body      : $BodyFile ($([math]::Round(($body.Length)/1kb,1)) KB)"

# ---- labels (required on the team's release-notes pages) ----
$requiredLabels = @()
if (-not $SkipLabels -and $Labels) {
  # powershell -File passes "a,b,c" as one string
  $requiredLabels = @($Labels | ForEach-Object { ([string]$_) -split ',' } | Where-Object { $_ } | Select-Object -Unique)
}
$existingLabelNames = @()
try {
  $lab = Invoke-RestMethod -Headers $h -Uri "$BaseUrl/rest/api/content/${PageId}/label?limit=100"
  $existingLabelNames = @($lab.results | ForEach-Object { [string]$_.name })
} catch {
  Write-Warning "Could not read current labels: $($_.Exception.Message)"
}
$missingLabels = @($requiredLabels | Where-Object { $_ -notin $existingLabelNames })
"Labels    : present=[$($existingLabelNames -join ', ')]"
if ($requiredLabels.Count -gt 0) {
  "Required  : [$($requiredLabels -join ', ')]  missing=[$($missingLabels -join ', ')]"
}

if (-not $Apply) {
  "MODE      : DRY-RUN (nothing written). Re-run with -Apply to publish."
  if ($missingLabels.Count -gt 0) {
    "Would add labels: $($missingLabels -join ', ')"
  }
  return
}

# Every value is cast to a primitive before it reaches ConvertTo-Json. Values
# read off an Invoke-RestMethod response are PSObject-wrapped even when
# `-is [string]` says otherwise, and PowerShell 5.1's ConvertTo-Json recurses
# over that wrapper and HANGS FOREVER on them - no error, no timeout. The casts
# are load-bearing; do not remove them.
$versionBlock = [ordered]@{ number = [int]$newVer }
if ($Message) { $versionBlock['message'] = [string]$Message }
$payload = [ordered]@{
  id      = [string]$PageId
  type    = 'page'
  title   = [string]$Title
  space   = [ordered]@{ key = [string]$cur.space.key }
  version = $versionBlock
  body    = [ordered]@{ storage = [ordered]@{ value = [string]$body; representation = 'storage' } }
} | ConvertTo-Json -Depth 10

# curl reads the payload from a file so nothing large or quoted goes through the
# shell, and writes the response to a file so we never parse stdout.
$payloadFile = Join-Path ([IO.Path]::GetTempPath()) "conf-put-$PID.json"
$respFile    = Join-Path ([IO.Path]::GetTempPath()) "conf-resp-$PID.json"
[IO.File]::WriteAllText($payloadFile, $payload, (New-Object Text.UTF8Encoding($false)))
try {
  $code = & curl.exe -s -S --http1.1 -m 120 -o $respFile -w "%{http_code}" `
    -X PUT "$BaseUrl/rest/api/content/$PageId" `
    -u $cred -H "Content-Type: application/json; charset=utf-8" -H "Expect:" `
    --data-binary "@$payloadFile" 2>&1

  if ("$code" -ne '200') {
    $detail = if (Test-Path $respFile) { (Get-Content $respFile -Raw) } else { '' }
    throw "PUT failed with HTTP $code. $($detail.Substring(0, [Math]::Min(400, $detail.Length)))"
  }
  $res = Get-Content $respFile -Raw | ConvertFrom-Json
} finally {
  Remove-Item $payloadFile, $respFile -Force -ErrorAction SilentlyContinue
}

# ---- ensure Confluence labels (idempotent add of missing only) ----
if ($missingLabels.Count -gt 0) {
  $labelPayload = (@($missingLabels | ForEach-Object {
    [ordered]@{ prefix = 'global'; name = [string]$_ }
  })) | ConvertTo-Json -Depth 5
  # ConvertTo-Json on a single object drops the array — force array wrapper
  if ($missingLabels.Count -eq 1) { $labelPayload = "[$labelPayload]" }
  $labelFile = Join-Path ([IO.Path]::GetTempPath()) "conf-labels-$PID.json"
  $labelResp = Join-Path ([IO.Path]::GetTempPath()) "conf-labels-resp-$PID.json"
  [IO.File]::WriteAllText($labelFile, $labelPayload, (New-Object Text.UTF8Encoding($false)))
  try {
    $lcode = & curl.exe -s -S --http1.1 -m 60 -o $labelResp -w "%{http_code}" `
      -X POST "$BaseUrl/rest/api/content/$PageId/label" `
      -u $cred -H "Content-Type: application/json; charset=utf-8" -H "Expect:" `
      --data-binary "@$labelFile" 2>&1
    if ("$lcode" -notin @('200','201')) {
      $detail = if (Test-Path $labelResp) { (Get-Content $labelResp -Raw) } else { '' }
      throw "Label POST failed with HTTP $lcode. $($detail.Substring(0, [Math]::Min(400, $detail.Length)))"
    }
    "LABELS   : added $($missingLabels -join ', ')"
  } finally {
    Remove-Item $labelFile, $labelResp -Force -ErrorAction SilentlyContinue
  }
} elseif ($requiredLabels.Count -gt 0) {
  "LABELS   : already present"
}

# ---- verify against the server, not against the response we were handed ----
$after = Invoke-RestMethod -Headers $h -Uri "$BaseUrl/rest/api/content/${PageId}?expand=version"
"PUBLISHED : version $($res.version.number)"
"VERIFIED  : server reports version $($after.version.number)"
if ([int]$after.version.number -ne $newVer) {
  Write-Warning "Server version $($after.version.number) is not the expected $newVer - someone else may have edited concurrently. Check the page history."
}
if ($requiredLabels.Count -gt 0) {
  $labAfter = Invoke-RestMethod -Headers $h -Uri "$BaseUrl/rest/api/content/${PageId}/label?limit=100"
  $afterNames = @($labAfter.results | ForEach-Object { [string]$_.name })
  $stillMissing = @($requiredLabels | Where-Object { $_ -notin $afterNames })
  "LABELS OK : [$($afterNames -join ', ')]"
  if ($stillMissing.Count -gt 0) {
    throw "Required labels still missing after POST: $($stillMissing -join ', ')"
  }
}
"URL       : $BaseUrl$($res._links.webui)"
