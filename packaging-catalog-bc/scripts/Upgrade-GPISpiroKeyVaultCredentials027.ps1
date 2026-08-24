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
$initScript = Join-Path $ProjectPath 'scripts\Initialize-GPISpiroKeyVaultCredentialsUAT.ps1'
$testScript = Join-Path $ProjectPath 'scripts\Test-GPISpiroKeyVaultRefreshUAT.ps1'

if (-not (Test-Path -LiteralPath $appJson)) {
    throw "app.json not found: $appJson"
}

Write-Host "`n== PRECHECK 0.26 ==" -ForegroundColor Cyan
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.26.0.0') {
    throw "Expected local app version 0.26.0.0. Found $($app.version)."
}
Write-Host '0.26 local app confirmed.' -ForegroundColor Green

Write-Host "`n== BUMP APP VERSION TO 0.27.0.0 ==" -ForegroundColor Cyan
$appText = Get-Content -LiteralPath $appJson -Raw
$oldVersion = '"version": "0.26.0.0"'
$newVersion = '"version": "0.27.0.0"'
if (-not $appText.Contains($oldVersion)) {
    throw '0.26 app version text was not found in app.json.'
}
$appText = $appText.Replace($oldVersion, $newVersion)
Save-Utf8NoBom -Path $appJson -Content $appText
Write-Host "Patched: $appJson" -ForegroundColor DarkGreen

Write-Host "`n== CREATE KEY VAULT CREDENTIAL INITIALIZER ==" -ForegroundColor Cyan
$initText = @'
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
'@
Save-Utf8NoBom -Path $initScript -Content $initText
Write-Host "Created: $initScript" -ForegroundColor DarkGreen

Write-Host "`n== CREATE KEY VAULT REFRESH TEST ==" -ForegroundColor Cyan
$testText = @'
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
'@
Save-Utf8NoBom -Path $testScript -Content $testText
Write-Host "Created: $testScript" -ForegroundColor DarkGreen

Write-Host "`n== VALIDATE 0.27 KEY VAULT FOUNDATION ==" -ForegroundColor Cyan
$checks = @(
    @{ Path=$appJson; Pattern='"version": "0.27.0.0"'; Label='0.27 app version' },
    @{ Path=$initScript; Pattern='PREVIEW ONLY. No Key Vault secrets were created or changed.'; Label='safe initializer preview' },
    @{ Path=$initScript; Pattern='spiro-oauth-refresh-token'; Label='refresh token Key Vault target' },
    @{ Path=$initScript; Pattern="--value '@-'"; Label='stdin secret write' },
    @{ Path=$testScript; Pattern="grant_type    = 'refresh_token'"; Label='Key Vault refresh grant' },
    @{ Path=$testScript; Pattern="Rotated refresh token saved to Key Vault."; Label='refresh token rotation persistence' },
    @{ Path=$testScript; Pattern='No token or secret values are displayed.'; Label='secret-safe output' }
)
foreach ($check in $checks) {
    $raw = Get-Content -LiteralPath $check.Path -Raw
    if (-not $raw.Contains($check.Pattern)) {
        throw "Validation failed: $($check.Label)"
    }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host ''
Write-Host '0.27 Spiro Key Vault credential foundation applied successfully.' -ForegroundColor Green
Write-Host 'No Key Vault secrets were created by this upgrade helper.' -ForegroundColor Yellow
Write-Host 'The live scheduled worker still uses the validated 0.26 DPAPI path until Key Vault UAT passes.' -ForegroundColor Yellow
