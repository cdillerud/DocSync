[CmdletBinding()]
param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Save-Utf8NoBom {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][string]$Content)
    [System.IO.File]::WriteAllText($Path,$Content,[System.Text.UTF8Encoding]::new($false))
}

$appJson = Join-Path $ProjectPath 'app.json'
$opsWorker = Join-Path $ProjectPath 'scripts\Start-GPISpiroPushWorkerUAT.ps1'
$bootstrapInit = Join-Path $ProjectPath 'scripts\Initialize-GPIAzureServicePrincipalBootstrapUAT.ps1'
$bootstrapTest = Join-Path $ProjectPath 'scripts\Test-GPIAzureServicePrincipalBootstrapUAT.ps1'

foreach ($file in @($appJson,$opsWorker)) {
    if (-not (Test-Path -LiteralPath $file)) { throw "Required 0.29 file not found: $file" }
}

Write-Host "`n== PRECHECK 0.29 ==" -ForegroundColor Cyan
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.29.0.0') { throw "Expected local app version 0.29.0.0. Found $($app.version)." }
$opsRaw = Get-Content -LiteralPath $opsWorker -Raw
if (-not $opsRaw.Contains('SPIRO KEY VAULT TOKEN LIFECYCLE')) { throw '0.29 operational worker Key Vault lifecycle marker not found.' }
Write-Host '0.29 operational worker confirmed.' -ForegroundColor Green

Write-Host "`n== BUMP APP VERSION TO 0.30.0.0 ==" -ForegroundColor Cyan
$appText = Get-Content -LiteralPath $appJson -Raw
$appText = $appText.Replace('"version": "0.29.0.0"','"version": "0.30.0.0"')
if (-not $appText.Contains('"version": "0.30.0.0"')) { throw 'Could not bump app version to 0.30.0.0.' }
Save-Utf8NoBom -Path $appJson -Content $appText
Write-Host "Patched: $appJson" -ForegroundColor DarkGreen

Write-Host "`n== CREATE AZURE SERVICE PRINCIPAL BOOTSTRAP INITIALIZER ==" -ForegroundColor Cyan
$initText = @'
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
'@
Save-Utf8NoBom -Path $bootstrapInit -Content $initText
Write-Host "Created: $bootstrapInit" -ForegroundColor DarkGreen

Write-Host "`n== CREATE AZURE BOOTSTRAP TEST ==" -ForegroundColor Cyan
$testText = @'
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
'@
Save-Utf8NoBom -Path $bootstrapTest -Content $testText
Write-Host "Created: $bootstrapTest" -ForegroundColor DarkGreen

Write-Host "`n== PATCH OPERATIONAL WORKER WITH NONINTERACTIVE AZURE LOGIN ==" -ForegroundColor Cyan
$opsText = Get-Content -LiteralPath $opsWorker -Raw
if (-not $opsText.Contains('AZURE SERVICE PRINCIPAL BOOTSTRAP LOGIN')) {
$marker = "    Write-Section 'SPIRO KEY VAULT TOKEN LIFECYCLE'"
$insert = @'
    Write-Section 'AZURE SERVICE PRINCIPAL BOOTSTRAP LOGIN'
    $bootstrapPath = "$env:LOCALAPPDATA\GPI\AzureBootstrap\gpi-azure-sp-uat.clixml"
    if (-not (Test-Path -LiteralPath $bootstrapPath)) { throw "Azure service-principal bootstrap not found: $bootstrapPath" }
    $bootstrap = Import-Clixml -LiteralPath $bootstrapPath
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($bootstrap.ClientSecret)
    try {
        $bootstrapSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        $loginOutput = & az login --service-principal --username $bootstrap.ClientId --password $bootstrapSecret --tenant $bootstrap.TenantId --allow-no-subscriptions --output none --only-show-errors 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Azure service-principal login failed. $(@($loginOutput)-join [Environment]::NewLine)" }
    }
    finally {
        if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
        $bootstrapSecret = $null
    }
    Write-Host 'PASS: noninteractive Azure service-principal login succeeded.' -ForegroundColor Green

    Write-Section 'SPIRO KEY VAULT TOKEN LIFECYCLE'
'@
if (-not $opsText.Contains($marker)) { throw 'Could not find Key Vault lifecycle marker in operational worker.' }
$opsText = $opsText.Replace($marker,($insert -replace "`n","`r`n").TrimEnd())
Save-Utf8NoBom -Path $opsWorker -Content $opsText
Write-Host "Patched: $opsWorker" -ForegroundColor DarkGreen
} else { Write-Host 'Already present: Azure service-principal bootstrap login.' -ForegroundColor DarkYellow }

Write-Host "`n== VALIDATE 0.30 ==" -ForegroundColor Cyan
$checks=@(
 @{Path=$appJson;Pattern='"version": "0.30.0.0"';Label='0.30 app version'},
 @{Path=$bootstrapInit;Pattern='Export-Clixml';Label='DPAPI bootstrap persistence'},
 @{Path=$bootstrapInit;Pattern='PREVIEW ONLY';Label='safe bootstrap preview'},
 @{Path=$bootstrapTest;Pattern='--service-principal';Label='bootstrap service-principal login test'},
 @{Path=$opsWorker;Pattern='AZURE SERVICE PRINCIPAL BOOTSTRAP LOGIN';Label='operational bootstrap login'},
 @{Path=$opsWorker;Pattern='--service-principal';Label='noninteractive Azure login'}
)
foreach($c in $checks){$raw=Get-Content -LiteralPath $c.Path -Raw;if(-not $raw.Contains($c.Pattern)){throw "Validation failed: $($c.Label)"};Write-Host "PASS: $($c.Label)" -ForegroundColor Green}
Write-Host ''
Write-Host '0.30 unattended Azure bootstrap applied successfully.' -ForegroundColor Green
Write-Host 'Existing scheduled tasks were not enabled or changed.' -ForegroundColor Yellow
Write-Host 'Next: build, initialize bootstrap, test bootstrap login, then rerun controlled unattended task.' -ForegroundColor Cyan
