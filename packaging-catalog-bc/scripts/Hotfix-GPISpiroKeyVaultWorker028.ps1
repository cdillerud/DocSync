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
$singleWorker = Join-Path $ProjectPath 'scripts\Process-GPISpiroPushQueueUAT.ps1'
$kvLifecycle = Join-Path $ProjectPath 'scripts\Update-GPISpiroKeyVaultTokenUAT.ps1'
$kvSeed = Join-Path $ProjectPath 'scripts\Seed-GPISpiroKeyVaultAccessTokenUAT.ps1'

foreach ($file in @($appJson, $opsWorker, $singleWorker, $kvLifecycle, $kvSeed)) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Required partially-applied 0.28 file not found: $file"
    }
}

Write-Host "`n== PRECHECK PARTIAL 0.28 ==" -ForegroundColor Cyan
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.28.0.0') {
    throw "Expected local app version 0.28.0.0. Found $($app.version)."
}
$opsRaw = Get-Content -LiteralPath $opsWorker -Raw
if (-not $opsRaw.Contains('SPIRO KEY VAULT TOKEN LIFECYCLE')) {
    throw 'Expected operational worker Key Vault lifecycle patch was not found.'
}
Write-Host 'Partial 0.28 state confirmed.' -ForegroundColor Green

Write-Host "`n== PATCH SINGLE WORKER TO READ ACCESS TOKEN FROM KEY VAULT ==" -ForegroundColor Cyan
$singleText = Get-Content -LiteralPath $singleWorker -Raw

if (-not $singleText.Contains('[string]$KeyVaultName = "kv-gbca-bacf30f9",')) {
    throw 'Single worker KeyVaultName parameter was not found.'
}

$dpapiPattern = '(?s)if \(-not \(Test-Path -LiteralPath \$TokenStorePath\)\) \{ throw "Spiro token store not found: \$TokenStorePath" \}\r?\n\$root = Import-Clixml -LiteralPath \$TokenStorePath\r?\n\$container = Get-TokenContainer -Root \$root\r?\n\$spiroToken = Convert-SecretValueToText -Value \(Get-PropertyValue \$container @\(''AccessToken'',''access_token'',''accessToken'',''Token''\)\)\r?\nif \(\[string\]::IsNullOrWhiteSpace\(\$spiroToken\)\) \{ throw ''No Spiro access token found\.'' \}'

$kvReadBlock = @'
$spiroToken = (& az keyvault secret show --vault-name $KeyVaultName --name 'spiro-oauth-access-token' --query value --output tsv --only-show-errors).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($spiroToken)) {
    throw 'No Spiro access token could be retrieved from Key Vault.'
}
'@

if ($singleText.Contains("--name 'spiro-oauth-access-token'")) {
    Write-Host 'Already present: single worker Key Vault access-token read.' -ForegroundColor DarkYellow
}
elseif ([regex]::IsMatch($singleText, $dpapiPattern)) {
    $singleText = [regex]::Replace(
        $singleText,
        $dpapiPattern,
        ($kvReadBlock -replace "`n", "`r`n").TrimEnd(),
        1
    )
    Save-Utf8NoBom -Path $singleWorker -Content $singleText
    Write-Host "Patched: $singleWorker" -ForegroundColor DarkGreen
}
else {
    throw 'Could not locate the exact DPAPI access-token read block in the single queue worker.'
}

Write-Host "`n== VALIDATE 0.28 KEY VAULT WORKER DECOUPLING ==" -ForegroundColor Cyan
$checks = @(
    @{ Path=$appJson; Pattern='"version": "0.28.0.0"'; Label='0.28 app version' },
    @{ Path=$kvSeed; Pattern='spiro-oauth-access-token'; Label='Key Vault access-token seed' },
    @{ Path=$kvSeed; Pattern='spiro-oauth-expires-at-utc'; Label='Key Vault expiry seed' },
    @{ Path=$kvLifecycle; Pattern="grant_type    = 'refresh_token'"; Label='Key Vault refresh grant' },
    @{ Path=$kvLifecycle; Pattern='spiro-oauth-access-token'; Label='refreshed access-token persistence' },
    @{ Path=$kvLifecycle; Pattern='spiro-oauth-expires-at-utc'; Label='expiry persistence' },
    @{ Path=$opsWorker; Pattern='SPIRO KEY VAULT TOKEN LIFECYCLE'; Label='operational Key Vault lifecycle' },
    @{ Path=$singleWorker; Pattern="--name 'spiro-oauth-access-token'"; Label='single worker Key Vault token read' }
)

foreach ($check in $checks) {
    $raw = Get-Content -LiteralPath $check.Path -Raw
    if (-not $raw.Contains($check.Pattern)) {
        throw "Validation failed: $($check.Label)"
    }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

$singleRaw = Get-Content -LiteralPath $singleWorker -Raw
if ($singleRaw.Contains('Import-Clixml -LiteralPath $TokenStorePath')) {
    throw 'Validation failed: single worker still imports DPAPI token store.'
}
Write-Host 'PASS: single worker no longer imports DPAPI token store' -ForegroundColor Green

Write-Host "`n0.28 Key Vault worker decoupling hotfix applied successfully." -ForegroundColor Green
Write-Host 'Existing scheduled task definition was not changed.' -ForegroundColor Yellow
Write-Host 'Next: rebuild 0.28, seed current access token/expiry to Key Vault, then run controlled worker UAT.' -ForegroundColor Cyan
