<#
  Render a Markdown release-notes file to a Regnology-branded PDF.
  Usage: ./make-pdf.ps1 -Md .\Product-1.2.0-notes.md -Title "Product 1.2.0" -Subtitle "Release notes"
#>
param(
  [Parameter(Mandatory)][string]$Md,
  [Parameter(Mandatory)][string]$Title,
  [string]$Subtitle = "Release notes",
  [string]$BrandDir = (Join-Path "$env:SPEC_KITTY_PACK_HOME" "doctrine-org\pack\templates\branding"),
  [string]$Node     = "node",
  [string]$Footer   = "Regnology"
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$mdFull = (Resolve-Path $Md).Path
$stem = [IO.Path]::GetFileNameWithoutExtension($mdFull)
$outDir = Split-Path $mdFull -Parent
$html = Join-Path $outDir "$stem.html"
$pdf  = Join-Path $outDir "$stem.pdf"

& $Node (Join-Path $here 'md-to-branded-html.mjs') $mdFull $html $Title $Subtitle $BrandDir $Footer
if ($LASTEXITCODE -ne 0) { throw "html generation failed" }

$chrome = @(
  "C:\Program Files\Google\Chrome\Application\chrome.exe",
  "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
  "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
  "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { throw "No Chrome/Edge found for PDF printing." }

$fileUrl = "file:///" + ($html -replace '\\','/')
$profile = Join-Path $env:TEMP ("rn-pdf-" + [guid]::NewGuid().ToString('N'))
if (Test-Path $pdf) { Remove-Item $pdf -Force }
$p = Start-Process -FilePath $chrome -Wait -PassThru -WindowStyle Hidden -ArgumentList @(
  "--headless=new","--disable-gpu","--no-first-run","--disable-extensions",
  "--user-data-dir=$profile","--print-to-pdf=$pdf",$fileUrl
)
Remove-Item $profile -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $pdf) {
  "OK  -> $pdf  ($([math]::Round((Get-Item $pdf).Length/1kb,1)) KB)"
} else {
  throw "PDF not produced: $pdf"
}
