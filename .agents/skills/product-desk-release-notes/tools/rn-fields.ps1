<#
.SYNOPSIS
  Pull a fix version's tickets from the team's Jira Cloud, and push generated
  release-note text back into the team's release-notes field and its
  exclude-from-release-notes field.

.DESCRIPTION
  Reusable, headless-friendly (CI / CLI) companion to the
  `product-desk-release-notes` skill. Every team value is a parameter; the
  skill's scripts/rn_tools.py fills them from the team's desk settings. Two
  commands:

    pull  - fetch the fixVersion's done tickets + their fields to JSON, and emit
            a seed `<ProductTag>-<version>-rn.json` mapping for the drafter to fill.
    push  - read a filled `<ProductTag>-<version>-rn.json` and write each ticket's
            release_notes into -RnField (and set/clear the -ExcludeField
            flag). DRY-RUN by default; writes ONLY with -Apply.

  Target: -SiteUrl, which must be the team's own instance (-AllowedSite). A
  read-only archive (-RefuseHosts) is NOT a valid target -- it still answers,
  so pointing at it produces a clean-looking run that touches nothing anyone
  reads.

  Field ids are instance-specific. Never carry an id across instances; read it
  from a populated issue.

  REST v2 is used deliberately: on Cloud it returns `description` and the
  Release Notes textarea as plain strings, where v3 would return ADF.

  Auth is Basic with the user's own Atlassian email + API token, read at
  runtime from the env file and NEVER printed or written anywhere. Accepted
  keys: JIRA_CLOUD_EMAIL / JIRA_CLOUD_API_TOKEN, falling back to
  CONFLUENCE_CLOUD_EMAIL / CONFLUENCE_CLOUD_API_TOKEN (one Atlassian token
  works for both on a Cloud site).

  Writes go through curl.exe: Invoke-RestMethod hangs on PUT to Atlassian Cloud.

.PARAMETER Command
  pull | push

.PARAMETER Version
  Bare product version, e.g. 1.2.0. Combined with -FixVersionPrefix to form the
  Jira fixVersion "<prefix> 1.2.0".

.PARAMETER Apply
  (push only) Actually write to Jira. Without it, push is a dry run.

.PARAMETER Overwrite
  (push only) Overwrite a release-notes field that is already non-empty.
  Default: skip tickets whose release-notes field is already populated.

.EXAMPLE
  python ../scripts/rn_tools.py fields pull --version 1.2.0

.EXAMPLE
  python ../scripts/rn_tools.py fields push --version 1.2.0            # dry run

.EXAMPLE
  python ../scripts/rn_tools.py fields push --version 1.2.0 --apply    # writes to Jira
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][ValidateSet('pull','push')] [string]   $Command,
  [Parameter(Mandatory)]                             [string]   $Version,
  [Parameter(Mandatory)]                             [string]   $EnvFile,
  [Parameter(Mandatory)]                             [string]   $SiteUrl,
  [Parameter(Mandatory)]                             [string]   $AllowedSite,      # the team's tracker.instance
  [Parameter(Mandatory)]                             [string]   $Project,
  [Parameter(Mandatory)]                             [string]   $FixVersionPrefix,
  [Parameter(Mandatory)]                             [string]   $ProductTag,       # output filename tag
  [Parameter(Mandatory)]                             [string]   $RnField,          # the release-notes field id
  [Parameter(Mandatory)]                             [string]   $ExcludeField,     # the exclude field id
  [Parameter(Mandatory)]                             [string]   $ExcludeValue,     # the exclude field's option value
  [Parameter(Mandatory)]                             [string[]] $DoneStatuses,
  [string[]] $RefuseHosts      = @(),                      # read-only archives
  [string]   $OutDir           = '',
  [string]   $InputJson,                                   # push: defaults to <ProductTag>-<v>-rn.json
  [switch]   $AllStatuses,                                 # pull: ignore status filter
  [switch]   $WithCommits,                                 # pull: best-effort Bitbucket dev-status
  [switch]   $Apply,                                       # push: write for real
  [switch]   $Overwrite                                    # push: overwrite non-empty RN
)

$ErrorActionPreference = 'Stop'
# powershell -File passes "a,b,c" as one string
$DoneStatuses = @($DoneStatuses | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
$RefuseHosts  = @($RefuseHosts  | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
foreach ($archive in $RefuseHosts) {
  if ($archive -and $SiteUrl -match [regex]::Escape($archive)) {
    throw "Refusing to run against $SiteUrl - $archive is a read-only archive. Use $AllowedSite."
  }
}
if (([uri]$SiteUrl).Host -ne ([uri]$AllowedSite).Host) {
  throw "Refusing to run against $SiteUrl - only $AllowedSite is configured for this team."
}
$SiteUrl       = $SiteUrl.TrimEnd('/')
$BaseUrl       = "$SiteUrl/rest/api/2"
$RN_FIELD      = $RnField
$EXCLUDE_FIELD = $ExcludeField
$EXCLUDE_VALUE = $ExcludeValue
if (-not $OutDir) { $OutDir = (Get-Location).Path }
$fixVersion = "$FixVersionPrefix $Version"

# ---- credentials (never printed) -------------------------------------------
function Get-CloudCredential {
  param([string]$File)
  if (-not (Test-Path $File)) { throw "Cloud env file not found: $File" }
  $kv = @{}
  Get-Content $File | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
    $p = $_ -split '=', 2; $kv[$p[0].Trim()] = $p[1].Trim()
  }
  $email = if ($kv['JIRA_CLOUD_EMAIL'])     { $kv['JIRA_CLOUD_EMAIL'] }     else { $kv['CONFLUENCE_CLOUD_EMAIL'] }
  $token = if ($kv['JIRA_CLOUD_API_TOKEN']) { $kv['JIRA_CLOUD_API_TOKEN'] } else { $kv['CONFLUENCE_CLOUD_API_TOKEN'] }
  if (-not $email -or -not $token) {
    throw "No Cloud credential in $File (need JIRA_CLOUD_EMAIL/JIRA_CLOUD_API_TOKEN or CONFLUENCE_CLOUD_EMAIL/CONFLUENCE_CLOUD_API_TOKEN)"
  }
  return "${email}:${token}"
}
$script:Cred    = Get-CloudCredential -File $EnvFile
$script:Headers = @{ Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($script:Cred)) }

function Invoke-Cloud {
  # Reads only. Writes go through Invoke-CloudPut (curl), because
  # Invoke-RestMethod hangs on PUT to this host.
  param([string]$Uri)
  Invoke-RestMethod -Method GET -Headers $script:Headers -Uri $Uri -TimeoutSec 60
}

function Invoke-CloudPut {
  param([string]$Path,[string]$JsonBody)
  $bodyFile = Join-Path ([IO.Path]::GetTempPath()) "rn-fields-put-$PID.json"
  $respFile = Join-Path ([IO.Path]::GetTempPath()) "rn-fields-resp-$PID.txt"
  [IO.File]::WriteAllText($bodyFile, $JsonBody, (New-Object Text.UTF8Encoding($false)))
  try {
    $code = & curl.exe -s -S --http1.1 -m 60 -o $respFile -w "%{http_code}" `
      -X PUT "$BaseUrl$Path" -u $script:Cred `
      -H "Content-Type: application/json; charset=utf-8" -H "Expect:" `
      --data-binary "@$bodyFile" 2>&1
    if ("$code" -ne '204' -and "$code" -ne '200') {
      $detail = if (Test-Path $respFile) { Get-Content $respFile -Raw } else { '' }
      throw "HTTP $code $detail"
    }
  } finally {
    Remove-Item $bodyFile, $respFile -Force -ErrorAction SilentlyContinue
  }
}

function Get-FixVersionIssues {
  $statusClause = ''
  if (-not $AllStatuses) {
    $inList = ($DoneStatuses | ForEach-Object { '"' + $_ + '"' }) -join ','
    $statusClause = " AND status in ($inList)"
  }
  $jql = "project = $Project AND fixVersion = `"$fixVersion`"$statusClause ORDER BY key ASC"
  $fields = @('key','summary','status','issuetype','description',$RN_FIELD,$EXCLUDE_FIELD,'issuelinks','components') -join ','
  # Cloud: classic /search returns 410 Gone. /search/jql paginates by
  # nextPageToken rather than startAt/total.
  $all = @(); $token = $null
  do {
    $q = "jql=$([uri]::EscapeDataString($jql))&maxResults=100&fields=$fields"
    if ($token) { $q += "&nextPageToken=$([uri]::EscapeDataString($token))" }
    $res = Invoke-Cloud -Uri "$BaseUrl/search/jql?$q"
    if ($res.issues) { $all += $res.issues }
    $token = $res.nextPageToken
  } while ($token -and -not $res.isLast)
  return ,$all
}

function Get-BitbucketCommits {
  param([string]$IssueId)
  # Best-effort: Jira dev-status (present when the Bitbucket app is linked).
  try {
    $d = Invoke-Cloud -Uri "$SiteUrl/rest/dev-status/1.0/issue/detail?issueId=$IssueId&applicationType=stash&dataType=repository"
    $commits = @()
    foreach ($r in $d.detail.repositories) {
      foreach ($c in $r.commits) { $commits += [pscustomobject]@{ repo=$r.name; id=$c.displayId; message=$c.message } }
    }
    return $commits
  } catch { return @() }
}

# ===========================================================================
if ($Command -eq 'pull') {
  Write-Host "Pulling $Project / fixVersion '$fixVersion' from $SiteUrl..." -ForegroundColor Cyan
  $issues = Get-FixVersionIssues
  Write-Host "  $($issues.Count) issue(s) found." -ForegroundColor Green

  $dump = foreach ($i in $issues) {
    $commits = @()
    if ($WithCommits) { $commits = Get-BitbucketCommits -IssueId $i.id }
    [pscustomobject]@{
      key           = $i.key
      summary       = $i.fields.summary
      status        = $i.fields.status.name
      issuetype     = $i.fields.issuetype.name
      components    = @($i.fields.components | ForEach-Object { $_.name })
      description   = $i.fields.description
      release_notes = $i.fields.$RN_FIELD
      exclude       = [bool]($i.fields.$EXCLUDE_FIELD)
      commits       = $commits
    }
  }

  $ticketsPath = Join-Path $OutDir "$ProductTag-$Version-tickets.json"
  $dump | ConvertTo-Json -Depth 8 | Set-Content -Path $ticketsPath -Encoding UTF8
  Write-Host "  Wrote full dump -> $ticketsPath" -ForegroundColor Green

  # Seed RN mapping for the drafter (don't clobber an existing filled one).
  $seedPath = Join-Path $OutDir "$ProductTag-$Version-rn.json"
  if (Test-Path $seedPath) {
    Write-Host "  Seed already exists, left untouched -> $seedPath" -ForegroundColor Yellow
  } else {
    $seed = $dump | ForEach-Object {
      [pscustomobject]@{ key=$_.key; summary=$_.summary; release_notes=''; exclude=$_.exclude }
    }
    $seed | ConvertTo-Json -Depth 5 | Set-Content -Path $seedPath -Encoding UTF8
    Write-Host "  Wrote seed mapping -> $seedPath (fill 'release_notes' then run push)" -ForegroundColor Green
  }
  return
}

# ===========================================================================
if ($Command -eq 'push') {
  if (-not $InputJson) { $InputJson = Join-Path $OutDir "$ProductTag-$Version-rn.json" }
  if (-not (Test-Path $InputJson)) { throw "Input mapping not found: $InputJson (run pull first, then fill release_notes)" }
  $map = Get-Content $InputJson -Raw | ConvertFrom-Json

  $mode = if ($Apply) { 'APPLY (writing to Jira)' } else { 'DRY-RUN (no writes)' }
  Write-Host "Push $Project / '$fixVersion' - $mode" -ForegroundColor Cyan
  Write-Host "  Target: $SiteUrl" -ForegroundColor Cyan
  if ($Apply) { Write-Host "  !! This writes to PRODUCTION Jira tickets." -ForegroundColor Red }

  $rows = @()
  foreach ($m in $map) {
    if (-not $m.key) { continue }
    $cur = Invoke-Cloud -Uri "$BaseUrl/issue/$($m.key)?fields=$RN_FIELD,$EXCLUDE_FIELD,summary"
    $curRN      = [string]$cur.fields.$RN_FIELD
    $curExclude = [bool]($cur.fields.$EXCLUDE_FIELD)
    $newRN      = [string]$m.release_notes
    $wantExcl   = [bool]$m.exclude

    $fields = @{}
    $rnAction = 'skip'
    if ($newRN.Trim()) {
      if (-not $curRN.Trim() -or $Overwrite) {
        if ($curRN.Trim() -ne $newRN.Trim()) { $fields[$RN_FIELD] = $newRN; $rnAction = if($curRN.Trim()){'overwrite'}else{'set'} }
        else { $rnAction = 'unchanged' }
      } else { $rnAction = 'skip(non-empty)' }
    }
    $exAction = 'unchanged'
    if ($wantExcl -ne $curExclude) {
      $fields[$EXCLUDE_FIELD] = if ($wantExcl) { @(@{ value = $EXCLUDE_VALUE }) } else { @() }
      $exAction = if ($wantExcl) { 'set-exclude' } else { 'clear-exclude' }
    }

    $status = 'no-change'
    if ($fields.Count -gt 0) {
      if ($Apply) {
        # Values are cast to primitives above; ConvertTo-Json hangs on
        # PSObject-wrapped values read off a REST response or a JSON file.
        $json = @{ fields = $fields } | ConvertTo-Json -Depth 8
        try { Invoke-CloudPut -Path "/issue/$([string]$m.key)" -JsonBody $json; $status = 'written' }
        catch { $status = "ERROR: $($_.Exception.Message)" }
      } else { $status = 'would-write' }
    }
    $rows += [pscustomobject]@{ key=$m.key; rn=$rnAction; exclude=$exAction; result=$status }
  }

  $rows | Format-Table -Auto | Out-String | Write-Host
  $previewPath = Join-Path $OutDir "$ProductTag-$Version-push-preview.md"
  "# Push preview - $fixVersion ($mode)`n`n| Key | RN action | Exclude action | Result |`n|---|---|---|---|`n" +
    (($rows | ForEach-Object { "| $($_.key) | $($_.rn) | $($_.exclude) | $($_.result) |" }) -join "`n") |
    Set-Content -Path $previewPath -Encoding UTF8
  Write-Host "Wrote preview -> $previewPath" -ForegroundColor Green
  if (-not $Apply) { Write-Host "Dry run only. Re-run with -Apply to write." -ForegroundColor Yellow }
  return
}

