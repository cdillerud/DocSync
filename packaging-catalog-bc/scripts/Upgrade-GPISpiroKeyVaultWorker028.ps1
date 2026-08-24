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

foreach ($file in @($appJson, $opsWorker, $singleWorker)) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Required 0.27 file not found: $file"
    }
}

Write-Host "`n== PRECHECK 0.27 ==" -ForegroundColor Cyan
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.27.0.0') {
    throw "Expected local app version 0.27.0.0. Found $($app.version)."
}
Write-Host '0.27 local app confirmed.' -ForegroundColor Green

Write-Host "`n== BUMP APP VERSION TO 0.28.0.0 ==" -ForegroundColor Cyan
$appText = Get-Content -LiteralPath $appJson -Raw
$oldVersion = '"version": "0.27.0.0"'
$newVersion = '"version": "0.28.0.0"'
if (-not $appText.Contains($oldVersion)) {
    throw '0.27 app version text was not found in app.json.'
}
$appText = $appText.Replace($oldVersion, $newVersion)
Save-Utf8NoBom -Path $appJson -Content $appText
Write-Host "Patched: $appJson" -ForegroundColor DarkGreen

Write-Host "`n== CREATE KEY VAULT ACCESS-TOKEN SEEDER ==" -ForegroundColor Cyan
$seedText = @'
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
'@
Save-Utf8NoBom -Path $kvSeed -Content $seedText
Write-Host "Created: $kvSeed" -ForegroundColor DarkGreen

Write-Host "`n== CREATE KEY VAULT TOKEN LIFECYCLE HELPER ==" -ForegroundColor Cyan
$lifecycleText = @'
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
'@
Save-Utf8NoBom -Path $kvLifecycle -Content $lifecycleText
Write-Host "Created: $kvLifecycle" -ForegroundColor DarkGreen

Write-Host "`n== PATCH OPERATIONAL WORKER TO KEY VAULT LIFECYCLE ==" -ForegroundColor Cyan
$opsText = Get-Content -LiteralPath $opsWorker -Raw
$oldBlockPattern = '(?s)    Write-Section ''SPIRO OAUTH TOKEN LIFECYCLE''.*?    Write-Section ''AUTHENTICATE TO BUSINESS CENTRAL'''
$newBlock = @'
    Write-Section 'SPIRO KEY VAULT TOKEN LIFECYCLE'
    $refreshHelper = Join-Path $PSScriptRoot 'Update-GPISpiroKeyVaultTokenUAT.ps1'
    if (-not (Test-Path -LiteralPath $refreshHelper)) {
        throw "Spiro Key Vault lifecycle helper not found: $refreshHelper"
    }
    $refreshArgs = @{
        RefreshWithinMinutes = 120
        KeyVaultName         = $KeyVaultName
        TimeoutSeconds       = $TimeoutSeconds
    }
    if ($Apply) { $refreshArgs.Apply = $true }
    & $refreshHelper @refreshArgs

    Write-Section 'AUTHENTICATE TO BUSINESS CENTRAL'
'@
if ($opsText -match "SPIRO KEY VAULT TOKEN LIFECYCLE") {
    Write-Host 'Already present: Key Vault lifecycle integration.' -ForegroundColor DarkYellow
}
elseif ([regex]::IsMatch($opsText, $oldBlockPattern)) {
    $opsText = [regex]::Replace($opsText, $oldBlockPattern, ($newBlock -replace "`n","`r`n").TrimEnd(), 1)
    Save-Utf8NoBom -Path $opsWorker -Content $opsText
    Write-Host "Patched: $opsWorker" -ForegroundColor DarkGreen
}
else {
    throw 'Could not locate the 0.26 DPAPI OAuth lifecycle block in the operational worker.'
}

Write-Host "`n== PATCH SINGLE WORKER TO READ ACCESS TOKEN FROM KEY VAULT ==" -ForegroundColor Cyan
$singleText = Get-Content -LiteralPath $singleWorker -Raw
if ($singleText -notmatch "\[string\]\$KeyVaultName") {
    $singleText = $singleText.Replace(
        '[string]$KeyVaultName = "kv-gbca-bacf30f9",',
        '[string]$KeyVaultName = "kv-gbca-bacf30f9",'
    )
}
$dpapiPattern = '(?s)if \(-not \(Test-Path -LiteralPath \$TokenStorePath\)\).*?\$spiroToken = Convert-SecretValueToText -Value \(Get-PropertyValue \$container @\(''AccessToken'',''access_token'',''accessToken'',''Token''\)\)\r?\nif \(\[string\]::IsNullOrWhiteSpace\(\$spiroToken\)\) \{ throw ''No Spiro access token found\.'' \}'
$kvReadBlock = @'
$spiroToken = (& az keyvault secret show --vault-name $KeyVaultName --name 'spiro-oauth-access-token' --query value --output tsv --only-show-errors).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($spiroToken)) {
    throw 'No Spiro access token could be retrieved from Key Vault.'
}
'@
if ($singleText -match "spiro-oauth-access-token") {
    Write-Host 'Already present: single worker Key Vault access-token read.' -ForegroundColor DarkYellow
}
elseif ([regex]::IsMatch($singleText, $dpapiPattern)) {
    $singleText = [regex]::Replace($singleText, $dpapiPattern, ($kvReadBlock -replace "`n","`r`n").TrimEnd(), 1)
    Save-Utf8NoBom -Path $singleWorker -Content $singleText
    Write-Host "Patched: $singleWorker" -ForegroundColor DarkGreen
}
else {
    throw 'Could not locate DPAPI access-token read block in single queue worker.'
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
    if (-not $raw.Contains($check.Pattern)) { throw "Validation failed: $($check.Label)" }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

$singleRaw = Get-Content -LiteralPath $singleWorker -Raw
if ($singleRaw.Contains('Import-Clixml -LiteralPath $TokenStorePath')) {
    throw 'Validation failed: single worker still imports DPAPI token store.'
}
Write-Host 'PASS: single worker no longer imports DPAPI token store' -ForegroundColor Green

Write-Host ''
Write-Host '0.28 Key Vault worker decoupling applied successfully.' -ForegroundColor Green
Write-Host 'Existing scheduled task definition was not changed.' -ForegroundColor Yellow
Write-Host 'Next: build 0.28, seed current access token/expiry to Key Vault, then run controlled worker UAT before changing task logon behavior.' -ForegroundColor Cyan
