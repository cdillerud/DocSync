[CmdletBinding()]
param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Save-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

$appJson = Join-Path $ProjectPath 'app.json'
$opsWorker = Join-Path $ProjectPath 'scripts\Start-GPISpiroPushWorkerUAT.ps1'
$refreshScript = Join-Path $ProjectPath 'scripts\Update-GPISpiroOAuthTokenUAT.ps1'

foreach ($file in @($appJson, $opsWorker)) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Required 0.25 file not found: $file"
    }
}

Write-Host "`n== PRECHECK 0.25 ==" -ForegroundColor Cyan
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.25.0.0') {
    throw "Expected local app version 0.25.0.0. Found $($app.version)."
}
$opsRaw = Get-Content -LiteralPath $opsWorker -Raw
foreach ($marker in @('GPI SPIRO PUSH WORKER OPERATIONS UAT','STALE PROCESSING RECOVERY','RUN BATCH PROCESSOR')) {
    if (-not $opsRaw.Contains($marker)) {
        throw "0.25 operational worker marker not found: $marker"
    }
}
Write-Host '0.25 operational worker confirmed.' -ForegroundColor Green

Write-Host "`n== BUMP APP VERSION TO 0.26.0.0 ==" -ForegroundColor Cyan
$appText = Get-Content -LiteralPath $appJson -Raw
$oldVersion = '"version": "0.25.0.0"'
$newVersion = '"version": "0.26.0.0"'
if (-not $appText.Contains($oldVersion)) {
    throw '0.25 app version text was not found in app.json.'
}
$appText = $appText.Replace($oldVersion, $newVersion)
Save-Utf8NoBom -Path $appJson -Content $appText
Write-Host "Patched: $appJson" -ForegroundColor DarkGreen

Write-Host "`n== CREATE SPIRO OAUTH REFRESH HELPER ==" -ForegroundColor Cyan
$refreshText = @'
[CmdletBinding()]
param(
    [switch]$Apply,
    [int]$RefreshWithinMinutes = 120,
    [string]$TokenStorePath = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml",
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($RefreshWithinMinutes -lt 1 -or $RefreshWithinMinutes -gt 10080) {
    throw 'RefreshWithinMinutes must be between 1 and 10080.'
}
if (-not (Test-Path -LiteralPath $TokenStorePath)) {
    throw "Spiro token store not found: $TokenStorePath"
}

function Convert-SecureToText {
    param([AllowNull()]$Value)
    if ($null -eq $Value) { return $null }
    if ($Value -is [Security.SecureString]) {
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
        try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    }
    return [string]$Value
}

function Convert-TextToSecure {
    param([Parameter(Mandatory)][string]$Text)
    return ConvertTo-SecureString -String $Text -AsPlainText -Force
}

$store = Import-Clixml -LiteralPath $TokenStorePath
$required = @('ClientId','ClientSecret','AccessToken','RefreshToken','TokenEndpoint','ExpiresAtUtc')
foreach ($name in $required) {
    if (-not $store.PSObject.Properties[$name]) {
        throw "Spiro token store is missing required property '$name'."
    }
}

$clientId = [string]$store.ClientId
$clientSecret = Convert-SecureToText $store.ClientSecret
$refreshToken = Convert-SecureToText $store.RefreshToken
$tokenEndpoint = [string]$store.TokenEndpoint
$redirectUri = if ($store.PSObject.Properties['RedirectUri']) { [string]$store.RedirectUri } else { '' }
$expiresAt = [datetime]$store.ExpiresAtUtc
$now = [datetime]::UtcNow
$remaining = $expiresAt.ToUniversalTime() - $now
$needsRefresh = $remaining.TotalMinutes -le $RefreshWithinMinutes

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'SPIRO OAUTH TOKEN LIFECYCLE UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Token Store              : $TokenStorePath"
Write-Host "Expires At UTC           : $($expiresAt.ToUniversalTime().ToString('u'))"
Write-Host "Minutes Remaining        : $([math]::Round($remaining.TotalMinutes, 1))"
Write-Host "Refresh Threshold        : $RefreshWithinMinutes minute(s)"
Write-Host "Refresh Required         : $needsRefresh"
Write-Host "Apply                     : $($Apply.IsPresent)"
Write-Host "Refresh Token Present     : $(-not [string]::IsNullOrWhiteSpace($refreshToken))"
Write-Host "Client Secret Present     : $(-not [string]::IsNullOrWhiteSpace($clientSecret))"
Write-Host "Token Endpoint Host       : $(([uri]$tokenEndpoint).Host)"

if (-not $needsRefresh) {
    Write-Host 'No refresh needed.' -ForegroundColor Green
    return
}

if (-not $Apply) {
    Write-Host 'DRY RUN: token would be refreshed, but no request was sent.' -ForegroundColor Yellow
    return
}

if ([string]::IsNullOrWhiteSpace($clientId) -or [string]::IsNullOrWhiteSpace($clientSecret) -or [string]::IsNullOrWhiteSpace($refreshToken)) {
    throw 'Client ID, client secret, or refresh token is unavailable.'
}
if (-not [uri]::IsWellFormedUriString($tokenEndpoint, [UriKind]::Absolute)) {
    throw 'TokenEndpoint is not a valid absolute URI.'
}

$body = @{
    grant_type    = 'refresh_token'
    client_id     = $clientId
    client_secret = $clientSecret
    refresh_token = $refreshToken
}
if (-not [string]::IsNullOrWhiteSpace($redirectUri)) {
    $body.redirect_uri = $redirectUri
}

Write-Host 'Refreshing Spiro OAuth token...' -ForegroundColor Cyan
$response = Invoke-RestMethod -Method POST -Uri $tokenEndpoint -ContentType 'application/x-www-form-urlencoded' -Body $body -TimeoutSec $TimeoutSeconds

$newAccessToken = [string]$response.access_token
if ([string]::IsNullOrWhiteSpace($newAccessToken)) {
    throw 'Spiro refresh response did not include access_token.'
}

$newRefreshToken = if ($response.PSObject.Properties['refresh_token'] -and -not [string]::IsNullOrWhiteSpace([string]$response.refresh_token)) {
    [string]$response.refresh_token
}
else {
    $refreshToken
}

$expiresIn = if ($response.PSObject.Properties['expires_in']) { [int]$response.expires_in } else { 3600 }
if ($expiresIn -lt 60) {
    throw "Spiro refresh response returned an invalid expires_in value: $expiresIn"
}
$newAcquiredAt = [datetime]::UtcNow
$newExpiresAt = $newAcquiredAt.AddSeconds($expiresIn)

$store.AccessToken = Convert-TextToSecure $newAccessToken
$store.RefreshToken = Convert-TextToSecure $newRefreshToken
if ($store.PSObject.Properties['AcquiredAtUtc']) { $store.AcquiredAtUtc = $newAcquiredAt }
else { $store | Add-Member -NotePropertyName AcquiredAtUtc -NotePropertyValue $newAcquiredAt }
$store.ExpiresAtUtc = $newExpiresAt

$directory = Split-Path -Parent $TokenStorePath
$leaf = Split-Path -Leaf $TokenStorePath
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$tempPath = Join-Path $directory "$leaf.$stamp.tmp"
$backupPath = Join-Path $directory "$leaf.$stamp.bak"

try {
    $store | Export-Clixml -LiteralPath $tempPath -Force
    $verify = Import-Clixml -LiteralPath $tempPath
    if (-not $verify.PSObject.Properties['AccessToken'] -or -not $verify.PSObject.Properties['RefreshToken']) {
        throw 'Temporary refreshed token store failed validation.'
    }
    Copy-Item -LiteralPath $TokenStorePath -Destination $backupPath -Force
    Move-Item -LiteralPath $tempPath -Destination $TokenStorePath -Force
}
finally {
    if (Test-Path -LiteralPath $tempPath) {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
    $clientSecret = $null
    $refreshToken = $null
    $newAccessToken = $null
    $newRefreshToken = $null
}

Write-Host "Refresh succeeded." -ForegroundColor Green
Write-Host "New Expires At UTC       : $($newExpiresAt.ToString('u'))" -ForegroundColor Green
Write-Host "Backup                    : $backupPath" -ForegroundColor DarkGray
Write-Host 'No token or secret values were displayed.' -ForegroundColor Green
'@
Save-Utf8NoBom -Path $refreshScript -Content $refreshText
Write-Host "Created: $refreshScript" -ForegroundColor DarkGreen

Write-Host "`n== INTEGRATE REFRESH INTO OPERATIONAL WORKER ==" -ForegroundColor Cyan
$opsText = Get-Content -LiteralPath $opsWorker -Raw
$anchor = "    Write-Section 'AUTHENTICATE TO BUSINESS CENTRAL'"
$integration = @'
    Write-Section 'SPIRO OAUTH TOKEN LIFECYCLE'
    $refreshHelper = Join-Path $PSScriptRoot 'Update-GPISpiroOAuthTokenUAT.ps1'
    if (-not (Test-Path -LiteralPath $refreshHelper)) {
        throw "Spiro OAuth refresh helper not found: $refreshHelper"
    }
    $refreshArgs = @{
        RefreshWithinMinutes = 120
        TokenStorePath       = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml"
        TimeoutSeconds       = $TimeoutSeconds
    }
    if ($Apply) {
        $refreshArgs.Apply = $true
    }
    & $refreshHelper @refreshArgs

    Write-Section 'AUTHENTICATE TO BUSINESS CENTRAL'
'@
if ($opsText.Contains("SPIRO OAUTH TOKEN LIFECYCLE")) {
    Write-Host 'Already present: operational refresh integration.' -ForegroundColor DarkYellow
}
elseif ($opsText.Contains($anchor)) {
    $opsText = $opsText.Replace($anchor, ($integration -replace "`n", "`r`n").TrimEnd())
    Save-Utf8NoBom -Path $opsWorker -Content $opsText
    Write-Host "Patched: $opsWorker" -ForegroundColor DarkGreen
}
else {
    throw 'Operational worker authentication anchor not found.'
}

Write-Host "`n== VALIDATE 0.26 OAUTH LIFECYCLE ==" -ForegroundColor Cyan
$checks = @(
    @{ Path=$appJson; Pattern='"version": "0.26.0.0"'; Label='0.26 app version' },
    @{ Path=$refreshScript; Pattern="grant_type    = 'refresh_token'"; Label='refresh-token grant' },
    @{ Path=$refreshScript; Pattern='Export-Clixml'; Label='DPAPI token persistence' },
    @{ Path=$refreshScript; Pattern='backupPath'; Label='token-store backup' },
    @{ Path=$refreshScript; Pattern='No token or secret values were displayed.'; Label='secret-safe output' },
    @{ Path=$opsWorker; Pattern='SPIRO OAUTH TOKEN LIFECYCLE'; Label='operational refresh integration' },
    @{ Path=$opsWorker; Pattern='RefreshWithinMinutes = 120'; Label='proactive refresh threshold' }
)
foreach ($check in $checks) {
    $raw = Get-Content -LiteralPath $check.Path -Raw
    if (-not $raw.Contains($check.Pattern)) {
        throw "Validation failed: $($check.Label)"
    }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host "`n0.26 Spiro OAuth refresh lifecycle hardening applied successfully." -ForegroundColor Green
Write-Host 'Existing scheduled task definition was not changed.' -ForegroundColor Yellow
Write-Host 'Build 0.26, then test the refresh helper in dry-run mode before forcing a refresh.' -ForegroundColor Cyan
