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