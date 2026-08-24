[CmdletBinding()]
param(
    [string]$BootstrapPath = "$env:LOCALAPPDATA\GPI\AzureBootstrap\gpi-azure-sp-uat.clixml",
    [string]$KeyVaultName = 'kv-gbca-bacf30f9'
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if (-not (Test-Path -LiteralPath $BootstrapPath)) { throw "Bootstrap file not found: $BootstrapPath" }
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw 'Azure CLI (az) is required.' }
function Convert-SecureToText { param([Security.SecureString]$Value) $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value); try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) } }
$store=Import-Clixml -LiteralPath $BootstrapPath
$plain=Convert-SecureToText $store.ClientSecret
try {
    & az logout 2>$null | Out-Null
    & az login --service-principal --username $store.ClientId --password $plain --tenant $store.TenantId --allow-no-subscriptions --output none --only-show-errors
    if ($LASTEXITCODE -ne 0) { throw 'Service-principal Azure login from bootstrap failed.' }
    $id = (& az keyvault secret show --vault-name $KeyVaultName --name 'spiro-oauth-client-id' --query id --output tsv --only-show-errors 2>&1)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace((@($id)-join '').Trim())) { throw "Key Vault read using bootstrap-authenticated service principal failed. $(@($id)-join [Environment]::NewLine)" }
    Write-Host 'PASS: bootstrap-authenticated service principal can read Key Vault.' -ForegroundColor Green
}
finally { $plain=$null; & az logout 2>$null | Out-Null }