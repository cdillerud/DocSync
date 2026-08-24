[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$KeyVaultName = 'kv-gbca-bacf30f9',
    [string]$TokenStorePath = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI (az) is required.'
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

$store = Import-Clixml -LiteralPath $TokenStorePath
$required = @('ClientId','ClientSecret','RefreshToken','TokenEndpoint')
foreach ($name in $required) {
    if (-not $store.PSObject.Properties[$name]) {
        throw "Spiro token store is missing required property '$name'."
    }
}

$values = [ordered]@{
    'spiro-oauth-client-id'     = [string]$store.ClientId
    'spiro-oauth-client-secret' = Convert-SecureToText $store.ClientSecret
    'spiro-oauth-refresh-token' = Convert-SecureToText $store.RefreshToken
    'spiro-oauth-token-endpoint'= [string]$store.TokenEndpoint
    'spiro-oauth-redirect-uri'  = if ($store.PSObject.Properties['RedirectUri']) { [string]$store.RedirectUri } else { '' }
}

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'GPI SPIRO KEY VAULT CREDENTIAL INITIALIZER UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Key Vault : $KeyVaultName"
Write-Host "Source    : $TokenStorePath"
Write-Host "Apply     : $($Apply.IsPresent)"
Write-Host ''
foreach ($name in $values.Keys) {
    $present = -not [string]::IsNullOrWhiteSpace([string]$values[$name])
    Write-Host ("{0,-30} Present: {1}" -f $name, $present)
}
Write-Host ''
Write-Host 'No secret values are displayed.' -ForegroundColor Green

if (-not $Apply) {
    Write-Host 'PREVIEW ONLY. No Key Vault secrets were created or changed.' -ForegroundColor Yellow
    return
}

foreach ($name in $values.Keys) {
    $value = [string]$values[$name]
    if ([string]::IsNullOrWhiteSpace($value)) {
        if ($name -eq 'spiro-oauth-redirect-uri') { continue }
        throw "Required value for '$name' is empty."
    }
    $null = $value | & az keyvault secret set --vault-name $KeyVaultName --name $name --value '@-' --only-show-errors --output none
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to set Key Vault secret '$name'."
    }
    Write-Host "Stored: $name" -ForegroundColor Green
}

Write-Host ''
Write-Host 'PASS: Spiro OAuth credential material copied to Key Vault.' -ForegroundColor Green
Write-Host 'The existing DPAPI token store was not changed.' -ForegroundColor Yellow