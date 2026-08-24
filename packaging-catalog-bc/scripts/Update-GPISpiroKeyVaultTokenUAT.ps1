[CmdletBinding()]
param(
    [switch]$Apply,
    [int]$RefreshWithinMinutes = 120,
    [string]$KeyVaultName = 'kv-gbca-bacf30f9',
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($RefreshWithinMinutes -lt 1 -or $RefreshWithinMinutes -gt 10080) { throw 'RefreshWithinMinutes must be between 1 and 10080.' }
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw 'Azure CLI (az) is required.' }

function Get-KvSecret {
    param([Parameter(Mandatory)][string]$Name)
    $value = (& az keyvault secret show --vault-name $KeyVaultName --name $Name --query value --output tsv --only-show-errors).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($value)) { throw "Could not retrieve Key Vault secret '$Name'." }
    return $value
}

$clientId = Get-KvSecret 'spiro-oauth-client-id'
$clientSecret = Get-KvSecret 'spiro-oauth-client-secret'
$refreshToken = Get-KvSecret 'spiro-oauth-refresh-token'
$tokenEndpoint = Get-KvSecret 'spiro-oauth-token-endpoint'
$accessToken = Get-KvSecret 'spiro-oauth-access-token'
$expiresText = Get-KvSecret 'spiro-oauth-expires-at-utc'
$redirectUri = (& az keyvault secret show --vault-name $KeyVaultName --name 'spiro-oauth-redirect-uri' --query value --output tsv --only-show-errors 2>$null).Trim()

$expiresAt = [datetime]::Parse($expiresText).ToUniversalTime()
$remaining = $expiresAt - [datetime]::UtcNow
$needsRefresh = $remaining.TotalMinutes -le $RefreshWithinMinutes

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'SPIRO KEY VAULT TOKEN LIFECYCLE UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Key Vault               : $KeyVaultName"
Write-Host "Expires At UTC           : $($expiresAt.ToString('u'))"
Write-Host "Minutes Remaining        : $([math]::Round($remaining.TotalMinutes,1))"
Write-Host "Refresh Threshold        : $RefreshWithinMinutes minute(s)"
Write-Host "Refresh Required         : $needsRefresh"
Write-Host "Apply                    : $($Apply.IsPresent)"
Write-Host 'No token or secret values are displayed.' -ForegroundColor Green

if (-not $needsRefresh) {
    Write-Host 'No refresh needed.' -ForegroundColor Green
    return
}
if (-not $Apply) {
    Write-Host 'DRY RUN: token would be refreshed, but no OAuth request was sent.' -ForegroundColor Yellow
    return
}

$body = @{
    grant_type    = 'refresh_token'
    client_id     = $clientId
    client_secret = $clientSecret
    refresh_token = $refreshToken
}
if (-not [string]::IsNullOrWhiteSpace($redirectUri)) { $body.redirect_uri = $redirectUri }

$response = Invoke-RestMethod -Method POST -Uri $tokenEndpoint -ContentType 'application/x-www-form-urlencoded' -Body $body -TimeoutSec $TimeoutSeconds
$newAccessToken = [string]$response.access_token
if ([string]::IsNullOrWhiteSpace($newAccessToken)) { throw 'Spiro refresh response did not include access_token.' }
$newRefreshToken = if ($response.PSObject.Properties['refresh_token'] -and -not [string]::IsNullOrWhiteSpace([string]$response.refresh_token)) { [string]$response.refresh_token } else { $refreshToken }
$expiresIn = if ($response.PSObject.Properties['expires_in']) { [int]$response.expires_in } else { 3600 }
if ($expiresIn -lt 60) { throw "Invalid expires_in returned by Spiro: $expiresIn" }
$newExpiresAt = [datetime]::UtcNow.AddSeconds($expiresIn).ToString('o')

$null = $newAccessToken | & az keyvault secret set --vault-name $KeyVaultName --name 'spiro-oauth-access-token' --value '@-' --only-show-errors --output none
if ($LASTEXITCODE -ne 0) { throw 'Failed to persist refreshed access token to Key Vault.' }
$null = $newExpiresAt | & az keyvault secret set --vault-name $KeyVaultName --name 'spiro-oauth-expires-at-utc' --value '@-' --only-show-errors --output none
if ($LASTEXITCODE -ne 0) { throw 'Failed to persist refreshed expiry to Key Vault.' }
if ($newRefreshToken -ne $refreshToken) {
    $null = $newRefreshToken | & az keyvault secret set --vault-name $KeyVaultName --name 'spiro-oauth-refresh-token' --value '@-' --only-show-errors --output none
    if ($LASTEXITCODE -ne 0) { throw 'Failed to persist rotated refresh token to Key Vault.' }
    Write-Host 'Rotated refresh token saved to Key Vault.' -ForegroundColor Green
}

$headers = @{ Authorization = "Bearer $newAccessToken"; Accept = 'application/json'; 'X-Api-Version' = '1' }
$verify = Invoke-RestMethod -Method GET -Uri 'https://api.spiro.ai/api/v1/opportunities/3609460' -Headers $headers -TimeoutSec $TimeoutSeconds
if (-not $verify) { throw 'Spiro verification request returned no response.' }

$clientSecret = $null
$refreshToken = $null
$accessToken = $null
$newAccessToken = $null
$newRefreshToken = $null
Write-Host "Refresh succeeded. New Expires At UTC: $([datetime]::Parse($newExpiresAt).ToUniversalTime().ToString('u'))" -ForegroundColor Green
Write-Host 'PASS: Key Vault token lifecycle refresh and Spiro verification succeeded.' -ForegroundColor Green