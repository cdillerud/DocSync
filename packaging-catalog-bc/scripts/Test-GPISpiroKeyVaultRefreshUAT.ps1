[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$KeyVaultName = 'kv-gbca-bacf30f9',
    [string]$OpportunityId = '3609460',
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI (az) is required.'
}

function Get-KvSecret {
    param([Parameter(Mandatory)][string]$Name)
    $value = (& az keyvault secret show --vault-name $KeyVaultName --name $Name --query value --output tsv --only-show-errors).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($value)) {
        throw "Could not retrieve Key Vault secret '$Name'."
    }
    return $value
}

$clientId = Get-KvSecret 'spiro-oauth-client-id'
$clientSecret = Get-KvSecret 'spiro-oauth-client-secret'
$refreshToken = Get-KvSecret 'spiro-oauth-refresh-token'
$tokenEndpoint = Get-KvSecret 'spiro-oauth-token-endpoint'
$redirectUri = (& az keyvault secret show --vault-name $KeyVaultName --name 'spiro-oauth-redirect-uri' --query value --output tsv --only-show-errors 2>$null).Trim()

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'GPI SPIRO KEY VAULT REFRESH TEST UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Key Vault           : $KeyVaultName"
Write-Host "Token Endpoint Host : $(([uri]$tokenEndpoint).Host)"
Write-Host "Refresh Token       : Present"
Write-Host "Client Secret       : Present"
Write-Host "Apply               : $($Apply.IsPresent)"
Write-Host 'No token or secret values are displayed.' -ForegroundColor Green

if (-not $Apply) {
    Write-Host 'DRY RUN: Key Vault credentials are readable. No OAuth request was sent.' -ForegroundColor Yellow
    return
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

$response = Invoke-RestMethod -Method POST -Uri $tokenEndpoint -ContentType 'application/x-www-form-urlencoded' -Body $body -TimeoutSec $TimeoutSeconds
$accessToken = [string]$response.access_token
if ([string]::IsNullOrWhiteSpace($accessToken)) {
    throw 'Spiro refresh response did not include access_token.'
}

$newRefreshToken = if ($response.PSObject.Properties['refresh_token'] -and -not [string]::IsNullOrWhiteSpace([string]$response.refresh_token)) {
    [string]$response.refresh_token
}
else {
    $refreshToken
}

if ($newRefreshToken -ne $refreshToken) {
    $null = $newRefreshToken | & az keyvault secret set --vault-name $KeyVaultName --name 'spiro-oauth-refresh-token' --value '@-' --only-show-errors --output none
    if ($LASTEXITCODE -ne 0) {
        throw 'Spiro refresh succeeded, but rotated refresh token could not be saved to Key Vault.'
    }
    Write-Host 'Rotated refresh token saved to Key Vault.' -ForegroundColor Green
}
else {
    Write-Host 'Refresh token was not rotated by Spiro.' -ForegroundColor DarkGray
}

$headers = @{ Authorization = "Bearer $accessToken"; Accept = 'application/json'; 'X-Api-Version' = '1' }
$uri = "https://api.spiro.ai/api/v1/opportunities/$OpportunityId"
$verify = Invoke-RestMethod -Method GET -Uri $uri -Headers $headers -TimeoutSec $TimeoutSeconds
if (-not $verify) {
    throw 'Spiro verification request returned no response.'
}

Write-Host 'PASS: Key Vault sourced refresh grant and Spiro API verification succeeded.' -ForegroundColor Green
$clientSecret = $null
$refreshToken = $null
$newRefreshToken = $null
$accessToken = $null