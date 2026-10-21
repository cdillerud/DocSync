#requires -Version 7.0
<#
.SYNOPSIS
  Builds and publishes the GPI Packaging Catalog extension to a Business Central sandbox in one step, the same
  way VS Code does (the BC development endpoint, schema update mode Synchronize), using YOUR az login.

.DESCRIPTION
  1. Builds the .app with Build-GPIPackagingCatalog.ps1 (unless -SkipBuild and the .app for this version exists).
  2. Publishes it to the sandbox (default PRE_GAMERDOCS_CUTOVER_20260831).
  3. Reads back the installed version.
  Sandboxes only: Production is refused (the README requires explicit approval for Production).
.EXAMPLE
  .\packaging-catalog-bc\scripts\Publish-GPIPackagingCatalog.ps1
#>
[CmdletBinding()]
param(
    [string]$Environment = 'PRE_GAMERDOCS_CUTOVER_20260831',
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
$tenantId = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$companyId = '7d84c6d5-81e2-eb11-86df-00224822baa7'
if ($Environment -match '(?i)^prod') { throw 'Production is not published from this script. Publish to a sandbox.' }

$appRoot = Split-Path -Parent $PSScriptRoot
$app = Get-Content -LiteralPath (Join-Path $appRoot 'app.json') -Raw | ConvertFrom-Json
$appFile = Join-Path $appRoot "$($app.name)_$($app.version).app"

if (-not $SkipBuild -or -not (Test-Path -LiteralPath $appFile)) {
    & (Join-Path $PSScriptRoot 'Build-GPIPackagingCatalog.ps1')
    if (-not (Test-Path -LiteralPath $appFile)) { throw "Build did not produce $appFile" }
}

Write-Host ''
Write-Host "==> Publishing $($app.name) $($app.version) to $Environment" -ForegroundColor Cyan
$token = az account get-access-token --resource https://api.businesscentral.dynamics.com --tenant $tenantId --query accessToken -o tsv 2>$null
if (-not $token) {
    az login --tenant $tenantId --output none
    $token = az account get-access-token --resource https://api.businesscentral.dynamics.com --tenant $tenantId --query accessToken -o tsv
}
if (-not $token) { throw "No Business Central token. Run: az login --tenant $tenantId" }

$url = "https://api.businesscentral.dynamics.com/v2.0/$tenantId/$Environment/dev/apps?SchemaUpdateMode=synchronize"
Add-Type -AssemblyName System.Net.Http
$client = [System.Net.Http.HttpClient]::new()
$client.Timeout = [TimeSpan]::FromMinutes(10)
$client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $token)
$stream = [System.IO.File]::OpenRead($appFile)
try {
    $content = [System.Net.Http.MultipartFormDataContent]::new()
    $file = [System.Net.Http.StreamContent]::new($stream)
    $disposition = [System.Net.Http.Headers.ContentDispositionHeaderValue]::new('form-data')
    $disposition.Name = '"file"'
    $disposition.FileName = '"' + [IO.Path]::GetFileName($appFile) + '"'
    $file.Headers.ContentDisposition = $disposition
    $file.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::new('application/octet-stream')
    $content.Add($file)
    Write-Host 'Uploading and installing (1-3 minutes) ...'
    $response = $client.PostAsync($url, $content).GetAwaiter().GetResult()
    $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    if (-not $response.IsSuccessStatusCode) {
        throw "Business Central refused the publish: HTTP $([int]$response.StatusCode). $body"
    }
}
finally { $stream.Dispose(); $client.Dispose() }
Write-Host "Published $($app.name) $($app.version) to $Environment." -ForegroundColor Green

try {
    $ext = Invoke-RestMethod -Headers @{ Authorization = "Bearer $token" } -Uri ("https://api.businesscentral.dynamics.com/v2.0/$tenantId/$Environment/api/microsoft/automation/v2.0/companies($companyId)/extensions?" + '$filter=' + [uri]::EscapeDataString("displayName eq '$($app.name)'"))
    foreach ($e in $ext.value) {
        Write-Host ("Installed: {0} {1}.{2}.{3}.{4} (installed: {5})" -f $e.displayName, $e.versionMajor, $e.versionMinor, $e.versionBuild, $e.versionRevision, $e.isInstalled)
    }
} catch { Write-Host 'Published; the installed version could not be read back with this login (not an error).' -ForegroundColor Yellow }
Write-Host "Next: in Business Central ($Environment), search 'GPI Catalog Sync Setup'." -ForegroundColor Cyan
