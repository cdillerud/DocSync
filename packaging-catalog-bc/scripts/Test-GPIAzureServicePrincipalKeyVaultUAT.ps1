[CmdletBinding()]
param(
    [string]$TenantId = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc',
    [string]$ClientId = '6ac62e44-8968-4ad9-b781-434507a5c83a',
    [string]$KeyVaultName = 'kv-gbca-bacf30f9',
    [string]$BootstrapSecretName = 'bc-client-secret'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-AzText {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & az @Arguments 2>&1
    $exit = $LASTEXITCODE
    $text = (@($output) -join [Environment]::NewLine).Trim()

    [pscustomobject]@{
        ExitCode = $exit
        Text     = $text
    }
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI (az) is required.'
}

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'GPI AZURE SERVICE PRINCIPAL KEY VAULT PREFLIGHT UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Tenant ID       : $TenantId"
Write-Host "Client ID       : $ClientId"
Write-Host "Key Vault       : $KeyVaultName"
Write-Host 'No secret values are displayed.' -ForegroundColor Green

$current = Invoke-AzText @('account','show','--query','{user:user.name,type:user.type,tenantId:tenantId}','--output','json','--only-show-errors')
if ($current.ExitCode -ne 0) {
    throw "Current Azure CLI context is unavailable: $($current.Text)"
}
Write-Host 'PASS: current interactive Azure CLI context is available.' -ForegroundColor Green

$secretResult = Invoke-AzText @('keyvault','secret','show','--vault-name',$KeyVaultName,'--name',$BootstrapSecretName,'--query','value','--output','tsv','--only-show-errors')
if ($secretResult.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($secretResult.Text)) {
    throw "Could not retrieve bootstrap client secret from Key Vault using the current interactive Azure context. $($secretResult.Text)"
}
$clientSecret = $secretResult.Text

try {
    $logout = Invoke-AzText @('logout')

    $login = Invoke-AzText @('login','--service-principal','--username',$ClientId,'--password',$clientSecret,'--tenant',$TenantId,'--allow-no-subscriptions','--output','none','--only-show-errors')
    if ($login.ExitCode -ne 0) {
        throw "Service-principal Azure login failed. $($login.Text)"
    }
    Write-Host 'PASS: service-principal Azure login succeeded.' -ForegroundColor Green

    $spContext = Invoke-AzText @('account','show','--query','{user:user.name,type:user.type,tenantId:tenantId}','--output','json','--only-show-errors')
    if ($spContext.ExitCode -ne 0) {
        throw "Could not inspect service-principal Azure context. $($spContext.Text)"
    }
    Write-Host 'PASS: service-principal Azure context is active.' -ForegroundColor Green

    $kvTest = Invoke-AzText @('keyvault','secret','show','--vault-name',$KeyVaultName,'--name','spiro-oauth-client-id','--query','id','--output','tsv','--only-show-errors')
    if ($kvTest.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($kvTest.Text)) {
        Write-Host 'FAIL: service principal authenticated but cannot read Key Vault secrets.' -ForegroundColor Red
        Write-Host $kvTest.Text -ForegroundColor Yellow
        exit 2
    }

    Write-Host 'PASS: service principal can read required Key Vault secrets.' -ForegroundColor Green
    Write-Host 'RESULT: Azure service principal is suitable for unattended worker authentication.' -ForegroundColor Green
}
finally {
    $clientSecret = $null
    $null = Invoke-AzText @('logout')
    Write-Host 'Azure CLI service-principal session logged out.' -ForegroundColor Yellow
    Write-Host 'Run az login interactively afterward if you need to restore your user Azure CLI session.' -ForegroundColor Yellow
}
