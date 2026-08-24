[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$KeyVaultName = 'kv-gbca-bacf30f9',
    [string]$TokenStorePath = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw 'Azure CLI (az) is required.' }
if (-not (Test-Path -LiteralPath $TokenStorePath)) { throw "Spiro token store not found: $TokenStorePath" }

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

$store = Import-Clixml -LiteralPath $TokenStorePath
if (-not $store.PSObject.Properties['AccessToken']) { throw 'DPAPI store is missing AccessToken.' }
if (-not $store.PSObject.Properties['ExpiresAtUtc']) { throw 'DPAPI store is missing ExpiresAtUtc.' }

$accessToken = Convert-SecureToText $store.AccessToken
$expiresAt = ([datetime]$store.ExpiresAtUtc).ToUniversalTime().ToString('o')

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'GPI SPIRO KEY VAULT ACCESS TOKEN SEED UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Key Vault              : $KeyVaultName"
Write-Host "Access Token Present   : $(-not [string]::IsNullOrWhiteSpace($accessToken))"
Write-Host "Expiry Present         : $(-not [string]::IsNullOrWhiteSpace($expiresAt))"
Write-Host "Apply                  : $($Apply.IsPresent)"
Write-Host 'No token or secret values are displayed.' -ForegroundColor Green

if (-not $Apply) {
    Write-Host 'PREVIEW ONLY. No Key Vault secrets were created or changed.' -ForegroundColor Yellow
    return
}

if ([string]::IsNullOrWhiteSpace($accessToken)) { throw 'Access token is empty.' }
$null = $accessToken | & az keyvault secret set --vault-name $KeyVaultName --name 'spiro-oauth-access-token' --value '@-' --only-show-errors --output none
if ($LASTEXITCODE -ne 0) { throw 'Failed to store spiro-oauth-access-token.' }
$null = $expiresAt | & az keyvault secret set --vault-name $KeyVaultName --name 'spiro-oauth-expires-at-utc' --value '@-' --only-show-errors --output none
if ($LASTEXITCODE -ne 0) { throw 'Failed to store spiro-oauth-expires-at-utc.' }

$accessToken = $null
Write-Host 'PASS: current Spiro access token and expiry seeded into Key Vault.' -ForegroundColor Green
Write-Host 'The DPAPI token store was not changed.' -ForegroundColor Yellow