#requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Fa-f0-9]{64}$')]
    [string]$ExpectedSha256
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch = 'feature/phase-3-record-documents'
$TenantId = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment = 'Sandbox_08142026_GamerDocs'
$ApplicationFamily = 'BusinessCentral'
$AdminApiVersion = 'v2.29'
$AppId = 'bca2cd58-6708-4b42-bff3-05dc11c8f790'
$AppName = 'GPI Zetadocs Pilot Bridge'
$TargetVersion = '0.1.0.21'
$BridgeRoot = Join-Path $RepoRoot 'bc-extension\gpi-zetadocs-pilot-bridge'
$AppJson = Join-Path $BridgeRoot 'app.json'
$TaskPath = Join-Path $BridgeRoot 'src\codeunit\GPIZetadocsAutoMigrationTask.Codeunit.al'
$PackagePath = Join-Path $BridgeRoot "Gamer Packaging_GPI Zetadocs Pilot Bridge_$TargetVersion.app"

function Section([string]$Name) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Name -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

function Convert-TokenToString($TokenValue) {
    if ($null -eq $TokenValue) { return $null }
    if ($TokenValue -is [string]) { return $TokenValue }
    if ($TokenValue -is [Security.SecureString]) {
        return [System.Net.NetworkCredential]::new('', $TokenValue).Password
    }
    return [string]$TokenValue
}

function Get-BcToken {
    if (-not (Get-Module -ListAvailable -Name Az.Accounts)) {
        throw 'Az.Accounts is not installed.'
    }

    Import-Module Az.Accounts -ErrorAction Stop
    $Ctx = Get-AzContext -ErrorAction SilentlyContinue
    if (($null -eq $Ctx) -or ($null -eq $Ctx.Account) -or ([string]$Ctx.Tenant.Id -ne $TenantId)) {
        Connect-AzAccount -Tenant $TenantId -AuthScope 'https://api.businesscentral.dynamics.com' | Out-Null
    }

    $Result = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
    $Token = Convert-TokenToString $Result.Token
    if ([string]::IsNullOrWhiteSpace($Token)) { throw 'Business Central access token was empty.' }
    return $Token
}

function Get-AdminAppRecord([string]$Token) {
    $EnvEncoded = [uri]::EscapeDataString($Environment)
    $FamilyEncoded = [uri]::EscapeDataString($ApplicationFamily)
    $Uri = "https://api.businesscentral.dynamics.com/admin/$AdminApiVersion/applications/$FamilyEncoded/environments/$EnvEncoded/apps/$AppId"
    Invoke-RestMethod -Method Get -Uri $Uri -Headers @{ Authorization = "Bearer $Token"; Accept = 'application/json' } -ErrorAction Stop
}

Section '1. HARD SAFETY / PACKAGE PROOF'

if ($Environment -ne 'Sandbox_08142026_GamerDocs' -or $Environment -match '(?i)prod|production') {
    throw "SAFETY STOP: unexpected or Production-like environment '$Environment'."
}

$Branch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not determine current Git branch.' }
if ($Branch -ne $ExpectedBranch) { throw "Expected branch '$ExpectedBranch', found '$Branch'." }

foreach ($Path in @($BridgeRoot,$AppJson,$TaskPath,$PackagePath)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Required path missing: $Path" }
}

$App = Get-Content -LiteralPath $AppJson -Raw | ConvertFrom-Json
if ([string]$App.id -ne $AppId) { throw "Unexpected app ID $($App.id)." }
if ([string]$App.name -ne $AppName) { throw "Unexpected app name '$($App.name)'." }
if ([string]$App.version -ne $TargetVersion) { throw "Expected local Bridge $TargetVersion, found $($App.version)." }

$Task = Get-Content -LiteralPath $TaskPath -Raw
foreach ($Marker in @(
    'StaleReferenceDateTime: DateTime;',
    'StaleReferenceLabel: Text[50];',
    'if State."Last Batch Date/Time" <> 0DT then begin',
    'StaleReferenceDateTime := State."Started Date/Time";',
    "StaleReferenceLabel := 'run start';",
    'StaleThreshold := 60 * 60 * 1000;',
    'if not IsNullGuid(State."Scheduled Task ID") then'
)) {
    if (-not $Task.Contains($Marker)) { throw "Bridge .21 recovery marker missing: $Marker" }
}

$ExpectedSha256 = $ExpectedSha256.ToUpperInvariant()
$ActualSha256 = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToUpperInvariant()
if ($ActualSha256 -ne $ExpectedSha256) {
    throw "Package SHA256 mismatch. Expected $ExpectedSha256, found $ActualSha256."
}

$Pkg = Get-Item -LiteralPath $PackagePath
Write-Host "Environment : $Environment"
Write-Host "App         : $AppName $TargetVersion"
Write-Host "Package     : $($Pkg.FullName)"
Write-Host "Bytes       : $($Pkg.Length)"
Write-Host "SHA256      : $ActualSha256"
Write-Host 'Production  : HARD BLOCKED' -ForegroundColor Green
Write-Host 'Data action : NONE'

Section '2. VERIFY CURRENT SANDBOX DEV SCOPE'

$Token = Get-BcToken
$Current = Get-AdminAppRecord -Token $Token

Write-Host "Installed version : $($Current.version)"
Write-Host "State             : $($Current.state)"
Write-Host "App type          : $($Current.appType)"
Write-Host "Last result       : $($Current.lastUpdateAttemptResult)"

if ([string]$Current.state -notmatch '(?i)^installed$') { throw "Current app state is '$($Current.state)'." }
if ([string]$Current.appType -notmatch '(?i)^dev$') { throw "Current app type is '$($Current.appType)', expected DEV." }
if ([version][string]$Current.version -gt [version]$TargetVersion) { throw "Installed bridge $($Current.version) is newer than target $TargetVersion." }

if ([string]$Current.version -eq $TargetVersion) {
    Write-Host 'Target bridge is already installed.' -ForegroundColor Green
    exit 0
}

if ([string]$Current.version -ne '0.1.0.20') {
    throw "Expected installed bridge 0.1.0.20 before .21, found $($Current.version)."
}

Section '3. PUBLISH .21 TO SAME DEV SCOPE'

$Token = Get-BcToken
$TenantEncoded = [uri]::EscapeDataString($TenantId)
$EnvironmentEncoded = [uri]::EscapeDataString($Environment)
$DevBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantEncoded/$EnvironmentEncoded/dev/apps"
$PublishUri = "$DevBase?SchemaUpdateMode=synchronize&DependencyPublishingOption=ignore"

Invoke-RestMethod `
    -Method Post `
    -Uri $PublishUri `
    -Headers @{ Authorization = "Bearer $Token"; Accept = 'application/json' } `
    -Form @{ file = $Pkg } `
    -ErrorAction Stop | Out-Null

Write-Host 'DEV publish request accepted.' -ForegroundColor Green

Section '4. VERIFY INSTALLED .21'

$Deadline = (Get-Date).AddMinutes(10)
$Verified = $false
$LastVersion = [string]$Current.version
$LastType = [string]$Current.appType

while ((Get-Date) -lt $Deadline) {
    Start-Sleep -Seconds 8
    $Token = Get-BcToken
    $Observed = Get-AdminAppRecord -Token $Token
    $LastVersion = [string]$Observed.version
    $LastType = [string]$Observed.appType

    Write-Host ("{0}  Version={1}  Type={2}  State={3}" -f (Get-Date -Format 'HH:mm:ss'),$LastVersion,$LastType,$Observed.state)

    if (($LastVersion -eq $TargetVersion) -and ($LastType -match '(?i)^dev$') -and ([string]$Observed.state -match '(?i)^installed$')) {
        $Verified = $true
        break
    }
}

if (-not $Verified) { throw "Publish accepted but .21 was not verified installed. Last seen $LastVersion / $LastType." }

Section '5. RESULT'
Write-Host 'BRIDGE .21 SANDBOX PUBLISH VERIFIED' -ForegroundColor Green
Write-Host "Environment : $Environment"
Write-Host "Installed   : $AppName $TargetVersion"
Write-Host "Scope       : DEV"
Write-Host "SHA256      : $ActualSha256"
Write-Host 'Production  : NOT TOUCHED'
Write-Host 'Routing     : NOT CHANGED'
Write-Host 'Migration data: NOT CHANGED BY PUBLISH SCRIPT'
