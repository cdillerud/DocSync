[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$TenantId = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc',
    [string]$ClientId = '6ac62e44-8968-4ad9-b781-434507a5c83a',
    [string]$KeyVaultName = 'kv-gbca-bacf30f9',
    [string]$BootstrapSecretName = 'bc-client-secret',
    [string]$BootstrapPath = "$env:LOCALAPPDATA\GPI\AzureBootstrap\gpi-azure-sp-uat.clixml"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw 'Azure CLI (az) is required.' }

function Invoke-AzText {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $output = & az @Arguments 2>&1
    [pscustomobject]@{ ExitCode=$LASTEXITCODE; Text=(@($output)-join [Environment]::NewLine).Trim() }
}

Write-Host ''
Write-Host ('='*72) -ForegroundColor Cyan
Write-Host 'GPI AZURE SERVICE PRINCIPAL BOOTSTRAP UAT' -ForegroundColor Cyan
Write-Host ('='*72) -ForegroundColor Cyan
Write-Host "Tenant ID      : $TenantId"
Write-Host "Client ID      : $ClientId"
Write-Host "Key Vault      : $KeyVaultName"
Write-Host "Bootstrap Path : $BootstrapPath"
Write-Host "Apply          : $($Apply.IsPresent)"
Write-Host 'No secret values are displayed.' -ForegroundColor Green

$current = Invoke-AzText @('account','show','--output','none','--only-show-errors')
if ($current.ExitCode -ne 0) { throw 'Interactive Azure CLI context is required to initialize the bootstrap. Run az login first.' }
$secret = Invoke-AzText @('keyvault','secret','show','--vault-name',$KeyVaultName,'--name',$BootstrapSecretName,'--query','value','--output','tsv','--only-show-errors')
if ($secret.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($secret.Text)) { throw "Could not retrieve bootstrap secret from Key Vault. $($secret.Text)" }

if (-not $Apply) {
    Write-Host 'PREVIEW ONLY. Bootstrap secret is readable but no local bootstrap file was written.' -ForegroundColor Yellow
    return
}

$dir = Split-Path -Parent $BootstrapPath
New-Item -ItemType Directory -Path $dir -Force | Out-Null
$secure = ConvertTo-SecureString -String $secret.Text -AsPlainText -Force
$payload = [pscustomobject]@{
    TenantId     = $TenantId
    ClientId     = $ClientId
    ClientSecret = $secure
    CreatedAtUtc = [datetime]::UtcNow
}
$temp = "$BootstrapPath.tmp"
$payload | Export-Clixml -LiteralPath $temp -Force
$verify = Import-Clixml -LiteralPath $temp
if (-not $verify.ClientSecret -or [string]$verify.ClientId -ne $ClientId) { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue; throw 'Bootstrap verification failed.' }
Move-Item -LiteralPath $temp -Destination $BootstrapPath -Force
$secret = $null
$secure = $null
Write-Host 'PASS: DPAPI-protected Azure service-principal bootstrap created for the current Windows user.' -ForegroundColor Green
Write-Host 'This removes interactive Azure CLI dependency, but remains intentionally user-bound for UAT.' -ForegroundColor Yellow